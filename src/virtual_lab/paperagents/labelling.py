"""The file of right answers that a person may point a bake-off to, as far as it is read before any method is run: which
columns it has.

The person may say that a table of theirs, on the Data page, holds the right answers for the data that the methods are
run on: a column that has the answer for each row, and, if the rows are not in the order that the methods give their
answers in, a column that says what each is the answer to. What is read here is the first line of such a file, to say
whether the columns the person named are in it. No answer is read, and nothing is decided about a method: whether a
method is right is a thing that only the person's answers can say, and only where they are the person's to give.

The names of columns are taken as they are in the file, without the space round them, and a name that two columns have
is not taken, as it would be a guess which was meant.
"""

import csv
import io
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


class LabelsError(ValueError):
    """Why a file cannot be the right answers that the person said, in words for them."""


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
