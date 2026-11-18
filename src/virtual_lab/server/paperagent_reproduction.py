"""What trying a PaperAgent's claims against what its tutorials gave leaves in its directory, and how it is shown.

checks/reproduction.json is the account of the trying: for each claim of the paper, whether it was reproduced, partly,
not, or not attempted, with why, and against what: the tutorial, the place in what it gave, the value that was kept
there, and the model that chose that place for the sentence. It is bound to what it was made of: the commit of the code,
the image of the environment, and the reference run, whose kept results the claims are held to, and the claims, by a
hash of them with their sentences. An account that is bound to something that is not what is kept now is stale, is shown
as stale, and counts for nothing: the tutorials were run again, or the paper was read again, and what was kept is no
longer of them.

Nothing here runs code. The tutorials were run by the reference run (paperagent_reference.py), and it is what it kept
that the claims are held to. A claim is listed whatever came of it, so that one that was not attempted says so, with
why, and is never shown as failed.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from virtual_lab.paperagents import reproducing
from virtual_lab.paperagents.repository import COMMIT
from virtual_lab.paperagents.stock import matches
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_reference as kept_reference
from virtual_lab.server.jobs import Job
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import write_atomically

RECORD_FILE = "reproduction.json"
# What a record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1
# The most that is kept of the account, which is far more than one is
MAX_RECORD_BYTES = 8 << 20
# What a claim of an account that is not for what is kept now is shown as
STALE = "stale"
NOT_TRIED = "not_tried"
SHA256 = re.compile(r"[0-9a-f]{64}")

ENTRY = {
    "id": str,
    "kind": str,
    "value": str,
    "quote": str,
    "anchor": (dict, None),
    "figures": [str],
    "status": str,
    "reason": (str, None),
    "summary": str,
    "link": (dict, None),
    "considered": int,
    "ambiguous": int,
}
RECORD = {
    "schema": int,
    "commit": str,
    "image_id": str,
    "reference": {"started_at": str, "finished_at": str},
    "claims_sha256": str,
    "started_at": str,
    "finished_at": (str, None),
    "complete": bool,
    "model": str,
    "cost": (int, float, None),
    "limits": dict,
    "requests": int,
    "more": int,
    "limit": (str, None),
    "notes": [str],
    "claims": [ENTRY],
}


def record_path(directory: Path) -> Path:
    return directory / "checks" / RECORD_FILE


def is_record(value: Any) -> bool:
    """Whether what a file holds is the account of the trying of the claims, in the shape that is kept, with each claim
    having a status and a reason that are ones, and a claim that is not attempted having a reason."""
    return (
        matches(RECORD, value)
        and value["schema"] == SCHEMA
        and COMMIT.fullmatch(value["commit"]) is not None
        and value["image_id"].startswith("sha256:")
        and SHA256.fullmatch(value["claims_sha256"]) is not None
        and all(
            entry["status"] in reproducing.STATUSES
            and (entry["reason"] is None or entry["reason"] in reproducing.REASONS)
            and (entry["status"] == reproducing.NOT_ATTEMPTED) == (entry["reason"] is not None)
            for entry in value["claims"]
        )
    )


def load(directory: Path) -> dict[str, Any] | None:
    """The account as it is kept, whatever it is bound to, or None if there is none or what is there is not one."""
    path = record_path(directory)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
            return None
        value = read_json(path)
    except OSError:
        return None

    return value if is_record(value) else None


def keep(directory: Path, record: dict[str, Any]) -> None:
    path = record_path(directory)
    path.parent.mkdir(exist_ok=True)
    write_atomically(path, json.dumps(record, indent=4).encode("utf-8"))


def forget(directory: Path) -> None:
    """Removes the account, if there is one."""
    record_path(directory).unlink(missing_ok=True)


def claims_sha256(claims: Sequence[dict[str, Any]]) -> str:
    """What the account is bound to of the paper: each claim, with its kind and number and sentence."""
    shown = sorted((claim["id"], claim["kind"], claim["value"], claim["quote"]) for claim in claims)

    return hashlib.sha256(json.dumps(shown).encode("utf-8")).hexdigest()


def made_of(reference: dict[str, Any]) -> dict[str, Any]:
    """What the account is bound to of the code: the commit, the image, and the reference run.

    :param reference: The account of the reference run that is kept, which came to its end.
    """
    return {
        "commit": reference["commit"],
        "image_id": reference["image_id"],
        "reference": {"started_at": reference["started_at"], "finished_at": reference["finished_at"]},
    }


def is_current(record: dict[str, Any], reference: dict[str, Any] | None, claims: Sequence[dict[str, Any]]) -> bool:
    """Whether the account is of the reference run and the claims that are kept now."""
    return (
        reference is not None
        and all(record[key] == value for key, value in made_of(reference).items())
        and record["claims_sha256"] == claims_sha256(claims)
    )


def record_of(
    reference: dict[str, Any],
    claims: Sequence[dict[str, Any]],
    done: Sequence[dict[str, Any]],
    model: str,
    cost: float | None,
    limits: dict[str, Any],
    started_at: str,
    finished_at: str | None,
    summary: reproducing.Reproduction | None = None,
) -> dict[str, Any]:
    """The account, bound to what it was made of.

    :param claims: Every claim that was read of the paper, which is what it is bound to.
    :param done: What came of each claim that has come to something.
    :param summary: What the trying came to, if it has come to its end.
    """
    return {
        "schema": SCHEMA,
        **made_of(reference),
        "claims_sha256": claims_sha256(claims),
        "started_at": started_at,
        "finished_at": finished_at,
        "complete": summary is not None,
        "model": model,
        "cost": round(cost, 6) if cost is not None else None,
        "limits": limits,
        "requests": summary.requests if summary is not None else 0,
        "more": summary.more if summary is not None else max(0, len(claims) - reproducing.MOST_CLAIMS),
        "limit": summary.limit if summary is not None else None,
        "notes": list(summary.notes) if summary is not None else [],
        "claims": list(done),
    }


def tutorials_of(directory: Path, reference: dict[str, Any], repo: Path) -> list[reproducing.Tutorial]:
    """The tutorials of the reference run that is kept, with what each gave if it ran to the end, and what each refers
    to, which is read from the code as text."""
    return reproducing.tutorials_of(
        reference,
        lambda tutorial: kept_reference.load_detail(directory, reference, tutorial),
        lambda path: reproducing.tutorial_text(repo, path),
    )


def table(
    claims: Sequence[dict[str, Any]], record: dict[str, Any] | None, current: bool
) -> tuple[list[dict[str, Any]], int]:
    """Every claim of the paper, in order, with what came of it: what the account says if it is of what is kept now, and
    stale if it is not. A claim that the account does not have is not attempted, because it has not been tried.

    :return: The claims, and how many there were beyond the most that are listed.
    """
    kept = {(entry["id"], entry["quote"]): entry for entry in (record["claims"] if record is not None else [])}
    shown = []
    for claim in claims[: reproducing.MOST_CLAIMS]:
        entry = kept.get((claim["id"], claim["quote"]))
        if entry is None:
            figures = reproducing.references_in(claim["quote"], reproducing.MOST_FIGURES)
            shown.append(reproducing.unattempted(claim, figures, NOT_TRIED))
        elif current:
            shown.append(entry)
        else:
            shown.append({**entry, "status": STALE, "was": entry["status"]})

    return shown, max(0, len(claims) - reproducing.MOST_CLAIMS)


def counts_of(shown: Sequence[dict[str, Any]]) -> dict[str, int]:
    return {status: sum(1 for claim in shown if claim["status"] == status) for status in (*reproducing.STATUSES, STALE)}


def summary_of(done: reproducing.Reproduction, model: str, cost: float | None) -> str:
    counts = reproducing.counts_of(done.claims)
    said = (
        f"Tried {len(done.claims)} claim{'s' if len(done.claims) != 1 else ''}: {counts[reproducing.REPRODUCED]} "
        f"reproduced, {counts[reproducing.PARTLY]} partly, {counts[reproducing.NOT_REPRODUCED]} not reproduced, "
        f"{counts[reproducing.NOT_ATTEMPTED]} not attempted."
    )
    if done.more:
        said += f" {done.more} more were not listed."
    if done.limit is not None:
        said += f" {done.limit}."
    if cost is not None and done.requests:
        said += f" Asking {model} cost ${cost:.4f}."

    return said


def reproduce_all(
    job: Job,
    directory: Path,
    reference: dict[str, Any],
    claims: Sequence[dict[str, Any]],
    picker: reproducing.Picker,
    repo: Path,
    limits: dict[str, Any],
) -> str:
    """The work of the job: reads what the tutorials gave, tries each claim, and keeps what has come of them after each
    request to a model, so that a job that is stopped keeps what it had. The account that was kept before is taken
    away when the job begins, as it is of another trying.

    :param reference: The account of the reference run that is kept, which came to its end.
    :param claims: Every claim that was read of the paper.
    :param picker: What chooses which place in what a tutorial gave a sentence is about.
    :param repo: The code that was fetched, which is read for what each tutorial refers to and never run.
    :raises StoppedError: If the job was stopped.
    """
    forget(directory)
    job.update("Reading what the tutorials gave")
    tutorials = tutorials_of(directory, reference, repo)
    started = utc_timestamp()

    def kept(done: list[dict[str, Any]]) -> None:
        keep(directory, record_of(reference, claims, done, picker.model, picker.spent(), limits, started, None))

    job.update("Trying the claims")
    done = reproducing.reproduce(claims, tutorials, picker, kept, job.stop.is_set)
    cost = picker.spent()
    keep(
        directory,
        record_of(reference, claims, done.claims, picker.model, cost, limits, started, utc_timestamp(), done),
    )
    summary = summary_of(done, picker.model, cost)
    job.log(summary)

    return summary
