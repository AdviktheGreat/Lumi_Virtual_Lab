"""Watching what an agent is pinned to, and what a change in it would be, without changing any of it.

An agent is made of one commit of the authors' code and of an environment that was built from it. Both go out of date,
and a person who comes back to an agent after months has to be told whether it still works. What is looked at is only
read, and none of it is run:

- the source: where the code was fetched from, asked for the commit that its ref is at now (`git ls-remote`, which
  fetches nothing). A ref that is at the commit that was fetched has not moved; one that is at another commit has; one
  that is not there, or whose project is not, is gone; one that could not be asked is unknown. A commit does not move.
- the dependencies: each version that a pip lock pins is asked of the package index, which says whether it is still
  there, and whether it was yanked, which is what a build of the lock would fail on, or would be warned of.
- what a newer commit would change: the files of the version that is kept and of the newer one, held side by side, as
  a diff that is bounded, and which of the tools are of a file that changed.

What the person is told, as one word, follows from these and from the tools' own recorded calls, which are run in the
environment that is kept (`health_of`). Nothing here decides that a change is a repair: a newer version is shown, and is
taken only when the person says so.
"""

import difflib
import hashlib
import http.client
import json
import os
import re
import shutil
import ssl
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from virtual_lab.paperagents.repository import COMMIT, RepositoryError, explain, git_environment, run_git, scrub

HEALTHY = "healthy"
DEGRADED = "degraded"
BROKEN = "broken"
UNCHECKED = "unchecked"
STATUSES = (HEALTHY, DEGRADED, BROKEN, UNCHECKED)

# What of the source is found: it has not moved, it has, it is not there, it could not be asked, or it is one commit
SAME = "same"
MOVED = "moved"
GONE = "gone"
UNKNOWN = "unknown"
PINNED = "pinned"

# What the index says of a version that a lock pins
FOUND = "found"
YANKED = "yanked"
MISSING = "missing"

# What the words mean, which is shown with them
MEANING = (
    "Healthy is that the tools gave again, in the environment that is kept, what their tutorials got, and nothing that "
    "was looked at is gone. Degraded is that something is wrong and the tools may still be used: a tool gave something "
    "else, a version that the lock pins cannot be had, or the source is gone. Broken is that the tools cannot be used "
    "as they are: the environment's image is gone, or no tool gave again what its tutorials got. Unchecked is that "
    "nothing wrong was found but the tools were not run. A newer version of the code is not a state: the version that "
    "is kept stays as it is until a newer one is approved, and gets no repair that was not looked at."
)

# How long asking of a ref may take, and how many versions are asked of the index at most, and how long all of them may
ASK_SECONDS = 60
MOST_PINS = 150
PINS_SECONDS = 90
INDEX_HOST = "pypi.org"
REQUEST_SECONDS = 10
MAX_INDEX_BYTES = 4 << 20

PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]{0,99})==([A-Za-z0-9][A-Za-z0-9._+!-]{0,99})")

# What of a diff is shown: how many files with their lines, how much of one, how much of all, and how many files are
# only listed. A file bigger than the first is not read
MOST_SHOWN = 40
MOST_LISTED = 400
MAX_FILE_BYTES = 512 * 1024
MAX_FILE_DIFF = 6000
MAX_ALL_DIFF = 60000
# The most lines, of the two versions of a file together, that are compared, as comparing grows with the square of them
MAX_DIFF_LINES = 4000
MAX_WALK_FILES = 100_000

# Files that say what an environment is made of, which a change in decides whether the one that is kept is still right
ENVIRONMENT_FILES = frozenset(
    {
        "environment.yml",
        "environment.yaml",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "pipfile",
        "pipfile.lock",
        "poetry.lock",
        "dockerfile",
        "conda.yml",
        "conda.yaml",
    }
)


@dataclass(frozen=True)
class Probe:
    """What was found of the source.

    :param state: SAME, MOVED, GONE, UNKNOWN, or PINNED.
    :param commit: The commit that the ref is at now, if it was told.
    :param message: What it comes to, in a sentence.
    """

    state: str
    commit: str | None
    message: str


def wanted(ref: str) -> list[str]:
    """What is asked of the remote for a ref: the project's default, or the branch or tag by that name."""
    if ref == "HEAD":
        return ["HEAD"]

    return [f"refs/heads/{ref}", f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}"]


def commit_of(said: str, ref: str) -> str | None:
    """The commit that Git's list of refs puts a ref at, a tag by the commit it is of."""
    found: dict[str, str] = {}
    for line in said.splitlines():
        sha, _, name = line.partition("\t")
        if COMMIT.fullmatch(sha):
            found[name.strip()] = sha
    order = ["HEAD"] if ref == "HEAD" else [f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}", f"refs/heads/{ref}"]

    return next((found[name] for name in order if name in found), None)


def probe_source(
    url: str, ref: str, commit: str, seconds: float = ASK_SECONDS, protocols: str = "https", folder: Path | None = None
) -> Probe:
    """Asks where a ref is now, without fetching anything, and says what that is to the commit that was fetched.

    :param url: Where the code was fetched from.
    :param ref: What was asked for then: a branch, a tag, a commit, or HEAD.
    :param commit: The commit that was fetched.
    :param protocols: What Git may ask by, which is not changed except by a test.
    """
    if COMMIT.fullmatch(ref):
        return Probe(PINNED, None, "It was fetched at one commit, which does not move.")
    if shutil.which("git") is None:
        return Probe(UNKNOWN, None, "Git is not installed on this machine, so the code's source was not asked.")
    with tempfile.TemporaryDirectory(prefix="git-home.", dir=folder) as home:
        try:
            said = run_git(
                ["ls-remote", "--", url, *wanted(ref)], Path(home), git_environment(Path(home), protocols), seconds
            )
        except RepositoryError as error:
            text = explain(scrub(str(error), home), url, ref)
            lowered = text.lower()
            if "not found" in lowered or ("no " in lowered and "can be fetched" in lowered):
                return Probe(GONE, None, f"{url} cannot be found any more. {text}"[:400])
            return Probe(UNKNOWN, None, f"The source could not be asked: {text}"[:400])
    now = commit_of(said, ref)
    if now is None:
        return Probe(GONE, None, f"{url} has no {ref!r} any more.")
    if now == commit:
        return Probe(SAME, now, "The code is where it was fetched from, at the same commit.")

    return Probe(MOVED, now, f"{ref!r} is now at {now[:12]}, and the code that is kept is of {commit[:12]}.")


class Index:
    """What a package index says of a version: whether it is there, and whether it was yanked. This one is PyPI, asked
    at one host and at one kind of address that is built from a name and a version that were checked, and which does not
    follow a redirect, so that it asks nowhere else."""

    def status(self, name: str, version: str) -> str | None:
        """FOUND, YANKED, MISSING, or None if the index could not be asked or did not say. A local version (2.1.0+cu118)
        is of a build that is not on the index, so the index is not asked of it."""
        if "+" in version or PIN.fullmatch(f"{name}=={version}") is None:
            return None
        connection = http.client.HTTPSConnection(
            INDEX_HOST, timeout=REQUEST_SECONDS, context=ssl.create_default_context()
        )
        try:
            connection.request(
                "GET",
                f"/pypi/{quote(name, safe='')}/{quote(version, safe='')}/json",
                headers={"Accept": "application/json", "User-Agent": "lumi-paperagents"},
            )
            response = connection.getresponse()
            if response.status == 404:
                return MISSING
            if response.status != 200:
                return None
            body = response.read(MAX_INDEX_BYTES + 1)
        except (OSError, http.client.HTTPException):
            return None
        finally:
            connection.close()
        if len(body) > MAX_INDEX_BYTES:
            return None
        try:
            files = json.loads(body).get("urls")
        except (ValueError, AttributeError, RecursionError):
            return None
        if not isinstance(files, list):
            return None
        if not files:
            return MISSING

        return YANKED if all(isinstance(one, dict) and one.get("yanked") is True for one in files) else FOUND


def pins_of(lock: str) -> list[tuple[str, str]]:
    """The versions that a pip lock pins, as names and versions, each once."""
    found: dict[tuple[str, str], None] = {}
    for line in lock.splitlines():
        match = PIN.fullmatch(line.split(";")[0].strip())
        if match is not None:
            found[(match.group(1), match.group(2))] = None

    return list(found)


def look_at_pins(
    lock: str,
    index: Index,
    should_stop: Callable[[], bool] | None = None,
    most: int = MOST_PINS,
    seconds: float = PINS_SECONDS,
) -> dict[str, Any]:
    """Asks the index of each version that a pip lock pins, until the most that are asked or the time is out.

    :return: How many pins there are and how many were asked of, those that are gone or yanked, and how many the index
        did not say of.
    """
    pins = pins_of(lock)
    deadline = time.monotonic() + seconds
    problems = []
    looked = unsaid = 0
    for name, version in pins[:most]:
        if time.monotonic() > deadline or (should_stop is not None and should_stop()):
            break
        state = index.status(name, version)
        looked += 1
        if state is None:
            unsaid += 1
        elif state != FOUND:
            problems.append({"name": name, "version": version, "state": state})

    return {"total": len(pins), "looked_at": looked, "unsaid": unsaid, "problems": problems}


def files_of(root: Path) -> dict[str, Path]:
    """The regular files of a folder by their path from it, with links and Git's own files left out."""
    found: dict[str, Path] = {}
    for current, folders, names in os.walk(root, followlinks=False):
        folders[:] = sorted(name for name in folders if name != ".git" and not (Path(current) / name).is_symlink())
        for name in sorted(names):
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                continue
            found[path.relative_to(root).as_posix()] = path
            if len(found) > MAX_WALK_FILES:
                return found

    return found


def digest_of(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            sha.update(block)

    return sha.hexdigest()


def lines_of(path: Path) -> list[str] | None:
    """The lines of a text file, or None if it is too big or is not text."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None

    return data.decode("utf-8", errors="replace").splitlines()


def diff_trees(old: Path, new: Path, should_stop: Callable[[], bool] | None = None) -> dict[str, Any]:
    """What differs between the files of two folders, as a diff that is bounded: which files were added, taken away, or
    changed, and for the first of those that changed, the lines. A file that is too big, or is not text, is said to be
    changed and is not read. The paths of all that differ are given too, as only the first of them are listed.

    Only the files whose lines are shown are compared, so that the work is bounded too: of the others, the lines that
    were added or taken away are counted if the file is new or gone, and are not (None) if it is changed.

    :param should_stop: Asked between files; if it says so, what was done is given and is not the whole.
    """
    before, after = files_of(old), files_of(new)
    listed: list[dict[str, Any]] = []
    shown = spent = 0
    for path in sorted(before.keys() | after.keys()):
        if should_stop is not None and should_stop():
            break
        if path in before and path in after:
            if digest_of(before[path]) == digest_of(after[path]):
                continue
            change = "changed"
        else:
            change = "added" if path in after else "removed"
        entry: dict[str, Any] = {"path": path, "change": change, "added": 0, "removed": 0, "diff": None, "cut": False}
        was = lines_of(before[path]) if change != "added" else []
        now = lines_of(after[path]) if change != "removed" else []
        if was is None or now is None:
            entry["binary"] = True
        else:
            entry["binary"] = False
            if shown < MOST_SHOWN and spent < MAX_ALL_DIFF and len(was) + len(now) <= MAX_DIFF_LINES:
                made = list(difflib.unified_diff(was, now, f"a/{path}", f"b/{path}", lineterm="", n=2))
                entry["added"] = sum(1 for line in made if line.startswith("+") and not line.startswith("+++"))
                entry["removed"] = sum(1 for line in made if line.startswith("-") and not line.startswith("---"))
                text = "\n".join(made)
                allowed = min(MAX_FILE_DIFF, MAX_ALL_DIFF - spent)
                entry["diff"] = text[:allowed]
                entry["cut"] = len(text) > allowed
                spent += len(entry["diff"])
                shown += 1
            elif change == "changed":
                entry["added"] = entry["removed"] = None
            else:
                entry["added"], entry["removed"] = len(now), len(was)
        listed.append(entry)

    return {
        "changed": len(listed),
        "added": sum(1 for entry in listed if entry["change"] == "added"),
        "removed": sum(1 for entry in listed if entry["change"] == "removed"),
        "files": listed[:MOST_LISTED],
        "paths": [entry["path"] for entry in listed],
        "truncated": len(listed) > MOST_LISTED
        or any(entry["diff"] is None and not entry["binary"] or entry["cut"] for entry in listed),
    }


def affected(tools: Sequence[dict[str, Any]], paths: Sequence[str]) -> list[str]:
    """Which tools are of a file that changed, which is the file of the module that holds the function that each is a
    wrapper of. A tool that is of a function that calls another file is not told of by this."""
    names = []
    for tool in tools:
        module = tool["repo"]["module"].replace(".", "/")
        for path in paths:
            if path in (f"{module}.py", f"{module}/__init__.py") or path.endswith(
                (f"/{module}.py", f"/{module}/__init__.py")
            ):
                names.append(tool["name"])
                break

    return names


def environment_files(paths: Sequence[str]) -> list[str]:
    """Which of the files that changed are ones that say what an environment is made of."""
    return [
        path
        for path in paths
        if path.rsplit("/", 1)[-1].lower() in ENVIRONMENT_FILES
        or re.fullmatch(r"(?:.*/)?requirements(?:[^/]*\.(?:txt|in)|/[^/]+\.(?:txt|in))", path.lower()) is not None
    ]


def health_of(
    source: dict[str, Any],
    image_present: bool | None,
    pins: dict[str, Any] | None,
    tools: list[dict[str, Any]] | None,
    tools_message: str | None,
) -> tuple[str, list[str]]:
    """The one word for how an agent is, and why, from what was found.

    Broken is that the tools cannot be used as they are: the environment's image is gone, or no tool gave again what its
    tutorials got. Degraded is that something is wrong and the tools may still be used: one gave something else, a
    version that the lock pins is gone or was yanked, or the source is gone. Unchecked is that nothing is wrong that was
    found, but the tools were not run, so that it is not known that they work. A newer commit is not any of these; it is
    told of apart, since the version that is kept still works.

    :param source: What was found of the source (state and message).
    :param image_present: Whether the environment's image is in Docker, or None if Docker could not be asked.
    :param pins: What was found of the pins, or None if they were not asked of.
    :param tools: Each tool as it was run (name, calls, matched, message), or None if they were not run. A tool with no
        recorded call that could be run again was not held to anything, and is left out of what is said.
    :param tools_message: Why the tools were not run, if they were not.
    """
    reasons: list[str] = []
    if image_present is False:
        return BROKEN, ["The image of the environment is not in Docker any more, so the tools cannot be run."]
    status = HEALTHY
    if source["state"] == GONE:
        status = DEGRADED
        reasons.append(f"The source is gone: {source['message']}")
    if pins is not None and pins["problems"]:
        status = DEGRADED
        gone = [f"{one['name']}=={one['version']} ({one['state']})" for one in pins["problems"][:5]]
        reasons.append(
            f"{len(pins['problems'])} pinned version{'s' if len(pins['problems']) != 1 else ''} cannot be installed "
            f"again as they are: {', '.join(gone)}"
        )
    held = [tool for tool in tools or [] if tool["calls"]]
    if not held:
        if status == HEALTHY:
            status = UNCHECKED
        reasons.append(
            tools_message
            or ("The tools were not run." if tools is None else "No tool has a recorded call that could be run again.")
        )
    else:
        wrong = [tool for tool in held if tool["matched"] < tool["calls"]]
        if len(wrong) == len(held):
            return BROKEN, [*reasons, "No tool gave again what its tutorials got: " + "; ".join(map(_why, wrong[:3]))]
        if wrong:
            status = DEGRADED
            reasons.append("Some tools did not give again what their tutorials got: " + "; ".join(map(_why, wrong[:3])))

    return status, reasons


def _why(tool: dict[str, Any]) -> str:
    return f"{tool['name']} ({tool['matched']} of {tool['calls']} calls)" + (
        f": {tool['message']}" if tool.get("message") else ""
    )
