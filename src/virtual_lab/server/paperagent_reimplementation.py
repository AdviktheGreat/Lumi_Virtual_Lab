"""What writing a function from a paper's words leaves in a PaperAgent's directory, and how it is shown.

reimplementation/record.json says what was done: which words of the paper the model was given, which model wrote it,
what it cost, whether a function came of it, and, if not, why. reimplementation/function.py is the function, if there
is one. The record is bound to the paper's file by its hash, so that a function written from one paper's words is not
shown as of another that took its place.

A function that was written has not been checked against anything of the paper. It has been read as Python and
imported in a container with no network, which shows that it is a function that can be a tool, and nothing about what it
gives. It is of no tier until it has matched a number that the paper reports (paperagent_matching.py).

Nothing is run here but the importing of the file, by function_generator, in the executor that is given.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerUnavailableError, Executor
from virtual_lab.function_generator import (
    VERIFIED,
    FunctionBudgetExceededError,
    FunctionGenerationError,
    FunctionTask,
    cost_of,
    generate_function,
)
from virtual_lab.llm import ModelSource
from virtual_lab.paperagents import reimplementing
from virtual_lab.paperagents.stock import matches
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server.jobs import Job
from virtual_lab.server.papers import StopWork
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import MeetingUsage, write_atomically

DIR = "reimplementation"
RECORD_FILE = "record.json"
FUNCTION_FILE = "function.py"
# What checking the function against the paper's numbers keeps, and the inputs that the person gave for it
# (paperagent_matching.py), which are of the function and go with it
CHECKS_FILE = "checks.json"
INPUTS_FILE = "inputs.json"
# What a record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1
# The most that is read of a record or of a function, which is far more than either is
MAX_RECORD_BYTES = 1 << 20
MAX_SOURCE_BYTES = 1 << 20

WRITTEN = "written"
FAILED = "failed"
STOPPED = "stopped"
STATUSES = (WRITTEN, FAILED, STOPPED)
SHA256 = re.compile(r"[0-9a-f]{64}")

PLACE = {"start": int, "end": int, "section": (str, None), "page": (int, None)}
RECORD = {
    "schema": int,
    "name": str,
    "paper_sha256": str,
    "key": str,
    "agreed_at": str,
    "model": str,
    "limit": (int, float),
    "started_at": str,
    "finished_at": str,
    "status": str,
    "error": (str, None),
    "problems": [str],
    "attempts": int,
    "cost": (int, float, None),
    "task": {
        "goal": (str, None),
        "search": (str, None),
        "sections": [int],
        "places": [PLACE],
        "cut": bool,
        "chars": int,
        "brief_sha256": str,
    },
    "function": ({"status": str, "source_sha256": str, "modules": [str]}, None),
}


def record_path(directory: Path) -> Path:
    return directory / DIR / RECORD_FILE


def function_path(directory: Path) -> Path:
    return directory / DIR / FUNCTION_FILE


def is_record(value: Any) -> bool:
    """Whether what a file holds is a record, in the shape that is kept: a function only if it was written, and one that
    is has the hash of its file."""
    return (
        matches(RECORD, value)
        and value["schema"] == SCHEMA
        and value["status"] in STATUSES
        and SHA256.fullmatch(value["paper_sha256"]) is not None
        and SHA256.fullmatch(value["key"]) is not None
        and SHA256.fullmatch(value["task"]["brief_sha256"]) is not None
        and (value["status"] == WRITTEN) == (value["function"] is not None)
        and (
            value["function"] is None
            or (
                SHA256.fullmatch(value["function"]["source_sha256"]) is not None
                and value["function"]["status"] in ("verified", "unverified")
            )
        )
    )


def load(directory: Path) -> dict[str, Any] | None:
    """The record as it is kept, whatever it is bound to, or None if there is none or what is there is not one."""
    path = record_path(directory)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
            return None
        value = read_json(path)
    except OSError:
        return None

    return value if is_record(value) else None


def source_of(directory: Path, record: dict[str, Any]) -> str | None:
    """The function's code, if there is a function and the file is the one that was written: one that was changed since,
    or taken away, is not it, and is not used."""
    kept = record["function"]
    path = function_path(directory)
    if kept is None:
        return None
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            return None
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None

    return source if hashlib.sha256(source.encode("utf-8")).hexdigest() == kept["source_sha256"] else None


def keep(directory: Path, record: dict[str, Any], source: str | None) -> None:
    """Keeps the function, if there is one, and then the record that says what it is, so that a record never says that
    there is a function that was not kept."""
    folder = directory / DIR
    folder.mkdir(exist_ok=True)
    if source is not None:
        write_atomically(function_path(directory), source.encode("utf-8"))
    write_atomically(record_path(directory), json.dumps(record, indent=4).encode("utf-8"))


def forget(directory: Path) -> None:
    """Takes away the record and the function, and what was kept of checking it and the inputs that were given for it,
    which are of the function."""
    for name in (CHECKS_FILE, INPUTS_FILE):
        (directory / DIR / name).unlink(missing_ok=True)
    record_path(directory).unlink(missing_ok=True)
    function_path(directory).unlink(missing_ok=True)


def is_current(record: dict[str, Any], file_sha256: str | None) -> bool:
    """Whether the record is of the paper that the agent has now."""
    return file_sha256 is not None and record["paper_sha256"] == file_sha256


def shown(directory: Path, file_sha256: str | None) -> dict[str, Any] | None:
    """What is kept, for a person to see: the record, whether it is of the paper that is there now, and the function's
    code, which they are to read before they rely on it."""
    record = load(directory)
    if record is None:
        return None

    return {**record, "current": is_current(record, file_sha256), "source": source_of(directory, record)}


def record_of(
    offer: dict[str, Any],
    model: str,
    limit: float,
    started_at: str,
    status: str,
    error: str | None,
    problems: list[str],
    attempts: int,
    cost: float | None,
    function: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "name": offer["name"],
        "paper_sha256": offer["file_sha256"],
        "key": offer["key"],
        "agreed_at": offer["agreed_at"],
        "model": model,
        "limit": limit,
        "started_at": started_at,
        "finished_at": utc_timestamp(),
        "status": status,
        "error": error,
        "problems": problems,
        "attempts": attempts,
        "cost": round(cost, 6) if cost is not None else None,
        "task": {
            "goal": offer["goal"],
            "search": offer["search"],
            "sections": offer["sections"],
            "places": offer["places"],
            "cut": offer["cut"],
            "chars": len(offer["brief"]),
            "brief_sha256": hashlib.sha256(offer["brief"].encode("utf-8")).hexdigest(),
        },
        "function": function,
    }


def write_function(
    job: Job,
    directory: Path,
    offer: dict[str, Any],
    title: str,
    model: str,
    limit: float,
    executor: Executor,
    chat_models: ModelSource | None,
    client: Any,
    usage: MeetingUsage,
) -> str:
    """The work of the job: asks the model for the function, from the words of the paper that the person was shown and
    agreed to, checks that it is one that can be a tool, imports it in the executor, and keeps what came of it, whether
    it was written, failed, or was stopped, with what it cost. What was kept before is taken away when the job begins,
    as it is of another writing.

    :param offer: What the person agreed to, as the offer of an agent makes it, with when they agreed.
    :param title: The paper's title.
    :param usage: What has been used, to which what the requests use is added.
    :raises StoppedError: If the job was stopped.
    :raises RuntimeError: If no function that can be used was written, or the limit was reached, which is what the job's
        error says.
    """
    forget(directory)
    started = utc_timestamp()
    task = FunctionTask(name=f"Re-implement: {' '.join(title.split())[:120]}", brief=offer["brief"])

    def progress(line: str) -> None:
        if job.stop.is_set():
            raise StopWork
        job.log(line)
        job.update(line.strip())

    def failed(status: str, error: str, problems: list[str], attempts: int) -> None:
        keep(
            directory,
            record_of(offer, model, limit, started, status, error, problems, attempts, cost_of(usage), None),
            None,
        )

    job.update("Writing the function")
    try:
        written = generate_function(
            task,
            name=offer["name"],
            model=model,
            executor=executor,
            max_cost=limit,
            chat_models=chat_models,
            client=client,
            usage=usage,
            on_progress=progress,
            system_prompt=reimplementing.SYSTEM_PROMPT,
        )
    except StopWork:
        failed(STOPPED, "Stopped before a function was written.", [], usage.num_calls)
        raise StoppedError("Stopped. What it cost is kept, and the function was not written.") from None
    except FunctionBudgetExceededError as error:
        message = f"No function was written. {error}"
        failed(FAILED, message, [], usage.num_calls)
        raise RuntimeError(message) from None
    except FunctionGenerationError as error:
        failed(FAILED, str(error), [str(problem) for problem in error.problems], error.attempts)
        raise RuntimeError(str(error)) from None
    except DockerUnavailableError as error:
        message = f"Docker stopped being available while the function was imported: {error}"
        failed(FAILED, message, [], usage.num_calls)
        raise RuntimeError(message) from None

    source = written.source or ""
    function = {
        "status": written.status,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "modules": list(written.modules),
    }
    keep(
        directory,
        record_of(offer, model, limit, started, WRITTEN, None, [], written.attempts, cost_of(usage), function),
        source,
    )
    imported = "imported in a container with no network" if written.status == VERIFIED else "read, and not run"
    attempts = f"{written.attempts} {'attempt' if written.attempts == 1 else 'attempts'}"
    said = (
        f"Wrote {offer['name']} in {attempts}: {imported}. "
        "It has not been checked against anything of the paper, and is given to no conversation until it matches a "
        "number that the paper reports."
    )
    job.log(said)

    return said
