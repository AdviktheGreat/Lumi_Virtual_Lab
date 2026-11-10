"""Tests of making a PaperAgent's tools: what would be made and what would not and why, the job that makes them and what
it is given, what is kept and for which commit, image, and reference run, what the other operations do while it runs and
after, and that what was made goes with what it was made from. Docker and its containers are replaced by stand-ins, so
what the server does is what is looked at here; the real calls are in test_paperagents_toolmaking."""

import hashlib
import json
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import test_server_paperagent_reference as reference
from fastapi.testclient import TestClient
from test_paperagents_reference import call_of, failure_of, result_of
from test_server_paperagent_reference import NOTEBOOK, SCRIPT, run, why, writes
from test_server_paperagent_repository import (
    LOCAL,
    URL,
    Remote,
    agent_of,
    directory_of,
    fetch,
    finish,
    refused,
)

from virtual_lab.execution import DockerUnavailableError
from virtual_lab.paperagents import reference as referencing
from virtual_lab.paperagents import toolmaking as making
from virtual_lab.paperagents import wrappers
from virtual_lab.server import paperagent_reference as kept_reference
from virtual_lab.server import paperagent_tools as kept_tools
from virtual_lab.server.paperagents import TOOLS_JOB, PaperAgents, steps_of
from virtual_lab.server.workspace import Workspace

# What the tests of running the tutorials are made with, which are fixtures of that module
agents = reference.agents
client = reference.client
containers = reference.containers
docker = reference.docker
git_is_installed = reference.git_is_installed
jobs = reference.jobs
marker = reference.marker
remote = reference.remote
workspace = reference.workspace
Containers = reference.Containers
Docker = reference.Docker

MAPPING = '''
def map_cells(counts):
    """Maps the cells."""
    return counts


def tally(counts, scale=1):
    return sum(counts) * scale
'''
# What each function gives, which is what the stand-in for a container gives for it unless it is told otherwise
FUNCTIONS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "map_cells": lambda args: args["counts"],
    "tally": lambda args: sum(args["counts"]) * args["scale"],
}


def call(name: str, args: dict[str, Any], result: Any, number: int, **changes: Any) -> dict[str, Any]:
    return {
        **call_of(name, args, result, number),
        "module": "cellmapper.mapping",
        "file": "cellmapper/mapping.py",
        **changes,
    }


CALLS = [
    call("map_cells", {"counts": [1, 2]}, [1, 2], 1),
    call("tally", {"counts": [1, 2, 3], "scale": 2}, 12, 2),
]
WITH_A_METHOD = [
    *CALLS,
    call("add", {"amount": 1}, 3, 3, qualname="Counter.add", method=True),
]


def value_of(value: Any) -> dict[str, Any]:
    return {"type": type(value).__name__, "plain": True, "value": value}


class Replays:
    """Stands in for the containers that tools are called in: what it is given is kept, and what each call gives is what
    the function gives, unless a play says otherwise."""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.plays: dict[str, Callable[[dict[str, Any], int], dict[str, Any] | None]] = {}
        self.gates: dict[str, threading.Event] = {}
        self.began: defaultdict[str, threading.Event] = defaultdict(threading.Event)
        self.broken: BaseException | None = None

    def execute(
        self, runner: making.ToolRunner, folder: Path, item: Any, seconds: float
    ) -> tuple[str, int | None, str]:
        spec = json.loads((folder / making.CALL_FILE).read_text())
        function = spec["function"]
        self.runs.append(
            {
                "function": function,
                "cases": spec["cases"],
                "repeats": spec["repeats"],
                "seconds": seconds,
                "spec_seconds": spec["seconds"],
                "files": sorted(path.name for path in folder.iterdir()),
                "source": (folder / making.WRAPPER_AT).read_text(),
                "data": runner.data,
                "label": runner.label,
                "tag": runner.tag,
                "limits": runner.tools,
                "scratch": runner.scratch,
            }
        )
        self.began[function].set()
        gate = self.gates.get(function)
        if gate is not None:
            while not gate.wait(0.01):
                if runner.stop.is_set():
                    return "stopped", None, ""
        if self.broken is not None:
            raise self.broken
        where = folder / making.CALLS_FOLDER
        where.mkdir()
        for case in spec["cases"]:
            for repeat in range(spec["repeats"]):
                play = self.plays.get(function)
                result = play(case, repeat) if play is not None else self.gives(function, case)
                if result is not None:
                    (where / f"{case['id']}-{repeat}.json").write_text(json.dumps(result))

        return "done", 0, ""

    def gives(self, function: str, case: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": 1,
            "ok": True,
            "error": None,
            "result": value_of(FUNCTIONS[function](case["args"])),
            "seconds": 0.1,
            "output": "",
        }

    def functions(self) -> list[str]:
        return [run["function"] for run in self.runs]


def gives(value: Any) -> Callable[[dict[str, Any], int], dict[str, Any]]:
    """A play in which each call gives a value, whatever it was passed."""

    def play(case: dict[str, Any], repeat: int) -> dict[str, Any]:
        return {"schema": 1, "ok": True, "error": None, "result": value_of(value), "seconds": 0.1, "output": ""}

    return play


@pytest.fixture
def replays(monkeypatch: pytest.MonkeyPatch) -> Replays:
    stand_in = Replays()
    monkeypatch.setattr(making.ToolRunner, "execute", lambda *arguments: stand_in.execute(*arguments))

    return stand_in


@pytest.fixture
def prepared(agents: PaperAgents, remote: Remote, docker: Docker, containers: Containers, replays: Replays) -> str:
    """An agent whose code has been fetched and environment built, and whose tutorials call two functions."""
    remote.files = {**remote.files, SCRIPT: "print(1)\n", "cellmapper/mapping.py": MAPPING}
    agent_id = agent_of(agents)
    fetch(agents, agent_id)
    reference.build(agents, agent_id)
    containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=CALLS))

    return agent_id


def reference_run(agents: PaperAgents, agent_id: str, **options: Any) -> Any:
    return run(agents, agent_id, repeats=1, **options)


@pytest.fixture
def referenced(agents: PaperAgents, prepared: str) -> str:
    """An agent whose tutorials have been run."""
    reference_run(agents, prepared)

    return prepared


def make(agents: PaperAgents, agent_id: str, **options: Any) -> Any:
    return finish(agents.start_tools(agent_id, **options))


def tools_step(agents: PaperAgents, agent_id: str) -> str:
    return steps_of(agents.lookup(agent_id)[1])["tools"]


def kept_of(agents: PaperAgents, agent_id: str) -> dict[str, Any]:
    kept = agents.tools(agent_id)["kept"]
    assert kept is not None

    return kept


class TestWhatWouldBeMade:
    def test_nothing_is_made_until_the_tutorials_have_been_run(
        self, agents: PaperAgents, prepared: str, replays: Replays
    ) -> None:
        found = agents.tools(prepared)

        assert (found["reference"], found["preview"], found["kept"], found["job"]) == (None,) * 4
        assert found["docker"] == {"ready": True, "message": None}
        assert found["meaning"].endswith("does not show that what it gives is right.")
        limits = found["limits"]
        assert (limits["default_minutes"], limits["max_total_minutes"], limits["default_repeats"]) == (5, 120, 2)
        assert (limits["default_tools"], limits["max_repairs"], limits["memory"], limits["pids"]) == (20, 3, "8g", 1024)
        assert why(agents.start_tools, prepared) == (422, "no_reference")
        assert replays.runs == []
        json.dumps(found)

    def test_there_is_nothing_to_make_it_from_before_the_code_is_fetched(
        self, agents: PaperAgents, docker: Docker, replays: Replays
    ) -> None:
        agent_id = agent_of(agents)

        assert agents.tools(agent_id)["reference"] is None
        assert why(agents.start_tools, agent_id) == (422, "no_code")

    def test_after_the_tutorials_it_says_which_functions_would_be_made_and_which_would_not_and_why(
        self, agents: PaperAgents, prepared: str, containers: Containers, replays: Replays
    ) -> None:
        containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=WITH_A_METHOD))
        reference_run(agents, prepared)
        found = agents.tools(prepared)

        assert found["reference"]["complete"] is True and found["reference"]["tutorials"] == 2
        assert found["reference"]["data"] is False
        preview = found["preview"]
        assert [(one["name"], one["cases"], one["skipped"]) for one in preview["candidates"]] == [
            ("map_cells", 2, []),
            ("tally", 2, []),
        ]
        assert [(one["name"], one["kind"]) for one in preview["dropped"]] == [("add", "method")]
        assert "takes an object that the tutorial made first" in preview["dropped"][0]["reason"]
        assert preview["unused"] == [] and found["kept"] is None
        assert replays.runs == []
        json.dumps(found)

    def test_a_reference_run_that_did_not_come_to_its_end_is_not_made_from(
        self, agents: PaperAgents, prepared: str, containers: Containers
    ) -> None:
        containers.gates[SCRIPT] = containers.gates[NOTEBOOK] = threading.Event()
        job = agents.start_reference(prepared, repeats=1)
        first = next(item["path"] for item in agents.reference(prepared)["plan"]["runnable"])
        assert containers.began[first].wait(10)
        job.request_stop()
        finish(job)

        assert agents.reference(prepared)["kept"]["complete"] is False
        assert agents.tools(prepared)["reference"] is None
        assert why(agents.start_tools, prepared) == (422, "no_reference")

    def test_tutorials_that_did_not_run_to_their_end_are_not_held_to_and_if_none_is_left_it_is_said(
        self, agents: PaperAgents, prepared: str, containers: Containers, replays: Replays
    ) -> None:
        broken = writes(result_of(ok=False, error=failure_of("ValueError"), calls=CALLS))
        containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = broken
        reference_run(agents, prepared)
        preview = agents.tools(prepared)["preview"]

        assert preview["candidates"] == [] and len(preview["unused"]) == 2
        assert all("did not run to its end" in one["reason"] for one in preview["unused"])
        error = refused(agents.start_tools, prepared)
        assert (error.status, error.code) == (422, "no_tools")
        assert "None of the tutorials that ran to their end called a function of the code." in error.message
        assert replays.runs == []

    def test_the_reasons_a_function_is_left_out_are_in_what_is_said_when_none_can_be_made(
        self, agents: PaperAgents, prepared: str, containers: Containers
    ) -> None:
        only = [call("add", {"amount": 1}, 3, 1, qualname="Counter.add", method=True)]
        containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=only))
        reference_run(agents, prepared)

        error = refused(agents.start_tools, prepared)
        assert error.code == "no_tools" and "add: It is a method of a class" in error.message


class TestMaking:
    def test_the_tools_are_made_and_kept_for_the_commit_the_image_and_the_reference_run_they_were_made_from(
        self, agents: PaperAgents, referenced: str, docker: Docker, workspace: Workspace
    ) -> None:
        job = make(agents, referenced)

        assert job.state == "succeeded" and job.kind == TOOLS_JOB
        assert job.message == "Made 2 tools of tier A. 0 functions were not made into a tool."
        found = agents.tools(referenced)
        kept = found["kept"]
        reference_kept = agents.reference(referenced)["kept"]
        assert (kept["commit"], kept["image_id"], kept["complete"]) == (
            reference.COMMIT,
            docker.images[reference.tag_of(referenced)],
            True,
        )
        assert kept["reference"] == {
            "started_at": reference_kept["started_at"],
            "finished_at": reference_kept["finished_at"],
        }
        assert kept["finished_at"] is not None and kept["dropped"] == [] and kept["unused"] == []
        assert [(one["name"], one["tier"], one["module"], one["checked"], one["repeats"]) for one in kept["tools"]] == [
            ("map_cells", "A", "cellmapper.mapping", 2, 2),
            ("tally", "A", "cellmapper.mapping", 2, 2),
        ]
        assert [one["parameters"] for one in kept["tools"]] == [["counts"], ["counts", "scale"]]
        assert tools_step(agents, referenced) == "done" and agents.view(referenced)["steps"]["tools"] == "done"
        directory = directory_of(workspace, referenced)
        assert sorted(path.name for path in kept_tools.tools_path(directory).iterdir()) == ["map_cells", "tally"]
        json.dumps(found)

    def test_one_tool_is_kept_with_its_wrapper_and_each_call_that_was_made_again(
        self, agents: PaperAgents, referenced: str
    ) -> None:
        make(agents, referenced)
        tool = agents.tool(referenced, "tally")

        assert tool["tier"] == "A" and tool["repo"]["function"] == "tally" and tool["wrapper"] == "wrapper.py"
        assert tool["wrapper_sha256"] == hashlib.sha256(tool["source"].encode()).hexdigest()
        wrapped = wrappers.check_wrapper(tool["source"], "cellmapper.mapping", "tally")
        assert wrapped.name == "tally" and [item["name"] for item in tool["signature"]] == ["counts", "scale"]
        evidence = tool["evidence"]
        assert evidence["kind"] == "reference_run" and evidence["checked"] == 2 and evidence["repeats"] == 2
        assert [(item["verdict"], item["matched"]) for item in evidence["cases"]] == [("match", 2), ("match", 2)]
        assert evidence["cases"][0]["args"] == {"counts": [1, 2, 3], "scale": 2}
        assert evidence["cases"][0]["expected"]["value"] == 12 and evidence["cases"][0]["cwd"] == "examples"
        assert len({item["tutorial"] for item in evidence["cases"]}) == 2
        assert refused(agents.tool, referenced, "nothing").status == 404
        assert refused(agents.tool, referenced, "../x").status == 404
        assert refused(agents.tool, "nothing", "tally").status == 404
        json.dumps(tool)

    def test_each_tool_is_called_in_the_environment_of_the_agent_with_what_the_tutorial_passed_and_not_what_it_got(
        self, agents: PaperAgents, referenced: str, replays: Replays, workspace: Workspace
    ) -> None:
        make(agents, referenced)

        assert replays.functions() == ["map_cells", "tally"]
        first = replays.runs[0]
        assert first["tag"] == reference.tag_of(referenced) and first["label"] == referenced
        assert first["limits"] == making.ToolLimits() and first["repeats"] == 2 and first["data"] is None
        assert first["cases"] == [
            {"id": 0, "args": {"counts": [1, 2]}, "cwd": "examples"},
            {"id": 1, "args": {"counts": [1, 2]}, "cwd": "examples"},
        ]
        assert first["files"] == sorted([making.CALL_FILE, making.WRAPPER_AT, making.RECORD_AT, referencing.RUNNER_AT])
        assert "import cellmapper.mapping as _repo" in first["source"] and "return _repo.map_cells" in first["source"]
        assert first["scratch"].parent == workspace.root and not first["scratch"].exists()

    def test_a_tool_that_does_not_give_the_same_is_dropped_with_why_and_the_others_are_kept(
        self, agents: PaperAgents, referenced: str, replays: Replays, workspace: Workspace
    ) -> None:
        replays.plays["tally"] = gives(7)
        job = make(agents, referenced)

        assert job.state == "succeeded"
        assert job.message == "Made 1 tool of tier A. 1 function was not made into a tool."
        kept = kept_of(agents, referenced)
        assert [one["name"] for one in kept["tools"]] == ["map_cells"] and kept["complete"] is True
        (dropped,) = kept["dropped"]
        assert (dropped["name"], dropped["kind"], dropped["calls"]) == ("tally", "replay_differs", 2)
        assert "gave something else" in dropped["reason"] and dropped["details"]
        assert tools_step(agents, referenced) == "done"
        directory = directory_of(workspace, referenced)
        assert not kept_tools.tool_path(directory, "tally").exists()
        assert refused(agents.tool, referenced, "tally").status == 404

    def test_a_call_that_raised_when_made_again_is_why_a_tool_is_dropped(
        self, agents: PaperAgents, referenced: str, replays: Replays
    ) -> None:
        def raises(case: dict[str, Any], repeat: int) -> dict[str, Any]:
            error = {"type": "FileNotFoundError", "message": "x.h5ad", "traceback": ["FileNotFoundError: x.h5ad"]}

            return {
                "schema": 1,
                "ok": False,
                "error": {**error, "cell": None},
                "result": None,
                "seconds": 0.1,
                "output": "",
            }

        replays.plays["map_cells"] = raises
        make(agents, referenced)

        (dropped,) = [one for one in kept_of(agents, referenced)["dropped"] if one["name"] == "map_cells"]
        assert dropped["kind"] == "replay_error" and dropped["reason"].startswith("It stopped with an error")
        assert "stopped with FileNotFoundError when it was made again: x.h5ad." in dropped["details"][0]
        assert "may read a file that the tutorial wrote" in dropped["details"][0]

    def test_when_no_tool_holds_the_job_says_so_and_the_step_is_failed_and_why_is_kept(
        self, agents: PaperAgents, referenced: str, replays: Replays
    ) -> None:
        replays.plays["map_cells"] = gives("something else")
        replays.plays["tally"] = gives("something else")
        job = make(agents, referenced)

        assert job.state == "succeeded"
        assert job.message == "Made 0 tools of tier A. 2 functions were not made into a tool."
        kept = kept_of(agents, referenced)
        assert kept["complete"] is True and kept["tools"] == [] and len(kept["dropped"]) == 2
        assert tools_step(agents, referenced) == "failed"
        agents.clear_tools(referenced)
        assert tools_step(agents, referenced) == "pending"

    def test_the_time_for_all_of_the_tools_used_leaves_the_rest_not_tried_and_says_so(
        self, agents: PaperAgents, referenced: str, replays: Replays, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(making, "LEAST_SECONDS", 10_000)
        job = make(agents, referenced)

        assert job.state == "succeeded" and "2 were not tried" in (job.message or "")
        kept = kept_of(agents, referenced)
        assert kept["complete"] is True and kept["tools"] == []
        assert [(one["name"], one["kind"]) for one in kept["dropped"]] == [
            ("map_cells", "out_of_time"),
            ("tally", "out_of_time"),
        ]
        assert replays.runs == []

    def test_the_limits_that_were_given_are_the_ones_the_calls_keep_to(
        self, agents: PaperAgents, referenced: str, replays: Replays
    ) -> None:
        make(agents, referenced, minutes=3, total_minutes=7, tools=1, repeats=3, repairs=0, gigabytes=4)

        assert replays.functions() == ["map_cells"]
        used = replays.runs[0]
        assert used["limits"] == making.ToolLimits(3, 7, 1, 3, 0, 4) and used["repeats"] == 3
        assert used["seconds"] <= 180 and used["spec_seconds"] == int(used["seconds"] * 0.9)
        kept = kept_of(agents, referenced)
        assert kept["limits"]["tools"] == 1 and kept["limits"]["repeats"] == 3 and kept["limits"]["gigabytes"] == 4
        assert [(one["name"], one["kind"]) for one in kept["dropped"]] == [("tally", "over_limit")]
        assert kept["tools"][0]["repeats"] == 3

    @pytest.mark.parametrize(
        "options",
        [
            {"minutes": 0},
            {"minutes": 31},
            {"total_minutes": 121},
            {"tools": 51},
            {"repeats": 4},
            {"repairs": 4},
            {"repairs": -1},
            {"gigabytes": 21},
            {"minutes": "5"},
            {"minutes": True},
        ],
    )
    def test_limits_that_are_not_allowed_are_refused_before_anything_is_called(
        self, agents: PaperAgents, referenced: str, replays: Replays, options: dict[str, Any]
    ) -> None:
        assert why(agents.start_tools, referenced, **options) == (422, "invalid")
        assert replays.runs == [] and agents.tools(referenced)["kept"] is None

    def test_the_data_that_the_tutorials_were_given_is_given_to_the_calls_and_nothing_else_is(
        self, agents: PaperAgents, prepared: str, replays: Replays, workspace: Workspace
    ) -> None:
        reference.keep_data(workspace, prepared)
        reference_run(agents, prepared)
        assert agents.tools(prepared)["reference"]["data"] is True
        make(agents, prepared)

        data = directory_of(workspace, prepared) / "data"
        assert {one["data"] for one in replays.runs} == {data}
        assert kept_of(agents, prepared)["data"] is True

        agents.clear_reference(prepared)
        replays.runs.clear()
        reference_run(agents, prepared, use_data=False)
        make(agents, prepared)
        assert {one["data"] for one in replays.runs} == {None} and kept_of(agents, prepared)["data"] is False

    def test_the_code_is_read_and_never_run_on_this_machine(
        self, agents: PaperAgents, referenced: str, marker: Path
    ) -> None:
        make(agents, referenced)

        assert not marker.exists()

    def test_docker_that_is_not_running_is_said_and_nothing_is_called(
        self, agents: PaperAgents, referenced: str, docker: Docker, replays: Replays
    ) -> None:
        docker.usable = (False, "Docker is not running.")

        error = refused(agents.start_tools, referenced)
        assert (error.status, error.code) == (422, "docker_missing") and "not running" in error.message
        assert agents.tools(referenced)["docker"] == {"ready": False, "message": "Docker is not running."}
        assert replays.runs == []

    def test_an_image_that_is_gone_from_docker_is_said_and_nothing_is_called(
        self, agents: PaperAgents, referenced: str, docker: Docker, replays: Replays
    ) -> None:
        docker.images.clear()

        assert why(agents.start_tools, referenced) == (409, "image_missing")
        assert replays.runs == []

    def test_leftover_containers_of_the_agent_are_taken_away_before_the_making(
        self, agents: PaperAgents, referenced: str, docker: Docker
    ) -> None:
        docker.runs_cleaned.clear()
        make(agents, referenced)

        assert docker.runs_cleaned == [referenced]

    def test_what_is_made_is_not_made_again_until_it_is_taken_away_and_what_the_tutorials_gave_is_kept(
        self, agents: PaperAgents, referenced: str, replays: Replays, workspace: Workspace
    ) -> None:
        make(agents, referenced)

        assert why(agents.start_tools, referenced) == (409, "done")
        agents.clear_tools(referenced)
        directory = directory_of(workspace, referenced)
        assert agents.tools(referenced)["kept"] is None and tools_step(agents, referenced) == "pending"
        assert not kept_tools.tools_path(directory).exists() and kept_reference.stored(directory) is not None
        assert refused(agents.tool, referenced, "tally").status == 404
        replays.runs.clear()
        make(agents, referenced)
        assert kept_of(agents, referenced)["complete"] is True and len(replays.runs) == 2


class TestWhenItGoesWrong:
    def test_a_making_that_is_stopped_keeps_the_tools_it_had_made_and_can_be_started_again(
        self, agents: PaperAgents, referenced: str, replays: Replays
    ) -> None:
        replays.gates["tally"] = threading.Event()
        job = agents.start_tools(referenced)
        assert replays.began["tally"].wait(10)
        assert agents.view(referenced)["steps"]["tools"] == "running"
        job.request_stop()
        finish(job)

        assert job.state == "stopped"
        kept = kept_of(agents, referenced)
        assert kept["complete"] is False and kept["finished_at"] is None
        assert [one["name"] for one in kept["tools"]] == ["map_cells"]
        assert agents.tool(referenced, "map_cells")["tier"] == "A"
        assert tools_step(agents, referenced) == "pending"

        del replays.gates["tally"]
        make(agents, referenced)
        kept = kept_of(agents, referenced)
        assert kept["complete"] is True and [one["name"] for one in kept["tools"]] == ["map_cells", "tally"]
        assert tools_step(agents, referenced) == "done"

    def test_docker_that_stops_answering_fails_the_job_and_does_not_blame_the_tool(
        self, agents: PaperAgents, referenced: str, replays: Replays
    ) -> None:
        replays.broken = DockerUnavailableError("Docker did not run the tool: Cannot connect to the Docker daemon")
        job = make(agents, referenced)

        assert job.state == "failed" and job.error is not None and "Cannot connect" in job.error
        kept = kept_of(agents, referenced)
        assert kept["complete"] is False and kept["tools"] == [] and kept["dropped"] == []
        assert tools_step(agents, referenced) == "failed"
        agents.clear_tools(referenced)
        assert tools_step(agents, referenced) == "pending" and agents.tools(referenced)["kept"] is None


class TestWhileTheyAreMade:
    def test_nothing_that_would_change_what_is_made_is_done_until_it_has_ended(
        self, agents: PaperAgents, referenced: str, replays: Replays
    ) -> None:
        replays.gates["map_cells"] = threading.Event()
        job = agents.start_tools(referenced)
        assert replays.began["map_cells"].wait(10)

        assert agents.tools(referenced)["job"]["id"] == job.id
        for action in (
            lambda: agents.start_tools(referenced),
            lambda: agents.start_reference(referenced),
            lambda: agents.clear_tools(referenced),
            lambda: agents.clear_reference(referenced),
            lambda: agents.clear_environment(referenced),
            lambda: agents.clear_repository(referenced),
            lambda: agents.build_environment(referenced),
            lambda: agents.delete(referenced),
            lambda: agents.change(referenced, repo="https://github.com/example/other"),
        ):
            error = refused(action)
            assert error.status == 409 and error.code == "busy", action
        assert agents.view(referenced)["steps"]["tools"] == "running"

        replays.gates["map_cells"].set()
        finish(job)
        assert job.state == "succeeded" and agents.view(referenced)["steps"]["tools"] == "done"


class TestWhatTheyBelongTo:
    def test_tools_go_with_the_tutorials_they_were_made_from(
        self, agents: PaperAgents, referenced: str, workspace: Workspace
    ) -> None:
        make(agents, referenced)
        directory = directory_of(workspace, referenced)
        assert kept_tools.stored(directory) is not None

        agents.clear_reference(referenced)

        assert kept_tools.stored(directory) is None and not kept_tools.tools_path(directory).exists()
        assert tools_step(agents, referenced) == "pending"
        assert agents.tools(referenced)["reference"] is None

    def test_tools_go_with_the_environment_they_were_called_in(
        self, agents: PaperAgents, referenced: str, docker: Docker, workspace: Workspace
    ) -> None:
        make(agents, referenced)
        directory = directory_of(workspace, referenced)

        agents.clear_environment(referenced)

        assert kept_tools.stored(directory) is None and not kept_tools.tools_path(directory).exists()
        reference.build(agents, referenced)
        assert agents.tools(referenced)["kept"] is None

    def test_tools_go_with_the_code_they_were_made_of(
        self, agents: PaperAgents, referenced: str, workspace: Workspace
    ) -> None:
        make(agents, referenced)
        directory = directory_of(workspace, referenced)

        agents.clear_repository(referenced)

        assert kept_tools.stored(directory) is None and not kept_tools.tools_path(directory).exists()
        assert agents.tools(referenced)["reference"] is None

    def test_deleting_the_agent_takes_all_of_it_away(
        self, agents: PaperAgents, referenced: str, docker: Docker, workspace: Workspace
    ) -> None:
        make(agents, referenced)
        agents.delete(referenced)

        assert not directory_of(workspace, referenced).exists() and docker.images == {}

    def test_running_the_tutorials_again_takes_away_the_tools_made_from_what_they_gave_before(
        self, agents: PaperAgents, referenced: str, workspace: Workspace
    ) -> None:
        make(agents, referenced)
        directory = directory_of(workspace, referenced)
        record = kept_reference.stored(directory)
        assert record is not None
        # A run that was started again, which is what is left of one that came to its end and was not taken away
        kept_reference.save(directory, {**record, "complete": False})
        assert agents.tools(referenced)["kept"] is None
        reference_run(agents, referenced)

        assert kept_tools.stored(directory) is None and tools_step(agents, referenced) == "pending"

    @pytest.mark.parametrize(
        "changes",
        [
            {"image_id": "sha256:" + "9" * 64},
            {"commit": "f" * 40},
            {"reference": {"started_at": "2000-01-01T00:00:00Z", "finished_at": "2000-01-01T00:01:00Z"}},
        ],
    )
    def test_tools_made_of_another_image_commit_or_run_are_not_shown(
        self, agents: PaperAgents, referenced: str, workspace: Workspace, changes: dict[str, Any]
    ) -> None:
        make(agents, referenced)
        directory = directory_of(workspace, referenced)
        record = kept_tools.stored(directory)
        assert record is not None
        kept_tools.save(directory, {**record, **changes})

        assert agents.tools(referenced)["kept"] is None
        assert refused(agents.tool, referenced, "tally").status == 404
        make(agents, referenced)
        assert kept_of(agents, referenced)["complete"] is True


class TestWhatWasEdited:
    def test_an_account_that_is_not_one_is_not_shown_and_the_tools_can_be_made_again(
        self, agents: PaperAgents, referenced: str, workspace: Workspace
    ) -> None:
        make(agents, referenced)
        directory = directory_of(workspace, referenced)
        path = kept_tools.checks_path(directory) / kept_tools.RECORD_FILE
        whole = json.loads(path.read_text())
        for text in ("not json", "[]", json.dumps({"schema": 1}), json.dumps({**whole, "tools": "a"})):
            path.write_text(text)
            assert agents.tools(referenced)["kept"] is None, text
        make(agents, referenced)
        assert kept_of(agents, referenced)["complete"] is True

    def test_an_account_that_names_a_tool_by_what_is_not_a_name_is_not_shown(
        self, agents: PaperAgents, referenced: str, workspace: Workspace
    ) -> None:
        make(agents, referenced)
        directory = directory_of(workspace, referenced)
        record = kept_tools.stored(directory)
        assert record is not None
        for name in ("..", "", "../x", "a b", "tally/../map_cells"):
            tools = [{**record["tools"][0], "name": name}, *record["tools"][1:]]
            kept_tools.save(directory, {**record, "tools": tools})
            assert kept_tools.stored(directory) is None, name
            assert agents.tools(referenced)["kept"] is None

    def test_a_tool_whose_files_were_taken_away_is_not_listed(
        self, agents: PaperAgents, referenced: str, workspace: Workspace
    ) -> None:
        make(agents, referenced)
        directory = directory_of(workspace, referenced)
        (kept_tools.tool_path(directory, "tally") / wrappers.WRAPPER_FILE).unlink()

        assert [one["name"] for one in kept_of(agents, referenced)["tools"]] == ["map_cells"]
        assert refused(agents.tool, referenced, "tally").status == 404

    @pytest.mark.parametrize(
        "source",
        [
            "import os\n\n\ndef tally(counts, scale=1):\n    return os.system('echo hi')\n",
            "def tally(counts: list, scale: int = 1):\n    return sum(counts) * scale\n",
            "import cellmapper.mapping as _repo\n\n\ndef tally(counts: list, scale: int = 1):\n"
            "    _repo.tally(counts=counts, scale=scale)\n    return 1\n",
            "this is not python",
        ],
    )
    def test_a_wrapper_that_was_edited_to_be_more_than_a_call_of_the_function_is_not_a_tool(
        self, agents: PaperAgents, referenced: str, workspace: Workspace, source: str
    ) -> None:
        make(agents, referenced)
        directory = directory_of(workspace, referenced)
        (kept_tools.tool_path(directory, "tally") / wrappers.WRAPPER_FILE).write_text(source)

        assert refused(agents.tool, referenced, "tally").status == 404
        assert agents.tool(referenced, "map_cells")["name"] == "map_cells"

    def test_a_wrapper_that_was_edited_in_a_way_that_still_calls_the_function_is_not_the_one_that_was_checked(
        self, agents: PaperAgents, referenced: str, workspace: Workspace
    ) -> None:
        make(agents, referenced)
        directory = directory_of(workspace, referenced)
        path = kept_tools.tool_path(directory, "tally") / wrappers.WRAPPER_FILE
        tool = agents.tool(referenced, "tally")
        path.write_text(tool["source"].replace("scale=scale", "scale=3"))
        # What was edited still passes the check of what a wrapper is, and so it is the hash that says
        assert refused(agents.tool, referenced, "tally").status == 404

    def test_a_record_of_a_tool_that_was_edited_to_be_another_is_not_shown(
        self, agents: PaperAgents, referenced: str, workspace: Workspace
    ) -> None:
        make(agents, referenced)
        directory = directory_of(workspace, referenced)
        path = kept_tools.tool_path(directory, "tally") / kept_tools.TOOL_FILE
        tool = json.loads(path.read_text())

        for changes in (
            {"name": "map_cells"},
            {"tier": "B"},
            {"schema": 2},
            {"evidence": "none"},
            {"wrapper": "../wrapper.py"},
            {"repo": {**tool["repo"], "function": "map_cells"}},
        ):
            path.write_text(json.dumps({**tool, **changes}))
            assert refused(agents.tool, referenced, "tally").status == 404, changes
        path.write_text("not json")
        assert refused(agents.tool, referenced, "tally").status == 404

    def test_a_folder_of_a_tool_that_is_a_link_is_not_followed(
        self, agents: PaperAgents, referenced: str, workspace: Workspace, tmp_path: Path
    ) -> None:
        make(agents, referenced)
        directory = directory_of(workspace, referenced)
        folder = kept_tools.tool_path(directory, "tally")
        outside = tmp_path / "outside"
        folder.rename(outside)
        folder.symlink_to(outside)

        assert [one["name"] for one in kept_of(agents, referenced)["tools"]] == ["map_cells"]
        assert refused(agents.tool, referenced, "tally").status == 404

    def test_a_wrapper_that_is_a_link_or_too_big_is_not_read(
        self, agents: PaperAgents, referenced: str, workspace: Workspace, tmp_path: Path
    ) -> None:
        make(agents, referenced)
        directory = directory_of(workspace, referenced)
        path = kept_tools.tool_path(directory, "tally") / wrappers.WRAPPER_FILE
        source = path.read_text()
        outside = tmp_path / "wrapper.py"
        outside.write_text(source)
        path.unlink()
        path.symlink_to(outside)
        assert refused(agents.tool, referenced, "tally").status == 404
        path.unlink()
        path.write_text(source + "#" * kept_tools.MAX_WRAPPER_BYTES)
        assert refused(agents.tool, referenced, "tally").status == 404


class TestTheStore:
    def test_what_may_be_a_name_a_tool_is_kept_under(self) -> None:
        for name in ("tally", "_x", "A1", "a" * 20):
            assert kept_tools.is_name(name)
        for name in ("", "..", "a/b", "1a", "a b", "a.b", "a" * 500, None, 3, "tally\n"):
            assert not kept_tools.is_name(name)

    def test_a_place_is_not_made_for_what_is_not_a_name(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="name of a tool"):
            kept_tools.tool_path(tmp_path, "../x")

    def test_the_account_goes_before_the_tools_so_that_it_never_names_what_is_gone(self, tmp_path: Path) -> None:
        (tmp_path / "checks").mkdir()
        (tmp_path / "checks" / kept_tools.RECORD_FILE).write_text("{}")
        (tmp_path / "tools" / "tally").mkdir(parents=True)
        (tmp_path / "tools" / "tally" / "wrapper.py").write_text("x")

        kept_tools.forget(tmp_path)

        assert not (tmp_path / "checks" / kept_tools.RECORD_FILE).exists() and not (tmp_path / "tools").exists()
        kept_tools.forget(tmp_path)


class TestOverHttp:
    def wait_for(self, client: TestClient, agent_id: str, step: str, status: str) -> None:
        deadline = time.monotonic() + 20
        while client.get(f"/api/paperagents/{agent_id}").json()["steps"][step] != status:
            assert time.monotonic() < deadline
            time.sleep(0.02)

    def test_making_asking_and_taking_away(
        self, client: TestClient, remote: Remote, docker: Docker, containers: Containers, replays: Replays
    ) -> None:
        remote.files = {**remote.files, SCRIPT: "print(1)\n", "cellmapper/mapping.py": MAPPING}
        containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=CALLS))
        made = client.post(
            "/api/paperagents",
            json={"title": "CellMapper", "paper": {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}, "repo": URL},
        )
        agent_id = made.json()["id"]
        base = f"/api/paperagents/{agent_id}"
        assert client.post(f"{base}/tools", json={}).status_code == 422
        client.post(f"{base}/repository", json={})
        self.wait_for(client, agent_id, "repository", "done")
        client.post(f"{base}/environment", json={})
        self.wait_for(client, agent_id, "environment", "done")
        assert client.post(f"{base}/tools", json={}).json()["error"]["code"] == "no_reference"

        client.post(f"{base}/reference", json={"repeats": 1, "data": False})
        deadline = time.monotonic() + 20
        while (shown := client.get(f"{base}/tools").json())["reference"] is None:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert shown["kept"] is None and len(shown["preview"]["candidates"]) == 2

        started = client.post(f"{base}/tools", json={"minutes": 2, "repeats": 1, "repairs": 0})
        assert started.status_code == 202 and started.json()["kind"] == TOOLS_JOB
        self.wait_for(client, agent_id, "tools", "done")
        assert replays.runs[0]["limits"] == making.ToolLimits(2, 20, 20, 1, 0, 2)

        kept = client.get(f"{base}/tools").json()["kept"]
        assert kept["complete"] is True and [one["name"] for one in kept["tools"]] == ["map_cells", "tally"]
        tool = client.get(f"{base}/tools/tally")
        assert tool.status_code == 200 and tool.json()["tier"] == "A" and "_repo.tally" in tool.json()["source"]
        assert client.get(f"{base}/tools/nothing").status_code == 404
        again = client.post(f"{base}/tools", json={})
        assert (again.status_code, again.json()["error"]["code"]) == (409, "done")

        removed = client.delete(f"{base}/tools")
        assert removed.status_code == 200 and removed.json()["kept"] is None
        assert client.get(f"{base}/tools/tally").status_code == 404
        assert client.get(f"{base}/reference").json()["kept"]["complete"] is True

    def test_a_body_that_is_not_what_is_asked_for_is_refused(self, client: TestClient, docker: Docker) -> None:
        made = client.post(
            "/api/paperagents",
            json={"title": "CellMapper", "paper": {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}},
        )
        agent_id = made.json()["id"]

        for body in ({"minutes": "5"}, {"repeats": 1.5}, {"repairs": True}, {"data": True}, {"surprise": 1}):
            assert client.post(f"/api/paperagents/{agent_id}/tools", json=body).status_code == 422, body

    def test_it_is_not_there_without_the_token_or_for_an_agent_that_is_not(self, client: TestClient) -> None:
        assert client.get("/api/paperagents/nothing/tools").status_code == 404
        assert client.post("/api/paperagents/nothing/tools", json={}).status_code == 404
        assert client.get("/api/paperagents/nothing/tools/tally").status_code == 404
        assert client.delete("/api/paperagents/nothing/tools").status_code == 404
        bare = TestClient(client.app, base_url=LOCAL)
        assert bare.get("/api/paperagents/nothing/tools").status_code == 401
