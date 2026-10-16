"""A conversation with the head of a lab as a Jupyter notebook, to open, run again, or build on.

Biomni's agent works as a notebook does: it writes code, sees what it printed, and writes more. A conversation is
laid out the same way. What the researcher wrote and what the lead said are Markdown cells, each piece of code the
lead ran is a code cell with what it printed, the value it came to, and the figures it drew as its outputs, and the
answer closes the turn. What the lead called other than code, such as a look through the resources or a question
put to the team, is told in Markdown. The team sessions the lead held are not in it, only what the team told the
lead, which is in the call that asked.

Code in R or the shell is a cell that starts with the magic that runs it (%%R, which needs rpy2, and %%bash), since a
notebook has one language. Figures are embedded, so the notebook stands alone, but the files the code made are only
named, since they are in the conversation's directory.

It is made the way the document of a conversation is: from what the conversation saved, at any time, including while
it goes on, and it fetches nothing.
"""

import base64
import json
import re
from pathlib import Path
from typing import Any

from virtual_lab.chat import describe_size
from virtual_lab.events import ChatEvent
from virtual_lab.export import MAX_EXPORTED_OUTPUT_CHARS, figure_file, money, shorten, when
from virtual_lab.export_chat import (
    MAX_NAMED_FILES,
    NAMED_TOOLS,
    TEAM_TOOLS,
    Call,
    Turn,
    describe_call,
    describe_resources,
    language_of,
    load_chat,
    parse_arguments,
    turns_of,
    without_ansi,
)
from virtual_lab.session import CODE_TOOL_NAME

NOTEBOOK_FORMAT = 4
NOTEBOOK_MINOR = 5

# What a cell in a language the notebook's kernel does not speak starts with, to have it run all the same
MAGICS = {"r": "%%R", "bash": "%%bash"}

# How an error's first line begins when it names the exception, as ZeroDivisionError: division by zero does
EXCEPTION_NAME = re.compile(r"[A-Za-z_][\w.]*")


def lines_of(text: str) -> list[str]:
    """A text as the lines a notebook keeps it in, each with its line break but the last."""
    return text.splitlines(keepends=True)


def fenced(text: str, language: str = "") -> str:
    """A text as a block of code in Markdown, with a fence longer than any run of backticks in it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)

    return f"{fence}{language}\n{text}\n{fence}"


def quoted(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


class Notebook:
    """The cells of a notebook, made one after another, and the number the code in them was run as."""

    def __init__(self, directory: Path | None, max_output_chars: int) -> None:
        self.directory = directory
        self.max_output_chars = max_output_chars
        self.cells: list[dict[str, Any]] = []
        self.runs = 0

    def markdown(self, *parts: str) -> None:
        text = "\n\n".join(part for part in parts if part)
        if text:
            self.cells.append(
                {"cell_type": "markdown", "id": f"cell-{len(self.cells) + 1}", "metadata": {}, "source": lines_of(text)}
            )

    def code(self, cell: dict[str, Any]) -> None:
        """Code that ran, with what came of it as the outputs it was run with."""
        self.runs += 1
        language = str(cell.get("language") or "python")
        code = str(cell.get("code") or "")
        source = f"{MAGICS[language.lower()]}\n{code}" if language.lower() in MAGICS else code
        self.cells.append(
            {
                "cell_type": "code",
                "id": f"cell-{len(self.cells) + 1}",
                "metadata": {},
                "execution_count": self.runs,
                "source": lines_of(source),
                "outputs": self.outputs(cell),
            }
        )
        plots = [str(plot) for plot in cell.get("plots") or []]
        made = [str(path) for path in cell.get("produced_files") or [] if str(path) not in plots]
        if made:
            named = ", ".join(f"`{path}`" for path in made[:MAX_NAMED_FILES])
            more = f" and {len(made) - MAX_NAMED_FILES:,} more" if len(made) > MAX_NAMED_FILES else ""
            self.markdown(f"*Files it made: {named}{more}*")

    def outputs(self, cell: dict[str, Any]) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        output = without_ansi(cell.get("output") or "").rstrip()
        dropped = cell.get("output_dropped")
        if output:
            left_out = (
                f"[The middle of the output, {dropped:,} bytes, is left out.]\n"
                if isinstance(dropped, int) and dropped > 0
                else ""
            )
            outputs.append(
                {
                    "output_type": "stream",
                    "name": "stdout",
                    "text": lines_of(left_out + shorten(output, self.max_output_chars) + "\n"),
                }
            )

        # A traceback is already in what the code printed, so the error is only said again where it is not
        error = without_ansi(cell.get("error") or "").strip()
        if error and error not in output:
            name, _, value = error.partition(": ")
            named = bool(value) and EXCEPTION_NAME.fullmatch(name) is not None
            outputs.append(
                {
                    "output_type": "error",
                    "ename": name if named else "Error",
                    "evalue": value if named else error,
                    "traceback": error.splitlines(),
                }
            )

        if cell.get("value") is not None:
            value_text = json.dumps(cell["value"], indent=2, ensure_ascii=False, default=str)
            outputs.append(
                {
                    "output_type": "execute_result",
                    "execution_count": self.runs,
                    "data": {"text/plain": lines_of(shorten(value_text, self.max_output_chars))},
                    "metadata": {},
                }
            )

        for plot in cell.get("plots") or []:
            outputs.append(self.figure(str(plot)))

        return outputs

    def figure(self, plot: str) -> dict[str, Any]:
        found = figure_file(self.directory, plot) if self.directory is not None else None
        if found is None:
            return {"output_type": "stream", "name": "stderr", "text": [f"{plot} could not be found.\n"]}
        kind, path = found
        try:
            data = (
                lines_of(path.read_text(encoding="utf-8"))
                if kind == "image/svg+xml"
                else base64.b64encode(path.read_bytes()).decode("ascii")
            )
        except (OSError, ValueError):
            return {"output_type": "stream", "name": "stderr", "text": [f"{plot} could not be read.\n"]}

        return {
            "output_type": "display_data",
            "data": {kind: data, "text/plain": [f"<Figure: {plot}>"]},
            "metadata": {},
        }

    def call(self, call: Call) -> None:
        """What the lead called: each piece of code as a cell, anything else told in Markdown."""
        if call.cells:
            for cell in call.cells:
                self.code(cell)

            return
        args = parse_arguments(call.arguments)
        title, details = describe_call(call, args or {})
        parts = [f"**{title}**", *details]
        if call.name == CODE_TOOL_NAME and args is not None and isinstance(args.get("code"), str):
            # The code it was given, where it did not run
            parts.append(fenced(args["code"], language_of(args)))
        elif call.name not in NAMED_TOOLS and call.arguments:
            given = json.dumps(args, indent=2, ensure_ascii=False) if args is not None else call.arguments
            if given != "{}":
                parts.append(fenced(shorten(given, self.max_output_chars), "json"))
        if call.output is not None:
            output = shorten(call.output, self.max_output_chars)
            if call.name in TEAM_TOOLS:
                parts.extend(["What the team told the lead:", quoted(output)])
            else:
                parts.extend(["What it returned:", fenced(output)])
        self.markdown(*parts)


def user_text(event: ChatEvent) -> str:
    parts = [quoted(f"**Researcher**\n\n{event.text}") if event.text else quoted("**Researcher**")]
    files = [file for file in event.data.get("attachments") or [] if isinstance(file, dict)]
    if files:
        items = "\n".join(
            f"> - {file.get('name', '')}"
            + (f" ({describe_size(file['size'])})" if isinstance(file.get("size"), int) else "")
            for file in files
        )
        parts.append(f">\n> Attached:\n>\n{items}")

    return "\n".join(parts)


def note_text(event: ChatEvent, lead: str) -> str:
    to = event.data.get("to")
    label = (
        f"A note to {lead}"
        if to == "lead"
        else "A note to the team"
        if to == "lab"
        else "A note that came too late for anyone to read"
    )

    return quoted(f"**{event.speaker or 'Researcher'}** · {label}\n\n{event.text}")


def add_turn(notebook: Notebook, turn: Turn, lead: str) -> None:
    notebook.markdown(f"## Turn {turn.number}", user_text(turn.user) if turn.user is not None else "")
    for kind, step in turn.steps:
        if kind == "say":
            notebook.markdown(step)
        elif kind == "call":
            notebook.call(step)
        elif kind == "resources":
            notebook.markdown(f"*{describe_resources(step)}*")
        else:
            notebook.markdown(note_text(step, lead))
    end = turn.end
    if end is not None and end.kind == "answer":
        notebook.markdown(end.text)
    elif end is None:
        notebook.markdown("*This turn had not ended when the conversation was saved.*")
    elif end.kind == "stopped":
        notebook.markdown(f"*{end.text or 'The researcher stopped this turn.'}*")
    elif end.kind == "failed":
        notebook.markdown(f"*{end.text or 'This turn ended with an error.'}*")


def chat_notebook(
    chat_dir: Path,
    files_dir: Path | None = None,
    max_output_chars: int = MAX_EXPORTED_OUTPUT_CHARS,
) -> dict[str, Any]:
    """A conversation as a Jupyter notebook: a heading, then each turn as it went.

    :param chat_dir: The conversation's directory.
    :param files_dir: Where the figures its code drew are, which is the session's directory. By default, where
        the conversation says its session was, which is not where it is if the directory has been moved.
    :param max_output_chars: The most of what a tool or a piece of code returned to show for one call, half from
        each end.
    :raises FileNotFoundError: If there is no conversation there.
    :raises ValueError: If what is there is not a conversation's.
    :return: The notebook, as what a .ipynb file holds.
    """
    chat = load_chat(Path(chat_dir))
    info = chat.info
    if files_dir is None and (info.get("session") or {}).get("directory"):
        files_dir = Path(info["session"]["directory"])
    turns = turns_of(chat.events)
    lead = info.get("lead") or {}
    lead_name = str(lead.get("title") or "Lead")
    title = str(info.get("title") or "Conversation")

    notebook = Notebook(files_dir, max_output_chars)
    facts = " · ".join(
        fact
        for fact in (
            when(info.get("created_at")),
            f"{len(turns)} {'turn' if len(turns) == 1 else 'turns'}",
            f"cost {money(info.get('spent'))}",
        )
        if fact
    )
    team = [str(member.get("title")) for member in info.get("team") or [] if isinstance(member, dict)]
    who = f"Led by **{lead_name}**" + (f", who can call on {', '.join(team)}" if team else "") if lead else ""
    uses_magic = any(
        str(cell.get("language") or "python").lower() in MAGICS
        for turn in turns
        for kind, step in turn.steps
        if kind == "call"
        for cell in step.cells
    )
    magic_note = (
        "Cells that start with `%%R` need rpy2 (`%load_ext rpy2.ipython`); "
        "the ones that start with `%%bash` run in the shell."
        if uses_magic
        else ""
    )
    notebook.markdown(f"# {title}", f"*Virtual Lab conversation · {facts}*", who, magic_note)
    if not turns:
        notebook.markdown("Nothing has been said in this conversation yet.")
    for turn in turns:
        add_turn(notebook, turn, lead_name)

    return {
        "nbformat": NOTEBOOK_FORMAT,
        "nbformat_minor": NOTEBOOK_MINOR,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
            "title": title,
        },
        "cells": notebook.cells,
    }


def notebook_text(notebook: dict[str, Any]) -> str:
    """A notebook as the text of a .ipynb file."""
    return json.dumps(notebook, indent=1, ensure_ascii=False) + "\n"


def save_chat_notebook(chat_dir: Path, notebook_path: Path | None = None, **options: Any) -> Path:
    """Saves a conversation as a notebook, as conversation.ipynb in its directory unless told where.

    :param chat_dir: The conversation's directory.
    :param notebook_path: Where to save it, or None for conversation.ipynb in the conversation's directory.
    :param options: What chat_notebook takes.
    :return: Where it was saved.
    """
    chat_dir = Path(chat_dir)
    path = Path(notebook_path) if notebook_path is not None else chat_dir / "conversation.ipynb"
    text = notebook_text(chat_notebook(chat_dir, **options))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

    return path
