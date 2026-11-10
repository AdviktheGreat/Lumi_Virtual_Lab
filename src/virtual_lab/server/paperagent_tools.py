"""What making a PaperAgent's tools leaves in its directory, and how it is read back.

tools/<name>/ is one tool: its wrapper (wrapper.py, which calls the paper's own function and does nothing else) and
what is known of it (tool.json: its signature, its tier, and the evidence for the tier, which is each call that was
made again and what it gave). checks/tools.json is the account of the making: which commit of the code and which image
of the environment it was of, which reference run the tools were made from, what was allowed, whether it came to its
end, which tools were made, and which functions were not, with why. A tool is written before the account names it, so
that the account never names one that is not there, and what was made before a job was stopped is kept.

Tools belong to the commit, the image, and the reference run they were made from. Tools of another are not shown. A
tool is read back only if its wrapper is what was hashed when it was made and still passes the check that it calls the
paper's function and does nothing else, so that a file that was edited is not a tool. What a tool of tier A says is that
it gave again what the tutorials got, for the arguments they passed. It does not say that what it gives is right.
"""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from virtual_lab.constants import MAX_FUNCTION_NAME_CHARS
from virtual_lab.paperagents import wrappers
from virtual_lab.paperagents.repository import COMMIT
from virtual_lab.paperagents.stock import matches
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import write_atomically

CHECKS_DIR = "checks"
RECORD_FILE = "tools.json"
TOOLS_DIR = "tools"
TOOL_FILE = "tool.json"

# What a record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1
# The most of a wrapper that is read back, which is far more than one is
MAX_WRAPPER_BYTES = 1 << 20
# The most that is kept of a tool's record, and of what a tool is told of
MAX_TOOL_BYTES = 8 << 20

NUMBER = (int, float)
SUMMARY = {
    "name": str,
    "tier": str,
    "module": str,
    "function": str,
    "parameters": [str],
    "checked": int,
    "recorded": int,
    "repeats": int,
    "tutorials": [str],
}
DROPPED = {"name": str, "module": str, "function": str, "kind": str, "reason": str, "details": [str], "calls": int}
UNUSED = {"tutorial": str, "reason": str}
RECORD = {
    "schema": int,
    "commit": str,
    "image_id": str,
    "reference": {"started_at": str, "finished_at": str},
    "started_at": str,
    "finished_at": (str, None),
    "complete": bool,
    "limits": dict,
    "data": bool,
    "tools": [SUMMARY],
    "dropped": [DROPPED],
    "unused": [UNUSED],
}
TOOL = {
    "schema": int,
    "name": str,
    "tier": str,
    "repo": {"module": str, "function": str, "file": str, "line": int},
    "wrapper": str,
    "wrapper_sha256": str,
    "signature": [{"name": str, "type": str, "required": bool}],
    "description": str,
    "evidence": {
        "kind": str,
        "image_id": str,
        "tolerance": {"relative": NUMBER, "absolute": NUMBER},
        "repeats": int,
        "checked": int,
        "recorded": int,
        "cases": [dict],
        "skipped": [dict],
        "repairs": [dict],
    },
}


def checks_path(directory: Path) -> Path:
    return directory / CHECKS_DIR


def tools_path(directory: Path) -> Path:
    return directory / TOOLS_DIR


def is_name(name: Any) -> bool:
    """Whether something is a name that a tool is kept under, which is that of a function, so that nothing that leads
    out of the folder of tools is."""
    return (
        isinstance(name, str)
        and len(name) <= MAX_FUNCTION_NAME_CHARS
        and wrappers.IDENTIFIER.fullmatch(name) is not None
    )


def tool_path(directory: Path, name: str) -> Path:
    """Where a tool is kept.

    :raises ValueError: If it is not a name that a tool is kept under.
    """
    if not is_name(name):
        raise ValueError("That is not the name of a tool")

    return tools_path(directory) / name


def is_record(value: Any) -> bool:
    """Whether what a file holds is the account of the making of tools: of one commit, one image, and one reference run,
    in the shape that is kept."""
    return (
        matches(RECORD, value)
        and value["schema"] == SCHEMA
        and COMMIT.fullmatch(value["commit"]) is not None
        and value["image_id"].startswith("sha256:")
        and all(is_name(tool["name"]) for tool in value["tools"])
        and len({tool["name"].lower() for tool in value["tools"]}) == len(value["tools"])
    )


def stored(directory: Path) -> dict[str, Any] | None:
    """The account of the making of tools, whatever it was of."""
    record = read_json(checks_path(directory) / RECORD_FILE)

    return record if is_record(record) else None


def load(
    directory: Path, commit: str | None, image_id: str | None, reference: dict[str, Any] | None
) -> dict[str, Any] | None:
    """The account of the tools that were made of this commit, in this image, from this reference run, with only the
    tools whose files are there.

    :param reference: The account of the reference run that is kept now, which is the one that tools are made from.
    """
    record = stored(directory)
    if record is None or commit is None or image_id is None or reference is None:
        return None
    if record["commit"] != commit or record["image_id"] != image_id:
        return None
    if record["reference"] != {"started_at": reference["started_at"], "finished_at": reference["finished_at"]}:
        return None
    present = [
        tool
        for tool in record["tools"]
        if not tool_path(directory, tool["name"]).is_symlink()
        and (tool_path(directory, tool["name"]) / TOOL_FILE).is_file()
        and (tool_path(directory, tool["name"]) / wrappers.WRAPPER_FILE).is_file()
    ]

    return {**record, "tools": present}


def is_tool(value: Any) -> bool:
    return (
        matches(TOOL, value)
        and value["schema"] == SCHEMA
        and value["tier"] == wrappers.TIER
        and value["wrapper"] == wrappers.WRAPPER_FILE
        and is_name(value["name"])
    )


def read_text(path: Path, most: int) -> str | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > most:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def load_tool(directory: Path, name: str) -> dict[str, Any] | None:
    """One tool as it is kept, with its wrapper's code, if what is kept is a tool: its record is in the shape that is
    written, and its wrapper is what was hashed when it was made, and still calls the paper's function and does nothing
    else."""
    if not is_name(name):
        return None
    folder = tool_path(directory, name)
    if folder.is_symlink() or not folder.is_dir():
        return None
    text = read_text(folder / TOOL_FILE, MAX_TOOL_BYTES)
    source = read_text(folder / wrappers.WRAPPER_FILE, MAX_WRAPPER_BYTES)
    if text is None or source is None:
        return None
    try:
        record = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if not is_tool(record) or record["name"] != name:
        return None
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != record["wrapper_sha256"]:
        return None
    try:
        wrapped = wrappers.check_wrapper(source, record["repo"]["module"], record["repo"]["function"])
    except wrappers.WrapperError:
        return None
    if wrapped.name != name:
        return None

    return {**record, "source": source}


def save(directory: Path, record: dict[str, Any]) -> None:
    folder = checks_path(directory)
    folder.mkdir(exist_ok=True)
    write_atomically(folder / RECORD_FILE, json.dumps(record, indent=4).encode("utf-8"))


def begin(directory: Path, record: dict[str, Any]) -> None:
    """Starts the making of tools in place of what was kept: that is taken away, and the account is of a making with
    nothing yet."""
    forget(directory)
    tools_path(directory).mkdir(exist_ok=True)
    save(directory, record)


def summary_of(tool: dict[str, Any]) -> dict[str, Any]:
    """What the account says of a tool, which is enough to list it."""
    evidence = tool["evidence"]

    return {
        "name": tool["name"],
        "tier": tool["tier"],
        "module": tool["repo"]["module"],
        "function": tool["repo"]["function"],
        "parameters": [parameter["name"] for parameter in tool["signature"]],
        "checked": evidence["checked"],
        "recorded": evidence["recorded"],
        "repeats": evidence["repeats"],
        "tutorials": sorted({case["tutorial"] for case in evidence["cases"]}),
    }


def keep_tool(directory: Path, record: dict[str, Any], tool: dict[str, Any], source: str) -> dict[str, Any]:
    """Keeps a tool, and then says in the account that it was made.

    :return: The account as it is now.
    """
    folder = tool_path(directory, tool["name"])
    folder.mkdir(parents=True, exist_ok=True)
    write_atomically(folder / wrappers.WRAPPER_FILE, source.encode("utf-8"))
    write_atomically(folder / TOOL_FILE, json.dumps(tool, indent=4).encode("utf-8"))
    kept = {**record, "tools": [*record["tools"], summary_of(tool)]}
    save(directory, kept)

    return kept


def keep_dropped(directory: Path, record: dict[str, Any], dropped: dict[str, Any]) -> dict[str, Any]:
    """Says in the account that a function was not made a tool, and why."""
    kept = {**record, "dropped": [*record["dropped"], dropped]}
    save(directory, kept)

    return kept


def finish(directory: Path, record: dict[str, Any], not_tried: list[dict[str, Any]], at: str) -> dict[str, Any]:
    """Says in the account that the making came to its end, and which functions were not tried."""
    kept = {**record, "complete": True, "finished_at": at, "dropped": [*record["dropped"], *not_tried]}
    save(directory, kept)

    return kept


def forget(directory: Path) -> None:
    """Removes the account of the making of tools, and the tools. The account goes first, so that it never names what
    is gone."""
    (checks_path(directory) / RECORD_FILE).unlink(missing_ok=True)
    shutil.rmtree(tools_path(directory), ignore_errors=True)
