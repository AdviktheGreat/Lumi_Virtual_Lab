"""What reading a paper leaves in a PaperAgent's directory, and how it is read back.

The text of the paper is kept in paper/ with where its pages and sections are, since that is what a place in the paper
counts in. What each chunk came to is kept in log/reading/, a file for each, as soon as it is read, so that a reading
that is stopped, or ends at its limit, or is cut off, has lost only the chunk it was in, and starts again after the
last one. The claims, the draft of the method card, and the resources the paper names are written from those when a
reading ends, as claims.json, method_card.json, and resources.json.

A reading belongs to the file it was made from, which is told by the file's hash, so that what was read of one paper is
never shown as what another says: a reading of a file that is not the agent's is not seen, and is started again.
"""

import json
import shutil
from pathlib import Path
from typing import Any

from virtual_lab.paperagents.anchors import Document, document_of
from virtual_lab.paperagents.reading import assemble, reading_of
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import write_atomically

# Where the reading of a paper is kept, and what it keeps of the paper's text, in the paper's own directory
LOG_DIR = "log"
READING_DIR = "reading"
CHUNKS_DIR = "chunks"
RUN_FILE = "run.json"
TEXT_FILE = "text.txt"
LAYOUT_FILE = "layout.json"
CLAIMS_FILE = "claims.json"
CARD_FILE = "method_card.json"
RESOURCES_FILE = "resources.json"

# What a record of a reading says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1

# How much of the paper is given around a quote, and the most of it that a page may ask for
PASSAGE_CONTEXT = 400
MAX_PASSAGE_CHARS = 5000


def reading_dir(directory: Path) -> Path:
    return directory / LOG_DIR / READING_DIR


def save_text(paper_directory: Path, document: Document) -> None:
    """Keeps the paper's text, and where its pages and sections are. The text is written exactly as it is, since the
    places in it count its characters."""
    write_atomically(paper_directory / TEXT_FILE, document.text.encode("utf-8"))
    write_atomically(paper_directory / LAYOUT_FILE, json.dumps(document.to_dict(), indent=4).encode("utf-8"))


def load_document(paper_directory: Path) -> Document | None:
    """The text that was kept of a paper, with its layout, or None if none is, or it cannot be read."""
    try:
        text = (paper_directory / TEXT_FILE).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    return document_of(text, read_json(paper_directory / LAYOUT_FILE))


def saved_run(directory: Path, file_sha256: str | None) -> dict[str, Any] | None:
    """The record of how a reading was begun, if it is of this file and of this version of what reads."""
    run = read_json(reading_dir(directory) / RUN_FILE)
    if (
        isinstance(run, dict)
        and run.get("schema") == SCHEMA
        and file_sha256 is not None
        and run.get("file_sha256") == file_sha256
        and isinstance(run.get("version"), int)
        and isinstance(run.get("chunks"), int)
        and not isinstance(run.get("chunks"), bool)
    ):
        return run

    return None


def begin_run(directory: Path, run: dict[str, Any]) -> None:
    """Records how a reading is begun. What was kept of another reading, of another file or with other sizes of chunk,
    or by another version of what reads, is removed, since it is not of these chunks."""
    earlier = read_json(reading_dir(directory) / RUN_FILE)
    same = isinstance(earlier, dict) and all(
        earlier.get(name) == run[name] for name in ("schema", "version", "file_sha256", "chunk_size", "chunk_overlap")
    )
    if not same:
        shutil.rmtree(reading_dir(directory), ignore_errors=True)
    (reading_dir(directory) / CHUNKS_DIR).mkdir(parents=True, exist_ok=True)
    write_atomically(reading_dir(directory) / RUN_FILE, json.dumps(run, indent=4).encode("utf-8"))


def end_run(directory: Path, run: dict[str, Any]) -> None:
    """Records when a reading ended, whether it read the paper through or stopped."""
    write_atomically(
        reading_dir(directory) / RUN_FILE, json.dumps({**run, "finished_at": utc_timestamp()}, indent=4).encode("utf-8")
    )


def save_chunk(directory: Path, record: dict[str, Any]) -> None:
    write_atomically(
        reading_dir(directory) / CHUNKS_DIR / f"{record['number']:05d}.json",
        json.dumps(record, indent=1).encode("utf-8"),
    )


def saved_chunks(directory: Path) -> dict[int, dict[str, Any]]:
    """What each chunk that has been read came to, by its number."""
    found = {}
    folder = reading_dir(directory) / CHUNKS_DIR
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            record = read_json(path)
            if reading_of(record) and path.name == f"{record['number']:05d}.json":
                found[record["number"]] = record

    return found


def write_files(directory: Path, results: dict[int, dict[str, Any]]) -> None:
    """Writes what the chunks that were read show, as the files of the claims, the method card, and the resources."""
    files = assemble(results.values(), SCHEMA)
    for name, key in ((CLAIMS_FILE, "claims"), (CARD_FILE, "method_card"), (RESOURCES_FILE, "resources")):
        write_atomically(directory / name, json.dumps(files[key], indent=4).encode("utf-8"))


def forget(directory: Path) -> None:
    """Removes everything that was kept of a reading, and of the text it was made from."""
    shutil.rmtree(reading_dir(directory), ignore_errors=True)
    # The log has more in it when more of the steps are done, so it is only taken away if this was all there was
    try:
        (directory / LOG_DIR).rmdir()
    except OSError:
        pass
    for name in (CLAIMS_FILE, CARD_FILE, RESOURCES_FILE):
        (directory / name).unlink(missing_ok=True)
    for name in (TEXT_FILE, LAYOUT_FILE):
        (directory / "paper" / name).unlink(missing_ok=True)


def describe(directory: Path, file_sha256: str | None) -> dict[str, Any]:
    """What has been read of a paper: how far it has got, what it cost, and the claims, the draft of the method card,
    and the resources, each fact with its quote and where that is. All of it is made from what the chunks came to, so
    that it never says more than they do."""
    run = saved_run(directory, file_sha256)
    results = saved_chunks(directory) if run is not None else {}
    counts = {
        status: sum(1 for record in results.values() if record["status"] == status)
        for status in ("read", "skipped", "failed")
    }
    dropped = {
        reason: sum(
            record["dropped"].get(reason, 0)
            for record in results.values()
            if isinstance(record["dropped"].get(reason, 0), int)
        )
        for reason in ("quote", "detail")
    }
    costs = [record["usage"].get("cost") for record in results.values()]
    files = assemble(results.values(), SCHEMA)

    return {
        "chunks": run["chunks"] if run is not None else None,
        "read": counts["read"],
        "skipped": counts["skipped"],
        "failed": counts["failed"],
        "dropped": dropped,
        "cost": None if any(not isinstance(cost, int | float) for cost in costs) else sum(costs),
        "calls": sum(record["usage"].get("num_calls", 0) for record in results.values()),
        "models": sorted({str(record.get("model")) for record in results.values() if record["status"] != "skipped"}),
        "characters": run.get("characters") if run is not None else None,
        "truncated_from": run.get("truncated_from") if run is not None else None,
        "finished_at": run.get("finished_at") if run is not None else None,
        "claims": files["claims"]["claims"],
        "card": {key: value for key, value in files["method_card"].items() if key != "schema"},
        "resources": {key: value for key, value in files["resources"].items() if key != "schema"},
    }


def passage(document: Document, start: int, end: int) -> dict[str, Any]:
    """The words at a place in the paper, with some of what comes before and after, so that a quote is seen where it is.

    :raises ValueError: If the place is not in the text, or is longer than a page is given.
    """
    if not 0 <= start < end <= len(document.text) or end - start > MAX_PASSAGE_CHARS:
        raise ValueError(
            f"A place in the paper is from one character to {MAX_PASSAGE_CHARS:,}, within its {len(document.text):,}"
        )
    anchor = document.anchor(start, end)

    return {
        **anchor,
        "before": document.text[max(start - PASSAGE_CONTEXT, 0) : start],
        "text": document.text[start:end],
        "after": document.text[end : end + PASSAGE_CONTEXT],
    }
