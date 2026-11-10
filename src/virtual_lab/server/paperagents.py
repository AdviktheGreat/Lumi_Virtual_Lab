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

The data that the paper used is found from what the paper and its code say of where it is: the accessions and links in
them, and what the person adds. Each is a place, with what it holds, which is looked up and shown before anything is
fetched. Files are fetched only when the person says which, and how much may be fetched, from the few places that data
is fetched from and no others, into the agent's data/ with where each came from and its checksum. The person's own
data, from the Data page, can stand in for data that the paper used, which is a note of which and not a copy.

The tutorials and examples of the code are run, when the person asks, in the environment that was built, each in a
container of its own with no network, and what each did is kept in checks/ as the reference run: the calls it made to
the project's own functions, with what went in and came out, and the files it wrote. Each is run more than once, to see
whether the runs agree. The reference run belongs to the environment it was run in: when that goes, it goes. It shows
that the tutorials ran here and what they gave, and does not show that what they gave is right.
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
from virtual_lab.execution import DockerUnavailableError
from virtual_lab.llm import ModelSource
from virtual_lab.paperagents import data as finding
from virtual_lab.paperagents import datahosts as hosting
from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import fetch as fetching
from virtual_lab.paperagents import preflight as checking
from virtual_lab.paperagents import reference as referencing
from virtual_lab.paperagents import repository as cloning
from virtual_lab.paperagents import stock as stocking
from virtual_lab.paperagents.anchors import document_from
from virtual_lab.paperagents.reading import READING_VERSION, plan_chunks, read_structure
from virtual_lab.papers import PaperBudgetExceededError, read_paper_pages
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_data as kept_data
from virtual_lab.server import paperagent_environment as kept_environment
from virtual_lab.server import paperagent_reading as kept_reading
from virtual_lab.server import paperagent_reference as kept_reference
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.jobs import Job, JobConflictError, Jobs
from virtual_lab.server.own import Own
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
# The job that fetches data, which is not done to an agent while another job is
DATA_JOB = "paperagent-data"
# The job that runs the tutorials of an agent's code, which is not done to an agent while another job is
REFERENCE_JOB = "paperagent-reference"
# What is left free on the disk when data is fetched, and the longest that a note of which data stands in for what is
DISK_RESERVE_BYTES = 1 << 30
MAX_DATASET_CHARS = 200
# What each kind of thing that keeps data from being listed or fetched is, as an answer
DATA_STATUSES = {
    "invalid": 422,
    "unsupported": 422,
    "refused": 422,
    "too_big": 422,
    "missing": 404,
    "changed": 409,
    "kept": 409,
}

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


def describe_run(detail: dict[str, Any]) -> str:
    """What came of a tutorial, in a line for a job's log."""
    if detail["failure"] is not None:
        return f"{detail['path']}: {detail['failure']['title'].lower()}"
    agreed = {True: ", and the runs agree", False: ", but the runs do not agree", None: ""}[detail["stable"]]

    return f"{detail['path']}: ran to the end in {detail['seconds']} seconds{agreed}"


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
        if self.downloading(agent_id) is not None:
            steps["data"] = "running"
        if self.reference_job(agent_id) is not None:
            steps["tools"] = "running"

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

    def downloading(self, agent_id: str) -> Job | None:
        """The job that is fetching an agent's data, if one is."""
        return next((job for job in self.jobs.active(DATA_JOB) if job.subject == agent_id), None)

    def reference_job(self, agent_id: str) -> Job | None:
        """The job that is running an agent's tutorials, if one is."""
        return next((job for job in self.jobs.active(REFERENCE_JOB) if job.subject == agent_id), None)

    def check_idle(self, agent_id: str, reading: bool = True) -> None:
        """
        :param reading: Whether a reading of the paper is waited for as well as the fetching of the code.
        :raises ApiError: If the agent's paper is being read, its code fetched, its environment built, its data
            fetched, or its tutorials run, which what is done to them must wait for.
        """
        job = (
            (self.running(agent_id) if reading else None)
            or self.cloning(agent_id)
            or self.making(agent_id)
            or self.downloading(agent_id)
            or self.reference_job(agent_id)
        )
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
        """Deletes an agent with the paper that was uploaded to it, the data fetched for it, and the image of its
        environment.

        :raises ApiError: If there is no agent with this id, its paper is being read, its code fetched, its environment
            built, or its data fetched, or the image of its environment cannot be removed.
        """
        # With the lock that starting a reading takes, so that one cannot begin in a directory that is being removed
        with self._lock:
            directory, _ = self.lookup(agent_id)
            self.check_idle(agent_id)
            self.forget_environment(directory)
            # A container that a build left when the server was stopped hard, which nothing else would take away
            building.remove_builds(directory.name, self.docker_command)
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
        Every image that was built for the agent goes, by the label it carries, so that one is not left behind when the
        account of it is missing or cannot be read, as it is if the server stopped between making the image and
        writing the account.

        :raises ApiError: If an image cannot be removed, which is when Docker does not answer or will not let it go.
            The account is kept, so that an image is never left in Docker with nothing to say it is there.
        """
        record = kept_environment.stored(directory)
        gone = True
        # A container that a run left when the server was stopped hard, which would keep its image from being removed
        referencing.remove_runs(directory.name, self.docker_command)
        if record is not None:
            gone = building.remove_image(building.tag_of(directory.name, record["commit"]), self.docker_command)
        if not (building.remove_images(directory.name, self.docker_command) and gone):
            raise ApiError(
                409,
                "docker",
                "The image of the environment could not be removed. Docker did not answer, or would not let it go, as "
                "something may be using it. Start Docker, stop what uses the image, and try again.",
            )
        kept_environment.forget(directory)
        # What was run in the image is of no use without it
        kept_reference.forget(directory)

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
        building.remove_images(agent_id, self.docker_command)
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
        except (building.EnvironmentBuildError, DockerUnavailableError) as error:
            failure = (
                error.failure
                if isinstance(error, building.EnvironmentBuildError)
                else building.Failure(
                    "docker",
                    "Docker did not do what the build needed",
                    f"{str(error).rstrip('.')}. The build can be asked for again.",
                )
            )
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
                            "failure": failure.to_dict(),
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

    # The tutorials, run to keep what they give as the reference

    def data_to_give(self, directory: Path) -> tuple[Path | None, dict[str, int] | None]:
        """The folder of the data that was fetched, and how much is in it, if there is any, which is what a run is
        given to read."""
        record = kept_data.load(directory)
        present = [
            file for source in record["sources"] for file in source["files"] if kept_data.present(directory, file)
        ]
        folder = kept_data.data_path(directory)
        if not present or folder.is_symlink() or not folder.is_dir():
            return None, None

        return folder, {"files": len(present), "bytes": sum(file["bytes"] for file in present)}

    def reference(self, agent_id: str) -> dict[str, Any]:
        """What there is of the running of an agent's tutorials: which would be run and which would not, with why, what
        a run is given to read, what was kept of the last, and what is allowed.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.lookup(agent_id)
        code = agent.get("repo")
        intake = kept_repository.load(directory, code["url"] if code is not None else None)
        commit = intake["commit"] if intake is not None else None
        usable, problem = building.ready(self.docker_command)
        built = kept_environment.load(directory, commit)
        present = None
        if built is not None and usable:
            present = (
                building.image_id_of(building.tag_of(agent_id, built["commit"]), self.docker_command)
                == built["image"]["id"]
            )
        job = self.reference_job(agent_id)
        _, data = self.data_to_give(directory)

        return {
            "id": agent_id,
            "docker": {"ready": usable, "message": problem},
            "commit": commit,
            "environment": {"built": built is not None, "image_present": present},
            "plan": referencing.plan(intake["stock"]).to_dict() if intake is not None else None,
            "data": data,
            "kept": kept_reference.load(directory, commit, built["image"]["id"] if built is not None else None),
            "job": job.snapshot() if job is not None else None,
            "meaning": referencing.MEANING,
            "limits": {
                "default_minutes": referencing.DEFAULT_MINUTES,
                "max_minutes": referencing.MAX_MINUTES,
                "default_total_minutes": referencing.DEFAULT_TOTAL_MINUTES,
                "max_total_minutes": referencing.MAX_TOTAL_MINUTES,
                "default_tutorials": referencing.DEFAULT_TUTORIALS,
                "max_tutorials": referencing.MAX_TUTORIALS,
                "default_repeats": referencing.DEFAULT_REPEATS,
                "max_repeats": referencing.MAX_REPEATS,
                "default_gigabytes": referencing.DEFAULT_GIGABYTES,
                "max_gigabytes": referencing.MAX_GIGABYTES,
                "memory": building.MEMORY,
                "cpus": building.CPUS,
                "pids": building.PIDS,
            },
        }

    def reference_tutorial(self, agent_id: str, tutorial: str) -> dict[str, Any]:
        """What was kept of one tutorial of the reference run: how it ended, what it printed, the calls it made to the
        project's functions, and the files it wrote.

        :raises ApiError: If there is no agent with this id, or the reference run did not include that tutorial.
        """
        directory, agent = self.lookup(agent_id)
        code = agent.get("repo")
        intake = kept_repository.load(directory, code["url"] if code is not None else None)
        built = kept_environment.load(directory, intake["commit"] if intake is not None else None)
        record = (
            kept_reference.load(directory, intake["commit"], built["image"]["id"])
            if intake is not None and built is not None
            else None
        )
        detail = kept_reference.load_detail(directory, record, tutorial) if record is not None else None
        if detail is None:
            raise not_found("tutorial of that PaperAgent's reference run")

        return detail

    def start_reference(
        self,
        agent_id: str,
        minutes: Any = None,
        total_minutes: Any = None,
        tutorials: Any = None,
        repeats: Any = None,
        gigabytes: Any = None,
        use_data: Any = None,
    ) -> Job:
        """Starts running the tutorials of an agent's code in its environment, each in a container that has none of this
        machine in it and no network, within the time and the disk it is given, and keeping what each did.

        :param minutes: The most time one run of one tutorial may take.
        :param total_minutes: The most time all of the runs may take together.
        :param tutorials: The most tutorials to run.
        :param repeats: How many times each is run, to see whether the runs agree.
        :param gigabytes: The most that one run may write.
        :param use_data: Whether the runs are given the data that was fetched, to read. It is, if it is not said.
        :raises ApiError: If there is no agent with this id, what is given is not fit, Docker is not running, the code
            has not been fetched or its environment not built or its image is not in Docker, there is nothing in the
            code to run, the tutorials have been run, or the agent's paper, code, environment, or data is being worked
            on.
        """
        self.lookup(agent_id)
        try:
            limits = referencing.check_limits(minutes, total_minutes, tutorials, repeats, gigabytes)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error
        give = check_flag(True if use_data is None else use_data, "Whether the runs are given the data")
        usable, problem = building.ready(self.docker_command)
        if not usable:
            raise ApiError(422, "docker_missing", problem or "Docker is not running, and running tutorials takes it")

        with self._lock:
            directory, agent = self.lookup(agent_id)
            code = agent.get("repo")
            intake = kept_repository.load(directory, code["url"] if code is not None else None)
            if intake is None:
                raise ApiError(422, "no_code", "Fetch the code first")
            built = kept_environment.load(directory, intake["commit"])
            if built is None:
                raise ApiError(422, "no_environment", "Build the environment first, as the tutorials run in it")
            self.check_idle(agent_id)
            image_id = built["image"]["id"]
            if building.image_id_of(building.tag_of(agent_id, intake["commit"]), self.docker_command) != image_id:
                raise ApiError(
                    409,
                    "image_missing",
                    "The image of the environment is not in Docker any more. Remove the environment and build it "
                    "again.",
                )
            kept = kept_reference.load(directory, intake["commit"], image_id)
            if kept is not None and kept["complete"]:
                raise ApiError(409, "done", "The tutorials have been run. Remove that to run them again.")
            plan = referencing.plan(intake["stock"])
            if not plan.runnable:
                raise ApiError(
                    422, "no_tutorials", "There is no tutorial in the code that can be run here: only Python is run"
                )
            folder, data = self.data_to_give(directory) if give else (None, None)
            try:
                return self.jobs.start(
                    REFERENCE_JOB,
                    agent_id,
                    f"Running the tutorials: {agent['title']}",
                    self.referrer(agent_id, intake["commit"], image_id, limits, plan, data, folder),
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def referrer(
        self,
        agent_id: str,
        commit: str,
        image_id: str,
        limits: referencing.Limits,
        plan: referencing.Plan,
        data: dict[str, int] | None,
        folder: Path | None,
    ) -> Callable[[Job], str | None]:
        """What a job does to run the tutorials: runs them one after another, and keeps what each came to as it ends,
        so that a run that is stopped keeps what it had done."""

        def work(job: Job) -> str | None:
            failed = False
            try:
                return self.run_tutorials(job, agent_id, commit, image_id, limits, plan, data, folder)
            except StoppedError:
                raise
            except BaseException:
                failed = True
                raise
            finally:
                self.settle_reference(agent_id, failed)

        return work

    def run_tutorials(
        self,
        job: Job,
        agent_id: str,
        commit: str,
        image_id: str,
        limits: referencing.Limits,
        plan: referencing.Plan,
        data: dict[str, int] | None,
        folder: Path | None,
    ) -> str:
        directory = self.workspace.paperagents_dir / agent_id
        job.update("Running the tutorials")
        # What an earlier run left of itself, which only a server that was stopped hard would
        referencing.remove_runs(agent_id, self.docker_command)
        account = {
            "schema": kept_reference.SCHEMA,
            "commit": commit,
            "image_id": image_id,
            "started_at": utc_timestamp(),
            "finished_at": None,
            "complete": False,
            "limits": limits.to_dict(),
            "data": data,
            "tutorials": [],
            "skipped": list(plan.skipped),
            "more": plan.more,
            "not_run": [],
        }
        kept_reference.begin(directory, account)

        def started(item: referencing.Item, number: int, total: int) -> None:
            job.update(f"Running the tutorials: {item.path} ({number} of {total})")
            job.log(f"Running {item.path}")

        def ended(item: referencing.Item, outcome: referencing.Outcome) -> None:
            nonlocal account
            summary = referencing.summary_of(outcome.detail)
            account = kept_reference.keep_tutorial(directory, account, outcome.detail, summary)
            job.log(describe_run(outcome.detail))

        with tempfile.TemporaryDirectory(prefix="paperagent.", dir=self.workspace.root) as scratch:
            runner = referencing.Runner(
                building.tag_of(agent_id, commit),
                limits,
                Path(scratch),
                folder,
                self.docker_command,
                job.stop,
                agent_id,
            )
            not_run = referencing.run_reference(
                runner, plan.runnable, started, ended, lambda item: kept_reference.files_path(directory, item.id)
            )
        kept_reference.finish(directory, account, not_run, utc_timestamp())
        ran = account["tutorials"]
        finished = sum(1 for tutorial in ran if tutorial["status"] == "ok")
        agreed = sum(1 for tutorial in ran if tutorial["stable"] is True)
        left = f" {len(not_run)} were not run." if not_run else ""

        return (
            f"Ran {len(ran)} tutorials: {finished} to the end, {len(ran) - finished} not. "
            f"{agreed} gave the same each time it was run.{left}"
        )

    def settle_reference(self, agent_id: str, failed: bool) -> None:
        """Says how far the step of making tools has got: failed if the running of the tutorials failed, and pending
        if it was done or only stopped, as tools are not made from what it kept yet."""
        with self._lock:
            try:
                directory, agent = self.lookup(agent_id)
            except ApiError:
                return
            status = steps_of(agent)["tools"]
            wanted = "failed" if failed else "pending"
            if status not in ("done", wanted):
                self.save(directory, {**agent, "steps": {**steps_of(agent), "tools": wanted}})

    def clear_reference(self, agent_id: str) -> None:
        """Takes away what was kept of the running of an agent's tutorials, so that they can be run again.

        :raises ApiError: If there is no agent with this id, or its paper is being read, its code fetched, its
            environment built, its data fetched, or its tutorials run.
        """
        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            referencing.remove_runs(agent_id, self.docker_command)
            kept_reference.forget(directory)
            if steps_of(agent)["tools"] == "failed":
                self.save(directory, {**agent, "steps": {**steps_of(agent), "tools": "pending"}})

    # The data that the paper used

    def own_data(self) -> dict[str, dict[str, Any]]:
        """The person's own data, from the Data page, by name: what it is, and whether it is there and how big."""
        own = Own(self.workspace, self.max_upload_bytes)

        return {
            name: {key: shown[key] for key in ("name", "description", "kind", "bytes")}
            for name, entry in self.workspace.load_own()["data"].items()
            for shown in [own.describe_data(name, entry)]
        }

    def data(self, agent_id: str) -> dict[str, Any]:
        """What there is of an agent's data: the datasets the paper names and the places that it and its code point to
        for them, what has been fetched, and the person's own data that stands in for some. Nothing is fetched or asked
        of any host to make this.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.lookup(agent_id)
        code = agent.get("repo")
        intake = kept_repository.load(directory, code["url"] if code is not None else None)
        file = agent["paper"].get("file")
        reading = kept_reading.describe(directory, file["sha256"] if file is not None else None, made_with())
        found = finding.find(
            reading["card"], reading["resources"], intake["stock"]["data"] if intake is not None else None
        )
        record = kept_data.load(directory)
        own = self.own_data()
        stand_ins = {stand_in["key"]: stand_in for stand_in in record["stand_ins"]}
        fetched = {source["key"]: len(source["files"]) for source in record["sources"]}
        job = self.downloading(agent_id)

        return {
            "id": agent_id,
            "read": reading["complete"],
            "datasets": [{**dataset, "stand_in": stand_ins.get(dataset["key"])} for dataset in found["datasets"]],
            "candidates": [
                {**candidate, "fetched": fetched.get(candidate["key"], 0)} for candidate in found["candidates"]
            ],
            "stand_ins": [{**stand_in, "own_data": own.get(stand_in["own"])} for stand_in in record["stand_ins"]],
            "own": list(own.values()),
            "kept": {
                **kept_data.totals(record),
                "sources": [
                    {
                        **source,
                        "files": [{**kept, "present": kept_data.present(directory, kept)} for kept in source["files"]],
                    }
                    for source in record["sources"]
                ],
            },
            "sources": finding.approved(),
            "job": job.snapshot() if job is not None else None,
            "limits": {
                "default_megabytes": finding.DEFAULT_MEGABYTES,
                "min_megabytes": finding.MIN_MEGABYTES,
                "max_megabytes": finding.MAX_MEGABYTES,
                "max_kept_megabytes": finding.MAX_KEPT_MEGABYTES,
                "max_files": finding.MAX_CHOSEN_FILES,
            },
        }

    def list_data(self, reference: Any) -> finding.Listing:
        """What a place has, asked of the place.

        :raises ApiError: If the place is not one that data is fetched from here, cannot be asked, or has no such thing.
        """
        try:
            return hosting.list_files(finding.parse_reference(reference))
        except finding.DataError as error:
            raise data_error(error) from error

    def data_files(self, agent_id: str, reference: Any) -> dict[str, Any]:
        """The files of a place, with how big each is, what it is licensed as, and which are fetched already. Nothing is
        fetched of the files.

        :param reference: An address, a DOI, or an accession.
        :raises ApiError: If there is no agent with this id, or what is asked is not a place that can be listed.
        """
        directory, _ = self.lookup(agent_id)
        listing = self.list_data(reference)
        fetched = kept_data.kept_names(kept_data.load(directory), listing.reference.key)
        shown = listing.to_dict()
        shown["files"] = [{**file, "kept": file["name"] in fetched} for file in shown["files"]]

        return shown

    def download_data(
        self, agent_id: str, reference: Any, files: Any, expected_bytes: Any, max_megabytes: Any = None
    ) -> Job:
        """Starts fetching files of a place that the person has chosen, which is the only way that anything is fetched.
        The place is asked what it has again, so that what is fetched is what it says now and not what a page said, and
        nothing is fetched unless it comes to the size the person was shown.

        :param reference: An address, a DOI, or an accession of a place that data is fetched from.
        :param files: The names of the files, as the place lists them.
        :param expected_bytes: What the files came to when they were shown, which is what was agreed to.
        :param max_megabytes: The most to fetch, in megabytes.
        :raises ApiError: If there is no agent with this id, what is given is not fit, the files are not what was shown,
            are more than the limit, are kept already, or cannot be had, or there is not the room, or the agent is
            being worked on.
        """
        self.lookup(agent_id)
        megabytes = check_count(
            finding.DEFAULT_MEGABYTES if max_megabytes is None else max_megabytes,
            "The most that is fetched, in megabytes,",
            finding.MIN_MEGABYTES,
            finding.MAX_MEGABYTES,
        )
        expected = check_count(
            expected_bytes,
            "The size of the files that were shown, in bytes,",
            0,
            finding.MAX_MEGABYTES * finding.MEGABYTE,
        )
        if not isinstance(files, list) or not all(isinstance(name, str) for name in files):
            raise ApiError(422, "invalid", "Say which files to fetch, by their names")
        listing = self.list_data(reference)

        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            record = kept_data.load(directory)
            try:
                chosen = finding.choose(
                    listing,
                    files,
                    expected,
                    megabytes * finding.MEGABYTE,
                    kept_data.kept_names(record, listing.reference.key),
                )
            except finding.DataError as error:
                raise data_error(error) from error
            self.check_room(record, listing.reference, sum(file.bytes or 0 for file in chosen))
            try:
                return self.jobs.start(
                    DATA_JOB,
                    agent_id,
                    f"Fetching data: {agent['title']}",
                    self.loader(agent_id, listing, chosen),
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def check_room(self, record: dict[str, Any], reference: finding.Reference, total: int) -> None:
        """
        :raises ApiError: If the files of another place are kept under the name this one would be, so that one would be
            written over, if an agent would keep more than it may, or the disk would be left with too little.
        """
        folder = finding.folder_of(reference)
        if any(source["folder"] == folder and source["key"] != reference.key for source in record["sources"]):
            raise ApiError(409, "exists", "The files of another place are kept under the name that this one would have")
        have = kept_data.totals(record)["bytes"]
        most = finding.MAX_KEPT_MEGABYTES * finding.MEGABYTE
        if have + total > most:
            raise ApiError(
                409,
                "too_big",
                f"An agent keeps no more than {describe_size(most)} of data, and {describe_size(have)} is kept. "
                "Remove some first.",
            )
        free = shutil.disk_usage(self.workspace.root).free
        if free < total + DISK_RESERVE_BYTES:
            raise ApiError(
                409,
                "disk_full",
                f"There is not room: these files are {describe_size(total)}, and {describe_size(free)} is free on this "
                f"machine, of which {describe_size(DISK_RESERVE_BYTES)} is left alone.",
            )

    def loader(
        self, agent_id: str, listing: finding.Listing, chosen: list[finding.DataFile]
    ) -> Callable[[Job], str | None]:
        """What a job does to fetch data: fetches each file that was chosen, checks it, and keeps it."""

        def work(job: Job) -> str | None:
            failed = False
            try:
                return self.take_data(job, agent_id, listing, chosen)
            except StoppedError:
                raise
            except BaseException:
                failed = True
                raise
            finally:
                self.settle_data(agent_id, failed)

        return work

    def take_data(self, job: Job, agent_id: str, listing: finding.Listing, chosen: list[finding.DataFile]) -> str:
        reference = listing.reference
        total = sum(file.bytes or 0 for file in chosen)
        kept = 0
        written = 0
        checked = 0
        failures: list[str] = []
        job.update(
            f"Fetching {len(chosen)} file{'s' if len(chosen) != 1 else ''} from {reference.label}",
            files_total=len(chosen),
            files_done=0,
            bytes_total=total,
            bytes_done=0,
            current=None,
        )
        with tempfile.TemporaryDirectory(prefix="paperagent.", dir=self.workspace.root) as scratch:
            for number, file in enumerate(chosen, 1):
                if job.stop.is_set():
                    raise StoppedError("Stopped.")
                job.update(f"Fetching {file.name}", current=file.name)
                job.log(f"Fetching {file.name} ({describe_size(file.bytes or 0)}) from {file.url}")
                try:
                    fetched = self.fetch_data_file(
                        job, agent_id, listing, file, Path(scratch) / f"{number}.part", written
                    )
                except finding.DataError as error:
                    failures.append(f"{file.name}: {error}")
                    job.log(f"Not kept: {error}")
                    job.update(bytes_done=written)
                    continue
                kept += 1
                written += fetched.bytes
                checked += fetched.checked is not None
                job.update(files_done=kept, bytes_done=written)
                job.log(
                    f"Kept {file.name}: {fetched.bytes:,} bytes, SHA-256 {fetched.sha256}"
                    + (
                        f", matching the {fetched.checked[0].upper()} that {reference.source} gave"
                        if fetched.checked
                        else ""
                    )
                )
        if failures:
            raise ValueError(
                f"{kept} of {len(chosen)} files were kept, and {len(failures)} were not. " + " ".join(failures)
            )
        how = []
        if checked:
            how.append(f"{checked} matched the checksum that the place gave")
        if kept - checked:
            how.append(f"{kept - checked} had none to match, and were checked against their size only")

        return (
            f"Kept {kept} file{'s' if kept != 1 else ''}, {describe_size(written)}, from {reference.label}, in "
            f"data/{finding.folder_of(reference)}/. {'; '.join(how).capitalize()}."
        )

    def fetch_data_file(
        self,
        job: Job,
        agent_id: str,
        listing: finding.Listing,
        file: finding.DataFile,
        target: Path,
        before: int,
    ) -> hosting.Fetched:
        """Fetches one file, and puts it where it is kept, with what is said of it.

        :param before: How many bytes of the files before it were kept, which what it adds is counted on.
        :raises DataError: If it cannot be fetched, is not what it was said to be, or cannot be put in place.
        """
        received = 0

        def count(chunk: int) -> None:
            nonlocal received
            received += chunk
            job.update(bytes_done=before + received)

        fetched = hosting.fetch_file(listing.reference, file, target, count, job.stop.is_set)
        with self._lock:
            directory, _ = self.lookup(agent_id)
            root = kept_data.data_path(directory)
            destination = root / finding.folder_of(listing.reference) / file.name
            try:
                if not destination.resolve().is_relative_to(root.resolve()):
                    raise finding.DataError(f"{file.name} would be kept outside the agent's data", "refused")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.is_dir():
                    raise finding.DataError(f"{file.name} cannot be kept: a folder is where it would be", "failed")
                shutil.move(str(target), destination)
                size = destination.stat().st_size
            except OSError as error:
                raise finding.DataError(
                    f"{file.name} could not be put in place: {error.strerror or type(error).__name__}", "failed"
                ) from error
            if size != fetched.bytes:
                destination.unlink(missing_ok=True)
                raise finding.DataError(
                    f"{file.name} is {size:,} bytes where it was put, and {fetched.bytes:,} were fetched", "size"
                )
            kept_data.save(
                directory,
                kept_data.with_file(
                    kept_data.load(directory),
                    listing.reference,
                    listing.reference.label,
                    listing.title,
                    listing.license,
                    {
                        "name": file.name,
                        "path": f"{finding.folder_of(listing.reference)}/{file.name}",
                        "bytes": size,
                        "sha256": fetched.sha256,
                        "checksum": (
                            {"algorithm": fetched.checked[0], "value": fetched.checked[1]}
                            if fetched.checked is not None
                            else None
                        ),
                        "url": file.url,
                        "fetched_at": utc_timestamp(),
                    },
                ),
            )

        return fetched

    def settle_data(self, agent_id: str, failed: bool) -> None:
        """Says how far the step of the data has got: done if there is data that was fetched or that stands in, failed
        if there is none and fetching failed, and pending if it was only stopped."""
        with self._lock:
            try:
                directory, agent = self.lookup(agent_id)
            except ApiError:
                return
            self.set_data_step(directory, agent, failed)

    def set_data_step(self, directory: Path, agent: dict[str, Any], failed: bool = False) -> None:
        """Says how far the step of the data has got, from what is kept. Called with the lock held."""
        status = "done" if kept_data.has_data(kept_data.load(directory)) else "failed" if failed else "pending"
        if steps_of(agent)["data"] != status:
            self.save(directory, {**agent, "steps": {**steps_of(agent), "data": status}})

    def clear_data(self, agent_id: str, source: Any = None) -> None:
        """Takes away the files that were fetched, of one place or of all. What stands in for data is left.

        :param source: The key of a place, as the files are listed by, or none for every file.
        :raises ApiError: If there is no agent with this id, there are no files of that place, or the agent is being
            worked on.
        """
        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            record = kept_data.load(directory)
            if source is None:
                record = kept_data.forget_files(directory, record)
            elif isinstance(source, str) and any(kept["key"] == source for kept in record["sources"]):
                record = kept_data.forget_source(directory, record, source)
            else:
                raise not_found("fetched data of that place")
            kept_data.save(directory, record)
            self.set_data_step(directory, agent)

    def set_stand_in(self, agent_id: str, dataset: Any, own: Any) -> None:
        """Says that some of the person's own data stands in for a dataset that the paper used. It is only a note of
        which: the data stays where it is, as theirs, and nothing is copied.

        :param dataset: The key of a dataset that the paper names, or, for one that it does not, what to call it.
        :param own: The name of the data on the Data page.
        :raises ApiError: If there is no agent with this id, what is given is not fit, or there is no such data of the
            person's.
        """
        self.lookup(agent_id)
        if not isinstance(dataset, str) or not dataset.strip() or len(dataset) > MAX_DATASET_CHARS:
            raise ApiError(
                422,
                "invalid",
                f"Say which dataset of the paper it stands in for, in at most {MAX_DATASET_CHARS} characters",
            )
        if has_control_character(dataset):
            raise ApiError(422, "invalid", "The name of the dataset cannot have a control character in it")
        if not isinstance(own, str) or own not in self.workspace.load_own()["data"]:
            raise ApiError(422, "no_data", "There is no data of yours with that name. Add it on the Data page first")
        with self._lock:
            directory, agent = self.lookup(agent_id)
            file = agent["paper"].get("file")
            reading = kept_reading.describe(directory, file["sha256"] if file is not None else None, made_with())
            named = {item["id"]: item["name"] for item in reading["card"].get("datasets", [])}
            text = " ".join(dataset.split())
            key, name = (dataset, named[dataset]) if dataset in named else (f"name:{text.casefold()}", text)
            record = kept_data.load(directory)
            others = [stand_in for stand_in in record["stand_ins"] if stand_in["key"] != key]
            if len(others) >= kept_data.MAX_STAND_INS:
                raise ApiError(
                    409, "too_many", f"No more than {kept_data.MAX_STAND_INS} datasets can have data standing in"
                )
            kept_data.save(
                directory,
                {**record, "stand_ins": [*others, {"key": key, "name": name, "own": own, "set_at": utc_timestamp()}]},
            )
            self.set_data_step(directory, agent)

    def clear_stand_in(self, agent_id: str, dataset: Any) -> None:
        """Takes away what stands in for a dataset.

        :param dataset: The key it was set with.
        :raises ApiError: If there is no agent with this id, or nothing stands in for that dataset.
        """
        with self._lock:
            directory, agent = self.lookup(agent_id)
            record = kept_data.load(directory)
            left = [stand_in for stand_in in record["stand_ins"] if stand_in["key"] != dataset]
            if len(left) == len(record["stand_ins"]):
                raise not_found("stand-in for that dataset")
            kept_data.save(directory, {**record, "stand_ins": left})
            self.set_data_step(directory, agent)


def data_error(error: finding.DataError) -> ApiError:
    """What a PaperAgent says of something that kept data from being listed or fetched: a place that cannot be had
    from is the host's, and a request that is not fit is the person's."""
    return ApiError(DATA_STATUSES.get(error.kind, 502), error.kind, str(error))
