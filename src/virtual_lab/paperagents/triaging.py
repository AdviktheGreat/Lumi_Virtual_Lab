"""Triage of a listing of papers: which of them are worth building first, from what a look at their code says, before
anything is built.

A listing of preprints is long, and most of its papers have no code that tools could be made from. Building a paper's
environment and running its tutorials costs minutes of a machine and, for the tools, a model's requests, so it is not
done to every paper to find out. What can be known sooner is what the code looks like: whether the paper says where it
is, whether it can be fetched, whether it has a license, tutorials, a file that says what to install, and no need of a
GPU. These are the checks of the pre-flight, and here they are made of each paper's code, which is fetched at one commit
and read, with nothing run and no model asked, and put in an order.

The order is by the answer of the pre-flight (go, then ask, then no-go), then, among those that have the same, by what
there is the least of to weigh (blocks, warnings, what is not known), by how many tutorials there are, which are what
tools are made from, and last by the guess of what making the tools would cost. Papers whose code was not looked at come
after all of those, with the reason: the code could not be fetched, was larger than the most that is fetched, or was
beyond the most that are looked at; and those that say nowhere where their code is come last, in the order of the
listing.

It is an order of how likely the code is to give tools without trouble, and of nothing else. It does not say that a
paper is good, that its method works, that its numbers hold, or that its code is the code of the paper: the address is
the first that the abstract gives, or the one that a person gave, and a paper whose code is only named in its full text
is among those with none. The check was made of what the files say, so it can be wrong in either direction.
"""

import math
import re
from collections.abc import Callable
from typing import Any

# What a paper's entry comes to, in the order that it is ranked in
TIERS = ("go", "ask", "no-go", "not_looked_at", "no_code")
# How many other addresses of code that an abstract gives are said, and how long what a check says is, as it is kept
MAX_OTHER_CODES = 3
MAX_DETAIL_CHARS = 300
MAX_LANGUAGES = 3

MEANING = {
    "ranking": (
        "Papers are ordered by what a look at their code says of whether tools could be made from it, and by nothing "
        "else. It does not say that a paper is good, that its method works, or that its numbers hold."
    ),
    "order": (
        "By the answer of the pre-flight, then by the fewest blocks, warnings, and things not known, then by the most "
        "tutorials, then by the lowest guess of the cost, then as listed."
    ),
    "tiers": {
        "go": "Nothing in the code's files stands in the way of making tools from it.",
        "ask": "Some things in the files are to weigh first, such as no license, no tutorials, or nothing to say what "
        "to install.",
        "no-go": "Something in the files stops it, such as no code that runs here, or a need of a GPU.",
        "not_looked_at": "Its code was not looked at: it could not be fetched, was too large, or was beyond the most "
        "that are looked at. The reason is given.",
        "no_code": "No address of code was found in the abstract, and none was given. The paper's full text may say.",
    },
    "checked": "The files were read and nothing was run, so a check can be wrong in either direction.",
}

# Not preceded by what makes the host part of another word or address (notgithub.com, evil.com/github.com, a@github.com)
ADDRESS = re.compile(
    r"(?<![\w./@-])(?:https?://)?(?:www\.)?(?:github\.com|gitlab\.com|bitbucket\.org|codeberg\.org)/[^\s<>\"'`]+",
    re.IGNORECASE,
)


def project_links(text: str, as_repo: Callable[[str], str | None]) -> list[str]:
    """The projects that a text gives the address of, each once, in the order they are given, as an agent keeps them.

    :param as_repo: Gives the address of the project that a link is to in the form that is kept, or None if it is not
        to one.
    """
    found: dict[str, None] = {}
    for match in ADDRESS.finditer(text):
        project = as_repo(match.group(0).rstrip(".,;:!?)]}"))
        if project is not None:
            found.setdefault(project, None)

    return list(found)


def choose_code(
    given: str | None, abstract: str, as_repo: Callable[[str], str | None]
) -> tuple[str | None, str | None, list[str]]:
    """Which address is the paper's code: the one the person gave, or else the first that the abstract does.

    :return: The address, whose it is (person or abstract), and the other addresses that the abstract gives.
    """
    shown = project_links(abstract, as_repo)
    if given is not None:
        return given, "person", [url for url in shown if url != given][:MAX_OTHER_CODES]
    if shown:
        return shown[0], "abstract", shown[1:][:MAX_OTHER_CODES]

    return None, None, []


def brief(
    entry: dict[str, Any], position: int, code: str | None, source: str | None, others: list[str]
) -> dict[str, Any]:
    """What every record says of the paper, whether or not its code was looked at."""
    doi = entry.get("doi")

    return {
        "position": position,
        "doi": doi,
        "title": entry["title"],
        "date": entry.get("date") or None,
        "category": entry.get("category") or None,
        "paper": {"kind": "doi", "doi": doi} if doi else None,
        "code": code,
        "code_from": source,
        "other_codes": others,
    }


def unlooked(
    entry: dict[str, Any], position: int, code: str | None, source: str | None, others: list[str], why: str
) -> dict[str, Any]:
    """A paper whose code was not looked at: it has none, or could not be had, or was not got to."""
    return {
        **brief(entry, position, code, source, others),
        "tier": "not_looked_at" if code is not None else "no_code",
        "why": why,
        "verdict": None,
        "checks": [],
        "tutorials": None,
        "estimate": None,
        "stock": None,
    }


def looked(
    entry: dict[str, Any],
    position: int,
    code: str,
    source: str | None,
    others: list[str],
    commit: str,
    stock: dict[str, Any],
    checked: dict[str, Any],
) -> dict[str, Any]:
    """A paper whose code was fetched and read.

    :param commit: The commit that was fetched, which is what the checks are of.
    :param stock: What was found in the code.
    :param checked: What the pre-flight said of it.
    """
    license_found = stock["license"]
    estimate = checked["estimate"]

    return {
        **brief(entry, position, code, source, others),
        "tier": checked["verdict"],
        "why": checked["summary"],
        "verdict": checked["verdict"],
        "checks": [
            {"id": item["id"], "status": item["status"], "detail": item["detail"][:MAX_DETAIL_CHARS]}
            for item in checked["checks"]
        ],
        "tutorials": stock["tutorials"]["count"],
        "estimate": {"low": estimate["low"], "high": estimate["high"], "tutorials": estimate["tutorials"]},
        "stock": {
            "commit": commit,
            "files": stock["files"],
            "bytes": stock["bytes"],
            "languages": [language["name"] for language in stock["languages"][:MAX_LANGUAGES]],
            "license": license_found["name"] if license_found is not None else None,
        },
    }


def sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
    """What a record is ordered by: its tier, what there is to weigh, what there is of value, and then the cost."""
    counts: dict[str, int] = {}
    for item in record["checks"]:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    estimate = record["estimate"]
    cost = estimate["high"] if estimate is not None and estimate["high"] is not None else math.inf

    return (
        TIERS.index(record["tier"]),
        counts.get("block", 0),
        counts.get("warn", 0),
        counts.get("unknown", 0),
        -(record["tutorials"] or 0),
        cost,
        record["position"],
    )


def rank(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The records in order, each with its place from 1."""
    return [{**record, "rank": place} for place, record in enumerate(sorted(records, key=sort_key), 1)]


def counts_of(records: list[dict[str, Any]]) -> dict[str, int]:
    """How many papers there are of each tier, and of all."""
    found = {tier: sum(1 for record in records if record["tier"] == tier) for tier in TIERS}

    return {"papers": len(records), **found}
