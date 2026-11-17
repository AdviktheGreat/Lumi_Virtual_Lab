"""A number as a paper wrote it, and where in what a tool gave there is one of that value.

A paper writes a number to the digits it is sure of: "0.93" says that the number is from 0.925 to 0.935. So a number
that a tool gave is the number the paper wrote if it rounds to it, and not if it is merely near: the tolerance is that
of the paper's own rounding, and nothing is allowed beyond it. A number written with few digits ("5", "12%", "0.05")
says too little to be told from one that is the same by chance, so those are not looked for at all. So is one whose
rounding is wide for its size ("1.0" is from 0.95 to 1.05, a tenth of its own size).

Nothing here asks a model anything. Where a number is, in a result that was kept, is found by walking the result, and
a place is a path of keys and positions that is written down, so that it can be followed again in another result.
"""

import math
import re
from dataclasses import dataclass
from typing import Any

# The most that is read of a number as written, the most numbers that are looked at in one result, and the longest key
# that is followed in one, which is more than a name for a number is
MAX_WRITTEN_CHARS = 40
MOST_LEAVES = 2000
MAX_KEY_CHARS = 60
# How deep a result is walked, which is more than a plain result of a function is
MAX_DEPTH = 8
# The digits that a number must have to say enough: this many, or this many if it has a decimal point
SPECIFIC_DIGITS = 3
SPECIFIC_DIGITS_WITH_POINT = 2
# How wide the rounding of a number may be for its size, as a share of it: "0.93" is within 0.6% of itself and "2.5"
# within 2%, so only the first says enough
SPECIFIC_SHARE = 0.01
# What float arithmetic is allowed on top of a rounding, so that 0.935 is within a half of 0.94 as it is on paper
SLACK = 1e-9

AS_WRITTEN = "as written"
AS_PERCENT = "as a part of one"

WRITTEN = re.compile(r"(?P<sign>[-+]?)(?P<whole>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<fraction>\d+))?(?P<percent>\s?%)?")

Path = tuple[str | int, ...]


@dataclass(frozen=True)
class Written:
    """A number as it was written.

    :param text: As written, with a true minus made a hyphen.
    :param value: What it says, as it is written: 12 for "12%".
    :param decimals: How many digits it has after the point.
    :param digits: How many of its digits say something: those from the first that is not a zero, and for a whole number
        written without a point, those before the zeros at its end, which may only be there to hold the places.
    :param percent: Whether it was written as a percentage.
    """

    text: str
    value: float
    decimals: int
    digits: int
    percent: bool

    @property
    def half(self) -> float:
        """How far a number that rounds to this may be from it: half of the last place that was written."""
        return 0.5 * 10.0**-self.decimals

    @property
    def specific(self) -> bool:
        """Whether it has digits enough to be told from a number that is the same by chance, and a rounding that is
        narrow for its size."""
        enough = self.digits >= SPECIFIC_DIGITS or (self.decimals >= 1 and self.digits >= SPECIFIC_DIGITS_WITH_POINT)

        return enough and self.half <= SPECIFIC_SHARE * abs(self.value) + SLACK

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "value": self.value, "decimals": self.decimals, "percent": self.percent}


def parse(text: Any) -> Written | None:
    """A number as written, or None if the text is anything but a number: one that is not plain digits (with commas in
    groups of three, a point, a sign, and a percent sign), or is not finite."""
    if not isinstance(text, str) or len(text) > MAX_WRITTEN_CHARS:
        return None
    cleaned = text.strip().replace("\u2212", "-")
    found = WRITTEN.fullmatch(cleaned)
    if found is None:
        return None
    whole = found["whole"].replace(",", "")
    fraction = found["fraction"] or ""
    value = float(f"{found['sign']}{whole}.{fraction or '0'}")
    if not math.isfinite(value):
        return None
    significant = (whole + fraction).lstrip("0")
    if not fraction:
        significant = significant.rstrip("0")

    return Written(cleaned, value, len(fraction), len(significant), found["percent"] is not None)


def is_number(value: Any) -> bool:
    """Whether a value of JSON is a number that can be compared: a whole number or a fraction that is finite."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def close(written: Written, number: float) -> str | None:
    """How a number that was given is the number that was written, if it rounds to it, and None if it does not: as it
    was written, or, for a percentage, as a part of one (0.123 for 12.3%)."""
    reach = written.half * (1 + SLACK)
    if abs(number - written.value) <= reach:
        return AS_WRITTEN
    if written.percent and abs(number * 100 - written.value) <= reach:
        return AS_PERCENT

    return None


def root_of(described: Any) -> Any:
    """What a result that was kept holds to be walked: its value if it is plain data, and the values that were kept of
    an array or a table if it is not, and nothing if only a look at it was kept."""
    if not isinstance(described, dict):
        return None

    return described.get("value") if described.get("plain") is True else described.get("values")


def numbers_in(described: Any, most: int = MOST_LEAVES) -> list[tuple[Path, float]]:
    """Each number in a result that was kept, with the path to it, in the order they come. A key that is longer than a
    name is not followed, so that a path is short enough to be shown."""
    found: list[tuple[Path, float]] = []

    def walk(value: Any, path: Path) -> None:
        if len(found) >= most or len(path) > MAX_DEPTH:
            return
        if is_number(value):
            found.append((path, float(value)))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, (*path, index))
        elif isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and len(key) <= MAX_KEY_CHARS:
                    walk(item, (*path, key))

    walk(root_of(described), ())

    return found


def number_at(described: Any, path: Path) -> float | None:
    """The number that a path leads to in a result, or None if the path leads to something else, or nowhere."""
    value = root_of(described)
    for step in path:
        if isinstance(step, str) and isinstance(value, dict):
            value = value.get(step)
        elif isinstance(step, int) and not isinstance(step, bool) and isinstance(value, list):
            value = value[step] if 0 <= step < len(value) else None
        else:
            return None

    return float(value) if is_number(value) else None


def path_text(path: Path) -> str:
    """A path as it would be written to get there from the result."""
    return "result" + "".join(f"[{step!r}]" for step in path)


def valid_path(value: Any) -> bool:
    """Whether what a record holds as a path is one: a list of keys and positions that is not too long."""
    return (
        isinstance(value, list)
        and len(value) <= MAX_DEPTH
        and all(
            (isinstance(step, str) and len(step) <= MAX_KEY_CHARS)
            or (isinstance(step, int) and not isinstance(step, bool))
            for step in value
        )
    )
