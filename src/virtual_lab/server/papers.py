"""What the researcher has the lab read of papers: the tasks, databases, and software in them, and what they share.

A run is a set of papers, from files uploaded to it, a folder on this machine, or bioRxiv, and what was found in each,
kept in a directory of its own in the workspace's papers/. The reading is the library's: each paper's result is saved as
it is read, so a run that stops, for its budget, a run of failures, or a request to stop, carries on where it stopped
when it is read again. Reading takes minutes or hours, so it is a job, which a page follows and may stop.
"""

import json
import math
import os
import re
import shutil
import tempfile
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, BinaryIO

from virtual_lab.chat import describe_size, safe_filename
from virtual_lab.constants import BIORXIV_SUBJECTS, MAX_BIORXIV_PAGES, MAX_PAPER_FILE_BYTES
from virtual_lab.environment import StoppedError
from virtual_lab.llm import ModelSource
from virtual_lab.paper_batch import (
    FREQUENCY_FILE,
    REPORT_FILE,
    RESULTS_DIR,
    RUN_FILE,
    Paper,
    PaperResult,
    PaperRunReport,
    biorxiv_papers,
    papers_in,
    read_papers,
    saved_results,
)
from virtual_lab.papers import TEXT_SUFFIXES
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.jobs import Job, JobConflictError, Jobs
from virtual_lab.server.workspace import Workspace, has_control_character, read_json, slug
from virtual_lab.utils import CostUnknownError, compute_token_cost, write_atomically

# What a run is, kept beside what the library saves of it, and where the papers uploaded to it are
LAB_FILE = "lab.json"
UPLOADS_DIR = "files"

# The most runs, files uploaded to one, and papers asked of bioRxiv for one
MAX_RUNS = 200
MAX_RUN_FILES = 500
MAX_BIORXIV_LIMIT = 500

MAX_TITLE_CHARS = 200

# The most of each kind of finding a page is shown of a run's counts, the most common first
MAX_SUMMARY_ROWS = 100

# What the papers of a run are counted for
SUMMARY_KINDS = ("tasks", "databases", "software")

PAPER_SUFFIXES = (".pdf", *TEXT_SUFFIXES)
PAPER_KINDS = f"a PDF, or a {', '.join(TEXT_SUFFIXES)} file"

# A run's name is what its title makes, and a number if that is taken, so it is never a place anywhere else
RUN_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Where papers may come from, and what each is told about itself
SOURCES = {
    "files": ("uploaded files", set()),
    "folder": ("a folder on this machine", {"path", "recursive"}),
    "biorxiv": ("bioRxiv", {"since", "until", "subject", "limit", "random", "include_unpublished"}),
}


class StopReading(BaseException):
    """Raised to leave the reading of papers when a request to stop has come. It is not an Exception so that the
    reading of a paper does not take it for that paper's failure and save it as one."""


def money(amount: float | None) -> str:
    return "an amount that cannot be worked out" if amount is None else f"${amount:.4f}"


def describe_report(report: PaperRunReport) -> str:
    """What a run did, in a sentence or two."""
    others = [
        f"{count} {name}" for count, name in ((report.unavailable, "unavailable"), (report.failed, "failed")) if count
    ]
    line = f"Read {report.read} of {report.papers} papers"
    if others:
        line += f" ({', '.join(others)})"
    line += f", spending {money(report.spent)}."
    if report.stopped is not None:
        line += f" Stopped: {report.stopped}"

    return line


def check_flag(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ApiError(422, "invalid", f"{name} is yes or no, not {value!r}")

    return value


def check_folder(text: Any) -> Path:
    """A folder of papers on this machine, from the full path it was given by.

    :raises ApiError: If it is not a full path, or there is no folder there.
    """
    asked_for = text.strip() if isinstance(text, str) else ""
    try:
        asked = Path(asked_for).expanduser()
        if not asked_for or has_control_character(asked_for) or not asked.is_absolute():
            raise ValueError(asked_for)
        where = Path(os.path.abspath(asked))
        there = where.is_dir()
    except (OSError, RuntimeError, ValueError):
        raise ApiError(422, "invalid", f"Give the full path of the folder, which {asked_for!r} is not") from None
    if not there:
        raise ApiError(422, "invalid", f"There is no folder at {where}")

    return where


def check_date(value: Any, what: str) -> date:
    if not isinstance(value, str) or not DATE.fullmatch(value):
        raise ApiError(422, "invalid", f"{what} is a date as YYYY-MM-DD, not {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError(422, "invalid", f"{value} is not a date") from None


def check_source(source: dict[str, Any]) -> dict[str, Any]:
    """Where a run's papers come from, as it is kept: what a page sent, made sure of and without what is not for the
    kind of source it is.

    :raises ApiError: If the kind is not one there is, something is sent that is not for it, or what is sent is wrong.
    """
    kind = source.get("kind")
    if kind not in SOURCES:
        raise ApiError(422, "invalid", "Papers come from files that are uploaded, a folder on this machine, or bioRxiv")
    name, allowed = SOURCES[kind]
    given = {key: value for key, value in source.items() if key != "kind" and value is not None}
    if extra := sorted(set(given) - allowed):
        raise ApiError(422, "invalid", f"{', '.join(extra)} is not asked for when papers come from {name}")
    if kind == "files":
        return {"kind": "files"}
    if kind == "folder":
        where = check_folder(given.get("path"))
        recursive = check_flag(given.get("recursive", False), "recursive")
        try:
            found = papers_in(where, recursive)
        except (OSError, ValueError) as error:
            raise ApiError(422, "invalid", str(error)) from None
        if not found:
            raise ApiError(422, "invalid", f"There are no papers in {where}, which needs {PAPER_KINDS}")

        return {"kind": "folder", "path": str(where), "recursive": recursive}

    if "since" not in given:
        raise ApiError(422, "invalid", "Say the first day of the period to read the preprints of")
    since = check_date(given["since"], "since")
    until = check_date(given["until"], "until") if "until" in given else None
    if until is not None and until < since:
        raise ApiError(422, "invalid", f"The period ends on {until}, before it begins on {since}")
    subject = given.get("subject", "all")
    if not isinstance(subject, str) or subject.strip().lower() not in {"all", *BIORXIV_SUBJECTS}:
        raise ApiError(422, "invalid", f'The subject is "all" or one of bioRxiv\'s, not {subject!r}')
    limit = given.get("limit", 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_BIORXIV_LIMIT:
        raise ApiError(422, "invalid", f"The number of preprints is from 1 to {MAX_BIORXIV_LIMIT}, not {limit!r}")

    return {
        "kind": "biorxiv",
        "since": since.isoformat(),
        "until": until.isoformat() if until is not None else None,
        "subject": subject.strip().lower(),
        "limit": limit,
        "random": check_flag(given.get("random", False), "random"),
        "include_unpublished": check_flag(given.get("include_unpublished", False), "include_unpublished"),
    }


def check_budget(value: Any, what: str, required: bool) -> float | None:
    """What a run may spend, in dollars.

    :raises ApiError: If it is not an amount, zero or more, or is missing when it is required.
    """
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
        raise ApiError(422, "invalid", f"{what} is an amount in dollars, zero or more, not {value!r}")

    return float(value)


def is_lab(value: Any) -> bool:
    """Whether what a run's file holds is a run's: a title, where its papers come from, and when it was made."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("title"), str)
        and isinstance(value.get("created_at"), str)
        and isinstance(value.get("source"), dict)
        and value["source"].get("kind") in SOURCES
    )


def counts_of(result: PaperResult | None) -> dict[str, int]:
    """How many tasks, databases, and software a paper was found to use."""
    findings = result.findings if result is not None and result.status == "read" else None

    return {kind: len(getattr(findings, kind)) if findings is not None else 0 for kind in SUMMARY_KINDS}


class Papers:
    """The runs that read papers, kept in a workspace.

    :param workspace: Where they are kept.
    :param jobs: Where the reading is done, which a page follows.
    :param max_upload_bytes: The most bytes of one file that may be uploaded.
    :param missing_keys: Says which variables a model's provider needs that are not set.
    :param client: An OpenAI client to read with, which is for tests.
    :param chat_models: The chat models to read with, which is for tests.
    """

    def __init__(
        self,
        workspace: Workspace,
        jobs: Jobs,
        max_upload_bytes: int,
        missing_keys: Callable[[str], list[str]],
        client: Any = None,
        chat_models: ModelSource | None = None,
    ) -> None:
        self.workspace = workspace
        self.jobs = jobs
        self.max_upload_bytes = min(max_upload_bytes, MAX_PAPER_FILE_BYTES)
        self.missing_keys = missing_keys
        self.client = client
        self.chat_models = chat_models
        # Held while a file is put among a run's, so that of two with one name only one is
        self._lock = threading.Lock()

    # Runs

    def describe(self) -> dict[str, Any]:
        """Every run, the latest first, and what a page needs to make one."""
        runs = []
        if self.workspace.papers_dir.is_dir():
            for directory in self.workspace.papers_dir.iterdir():
                lab = read_json(directory / LAB_FILE)
                if RUN_ID.fullmatch(directory.name) and directory.is_dir() and is_lab(lab):
                    runs.append(self.entry(directory, lab))

        return {
            "runs": sorted(runs, key=lambda run: (run["created_at"], run["id"]), reverse=True),
            "subjects": list(BIORXIV_SUBJECTS),
            "max_paper_bytes": self.max_upload_bytes,
            "max_files": MAX_RUN_FILES,
            "suffixes": list(PAPER_SUFFIXES),
        }

    def entry(self, directory: Path, lab: dict[str, Any]) -> dict[str, Any]:
        """A run as a list shows it: what it is, where its papers come from, and how far the reading has got."""
        report = read_json(directory / REPORT_FILE)
        report = report if isinstance(report, dict) else {}
        uploaded = self.uploads(directory) if lab["source"]["kind"] == "files" else None
        results_dir = directory / RESULTS_DIR
        job = self.running(directory.name)

        return {
            "id": directory.name,
            "title": lab["title"],
            "source": lab["source"],
            "created_at": lab["created_at"],
            "files": len(uploaded) if uploaded is not None else None,
            "papers": report.get("papers", len(uploaded) if uploaded is not None else None),
            "finished": len(list(results_dir.glob("*.json"))) if results_dir.is_dir() else 0,
            "read": report.get("read"),
            "unavailable": report.get("unavailable"),
            "failed": report.get("failed"),
            "spent": report.get("spent"),
            "stopped": report.get("stopped"),
            "job": job.id if job is not None else None,
        }

    def lookup(self, run_id: str) -> tuple[Path, dict[str, Any]]:
        """Where a run is kept, and what it is.

        :raises ApiError: If there is no run with this id.
        """
        directory = self.workspace.papers_dir / run_id
        lab = read_json(directory / LAB_FILE) if RUN_ID.fullmatch(run_id) else None
        if not is_lab(lab):
            raise not_found("run of papers with that id")

        return directory, lab

    def running(self, run_id: str) -> Job | None:
        """The job that is reading a run, if one is."""
        return next((job for job in self.jobs.active("papers") if job.subject == run_id), None)

    def create(self, title: str, source: dict[str, Any]) -> str:
        """Makes a run with nothing read yet.

        :param title: What it is called.
        :param source: Where its papers come from, as check_source takes it.
        :raises ApiError: If the title or the source is not fit, or there are too many runs.
        :return: Its id.
        """
        named = " ".join(title.split())
        if not named or len(named) > MAX_TITLE_CHARS or has_control_character(named):
            raise ApiError(422, "invalid", f"A run is called by one to {MAX_TITLE_CHARS} characters, not {title!r}")
        kept = check_source(source)
        root = self.workspace.papers_dir
        root.mkdir(parents=True, exist_ok=True)
        if sum(1 for path in root.iterdir() if path.is_dir()) >= MAX_RUNS:
            raise ApiError(409, "too_many", f"No more than {MAX_RUNS} runs can be kept. Delete some first")

        base = slug(named)
        number = 1
        while True:
            # Made, not looked for first: of two requests that begin at once with one name, one makes it and the
            # other takes the next
            directory = root / (base if number == 1 else f"{base}-{number}")
            try:
                directory.mkdir()
            except FileExistsError:
                number += 1
            else:
                break
        try:
            lab = {"title": named, "source": kept, "created_at": utc_timestamp()}
            write_atomically(directory / LAB_FILE, json.dumps(lab, indent=4).encode("utf-8"))
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise

        return directory.name

    def view(self, run_id: str) -> dict[str, Any]:
        """A run, with each of its papers and what the papers share.

        :raises ApiError: If there is no run with this id.
        """
        directory, lab = self.lookup(run_id)
        results = {result.paper.key: result for result in saved_results(directory)}
        listed = self.listed(directory, lab["source"])
        known = {paper.key for paper in listed}
        # What is known to be asked for, and what was read though it is no longer, such as a file taken away
        asked = [*listed, *(result.paper for key, result in results.items() if key not in known)]
        papers = []
        for paper in asked:
            result = results.get(paper.key)
            papers.append(
                {
                    "key": paper.key,
                    "title": paper.title or paper.key,
                    "doi": paper.doi,
                    "status": result.status if result is not None else "pending",
                    **counts_of(result),
                    "cost": result.cost if result is not None else None,
                    "error": result.error if result is not None else None,
                }
            )
        uploads = None
        if lab["source"]["kind"] == "files":
            uploads = [{"name": path.name, "bytes": path.stat().st_size} for path in self.uploads(directory)]

        return {
            **self.entry(directory, lab),
            "uploads": uploads,
            "results": papers,
            "summary": self.summary(directory),
        }

    def listed(self, directory: Path, source: dict[str, Any]) -> list[Paper]:
        """The papers a run asks for that are known without reaching anywhere: those uploaded to it, and those in
        its folder."""
        try:
            if source["kind"] == "files":
                return papers_in(directory / UPLOADS_DIR)
            if source["kind"] == "folder":
                return papers_in(Path(source["path"]), source.get("recursive", False))
        except (OSError, ValueError):
            pass

        return []

    def summary(self, directory: Path) -> dict[str, Any]:
        """What the papers read in a run share, as the library counted when it last read: how many papers, and each
        task, database, and piece of software with the number of papers it is found in, the most common first."""
        counted = read_json(directory / FREQUENCY_FILE)
        counted = counted if isinstance(counted, dict) else {}
        papers = counted.get("papers")
        shown: dict[str, Any] = {"papers": papers if isinstance(papers, int) else 0, "more": {}}
        for kind in SUMMARY_KINDS:
            names = counted.get(kind)
            rows = [
                {"name": name, "papers": number}
                for name, number in (names.items() if isinstance(names, dict) else ())
                if isinstance(name, str) and isinstance(number, int)
            ]
            shown[kind] = rows[:MAX_SUMMARY_ROWS]
            shown["more"][kind] = max(len(rows) - MAX_SUMMARY_ROWS, 0)

        return shown

    def summary_file(self, run_id: str, kind: str) -> Path:
        """The table of what was found, as the library wrote it, for the person to open in a spreadsheet.

        :raises ApiError: If there is no run with this id, the kind is not one, or nothing of it has been found.
        """
        directory, _ = self.lookup(run_id)
        path = directory / f"{kind}_summary.csv"
        if kind not in SUMMARY_KINDS or not path.is_file():
            raise not_found(f"table of {kind} found in that run")

        return path

    def delete(self, run_id: str) -> None:
        """Deletes a run with what was uploaded to it and what was found.

        :raises ApiError: If there is no run with this id, or it is being read.
        """
        # With the lock that starting a read takes, so that a read cannot begin in a directory that is being removed
        with self._lock:
            directory, _ = self.lookup(run_id)
            self.check_idle(run_id)
            shutil.rmtree(directory)

    def check_idle(self, run_id: str) -> None:
        if self.running(run_id) is not None:
            raise ApiError(409, "busy", "Papers are being read in this run. Stop that first")

    # Files

    def uploads(self, directory: Path) -> list[Path]:
        """The papers uploaded to a run, in name order."""
        files = directory / UPLOADS_DIR
        if not files.is_dir():
            return []

        return sorted((path for path in files.iterdir() if path.is_file() and not path.name.startswith(".")), key=str)

    def add_file(self, run_id: str, name: str, content: BinaryIO) -> None:
        """Keeps a paper that was uploaded to a run.

        :param name: What it was called, which may have a path, as a browser sends it.
        :param content: What is in it, read as it arrives.
        :raises ApiError: If there is no run with this id, it does not take uploads or is being read, the file is not
            a paper, its name is taken, there are too many, or it is too big.
        """
        directory, lab = self.lookup(run_id)
        if lab["source"]["kind"] != "files":
            raise ApiError(409, "invalid", "Papers are not uploaded to a run whose papers come from elsewhere")
        self.check_idle(run_id)
        filename = safe_filename(name)
        if not filename or Path(filename).suffix.lower() not in PAPER_SUFFIXES:
            raise ApiError(422, "invalid", f"{filename or name!r} is not a paper this reads: give {PAPER_KINDS}")
        self.check_room(directory, filename)
        files = directory / UPLOADS_DIR
        files.mkdir(exist_ok=True)

        handle, temporary = tempfile.mkstemp(dir=files, prefix=".upload.", suffix=".part")
        try:
            size = 0
            with os.fdopen(handle, "wb") as file:
                while block := content.read(1 << 20):
                    size += len(block)
                    if size > self.max_upload_bytes:
                        raise ApiError(
                            413,
                            "too_large",
                            f"{filename} is larger than the {describe_size(self.max_upload_bytes)} that can be "
                            "uploaded as a paper.",
                        )
                    file.write(block)
            with self._lock:
                self.check_idle(run_id)
                self.check_room(directory, filename)
                os.replace(temporary, files / filename)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def check_room(self, directory: Path, filename: str) -> None:
        taken = {path.name.casefold() for path in self.uploads(directory)}
        if filename.casefold() in taken:
            raise ApiError(
                409,
                "name_taken",
                f"There is a paper named {filename} in this run already. Remove it first, or give this another name.",
            )
        if len(taken) >= MAX_RUN_FILES:
            raise ApiError(409, "too_many", f"No more than {MAX_RUN_FILES} papers can be uploaded to one run")

    def remove_file(self, run_id: str, name: str) -> None:
        """Takes away a paper that was uploaded. What was found in it is kept, and counted, until it is read again.

        :raises ApiError: If there is no run with this id, it is being read, or it has no such paper.
        """
        with self._lock:
            directory, lab = self.lookup(run_id)
            self.check_idle(run_id)
            path = directory / UPLOADS_DIR / name
            if lab["source"]["kind"] != "files" or path.parent != directory / UPLOADS_DIR or not path.is_file():
                raise not_found("paper of that name in the run")
            path.unlink()

    # Reading

    def read(self, run_id: str, max_cost: Any, max_cost_per_paper: Any, retry_failed: Any) -> Job:
        """Starts reading the papers of a run that have not been read, which are all of them the first time. A run
        that stopped carries on from there.

        :param max_cost: The most the reading may spend, in USD, in all.
        :param max_cost_per_paper: The most one paper may spend, or None for no limit on one.
        :param retry_failed: Whether to read again the papers an earlier reading could not.
        :raises ApiError: If there is no run with this id, a limit is not an amount, a key or a price is missing, the
            run was read with another model, there are no papers, or it is being read.
        """
        directory, lab = self.lookup(run_id)
        budget = check_budget(max_cost, "The most it may spend", required=True)
        per_paper = check_budget(max_cost_per_paper, "The most one paper may spend", required=False)
        again = check_flag(retry_failed, "retry_failed")
        model = self.workspace.load_settings().model
        if missing := self.missing_keys(model):
            raise ApiError(
                422,
                "missing_keys",
                f"{model} needs {', '.join(missing)}, which is not set. Add it in the settings.",
                missing=missing,
            )
        try:
            compute_token_cost(model, 0, 0)
        except CostUnknownError as error:
            raise ApiError(422, "unavailable", f"{error}, so a limit on spending cannot be kept") from error
        earlier = read_json(directory / RUN_FILE)
        if isinstance(earlier, dict) and earlier.get("model") not in (None, model):
            raise ApiError(
                409,
                "different_model",
                f"This run was read with {earlier['model']}, and the model in the settings is {model}, whose results "
                "cannot be counted with those. Change the model back to carry on, or read the papers in a new run.",
            )
        if lab["source"]["kind"] == "files" and not self.uploads(directory):
            raise ApiError(422, "invalid", "Upload the papers to read first")

        work = self.reader(directory, lab["source"], model, budget, per_paper, again)
        with self._lock:
            # Looked for again, as a run that was deleted while the checks above were made has no place to read in
            self.lookup(run_id)
            try:
                return self.jobs.start(
                    "papers", run_id, f"Reading papers: {lab['title']}", work, exclusive=f"papers:{run_id}"
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def reader(
        self,
        directory: Path,
        source: dict[str, Any],
        model: str,
        max_cost: float | None,
        max_cost_per_paper: float | None,
        retry_failed: bool,
    ) -> Callable[[Job], str | None]:
        """What a job does to read a run: finds its papers, reads each, and says how it went."""

        def finished() -> int:
            results = directory / RESULTS_DIR

            return len(list(results.glob("*.json"))) if results.is_dir() else 0

        def work(job: Job) -> str | None:
            papers = self.papers_of(directory, source)
            if job.stop.is_set():
                raise StoppedError("Stopped before any paper was read.")
            job.update("Reading the papers", papers=len(papers), finished=finished())
            if not papers:
                return "There are no papers to read."

            def progress(line: str) -> None:
                if job.stop.is_set():
                    raise StopReading
                job.log(line)
                job.update(line.strip(), finished=finished())

            try:
                report = read_papers(
                    papers,
                    directory,
                    model=model,
                    max_cost=max_cost,
                    max_cost_per_paper=max_cost_per_paper,
                    retry_failed=retry_failed,
                    chat_models=self.chat_models,
                    client=self.client,
                    on_progress=progress,
                )
            except StopReading:
                raise StoppedError("Stopped. What was read is kept, and reading again carries on from there.") from None
            job.update(finished=finished())

            return describe_report(report)

        return work

    def papers_of(self, directory: Path, source: dict[str, Any]) -> list[Paper]:
        """The papers a run asks for, which for bioRxiv are listed from bioRxiv's own listing now."""
        if source["kind"] == "files":
            return papers_in(directory / UPLOADS_DIR)
        if source["kind"] == "folder":
            return papers_in(Path(source["path"]), source["recursive"])

        return biorxiv_papers(
            source["since"],
            source["until"],
            subject=source["subject"],
            limit=source["limit"],
            published_only=not source["include_unpublished"],
            random_sample=source["random"],
            max_pages=MAX_BIORXIV_PAGES,
        )
