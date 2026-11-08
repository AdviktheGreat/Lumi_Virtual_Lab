"""PaperAgents: a paper, and the code that came with it, made into something the lab can use.

An agent is kept in a directory of its own in the workspace's paperagents/. Its agent.json says which paper it is of
(a DOI, a link, or a file the person uploaded, which is kept beside it in paper/), where the paper's code is, if that is
known, and how far each step of making it has got. The steps are added one at a time, so for now every step is pending
and an agent is the record of what it is to be made from.

The paper is how an agent is told from others: one paper is one agent, so a DOI, a link, or a file already in an agent
is refused, with the agent it is in.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import unquote, urlsplit, urlunsplit

from virtual_lab.chat import describe_size, safe_filename
from virtual_lab.constants import MAX_PAPER_FILE_BYTES
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.papers import MAX_TITLE_CHARS, PAPER_KINDS, PAPER_SUFFIXES, RUN_ID
from virtual_lab.server.workspace import Workspace, claim_directory, has_control_character, read_json
from virtual_lab.utils import write_atomically

# What an agent is, and where the paper uploaded to it is kept
AGENT_FILE = "agent.json"
PAPER_DIR = "paper"

# What an agent's record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1

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

DOI = re.compile(r"10\.\d{4,9}/\S+")
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
    try:
        parts = urlsplit(given)
        host = parts.hostname
        parts.port  # noqa: B018  Read only to find out if it is a number, which raises if it is not
    except ValueError:
        host = None
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

    return parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query


def check_url(text: Any) -> str:
    """A link to a paper as it is kept: its host in lower case, without a part after #, and without a slash at the end.

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


def is_agent(value: Any) -> bool:
    """Whether what an agent's file holds is an agent's: a title, when it was made, and which paper it is of."""
    if not (
        isinstance(value, dict)
        and isinstance(value.get("schema"), int)
        and isinstance(value.get("title"), str)
        and isinstance(value.get("created_at"), str)
        and isinstance(paper := value.get("paper"), dict)
        and paper.get("kind") in PAPERS
    ):
        return False
    if paper["kind"] == "doi" and not isinstance(paper.get("doi"), str):
        return False
    if paper["kind"] == "url" and not isinstance(paper.get("url"), str):
        return False
    if paper["kind"] == "file":
        file = paper.get("file")
        if file is not None and not (
            isinstance(file, dict)
            and isinstance(file.get("name"), str)
            and isinstance(file.get("bytes"), int)
            and isinstance(file.get("sha256"), str)
            and SHA256.fullmatch(file["sha256"])
        ):
            return False
    repo = value.get("repo")

    return repo is None or (isinstance(repo, dict) and isinstance(repo.get("url"), str))


def steps_of(agent: dict[str, Any]) -> dict[str, str]:
    """How far each step has got: pending for one the record does not say, and for one it says something else of."""
    steps = agent.get("steps")
    steps = steps if isinstance(steps, dict) else {}

    return {step: steps[step] if steps.get(step) in STATUSES else "pending" for step in STEPS}


def same_paper(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Whether two agents are of one paper, which is told by the DOI, the link, or the contents of the file."""
    if left["kind"] != right["kind"]:
        return False
    if left["kind"] == "file":
        return (
            left["file"] is not None and right["file"] is not None and left["file"]["sha256"] == right["file"]["sha256"]
        )

    return bool(left[left["kind"]] == right[right["kind"]])


class PaperAgents:
    """The PaperAgents, kept in a workspace.

    :param workspace: Where they are kept.
    :param max_upload_bytes: The most bytes of a paper that may be uploaded.
    """

    def __init__(self, workspace: Workspace, max_upload_bytes: int) -> None:
        self.workspace = workspace
        self.max_upload_bytes = min(max_upload_bytes, MAX_PAPER_FILE_BYTES)
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
                if RUN_ID.fullmatch(directory.name) and directory.is_dir() and is_agent(agent):
                    found.append((directory, agent))

        return found

    def entry(self, agent_id: str, agent: dict[str, Any]) -> dict[str, Any]:
        """An agent as a page shows it."""
        return {
            "id": agent_id,
            "title": agent["title"],
            "created_at": agent["created_at"],
            "paper": agent["paper"],
            "repo": agent.get("repo"),
            "steps": steps_of(agent),
        }

    def lookup(self, agent_id: str) -> tuple[Path, dict[str, Any]]:
        """Where an agent is kept, and what it is.

        :raises ApiError: If there is no agent with this id.
        """
        directory = self.workspace.paperagents_dir / agent_id
        agent = read_json(directory / AGENT_FILE) if RUN_ID.fullmatch(agent_id) else None
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
        code = check_repo(repo) if repo not in (None, "") else None
        root = self.workspace.paperagents_dir
        root.mkdir(parents=True, exist_ok=True)

        with self._lock:
            self.check_unique(kept)
            if sum(1 for path in root.iterdir() if path.is_dir()) >= MAX_AGENTS:
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
                agent = {**agent, "repo": {"url": check_repo(repo)} if repo != "" else None}
            self.save(directory, agent)

    def delete(self, agent_id: str) -> None:
        """Deletes an agent with the paper that was uploaded to it.

        :raises ApiError: If there is no agent with this id.
        """
        with self._lock:
            directory, _ = self.lookup(agent_id)
            shutil.rmtree(directory)

    def put_paper(self, agent_id: str, name: str, content: BinaryIO) -> None:
        """Keeps the paper that was uploaded to an agent, in place of one that was. What is in it is read as it arrives.

        :param name: What it was called, which may have a path, as a browser sends it.
        :raises ApiError: If there is no agent with this id, its paper is not a file, the file is not a paper, it is
            too big, or another agent has it.
        """
        _, agent = self.lookup(agent_id)
        if agent["paper"]["kind"] != "file":
            raise ApiError(409, "invalid", "A paper is uploaded only to a PaperAgent whose paper is a file")
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
                paper = {**agent["paper"], "file": kept}
                self.check_unique(paper, besides=agent_id)
                folder = directory / PAPER_DIR
                shutil.rmtree(folder, ignore_errors=True)
                folder.mkdir()
                try:
                    os.replace(temporary, folder / filename)
                    self.save(directory, {**agent, "paper": paper})
                except BaseException:
                    shutil.rmtree(folder, ignore_errors=True)
                    raise

    def remove_paper(self, agent_id: str) -> None:
        """Takes away the paper that was uploaded to an agent.

        :raises ApiError: If there is no agent with this id, or it has no paper uploaded.
        """
        with self._lock:
            directory, agent = self.lookup(agent_id)
            if agent["paper"]["kind"] != "file" or agent["paper"]["file"] is None:
                raise not_found("paper uploaded to that PaperAgent")
            self.save(directory, {**agent, "paper": {**agent["paper"], "file": None}})
            shutil.rmtree(directory / PAPER_DIR, ignore_errors=True)
