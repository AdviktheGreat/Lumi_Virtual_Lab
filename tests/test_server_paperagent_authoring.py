"""Tests of what the server says to the person who wrote a paper, from what is kept of its agent: that nothing is
claimed of code that was not fetched, what each step that was run says to a reader and each that was not is said not to
have been, what the imports of the code are held against, that files that are not the project's own are not read, and
what is in the package that is made. Git, Docker, and the containers are replaced by stand-ins, as in the tests of
making the tools; what the findings are made of is in test_paperagents_authoring."""

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any

import pytest
import test_server_paperagent_environment as environment_tests
import test_server_paperagent_library as library_tests
import test_server_paperagent_reproduction as reproduction_tests
import test_server_paperagent_tools as tools
from conftest import FakeClient
from fastapi.testclient import TestClient
from test_paperagents_reference import failure_of, result_of
from test_server_paperagent_reference import NOTEBOOK, SCRIPT, writes
from test_server_paperagent_repository import COMMIT, URL, Remote, agent_of, directory_of, fetch, refused

from virtual_lab.paperagents import authoring as pure
from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import exporting
from virtual_lab.server import paperagent_authoring as authoring
from virtual_lab.server import paperagent_environment as kept_environment
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server.paperagents import PaperAgents
from virtual_lab.server.workspace import Workspace

# What the tests of the library are made with, which are fixtures of that module and of the ones before it
agents = tools.agents
client = tools.client
containers = tools.containers
docker = tools.docker
git_is_installed = tools.git_is_installed
jobs = tools.jobs
marker = tools.marker
prepared = tools.prepared
referenced = tools.referenced
remote = tools.remote
replays = tools.replays
workspace = tools.workspace
made = library_tests.made
packages = library_tests.packages
small_chunks = reproduction_tests.small_chunks
built = reproduction_tests.built
ran = reproduction_tests.ran
ready = reproduction_tests.ready
Docker = tools.Docker
Containers = tools.Containers
Packages = library_tests.Packages

ANALYSIS = "import numpy\nimport scanpy as sc\nfrom cellmapper import mapping\n"
STEPS = ("reading", "repository", "environment", "reference", "reproduction")


def view(agents: PaperAgents, agent_id: str) -> dict[str, Any]:
    return authoring.view(agents, agent_id)


def findings_of(agents: PaperAgents, agent_id: str) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in view(agents, agent_id)["findings"]}


def steps_not_run(agents: PaperAgents, agent_id: str) -> list[str]:
    return [item["id"] for item in view(agents, agent_id)["not_checked"]]


def package_of(agents: PaperAgents, agent_id: str) -> zipfile.ZipFile:
    _, content = authoring.package(agents, agent_id)

    return zipfile.ZipFile(io.BytesIO(content))


def names_in(archive: zipfile.ZipFile) -> list[str]:
    folders = {name.split("/")[0] for name in archive.namelist()}
    assert len(folders) == 1, folders

    return sorted(name.split("/", 1)[1] for name in archive.namelist())


@pytest.fixture
def fetched(agents: PaperAgents, remote: Remote, docker: Docker, containers: Containers) -> str:
    """An agent whose code has been fetched, whose code imports a package that its environment file does not name."""
    remote.files = {**remote.files, "analysis.py": ANALYSIS, SCRIPT: "print(1)\n"}
    agent_id = agent_of(agents)
    fetch(agents, agent_id)

    return agent_id


class TestBeforeTheCodeIsFetched:
    def test_nothing_is_known_and_the_steps_that_would_say_more_are_given(self, agents: PaperAgents) -> None:
        agent_id = agent_of(agents)

        found = view(agents, agent_id)

        assert (found["id"], found["title"], found["verdict"]) == (agent_id, "CellMapper", "not_checked")
        assert "has not been fetched" in found["summary"]
        assert [item["id"] for item in found["findings"]] == ["data_unread"]
        assert found["counts"] == {"block": 0, "warn": 0, "note": 1}
        assert [(item["id"], item["how"]) for item in found["not_checked"]] == [
            ("reading", f"POST /api/paperagents/{agent_id}/reading"),
            ("repository", f"POST /api/paperagents/{agent_id}/repository"),
        ]
        assert found["steps"] == {
            "read": False,
            "code": False,
            "environment": False,
            "tutorials": False,
            "claims": False,
        }
        assert found["package"] == {"ready": False, "files": [], "carries_tools": False}
        assert "Code: not fetched, so nothing below is known." in found["card"]
        assert "[Code availability: give where the code can be had.]" in found["statement"]

    def test_there_is_no_package_to_make_of_nothing(self, agents: PaperAgents) -> None:
        error = refused(authoring.package, agents, agent_of(agents))

        assert (error.status, error.code) == (409, "not_ready")
        assert "has not been fetched" in error.message

    def test_an_agent_that_is_not_there_is_refused(self, agents: PaperAgents) -> None:
        for call in (authoring.view, authoring.package):
            assert (refused(call, agents, "nothing").status, refused(call, agents, "nothing").code) == (
                404,
                "not_found",
            )


class TestWhatTheCodeSaysBeforeAnythingIsBuilt:
    def test_the_checks_made_of_the_files_are_said_as_what_a_reader_would_hit(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        remote.files = {"README.md": "# Plain\n", "run.py": "path = '/Users/me/lab/data.csv'\nprint(path)\n"}
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        found = findings_of(agents, agent_id)

        assert found["license"]["severity"] == "warn" and found["license"]["area"] == "license"
        assert found["environment"]["fix"] and found["tutorials"]["fix"]
        assert found["build_unsupported"]["severity"] == "note"
        assert "no_environment" not in found["build_unsupported"]["detail"]

    def test_a_project_that_was_fetched_and_not_built_says_so_and_is_not_ready(
        self, agents: PaperAgents, fetched: str
    ) -> None:
        found = view(agents, fetched)

        assert found["verdict"] in ("to_fix", "unfinished") and found["steps"]["code"] is True
        assert found["findings"][-1]["id"] == "build_not_built" or "build_not_built" in {
            item["id"] for item in found["findings"]
        }
        assert steps_not_run(agents, fetched)[-1] == "environment"

    def test_docker_that_is_not_running_is_said_as_why_it_was_not_built(
        self, agents: PaperAgents, fetched: str, docker: Docker
    ) -> None:
        docker.usable = (False, "Docker is not running.")

        assert findings_of(agents, fetched)["build_not_built"]["detail"] == "Docker is not running."

    def test_the_imports_of_the_code_are_held_against_the_files_that_say_what_to_install(
        self, agents: PaperAgents, fetched: str
    ) -> None:
        found = findings_of(agents, fetched)["requirements"]

        assert (found["severity"], found["area"]) == ("warn", "environment")
        assert found["where"] == ["scanpy: analysis.py"]
        assert "1 imports" in found["detail"]

    def test_an_import_in_a_notebook_counts_and_a_test_or_the_project_itself_does_not(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        notebook = json.dumps(
            {
                "cells": [
                    {"cell_type": "code", "source": ["%matplotlib inline\n", "import seaborn\n", "import cellmapper"]}
                ]
            }
        )
        remote.files = {
            **remote.files,
            "notebooks/plot.ipynb": notebook,
            "tests/test_x.py": "import pytest\nimport hypothesis\n",
            "setup.py": "import setuptools\nimport versioneer\n",
        }
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        assert findings_of(agents, agent_id)["requirements"]["where"] == ["seaborn: notebooks/plot.ipynb"]

    def test_a_project_with_no_file_that_says_what_to_install_is_not_asked_for_its_imports(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        remote.files = {"README.md": "# Plain\n", "analysis.py": ANALYSIS}
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        found = findings_of(agents, agent_id)
        assert "requirements" not in found and found["environment"]["severity"] in ("warn", "block")

    def test_a_file_too_large_to_be_what_a_person_wrote_is_not_read(self, agents: PaperAgents, remote: Remote) -> None:
        remote.files = {
            **remote.files,
            "generated.py": "import scanpy\n" + "x = 1\n" * authoring.MAX_CODE_BYTES,
        }
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        assert "requirements" not in findings_of(agents, agent_id)

    def test_a_link_in_the_project_is_not_followed_to_what_it_points_to(
        self, agents: PaperAgents, workspace: Workspace, remote: Remote, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside.py"
        outside.write_text("import scanpy\n")
        agent_id = agent_of(agents)
        fetch(agents, agent_id)
        os.symlink(outside, directory_of(workspace, agent_id) / "repo" / "linked.py")

        assert "requirements" not in findings_of(agents, agent_id)

    def test_a_path_that_was_edited_to_leave_the_project_is_not_read(
        self, agents: PaperAgents, workspace: Workspace, remote: Remote
    ) -> None:
        remote.files = {**remote.files, "analysis.py": ANALYSIS}
        agent_id = agent_of(agents)
        fetch(agents, agent_id)
        directory = directory_of(workspace, agent_id)
        (directory / "outside.txt").write_text("scanpy\n")
        path = directory / kept_repository.INTAKE_FILE
        record = json.loads(path.read_text())
        record["stock"]["environment"].append({"path": "../outside.txt", "kind": "pip", "pins": None})
        path.write_text(json.dumps(record))

        assert findings_of(agents, agent_id)["requirements"]["where"] == ["scanpy: analysis.py"]

    def test_nothing_is_run_and_no_model_is_asked(
        self,
        agents: PaperAgents,
        fetched: str,
        marker: Path,
        docker: Docker,
        containers: Containers,
        fake_client: FakeClient,
    ) -> None:
        view(agents, fetched)
        authoring.package(agents, fetched)

        assert not marker.exists() and docker.builds == [] and containers.runs == []
        assert fake_client.completions.parse_calls == [] and fake_client.completions.calls == []


class TestWhatTheBuildSays:
    def failure(self) -> building.EnvironmentBuildError:
        return building.EnvironmentBuildError(
            building.classify(
                f"Collecting x\n{environment_tests.FAILING_INSTALL}\nerror: subprocess-exited-with-error", "project", 1
            )
        )

    def test_a_build_that_failed_stops_a_reader_and_blocks_the_project(
        self, agents: PaperAgents, fetched: str, docker: Docker
    ) -> None:
        docker.error = self.failure()
        environment_tests.build(agents, fetched)

        found = view(agents, fetched)

        assert found["verdict"] == "blocked" and found["counts"]["block"] == 1
        build = findings_of(agents, fetched)["build"]
        assert build["title"].startswith("The environment does not build:") and build["severity"] == "block"
        assert "zlib1g-dev" in build["fix"]
        assert found["findings"][0]["id"] == "build"
        assert "environment" in steps_not_run(agents, fetched)

    def test_a_build_that_works_afterwards_takes_the_finding_away(
        self, agents: PaperAgents, fetched: str, docker: Docker
    ) -> None:
        docker.error = self.failure()
        environment_tests.build(agents, fetched)
        docker.error = None
        environment_tests.build(agents, fetched)

        found = findings_of(agents, fetched)

        assert "build" not in found and "build_not_built" not in found
        assert steps_not_run(agents, fetched) == ["reading", "reference"]

    def test_a_failure_that_is_older_than_what_was_built_is_not_said(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        environment_tests.build(agents, fetched)
        directory = directory_of(workspace, fetched)
        built = kept_environment.load(directory, COMMIT)
        assert built is not None
        old = {
            "schema": 1,
            "commit": COMMIT,
            "failed_at": "2000-01-01T00:00:00Z",
            "recipe": built["recipe"],
            "limits": built["limits"],
            "failure": {"kind": "timeout", "title": "Too slow", "detail": "It was.", "tail": []},
        }
        (kept_environment.env_path(directory) / kept_environment.FAILURE_FILE).write_text(json.dumps(old))

        assert "build" not in findings_of(agents, fetched)

    def test_packages_that_conflict_are_a_warning(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        environment_tests.build(agents, fetched)
        path = kept_environment.env_path(directory_of(workspace, fetched)) / kept_environment.RECORD_FILE
        record = json.loads(path.read_text())
        record["pip_check"] = {"ok": False, "problems": ["a 1.0 requires b>=2, which is not installed"]}
        path.write_text(json.dumps(record))

        found = findings_of(agents, fetched)

        assert found["pip_check"]["severity"] == "warn"

    def test_a_project_that_cannot_be_built_here_does_not_ask_for_steps_that_cannot_be_run(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        remote.files = {"README.md": "# R\n", "DESCRIPTION": "Package: x\n", "analysis.R": "x <- 1\n"}
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        found = view(agents, agent_id)

        assert found["steps"]["environment"] is True and "build_unsupported" in findings_of(agents, agent_id)
        assert steps_not_run(agents, agent_id) == ["reading"]


class TestWhatTheTutorialsSay:
    def test_tutorials_that_ran_to_the_end_say_nothing_and_are_counted_in_the_card(
        self, agents: PaperAgents, referenced: str
    ) -> None:
        found = view(agents, referenced)

        assert not [item for item in found["findings"] if item["area"] == "examples" and item["severity"] != "note"]
        assert "2 run in the environment with no network" in found["card"]
        assert found["steps"]["tutorials"] is True and "reference" not in steps_not_run(agents, referenced)

    def test_one_that_did_not_run_to_the_end_is_a_warning_and_is_counted(
        self, agents: PaperAgents, prepared: str, containers: Containers
    ) -> None:
        containers.plays[NOTEBOOK] = writes(result_of(ok=False, error=failure_of("ValueError", message="boom")))
        containers.plays[SCRIPT] = writes(result_of(calls=tools.CALLS))
        tools.reference_run(agents, prepared)

        found = findings_of(agents, prepared)

        [broken] = [item for item in found.values() if item["id"].startswith("tutorial:")]
        assert broken["severity"] == "warn" and broken["where"] == [NOTEBOOK]
        assert "1 not" in view(agents, prepared)["card"]
        assert view(agents, prepared)["verdict"] == "to_fix"

    def test_a_reference_run_of_another_image_is_not_taken_for_this_one(
        self, agents: PaperAgents, workspace: Workspace, referenced: str
    ) -> None:
        directory = directory_of(workspace, referenced)
        path = directory / "checks" / "reference.json"
        record = json.loads(path.read_text())
        record["image_id"] = "sha256:" + "0" * 64
        path.write_text(json.dumps(record))

        found = view(agents, referenced)

        assert found["steps"]["tutorials"] is False and "reference" in steps_not_run(agents, referenced)
        assert "Not run here." in found["card"]


class TestWhatThePaperSays:
    def test_a_paper_that_was_not_read_says_that_its_data_was_not_looked_for(
        self, agents: PaperAgents, referenced: str
    ) -> None:
        found = findings_of(agents, referenced)

        assert found["data_unread"]["severity"] == "note"
        assert steps_not_run(agents, referenced)[0] == "reading"

    def test_once_it_is_read_that_is_not_said_and_the_numbers_are_the_step_that_is_left(
        self, agents: PaperAgents, ran: str, fake_client: FakeClient
    ) -> None:
        reproduction_tests.read_paper(agents, ran, fake_client)

        found = view(agents, ran)

        assert found["steps"]["read"] is True and "data_unread" not in findings_of(agents, ran)
        assert steps_not_run(agents, ran) == ["reproduction"]
        assert "Not tried against the code." in found["card"]

    def test_a_paper_that_was_read_and_has_no_numbers_to_try_leaves_no_step_undone(
        self, agents: PaperAgents, ran: str, fake_client: FakeClient
    ) -> None:
        reproduction_tests.read_paper(agents, ran, fake_client, claims=[])

        found = view(agents, ran)

        assert found["steps"]["claims"] is True and found["not_checked"] == []
        assert found["verdict"] in ("to_fix", "ready")

    def test_a_number_that_was_not_found_again_is_a_warning_and_the_card_has_what_came_of_each(
        self, agents: PaperAgents, ready: str, fake_client: FakeClient
    ) -> None:
        reproduction_tests.pick(fake_client, reproduction_tests.TALLY, reproduction_tests.AUROC)
        reproduction_tests.reproduce(agents, ready)

        found = view(agents, ready)

        warned = [item for item in found["findings"] if item["id"].startswith("claim:")]
        assert [(item["severity"], item["area"]) for item in warned] == [("warn", "claims")]
        assert "0.88" in warned[0]["title"] and "Seurat" in warned[0]["detail"]
        assert found["steps"]["claims"] is True and "reproduction" not in steps_not_run(agents, ready)
        assert "1 reproduced, 0 partly, 1 not reproduced, 3 not attempted" in found["card"]
        assert "| 0.93 | reproduced |" in found["card"] and "| 0.88 | not reproduced |" in found["card"]

    def test_what_was_tried_of_another_paper_or_code_is_not_said(
        self, agents: PaperAgents, ready: str, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        reproduction_tests.pick(fake_client, reproduction_tests.TALLY, reproduction_tests.AUROC)
        reproduction_tests.reproduce(agents, ready)
        reproduction_tests.rewrite(workspace, ready, claims_sha256="0" * 64)

        found = view(agents, ready)

        assert not [item for item in found["findings"] if item["id"].startswith("claim:")]
        assert found["steps"]["claims"] is False and "Not tried against the code." in found["card"]


class TestThePackage:
    def test_it_is_a_folder_with_the_card_the_statement_and_what_was_found(
        self, agents: PaperAgents, fetched: str
    ) -> None:
        archive = package_of(agents, fetched)

        assert names_in(archive) == ["availability_statement.md", "findings.json", "reproducibility_card.md"]
        record = json.loads(archive.read(archive.namelist()[0].split("/")[0] + "/findings.json"))
        assert record["verdict"] in ("to_fix", "unfinished") and record["commit"] == COMMIT
        assert record["findings"] and record["not_checked"] and "stood in a reader's way" in record["meaning"]
        assert not any(name.startswith(("/", "..")) or ".." in name.split("/") for name in archive.namelist())

    def test_the_exact_versions_of_a_built_environment_are_in_it_without_the_project_itself(
        self, agents: PaperAgents, prepared: str, workspace: Workspace
    ) -> None:
        archive = package_of(agents, prepared)

        directory = directory_of(workspace, prepared)
        built = kept_environment.load(directory, COMMIT)
        assert built is not None
        name = exporting.LOCKS[built["lock"]["name"]]
        assert name in names_in(archive)
        folder = archive.namelist()[0].split("/")[0]
        lock = archive.read(f"{folder}/{name}").decode()
        assert lock.strip() and lock.endswith("\n")
        assert lock == exporting.lock_lines(kept_environment.read_lock(directory, built), built["recipe"]["kind"])
        shown = view(agents, prepared)["card"]
        digest = hashlib.sha256(lock.encode()).hexdigest()[:16]
        assert f"{built['lock']['packages']} packages, in `{name}` (sha256 `{digest}`)" in shown

    def test_a_package_of_the_tools_that_is_of_what_is_kept_is_carried_in_it(
        self, agents: PaperAgents, made: str, packages: Packages
    ) -> None:
        library_tests.export(agents, made)
        entry = library_tests.entry_of(agents, made)["export"]

        found = view(agents, made)
        archive = package_of(agents, made)

        assert found["package"]["carries_tools"] is True
        assert f"mcp/{entry['file']}" in names_in(archive)
        assert {"name": f"mcp/{entry['file']}", "bytes": entry["bytes"]} in found["package"]["files"]
        folder = archive.namelist()[0].split("/")[0]
        assert archive.read(f"{folder}/mcp/{entry['file']}") == agents.export_file(made).read_bytes()
        assert f"`{entry['file']}` ({entry['bytes']:,} bytes" in found["card"]
        assert "| map_cells | A |" in found["card"]

    def test_a_package_of_the_tools_that_is_not_of_what_is_kept_now_is_left_out(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace
    ) -> None:
        library_tests.export(agents, made)
        directory = directory_of(workspace, made)
        built = kept_environment.load(directory, COMMIT)
        assert built is not None
        lock = kept_environment.env_path(directory) / built["lock"]["name"]
        lock.write_text(lock.read_text() + "\nextra==1.0\n")

        found = view(agents, made)

        assert found["package"]["carries_tools"] is False
        assert not any(name.startswith("mcp/") for name in names_in(package_of(agents, made)))
        assert "## Package" not in found["card"]

    def test_a_package_of_the_tools_that_is_too_large_to_carry_is_named_and_left_out(
        self, agents: PaperAgents, made: str, packages: Packages, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        library_tests.export(agents, made)
        monkeypatch.setattr(authoring, "MAX_CARRIED_PACKAGE_BYTES", 10)

        found = view(agents, made)

        assert found["package"]["carries_tools"] is False
        assert not any(name.startswith("mcp/") for name in names_in(package_of(agents, made)))
        assert "## Package" in found["card"]

    def test_what_the_paper_and_the_code_say_cannot_break_the_card(self, agents: PaperAgents, remote: Remote) -> None:
        agent_id = agents.create("Maps | cells\n# Injected", {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}, URL)
        fetch(agents, agent_id)

        card = view(agents, agent_id)["card"]

        assert card.splitlines()[0] == "# Reproducibility card: Maps / cells # Injected"
        assert "\n# Injected" not in card


class TestWhatIsReadFromTheProject:
    def test_only_a_plain_file_that_is_not_larger_than_the_limit_is_read(self, tmp_path: Path) -> None:
        (tmp_path / "exact.txt").write_bytes(b"12345")
        (tmp_path / "over.txt").write_bytes(b"123456")
        (tmp_path / "bad.txt").write_bytes(b"ok \xff ok")
        (tmp_path / "folder").mkdir()
        (tmp_path / "link.txt").symlink_to(tmp_path / "exact.txt")

        assert authoring.read_text(tmp_path / "exact.txt", 5) == "12345"
        assert authoring.read_text(tmp_path / "over.txt", 5) is None
        assert authoring.read_text(tmp_path / "bad.txt", 20) == "ok \ufffd ok"
        assert authoring.read_text(tmp_path / "folder", 5) is None
        assert authoring.read_text(tmp_path / "link.txt", 5) is None
        assert authoring.read_text(tmp_path / "missing.txt", 5) is None

    def test_a_path_that_leaves_the_project_is_not_inside_it(self) -> None:
        assert authoring.is_inside("requirements.txt") and authoring.is_inside("docs/requirements.txt")
        assert not authoring.is_inside("")
        assert not authoring.is_inside("/etc/passwd")
        assert not authoring.is_inside("../requirements.txt")
        assert not authoring.is_inside("docs/../../requirements.txt")

    def test_code_larger_than_a_limit_is_not_read_and_a_notebook_has_a_larger_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(authoring, "MAX_CODE_BYTES", 10)
        monkeypatch.setattr(authoring, "MAX_NOTEBOOK_BYTES", 100)
        (tmp_path / "small.py").write_text("import a\n")
        (tmp_path / "large.py").write_text("import a\nimport b\n")
        (tmp_path / "book.ipynb").write_text("x" * 50)
        (tmp_path / "huge.ipynb").write_text("x" * 101)
        listed = [("small.py", 9), ("large.py", 18), ("book.ipynb", 50), ("huge.ipynb", 101), ("notes.md", 3)]

        assert [path for path, _ in authoring.code_of(tmp_path, listed)] == ["small.py", "book.ipynb"]

    def test_only_the_files_of_python_in_the_project_say_what_is_installed(
        self, tmp_path: Path, workspace: Workspace
    ) -> None:
        repo = kept_repository.repo_path(tmp_path)
        repo.mkdir()
        (repo / "requirements.txt").write_text("pandas\n")
        (repo / "Dockerfile").write_text("FROM python\nRUN pip install numpy\n")
        (tmp_path / "outside.txt").write_text("numpy\n")
        (repo / "analysis.py").write_text("import numpy\nimport pandas\n")
        stock = {
            "environment": [
                {"kind": "pip", "path": "requirements.txt"},
                {"kind": "pip", "path": "../outside.txt"},
                {"kind": "docker", "path": "Dockerfile"},
            ]
        }

        assert [item["name"] for item in authoring.missing_requirements(tmp_path, stock)] == ["numpy"]


class TestWhatIsMadeOfWhatIsKept:
    def test_a_failure_that_is_newer_than_what_was_built_is_said(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        environment_tests.build(agents, fetched)
        directory = directory_of(workspace, fetched)
        built = kept_environment.load(directory, COMMIT)
        assert built is not None
        newer = {
            "schema": 1,
            "commit": COMMIT,
            "failed_at": "2999-01-01T00:00:00Z",
            "recipe": built["recipe"],
            "limits": built["limits"],
            "failure": {"kind": "timeout", "title": "Too slow", "detail": "It was.", "tail": []},
        }
        (kept_environment.env_path(directory) / kept_environment.FAILURE_FILE).write_text(json.dumps(newer))

        assert "build" in findings_of(agents, fetched)

    def test_tutorials_are_counted_by_how_they_ended(self) -> None:
        ran = {
            "tutorials": [
                {"status": "ok", "stable": False},
                {"status": "ok", "stable": True},
                {"status": "ok", "stable": None},
                {"status": "failed", "stable": False},
            ]
        }

        assert authoring.tutorials_of(ran) == {"ran": 4, "ok": 3, "failed": 1, "unstable": 1}
        assert authoring.tutorials_of(None) is None

    def test_datasets_say_where_each_is_and_only_places_the_paper_or_the_code_gives_are_listed(self) -> None:
        candidates = [
            {"key": "a", "url": "https://zenodo.org/records/1", "label": "A", "facts": [1], "in_code": False},
            {"key": "b", "url": "https://zenodo.org/records/2", "label": "B", "facts": [], "in_code": True},
            {"key": "c", "url": "https://zenodo.org/records/3", "label": "C", "facts": [], "in_code": False},
        ]
        datasets = [
            {"name": "One", "accession": "GSE1", "candidate": "a"},
            {"name": "Two", "accession": None, "candidate": None},
        ]

        found, places = authoring.data_of({"candidates": candidates, "datasets": datasets})

        assert [item["place"] for item in found] == ["https://zenodo.org/records/1", None]
        assert [item["label"] for item in places] == ["A", "B"]

    def test_what_is_listed_of_the_data_is_limited(self) -> None:
        many = [
            {"key": str(n), "url": f"https://zenodo.org/records/{n}", "label": str(n), "facts": [n], "in_code": False}
            for n in range(authoring.MAX_PLACES + 3)
        ]
        names = [{"name": str(n), "accession": None, "candidate": None} for n in range(pure.MAX_EACH + 3)]

        found, places = authoring.data_of({"candidates": many, "datasets": names})

        assert len(found) == pure.MAX_EACH and len(places) == authoring.MAX_PLACES

    def test_only_the_numbers_that_were_tried_are_listed_and_not_more_than_the_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pure, "MAX_CLAIM_ROWS", 2)
        claims = [
            {"value": str(n), "status": "reproduced" if n else "not_attempted", "quote": f"q{n}"} for n in range(5)
        ]
        record = {"current": True, "kept": {}, "counts": {"reproduced": 4}, "claims": claims}

        tried = authoring.tried_of(record)

        assert tried is not None and [row["value"] for row in tried["rows"]] == ["1", "2"]
        assert tried["entries"] == claims
        assert authoring.tried_of({**record, "current": False}) is None
        assert authoring.tried_of({**record, "kept": None}) is None

    def test_the_top_of_what_was_found_is_limited(
        self, agents: PaperAgents, fetched: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(authoring, "MAX_TOP", 1)

        gathered = authoring.gather(agents, fetched)

        first = gathered["findings"][0]
        assert gathered["facts"]["top"] == [{"severity": first["severity"], "title": first["title"]}]


class TestWhatThePackageCarries:
    def test_the_package_of_the_tools_is_carried_stored_and_the_rest_compressed(
        self, agents: PaperAgents, made: str, packages: Packages
    ) -> None:
        library_tests.export(agents, made)

        archive = package_of(agents, made)

        kinds = {info.filename.split("/", 1)[1]: info.compress_type for info in archive.infolist()}
        [tools_file] = [name for name in kinds if name.startswith("mcp/")]
        assert kinds[tools_file] == zipfile.ZIP_STORED
        assert kinds["reproducibility_card.md"] == zipfile.ZIP_DEFLATED
        listed = [item["name"] for item in view(agents, made)["package"]["files"]]
        assert listed.count(tools_file) == 1

    def test_the_tools_are_carried_only_when_asked_for_and_not_too_large(
        self, agents: PaperAgents, made: str, packages: Packages, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        library_tests.export(agents, made)
        gathered = authoring.gather(agents, made)

        def carried(**options: Any) -> list[str]:
            return [name for name, _, _ in authoring.carried_files(gathered, **options) if name.startswith("mcp/")]

        assert len(carried()) == 1
        assert carried(with_tools=False) == []
        monkeypatch.setattr(authoring, "MAX_CARRIED_PACKAGE_BYTES", 10)
        assert carried() == []

    def test_a_file_is_the_package_only_if_it_is_the_one_that_was_made(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace
    ) -> None:
        library_tests.export(agents, made)
        directory = directory_of(workspace, made)
        kept = authoring.gather(agents, made)["facts"]["package"]
        assert kept is not None

        assert authoring.read_package(directory, kept) == agents.export_file(made).read_bytes()
        assert authoring.read_package(directory, {**kept, "file": "other.zip"}) is None
        assert authoring.read_package(directory, {**kept, "bytes": kept["bytes"] + 1}) is None


class TestOverHttp:
    def test_the_view_and_the_package_are_given(self, client: TestClient, agents: PaperAgents, fetched: str) -> None:
        shown = client.get(f"/api/paperagents/{fetched}/author")

        assert shown.status_code == 200
        body = shown.json()
        assert body["verdict"] in ("to_fix", "unfinished") and body["package"]["ready"] is True
        assert body["limits"]["most_files_read"] == 400

    def test_the_package_is_a_zip_that_is_saved_and_not_shown(self, client: TestClient, fetched: str) -> None:
        sent = client.get(f"/api/paperagents/{fetched}/author/package")

        assert sent.status_code == 200 and sent.headers["content-type"] == "application/zip"
        assert sent.headers["content-disposition"].startswith("attachment; filename=")
        assert sent.headers["x-content-type-options"] == "nosniff"
        assert "reproducibility package.zip" in sent.headers["content-disposition"]
        assert zipfile.ZipFile(io.BytesIO(sent.content)).testzip() is None

    def test_what_is_not_ready_or_not_there_is_refused(self, client: TestClient, agents: PaperAgents) -> None:
        agent_id = agent_of(agents)

        refused_package = client.get(f"/api/paperagents/{agent_id}/author/package")
        gone = client.get("/api/paperagents/nothing/author")

        assert (refused_package.status_code, refused_package.json()["error"]["code"]) == (409, "not_ready")
        assert (gone.status_code, gone.json()["error"]["code"]) == (404, "not_found")

    def test_the_views_do_not_change_what_is_kept(self, client: TestClient, workspace: Workspace, fetched: str) -> None:
        directory = directory_of(workspace, fetched)

        def snapshot() -> dict[str, tuple[int, float]]:
            return {
                str(path.relative_to(directory)): (path.stat().st_size, path.stat().st_mtime)
                for path in directory.rglob("*")
                if path.is_file()
            }

        before = snapshot()
        client.get(f"/api/paperagents/{fetched}/author")
        client.get(f"/api/paperagents/{fetched}/author/package")

        assert snapshot() == before
