"""What running a PaperAgent's tutorials leaves in its directory, and how it is read back.

checks/reference.json is the account of the reference run: which commit of the code it was of, which image of the
environment it was run in, what was allowed, whether it came to its end, which tutorials were run with how each ended,
and which were not run, with why. The record of each tutorial is in checks/reference/<id>/detail.json, with the files
it wrote that were small enough in checks/reference/<id>/files/. A tutorial's record is written before the account names
it, so that the account never names one that is not there, and what was run before a run was stopped is kept.

A reference run belongs to the commit and the image it was run with. One for another commit, or another image, is not
shown. What was kept says that the tutorials ran here and what they gave, which is all it says.
"""

import json
import shutil
from pathlib import Path
from typing import Any

from virtual_lab.paperagents.reference import ITEM_ID, is_detail
from virtual_lab.paperagents.repository import COMMIT
from virtual_lab.paperagents.stock import matches
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import write_atomically

CHECKS_DIR = "checks"
RECORD_FILE = "reference.json"
RUNS_DIR = "reference"
DETAIL_FILE = "detail.json"
FILES_DIR = "files"

# What a record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1

NUMBER = (int, float)
SUMMARY = {
    "id": str,
    "path": str,
    "kind": str,
    "status": str,
    "failure": ({"kind": str, "title": str}, None),
    "seconds": NUMBER,
    "runs": int,
    "stable": (bool, None),
    "differs": [str],
    "calls": int,
    "files": int,
    "cells": int,
    "cells_total": int,
}
SKIPPED = {"path": str, "kind": str, "reason": str}
NOT_RUN = {"path": str, "reason": str}
RECORD = {
    "schema": int,
    "commit": str,
    "image_id": str,
    "started_at": str,
    "finished_at": (str, None),
    "complete": bool,
    "limits": dict,
    "data": (dict, None),
    "tutorials": [SUMMARY],
    "skipped": [SKIPPED],
    "more": int,
    "not_run": [NOT_RUN],
}


def checks_path(directory: Path) -> Path:
    return directory / CHECKS_DIR


def runs_path(directory: Path) -> Path:
    return checks_path(directory) / RUNS_DIR


def run_path(directory: Path, tutorial: str) -> Path:
    return runs_path(directory) / tutorial


def files_path(directory: Path, tutorial: str) -> Path:
    """Where the files that a tutorial wrote are kept, which is where a run is told to put them."""
    return run_path(directory, tutorial) / FILES_DIR


def is_record(value: Any) -> bool:
    """Whether what a file holds is the account of a reference run: of one commit and one image, in the shape that is
    kept."""
    return (
        matches(RECORD, value)
        and value["schema"] == SCHEMA
        and COMMIT.fullmatch(value["commit"]) is not None
        and value["image_id"].startswith("sha256:")
        and len({tutorial["id"] for tutorial in value["tutorials"]}) == len(value["tutorials"])
        and all(ITEM_ID.fullmatch(tutorial["id"]) is not None for tutorial in value["tutorials"])
    )


def stored(directory: Path) -> dict[str, Any] | None:
    """The account of a reference run, whatever it was of."""
    record = read_json(checks_path(directory) / RECORD_FILE)

    return record if is_record(record) else None


def load(directory: Path, commit: str | None, image_id: str | None) -> dict[str, Any] | None:
    """The account of the reference run that was made of this commit in this image, with only the tutorials whose
    record is there."""
    record = stored(directory)
    if record is None or commit is None or image_id is None or record["commit"] != commit:
        return None
    if record["image_id"] != image_id:
        return None
    present = [
        tutorial
        for tutorial in record["tutorials"]
        if (run_path(directory, tutorial["id"]) / DETAIL_FILE).is_file()
        and not run_path(directory, tutorial["id"]).is_symlink()
    ]

    return {**record, "tutorials": present}


def load_detail(directory: Path, record: dict[str, Any], tutorial: str) -> dict[str, Any] | None:
    """The record of one tutorial of a reference run, if the account names it and what is kept is what it says."""
    named = next((one for one in record["tutorials"] if one["id"] == tutorial), None)
    if named is None or run_path(directory, tutorial).is_symlink():
        return None
    detail = read_json(run_path(directory, tutorial) / DETAIL_FILE)
    if not is_detail(detail) or detail["id"] != tutorial or detail["path"] != named["path"]:
        return None

    return detail


def save(directory: Path, record: dict[str, Any]) -> None:
    folder = checks_path(directory)
    folder.mkdir(exist_ok=True)
    write_atomically(folder / RECORD_FILE, json.dumps(record, indent=4).encode("utf-8"))


def begin(directory: Path, record: dict[str, Any]) -> None:
    """Starts a reference run in place of what was kept: that is taken away, and the account is of a run with nothing
    yet."""
    forget(directory)
    runs_path(directory).mkdir(parents=True, exist_ok=True)
    save(directory, record)


def keep_tutorial(
    directory: Path, record: dict[str, Any], detail: dict[str, Any], summary: dict[str, Any]
) -> dict[str, Any]:
    """Keeps what came of a tutorial, and then says in the account that it was run. The folder that its files were put
    in is made by the run, if there were any.

    :return: The account as it is now.
    """
    folder = run_path(directory, detail["id"])
    folder.mkdir(parents=True, exist_ok=True)
    write_atomically(folder / DETAIL_FILE, json.dumps(detail, indent=4).encode("utf-8"))
    kept = {**record, "tutorials": [*record["tutorials"], summary]}
    save(directory, kept)

    return kept


def finish(directory: Path, record: dict[str, Any], not_run: list[dict[str, str]], at: str) -> None:
    """Says in the account that the run came to its end, and which tutorials were not run."""
    save(directory, {**record, "complete": True, "finished_at": at, "not_run": not_run})


def forget(directory: Path) -> None:
    """Removes the account of a reference run, with the record of each tutorial and what they wrote. The account goes
    first, so that it never names what is gone."""
    (checks_path(directory) / RECORD_FILE).unlink(missing_ok=True)
    shutil.rmtree(runs_path(directory), ignore_errors=True)
