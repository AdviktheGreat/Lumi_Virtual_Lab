"""Tests of checking a PaperAgent's tools by what their tutorials did not give them: what would be checked, the job that
checks and what it is given, what is kept for which wrapper, commit, image, and reference run and what is shown when it
is not what is kept now, that a tool is of tier B only when two kinds passed and none failed and only by what is kept,
what the other operations do while the checks are made and after, and the tier that a conversation is given. Docker and
its containers are replaced by stand-ins, so what the server does is what is looked at here; the real checks are in
test_paperagents_checking."""

import hashlib
import json
import re
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
import test_server_paperagent_reference as reference
import test_server_paperagent_tools as tooling
from fastapi.testclient import TestClient
from test_paperagents_reference import result_of
from test_server_paperagent_reference import NOTEBOOK, SCRIPT, run, why, writes
from test_server_paperagent_repository import LOCAL, URL, Remote, agent_of, directory_of, fetch, finish, refused
from test_server_paperagent_tools import CALLS, FUNCTIONS, MAPPING, Replays, make

from virtual_lab.execution import DockerUnavailableError
from virtual_lab.paperagents import checking, wrappers
from virtual_lab.paperagents import reference as referencing
from virtual_lab.paperagents import toolmaking as making
from virtual_lab.server import paperagent_checks as kept_checks
from virtual_lab.server import paperagent_checkwork as checkwork
from virtual_lab.server import paperagent_given as given
from virtual_lab.server import paperagent_tools as kept_tools
from virtual_lab.server.paperagents import CHECKS_JOB, PaperAgents
from virtual_lab.server.workspace import Workspace
from virtual_lab.session import Session

# What the tests of making tools are made with, which are fixtures of that module
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

SESSION = cast(Session, MagicMock(spec=Session))
TESTS = """
from cellmapper.mapping import map_cells, tally


def test_map_cells():
    assert map_cells([1]) == [1]


def test_tally():
    assert tally([1, 2]) == 3
"""
DIRECT = re.compile(r"import_module\('([\w.]+)'\), '(\w+)'")
ALL = ("heldout", "repo_tests")


def passed_tests(ids: list[str]) -> dict[str, Any]:
    return {
        "schema": 1,
        "ran": True,
        "reason": None,
        "tests": len(ids),
        "passed": len(ids),
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "failures": [],
        "seconds": 0.2,
        "output": "." * len(ids),
    }


class Checks(Replays):
    """Stands in for the containers that the checks are made in: a tool's wrapper and the caller of the code's own
    function give what the function gives, and the tests pass, unless a play says otherwise."""

    def __init__(self) -> None:
        super().__init__()
        self.tests: list[dict[str, Any]] = []
        self.tests_play: Callable[[list[str]], dict[str, Any] | None] = passed_tests
        self.target = ""

    def execute(
        self, runner: making.ToolRunner, folder: Path, item: Any, seconds: float
    ) -> tuple[str, int | None, str]:
        if not (folder / checking.TESTS_FILE).exists():
            source = (folder / making.WRAPPER_AT).read_text()
            found = DIRECT.search(source)
            self.target = found.group(2) if found else ""

            return super().execute(runner, folder, item, seconds)
        spec = json.loads((folder / checking.TESTS_FILE).read_text())
        self.tests.append(
            {
                "ids": spec["tests"],
                "seconds": seconds,
                "spec_seconds": spec["seconds"],
                "files": sorted(path.name for path in folder.iterdir()),
                "data": runner.data,
                "label": runner.label,
                "tag": runner.tag,
                "limits": runner.tools,
                "scratch": runner.scratch,
            }
        )
        self.began["tests"].set()
        gate = self.gates.get("tests")
        if gate is not None:
            while not gate.wait(0.01):
                if runner.stop.is_set():
                    return "stopped", None, ""
        if self.broken is not None:
            raise self.broken
        result = self.tests_play(spec["tests"])
        if result is not None:
            where = folder / checking.RESULT_AT
            where.parent.mkdir(exist_ok=True)
            where.write_text(json.dumps(result))

        return "done", 0, ""

    def gives(self, function: str, case: dict[str, Any]) -> dict[str, Any]:
        return super().gives(self.target if function == checking.DIRECT_NAME else function, case)

    def checked(self, since: int = 0) -> list[str]:
        """The functions that were called through the tools since some run, which is what a check of inputs begins
        with."""
        return [run["function"] for run in self.runs[since:] if run["function"] != checking.DIRECT_NAME]


@pytest.fixture
def replays(monkeypatch: pytest.MonkeyPatch) -> Checks:
    stand_in = Checks()
    monkeypatch.setattr(making.ToolRunner, "execute", lambda *arguments: stand_in.execute(*arguments))

    return stand_in


@pytest.fixture
def prepared(agents: PaperAgents, remote: Remote, docker: Docker, containers: Containers, replays: Checks) -> str:
    """An agent whose code, which has tests, has been fetched and environment built, and whose tutorials call two
    functions."""
    remote.files = {
        **remote.files,
        SCRIPT: "print(1)\n",
        "cellmapper/mapping.py": MAPPING,
        "tests/test_mapping.py": TESTS,
    }
    agent_id = agent_of(agents)
    fetch(agents, agent_id)
    reference.build(agents, agent_id)
    containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=CALLS))

    return agent_id


@pytest.fixture
def made(agents: PaperAgents, prepared: str) -> str:
    """An agent whose tutorials have been run and whose two tools have been made, which are of tier A."""
    run(agents, prepared, repeats=1)
    make(agents, prepared)

    return prepared


def check(agents: PaperAgents, agent_id: str, **options: Any) -> Any:
    return finish(agents.start_checks(agent_id, **options))


def tools_of(agents: PaperAgents, agent_id: str) -> dict[str, dict[str, Any]]:
    return {tool["name"]: tool for tool in agents.checks(agent_id)["tools"]}


def statuses(agents: PaperAgents, agent_id: str, name: str) -> dict[str, str]:
    return {entry["kind"]: entry["status"] for entry in tools_of(agents, agent_id)[name]["evidence"]}


def record_of(workspace: Workspace, agent_id: str, name: str, kind: str) -> dict[str, Any]:
    return cast(
        dict[str, Any], json.loads(kept_checks.record_path(directory_of(workspace, agent_id), name, kind).read_text())
    )


def rewrite(workspace: Workspace, agent_id: str, name: str, which: str, changes: dict[str, Any]) -> None:
    """Edits a check that was kept, as a person or a process that has the files might."""
    path = kept_checks.record_path(directory_of(workspace, agent_id), name, which)
    path.write_text(json.dumps({**json.loads(path.read_text()), **changes}))


class TestWhatCanBeChecked:
    def test_nothing_is_checked_before_there_are_tools(
        self, agents: PaperAgents, prepared: str, replays: Checks
    ) -> None:
        found = agents.checks(prepared)

        assert (found["made"], found["tools"], found["job"]) == (False, [], None)
        assert found["docker"] == {"ready": True, "message": None}
        assert [kind["kind"] for kind in found["kinds"]] == list(ALL)
        assert all(kind["title"] and "not show" in kind["what"] for kind in found["kinds"])
        assert found["kinds_for_b"] == 2 and "does not show that what the tool gives is right" in found["meaning"]
        limits = found["limits"]
        assert (limits["default_minutes"], limits["max_total_minutes"], limits["default_repeats"]) == (5, 180, 2)
        assert (limits["max_gigabytes"], limits["memory"], limits["pids"]) == (20, "8g", 1024)
        assert why(agents.start_checks, prepared) == (422, "no_tools")
        assert replays.runs == [] and replays.tests == []
        json.dumps(found)

    def test_there_is_nothing_to_check_before_the_code_is_fetched(
        self, agents: PaperAgents, docker: Docker, replays: Checks
    ) -> None:
        agent_id = agent_of(agents)

        assert agents.checks(agent_id)["made"] is False
        assert why(agents.start_checks, agent_id) == (422, "no_code")

    def test_tools_that_were_made_are_listed_as_of_tier_a_with_no_check_made(
        self, agents: PaperAgents, made: str
    ) -> None:
        found = tools_of(agents, made)

        assert list(found) == ["map_cells", "tally"]
        for tool in found.values():
            assert (tool["made_as"], tool["tier"], tool["passed"]) == ("A", "A", [])
            assert tool["module"] == "cellmapper.mapping"
            assert [(entry["kind"], entry["status"], entry["file"]) for entry in tool["evidence"]] == [
                ("heldout", "not_run", None),
                ("repo_tests", "not_run", None),
            ]
            assert all("details" not in entry for entry in tool["evidence"])
        json.dumps(found)

    def test_tools_that_did_not_come_to_the_end_of_their_making_are_not_checked(
        self, agents: PaperAgents, prepared: str, replays: Checks
    ) -> None:
        run(agents, prepared, repeats=1)
        replays.gates["tally"] = threading.Event()
        job = agents.start_tools(prepared)
        assert replays.began["tally"].wait(10)
        job.request_stop()
        finish(job)

        assert agents.checks(prepared)["made"] is False and agents.checks(prepared)["tools"] == []
        assert why(agents.start_checks, prepared) == (422, "no_tools")


class TestChecking:
    def test_each_tool_is_checked_both_ways_and_two_kinds_that_pass_make_it_a_tool_of_tier_b(
        self, agents: PaperAgents, made: str, replays: Checks, workspace: Workspace
    ) -> None:
        before = len(replays.runs)
        job = check(agents, made)

        assert job.state == "succeeded" and job.kind == CHECKS_JOB
        assert job.message == "Made 4 checks of 2 tools: 4 passed, 0 failed, 0 not obtained."
        found = tools_of(agents, made)
        for name, tool in found.items():
            assert (tool["made_as"], tool["tier"], tool["passed"]) == ("A", "B", ["heldout", "repo_tests"]), name
            assert statuses(agents, made, name) == {"heldout": "passed", "repo_tests": "passed"}
        # Each tool, and the code's own function, was called with arguments that the tutorial had not passed
        ran = replays.runs[before:]
        assert [one["function"] for one in ran] == [
            "map_cells",
            "lumi_direct",
            "tally",
            "lumi_direct",
        ]
        assert [case["args"] for case in ran[0]["cases"]] == [{"counts": [2, 3]}]
        assert [case["args"] for case in ran[2]["cases"]] == [{"counts": [2, 3, 4], "scale": 3}]
        assert [case["args"] for case in ran[1]["cases"]] == [case["args"] for case in ran[0]["cases"]]
        assert [one["ids"] for one in replays.tests] == [
            ["tests/test_mapping.py::test_map_cells"],
            ["tests/test_mapping.py::test_tally"],
        ]
        json.dumps(found)

    def test_what_each_check_kept_is_in_a_file_that_the_list_names(
        self, agents: PaperAgents, made: str, workspace: Workspace
    ) -> None:
        check(agents, made)
        directory = directory_of(workspace, made)

        for name, tool in tools_of(agents, made).items():
            for entry in tool["evidence"]:
                path = directory / entry["file"]
                assert path == kept_checks.record_path(directory, name, entry["kind"]) and path.is_file()
                assert entry["file"] == f"checks/independent/{name}/{entry['kind']}.json"
        files = sorted(
            path.relative_to(directory).as_posix() for path in (directory / "checks" / "independent").rglob("*.json")
        )
        assert files == [
            "checks/independent/map_cells/heldout.json",
            "checks/independent/map_cells/repo_tests.json",
            "checks/independent/tally/heldout.json",
            "checks/independent/tally/repo_tests.json",
        ]

    def test_a_check_is_bound_to_what_it_was_made_of(
        self, agents: PaperAgents, made: str, workspace: Workspace, docker: Docker
    ) -> None:
        check(agents, made)
        kept = tooling.kept_of(agents, made)
        tool = agents.tool(made, "tally")
        record = record_of(workspace, made, "tally", "heldout")

        assert record["schema"] == 1 and record["tool"] == "tally" and record["kind"] == "heldout"
        assert record["status"] == "passed" and record["summary"] and record["checked_at"]
        assert record["wrapper_sha256"] == tool["wrapper_sha256"]
        assert (record["commit"], record["image_id"]) == (kept["commit"], kept["image_id"])
        assert record["image_id"] == docker.images[reference.tag_of(made)]
        assert record["reference"] == kept["reference"]
        assert record["limits"] == {"minutes": 5, "total_minutes": 30, "repeats": 2, "gigabytes": 2}
        assert record["details"]["counts"]["agree"] == 1 and record["details"]["repeats"] == 2

    def test_a_tool_that_has_only_its_tutorial_stays_at_tier_a(
        self, agents: PaperAgents, made: str, workspace: Workspace, docker: Docker
    ) -> None:
        for name in ("map_cells", "tally"):
            assert tools_of(agents, made)[name]["tier"] == "A"
        view = given.view(workspace, made)
        assert view["tier"] == "A" and {tool["tier"] for tool in view["tools"] if tool["kind"] == "run"} == {"A"}

    def test_one_kind_that_passes_is_not_enough(self, agents: PaperAgents, made: str) -> None:
        check(agents, made, kinds=["heldout"])

        found = tools_of(agents, made)["tally"]
        assert found["tier"] == "A" and found["passed"] == ["heldout"]
        assert statuses(agents, made, "tally") == {"heldout": "passed", "repo_tests": "not_run"}

        check(agents, made, kinds=["repo_tests"])
        assert tools_of(agents, made)["tally"]["tier"] == "B"

    def test_a_kind_that_fails_keeps_a_tool_from_tier_b_whatever_else_passed(
        self, agents: PaperAgents, made: str, replays: Checks
    ) -> None:
        replays.plays["tally"] = lambda case, repeat: {
            "schema": 1,
            "ok": True,
            "error": None,
            "result": tooling.value_of(-1),
            "seconds": 0.1,
            "output": "",
        }
        job = check(agents, made)

        assert job.state == "succeeded" and job.message.startswith("Made 4 checks of 2 tools: 3 passed, 1 failed")
        assert statuses(agents, made, "tally") == {"heldout": "failed", "repo_tests": "passed"}
        assert tools_of(agents, made)["tally"]["tier"] == "A" and tools_of(agents, made)["map_cells"]["tier"] == "B"
        failed = next(entry for entry in tools_of(agents, made)["tally"]["evidence"] if entry["kind"] == "heldout")
        assert "What the tool gave is not what the code's own function gave" in failed["summary"]

    def test_tests_of_the_code_that_fail_fail_the_kind_and_say_which(
        self, agents: PaperAgents, made: str, replays: Checks
    ) -> None:
        failure = {"name": "tests.test_mapping::test_tally", "message": "assert 2 == 3"}
        replays.tests_play = lambda ids: {**passed_tests(ids), "passed": 0, "failed": len(ids), "failures": [failure]}
        check(agents, made)

        assert statuses(agents, made, "tally") == {"heldout": "passed", "repo_tests": "failed"}
        assert tools_of(agents, made)["tally"]["tier"] == "A"
        detail = agents.check_of_tool(made, "tally")["evidence"][1]
        assert detail["status"] == "failed" and detail["details"]["failures"] == [failure]
        assert "assert 2 == 3" in detail["summary"]

    def test_a_kind_that_could_not_be_obtained_is_neither_a_pass_nor_a_failure(
        self, agents: PaperAgents, made: str, replays: Checks
    ) -> None:
        replays.tests_play = lambda ids: {
            **passed_tests(ids),
            "ran": False,
            "reason": "pytest is not in the environment, and nothing can be installed",
            "tests": 0,
            "passed": 0,
        }
        job = check(agents, made)

        assert job.message == "Made 4 checks of 2 tools: 2 passed, 0 failed, 2 not obtained."
        assert statuses(agents, made, "tally") == {"heldout": "passed", "repo_tests": "not_obtained"}
        found = tools_of(agents, made)["tally"]
        assert found["tier"] == "A" and found["passed"] == ["heldout"]
        assert "pytest is not in the environment" in found["evidence"][1]["summary"]

    def test_tests_that_wrote_no_result_are_not_obtained(self, agents: PaperAgents, made: str, replays: Checks) -> None:
        replays.tests_play = lambda ids: None
        check(agents, made)

        assert statuses(agents, made, "tally")["repo_tests"] == "not_obtained"
        assert tools_of(agents, made)["tally"]["tier"] == "A"

    def test_a_result_of_the_tests_that_is_not_in_the_shape_written_is_not_believed(
        self, agents: PaperAgents, made: str, replays: Checks
    ) -> None:
        replays.tests_play = lambda ids: {"schema": 1, "ran": True, "tests": 99, "passed": 99}
        check(agents, made)

        assert statuses(agents, made, "tally")["repo_tests"] == "not_obtained"

    def test_a_function_that_no_test_calls_has_none_to_run(
        self, agents: PaperAgents, remote: Remote, prepared: str, replays: Checks
    ) -> None:
        agents.clear_repository(prepared)
        remote.files = {
            **remote.files,
            "tests/test_mapping.py": "from cellmapper.mapping import tally\n\n\ndef test_t():\n    tally([1])\n",
        }
        fetch(agents, prepared)
        reference.build(agents, prepared)
        run(agents, prepared, repeats=1)
        make(agents, prepared)
        check(agents, prepared)

        assert statuses(agents, prepared, "map_cells") == {"heldout": "passed", "repo_tests": "not_obtained"}
        assert statuses(agents, prepared, "tally") == {"heldout": "passed", "repo_tests": "passed"}
        assert (
            "No test in the code calls map_cells" in tools_of(agents, prepared)["map_cells"]["evidence"][1]["summary"]
        )
        assert [one["ids"] for one in replays.tests] == [["tests/test_mapping.py::test_t"]]

    def test_checking_again_replaces_what_was_kept(self, agents: PaperAgents, made: str, replays: Checks) -> None:
        check(agents, made)
        assert tools_of(agents, made)["tally"]["tier"] == "B"
        replays.tests_play = lambda ids: {**passed_tests(ids), "passed": 0, "failed": 1, "failures": []}
        check(agents, made)

        assert statuses(agents, made, "tally") == {"heldout": "passed", "repo_tests": "failed"}
        assert tools_of(agents, made)["tally"]["tier"] == "A"

    def test_only_the_tools_that_are_named_are_checked(self, agents: PaperAgents, made: str, replays: Checks) -> None:
        before = len(replays.runs)
        job = check(agents, made, tools=["tally"])

        assert job.message == "Made 2 checks of 1 tool: 2 passed, 0 failed, 0 not obtained."
        assert replays.checked(before) == ["tally"]
        assert [one["ids"] for one in replays.tests] == [["tests/test_mapping.py::test_tally"]]
        assert tools_of(agents, made)["tally"]["tier"] == "B" and tools_of(agents, made)["map_cells"]["tier"] == "A"

    def test_what_a_runner_is_given_is_what_the_tools_were_called_with(
        self, agents: PaperAgents, made: str, replays: Checks, docker: Docker
    ) -> None:
        check(agents, made, minutes=2, total_minutes=10, repeats=1, gigabytes=1)

        run_ = replays.runs[-1]
        assert run_["limits"] == making.ToolLimits(minutes=2, total_minutes=10, repeats=1, gigabytes=1)
        assert (run_["tag"], run_["label"], run_["data"]) == (reference.tag_of(made), made, None)
        assert run_["repeats"] == 1 and run_["spec_seconds"] <= 2 * 60 / 2
        assert not run_["scratch"].exists()
        tests = replays.tests[-1]
        assert tests["files"] == [".lumi-runner.py", ".lumi-tests.json", "lumi_record.py"]
        assert tests["spec_seconds"] <= 2 * 60 and tests["label"] == made and tests["data"] is None

    def test_the_code_is_read_for_what_each_function_takes_and_never_run_on_this_machine(
        self, agents: PaperAgents, made: str, replays: Checks, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: list[Any] = []
        original = subprocess.run
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a) or original(*a, **k))
        check(agents, made, kinds=["heldout"])

        assert not any("python" in str(command) and "pytest" in str(command) for command in called)

    def test_the_data_that_the_tutorials_were_given_is_given_to_the_checks_too(
        self, agents: PaperAgents, prepared: str, replays: Checks, workspace: Workspace
    ) -> None:
        reference.keep_data(workspace, prepared)
        run(agents, prepared, repeats=1)
        make(agents, prepared)
        check(agents, prepared)

        data = replays.runs[-1]["data"]
        assert data is not None and data.name == "data"
        assert replays.tests[-1]["data"] == data

    def test_the_time_that_all_of_the_checks_may_take_is_not_gone_beyond(
        self, agents: PaperAgents, made: str, replays: Checks, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Clock:
            """Time that goes on a minute each time it is asked."""

            def __init__(self) -> None:
                self.now = 0.0

            def monotonic(self) -> float:
                self.now += 60
                return self.now

        monkeypatch.setattr(checkwork, "time", Clock())
        job = check(agents, made, total_minutes=3)

        assert job.state == "succeeded"
        assert "were not made, as the time was used" in job.message
        made_ = [entry["status"] for tool in tools_of(agents, made).values() for entry in tool["evidence"]]
        assert made_.count("passed") < 4 and made_.count("passed") >= 1
        assert made_.count("not_run") >= 1


class TestWhenItGoesWrong:
    def test_a_job_that_is_stopped_keeps_the_checks_it_had_made_and_not_the_one_it_was_making(
        self, agents: PaperAgents, made: str, replays: Checks, workspace: Workspace
    ) -> None:
        replays.gates["tally"] = threading.Event()
        job = agents.start_checks(made)
        assert replays.began["tally"].wait(10)
        assert agents.view(made)["steps"]["tools"] == "running"
        job.request_stop()
        finish(job)

        assert job.state == "stopped"
        found = tools_of(agents, made)
        assert found["map_cells"]["evidence"][0]["status"] == "passed"
        assert [entry["status"] for entry in found["tally"]["evidence"]] == ["not_run", "not_run"]
        assert found["tally"]["tier"] == "A"
        del replays.gates["tally"]
        check(agents, made)
        assert tools_of(agents, made)["tally"]["tier"] == "B"

    def test_docker_that_stops_answering_fails_the_job_and_does_not_blame_the_tool(
        self, agents: PaperAgents, made: str, replays: Checks
    ) -> None:
        replays.broken = DockerUnavailableError("Docker did not run the tool: Cannot connect to the Docker daemon")
        job = check(agents, made)

        assert job.state == "failed" and job.error is not None and "Cannot connect" in job.error
        assert all(
            entry["status"] == "not_run" for tool in tools_of(agents, made).values() for entry in tool["evidence"]
        )

    def test_a_check_that_could_not_be_made_does_not_take_away_a_tier_that_was_earned(
        self, agents: PaperAgents, made: str, replays: Checks
    ) -> None:
        check(agents, made)
        replays.broken = DockerUnavailableError("Docker did not run the tool: gone")
        assert check(agents, made).state == "failed"

        assert tools_of(agents, made)["tally"]["tier"] == "B"


class TestWhileTheyAreChecked:
    def test_nothing_that_would_change_what_is_checked_is_done_until_it_has_ended(
        self, agents: PaperAgents, made: str, replays: Checks
    ) -> None:
        replays.gates["map_cells"] = threading.Event()
        job = agents.start_checks(made)
        assert replays.began["map_cells"].wait(10)

        assert agents.checks(made)["job"]["id"] == job.id
        for action in (
            lambda: agents.start_checks(made),
            lambda: agents.start_tools(made),
            lambda: agents.start_reference(made),
            lambda: agents.clear_checks(made),
            lambda: agents.clear_tools(made),
            lambda: agents.clear_reference(made),
            lambda: agents.clear_environment(made),
            lambda: agents.clear_repository(made),
            lambda: agents.build_environment(made),
            lambda: agents.delete(made),
        ):
            error = refused(action)
            assert error.status == 409 and error.code == "busy", action

        replays.gates["map_cells"].set()
        finish(job)
        assert job.state == "succeeded" and agents.view(made)["steps"]["tools"] == "done"

    def test_checks_are_not_started_while_something_else_is_being_done_to_the_agent(
        self, agents: PaperAgents, prepared: str, containers: Containers
    ) -> None:
        containers.gates[SCRIPT] = containers.gates[NOTEBOOK] = threading.Event()
        job = agents.start_reference(prepared, repeats=1)
        first = next(item["path"] for item in agents.reference(prepared)["plan"]["runnable"])
        assert containers.began[first].wait(10)

        assert why(agents.start_checks, prepared) == (409, "busy")
        job.request_stop()
        finish(job)


class TestWhatTheyBelongTo:
    def test_checks_go_with_the_tools_that_are_taken_away(
        self, agents: PaperAgents, made: str, workspace: Workspace
    ) -> None:
        check(agents, made)
        directory = directory_of(workspace, made)
        assert (directory / "checks" / "independent").is_dir()

        agents.clear_tools(made)

        assert not (directory / "checks" / "independent").exists()
        make(agents, made)
        assert [entry["status"] for entry in tools_of(agents, made)["tally"]["evidence"]] == ["not_run", "not_run"]

    @pytest.mark.parametrize("operation", ["clear_reference", "clear_environment", "clear_repository"])
    def test_checks_go_with_what_the_tools_were_made_from(
        self, agents: PaperAgents, made: str, workspace: Workspace, operation: str
    ) -> None:
        check(agents, made)
        directory = directory_of(workspace, made)

        getattr(agents, operation)(made)

        assert not (directory / "checks" / "independent").exists()
        assert tools_of(agents, made) == {}

    def test_making_the_tools_again_takes_away_the_checks_of_the_tools_before(
        self, agents: PaperAgents, made: str, workspace: Workspace
    ) -> None:
        check(agents, made)
        directory = directory_of(workspace, made)
        kept_tools.begin(directory, {**cast(dict[str, Any], kept_tools.stored(directory)), "tools": []})

        assert not (directory / "checks" / "independent").exists()

    def test_deleting_the_agent_takes_all_of_it_away(
        self, agents: PaperAgents, made: str, workspace: Workspace
    ) -> None:
        check(agents, made)
        agents.delete(made)

        assert not directory_of(workspace, made).exists()

    def test_taking_the_checks_away_leaves_the_tools_at_the_tier_they_were_made(
        self, agents: PaperAgents, made: str, workspace: Workspace
    ) -> None:
        check(agents, made)
        assert tools_of(agents, made)["tally"]["tier"] == "B"

        agents.clear_checks(made)

        found = tools_of(agents, made)
        assert [tool["tier"] for tool in found.values()] == ["A", "A"]
        assert tooling.kept_of(agents, made)["complete"] is True
        assert not (directory_of(workspace, made) / "checks" / "independent").exists()
        agents.clear_checks(made)


class TestWhatIsNotWhatIsKeptNow:
    def test_a_check_of_a_wrapper_that_has_been_rewritten_counts_for_nothing_until_it_is_checked_again(
        self, agents: PaperAgents, made: str, workspace: Workspace
    ) -> None:
        check(agents, made)
        directory = directory_of(workspace, made)
        folder = kept_tools.tool_path(directory, "tally")
        tool = agents.tool(made, "tally")
        # A rewrite that still calls the function and is recorded as the wrapper that the tool is, which is what a
        # repair of a wrapper would leave
        source = tool["source"] + "# rewritten\n"
        (folder / wrappers.WRAPPER_FILE).write_text(source)
        record = json.loads((folder / kept_tools.TOOL_FILE).read_text())
        record["wrapper_sha256"] = hashlib.sha256(source.encode()).hexdigest()
        (folder / kept_tools.TOOL_FILE).write_text(json.dumps(record))

        found = tools_of(agents, made)["tally"]
        assert found["tier"] == "A" and found["passed"] == []
        assert [entry["status"] for entry in found["evidence"]] == ["stale", "stale"]
        assert [entry["was"] for entry in found["evidence"]] == ["passed", "passed"]
        assert "counts for nothing" in found["evidence"][0]["summary"]
        assert tools_of(agents, made)["map_cells"]["tier"] == "B"
        check(agents, made, tools=["tally"])
        assert tools_of(agents, made)["tally"]["tier"] == "B"

    @pytest.mark.parametrize("key", ["wrapper_sha256", "commit", "image_id", "reference"])
    def test_a_check_that_is_bound_to_something_else_is_stale(
        self, agents: PaperAgents, made: str, workspace: Workspace, key: str
    ) -> None:
        check(agents, made)
        value: Any = {
            "wrapper_sha256": "b" * 64,
            "commit": "b" * 40,
            "image_id": "sha256:other",
            "reference": {"started_at": "x", "finished_at": "y"},
        }[key]
        rewrite(workspace, made, "tally", "heldout", {key: value})

        found = tools_of(agents, made)["tally"]
        assert [entry["status"] for entry in found["evidence"]] == ["stale", "passed"]
        assert found["tier"] == "A"

    @pytest.mark.parametrize(
        "change",
        [
            {"status": "great"},
            {"schema": 2},
            {"kind": "repo_tests"},
            {"tool": "map_cells"},
            {"commit": "abc"},
            {"image_id": "latest"},
            {"wrapper_sha256": "short"},
            {"details": "none"},
            {"seconds": "slow"},
            {"checked_at": 5},
        ],
    )
    def test_a_check_that_is_not_in_the_shape_written_is_not_shown_as_made(
        self, agents: PaperAgents, made: str, workspace: Workspace, change: dict[str, Any]
    ) -> None:
        check(agents, made)
        rewrite(workspace, made, "tally", "heldout", change)

        found = tools_of(agents, made)["tally"]
        assert [entry["status"] for entry in found["evidence"]] == ["not_run", "passed"]
        assert found["tier"] == "A"

    def test_a_file_that_is_not_json_or_is_a_link_or_too_big_is_not_read(
        self, agents: PaperAgents, made: str, workspace: Workspace, tmp_path: Path
    ) -> None:
        check(agents, made)
        path = kept_checks.record_path(directory_of(workspace, made), "tally", "heldout")
        text = path.read_text()
        for content in ("not json", "[]", "null"):
            path.write_text(content)
            assert tools_of(agents, made)["tally"]["evidence"][0]["status"] == "not_run"
        path.write_text(text + " " * kept_checks.MAX_RECORD_BYTES)
        assert tools_of(agents, made)["tally"]["evidence"][0]["status"] == "not_run"
        outside = tmp_path / "outside.json"
        outside.write_text(text)
        path.unlink()
        path.symlink_to(outside)
        assert tools_of(agents, made)["tally"]["evidence"][0]["status"] == "not_run"

    def test_a_folder_of_checks_that_is_a_link_is_not_followed(
        self, agents: PaperAgents, made: str, workspace: Workspace, tmp_path: Path
    ) -> None:
        check(agents, made)
        folder = kept_checks.record_path(directory_of(workspace, made), "tally", "heldout").parent
        outside = tmp_path / "outside"
        folder.rename(outside)
        folder.symlink_to(outside)

        assert [entry["status"] for entry in tools_of(agents, made)["tally"]["evidence"]] == ["not_run", "not_run"]
        assert tools_of(agents, made)["tally"]["tier"] == "A"

    def test_a_tool_that_says_it_is_of_tier_b_is_not_shown_and_its_tier_is_what_its_checks_come_to(
        self, agents: PaperAgents, made: str, workspace: Workspace
    ) -> None:
        directory = directory_of(workspace, made)
        path = kept_tools.tool_path(directory, "tally") / kept_tools.TOOL_FILE
        path.write_text(json.dumps({**json.loads(path.read_text()), "tier": "B"}))

        assert "tally" not in tools_of(agents, made)

    def test_what_is_not_a_tool_and_a_kind_has_no_place(self, tmp_path: Path) -> None:
        for name, kind in (("../x", "heldout"), ("tally", "../x"), ("tally", "other"), ("", "heldout")):
            with pytest.raises(ValueError, match="a tool and a kind of check"):
                kept_checks.record_path(tmp_path, name, kind)
        assert kept_checks.load(tmp_path, "../x", "heldout") is None
        assert kept_checks.load(tmp_path, "tally", "other") is None


class TestWhatIsAsked:
    @pytest.mark.parametrize(
        "options",
        [
            {"minutes": 0},
            {"minutes": 31},
            {"total_minutes": 181},
            {"repeats": 4},
            {"gigabytes": 21},
            {"minutes": True},
            {"kinds": []},
            {"kinds": ["heldout", "heldout"]},
            {"kinds": ["magic"]},
            {"kinds": "heldout"},
            {"tools": []},
            {"tools": ["tally", "tally"]},
            {"tools": "tally"},
            {"tools": [1]},
        ],
    )
    def test_what_is_not_fit_is_refused_and_nothing_is_run(
        self, agents: PaperAgents, made: str, replays: Checks, options: dict[str, Any]
    ) -> None:
        before = len(replays.runs)

        assert why(agents.start_checks, made, **options) == (422, "invalid")
        assert len(replays.runs) == before and replays.tests == []

    def test_a_tool_that_is_not_there_is_not_found(self, agents: PaperAgents, made: str) -> None:
        assert why(agents.start_checks, made, tools=["nothing"]) == (404, "not_found")
        assert refused(agents.check_of_tool, made, "nothing").status == 404
        assert refused(agents.check_of_tool, made, "../x").status == 404

    def test_docker_that_is_not_running_is_said_and_nothing_is_run(
        self, agents: PaperAgents, made: str, docker: Docker, replays: Checks
    ) -> None:
        docker.usable = (False, "Docker is not running.")

        assert why(agents.start_checks, made) == (422, "docker_missing")
        assert agents.checks(made)["docker"] == {"ready": False, "message": "Docker is not running."}
        assert replays.tests == []

    def test_an_image_that_is_gone_from_docker_is_said(
        self, agents: PaperAgents, made: str, docker: Docker, replays: Checks
    ) -> None:
        docker.images.clear()

        assert why(agents.start_checks, made) == (409, "image_missing")
        assert replays.tests == []

    def test_leftover_containers_of_the_agent_are_taken_away_before_the_checks(
        self, agents: PaperAgents, made: str, docker: Docker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        removed: list[str] = []
        monkeypatch.setattr(referencing, "remove_runs", lambda agent_id, command: removed.append(agent_id))
        check(agents, made)

        assert removed[0] == made

    def test_one_tool_with_its_checks_and_what_each_was_made_of(self, agents: PaperAgents, made: str) -> None:
        check(agents, made)
        found = agents.check_of_tool(made, "tally")

        assert (found["name"], found["made_as"], found["tier"]) == ("tally", "A", "B")
        assert "does not show that what the tool gives is right" in found["meaning"]
        heldout, tests = found["evidence"]
        assert heldout["details"]["counts"]["agree"] == 1 and heldout["limits"]["repeats"] == 2
        assert tests["details"]["ids"] == ["tests/test_mapping.py::test_tally"]
        assert heldout["seconds"] >= 0 and heldout["file"].endswith("tally/heldout.json")
        json.dumps(found)


class TestWhatAConversationIsGiven:
    def tools(self, workspace: Workspace, agent_id: str) -> dict[str, Any]:
        return {tool.name: tool for tool in given.agent_tools(workspace, [agent_id], SESSION)}

    def test_a_tool_of_tier_b_says_so_and_what_passed_to_the_model_and_the_page(
        self, agents: PaperAgents, made: str, workspace: Workspace
    ) -> None:
        check(agents, made)

        tally = self.tools(workspace, made)[f"{made}_tally"]
        assert tally.description.startswith('[Tier B] From the PaperAgent "CellMapper". Runs the authors\' own code')
        assert (
            "and passed checks that its tutorial did not give it (inputs the tutorial did not use and"
            in tally.description
        )
        assert "the code's own tests)" in tally.description
        assert "does not show that what it gives is right" in tally.description
        view = given.view(workspace, made)
        assert view["tier"] == "B"
        assert [(tool["kind"], tool["tier"]) for tool in view["tools"] if tool["kind"] == "run"] == [
            ("run", "B"),
            ("run", "B"),
        ]
        assert "tier B" in view["meaning"]

    def test_a_call_of_a_tool_of_tier_b_says_it_is(self, agents: PaperAgents, made: str, workspace: Workspace) -> None:
        check(agents, made)

        answer = self.tools(workspace, made)[f"{made}_tally"].function(counts=[1, 2, 3], scale=2)

        assert answer["tier"] == "B" and answer["result"] == {"type": "int", "value": 12}

    def test_only_the_tool_that_passed_is_of_tier_b_and_so_is_the_agent_that_has_one(
        self, agents: PaperAgents, made: str, workspace: Workspace
    ) -> None:
        check(agents, made, tools=["tally"])

        found = self.tools(workspace, made)
        assert found[f"{made}_tally"].description.startswith("[Tier B]")
        assert found[f"{made}_map_cells"].description.startswith("[Tier A]")
        assert "passed checks" not in found[f"{made}_map_cells"].description
        assert given.view(workspace, made)["tier"] == "B"

    def test_a_tool_whose_checks_were_taken_away_is_of_tier_a_again_at_once(
        self, agents: PaperAgents, made: str, workspace: Workspace
    ) -> None:
        check(agents, made)
        held = self.tools(workspace, made)[f"{made}_tally"]
        agents.clear_checks(made)

        assert held.function(counts=[1], scale=1)["tier"] == "A"
        assert self.tools(workspace, made)[f"{made}_tally"].description.startswith("[Tier A]")
        assert given.view(workspace, made)["tier"] == "A"


class TestOverHttp:
    def wait_for(self, client: TestClient, agent_id: str, step: str, status: str) -> None:
        tooling.TestOverHttp().wait_for(client, agent_id, step, status)

    def wait_until(self, done: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 20
        while not done():
            assert time.monotonic() < deadline
            time.sleep(0.02)

    def test_checking_asking_and_taking_away(
        self, client: TestClient, remote: Remote, docker: Docker, containers: Containers, replays: Checks
    ) -> None:
        remote.files = {
            **remote.files,
            SCRIPT: "print(1)\n",
            "cellmapper/mapping.py": MAPPING,
            "tests/test_mapping.py": TESTS,
        }
        containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=CALLS))
        made = client.post(
            "/api/paperagents",
            json={"title": "CellMapper", "paper": {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}, "repo": URL},
        )
        agent_id = made.json()["id"]
        base = f"/api/paperagents/{agent_id}"
        assert client.post(f"{base}/checks", json={}).status_code == 422
        client.post(f"{base}/repository", json={})
        self.wait_for(client, agent_id, "repository", "done")
        client.post(f"{base}/environment", json={})
        self.wait_for(client, agent_id, "environment", "done")
        client.post(f"{base}/reference", json={"repeats": 1, "data": False})
        self.wait_until(lambda: client.get(f"{base}/tools").json()["reference"] is not None)
        client.post(f"{base}/tools", json={"repeats": 1})
        self.wait_for(client, agent_id, "tools", "done")

        shown = client.get(f"{base}/checks").json()
        assert [tool["tier"] for tool in shown["tools"]] == ["A", "A"] and shown["job"] is None
        started = client.post(f"{base}/checks", json={"minutes": 2, "repeats": 1, "kinds": ["heldout"]})
        assert started.status_code == 202 and started.json()["kind"] == CHECKS_JOB
        self.wait_until(lambda: client.get(f"{base}/checks").json()["job"] is None)
        shown = client.get(f"{base}/checks").json()
        assert [tool["passed"] for tool in shown["tools"]] == [["heldout"], ["heldout"]]
        assert [tool["tier"] for tool in shown["tools"]] == ["A", "A"]

        client.post(f"{base}/checks", json={"kinds": ["repo_tests"]})
        self.wait_until(lambda: client.get(f"{base}/checks").json()["job"] is None)
        tool = client.get(f"{base}/checks/tally")
        assert tool.status_code == 200 and tool.json()["tier"] == "B"
        assert tool.json()["evidence"][0]["details"]["counts"]["agree"] == 1
        assert client.get(f"{base}/checks/nothing").status_code == 404
        assert client.get(f"{base}/given").json()["tier"] == "B"

        removed = client.delete(f"{base}/checks")
        assert removed.status_code == 200 and [tool["tier"] for tool in removed.json()["tools"]] == ["A", "A"]
        assert client.get(f"{base}/tools").json()["kept"]["complete"] is True

    def test_a_body_that_is_not_what_is_asked_for_is_refused(self, client: TestClient, docker: Docker) -> None:
        made = client.post(
            "/api/paperagents",
            json={"title": "CellMapper", "paper": {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}},
        )
        base = f"/api/paperagents/{made.json()['id']}/checks"

        for body in (
            {"minutes": "5"},
            {"repeats": 1.5},
            {"gigabytes": True},
            {"kinds": "heldout"},
            {"kinds": [1]},
            {"tools": "tally"},
            {"tools": ["a" * 65]},
            {"tools": ["a"] * 101},
            {"surprise": 1},
        ):
            assert client.post(base, json=body).status_code == 422, body

    def test_it_is_not_there_without_the_token_or_for_an_agent_that_is_not(self, client: TestClient) -> None:
        assert client.get("/api/paperagents/nothing/checks").status_code == 404
        assert client.post("/api/paperagents/nothing/checks", json={}).status_code == 404
        assert client.get("/api/paperagents/nothing/checks/tally").status_code == 404
        assert client.delete("/api/paperagents/nothing/checks").status_code == 404
        bare = TestClient(client.app, base_url=LOCAL)
        assert bare.get("/api/paperagents/nothing/checks").status_code == 401


def test_the_functions_the_stand_in_knows_are_those_of_the_fixture() -> None:
    assert set(FUNCTIONS) == {"map_cells", "tally"}
