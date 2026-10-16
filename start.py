#!/usr/bin/env python3
"""Starts the Virtual Lab from a clone of this repository, doing first whatever is not yet done.

It makes a Python environment in .venv (or uses the one you are in), installs the lab in it, and builds the pages of
the interface, which needs Node 22 or later. Each is looked at before it is done and left alone if it is there, so the
first start takes a few minutes and the ones after it a moment. What this does not recognise is given to
virtual-lab-server:

    python3 start.py
    python3 start.py --workspace ~/lab --port 9000 --no-browser
    python3 start.py --plan         # what it would do, without doing it
    python3 start.py --rebuild      # build the pages again

It is started from this directory, so a .env file here, with the keys you use, is read as the lab starts.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent

MINIMUM_PYTHON = (3, 12)
MINIMUM_NODE = 22

# What the interface needs beyond the lab itself: the server, MCP servers, reading papers, and Biomni's benchmarks
EXTRAS = "server,mcp,papers,eval"

# The modules an environment needs for the interface, which are looked for and not imported, since importing the lab
# takes seconds
NEEDED_MODULES = ("virtual_lab", "fastapi", "uvicorn", "keyring", "mcp", "pypdf", "yaml", "numpy", "pandas", "pyarrow")

# Run by an environment's own Python: its version, where it finds the lab (empty if it does not), and what of the
# needed modules it cannot find
PROBE = f"""\
import importlib.util as found, sys
print(sys.version_info[0], sys.version_info[1])
lab = found.find_spec("virtual_lab")
print(lab.origin if lab and lab.origin else "")
print(" ".join(name for name in {NEEDED_MODULES!r} if found.find_spec(name) is None))
"""

# Where the pages are put, for the server to find
PAGES = Path("src") / "virtual_lab" / "server" / "static"

# What the pages are built from, apart from everything under web/src
PAGE_INPUTS = ("package.json", "package-lock.json", "next.config.ts", "tsconfig.json", "components.json")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class StartError(Exception):
    """Raised when the lab cannot be started, with what is wrong and what to do about it."""


@dataclass(frozen=True)
class Step:
    """Something to do before the lab is started, or starting it.

    :param title: What it does, for the person.
    :param command: The program and its arguments.
    :param cwd: Where it is run.
    """

    title: str
    command: tuple[str, ...]
    cwd: Path


@dataclass(frozen=True)
class Plan:
    """What to do, in order, ending with starting the lab, and what is worth saying first."""

    steps: list[Step]
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Facts:
    """What is there on this machine, which decides what is left to do.

    :param python: The interpreter the lab will run with, which may not be made yet.
    :param own: Whether it is the environment the person is in, rather than .venv.
    :param made: Whether it exists.
    :param version: Its Python's major and minor version, if it could be told.
    :param installed: Whether it has the lab, from this clone, and everything the interface needs.
    :param pip: Whether it has pip.
    :param uv: Where uv is, if it is installed.
    :param node: Node's version, if it is installed.
    :param npm: Where npm is, if it is installed.
    :param modules_current: Whether what npm installed is what package-lock.json asks for.
    :param pages_exist: Whether pages are built.
    :param pages_current: Whether they are newer than everything they are built from.
    """

    python: Path
    own: bool
    made: bool
    version: tuple[int, int] | None
    installed: bool
    pip: bool
    uv: str | None
    node: tuple[int, ...] | None
    npm: str | None
    modules_current: bool
    pages_exist: bool
    pages_current: bool


def interpreter(environment: Path) -> Path:
    """The Python in an environment, where this system keeps it."""
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def own_environment(env: Mapping[str, str]) -> bool:
    """Whether this Python is running in an environment the person is in: a virtual environment, or a conda one."""
    return sys.prefix != sys.base_prefix or (
        bool(env.get("CONDA_PREFIX")) and Path(env["CONDA_PREFIX"]) == Path(sys.prefix)
    )


def newest(paths: Sequence[Path]) -> float:
    """The latest time any of these files, or of the files under any of these directories, was changed."""
    latest = 0.0
    for path in paths:
        if path.is_dir():
            latest = max(latest, newest([found for found in path.rglob("*") if found.is_file()]))
        elif path.is_file():
            latest = max(latest, path.stat().st_mtime)

    return latest


def pages_current(root: Path) -> bool:
    """Whether the pages are built, and after the last change to what they are built from."""
    index = root / PAGES / "index.html"
    if not index.is_file():
        return False
    web = root / "web"
    inputs = [web / "src", *(web / name for name in PAGE_INPUTS)]

    return index.stat().st_mtime >= newest(inputs)


def modules_current(root: Path) -> bool:
    """Whether npm has installed what package-lock.json asks for, by the file it leaves of that."""
    marker = root / "web" / "node_modules" / ".package-lock.json"
    lock = root / "web" / "package-lock.json"

    return marker.is_file() and (not lock.is_file() or marker.stat().st_mtime >= lock.stat().st_mtime)


def node_version(node: str | None, run: Runner) -> tuple[int, ...] | None:
    """Node's version as numbers, or None if it is not installed or does not say."""
    if node is None:
        return None
    try:
        said = run([node, "--version"], capture_output=True, text=True, check=False, timeout=30).stdout.strip()
        return tuple(int(part) for part in said.lstrip("v").split("."))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def probe(python: Path, root: Path, run: Runner) -> tuple[tuple[int, int] | None, bool]:
    """What an environment's Python is, and whether it has the lab from this clone and what the interface needs."""
    try:
        done = run([str(python), "-c", PROBE], capture_output=True, text=True, check=False, cwd=root, timeout=120)
        version, origin, missing = (done.stdout.splitlines() + ["", "", ""])[:3]
        major, minor = (int(part) for part in version.split())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, False
    # A copy of the lab installed from somewhere else would be the one that ran, in place of this clone's
    here = bool(origin) and Path(origin).resolve().is_relative_to((root / "src").resolve())

    return (major, minor), done.returncode == 0 and here and not missing.strip()


def gather(
    root: Path = ROOT,
    env: Mapping[str, str] | None = None,
    run: Runner = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> Facts:
    """Looks at what is there."""
    env = os.environ if env is None else env
    own = own_environment(env)
    python = Path(sys.executable) if own else interpreter(root / ".venv")
    made = python.exists()
    version, installed = probe(python, root, run) if made else (None, False)
    pip = False
    if made:
        try:
            pip = (
                run([str(python), "-m", "pip", "--version"], capture_output=True, check=False, timeout=60).returncode
                == 0
            )
        except (OSError, subprocess.SubprocessError):
            pip = False
    node = which("node")
    npm = which("npm")

    return Facts(
        python=python,
        own=own,
        made=made,
        version=version,
        installed=installed,
        pip=pip,
        uv=which("uv"),
        node=node_version(node, run),
        npm=npm,
        modules_current=modules_current(root),
        pages_exist=(root / PAGES / "index.html").is_file(),
        pages_current=pages_current(root),
    )


def plan(root: Path, facts: Facts, forwarded: Sequence[str] = (), rebuild: bool = False) -> Plan:
    """What to do before the lab is started, and then starting it.

    :param root: This clone.
    :param facts: What is there.
    :param forwarded: What is given to virtual-lab-server.
    :param rebuild: Whether to build the pages again whether or not they are current.
    :raises StartError: If the lab cannot be started as things are, saying what to do.
    """
    python = str(facts.python)
    steps: list[Step] = []
    notes: list[str] = []
    environment = root / ".venv"

    if facts.own:
        notes.append(f"Using the environment you are in, {Path(sys.prefix)}.")
    if not facts.made:
        steps.append(Step("Make a Python environment in .venv", (sys.executable, "-m", "venv", str(environment)), root))
    elif facts.version is not None and facts.version < MINIMUM_PYTHON:
        found = ".".join(str(part) for part in facts.version)
        needed = ".".join(str(part) for part in MINIMUM_PYTHON)
        remedy = "Activate one that is" if facts.own else f"Delete {environment} to have one made"
        raise StartError(f"{python} is Python {found}, and the Virtual Lab needs {needed} or later. {remedy}.")

    if not facts.made or not facts.installed:
        target = f".[{EXTRAS}]"
        # An environment that is just made has pip, and one that is not has what the person made it with
        if facts.made and not facts.pip:
            if facts.uv:
                install = (facts.uv, "pip", "install", "--python", python, "-e", target)
            else:
                steps.append(Step("Give the environment pip", (python, "-m", "ensurepip", "--upgrade"), root))
                install = (python, "-m", "pip", "install", "-e", target)
        else:
            install = (python, "-m", "pip", "install", "-e", target)
        steps.append(Step("Install the Virtual Lab from this clone, and what its interface needs", install, root))

    if rebuild or not facts.pages_current:
        enough = facts.node is not None and facts.node[0] >= MINIMUM_NODE and facts.npm is not None
        if enough:
            assert facts.npm is not None
            web = root / "web"
            if not facts.modules_current:
                steps.append(Step("Install what the pages are built from", (facts.npm, "ci"), web))
            steps.append(Step("Build the pages of the interface", (facts.npm, "run", "package"), web))
        elif facts.pages_exist and not rebuild:
            notes.append("Node 22 or later is needed to build the pages again, so the ones already built are used.")
        else:
            found = "is not installed" if facts.node is None else f"is {'.'.join(map(str, facts.node))}"
            if facts.node is not None and facts.npm is None:
                found = "is installed without npm"
            raise StartError(
                f"Building the interface needs Node {MINIMUM_NODE} or later, and Node {found}. Install it from "
                "https://nodejs.org (or with a package manager, such as brew install node) and run this again."
            )

    steps.append(Step("Start the Virtual Lab", (python, "-m", "virtual_lab.server", *forwarded), root))

    return Plan(steps, notes)


def describe(chosen: Plan, root: Path = ROOT) -> str:
    """What a plan would do, as lines to print."""
    lines = list(chosen.notes)
    preparing = chosen.steps[:-1]
    if not preparing:
        lines.append("Nothing needs doing first.")
    else:
        lines.append("First:")
    for number, step in enumerate(preparing, 1):
        where = "" if step.cwd == root else f" (in {step.cwd.relative_to(root)})"
        lines.append(f"  {number}. {step.title}{where}")
        lines.append(f"       {shlex.join(step.command)}")
    last = chosen.steps[-1]
    lines.append("Then it starts the Virtual Lab:")
    lines.append(f"       {shlex.join(last.command)}")

    return "\n".join(lines)


def execute(chosen: Plan) -> int:
    """Does what a plan says, and returns the exit code to end with: that of a step that fails, or of the lab."""
    for note in chosen.notes:
        print(note, flush=True)
    *preparing, serving = chosen.steps
    for number, step in enumerate(preparing, 1):
        print(f"[{number}/{len(preparing)}] {step.title}", flush=True)
        try:
            code = subprocess.run(step.command, cwd=step.cwd, check=False).returncode
        except OSError as error:
            print(f"start.py: {step.title} could not be run: {error}", file=sys.stderr)
            return 1
        if code != 0:
            print(
                f"start.py: {step.title} failed, with exit code {code}. Put that right and run this again: "
                "what is already done is not done twice.",
                file=sys.stderr,
            )
            return code
    try:
        return subprocess.call(serving.command, cwd=serving.cwd)
    except KeyboardInterrupt:
        return 130


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """Starts the lab, after doing what is not done."""
    if sys.version_info < MINIMUM_PYTHON:
        needed = ".".join(str(part) for part in MINIMUM_PYTHON)
        print(
            f"start.py: the Virtual Lab needs Python {needed} or later, and this is Python "
            f"{sys.version_info[0]}.{sys.version_info[1]}. Run this with a newer one, such as python{needed} start.py.",
            file=sys.stderr,
        )
        return 1
    parser = argparse.ArgumentParser(
        prog="start.py",
        description="Starts the Virtual Lab, after doing what is not yet done: making an environment, installing the "
        "lab, and building the pages of the interface.",
        epilog="Anything else is given to virtual-lab-server: --workspace, --port, --no-browser, and the rest.",
        # An option of the server that begins as one of these do must reach the server, not be taken for one of these
        allow_abbrev=False,
    )
    parser.add_argument("--plan", action="store_true", help="say what would be done, and do nothing")
    parser.add_argument("--rebuild", action="store_true", help="build the pages again, even if they are up to date")
    options, forwarded = parser.parse_known_args(argv)

    try:
        chosen = plan(root, gather(root), forwarded, options.rebuild)
    except StartError as error:
        print(f"start.py: {error}", file=sys.stderr)
        return 1
    if options.plan:
        print(describe(chosen, root))
        return 0

    return execute(chosen)


if __name__ == "__main__":
    sys.exit(main())
