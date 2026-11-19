"""Tests of the tables of what an agent's claims came to: that there is a row for each claim, in order, and for each
variant, that each says what the server shows and no more, that a claim that is stale is not given what an earlier
trying said of it, that a variant is given beside the claim's own result and is said not to be the paper's, and that
what a paper says is made safe to open in a spreadsheet."""

import csv
import io
from typing import Any

from virtual_lab.paper_batch import csv_bytes
from virtual_lab.paperagents import reporting, reproducing, varying


def link(path: str = "examples/demo.py", call: int | None = 2, got: float = 0.93) -> dict[str, Any]:
    return {
        "tutorial": {"id": "demo", "path": path},
        "call": call,
        "where": f"the call of tally in {path}" if call is not None else 'a printed line "AUROC 0.93"',
        "got": got,
    }


def claim(
    id: str = "c1",
    status: str = "reproduced",
    value: str = "0.93",
    reason: str | None = None,
    linked: dict[str, Any] | None = None,
    **more: Any,
) -> dict[str, Any]:
    return {
        "id": id,
        "kind": "number",
        "value": value,
        "quote": f"The AUROC was {value}.",
        "status": status,
        "reason": reason,
        "summary": f"It came to {status}.",
        "link": linked if linked is not None else link(),
        **more,
    }


def reproduction(*claims: dict[str, Any]) -> dict[str, Any]:
    return {"claims": list(claims)}


def divergence(*claims: dict[str, Any]) -> dict[str, Any]:
    return {"claims": list(claims)}


def variants(*made: dict[str, Any]) -> dict[str, Any]:
    return {"variants": list(made)}


def point(id: str, text: str, differences: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "id": id,
        "point": {"text": text},
        "differences": [{"kind": "package", "text": each} for each in differences],
    }


def variant(claim_id: str = "c1", **more: Any) -> dict[str, Any]:
    return {
        "id": "0123456789ab",
        "made_at": "2026-01-02T03:04:05Z",
        "note": None,
        "claim": claim_id,
        "quote": "The AUROC was 0.93.",
        "number": "0.93",
        "where": "the call of tally in examples/demo.py",
        "claim_run": 0.93,
        "changes": [{"name": "scale", "was": 2, "now": 3}],
        "control": {"verdict": "match", "gave": 0.93, "differences": [], "error": None},
        "variant": {
            "status": "gave",
            "gave": 1.395,
            "values": [1.395],
            "type": "float",
            "error": None,
            "differences": [],
        },
        "comparable": True,
        "rounds_to_paper": False,
        "text": f"It gave 1.395. {varying.CLOSING}",
        **more,
    }


def rows_of(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> list[list[Any]]:
    return [[row[column] for column in columns] for row in rows]


class TestTheClaims:
    def test_each_claim_of_the_paper_has_a_row_in_its_order_with_every_column(self) -> None:
        shown = reproduction(claim("c3"), claim("c1", "not_reproduced"), claim("c2", "partly"))

        rows = reporting.claim_rows(shown, divergence(), variants())

        assert [row["Claim"] for row in rows] == ["c3", "c1", "c2"]
        assert all(set(row) == set(reporting.CLAIM_COLUMNS) for row in rows)
        assert [row["Status"] for row in rows] == ["Reproduced", "Not reproduced", "Partly reproduced"]

    def test_what_a_claim_was_held_to_is_given_with_where_and_what_the_tutorial_gave(self) -> None:
        rows = reporting.claim_rows(reproduction(claim()), divergence(), variants())

        [row] = rows
        assert (row["Paper reports"], row["Sentence"]) == ("0.93", "The AUROC was 0.93.")
        assert (row["Tutorial"], row["Call"], row["What the tutorial gave"]) == ("examples/demo.py", 2, 0.93)
        assert row["Where in what it gave"] == "the call of tally in examples/demo.py"
        assert row["What it came to"] == "It came to reproduced."

    def test_a_claim_held_to_a_printed_line_has_no_call(self) -> None:
        [row] = reporting.claim_rows(reproduction(claim(linked=link(call=None))), divergence(), variants())

        assert row["Call"] == "" and row["Where in what it gave"] == 'a printed line "AUROC 0.93"'

    def test_a_claim_that_was_not_attempted_says_why_in_words_and_has_nothing_it_was_held_to(self) -> None:
        shown = reproduction({**claim(status="not_attempted", reason="no_code"), "link": None})

        [row] = reporting.claim_rows(shown, divergence(), variants())

        assert row["Status"] == "Not attempted"
        assert row["Why it was not attempted"] == reproducing.REASONS["no_code"]
        assert [row[column] for column in ("Tutorial", "Call", "Where in what it gave", "What the tutorial gave")] == [
            ""
        ] * 4

    def test_a_reason_that_the_page_does_not_know_is_given_as_it_is(self) -> None:
        shown = reproduction({**claim(status="not_attempted", reason="something_new"), "link": None})

        [row] = reporting.claim_rows(shown, divergence(), variants())

        assert row["Why it was not attempted"] == "something_new"

    def test_a_claim_that_was_reproduced_has_no_reason(self) -> None:
        [row] = reporting.claim_rows(reproduction(claim()), divergence(), variants())

        assert row["Why it was not attempted"] == ""

    def test_a_stale_claim_is_said_to_be_with_what_it_was_and_is_given_nothing_that_the_earlier_trying_said(
        self,
    ) -> None:
        shown = reproduction(claim(status="stale", was="reproduced", reason="no_code"))
        looked = divergence(point("c1", "It first parts here.", ("The package differs.",)))

        [row] = reporting.claim_rows(shown, looked, variants(variant()))

        assert row["Status"] == "Stale (was Reproduced)"
        for column in reporting.CLAIM_COLUMNS[4:12]:
            assert row[column] == "", column
        assert row["Variants made"] == 1

    def test_a_stale_claim_that_was_not_attempted_is_said_to_have_been_not_attempted(self) -> None:
        [row] = reporting.claim_rows(reproduction(claim(status="stale", was="not_attempted")), divergence(), variants())

        assert row["Status"] == "Stale (was Not attempted)"

    def test_a_stale_claim_with_no_earlier_status_is_only_said_to_be_stale(self) -> None:
        assert reporting.status_title({"status": "stale"}) == "Stale"
        assert reporting.status_title({"status": "stale", "was": None}) == "Stale"

    def test_a_status_that_is_not_known_is_given_as_it_is(self) -> None:
        assert reporting.status_title({"status": "something_new"}) == "something_new"

    def test_where_a_claim_first_parts_and_what_differs_are_given_for_the_claims_that_have_them(self) -> None:
        shown = reproduction(claim("c1", "not_reproduced"), claim("c2", "partly"), claim("c3"))
        looked = divergence(
            point("c1", "The output first parts here.", ("Python is 3.11.", "Seed was not set.")),
            {"id": "c2", "point": None, "differences": [{"kind": "data", "text": "No data was given."}]},
        )

        rows = reporting.claim_rows(shown, looked, variants())

        first, second, third = rows
        assert first["Where it first parts from the paper"] == "The output first parts here."
        assert first["Differences found (not shown to be why)"] == "Python is 3.11. Seed was not set."
        assert second["Where it first parts from the paper"] == ""
        assert second["Differences found (not shown to be why)"] == "No data was given."
        assert (
            third["Where it first parts from the paper"] == ""
            and third["Differences found (not shown to be why)"] == ""
        )

    def test_how_many_variants_were_made_of_each_claim_is_counted(self) -> None:
        shown = reproduction(claim("c1"), claim("c2"), claim("c3"))

        rows = reporting.claim_rows(shown, divergence(), variants(variant("c2"), variant("c1"), variant("c2")))

        assert [row["Variants made"] for row in rows] == [1, 2, 0]

    def test_no_claims_is_no_rows(self) -> None:
        assert reporting.claim_rows(reproduction(), divergence(), variants()) == []

    def test_what_the_rows_are_made_from_is_not_changed(self) -> None:
        shown = reproduction(claim(status="stale", was="reproduced"), claim("c2"))
        looked = divergence(point("c2", "x", ("y",)))
        made = variants(variant("c2"))
        before = repr((shown, looked, made))

        reporting.claim_rows(shown, looked, made)
        reporting.variant_rows(shown, made)

        assert repr((shown, looked, made)) == before


class TestTheVariants:
    def test_each_variant_has_a_row_in_the_order_it_was_made_with_every_column(self) -> None:
        shown = reproduction(claim("c1"), claim("c2", "not_reproduced"))

        rows = reporting.variant_rows(shown, variants(variant("c2", id="b" * 12), variant("c1")))

        assert [row["Claim"] for row in rows] == ["c2", "c1"]
        assert all(set(row) == set(reporting.VARIANT_COLUMNS) for row in rows)

    def test_a_variant_is_given_beside_the_claim_s_own_result_and_is_said_not_to_be_the_paper_s(self) -> None:
        [row] = reporting.variant_rows(reproduction(claim("c1", "not_reproduced")), variants(variant("c1")))

        assert row["The claim's own result"] == "Not reproduced"
        assert row["Is it the paper's result"] == "No"
        assert row["What it came to"].endswith(varying.CLOSING)

    def test_what_a_variant_came_to_is_given_in_full(self) -> None:
        [row] = reporting.variant_rows(reproduction(claim()), variants(variant(note="What if the scale were three?")))

        assert (row["Paper reports"], row["Sentence"], row["Made"]) == (
            "0.93",
            "The AUROC was 0.93.",
            "2026-01-02T03:04:05Z",
        )
        assert row["Changed"] == "scale = 3 in place of 2"
        assert row["The call with nothing changed"] == "Gave what the tutorial got"
        assert row["The variant"] == "Gave a number"
        assert (
            row["Number the tutorial's call gave"],
            row["Number with nothing changed"],
            row["Number the variant gave"],
        ) == (
            0.93,
            0.93,
            1.395,
        )
        assert row["Where"] == "the call of tally in examples/demo.py"
        assert (row["Comparable"], row["Rounds to the paper's number"]) == ("Yes", "No")
        assert row["Note"] == "What if the scale were three?"

    def test_whether_it_rounds_to_the_paper_s_number_is_yes_no_or_not_said(self) -> None:
        shown = reproduction(claim())
        rows = reporting.variant_rows(
            shown,
            variants(variant(rounds_to_paper=True), variant(rounds_to_paper=False), variant(rounds_to_paper=None)),
        )

        assert [row["Rounds to the paper's number"] for row in rows] == ["Yes", "No", ""]

    def test_a_variant_that_was_not_comparable_is_said_not_to_be(self) -> None:
        [row] = reporting.variant_rows(reproduction(claim()), variants(variant(comparable=False)))

        assert row["Comparable"] == "No"

    def test_how_the_call_with_nothing_changed_went_is_in_words(self) -> None:
        shown = reproduction(claim())
        verdicts = ("match", "differs", "error", "not_run", "something_new")

        rows = reporting.variant_rows(
            shown,
            variants(
                *(
                    variant(control={"verdict": each, "gave": None, "differences": [], "error": None})
                    for each in verdicts
                )
            ),
        )

        assert [row["The call with nothing changed"] for row in rows] == [
            "Gave what the tutorial got",
            "Did not give what the tutorial got",
            "Stopped with an error",
            "Was not made in the time",
            "something_new",
        ]
        assert {row["Number with nothing changed"] for row in rows} == {""}

    def test_how_the_variant_went_is_in_words_and_has_no_number_unless_it_gave_one(self) -> None:
        shown = reproduction(claim())
        statuses = ("gave", "no_place", "unstable", "error", "not_run", "something_new")
        none = {"gave": None, "values": [], "type": None, "error": None, "differences": []}

        rows = reporting.variant_rows(
            shown, variants(*(variant(variant={**none, "status": each}) for each in statuses))
        )

        assert [row["The variant"] for row in rows] == [
            "Gave a number",
            "Gave no number at the place",
            "Gave something else each time",
            "Stopped with an error",
            "Was not made in the time",
            "something_new",
        ]
        assert {row["Number the variant gave"] for row in rows} == {""}

    def test_a_number_that_is_zero_is_given_and_not_taken_for_none(self) -> None:
        zero = {"status": "gave", "gave": 0.0, "values": [0.0], "type": "float", "error": None, "differences": []}

        [row] = reporting.variant_rows(
            reproduction(claim()),
            variants(variant(variant=zero, control={"verdict": "match", "gave": 0, "differences": [], "error": None})),
        )

        assert row["Number the variant gave"] == 0.0 and row["Number with nothing changed"] == 0

    def test_a_variant_of_a_claim_that_is_not_listed_has_no_result_of_the_claim_to_be_beside(self) -> None:
        [row] = reporting.variant_rows(reproduction(claim("c1")), variants(variant("other")))

        assert row["The claim's own result"] == ""

    def test_no_note_is_an_empty_cell(self) -> None:
        [row] = reporting.variant_rows(reproduction(claim()), variants(variant(note=None)))

        assert row["Note"] == ""

    def test_no_variants_is_no_rows(self) -> None:
        assert reporting.variant_rows(reproduction(claim()), variants()) == []

    def test_what_was_changed_is_given_with_every_value_in_full_as_json(self) -> None:
        changes = [
            {"name": "genes", "was": ["a", "ß"], "now": ["a", "é", "c" * 80]},
            {"name": "flag", "was": True, "now": None},
            {"name": "table", "was": {"x": 1}, "now": {"x": [1.5, 2]}},
        ]

        said = reporting.changes_in_words(changes)

        assert said == (
            f'genes = ["a", "é", "{"c" * 80}"] in place of ["a", "ß"]; flag = null in place of true; '
            'table = {"x": [1.5, 2]} in place of {"x": 1}'
        )


class TestOpeningInASpreadsheet:
    def test_what_a_paper_says_that_a_spreadsheet_would_read_as_a_formula_is_made_text(self) -> None:
        hostile = {**claim(), "quote": '=HYPERLINK("http://example.com")', "value": "+1"}
        text = csv_bytes(reporting.CLAIM_COLUMNS, reporting.claim_rows(reproduction(hostile), divergence(), variants()))

        [row] = csv.DictReader(io.StringIO(text.decode("utf-8")))

        assert row["Sentence"].startswith("'=") and row["Paper reports"] == "'+1"

    def test_a_note_and_a_change_that_a_person_wrote_are_made_text_too(self) -> None:
        hostile = variant(note="@SUM(1)", changes=[{"name": "-x", "was": 1, "now": 2}])
        text = csv_bytes(reporting.VARIANT_COLUMNS, reporting.variant_rows(reproduction(claim()), variants(hostile)))

        [row] = csv.DictReader(io.StringIO(text.decode("utf-8")))

        assert row["Note"] == "'@SUM(1)" and row["Changed"] == "'-x = 2 in place of 1"

    def test_the_columns_are_the_header_and_a_cell_with_a_comma_or_a_line_break_is_one_cell(self) -> None:
        shown = reproduction({**claim(), "quote": 'It was 0.93, "very" good.\nAs said.'})

        text = csv_bytes(reporting.CLAIM_COLUMNS, reporting.claim_rows(shown, divergence(), variants()))
        [header, row] = list(csv.reader(io.StringIO(text.decode("utf-8"))))

        assert tuple(header) == reporting.CLAIM_COLUMNS and len(row) == len(header)
        assert row[2] == 'It was 0.93, "very" good.\nAs said.'

    def test_there_are_two_tables_and_each_is_named(self) -> None:
        assert reporting.KINDS == ("claims", "variants")
        assert len(set(reporting.CLAIM_COLUMNS)) == len(reporting.CLAIM_COLUMNS)
        assert len(set(reporting.VARIANT_COLUMNS)) == len(reporting.VARIANT_COLUMNS)
