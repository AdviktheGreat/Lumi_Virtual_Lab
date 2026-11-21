"""The file of right answers that a person may point a bake-off to: which columns it has, and what it says row by row.

The person may say that a table of theirs, on the Data page, holds the right answers for the data that the methods are
run on: a column that has the answer for each row, and, if the rows are not in the order that the methods give their
answers in, a column that says what each is the answer to. When the bake-off is made, or said again, only the first line
of such a file is read, to say whether the columns the person named are in it. When the methods are held to the answers,
the whole of it is read, a row at a time, as text: a cell is what is written in it, without the space round it, and an
empty cell is a row that has no answer, which is not one that has an answer of nothing.

The names of columns are taken as they are in the file, without the space round them, and a name that two columns have
is not taken, as it would be a guess which was meant. Whether a method is right is something that only the person's
answers can say, and only where they are the person's to give: nothing here checks them.
"""

import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import PurePath

from virtual_lab.tables import decode, skip_preamble

# What a file of right answers may be, by its ending, with what separates its fields. A file is not sniffed: the person
# says which columns, and a guess at what separates them would be the first of many guesses about what they meant.
SUFFIXES = {".csv": ",", ".tsv": "\t"}
# The most bytes that a file of right answers may have, and of its start that are read to find its columns
MAX_BYTES = 16 << 20
MAX_HEADER_BYTES = 256 << 10
# The most characters in the name of a column, and of the names of the columns that are listed to say which there are
MAX_COLUMN_CHARS = 200
MAX_LISTED = 10
# The most rows that a file of right answers may have: an answer that is kept whole is of at most 400,000 characters,
# which is at most this many items, so a file with more cannot be held to one
MAX_ROWS = 200_000


class LabelsError(ValueError):
    """Why a file cannot be the right answers that the person said, in words for them."""


@dataclass(frozen=True)
class Labels:
    """What a file of right answers says, row by row, in the order of the file. A row is a line with something in it:
    a blank line is not one.

    :param column: The name of the column of the answers.
    :param id_column: The name of the column of what each is the answer to, if there is one.
    :param answers: The answer of each row, as the text of its cell, or None for a row whose cell is empty.
    :param ids: What each row is the answer to, as the text of its cell, or None for a row whose cell is empty. None
        if there is no such column.
    :param sha256: A hash of the file as it was read, to say which file the answers were of.
    :param size: How many bytes it has.
    """

    column: str
    id_column: str | None
    answers: tuple[str | None, ...]
    ids: tuple[str | None, ...] | None
    sha256: str
    size: int

    @property
    def labelled(self) -> int:
        """How many rows have an answer, which is the number of labels."""
        return sum(1 for answer in self.answers if answer is not None)


def delimiter_of(name: str) -> str | None:
    """What separates the fields of a file by the ending of its name, or None if it is not a kind that is read."""
    return SUFFIXES.get(PurePath(name).suffix.lower())


def header_of(start: bytes, whole: bool, delimiter: str) -> list[str]:
    """The names of the columns of a file, from the start of it.

    :param start: The first bytes of the file.
    :param whole: Whether that is all of the file.
    :raises LabelsError: If it is not text, has no first line in what was read, or is nothing but comments and blanks.
    """
    if b"\x00" in start:
        raise LabelsError("The file is not text, so it has no columns to name")
    if not whole:
        ended = max(start.rfind(b"\n"), start.rfind(b"\r"))
        if ended < 0:
            raise LabelsError(
                f"The first {MAX_HEADER_BYTES:,} bytes of the file have no end of a line in them, so there is no "
                "row of column names to read"
            )
        start = start[: ended + 1]
    try:
        text, _, _ = decode(start)
    except UnicodeDecodeError:
        raise LabelsError("The file is not text that can be read, so it has no columns to name") from None
    text, _ = skip_preamble(text)
    try:
        for row in csv.reader(io.StringIO(text), delimiter=delimiter):
            if any(cell.strip() for cell in row):
                return [cell.strip() for cell in row]
    except csv.Error as problem:
        raise LabelsError(f"The first line of the file could not be read as a row of a table: {problem}") from None

    raise LabelsError("The file has nothing in it but comments and blank lines, so it has no columns to name")


def listed(header: list[str]) -> str:
    """The names of some of the columns, for saying which there are."""
    shown = ", ".join(repr(name) for name in header[:MAX_LISTED])
    more = len(header) - MAX_LISTED

    return f"{shown}, and {more:,} more" if more > 0 else shown


def check_columns(header: list[str], column: str, id_column: str | None) -> None:
    """
    :param header: The names of the columns of the file.
    :param column: The column that has the right answers.
    :param id_column: The column that says what each is the answer to, if the person said.
    :raises LabelsError: If a column that was named is not there, or is the name of more than one, or the two that were
        named are the same.
    """
    for name in (column, id_column):
        if name is None:
            continue
        found = header.count(name)
        if found == 0:
            raise LabelsError(f"There is no column called {name!r} in the file, which has {listed(header)}")
        if found > 1:
            raise LabelsError(f"{found} columns of the file are called {name!r}, so it is not known which is meant")
    if id_column is not None and id_column == column:
        raise LabelsError(
            f"{column!r} cannot be both the column of the right answers and the column of what each is the answer to"
        )


def check(name: str, size: int, start: bytes, column: str, id_column: str | None) -> list[str]:
    """Whether a file can be the right answers that were said of it, by what it is called, how big it is, and its first
    line.

    :param name: What the file is called on the Data page.
    :param size: How many bytes it has.
    :param start: Its first bytes, up to MAX_HEADER_BYTES of them.
    :return: The names of its columns.
    :raises LabelsError: If it is not a file of a kind that is read, is too big, or does not have the columns.
    """
    delimiter = delimiter_of(name)
    if delimiter is None:
        raise LabelsError(f"{name!r} is not a .csv or a .tsv file, which are what right answers are read from")
    if size > MAX_BYTES:
        raise LabelsError(
            f"{name!r} has {size:,} bytes, and right answers are read from files of at most {MAX_BYTES:,}"
        )
    header = header_of(start, size <= len(start), delimiter)
    check_columns(header, column, id_column)

    return header


def read_labels(name: str, raw: bytes, column: str, id_column: str | None) -> Labels:
    """What a file says, row by row.

    :param name: What the file is called on the Data page.
    :param raw: All of the file.
    :raises LabelsError: If it is not a file of a kind that is read, is too big, is not text, does not have the columns,
        has more rows than an answer can be kept whole for, or has no row with an answer.
    """
    delimiter = delimiter_of(name)
    if delimiter is None:
        raise LabelsError(f"{name!r} is not a .csv or a .tsv file, which are what right answers are read from")
    if len(raw) > MAX_BYTES:
        raise LabelsError(
            f"{name!r} has more than {MAX_BYTES:,} bytes, and right answers are read from files of at most that"
        )
    if b"\x00" in raw:
        raise LabelsError("The file is not text, so it has no answers to read")
    try:
        text, _, _ = decode(raw)
    except UnicodeDecodeError:
        raise LabelsError("The file is not text that can be read, so it has no answers to read") from None
    text, _ = skip_preamble(text)
    header: list[str] | None = None
    answers: list[str | None] = []
    ids: list[str | None] = []
    where = (0, 0)
    try:
        for row in csv.reader(io.StringIO(text), delimiter=delimiter):
            if not any(cell.strip() for cell in row):
                continue
            if header is None:
                header = [cell.strip() for cell in row]
                check_columns(header, column, id_column)
                where = (header.index(column), header.index(id_column) if id_column is not None else 0)
                continue
            if len(answers) >= MAX_ROWS:
                raise LabelsError(
                    f"The file has more than {MAX_ROWS:,} rows, which is more than an answer can be kept whole for"
                )
            answers.append(cell_of(row, where[0]))
            if id_column is not None:
                ids.append(cell_of(row, where[1]))
    except csv.Error as problem:
        raise LabelsError(f"The file could not be read as a table: {problem}") from None
    if header is None:
        raise LabelsError("The file has nothing in it but comments and blank lines, so it has no answers to read")
    if all(answer is None for answer in answers):
        raise LabelsError(
            f"No row of the file has an answer in the column {column!r}, so there is nothing to hold a method to"
        )

    return Labels(
        column=column,
        id_column=id_column,
        answers=tuple(answers),
        ids=tuple(ids) if id_column is not None else None,
        sha256=hashlib.sha256(raw).hexdigest(),
        size=len(raw),
    )


def cell_of(row: list[str], position: int) -> str | None:
    """What is in a cell of a row, without the space round it, or None if there is nothing, as a row that stops short
    has no cell where the header has a column."""
    text = row[position].strip() if position < len(row) else ""

    return text or None
