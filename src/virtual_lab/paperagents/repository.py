"""Getting the code of a paper from where it is kept, without running any of it.

The code is fetched with Git, as one commit and none of its history, and written out as files. Nothing in what comes
is run: Git is run with the settings of the person who uses this machine put aside, with no hook, no filter, no
credential helper, and only https, and what it writes is files, with a symbolic link written as a file that holds
where it points, so that nothing in the project can reach out of the folder it is in. Submodules and files that the
project keeps in Git LFS are not fetched, and are noticed in what is taken stock of instead. The folder is cut to its
files: Git's own files are taken away, so that nothing later is run in a folder that Git would act on.

How much is fetched is limited, and it is the limit that is watched while Git works, since a project's size is not known
before it is fetched. A project over the limit is refused, and says how far it got.
"""

import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from virtual_lab.chat import describe_size
from virtual_lab.environment import StoppedError

# The most bytes that are fetched by default, and the most that the limit may be raised to, counted for the history that
# is fetched and then for the files that are written out, each on its own
MEGABYTE = 1024 * 1024
DEFAULT_MEGABYTES = 200
MAX_MEGABYTES = 1000
DEFAULT_BYTES = DEFAULT_MEGABYTES * MEGABYTE

# How long Git may take for each of the steps, and how often it is looked at while it works
GIT_SECONDS = 300
WATCH_SECONDS = 0.5

# What a commit, a tag, or a branch is called that is asked for. It never begins with a dash, which Git would take for
# an option
REF = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./@+-]{0,199}")
COMMIT = re.compile(r"[0-9a-f]{40}")

# What of the person's environment Git keeps: where it finds programs, how it reaches the internet by a proxy, and which
# certificates it trusts
KEPT_VARIABLES = (
    "PATH",
    "SYSTEMROOT",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "CURL_CA_BUNDLE",
    "GIT_SSL_CAINFO",
)

# What Git is told on every command, whatever else is set: nothing is run for a hook or a credential, symbolic links
# are not made, and the files of a project are written as they are, with no program applied to them
SAFE_SETTINGS = (
    "core.hooksPath=/dev/null",
    "core.symlinks=false",
    "core.fsmonitor=false",
    "credential.helper=",
    "protocol.version=2",
    "submodule.recurse=false",
    "fetch.recurseSubmodules=false",
    "advice.detachedHead=false",
    "gc.auto=0",
)


class RepositoryError(Exception):
    """Code that could not be fetched, with why, in words for the person who asked for it."""


class RepositoryTooBigError(RepositoryError):
    """Code that is bigger than the limit.

    :param seen: The bytes that had been fetched when it was stopped, which is at least the limit.
    :param limit: The limit.
    """

    def __init__(self, message: str, seen: int, limit: int) -> None:
        super().__init__(message)
        self.seen = seen
        self.limit = limit


@dataclass(frozen=True)
class Cloned:
    """Code that was fetched.

    :param commit: The commit that the files are of, all of its 40 characters, which is what makes it the same code
        later.
    :param ref: What was asked for: a branch, a tag, or a commit, or HEAD, which is the project's default branch.
    """

    commit: str
    ref: str


def check_ref(ref: str | None) -> str:
    """What is asked for of a project, as Git is asked for it.

    :raises RepositoryError: If it is not the name of a branch or a tag, or a commit.
    """
    if ref is None or not ref.strip():
        return "HEAD"
    text = ref.strip()
    if not REF.fullmatch(text) or ".." in text or text.endswith((".", "/", ".lock")) or "//" in text:
        raise RepositoryError(f"{text[:80]!r} is not the name of a branch or a tag, or a commit")

    return text


def git_environment(home: Path, protocols: str) -> dict[str, str]:
    """What Git is run with: a few of the person's own variables, and a home that has nothing in it, so that none of
    their settings, hooks, or credentials are used, and no prompt can be waited on."""
    environment = {name: os.environ[name] for name in KEPT_VARIABLES if name in os.environ}
    environment.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / "config"),
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_ALLOW_PROTOCOL=protocols,
        GIT_LFS_SKIP_SMUDGE="1",
        GIT_OPTIONAL_LOCKS="0",
        GIT_ASKPASS="",
        GIT_EXTERNAL_DIFF="",
        GIT_PAGER="cat",
    )

    return environment


def size_of(folder: Path) -> int:
    """The bytes in the files in a folder and below it, not following links."""
    total = 0
    for directory, _, files in os.walk(folder):
        for file in files:
            try:
                total += os.lstat(os.path.join(directory, file)).st_size
            except OSError:
                continue

    return total


def stop_git(process: "subprocess.Popen[str]") -> None:
    """Stops Git and what it started, such as the program that talks https for it, which a kill of Git alone leaves
    going."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except OSError:
        pass
    try:
        process.communicate(timeout=10)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


def too_big(seen: int, limit: int) -> RepositoryTooBigError:
    return RepositoryTooBigError(
        f"The code is more than {describe_size(limit)}, which is the most that is fetched. "
        f"It had come to {describe_size(seen)}.",
        seen,
        limit,
    )


def run_git(
    arguments: list[str],
    folder: Path,
    environment: dict[str, str],
    seconds: float,
    watched: Path | None = None,
    limit: int | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> str:
    """Runs Git in a folder, and gives what it wrote.

    :param watched: A folder to watch the size of while it works, which is stopped if it grows past limit.
    :raises RepositoryError: If Git is not installed, does not finish in time, or fails, which says what it said.
    :raises RepositoryTooBigError: If the watched folder grew past the limit.
    :raises StoppedError: If should_stop said to stop.
    """
    command = ["git", *(part for setting in SAFE_SETTINGS for part in ("-c", setting)), *arguments]
    try:
        process = subprocess.Popen(
            command,
            cwd=folder,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except FileNotFoundError:
        raise RepositoryError("Git is not installed on this machine, and fetching code takes it") from None
    deadline = time.monotonic() + seconds
    try:
        while True:
            try:
                said, complained = process.communicate(
                    timeout=max(0.0, min(WATCH_SECONDS, deadline - time.monotonic()))
                )
                break
            except subprocess.TimeoutExpired:
                if should_stop is not None and should_stop():
                    stop_git(process)
                    raise StoppedError("Stopped before the code was fetched.") from None
                if time.monotonic() >= deadline:
                    stop_git(process)
                    raise RepositoryError(f"Git did not finish in {seconds:,.0f} seconds") from None
                if watched is not None and limit is not None and (seen := size_of(watched)) > limit:
                    stop_git(process)
                    raise too_big(seen, limit) from None
    except BaseException:
        if process.poll() is None:
            stop_git(process)
        raise
    if process.returncode != 0:
        detail = " ".join((complained or "").split())[-300:] or f"it stopped with status {process.returncode}"
        raise RepositoryError(detail)
    # A step that is quick is over before it is looked at, and is as big as it is
    if watched is not None and limit is not None and (seen := size_of(watched)) > limit:
        raise too_big(seen, limit)

    return said or ""


def clone(
    url: str,
    destination: Path,
    ref: str | None = None,
    max_bytes: int = DEFAULT_BYTES,
    seconds: float = GIT_SECONDS,
    should_stop: Callable[[], bool] | None = None,
    protocols: str = "https",
) -> Cloned:
    """Fetches a project as one commit, and writes its files in a folder, with nothing run.

    :param url: Where the project is, as the server keeps it, which is https at a host that holds code.
    :param destination: A folder that is not there, or is empty, for the files.
    :param ref: A branch, a tag, or a commit, or none for the project's default branch. A commit is only fetched from
        a host that gives out one by its name.
    :param max_bytes: The most bytes to fetch, which the files may not take more than either.
    :param seconds: How long each step may take.
    :param should_stop: Asked while Git works, and stops it, taking the work back, if it says so.
    :param protocols: What Git may fetch by, which is https and is not changed except by a test, to fetch from a folder.
    :raises RepositoryError: If the ref is not one, Git is not there, or it fails, which says what it said.
    :raises RepositoryTooBigError: If it is bigger than max_bytes, which says by how much it got before it was stopped.
    :raises StoppedError: If should_stop said to stop.
    """
    asked = check_ref(ref)
    if shutil.which("git") is None:
        raise RepositoryError("Git is not installed on this machine, and fetching code takes it")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise RepositoryError(f"{destination} has files in it already")
    with tempfile.TemporaryDirectory(prefix="git-home.") as home:
        environment = git_environment(Path(home), protocols)
        try:
            run_git(["init", "--quiet", "--template="], destination, environment, seconds, should_stop=should_stop)
            run_git(
                ["fetch", "--quiet", "--depth=1", "--no-tags", "--no-recurse-submodules", "--", url, asked],
                destination,
                environment,
                seconds,
                destination / ".git",
                max_bytes,
                should_stop,
            )
            commit = run_git(
                ["rev-parse", "--verify", "FETCH_HEAD^{commit}"],
                destination,
                environment,
                seconds,
                should_stop=should_stop,
            ).strip()
            if not COMMIT.fullmatch(commit):
                raise RepositoryError("Git did not say which commit this is")
            run_git(
                ["checkout", "--quiet", "--detach", commit],
                destination,
                environment,
                seconds,
                destination,
                max_bytes + size_of(destination / ".git"),
                should_stop,
            )
        except RepositoryError as error:
            if isinstance(error, RepositoryTooBigError):
                raise
            raise RepositoryError(explain(str(error), url, asked)) from None
        shutil.rmtree(destination / ".git", ignore_errors=True)

    return Cloned(commit=commit, ref=asked)


def explain(said: str, url: str, ref: str) -> str:
    """What Git said when it could not fetch, with what it most likely means said first where Git's own words are not
    clear."""
    lowered = said.lower()
    if "not found" in lowered or "could not read username" in lowered or "authentication failed" in lowered:
        return f"{url} was not found. It may be private, or the address may be wrong. Git said: {said}"
    if "couldn't find remote ref" in lowered or "not our ref" in lowered or "unadvertised object" in lowered:
        return f"{url} has no {ref!r} that can be fetched. Git said: {said}"
    if "not allowed" in lowered and "transport" in lowered:
        return f"{url} is not fetched by a way that is allowed here. Git said: {said}"

    return f"Git could not fetch {url}: {said}"
