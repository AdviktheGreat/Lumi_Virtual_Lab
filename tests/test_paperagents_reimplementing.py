"""Tests of what a program chooses of a paper's words for a re-implementation to be written from: the sections that can
be chosen, the ones that are chosen to start with, how sections and searched-for places come together, what fits in
what the writer is given and where it is cut, what the writer is told, what the function is named, and what the key
that a person agrees to is bound to."""

import pytest

from virtual_lab.constants import MAX_FUNCTION_TASK_CHARS
from virtual_lab.paperagents import reimplementing
from virtual_lab.paperagents.anchors import document_from

TITLE = "Adding and doubling: a method"
ABSTRACT = "We present a method that adds numbers and doubles them."
METHODS = "We take the numbers, add them one to another, and double the sum. The detail is left out."
RESULTS = "The method reached 0.93 on the held-out set."
PAPER = "\n\n".join(
    [
        TITLE,
        "Abstract",
        ABSTRACT,
        "Methods",
        METHODS,
        "Results",
        RESULTS,
        "Data availability",
        "The data are there.",
        "References",
        "Smith, J. (2020). A paper.",
    ]
)


def document() -> object:
    return document_from([PAPER], True)


def spans() -> list[reimplementing.Span]:
    return reimplementing.spans_of(document())  # type: ignore[arg-type]


class TestSectionsThatCanBeChosen:
    def test_every_heading_but_the_references_is_one(self) -> None:
        found = spans()

        assert [span.title for span in found] == ["Abstract", "Methods", "Results", "Data availability"]
        assert [span.index for span in found] == [0, 1, 2, 3]

    def test_a_section_runs_to_the_next_one(self) -> None:
        doc = document()
        methods = next(span for span in spans() if span.title == "Methods")

        assert doc.text[methods.start : methods.end].strip() == f"Methods\n\n{METHODS}"  # type: ignore[union-attr]
        assert methods.chars == len(f"Methods\n\n{METHODS}\n\n")
        assert methods.page == 1

    def test_a_section_with_nothing_but_its_heading_is_one_all_the_same(self) -> None:
        text = "Methods\n\nResults\n\nNothing is between the headings here.\n\nReferences\n\nA. One."
        found = reimplementing.spans_of(document_from([text], False))

        assert [span.title for span in found] == ["Methods", "Results"]

    def test_the_references_are_not_one(self) -> None:
        assert all(span.title != "References" for span in spans())

    def test_whose_headings_say_they_are_of_how_something_was_done_are_chosen_to_start_with(self) -> None:
        assert reimplementing.default_sections(spans()) == [1]

    def test_the_words_of_a_heading_are_told_however_they_are_written(self) -> None:
        for heading in (
            "METHODS",
            "Materials and methods",
            "Experimental Procedures",
            "Online methods",
            "Star methods",
        ):
            text = f"{heading}\n\nHow it is done.\n\nReferences\n\nA. One."
            found = reimplementing.spans_of(document_from([text], False))
            assert reimplementing.default_sections(found) == [0], heading

    def test_results_and_availability_are_not_chosen_to_start_with(self) -> None:
        text = "Results\n\nWhat was found.\n\nData availability\n\nThe data.\n\nReferences\n\nA. One."
        found = reimplementing.spans_of(document_from([text], False))

        assert reimplementing.default_sections(found) == []


class TestChoosing:
    def test_the_sections_that_are_named_and_the_places_that_were_found_in_the_order_of_the_paper(self) -> None:
        doc = document()
        places = reimplementing.choose(doc, [2, 0], [])  # type: ignore[arg-type]

        assert [place.section for place in places] == ["Abstract", "Results"]

    def test_a_place_that_a_search_found_is_chosen_with_the_sections(self) -> None:
        doc = document()
        hits = [{"start": PAPER.index("0.93") - 10, "end": PAPER.index("0.93") + 10}]
        places = reimplementing.choose(doc, [0], hits)  # type: ignore[arg-type]

        assert len(places) == 2
        assert places[0].section == "Abstract" and places[1].section == "Results"

    def test_places_that_touch_are_made_one(self) -> None:
        doc = document()
        at = PAPER.index("0.93")
        hits = [{"start": at - 20, "end": at}, {"start": at - 5, "end": at + 30}]
        places = reimplementing.choose(doc, [], hits)  # type: ignore[arg-type]

        assert len(places) == 1
        assert (places[0].start, places[0].end) == (at - 20, at + 30)

    def test_a_place_within_a_section_is_made_one_with_it(self) -> None:
        doc = document()
        at = PAPER.index(METHODS)
        hits = [{"start": at, "end": at + 10}]
        places = reimplementing.choose(doc, [1], hits)  # type: ignore[arg-type]

        assert len(places) == 1 and places[0].section == "Methods"

    def test_what_is_not_a_section_is_refused(self) -> None:
        doc = document()
        for bad in ([99], ["1"], [True], [None]):
            with pytest.raises(ValueError, match="not"):
                reimplementing.choose(doc, bad, [])  # type: ignore[arg-type]

    def test_the_references_cannot_be_chosen(self) -> None:
        doc = document()
        references = len(doc.sections) - 1  # type: ignore[union-attr]

        with pytest.raises(ValueError):
            reimplementing.choose(doc, [references], [])  # type: ignore[arg-type]

    def test_a_section_once(self) -> None:
        with pytest.raises(ValueError, match="once"):
            reimplementing.choose(document(), [1, 1], [])  # type: ignore[arg-type]

    def test_nothing_is_refused(self) -> None:
        with pytest.raises(ValueError, match="[Cc]hoose"):
            reimplementing.choose(document(), [], [])  # type: ignore[arg-type]

    def test_too_many_sections_are_refused(self) -> None:
        with pytest.raises(ValueError, match="At most"):
            reimplementing.choose(document(), list(range(reimplementing.MAX_SECTIONS + 1)), [])  # type: ignore[arg-type]

    def test_more_places_than_can_be_given_are_refused(self) -> None:
        # Sections that are not next to one another are one place each, so others are put between them
        sections = "\n\n".join(
            part
            for _ in range(reimplementing.MOST_PLACES + 1)
            for part in ("Methods", "Some words here.", "Results", "Some other words.")
        )
        text = f"{sections}\n\nReferences\n\nA. One."
        doc = document_from([text], False)
        chosen = [span.index for span in reimplementing.spans_of(doc) if span.title == "Methods"]

        with pytest.raises(ValueError, match="places"):
            reimplementing.choose(doc, chosen, [])


class TestWhatFits:
    def test_everything_that_fits_is_kept_whole(self) -> None:
        doc = document()
        places = reimplementing.choose(doc, [0, 1, 2], [])  # type: ignore[arg-type]
        kept, cut = reimplementing.fit(doc, places)  # type: ignore[arg-type]

        assert kept == places and cut is False

    def test_what_does_not_fit_is_cut_where_a_paragraph_ends(self, monkeypatch: pytest.MonkeyPatch) -> None:
        long_methods = "\n\n".join(
            ["Methods", *[f"Paragraph {index}. " + " ".join(["It says how it is done."] * 6) for index in range(20)]]
        )
        text = f"A title\n\n{long_methods}\n\nReferences\n\nA. One."
        doc = document_from([text], False)
        monkeypatch.setattr(reimplementing, "MAX_PASSAGES_CHARS", 800)
        places = reimplementing.choose(doc, [0], [])
        kept, cut = reimplementing.fit(doc, places)

        assert cut is True and len(kept) == 1
        piece = doc.text[kept[0].start : kept[0].end]
        whole = doc.text[places[0].start : places[0].end]
        assert piece.startswith("Methods") and len(piece) >= reimplementing.MIN_PIECE_CHARS
        assert len(piece) < len(whole) and doc.text[kept[0].end : kept[0].end + 2] == "\n\n"

    def test_a_paragraph_too_long_to_cut_at_is_cut_at_a_word(self, monkeypatch: pytest.MonkeyPatch) -> None:
        long_methods = "Methods\n\n" + "First, the numbers are added. " * 60
        text = f"A title\n\n{long_methods}\n\nReferences\n\nA. One."
        doc = document_from([text], False)
        monkeypatch.setattr(reimplementing, "MAX_PASSAGES_CHARS", 800)
        (kept,), cut = reimplementing.fit(doc, reimplementing.choose(doc, [0], []))

        assert cut is True
        assert len(doc.text[kept.start : kept.end]) >= reimplementing.MIN_PIECE_CHARS
        assert doc.text[kept.end] == " "

    def test_what_cannot_be_given_far_enough_to_be_worth_it_is_not_given(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(reimplementing, "MAX_PASSAGES_CHARS", reimplementing.MIN_PIECE_CHARS // 2)
        doc = document()
        places = reimplementing.choose(doc, [0, 1], [])  # type: ignore[arg-type]
        kept, cut = reimplementing.fit(doc, places)  # type: ignore[arg-type]

        assert kept == [] and cut is True

    def test_nothing_after_a_cut_is_given(self, monkeypatch: pytest.MonkeyPatch) -> None:
        long_methods = "\n\n".join(
            ["Methods", *[f"Paragraph {index}. " + " ".join(["It says how it is done."] * 6) for index in range(20)]]
        )
        text = f"A title\n\n{long_methods}\n\nResults\n\n0.93 was reached.\n\nReferences\n\nA. One."
        doc = document_from([text], False)
        monkeypatch.setattr(reimplementing, "MAX_PASSAGES_CHARS", 800)
        places = reimplementing.choose(doc, [0, 1], [])
        kept, cut = reimplementing.fit(doc, places)

        assert [place.section for place in kept] == ["Methods"] and cut is True


class TestWhatTheWriterIsTold:
    def test_the_title_what_is_wanted_and_the_papers_own_words_with_where_they_are_from(self) -> None:
        doc = document()
        places = reimplementing.choose(doc, [1, 2], [])  # type: ignore[arg-type]
        brief = reimplementing.brief_of(TITLE, doc, places, "I want the doubling, as one number.")  # type: ignore[arg-type]

        assert f"The paper: {TITLE}" in brief
        assert "I want the doubling, as one number." in brief
        # Sections next to one another are one place, which is said to be from the first of them
        assert "[Methods, page 1]" in brief
        assert METHODS in brief and RESULTS in brief

    def test_nothing_is_said_of_what_is_wanted_when_it_is_not_said(self) -> None:
        doc = document()
        places = reimplementing.choose(doc, [1], [])  # type: ignore[arg-type]
        brief = reimplementing.brief_of(TITLE, doc, places, None)  # type: ignore[arg-type]

        assert "What the person" not in brief and METHODS in brief

    def test_more_than_a_task_may_be_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(reimplementing, "MAX_FUNCTION_TASK_CHARS", 100)
        doc = document()
        places = reimplementing.choose(doc, [1], [])  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="characters"):
            reimplementing.brief_of(TITLE, doc, places, None)  # type: ignore[arg-type]

    def test_what_fits_after_the_cut_is_within_a_task(self) -> None:
        text = "\n\n".join(["A title", "Methods", "word " * 40_000, "References", "A. One."])
        doc = document_from([text], False)
        places = reimplementing.choose(doc, [0], [])
        kept, cut = reimplementing.fit(doc, places)
        brief = reimplementing.brief_of("A title", doc, kept, None)

        assert cut is True and len(brief) <= MAX_FUNCTION_TASK_CHARS


class TestTheName:
    def test_is_of_the_title(self) -> None:
        assert (
            reimplementing.default_name("Adding and Doubling: A Method") == "reimplemented_adding_and_doubling_a_method"
        )

    def test_has_no_marks_and_no_capitals(self) -> None:
        name = reimplementing.default_name("CellMapper v2.0: Fast, Accurate Mapping!")

        assert name == "reimplemented_cellmapper_v2_0_fast_accurate_mapping"

    def test_does_not_begin_with_a_digit_and_is_not_too_long(self) -> None:
        name = reimplementing.default_name("2024 " + "word " * 40)

        assert name[0].isalpha() and len(name) <= 64 and name == name.rstrip("_")

    def test_a_title_with_no_words_has_a_name_all_the_same(self) -> None:
        assert reimplementing.default_name("!!!") == "reimplemented_method"


class TestBoundaries:
    def test_the_last_section_runs_to_the_end_of_the_paper_when_no_references_follow(self) -> None:
        text = "Methods\n\nHow it is done.\n\nResults\n\nWhat was found."
        found = reimplementing.spans_of(document_from([text], False))

        assert found[-1].title == "Results"
        assert found[-1].end == len(text)

    def test_as_many_sections_as_can_be_chosen_are_looked_at(self) -> None:
        # One too many is refused before any is looked at; as many as can be are, and the second [0] is the fault
        with pytest.raises(ValueError, match="chosen once"):
            reimplementing.choose(document(), [0] * reimplementing.MAX_SECTIONS, [])  # type: ignore[arg-type]

    def test_as_many_places_as_can_be_given_are_given(self) -> None:
        text = "Methods\n\n" + "word " * 4_000 + "\n\nReferences\n\nA. One."
        doc = document_from([text], False)
        hits = [{"start": 100 + 300 * at, "end": 200 + 300 * at} for at in range(reimplementing.MOST_PLACES)]

        places = reimplementing.choose(doc, [], hits)  # type: ignore[arg-type]

        assert len(places) == reimplementing.MOST_PLACES

    def test_a_place_that_fits_exactly_is_given_whole(self) -> None:
        heading = len("[Methods, page 1]\n\n") + len("Methods\n\n") + len("\n\n")
        body = "a" * (reimplementing.MAX_PASSAGES_CHARS - heading)
        text = f"Methods\n\n{body}\n\nReferences\n\nA. One."
        doc = document_from([text], True)
        places = reimplementing.choose(doc, [0], [])  # type: ignore[arg-type]

        kept, cut = reimplementing.fit(doc, places)  # type: ignore[arg-type]

        assert cut is False and kept == places

    def test_a_piece_smaller_than_is_worth_giving_is_not_given(self) -> None:
        heading = len("[Methods, page 1]\n\n") + len("Methods\n\n") + len("\n\n")
        room = reimplementing.MIN_PIECE_CHARS + len("[Discussion, page 1]\n\n") - 1
        body = "a" * (reimplementing.MAX_PASSAGES_CHARS - heading - room)
        text = f"Methods\n\n{body}\n\nResults\n\nr\n\nDiscussion\n\n{'b' * 1_000}\n\nReferences\n\nA. One."
        doc = document_from([text], True)
        # [0] and [2], with [1] between them left out, so that they are two places and are not made one
        places = reimplementing.choose(doc, [0, 2], [])  # type: ignore[arg-type]

        kept, cut = reimplementing.fit(doc, places)  # type: ignore[arg-type]

        assert cut is True and len(kept) == 1

    def test_a_piece_exactly_worth_giving_is_given(self) -> None:
        heading = len("[Methods, page 1]\n\n") + len("Methods\n\n") + len("\n\n")
        room = reimplementing.MIN_PIECE_CHARS + len("[Discussion, page 1]\n\n")
        body = "a" * (reimplementing.MAX_PASSAGES_CHARS - heading - room)
        text = f"Methods\n\n{body}\n\nResults\n\nr\n\nDiscussion\n\n{'b' * 1_000}\n\nReferences\n\nA. One."
        doc = document_from([text], True)
        places = reimplementing.choose(doc, [0, 2], [])  # type: ignore[arg-type]

        kept, cut = reimplementing.fit(doc, places)  # type: ignore[arg-type]

        assert cut is True and len(kept) == 2
        assert kept[1].end - kept[1].start == reimplementing.MIN_PIECE_CHARS


class TestWhatAgreeingIsBoundTo:
    def test_the_key_is_of_the_brief_the_name_the_model_and_the_file(self) -> None:
        key = reimplementing.key_of("a brief", "a_name", "a-model", "ab" * 32)

        assert len(key) == 64
        assert key == reimplementing.key_of("a brief", "a_name", "a-model", "ab" * 32)
        assert key != reimplementing.key_of("another brief", "a_name", "a-model", "ab" * 32)
        assert key != reimplementing.key_of("a brief", "another_name", "a-model", "ab" * 32)
        assert key != reimplementing.key_of("a brief", "a_name", "another-model", "ab" * 32)
        assert key != reimplementing.key_of("a brief", "a_name", "a-model", "cd" * 32)

    def test_a_change_in_what_is_said_of_it_is_another_offer(self) -> None:
        key = reimplementing.key_of("a brief", "a_name", "a-model", "ab" * 32)
        monkey_meaning = reimplementing.MEANING + " "
        original = reimplementing.MEANING
        try:
            reimplementing.MEANING = monkey_meaning  # type: ignore[misc]
            assert reimplementing.key_of("a brief", "a_name", "a-model", "ab" * 32) != key
        finally:
            reimplementing.MEANING = original  # type: ignore[misc]
