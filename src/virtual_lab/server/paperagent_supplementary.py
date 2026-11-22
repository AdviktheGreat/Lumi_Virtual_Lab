"""The supplementary files of a PaperAgent's paper: what came with it, such as its supplementary methods, notes, or
tables in a text, which are read with the paper.

They are kept in the agent's supplementary/, under the names they were uploaded with, and its agent.json lists them, in
the order they were added, with how big each is and the SHA-256 of it. Each is a PDF or a text, as the paper is. Its
text is put after the paper's, under a heading that names it, so that a fact found in one is said to be in that file.
A reading is of the paper with the files it had when it was read: adding one, or taking one away, clears what was read.
"""

import re
from pathlib import Path
from typing import Any

from virtual_lab.chat import safe_filename
from virtual_lab.paperagents.anchors import MAX_HEADING_CHARS, Document, document_from, find_sections
from virtual_lab.papers import truncate_text

SUPPLEMENTARY_DIR = "supplementary"
MAX_FILES = 10
HEADING = "# Supplementary file: "
SHA256 = re.compile(r"[0-9a-f]{64}")


def folder_of(directory: Path) -> Path:
    return directory / SUPPLEMENTARY_DIR


def is_file(value: Any) -> bool:
    """Whether what agent.json says of a file is of one: its name, which is one that can be kept, its size, and the
    SHA-256 of it."""
    return (
        isinstance(value, dict)
        and set(value) == {"name", "bytes", "sha256"}
        and isinstance(value["name"], str)
        and bool(value["name"])
        and safe_filename(value["name"]) == value["name"]
        and isinstance(value["bytes"], int)
        and not isinstance(value["bytes"], bool)
        and value["bytes"] >= 0
        and isinstance(value["sha256"], str)
        and SHA256.fullmatch(value["sha256"]) is not None
    )


def is_listing(value: Any) -> bool:
    """Whether what agent.json says of the supplementary files is fit: nothing, or a list of them with no name twice,
    whatever its case, and no more than may be kept."""
    return value is None or (
        isinstance(value, list)
        and len(value) <= MAX_FILES
        and all(is_file(file) for file in value)
        and len({file["name"].casefold() for file in value}) == len(value)
    )


def listed(agent: dict[str, Any]) -> list[dict[str, Any]]:
    """The supplementary files of an agent, in the order they were added."""
    return list(agent.get("supplementary") or [])


def heading(name: str) -> str:
    """The line that a file's text is put under, which is found as a heading, so it is no longer than one may be."""
    return HEADING + name[: MAX_HEADING_CHARS - len(HEADING)]


def document_with(
    pages: list[str], paged: bool, extras: list[tuple[str, list[str]]], max_chars: int | None = None
) -> Document:
    """The text that is read: the paper's, from its pages, and after it the text of each supplementary file under a
    heading of its name. The pages of a PDF paper are its own: a place in a file after it is on none of them.

    :param extras: Each file's name, and its text as read_paper_pages gives it.
    :param max_chars: The most of the text to keep, cut at the end of a sentence, or None for all of it.
    """
    if not extras:
        return document_from(pages, paged, max_chars)
    paper = document_from(pages, paged)
    text = "\n\n".join(
        [paper.text, *(f"{heading(name)}\n\n{document_from(pieces, False).text}" for name, pieces in extras)]
    )
    spans = list(paper.pages)
    truncated_from = None
    if max_chars is not None and len(text) > max_chars:
        truncated_from = len(text)
        text = truncate_text(text, max_chars)
        spans = [(start, min(end, len(text))) for start, end in spans if start < len(text)]

    return Document(text=text, pages=tuple(spans), sections=tuple(find_sections(text)), truncated_from=truncated_from)
