"""Running the methods of a bake-off on the person's data.

A method that is built has tools, each a thin wrapper of one of the authors' own functions that was called again to
see that it gave what the tutorial got. Running the method is calling one of them, once, with arguments, on the
person's data, in the container that a tool is called in everywhere else (paperagent_given.call_once): the image of the
method's environment, no network, the data of the person's read-only under /data, a process of its own on a copy of
the code of its own, for at most the minutes that were allowed and writing at most the gigabytes that are.

The call is the person's: they say which tool, and with which arguments. Or it is a model's, if they ask for one to be
proposed (paperagents/applying.py), from the task, what they say their data is, and what the method's tools say of
themselves. It is not asked until nothing else stands in the way of the call, so nothing is spent on a call that would
not be made. What a model proposes is data and nothing more: a program checks it as it checks the person's, before
anything is sent, and the model's say-so changes nothing of that:

- the tool is one that the method has, as it is kept now (and, if a model chose it, one of those it was shown);
- the arguments are an object of values by the names of the tool's parameters, each of the type that the tool's
  signature says, with each that has no default given and none that the tool does not take;
- a place in the data that an argument names is in the data of this bake-off, and is there;
- if a model chose the call, some argument is the place of the data. A call that does not use it is not on it, and the
  run would say that it was.

What a model is asked is paid for out of the bake-off's one limit, and no more is asked of it once that is reached: a
method whose call was still to be proposed is then not run, and says so.

Whether the call is made at all is for the guardrail of the method card (bakeoff_scope.py): data that is outside what
the card of the method's paper says is not run on until the person has said to go on with that method, and what is not
run is kept and shown with why, not left out. Data that was not put against a card, since nothing was said of it or the
paper is not read, is run on, and the run says that it was not put against one.

Whatever a call came to is kept (bakeoff_runs.py): what ran, with what, on what, and what it gave, took, or failed with.
It is not said that what it gave is right.
"""

import hashlib
import json
import math
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from virtual_lab.constants import SANDBOX_USER_DATA_DIR
from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerUnavailableError, ExecutionError
from virtual_lab.function_checks import FunctionSourceError, read_function
from virtual_lab.paperagents import applying, asking, proposing, wrappers
from virtual_lab.paperagents import toolmaking as making
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import bakeoff_runs as kept_runs
from virtual_lab.server import bakeoff_scope
from virtual_lab.server import own as own_data
from virtual_lab.server import paperagent_bakeoff as kept_bakeoff
from virtual_lab.server import paperagent_given as given
from virtual_lab.server.errors import ApiError
from virtual_lab.server.jobs import Job
from virtual_lab.server.paperagents import kept_tools_of

if TYPE_CHECKING:
    from virtual_lab.server.bakeoffs import Bakeoffs

MAX_TOOL_NAME_CHARS = 100
STOPPED = "Stopped. What was run is kept, and what was not got to was not run."
# How many nested levels of arguments are looked in for places in the data
MAX_DEPTH = 20


class Refused(Exception):
    """Why a call was not made, for it to be kept and shown.

    :param why: A short name for it, which a page can go by (bakeoff_runs.NOT_RUN_WHY).
    :param reason: What it is, in words.
    """

    def __init__(self, why: str, reason: str) -> None:
        super().__init__(reason)
        self.why = why
        self.reason = reason


def cut(text: str, most: int) -> str:
    return text if len(text) <= most else text[: most - 1] + "…"


def place_of(workspace: Any, name: str) -> Path | None:
    """Where a piece of the person's data is, as code is given it, or None if it is not there or cannot be given: what
    a conversation is given and what is run on here are the same."""
    files, _ = own_data.given(workspace, [name], [])

    return Path(next(iter(files))) if files else None


def inside_container(name: str) -> str:
    """Where in the container a piece of the person's data is."""
    return f"{SANDBOX_USER_DATA_DIR}/{name}"


def strings_in(value: Any, depth: int = 0) -> Iterator[str]:
    """The text of what an argument is, for the places in the data that it may name."""
    if isinstance(value, str):
        yield value
    elif depth < MAX_DEPTH and isinstance(value, dict):
        for each in value.values():
            yield from strings_in(each, depth + 1)
    elif depth < MAX_DEPTH and isinstance(value, list):
        for each in value:
            yield from strings_in(each, depth + 1)


def check_places(arguments: dict[str, Any], name: str, root: Path) -> list[str]:
    """What is wrong with the places in the data that arguments name, which are any text that starts with where the
    person's data is put: it must be this bake-off's data, and a place that is there.

    :param name: The name of the data of the bake-off.
    :param root: Where the data is on this machine.
    """
    problems = []
    base = inside_container(name)
    for text in strings_in(arguments):
        if text != SANDBOX_USER_DATA_DIR and not text.startswith(f"{SANDBOX_USER_DATA_DIR}/"):
            continue
        shown = cut(text, 80)
        if text != base and not text.startswith(f"{base}/"):
            problems.append(f"{shown!r} is not in the data of this bake-off, which is at {base}")
            continue
        parts = PurePosixPath(text[len(base) :].strip("/")).parts
        if ".." in parts:
            problems.append(f"{shown!r} goes out of the data with ..")
        elif parts and not root.joinpath(*parts).exists():
            problems.append(f"{shown!r} is not in the data")
    if len(problems) > 3:
        problems = [*problems[:3], f"and {len(problems) - 3} more places that are not as they should be"]

    return problems


def names_data(arguments: dict[str, Any], name: str) -> bool:
    """Whether some argument is the place of the data, or a place in it."""
    base = inside_container(name)

    return any(text == base or text.startswith(f"{base}/") for text in strings_in(arguments))


def check_call(tool: dict[str, Any], arguments: Any, name: str, root: Path) -> list[str]:
    """What is wrong with a call of a tool, which is nothing if it is one that the tool's signature allows. What
    checks it is a program: the names and types of the arguments, as the tool says them.

    :param tool: The tool as it is kept, with its wrapper's code.
    :param arguments: What it is to be called with.
    :param name: The name of the data of the bake-off.
    :param root: Where the data is on this machine.
    :return: What is wrong with it, in words, which is empty if nothing is.
    """
    if not isinstance(arguments, dict) or not all(isinstance(key, str) for key in arguments):
        return ["The arguments are an object of values, by the names of the tool's parameters"]
    try:
        text = json.dumps(arguments, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return ["The arguments are not JSON: a number that JSON does not have, or a value that is not plain data"]
    if len(text) > kept_runs.MAX_ARGUMENTS_CHARS:
        return [f"The arguments are more than {kept_runs.MAX_ARGUMENTS_CHARS:,} characters"]
    try:
        reading = read_function(tool["source"], tool["name"])
    except FunctionSourceError:
        return ["The tool's wrapper cannot be read for its types, so nothing can be checked of the call"]
    parameters = reading.signature.parameters
    problems = []
    unknown = [key for key in arguments if key not in parameters]
    if unknown:
        problems.append(f"The tool does not take {', '.join(cut(key, 40) for key in unknown[:3])}")
    missing = [
        parameter["name"]
        for parameter in tool["signature"]
        if parameter["required"] and parameter["name"] not in arguments
    ]
    if missing:
        problems.append(f"The tool needs {', '.join(missing[:3])}, which was not given")
    for key, value in arguments.items():
        if key in parameters and not wrappers.fits(parameters[key].annotation, wrappers.real(value)):
            problems.append(f"What is given for {key} is not of the type that the tool says")
    if not problems:
        problems += check_places(arguments, name, root)

    return problems


class Runs:
    """Runs the methods of bake-offs on the data of the person's, for the bake-offs that were given.

    :param bakeoffs: The bake-offs, which say what a method is, and which data it is run on, and which keep what came
        of the run of each.
    """

    def __init__(self, bakeoffs: "Bakeoffs") -> None:
        self.bakeoffs = bakeoffs
        self.paperagents = bakeoffs.paperagents
        self.workspace = bakeoffs.workspace

    # What is asked for

    def check_calls(self, calls: Any) -> dict[str, dict[str, Any]]:
        """The calls that were asked for, each by the method it is of.

        :raises ApiError: If they are not an object of calls by the ids of methods, each with the name of a tool and an
            object of arguments.
        """
        what = (
            "The calls to make are an object by the id of each method, with the name of a tool and its arguments, or "
            "with propose: true for a model to propose the call"
        )
        if not isinstance(calls, dict) or not calls:
            raise ApiError(422, "invalid", what)
        if len(calls) > kept_bakeoff.MAX_CANDIDATES:
            raise ApiError(422, "invalid", f"No more than {kept_bakeoff.MAX_CANDIDATES} methods can be run at once")
        checked: dict[str, dict[str, Any]] = {}
        for candidate_id, call in calls.items():
            if (
                not isinstance(candidate_id, str)
                or not isinstance(call, dict)
                or set(call) - {"tool", "arguments", "propose"}
                or not isinstance(call.get("propose", False), bool)
            ):
                raise ApiError(422, "invalid", what)
            if call.get("propose"):
                if "tool" in call or "arguments" in call:
                    raise ApiError(
                        422,
                        "invalid",
                        "A call is either the person's, with a tool and arguments, or a model's to propose",
                    )
                checked[candidate_id] = {"propose": True}
                continue
            tool = call.get("tool")
            if not isinstance(tool, str) or not 0 < len(tool) <= MAX_TOOL_NAME_CHARS or tool != tool.strip():
                raise ApiError(422, "invalid", "A tool is called by its name, which is not empty or very long")
            checked[candidate_id] = {"tool": tool, "arguments": call.get("arguments", {})}

        return checked

    def check_minutes(self, minutes: Any) -> int:
        """The most seconds that one call may take.

        :raises ApiError: If it is not a whole number of minutes that is allowed.
        """
        if minutes is None:
            return making.DEFAULT_MINUTES * 60
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= making.MAX_MINUTES:
            raise ApiError(
                422,
                "invalid",
                f"The most minutes that a call may take is a whole number from 1 to {making.MAX_MINUTES}",
            )

        return minutes * 60

    # Doing it

    def work(
        self,
        bakeoff_id: str,
        calls: dict[str, dict[str, Any]],
        seconds: int,
        asker: applying.ModelApplier | None = None,
    ) -> Callable[[Job], str]:
        """What a job does to run methods: runs each, one after another, whatever came of the one before, and, whatever
        came of the job, adds what a model that proposed calls used to what the bake-off has spent.

        :param asker: What proposes the calls that are asked of a model, which is for the job to be given if any is.
        """

        def run(job: Job) -> str:
            try:
                return self.run_all(job, bakeoff_id, calls, seconds, asker)
            finally:
                if asker is not None:
                    self.bakeoffs.settle(bakeoff_id, asker.usage)

        return run

    def run_all(
        self,
        job: Job,
        bakeoff_id: str,
        calls: dict[str, dict[str, Any]],
        seconds: int,
        asker: applying.ModelApplier | None,
    ) -> str:
        counts: dict[str, int] = {}
        job.update(candidates=len(calls), finished=0)
        for number, (candidate_id, call) in enumerate(calls.items(), 1):
            if job.stop.is_set():
                raise StoppedError(STOPPED)
            try:
                _, record = self.bakeoffs.lookup(bakeoff_id)
            except ApiError:
                break
            candidate = next((each for each in record["candidates"] if each["id"] == candidate_id), None)
            if candidate is None:
                continue
            job.update(
                f"Running {candidate['name']} ({number} of {len(calls)})",
                candidate=candidate_id,
                finished=number - 1,
            )
            try:
                run = self.run_one(job, record, candidate, call, seconds, asker)
            except StoppedError:
                raise StoppedError(STOPPED) from None
            if not self.bakeoffs.keep_run(bakeoff_id, run):
                continue
            counts[run["state"]] = counts.get(run["state"], 0) + 1
            job.log(
                f"{candidate['name']}: {run['state'].replace('_', ' ')}"
                + (f", {run['why'].replace('_', ' ')}" if run["why"] else "")
            )
        job.update("Done", candidate=None, finished=len(calls))

        return self.describe(counts)

    def describe(self, counts: dict[str, int]) -> str:
        """What running came to, in a sentence or two."""
        parts = [f"Ran {counts.get(kept_runs.RAN, 0)} of {sum(counts.values())} methods."]
        if counts.get(kept_runs.FAILED):
            parts.append(f"Failed on the data: {counts[kept_runs.FAILED]}.")
        if counts.get(kept_runs.NOT_RUN):
            parts.append(f"Not run, each with why: {counts[kept_runs.NOT_RUN]}.")

        return " ".join(parts)

    def run_one(
        self,
        job: Job,
        record: dict[str, Any],
        candidate: dict[str, Any],
        call: dict[str, Any],
        seconds: int,
        asker: applying.ModelApplier | None,
    ) -> dict[str, Any]:
        """What came of running one method: the call is made if nothing stands in the way of it, and whatever came
        of it, or why it was not made, is the run.

        :param record: The bake-off as it is kept now.
        :raises StoppedError: If running was stopped.
        :raises DockerUnavailableError: If Docker did not run it, which is not a failing of the method.
        """
        agents = self.paperagents.kept()
        found = kept_bakeoff.agent_for(candidate["paper"], agents)
        agent_id = found[0] if found is not None else None
        scope = bakeoff_scope.scope_of(self.paperagents, record["described"], candidate, agent_id)
        seen = {
            "checked": scope["checked"],
            "why": scope["why"],
            "outcome": scope["outcome"],
            "key": scope["key"],
            "went_on": scope["went_on"],
            "warnings": [
                cut(each, kept_runs.MAX_WARNING_CHARS) for each in scope["warnings"][: kept_runs.MAX_WARNINGS]
            ],
        }
        base: dict[str, Any] = {
            "schema": kept_runs.SCHEMA,
            "candidate": candidate["id"],
            "at": utc_timestamp(),
            "by": kept_runs.BY_PERSON,
            "proposed": None,
            "tool": None,
            "arguments": None,
            "seconds": None,
            "result": None,
            "printed": None,
            "data": None,
            "scope": seen,
            "method": None,
        }
        try:
            return self.attempt(job, record, candidate, found, scope, call, seconds, asker, base)
        except Refused as refused:
            return {
                **base,
                "state": kept_runs.NOT_RUN,
                "why": refused.why,
                "reason": cut(refused.reason, kept_runs.MAX_REASON_CHARS),
            }

    def attempt(
        self,
        job: Job,
        record: dict[str, Any],
        candidate: dict[str, Any],
        found: tuple[str, dict[str, Any]] | None,
        scope: dict[str, Any],
        call: dict[str, Any],
        seconds: int,
        asker: applying.ModelApplier | None,
        base: dict[str, Any],
    ) -> dict[str, Any]:
        """Makes the call, if nothing stands in the way of it, in the order that costs least, and says what came of it.
        A call that a model is to propose is asked for last of all that costs nothing, so that none is paid for that
        would not be made.

        :param base: What the run is to start as, which is filled in with who chose the call if a model did, as soon as
            it is asked, so that a call that was then refused says so.
        :raises Refused: If something does.
        """
        if record["data"] is None:
            raise Refused(
                "no_data",
                "No data is named for this bake-off, so there is nothing to run the method on. Say which of "
                "your data it is.",
            )
        name = record["data"]["own"]
        place = place_of(self.workspace, name)
        if place is None:
            raise Refused(
                "data_missing",
                f"The data called {name!r} is not where the Data page says it is, or cannot be given to code to read.",
            )
        agents = self.paperagents.kept()
        if found is None or not self.bakeoffs.is_built(candidate, agents):
            raise Refused(
                "not_built",
                f"{candidate['name']} is not built: there are no tools made of its code, so there is nothing to run. "
                "Build it first.",
            )
        if scope["outcome"] == bakeoff_scope.OUTSIDE and not scope["went_on"]:
            says = scope["warnings"][0] if scope["warnings"] else "The method card does not cover it."
            raise Refused(
                "outside",
                "The data is outside what the method card of this method's paper says it was used on, and you have not "
                f"said to go on with this method, so it was not run. {says}",
            )
        agent_id = found[0]
        runnable, problem = given.runnable(self.workspace, agent_id, self.paperagents.docker_command)
        if runnable is None:
            raise Refused("not_built", problem or "The tools of this method cannot be run now. Build it again.")
        by_model = bool(call.get("propose"))
        tools = runnable.tools[: applying.MOST_TOOLS] if by_model else runnable.tools
        if by_model:
            call = self.proposed_call(record, tools, name, place, asker, base)
        tool = next((each for each in tools if each["name"] == call["tool"]), None)
        if tool is None:
            names = ", ".join(each["name"] for each in tools[:8])
            raise Refused(
                "no_tool",
                (
                    f"The model chose {cut(call['tool'], 60)!r}, which is not one of the tools that it was shown. "
                    if by_model
                    else f"This method has no tool called {cut(call['tool'], 60)!r}. "
                )
                + f"It has: {names}.",
            )
        problems = check_call(tool, call["arguments"], name, place)
        if by_model and not problems and not names_data(call["arguments"], name):
            problems = [
                f"No argument of the call is the person's data, which is at {inside_container(name)}, so it would "
                "not be a call on it"
            ]
        if problems:
            raise Refused("bad_call", "; ".join(problems) + ".")
        listed = kept_runs.listing_of(place)
        made = {
            **base,
            "tool": {
                "name": tool["name"],
                "called": f"{tool['repo']['module']}.{tool['repo']['function']}",
                "tier": tool["tier"],
            },
            "arguments": call["arguments"],
            "data": {"own": name, "path": inside_container(name), **listed},
            "method": {"agent": agent_id, "commit": runnable.commit, "image_id": runnable.image_id},
        }
        try:
            replay, limits = given.call_once(
                self.workspace,
                agent_id,
                runnable,
                tool,
                given.encode(call["arguments"]),
                self.paperagents.docker_command,
                job.stop.is_set,
                [(place, inside_container(name))],
                seconds,
            )
        except DockerUnavailableError:
            raise
        except ExecutionError as error:
            raise Refused("cannot_mount", f"The container could not be started with the data in it: {error}") from None

        return self.outcome_of(made, replay, limits, seconds)

    def proposed_call(
        self,
        record: dict[str, Any],
        tools: Sequence[dict[str, Any]],
        name: str,
        place: Path,
        asker: applying.ModelApplier | None,
        base: dict[str, Any],
    ) -> dict[str, Any]:
        """The call that a model proposes for a method, as the person would have given it: the name of a tool, and its
        arguments. Nothing of it is yet known to be a call that can be made, which is for a program to find out.

        :param tools: The tools of the method that the model may choose from.
        :param base: The run as it starts, which says that a model chose the call, with which model, its words for why,
            and what asking it cost.
        :raises Refused: If the limit was reached before it could be asked, it gave no tool or could not be asked, or
            the arguments that it wrote are not JSON of the kind that is allowed.
        """
        if asker is None:
            raise ValueError("A call was to be proposed, and no model was given to propose it")
        base["by"] = kept_runs.BY_MODEL
        base["proposed"] = {"model": asker.model, "reason": "", "cost": 0.0, "tool": None, "arguments": None}
        before = asker.spent()
        try:
            got = asker.propose(
                record["task"], self.bakeoffs.describe_data(record), inside_container(name), place.is_dir(), tools
            )
        except asking.LimitReached as error:
            raise Refused("limit", f"A call was not proposed, as the model was not asked: {error}.") from None
        after = asker.spent()
        base["proposed"] = {
            "model": asker.model,
            "reason": got.reason,
            "cost": round(after - before, 6) if before is not None and after is not None else None,
            "tool": applying.readable(got.tool)[: kept_runs.MAX_SAID_TOOL_CHARS] if got.tool is not None else None,
            "arguments": (
                cut(applying.readable(got.arguments), kept_runs.MAX_SAID_ARGUMENTS_CHARS)
                if got.tool is not None
                else None
            ),
        }
        if got.tool is None:
            raise Refused("not_proposed", got.note or "The model proposed no call.")
        arguments, why = proposing.parse_arguments(got.arguments)
        if arguments is None:
            raise Refused("bad_call", f"The arguments that the model wrote cannot be used. {why}")

        return {"tool": got.tool, "arguments": arguments}

    def outcome_of(
        self, made: dict[str, Any], replay: making.Replay, limits: making.ToolLimits, seconds: int
    ) -> dict[str, Any]:
        """What a call came to, as it is kept, from how the container ended and what the call wrote of itself."""
        call = replay.results[0][0]
        if call is not None and not self.is_answer(call):
            call = None
        if call is None:
            why, reason = {
                "timed_out": (
                    "timed_out",
                    f"It was stopped after {seconds} seconds, which is as long as a call was allowed.",
                ),
                "too_big": ("too_big", f"It was stopped for writing more than {limits.gigabytes} gigabytes."),
            }.get(
                replay.ended,
                ("no_answer", "The call ended without saying how it went, or said it in a way that cannot be kept."),
            )
            # Five lines of at most 300 characters each (paperagents.reference.lines_of), so no more than can be kept
            ending = [line for line in replay.output if line.strip()][-5:]
            more = "\n\nThe end of what the container printed:\n" + "\n".join(ending) if ending else ""

            return {**made, "state": kept_runs.FAILED, "why": why, "reason": reason + more}
        printed = call["output"].strip()
        if not call["ok"]:
            return {
                **made,
                "state": kept_runs.FAILED,
                "why": "error",
                "reason": cut(given.failure_of(call), kept_runs.MAX_REASON_CHARS),
                "seconds": call["seconds"],
            }

        return self.fitted(
            {
                **made,
                "state": kept_runs.RAN,
                "why": None,
                "reason": "",
                "seconds": call["seconds"],
                "result": given.shown(call["result"]),
                "printed": cut(printed, kept_runs.MAX_PRINTED_CHARS) if printed else None,
            }
        )

    def is_answer(self, call: dict[str, Any]) -> bool:
        """Whether what a call wrote of itself can be kept as what it came to. It is written by the process that ran the
        authors' code, which can write what a runner would not, such as a number of seconds that is not a time or a
        number that JSON does not have."""
        seconds = call["seconds"]

        return math.isfinite(seconds) and seconds >= 0 and kept_runs.is_finite_json(call["result"])

    def fitted(self, run: dict[str, Any]) -> dict[str, Any]:
        """A run that came to an answer, as it can be kept. What a call gave that is too big to be kept is described,
        with a hash of it so that two can still be told to be the same, and is not kept: the call did give it."""
        try:
            kept_runs.encode(run)
        except ValueError:
            text = json.dumps(run["result"], sort_keys=True)
            run = {
                **run,
                "result": {
                    "type": run["result"]["type"],
                    "chars": len(text),
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "note": "It gave more than can be kept, so it is described and not kept.",
                },
            }

        return run

    # What is shown of it

    def method_now(self, found: tuple[str, dict[str, Any]] | None) -> dict[str, str] | None:
        """The PaperAgent of a method and the commit and image its tools were made of, as they are kept now, which is
        what a run says it ran, to be told apart from it. No container is asked.

        :param found: The PaperAgent of the method's paper, with its id, as the bake-off finds it.
        """
        located = given.find(self.workspace, found[0]) if found is not None else None
        _, kept = kept_tools_of(*located) if located is not None else (None, None)
        if located is None or kept is None or not kept["complete"] or not kept["tools"]:
            return None

        return {"agent": located[0].name, "commit": kept["commit"], "image_id": kept["image_id"]}
