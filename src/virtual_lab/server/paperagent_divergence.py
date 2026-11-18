"""What looking at the claims that did not reproduce is given, read back from what is kept of a PaperAgent.

Nothing is kept of the looking itself. It is made each time it is asked for, from the account of the trying of the
claims when that is of the run of the tutorials and the claims that are kept now (paperagent_reproduction.py), the
record of each tutorial that a claim was held to, the environment that the run was made in, what the paper names, and
the paper's text, so that it cannot say what what is kept does not, and is not out of date. A file that is not in the
shape that a reading or a build writes adds nothing, as it may not be if it was edited.
"""

from pathlib import Path
from typing import Any

from virtual_lab.paperagents import diverging, reproducing
from virtual_lab.server import paperagent_environment as kept_environment
from virtual_lab.server import paperagent_reading as kept_reading
from virtual_lab.server import paperagent_reference as kept_reference
from virtual_lab.server.workspace import read_json

# The fields of each fact that are read, which are strings
SOFTWARE_FIELDS = ("name", "version", "quote")
DATASET_FIELDS = ("name", "accession", "quote")
MOST_FACTS = 500


def facts_of(directory: Path, name: str, kind: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
    """The facts of one kind that a reading kept in a file, each with only the fields that are read, and those that are
    not in the shape that a reading writes left out: not a list, or a fact that is not an object, or has no name, or has
    a field that is not text, as it may not if the file was edited."""
    record = read_json(directory / name)
    facts = record.get(kind) if isinstance(record, dict) else None
    if not isinstance(facts, list):
        return []
    found = []
    for fact in facts[:MOST_FACTS]:
        if not isinstance(fact, dict) or not all(isinstance(fact.get(field), str) for field in fields):
            continue
        if fact["name"].strip():
            found.append({field: fact[field] for field in fields})

    return found


def software_of(directory: Path) -> list[dict[str, str]]:
    """The software that the paper names, as it was read."""
    return facts_of(directory, kept_reading.RESOURCES_FILE, "software", SOFTWARE_FIELDS)


def datasets_of(directory: Path) -> list[dict[str, str]]:
    """The data that the paper names, as it was read, before anything that a person did to the card."""
    return facts_of(directory, kept_reading.CARD_FILE, "datasets", DATASET_FIELDS)


def paper_text(paper_directory: Path) -> str | None:
    """The text that was kept of the paper, or None if none is."""
    document = kept_reading.load_document(paper_directory)

    return document.text[: diverging.MAX_PAPER_CHARS] if document is not None else None


def environment_of(directory: Path, reference: dict[str, Any]) -> tuple[str | None, str | None]:
    """The Python that the environment was built with and the list of what was installed in it, if the environment that
    is kept is the image that the tutorials were run in, and nothing if it is not."""
    record = kept_environment.load(directory, reference["commit"])
    if record is None or record["image"]["id"] != reference["image_id"]:
        return None, None

    return record["python"], kept_environment.read_lock(directory, record)


def evidence_of(
    directory: Path, paper_directory: Path, reference: dict[str, Any], tried: dict[str, Any], repo: Path
) -> diverging.Evidence:
    """What a claim that did not reproduce is looked at against.

    :param reference: The account of the reference run that the claims were held to.
    :param tried: The account of the trying of the claims, which is of that run.
    :param repo: The code that was fetched, which is read as text for what each tutorial sets and never run.
    """
    python, lock = environment_of(directory, reference)
    ids: dict[str, str] = {}
    for entry in tried["claims"]:
        if entry["link"] is not None and entry["status"] in (reproducing.PARTLY, reproducing.NOT_REPRODUCED):
            ids[entry["link"]["tutorial"]["path"]] = entry["link"]["tutorial"]["id"]
    details = {}
    for path, identifier in ids.items():
        detail = kept_reference.load_detail(directory, reference, identifier)
        if detail is not None:
            details[path] = detail

    return diverging.Evidence(
        python=python,
        lock=lock,
        software=software_of(directory),
        datasets=datasets_of(directory),
        data=reference["data"],
        paper=paper_text(paper_directory),
        details=details,
        text_of=lambda path: reproducing.tutorial_text(repo, path),
    )
