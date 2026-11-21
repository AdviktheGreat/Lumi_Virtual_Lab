"""Tests of the rows that a bake-off's comparison is written as: that a thing that is not known is the word for it and
not a blank, that a blank is for what does not apply, and that each cell is of what its column says."""

from typing import Any

from virtual_lab.paperagents import bakeoff_table as table


def method(name: str, **given: Any) -> dict[str, Any]:
    return {
        "id": name.lower()[:8].ljust(8, "0"),
        "name": name,
        "title": f"The paper of {name}",
        "agent": {"id": "a"},
        "state": "ran",
        "why": None,
        "reason": "",
        "tier": "A",
        "tool": "map_cells",
        "seconds": 1.5,
        "cost": {"reading": 0.25, "asking": 0.0},
        "by": "person",
        "kept": "whole",
        "since": [],
        "score": None,
        "agrees": [],
        "differs": [],
        "unknown": [],
        **given,
    }


def comparison(*methods: dict[str, Any], pairs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"methods": list(methods), "pairs": pairs or [], "tolerance": {"relative": 1e-6, "absolute": 1e-9}}


class TestTheRowsOfMethods:
    def test_a_cost_that_is_not_known_is_said_so_and_one_that_does_not_apply_is_left_blank(self) -> None:
        unknown = method("Unknown", cost={"reading": None, "asking": None}, by="model")
        nothing = method(
            "Nothing", agent=None, by=None, state="not_built", tier=None, tool=None, seconds=None, kept=None
        )

        known, unreported, none_at_all = table.method_rows(comparison(method("Known"), unknown, nothing))

        assert (known["Cost of reading its paper"], known["Cost of asking a model for the call"]) == (0.25, 0.0)
        assert unreported["Cost of reading its paper"] == "not known"
        assert unreported["Cost of asking a model for the call"] == "not known"
        assert unreported["The call was made by"] == "A model, checked by a program"
        assert (
            none_at_all["Cost of reading its paper"] == "" and none_at_all["Cost of asking a model for the call"] == ""
        )
        assert none_at_all["The call was made by"] == "" and none_at_all["What was kept of its answer"] == ""
        assert (none_at_all["Trust tier"], none_at_all["Tool called"], none_at_all["Seconds"]) == ("", "", "")

    def test_a_cost_is_to_the_millionth_of_a_dollar(self) -> None:
        [row] = table.method_rows(comparison(method("Priced", cost={"reading": 0.123456789, "asking": 1e-9})))

        assert (row["Cost of reading its paper"], row["Cost of asking a model for the call"]) == (0.123457, 0.0)

    def test_each_of_agrees_differs_and_not_known_is_its_own_column_of_the_names_of_the_other_methods(self) -> None:
        first = method("First", agrees=["second00"], differs=["third000"], unknown=["fourth00"])
        rows = table.method_rows(
            comparison(
                first,
                method("Second"),
                method("Third"),
                method("Fourth"),
                method("Fifth", agrees=["second00", "third000"]),
            )
        )

        assert (rows[0]["Agrees with"], rows[0]["Differs from"], rows[0]["Not known whether it agrees with"]) == (
            "Second",
            "Third",
            "Fourth",
        )
        assert rows[4]["Agrees with"] == "Second; Third" and rows[4]["Differs from"] == ""

    def test_what_is_not_as_it_was_is_said_in_words(self) -> None:
        [row] = table.method_rows(comparison(method("Old", since=["data", "method"], state="failed", why="error")))

        assert row["Since it ran"] == "The data is not as it was listed then; The method was built again or is gone"
        assert (row["State"], row["Why (kind)"]) == ("Failed", "error")


class TestTheRowsOfPairs:
    def test_each_pair_names_the_methods_and_what_was_kept_of_each_answer_in_its_own_order(self) -> None:
        pair = {
            "first": "first000",
            "second": "second00",
            "verdict": "unknown",
            "how": "Not compared.",
            "differences": ["a", "b"],
            "kept": ["whole", "hash"],
        }

        [row] = table.pair_rows(comparison(method("First"), method("Second"), pairs=[pair]))

        assert (row["Method"], row["Other method"], row["Agree"]) == ("First", "Second", "Not known")
        assert (row["Kept of the method's answer"], row["Kept of the other's answer"]) == (
            "All of it",
            "Only a hash of it",
        )
        assert (row["How that is known"], row["What differs"]) == ("Not compared.", "a; b")
        assert (row["Relative tolerance"], row["Absolute tolerance"]) == (1e-6, 1e-9)
