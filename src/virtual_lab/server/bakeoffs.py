"""Bake-offs: which method to use for a task, decided by trying the methods of the literature on the person's own data.

A bake-off is kept in a directory of its own in the workspace's bakeoffs/ (paperagent_bakeoff.py). It says what the
person wants done, which of their data it is to be done on, and how much the whole of it may spend, and it has the
methods that are in the running, the candidates. This is the first step of it: finding them.

A model writes a few short searches for the task, a program runs them in Europe PMC and on arXiv, and a model chooses,
from the abstracts that were found, the papers that are of a method that does the task, with the words of the abstract
that it went by, which a program checks are in the abstract (paperagents/shortlisting.py). The candidates that come of
that are the model's reading of abstracts and are shown as that: it is not said that they work, or that they work on
the person's data, or that they are the best there are. The person may add a method that it left out, by its paper, and
may take any away, name them, and say where each one's code is. The address of code that an abstract has in it is only
shown as a suggestion, and nothing is fetched from it, nor from anywhere else, before the person says that it is the
code. Nothing is built or run here, and no PaperAgent is made: those are the steps that follow.

What a model is asked is paid for out of the bake-off's one limit on spending, which is set when it is made and may be
raised, and which is never less than what has been spent.
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
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_bakeoff as kept_bakeoff
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
)
from virtual_lab.server.papers import RUN_ID, check_budget, money
from virtual_lab.server.workspace import claim_directory, has_control_character
from virtual_lab.utils import MeetingUsage

# The job that finds the methods of a task in the literature, which is not done to a bake-off while it is being done
SHORTLIST_JOB = "bakeoff-shortlist"


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


def printable(text: str) -> str:
    """Text without what is not text in it, which a paper's title from a service may have."""
    return " ".join("".join(char if char.isprintable() else " " for char in text).split())


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

    def check_idle(self, bakeoff_id: str) -> None:
        """
        :raises ApiError: If the methods of the bake-off are being found, which what is done to it must wait for.
        """
        job = self.finding(bakeoff_id)
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
        job = self.finding(bakeoff_id)

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
        _, record = self.lookup(bakeoff_id)
        agents = self.paperagents.kept()
        named = record["data"]["own"] if record["data"] is not None else None
        own = self.paperagents.own_data().get(named) if named is not None else None
        job = self.finding(bakeoff_id)

        return {
            **self.summary(bakeoff_id, record),
            "data": (
                {"own": named, "missing": own is None or own["kind"] == "missing", **(own or {})}
                if named is not None
                else None
            ),
            "left": kept_bakeoff.left_of(record),
            "shortlist": record["shortlist"],
            "candidates": [
                {
                    **candidate,
                    "agent": next(
                        (
                            {
                                "id": directory.name,
                                "title": agent["title"],
                                "repo": (agent.get("repo") or {}).get("url"),
                            }
                            for directory, agent in agents
                            if same_paper(candidate["paper"], agent["paper"])
                        ),
                        None,
                    ),
                }
                for candidate in record["candidates"]
            ],
            "job": job.snapshot() if job is not None else None,
            "limits": self.limits(),
            "meaning": shortlisting_meaning(),
            "settings_model": self.workspace.load_settings().model,
        }

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

    def create(self, title: Any, task: Any, data: Any = None, limit: Any = None) -> str:
        """Makes a bake-off, with no methods in it yet.

        :param title: What it is called, which may be left out, and is then made of the task.
        :param task: What the person wants done.
        :param data: The name of the person's own data that the methods are to be run on, if it is known.
        :param limit: The most that the whole of it may spend, in USD, which must be said.
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
                kept_bakeoff.keep(directory, kept_bakeoff.new_record(named, made, chosen, budget))
            except BaseException:
                shutil.rmtree(directory, ignore_errors=True)
                raise

        return directory.name

    def change(self, bakeoff_id: str, title: Any = None, task: Any = None, data: Any = None, limit: Any = None) -> None:
        """Says again what a bake-off is called, what it is for, which data it is run on, and what it may spend. What is
        left out is left as it was, and an empty name of data takes the data away.

        :raises ApiError: If there is no bake-off with this id, nothing is said, what is said is not fit, the limit is
            less than what has been spent, or the methods are being found.
        """
        if title is None and task is None and data is None and limit is None:
            raise ApiError(422, "invalid", "Say what to change: the title, the task, the data, or the limit")
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
                candidate = {**candidate, "repo": None if is_blank(repo) else check_repo(repo)}
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
            if not record["cost_known"]:
                raise ApiError(
                    409,
                    "cost_unknown",
                    "A response did not say what it used, so what has been spent is not known and the limit cannot be "
                    "kept. No more is asked of a model for this bake-off",
                )
            left = kept_bakeoff.left_of(record)
            if left <= 0:
                raise ApiError(
                    409,
                    "limit",
                    f"The limit on spending, {money(record['limit'])}, has been reached. Raise it to go on",
                )
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
        title = printable(found.title)[: shortlisting.MAX_TITLE_CHARS] or default_title(paper)
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
            "found": {**found.record(), "credit": printable(found.record()["credit"])},
            "fit": {"quote": choice.quote, "model": model},
        }

    def settle(self, bakeoff_id: str, usage: MeetingUsage) -> None:
        """Adds what a step used to what the bake-off has spent, whether the step came to its end or not."""
        with self._lock:
            try:
                directory, record = self.lookup(bakeoff_id)
            except ApiError:
                return
            kept_bakeoff.keep(directory, kept_bakeoff.charge(record, usage))


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
