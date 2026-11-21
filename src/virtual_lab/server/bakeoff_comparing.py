"""Putting the methods of a bake-off side by side: how each came out, what it cost, and whether they agree.

It is made each time from what is kept, with nothing run and no model asked: each method as the bake-off shows it, the
latest run of it, and what it cost to read its paper. A method that was not built, was not run, or failed is a row of
the table with why, and is not left out of it.

Without right answers there is no ground truth here, and the table says so: the methods are held to each other and not
to what the answer should be, so they are not ranked, and agreeing is not being right (paperagents/agreeing.py). A
person who has said where the right answers are for their data (bakeoff_labels.py) has the methods held to them too,
each scored by how many of the labels it matched, and ranked by that and by nothing else (paperagents/scoring.py). The
labels are read from where they are each time, and the table says which file they were, by its hash, and that they are
the person's word.

What a method cost is of two kinds, which are kept apart: reading its paper, which is what its PaperAgent's reading
cost, and may have been paid before the bake-off was made, and asking a model to propose the call, which is what the
run says it cost, and is nothing if the person made the call.
"""

from typing import TYPE_CHECKING, Any

from virtual_lab.paper_batch import csv_bytes
from virtual_lab.paperagents import agreeing, comparing, labelling, scoring
from virtual_lab.paperagents import bakeoff_table as table
from virtual_lab.server import bakeoff_labels
from virtual_lab.server import bakeoff_runs as kept_runs
from virtual_lab.server.errors import ApiError, not_found

if TYPE_CHECKING:
    from virtual_lab.server.bakeoffs import Bakeoffs

STATE_NOT_BUILT = "not_built"
# Which of a method's lists of the others a verdict puts the other method in
LISTS = {agreeing.AGREE: "agrees", agreeing.DIFFER: "differs", agreeing.UNKNOWN: "unknown"}
SAYS = (
    "No answer that is known to be right was given, so the methods are compared with each other and are not ranked. "
    "Agreeing is not being right."
)
SAYS_SCORED = (
    "The methods were held to the right answers that the person gave, which are their word and are not checked here, "
    "and ranked by how many of them each matched. A method that could not be held to them is not ranked, and says why. "
    "Agreeing with each other is still not being right."
)
SAYS_UNUSABLE = (
    "The person said where the right answers are, and they cannot be used now ({problem}), so the methods are compared "
    "with each other and are not scored or ranked. Agreeing is not being right."
)


def check_tolerance(relative: Any, absolute: Any) -> comparing.Tolerance:
    """How closely two numbers must be to be the same, which is the person's to say and is shown.

    :raises ApiError: If either is not a number that is finite and not negative, or the relative one is 1 or more.
    """
    tolerance = comparing.Tolerance(
        comparing.RELATIVE_TOLERANCE if relative is None else relative,
        comparing.ABSOLUTE_TOLERANCE if absolute is None else absolute,
    )
    if not agreeing.is_tolerance(tolerance.relative, tolerance.absolute):
        raise ApiError(
            422,
            "invalid",
            "A tolerance is a number that is not negative, and the relative one is less than 1",
        )

    return tolerance


class Comparer:
    """Shows the methods of bake-offs side by side.

    :param bakeoffs: The bake-offs, which say what a method is and keep what came of the run of each.
    """

    def __init__(self, bakeoffs: "Bakeoffs") -> None:
        self.bakeoffs = bakeoffs
        self.paperagents = bakeoffs.paperagents

    def comparison(self, bakeoff_id: str, relative: Any = None, absolute: Any = None) -> dict[str, Any]:
        """How the methods of a bake-off came out and whether they agree, as of now.

        :param relative: How closely two numbers must be, as a part of the larger, to be the same. The checks' own if
            left out.
        :param absolute: The same for two numbers near zero.
        :raises ApiError: If there is no bake-off with this id, or the tolerance is not one.
        """
        tolerance = check_tolerance(relative, absolute)
        directory, record = self.bakeoffs.lookup(bakeoff_id)
        agents = self.paperagents.kept()
        named = record["data"]["own"] if record["data"] is not None else None
        runs = {each["id"]: kept_runs.load(directory, each["id"]) for each in record["candidates"]}
        data_now = (
            self.bakeoffs.data_now(named)
            if any(run is not None and run["data"] is not None for run in runs.values())
            else None
        )
        building_now = self.bakeoffs.building(bakeoff_id)
        snapshot = building_now.snapshot() if building_now is not None else None
        pairs = agreeing.pairs(runs, tolerance)
        truth, labels = bakeoff_labels.examined(self.paperagents, record["labels"], named)
        methods = [
            self.method_of(
                self.bakeoffs.shown(candidate, agents, snapshot, record["described"], runs[candidate["id"]], data_now),
                runs[candidate["id"]],
                pairs,
            )
            for candidate in record["candidates"]
        ]
        ranked = self.score(methods, runs, truth, labels, tolerance)

        return {
            "id": bakeoff_id,
            "title": record["title"],
            "task": record["task"],
            "limit": record["limit"],
            "spent": record["spent"],
            "cost_known": record["cost_known"],
            "tolerance": tolerance.to_dict(),
            "ground_truth": truth,
            "ranked": ranked,
            "says": (
                SAYS
                if truth is None
                else SAYS_SCORED
                if truth["ok"]
                else SAYS_UNUSABLE.format(problem=truth["problem"].rstrip("."))
            ),
            "meaning": agreeing.MEANING + (" " + scoring.MEANING if truth is not None and truth["ok"] else ""),
            "methods": methods,
            "pairs": pairs,
        }

    def score(
        self,
        methods: list[dict[str, Any]],
        runs: dict[str, dict[str, Any] | None],
        truth: dict[str, Any] | None,
        labels: labelling.Labels | None,
        tolerance: comparing.Tolerance,
    ) -> bool:
        """Holds each method to the right answers, if there are any, and ranks the ones that were scored, putting what
        it found in each method's `score`.

        :return: Whether any method was ranked.
        """
        if truth is None:
            return False
        scores = {
            method["id"]: self.score_of(method, runs[method["id"]], truth, labels, tolerance) for method in methods
        }
        ranks = scoring.ranks(scores)
        for method in methods:
            method["score"] = {**scores[method["id"]], "rank": ranks.get(method["id"])}

        return bool(ranks)

    def score_of(
        self,
        method: dict[str, Any],
        run: dict[str, Any] | None,
        truth: dict[str, Any],
        labels: labelling.Labels | None,
        tolerance: comparing.Tolerance,
    ) -> dict[str, Any]:
        """How one method does against the right answers, or why it was not held to them."""
        if labels is None:
            return scoring.unscored(scoring.LABELS_UNUSABLE, truth["problem"] or "The right answers cannot be used.")
        if run is None or run["state"] != kept_runs.RAN:
            return scoring.unscored(scoring.NO_ANSWER, "It gave no answer, so there is nothing to hold to the labels.")
        if "data" in method["since"]:
            return scoring.unscored(
                scoring.DATA_CHANGED,
                "The data is not as it was listed when this was run, so what it gave may not be of the rows that the "
                "labels are of. Run it again.",
            )

        return scoring.score(run["result"], labels, tolerance)

    def method_of(
        self, shown: dict[str, Any], run: dict[str, Any] | None, pairs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """A method as the table shows it: where it stands, what came of running it, what it cost, and whom it agrees
        with."""
        standing = shown["standing"]
        if run is not None:
            state, why, reason = run["state"], run["why"], run["reason"]
        elif standing["state"] == "built":
            state, why, reason = kept_runs.NOT_RUN, "not_yet", "It is built, and has not been run."
        else:
            state = STATE_NOT_BUILT
            why = standing.get("why") or standing["state"]
            reason = standing["reason"] or "It has not been built."
        agent = shown["agent"]
        reading = self.paperagents.reading(agent["id"])["cost"] if agent is not None else None
        proposed = run["proposed"] if run is not None else None
        mine = shown["id"]
        others: dict[str, list[str]] = {name: [] for name in LISTS.values()}
        for pair in pairs:
            if mine in (pair["first"], pair["second"]):
                others[LISTS[pair["verdict"]]].append(pair["second"] if pair["first"] == mine else pair["first"])

        return {
            "id": mine,
            "name": shown["name"],
            "title": shown["title"],
            "agent": agent,
            "state": state,
            "why": why,
            "reason": reason,
            "tier": run["tool"]["tier"] if run is not None and run["tool"] is not None else None,
            "tool": run["tool"]["name"] if run is not None and run["tool"] is not None else None,
            "seconds": run["seconds"] if run is not None else None,
            "cost": {
                "reading": reading,
                "asking": (0.0 if proposed is None else proposed["cost"]) if run is not None else None,
            },
            "by": run["by"] if run is not None else None,
            "kept": agreeing.kept_as(run["result"]) if run is not None and run["result"] is not None else None,
            "since": shown["run"]["since"] if shown["run"] is not None else [],
            "score": None,
            **others,
        }

    def table(self, bakeoff_id: str, kind: str, relative: Any = None, absolute: Any = None) -> tuple[str, bytes]:
        """The methods, or each two of them that gave an answer, as a table to open in a spreadsheet, made each time
        from what is kept.

        :param kind: "methods" or "pairs".
        :return: What to call the file, and what is in it.
        :raises ApiError: If there is no bake-off with this id, or no such table, or the tolerance is not one.
        """
        if kind not in table.KINDS:
            raise not_found("table of that bake-off")
        found = self.comparison(bakeoff_id, relative, absolute)
        if kind == table.METHODS:
            content = csv_bytes(table.METHOD_COLUMNS, table.method_rows(found))
        else:
            content = csv_bytes(table.PAIR_COLUMNS, table.pair_rows(found))

        return f"{found['title']} - {kind}", content
