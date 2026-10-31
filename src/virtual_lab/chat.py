"""A conversation with the head of a lab, who answers, runs code, or has the team work on it.

Meetings and projects are run to a plan: they are given an agenda or a goal and report when they
are done. A Chat is the other way round. A researcher talks to one agent, the lead, which answers
directly when it can, runs code in a session when the answer needs a computation, and, when a
question needs more than one kind of expertise, calls a tool to bring the team in: convene_team
for a discussion the lead leads, or consult for one scientist to work on a focused task with the
Scientific Critic reviewing it. Those are meetings, held as a Project holds them, in the same
session and within the same budget, and the lead is given what they concluded.

Everything that happens is told of through ChatEvents, kept in order, so that a page can follow a
turn as it goes and, after it is closed, find the conversation as it was. The conversation lives
in its directory: chat.json says what it is, messages.jsonl holds what the lead has been sent and
has said, events.jsonl what happened, uploads/ the files the researcher attached, and lab/ the
meetings the lead held, which are a Project. A Chat opened on a directory carries on from there.

One turn runs at a time, in the thread that calls send, or in one of its own with start. The
researcher can steer it from any other thread: add a note, which the lead, or the team if it is
working, reads before it goes on; pause it, to hold it before its next request; or stop it, which
ends it at the next point it can be and keeps what was done. How much it may spend, and how many team
sessions and rounds the lead may ask for, can be changed at any time with set_limits.
"""

import hashlib
import itertools
import json
import math
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, BinaryIO, Literal

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from virtual_lab.agent import Agent
from virtual_lab.completions import check_temperature, send_request
from virtual_lab.constants import (
    CHAT_EVENTS_FILE_NAME,
    CHAT_FILE_NAME,
    CHAT_LAB_DIR_NAME,
    CHAT_MESSAGES_FILE_NAME,
    CHAT_UPLOADS_DIR_NAME,
    CONSISTENT_TEMPERATURE,
    DEFAULT_MAX_RETRIES,
    HUMAN_SPEAKER,
    MAX_CHAT_DELEGATION_ROUNDS,
    MAX_CHAT_DELEGATIONS,
    MAX_CHAT_TITLE_CHARS,
    MAX_TOOL_ITERATIONS,
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_NAME_BYTES,
    SESSION_MAX_TOOL_ITERATIONS,
)
from virtual_lab.directives import DIRECTIVES, Check, Directive, LabRequest, directive_named, is_literature_tool
from virtual_lab.events import ChatEvent, ChatEventKind, MeetingEvent, NextTurn, OnChatEvent
from virtual_lab.failures import Failure, describe_failure
from virtual_lab.llm import ModelReply, ModelSource, ToolCall, ask, resolve_chat_models
from virtual_lab.project import Project, sha256_file
from virtual_lab.prompts import (
    SCIENTIFIC_CRITIC,
    chat_attachments_prompt,
    chat_note_prompt,
    chat_resources_prompt,
    chat_session_prompt,
    lab_chat_prompt,
)
from virtual_lab.provenance import describe_agent, utc_timestamp
from virtual_lab.resources import (
    Resources,
    available_resources,
    check_installed,
    parse_retrieval,
    resources_prompt,
    retrieval_prompt,
    select_resources,
)
from virtual_lab.run_meeting import MeetingResult, TruncatedResponseError
from virtual_lab.schemas import normalize_title
from virtual_lab.session import CODE_TOOL_NAME, Session, own_resources_prompt, session_tool
from virtual_lab.tools import PUBMED_TOOL, Tool, run_tool_calls, tool_instructions_prompt
from virtual_lab.utils import (
    BudgetExceededError,
    ContextLengthExceededError,
    CostUnknownError,
    MeetingUsage,
    ModelUsage,
    check_context_length,
    combine_usage,
    compute_token_cost,
    count_message_tokens,
    get_max_input_tokens,
    write_atomically,
)

ChatState = Literal["idle", "running", "pausing", "paused", "stopping"]
ChatStatus = Literal["answered", "stopped", "failed"]

# The tools the lead has that are not its own to name, and the two that start a team session
FIND_RESOURCES_TOOL_NAME = "find_resources"
CONVENE_TOOL_NAME = "convene_team"
CONSULT_TOOL_NAME = "consult"
RESERVED_TOOL_NAMES = frozenset({CODE_TOOL_NAME, FIND_RESOURCES_TOOL_NAME, CONVENE_TOOL_NAME, CONSULT_TOOL_NAME})

# The tool of the library's that looks inside a table, which a conversation with no session can be given, and which
# then tells the lead that the files attached can be looked into
INSPECT_FILE_TOOL_NAME = "inspect_data_file"

# The events that whatever supplies the lead's tools tells of, with Chat.tell
TOLD_BY_TOOLS = frozenset({"connection", "approval", "question"})

# The events of a team session that a stop interrupts, since they are told of before the work
# they announce, in the thread that does it
STOPPABLE_LAB_EVENTS = frozenset({"turn", "writing", "message", "tool_calls", "code"})

# What a team session's events are not passed on for: its usage is the conversation's, told of
# as one, and its prompts, which hold all the resources it was told of, are in its transcript
UNTOLD_LAB_EVENTS = frozenset({"usage"})

STOPPED_REPLY = "I was stopped by the researcher before I finished."

# What the project that holds the team's meetings is for, which only has to be the same every time
CHAT_PROJECT_GOAL = "Conversation with the head of a lab"


class _Unchanged:
    """What a limit that is left as it is is given as, since None is what a spending limit is when there is none."""

    def __repr__(self) -> str:
        return "UNCHANGED"


UNCHANGED = _Unchanged()


class ChatBusyError(RuntimeError):
    """Raised when a message is sent to a conversation that is still working on the last one."""


class ChatClosedError(RuntimeError):
    """Raised when a message is sent to a conversation that was closed."""


class ChatStopped(Exception):
    """Raised in a turn the researcher stopped, at the point it was stopped."""

    def __init__(self) -> None:
        super().__init__("Stopped by the researcher")


class UploadTooLargeError(ValueError):
    """Raised when a file the researcher attached is larger than a conversation takes."""


@dataclass(frozen=True)
class Attachment:
    """A file the researcher attached to the conversation.

    :param name: Its name, in the uploads directory.
    :param path: Where it is, relative to the session's working directory, as code reads it.
    :param size: Its size in bytes.
    """

    name: str
    path: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "path": self.path, "size": self.size}


@dataclass(frozen=True)
class ChatReply:
    """How a turn ended.

    :param status: "answered" if the lead replied, "stopped" if the researcher stopped it, or
        "failed" if it ended with an error, which is also told of as an event.
    :param text: The lead's answer, or an empty string if it did not give one.
    :param error: What stopped it, as its type and message, if it failed.
    :param usage: The usage of the whole conversation so far, as MeetingUsage.to_dict gives it.
    :param elapsed_time: Seconds the turn took.
    """

    status: ChatStatus
    text: str
    error: str | None
    usage: dict[str, Any]
    elapsed_time: float


def cut_to_bytes(text: str, size: int) -> str:
    """The start of text that is at most size bytes in UTF-8, without half of a character."""
    return text.encode()[:size].decode(errors="ignore")


def safe_filename(name: str) -> str:
    """Makes a name a file can be saved under in a directory, whatever it was uploaded as.

    :param name: The name the file came with, which may have a path, as a browser sends it.
    :return: Its last part, without control characters or a leading dot, and short enough, in bytes,
        for a file system to take with a number added to it.
    """
    name = re.sub(r"[\x00-\x1f\x7f]", "", name.replace("\\", "/").rsplit("/", 1)[-1])
    name = name.strip().lstrip(".").strip()
    if len(name.encode()) > MAX_UPLOAD_NAME_BYTES:
        stem, suffix = os.path.splitext(name)
        suffix = cut_to_bytes(suffix, 20)
        name = cut_to_bytes(stem, MAX_UPLOAD_NAME_BYTES - len(suffix.encode())) + suffix

    return name or "upload"


def describe_size(size: int) -> str:
    """A size in bytes as a person reads it."""
    if size < 1024:
        return f"{size} bytes"

    value = size / 1024
    for unit in ("KB", "MB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024

    return f"{value:.1f} GB"


def title_of(text: str, files: Sequence[Attachment]) -> str:
    """A conversation's title from the first thing the researcher said."""
    line = next((" ".join(line.split()) for line in text.splitlines() if line.strip()), "")
    line = line or (files[0].name if files else "")
    if len(line) > MAX_CHAT_TITLE_CHARS:
        line = line[: MAX_CHAT_TITLE_CHARS - 1].rstrip() + "…"

    return line


def is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_usage(value: Any) -> bool:
    """Whether it is what MeetingUsage.to_dict gives, as far as MeetingUsage.from_dict reads it."""
    per_model = value.get("per_model", {}) if isinstance(value, dict) else None

    known = {usage_field.name for usage_field in fields(ModelUsage)}

    return isinstance(per_model, dict) and all(
        isinstance(counts, dict) and all(is_count(count) for name, count in counts.items() if name in known)
        for counts in per_model.values()
    )


# What a conversation saves in chat.json that is read back, each with whether a value is of the kind and what that is
SAVED_INFO_PARTS: dict[str, tuple[Callable[[Any], bool], str]] = {
    "title": (lambda value: value is None or isinstance(value, str), "text"),
    "created_at": (lambda value: isinstance(value, str), "text"),
    "turns": (is_count, "a whole number"),
    "lab_calls": (is_count, "a whole number"),
    "events": (is_count, "a whole number"),
    "usage": (is_usage, "the usage a conversation saves"),
}


def read_chat_info(path: Path) -> dict[str, Any]:
    """Reads what a conversation saved of itself, which is read back before anything is built from it.

    :raises ValueError: If the file is not JSON, or what it holds is not what a conversation saves, which a file that
        was changed, or is not a conversation's, can hold.
    """
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError(f"{path} cannot be read: {error}") from error
    if not isinstance(info, dict):
        raise ValueError(f"{path} cannot be used: it holds {type(info).__name__}, not an object")
    for name, (is_valid, described) in SAVED_INFO_PARTS.items():
        if name in info and not is_valid(info[name]):
            found = type(info[name]).__name__
            raise ValueError(f"{path} cannot be used: its {name} should be {described}, not {found}")

    return info


def read_json_lines(path: Path, repair: bool = True) -> list[dict[str, Any]]:
    """Reads a file of JSON objects, one to a line, as the conversation saved it.

    A last line cut short, as a process killed while writing leaves, is dropped, and the file
    made whole again so that what is written next starts a line of its own.

    :param repair: Whether to make the file whole, and to warn of the line that was cut short. A reader
        that is not the conversation leaves the file alone, and takes the last line, which the
        conversation may be writing as it reads, to be unfinished, not cut short.
    :raises ValueError: If any other line is not JSON, or is JSON that is not an object, which is not what a crash
        does.
    """
    if not path.is_file():
        return []

    # A crash can cut the last line in the middle of a character, which is then dropped with the line
    text = path.read_bytes().decode("utf-8", errors="replace")
    # Only a newline ends a line: text may hold the other characters splitlines breaks at, such as U+2028
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    items: list[dict[str, Any]] = []
    mend = bool(text) and not text.endswith("\n")
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            if number < len(lines):
                raise ValueError(f"Line {number} of {path} is not JSON: {error}") from error
            if repair:
                print(f"Warning: the last line of {path} was cut short, and is left out")
            mend = True
            continue
        if not isinstance(item, dict):
            raise ValueError(f"Line {number} of {path} is not a JSON object, but {type(item).__name__}")
        items.append(item)

    if mend and repair:
        write_atomically(path, "".join(json_line(item) for item in items).encode("utf-8"))

    return items


def json_line(item: Any) -> str:
    return json.dumps(item, ensure_ascii=False, default=str) + "\n"


def append_json_line(path: Path, item: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json_line(item))


def describe_call(call: ToolCall) -> dict[str, str]:
    return {"id": call.id, "name": call.function.name, "arguments": call.function.arguments}


def request_of(call: ToolCall) -> tuple[str, str]:
    """What a tool call asks, as the tool and its arguments, which are the same however they were written out."""
    try:
        arguments = json.dumps(json.loads(call.function.arguments), sort_keys=True)
    except ValueError:
        arguments = call.function.arguments

    return call.function.name, arguments


class Chat:
    """A conversation between a researcher and the head of a lab.

    :param save_dir: The conversation's directory, where an earlier run of it was saved, if there
        was one, which is carried on from.
    :param lead: The head of the lab, who the researcher talks to.
    :param team: The scientists the lead can bring in, each by its title. A Scientific Critic among
        them reviews a scientist the lead consults. With none, the lead works alone.
    :param session: A session for the lead and the team to run code in, as hold_meeting takes it,
        started on the first message and left running afterwards, so close it when done. It is
        also where the files the researcher attaches are saved, in its directory's uploads/,
        which is where code finds them. Without one nobody can run code.
    :param title: What to call the conversation; by default its first message, shortened.
    :param chat_models: The chat models to ask, as hold_meeting takes them.
    :param client: An OpenAI client, as hold_meeting takes it.
    :param max_cost: The most the conversation may spend, in USD, the lead's requests and the team's
        together and over every run of it on this directory. It is checked before every request,
        so it can be overrun by the cost of one; max_completion_tokens bounds that. Every model
        must be priced for the limit to mean anything.
    :param temperature: The sampling temperature, as hold_meeting takes it.
    :param max_completion_tokens: The most tokens any one response may use, or None for the
        model's own limit.
    :param max_retries: The times to retry a failed API call, as hold_meeting takes it.
    :param tools: Tools the lead, and the team in its sessions, may call, as hold_meeting takes
        them. The tool that runs code is added if there is a session.
    :param pubmed_search: Whether to add the PubMed tool to them.
    :param late_tools: Gives more tools of the same kind, for those that cannot be had until the
        first message, such as those of servers that have to be connected to, which may take a
        person's sign-in. It is called once, in the thread that answers the first message, after the
        session has started and before the first request, and the tools it gives join tools, for
        the lead and the team. What it raises fails that turn before anything is spent, as a
        session that cannot start does, and it is called again for the next message, so it must
        be safe to call again, and none of what it gave is kept. Raising ChatStopped ends the turn
        as stopped.
    :param resources: What of Biomni's environment the lead is told of in the session: with
        "retrieve", that it has a find_resources tool, which asks which suit a task, at the cost of
        one request of about 12,000 tokens when it does; with "all", every one, which is about
        40,000 tokens more in every request; or a Resources of your own. "none" lists nothing.
        The team's meetings are given the same. Only used with a session.
    :param commercial_mode: Whether to leave out data and know-how that may not be used
        commercially, as hold_meeting takes it.
    :param max_tool_iterations: The most tool calls the lead makes in answering one message before it
        is asked to answer without them. Defaults to 20 with a session, and 5 without one.
    :param max_delegations: The most team sessions the lead may start in answering one message.
        With none, the lead does not have the tools to start any.
    :param max_rounds: The most rounds of discussion the lead may ask a team session for.
    :param stream: Whether on_event, and anyone following the conversation, is also told of each
        reply as it is written, with "writing" events, as hold_meeting takes it.
    :param on_event: Called with every ChatEvent in the thread that caused it, which can be any
        thread that steers the conversation, with no lock of the conversation's held, so that a slow
        one holds up only that thread. Events from different threads may arrive out of order: their
        id is the order they happened in. It may call the conversation's own methods, but it must
        not wait for another thread that does. An exception it raises ends the turn the way any
        other failure does, except from an event that tells of how the turn ended or of the state
        the conversation is in, which are warned of, so that a failing callback, such as one for
        a page that went away, cannot leave the conversation running.
    :param max_upload_bytes: The most bytes of one file the researcher may attach.
    :raises ValueError: If an argument is not valid, or the lead and the team do not have titles of
        their own.
    :raises CostUnknownError: If max_cost is given and a model is not priced.
    :raises ProjectStateError: If save_dir holds a project that is not this conversation's.
    """

    def __init__(
        self,
        save_dir: Path,
        lead: Agent,
        team: Sequence[Agent] = (),
        session: Session | None = None,
        title: str | None = None,
        chat_models: ModelSource | None = None,
        client: OpenAI | None = None,
        max_cost: float | None = None,
        temperature: float = CONSISTENT_TEMPERATURE,
        max_completion_tokens: int | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        tools: tuple[Tool, ...] = (),
        pubmed_search: bool = False,
        late_tools: Callable[[], Iterable[Tool]] | None = None,
        resources: Literal["retrieve", "all", "none"] | Resources = "retrieve",
        commercial_mode: bool = False,
        max_tool_iterations: int | None = None,
        max_delegations: int = MAX_CHAT_DELEGATIONS,
        max_rounds: int = MAX_CHAT_DELEGATION_ROUNDS,
        stream: bool = False,
        on_event: OnChatEvent | None = None,
        max_upload_bytes: int = MAX_UPLOAD_BYTES,
    ) -> None:
        if max_cost is not None and not (math.isfinite(max_cost) and max_cost >= 0):
            raise ValueError(f"max_cost must be a finite amount, zero or more, not {max_cost}")
        check_temperature(temperature)
        if max_completion_tokens is not None and max_completion_tokens < 1:
            raise ValueError(f"max_completion_tokens must be at least 1, not {max_completion_tokens}")
        if max_tool_iterations is None:
            max_tool_iterations = SESSION_MAX_TOOL_ITERATIONS if session is not None else MAX_TOOL_ITERATIONS
        elif max_tool_iterations < 1:
            raise ValueError(f"max_tool_iterations must be at least 1, not {max_tool_iterations}")
        if max_delegations < 0:
            raise ValueError(f"max_delegations must be zero or more, not {max_delegations}")
        if max_rounds < 0:
            raise ValueError(f"max_rounds must be zero or more, not {max_rounds}")
        if max_upload_bytes < 1:
            raise ValueError(f"max_upload_bytes must be at least 1, not {max_upload_bytes}")
        if not_tools := [type(tool).__name__ for tool in tools if not isinstance(tool, Tool)]:
            raise TypeError(f"A conversation's tools are Tools, not {', '.join(not_tools)}")
        if isinstance(resources, Resources):
            if session is None:
                raise ValueError("resources lists what can be used in a session, so it needs a session")
        elif resources not in ("retrieve", "all", "none"):
            raise ValueError(f'resources must be "retrieve", "all", "none", or a Resources, not {resources!r}')

        team = tuple(team)
        titles = [normalize_title(agent.title) for agent in (lead, *team)]
        if not all(titles):
            raise ValueError("Everyone in a conversation needs a title")
        if len(set(titles)) != len(titles):
            raise ValueError("The lead and the team must have different titles")
        if normalize_title(HUMAN_SPEAKER) in titles:
            raise ValueError(f"{HUMAN_SPEAKER} is the title of the researcher's notes, so no agent may have it")

        chat_tools = tools
        if pubmed_search and PUBMED_TOOL.name not in {tool.name for tool in tools}:
            chat_tools = (PUBMED_TOOL, *tools)
        if taken := sorted({tool.name for tool in chat_tools} & RESERVED_TOOL_NAMES):
            raise ValueError(f"A conversation has tools of its own named {', '.join(taken)}, so no other may be")
        if len({tool.name for tool in chat_tools}) != len(chat_tools):
            raise ValueError("Tool names must be unique")

        if max_cost is not None:
            for agent in (lead, *team):
                try:
                    compute_token_cost(agent.model, 0, 0)
                except CostUnknownError as error:
                    raise CostUnknownError(
                        f"{error}, so a max_cost cannot be enforced. Add its prices to the tables in "
                        f"virtual_lab.constants, or run without a limit."
                    ) from error

        self.save_dir = Path(save_dir).resolve()
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.id = self.save_dir.name
        self.lead = lead
        self.team = team
        self.session = session
        self.max_cost = max_cost
        self.temperature = temperature
        self.max_completion_tokens = max_completion_tokens
        self.resources = resources
        self.commercial_mode = commercial_mode
        self.max_tool_iterations = max_tool_iterations
        self.max_delegations = max_delegations
        self.max_rounds = max_rounds
        self.stream = stream
        self.on_event = on_event
        self.max_upload_bytes = max_upload_bytes
        self.tools = chat_tools
        self._late_tools = late_tools
        self._late_tools_added = False

        # Built before the first request, so that a model whose provider cannot be worked out, or
        # whose package is not installed, fails here, before anything is spent
        self._llms = resolve_chat_models(
            [agent.model for agent in (lead, *team)],
            chat_models=chat_models,
            client=client,
            max_retries=max_retries,
        )

        critic = next(
            (agent for agent in team if normalize_title(agent.title) == normalize_title(SCIENTIFIC_CRITIC.title)), None
        )
        self._critic = critic
        self._consultants = tuple(agent for agent in team if agent is not critic)

        self._changed = threading.Condition()
        self._uploading = threading.Lock()
        self._events: list[ChatEvent] = []
        self._live: dict[tuple[Any, ...], ChatEvent] = {}
        self._state_event: ChatEvent | None = None
        self._next_id = 1
        self._messages: list[dict[str, Any]] = []
        self._notes: list[str] = []
        self._state: ChatState = "idle"
        self._paused = False
        self._stopping = False
        self._closed = False
        self._thread: threading.Thread | None = None
        self.last_reply: ChatReply | None = None

        self._turn = 0
        self._lab_calls = 0
        self._delegations = 0
        self._usage = MeetingUsage()
        self._requests = itertools.count(1)
        self._call_id: str | None = None
        # The command the message being answered was given with, and with /lab who is to work on it, what the lead has
        # called since, whether the Critic has reviewed its last answer, and how many cells the session had run when
        # it began
        self._directive: Directive | None = None
        self._lab: LabRequest | None = None
        self._called: set[str] = set()
        self._reviewed = False
        self._cells_before = 0

        # Worked out on the first message, since it starts the session
        self._system: str | None = None
        self._lead_tools: tuple[Tool, ...] = ()
        # What the lead is told and given that does not depend on who is on the team or how much it may do, which
        # is put together with what does, again if the limits are changed
        self._fixed_parts: tuple[str, ...] = ()
        self._fixed_tools: tuple[Tool, ...] = ()
        self._reassemble = False
        self._catalog: Resources | None = None
        self._cells_told = 0

        self.title = title or ""
        self.created_at = utc_timestamp()
        self._load()

        self.project = Project(
            save_dir=self.save_dir / CHAT_LAB_DIR_NAME,
            goal=CHAT_PROJECT_GOAL,
            session=session,
            chat_models=chat_models,
            client=client,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            max_retries=max_retries,
            tools=chat_tools,
            resources=resources,
            commercial_mode=commercial_mode,
            stream=stream,
        )
        self._recover()
        if not (self.save_dir / CHAT_FILE_NAME).is_file():
            self._save_info()

    # Loading and saving

    def _load(self) -> None:
        info_path = self.save_dir / CHAT_FILE_NAME
        self._interrupted = False
        numbered = 0
        if info_path.is_file():
            info = read_chat_info(info_path)
            self.title = info.get("title") or self.title
            self.created_at = info.get("created_at", self.created_at)
            self._turn = info.get("turns", 0)
            self._lab_calls = info.get("lab_calls", 0)
            self._usage = MeetingUsage.from_dict(info.get("usage", {}))
            self._interrupted = bool(info.get("running"))
            numbered = info.get("events", 0)

        events_path = self.save_dir / CHAT_EVENTS_FILE_NAME
        self._events = []
        for number, saved in enumerate(read_json_lines(events_path), start=1):
            try:
                self._events.append(ChatEvent.from_dict(saved))
            except ValueError as error:
                raise ValueError(f"Event {number} of {events_path} cannot be used: {error}") from error
        # The state the conversation was in is numbered like an event but not kept, so what was
        # numbered is saved too, and a page that saw that number is not told of a new event by it
        self._next_id = max(numbered, *(event.id for event in self._events), 0) + 1

        messages_path = self.save_dir / CHAT_MESSAGES_FILE_NAME
        self._messages = read_json_lines(messages_path)
        for number, message in enumerate(self._messages, start=1):
            if not isinstance(message.get("role"), str):
                raise ValueError(f"Message {number} of {messages_path} cannot be used: it has no role")

    def _recover(self) -> None:
        """Ends a turn that a process stopped in, so that the conversation can go on from it."""
        if not self._interrupted:
            return

        reason = "The process running this conversation stopped before the turn ended."
        self._close_open_calls(f"Not run. {reason}")
        self._emit_ending("failed", reason, type="Interrupted")
        self._save_info()

    def _save_info(self) -> None:
        with self._changed:
            try:
                spent: float | None = self._total_usage().compute_cost()
            except CostUnknownError:
                spent = None
            info = {
                "id": self.id,
                "title": self.title,
                "created_at": self.created_at,
                "updated_at": utc_timestamp(),
                "lead": describe_agent(self.lead),
                "team": [describe_agent(agent) for agent in self.team],
                "session": self.session.describe() if self.session is not None else None,
                "max_cost": self.max_cost,
                "max_delegations": self.max_delegations,
                "max_rounds": self.max_rounds,
                "spent": spent,
                "turns": self._turn,
                "events": self._next_id - 1,
                "lab_calls": self._lab_calls,
                "running": self._state != "idle",
                "usage": self._usage.to_dict(),
            }
            write_atomically(self.save_dir / CHAT_FILE_NAME, json.dumps(info, indent=4, default=str).encode("utf-8"))

    def _append(self, message: dict[str, Any]) -> None:
        with self._changed:
            self._messages.append(message)
            append_json_line(self.save_dir / CHAT_MESSAGES_FILE_NAME, message)

    # Telling the caller

    def _record(self, kind: ChatEventKind, speaker: str | None, text: str, data: dict[str, Any]) -> ChatEvent:
        with self._changed:
            event = ChatEvent(
                kind=kind, id=self._next_id, turn=self._turn, speaker=speaker, text=text, data=data, time=time.time()
            )
            self._next_id += 1
            if kind == "writing":
                self._live[(data.get("meeting"), data.get("request"))] = event
            elif kind == "status":
                self._state_event = event
            else:
                # Whatever was being written is written, and is told of whole by this
                self._live.clear()
                self._events.append(event)
                append_json_line(self.save_dir / CHAT_EVENTS_FILE_NAME, event.to_dict())
            self._changed.notify_all()

        return event

    # Positional only, so that an event's own data can be called anything
    def _emit(self, kind: ChatEventKind, /, speaker: str | None = None, text: str = "", **data: Any) -> ChatEvent:
        event = self._record(kind, speaker, text, data)
        if self.on_event is not None:
            self.on_event(event)

        return event

    def tell(self, kind: Literal["connection", "approval", "question"], /, text: str = "", **data: Any) -> ChatEvent:
        """Tells of something that happens round the lead's work, which only a tool or the code that supplies tools
        knows of: a server being connected to, a call that waits for the researcher, or a question a server asks.
        The event is numbered, kept, and passed on as the rest are.

        :param kind: "connection", "approval", or "question", as ChatEvent describes them.
        :param text: What it says, as ChatEvent describes for the kind.
        :param data: The rest, as ChatEvent describes for the kind.
        :raises ValueError: If it is not one of those kinds, so that what the lead and the researcher said, and how
            a turn ended, cannot be told of from outside.
        """
        if kind not in TOLD_BY_TOOLS:
            raise ValueError(f"Only {', '.join(sorted(TOLD_BY_TOOLS))} can be told of from outside, not {kind!r}")

        return self._emit(kind, text=text, **data)

    def _emit_ending(self, kind: ChatEventKind, text: str, **data: Any) -> None:
        """Tells of what ends a turn, which has been done and paid for by now, so that a caller's
        failure to take it does not undo that or hide the error that ended the turn."""
        try:
            self._emit(kind, text=text, **data)
        except Exception as error:
            print(f"Warning: on_event failed when told of the end of the turn: {error!r}")

    def _change_state(self, state: ChatState) -> ChatEvent | None:
        """Moves the conversation to a state, with self._changed held, and numbers the event that tells
        of it, which is for _tell_state to pass on once the lock is released, so that a callback that
        is slow cannot hold up whoever else is steering or following the conversation."""
        if self._state == state:
            return None
        self._state = state

        return self._record("status", None, "", {"state": state})

    def _tell_state(self, event: ChatEvent | None) -> None:
        if event is None or self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception as error:
            print(f"Warning: on_event failed when told the conversation was {event.data['state']}: {error!r}")

    def events_since(self, after: int = 0) -> list[ChatEvent]:
        """What has happened since the event numbered after, in order, for a page to catch up with.

        What is being written, and the state the conversation is in, are the latest of each, not
        what they were as they changed.
        """
        with self._changed:
            return self._since(after)

    def wait_for_events(self, after: int, timeout: float | None = None) -> list[ChatEvent]:
        """What has happened since the event numbered after, waiting up to timeout seconds for
        something to, or for the conversation to be closed. An empty list means nothing did."""
        with self._changed:
            self._changed.wait_for(lambda: self._next_id - 1 > after or self._closed, timeout)
            return self._since(after)

    def _since(self, after: int) -> list[ChatEvent]:
        latest = [self._state_event] if self._state_event is not None else []
        pending = [*self._events, *self._live.values(), *latest]

        return sorted((event for event in pending if event.id > after), key=lambda event: event.id)

    def describe(self) -> dict[str, Any]:
        """What the conversation is and where it stands, in JSON's types, for a page that lists it.

        It holds its id, title, created_at, state, how many turns and team sessions there have been, what it
        has cost and may cost, its usage, the number of the last event, who leads and who is on the team by
        title, and whether anyone can run code. max_cost, max_delegations and max_rounds are the limits as
        set_limits has left them. directives says of each command that can be given with a message why it cannot
        be, in words, or None if it can, as far as that does not depend on what was said before.
        """
        with self._changed:
            return {
                "id": self.id,
                "title": self.title,
                "created_at": self.created_at,
                "state": self._state,
                "turns": self._turn,
                "lab_calls": self._lab_calls,
                "spent": self.spent,
                "max_cost": self.max_cost,
                "max_delegations": self.max_delegations,
                "max_rounds": self.max_rounds,
                "usage": self._total_usage().to_dict(),
                "last_event_id": self._next_id - 1,
                "lead": self.lead.title,
                "team": [agent.title for agent in self.team],
                "can_run_code": self.session is not None,
                "directives": {name: self._why_not(directive) for name, directive in DIRECTIVES.items()},
            }

    @property
    def messages(self) -> list[dict[str, Any]]:
        """What the lead has been sent and has said, as it reads them, copied."""
        with self._changed:
            return [dict(message) for message in self._messages]

    @property
    def state(self) -> ChatState:
        with self._changed:
            return self._state

    @property
    def turns(self) -> int:
        """How many messages the researcher has sent."""
        with self._changed:
            return self._turn

    @property
    def usage(self) -> MeetingUsage:
        """What the lead and the team have used between them, in tokens, per model."""
        with self._changed:
            return self._total_usage()

    @property
    def spent(self) -> float | None:
        """What the conversation has cost in USD, or None if that cannot be worked out."""
        try:
            return self.usage.compute_cost()
        except CostUnknownError:
            return None

    def _total_usage(self) -> MeetingUsage:
        return combine_usage([self._usage, *(MeetingUsage.from_dict(step.usage) for step in self.project.steps)])

    def _usage_data(self) -> dict[str, Any]:
        return {**self._total_usage().to_dict(), "max_cost": self.max_cost}

    def _tell_usage(self) -> None:
        with self._changed:
            data = self._usage_data()
        self._emit("usage", **data)

    # What the researcher does

    def add_note(self, note: str) -> bool:
        """Adds a note, which the lead, or the team if it is working, reads before it goes on.

        :return: False if there is nothing to add it to, because no turn is running or the note is empty.
        """
        note = note.strip()
        with self._changed:
            if not note or self._state == "idle" or self._closed:
                return False
            self._notes.append(note)
            self._changed.notify_all()

        return True

    def pause(self) -> bool:
        """Holds the turn before its next request, or the next turn of a team session. A turn
        that is running code or a tool is carried through first. False if no turn is running."""
        with self._changed:
            if self._state not in ("running", "pausing", "paused"):
                return False
            self._paused = True
            told = self._change_state("pausing") if self._state == "running" else None
        self._tell_state(told)

        return True

    def resume(self) -> bool:
        """Lets a paused turn go on. False if it was not paused."""
        with self._changed:
            if not self._paused:
                return False
            self._paused = False
            told = self._change_state("running") if self._state in ("pausing", "paused") else None
            self._changed.notify_all()
        self._tell_state(told)

        return True

    def stop(self) -> bool:
        """Ends the turn at the next point it can be, keeping what was done. Code or a tool that is
        running is not interrupted. False if no turn is running."""
        with self._changed:
            if self._state == "idle":
                return False
            self._stopping = True
            told = self._change_state("stopping")
            self._changed.notify_all()
        self._tell_state(told)

        return True

    def set_limits(
        self,
        max_cost: float | None | _Unchanged = UNCHANGED,
        max_delegations: int | _Unchanged = UNCHANGED,
        max_rounds: int | _Unchanged = UNCHANGED,
    ) -> None:
        """Changes what the conversation may spend and how much of the team's time the lead may ask for, whether or not
        a turn is running. The cost is checked before the next request, so a limit raised while a turn is stopping for
        want of money lets the next message go on. A limit lowered below what is spent stops the next request, and a
        turn that is running is ended at it as one that has reached its limit is.

        Only what is given is changed, and nothing is if any of it is not valid. How many team sessions and rounds
        the lead may ask for is told to it at the start of a turn, so a change to them is put to the lead from the next
        turn, and held to at once, since a team session that asks for more than is allowed is held to what is.

        :param max_cost: The most the conversation may spend in USD, as the constructor takes it, or None to take the
            limit away.
        :param max_delegations: The most team sessions the lead may start in answering one message.
        :param max_rounds: The most rounds of discussion the lead may ask a team session for.
        :raises ValueError: If a limit is not valid, as the constructor checks.
        :raises CostUnknownError: If a spending limit is given and a model is not priced.
        """
        if not isinstance(max_cost, _Unchanged) and max_cost is not None:
            if not (math.isfinite(max_cost) and max_cost >= 0):
                raise ValueError(f"max_cost must be a finite amount, zero or more, not {max_cost}")
            for agent in (self.lead, *self.team):
                try:
                    compute_token_cost(agent.model, 0, 0)
                except CostUnknownError as error:
                    raise CostUnknownError(
                        f"{error}, so a max_cost cannot be enforced. Add its prices to the tables in "
                        f"virtual_lab.constants, or run without a limit."
                    ) from error
        if not isinstance(max_delegations, _Unchanged) and max_delegations < 0:
            raise ValueError(f"max_delegations must be zero or more, not {max_delegations}")
        if not isinstance(max_rounds, _Unchanged) and max_rounds < 0:
            raise ValueError(f"max_rounds must be zero or more, not {max_rounds}")

        with self._changed:
            changed_cost = not isinstance(max_cost, _Unchanged) and max_cost != self.max_cost
            if not isinstance(max_cost, _Unchanged):
                self.max_cost = max_cost
            if not isinstance(max_delegations, _Unchanged) and max_delegations != self.max_delegations:
                self.max_delegations = max_delegations
                self._reassemble = True
            if not isinstance(max_rounds, _Unchanged) and max_rounds != self.max_rounds:
                self.max_rounds = max_rounds
                self._reassemble = True
            self._save_info()
        if changed_cost:
            self._tell_usage()

    def rename(self, title: str) -> None:
        """Gives the conversation another title."""
        title = " ".join(title.split())
        with self._changed:
            self.title = title
            self._save_info()
        self._emit("title", text=title)

    def close(self, timeout: float | None = None) -> None:
        """Stops the turn, if one is running, and waits up to timeout seconds for it to end.

        The session is the caller's, and is left as it was.
        """
        self.stop()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        with self._changed:
            self._closed = True
            self._changed.notify_all()

    def __enter__(self) -> "Chat":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # Files

    @property
    def uploads_dir(self) -> Path:
        """Where the files the researcher attaches are kept: in the session's directory, where its code reads them."""
        return (self.session.directory if self.session is not None else self.save_dir) / CHAT_UPLOADS_DIR_NAME

    def save_upload(self, name: str, data: bytes | BinaryIO) -> Attachment:
        """Saves a file the researcher attached, to be mentioned when they send their message.

        A file is never replaced: one with a name already taken is kept under another, unless it
        is the same file, which is not saved again.

        :param name: The name it came with, which may have a path as a browser sends it.
        :param data: Its content.
        :raises UploadTooLargeError: If it is larger than max_upload_bytes.
        """
        filename = safe_filename(name)
        directory = self.uploads_dir
        directory.mkdir(parents=True, exist_ok=True)

        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".upload.", suffix=".part")
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(handle, "wb") as file:
                blocks: Iterable[bytes] = (
                    [data] if isinstance(data, bytes) else iter(lambda: data.read(1 << 20), b"")  # type: ignore[union-attr]
                )
                for block in blocks:
                    size += len(block)
                    if size > self.max_upload_bytes:
                        raise UploadTooLargeError(
                            f"{filename} is larger than the {describe_size(self.max_upload_bytes)} that can be attached"
                        )
                    digest.update(block)
                    file.write(block)

            stem, suffix = os.path.splitext(filename)
            # Choosing a name and taking it are one step, or two uploads of a name could both take it
            with self._uploading:
                for number in itertools.count(1):
                    target = directory / (filename if number == 1 else f"{stem} ({number}){suffix}")
                    if not target.exists():
                        os.replace(temporary, target)
                        break
                    if sha256_file(target) == digest.hexdigest():
                        break
        finally:
            Path(temporary).unlink(missing_ok=True)

        return Attachment(name=target.name, path=f"{CHAT_UPLOADS_DIR_NAME}/{target.name}", size=size)

    def _attachments(self, items: Iterable[Attachment | str]) -> list[Attachment]:
        files: list[Attachment] = []
        for item in items:
            name = item.name if isinstance(item, Attachment) else item
            path = self.uploads_dir / name
            if name != safe_filename(name) or path.is_symlink() or not path.is_file():
                raise ValueError(f"No file named {name!r} was attached to this conversation")
            files.append(Attachment(name=name, path=f"{CHAT_UPLOADS_DIR_NAME}/{name}", size=path.stat().st_size))

        return files

    # Sending a message

    def send(
        self,
        message: str,
        attachments: Iterable[Attachment | str] = (),
        replace_last: bool = False,
        directive: str | None = None,
        lab: LabRequest | Mapping[str, Any] | None = None,
    ) -> ChatReply:
        """Sends the lead a message, and waits for its answer.

        :param message: What the researcher says.
        :param attachments: Files attached with save_upload, as it returned them or by name.
        :param replace_last: Whether this takes the place of the last message, to send it again or changed. That
            message, and all that came of it, is taken out of the conversation first, so that the lead
            is not told of it. What it did to the session and to the files of the lab is not undone.
        :param directive: The name of a command that says how the lead is to answer this message, such as "ask",
            without the slash. It is told of with the message, and kept with it. If the lead answers without doing
            what the command asked for, it is told once to, and the answer says whether it was done.
        :param lab: With the command "lab", who is to work on the message and how: a LabRequest, or as one is written
            out, with a mode ("team" or "individual"), the titles of the members, the rounds, and the questions.
            The lead is given the one tool that brings them together, which has them set, and writes the agenda.
        :raises ChatBusyError: If the last message is still being answered.
        :raises ChatClosedError: If the conversation was closed.
        :raises ValueError: If there is no message and no file, or a file was not attached, or there is no
            message to replace, or the last one was sent before messages could be replaced, or the command is not
            one, or cannot be given in this conversation, or needs something written with it.
        :return: How the turn ended. A turn that failed is reported in the reply, and told of as an
            event, rather than raised.
        """
        text, files = self._begin(message, attachments, replace_last, directive, lab)

        return self._run_turn(text, files)

    def start(
        self,
        message: str,
        attachments: Iterable[Attachment | str] = (),
        replace_last: bool = False,
        directive: str | None = None,
        lab: LabRequest | Mapping[str, Any] | None = None,
    ) -> threading.Thread:
        """Sends the lead a message as send does, but answers in a thread of its own, followed through
        the events, and the last_reply once it has ended. The message is told of before this returns.

        :raises ChatBusyError: If the last message is still being answered.
        :raises ChatClosedError: If the conversation was closed.
        :raises ValueError: As send says.
        :return: The thread, started.
        """
        text, files = self._begin(message, attachments, replace_last, directive, lab)

        thread = threading.Thread(
            target=self._run_turn, args=(text, files), name=f"virtual-lab-chat-{self.id}", daemon=True
        )
        self._thread = thread
        try:
            thread.start()
        except BaseException:
            self._end_turn()
            raise

        return thread

    def check_lab(self, message: str, lab: LabRequest | Mapping[str, Any], joining: Sequence[str] = ()) -> None:
        """Checks that /lab can be given with this message, as send and start would, without taking the conversation
        for a turn, so that a team is not changed for a command that is then refused.

        :param joining: The titles of the scientists who are to be put on the team first, and so are taken to be on it.
        :raises ValueError: If /lab cannot be given: it is not valid, needs something written with it, or the scientists
            it names cannot work on it.
        """
        directive = directive_named("lab")
        request = self._lab_request(directive, lab)
        if not message.strip():
            raise ValueError("/lab needs what it is for written after it")
        if (why := self._why_not(directive, None, request, joining)) is not None:
            raise ValueError(f"/lab cannot be given: {why}")

    def _begin(
        self,
        message: str,
        attachments: Iterable[Attachment | str],
        replace_last: bool = False,
        directive: str | None = None,
        lab: LabRequest | Mapping[str, Any] | None = None,
    ) -> tuple[str, list[Attachment]]:
        """Takes the conversation for a turn, and tells of the message that begins it."""
        chosen = directive_named(directive) if directive is not None else None
        request = self._lab_request(chosen, lab)
        text = message.strip()
        files = self._attachments(attachments)
        if chosen is not None and chosen.needs_text and not text:
            raise ValueError(f"/{chosen.name} needs what it is for written after it")
        if not text and not files and (chosen is None or chosen.needs_text):
            raise ValueError("A message needs something in it: some text or a file")

        with self._changed:
            if self._closed:
                raise ChatClosedError("This conversation was closed")
            if self._state != "idle":
                raise ChatBusyError("The lead is still answering the last message")
            if replace_last:
                withdrawn = self._withdraw_last_turn(chosen, request)
            else:
                withdrawn = None
                self._check_directive(chosen, self._messages, request)
            self._turn += 1
            sent_after = len(self._messages)
            self._paused = False
            self._stopping = False
            self._notes = []
            self._delegations = 0
            self._directive = chosen
            self._lab = request
            self._called = set()
            self._reviewed = False
            told = self._change_state("running")
            self._save_info()
        self._tell_state(told)

        try:
            if withdrawn is not None:
                self._emit("withdrawn", turn=withdrawn)
            self._emit(
                "user",
                speaker=HUMAN_SPEAKER,
                text=text,
                attachments=[file.to_dict() for file in files],
                messages_before=sent_after,
                **({"directive": chosen.name} if chosen is not None else {}),
                **({"lab": request.to_dict()} if request is not None else {}),
            )
            if not self.title:
                self.rename(title_of(text, files))
        except BaseException:
            self._end_turn()
            raise

        return text, files

    def _withdraw_last_turn(self, directive: Directive | None = None, lab: LabRequest | None = None) -> int:
        """Takes the last message, and all that came of it, out of the conversation and its saved files, with
        self._changed held, so that the turn can begin again.

        :param directive: The command the turn is to begin again with, and with /lab who is to work on it, which are
            checked against what the conversation will have been left with, before anything is changed.
        :raises ValueError: If there is no message, or it was saved without where the conversation was cut back to, or
            the command cannot be given to what is left.
        :return: The turn it began.
        """
        at = next((i for i in range(len(self._events) - 1, -1, -1) if self._events[i].kind == "user"), None)
        if at is None:
            raise ValueError("There is no message to replace")
        first = self._events[at]
        before = first.data.get("messages_before")
        if not is_count(before) or before > len(self._messages):
            raise ValueError("The last message was sent before messages could be replaced, and cannot be")

        events = self._events[:at]
        messages = self._messages[:before]
        self._check_directive(directive, messages, lab)
        # Written before anything is changed, so that a file that cannot be written leaves the conversation as it was
        write_atomically(
            self.save_dir / CHAT_EVENTS_FILE_NAME,
            "".join(json_line(event.to_dict()) for event in events).encode("utf-8"),
        )
        write_atomically(
            self.save_dir / CHAT_MESSAGES_FILE_NAME, "".join(json_line(message) for message in messages).encode("utf-8")
        )

        # A title that came from this message is not one for what replaces it
        files = [
            Attachment(str(file.get("name", "")), "", 0)
            for file in first.data.get("attachments") or []
            if isinstance(file, dict)
        ]
        if self.title == title_of(first.text, files) and not any(event.kind == "user" for event in events):
            self.title = ""
        self._events = events
        self._messages = messages
        self._turn = first.turn - 1
        self._live.clear()

        return first.turn

    def _end_turn(self) -> None:
        with self._changed:
            self._paused = False
            self._stopping = False
            self._notes = []
            told = self._change_state("idle")
            self._save_info()
        self._tell_state(told)

    def _run_turn(self, text: str, files: list[Attachment]) -> ChatReply:
        try:
            reply, crash = self._answer(text, files)
        finally:
            # Whatever went wrong, the conversation is given back, so that it is not left running for good
            self._end_turn()
        if crash is not None:
            raise crash

        return reply

    def _answer(self, text: str, files: list[Attachment]) -> tuple[ChatReply, BaseException | None]:
        started = time.monotonic()
        status: ChatStatus = "answered"
        answer = ""
        carried_out: bool | None = None
        failure: Failure | None = None
        crash: BaseException | None = None

        try:
            self._prepare()
            self._cells_before = len(self.session.history) if self.session is not None else 0
            self._append({"role": "user", "content": self._what_was_sent(text, files)})
            answer = self._converse()
            carried_out = self._carried_out()
        except ChatStopped:
            status = "stopped"
            self._close_open_calls("Not run: the researcher stopped the turn.")
            self._append({"role": "assistant", "name": self.lead.name, "content": STOPPED_REPLY})
        except BaseException as caught:
            status = "failed"
            failure = describe_failure(caught)
            self._close_open_calls(f"Not run: {failure.detail}")
            if not isinstance(caught, Exception):
                crash = caught

        with self._changed:
            unread, self._notes = self._notes, []
            usage = self._usage_data()
        for note in unread:
            self._emit_ending("note", note, to=None, read=False)

        elapsed = round(time.monotonic() - started, 3)
        reply = ChatReply(
            status=status, text=answer, error=failure.text if failure else None, usage=usage, elapsed_time=elapsed
        )
        self.last_reply = reply
        if status == "answered":
            self._emit_ending(
                "answer",
                answer,
                usage=usage,
                elapsed_time=elapsed,
                **({} if carried_out is None else {"directive_met": carried_out}),
            )
        elif status == "stopped":
            self._emit_ending("stopped", "Stopped by you. What was done is kept.", elapsed_time=elapsed)
        else:
            assert failure is not None
            self._emit_ending("failed", failure.text, type=failure.type, elapsed_time=elapsed)

        return reply, crash

    def _what_was_sent(self, text: str, files: list[Attachment]) -> str:
        parts = [text] if text else []
        if files:
            parts.append(
                chat_attachments_prompt(
                    [(file.path, describe_size(file.size)) for file in files],
                    can_open=self.session is not None,
                    can_inspect=any(tool.name == INSPECT_FILE_TOOL_NAME for tool in self.tools),
                )
            )
        if self._directive is not None:
            parts.append(self._directive.prompt_for(self._lab))

        return "\n\n".join(parts)

    # Commands

    def _lab_request(
        self, directive: Directive | None, lab: LabRequest | Mapping[str, Any] | None
    ) -> LabRequest | None:
        """Who a message is to be worked on by, which only /lab says, and which it must.

        :raises ValueError: If /lab does not say, another command or none does, or what it says is not valid.
        """
        if directive is None or directive.name != "lab":
            if lab is not None:
                raise ValueError("Who works on a message is chosen only with /lab")
            return None
        if lab is None:
            raise ValueError("/lab needs who is to work on it chosen")

        return lab if isinstance(lab, LabRequest) else LabRequest.from_data(lab)

    def _why_not(
        self,
        directive: Directive,
        messages: Sequence[dict[str, Any]] | None = None,
        lab: LabRequest | None = None,
        joining: Sequence[str] = (),
    ) -> str | None:
        """Why a command cannot be given, in words, or None if it can.

        :param messages: What the lead has been sent and has said, for the commands that need an answer to have been
            given. Without them, those are not checked for it.
        :param lab: Who /lab names, which is checked against the team. Without it, only whether the lead may start team
            sessions is.
        :param joining: The titles of scientists who are to be put on the team before the command is given, and so are
            taken to be on it.
        """
        match directive.name:
            case "code" | "plot":
                if self.session is None:
                    return "nothing can run code in this conversation"
            case "search":
                searchable = any(is_literature_tool(tool.name) for tool in self.tools)
                # The tools of the servers that are connected to with the first message are not known until then
                if not searchable and (self._late_tools is None or self._late_tools_added):
                    return "no literature tool is turned on for this conversation"
            case "review":
                if self._critic is None:
                    return f"the {SCIENTIFIC_CRITIC.title} is not on the team"
                if self.max_delegations == 0:
                    return "the lead may not start team sessions"
                if not self._consultants:
                    return f"the lead starts no team sessions when the {SCIENTIFIC_CRITIC.title} is the whole team"
                if messages is not None and not any(
                    message.get("role") == "assistant"
                    and not message.get("tool_calls")
                    and str(message.get("content") or "").strip() not in ("", STOPPED_REPLY)
                    for message in messages
                ):
                    return "there is no answer to review yet"
            case "lab":
                if self.max_delegations == 0:
                    return "the lead may not start team sessions"
                if lab is not None:
                    return self._why_not_lab(lab, joining)

        return None

    def _why_not_lab(self, lab: LabRequest, joining: Sequence[str] = ()) -> str | None:
        """Why the scientists a /lab names cannot work on a message, or None if they can."""
        coming = {normalize_title(title) for title in joining}
        for title in lab.members:
            if normalize_title(title) == normalize_title(self.lead.title):
                return f"{self.lead.title} leads the session, so choose the others"
            if self._find_member(title) is None and normalize_title(title) not in coming:
                return f'"{title}" is not on the team'
        if lab.rounds > self.max_rounds:
            return f"a session may have at most {self.max_rounds} round{'s' if self.max_rounds != 1 else ''}"
        if lab.mode == "individual":
            if self._critic is None:
                return f"the {SCIENTIFIC_CRITIC.title} is not on the team to review"
            if self._find_member(lab.members[0]) is self._critic:
                return f"the {SCIENTIFIC_CRITIC.title} reviews, so choose another to work on it"

        return None

    def _check_directive(
        self, directive: Directive | None, messages: Sequence[dict[str, Any]], lab: LabRequest | None = None
    ) -> None:
        """Raises if a command cannot be given to a conversation that has these messages."""
        if directive is not None and (why := self._why_not(directive, messages, lab)) is not None:
            raise ValueError(f"/{directive.name} cannot be given: {why}")

    def _done(self, check: Check) -> bool:
        """Whether what a command checked for has happened in answering this message."""
        session = self.session
        match check:
            case "code":
                return session is not None and len(session.history) > self._cells_before
            case "plot":
                return session is not None and any(cell.plots for cell in session.history[self._cells_before :])
            case "literature":
                return any(is_literature_tool(name) for name in self._called)
            case "critic":
                return self._reviewed
            case "team":
                return self._delegations > 0

    def _carried_out(self) -> bool | None:
        """Whether the command of this message was carried out, or None if it has nothing that is checked."""
        directive = self._directive

        return None if directive is None or directive.check is None else self._done(directive.check)

    def _remind(self, reply: ModelReply) -> bool:
        """Tells the lead that it has not done what the command asked, if that is so, putting what it wrote as its
        say before.

        :return: Whether it was told.
        """
        directive = self._directive
        if directive is None or directive.reminder is None or self._carried_out() is not False:
            return False

        if reply.content.strip():
            self._append({"role": "assistant", "name": self.lead.name, "content": reply.content})
            self._emit("tool_calls", speaker=self.lead.title, text=reply.content, calls=[])
        self._append({"role": "user", "content": directive.reminder})

        return True

    # Getting ready

    def _prepare(self) -> None:
        """Starts the session, and works out what the lead is told of it and of Biomni's resources. Once, but for
        what the limits change, which is put together again when they have."""
        if self._system is not None:
            if self._reassemble:
                self._assemble()
            return

        session = self.session
        catalog: Resources | None = None
        not_found: list[str] = []
        if session is not None:
            # Before the first request, so that a session that cannot start, such as one whose image
            # was never built, fails the turn before anything is spent
            session.start()
            self._cells_told = len(session.history)
            if session.software:
                checked = check_installed(session, list(session.software), [], what="the software added to it")
                if checked is not None:
                    not_found = [name for name in session.software if name in checked[0]]
                    if not_found:
                        print(
                            f"Warning: the session does not have {', '.join(not_found)}: not as a Python "
                            "distribution or module, an R package, or a command. The lead is told of it "
                            "anyway, as not found."
                        )
            if isinstance(self.resources, Resources):
                catalog = self.resources
                if catalog.data_lake and catalog.data_lake_path is None:
                    catalog = replace(catalog, data_lake_path=session.data_lake_path())
            elif self.resources != "none":
                catalog = available_resources(session, commercial_mode=self.commercial_mode)

        self._add_late_tools()
        tools: list[Tool] = list(self.tools)
        parts: list[str] = []

        if session is not None:
            tools.append(session_tool(session))
            parts.append(
                chat_session_prompt(session.where_code_runs(), session.can_reach_network(), session.data_lake_path())
            )
            if own := own_resources_prompt(session, not_found):
                parts.append(own)

        retrieving = catalog is not None and self.resources == "retrieve" and not catalog.is_empty()
        if catalog is not None:
            self._emit(
                "resources",
                mode=self.resources if isinstance(self.resources, str) else "given",
                commercial_mode=self.commercial_mode,
                available=catalog.counts(),
                not_installed=catalog.not_installed,
                selected=Resources().names() if retrieving else catalog.names(),
                retrieval=None,
            )
            if retrieving:
                self._catalog = catalog
                tools.append(self._find_resources_tool())
                parts.append(chat_resources_prompt(catalog.counts()))
            elif listed := resources_prompt(catalog, "tool", retrieved=False):
                parts.append(listed)

        if instructions := tool_instructions_prompt((*self.tools, *(session.tools if session is not None else ()))):
            parts.append(instructions)

        self._fixed_tools = tuple(tools)
        self._fixed_parts = tuple(parts)
        self._assemble()

    def _assemble(self) -> None:
        """Puts together what the lead is told and given from what was worked out, and from who is on the team and how
        much they may be asked for, which are what the lead's limits change."""
        # Cleared before what it is for is read, so that a limit changed while this is done is put together again
        self._reassemble = False
        delegating = bool(self._consultants) and self.max_delegations > 0
        lab = lab_chat_prompt(self.lead, self.team if delegating else (), can_run_code=self.session is not None)
        delegation = self._delegation_tools() if delegating else ()
        self._lead_tools = (*self._fixed_tools, *delegation)
        self._system = "\n\n".join([lab, *self._fixed_parts])

    def _add_late_tools(self) -> None:
        """Asks for the tools that could not be had before the first message, and adds them to the lead's and the
        team's."""
        if self._late_tools is None or self._late_tools_added:
            return
        given = tuple(self._late_tools())
        if not_tools := [type(tool).__name__ for tool in given if not isinstance(tool, Tool)]:
            raise TypeError(f"A conversation's tools are Tools, not {', '.join(not_tools)}")
        if taken := sorted({tool.name for tool in given} & RESERVED_TOOL_NAMES):
            raise ValueError(f"A conversation has tools of its own named {', '.join(taken)}, so no other may be")
        names = [tool.name for tool in (*self.tools, *given)]
        if duplicated := sorted({name for name in names if names.count(name) > 1}):
            raise ValueError(f"Tool names must be unique, but {', '.join(duplicated)} is given more than once")
        self.tools = (*self.tools, *given)
        self.project.meeting_options["tools"] = self.tools
        self._late_tools_added = True

    # The lead's turn

    def _converse(self) -> str:
        """Asks the lead, and runs what it calls, until it answers."""
        assert self._system is not None
        withheld = self._directive is not None and self._directive.no_tools
        definitions = [] if withheld else [tool.definition for tool in self._turn_tools()]
        reminded = False

        for iteration in range(self.max_tool_iterations + 1):
            # The tools are withheld on the final attempt, to force an answer
            final = iteration == self.max_tool_iterations

            if note := self._gate("lead"):
                self._append({"role": "user", "content": chat_note_prompt(note)})

            request: list[ChatCompletionMessageParam] = [
                {"role": "system", "content": self._system},
                *self.messages,  # type: ignore[list-item]
            ]
            self._check_fits(request)
            self._check_budget()
            reply = self._ask(self.lead, request, definitions if definitions and not final else None)
            self._count(self.lead.model, reply)
            self._checkpoint()

            if reply.finish_reason == "length" and not reply.content.strip():
                raise TruncatedResponseError(
                    f"{self.lead.title} ran out of tokens before writing any of its answer. Allow more with "
                    "max_completion_tokens."
                )

            if not final and not reply.tool_calls and not reminded and self._remind(reply):
                reminded = True
                continue

            if final or not reply.tool_calls:
                if not reply.content.strip():
                    raise RuntimeError(f"{self.lead.title} sent no answer")
                if reply.finish_reason == "length":
                    print(f"Warning: {self.lead.title} ran out of tokens and its answer is cut short.")
                self._append({"role": "assistant", "name": self.lead.name, "content": reply.content})

                return reply.content

            self._append(
                {
                    "role": "assistant",
                    "name": self.lead.name,
                    "content": reply.content or None,
                    "tool_calls": [call.model_dump() for call in reply.tool_calls],
                }
            )
            self._emit(
                "tool_calls",
                speaker=self.lead.title,
                text=reply.content,
                calls=[describe_call(call) for call in reply.tool_calls],
            )
            self._run_calls(reply.tool_calls)

        raise AssertionError("The final attempt returns or raises")  # pragma: no cover

    def _run_calls(self, calls: Iterable[ToolCall]) -> None:
        """Runs the lead's tool calls one at a time, so that each is told of when it is done."""
        # The team's requests of this message, by what was asked, which is the id of the call that held it. A model
        # can send the same request twice in one message, and holding a meeting twice costs twice for nothing.
        held: dict[tuple[str, str], str] = {}
        for call in calls:
            self._checkpoint()
            asked = request_of(call) if call.function.name in (CONVENE_TOOL_NAME, CONSULT_TOOL_NAME) else None
            if asked is not None and asked in held:
                output = (
                    f"Not held again: this is the same request as {held[asked]}, in this message, which is answered "
                    "there."
                )
                self._append({"role": "tool", "tool_call_id": call.id, "content": output})
                self._emit("tool_output", text=output, call=call.id, name=call.function.name)
                continue
            if asked is not None:
                held[asked] = call.id
            self._called.add(call.function.name)
            self._call_id = call.id
            outputs, messages = run_tool_calls([call], self._turn_tools())  # type: ignore[arg-type]
            self._call_id = None
            self._append(dict(messages[0]))
            self._tell_cells(call.id, own=call.function.name not in (CONVENE_TOOL_NAME, CONSULT_TOOL_NAME))
            self._emit("tool_output", text=outputs[0], call=call.id, name=call.function.name)

    def _tell_cells(self, call_id: str, own: bool) -> None:
        """Tells of the code the session has run since it was last told, by the call that ran it. A
        team's code is told of by the events of its meeting."""
        session = self.session
        if session is None:
            return
        cells = session.history[self._cells_told :]
        self._cells_told = len(session.history)
        if own:
            for cell in cells:
                plot_paths = [str(session.directory / plot) for plot in cell.plots]
                self._emit("cell", **cell.to_dict(), plot_paths=plot_paths, call=call_id)

    def _ask(
        self,
        agent: Agent,
        messages: list[ChatCompletionMessageParam],
        tools: list[Any] | None,
        speaking: bool = True,
    ) -> ModelReply:
        """Asks an agent for its next message, without a temperature if its model refuses one.

        :param speaking: Whether the reply is the agent's say, which is streamed to those following the
            conversation, rather than a request made for the conversation's sake.
        """
        on_text = None
        if self.stream and speaking:
            request = next(self._requests)

            def on_text(text: str) -> None:
                self._emit("writing", speaker=agent.title, text=text, request=request, model=agent.model)
                self._checkpoint()

        return send_request(
            lambda temperature: ask(
                self._llms[agent.model],
                messages,
                temperature=temperature,
                tools=tools or None,
                max_tokens=self.max_completion_tokens,
                reader=agent.name,
                on_text=on_text,
                interrupt=self._checkpoint,
            ),
            model=agent.model,
            temperature=self.temperature,
        )

    def _count(self, model: str, reply: ModelReply) -> None:
        """Adds a response's usage to the lead's, and tells of the conversation's."""
        with self._changed:
            self._usage.add(model=model, usage=reply.usage)
            self._save_info()
        self._tell_usage()

    def _check_budget(self) -> None:
        """Stops the turn before a request that the conversation has no money left for."""
        if self.max_cost is None:
            return

        spent = self.usage.compute_cost()
        if spent >= self.max_cost:
            raise BudgetExceededError(spent=spent, limit=self.max_cost, what="conversation")

    def _check_fits(self, messages: list[ChatCompletionMessageParam]) -> None:
        try:
            check_context_length(messages=messages, model=self.lead.model)
        except ContextLengthExceededError as error:
            raise ContextLengthExceededError(
                f"This conversation has grown to about {count_message_tokens(messages):,} tokens, more than the "
                f'{get_max_input_tokens(self.lead.model):,} that "{self.lead.model}" can read. Start a new '
                "conversation, and say in its first message what you need from this one."
            ) from error

    # Steering

    def _checkpoint(self) -> None:
        """Ends the turn here if the researcher stopped it."""
        with self._changed:
            if self._stopping:
                raise ChatStopped()

    def _gate(self, to: Literal["lead", "lab"]) -> str | None:
        """Holds the turn while it is paused, ends it if it was stopped, and gives back the notes the
        researcher added, which whoever goes on reads first.

        :param to: Who is about to read them.
        """
        while True:
            with self._changed:
                if self._stopping:
                    raise ChatStopped()
                if not self._paused:
                    notes, self._notes = self._notes, []
                    break
                told = self._change_state("paused") if self._state == "pausing" else None
                if told is None:
                    self._changed.wait()
            self._tell_state(told)

        for note in notes:
            self._emit("note", speaker=HUMAN_SPEAKER, text=note, to=to, read=True)

        return "\n\n".join(notes) or None

    def _close_open_calls(self, reason: str) -> None:
        """Answers the lead's tool calls that were never run, so that what it is sent next is valid."""
        with self._changed:
            index = next(
                (i for i in range(len(self._messages) - 1, -1, -1) if self._messages[i]["role"] == "assistant"), None
            )
            if index is None or not self._messages[index].get("tool_calls"):
                return
            answered = {message["tool_call_id"] for message in self._messages[index + 1 :] if message["role"] == "tool"}
            open_calls = [call for call in self._messages[index]["tool_calls"] if call["id"] not in answered]

        for call in open_calls:
            self._append({"role": "tool", "tool_call_id": call["id"], "content": reason})
            self._emit_ending("tool_output", reason, call=call["id"], name=call["function"]["name"])

    # Resources

    def _find_resources_tool(self) -> Tool:
        return Tool(
            name=FIND_RESOURCES_TOOL_NAME,
            description=(
                "Find which of Biomni's tool functions, data lake files, software libraries, and know-how "
                "documents in the session's environment suit a task, and see how to use them. Call it before "
                "you write code for a task that may use them, and describe the task in a sentence or two, "
                "saying what is to be found out and from what. It does not run anything."
            ),
            parameters={
                "type": "object",
                "properties": {"task": {"type": "string", "description": "The task, in a sentence or two."}},
                "required": ["task"],
            },
            function=self._find_resources,
        )

    def _find_resources(self, task: str) -> str:
        assert self._catalog is not None
        messages: list[ChatCompletionMessageParam] = [
            {"role": "user", "content": retrieval_prompt(task, self._catalog)}
        ]
        check_context_length(messages=messages, model=self.lead.model)
        self._check_budget()
        reply = self._ask(self.lead, messages, None, speaking=False)
        self._count(self.lead.model, reply)

        chosen = parse_retrieval(reply.content)
        if chosen is None:
            return (
                "Which resources suit that task could not be worked out, since the answer named none of the "
                "kinds. Describe the task more specifically and ask again."
            )

        selected = select_resources(self._catalog, chosen)
        self._emit(
            "resources",
            mode="retrieve",
            commercial_mode=self.commercial_mode,
            available=self._catalog.counts(),
            not_installed=self._catalog.not_installed,
            selected=selected.names(),
            retrieval={"task": task, "model": self.lead.model, "reply": reply.content},
        )

        return resources_prompt(selected, "tool", retrieved=True) or "None of the resources suit that task."

    # The team

    def _delegation_tools(self) -> tuple[Tool, ...]:
        titles = [agent.title for agent in self.team]
        consultants = [agent.title for agent in self._consultants]
        rounds = {
            "type": "integer",
            "minimum": 0,
            "maximum": self.max_rounds,
            "description": (
                "Rounds of discussion before the summary. 0 is one answer with no discussion. Defaults to 1; "
                f"at most {self.max_rounds}."
            ),
        }
        questions = {
            "type": "array",
            "items": {"type": "string"},
            "description": "Questions the team must answer by the end, if there are particular ones.",
        }
        warning = (
            "The team cannot see this conversation, so the agenda must have everything the work needs. "
            "A session costs many requests: use it when it will change the answer."
        )

        return (
            Tool(
                name=CONVENE_TOOL_NAME,
                description=(
                    "Have several scientists of your team discuss something, with you leading, and be given the "
                    "summary you reach. Use it when a question needs more than one kind of expertise, or "
                    "someone to push back on a plan. Include the Scientific Critic when the answer needs "
                    f"checking. {warning}"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "agenda": {
                            "type": "string",
                            "description": "What the team is to work on: the goal, the files and data, what has "
                            "been tried, and what you want back.",
                        },
                        "members": {
                            "type": "array",
                            "items": {"type": "string", "enum": titles},
                            "description": "Who takes part, by title, besides you.",
                        },
                        "questions": questions,
                        "rounds": rounds,
                    },
                    "required": ["agenda", "members"],
                },
                function=self._convene_team,
            ),
            Tool(
                name=CONSULT_TOOL_NAME,
                description=(
                    "Have one scientist of your team work on a focused task, with the Scientific Critic "
                    f"reviewing it, and be given the answer. {warning}"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "member": {"type": "string", "enum": consultants, "description": "Who, by title."},
                        "agenda": {
                            "type": "string",
                            "description": "The task: the goal, the files and data, what has been tried, and "
                            "what you want back.",
                        },
                        "questions": questions,
                        "rounds": rounds,
                    },
                    "required": ["member", "agenda"],
                },
                function=self._consult,
            ),
        )

    def _turn_tools(self) -> tuple[Tool, ...]:
        """The tools the lead is given for the message it is answering: its own, but for a message given with /lab, the
        team's are replaced by the one the researcher has set up."""
        lab = self._lab
        if lab is None:
            return self._lead_tools

        others = (tool for tool in self._lead_tools if tool.name not in (CONVENE_TOOL_NAME, CONSULT_TOOL_NAME))

        return (*others, self._lab_tool(lab))

    def _lab_tool(self, lab: LabRequest) -> Tool:
        """The tool that brings together who the researcher chose, with them and the rounds as they chose, so that the
        lead is left to write the agenda, and to add questions of its own."""

        # What else the lead gives, such as members it was told of before, is not taken, since they are set
        def hold(agenda: str, questions: list[str] | None = None, **_set: Any) -> str:
            own = [str(question) for question in questions] if isinstance(questions, list) else []
            asked = [*lab.questions, *(question for question in own if question not in lab.questions)]
            if lab.mode == "individual":
                return self._consult(lab.members[0], agenda, asked, lab.rounds)

            return self._convene_team(agenda, list(lab.members), asked, lab.rounds)

        individual = lab.mode == "individual"
        who = lab.members[0] if individual else ", ".join(lab.members)

        return Tool(
            name=CONSULT_TOOL_NAME if individual else CONVENE_TOOL_NAME,
            description=(
                f"Have {who} work on what the researcher asked for with /lab"
                + (", with the Scientific Critic reviewing it" if individual else ", with you leading")
                + ", and be given what comes of it. Who works on it and for how many rounds is set. "
                "The team cannot see this conversation, so the agenda must have everything the work needs."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agenda": {
                        "type": "string",
                        "description": "What they are to work on: the goal, the files and data, what has been "
                        "tried, and what you want back.",
                    },
                    "questions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Further questions they must answer by the end, besides the "
                        "researcher's own, which are asked already.",
                    },
                },
                "required": ["agenda"],
            },
            function=hold,
        )

    def _find_member(self, title: str) -> Agent | None:
        wanted = normalize_title(str(title))
        return next((agent for agent in self.team if normalize_title(agent.title) == wanted), None)

    def _convene_team(
        self, agenda: str, members: list[str], questions: list[str] | None = None, rounds: int = 1
    ) -> str:
        chosen: list[Agent] = []
        for title in members:
            if normalize_title(str(title)) == normalize_title(self.lead.title):
                return f"Not held: you lead the discussion, so name the others, from {self._roster()}."
            member = self._find_member(title)
            if member is None:
                return f'Not held: there is no "{title}" on your team. Your team is {self._roster()}.'
            if member not in chosen:
                chosen.append(member)
        if not chosen:
            return f"Not held: name at least one member of your team, from {self._roster()}."

        names = ", ".join(member.title for member in chosen)

        held = self._delegations
        report = self._hold(
            "team",
            agenda,
            questions,
            rounds,
            {"team_lead": self.lead, "team_members": tuple(chosen)},
            lambda result, rounds: (
                f"{names} took part in a discussion that you led, for {rounds} round{'s' if rounds != 1 else ''} "
                f"of discussion. The summary you reached with them:\n\n{result.summary}"
            ),
        )
        if self._critic in chosen and self._delegations > held:
            self._reviewed = True

        return report

    def _consult(self, member: str, agenda: str, questions: list[str] | None = None, rounds: int = 1) -> str:
        found = self._find_member(member)
        if found is None or found is self._critic:
            return (
                f'Not held: "{member}" cannot be consulted. Consult one of '
                f"{', '.join(agent.title for agent in self._consultants)}."
            )

        options: dict[str, Any] = {"team_member": found}
        reviewer = self._critic.title if self._critic is not None else SCIENTIFIC_CRITIC.title
        if self._critic is not None:
            options["critic"] = self._critic

        return self._hold(
            "individual",
            agenda,
            questions,
            rounds,
            options,
            lambda result, rounds: (
                f"{found.title} worked on it, with the {reviewer} reviewing, for {rounds} round"
                f"{'s' if rounds != 1 else ''} of review. Their answer:\n\n{result.summary}"
            ),
        )

    def _roster(self) -> str:
        return ", ".join(agent.title for agent in self.team)

    def _hold(
        self,
        meeting_type: Literal["team", "individual"],
        agenda: str,
        questions: list[str] | None,
        rounds: int,
        who: dict[str, Any],
        report: Callable[[MeetingResult, int], str],
    ) -> str:
        """Holds a meeting for the lead, as a project would, and writes what it found as the lead reads it."""
        if not str(agenda).strip():
            return "Not held: the agenda is empty. Say what the team is to work on."
        if self._delegations >= self.max_delegations:
            return (
                f"Not held: the team has already worked {self._delegations} time"
                f"{'s' if self._delegations != 1 else ''} on this message, which is the most allowed. Answer with "
                "what you have, and say what is left, or ask the researcher to carry on."
            )

        rounds = max(0, min(int(rounds), self.max_rounds))
        with self._changed:
            self._delegations += 1
            self._lab_calls += 1
            name = f"lab_{self._lab_calls:03d}"
            self._save_info()

        call = self._call_id
        read_by_team: list[str] = []

        def on_event(event: MeetingEvent) -> None:
            self._pass_on(call, event)

        def steer(turn: NextTurn) -> str | None:
            note = self._gate("lab")
            if note:
                read_by_team.append(note)

            return note

        try:
            result = self.project.meeting(
                meeting_type,
                str(agenda),
                name=name,
                agenda_questions=tuple(str(question) for question in questions or ()),
                num_rounds=rounds,
                on_event=on_event,
                steer=steer,
                interrupt=self._checkpoint,
                on_usage=lambda usage: self._tell_usage(),
                before_request=self._check_budget,
                **who,
            )
        except ChatStopped:
            return "The researcher stopped the team before it finished, so there is no summary."

        text = report(result, rounds)
        if read_by_team:
            text += "\n\nWhile the team worked, the researcher told it:\n\n" + "\n\n".join(read_by_team)

        return text

    def _pass_on(self, call: str | None, event: MeetingEvent) -> None:
        """Tells of an event of a team session as the conversation's, and ends it if the researcher stopped it."""
        if event.kind in UNTOLD_LAB_EVENTS or (event.kind == "message" and event.data.get("kind") == "prompt"):
            return

        if event.kind == "writing":
            self._emit(
                "writing", speaker=event.speaker, text=event.text, **event.data, meeting=event.meeting, call=call
            )
        else:
            self._emit(
                "lab",
                speaker=event.speaker,
                text=event.text,
                call=call,
                event=event.kind,
                meeting=event.meeting,
                round=event.round,
                details=dict(event.data),
            )

        if event.kind in STOPPABLE_LAB_EVENTS:
            self._checkpoint()
