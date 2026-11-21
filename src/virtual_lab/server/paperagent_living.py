"""What watching a PaperAgent leaves in its directory: how it is, when it is to be looked at again, and a newer
version of its code that is proposed.

living/health.json is what the last check found: the source (has the code's ref moved, or is it gone), the image of the
environment, the versions that a pip lock pins, and each tool's recorded calls, which are run again in the environment
that is kept, in a container with no network. It is bound to the commit and the image it was of, and is not shown for
another. living/watch.json is a schedule that the person set, in hours. living/update.json is a newer commit of the
code, shown as a diff against the version that is kept; it is bound to the commit it is a change from.

Nothing here changes what the agent is pinned to. A check reads, and runs the tools in the image that is kept. A newer
version is taken only when the person says so (PaperAgents.apply_update), and until then the commit, the environment,
and the tools are as they were.
"""

import json
import shutil
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerUnavailableError
from virtual_lab.paperagents import watching
from virtual_lab.paperagents.repository import RepositoryError
from virtual_lab.paperagents.stock import matches
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_environment as kept_environment
from virtual_lab.server import paperagent_library as kept_library
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server.jobs import Job
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import write_atomically

LIVING_DIR = "living"
HEALTH_FILE = "health.json"
WATCH_FILE = "watch.json"
UPDATE_FILE = "update.json"
SCHEMA = 1

# How often an agent may be looked at, in hours: not more than hourly, and not less than every ninety days
MIN_HOURS = 1
MAX_HOURS = 24 * 90
# How many earlier results are kept to say how an agent has been, and the most that a record may be
HISTORY = 10
MAX_RECORD_BYTES = 2 << 20
MAX_TEXT = 400

HEALTH = {
    "schema": int,
    "checked_at": str,
    "status": str,
    "reasons": [str],
    "commit": str,
    "image_id": str,
    "tools_made_at": str,
    "source": {"state": str, "commit": (str, None), "message": str, "update_error": (str, None)},
    "image": {"present": (bool, None)},
    "dependencies": (
        {
            "kind": str,
            "total": int,
            "looked_at": int,
            "unsaid": int,
            "problems": [{"name": str, "version": str, "state": str}],
        },
        None,
    ),
    "dependencies_message": (str, None),
    "tools": [{"name": str, "calls": int, "matched": int, "message": (str, None)}],
    "tools_message": (str, None),
    "seconds": (int, float),
    "history": [{"at": str, "status": str}],
}
WATCH = {"schema": int, "every_hours": int, "set_at": str, "last_started_at": (str, None)}
FILE = {
    "path": str,
    "change": str,
    "added": (int, None),
    "removed": (int, None),
    "diff": (str, None),
    "cut": bool,
    "binary": bool,
}
UPDATE = {
    "schema": int,
    "proposed_at": str,
    "url": str,
    "ref": str,
    "from_commit": str,
    "to_commit": str,
    "diff": {"changed": int, "added": int, "removed": int, "files": [FILE], "truncated": bool},
    "affects": [str],
    "environment_files": [str],
}


def living_path(directory: Path) -> Path:
    return directory / LIVING_DIR


def read(directory: Path, name: str, shape: Any) -> dict[str, Any] | None:
    """What a file of the agent's living folder holds, if it is a record as it is written. It is a file that a server
    wrote, but it is looked at as one that was not: not a link, not big, and of the shape."""
    path = living_path(directory) / name
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
            return None
    except OSError:
        return None
    value = read_json(path)

    return value if matches(shape, value) and value["schema"] == SCHEMA else None


def keep(directory: Path, name: str, record: dict[str, Any]) -> None:
    folder = living_path(directory)
    folder.mkdir(exist_ok=True)
    write_atomically(folder / name, json.dumps({"schema": SCHEMA, **record}, indent=2).encode("utf-8"))


def drop(directory: Path, name: str) -> None:
    (living_path(directory) / name).unlink(missing_ok=True)


def forget(directory: Path) -> None:
    """Removes what watching left, and the schedule."""
    shutil.rmtree(living_path(directory), ignore_errors=True)


def load_health(directory: Path) -> dict[str, Any] | None:
    return read(directory, HEALTH_FILE, HEALTH)


def load_watch(directory: Path) -> dict[str, Any] | None:
    record = read(directory, WATCH_FILE, WATCH)

    return record if record is not None and MIN_HOURS <= record["every_hours"] <= MAX_HOURS else None


def load_update(directory: Path) -> dict[str, Any] | None:
    return read(directory, UPDATE_FILE, UPDATE)


def made_at(kept: dict[str, Any]) -> str:
    """When the tools that are kept were made, which says which tools they are: making them again makes other ones."""
    return f"{kept['started_at']} {kept['finished_at']}"


def health_view(
    record: dict[str, Any] | None,
    intake: dict[str, Any] | None,
    built: dict[str, Any] | None,
    kept: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """What the last check found, if it was of the commit, the image, and the tools that are kept now."""
    if record is None or intake is None or built is None or kept is None:
        return None

    return (
        record
        if record["commit"] == intake["commit"]
        and record["image_id"] == built["image"]["id"]
        and record["tools_made_at"] == made_at(kept)
        else None
    )


def update_view(record: dict[str, Any] | None, intake: dict[str, Any] | None) -> dict[str, Any] | None:
    """The newer version that is proposed, if it is a change from the commit that is kept now, of the code at the
    address that it was fetched from."""
    if record is None or intake is None:
        return None

    return record if record["from_commit"] == intake["commit"] and record["url"] == intake["url"] else None


def moment(text: str | None) -> datetime | None:
    try:
        found = datetime.fromisoformat(text) if text else None
    except ValueError:
        return None
    if found is not None and found.tzinfo is None:
        found = found.replace(tzinfo=timezone.utc)

    return found


def is_due(watch: dict[str, Any] | None, now: datetime) -> bool:
    """Whether an agent that is watched is to be looked at: it never was since the schedule was set, or the hours that
    were set have passed since it was last started. A time that cannot be read is a check that is due."""
    if watch is None:
        return False
    last = moment(watch["last_started_at"])

    return last is None or now >= last + timedelta(hours=watch["every_hours"])


def propose_update(
    job: Job,
    directory: Path,
    scratch_root: Path,
    intake: dict[str, Any],
    tools: Sequence[dict[str, Any]],
    fetch: Callable[..., Any],
) -> dict[str, Any] | None:
    """Fetches the newer version of the code into a folder of its own, holds it to the version that is kept, and keeps
    what differs as a proposal. Nothing that is kept is changed.

    :param fetch: What fetches code, as paperagents.repository.clone does.
    :return: The proposal, or None if what was fetched is the version that is kept.
    :raises RepositoryError: If the newer version cannot be fetched or is too big.
    :raises StoppedError: If the job was stopped.
    """
    with tempfile.TemporaryDirectory(prefix="paperagent.", dir=scratch_root) as scratch:
        fetched = Path(scratch) / kept_repository.REPO_DIR
        cloned = fetch(intake["url"], fetched, intake["ref"], intake["limit_bytes"], should_stop=job.stop.is_set)
        if cloned.commit == intake["commit"]:
            drop(directory, UPDATE_FILE)
            return None
        if job.stop.is_set():
            raise StoppedError("Stopped.")
        changes = watching.diff_trees(kept_repository.repo_path(directory), fetched, job.stop.is_set)
        if job.stop.is_set():
            raise StoppedError("Stopped.")
    paths = changes.pop("paths")
    record = {
        "proposed_at": utc_timestamp(),
        "url": intake["url"],
        "ref": intake["ref"],
        "from_commit": intake["commit"],
        "to_commit": cloned.commit,
        "diff": changes,
        "affects": watching.affected(tools, paths),
        "environment_files": watching.environment_files(paths),
    }
    keep(directory, UPDATE_FILE, record)

    return record


def tools_found(checked: kept_library.Checked) -> list[dict[str, Any]]:
    """Each tool of a package as its check ran it again: how many recorded calls it was held to and how many gave what
    the tutorials got, and, of the first that did not, what differed."""
    found = []
    for tool in checked.manifest["tools"]:
        named = next((one for one in (checked.report or {"tools": []})["tools"] if one["name"] == tool["name"]), None)
        calls = min(len(tool["examples"]), kept_library.MAX_CASES)
        if named is None:
            found.append(
                {"name": tool["name"], "calls": calls, "matched": 0, "message": (checked.reason or "")[:MAX_TEXT]}
            )
            continue
        wrong = [case for case in named["cases"] if case["status"] != "match"]
        said = None
        if wrong:
            said = "; ".join(wrong[0]["differences"]) or wrong[0]["message"] or wrong[0]["status"]
        found.append(
            {
                "name": tool["name"],
                "calls": calls,
                "matched": len(named["cases"]) - len(wrong),
                "message": said[:MAX_TEXT] if said else None,
            }
        )

    return found


def check_health(
    job: Job,
    directory: Path,
    scratch_root: Path,
    agent_id: str,
    agent: dict[str, Any],
    intake: dict[str, Any],
    built: dict[str, Any],
    kept: dict[str, Any],
    data: Path | None,
    docker_command: Sequence[str],
    probe: Callable[..., watching.Probe],
    index: watching.Index,
    fetch: Callable[..., Any],
    image_present: bool | None,
    docker_problem: str | None,
) -> str:
    """Looks at an agent: asks where its code is now, and shows what a newer version would change; asks the index of the
    versions that its lock pins; and runs the recorded calls of its tools again in its environment, in a container with
    no network. What it finds is kept, as how the agent is.

    :param image_present: Whether the environment's image is in Docker, or None if Docker could not be asked.
    :param docker_problem: Why Docker cannot run the tools now, if it cannot.
    :return: What it came to, in a sentence.
    :raises StoppedError: If the job was stopped.
    """
    began = utc_timestamp()
    clock = datetime.now(timezone.utc)
    tools = kept_library.tools_now(directory, kept)
    job.update("Asking where the code is now")
    found = probe(intake["url"], intake["ref"], intake["commit"])
    job.log(found.message)
    update_error = None
    proposal = None
    if found.state == watching.MOVED:
        earlier = load_update(directory)
        if earlier is not None and (earlier["from_commit"], earlier["to_commit"]) == (intake["commit"], found.commit):
            proposal = earlier
        else:
            job.update("Fetching the newer version, to show what it would change")
            try:
                proposal = propose_update(job, directory, scratch_root, intake, tools, fetch)
            except RepositoryError as error:
                update_error = str(error)[:MAX_TEXT]
                job.log(f"The newer version was not fetched: {update_error}")
    elif found.state in (watching.SAME, watching.PINNED):
        drop(directory, UPDATE_FILE)
    if job.stop.is_set():
        raise StoppedError("Stopped.")

    pins = None
    pins_message = None
    if built["recipe"]["kind"] == "pip":
        job.update("Asking the package index of the versions that the lock pins")
        pins = {
            "kind": "pip",
            **watching.look_at_pins(kept_environment.read_lock(directory, built), index, job.stop.is_set),
        }
    else:
        pins_message = "Only the versions that a pip lock pins are asked of, and this environment is a conda one."
    if job.stop.is_set():
        raise StoppedError("Stopped.")

    ran = None
    ran_message = None
    if image_present is False:
        ran_message = "The image of the environment is not in Docker, so the tools were not run."
    elif docker_problem is not None or image_present is None:
        ran_message = f"The tools were not run: {docker_problem or 'Docker could not be asked'}"
    else:
        job.update("Running the recorded calls of the tools again, in a clean container")
        try:
            with kept_library.checked_package(
                job, directory, scratch_root, agent_id, agent, intake, built, kept, data, docker_command
            ) as checked:
                if checked.report is None:
                    ran_message = f"The check did not report: {checked.reason or 'it gave no reason'}"[:MAX_TEXT]
                elif (other := kept_library.not_of_the_package(checked.report, checked.manifest)) is not None:
                    ran_message = other
                elif checked.report["problems"]:
                    ran_message = "Its check said: " + " ".join(checked.report["problems"])[:MAX_TEXT]
                else:
                    ran = tools_found(checked)
        except kept_library.ExportError as error:
            ran_message = f"The tools could not be run again: {error}"[:MAX_TEXT]
        except DockerUnavailableError as error:
            ran_message = f"The tools were not run: {error}"[:MAX_TEXT]

    if job.stop.is_set():
        raise StoppedError("Stopped.")
    status, reasons = watching.health_of(
        {"state": found.state, "message": found.message}, image_present, pins, ran, ran_message
    )
    earlier_health = load_health(directory)
    history = [*(earlier_health["history"] if earlier_health is not None else []), {"at": began, "status": status}]
    keep(
        directory,
        HEALTH_FILE,
        {
            "checked_at": began,
            "status": status,
            "reasons": [reason[:MAX_TEXT] for reason in reasons],
            "commit": intake["commit"],
            "image_id": built["image"]["id"],
            "tools_made_at": made_at(kept),
            "source": {
                "state": found.state,
                "commit": found.commit,
                "message": found.message,
                "update_error": update_error,
            },
            "image": {"present": image_present},
            "dependencies": pins,
            "dependencies_message": pins_message,
            "tools": ran or [],
            "tools_message": ran_message,
            "seconds": round((datetime.now(timezone.utc) - clock).total_seconds(), 1),
            "history": history[-HISTORY:],
        },
    )

    return summary_of(status, reasons, ran, proposal)


def summary_of(
    status: str, reasons: Sequence[str], tools: Sequence[dict[str, Any]] | None, proposal: dict[str, Any] | None
) -> str:
    """What a check came to, in a sentence or two."""
    held = [tool for tool in tools or [] if tool["calls"]]
    if status == watching.HEALTHY:
        said = f"Healthy: {len(held)} tool{'s' if len(held) != 1 else ''} gave again what their tutorials got."
    else:
        said = f"{status.capitalize()}. {reasons[0] if reasons else ''}".strip()
    if proposal is not None:
        said += (
            f" A newer version of the code is proposed ({proposal['from_commit'][:7]} to {proposal['to_commit'][:7]}, "
            f"{proposal['diff']['changed']} file{'s' if proposal['diff']['changed'] != 1 else ''} changed). "
            "Nothing was changed."
        )

    return said
