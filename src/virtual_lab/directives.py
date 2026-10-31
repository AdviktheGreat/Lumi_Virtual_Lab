"""The commands a researcher can give the lead with a message, such as /ask or /code.

A command does not replace the message: it says how the lead is to answer it. The lead is told so beside the
message, and what the command asks for that can be checked is checked when the lead is done, which is when the
lead that answered without it is told once to do it. Whether it did is then told of with the answer, so that
a page can say when a command was not carried out.
"""

from dataclasses import dataclass
from typing import Literal

from virtual_lab.mcp_tools import tool_prefix
from virtual_lab.prompts import CHAT_DIRECTIVE_PROMPTS, CHAT_DIRECTIVE_REMINDER_PROMPTS

# The tools that search the literature, which are the library's own, and the prefix of the names of those of Paperclip
LITERATURE_TOOL_NAMES = ("pubmed_search", "europepmc_search", "europepmc_lookup", "europepmc_fulltext", "arxiv_search")
LITERATURE_TOOL_PREFIXES = (f"{tool_prefix('paperclip')}_",)

# What a command asks for that can be checked: that code ran, that a figure was made, that the literature was
# searched, or that the Scientific Critic reviewed the last answer
Check = Literal["code", "plot", "literature", "critic"]


@dataclass(frozen=True)
class Directive:
    """One command.

    :param name: What it is called, without the slash.
    :param no_tools: Whether the lead has no tools for the message.
    :param needs_text: Whether the message must have something written in it.
    :param check: What is checked when the lead is done, if anything is.
    """

    name: str
    no_tools: bool = False
    needs_text: bool = True
    check: Check | None = None

    @property
    def prompt(self) -> str:
        """What the lead is told beside the message."""
        return CHAT_DIRECTIVE_PROMPTS[self.name]

    @property
    def reminder(self) -> str | None:
        """What the lead is told when the check fails."""
        return CHAT_DIRECTIVE_REMINDER_PROMPTS.get(self.name)


DIRECTIVES: dict[str, Directive] = {
    directive.name: directive
    for directive in (
        Directive("ask", no_tools=True),
        Directive("plan", no_tools=True),
        Directive("code", check="code"),
        Directive("plot", check="plot"),
        Directive("search", check="literature"),
        Directive("review", needs_text=False, check="critic"),
    )
}


def directive_named(name: str) -> Directive:
    """The command with this name.

    :raises ValueError: If there is no such command.
    """
    found = DIRECTIVES.get(name)
    if found is None:
        names = ", ".join(f"/{each}" for each in DIRECTIVES)
        raise ValueError(f"/{name} is not a command the lead is given. They are {names}")

    return found


def is_literature_tool(name: str) -> bool:
    """Whether a tool of this name searches the literature."""
    return name in LITERATURE_TOOL_NAMES or name.startswith(LITERATURE_TOOL_PREFIXES)
