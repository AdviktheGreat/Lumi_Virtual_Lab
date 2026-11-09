"""PaperAgents: a paper, and the code that came with it, made into something the lab can use.

An agent is kept in a directory of its own in the workspace's paperagents/. Its agent.json says which paper it is of
(a DOI, a link, or a file the person uploaded, which is kept beside it in paper/), where the paper's code is, if that is
known, and how far each step of making it has got. The steps are added one at a time: so far the paper can be read,
which is a job that keeps what it finds in the agent's directory.

The paper is how an agent is told from others: one paper is one agent, so a DOI, a link, or a file already in an agent
is refused, with the agent it is in. What is read is the text of a file, which a paper that is a DOI or a link can have
put beside it, or, if it has none when it is read, gets by the job that reads it fetching the text: a DOI from Europe
PMC, which holds the papers that are open access, and a link from the public internet. The text that is fetched is kept
as the file, with where it came from, so that the paper is the same to read again and is not fetched twice.

The code of the paper is fetched when the person asks, from the address the agent has for it. The paper's text only
suggests where it is: the person says which, and nothing is fetched from a link in a paper that they have not. It is
fetched at one commit, never run, and taken stock of, and a check says whether it is worth going on with. The check is
worked out again from what was kept each time it is asked for, so that it uses what the paper has been read to say
since.

The environment that the code runs in is built, when the person asks, from the code's own files, in a container that has
none of this machine in it, and is kept as an image in Docker, which is the same each time it is used. It belongs to the
commit it was built from: when the code is taken away, or its address is changed, the image goes with it.
"""

import hashlib
import ipaddress
import json
import os
import re
import shutil
import tempfile
import threading
from collections import deque
from collections.abc import Callable, Sequence
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
from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import fetch as fetching
from virtual_lab.paperagents import preflight as checking
from virtual_lab.paperagents import repository as cloning
from virtual_lab.paperagents import stock as stocking
from virtual_lab.paperagents.anchors import document_from
from virtual_lab.paperagents.reading import READING_VERSION, plan_chunks, read_structure
from virtual_lab.papers import PaperBudgetExceededError, read_paper_pages
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_environment as kept_environment
from virtual_lab.server import paperagent_reading as kept_reading
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.jobs import Job, JobConflictError, Jobs
from virtual_lab.server.papers import (
    MAX_TITLE_CHARS,
    PAPER_KINDS,
    PAPER_SUFFIXES,
    RUN_ID,
    StopWork,
    check_budget,
    check_count,
    check_flag,
    check_model,
    money,
)
from virtual_lab.server.workspace import Workspace, claim_directory, has_control_character, read_json
from virtual_lab.utils import compute_token_cost, write_atomically
from virtual_lab.webpages import is_public_address

# What an agent is, and where the paper uploaded to it is kept
AGENT_FILE = "agent.json"
PAPER_DIR = "paper"

# What an agent's record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1

# The job that reads a paper, only one of which is done to an agent at a time
READING_JOB = "paperagent-reading"
# The job that fetches the code, which is not done to an agent while its paper is being read, nor twice
REPOSITORY_JOB = "paperagent-repository"
# The least that the limit on what is fetched of the code may be set to, in megabytes
MIN_MEGABYTES = 10
# The job that builds the environment, which is not done to an agent while another job is
ENVIRONMENT_JOB = "paperagent-environment"

MAX_AGENTS = 200
MAX_URL_CHARS = 2000
MAX_DOI_CHARS = 200
MAX_SOURCE_CHARS = 300

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
# The endings of names that are for a network of one's own, which a paper is not at
LOCAL_NAME_ENDINGS = (".local", ".localhost", ".localdomain", ".internal", ".intranet", ".lan", ".home.arpa")
# Where a paper that was fetched came from, which is what its source says
SOURCE_KINDS = ("europepmc", "link")
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


def is_local_host(host: str) -> bool:
    """Whether a host is plainly this machine's or a private network's: an address that is not on the public internet,
    a name with no dot in it, or one that ends as the names of a network of one's own do. A name that leads to such an
    address by the DNS is not told by this, and is refused when the page is fetched."""
    name = host.rstrip(".")
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return "." not in name or name.endswith(LOCAL_NAME_ENDINGS)

    return not is_public_address(name)


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
    if is_local_host(host):
        raise ApiError(
            422,
            "invalid",
            f"A link to a paper is to a site on the public internet, which {host} is not. "
            "Upload the paper's file in place of a link to it",
        )

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


def is_source(value: Any) -> bool:
    """Whether what a paper's file says of where it came from, which is nothing for a file that was uploaded, is a
    source: what kind it is, how to say it, and the link to it."""
    return value is None or (
        isinstance(value, dict)
        and value.get("kind") in SOURCE_KINDS
        and isinstance(label := value.get("label"), str)
        and 0 < len(label) <= MAX_SOURCE_CHARS
        and passes(check_url, value.get("url"))
    )


def kept_source(source: dict[str, str], asked: str) -> dict[str, str]:
    """Where fetched text came from, as an agent's record can hold it.

    The address that a page was at after its redirects, or the one Europe PMC gives, may be one that is not kept (a site
    can send a link on to one that is too long), and the address that was asked for is given in its place, so that the
    agent is never one that cannot be read back.
    """
    source = {**source, "label": source["label"][:MAX_SOURCE_CHARS]}

    return source if is_source(source) else {**source, "url": asked}


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
        and is_source(file.get("source"))
    ):
        return False
    repo = value.get("repo")

    return repo is None or (isinstance(repo, dict) and passes(check_repo, repo.get("url")) and is_pin(repo))


def is_pin(repo: dict[str, Any]) -> bool:
    """Whether what an agent's code says of the commit that was fetched is fit: the commit, and what was asked for to
    get it, which are both there or neither."""
    commit, ref = repo.get("commit"), repo.get("ref")
    if commit is None and ref is None:
        return True
    try:
        return (
            isinstance(commit, str)
            and cloning.COMMIT.fullmatch(commit) is not None
            and isinstance(ref, str)
            and cloning.check_ref(ref) == ref
        )
    except cloning.RepositoryError:
        return False


def made_with() -> dict[str, int]:
    """What a reading is made with now, which a reading that was kept must have been made with to be shown as this
    one: the version of what reads, and the sizes the text is cut into chunks of."""
    return {
        "version": READING_VERSION,
        "chunk_size": DEFAULT_PAPER_CHUNK_SIZE,
        "chunk_overlap": DEFAULT_PAPER_CHUNK_OVERLAP,
    }


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
    :param docker_command: How Docker is invoked, which environments are built and kept with.
    """

    def __init__(
        self,
        workspace: Workspace,
        max_upload_bytes: int,
        jobs: Jobs | None = None,
        missing_keys: Callable[[str], list[str]] | None = None,
        client: Any = None,
        chat_models: ModelSource | None = None,
        docker_command: Sequence[str] = ("docker",),
    ) -> None:
        self.docker_command = tuple(docker_command)
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
        if self.cloning(agent_id) is not None:
            steps["repository"] = "running"
        if self.making(agent_id) is not None:
            steps["environment"] = "running"

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

    def cloning(self, agent_id: str) -> Job | None:
        """The job that is fetching an agent's code, if one is."""
        return next((job for job in self.jobs.active(REPOSITORY_JOB) if job.subject == agent_id), None)

    def making(self, agent_id: str) -> Job | None:
        """The job that is building an agent's environment, if one is."""
        return next((job for job in self.jobs.active(ENVIRONMENT_JOB) if job.subject == agent_id), None)

    def check_idle(self, agent_id: str, reading: bool = True) -> None:
        """
        :param reading: Whether a reading of the paper is waited for as well as the fetching of the code.
        :raises ApiError: If the agent's paper is being read, its code fetched, or its environment built, which what is
            done to them must wait for.
        """
        job = (self.running(agent_id) if reading else None) or self.cloning(agent_id) or self.making(agent_id)
        if job is not None:
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
                url = None if is_blank(repo) else check_repo(repo)
                if url != (agent.get("repo") or {}).get("url"):
                    # The code that was fetched is of the address it was fetched from, and is not another's
                    self.check_idle(agent_id, reading=False)
                    self.forget_code(directory)
                    agent = {
                        **agent,
                        "repo": {"url": url} if url is not None else None,
                        "steps": {**steps_of(agent), "repository": "pending", "environment": "pending"},
                    }
            self.save(directory, agent)

    def delete(self, agent_id: str) -> None:
        """Deletes an agent with the paper that was uploaded to it, and the image of its environment.

        :raises ApiError: If there is no agent with this id, its paper is being read, its code fetched, or its
            environment built, or the image of its environment cannot be removed.
        """
        # With the lock that starting a reading takes, so that one cannot begin in a directory that is being removed
        with self._lock:
            directory, _ = self.lookup(agent_id)
            self.check_idle(agent_id)
            self.forget_environment(directory)
            # The code that was fetched is read only, which a platform may not remove without being mended first
            kept_repository.remove_tree(directory)

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
            "fetchable": file is None and agent["paper"]["kind"] != "file",
            "source": file.get("source") if file is not None else None,
            "has_text": (directory / PAPER_DIR / kept_reading.TEXT_FILE).is_file(),
            "job": job.snapshot() if job is not None else None,
            **kept_reading.describe(directory, file["sha256"] if file is not None else None, made_with()),
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
            the paper is a file that was not uploaded, it has been read, or it is being read.
        """
        directory, agent = self.lookup(agent_id)
        budget = check_budget(max_cost, "The most it may spend", required=True)
        again = check_flag(retry_failed, "retry_failed")
        model = self.usable_model()
        file = agent["paper"].get("file")
        if file is None and agent["paper"]["kind"] == "file":
            raise ApiError(422, "no_file", "Upload the paper's file first.")
        if file is not None:
            earlier = kept_reading.describe(directory, file["sha256"], made_with())
            if earlier["complete"] and not (again and earlier["failed"]):
                raise ApiError(409, "done", "The paper has been read. Clear the reading to read it again.")

        work = self.reader(agent_id, file, model, budget, again)
        with self._lock:
            # Looked for again, as an agent that was deleted, or whose paper was changed, while the checks above were
            # made has nothing to read, or another paper
            _, current = self.lookup(agent_id)
            if (current["paper"].get("file") or {}).get("sha256") != (file["sha256"] if file is not None else None):
                raise ApiError(409, "changed", "The paper was changed. Read it again")
            try:
                return self.jobs.start(
                    READING_JOB,
                    agent_id,
                    f"{'Reading' if file is not None else 'Fetching and reading'} the paper: {agent['title']}",
                    work,
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def reader(
        self, agent_id: str, file: dict[str, Any] | None, model: str, max_cost: float, retry_failed: bool
    ) -> Callable[[Job], str | None]:
        """What a job does to read a paper: gets its text if there is no file, reads the file, reads each chunk of its
        text, and keeps what it shows."""

        def work(job: Job) -> str | None:
            directory = self.workspace.paperagents_dir / agent_id
            state: dict[str, Any] = {"run": None, "error": False}
            try:
                kept = file if file is not None else self.fetch_paper(job, agent_id)
                return self.read_paper(job, directory, kept, model, max_cost, retry_failed, state)
            except StoppedError:
                raise
            except BaseException:
                state["error"] = True
                raise
            finally:
                self.settle(agent_id, directory, state["run"], state["error"])

        return work

    def fetch_paper(self, job: Job, agent_id: str) -> dict[str, Any]:
        """Gets the text of a paper that is a DOI or a link, and keeps it as the agent's file, with where it came from.

        :raises PaperUnavailableError: If the paper cannot be had, which says why and asks for its file.
        :return: The file, as the agent's record has it.
        """
        job.update("Fetching the paper")
        _, agent = self.lookup(agent_id)
        paper = agent["paper"]
        if paper["kind"] == "doi":
            asked = f"https://doi.org/{paper['doi']}"
            fetched = fetching.europe_pmc_paper(paper["doi"])
        else:
            asked = paper["url"]
            fetched = fetching.linked_paper(paper["url"])
        if job.stop.is_set():
            raise StoppedError("Stopped before any of the paper was read.")
        content = fetched.text.encode("utf-8")
        if len(content) > self.max_upload_bytes:
            raise fetching.PaperUnavailableError(
                f"The text of the paper is {describe_size(len(content))}, which is more than the "
                f"{describe_size(self.max_upload_bytes)} that is read. {fetching.UPLOAD}"
            )
        file = {
            "name": fetched.name,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "source": kept_source(fetched.source, asked),
        }
        with tempfile.TemporaryDirectory(prefix="paperagent.", dir=self.workspace.root) as scratch:
            temporary = Path(scratch) / "fetched"
            temporary.write_bytes(content)
            with self._lock:
                directory, agent = self.lookup(agent_id)
                kept = {**agent["paper"], "file": file}
                try:
                    self.check_unique(kept, besides=agent_id)
                except ApiError as error:
                    raise fetching.PaperUnavailableError(
                        f"{error.message} Open that PaperAgent in place of making another."
                    ) from None
                self.swap_paper(directory, self.unread(agent, kept), temporary, file["name"])
                kept_reading.forget(directory)
        job.log(f"Fetched {describe_size(len(content))} of text from {fetched.source['label']}")

        return file

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
            **made_with(),
            "file_sha256": file["sha256"],
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
        found = kept_reading.describe(directory, sha256, made_with())
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

    # The code of the paper

    def as_repo(self, address: str) -> str | None:
        """The project that a link in the paper is to, as an agent keeps one, or None if it is to none, or to a page of
        the host that is at an address like a project's."""
        text = re.sub(r"^http://", "https://", address.strip().rstrip(".,;"), flags=re.IGNORECASE)
        try:
            url = check_repo(text if "://" in text else f"https://{text}")
        except ApiError:
            return None

        return url if kept_repository.is_project(urlsplit(url).path.strip("/").split("/")) else None

    def priced(self) -> Callable[[int, int], float]:
        """Prices tokens at the model in the settings, which raises ValueError if its price is not known."""
        model = self.workspace.load_settings().model

        return lambda tokens_in, tokens_out: compute_token_cost(model, tokens_in, tokens_out)

    def repository(self, agent_id: str) -> dict[str, Any]:
        """What there is of an agent's code: where it is said to be, the projects the paper points to for the person to
        choose from, and, once it is fetched, what was found in it and the check of whether to go on. The check is made
        again each time, from what was kept and from what the paper has been read to say.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.lookup(agent_id)
        code = agent.get("repo")
        url = code["url"] if code is not None else None
        intake = kept_repository.load(directory, url)
        file = agent["paper"].get("file")
        reading = kept_reading.describe(directory, file["sha256"] if file is not None else None, made_with())
        job = self.cloning(agent_id)

        return {
            "id": agent_id,
            "repo": code,
            "cloned": intake is not None,
            "intake": (
                {key: intake[key] for key in ("url", "ref", "commit", "cloned_at", "limit_bytes")}
                if intake is not None
                else None
            ),
            "stock": intake["stock"] if intake is not None else None,
            "preflight": (
                checking.preflight(intake["stock"], kept_repository.facts_of_paper(reading), self.priced())
                if intake is not None
                else None
            ),
            "candidates": kept_repository.candidates(reading["resources"], url, self.as_repo),
            "job": job.snapshot() if job is not None else None,
            "git": shutil.which("git") is not None,
            "limits": {
                "default_megabytes": cloning.DEFAULT_MEGABYTES,
                "min_megabytes": MIN_MEGABYTES,
                "max_megabytes": cloning.MAX_MEGABYTES,
            },
        }

    def fetch_repository(self, agent_id: str, repo: Any = None, ref: Any = None, max_megabytes: Any = None) -> Job:
        """Starts fetching an agent's code, at one commit and without running any of it, and taking stock of it.

        :param repo: The address of the code, which is what the person chose if the paper only pointed to it. It is
            kept as the agent's, in place of what the agent had. Left out, the agent's own is fetched.
        :param ref: A branch, a tag, or a commit to fetch, or none for the project's default branch.
        :param max_megabytes: The most to fetch, in megabytes, which the code is refused if it is more than.
        :raises ApiError: If there is no agent with this id, nothing is given or kept to fetch, what is given is not
            fit, Git is not installed, the code has been fetched, or the agent's paper or code is being worked on.
        """
        self.lookup(agent_id)
        megabytes = check_count(
            cloning.DEFAULT_MEGABYTES if max_megabytes is None else max_megabytes,
            "The most that is fetched, in megabytes,",
            MIN_MEGABYTES,
            cloning.MAX_MEGABYTES,
        )
        try:
            asked = cloning.check_ref(ref if ref is None or isinstance(ref, str) else str(ref))
        except cloning.RepositoryError as error:
            raise ApiError(422, "invalid", str(error)) from error
        named = None if is_blank(repo) else check_repo(repo)
        if shutil.which("git") is None:
            raise ApiError(422, "git_missing", "Git is not installed on this machine, and fetching code takes it")

        with self._lock:
            directory, agent = self.lookup(agent_id)
            current = (agent.get("repo") or {}).get("url")
            url = named or current
            if url is None:
                raise ApiError(422, "no_repo", "Say where the code is first")
            self.check_idle(agent_id)
            if url != current:
                self.forget_code(directory)
                agent = {
                    **agent,
                    "repo": {"url": url},
                    "steps": {**steps_of(agent), "repository": "pending", "environment": "pending"},
                }
                self.save(directory, agent)
            elif kept_repository.load(directory, url) is not None:
                raise ApiError(409, "done", "The code has been fetched. Remove it to fetch it again.")
            try:
                return self.jobs.start(
                    REPOSITORY_JOB,
                    agent_id,
                    f"Fetching the code and taking stock of it: {agent['title']}",
                    self.cloner(agent_id, url, asked, megabytes * cloning.MEGABYTE),
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def cloner(self, agent_id: str, url: str, ref: str, max_bytes: int) -> Callable[[Job], str | None]:
        """What a job does to fetch the code: fetches it, takes stock of it, and keeps both."""

        def work(job: Job) -> str | None:
            failed = False
            try:
                return self.take_repository(job, agent_id, url, ref, max_bytes)
            except StoppedError:
                raise
            except BaseException:
                failed = True
                raise
            finally:
                self.settle_repository(agent_id, failed)

        return work

    def take_repository(self, job: Job, agent_id: str, url: str, ref: str, max_bytes: int) -> str:
        job.update("Fetching the code")
        with tempfile.TemporaryDirectory(prefix="paperagent.", dir=self.workspace.root) as scratch:
            fetched = Path(scratch) / kept_repository.REPO_DIR
            cloned = cloning.clone(url, fetched, ref, max_bytes, should_stop=job.stop.is_set)
            job.log(f"Fetched {url} at commit {cloned.commit}")
            job.update("Taking stock of the code")
            stock = stocking.take_stock(fetched)
            if job.stop.is_set():
                raise StoppedError("Stopped before the code was kept.")
            intake = {
                "url": url,
                "ref": cloned.ref,
                "commit": cloned.commit,
                "cloned_at": utc_timestamp(),
                "limit_bytes": max_bytes,
                "stock": stock,
            }
            with self._lock:
                directory, agent = self.lookup(agent_id)
                if (agent.get("repo") or {}).get("url") != url:
                    raise ValueError("The address of the code was changed while it was fetched. Fetch it again.")
                self.forget_environment(directory)
                kept_repository.keep(directory, fetched, intake)
                self.save(
                    directory,
                    {
                        **agent,
                        "repo": {"url": url, "ref": cloned.ref, "commit": cloned.commit},
                        "steps": {**steps_of(agent), "repository": "done", "environment": "pending"},
                    },
                )
        checked = self.repository(agent_id)["preflight"]

        return (
            f"Fetched {describe_size(stock['bytes'])} in {stock['files']:,} files, at commit {cloned.commit[:12]}. "
            f"{checked['summary'] if checked is not None else ''}"
        ).strip()

    def settle_repository(self, agent_id: str, failed: bool) -> None:
        """Says how far the step of fetching the code has got: done if code is kept for the agent's address, failed if
        none is and the fetching failed, and pending if it was only stopped. What was kept before is not lost by a
        fetching that fails."""
        with self._lock:
            try:
                directory, agent = self.lookup(agent_id)
            except ApiError:
                return
            kept = kept_repository.load(directory, (agent.get("repo") or {}).get("url")) is not None
            status = "done" if kept else "failed" if failed else "pending"
            if steps_of(agent)["repository"] != status:
                self.save(directory, {**agent, "steps": {**steps_of(agent), "repository": status}})

    def clear_repository(self, agent_id: str) -> None:
        """Takes away the code that was fetched, and what was found in it, so that it can be fetched again. The address
        stays.

        :raises ApiError: If there is no agent with this id, its paper is being read, its code fetched, or its
            environment built, or the image of its environment cannot be removed.
        """
        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            self.forget_code(directory)
            code = agent.get("repo")
            self.save(
                directory,
                {
                    **agent,
                    "repo": {"url": code["url"]} if code is not None else None,
                    "steps": {**steps_of(agent), "repository": "pending", "environment": "pending"},
                },
            )

    # The environment the code is run in

    def forget_code(self, directory: Path) -> None:
        """Takes away the code that was fetched, and with it what was built from it: the environment is of one commit,
        and is of no use without the code that says what it is.

        :raises ApiError: If the image of the environment cannot be removed.
        """
        self.forget_environment(directory)
        kept_repository.forget(directory)

    def forget_environment(self, directory: Path) -> None:
        """Takes away an agent's environment: its image in Docker, and the account of it. The image is named from the
        agent and the commit, and not from what the file says, so that a file that was edited cannot point at another.

        :raises ApiError: If the image cannot be removed, which is when Docker does not answer. The account is kept,
            so that an image is never left in Docker with nothing to say it is there.
        """
        record = kept_environment.stored(directory)
        if record is not None:
            tag = building.tag_of(directory.name, record["commit"])
            if not building.remove_image(tag, self.docker_command):
                raise ApiError(
                    409,
                    "docker",
                    "The image of the environment could not be removed, as Docker did not answer. Start Docker and try "
                    "again.",
                )
        kept_environment.forget(directory)

    def environment(self, agent_id: str, python: Any = None, system_packages: Any = None) -> dict[str, Any]:
        """What there is of an agent's environment: what would be built from its code and how, if it can be, why not
        if it cannot, what was built and whether the image is still in Docker, and why the last build failed, if it did.

        :param python: A version of Python to plan for, in place of what the code says, to see what it would do.
        :param system_packages: Debian packages to plan to install first.
        :raises ApiError: If there is no agent with this id, or what is asked to be planned is not fit.
        """
        directory, agent = self.lookup(agent_id)
        try:
            version = building.check_python(python)
            packages = building.check_system_packages(system_packages)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error
        code = agent.get("repo")
        intake = kept_repository.load(directory, code["url"] if code is not None else None)
        commit = intake["commit"] if intake is not None else None
        usable, problem = building.ready(self.docker_command)
        recipe: dict[str, Any] | None = None
        unsupported: dict[str, str] | None = None
        if intake is not None:
            try:
                recipe = building.plan(
                    kept_repository.repo_path(directory), intake["stock"], version, packages
                ).to_dict()
            except building.EnvironmentUnsupportedError as error:
                unsupported = {"kind": error.kind, "message": str(error)}
            except ValueError as error:
                raise ApiError(422, "invalid", str(error)) from error
        built = kept_environment.load(directory, commit)
        present = None
        if built is not None and usable:
            present = (
                building.image_id_of(building.tag_of(agent_id, built["commit"]), self.docker_command)
                == (built["image"]["id"])
            )
        failure = kept_environment.load_failure(directory, commit)
        job = self.making(agent_id)

        return {
            "id": agent_id,
            "docker": {"ready": usable, "message": problem},
            "commit": commit,
            "recipe": recipe,
            "unsupported": unsupported,
            "built": {**built, "image_present": present} if built is not None else None,
            "failure": failure,
            "has_log": kept_environment.read_log(directory) is not None,
            "job": job.snapshot() if job is not None else None,
            "limits": {
                "default_minutes": building.DEFAULT_MINUTES,
                "max_minutes": building.MAX_MINUTES,
                "default_gigabytes": building.DEFAULT_GIGABYTES,
                "max_gigabytes": building.MAX_GIGABYTES,
                "memory": building.MEMORY,
                "cpus": building.CPUS,
                "pids": building.PIDS,
            },
            "python_versions": list(building.PYTHON_VERSIONS),
            "max_system_packages": building.MAX_SYSTEM_PACKAGES,
        }

    def build_environment(
        self, agent_id: str, python: Any = None, system_packages: Any = None, minutes: Any = None, gigabytes: Any = None
    ) -> Job:
        """Starts building the environment of an agent's code, from the code's own files, in a container that has none
        of this machine in it, within the time and the disk it is given.

        :param python: A version of Python to build for, in place of what the code says.
        :param system_packages: Debian packages to install first, which a failed build may have said it needs.
        :param minutes: The most time the build may take.
        :param gigabytes: The most disk the build may write.
        :raises ApiError: If there is no agent with this id, what is given is not fit, Docker is not running, the code
            has not been fetched or is not one that is built here, there is an environment already, or the agent's
            paper or code or environment is being worked on.
        """
        self.lookup(agent_id)
        try:
            version = building.check_python(python)
            packages = building.check_system_packages(system_packages)
            limits = building.check_limits(minutes, gigabytes)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error
        usable, problem = building.ready(self.docker_command)
        if not usable:
            raise ApiError(422, "docker_missing", problem or "Docker is not running, and building takes it")

        with self._lock:
            directory, agent = self.lookup(agent_id)
            code = agent.get("repo")
            intake = kept_repository.load(directory, code["url"] if code is not None else None)
            if intake is None:
                raise ApiError(422, "no_code", "Fetch the code first")
            self.check_idle(agent_id)
            if kept_environment.load(directory, intake["commit"]) is not None:
                raise ApiError(409, "done", "The environment has been built. Remove it to build it again.")
            try:
                recipe = building.plan(kept_repository.repo_path(directory), intake["stock"], version, packages)
            except building.EnvironmentUnsupportedError as error:
                raise ApiError(422, "unsupported", str(error), reason=error.kind) from error
            except ValueError as error:
                raise ApiError(422, "invalid", str(error)) from error
            try:
                return self.jobs.start(
                    ENVIRONMENT_JOB,
                    agent_id,
                    f"Building the environment: {agent['title']}",
                    self.maker(agent_id, recipe, limits, intake["commit"], intake["url"]),
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def maker(
        self, agent_id: str, recipe: building.Recipe, limits: building.Limits, commit: str, url: str
    ) -> Callable[[Job], str | None]:
        """What a job does to build an environment: builds it, checks that it runs with no network, and keeps it, or
        keeps why it did not come to one."""

        def work(job: Job) -> str | None:
            failed = False
            try:
                return self.make_environment(job, agent_id, recipe, limits, commit, url)
            except StoppedError:
                raise
            except BaseException:
                failed = True
                raise
            finally:
                self.settle_environment(agent_id, failed)

        return work

    def make_environment(
        self, job: Job, agent_id: str, recipe: building.Recipe, limits: building.Limits, commit: str, url: str
    ) -> str:
        directory = self.workspace.paperagents_dir / agent_id
        tag = building.tag_of(agent_id, commit)
        lines: deque[str] = deque(maxlen=building.KEPT_LOG_LINES)

        def output(line: str) -> None:
            lines.append(line)
            job.log(line)

        job.update("Building the environment")
        # What an earlier build left of itself, which is not an environment that anything says is there
        building.remove_builds(agent_id, self.docker_command)
        building.remove_image(tag, self.docker_command)
        try:
            with tempfile.TemporaryDirectory(prefix="paperagent.", dir=self.workspace.root) as scratch:
                built = building.build_environment(
                    kept_repository.repo_path(directory),
                    recipe,
                    tag,
                    limits,
                    Path(scratch),
                    self.docker_command,
                    output,
                    job.stop,
                    label=agent_id,
                )
        except building.EnvironmentBuildError as error:
            with self._lock:
                try:
                    saved, _ = self.lookup(agent_id)
                except ApiError:
                    saved = None
                if saved is not None:
                    kept_environment.keep_failure(
                        saved,
                        {
                            "schema": kept_environment.SCHEMA,
                            "commit": commit,
                            "failed_at": utc_timestamp(),
                            "recipe": recipe.to_dict(),
                            "limits": limits.to_dict(),
                            "failure": error.failure.to_dict(),
                        },
                        list(lines),
                    )
            raise
        record = {
            "schema": kept_environment.SCHEMA,
            "commit": commit,
            "url": url,
            "built_at": utc_timestamp(),
            "recipe": recipe.to_dict(),
            "limits": limits.to_dict(),
            "image": {
                "tag": built.tag,
                "id": built.image_id,
                "base_id": built.base_id,
                "base_digests": list(built.base_digests),
                "architecture": built.architecture,
                "size_bytes": built.size_bytes,
                "added_bytes": built.added_bytes,
            },
            "python": built.python,
            "lock": {"name": built.lock_name, "packages": built.packages},
            "pip_check": built.pip_check,
            "steps": list(built.steps),
            "duration": built.duration,
        }
        with self._lock:
            try:
                saved, agent = self.lookup(agent_id)
                intake = kept_repository.load(saved, (agent.get("repo") or {}).get("url"))
                if intake is None or intake["commit"] != commit:
                    raise ValueError("The code was changed while the environment was built. Build it again.")
                kept_environment.keep(saved, record, built.lock, list(lines))
            except BaseException:
                building.remove_image(tag, self.docker_command)
                raise

        return (
            f"Built the environment with Python {built.python}: {built.packages} packages in "
            f"{describe_size(built.size_bytes)}, as the image {built.image_id[7:19]}."
        )

    def settle_environment(self, agent_id: str, failed: bool) -> None:
        """Says how far the step of building the environment has got: done if one is kept for the code, failed if
        none is and the build failed, and pending if it was only stopped."""
        with self._lock:
            try:
                directory, agent = self.lookup(agent_id)
            except ApiError:
                return
            intake = kept_repository.load(directory, (agent.get("repo") or {}).get("url"))
            kept = intake is not None and kept_environment.load(directory, intake["commit"]) is not None
            status = "done" if kept else "failed" if failed else "pending"
            if steps_of(agent)["environment"] != status:
                self.save(directory, {**agent, "steps": {**steps_of(agent), "environment": status}})

    def clear_environment(self, agent_id: str) -> None:
        """Takes away an agent's environment, with its image, so that it can be built again, and what was kept of a
        build that failed.

        :raises ApiError: If there is no agent with this id, its paper is being read, its code fetched, or its
            environment built, or the image cannot be removed.
        """
        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            self.forget_environment(directory)
            if steps_of(agent)["environment"] != "pending":
                self.save(directory, {**agent, "steps": {**steps_of(agent), "environment": "pending"}})

    def environment_lock(self, agent_id: str) -> dict[str, str]:
        """The exact versions that were installed in an agent's environment, as the text of a file.

        :raises ApiError: If there is no agent with this id, or it has no environment.
        """
        directory, agent = self.lookup(agent_id)
        code = agent.get("repo")
        intake = kept_repository.load(directory, code["url"] if code is not None else None)
        record = kept_environment.load(directory, intake["commit"] if intake is not None else None)
        if record is None:
            raise not_found("environment of that PaperAgent")

        return {"name": record["lock"]["name"], "text": kept_environment.read_lock(directory, record)}

    def environment_log(self, agent_id: str) -> dict[str, Any]:
        """What the last build of an agent's environment printed, which is kept whether it worked or not.

        :raises ApiError: If there is no agent with this id, or no build has been kept.
        """
        directory, _ = self.lookup(agent_id)
        lines = kept_environment.read_log(directory)
        if lines is None:
            raise not_found("build of that PaperAgent's environment")

        return {"lines": lines}
