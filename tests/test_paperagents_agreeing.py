"""Tests of whether two methods gave the same answer, from what was kept of each: that numbers are held to a tolerance
and the rest to what it is, that a result of which only a hash or a look was kept is not said to agree or to differ
when that does not say, and that two runs are only compared if they were made on the same data."""

from typing import Any

import pytest

from virtual_lab.paperagents import agreeing as ag
from virtual_lab.paperagents import comparing

TOLERANCE = comparing.Tolerance()
LOOSE = comparing.Tolerance(relative=0.01, absolute=0.0)


def whole(value: Any) -> dict[str, Any]:
    return {"type": type(value).__name__, "value": value}


def look(kind: str = "ndarray", **kept: Any) -> dict[str, Any]:
    return {
        "type": kind,
        "repr": "array([...])",
        "note": "This is not plain data, so it is described and not sent.",
        **kept,
    }


def too_big(digest: str = "a" * 64, kind: str = "list") -> dict[str, Any]:
    return {"type": kind, "chars": 2_000_000, "sha256": digest, "note": "It gave more than can be kept."}


def verdict(first: dict[str, Any], second: dict[str, Any], tolerance: comparing.Tolerance = TOLERANCE) -> str:
    return str(ag.compare(first, second, tolerance)["verdict"])


class TestHowMuchWasKept:
    def test_a_result_with_its_value_is_whole_one_with_only_a_hash_is_a_hash_and_any_other_is_a_look(self) -> None:
        assert ag.kept_as(whole([1, 2])) == ag.WHOLE
        assert ag.kept_as(whole(None)) == ag.WHOLE
        assert ag.kept_as(too_big()) == ag.HASH
        assert ag.kept_as(look(values=[1, 2], shape=[2])) == ag.LOOK
        assert ag.kept_as(look(sha256="b" * 64)) == ag.LOOK


class TestTwoResultsThatWereKeptWhole:
    @pytest.mark.parametrize(
        ("first", "second"),
        [
            (3, 3),
            (3, 3.0),
            (0.1 + 0.2, 0.3),
            ("type1", "type1"),
            ([1, 2.0, "a"], [1, 2, "a"]),
            ({"a": [1, 2], "b": {"c": 1.0}}, {"b": {"c": 1}, "a": [1, 2]}),
            (None, None),
            (True, True),
            ([], []),
            ({"$float": "nan"}, {"$float": "nan"}),
        ],
    )
    def test_answers_that_are_the_same_within_the_tolerance_agree(self, first: Any, second: Any) -> None:
        found = ag.compare(whole(first), whole(second), TOLERANCE)

        assert found["verdict"] == ag.AGREE and found["differences"] == []
        assert found["kept"] == [ag.WHOLE, ag.WHOLE]

    @pytest.mark.parametrize(
        ("first", "second", "says"),
        [
            (3, 4, "the result is 3 against 4"),
            (1.0, 1.1, "the result is 1.0 against 1.1"),
            ("a", "b", "the result is 'a' against 'b'"),
            ("1", 1, "the result is '1' against 1"),
            (True, 1, "the result is True against 1"),
            (None, 0, "the result is None against 0"),
            ([1, 2], [1, 2, 3], "the result has 2 items against 3"),
            ({"a": 1}, {"b": 1}, "the result has the keys ['a'] against ['b']"),
            ([1, 2, [3, 4]], [1, 2, [3, 5]], "[2][1] is 4 against 5"),
            ({"a": {"b": [1]}}, {"a": {"b": [2]}}, "a.b[0] is 1 against 2"),
            ({"$float": "nan"}, {"$float": "inf"}, "the result is {'$float': 'nan'} against {'$float': 'inf'}"),
            ({"$float": "nan"}, 1.0, "the result is {'$float': 'nan'} against 1.0"),
            ([1], {"a": 1}, "the result is [1] against {'a': 1}"),
        ],
    )
    def test_answers_that_differ_are_said_to_and_where(self, first: Any, second: Any, says: str) -> None:
        found = ag.compare(whole(first), whole(second), TOLERANCE)

        assert found["verdict"] == ag.DIFFER
        assert [difference.lower() for difference in found["differences"]][0].startswith(says.lower())

    def test_a_whole_number_and_a_number_that_is_not_whole_are_both_numbers_but_two_whole_numbers_are_exact(
        self,
    ) -> None:
        assert verdict(whole(2), whole(2.0)) == ag.AGREE
        assert verdict(whole(10**20), whole(10**20 + 1)) == ag.DIFFER
        assert verdict(whole(10**400), whole(float(1))) == ag.DIFFER
        assert verdict(whole(10**400), whole(10**400)) == ag.AGREE
        assert verdict(whole(1_000_000), whole(1_000_000.0000001)) == ag.AGREE
        assert verdict(whole(1_000_000.0000001), whole(1_000_000)) == ag.AGREE

    def test_a_number_that_a_bit_is_off_agrees_only_if_the_tolerance_is_wide_enough_to_say_so(self) -> None:
        assert verdict(whole(100.0), whole(100.5)) == ag.DIFFER
        assert verdict(whole(100.0), whole(100.5), LOOSE) == ag.AGREE
        assert verdict(whole(0.0), whole(1e-10)) == ag.AGREE
        assert verdict(whole(0.0), whole(1e-3), LOOSE) == ag.DIFFER

    def test_no_more_than_a_few_differences_are_given(self) -> None:
        found = ag.compare(whole(list(range(20))), whole(list(range(100, 120))), TOLERANCE)

        assert found["verdict"] == ag.DIFFER and len(found["differences"]) == comparing.MAX_DIFFERENCES


class TestResultsThatWereNotKeptWhole:
    def test_a_result_that_is_whole_and_one_that_is_only_a_look_are_not_told_to_agree_or_to_differ(self) -> None:
        found = ag.compare(whole([1, 2]), look("list", values=[1, 2]), TOLERANCE)

        assert found["verdict"] == ag.UNKNOWN and "cannot be compared" in found["how"]
        assert found["kept"] == [ag.WHOLE, ag.LOOK]
        backwards = ag.compare(look("list", values=[1, 2]), whole([1, 2]), TOLERANCE)
        assert backwards["verdict"] == ag.UNKNOWN and backwards["kept"] == [ag.LOOK, ag.WHOLE]
        assert "cannot be compared" in backwards["how"]

    def test_two_results_that_are_not_the_same_kind_are_not_compared(self) -> None:
        found = ag.compare(look("ndarray", values=[1]), look("DataFrame", values={"a": [1]}), TOLERANCE)

        assert found["verdict"] == ag.UNKNOWN and "'ndarray' and 'DataFrame'" in found["how"]

    def test_arrays_with_their_values_are_held_to_the_tolerance_as_lists_are(self) -> None:
        first = look(values=[1.0, 2.0], shape=[2], sha256="a" * 64)

        assert verdict(first, look(values=[1.0, 2.0 + 1e-12], shape=[2], sha256="b" * 64)) == ag.AGREE
        assert verdict(first, look(values=[1.0, 2.5], shape=[2], sha256="b" * 64)) == ag.DIFFER
        assert (
            verdict(first, look(values=[1.0, 2.5], shape=[2], sha256="b" * 64), comparing.Tolerance(0.5, 0)) == ag.AGREE
        )

    def test_arrays_of_other_shapes_differ_whatever_else_was_kept(self) -> None:
        found = ag.compare(look(shape=[2, 3], sha256="a" * 64), look(shape=[3, 2], sha256="a" * 64), TOLERANCE)

        assert found["verdict"] == ag.DIFFER and found["differences"] == ["The shape is [2, 3] against [3, 2]"]

    def test_a_shape_that_was_kept_of_one_only_is_not_a_shape_that_differs(self) -> None:
        with_shape = look(shape=[3], sha256="a" * 64)
        without = look(sha256="a" * 64)

        assert verdict(with_shape, without) == ag.AGREE and verdict(without, with_shape) == ag.AGREE
        assert verdict(look("Frame", repr="a b", shape=[1]), look("Frame", repr="a b")) == ag.UNKNOWN
        assert verdict(look("Frame", repr="a b"), look("Frame", repr="a b", shape=[1])) == ag.UNKNOWN

    def test_arrays_of_which_the_values_were_kept_of_one_only_are_not_told_apart(self) -> None:
        found = ag.compare(look(values=[1], shape=[1]), look(shape=[1], sha256="a" * 64), TOLERANCE)

        assert found["verdict"] == ag.UNKNOWN and "kept of one and not of the other" in found["how"]

    def test_arrays_of_which_only_the_hashes_were_kept_agree_if_they_are_the_same_and_are_not_known_to_if_they_are_not(
        self,
    ) -> None:
        same = ag.compare(look(shape=[3], sha256="a" * 64), look(shape=[3], sha256="a" * 64), TOLERANCE)
        apart = ag.compare(look(shape=[3], sha256="a" * 64), look(shape=[3], sha256="b" * 64), TOLERANCE)

        assert same["verdict"] == ag.AGREE and "hashes" in same["how"]
        assert apart["verdict"] == ag.UNKNOWN and "does not say how close" in apart["how"]

    def test_what_shows_itself_in_full_is_told_apart_by_it_and_what_does_not_is_not(self) -> None:
        one = look("Model", repr="Model(a=1)")
        assert verdict(one, look("Model", repr="Model(a=1)")) == ag.AGREE
        found = ag.compare(one, look("Model", repr="Model(a=2)"), TOLERANCE)
        assert found["verdict"] == ag.DIFFER and found["differences"] == [
            "It shows as 'Model(a=1)' against 'Model(a=2)'"
        ]
        for hidden in ("<Model object at 0x7f>", "Model(a=1) [cut]", "<Model that could not be shown>"):
            assert verdict(look("Model", repr=hidden), look("Model", repr=hidden)) == ag.UNKNOWN
        assert verdict(look("Frame", repr="a b", shape=[1, 2]), look("Frame", repr="a b", shape=[1, 2])) == ag.UNKNOWN

    def test_results_that_were_more_than_could_be_kept_agree_if_their_hashes_are_the_same_and_are_not_known_to_if_not(
        self,
    ) -> None:
        assert verdict(too_big("a" * 64), too_big("a" * 64)) == ag.AGREE
        assert verdict(too_big("a" * 64), too_big("b" * 64)) == ag.UNKNOWN
        assert verdict(too_big("a" * 64), look("list", sha256="a" * 64, shape=[1])) == ag.UNKNOWN
        assert verdict(too_big("a" * 64), too_big("a" * 64, "dict")) == ag.UNKNOWN
        assert verdict(too_big(), whole([1])) == ag.UNKNOWN

    def test_results_that_were_more_than_could_be_kept_and_have_no_hash_are_not_told_to_agree(self) -> None:
        bare = {"type": "list", "chars": 5}

        assert verdict(bare, dict(bare)) == ag.UNKNOWN
        assert verdict(bare, too_big(kind="list")) == ag.UNKNOWN

    def test_a_value_that_is_nested_too_deeply_to_be_compared_is_not_told_to_agree_or_to_differ(self) -> None:
        deep: Any = 1
        for _ in range(5000):
            deep = [deep]

        found = ag.compare(whole(deep), whole(deep), TOLERANCE)

        assert found["verdict"] == ag.UNKNOWN and "nested too deeply" in found["how"]


def run_of(result: dict[str, Any] | None, state: str = "ran", fingerprint: str = "f" * 64, own: str = "x.csv") -> Any:
    return {
        "state": state,
        "result": result,
        "data": {"own": own, "fingerprint": fingerprint} if state == "ran" else None,
    }


class TestTwoRuns:
    def test_two_runs_on_the_data_as_it_was_listed_both_times_are_compared_by_what_they_gave(self) -> None:
        found = ag.compare_runs(run_of(whole([1, 2])), run_of(whole([1, 3])), TOLERANCE)

        assert found["verdict"] == ag.DIFFER

    @pytest.mark.parametrize("other", [run_of(whole([1, 2]), fingerprint="e" * 64), run_of(whole([1, 2]), own="y.csv")])
    def test_runs_that_were_made_on_the_data_as_it_was_at_different_times_were_not_asked_the_same_thing(
        self, other: Any
    ) -> None:
        found = ag.compare_runs(run_of(whole([1, 2])), other, TOLERANCE)

        assert found["verdict"] == ag.UNKNOWN and "different times" in found["how"]
        assert found["kept"] == [ag.WHOLE, ag.WHOLE]

    def test_each_two_methods_that_gave_an_answer_are_paired_in_order_and_the_rest_are_left_out(self) -> None:
        runs = {
            "aaaaaaaa": run_of(whole(1)),
            "bbbbbbbb": None,
            "cccccccc": run_of(None, state="failed"),
            "dddddddd": run_of(whole(1.0)),
            "eeeeeeee": run_of(whole(2)),
            "ffffffff": run_of(None, state="not_run"),
        }

        found = ag.pairs(runs, TOLERANCE)

        assert [(each["first"], each["second"], each["verdict"]) for each in found] == [
            ("aaaaaaaa", "dddddddd", ag.AGREE),
            ("aaaaaaaa", "eeeeeeee", ag.DIFFER),
            ("dddddddd", "eeeeeeee", ag.DIFFER),
        ]
        assert ag.pairs({"aaaaaaaa": run_of(whole(1))}, TOLERANCE) == []
        assert ag.pairs({}, TOLERANCE) == []


class TestATolerance:
    @pytest.mark.parametrize(
        ("relative", "absolute", "allowed"),
        [
            (0, 0, True),
            (1e-6, 1e-9, True),
            (0.999, 5, True),
            (1, 0, False),
            (-1e-6, 0, False),
            (0, -1, False),
            (float("nan"), 0, False),
            (0, float("inf"), False),
            (True, 0, False),
            ("1e-6", 0, False),
            (None, 0, False),
        ],
    )
    def test_it_is_numbers_that_are_finite_and_not_negative_and_a_relative_one_is_less_than_one(
        self, relative: Any, absolute: Any, allowed: bool
    ) -> None:
        assert ag.is_tolerance(relative, absolute) is allowed
