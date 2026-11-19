"""What making variants of a PaperAgent's claims leaves in its directory, and how a variant is made as a job.

checks/variants.json holds the variants that a person asked for: each is a claim's call made again, in the environment,
with the arguments that they named changed, and what came of it (paperagents/varying.py). It is a file of its own, and
making a variant never writes to checks/reproduction.json, so what was said of whether a claim reproduced is never
changed by one. A variant is not the paper's result, and nothing here calls it one.

The record is bound to what the claims were tried against: the commit of the code, the image of the environment, the
reference run, the claims by a hash of them with their sentences, and the trying of the claims itself, which is the
time it began. A record that is bound to something that is not what is kept now is stale: the tutorials were run again,
the paper was read again, or the claims were tried again, and the place that a variant was read at is no longer one that
a claim is held to. It is not shown, and counts for nothing, and it is replaced by the next variant that is made.

A file that is not in the shape that a variant is kept in is not used, as it may not be if it was edited.
"""

import json
import re
import secrets
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import reference as referencing
from virtual_lab.paperagents import toolmaking as making
from virtual_lab.paperagents import varying
from virtual_lab.paperagents.repository import COMMIT
from virtual_lab.paperagents.stock import matches
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_reproduction as kept_reproduction
from virtual_lab.server.jobs import Job
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import write_atomically

RECORD_FILE = "variants.json"
# What a record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1
# The most that is kept of the variants, which is far more than are
MAX_RECORD_BYTES = 8 << 20
# How many variants are kept, the oldest going when a newer one is made beyond it
MOST_KEPT = 100
VARIANT_ID = re.compile(r"[0-9a-f]{12}")
SHA256 = re.compile(r"[0-9a-f]{64}")

NUMBER = (int, float)
ERROR = ({"type": str, "message": str}, None)
VARIANT = {
    "id": str,
    "made_at": str,
    "seconds": NUMBER,
    "limits": {"minutes": int, "repeats": int, "gigabytes": int},
    "note": (str, None),
    "claim": str,
    "quote": str,
    "number": str,
    "tutorial": {"id": str, "path": str},
    "call": int,
    "function": str,
    "where": str,
    "path": list,
    "changes": [{"name": str, "was": object, "now": object}],
    "claim_run": NUMBER,
    "control": {"verdict": str, "gave": (*NUMBER, None), "differences": [str], "error": ERROR},
    "variant": {
        "status": str,
        "gave": (*NUMBER, None),
        "values": [(*NUMBER, None)],
        "type": (str, None),
        "error": ERROR,
        "differences": [str],
    },
    "comparable": bool,
    "rounds_to_paper": (bool, None),
    "repeats": int,
    "tolerance": {"relative": NUMBER, "absolute": NUMBER},
    "text": str,
}
RECORD = {
    "schema": int,
    "commit": str,
    "image_id": str,
    "reference": {"started_at": str, "finished_at": str},
    "claims_sha256": str,
    "reproduction": {"started_at": str},
    "variants": [VARIANT],
}


def record_path(directory: Path) -> Path:
    return directory / "checks" / RECORD_FILE


def is_variant(value: dict[str, Any]) -> bool:
    """Whether what a record holds as a variant says what it came to in ways that agree: its status and its control are
    ones, a number is given when it gave one and only then, it is comparable only if its control matched and it gave a
    number, whether it rounds to the paper's is said only of a number that it gave, the changes are a few and each of a
    value that an argument can be given as, and it says what it is."""
    result, control, changes = value["variant"], value["control"], value["changes"]
    names = [each["name"] for each in changes]

    return (
        VARIANT_ID.fullmatch(value["id"]) is not None
        and (value["note"] is None or len(value["note"]) <= varying.MAX_NOTE_CHARS)
        and result["status"] in varying.STATUSES
        and control["verdict"] in varying.CONTROL_VERDICTS
        and (result["gave"] is not None) == (result["status"] == varying.GAVE)
        and (result["error"] is not None) == (result["status"] == varying.ERROR)
        and value["comparable"] == (control["verdict"] == varying.MATCH and result["status"] == varying.GAVE)
        and (value["rounds_to_paper"] is None or result["status"] == varying.GAVE)
        and 1 <= len(changes) <= varying.MOST_CHANGES
        and len(set(names)) == len(names)
        and all(len(name) <= varying.MAX_NAME_CHARS for name in names)
        and all(varying.is_plain(each["now"]) for each in changes)
        and all(
            isinstance(step, str) or (isinstance(step, int) and not isinstance(step, bool)) for step in value["path"]
        )
        and value["repeats"] >= 1
        and value["text"].endswith(varying.CLOSING)
    )


def is_record(value: Any) -> bool:
    """Whether what a file holds is the variants of a PaperAgent's claims, in the shape that is kept."""
    if not matches(RECORD, value) or value["schema"] != SCHEMA:
        return False
    ids = [variant["id"] for variant in value["variants"]]

    return (
        COMMIT.fullmatch(value["commit"]) is not None
        and value["image_id"].startswith("sha256:")
        and SHA256.fullmatch(value["claims_sha256"]) is not None
        and len(value["variants"]) <= MOST_KEPT
        and len(set(ids)) == len(ids)
        and all(is_variant(variant) for variant in value["variants"])
    )


def load(directory: Path) -> dict[str, Any] | None:
    """The variants as they are kept, whatever they are bound to, or None if there are none or what is there is not
    them."""
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
    """Removes the variants, if there are any."""
    record_path(directory).unlink(missing_ok=True)


def bound_to(reference: dict[str, Any], trying: dict[str, Any], claims: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """What a variant is bound to: the code, the environment, the reference run, the claims, and the trying of them.

    :param reference: The account of the reference run that is kept, which came to its end.
    :param trying: The account of the trying of the claims that is kept.
    """
    return {
        **kept_reproduction.made_of(reference),
        "claims_sha256": kept_reproduction.claims_sha256(claims),
        "reproduction": {"started_at": trying["started_at"]},
    }


def is_current(
    record: dict[str, Any],
    reference: dict[str, Any] | None,
    trying: dict[str, Any] | None,
    claims: Sequence[dict[str, Any]],
) -> bool:
    """Whether the variants are of the reference run, the claims, and the trying of them that are kept now."""
    if reference is None or trying is None:
        return False

    return all(record[key] == value for key, value in bound_to(reference, trying, claims).items())


def add(directory: Path, bound: Mapping[str, Any], variant: dict[str, Any]) -> None:
    """Keeps a variant with the ones that were kept, if those are bound to what this is, and by itself if they are not,
    as they are of another run, other claims, or another trying. Beyond the most that are kept, the oldest go."""
    record = load(directory)
    before = (
        record["variants"] if record is not None and all(record[key] == value for key, value in bound.items()) else []
    )
    keep(directory, {"schema": SCHEMA, **bound, "variants": [*before, variant][-MOST_KEPT:]})


def counts_of(variants: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "variants": len(variants),
        "comparable": sum(1 for variant in variants if variant["comparable"]),
        "rounds_to_paper": sum(1 for variant in variants if variant["rounds_to_paper"] is True),
    }


def make_variant(
    job: Job,
    directory: Path,
    scratch_root: Path,
    agent_id: str,
    commit: str,
    plan: varying.Plan,
    bound: Mapping[str, Any],
    limits: making.ToolLimits,
    data: Path | None,
    docker_command: tuple[str, ...],
    note: str | None,
) -> str:
    """The work of the job: makes the call again with nothing changed and with the changes, in the environment, and
    keeps what came of it as a variant beside the claim, which it does not change.

    :param plan: The call, and what is to be changed in it.
    :param bound: What the variant is bound to, which is of the reference run and trying that it was planned from.
    :param limits: How long the calls may take, how many times each is made, and how much they may write.
    :param data: The folder of the data that the tutorials were given, if they were, which the calls are given too.
    :param note: What the person said of why they asked, if they did.
    :return: What it came to, in a sentence.
    :raises StoppedError: If the job was stopped.
    :raises DockerUnavailableError: If Docker did not run the calls.
    """
    job.update("Making the call again")
    # What an earlier run left of itself, which only a server that was stopped hard would
    referencing.remove_runs(agent_id, docker_command)
    began = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="paperagent.", dir=scratch_root) as scratch:
        runner = making.ToolRunner(
            building.tag_of(agent_id, commit), limits, Path(scratch), data, docker_command, job.stop, agent_id
        )
        found = varying.run(plan, runner, limits.minutes * 60)
    variant = {
        "id": secrets.token_hex(6),
        "made_at": utc_timestamp(),
        "seconds": round(time.monotonic() - began, 2),
        "limits": {"minutes": limits.minutes, "repeats": limits.repeats, "gigabytes": limits.gigabytes},
        "note": note,
        **found,
    }
    add(directory, bound, variant)
    job.log(found["text"])

    return found["text"]
