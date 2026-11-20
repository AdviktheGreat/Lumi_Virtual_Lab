"""Putting the methods of a bake-off side by side: how each came out, what it cost, and whether they agree.

It is made each time from what is kept, with nothing run and no model asked: each method as the bake-off shows it, the
latest run of it, and what it cost to read its paper. A method that was not built, was not run, or failed is a row of
the table with why, and is not left out of it.

There is no ground truth here, and the table says so: the methods are held to each other and not to what the answer
should be, so they are not ranked, and agreeing is not being right (paperagents/agreeing.py). A person who has labels
for their data can have the methods scored against them, and ranked only by that.

What a method cost is of two kinds, which are kept apart: reading its paper, which is what its PaperAgent's reading
cost, and may have been paid before the bake-off was made, and asking a model to propose the call, which is what the
run says it cost, and is nothing if the person made the call.
"""

from typing import TYPE_CHECKING, Any

from virtual_lab.paper_batch import csv_bytes
from virtual_lab.paperagents import agreeing, comparing
from virtual_lab.paperagents import bakeoff_table as table
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
        methods = [
            self.method_of(
                self.bakeoffs.shown(candidate, agents, snapshot, record["described"], runs[candidate["id"]], data_now),
                runs[candidate["id"]],
                pairs,
            )
            for candidate in record["candidates"]
        ]

        return {
            "id": bakeoff_id,
            "title": record["title"],
            "task": record["task"],
            "limit": record["limit"],
            "spent": record["spent"],
            "cost_known": record["cost_known"],
            "tolerance": tolerance.to_dict(),
            "ground_truth": None,
            "ranked": False,
            "says": SAYS,
            "meaning": agreeing.MEANING,
            "methods": methods,
            "pairs": pairs,
        }

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
