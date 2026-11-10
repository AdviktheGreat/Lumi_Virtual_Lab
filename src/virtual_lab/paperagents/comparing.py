"""Holding a call that is made again to what the tutorial got.

A call is made again with the arguments that the tutorial passed, and what comes back is described as the tutorial's
call was described, by what it is and a look at it: the value itself if it is plain data, and for anything else its
type, its shape and kind of number, a hash of it, and its values if there are not many. Here the two are compared,
within a tolerance that is kept and shown. Numbers are held to the tolerance, and everything else, which is the type,
the text, the whole numbers, the keys, and the length of a list, has to be as it was. Where only a hash of an array's
values was kept there is nothing to hold to a tolerance, so the hash has to be the same.

A call that does not give what it did is not tried again by changing it until it does, which would be to grade the
tool by itself. What differed is kept with it.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# How closely a result must be what it was to be taken for it: the number that comes back may differ by this much
# of its size, and, for numbers that are near zero, by this much. Set for the checks of tier A, and shown with them
RELATIVE_TOLERANCE = 1e-6
ABSOLUTE_TOLERANCE = 1e-9
MAX_DIFFERENCES = 5
SHOWN_CHARS = 80


@dataclass(frozen=True)
class Tolerance:
    """How closely a result has to be what it was.

    :param relative: The most that two numbers may differ by, as a part of the larger.
    :param absolute: The most that two numbers may differ by when both are small.
    """

    relative: float = RELATIVE_TOLERANCE
    absolute: float = ABSOLUTE_TOLERANCE

    def to_dict(self) -> dict[str, float]:
        return {"relative": self.relative, "absolute": self.absolute}


def shown(value: Any, limit: int = SHOWN_CHARS) -> str:
    text = repr(value)

    return text if len(text) <= limit else text[:limit] + "..."


# What a function was called with, and what came back


def is_close(expected: float, got: float, tolerance: Tolerance) -> bool:
    return math.isclose(expected, got, rel_tol=tolerance.relative, abs_tol=tolerance.absolute)


def compare_values(expected: Any, got: Any, tolerance: Tolerance, path: str, found: list[str]) -> None:
    """Adds to what differs between two values as JSON: what they are, and the numbers within a tolerance."""
    if len(found) >= MAX_DIFFERENCES:
        return
    here = path or "the value"
    if type(expected) is not type(got):
        found.append(f"{here} is {type(got).__name__} where it was {type(expected).__name__}")
    elif isinstance(expected, dict):
        marks = ("$float" in expected, "$float" in got)
        if any(marks):
            if expected != got:
                found.append(f"{here} is {shown(got)} where it was {shown(expected)}")
            return
        if set(expected) != set(got):
            found.append(f"{here} has the keys {shown(sorted(got))} where it had {shown(sorted(expected))}")
            return
        for key in expected:
            compare_values(expected[key], got[key], tolerance, f"{path}.{key}" if path else key, found)
    elif isinstance(expected, list):
        if len(expected) != len(got):
            found.append(f"{here} has {len(got)} items where it had {len(expected)}")
            return
        for index, (before, after) in enumerate(zip(expected, got, strict=True)):
            compare_values(before, after, tolerance, f"{path}[{index}]", found)
    elif isinstance(expected, float):
        if not is_close(expected, got, tolerance):
            found.append(f"{here} is {got!r} where it was {expected!r}")
    elif expected != got:
        found.append(f"{here} is {shown(got)} where it was {shown(expected)}")


def differences(expected: dict[str, Any], got: dict[str, Any], tolerance: Tolerance) -> list[str]:
    """How a result differs from what was recorded, which is nothing if it is the same within the tolerance.

    Two plain results are compared as they are. Otherwise what is compared is what the record kept of them: what they
    are, their shape and kind of number, and their values if those were kept, within the tolerance. Where only a hash
    of the values was kept, the hash has to be the same, as there is nothing to hold to a tolerance, and where only how
    a value shows itself was kept, that has to be.
    """
    found: list[str] = []
    if expected["type"] != got["type"]:
        return [f"Its type is {got['type']} where it was {expected['type']}"]
    if expected["plain"] != got["plain"]:
        return ["It is plain data where it was not" if got["plain"] else "It is not plain data where it was"]
    if expected["plain"]:
        compare_values(expected["value"], got["value"], tolerance, "", found)
        return found
    for key in ("shape", "dtype"):
        if expected.get(key) != got.get(key):
            found.append(f"The {key} is {shown(got.get(key))} where it was {shown(expected.get(key))}")
    if "values" in expected and "values" in got:
        compare_values(expected["values"], got["values"], tolerance, "values", found)
    elif "values" in expected or "values" in got:
        found.append("The values were kept of one and not of the other")
    elif "sha256" in expected or "sha256" in got:
        if expected.get("sha256") != got.get("sha256"):
            found.append("The hash of the values is not the same, and only a hash was kept, so there was no tolerance")
    elif expected.get("repr") != got.get("repr"):
        found.append(f"It shows as {shown(got.get('repr'))} where it showed as {shown(expected.get('repr'))}")

    return found[:MAX_DIFFERENCES]


def judge(
    case: dict[str, Any], replays: Sequence[dict[str, Any] | None], repeats: int, tolerance: Tolerance
) -> dict[str, Any]:
    """What came of calling again, as the evidence for one call: whether each time gave what the tutorial got.

    :param case: The call, as Case.to_dict gives it.
    :param replays: What each of the calls that were made again gave, or None for one that was not made.
    :param repeats: How many times it was to be made.
    """
    made = [replay for replay in replays if replay is not None]
    evidence: dict[str, Any] = {
        **case,
        "repeats": repeats,
        "matched": 0,
        "verdict": "match",
        "differences": [],
        "got": None,
        "error": None,
    }
    failed = next((replay for replay in made if not replay["ok"]), None)
    if failed is not None:
        error = failed["error"]
        evidence.update(verdict="error", error={"type": error["type"], "message": error["message"]})
        evidence["error"]["traceback"] = error["traceback"][-8:]
        return evidence
    if len(made) < repeats:
        evidence["verdict"] = "not_run"
        return evidence
    for replay in made:
        found = differences(case["expected"], replay["result"], tolerance)
        if found:
            if evidence["got"] is None:
                evidence.update(verdict="differs", differences=found, got=replay["result"])
        else:
            evidence["matched"] += 1

    return evidence


def verdict_of(cases: Sequence[dict[str, Any]]) -> tuple[str, str, list[str]] | None:
    """Why a tool is not of tier A, from what each of its calls came to, or None if every call gave what it did.

    :return: The kind of drop it is, what to say of it, and what differed.
    """
    for evidence in cases:
        if evidence["verdict"] == "error":
            error = evidence["error"]
            if error["type"] == "TimedOut":
                return "timed_out", f"Call {evidence['call']} of {evidence['tutorial']}: {error['message']}", []
            return (
                "replay_error",
                f"Call {evidence['call']} of {evidence['tutorial']} stopped with {error['type']} when it was made "
                f"again: {error['message'].rstrip('.')}.{hint_of(error['type'])}",
                [],
            )
    for evidence in cases:
        if evidence["verdict"] == "not_run":
            return (
                "timed_out",
                f"Call {evidence['call']} of {evidence['tutorial']} was not made again in the time a tool is given.",
                [],
            )
    for evidence in cases:
        if evidence["verdict"] == "differs":
            return (
                "replay_differs",
                f"Call {evidence['call']} of {evidence['tutorial']} gave something else when it was made again than "
                "the tutorial got.",
                evidence["differences"],
            )

    return None


def hint_of(kind: str) -> str:
    """What an error of a call that is made again, alone and in a fresh copy of the project, may mean."""
    if kind in ("FileNotFoundError", "NotADirectoryError", "IsADirectoryError"):
        return " It may read a file that the tutorial wrote or fetched before it was called."
    if kind in ("ModuleNotFoundError", "ImportError"):
        return " The environment may lack what it imports."
    if kind in ("NameError", "AttributeError", "KeyError"):
        return " It may rely on something that the tutorial set before it was called."

    return ""
