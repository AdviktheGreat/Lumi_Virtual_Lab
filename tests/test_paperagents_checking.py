"""Tests of checking a tool by what its tutorial did not give it: that inputs the tutorial did not use are made of its
arguments and the tool is held to the code's own function for them, that the tests the code comes with are found, run
in a copy, and read back, that each kind ends as passed, failed, or not obtained and never as more than the evidence
shows, and that nothing the code wrote or said is believed.

The runs are made on this machine in most tests, by the same runners that run in a container, so that real checks of
real recorded calls are tested without an image.
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_paperagents_environment import needs_docker, needs_pypi
from test_paperagents_reference import run_ids, tutorial
from test_paperagents_stock import tree
from test_paperagents_toolmaking import FILES, IMAGE, record

from virtual_lab.paperagents import checking
from virtual_lab.paperagents import environment as env
from virtual_lab.paperagents import reference as ref
from virtual_lab.paperagents import toolmaking as tm
from virtual_lab.paperagents import wrappers as wrap
from virtual_lab.paperagents.comparing import Tolerance
from virtual_lab.paperagents.reference import Limits, Runner

TESTS = {
    "tests/__init__.py": "",
    "tests/test_mean.py": """
import fixture
from fixture.core import mean


def test_mean_of_a_list():
    assert fixture.mean([1, 2, 3]) == 2


def test_mean_with_a_scale():
    assert mean([1, 3], scale=2) == 4


def test_something_else_entirely():
    assert 1 + 1 == 2
""",
    "tests/test_third.py": """
import unittest

from fixture import core


class TestThird:
    def test_a_third_of_three(self):
        assert core.third(3) == 1

    def test_a_third_of_three_is_not_two(self):
        assert core.third(3) == 2


class OthersTest(unittest.TestCase):
    def test_a_third_of_six(self):
        self.assertEqual(core.third(6), 2)
""",
    "tests/test_unrelated.py": """
def test_mean():
    mean = lambda values: 0
    assert mean([1]) == 0
""",
    "tests/test_slow.py": """
import time

from fixture.core import secret


def test_secret_after_a_long_while():
    time.sleep(60)
    assert secret(1)
""",
    "tests/test_writes.py": """
from fixture.core import length


def test_length_writes_a_file():
    open("written-by-a-test.txt", "w").write("x")
    assert length([1]) == 1
""",
}


@pytest.fixture
def processors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env, "cpus_for", lambda *a, **k: "2")


class LocalChecker(checking.CheckRunner):
    """Runs the checks as the container does, with the same runners, on this machine."""

    def __init__(self, repo: Path, scratch: Path, limits: checking.CheckLimits | None = None, **options: Any) -> None:
        super().__init__("local", (limits or checking.CheckLimits()).for_runs(), scratch, label="checktest", **options)
        self.repo = repo
        self.seen: list[dict[str, str]] = []

    def execute(self, folder: Path, item: ref.Item, seconds: float) -> tuple[str, int | None, str]:
        self.seen.append({path.name: path.read_text() for path in folder.iterdir() if path.is_file()})
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


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The code, with tests, and two of its functions made into tools of tier A from a tutorial that called them."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(env, "cpus_for", lambda *a, **k: "2")
        root = tmp_path_factory.mktemp("checked")
        repo, details = record(root, {**FILES, **TESTS}, ["examples/demo.py"])
        assert details[0]["status"] == "ok", details
        gathered = wrap.gather(details, repo, 50)
        scratch = root / "scratch"
        scratch.mkdir()
        runner = LocalChecker(repo, scratch)
        tools = {}
        for name in ("mean", "third", "length", "secret"):
            candidate = next(one for one in gathered.candidates if one.name == name)
            one = tm.make_tool(runner, candidate, 60, Tolerance(), IMAGE)
            assert one.record is not None and one.source is not None, one.dropped
            tools[name] = {**one.record, "source": one.source}

    return {"repo": repo, "tools": tools, "root": root}


def runner_for(made: dict[str, Any], tmp_path: Path, **options: Any) -> LocalChecker:
    scratch = tmp_path / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)

    return LocalChecker(made["repo"], scratch, **options)


def ok(value: Any, kind: str = "float") -> dict[str, Any]:
    return {"ok": True, "error": None, "result": {"type": kind, "plain": True, "value": value}, "seconds": 0.1}


def stopped(kind: str = "ValueError", message: str = "bad") -> dict[str, Any]:
    return {"ok": False, "error": {"type": kind, "message": message, "traceback": []}, "result": None, "seconds": 0.1}


class TestChangingWhatTheTutorialPassed:
    def test_every_second_item_of_a_list_of_four_or_more_is_kept(self) -> None:
        assert checking.thin([1, 2, 3, 4]) == [1, 3]
        assert checking.thin([1, 2, 3, 4, 5]) == [1, 3, 5]
        assert checking.thin([1, 2, 3]) == [1, 2, 3]
        assert checking.thin({"a": [[1, 2, 3, 4], "x"], "b": 7}) == {"a": [[1, 3], "x"], "b": 7}

    def test_a_number_that_json_does_not_have_is_left_as_it_is(self) -> None:
        marker = {"$float": "nan"}
        assert checking.thin([marker, 1, 2, 3]) == [marker, 2]
        assert checking.nudge(marker) == marker and checking.nudge(float("inf")) == float("inf")

    def test_numbers_are_moved_a_little_and_nothing_else_is(self) -> None:
        assert checking.nudge(5) == 6 and checking.nudge(-5) == -6 and checking.nudge(0) == 0
        assert checking.nudge(2.0) == pytest.approx(2.2) and checking.nudge(0.5) == pytest.approx(0.45)
        assert checking.nudge(0.0) == 0.0 and checking.nudge(1.7e308) == 1.7e308
        assert checking.nudge(True) is True and checking.nudge("text") == "text" and checking.nudge(None) is None
        assert checking.nudge({"a": [1, 2.0, "x"]}) == {"a": [2, pytest.approx(2.2), "x"]}

    def test_only_the_ways_that_change_the_arguments_are_kept(self) -> None:
        assert checking.variants_of({"name": "x", "flag": True}) == []
        assert checking.variants_of({"values": [1, 2, 3]}) == [("nudged", {"values": [2, 3, 4]})]
        assert [name for name, _ in checking.variants_of({"values": [1, 2, 3, 4]})] == ["thinned", "nudged"]
        assert checking.variants_of({"values": [0, 0, 0, 0]}) == [("thinned", {"values": [0, 0]})]

    def test_the_first_calls_with_arguments_of_their_own_are_changed_and_no_more_than_is_allowed(self) -> None:
        def case(number: int, args: dict[str, Any]) -> dict[str, Any]:
            return {"call": number, "tutorial": "t1", "cwd": "examples", "args": args}

        cases = [case(1, {"n": 1}), case(2, {"n": 1}), case(3, {"n": 2}), case(4, {"n": 3}), case(5, {"n": 4})]
        changed = checking.held_out(cases)
        assert [(one["from"], one["args"]) for one in changed] == [(1, {"n": 2}), (3, {"n": 3}), (4, {"n": 4})]
        assert all(one["tutorial"] == "t1" and one["cwd"] == "examples" and one["change"] for one in changed)
        wide = [case(index, {"values": [index, 2, 3, 4]}) for index in range(10)]
        assert len(checking.held_out(wide)) == checking.MOST_VARIANTS
        assert checking.held_out([case(1, {"name": "x"})]) == []


class TestJudgingAChangedCall:
    tolerance = Tolerance()

    def judge(self, through_tool: list[Any], from_code: list[Any]) -> dict[str, Any]:
        return checking.judge_held_out(through_tool, from_code, self.tolerance)

    def test_the_same_each_time_from_both_agrees(self) -> None:
        found = self.judge([ok(2.0), ok(2.0)], [ok(2.0), ok(2.0)])
        assert found == {"verdict": "agree", "differences": [], "error": None}

    def test_a_difference_within_the_tolerance_is_not_one(self) -> None:
        assert self.judge([ok(2.0 + 1e-12)], [ok(2.0)])["verdict"] == "agree"

    def test_what_the_tool_gave_that_the_code_did_not_differs(self) -> None:
        found = self.judge([ok(3.0), ok(3.0)], [ok(2.0), ok(2.0)])
        assert found["verdict"] == "differs"
        assert found["differences"][0].startswith("What the tool gave is not what the code's own function gave")

    def test_a_tool_that_gave_something_else_on_one_of_its_calls_differs(self) -> None:
        assert self.judge([ok(2.0), ok(2.5)], [ok(2.0), ok(2.0)])["verdict"] == "differs"

    def test_a_code_that_gave_something_else_when_called_again_is_not_something_to_hold_a_tool_to(self) -> None:
        found = self.judge([ok(2.0), ok(2.0)], [ok(2.0), ok(2.5)])
        assert found["verdict"] == "unstable" and "when it was called again" in found["differences"][0]

    def test_the_same_error_from_both_shows_nothing(self) -> None:
        found = self.judge([stopped()], [stopped(message="another words")])
        assert found["verdict"] == "same_error" and found["error"] == {"type": "ValueError", "message": "another words"}

    def test_an_error_from_one_and_not_the_other_differs(self) -> None:
        assert self.judge([stopped()], [ok(1.0)])["verdict"] == "differs"
        assert self.judge([ok(1.0)], [stopped()])["verdict"] == "differs"
        assert self.judge([stopped("KeyError")], [stopped("ValueError")])["verdict"] == "differs"

    def test_a_call_that_was_not_made_in_the_time_is_not_a_pass(self) -> None:
        assert self.judge([None, None], [ok(1.0), ok(1.0)])["verdict"] == "not_run"
        assert self.judge([ok(1.0), None], [ok(1.0), ok(1.0)])["verdict"] == "not_run"
        assert self.judge([ok(1.0), ok(1.0)], [ok(1.0), None])["verdict"] == "not_run"


class TestWhatChangedCallsCometo:
    def of(self, *verdicts: str) -> checking.Outcome:
        cases = [{"verdict": verdict, "differences": [f"{verdict} here"]} for verdict in verdicts]

        return checking.held_out_outcome(cases, 2, Tolerance())

    def test_calls_that_agree_pass(self) -> None:
        found = self.of("agree", "agree")
        assert found.status == checking.PASSED and found.summary.startswith("2 of 2 calls")
        assert found.details["counts"]["agree"] == 2 and len(found.details["cases"]) == 2

    def test_one_call_that_differs_fails_whatever_else_agreed(self) -> None:
        found = self.of("agree", "agree", "differs")
        assert found.status == checking.FAILED and found.summary.startswith("1 of 3 changed calls")
        assert "differs here" in found.summary

    def test_calls_that_show_nothing_are_not_for_the_tool_and_are_said(self) -> None:
        found = self.of("agree", "same_error", "unstable", "not_run")
        assert found.status == checking.PASSED and found.summary.startswith("1 of 4 call with")
        assert (
            "stopped with the same error from both" in found.summary
            and "gave something else each time" in found.summary
        )

    def test_when_none_agree_nothing_is_obtained_and_it_is_not_a_failure(self) -> None:
        for verdicts in (("same_error",), ("unstable", "same_error"), ("not_run",)):
            assert self.of(*verdicts).status == checking.NOT_OBTAINED
        assert self.of("same_error").summary.startswith("No changed call showed what the code gives.")


class TestFindingTheTestsOfAFunction:
    def test_the_tests_that_call_it_are_found_by_the_names_pytest_knows_them_by(self, made: dict[str, Any]) -> None:
        ids = checking.ids_of_tests(made["repo"], "fixture.core", "mean")
        assert sorted(ids) == [
            "tests/test_mean.py::test_mean_of_a_list",
            "tests/test_mean.py::test_mean_with_a_scale",
        ]

    def test_the_tests_of_a_class_are_found_with_the_class_and_those_of_a_test_case_too(
        self, made: dict[str, Any]
    ) -> None:
        ids = checking.ids_of_tests(made["repo"], "fixture.core", "third")
        assert sorted(ids) == [
            "tests/test_third.py::OthersTest::test_a_third_of_six",
            "tests/test_third.py::TestThird::test_a_third_of_three",
            "tests/test_third.py::TestThird::test_a_third_of_three_is_not_two",
        ]

    def test_a_test_in_a_file_that_does_not_import_the_project_is_not_one_of_its_tests(
        self, made: dict[str, Any]
    ) -> None:
        assert not any("test_unrelated" in item for item in checking.ids_of_tests(made["repo"], "fixture.core", "mean"))

    def test_a_test_of_another_librarys_function_of_the_same_name_is_not_taken_for_it(self, tmp_path: Path) -> None:
        repo = tree(
            tmp_path / "repo",
            {
                "pkg/__init__.py": "",
                "pkg/core.py": "def mean(values):\n    return 1\n",
                "tests/test_a.py": (
                    "import numpy as np\nfrom pkg import other\n\n\n"
                    "def test_unrelated():\n    assert np.mean([1, 2]) == 1.5\n\n\n"
                    "def test_a_parameter(runner):\n    assert runner.mean([1]) == 1\n"
                ),
                "tests/test_b.py": "import pkg\n\n\ndef test_the_project_one():\n    assert pkg.core.mean([1]) == 1\n",
            },
        )
        assert checking.ids_of_tests(repo, "pkg.core", "mean") == ["tests/test_b.py::test_the_project_one"]

    def test_only_what_is_imported_from_the_defining_module_or_a_package_above_it_is_the_function(
        self, tmp_path: Path
    ) -> None:
        repo = tree(
            tmp_path / "repo",
            {
                "pkg/__init__.py": "",
                "tests/test_ways.py": """
import pkg
import pkg.core as c
import pkg.other
from pkg import core, run as again
from pkg.core import run as direct
from pkg.other import run as another
from other import run as foreign
from .helpers import run as helper
from .core import run as near


def test_by_the_package():
    pkg.run()


def test_by_an_alias_of_the_module():
    c.run()


def test_by_a_module_of_the_package():
    core.run()


def test_by_a_name_of_the_package_under_another():
    again()


def test_by_the_module():
    direct()


def test_by_another_module_of_the_project():
    another()
    pkg.other.run()


def test_by_another_library():
    foreign()


def test_by_a_helper_of_the_tests():
    helper()


def test_by_a_relative_import_of_the_module():
    near()


def test_by_a_name_that_was_not_imported():
    run()
""",
            },
        )
        assert sorted(checking.ids_of_tests(repo, "pkg.core", "run")) == [
            "tests/test_ways.py::test_by_a_module_of_the_package",
            "tests/test_ways.py::test_by_a_name_of_the_package_under_another",
            "tests/test_ways.py::test_by_a_relative_import_of_the_module",
            "tests/test_ways.py::test_by_an_alias_of_the_module",
            "tests/test_ways.py::test_by_the_module",
            "tests/test_ways.py::test_by_the_package",
        ]

    def test_nothing_is_found_for_a_function_no_test_calls(self, made: dict[str, Any]) -> None:
        assert checking.ids_of_tests(made["repo"], "fixture.core", "jitter") == []

    def test_files_that_cannot_be_read_as_code_and_files_that_are_not_tests_are_passed_over(
        self, tmp_path: Path
    ) -> None:
        repo = tree(
            tmp_path / "repo",
            {
                "pkg/__init__.py": "",
                "pkg/core.py": "def run():\n    return 1\n",
                "tests/test_broken.py": "import pkg\ndef test_run(:\n",
                "tests/test_binary.py": "\x00import pkg\n",
                "tests/helpers.py": "import pkg\ndef test_run():\n    pkg.run()\n",
                "tests/test_good.py": "import pkg\n\n\ndef test_run():\n    assert pkg.run() == 1\n",
                "tests/relative_test.py": "from . import x\nfrom pkg import run\n\ndef test_run_again():\n    run()",
            },
        )
        assert sorted(checking.ids_of_tests(repo, "pkg.core", "run")) == [
            "tests/relative_test.py::test_run_again",
            "tests/test_good.py::test_run",
        ]

    def test_no_more_are_run_than_are_allowed(self, tmp_path: Path) -> None:
        many = "\n\n".join(f"def test_run_{number}():\n    run()" for number in range(40))
        repo = tree(
            tmp_path / "repo", {"pkg/__init__.py": "", "tests/test_many.py": f"from pkg import run\n\n{many}\n"}
        )
        assert len(checking.ids_of_tests(repo, "pkg.core", "run")) == checking.MOST_TESTS

    def test_a_file_that_is_too_big_is_not_read(self, tmp_path: Path) -> None:
        big = "import pkg\n\n\ndef test_run():\n    pkg.run()\n" + "# x\n" * (checking.MAX_TEST_FILE_BYTES // 4)
        repo = tree(tmp_path / "repo", {"pkg/__init__.py": "", "tests/test_big.py": big})
        assert checking.ids_of_tests(repo, "pkg.core", "run") == []


class TestWhatTestsComeTo:
    ids = ["tests/test_a.py::test_a"]

    def result(self, **changes: Any) -> dict[str, Any]:
        base = {
            "schema": 1,
            "ran": True,
            "reason": None,
            "tests": 2,
            "passed": 2,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "failures": [],
            "seconds": 0.5,
            "output": "..",
        }

        return {**base, **changes}

    def test_tests_that_passed_pass(self) -> None:
        found = checking.outcome_of_tests(self.ids, self.result())
        assert found.status == checking.PASSED and found.summary.startswith("2 tests of the code")
        assert found.details["ids"] == self.ids and found.details["passed"] == 2

    def test_one_that_failed_fails_whatever_else_passed(self) -> None:
        failure = {"name": "tests.test_a::test_a", "message": "assert 1 == 2"}
        found = checking.outcome_of_tests(self.ids, self.result(passed=1, failed=1, failures=[failure], output="F."))
        assert (
            found.status == checking.FAILED and "1 of the 2 tests" in found.summary and "assert 1 == 2" in found.summary
        )

    def test_tests_that_stopped_with_an_error_before_one_passed_were_not_run_and_are_not_a_failure_of_the_tool(
        self,
    ) -> None:
        failure = {"name": "tests.test_a", "message": "ModuleNotFoundError: No module named 'torch'"}
        found = checking.outcome_of_tests(self.ids, self.result(tests=1, passed=0, errors=1, failures=[failure]))
        assert found.status == checking.NOT_OBTAINED and "torch" in found.summary

    def test_tests_that_were_all_skipped_show_nothing(self) -> None:
        found = checking.outcome_of_tests(self.ids, self.result(tests=2, passed=0, skipped=2))
        assert found.status == checking.NOT_OBTAINED and "skipped" in found.summary

    def test_tests_that_were_not_run_say_why(self) -> None:
        found = checking.outcome_of_tests(
            self.ids, self.result(ran=False, reason="pytest is not in the environment, and nothing can be installed")
        )
        assert found.status == checking.NOT_OBTAINED and "pytest is not in the environment" in found.summary

    def test_what_the_runner_wrote_is_not_believed_unless_it_is_in_the_shape_it_writes(self) -> None:
        assert checking.valid_test_result(self.result())
        for bad in (
            None,
            [],
            self.result(schema=2),
            self.result(passed=-1),
            self.result(passed=True),
            self.result(ran="yes"),
            self.result(failures=[{"name": "a"}]),
            self.result(failures=[{"name": "a", "message": "b"}] * 11),
            {key: value for key, value in self.result().items() if key != "output"},
        ):
            assert not checking.valid_test_result(bad)


class TestRunningTheTests:
    def test_tests_that_pass_pass(self, made: dict[str, Any], tmp_path: Path, processors: None) -> None:
        found = checking.check_repo_tests(runner_for(made, tmp_path), made["tools"]["mean"], made["repo"], 120)
        assert found.status == checking.PASSED, found
        assert found.details["tests"] == 2 and found.details["passed"] == 2
        assert sorted(found.details["ids"]) == [
            "tests/test_mean.py::test_mean_of_a_list",
            "tests/test_mean.py::test_mean_with_a_scale",
        ]

    def test_a_test_that_fails_fails_the_check_and_says_which_and_why(
        self, made: dict[str, Any], tmp_path: Path, processors: None
    ) -> None:
        found = checking.check_repo_tests(runner_for(made, tmp_path), made["tools"]["third"], made["repo"], 120)
        assert found.status == checking.FAILED, found
        assert found.details["tests"] == 3 and found.details["passed"] == 2 and found.details["failed"] == 1
        (failure,) = found.details["failures"]
        assert "test_a_third_of_three_is_not_two" in failure["name"] and "assert" in failure["message"]

    def test_a_function_that_no_test_calls_has_none_to_run_and_nothing_is_run(
        self, made: dict[str, Any], tmp_path: Path, processors: None
    ) -> None:
        runner = runner_for(made, tmp_path)
        found = checking.check_repo_tests(runner, made["tools"]["length"], made["repo"], 120)
        assert found.status == checking.PASSED  # the test of length that writes a file calls it
        none = {**made["tools"]["length"], "repo": {**made["tools"]["length"]["repo"], "function": "pause"}}
        runner = runner_for(made, tmp_path / "other")
        found = checking.check_repo_tests(runner, none, made["repo"], 120)
        assert found.status == checking.NOT_OBTAINED and "No test in the code calls pause" in found.summary
        assert runner.seen == []

    def test_what_a_test_writes_is_written_to_a_copy_and_the_code_is_left_as_it_was(
        self, made: dict[str, Any], tmp_path: Path, processors: None
    ) -> None:
        found = checking.check_repo_tests(runner_for(made, tmp_path), made["tools"]["length"], made["repo"], 120)
        assert found.status == checking.PASSED, found
        assert not list(made["repo"].rglob("written-by-a-test.txt"))

    def test_tests_that_do_not_end_in_the_time_are_stopped_and_are_not_a_pass_or_a_failure(
        self, made: dict[str, Any], tmp_path: Path, processors: None
    ) -> None:
        runner = runner_for(made, tmp_path)
        began = time.monotonic()
        found = checking.check_repo_tests(runner, made["tools"]["secret"], made["repo"], 4)
        assert found.status == checking.NOT_OBTAINED, found
        assert time.monotonic() - began < 30
        assert "report" in found.summary or "did not end" in found.summary

    def test_what_the_runner_is_given_is_the_tests_by_id_and_the_time_and_nothing_else(
        self, made: dict[str, Any], tmp_path: Path, processors: None
    ) -> None:
        runner = runner_for(made, tmp_path)
        checking.check_repo_tests(runner, made["tools"]["mean"], made["repo"], 100)
        (seen,) = runner.seen
        assert sorted(seen) == [".lumi-runner.py", ".lumi-tests.json", "lumi_record.py"]
        spec = json.loads(seen[".lumi-tests.json"])
        assert spec["schema"] == 1 and spec["seconds"] == 90 and len(spec["tests"]) == 2
        assert list((tmp_path / "scratch").iterdir()) == []

    def test_a_stopped_job_stops_the_tests(self, made: dict[str, Any], tmp_path: Path, processors: None) -> None:
        import threading

        from virtual_lab.environment import StoppedError

        stop = threading.Event()
        stop.set()
        runner = runner_for(made, tmp_path, stop=stop)
        with pytest.raises(StoppedError):
            checking.check_repo_tests(runner, made["tools"]["mean"], made["repo"], 100)
        assert list((tmp_path / "scratch").iterdir()) == []

    def test_a_result_that_a_run_wrote_that_is_not_one_is_not_believed(self, tmp_path: Path) -> None:
        folder = tmp_path / "run"
        (folder / ".lumi-result").mkdir(parents=True)
        path = folder / ".lumi-result" / "tests.json"
        assert checking.read_test_result(folder) is None
        path.write_text("not json")
        assert checking.read_test_result(folder) is None
        path.write_text(json.dumps({"schema": 1, "ran": True, "tests": 5, "passed": 5}))
        assert checking.read_test_result(folder) is None
        path.write_text("x" * (tm.MAX_CALL_BYTES + 1))
        assert checking.read_test_result(folder) is None
        path.unlink()
        path.symlink_to(tmp_path)
        assert checking.read_test_result(folder) is None


class TestCallingWhatTheTutorialDidNotPass:
    def test_a_tool_that_does_nothing_of_its_own_gives_what_the_code_gives_for_other_arguments(
        self, made: dict[str, Any], tmp_path: Path, processors: None
    ) -> None:
        runner = runner_for(made, tmp_path)
        found = checking.check_held_out(runner, made["tools"]["mean"], made["repo"], 120, Tolerance())
        assert found.status == checking.PASSED, found
        counts = found.details["counts"]
        assert counts["agree"] >= 2 and counts["differs"] == 0 and found.details["repeats"] == 2
        assert {one["change"] for one in found.details["cases"]} >= {"nudged"}
        assert all("args" in one and isinstance(one["args"], str) for one in found.details["cases"])
        # Both the tool's wrapper and the caller of the code's own function were called, each in a run of its own
        assert len(runner.seen) == 2
        assert [name for name in runner.seen[0] if name.startswith("lumi_")] == ["lumi_record.py", "lumi_wrapper.py"]
        assert "lumi_direct" in runner.seen[1]["lumi_wrapper.py"] and "importlib" in runner.seen[1]["lumi_wrapper.py"]
        assert list((tmp_path / "scratch").iterdir()) == []

    def test_a_tool_that_gives_something_the_code_does_not_fails(
        self, made: dict[str, Any], tmp_path: Path, processors: None
    ) -> None:
        tool = made["tools"]["mean"]
        crooked = {**tool, "source": tool["source"].replace("return _repo.mean(", "return 1 + _repo.mean(")}
        assert crooked["source"] != tool["source"]
        found = checking.check_held_out(runner_for(made, tmp_path), crooked, made["repo"], 120, Tolerance())
        assert found.status == checking.FAILED, found
        assert found.details["counts"]["differs"] >= 1
        assert "What the tool gave is not what the code's own function gave" in found.summary

    def test_a_tutorial_that_passed_nothing_that_can_be_changed_leaves_nothing_to_check(
        self, made: dict[str, Any], tmp_path: Path, processors: None
    ) -> None:
        tool = made["tools"]["mean"]
        plain = {
            **tool,
            "evidence": {
                **tool["evidence"],
                "cases": [{**case, "args": {"name": "x"}} for case in tool["evidence"]["cases"]],
            },
        }
        runner = runner_for(made, tmp_path)
        found = checking.check_held_out(runner, plain, made["repo"], 120, Tolerance())
        assert (
            found.status == checking.NOT_OBTAINED and "Nothing that the tutorial passed can be changed" in found.summary
        )
        assert runner.seen == []

    def test_a_function_whose_parameters_cannot_be_read_is_not_called_directly(
        self, made: dict[str, Any], tmp_path: Path, processors: None
    ) -> None:
        tool = made["tools"]["mean"]
        elsewhere = {**tool, "repo": {**tool["repo"], "function": "gone"}}
        runner = runner_for(made, tmp_path)
        found = checking.check_held_out(runner, elsewhere, made["repo"], 120, Tolerance())
        assert found.status == checking.NOT_OBTAINED and "cannot be read" in found.summary
        assert runner.seen == []

    def test_calls_that_stop_with_the_same_error_from_both_show_nothing(
        self, made: dict[str, Any], tmp_path: Path, processors: None
    ) -> None:
        tool = made["tools"]["length"]
        cases = [{**case, "args": {"items": 5}} for case in tool["evidence"]["cases"]]
        odd = {**tool, "evidence": {**tool["evidence"], "cases": cases}}
        found = checking.check_held_out(runner_for(made, tmp_path), odd, made["repo"], 120, Tolerance())
        assert found.status == checking.NOT_OBTAINED, found
        assert found.details["counts"]["same_error"] == len(found.details["cases"])
        assert all(one["error"]["type"] == "TypeError" for one in found.details["cases"])


class TestLimits:
    def test_what_is_left_out_is_the_default(self) -> None:
        assert checking.check_limits(None, None, None, None) == checking.CheckLimits()
        assert checking.CheckLimits().to_dict() == {"minutes": 5, "total_minutes": 30, "repeats": 2, "gigabytes": 2}

    def test_what_is_allowed_is_whole_numbers_within_the_most(self) -> None:
        assert checking.check_limits(30, 180, 3, 20) == checking.CheckLimits(30, 180, 3, 20)
        for args in (
            (0, None, None, None),
            (31, None, None, None),
            (None, 181, None, None),
            (None, None, 4, None),
            (None, None, None, 21),
            (True, None, None, None),
            (1.5, None, None, None),
            ("5", None, None, None),
        ):
            with pytest.raises(ValueError, match="whole number from"):
                checking.check_limits(*args)

    def test_a_runner_is_given_what_it_makes_calls_with(self) -> None:
        limits = checking.check_limits(4, 20, 3, 1).for_runs()
        assert (limits.minutes, limits.total_minutes, limits.repeats, limits.gigabytes) == (4, 20, 3, 1)


class TestWhatEachKindShows:
    def test_each_kind_says_what_it_shows_and_what_it_does_not(self) -> None:
        assert set(checking.KIND_INFO) == set(checking.KINDS)
        for info in checking.KIND_INFO.values():
            assert info["title"] and "not show" in info["what"]

    def test_tier_b_is_not_said_to_show_that_a_tool_is_right(self) -> None:
        assert "does not show that what the tool gives is right" in checking.MEANING


# What a container does is tested with a project that is built into an image, as environments are

CONTAINER = """
import fixture

fixture.mean([1, 2, 3, 4])
fixture.mean([2.5, 3.5], scale=2)
fixture.third(1)
fixture.reach()
"""
NETWORK_TESTS = {
    "tests/test_reach.py": """
from fixture.core import reach


def test_reach_has_no_network():
    assert reach() is False
"""
}


def image_of(work: Path, files: dict[str, str]) -> tuple[str, Path]:
    repo = tree(work / "project", {**FILES, **TESTS, **NETWORK_TESTS, **files, "examples/container.py": CONTAINER})
    scratch = work / "scratch"
    scratch.mkdir()
    tag = f"virtual-lab-paperagent:checks-{time.time_ns()}"
    env.build_environment(repo, env.plan(repo), tag, env.Limits(10, 5), scratch)

    return tag, repo


def tools_in(tag: str, repo: Path, scratch: Path) -> dict[str, dict[str, Any]]:
    """Tools of tier A, made of what a tutorial did in the image."""
    detail = (
        Runner(tag, Limits(repeats=1), scratch, label="checktest")
        .tutorial(tutorial("examples/container.py"), 120)
        .detail
    )
    tools = {}
    runner = tm.ToolRunner(tag, tm.ToolLimits(), scratch, label="checktest")
    outcomes: dict[str, tm.Made] = {}
    tm.make_tools(
        runner,
        wrap.gather([detail], repo, 20),
        tag,
        lambda *a: None,
        lambda one, made: outcomes.update({one.name: made}),
    )
    for name, made in outcomes.items():
        if made.record is not None and made.source is not None:
            tools[name] = {**made.record, "source": made.source}

    return tools


@pytest.fixture(scope="module")
def offline(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    """An image that has pytest in it only if the project asks for it, which this does not."""
    work = tmp_path_factory.mktemp("image")
    tag, repo = image_of(work, {})
    scratch = work / "calls"
    scratch.mkdir()
    try:
        yield {"tag": tag, "repo": repo, "tools": tools_in(tag, repo, scratch), "scratch": scratch}
    finally:
        env.remove_image(tag)


@pytest.fixture(scope="module")
def with_pytest(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    work = tmp_path_factory.mktemp("image")
    tag, repo = image_of(work, {"requirements.txt": "pytest\n"})
    scratch = work / "calls"
    scratch.mkdir()
    try:
        yield {"tag": tag, "repo": repo, "tools": tools_in(tag, repo, scratch), "scratch": scratch}
    finally:
        env.remove_image(tag)


def checker_in(image: dict[str, Any]) -> checking.CheckRunner:
    return checking.CheckRunner(image["tag"], checking.CheckLimits().for_runs(), image["scratch"], label="checktest")


@needs_docker
class TestInAContainer:
    """Real checks, in containers that have no network, of tools that were made in containers."""

    def test_a_tool_is_held_to_the_code_for_other_arguments_in_a_container(self, offline: dict[str, Any]) -> None:
        assert {"mean", "third", "reach"} <= set(offline["tools"])
        found = checking.check_held_out(
            checker_in(offline), offline["tools"]["mean"], offline["repo"], 120, Tolerance()
        )
        assert found.status == checking.PASSED, found
        assert found.details["counts"]["agree"] >= 2 and found.details["counts"]["differs"] == 0

    def test_an_environment_with_no_pytest_in_it_gets_no_test_run_and_says_so(self, offline: dict[str, Any]) -> None:
        found = checking.check_repo_tests(checker_in(offline), offline["tools"]["mean"], offline["repo"], 120)
        assert found.status == checking.NOT_OBTAINED, found
        assert "pytest is not in the environment" in found.summary

    def test_no_container_and_no_folder_is_left(self, offline: dict[str, Any]) -> None:
        checking.check_repo_tests(checker_in(offline), offline["tools"]["mean"], offline["repo"], 120)
        assert run_ids("checktest") == [] and list(offline["scratch"].iterdir()) == []

    @needs_pypi
    def test_the_tests_of_the_code_are_run_by_the_pytest_of_the_environment_with_no_network(
        self, with_pytest: dict[str, Any]
    ) -> None:
        runner = checker_in(with_pytest)
        found = checking.check_repo_tests(runner, with_pytest["tools"]["reach"], with_pytest["repo"], 180)
        assert found.status == checking.PASSED, found
        assert found.details["passed"] == 1 and found.details["output"]
        mean = checking.check_repo_tests(runner, with_pytest["tools"]["mean"], with_pytest["repo"], 180)
        assert mean.status == checking.PASSED and mean.details["tests"] == 2, mean

    @needs_pypi
    def test_a_test_of_the_code_that_fails_in_the_environment_fails_the_check(
        self, with_pytest: dict[str, Any]
    ) -> None:
        found = checking.check_repo_tests(
            checker_in(with_pytest), with_pytest["tools"]["third"], with_pytest["repo"], 180
        )
        assert found.status == checking.FAILED, found
        assert (
            found.details["failed"] == 1 and "test_a_third_of_three_is_not_two" in found.details["failures"][0]["name"]
        )
        assert run_ids("checktest") == [] and list(with_pytest["scratch"].iterdir()) == []
