"""Trying a claim's calculation again with something changed, which a person asks for, and keeping what comes of it
apart from the claim.

A claim that was tried (reproducing.py) was held to a place in what a call of a tutorial gave. A person may want to know
what that number would be if the analysis were a little different: another threshold, another setting of a test. This
makes that call again, in the environment, with the arguments that the person named changed and nothing else, and reads
the number at the same place in what it gave.

What comes of it is a variant. It is never taken for the paper's result, and it does not change what was said of the
claim: the claim's own result is not touched, and a variant is kept beside it with what was changed and what it was held
to. Three things keep it to what it is:

- The call is made as the code's own function, alone, with each argument that it had, by name. It is not a tool's
  wrapper, and nothing else of the tutorial is run.
- The same call with nothing changed is made in the same way, and held to what the tutorial got. If it does not give
  that, the call alone does not stand for what the tutorial did (it may rely on what the tutorial set up before it), and
  the variant is said not to be comparable.
- What a variant gave is said as a number at a place. Whether it rounds to the number that the paper reports is said as
  that, and is not a reproduction of the paper's result: the analysis is not the paper's.
"""

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from virtual_lab.paperagents import checking, reproducing, wrappers, written
from virtual_lab.paperagents import toolmaking as making
from virtual_lab.paperagents.comparing import MAX_DIFFERENCES, Tolerance, differences, judge, shown

MEANING = (
    "A variant is a re-analysis that a person asked for: the call that a claim was held to was made again, in the "
    "environment, with the arguments that they named changed, and the number at the same place in what it gave was "
    "read. It is the result of a different analysis, and not the paper's, and it is kept beside the claim without "
    "changing it: what was said of whether the claim reproduced is as it was. The same call with nothing changed is "
    "made in the same way, and a variant is comparable only if that gave what the tutorial got. Whether a variant's "
    "number rounds to the one the paper reports is said, and it is not a reproduction."
)

# What a variant came to
GAVE = "gave"
NO_PLACE = "no_place"
UNSTABLE = "unstable"
ERROR = "error"
NOT_RUN = "not_run"
STATUSES = (GAVE, NO_PLACE, UNSTABLE, ERROR, NOT_RUN)
# What the call with nothing changed came to, which are those of comparing.judge
MATCH = "match"
CONTROL_VERDICTS = (MATCH, "differs", ERROR, NOT_RUN)

# How many arguments may be changed at once, how long a name may be, how much JSON a value may be, how deep, and how
# long a person's note may be
MOST_CHANGES = 5
MAX_NAME_CHARS = 100
MAX_VALUE_CHARS = 2000
MAX_DEPTH = 4
MAX_NOTE_CHARS = 300
# How much of a value is shown in a sentence, and of an error's words
SHOWN_VALUE = 60
MAX_MESSAGE = 300
# The most JSON of an argument's value that is offered to be changed from, which is shown cut if it is more
MAX_OFFERED_CHARS = 500
# What every account of a variant ends with
CLOSING = "This is a variant. It is not the paper's result, and the claim's own result is as it was."


class Refused(ValueError):
    """That a variant cannot be made of a claim, with a code for why and the words for it, which is known before
    anything is run."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def is_plain(value: Any, depth: int = 0) -> bool:
    """Whether a value is what an argument can be given as: text, a truth value, nothing, or a number that is finite, or
    a list or a table of those, not too deep. A table with the key that stands for a number that JSON does not have is
    not."""
    if depth > MAX_DEPTH:
        return False
    if value is None or isinstance(value, bool | str):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(is_plain(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and key != "$float" and is_plain(item, depth + 1) for key, item in value.items()
        )

    return False


def same_value(left: Any, right: Any) -> bool:
    """Whether two values are written the same, so that 1 and 1.0, which are not the same to the code, are not."""
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def check_changes(changes: Any, args: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The arguments that a person asked to change, each with what it was and what it is to be, if they can be.

    :param changes: What was asked, which is the new value of each argument by its name.
    :param args: What the call was given, by the name of each parameter, as JSON.
    :raises Refused: If it is not a few arguments that the call was given, with values that are not what they were.
    """
    if not isinstance(changes, dict) or not changes:
        raise Refused("invalid", "Name the arguments to change, each with the value that it is to have")
    if len(changes) > MOST_CHANGES:
        raise Refused("invalid", f"At most {MOST_CHANGES} arguments are changed at once")
    found = []
    for name, value in changes.items():
        if not isinstance(name, str) or len(name) > MAX_NAME_CHARS:
            raise Refused("invalid", "The name of an argument is text")
        if name not in args:
            known = ", ".join(sorted(args)[:20])
            raise Refused("invalid", f"The call was not given an argument called {name}. It was given {known}")
        if not is_plain(value) or len(json.dumps(value)) > MAX_VALUE_CHARS:
            raise Refused(
                "invalid",
                f"The value for {name} is not one that an argument is given as: text, a truth value, nothing, a number "
                f"that is finite, or a list or table of those, of at most {MAX_VALUE_CHARS} characters",
            )
        if same_value(value, args[name]):
            raise Refused("invalid", f"{name} was given that value, so it is not a change")
        found.append({"name": name, "was": args[name], "now": value})

    return found


@dataclass(frozen=True)
class Plan:
    """What is to be made again, which is known without running anything.

    :param entry: The claim as the trying of the claims kept it.
    :param case: The call, as it was made, which can be made again.
    :param changes: What is to be changed, each with the name, what it was, and what it is to be.
    :param module: The module that defines the function.
    :param function: The function's name.
    :param positional: The parameters that the function takes by their place alone, in order.
    """

    entry: Mapping[str, Any]
    case: wrappers.Case
    changes: list[dict[str, Any]]
    module: str
    function: str
    positional: list[str]

    @property
    def link(self) -> Mapping[str, Any]:
        return self.entry["link"]

    @property
    def changed(self) -> dict[str, Any]:
        """What the call is given, with the changes made."""
        return {**self.case.args, **{each["name"]: each["now"] for each in self.changes}}


Positional = Callable[[Path, str, str], list[str] | None]


def call_of(
    entry: Mapping[str, Any],
    detail: Mapping[str, Any] | None,
    repo: Path,
    positional_of: Positional = checking.positional_of,
) -> tuple[wrappers.Case, str, str, list[str]]:
    """The call that a claim was held to, as it can be made again: the call with the arguments it was given, the module
    and the function, and the parameters that the function takes by their place alone.

    :param entry: The claim as the trying kept it.
    :param detail: What was kept of the tutorial that the claim was held to, or None if that is not kept.
    :param repo: The code that was fetched, which is read for what the function takes and never run.
    :param positional_of: What says which parameters a function takes by their place alone, or None if it cannot be
        read. It is given so that a page that offers every claim's call reads each function once.
    :raises Refused: If the claim was not attempted, was held to a line that was printed and not a call, the tutorial's
        record is gone, or the call cannot be made again from what JSON has.
    """
    link = entry["link"]
    if entry["status"] == reproducing.NOT_ATTEMPTED or link is None:
        raise Refused("not_attempted", "That claim was not attempted, so there is no call that it was held to")
    if link["source"] != reproducing.CALL or not isinstance(link["call"], int):
        raise Refused(
            "not_a_call",
            "That claim was held to a line that the tutorial printed, and a line is not a call that can be made again "
            "with other arguments",
        )
    if detail is None or detail["status"] != "ok":
        raise Refused("no_record", "What was kept of that tutorial's run is gone. Run the tutorials again")
    call = next((each for each in detail["calls"] if each["id"] == link["call"]), None)
    if call is None:
        raise Refused("no_call", "The call that the claim was held to is not in what was kept of the tutorial's run")
    refusal = wrappers.refusal_of([(detail, call)])
    if refusal is not None:
        raise Refused("cannot_call", wrappers.DROPPED[refusal])
    case, why = wrappers.case_of(dict(detail), call)
    if case is None:
        raise Refused("cannot_call", why or "That call cannot be made again")
    positional = positional_of(repo, call["module"], call["function"])
    if positional is None:
        raise Refused("cannot_call", "The function cannot be read from the code, so it cannot be called directly")

    return case, call["module"], call["function"], positional


def plan(entry: Mapping[str, Any], detail: Mapping[str, Any] | None, repo: Path, changes: Any) -> Plan:
    """What it takes to make a claim's call again with arguments changed, or why it cannot be.

    :param changes: The new value of each argument to change, by its name.
    :raises Refused: If the call cannot be made again (see call_of), or what is asked is not fit.
    """
    case, module, function, positional = call_of(entry, detail, repo)

    return Plan(entry, case, check_changes(changes, case.args), module, function, positional)


def options_of(
    entry: Mapping[str, Any],
    detail: Mapping[str, Any] | None,
    repo: Path,
    positional_of: Positional = checking.positional_of,
) -> dict[str, Any]:
    """What a person may change of a claim's call, for a page that lets them choose: the function and each argument that
    it was given, as it was, or why no variant can be made of the claim. Nothing is run.

    An argument is changeable if it is one that an argument is given as. Its value is given if it is short, and is
    otherwise only shown, cut.
    """
    try:
        case, module, function, _ = call_of(entry, detail, repo, positional_of)
    except Refused as refused:
        return {"claim": entry["id"], "can": False, "refused": {"code": refused.code, "message": refused.message}}

    return {
        "claim": entry["id"],
        "can": True,
        "refused": None,
        "function": f"{module}.{function}",
        "arguments": [
            {
                "name": name,
                "text": shown(value, SHOWN_VALUE * 2),
                "value": value if len(json.dumps(value)) <= MAX_OFFERED_CHARS else None,
                "plain": is_plain(value),
            }
            for name, value in case.args.items()
        ],
    }


def number_at(result: Any, path: Sequence[Any]) -> float | None:
    return written.number_at(result, tuple(path))


def control_of(
    case: wrappers.Case,
    results: Sequence[dict[str, Any] | None],
    repeats: int,
    tolerance: Tolerance,
    path: Sequence[Any],
) -> dict[str, Any]:
    """What the call with nothing changed came to: whether each time it gave what the tutorial got, and the number at
    the place that the claim was held to."""
    judged = judge(case.to_dict(), results, repeats, tolerance)
    made = [each for each in results if each is not None]
    error = judged["error"]
    return {
        "verdict": judged["verdict"],
        "gave": number_at(made[0]["result"], path) if judged["verdict"] == MATCH else None,
        "differences": judged["differences"],
        "error": {"type": error["type"], "message": error["message"][:MAX_MESSAGE]} if error is not None else None,
    }


def variant_of(
    results: Sequence[dict[str, Any] | None], repeats: int, tolerance: Tolerance, path: Sequence[Any]
) -> dict[str, Any]:
    """What the call with arguments changed came to: an error, not made, not the same each time, a result with no number
    at the place, or the number there."""
    made = [each for each in results if each is not None]
    found: dict[str, Any] = {"status": GAVE, "gave": None, "values": [], "type": None, "error": None, "differences": []}
    failed = next((each for each in made if not each["ok"]), None)
    if failed is not None:
        error = failed["error"]
        found.update(status=ERROR, error={"type": error["type"], "message": error["message"][:MAX_MESSAGE]})
        return found
    if len(made) < repeats:
        found["status"] = NOT_RUN
        return found
    values = [number_at(each["result"], path) for each in made]
    found.update(values=values, type=made[0]["result"]["type"])
    unlike = [text for each in made[1:] for text in differences(made[0]["result"], each["result"], tolerance)]
    if unlike:
        found.update(status=UNSTABLE, differences=unlike[:MAX_DIFFERENCES])
    elif values[0] is None:
        found["status"] = NO_PLACE
    else:
        found["gave"] = values[0]

    return found


def changes_text(changes: Sequence[Mapping[str, Any]]) -> str:
    return ", ".join(
        f"{each['name']} = {shown(each['now'], SHOWN_VALUE)} in place of {shown(each['was'], SHOWN_VALUE)}"
        for each in changes
    )


CONTROL_WORDS = {
    MATCH: "The same call with nothing changed, made here in the same way, gave what the tutorial got.",
    "differs": (
        "The same call with nothing changed, made here alone, did not give what the tutorial got{why}, so the call "
        "alone does not stand for what the tutorial did, and what the variant gave cannot be held to what it got."
    ),
    ERROR: (
        "The same call with nothing changed, made here alone, stopped with an error{why}, so the call alone does not "
        "stand for what the tutorial did."
    ),
    NOT_RUN: "The same call with nothing changed was not made in the time that was given.",
}


def text_of(
    link: Mapping[str, Any],
    number: str,
    changes: Sequence[Mapping[str, Any]],
    control: Mapping[str, Any],
    variant: Mapping[str, Any],
    rounds: bool | None,
) -> str:
    """What a variant came to, in words."""
    what = changes_text(changes)
    at = written.path_text(tuple(link["path"])) if link["path"] is not None else "its result"
    status = variant["status"]
    if status == GAVE:
        said = (
            f"With {what}, the call gave {variant['gave']!r} at {at}. The claim was held to {link['where']}, which "
            f"gave {link['got']!r}, and the paper reports {number}."
        )
    elif status == NO_PLACE:
        said = f"With {what}, the call ran and gave a {variant['type']} with no number at {at}."
    elif status == UNSTABLE:
        said = f"With {what}, the call gave something else each time it was made, so no one number is said."
    elif status == ERROR:
        said = f"With {what}, the call stopped with {variant['error']['type']}: {variant['error']['message']}"
    else:
        said = f"With {what}, the call was not made in the time that was given."
    why = ""
    if control["error"] is not None:
        why = f" ({control['error']['type']})"
    elif control["differences"]:
        why = f" ({control['differences'][0]})"
    said += " " + CONTROL_WORDS[control["verdict"]].format(why=why)
    if status == GAVE and rounds is not None:
        said += (
            " That number rounds to the one the paper reports, which is not a reproduction of the paper's result."
            if rounds
            else " That number does not round to the one the paper reports."
        )

    return f"{said} {CLOSING}"


def run(plan_: Plan, runner: making.ToolRunner, seconds: float, tolerance: Tolerance | None = None) -> dict[str, Any]:
    """Makes the call again with nothing changed and with the arguments changed, each time in a process of its own and
    as many times as the runner is set to, as the code's own function, and says what came of both.

    :param seconds: How long both may take together.
    :raises StoppedError: If whoever started the runs asked to stop them.
    :raises DockerUnavailableError: If Docker did not run them.
    """
    tolerance = tolerance if tolerance is not None else Tolerance()
    link = plan_.link
    path = link["path"] if link["path"] is not None else []
    variant_case = replace(plan_.case, args=plan_.changed, expected={})
    replay = runner.replay(
        checking.direct_source(plan_.module, plan_.function, plan_.positional),
        checking.DIRECT_NAME,
        [plan_.case, variant_case],
        seconds,
    )
    repeats = runner.tools.repeats
    whole = making.failed_whole(replay)
    control = control_of(plan_.case, replay.results[0], repeats, tolerance, path)
    variant = (
        {"status": NOT_RUN, "gave": None, "values": [], "type": None, "error": None, "differences": [whole[1]]}
        if whole is not None
        else variant_of(replay.results[1], repeats, tolerance, path)
    )
    number = written.parse(plan_.entry["value"])
    rounds = (
        written.close(number, variant["gave"]) is not None
        if number is not None and variant["gave"] is not None
        else None
    )

    return {
        "claim": plan_.entry["id"],
        "quote": plan_.entry["quote"],
        "number": link["number"]["text"],
        "tutorial": {"id": link["tutorial"]["id"], "path": link["tutorial"]["path"]},
        "call": link["call"],
        "function": f"{plan_.module}.{plan_.function}",
        "where": link["where"],
        "path": list(path),
        "changes": plan_.changes,
        "claim_run": link["got"],
        "control": control,
        "variant": variant,
        "comparable": control["verdict"] == MATCH and variant["status"] == GAVE,
        "rounds_to_paper": rounds,
        "repeats": repeats,
        "tolerance": tolerance.to_dict(),
        "text": text_of(link, link["number"]["text"], plan_.changes, control, variant, rounds),
    }
