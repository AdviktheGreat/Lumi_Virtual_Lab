"""Holding what a method gave to the right answers that the person has, and ranking by that and by nothing else.

The right answers are the person's: a column of a table of theirs, one for each row of their data (labelling.py). They
are only as right as the person says, and a score here says how often a method gave the same answer as they did, and
nothing more: not that the method is good, and not that it would be on other data.

What a method gave is held to them only if what was kept of it is all of it, or all the values of a list or an array of
one dimension, as a run keeps them (agreeing.py): a look at an answer, or a hash of it, says too little to be held to a
row. It is matched to the rows in one of two ways, by what it is. A list has an item for each row, in the order of the
file, and has to be as long as the file has rows, since a list that is longer or shorter cannot be told which item is of
which row. An object has an item for what each row is the answer to, which is its key, and needs the column that says
what each row is the answer to. What is not one of those is not scored, and says why.

The score is how many of the labels it matched, over how many labels there are. The labels are the rows that have an
answer, for every method alike, so that a method that gave fewer items, or left out rows, is held to the same number
as the others and loses for it: an answer for a row that it did not give is wrong. A method that could not be held to
the labels at all is not scored, which is not the same as scoring none, and it is not ranked.

An item matches a label if it is the same text, exactly, or the same number within the tolerance for numbers (a label
that is a number is read as one, in the plain way), or the same truth if it is true or false. Nothing else is guessed:
not another case of the same word, and not a number written as words.
"""

from collections import Counter
from collections.abc import Mapping
from typing import Any

from virtual_lab.paperagents import agreeing, comparing, labelling
from virtual_lab.tables import NUMBER

# Why a method was not scored
LABELS_UNUSABLE = "labels_unusable"
NO_ANSWER = "no_answer"
DATA_CHANGED = "data_changed"
NOT_KEPT = "not_kept"
NOT_A_LIST_OR_OBJECT = "not_a_list_or_object"
NOT_VALUES = "not_values"
LENGTH = "length"
NO_ID_COLUMN = "no_id_column"
IDS_UNUSABLE = "ids_unusable"
NONE_IN_COMMON = "none_in_common"
BY_POSITION, BY_ID = "position", "id"
MAX_EXAMPLES = 5

MEANING = (
    "A score is how many of the person's labels a method gave the same answer to, out of how many labels there are, "
    "and is as good as the labels are, which are the person's word and are not checked. It says nothing of what the "
    "method would do on other data. An answer for a row that a method did not give counts as wrong. A method that "
    "could not be held to the labels is not scored, and its row says why; only the methods that were scored are "
    "ranked, and those that matched the same number share a rank."
)


def unscored(why: str, reason: str) -> dict[str, Any]:
    """What a method that was not held to the labels shows."""
    return {
        "scored": False,
        "why": why,
        "reason": reason,
        "by": None,
        "matched": None,
        "of": None,
        "score": None,
        "missing": None,
        "extra": None,
        "examples": [],
        "rank": None,
    }


def scored(by: str, matched: int, of: int, missing: int, extra: int, examples: list[str]) -> dict[str, Any]:
    return {
        "scored": True,
        "why": None,
        "reason": "",
        "by": by,
        "matched": matched,
        "of": of,
        "score": matched / of,
        "missing": missing,
        "extra": extra,
        "examples": examples,
        "rank": None,
    }


def content_of(result: Mapping[str, Any]) -> tuple[bool, Any, str]:
    """What a method gave, as far as it can be held to labels.

    :param result: What a run kept of the answer.
    :return: Whether there is something to hold, what it is, and, if not, why not.
    """
    kept = agreeing.kept_as(result)
    if kept == agreeing.WHOLE:
        return True, result["value"], ""
    if kept == agreeing.LOOK and "values" in result and len(result.get("shape") or []) == 1:
        return True, result["values"], ""
    if kept == agreeing.HASH:
        why = (
            "Only a hash of what it gave was kept, because it was more than could be kept, so it cannot be held to the "
            "labels."
        )
    elif "values" in result:
        why = "What it gave is a table or an array of more than one dimension, which is not one answer for each row."
    else:
        why = "Only a look at what it gave was kept, and not all of it, so it cannot be held to the labels."

    return False, None, why


def is_value(item: Any) -> bool:
    """Whether an item can be an answer for a row: some text, a number, or true or false."""
    return isinstance(item, str | int | float)


def number_of(label: str) -> int | float | None:
    """A label as a number, if it is written as one in the plain way, and not as what a reader that is more generous
    would take for one."""
    if NUMBER.fullmatch(label) is None:
        return None
    try:
        return int(label) if label.lstrip("+-").isdigit() else float(label)
    except ValueError:
        return None


def is_match(item: Any, label: str, tolerance: comparing.Tolerance) -> bool:
    """Whether what a method gave for a row is the answer that the labels have."""
    if isinstance(item, bool):
        return label.lower() in ("true", "false") and (label.lower() == "true") is item
    if isinstance(item, str):
        return item == label
    if agreeing.is_number(item):
        number = number_of(label)
        return number is not None and agreeing.is_same_number(item, number, tolerance)

    return False


def by_position(items: list[Any], labels: labelling.Labels, tolerance: comparing.Tolerance) -> dict[str, Any]:
    rows = len(labels.answers)
    if len(items) != rows:
        return unscored(
            LENGTH,
            f"It gave a list of {len(items):,} items, and the file has {rows:,} rows, so it is not known which item is "
            "of which row.",
        )
    if not any(is_value(item) for item in items):
        return unscored(
            NOT_VALUES,
            "Its list does not have an answer in it for any row: no item is text, a number, or true or false.",
        )
    matched = 0
    examples: list[str] = []
    for index, (item, label) in enumerate(zip(items, labels.answers, strict=True), start=1):
        if label is None:
            continue
        if is_match(item, label, tolerance):
            matched += 1
        elif len(examples) < MAX_EXAMPLES:
            examples.append(f"row {index}: the label is {comparing.shown(label)} and it gave {comparing.shown(item)}")

    return scored(BY_POSITION, matched, labels.labelled, 0, 0, examples)


def by_id(items: Mapping[str, Any], labels: labelling.Labels, tolerance: comparing.Tolerance) -> dict[str, Any]:
    if labels.ids is None:
        return unscored(
            NO_ID_COLUMN,
            "It gave an object with a key for each thing answered, and no column of what each row is the answer to was "
            "said, so its items cannot be matched to rows. Only a list in the order of the rows can be.",
        )
    rows = [(name, answer) for name, answer in zip(labels.ids, labels.answers, strict=True) if answer is not None]
    names = [name for name, _ in rows]
    if None in names:
        return unscored(
            IDS_UNUSABLE,
            f"Some rows that have an answer have nothing in the column {labels.id_column!r}, so they cannot be "
            "matched.",
        )
    if len(set(names)) != len(names):
        counts = Counter(names)
        repeated = next(name for name in names if counts[name] > 1)
        return unscored(
            IDS_UNUSABLE,
            f"{repeated!r} is in the column {labels.id_column!r} of more than one row that has an answer, so which "
            "is meant is not known.",
        )
    if not any(name in items for name in names):
        return unscored(
            NONE_IN_COMMON,
            f"None of its {len(items):,} keys is a value in the column {labels.id_column!r} of the file, so its items "
            "cannot be matched to rows.",
        )
    if not any(is_value(item) for item in items.values()):
        return unscored(
            NOT_VALUES,
            "Its object does not have an answer in it for any row: no item is text, a number, or true or false.",
        )
    matched = missing = 0
    examples: list[str] = []
    for name, label in rows:
        if name not in items:
            missing += 1
            if len(examples) < MAX_EXAMPLES:
                examples.append(f"{comparing.shown(name)}: the label is {comparing.shown(label)} and it gave nothing")
        elif is_match(items[name], label, tolerance):
            matched += 1
        elif len(examples) < MAX_EXAMPLES:
            gave = comparing.shown(items[name])
            examples.append(f"{comparing.shown(name)}: the label is {comparing.shown(label)} and it gave {gave}")
    known = {name for name in labels.ids if name is not None}
    extra = sum(1 for key in items if key not in known)

    return scored(BY_ID, matched, labels.labelled, missing, extra, examples)


def score(result: Mapping[str, Any], labels: labelling.Labels, tolerance: comparing.Tolerance) -> dict[str, Any]:
    """How a method's answer does against the labels.

    :param result: What a run kept of the answer, as `bakeoff_runs` keeps it.
    :param labels: The right answers, as read.
    :param tolerance: How closely two numbers must be to be the same.
    :return: Whether it was scored, and if so how it was matched to the rows, how many labels it matched out of how many
        there are, its score, and where it did not match; and if not, why not.
    """
    found, content, why = content_of(result)
    if not found:
        return unscored(NOT_KEPT, why)
    if isinstance(content, list):
        return by_position(content, labels, tolerance)
    if isinstance(content, dict) and "$float" not in content:
        return by_id(content, labels, tolerance)

    return unscored(
        NOT_A_LIST_OR_OBJECT,
        f"It gave {comparing.shown(content)}, which is not a list with an item for each row, or an object with an "
        "item for each thing answered.",
    )


def ranks(scores: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    """The rank of each method that was scored: the most labels matched is first, those that matched the same number
    share a rank, and the next rank is the one after them all (1, 1, 3). A method that was not scored has none, so it is
    not in what is given back.

    :param scores: What `score` gave, by the method's id.
    """
    matched: Mapping[str, int] = {name: each["matched"] for name, each in scores.items() if each["scored"]}

    return {name: 1 + sum(1 for other in matched.values() if other > count) for name, count in matched.items()}
