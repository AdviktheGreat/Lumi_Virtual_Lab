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

Tools are made, when the person asks, from the calls that the reference run kept. Each function that a tutorial called
is written as a wrapper that calls the paper's own function and does nothing else, and is called again, in the same
kind of container, with the arguments that the tutorial passed, each call in a process of its own on a copy of its own
of the code. A tool that gives again what the tutorial got is of tier A, and is kept with each call that was made as the
evidence. One that does not is dropped, with why, and is not changed to fit. Tier A says that a tool gives again what
the tutorials got, and does not say that what it gives is right.

Tools are checked, when the person asks, by what their tutorials did not give them: each tool and the code's own
function are called with arguments that the tutorial did not pass, and the tests that the code came with that call the
function are run, in the same kind of container. Each check is kept as it is made, bound to the wrapper, the commit, the
image, and the reference run it was made of (paperagent_checks.py). A tool of tier A that has passed checks against two
different bases (the code's function, the code's tests, the paper's numbers) and failed none is of tier B, which follows
from what is kept and from nothing else, and is not said to show that what the tool gives is right.

The claims of the paper that are numbers are tried, when the person asks, against what the tutorials gave: a program
finds where in what each tutorial gave a claim's number may be, by the number as the paper rounded it and by the figures
and tables that the sentence and the tutorial both refer to, a model chooses which place the sentence is about without
being shown any value, and a program holds what was kept there to the number (paperagent_reproduction.py). Each claim
is reproduced, partly, not, or not attempted, with why, and a claim that no code could be linked to is not attempted and
not failed. It is of the tutorials as they ran here, and does not say that they were run on the paper's data.

A paper that has none of its code can have a function written from its words instead, when the person says so and
agrees to the words of the paper that the model is to be given, which they are shown first
(paperagent_reimplementation.py). It is a re-implementation, of tier C if it comes to be checked, and is shown as one
wherever it is shown. A function that was written has not been checked against anything of the paper, and is given to
nothing.

An agent is given to conversations when the person says so (the flag `given` in its agent.json), or when they name it
for one. What a conversation is then given of it is in paperagent_given.py: tools that read what was found in the
paper, which are of tier D, and its tools of tier A, which run the authors' code where the conversation may run code.

An agent that someone else made of a paper, such as a server that Paper2Agent hosts, can be imported: it is kept as an
agent of that paper, with where the server is reached and the tools it listed. It is of the tier Imported, which says
that nothing of Lumi's has been done to it, and what it gives a conversation is in paperagent_given.py and
imported_agents.py.
"""

import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
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
from virtual_lab.execution import DockerExecutor, DockerUnavailableError
from virtual_lab.function_checks import FunctionSourceError, read_function
from virtual_lab.function_generator import check_function_name
from virtual_lab.llm import ModelSource
from virtual_lab.mcp_tools import MCPTools, connect_mcp
from virtual_lab.paper_batch import csv_bytes
from virtual_lab.paperagents import (
    asking,
    diverging,
    exporting,
    linking,
    matching,
    proposing,
    reimplementing,
    reporting,
    reproducing,
    toolmaking,
    varying,
    watching,
)
from virtual_lab.paperagents import card as method_card
from virtual_lab.paperagents import checking as verifying
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
from virtual_lab.server import imported_agents as importing
from virtual_lab.server import paperagent_checks as kept_checks
from virtual_lab.server import paperagent_checkwork as checkwork
from virtual_lab.server import paperagent_data as kept_data
from virtual_lab.server import paperagent_divergence as kept_divergence
from virtual_lab.server import paperagent_environment as kept_environment
from virtual_lab.server import paperagent_library as kept_library
from virtual_lab.server import paperagent_living as kept_living
from virtual_lab.server import paperagent_matching as kept_matching
from virtual_lab.server import paperagent_reading as kept_reading
from virtual_lab.server import paperagent_reference as kept_reference
from virtual_lab.server import paperagent_reimplementation as kept_reimplementation
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server import paperagent_reproduction as kept_reproduction
from virtual_lab.server import paperagent_tools as kept_tools
from virtual_lab.server import paperagent_toolwork as toolwork
from virtual_lab.server import paperagent_variants as kept_variants
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
from virtual_lab.utils import MeetingUsage, compute_token_cost, write_atomically
from virtual_lab.webpages import is_public_address

LOG = logging.getLogger("uvicorn.error")

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
# The job that makes tools from what the tutorials did, which is not done to an agent while another job is
TOOLS_JOB = "paperagent-tools"
# The job that checks the tools by what their tutorials did not give them, which is not done to an agent while another
# job is
CHECKS_JOB = "paperagent-checks"
# The job that makes a package of the tools and checks it in a clean container, which is not done to an agent while
# another job is
EXPORT_JOB = "paperagent-export"
# The job that looks at an agent: where its code is now, the versions it pins, and its tools' recorded calls run again
HEALTH_JOB = "paperagent-health"
# The job that tries the paper's claims against what the tutorials gave, which is not done to an agent while another job
# is
REPRODUCTION_JOB = "paperagent-reproduction"
# The job that makes a claim's call again with something changed, which is not done to an agent while another job is
VARIANT_JOB = "paperagent-variant"
# The job that writes a function from the words of the paper, which is not done to an agent while another job is
REIMPLEMENTATION_JOB = "paperagent-reimplementation"
# The job that checks that function against the numbers that the paper reports, which is not done to an agent while
# another job is
MATCHING_JOB = "paperagent-reimplementation-checks"
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
    """Whether a path is a directory of its own, and not a link to one, which is not followed out of the workspace. A
    name that the file system cannot take, as one that is too long, is of no directory."""
    try:
        return path.is_dir() and not path.is_symlink()
    except OSError:
        return False


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
    imported = value.get("imported")
    if imported is not None and not importing.is_imported(imported):
        return False

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


def is_given(agent: dict[str, Any]) -> bool:
    """Whether the person gave the agent to the conversations that are made from now on, which only a record that says
    so does."""
    return agent.get("given") is True


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


def data_to_give(directory: Path) -> tuple[Path | None, dict[str, int] | None]:
    """The folder of the data that was fetched for an agent, and how much is in it, if there is any, which is what a run
    is given to read."""
    record = kept_data.load(directory)
    present = [file for source in record["sources"] for file in source["files"] if kept_data.present(directory, file)]
    folder = kept_data.data_path(directory)
    if not present or folder.is_symlink() or not folder.is_dir():
        return None, None

    return folder, {"files": len(present), "bytes": sum(file["bytes"] for file in present)}


def kept_tools_of(directory: Path, agent: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The reference run that is kept for an agent, if it is complete, and the account of the tools that were made from
    it."""
    code = agent.get("repo")
    intake = kept_repository.load(directory, code["url"] if code is not None else None)
    commit = intake["commit"] if intake is not None else None
    built = kept_environment.load(directory, commit)
    image_id = built["image"]["id"] if built is not None else None
    reference = kept_reference.load(directory, commit, image_id)
    if reference is None or not reference["complete"]:
        return None, None

    return reference, kept_tools.load(directory, commit, image_id, reference)


class PaperAgents:
    """The PaperAgents, kept in a workspace.

    :param workspace: Where they are kept.
    :param max_upload_bytes: The most bytes of a paper that may be uploaded.
    :param jobs: Where a paper is read, which a page follows. Papers are not read without it.
    :param missing_keys: Says which variables a model's provider needs that are not set.
    :param client: An OpenAI client to read with, which is for tests.
    :param chat_models: The chat models to read with, which is for tests.
    :param docker_command: How Docker is invoked, which environments are built and kept with.
    :param connect: What connects to the server of an imported agent, as connect_mcp does, which is for tests.
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
        connect: Callable[..., MCPTools] = connect_mcp,
    ) -> None:
        self.docker_command = tuple(docker_command)
        self.connect = connect
        # What asks where the code is now, and what asks of the versions that a lock pins, which tests replace
        self.probe_source = watching.probe_source
        self.pin_index = watching.Index()
        self.workspace = workspace
        self.max_upload_bytes = min(max_upload_bytes, MAX_PAPER_FILE_BYTES)
        self.jobs = jobs if jobs is not None else Jobs()
        self.missing_keys = missing_keys if missing_keys is not None else (lambda model: [])
        self.client = client
        self.chat_models = chat_models
        # Held from looking for an agent of a paper to keeping the one that is made, so that of two of one paper only
        # one is made, and while a file is put in, an agent is changed, or one is removed
        self._lock = threading.Lock()
        # The imported agents whose server is being connected to, which is one connection at a time to each
        self._looking: set[str] = set()
        # The agents that are being deleted, which cannot be looked up or listed from when the deleting begins. They are
        # still counted, and their papers are still taken, as one whose deleting fails comes back.
        self._deleting: set[str] = set()

    def describe(self) -> dict[str, Any]:
        """Every agent, the latest first, and what a page needs to make one."""
        agents = [
            self.entry(directory.name, agent)
            for directory, agent in self.kept()
            if directory.name not in self._deleting
        ]

        return {
            "agents": sorted(agents, key=lambda agent: (agent["created_at"], agent["id"]), reverse=True),
            "max_agents": MAX_AGENTS,
            "max_paper_bytes": self.max_upload_bytes,
            "suffixes": list(PAPER_SUFFIXES),
            "repo_hosts": list(REPO_HOSTS),
            "importable": self.importable(),
        }

    def importable(self) -> list[dict[str, Any]]:
        """The servers that others host, which can be imported, each with the agent that has it already, and the agent
        of its paper, if there is one, which it could be added to."""
        kept = self.kept()
        found = []
        for server in importing.IMPORTABLE:
            paper = {"kind": "doi", "doi": server.doi}
            found.append(
                {
                    "key": server.key,
                    "title": server.title,
                    "about": server.about,
                    "made_by": server.made_by,
                    "url": server.url,
                    "site": server.site,
                    "paper": paper,
                    "repo": server.repo,
                    "agent": next(
                        (
                            directory.name
                            for directory, agent in kept
                            if agent.get("imported") and importing.same_address(agent["imported"]["url"], server.url)
                        ),
                        None,
                    ),
                    "paper_agent": next(
                        (directory.name for directory, agent in kept if same_paper(paper, agent["paper"])), None
                    ),
                }
            )

        return found

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
        if (
            self.reference_job(agent_id) is not None
            or self.tools_job(agent_id) is not None
            or self.checks_job(agent_id) is not None
        ):
            steps["tools"] = "running"

        return {
            "id": agent_id,
            "title": agent["title"],
            "created_at": agent["created_at"],
            "paper": agent["paper"],
            "repo": agent.get("repo"),
            "steps": steps,
            "given": is_given(agent),
            "imported": importing.describe(agent["imported"]) if agent.get("imported") is not None else None,
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

    def tools_job(self, agent_id: str) -> Job | None:
        """The job that is making an agent's tools, if one is."""
        return next((job for job in self.jobs.active(TOOLS_JOB) if job.subject == agent_id), None)

    def checks_job(self, agent_id: str) -> Job | None:
        """The job that is checking an agent's tools, if one is."""
        return next((job for job in self.jobs.active(CHECKS_JOB) if job.subject == agent_id), None)

    def export_job(self, agent_id: str) -> Job | None:
        """The job that is making a package of an agent's tools, if one is."""
        return next((job for job in self.jobs.active(EXPORT_JOB) if job.subject == agent_id), None)

    def health_job(self, agent_id: str) -> Job | None:
        """The job that is looking at an agent, if one is."""
        return next((job for job in self.jobs.active(HEALTH_JOB) if job.subject == agent_id), None)

    def reproduction_job(self, agent_id: str) -> Job | None:
        """The job that is trying an agent's claims, if one is."""
        return next((job for job in self.jobs.active(REPRODUCTION_JOB) if job.subject == agent_id), None)

    def variant_job(self, agent_id: str) -> Job | None:
        """The job that is making a variant of one of an agent's claims, if one is."""
        return next((job for job in self.jobs.active(VARIANT_JOB) if job.subject == agent_id), None)

    def reimplementation_job(self, agent_id: str) -> Job | None:
        """The job that is writing a function from an agent's paper, if one is."""
        return next((job for job in self.jobs.active(REIMPLEMENTATION_JOB) if job.subject == agent_id), None)

    def matching_job(self, agent_id: str) -> Job | None:
        """The job that is checking the function written from an agent's paper against its numbers, if one is."""
        return next((job for job in self.jobs.active(MATCHING_JOB) if job.subject == agent_id), None)

    def check_idle(self, agent_id: str, reading: bool = True) -> None:
        """
        :param reading: Whether a reading of the paper is waited for as well as the fetching of the code.
        :raises ApiError: If the agent's paper is being read, its code fetched, its environment built, its data
            fetched, its tutorials run, its tools made, its tools checked, a package made of them, it looked at, its
            claims tried, a variant of one made, or a function written from its paper or checked against it, which what
            is done to them must wait for.
        """
        job = (
            (self.running(agent_id) if reading else None)
            or self.cloning(agent_id)
            or self.making(agent_id)
            or self.downloading(agent_id)
            or self.reference_job(agent_id)
            or self.tools_job(agent_id)
            or self.checks_job(agent_id)
            or self.export_job(agent_id)
            or self.health_job(agent_id)
            or self.reproduction_job(agent_id)
            or self.variant_job(agent_id)
            or self.reimplementation_job(agent_id)
            or self.matching_job(agent_id)
        )
        if job is not None:
            raise ApiError(409, "busy", f"{job.title} is still going. Stop that first", job=job.snapshot())

    def lookup(self, agent_id: str) -> tuple[Path, dict[str, Any]]:
        """Where an agent is kept, and what it is.

        :raises ApiError: If there is no agent with this id.
        """
        directory = self.workspace.paperagents_dir / agent_id
        agent = (
            read_json(directory / AGENT_FILE)
            if RUN_ID.fullmatch(agent_id) and agent_id not in self._deleting and is_real_directory(directory)
            else None
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

    def create(
        self, title: Any, paper: dict[str, Any], repo: Any = None, imported: dict[str, Any] | None = None
    ) -> str:
        """Makes an agent of a paper, with nothing done to it yet.

        :param title: What it is called, which may be left out unless the paper is a file.
        :param paper: Which paper, as check_paper takes it.
        :param repo: The address of the paper's code, if it is known.
        :param imported: What the agent was imported from, as imported_agents.record_of makes it, for one that was.
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
            if imported is not None:
                # Again, since the server was connected to without the lock, and another may have been brought in since
                self.check_unimported(imported["url"])
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
                    **({"imported": imported} if imported is not None else {}),
                }
                self.save(directory, agent)
            except BaseException:
                shutil.rmtree(directory, ignore_errors=True)
                raise

        return directory.name

    def save(self, directory: Path, agent: dict[str, Any]) -> None:
        write_atomically(directory / AGENT_FILE, json.dumps(agent, indent=4).encode("utf-8"))

    def change(self, agent_id: str, title: Any = None, repo: Any = None, given: Any = None) -> None:
        """Says again what an agent is called, where its code is, and whether it is given to the conversations that are
        made from now on. What is left out is left as it was, and an empty address takes the code away.

        :raises ApiError: If there is no agent with this id, or what is given is not fit.
        """
        if title is None and repo is None and given is None:
            raise ApiError(422, "invalid", "Say what to change: the title, where the code is, or whether it is given")
        wanted = check_flag(given, "given") if given is not None else None
        with self._lock:
            directory, agent = self.lookup(agent_id)
            if title is not None:
                agent = {**agent, "title": check_title(title)}
            if wanted is not None:
                agent = {**agent, "given": wanted}
            if repo is not None:
                url = None if is_blank(repo) else check_repo(repo)
                if url != (agent.get("repo") or {}).get("url"):
                    # The code that was fetched is of the address it was fetched from, and is not another's
                    self.check_idle(agent_id, reading=False)
                    self.forget_code(directory)
                    agent = {
                        **agent,
                        "repo": {"url": url} if url is not None else None,
                        "steps": {
                            **steps_of(agent),
                            "repository": "pending",
                            "environment": "pending",
                            "tools": "pending",
                        },
                    }
            self.save(directory, agent)

    def import_agent(
        self, url: Any, title: Any = None, paper: dict[str, Any] | None = None, repo: Any = None, agent: Any = None
    ) -> str:
        """Brings in an agent that someone else made, from the server that hosts it: an agent of its paper, as one is
        made, or, for the id of an agent that there is, that agent with the server added to it. The server is connected
        to first, to see that it is one and which tools it gives, and nothing is called.

        :param url: Where the server is reached.
        :param title: What the agent is called, which may be left out unless the paper is a file.
        :param paper: Which paper the agent is of, as check_paper takes it, which an agent that there is already has.
        :param repo: The address of the paper's code, if it is known.
        :param agent: The agent to add the server to, if it is not to be made.
        :raises ApiError: If what is given is not fit, the server cannot be connected to or gives no tools, the agent
            has a server already, or another has this server or this paper.
        :return: The id of the agent.
        """
        address = importing.check_address(url)
        if agent is not None:
            if paper is not None or not is_blank(title) or not is_blank(repo):
                raise ApiError(
                    422, "invalid", "A server that is added to a PaperAgent that there is is given with its id only"
                )
            if not isinstance(agent, str):
                raise not_found("PaperAgent with that id")
            self.check_unimported(address, agent)
        else:
            if paper is None:
                raise ApiError(422, "invalid", "Say which paper the agent is of, by its DOI, a link, or a file")
            kept = check_paper(paper)
            check_title(title, kept)
            if not is_blank(repo):
                check_repo(repo)
            with self._lock:
                self.check_unique(kept)
                self.check_unimported(address)
        record = importing.record_of(address, self.look_at(address))
        if not importing.is_imported(record):
            raise ApiError(422, "invalid", f"The tools that {address} gives cannot be kept")
        if agent is None:
            assert paper is not None
            return self.create(title, paper, repo, record)
        with self._lock:
            directory, current = self.lookup(agent)
            self.check_unimported(address, agent)
            self.save(directory, {**current, "imported": record})

        return agent

    def check_unimported(self, address: str, agent_id: str | None = None) -> None:
        """
        :param agent_id: The agent that is to have the server, which has none already.
        :raises ApiError: If the agent has a server already, there is none such, or another agent has this server.
        """
        if agent_id is not None:
            _, current = self.lookup(agent_id)
            if current.get("imported") is not None:
                raise ApiError(409, "exists", f"{current['title']} was imported already", existing=agent_id)
        for directory, other in self.kept():
            if (
                directory.name != agent_id
                and other.get("imported")
                and importing.same_address(other["imported"]["url"], address)
            ):
                raise ApiError(
                    409,
                    "exists",
                    f"That server was imported already, as the PaperAgent {other['title']}.",
                    existing=directory.name,
                )

    def look_at(self, address: str) -> list[dict[str, str]]:
        """The tools that the server at an address gives.

        :raises ApiError: If it cannot be connected to or gives none, which says why.
        """
        try:
            return importing.look(address, self.connect)
        except importing.LookError as error:
            raise ApiError(error.status, "unavailable" if error.status == 502 else "invalid", str(error)) from error

    def check_import(self, agent_id: str) -> dict[str, Any]:
        """Connects to the server of an imported agent again, to say whether it can be, and to keep the tools it gives
        now, in place of those it gave. What an agent keeps is left as it was when the server cannot be connected to.

        :raises ApiError: If there is no agent with this id, it was not imported, or it is being connected to.
        :return: Whether it was, why not, and the agent.
        """
        _, agent = self.lookup(agent_id)
        imported = agent.get("imported")
        if imported is None:
            raise ApiError(422, "invalid", f"{agent['title']} was not imported")
        with self._lock:
            if agent_id in self._looking:
                raise ApiError(409, "busy", f"The server of {agent['title']} is being checked")
            self._looking.add(agent_id)
        try:
            try:
                tools = importing.look(imported["url"], self.connect)
            except importing.LookError as error:
                return {"ok": False, "reason": str(error), "agent": self.view(agent_id)}
            kept = importing.record_of(imported["url"], tools, imported["imported_at"])
            if not importing.is_imported(kept):
                return {
                    "ok": False,
                    "reason": f"The tools that {imported['url']} gives cannot be kept",
                    "agent": self.view(agent_id),
                }
            with self._lock:
                directory, current = self.lookup(agent_id)
                if current.get("imported") is None or current["imported"]["url"] != imported["url"]:
                    raise ApiError(409, "changed", f"{current['title']} was changed while its server was checked")
                self.save(directory, {**current, "imported": kept})
        finally:
            with self._lock:
                self._looking.discard(agent_id)

        return {"ok": True, "reason": None, "agent": self.view(agent_id)}

    def remove_import(self, agent_id: str) -> None:
        """Takes away what an agent was imported from, which leaves the agent of its paper, as it is otherwise.

        :raises ApiError: If there is no agent with this id, or it was not imported.
        """
        with self._lock:
            directory, agent = self.lookup(agent_id)
            if agent.get("imported") is None:
                raise ApiError(422, "invalid", f"{agent['title']} was not imported")
            self.save(directory, {key: value for key, value in agent.items() if key != "imported"})

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
            self._deleting.add(agent_id)
        # The lock is let go while Docker removes what it holds, which can take minutes when it is slow, as every other
        # agent waits on it. The agent is gone to everything else meanwhile, and is back if the deleting fails.
        try:
            self.forget_environment(directory)
            # A container that a build left when the server was stopped hard, which nothing else would take away
            building.remove_builds(directory.name, self.docker_command)
            # The code that was fetched is read only, which a platform may not remove without being mended first
            kept_repository.remove_tree(directory)
        finally:
            with self._lock:
                self._deleting.discard(agent_id)

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

    def check_scope(self, agent_id: str, described: Mapping[str, Any]) -> dict[str, Any]:
        """Puts what a person's data is against what the method card of an agent's paper says the method was used on:
        for each thing said of the data, whether it is inside, outside, or not covered, and for those that are
        outside, a warning with the card's words and the paper's. It does not stop anything: a person may go on.

        :param described: What is said of the data: its species, tissue, assay, input format, and its sample size with
            what that counts. At least one.
        :raises ApiError: If there is no agent with this id, or nothing is said of the data, or a thing is not said as
            it is taken.
        """
        directory, agent = self.lookup(agent_id)
        file = agent["paper"].get("file")
        found = kept_reading.describe(directory, file["sha256"] if file is not None else None, made_with())
        try:
            result = kept_reading.scope_check(found, described)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error

        return {"id": agent_id, **result}

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
            # What a person did to the card is theirs, and is of the paper, which stays
            kept_reading.forget(directory, edits=False)
            self.save(directory, self.unread(agent, agent["paper"]))

    # The method card, which a person reads, corrects, and approves

    def edit_card(
        self,
        agent_id: str,
        operation: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
        reading_blocks: bool = False,
    ) -> dict[str, Any]:
        """Does something to what a person has done to the card of an agent's paper, and gives the reading as it is
        after.

        :param operation: Given the card that the reading made and the edits that were, and gives the edits that are.
        :param reading_blocks: Whether it waits for a reading of the paper to end, as approving does, since the card is
            still being made while the paper is read.
        :raises ApiError: If there is no agent with this id, it has no paper, what is said is not something the card
            takes, or there is no such fact.
        """
        with self._lock:
            directory, agent = self.lookup(agent_id)
            file = agent["paper"].get("file")
            if file is None:
                raise ApiError(
                    409, "no_paper", "The agent has no paper yet, so it has no card. Upload the paper first."
                )
            if reading_blocks and (job := self.running(agent_id)) is not None:
                raise ApiError(409, "busy", f"{job.title} is still going. Stop that first", job=job.snapshot())
            read = kept_reading.read_card(directory, file["sha256"], made_with())
            edits = kept_reading.load_edits(directory, file["sha256"])
            try:
                edits = operation(read, edits)
            except method_card.NoSuchFactError as error:
                raise not_found("fact on that card") from error
            except ValueError as error:
                raise ApiError(422, "invalid", str(error)) from error
            kept_reading.save_edits(directory, file["sha256"], edits)

        return self.reading(agent_id)

    def add_card_fact(self, agent_id: str, kind: Any, fields: Any) -> dict[str, Any]:
        """Adds a fact to an agent's method card, which is the person's own.

        :param kind: Which sort of fact: methods, datasets, scope, or limitations.
        :param fields: What the fact says, by name, and its words as quote.
        """
        return self.edit_card(
            agent_id,
            lambda read, edits: method_card.add(read, edits, kind, fields, utc_timestamp(), secrets.token_hex(4)),
        )

    def change_card_fact(self, agent_id: str, fact_id: str, fields: Any) -> dict[str, Any]:
        """Changes a fact of an agent's method card to say what the person says, which makes it theirs."""
        return self.edit_card(
            agent_id, lambda read, edits: method_card.change(read, edits, fact_id, fields, utc_timestamp())
        )

    def remove_card_fact(self, agent_id: str, fact_id: str) -> dict[str, Any]:
        """Takes a fact off an agent's method card. One that was read can be put back."""
        return self.edit_card(agent_id, lambda read, edits: method_card.remove(read, edits, fact_id, utc_timestamp()))

    def restore_card_fact(self, agent_id: str, fact_id: str) -> dict[str, Any]:
        """Puts back a fact that was taken off an agent's method card, or has it say what it was read as."""
        return self.edit_card(agent_id, lambda read, edits: method_card.restore(read, edits, fact_id))

    def approve_card(self, agent_id: str) -> dict[str, Any]:
        """Says that a person read an agent's method card as it is and lets it stand, which is not that it is right. Any
        change to it makes it a draft again."""
        return self.edit_card(
            agent_id, lambda read, edits: method_card.approve(read, edits, utc_timestamp()), reading_blocks=True
        )

    def withdraw_card_approval(self, agent_id: str) -> dict[str, Any]:
        """Takes back the approval of an agent's method card, which makes it a draft."""
        return self.edit_card(agent_id, lambda read, edits: method_card.withdraw(edits))

    def discard_card_edits(self, agent_id: str) -> dict[str, Any]:
        """Takes away all that a person did to an agent's method card, and the approval, so that it is as it was
        read."""
        return self.edit_card(agent_id, lambda read, edits: method_card.empty_edits())

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
                    "steps": {**steps_of(agent), "repository": "pending", "environment": "pending", "tools": "pending"},
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

    def cloner(
        self, agent_id: str, url: str, ref: str, max_bytes: int, as_ref: str | None = None
    ) -> Callable[[Job], str | None]:
        """What a job does to fetch the code: fetches it, takes stock of it, and keeps both.

        :param as_ref: What to keep as the ref that the code is of, if it is not what was asked for: a commit that was
            fetched as the newer version of a branch is still of that branch.
        """

        def work(job: Job) -> str | None:
            failed = False
            try:
                return self.take_repository(job, agent_id, url, ref, max_bytes, as_ref)
            except StoppedError:
                raise
            except BaseException:
                failed = True
                raise
            finally:
                self.settle_repository(agent_id, failed)

        return work

    def take_repository(
        self, job: Job, agent_id: str, url: str, ref: str, max_bytes: int, as_ref: str | None = None
    ) -> str:
        job.update("Fetching the code")
        with tempfile.TemporaryDirectory(prefix="paperagent.", dir=self.workspace.root) as scratch:
            fetched = Path(scratch) / kept_repository.REPO_DIR
            cloned = cloning.clone(url, fetched, ref, max_bytes, should_stop=job.stop.is_set)
            job.log(f"Fetched {url} at commit {cloned.commit}")
            job.update("Taking stock of the code")
            stock = stocking.take_stock(fetched)
            if job.stop.is_set():
                raise StoppedError("Stopped before the code was kept.")
            kept_ref = as_ref or cloned.ref
            intake = {
                "url": url,
                "ref": kept_ref,
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
                kept_living.drop(directory, kept_living.UPDATE_FILE)
                self.save(
                    directory,
                    {
                        **agent,
                        "repo": {"url": url, "ref": kept_ref, "commit": cloned.commit},
                        "steps": {
                            **steps_of(agent),
                            "repository": "done",
                            "environment": "pending",
                            "tools": "pending",
                        },
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
                    "steps": {**steps_of(agent), "repository": "pending", "environment": "pending", "tools": "pending"},
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
        kept_living.drop(directory, kept_living.UPDATE_FILE)

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
        # A container that a run left when the server was stopped hard, which would keep its image from being removed,
        # and one that a conversation is calling a tool in, which would as well
        referencing.remove_runs(directory.name, self.docker_command, referencing.PREFIXES)
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
        # What was run in the image is of no use without it, nor are the tools made from that, nor the claims that were
        # held to what was run, nor how the tools were found when they were run again in it
        kept_living.drop(directory, kept_living.HEALTH_FILE)
        kept_tools.forget(directory)
        kept_reproduction.forget(directory)
        kept_variants.forget(directory)
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
            # The reference run and the tools went with the image they were made in
            steps = {**steps_of(agent), "environment": "pending", "tools": "pending"}
            if steps_of(agent) != steps:
                self.save(directory, {**agent, "steps": steps})

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
        _, data = data_to_give(directory)

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
            directory, agent, intake, built, image_id = self.image_for_runs(agent_id, "the tutorials run")
            kept = kept_reference.load(directory, intake["commit"], image_id)
            if kept is not None and kept["complete"]:
                raise ApiError(409, "done", "The tutorials have been run. Remove that to run them again.")
            plan = referencing.plan(intake["stock"])
            if not plan.runnable:
                raise ApiError(
                    422, "no_tutorials", "There is no tutorial in the code that can be run here: only Python is run"
                )
            folder, data = data_to_give(directory) if give else (None, None)
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

    def image_for_runs(
        self, agent_id: str, why: str
    ) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], str]:
        """What there is of an agent that is run in its environment: where it is kept, what it is, what was found of
        its code, what was built of it, and the id of the image, which is in Docker. It is called with the lock held.

        :param why: What is run in it, as the reason that it must be built.
        :raises ApiError: If the code has not been fetched or its environment not built, the agent's paper, code,
            environment, data, tutorials, or tools are being worked on, or the image is not in Docker.
        """
        directory, agent = self.lookup(agent_id)
        code = agent.get("repo")
        intake = kept_repository.load(directory, code["url"] if code is not None else None)
        if intake is None:
            raise ApiError(422, "no_code", "Fetch the code first")
        built = kept_environment.load(directory, intake["commit"])
        if built is None:
            raise ApiError(422, "no_environment", f"Build the environment first, as {why} in it")
        self.check_idle(agent_id)
        image_id = built["image"]["id"]
        if building.image_id_of(building.tag_of(agent_id, intake["commit"]), self.docker_command) != image_id:
            raise ApiError(
                409,
                "image_missing",
                "The image of the environment is not in Docker any more. Remove the environment and build it again.",
            )

        return directory, agent, intake, built, image_id

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
        # Tools are made from a reference run, and are of no use once it is taken away, nor is the trying of the claims
        kept_tools.forget(directory)
        kept_reproduction.forget(directory)
        kept_variants.forget(directory)
        self.settle_tools(agent_id, "pending")
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
        """Says how far the step of making tools has got when the running of the tutorials ends: failed if it failed,
        and pending if it was done or only stopped, as tools are made when the person asks."""
        self.settle_tools(agent_id, "failed" if failed else "pending")

    def clear_reference(self, agent_id: str) -> None:
        """Takes away what was kept of the running of an agent's tutorials, so that they can be run again.

        :raises ApiError: If there is no agent with this id, or its paper is being read, its code fetched, its
            environment built, its data fetched, its tutorials run, or its tools made. The tools that were made from
            them go too, and so does the trying of the claims that was held to them.
        """
        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            referencing.remove_runs(agent_id, self.docker_command)
            # The tools were made from what is taken away, and the claims were held to it
            kept_tools.forget(directory)
            kept_reproduction.forget(directory)
            kept_variants.forget(directory)
            kept_reference.forget(directory)
            if steps_of(agent)["tools"] in ("done", "failed"):
                self.save(directory, {**agent, "steps": {**steps_of(agent), "tools": "pending"}})

    # The tools, made from what the tutorials did

    def tools(self, agent_id: str) -> dict[str, Any]:
        """What there is of the making of an agent's tools: what the tutorials called, which of it would be made into
        tools and which would not, with why, what was kept of the last making, and what is allowed.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.lookup(agent_id)
        usable, problem = building.ready(self.docker_command)
        reference, kept = kept_tools_of(directory, agent)
        preview = None
        if reference is not None:
            gathered = toolwork.gather_kept(
                directory, reference, kept_repository.repo_path(directory), toolmaking.DEFAULT_TOOLS
            )
            preview = toolwork.preview_of(gathered)
        job = self.tools_job(agent_id)

        return {
            "id": agent_id,
            "docker": {"ready": usable, "message": problem},
            "reference": (
                {
                    "complete": True,
                    "tutorials": len(reference["tutorials"]),
                    "finished_at": reference["finished_at"],
                    "data": reference["data"] is not None,
                }
                if reference is not None
                else None
            ),
            "preview": preview,
            "kept": kept,
            "job": job.snapshot() if job is not None else None,
            "meaning": toolmaking.MEANING,
            "limits": toolwork.limits_of(),
        }

    def tool(self, agent_id: str, name: str) -> dict[str, Any]:
        """One tool of an agent: its wrapper's code, its signature, and the evidence for its tier, which is each call
        that was made again and what it gave.

        :raises ApiError: If there is no agent with this id, or it has no tool of that name that is as it was made.
        """
        directory, agent = self.lookup(agent_id)
        _, kept = kept_tools_of(directory, agent)
        tool = (
            kept_tools.load_tool(directory, name)
            if kept is not None and any(one["name"] == name for one in kept["tools"])
            else None
        )
        if tool is None:
            raise not_found("tool of that PaperAgent")

        return tool

    def start_tools(
        self,
        agent_id: str,
        minutes: Any = None,
        total_minutes: Any = None,
        tools: Any = None,
        repeats: Any = None,
        repairs: Any = None,
        gigabytes: Any = None,
    ) -> Job:
        """Starts making tools from the calls that the tutorials made: each function that was called is written as a
        wrapper of the paper's own function, and called again in the environment, in a container that has none of this
        machine in it and no network, with the arguments that the tutorial passed. A tool that gives again what the
        tutorial got is kept; one that does not is dropped, with why.

        :param minutes: The most time all of the calls of one tool may take.
        :param total_minutes: The most time all of the tools may take together.
        :param tools: The most tools to make.
        :param repeats: How many times each call is made again, to see that it gives the same each time.
        :param repairs: How many times a wrapper that does not pass the checks of one is rewritten.
        :param gigabytes: The most that one call may write.
        :raises ApiError: If there is no agent with this id, what is given is not fit, Docker is not running, the code
            has not been fetched or its environment not built or its image is not in Docker, the tutorials have not
            been run to their end, none of the functions they called can be a tool, the tools have been made, or the
            agent's paper, code, environment, data, tutorials, or tools are being worked on.
        """
        self.lookup(agent_id)
        try:
            limits = toolmaking.check_limits(minutes, total_minutes, tools, repeats, repairs, gigabytes)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error
        usable, problem = building.ready(self.docker_command)
        if not usable:
            raise ApiError(422, "docker_missing", problem or "Docker is not running, and making tools takes it")

        with self._lock:
            directory, agent, intake, built, image_id = self.image_for_runs(agent_id, "the tools are called")
            reference, kept = kept_tools_of(directory, agent)
            if reference is None:
                raise ApiError(422, "no_reference", "Run the tutorials first, as tools are made from what they did")
            if kept is not None and kept["complete"]:
                raise ApiError(409, "done", "The tools have been made. Remove them to make them again.")
            gathered = toolwork.gather_kept(directory, reference, kept_repository.repo_path(directory), limits.tools)
            if not gathered.candidates:
                raise ApiError(
                    422, "no_tools", f"No tool can be made of what the tutorials did. {toolwork.reasons_of(gathered)}"
                )
            folder, _ = data_to_give(directory) if reference["data"] is not None else (None, None)
            try:
                return self.jobs.start(
                    TOOLS_JOB,
                    agent_id,
                    f"Making the tools: {agent['title']}",
                    self.toolmaker(agent_id, intake["commit"], image_id, reference, limits, gathered, folder),
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def toolmaker(
        self,
        agent_id: str,
        commit: str,
        image_id: str,
        reference: dict[str, Any],
        limits: toolmaking.ToolLimits,
        gathered: Any,
        folder: Path | None,
    ) -> Callable[[Job], str | None]:
        """What a job does to make the tools: makes them one after another, and keeps each as it is made, so that a job
        that is stopped keeps what it had made."""

        def work(job: Job) -> str | None:
            status = "failed"
            try:
                summary, count = toolwork.make_all(
                    job,
                    self.workspace.paperagents_dir / agent_id,
                    self.workspace.root,
                    agent_id,
                    commit,
                    image_id,
                    reference,
                    limits,
                    gathered,
                    folder,
                    self.docker_command,
                )
                status = "done" if count else "failed"
                return summary
            except StoppedError:
                status = "pending"
                raise
            finally:
                self.settle_tools(agent_id, status)

        return work

    def settle_tools(self, agent_id: str, status: str) -> None:
        """Says how far the step of making tools has got: done if tools were made, failed if the making failed or no
        tool held, and pending if it was stopped or the tools were taken away."""
        with self._lock:
            try:
                directory, agent = self.lookup(agent_id)
            except ApiError:
                return
            if steps_of(agent)["tools"] != status:
                self.save(directory, {**agent, "steps": {**steps_of(agent), "tools": status}})

    def clear_tools(self, agent_id: str) -> None:
        """Takes away the tools that were made, so that they can be made again. What the tutorials did is kept.

        :raises ApiError: If there is no agent with this id, or its paper is being read, its code fetched, its
            environment built, its data fetched, its tutorials run, or its tools made.
        """
        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            referencing.remove_runs(agent_id, self.docker_command)
            kept_tools.forget(directory)
            if steps_of(agent)["tools"] in ("done", "failed"):
                self.save(directory, {**agent, "steps": {**steps_of(agent), "tools": "pending"}})

    # The library, and packages that are made of the tools

    def library_pieces(
        self, directory: Path, agent: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        """What an agent's tools are made of, which are what was found of its code, what was built of it, and the
        account of the tools, if it has tools that were made to their end."""
        code = agent.get("repo")
        intake = kept_repository.load(directory, code["url"] if code is not None else None)
        built = kept_environment.load(directory, intake["commit"] if intake is not None else None)
        _, kept = kept_tools_of(directory, agent)
        if intake is None or built is None or kept is None or not kept["complete"] or not kept["tools"]:
            return None

        return intake, built, kept

    def library(self) -> dict[str, Any]:
        """The agents that have tools, each with the version of the code that they are of, the environment that they
        are pinned to, the hash of each tool's wrapper, its tier, and the code's license, and whether a package has been
        made of them."""
        entries = []
        for directory, agent in self.kept():
            if directory.name in self._deleting:
                continue
            pieces = self.library_pieces(directory, agent)
            if pieces is not None:
                entry = kept_library.entry_of(directory, directory.name, agent, *pieces)
                entries.append({**entry, "health": self.health_summary(directory, pieces)})
        usable, problem = building.ready(self.docker_command)

        return {
            "agents": sorted(entries, key=lambda entry: entry["title"].lower()),
            "docker": {"ready": usable, "message": problem},
            "meaning": exporting.MEANING,
            "flags": exporting.FLAGS,
        }

    def export(self, agent_id: str) -> dict[str, Any]:
        """What there is of a package of an agent's tools: the agent as the library lists it, if it has tools, and
        whether a package is being made.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.lookup(agent_id)
        pieces = self.library_pieces(directory, agent)
        usable, problem = building.ready(self.docker_command)
        job = self.export_job(agent_id)

        return {
            "id": agent_id,
            "docker": {"ready": usable, "message": problem},
            "entry": kept_library.entry_of(directory, agent_id, agent, *pieces) if pieces is not None else None,
            "job": job.snapshot() if job is not None else None,
            "meaning": exporting.MEANING,
            "flags": exporting.FLAGS,
        }

    def export_file(self, agent_id: str) -> Path:
        """The file of the package that was made of an agent's tools.

        :raises ApiError: If there is no agent with this id, or no package was made, or it is not of what is kept now.
        """
        directory, agent = self.lookup(agent_id)
        pieces = self.library_pieces(directory, agent)
        record = kept_library.stored_export(directory)
        if record is None or pieces is None:
            raise not_found("package of that PaperAgent")
        entry = kept_library.entry_of(directory, agent_id, agent, *pieces)
        if entry["export"] is None or not entry["export"]["current"]:
            raise ApiError(
                409,
                "stale",
                "The package was made of tools, a version of the code, or an environment that are not what is kept "
                "now. Make it again.",
            )

        return kept_library.exports_path(directory) / record["file"]

    def start_export(self, agent_id: str, accept_license: Any = False) -> Job:
        """Starts making a package of an agent's tools that can be run as a server of the Model Context Protocol
        anywhere: the code, each tool's wrapper, the lock of the environment, a Dockerfile, a server, and what a person
        needs to know. It is checked in a clean container before it is kept.

        :param accept_license: Whether the person has read what is flagged of the code's license and goes on. A package
            of code with no license, with one that is not recognized, or with one for non-commercial use or a copyleft
            one is not made without it.
        :raises ApiError: If there is no agent with this id, accept_license is not yes or no, Docker is not running, the
            code has not been fetched or its environment not built or its image is not in Docker, there are no tools,
            the license is flagged and was not accepted, or the agent is being worked on.
        """
        self.lookup(agent_id)
        accepted = check_flag(accept_license, "accept_license")
        usable, problem = building.ready(self.docker_command)
        if not usable:
            raise ApiError(422, "docker_missing", problem or "Docker is not running, and a package is checked in it")

        with self._lock:
            directory, agent, intake, built, _ = self.image_for_runs(agent_id, "the package is checked")
            _, kept = kept_tools_of(directory, agent)
            if kept is None or not kept["complete"] or not kept["tools"]:
                raise ApiError(422, "no_tools", "Make the tools first, as a package is made of them")
            found = exporting.license_of(intake["stock"].get("license"))
            if found["flag"] is not None and not accepted:
                raise ApiError(
                    409,
                    "license",
                    f"{found['said']} Say that you have read this to make the package.",
                    license=found,
                )
            folder, _ = data_to_give(directory) if kept["data"] else (None, None)
            try:
                return self.jobs.start(
                    EXPORT_JOB,
                    agent_id,
                    f"Making a package: {agent['title']}",
                    self.exporter(agent_id, agent, intake, built, kept, folder, accepted),
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def exporter(
        self,
        agent_id: str,
        agent: dict[str, Any],
        intake: dict[str, Any],
        built: dict[str, Any],
        kept: dict[str, Any],
        folder: Path | None,
        accepted: bool,
    ) -> Callable[[Job], str | None]:
        """What a job does to make a package: makes it, checks it in a clean container, and keeps it if it passed."""

        def work(job: Job) -> str | None:
            return kept_library.make_package(
                job,
                self.workspace.paperagents_dir / agent_id,
                self.workspace.root,
                agent_id,
                agent,
                intake,
                built,
                kept,
                folder,
                self.docker_command,
                accepted,
            )

        return work

    def clear_export(self, agent_id: str) -> None:
        """Takes away the package that was made of an agent's tools.

        :raises ApiError: If there is no agent with this id, or it is being worked on.
        """
        with self._lock:
            directory, _ = self.lookup(agent_id)
            self.check_idle(agent_id)
            kept_library.forget(directory)

    def agent_ids(self) -> list[str]:
        """The ids of the agents that there are and that are not being removed, by title."""
        return [
            directory.name
            for directory, agent in sorted(self.kept(), key=lambda item: item[1]["title"].lower())
            if directory.name not in self._deleting
        ]

    # Watching an agent, so that it is told how it is and what a newer version of its code would change

    def health_summary(
        self, directory: Path, pieces: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
    ) -> dict[str, Any]:
        """How an agent was when it was last looked at, in a few words, and whether a newer version of its code is
        proposed. It is unchecked if it was not looked at, or was looked at in another environment or of other code."""
        intake, built, kept = pieces
        found = kept_living.health_view(kept_living.load_health(directory), intake, built, kept)
        proposed = kept_living.update_view(kept_living.load_update(directory), intake)
        watch = kept_living.load_watch(directory)

        return {
            "status": found["status"] if found is not None else watching.UNCHECKED,
            "checked_at": found["checked_at"] if found is not None else None,
            "update": proposed is not None,
            "watched_every_hours": watch["every_hours"] if watch is not None else None,
        }

    def health(self, agent_id: str) -> dict[str, Any]:
        """How an agent is, as it was found when it was last looked at: its source, its pinned versions, and its tools
        run again, with the schedule that it is looked at on, and whether a newer version of its code is proposed.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.lookup(agent_id)
        pieces = self.library_pieces(directory, agent)
        intake, built, kept = pieces if pieces is not None else (None, None, None)
        proposed = kept_living.update_view(kept_living.load_update(directory), intake)
        usable, problem = building.ready(self.docker_command)
        job = self.health_job(agent_id)

        return {
            "id": agent_id,
            "watchable": pieces is not None,
            "version": (
                {"commit": intake["commit"], "ref": intake["ref"], "url": intake["url"]} if intake is not None else None
            ),
            "health": kept_living.health_view(kept_living.load_health(directory), intake, built, kept),
            "watch": kept_living.load_watch(directory),
            "update": (
                {
                    key: proposed[key]
                    for key in ("proposed_at", "from_commit", "to_commit", "affects", "environment_files")
                }
                | {"changed": proposed["diff"]["changed"]}
                if proposed is not None
                else None
            ),
            "job": job.snapshot() if job is not None else None,
            "docker": {"ready": usable, "message": problem},
            "meaning": watching.MEANING,
            "limits": {"min_hours": kept_living.MIN_HOURS, "max_hours": kept_living.MAX_HOURS},
        }

    def start_health(self, agent_id: str) -> Job:
        """Starts looking at an agent: asking where its code is now, what a newer version would change, whether the
        versions that its lock pins can still be had, and running its tools' recorded calls again in its environment.
        Nothing that is kept is changed by it.

        :raises ApiError: If there is no agent with this id, it has no tools, or it is being worked on.
        """
        self.lookup(agent_id)
        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            pieces = self.library_pieces(directory, agent)
            if pieces is None:
                raise ApiError(422, "no_tools", "Make the tools first, as an agent is looked at by running them again")
            folder, _ = data_to_give(directory) if pieces[2]["data"] else (None, None)
            try:
                job = self.jobs.start(
                    HEALTH_JOB,
                    agent_id,
                    f"Looking at the agent: {agent['title']}",
                    self.looker(agent_id, agent, *pieces, folder),
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error
            watch = kept_living.load_watch(directory)
            if watch is not None:
                kept_living.keep(directory, kept_living.WATCH_FILE, {**watch, "last_started_at": utc_timestamp()})

            return job

    def looker(
        self,
        agent_id: str,
        agent: dict[str, Any],
        intake: dict[str, Any],
        built: dict[str, Any],
        kept: dict[str, Any],
        folder: Path | None,
    ) -> Callable[[Job], str | None]:
        """What a job does to look at an agent."""

        def fetch(*arguments: Any, **options: Any) -> Any:
            return cloning.clone(*arguments, **options)

        def work(job: Job) -> str | None:
            usable, problem = building.ready(self.docker_command)
            present = None
            if usable:
                tag = building.tag_of(agent_id, intake["commit"])
                present = building.image_is(tag, built["image"]["id"], self.docker_command)

            return kept_living.check_health(
                job,
                self.workspace.paperagents_dir / agent_id,
                self.workspace.root,
                agent_id,
                agent,
                intake,
                built,
                kept,
                folder,
                self.docker_command,
                self.probe_source,
                self.pin_index,
                fetch,
                present,
                None if usable else problem or "Docker is not running",
            )

        return work

    def set_watch(self, agent_id: str, every_hours: Any) -> dict[str, Any]:
        """Has an agent looked at again and again, every so many hours, while the server is running. It is looked at the
        next time the server checks the schedules.

        :param every_hours: How often, in hours.
        :raises ApiError: If there is no agent with this id, the hours are not a whole number in range, or it has no
            tools.
        """
        self.lookup(agent_id)
        hours = check_count(
            every_hours, "How often an agent is looked at, in hours,", kept_living.MIN_HOURS, kept_living.MAX_HOURS
        )
        with self._lock:
            directory, agent = self.lookup(agent_id)
            if self.library_pieces(directory, agent) is None:
                raise ApiError(422, "no_tools", "Make the tools first, as an agent is looked at by running them again")
            earlier = kept_living.load_watch(directory)
            kept_living.keep(
                directory,
                kept_living.WATCH_FILE,
                {
                    "every_hours": hours,
                    "set_at": utc_timestamp(),
                    "last_started_at": earlier["last_started_at"] if earlier is not None else None,
                },
            )

        return self.health(agent_id)

    def clear_watch(self, agent_id: str) -> dict[str, Any]:
        """Stops looking at an agent on a schedule. What was found stays, and it can still be looked at when asked.

        :raises ApiError: If there is no agent with this id.
        """
        with self._lock:
            directory, _ = self.lookup(agent_id)
            kept_living.drop(directory, kept_living.WATCH_FILE)

        return self.health(agent_id)

    def start_due_checks(self, now: datetime | None = None) -> list[str]:
        """Looks at each agent whose schedule says it is time, and that is not being worked on.

        :return: The agents that were started.
        """
        moment = now if now is not None else datetime.now(timezone.utc)
        started = []
        for directory, _ in self.kept():
            if directory.name in self._deleting or not kept_living.is_due(kept_living.load_watch(directory), moment):
                continue
            try:
                self.start_health(directory.name)
            except ApiError:
                continue
            started.append(directory.name)

        return started

    def watch_schedules(self, stopping: threading.Event, seconds: float) -> None:
        """Looks at the agents whose schedule says it is time, every so many seconds, until told to stop. A look that
        fails does not end it."""
        while not stopping.wait(seconds):
            try:
                self.start_due_checks()
            except Exception:
                LOG.exception("Looking at the agents that are watched failed")

    def update(self, agent_id: str) -> dict[str, Any]:
        """The newer version of an agent's code that is proposed, as a diff against the version that is kept, if there
        is one, and which of the tools are of a file that changed.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.lookup(agent_id)
        pieces = self.library_pieces(directory, agent)
        intake = pieces[0] if pieces is not None else None

        return {
            "id": agent_id,
            "update": kept_living.update_view(kept_living.load_update(directory), intake),
            "version": (
                {"commit": intake["commit"], "ref": intake["ref"], "url": intake["url"]} if intake is not None else None
            ),
            "pinned": "The commit, the environment, and the tools stay as they are until a newer version is approved.",
        }

    def apply_update(self, agent_id: str, commit: Any) -> Job:
        """Takes the newer version of an agent's code that was proposed, when the person has seen what it changes and
        says so. The code is fetched at that commit, which replaces the version that is kept; the environment and the
        tools were made of the commit that is replaced, so they are taken away, and are made again by the steps that
        made them.

        :param commit: The commit that was proposed, in full, which is what was approved.
        :raises ApiError: If there is no agent with this id, no newer version is proposed, it is not the one that was
            approved, the agent is being worked on, or Git is not installed.
        """
        self.lookup(agent_id)
        if not isinstance(commit, str) or not cloning.COMMIT.fullmatch(commit):
            raise ApiError(422, "invalid", "Say which commit you approve, in full")
        if shutil.which("git") is None:
            raise ApiError(422, "git_missing", "Git is not installed on this machine, and fetching code takes it")
        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            pieces = self.library_pieces(directory, agent)
            proposed = kept_living.update_view(
                kept_living.load_update(directory), pieces[0] if pieces is not None else None
            )
            if pieces is None or proposed is None:
                raise ApiError(409, "no_update", "There is no newer version of the code that is proposed")
            if proposed["to_commit"] != commit:
                raise ApiError(
                    409,
                    "changed",
                    "The newer version that is proposed is not the one that you approved. Look at what it changes.",
                )
            intake = pieces[0]
            try:
                return self.jobs.start(
                    REPOSITORY_JOB,
                    agent_id,
                    f"Fetching the newer version of the code: {agent['title']}",
                    self.cloner(agent_id, intake["url"], commit, intake["limit_bytes"], intake["ref"]),
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def dismiss_update(self, agent_id: str) -> dict[str, Any]:
        """Puts a proposed newer version aside. It is proposed again the next time the agent is looked at, if the code
        is still not at the commit that is kept.

        :raises ApiError: If there is no agent with this id.
        """
        with self._lock:
            directory, _ = self.lookup(agent_id)
            kept_living.drop(directory, kept_living.UPDATE_FILE)

        return self.update(agent_id)

    # The checks of the tools, by what their tutorials did not give them

    def checkable(self, directory: Path, agent: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """The account of the tools that are kept, if they came to the end of their making, and each of them as it is
        kept, with its wrapper's code, which are those that can be checked."""
        _, kept = kept_tools_of(directory, agent)
        if kept is None or not kept["complete"]:
            return None, []
        tools = [tool for one in kept["tools"] if (tool := kept_tools.load_tool(directory, one["name"])) is not None]

        return kept, tools

    def checks(self, agent_id: str) -> dict[str, Any]:
        """What there is of the checks of an agent's tools: each tool, its tier as it was made and its tier now, and
        how each kind of check of it went, with what is allowed and what each kind shows.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.lookup(agent_id)
        usable, problem = building.ready(self.docker_command)
        kept, tools = self.checkable(directory, agent)
        job = self.checks_job(agent_id)

        settings_model = self.workspace.load_settings().model

        return {
            "id": agent_id,
            "docker": {"ready": usable, "message": problem},
            "made": kept is not None,
            "tools": [kept_checks.tool_summary(directory, tool, kept) for tool in tools] if kept is not None else [],
            "settings_model": settings_model,
            "settings_family": asking.family_of(settings_model),
            "kinds": [
                {
                    "kind": kind,
                    **verifying.KIND_INFO[kind],
                    "default": kind in verifying.DEFAULT_KINDS,
                    "model": kind in verifying.MODEL_KINDS,
                }
                for kind in verifying.KINDS
            ],
            "numbers": len(linking.usable_numbers(kept_reading.number_claims(directory))),
            "job": job.snapshot() if job is not None else None,
            "meaning": verifying.MEANING,
            "bases": verifying.BASES,
            "bases_for_b": verifying.BASES_FOR_B,
            "limits": checkwork.limits_of(),
        }

    def check_of_tool(self, agent_id: str, name: str) -> dict[str, Any]:
        """The checks of one tool, each with what it was made of, and the tier that they come to.

        :raises ApiError: If there is no agent with this id, or it has no tool of that name that is as it was made.
        """
        directory, agent = self.lookup(agent_id)
        kept, tools = self.checkable(directory, agent)
        tool = next((one for one in tools if one["name"] == name), None)
        if kept is None or tool is None:
            raise not_found("tool of that PaperAgent")

        return {**kept_checks.tool_summary(directory, tool, kept, details=True), "meaning": verifying.MEANING}

    def start_checks(
        self,
        agent_id: str,
        minutes: Any = None,
        total_minutes: Any = None,
        repeats: Any = None,
        gigabytes: Any = None,
        kinds: Any = None,
        tools: Any = None,
        max_cost: Any = None,
        verifier_model: Any = None,
    ) -> Job:
        """Starts checking the tools by what their tutorials did not give them: each is called, and the code's own
        function with it, with inputs that the tutorial did not pass, and the tests that the code came with that call
        the function are run, all in the environment, in containers that have none of this machine in it and no network.
        If it is asked for, the numbers that the paper reports are looked for in what the tutorials' calls gave, a model
        is asked which of what was found are the quantity that the paper's sentence is about, and the tool is called
        again for those; and a model of another family than the one in the settings is asked for inputs that might tell
        the tool and the code's function apart, which are then tried by a program. Each check is kept as it is made. A
        tool that has passed checks against two different bases and failed none is of tier B.

        :param minutes: The most time that one check of one tool may take.
        :param total_minutes: The most time all of the checks may take together.
        :param repeats: How many times each call is made, to see that it gives the same each time.
        :param gigabytes: The most that one run may write.
        :param kinds: Which kinds of check to make, which are those that need no model if none are named.
        :param tools: Which tools to check, by name, which are all of them if none are named.
        :param max_cost: The most that asking a model may spend, in USD, over all of the kinds that ask one, which is
            said when one of them is asked for, and is not given otherwise.
        :param verifier_model: The model that chooses inputs to try, which is named when the check with inputs that it
            chose is asked for, and is not given otherwise. It must be of a family that is known and is not the one of
            the model in the settings.
        :raises ApiError: If there is no agent with this id, what is given is not fit, Docker is not running, the code
            has not been fetched or its environment not built or its image is not in Docker, no tools were made, the
            paper's numbers are asked for and the paper has none to check against, a key or a price is missing, the
            model that chooses inputs is not of another family, or the agent's paper, code, environment, data,
            tutorials, tools, or checks are being worked on.
        """
        self.lookup(agent_id)
        try:
            limits = verifying.check_limits(minutes, total_minutes, repeats, gigabytes)
            chosen = checkwork.kinds_of(kinds)
            if tools is not None and (
                not isinstance(tools, list)
                or not tools
                or any(not isinstance(name, str) for name in tools)
                or len(set(tools)) != len(tools)
            ):
                raise ValueError("The tools to check are a list of names of tools, each named once")
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error
        asks_a_model = any(kind in verifying.MODEL_KINDS for kind in chosen)
        budget = check_budget(max_cost, "The most it may spend", required=asks_a_model)
        if budget is not None and not asks_a_model:
            raise ApiError(
                422, "invalid", "A limit on spending is for the checks that ask a model, and none is asked for"
            )
        verifier_name = self.verifier_named(verifier_model, verifying.VERIFIER in chosen)
        usable, problem = building.ready(self.docker_command)
        if not usable:
            raise ApiError(422, "docker_missing", problem or "Docker is not running, and checking tools takes it")

        with self._lock:
            directory, agent, _, _, _ = self.image_for_runs(agent_id, "the tools are checked")
            kept, found = self.checkable(directory, agent)
            if kept is None or not found:
                raise ApiError(422, "no_tools", "Make the tools first, as it is tools that are checked")
            claims = kept_reading.number_claims(directory)
            if verifying.PAPER_NUMBERS in chosen and not linking.usable_numbers(claims):
                raise ApiError(
                    422,
                    "no_numbers",
                    "The paper has no number that it reports with digits enough to check against. Read the paper first "
                    "if it has not been read.",
                )
            # Askers that are given one record of what was used keep to one limit
            usage = MeetingUsage()
            judge = self.judge_of(budget, usage) if budget is not None and verifying.PAPER_NUMBERS in chosen else None
            verifier = (
                self.verifier_of(verifier_name, budget, usage)
                if budget is not None and verifier_name is not None
                else None
            )
            if tools is not None:
                known = {tool["name"] for tool in found}
                if any(name not in known for name in tools):
                    raise not_found("tool of that PaperAgent")
                found = [tool for tool in found if tool["name"] in tools]
            folder, _ = data_to_give(directory) if kept["data"] else (None, None)
            if kept["data"] and folder is None:
                raise ApiError(409, "no_data", "The data that the tutorials were given has been taken away.")
            try:
                return self.jobs.start(
                    CHECKS_JOB,
                    agent_id,
                    f"Checking the tools: {agent['title']}",
                    self.checker(agent_id, kept, found, chosen, limits, folder, claims, judge, verifier),
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def checker(
        self,
        agent_id: str,
        kept: dict[str, Any],
        tools: list[dict[str, Any]],
        kinds: Sequence[str],
        limits: verifying.CheckLimits,
        folder: Path | None,
        claims: Sequence[dict[str, Any]] = (),
        judge: linking.Judge | None = None,
        verifier: proposing.Verifier | None = None,
    ) -> Callable[[Job], str | None]:
        """What a job does to check the tools: makes the checks one after another, and keeps each as it is made, so
        that a job that is stopped keeps what it had made."""
        directory = self.workspace.paperagents_dir / agent_id

        def work(job: Job) -> str | None:
            summary, _ = checkwork.check_all(
                job,
                directory,
                self.workspace.root,
                agent_id,
                kept,
                tools,
                kinds,
                limits,
                kept_repository.repo_path(directory),
                folder,
                self.docker_command,
                claims,
                judge,
                verifier,
            )

            return summary

        return work

    def judge_of(self, max_cost: float, usage: MeetingUsage) -> linking.ModelJudge:
        """What asks the model in the settings which of the paper's numbers are the quantity that a result holds, within
        a limit on what it may cost.

        :param usage: What has been used, to which what it uses is added, so that what else is asked keeps to one limit.
        :raises ApiError: If a key it needs is not set, or its price is not known.
        """
        model = self.usable_model()
        try:
            return linking.ModelJudge(model, max_cost, self.chat_models, self.client, usage)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error

    def verifier_named(self, name: Any, asked: bool) -> str | None:
        """The model that is to choose inputs to try, if the check that asks it is asked for: it must be named, and be
        of a family that is known and is not that of the model in the settings, which is the one that read the paper and
        that the person works with, so that what it misses is not what the verifier misses.

        :raises ApiError: If it is named and the check is not asked for, or is not named and the check is asked for, or
            is of the same family as the model in the settings, or of one that is not known, or a key it needs is not
            set, or its price is not known.
        """
        if name is None:
            if asked:
                raise ApiError(
                    422, "invalid", "Name the model of another family that chooses the inputs to try (verifier_model)"
                )
            return None
        if not asked:
            raise ApiError(
                422,
                "invalid",
                "A model to choose inputs is for the check with inputs that a model chose, which is not asked for",
            )
        if not isinstance(name, str) or not name.strip() or has_control_character(name):
            raise ApiError(422, "invalid", "The model that chooses inputs is a name of a model")
        name = name.strip()
        family = asking.family_of(name)
        settings_model = self.workspace.load_settings().model
        settings_family = asking.family_of(settings_model)
        if family is None:
            raise ApiError(
                422,
                "invalid",
                f"It is not known whose model {name} is, so it cannot be told that it is of another family than "
                f"{settings_model}. Name a model of Anthropic, OpenAI, Google, Meta, Mistral, DeepSeek, Qwen, xAI, or "
                "Cohere.",
            )
        if settings_family is None or family == settings_family:
            why = (
                f"{name} is of the same family as {settings_model}, the model in the settings"
                if settings_family is not None
                else f"It is not known whose model {settings_model}, the one in the settings, is"
            )
            raise ApiError(
                422, "invalid", f"{why}, so it would not see what that one does not. Name a model of another family."
            )

        return check_model(name, self.missing_keys)

    def verifier_of(self, model: str, max_cost: float, usage: MeetingUsage) -> proposing.ModelVerifier:
        """What asks a model of another family for inputs to try, within a limit on what it may cost.

        :param usage: What has been used, to which what it uses is added, so that what else is asked keeps to one limit.
        :raises ApiError: If the model cannot be asked.
        """
        try:
            return proposing.ModelVerifier(model, max_cost, self.chat_models, self.client, usage)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error

    # The claims of the paper, tried against what the tutorials gave

    def reproduction(self, agent_id: str) -> dict[str, Any]:
        """What there is of the trying of an agent's claims: each claim of the paper with whether it was reproduced,
        partly, not, or not attempted, and why, and against what; whether the account is of what is kept now; and what
        is needed to try them again.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.lookup(agent_id)
        claims = kept_reading.claims_of(directory)
        reference, _ = kept_tools_of(directory, agent)
        record = kept_reproduction.load(directory)
        current = record is not None and kept_reproduction.is_current(record, reference, claims)
        shown, more = kept_reproduction.table(claims, record, current)
        usable = linking.usable_numbers(claims)
        problem = None
        if not claims:
            problem = ("no_claims", "Read the paper first, as it is the claims that were read from it that are tried")
        elif not usable:
            problem = ("no_numbers", "The paper reports no number with digits enough to be told from one by chance")
        elif reference is None:
            problem = ("no_reference", "Run the tutorials first, as it is what they gave that the claims are held to")
        job = self.reproduction_job(agent_id)
        settings_model = self.workspace.load_settings().model

        return {
            "id": agent_id,
            "ready": problem is None,
            "problem": {"code": problem[0], "message": problem[1]} if problem is not None else None,
            "settings_model": settings_model,
            "numbers": len(usable),
            "reference": kept_reproduction.made_of(reference) if reference is not None else None,
            "kept": (
                {
                    key: record[key]
                    for key in ("started_at", "finished_at", "complete", "model", "cost", "requests", "limit", "notes")
                }
                if record is not None
                else None
            ),
            "current": current,
            "claims": shown,
            "more": more,
            "counts": kept_reproduction.counts_of(shown),
            "job": job.snapshot() if job is not None else None,
            "meaning": reproducing.MEANING,
            "limits": {
                "partly_share": reproducing.PARTLY_SHARE,
                "most_claims": reproducing.MOST_CLAIMS,
                "most_asked": reproducing.MOST_ASKED,
                "batch": reproducing.BATCH,
            },
        }

    def start_reproduction(self, agent_id: str, max_cost: Any = None) -> Job:
        """Starts trying the paper's claims against what the tutorials gave: for each claim that is a number, a program
        finds where in what a tutorial gave it may be, a model of the settings chooses which place the sentence is about
        without being shown any value, and a program holds what was kept there to the number. Nothing is run. What was
        kept of an earlier trying is taken away when the job begins.

        :param max_cost: The most that asking the model may spend, in USD, which must be said.
        :raises ApiError: If there is no agent with this id, the limit is not fit, a key or a price is missing, the
            paper has not been read or reports no number to try, the tutorials have not been run to their end, or the
            agent's paper, code, environment, data, tutorials, tools, or claims are being worked on.
        """
        self.lookup(agent_id)
        budget = check_budget(max_cost, "The most it may spend", required=True)
        assert budget is not None
        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            claims = kept_reading.claims_of(directory)
            if not claims:
                raise ApiError(422, "no_claims", "Read the paper first, as it is its claims that are tried")
            if not linking.usable_numbers(claims):
                raise ApiError(
                    422, "no_numbers", "The paper reports no number with digits enough to be told from one by chance"
                )
            reference, _ = kept_tools_of(directory, agent)
            if reference is None:
                raise ApiError(
                    422,
                    "no_reference",
                    "Run the tutorials, to their end, first, as it is what they gave that the claims are held to",
                )
            picker = self.picker_of(budget, MeetingUsage())
            limits = {"max_cost": budget, "partly_share": reproducing.PARTLY_SHARE}
            repo = kept_repository.repo_path(directory)

            def work(job: Job) -> str:
                # The variants were read at places that the earlier trying held the claims to
                kept_variants.forget(directory)
                return kept_reproduction.reproduce_all(job, directory, reference, claims, picker, repo, limits)

            try:
                return self.jobs.start(
                    REPRODUCTION_JOB,
                    agent_id,
                    f"Trying the claims: {agent['title']}",
                    work,
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def picker_of(self, max_cost: float, usage: MeetingUsage) -> reproducing.ModelPicker:
        """What asks the model in the settings which place in what a tutorial gave a claim's sentence is about, within a
        limit on what it may cost.

        :raises ApiError: If a key it needs is not set, or its price is not known.
        """
        model = self.usable_model()
        try:
            return reproducing.ModelPicker(model, max_cost, self.chat_models, self.client, usage)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error

    def clear_reproduction(self, agent_id: str) -> None:
        """Takes away what was kept of the trying of the claims, so that they are tried again from nothing.

        :raises ApiError: If there is no agent with this id, or its paper is being read, its code fetched, its
            environment built, its data fetched, its tutorials run, its tools made or checked, or its claims tried. The
            variants that were made go too, as they were read at places that the trying held the claims to.
        """
        with self._lock:
            directory, _ = self.lookup(agent_id)
            self.check_idle(agent_id)
            kept_reproduction.forget(directory)
            kept_variants.forget(directory)

    # A function written from the words of a paper that has none of its code

    def reimplementation_problem(self, directory: Path, agent: dict[str, Any]) -> tuple[str, str] | None:
        """Why a function cannot be written from an agent's paper, if it cannot: it is the code of someone else's
        server, the paper's words have not been read, the paper reports no number that a function could be checked
        against, or the agent has tools that run the authors' own code, which are of the method as they ran it."""
        if agent.get("imported") is not None:
            return ("imported", "This agent was imported, and what it can do is what the server that it came from does")
        if agent["paper"].get("file") is None or kept_reading.load_document(directory / PAPER_DIR) is None:
            return ("no_text", "Read the paper first, as it is its words that the function is written from")
        if not linking.usable_numbers(kept_reading.number_claims(directory)):
            return (
                "no_numbers",
                "The paper reports no number with digits enough to be told from one by chance, so a function written "
                "from it could not be checked against anything. Read the paper first if it has not been read",
            )
        _, kept = kept_tools_of(directory, agent)
        if kept is not None and kept["tools"]:
            return (
                "has_tools",
                "This agent has tools that run the authors' own code, which is the method as they ran it",
            )

        return None

    def reimplementation_offer(
        self,
        directory: Path,
        agent: dict[str, Any],
        sections: Any,
        search: Any,
        name: Any,
        goal: Any,
    ) -> dict[str, Any]:
        """What a person is shown, and agrees to, before a function is written: the words of the paper that the model
        would be given, which a program chooses from what the person says and never the model, what the function would
        be called, the model that would write it, and a key that is bound to all of that.

        :param sections: The numbers of the sections to give, as the view lists them. Without it, and without a search,
            those whose headings say that they are of how something was done.
        :param search: Words to look for in the paper, whose best places are given as well.
        :param name: What the function is called, or None for a name made from the paper's title.
        :param goal: What the person wants of it, in their words, which the model is told as theirs.
        :raises ValueError: If what is said is not fit, or the words of the paper that it chooses are none or too many.
        """
        file = agent["paper"]["file"]
        document = kept_reading.load_document(directory / PAPER_DIR)
        assert document is not None
        if sections is not None and not isinstance(sections, list):
            raise ValueError("The sections are a list of their numbers")
        if search is not None:
            if not isinstance(search, str) or has_control_character(search):
                raise ValueError("The words to search for are a few words")
            search = search.strip() or None
        if goal is not None:
            if not isinstance(goal, str) or has_control_character(goal.replace("\n", " ")):
                raise ValueError("What is wanted of the function is said in words")
            goal = goal.strip() or None
            if goal is not None and len(goal) > reimplementing.MAX_GOAL_CHARS:
                raise ValueError(
                    f"What is wanted of the function is at most {reimplementing.MAX_GOAL_CHARS} characters"
                )
        title = agent["title"]
        if name is None:
            name = reimplementing.default_name(title)
        if not isinstance(name, str):
            raise ValueError("A function's name is a name")
        check_function_name(name)
        found = kept_reading.search(document, search, reimplementing.MOST_SEARCHED) if search is not None else []
        chosen = (
            list(sections)
            if sections is not None
            else ([] if search is not None else reimplementing.default_sections(reimplementing.spans_of(document)))
        )
        places, cut = reimplementing.fit(document, reimplementing.choose(document, chosen, found))
        brief = reimplementing.brief_of(title, document, places, goal)
        model = self.workspace.load_settings().model

        return {
            "name": name,
            "goal": goal,
            "search": search,
            "sections": chosen,
            "places": [{**place.to_dict(), "chars": place.end - place.start} for place in places],
            "cut": cut,
            "brief": brief,
            "chars": len(brief),
            "model": model,
            "file_sha256": file["sha256"],
            "key": reimplementing.key_of(brief, name, model, file["sha256"]),
        }

    def reimplementation(
        self,
        agent_id: str,
        sections: Any = None,
        search: Any = None,
        name: Any = None,
        goal: Any = None,
    ) -> dict[str, Any]:
        """What there is of writing a function from an agent's paper: whether it can be, the sections of the paper that
        can be chosen, what the person would be shown and agree to for what they have chosen so far, and what was kept
        of a writing, with the function's code, which they are to read before they rely on it.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.lookup(agent_id)
        file = agent["paper"].get("file")
        problem = self.reimplementation_problem(directory, agent)
        spans: list[reimplementing.Span] = []
        offer = None
        trouble = None
        if problem is None:
            document = kept_reading.load_document(directory / PAPER_DIR)
            assert document is not None
            spans = reimplementing.spans_of(document)
            try:
                offer = self.reimplementation_offer(directory, agent, sections, search, name, goal)
            except ValueError as error:
                trouble = str(error)
        job = self.reimplementation_job(agent_id)

        return {
            "id": agent_id,
            "ready": problem is None,
            "problem": {"code": problem[0], "message": problem[1]} if problem is not None else None,
            "settings_model": self.workspace.load_settings().model,
            "tier": reimplementing.TIER,
            "label": reimplementing.LABEL,
            "meaning": reimplementing.MEANING,
            "sections": [span.to_dict() for span in spans],
            "default_sections": reimplementing.default_sections(spans),
            "offer": offer,
            "choice_problem": trouble,
            "kept": kept_reimplementation.shown(directory, file["sha256"] if file is not None else None),
            "job": job.snapshot() if job is not None else None,
            "checks": self.matching_view(agent_id, directory, agent),
            "limits": {
                "most_chars": reimplementing.MAX_PASSAGES_CHARS,
                "most_goal_chars": reimplementing.MAX_GOAL_CHARS,
                "most_search_chars": kept_reading.MAX_QUERY_CHARS,
                "most_searched": reimplementing.MOST_SEARCHED,
                "most_sections": reimplementing.MAX_SECTIONS,
            },
        }

    def start_reimplementation(
        self,
        agent_id: str,
        agreed: Any,
        max_cost: Any = None,
        sections: Any = None,
        search: Any = None,
        name: Any = None,
        goal: Any = None,
    ) -> Job:
        """Starts writing a function from the words of the paper that the person was shown. A model of the settings is
        given those words, and nothing else of the paper, and writes the function; it is read as Python and imported in
        a container with no network. Nothing else is run, and nothing is checked against the paper yet. What was kept
        of an earlier writing is taken away when the job begins.

        :param agreed: The key of what the person was shown, which must be that of what would be sent now.
        :param max_cost: The most that asking the model may spend, in USD, which must be said.
        :raises ApiError: If there is no agent with this id, the limit is not fit, the person has not agreed, what they
            agreed to is not what would be sent now (409 changed), a key or a price is missing, Docker is not running,
            a function cannot be written from this paper, or the agent is being worked on.
        """
        self.lookup(agent_id)
        if not isinstance(agreed, str) or not agreed:
            raise ApiError(
                422,
                "not_agreed",
                "Agree first, to the words of the paper that the model is to be given, which are shown with their key",
            )
        budget = check_budget(max_cost, "The most it may spend", required=True)
        assert budget is not None
        usable, problem = building.ready(self.docker_command)
        if not usable:
            raise ApiError(422, "docker_missing", problem or "Docker is not running, and writing a function takes it")

        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            trouble = self.reimplementation_problem(directory, agent)
            if trouble is not None:
                raise ApiError(422, trouble[0], trouble[1])
            try:
                offer = self.reimplementation_offer(directory, agent, sections, search, name, goal)
            except ValueError as error:
                raise ApiError(422, "invalid", str(error)) from error
            if offer["key"] != agreed:
                raise ApiError(
                    409,
                    "changed",
                    "What would be sent is not what was shown when you agreed: the words of the paper, the name, the "
                    "model, or the paper itself is not the same. Look at what is offered now",
                    offer=offer,
                )
            model = check_model(offer["model"], self.missing_keys)
            offer["agreed_at"] = utc_timestamp()
            usage = MeetingUsage()
            executor = DockerExecutor(allow_network=False, docker_command=self.docker_command)

            def work(job: Job) -> str:
                return kept_reimplementation.write_function(
                    job, directory, offer, agent["title"], model, budget, executor, self.chat_models, self.client, usage
                )

            try:
                return self.jobs.start(
                    REIMPLEMENTATION_JOB,
                    agent_id,
                    f"Writing a function from the paper: {agent['title']}",
                    work,
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def clear_reimplementation(self, agent_id: str) -> None:
        """Takes away the function that was written from the paper and what was kept of writing it.

        :raises ApiError: If there is no agent with this id, or something is being done to it.
        """
        with self._lock:
            directory, _ = self.lookup(agent_id)
            self.check_idle(agent_id)
            kept_reimplementation.forget(directory)

    # Checking that function against the numbers that the paper reports

    def matching_view(self, agent_id: str, directory: Path, agent: dict[str, Any]) -> dict[str, Any]:
        """What there is of checking the function written from an agent's paper: the claims that would be tried, each
        with its passage and the person's inputs, what was found when it was last checked, the tier and label that come
        of that, and the job if one is going."""
        file = agent["paper"].get("file")
        record = kept_reimplementation.load(directory)
        source = kept_reimplementation.source_of(directory, record) if record is not None else None
        job = self.matching_job(agent_id)

        return {
            **kept_matching.shown(
                directory,
                record,
                source,
                file["sha256"] if file is not None else None,
                kept_reading.number_claims(directory),
                kept_reading.load_document(directory / PAPER_DIR),
            ),
            "job": job.snapshot() if job is not None else None,
        }

    def checked_function(self, directory: Path, agent: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
        """The function written from an agent's paper, as it is kept, if it can be checked: its record, its code, and
        the hash of the paper's file.

        :raises ApiError: If a function cannot be written from the paper, or none was, or it is not of the paper that is
            there now, or its file was changed.
        """
        trouble = self.reimplementation_problem(directory, agent)
        if trouble is not None:
            raise ApiError(422, trouble[0], trouble[1])
        file = agent["paper"]["file"]
        record = kept_reimplementation.load(directory)
        source = kept_reimplementation.source_of(directory, record) if record is not None else None
        if record is None or source is None or not kept_reimplementation.is_current(record, file["sha256"]):
            raise ApiError(
                422,
                "no_function",
                "Write the function from the paper first, as it is what is checked. One that was written from another "
                "file of the paper, or whose file was changed since, is not it",
            )

        return record, source, file["sha256"]

    def start_matching(self, agent_id: str, max_cost: Any = None, ask: Any = True, minutes: Any = None) -> Job:
        """Starts checking the function written from the paper against the numbers that the paper reports. For each
        claim that is tried, the inputs are the person's if they gave some, and otherwise, if a model is to be asked,
        what the model of the settings reads in the passage around the claim, which a program checks against the
        passage. The function is called with them twice in a container with no network, and the claim's number is
        looked for in what it gave. What was kept of an earlier checking is taken away when the job begins.

        :param max_cost: The most that asking the model may spend, in USD, which must be said if it is to be asked.
        :param ask: Whether the model is asked for the inputs of the claims that the person gave none for.
        :param minutes: The most minutes that all of the calls may take together.
        :raises ApiError: If there is no agent with this id, what is said is not fit, a key or a price is missing,
            Docker is not running, there is no function to check, the paper reports no number to try, no model is to
            be asked and the person gave no inputs, or the agent is being worked on.
        """
        self.lookup(agent_id)
        ask = check_flag(ask, "Whether a model reads the inputs from the paper")
        budget = check_budget(max_cost, "The most it may spend", required=ask)
        minutes = check_count(
            matching.DEFAULT_MINUTES if minutes is None else minutes,
            "The most minutes the calls may take",
            1,
            matching.MAX_MINUTES,
        )
        usable, problem = building.ready(self.docker_command)
        if not usable:
            raise ApiError(422, "docker_missing", problem or "Docker is not running, and calling the function takes it")

        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            record, source, paper_sha256 = self.checked_function(directory, agent)
            claims = kept_reading.number_claims(directory)
            document = kept_reading.load_document(directory / PAPER_DIR)
            assert document is not None
            usage = MeetingUsage()
            asker = None
            if ask:
                assert budget is not None
                model = self.usable_model()
                try:
                    asker = matching.InputsAsker(model, budget, self.chat_models, self.client, usage)
                except ValueError as error:
                    raise ApiError(422, "invalid", str(error)) from error
            elif not kept_matching.given_inputs(directory, source, claims):
                raise ApiError(
                    422,
                    "no_inputs",
                    "Give the inputs of a claim, or let a model read them from the paper, as the function has nothing "
                    "to be called with otherwise",
                )

            def work(job: Job) -> str:
                return kept_matching.check_function(
                    job,
                    directory,
                    record["name"],
                    source,
                    paper_sha256,
                    claims,
                    document,
                    asker,
                    usage,
                    minutes,
                    self.workspace.root,
                    self.docker_command,
                    agent_id,
                )

            try:
                return self.jobs.start(
                    MATCHING_JOB,
                    agent_id,
                    f"Checking the function against the paper: {agent['title']}",
                    work,
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def clear_matching(self, agent_id: str) -> None:
        """Takes away what was kept of checking the function against the paper, and keeps the inputs that the person
        gave.

        :raises ApiError: If there is no agent with this id, or something is being done to it.
        """
        with self._lock:
            directory, _ = self.lookup(agent_id)
            self.check_idle(agent_id)
            kept_matching.forget_checks(directory)

    def give_inputs(self, agent_id: str, claim_id: Any, arguments: Any) -> None:
        """Keeps the inputs that the person gives for a claim, which the function is called with for it in place of
        what a model would read, or takes them away. They are checked against the function: by the names of its
        parameters and their types, those without a default given, no bigger than a call may be, and none that holds
        the claim's number, as a function that is given it could give it back. They are the person's to say, and are not
        held to the paper's words.

        :param arguments: The arguments by the names of the parameters, or None to take away those that were given.
        :raises ApiError: If there is no agent with this id, no function to give inputs to, no claim of this id that is
            tried, inputs that cannot be called with, or the agent is being worked on.
        """
        with self._lock:
            directory, agent = self.lookup(agent_id)
            self.check_idle(agent_id)
            record, source, _ = self.checked_function(directory, agent)
            claims = kept_reading.number_claims(directory)
            found = next(
                ((claim, number) for claim, number in linking.usable_numbers(claims) if claim["id"] == claim_id), None
            )
            if found is None:
                raise not_found("claim of the paper that is a number that can be tried, with that id")
            if arguments is not None:
                try:
                    reading = read_function(source, record["name"])
                except FunctionSourceError as error:
                    raise ApiError(422, "no_function", "The function cannot be read as a tool") from error
                why = matching.check_arguments(arguments, reading, found[1], None)
                if why is not None:
                    raise ApiError(422, "invalid", why)
            kept_matching.keep_inputs(directory, source, claims, found[0]["id"], arguments)

    def divergence(self, agent_id: str) -> dict[str, Any]:
        """Where the tutorials of an agent first part from the paper for each claim that was not reproduced, or only
        partly, and what differs between what the paper says it used and what was used here. It is made from what is
        kept each time it is asked for, with nothing run and no model asked, and is only of a trying of the claims that
        is of the run of the tutorials and the claims that are kept now.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.lookup(agent_id)
        claims = kept_reading.claims_of(directory)
        reference, _ = kept_tools_of(directory, agent)
        tried = kept_reproduction.load(directory)
        current = tried is not None and kept_reproduction.is_current(tried, reference, claims)
        problem = None
        if tried is None:
            problem = (
                "no_reproduction",
                "Try the claims first, as it is the claims that did not reproduce that are looked at",
            )
        elif not current:
            problem = (
                "stale",
                "The claims were tried against another run of the tutorials, or other claims, than are kept now. Try "
                "them again",
            )
        base = {
            "id": agent_id,
            "ready": problem is None,
            "problem": {"code": problem[0], "message": problem[1]} if problem is not None else None,
            "current": current,
            "reproduction": kept_reproduction.made_of(reference) if reference is not None and current else None,
            "meaning": diverging.MEANING,
            "limits": {"most_agreed": diverging.MOST_AGREED, "most_calls": diverging.MOST_CALLS},
        }
        if problem is not None or tried is None or reference is None:
            return {
                **base,
                "run": None,
                "claims": [],
                "software": [],
                "differences": [],
                "counts": {"claims": 0, "points": 0, "differences": diverging.counts_of([])},
            }
        evidence = kept_divergence.evidence_of(
            directory, directory / PAPER_DIR, reference, tried, kept_repository.repo_path(directory)
        )
        found = diverging.diverge(tried["claims"], evidence)
        every = [*found.differences, *(each for claim in found.claims for each in claim["differences"])]

        return {
            **base,
            "run": {
                "python": evidence.python,
                "packages": len(diverging.installed_of(evidence.lock)),
                "data": evidence.data,
                "tutorials": len(evidence.details),
            },
            "claims": found.claims,
            "software": found.software,
            "differences": found.differences,
            "counts": {
                "claims": len(found.claims),
                "points": sum(1 for claim in found.claims if claim["point"] is not None),
                "differences": diverging.counts_of(every),
            },
        }

    # The claims' calculations made again with something changed, which a person asks for

    def variants(self, agent_id: str) -> dict[str, Any]:
        """What there is of the variants of an agent's claims: for each claim of the trying, whether its call can be
        made again and with what arguments, and the variants that were made, each with what was changed, what came of
        it, and whether the call with nothing changed gave what the tutorial got. A variant is never the paper's result,
        and what is said of a claim is not changed by one. Nothing is run to make this, and only the variants of the
        trying of the claims that is kept now are shown.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.lookup(agent_id)
        claims = kept_reading.claims_of(directory)
        reference, _ = kept_tools_of(directory, agent)
        trying = kept_reproduction.load(directory)
        current = trying is not None and kept_reproduction.is_current(trying, reference, claims)
        problem = None
        if trying is None:
            problem = (
                "no_reproduction",
                "Try the claims first, as it is a claim that was tried that a variant is made of",
            )
        elif not current:
            problem = (
                "stale",
                "The claims were tried against another run of the tutorials, or other claims, than are kept now. Try "
                "them again",
            )
        record = kept_variants.load(directory)
        kept = (
            record is not None
            and reference is not None
            and trying is not None
            and current
            and kept_variants.is_current(record, reference, trying, claims)
        )
        shown = record["variants"] if record is not None and kept else []
        job = self.variant_job(agent_id)
        checks = checkwork.limits_of()

        return {
            "id": agent_id,
            "ready": problem is None,
            "problem": {"code": problem[0], "message": problem[1]} if problem is not None else None,
            "reproduction": kept_reproduction.made_of(reference) if reference is not None and current else None,
            "claims": self.variant_options(directory, reference, trying) if reference is not None and current else [],
            "variants": shown,
            "stale": len(record["variants"]) if record is not None and not kept else 0,
            "counts": kept_variants.counts_of(shown),
            "job": job.snapshot() if job is not None else None,
            "meaning": varying.MEANING,
            "limits": {
                "most_changes": varying.MOST_CHANGES,
                "max_value_chars": varying.MAX_VALUE_CHARS,
                "max_note_chars": varying.MAX_NOTE_CHARS,
                "most_kept": kept_variants.MOST_KEPT,
                "default_minutes": checks["default_minutes"],
                "max_minutes": checks["max_minutes"],
                "default_repeats": checks["default_repeats"],
                "max_repeats": checks["max_repeats"],
                "default_gigabytes": checks["default_gigabytes"],
                "max_gigabytes": checks["max_gigabytes"],
            },
        }

    def variant_options(
        self, directory: Path, reference: dict[str, Any], trying: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        """For each claim of the trying, what a person may change of the call that it was held to, or why no variant of
        it can be made. The record of each tutorial is read once, and each function is read from the code once."""
        if trying is None:
            return []
        repo = kept_repository.repo_path(directory)
        details: dict[str, dict[str, Any] | None] = {}
        readable: dict[tuple[str, str], list[str] | None] = {}

        def positional_of(code: Path, module: str, function: str) -> list[str] | None:
            if (module, function) not in readable:
                readable[module, function] = verifying.positional_of(code, module, function)

            return readable[module, function]

        found = []
        for entry in trying["claims"]:
            link = entry["link"]
            detail = None
            if link is not None:
                tutorial = link["tutorial"]["id"]
                if tutorial not in details:
                    details[tutorial] = kept_reference.load_detail(directory, reference, tutorial)
                detail = details[tutorial]
            found.append(varying.options_of(entry, detail, repo, positional_of))

        return found

    def start_variant(
        self,
        agent_id: str,
        claim: Any,
        changes: Any,
        minutes: Any = None,
        repeats: Any = None,
        gigabytes: Any = None,
        note: Any = None,
    ) -> Job:
        """Starts making a variant of one of the agent's claims: the call that the claim was held to is made again, in
        the environment, in a container that has none of this machine in it and no network, as the code's own function,
        with the arguments that were named changed and nothing else, and the number at the place that the claim was held
        to is read. The same call with nothing changed is made in the same way, and the variant is comparable only if
        that gave what the tutorial got. What comes of it is kept beside the claim as a variant, which is not the
        paper's result and does not change what was said of the claim.

        :param claim: The id of the claim, which is one that was tried and was held to a call.
        :param changes: The new value of each argument to change, by its name, which are a few and are values that an
            argument is given as: text, a truth value, nothing, a finite number, or a list or table of those.
        :param minutes: The most time that both calls may take together.
        :param repeats: How many times each call is made, to see that it gives the same each time.
        :param gigabytes: The most that a call may write.
        :param note: What the person says of why they ask, which is kept with the variant.
        :raises ApiError: If there is no agent with this id or no such claim, what is given is not fit, Docker is not
            running, the code has not been fetched or its environment not built or its image is not in Docker, the
            tutorials were not run or the claims were not tried, the trying is of another run or other claims than are
            kept now, the claim was not attempted or was not held to a call that can be made again, or the agent's
            paper, code, environment, data, tutorials, tools, or claims are being worked on.
        """
        self.lookup(agent_id)
        try:
            limits = verifying.check_limits(minutes, None, repeats, gigabytes).for_runs()
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error
        if not isinstance(claim, str) or not claim:
            raise ApiError(422, "invalid", "Name the claim by its id")
        if note is not None and (
            not isinstance(note, str) or len(note) > varying.MAX_NOTE_CHARS or has_control_character(note)
        ):
            raise ApiError(422, "invalid", f"A note is text of at most {varying.MAX_NOTE_CHARS} characters")
        usable, problem = building.ready(self.docker_command)
        if not usable:
            raise ApiError(422, "docker_missing", problem or "Docker is not running, and making a variant takes it")

        with self._lock:
            directory, agent, intake, _, _ = self.image_for_runs(agent_id, "the call is made again")
            claims = kept_reading.claims_of(directory)
            if not any(each["id"] == claim for each in claims):
                raise not_found("claim of that PaperAgent")
            reference, _ = kept_tools_of(directory, agent)
            if reference is None:
                raise ApiError(422, "no_reference", "Run the tutorials first, as it is what they gave that is varied")
            trying = kept_reproduction.load(directory)
            if trying is None:
                raise ApiError(
                    422, "no_reproduction", "Try the claims first, as it is a claim that was tried that is varied"
                )
            if not kept_reproduction.is_current(trying, reference, claims):
                raise ApiError(
                    409,
                    "stale",
                    "The claims were tried against another run of the tutorials, or other claims, than are kept now. "
                    "Try them again",
                )
            entry = next((each for each in trying["claims"] if each["id"] == claim), None)
            if entry is None:
                raise ApiError(422, "not_tried", "That claim was not tried. Try the claims first")
            link = entry["link"]
            detail = kept_reference.load_detail(directory, reference, link["tutorial"]["id"]) if link else None
            try:
                plan = varying.plan(entry, detail, kept_repository.repo_path(directory), changes)
            except varying.Refused as refused:
                raise ApiError(422, refused.code, refused.message) from refused
            folder, _ = data_to_give(directory) if reference["data"] is not None else (None, None)
            if reference["data"] is not None and folder is None:
                raise ApiError(409, "no_data", "The data that the tutorials were given has been taken away.")
            bound = kept_variants.bound_to(reference, trying, claims)

            def work(job: Job) -> str:
                return kept_variants.make_variant(
                    job,
                    directory,
                    self.workspace.root,
                    agent_id,
                    intake["commit"],
                    plan,
                    bound,
                    limits,
                    folder,
                    self.docker_command,
                    note,
                )

            try:
                return self.jobs.start(
                    VARIANT_JOB,
                    agent_id,
                    f"Making a variant of a claim: {agent['title']}",
                    work,
                    exclusive=f"paperagent:{agent_id}",
                )
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def clear_variants(self, agent_id: str) -> None:
        """Takes away the variants that were made, which leaves what was said of each claim as it was.

        :raises ApiError: If there is no agent with this id, or its paper is being read, its code fetched, its
            environment built, its data fetched, its tutorials run, its tools made or checked, its claims tried, or a
            variant is being made.
        """
        with self._lock:
            directory, _ = self.lookup(agent_id)
            self.check_idle(agent_id)
            kept_variants.forget(directory)

    def table(self, agent_id: str, kind: str) -> tuple[str, bytes]:
        """What the claims came to, or the variants that were made of them, as a table to open in a spreadsheet, made
        each time from what is kept, with nothing run and no model asked. The claims are listed with where each first
        parts from the paper and how many variants were made, and a claim that is stale is given no more than that it
        is, as it is shown. The variants are listed beside what came of their claims, which they do not change, and
        each says that it is not the paper's result.

        :param kind: "claims" or "variants".
        :return: What to call the file, and what is in it.
        :raises ApiError: If there is no agent with this id, or no such table.
        """
        _, agent = self.lookup(agent_id)
        if kind not in reporting.KINDS:
            raise not_found("table of that PaperAgent")
        reproduction = self.reproduction(agent_id)
        variants = self.variants(agent_id)
        if kind == reporting.CLAIMS:
            content = csv_bytes(
                reporting.CLAIM_COLUMNS,
                reporting.claim_rows(reproduction, self.divergence(agent_id), variants),
            )
        else:
            content = csv_bytes(reporting.VARIANT_COLUMNS, reporting.variant_rows(reproduction, variants))

        return f"{agent['title']} - {kind}", content

    def clear_checks(self, agent_id: str) -> None:
        """Takes away the checks that were made of the tools, so that they are of the tier they were made as until they
        are checked again. The tools are kept.

        :raises ApiError: If there is no agent with this id, or its paper is being read, its code fetched, its
            environment built, its data fetched, its tutorials run, its tools made, or its tools checked.
        """
        with self._lock:
            directory, _ = self.lookup(agent_id)
            self.check_idle(agent_id)
            referencing.remove_runs(agent_id, self.docker_command)
            kept_checks.forget(directory)

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
