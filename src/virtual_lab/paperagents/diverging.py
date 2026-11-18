"""Where code that does not give a paper's number parts from the paper, and what differs that could be why.

A claim that was tried (reproducing.py) and was not reproduced, or only partly, is looked at again, by a program, with
nothing run and no model asked. It is looked at in two ways, each held to what was kept:

- The first point at which the tutorial parts from a number the paper states. The calls that a tutorial made are in the
  order it made them, and each claim of the paper that was held to one of them either agreed there or did not, so what
  is named is the first output, in that order, that did not: where it is, what it gave, and what the paper says. The
  outputs before it that agreed are named too, as the tutorial agrees with the paper as far as they go. A place in a
  line that a tutorial printed has no known order among its calls, and comes after them.
- The differences that were found between what the paper says it used and what was used here: the version of a package
  or of Python that the paper names and the one that is installed, data that the paper names and none was given to the
  tutorials, runs of the tutorial that did not agree and no seed set in it, and a number that the paper gives for an
  argument of a function and the one that the call was given.

A difference is one that was found, and not a cause. Nothing was changed and run again to see whether the number came
back, so that none of them is said to be why it did not. And that none was found does not say that there is none: what
the paper does not say, the code's own defaults, and what is installed under another name are not seen.
"""

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from virtual_lab.paperagents import reproducing, written

MEANING = (
    "For each claim that was not reproduced, or only partly, this names the first output of the tutorial that parts "
    "from a number the paper states, and lists differences found between what the paper says it used and what was used "
    "here. A difference is one that was found, not a cause: nothing was changed and run again to see whether the "
    "number came back. That none was found does not say that there is none, as what the paper does not say, and the "
    "code's own defaults, are not seen."
)

PYTHON = "python"
PACKAGE = "package"
DATA = "data"
RUNS = "runs"
SEED = "seed"
ARGUMENT = "argument"
KINDS = (PYTHON, PACKAGE, DATA, RUNS, SEED, ARGUMENT)

SAME = "same"
DIFFERS = "differs"
NOT_INSTALLED = "not_installed"
NO_VERSION = "no_version"
NOT_COMPARABLE = "not_comparable"

# How many outputs that agreed are named before the first that did not, how many numbers of the paper are named for an
# argument, how many names of data are said, how many calls are looked at for what the paper says of their arguments,
# and how many characters of the paper are kept around a statement of one
MOST_AGREED = 5
MOST_STATED = 3
MOST_DATA = 3
MOST_CALLS = 100
QUOTE_CONTEXT = 60
# The shortest name of an argument that is looked for in the paper, as a shorter one is in it for other reasons
LEAST_NAME = 3
MAX_PAPER_CHARS = 2_000_000

PYTHON_NAMES = frozenset({"python", "python3", "cpython"})
# What the names that a paper uses for a package are, where they are not the name it is installed by
ALIASES = {
    "pytorch": "torch",
    "sklearn": "scikit-learn",
    "scikit-learn": "scikit-learn",
    "opencv": "opencv-python",
    "pil": "pillow",
    "umap": "umap-learn",
}

SEPARATORS = re.compile(r"[-_.]+")
PIP_LINE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;#]+)", re.MULTILINE)
CONDA_LINE = re.compile(
    r"/(?P<name>[A-Za-z0-9._+-]+?)-(?P<version>\d[^-/]*)-[^-/]+\.(?:tar\.bz2|conda)\s*$", re.MULTILINE
)
PLAIN_VERSION = re.compile(r"v?(?P<number>\d+(?:\.\d+)*)")
LEADING_VERSION = re.compile(r"\d+(?:\.\d+)*")
SEEDED = re.compile(
    r"\b(?:np\.random\.seed|numpy\.random\.seed|random\.seed|set_seed|manual_seed|seed_everything|"
    r"RandomState|default_rng|random_state|seed)\b",
)
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def normal(name: str) -> str:
    """A name of a package as one name however it is written: lower case, with a run of -, _ and . as one -."""
    return SEPARATORS.sub("-", name.strip().casefold())


def installed_of(lock: str | None) -> dict[str, str]:
    """The version of each package that the lock says is installed, by its name, from a list of `name==version` lines or
    one of the links of an explicit list of conda packages."""
    found: dict[str, str] = {}
    for pattern in (PIP_LINE, CONDA_LINE):
        for match in pattern.finditer(lock or ""):
            found.setdefault(normal(match["name"]), match["version"])

    return found


def versions_agree(stated: str, installed: str, coarse: bool = False) -> bool | None:
    """Whether the version that a paper states is the one that is installed, as far as it states it: 1.4 is the one that
    1.4.2 is of, and 1.4.2 is not, and 1.4.0 is 1.4. None if the paper does not give a plain version (a range, or words
    with it), or what is installed has none, as they cannot then be compared.

    :param coarse: Whether what is installed is only as exact as it is given, as the Python of an environment is, which
        is of a minor version: the paper's 3.12.1 is then that of 3.12, as far as it can be told.
    """
    paper = PLAIN_VERSION.fullmatch(stated.strip())
    have = LEADING_VERSION.match(installed.strip())
    if paper is None or have is None:
        return None
    wanted = [int(part) for part in paper["number"].split(".")]
    got = [int(part) for part in have.group(0).split(".")]
    if coarse:
        wanted = wanted[: len(got)]
    got += [0] * (len(wanted) - len(got))

    return got[: len(wanted)] == wanted


# What the paper says it used, held to what was used


def software_of(
    software: Sequence[Mapping[str, Any]], installed: Mapping[str, str], python: str | None
) -> list[dict[str, Any]]:
    """Each software that the paper names, with its version as the paper gives it and the one that is installed, and
    whether they are the same, differ, cannot be compared, or it is not installed (as it may be of another language, or
    be installed under another name).

    :param software: What the paper names, as it was read: each with its name, version, and the quote.
    :param installed: The version of each package that is installed, by name.
    :param python: The version of Python that the environment was built with.
    """
    found = []
    for fact in software:
        name = fact["name"]
        key = normal(name)
        version = fact["version"].strip() or None
        have = python if key in PYTHON_NAMES else installed.get(ALIASES.get(key, key))
        agree = (
            versions_agree(version, have, coarse=key in PYTHON_NAMES)
            if version is not None and have is not None
            else None
        )
        if have is None:
            state = NOT_INSTALLED
        elif version is None:
            state = NO_VERSION
        elif agree is None:
            state = NOT_COMPARABLE
        else:
            state = SAME if agree else DIFFERS
        found.append({"name": name, "paper": version, "installed": have, "state": state, "quote": fact["quote"]})

    return found


def software_differences(software: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The software that the paper names that is not the version that is installed."""
    found = []
    for each in software:
        if each["state"] != DIFFERS:
            continue
        kind = PYTHON if normal(each["name"]) in PYTHON_NAMES else PACKAGE
        found.append(
            {
                "kind": kind,
                "text": f"The paper names {each['name']} {each['paper']}, and {each['installed']} is installed here.",
                "evidence": {"name": each["name"], "paper": each["paper"], "installed": each["installed"]},
                "quote": each["quote"],
            }
        )

    return found


def data_differences(data: Mapping[str, Any] | None, datasets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """That the paper names data and none was given to the tutorials to read, so that they ran on what the code holds or
    fetches itself.

    :param data: What the tutorials were given to read, or None if they were given none.
    :param datasets: The data that the paper names, as it was read.
    """
    if data is not None or not datasets:
        return []
    names = [each["accession"] or each["name"] for each in datasets[:MOST_DATA]]
    more = len(datasets) - len(names)
    said = ", ".join(names) + (f", and {more} more" if more > 0 else "")

    return [
        {
            "kind": DATA,
            "text": (
                f"The paper names data ({said}), and none was given to the tutorials to read, so they ran on what the "
                "code holds or fetches itself."
            ),
            "evidence": {"names": names, "named": len(datasets), "given": None},
            "quote": datasets[0]["quote"],
        }
    ]


# What of the tutorial


def runs_differences(detail: Mapping[str, Any], text: str) -> list[dict[str, Any]]:
    """That the runs of the tutorial did not give the same, and whether anything in the tutorial itself sets a seed.

    :param detail: What was kept of the tutorial's runs.
    :param text: What the tutorial says, as text.
    """
    if detail["stable"] is not False:
        return []
    parts = [part for part in detail["differs"] if part != "status"]
    said = " and ".join(parts) if parts else "what they did"
    found = [
        {
            "kind": RUNS,
            "text": f"The {len(detail['runs'])} runs of the tutorial did not give the same {said}.",
            "evidence": {"runs": len(detail["runs"]), "differs": list(detail["differs"])},
            "quote": None,
        }
    ]
    if SEEDED.search(text) is None:
        found.append(
            {
                "kind": SEED,
                "text": (
                    "Nothing in the tutorial itself sets a random seed, though what it calls may, and its runs did not "
                    "give the same."
                ),
                "evidence": {"seeded": False},
                "quote": None,
            }
        )

    return found


def name_pattern(name: str) -> re.Pattern[str]:
    """What the paper may say of an argument that is called `name`: the name, with its words apart or joined by _ or -,
    and then = or : or words, and a number."""
    words = [re.escape(word) for word in re.split(r"[_\s-]+", name) if word]
    joined = r"[\s_-]*".join(words)

    then = r"(?:\s*[=:]\s*|\s+(?:=|of|to|was|were|is|set\s+to|equal\s+to)\s+)"

    return re.compile(rf"(?<![\w.]){joined}{then}(?P<number>{NUMBER.pattern})(?![\w])", re.IGNORECASE)


def stated_for(name: str, paper: str) -> list[tuple[float, str]]:
    """The numbers that the paper gives for an argument by its name, each with the words round it."""
    found = []
    for match in name_pattern(name).finditer(paper):
        try:
            number = float(match["number"].replace(",", ""))
        except ValueError:
            continue
        start, end = match.span()
        quote = " ".join(paper[max(0, start - QUOTE_CONTEXT) : end + QUOTE_CONTEXT].split())
        found.append((number, quote))

    return found


def plain_numbers(call: Mapping[str, Any]) -> dict[str, float]:
    """The arguments of a call that were numbers, by name."""
    found = {}
    for name, value in call["args"].items():
        if isinstance(value, dict) and value.get("plain") is True and written.is_number(value.get("value")):
            found[name] = float(value["value"])

    return found


def argument_differences(
    detail: Mapping[str, Any],
    until: int | None,
    paper: str | None,
    stated_of: Callable[[str], list[tuple[float, str]]] | None = None,
) -> list[dict[str, Any]]:
    """The numbers that the paper gives for an argument of a function, by its name, that the tutorial's call was given
    another for: for each such argument of the calls up to the one at the point that was named, if every number that
    the paper gives for it differs from what the call was given.

    :param detail: What was kept of the tutorial's runs.
    :param until: The number of the last call that is looked at, or None for all of them.
    :param paper: The text of the paper, or None if it is not kept.
    :param stated_of: Gives what the paper states for an argument by its name, where that is kept so that the paper is
        read once for a name however many claims and calls are looked at. By default the paper is read for each.
    """
    if not paper:
        return []
    lookup = stated_of or (lambda name: stated_for(name, paper))
    calls = [
        call for call in detail["calls"][:MOST_CALLS] if call["returned"] and (until is None or call["id"] <= until)
    ]
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    for call in calls:
        for name, value in plain_numbers(call).items():
            if len(name) < LEAST_NAME or (name, value) in seen:
                continue
            seen.add((name, value))
            stated = lookup(name)
            if not stated or any(abs(number - value) <= 1e-9 * max(1.0, abs(value)) for number, _ in stated):
                continue
            numbers = list(dict.fromkeys(number for number, _ in stated))[:MOST_STATED]
            said = " or ".join(f"{number:g}" for number in numbers)
            found.append(
                {
                    "kind": ARGUMENT,
                    "text": (
                        f"The paper gives {name} as {said}, and the call of {call['qualname']} was given {value:g}."
                    ),
                    "evidence": {
                        "name": name,
                        "paper": numbers,
                        "gave": value,
                        "call": call["id"],
                        "function": f"{call['module']}.{call['qualname']}",
                    },
                    "quote": stated[0][1],
                }
            )

    return found


# Where a tutorial first parts from the paper


def parts(entry: Mapping[str, Any]) -> bool:
    """Whether a claim that was tried got a number that does not round to the one the paper states, which is so of one
    that was not reproduced, and of one that was partly for being near it, and not of one that was partly because its
    runs did not agree. A claim whose number was not read cannot be said to part from it."""
    if entry["status"] not in (reproducing.PARTLY, reproducing.NOT_REPRODUCED) or entry["link"] is None:
        return False
    number = written.parse(entry["value"])

    return number is not None and written.close(number, entry["link"]["got"]) is None


def order_of(entry: Mapping[str, Any], position: int) -> tuple[int, int]:
    """Where a claim's place is in the order of its tutorial: by the number of its call, with a place in a printed line,
    which has no known order among the calls, after them, in the order of the claims."""
    link = entry["link"]
    if link["source"] == reproducing.CALL and isinstance(link["call"], int):
        return 0, link["call"]

    return 1, position


def outcome_of(entry: Mapping[str, Any]) -> dict[str, Any]:
    """What a claim's place gave and what the paper says, as it is named at a point."""
    link = entry["link"]

    return {
        "claim": entry["id"],
        "quote": entry["quote"],
        "number": link["number"]["text"],
        "got": link["got"],
        "where": link["where"],
        "call": link["call"] if link["source"] == reproducing.CALL else None,
    }


def points_of(entries: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """For each tutorial that a claim was held to a place of, the first output that parts from a number the paper states
    and the outputs before it that agree, in the order that the tutorial made its calls.

    :return: By the tutorial's path.
    """
    by_tutorial: dict[str, list[tuple[tuple[int, int], Mapping[str, Any]]]] = {}
    for position, entry in enumerate(entries):
        if entry["link"] is not None:
            by_tutorial.setdefault(entry["link"]["tutorial"]["path"], []).append((order_of(entry, position), entry))
    found = {}
    for path, placed in by_tutorial.items():
        placed.sort(key=lambda each: each[0])
        first = next((at for at, (_, entry) in enumerate(placed) if parts(entry)), None)
        if first is None:
            continue
        before = [entry for _, entry in placed[:first]]
        found[path] = {
            "first": outcome_of(placed[first][1]),
            "ordered": placed[first][0][0] == 0,
            "agreed": [outcome_of(entry) for entry in before[-MOST_AGREED:]],
            "agreed_count": len(before),
        }

    return found


def point_text(path: str, point: Mapping[str, Any]) -> str:
    """What a point is, in words."""
    first = point["first"]
    gave = f"{first['where']}: it gave {first['got']!r}, and the paper reports {first['number']}."
    if point["ordered"]:
        said = f"In {path}, the first output, in the order that it made its calls, that parts from the paper is {gave}"
    else:
        said = (
            f"In {path}, the outputs that part from the paper are in lines that it printed, whose order among its "
            f"calls is not known. The first of them is {gave}"
        )
    count = point["agreed_count"]
    if count:
        last = point["agreed"][-1]
        said += (
            f" {count} output{'s' if count != 1 else ''} before it agreed with the paper, the last "
            f"{last['where']}, which gave {last['got']!r} for the paper's {last['number']}."
        )
    else:
        said += " No output of the tutorial before it was held to a number of the paper."

    return said


# Putting it together


@dataclass
class Evidence:
    """What is kept that a claim that did not reproduce is looked at against, which is nothing that is run.

    :param python: The version of Python that the environment was built with, or None if that is not known.
    :param lock: The versions of what is installed, as a list of `name==version` lines, or None if it is not known.
    :param software: What the paper names, as it was read, each with its name, version, and the quote.
    :param datasets: The data that the paper names, as it was read, each with its name, accession, and the quote.
    :param data: What the tutorials were given to read, or None if they were given none.
    :param paper: The paper's text, or None if it is not kept.
    :param details: What was kept of each tutorial's runs, by its path.
    :param text_of: Gives what a tutorial says, by its path, as text.
    """

    python: str | None
    lock: str | None
    software: Sequence[Mapping[str, Any]]
    datasets: Sequence[Mapping[str, Any]]
    data: Mapping[str, Any] | None
    paper: str | None
    details: Mapping[str, Mapping[str, Any]]
    text_of: Callable[[str], str]


@dataclass
class Divergence:
    """What looking at the claims that did not reproduce came to.

    :param claims: Each claim that was not reproduced or was partly, in order, with where its tutorial first parts from
        the paper and the differences that were found for it.
    :param software: Each software that the paper names, with the version that is installed.
    :param differences: The differences found that are of the whole run: Python, packages, and data.
    """

    claims: list[dict[str, Any]] = field(default_factory=list)
    software: list[dict[str, Any]] = field(default_factory=list)
    differences: list[dict[str, Any]] = field(default_factory=list)


def counts_of(differences: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """How many differences of each kind were found."""
    counted = Counter(each["kind"] for each in differences)

    return {kind: counted.get(kind, 0) for kind in KINDS}


def diverge(entries: Sequence[Mapping[str, Any]], evidence: Evidence) -> Divergence:
    """Looks at each claim that was tried and was not reproduced, or was partly, for where its tutorial first parts from
    the paper, and for the differences that were found.

    :param entries: The claims as the trying of them kept them, in order.
    :param evidence: What they are looked at against.
    """
    installed = installed_of(evidence.lock)
    software = software_of(evidence.software, installed, evidence.python)
    done = Divergence(
        software=software,
        differences=[*software_differences(software), *data_differences(evidence.data, evidence.datasets)],
    )
    points = points_of(entries)
    # A paper can be long and a tutorial can have many calls, so what it states for a name is read once, and the
    # arguments of a tutorial up to a point once, whatever the number of claims that come to them
    stated_of = cache(lambda name: stated_for(name, evidence.paper or ""))
    arguments: dict[tuple[str, int | None], list[dict[str, Any]]] = {}
    for entry in entries:
        if entry["status"] not in (reproducing.PARTLY, reproducing.NOT_REPRODUCED) or entry["link"] is None:
            continue
        path = entry["link"]["tutorial"]["path"]
        detail = evidence.details.get(path)
        found: list[dict[str, Any]] = []
        until = entry["link"]["call"] if entry["link"]["source"] == reproducing.CALL else None
        point = points.get(path) if parts(entry) else None
        if point is not None and point["first"]["call"] is not None:
            until = point["first"]["call"]
        if detail is not None:
            found += runs_differences(detail, evidence.text_of(path))
            if (path, until) not in arguments:
                arguments[path, until] = argument_differences(detail, until, evidence.paper, stated_of)
            found += deepcopy(arguments[path, until])
        done.claims.append(
            {
                "id": entry["id"],
                "quote": entry["quote"],
                "value": entry["value"],
                "status": entry["status"],
                "tutorial": path,
                "point": ({**point, "text": point_text(path, point)} if point is not None else None),
                "differences": found,
            }
        )

    return done
