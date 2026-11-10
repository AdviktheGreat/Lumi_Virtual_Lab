"""Tests of making tools: that a tool is made only of a wrapper that calls the authors' own function, that it is called
again in a fresh process on a fresh copy of the project and is held to what the tutorial got, that what differs is
dropped with why and is never changed to fit, that the limits hold, and, where Docker is there, that real calls are made
offline in containers that are removed.

The calls are made on this machine in most tests, by the same runner that runs in a container, so that what is made of
real recorded calls is tested without an image. The tests of a container build an image of the project as environments
are built.
"""

import ast
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_paperagents_environment import needs_docker
from test_paperagents_reference import BASE, RUNNER, run_ids, tutorial
from test_paperagents_stock import tree
from test_paperagents_wrappers import call_of, detail_of

from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerUnavailableError
from virtual_lab.paperagents import environment as env
from virtual_lab.paperagents import reference as ref
from virtual_lab.paperagents import toolmaking as tm
from virtual_lab.paperagents import wrappers as wrap
from virtual_lab.paperagents.comparing import Tolerance
from virtual_lab.paperagents.reference import Limits, Runner

IMAGE = "sha256:image"

CORE = '''
import os
import random
import socket
import time


def mean(values, scale=1.0):
    """Gives the mean of the values."""
    return sum(values) / len(values) * scale


def third(x):
    return x / 3


def secret(n):
    return "answer-" + str(n * 7919)


def jitter(x):
    return x + random.random()


def has_file(name):
    return os.path.exists(name)


def read_note(name):
    with open(name) as handle:
        return handle.read()


def write_once(name):
    if os.path.exists(name):
        raise FileExistsError(name)
    with open(name, "w") as handle:
        handle.write("x")
    return len(name)


_seen = []


def count(x):
    _seen.append(x)
    return len(_seen)


def shout(x):
    print("hello", x)
    return x


def nonfinite(x):
    return {"a": float("nan"), "b": float("inf"), "c": x}


def length(items):
    return len(items)


def reach():
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=3)
        return True
    except OSError:
        return False


def secrets():
    return [key for key in os.environ if "SECRET" in key]


def pause(seconds):
    time.sleep(seconds)
    return seconds
'''
DEMO = """
import fixture

fixture.mean([1, 2, 3, 4])
fixture.mean([2.5, 3.5], scale=2)
fixture.third(1)
fixture.secret(2)
fixture.jitter(1.0)
fixture.has_file("data.txt")
open("note.txt", "w").write("made by the tutorial")
fixture.read_note("note.txt")
fixture.write_once("out.txt")
fixture.count(1)
fixture.count(1)
fixture.shout("hi")
fixture.nonfinite(3)
fixture.length((1, 2, 3))
fixture.length([1, 2])
"""
FILES = {**BASE, "fixture/core.py": CORE, "examples/demo.py": DEMO, "examples/data.txt": "data\n"}


@pytest.fixture
def processors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env, "cpus_for", lambda *a, **k: "2")


class LocalRunner(tm.ToolRunner):
    """Calls the wrappers as the container does, with the same runner, on this machine."""

    def __init__(self, repo: Path, scratch: Path, limits: tm.ToolLimits | None = None, **options: Any) -> None:
        super().__init__("local", limits or tm.ToolLimits(), scratch, label="tooltest", **options)
        self.repo = repo
        self.seen: list[dict[str, str]] = []
        self.seconds: list[float] = []

    def execute(self, folder: Path, item: ref.Item, seconds: float) -> tuple[str, int | None, str]:
        self.seen.append({path.name: path.read_text() for path in folder.iterdir() if path.is_file()})
        self.seconds.append(seconds)
        if self.stop.is_set():
            return "stopped", None, ""
        done = subprocess.run(
            [sys.executable, str(folder / ref.RUNNER_AT), "run", item.path, "--repo", str(self.repo)]
            + ["--work", str(folder)],
            capture_output=True,
            text=True,
            timeout=seconds + 30,
            check=False,
            env={**os.environ, "LUMI_TIME_LIMIT": str(int(seconds) + 5)},
        )

        return "done", done.returncode, done.stdout + done.stderr


def record(root: Path, files: dict[str, Any], scripts: list[str]) -> tuple[Path, list[dict[str, Any]]]:
    """The records of tutorials that were run here, by the runner that records them, as a reference run keeps them."""
    repo = tree(root / "repo", files)
    details = []
    for number, path in enumerate(scripts, 1):
        work = root / f"work{number}"
        work.mkdir()
        subprocess.run(
            [sys.executable, str(RUNNER), "script", path, "--repo", str(repo), "--work", str(work)],
            capture_output=True,
            timeout=60,
            check=False,
        )
        result = json.loads((work / ref.RESULT_FOLDER / "result.json").read_text())
        details.append(
            {
                "id": ref.slug(number, path),
                "path": path,
                "status": "ok" if result["ok"] else "failed",
                "calls": result["calls"],
            }
        )

    return repo, details


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[dict[str, Any]], wrap.Gathered]:
    repo, details = record(tmp_path_factory.mktemp("recorded"), FILES, ["examples/demo.py"])
    assert details[0]["status"] == "ok", details
    gathered = wrap.gather(details, repo, 50)

    return repo, details, gathered


def candidate_of(gathered: wrap.Gathered, name: str) -> wrap.Candidate:
    return next(candidate for candidate in gathered.candidates if candidate.name == name)


@pytest.fixture(scope="module")
def made(
    recorded: tuple[Path, list[dict[str, Any]], wrap.Gathered], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Any]:
    """Every function of the fixture that the tutorial called, made into a tool or dropped, once for all of the tests
    that look at what came of it."""
    repo, _, gathered = recorded
    scratch = tmp_path_factory.mktemp("scratch")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(env, "cpus_for", lambda *a, **k: "2")
        runner = LocalRunner(repo, scratch)
    events: list[tuple[str, str]] = []
    outcomes: dict[str, tm.Made] = {}

    def made_one(candidate: wrap.Candidate, one: tm.Made) -> None:
        events.append(("made", candidate.name))
        outcomes[candidate.name] = one

    not_tried = tm.make_tools(
        runner, gathered, IMAGE, lambda candidate, number, total: events.append(("start", candidate.name)), made_one
    )

    return {"runner": runner, "outcomes": outcomes, "events": events, "not_tried": not_tried, "scratch": scratch}


def tier_a(outcomes: dict[str, tm.Made], name: str) -> dict[str, Any]:
    one = outcomes[name]
    assert one.dropped is None and one.record is not None, one.dropped

    return one.record


def dropped(outcomes: dict[str, tm.Made], name: str) -> dict[str, Any]:
    one = outcomes[name]
    assert one.record is None and one.dropped is not None, name

    return one.dropped


class TestWhatIsMade:
    def test_a_function_whose_calls_all_give_again_what_they_gave_is_a_tool_of_tier_a(
        self, made: dict[str, Any]
    ) -> None:
        tool = tier_a(made["outcomes"], "mean")
        assert tool["tier"] == "A" and tool["name"] == "mean" and tool["wrapper"] == "wrapper.py"
        assert tool["repo"] == {"module": "fixture.core", "function": "mean", "file": "fixture/core.py", "line": 8}
        assert [item["name"] for item in tool["signature"]] == ["values", "scale"]
        assert tool["description"].startswith("Calls `fixture.core.mean`") and "Gives the mean" in tool["description"]
        evidence = tool["evidence"]
        assert evidence["kind"] == "reference_run" and evidence["image_id"] == IMAGE
        assert evidence["checked"] == 2 and evidence["recorded"] == 2 and evidence["repeats"] == 2
        assert evidence["tolerance"] == Tolerance().to_dict()
        assert [item["verdict"] for item in evidence["cases"]] == ["match", "match"]
        assert [item["matched"] for item in evidence["cases"]] == [2, 2]
        assert evidence["cases"][1]["args"] == {"values": [2.5, 3.5], "scale": 2}
        assert evidence["cases"][1]["expected"]["value"] == 6.0 and evidence["repairs"] == []

    def test_the_hash_of_the_wrapper_is_the_hash_of_what_is_kept(self, made: dict[str, Any]) -> None:
        one = made["outcomes"]["mean"]
        assert one.record is not None and one.source is not None
        assert one.record["wrapper_sha256"] == hashlib.sha256(one.source.encode()).hexdigest()

    def test_every_tool_is_a_wrapper_that_does_no_more_than_call_the_authors_function(
        self, made: dict[str, Any]
    ) -> None:
        tools = [one for one in made["outcomes"].values() if one.record is not None]
        assert len(tools) >= 8
        for one in tools:
            assert one.record is not None and one.source is not None
            repo = one.record["repo"]
            wrapped = wrap.check_wrapper(one.source, repo["module"], repo["function"])
            assert wrapped.name == one.record["name"]
            (function,) = [node for node in ast.parse(one.source).body if isinstance(node, ast.FunctionDef)]
            body = [
                node
                for node in function.body
                if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
            ]
            assert len(body) == 2 and isinstance(body[0], ast.Import) and isinstance(body[1], ast.Return)
            assert [(name.name, name.asname) for name in body[0].names] == [(repo["module"], wrap.ALIAS)]
            (call,) = [node for node in ast.walk(body[1]) if isinstance(node, ast.Call)]
            assert isinstance(call.func, ast.Attribute) and call.func.attr == repo["function"]
            assert isinstance(call.func.value, ast.Name) and call.func.value.id == wrap.ALIAS
            assert all(isinstance(argument.value, ast.Name) for argument in call.keywords) and not call.args

    def test_a_number_that_is_not_finite_and_a_float_are_given_again_as_they_were(self, made: dict[str, Any]) -> None:
        assert tier_a(made["outcomes"], "nonfinite")["evidence"]["cases"][0]["verdict"] == "match"
        third = tier_a(made["outcomes"], "third")["evidence"]["cases"][0]
        assert third["expected"]["value"] == pytest.approx(1 / 3) and third["matched"] == 2

    def test_what_a_function_prints_is_not_held_to(self, made: dict[str, Any]) -> None:
        assert tier_a(made["outcomes"], "shout")["evidence"]["cases"][0]["verdict"] == "match"

    def test_a_call_that_cannot_be_made_again_is_left_out_and_said_and_the_rest_are_held_to(
        self, made: dict[str, Any]
    ) -> None:
        evidence = tier_a(made["outcomes"], "length")["evidence"]
        assert evidence["checked"] == 1 and evidence["recorded"] == 2
        assert evidence["cases"][0]["args"] == {"items": [1, 2]}
        (skipped,) = evidence["skipped"]
        assert "items was a tuple" in skipped["reason"]

    def test_a_call_is_made_from_the_folder_the_tutorial_made_it_from(self, made: dict[str, Any]) -> None:
        case = tier_a(made["outcomes"], "has_file")["evidence"]["cases"][0]
        assert case["cwd"] == "examples" and case["expected"]["value"] is True and case["matched"] == 2

    def test_a_call_that_writes_leaves_nothing_for_the_next_so_that_the_same_call_can_be_made_again(
        self, made: dict[str, Any], recorded: tuple[Path, list[dict[str, Any]], wrap.Gathered]
    ) -> None:
        assert tier_a(made["outcomes"], "write_once")["evidence"]["cases"][0]["matched"] == 2
        assert not (recorded[0] / "examples" / "out.txt").exists()

    def test_a_function_that_gives_something_else_each_time_is_dropped_with_what_it_gave(
        self, made: dict[str, Any]
    ) -> None:
        one = dropped(made["outcomes"], "jitter")
        assert one["kind"] == "replay_differs" and one["name"] == "jitter" and one["calls"] == 1
        assert "gave something else" in one["reason"] and one["details"]
        assert made["outcomes"]["jitter"].source is not None

    def test_a_function_that_counts_its_own_calls_is_not_hidden_by_calling_it_once_in_each_process(
        self, made: dict[str, Any]
    ) -> None:
        assert dropped(made["outcomes"], "count")["kind"] == "replay_differs"

    def test_a_function_that_needs_a_file_the_tutorial_made_is_dropped_with_what_it_may_mean(
        self, made: dict[str, Any]
    ) -> None:
        one = dropped(made["outcomes"], "read_note")
        assert one["kind"] == "replay_error"
        assert any(
            "FileNotFoundError" in line and "may read a file that the tutorial wrote" in line for line in one["details"]
        )

    def test_the_tools_are_made_in_the_order_the_functions_were_called_and_each_is_told_of_when_it_starts_and_ends(
        self, made: dict[str, Any]
    ) -> None:
        events = made["events"]
        assert events[0] == ("start", "mean") and events[1] == ("made", "mean")
        assert [name for kind, name in events if kind == "start"] == [name for kind, name in events if kind == "made"]
        assert made["not_tried"] == []

    def test_nothing_is_left_in_the_folder_that_runs_are_given(self, made: dict[str, Any]) -> None:
        assert list(made["scratch"].iterdir()) == []


class TestWhatIsNotGivenToTheCall:
    def test_the_answer_the_tutorial_got_is_not_in_anything_that_the_call_is_given(self, made: dict[str, Any]) -> None:
        runner = made["runner"]
        assert tier_a(made["outcomes"], "secret")["evidence"]["cases"][0]["expected"]["value"] == "answer-15838"
        assert runner.seen
        for files in runner.seen:
            assert sorted(files) == [".lumi-call.json", "lumi_wrapper.py"] or "lumi_wrapper.py" in files
            for text in files.values():
                assert "answer-15838" not in text

    def test_what_a_call_is_given_is_the_arguments_and_where_it_is_made_from(self, made: dict[str, Any]) -> None:
        spec = next(
            json.loads(files[tm.CALL_FILE]) for files in made["runner"].seen if '"has_file"' in files[tm.CALL_FILE]
        )
        assert spec["function"] == "has_file" and spec["repeats"] == 2 and spec["wrapper"] == tm.WRAPPER_AT
        assert spec["cases"] == [{"id": 0, "args": {"name": "data.txt"}, "cwd": "examples"}]


class TestWhatDoesNotHold:
    def test_a_call_made_from_another_folder_than_the_tutorials_is_not_the_same_call(
        self, tmp_path: Path, recorded: tuple[Path, list[dict[str, Any]], wrap.Gathered], processors: None
    ) -> None:
        repo, _, gathered = recorded
        candidate = candidate_of(gathered, "has_file")
        moved = dataclasses.replace(candidate, cases=[dataclasses.replace(case, cwd=".") for case in candidate.cases])
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        one = tm.make_tool(LocalRunner(repo, scratch), moved, 60, Tolerance(), IMAGE)
        assert one.record is None and one.dropped is not None and one.dropped["kind"] == "replay_differs"

    def test_a_tool_that_is_dropped_is_not_rewritten_until_it_passes(
        self, tmp_path: Path, recorded: tuple[Path, list[dict[str, Any]], wrap.Gathered], processors: None
    ) -> None:
        repo, _, gathered = recorded
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        runner = LocalRunner(repo, scratch, tm.ToolLimits(repairs=3))
        one = tm.make_tool(runner, candidate_of(gathered, "jitter"), 60, Tolerance(), IMAGE)
        assert one.dropped is not None and one.dropped["kind"] == "replay_differs"
        assert len(runner.seen) == 1

    def test_a_function_called_again_is_held_to_a_tolerance_and_a_difference_inside_it_is_not_one(
        self, tmp_path: Path, processors: None
    ) -> None:
        files = {**BASE, "fixture/core.py": CORE, "examples/demo.py": "import fixture\nfixture.third(1)\n"}
        repo, details = record(tmp_path, files, ["examples/demo.py"])
        details[0]["calls"][0]["result"]["value"] += 1e-9
        (candidate,) = wrap.gather(details, repo, 5).candidates
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        runner = LocalRunner(repo, scratch)
        assert tm.make_tool(runner, candidate, 60, Tolerance(), IMAGE).record is not None
        loose = tm.make_tool(runner, candidate, 60, Tolerance(relative=1e-12, absolute=1e-12), IMAGE)
        assert loose.dropped is not None and loose.dropped["kind"] == "replay_differs"

    def test_a_call_that_takes_longer_than_the_tool_is_given_is_stopped_and_the_function_is_dropped(
        self, tmp_path: Path, processors: None
    ) -> None:
        files = {**BASE, "fixture/core.py": CORE, "examples/demo.py": "import fixture\nfixture.pause(0)\n"}
        repo, details = record(tmp_path, files, ["examples/demo.py"])
        details[0]["calls"][0]["args"]["seconds"] = {"type": "int", "plain": True, "value": 30}
        (candidate,) = wrap.gather(details, repo, 5).candidates
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        runner = LocalRunner(repo, scratch)
        began = time.monotonic()
        one = tm.make_tool(runner, candidate, 4, Tolerance(), IMAGE)
        assert one.dropped is not None and one.dropped["kind"] == "timed_out"
        assert time.monotonic() - began < 25
        assert list(scratch.iterdir()) == []

    def test_a_tool_that_does_not_pass_the_checks_of_a_wrapper_is_dropped_before_anything_is_called(
        self, tmp_path: Path, recorded: tuple[Path, list[dict[str, Any]], wrap.Gathered], processors: None
    ) -> None:
        repo, _, gathered = recorded
        candidate = dataclasses.replace(candidate_of(gathered, "mean"), module="fixture.core; import os")
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        runner = LocalRunner(repo, scratch)
        one = tm.make_tool(runner, candidate, 60, Tolerance(), IMAGE)
        assert one.dropped is not None and one.dropped["kind"] == "wrapper" and one.source is None
        assert runner.seen == []


@pytest.mark.usefixtures("processors")
class TestLimits:
    def runner(self, tmp_path: Path, repo: Path, **limits: Any) -> LocalRunner:
        scratch = tmp_path / "scratch"
        scratch.mkdir(exist_ok=True)

        return LocalRunner(repo, scratch, tm.ToolLimits(**limits))

    def test_a_call_is_made_as_many_times_as_it_was_to_be(
        self, tmp_path: Path, recorded: tuple[Path, list[dict[str, Any]], wrap.Gathered]
    ) -> None:
        repo, _, gathered = recorded
        runner = self.runner(tmp_path, repo, repeats=3)
        one = tm.make_tool(runner, candidate_of(gathered, "third"), 60, Tolerance(), IMAGE)
        assert one.record is not None
        assert one.record["evidence"]["repeats"] == 3 and one.record["evidence"]["cases"][0]["matched"] == 3
        assert json.loads(runner.seen[0][tm.CALL_FILE])["repeats"] == 3

    def test_a_tool_is_given_the_time_that_was_allowed_less_what_the_runner_keeps_for_itself(
        self, tmp_path: Path, recorded: tuple[Path, list[dict[str, Any]], wrap.Gathered]
    ) -> None:
        repo, _, gathered = recorded
        runner = self.runner(tmp_path, repo)
        tm.make_tool(runner, candidate_of(gathered, "third"), 100, Tolerance(), IMAGE)
        assert runner.seconds == [100]
        assert json.loads(runner.seen[0][tm.CALL_FILE])["seconds"] == 90

    def test_the_time_left_for_all_of_the_tools_is_what_each_is_given_and_what_is_not_tried_is_dropped_with_why(
        self, tmp_path: Path, recorded: tuple[Path, list[dict[str, Any]], wrap.Gathered]
    ) -> None:
        repo, _, gathered = recorded
        clock = [0.0]
        runner = self.runner(tmp_path, repo, total_minutes=2, minutes=10)
        runner.clock = lambda: clock[0]
        few = wrap.Gathered(gathered.candidates[:3], [], [])

        def after(candidate: wrap.Candidate, one: tm.Made) -> None:
            clock[0] += 100

        not_tried = tm.make_tools(runner, few, IMAGE, lambda *a: None, after)
        assert runner.seconds == [120, 20]
        assert [item["name"] for item in not_tried] == [candidate.name for candidate in few.candidates[2:]]
        assert {item["kind"] for item in not_tried} == {"out_of_time"} and "time for all of the tools" in not_tried[0][
            "reason"
        ]

    def test_a_stop_before_a_tool_is_started_raises_and_what_was_made_was_passed_on(
        self, tmp_path: Path, recorded: tuple[Path, list[dict[str, Any]], wrap.Gathered]
    ) -> None:
        repo, _, gathered = recorded
        runner = self.runner(tmp_path, repo)
        made_names: list[str] = []

        def after(candidate: wrap.Candidate, one: tm.Made) -> None:
            made_names.append(candidate.name)
            runner.stop.set()

        with pytest.raises(StoppedError):
            tm.make_tools(runner, gathered, IMAGE, lambda *a: None, after)
        assert made_names == [gathered.candidates[0].name]

    def test_a_stop_while_a_tool_is_called_raises_and_leaves_nothing(
        self, tmp_path: Path, recorded: tuple[Path, list[dict[str, Any]], wrap.Gathered]
    ) -> None:
        repo, _, gathered = recorded
        runner = self.runner(tmp_path, repo)
        runner.stop.set()
        with pytest.raises(StoppedError):
            tm.make_tool(runner, gathered.candidates[0], 60, Tolerance(), IMAGE)
        assert list((tmp_path / "scratch").iterdir()) == []

    def test_docker_not_running_a_tool_is_not_a_failing_of_the_tool(
        self, tmp_path: Path, recorded: tuple[Path, list[dict[str, Any]], wrap.Gathered]
    ) -> None:
        repo, _, gathered = recorded
        runner = self.runner(tmp_path, repo)
        runner.execute = lambda folder, item, seconds: ("done", ref.DOCKER_FAILED, "docker: Cannot connect\n")  # type: ignore[method-assign]
        with pytest.raises(DockerUnavailableError, match="Cannot connect"):
            tm.make_tool(runner, gathered.candidates[0], 60, Tolerance(), IMAGE)
        assert list((tmp_path / "scratch").iterdir()) == []

    def test_a_container_that_ended_before_any_call_said_how_it_went_is_a_failing_of_the_tool_and_says_so(
        self, tmp_path: Path, recorded: tuple[Path, list[dict[str, Any]], wrap.Gathered]
    ) -> None:
        repo, _, gathered = recorded
        runner = self.runner(tmp_path, repo)
        runner.execute = lambda folder, item, seconds: ("done", 1, "Traceback: boom\n")  # type: ignore[method-assign]
        one = tm.make_tool(runner, gathered.candidates[0], 60, Tolerance(), IMAGE)
        assert one.dropped is not None and one.dropped["kind"] == "replay_error"
        assert "before any call said how it went" in one.dropped["details"][0]

    def test_a_container_that_wrote_too_much_is_a_failing_of_the_tool_and_says_so(
        self, tmp_path: Path, recorded: tuple[Path, list[dict[str, Any]], wrap.Gathered]
    ) -> None:
        repo, _, gathered = recorded
        runner = self.runner(tmp_path, repo)
        runner.execute = lambda folder, item, seconds: ("too_big", None, "")  # type: ignore[method-assign]
        one = tm.make_tool(runner, gathered.candidates[0], 60, Tolerance(), IMAGE)
        assert one.dropped is not None and "more than is allowed" in one.dropped["details"][0]


class TestWhatACallWrote:
    def written(self, folder: Path, name: str, value: Any) -> None:
        where = folder / tm.CALLS_FOLDER
        where.mkdir(exist_ok=True)
        (where / name).write_text(value if isinstance(value, str) else json.dumps(value))

    def good(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "ok": True,
            "error": None,
            "result": {"type": "int", "plain": True, "value": 1},
            "seconds": 0.1,
            "output": "",
        }

    def test_a_result_in_the_shape_the_runner_writes_is_read(self, tmp_path: Path) -> None:
        self.written(tmp_path, "0-0.json", self.good())
        assert tm.read_call(tmp_path, "0-0.json") == self.good()

    @pytest.mark.parametrize(
        "change",
        [
            {"schema": 2},
            {"ok": "yes"},
            {"ok": False, "error": None},
            {"ok": True, "result": None},
            {"result": {"type": 1, "plain": True}},
            {"seconds": "slow"},
        ],
    )
    def test_what_is_not_in_that_shape_is_not_read(self, tmp_path: Path, change: dict[str, Any]) -> None:
        self.written(tmp_path, "0-0.json", {**self.good(), **change})
        assert tm.read_call(tmp_path, "0-0.json") is None

    def test_what_is_not_json_or_not_there_or_too_big_or_a_link_is_not_read(self, tmp_path: Path) -> None:
        assert tm.read_call(tmp_path, "0-0.json") is None
        self.written(tmp_path, "1-0.json", "not json {")
        self.written(tmp_path, "2-0.json", json.dumps({**self.good(), "output": "x" * tm.MAX_CALL_BYTES}))
        self.written(tmp_path, "4-0.json", "[" * 100000)
        (tmp_path / tm.CALLS_FOLDER / "3-0.json").symlink_to(tmp_path / "elsewhere.json")
        (tmp_path / "elsewhere.json").write_text(json.dumps(self.good()))
        for name in ("1-0.json", "2-0.json", "3-0.json", "4-0.json"):
            assert tm.read_call(tmp_path, name) is None

    def test_a_folder_of_results_that_is_a_link_is_not_followed(self, tmp_path: Path) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "0-0.json").write_text(json.dumps(self.good()))
        folder = tmp_path / "run"
        folder.mkdir()
        (folder / tm.CALLS_FOLDER).symlink_to(elsewhere)
        assert tm.read_call(folder, "0-0.json") is None


@pytest.mark.usefixtures("processors")
class TestTheRunnerOfACall:
    """What runs inside the container, run here by hand."""

    def run(
        self, tmp_path: Path, cases: list[dict[str, Any]], wrapper: str, function: str = "mean", **spec: Any
    ) -> Path:
        repo = tree(tmp_path / "repo", FILES)
        work = tmp_path / "work"
        work.mkdir()
        for name, source in ((ref.RUNNER_AT, "tool_runner.py"), (tm.RECORD_AT, "tutorial_runner.py")):
            (work / name).write_text((Path(tm.__file__).parent / source).read_text())
        (work / tm.WRAPPER_AT).write_text(wrapper)
        call = {
            "schema": 1,
            "wrapper": tm.WRAPPER_AT,
            "function": function,
            "repeats": 1,
            "seconds": 20,
            "cases": cases,
        }
        (work / tm.CALL_FILE).write_text(json.dumps({**call, **spec}))
        subprocess.run(
            [sys.executable, str(work / ref.RUNNER_AT), "run", tm.CALL_FILE, "--repo", str(repo), "--work", str(work)],
            capture_output=True,
            timeout=60,
            check=False,
        )

        return work

    WRAPPER = (
        "import fixture.core as _repo\n\n\ndef mean(values, scale=1.0):\n"
        "    return _repo.mean(values=values, scale=scale)\n"
    )

    def test_a_call_that_works_is_written_with_what_it_gave_and_a_call_that_raised_with_what_it_said(
        self, tmp_path: Path
    ) -> None:
        cases = [
            {"id": 0, "args": {"values": [1, 2, 3, 4], "scale": 2}, "cwd": "examples"},
            {"id": 1, "args": {"values": [], "scale": 1}, "cwd": "examples"},
        ]
        work = self.run(tmp_path, cases, self.WRAPPER)
        good, bad = (tm.read_call(work, f"{index}-0.json") for index in range(2))
        assert good is not None and good["ok"] and good["result"] == {"type": "float", "plain": True, "value": 5.0}
        assert bad is not None and not bad["ok"] and bad["error"]["type"] == "ZeroDivisionError"
        assert all(frame for frame in bad["error"]["traceback"])

    def test_a_number_that_is_not_finite_goes_in_as_one_and_comes_out_as_one(self, tmp_path: Path) -> None:
        wrapper = "import fixture.core as _repo\n\n\ndef third(x):\n    return _repo.third(x=x)\n"
        work = self.run(tmp_path, [{"id": 0, "args": {"x": {"$float": "inf"}}, "cwd": "."}], wrapper, "third")
        result = tm.read_call(work, "0-0.json")
        assert result is not None and result["ok"] and result["result"]["value"] == {"$float": "inf"}

    def test_a_wrapper_that_cannot_be_loaded_is_an_error_of_each_call_and_not_a_failing_of_the_runner(
        self, tmp_path: Path
    ) -> None:
        work = self.run(tmp_path, [{"id": 0, "args": {}, "cwd": "."}], "def (:\n")
        result = tm.read_call(work, "0-0.json")
        assert result is not None and not result["ok"] and result["error"]["type"] == "SyntaxError"

    def test_a_folder_that_is_not_there_is_an_error_of_the_call(self, tmp_path: Path) -> None:
        cases = [{"id": 0, "args": {"values": [1], "scale": 1}, "cwd": "nowhere"}]
        work = self.run(tmp_path, cases, self.WRAPPER)
        result = tm.read_call(work, "0-0.json")
        assert result is not None and not result["ok"] and result["error"]["type"] == "FileNotFoundError"

    def test_a_runner_that_is_written_for_the_oldest_python_that_environments_are_built_for(self) -> None:
        source = (Path(tm.__file__).parent / "tool_runner.py").read_text()
        ast.parse(source, feature_version=(3, 7))
        assert ":=" not in source and "match " not in source


@pytest.mark.usefixtures("processors")
class TestCommand:
    def test_a_tool_is_called_by_the_runner_in_a_container_made_as_a_tutorials_is(self, tmp_path: Path) -> None:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        runner = tm.ToolRunner("image:tag", tm.ToolLimits(), scratch, label="abc-1")
        folder = tmp_path / "folder"
        folder.mkdir()
        command = runner.command(folder, ref.Item("tool", tm.CALL_FILE, "run"), 100, "virtual-lab-run-x")
        text = " ".join(command)
        assert "--network none" in text and "--read-only" in text and "--cap-drop ALL" in text
        assert f"{env.AGENT_LABEL}=abc-1" in text and "LUMI_TIME_LIMIT=130" in command
        assert command[-4:] == ("python", "/workspace/" + ref.RUNNER_AT, "run", tm.CALL_FILE)

    def test_the_limit_on_what_is_written_is_what_was_allowed(self, tmp_path: Path) -> None:
        runner = tm.ToolRunner("image:tag", tm.ToolLimits(gigabytes=7), tmp_path)
        assert runner.limits.gigabytes == 7 and runner.tools.gigabytes == 7


# What a container does is tested with a project that is built into an image, as environments are


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path]]:
    work = tmp_path_factory.mktemp("image")
    repo = tree(work / "project", {**FILES, "examples/container.py": CONTAINER})
    scratch = work / "scratch"
    scratch.mkdir()
    tag = f"virtual-lab-paperagent:tools-{time.time_ns()}"
    env.build_environment(repo, env.plan(repo), tag, env.Limits(10, 5), scratch)
    try:
        yield tag, repo
    finally:
        env.remove_image(tag)


CONTAINER = """
import fixture

fixture.mean([1, 2, 3, 4])
fixture.jitter(1.0)
fixture.reach()
fixture.secrets()
fixture.has_file("data.txt")
fixture.write_once("out.txt")
"""


@pytest.fixture(scope="module")
def outcome(built: tuple[str, Path], tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tag, repo = built
    scratch = tmp_path_factory.mktemp("scratch")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("LUMI_TEST_SECRET", "do-not-pass-on")
        runner = Runner(tag, Limits(repeats=1), scratch, label="tooltest")
        detail = runner.tutorial(tutorial("examples/container.py"), 120).detail
        gathered = wrap.gather([detail], repo, 20)
        tools = tm.ToolRunner(tag, tm.ToolLimits(), scratch, label="tooltest")
        outcomes: dict[str, tm.Made] = {}
        tm.make_tools(
            tools, gathered, tag, lambda *a: None, lambda candidate, one: outcomes.update({candidate.name: one})
        )

    return {"detail": detail, "gathered": gathered, "outcomes": outcomes, "scratch": scratch}


@needs_docker
class TestInContainers:
    """Tools that are made in Docker, from the calls that a tutorial made in Docker."""

    def test_the_tutorial_ran_in_a_container_and_made_the_calls_that_are_made_again(
        self, outcome: dict[str, Any]
    ) -> None:
        assert outcome["detail"]["status"] == "ok"
        assert sorted(candidate.name for candidate in outcome["gathered"].candidates) == sorted(outcome["outcomes"])
        assert len(outcome["outcomes"]) == 6

    def test_a_function_that_gives_the_same_each_time_is_a_tool_of_tier_a_when_called_in_a_container(
        self, outcome: dict[str, Any]
    ) -> None:
        for name in ("mean", "has_file", "write_once"):
            tool = tier_a(outcome["outcomes"], name)
            assert tool["tier"] == "A" and tool["evidence"]["cases"][0]["matched"] == 2

    def test_a_function_that_gives_something_else_each_time_is_dropped(self, outcome: dict[str, Any]) -> None:
        assert dropped(outcome["outcomes"], "jitter")["kind"] == "replay_differs"

    def test_the_call_is_made_with_no_network_and_none_of_this_machines_variables(
        self, outcome: dict[str, Any]
    ) -> None:
        reach = tier_a(outcome["outcomes"], "reach")["evidence"]["cases"][0]
        assert reach["expected"]["value"] is False and reach["matched"] == 2
        secrets = tier_a(outcome["outcomes"], "secrets")["evidence"]["cases"][0]
        assert secrets["expected"]["value"] == [] and secrets["matched"] == 2

    def test_no_container_and_no_folder_is_left(self, outcome: dict[str, Any]) -> None:
        assert run_ids("tooltest") == []
        assert list(outcome["scratch"].iterdir()) == []

    def sleeping(self, built: tuple[str, Path]) -> wrap.Candidate:
        _, repo = built
        detail = detail_of([call_of("pause", {"seconds": 60}, 60)])
        (candidate,) = wrap.gather([detail], repo, 5).candidates

        return candidate

    def test_a_call_that_runs_too_long_is_stopped_and_nothing_is_left_running(
        self, built: tuple[str, Path], tmp_path: Path
    ) -> None:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        runner = tm.ToolRunner(built[0], tm.ToolLimits(), scratch, label="tooltest")
        began = time.monotonic()
        one = tm.make_tool(runner, self.sleeping(built), 8, Tolerance(), built[0])
        assert one.dropped is not None and one.dropped["kind"] == "timed_out"
        assert time.monotonic() - began < 90
        assert run_ids("tooltest") == [] and list(scratch.iterdir()) == []

    def test_a_stop_ends_the_call_and_raises(self, built: tuple[str, Path], tmp_path: Path) -> None:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        runner = tm.ToolRunner(built[0], tm.ToolLimits(), scratch, label="tooltest")
        threading.Timer(5, runner.stop.set).start()
        with pytest.raises(StoppedError):
            tm.make_tool(runner, self.sleeping(built), 120, Tolerance(), built[0])
        assert run_ids("tooltest") == [] and list(scratch.iterdir()) == []

    def test_a_call_that_writes_more_than_is_allowed_is_stopped(
        self, built: tuple[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ref, "SIZE_SECONDS", 0.5)
        monkeypatch.setattr(ref, "folder_size", lambda folder: 5 * 1024**3)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        runner = tm.ToolRunner(built[0], tm.ToolLimits(), scratch, label="tooltest")
        one = tm.make_tool(runner, self.sleeping(built), 60, Tolerance(), built[0])
        assert one.dropped is not None and one.dropped["kind"] == "replay_error"
        assert "more than is allowed" in one.dropped["details"][0]
        assert run_ids("tooltest") == []
