"""Tests of putting what a person's data is against what the method card says the method was used on: that names that
mean one thing are one, that the answer is inside, outside, or not covered, and is outside only where the card says
something that a program can compare, that a sample size is put against the range that a statement gives, and that a
warning has the card's words."""

import json
from typing import Any

import pytest

from virtual_lab.paperagents import scope


def fact(
    aspect: str,
    value: str,
    quote: str = "The authors' words.",
    by: str = "reading",
    read_as: dict[str, str] | None = None,
    number: int = 1,
) -> dict[str, Any]:
    anchor = (
        {"start": 10 * number, "end": 10 * number + 5, "page": 2, "section": "Methods"} if by == "reading" else None
    )
    return {
        "id": f"scope-{aspect.replace(' ', '')}{number}",
        "aspect": aspect,
        "value": value,
        "quote": quote,
        "anchor": anchor,
        "by": by,
        "read_as": read_as,
    }


def outcome(facts: list[dict[str, Any]], **described: Any) -> str:
    return scope.check(facts, described)["outcome"]


class TestNamesThatMeanOneThing:
    @pytest.mark.parametrize(
        ("on_the_card", "of_the_data"),
        [
            ("mouse", "Mus musculus"),
            ("Mus musculus", "mice"),
            ("human", "Homo sapiens"),
            ("Homo sapiens (human)", "humans"),
            ("zebrafish", "Danio rerio"),
        ],
    )
    def test_species_are_told_by_what_they_are_and_not_how_they_are_called(
        self, on_the_card: str, of_the_data: str
    ) -> None:
        assert outcome([fact("species", on_the_card)], species=of_the_data) == scope.INSIDE

    @pytest.mark.parametrize(
        ("on_the_card", "of_the_data"),
        [
            ("scRNA-seq", "single-cell RNA sequencing"),
            ("single cell RNA-seq (10x Chromium)", "scRNA seq"),
            ("snRNA-seq", "single nucleus RNA-seq"),
            ("ATAC-seq", "ATACseq"),
        ],
    )
    def test_assays_are_told_by_what_they_are_and_not_how_they_are_written(
        self, on_the_card: str, of_the_data: str
    ) -> None:
        assert outcome([fact("assay", on_the_card)], assay=of_the_data) == scope.INSIDE

    def test_a_tissue_and_an_input_format_have_names_that_mean_one_thing_too(self) -> None:
        assert outcome([fact("tissue", "PBMC")], tissue="peripheral blood mononuclear cells") == scope.INSIDE
        assert outcome([fact("input", "AnnData")], input_format="h5ad file") == scope.INSIDE
        assert outcome([fact("input", "FASTQ")], input_format="fastq.gz") == scope.INSIDE

    def test_a_name_is_not_told_from_a_longer_one_that_ends_it(self) -> None:
        # Single-cell RNA-seq is not RNA-seq, as it is for what a method was tested on
        assert outcome([fact("assay", "scRNA-seq")], assay="bulk RNA-seq") == scope.OUTSIDE
        assert outcome([fact("assay", "RNA-seq")], assay="single-cell RNA-seq") == scope.OUTSIDE

    def test_small_words_and_plurals_do_not_tell_things_apart(self) -> None:
        assert outcome([fact("tissue", "the brain tissue")], tissue="brains") == scope.INSIDE
        assert outcome([fact("tissue", "T cells")], tissue="T cell") == scope.INSIDE
        assert outcome([fact("tissue", "T cells")], tissue="B cells") == scope.OUTSIDE


class TestInsideOutsideAndNotCovered:
    def test_data_that_a_statement_covers_is_inside_and_has_no_warning(self) -> None:
        facts = [fact("species", "mouse", quote="we used mouse cortex")]

        result = scope.check(facts, {"species": "Mus musculus"})

        assert result["outcome"] == scope.INSIDE and result["warnings"] == []
        assert [(a["aspect"], a["outcome"]) for a in result["aspects"]] == [("species", scope.INSIDE)]
        assert [s["quote"] for s in result["aspects"][0]["says"]] == ["we used mouse cortex"]

    def test_data_that_no_statement_covers_is_outside_and_the_warning_has_the_cards_words(self) -> None:
        facts = [fact("species", "mouse", quote="CellMapper was tested on mouse cortex.")]

        result = scope.check(facts, {"species": "zebrafish"})

        assert result["outcome"] == scope.OUTSIDE
        assert result["warnings"] == [
            "Outside what the card says: the data's species is “zebrafish”, and the card gives the species as "
            "“mouse” (the paper: “CellMapper was tested on mouse cortex.”)."
        ]
        says = result["aspects"][0]["says"][0]
        assert (says["value"], says["by"], says["page"], says["section"]) == ("mouse", "reading", 2, "Methods")

    def test_the_warning_has_every_statement_that_the_data_is_outside_of(self) -> None:
        facts = [fact("species", "mouse", "in mouse", number=1), fact("species", "human", "in human", number=2)]

        warning = scope.check(facts, {"species": "rat"})["warnings"][0]

        assert "“mouse” (the paper: “in mouse”); “human” (the paper: “in human”)" in warning

    def test_data_is_inside_only_if_every_word_that_says_what_it_is_is_on_the_card(self) -> None:
        facts = [fact("species", "mouse")]

        assert outcome(facts, species="mouse or rat") == scope.OUTSIDE
        assert outcome(facts, species="mouse and human") == scope.OUTSIDE

    def test_data_of_two_things_is_inside_a_card_that_has_a_statement_of_each(self) -> None:
        facts = [fact("species", "mouse", number=1), fact("species", "human", number=2)]

        result = scope.check(facts, {"species": "human and mouse"})

        assert result["outcome"] == scope.INSIDE and len(result["aspects"][0]["says"]) == 2

    def test_a_card_that_says_nothing_of_a_sort_does_not_cover_it_and_does_not_warn(self) -> None:
        facts = [fact("species", "mouse")]

        result = scope.check(facts, {"tissue": "liver"})

        assert result["outcome"] == scope.NOT_COVERED and result["warnings"] == []
        assert result["aspects"][0]["says"] == [] and "says nothing of the tissue" in result["aspects"][0]["reason"]

    def test_a_card_without_scope_covers_nothing(self) -> None:
        result = scope.check([], {"species": "human", "sample_size": 10})

        assert result["outcome"] == scope.NOT_COVERED
        assert [a["outcome"] for a in result["aspects"]] == [scope.NOT_COVERED] * 2 and result["warnings"] == []

    def test_a_statement_of_what_was_not_so_is_shown_and_not_compared(self) -> None:
        facts = [fact("species", "not tested on human", "It was not tested on human samples.")]

        result = scope.check(facts, {"species": "human"})

        assert result["outcome"] == scope.NOT_COVERED and result["warnings"] == []
        assert [s["value"] for s in result["aspects"][0]["says"]] == ["not tested on human"]
        assert "cannot compare" in result["aspects"][0]["reason"]

    def test_a_statement_of_what_was_not_so_does_not_make_data_that_it_does_not_name_inside(self) -> None:
        facts = [fact("species", "mouse", number=1), fact("species", "non-human primates", number=2)]

        assert outcome(facts, species="mouse") == scope.INSIDE
        assert outcome(facts, species="zebrafish") == scope.OUTSIDE
        assert outcome(facts, species="human") == scope.NOT_COVERED

    def test_a_card_that_says_it_is_of_any_covers_what_is_said_of_the_data(self) -> None:
        assert outcome([fact("species", "any species")], species="axolotl") == scope.INSIDE
        assert outcome([fact("species", "species-agnostic")], species="axolotl") == scope.INSIDE
        assert outcome([fact("species", "all mouse strains")], species="human") == scope.OUTSIDE

    def test_a_statement_with_no_word_that_says_what_it_is_is_not_compared(self) -> None:
        facts = [fact("species", "cells")]

        assert outcome(facts, species="mouse") == scope.NOT_COVERED

    def test_the_whole_is_outside_if_anything_is_and_inside_only_if_everything_is(self) -> None:
        facts = [fact("species", "mouse"), fact("tissue", "brain")]

        assert outcome(facts, species="mouse", tissue="brain") == scope.INSIDE
        assert outcome(facts, species="mouse", tissue="liver") == scope.OUTSIDE
        assert outcome(facts, species="rat", tissue="liver", assay="ATAC-seq") == scope.OUTSIDE
        assert outcome(facts, species="mouse", assay="ATAC-seq") == scope.NOT_COVERED

    def test_a_warning_is_given_for_each_thing_that_is_outside_in_the_order_they_are_checked(self) -> None:
        facts = [fact("species", "mouse"), fact("tissue", "brain"), fact("input", "h5ad")]

        warnings = scope.check(facts, {"input_format": "CSV", "tissue": "liver", "species": "rat"})["warnings"]

        assert [warning.split(" is ")[0] for warning in warnings] == [
            "Outside what the card says: the data's species",
            "Outside what the card says: the data's tissue",
            "Outside what the card says: the data's input format",
        ]

    def test_what_the_card_says_of_what_nothing_was_said_of_is_given_so_that_it_can_be_seen(self) -> None:
        facts = [fact("species", "mouse"), fact("assay", "scRNA-seq"), fact("other", "No batch effects")]

        result = scope.check(facts, {"species": "mouse"})

        assert [(each["aspect"], [s["value"] for s in each["says"]]) for each in result["not_checked"]] == [
            ("assay", ["scRNA-seq"]),
            ("other", ["No batch effects"]),
        ]

    def test_a_statement_that_is_of_something_besides_what_is_compared_is_never_compared(self) -> None:
        assert outcome([fact("other", "mouse")], species="mouse") == scope.NOT_COVERED

    def test_the_answer_is_plain_data(self) -> None:
        facts = [fact("species", "mouse"), fact("sample size", "at least 500 nuclei")]

        json.dumps(scope.check(facts, {"species": "rat", "sample_size": 100, "sample_unit": "nuclei"}))


class TestWhoseTheWordsAre:
    def test_a_statement_that_a_person_added_is_said_to_be_theirs_with_the_words_they_gave(self) -> None:
        facts = [fact("species", "mouse", "From our own notes", by="person")]

        result = scope.check(facts, {"species": "rat"})

        assert "“mouse” (added by a person: “From our own notes”)" in result["warnings"][0]
        assert result["aspects"][0]["says"][0]["by"] == "person" and result["aspects"][0]["says"][0]["page"] is None

    def test_a_statement_that_a_person_added_without_words_has_none_in_the_warning(self) -> None:
        facts = [fact("species", "mouse", "", by="person")]

        warning = scope.check(facts, {"species": "rat"})["warnings"][0]

        assert warning.endswith("as “mouse” (added by a person).")

    def test_a_statement_that_a_person_changed_has_what_they_say_and_the_papers_words(self) -> None:
        facts = [
            fact(
                "species",
                "mouse",
                "We used rat cortex.",
                by="person",
                read_as={"aspect": "species", "value": "rat"},
            )
        ]

        result = scope.check(facts, {"species": "rat"})

        # What the card says now is what is put against the data, and not the words that it was read from
        assert result["outcome"] == scope.OUTSIDE
        assert "“mouse” (changed by a person; the paper's words: “We used rat cortex.”)" in result["warnings"][0]
        assert result["aspects"][0]["says"][0]["changed"] is True

    def test_a_long_quote_is_cut_in_a_warning_and_not_in_what_is_given_back(self) -> None:
        quote = "It was used on mouse. " * 40
        facts = [fact("species", "mouse", quote)]

        result = scope.check(facts, {"species": "rat"})

        assert "…”" in result["warnings"][0] and len(result["warnings"][0]) < len(quote)
        assert result["aspects"][0]["says"][0]["quote"] == quote


class TestSampleSizes:
    @pytest.mark.parametrize(
        ("text", "low", "high", "low_open", "high_open", "unit"),
        [
            ("at least 500 nuclei", 500, None, False, False, "nucleus"),
            ("≥ 100 cells", 100, None, False, False, "cell"),
            (">= 100 cells", 100, None, False, False, "cell"),
            ("more than 500", 500, None, True, False, ""),
            ("over 1,000 cells", 1000, None, True, False, "cell"),
            ("500+ cells", 500, None, False, False, "cell"),
            ("500 or more cells", 500, None, False, False, "cell"),
            ("no more than 50 samples", None, 50, False, False, "sample"),
            ("up to 2 million reads", None, 2_000_000, False, False, "read"),
            ("fewer than 1,000", None, 1000, False, True, ""),
            ("< 1000 cells", None, 1000, False, True, "cell"),
            ("1,000 to 10,000 cells", 1000, 10000, False, False, "cell"),
            ("between 3 and 5 donors", 3, 5, False, False, "donor"),
            ("500–5000", 500, 5000, False, False, ""),
            ("10 - 20 patients", 10, 20, False, False, "patient"),
        ],
    )
    def test_a_range_is_read_from_the_words_that_give_it(
        self, text: str, low: float | None, high: float | None, low_open: bool, high_open: bool, unit: str
    ) -> None:
        size = scope.size_of(text)

        assert size is not None and not size.exact
        assert (size.low, size.high, size.low_open, size.high_open, size.unit) == (low, high, low_open, high_open, unit)

    @pytest.mark.parametrize("text", ["n = 12", "12 samples", "10k cells", "about 10,000 cells"])
    def test_one_number_is_a_size_that_was_used_and_not_a_range(self, text: str) -> None:
        size = scope.size_of(text)

        assert size is not None and size.exact and size.low == size.high

    @pytest.mark.parametrize(
        "text", ["large", "", "3 datasets of 5,000 cells", "10x Chromium 5,000 cells", "1, 2, and 3 samples"]
    )
    def test_words_that_do_not_give_one_range_are_not_read(self, text: str) -> None:
        assert scope.size_of(text) is None

    def test_a_size_is_put_against_a_range_that_has_it_or_not(self) -> None:
        facts = [fact("sample size", "at least 500 nuclei")]

        assert outcome(facts, sample_size=500, sample_unit="nuclei") == scope.INSIDE
        assert outcome(facts, sample_size=20000, sample_unit="nuclei") == scope.INSIDE
        assert outcome(facts, sample_size=499, sample_unit="nuclei") == scope.OUTSIDE

    def test_a_range_that_is_open_at_an_end_leaves_that_end_out(self) -> None:
        assert outcome([fact("sample size", "more than 500")], sample_size=500) == scope.OUTSIDE
        assert outcome([fact("sample size", "more than 500")], sample_size=501) == scope.INSIDE
        assert outcome([fact("sample size", "fewer than 50")], sample_size=50) == scope.OUTSIDE
        assert outcome([fact("sample size", "no more than 50")], sample_size=50) == scope.INSIDE
        assert outcome([fact("sample size", "1,000 to 10,000")], sample_size=10000) == scope.INSIDE
        assert outcome([fact("sample size", "1,000 to 10,000")], sample_size=10001) == scope.OUTSIDE

    def test_the_warning_for_a_size_has_the_size_and_the_range_in_the_cards_words(self) -> None:
        facts = [fact("sample size", "at least 500 nuclei", "It assumes at least 500 nuclei per sample.")]

        warning = scope.check(facts, {"sample_size": 120, "sample_unit": "nuclei"})["warnings"][0]

        assert warning == (
            "Outside what the card says: the data's sample size is “120 nuclei”, and the card gives the sample size "
            "as “at least 500 nuclei” (the paper: “It assumes at least 500 nuclei per sample.”)."
        )

    def test_a_size_of_one_kind_is_not_put_against_a_range_of_another(self) -> None:
        facts = [fact("sample size", "at least 500 nuclei")]

        result = scope.check(facts, {"sample_size": 120, "sample_unit": "patients"})

        assert result["outcome"] == scope.NOT_COVERED and result["warnings"] == []
        assert [s["value"] for s in result["aspects"][0]["says"]] == ["at least 500 nuclei"]

    def test_a_size_is_put_against_a_range_that_counts_when_the_unit_is_not_said_on_one_side(self) -> None:
        assert outcome([fact("sample size", "at least 500")], sample_size=120, sample_unit="nuclei") == scope.OUTSIDE
        assert outcome([fact("sample size", "at least 500 nuclei")], sample_size=120) == scope.OUTSIDE

    def test_a_unit_is_told_by_its_plural_and_by_any_of_its_words(self) -> None:
        facts = [fact("sample size", "at least 500 cells")]

        assert outcome(facts, sample_size=600, sample_unit="single cells") == scope.INSIDE
        assert outcome(facts, sample_size=600, sample_unit="Cells") == scope.INSIDE

    def test_one_number_covers_only_that_size_and_says_nothing_of_another(self) -> None:
        facts = [fact("sample size", "10,000 cells")]

        assert outcome(facts, sample_size=10000, sample_unit="cells") == scope.INSIDE
        result = scope.check(facts, {"sample_size": 8000, "sample_unit": "cells"})
        assert result["outcome"] == scope.NOT_COVERED and result["warnings"] == []

    def test_a_range_that_does_not_have_the_size_is_outside_even_if_another_statement_is_unreadable(self) -> None:
        facts = [fact("sample size", "at least 500 nuclei", number=1), fact("sample size", "many", number=2)]

        result = scope.check(facts, {"sample_size": 100, "sample_unit": "nuclei"})

        assert result["outcome"] == scope.OUTSIDE
        assert [s["value"] for s in result["aspects"][0]["says"]] == ["at least 500 nuclei", "many"]

    def test_a_range_that_has_the_size_covers_it_whatever_else_the_card_says(self) -> None:
        facts = [fact("sample size", "at least 500 nuclei", number=1), fact("sample size", "10 samples", number=2)]

        assert outcome(facts, sample_size=2000, sample_unit="nuclei") == scope.INSIDE

    def test_a_statement_that_is_not_a_range_is_shown_and_does_not_warn(self) -> None:
        result = scope.check([fact("sample size", "large cohorts")], {"sample_size": 5})

        assert result["outcome"] == scope.NOT_COVERED and result["warnings"] == []


class TestWhatIsSaidOfTheData:
    def test_something_must_be_said(self) -> None:
        for nothing in (
            {},
            {"species": ""},
            {"species": "   ", "sample_size": 0},
            {"species": None, "sample_size": None},
        ):
            with pytest.raises(ValueError, match="Say something of the data"):
                scope.check([], nothing)

    def test_a_thing_is_said_in_words_that_say_what_it_is(self) -> None:
        with pytest.raises(ValueError, match="species has no words that say what it is"):
            scope.check([], {"species": "the cells"})
        with pytest.raises(ValueError, match="tissue is said in words"):
            scope.check([], {"tissue": 5})
        with pytest.raises(ValueError, match="at most 200 characters"):
            scope.check([], {"assay": "scRNA-seq " * 30})

    @pytest.mark.parametrize("size", [True, -3, 1.5, "10", 10**12 + 1])
    def test_a_size_is_a_whole_number_from_one(self, size: Any) -> None:
        with pytest.raises(ValueError, match="sample size is a whole number"):
            scope.check([], {"sample_size": size})

    def test_what_a_size_counts_needs_a_size(self) -> None:
        with pytest.raises(ValueError, match="Say the sample size as well"):
            scope.check([], {"species": "mouse", "sample_unit": "cells"})
        with pytest.raises(ValueError, match="counts is said in words"):
            scope.check([], {"sample_size": 5, "sample_unit": 3})
        with pytest.raises(ValueError, match="at most 40 characters"):
            scope.check([], {"sample_size": 5, "sample_unit": "cells " * 10})

    def test_a_size_of_nothing_and_words_of_nothing_are_things_that_were_not_said(self) -> None:
        result = scope.check([fact("species", "mouse")], {"species": "mouse", "sample_size": 0, "tissue": " "})

        assert [a["aspect"] for a in result["aspects"]] == ["species"]

    def test_words_are_taken_on_one_line(self) -> None:
        result = scope.check([fact("species", "mouse")], {"species": "  Mus \n  musculus "})

        assert result["aspects"][0]["given"] == "Mus musculus"
