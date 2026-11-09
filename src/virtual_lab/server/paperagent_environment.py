"""What building a PaperAgent's environment leaves in its directory, and how it is read back.

The environment itself is an image in Docker, which is what is run in later, and what is here is the account of it:
environment.json says which commit of the code it was built from, what was planned and what it was built with, and
which image it is, by the hash of its contents; the exact versions that were installed are in a file beside it; and the
output of the build is kept. A build that fails leaves failure.json, which says why as far as the output could tell, and
the output, and is taken away by a build that works.

An environment belongs to the commit of the code it was built from. A record for another commit than the code has now
is not shown.
"""

import json
import shutil
from pathlib import Path
from typing import Any

from virtual_lab.paperagents.environment import FAILURE_KINDS
from virtual_lab.paperagents.repository import COMMIT
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import write_atomically

ENV_DIR = "env"
RECORD_FILE = "environment.json"
FAILURE_FILE = "failure.json"
LOG_FILE = "build.log"
LOCK_NAMES = ("pip-freeze.txt", "conda-explicit.txt")

# What a record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1


def env_path(directory: Path) -> Path:
    return directory / ENV_DIR


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_recipe(value: Any) -> bool:
    return isinstance(value, dict) and value.get("kind") in ("pip", "conda") and isinstance(value.get("steps"), list)


def is_record(value: Any) -> bool:
    """Whether what a file holds is a record of an environment that was built: the commit, the image, the lock, and what
    it was built from and with."""
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        return False
    image, lock, check = value.get("image"), value.get("lock"), value.get("pip_check")

    return (
        isinstance(value.get("commit"), str)
        and COMMIT.fullmatch(value["commit"]) is not None
        and isinstance(value.get("built_at"), str)
        and is_recipe(value.get("recipe"))
        and isinstance(value.get("limits"), dict)
        and isinstance(image, dict)
        and isinstance(image.get("tag"), str)
        and isinstance(image.get("id"), str)
        and image["id"].startswith("sha256:")
        and isinstance(lock, dict)
        and lock.get("name") in LOCK_NAMES
        and isinstance(lock.get("packages"), int)
        and isinstance(value.get("python"), str)
        and isinstance(check, dict)
        and isinstance(check.get("ok"), bool)
        and isinstance(value.get("steps"), list)
        and is_number(value.get("duration"))
    )


def is_failure(value: Any) -> bool:
    """Whether what a file holds is a record of a build that failed."""
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        return False
    failure = value.get("failure")

    return (
        isinstance(value.get("commit"), str)
        and COMMIT.fullmatch(value["commit"]) is not None
        and isinstance(value.get("failed_at"), str)
        and is_recipe(value.get("recipe"))
        and isinstance(value.get("limits"), dict)
        and isinstance(failure, dict)
        and failure.get("kind") in FAILURE_KINDS
        and isinstance(failure.get("title"), str)
        and isinstance(failure.get("detail"), str)
        and isinstance(failure.get("tail"), list)
    )


def stored(directory: Path) -> dict[str, Any] | None:
    """The record of an environment, whatever commit it is of, which is what is looked at to take its image away."""
    record = read_json(env_path(directory) / RECORD_FILE)

    return record if is_record(record) else None


def load(directory: Path, commit: str | None) -> dict[str, Any] | None:
    """The record of the environment that was built, if it is of this commit and its lock is there."""
    record = stored(directory)
    if record is None or commit is None or record["commit"] != commit:
        return None

    return record if (env_path(directory) / record["lock"]["name"]).is_file() else None


def load_failure(directory: Path, commit: str | None) -> dict[str, Any] | None:
    """The record of the last build that failed, if it was of this commit."""
    record = read_json(env_path(directory) / FAILURE_FILE)
    if commit is None or not is_failure(record) or record["commit"] != commit:
        return None

    return record


def keep(directory: Path, record: dict[str, Any], lock: str, log: list[str]) -> None:
    """Keeps an environment that was built, and what a build that failed left is taken away. The record is written
    last, so that it never names a lock that is not there."""
    folder = env_path(directory)
    folder.mkdir(exist_ok=True)
    (folder / FAILURE_FILE).unlink(missing_ok=True)
    (folder / RECORD_FILE).unlink(missing_ok=True)
    write_atomically(folder / record["lock"]["name"], lock.encode("utf-8"))
    write_atomically(folder / LOG_FILE, "\n".join(log).encode("utf-8"))
    write_atomically(folder / RECORD_FILE, json.dumps(record, indent=4).encode("utf-8"))


def keep_failure(directory: Path, record: dict[str, Any], log: list[str]) -> None:
    """Keeps why a build failed, and its output, for as long as there is not one that works."""
    folder = env_path(directory)
    folder.mkdir(exist_ok=True)
    write_atomically(folder / LOG_FILE, "\n".join(log).encode("utf-8"))
    write_atomically(folder / FAILURE_FILE, json.dumps(record, indent=4).encode("utf-8"))


def read_lock(directory: Path, record: dict[str, Any]) -> str:
    return (env_path(directory) / record["lock"]["name"]).read_text(encoding="utf-8", errors="replace")


def read_log(directory: Path) -> list[str] | None:
    """The output of the last build, as its lines, or None if there is none."""
    path = env_path(directory) / LOG_FILE
    if path.is_symlink() or not path.is_file():
        return None

    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def forget(directory: Path) -> None:
    """Removes the account of an environment, with its lock and its log. The image is taken away before this, by its
    name, and not by what a file says."""
    shutil.rmtree(env_path(directory), ignore_errors=True)
