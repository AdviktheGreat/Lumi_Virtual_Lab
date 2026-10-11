"""The software and data code from a meeting can run with, matching Biomni's.

Biomni's agent writes code against a large environment: Python and R libraries, command-line
bioinformatics tools, and an 11 GB data lake of curated tables. Code a meeting writes can only
use what the sandbox it runs in has, so this module builds Biomni's environment as a sandbox
image and fetches its data lake, to be mounted into that sandbox read-only.

The image is built from Biomni's own environment files, which ship with this package (see
virtual_lab/sandbox). It is built in stages, "base", "bio", and "full", because the full
environment takes hours to build and tens of gigabytes to hold, and most analyses need far
less of it.
"""

import os
import shutil
import signal
import subprocess
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

import requests

from virtual_lab.__about__ import __version__
from virtual_lab.biomni_env_desc import data_lake_dict, library_content_dict
from virtual_lab.constants import (
    BIOMNI_RELEASE_URL,
    DATA_LAKE_CHUNK_BYTES,
    SANDBOX_IMAGE_NAME,
    SANDBOX_PLATFORM,
    WEB_TIMEOUT_SECONDS,
    WEB_USER_AGENT,
)
from virtual_lab.execution import DockerUnavailableError, ExecutionError

SANDBOX_TARGETS = ("base", "bio", "full")

# Every file in Biomni's data lake, with Biomni's description of it
DATA_LAKE: dict[str, str] = dict(data_lake_dict)

# The software in the full sandbox image, with Biomni's description of each
SANDBOX_LIBRARIES: dict[str, str] = dict(library_content_dict)

# Seconds a build that was asked to stop is given to do so before it is killed
BUILD_STOP_GRACE_SECONDS = 10.0


class StoppedError(Exception):
    """Raised when a build or a download ends early because whoever started it asked it to stop."""


def sandbox_context() -> Path:
    """The directory the sandbox image is built from: its Dockerfile and Biomni's files."""
    return Path(str(files("virtual_lab") / "sandbox"))


def sandbox_image(target: str = "full", platform: str | None = SANDBOX_PLATFORM) -> str:
    """The tag a stage of the sandbox image is built under.

    The package version is part of the tag, so that upgrading to a version whose environment
    differs builds a new image rather than silently running the old one. So is the platform,
    since Docker keeps one image per tag: a native build under the same tag as an x86-64 one
    would replace it, and would then be reused for a run that asks for x86-64 and cannot have it.

    :param target: "base", "bio", or "full".
    :param platform: The platform the image is built for, or None for this machine's own.
    :raises ValueError: If the target is not one of those.
    :return: The image tag.
    """
    check_target(target)
    architecture = "native" if platform is None else platform.replace("/", "-")

    return f"{SANDBOX_IMAGE_NAME}:{target}-{__version__}-{architecture}"


def check_target(target: str) -> None:
    """Refuses a stage the Dockerfile does not have."""
    if target not in SANDBOX_TARGETS:
        raise ValueError(f"target must be one of {', '.join(SANDBOX_TARGETS)}, not {target!r}")


def find_docker(docker_command: tuple[str, ...]) -> None:
    """Refuses to go on without the Docker command line."""
    if shutil.which(docker_command[0]) is None:
        raise DockerUnavailableError(
            f'Cannot build the sandbox image: "{docker_command[0]}" was not found. Install Docker.'
        )


def sandbox_image_exists(tag: str, docker_command: tuple[str, ...] = ("docker",)) -> bool:
    """Whether an image is present locally, without pulling it.

    :param tag: The image tag.
    :param docker_command: How to invoke Docker.
    :return: Whether Docker has the image.
    """
    find_docker(docker_command)
    # Listed rather than inspected: with Docker's containerd image store, inspect looks only for
    # the machine's own platform, so an x86-64 image on an ARM machine would be reported missing
    result = subprocess.run(
        [*docker_command, "image", "ls", "--quiet", tag], capture_output=True, text=True, check=False
    )

    return result.returncode == 0 and bool(result.stdout.strip())


def build_command(
    target: str,
    tag: str,
    platform: str | None = SANDBOX_PLATFORM,
    docker_command: tuple[str, ...] = ("docker",),
    build_args: dict[str, str] | None = None,
) -> tuple[str, ...]:
    """The docker build command for a stage of the sandbox image, to run or to record."""
    check_target(target)
    command = [*docker_command, "build", "--target", target, "--tag", tag]

    if platform is not None:
        command += ["--platform", platform]

    for name, value in (build_args or {}).items():
        command += ["--build-arg", f"{name}={value}"]

    return tuple([*command, str(sandbox_context())])


def build_sandbox_image(
    target: str = "full",
    tag: str | None = None,
    platform: str | None = SANDBOX_PLATFORM,
    docker_command: tuple[str, ...] = ("docker",),
    build_args: dict[str, str] | None = None,
    rebuild: bool = False,
    on_output: Callable[[str], None] | None = None,
    stop: threading.Event | None = None,
) -> str:
    """Builds a stage of the sandbox image, unless it is already built.

    Docker's own output is shown as the build runs, since the full image takes hours, unless
    on_output is given to take it.

    :param target: "base" for Biomni's analysis libraries, "bio" to add its bioinformatics
        tools, or "full" to add R and the command-line tools as well.
    :param tag: The tag to build under, defaulting to sandbox_image(target, platform).
    :param platform: The platform to build for. Biomni's environment is published for x86-64
        Linux only, so the default is "linux/amd64" even on an ARM machine, where Docker
        emulates it; run the image with DockerExecutor(platform=...) set to match. None builds
        for this machine's own architecture, which only the base image is known to support.
    :param docker_command: How to invoke Docker.
    :param build_args: Build arguments, such as MINIFORGE_VERSION.
    :param rebuild: Whether to build even if the tag already exists.
    :param on_output: Called with each line Docker prints, its errors included, in place of showing it.
    :param stop: Set to end the build, which is stopped as Docker's client is told to end and killed
        if it does not. Layers already built are kept, so building again carries on from them.
    :raises ValueError: If the target is not a stage of the image.
    :raises DockerUnavailableError: If Docker is not installed.
    :raises ExecutionError: If the build fails.
    :raises StoppedError: If it was stopped before it finished.
    :return: The tag of the image, to pass to DockerExecutor.
    """
    tag = tag or sandbox_image(target, platform)
    command = build_command(target, tag, platform, docker_command, build_args)
    find_docker(docker_command)

    if not rebuild and sandbox_image_exists(tag, docker_command):
        return tag

    if on_output is None and stop is None:
        returncode = subprocess.run(command, check=False).returncode
    else:
        returncode = run_build(command, on_output, stop)

    if returncode != 0:
        if stop is not None and stop.is_set():
            raise StoppedError(f"Building the {target} sandbox image was stopped")
        raise ExecutionError(
            f"Building the {target} sandbox image failed with exit code {returncode}. "
            f"The command was: {' '.join(command)}"
        )

    return tag


def run_build(command: Sequence[str], on_output: Callable[[str], None] | None, stop: threading.Event | None) -> int:
    """Runs a build, passing on what it prints a line at a time, and ending it when asked to.

    :param command: The docker build command.
    :param on_output: Called with each line of output, errors included, or None to drop them.
    :param stop: Set to end the build.
    :return: The exit code, which is not zero for a build that was stopped.
    """
    # In a group of its own, so that docker's build plugin, which it starts, is ended with it
    process = subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        start_new_session=hasattr(os, "killpg"),
    )
    finished = threading.Event()

    def watch() -> None:
        assert stop is not None
        while not finished.is_set():
            if not stop.wait(0.1):
                continue
            if process.poll() is None:
                end_build(process, force=False)
                try:
                    process.wait(BUILD_STOP_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    end_build(process, force=True)
            return

    watcher = threading.Thread(target=watch, name="virtual-lab-build-stop", daemon=True) if stop is not None else None
    if watcher is not None:
        watcher.start()

    try:
        assert process.stdout is not None
        for line in process.stdout:
            if on_output is not None:
                on_output(line.rstrip("\r\n"))
        return process.wait()
    finally:
        # A callback that raised leaves a build that nothing is reading
        if process.poll() is None:
            end_build(process, force=True)
            process.wait()
        finished.set()
        if watcher is not None:
            watcher.join()


def end_build(process: subprocess.Popen, force: bool) -> None:
    """Asks a build and what it started to end, or makes them."""
    if not hasattr(os, "killpg"):
        if force:
            process.kill()
        else:
            process.terminate()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


@dataclass
class DataLakeDownload:
    """What happened when the data lake was fetched.

    :param directory: Where the files are.
    :param downloaded: The files fetched this time.
    :param present: The files that were already there and were left alone.
    :param failed: The files that could not be fetched, with the reason for each.
    """

    directory: Path
    downloaded: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """Whether every file asked for is now on disk."""
        return not self.failed


def check_filename(name: str) -> None:
    """Refuses a name that would be written anywhere but directly inside the data lake."""
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        raise ValueError(f"Not a data lake file name: {name!r}")


def download_data_lake(
    directory: Path,
    names: Iterable[str] | None = None,
    base_url: str = BIOMNI_RELEASE_URL,
    on_file: Callable[[str, int, int | None], None] | None = None,
    on_progress: Callable[[str, int, int | None], None] | None = None,
    stop: threading.Event | None = None,
) -> DataLakeDownload:
    """Fetches Biomni's data lake, or part of it, into a directory.

    A file already in the directory is left alone, so an interrupted download can be resumed by
    calling this again. Each file is written under a temporary name and renamed once complete,
    so a file that is present is never a partial one.

    :param directory: Where to put the files. Mount it into the sandbox with
        DockerExecutor(data_lake=directory).
    :param names: The files to fetch, defaulting to all of DATA_LAKE, which is about 11 GB.
    :param base_url: Where Biomni publishes its release files.
    :param on_file: Called as each file finishes, with its name, its size in bytes, and the
        size the server announced, or None if it announced none.
    :param on_progress: Called as a file is fetched, with its name, the bytes written so far,
        and the size the server announced, or None if it announced none: once with none written
        when the server has answered, then as each part is written.
    :param stop: Set to end the download, which stops within a part of a file, keeping what
        was fetched before.
    :raises ValueError: If a name is not a plain file name.
    :raises StoppedError: If it was stopped before it finished.
    :return: What was fetched, what was already there, and what failed.
    """
    wanted = list(DATA_LAKE if names is None else names)
    for name in wanted:
        check_filename(name)

    directory.mkdir(parents=True, exist_ok=True)
    outcome = DataLakeDownload(directory=directory)

    for name in wanted:
        path = directory / name

        if stop is not None and stop.is_set():
            raise StoppedError("Fetching the data lake was stopped")

        if path.is_file():
            outcome.present.append(name)
            continue

        def report(written: int, announced: int | None, name: str = name) -> None:
            if on_progress is not None:
                on_progress(name, written, announced)

        try:
            size, announced = fetch_file(f"{base_url.rstrip('/')}/data_lake/{name}", path, report, stop)
        except (requests.RequestException, OSError, ValueError) as error:
            outcome.failed[name] = str(error) or type(error).__name__
            continue

        outcome.downloaded.append(name)
        if on_file is not None:
            on_file(name, size, announced)

    return outcome


def fetch_file(
    url: str,
    path: Path,
    on_progress: Callable[[int, int | None], None] | None = None,
    stop: threading.Event | None = None,
) -> tuple[int, int | None]:
    """Streams a URL to a file, renaming it into place only once it is complete.

    :param url: What to fetch.
    :param path: Where to write it.
    :param on_progress: Called with the bytes written and the length the server announced, or None,
        once the server has answered and after each part is written.
    :param stop: Set to end the fetch, which leaves no file behind.
    :raises requests.RequestException: If the request fails.
    :raises ValueError: If the body is shorter or longer than the server announced.
    :raises StoppedError: If it was stopped before it finished.
    :return: The bytes written, and the length the server announced.
    """
    partial = path.with_name(f".{path.name}.part")

    try:
        with requests.get(
            url, stream=True, timeout=WEB_TIMEOUT_SECONDS, headers={"User-Agent": WEB_USER_AGENT}
        ) as response:
            response.raise_for_status()
            header = response.headers.get("Content-Length")
            # The length of a compressed body is not the length of what iter_content yields
            encoded = response.headers.get("Content-Encoding", "identity") != "identity"
            announced = int(header) if header and header.isdigit() and not encoded else None
            written = 0
            if on_progress is not None:
                on_progress(0, announced)

            with open(partial, "wb") as file:
                for chunk in response.iter_content(chunk_size=DATA_LAKE_CHUNK_BYTES):
                    if stop is not None and stop.is_set():
                        raise StoppedError(f"Fetching {path.name} was stopped")
                    file.write(chunk)
                    written += len(chunk)
                    if on_progress is not None:
                        on_progress(written, announced)

        # A connection dropped partway through ends the body early without an error, and the
        # file would otherwise be kept as if it were whole
        if announced is not None and written != announced:
            raise ValueError(f"Received {written:,} of the {announced:,} bytes announced for {url}")

        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)

    return written, announced
