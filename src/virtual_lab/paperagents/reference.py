"""Running a paper's tutorials and examples in its environment, and keeping what they did as the reference run.

A tutorial is the nearest thing a project has to a statement of how its code is used, and what it prints and writes is
what the authors' code does with the inputs they chose. Running each in the environment that was built, and keeping the
result, gives later checks something to compare with. It is only that: it shows that the tutorial ran here and what it
gave. It does not show the answer is right, and nothing here says it does.

Each runs in a container made from the image of the environment: with no network, a root that cannot be written to, no
capabilities, none of this machine but its own folder, and ceilings on memory, processes, time, and what it writes. The
project is already in the image, and is copied to the folder, since a tutorial writes beside itself. A tutorial is run
by a small script of ours (tutorial_runner.py) that records what it did, and the code of the tutorial is the authors'.

A tutorial is run more than once, as a reference that two runs do not agree on is not one to hold anything to. What is
compared is what later checks will rely on: the calls that the tutorial made to the project's own functions, with what
went in and what came out, and the files that it wrote. What it printed is compared and said, but it holds timings and
progress bars, so it is not what decides.

Only Python is run. A tutorial in R, Julia, or the shell is listed with that as the reason.
"""

import hashlib
import json
import re
import shutil
import stat
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from virtual_lab.constants import SANDBOX_WORK_DIR
from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerExecutor, DockerUnavailableError, OutputTail
from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents.stock import matches

SCHEMA = 1

RUNNER_FILE = "tutorial_runner.py"
# Where the runner is put in the folder that a run is given, and where the project's data is, if it has some
RUNNER_AT = ".lumi-runner.py"
RESULT_FOLDER = ".lumi-result"
DATA_PATH = "/opt/paper/data"
RUN_PREFIX = "virtual-lab-run-"

# What a person may allow, by default and at most: minutes for one run of one tutorial, minutes for all, how many
# tutorials, how many times each is run, and gigabytes that one may write
DEFAULT_MINUTES = 10
MAX_MINUTES = 60
DEFAULT_TOTAL_MINUTES = 30
MAX_TOTAL_MINUTES = 240
DEFAULT_TUTORIALS = 10
MAX_TUTORIALS = 25
DEFAULT_REPEATS = 2
MAX_REPEATS = 3
DEFAULT_GIGABYTES = 2
MAX_GIGABYTES = 20

# What every run is given of what the machine has, which is what a build is given
TMPFS = "1g"
MAX_FILE_BYTES = 256 * 1024**2
# How often the folder a run writes in is measured, how much of what a run printed is read, and how much of what it
# says of itself is read, and how many lines of what it printed are kept
SIZE_SECONDS = 5.0
OUTPUT_BYTES = 200_000
MAX_RESULT_BYTES = 10 * 1024**2
# What the runner keeps at most, which is held to here as well, since what it wrote is written by the tutorial's own
# process and may say anything: how many calls, files, and cells, and how deeply a value is nested
MAX_RESULT_CALLS = 100
MAX_RESULT_FILES = 200
MAX_RESULT_CELLS = 300
MAX_DEPTH = 40
ITEM_ID = re.compile(r"[0-9]{2,}-[a-z0-9-]+")
KEPT_LINES = 60
MAX_FILE_NAME = 200
MAX_KEPT_FILE = 1 << 20
MAX_KEPT_TOTAL = 20 << 20
# How long after the time that a run is allowed that the runner, inside, ends itself, in case this was stopped
GRACE_SECONDS = 30
# What is left of the time for all of the runs when there is too little to be worth starting another
LEAST_SECONDS = 20
# What Docker's own exit code is when it could not run a container, and not the code of what ran in it
DOCKER_FAILED = 125

# What a person is told a reference run is, wherever it is shown
MEANING = (
    "A reference run shows that each tutorial ran here, and what it gave. It does not show that what it gave is right."
)

STATUSES = ("ok", "failed", "timed_out", "too_big")
FAILURE_KINDS = (
    "needs_network",
    "missing_file",
    "missing_package",
    "needs_gpu",
    "needs_notebook",
    "notebook_unreadable",
    "out_of_memory",
    "timeout",
    "too_big",
    "no_result",
    "error",
)
# What is compared between runs, and what decides whether they agree
COMPARED = ("calls", "files", "output")
DECIDING = ("calls", "files")

NUMBER = (int, float)
ERROR = {"type": str, "message": str, "traceback": [str], "cell": (int, None)}
CELL = {
    "index": int,
    "ok": bool,
    "seconds": NUMBER,
    "output": str,
    "result": (str, None),
    "skipped": [str],
    "error": (ERROR, None),
}
VALUE = {"type": str, "plain": bool}
CALL = {
    "id": int,
    "module": str,
    "function": str,
    "qualname": str,
    "method": bool,
    "file": str,
    "line": int,
    "args": dict,
    "variadic": bool,
    "result": (VALUE, None),
    "returned": bool,
    "cell": (int, None),
    "from": {"file": str, "line": int},
}
FILE = {"path": str, "bytes": int, "sha256": (str, None), "new": bool, "kept": bool}
FAILURE = {"kind": str, "title": str, "detail": str, "tail": [str]}
RESULT = {
    "schema": int,
    "kind": str,
    "path": str,
    "python": str,
    "ok": bool,
    "error": (ERROR, None),
    "seconds": NUMBER,
    "cells": [CELL],
    "cells_total": int,
    "calls": [CALL],
    "calls_seen": int,
    "files": [FILE],
    "files_more": int,
    "packages": [str],
}
RUN = {"status": str, "seconds": NUMBER, "digest": (dict, None)}
DETAIL = {
    "schema": int,
    "id": str,
    "path": str,
    "kind": str,
    "status": str,
    "failure": (FAILURE, None),
    "python": (str, None),
    "seconds": NUMBER,
    "runs": [RUN],
    "stable": (bool, None),
    "differs": [str],
    "output": [str],
    "cells": [CELL],
    "cells_total": int,
    "calls": [CALL],
    "calls_seen": int,
    "files": [FILE],
    "files_more": int,
    "packages": [str],
}

SCRIPT_REASONS = {
    ".r": "It is written in R, and only Python is run here.",
    ".jl": "It is written in Julia, and only Python is run here.",
    ".sh": "It is a shell script, and only Python is run here.",
}
DOCUMENT_REASON = "It is a document that R or Quarto runs, and only Python is run here."

TITLES = {
    "needs_network": "It needs the network",
    "missing_file": "A file it reads is not there",
    "missing_package": "Something it imports is not installed",
    "needs_gpu": "It needs a GPU",
    "needs_notebook": "It uses what only a notebook's own kernel has",
    "notebook_unreadable": "The notebook could not be read",
    "out_of_memory": "It ran out of memory",
    "timeout": "It did not finish in time",
    "too_big": "It wrote more than is allowed",
    "no_result": "It ended without saying how",
    "error": "It stopped with an error",
}
NETWORK = re.compile(
    r"ConnectionError|URLError|gaierror|NameResolutionError|Max retries exceeded|Name or service not known|"
    r"Temporary failure in name resolution|Network is unreachable|Connection refused|ConnectTimeout|"
    r"NewConnectionError|ConnectionResetError",
    re.IGNORECASE,
)
GPU = re.compile(
    r"no NVIDIA driver|CUDA (?:is not available|driver|error|out of memory|initialization)|"
    r"Torch not compiled with CUDA|No CUDA GPUs|cudaGetDevice|Found no NVIDIA",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Limits:
    """What the runs are allowed.

    :param minutes: How long one run of one tutorial may take.
    :param total_minutes: How long all of the runs may take together.
    :param tutorials: How many tutorials are run.
    :param repeats: How many times each is run, to see whether the runs agree.
    :param gigabytes: How much one run may write, counting its copy of the project.
    """

    minutes: int = DEFAULT_MINUTES
    total_minutes: int = DEFAULT_TOTAL_MINUTES
    tutorials: int = DEFAULT_TUTORIALS
    repeats: int = DEFAULT_REPEATS
    gigabytes: int = DEFAULT_GIGABYTES

    def to_dict(self) -> dict[str, Any]:
        return {
            "minutes": self.minutes,
            "total_minutes": self.total_minutes,
            "tutorials": self.tutorials,
            "repeats": self.repeats,
            "gigabytes": self.gigabytes,
            "memory": building.MEMORY,
            "cpus": building.CPUS,
            "pids": building.PIDS,
        }


@dataclass(frozen=True)
class Item:
    """A tutorial that can be run.

    :param id: What its record is kept under, which is made of its place in the list and its name.
    :param path: Where it is in the project.
    :param kind: script or notebook.
    """

    id: str
    path: str
    kind: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "path": self.path, "kind": self.kind}


@dataclass(frozen=True)
class Plan:
    """What would be run, from what was found in the project.

    :param runnable: The tutorials that are Python, each with the id it is kept under.
    :param skipped: The others, each with why.
    :param more: How many tutorials the project has that were not listed, as only so many are.
    """

    runnable: tuple[Item, ...]
    skipped: tuple[dict[str, str], ...]
    more: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "runnable": [item.to_dict() for item in self.runnable],
            "skipped": list(self.skipped),
            "more": self.more,
        }


@dataclass
class Outcome:
    """What came of running one tutorial.

    :param detail: Its record, as it is kept.
    :param files: Where the files that it wrote, which were small enough, were put for the first run.
    """

    detail: dict[str, Any]
    files: Path | None = None


def check_limits(minutes: Any, total_minutes: Any, tutorials: Any, repeats: Any, gigabytes: Any) -> Limits:
    """What a person allowed, with the defaults for what was left out.

    :raises ValueError: If it is not whole numbers within what is allowed.
    """
    values = []
    for name, value, default, most in (
        ("minutes one run may take", minutes, DEFAULT_MINUTES, MAX_MINUTES),
        ("minutes all of the runs may take", total_minutes, DEFAULT_TOTAL_MINUTES, MAX_TOTAL_MINUTES),
        ("tutorials that are run", tutorials, DEFAULT_TUTORIALS, MAX_TUTORIALS),
        ("times each is run", repeats, DEFAULT_REPEATS, MAX_REPEATS),
        ("gigabytes one run may write", gigabytes, DEFAULT_GIGABYTES, MAX_GIGABYTES),
    ):
        if value is None:
            values.append(default)
        elif isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= most:
            raise ValueError(f"The most {name} is a whole number from 1 to {most}")
        else:
            values.append(value)

    return Limits(*values)


def slug(number: int, path: str) -> str:
    """What a tutorial's record is kept under: its place in the list, and its name in letters and digits, so that
    nothing that the project calls a file can be taken for a place."""
    words = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")

    return f"{number:02d}-{words[:50].strip('-') or 'tutorial'}"


def plan(stock: dict[str, Any]) -> Plan:
    """The tutorials that would be run, from the stock that was taken of the project, and why the others would not be.
    Which are Python is read from their names and, for a notebook, from the language it says it is in.
    """
    languages = {item["path"]: item["language"] for item in stock["notebooks"]["listed"]}
    runnable: list[Item] = []
    skipped: list[dict[str, str]] = []
    for tutorial in stock["tutorials"]["listed"]:
        path, kind = tutorial["path"], tutorial["kind"]
        suffix = PurePosixPath(path).suffix.lower()
        reason = None
        if kind == "document":
            reason = DOCUMENT_REASON
        elif kind == "notebook":
            language = languages.get(path)
            if language not in (None, "Python"):
                reason = f"It is a notebook in {language}, and only Python is run here."
            else:
                runnable.append(Item(slug(len(runnable) + 1, path), path, "notebook"))
        elif suffix == ".py":
            runnable.append(Item(slug(len(runnable) + 1, path), path, "script"))
        else:
            reason = SCRIPT_REASONS.get(suffix, "Only Python is run here.")
        if reason is not None:
            skipped.append({"path": path, "kind": kind, "reason": reason})

    return Plan(
        tuple(runnable), tuple(skipped), max(0, stock["tutorials"]["count"] - len(stock["tutorials"]["listed"]))
    )


def is_shallow(value: Any, limit: int = MAX_DEPTH) -> bool:
    """Whether JSON is nested no deeper than a limit. It is looked at without recursion, since a value that is nested
    deeply enough is one that Python cannot be asked to read or write again."""
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if not isinstance(item, (dict, list)):
            continue
        if depth > limit:
            return False
        children = item.values() if isinstance(item, dict) else item
        stack.extend((child, depth + 1) for child in children if isinstance(child, (dict, list)))

    return True


def valid_result(value: Any) -> bool:
    """Whether what a run wrote of itself is a result, in the shape the runner writes, and no bigger than the runner
    keeps. It is written by the same process as the tutorial, and so is not trusted to be anything."""
    if not matches(RESULT, value) or value["schema"] != 1 or value["kind"] not in ("script", "notebook"):
        return False
    if (
        len(value["calls"]) > MAX_RESULT_CALLS
        or len(value["files"]) > MAX_RESULT_FILES
        or len(value["cells"]) > MAX_RESULT_CELLS
    ):
        return False
    values = [call["args"] for call in value["calls"]]

    return (
        all(matches(VALUE, one) for args in values for one in args.values())
        and all(call["result"] is None or matches(VALUE, call["result"]) for call in value["calls"])
        and is_shallow(value)
    )


def is_detail(value: Any) -> bool:
    """Whether what was kept of a tutorial is a record of one, as it is made here."""
    return (
        matches(DETAIL, value)
        and value["schema"] == SCHEMA
        and ITEM_ID.fullmatch(value["id"]) is not None
        and value["status"] in STATUSES
        and (value["failure"] is None or value["failure"]["kind"] in FAILURE_KINDS)
        and all(call["result"] is None or matches(VALUE, call["result"]) for call in value["calls"])
        and all(matches(VALUE, one) for call in value["calls"] for one in call["args"].values())
        and is_shallow(value)
    )


def summary_of(detail: dict[str, Any]) -> dict[str, Any]:
    """What is shown of a tutorial in a list: how it ended, and how much was kept of it."""
    failure = detail["failure"]

    return {
        "id": detail["id"],
        "path": detail["path"],
        "kind": detail["kind"],
        "status": detail["status"],
        "failure": {"kind": failure["kind"], "title": failure["title"]} if failure is not None else None,
        "seconds": detail["seconds"],
        "runs": len(detail["runs"]),
        "stable": detail["stable"],
        "differs": detail["differs"],
        "calls": len(detail["calls"]),
        "files": len(detail["files"]),
        "cells": len(detail["cells"]),
        "cells_total": detail["cells_total"],
    }


def classify(error: dict[str, Any] | None, code: int | None, text: str) -> dict[str, Any]:
    """Why a run did not come to an end that is not a failure, as far as what it says can tell.

    :param error: What the runner recorded of the exception, if it recorded one.
    :param code: How the container ended.
    :param text: What the run printed, which is all there is if it said nothing of itself.
    """
    if error is not None:
        said = "\n".join([error["type"], error["message"], *error["traceback"]])
        tail = list(error["traceback"][-20:]) or [f"{error['type']}: {error['message']}"]
        message = error["message"]
        name = error["type"]
    else:
        said, tail, message, name = text, text.splitlines()[-20:], "", ""
    if name == "NotebookUnreadable":
        kind, detail = "notebook_unreadable", f"{message} Nothing of it was run."
    elif name == "MemoryError" or (error is None and code in (137, -9)):
        kind, detail = "out_of_memory", "It was stopped for using more memory than a run is given."
    elif name == "NameError" and "get_ipython" in message:
        kind, detail = (
            "needs_notebook",
            "It calls IPython's own functions, which are there only in a notebook's kernel. This runs the code of "
            "each cell as Python.",
        )
    elif name in ("ModuleNotFoundError", "ImportError"):
        kind, detail = (
            "missing_package",
            f"{message}. The environment is made of what the authors' files list, and the tutorial wants more.",
        )
    elif name in ("FileNotFoundError", "IsADirectoryError", "NotADirectoryError"):
        kind, detail = (
            "missing_file",
            f"{message}. Data is there only if it was fetched, and a tutorial has to look for it where it is kept.",
        )
    elif GPU.search(said):
        kind, detail = "needs_gpu", "It asks for a GPU, and runs here have none."
    elif NETWORK.search(said):
        kind, detail = (
            "needs_network",
            "It tried to reach something over the network, and runs here have none. If it fetches data when it runs, "
            "fetch that on the Data page first.",
        )
    elif error is None:
        kind, detail = (
            "no_result",
            "It ended without writing what it had done." + (f" Its exit code was {code}." if code else ""),
        )
    else:
        kind, detail = "error", f"{name}: {message}" if name else message

    return {"kind": kind, "title": TITLES[kind], "detail": detail[:500], "tail": [line[:300] for line in tail]}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def digests_of(result: dict[str, Any], output: str) -> dict[str, str]:
    """What a run did, in the parts that are compared with another's: the calls to the project's functions, the files
    written, and what was printed."""
    return {
        "calls": digest([[call["module"], call["qualname"], call["args"], call["result"]] for call in result["calls"]]),
        "files": digest([[file["path"], file["sha256"]] for file in result["files"]]),
        "output": digest([cell["output"] for cell in result["cells"]] if result["cells"] else output),
    }


def compare(first: dict[str, Any], runs: Sequence[dict[str, Any]], recorded: bool) -> tuple[bool | None, list[str]]:
    """Whether the runs after the first did what it did.

    :param first: Its digests.
    :param runs: The digests of each of the runs that came after, or None in place of one that did not end well.
    :param recorded: Whether the first run made a call to the project's functions or wrote a file, since two runs that
        did neither have nothing that they could agree on.
    :return: Whether they agree on the parts that decide, or None if there was nothing to agree on or no second run,
        and the parts that differ from the first in any of them.
    """
    if not runs:
        return None, []
    differs: list[str] = []
    for part in COMPARED:
        if any(run is None or run[part] != first[part] for run in runs):
            differs.append(part)
    if any(run is None for run in runs):
        return False, ["status", *differs]
    if not recorded:
        return None, differs

    return not any(part in differs for part in DECIDING), differs


def mend(function: Callable[[str], Any], path: str, error: BaseException) -> None:
    """Gives back the means to remove what a tutorial made unwritable, which a platform may not remove: the file or
    folder itself, and the folder it is in, which is what has to be written to take it away."""
    for target in (Path(path).parent, Path(path)):
        try:
            if not target.is_symlink():
                target.chmod(stat.S_IRWXU)
        except OSError:
            pass
    function(path)


def remove_tree(folder: Path) -> None:
    if folder.exists():
        shutil.rmtree(folder, onexc=mend)


def folder_size(folder: Path) -> int:
    """How many bytes are in a folder, following no link. A file with more than one name is counted for each, which
    errs on the side of stopping a run early."""
    total = 0
    stack = [folder]
    while stack:
        try:
            with_entries = list(stack.pop().iterdir())
        except OSError:
            continue
        for entry in with_entries:
            try:
                status = entry.lstat()
            except OSError:
                continue
            if stat.S_ISDIR(status.st_mode):
                stack.append(entry)
            elif stat.S_ISREG(status.st_mode):
                total += status.st_size

    return total


def safe_name(name: Any) -> PurePosixPath | None:
    """A path that a file is kept under, if it can only be a place inside the folder it is put in."""
    if not isinstance(name, str) or not name or len(name) > 1000:
        return None
    path = PurePosixPath(name)
    parts = path.parts
    if path.is_absolute() or not parts or any(part in ("", ".", "..") or len(part) > MAX_FILE_NAME for part in parts):
        return None

    return None if any(ord(character) < 32 or character == "\x7f" for character in name) else path


def is_real_folder(path: Path) -> bool:
    return not path.is_symlink() and path.is_dir()


def copy_kept(file: dict[str, Any], source: Path, destination: Path) -> bool:
    """Puts one file that a run kept where it is to be kept, if it is what the run said: a plain file that is not
    reached through a link, of the size and the hash that were said."""
    name = safe_name(file["path"])
    if name is None or file["bytes"] > MAX_KEPT_FILE:
        return False
    try:
        current = source
        for part in name.parts[:-1]:
            current = current / part
            if not is_real_folder(current):
                return False
        origin = current / name.parts[-1]
        status = origin.lstat()
        if not stat.S_ISREG(status.st_mode) or status.st_size != file["bytes"]:
            return False
        data = origin.read_bytes()
        if hashlib.sha256(data).hexdigest() != file["sha256"]:
            return False
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError:
        return False

    return True


def keep_files(result: dict[str, Any], source: Path, destination: Path | None) -> None:
    """Puts the files that a run wrote, which it kept, in a folder of their own. What a tutorial left there is not
    trusted: a file is taken only if it is what the run said it was, and any that is not is said not to have been kept.
    At most so much is kept, whatever the run said.
    """
    room = MAX_KEPT_TOTAL if destination is not None and is_real_folder(source) else 0
    for file in result["files"]:
        if not file["kept"]:
            continue
        file["kept"] = destination is not None and file["bytes"] <= room and copy_kept(file, source, destination)
        if file["kept"]:
            room -= file["bytes"]


def read_result(folder: Path) -> dict[str, Any] | None:
    """What a run wrote of itself, if it is there and is a result. The folder it is in was made by the tutorial's own
    process, and so is not followed if it is a link."""
    where = folder / RESULT_FOLDER
    path = where / "result.json"
    try:
        status = path.lstat()
        if not is_real_folder(where) or not stat.S_ISREG(status.st_mode) or status.st_size > MAX_RESULT_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None

    return value if valid_result(value) else None


def lines_of(text: str) -> list[str]:
    return [line[:300] for line in text.splitlines()[-KEPT_LINES:]]


def kill_container(docker: Sequence[str], name: str) -> None:
    try:
        building.docker_run(docker, "kill", name, timeout=60)
    except Exception:
        pass


def remove_runs(label: str, docker_command: Sequence[str] = ("docker",)) -> int:
    """Removes the containers of runs that were left behind, as a run is not left by anything but a server that was
    stopped hard. Those of one label only, which is of an agent that has no run going.

    :return: How many were removed.
    """
    if not label or building.BUILD_LABEL.fullmatch(label) is None:
        return 0
    try:
        listed = building.docker_run(
            docker_command,
            "ps",
            "--all",
            "--filter",
            f"label={building.AGENT_LABEL}={label}",
            "--format",
            "{{.Names}}",
            timeout=60,
        )
        names = [name for name in listed.stdout.split() if name.startswith(RUN_PREFIX)]
        if listed.returncode != 0 or not names:
            return 0
        building.docker_run(docker_command, "rm", "--force", "--volumes", *names, timeout=300)
    except Exception:
        return 0

    return len(names)


class Runner:
    """What runs the tutorials of one agent's code, each in a container of its own.

    :param tag: The image of the environment.
    :param limits: What is allowed.
    :param scratch: Where the folders that runs are given are made, which is a folder of this machine's and not the
        project's.
    :param data: The folder of the data that was fetched, to be given to the runs to read, or None.
    :param docker_command: How Docker is invoked.
    :param stop: Set when whoever started the runs asks to stop them.
    :param label: Whose they are, so that one that is left can be found.
    :param clock: What time is told by, which the limits on the time of all of the runs are kept with.
    """

    def __init__(
        self,
        tag: str,
        limits: Limits,
        scratch: Path,
        data: Path | None = None,
        docker_command: Sequence[str] = ("docker",),
        stop: threading.Event | None = None,
        label: str = "",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if building.BUILD_LABEL.fullmatch(label) is None:
            raise ValueError("The label of a run is lower case letters, digits, and hyphens")
        self.clock = clock
        self.tag = tag
        self.limits = limits
        self.scratch = scratch
        self.data = data
        self.docker = tuple(docker_command)
        self.stop = stop if stop is not None else threading.Event()
        self.label = label
        self.cpus = building.cpus_for(self.docker)

    def command(self, folder: Path, item: Item, seconds: float, container: str) -> tuple[str, ...]:
        """The docker command that runs a tutorial: everything that the executor of this lab gives code that it runs,
        a container made for a run, and the runner told when to end itself."""
        executor = DockerExecutor(
            image=self.tag,
            allow_network=False,
            memory_limit=building.MEMORY,
            cpu_limit=self.cpus,
            pids_limit=building.PIDS,
            tmpfs_size=TMPFS,
            max_file_bytes=MAX_FILE_BYTES,
            docker_command=self.docker,
            environment={
                "MPLBACKEND": "Agg",
                "PYTHONHASHSEED": "0",
                "LUMI_TIME_LIMIT": str(int(seconds) + GRACE_SECONDS),
                **({"PAPER_DATA": DATA_PATH} if self.data is not None else {}),
            },
        )
        arguments = executor.build_command(
            directory=folder.resolve(),
            command=["python", f"{SANDBOX_WORK_DIR}/{RUNNER_AT}", item.kind, item.path],
            container_name=container,
            mounts=[(self.data, DATA_PATH)] if self.data is not None else [],
        )
        where = len(self.docker) + 1
        label = ("--label", f"{building.AGENT_LABEL}={self.label}") if self.label else ()

        return (*arguments[:where], *label, *arguments[where:])

    def execute(self, folder: Path, item: Item, seconds: float) -> tuple[str, int | None, str]:
        """Runs a tutorial, and waits for it to end or for a limit to be reached.

        :return: How it ended: done, timed_out, too_big, or stopped; its exit code; and what it printed, the end of it.
        """
        container = f"{RUN_PREFIX}{self.label + '-' if self.label else ''}{uuid4().hex[:12]}"
        arguments = self.command(folder, item, seconds, container)
        process = subprocess.Popen(
            list(arguments), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL
        )
        assert process.stdout is not None
        tail = OutputTail(process.stdout, OUTPUT_BYTES)
        deadline = time.monotonic() + seconds
        next_size = time.monotonic() + SIZE_SECONDS
        ended = "done"
        try:
            while True:
                try:
                    process.wait(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    pass
                now = time.monotonic()
                if self.stop.is_set():
                    ended = "stopped"
                elif now > deadline:
                    ended = "timed_out"
                elif now >= next_size:
                    next_size = now + SIZE_SECONDS
                    if folder_size(folder) > self.limits.gigabytes * 1024**3:
                        ended = "too_big"
                if ended != "done":
                    break
        finally:
            if process.poll() is None:
                kill_container(self.docker, container)
                process.kill()
            process.wait()
        text = tail.text(wait=5.0)

        return ended, process.returncode, text

    def run(self, item: Item, seconds: float, keep: Path | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Runs a tutorial once.

        :param seconds: How long it may take.
        :param keep: A folder to put the files that it wrote in, if they are to be kept.
        :return: What it came to, as the status, the failure if there is one, its seconds, and the output; and what the
            runner wrote of it, if it wrote anything that is a result.
        :raises StoppedError: If whoever started the runs asked to stop them.
        :raises DockerUnavailableError: If Docker did not run it, which is not a failure of the tutorial.
        """
        began = self.clock()
        folder = self.scratch / f"run-{uuid4().hex[:12]}"
        folder.mkdir()
        try:
            shutil.copyfile(Path(__file__).with_name(RUNNER_FILE), folder / RUNNER_AT)
            ended, code, text = self.execute(folder, item, seconds)
            if ended == "stopped":
                raise StoppedError("Stopped.")
            result = read_result(folder)
            if result is None and ended == "done" and code == DOCKER_FAILED:
                said = " ".join(lines_of(text)[-3:]) or "it gave no reason"
                raise DockerUnavailableError(f"Docker did not run the tutorial: {said}")
            seconds_taken = round(self.clock() - began, 1)
            failure = None
            if ended == "timed_out":
                status = "timed_out"
                failure = {
                    "kind": "timeout",
                    "title": TITLES["timeout"],
                    "detail": f"It was stopped after {int(seconds)} seconds, which is what it was given.",
                    "tail": lines_of(text)[-20:],
                }
            elif ended == "too_big":
                status = "too_big"
                failure = {
                    "kind": "too_big",
                    "title": TITLES["too_big"],
                    "detail": f"It was stopped for writing more than {self.limits.gigabytes} gigabytes.",
                    "tail": lines_of(text)[-20:],
                }
            elif result is not None and result["ok"]:
                status = "ok"
            else:
                status = "failed"
                failure = classify(result["error"] if result is not None else None, code, text)
            if result is not None and ended == "done":
                keep_files(result, folder / RESULT_FOLDER / "files", keep)
            elif result is not None:
                for file in result["files"]:
                    file["kept"] = False
        finally:
            remove_tree(folder)

        return {"status": status, "failure": failure, "seconds": seconds_taken, "output": lines_of(text)}, result

    def tutorial(self, item: Item, seconds: float, keep: Path | None = None, until: float | None = None) -> Outcome:
        """Runs a tutorial the number of times that was allowed, and says what came of it. The first run is the
        reference, and the others are to see whether it is one that can be held to.

        :param seconds: How long one run may take.
        :param keep: A folder for the files that the first run wrote.
        :param until: When, by the clock of the runner, to run no more.
        """
        first, result = self.run(item, seconds, keep)
        runs = [{"status": first["status"], "seconds": first["seconds"], "digest": None}]
        later: list[dict[str, Any] | None] = []
        if result is not None:
            output = "\n".join(first["output"])
            runs[0]["digest"] = digests_of(result, output)
        while first["status"] == "ok" and result is not None and len(runs) < self.limits.repeats:
            left = (until - self.clock()) if until is not None else seconds
            if left < LEAST_SECONDS:
                break
            again, repeat = self.run(item, min(seconds, left))
            marks = (
                digests_of(repeat, "\n".join(again["output"]))
                if repeat is not None and again["status"] == "ok"
                else None
            )
            runs.append({"status": again["status"], "seconds": again["seconds"], "digest": marks})
            later.append(marks)
        recorded = result is not None and bool(result["calls"] or result["files"])
        stable, differs = compare(runs[0]["digest"], later, recorded) if runs[0]["digest"] else (None, [])
        detail = {
            "schema": SCHEMA,
            "id": item.id,
            "path": item.path,
            "kind": item.kind,
            "status": first["status"],
            "failure": first["failure"],
            "python": result["python"] if result is not None else None,
            "seconds": round(sum(run["seconds"] for run in runs), 1),
            "runs": runs,
            "stable": stable,
            "differs": differs,
            "output": first["output"],
            "cells": result["cells"] if result is not None else [],
            "cells_total": result["cells_total"] if result is not None else 0,
            "calls": result["calls"] if result is not None else [],
            "calls_seen": result["calls_seen"] if result is not None else 0,
            "files": result["files"] if result is not None else [],
            "files_more": result["files_more"] if result is not None else 0,
            "packages": result["packages"] if result is not None else [],
        }

        return Outcome(detail, keep)


def run_reference(
    runner: Runner,
    items: Sequence[Item],
    on_start: Callable[[Item, int, int], None],
    on_outcome: Callable[[Item, Outcome], None],
    keep: Callable[[Item], Path | None],
) -> list[dict[str, str]]:
    """Runs the tutorials one after another, within the time that is allowed for all of them.

    :param keep: Gives the folder that the files a tutorial wrote are to be put in.
    :param on_start: Called as each is started, with its place and how many there are.
    :param on_outcome: Called as each is finished, with what came of it.
    :return: The tutorials that were not run, each with why.
    :raises StoppedError: If whoever started the runs asked to stop them. What was run before is not lost, as it was
        passed on when it finished.
    """
    limits = runner.limits
    until = runner.clock() + limits.total_minutes * 60
    not_run: list[dict[str, str]] = []
    chosen = list(items[: limits.tutorials])
    not_run.extend(
        {"path": item.path, "reason": f"Only {limits.tutorials} tutorials are run at a time."}
        for item in items[limits.tutorials :]
    )
    for number, item in enumerate(chosen, 1):
        if runner.stop.is_set():
            raise StoppedError("Stopped.")
        left = until - runner.clock()
        if left < LEAST_SECONDS:
            not_run.extend(
                {"path": other.path, "reason": f"The {limits.total_minutes} minutes for all of the runs were used."}
                for other in chosen[number - 1 :]
            )
            break
        on_start(item, number, len(chosen))
        on_outcome(item, runner.tutorial(item, min(limits.minutes * 60, left), keep(item), until))

    return not_run
