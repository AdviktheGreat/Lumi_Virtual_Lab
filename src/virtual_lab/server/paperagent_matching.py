"""What checking a function that was written from a paper against the paper's numbers leaves in a PaperAgent's
directory, and how it is shown.

reimplementation/checks.json says what each claim that was tried came to: what the function was called with and whose
that was, and whether what it gave has the claim's number (paperagents/matching.py). It is bound to the function's code
by its hash, to the paper's file, and to the claims that were read of it, so that it is not taken for evidence of a
function or a paper that took the place of the one it is of. reimplementation/inputs.json keeps the inputs that the
person gave for claims, each bound to the claim as it was then and all to the function they were checked against.

What is run is the function, in a container with no network, by the runner of a tool's calls. A model, if one is asked,
reads the passage of the paper around each claim for its inputs; what it gives is checked by a program.
"""

import hashlib
import inspect
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerUnavailableError
from virtual_lab.function_checks import FunctionSourceError, read_function
from virtual_lab.function_generator import cost_of
from virtual_lab.paperagents import asking, matching, reimplementing
from virtual_lab.paperagents import reference as referencing
from virtual_lab.paperagents.anchors import Document
from virtual_lab.paperagents.comparing import shown as shown_value
from virtual_lab.paperagents.stock import matches
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_reimplementation as kept_reimplementation
from virtual_lab.server.jobs import Job
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import MeetingUsage, write_atomically

SCHEMA = 1
MAX_RECORD_BYTES = 4 << 20
DONE = "done"
STOPPED = "stopped"
FAILED = "failed"
STATUSES = (DONE, STOPPED, FAILED)
# How much of what the container printed is kept, by lines, which is the runner's own and not the function's
OUTPUT_LINES = 10

ENTRY = {
    "claim": str,
    "claim_sha256": str,
    "value": str,
    "quote": str,
    "by": (str, None),
    "arguments": (dict, None),
    "where": (str, None),
    "reason": (str, None),
    "note": (str, None),
    "hard_coded": [str],
    "status": str,
    "found": (dict, None),
    "places": int,
    "error": (str, None),
    "gave": (str, None),
    "seconds": (int, float, None),
}
CHECKS = {
    "schema": int,
    "source_sha256": str,
    "paper_sha256": str,
    "claims_sha256": str,
    "started_at": str,
    "finished_at": str,
    "status": str,
    "error": (str, None),
    "model": (str, None),
    "limit": (int, float, None),
    "cost": (int, float, None),
    "requests": int,
    "minutes": int,
    "ended": (str, None),
    "output": [str],
    "entries": [ENTRY],
}
GIVEN = {"claim": str, "claim_sha256": str, "arguments": dict, "given_at": str}
INPUTS = {"schema": int, "source_sha256": str, "inputs": [GIVEN]}


def checks_path(directory: Path) -> Path:
    return directory / kept_reimplementation.DIR / kept_reimplementation.CHECKS_FILE


def inputs_path(directory: Path) -> Path:
    return directory / kept_reimplementation.DIR / kept_reimplementation.INPUTS_FILE


def read_kept(path: Path) -> Any:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
            return None
        return read_json(path)
    except OSError:
        return None


def is_checks(value: Any) -> bool:
    return (
        matches(CHECKS, value)
        and value["schema"] == SCHEMA
        and value["status"] in STATUSES
        and all(entry["status"] in matching.STATUSES for entry in value["entries"])
    )


def load_checks(directory: Path) -> dict[str, Any] | None:
    """What was kept of the checking, whatever it is bound to, or None if there is none or what is there is not it."""
    value = read_kept(checks_path(directory))

    return value if is_checks(value) else None


def forget_checks(directory: Path) -> None:
    checks_path(directory).unlink(missing_ok=True)


def keep_checks(directory: Path, record: dict[str, Any]) -> None:
    (directory / kept_reimplementation.DIR).mkdir(exist_ok=True)
    write_atomically(checks_path(directory), json.dumps(record, indent=4).encode("utf-8"))


def sha256_of(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def is_current(
    checks: dict[str, Any], source: str | None, paper_sha256: str | None, claims: list[dict[str, Any]]
) -> bool:
    """Whether what was kept of the checking is of the function that is kept now, the paper that is there now, and the
    claims that were read of it."""
    return (
        source is not None
        and paper_sha256 is not None
        and checks["source_sha256"] == sha256_of(source)
        and checks["paper_sha256"] == paper_sha256
        and checks["claims_sha256"] == matching.claims_sha256(claims)
    )


@dataclass(frozen=True)
class Given:
    """A function written from a paper that is of tier C now, which is what a conversation may be given of it.

    :param name: The function's name.
    :param source: Its code, as it is kept.
    :param label: What it is, and what it matched of the paper (matching.standing_of).
    """

    name: str
    source: str
    label: str


def given_function(directory: Path, paper_sha256: str | None, claims: list[dict[str, Any]]) -> Given | None:
    """The function written from the paper, if it is of tier C now: it is of the paper that is there now, its file is
    the one that was written, and the checking that was kept came to its end, is of this function, paper, and claims,
    and matched a number of the paper."""
    record = kept_reimplementation.load(directory)
    if record is None or not kept_reimplementation.is_current(record, paper_sha256):
        return None
    source = kept_reimplementation.source_of(directory, record)
    checks = load_checks(directory)
    if source is None or checks is None or checks["status"] != DONE:
        return None
    if not is_current(checks, source, paper_sha256, claims):
        return None
    tier, label = matching.standing_of(checks["entries"])

    return Given(record["name"], source, label) if tier == reimplementing.TIER else None


# The person's inputs


def load_inputs(directory: Path) -> dict[str, Any] | None:
    value = read_kept(inputs_path(directory))

    return value if matches(INPUTS, value) and value["schema"] == SCHEMA else None


def given_inputs(directory: Path, source: str | None, claims: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The inputs that the person gave, by claim, that are of the function that is kept now and of a claim that says
    what it said when they were given."""
    kept = load_inputs(directory)
    if kept is None or source is None or kept["source_sha256"] != sha256_of(source):
        return {}
    hashes = {claim["id"]: matching.claim_sha256(claim) for claim in claims}

    return {given["claim"]: given for given in kept["inputs"] if hashes.get(given["claim"]) == given["claim_sha256"]}


def keep_inputs(
    directory: Path, source: str, claims: list[dict[str, Any]], claim_id: str, arguments: dict[str, Any] | None
) -> None:
    """Keeps the inputs that the person gave for a claim, or takes them away if there are none, with those of the other
    claims that are still of this function and of what the claims say."""
    given = given_inputs(directory, source, claims)
    given.pop(claim_id, None)
    claim = next(claim for claim in claims if claim["id"] == claim_id)
    if arguments is not None:
        given[claim_id] = {
            "claim": claim_id,
            "claim_sha256": matching.claim_sha256(claim),
            "arguments": arguments,
            "given_at": utc_timestamp(),
        }
    record = {"schema": SCHEMA, "source_sha256": sha256_of(source), "inputs": list(given.values())}
    (directory / kept_reimplementation.DIR).mkdir(exist_ok=True)
    write_atomically(inputs_path(directory), json.dumps(record, indent=4).encode("utf-8"))


# Checking


def record_of(
    source: str,
    paper_sha256: str,
    claims_sha256: str,
    started_at: str,
    status: str,
    error: str | None,
    model: str | None,
    limit: float | None,
    usage: MeetingUsage,
    minutes: int,
    replay: Any,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    cost = cost_of(usage)

    return {
        "schema": SCHEMA,
        "source_sha256": sha256_of(source),
        "paper_sha256": paper_sha256,
        "claims_sha256": claims_sha256,
        "started_at": started_at,
        "finished_at": utc_timestamp(),
        "status": status,
        "error": error,
        "model": model,
        "limit": limit,
        "cost": round(cost, 6) if cost is not None else None,
        "requests": usage.num_calls,
        "minutes": minutes,
        "ended": replay.ended if replay is not None else None,
        "output": replay.output[-OUTPUT_LINES:] if replay is not None else [],
        "entries": entries,
    }


def check_function(
    job: Job,
    directory: Path,
    name: str,
    source: str,
    paper_sha256: str,
    claims: list[dict[str, Any]],
    document: Document,
    asker: matching.InputsAsker | None,
    usage: MeetingUsage,
    minutes: int,
    scratch_root: Path,
    docker_command: tuple[str, ...],
    agent_id: str,
) -> str:
    """The work of the job: finds what each claim that is tried is to be called with, calls the function with them in a
    container with no network, and keeps what each came to, whether the checking was done, stopped, or failed. What was
    kept of an earlier checking is taken away when the job begins.

    :param name: The function's name.
    :param source: Its code, as it is kept.
    :param claims: The claims of the paper, as they are kept.
    :param asker: The model that reads a claim's passage for its inputs, or None if none is to be.
    :param usage: What has been used, to which what the requests use is added.
    :param minutes: How long all of the calls may take together.
    :raises StoppedError: If the job was stopped.
    :raises RuntimeError: If the function could not be read or called, which is what the job's error says.
    """
    forget_checks(directory)
    started = utc_timestamp()
    person = given_inputs(directory, source, claims)
    tried = matching.claims_to_try(claims, person)
    model = asker.model if asker is not None else None
    limit = asker.max_cost if asker is not None else None
    claims_sha256 = matching.claims_sha256(claims)
    reached: str | None = None

    def keep(status: str, error: str | None, replay: Any, entries: list[dict[str, Any]]) -> None:
        record = record_of(
            source, paper_sha256, claims_sha256, started, status, error, model, limit, usage, minutes, replay, entries
        )
        keep_checks(directory, record)

    try:
        reading = read_function(source, name)
    except FunctionSourceError as error:
        message = f"The function cannot be read as a tool: {' '.join(error.problems)[:400]}"
        keep(FAILED, message, None, [])
        raise RuntimeError(message) from None

    planned: list[tuple[dict[str, Any], Any, dict[str, Any], list[str]]] = []
    for number_of, (claim, number) in enumerate(tried, start=1):
        if job.stop.is_set():
            keep(STOPPED, "Stopped before the function was called.", None, unrun_entries(planned))
            raise StoppedError("Stopped. What it cost is kept, and the function was not called.")
        job.update(f"Finding the inputs of claim {number_of} of {len(tried)}")
        literals = matching.hard_coded(source, number)
        blank = {"by": None, "arguments": None, "where": None, "reason": None, "note": None}
        if literals:
            planned.append((claim, number, blank, literals))
            continue
        given = person.get(claim["id"])
        arguments = given["arguments"] if given is not None else None
        if reached is not None and arguments is None:
            inputs = {**blank, "by": matching.BY_MODEL, "reason": matching.LIMIT, "note": reached}
        else:
            try:
                passage = matching.passage_of(document, claim)
                inputs = matching.inputs_for(asker, reading, claim, number, passage, arguments)
            except asking.LimitReached as error:
                reached = str(error)
                inputs = {**blank, "by": matching.BY_MODEL, "reason": matching.LIMIT, "note": reached}
        planned.append((claim, number, inputs, []))
        job.log(f"{claim['id']} ({number.text}): {inputs['note'] or 'inputs ' + str(inputs['by'])}"[:400])

    calls = [inputs["arguments"] for _, _, inputs, literals in planned if inputs["arguments"] is not None]
    replay = None
    if calls:
        job.update(f"Calling the function, {len(calls)} call{'s' if len(calls) != 1 else ''} twice each")
        referencing.remove_runs(agent_id, docker_command)
        try:
            with tempfile.TemporaryDirectory(prefix="paperagent.", dir=scratch_root) as scratch:
                runner = matching.runner_for(Path(scratch), docker_command, job.stop, agent_id)
                replay = matching.run_calls(runner, source, name, calls, minutes * 60)
        except StoppedError:
            keep(STOPPED, "Stopped while the function was called.", None, unrun_entries(planned))
            raise StoppedError("Stopped. What it cost is kept, and what the calls gave was not.") from None
        except DockerUnavailableError as error:
            message = f"Docker stopped being available while the function was called: {error}"
            keep(FAILED, message, None, unrun_entries(planned))
            raise RuntimeError(message) from None

    entries = []
    results = iter(replay.results if replay is not None else [])
    for claim, number, inputs, literals in planned:
        if literals:
            outcome = matching.unrun(matching.HARD_CODED)
        elif inputs["arguments"] is None:
            outcome = matching.unrun(matching.NO_INPUTS)
        else:
            outcome = matching.outcome_of(next(results), number)
        entries.append(matching.entry_of(claim, number, inputs, literals, outcome))
    keep(DONE, None, replay, entries)
    _, label = matching.standing_of(entries)
    job.log(label)

    return label


def unrun_entries(planned: list[tuple[dict[str, Any], Any, dict[str, Any], list[str]]]) -> list[dict[str, Any]]:
    """What the claims came to when the function was not called for any of them."""
    entries = []
    for claim, number, inputs, literals in planned:
        status = (
            matching.HARD_CODED if literals else matching.NO_INPUTS if inputs["arguments"] is None else matching.NOT_RUN
        )
        entries.append(matching.entry_of(claim, number, inputs, literals, matching.unrun(status)))

    return entries


# What is shown


def parameters_of(source: str | None, name: str | None) -> list[dict[str, Any]] | None:
    """The parameters that the person may give, as the function declares them, or None if there is no function that
    can be read."""
    if source is None or name is None:
        return None
    try:
        reading = read_function(source, name)
    except FunctionSourceError:
        return None

    return [
        {
            "name": parameter_name,
            "hint": inspect.formatannotation(parameter.annotation),
            "required": parameter.default is parameter.empty,
            "default": None if parameter.default is parameter.empty else shown_value(parameter.default, 60),
        }
        for parameter_name, parameter in matching.parameters_of(reading).items()
    ]


def shown(
    directory: Path,
    record: dict[str, Any] | None,
    source: str | None,
    paper_sha256: str | None,
    claims: list[dict[str, Any]],
    document: Document | None,
) -> dict[str, Any]:
    """What there is of checking the function, for a person to see: the claims that would be tried now, each with its
    passage, the inputs that the person gave for it, and what it came to when the function was last checked if that is
    of this function and paper; the tier and label that come of it; and the parameters that inputs are given for."""
    current_record = record is not None and kept_reimplementation.is_current(record, paper_sha256)
    usable = source if current_record else None
    checks = load_checks(directory)
    current = checks is not None and is_current(checks, usable, paper_sha256, claims)
    person = given_inputs(directory, usable, claims)
    entries = {entry["claim"]: entry for entry in checks["entries"]} if checks is not None and current else {}
    tier, label = matching.standing_of(checks["entries"] if checks is not None and current else None)
    if checks is not None and current and checks["status"] != DONE:
        tier, label = matching.standing_of(None)
    listed = []
    for claim, number in matching.claims_to_try(claims, person):
        entry = entries.get(claim["id"])
        listed.append(
            {
                "id": claim["id"],
                "value": number.text,
                "quote": claim["quote"],
                "passage": matching.passage_of(document, claim) if document is not None else None,
                "inputs": person[claim["id"]] if claim["id"] in person else None,
                "entry": entry if entry is not None and entry["claim_sha256"] == matching.claim_sha256(claim) else None,
            }
        )

    return {
        "kept": {key: value for key, value in checks.items() if key != "entries"} if checks is not None else None,
        "current": current,
        "tier": tier,
        "label": label,
        "claims": listed,
        "counts": matching.counts_of(checks["entries"]) if checks is not None and current else None,
        "parameters": parameters_of(usable, record["name"] if record is not None else None),
        "meaning": matching.MEANING,
        "limits": {
            "most_tried": matching.MOST_TRIED,
            "repeats": matching.REPEATS,
            "default_minutes": matching.DEFAULT_MINUTES,
            "most_minutes": matching.MAX_MINUTES,
            "most_arguments_chars": matching.MAX_ARGUMENTS_CHARS,
        },
    }
