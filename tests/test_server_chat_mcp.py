"""Tests of a conversation that is given MCP servers: connecting, approving calls, and answering questions, as a page
does them, with a scripted model and a real server."""

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from virtual_lab.server.app import create_app
from virtual_lab.server.conversations import Conversations
from virtual_lab.server.workspace import Settings, Workspace

from conftest import TEST_MODEL, FakeClient, text_response, tool_call_response
from test_server_app import handle_of, new_chat, wait_idle
from test_server_conversations import wait_until

pytest.importorskip("mcp")

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}
SERVER = str(Path(__file__).with_name("mcp_test_server.py"))


@pytest.fixture(autouse=True)
def model_client(fake_client: FakeClient) -> FakeClient:
    return fake_client


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    store = Workspace(tmp_path / "workspace")
    store.save_settings(Settings(model=TEST_MODEL, max_cost=None))

    return store


@pytest.fixture
def app(workspace: Workspace) -> FastAPI:
    return create_app(workspace.root, token=TOKEN, check_keys=False)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


def add_server(client: TestClient, name: str = "genes", **entry: Any) -> None:
    given = {"command": [sys.executable, SERVER], **entry}
    response = client.put(f"/api/mcp/servers/{name}", json={"entry": given})
    assert response.status_code == 200, response.text


def say(client: TestClient, chat_id: str, text: str = "Go.") -> None:
    response = client.post(f"/api/chats/{chat_id}/messages", json={"text": text})
    assert response.status_code == 202, response.text


def events(app: FastAPI, chat_id: str, kind: str, state: str | None = None) -> list[Any]:
    return [
        event
        for event in handle_of(app, chat_id).chat.events_since(0)
        if event.kind == kind and (state is None or event.data.get("state") == state)
    ]


def wait_for_event(app: FastAPI, chat_id: str, kind: str, state: str) -> Any:
    wait_until(lambda: events(app, chat_id, kind, state), timeout=30)

    return events(app, chat_id, kind, state)[0]


def approve(client: TestClient, chat_id: str, request: str, allow: bool) -> Any:
    return client.post(f"/api/chats/{chat_id}/approvals/{request}", json={"allow": allow})


def reply(client: TestClient, chat_id: str, request: str, answer: Any) -> Any:
    return client.post(f"/api/chats/{chat_id}/questions/{request}", json={"answer": answer})


def tool_output(app: FastAPI, chat_id: str) -> str:
    (output,) = events(app, chat_id, "tool_output")

    return output.text


def tool_output_events(app: FastAPI, chat_id: str) -> list[Any]:
    return events(app, chat_id, "tool_output")


def process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False

    return True


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))

        return probe.getsockname()[1]


class TestConnecting:
    def test_the_servers_are_connected_to_when_the_first_message_is_sent_and_the_lead_is_given_their_tools(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        add_server(client)
        made = new_chat(client)
        assert events(app, made["id"], "connection") == []

        say(client, made["id"])
        wait_idle(client, made["id"])

        assert [event.data["state"] for event in events(app, made["id"], "connection")] == ["connecting", "ready"]
        ready = events(app, made["id"], "connection", "ready")[0]
        assert ready.data["server"] == "genes"
        assert ready.data["tools"] >= 10
        names = [tool["function"]["name"] for tool in fake_client.completions.calls[0]["tools"]]
        assert {"genes_echo", "genes_total", "genes_lookup"} <= set(names)

    def test_the_servers_are_kept_for_the_next_message_and_not_connected_to_again(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        add_server(client)
        fake_client.completions.responses = [
            tool_call_response("genes_process"),
            text_response("One."),
            tool_call_response("genes_process", call_id="call_2"),
            text_response("Two."),
        ]
        made = new_chat(client)

        say(client, made["id"])
        wait_idle(client, made["id"])
        say(client, made["id"])
        wait_idle(client, made["id"], turns=2)

        outputs = [event.text for event in events(app, made["id"], "tool_output")]
        assert len(outputs) == 2
        assert outputs[0] == outputs[1]
        assert len(events(app, made["id"], "connection")) == 2

    def test_a_server_that_cannot_be_started_fails_the_turn_before_anything_is_spent(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        client.put("/api/mcp/servers/broken", json={"entry": {"command": ["/nonexistent/program-of-genes"]}})
        made = new_chat(client)

        say(client, made["id"])
        wait_idle(client, made["id"])

        (failed,) = events(app, made["id"], "failed")
        assert "broken could not be connected to" in failed.text
        assert "nothing was spent" in failed.text
        assert fake_client.completions.calls == []
        assert [event.data["state"] for event in events(app, made["id"], "connection")] == ["connecting", "failed"]

    def test_a_server_that_was_down_is_tried_again_with_the_next_message_and_the_others_are_not(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        port = free_port()
        add_server(client)
        client.put(
            "/api/mcp/servers/remote",
            json={"entry": {"url": f"http://127.0.0.1:{port}/mcp", "type": "http"}},
        )
        fake_client.completions.responses = [tool_call_response("remote_echo", {"text": "hi"}), text_response("Done.")]
        made = new_chat(client)
        say(client, made["id"])
        wait_idle(client, made["id"])
        assert "remote could not be connected to" in events(app, made["id"], "failed")[0].text
        process = subprocess.Popen(
            [sys.executable, SERVER, "http", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                    break
                except OSError:
                    time.sleep(0.05)

            say(client, made["id"], "Again.")
            wait_idle(client, made["id"], turns=2)

            assert tool_output(app, made["id"]) == "hi"
            states = [(event.data["server"], event.data["state"]) for event in events(app, made["id"], "connection")]
            assert states.count(("genes", "connecting")) == 1
            assert states.count(("remote", "connecting")) == 2
            assert states[-1] == ("remote", "ready")
        finally:
            process.kill()
            process.wait()

    def test_a_conversation_is_set_up_with_the_servers_that_are_on_and_keeps_them_while_it_is_open(
        self, client: TestClient, app: FastAPI
    ) -> None:
        add_server(client, "on")
        add_server(client, "off", enabled=False)
        add_server(client, "later")
        made = new_chat(client)
        assert made["config"]["mcp"] == ["on", "later"]
        client.delete("/api/mcp/servers/later")

        say(client, made["id"])
        wait_idle(client, made["id"])

        assert {event.data["server"] for event in events(app, made["id"], "connection")} == {"on", "later"}

    def test_a_conversation_opened_again_has_the_servers_it_was_set_up_with_that_are_still_there_and_on(
        self, workspace: Workspace
    ) -> None:
        for name in ("kept", "removed", "turned_off"):
            workspace.put_mcp_server(name, {"command": [sys.executable, SERVER]})
        first = Conversations(workspace, check_keys=False)
        chat_id = first.create({"team": []}).id
        first.close()
        workspace.remove_mcp_server("removed")
        workspace.put_mcp_server("turned_off", {"command": [sys.executable, SERVER], "enabled": False})
        workspace.put_mcp_server("new", {"command": [sys.executable, SERVER]})

        second = Conversations(workspace, check_keys=False)
        try:
            reopened = second.get(chat_id)
            assert reopened.connections is not None
            reopened.chat.start("Hello").join(30)
            told = [e.data["server"] for e in reopened.chat.events_since(0) if e.kind == "connection"]
        finally:
            second.close()

        assert set(told) == {"kept"}

    def test_a_conversation_without_servers_has_no_connections(self, client: TestClient, app: FastAPI) -> None:
        add_server(client)
        made = new_chat(client, mcp=[])

        say(client, made["id"])
        wait_idle(client, made["id"])

        assert handle_of(app, made["id"]).connections is None
        assert events(app, made["id"], "connection") == []


class TestApprovingACall:
    def asking(self, client: TestClient, fake_client: FakeClient, app: FastAPI) -> tuple[str, Any]:
        add_server(client, approval={"ask": ["echo", "count"]})
        fake_client.completions.responses = [tool_call_response("genes_echo", {"text": "ab"}), text_response("Done.")]
        made = new_chat(client)
        say(client, made["id"])

        return made["id"], wait_for_event(app, made["id"], "approval", "waiting")

    def test_a_call_waits_for_the_researcher_and_is_made_when_it_is_allowed(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        chat_id, waiting = self.asking(client, fake_client, app)

        assert waiting.data["tool"] == "genes_echo"
        assert waiting.data["server"] == "genes"
        assert json.loads(waiting.data["arguments"]) == {"text": "ab"}
        assert client.get(f"/api/chats/{chat_id}").json()["state"] == "running"
        assert tool_output_events(app, chat_id) == []

        response = approve(client, chat_id, waiting.data["request"], True)
        wait_idle(client, chat_id)

        assert (response.status_code, response.json()) == (200, {"state": "approved"})
        assert tool_output(app, chat_id) == "ab"
        assert [event.data["state"] for event in events(app, chat_id, "approval")] == ["waiting", "approved"]

    def test_a_call_that_is_declined_is_not_made_and_the_lead_is_told_so(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        chat_id, waiting = self.asking(client, fake_client, app)

        response = approve(client, chat_id, waiting.data["request"], False)
        wait_idle(client, chat_id)

        assert response.json() == {"state": "declined"}
        assert "declined this call to genes_echo, so it was not made" in tool_output(app, chat_id)
        assert [event.data["state"] for event in events(app, chat_id, "approval")] == ["waiting", "declined"]
        assert events(app, chat_id, "answer")

    def test_a_request_answered_twice_is_refused_the_second_time(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        chat_id, waiting = self.asking(client, fake_client, app)
        request = waiting.data["request"]
        assert approve(client, chat_id, request, True).status_code == 200
        wait_idle(client, chat_id)

        again = approve(client, chat_id, request, False)

        assert again.status_code == 409
        assert again.json()["error"]["code"] == "not_waiting"

    def test_a_request_that_is_not_waiting_is_refused(self, client: TestClient, app: FastAPI) -> None:
        add_server(client)
        with_servers = new_chat(client)
        without_servers = new_chat(client, mcp=[])
        say(client, with_servers["id"])
        wait_idle(client, with_servers["id"])

        for chat_id in (with_servers["id"], without_servers["id"]):
            refused = approve(client, chat_id, "nothing-asked", True)
            assert refused.status_code == 409, chat_id
            assert refused.json()["error"]["code"] == "not_waiting"
            assert reply(client, chat_id, "nothing-asked", {}).status_code == 409
        assert approve(client, "no-such-chat", "x", True).status_code == 404
        assert reply(client, "no-such-chat", "x", {}).status_code == 404

    def test_a_question_cannot_be_answered_as_an_approval_nor_the_other_way_round(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        chat_id, waiting = self.asking(client, fake_client, app)

        mixed = reply(client, chat_id, waiting.data["request"], {})

        assert mixed.status_code == 409
        assert events(app, chat_id, "approval", "waiting")
        assert not events(app, chat_id, "approval", "approved")
        assert approve(client, chat_id, waiting.data["request"], True).status_code == 200
        wait_idle(client, chat_id)

    def test_the_body_must_say_whether_to_allow(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        chat_id, waiting = self.asking(client, fake_client, app)
        request = waiting.data["request"]

        for body in ({}, {"allow": "yes"}, {"allow": True, "other": 1}):
            response = client.post(f"/api/chats/{chat_id}/approvals/{request}", json=body)
            assert response.status_code == 422, body
        assert approve(client, chat_id, request, True).status_code == 200
        wait_idle(client, chat_id)

    def test_stopping_the_turn_withdraws_the_call_that_waits_and_it_is_not_made(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        chat_id, waiting = self.asking(client, fake_client, app)

        assert client.post(f"/api/chats/{chat_id}/stop").json() == {"accepted": True}
        info = wait_idle(client, chat_id)

        assert info["state"] == "idle"
        assert [event.data["state"] for event in events(app, chat_id, "approval")] == ["waiting", "withdrawn"]
        assert events(app, chat_id, "stopped")
        assert "ab" not in [event.text for event in events(app, chat_id, "tool_output")]
        assert approve(client, chat_id, waiting.data["request"], True).status_code == 409

    def test_the_next_turn_after_a_stopped_one_asks_again(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        chat_id, _ = self.asking(client, fake_client, app)
        client.post(f"/api/chats/{chat_id}/stop")
        wait_idle(client, chat_id)
        fake_client.completions.responses = [tool_call_response("genes_echo", {"text": "cd"}), text_response("Done.")]

        say(client, chat_id, "Again.")
        second = wait_for_event(app, chat_id, "approval", "waiting")
        wait_until(lambda: len(events(app, chat_id, "approval", "waiting")) == 2)
        waiting = events(app, chat_id, "approval", "waiting")[1]
        approve(client, chat_id, waiting.data["request"], True)
        wait_idle(client, chat_id, turns=2)

        assert second.data["request"] != waiting.data["request"]
        assert "cd" in [event.text for event in events(app, chat_id, "tool_output")]

    def test_deleting_the_conversation_withdraws_the_call_that_waits_and_stops_the_servers(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        add_server(client, approval={"ask": ["echo"]})
        fake_client.completions.responses = [
            tool_call_response("genes_process"),
            tool_call_response("genes_echo", {"text": "ab"}),
        ]
        made = new_chat(client)
        say(client, made["id"])
        wait_for_event(app, made["id"], "approval", "waiting")
        pid = int(tool_output(app, made["id"]))
        assert process_running(pid)

        assert client.delete(f"/api/chats/{made['id']}").status_code == 204

        wait_until(lambda: not process_running(pid), timeout=20)


class TestAnsweringAQuestion:
    ORDER = {"name": "guide", "kind": "dna", "copies": 2}

    def asking(
        self, client: TestClient, fake_client: FakeClient, app: FastAPI, tool: str = "genes_order"
    ) -> tuple[str, Any]:
        add_server(client)
        fake_client.completions.responses = [tool_call_response(tool), text_response("Done.")]
        made = new_chat(client)
        say(client, made["id"])

        return made["id"], wait_for_event(app, made["id"], "question", "waiting")

    def test_a_form_the_server_asks_is_put_to_the_researcher_and_what_they_fill_in_goes_back(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        chat_id, waiting = self.asking(client, fake_client, app)

        assert waiting.text == "What is to be ordered?"
        assert set(waiting.data["fields"]) == {"name", "kind", "copies"}
        assert sorted(waiting.data["required"]) == ["kind", "name"]
        assert waiting.data["url"] is None

        response = reply(client, chat_id, waiting.data["request"], self.ORDER)
        wait_idle(client, chat_id)

        assert response.json() == {"state": "answered"}
        assert json.loads(tool_output(app, chat_id)) == {"action": "accept", "order": self.ORDER}

    def test_what_was_answered_is_not_kept_in_what_the_conversation_tells(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        chat_id, waiting = self.asking(client, fake_client, app)
        reply(client, chat_id, waiting.data["request"], {**self.ORDER, "name": "a-secret-name"})
        wait_idle(client, chat_id)

        for event in events(app, chat_id, "question"):
            assert "a-secret-name" not in json.dumps([event.text, dict(event.data)])
        assert [event.data["state"] for event in events(app, chat_id, "question")] == ["waiting", "answered"]

    def test_an_answer_the_form_does_not_take_is_refused_and_the_question_goes_on_waiting(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        chat_id, waiting = self.asking(client, fake_client, app)
        request = waiting.data["request"]

        for answer in ({}, {"name": "x"}, {"name": "x", "kind": "rna"}, {**self.ORDER, "copies": "two"}, "text", [1]):
            refused = reply(client, chat_id, request, answer)
            assert refused.status_code == 422, answer
            assert refused.json()["error"]["code"] == "invalid"
        assert events(app, chat_id, "question", "answered") == []
        assert reply(client, chat_id, request, self.ORDER).status_code == 200
        wait_idle(client, chat_id)

    def test_a_question_that_is_declined_is_told_to_the_server_as_declined(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        chat_id, waiting = self.asking(client, fake_client, app)

        response = reply(client, chat_id, waiting.data["request"], None)
        wait_idle(client, chat_id)

        assert response.json() == {"state": "declined"}
        assert json.loads(tool_output(app, chat_id)) == {"action": "decline", "order": None}

    def test_a_yes_or_no_question_is_answered_with_a_boolean(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        chat_id, waiting = self.asking(client, fake_client, app, "genes_confirm")

        assert waiting.data["fields"]["approve"]["type"] == "boolean"
        reply(client, chat_id, waiting.data["request"], {"approve": True})
        wait_idle(client, chat_id)

        assert tool_output(app, chat_id) == "accept True"

    def test_a_question_answered_at_a_web_page_is_offered_as_a_link_and_answered_once_it_was_visited(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Only under the protocol from before 2026 can a server ask for a web page to be visited while a tool runs
        monkeypatch.setattr(import_module("virtual_lab.mcp_tools").MCPConnection, "protocol_mode", "legacy")
        chat_id, waiting = self.asking(client, fake_client, app, "genes_visit")

        assert waiting.data["url"] == "https://pay.example.org/test"
        reply(client, chat_id, waiting.data["request"], {})
        wait_idle(client, chat_id)

        assert tool_output(app, chat_id) == "accept"

    def test_stopping_the_turn_withdraws_a_question_that_waits(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        chat_id, waiting = self.asking(client, fake_client, app)

        client.post(f"/api/chats/{chat_id}/stop")
        wait_idle(client, chat_id)

        assert [event.data["state"] for event in events(app, chat_id, "question")] == ["waiting", "withdrawn"]
        assert reply(client, chat_id, waiting.data["request"], self.ORDER).status_code == 409
