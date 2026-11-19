"""What a bake-off leaves in the workspace.

A bake-off is the question of which method to use for a task: what the person wants done, the data of theirs it is to be
done on, the methods that are in the running, and one limit on what the whole of it may spend. It is kept in a directory
of its own in the workspace's bakeoffs/, in bakeoff.json, and not in any PaperAgent's directory, since it is of many
papers, one for each method, and a PaperAgent is of one. A method that is built becomes a PaperAgent of its paper like
any other, and the bake-off says which by the paper, which is what an agent is told from others by, and keeps nothing of
it, so that an agent that was made, changed, or taken away since is as it is and not as the bake-off last saw it.

The limit is kept with what has been spent of it. Every step of a bake-off that asks a model is given what is left, and
what each step used is added when it ends, whether it came to its end or was stopped or failed, so that the limit is
one for all of them, and for the whole of the time, and is not set again by each step or each time that the bake-off is
carried on. A response that does not say what it used makes what was spent not known, which is kept, and no model is
asked after it, since a limit cannot be kept without it.

A candidate is a method that is in the running: the paper it is of, which is a DOI or a link, what it is called, where
its code is if the person said, and how it came to be there. One that a search found has the words of its abstract
that a model went by, which a program found in the abstract, and the addresses of code that the abstract has in it,
which are suggestions and are not the address of its code until the person says so. One that the person added has
neither.

A file that is not in the shape that a bake-off is kept in is not used, as it may not be if it was edited.
"""

import json
import math
import re
from pathlib import Path
from typing import Any

from virtual_lab.paperagents.stock import matches
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server.errors import ApiError
from virtual_lab.server.paperagents import check_paper, check_repo, passes
from virtual_lab.server.workspace import has_control_character, read_json
from virtual_lab.utils import MeetingUsage, compute_token_cost, write_atomically

RECORD_FILE = "bakeoff.json"
# What a record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1
MAX_RECORD_BYTES = 2 << 20
MAX_BAKEOFFS = 50
MAX_CANDIDATES = 12
MAX_SUGGESTED = 5
MAX_TASK_CHARS = 2000
MAX_TITLE_CHARS = 120
MAX_NAME_CHARS = 200
MAX_NOTES = 10
MAX_NOTE_CHARS = 400
CANDIDATE_ID = re.compile(r"[0-9a-f]{8}")
# How a candidate came to be in the running
BY_SEARCH = "search"
BY_PERSON = "person"
# Who wrote the searches
WRITERS = ("model", "person")
# Why a choice of a model did not become a candidate, which a shortlist counts
DROPPED = ("not_shown", "twice", "quote", "more", "already", "no_room")

NUMBER = (int, float)
FOUND = {
    "source": str,
    "url": str,
    "credit": str,
    "venue": str,
    "year": (int, None),
    "cited_by": int,
    "preprint": bool,
    "full_text": (bool, None),
}
CANDIDATE = {
    "id": str,
    "name": str,
    "paper": dict,
    "title": str,
    "repo": (str, None),
    "suggested": [str],
    "added_by": str,
    "added_at": str,
    "found": (FOUND, None),
    "fit": ({"quote": str, "model": str}, None),
}
SHORTLIST = {
    "started_at": str,
    "finished_at": str,
    "model": str,
    "written_by": str,
    "queries": [str],
    "found": int,
    "total": int,
    "chosen": int,
    "added": int,
    "dropped": {reason: int for reason in DROPPED},
    "notes": [str],
    "complete": bool,
    "note": (str, None),
    "cost": NUMBER,
}
RECORD = {
    "schema": int,
    "title": str,
    "created_at": str,
    "task": str,
    "data": ({"own": str}, None),
    "limit": NUMBER,
    "spent": NUMBER,
    "cost_known": bool,
    "shortlist": (SHORTLIST, None),
    "candidates": [CANDIDATE],
}


def is_amount(value: Any) -> bool:
    return isinstance(value, NUMBER) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def is_candidate(value: dict[str, Any]) -> bool:
    """Whether what a record holds as a candidate is one: its paper is a DOI or a link, as it is kept, its code and
    suggestions are addresses of code, and it has the words of a model if a search found it and has none if the person
    added it."""
    paper = value["paper"]
    try:
        kept = check_paper(paper)
    except ApiError:
        return False

    return (
        CANDIDATE_ID.fullmatch(value["id"]) is not None
        and kept == paper
        and paper["kind"] != "file"
        and 0 < len(value["name"]) <= MAX_NAME_CHARS
        and not has_control_character(value["name"])
        and (value["repo"] is None or passes(check_repo, value["repo"]))
        and len(value["suggested"]) <= MAX_SUGGESTED
        and all(passes(check_repo, address) for address in value["suggested"])
        and value["added_by"] in (BY_SEARCH, BY_PERSON)
        and (value["fit"] is not None) == (value["added_by"] == BY_SEARCH)
    )


def is_record(value: Any) -> bool:
    """Whether what a file holds is a bake-off, in the shape that is kept."""
    if not matches(RECORD, value) or value["schema"] != SCHEMA:
        return False
    ids = [candidate["id"] for candidate in value["candidates"]]
    shortlist = value["shortlist"]

    return (
        0 < len(value["title"]) <= MAX_TITLE_CHARS
        and not has_control_character(value["title"])
        and 0 < len(value["task"]) <= MAX_TASK_CHARS
        and not has_control_character(value["task"])
        and is_amount(value["limit"])
        and is_amount(value["spent"])
        and len(value["candidates"]) <= MAX_CANDIDATES
        and len(set(ids)) == len(ids)
        and all(is_candidate(candidate) for candidate in value["candidates"])
        and (shortlist is None or shortlist["written_by"] in WRITERS)
    )


def load(directory: Path) -> dict[str, Any] | None:
    """The bake-off in a directory, or None if there is none or what is there is not one."""
    path = directory / RECORD_FILE
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
            return None
        value = read_json(path)
    except OSError:
        return None

    return value if is_record(value) else None


def keep(directory: Path, record: dict[str, Any]) -> None:
    write_atomically(directory / RECORD_FILE, json.dumps(record, indent=4).encode("utf-8"))


def new_record(title: str, task: str, data: str | None, limit: float) -> dict[str, Any]:
    """A bake-off with nothing spent and nobody in the running."""
    return {
        "schema": SCHEMA,
        "title": title,
        "created_at": utc_timestamp(),
        "task": task,
        "data": {"own": data} if data is not None else None,
        "limit": limit,
        "spent": 0.0,
        "cost_known": True,
        "shortlist": None,
        "candidates": [],
    }


def left_of(record: dict[str, Any]) -> float:
    """What may still be spent, which is none if what has been spent is not known."""
    return max(record["limit"] - record["spent"], 0.0) if record["cost_known"] else 0.0


def cost_of(usage: MeetingUsage) -> tuple[float, bool]:
    """What was spent of the requests that said what they used, and whether every request did."""
    known = usage.unreported_calls == 0
    try:
        spent = sum(
            compute_token_cost(
                model=model,
                input_token_count=each.input_tokens,
                output_token_count=each.output_tokens,
                cached_input_token_count=each.cached_input_tokens,
                cache_write_token_count=each.cache_write_tokens,
            )
            for model, each in usage.per_model.items()
        )
    except ValueError:
        return 0.0, False

    return float(spent), known


def charge(record: dict[str, Any], usage: MeetingUsage) -> dict[str, Any]:
    """The bake-off with what a step used added to what has been spent."""
    cost, known = cost_of(usage)

    return {**record, "spent": round(record["spent"] + cost, 6), "cost_known": record["cost_known"] and known}
