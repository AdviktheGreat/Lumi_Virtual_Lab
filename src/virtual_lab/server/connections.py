"""A conversation's connections to its MCP servers, made when its first message is sent, and kept until it is closed.

Connecting to a server may take a download, or a sign-in in the browser, so it is not done when the conversation is
made. The lead is given the servers' tools as its first message begins, before anything is spent: each server is
connected to in a thread of its own, the conversation is told of how each is getting on, and the turn fails, saying
why, if one cannot be connected to. The servers that were connected to are kept, and only those that were not are
tried again with the next message.
"""

import threading
from collections.abc import Callable, Mapping
from typing import Any

from virtual_lab.chat import ChatStopped
from virtual_lab.constants import MCP_START_TIMEOUT
from virtual_lab.mcp_tools import MCPTools, connect_mcp
from virtual_lab.server.asking import Asker, Tell, is_web_address
from virtual_lab.server.mcp import server_title
from virtual_lab.tools import Tool

# Seconds between looks at whether the turn was stopped, while a server is being connected to
POLL_SECONDS = 0.2


class ServersNotConnectedError(RuntimeError):
    """Raised, to fail the turn that needs them, when servers could not be connected to."""


class Link:
    """One server of the conversation, and how far it has got.

    :param name: The server's name.
    :param entry: How to reach it, as a config gives it.
    :param title: What to call it.
    """

    def __init__(self, name: str, entry: Mapping[str, Any], title: str) -> None:
        self.name = name
        self.entry = dict(entry)
        self.title = title
        # "idle" until it is tried, then "connecting", and then "ready" or "failed"; a failed one is tried again
        self.state = "idle"
        self.opened: MCPTools | None = None
        self.error: str | None = None
        # Whether the conversation was told how it ended
        self.told = False


class Connections:
    """The servers a conversation was set up with, and the questions they and their tools ask.

    :param servers: The servers to connect to, by name, each as a config gives it.
    :param tell: Tells the conversation of an event, as Chat.tell does.
    :param stopping: Whether the turn is being stopped.
    :param asker: What the servers' approvals and questions are put to the researcher with.
    :param start_timeout: Seconds a server may take to start, or be connected to, besides any spent signing in.
    :param connect: What connects to a server, as connect_mcp does, which is for tests.
    """

    def __init__(
        self,
        servers: Mapping[str, Mapping[str, Any]],
        tell: Tell,
        stopping: Callable[[], bool],
        asker: Asker,
        start_timeout: float = MCP_START_TIMEOUT,
        connect: Callable[..., MCPTools] = connect_mcp,
    ) -> None:
        self._tell = tell
        self._stopping = stopping
        self.asker = asker
        self._start_timeout = start_timeout
        self._connect = connect
        self._changed = threading.Condition()
        self._closed = False
        self._links = {name: Link(name, entry, server_title(name, entry)) for name, entry in servers.items()}

    def tools(self) -> tuple[Tool, ...]:
        """The servers' tools, once every server is connected to, which the conversation is given before its first
        request.

        :raises ChatStopped: If the turn was stopped, or the conversation closed, while they were being connected to.
        :raises ServersNotConnectedError: If a server could not be connected to, after trying the rest.
        """
        waiting = self._begin()
        try:
            self._wait()
        except ChatStopped:
            # Those still being connected to go on in their threads, and are waited for by the next message
            for link in waiting:
                if link.state == "connecting":
                    self._announce(link, "failed", "Not connected: the turn ended before it was.")
            raise
        failed: list[Link] = []
        for link in self._links.values():
            if link.state == "failed":
                failed.append(link)
            if not link.told and link.state in ("ready", "failed"):
                link.told = True
                if link.state == "ready":
                    assert link.opened is not None
                    self._announce(link, "ready", tools=len(link.opened.tools))
                else:
                    self._announce(link, "failed", link.error or "")
        if failed:
            raise ServersNotConnectedError(
                "\n\n".join(f"{link.title} could not be connected to: {link.error}" for link in failed)
                + "\n\nThe turn did not begin, and nothing was spent. Put it right, or turn the server off in the "
                "settings, and send the message again."
            )

        return tuple(tool for link in self._links.values() if link.opened is not None for tool in link.opened.tools)

    def interrupt(self) -> None:
        """Ends what waits, so that a turn that is held by a connection or a question is let go, and takes no more
        questions, as a conversation does when it is closed. The servers are left open."""
        with self._changed:
            self._closed = True
            self._changed.notify_all()
        self.asker.close()

    def close(self) -> None:
        """Interrupts, and closes the servers, which stops those that were started here."""
        self.interrupt()
        with self._changed:
            opened = [link.opened for link in self._links.values() if link.opened is not None]
        for tools in opened:
            tools.close()

    def _begin(self) -> list[Link]:
        """Starts connecting to every server not yet connected to, and says so. The servers still being connected to
        from a turn that was stopped are waited for, not started again."""
        with self._changed:
            if self._closed:
                raise ChatStopped()
            waiting = [link for link in self._links.values() if link.state != "ready"]
            starting = [link for link in waiting if link.state != "connecting"]
            for link in waiting:
                link.state, link.error, link.told = "connecting", None, False
        for link in waiting:
            self._announce(link, "connecting")
        for link in starting:
            threading.Thread(target=self._open, args=(link,), name=f"virtual-lab-mcp-{link.name}", daemon=True).start()

        return waiting

    def _wait(self) -> None:
        with self._changed:
            while not all(link.state in ("ready", "failed") for link in self._links.values()):
                if self._closed or self._stopping():
                    raise ChatStopped()
                self._changed.wait(POLL_SECONDS)

    def _open(self, link: Link) -> None:
        """Connects to one server, in a thread of its own, and leaves what came of it for the turn to tell of."""
        opened: MCPTools | None = None
        error: str | None = None
        try:
            opened = self._connect(
                {"mcpServers": {link.name: link.entry}},
                start_timeout=self._start_timeout,
                approve=self.asker.approve,
                answer=self.asker.answer,
                on_sign_in=self._signing_in,
            )
        except Exception as caught:  # noqa: BLE001
            error = str(caught) or type(caught).__name__
        with self._changed:
            # Not kept for a conversation that was closed while it connected, which nothing would close it for
            discard = opened if self._closed else None
            if discard is None:
                link.opened, link.error = opened, error
                link.state = "ready" if opened is not None else "failed"
            self._changed.notify_all()
        if discard is not None:
            discard.close()

    def _signing_in(self, name: str, url: str) -> None:
        """Offers the researcher the sign-in page of a server, which is opened in their browser as well."""
        link = self._links.get(name)
        if link is not None and is_web_address(url):
            self._announce(link, "signing_in", url=url)

    def _announce(self, link: Link, state: str, text: str = "", **data: Any) -> None:
        self._tell("connection", text, server=link.name, title=link.title, state=state, **data)
