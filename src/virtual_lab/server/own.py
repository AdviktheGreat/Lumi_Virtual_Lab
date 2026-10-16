"""What the researcher gave the lab to use in every conversation: their own data, and the software they have.

Data is a file or a folder. It is uploaded, and kept in the workspace, or it is pointed to where it is on this
machine, and left there. A conversation that runs code is given each piece to read, in Docker under /data and on this
machine where it is, and the lead is told what each is by the description the researcher wrote. Software is a name
and what it is for. It has to be installed where the code runs, which the conversation checks when its code first
runs and tells the lead of if it is not.

A piece of data is found by its file name, so no two have the same name. What is given is kept in the workspace's
own.json, and the files that were uploaded in its own_data.
"""

import os
import re
import stat
import tempfile
from collections.abc import Collection
from pathlib import Path
from typing import Any, BinaryIO

from virtual_lab.chat import describe_size, safe_filename
from virtual_lab.constants import SANDBOX_USER_DATA_DIR
from virtual_lab.execution import ExecutionError, check_mountable
from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.workspace import Workspace

# The most pieces of data, and the most software, that may be given
MAX_OWN_ITEMS = 500

# The most characters of what a piece of data or some software is, and of a name of software
MAX_DESCRIPTION_CHARS = 1000
MAX_SOFTWARE_NAME_CHARS = 100

# What of a file is shown to say what is in it: as many bytes as are read, the lines of them, and of each line, and
# for a folder, how many of what is in it
PREVIEW_BYTES = 64 * 1024
PREVIEW_LINES = 40
PREVIEW_LINE_CHARS = 300
PREVIEW_ENTRIES = 50

CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def check_description(text: Any, what: str) -> str:
    """What a piece of data or some software is, on one line of words.

    :raises ApiError: If there is nothing said, or too much.
    """
    if not isinstance(text, str) or not text.strip():
        raise ApiError(422, "invalid", f"Say what {what} is, so that the lead knows when to use it")
    described = " ".join(text.split())
    if len(described) > MAX_DESCRIPTION_CHARS:
        raise ApiError(422, "invalid", f"What {what} is can be at most {MAX_DESCRIPTION_CHARS} characters")

    return described


def check_name(name: str) -> str:
    """The name a piece of data is found by, which is a place in a container's file system.

    :raises ApiError: If code could not be given it by that name.
    """
    if not name or name in {".", ".."} or CONTROL_CHARACTERS.search(name):
        raise ApiError(422, "invalid", f"{name!r} cannot be the name of a file that code is given")
    try:
        check_mountable(Path(f"{SANDBOX_USER_DATA_DIR}/{name}"), "")
    except ExecutionError:
        raise ApiError(
            422,
            "invalid",
            f"Docker cannot be given a file with a comma, a quote, or a line break in its name, which {name!r} has. "
            "Give it another name.",
        ) from None

    return name


def location(workspace: Workspace, name: str, entry: dict[str, Any]) -> Path:
    """Where a piece of data is on this machine, as it was given: a link is not followed, so that it is found by the
    name it was given."""
    return Path(entry["path"]) if "path" in entry else workspace.own_data_dir / name


def is_mountable(path: Path) -> bool:
    """Whether Docker can be given what a path leads to, which a link that was pointed to may come to lead to
    something it cannot."""
    try:
        check_mountable(path.resolve(), "")
    except (ExecutionError, OSError, RuntimeError):
        return False

    return True


def given(
    workspace: Workspace, data: Collection[str], software: Collection[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """What a session is given, as it takes it: each piece of data by its path, and each piece of software by its
    name, each with what it is. What is not kept any more is left out, and so is data that is no longer there or that
    Docker could no longer be given, so that a conversation can be opened whatever has become of it.

    :param data: The names of the data to give.
    :param software: The names of the software to give.
    """
    kept = workspace.load_own()
    files = {}
    for name in data:
        entry = kept["data"].get(name)
        if entry is None:
            continue
        where = location(workspace, name, entry)
        # Code finds it by the name of its file, so a path that is not called what the data is, as one in a file edited
        # by hand may not be, would be found by another name, or by one that another has
        if where.name == name and where.exists() and is_mountable(where):
            files[str(where)] = entry["description"]

    return files, {name: kept["software"][name] for name in software if name in kept["software"]}


class Own:
    """What the researcher gave the lab, kept in a workspace.

    :param workspace: Where it is kept.
    :param max_upload_bytes: The most bytes of one file that may be uploaded.
    """

    def __init__(self, workspace: Workspace, max_upload_bytes: int) -> None:
        self.workspace = workspace
        self.max_upload_bytes = max_upload_bytes

    # What is kept

    def describe(self) -> dict[str, Any]:
        """Every piece of data and every piece of software, with what a page shows of each."""
        kept = self.workspace.load_own()

        return {
            "data": [self.describe_data(name, entry) for name, entry in kept["data"].items()],
            "software": [{"name": name, "description": description} for name, description in kept["software"].items()],
            "max_upload_bytes": self.max_upload_bytes,
        }

    def describe_data(self, name: str, entry: dict[str, Any]) -> dict[str, Any]:
        """A piece of data as a page shows it: what it is, where it is, file or folder, and how big."""
        shown: dict[str, Any] = {
            "name": name,
            "description": entry["description"],
            "source": "path" if "path" in entry else "uploaded",
            "path": entry.get("path"),
            "kind": "missing",
            "bytes": None,
            "modified": None,
        }
        try:
            status = location(self.workspace, name, entry).stat()
        except OSError:
            return shown
        if stat.S_ISDIR(status.st_mode):
            shown["kind"] = "folder"
        elif stat.S_ISREG(status.st_mode):
            shown.update(kind="file", bytes=status.st_size)
        else:
            return shown
        shown["modified"] = status.st_mtime

        return shown

    # Data

    def add_upload(self, name: str, content: BinaryIO, description: str) -> None:
        """Keeps a file that was uploaded.

        :param name: What it was called, which may have a path, as a browser sends it.
        :param content: What is in it, read as it arrives.
        :param description: What it is.
        :raises ApiError: If what it is is not said, its name is taken or cannot be used, or it is too big.
        """
        described = check_description(description, "the file")
        filename = check_name(safe_filename(name))
        self.check_room(filename)
        directory = self.workspace.own_data_dir
        directory.mkdir(parents=True, exist_ok=True)

        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".upload.", suffix=".part")
        try:
            size = 0
            with os.fdopen(handle, "wb") as file:
                while block := content.read(1 << 20):
                    size += len(block)
                    if size > self.max_upload_bytes:
                        raise ApiError(
                            413,
                            "too_large",
                            f"{filename} is larger than the {describe_size(self.max_upload_bytes)} "
                            "that can be uploaded. Point to it where it is on this machine instead.",
                        )
                    file.write(block)

            def keep(kept: dict[str, dict[str, Any]]) -> None:
                self.check_room(filename, kept)
                kept["data"][filename] = {"description": described}
                os.replace(temporary, directory / filename)

            self.workspace.update_own(keep)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def add_path(self, path: str, description: str) -> None:
        """Keeps a file or folder where it is on this machine, which is given to code as it is, and is not changed.

        :param path: Where it is, as a full path.
        :param description: What it is.
        :raises ApiError: If it is not there, is not a file or folder, is where conversations are kept or holds them,
            or its name is taken or cannot be used.
        """
        described = check_description(description, "it")
        text = path.strip()
        try:
            asked = Path(text).expanduser()
            if not text or CONTROL_CHARACTERS.search(text) or not asked.is_absolute():
                raise ValueError(text)
            where = Path(os.path.abspath(asked))
            source = where.resolve()
            there = source.exists()
        except (OSError, RuntimeError, ValueError):
            raise ApiError(422, "invalid", f"Give the full path of the file or folder, which {text!r} is not") from None
        if not there:
            raise ApiError(422, "invalid", f"There is nothing at {source}")
        if not (source.is_file() or source.is_dir()):
            raise ApiError(422, "invalid", f"{source} is neither a file nor a folder")
        if not where.name:
            raise ApiError(422, "invalid", f"Give the files or folders in {source}, not all of it")
        name = check_name(where.name)
        try:
            check_mountable(source, "")
        except ExecutionError:
            raise ApiError(
                422,
                "invalid",
                f"Docker cannot be given a path with a comma, a quote, or a line break in it, which {source} has. "
                "Move it, or rename what holds it.",
            ) from None
        self.check_apart(source)
        self.check_room(name)

        def keep(kept: dict[str, dict[str, Any]]) -> None:
            self.check_room(name, kept)
            kept["data"][name] = {"description": described, "path": str(where)}

        self.workspace.update_own(keep)

    def check_apart(self, source: Path) -> None:
        """Refuses what is where conversations are kept, or holds them, since code that was given it could change what
        it is to be kept apart from, or what the conversation is run in, and what was uploaded, which is kept
        as uploads.

        :raises ApiError: If it is.
        """
        chats = self.workspace.chats_dir
        uploads = self.workspace.own_data_dir.resolve()
        if source.is_relative_to(chats) or chats.is_relative_to(source):
            raise ApiError(422, "invalid", f"{source} is where conversations are kept, or holds them")
        if source.is_relative_to(uploads) or uploads.is_relative_to(source):
            raise ApiError(422, "invalid", f"{source} is where uploaded files are kept, or holds them")

    def check_room(self, name: str, kept: dict[str, dict[str, Any]] | None = None) -> None:
        """Refuses a name that is taken, and more pieces of data than may be given.

        :param kept: What is kept, if it is being changed, or None to look.
        :raises ApiError: If the name is taken or there is no room.
        """
        data = (kept if kept is not None else self.workspace.load_own())["data"]
        if name in data:
            raise ApiError(
                409,
                "name_taken",
                f"There is data named {name} already. Code finds data by its name, so remove that first, or give "
                "this another name.",
            )
        if len(data) >= MAX_OWN_ITEMS:
            raise ApiError(409, "too_many", f"No more than {MAX_OWN_ITEMS} pieces of data can be given")

    def change_description(self, name: str, description: str) -> None:
        """Says again what a piece of data is.

        :raises ApiError: If there is none by this name, or what it is is not said.
        """
        described = check_description(description, "it")

        def change(kept: dict[str, dict[str, Any]]) -> None:
            if name not in kept["data"]:
                raise not_found("data of yours with that name")
            kept["data"][name]["description"] = described

        self.workspace.update_own(change)

    def remove(self, name: str) -> None:
        """Gives up a piece of data. A file that was uploaded is deleted; what was pointed to is left where it is.

        :raises ApiError: If there is none by this name.
        """

        def forget(kept: dict[str, dict[str, Any]]) -> None:
            entry = kept["data"].get(name)
            if entry is None:
                raise not_found("data of yours with that name")
            if "path" not in entry:
                (self.workspace.own_data_dir / name).unlink(missing_ok=True)
            del kept["data"][name]

        self.workspace.update_own(forget)

    def preview(self, name: str) -> dict[str, Any]:
        """What is at the start of a piece of data: the first lines of a text file, and what is in a folder.

        :raises ApiError: If there is none by this name.
        """
        entry = self.workspace.load_own()["data"].get(name)
        if entry is None:
            raise not_found("data of yours with that name")
        path = location(self.workspace, name, entry)
        if path.is_dir():
            return preview_folder(path)
        if path.is_file():
            return preview_file(path)

        return {"kind": "missing"}

    # Software

    def put_software(self, name: str, description: str) -> None:
        """Keeps some software, in place of any with the same name.

        :raises ApiError: If the name or what it is is not fit to be kept, or there is no room.
        """
        title = " ".join(name.split())
        if not title or len(title) > MAX_SOFTWARE_NAME_CHARS or CONTROL_CHARACTERS.search(title):
            raise ApiError(
                422,
                "invalid",
                f"The name of software is one to {MAX_SOFTWARE_NAME_CHARS} characters, which {name!r} is not",
            )
        described = check_description(description, title)

        def keep(kept: dict[str, dict[str, Any]]) -> None:
            if title not in kept["software"] and len(kept["software"]) >= MAX_OWN_ITEMS:
                raise ApiError(409, "too_many", f"No more than {MAX_OWN_ITEMS} pieces of software can be given")
            kept["software"][title] = described

        self.workspace.update_own(keep)

    def remove_software(self, name: str) -> None:
        """Gives up some software.

        :raises ApiError: If there is none by this name.
        """

        def forget(kept: dict[str, dict[str, Any]]) -> None:
            if name not in kept["software"]:
                raise not_found("software of yours with that name")
            del kept["software"][name]

        self.workspace.update_own(forget)


def check_own_names(names: Any, kept: Collection[str], what: str) -> list[str]:
    """The names of data or software to give a conversation, without repeats, each one that was given to the lab.

    :param what: What they are, as "data" or "software".
    :raises ValueError: If it is not a list of the names of what was given.
    """
    if not isinstance(names, list | tuple):
        raise ValueError(f"The {what} to give is a list of names, not {names!r}")
    if unknown := [name for name in names if not isinstance(name, str) or name not in kept]:
        there_is = ", ".join(kept) or "none"
        raise ValueError(
            f"There is no {what} named {', '.join(map(str, unknown))} given to the lab: there is {there_is}"
        )

    return list(dict.fromkeys(names))


def preview_file(path: Path) -> dict[str, Any]:
    """The first lines of a file, if it is text, which is anything with no zero byte in what is read of it."""
    try:
        with path.open("rb") as file:
            start = file.read(PREVIEW_BYTES + 1)
    except OSError:
        return {"kind": "missing"}
    if b"\x00" in start:
        return {"kind": "binary"}
    truncated = len(start) > PREVIEW_BYTES
    lines = start[:PREVIEW_BYTES].decode("utf-8", errors="replace").splitlines()
    if len(lines) > PREVIEW_LINES:
        lines, truncated = lines[:PREVIEW_LINES], True
    if any(len(line) > PREVIEW_LINE_CHARS for line in lines):
        lines, truncated = [line[:PREVIEW_LINE_CHARS] for line in lines], True

    return {"kind": "text", "lines": lines, "truncated": truncated}


def preview_folder(path: Path) -> dict[str, Any]:
    """What is in a folder, a few of them, folders first."""
    try:
        found = sorted(path.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.casefold()))
    except OSError:
        return {"kind": "missing"}
    entries = [{"name": entry.name, "folder": entry.is_dir()} for entry in found[:PREVIEW_ENTRIES]]

    return {"kind": "folder", "entries": entries, "more": max(len(found) - PREVIEW_ENTRIES, 0)}
