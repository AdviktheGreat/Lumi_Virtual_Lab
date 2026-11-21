"""Tests of holding what a method gave to the right answers that a person has: how a list and an object are matched to
the rows, what an item has to be to match a label, that a missing item is wrong and an extra one is counted, that what
cannot be held to the labels is not scored and says why, and that ranking is by the number matched and shares a rank."""

import time
from typing import Any

import pytest

from virtual_lab.paperagents import comparing, labelling, scoring

TOLERANCE = comparing.Tolerance()
LOOSE = comparing.Tolerance(relative=0.1, absolute=0)


def labels_of(
    answers: list[str | None], ids: list[str | None] | None = None, column: str = "type", id_column: str | None = None
) -> labelling.Labels:
    return labelling.Labels(
        column=column,
        id_column=id_column if id_column is not None or ids is None else "cell",
        answers=tuple(answers),
        ids=tuple(ids) if ids is not None else None,
        sha256="0" * 64,
        size=1,
    )


def whole(value: Any) -> dict[str, Any]:
    return {"type": type(value).__name__, "value": value}


def look(values: Any, shape: list[int], **more: Any) -> dict[str, Any]:
    return {"type": "ndarray", "repr": "array(...)", "shape": shape, "values": values, "note": "A look.", **more}


def scored(found: dict[str, Any]) -> tuple[Any, ...]:
    assert found["scored"] is True and found["why"] is None and found["reason"] == "", found
    return found["by"], found["matched"], found["of"], found["missing"], found["extra"]


class TestAListIsMatchedByPosition:
    def test_an_item_is_held_to_the_label_of_the_row_it_is_the_place_of_and_the_score_is_the_part_that_matched(
        self,
    ) -> None:
        labels = labels_of(["T", "B", "T", "NK"])

        found = scoring.score(whole(["T", "B", "B", "NK"]), labels, TOLERANCE)

        assert scored(found) == ("position", 3, 4, 0, 0)
        assert found["score"] == 0.75 and found["rank"] is None
        assert found["examples"] == ["row 3: the label is 'T' and it gave 'B'"]

    def test_a_row_that_has_no_answer_has_no_label_and_what_a_method_gave_for_it_is_not_held_to_anything(self) -> None:
        labels = labels_of(["T", None, "B"])

        found = scoring.score(whole(["T", "anything", "X"]), labels, TOLERANCE)

        assert scored(found) == ("position", 1, 2, 0, 0)
        assert found["score"] == 0.5

    def test_the_denominator_is_the_number_of_labels_and_is_the_same_for_every_method(self) -> None:
        labels = labels_of(["a", None, "b", None, "c"])

        first = scoring.score(whole(["a", "", "b", "", "c"]), labels, TOLERANCE)
        second = scoring.score(whole(["a", "x", "x", "x", "x"]), labels, TOLERANCE)

        assert (first["of"], second["of"]) == (3, 3)
        assert (first["matched"], second["matched"]) == (3, 1)

    def test_a_list_longer_or_shorter_than_the_file_is_not_scored_since_which_item_is_of_which_row_is_not_known(
        self,
    ) -> None:
        labels = labels_of(["a", "b", "c"])

        for items in (["a", "b"], ["a", "b", "c", "d"], []):
            found = scoring.score(whole(items), labels, TOLERANCE)
            assert found["scored"] is False and found["why"] == "length", items
            assert f"{len(items)} items" in found["reason"] and "3 rows" in found["reason"]
            assert found["matched"] is None and found["score"] is None and found["rank"] is None

    def test_the_length_to_be_held_is_the_rows_of_the_file_and_not_the_rows_that_have_an_answer(self) -> None:
        labels = labels_of(["a", None, "c"])

        assert scoring.score(whole(["a", "c"]), labels, TOLERANCE)["why"] == "length"

    def test_a_list_with_nothing_in_it_that_could_be_an_answer_is_not_scored(self) -> None:
        labels = labels_of(["a", "b"])

        for items in ([None, None], [[1], [2]], [{"a": 1}, {"b": 2}]):
            found = scoring.score(whole(items), labels, TOLERANCE)
            assert found["scored"] is False and found["why"] == "not_values", items

    def test_items_that_are_not_answers_in_a_list_that_has_some_are_wrong(self) -> None:
        labels = labels_of(["a", "b", "c"])

        found = scoring.score(whole(["a", None, [1]]), labels, TOLERANCE)

        assert scored(found) == ("position", 1, 3, 0, 0)
        assert found["examples"] == [
            "row 2: the label is 'b' and it gave None",
            "row 3: the label is 'c' and it gave [1]",
        ]

    def test_no_more_than_a_few_places_where_it_differs_are_listed(self) -> None:
        labels = labels_of(["a"] * 20)

        found = scoring.score(whole(["b"] * 20), labels, TOLERANCE)

        assert found["matched"] == 0 and len(found["examples"]) == scoring.MAX_EXAMPLES
        assert found["examples"][0].startswith("row 1:") and found["examples"][-1].startswith("row 5:")

    def test_a_label_that_is_long_is_not_listed_in_full(self) -> None:
        labels = labels_of(["x" * 1000])

        [example] = scoring.score(whole(["y"]), labels, TOLERANCE)["examples"]

        assert len(example) < 400 and "..." in example


class TestAnObjectIsMatchedByWhatEachRowIsTheAnswerTo:
    def test_an_item_is_held_to_the_label_of_the_row_that_it_is_the_answer_to_whatever_order_it_is_in(self) -> None:
        labels = labels_of(["T", "B", "NK"], ids=["c1", "c2", "c3"])

        found = scoring.score(whole({"c3": "NK", "c1": "T", "c2": "T"}), labels, TOLERANCE)

        assert scored(found) == ("id", 2, 3, 0, 0)
        assert found["examples"] == ["'c2': the label is 'B' and it gave 'T'"]

    def test_a_row_that_it_gave_nothing_for_is_wrong_and_is_counted_as_missing(self) -> None:
        labels = labels_of(["T", "B", "NK"], ids=["c1", "c2", "c3"])

        found = scoring.score(whole({"c1": "T"}), labels, TOLERANCE)

        assert scored(found) == ("id", 1, 3, 2, 0)
        assert found["score"] == pytest.approx(1 / 3)
        assert found["examples"] == [
            "'c2': the label is 'B' and it gave nothing",
            "'c3': the label is 'NK' and it gave nothing",
        ]

    def test_an_item_for_what_is_not_a_row_with_an_answer_is_counted_as_extra_and_is_not_a_reward_or_a_penalty(
        self,
    ) -> None:
        labels = labels_of(["T", None, "NK"], ids=["c1", "c2", "c3"])

        found = scoring.score(whole({"c1": "T", "c3": "NK", "c9": "T", "c2": "whatever"}), labels, TOLERANCE)

        assert scored(found) == ("id", 2, 2, 0, 1)
        assert found["score"] == 1.0

    def test_a_row_that_has_no_label_but_has_a_name_is_not_extra(self) -> None:
        labels = labels_of(["T", None], ids=["c1", "c2"])

        found = scoring.score(whole({"c1": "T", "c2": "x"}), labels, TOLERANCE)

        assert found["extra"] == 0

    def test_it_needs_the_column_that_says_what_each_row_is_the_answer_to(self) -> None:
        labels = labels_of(["T", "B"])

        found = scoring.score(whole({"c1": "T", "c2": "B"}), labels, TOLERANCE)

        assert found["scored"] is False and found["why"] == "no_id_column"
        assert "no column of what each row is the answer to" in found["reason"]

    def test_a_name_that_two_rows_with_answers_have_cannot_be_matched_and_is_not_guessed(self) -> None:
        labels = labels_of(["T", "B", "NK"], ids=["c1", "c1", "c3"])

        found = scoring.score(whole({"c1": "T", "c3": "NK"}), labels, TOLERANCE)

        assert found["scored"] is False and found["why"] == "ids_unusable"
        assert "'c1'" in found["reason"] and "more than one row" in found["reason"]

    def test_the_name_said_to_be_repeated_is_the_first_of_the_rows_that_is_and_not_the_first_to_be_seen_twice(
        self,
    ) -> None:
        labels = labels_of(["T", "B", "B", "T"], ids=["c1", "c2", "c2", "c1"])

        found = scoring.score(whole({"c1": "T"}), labels, TOLERANCE)

        assert found["why"] == "ids_unusable" and "'c1'" in found["reason"]

    def test_a_file_of_many_rows_that_has_a_name_twice_at_its_end_is_not_slow_to_say_so(self) -> None:
        count = 60_000
        names = [f"c{number}" for number in range(count - 1)] + ["c0"]
        labels = labels_of(["T"] * count, ids=names)

        started = time.monotonic()
        found = scoring.score(whole({"c1": "T"}), labels, TOLERANCE)

        assert found["why"] == "ids_unusable" and "'c0'" in found["reason"]
        assert time.monotonic() - started < 2

    def test_a_name_that_is_repeated_only_by_a_row_that_has_no_answer_is_no_matter(self) -> None:
        labels = labels_of(["T", None, "NK"], ids=["c1", "c1", "c3"])

        found = scoring.score(whole({"c1": "T", "c3": "NK"}), labels, TOLERANCE)

        assert scored(found) == ("id", 2, 2, 0, 0)

    def test_a_row_that_has_an_answer_and_no_name_cannot_be_matched(self) -> None:
        labels = labels_of(["T", "B"], ids=["c1", None])

        found = scoring.score(whole({"c1": "T"}), labels, TOLERANCE)

        assert (
            found["scored"] is False and found["why"] == "ids_unusable" and "nothing in the column" in found["reason"]
        )

    def test_a_row_that_has_no_name_and_no_answer_is_no_matter(self) -> None:
        labels = labels_of(["T", None], ids=["c1", None])

        assert scored(scoring.score(whole({"c1": "T"}), labels, TOLERANCE)) == ("id", 1, 1, 0, 0)

    def test_an_object_that_has_no_name_that_the_file_has_is_not_scored_rather_than_scored_nothing(self) -> None:
        labels = labels_of(["T", "B"], ids=["c1", "c2"])

        found = scoring.score(whole({"x": "T", "y": "B"}), labels, TOLERANCE)

        assert found["scored"] is False and found["why"] == "none_in_common" and "'cell'" in found["reason"]

    def test_an_object_with_nothing_in_it_that_could_be_an_answer_is_not_scored(self) -> None:
        labels = labels_of(["T", "B"], ids=["c1", "c2"])

        found = scoring.score(whole({"c1": [1], "c2": None}), labels, TOLERANCE)

        assert found["scored"] is False and found["why"] == "not_values"

    def test_the_names_are_text_so_a_number_is_held_to_what_is_written_in_the_file(self) -> None:
        labels = labels_of(["T", "B"], ids=["1", "2"])

        assert scored(scoring.score(whole({"1": "T", "2": "B"}), labels, TOLERANCE)) == ("id", 2, 2, 0, 0)


class TestWhatMatchesALabel:
    @pytest.mark.parametrize(
        ("item", "label", "same"),
        [
            ("T", "T", True),
            ("T", "t", False),
            ("T ", "T", False),
            (" T", "T", False),
            ("T cell", "T  cell", False),
            ("1", "1", True),
            ("1.0", "1", False),
            (1, "1", True),
            (1, "1.0", True),
            (1.0, "1", True),
            (1.5, "1.5", True),
            (1.5, "1.6", False),
            (2, "1", False),
            (1, "one", False),
            (1, "1e0", True),
            (1, "0x1", False),
            (1, "nan", False),
            (1, "", False),
            (float("nan"), "nan", False),
            (True, "true", True),
            (True, "True", True),
            (False, "FALSE", True),
            (True, "false", False),
            (True, "1", False),
            (False, "0", False),
            (True, "yes", False),
            (1, "true", False),
            ("true", "true", True),
            ("True", "true", False),
            (None, "None", False),
            (None, "", False),
            ([1], "[1]", False),
            ({"a": 1}, "a", False),
        ],
    )
    def test_text_is_the_same_text_a_number_is_a_number_that_the_label_is_and_a_truth_is_true_or_false(
        self, item: Any, label: str, same: bool
    ) -> None:
        assert scoring.is_match(item, label, TOLERANCE) is same

    def test_a_number_is_the_same_within_the_tolerance_that_is_given(self) -> None:
        assert scoring.is_match(1.05, "1", LOOSE) is True
        assert scoring.is_match(1.05, "1", TOLERANCE) is False
        assert scoring.is_match(1.0000000001, "1", TOLERANCE) is True
        assert scoring.is_match(1.2, "1", LOOSE) is False

    def test_whole_numbers_are_the_same_only_if_equal_whatever_the_tolerance(self) -> None:
        assert scoring.is_match(10, "11", LOOSE) is False
        assert scoring.is_match(10, "10", LOOSE) is True

    @pytest.mark.parametrize(
        ("label", "number"),
        [
            ("5", 5),
            ("-5", -5),
            ("+5", 5),
            ("5.5", 5.5),
            ("1e3", 1000.0),
            (".5", 0.5),
            ("5.", 5.0),
            ("1" * 400, int("1" * 400)),
        ],
    )
    def test_a_label_that_is_written_as_a_number_in_the_plain_way_is_read_as_one(self, label: str, number: Any) -> None:
        assert scoring.number_of(label) == number

    @pytest.mark.parametrize("label", ["", "five", "1,5", "1 5", "0x10", "nan", "inf", "Infinity", "1_000", "--5", "٣"])
    def test_and_what_a_reader_that_is_more_generous_would_take_for_a_number_is_not_one(self, label: str) -> None:
        assert scoring.number_of(label) is None

    def test_a_label_of_more_digits_than_a_whole_number_can_be_read_from_is_not_a_number_and_is_not_a_crash(
        self,
    ) -> None:
        label = "1" * 5000

        assert scoring.number_of(label) is None
        assert scoring.is_match(1, label, TOLERANCE) is False

    def test_a_label_that_is_a_number_too_big_to_be_a_float_is_the_same_only_as_a_number_equal_to_it(self) -> None:
        huge = "1" + "0" * 400

        assert scoring.is_match(int(huge), huge, TOLERANCE) is True
        assert scoring.is_match(1.0, huge, TOLERANCE) is False
        assert scoring.is_match(int(huge) + 1, huge, TOLERANCE) is False


class TestWhatIsKeptOfAnAnswer:
    def test_a_one_dimensional_look_that_has_all_its_values_is_held_to_the_labels_as_a_list_is(self) -> None:
        labels = labels_of(["a", "b"])

        found = scoring.score(look(["a", "c"], [2]), labels, TOLERANCE)

        assert scored(found) == ("position", 1, 2, 0, 0)

    def test_a_series_that_was_kept_as_its_values_is_held_to_them(self) -> None:
        labels = labels_of(["1", "2", "3"])

        assert scored(scoring.score(look([1.0, 2.0, 4.0], [3]), labels, TOLERANCE)) == ("position", 2, 3, 0, 0)

    def test_a_table_or_an_array_of_more_than_one_dimension_is_not_one_answer_for_each_row(self) -> None:
        labels = labels_of(["a", "b"])

        for shape in ([2, 2], [2, 1], [1, 2], [2, 2, 2]):
            found = scoring.score(look([["a", "b"], ["c", "d"]], shape), labels, TOLERANCE)
            assert found["scored"] is False and found["why"] == "not_kept", shape
            assert "more than one dimension" in found["reason"]

    def test_a_table_that_was_kept_as_its_columns_is_not_held_to_the_labels(self) -> None:
        labels = labels_of(["a", "b"])

        found = scoring.score(look({"x": [1, 2]}, [2, 1]), labels, TOLERANCE)

        assert found["scored"] is False and found["why"] == "not_kept"

    def test_a_look_that_is_not_all_of_the_answer_is_not_held_to_the_labels(self) -> None:
        labels = labels_of(["a", "b"])

        found = scoring.score({"type": "list", "plain": False, "repr": "[array([1, 2])]"}, labels, TOLERANCE)

        assert found["scored"] is False and found["why"] == "not_kept" and "only a look" in found["reason"].lower()

    def test_a_one_dimensional_look_that_has_no_values_is_not_held_to_the_labels(self) -> None:
        labels = labels_of(["a", "b"])
        big = {"type": "ndarray", "repr": "array(...)", "shape": [2], "dtype": "str", "note": "A look."}

        found = scoring.score(big, labels, TOLERANCE)

        assert found["scored"] is False and found["why"] == "not_kept"

    def test_a_look_without_a_shape_is_not_taken_for_a_list(self) -> None:
        labels = labels_of(["a", "b"])

        found = scoring.score(
            {"type": "Series", "repr": "...", "values": ["a", "b"], "note": "A look."}, labels, TOLERANCE
        )

        assert found["scored"] is False and found["why"] == "not_kept"

    def test_an_answer_of_which_only_a_hash_was_kept_is_not_held_to_the_labels(self) -> None:
        labels = labels_of(["a", "b"])

        found = scoring.score(
            {"type": "list", "chars": 900_000, "sha256": "f" * 64, "note": "Too big."}, labels, TOLERANCE
        )

        assert found["scored"] is False and found["why"] == "not_kept" and "hash" in found["reason"]

    @pytest.mark.parametrize("value", ["T", 3, 2.5, True, None])
    def test_an_answer_that_is_one_value_is_not_a_list_or_an_object(self, value: Any) -> None:
        found = scoring.score(whole(value), labels_of(["a"]), TOLERANCE)

        assert found["scored"] is False and found["why"] == "not_a_list_or_object"
        assert repr(value) in found["reason"]

    def test_a_number_that_could_not_be_written_in_the_record_is_not_an_object_of_answers(self) -> None:
        labels = labels_of(["nan", "1"], ids=["$float", "c"])

        found = scoring.score(whole({"$float": "nan"}), labels, TOLERANCE)

        assert found["scored"] is False and found["why"] == "not_a_list_or_object"

    def test_an_empty_answer_is_not_scored_as_a_method_that_got_everything_wrong(self) -> None:
        labels = labels_of(["a", "b"], ids=["c1", "c2"])

        assert scoring.score(whole({}), labels, TOLERANCE)["why"] == "none_in_common"
        assert scoring.score(whole([]), labels, TOLERANCE)["why"] == "length"


class TestRanking:
    def ranked(self, **matched: int | None) -> dict[str, int]:
        return scoring.ranks(
            {
                name: scoring.unscored("no_answer", "x")
                if count is None
                else scoring.scored("position", count, 10, 0, 0, [])
                for name, count in matched.items()
            }
        )

    def test_the_most_labels_matched_is_first(self) -> None:
        assert self.ranked(a=3, b=9, c=5) == {"a": 3, "b": 1, "c": 2}

    def test_methods_that_matched_the_same_number_share_a_rank_and_the_next_rank_is_after_them_all(self) -> None:
        assert self.ranked(a=9, b=9, c=5, d=2, e=2, f=2, g=0) == {
            "a": 1,
            "b": 1,
            "c": 3,
            "d": 4,
            "e": 4,
            "f": 4,
            "g": 7,
        }

    def test_a_method_that_was_not_scored_has_no_rank_and_does_not_take_one_from_the_others(self) -> None:
        assert self.ranked(a=None, b=0, c=None) == {"b": 1}

    def test_a_method_that_matched_none_is_ranked_and_is_not_the_same_as_one_that_was_not_scored(self) -> None:
        assert self.ranked(a=0, b=None) == {"a": 1}

    def test_nothing_scored_ranks_nothing(self) -> None:
        assert self.ranked(a=None, b=None) == {} and self.ranked() == {}

    def test_one_method_that_was_scored_is_first_alone(self) -> None:
        assert self.ranked(only=4) == {"only": 1}
