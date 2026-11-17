"""What the independent checks of a PaperAgent's tools leave in its directory, and the tier that comes of them.

checks/independent/<tool>/<kind>.json is one check of one tool: which kind of evidence it is, whether it passed, failed,
or was not obtained, what it came to in a sentence, and what it was made of. Each is bound to what it was made of: the
tool's wrapper (by its hash), the commit of the code, the image of the environment, and the reference run. A check that
is bound to something that is not what is kept now is stale, is shown as stale, and counts for nothing. A check against
the numbers that the paper reports is also bound to those numbers, by a hash of them with the sentences they are from,
so that a paper that is read again, and gives other numbers, leaves it stale.

The tier of a tool follows from these files and from nothing else. A tool of tier A that has two kinds of checks that
passed and none that failed, all of them of what is kept now, is of tier B. No model decides it: a model says nothing
that is kept here, and a record that is not in the shape that is written, or is of another tool or kind, counts for
nothing. What tier B says is that the tool did more than give again what its tutorial got; it does not say that what
the tool gives is right.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from virtual_lab.paperagents import checking, wrappers
from virtual_lab.paperagents.repository import COMMIT
from virtual_lab.paperagents.stock import matches
from virtual_lab.server import paperagent_reading as kept_reading
from virtual_lab.server import paperagent_tools as kept_tools
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import write_atomically

# What a record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1
# The most that is kept of one check, which is far more than one is
MAX_RECORD_BYTES = 1 << 20
# What a check that is not for what is kept now is shown as, and what a kind that was not checked is shown as
STALE = "stale"
NOT_RUN = "not_run"
SHOWN_STATUSES = (*checking.STATUSES, STALE, NOT_RUN)
SHA256 = re.compile(r"[0-9a-f]{64}")

RECORD = {
    "schema": int,
    "tool": str,
    "kind": str,
    "status": str,
    "summary": str,
    "details": dict,
    "checked_at": str,
    "seconds": (int, float),
    "limits": dict,
    "wrapper_sha256": str,
    "commit": str,
    "image_id": str,
    "reference": {"started_at": str, "finished_at": str},
}


def independent_path(directory: Path) -> Path:
    return kept_tools.checks_path(directory) / kept_tools.INDEPENDENT_DIR


def record_path(directory: Path, name: str, kind: str) -> Path:
    """Where a check is kept.

    :raises ValueError: If it is not the name of a tool, or not a kind of check.
    """
    if not kept_tools.is_name(name) or kind not in checking.KINDS:
        raise ValueError("That is not a tool and a kind of check")

    return independent_path(directory) / name / f"{kind}.json"


def is_record(value: Any, name: str, kind: str) -> bool:
    """Whether what a file holds is the check of this kind of this tool, in the shape that is kept."""
    return (
        matches(RECORD, value)
        and value["schema"] == SCHEMA
        and value["tool"] == name
        and value["kind"] == kind
        and value["status"] in checking.STATUSES
        and COMMIT.fullmatch(value["commit"]) is not None
        and value["image_id"].startswith("sha256:")
        and SHA256.fullmatch(value["wrapper_sha256"]) is not None
        and (value["kind"] != checking.PAPER_NUMBERS or SHA256.fullmatch(str(value.get("claims_sha256"))) is not None)
    )


def load(directory: Path, name: str, kind: str) -> dict[str, Any] | None:
    """One check as it is kept, whatever it is bound to, or None if there is none or what is there is not one."""
    try:
        path = record_path(directory, name, kind)
        folder = path.parent
        if folder.is_symlink() or path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
            return None
        value = read_json(path)
    except (ValueError, OSError):
        return None

    return value if is_record(value, name, kind) else None


def keep(directory: Path, record: dict[str, Any]) -> None:
    """Keeps a check in place of one of the same kind of the same tool.

    :raises ValueError: If it is not for a tool and a kind of check.
    """
    path = record_path(directory, record["tool"], record["kind"])
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomically(path, json.dumps(record, indent=4).encode("utf-8"))


def made_of(tool: dict[str, Any], kept: dict[str, Any]) -> dict[str, Any]:
    """What a check of a tool is bound to now: the wrapper, the commit, the image, and the reference run.

    :param tool: The tool as it is kept.
    :param kept: The account of the making of the tools, which is of the commit, image, and reference run that are kept.
    """
    return {
        "wrapper_sha256": tool["wrapper_sha256"],
        "commit": kept["commit"],
        "image_id": kept["image_id"],
        "reference": dict(kept["reference"]),
    }


def numbers_sha256(claims: Sequence[dict[str, Any]]) -> str:
    """What a check against the paper's numbers is bound to: each number that the paper reports, with its sentence."""
    shown = sorted((claim["id"], claim["value"], claim["quote"]) for claim in claims)

    return hashlib.sha256(json.dumps(shown).encode("utf-8")).hexdigest()


def record_of(
    tool: dict[str, Any],
    kept: dict[str, Any],
    kind: str,
    outcome: checking.Outcome,
    at: str,
    seconds: float,
    limits: dict[str, int],
    claims: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A check as it is kept, bound to what it was made of.

    :param claims: The numbers that the paper reports, which a check against them was made with.
    """
    return {
        "schema": SCHEMA,
        "tool": tool["name"],
        "kind": kind,
        "status": outcome.status,
        "summary": outcome.summary,
        "details": outcome.details,
        "checked_at": at,
        "seconds": round(seconds, 1),
        "limits": limits,
        **made_of(tool, kept),
        **({"claims_sha256": numbers_sha256(claims)} if kind == checking.PAPER_NUMBERS and claims is not None else {}),
    }


def is_current(
    record: dict[str, Any], tool: dict[str, Any], kept: dict[str, Any], claims_sha256: str | None = None
) -> bool:
    """Whether a check is bound to the tool as it is, in the commit, the image, and the reference run that are kept, and
    if it is against the numbers that the paper reports, to the numbers that are read from it now.

    :param claims_sha256: What the numbers that the paper reports are now, which is none if there are none.
    """
    return all(record[key] == value for key, value in made_of(tool, kept).items()) and (
        record["kind"] != checking.PAPER_NUMBERS
        or (claims_sha256 is not None and record.get("claims_sha256") == claims_sha256)
    )


def evidence_of(
    directory: Path, tool: dict[str, Any], kept: dict[str, Any], details: bool = True
) -> list[dict[str, Any]]:
    """Each kind of check of a tool, in order, with how it went: passed, failed, not obtained, stale if it is of
    something that is not kept now, or not run if there is none.

    :param tool: The tool as it is kept.
    :param kept: The account of the making of the tools.
    :param details: Whether what each check was made of is given, which is much more than what it came to.
    """
    found = []
    claims = kept_reading.number_claims(directory)
    numbers = numbers_sha256(claims) if claims else None
    for kind in checking.KINDS:
        record = load(directory, tool["name"], kind)
        entry: dict[str, Any] = {
            "kind": kind,
            "title": checking.KIND_INFO[kind]["title"],
            "what": checking.KIND_INFO[kind]["what"],
            "status": NOT_RUN,
            "summary": "It has not been checked this way.",
            "file": None,
            "checked_at": None,
            "was": None,
        }
        if record is not None:
            current = is_current(record, tool, kept, numbers)
            entry.update(
                status=record["status"] if current else STALE,
                summary=(
                    record["summary"]
                    if current
                    else "It was checked for a wrapper, a commit of the code, an image of the environment, a "
                    "reference run, or numbers of the paper that are not what is kept now, so it counts for nothing. "
                    "Check again."
                ),
                file=f"{kept_tools.CHECKS_DIR}/{kept_tools.INDEPENDENT_DIR}/{tool['name']}/{kind}.json",
                checked_at=record["checked_at"],
                was=None if current else record["status"],
            )
            if details:
                entry["details"] = record["details"]
                entry["limits"] = record["limits"]
                entry["seconds"] = record["seconds"]
        found.append(entry)

    return found


def tier_of(tool: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    """The tier that a tool is of, from how its checks went: B if it is of tier A and two kinds passed and none failed,
    and what it was made as if not. Checks that are stale are not counted, either way."""
    passed = sum(1 for entry in evidence if entry["status"] == checking.PASSED)
    failed = any(entry["status"] == checking.FAILED for entry in evidence)
    if tool["tier"] == wrappers.TIER and passed >= checking.KINDS_FOR_B and not failed:
        return checking.TIER_B

    return str(tool["tier"])


def tool_summary(directory: Path, tool: dict[str, Any], kept: dict[str, Any], details: bool = False) -> dict[str, Any]:
    """A tool as a page lists it for its checks: its tier as it was made, its tier now, and each kind of check."""
    evidence = evidence_of(directory, tool, kept, details)

    return {
        "name": tool["name"],
        "module": tool["repo"]["module"],
        "function": tool["repo"]["function"],
        "made_as": tool["tier"],
        "tier": tier_of(tool, evidence),
        "passed": [entry["kind"] for entry in evidence if entry["status"] == checking.PASSED],
        "evidence": evidence,
    }


def with_tier(directory: Path, tool: dict[str, Any], kept: dict[str, Any]) -> dict[str, Any]:
    """A tool as it is given to a conversation, which is of the tier that its checks come to, and says which kinds
    passed."""
    summary = tool_summary(directory, tool, kept)

    return {**tool, "tier": summary["tier"], "passed": summary["passed"]}


def forget(directory: Path) -> None:
    """Removes every check of every tool."""
    kept_tools.forget_independent(directory)
