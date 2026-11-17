"""Checking a tool by what its tutorial did not give it.

A tool of tier A gave again what its tutorial got, for the arguments the tutorial passed. Of that, the tutorial is both
the source and the test, so it shows little. Tier B asks for more: kinds of evidence that the making of the tool did not
produce, of which two must pass and none fail. Here are the kinds that need only the tool, the code, and the
environment:

- inputs that the tutorial did not use. The arguments of a call that the tutorial made are changed (numbers nudged,
  lists thinned), and the tool and the code's own function are called with them, each in a process of its own, as many
  times as asked. They must give the same, and the same each time. That is what the tool adds nothing to, and it is
  held to inputs that no tutorial chose.
- the tests that the code comes with. Those that call the function are run, in the environment, with no network, by
  pytest if the environment has it. They must pass.

Each ends as passed, failed, or not obtained: a check that could not be made, such as one for a function that no test
calls, is not a failure, and is not evidence either. What each shows is said, and none shows that what the tool gives
is right.
"""

import ast
import json
import math
import shutil
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerUnavailableError
from virtual_lab.paperagents import reference as referencing
from virtual_lab.paperagents import toolmaking as making
from virtual_lab.paperagents import wrappers
from virtual_lab.paperagents.comparing import Tolerance, differences, shown
from virtual_lab.paperagents.stock import matches, walk

SCHEMA = 1
HELDOUT = "heldout"
REPO_TESTS = "repo_tests"
KINDS = (HELDOUT, REPO_TESTS)
PASSED = "passed"
FAILED = "failed"
NOT_OBTAINED = "not_obtained"
STATUSES = (PASSED, FAILED, NOT_OBTAINED)
# How many kinds must pass for tier B, and the tier that a tool is of with fewer
KINDS_FOR_B = 2
TIER_B = "B"

CHECK_RUNNER_FILE = "check_runner.py"
TESTS_FILE = ".lumi-tests.json"
RESULT_AT = f"{referencing.RESULT_FOLDER}/tests.json"
DIRECT_NAME = "lumi_direct"

# What a person may allow, by default and at most: minutes for each check of one tool, minutes for all of them,
# how many times each call is made, and gigabytes that one run may write
DEFAULT_MINUTES = 5
MAX_MINUTES = 30
DEFAULT_TOTAL_MINUTES = 30
MAX_TOTAL_MINUTES = 180
DEFAULT_REPEATS = 2
MAX_REPEATS = 3
DEFAULT_GIGABYTES = 2
MAX_GIGABYTES = 20

# How many of the calls that the tutorials made are changed, and how many calls that comes to at most, for a tool
MOST_CASES = 3
MOST_VARIANTS = 6
# How many tests are run for a function at most, how big a file of tests is read, and how many are looked in
MOST_TESTS = 25
MAX_TEST_FILE_BYTES = 500_000
MAX_TEST_FILES = 400
# How much of a failure, and of what a test printed, is kept
MAX_FAILURES = 10
MAX_TEXT_CHARS = 300
MAX_OUTPUT_CHARS = 4000
NUMBER = (int, float)

KIND_INFO: dict[str, dict[str, str]] = {
    HELDOUT: {
        "title": "Inputs the tutorial did not use",
        "what": (
            "The tool and the code's own function were called with the arguments of a tutorial's call changed (numbers "
            "nudged, lists thinned), each in a process of its own, and gave the same, each time. This shows that the "
            "tool adds nothing of its own and does not hold only for what the tutorial passed. It does not show that "
            "what is given is right."
        ),
    },
    REPO_TESTS: {
        "title": "The code's own tests",
        "what": (
            "The tests in the code that call the function were run in the environment, with no network, and passed. "
            "They are the authors' own, and are what they chose to check. They do not show that what the tool gives is "
            "right for other arguments."
        ),
    },
}

MEANING = (
    "A tool of tier B is of tier A and has also passed two kinds of checks that its tutorial did not give it, and "
    "failed none. That lowers the chance that it is right only for its tutorial. It does not make that chance nothing, "
    "and it does not show that what the tool gives is right."
)

TESTS_RESULT = {
    "schema": int,
    "ran": bool,
    "reason": (str, None),
    "tests": int,
    "passed": int,
    "failed": int,
    "errors": int,
    "skipped": int,
    "failures": [{"name": str, "message": str}],
    "seconds": NUMBER,
    "output": str,
}


@dataclass(frozen=True)
class CheckLimits:
    """What the checking of tools is allowed.

    :param minutes: How long each check of one tool may take.
    :param total_minutes: How long all of the checks of all of the tools may take together.
    :param repeats: How many times each call is made, to see that it gives the same each time.
    :param gigabytes: How much one run may write, counting its copies of the project.
    """

    minutes: int = DEFAULT_MINUTES
    total_minutes: int = DEFAULT_TOTAL_MINUTES
    repeats: int = DEFAULT_REPEATS
    gigabytes: int = DEFAULT_GIGABYTES

    def to_dict(self) -> dict[str, int]:
        return {
            "minutes": self.minutes,
            "total_minutes": self.total_minutes,
            "repeats": self.repeats,
            "gigabytes": self.gigabytes,
        }

    def for_runs(self) -> making.ToolLimits:
        """What a runner is given, which is made for calling tools."""
        return making.ToolLimits(
            minutes=self.minutes,
            total_minutes=self.total_minutes,
            repeats=self.repeats,
            gigabytes=self.gigabytes,
        )


def check_limits(minutes: Any, total_minutes: Any, repeats: Any, gigabytes: Any) -> CheckLimits:
    """What a person allowed, with the defaults for what was left out.

    :raises ValueError: If it is not whole numbers within what is allowed.
    """
    values = []
    for name, value, default, least, most in (
        ("minutes one check of a tool may take", minutes, DEFAULT_MINUTES, 1, MAX_MINUTES),
        ("minutes all of the checks may take", total_minutes, DEFAULT_TOTAL_MINUTES, 1, MAX_TOTAL_MINUTES),
        ("times each call is made", repeats, DEFAULT_REPEATS, 1, MAX_REPEATS),
        ("gigabytes one run may write", gigabytes, DEFAULT_GIGABYTES, 1, MAX_GIGABYTES),
    ):
        if value is None:
            values.append(default)
        elif isinstance(value, bool) or not isinstance(value, int) or not least <= value <= most:
            raise ValueError(f"The most {name} is a whole number from {least} to {most}")
        else:
            values.append(value)

    return CheckLimits(*values)


@dataclass
class Outcome:
    """What came of one kind of check of one tool.

    :param status: passed, failed, or not_obtained.
    :param summary: What it came to, in a sentence.
    :param details: What it came to, for a page that opens it: for inputs, each call that was changed and how it went;
        for tests, what was run and what did not pass.
    """

    status: str
    summary: str
    details: dict[str, Any]


def outcome(status: str, summary: str, **details: Any) -> Outcome:
    return Outcome(status, summary, details)


# Inputs the tutorial did not use


def is_marker(value: Any) -> bool:
    """Whether a value of JSON stands for a number that JSON does not have (not finite), which is left as it is."""
    return isinstance(value, dict) and len(value) == 1 and "$float" in value


def thin(value: Any) -> Any:
    """What is left of a value when every second item of each list of four or more is kept."""
    if isinstance(value, list):
        return [thin(item) for item in (value[::2] if len(value) >= 4 else value)]
    if isinstance(value, dict) and not is_marker(value):
        return {key: thin(item) for key, item in value.items()}

    return value


def nudge(value: Any) -> Any:
    """A value with each number moved a little: a whole number by one away from nothing, a fraction by a tenth less, and
    any other number by a tenth more. Text, truth values, and what is not finite are left."""
    if isinstance(value, bool) or is_marker(value):
        return value
    if isinstance(value, int):
        return value + 1 if value > 0 else value - 1 if value < 0 else value
    if isinstance(value, float):
        if value == 0 or not math.isfinite(value):
            return value
        moved = value * 0.9 if abs(value) < 1 else value * 1.1

        return moved if math.isfinite(moved) else value
    if isinstance(value, list):
        return [nudge(item) for item in value]
    if isinstance(value, dict):
        return {key: nudge(item) for key, item in value.items()}

    return value


def variants_of(args: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The ways that the arguments of a call are changed, each as a name and the changed arguments, leaving out one
    that is what it was."""
    found: list[tuple[str, dict[str, Any]]] = []
    for name, change in (("thinned", thin), ("nudged", nudge)):
        changed = {key: change(value) for key, value in args.items()}
        if changed != args and all(changed != other for _, other in found):
            found.append((name, changed))

    return found


def held_out(
    cases: Sequence[dict[str, Any]], most_cases: int = MOST_CASES, most: int = MOST_VARIANTS
) -> list[dict[str, Any]]:
    """The calls to make that the tutorial did not: for the first of the calls it made, with arguments that are not the
    same as another's, each way that its arguments can be changed.

    :param cases: The calls that were made again for tier A, as a tool keeps them.
    """
    chosen: list[dict[str, Any]] = []
    taken: list[dict[str, Any]] = []
    for case in cases:
        if len(taken) >= most_cases:
            break
        if case["args"] in taken:
            continue
        taken.append(case["args"])
        for name, args in variants_of(case["args"]):
            if len(chosen) < most:
                chosen.append(
                    {
                        "from": case["call"],
                        "tutorial": case["tutorial"],
                        "cwd": case["cwd"],
                        "change": name,
                        "args": args,
                    }
                )

    return chosen


def positional_of(repo: Path, module: str, function: str) -> list[str] | None:
    """The names of the parameters that the function takes by their place alone, in order, from the project's code, or
    None if the function cannot be read or takes *args or **kwargs."""
    found = wrappers.definition(repo, module, function)
    if found is None:
        return None
    parameters = wrappers.parameters_of(found[1])

    return [parameter.name for parameter in parameters if parameter.positional_only] if parameters is not None else None


def direct_source(module: str, function: str, positional: Sequence[str]) -> str:
    """The code of a caller that is not the tool's wrapper: it imports the module and calls the function, which is what
    the project's own code is, given the arguments as the wrapper is."""
    return (
        "import importlib\n\n\n"
        f"def {DIRECT_NAME}(**arguments):\n"
        f"    function = getattr(importlib.import_module({module!r}), {function!r})\n"
        f"    positional = [arguments.pop(name) for name in {list(positional)!r}]\n"
        "    return function(*positional, **arguments)\n"
    )


def judge_held_out(
    through_tool: Sequence[dict[str, Any] | None], from_code: Sequence[dict[str, Any] | None], tolerance: Tolerance
) -> dict[str, Any]:
    """What came of one changed call, made through the tool and made of the code's own function: agree if both gave the
    same, each time; same_error if both stopped with the same error; differs if they did not; unstable if the code's own
    function gave something else each time it was called; and not_run if there was no time. Of these only differs is
    against the tool, and only agree is for it.
    """
    tool = [call for call in through_tool if call is not None]
    code = [call for call in from_code if call is not None]
    found: dict[str, Any] = {"verdict": "agree", "differences": [], "error": None}
    if not tool or not code:
        found["verdict"] = "not_run"
        return found
    tool_failed = next((call for call in tool if not call["ok"]), None)
    code_failed = next((call for call in code if not call["ok"]), None)
    if tool_failed is not None or code_failed is not None:
        if tool_failed is not None and code_failed is not None:
            first, second = tool_failed["error"], code_failed["error"]
            found["error"] = {"type": second["type"], "message": second["message"]}
            if first["type"] == second["type"]:
                found["verdict"] = "same_error"
            else:
                found.update(
                    verdict="differs",
                    differences=[
                        f"The tool stopped with {first['type']} where the code's own function stopped with "
                        f"{second['type']}"
                    ],
                )
        elif tool_failed is not None:
            error = tool_failed["error"]
            found.update(
                verdict="differs",
                error={"type": error["type"], "message": error["message"]},
                differences=[f"The tool stopped with {error['type']} where the code's own function gave a result"],
            )
        else:
            assert code_failed is not None
            error = code_failed["error"]
            found.update(
                verdict="differs",
                error={"type": error["type"], "message": error["message"]},
                differences=[f"The tool gave a result where the code's own function stopped with {error['type']}"],
            )

        return found
    if len(tool) < len(through_tool) or len(code) < len(from_code):
        found["verdict"] = "not_run"
        return found
    reference = code[0]["result"]
    for call in code[1:]:
        unlike = differences(reference, call["result"], tolerance)
        if unlike:
            found.update(
                verdict="unstable",
                differences=[f"The code's own function gave something else when it was called again: {unlike[0]}"],
            )
            return found
    for call in tool:
        unlike = differences(reference, call["result"], tolerance)
        if unlike:
            found.update(
                verdict="differs",
                differences=[f"What the tool gave is not what the code's own function gave: {unlike[0]}"],
            )
            return found

    return found


def held_out_outcome(cases: Sequence[dict[str, Any]], repeats: int, tolerance: Tolerance) -> Outcome:
    """What the changed calls come to, as a kind of evidence: failed if the tool gave anything but what the code's own
    function gave, passed if some calls gave the same and none gave otherwise, and not obtained if none could be
    compared. A call that stopped with the same error from both, or whose function gave something else each time it was
    called, or that was not made, is neither for the tool nor against it."""
    counts = {
        name: sum(1 for case in cases if case["verdict"] == name)
        for name in ("agree", "same_error", "differs", "unstable", "not_run")
    }
    details = {"repeats": repeats, "tolerance": tolerance.to_dict(), "counts": counts, "cases": list(cases)}
    total = len(cases)
    if counts["differs"]:
        bad = next(case for case in cases if case["verdict"] == "differs")
        return Outcome(
            FAILED,
            f"{counts['differs']} of {total} changed calls did not give the same through the tool as from the code's "
            f"own function. {bad['differences'][0]}.",
            details,
        )
    showed_nothing = [
        text
        for name, text in (
            ("same_error", "stopped with the same error from both"),
            ("unstable", "could not be compared, as the code's own function gave something else each time"),
            ("not_run", "were not made in the time that was given"),
        )
        if counts[name]
        for text in [f"{counts[name]} {text}"]
    ]
    left = f" Of the others, {'; '.join(showed_nothing)}." if showed_nothing else ""
    if counts["agree"]:
        plural = "s" if counts["agree"] != 1 else ""
        return Outcome(
            PASSED,
            f"{counts['agree']} of {total} call{plural} with arguments that the tutorial did not pass gave the same "
            f"through the tool as from the code's own function, each of {repeats} times.{left}",
            details,
        )

    return Outcome(NOT_OBTAINED, f"No changed call showed what the code gives.{left}", details)


# The tests that the code comes with


def mentions(node: ast.AST, function: str) -> bool:
    """Whether the code of a test names the function, as a name or as what follows a dot."""
    return any(
        (isinstance(part, ast.Name) and part.id == function)
        or (isinstance(part, ast.Attribute) and part.attr == function)
        for part in ast.walk(node)
    )


def is_test_class(node: ast.ClassDef) -> bool:
    return node.name.startswith("Test") or any(
        (isinstance(base, ast.Attribute) and base.attr.endswith("TestCase"))
        or (isinstance(base, ast.Name) and base.id.endswith("TestCase"))
        for base in node.bases
    )


def imports_package(tree: ast.Module, package: str) -> bool:
    """Whether a file of tests imports the project's package, or something of its own folder, which is how a test that
    calls a function of the project is told from one that calls another library's function of the same name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == package for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.level > 0 or (node.module or "").split(".")[0] == package):
            return True

    return False


def names_of_tests(tree: ast.Module, function: str) -> list[str]:
    """The tests of a file that call the function: those named test_ at its top, and those of a class of tests, as
    pytest names them below the file."""
    found = []
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test")
            and mentions(node, function)
        ):
            found.append(node.name)
        elif isinstance(node, ast.ClassDef) and is_test_class(node):
            found += [
                f"{node.name}::{method.name}"
                for method in node.body
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                and method.name.startswith("test")
                and mentions(method, function)
            ]

    return found


def is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name.lower()

    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def ids_of_tests(repo: Path, module: str, function: str) -> list[str]:
    """The tests of the project's own that call the function, by the names pytest knows them by, found by reading the
    files of tests, which import the project, and never running them. A test that calls the function through another
    is not found.

    :param module: The module that the function is defined in, whose first part is the project's package."""
    files, _ = walk(repo)
    ids: list[str] = []
    looked = 0
    for path, size in files:
        if not is_test_file(path) or size > MAX_TEST_FILE_BYTES:
            continue
        looked += 1
        if looked > MAX_TEST_FILES:
            break
        try:
            tree = ast.parse((repo / path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        if not imports_package(tree, module.split(".")[0]):
            continue
        ids += [f"{path}::{name}" for name in names_of_tests(tree, function)]
        if len(ids) >= MOST_TESTS:
            break

    return ids[:MOST_TESTS]


def valid_test_result(value: Any) -> bool:
    """Whether what the runner wrote of the tests is in the shape that it writes. It is written by a process that ran
    the project's code, and so is not trusted to be anything."""
    return (
        matches(TESTS_RESULT, value)
        and value["schema"] == 1
        and len(value["failures"]) <= MAX_FAILURES
        and all(value[name] >= 0 for name in ("tests", "passed", "failed", "errors", "skipped"))
    )


def outcome_of_tests(ids: Sequence[str], result: dict[str, Any]) -> Outcome:
    """What the tests that were run come to, as a kind of evidence."""
    details = {
        "ids": list(ids),
        "tests": result["tests"],
        "passed": result["passed"],
        "failed": result["failed"],
        "errors": result["errors"],
        "skipped": result["skipped"],
        "failures": result["failures"],
        "seconds": result["seconds"],
        "output": result["output"][-MAX_OUTPUT_CHARS:],
    }
    if not result["ran"]:
        return Outcome(NOT_OBTAINED, f"The tests were not run: {result['reason'] or 'it gave no reason'}.", details)
    bad = result["failed"] + result["errors"]
    if result["failed"] or (bad and result["passed"]):
        first = result["failures"][0] if result["failures"] else None
        said = f" {first['name']}: {first['message']}" if first else ""
        return Outcome(
            FAILED,
            f"{bad} of the {result['tests']} tests of the code that call the function did not pass.{said}",
            details,
        )
    if bad:
        first = result["failures"][0] if result["failures"] else None
        said = f" {first['message']}" if first else ""
        return Outcome(
            NOT_OBTAINED, f"The tests could not be run: they stopped with an error before one passed.{said}", details
        )
    if result["passed"]:
        plural = "s" if result["passed"] != 1 else ""
        left = f" {result['skipped']} were skipped." if result["skipped"] else ""
        return Outcome(
            PASSED,
            f"{result['passed']} test{plural} of the code that call the function passed, in the environment, with no "
            f"network.{left}",
            details,
        )

    return Outcome(NOT_OBTAINED, "Every test of the code that calls the function was skipped.", details)


class CheckRunner(making.ToolRunner):
    """What runs the checks of one agent's tools, each in a container of its own, as a tool's calls are made: from the
    image of the environment, with the data that was fetched, no network, and the ceilings."""

    def run_tests(self, ids: Sequence[str], seconds: float) -> tuple[str, dict[str, Any] | None, list[str]]:
        """Runs some of the tests of the code, by pytest, in a copy of the project.

        :param ids: The tests, by the names pytest knows them by.
        :param seconds: How long they may take.
        :return: How the container ended (done, timed_out, too_big), what the runner wrote of the tests, or None, and
            what the container printed.
        :raises StoppedError: If whoever started the runs asked to stop them.
        :raises DockerUnavailableError: If Docker did not run it.
        """
        folder = self.scratch / f"run-{uuid4().hex[:12]}"
        folder.mkdir()
        try:
            here = Path(__file__).parent
            shutil.copyfile(here / CHECK_RUNNER_FILE, folder / referencing.RUNNER_AT)
            shutil.copyfile(here / making.RECORD_RUNNER_FILE, folder / making.RECORD_AT)
            spec = {"schema": SCHEMA, "tests": list(ids), "seconds": max(1, int(seconds * making.SPARE))}
            (folder / TESTS_FILE).write_text(json.dumps(spec), encoding="utf-8")
            ended, code, text = self.execute(folder, referencing.Item("tool", TESTS_FILE, "run"), seconds)
            if ended == "stopped":
                raise StoppedError("Stopped.")
            result = read_test_result(folder)
            if ended == "done" and code == referencing.DOCKER_FAILED and result is None:
                said = " ".join(referencing.lines_of(text)[-3:]) or "it gave no reason"
                raise DockerUnavailableError(f"Docker did not run the tests: {said}")
        finally:
            referencing.remove_tree(folder)

        return ended, result, referencing.lines_of(text)


def read_test_result(folder: Path) -> dict[str, Any] | None:
    """What the runner wrote of the tests, if it is there and is a result."""
    where = folder / referencing.RESULT_FOLDER
    path = folder / RESULT_AT
    try:
        status = path.lstat()
        if (
            not referencing.is_real_folder(where)
            or not stat.S_ISREG(status.st_mode)
            or status.st_size > making.MAX_CALL_BYTES
        ):
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None

    return value if valid_test_result(value) else None


def check_held_out(
    runner: CheckRunner, tool: dict[str, Any], repo: Path, seconds: float, tolerance: Tolerance
) -> Outcome:
    """Calls a tool and the code's own function with arguments that the tutorial did not pass, and says whether they
    gave the same, each time.

    :param tool: The tool as it is kept, with its wrapper's code.
    :param repo: The code that was fetched, which is read for the function's parameters and never run.
    :param seconds: How long all of the calls may take together.
    :raises StoppedError: If whoever started the runs asked to stop them.
    :raises DockerUnavailableError: If Docker did not run them.
    """
    changed = held_out(tool["evidence"]["cases"])
    if not changed:
        return outcome(
            NOT_OBTAINED,
            "Nothing that the tutorial passed can be changed here: it has no number and no list of four or more, which "
            "are what are changed.",
        )
    module, function = tool["repo"]["module"], tool["repo"]["function"]
    positional = positional_of(repo, module, function)
    if positional is None:
        return outcome(
            NOT_OBTAINED, "The code's own function cannot be read from the code, so it was not called directly."
        )
    cases = [
        wrappers.Case(index, one["tutorial"], None, {}, one["cwd"], one["args"], {})
        for index, one in enumerate(changed)
    ]
    each = seconds / 2
    through_tool = runner.replay(tool["source"], tool["name"], cases, each)
    from_code = runner.replay(direct_source(module, function, positional), DIRECT_NAME, cases, each)
    repeats = runner.tools.repeats
    judged = [
        {
            "from": one["from"],
            "tutorial": one["tutorial"],
            "change": one["change"],
            "args": shown(one["args"], 2 * MAX_TEXT_CHARS),
            **judge_held_out(through_tool.results[index], from_code.results[index], tolerance),
        }
        for index, one in enumerate(changed)
    ]
    for ended, replay in (("the tool", through_tool), ("the code's own function", from_code)):
        why = making.failed_whole(replay)
        if why is not None and not any(case["verdict"] != "not_run" for case in judged):
            return Outcome(NOT_OBTAINED, f"The calls of {ended} could not be made. {why[1]}", {"cases": judged})

    return held_out_outcome(judged, repeats, tolerance)


def check_repo_tests(runner: CheckRunner, tool: dict[str, Any], repo: Path, seconds: float) -> Outcome:
    """Runs the tests of the code that call a tool's function, and says whether they passed.

    :raises StoppedError: If whoever started the runs asked to stop them.
    :raises DockerUnavailableError: If Docker did not run them.
    """
    module, function = tool["repo"]["module"], tool["repo"]["function"]
    ids = ids_of_tests(repo, module, function)
    if not ids:
        return outcome(NOT_OBTAINED, f"No test in the code calls {function}, so there is none to run.")
    ended, result, lines = runner.run_tests(ids, seconds)
    if result is None:
        why = {
            "timed_out": "They did not end in the time that was given.",
            "too_big": "They wrote more than is allowed.",
        }.get(ended, "The container ended before the tests said how they went.")
        return outcome(
            NOT_OBTAINED, f"The tests were not run to their end. {why}", ids=ids, output="\n".join(lines[-20:])
        )

    return outcome_of_tests(ids, result)
