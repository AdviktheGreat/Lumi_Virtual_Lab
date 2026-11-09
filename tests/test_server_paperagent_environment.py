"""Tests of building the environment of a PaperAgent's code: what is planned and shown, the job that builds it, what is
kept and for which commit, what the other operations do while one is built and after, and that an image is taken away
with what it was built from. Docker is replaced by a stand-in that says what it was asked and keeps images by name, so
what the server does is what is looked at here; the real builds are in test_paperagents_environment."""

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MODEL
from fastapi.testclient import TestClient
from test_server_paperagent_repository import (
    BEARER,
    COMMIT,
    LIMIT_BYTES,
    LOCAL,
    TOKEN,
    URL,
    Remote,
    agent_of,
    directory_of,
    fetch,
    finish,
    git_is_installed,  # noqa: F401
    project,
    refused,
)

from virtual_lab.environment import StoppedError
from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import repository as cloning
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server.app import create_app
from virtual_lab.server.jobs import Jobs
from virtual_lab.server.paperagents import ENVIRONMENT_JOB, PaperAgents, steps_of
from virtual_lab.server.workspace import Settings, Workspace

FAILING_INSTALL = "src/_speed.c:1:10: fatal error: zlib.h: No such file or directory"


class Docker:
    """Stands in for Docker: builds what it is told to, keeps the images there are by their names, and says what it was
    asked."""

    def __init__(self) -> None:
        self.images: dict[str, str] = {}
        self.builds: list[dict[str, Any]] = []
        self.removed: list[str] = []
        self.cleaned: list[str] = []
        self.usable: tuple[bool, str | None] = (True, None)
        self.error: BaseException | None = None
        self.gate: threading.Event | None = None
        self.started = threading.Event()
        self.during: Any = None
        self.refuses = False
        self.count = 0

    def ready(self, docker_command: Any = ("docker",)) -> tuple[bool, str | None]:
        return self.usable

    def build(
        self,
        repo: Path,
        recipe: building.Recipe,
        tag: str,
        limits: building.Limits,
        scratch: Path,
        docker_command: Any = ("docker",),
        on_output: Any = None,
        stop: threading.Event | None = None,
        label: str = "",
    ) -> building.Built:
        self.builds.append(
            {
                "files": sorted(path.name for path in repo.iterdir()),
                "recipe": recipe,
                "tag": tag,
                "limits": limits,
                "scratch_is_empty": scratch.is_dir() and not any(scratch.iterdir()),
                "label": label,
                "stop": stop,
            }
        )
        self.started.set()
        if on_output is not None:
            on_output("Starting from python:3.11-slim")
            on_output("== Install the project itself")
        if self.gate is not None:
            while not self.gate.wait(0.01):
                if stop is not None and stop.is_set():
                    raise StoppedError("The build was stopped.")
        if self.during is not None:
            self.during()
        if self.error is not None:
            raise self.error
        self.count += 1
        image = f"sha256:{self.count:064x}"
        self.images[tag] = image

        return building.Built(
            tag=tag,
            image_id=image,
            base_id="sha256:" + "b" * 64,
            base_digests=("python@sha256:" + "c" * 64,),
            architecture="arm64",
            size_bytes=180_000_000,
            added_bytes=130_000_000,
            python="3.11.9",
            lock="numpy==1.26.4\nsix==1.16.0\n",
            lock_name="pip-freeze.txt",
            packages=2,
            pip_check={"ok": True, "problems": []},
            steps=({"id": "project", "title": "Install the project itself", "seconds": 2.0, "exit_code": 0},),
            duration=3.5,
            log="",
        )

    def image_id_of(self, tag: str, docker_command: Any = ("docker",)) -> str | None:
        return self.images.get(tag)

    def remove_image(self, tag: str, docker_command: Any = ("docker",)) -> bool:
        self.removed.append(tag)
        if self.refuses:
            return False
        self.images.pop(tag, None)

        return True

    def remove_builds(self, label: str, docker_command: Any = ("docker",)) -> int:
        self.cleaned.append(label)

        return 0


@pytest.fixture
def docker(monkeypatch: pytest.MonkeyPatch) -> Docker:
    stand_in = Docker()
    monkeypatch.setattr(building, "ready", stand_in.ready)
    monkeypatch.setattr(building, "build_environment", stand_in.build)
    monkeypatch.setattr(building, "image_id_of", stand_in.image_id_of)
    monkeypatch.setattr(building, "remove_image", stand_in.remove_image)
    monkeypatch.setattr(building, "remove_builds", stand_in.remove_builds)

    return stand_in


@pytest.fixture
def marker(tmp_path: Path) -> Path:
    return tmp_path / "code-ran"


@pytest.fixture
def remote(marker: Path, monkeypatch: pytest.MonkeyPatch) -> Remote:
    fetching = Remote(project(marker))
    monkeypatch.setattr(cloning, "clone", fetching)

    return fetching


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    store = Workspace(tmp_path / "workspace")
    store.save_settings(Settings(model=TEST_MODEL, max_cost=None))

    return store


@pytest.fixture
def jobs() -> Iterator[Jobs]:
    kept = Jobs()
    yield kept
    kept.close()


@pytest.fixture
def agents(workspace: Workspace, jobs: Jobs) -> PaperAgents:
    return PaperAgents(workspace, LIMIT_BYTES, jobs, lambda model: [])


@pytest.fixture
def client(workspace: Workspace) -> Iterator[TestClient]:
    app = create_app(workspace.root, token=TOKEN, check_keys=False, max_upload_bytes=LIMIT_BYTES)
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


@pytest.fixture
def fetched(agents: PaperAgents, remote: Remote, docker: Docker) -> str:
    """An agent whose code has been fetched, which is what an environment is built from."""
    agent_id = agent_of(agents)
    fetch(agents, agent_id)

    return agent_id


def build(agents: PaperAgents, agent_id: str, **options: Any) -> Any:
    return finish(agents.build_environment(agent_id, **options))


def tag_of(agent_id: str) -> str:
    return f"virtual-lab-paperagent:{agent_id}-{COMMIT[:12]}"


def step_of(agents: PaperAgents, agent_id: str) -> str:
    return steps_of(agents.lookup(agent_id)[1])["environment"]


class TestPlanned:
    def test_there_is_nothing_to_plan_until_the_code_is_fetched(self, agents: PaperAgents, docker: Docker) -> None:
        found = agents.environment(agent_of(agents))

        assert (found["commit"], found["recipe"], found["unsupported"], found["built"], found["failure"]) == (
            None,
            None,
            None,
            None,
            None,
        )
        assert found["docker"] == {"ready": True, "message": None}
        assert (found["job"], found["has_log"]) == (None, False)
        assert found["limits"]["default_minutes"] == 30 and found["limits"]["max_gigabytes"] == 40
        assert found["limits"]["memory"] == "8g" and found["limits"]["pids"] == 1024
        assert found["python_versions"][:2] == ["3.13", "3.12"] and found["max_system_packages"] == 20

    def test_what_would_be_built_comes_from_the_code_s_files(self, agents: PaperAgents, fetched: str) -> None:
        found = agents.environment(fetched)

        assert found["commit"] == COMMIT
        recipe = found["recipe"]
        assert (recipe["kind"], recipe["files"], recipe["python"]) == ("conda", ["environment.yml"], None)
        assert recipe["base_image"] == building.CONDA_IMAGE
        assert [step["id"] for step in recipe["steps"]] == ["requirements", "project", "clean"]
        assert found["unsupported"] is None
        json.dumps(found)

    def test_a_python_and_system_packages_can_be_tried_without_building(
        self, agents: PaperAgents, workspace: Workspace, remote: Remote, docker: Docker
    ) -> None:
        remote.files = {"requirements.txt": "numpy\n", "README.md": "x"}
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        recipe = agents.environment(agent_id, "3.9", ["libhdf5-dev"])["recipe"]

        assert (recipe["python"], recipe["base_image"], recipe["system_packages"]) == (
            "3.9",
            "python:3.9-slim",
            ["libhdf5-dev"],
        )
        assert [step["id"] for step in recipe["steps"]] == ["system", "requirements"]
        assert docker.builds == []

    def test_what_is_asked_to_be_tried_is_checked(self, agents: PaperAgents, fetched: str) -> None:
        assert refused(agents.environment, fetched, "3.2").status == 422
        assert refused(agents.environment, fetched, None, ["no good"]).status == 422
        # A conda file that says its Python has it said, and not another
        error = refused(agents.environment, fetched, "3.9")
        assert error.status == 422 and "says which Python" in error.message

    def test_a_project_that_is_not_built_here_says_why(
        self, agents: PaperAgents, remote: Remote, docker: Docker
    ) -> None:
        remote.files = {"README.md": "Install numpy, then run it.\n", "analysis.R": "library(Seurat)\n"}
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        found = agents.environment(agent_id)

        assert found["recipe"] is None
        assert found["unsupported"]["kind"] == "no_environment"
        assert "Nothing is guessed" in found["unsupported"]["message"]

    def test_docker_not_running_is_said_with_what_to_do(
        self, agents: PaperAgents, fetched: str, docker: Docker
    ) -> None:
        docker.usable = (False, "Start Docker and try again.")

        found = agents.environment(fetched)

        assert found["docker"] == {"ready": False, "message": "Start Docker and try again."}
        assert found["recipe"] is not None


class TestBuilding:
    def test_the_environment_is_built_as_a_job_and_what_was_built_is_kept(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        started = agents.build_environment(fetched, minutes=12, gigabytes=3)
        assert (started.kind, started.subject) == (ENVIRONMENT_JOB, fetched)
        assert started.title == "Building the environment: CellMapper"
        job = finish(started)

        assert job.state == "succeeded"
        assert job.message.startswith("Built the environment with Python 3.11.9: 2 packages in ")
        assert any("Install the project itself" in line for line in job.snapshot(0)["log"]["lines"])
        (made,) = docker.builds
        assert made["tag"] == tag_of(fetched) and made["label"] == fetched
        assert made["limits"] == building.Limits(12, 3)
        assert made["scratch_is_empty"] is True and made["stop"] is started.stop
        assert docker.cleaned == [fetched] and tag_of(fetched) in docker.removed
        found = agents.environment(fetched)
        record = found["built"]
        assert record["commit"] == COMMIT and record["url"] == URL
        assert record["image"] == {
            "tag": tag_of(fetched),
            "id": docker.images[tag_of(fetched)],
            "base_id": "sha256:" + "b" * 64,
            "base_digests": ["python@sha256:" + "c" * 64],
            "architecture": "arm64",
            "size_bytes": 180_000_000,
            "added_bytes": 130_000_000,
        }
        assert (record["python"], record["lock"], record["pip_check"]) == (
            "3.11.9",
            {"name": "pip-freeze.txt", "packages": 2},
            {"ok": True, "problems": []},
        )
        assert record["limits"]["minutes"] == 12 and record["recipe"]["kind"] == "conda"
        assert record["image_present"] is True
        assert found["failure"] is None and found["has_log"] is True
        assert step_of(agents, fetched) == "done"
        assert agents.view(fetched)["steps"]["environment"] == "done"
        assert directory_of(workspace, fetched).joinpath("env", "environment.json").is_file()

    def test_the_code_that_is_built_is_the_code_that_was_fetched(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        build(agents, fetched)

        files = docker.builds[0]["files"]
        assert "environment.yml" in files and "setup.py" in files

    def test_the_lock_and_the_log_are_kept(self, agents: PaperAgents, fetched: str) -> None:
        build(agents, fetched)

        assert agents.environment_lock(fetched) == {"name": "pip-freeze.txt", "text": "numpy==1.26.4\nsix==1.16.0\n"}
        assert agents.environment_log(fetched)["lines"] == [
            "Starting from python:3.11-slim",
            "== Install the project itself",
        ]

    def test_there_is_one_environment_at_a_time(self, agents: PaperAgents, fetched: str, docker: Docker) -> None:
        build(agents, fetched)

        error = refused(agents.build_environment, fetched)

        assert (error.status, error.code) == (409, "done")
        assert len(docker.builds) == 1

    def test_the_code_has_to_be_fetched_first(self, agents: PaperAgents, docker: Docker) -> None:
        error = refused(agents.build_environment, agent_of(agents))

        assert (error.status, error.code) == (422, "no_code")
        assert docker.builds == []

    def test_docker_has_to_be_running(self, agents: PaperAgents, fetched: str, docker: Docker) -> None:
        docker.usable = (False, "Docker is installed but its daemon is not running.")

        error = refused(agents.build_environment, fetched)

        assert (error.status, error.code) == (422, "docker_missing")
        assert "daemon is not running" in error.message

    def test_what_is_given_is_checked_before_anything_starts(
        self, agents: PaperAgents, fetched: str, docker: Docker
    ) -> None:
        for options in (
            {"python": "2.7"},
            {"system_packages": ["x; reboot"]},
            {"minutes": 0},
            {"minutes": 10_000},
            {"gigabytes": 1.5},
            {"gigabytes": True},
        ):
            error = refused(agents.build_environment, fetched, **options)
            assert (error.status, error.code) == (422, "invalid"), options
        assert docker.builds == []

    def test_a_project_that_is_not_built_here_is_refused_with_why(
        self, agents: PaperAgents, remote: Remote, docker: Docker
    ) -> None:
        remote.files = {"renv.lock": "{}", "analysis.R": "library(Seurat)\n"}
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        error = refused(agents.build_environment, agent_id)

        assert (error.status, error.code) == (422, "unsupported")
        assert error.details["reason"] == "r"
        assert docker.builds == []

    def test_a_python_is_taken_where_the_code_does_not_say_which(
        self, agents: PaperAgents, remote: Remote, docker: Docker
    ) -> None:
        remote.files = {"requirements.txt": "numpy\n"}
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        build(agents, agent_id, python="3.9", system_packages=["libhdf5-dev"])

        recipe = docker.builds[0]["recipe"]
        assert (recipe.python, recipe.system_packages) == ("3.9", ("libhdf5-dev",))

    def test_the_limits_default_to_what_is_said_to_be_the_default(
        self, agents: PaperAgents, fetched: str, docker: Docker
    ) -> None:
        build(agents, fetched)

        assert docker.builds[0]["limits"] == building.Limits(building.DEFAULT_MINUTES, building.DEFAULT_GIGABYTES)

    def test_nothing_in_the_code_is_run_by_the_server(self, agents: PaperAgents, fetched: str, marker: Path) -> None:
        build(agents, fetched)

        assert not marker.exists()


class TestFailing:
    def failure(self) -> building.EnvironmentBuildError:
        return building.EnvironmentBuildError(
            building.classify(f"Collecting x\n{FAILING_INSTALL}\nerror: subprocess-exited-with-error", "project", 1)
        )

    def test_a_build_that_fails_says_why_and_keeps_its_output(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        docker.error = self.failure()

        job = build(agents, fetched)

        assert job.state == "failed"
        assert job.error.startswith("A system library is missing.")
        found = agents.environment(fetched)
        assert found["built"] is None
        failure = found["failure"]
        assert failure["commit"] == COMMIT
        assert failure["failure"]["kind"] == "missing_system_library"
        assert failure["failure"]["system_packages"] == ["zlib1g-dev"]
        assert failure["failure"]["step"] == "project"
        assert any("zlib.h" in line for line in failure["failure"]["tail"])
        assert failure["recipe"]["kind"] == "conda" and failure["limits"]["minutes"] == 30
        assert found["has_log"] is True
        assert agents.environment_log(fetched)["lines"] == [
            "Starting from python:3.11-slim",
            "== Install the project itself",
        ]
        assert step_of(agents, fetched) == "failed"
        assert agents.view(fetched)["steps"]["environment"] == "failed"
        assert docker.images == {}

    def test_it_can_be_tried_again_and_a_success_takes_the_failure_away(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        docker.error = self.failure()
        build(agents, fetched)
        docker.error = None

        job = build(agents, fetched, system_packages=["zlib1g-dev"])

        assert job.state == "succeeded"
        found = agents.environment(fetched)
        assert found["failure"] is None and found["built"] is not None
        assert not directory_of(workspace, fetched).joinpath("env", "failure.json").exists()
        assert step_of(agents, fetched) == "done"

    def test_a_failure_of_the_server_is_a_failed_job_and_not_an_environment(
        self, agents: PaperAgents, fetched: str, docker: Docker
    ) -> None:
        docker.error = RuntimeError("Docker could not make the container: no space left on device")

        job = build(agents, fetched)

        assert job.state == "failed" and "no space left" in job.error
        assert agents.environment(fetched)["failure"] is None
        assert step_of(agents, fetched) == "failed"

    def test_a_build_that_is_stopped_keeps_nothing(
        self, agents: PaperAgents, fetched: str, docker: Docker, jobs: Jobs
    ) -> None:
        docker.gate = threading.Event()
        started = agents.build_environment(fetched)
        assert docker.started.wait(10)
        assert agents.view(fetched)["steps"]["environment"] == "running"

        jobs.stop(started.id)
        job = finish(started)

        assert job.state == "stopped"
        found = agents.environment(fetched)
        assert (found["built"], found["failure"], found["has_log"]) == (None, None, False)
        assert step_of(agents, fetched) == "pending"

    def test_a_failure_for_another_commit_is_not_shown(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        docker.error = self.failure()
        build(agents, fetched)
        path = directory_of(workspace, fetched) / "env" / "failure.json"
        kept = json.loads(path.read_text())
        path.write_text(json.dumps({**kept, "commit": "f" * 40}))

        assert agents.environment(fetched)["failure"] is None

    def test_a_failure_that_was_edited_into_nonsense_is_not_shown(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        docker.error = self.failure()
        build(agents, fetched)
        path = directory_of(workspace, fetched) / "env" / "failure.json"
        kept = json.loads(path.read_text())
        for edited in (
            {**kept, "failure": {**kept["failure"], "kind": "whatever"}},
            {**kept, "failure": None},
            {**kept, "schema": 2},
            [],
        ):
            path.write_text(json.dumps(edited))
            assert agents.environment(fetched)["failure"] is None


class TestWhileBuilding:
    def test_what_would_change_the_code_or_the_agent_waits(
        self, agents: PaperAgents, fetched: str, docker: Docker, jobs: Jobs
    ) -> None:
        docker.gate = threading.Event()
        started = agents.build_environment(fetched)
        assert docker.started.wait(10)

        for call in (
            lambda: agents.delete(fetched),
            lambda: agents.clear_repository(fetched),
            lambda: agents.clear_environment(fetched),
            lambda: agents.fetch_repository(fetched),
            lambda: agents.build_environment(fetched),
            lambda: agents.change(fetched, repo="https://github.com/example/plots"),
            lambda: agents.read(fetched, 1),
        ):
            error = refused(call)
            assert (error.status, error.code) == (409, "busy")
            assert error.details["job"]["id"] == started.id
        assert agents.environment(fetched)["job"]["id"] == started.id
        docker.gate.set()
        assert finish(started).state == "succeeded"

    def test_the_title_can_still_be_changed(self, agents: PaperAgents, fetched: str, docker: Docker) -> None:
        docker.gate = threading.Event()
        started = agents.build_environment(fetched)
        assert docker.started.wait(10)

        agents.change(fetched, title="CellMapper, the second")

        docker.gate.set()
        finish(started)
        assert agents.view(fetched)["title"] == "CellMapper, the second"

    def test_the_code_that_is_changed_under_a_build_is_not_given_an_environment_it_did_not_make(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        directory = directory_of(workspace, fetched)

        def another_commit() -> None:
            intake = json.loads((directory / kept_repository.INTAKE_FILE).read_text())
            (directory / kept_repository.INTAKE_FILE).write_text(json.dumps({**intake, "commit": "e" * 40}))

        docker.during = another_commit

        job = build(agents, fetched)

        assert job.state == "failed" and "changed while the environment was built" in job.error
        assert docker.images == {}
        assert not (directory / "env" / "environment.json").exists()


class TestKept:
    def test_an_environment_is_of_the_commit_it_was_built_from(
        self, agents: PaperAgents, workspace: Workspace, fetched: str
    ) -> None:
        build(agents, fetched)
        path = directory_of(workspace, fetched) / "env" / "environment.json"
        kept = json.loads(path.read_text())
        path.write_text(json.dumps({**kept, "commit": "a" * 40}))

        found = agents.environment(fetched)

        assert found["built"] is None
        assert refused(agents.environment_lock, fetched).status == 404

    def test_a_record_that_was_edited_into_nonsense_is_not_shown(
        self, agents: PaperAgents, workspace: Workspace, fetched: str
    ) -> None:
        build(agents, fetched)
        path = directory_of(workspace, fetched) / "env" / "environment.json"
        kept = json.loads(path.read_text())
        for edited in (
            {**kept, "image": {**kept["image"], "id": "not-a-hash"}},
            {**kept, "lock": {"name": "../../agent.json", "packages": 1}},
            {**kept, "recipe": {"kind": "shell", "steps": []}},
            {**kept, "schema": 7},
            {**kept, "duration": "long"},
            "text",
        ):
            path.write_text(json.dumps(edited))
            assert agents.environment(fetched)["built"] is None

    def test_a_record_without_its_lock_is_not_shown(
        self, agents: PaperAgents, workspace: Workspace, fetched: str
    ) -> None:
        build(agents, fetched)
        (directory_of(workspace, fetched) / "env" / "pip-freeze.txt").unlink()

        assert agents.environment(fetched)["built"] is None

    def test_an_image_that_is_gone_from_docker_is_said_to_be(
        self, agents: PaperAgents, fetched: str, docker: Docker
    ) -> None:
        build(agents, fetched)

        docker.images.clear()
        assert agents.environment(fetched)["built"]["image_present"] is False
        docker.images[tag_of(fetched)] = "sha256:" + "9" * 64
        assert agents.environment(fetched)["built"]["image_present"] is False
        docker.usable = (False, "Docker is not running.")
        assert agents.environment(fetched)["built"]["image_present"] is None

    def test_what_is_kept_is_in_the_agents_own_directory(
        self, agents: PaperAgents, workspace: Workspace, fetched: str
    ) -> None:
        build(agents, fetched)

        assert sorted(path.name for path in (directory_of(workspace, fetched) / "env").iterdir()) == [
            "build.log",
            "environment.json",
            "pip-freeze.txt",
        ]


class TestRemoving:
    def test_the_environment_is_taken_away_with_its_image(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        build(agents, fetched)
        docker.removed.clear()

        agents.clear_environment(fetched)

        assert docker.removed == [tag_of(fetched)] and docker.images == {}
        assert not (directory_of(workspace, fetched) / "env").exists()
        found = agents.environment(fetched)
        assert (found["built"], found["has_log"], found["recipe"] is not None) == (None, False, True)
        assert step_of(agents, fetched) == "pending"
        build(agents, fetched)
        assert len(docker.builds) == 2

    def test_the_image_is_taken_by_the_name_the_agent_and_the_commit_make_and_not_by_the_file(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        build(agents, fetched)
        path = directory_of(workspace, fetched) / "env" / "environment.json"
        kept = json.loads(path.read_text())
        path.write_text(json.dumps({**kept, "image": {**kept["image"], "tag": "ubuntu:latest"}}))
        docker.removed.clear()

        agents.clear_environment(fetched)

        assert docker.removed == [tag_of(fetched)]

    def test_an_image_that_docker_would_not_remove_keeps_its_account(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        build(agents, fetched)
        docker.refuses = True

        error = refused(agents.clear_environment, fetched)

        assert (error.status, error.code) == (409, "docker")
        assert (directory_of(workspace, fetched) / "env" / "environment.json").is_file()
        assert agents.environment(fetched)["built"] is not None
        docker.refuses = False
        agents.clear_environment(fetched)
        assert agents.environment(fetched)["built"] is None

    def test_clearing_where_there_is_none_is_not_an_error(
        self, agents: PaperAgents, fetched: str, docker: Docker
    ) -> None:
        agents.clear_environment(fetched)

        assert docker.removed == []

    def test_a_failure_is_taken_away_too(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        docker.error = TestFailing().failure()
        build(agents, fetched)

        agents.clear_environment(fetched)

        assert agents.environment(fetched)["failure"] is None
        assert step_of(agents, fetched) == "pending"

    def test_taking_away_the_code_takes_the_environment_with_it(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        build(agents, fetched)

        agents.clear_repository(fetched)

        assert docker.images == {} and tag_of(fetched) in docker.removed
        assert not (directory_of(workspace, fetched) / "env").exists()
        assert step_of(agents, fetched) == "pending"
        assert agents.view(fetched)["steps"]["repository"] == "pending"

    def test_changing_where_the_code_is_takes_the_environment_with_it(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        build(agents, fetched)

        agents.change(fetched, repo="https://github.com/example/plots")

        assert docker.images == {}
        assert not (directory_of(workspace, fetched) / "env").exists()
        assert step_of(agents, fetched) == "pending"

    def test_keeping_the_same_address_keeps_the_environment(
        self, agents: PaperAgents, fetched: str, docker: Docker
    ) -> None:
        build(agents, fetched)

        agents.change(fetched, repo=URL)

        assert len(docker.images) == 1 and agents.environment(fetched)["built"] is not None

    def test_deleting_the_agent_takes_the_image_away(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        build(agents, fetched)

        agents.delete(fetched)

        assert docker.images == {}
        assert not directory_of(workspace, fetched).exists()

    def test_an_agent_whose_image_cannot_be_removed_is_not_deleted(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        build(agents, fetched)
        docker.refuses = True

        error = refused(agents.delete, fetched)

        assert (error.status, error.code) == (409, "docker")
        assert directory_of(workspace, fetched).is_dir()

    def test_an_agent_that_never_had_an_environment_is_deleted_with_docker_never_asked(
        self, agents: PaperAgents, fetched: str, docker: Docker
    ) -> None:
        agents.delete(fetched)

        assert docker.removed == []

    def test_fetching_the_code_again_takes_an_environment_that_was_left_away(
        self, agents: PaperAgents, workspace: Workspace, fetched: str, docker: Docker
    ) -> None:
        build(agents, fetched)
        directory = directory_of(workspace, fetched)
        # The code is gone but the environment was not taken away, as when the server was stopped between the two
        kept_repository.forget(directory)
        agents.save(directory, {**agents.lookup(fetched)[1], "steps": steps_of(agents.lookup(fetched)[1])})

        fetch(agents, fetched)

        assert docker.images == {}
        assert agents.environment(fetched)["built"] is None


class TestOverHttp:
    def test_building_asking_and_removing(self, client: TestClient, remote: Remote, docker: Docker, jobs: Jobs) -> None:
        made = client.post(
            "/api/paperagents",
            json={"title": "CellMapper", "paper": {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}, "repo": URL},
        )
        agent_id = made.json()["id"]
        client.post(f"/api/paperagents/{agent_id}/repository", json={})
        deadline = time.monotonic() + 20
        while client.get(f"/api/paperagents/{agent_id}").json()["steps"]["repository"] != "done":
            assert time.monotonic() < deadline
            time.sleep(0.02)

        asked = client.get(f"/api/paperagents/{agent_id}/environment", params={"system_packages": ["libhdf5-dev"]})
        assert asked.status_code == 200
        assert asked.json()["recipe"]["system_packages"] == ["libhdf5-dev"]
        assert client.get(f"/api/paperagents/{agent_id}/environment", params={"python": "9.9"}).status_code == 422

        started = client.post(f"/api/paperagents/{agent_id}/environment", json={"minutes": 5, "gigabytes": 2})
        assert started.status_code == 202
        assert started.json()["kind"] == ENVIRONMENT_JOB
        deadline = time.monotonic() + 20
        while client.get(f"/api/paperagents/{agent_id}").json()["steps"]["environment"] != "done":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert docker.builds[0]["limits"] == building.Limits(5, 2)

        shown = client.get(f"/api/paperagents/{agent_id}/environment").json()
        assert shown["built"]["image"]["id"].startswith("sha256:") and shown["built"]["image_present"] is True
        assert client.get(f"/api/paperagents/{agent_id}/environment/lock").json()["name"] == "pip-freeze.txt"
        assert client.get(f"/api/paperagents/{agent_id}/environment/log").json()["lines"][0].startswith("Starting")
        again = client.post(f"/api/paperagents/{agent_id}/environment", json={})
        assert (again.status_code, again.json()["error"]["code"]) == (409, "done")

        removed = client.delete(f"/api/paperagents/{agent_id}/environment")
        assert removed.status_code == 200 and removed.json()["built"] is None
        assert client.get(f"/api/paperagents/{agent_id}/environment/lock").status_code == 404
        assert client.get(f"/api/paperagents/{agent_id}/environment/log").status_code == 404
        assert docker.images == {}

    def test_a_body_that_is_not_what_is_asked_for_is_refused(self, client: TestClient, docker: Docker) -> None:
        made = client.post(
            "/api/paperagents",
            json={"title": "CellMapper", "paper": {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}},
        )
        agent_id = made.json()["id"]

        for body in ({"minutes": "5"}, {"python": 3.9}, {"system_packages": "libhdf5-dev"}, {"surprise": 1}):
            assert client.post(f"/api/paperagents/{agent_id}/environment", json=body).status_code == 422, body

    def test_it_is_not_there_without_the_token_or_for_an_agent_that_is_not(self, client: TestClient) -> None:
        assert client.get("/api/paperagents/nothing/environment").status_code == 404
        assert client.post("/api/paperagents/nothing/environment", json={}).status_code == 404
        assert client.get("/api/paperagents/nothing/environment/lock").status_code == 404
        assert client.delete("/api/paperagents/nothing/environment").status_code == 404
        bare = TestClient(client.app, base_url=LOCAL)
        assert bare.get("/api/paperagents/nothing/environment").status_code == 401
