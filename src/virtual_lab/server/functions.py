"""The functions written from papers that a conversation is given as tools.

A run of papers (see papers.py) can have functions a model wrote for the tasks its papers share. They are code no one
has read, so the person gives a run's functions to conversations by saying so, and a conversation that is given them
runs them where its code runs, in the sandbox if that is Docker, and not at all where code runs nowhere.
"""

from collections.abc import Collection, Iterable
from pathlib import Path

from virtual_lab.chat import RESERVED_TOOL_NAMES
from virtual_lab.function_generator import function_path
from virtual_lab.function_tools import tool_from_source
from virtual_lab.server.papers import FUNCTIONS_DIR, LAB_FILE, RUN_ID, is_lab, usable_functions
from virtual_lab.server.workspace import Workspace, read_json
from virtual_lab.session import Session
from virtual_lab.tools import Tool


def runs_with_functions(workspace: Workspace) -> dict[str, bool]:
    """The runs that have a function that passed, each with whether the person gave its functions to conversations."""
    found: dict[str, bool] = {}
    if not workspace.papers_dir.is_dir():
        return found
    for directory in sorted(workspace.papers_dir.iterdir()):
        lab = read_json(directory / LAB_FILE)
        if RUN_ID.fullmatch(directory.name) and directory.is_dir() and is_lab(lab) and usable_functions(directory):
            found[directory.name] = bool(lab.get("given", False))

    return found


def given_runs(workspace: Workspace) -> list[str]:
    """The runs whose functions are given to the conversations that are made now."""
    return [run for run, given in runs_with_functions(workspace).items() if given]


def check_function_runs(names: object, workspace: Workspace) -> list[str]:
    """The runs to give the functions of, without repeats.

    :raises ValueError: If it is not a list of runs that have functions.
    """
    if not isinstance(names, (list, tuple)):
        raise ValueError(f"The runs to give the functions of are a list of their ids, not {names!r}")
    known = runs_with_functions(workspace)
    if unknown := [name for name in names if not isinstance(name, str) or name not in known]:
        raise ValueError(f"There is no run of papers with functions {', '.join(map(repr, unknown))}")

    return list(dict.fromkeys(names))


def function_tools(
    workspace: Workspace, runs: Iterable[str], session: Session | None, taken: Collection[str] = ()
) -> tuple[Tool, ...]:
    """The functions of these runs, each as a tool that runs in the session.

    A run that is gone is left out, and so is a function that has gone or has been changed into something that
    cannot be a tool, and one whose name a tool already has, since a conversation's tools are named differently:
    of two runs with a function of one name, the first is given.

    :param taken: The names of the tools the conversation has already.
    """
    if session is None:
        return ()
    names = {*taken, *RESERVED_TOOL_NAMES}
    tools: list[Tool] = []
    for run in runs:
        directory = workspace.papers_dir / run
        if not RUN_ID.fullmatch(run) or not is_lab(read_json(directory / LAB_FILE)):
            continue
        for function in usable_functions(directory):
            if function.name in names:
                continue
            path = function_path(Path(directory / FUNCTIONS_DIR), function.name)
            try:
                tool = tool_from_source(path.read_text(encoding="utf-8"), function.name, session, filename=str(path))
            except (OSError, ValueError):
                continue
            names.add(function.name)
            tools.append(tool)

    return tuple(tools)
