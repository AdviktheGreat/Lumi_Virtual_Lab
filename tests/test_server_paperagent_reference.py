"""Tests of running the tutorials of a PaperAgent's code: what would be run and why the rest would not, the job that
runs them and what it is given, what is kept and for which commit and image, what the other operations do while it runs
and after, and that what was run goes with the environment it was run in. Docker and its containers are replaced by
stand-ins, so what the server does is what is looked at here; the real runs are in test_paperagents_reference."""

import hashlib
import json
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import test_server_paperagent_environment as environment
from fastapi.testclient import TestClient
from test_paperagents_reference import call_of, failure_of, kept_file, result_of
from test_server_paperagent_environment import (
    COMMIT,
    LOCAL,
    URL,
    Docker,
    Remote,
    agent_of,
    build,
    directory_of,
    fetch,
    finish,
    refused,
    tag_of,
)

from virtual_lab.execution import DockerUnavailableError
from virtual_lab.paperagents import data as finding
from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import reference as referencing
from virtual_lab.server import paperagent_data as kept_data
from virtual_lab.server import paperagent_reference as kept_reference
from virtual_lab.server.paperagents import REFERENCE_JOB, PaperAgents, steps_of
from virtual_lab.server.workspace import Workspace

# What the tests of building an environment are made with, which are fixtures of that module
agents = environment.agents
client = environment.client
docker = environment.docker
git_is_installed = environment.git_is_installed
jobs = environment.jobs
marker = environment.marker
remote = environment.remote
workspace = environment.workspace

Play = Callable[[int, Path, referencing.Item], tuple[str, int | None, str]]

NOTEBOOK = "tutorials/quickstart.ipynb"
SCRIPT = "examples/analyse.py"
SKIPPED = "examples/plots.R"


class Containers:
    """Stands in for the containers that tutorials run in: what a run is told, and what it did, are what is set here."""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.plays: dict[str, Play] = {}
        self.gates: dict[str, threading.Event] = {}
        self.began: defaultdict[str, threading.Event] = defaultdict(threading.Event)
        self.counts: defaultdict[str, int] = defaultdict(int)

    def execute(
        self, runner: referencing.Runner, folder: Path, item: referencing.Item, seconds: float
    ) -> tuple[str, int | None, str]:
        self.counts[item.path] += 1
        self.runs.append(
            {
                "path": item.path,
                "seconds": seconds,
                "data": runner.data,
                "label": runner.label,
                "tag": runner.tag,
                "limits": runner.limits,
                "scratch": runner.scratch,
            }
        )
        self.began[item.path].set()
        gate = self.gates.get(item.path)
        if gate is not None:
            while not gate.wait(0.01):
                if runner.stop.is_set():
                    return "stopped", None, ""

        return self.plays.get(item.path, good)(self.counts[item.path], folder, item)

    def paths(self) -> list[str]:
        return [run["path"] for run in self.runs]


def writes(result: dict[str, Any], files: dict[str, bytes] | None = None, text: str = "printed") -> Play:
    def play(count: int, folder: Path, item: referencing.Item) -> tuple[str, int | None, str]:
        where = folder / referencing.RESULT_FOLDER
        where.mkdir()
        (where / "result.json").write_text(json.dumps({**result, "kind": item.kind, "path": item.path}))
        for name, data in (files or {}).items():
            (where / "files" / name).parent.mkdir(parents=True, exist_ok=True)
            (where / "files" / name).write_bytes(data)

        return "done", 0 if result["ok"] else 1, text

    return play


def good(count: int, folder: Path, item: referencing.Item) -> tuple[str, int | None, str]:
    return writes(result_of(calls=[call_of("map_cells", {"counts": [1, 2]}, [1, 2])]))(count, folder, item)


@pytest.fixture
def containers(monkeypatch: pytest.MonkeyPatch) -> Containers:
    stand_in = Containers()
    monkeypatch.setattr(referencing.Runner, "execute", lambda *arguments: stand_in.execute(*arguments))
    monkeypatch.setattr(building, "cpus_for", lambda *arguments, **options: "2")

    return stand_in


@pytest.fixture
def prepared(agents: PaperAgents, remote: Remote, docker: Docker, containers: Containers) -> str:
    """An agent whose code has been fetched and environment built, with two tutorials in Python and one in R."""
    remote.files = {**remote.files, SCRIPT: "print(1)\n", SKIPPED: "plot(1)\n"}
    agent_id = agent_of(agents)
    fetch(agents, agent_id)
    build(agents, agent_id)

    return agent_id


def why(call: Any, *args: Any, **kwargs: Any) -> tuple[int, str]:
    error = refused(call, *args, **kwargs)

    return error.status, error.code


def run(agents: PaperAgents, agent_id: str, **options: Any) -> Any:
    return finish(agents.start_reference(agent_id, **options))


def step_of(agents: PaperAgents, agent_id: str) -> str:
    return steps_of(agents.lookup(agent_id)[1])["tools"]


def keep_data(workspace: Workspace, agent_id: str) -> bytes:
    """Puts a file that was fetched where the agent's data is kept, as fetching would."""
    directory = directory_of(workspace, agent_id)
    reference = finding.Reference("zenodo", "1234567")
    content = b"gene,count\nA,1\n"
    file = {
        "name": "counts.csv",
        "path": f"{finding.folder_of(reference)}/counts.csv",
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "checksum": None,
        "url": "https://zenodo.org/records/1234567/files/counts.csv",
        "fetched_at": "2026-01-01T00:00:00Z",
    }
    target = kept_data.data_path(directory) / file["path"]
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    kept_data.save(directory, kept_data.with_file(kept_data.load(directory), reference, "Zenodo", "Counts", None, file))

    return content


class TestWhatWouldBeRun:
    def test_there_is_nothing_to_run_until_the_code_is_fetched_and_the_environment_built(
        self, agents: PaperAgents, docker: Docker, containers: Containers
    ) -> None:
        agent_id = agent_of(agents)
        found = agents.reference(agent_id)

        assert (found["commit"], found["plan"], found["kept"], found["job"], found["data"]) == (None,) * 5
        assert found["environment"] == {"built": False, "image_present": None}
        assert found["docker"] == {"ready": True, "message": None}
        assert found["meaning"].endswith("does not show that what it gave is right.")
        limits = found["limits"]
        assert (limits["default_minutes"], limits["max_total_minutes"], limits["default_repeats"]) == (10, 240, 2)
        assert (limits["memory"], limits["pids"]) == ("8g", 1024)
        assert why(agents.start_reference, agent_id) == (422, "no_code")

    def test_the_python_tutorials_are_listed_and_the_others_say_why_they_are_not(
        self, agents: PaperAgents, remote: Remote, docker: Docker, containers: Containers
    ) -> None:
        remote.files = {**remote.files, SCRIPT: "print(1)\n", SKIPPED: "plot(1)\n"}
        agent_id = agent_of(agents)
        fetch(agents, agent_id)
        found = agents.reference(agent_id)

        assert found["commit"] == COMMIT and found["environment"] == {"built": False, "image_present": None}
        assert sorted(item["path"] for item in found["plan"]["runnable"]) == [SCRIPT, NOTEBOOK]
        assert [(item["path"], "R" in item["reason"]) for item in found["plan"]["skipped"]] == [(SKIPPED, True)]
        assert why(agents.start_reference, agent_id) == (422, "no_environment")
        json.dumps(found)

    def test_a_project_with_no_python_tutorial_is_refused(
        self, agents: PaperAgents, remote: Remote, docker: Docker, containers: Containers
    ) -> None:
        remote.files = {"README.md": "# x\n", "environment.yml": "name: x\ndependencies:\n  - python=3.11\n"}
        agent_id = agent_of(agents)
        fetch(agents, agent_id)
        build(agents, agent_id)

        assert why(agents.start_reference, agent_id) == (422, "no_tutorials")


class TestRunning:
    def test_the_tutorials_are_run_in_the_environment_and_what_they_did_is_kept_for_it(
        self, agents: PaperAgents, prepared: str, docker: Docker, containers: Containers, workspace: Workspace
    ) -> None:
        job = run(agents, prepared)

        assert job.state == "succeeded" and job.kind == REFERENCE_JOB
        assert job.message is not None and job.message.startswith("Ran 2 tutorials: 2 to the end, 0 not.")
        assert "2 gave the same each time" in job.message
        image = docker.images[tag_of(prepared)]
        found = agents.reference(prepared)
        kept = found["kept"]
        assert (kept["commit"], kept["image_id"], kept["complete"]) == (COMMIT, image, True)
        assert kept["finished_at"] is not None and kept["not_run"] == [] and kept["more"] == 0
        assert [one["path"] for one in kept["tutorials"]] == containers.paths()[::2]
        assert {one["status"] for one in kept["tutorials"]} == {"ok"}
        assert {(one["runs"], one["stable"], one["calls"]) for one in kept["tutorials"]} == {(2, True, 1)}
        assert [item["path"] for item in kept["skipped"]] == [SKIPPED]
        assert containers.counts == {NOTEBOOK: 2, SCRIPT: 2}
        assert {run["tag"] for run in containers.runs} == {tag_of(prepared)}
        assert {run["label"] for run in containers.runs} == {prepared}
        assert referencing.Limits() == containers.runs[0]["limits"] and containers.runs[0]["data"] is None
        assert containers.runs[0]["scratch"].parent == workspace.root
        assert not containers.runs[0]["scratch"].exists()
        json.dumps(found)

    def test_one_tutorial_is_kept_with_the_calls_it_made_into_the_code(
        self, agents: PaperAgents, prepared: str, containers: Containers
    ) -> None:
        run(agents, prepared)
        listed = agents.reference(prepared)["kept"]["tutorials"]
        detail = agents.reference_tutorial(prepared, listed[0]["id"])

        assert referencing.is_detail(detail) and detail["status"] == "ok"
        assert [call["qualname"] for call in detail["calls"]] == ["map_cells"]
        assert detail["calls"][0]["args"]["counts"]["value"] == [1, 2] and detail["output"] == ["printed"]
        assert why(agents.reference_tutorial, prepared, "99-nothing") == (404, "not_found")
        assert why(agents.reference_tutorial, prepared, "..") == (404, "not_found")

    def test_the_files_a_tutorial_wrote_are_kept_when_they_are_small(
        self, agents: PaperAgents, prepared: str, containers: Containers, workspace: Workspace
    ) -> None:
        data = b"cell,type\n1,T\n"
        done = result_of(files=[kept_file("out/table.csv", data)])
        containers.plays[NOTEBOOK] = writes(done, {"out/table.csv": data})
        containers.plays[SCRIPT] = writes(done, {"out/table.csv": data})
        run(agents, prepared, repeats=1)

        directory = directory_of(workspace, prepared)
        first = agents.reference(prepared)["kept"]["tutorials"][0]["id"]
        assert (kept_reference.files_path(directory, first) / "out/table.csv").read_bytes() == data
        assert agents.reference_tutorial(prepared, first)["files"][0]["kept"] is True

    def test_a_tutorial_that_failed_is_kept_with_why_and_the_others_are_still_run(
        self, agents: PaperAgents, prepared: str, containers: Containers
    ) -> None:
        containers.plays[NOTEBOOK] = writes(
            result_of(ok=False, error=failure_of("FileNotFoundError", message="x.h5ad"))
        )
        job = run(agents, prepared)

        assert job.state == "succeeded" and job.message is not None
        assert job.message.startswith("Ran 2 tutorials: 1 to the end, 1 not.")
        by_path = {one["path"]: one for one in agents.reference(prepared)["kept"]["tutorials"]}
        assert by_path[NOTEBOOK]["status"] == "failed" and by_path[NOTEBOOK]["failure"]["kind"] == "missing_file"
        assert by_path[NOTEBOOK]["runs"] == 1 and by_path[NOTEBOOK]["stable"] is None
        assert by_path[SCRIPT]["status"] == "ok"
        assert containers.counts == {NOTEBOOK: 1, SCRIPT: 2}

    def test_a_tutorial_that_gives_something_else_each_time_is_not_said_to_be_stable(
        self, agents: PaperAgents, prepared: str, containers: Containers
    ) -> None:
        def different(count: int, folder: Path, item: referencing.Item) -> tuple[str, int | None, str]:
            return writes(result_of(calls=[call_of("map_cells", {"counts": [count]}, [count])]))(count, folder, item)

        containers.plays[SCRIPT] = different
        run(agents, prepared)

        by_path = {one["path"]: one for one in agents.reference(prepared)["kept"]["tutorials"]}
        assert by_path[SCRIPT]["stable"] is False and "calls" in by_path[SCRIPT]["differs"]
        assert by_path[NOTEBOOK]["stable"] is True

    def test_the_limits_that_were_given_are_the_ones_the_runs_keep_to(
        self, agents: PaperAgents, prepared: str, containers: Containers
    ) -> None:
        run(agents, prepared, minutes=3, total_minutes=7, tutorials=1, repeats=1, gigabytes=4)

        assert containers.counts == {NOTEBOOK: 1} or containers.counts == {SCRIPT: 1}
        assert containers.runs[0]["limits"] == referencing.Limits(3, 7, 1, 1, 4)
        assert containers.runs[0]["seconds"] <= 180
        kept = agents.reference(prepared)["kept"]
        assert kept["limits"]["tutorials"] == 1 and len(kept["not_run"]) == 1
        assert "Only 1 tutorials are run" in kept["not_run"][0]["reason"]

    @pytest.mark.parametrize(
        "options",
        [
            {"minutes": 0},
            {"minutes": 61},
            {"total_minutes": 241},
            {"tutorials": 26},
            {"repeats": 4},
            {"gigabytes": 21},
            {"minutes": "5"},
            {"minutes": True},
            {"use_data": "yes"},
        ],
    )
    def test_limits_that_are_not_allowed_are_refused_before_anything_is_run(
        self, agents: PaperAgents, prepared: str, containers: Containers, options: dict[str, Any]
    ) -> None:
        assert why(agents.start_reference, prepared, **options) == (422, "invalid")
        assert containers.runs == [] and agents.reference(prepared)["kept"] is None

    def test_the_data_that_was_fetched_is_given_to_the_runs_to_read_unless_it_is_not_wanted(
        self, agents: PaperAgents, prepared: str, containers: Containers, workspace: Workspace
    ) -> None:
        keep_data(workspace, prepared)
        directory = directory_of(workspace, prepared)
        found = agents.reference(prepared)
        assert found["data"] == {"files": 1, "bytes": 15}

        run(agents, prepared, repeats=1)
        assert {run["data"] for run in containers.runs} == {kept_data.data_path(directory)}
        assert agents.reference(prepared)["kept"]["data"] == {"files": 1, "bytes": 15}

        agents.clear_reference(prepared)
        containers.runs.clear()
        run(agents, prepared, repeats=1, use_data=False)
        assert {run["data"] for run in containers.runs} == {None}
        assert agents.reference(prepared)["kept"]["data"] is None

    def test_data_that_is_only_a_note_of_what_stands_in_is_not_given(
        self, agents: PaperAgents, prepared: str, containers: Containers, workspace: Workspace
    ) -> None:
        directory = directory_of(workspace, prepared)
        record = kept_data.load(directory)
        kept_data.save(
            directory,
            {**record, "stand_ins": [{"key": "zenodo:1", "name": "Counts", "own": "counts", "set_at": "2026-01-01"}]},
        )
        run(agents, prepared, repeats=1)

        assert {run["data"] for run in containers.runs} == {None}

    def test_docker_that_is_not_running_is_said_and_nothing_is_run(
        self, agents: PaperAgents, prepared: str, docker: Docker, containers: Containers
    ) -> None:
        docker.usable = (False, "Docker is not running.")

        error = refused(agents.start_reference, prepared)
        assert (error.status, error.code) == (422, "docker_missing") and "not running" in error.message
        assert agents.reference(prepared)["docker"] == {"ready": False, "message": "Docker is not running."}
        assert containers.runs == []

    def test_an_image_that_is_gone_from_docker_is_said_and_nothing_is_run(
        self, agents: PaperAgents, prepared: str, docker: Docker, containers: Containers
    ) -> None:
        docker.images.clear()

        assert why(agents.start_reference, prepared) == (409, "image_missing")
        assert agents.reference(prepared)["environment"] == {"built": True, "image_present": False}
        assert containers.runs == []

    def test_leftover_containers_of_the_agent_are_taken_away_before_a_run(
        self, agents: PaperAgents, prepared: str, docker: Docker, containers: Containers
    ) -> None:
        docker.runs_cleaned.clear()
        run(agents, prepared, repeats=1)

        assert docker.runs_cleaned == [prepared]

    def test_what_is_kept_is_not_run_again_until_it_is_taken_away(
        self, agents: PaperAgents, prepared: str, containers: Containers
    ) -> None:
        run(agents, prepared, repeats=1)

        assert why(agents.start_reference, prepared) == (409, "done")
        agents.clear_reference(prepared)
        assert agents.reference(prepared)["kept"] is None
        assert why(agents.reference_tutorial, prepared, "01-examples-analyse-py") == (404, "not_found")
        run(agents, prepared, repeats=1)
        assert agents.reference(prepared)["kept"]["complete"] is True


class TestWhenItGoesWrong:
    def test_a_run_that_is_stopped_keeps_what_it_had_done_and_can_be_started_again(
        self, agents: PaperAgents, prepared: str, containers: Containers
    ) -> None:
        first, second = (item["path"] for item in agents.reference(prepared)["plan"]["runnable"])
        containers.gates[second] = threading.Event()
        job = agents.start_reference(prepared, repeats=1)
        assert containers.began[second].wait(10)
        assert agents.view(prepared)["steps"]["tools"] == "running"
        job.request_stop()
        finish(job)

        assert job.state == "stopped"
        kept = agents.reference(prepared)["kept"]
        assert kept["complete"] is False and kept["finished_at"] is None
        assert [one["path"] for one in kept["tutorials"]] == [first]
        assert agents.reference_tutorial(prepared, kept["tutorials"][0]["id"])["status"] == "ok"
        assert step_of(agents, prepared) == "pending"

        del containers.gates[second]
        run(agents, prepared, repeats=1)
        kept = agents.reference(prepared)["kept"]
        assert kept["complete"] is True and [one["path"] for one in kept["tutorials"]] == [first, second]

    def test_docker_that_stops_answering_fails_the_job_and_does_not_blame_the_tutorial(
        self, agents: PaperAgents, prepared: str, containers: Containers
    ) -> None:
        def broken(count: int, folder: Path, item: referencing.Item) -> tuple[str, int | None, str]:
            raise DockerUnavailableError("Docker did not run the tutorial: Cannot connect to the Docker daemon")

        containers.plays[NOTEBOOK] = broken
        containers.plays[SCRIPT] = broken
        job = run(agents, prepared)

        assert job.state == "failed" and job.error is not None and "Cannot connect" in job.error
        kept = agents.reference(prepared)["kept"]
        assert kept["complete"] is False and kept["tutorials"] == []
        assert step_of(agents, prepared) == "failed"
        agents.clear_reference(prepared)
        assert step_of(agents, prepared) == "pending" and agents.reference(prepared)["kept"] is None

    def test_when_the_time_for_all_of_the_runs_is_used_the_tutorials_not_run_are_listed_with_that(
        self, agents: PaperAgents, prepared: str, containers: Containers, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(referencing, "LEAST_SECONDS", 10_000)
        job = run(agents, prepared)

        assert job.state == "succeeded"
        kept = agents.reference(prepared)["kept"]
        assert kept["complete"] is True and kept["tutorials"] == []
        assert sorted(one["path"] for one in kept["not_run"]) == sorted([NOTEBOOK, SCRIPT])
        assert all("minutes for all of the runs were used" in one["reason"] for one in kept["not_run"])


class TestWhileTheyRun:
    def test_nothing_that_would_change_what_is_run_is_done_until_it_has_ended(
        self, agents: PaperAgents, prepared: str, containers: Containers
    ) -> None:
        containers.gates[NOTEBOOK] = containers.gates[SCRIPT] = threading.Event()
        job = agents.start_reference(prepared, repeats=1)
        first = next(item["path"] for item in agents.reference(prepared)["plan"]["runnable"])
        assert containers.began[first].wait(10)

        assert agents.reference(prepared)["job"]["id"] == job.id
        for call in (
            lambda: agents.start_reference(prepared),
            lambda: agents.clear_reference(prepared),
            lambda: agents.clear_environment(prepared),
            lambda: agents.clear_repository(prepared),
            lambda: agents.build_environment(prepared),
            lambda: agents.delete(prepared),
            lambda: agents.change(prepared, repo="https://github.com/example/other"),
        ):
            error = refused(call)
            assert error.status == 409 and error.code == "busy", call
        assert agents.view(prepared)["steps"]["tools"] == "running"

        containers.gates[NOTEBOOK].set()
        finish(job)
        assert job.state == "succeeded" and agents.view(prepared)["steps"]["tools"] == "pending"


class TestWhatItBelongsTo:
    def test_what_was_run_goes_with_the_environment_it_was_run_in(
        self, agents: PaperAgents, prepared: str, docker: Docker, containers: Containers, workspace: Workspace
    ) -> None:
        run(agents, prepared, repeats=1)
        directory = directory_of(workspace, prepared)
        assert kept_reference.stored(directory) is not None

        agents.clear_environment(prepared)

        assert kept_reference.stored(directory) is None and not kept_reference.runs_path(directory).exists()
        assert docker.runs_cleaned[-1] == prepared
        build(agents, prepared)
        assert agents.reference(prepared)["kept"] is None

    def test_what_was_run_goes_with_the_code_it_was_run_on(
        self, agents: PaperAgents, prepared: str, containers: Containers, workspace: Workspace
    ) -> None:
        run(agents, prepared, repeats=1)
        directory = directory_of(workspace, prepared)

        agents.clear_repository(prepared)

        assert kept_reference.stored(directory) is None
        assert agents.reference(prepared)["plan"] is None

    def test_deleting_the_agent_takes_all_of_it_away(
        self, agents: PaperAgents, prepared: str, docker: Docker, containers: Containers, workspace: Workspace
    ) -> None:
        run(agents, prepared, repeats=1)
        agents.delete(prepared)

        assert not directory_of(workspace, prepared).exists() and docker.images == {}
        assert docker.runs_cleaned[-1] == prepared

    def test_what_was_run_in_another_image_is_not_shown(
        self, agents: PaperAgents, prepared: str, containers: Containers, workspace: Workspace
    ) -> None:
        run(agents, prepared, repeats=1)
        directory = directory_of(workspace, prepared)
        record = kept_reference.stored(directory)
        assert record is not None
        kept_reference.save(directory, {**record, "image_id": "sha256:" + "9" * 64})

        assert agents.reference(prepared)["kept"] is None
        assert refused(agents.reference_tutorial, prepared, record["tutorials"][0]["id"]).status == 404

    def test_what_was_run_on_another_commit_is_not_shown(
        self, agents: PaperAgents, prepared: str, containers: Containers, workspace: Workspace
    ) -> None:
        run(agents, prepared, repeats=1)
        directory = directory_of(workspace, prepared)
        record = kept_reference.stored(directory)
        assert record is not None
        kept_reference.save(directory, {**record, "commit": "f" * 40})

        assert agents.reference(prepared)["kept"] is None


class TestWhatWasEdited:
    def test_an_account_that_is_not_one_is_not_shown_and_the_tutorials_can_be_run_again(
        self, agents: PaperAgents, prepared: str, containers: Containers, workspace: Workspace
    ) -> None:
        run(agents, prepared, repeats=1)
        directory = directory_of(workspace, prepared)
        path = kept_reference.checks_path(directory) / kept_reference.RECORD_FILE
        whole = json.loads(path.read_text())
        for text in ("not json", "[]", json.dumps({"schema": 1}), json.dumps({**whole, "tutorials": "a"})):
            path.write_text(text)
            assert agents.reference(prepared)["kept"] is None, text
        run(agents, prepared, repeats=1)
        assert agents.reference(prepared)["kept"]["complete"] is True

    def test_an_account_that_names_a_tutorial_by_what_is_not_an_id_is_not_shown(
        self, agents: PaperAgents, prepared: str, containers: Containers, workspace: Workspace
    ) -> None:
        run(agents, prepared, repeats=1)
        directory = directory_of(workspace, prepared)
        record = kept_reference.stored(directory)
        assert record is not None
        for name in ("..", "", "../x", "01-X"):
            tutorials = [{**record["tutorials"][0], "id": name}, *record["tutorials"][1:]]
            kept_reference.save(directory, {**record, "tutorials": tutorials})
            assert kept_reference.stored(directory) is None, name
            assert agents.reference(prepared)["kept"] is None

    def test_a_tutorial_whose_record_was_taken_away_is_not_listed(
        self, agents: PaperAgents, prepared: str, containers: Containers, workspace: Workspace
    ) -> None:
        run(agents, prepared, repeats=1)
        directory = directory_of(workspace, prepared)
        first = agents.reference(prepared)["kept"]["tutorials"][0]["id"]
        (kept_reference.run_path(directory, first) / kept_reference.DETAIL_FILE).unlink()

        assert [one["id"] for one in agents.reference(prepared)["kept"]["tutorials"]] != [first]
        assert len(agents.reference(prepared)["kept"]["tutorials"]) == 1

    def test_a_record_of_a_tutorial_that_was_edited_to_be_another_is_not_shown(
        self, agents: PaperAgents, prepared: str, containers: Containers, workspace: Workspace
    ) -> None:
        run(agents, prepared, repeats=1)
        directory = directory_of(workspace, prepared)
        first = agents.reference(prepared)["kept"]["tutorials"][0]["id"]
        path = kept_reference.run_path(directory, first) / kept_reference.DETAIL_FILE
        detail = json.loads(path.read_text())

        for changes in ({"path": "other.py"}, {"id": "02-other"}, {"calls": "none"}, {"schema": 2}):
            path.write_text(json.dumps({**detail, **changes}))
            assert refused(agents.reference_tutorial, prepared, first).status == 404, changes

    def test_a_folder_that_is_a_link_is_not_followed(
        self, agents: PaperAgents, prepared: str, containers: Containers, workspace: Workspace, tmp_path: Path
    ) -> None:
        run(agents, prepared, repeats=1)
        directory = directory_of(workspace, prepared)
        first = agents.reference(prepared)["kept"]["tutorials"][0]["id"]
        folder = kept_reference.run_path(directory, first)
        outside = tmp_path / "outside"
        folder.rename(outside)
        folder.symlink_to(outside)

        assert first not in [one["id"] for one in agents.reference(prepared)["kept"]["tutorials"]]
        assert refused(agents.reference_tutorial, prepared, first).status == 404


class TestOverHttp:
    def wait_for(self, client: TestClient, agent_id: str, step: str, status: str) -> None:
        deadline = time.monotonic() + 20
        while client.get(f"/api/paperagents/{agent_id}").json()["steps"][step] != status:
            assert time.monotonic() < deadline
            time.sleep(0.02)

    def test_running_asking_and_taking_away(
        self, client: TestClient, remote: Remote, docker: Docker, containers: Containers
    ) -> None:
        remote.files = {**remote.files, SCRIPT: "print(1)\n"}
        made = client.post(
            "/api/paperagents",
            json={"title": "CellMapper", "paper": {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}, "repo": URL},
        )
        agent_id = made.json()["id"]
        base = f"/api/paperagents/{agent_id}"
        assert client.post(f"{base}/reference", json={}).status_code == 422
        client.post(f"{base}/repository", json={})
        self.wait_for(client, agent_id, "repository", "done")
        client.post(f"{base}/environment", json={})
        self.wait_for(client, agent_id, "environment", "done")

        shown = client.get(f"{base}/reference").json()
        assert shown["kept"] is None and len(shown["plan"]["runnable"]) == 2
        started = client.post(f"{base}/reference", json={"minutes": 5, "repeats": 1, "data": False})
        assert started.status_code == 202 and started.json()["kind"] == REFERENCE_JOB
        deadline = time.monotonic() + 20
        while (shown := client.get(f"{base}/reference").json())["job"] is not None or shown["kept"] is None:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert containers.runs[0]["limits"].minutes == 5

        kept = client.get(f"{base}/reference").json()["kept"]
        assert kept["complete"] is True and len(kept["tutorials"]) == 2
        detail = client.get(f"{base}/reference/{kept['tutorials'][0]['id']}")
        assert detail.status_code == 200 and detail.json()["calls"][0]["qualname"] == "map_cells"
        assert client.get(f"{base}/reference/99-nothing").status_code == 404
        again = client.post(f"{base}/reference", json={})
        assert (again.status_code, again.json()["error"]["code"]) == (409, "done")

        removed = client.delete(f"{base}/reference")
        assert removed.status_code == 200 and removed.json()["kept"] is None
        assert client.get(f"{base}/reference/{kept['tutorials'][0]['id']}").status_code == 404

    def test_a_body_that_is_not_what_is_asked_for_is_refused(self, client: TestClient, docker: Docker) -> None:
        made = client.post(
            "/api/paperagents",
            json={"title": "CellMapper", "paper": {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}},
        )
        agent_id = made.json()["id"]

        for body in ({"minutes": "5"}, {"data": "yes"}, {"repeats": 1.5}, {"surprise": 1}):
            assert client.post(f"/api/paperagents/{agent_id}/reference", json=body).status_code == 422, body

    def test_it_is_not_there_without_the_token_or_for_an_agent_that_is_not(self, client: TestClient) -> None:
        assert client.get("/api/paperagents/nothing/reference").status_code == 404
        assert client.post("/api/paperagents/nothing/reference", json={}).status_code == 404
        assert client.get("/api/paperagents/nothing/reference/01-x").status_code == 404
        assert client.delete("/api/paperagents/nothing/reference").status_code == 404
        bare = TestClient(client.app, base_url=LOCAL)
        assert bare.get("/api/paperagents/nothing/reference").status_code == 401
