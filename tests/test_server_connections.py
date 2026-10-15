"""Tests of a conversation's connections to its MCP servers: made when a turn begins, told of, and kept."""

import json
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from virtual_lab.approval import ApprovalDeclined, ApprovalRequest
from virtual_lab.chat import ChatStopped
from virtual_lab.server import connections as connections_module
from virtual_lab.server.asking import Asker
from virtual_lab.server.connections import Connections, ServersNotConnectedError
from virtual_lab.tools import Tool

SERVER = str(Path(__file__).with_name("mcp_test_server.py"))
WAIT = 15.0


@pytest.fixture(autouse=True)
def quick_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connections_module, "POLL_SECONDS", 0.02)


class Told:
    """What the conversation was told, which a test waits on."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.changed = threading.Condition()

    def __call__(self, kind: str, text: str = "", **data: Any) -> None:
        with self.changed:
            self.events.append((kind, text, data))
            self.changed.notify_all()

    def of(self, kind: str, server: str | None = None) -> list[dict[str, Any]]:
        with self.changed:
            return [
                {"text": text, **data}
                for found, text, data in self.events
                if found == kind and (server is None or data.get("server") == server)
            ]

    def states(self, server: str) -> list[str]:
        return [event["state"] for event in self.of("connection", server)]

    def wait_for(self, server: str, state: str) -> dict[str, Any]:
        with self.changed:
            assert self.changed.wait_for(lambda: state in self.states(server), WAIT), self.events
        return next(event for event in self.of("connection", server) if event["state"] == state)


class FakeTools:
    """What connect_mcp gives, without a server."""

    def __init__(self, *names: str) -> None:
        self.tools = tuple(Tool(name, name, {"type": "object", "properties": {}}, lambda: name) for name in names)
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class Then:
    """What a server does each time it is connected to, one after another, the last for every time after."""

    def __init__(self, *steps: Any) -> None:
        self.steps = list(steps)


class FakeConnect:
    """Stands in for connect_mcp: what it was asked for, and what each server does when it is.

    What a server does is the names of the tools it gives, an exception to raise, a function that is given its name and
    what connect_mcp was given and returns one of those, or Then of those.
    """

    def __init__(self, **servers: Any) -> None:
        self.servers = servers
        self.asked: list[dict[str, Any]] = []
        self.made: list[FakeTools] = []
        self.lock = threading.Lock()

    def __call__(self, config: dict[str, Any], **options: Any) -> FakeTools:
        (name,) = config["mcpServers"]
        with self.lock:
            self.asked.append({"name": name, "entry": config["mcpServers"][name], **options})
            what = self.servers[name]
            if isinstance(what, Then):
                what = what.steps.pop(0) if len(what.steps) > 1 else what.steps[0]
        if callable(what):
            what = what(name, options)
        if isinstance(what, BaseException):
            raise what
        tools = FakeTools(*what)
        with self.lock:
            self.made.append(tools)

        return tools

    def times(self, name: str) -> int:
        return sum(1 for asked in self.asked if asked["name"] == name)


def entry(name: str) -> dict[str, Any]:
    return {"url": f"https://{name}.example.org/mcp"}


def make(
    connect: Callable[..., Any],
    names: tuple[str, ...] = ("alpha", "beta"),
    stopping: Callable[[], bool] = lambda: False,
    told: Told | None = None,
    timeout: float = 30.0,
) -> tuple[Connections, Told]:
    told = told or Told()
    asker = Asker(told, stopping, lambda name: name.title(), 30.0)
    connections = Connections(
        {name: entry(name) for name in names}, told, stopping, asker, start_timeout=timeout, connect=connect
    )

    return connections, told


class TestConnecting:
    def test_there_is_nothing_to_connect_to_without_servers(self) -> None:
        connections, told = make(FakeConnect(), names=())

        assert connections.tools() == ()
        assert told.events == []

    def test_every_server_is_connected_to_and_its_tools_are_given_in_the_order_of_the_servers(self) -> None:
        connect = FakeConnect(alpha=("a_one", "a_two"), beta=("b_one",))
        connections, _ = make(connect)

        assert [tool.name for tool in connections.tools()] == ["a_one", "a_two", "b_one"]

    def test_each_server_is_connected_to_in_a_thread_of_its_own_so_that_a_slow_one_does_not_hold_up_the_rest(
        self,
    ) -> None:
        release = threading.Event()
        started: list[str] = []

        def slow(name: str, options: dict[str, Any]) -> tuple[str, ...]:
            started.append(name)
            assert release.wait(WAIT)

            return ("a_one",)

        connect = FakeConnect(alpha=slow, beta=slow)
        connections, told = make(connect)
        running = threading.Thread(target=connections.tools, daemon=True)
        running.start()
        try:
            deadline = time.monotonic() + WAIT
            while len(started) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert sorted(started) == ["alpha", "beta"]
        finally:
            release.set()
            running.join(WAIT)
        assert told.states("alpha") == ["connecting", "ready"]

    def test_it_is_told_of_each_server_connecting_and_ready_with_how_many_tools_it_gave(self) -> None:
        connections, told = make(FakeConnect(alpha=("a_one", "a_two"), beta=()))
        connections.tools()

        assert told.states("alpha") == ["connecting", "ready"]
        assert told.states("beta") == ["connecting", "ready"]
        ready = told.of("connection", "alpha")[1]
        assert ready["tools"] == 2
        assert ready["title"] == "alpha"
        assert told.of("connection", "beta")[1]["tools"] == 0

    def test_a_server_is_asked_for_with_its_entry_the_time_it_has_and_the_askers_of_the_conversation(self) -> None:
        connect = FakeConnect(alpha=("a_one",))
        connections, _ = make(connect, names=("alpha",), timeout=12.5)
        connections.tools()

        (asked,) = connect.asked
        assert asked["entry"] == entry("alpha")
        assert asked["start_timeout"] == 12.5
        assert asked["approve"] == connections.asker.approve
        assert asked["answer"] == connections.asker.answer
        assert callable(asked["on_sign_in"])

    def test_a_preset_is_told_of_by_its_title(self) -> None:
        told = Told()
        asker = Asker(told, lambda: False, lambda name: name, 30.0)
        connections = Connections(
            {"paperclip": {"preset": "paperclip"}}, told, lambda: False, asker, connect=FakeConnect(paperclip=("p",))
        )
        connections.tools()

        assert told.of("connection")[0]["title"] == "Paperclip"

    def test_the_servers_that_are_connected_to_are_kept_for_the_next_message_and_not_told_of_again(self) -> None:
        connect = FakeConnect(alpha=("a_one",), beta=("b_one",))
        connections, told = make(connect)
        first = connections.tools()

        assert connections.tools() == first
        assert (connect.times("alpha"), connect.times("beta")) == (1, 1)
        assert told.states("alpha") == ["connecting", "ready"]


class TestFailing:
    def test_a_server_that_cannot_be_connected_to_fails_the_turn_saying_which_and_why(self) -> None:
        connect = FakeConnect(alpha=("a_one",), beta=RuntimeError("beta is not reachable"))
        connections, _ = make(connect)

        with pytest.raises(ServersNotConnectedError) as raised:
            connections.tools()

        message = str(raised.value)
        assert "beta could not be connected to: beta is not reachable" in message
        assert "alpha" not in message
        assert "nothing was spent" in message

    def test_every_server_that_failed_is_named_and_the_others_are_still_tried(self) -> None:
        connect = FakeConnect(alpha=OSError("no network"), beta=ValueError("a bad entry"), gamma=("g",))
        connections, told = make(connect, names=("alpha", "beta", "gamma"))

        with pytest.raises(ServersNotConnectedError) as raised:
            connections.tools()

        assert "alpha could not be connected to: no network" in str(raised.value)
        assert "beta could not be connected to: a bad entry" in str(raised.value)
        assert told.states("gamma") == ["connecting", "ready"]
        assert told.of("connection", "alpha")[-1] == {
            "text": "no network",
            "server": "alpha",
            "title": "alpha",
            "state": "failed",
        }

    def test_an_error_with_no_message_is_told_by_its_kind(self) -> None:
        connections, told = make(FakeConnect(alpha=TimeoutError()), names=("alpha",))

        with pytest.raises(ServersNotConnectedError, match="alpha could not be connected to: TimeoutError"):
            connections.tools()
        assert told.of("connection", "alpha")[-1]["text"] == "TimeoutError"

    def test_only_the_server_that_failed_is_tried_again_with_the_next_message(self) -> None:
        connect = FakeConnect(alpha=("a_one",), beta=Then(RuntimeError("down"), ("b_one",)))
        connections, told = make(connect)
        with pytest.raises(ServersNotConnectedError):
            connections.tools()

        tools = connections.tools()

        assert [tool.name for tool in tools] == ["a_one", "b_one"]
        assert (connect.times("alpha"), connect.times("beta")) == (1, 2)
        assert told.states("beta") == ["connecting", "failed", "connecting", "ready"]
        assert told.states("alpha") == ["connecting", "ready"]

    def test_a_server_that_fails_again_fails_the_turn_again_and_is_told_of_again(self) -> None:
        connect = FakeConnect(alpha=RuntimeError("down"))
        connections, told = make(connect, names=("alpha",))

        for _ in range(2):
            with pytest.raises(ServersNotConnectedError):
                connections.tools()

        assert told.states("alpha") == ["connecting", "failed", "connecting", "failed"]


class TestStopping:
    def test_a_turn_stopped_while_a_server_connects_ends_and_tells_it_was_not_connected(self) -> None:
        release = threading.Event()
        stopped = threading.Event()
        connect = FakeConnect(alpha=lambda name, options: release.wait(WAIT) and ("a_one",))
        connections, told = make(connect, names=("alpha",), stopping=stopped.is_set)
        raised: list[BaseException] = []

        def run() -> None:
            try:
                connections.tools()
            except BaseException as error:  # noqa: BLE001
                raised.append(error)

        running = threading.Thread(target=run, daemon=True)
        running.start()
        try:
            told.wait_for("alpha", "connecting")
            stopped.set()
            running.join(WAIT)
            assert not running.is_alive()
            assert isinstance(raised[0], ChatStopped)
            assert told.states("alpha") == ["connecting", "failed"]
            assert "turn ended" in told.of("connection", "alpha")[-1]["text"]
        finally:
            release.set()
            connections.close()

    def test_the_next_message_waits_for_a_server_still_connecting_and_does_not_start_it_again(self) -> None:
        release = threading.Event()
        stopped = threading.Event()
        connect = FakeConnect(alpha=lambda name, options: release.wait(WAIT) and ("a_one",))
        connections, told = make(connect, names=("alpha",), stopping=stopped.is_set)
        stopped.set()
        with pytest.raises(ChatStopped):
            connections.tools()
        stopped.clear()
        release.set()

        tools = connections.tools()

        assert [tool.name for tool in tools] == ["a_one"]
        assert connect.times("alpha") == 1
        assert told.states("alpha") == ["connecting", "failed", "connecting", "ready"]

    def test_a_server_that_finished_after_its_turn_was_stopped_is_told_of_as_ready_by_the_next_message(self) -> None:
        release = threading.Event()
        stopped = threading.Event()
        connect = FakeConnect(alpha=lambda name, options: release.wait(WAIT) and ("a_one",))
        connections, told = make(connect, names=("alpha",), stopping=stopped.is_set)
        stopped.set()
        with pytest.raises(ChatStopped):
            connections.tools()
        release.set()
        deadline = time.monotonic() + WAIT
        while not connect.made and time.monotonic() < deadline:
            time.sleep(0.01)
        stopped.clear()

        connections.tools()

        assert told.states("alpha") == ["connecting", "failed", "ready"]
        assert connect.times("alpha") == 1

    def test_a_turn_begun_when_it_is_already_being_stopped_connects_to_nothing_it_waits_for(self) -> None:
        release = threading.Event()
        connect = FakeConnect(alpha=lambda name, options: release.wait(WAIT) and ("a_one",))
        connections, _ = make(connect, names=("alpha",), stopping=lambda: True)
        try:
            with pytest.raises(ChatStopped):
                connections.tools()
        finally:
            release.set()
            connections.close()


class TestClosing:
    def test_the_servers_that_were_connected_to_are_closed_with_the_conversation(self) -> None:
        connect = FakeConnect(alpha=("a_one",), beta=("b_one",))
        connections, _ = make(connect)
        connections.tools()

        connections.close()

        assert [tools.closed for tools in connect.made] == [1, 1]

    def test_a_conversation_closed_while_a_server_connects_ends_the_turn_and_closes_the_server_that_comes_late(
        self,
    ) -> None:
        release = threading.Event()
        connect = FakeConnect(alpha=lambda name, options: release.wait(WAIT) and ("a_one",))
        connections, told = make(connect, names=("alpha",))
        raised: list[BaseException] = []

        def run() -> None:
            try:
                connections.tools()
            except BaseException as error:  # noqa: BLE001
                raised.append(error)

        running = threading.Thread(target=run, daemon=True)
        running.start()
        told.wait_for("alpha", "connecting")

        connections.close()
        running.join(WAIT)
        assert isinstance(raised[0], ChatStopped)
        release.set()
        deadline = time.monotonic() + WAIT
        while not connect.made and time.monotonic() < deadline:
            time.sleep(0.01)
        while connect.made and connect.made[0].closed == 0 and time.monotonic() < deadline:
            time.sleep(0.01)

        assert [tools.closed for tools in connect.made] == [1]

    def test_a_closed_conversation_connects_to_nothing_more(self) -> None:
        connect = FakeConnect(alpha=("a_one",))
        connections, _ = make(connect, names=("alpha",))
        connections.close()

        with pytest.raises(ChatStopped):
            connections.tools()
        assert connect.asked == []

    def test_interrupting_ends_what_waits_but_leaves_the_servers_open(self) -> None:
        connect = FakeConnect(alpha=("a_one",))
        connections, told = make(connect, names=("alpha",))
        connections.tools()

        connections.interrupt()

        assert [tools.closed for tools in connect.made] == [0]
        with pytest.raises(ChatStopped):
            connections.tools()
        assert told.states("alpha") == ["connecting", "ready"]

    def test_interrupting_declines_what_a_server_was_asking(self) -> None:
        connections, told = make(FakeConnect(alpha=("a_one",)), names=("alpha",))
        connections.tools()
        failures: list[BaseException] = []

        def ask() -> None:
            try:
                connections.asker.approve(
                    ApprovalRequest(tool="alpha_one", server="alpha", server_tool="one", arguments={}, description="")
                )
            except BaseException as error:  # noqa: BLE001
                failures.append(error)

        running = threading.Thread(target=ask, daemon=True)
        running.start()
        with told.changed:
            assert told.changed.wait_for(lambda: told.of("approval"), WAIT)

        connections.interrupt()
        running.join(WAIT)

        assert isinstance(failures[0], ApprovalDeclined)
        assert told.of("approval")[-1]["state"] == "withdrawn"


class TestSigningIn:
    def test_a_sign_in_page_is_offered_for_the_server_that_asked_for_it(self) -> None:
        def signs_in(name: str, options: dict[str, Any]) -> tuple[str, ...]:
            options["on_sign_in"](name, "https://accounts.example.org/authorize?x=1")

            return ("a_one",)

        connections, told = make(FakeConnect(alpha=signs_in), names=("alpha",))
        connections.tools()

        assert told.states("alpha") == ["connecting", "signing_in", "ready"]
        assert told.of("connection", "alpha")[1]["url"] == "https://accounts.example.org/authorize?x=1"

    def test_a_page_that_is_not_a_web_address_is_not_offered(self) -> None:
        def signs_in(name: str, options: dict[str, Any]) -> tuple[str, ...]:
            options["on_sign_in"](name, "file:///etc/passwd")
            options["on_sign_in"](name, "javascript:alert(1)")

            return ("a_one",)

        connections, told = make(FakeConnect(alpha=signs_in), names=("alpha",))
        connections.tools()

        assert told.states("alpha") == ["connecting", "ready"]

    def test_a_sign_in_for_a_server_that_is_not_one_of_the_conversation_is_ignored(self) -> None:
        connections, told = make(FakeConnect(alpha=("a_one",)), names=("alpha",))
        connections.tools()

        connections._signing_in("gamma", "https://accounts.example.org/")

        assert told.of("connection", "gamma") == []


@pytest.fixture
def genes() -> Iterator[tuple[Connections, Told]]:
    told = Told()
    asker = Asker(told, lambda: False, lambda name: name, 30.0)
    entry = {"command": [sys.executable, SERVER], "approval": {"ask": ["count", "echo"]}}
    connections = Connections({"genes": entry}, told, lambda: False, asker, start_timeout=30)
    yield connections, told
    connections.close()


class TestARealServer:
    @pytest.fixture(autouse=True)
    def needs_mcp(self) -> None:
        pytest.importorskip("mcp")

    def test_its_tools_are_given_and_called(self, genes: tuple[Connections, Told]) -> None:
        connections, told = genes

        tools = {tool.name: tool for tool in connections.tools()}

        assert tools["genes_total"].function(values=[1, 2, 3]) == 6
        assert told.states("genes") == ["connecting", "ready"]
        assert told.of("connection", "genes")[1]["tools"] == len(tools)

    def test_a_call_that_waits_for_approval_is_made_once_it_is_allowed(self, genes: tuple[Connections, Told]) -> None:
        connections, told = genes
        tools = {tool.name: tool for tool in connections.tools()}
        results: list[Any] = []
        running = threading.Thread(target=lambda: results.append(tools["genes_echo"].function(text="ab")), daemon=True)
        running.start()
        with told.changed:
            assert told.changed.wait_for(lambda: told.of("approval"), WAIT)
        waiting = told.of("approval")[0]

        assert waiting["tool"] == "genes_echo"
        assert json.loads(waiting["arguments"]) == {"text": "ab"}
        assert results == []
        connections.asker.approval(waiting["request"], True)
        running.join(WAIT)

        assert results == ["ab"]

    def test_a_call_that_is_declined_is_not_made(self, genes: tuple[Connections, Told]) -> None:
        connections, told = genes
        tools = {tool.name: tool for tool in connections.tools()}
        failures: list[BaseException] = []

        def call() -> None:
            try:
                tools["genes_count"].function()
            except BaseException as error:  # noqa: BLE001
                failures.append(error)

        running = threading.Thread(target=call, daemon=True)
        running.start()
        with told.changed:
            assert told.changed.wait_for(lambda: told.of("approval"), WAIT)
        connections.asker.approval(told.of("approval")[0]["request"], False)
        running.join(WAIT)

        assert isinstance(failures[0], ApprovalDeclined)
