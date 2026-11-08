"""A paper's text, and the places in it that a fact can be traced to.

A fact is taken from a paper only with the words it was taken from, and those words are found again in the text, which
is what makes a place in the paper of it: where they begin and end, the page of a PDF they are on, and the section
they are in. A quote is compared as a person reads it, not as bytes: spaces and line breaks do not tell one quote from
another, nor do curly quotes and straight ones, a ligature and the letters it stands for, or a word that a line ended
in the middle of, so that a quote copied out of a PDF's text is found even if it was set differently. Words are never
told apart that differ in the letters themselves, so a quote that a model reworded is not found.
"""

import bisect
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from virtual_lab.papers import truncate_text

SCHEMA = 1

# Headings that are told by their words alone, since the text of a PDF has no marks of what is a heading. What is here
# is what papers are divided into, and what each is called in the journals that print them
SECTIONS = (
    "abstract",
    "summary",
    "introduction",
    "background",
    "results",
    "results and discussion",
    "discussion",
    "conclusion",
    "conclusions",
    "limitations",
    "limitations of the study",
    "methods",
    "online methods",
    "star methods",
    "materials and methods",
    "methods summary",
    "experimental procedures",
    "data availability",
    "code availability",
    "data and code availability",
    "code and data availability",
    "software availability",
    "availability of data and materials",
    "data and materials availability",
    "key resources table",
    "reporting summary",
    "ethics statement",
    "acknowledgements",
    "acknowledgments",
    "funding",
    "author contributions",
    "competing interests",
    "declaration of interests",
    "additional information",
    "supplementary information",
    "extended data",
    "references",
    "bibliography",
    "literature cited",
)
REFERENCE_SECTIONS = ("references", "bibliography", "literature cited")

MAX_HEADING_CHARS = 120

NUMBERED = re.compile(r"^(?:\d+(?:\.\d+)*|[IVX]+)[.)]?\s+")
MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(\S.*?)\s*#*\s*$")
LATEX_HEADING = re.compile(r"^\\(?:sub)*section\*?\{([^}]+)\}")

QUOTE_MARKS = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)
# Characters with no width, which a PDF puts in the middle of a word
INVISIBLE = frozenset("\u00ad\u200b\u200c\u200d\u2060\ufeff")


class Flat(NamedTuple):
    """A text as quotes are compared, and for each of its characters the span of the text it came from."""

    text: str
    starts: list[int]
    ends: list[int]


@dataclass(frozen=True)
class Section:
    """A heading in the text: what it says, where it is, and whether what follows it is the paper's references."""

    title: str
    start: int
    references: bool


@dataclass(frozen=True)
class Document:
    """A paper's text, with where its pages and sections are.

    :param text: The text, whose characters every place in it counts.
    :param pages: The first and last character of each page of a PDF, in order, or nothing for a text.
    :param sections: The headings found in it, in order.
    :param truncated_from: How long the text was before it was cut short, or None if it was not.
    """

    text: str
    pages: tuple[tuple[int, int], ...] = ()
    sections: tuple[Section, ...] = ()
    truncated_from: int | None = None
    _page_starts: list[int] = field(default_factory=list, repr=False, compare=False)
    _section_starts: list[int] = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._page_starts.extend(start for start, _ in self.pages)
        self._section_starts.extend(section.start for section in self.sections)

    def page_at(self, offset: int) -> int | None:
        """The page, from 1, that a character is on, or None if the text has no pages."""
        if not self.pages:
            return None

        return max(bisect.bisect_right(self._page_starts, offset), 1)

    def section_at(self, offset: int) -> str | None:
        """What the nearest heading before a character says, or None if there is none."""
        index = bisect.bisect_right(self._section_starts, offset)

        return self.sections[index - 1].title if index else None

    def anchor(self, start: int, end: int) -> dict[str, Any]:
        """Where a span of the text is: its first and last character, and the page and section it begins in."""
        return {"start": start, "end": end, "page": self.page_at(start), "section": self.section_at(start)}

    def references(self) -> list[tuple[int, int]]:
        """The spans of the text that are references: from a heading of them to the next heading, or to the end."""
        spans = []
        for index, section in enumerate(self.sections):
            if section.references:
                end = next(
                    (later.start for later in self.sections[index + 1 :] if not later.references), len(self.text)
                )
                spans.append((section.start, end))

        return spans

    def to_dict(self) -> dict[str, Any]:
        """What is kept of how the text is laid out, with the text kept beside it."""
        return {
            "schema": SCHEMA,
            "characters": len(self.text),
            "truncated_from": self.truncated_from,
            "pages": [
                {"page": number, "start": start, "end": end} for number, (start, end) in enumerate(self.pages, 1)
            ],
            "sections": [
                {"title": section.title, "start": section.start, "references": section.references}
                for section in self.sections
            ],
        }


def document_from(pages: list[str], paged: bool, max_chars: int | None = None) -> Document:
    """A paper's text from its pages, laid end to end with a blank line between, with its sections found.

    :param pages: What each page says, or the whole text as one piece.
    :param paged: Whether the pieces are the pages of a PDF, which a place in the text then says.
    :param max_chars: The most of the text to keep, cut at the end of a sentence, or None for all of it.
    """
    cleaned = [page.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "") for page in pages]
    text = "\n\n".join(cleaned)
    spans = []
    cursor = 0
    for page in cleaned:
        spans.append((cursor, cursor + len(page)))
        cursor += len(page) + 2
    truncated_from = None
    if max_chars is not None and len(text) > max_chars:
        truncated_from = len(text)
        text = truncate_text(text, max_chars)
        spans = [(start, min(end, len(text))) for start, end in spans if start < len(text)]

    return Document(
        text=text,
        pages=tuple(spans) if paged else (),
        sections=tuple(find_sections(text)),
        truncated_from=truncated_from,
    )


def document_of(text: str, layout: Any) -> Document:
    """A paper's text with the layout that was kept of it, which is not used where it is not what a text of that length
    would have, so that a layout kept of another text is not taken for this one's."""
    layout = layout if isinstance(layout, dict) else {}
    pages = layout.get("pages")
    sections = layout.get("sections")
    if layout.get("schema") != SCHEMA or layout.get("characters") != len(text):
        return Document(text=text, sections=tuple(find_sections(text)))
    try:
        kept_pages = tuple((int(page["start"]), int(page["end"])) for page in pages) if isinstance(pages, list) else ()
        kept_sections = (
            tuple(Section(str(item["title"]), int(item["start"]), bool(item["references"])) for item in sections)
            if isinstance(sections, list)
            else tuple(find_sections(text))
        )
    except (KeyError, TypeError, ValueError):
        return Document(text=text, sections=tuple(find_sections(text)))
    truncated = layout.get("truncated_from")

    return Document(
        text=text,
        pages=kept_pages,
        sections=kept_sections,
        truncated_from=truncated if isinstance(truncated, int) and not isinstance(truncated, bool) else None,
    )


def heading_of(line: str) -> str | None:
    """What a line says if it is a heading, which is one of the markings of Markdown or LaTeX, or the name of a part
    of a paper alone on a line, with a number before it or a colon after it if the journal sets one."""
    stripped = line.strip()
    if not stripped or len(stripped) > MAX_HEADING_CHARS:
        return None
    if match := MARKDOWN_HEADING.match(stripped) or LATEX_HEADING.match(stripped):
        return match.group(1).strip()
    name = NUMBERED.sub("", stripped).rstrip(" :.").casefold()

    return NUMBERED.sub("", stripped).rstrip(" :.") if name in SECTIONS else None


def find_sections(text: str) -> list[Section]:
    """The headings of a text, in order."""
    found = []
    offset = 0
    for line in text.split("\n"):
        if (title := heading_of(line)) is not None:
            start = offset + len(line) - len(line.lstrip())
            found.append(Section(title, start, title.casefold().rstrip(" :.") in REFERENCE_SECTIONS))
        offset += len(line) + 1

    return found


def hyphen_break(text: str, index: int) -> int | None:
    """Where a word goes on after a hyphen that a line ended in, if the hyphen at an index is one: the next character,
    which is a letter that a word goes on with. A hyphen that a word was written with, and a dash, are not."""
    if index == 0 or not text[index - 1].isalpha():
        return None
    after = index + 1
    while after < len(text) and text[after] in " \t\r\n":
        after += 1

    if after > index + 1 and "\n" in text[index + 1 : after] and after < len(text) and text[after].islower():
        return after

    return None


def flatten(text: str, join_broken_words: bool = False) -> Flat:
    """A text as quotes are compared: every run of spaces and breaks is one space, curly quotes and dashes are plain,
    letters are as they are written in plain form, and what has no width is gone. The text is not cased.

    :param join_broken_words: Whether to join a word that a line ended in the middle of, as 'signif-' and 'icant'.
    """
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    gap = True
    index = 0
    while index < len(text):
        char = text[index]
        if char in INVISIBLE:
            index += 1
        elif join_broken_words and char == "-" and (after := hyphen_break(text, index)) is not None:
            index = after
        elif char.isspace():
            if not gap:
                out.append(" ")
                starts.append(index)
                ends.append(index + 1)
                gap = True
            index += 1
        else:
            # A letter with its accents set apart, as a PDF may, is made one again before the rest is done to it
            stop = index + 1
            while stop < len(text) and unicodedata.combining(text[stop]):
                stop += 1
            for made in unicodedata.normalize("NFKC", text[index:stop]).translate(QUOTE_MARKS):
                if made.isspace():
                    if gap:
                        continue
                    made = " "
                out.append(made)
                starts.append(index)
                ends.append(stop)
                gap = made == " "
            index = stop
    if out and out[-1] == " ":
        out.pop()
        starts.pop()
        ends.pop()

    return Flat("".join(out), starts, ends)


def find_quote(quote: str, flat: Flat) -> tuple[int, int] | None:
    """Where a quote is in a text, as flatten made it, as the first and last character in the text itself.

    :return: The span, or None if the words are not there.
    """
    needle = flatten(quote).text
    if not needle:
        return None
    found = flat.text.find(needle)

    return None if found < 0 else (flat.starts[found], flat.ends[found + len(needle) - 1])


def contains(quote: str, detail: str, spaced: bool = True) -> bool:
    """Whether a detail, a name or a number or an address, is in the words it was taken from, apart from case.

    :param spaced: Whether spaces count. An address is told with none, since a PDF breaks a line in the middle of one.
    """
    wanted = flatten(detail).text.casefold()
    words = flatten(quote).text.casefold()
    if not spaced:
        wanted = wanted.replace(" ", "")
        words = words.replace(" ", "")

    return bool(wanted) and wanted in words
