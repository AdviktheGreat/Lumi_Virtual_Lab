"""Getting the text of a paper that was given as a DOI or a link, and not as a file.

A DOI is looked up in Europe PMC, which holds the full text of the papers that are open access, and nowhere else: a
paper that is not there is said not to be, and is not got round. A link is read as a page is read for a model, which
refuses anything that does not lead to the public internet, so that a link cannot be made to read this machine or its
network.

What comes back is the paper's text with its headings marked, as the file of a paper would be, so that it is read in the
same way. Europe PMC's full text is cut into sections, and the ones that say where the data and the code are, which
`literature.get_article_text` leaves out, are kept, since they are among what is read for. The references are not kept,
nor what thanks people or says who paid.
"""

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from urllib.parse import urlsplit

from virtual_lab.literature import EUROPE_PMC_BASE, collapse, field, get_article, section_text
from virtual_lab.records import RecordNotFoundError, parse_xml
from virtual_lab.web import DisallowedHostError, WebRequestError, build_url, request_text
from virtual_lab.webpages import PDF_TYPE, fetch_page

# The fewest characters that can be a paper's text. A page that holds less is a paywall, a login, a page that scripts
# make, or an abstract, and reading it would spend money to find nothing.
MIN_PAPER_CHARS = 3000

# Sections of a full text that are not read, by what their heading begins with. The statements of where data and code
# are, and the supplementary material, are read.
LEFT_OUT = (
    "reference",
    "bibliography",
    "acknowledg",
    "funding",
    "conflict",
    "competing interest",
    "author contribution",
    "author information",
    "abbreviation",
)

# What Europe PMC calls a part of the back matter that has no heading, as a person would
NOTE_HEADINGS = {
    "data-availability": "Data availability",
    "data-availability-statement": "Data availability",
    "code-availability": "Code availability",
    "supplementary-material": "Supplementary material",
}

UPLOAD = "Upload the paper's file to have it read."


class PaperUnavailableError(Exception):
    """A paper whose text could not be got, with why, in words for the person who asked for it to be read."""


@dataclass(frozen=True)
class FetchedPaper:
    """The text of a paper, and where it came from.

    :param text: The text, with its headings marked as Markdown does.
    :param name: What to call the file it is kept as.
    :param source: Where it came from: its `kind` (europepmc or link), a `label` to say it by, and the `url` to see it
        at.
    """

    text: str
    name: str
    source: dict[str, str]


def left_out(heading: str) -> bool:
    return heading.strip().lower().startswith(LEFT_OUT)


def heading_of(element: ElementTree.Element, fallback: str) -> str:
    """What a section is called: its title, or what its type says, or the fallback."""
    kind = (element.get("sec-type") or element.get("notes-type") or "").strip().lower()

    return field(element.findtext("title", "")) or NOTE_HEADINGS.get(kind, "") or fallback


def sections_of(root: ElementTree.Element) -> list[tuple[str, str]]:
    """The sections of a full text that are read, in the order a paper has them.

    That is the abstract, the body, and the sections of what follows the body that are not left out.
    """
    found: list[tuple[str, str]] = []

    def keep(heading: str, element: ElementTree.Element) -> None:
        if not left_out(heading) and (text := section_text(element)):
            found.append((heading, text))

    for abstract in root.findall("./front/article-meta/abstract"):
        keep(heading_of(abstract, "Abstract"), abstract)
    if (body := root.find("./body")) is not None:
        parts = body.findall("./sec")
        for element in parts:
            keep(heading_of(element, "Untitled section"), element)
        if not parts and (
            text := collapse(" ".join("".join(paragraph.itertext()) for paragraph in body.findall("./p")))
        ):
            found.append(("Text", text))
    if (back := root.find("./back")) is not None:
        for element in (*back.findall("./sec"), *back.findall("./notes")):
            keep(heading_of(element, "Untitled section"), element)

    return found


def marked(title: str, sections: list[tuple[str, str]]) -> str:
    """A paper's text from its title and sections, with each heading on a line of its own, marked as Markdown does."""
    parts = [f"# {title}"] if title else []
    parts += [f"## {heading}\n\n{text}" for heading, text in sections]

    return "\n\n".join(parts)


def europe_pmc_paper(doi: str) -> FetchedPaper:
    """The full text of a paper that Europe PMC holds, by its DOI.

    :raises PaperUnavailableError: If Europe PMC has no article with the DOI, holds only its abstract, which is so of a
        paper that is not open access, cannot be reached, or has too little text.
    """
    try:
        article = get_article(doi)
        if not article.doi or article.doi.lower() != doi.lower():
            raise RecordNotFoundError(f"Europe PMC answered with another article than {doi}")
    except (RecordNotFoundError, ValueError):
        raise PaperUnavailableError(f"Europe PMC has no article with the DOI {doi}. {UPLOAD}") from None
    except WebRequestError as error:
        raise PaperUnavailableError(
            f"Europe PMC could not be reached: {error}. Try again, or {UPLOAD.lower()}"
        ) from None
    if not article.has_full_text:
        why = (
            "is not open access, so Europe PMC does not give out its full text"
            if not article.open_access
            else "is not held by Europe PMC as full text, only as an abstract"
        )
        raise PaperUnavailableError(f"The paper {doi} {why}. {UPLOAD}")
    try:
        url = build_url(f"{EUROPE_PMC_BASE}/{{pmcid}}/fullTextXML", pmcid=article.pmcid)
        root = parse_xml(request_text(url), WebRequestError, allow_external_doctype=True)
    except WebRequestError as error:
        raise PaperUnavailableError(
            f"The full text of {doi} could not be got from Europe PMC: {error}. {UPLOAD}"
        ) from None
    text = marked(article.title, sections_of(root))
    if len(text) < MIN_PAPER_CHARS:
        raise PaperUnavailableError(
            f"Europe PMC's text of {doi} is {len(text):,} characters, which is too little to be the paper. {UPLOAD}"
        )

    return FetchedPaper(
        text,
        f"europepmc-{re.sub(r'[^a-z0-9]', '', article.pmcid.lower())}.txt",
        {"kind": "europepmc", "label": f"Europe PMC, {article.pmcid}", "url": article.url},
    )


def linked_paper(url: str) -> FetchedPaper:
    """The text of the page a link leads to, which is a paper's, or its PDF.

    :raises PaperUnavailableError: If the link does not lead to the public internet, the page cannot be read, or it has
        too little text to be a paper.
    """
    try:
        page = fetch_page(url)
    except DisallowedHostError as error:
        raise PaperUnavailableError(
            f"{error}. A link to a paper is to a site on the public internet. {UPLOAD}"
        ) from None
    except WebRequestError as error:
        raise PaperUnavailableError(f"{error}. {UPLOAD}") from None
    text = page.text
    if page.title and page.title.lower() not in text[:500].lower():
        text = f"# {page.title}\n\n{text}"
    if len(text) < MIN_PAPER_CHARS:
        raise PaperUnavailableError(
            f"The page holds {len(text):,} characters of text, which is too little to be a paper. It may ask for a "
            f"login or a payment, or be made by scripts that are not run here. {UPLOAD}"
        )
    host = urlsplit(page.url).hostname or page.url

    return FetchedPaper(
        text,
        "linked-paper.txt",
        {"kind": "link", "label": f"{'The PDF' if page.kind == PDF_TYPE else 'The page'} at {host}", "url": page.url},
    )
