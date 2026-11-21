"""Tests of reading the first line of a file of right answers, to say whether the columns that the person named are in
it: what kind of file is read, how its header is found, and what is said when it cannot be or a column is not there."""

from typing import Any

import pytest

from virtual_lab.paperagents import labelling
from virtual_lab.paperagents.labelling import LabelsError


def refused(call: Any, *args: Any) -> str:
    with pytest.raises(LabelsError) as caught:
        call(*args)

    return str(caught.value)


class TestKinds:
    @pytest.mark.parametrize(
        ("name", "delimiter"),
        [("a.csv", ","), ("a.tsv", "\t"), ("A.CSV", ","), ("b.Tsv", "\t"), ("x.y.csv", ",")],
    )
    def test_a_csv_is_split_at_commas_and_a_tsv_at_tabs_by_what_it_is_called(self, name: str, delimiter: str) -> None:
        assert labelling.delimiter_of(name) == delimiter

    @pytest.mark.parametrize("name", ["a.txt", "a", "csv", "a.csv.gz", "a.xlsx", ".csv", "a.tab", ""])
    def test_no_other_kind_of_file_is_read(self, name: str) -> None:
        assert labelling.delimiter_of(name) is None


class TestHeader:
    def test_the_names_are_the_first_row_without_the_space_round_them(self) -> None:
        assert labelling.header_of(b" cell , type ,id\nx,y,z\n", True, ",") == ["cell", "type", "id"]

    def test_a_tab_separated_file_is_read_at_tabs(self) -> None:
        assert labelling.header_of(b"cell\ttype, a\n1\t2\n", True, "\t") == ["cell", "type, a"]

    def test_a_name_in_quotes_may_have_the_delimiter_in_it(self) -> None:
        assert labelling.header_of(b'"a,b",c\n1,2\n', True, ",") == ["a,b", "c"]

    def test_a_byte_order_mark_is_not_part_of_the_first_name(self) -> None:
        assert labelling.header_of(b"\xef\xbb\xbfcell,type\n", True, ",") == ["cell", "type"]

    def test_commented_and_blank_lines_above_the_names_are_skipped(self) -> None:
        assert labelling.header_of(b"# made by a pipeline\n# on a Monday\n\n  ,\ncell,type\n", True, ",") == [
            "cell",
            "type",
        ]

    def test_a_file_that_is_not_utf8_is_read_as_windows_text(self) -> None:
        assert labelling.header_of("cellule,type\n".replace("e", "\xe9", 1).encode("cp1252"), True, ",") == [
            "c\xe9llule",
            "type",
        ]

    def test_a_file_with_one_line_and_no_line_ending_has_that_line_for_names(self) -> None:
        assert labelling.header_of(b"cell,type", True, ",") == ["cell", "type"]

    def test_a_file_whose_start_only_was_read_is_cut_back_to_a_whole_line(self) -> None:
        # The second line is cut in the middle of a character of two bytes, which would make the start not UTF-8
        start = "a,b\n".encode() + "é".encode()[:1]

        assert labelling.header_of(start, False, ",") == ["a", "b"]
        assert refused(labelling.header_of, "é".encode() * 10, False, ",").startswith(
            f"The first {labelling.MAX_HEADER_BYTES:,} bytes"
        )

    def test_a_blank_first_line_with_the_rest_not_read_is_a_file_with_no_names_and_not_one_with_a_long_line(
        self,
    ) -> None:
        assert "nothing in it" in refused(labelling.header_of, b"\n" + b"x" * 10, False, ",")

    def test_a_line_that_ends_with_a_carriage_return_alone_is_an_end_of_a_line(self) -> None:
        assert labelling.header_of(b"a,b\rc,d", False, ",") == ["a", "b"]

    @pytest.mark.parametrize(
        ("start", "words"),
        [
            (b"a,b\x00c\n", "not text"),
            (b"", "nothing in it"),
            (b"# one\n# two\n", "nothing in it"),
            (b"\n\n  \n", "nothing in it"),
            (b"caf\x81,b\n", "not text that can be read"),
            (b"a," + b"x" * 200_000 + b"\n", "could not be read"),
        ],
    )
    def test_what_has_no_names_in_it_is_refused_and_said_why(self, start: bytes, words: str) -> None:
        assert words in refused(labelling.header_of, start, True, ",")


class TestColumns:
    HEADER = ["id", "label", "score"]

    def test_columns_that_are_in_the_header_are_accepted(self) -> None:
        labelling.check_columns(self.HEADER, "label", None)
        labelling.check_columns(self.HEADER, "label", "id")

    def test_a_column_that_is_not_there_is_said_with_the_columns_that_are(self) -> None:
        assert refused(labelling.check_columns, self.HEADER, "truth", None) == (
            "There is no column called 'truth' in the file, which has 'id', 'label', 'score'"
        )
        assert refused(labelling.check_columns, self.HEADER, "label", "name").startswith(
            "There is no column called 'name'"
        )

    def test_names_are_looked_for_as_they_are_written(self) -> None:
        assert "There is no column called 'Label'" in refused(labelling.check_columns, self.HEADER, "Label", None)

    def test_only_some_of_a_long_header_is_listed(self) -> None:
        header = [f"c{number}" for number in range(25)]

        message = refused(labelling.check_columns, header, "truth", None)

        assert "'c9'" in message and "'c10'" not in message and message.endswith("and 15 more")

    def test_the_most_that_is_listed_are_not_followed_by_a_count_of_none_more(self) -> None:
        header = [f"c{number}" for number in range(labelling.MAX_LISTED)]

        message = refused(labelling.check_columns, header, "truth", None)

        assert message.endswith("'c9'") and "more" not in message

    def test_a_name_that_two_columns_have_is_not_guessed_at(self) -> None:
        assert refused(labelling.check_columns, ["a", "b", "a"], "a", None) == (
            "2 columns of the file are called 'a', so it is not known which is meant"
        )
        assert refused(labelling.check_columns, ["a", "b", "b"], "a", "b").startswith("2 columns")

    def test_the_answers_and_what_they_are_the_answers_to_are_not_one_column(self) -> None:
        assert "cannot be both" in refused(labelling.check_columns, self.HEADER, "label", "label")


class TestCheck:
    def test_a_file_that_has_the_columns_gives_its_header(self) -> None:
        text = b"id,label\n1,a\n"

        assert labelling.check("truth.csv", len(text), text, "label", "id") == ["id", "label"]

    def test_a_file_that_is_not_a_csv_or_a_tsv_is_refused_by_its_name_before_it_is_read(self) -> None:
        assert "not a .csv or a .tsv" in refused(labelling.check, "truth.xlsx", 10, b"id,label\n", "label", None)

    def test_a_file_that_is_too_big_is_refused_and_one_of_the_most_is_not(self) -> None:
        start = b"id,label\n"

        assert "has 16,777,217 bytes" in refused(
            labelling.check, "t.csv", labelling.MAX_BYTES + 1, start, "label", None
        )
        assert labelling.check("t.csv", labelling.MAX_BYTES, start, "label", None) == ["id", "label"]

    def test_a_file_that_is_all_there_is_has_its_last_line_for_names_whether_or_not_it_ends_in_a_line_ending(
        self,
    ) -> None:
        assert labelling.check("t.csv", 8, b"id,label", "label", None) == ["id", "label"]
        assert labelling.check("t.csv", 9, b"id,label\n", "label", None) == ["id", "label"]

    def test_a_file_bigger_than_what_is_read_of_it_is_not_taken_for_all_of_it(self) -> None:
        start = b"id,label\n1,a\n" + b"2,b"

        assert labelling.check("t.csv", 5_000_000, start, "label", "id") == ["id", "label"]
        assert "no end of a line" in refused(labelling.check, "t.csv", 5_000_000, b"id,label", "label", None)

    def test_a_column_that_is_not_there_is_refused(self) -> None:
        assert "There is no column called 'truth'" in refused(labelling.check, "t.csv", 9, b"id,label\n", "truth", None)
