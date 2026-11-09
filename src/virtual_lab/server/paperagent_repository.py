"""What fetching a PaperAgent's code leaves in its directory, and how it is read back.

The project's files are kept in repo/, as they were at the commit that was fetched, with the means to write to them
taken away: they are there to be read, and to be copied into an environment later. What was found of them is kept in
intake.json, with where they came from and the commit, so that it is the same code when it is used again.

A clone belongs to the address it was fetched from. One that is for another address than the agent's now has is not
shown, and is taken away when the address is changed.
"""

import json
import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from virtual_lab.paperagents.repository import COMMIT, RepositoryError, check_ref
from virtual_lab.paperagents.stock import is_stock
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import write_atomically

REPO_DIR = "repo"
INTAKE_FILE = "intake.json"

# What a record of an intake says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1

# What on a host that is not a project, though it is at an address that is like one
NOT_PROJECTS = frozenset(
    {
        "orgs",
        "sponsors",
        "features",
        "topics",
        "collections",
        "settings",
        "marketplace",
        "about",
        "pricing",
        "login",
        "join",
        "apps",
        "enterprise",
        "explore",
        "search",
        "notifications",
        "issues",
        "pulls",
        "codespaces",
        "readme",
        "security",
        "site",
        "trending",
        "users",
    }
)


def repo_path(directory: Path) -> Path:
    return directory / REPO_DIR


def read_only(folder: Path) -> None:
    """Takes the means to write away from the files of a folder, so that nothing changes what was fetched. The folders
    stay as they are, so that the whole can be removed."""
    for current, _, files in os.walk(folder):
        for name in files:
            path = os.path.join(current, name)
            try:
                os.chmod(path, os.lstat(path).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
            except OSError:
                continue


def remove_tree(folder: Path) -> None:
    """Removes a folder, with files that cannot be written to, which a platform may not remove."""

    def mend(function: Callable[[str], Any], path: str, error: BaseException) -> None:
        os.chmod(path, stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)
        function(path)

    shutil.rmtree(folder, onexc=mend)


def forget(directory: Path) -> None:
    """Removes the code that was fetched, and what was found of it."""
    (directory / INTAKE_FILE).unlink(missing_ok=True)
    for name in (REPO_DIR, f"{REPO_DIR}.new", f"{REPO_DIR}.old"):
        if (directory / name).exists():
            remove_tree(directory / name)


def keep(directory: Path, fetched: Path, intake: dict[str, Any]) -> None:
    """Puts the code that was fetched in place of what was kept, and says what it is. The record is only there when
    the files are, so that it never names code that is not: what was kept is taken away first, and the record is written
    last."""
    (directory / INTAKE_FILE).unlink(missing_ok=True)
    for name in (f"{REPO_DIR}.new", f"{REPO_DIR}.old"):
        if (directory / name).exists():
            remove_tree(directory / name)
    read_only(fetched)
    folder = repo_path(directory)
    aside = directory / f"{REPO_DIR}.old"
    if folder.exists():
        os.replace(folder, aside)
    os.replace(fetched, folder)
    if aside.exists():
        remove_tree(aside)
    write_atomically(directory / INTAKE_FILE, json.dumps({"schema": SCHEMA, **intake}, indent=4).encode("utf-8"))


def is_intake(value: Any) -> bool:
    """Whether what a file holds is an intake's: where the code was from, which commit, when, how much was allowed,
    and the stock that was taken of it."""
    if not isinstance(value, dict):
        return False
    try:
        check_ref(value.get("ref"))
    except RepositoryError:
        return False

    return (
        value.get("schema") == SCHEMA
        and isinstance(value.get("url"), str)
        and isinstance(value.get("commit"), str)
        and COMMIT.fullmatch(value["commit"]) is not None
        and isinstance(value.get("cloned_at"), str)
        and isinstance(value.get("limit_bytes"), int)
        and not isinstance(value["limit_bytes"], bool)
        and is_stock(value.get("stock"))
    )


def load(directory: Path, url: str | None) -> dict[str, Any] | None:
    """What was found of the code that was fetched, if there is code, and it is of this address."""
    intake = read_json(directory / INTAKE_FILE)
    folder = repo_path(directory)
    if is_intake(intake) and url is not None and intake["url"] == url and folder.is_dir() and not folder.is_symlink():
        return intake

    return None


def candidates(
    resources: dict[str, Any], chosen: str | None, as_repo: Callable[[str], str | None]
) -> list[dict[str, Any]]:
    """The projects that the paper's text points to, for the person to say which, if any, is its code.

    :param resources: What reading the paper found, of which its links are looked at.
    :param chosen: The address that the agent has now.
    :param as_repo: Gives the address of the project that a link is to, in the form that is kept, or None if it is not
        to one.
    :return: Each project once, with the places in the paper that give it, the first of which says whether it said it
        was of the code; those that the paper says are of the code first.
    """
    found: dict[str, dict[str, Any]] = {}
    for fact in resources.get("links", []):
        url = as_repo(fact["url"])
        if url is None:
            continue
        entry = found.setdefault(url, {"url": url, "role": fact["role"], "chosen": url == chosen, "facts": []})
        if fact["role"] == "code":
            entry["role"] = "code"
        entry["facts"].append({"id": fact["id"], "quote": fact["quote"], "anchor": fact["anchor"]})

    return sorted(found.values(), key=lambda entry: (entry["role"] != "code", entry["facts"][0]["anchor"]["start"]))


def is_project(segments: list[str]) -> bool:
    """Whether the path of an address at a host that holds code is of a project, and not of one of the pages that the
    host has at an address like one."""
    return len(segments) >= 2 and segments[0].lower() not in NOT_PROJECTS


def facts_of_paper(reading: dict[str, Any]) -> dict[str, list[dict[str, Any]]] | None:
    """What of a reading bears on whether the code can be used: the data it names, the places it links, what it says of
    where data is, and what it says the code is licensed as. None if the paper has not been read through, since what
    it does not say is not known until it has been."""
    if not reading["complete"]:
        return None

    return {
        "datasets": reading["card"].get("datasets", []),
        "links": reading["resources"].get("links", []),
        "availability": reading["resources"].get("availability", []),
        "licenses": reading["resources"].get("licenses", []),
    }
