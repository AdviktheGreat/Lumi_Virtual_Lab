"""Tests of getting the text of a paper that is a DOI or a link: what Europe PMC gives and what is kept of it, a paper
that cannot be had and why it says so, and a link that does not lead to the public internet."""

from typing import Any

import pytest
from conftest import FakeResponse, FakeTransport
from test_literature import ARTICLE_RECORD, search_response

from virtual_lab.paperagents import fetch as fetching
from virtual_lab.paperagents.fetch import (
    MIN_PAPER_CHARS,
    UPLOAD,
    PaperUnavailableError,
    europe_pmc_paper,
    left_out,
    linked_paper,
    marked,
    sections_of,
)
from virtual_lab.records import parse_xml
from virtual_lab.web import WebRequestError
from virtual_lab.webpages import PDF_TYPE, Page

DOI = "10.1093/nar/gkr715"


def sentences(about: str, count: int = 20) -> str:
    return " ".join(f"This is sentence {number} about {about}, which the authors measured." for number in range(count))


def full_text() -> str:
    """A full text of the kind Europe PMC gives, with a section of each kind a paper has, including those not read."""
    return f"""<?xml version="1.0"?>
<article>
  <front><article-meta>
    <abstract><title>Abstract</title><p>{sentences("the abstract", 3)}</p></abstract>
  </article-meta></front>
  <body>
    <sec><title>Introduction</title><p>{sentences("why it matters")}</p></sec>
    <sec><title>Results</title>
      <sec><title>Affinity purification</title><p>{sentences("purification")}</p></sec>
      <sec><title>Binding</title><p>{sentences("binding")}</p></sec>
    </sec>
    <sec><title>Methods</title><p>{sentences("the methods")}</p></sec>
  </body>
  <back>
    <ack><title>Acknowledgements</title><p>We thank the people of the lab.</p></ack>
    <sec><title>Data availability</title><p>The data are in GEO under GSE12345.</p></sec>
    <sec sec-type="data-availability"><p>Sequences are held at the ENA.</p></sec>
    <sec><title>Code availability</title><p>The code is at https://github.com/example/mapper.</p></sec>
    <sec><title>Funding</title><p>Grant 12345 paid for it.</p></sec>
    <sec><title>Competing interests</title><p>None are declared.</p></sec>
    <notes notes-type="supplementary-material"><p>Tables S1 to S4 are with the paper.</p></notes>
    <notes><title>Author contributions</title><p>A designed it. B ran it.</p></notes>
    <ref-list><title>References</title>
      <ref><mixed-citation>Someone else. A different paper entirely.</mixed-citation></ref>
    </ref-list>
  </back>
</article>
"""


def serve(transport: FakeTransport, text: str | None, record: dict[str, Any] | None = None) -> None:
    """Queues what Europe PMC answers a look-up with, and then the full text, if there is one."""
    transport.responses = [FakeResponse(json_body=search_response(record if record is not None else ARTICLE_RECORD))]
    if text is not None:
        transport.responses.append(FakeResponse(body=text.encode()))


def unavailable(call: Any, *args: Any) -> str:
    with pytest.raises(PaperUnavailableError) as caught:
        call(*args)

    return str(caught.value)


class TestAnOpenAccessPaperFromEuropePmc:
    def test_the_paper_is_got_by_its_doi_with_its_headings_marked(self, web_transport: FakeTransport) -> None:
        serve(web_transport, full_text())

        paper = europe_pmc_paper(DOI)

        assert web_transport.params[0]["query"] == f'DOI:"{DOI}"'
        assert web_transport.urls[1].endswith("/PMC3258128/fullTextXML")
        assert paper.name == "europepmc-pmc3258128.txt"
        assert paper.source == {
            "kind": "europepmc",
            "label": "Europe PMC, PMC3258128",
            "url": "https://europepmc.org/article/MED/21937511",
        }
        headings = [line for line in paper.text.splitlines() if line.startswith("#")]
        assert headings == [
            f"# {ARTICLE_RECORD['title']}",
            "## Abstract",
            "## Introduction",
            "## Results",
            "## Methods",
            "## Data availability",
            "## Data availability",
            "## Code availability",
            "## Supplementary material",
        ]
        assert len(paper.text) >= MIN_PAPER_CHARS

    def test_where_the_data_and_the_code_are_is_kept_since_it_is_read_for(self, web_transport: FakeTransport) -> None:
        serve(web_transport, full_text())

        text = europe_pmc_paper(DOI).text

        for kept in ("GSE12345", "held at the ENA", "github.com/example/mapper", "Tables S1 to S4"):
            assert kept in text

    def test_what_thanks_people_or_says_who_paid_and_the_references_are_not_kept(
        self, web_transport: FakeTransport
    ) -> None:
        serve(web_transport, full_text())

        text = europe_pmc_paper(DOI).text

        for left in ("thank the people", "Grant 12345", "None are declared", "A designed it", "A different paper"):
            assert left not in text

    def test_a_subsection_is_kept_in_the_section_that_it_is_in(self, web_transport: FakeTransport) -> None:
        serve(web_transport, full_text())

        text = europe_pmc_paper(DOI).text

        assert "Affinity purification. This is sentence 0 about purification" in text
        assert text.index("## Results") < text.index("Binding. This is sentence 0") < text.index("## Methods")

    def test_the_text_is_what_the_paper_says_and_nothing_is_added_to_it(self, web_transport: FakeTransport) -> None:
        serve(web_transport, full_text())

        text = europe_pmc_paper(DOI).text

        assert sentences("why it matters") in text and sentences("the methods") in text


class TestAPaperThatCannotBeHad:
    @pytest.mark.parametrize(
        ("record", "why"),
        [
            ({**ARTICLE_RECORD, "isOpenAccess": "N"}, "is not open access"),
            ({**ARTICLE_RECORD, "inEPMC": "N"}, "only as an abstract"),
            ({**ARTICLE_RECORD, "pmcid": ""}, "only as an abstract"),
        ],
    )
    def test_a_paper_without_full_text_says_why_and_asks_for_the_file_and_the_text_is_not_asked_for(
        self, web_transport: FakeTransport, record: dict[str, Any], why: str
    ) -> None:
        serve(web_transport, None, record)

        message = unavailable(europe_pmc_paper, DOI)

        assert f"The paper {DOI}" in message and why in message and message.endswith(UPLOAD)
        assert len(web_transport.requests) == 1

    def test_a_doi_that_europe_pmc_does_not_have_says_so(self, web_transport: FakeTransport) -> None:
        web_transport.responses = [FakeResponse(json_body=search_response())]

        message = unavailable(europe_pmc_paper, DOI)

        assert f"Europe PMC has no article with the DOI {DOI}" in message and message.endswith(UPLOAD)

    def test_an_article_with_another_doi_is_not_the_paper(self, web_transport: FakeTransport) -> None:
        serve(web_transport, full_text(), {**ARTICLE_RECORD, "doi": "10.1000/someone-else"})

        assert "has no article with the DOI" in unavailable(europe_pmc_paper, DOI)
        assert len(web_transport.requests) == 1

    def test_the_doi_is_told_from_another_by_what_it_says_and_not_by_its_case(
        self, web_transport: FakeTransport
    ) -> None:
        serve(web_transport, full_text(), {**ARTICLE_RECORD, "doi": DOI.upper()})

        assert europe_pmc_paper(DOI).name == "europepmc-pmc3258128.txt"

    def test_europe_pmc_that_cannot_be_reached_says_so_and_that_trying_again_may_do(
        self, web_transport: FakeTransport
    ) -> None:
        web_transport.responses = [FakeResponse(status_code=503) for _ in range(5)]

        message = unavailable(europe_pmc_paper, DOI)

        assert "Europe PMC could not be reached" in message and "Try again" in message and UPLOAD.lower() in message

    def test_a_full_text_that_cannot_be_got_says_so(self, web_transport: FakeTransport) -> None:
        web_transport.responses = [FakeResponse(json_body=search_response(ARTICLE_RECORD))] + [
            FakeResponse(status_code=500) for _ in range(5)
        ]

        message = unavailable(europe_pmc_paper, DOI)

        assert f"The full text of {DOI} could not be got from Europe PMC" in message and message.endswith(UPLOAD)

    def test_a_full_text_that_is_not_xml_says_so(self, web_transport: FakeTransport) -> None:
        serve(web_transport, "<html>an error page</html")

        message = unavailable(europe_pmc_paper, DOI)

        assert "could not be got from Europe PMC" in message

    def test_a_text_too_short_to_be_a_paper_is_refused(self, web_transport: FakeTransport) -> None:
        serve(web_transport, "<article><body><sec><title>Intro</title><p>Brief.</p></sec></body></article>")

        message = unavailable(europe_pmc_paper, DOI)

        assert "too little to be the paper" in message and message.endswith(UPLOAD)


class TestSectionsOfAFullText:
    @pytest.mark.parametrize(
        ("heading", "is_left_out"),
        [
            ("References", True),
            ("REFERENCES AND NOTES", True),
            ("Bibliography", True),
            ("Acknowledgements", True),
            ("Acknowledgments", True),
            ("Funding", True),
            ("Funding sources", True),
            ("Conflict of interest", True),
            ("Competing interests", True),
            ("Author contributions", True),
            ("Author information", True),
            ("Abbreviations", True),
            ("Results", False),
            ("Methods", False),
            ("Data availability", False),
            ("Code availability", False),
            ("Supplementary material", False),
            ("Discussion", False),
        ],
    )
    def test_what_is_left_out_is_told_by_what_its_heading_begins_with(self, heading: str, is_left_out: bool) -> None:
        assert left_out(heading) is is_left_out

    def test_a_body_with_no_sections_is_kept_as_its_paragraphs(self) -> None:
        root = parse_xml(
            "<article><body><p>The first.</p><p>The  second\nparagraph.</p></body></article>", WebRequestError
        )

        assert sections_of(root) == [("Text", "The first. The second paragraph.")]

    def test_a_section_with_no_heading_is_named_for_its_kind_or_left_untitled(self) -> None:
        root = parse_xml(
            "<article><body><sec><p>No heading.</p></sec></body>"
            '<back><sec sec-type="code-availability"><p>At GitHub.</p></sec><notes><p>A note.</p></notes></back>'
            "</article>",
            WebRequestError,
        )

        assert sections_of(root) == [
            ("Untitled section", "No heading."),
            ("Code availability", "At GitHub."),
            ("Untitled section", "A note."),
        ]

    def test_a_section_with_nothing_in_it_is_not_kept(self) -> None:
        root = parse_xml("<article><body><sec><title>Empty</title></sec></body></article>", WebRequestError)

        assert sections_of(root) == []

    def test_the_abstract_comes_first_and_is_named_if_it_has_no_title(self) -> None:
        root = parse_xml(
            "<article><front><article-meta><abstract><p>What it found.</p></abstract></article-meta></front>"
            "<body><sec><title>Intro</title><p>Why.</p></sec></body></article>",
            WebRequestError,
        )

        assert sections_of(root) == [("Abstract", "What it found."), ("Intro", "Why.")]

    def test_the_text_marks_its_title_and_each_heading_on_a_line_of_its_own(self) -> None:
        assert (
            marked("A title", [("One", "First."), ("Two", "Second.")])
            == "# A title\n\n## One\n\nFirst.\n\n## Two\n\nSecond."
        )
        assert marked("", [("One", "First.")]) == "## One\n\nFirst."


def page(text: str, title: str = "A paper", kind: str = "text/html", url: str = "https://example.org/paper") -> Page:
    return Page(url=url, title=title, kind=kind, text=text)


class TestAPaperFromALink:
    def test_the_text_of_the_page_is_the_paper_with_where_it_came_from(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = "## Results\n\n" + sentences("results", 100)
        monkeypatch.setattr(fetching, "fetch_page", lambda url: page(body, url="https://www.example.org/final/paper"))

        paper = linked_paper("https://example.org/paper")

        assert paper.text == f"# A paper\n\n{body}" and paper.name == "linked-paper.txt"
        assert paper.source == {
            "kind": "link",
            "label": "The page at www.example.org",
            "url": "https://www.example.org/final/paper",
        }

    def test_a_pdf_is_named_as_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fetching, "fetch_page", lambda url: page(sentences("a pdf", 100), title="", kind=PDF_TYPE))

        paper = linked_paper("https://example.org/paper.pdf")

        assert paper.source["label"] == "The PDF at example.org" and not paper.text.startswith("#")

    def test_a_title_that_the_text_begins_with_is_not_put_before_it_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = "# A paper\n\n" + sentences("results", 100)
        monkeypatch.setattr(fetching, "fetch_page", lambda url: page(body))

        assert linked_paper("https://example.org/paper").text == body

    def test_a_page_with_too_little_text_is_refused_and_says_what_may_be_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(fetching, "fetch_page", lambda url: page("Please log in to read this paper."))

        message = unavailable(linked_paper, "https://example.org/paper")

        assert "too little to be a paper" in message and "login" in message and message.endswith(UPLOAD)

    def test_a_page_that_cannot_be_read_says_why(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def gone(url: str) -> Page:
            raise WebRequestError("The page answered 404")

        monkeypatch.setattr(fetching, "fetch_page", gone)

        message = unavailable(linked_paper, "https://example.org/paper")

        assert message == f"The page answered 404. {UPLOAD}"

    @pytest.mark.parametrize(
        "link",
        [
            "http://127.0.0.1/paper",
            "http://127.0.0.1:8765/api/setup",
            "http://localhost/paper",
            "http://10.1.2.3/paper",
            "http://192.168.0.1/paper",
            "http://169.254.169.254/latest/meta-data",
            "http://[::1]/paper",
            "http://[::ffff:7f00:1]/paper",
            "http://93.184.216.34:8443/paper",
            "ftp://example.org/paper",
            "http://user:secret@example.org/paper",
        ],
    )
    def test_a_link_that_does_not_lead_to_the_public_internet_is_refused_before_anything_is_asked_of_it(
        self, web_transport: FakeTransport, link: str
    ) -> None:
        message = unavailable(linked_paper, link)

        assert "Refusing to read" in message and message.endswith(UPLOAD)
        assert web_transport.requests == []
