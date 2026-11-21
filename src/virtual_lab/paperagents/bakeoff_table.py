"""What a bake-off came to, as tables to open in a spreadsheet: one row for each method, and one for each two
methods that gave an answer.

The rows are made of what the server shows of the comparison of the methods (which is made of what was kept of each
run), and say no more than it does. A method that was not built, or was not run, or failed, has its row, with why, so
that it is not left out of a table for not having an answer; the first table is how each did and what it cost, and the
second is whether two agreed. The first ranks the methods only if the person said where the right answers are, by how
many of them each matched (scoring.py), and says which methods were not held to them and why; with none, nothing is
ranked, as there is no answer that is known to be right, and a table says so, in words that go with it. A method's cell
for a thing that is not known is left as the word that says so, and not as nothing, which would read as none. Some cells
are made of a paper's words, and are cleaned when the table is written.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from virtual_lab.paperagents import agreeing

METHODS = "methods"
PAIRS = "pairs"
KINDS = (METHODS, PAIRS)

METHOD_COLUMNS = (
    "Method",
    "Paper",
    "State",
    "Why (kind)",
    "Why",
    "Trust tier",
    "Tool called",
    "Seconds",
    "Cost of reading its paper",
    "Cost of asking a model for the call",
    "The call was made by",
    "What was kept of its answer",
    "Score",
    "Matched",
    "Of labels",
    "Rank",
    "Held to the labels",
    "Where it differs from the labels",
    "Not scored because",
    "Agrees with",
    "Differs from",
    "Not known whether it agrees with",
    "Since it ran",
)

PAIR_COLUMNS = (
    "Method",
    "Other method",
    "Agree",
    "How that is known",
    "What differs",
    "Kept of the method's answer",
    "Kept of the other's answer",
    "Relative tolerance",
    "Absolute tolerance",
)

STATE_TITLES = {"ran": "Ran", "failed": "Failed", "not_run": "Not run", "not_built": "Not built"}
VERDICT_TITLES = {agreeing.AGREE: "Agree", agreeing.DIFFER: "Differ", agreeing.UNKNOWN: "Not known"}
KEPT_TITLES = {agreeing.WHOLE: "All of it", agreeing.LOOK: "A look at it", agreeing.HASH: "Only a hash of it"}
BY_TITLES = {"person": "The person", "model": "A model, checked by a program"}
HELD_TITLES = {"position": "By position, in the order of the rows", "id": "By what each row is the answer to"}
SINCE_TITLES = {
    "data": "The data is not as it was listed then",
    "method": "The method was built again or is gone",
}
UNKNOWN = "not known"


def money(value: float | None) -> Any:
    """What something cost, which is the word for it if it is not known."""
    return UNKNOWN if value is None else round(value, 6)


def named(names: Mapping[str, str], ids: Sequence[str]) -> str:
    return "; ".join(names.get(each, each) for each in ids)


def score_cells(score: Mapping[str, Any] | None) -> dict[str, Any]:
    """The cells of a method's row that are of the right answers, which are all empty if there are none, or the method
    was not held to them."""
    if score is None:
        return {
            "Score": "",
            "Matched": "",
            "Of labels": "",
            "Rank": "",
            "Held to the labels": "",
            "Where it differs from the labels": "",
            "Not scored because": "",
        }

    return {
        "Score": round(score["score"], 6) if score["scored"] else "",
        "Matched": score["matched"] if score["scored"] else "",
        "Of labels": score["of"] if score["scored"] else "",
        "Rank": score["rank"] if score["rank"] is not None else "",
        "Held to the labels": HELD_TITLES.get(score["by"], "") if score["by"] else "",
        "Where it differs from the labels": "; ".join(score["examples"]),
        "Not scored because": "" if score["scored"] else score["reason"],
    }


def method_rows(comparison: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row for each method, in the order that they were put in the running.

    :param comparison: What `Bakeoffs.comparison` gives.
    """
    names = {method["id"]: method["name"] for method in comparison["methods"]}

    return [
        {
            "Method": method["name"],
            "Paper": method["title"],
            "State": STATE_TITLES.get(method["state"], method["state"]),
            "Why (kind)": method["why"] or "",
            "Why": method["reason"],
            "Trust tier": method["tier"] or "",
            "Tool called": method["tool"] or "",
            "Seconds": method["seconds"] if method["seconds"] is not None else "",
            "Cost of reading its paper": money(method["cost"]["reading"]) if method["agent"] else "",
            "Cost of asking a model for the call": (
                money(method["cost"]["asking"]) if method["by"] is not None else ""
            ),
            "The call was made by": BY_TITLES.get(method["by"], "") if method["by"] else "",
            "What was kept of its answer": KEPT_TITLES.get(method["kept"], "") if method["kept"] else "",
            **score_cells(method["score"]),
            "Agrees with": named(names, method["agrees"]),
            "Differs from": named(names, method["differs"]),
            "Not known whether it agrees with": named(names, method["unknown"]),
            "Since it ran": "; ".join(SINCE_TITLES.get(each, each) for each in method["since"]),
        }
        for method in comparison["methods"]
    ]


def pair_rows(comparison: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row for each two methods that both gave an answer.

    :param comparison: What `Bakeoffs.comparison` gives.
    """
    names = {method["id"]: method["name"] for method in comparison["methods"]}
    tolerance = comparison["tolerance"]

    return [
        {
            "Method": names.get(pair["first"], pair["first"]),
            "Other method": names.get(pair["second"], pair["second"]),
            "Agree": VERDICT_TITLES[pair["verdict"]],
            "How that is known": pair["how"],
            "What differs": "; ".join(pair["differences"]),
            "Kept of the method's answer": KEPT_TITLES[pair["kept"][0]],
            "Kept of the other's answer": KEPT_TITLES[pair["kept"][1]],
            "Relative tolerance": tolerance["relative"],
            "Absolute tolerance": tolerance["absolute"],
        }
        for pair in comparison["pairs"]
    ]
