"""The tools the lead of a conversation may be given, which the person chooses among in the settings.

These are the library's own: the literature and database lookups that need nothing set up, and the tools that
read the files in a conversation. Each is a function of the library that the lead calls by name, and what it
asks and is told is shown in the conversation like any other call.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

from virtual_lab.constants import CHAT_UPLOADS_DIR_NAME
from virtual_lab.directives import LITERATURE_TOOL_NAMES
from virtual_lab.tables import list_data_files
from virtual_lab.tools import (
    DATABASE_TOOLS,
    Tool,
    data_file_tools,
    inspect_data_file,
    structure_file_tool,
)

# The tools by what they are for, which is how the settings list them and the order of each, so that a tool is
# listed beside those it is used with
GROUPS: dict[str, tuple[str, ...]] = {
    "Literature": LITERATURE_TOOL_NAMES,
    "Proteins and structures": (
        "uniprot_search",
        "uniprot_lookup",
        "pdb_lookup",
        "alphafold_lookup",
        "fetch_structure_file",
    ),
    "Chemistry": ("pubchem_lookup", "chembl_search", "chembl_lookup", "chembl_target_search", "chembl_activities"),
    "Your files": ("data_files", "inspect_data_file"),
}

# The tools that only make sense where code can run, since what they write is for code to read
NEEDS_CODE = frozenset({"fetch_structure_file"})

# The most characters of a tool's description that the settings show
MAX_SUMMARY_CHARS = 200

NO_FILES_ATTACHED = "No files have been attached to this conversation yet."


def attached_file_tools(directory: Path) -> tuple[Tool, ...]:
    """The tools that read files, for a conversation with nowhere to run code, which see the files attached to it and
    name them as the lead is told of them, in uploads/.

    :param directory: The conversation's own directory, in which the files attached are in uploads/.
    """
    uploads = directory / CHAT_UPLOADS_DIR_NAME
    prefix = f"{CHAT_UPLOADS_DIR_NAME}/"
    listing, inspection = data_file_tools(uploads)

    def show_attached() -> str:
        found = list_data_files(uploads)
        if not found.files:
            return NO_FILES_ATTACHED

        return replace(found, files=tuple(replace(file, name=prefix + file.name) for file in found.files)).report()

    def inspect_attached(filename: str, sheet: str | None = None) -> str:
        return inspect_data_file(uploads, filename.removeprefix(prefix), sheet)

    return (replace(listing, function=show_attached), replace(inspection, function=inspect_attached))


def conversation_tools(directory: Path, session_directory: Path | None) -> dict[str, Tool]:
    """Every tool a conversation may be given, by name, in the order the settings list them.

    :param directory: The conversation's own directory.
    :param session_directory: Where the conversation's code runs, which the tools that read files see, and the one
        that fetches a structure writes in; or None where none does, when they see the files attached instead, and
        the one that fetches a structure is left out.
    """
    if session_directory is None:
        files = attached_file_tools(directory)
    else:
        files = data_file_tools(session_directory)
    made = {tool.name: tool for tool in (*DATABASE_TOOLS, *files)}
    if session_directory is not None:
        fetching = structure_file_tool(session_directory)
        made[fetching.name] = fetching

    return {name: made[name] for names in GROUPS.values() for name in names if name in made}


def tool_names() -> tuple[str, ...]:
    """The names of every tool that may be given, in the order the settings list them."""
    return tuple(conversation_tools(Path(), Path()))


def summary(description: str) -> str:
    """What a tool does, in a sentence the settings can show beside it."""
    first = " ".join(description.split()).split(". ")[0].rstrip(".")
    if len(first) > MAX_SUMMARY_CHARS:
        first = first[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"

    return first


def describe_tools(disabled: list[str]) -> list[dict[str, Any]]:
    """The tools as the settings show them: each with its name, what it is for, what it does, whether it needs code to
    run, and whether it is given to a new conversation.

    :param disabled: The names of the tools that are not given to a new conversation.
    """
    made = conversation_tools(Path(), Path())

    return [
        {
            "name": name,
            "group": group,
            "summary": summary(made[name].description),
            "needs_code": name in NEEDS_CODE,
            "enabled": name not in disabled,
        }
        for group, names in GROUPS.items()
        for name in names
        if name in made
    ]


def check_tool_names(names: Any) -> list[str]:
    """The names of tools to give, without repeats and in the order the settings list them.

    :raises ValueError: If it is not a list of the names of tools there are.
    """
    if not isinstance(names, (list, tuple)):
        raise ValueError(f"The tools are a list of names, not {names!r}")
    known = tool_names()
    if unknown := [name for name in names if not isinstance(name, str) or name not in known]:
        raise ValueError(f"There is no tool {', '.join(map(str, unknown))}: the tools are {', '.join(known)}")

    return [name for name in known if name in names]
