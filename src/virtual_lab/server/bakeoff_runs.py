"""What is kept of running a method of a bake-off on the person's data.

A method that was built is run by calling one of its tools once, on the person's data, in a sandbox: the image of the
method's environment, no network, the data read-only. What came of it is kept with the method, in the bake-off's own
`runs` folder and not in the bake-off's file, since a result may be large and is not what the bake-off is. It is kept
whichever way it came out, so that a method is not left out of a table for not having run:

- ran: the call came to an answer. The result is kept as the tool gave it, if it is plain data, and described if it is
  not, with what it printed and the seconds it took.
- failed: the call was made and did not come to an answer: the authors' function raised, or it was stopped for the time
  or the size, or the container ended without saying how it went. It is kept with what was seen, since a method that
  fails on the person's data is a thing to know of it.
- not_run: the call was not made, and why: the data is outside what the card of the method's paper says and the person
  has not said to go on, or there is no data to run on, or the method is not built, or the tool or the arguments are not
  as the tool's signature says. It is shown as it is, and not left out.

Each says what it ran: the tool and its tier, the arguments it was called with and whose they were, the method's own
commit and image, the data as it was listed (its names, sizes and times, which are not a hash of what is in it), and
what the data was put against the card with. It does not say that the result is right: what it says is that this call
was made to this code on this data, and what it gave.

Only the latest run of a method is kept. A run is of what was there when it was made, so what is shown of it says
whether the data, or the method, is as it was.

A file that is not in the shape that a run is kept in is not used, as it may not be if it was edited.
"""

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any

from virtual_lab.paperagents.stock import matches
from virtual_lab.server.workspace import has_control_character
from virtual_lab.utils import write_atomically

RUNS_FOLDER = "runs"
SCHEMA = 1
MAX_RUN_BYTES = 1 << 20
MAX_ARGUMENTS_CHARS = 20_000
MAX_REASON_CHARS = 4000
MAX_PRINTED_CHARS = 2000
MAX_WARNINGS = 5
MAX_WARNING_CHARS = 600
# How many files of a piece of data are listed to say whether it is as it was
MAX_LISTED = 5000
# How much of a result a page is shown before it asks for the whole of it
PREVIEW_CHARS = 400

ID = re.compile(r"[0-9a-f]{8}")
COMMIT = re.compile(r"[0-9a-f]{7,64}")
HASH = re.compile(r"[0-9a-f]{64}")

RAN, FAILED, NOT_RUN = "ran", "failed", "not_run"
STATES = (RAN, FAILED, NOT_RUN)
# Why a call was made and did not come to an answer, and why it was not made
FAILED_WHY = ("error", "timed_out", "too_big", "no_answer")
NOT_RUN_WHY = (
    "outside",
    "no_data",
    "data_missing",
    "cannot_mount",
    "not_built",
    "no_tool",
    "bad_call",
)
# Who chose the call: the person, in what they said
BY_PERSON = "person"

NUMBER = (int, float)
TOOL = {"name": str, "called": str, "tier": str}
DATA = {"own": str, "path": str, "files": int, "bytes": int, "fingerprint": str, "complete": bool}
SCOPE = {
    "checked": bool,
    "why": (str, None),
    "outcome": (str, None),
    "key": (str, None),
    "went_on": bool,
    "warnings": [str],
}
METHOD = {"agent": str, "commit": str, "image_id": str}
RUN = {
    "schema": int,
    "candidate": str,
    "state": str,
    "why": (str, None),
    "reason": str,
    "at": str,
    "by": str,
    "tool": (TOOL, None),
    "arguments": (dict, None),
    "seconds": (NUMBER, None),
    "result": (dict, None),
    "printed": (str, None),
    "data": (DATA, None),
    "scope": SCOPE,
    "method": (METHOD, None),
}


def is_finite_json(value: Any) -> bool:
    """Whether a value is what JSON holds: no number that is not finite, and nothing that is not plain data."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return False

    return True


def is_tool(tool: dict[str, Any]) -> bool:
    return not any(has_control_character(text) for text in tool.values())


def is_data(data: dict[str, Any]) -> bool:
    return (
        not has_control_character(data["own"])
        and not has_control_character(data["path"])
        and data["files"] >= 0
        and data["bytes"] >= 0
        and HASH.fullmatch(data["fingerprint"]) is not None
    )


def is_scope(scope: dict[str, Any]) -> bool:
    return (
        all(value is None or not has_control_character(value) for value in (scope["why"], scope["outcome"]))
        and (scope["key"] is None or HASH.fullmatch(scope["key"]) is not None)
        and len(scope["warnings"]) <= MAX_WARNINGS
        and all(len(each) <= MAX_WARNING_CHARS for each in scope["warnings"])
        # What was not put against a card has no outcome to go on with
        and (scope["checked"] or (scope["outcome"] is None and not scope["went_on"] and scope["key"] is None))
    )


def is_method(method: dict[str, Any]) -> bool:
    return (
        method["agent"] != ""
        and not has_control_character(method["agent"])
        and COMMIT.fullmatch(method["commit"]) is not None
        and not has_control_character(method["image_id"])
    )


def is_run(value: Any, candidate_id: str) -> bool:
    """Whether what is kept as the run of a method is one: of that method, in one of the states with a reason that fits
    it, and having what a run of that state has."""
    if not matches(RUN, value) or value["schema"] != SCHEMA or value["candidate"] != candidate_id:
        return False
    if (
        value["state"] not in STATES
        or has_control_character(value["at"])
        or value["by"] != BY_PERSON
        or len(value["reason"]) > MAX_REASON_CHARS
        or (value["printed"] is not None and len(value["printed"]) > MAX_PRINTED_CHARS)
        or not is_scope(value["scope"])
        or (value["tool"] is not None and not is_tool(value["tool"]))
        or (value["data"] is not None and not is_data(value["data"]))
        or (value["method"] is not None and not is_method(value["method"]))
        or (value["seconds"] is not None and not (math.isfinite(value["seconds"]) and value["seconds"] >= 0))
        or not is_finite_json(value["arguments"])
        or not is_finite_json(value["result"])
        or (value["arguments"] is not None and len(json.dumps(value["arguments"])) > MAX_ARGUMENTS_CHARS)
    ):
        return False
    made = value["tool"] is not None and value["data"] is not None and value["method"] is not None
    if value["state"] == RAN:
        return (
            made
            and value["why"] is None
            and value["reason"] == ""
            and value["arguments"] is not None
            and value["seconds"] is not None
            and value["result"] is not None
            and "type" in value["result"]
        )
    if value["state"] == FAILED:
        return (
            made
            and value["why"] in FAILED_WHY
            and value["reason"] != ""
            and value["arguments"] is not None
            and value["result"] is None
        )

    return (
        value["why"] in NOT_RUN_WHY
        and value["reason"] != ""
        and value["seconds"] is None
        and value["result"] is None
        and value["printed"] is None
    )


def where(directory: Path, candidate_id: str) -> Path:
    return directory / RUNS_FOLDER / f"{candidate_id}.json"


def load(directory: Path, candidate_id: str) -> dict[str, Any] | None:
    """The run that is kept of a method of the bake-off kept in a directory, or None if there is none or what is there
    is not one."""
    if ID.fullmatch(candidate_id) is None:
        return None
    path = where(directory, candidate_id)
    try:
        folder = path.parent
        if folder.is_symlink() or path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RUN_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None

    return value if is_run(value, candidate_id) else None


def encode(run: dict[str, Any]) -> bytes:
    """A run as it is kept.

    :raises ValueError: If it is not a run, or is too big to be kept, which is for whoever made it to say.
    """
    if not is_run(run, run.get("candidate", "")):
        raise ValueError("That is not a run of a method")
    text = json.dumps(run, indent=2, allow_nan=False).encode("utf-8")
    if len(text) > MAX_RUN_BYTES:
        raise ValueError("That run is too big to be kept")

    return text


def keep(directory: Path, run: dict[str, Any]) -> None:
    """Keeps the run of a method, in place of the one that was.

    :raises ValueError: If it is not a run, or is too big to be kept, which is for whoever made it to say.
    """
    text = encode(run)
    folder = directory / RUNS_FOLDER
    if folder.is_symlink():
        raise ValueError("The place that runs are kept is a link")
    write_atomically(where(directory, run["candidate"]), text)


def forget(directory: Path, candidate_id: str) -> None:
    """Takes away the run of a method, if there is one, as when the method is taken out of the running."""
    if ID.fullmatch(candidate_id) is None:
        return
    try:
        path = where(directory, candidate_id)
        if not path.parent.is_symlink():
            path.unlink(missing_ok=True)
    except OSError:
        pass


def listing_of(path: Path) -> dict[str, Any]:
    """A piece of data as it is listed: how many files it has, how many bytes, and a hash of their names, sizes, and
    times of change, so that whether it is as it was can be told. It is not a hash of what is in the files, which would
    mean reading all of them each time that a page is shown. A link is not followed, and no more than a number of files
    are listed, which `complete` says.

    :param path: A file, or a folder.
    """
    entries: list[tuple[str, int, int]] = []
    complete = True
    try:
        status = path.lstat()
        if stat.S_ISREG(status.st_mode):
            entries.append((path.name, status.st_size, status.st_mtime_ns))
        elif stat.S_ISDIR(status.st_mode):
            for directory, directories, names in os.walk(path, followlinks=False):
                directories.sort()
                here = Path(directory)
                for name in sorted(names):
                    try:
                        found = (here / name).lstat()
                    except OSError:
                        continue
                    if not stat.S_ISREG(found.st_mode):
                        continue
                    if len(entries) >= MAX_LISTED:
                        complete = False
                        break
                    entries.append(((here / name).relative_to(path).as_posix(), found.st_size, found.st_mtime_ns))
                if not complete:
                    break
    except OSError:
        pass
    digest = hashlib.sha256()
    for name, size, changed in entries:
        digest.update(f"{name}\0{size}\0{changed}\n".encode())

    return {
        "files": len(entries),
        "bytes": sum(size for _, size, _ in entries),
        "fingerprint": digest.hexdigest(),
        "complete": complete,
    }


def preview_of(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """What a page is shown of a result before it asks for the whole: what it is, how long it is as JSON, and the start
    of it."""
    if result is None:
        return None
    text = json.dumps(result.get("value", result), sort_keys=True)

    return {
        "type": result["type"],
        "plain": "value" in result,
        "chars": len(text),
        "start": text[:PREVIEW_CHARS],
        "cut": len(text) > PREVIEW_CHARS,
    }


def summary(run: dict[str, Any], data: dict[str, Any] | None, method: dict[str, str] | None) -> dict[str, Any]:
    """A run as a list of methods shows it: all of it but the result, of which only the start is given, and what is not
    as it was when it was made."""
    return {
        **run,
        "result": preview_of(run["result"]),
        "since": since(run, data, method),
    }


def since(run: dict[str, Any], data: dict[str, Any] | None, method: dict[str, str] | None) -> list[str]:
    """What is not as it was when the run was made: the data, if it is not the same piece as it was listed, or is not
    there, and the method, if it was built again or from other code.

    :param data: The data that the bake-off is run on now, as `listing_of` gives it with its name as `own`, or None.
    :param method: The method's PaperAgent and the commit and image its tools were made of now, or None.
    """
    changed = []
    ran = run["data"]
    if ran is not None and (data is None or data["own"] != ran["own"] or data["fingerprint"] != ran["fingerprint"]):
        changed.append("data")
    if run["method"] is not None and method != run["method"]:
        changed.append("method")

    return changed
