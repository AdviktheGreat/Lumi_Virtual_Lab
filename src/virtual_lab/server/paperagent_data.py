"""What fetching the data of a PaperAgent leaves in its directory, and how it is read back.

The files are kept in data/, in a folder for each place they were fetched from (data/zenodo/123456/, ...), under the
names the place gave them. What is there is told by data.json: for each place, where it is, what it was called and
licensed as, and, for each file, how big it is, the SHA-256 of it, the checksum the place gave if it gave one, which it
matched, since a file that did not is not kept, the address it was fetched from, and when. The record is written after
the file is in place, and what it names is checked against what is on disk each time it is shown.

data.json also says which of the person's own data stands in for data that the paper used. That is only a name, from the
Data page, and nothing is copied: the data stays where it is, as theirs.

Nothing in the record is trusted to be a path: each path is worked out again from the place and the name, and a record
that has one that is not what that comes to is not shown.
"""

import json
import shutil
from pathlib import Path
from typing import Any

from virtual_lab.paperagents.data import SOURCES, Reference, folder_of, safe_path
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import write_atomically

DATA_DIR = "data"
RECORD_FILE = "data.json"

# What a record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1
MAX_STAND_INS = 50
SHA256_LENGTH = 64
ALGORITHMS = ("md5", "sha256")


def data_path(directory: Path) -> Path:
    return directory / DATA_DIR


def is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_text(value: Any) -> bool:
    return isinstance(value, str)


def is_file(value: Any, folder: str) -> bool:
    """Whether what a record says of a file is of one that is kept in this folder, whose path is what the folder and
    the name come to."""
    if not isinstance(value, dict):
        return False
    checksum = value.get("checksum")
    digest = value.get("sha256")

    return (
        isinstance(value.get("name"), str)
        and safe_path(value["name"]) is not None
        and value.get("path") == f"{folder}/{value['name']}"
        and is_count(value.get("bytes"))
        and isinstance(digest, str)
        and len(digest) == SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in digest)
        and (
            checksum is None
            or (
                isinstance(checksum, dict)
                and checksum.get("algorithm") in ALGORITHMS
                and isinstance(checksum.get("value"), str)
            )
        )
        and is_text(value.get("url"))
        and is_text(value.get("fetched_at"))
    )


def is_source(value: Any) -> bool:
    """Whether what a record says of a place is of one that is fetched from, with files that are kept where they should
    be."""
    if not isinstance(value, dict) or value.get("source") not in SOURCES or not is_text(value.get("reference")):
        return False
    reference = Reference(value["source"], value["reference"])
    license = value.get("license")

    return (
        value.get("key") == reference.key
        and value.get("folder") == folder_of(reference)
        and is_text(value.get("label"))
        and is_text(value.get("title"))
        and (license is None or isinstance(license, dict))
        and isinstance(value.get("files"), list)
        and all(is_file(file, value["folder"]) for file in value["files"])
    )


def is_stand_in(value: Any) -> bool:
    """Whether what a record says of data that stands in for a paper's is of one."""
    return (
        isinstance(value, dict)
        and all(isinstance(value.get(name), str) and value[name] for name in ("key", "name", "own"))
        and is_text(value.get("set_at"))
    )


def empty() -> dict[str, Any]:
    return {"schema": SCHEMA, "sources": [], "stand_ins": []}


def load(directory: Path) -> dict[str, Any]:
    """What is kept of an agent's data: the places files were fetched from, and the data that stands in. What a record
    says that is not fit, as it may not be if it was edited, is left out."""
    record = read_json(directory / RECORD_FILE)
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        return empty()
    sources = record.get("sources") if isinstance(record.get("sources"), list) else []
    stand_ins = record.get("stand_ins") if isinstance(record.get("stand_ins"), list) else []

    return {
        "schema": SCHEMA,
        "sources": [source for source in sources if is_source(source)],
        "stand_ins": [stand_in for stand_in in stand_ins if is_stand_in(stand_in)][:MAX_STAND_INS],
    }


def save(directory: Path, record: dict[str, Any]) -> None:
    write_atomically(directory / RECORD_FILE, json.dumps(record, indent=4).encode("utf-8"))


def kept_names(record: dict[str, Any], key: str) -> set[str]:
    """The names of the files that are kept of a place."""
    return {file["name"] for source in record["sources"] if source["key"] == key for file in source["files"]}


def totals(record: dict[str, Any]) -> dict[str, int]:
    files = [file for source in record["sources"] for file in source["files"]]

    return {"files": len(files), "bytes": sum(file["bytes"] for file in files)}


def has_data(record: dict[str, Any]) -> bool:
    """Whether there is something for the agent to use: a file that was fetched, or data of the person's own."""
    return bool(record["sources"] or record["stand_ins"])


def with_file(
    record: dict[str, Any],
    reference: Reference,
    label: str,
    title: str,
    license: dict[str, Any] | None,
    file: dict[str, Any],
) -> dict[str, Any]:
    """The record, with a file that was kept added to its place, which is added if it is not there."""
    folder = folder_of(reference)
    sources = [dict(source) for source in record["sources"]]
    found = next((source for source in sources if source["key"] == reference.key), None)
    if found is None:
        found = {
            "key": reference.key,
            "source": reference.source,
            "reference": reference.id,
            "label": label,
            "url": reference.url,
            "title": title,
            "license": license,
            "folder": folder,
            "files": [],
        }
        sources.append(found)
    found["files"] = [kept for kept in found["files"] if kept["name"] != file["name"]] + [file]

    return {**record, "sources": sources}


def present(directory: Path, file: dict[str, Any]) -> bool:
    """Whether a file that the record names is on disk and is the size that was written."""
    path = data_path(directory) / file["path"]
    try:
        return not path.is_symlink() and path.is_file() and path.stat().st_size == file["bytes"]
    except OSError:
        return False


def forget_source(directory: Path, record: dict[str, Any], key: str) -> dict[str, Any]:
    """Takes away the files fetched from a place, with the folder they were in, and what the record says of them."""
    for source in record["sources"]:
        if source["key"] == key:
            folder = data_path(directory) / source["folder"]
            shutil.rmtree(folder, ignore_errors=True)
            try:
                folder.parent.rmdir()
            except OSError:
                pass

    return {**record, "sources": [source for source in record["sources"] if source["key"] != key]}


def forget_files(directory: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Takes away every file that was fetched, and anything else in the folder of them, which a file that was being kept
    when the server stopped may have left. What stands in is not touched."""
    shutil.rmtree(data_path(directory), ignore_errors=True)

    return {**record, "sources": []}
