"""PaperAgents: a paper, and the code that came with it, made into something the lab can use.

An agent is kept in a directory of its own in the workspace's paperagents/. Its agent.json says which paper it is of
(a DOI, a link, or a file the person uploaded, which is kept beside it in paper/), where the paper's code is, if that is
known, and how far each step of making it has got. The steps are added one at a time: so far the paper can be read,
which is a job that keeps what it finds in the agent's directory.

The paper is how an agent is told from others: one paper is one agent, so a DOI, a link, or a file already in an agent
is refused, with the agent it is in. A paper that is a DOI or a link can have its file put beside it too, since the text
that is read is the file's, and nothing here fetches a paper.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import unquote, urlsplit, urlunsplit

from virtual_lab.chat import describe_size, safe_filename
from virtual_lab.constants import (
    CONSISTENT_TEMPERATURE,
    DEFAULT_PAPER_CHUNK_OVERLAP,
    DEFAULT_PAPER_CHUNK_SIZE,
    MAX_PAPER_CHARS,
    MAX_PAPER_FILE_BYTES,
)
from virtual_lab.environment import StoppedError
from virtual_lab.llm import ModelSource
from virtual_lab.paperagents.anchors import document_from
from virtual_lab.paperagents.reading import READING_VERSION, plan_chunks, read_structure
from virtual_lab.papers import PaperBudgetExceededError, read_paper_pages
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_reading as kept_reading
from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.jobs import Job, JobConflictError, Jobs
from virtual_lab.server.papers import (
    MAX_TITLE_CHARS,
    PAPER_KINDS,
    PAPER_SUFFIXES,
    RUN_ID,
    StopWork,
    check_budget,
    check_flag,
    check_model,
    money,
)
from virtual_lab.server.workspace import Workspace, claim_directory, has_control_character, read_json
from virtual_lab.utils import write_atomically

# What an agent is, and where the paper uploaded to it is kept
AGENT_FILE = "agent.json"
PAPER_DIR = "paper"

# What an agent's record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1

# The job that reads a paper, only one of which is done to an agent at a time
READING_JOB = "paperagent-reading"

MAX_AGENTS = 200
MAX_URL_CHARS = 2000
MAX_DOI_CHARS = 200

# The steps of making an agent, in order, and what each can be. Only pending is used until the steps exist
STEPS = ("reading", "repository", "environment", "data", "tools")
STATUSES = ("pending", "running", "done", "failed", "skipped")

# Where the code of a paper may be, since it is cloned from there later
REPO_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org")

# Where a paper may come from, and what each is told about itself
PAPERS = {
    "doi": ("a DOI", {"doi"}),
    "url": ("a link", {"url"}),
    "file": ("a file that is uploaded", set()),
}

DOI = re.compile(r"10\.[0-9]{4,9}/\S+")
DOI_PREFIX = re.compile(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE)
DOI_HOSTS = ("doi.org", "dx.doi.org")
REPO_SEGMENT = re.compile(r"[A-Za-z0-9_.-]+")
SHA256 = re.compile(r"[0-9a-f]{64}")


def check_doi(text: Any) -> str:
    """A DOI as it is kept, in lower case and without what a link to it begins with.

    :raises ApiError: If it is not one.
    """
    given = text.strip() if isinstance(text, str) else ""
    doi = DOI_PREFIX.sub("", given, count=1).strip()
    if not DOI.fullmatch(doi) or len(doi) > MAX_DOI_CHARS or has_control_character(doi):
        raise ApiError(422, "invalid", f"A DOI is like 10.1038/s41586-020-2649-2, which {given!r} is not")

    return doi.lower()


def split_url(text: Any, what: str) -> tuple[str, str, str, str]:
    """The parts of a web address that was given, if it leads somewhere by http or https and holds no password.

    :raises ApiError: If it is not one.
    """
    given = text.strip() if isinstance(text, str) else ""
    parts = urlsplit("")
    try:
        parts = urlsplit(given)
        host = parts.hostname
        port = parts.port
    except ValueError:
        host = port = None
    problem = None
    if not given or len(given) > MAX_URL_CHARS or has_control_character(given) or re.search(r"\s", given):
        problem = (
            f"{what} is a web address of up to {MAX_URL_CHARS} characters with no spaces, which {given[:80]!r} is not"
        )
    elif parts.scheme.lower() not in ("http", "https") or not host:
        problem = f"{what} is a web address that begins with http:// or https://, not {given[:80]!r}"
    elif parts.username is not None or parts.password is not None:
        problem = f"{what} is a web address without a name and password in it"
    if problem is not None:
        raise ApiError(422, "invalid", problem)

    scheme, netloc = parts.scheme.lower(), parts.netloc.lower()
    if port == {"http": 80, "https": 443}[scheme]:
        netloc = netloc.removesuffix(f":{port}")

    return scheme, netloc, parts.path, parts.query


def check_url(text: Any) -> str:
    """A link to a paper as it is kept: its host in lower case, without a part after #, without the port that its scheme
    has by itself, and without a slash at the end.

    :raises ApiError: If it is not a web address.
    """
    scheme, netloc, path, query = split_url(text, "A link")
    path = path.rstrip("/") or "/"

    return urlunsplit((scheme, netloc, path, query, ""))


def check_repo(text: Any) -> str:
    """The address of a paper's code as it is kept: https, at a host that holds code, to the project and no further.

    :raises ApiError: If it is not one.
    """
    scheme, netloc, path, _ = split_url(text, "The address of the code")
    host = netloc.removeprefix("www.")
    if scheme != "https" or host not in REPO_HOSTS:
        raise ApiError(
            422,
            "invalid",
            f"The code is at an https address on {', '.join(REPO_HOSTS)}, which {str(text)[:80]!r} is not",
        )
    segments = [unquote(part) for part in path.split("/") if part]
    if host == "gitlab.com":
        # GitLab projects can be in groups within groups, and what follows /-/ is a page of the project
        segments = segments[: segments.index("-")] if "-" in segments else segments
    else:
        segments = segments[:2]
    if segments:
        segments[-1] = segments[-1].removesuffix(".git")
    if len(segments) < 2 or not all(REPO_SEGMENT.fullmatch(part) and part not in (".", "..") for part in segments):
        raise ApiError(
            422, "invalid", f"Give the address of the project, like https://{host}/owner/name, not {str(text)[:80]!r}"
        )

    return f"https://{host}/{'/'.join(segments)}"


def is_blank(text: Any) -> bool:
    """Whether the address of code that was given says there is none: it is left out, or is nothing but space."""
    return text is None or (isinstance(text, str) and not text.strip())


def check_paper(paper: dict[str, Any]) -> dict[str, Any]:
    """Which paper an agent is of, as it is kept: what a page sent, made sure of and without what is not for the kind of
    paper it is. A link to a DOI is kept as the DOI.

    :raises ApiError: If the kind is not one there is, something is sent that is not for it, or what is sent is wrong.
    """
    kind = paper.get("kind")
    if kind not in PAPERS:
        raise ApiError(422, "invalid", "A paper is given by its DOI, a link to it, or a file that is uploaded")
    name, allowed = PAPERS[kind]
    given = {key: value for key, value in paper.items() if key != "kind" and value is not None}
    if extra := sorted(set(given) - allowed):
        raise ApiError(422, "invalid", f"{', '.join(extra)} is not asked for when a paper is {name}")
    if kind == "file":
        return {"kind": "file", "file": None}
    if kind == "doi":
        if "doi" not in given:
            raise ApiError(422, "invalid", "Give the DOI of the paper")
        return {"kind": "doi", "doi": check_doi(given["doi"])}
    if "url" not in given:
        raise ApiError(422, "invalid", "Give the link to the paper")
    url = check_url(given["url"])
    host = urlsplit(url).hostname or ""
    if host in DOI_HOSTS:
        return {"kind": "doi", "doi": check_doi(unquote(urlsplit(url).path.lstrip("/")))}

    return {"kind": "url", "url": url}


def default_title(paper: dict[str, Any]) -> str:
    """What an agent is called when it is not told: the DOI, or where the link leads."""
    if paper["kind"] == "doi":
        return paper["doi"]
    parts = urlsplit(paper["url"])

    return f"{parts.hostname}{parts.path.rstrip('/')}"[:MAX_TITLE_CHARS]


def check_title(title: Any, paper: dict[str, Any] | None = None) -> str:
    """What an agent is called, one line, or for a paper that is a link or a DOI what that makes if it is left out.

    :raises ApiError: If it is not fit, or is left out for a paper that is a file.
    """
    named = " ".join(title.split()) if isinstance(title, str) else ""
    if not named and paper is not None and paper["kind"] != "file":
        return default_title(paper)
    if not named or len(named) > MAX_TITLE_CHARS or has_control_character(named):
        raise ApiError(422, "invalid", f"A PaperAgent is called by one to {MAX_TITLE_CHARS} characters, not {title!r}")

    return named


def is_real_directory(path: Path) -> bool:
    """Whether a path is a directory of its own, and not a link to one, which is not followed out of the workspace."""
    return path.is_dir() and not path.is_symlink()


def passes(check: Callable[[Any], Any], value: Any) -> bool:
    """Whether a value is fit by one of the checks above, which is how what was kept is told from what was edited."""
    try:
        check(value)
    except ApiError:
        return False

    return True


def is_agent(value: Any) -> bool:
    """Whether what an agent's file holds is an agent's: a title, when it was made, and which paper it is of, with the
    DOI, link, and address of code that a page is given made sure of again, since the file may have been edited."""
    if not (
        isinstance(value, dict)
        and isinstance(value.get("schema"), int)
        and isinstance(value.get("title"), str)
        and isinstance(value.get("created_at"), str)
        and isinstance(paper := value.get("paper"), dict)
        and paper.get("kind") in PAPERS
    ):
        return False
    if paper["kind"] == "doi" and not passes(check_doi, paper.get("doi")):
        return False
    if paper["kind"] == "url" and not passes(check_url, paper.get("url")):
        return False
    file = paper.get("file")
    if file is not None and not (
        isinstance(file, dict)
        and isinstance(file.get("name"), str)
        and safe_filename(file["name"]) == file["name"]
        and isinstance(file.get("bytes"), int)
        and not isinstance(file["bytes"], bool)
        and isinstance(file.get("sha256"), str)
        and SHA256.fullmatch(file["sha256"])
    ):
        return False
    repo = value.get("repo")

    return repo is None or (isinstance(repo, dict) and passes(check_repo, repo.get("url")))


def steps_of(agent: dict[str, Any]) -> dict[str, str]:
    """How far each step has got: pending for one the record does not say, and for one it says something else of."""
    steps = agent.get("steps")
    steps = steps if isinstance(steps, dict) else {}

    return {step: steps[step] if steps.get(step) in STATUSES else "pending" for step in STEPS}


def same_paper(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Whether two agents are of one paper, which is told by the contents of the file, if both have one, and by the DOI
    or the link."""
    first, second = left.get("file"), right.get("file")
    if first is not None and second is not None and first["sha256"] == second["sha256"]:
        return True
    if left["kind"] != right["kind"] or left["kind"] == "file":
        return False

    return bool(left[left["kind"]] == right[right["kind"]])


class PaperAgents:
    """The PaperAgents, kept in a workspace.

    :param workspace: Where they are kept.
    :param max_upload_bytes: The most bytes of a paper that may be uploaded.
    :param jobs: Where a paper is read, which a page follows. Papers are not read without it.
    :param missing_keys: Says which variables a model's provider needs that are not set.
    :param client: An OpenAI client to read with, which is for tests.
    :param chat_models: The chat models to read with, which is for tests.
    """

    def __init__(
        self,
        workspace: Workspace,
        max_upload_bytes: int,
        jobs: Jobs | None = None,
        missing_keys: Callable[[str], list[str]] | None = None,
        client: Any = None,
        chat_models: ModelSource | None = None,
    ) -> None:
        self.workspace = workspace
        self.max_upload_bytes = min(max_upload_bytes, MAX_PAPER_FILE_BYTES)
        self.jobs = jobs if jobs is not None else Jobs()
        self.missing_keys = missing_keys if missing_keys is not None else (lambda model: [])
        self.client = client
        self.chat_models = chat_models
        # Held from looking for an agent of a paper to keeping the one that is made, so that of two of one paper only
        # one is made, and while a file is put in, an agent is changed, or one is removed
        self._lock = threading.Lock()

    def describe(self) -> dict[str, Any]:
        """Every agent, the latest first, and what a page needs to make one."""
        agents = [self.entry(directory.name, agent) for directory, agent in self.kept()]

        return {
            "agents": sorted(agents, key=lambda agent: (agent["created_at"], agent["id"]), reverse=True),
            "max_agents": MAX_AGENTS,
            "max_paper_bytes": self.max_upload_bytes,
            "suffixes": list(PAPER_SUFFIXES),
            "repo_hosts": list(REPO_HOSTS),
        }

    def kept(self) -> list[tuple[Path, dict[str, Any]]]:
        """The agents there are, each with where it is kept and what its file holds."""
        root = self.workspace.paperagents_dir
        found = []
        if root.is_dir():
            for directory in root.iterdir():
                agent = read_json(directory / AGENT_FILE)
                if RUN_ID.fullmatch(directory.name) and is_real_directory(directory) and is_agent(agent):
                    found.append((directory, agent))

        return found

    def entry(self, agent_id: str, agent: dict[str, Any]) -> dict[str, Any]:
        """An agent as a page shows it, with the step that is being done said to be running."""
        steps = steps_of(agent)
        if self.running(agent_id) is not None:
            steps["reading"] = "running"

        return {
            "id": agent_id,
            "title": agent["title"],
            "created_at": agent["created_at"],
            "paper": agent["paper"],
            "repo": agent.get("repo"),
            "steps": steps,
        }

    def running(self, agent_id: str) -> Job | None:
        """The job that is reading an agent's paper, if one is."""
        return next((job for job in self.jobs.active(READING_JOB) if job.subject == agent_id), None)

    def check_idle(self, agent_id: str) -> None:
        """
        :raises ApiError: If the agent's paper is being read, which what is done to the paper must wait for.
        """
        if (job := self.running(agent_id)) is not None:
            raise ApiError(409, "busy", f"{job.title} is still going. Stop that first", job=job.snapshot())

    def lookup(self, agent_id: str) -> tuple[Path, dict[str, Any]]:
        """Where an agent is kept, and what it is.

        :raises ApiError: If there is no agent with this id.
        """
        directory = self.workspace.paperagents_dir / agent_id
        agent = (
            read_json(directory / AGENT_FILE) if RUN_ID.fullmatch(agent_id) and is_real_directory(directory) else None
        )
        if not is_agent(agent):
            raise not_found("PaperAgent with that id")

        return directory, agent

    def view(self, agent_id: str) -> dict[str, Any]:
        """An agent.

        :raises ApiError: If there is no agent with this id.
        """
        _, agent = self.lookup(agent_id)

        return self.entry(agent_id, agent)

    def check_unique(self, paper: dict[str, Any], besides: str | None = None) -> None:
        """
        :raises ApiError: If another agent is of this paper, which says which.
        """
        for directory, other in self.kept():
            if directory.name != besides and same_paper(paper, other["paper"]):
                raise ApiError(
                    409,
                    "exists",
                    f"There is a PaperAgent for that paper already, {other['title']}.",
                    existing=directory.name,
                )

    def create(self, title: Any, paper: dict[str, Any], repo: Any = None) -> str:
        """Makes an agent of a paper, with nothing done to it yet.

        :param title: What it is called, which may be left out unless the paper is a file.
        :param paper: Which paper, as check_paper takes it.
        :param repo: The address of the paper's code, if it is known.
        :raises ApiError: If what is given is not fit, there is an agent of the paper already, or there are too many.
        :return: Its id.
        """
        kept = check_paper(paper)
        named = check_title(title, kept)
        code = check_repo(repo) if not is_blank(repo) else None
        root = self.workspace.paperagents_dir
        root.mkdir(parents=True, exist_ok=True)

        with self._lock:
            self.check_unique(kept)
            if len(self.kept()) >= MAX_AGENTS:
                raise ApiError(409, "too_many", f"No more than {MAX_AGENTS} PaperAgents can be kept. Delete some first")
            directory = claim_directory(root, named)
            try:
                agent = {
                    "schema": SCHEMA,
                    "title": named,
                    "created_at": utc_timestamp(),
                    "paper": kept,
                    "repo": {"url": code} if code is not None else None,
                    "steps": dict.fromkeys(STEPS, "pending"),
                }
                self.save(directory, agent)
            except BaseException:
                shutil.rmtree(directory, ignore_errors=True)
                raise

        return directory.name

    def save(self, directory: Path, agent: dict[str, Any]) -> None:
        write_atomically(directory / AGENT_FILE, json.dumps(agent, indent=4).encode("utf-8"))

    def change(self, agent_id: str, title: Any = None, repo: Any = None) -> None:
        """Says again what an agent is called, and where its code is. What is left out is left as it was, and an empty
        address takes the code away.

        :raises ApiError: If there is no agent with this id, or what is given is not fit.
        """
        if title is None and repo is None:
            raise ApiError(422, "invalid", "Say what to change: the title, or where the code is")
        with self._lock:
            directory, agent = self.lookup(agent_id)
            if title is not None:
                agent = {**agent, "title": check_title(title)}
            if repo is not None:
                agent = {**agent, "repo": None if is_blank(repo) else {"url": check_repo(repo)}}
            self.save(directory, agent)

    def delete(self, agent_id: str) -> None:
        """Deletes an agent with the paper that was uploaded to it.

        :raises ApiError: If there is no agent with this id, or its paper is being read.
        """
        # With the lock that starting a reading takes, so that one cannot begin in a directory that is being removed
        with self._lock:
            directory, _ = self.lookup(agent_id)
            self.check_idle(agent_id)
            shutil.rmtree(directory)

    def put_paper(self, agent_id: str, name: str, content: BinaryIO) -> None:
        """Keeps the paper that was uploaded to an agent, in place of one that was, with what was read of it taken away.
        What is in it is read as it arrives. An agent whose paper is a DOI or a link keeps the file beside it.

        :param name: What it was called, which may have a path, as a browser sends it.
        :raises ApiError: If there is no agent with this id, the file is not a paper, it is too big, another agent has
            it, or the paper is being read.
        """
        self.lookup(agent_id)
        filename = safe_filename(name)
        if not filename or Path(filename).suffix.lower() not in PAPER_SUFFIXES:
            raise ApiError(422, "invalid", f"{filename or name!r} is not a paper this reads: give {PAPER_KINDS}")

        with tempfile.TemporaryDirectory(prefix="paperagent.", dir=self.workspace.root) as scratch:
            temporary = Path(scratch) / "upload"
            digest = hashlib.sha256()
            size = 0
            with temporary.open("wb") as file:
                while block := content.read(1 << 20):
                    size += len(block)
                    if size > self.max_upload_bytes:
                        raise ApiError(
                            413,
                            "too_large",
                            f"{filename} is larger than the {describe_size(self.max_upload_bytes)} that can be "
                            "uploaded as a paper.",
                        )
                    digest.update(block)
                    file.write(block)
            kept = {"name": filename, "bytes": size, "sha256": digest.hexdigest()}
            with self._lock:
                directory, agent = self.lookup(agent_id)
                self.check_idle(agent_id)
                paper = {**agent["paper"], "file": kept}
                self.check_unique(paper, besides=agent_id)
                self.swap_paper(directory, self.unread(agent, paper), temporary, filename)
                kept_reading.forget(directory)

    def swap_paper(self, directory: Path, agent: dict[str, Any], uploaded: Path, filename: str) -> None:
        """Puts a paper in place of the one an agent had, and saves the agent that says so. The record never names a
        file that is not there: the paper that was is kept aside until the record is saved, and is put back if anything
        fails before then."""
        folder = directory / PAPER_DIR
        staged = directory / f"{PAPER_DIR}.new"
        aside = directory / f"{PAPER_DIR}.old"
        for leftover in (staged, aside):
            shutil.rmtree(leftover, ignore_errors=True)
        staged.mkdir()
        moved = placed = False
        try:
            os.replace(uploaded, staged / filename)
            if folder.is_dir():
                os.replace(folder, aside)
                moved = True
            os.replace(staged, folder)
            placed = True
            self.save(directory, agent)
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)
            if placed:
                shutil.rmtree(folder, ignore_errors=True)
            if moved:
                os.replace(aside, folder)
            raise
        shutil.rmtree(aside, ignore_errors=True)

    def remove_paper(self, agent_id: str) -> None:
        """Takes away the paper that was uploaded to an agent, with what was read of it.

        :raises ApiError: If there is no agent with this id, it has no paper uploaded, or the paper is being read.
        """
        with self._lock:
            directory, agent = self.lookup(agent_id)
            if agent["paper"].get("file") is None:
                raise not_found("paper uploaded to that PaperAgent")
            self.check_idle(agent_id)
            paper = {key: value for key, value in agent["paper"].items() if key != "file"}
            self.save(directory, self.unread(agent, {**paper, "file": None} if paper["kind"] == "file" else paper))
            shutil.rmtree(directory / PAPER_DIR, ignore_errors=True)
            kept_reading.forget(directory)

    def unread(self, agent: dict[str, Any], paper: dict[str, Any]) -> dict[str, Any]:
        """An agent with another paper, and the step of reading it not done."""
        return {**agent, "paper": paper, "steps": {**steps_of(agent), "reading": "pending"}}

    # Reading

    def usable_model(self) -> str:
        """The model in the settings, if what is done with it can be paid for and its spending limited.

        :raises ApiError: If a key it needs is not set, or its price is not known.
        """
        return check_model(self.workspace.load_settings().model, self.missing_keys)

    def reading(self, agent_id: str) -> dict[str, Any]:
        """What has been read of an agent's paper: how far it has got, what it cost, and the claims, the draft of the
        method card, and the resources, each fact with its quote and where in the paper that is.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.lookup(agent_id)
        file = agent["paper"].get("file")
        job = self.running(agent_id)

        return {
            "id": agent_id,
            "has_paper": file is not None,
            "has_text": (directory / PAPER_DIR / kept_reading.TEXT_FILE).is_file(),
            "job": job.snapshot() if job is not None else None,
            **kept_reading.describe(directory, file["sha256"] if file is not None else None),
        }

    def passage(self, agent_id: str, start: Any, end: Any) -> dict[str, Any]:
        """The words of the paper at a place, with some of what is around them.

        :raises ApiError: If there is no agent with this id, its text has not been read, or the place is not in it.
        """
        directory, _ = self.lookup(agent_id)
        document = kept_reading.load_document(directory / PAPER_DIR)
        if document is None:
            raise not_found("text of that PaperAgent's paper. Read the paper first")
        if any(isinstance(place, bool) or not isinstance(place, int) for place in (start, end)):
            raise ApiError(422, "invalid", "A place in the paper is from one character to another, as whole numbers")
        try:
            return kept_reading.passage(document, start, end)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error

    def clear_reading(self, agent_id: str) -> None:
        """Takes away what was read of an agent's paper, so that it can be read again from the start.

        :raises ApiError: If there is no agent with this id, or its paper is being read.
        """
        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            kept_reading.forget(directory)
            self.save(directory, self.unread(agent, agent["paper"]))

    def read(self, agent_id: str, max_cost: Any, retry_failed: Any = False) -> Job:
        """Starts reading an agent's paper, for the claims in it, the methods and data and software it names, what the
        authors say the method was tested on and where it falls short, and where its code and data are. A reading that
        was stopped carries on from the chunk it stopped at.

        :param max_cost: The most the reading may spend, in USD, which is always said.
        :param retry_failed: Whether to read again the chunks that an earlier reading could not.
        :raises ApiError: If there is no agent with this id, the limit is not an amount, a key or a price is missing,
            the paper has no file, it has been read, or it is being read.
        """
        directory, agent = self.lookup(agent_id)
        budget = check_budget(max_cost, "The most it may spend", required=True)
        again = check_flag(retry_failed, "retry_failed")
        model = self.usable_model()
        file = agent["paper"].get("file")
        if file is None:
            raise ApiError(
                422,
                "invalid",
                "Upload the paper's file first. Only a file is read: a DOI or a link is not fetched.",
            )
        earlier = kept_reading.describe(directory, file["sha256"])
        if (
            earlier["chunks"] is not None
            and earlier["read"] + earlier["skipped"] + earlier["failed"] >= earlier["chunks"]
            and not (again and earlier["failed"])
        ):
            raise ApiError(409, "done", "The paper has been read. Clear the reading to read it again.")

        work = self.reader(agent_id, file, model, budget, again)
        with self._lock:
            # Looked for again, as an agent that was deleted, or whose paper was changed, while the checks above were
            # made has nothing to read, or another paper
            _, current = self.lookup(agent_id)
            if (current["paper"].get("file") or {}).get("sha256") != file["sha256"]:
                raise ApiError(409, "changed", "The paper was changed. Read it again")
            try:
                return self.jobs.start(
                    READING_JOB,
                    agent_id,
                    f"Reading the paper: {agent['title']}",
                    work,
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def reader(
        self, agent_id: str, file: dict[str, Any], model: str, max_cost: float, retry_failed: bool
    ) -> Callable[[Job], str | None]:
        """What a job does to read a paper: reads the file, reads each chunk of its text, and keeps what it shows."""

        def work(job: Job) -> str | None:
            directory = self.workspace.paperagents_dir / agent_id
            state: dict[str, Any] = {"run": None, "error": False}
            try:
                return self.read_paper(job, directory, file, model, max_cost, retry_failed, state)
            except StoppedError:
                raise
            except BaseException:
                state["error"] = True
                raise
            finally:
                self.settle(agent_id, directory, state["run"], state["error"])

        return work

    def read_paper(
        self,
        job: Job,
        directory: Path,
        file: dict[str, Any],
        model: str,
        max_cost: float,
        retry_failed: bool,
        state: dict[str, Any],
    ) -> str:
        if job.stop.is_set():
            raise StoppedError("Stopped before any of the paper was read.")
        job.update("Reading the file")
        pages, paged = read_paper_pages(directory / PAPER_DIR / file["name"])
        document = document_from(pages, paged, MAX_PAPER_CHARS)
        if not document.text.strip():
            raise ValueError("There is no text in the paper to read. A paper that is a scan of pages has none.")
        kept_reading.save_text(directory / PAPER_DIR, document)
        chunks = plan_chunks(document, DEFAULT_PAPER_CHUNK_SIZE, DEFAULT_PAPER_CHUNK_OVERLAP)
        run = {
            "schema": kept_reading.SCHEMA,
            "version": READING_VERSION,
            "file_sha256": file["sha256"],
            "chunk_size": DEFAULT_PAPER_CHUNK_SIZE,
            "chunk_overlap": DEFAULT_PAPER_CHUNK_OVERLAP,
            "chunks": len(chunks),
            "characters": len(document.text),
            "truncated_from": document.truncated_from,
            "started_at": utc_timestamp(),
            "finished_at": None,
        }
        kept_reading.begin_run(directory, run)
        state["run"] = run
        saved = kept_reading.saved_chunks(directory)
        job.update("Reading the paper", chunks=len(chunks), finished=len(saved))

        def before(number: int, total: int) -> None:
            if job.stop.is_set():
                raise StopWork
            line = f"Reading chunk {number} of {total}"
            job.log(line)
            job.update(line)

        def keep(record: dict[str, Any]) -> None:
            kept_reading.save_chunk(directory, record)
            job.update(finished=len(kept_reading.saved_chunks(directory)))

        try:
            reading = read_structure(
                document,
                model,
                saved=saved,
                on_chunk=keep,
                before_chunk=before,
                chunk_size=DEFAULT_PAPER_CHUNK_SIZE,
                chunk_overlap=DEFAULT_PAPER_CHUNK_OVERLAP,
                temperature=CONSISTENT_TEMPERATURE,
                max_cost=max_cost,
                chat_models=self.chat_models,
                client=self.client,
                retry_failed=retry_failed,
            )
        except StopWork:
            raise StoppedError("Stopped. What was read is kept, and reading again carries on from there.") from None
        except PaperBudgetExceededError as error:
            done = len(kept_reading.saved_chunks(directory))

            return (
                f"Stopped at the limit: reading has cost {money(error.spent)} of the {money(error.limit)} allowed, "
                f"with {done} of {len(chunks)} chunks read. What was read is kept, and reading again carries on "
                "from there."
            )

        return self.describe_reading(directory, file["sha256"], reading.usage)

    def describe_reading(self, directory: Path, sha256: str, usage: Any) -> str:
        """What a reading found, in a sentence or two."""
        found = kept_reading.describe(directory, sha256)
        facts = len(found["claims"]) + sum(
            len(items) for part in ("card", "resources") for items in found[part].values() if isinstance(items, list)
        )
        try:
            spent: float | None = usage.compute_cost()
        except ValueError:
            spent = None
        line = f"Read {found['read']} of {found['chunks']} chunks and kept {facts} facts, spending {money(spent)}."
        if found["failed"]:
            line += f" {found['failed']} chunks could not be read."
        left_out = found["dropped"]["quote"] + found["dropped"]["detail"]
        if left_out:
            line += f" {left_out} facts were left out because the paper does not bear them out."

        return line

    def settle(self, agent_id: str, directory: Path, run: dict[str, Any] | None, error: bool) -> None:
        """Keeps what a reading found, as the files of the claims, the method card, and the resources, whether it read
        the paper through or not, and says how far the step has got: done if every chunk was read, failed if none could
        be, and pending if it stopped part way and can carry on."""
        results = kept_reading.saved_chunks(directory) if run is not None else {}
        if run is not None and directory.is_dir():
            if results:
                kept_reading.write_files(directory, results)
            kept_reading.end_run(directory, run)
        read = sum(1 for record in results.values() if record["status"] == "read")
        failed = sum(1 for record in results.values() if record["status"] == "failed")
        if run is not None and len(results) >= run["chunks"]:
            status = "failed" if read == 0 and failed else "done"
        else:
            status = "failed" if error and read == 0 else "pending"
        with self._lock:
            try:
                saved, agent = self.lookup(agent_id)
            except ApiError:
                return
            self.save(saved, {**agent, "steps": {**steps_of(agent), "reading": status}})
