"""Whether the methods of a bake-off gave the same answer to the same question, from what was kept of each run.

Two methods are not one tool called twice: they are written by different people, and they do not give the same bytes
when they agree. So a number is held to a tolerance (which is the person's to set, and is shown), a whole number to
whole numbers, a list to a list of the same length, and a table of keys to the same keys. What is compared is only what
was kept, and what was kept of a result is one of three things: the result whole, a look at it with its values if they
were few enough, or only a hash of it. Where what was kept does not say whether two results are the same, the answer is
that it is not known, and why, and not that they are: agreeing is said only of what was seen to be so, and differing
only of what was seen to differ.

Two methods that agree are not shown to be right: they may be wrong in the same way, and a method that differs from
all the others may be the one that is right. What is said here is of the methods against each other. It says nothing
of which is better; that needs what the answer should be, which is the person's.
"""

import math
from collections.abc import Mapping
from typing import Any

from virtual_lab.paperagents import comparing

AGREE, DIFFER, UNKNOWN = "agree", "differ", "unknown"
VERDICTS = (AGREE, DIFFER, UNKNOWN)

# How much of a result was kept, which is what decides what it can be compared by
WHOLE, LOOK, HASH = "whole", "look", "hash"

MEANING = (
    "Methods that agree gave the same answer as far as what was kept of it shows, within the tolerance for numbers. "
    "That does not make the answer right: they may be wrong in the same way, and a method that differs from the rest "
    "may be the one that is right. Where only a hash, or a look, was kept of an answer, whether two agree is not known "
    "and is said not to be, and they are not counted as agreeing or as differing."
)


def kept_as(result: Mapping[str, Any]) -> str:
    """How much of a result a run kept: all of it if it is plain data (it has its value), a hash and what it is if it
    was more than could be kept, and otherwise a look at it, with its values if there were few."""
    if "value" in result:
        return WHOLE

    return HASH if "chars" in result and "repr" not in result else LOOK


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def is_same_number(first: Any, second: Any, tolerance: comparing.Tolerance) -> bool:
    """Whether two numbers are the same: two whole numbers if they are equal, and if one is not whole, if they are
    within the tolerance. A whole number too big to be a float is only the same as one that is equal to it."""
    if isinstance(first, int) and isinstance(second, int):
        return first == second
    try:
        return comparing.is_close(float(first), float(second), tolerance)
    except OverflowError:
        return first == second


def differences_in(first: Any, second: Any, tolerance: comparing.Tolerance, path: str, found: list[str]) -> None:
    """Adds to what differs between two values as JSON (as `comparing.compare_values` does for one tool called twice,
    but for two that are written apart: a whole number and a number that is not whole are both numbers)."""
    if len(found) >= comparing.MAX_DIFFERENCES:
        return
    here = path or "the result"
    if is_number(first) and is_number(second):
        if not is_same_number(first, second, tolerance):
            found.append(f"{here} is {first!r} against {second!r}")
    elif type(first) is not type(second):
        found.append(f"{here} is {comparing.shown(first)} against {comparing.shown(second)}")
    elif isinstance(first, dict):
        if ("$float" in first or "$float" in second) and first != second:
            found.append(f"{here} is {comparing.shown(first)} against {comparing.shown(second)}")
        elif "$float" in first:
            return
        elif set(first) != set(second):
            found.append(
                f"{here} has the keys {comparing.shown(sorted(first))} against {comparing.shown(sorted(second))}"
            )
        else:
            for key in first:
                differences_in(first[key], second[key], tolerance, f"{path}.{key}" if path else key, found)
    elif isinstance(first, list):
        if len(first) != len(second):
            found.append(f"{here} has {len(first)} items against {len(second)}")
        else:
            for index, (before, after) in enumerate(zip(first, second, strict=True)):
                differences_in(before, after, tolerance, f"{path}[{index}]", found)
    elif first != second:
        found.append(f"{here} is {comparing.shown(first)} against {comparing.shown(second)}")


def verdict(
    kind: str, how: str, found: list[str] | None = None, kept: tuple[str, str] = (WHOLE, WHOLE)
) -> dict[str, Any]:
    return {"verdict": kind, "how": how, "differences": found or [], "kept": list(kept)}


def of_values(first: Any, second: Any, tolerance: comparing.Tolerance, kept: tuple[str, str]) -> dict[str, Any]:
    found: list[str] = []
    differences_in(first, second, tolerance, "", found)
    if found:
        return verdict(DIFFER, "They give different answers.", found, kept)

    return verdict(AGREE, "They give the same answer, within the tolerance for numbers.", None, kept)


def compare(first: Mapping[str, Any], second: Mapping[str, Any], tolerance: comparing.Tolerance) -> dict[str, Any]:
    """Whether two results, as a run keeps them, are the same answer.

    :param first: What a run kept of what a method gave.
    :param second: The same, of another method.
    :return: Which of `VERDICTS` it is, in words how it is known (or why it is not), what differs if it does, and how
        much of each was kept.
    """
    kept = (kept_as(first), kept_as(second))
    if kept == (WHOLE, WHOLE):
        return of_values(first["value"], second["value"], tolerance, kept)
    if WHOLE in kept:
        return verdict(
            UNKNOWN,
            "One of them was kept whole and the other only as a look at it, so they cannot be compared.",
            None,
            kept,
        )
    if first["type"] != second["type"]:
        return verdict(
            UNKNOWN,
            f"They are not the same kind of result ({comparing.shown(first['type'])} and "
            f"{comparing.shown(second['type'])}), so they are not compared as one answer.",
            None,
            kept,
        )
    if HASH in kept:
        if kept == (HASH, HASH) and first["sha256"] == second["sha256"]:
            return verdict(AGREE, "Both were more than could be kept, and the hashes of them are the same.", None, kept)

        return verdict(
            UNKNOWN,
            "At least one was more than could be kept, and only a hash was kept of it, which says whether two are "
            "exactly the same and not how close they are.",
            None,
            kept,
        )
    shapes = [shape for shape in (first.get("shape"), second.get("shape")) if shape is not None]
    if len(shapes) == 2 and shapes[0] != shapes[1]:
        return verdict(
            DIFFER,
            "They are not the same shape.",
            [f"The shape is {comparing.shown(shapes[0])} against {comparing.shown(shapes[1])}"],
            kept,
        )
    if "values" in first and "values" in second:
        return of_values(first["values"], second["values"], tolerance, kept)
    if "values" in first or "values" in second:
        return verdict(UNKNOWN, "The values were kept of one and not of the other.", None, kept)
    if "sha256" in first and "sha256" in second:
        if first["sha256"] == second["sha256"]:
            return verdict(AGREE, "Only hashes of the values were kept, and they are the same.", None, kept)

        return verdict(
            UNKNOWN,
            "Only hashes of the values were kept, and they are not the same, which does not say how close the "
            "values are.",
            None,
            kept,
        )
    if (
        "shape" in first
        or "shape" in second
        or not (comparing.is_whole(first.get("repr")) and comparing.is_whole(second.get("repr")))
    ):
        return verdict(UNKNOWN, "Only how each shows itself was kept, and not all of it.", None, kept)
    if first["repr"] == second["repr"]:
        return verdict(AGREE, "They show themselves in the same way, which is all that was kept.", None, kept)

    return verdict(
        DIFFER,
        "They show themselves in different ways, which is all that was kept.",
        [f"It shows as {comparing.shown(first['repr'])} against {comparing.shown(second['repr'])}"],
        kept,
    )


def compare_runs(first: Mapping[str, Any], second: Mapping[str, Any], tolerance: comparing.Tolerance) -> dict[str, Any]:
    """Whether two runs of a bake-off gave the same answer. They can only be told to if both gave one, and were made on
    the same data as it was listed when they ran, since only the latest run of a method is kept and a method may have
    been run after the data changed.

    :param first: A run that came to an answer, as `bakeoff_runs` keeps it.
    :param second: The same, of another method.
    """
    if first["data"]["own"] != second["data"]["own"] or first["data"]["fingerprint"] != second["data"]["fingerprint"]:
        return verdict(
            UNKNOWN,
            "They were run on the data as it was listed at different times, so they were not asked the same thing.",
            None,
            (kept_as(first["result"]), kept_as(second["result"])),
        )

    return compare(first["result"], second["result"], tolerance)


def pairs(runs: Mapping[str, Mapping[str, Any] | None], tolerance: comparing.Tolerance) -> list[dict[str, Any]]:
    """Every two methods that gave an answer, each with whether they agree, in the order that they are given.

    :param runs: The latest run of each method by its id, or None for one that has no run. A run that did not come to
        an answer is not compared, and is left out of the pairs.
    """
    answered = [(name, run) for name, run in runs.items() if run is not None and run["state"] == "ran"]

    return [
        {"first": first, "second": second, **compare_runs(one, other, tolerance)}
        for index, (first, one) in enumerate(answered)
        for second, other in answered[index + 1 :]
    ]


def is_tolerance(relative: Any, absolute: Any) -> bool:
    """Whether a tolerance is one: numbers that are finite and not negative, and a relative tolerance of less than one,
    since one of 1 or more would hold any number to be the same as zero."""
    return (
        all(is_number(value) and math.isfinite(value) and value >= 0 for value in (relative, absolute)) and relative < 1
    )
