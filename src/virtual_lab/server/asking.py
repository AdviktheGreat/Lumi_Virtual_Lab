"""Asking the researcher, in the conversation, what a tool or a server waits to be told: whether a call that costs
money or cannot be undone may be made, and what an MCP server asks while one of its tools runs.

Each is told of in the conversation as an event that waits, and the call or the server waits with it until the page
answers, the turn is stopped, the conversation is closed, or too long has passed. Nothing is done that no one agreed
to, so anything but a yes is a no.
"""

import math
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from virtual_lab.approval import (
    ApprovalDeclined,
    ApprovalRequest,
    ServerQuestion,
    choices,
    field_kind,
    first_paragraph,
    shown_arguments,
)
from virtual_lab.server.errors import ApiError

# Seconds a request waits for the researcher before it is withdrawn, so that a turn is not held for good by someone
# who has gone away
ANSWER_TIMEOUT = 3600.0

# The most characters of an answer to one field, which no one types by hand
MAX_ANSWER_CHARS = 20_000

# The most items an answer to a field of several may have
MAX_ANSWER_ITEMS = 1_000

# How a request ended, as the conversation's events say it
APPROVED, DECLINED, ANSWERED, WITHDRAWN = "approved", "declined", "answered", "withdrawn"

# Tells the conversation of an event, as Chat.tell does
Tell = Callable[..., Any]


@dataclass
class Pending:
    """A request that waits for the researcher.

    :param id: What the page answers it by.
    :param kind: "approval" or "question".
    :param server: The name of the server it is of, and what to call it, which each of its events carries, so that
        however it ends is told as being of the same server.
    :param question: What is asked, for a question.
    """

    id: str
    kind: str
    server: dict[str, str]
    question: ServerQuestion | None = None
    done: threading.Event = field(default_factory=threading.Event)
    state: str = "waiting"
    value: Any = None


def not_waiting(request_id: str) -> ApiError:
    """What a page is told when it answers what nothing waits for, as when it was answered already, or the turn
    stopped waiting for it."""
    return ApiError(
        409,
        "not_waiting",
        f"Nothing waits for an answer under {request_id}: it was answered already, or the turn stopped waiting for it",
    )


def check_value(name: str, schema: Mapping[str, Any], value: Any) -> Any:
    """A field's answer, if it is what the field takes.

    Only what a person could get wrong in a form is checked, which is the kind and the choices: a server that wants
    more, such as a length, says so itself, and the lead is told so as the result.

    :raises ValueError: If it is not.
    """
    kind = field_kind(schema)
    label = str(schema.get("title") or name)
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{label} is yes or no")
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{label} is a whole number")
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
            raise ValueError(f"{label} is a number")
    elif kind == "choice":
        options = choices(schema) or []
        # Of the same type as well, so that 1 is not taken for True
        if not any(type(value) is type(option) and value == option for option in options):
            raise ValueError(f"{label} is one of {', '.join(str(option) for option in options)}")
    elif kind == "array":
        if not isinstance(value, list) or len(value) > MAX_ANSWER_ITEMS:
            raise ValueError(f"{label} is a list")
        items = schema.get("items")
        for item in value:
            check_value(name, items if isinstance(items, Mapping) else {}, item)
    elif not isinstance(value, str) or len(value) > MAX_ANSWER_CHARS:
        raise ValueError(f"{label} is text of at most {MAX_ANSWER_CHARS:,} characters")

    return value


def check_answer(question: ServerQuestion, answer: Any) -> dict[str, Any]:
    """An answer to a question, if it is one: each field it fills in is one the form has and takes what it was given,
    and every field that is required is filled in.

    :raises ValueError: If it is not, saying what is wrong, so that the form can be put right.
    """
    if not isinstance(answer, dict):
        raise ValueError("An answer is the form's fields, by name")
    if question.url is not None:
        if answer:
            raise ValueError("A question answered at a web page takes no fields")
        return {}
    if unknown := sorted(str(name) for name in set(answer) - set(question.fields)):
        fields = ", ".join(question.fields) or "none"
        raise ValueError(f"There is no field {', '.join(unknown)}: the fields are {fields}")
    if missing := [name for name in question.required if name not in answer]:
        raise ValueError(f"{', '.join(missing)} must be filled in")

    return {name: check_value(name, question.fields[name], value) for name, value in answer.items()}


def is_web_address(url: Any) -> bool:
    """Whether a page may be sent to the address, which only a web page may: anything else, such as javascript:, is
    one a link must not follow."""
    if not isinstance(url, str):
        return False
    parts = urlsplit(url)

    return parts.scheme in ("http", "https") and bool(parts.netloc)


class Asker:
    """What a conversation asks the researcher, and waits for the answer of.

    :param tell: Tells the conversation of an event, as Chat.tell does.
    :param stopping: Whether the turn is being stopped, so that nothing new is waited for.
    :param title: What to call an MCP server, by its name.
    :param timeout: Seconds a request waits before it is withdrawn.
    """

    def __init__(
        self, tell: Tell, stopping: Callable[[], bool], title: Callable[[str], str], timeout: float = ANSWER_TIMEOUT
    ) -> None:
        self._tell = tell
        self._stopping = stopping
        self._title = title
        self._timeout = timeout
        self._lock = threading.Lock()
        self._pending: dict[str, Pending] = {}
        self._closed = False

    def approve(self, request: ApprovalRequest) -> bool:
        """Asks whether a call may be made, and waits. This is what an MCP connection is given to approve with.

        :raises ApprovalDeclined: If it was not asked, because the turn was ending or the conversation closed, or it
            was not answered in time, or the turn ended while it waited.
        :return: Whether it may.
        """
        server = {"server": request.server, "title": self._title(request.server)}
        pending = self._open("approval", server)
        if pending is None:
            raise ApprovalDeclined(
                f"The turn was ending before a person approved the call to {request.tool}, so it was not made."
            )
        self._tell(
            "approval",
            request=pending.id,
            state="waiting",
            tool=request.tool,
            description=first_paragraph(request.description),
            arguments=shown_arguments(request.arguments),
            **server,
        )
        if not self._wait(pending):
            raise ApprovalDeclined(
                f"No one approved the call to {request.tool} within {self._timeout:g} seconds, so it was not made."
            )
        if pending.state == WITHDRAWN:
            raise ApprovalDeclined(
                f"The turn ended before a person approved the call to {request.tool}, so it was not made."
            )

        return pending.state == APPROVED

    def answer(self, question: ServerQuestion) -> dict[str, Any] | None:
        """Asks what a server asks, and waits. This is what an MCP connection is given to answer with.

        :return: The form's fields, by name, or {} for a question answered at a web page once the researcher has been
            to it; or None if they declined it, it could not be asked, or it was not answered in time.
        """
        server = {"server": question.server, "title": self._title(question.server)}
        if question.url is not None and not is_web_address(question.url):
            # Not offered as a link, which a page could not follow safely, and not asked
            self._tell(
                "question",
                f"{question.message.strip()}\n\nIt was declined without asking, since it points to {question.url!r}, "
                "which is not a web address.",
                request=uuid.uuid4().hex[:12],
                state=DECLINED,
                **server,
            )
            return None
        pending = self._open("question", server, question)
        if pending is None:
            return None
        self._tell(
            "question",
            question.message.strip(),
            request=pending.id,
            state="waiting",
            fields=question.fields,
            required=list(question.required),
            url=question.url,
            **server,
        )
        if not self._wait(pending):
            return None

        return pending.value if pending.state == ANSWERED else None

    def approval(self, request_id: str, allow: bool) -> str:
        """Settles a call that waits for approval, as the researcher answered.

        :raises ApiError: If no call waits under this id, as when it was answered already.
        :return: How it ended.
        """
        pending = self._get(request_id, "approval")
        state = APPROVED if allow else DECLINED
        if not self._settle(pending, state, allow):
            raise not_waiting(request_id)

        return state

    def reply(self, request_id: str, answer: Any) -> str:
        """Settles a question, as the researcher answered it.

        :param answer: The form's fields, by name, or {} for a question answered at a web page; None to decline.
        :raises ApiError: If no question waits under this id, as when it was answered already, or the answer is not
            one the form takes, in which case it goes on waiting.
        :return: How it ended.
        """
        pending = self._get(request_id, "question")
        assert pending.question is not None
        if answer is None:
            state, value = DECLINED, None
        else:
            try:
                state, value = ANSWERED, check_answer(pending.question, answer)
            except ValueError as error:
                raise ApiError(422, "invalid", str(error)) from error
        if not self._settle(pending, state, value):
            raise not_waiting(request_id)

        return state

    def withdraw(self) -> None:
        """Ends everything that waits, as not answered, as the turn does when it is stopped."""
        with self._lock:
            waiting = list(self._pending.values())
        for pending in waiting:
            self._settle(pending, WITHDRAWN, None)

    def close(self) -> None:
        """Ends everything that waits and takes no more, as a conversation does when it is closed."""
        with self._lock:
            self._closed = True
        self.withdraw()

    def waiting(self) -> list[str]:
        """The ids of what waits, oldest first."""
        with self._lock:
            return list(self._pending)

    def _open(self, kind: str, server: dict[str, str], question: ServerQuestion | None = None) -> Pending | None:
        with self._lock:
            if self._closed or self._stopping():
                return None
            pending = Pending(id=uuid.uuid4().hex[:12], kind=kind, server=server, question=question)
            self._pending[pending.id] = pending

        return pending

    def _wait(self, pending: Pending) -> bool:
        """Waits for the request to end, and withdraws it if it does not in time. False if it ran out of time."""
        if pending.done.wait(self._timeout):
            return True

        # An answer that came as the time ran out has settled it already, and is not lost
        return not self._settle(pending, WITHDRAWN, None)

    def _get(self, request_id: str, kind: str) -> Pending:
        with self._lock:
            pending = self._pending.get(request_id)
        if pending is None or pending.kind != kind:
            raise not_waiting(request_id)

        return pending

    def _settle(self, pending: Pending, state: str, value: Any) -> bool:
        """Ends a request, once: the first to say how wins. False if it had ended."""
        with self._lock:
            if pending.state != "waiting":
                return False
            pending.state, pending.value = state, value
            self._pending.pop(pending.id, None)
        pending.done.set()
        self._tell(pending.kind, request=pending.id, state=state, **pending.server)

        return True
