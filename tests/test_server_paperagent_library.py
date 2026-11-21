"""Tests of the lab's library of PaperAgents and of making a package of an agent's tools: which agents the library lists
and what it says of each, what a package is made of and checked in, that one that did not pass is not kept, that one is
stale once what it was made of is not what is kept, and what the other operations do while one is made. Docker and its
containers are replaced by stand-ins, as in the tests of making the tools; the package's own check, which is what a
container would run, is run here by this machine's Python, and what the package does itself is in
test_paperagents_exporting."""

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
import test_server_paperagent_tools as tools
from fastapi.testclient import TestClient
from test_paperagents_reference import result_of
from test_server_paperagent_reference import NOTEBOOK, writes
from test_server_paperagent_repository import (
    COMMIT,
    LOCAL,
    URL,
    Remote,
    agent_of,
    directory_of,
    fetch,
    finish,
    refused,
)
from test_server_paperagent_tools import MAPPING, SCRIPT, Replays, make

from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import exporting
from virtual_lab.paperagents import reference as referencing
from virtual_lab.server import paperagent_checks as kept_checks
from virtual_lab.server import paperagent_environment as kept_environment
from virtual_lab.server import paperagent_library as library
from virtual_lab.server import paperagent_tools as kept_tools
from virtual_lab.server.paperagents import EXPORT_JOB, PaperAgents
from virtual_lab.server.workspace import Workspace

# What the tests of making tools are made with, which are fixtures of that module
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
Docker = tools.Docker
Containers = tools.Containers

PAPER_SENTENCE = "We present CellMapper, a method for mapping cell types in single-nucleus RNA-seq data."


def run_check(folder: Path, package: Path) -> tuple[str, int | None, str]:
    """What a container would run, run by this machine's Python: the package's own check, in the folder it is given."""
    done = subprocess.run(
        [
            sys.executable,
            str(package / exporting.SERVER_FILE),
            "check",
            "--report",
            str(folder / library.REPORT_FILE),
            "--work",
            str(folder / library.CALLS_FOLDER),
            "--seconds",
            "100",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )

    return "done", done.returncode, done.stdout + done.stderr


class Packages:
    """Stands in for the container that a package is checked in: what it was given is kept, and what it does is what the
    package's own check does, run by this machine's Python in the folder it was given, unless a play says otherwise."""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.play: Any = None
        self.gate: threading.Event | None = None
        self.began = threading.Event()

    def execute(
        self, runner: library.PackageRunner, folder: Path, item: referencing.Item, seconds: float
    ) -> tuple[str, int | None, str]:
        package = runner.mounts[0][0]
        self.runs.append(
            {
                "tag": runner.tag,
                "data": runner.data,
                "label": runner.label,
                "scratch": runner.scratch,
                "mounts": runner.mounts,
                "argv": runner.argv(item),
                "seconds": seconds,
                "files": sorted(path.name for path in package.iterdir()),
            }
        )
        self.began.set()
        if self.gate is not None:
            while not self.gate.wait(0.01):
                if runner.stop.is_set():
                    return "stopped", None, ""
        if self.play is not None:
            return self.play(folder, package)
        return run_check(folder, package)


@pytest.fixture
def packages(monkeypatch: pytest.MonkeyPatch) -> Packages:
    stand_in = Packages()
    monkeypatch.setattr(library.PackageRunner, "execute", lambda *arguments: stand_in.execute(*arguments))

    return stand_in


@pytest.fixture
def made(agents: PaperAgents, referenced: str) -> str:
    """An agent with two tools of tier A, whose code is under the MIT license."""
    make(agents, referenced)

    return referenced


def made_without(
    agents: PaperAgents, remote: Remote, containers: Containers, name: str, changes: dict[str, Any] | None = None
) -> str:
    """The same as `made`, but of code with a file or two other than they would be."""
    files = {**remote.files, SCRIPT: "print(1)\n", "cellmapper/mapping.py": MAPPING}
    files = {key: value for key, value in files.items() if key != name}
    remote.files = {**files, **(changes or {})}
    agent_id = agent_of(agents)
    fetch(agents, agent_id)
    tools.reference.build(agents, agent_id)
    containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=tools.CALLS))
    tools.reference_run(agents, agent_id)
    make(agents, agent_id)

    return agent_id


def export(agents: PaperAgents, agent_id: str, **options: Any) -> Any:
    return finish(agents.start_export(agent_id, **options))


def entry_of(agents: PaperAgents, agent_id: str) -> dict[str, Any]:
    entry = agents.export(agent_id)["entry"]
    assert entry is not None

    return entry


class TestTheLibrary:
    def test_an_agent_that_has_no_tools_is_not_in_it(self, agents: PaperAgents, prepared: str) -> None:
        shown = agents.library()

        assert shown["agents"] == []
        assert shown["docker"] == {"ready": True, "message": None}
        assert shown["meaning"] and set(shown["flags"]) == {"none", "unrecognized", "noncommercial", "copyleft"}
        assert agents.export(prepared)["entry"] is None

    def test_an_agent_that_has_tools_is_given_with_its_version_its_environment_its_tools_and_its_license(
        self, agents: PaperAgents, made: str, workspace: Workspace
    ) -> None:
        (entry,) = agents.library()["agents"]

        assert entry["id"] == made and entry["title"] == "CellMapper" and entry["given"] is False
        assert entry["version"] == {
            "commit": COMMIT,
            "short": COMMIT[:7],
            "ref": "HEAD",
            "url": URL,
            "fetched_at": entry["version"]["fetched_at"],
        }
        assert entry["environment"]["kind"] == "conda" and entry["environment"]["python"] == "3.11.9"
        assert entry["environment"]["image"]["id"].startswith("sha256:")
        assert entry["environment"]["lock"]["packages"] == 2 and entry["environment"]["pip_check"] is True
        assert entry["license"]["flag"] is None and entry["license"]["kind"] == "permissive"
        assert [tool["name"] for tool in entry["tools"]] == ["map_cells", "tally"]
        assert {tool["tier"] for tool in entry["tools"]} == {"A"} and entry["tier"] == "A"
        assert entry["tools"][1]["function"] == "cellmapper.mapping.tally" and entry["tools"][1]["calls"] >= 1
        assert entry["export"] is None and entry["dropped"] == 0
        lock = (
            kept_environment.env_path(directory_of(workspace, made)) / entry["environment"]["lock"]["name"]
        ).read_bytes()
        assert entry["environment"]["lock"]["sha256"] == hashlib.sha256(lock).hexdigest()
        for tool in entry["tools"]:
            stored = kept_tools.load_tool(directory_of(workspace, made), tool["name"])
            assert stored is not None and tool["wrapper_sha256"] == stored["wrapper_sha256"]

    def test_an_agent_is_given_by_the_title_it_has_now(self, agents: PaperAgents, made: str) -> None:
        agents.change(made, title="Zebra")

        assert [entry["title"] for entry in agents.library()["agents"]] == ["Zebra"]

    def test_the_agent_is_of_the_highest_tier_of_its_tools(
        self, agents: PaperAgents, made: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = kept_checks.with_tier

        def raised(directory: Path, tool: dict[str, Any], kept: dict[str, Any]) -> dict[str, Any]:
            shown = real(directory, tool, kept)

            return {**shown, "tier": "B", "passed": ["heldout"]} if tool["name"] == "tally" else shown

        monkeypatch.setattr(kept_checks, "with_tier", raised)

        entry = entry_of(agents, made)
        by_name = {tool["name"]: tool for tool in entry["tools"]}
        assert entry["tier"] == "B"
        assert by_name["tally"]["tier"] == "B" and by_name["tally"]["made_as"] == "A"
        assert by_name["tally"]["passed"] == ["heldout"] and by_name["map_cells"]["tier"] == "A"

    def test_it_is_given_when_docker_is_not_running_and_says_so(
        self, agents: PaperAgents, made: str, docker: Docker
    ) -> None:
        docker.usable = (False, "Docker is not running")

        shown = agents.library()

        assert len(shown["agents"]) == 1 and shown["docker"] == {"ready": False, "message": "Docker is not running"}
        assert agents.export(made)["docker"]["ready"] is False

    def test_an_agent_whose_tools_were_not_all_made_is_not_in_it(
        self, agents: PaperAgents, referenced: str, replays: Replays
    ) -> None:
        replays.gates["tally"] = threading.Event()
        job = agents.start_tools(referenced)
        assert replays.began["tally"].wait(10)
        job.request_stop()
        finish(job)

        assert agents.library()["agents"] == []
        assert agents.export(referenced)["entry"] is None

    def test_an_agent_that_is_being_removed_is_not_in_it(self, agents: PaperAgents, made: str) -> None:
        agents._deleting.add(made)

        assert agents.library()["agents"] == []

    def test_a_package_of_an_agent_that_has_no_tools_now_is_not_given(
        self, agents: PaperAgents, made: str, packages: Packages, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        export(agents, made)
        monkeypatch.setattr(agents, "library_pieces", lambda directory, agent: None)

        assert refused(agents.export_file, made).status == 404

    def test_an_agent_that_is_not_there_has_no_package(self, agents: PaperAgents) -> None:
        for call in (agents.export, agents.export_file, agents.start_export, agents.clear_export):
            error = refused(call, "nothing")
            assert error.status == 404, call


class TestMakingAPackage:
    def test_it_is_made_of_the_tools_and_kept_only_after_it_passed_its_check_in_a_container(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace
    ) -> None:
        job = export(agents, made)

        assert job.state == "succeeded", job.error
        assert job.kind == EXPORT_JOB
        assert "clean container" in job.message and "recorded call" in job.message
        (run,) = packages.runs
        assert run["tag"] == building.tag_of(made, COMMIT) and run["label"] == made and run["data"] is None
        assert run["mounts"] == ((run["mounts"][0][0], library.PACKAGE_AT),)
        assert run["argv"][:3] == ["python", f"{library.PACKAGE_AT}/{exporting.SERVER_FILE}", "check"]
        assert {"package.json", "mcp_server.py", "repo", "tools", "Dockerfile"} <= set(run["files"])
        assert str(run["scratch"]).startswith(str(workspace.root))
        assert not run["mounts"][0][0].exists() and not list(run["scratch"].glob("check-*"))

        directory = directory_of(workspace, made)
        record = json.loads((library.exports_path(directory) / library.EXPORT_FILE).read_text())
        path = library.exports_path(directory) / record["file"]
        assert record["file"] == "cellmapper-" + COMMIT[:7] + ".zip" and path.is_file()
        assert (
            record["bytes"] == path.stat().st_size and record["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        )
        assert record["commit"] == COMMIT and record["accepted_license"] is False
        assert record["license"] == {"flag": None, "name": "MIT", "kind": "permissive"}
        assert [tool["name"] for tool in record["tools"]] == ["map_cells", "tally"]
        assert record["tested"]["ok"] is True and record["tested"]["calls"] == sum(
            tool["calls"] for tool in entry_of(agents, made)["tools"]
        )
        assert record["tested"]["image_id"] == entry_of(agents, made)["environment"]["image"]["id"]
        assert not list(library.exports_path(directory).glob("*.part"))

    def test_what_it_holds_is_the_code_and_the_tools_and_nothing_of_the_paper(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace, tmp_path: Path
    ) -> None:
        export(agents, made)
        kept = agents.export_file(made)

        unpacked = exporting.unpack(kept, tmp_path / "out")

        manifest = json.loads((unpacked / "package.json").read_text())
        assert manifest["code"]["commit"] == COMMIT and manifest["paper"] == {
            "kind": "doi",
            "doi": "10.1038/s41586-020-2649-2",
        }
        assert (unpacked / "repo" / "cellmapper" / "mapping.py").read_text() == MAPPING
        assert not (unpacked / "repo" / ".git").exists()
        assert sorted(path.name for path in (unpacked / "tools").iterdir()) == ["map_cells", "tally"]
        everything = "\n".join(p.read_text(errors="ignore") for p in unpacked.rglob("*") if p.is_file())
        assert PAPER_SENTENCE not in everything
        with zipfile.ZipFile(kept) as archive:
            assert archive.testzip() is None

    def test_what_it_is_as_the_library_lists_it(self, agents: PaperAgents, made: str, packages: Packages) -> None:
        export(agents, made)

        shown = entry_of(agents, made)["export"]

        assert shown["current"] is True and shown["commit"] == COMMIT and shown["tested"]["ok"] is True
        assert shown["file"] == shown["name"] + ".zip" and shown["accepted_license"] is False
        assert "path" not in shown and shown["repo"]["files"] >= 2
        assert agents.export(made)["job"] is None
        assert agents.library()["agents"][0]["export"] == shown

    def test_a_package_that_gave_something_else_than_the_tutorials_did_is_not_kept_and_says_how(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace
    ) -> None:
        def play(folder: Path, package: Path) -> tuple[str, int | None, str]:
            source = package / "repo" / "cellmapper" / "mapping.py"
            source.write_text(MAPPING.replace("sum(counts) * scale", "sum(counts) * scale + 1"))
            return run_check(folder, package)

        packages.play = play

        job = export(agents, made)

        assert job.state == "failed" and job.error is not None
        assert "was not kept" in job.error and "tally, call 1" in job.error
        assert library.stored_export(directory_of(workspace, made)) is None
        assert not library.exports_path(directory_of(workspace, made)).exists()
        assert entry_of(agents, made)["export"] is None
        assert refused(agents.export_file, made).status == 404

    @pytest.mark.parametrize(
        ("change", "said"),
        [
            (lambda report: {**report, "tools": []}, "did not report on the tools"),
            (lambda report: {**report, "tools": report["tools"][:1]}, "did not report on the tools"),
            (lambda report: {**report, "name": "other-package"}, "another package"),
            (lambda report: {**report, "version": "0000000"}, "another package"),
            (lambda report: {**report, "tools": [{**tool, "cases": []} for tool in report["tools"]]}, "recorded calls"),
            (
                lambda report: {
                    **report,
                    "tools": [{**tool, "cases": [{**tool["cases"][0], "case": 5}]} for tool in report["tools"]],
                },
                "recorded calls",
            ),
            (
                lambda report: {
                    **report,
                    "tools": [*report["tools"], report["tools"][0]],
                },
                "did not report on the tools",
            ),
        ],
    )
    def test_a_report_that_is_not_of_what_the_package_holds_is_not_believed_though_it_says_it_passed(
        self,
        agents: PaperAgents,
        made: str,
        packages: Packages,
        workspace: Workspace,
        change: Any,
        said: str,
    ) -> None:
        def play(folder: Path, package: Path) -> tuple[str, int | None, str]:
            ended, code, text = run_check(folder, package)
            path = folder / library.REPORT_FILE
            path.write_text(json.dumps(change({**json.loads(path.read_text()), "ok": True, "problems": []})))
            return ended, code, text

        packages.play = play

        job = export(agents, made)

        assert job.state == "failed" and job.error is not None and said in job.error, job.error
        assert library.stored_export(directory_of(workspace, made)) is None

    def test_a_report_is_held_to_the_most_calls_that_the_check_is_asked_to_make_of_a_tool(self) -> None:
        manifest = {"name": "p", "version": "1", "tools": [{"name": "a", "examples": [{}] * 5}]}
        cases = [
            {"case": number, "status": "match", "differences": [], "message": None, "seconds": 1} for number in range(5)
        ]
        report = {"name": "p", "version": "1", "tools": [{"name": "a", "cases": cases[: library.MAX_CASES]}]}

        assert library.not_of_the_package(report, manifest) is None
        report["tools"][0]["cases"] = cases
        assert "recorded calls" in (library.not_of_the_package(report, manifest) or "")

    def test_a_package_that_the_tutorials_were_given_data_for_is_not_of_what_it_is_made_of_without(
        self, agents: PaperAgents, made: str, workspace: Workspace
    ) -> None:
        directory = directory_of(workspace, made)
        pieces = agents.library_pieces(directory, agents.lookup(made)[1])
        assert pieces is not None
        intake, built, kept = pieces
        tools_made = library.tools_now(directory, kept)

        without = library.state_for(directory, intake, built, {**kept, "data": None}, tools_made, None)
        given = library.state_for(directory, intake, built, {**kept, "data": {"x": 1}}, tools_made, None)

        assert without != given

    def test_the_check_is_asked_for_a_number_of_calls_of_each_tool_that_the_report_is_held_to(
        self, agents: PaperAgents, made: str, packages: Packages
    ) -> None:
        export(agents, made)

        argv = packages.runs[0]["argv"]

        assert argv[argv.index("--cases") + 1] == str(library.MAX_CASES)

    @pytest.mark.parametrize(
        ("ended", "code", "wrote", "said"),
        [
            ("timed_out", None, None, "stopped after 20 minutes"),
            ("too_big", None, None, "more than 2 gigabytes"),
            ("done", 3, None, "ended with code 3, without a report"),
            ("done", 0, "not json", "without a report"),
        ],
    )
    def test_a_check_that_did_not_end_in_a_report_is_not_a_package(
        self,
        agents: PaperAgents,
        made: str,
        packages: Packages,
        workspace: Workspace,
        ended: str,
        code: int | None,
        wrote: str | None,
        said: str,
    ) -> None:
        def play(folder: Path, package: Path) -> tuple[str, int | None, str]:
            if wrote is not None:
                (folder / library.REPORT_FILE).write_text(wrote)
            return ended, code, "it broke"

        packages.play = play

        job = export(agents, made)

        assert job.state == "failed" and job.error is not None and said in job.error
        assert library.stored_export(directory_of(workspace, made)) is None

    def test_a_report_that_says_it_did_not_pass_is_not_a_package(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace
    ) -> None:
        def play(folder: Path, package: Path) -> tuple[str, int | None, str]:
            report = {
                "schema": 1,
                "ok": False,
                "python": "3.11.9",
                "name": "x",
                "version": "1",
                "problems": ["a file of the package is not as it was made: tools/tally/wrapper.py"],
                "tools": [],
            }
            (folder / library.REPORT_FILE).write_text(json.dumps(report))
            return "done", 1, ""

        packages.play = play

        job = export(agents, made)

        assert job.state == "failed" and job.error is not None and "tools/tally/wrapper.py" in job.error

    def test_a_package_that_was_kept_stays_when_a_later_one_does_not_pass(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace
    ) -> None:
        export(agents, made)
        before = agents.export_file(made).read_bytes()
        packages.play = lambda folder, package: ("done", 4, "no")

        job = export(agents, made)

        assert job.state == "failed"
        assert agents.export_file(made).read_bytes() == before

    def test_a_check_that_could_not_be_run_because_docker_could_not_is_not_a_failing_of_the_package(
        self, agents: PaperAgents, made: str, packages: Packages
    ) -> None:
        packages.play = lambda folder, package: (
            "done",
            referencing.DOCKER_FAILED,
            "Cannot connect to the Docker daemon",
        )

        job = export(agents, made)

        assert job.state == "failed" and job.error is not None
        assert "Docker did not run the package" in job.error and "Cannot connect" in job.error
        assert "was not kept" not in job.error

    def test_a_package_that_is_stopped_is_not_kept(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace
    ) -> None:
        packages.gate = threading.Event()
        job = agents.start_export(made)
        assert packages.began.wait(10)

        job.request_stop()
        finish(job)

        assert job.state == "stopped"
        assert library.stored_export(directory_of(workspace, made)) is None
        assert agents.export(made)["job"] is None


class TestWhatIsMadeOf:
    def test_a_tool_that_is_not_as_it_was_made_is_a_package_that_is_not_made(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace
    ) -> None:
        (kept_tools.tool_path(directory_of(workspace, made), "tally") / "tool.json").write_text("{")

        job = export(agents, made)

        assert job.state == "failed" and job.error is not None and "Make the tools again" in job.error
        assert packages.runs == []

    def test_a_package_made_again_under_another_name_takes_the_earlier_one_away(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace
    ) -> None:
        export(agents, made)
        agents.change(made, title="Another name")

        job = export(agents, made)

        assert job.state == "succeeded", job.error
        files = [path.name for path in library.exports_path(directory_of(workspace, made)).iterdir()]
        assert sorted(files) == sorted([library.EXPORT_FILE, "another-name-" + COMMIT[:7] + ".zip"])


class TestWhenItIsRefused:
    def test_docker_has_to_be_running(self, agents: PaperAgents, made: str, docker: Docker) -> None:
        docker.usable = (False, "Docker is not running")

        error = refused(agents.start_export, made)

        assert (error.status, error.code) == (422, "docker_missing")

    def test_the_tools_have_to_be_made(self, agents: PaperAgents, referenced: str) -> None:
        error = refused(agents.start_export, referenced)

        assert (error.status, error.code) == (422, "no_tools")

    def test_the_code_and_the_environment_have_to_be_there(self, agents: PaperAgents) -> None:
        agent_id = agent_of(agents, repo=None)

        assert refused(agents.start_export, agent_id).status == 422

    def test_the_image_has_to_be_in_docker(self, agents: PaperAgents, made: str, docker: Docker) -> None:
        docker.images.pop(building.tag_of(made, COMMIT))

        assert refused(agents.start_export, made).status == 409

    @pytest.mark.parametrize("value", ["yes", 1, 0, None, [], "true"])
    def test_whether_to_go_on_with_a_license_is_yes_or_no(self, agents: PaperAgents, made: str, value: Any) -> None:
        error = refused(agents.start_export, made, value)

        assert error.status == 422

    def test_only_one_package_is_made_at_a_time_and_nothing_that_changes_what_it_is_made_of_is_done(
        self, agents: PaperAgents, made: str, packages: Packages
    ) -> None:
        packages.gate = threading.Event()
        job = agents.start_export(made)
        assert packages.began.wait(10)

        assert agents.export(made)["job"]["id"] == job.id
        for action in (
            lambda: agents.start_export(made),
            lambda: agents.clear_export(made),
            lambda: agents.clear_tools(made),
            lambda: agents.clear_reference(made),
            lambda: agents.clear_environment(made),
            lambda: agents.clear_repository(made),
            lambda: agents.start_tools(made),
            lambda: agents.delete(made),
        ):
            error = refused(action)
            assert error.status == 409 and error.code == "busy", action

        packages.gate.set()
        finish(job)
        assert job.state == "succeeded"


class TestTheLicense:
    @pytest.fixture
    def unlicensed(
        self, agents: PaperAgents, remote: Remote, docker: Docker, containers: Containers, replays: Replays
    ) -> str:
        return made_without(agents, remote, containers, "LICENSE")

    def test_code_with_no_license_is_not_made_into_a_package_unless_the_person_says_to_go_on(
        self, agents: PaperAgents, unlicensed: str, packages: Packages
    ) -> None:
        entry = entry_of(agents, unlicensed)
        assert entry["license"]["flag"] == "none"

        error = refused(agents.start_export, unlicensed)

        assert (error.status, error.code) == (409, "license")
        assert error.details["license"]["flag"] == "none" and "no license" in error.message.lower()
        assert packages.runs == []

    def test_when_the_person_goes_on_it_is_made_and_the_package_says_the_license_first(
        self, agents: PaperAgents, unlicensed: str, packages: Packages, tmp_path: Path
    ) -> None:
        job = export(agents, unlicensed, accept_license=True)

        assert job.state == "succeeded", job.error
        shown = entry_of(agents, unlicensed)["export"]
        assert shown["accepted_license"] is True and shown["license"]["flag"] == "none"
        readme = exporting.unpack(agents.export_file(unlicensed), tmp_path / "out") / "README.md"
        assert (
            readme.read_text().lstrip().startswith(("#", ">", "**", "!"))
            and "license" in readme.read_text()[:600].lower()
        )

    def test_a_license_that_limits_what_may_be_done_is_flagged_too(
        self, agents: PaperAgents, remote: Remote, docker: Docker, containers: Containers, replays: Replays
    ) -> None:
        agent_id = made_without(
            agents, remote, containers, "LICENSE", {"LICENSE": "Creative Commons Attribution-NonCommercial 4.0\n"}
        )

        error = refused(agents.start_export, agent_id)

        assert error.code == "license" and error.details["license"]["flag"] == "noncommercial"

    def test_a_license_that_is_not_flagged_needs_nothing_said(
        self, agents: PaperAgents, made: str, packages: Packages
    ) -> None:
        assert export(agents, made).state == "succeeded"


class TestWhenWhatItWasMadeOfChanges:
    def test_a_package_is_stale_when_the_lock_that_the_environment_was_built_to_is_not_the_same(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace
    ) -> None:
        export(agents, made)
        directory = directory_of(workspace, made)
        built = kept_environment.load(directory, COMMIT)
        assert built is not None
        lock = kept_environment.env_path(directory) / built["lock"]["name"]

        lock.write_text(lock.read_text() + "\nextra==1.0\n")

        assert entry_of(agents, made)["export"]["current"] is False
        assert refused(agents.export_file, made).status == 409

    def test_a_package_is_stale_once_a_tools_tier_is_not_what_it_was(
        self, agents: PaperAgents, made: str, packages: Packages, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        export(agents, made)
        real = kept_checks.with_tier
        monkeypatch.setattr(
            kept_checks, "with_tier", lambda *arguments: {**real(*arguments), "tier": "B", "passed": ["heldout"]}
        )

        assert entry_of(agents, made)["export"]["current"] is False
        error = refused(agents.export_file, made)
        assert (error.status, error.code) == (409, "stale")

        monkeypatch.setattr(kept_checks, "with_tier", real)
        assert entry_of(agents, made)["export"]["current"] is True
        assert agents.export_file(made).is_file()

    def test_it_is_made_again_for_what_is_kept_now(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        export(agents, made)
        first = entry_of(agents, made)["export"]["sha256"]
        real = kept_checks.with_tier
        monkeypatch.setattr(
            kept_checks, "with_tier", lambda *arguments: {**real(*arguments), "tier": "B", "passed": ["heldout"]}
        )

        job = export(agents, made)

        assert job.state == "succeeded"
        again = entry_of(agents, made)["export"]
        assert again["current"] is True and again["sha256"] != first
        assert [path.name for path in library.exports_path(directory_of(workspace, made)).iterdir()].count(
            library.EXPORT_FILE
        ) == 1
        assert len(list(library.exports_path(directory_of(workspace, made)).glob("*.zip"))) == 1

    def test_taking_the_tools_away_takes_the_package(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace
    ) -> None:
        export(agents, made)
        directory = directory_of(workspace, made)
        assert library.stored_export(directory) is not None

        agents.clear_tools(made)

        assert library.stored_export(directory) is None and not library.exports_path(directory).exists()
        assert agents.export(made)["entry"] is None
        assert refused(agents.export_file, made).status == 404

    def test_taking_the_tutorials_away_takes_the_package_with_the_tools(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace
    ) -> None:
        export(agents, made)

        agents.clear_reference(made)

        assert not library.exports_path(directory_of(workspace, made)).exists()

    def test_taking_the_package_away_leaves_the_tools(
        self, agents: PaperAgents, made: str, packages: Packages, workspace: Workspace
    ) -> None:
        export(agents, made)

        agents.clear_export(made)
        agents.clear_export(made)

        assert agents.export(made)["entry"]["export"] is None and len(agents.library()["agents"]) == 1
        assert refused(agents.export_file, made).status == 404
        assert not library.exports_path(directory_of(workspace, made)).exists()

    @pytest.mark.parametrize(
        "change",
        ["commit", "image", "flag", "wrapper", "tier", "passed", "tool_gone", "cases", "tolerance", "lock", "data"],
    )
    def test_what_a_package_is_made_of_is_what_its_state_is_of(self, change: str) -> None:
        evidence = {"cases": [{"args": {"x": 1}}], "tolerance": {"relative": 0.1, "absolute": 0.1}}
        tools = [
            {"name": "a", "wrapper_sha256": "1", "now": {"tier": "A", "passed": []}, "evidence": evidence},
            {"name": "b", "wrapper_sha256": "2", "now": {"tier": "A", "passed": []}, "evidence": evidence},
        ]
        base = library.state_of("c" * 40, "sha256:i", tools, None, "lock", False)
        assert (
            library.state_of("c" * 40, "sha256:i", [dict(tool) for tool in reversed(tools)], None, "lock", False)
            == base
        )

        c, i = "c" * 40, "sha256:i"
        changed = {
            "commit": ("d" * 40, i, tools, None, "lock", False),
            "image": (c, "sha256:j", tools, None, "lock", False),
            "flag": (c, i, tools, "none", "lock", False),
            "wrapper": (c, i, [{**tools[0], "wrapper_sha256": "9"}, tools[1]], None, "lock", False),
            "tier": (c, i, [{**tools[0], "now": {"tier": "B", "passed": []}}, tools[1]], None, "lock", False),
            "passed": (c, i, [{**tools[0], "now": {"tier": "A", "passed": ["x"]}}, tools[1]], None, "lock", False),
            "tool_gone": (c, i, tools[:1], None, "lock", False),
            "cases": (
                c,
                i,
                [{**tools[0], "evidence": {**evidence, "cases": [{"args": {"x": 2}}]}}, tools[1]],
                None,
                "lock",
                False,
            ),
            "tolerance": (
                c,
                i,
                [{**tools[0], "evidence": {**evidence, "tolerance": {"relative": 0.2, "absolute": 0.1}}}, tools[1]],
                None,
                "lock",
                False,
            ),
            "lock": (c, i, tools, None, "other", False),
            "data": (c, i, tools, None, "lock", True),
        }[change]

        assert library.state_of(*changed) != base


class TestWhatIsKept:
    def record(self, directory: Path, **changes: Any) -> Path:
        folder = library.exports_path(directory)
        folder.mkdir(parents=True)
        (folder / "p.zip").write_bytes(b"zip")
        record = {
            "schema": 1,
            "name": "p",
            "file": "p.zip",
            "made_at": "2025-01-01T00:00:00Z",
            "bytes": 3,
            "sha256": hashlib.sha256(b"zip").hexdigest(),
            "state": "s",
            "commit": "c" * 40,
            "accepted_license": False,
            "license": {"flag": None, "name": "MIT", "kind": "permissive"},
            "tools": [{"name": "a", "tier": "A", "wrapper_sha256": "1"}],
            "repo": {"files": 1, "bytes": 1, "sha256": "2"},
            "tested": {
                "ok": True,
                "python": "3.11.9",
                "image_id": "sha256:i",
                "at": "2025-01-01T00:00:00Z",
                "seconds": 1.5,
                "calls": 1,
                "tools": [{"name": "a", "cases": [{"case": 0, "status": "match", "seconds": 1}]}],
            },
            **changes,
        }
        (folder / library.EXPORT_FILE).write_text(json.dumps(record))

        return folder

    def test_a_record_that_is_whole_and_whose_file_is_what_it_says_is_kept(self, tmp_path: Path) -> None:
        self.record(tmp_path)

        assert library.stored_export(tmp_path) is not None
        assert library.export_file(tmp_path) == library.exports_path(tmp_path) / "p.zip"

    @pytest.mark.parametrize(
        "changes",
        [
            {"schema": 2},
            {"file": "../p.zip"},
            {"file": ".hidden"},
            {"file": "a/p.zip"},
            {"bytes": 4},
            {"bytes": "3"},
            {"license": None},
            {"tested": {"ok": True}},
        ],
    )
    def test_a_record_that_is_not_is_not(self, tmp_path: Path, changes: dict[str, Any]) -> None:
        self.record(tmp_path, **changes)

        assert library.stored_export(tmp_path) is None and library.export_file(tmp_path) is None

    @pytest.mark.parametrize("name", ["../outside.zip", ".hidden.zip", "inside/p.zip"])
    def test_a_name_that_leads_out_of_the_folder_or_hides_is_not_one_that_is_kept_even_when_the_file_is_there(
        self, tmp_path: Path, name: str
    ) -> None:
        folder = self.record(tmp_path, file=name)
        (folder / name).parent.mkdir(exist_ok=True)
        (folder / name).write_bytes(b"zip")

        assert library.stored_export(tmp_path) is None

    def test_a_file_that_is_a_link_is_not_followed(self, tmp_path: Path) -> None:
        folder = self.record(tmp_path)
        (folder / "p.zip").unlink()
        (tmp_path / "elsewhere.zip").write_bytes(b"zip")
        (folder / "p.zip").symlink_to(tmp_path / "elsewhere.zip")

        assert library.stored_export(tmp_path) is None

    def test_a_record_that_is_not_json_or_is_not_there_is_not_one(self, tmp_path: Path) -> None:
        assert library.stored_export(tmp_path) is None
        folder = self.record(tmp_path)
        (folder / library.EXPORT_FILE).write_text("{")

        assert library.stored_export(tmp_path) is None

    def test_the_record_is_taken_before_the_file_so_that_it_never_names_one_that_is_gone(self, tmp_path: Path) -> None:
        folder = self.record(tmp_path)

        library.forget(tmp_path)
        library.forget(tmp_path)

        assert not folder.exists()


class TestWhatTheCheckSays:
    REPORT = {
        "schema": 1,
        "ok": True,
        "python": "3.11.9",
        "name": "p",
        "version": "1",
        "problems": [],
        "tools": [
            {"name": "a", "cases": [{"case": 0, "status": "match", "differences": [], "message": None, "seconds": 0.5}]}
        ],
    }

    def test_a_report_that_passed_has_no_reason_why_not(self) -> None:
        assert library.why_not(self.REPORT, "done", 0, []) is None

    def test_how_the_container_ended_is_said_when_it_did_not_end_well(self) -> None:
        assert "20 minutes" in (library.why_not(None, "timed_out", None, []) or "")
        assert "2 gigabytes" in (library.why_not(None, "too_big", None, []) or "")
        assert (
            library.why_not(None, "done", 2, ["a", "b", "c", "d"])
            == "Its check ended with code 2, without a report. b c d"
        )

    def test_what_differed_is_said_by_tool_and_call(self) -> None:
        report = {
            **self.REPORT,
            "ok": False,
            "tools": [
                {
                    "name": "a",
                    "cases": [
                        {"case": 0, "status": "match", "differences": [], "message": None, "seconds": 1},
                        {
                            "case": 1,
                            "status": "differs",
                            "differences": ["value: 1 against 2"],
                            "message": None,
                            "seconds": 1,
                        },
                        {"case": 2, "status": "error", "differences": [], "message": "boom", "seconds": 1},
                    ],
                }
            ],
        }

        said = library.why_not(report, "done", 1, []) or ""

        assert "a, call 2: value: 1 against 2" in said and "a, call 3: boom" in said and "call 1" not in said

    def test_a_report_that_does_not_pass_and_does_not_say_why_is_still_not_a_pass(self) -> None:
        said = library.why_not({**self.REPORT, "ok": False}, "done", 1, [])

        assert said is not None and "did not say" in said

    def test_what_is_said_is_at_most_three_reasons(self) -> None:
        report = {**self.REPORT, "ok": False, "problems": ["one", "two", "three", "four"]}

        assert library.why_not(report, "done", 1, []) == "one two three"

    def test_a_report_is_only_read_when_it_is_one(self, tmp_path: Path) -> None:
        path = tmp_path / "report.json"
        path.write_text(json.dumps(self.REPORT))
        assert library.read_report(path) == self.REPORT

        for text in ("{", "[]", json.dumps({**self.REPORT, "schema": 2}), json.dumps({**self.REPORT, "ok": "yes"})):
            path.write_text(text)
            assert library.read_report(path) is None
        path.write_text(json.dumps(self.REPORT) + " " * library.MAX_REPORT_BYTES)
        assert library.read_report(path) is None
        path.unlink()
        assert library.read_report(path) is None
        (tmp_path / "other.json").write_text(json.dumps(self.REPORT))
        path.symlink_to(tmp_path / "other.json")
        assert library.read_report(path) is None

    def test_the_check_is_run_with_no_network_and_a_package_that_cannot_be_written_to(self, tmp_path: Path) -> None:
        (tmp_path / "package").mkdir()
        (tmp_path / "work").mkdir()
        runner = library.PackageRunner(
            "image:tag",
            referencing.Limits(gigabytes=1),
            tmp_path,
            None,
            ("docker",),
            None,
            "calc",
            mounts=((tmp_path / "package", library.PACKAGE_AT),),
        )

        command = runner.command(tmp_path / "work", referencing.Item("package", "report.json", "check"), 100, "name")

        text = " ".join(command)
        assert "none" == command[command.index("--network") + 1] and "--read-only" in command
        assert f"source={(tmp_path / 'package').resolve()},target={library.PACKAGE_AT},readonly" in text
        assert f"source={(tmp_path / 'work').resolve()},target=/workspace " in text
        assert "--cap-drop ALL" in text
        assert f"python {library.PACKAGE_AT}/{exporting.SERVER_FILE} check --report /workspace/report.json" in text


class TestOverHttp:
    def wait_for(self, client: TestClient, started: Any, state: str) -> dict[str, Any]:
        return wait_for_job(client, started.json()["id"], state)

    def test_a_package_is_asked_for_made_downloaded_and_taken_away(
        self,
        client: TestClient,
        remote: Remote,
        docker: Docker,
        containers: Containers,
        replays: Replays,
        packages: Packages,
        tmp_path: Path,
    ) -> None:
        agent_id = made_over_http(client, remote, containers)
        base = f"/api/paperagents/{agent_id}"
        listed = client.get("/api/paperagents/library")
        assert listed.status_code == 200 and [entry["id"] for entry in listed.json()["agents"]] == [agent_id]
        assert client.get(f"{base}/export/package").status_code == 404

        started = client.post(f"{base}/export", json={})
        assert started.status_code == 202 and started.json()["kind"] == EXPORT_JOB
        self.wait_for(client, started, "succeeded")
        shown = client.get(f"{base}/export").json()
        assert shown["entry"]["export"]["current"] is True and shown["docker"]["ready"] is True

        package = client.get(f"{base}/export/package")
        assert package.status_code == 200 and package.headers["content-type"] == "application/zip"
        assert (
            "attachment" in package.headers["content-disposition"] and ".zip" in package.headers["content-disposition"]
        )
        assert hashlib.sha256(package.content).hexdigest() == shown["entry"]["export"]["sha256"]
        (tmp_path / "got.zip").write_bytes(package.content)
        assert exporting.unpack(tmp_path / "got.zip", tmp_path / "out").is_dir()

        removed = client.delete(f"{base}/export")
        assert removed.status_code == 200 and removed.json()["entry"]["export"] is None
        assert client.get(f"{base}/export/package").status_code == 404

    def test_a_license_that_is_flagged_is_a_conflict_until_the_person_goes_on(
        self,
        client: TestClient,
        remote: Remote,
        docker: Docker,
        containers: Containers,
        replays: Replays,
        packages: Packages,
    ) -> None:
        agent_id = made_over_http(client, remote, containers, without="LICENSE")
        base = f"/api/paperagents/{agent_id}"

        refused_at_first = client.post(f"{base}/export", json={})
        assert refused_at_first.status_code == 409 and refused_at_first.json()["error"]["code"] == "license"
        assert refused_at_first.json()["error"]["license"]["flag"] == "none"
        started = client.post(f"{base}/export", json={"accept_license": True})
        assert started.status_code == 202
        self.wait_for(client, started, "succeeded")
        shown = client.get(f"{base}/export").json()
        assert shown["entry"]["export"]["accepted_license"] is True

    def test_a_body_that_is_not_what_is_asked_for_is_refused(
        self, client: TestClient, docker: Docker, containers: Containers, remote: Remote, replays: Replays
    ) -> None:
        agent_id = made_over_http(client, remote, containers)
        base = f"/api/paperagents/{agent_id}"

        for body in ({"accept_license": "yes"}, {"accept_license": 1}, {"accept_license": None}, {"surprise": 1}):
            assert client.post(f"{base}/export", json=body).status_code == 422, body

    def test_it_is_not_there_without_the_token_or_for_an_agent_that_is_not(self, client: TestClient) -> None:
        assert client.get("/api/paperagents/library").status_code == 200
        assert client.get("/api/paperagents/nothing/export").status_code == 404
        assert client.post("/api/paperagents/nothing/export", json={}).status_code == 404
        assert client.get("/api/paperagents/nothing/export/package").status_code == 404
        assert client.delete("/api/paperagents/nothing/export").status_code == 404
        bare = TestClient(client.app, base_url=LOCAL)
        assert bare.get("/api/paperagents/library").status_code == 401
        assert bare.get("/api/paperagents/nothing/export").status_code == 401
        assert bare.get("/api/paperagents/nothing/export/package").status_code == 401
        assert bare.post("/api/paperagents/nothing/export", json={}).status_code == 401


def wait_for_job(client: TestClient, job_id: str, state: str = "succeeded") -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while (job := client.get(f"/api/setup/jobs/{job_id}").json())["state"] in ("running", "stopping"):
        assert time.monotonic() < deadline, job
        time.sleep(0.02)
    assert job["state"] == state, job

    return job


def made_over_http(client: TestClient, remote: Remote, containers: Containers, without: str | None = None) -> str:
    files = {**remote.files, SCRIPT: "print(1)\n", "cellmapper/mapping.py": MAPPING}
    remote.files = {key: value for key, value in files.items() if key != without}
    containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=tools.CALLS))
    agent_id = client.post(
        "/api/paperagents",
        json={"title": "CellMapper", "paper": {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}, "repo": URL},
    ).json()["id"]
    base = f"/api/paperagents/{agent_id}"

    for step, body in (
        ("repository", {}),
        ("environment", {}),
        ("reference", {"repeats": 1, "data": False}),
        ("tools", {"minutes": 2, "repeats": 1, "repairs": 0}),
    ):
        started = client.post(f"{base}/{step}", json=body)
        assert started.status_code == 202, (step, started.text)
        wait_for_job(client, started.json()["id"])

    return agent_id
