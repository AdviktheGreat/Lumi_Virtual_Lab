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

A candidate that has been built, or that building could not go on with, says which, and why: what stands in the way of
a method, in words, and whether it is for the person to say something (waiting), something that is so of the method
and not for anyone to change here (blocked), something that went wrong that may not the next time it is tried
(failed), or something that was not got to (pending). That a method is built is not kept here, since it is the
PaperAgent that is looked at: a method is built if its PaperAgent's tools are made. What is kept is only the last thing
that stood in the way, and what the person said to it.

The person may say what their data is, as the scope check of a PaperAgent takes it (its species, tissue, assay, input
format, and sample size with what that counts), and it is kept as they said it. What is put against the method card of
each method's paper is worked out from it and the card as they are, each time, and is not kept; what is kept is only the
person's saying to go on with a method whose card the data is outside of, with the data and the card's words that they
were shown, so that it is not taken for going on with anything else.

The person may also say where the right answers are: a table of theirs on the Data page, the column of it that has the
answer for each row, and, if the rows are not in the order of the data, the column that says what each is the answer
to. Only those names are kept, and not the table, which stays where the Data page has it and is read from there.

A file that is not in the shape that a bake-off is kept in is not used, as it may not be if it was edited.
"""

import json
import math
import re
from pathlib import Path
from typing import Any

from virtual_lab.paperagents import labelling, scope
from virtual_lab.paperagents.stock import matches
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server.errors import ApiError
from virtual_lab.server.paperagents import check_paper, check_repo, passes, same_paper
from virtual_lab.server.workspace import has_control_character, read_json
from virtual_lab.utils import MeetingUsage, compute_token_cost, write_atomically

RECORD_FILE = "bakeoff.json"
# What a record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 4
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
# Where a paper that a search found can be read, by the service that found it
FOUND_PAGES = {"europepmc": "https://europepmc.org/", "arxiv": "https://arxiv.org/"}
# What stands in the way of a method that is being built, and at which step of building it
BUILD_STATES = ("waiting", "blocked", "failed", "pending")
BUILD_STEPS = ("agent", "code", "paper", "preflight", "environment", "tutorials", "tools")
MAX_REASON_CHARS = 600
WHY = re.compile(r"[a-z_]{1,30}")
COMMIT = re.compile(r"[0-9a-f]{7,64}")
KEY = re.compile(r"[0-9a-f]{64}")
# What the person may say of their data, which is what a PaperAgent's scope check takes
DESCRIBED_WORDS = ("species", "tissue", "assay", "input_format", "sample_unit")
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
BUILD = {
    "state": str,
    "step": str,
    "why": str,
    "reason": str,
    "at": str,
    "go_on": (str, None),
}
WENT_ON = {"key": str, "at": str}
DESCRIBED = {
    "species": str,
    "tissue": str,
    "assay": str,
    "input_format": str,
    "sample_size": int,
    "sample_unit": str,
    "at": str,
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
    "build": (BUILD, None),
    "went_on": (WENT_ON, None),
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
    "described": (DESCRIBED, None),
    "labels": ({"own": str, "column": str, "id_column": (str, None)}, None),
    "limit": NUMBER,
    "spent": NUMBER,
    "cost_known": bool,
    "shortlist": (SHORTLIST, None),
    "candidates": [CANDIDATE],
}


def printable(text: str) -> str:
    """Text without what is not text in it, which a paper's title from a service may have, on one line."""
    return " ".join("".join(char if char.isprintable() else " " for char in text).split())


def is_amount(value: Any) -> bool:
    return isinstance(value, NUMBER) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def page_of(source: str, url: str) -> str:
    """The page where a paper that a search found can be read, if it is one of the service's, and none if it is not: a
    page shows it as a link, so it must be at the service that found the paper, and has no space or control character
    in it."""
    prefix = FOUND_PAGES.get(source)
    if prefix is None or not url.startswith(prefix) or any(not char.isprintable() or char.isspace() for char in url):
        return ""

    return url


def is_found(found: dict[str, Any]) -> bool:
    """Whether what is kept of where a candidate was found is what a search gives: a service that there is, a page of
    it or none, and words with no control character in them."""
    return (
        found["source"] in FOUND_PAGES
        and (found["url"] == "" or page_of(found["source"], found["url"]) == found["url"])
        and not has_control_character(found["credit"])
        and not has_control_character(found["venue"])
    )


def is_build(build: dict[str, Any]) -> bool:
    """Whether what is kept of what stands in the way of a method is that: one of the states and steps there are, a
    reason in words, and, if the person said to go on, the commit of the code that they said it of."""
    return (
        build["state"] in BUILD_STATES
        and build["step"] in BUILD_STEPS
        and WHY.fullmatch(build["why"]) is not None
        and 0 < len(build["reason"]) <= MAX_REASON_CHARS
        and not has_control_character(build["reason"])
        and not has_control_character(build["at"])
        and (build["go_on"] is None or COMMIT.fullmatch(build["go_on"]) is not None)
    )


def facts_of(described: dict[str, Any]) -> dict[str, Any]:
    """What the person said of their data, as a scope check takes it: without when they said it."""
    return {key: value for key, value in described.items() if key != "at"}


def is_described(described: dict[str, Any]) -> bool:
    """Whether what is kept of what the data is, is what a scope check takes: something is said, in words, and the
    size, if one is said, is a whole number with what it counts."""
    try:
        scope.clean(facts_of(described))
    except ValueError:
        return False

    return not has_control_character(described["at"]) and all(
        not has_control_character(described[key]) for key in DESCRIBED_WORDS
    )


def is_column(name: str) -> bool:
    """Whether a name of a column can be looked for in a header, which is read without the space round its names."""
    return name == name.strip() and 0 < len(name) <= labelling.MAX_COLUMN_CHARS and not has_control_character(name)


def is_labels(labels: dict[str, Any]) -> bool:
    """Whether what is kept of where the right answers are is that: a piece of data by a name, a column of the right
    answers, and, if there is one, a different column that says what each is the answer to."""
    return (
        0 < len(labels["own"])
        and not has_control_character(labels["own"])
        and is_column(labels["column"])
        and (
            labels["id_column"] is None or (is_column(labels["id_column"]) and labels["id_column"] != labels["column"])
        )
    )


def is_went_on(went_on: dict[str, Any]) -> bool:
    return KEY.fullmatch(went_on["key"]) is not None and not has_control_character(went_on["at"])


def is_candidate(value: dict[str, Any]) -> bool:
    """Whether what a record holds as a candidate is one: its paper is a DOI or a link, as it is kept, its code and
    suggestions are addresses of code, and, if a search found it, it has the words of a model and where it was found,
    and, if the person added it, it has neither."""
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
        and not has_control_character(value["title"])
        and (value["repo"] is None or passes(check_repo, value["repo"]))
        and len(value["suggested"]) <= MAX_SUGGESTED
        and all(passes(check_repo, address) for address in value["suggested"])
        and value["added_by"] in (BY_SEARCH, BY_PERSON)
        and (value["fit"] is not None) == (value["added_by"] == BY_SEARCH)
        and (value["found"] is not None) == (value["added_by"] == BY_SEARCH)
        and (value["found"] is None or is_found(value["found"]))
        and (value["build"] is None or is_build(value["build"]))
        and (value["went_on"] is None or is_went_on(value["went_on"]))
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
        and (value["described"] is None or is_described(value["described"]))
        and (value["labels"] is None or is_labels(value["labels"]))
        and len(value["candidates"]) <= MAX_CANDIDATES
        and len(set(ids)) == len(ids)
        and all(is_candidate(candidate) for candidate in value["candidates"])
        and (shortlist is None or shortlist["written_by"] in WRITERS)
    )


def upgraded(value: Any) -> Any:
    """What an earlier version kept, as this one keeps it: the first, which had no building, has none said of any
    candidate, the first two, which had no saying what the data is, have none and no one gone on with, and the first
    three, which had no saying where the right answers are, have none. What is not a record of one of those versions
    is as it was."""
    if (
        not isinstance(value, dict)
        or value.get("schema") not in (1, 2, 3)
        or not isinstance(value.get("candidates"), list)
    ):
        return value
    earlier = value["schema"]

    def made(each: Any) -> Any:
        if not isinstance(each, dict):
            return each

        return {**({"build": None} if earlier == 1 else {}), **each, **({"went_on": None} if earlier <= 2 else {})}

    return {
        **value,
        "schema": SCHEMA,
        **({"described": None} if earlier <= 2 else {}),
        "labels": None,
        "candidates": [made(each) for each in value["candidates"]],
    }


def load(directory: Path) -> dict[str, Any] | None:
    """The bake-off in a directory, or None if there is none or what is there is not one."""
    path = directory / RECORD_FILE
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
            return None
        value = upgraded(read_json(path))
    except OSError:
        return None

    return value if is_record(value) else None


def keep(directory: Path, record: dict[str, Any]) -> None:
    write_atomically(directory / RECORD_FILE, json.dumps(record, indent=4).encode("utf-8"))


def new_record(
    title: str,
    task: str,
    data: str | None,
    limit: float,
    described: dict[str, Any] | None = None,
    labels: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A bake-off with nothing spent and nobody in the running."""
    return {
        "schema": SCHEMA,
        "title": title,
        "created_at": utc_timestamp(),
        "task": task,
        "data": {"own": data} if data is not None else None,
        "described": described,
        "labels": labels,
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


def charge_amount(record: dict[str, Any], cost: float, known: bool = True) -> dict[str, Any]:
    """The bake-off with an amount that a step spent added to what has been spent, which is not known if the step's is
    not, and is not known again after that."""
    return {**record, "spent": round(record["spent"] + cost, 6), "cost_known": record["cost_known"] and known}


def charge(record: dict[str, Any], usage: MeetingUsage) -> dict[str, Any]:
    """The bake-off with what a step used added to what has been spent."""
    cost, known = cost_of(usage)

    return charge_amount(record, cost, known)


def standing_of(
    candidate: dict[str, Any], agent: dict[str, Any] | None, building: dict[str, Any] | None
) -> dict[str, Any]:
    """Where a method stands: being built, built, stood in the way of, or not yet gone at. It is made from what there is
    now, and not from what was kept of it, so that a PaperAgent that was built by hand, or one whose environment was
    taken away, is as it is.

    :param agent: The PaperAgent of the method's paper, as a page is given one, if there is one.
    :param building: The job that is building the bake-off's methods, if there is one, as it is given to a page.
    """
    progress = building["progress"] if building is not None else {}
    if progress.get("candidate") == candidate["id"]:
        return {"state": "building", "step": progress.get("step"), "reason": building["message"] if building else ""}
    if agent is not None and agent["steps"]["tools"] == "done" and agrees(candidate["repo"], agent["repo"]):
        return {"state": "built", "step": None, "reason": "Its tools are made."}
    if candidate["build"] is not None:
        return {key: candidate["build"][key] for key in ("state", "step", "why", "reason", "at")}

    return {"state": "new", "step": None, "reason": ""}


def agrees(said: str | None, has: str | None) -> bool:
    """Whether a PaperAgent's code is the code that the bake-off says a method has: it is if the bake-off says none, and
    otherwise if they are the same address. A PaperAgent that was built from other code is not the method that was
    asked for, and building asks the person which is."""
    return said is None or said == has


def agent_for(paper: dict[str, Any], agents: list[tuple[Path, dict[str, Any]]]) -> tuple[str, dict[str, Any]] | None:
    """The PaperAgent of a paper, with its id, from the PaperAgents there are as `kept` lists them, if there is one."""
    return next(((directory.name, agent) for directory, agent in agents if same_paper(paper, agent["paper"])), None)
