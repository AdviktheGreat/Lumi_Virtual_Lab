"""A method written again from the words of a paper that has none of its code, and what a person is shown before it is.

A tool of tier C is a re-implementation: a model reads the passages of a paper that describe a method and writes a
function that does what they say. None of the authors' code is in it, so it is not the authors' method as they ran
it, and it is shown as a re-implementation wherever it is shown. It is never of tier A or B, which are of the authors'
own code.

Nothing here asks a model anything or runs anything. A program picks the words of the paper that the writer is given,
from the sections the person chooses and the words they search for, so that the person sees exactly what the model
will read and it is never the model that chooses what it reads. What the person is shown has a key, which is a hash of
what would be sent, so that agreeing to it is agreeing to that, and not to what it has become since.
"""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from virtual_lab.constants import MAX_FUNCTION_NAME_CHARS, MAX_FUNCTION_TASK_CHARS
from virtual_lab.paperagents.anchors import Document

TIER = "C"
LABEL = "Re-implementation"

MEANING = (
    "A tool of tier C is a re-implementation: a model wrote it from the words of a paper, and none of the authors' "
    "code is in it. It is not the authors' method as they ran it, and it is shown as a re-implementation wherever it "
    "is shown. It is of tier C only if a program found a number that the paper reports in what it gave for inputs "
    "that the paper itself gives, which is a check against that number and no more: it does not show that the "
    "function does what the authors' code does for any other input, or that what it gives is right. A function that "
    "was written and has not matched a number of the paper is kept, with why, and is given to nothing. One that has is "
    "given to the conversations that are given its agent, as a tool that says it is a re-implementation in its "
    "description and in everything it gives."
)

# The most characters of the paper that the writer is given, which leaves room in a task for what the person says of
# what they want, the paper's title, and where each passage is from
MAX_PASSAGES_CHARS = 8_000
MAX_GOAL_CHARS = 1_000
MAX_TITLE_CHARS = 300
MAX_SECTIONS = 50
MOST_PLACES = 30
# How many places a search of the paper gives
MOST_SEARCHED = 10
# The least that is left of a passage that does not fit, which is not worth giving if it is less
MIN_PIECE_CHARS = 200
# The words of a section's heading that say it is of how something was done, which is what is chosen to start with
METHOD_TITLE = re.compile(r"\b(?:methods?|materials|procedures?)\b", re.IGNORECASE)

SYSTEM_PROMPT = """You are a senior Python engineer. You are given the words of a scientific paper that describe a \
method, and you write that method as a Python function, from those words and nothing else. Requirements:
1. Output ONLY Python code, inside a single triple-backtick code block, with minimal inline comments and a small \
docstring.
2. Do what the passages say. Where they leave out a detail, take the simplest reading of what they do say, and say \
in a comment that you chose it. Do not use what you remember of the authors' own code, and do not fetch anything: \
there is no network.
3. Use the Python standard library only.
4. Never put a number that the paper reports as a result into the code, its comments, or its docstring. A result is \
worked out from the inputs.
5. The code will be called as a tool, by a program that sends JSON, so it must define one function named `{name}` \
that carries out the method. Give every parameter of it a type hint, of one of the types JSON has: str, int, float, \
bool, list, dict, or an Optional, union, or Literal of them. Give the function a docstring that says what it does, \
what each parameter is, and what it returns, and have it return a value that can be written as JSON.
6. Importing the file must only define things. Do not run anything when it is imported."""


@dataclass(frozen=True)
class Span:
    """A section of the paper that can be chosen: its place in the list of the headings that were found, what it is
    called, and where it is."""

    index: int
    title: str
    start: int
    end: int
    page: int | None

    @property
    def chars(self) -> int:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "chars": self.chars,
            "page": self.page,
        }


@dataclass(frozen=True)
class Place:
    """Words of the paper that the writer is given: from one character to another, with the section and page they
    begin in."""

    start: int
    end: int
    section: str | None
    page: int | None

    @property
    def label(self) -> str:
        where = self.section if self.section else "the paper"

        return f"{where}, page {self.page}" if self.page is not None else where

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "section": self.section, "page": self.page}


def spans_of(document: Document) -> list[Span]:
    """The sections that can be chosen: each heading that was found, from it to the next, except the references and a
    section with nothing in it."""
    spans = []
    for index, section in enumerate(document.sections):
        if section.references:
            continue
        end = document.sections[index + 1].start if index + 1 < len(document.sections) else len(document.text)
        spans.append(Span(index, section.title, section.start, end, document.page_at(section.start)))

    return spans


def default_sections(spans: Sequence[Span]) -> list[int]:
    """The sections whose headings say that they are of how something was done, which is where a method is."""
    return [span.index for span in spans if METHOD_TITLE.search(span.title)]


def choose(document: Document, sections: Sequence[Any], found: Sequence[Mapping[str, Any]] = ()) -> list[Place]:
    """The words of the paper that are chosen: the sections that are named, and the places that a search found, in the
    order of the paper, with those that touch one another made one.

    :param sections: The numbers of sections, as spans_of lists them.
    :param found: Places that a search of the paper found, each with where it starts and ends.
    :raises ValueError: If a section is not one that can be chosen, is named twice, or too many are, or nothing is
        chosen, or more places than can be given.
    """
    spans = {span.index: span for span in spans_of(document)}
    if len(sections) > MAX_SECTIONS:
        raise ValueError(f"At most {MAX_SECTIONS} sections can be chosen")
    seen = set()
    chosen: list[tuple[int, int]] = []
    for number in sections:
        if isinstance(number, bool) or not isinstance(number, int) or number not in spans:
            raise ValueError("A section is chosen by its number in the paper's list of sections, which this is not")
        if number in seen:
            raise ValueError("A section is chosen once")
        seen.add(number)
        chosen.append((spans[number].start, spans[number].end))
    chosen.extend((int(place["start"]), int(place["end"])) for place in found)
    if not chosen:
        raise ValueError("Choose a section of the paper, or search for the words that it describes the method in")
    merged: list[list[int]] = []
    for start, end in sorted(chosen):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    if len(merged) > MOST_PLACES:
        raise ValueError(f"The words chosen are in {len(merged)} places, and at most {MOST_PLACES} can be given")

    return [
        Place(start, end, document.section_at(start), document.page_at(start))
        for start, end in merged
        if document.text[start:end].strip()
    ]


def fit(document: Document, places: Sequence[Place]) -> tuple[list[Place], bool]:
    """What of the places fits in what the writer is given, cut where a paragraph or a word ends, and whether it was
    cut. Places are given whole, in order, until one does not fit, which is given as far as it does, if that is far
    enough to be worth it, and nothing after it is given."""
    room = MAX_PASSAGES_CHARS
    kept: list[Place] = []
    for place in places:
        text = document.text[place.start : place.end]
        cost = len(heading_of(place)) + len(text)
        if cost <= room:
            kept.append(place)
            room -= cost
            continue
        available = room - len(heading_of(place))
        if available >= MIN_PIECE_CHARS:
            piece = text[:available]
            stop = piece.rfind("\n\n")
            if stop < MIN_PIECE_CHARS // 2:
                stop = piece.rfind(" ")
            piece = piece[:stop] if stop >= MIN_PIECE_CHARS // 2 else piece
            kept.append(Place(place.start, place.start + len(piece.rstrip()), place.section, place.page))

        return kept, True

    return kept, False


def heading_of(place: Place) -> str:
    return f"[{place.label}]\n\n"


def brief_of(title: str, document: Document, places: Sequence[Place], goal: str | None) -> str:
    """What the writer is told: the paper's title, what the person says they want of the function, if they say, and the
    words of the paper, each with where they are from. The words are the paper's own, not shortened or put otherwise.

    :raises ValueError: If it comes to more than a task may be.
    """
    parts = [f"The paper: {' '.join(title.split())[:MAX_TITLE_CHARS]}"]
    if goal:
        parts.append(f"What the person who asked for the function says they want of it, in their words: {goal}")
    parts.append("The paper's own words about the method, each with where they are from:")
    parts.extend(f"{heading_of(place)}{document.text[place.start : place.end].strip()}" for place in places)
    brief = "\n\n".join(parts)
    if len(brief) > MAX_FUNCTION_TASK_CHARS:
        raise ValueError(
            f"What is to be given the writer is {len(brief):,} characters, more than {MAX_FUNCTION_TASK_CHARS:,}"
        )

    return brief


def default_name(title: str) -> str:
    """A name for the function, of the paper's title: lower case, with the words of it that are letters and digits, and
    not beginning with a digit."""
    words = re.findall(r"[a-z0-9]+", title.lower())[:6]
    name = "_".join(["reimplemented", *words]) if words else "reimplemented_method"

    return name[:MAX_FUNCTION_NAME_CHARS].rstrip("_")


def key_of(brief: str, name: str, model: str, file_sha256: str) -> str:
    """What agreeing is bound to: the words that the writer would be given, what the function is called, the model that
    writes it, the paper's file, and what is said of what a re-implementation is and how it is told to write. A key
    that is not the one the person was shown is a different offer."""
    shown = {
        "brief": brief,
        "name": name,
        "model": model,
        "file": file_sha256,
        "system": SYSTEM_PROMPT,
        "meaning": MEANING,
    }

    return hashlib.sha256(json.dumps(shown, sort_keys=True).encode("utf-8")).hexdigest()
