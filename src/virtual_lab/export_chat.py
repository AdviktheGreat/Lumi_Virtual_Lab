"""A conversation with the head of a lab as a document to read, print, or share: HTML, and PDF through WeasyPrint.

A conversation is laid out as it was had, turn by turn: what the researcher wrote and attached, then what the lead
did to answer, which is what it said as it went, the tools it called, the code it ran with what that printed and
the figures it drew, and the notes the researcher added on the way, and then the answer. The team sessions the lead
held are added after the last turn, each laid out as virtual_lab.export lays out a meeting, and what the lead did to
bring the team in links to its session. What the conversation cost is in its heading.

Everything is read from what the conversation saved, so a document can be made of one at any time, including one
that is still going, which is shown as far as it has got, or one that was cut off. It is made the way a meeting's
is: the Markdown the agents wrote is rendered without the HTML it may hold, and neither the HTML nor the PDF
fetches anything, since the figures are embedded in it and an image an agent linked to is shown as a link.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from virtual_lab.chat import (
    CONSULT_TOOL_NAME,
    CONVENE_TOOL_NAME,
    FIND_RESOURCES_TOOL_NAME,
    describe_size,
    read_json_lines,
)
from virtual_lab.constants import (
    CHAT_EVENTS_FILE_NAME,
    CHAT_FILE_NAME,
    CHAT_LAB_DIR_NAME,
    HUMAN_SPEAKER,
    PROJECT_FILE_NAME,
)
from virtual_lab.directives import describe_lab
from virtual_lab.events import ChatEvent
from virtual_lab.export import (
    AGENT_COLOURS,
    MAX_EXPORTED_OUTPUT_CHARS,
    code_block,
    document,
    escape,
    humanize,
    image_uri,
    load_meeting,
    markdown,
    meeting_body,
    meta_line,
    money,
    render_pdf,
    shorten,
    team_cards,
    when,
)
from virtual_lab.session import CODE_TOOL_NAME

# The most files a piece of code made that are named under it, and the most characters of a task or a scientist's name
MAX_NAMED_FILES = 30
MAX_TASK_CHARS = 120
MAX_NAME_CHARS = 60

LANGUAGES = {"python": "Python", "r": "R", "bash": "shell"}

# The kinds of resource a conversation tells of, as the events name them, and what each is called
RESOURCE_KINDS = (
    ("tools", "tool", "tools"),
    ("data_lake", "data file", "data files"),
    ("libraries", "software package", "software packages"),
    ("know_how", "know-how document", "know-how documents"),
)

# The tools whose calls are said in what is told of them, rather than by the arguments they were given
NAMED_TOOLS = (CODE_TOOL_NAME, FIND_RESOURCES_TOOL_NAME, CONVENE_TOOL_NAME, CONSULT_TOOL_NAME)
TEAM_TOOLS = (CONVENE_TOOL_NAME, CONSULT_TOOL_NAME)

# What a terminal does with what a program prints, which a document has no use for
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


@dataclass(frozen=True)
class SavedChat:
    """A conversation as it was saved.

    :param info: What chat.json says it is: its title, when it began, who leads and who is on the team, what it
        has cost, and where its code runs.
    :param events: What happened in it, in the order it happened.
    """

    info: dict[str, Any]
    events: list[ChatEvent]


def load_chat(chat_dir: Path) -> SavedChat:
    """Reads a conversation back from where it was saved, changing nothing there, since it may be going.

    :param chat_dir: The conversation's directory.
    :raises FileNotFoundError: If there is no conversation there.
    :raises ValueError: If what is there is not a conversation's.
    :return: The conversation.
    """
    chat_dir = Path(chat_dir)
    info = json.loads((chat_dir / CHAT_FILE_NAME).read_text(encoding="utf-8"))
    if not isinstance(info, dict) or "id" not in info:
        raise ValueError(f"{chat_dir / CHAT_FILE_NAME} is not a conversation's")
    saved = read_json_lines(chat_dir / CHAT_EVENTS_FILE_NAME, repair=False)
    # Events from different threads can be written out of order, and an event's number is the order it happened in
    events = sorted((ChatEvent.from_dict(event) for event in saved), key=lambda event: event.id)

    return SavedChat(info=info, events=events)


# What the lead did in a turn

@dataclass
class Call:
    """A tool the lead called, with what came of it."""

    id: str
    name: str
    arguments: str
    output: str | None = None
    cells: list[dict[str, Any]] = field(default_factory=list)
    # The team session it started, by the name it was saved under
    meeting: str | None = None


@dataclass
class Turn:
    """A turn: what the researcher said, what the lead did, and how it ended.

    :param steps: What the lead did, in order, each as its kind and what it is of: "say" and a text, "call" and a
        Call, "resources" and the event's data, or "note" and its event.
    """

    number: int
    user: ChatEvent | None = None
    steps: list[tuple[str, Any]] = field(default_factory=list)
    end: ChatEvent | None = None

    def call(self, call_id: str) -> Call | None:
        return next((step for kind, step in self.steps if kind == "call" and step.id == call_id), None)


def turns_of(events: list[ChatEvent]) -> list[Turn]:
    """The turns of a conversation, from its events."""
    turns: dict[int, Turn] = {}
    for event in events:
        # What happens outside a turn, such as the conversation being given a title, is not part of one
        if event.turn < 1:
            continue
        turn = turns.setdefault(event.turn, Turn(event.turn))
        data = event.data

        if event.kind == "user":
            turn.user = event
        elif event.kind == "tool_calls":
            if event.text.strip():
                turn.steps.append(("say", event.text))
            for place, given in enumerate(data.get("calls") or []):
                call_id = str(given.get("id") or f"call-{place}")
                if turn.call(call_id) is None:
                    turn.steps.append(
                        ("call", Call(call_id, str(given.get("name") or ""), str(given.get("arguments") or "")))
                    )
        elif event.kind == "tool_output":
            call_id = str(data.get("call") or "")
            if (call := turn.call(call_id)) is None:
                # What it answers was not told of, so it is shown as the answer alone
                call = Call(call_id, str(data.get("name") or ""), "")
                turn.steps.append(("call", call))
            call.output = event.text
        elif event.kind == "cell":
            if (call := turn.call(str(data.get("call") or ""))) is not None:
                call.cells.append(dict(data))
        elif event.kind == "lab":
            call = turn.call(str(data.get("call") or ""))
            if call is not None and data.get("meeting"):
                call.meeting = str(data["meeting"])
        elif event.kind == "resources":
            turn.steps.append(("resources", dict(data)))
        elif event.kind == "note":
            turn.steps.append(("note", event))
        elif event.kind in ("answer", "stopped", "failed"):
            turn.end = event

    return [turns[number] for number in sorted(turns)]


# Saying what a call was

def one_line(value: Any, max_chars: int) -> str | None:
    """A text on one line, cut to max_chars, or None if it has nothing in it."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None

    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def text_of(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_arguments(arguments: str) -> dict[str, Any] | None:
    """What a call was given, which is JSON where the model wrote it well, and nothing where it did not."""
    try:
        parsed = json.loads(arguments)
    except ValueError:
        return None

    return parsed if isinstance(parsed, dict) else None


def language_name(language: str) -> str:
    return LANGUAGES.get(language.lower(), language)


def language_of(args: dict[str, Any]) -> str:
    return args["language"] if isinstance(args.get("language"), str) and args["language"] else "python"


def describe_call(call: Call, args: dict[str, Any]) -> tuple[str, list[str]]:
    """What a call is said to be: a line saying what was done, and what it was asked, as lines of text."""
    if call.name == CODE_TOOL_NAME:
        return f"Ran {language_name(language_of(args))} code", []
    if call.name == FIND_RESOURCES_TOOL_NAME:
        task = one_line(args.get("task"), MAX_TASK_CHARS)

        return "Looked up resources", [task] if task else []
    if call.name == CONVENE_TOOL_NAME:
        members = args.get("members") if isinstance(args.get("members"), list) else []
        names = ", ".join(member.strip() for member in members if isinstance(member, str) and member.strip())

        return "Convened the team", [line for line in (names, text_of(args.get("agenda"))) if line]
    if call.name == CONSULT_TOOL_NAME:
        member = one_line(args.get("member"), MAX_NAME_CHARS)
        agenda = text_of(args.get("agenda"))

        return f"Consulted {member or 'a scientist'}", [agenda] if agenda else []

    return f"Called {call.name or 'a tool'}", []


def describe_resources(data: dict[str, Any]) -> str:
    """What the lead was told it has to work with, or what it asked for, in a line."""
    selected = data["selected"] if isinstance(data.get("selected"), dict) else {}
    available = data["available"] if isinstance(data.get("available"), dict) else {}
    retrieval = data["retrieval"] if isinstance(data.get("retrieval"), dict) else {}

    def count(of: dict[str, Any], key: str) -> int:
        value = of.get(key)
        if isinstance(value, list):
            return len(value)

        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    def counted(of: dict[str, Any]) -> str | None:
        parts = [
            f"{number} {one if number == 1 else many}"
            for key, one, many in RESOURCE_KINDS
            if (number := count(of, key)) > 0
        ]

        return ", ".join(parts) or None

    chosen = counted(selected)
    task = one_line(retrieval.get("task"), MAX_TASK_CHARS)
    if task:
        return "Chose resources for a task: " + " · ".join(part for part in (task, chosen) if part)
    if data.get("mode") == "none":
        return "No resources"
    if data.get("mode") == "retrieve" and chosen is None:
        found = counted(available)

        return "Resources it can look up" + (f": {found}" if found else "")
    found = chosen or counted(available)

    return "Resources it can use" + (f": {found}" if found else "")


# Laying it out

class Figures:
    """The figures a document has shown, which are numbered through it, and the directory they are drawn in."""

    def __init__(self, directory: Path | None) -> None:
        self.directory = directory
        self.count = 0

    def html(self, plot: str) -> str:
        self.count += 1
        uri = image_uri(self.directory, plot) if self.directory is not None else None
        picture = (
            f'<img src="{uri}" alt="Figure {self.count}">' if uri else f"<em>{escape(plot)} could not be found.</em>"
        )

        return (
            f"<figure>{picture}<figcaption>Figure {self.count}. Drawn by the code above ({escape(plot)}).</figcaption>"
            "</figure>"
        )


def without_ansi(text: Any) -> str:
    return ANSI.sub("", str(text))


def how_it_went(status: str, duration: Any) -> tuple[str, str]:
    """What became of code that ran, in words, and the kind of badge that says it."""
    took = f"{duration:.1f} s" if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None
    if status == "ok":
        return (f"ran in {took}" if took else "ran"), "ok"
    if status == "error":
        return (f"failed after {took}" if took else "failed"), "bad"
    if status == "timeout":
        return (f"stopped at its time limit ({took})" if took else "stopped at its time limit"), "warn"
    if status == "lost":
        return "the session ended while it ran", "warn"

    return status, "neutral"


def cell_html(cell: dict[str, Any], figures: Figures, max_output_chars: int) -> str:
    """Code that ran, with how it went, what it printed, and the figures it drew."""
    language = str(cell.get("language") or "python")
    said, badge = how_it_went(str(cell.get("status") or "ok"), cell.get("duration"))
    parts = [
        (
            f'<div class="label">{escape(language_name(language))} code '
            f'<span class="badge {badge}">{escape(said)}</span></div>'
        ),
        code_block(str(cell.get("code") or ""), language),
    ]

    output = without_ansi(cell.get("output") or "").rstrip()
    if output:
        dropped = cell.get("output_dropped")
        if isinstance(dropped, int) and dropped > 0:
            parts.append(f'<p class="meta">The middle of the output, {dropped:,} bytes, is left out.</p>')
        shown = escape(shorten(output, max_output_chars))
        parts.append(f'<div class="label">Output</div><pre class="output">{shown}</pre>')

    # A traceback is already in what the code printed, so the error is only said again where it is not
    error = without_ansi(cell.get("error") or "").strip()
    if error and error not in output:
        parts.append(f'<div class="callout error">{escape(error)}</div>')

    if cell.get("value") is not None:
        value = shorten(json.dumps(cell["value"], indent=2, ensure_ascii=False, default=str), max_output_chars)
        parts.append(f'<div class="label">Value</div>{code_block(value, "json")}')

    plots = [str(plot) for plot in cell.get("plots") or []]
    parts.extend(figures.html(plot) for plot in plots)

    made = [str(path) for path in cell.get("produced_files") or [] if str(path) not in plots]
    if made:
        named = ", ".join(f"<code>{escape(path)}</code>" for path in made[:MAX_NAMED_FILES])
        more = f" and {len(made) - MAX_NAMED_FILES:,} more" if len(made) > MAX_NAMED_FILES else ""
        parts.append(f'<p class="meta">Files it made: {named}{more}</p>')

    return "\n".join(parts)


def session_anchor(name: str) -> str:
    return f"team-session-{escape(name)}"


def call_html(call: Call, sessions: dict[str, Path], figures: Figures, max_output_chars: int) -> str:
    """What the lead called, what it was asked, and what came of it."""
    args = parse_arguments(call.arguments)
    title, details = describe_call(call, args or {})
    parts = []
    if call.cells:
        # Each says for itself what was run and what came of it, which is what the call's own answer repeats
        parts.extend(cell_html(cell, figures, max_output_chars) for cell in call.cells)
    else:
        parts.append(f'<div class="label">{escape(title)}</div>')
        parts.extend(f'<div class="body plain">{escape(line)}</div>' for line in details)
        if call.name == CODE_TOOL_NAME and args is not None and isinstance(args.get("code"), str):
            # The code it was given, where it did not run
            parts.append(code_block(args["code"], language_of(args)))
        elif call.name not in NAMED_TOOLS and call.arguments:
            given = json.dumps(args, indent=2, ensure_ascii=False) if args is not None else call.arguments
            if given != "{}":
                parts.append(code_block(shorten(given, max_output_chars), "json"))
        if call.output is not None:
            label = "What the team told the lead" if call.name in TEAM_TOOLS else "What it returned"
            answer = markdown(shorten(call.output, max_output_chars))
            parts.append(f'<div class="label">{label}</div><div class="body">{answer}</div>')

    if call.meeting in sessions:
        parts.append(f'<p class="meta"><a href="#{session_anchor(call.meeting)}">Read the discussion</a></p>')

    return f'<div class="call">{"".join(parts)}</div>'


def user_html(event: ChatEvent) -> str:
    body = f'<div class="body plain">{escape(event.text)}</div>' if event.text else ""
    if directive := event.data.get("directive"):
        what = describe_lab(event.data.get("lab")) if directive == "lab" else None
        label = f"Command /{escape(str(directive))}" + (f": {escape(what)}" if what else "")
        body = f'<div class="label">{label}</div>{body}'
    files = [file for file in event.data.get("attachments") or [] if isinstance(file, dict)]
    if files:
        items = "".join(
            f"<li>{escape(file.get('name', ''))}"
            + (f" ({describe_size(file['size'])})" if isinstance(file.get("size"), int) else "")
            + "</li>"
            for file in files
        )
        body += f'<div class="label">Attached</div><ul>{items}</ul>'

    return f'<div class="turn human"><div class="speaker">Researcher</div>{body}</div>'


def note_html(event: ChatEvent, lead: str) -> str:
    to = event.data.get("to")
    label = (
        f"A note to {escape(lead)}"
        if to == "lead"
        else "A note to the team"
        if to == "lab"
        else "A note that came too late for anyone to read"
    )

    return (
        f'<div class="turn human"><div class="speaker">{escape(event.speaker or HUMAN_SPEAKER)}</div>'
        f'<div class="label">{label}</div><div class="body plain">{escape(event.text)}</div></div>'
    )


def turn_html(turn: Turn, lead: str, sessions: dict[str, Path], figures: Figures, max_output_chars: int) -> str:
    """A turn: what the researcher said, what the lead did and answered, and how it ended."""
    parts = [f'<div class="round">Turn {turn.number}</div>']
    if turn.user is not None:
        parts.append(user_html(turn.user))

    steps: list[str] = []
    for kind, step in turn.steps:
        if kind == "say":
            steps.append(f'<div class="body">{markdown(step)}</div>')
        elif kind == "call":
            steps.append(call_html(step, sessions, figures, max_output_chars))
        elif kind == "resources":
            steps.append(f'<p class="meta">{escape(describe_resources(step))}</p>')
        else:
            steps.append(note_html(step, lead))
    end = turn.end
    if end is not None and end.kind == "answer":
        steps.append(f'<div class="body">{markdown(end.text)}</div>')
    if steps:
        parts.append(
            f'<div class="turn" style="--colour: {AGENT_COLOURS[0]}"><div class="speaker">{escape(lead)}</div>'
            f'{"".join(steps)}</div>'
        )

    if end is None:
        parts.append('<div class="callout">This turn had not ended when the conversation was saved.</div>')
    elif end.kind == "stopped":
        parts.append(f'<div class="callout">{escape(end.text or "The researcher stopped this turn.")}</div>')
    elif end.kind == "failed":
        parts.append(f'<div class="callout error">{escape(end.text or "This turn ended with an error.")}</div>')

    return "\n".join(parts)


def team_sessions_of(chat_dir: Path) -> dict[str, Path]:
    """The transcripts of the team sessions the lead held, by the name each was saved under, in the order they
    were held. One that was stopped or failed is there as far as it got. A ledger that cannot be read is taken as
    the lead having held none, so that the conversation can still be saved."""
    ledger_path = Path(chat_dir) / CHAT_LAB_DIR_NAME / PROJECT_FILE_NAME
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    steps = ledger.get("steps") if isinstance(ledger, dict) else None
    sessions: dict[str, Path] = {}
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict) or step.get("kind") != "meeting" or not isinstance(step.get("name"), str):
            continue
        files = step.get("files")
        files = files if isinstance(files, dict) else {}
        saved = files.get("transcript") or files.get("partial")
        if isinstance(saved, str) and (path := ledger_path.parent / saved).is_file():
            sessions[step["name"]] = path

    return sessions


def chat_html(
    chat_dir: Path,
    files_dir: Path | None = None,
    team_sessions: bool = True,
    max_output_chars: int = MAX_EXPORTED_OUTPUT_CHARS,
) -> str:
    """A conversation as an HTML document: the lead and its team, then each turn as it went, then the team sessions.

    :param chat_dir: The conversation's directory.
    :param files_dir: Where the figures its code drew are, which is the session's directory. By default, where
        the conversation says its session was, which is not where it is if the directory has been moved.
    :param team_sessions: Whether to add every team session the lead held, each from a new page.
    :param max_output_chars: The most of what a tool or a piece of code returned to show for one call, half from
        each end.
    :raises FileNotFoundError: If there is no conversation there.
    :raises ValueError: If what is there is not a conversation's.
    :return: The document.
    """
    chat_dir = Path(chat_dir)
    chat = load_chat(chat_dir)
    info = chat.info
    if files_dir is None and (info.get("session") or {}).get("directory"):
        files_dir = Path(info["session"]["directory"])
    sessions = team_sessions_of(chat_dir) if team_sessions else {}
    turns = turns_of(chat.events)

    lead = info.get("lead") or {}
    agents = [lead, *(info.get("team") or [])] if lead else list(info.get("team") or [])
    members = [
        (agent, AGENT_COLOURS[place % len(AGENT_COLOURS)], "lead" if agent is lead else None)
        for place, agent in enumerate(agents)
    ]
    title = info.get("title") or "Conversation"

    parts = [
        '<div class="eyebrow">Virtual Lab · Conversation</div>',
        f"<h1>{escape(title)}</h1>",
        meta_line(
            [
                escape(when(info.get("created_at")) or "") or None,
                f"{len(turns)} {'turn' if len(turns) == 1 else 'turns'}",
                f"cost {money(info.get('spent'))}",
            ]
        ),
    ]
    if members:
        parts.append(f"<h2>The lead and the team it can call on</h2>{team_cards(members)}")

    if turns:
        figures = Figures(files_dir)
        parts.append("<h2>The conversation</h2>")
        parts.extend(
            turn_html(turn, str(lead.get("title") or "Lead"), sessions, figures, max_output_chars) for turn in turns
        )
    else:
        parts.append("<p>Nothing has been said in this conversation yet.</p>")

    for name, path in sessions.items():
        try:
            section = meeting_body(load_meeting(path), False, max_output_chars, heading_level=2)
        except (OSError, ValueError):
            section = (
                '<div class="eyebrow">Virtual Lab · Team meeting</div>'
                f"<h2>{escape(humanize(name))}</h2>"
                '<div class="callout error">This session could not be read, so what was said in it is not here.</div>'
            )
        parts.append(f'<section class="meeting" id="{session_anchor(name)}">{section}</section>')

    return document(str(title), "\n".join(parts))


def save_chat_html(chat_dir: Path, html_path: Path | None = None, **options: Any) -> Path:
    """Saves a conversation as an HTML document, as conversation.html in its directory unless told where.

    :param chat_dir: The conversation's directory.
    :param html_path: Where to save it, or None for conversation.html in the conversation's directory.
    :param options: What chat_html takes.
    :return: Where it was saved.
    """
    chat_dir = Path(chat_dir)
    path = Path(html_path) if html_path is not None else chat_dir / "conversation.html"
    page = chat_html(chat_dir, **options)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")

    return path


def save_chat_pdf(chat_dir: Path, pdf_path: Path | None = None, **options: Any) -> Path:
    """Saves a conversation as a PDF, as conversation.pdf in its directory unless told where.

    :param chat_dir: The conversation's directory.
    :param pdf_path: Where to save it, or None for conversation.pdf in the conversation's directory.
    :param options: What chat_html takes.
    :raises PDFExportError: If WeasyPrint or Pango is not installed.
    :return: Where it was saved.
    """
    chat_dir = Path(chat_dir)
    path = Path(pdf_path) if pdf_path is not None else chat_dir / "conversation.pdf"

    return render_pdf(chat_html(chat_dir, **options), path)
