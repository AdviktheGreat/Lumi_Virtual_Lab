"""Bake-offs: which method to use for a task, decided by trying the methods of the literature on the person's own data.

A bake-off is kept in a directory of its own in the workspace's bakeoffs/ (paperagent_bakeoff.py). It says what the
person wants done, which of their data it is to be done on, and how much the whole of it may spend, and it has the
methods that are in the running, the candidates. The first step of it is finding them, and the second is building them.

A model writes a few short searches for the task, a program runs them in Europe PMC and on arXiv, and a model chooses,
from the abstracts that were found, the papers that are of a method that does the task, with the words of the abstract
that it went by, which a program checks are in the abstract (paperagents/shortlisting.py). The candidates that come of
that are the model's reading of abstracts and are shown as that: it is not said that they work, or that they work on
the person's data, or that they are the best there are. The person may add a method that it left out, by its paper, and
may take any away, name them, and say where each one's code is. The address of code that an abstract has in it is only
shown as a suggestion, and nothing is fetched from it, nor from anywhere else, before the person says that it is the
code. Finding them builds nothing and runs nothing, and makes no PaperAgent.

Building them (bakeoff_building.py) gives each method that the person asks for the PaperAgent of its paper, which is
made if there is none, and does the steps that a PaperAgent has to it one after another, as they are done by hand: so a
step that was done by hand is not done again, and one that is done here can be looked at on the PaperAgent's page. What
is built is the PaperAgent's, and what stood in the way of a method is kept with it here.

What a model is asked is paid for out of the bake-off's one limit on spending, which is set when it is made and may be
raised, and which is never less than what has been spent.

The person may say what their data is, and each method is then shown with what the method card of its paper says of it,
once the paper is read: inside, outside, or not covered (bakeoff_scope.py). A method whose card the data is outside of
is not run on it until the person has said to go on with that method, which they say of what they were shown.
"""

import secrets
import shutil
import textwrap
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from virtual_lab.environment import StoppedError
from virtual_lab.paperagents import asking, shortlisting
from virtual_lab.paperagents import environment as building
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import bakeoff_runs as kept_runs
from virtual_lab.server import bakeoff_scope
from virtual_lab.server import paperagent_bakeoff as kept_bakeoff
from virtual_lab.server.bakeoff_building import Builder
from virtual_lab.server.bakeoff_running import Runs, place_of
from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.jobs import Job, JobConflictError
from virtual_lab.server.paperagents import (
    PaperAgents,
    check_paper,
    check_repo,
    default_title,
    is_blank,
    is_real_directory,
    same_paper,
    steps_of,
)
from virtual_lab.server.papers import RUN_ID, check_budget, money
from virtual_lab.server.workspace import claim_directory, has_control_character
from virtual_lab.utils import MeetingUsage

# The job that finds the methods of a task in the literature, which is not done to a bake-off while it is being done
SHORTLIST_JOB = "bakeoff-shortlist"
# The job that builds the methods that are in the running, which is not done to a bake-off while it is being done either
BUILD_JOB = "bakeoff-build"
RUN_JOB = "bakeoff-run"


def check_task(text: Any) -> str:
    """What the person wants done, as it is kept: in their words, on one line.

    :raises ApiError: If it is nothing, is too long, or has what is not text in it.
    """
    task = " ".join(text.split()) if isinstance(text, str) else ""
    if not task or len(task) > kept_bakeoff.MAX_TASK_CHARS or has_control_character(task):
        raise ApiError(
            422,
            "invalid",
            f"The task is what the person wants done, in one to {kept_bakeoff.MAX_TASK_CHARS} characters, "
            f"not {str(text)[:80]!r}",
        )

    return task


def check_name(text: Any, what: str, most: int) -> str:
    """What a bake-off or a candidate is called, one line.

    :raises ApiError: If it is nothing, is too long, or has what is not text in it.
    """
    name = " ".join(text.split()) if isinstance(text, str) else ""
    if not name or len(name) > most or has_control_character(name):
        raise ApiError(422, "invalid", f"{what} is called by one to {most} characters, not {str(text)[:80]!r}")

    return name


class Bakeoffs:
    """The bake-offs, kept in a workspace.

    :param paperagents: The PaperAgents, which a bake-off is of the papers of, and which it asks what it needs of: the
        model that may be paid for, the person's own data, which addresses are those of code, and where jobs are run.
    :param articles: What searches Europe PMC, as `literature.search_articles` does, which is for tests.
    :param preprints: What searches arXiv, as `literature.search_preprints` does, which is for tests.
    """

    def __init__(
        self,
        paperagents: PaperAgents,
        articles: Callable[..., Any] | None = None,
        preprints: Callable[..., Any] | None = None,
    ) -> None:
        self.paperagents = paperagents
        self.workspace = paperagents.workspace
        self.jobs = paperagents.jobs
        self.articles = articles
        self.preprints = preprints
        self.builder = Builder(self)
        self.runs = Runs(self)
        # Held while a bake-off is read, changed, and kept again, so that two changes do not undo each other
        self._lock = threading.Lock()

    # What there is

    def kept(self) -> list[tuple[Path, dict[str, Any]]]:
        """The bake-offs there are, each with where it is kept and what its file holds."""
        root = self.workspace.bakeoffs_dir
        found = []
        if root.is_dir():
            for directory in root.iterdir():
                record = (
                    kept_bakeoff.load(directory)
                    if RUN_ID.fullmatch(directory.name) and is_real_directory(directory)
                    else None
                )
                if record is not None:
                    found.append((directory, record))

        return found

    def lookup(self, bakeoff_id: str) -> tuple[Path, dict[str, Any]]:
        """Where a bake-off is kept, and what it is.

        :raises ApiError: If there is no bake-off with this id.
        """
        directory = self.workspace.bakeoffs_dir / bakeoff_id
        record = kept_bakeoff.load(directory) if RUN_ID.fullmatch(bakeoff_id) and is_real_directory(directory) else None
        if record is None:
            raise not_found("bake-off with that id")

        return directory, record

    def finding(self, bakeoff_id: str) -> Job | None:
        """The job that is finding the methods of a bake-off, if one is."""
        return next((job for job in self.jobs.active(SHORTLIST_JOB) if job.subject == bakeoff_id), None)

    def building(self, bakeoff_id: str) -> Job | None:
        """The job that is building the methods of a bake-off, if one is."""
        return next((job for job in self.jobs.active(BUILD_JOB) if job.subject == bakeoff_id), None)

    def calling(self, bakeoff_id: str) -> Job | None:
        """The job that is running the methods of a bake-off on the person's data, if one is."""
        return next((job for job in self.jobs.active(RUN_JOB) if job.subject == bakeoff_id), None)

    def running(self, bakeoff_id: str) -> Job | None:
        """The job that is finding, building, or running the methods of a bake-off, if one is."""
        return self.finding(bakeoff_id) or self.building(bakeoff_id) or self.calling(bakeoff_id)

    def check_idle(self, bakeoff_id: str) -> None:
        """
        :raises ApiError: If the methods of the bake-off are being found, built, or run, which what is done to it must
            wait for.
        """
        job = self.running(bakeoff_id)
        if job is not None:
            raise ApiError(409, "busy", f"{job.title} is still going. Stop that first", job=job.snapshot())

    def describe(self) -> dict[str, Any]:
        """Every bake-off, the latest first, and what a page needs to make one."""
        found = [self.summary(directory.name, record) for directory, record in self.kept()]

        return {
            "bakeoffs": sorted(found, key=lambda entry: (entry["created_at"], entry["id"]), reverse=True),
            "own": list(self.paperagents.own_data().values()),
            "limits": self.limits(),
            "settings_model": self.workspace.load_settings().model,
        }

    def limits(self) -> dict[str, int]:
        return {
            "max_bakeoffs": kept_bakeoff.MAX_BAKEOFFS,
            "max_candidates": kept_bakeoff.MAX_CANDIDATES,
            "max_task_chars": kept_bakeoff.MAX_TASK_CHARS,
            "max_title_chars": kept_bakeoff.MAX_TITLE_CHARS,
            "max_name_chars": kept_bakeoff.MAX_NAME_CHARS,
            "max_queries": shortlisting.MAX_QUERIES,
            "most_found": shortlisting.MOST_FOUND,
            "most_chosen": shortlisting.MOST_CHOSEN,
        }

    def summary(self, bakeoff_id: str, record: dict[str, Any]) -> dict[str, Any]:
        """A bake-off as a list of them shows it."""
        job = self.running(bakeoff_id)

        return {
            "id": bakeoff_id,
            "title": record["title"],
            "task": record["task"],
            "created_at": record["created_at"],
            "candidates": len(record["candidates"]),
            "limit": record["limit"],
            "spent": record["spent"],
            "cost_known": record["cost_known"],
            "job": job.snapshot() if job is not None else None,
        }

    def view(self, bakeoff_id: str) -> dict[str, Any]:
        """A bake-off, with its data as it is now, its candidates each with the PaperAgent of its paper if there is
        one, and what is left of its limit.

        :raises ApiError: If there is no bake-off with this id.
        """
        directory, record = self.lookup(bakeoff_id)
        agents = self.paperagents.kept()
        named = record["data"]["own"] if record["data"] is not None else None
        own = self.paperagents.own_data().get(named) if named is not None else None
        job = self.running(bakeoff_id)
        building_now = self.building(bakeoff_id)
        building_snapshot = building_now.snapshot() if building_now is not None else None
        runs = {each["id"]: kept_runs.load(directory, each["id"]) for each in record["candidates"]}
        data_now = (
            self.data_now(named) if any(run is not None and run["data"] is not None for run in runs.values()) else None
        )

        return {
            **self.summary(bakeoff_id, record),
            "data": (
                {"own": named, "missing": own is None or own["kind"] == "missing", **(own or {})}
                if named is not None
                else None
            ),
            "described": record["described"],
            "left": kept_bakeoff.left_of(record),
            "shortlist": record["shortlist"],
            "candidates": [
                self.shown(candidate, agents, building_snapshot, record["described"], runs[candidate["id"]], data_now)
                for candidate in record["candidates"]
            ],
            "job": job.snapshot() if job is not None else None,
            "limits": self.limits(),
            "meaning": shortlisting_meaning(),
            "settings_model": self.workspace.load_settings().model,
        }

    def shown(
        self,
        candidate: dict[str, Any],
        agents: list[tuple[Path, dict[str, Any]]],
        building_snapshot: dict[str, Any] | None,
        described: dict[str, Any] | None = None,
        run: dict[str, Any] | None = None,
        data_now: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """A candidate as a page is shown it: with the PaperAgent of its paper if there is one, where it stands, what
        the card of its paper says of the data, and what came of running it on the data if it was, with whether the data
        and the method are as they were then.

        :param run: What is kept of the last run of the method.
        :param data_now: The data that the bake-off is run on as it is listed now, if a run says what it ran on.
        """
        found = kept_bakeoff.agent_for(candidate["paper"], agents)
        entry = self.paperagents.entry(found[0], found[1]) if found is not None else None
        agent = (
            {
                "id": entry["id"],
                "title": entry["title"],
                "repo": (entry["repo"] or {}).get("url"),
                "steps": entry["steps"],
            }
            if entry is not None
            else None
        )

        return {
            **candidate,
            "agent": agent,
            "standing": kept_bakeoff.standing_of(candidate, agent, building_snapshot),
            "scope": bakeoff_scope.scope_of(self.paperagents, described, candidate, agent["id"] if agent else None),
            "run": kept_runs.summary(run, data_now, self.runs.method_now(found)) if run is not None else None,
        }

    def data_now(self, named: str | None) -> dict[str, Any] | None:
        """The data that a bake-off is run on as it is listed now, with its name, or None if there is none or it cannot
        be given to code."""
        place = place_of(self.workspace, named) if named is not None else None

        return {"own": named, **kept_runs.listing_of(place)} if place is not None and named is not None else None

    # Making, changing, and taking away

    def check_data(self, name: Any) -> str | None:
        """The name of the person's own data, which is a piece of it that is there, or None for none.

        :raises ApiError: If there is no data of the person's with that name, or it is gone from where it was.
        """
        if is_blank(name):
            return None
        own = self.paperagents.own_data().get(name) if isinstance(name, str) else None
        if own is None:
            raise ApiError(422, "unknown_data", f"There is no data called {str(name)[:80]!r} on the Data page")
        if own["kind"] == "missing":
            raise ApiError(422, "missing_data", f"The data called {name!r} is not where the Data page says it is")

        return str(name)

    def create(self, title: Any, task: Any, data: Any = None, limit: Any = None, described: Any = None) -> str:
        """Makes a bake-off, with no methods in it yet.

        :param title: What it is called, which may be left out, and is then made of the task.
        :param task: What the person wants done.
        :param data: The name of the person's own data that the methods are to be run on, if it is known.
        :param limit: The most that the whole of it may spend, in USD, which must be said.
        :param described: What the data is, if the person says, as a scope check takes it.
        :raises ApiError: If what is given is not fit, or there are too many bake-offs.
        :return: Its id.
        """
        made = check_task(task)
        named = (
            check_name(title, "A bake-off", kept_bakeoff.MAX_TITLE_CHARS)
            if not is_blank(title)
            else textwrap.shorten(made, 80, placeholder="…")
        )
        chosen = self.check_data(data)
        said = bakeoff_scope.check_described(described) if described is not None else None
        budget = check_budget(limit, "The most it may spend", required=True)
        assert budget is not None
        root = self.workspace.bakeoffs_dir
        root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if len(self.kept()) >= kept_bakeoff.MAX_BAKEOFFS:
                raise ApiError(
                    409,
                    "too_many",
                    f"No more than {kept_bakeoff.MAX_BAKEOFFS} bake-offs can be kept. Delete some first",
                )
            directory = claim_directory(root, named)
            try:
                kept_bakeoff.keep(directory, kept_bakeoff.new_record(named, made, chosen, budget, said))
            except BaseException:
                shutil.rmtree(directory, ignore_errors=True)
                raise

        return directory.name

    def change(
        self,
        bakeoff_id: str,
        title: Any = None,
        task: Any = None,
        data: Any = None,
        limit: Any = None,
        described: Any = None,
    ) -> None:
        """Says again what a bake-off is called, what it is for, which data it is run on, what that is, and what it may
        spend. What is left out is left as it was, an empty name of data takes the data away, and saying nothing of what
        the data is takes that away.

        :raises ApiError: If there is no bake-off with this id, nothing is said, what is said is not fit, the limit is
            less than what has been spent, or the methods are being found.
        """
        if title is None and task is None and data is None and limit is None and described is None:
            raise ApiError(
                422, "invalid", "Say what to change: the title, the task, the data, what the data is, or the limit"
            )
        said = bakeoff_scope.check_described(described) if described is not None else None
        with self._lock:
            directory, record = self.lookup(bakeoff_id)
            self.check_idle(bakeoff_id)
            if title is not None:
                record = {**record, "title": check_name(title, "A bake-off", kept_bakeoff.MAX_TITLE_CHARS)}
            if task is not None:
                record = {**record, "task": check_task(task)}
            if data is not None:
                chosen = self.check_data(data)
                record = {**record, "data": {"own": chosen} if chosen is not None else None}
            if described is not None:
                record = {**record, "described": said}
            if limit is not None:
                budget = check_budget(limit, "The most it may spend", required=True)
                assert budget is not None
                if budget < record["spent"]:
                    raise ApiError(
                        422,
                        "invalid",
                        f"{money(record['spent'])} has been spent already, so the limit cannot be less than that",
                    )
                record = {**record, "limit": budget}
            kept_bakeoff.keep(directory, record)

    def delete(self, bakeoff_id: str) -> None:
        """Takes a bake-off away. The PaperAgents that were made for its methods stay, as they are of their papers.

        :raises ApiError: If there is no bake-off with this id, or its methods are being found.
        """
        with self._lock:
            directory, _ = self.lookup(bakeoff_id)
            self.check_idle(bakeoff_id)
            shutil.rmtree(directory)

    # The methods in the running

    def add_candidate(self, bakeoff_id: str, paper: dict[str, Any], name: Any = None, repo: Any = None) -> str:
        """Puts a method in the running, by its paper.

        :param paper: Which paper, as a PaperAgent is made of one: its DOI, or a link to it.
        :param name: What the method is called, which may be left out, and is then its DOI or its link.
        :param repo: The address of its code, if the person knows it.
        :raises ApiError: If there is no bake-off with this id, what is given is not fit, a method of this paper is in
            the running already, or there are too many.
        :return: The candidate's id.
        """
        made = check_paper(paper)
        if made["kind"] == "file":
            raise ApiError(422, "invalid", "A method is given by the DOI of its paper or a link to it")
        named = check_name(name, "A method", kept_bakeoff.MAX_NAME_CHARS) if not is_blank(name) else default_title(made)
        code = check_repo(repo) if not is_blank(repo) else None
        candidate = {
            "id": secrets.token_hex(4),
            "name": named[: kept_bakeoff.MAX_NAME_CHARS],
            "paper": made,
            "title": "",
            "repo": code,
            "suggested": [],
            "added_by": kept_bakeoff.BY_PERSON,
            "added_at": utc_timestamp(),
            "found": None,
            "fit": None,
            "build": None,
            "went_on": None,
        }
        with self._lock:
            directory, record = self.lookup(bakeoff_id)
            self.check_unique(record, made)
            if len(record["candidates"]) >= kept_bakeoff.MAX_CANDIDATES:
                raise ApiError(
                    409,
                    "too_many",
                    f"No more than {kept_bakeoff.MAX_CANDIDATES} methods can be in a bake-off. Remove some first",
                )
            kept_bakeoff.keep(directory, {**record, "candidates": [*record["candidates"], candidate]})

        return str(candidate["id"])

    def check_unique(self, record: dict[str, Any], paper: dict[str, Any]) -> None:
        """
        :raises ApiError: If a method of this paper is in the running already, which says which.
        """
        for candidate in record["candidates"]:
            if same_paper(paper, candidate["paper"]):
                raise ApiError(
                    409,
                    "exists",
                    f"A method of that paper is in the running already, {candidate['name']}.",
                    existing=candidate["id"],
                )

    def change_candidate(self, bakeoff_id: str, candidate_id: str, name: Any = None, repo: Any = None) -> None:
        """Says again what a method is called and where its code is. What is left out is left as it was, and an empty
        address takes the code away.

        :raises ApiError: If there is no such bake-off or method, nothing is said, or what is said is not fit.
        """
        if name is None and repo is None:
            raise ApiError(422, "invalid", "Say what to change: the name, or where the code is")
        with self._lock:
            directory, record = self.lookup(bakeoff_id)
            candidates = record["candidates"]
            position = next((index for index, each in enumerate(candidates) if each["id"] == candidate_id), None)
            if position is None:
                raise not_found("method in that bake-off with that id")
            candidate = candidates[position]
            if name is not None:
                candidate = {**candidate, "name": check_name(name, "A method", kept_bakeoff.MAX_NAME_CHARS)}
            if repo is not None:
                code = None if is_blank(repo) else check_repo(repo)
                if code != candidate["repo"]:
                    # What stood in the way of building the method was of the code that it had
                    candidate = {**candidate, "repo": code, "build": None}
            kept_bakeoff.keep(
                directory, {**record, "candidates": [*candidates[:position], candidate, *candidates[position + 1 :]]}
            )

    def remove_candidate(self, bakeoff_id: str, candidate_id: str) -> None:
        """Takes a method out of the running.

        :raises ApiError: If there is no such bake-off or method.
        """
        with self._lock:
            directory, record = self.lookup(bakeoff_id)
            left = [each for each in record["candidates"] if each["id"] != candidate_id]
            if len(left) == len(record["candidates"]):
                raise not_found("method in that bake-off with that id")
            kept_bakeoff.keep(directory, {**record, "candidates": left})
            kept_runs.forget(directory, candidate_id)

    # Going on with a method whose card the data is outside of

    def go_on_with(self, bakeoff_id: str, candidate_id: str, key: Any) -> None:
        """Keeps that the person goes on with a method whose card the data is outside of, as they were shown it. It is
        not going on with the data said otherwise, nor with the card as it says something else, and what is kept is
        only the key of what they were shown.

        :param key: The key of the method's scope, as a page was given it.
        :raises ApiError: If there is no such bake-off or method, the key is not one, the data is not outside the card
            now, or it, or the card, is not as they were shown.
        """
        if not isinstance(key, str) or kept_bakeoff.KEY.fullmatch(key) is None:
            raise ApiError(422, "invalid", "Say what it is that you go on with, by the key that its scope gave")
        agents = self.paperagents.kept()
        with self._lock:
            directory, record = self.lookup(bakeoff_id)
            candidate = self.find_candidate(record, candidate_id)
            found = kept_bakeoff.agent_for(candidate["paper"], agents)
            now = bakeoff_scope.scope_of(
                self.paperagents, record["described"], candidate, found[0] if found is not None else None
            )
            if now["outcome"] != bakeoff_scope.OUTSIDE:
                raise ApiError(
                    409,
                    "not_outside",
                    f"The data is not outside what the card of {candidate['name']} says, so there is nothing to go on "
                    "with",
                )
            if now["key"] != key:
                raise ApiError(
                    409,
                    "changed",
                    "What the data is, or what the card says, is not what you were shown. Look at it again",
                )
            self.keep_candidate(directory, record, {**candidate, "went_on": {"key": key, "at": utc_timestamp()}})

    def take_back(self, bakeoff_id: str, candidate_id: str) -> None:
        """Takes away the person's going on with a method, so that it is not run on data that is outside its card until
        they say so again.

        :raises ApiError: If there is no such bake-off or method.
        """
        with self._lock:
            directory, record = self.lookup(bakeoff_id)
            candidate = self.find_candidate(record, candidate_id)
            self.keep_candidate(directory, record, {**candidate, "went_on": None})

    def find_candidate(self, record: dict[str, Any], candidate_id: str) -> dict[str, Any]:
        """
        :raises ApiError: If there is no method with this id in the bake-off.
        """
        found = next((each for each in record["candidates"] if each["id"] == candidate_id), None)
        if found is None:
            raise not_found("method in that bake-off with that id")

        return found

    def keep_candidate(self, directory: Path, record: dict[str, Any], candidate: dict[str, Any]) -> None:
        """Keeps a method as it is given, in the place that it has in the running. The lock is held."""
        kept_bakeoff.keep(
            directory,
            {
                **record,
                "candidates": [candidate if each["id"] == candidate["id"] else each for each in record["candidates"]],
            },
        )

    # Finding them

    def check_queries(self, queries: Any) -> list[str] | None:
        """The searches that the person gave, made plain, or None if they gave none.

        :raises ApiError: If they are not a list of words, or none of them has a word to search for.
        """
        if queries is None:
            return None
        if not isinstance(queries, list) or not all(isinstance(each, str) for each in queries):
            raise ApiError(422, "invalid", "The searches are a list of what to search for")
        made = shortlisting.plain_queries(queries)
        if not made:
            raise ApiError(422, "invalid", "None of the searches has a word to search for")

        return made

    def asker_of(self, model: str, max_cost: float, usage: MeetingUsage) -> shortlisting.ModelShortlister:
        """What asks the model in the settings to write the searches and to choose, within a limit on what it may cost.

        :raises ApiError: If a key it needs is not set, or its price is not known.
        """
        try:
            return shortlisting.ModelShortlister(
                model, max_cost, self.paperagents.chat_models, self.paperagents.client, usage
            )
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error

    def start_shortlist(self, bakeoff_id: str, queries: Any = None) -> Job:
        """Starts finding the methods of the task in the literature: the searches are written by a model, or are the
        person's, they are run, and a model chooses from what they found, within what is left of the limit. What it
        finds is added to the methods that are in the running, and none is taken away.

        :param queries: The searches to make, up to a few short ones, if the person would rather say than have a model
            write them.
        :raises ApiError: If there is no bake-off with this id, the searches are not fit, a key or a price is missing,
            nothing is left of the limit, what has been spent is not known, there is no room for more methods, or the
            methods are being found.
        """
        self.lookup(bakeoff_id)
        wanted = self.check_queries(queries)
        model = self.paperagents.usable_model()
        with self._lock:
            _, record = self.lookup(bakeoff_id)
            self.check_idle(bakeoff_id)
            if len(record["candidates"]) >= kept_bakeoff.MAX_CANDIDATES:
                raise ApiError(
                    409,
                    "too_many",
                    f"There are {kept_bakeoff.MAX_CANDIDATES} methods in the running, which is as many as there can "
                    "be. Remove some first",
                )
            self.check_money(record)
            left = kept_bakeoff.left_of(record)
            usage = MeetingUsage()
            work = self.shortlister(bakeoff_id, self.asker_of(model, left, usage), usage, wanted)
            try:
                return self.jobs.start(
                    SHORTLIST_JOB,
                    bakeoff_id,
                    f"Finding methods: {record['title']}",
                    work,
                    exclusive=f"bakeoff:{bakeoff_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def shortlister(
        self, bakeoff_id: str, asker: shortlisting.ModelShortlister, usage: MeetingUsage, wanted: list[str] | None
    ) -> Callable[[Job], str]:
        """What a job does to find the methods: finds them and, whatever came of it, adds what it spent to the limit."""

        def work(job: Job) -> str:
            try:
                return self.find_methods(job, bakeoff_id, asker, usage, wanted)
            finally:
                self.settle(bakeoff_id, usage)

        return work

    def describe_data(self, record: dict[str, Any]) -> str | None:
        """What the person says of their data, which is what the Data page says of it, for a model to be told."""
        named = record["data"]["own"] if record["data"] is not None else None
        own = self.paperagents.own_data().get(named) if named is not None else None
        if own is None:
            return None

        return f"{named}: {own['description']}"[: shortlisting.MAX_DATA_CHARS]

    def find_methods(
        self,
        job: Job,
        bakeoff_id: str,
        asker: shortlisting.ModelShortlister,
        usage: MeetingUsage,
        wanted: list[str] | None,
    ) -> str:
        started = utc_timestamp()
        _, record = self.lookup(bakeoff_id)
        task, data = record["task"], self.describe_data(record)
        queries: list[str] = list(wanted or [])
        searched = shortlisting.Searched([])
        chosen = shortlisting.Chosen([])
        stopped_at: str | None = None
        try:
            if wanted is None:
                job.update("Writing the searches")
                written = asker.write(task, data)
                if not written.queries:
                    raise ValueError(written.note or "The model gave no search that could be made.")
                queries = written.queries
            job.log("Searching for: " + "; ".join(queries))
            self.stop_if_asked(job)
            job.update("Searching the literature")
            try:
                searched = shortlisting.search(queries, self.articles, self.preprints)
            except shortlisting.SearchError as error:
                raise ValueError(str(error)) from None
            job.log(f"Found {len(searched.found)} papers to choose from, of {searched.total}")
            self.stop_if_asked(job)
            if searched.found:
                job.update(f"Choosing from {len(searched.found)} papers")
                chosen = asker.choose(task, data, searched.found)
        except asking.LimitReached as error:
            stopped_at = str(error)
        self.stop_if_asked(job)
        notes = [*searched.notes, *([chosen.note] if chosen.note else [])]
        note = stopped_at or chosen.note
        with self._lock:
            directory, record = self.lookup(bakeoff_id)
            candidates = list(record["candidates"])
            dropped = {**dict.fromkeys(kept_bakeoff.DROPPED, 0), **chosen.dropped}
            added = 0
            for choice in chosen.chosen:
                try:
                    paper = check_paper(dict(choice.found.paper))
                except ApiError:
                    notes.append(
                        f"A method whose DOI or link could not be used was left out: {choice.found.title[:80]}"
                    )
                    continue
                if any(same_paper(paper, each["paper"]) for each in candidates):
                    dropped["already"] += 1
                elif len(candidates) >= kept_bakeoff.MAX_CANDIDATES:
                    dropped["no_room"] += 1
                else:
                    candidates.append(self.candidate_of(choice, paper, asker.model))
                    added += 1
            cost, _ = kept_bakeoff.cost_of(usage)
            shortlist = {
                "started_at": started,
                "finished_at": utc_timestamp(),
                "model": asker.model,
                "written_by": "person" if wanted is not None else "model",
                "queries": queries,
                "found": len(searched.found),
                "total": searched.total,
                "chosen": len(chosen.chosen),
                "added": added,
                "dropped": dropped,
                "notes": [each[: kept_bakeoff.MAX_NOTE_CHARS] for each in notes][: kept_bakeoff.MAX_NOTES],
                "complete": note is None,
                "note": note[: kept_bakeoff.MAX_NOTE_CHARS] if note is not None else None,
                "cost": round(cost, 6),
            }
            kept_bakeoff.keep(directory, {**record, "shortlist": shortlist, "candidates": candidates})

        return describe_shortlist(shortlist)

    def stop_if_asked(self, job: Job) -> None:
        if job.stop.is_set():
            raise StoppedError("Stopped. What was found is not kept, and what was spent is.")

    def candidate_of(self, choice: shortlisting.Choice, paper: dict[str, Any], model: str) -> dict[str, Any]:
        """A method that a model chose, as it is kept: with the words of its abstract that were found there, and the
        addresses of code that its abstract has in it, which are suggestions."""
        found = choice.found
        title = kept_bakeoff.printable(found.title)[: shortlisting.MAX_TITLE_CHARS] or default_title(paper)
        suggested = dict.fromkeys(
            address for link in found.links if (address := self.paperagents.as_repo(link)) is not None
        )

        return {
            "id": secrets.token_hex(4),
            "name": title[: kept_bakeoff.MAX_NAME_CHARS],
            "paper": paper,
            "title": title,
            "repo": None,
            "suggested": list(suggested)[: kept_bakeoff.MAX_SUGGESTED],
            "added_by": kept_bakeoff.BY_SEARCH,
            "added_at": utc_timestamp(),
            "found": {
                **found.record(),
                "url": kept_bakeoff.page_of(found.source, found.url),
                "credit": kept_bakeoff.printable(found.credit),
                "venue": kept_bakeoff.printable(found.venue),
            },
            "fit": {"quote": choice.quote, "model": model},
            "build": None,
            "went_on": None,
        }

    def settle(self, bakeoff_id: str, usage: MeetingUsage) -> None:
        """Adds what a step used to what the bake-off has spent, whether the step came to its end or not."""
        with self._lock:
            try:
                directory, record = self.lookup(bakeoff_id)
            except ApiError:
                return
            kept_bakeoff.keep(directory, kept_bakeoff.charge(record, usage))

    def settle_cost(self, bakeoff_id: str, cost: float, known: bool) -> None:
        """Adds what a step spent, as it says, to what the bake-off has spent. It is not known what was spent if the
        step could not say."""
        with self._lock:
            try:
                directory, record = self.lookup(bakeoff_id)
            except ApiError:
                return
            kept_bakeoff.keep(directory, kept_bakeoff.charge_amount(record, cost, known))

    def edit_candidate(
        self, bakeoff_id: str, candidate_id: str, change: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> None:
        """Keeps a method as `change` makes it of what it is now, which is for a step that was started to say what came
        of it. Nothing is kept of a method that was taken out of the running since, or of a bake-off that was taken
        away."""
        with self._lock:
            try:
                directory, record = self.lookup(bakeoff_id)
            except ApiError:
                return
            candidates = [change(each) if each["id"] == candidate_id else each for each in record["candidates"]]
            kept_bakeoff.keep(directory, {**record, "candidates": candidates})

    def candidate(self, bakeoff_id: str, candidate_id: str) -> dict[str, Any] | None:
        """A method as it is kept now, or None if it, or the bake-off, is gone."""
        try:
            _, record = self.lookup(bakeoff_id)
        except ApiError:
            return None

        return next((each for each in record["candidates"] if each["id"] == candidate_id), None)

    # Building them

    def check_ids(self, ids: Any, what: str) -> list[str] | None:
        """The ids of methods that were given, or None if none were.

        :raises ApiError: If they are not a list of ids, each once.
        """
        if ids is None:
            return None
        if not isinstance(ids, list) or not all(isinstance(each, str) for each in ids) or len(set(ids)) != len(ids):
            raise ApiError(422, "invalid", f"{what} are given as a list of the ids of methods, each once")

        return ids

    def start_build(self, bakeoff_id: str, candidates: Any = None, go_on: Any = None) -> Job:
        """Starts building methods: each is given the PaperAgent of its paper, the paper is read for what it says of
        the code, the code is fetched and looked at to see whether it is worth going on with, and, if it is, its
        environment is built, its tutorials are run, and tools are made of what they did. Each step is the
        PaperAgent's own, and one that has been done is not done again. Reading is the only step that is paid for in
        model requests, and it is paid for out of what is left of the limit.

        :param candidates: The ids of the methods to build, or none for all that are not built.
        :param go_on: The ids of methods whose code the look at it said to ask about, and that the person says to go on
            with.
        :raises ApiError: If there is no bake-off or method with these ids, what is given is not fit, Git is not
            installed or Docker is not running, nothing is left to build, a method to go on with is not one that was
            asked about, a key or a price is missing, nothing is left of the limit for reading the papers that are
            not read, or the methods of the bake-off are being found or built.
        """
        self.lookup(bakeoff_id)
        wanted = self.check_ids(candidates, "The methods to build")
        approved = self.check_ids(go_on, "The methods to go on with") or []
        if shutil.which("git") is None:
            raise ApiError(422, "git_missing", "Git is not installed on this machine, and fetching code takes it")
        usable, problem = building.ready(self.paperagents.docker_command)
        if not usable:
            raise ApiError(422, "docker_missing", problem or "Docker is not running, and building takes it")

        with self._lock:
            directory, record = self.lookup(bakeoff_id)
            self.check_idle(bakeoff_id)
            agents = self.paperagents.kept()
            known = {each["id"]: each for each in record["candidates"]}
            for each in (*(wanted or []), *approved):
                if each not in known:
                    raise not_found("method in that bake-off with that id")
            asked = list(known) if wanted is None else wanted
            chosen = [each for each in asked if not self.is_built(known[each], agents)]
            if not chosen:
                raise ApiError(
                    409,
                    "nothing_to_build",
                    "There is no method in the running to build, or each of those asked for is built already",
                )
            commits = {each: self.commit_asked_about(known[each], agents) for each in approved}
            for each, commit in commits.items():
                if each not in chosen or commit is None:
                    raise ApiError(
                        409,
                        "not_asking",
                        f"{known[each]['name']} is not waiting for you to go on with it: looking at its code did not "
                        "find things to ask you about, or it is not one of those to build",
                    )
            unread = [each for each in chosen if not self.is_read(known[each], agents)]
            if unread:
                self.paperagents.usable_model()
                if len(unread) == len(chosen):
                    self.check_money(record)
            # What the person said is kept before the work starts, which looks for it from its first moment on and
            # does not take this lock to do so
            if commits:
                kept_bakeoff.keep(
                    directory,
                    {
                        **record,
                        "candidates": [
                            {**each, "build": {**each["build"], "go_on": commits[each["id"]]}}
                            if each["id"] in commits
                            else each
                            for each in record["candidates"]
                        ],
                    },
                )
            try:
                job = self.jobs.start(
                    BUILD_JOB,
                    bakeoff_id,
                    f"Building the methods: {record['title']}",
                    self.builder.work(bakeoff_id, chosen),
                    exclusive=f"bakeoff:{bakeoff_id}",
                )
            except JobConflictError as error:
                if commits:
                    kept_bakeoff.keep(directory, record)
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

        return job

    # Running them

    def start_run(self, bakeoff_id: str, calls: Any, minutes: Any = None) -> Job:
        """Starts running methods on the person's data: for each, the tool and the arguments that the person says are
        called once, in a container with the data read-only and no network. What comes of each is kept, and so is why a
        method was not run: the data is outside what the card of its paper says and the person has not said to go on
        with it, it is not built, or the call is not as the tool's signature says.

        :param calls: The calls to make, by the id of each method, each with the name of a tool and its arguments.
        :param minutes: The most that one call may take.
        :raises ApiError: If there is no bake-off or method with these ids, what is given is not fit, Docker is not
            running, the bake-off has no data of the person's to run on or it is not where the Data page says, or its
            methods are being found, built, or run.
        """
        self.lookup(bakeoff_id)
        wanted = self.runs.check_calls(calls)
        seconds = self.runs.check_minutes(minutes)
        usable, problem = building.ready(self.paperagents.docker_command)
        if not usable:
            raise ApiError(422, "docker_missing", problem or "Docker is not running, and running a method takes it")
        with self._lock:
            _, record = self.lookup(bakeoff_id)
            self.check_idle(bakeoff_id)
            if record["data"] is None:
                raise ApiError(
                    422, "no_data", "Say which of your data the methods are run on, on the bake-off, and then run them"
                )
            self.check_data(record["data"]["own"])
            known = {each["id"] for each in record["candidates"]}
            if any(each not in known for each in wanted):
                raise not_found("method in that bake-off with that id")
            try:
                return self.jobs.start(
                    RUN_JOB,
                    bakeoff_id,
                    f"Running the methods: {record['title']}",
                    self.runs.work(bakeoff_id, wanted, seconds),
                    exclusive=f"bakeoff:{bakeoff_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def keep_run(self, bakeoff_id: str, run: dict[str, Any]) -> bool:
        """Keeps what came of running a method, in place of the last run of it. It is not kept if the method, or the
        bake-off, was taken away since the run was started, which is said by the answer.

        :raises ValueError: If it is not a run, which is for whoever made it to say.
        """
        with self._lock:
            try:
                directory, record = self.lookup(bakeoff_id)
            except ApiError:
                return False
            if not any(each["id"] == run["candidate"] for each in record["candidates"]):
                return False
            kept_runs.keep(directory, run)

        return True

    def run_of(self, bakeoff_id: str, candidate_id: str) -> dict[str, Any]:
        """The last run of a method, the whole of it with its result, and whether the data and the method are as they
        were when it was made.

        :raises ApiError: If there is no such bake-off or method, or the method has not been run.
        """
        directory, record = self.lookup(bakeoff_id)
        candidate = self.find_candidate(record, candidate_id)
        run = kept_runs.load(directory, candidate_id)
        if run is None:
            raise not_found("run of that method")
        named = record["data"]["own"] if record["data"] is not None else None
        found = kept_bakeoff.agent_for(candidate["paper"], self.paperagents.kept())

        return {**run, "since": kept_runs.since(run, self.data_now(named), self.runs.method_now(found))}

    def check_money(self, record: dict[str, Any]) -> None:
        """
        :raises ApiError: If nothing is left of the limit to ask a model with, or what has been spent is not known.
        """
        if not record["cost_known"]:
            raise ApiError(
                409,
                "cost_unknown",
                "A response did not say what it used, so what has been spent is not known and the limit cannot be "
                "kept. No more is asked of a model for this bake-off",
            )
        if kept_bakeoff.left_of(record) <= 0:
            raise ApiError(
                409,
                "limit",
                f"The limit on spending, {money(record['limit'])}, has been reached. Raise it to go on",
            )

    def is_built(self, candidate: dict[str, Any], agents: list[tuple[Path, dict[str, Any]]]) -> bool:
        found = kept_bakeoff.agent_for(candidate["paper"], agents)

        return (
            found is not None
            and steps_of(found[1])["tools"] == "done"
            and kept_bakeoff.agrees(candidate["repo"], (found[1].get("repo") or {}).get("url"))
        )

    def is_read(self, candidate: dict[str, Any], agents: list[tuple[Path, dict[str, Any]]]) -> bool:
        found = kept_bakeoff.agent_for(candidate["paper"], agents)

        return found is not None and steps_of(found[1])["reading"] == "done"

    def commit_asked_about(self, candidate: dict[str, Any], agents: list[tuple[Path, dict[str, Any]]]) -> str | None:
        """The commit of the code that a method's building asked the person about, or None if it did not, or the code
        is not what it was asked about of."""
        build = candidate["build"]
        found = kept_bakeoff.agent_for(candidate["paper"], agents)
        if build is None or build["why"] != "ask" or found is None:
            return None
        intake = self.paperagents.repository(found[0])["intake"]

        return str(intake["commit"]) if intake is not None else None


def shortlisting_meaning() -> str:
    """What the candidates that a search found are, and are not, for a page to say beside them."""
    return (
        "A model wrote searches for the task, they were run in Europe PMC and on arXiv, and a model chose, from the "
        "abstracts that were found, the papers that it took to be of a method that does the task, with the words of "
        "the abstract that it went by, which a program checked are there. It is the model's reading of abstracts. It "
        "does not say that a method works, that it works on your data, or that it is the best of those there are, and "
        "its order is not a ranking. A method it left out can be added by its paper. Nothing is fetched or run for a "
        "method until you have said where its code is and asked for it to be built."
    )


def describe_shortlist(shortlist: dict[str, Any]) -> str:
    """What finding the methods came to, in a sentence or two."""
    line = (
        f"Added {shortlist['added']} of the {shortlist['chosen']} methods that the model chose from "
        f"{shortlist['found']} papers, spending {money(shortlist['cost'])}."
    )
    if shortlist["dropped"]["quote"]:
        line += (
            f" {shortlist['dropped']['quote']} choices were thrown away because the words that were quoted are not "
            "in the abstract."
        )
    if shortlist["note"]:
        line += f" {shortlist['note']}"

    return line
