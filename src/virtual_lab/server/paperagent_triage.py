"""Triage of a listing of papers by their code, and what it leaves in the workspace.

A triage is a question put to a list of papers: which of them have code that is worth building first. The papers are
those that a person gives by DOI, with the address of their code if they know it, or the preprints that bioRxiv lists
for a period and a subject, or both. For each, the address of its code is the one that was given, or else the first that
its abstract gives; the code at that address is fetched at one commit, read, and put to the pre-flight, as a
PaperAgent's is, and then taken away again. Nothing is run, no model is asked, and no PaperAgent is made: a paper that
is worth going on with is made into one by the person, with the address that the triage found.

At most so many are looked at, since each is a fetch of code, and the rest that have an address are said to have been
left. It is one job at a time, which can be stopped, and what was looked at before it was stopped is kept.

A triage is kept in triages/ in the workspace as one file of its own, with what it was asked, what was found of each
paper, and the order they are in (see paperagents/triaging.py). A file that is not in the shape that a triage is kept in
is not used, as it may not be if it was edited.
"""

import json
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from virtual_lab import literature, paper_batch
from virtual_lab.constants import BIORXIV_SUBJECTS, MAX_BIORXIV_PAGES
from virtual_lab.environment import StoppedError
from virtual_lab.paperagents import preflight, triaging
from virtual_lab.paperagents import repository as cloning
from virtual_lab.paperagents import stock as stocking
from virtual_lab.provenance import utc_timestamp
from virtual_lab.records import DatabaseError
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.jobs import Job, JobConflictError
from virtual_lab.server.paperagents import PaperAgents, check_doi, check_repo, is_blank
from virtual_lab.server.papers import check_count, check_date
from virtual_lab.server.workspace import has_control_character, read_json
from virtual_lab.utils import write_atomically
from virtual_lab.web import WebRequestError

TRIAGE_JOB = "paperagent-triage"
TRIAGE_ID = re.compile(r"[0-9a-f]{12}")
# What a record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1
STATES = ("running", "done", "stopped", "failed")
MAX_TRIAGES = 20
MAX_RECORD_BYTES = 8 << 20

MOST_GIVEN = 100
DEFAULT_LISTED = 100
MOST_LISTED = 300
DEFAULT_LOOKED_AT = 20
MOST_LOOKED_AT = 40
# What is fetched of one project at most, in megabytes: a triage is a look, and a project larger than this is said to be
DEFAULT_MEGABYTES = 50
MIN_MEGABYTES = 5
MAX_MEGABYTES = 200
# The most abstracts that are looked up, of papers that were given by DOI alone
MOST_LOOKED_UP = 30
MAX_TITLE_CHARS = 300
MAX_ABSTRACT_CHARS = 6000
GIVEN_KEYS = frozenset({"doi", "title", "abstract", "code"})
LISTING_KEYS = frozenset({"since", "until", "subject", "limit"})


def check_given(papers: Any) -> list[dict[str, Any]]:
    """The papers that a person gave, as they are kept: each by its DOI, with what it is called, its abstract, and the
    address of its code, which may be left out. One whose DOI is given before is left out.

    :raises ApiError: If it is not a list of at most so many, or one of them is not fit.
    """
    if not isinstance(papers, list) or len(papers) > MOST_GIVEN:
        raise ApiError(422, "invalid", f"The papers are a list of at most {MOST_GIVEN}")
    found: dict[str, dict[str, Any]] = {}
    for item in papers:
        if not isinstance(item, dict) or not item.get("doi"):
            raise ApiError(422, "invalid", "Each paper is given by its DOI, and may say its title, abstract, and code")
        if extra := sorted(set(item) - GIVEN_KEYS):
            raise ApiError(422, "invalid", f"A paper is given by {', '.join(sorted(GIVEN_KEYS))}, not {extra[0]!r}")
        doi = check_doi(item["doi"])
        texts = []
        for name, most in (("title", MAX_TITLE_CHARS), ("abstract", MAX_ABSTRACT_CHARS)):
            value = item.get(name)
            if value is not None and (
                not isinstance(value, str) or len(value) > most or has_control_character(value.replace("\n", " "))
            ):
                raise ApiError(422, "invalid", f"The {name} of a paper is text of at most {most} characters")
            texts.append((value or "").strip())
        code = None if is_blank(item.get("code")) else check_repo(item["code"])
        found.setdefault(doi, {"doi": doi, "title": texts[0] or doi, "abstract": texts[1], "code": code})

    return list(found.values())


def check_listing(listing: Any) -> dict[str, Any]:
    """What to list of bioRxiv, as it is kept.

    :raises ApiError: If it is not fit.
    """
    if not isinstance(listing, dict) or "since" not in listing:
        raise ApiError(422, "invalid", "A listing says the first day to list the preprints of, as since")
    if extra := sorted(set(listing) - LISTING_KEYS):
        raise ApiError(422, "invalid", f"A listing is given by {', '.join(sorted(LISTING_KEYS))}, not {extra[0]!r}")
    since = check_date(listing["since"], "since")
    until = check_date(listing["until"], "until") if listing.get("until") is not None else None
    if until is not None and until < since:
        raise ApiError(422, "invalid", f"The period ends on {until}, before it begins on {since}")
    subject = listing.get("subject", "all")
    if not isinstance(subject, str) or subject.strip().lower() not in {"all", *BIORXIV_SUBJECTS}:
        raise ApiError(422, "invalid", f'The subject is "all" or one of bioRxiv\'s, not {subject!r}')
    limit = check_count(listing.get("limit", DEFAULT_LISTED), "The number of preprints listed", 1, MOST_LISTED)

    return {
        "since": since.isoformat(),
        "until": until.isoformat() if until is not None else None,
        "subject": subject.strip().lower(),
        "limit": limit,
    }


def is_record(value: Any, triage_id: str) -> bool:
    """Whether what a file holds is a triage's: what it was asked, how it ended, and what was found."""
    return (
        isinstance(value, dict)
        and value.get("schema") == SCHEMA
        and value.get("id") == triage_id
        and value.get("state") in STATES
        and isinstance(value.get("created_at"), str)
        and isinstance(value.get("source"), dict)
        and isinstance(value.get("settings"), dict)
        and isinstance(value.get("entries"), list)
        and isinstance(value.get("counts"), dict)
    )


class Triages:
    """The triages of listings, kept in a workspace.

    :param paperagents: The PaperAgents, which say which addresses are those of code, what the model costs, and where
        jobs are run.
    """

    def __init__(self, paperagents: PaperAgents) -> None:
        self.paperagents = paperagents
        self.workspace = paperagents.workspace
        self.jobs = paperagents.jobs
        # Held while a triage is made and while one is settled, so that two do not undo each other
        self._lock = threading.Lock()

    # What there is

    def path(self, triage_id: str) -> Path:
        return self.workspace.triages_dir / f"{triage_id}.json"

    def load(self, triage_id: str) -> dict[str, Any] | None:
        path = self.path(triage_id)
        if not TRIAGE_ID.fullmatch(triage_id) or path.is_symlink() or not path.is_file():
            return None
        if path.stat().st_size > MAX_RECORD_BYTES:
            return None
        record = read_json(path)

        return record if is_record(record, triage_id) else None

    def kept(self) -> list[dict[str, Any]]:
        """The triages there are, the newest first."""
        root = self.workspace.triages_dir
        found = []
        if root.is_dir():
            for path in root.glob("*.json"):
                record = self.load(path.stem)
                if record is not None:
                    found.append(record)

        return sorted(found, key=lambda record: record["created_at"], reverse=True)

    def lookup(self, triage_id: str) -> dict[str, Any]:
        """:raises ApiError: If there is no triage with this id."""
        record = self.load(triage_id)
        if record is None:
            raise not_found("triage with that id")

        return record

    def running(self, triage_id: str | None = None) -> Job | None:
        """The job that is making a triage, or this one, if one is."""
        return next((job for job in self.jobs.active(TRIAGE_JOB) if triage_id in (None, job.subject)), None)

    def state_of(self, record: dict[str, Any]) -> str:
        """How a triage is: a record that says it is running, and has no job doing it, was interrupted."""
        if record["state"] == "running" and self.running(record["id"]) is None:
            return "interrupted"

        return record["state"]

    def summary(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": record["id"],
            "state": self.state_of(record),
            "created_at": record["created_at"],
            "finished_at": record.get("finished_at"),
            "source": record["source"],
            "counts": record["counts"],
        }

    def describe(self) -> dict[str, Any]:
        """The triages there are, and what a page needs to ask for one."""
        return {
            "triages": [self.summary(record) for record in self.kept()],
            "subjects": list(BIORXIV_SUBJECTS),
            "git": shutil.which("git") is not None,
            "limits": {
                "most_triages": MAX_TRIAGES,
                "most_given": MOST_GIVEN,
                "most_listed": MOST_LISTED,
                "default_listed": DEFAULT_LISTED,
                "most_looked_at": MOST_LOOKED_AT,
                "default_looked_at": DEFAULT_LOOKED_AT,
                "default_megabytes": DEFAULT_MEGABYTES,
                "min_megabytes": MIN_MEGABYTES,
                "max_megabytes": MAX_MEGABYTES,
            },
        }

    def view(self, triage_id: str) -> dict[str, Any]:
        """A triage, with its papers in order and the job that is making it, if one is.

        :raises ApiError: If there is no triage with this id.
        """
        record = self.lookup(triage_id)
        job = self.running(triage_id)

        return {
            **{key: record[key] for key in ("id", "created_at", "finished_at", "source", "settings", "counts")},
            "state": self.state_of(record),
            "note": record.get("note"),
            "entries": record["entries"],
            "job": job.snapshot() if job is not None else None,
            "meaning": triaging.MEANING,
        }

    def delete(self, triage_id: str) -> None:
        """Takes a triage away.

        :raises ApiError: If there is no triage with this id, or it is being made.
        """
        with self._lock:
            self.lookup(triage_id)
            if self.running(triage_id) is not None:
                raise ApiError(409, "busy", "The triage is being made. Stop it first")
            self.path(triage_id).unlink(missing_ok=True)

    # Making one

    def create(
        self, papers: Any = None, listing: Any = None, most_looked_at: Any = None, max_megabytes: Any = None
    ) -> dict[str, Any]:
        """Starts a triage of the papers given, of a listing of bioRxiv, or of both, as a job.

        :param papers: Papers by DOI, each with, if known, its title, abstract, and the address of its code.
        :param listing: What to list of bioRxiv: since, until, subject, and limit.
        :param most_looked_at: The most papers whose code is fetched.
        :param max_megabytes: The most that is fetched of one project, which one that is larger is not looked at for.
        :raises ApiError: If what is given is not fit, nothing is given, Git is not installed, or there are too many
            triages or one is being made.
        :return: The triage, as it is when it begins.
        """
        given = check_given(papers) if papers is not None else []
        asked = check_listing(listing) if listing is not None else None
        if not given and asked is None:
            raise ApiError(422, "invalid", "Give papers to look at, a listing of bioRxiv to look at, or both")
        most = check_count(
            DEFAULT_LOOKED_AT if most_looked_at is None else most_looked_at,
            "The most papers whose code is looked at",
            1,
            MOST_LOOKED_AT,
        )
        megabytes = check_count(
            DEFAULT_MEGABYTES if max_megabytes is None else max_megabytes,
            "The most that is fetched of one project, in megabytes,",
            MIN_MEGABYTES,
            MAX_MEGABYTES,
        )
        if shutil.which("git") is None:
            raise ApiError(422, "git_missing", "Git is not installed on this machine, and fetching code takes it")
        with self._lock:
            if len(self.kept()) >= MAX_TRIAGES:
                raise ApiError(409, "too_many", f"No more than {MAX_TRIAGES} triages are kept. Delete some first")
            triage_id = uuid4().hex[:12]
            record = {
                "schema": SCHEMA,
                "id": triage_id,
                "state": "running",
                "created_at": utc_timestamp(),
                "finished_at": None,
                "source": {"papers": len(given), "listing": asked},
                "settings": {"most_looked_at": most, "max_megabytes": megabytes},
                "counts": triaging.counts_of([]),
                "entries": [],
                "note": None,
            }
            self.save(record)
            try:
                self.jobs.start(
                    TRIAGE_JOB,
                    triage_id,
                    "Looking at the code of a listing of papers",
                    self.worker(triage_id, given, asked, most, megabytes * cloning.MEGABYTE),
                )
            except JobConflictError as error:
                self.path(triage_id).unlink(missing_ok=True)
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

        return self.view(triage_id)

    def save(self, record: dict[str, Any]) -> None:
        self.workspace.triages_dir.mkdir(parents=True, exist_ok=True)
        write_atomically(self.path(record["id"]), json.dumps(record, indent=2).encode("utf-8"))

    def worker(
        self, triage_id: str, given: list[dict[str, Any]], listing: dict[str, Any] | None, most: int, max_bytes: int
    ) -> Any:
        """What the job does: lists, looks, and keeps what it found, whether it ended, was stopped, or failed."""

        def work(job: Job) -> str:
            records: list[dict[str, Any]] = []
            state, note = "failed", None
            try:
                entries = self.entries_of(job, given, listing)
                self.look(job, entries, most, max_bytes, records)
                state = "done"
                found = triaging.counts_of(records)

                return (
                    f"Looked at {found['go'] + found['ask'] + found['no-go']} of {found['papers']} papers: "
                    f"{found['go']} go, {found['ask']} ask, {found['no-go']} no-go."
                )
            except StoppedError:
                state = "stopped"
                raise
            except BaseException as error:
                note = str(error)[:500]
                raise
            finally:
                self.settle(triage_id, state, note, records)

        return work

    def entries_of(self, job: Job, given: list[dict[str, Any]], listing: dict[str, Any] | None) -> list[dict[str, Any]]:
        """The papers to look at: those given, with the abstracts of those that gave none looked up, and then those that
        bioRxiv lists, each paper once."""
        entries = [dict(item) for item in given]
        looked_up = 0
        for item in entries:
            if item["abstract"] or item["code"] is not None or looked_up >= MOST_LOOKED_UP:
                continue
            looked_up += 1
            job.update(f"Looking up the abstract of {item['doi']}")
            try:
                article = literature.get_article(item["doi"])
            except (WebRequestError, DatabaseError, ValueError):
                continue
            item["abstract"] = article.abstract
            if item["title"] == item["doi"] and article.title:
                item["title"] = literature.collapse(article.title)[:MAX_TITLE_CHARS]
        if listing is not None:
            if job.stop.is_set():
                raise StoppedError("Stopped before the listing was read.")
            job.update("Listing the preprints of bioRxiv")
            listed = paper_batch.biorxiv_papers(
                listing["since"],
                listing["until"],
                subject=listing["subject"],
                limit=listing["limit"],
                published_only=False,
                max_pages=MAX_BIORXIV_PAGES,
            )
            seen = {item["doi"].lower() for item in entries}
            for paper in listed:
                if paper.doi.lower() in seen:
                    continue
                seen.add(paper.doi.lower())
                entries.append(
                    {
                        "doi": paper.doi,
                        "title": paper.title or paper.doi,
                        "abstract": paper.abstract,
                        "code": None,
                        "date": paper.date,
                        "category": paper.category,
                    }
                )

        return entries

    def look(
        self, job: Job, entries: list[dict[str, Any]], most: int, max_bytes: int, records: list[dict[str, Any]]
    ) -> None:
        """Looks at the code of each paper that says where it is, up to the most, and adds what was found of every
        paper to the records, which a stop leaves with what was looked at."""
        queued: list[tuple[int, dict[str, Any], str, str | None, list[str]]] = []
        for position, entry in enumerate(entries, 1):
            code, source, others = triaging.choose_code(entry["code"], entry["abstract"], self.paperagents.as_repo)
            if code is None:
                records.append(
                    triaging.unlooked(entry, position, None, None, [], "No address of code was found in the abstract.")
                )
            elif len(queued) >= most:
                records.append(
                    triaging.unlooked(
                        entry, position, code, source, others, f"Beyond the {most} papers whose code is looked at."
                    )
                )
            else:
                queued.append((position, entry, code, source, others))
        price = self.paperagents.priced()
        for number, (position, entry, code, source, others) in enumerate(queued, 1):
            if job.stop.is_set():
                self.leave(queued[number - 1 :], records)
                raise StoppedError("Stopped before the code of every paper was looked at.")
            job.update(f"Looking at the code of {number} of {len(queued)}: {entry['title'][:80]}", looked=number - 1)
            try:
                records.append(self.read_code(job, entry, position, code, source, others, max_bytes, price))
            except StoppedError:
                self.leave(queued[number - 1 :], records)
                raise
        job.update(looked=len(queued))

    @staticmethod
    def leave(
        rest: list[tuple[int, dict[str, Any], str, str | None, list[str]]], records: list[dict[str, Any]]
    ) -> None:
        """Says of the papers that a stop came before that their code was not looked at."""
        for place, item, address, origin, more in rest:
            records.append(
                triaging.unlooked(item, place, address, origin, more, "It was stopped before this paper was reached.")
            )

    def read_code(
        self,
        job: Job,
        entry: dict[str, Any],
        position: int,
        code: str,
        source: str | None,
        others: list[str],
        max_bytes: int,
        price: Any,
    ) -> dict[str, Any]:
        """What was found of one paper's code: it is fetched at one commit, read, put to the pre-flight, and taken away.
        What stops it from being fetched is what is said of the paper."""
        scratch = Path(tempfile.mkdtemp(prefix="triage.", dir=self.workspace.root))
        try:
            fetched = scratch / kept_repository.REPO_DIR
            try:
                cloned = cloning.clone(code, fetched, None, max_bytes, should_stop=job.stop.is_set)
            except cloning.RepositoryTooBigError:
                return triaging.unlooked(
                    entry,
                    position,
                    code,
                    source,
                    others,
                    f"Its code is larger than the {max_bytes >> 20} MB that is fetched.",
                )
            except cloning.RepositoryError as error:
                return triaging.unlooked(
                    entry, position, code, source, others, f"Its code could not be fetched: {error}"[:500]
                )
            stock = stocking.take_stock(fetched)
            checked = preflight.preflight(stock, None, price)

            return triaging.looked(entry, position, code, source, others, cloned.commit, stock, checked)
        finally:
            try:
                kept_repository.remove_tree(scratch)
            except OSError:
                shutil.rmtree(scratch, ignore_errors=True)

    def settle(self, triage_id: str, state: str, note: str | None, records: list[dict[str, Any]]) -> None:
        """Keeps what a triage came to, ranked, and how it ended."""
        with self._lock:
            record = self.load(triage_id)
            if record is None:
                return
            ranked = triaging.rank(records)
            self.save(
                {
                    **record,
                    "state": state,
                    "finished_at": utc_timestamp(),
                    "note": note,
                    "entries": ranked,
                    "counts": triaging.counts_of(ranked),
                }
            )
