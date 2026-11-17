"""Tests of a number as a paper wrote it: what is read as one, which are specific enough to look for, that a number that
was given is the number that was written only if it rounds to it, and that a place in a result is found and followed
again without being believed."""

from typing import Any

import pytest

from virtual_lab.paperagents import written


class TestReadingANumberAsWritten:
    @pytest.mark.parametrize(
        ("text", "value", "decimals", "digits", "percent"),
        [
            ("0.93", 0.93, 2, 2, False),
            ("0.930", 0.93, 3, 3, False),
            ("12%", 12.0, 0, 2, True),
            ("12.5 %", 12.5, 1, 3, True),
            ("1,234", 1234.0, 0, 4, False),
            ("1,234.5", 1234.5, 1, 5, False),
            ("-0.42", -0.42, 2, 2, False),
            ("\u22120.42", -0.42, 2, 2, False),
            ("+7.10", 7.1, 2, 3, False),
            ("1200", 1200.0, 0, 2, False),
            ("0", 0.0, 0, 0, False),
            ("  4.5  ", 4.5, 1, 2, False),
        ],
    )
    def test_plain_numbers_are_read_with_the_digits_that_say_something(
        self, text: str, value: float, decimals: int, digits: int, percent: bool
    ) -> None:
        found = written.parse(text)
        assert found is not None
        assert (found.value, found.decimals, found.digits, found.percent) == (value, decimals, digits, percent)

    @pytest.mark.parametrize(
        "text",
        ["", "abc", "0.93 and", "1.2e-3", "3 x 10^-4", "1,23", "12,34,567", "1.", ".5", "p < 0.05", "1/2", "0x10"]
        + ["9" * 400, "1" * 41, "nan", "inf", "--1", "1.2.3", "12%%"],
    )
    def test_anything_but_a_plain_number_is_not_one(self, text: str) -> None:
        assert written.parse(text) is None

    @pytest.mark.parametrize("value", [None, 0.93, 93, ["0.93"], {"a": 1}, True])
    def test_what_is_not_text_is_not_a_number_as_written(self, value: Any) -> None:
        assert written.parse(value) is None

    @pytest.mark.parametrize(
        ("text", "specific"),
        [
            ("0.93", True),
            ("4.5", True),
            ("0.930", True),
            ("1,234", True),
            ("812", True),
            ("0.05", False),
            ("0.5", False),
            ("12%", False),
            ("95", False),
            ("100", False),
            ("1200", False),
            ("0", False),
            ("0.001", False),
        ],
    )
    def test_a_number_is_looked_for_only_if_it_has_digits_enough_to_be_told_from_chance(
        self, text: str, specific: bool
    ) -> None:
        found = written.parse(text)
        assert found is not None and found.specific is specific


class TestRoundingToWhatWasWritten:
    def of(self, text: str) -> written.Written:
        found = written.parse(text)
        assert found is not None

        return found

    def test_a_number_that_rounds_to_it_is_the_number_and_one_that_is_near_is_not(self) -> None:
        paper = self.of("0.93")
        for number in (0.93, 0.9312, 0.925, 0.9349, 0.935):
            assert written.close(paper, number) == written.AS_WRITTEN, number
        for number in (0.9251 - 0.001, 0.9351, 0.94, 0.9, 0.0, 93.0):
            assert written.close(paper, number) is None, number

    def test_the_edge_of_the_rounding_is_not_lost_to_the_way_that_floats_are_kept(self) -> None:
        # 0.94 - 0.935 is a little more than 0.005 as floats
        assert written.close(self.of("0.94"), 0.935) == written.AS_WRITTEN
        assert written.close(self.of("0.94"), 0.9449999) == written.AS_WRITTEN
        assert written.close(self.of("0.94"), 0.9351 - 0.0002) is None

    def test_the_place_of_the_last_digit_sets_how_near_it_must_be(self) -> None:
        assert written.close(self.of("12.34"), 12.3449) == written.AS_WRITTEN
        assert written.close(self.of("12.34"), 12.346) is None
        assert written.close(self.of("1,234"), 1234.4) == written.AS_WRITTEN
        assert written.close(self.of("1,234"), 1234.6) is None
        assert written.close(self.of("812"), 812) == written.AS_WRITTEN
        assert written.close(self.of("812"), 813) is None

    def test_a_percentage_is_met_as_written_or_as_a_part_of_one(self) -> None:
        paper = self.of("12.5%")
        assert written.close(paper, 12.5) == written.AS_WRITTEN
        assert written.close(paper, 0.125) == written.AS_PERCENT
        assert written.close(paper, 0.1254) == written.AS_PERCENT
        assert written.close(paper, 1.25) is None
        assert written.close(paper, 0.13) is None

    def test_a_number_not_written_as_a_percentage_is_not_met_as_a_part_of_one(self) -> None:
        assert written.close(self.of("12.5"), 0.125) is None

    def test_a_negative_number_is_held_to_its_sign(self) -> None:
        assert written.close(self.of("-0.42"), -0.42) == written.AS_WRITTEN
        assert written.close(self.of("-0.42"), 0.42) is None


RESULT = {
    "type": "dict",
    "plain": True,
    "value": {
        "auc": 0.9312,
        "scores": [0.1, 0.25, {"inner": 4.5}],
        "n": 812,
        "ok": True,
        "name": "x",
        "bad": {"$float": "nan"},
    },
}


class TestWhereANumberIsInAResult:
    def test_each_number_is_given_with_its_path_and_a_truth_value_and_text_are_not_numbers(self) -> None:
        found = dict(written.numbers_in(RESULT))
        assert found == {
            ("auc",): 0.9312,
            ("scores", 0): 0.1,
            ("scores", 1): 0.25,
            ("scores", 2, "inner"): 4.5,
            ("n",): 812.0,
        }

    def test_a_result_that_is_one_number_has_the_empty_path(self) -> None:
        assert written.numbers_in({"type": "float", "plain": True, "value": 2.5}) == [((), 2.5)]

    def test_what_is_kept_of_an_array_is_walked_as_its_values(self) -> None:
        array = {"type": "ndarray", "plain": False, "shape": [2], "dtype": "float64", "values": [1.5, 2.5]}
        assert written.numbers_in(array) == [((0,), 1.5), ((1,), 2.5)]

    def test_a_result_of_which_only_a_look_was_kept_has_no_numbers(self) -> None:
        assert written.numbers_in({"type": "Model", "plain": False, "repr": "<Model 1.5>"}) == []
        assert written.numbers_in({"type": "ndarray", "plain": False, "sha256": "a" * 64, "shape": [9]}) == []

    @pytest.mark.parametrize("value", [None, 1.5, "1.5", [1.5], {"plain": "yes", "value": 1.5}])
    def test_what_is_not_a_kept_result_has_no_numbers(self, value: Any) -> None:
        assert written.numbers_in(value) == []

    def test_no_more_are_looked_at_than_the_most_and_none_deeper_than_the_depth(self) -> None:
        many = {"type": "list", "plain": True, "value": list(range(50))}
        assert len(written.numbers_in(many, most=10)) == 10
        deep: Any = 1.5
        for _ in range(written.MAX_DEPTH + 2):
            deep = [deep]
        assert written.numbers_in({"type": "list", "plain": True, "value": deep}) == []

    def test_a_number_too_big_to_be_a_float_is_not_a_number(self) -> None:
        assert not written.is_number(10**400)
        assert written.numbers_in({"type": "int", "plain": True, "value": 10**400}) == []
        assert not written.is_number(True) and not written.is_number(float("inf")) and written.is_number(3)


class TestFollowingAPathAgain:
    def test_a_path_leads_to_the_same_number_in_another_result_of_the_same_shape(self) -> None:
        other = {"type": "dict", "plain": True, "value": {"auc": 0.9301, "scores": [0, 0, {"inner": 4.4}]}}
        assert written.number_at(RESULT, ("auc",)) == 0.9312
        assert written.number_at(other, ("auc",)) == 0.9301
        assert written.number_at(other, ("scores", 2, "inner")) == 4.4

    @pytest.mark.parametrize(
        "path",
        [
            ("nope",),
            ("scores", 9),
            ("scores", -1),
            ("scores", "a"),
            ("auc", 0),
            ("name",),
            ("ok",),
            ("bad",),
            ("scores",),
        ],
    )
    def test_a_path_that_leads_nowhere_or_to_what_is_not_a_number_gives_none(self, path: tuple[Any, ...]) -> None:
        assert written.number_at(RESULT, path) is None

    def test_a_truth_value_is_not_taken_for_a_position(self) -> None:
        assert written.number_at({"type": "list", "plain": True, "value": [5, 6]}, (True,)) is None

    def test_a_path_is_written_to_be_read(self) -> None:
        assert written.path_text(()) == "result"
        assert written.path_text(("scores", 2, "inner")) == "result['scores'][2]['inner']"

    @pytest.mark.parametrize(
        ("value", "valid"),
        [
            ([], True),
            (["a", 0], True),
            ([True], False),
            ([1.5], False),
            ("a", False),
            (None, False),
            (["a"] * 9, False),
        ],
    )
    def test_only_a_list_of_keys_and_positions_is_a_path(self, value: Any, valid: bool) -> None:
        assert written.valid_path(value) is valid
