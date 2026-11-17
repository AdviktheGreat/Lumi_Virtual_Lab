"""Tests of the method card as a person has corrected it, apart from where it is kept: how what a person did is put over
what a reading made, whose each fact is, what an approval covers, and what is taken for a person's edits when a record
of them is read."""

import copy
from typing import Any

import pytest

from virtual_lab.paperagents import card as method_card
from virtual_lab.paperagents.reading import CARD_KINDS


def place(start: int) -> dict[str, Any]:
    return {"start": start, "end": start + 10, "page": 1, "section": "Methods"}


def read_card() -> dict[str, Any]:
    """The card a reading made: two methods and two things that it was tested on, in the order of the paper."""
    return {
        "schema": 1,
        "status": "draft",
        "methods": [
            {"id": "method-aaaaaaaa", "name": "STAR", "quote": "aligned with STAR", "anchor": place(10)},
            {"id": "method-bbbbbbbb", "name": "Seurat", "quote": "clustered with Seurat", "anchor": place(50)},
        ],
        "datasets": [],
        "scope": [
            {"id": "scope-11111111", "aspect": "species", "value": "mouse", "quote": "in mouse", "anchor": place(20)},
            {"id": "scope-22222222", "aspect": "tissue", "value": "brain", "quote": "of brain", "anchor": place(60)},
        ],
        "limitations": [{"id": "limit-33333333", "quote": "It was slow.", "anchor": place(70)}],
    }


AT = "2026-01-01T00:00:00Z"
LATER = "2026-01-02T00:00:00Z"


def ids(card: dict[str, Any], kind: str) -> list[str]:
    return [fact["id"] for fact in card[kind]]


class TestPutOverTheReading:
    def test_a_card_that_nobody_has_touched_is_the_reading_with_every_fact_marked_as_read(self) -> None:
        card = method_card.shown(read_card(), method_card.empty_edits())

        assert (card["status"], card["edited"], card["approved_at"], card["changed_since_approval"]) == (
            "draft",
            False,
            None,
            False,
        )
        assert [fact["by"] for kind in CARD_KINDS for fact in card[kind]] == ["reading"] * 5
        assert "schema" not in card and card["removed"] == {kind: [] for kind in CARD_KINDS}

    def test_the_reading_is_not_changed(self) -> None:
        read = read_card()
        before = copy.deepcopy(read)

        edits = method_card.add(read, method_card.empty_edits(), "methods", {"name": "Ours"}, AT, "x1")
        edits = method_card.change(read, edits, "scope-11111111", {"aspect": "species", "value": "rat"}, AT)
        edits = method_card.remove(read, edits, "method-aaaaaaaa", AT)
        method_card.shown(read, edits)

        assert read == before

    def test_a_fact_a_person_added_comes_after_those_of_the_paper_and_in_the_order_they_were_added(self) -> None:
        read = read_card()
        edits = method_card.add(read, method_card.empty_edits(), "methods", {"name": "First"}, AT, "x1")
        edits = method_card.add(read, edits, "methods", {"name": "Second"}, AT, "x2")

        card = method_card.shown(read, edits)

        assert [fact["name"] for fact in card["methods"]] == ["STAR", "Seurat", "First", "Second"]

    def test_a_fact_that_was_changed_stays_where_the_paper_has_it_even_if_the_reading_no_longer_finds_it(self) -> None:
        read = read_card()
        edits = method_card.change(
            read, method_card.empty_edits(), "scope-22222222", {"aspect": "tissue", "value": "x"}, AT
        )
        edits = method_card.add(read, edits, "scope", {"aspect": "assay", "value": "RNA"}, AT, "x1")
        smaller = read_card()
        smaller["scope"] = [smaller["scope"][0]]

        card = method_card.shown(smaller, edits)

        assert [(fact["value"], fact["by"]) for fact in card["scope"]] == [
            ("mouse", "reading"),
            ("x", "person"),
            ("RNA", "person"),
        ]

    def test_a_person_may_put_in_words_of_their_own_for_a_fact_they_added_and_change_them(self) -> None:
        read = read_card()
        edits = method_card.add(read, method_card.empty_edits(), "limitations", {"quote": "Slow."}, AT, "x1")
        fact_id = "limit-ownx1"

        edits = method_card.change(read, edits, fact_id, {"quote": "Very slow."}, LATER)

        fact = method_card.shown(read, edits)["limitations"][1]
        assert (fact["id"], fact["quote"], fact["by"], fact["at"], fact["anchor"]) == (
            fact_id,
            "Very slow.",
            "person",
            LATER,
            None,
        )
        assert fact["read_as"] is None

    def test_what_a_person_changed_of_a_fact_they_added_does_not_say_it_was_read_as_anything(self) -> None:
        read = read_card()
        edits = method_card.add(read, method_card.empty_edits(), "methods", {"name": "Ours"}, AT, "x1")

        edits = method_card.change(read, edits, "method-ownx1", {"name": "Ours, again"}, LATER)

        assert method_card.shown(read, edits)["methods"][2]["read_as"] is None


class TestApproval:
    def test_what_an_approval_covers_is_the_facts_their_fields_and_whose_they_are(self) -> None:
        read = read_card()
        approved = method_card.approve(read, method_card.empty_edits(), AT)

        assert method_card.shown(read, approved)["status"] == "approved"
        for edits in (
            method_card.change(read, approved, "scope-11111111", {"aspect": "species", "value": "rat"}, AT),
            method_card.remove(read, approved, "scope-11111111", AT),
            method_card.add(read, approved, "scope", {"aspect": "assay", "value": "x"}, AT, "x1"),
        ):
            card = method_card.shown(read, edits)
            assert (card["status"], card["approved_at"], card["changed_since_approval"]) == ("draft", None, True)

    def test_a_reading_that_finds_something_else_leaves_the_approval_not_covering_it(self) -> None:
        read = read_card()
        approved = method_card.approve(read, method_card.empty_edits(), AT)
        other = read_card()
        other["methods"].append({"id": "method-cccccccc", "name": "X", "quote": "with X is it", "anchor": place(90)})

        card = method_card.shown(other, approved)

        assert (card["status"], card["changed_since_approval"]) == ("draft", True)

    def test_when_a_change_is_undone_the_card_is_the_one_that_was_approved_again(self) -> None:
        read = read_card()
        approved = method_card.approve(read, method_card.empty_edits(), AT)
        removed = method_card.remove(read, approved, "scope-11111111", AT)

        back = method_card.restore(read, removed, "scope-11111111")

        assert method_card.shown(read, back)["status"] == "approved"

    def test_a_fact_that_a_person_changed_back_to_what_it_was_read_as_is_the_readings_and_the_card_is_approved_again(
        self,
    ) -> None:
        read = read_card()
        approved = method_card.approve(read, method_card.empty_edits(), AT)
        changed = method_card.change(read, approved, "scope-11111111", {"aspect": "species", "value": "rat"}, AT)

        back = method_card.change(read, changed, "scope-11111111", {"aspect": "species", "value": "mouse"}, AT)

        card = method_card.shown(read, back)
        assert card["status"] == "approved" and card["scope"][0]["by"] == "reading" and card["edited"] is False
        assert back["facts"] == {}

    def test_a_fact_changed_back_when_the_reading_no_longer_has_it_stays_the_persons(self) -> None:
        read = read_card()
        changed = method_card.change(
            read, method_card.empty_edits(), "scope-11111111", {"aspect": "other", "value": "x"}, AT
        )
        smaller = read_card()
        smaller["scope"] = smaller["scope"][1:]

        back = method_card.change(smaller, changed, "scope-11111111", {"aspect": "species", "value": "mouse"}, LATER)

        fact = method_card.shown(smaller, back)["scope"][0]
        assert fact["by"] == "person" and fact["value"] == "mouse" and fact["id"] == "scope-11111111"

    def test_the_approval_is_withdrawn_and_nothing_else_is_lost(self) -> None:
        read = read_card()
        edits = method_card.add(read, method_card.empty_edits(), "methods", {"name": "Ours"}, AT, "x1")

        withdrawn = method_card.withdraw(method_card.approve(read, edits, AT))

        assert withdrawn == edits and method_card.shown(read, withdrawn)["changed_since_approval"] is False

    def test_a_card_whose_every_fact_was_taken_off_has_nothing_to_approve(self) -> None:
        read = read_card()
        edits = method_card.empty_edits()
        for fact in [*read["methods"], *read["scope"], *read["limitations"]]:
            edits = method_card.remove(read, edits, fact["id"], AT)

        with pytest.raises(ValueError, match="nothing to approve"):
            method_card.approve(read, edits, AT)


class TestWhatAPersonMayGive:
    def test_words_are_put_on_one_line_and_trimmed(self) -> None:
        fields, words = method_card.check_fields(
            "scope", {"aspect": "tissue", "value": " brain \n cortex ", "quote": " a\tb "}, True
        )

        assert fields == {"aspect": "tissue", "value": "brain cortex"} and words == "a b"

    def test_the_words_of_a_fact_that_was_read_are_the_papers_and_are_not_taken(self) -> None:
        with pytest.raises(ValueError, match="quote is not something"):
            method_card.check_fields("scope", {"aspect": "tissue", "value": "x", "quote": "mine"}, False)

    def test_what_is_not_text_is_refused(self) -> None:
        for wrong in (None, 3, ["a"], {"a": 1}):
            with pytest.raises(ValueError, match="is words"):
                method_card.check_fields("methods", {"name": wrong}, False)

    def test_a_fact_that_is_empty_of_words_is_not_one_and_blank_words_are_empty(self) -> None:
        with pytest.raises(ValueError, match="name must be filled in"):
            method_card.check_fields("methods", {"name": "  \n "}, False)

    def test_a_kind_that_the_card_does_not_have_is_refused(self) -> None:
        for wrong in ("claims", "software", "", None, 3):
            with pytest.raises(ValueError, match="Say which sort of fact"):
                method_card.add(read_card(), method_card.empty_edits(), wrong, {}, AT, "x")


class TestARecordOfEdits:
    def kept(self) -> dict[str, Any]:
        read = read_card()
        edits = method_card.add(read, method_card.empty_edits(), "methods", {"name": "Ours"}, AT, "x1")
        edits = method_card.change(read, edits, "scope-11111111", {"aspect": "species", "value": "rat"}, AT)
        edits = method_card.remove(read, edits, "method-aaaaaaaa", AT)

        return {"schema": method_card.SCHEMA, "file_sha256": "f" * 64, **method_card.approve(read, edits, AT)}

    def test_what_was_written_is_read_back_as_it_was(self) -> None:
        record = self.kept()

        assert method_card.edits_of(record) == {key: record[key] for key in ("facts", "removed", "approval")}

    @pytest.mark.parametrize("record", [None, [], "x", 3, {}, {"schema": 2}, {"schema": True}, {"schema": "1"}])
    def test_a_record_that_is_not_of_this_version_is_no_edits(self, record: Any) -> None:
        assert method_card.edits_of(record) == method_card.empty_edits()

    @pytest.mark.parametrize(
        "damage",
        [
            lambda fact: fact.update(kind="claims"),
            lambda fact: fact.update(by="reading"),
            lambda fact: fact.update(id="other-x1"),
            lambda fact: fact.update(id=3),
            lambda fact: fact.update(name=3),
            lambda fact: fact.pop("quote"),
            lambda fact: fact.pop("at"),
            lambda fact: fact.update(anchor={"start": True, "end": 3}),
            lambda fact: fact.update(anchor=[1, 2]),
            lambda fact: fact.update(read_as={"name": 3}),
        ],
    )
    def test_a_fact_that_is_not_in_the_shape_that_is_written_is_left_out_and_the_others_are_kept(
        self, damage: Any
    ) -> None:
        record = self.kept()
        damaged = copy.deepcopy(record)
        damage(damaged["facts"]["method-ownx1"])

        found = method_card.edits_of(damaged)

        assert list(found["facts"]) == ["scope-11111111"] and found["removed"] == record["removed"]

    def test_a_fact_that_is_filed_under_another_id_than_its_own_is_left_out(self) -> None:
        record = self.kept()
        record["facts"]["method-elsewhere"] = record["facts"].pop("method-ownx1")

        assert list(method_card.edits_of(record)["facts"]) == ["scope-11111111"]

    def test_an_approval_or_a_removal_that_is_not_text_is_left_out(self) -> None:
        record = self.kept()
        record["approval"] = {"at": AT, "of": 3}
        record["removed"] = {"method-aaaaaaaa": AT, "method-bbbbbbbb": 3, 4: AT}

        found = method_card.edits_of(record)

        assert found["approval"] is None and found["removed"] == {"method-aaaaaaaa": AT}

    def test_nothing_done_is_empty_and_something_done_is_not(self) -> None:
        assert method_card.is_empty(method_card.empty_edits())
        assert not method_card.is_empty(method_card.withdraw({**method_card.empty_edits(), "removed": {"a": AT}}))
        assert not method_card.is_empty(self.kept())
