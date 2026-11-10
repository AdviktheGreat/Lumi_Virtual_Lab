"""Making the tools of an agent from the calls that its tutorials made, and calling each again to see that it holds.

Each function that the reference run recorded a call to, and that can be a tool, is written as a wrapper (wrappers.py),
and the wrapper is then called again in a container made from the image of the environment: with no network, a root that
cannot be written to, none of this machine but its own folder, and ceilings on time, memory, and what it writes. It is
given the arguments that the tutorial passed, one call at a time, each in a process of its own and on a copy of the
project of its own, so that one call leaves nothing for the next. The answer the tutorial got is not given to it.

What comes back is compared with what the tutorial got (comparing.py). A tool all of whose calls give it again, each
time they are made, is of tier A. A tool that does not is dropped, with what happened, and it is not changed until it
does. Only how a wrapper is written is repaired, and only before it is called.
"""

import hashlib
import json
import shutil
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from virtual_lab.constants import SANDBOX_WORK_DIR
from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerUnavailableError
from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import reference as referencing
from virtual_lab.paperagents import wrappers
from virtual_lab.paperagents.comparing import Tolerance, judge, verdict_of
from virtual_lab.paperagents.stock import matches

SCHEMA = 1
TOOL_RUNNER_FILE = "tool_runner.py"
RECORD_RUNNER_FILE = "tutorial_runner.py"
# Where the files that a replay needs are put in the folder that it is given, besides the runner, and where the
# runner puts what each call gave
CALL_FILE = ".lumi-call.json"
WRAPPER_AT = "lumi_wrapper.py"
RECORD_AT = "lumi_record.py"
CALLS_FOLDER = referencing.RESULT_FOLDER

# What a person may allow, by default and at most: minutes for all of the calls of one tool, minutes for all of the
# tools, how many tools, how many times each call is made, how many times a wrapper is rewritten, and gigabytes that
# one replay may write
DEFAULT_MINUTES = 5
MAX_MINUTES = 30
DEFAULT_TOTAL_MINUTES = 20
MAX_TOTAL_MINUTES = 120
DEFAULT_TOOLS = 20
MAX_TOOLS = 50
DEFAULT_REPEATS = 2
MAX_REPEATS = 3
DEFAULT_REPAIRS = 2
MAX_REPAIRS = 3
DEFAULT_GIGABYTES = 2
MAX_GIGABYTES = 20

# How big what one call wrote of itself may be, since it is written by the process that ran the project's code
MAX_CALL_BYTES = 200_000
# How much of the time that a replay is given the runner inside takes for itself to say how it went, as a part
SPARE = 0.9
LEAST_SECONDS = referencing.LEAST_SECONDS

MEANING = (
    "A tool of tier A calls the authors' own function, and gives again what the tutorial's run gave for the arguments "
    "that the tutorial passed. It does not show that what it gives is right."
)

NUMBER = (int, float)
CALL_RESULT = {
    "schema": int,
    "ok": bool,
    "error": (referencing.ERROR, None),
    "result": (referencing.VALUE, None),
    "seconds": NUMBER,
    "output": str,
}


@dataclass(frozen=True)
class ToolLimits:
    """What the making of tools is allowed.

    :param minutes: How long all of the calls of one tool may take.
    :param total_minutes: How long all of the tools may take together.
    :param tools: How many tools are made.
    :param repeats: How many times each call is made again, to see that it gives the same each time.
    :param repairs: How many times a wrapper that does not pass is rewritten.
    :param gigabytes: How much one replay may write, counting its copies of the project.
    """

    minutes: int = DEFAULT_MINUTES
    total_minutes: int = DEFAULT_TOTAL_MINUTES
    tools: int = DEFAULT_TOOLS
    repeats: int = DEFAULT_REPEATS
    repairs: int = DEFAULT_REPAIRS
    gigabytes: int = DEFAULT_GIGABYTES

    def to_dict(self) -> dict[str, Any]:
        return {
            "minutes": self.minutes,
            "total_minutes": self.total_minutes,
            "tools": self.tools,
            "repeats": self.repeats,
            "repairs": self.repairs,
            "gigabytes": self.gigabytes,
            "memory": building.MEMORY,
            "cpus": building.CPUS,
            "pids": building.PIDS,
        }


def check_limits(
    minutes: Any, total_minutes: Any, tools: Any, repeats: Any, repairs: Any, gigabytes: Any
) -> ToolLimits:
    """What a person allowed, with the defaults for what was left out.

    :raises ValueError: If it is not whole numbers within what is allowed.
    """
    values = []
    for name, value, default, least, most in (
        ("minutes the calls of one tool may take", minutes, DEFAULT_MINUTES, 1, MAX_MINUTES),
        ("minutes all of the tools may take", total_minutes, DEFAULT_TOTAL_MINUTES, 1, MAX_TOTAL_MINUTES),
        ("tools that are made", tools, DEFAULT_TOOLS, 1, MAX_TOOLS),
        ("times each call is made again", repeats, DEFAULT_REPEATS, 1, MAX_REPEATS),
        ("times a wrapper is rewritten", repairs, DEFAULT_REPAIRS, 0, MAX_REPAIRS),
        ("gigabytes one replay may write", gigabytes, DEFAULT_GIGABYTES, 1, MAX_GIGABYTES),
    ):
        if value is None:
            values.append(default)
        elif isinstance(value, bool) or not isinstance(value, int) or not least <= value <= most:
            raise ValueError(f"The most {name} is a whole number from {least} to {most}")
        else:
            values.append(value)

    return ToolLimits(*values)


def valid_call(value: Any) -> bool:
    """Whether what a call wrote of itself is a result, in the shape the runner writes. It is written by the process
    that ran the project's code, and so is not trusted to be anything."""
    return (
        matches(CALL_RESULT, value)
        and value["schema"] == 1
        and (value["error"] is not None if not value["ok"] else value["result"] is not None)
        and referencing.is_shallow(value)
    )


def read_call(folder: Path, name: str) -> dict[str, Any] | None:
    """What one call wrote of itself, if it is there and is a result."""
    where = folder / CALLS_FOLDER
    path = where / name
    try:
        status = path.lstat()
        if not referencing.is_real_folder(where) or not stat.S_ISREG(status.st_mode) or status.st_size > MAX_CALL_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None

    return value if valid_call(value) else None


@dataclass
class Replay:
    """What came of calling a wrapper again.

    :param ended: How the container ended: done, timed_out, or too_big.
    :param code: Its exit code.
    :param results: What each call gave, by call and by time it was made, or None where it was not made or wrote
        nothing.
    :param output: The end of what it printed.
    """

    ended: str
    code: int | None
    results: list[list[dict[str, Any] | None]]
    output: list[str]


class ToolRunner(referencing.Runner):
    """What calls the wrappers of one agent's tools, each tool in a container of its own, with what a tutorial's run is
    given: the image of the environment, the data that was fetched, no network, and the ceilings."""

    def __init__(self, tag: str, limits: ToolLimits, *arguments: Any, **options: Any) -> None:
        super().__init__(tag, referencing.Limits(gigabytes=limits.gigabytes), *arguments, **options)
        self.tools = limits

    def argv(self, item: referencing.Item) -> list[str]:
        return ["python", f"{SANDBOX_WORK_DIR}/{referencing.RUNNER_AT}", "run", item.path]

    def replay(self, source: str, function: str, cases: Sequence[wrappers.Case], seconds: float) -> Replay:
        """Calls a wrapper again with the arguments of each of the calls that the tutorials made to its function.

        :param source: The wrapper's code.
        :param function: Its name.
        :param seconds: How long all of the calls may take together.
        :raises StoppedError: If whoever started the runs asked to stop them.
        :raises DockerUnavailableError: If Docker did not run it, which is not a failing of the tool.
        """
        repeats = self.tools.repeats
        folder = self.scratch / f"run-{uuid4().hex[:12]}"
        folder.mkdir()
        try:
            here = Path(__file__).parent
            shutil.copyfile(here / TOOL_RUNNER_FILE, folder / referencing.RUNNER_AT)
            shutil.copyfile(here / RECORD_RUNNER_FILE, folder / RECORD_AT)
            (folder / WRAPPER_AT).write_text(source, encoding="utf-8")
            spec = {
                "schema": SCHEMA,
                "wrapper": WRAPPER_AT,
                "function": function,
                "repeats": repeats,
                "seconds": max(1, int(seconds * SPARE)),
                "cases": [{"id": index, "args": case.args, "cwd": case.cwd} for index, case in enumerate(cases)],
            }
            (folder / CALL_FILE).write_text(json.dumps(spec), encoding="utf-8")
            ended, code, text = self.execute(folder, referencing.Item("tool", CALL_FILE, "run"), seconds)
            if ended == "stopped":
                raise StoppedError("Stopped.")
            results = [
                [read_call(folder, f"{index}-{repeat}.json") for repeat in range(repeats)]
                for index in range(len(cases))
            ]
            if ended == "done" and code == referencing.DOCKER_FAILED and not any(any(each) for each in results):
                said = " ".join(referencing.lines_of(text)[-3:]) or "it gave no reason"
                raise DockerUnavailableError(f"Docker did not run the tool: {said}")
        finally:
            referencing.remove_tree(folder)

        return Replay(ended, code, results, referencing.lines_of(text))


@dataclass
class Made:
    """What came of making one tool.

    :param record: The tool as it is kept, if it was made, which is a tool of tier A.
    :param source: Its wrapper's code.
    :param dropped: Why it was not made, if it was not.
    """

    record: dict[str, Any] | None
    source: str | None
    dropped: dict[str, Any] | None


def failed_whole(replay: Replay) -> tuple[str, str, list[str]] | None:
    """Why no call was made again at all, if that is so and it is not that there was no time: the container wrote too
    much, or ended without any of the calls saying how."""
    if any(any(each) for each in replay.results):
        return None
    if replay.ended == "too_big":
        return "replay_error", "It wrote more than is allowed when it was called again.", []
    if replay.ended == "done":
        failure = referencing.classify(None, replay.code, "\n".join(replay.output))

        return "replay_error", f"The container ended before any call said how it went. {failure['detail']}", []

    return None


def make_tool(
    runner: ToolRunner, candidate: wrappers.Candidate, seconds: float, tolerance: Tolerance, image_id: str
) -> Made:
    """Makes the wrapper of one function and calls it again, and says whether it holds.

    :param seconds: How long all of the calls of the tool may take together.
    :param image_id: The image of the environment that the calls are made in, to be kept with what they came to.
    :raises StoppedError: If whoever started the runs asked to stop them.
    :raises DockerUnavailableError: If Docker did not run it.
    """
    limits = runner.tools
    calls = len(candidate.cases) + len(candidate.skipped)
    built = wrappers.build(candidate, limits.repairs)
    if built.source is None:
        dropped = wrappers.drop(candidate.name, candidate.module, candidate.function, "wrapper", calls, built.problems)
        return Made(None, None, dropped)
    wrapped = wrappers.check_wrapper(built.source)
    replay = runner.replay(built.source, candidate.name, candidate.cases, seconds)
    why = failed_whole(replay)
    if why is None:
        evidence = [
            judge(case.to_dict(), replay.results[index], limits.repeats, tolerance)
            for index, case in enumerate(candidate.cases)
        ]
        why = verdict_of(evidence)
    if why is not None:
        kind, reason, details = why
        dropped = wrappers.drop(candidate.name, candidate.module, candidate.function, kind, calls, [reason, *details])
        return Made(None, built.source, dropped)
    record = {
        "schema": SCHEMA,
        "name": candidate.name,
        "tier": wrappers.TIER,
        "repo": {
            "module": candidate.module,
            "function": candidate.function,
            "file": candidate.file,
            "line": candidate.line,
        },
        "wrapper": wrappers.WRAPPER_FILE,
        "wrapper_sha256": hashlib.sha256(built.source.encode("utf-8")).hexdigest(),
        "signature": wrapped.parameters,
        "description": wrapped.description,
        "evidence": {
            "kind": "reference_run",
            "image_id": image_id,
            "tolerance": tolerance.to_dict(),
            "repeats": limits.repeats,
            "checked": len(evidence),
            "recorded": calls,
            "cases": evidence,
            "skipped": candidate.skipped,
            "repairs": built.repairs,
        },
    }

    return Made(record, built.source, None)


def make_tools(
    runner: ToolRunner,
    gathered: wrappers.Gathered,
    image_id: str,
    on_start: Callable[[wrappers.Candidate, int, int], None],
    on_made: Callable[[wrappers.Candidate, Made], None],
    tolerance: Tolerance | None = None,
) -> list[dict[str, Any]]:
    """Makes the tools one after another, within the time that is allowed for all of them.

    :param on_start: Called as each is started, with its place and how many there are.
    :param on_made: Called as each is finished, with what came of it.
    :return: The functions that were not tried because there was no time, each as a dropped tool.
    :raises StoppedError: If whoever started the runs asked to stop them. What was made before is not lost, as it was
        passed on when it was finished.
    """
    limits = runner.tools
    tolerance = tolerance if tolerance is not None else Tolerance()
    until = runner.clock() + limits.total_minutes * 60
    candidates = gathered.candidates
    not_tried: list[dict[str, Any]] = []
    for number, candidate in enumerate(candidates, 1):
        if runner.stop.is_set():
            raise StoppedError("Stopped.")
        left = until - runner.clock()
        if left < LEAST_SECONDS:
            not_tried.extend(
                wrappers.drop(
                    other.name, other.module, other.function, "out_of_time", len(other.cases) + len(other.skipped)
                )
                for other in candidates[number - 1 :]
            )
            break
        on_start(candidate, number, len(candidates))
        on_made(candidate, make_tool(runner, candidate, min(limits.minutes * 60, left), tolerance, image_id))

    return not_tried
