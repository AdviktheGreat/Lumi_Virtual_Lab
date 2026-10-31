"""The commands a researcher can give the lead with a message, such as /ask or /code.

A command does not replace the message: it says how the lead is to answer it. The lead is told so beside the
message, and what the command asks for that can be checked is checked when the lead is done, which is when the
lead that answered without it is told once to do it. Whether it did is then told of with the answer, so that
a page can say when a command was not carried out.

/lab is the one that is given more than a name: it says which scientists are to work on the message, and how.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from virtual_lab.mcp_tools import tool_prefix
from virtual_lab.prompts import CHAT_DIRECTIVE_PROMPTS, CHAT_DIRECTIVE_REMINDER_PROMPTS, chat_lab_directive_prompt

# The tools that search the literature, which are the library's own, and the prefix of the names of those of Paperclip
LITERATURE_TOOL_NAMES = ("pubmed_search", "europepmc_search", "europepmc_lookup", "europepmc_fulltext", "arxiv_search")
LITERATURE_TOOL_PREFIXES = (f"{tool_prefix('paperclip')}_",)

# What a command asks for that can be checked: that code ran, that a figure was made, that the literature was
# searched, that the Scientific Critic reviewed the last answer, or that the team was brought together
Check = Literal["code", "plot", "literature", "critic", "team"]

# The most scientists, and questions, a /lab may name, and the longest of each, which are far more than are of use
MAX_LAB_MEMBERS = 50
MAX_LAB_QUESTIONS = 10
MAX_LAB_TITLE_CHARS = 200
MAX_LAB_QUESTION_CHARS = 2000


@dataclass(frozen=True)
class LabRequest:
    """Who the researcher has work on a message with /lab, and how.

    :param mode: "team" for several scientists discussing it with the lead leading, or "individual" for one working
        on it with the Scientific Critic reviewing.
    :param members: Their titles, besides the lead. One, for an individual.
    :param rounds: How many rounds of discussion, or of review.
    :param questions: What the researcher wants the work to answer by the end.
    """

    mode: Literal["team", "individual"] = "team"
    members: tuple[str, ...] = ()
    rounds: int = 1
    questions: tuple[str, ...] = ()

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> "LabRequest":
        """A request as a page sends it, and as it is kept with the message.

        :raises ValueError: If it is not one.
        """
        if not isinstance(data, Mapping):
            raise ValueError("Who works on it is given as a mode, members, rounds, and questions")
        mode = data.get("mode", "team")
        if mode not in ("team", "individual"):
            raise ValueError(f'The mode of /lab is "team" or "individual", not {mode!r}')
        rounds = data.get("rounds", 1)
        if isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < 0:
            raise ValueError(f"The rounds of /lab are a whole number, zero or more, not {rounds!r}")

        members = _texts("members", data.get("members", ()), MAX_LAB_MEMBERS, MAX_LAB_TITLE_CHARS)
        # A title named twice is one scientist
        first: dict[str, str] = {}
        for title in members:
            first.setdefault(title.casefold(), title)
        members = tuple(first.values())
        if mode == "individual" and len(members) != 1:
            raise ValueError("/lab with one scientist needs exactly one to be chosen")
        if not members:
            raise ValueError("/lab needs at least one scientist to be chosen")
        questions = _texts("questions", data.get("questions", ()), MAX_LAB_QUESTIONS, MAX_LAB_QUESTION_CHARS)

        return cls(mode=mode, members=members, rounds=rounds, questions=questions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "members": list(self.members),
            "rounds": self.rounds,
            "questions": list(self.questions),
        }


def describe_lab(data: Any) -> str | None:
    """What a /lab asked for, in words, as an event of the conversation holds it, or None if it holds something else."""
    try:
        lab = LabRequest.from_data(data)
    except ValueError:
        return None
    rounds = f"{lab.rounds} round{'s' if lab.rounds != 1 else ''}"
    if lab.mode == "individual":
        return f"{lab.members[0]} working on it, with the Scientific Critic reviewing, for {rounds}"

    return f"a team session with {', '.join(lab.members)}, for {rounds}"


def _texts(name: str, value: Any, most: int, longest: int) -> tuple[str, ...]:
    """A list of lines of text, as /lab is given them, with the empty ones left out."""
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError(f"The {name} of /lab are a list of text")
    kept: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"The {name} of /lab are a list of text, not {item!r}")
        item = " ".join(item.split())
        if len(item) > longest:
            raise ValueError(f"A {name.removesuffix('s')} of /lab is at most {longest} characters")
        if item:
            kept.append(item)
    if len(kept) > most:
        raise ValueError(f"/lab takes at most {most} {name}")

    return tuple(kept)


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

    def prompt_for(self, lab: LabRequest | None) -> str:
        """What the lead is told beside the message, which for /lab says who is to work on it."""
        if self.name == "lab":
            assert lab is not None
            return chat_lab_directive_prompt(lab.mode, lab.members, lab.rounds, lab.questions)

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
        Directive("lab", check="team"),
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
