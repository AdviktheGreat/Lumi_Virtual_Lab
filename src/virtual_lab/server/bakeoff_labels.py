"""Where the right answers of a bake-off are, which is the person's to say.

The person may say that a table on the Data page has the right answers for the data that the methods are run on: the
column that has the answer for each row, and, if the rows are not in the order of the data, the column that says what
each is the answer to (paperagents/labelling.py). What is kept is those names, and the table stays where the Data page
has it and is read from there each time, so that the answers are what the file has now and not what it had when it was
named. It is not copied, and it is not given to any method, which is run on the data of the bake-off and nothing else.
A method is able to read the answers if the person named the same file as the data, or the data is a folder that has the
file in it, which is said where it is shown.

That the answers are right is the person's word. Nothing here checks them against anything, and nothing that is scored
by them is called right without saying that it is by them.
"""

from collections.abc import Mapping
from typing import Any

from virtual_lab.paperagents import labelling
from virtual_lab.server.errors import ApiError
from virtual_lab.server.own import location, overlaps
from virtual_lab.server.paperagents import PaperAgents, is_blank
from virtual_lab.server.workspace import has_control_character

FIELDS = ("own", "column", "id_column")
SAYING = (
    "The right answers are the person's word: nothing here checks them. The file stays where the Data page has it, and "
    "is read from there each time, so they are what it has now."
)
ALSO_THE_DATA = (
    " It is also the data that the methods are run on, or is in it, so a method is able to read the answers that it is "
    "to be scored by."
)


def name_of(said: Mapping[str, Any], key: str, what: str, most: int | None = None) -> str | None:
    """A name that was said, as it is looked for, or None if it was not said. The name of a piece of data is as it was
    said, and the name of a column is without the space round it, as a header is read.

    :param most: The most characters that the name may have, if there is a most.
    :raises ApiError: If it is not text, or has what is not text in it, or is too long.
    """
    value = said.get(key)
    if is_blank(value):
        return None
    if not isinstance(value, str) or has_control_character(value) or (most is not None and len(value.strip()) > most):
        raise ApiError(422, "invalid", f"{what} is text with no control character in it, not {str(value)[:60]!r}")

    return value if most is None else value.strip()


def look(paperagents: PaperAgents, own: str, column: str, id_column: str | None) -> tuple[str, str] | None:
    """What stands in the way of the table being the right answers that were said of it, by the file as it is now.

    :return: None if nothing does. If something does: a short name for it that a page can go by, and what it is in
        words.
    """
    entry = paperagents.workspace.load_own()["data"].get(own)
    if entry is None:
        return "unknown_data", f"There is no data called {own[:80]!r} on the Data page"
    path = location(paperagents.workspace, own, entry)
    try:
        if path.is_dir():
            return "invalid", f"{own!r} is a folder, and right answers are read from one file"
        if not path.is_file():
            return "missing_data", f"The data called {own!r} is not where the Data page says it is"
        with path.open("rb") as file:
            size = path.stat().st_size
            start = file.read(labelling.MAX_HEADER_BYTES)
    except OSError:
        return "missing_data", f"The data called {own!r} could not be read from where the Data page says it is"
    try:
        labelling.check(own, size, start, column, id_column)
    except labelling.LabelsError as error:
        return "invalid", str(error)

    return None


def check_labels(paperagents: PaperAgents, said: Any) -> dict[str, Any] | None:
    """Where the person says the right answers are, as it is kept, or None if they say that there are none.

    :param said: The file on the Data page that has them (own), the column that has the answer for each row (column),
        and, if the rows are not in the order of the data, the column that says what each is the answer to (id_column).
        What is left out, or is nothing but space, is not said, and saying none of it says that there are none.
    :raises ApiError: If it is not that, only some of what is needed is said, the file is not there or is not a .csv or
        a .tsv, or the columns are not in it.
    """
    if not isinstance(said, Mapping):
        raise ApiError(
            422,
            "invalid",
            "The right answers are said by the file on the Data page that has them, the column that has the answer for "
            "each row, and, if the rows are not in the order of the data, the column that says what each is the "
            "answer to",
        )
    unknown = [str(key)[:40] for key in said if key not in FIELDS]
    if unknown:
        raise ApiError(422, "invalid", f"{', '.join(unknown[:3])} is not something that is said of the right answers")
    own = name_of(said, "own", "The name of the file of right answers")
    column = name_of(said, "column", "The name of the column of right answers", labelling.MAX_COLUMN_CHARS)
    id_column = name_of(
        said, "id_column", "The name of the column of what each is the answer to", labelling.MAX_COLUMN_CHARS
    )
    if own is None and column is None and id_column is None:
        return None
    if own is None:
        raise ApiError(422, "invalid", "Say which file on the Data page has the right answers")
    if column is None:
        raise ApiError(422, "invalid", "Say which column of the file has the right answer for each row")
    if id_column is not None and id_column == column:
        raise ApiError(
            422,
            "invalid",
            "The column of the right answers and the column of what each is the answer to cannot be the same",
        )
    stands = look(paperagents, own, column, id_column)
    if stands is not None:
        raise ApiError(422, stands[0], stands[1])

    return {"own": own, "column": column, "id_column": id_column}


def is_in_data(paperagents: PaperAgents, answers: str, data: str | None) -> bool:
    """Whether the file of right answers is the data that the methods are run on, or is in it, as it is if the data is
    a folder that has it: code that is given the data is then given the answers, and the person is told so.

    :param answers: The name of the file of right answers, on the Data page.
    :param data: The name of the data that the methods are run on, if there is any.
    """
    if data is None:
        return False
    kept = paperagents.workspace.load_own()["data"]
    if answers not in kept or data not in kept:
        return False
    try:
        return overlaps(
            location(paperagents.workspace, answers, kept[answers]).resolve(),
            location(paperagents.workspace, data, kept[data]).resolve(),
        )
    except (OSError, RuntimeError):
        return False


def shown(paperagents: PaperAgents, labels: dict[str, Any] | None, data: str | None) -> dict[str, Any] | None:
    """Where the right answers are as a page is shown it, with what stands in the way of using them now, if anything.

    :param labels: What the bake-off keeps of them.
    :param data: The name of the data that the bake-off's methods are run on.
    """
    if labels is None:
        return None
    stands = look(paperagents, labels["own"], labels["column"], labels["id_column"])
    in_data = is_in_data(paperagents, labels["own"], data)
    file = paperagents.own_data().get(labels["own"])

    return {
        **labels,
        "ok": stands is None,
        "why": stands[0] if stands is not None else None,
        "problem": stands[1] if stands is not None else None,
        "bytes": file["bytes"] if file is not None else None,
        "in_data": in_data,
        "says": SAYING + (ALSO_THE_DATA if in_data else ""),
    }
