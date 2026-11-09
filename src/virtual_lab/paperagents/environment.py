"""Building what a paper's code needs to run, from the code's own files, as an image that is the same later.

The recipe is read from the project: an environment file for conda, or a file of requirements and the project's own
metadata for pip. Nothing is guessed from the README, and a project with no file that says what to install is refused,
with that said, rather than built from what a model thought it needed. A project in R, in Julia, or with only a
Dockerfile is refused too, and says so, since this builds Python environments.

The build runs a stranger's install steps (a `setup.py` runs code), so it is done in a container that has none of this
machine in it: nothing is mounted (the project is copied in), none of this process's environment is passed on, it has
the capabilities that installing packages takes and no others, and it has ceilings on memory, processes, time, and the
disk it may write. The network is on while it builds, since that is how packages are fetched, and a project that asks
for more than it is allowed is stopped and refused. What it builds is committed as an image, whose id is the pin,
with the exact versions that were installed kept beside it. Everything run in the image afterwards has no network.
"""

import json
import os
import queue
import re
import shlex
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerExecutor, DockerUnavailableError

SCHEMA = 1

# Where the project is copied to in the container, and in the image that is made from it
REPO_PATH = "/opt/paper/repo"
CONDA_ENV = "paper"
CONDA_PREFIX = f"/opt/conda/envs/{CONDA_ENV}"

# The images builds start from: one Python each, for a pip environment, and conda's own for a conda environment. They
# are named by tag, and the id of what was pulled is kept with what was built, since that is what makes it the same
# later
PYTHON_VERSIONS = ("3.13", "3.12", "3.11", "3.10", "3.9", "3.8", "3.7")
DEFAULT_PYTHON = "3.11"
CONDA_IMAGE = "condaforge/miniforge3:25.3.1-0"

IMAGE_REPOSITORY = "virtual-lab-paperagent"
# What the containers that builds are run in are called, so that one left by a server that was stopped can be found
BUILD_PREFIX = "virtual-lab-build-"
BUILD_LABEL = re.compile(r"[a-z0-9-]*")

# What a build is allowed, by default and at most
DEFAULT_MINUTES = 30
MAX_MINUTES = 180
DEFAULT_GIGABYTES = 6
MAX_GIGABYTES = 40
MEMORY = "8g"
CPUS = "4"
PIDS = 1024
BUILD_TMPFS = "1g"

# What the container is given of what root can do, which is what apt and pip take and no more
CAPABILITIES = ("CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID")

# How often the disk a build writes is looked at, how long docker's own commands may take, and how much of a build's
# output is kept
SIZE_SECONDS = 10.0
DOCKER_SECONDS = 600
KEPT_LOG_LINES = 4000
TAIL_LINES = 40

# How many system packages may be asked for, and what a Debian package is called
MAX_SYSTEM_PACKAGES = 20
SYSTEM_PACKAGE = re.compile(r"[a-z0-9][a-z0-9+.-]{1,60}")

# What the people who wrote a project say of the Python it needs, in the order they are looked at
PYTHON_PIN = re.compile(r"(?:python-)?(3)\.(\d{1,2})(?:\.\d+)?", re.IGNORECASE)
SPECIFIER = re.compile(r"\s*(~=|===|==|!=|<=|>=|<|>)\s*(\d+(?:\.\d+)*)(\.\*)?\s*")

FAILURE_KINDS = (
    "missing_system_library",
    "version_conflict",
    "python_mismatch",
    "not_found",
    "network",
    "private_dependency",
    "build_failed",
    "out_of_memory",
    "too_big",
    "timeout",
    "does_not_run",
    "failed",
)


class EnvironmentUnsupportedError(Exception):
    """A project whose environment is not one that is built here, with why, in words for the person who asked.

    :param kind: What it is: no_environment, r, julia, docker, pipfile, or python_mismatch.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Failure:
    """Why a build did not come to an environment that runs, as far as its output can say.

    :param kind: One of FAILURE_KINDS.
    :param title: What kind of failure it is, in a few words.
    :param detail: What happened, in a sentence or two.
    :param step: The step it was at, by its id.
    :param package: The package it was at, if the output says.
    :param system_packages: Debian packages that would most likely mend it, which a person may ask for.
    :param python: A version of Python to try in its place, if the output points to one.
    :param tail: The last lines of the step's output.
    """

    kind: str
    title: str
    detail: str
    step: str | None = None
    package: str | None = None
    system_packages: tuple[str, ...] = ()
    python: str | None = None
    tail: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "step": self.step,
            "package": self.package,
            "system_packages": list(self.system_packages),
            "python": self.python,
            "tail": list(self.tail),
        }


class EnvironmentBuildError(Exception):
    """A build that did not come to an environment, with why.

    :param failure: What the output says of it.
    """

    def __init__(self, failure: Failure) -> None:
        super().__init__(f"{failure.title}. {failure.detail}")
        self.failure = failure


@dataclass(frozen=True)
class Step:
    """One thing run in the container, as a list of arguments and never a line for a shell to read, so that nothing in
    the project's file names can be taken for a command, except in the one step that installs system packages, whose
    names are checked.

    :param id: What the step is, for the record: system, create, requirements, project, clean.
    :param title: What it is for, in words.
    :param command: The arguments to run.
    """

    id: str
    title: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class Recipe:
    """What is built, and from what. Everything in it is from the project's own files, or from what a person asked for.

    :param kind: pip or conda.
    :param python: The version of Python, as 3.11, or None for a conda file that says its own.
    :param python_from: Where the version came from, in words.
    :param base_image: What the build starts from.
    :param files: The project's files that it is made from, as their paths.
    :param system_packages: What is installed with apt first, which a person asked for.
    :param steps: What is run, in order.
    :param notes: What a person should know of how far it follows the authors'.
    """

    kind: str
    python: str | None
    python_from: str
    base_image: str
    files: tuple[str, ...]
    system_packages: tuple[str, ...]
    steps: tuple[Step, ...]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "python": self.python,
            "python_from": self.python_from,
            "base_image": self.base_image,
            "files": list(self.files),
            "system_packages": list(self.system_packages),
            "steps": [{"id": step.id, "title": step.title, "command": list(step.command)} for step in self.steps],
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class Limits:
    """What a build is allowed.

    :param minutes: How long it may take.
    :param gigabytes: How much it may write to its disk, counting what it installs.
    """

    minutes: int = DEFAULT_MINUTES
    gigabytes: int = DEFAULT_GIGABYTES

    def to_dict(self) -> dict[str, Any]:
        return {"minutes": self.minutes, "gigabytes": self.gigabytes, "memory": MEMORY, "cpus": CPUS, "pids": PIDS}


@dataclass(frozen=True)
class Built:
    """An environment that was built and runs.

    :param tag: What the image is called.
    :param image_id: What it is, as Docker says it: the hash of its contents.
    :param base_id: What it was built on, in the same way, with base_digests as the registry names it.
    :param architecture: The processor it is for.
    :param size_bytes: How big the image is, and added_bytes how much of that the build added to what it began with.
    :param python: The version of Python in it, as it said.
    :param lock: The exact versions that were installed, as text, kept in a file called lock_name.
    :param packages: How many there are in it.
    :param pip_check: What `pip check` said of the packages: whether they are all met, and what was not.
    :param steps: Each step that was run, with how long it took.
    :param duration: How long the build took, in seconds.
    :param log: What the build printed, the end of it if it was long.
    """

    tag: str
    image_id: str
    base_id: str
    base_digests: tuple[str, ...]
    architecture: str
    size_bytes: int
    added_bytes: int
    python: str
    lock: str
    lock_name: str
    packages: int
    pip_check: dict[str, Any]
    steps: tuple[dict[str, Any], ...]
    duration: float
    log: str = field(default="", repr=False)


def specifier_allows(specifier: str, minor: int) -> bool:
    """Whether a Python 3.minor is one that a requires-python clause allows, for some patch of it. A clause that is
    not understood allows everything, so that a version is not refused for a form that this does not read.

    :param specifier: A clause such as >=3.8,<3.11 or ~=3.9.
    :param minor: The minor version, as 11 for Python 3.11.
    """
    low, high = (3, minor, 0), (3, minor, 99)
    for clause in specifier.split(","):
        if not clause.strip():
            continue
        found = SPECIFIER.fullmatch(clause)
        if found is None:
            continue
        operator, text, star = found.group(1), found.group(2), found.group(3)
        wanted = tuple(int(part) for part in text.split("."))
        padded = (wanted + (0, 0, 0))[:3]
        if operator in ("==", "===") and star:
            keep = high[: len(wanted)] == wanted[: len(wanted)]
        elif operator == "!=" and star:
            keep = not (high[: len(wanted)] == wanted[: len(wanted)] and len(wanted) <= 2)
        elif operator in ("==", "==="):
            keep = low <= padded <= high
        elif operator == "!=":
            keep = not (low == high == padded)
        elif operator == "~=":
            keep = high >= padded and (wanted[0] == 3 and (len(wanted) < 3 or (3, minor) == wanted[:2]))
        elif operator == ">=":
            keep = high >= padded
        elif operator == ">":
            keep = high > padded
        elif operator == "<=":
            keep = low <= padded
        else:
            keep = low < padded
        if not keep:
            return False

    return True


def read_text(path: Path, limit: int = 200_000) -> str | None:
    """What a file of the project says, or None if it is not a plain file, is not there, or cannot be read."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        with path.open("rb") as handle:
            return handle.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return None


def python_wanted(repo: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """What the project says of the Python it needs: the exact minor versions it names, and the clauses that say a
    range, each with where it was said. They are in the order the authors are most likely to mean them in.

    :return: The exact versions as (version, where), and the ranges as (clause, where).
    """
    exact: list[tuple[str, str]] = []
    ranges: list[tuple[str, str]] = []
    if (text := read_text(repo / ".python-version")) is not None:
        for line in text.splitlines():
            if (found := PYTHON_PIN.fullmatch(line.strip())) is not None:
                exact.append((f"{found.group(1)}.{found.group(2)}", ".python-version"))
                break
    if (text := read_text(repo / "runtime.txt")) is not None and (found := PYTHON_PIN.fullmatch(text.strip())):
        exact.append((f"{found.group(1)}.{found.group(2)}", "runtime.txt"))
    if (text := read_text(repo / "pyproject.toml")) is not None:
        found = re.search(r"^\s*requires-python\s*=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
        if found is None:
            found = re.search(r"^\s*python\s*=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
            if found is not None:
                ranges.append((poetry_range(found.group(1)), "pyproject.toml"))
        else:
            ranges.append((found.group(1), "requires-python in pyproject.toml"))
    for name in ("setup.py", "setup.cfg"):
        if (text := read_text(repo / name)) is not None:
            found = re.search(r"python_requires\s*[=:]\s*[\"']?([<>=!~][^\"'\n,)]*(?:,\s*[<>=!~][^\"'\n,)]*)*)", text)
            if found is not None:
                ranges.append((found.group(1).strip(), f"python_requires in {name}"))

    return exact, ranges


def poetry_range(text: str) -> str:
    """A Poetry version constraint, as a requires-python clause: ^3.8 is >=3.8,<4, and ~3.8 is ~=3.8."""
    text = text.strip()
    if text.startswith("^"):
        return f">={text[1:]},<4"
    if text.startswith("~") and not text.startswith("~="):
        return f"~={text[1:]}"

    return text


def fitting_python(specifier: str) -> str | None:
    """The version of Python, of those offered, that a requires-python clause allows and that is nearest the default,
    the older if two are as near, or None if the clause allows none. The default is not always one that the authors
    can have tested, and the nearest to it is the likeliest that they did."""
    allowed = [version for version in PYTHON_VERSIONS if specifier_allows(specifier, int(version.split(".")[1]))]
    default = int(DEFAULT_PYTHON.split(".")[1])

    return min(
        allowed,
        key=lambda version: (abs(int(version.split(".")[1]) - default), int(version.split(".")[1])),
        default=None,
    )


def choose_python(repo: Path, asked: str | None) -> tuple[str, str]:
    """Which Python to build for, and where that came from. A person's choice is first, then the exact version the
    authors name, then a range they give, and then the default.

    :raises EnvironmentUnsupportedError: If no version that is offered is in the range the authors give.
    """
    if asked is not None:
        return asked, "chosen by you"
    exact, ranges = python_wanted(repo)
    for version, where in exact:
        if version in PYTHON_VERSIONS:
            return version, f"{where} says {version}"
    for clause, where in ranges:
        if (version := fitting_python(clause)) is None:
            raise EnvironmentUnsupportedError(
                "python_mismatch",
                f"The code needs Python {clause} ({where}), and none of the versions this builds with ("
                f"{', '.join(PYTHON_VERSIONS)}) is in that range.",
            )
        return version, f"{where} allows {clause}, and {version} is the nearest to {DEFAULT_PYTHON} that does"

    return DEFAULT_PYTHON, "the project does not say, so the default"


def check_python(version: Any) -> str | None:
    """A version of Python that a person asked for, if it is one that is offered.

    :raises ValueError: If it is not.
    """
    if version is None:
        return None
    if not isinstance(version, str) or version not in PYTHON_VERSIONS:
        raise ValueError(f"Python is one of {', '.join(PYTHON_VERSIONS)}")

    return version


def check_system_packages(names: Any) -> tuple[str, ...]:
    """The Debian packages that a person asked to be installed first, each once.

    :raises ValueError: If it is not a short list of names of packages.
    """
    if names is None:
        return ()
    if not isinstance(names, (list, tuple)) or len(names) > MAX_SYSTEM_PACKAGES:
        raise ValueError(f"System packages are given as a list of at most {MAX_SYSTEM_PACKAGES} names")
    kept: list[str] = []
    for name in names:
        if not isinstance(name, str) or SYSTEM_PACKAGE.fullmatch(name) is None:
            raise ValueError(f"{str(name)[:60]!r} is not the name of a Debian package, such as libhdf5-dev")
        if name not in kept:
            kept.append(name)

    return tuple(kept)


def check_limits(minutes: Any, gigabytes: Any) -> Limits:
    """What a person allowed a build, with the defaults for what was left out.

    :raises ValueError: If it is not whole numbers within what is allowed.
    """
    values = []
    for name, value, default, most in (
        ("minutes", minutes, DEFAULT_MINUTES, MAX_MINUTES),
        ("gigabytes", gigabytes, DEFAULT_GIGABYTES, MAX_GIGABYTES),
    ):
        if value is None:
            values.append(default)
        elif isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= most:
            raise ValueError(f"The most {name} a build may take is a whole number from 1 to {most}")
        else:
            values.append(value)

    return Limits(values[0], values[1])


def conda_file_of(repo: Path) -> str | None:
    """The environment file of a conda project, which is at the top of the project: environment.yml first."""
    names = sorted(
        item.name
        for item in repo.iterdir()
        if re.fullmatch(r"(?:environment|conda)[\w.-]*\.ya?ml", item.name, re.IGNORECASE) and item.is_file()
    )
    for first in ("environment.yml", "environment.yaml"):
        if first in names:
            return first

    return names[0] if names else None


def project_install(repo: Path) -> bool:
    """Whether the project is itself something to install: it has a setup script, or metadata that says it is one."""
    if (repo / "setup.py").is_file() or (repo / "setup.cfg").is_file():
        return True
    text = read_text(repo / "pyproject.toml")

    return text is not None and re.search(r"^\[(?:project|tool\.poetry)\]", text, re.MULTILINE) is not None


def requirements_file_of(repo: Path) -> str | None:
    for name in ("requirements.txt", "requirements/requirements.txt", "requirements/base.txt", "requirements/main.txt"):
        if (repo / name).is_file() and not (repo / name).is_symlink():
            return name

    return None


def conda_pins_python(text: str) -> bool:
    """Whether an environment file says which Python."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    dependencies = data.get("dependencies") if isinstance(data, dict) else None

    return isinstance(dependencies, list) and any(
        isinstance(item, str) and re.match(r"python\s*([=<>!~ ]|$)", item.strip()) for item in dependencies
    )


def conda_installs_project(text: str) -> bool:
    """Whether an environment file installs the project itself, with pip, as an `-e .` or a `.` does."""
    return re.search(r"^\s*-\s+(?:-e\s+)?\.\S*\s*$|^\s*-\s+(?:-e|--editable)\s+\.", text, re.MULTILINE) is not None


def system_step(packages: Sequence[str]) -> Step:
    """The step that installs system packages, as one line for a shell, of names that were checked."""
    names = " ".join(shlex.quote(name) for name in packages)
    script = (
        "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends -qq "
        f"{names} && rm -rf /var/lib/apt/lists/*"
    )

    return Step("system", f"Install system packages: {', '.join(packages)}", ("sh", "-c", script))


def plan(
    repo: Path, stock: dict[str, Any] | None = None, python: str | None = None, system_packages: Sequence[str] = ()
) -> Recipe:
    """What would be built from a project, and how, from its files alone.

    :param repo: The project's folder.
    :param stock: What was found in its files, which is used to say what a project with no Python environment is.
    :param python: A version of Python the person asked for, which is used in place of what the project says.
    :param system_packages: Debian packages the person asked to have installed first.
    :raises EnvironmentUnsupportedError: If the project is not one that is built here, with why.
    """
    conda_file = conda_file_of(repo)
    requirements = requirements_file_of(repo)
    installs = project_install(repo)
    notes: list[str] = []
    for lock in ("poetry.lock", "uv.lock", "pdm.lock", "Pipfile.lock"):
        if (repo / lock).is_file():
            notes.append(f"{lock} is not used, so versions may differ from the ones the authors locked.")
    if conda_file is None and requirements is None and not installs:
        found = {item.get("kind") for item in (stock or {}).get("environment", []) if isinstance(item, dict)}
        if "renv" in found or "r-package" in found:
            raise EnvironmentUnsupportedError(
                "r", "The code is in R, and what it needs is set up with renv or as an R package. Only Python is built."
            )
        if "julia" in found:
            raise EnvironmentUnsupportedError("julia", "The code is in Julia. Only Python is built.")
        if "docker" in found:
            raise EnvironmentUnsupportedError(
                "docker", "The authors give a Dockerfile, and building from a Dockerfile is not done here."
            )
        if (repo / "Pipfile").is_file():
            raise EnvironmentUnsupportedError("pipfile", "The code is set up with a Pipfile, which is not read here.")
        raise EnvironmentUnsupportedError(
            "no_environment",
            "No file in the code says what to install: there is no environment file, no requirements.txt, and no "
            "setup script or package metadata. Nothing is guessed from the README.",
        )
    if "docker" in {item.get("kind") for item in (stock or {}).get("environment", []) if isinstance(item, dict)}:
        notes.append("A Dockerfile is there too, and is not used.")

    packages = tuple(system_packages)
    steps: list[Step] = [system_step(packages)] if packages else []
    files: list[str] = []
    if conda_file is not None:
        text = read_text(repo / conda_file)
        if text is None:
            raise EnvironmentUnsupportedError("no_environment", f"{conda_file} cannot be read.")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise EnvironmentUnsupportedError("no_environment", f"{conda_file} is not valid YAML: {error}") from None
        if not isinstance(data, dict) or not isinstance(data.get("dependencies"), list):
            raise EnvironmentUnsupportedError("no_environment", f"{conda_file} has no list of dependencies.")
        files.append(conda_file)
        pinned = conda_pins_python(text)
        if pinned and python is not None:
            raise ValueError(f"{conda_file} says which Python it needs, so a version cannot be chosen in its place")
        if pinned:
            version, where = None, f"{conda_file} says"
            steps.append(
                Step(
                    "requirements",
                    f"Create the environment {conda_file} asks for",
                    ("conda", "env", "create", "--quiet", "-n", CONDA_ENV, "-f", f"./{conda_file}"),
                )
            )
        else:
            version, where = choose_python(repo, python)
            steps.append(
                Step(
                    "create",
                    f"Create a conda environment with Python {version}",
                    ("conda", "create", "--yes", "--quiet", "-n", CONDA_ENV, f"python={version}"),
                )
            )
            steps.append(
                Step(
                    "requirements",
                    f"Add what {conda_file} asks for",
                    ("conda", "env", "update", "--quiet", "-n", CONDA_ENV, "-f", f"./{conda_file}"),
                )
            )
        if installs and not conda_installs_project(text):
            steps.append(
                Step(
                    "project",
                    "Install the project itself, without its dependencies, which the environment file gave",
                    (f"{CONDA_PREFIX}/bin/python", "-m", "pip", "install", "--no-input", "--no-deps", "./"),
                )
            )
            notes.append("The environment file does not install the project itself, so it was installed after it.")
        steps.append(Step("clean", "Clear conda's downloads", ("conda", "clean", "--all", "--yes", "--quiet")))

        return Recipe("conda", version, where, CONDA_IMAGE, tuple(files), packages, tuple(steps), tuple(notes))

    version, where = choose_python(repo, python)
    pip = ("python", "-m", "pip", "install", "--no-input", "--progress-bar", "off")
    if requirements is not None:
        files.append(requirements)
        steps.append(Step("requirements", f"Install what {requirements} asks for", (*pip, "-r", f"./{requirements}")))
    if installs:
        files += [name for name in ("setup.py", "setup.cfg", "pyproject.toml") if (repo / name).is_file()]
        steps.append(Step("project", "Install the project itself", (*pip, "./")))

    return Recipe("pip", version, where, f"python:{version}-slim", tuple(files), packages, tuple(steps), tuple(notes))


HEADER_PACKAGES = {
    "zlib.h": "zlib1g-dev",
    "openssl/ssl.h": "libssl-dev",
    "openssl/opensslv.h": "libssl-dev",
    "ffi.h": "libffi-dev",
    "ffitarget.h": "libffi-dev",
    "hdf5.h": "libhdf5-dev",
    "png.h": "libpng-dev",
    "jpeglib.h": "libjpeg-dev",
    "ft2build.h": "libfreetype-dev",
    "libxml/parser.h": "libxml2-dev",
    "libxslt/xslt.h": "libxslt1-dev",
    "curl/curl.h": "libcurl4-openssl-dev",
    "cairo.h": "libcairo2-dev",
    "gmp.h": "libgmp-dev",
    "bz2.h": "libbz2-dev",
    "lzma.h": "liblzma-dev",
    "sqlite3.h": "libsqlite3-dev",
    "glib.h": "libglib2.0-dev",
    "gsl/gsl_version.h": "libgsl-dev",
    "igraph/igraph.h": "libigraph-dev",
    "yaml.h": "libyaml-dev",
    "readline/readline.h": "libreadline-dev",
    "ncurses.h": "libncurses-dev",
    "tiffio.h": "libtiff-dev",
    "pcre2.h": "libpcre2-dev",
    "mpi.h": "libopenmpi-dev",
    "fftw3.h": "libfftw3-dev",
    "gdal.h": "libgdal-dev",
    "geos_c.h": "libgeos-dev",
    "proj.h": "libproj-dev",
    "htslib/hts.h": "libhts-dev",
}
TOOL_PACKAGES = {
    "gcc": "build-essential",
    "g++": "build-essential",
    "cc": "build-essential",
    "c++": "build-essential",
    "make": "build-essential",
    "cmake": "cmake",
    "gfortran": "gfortran",
    "pkg-config": "pkg-config",
    "cargo": "cargo",
    "rustc": "rustc",
    "git": "git",
    "swig": "swig",
    "patch": "patch",
    "curl": "curl",
    "wget": "wget",
    "unzip": "unzip",
}
# What a library is called to the linker or to pkg-config, and the Debian package that has it for building against
LIBRARY_PACKAGES = {
    "z": "zlib1g-dev",
    "ssl": "libssl-dev",
    "crypto": "libssl-dev",
    "ffi": "libffi-dev",
    "hdf5": "libhdf5-dev",
    "png": "libpng-dev",
    "png16": "libpng-dev",
    "jpeg": "libjpeg-dev",
    "tiff": "libtiff-dev",
    "freetype2": "libfreetype-dev",
    "xml2": "libxml2-dev",
    "libxml-2.0": "libxml2-dev",
    "xslt": "libxslt1-dev",
    "curl": "libcurl4-openssl-dev",
    "libcurl": "libcurl4-openssl-dev",
    "cairo": "libcairo2-dev",
    "glib-2.0": "libglib2.0-dev",
    "gobject-2.0": "libglib2.0-dev",
    "gmp": "libgmp-dev",
    "bz2": "libbz2-dev",
    "lzma": "liblzma-dev",
    "sqlite3": "libsqlite3-dev",
    "gsl": "libgsl-dev",
    "igraph": "libigraph-dev",
    "yaml": "libyaml-dev",
    "readline": "libreadline-dev",
    "ncurses": "libncurses-dev",
    "fftw3": "libfftw3-dev",
    "gdal": "libgdal-dev",
    "geos": "libgeos-dev",
    "proj": "libproj-dev",
    "hts": "libhts-dev",
    "openblas": "libopenblas-dev",
    "blas": "libblas-dev",
    "lapack": "liblapack-dev",
    "mpi": "libopenmpi-dev",
}
NETWORK_WORDS = re.compile(
    r"Temporary failure in name resolution|Name or service not known|Could not resolve host|"
    r"Connection (?:timed out|refused|reset)|Max retries exceeded|Read timed out|"
    r"Network is unreachable|CondaHTTPError|ConnectTimeoutError|ReadTimeoutError",
    re.IGNORECASE,
)
PRIVATE_WORDS = re.compile(
    r"Permission denied \(publickey\)|could not read Username|terminal prompts disabled|"
    r"Repository not found|(?:401|403) Client Error|Authentication failed|Host key verification failed",
    re.IGNORECASE,
)
CONFLICT_WORDS = re.compile(
    r"ResolutionImpossible|conflicting dependencies|UnsatisfiableError|specifications were found to be incompatible|"
    r"Encountered problems while solving|incompatible with",
    re.IGNORECASE,
)
OLD_PYTHON_WORDS = re.compile(
    r"No module named '(?:distutils|imp|pkg_resources|asyncore|smtpd)'|ImpImporter|"
    r"cannot import name '(?:Mapping|MutableMapping|Iterable|Callable|Sequence)' from 'collections'|"
    r"module 'inspect' has no attribute 'getargspec'|module 'numpy' has no attribute '(?:int|float|bool|object)'",
)


def older_python(version: str | None) -> str | None:
    """The next older version of Python that is offered, or None if there is none."""
    if version not in PYTHON_VERSIONS:
        return None
    position = PYTHON_VERSIONS.index(version)

    return PYTHON_VERSIONS[position + 1] if position + 1 < len(PYTHON_VERSIONS) else None


def classify(
    output: str,
    step: str | None = None,
    exit_code: int | None = None,
    python: str | None = None,
    timed_out: bool = False,
    too_big: bool = False,
) -> Failure:
    """What a step's output says of why it failed. This reads words, which a package manager does not keep the same, so
    what it says is the likeliest reason and not a certainty: the output is always kept beside it.

    :param output: What the step printed.
    :param step: The step's id.
    :param exit_code: What the step ended with.
    :param python: The version of Python the build was for.
    :param timed_out: Whether the build was stopped for taking too long.
    :param too_big: Whether it was stopped for writing more than it was allowed.
    """
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    tail = tuple(lines[-TAIL_LINES:])

    def failure(kind: str, title: str, detail: str, **more: Any) -> Failure:
        return Failure(kind, title, detail, step=step, tail=tail, **more)

    if timed_out:
        return failure(
            "timeout", "It took too long", "The build did not finish in the time it was given, and was stopped."
        )
    if too_big:
        return failure(
            "too_big", "It wrote too much", "The build wrote more to its disk than it was allowed, and was stopped."
        )

    if (header := re.search(r"fatal error: ([\w./+-]+\.h): No such file or directory", output)) is not None:
        name = header.group(1)
        suggestion = HEADER_PACKAGES.get(name)
        return failure(
            "missing_system_library",
            "A system library is missing",
            f"Something was built that needs the header {name}, which this image does not have."
            + (f" The Debian package {suggestion} has it." if suggestion else ""),
            system_packages=(suggestion,) if suggestion else (),
        )
    tool = re.search(
        r"(?:unable to execute '?(\S+?)'?: No such file|(?<![\w-])([\w+.-]+): (?:command )?not found|"
        r"error: command '([\w+.-]+)' failed: No such file|Cannot find command '([\w+.-]+)'|"
        r"No such file or directory: '([\w+.-]+)'|'([\w+.-]+)' not found\.|CMake must be installed|"
        r"Could not find a (cargo|rustc|cmake))",
        output,
    )
    if tool is not None:
        name = next((group for group in tool.groups() if group), "cmake")
        name = "cmake" if name.startswith("CMake") else name
        if name in TOOL_PACKAGES:
            suggestion = TOOL_PACKAGES[name]
            return failure(
                "missing_system_library",
                "A tool is missing",
                f"The build needs {name}, which this image does not have. The Debian package {suggestion} has it.",
                system_packages=(suggestion,),
            )
    library = re.search(
        r"cannot find -l([\w+.-]+)|Package '?([\w+.-]+)'? was not found in the pkg-config|"
        r"Dependency \"([\w+.-]+)\" not found",
        output,
    )
    if library is not None:
        name = next(group for group in library.groups() if group)
        suggestion = LIBRARY_PACKAGES.get(name)
        return failure(
            "missing_system_library",
            "A system library is missing",
            f"Something was built against {name}, which this image does not have."
            + (f" The Debian package {suggestion} has it." if suggestion else " Its Debian package is not known here."),
            system_packages=(suggestion,) if suggestion else (),
        )
    if exit_code == 137 or re.search(r"MemoryError|^Killed$|Out of memory", output, re.MULTILINE):
        return failure(
            "out_of_memory",
            "It ran out of memory",
            f"The build was stopped for using more than the {MEMORY} of memory it was given.",
        )
    if CONFLICT_WORDS.search(output):
        return failure(
            "version_conflict",
            "Versions that cannot be used together",
            "The packages the code asks for need versions of each other that cannot all be had. The authors' own "
            "pins may be for a Python that is not this one, or may have been right only when they were written.",
        )
    mismatch = re.search(r"requires a different Python: ([\d.]+) not in '([^']+)'", output)
    if mismatch is not None:
        return failure(
            "python_mismatch",
            "A package needs another Python",
            f"A package needs Python {mismatch.group(2)}, and the build is for Python {mismatch.group(1)}.",
            python=fitting_python(mismatch.group(2)),
        )
    wanted = re.search(r"No matching distribution found for ([\w.\[\],<>=!~-]+)", output)
    if wanted is not None and "require a different python version" in output:
        return failure(
            "python_mismatch",
            "A package needs another Python",
            f"No version of {wanted.group(1)} is for Python {python or 'this one'}: the ones that exist need another.",
            package=wanted.group(1),
        )
    if OLD_PYTHON_WORDS.search(output):
        older = older_python(python)
        return failure(
            "python_mismatch",
            "The code is too old for this Python",
            f"Something that was built uses what Python {python or 'this version'} has taken away."
            + (f" Python {older} may do." if older else ""),
            python=older,
        )
    if PRIVATE_WORDS.search(output):
        return failure(
            "private_dependency",
            "It needs something that is private",
            "A package or a repository that it asks for needs a sign-in, or is not public. Nothing is signed in to "
            "in a build.",
        )
    if NETWORK_WORDS.search(output):
        return failure(
            "network",
            "The network did not answer",
            "A package could not be fetched because the network did not answer. This may pass if it is tried again.",
        )
    missing = re.search(
        r"(?:Could not find a version that satisfies the requirement|No matching distribution found for) "
        r"([\w.\[\],<>=!~-]+)|"
        r"PackagesNotFoundError: The following packages are not available from current channels:\s*\n?\s*"
        r"- ([\w.=<>-]+)",
        output,
    )
    if missing is not None:
        name = next(group for group in missing.groups() if group)
        return failure(
            "not_found",
            "A package was not found",
            f"{name} could not be found for this Python and machine. It may have been taken down, or may not be "
            "built for this machine's processor.",
            package=name,
        )
    built = re.search(
        r"Failed building wheel for ([\w.-]+)|Failed to build ([\w.-]+)|Building wheel for ([\w.-]+).*error", output
    )
    if built is not None or "subprocess-exited-with-error" in output:
        name = next((group for group in built.groups() if group), None) if built else None
        return failure(
            "build_failed",
            "A package would not build",
            f"{name or 'A package'} has no ready-made version for this machine and Python, and building it failed. The "
            "output says why.",
            package=name,
        )

    return failure(
        "failed",
        "The step failed",
        f"The step ended with exit code {exit_code}. Its output is kept, and says more."
        if exit_code
        else "The step failed.",
    )


def docker_run(
    docker_command: Sequence[str], *arguments: str, timeout: float = DOCKER_SECONDS
) -> subprocess.CompletedProcess:
    """Runs one of docker's own commands to the end, with its output.

    :raises DockerUnavailableError: If Docker is not there or does not answer.
    """
    try:
        return subprocess.run(
            [*docker_command, *arguments],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise DockerUnavailableError(f'"{docker_command[0]}" was not found. Install Docker.') from None
    except subprocess.TimeoutExpired:
        raise DockerUnavailableError(f"Docker did not answer {arguments[0]} in {int(timeout)} seconds.") from None


def create_arguments(container: str, image: str) -> tuple[str, ...]:
    """The arguments of the `docker create` that makes the container a build is run in, which is the whole of what it
    is given.

    It is given no mount, and no variable of this process's, since docker passes none that is not named. It has the
    network, since that is how packages are fetched, and has the capabilities that apt and pip need to install. Its
    memory, processes, and scratch space are limited, and what it writes to its disk is watched while it runs.
    """
    capabilities = [argument for name in CAPABILITIES for argument in ("--cap-add", name)]

    return (
        "create",
        "--name",
        container,
        "--init",
        "--network",
        "bridge",
        "--memory",
        MEMORY,
        "--memory-swap",
        MEMORY,
        "--cpus",
        CPUS,
        "--pids-limit",
        str(PIDS),
        "--cap-drop",
        "ALL",
        *capabilities,
        "--security-opt",
        "no-new-privileges",
        "--log-driver",
        "none",
        "--tmpfs",
        f"/tmp:rw,exec,size={BUILD_TMPFS},mode=1777",
        "--env",
        "HOME=/tmp",
        "--env",
        "PIP_NO_CACHE_DIR=1",
        "--env",
        "PIP_DISABLE_PIP_VERSION_CHECK=1",
        "--env",
        "PIP_ROOT_USER_ACTION=ignore",
        "--env",
        "GIT_TERMINAL_PROMPT=0",
        "--workdir",
        REPO_PATH,
        image,
        "sleep",
        "infinity",
    )


class Builder:
    """One build, in one container, which is removed when it is over however it ended."""

    def __init__(
        self,
        repo: Path,
        recipe: Recipe,
        tag: str,
        limits: Limits,
        docker_command: Sequence[str] = ("docker",),
        on_output: Callable[[str], None] | None = None,
        stop: threading.Event | None = None,
        label: str = "",
    ) -> None:
        if BUILD_LABEL.fullmatch(label) is None:
            raise ValueError("The label of a build is lower case letters, digits, and hyphens")
        self.repo = repo
        self.recipe = recipe
        self.tag = tag
        self.limits = limits
        self.docker = tuple(docker_command)
        self.on_output = on_output
        self.stop = stop if stop is not None else threading.Event()
        self.container = f"{BUILD_PREFIX}{label + '-' if label else ''}{uuid4().hex[:12]}"
        self.started = time.monotonic()
        self.deadline = self.started + limits.minutes * 60
        self.last_size = self.started
        self.log: deque[str] = deque(maxlen=KEPT_LOG_LINES)
        self.committed = False

    def say(self, line: str) -> None:
        self.log.append(line)
        if self.on_output is not None:
            self.on_output(line)

    def need(self, what: str, *arguments: str) -> str:
        """Runs one of docker's commands that the build cannot go on without, and gives what it printed.

        :raises DockerUnavailableError: If it did not work, with what Docker said.
        """
        result = docker_run(self.docker, *arguments)
        if result.returncode != 0:
            raise DockerUnavailableError(f"Docker could not {what}: {result.stderr.strip()[:300]}")

        return result.stdout

    def kill(self) -> None:
        try:
            docker_run(self.docker, "kill", self.container, timeout=60)
        except DockerUnavailableError:
            pass

    def remove(self) -> None:
        try:
            docker_run(self.docker, "rm", "--force", "--volumes", self.container, timeout=120)
        except DockerUnavailableError:
            pass

    def size(self) -> int:
        """How much the container has written to its disk, which is nothing before there is a container."""
        result = docker_run(self.docker, "inspect", "--size", "--format", "{{.SizeRw}}", self.container, timeout=120)
        try:
            return int(result.stdout.strip())
        except ValueError:
            return 0

    def watch(self, output: Sequence[str], step: str | None) -> None:
        """Looks at whether the build was told to stop, and whether it has run over what it was allowed.

        :raises StoppedError: If whoever started the build asked to stop it.
        :raises EnvironmentBuildError: If it ran over the time or the disk the build was allowed.
        """
        if self.stop.is_set():
            self.kill()
            raise StoppedError("The build was stopped.")
        now = time.monotonic()
        if now > self.deadline:
            self.kill()
            raise EnvironmentBuildError(classify("\n".join(output), step, python=self.recipe.python, timed_out=True))
        if now - self.last_size > SIZE_SECONDS:
            self.last_size = now
            if self.size() > self.limits.gigabytes * 1024**3:
                self.kill()
                raise EnvironmentBuildError(classify("\n".join(output), step, python=self.recipe.python, too_big=True))

    def stream(self, arguments: Sequence[str], step: str | None = None, quiet: bool = False) -> tuple[int, str]:
        """Runs a docker command, passing its output on as it comes, and keeps to the limits while it runs.

        :param quiet: Whether its output is kept to itself, and not passed on or put in the log.
        :return: What it ended with, and what it printed, the last of it if there was a great deal.
        :raises StoppedError: If whoever started the build asked to stop it.
        :raises EnvironmentBuildError: If it ran over the time or the disk the build was allowed.
        """
        process = subprocess.Popen(
            list(arguments),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            errors="replace",
        )
        lines: queue.Queue[str | None] = queue.Queue()

        def read() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(line.rstrip("\r\n"))
            lines.put(None)

        reader = threading.Thread(target=read, name="virtual-lab-build-output", daemon=True)
        reader.start()
        output: deque[str] = deque(maxlen=KEPT_LOG_LINES)
        try:
            while True:
                try:
                    line = lines.get(timeout=0.5)
                except queue.Empty:
                    line = ""
                else:
                    if line is None:
                        break
                    output.append(line)
                    if not quiet:
                        self.say(line)
                self.watch(output, step)
            return process.wait(), "\n".join(output)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            reader.join(timeout=5)

    def exec(self, command: Sequence[str], step: str | None = None, quiet: bool = False) -> tuple[int, str]:
        """Runs a command in the container, at the project, as root.

        :raises StoppedError: If whoever started the build asked to stop it.
        :raises EnvironmentBuildError: If it ran over the time or the disk the build was allowed.
        """
        return self.stream([*self.docker, "exec", "--workdir", REPO_PATH, self.container, *command], step, quiet)

    def base_image(self) -> dict[str, Any]:
        """What the image that the build starts from is, as Docker says it, once it has been pulled."""
        text = self.need(
            f"say what {self.recipe.base_image} is",
            "image",
            "inspect",
            "--format",
            "{{json .}}",
            self.recipe.base_image,
        )
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {}

        return data if isinstance(data, dict) else {}

    def run(self) -> Built:
        """Builds the environment, and commits it as an image.

        :raises DockerUnavailableError: If Docker is not there, does not answer, or would not do what the build needs.
        :raises EnvironmentBuildError: If a step failed, or the build ran over its time or its disk, or it is not an
            environment that Python runs in.
        :raises StoppedError: If it was stopped. Nothing is kept of it.
        """
        try:
            return self.build()
        except BaseException:
            if self.committed:
                remove_image(self.tag, self.docker)
            raise
        finally:
            self.remove()

    def build(self) -> Built:
        recipe = self.recipe
        self.say(f"Starting from {recipe.base_image}")
        if image_id_of(recipe.base_image, self.docker) is None:
            self.say(f"== Fetch {recipe.base_image}")
            code, output = self.stream([*self.docker, "pull", recipe.base_image], "pull")
            if code != 0:
                raise EnvironmentBuildError(classify(output, "pull", code, recipe.python))
        base = self.base_image()
        self.need("make the container", *create_arguments(self.container, recipe.base_image))
        self.need("start the container", "start", self.container)
        self.need("copy the code in", "cp", f"{self.repo}{os.sep}.", f"{self.container}:{REPO_PATH}")
        done: list[dict[str, Any]] = []
        for step in recipe.steps:
            self.say(f"== {step.title}")
            began = time.monotonic()
            code, output = self.exec(step.command, step.id)
            done.append(
                {"id": step.id, "title": step.title, "seconds": round(time.monotonic() - began, 1), "exit_code": code}
            )
            if code != 0:
                raise EnvironmentBuildError(classify(output, step.id, code, recipe.python))
        conda = recipe.kind == "conda"
        python_bin = f"{CONDA_PREFIX}/bin/python" if conda else "python"
        self.say("== Record what was installed")
        shown = self.exec((python_bin, "-c", "import sys; print(sys.version.split()[0])"), quiet=True)
        python = shown[1].strip().splitlines()[-1] if shown[0] == 0 and shown[1].strip() else "unknown"
        frozen = self.exec((python_bin, "-m", "pip", "freeze", "--all"), quiet=True)
        pip_lines = [line for line in frozen[1].splitlines() if line.strip()] if frozen[0] == 0 else []
        if conda:
            listed = self.exec(("conda", "list", "-n", CONDA_ENV, "--explicit", "--md5"), quiet=True)
            # What conda put in is in its own list, and pip names it with the path it was built at, which says nothing
            by_pip = [line for line in pip_lines if " @ file:///home/conda/" not in line]
            lock = (
                listed[1].strip()
                + "\n\n# Put in with pip, or by the project's own install\n"
                + "\n".join(by_pip)
                + "\n"
            )
            packages = len([line for line in listed[1].splitlines() if line.startswith("http")]) + len(by_pip)
            lock_name = "conda-explicit.txt"
        else:
            lock = "\n".join(pip_lines) + "\n"
            packages = len(pip_lines)
            lock_name = "pip-freeze.txt"
        checked = self.exec((python_bin, "-m", "pip", "check"), quiet=True)
        pip_check = {
            "ok": checked[0] == 0,
            "problems": [] if checked[0] == 0 else [line for line in checked[1].splitlines() if line.strip()][:20],
        }
        if self.size() > self.limits.gigabytes * 1024**3:
            raise EnvironmentBuildError(classify("", "commit", python=recipe.python, too_big=True))
        self.say("== Keep it as an image")
        self.need("stop the container", "stop", "--time", "5", self.container)
        base_path = next(
            (item[5:] for item in base.get("Config", {}).get("Env", []) if item.startswith("PATH=")),
            "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        )
        # The command the container was made with is put back to the image's own, as the entrypoint was never changed
        base_command = base.get("Config", {}).get("Cmd")
        changes = ["--change", f"CMD {json.dumps(base_command)}" if base_command else "CMD []", "--change", "WORKDIR /"]
        if conda:
            changes += ["--change", f"ENV PATH={CONDA_PREFIX}/bin:{base_path}"]
        self.need(
            "keep the image",
            "commit",
            *changes,
            "--message",
            f"Built from {', '.join(recipe.files)}",
            self.container,
            self.tag,
        )
        self.committed = True
        info = self.need(
            "say what the image is", "image", "inspect", "--format", "{{.Id}} {{.Size}} {{.Architecture}}", self.tag
        )
        image_id, image_size, architecture = (info.split() + ["", "0", "unknown"])[:3]
        size = int(image_size) if image_size.isdigit() else 0

        return Built(
            tag=self.tag,
            image_id=image_id,
            base_id=str(base.get("Id", "")),
            base_digests=tuple(str(item) for item in base.get("RepoDigests") or []),
            architecture=architecture,
            size_bytes=size,
            added_bytes=max(0, size - int(base.get("Size") or 0)),
            python=python,
            lock=lock,
            lock_name=lock_name,
            packages=packages,
            pip_check=pip_check,
            steps=tuple(done),
            duration=round(time.monotonic() - self.started, 1),
            log="\n".join(self.log),
        )


def image_id_of(tag: str, docker_command: Sequence[str] = ("docker",)) -> str | None:
    """What an image is, as Docker says it, or None if there is no image with this name, or Docker does not answer."""
    try:
        result = docker_run(docker_command, "image", "inspect", "--format", "{{.Id}}", tag, timeout=60)
    except DockerUnavailableError:
        return None

    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def remove_image(tag: str, docker_command: Sequence[str] = ("docker",)) -> bool:
    """Takes an image away, which is done by its name, so that what the name was moved to is not. Whether it is gone: an
    image that is not there is gone, and one that Docker would not remove, or that it cannot be asked about, is not."""
    try:
        result = docker_run(docker_command, "image", "rm", tag, timeout=300)
    except DockerUnavailableError:
        return False

    return result.returncode == 0 or "No such image" in result.stderr


def smoke(tag: str, scratch: Path, docker_command: Sequence[str] = ("docker",)) -> Failure | None:
    """Runs a few words of Python in the image as it will be run later: with no network, as the person who runs it and
    not as root, and with the root of the image read-only. What is built has to start there, since that is the only way
    it is used.

    :param scratch: An empty folder, which is what the run is given to write in.
    :return: Why it did not, or None.
    """
    executor = DockerExecutor(image=tag, allow_network=False, docker_command=tuple(docker_command), timeout=120)
    result = executor.run(scratch, ["python", "-c", "import sys; print(sys.version.split()[0])"])
    if result.succeeded:
        return None
    lines = (result.stdout + "\n" + result.stderr).strip().splitlines()

    return Failure(
        "does_not_run",
        "It does not run offline",
        "What was built does not start with no network, as it has to be run. "
        + (lines[-1] if lines else "It printed nothing."),
        step="offline run",
        tail=tuple(lines[-TAIL_LINES:]),
    )


def remove_builds(label: str, docker_command: Sequence[str] = ("docker",)) -> int:
    """Removes the containers of builds that were left behind, as a build is not left by anything but a server that was
    stopped hard. Those of one label only, which is of an agent that has no build going.

    :return: How many were removed.
    """
    if not label or BUILD_LABEL.fullmatch(label) is None:
        return 0
    try:
        listed = docker_run(
            docker_command,
            "ps",
            "--all",
            "--filter",
            f"name=^/{BUILD_PREFIX}{label}-",
            "--format",
            "{{.Names}}",
            timeout=60,
        )
        names = [name for name in listed.stdout.split() if name.startswith(f"{BUILD_PREFIX}{label}-")]
        if listed.returncode != 0 or not names:
            return 0
        docker_run(docker_command, "rm", "--force", "--volumes", *names, timeout=300)
    except DockerUnavailableError:
        return 0

    return len(names)


def ready(docker_command: Sequence[str] = ("docker",)) -> tuple[bool, str | None]:
    """Whether builds can be made now: whether Docker is installed and running, and if not, what to do."""
    try:
        DockerExecutor(docker_command=tuple(docker_command)).check_available()
    except DockerUnavailableError as error:
        return False, str(error)

    return True, None


def build_environment(
    repo: Path,
    recipe: Recipe,
    tag: str,
    limits: Limits,
    scratch: Path,
    docker_command: Sequence[str] = ("docker",),
    on_output: Callable[[str], None] | None = None,
    stop: threading.Event | None = None,
    label: str = "",
) -> Built:
    """Builds an environment from a recipe, and checks that it runs as it will be run: with no network.

    On any failure the image is not kept, and nothing of the build is left in Docker. The name the image is to have
    must not be in use.

    :param scratch: An empty folder for the check that the image runs.
    :param label: Put in the name of the container, to say whose it is.
    :raises DockerUnavailableError: If Docker is not there.
    :raises EnvironmentBuildError: If it did not come to an environment that runs, with why.
    :raises StoppedError: If it was stopped.
    """
    built = Builder(repo, recipe, tag, limits, docker_command, on_output, stop, label).run()
    try:
        problem = smoke(built.tag, scratch, docker_command)
        if problem is None and stop is not None and stop.is_set():
            raise StoppedError("The build was stopped.")
    except BaseException:
        remove_image(built.tag, docker_command)
        raise
    if problem is not None:
        remove_image(built.tag, docker_command)
        raise EnvironmentBuildError(problem)

    return built


def tag_of(agent_id: str, commit: str) -> str:
    """What an agent's image is called, which depends on the code it was built from."""
    return f"{IMAGE_REPOSITORY}:{agent_id}-{commit[:12]}".lower()
