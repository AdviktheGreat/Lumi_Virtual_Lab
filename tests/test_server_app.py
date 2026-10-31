"""Tests of the server's routes, as a page uses them."""

import asyncio
import errno
import hashlib
import json
import logging
import os
import shutil
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import requests
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from virtual_lab.__about__ import __version__
from virtual_lab import environment, utils
from virtual_lab.constants import MAX_UPLOAD_BYTES
from virtual_lab.environment import DATA_LAKE, sandbox_image
from virtual_lab.events import ChatEvent
from virtual_lab.export import PDFExportError
from virtual_lab.openrouter import Catalog, models_from
from virtual_lab.server import app as app_module
from virtual_lab.server.app import (
    MAX_MESSAGE_CHARS,
    MAX_PATH_CHARS,
    PDF_UNAVAILABLE,
    RequestBodyReader,
    create_app,
    last_event,
)
from virtual_lab.server.errors import ApiError, file_error
from virtual_lab.server.files import download_headers
from virtual_lab.server.security import TOKEN_COOKIE
from virtual_lab.server.workspace import Settings, Workspace
from virtual_lab.utils import CostUnknownError

from conftest import TEST_MODEL, FakeClient, text_response, tool_call_response
from test_export import PNG
from setup_fakes import Bucket, FakeDocker, wait_for
from test_server_conversations import hold_the_model, wait_until

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}


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


def new_chat(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post("/api/chats", json={"team": [], **body})
    assert response.status_code == 201, response.text

    return response.json()


def wait_idle(client: TestClient, chat_id: str, turns: int = 1) -> dict[str, Any]:
    info: dict[str, Any] = {}

    def done() -> bool:
        nonlocal info
        info = client.get(f"/api/chats/{chat_id}").json()
        return info["state"] == "idle" and info["turns"] >= turns

    wait_until(done)

    return info


def handle_of(app: FastAPI, chat_id: str) -> Any:
    return app.state.conversations.get(chat_id)


def fail(message: str) -> Any:
    raise AssertionError(message)


async def call_app(
    app: Any, method: str, path: str, query: str, headers: dict[str, str], receive_next: Any
) -> list[dict[str, Any]]:
    """What the application sends for a request made to it directly, whose body is whatever receive_next gives."""
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return receive_next()

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "scheme": "http",
        "query_string": query.encode(),
        "headers": [(b"host", b"localhost"), (b"authorization", f"Bearer {TOKEN}".encode())]
        + [(name.encode(), value.encode()) for name, value in headers.items()],
        "client": ("127.0.0.1", 50000),
        "server": ("localhost", 80),
    }
    await app(scope, receive, send)

    return sent


def error_of(response: httpx.Response) -> dict[str, Any]:
    body = response.json()
    assert list(body) == ["error"], body

    return body["error"]


class TestAccess:
    def test_only_the_health_check_is_answered_without_the_token(self, app: FastAPI) -> None:
        with TestClient(app, base_url=LOCAL) as anonymous:
            health = anonymous.get("/api/health")
            assert health.json() == {"status": "ok", "version": __version__}

            for method, path in [
                ("GET", "/api/settings"),
                ("GET", "/api/chats"),
                ("POST", "/api/chats"),
                ("GET", "/api/keys"),
                ("PUT", "/api/keys/OPENAI_API_KEY"),
                ("GET", "/api/chats/anything/events"),
                ("GET", "/api/chats/anything/export"),
            ]:
                response = anonymous.request(method, path, json={})
                assert response.status_code == 401, path
                assert error_of(response)["code"] == "unauthorized"

    def test_a_page_of_another_address_may_not_change_anything(self, client: TestClient) -> None:
        response = client.post("/api/chats", json={"team": []}, headers={"Origin": "http://evil.example"})

        assert response.status_code == 403
        assert error_of(response)["code"] == "forbidden_origin"
        assert client.get("/api/chats").json() == {"chats": []}

    def test_a_name_that_is_not_this_machines_is_turned_away(self, app: FastAPI) -> None:
        with TestClient(app, base_url="http://evil.example", headers=BEARER) as elsewhere:
            assert elsewhere.get("/api/health").status_code == 403

    def test_an_address_there_is_none_of_is_answered_in_the_servers_shape(self, client: TestClient) -> None:
        for path in ("/api/nothing", "/api", "/api/chats/x/nothing"):
            response = client.get(path)
            assert response.status_code == 404, path
            assert error_of(response)["code"] == "not_found"

    def test_a_kind_of_request_an_address_does_not_take_is_answered_in_the_servers_shape(
        self, client: TestClient
    ) -> None:
        response = client.put("/api/chats")

        assert response.status_code == 405
        assert error_of(response)["code"] == "method_not_allowed"
        assert "GET" in response.headers["allow"]

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/api/docs", "/api/openapi.json"])
    def test_the_server_does_not_describe_itself_to_a_page(self, client: TestClient, path: str) -> None:
        response = client.get(path)

        assert response.status_code == 404
        assert error_of(response)["code"] == "not_found"

    def test_a_request_that_is_not_valid_says_which_part(self, client: TestClient) -> None:
        response = client.post("/api/chats", json={"team": "everyone", "max_cost": "plenty", "colour": "red"})

        error = error_of(response)
        assert response.status_code == 422
        assert error["code"] == "invalid"
        assert {item["field"] for item in error["fields"]} == {"team", "max_cost", "colour"}
        assert all(item["message"] for item in error["fields"])
        assert all(f"{item['field']}: {item['message']}" in error["message"] for item in error["fields"])
        # What was sent is not sent back
        assert "everyone" not in response.text and "plenty" not in response.text

    def test_a_body_that_is_not_json_is_not_valid(self, client: TestClient) -> None:
        response = client.post("/api/chats", content=b"{not json", headers={"Content-Type": "application/json"})

        assert response.status_code == 422
        assert error_of(response)["code"] == "invalid"

    def test_a_failure_in_the_server_is_not_told_to_the_page(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken() -> None:
            raise RuntimeError("secret detail of the machine")

        monkeypatch.setattr(app.state.conversations, "summaries", broken)

        with TestClient(app, base_url=LOCAL, headers=BEARER, raise_server_exceptions=False) as quiet:
            response = quiet.get("/api/chats")

        assert response.status_code == 500
        assert error_of(response)["code"] == "internal"
        assert "secret detail" not in response.text


class TestSettings:
    def test_the_settings_are_shown_with_where_everything_is_kept(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        shown = client.get("/api/settings").json()

        assert shown == {
            "model": TEST_MODEL,
            "stream": True,
            "max_cost": None,
            "code": "none",
            "sandbox": "python",
            "network": True,
            "python": "",
            "data_lake": "",
            "forward_keys": [],
            "workspace": str(workspace.root),
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "chat_limits": {
                "max_delegations": {"default": 3, "ceiling": 20},
                "max_rounds": {"default": 3, "ceiling": 10},
            },
        }

    def test_the_largest_file_that_can_be_attached_is_told_with_the_settings_and_kept_by_a_change(
        self, workspace: Workspace
    ) -> None:
        app = create_app(workspace.root, token=TOKEN, check_keys=False, max_upload_bytes=1234)

        with TestClient(app, base_url=LOCAL, headers=BEARER) as client:
            assert client.get("/api/settings").json()["max_upload_bytes"] == 1234
            assert client.patch("/api/settings", json={"stream": False}).json()["max_upload_bytes"] == 1234

    def test_a_conversation_takes_the_largest_file_the_server_was_set_up_with(self, workspace: Workspace) -> None:
        app = create_app(workspace.root, token=TOKEN, check_keys=False, max_upload_bytes=5)

        with TestClient(app, base_url=LOCAL, headers=BEARER) as client:
            made = new_chat(client)

            assert handle_of(app, made["id"]).chat.max_upload_bytes == 5
            response = client.post(f"/api/chats/{made['id']}/uploads", params={"name": "a.bin"}, content=b"012345")
            assert response.status_code == 413
            assert (
                client.post(f"/api/chats/{made['id']}/uploads", params={"name": "a.bin"}, content=b"01234").status_code
                == 201
            )

    def test_a_change_is_kept_for_the_next_time(self, client: TestClient, workspace: Workspace) -> None:
        response = client.patch("/api/settings", json={"code": "docker", "max_cost": 4, "stream": False})

        assert response.status_code == 200
        assert response.json()["code"] == "docker"
        saved = workspace.load_settings()
        assert (saved.code, saved.max_cost, saved.stream, saved.model) == ("docker", 4.0, False, TEST_MODEL)
        assert client.get("/api/settings").json()["max_cost"] == 4.0

    def test_no_limit_is_set_by_null_and_a_setting_left_out_is_left_alone(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        workspace.save_settings(Settings(model=TEST_MODEL, max_cost=2.0, network=False))

        client.patch("/api/settings", json={"max_cost": None})
        assert workspace.load_settings().max_cost is None
        assert workspace.load_settings().network is False

        client.patch("/api/settings", json={})
        assert workspace.load_settings().network is False

    def test_where_the_data_lake_is_and_the_keys_code_is_given_are_kept(
        self, client: TestClient, workspace: Workspace, tmp_path: Path
    ) -> None:
        lake = tmp_path / "lake"

        response = client.patch(
            "/api/settings", json={"data_lake": str(lake), "forward_keys": ["ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"]}
        )

        assert response.status_code == 200
        assert response.json()["data_lake"] == str(lake.resolve())
        assert response.json()["forward_keys"] == ["ANTHROPIC_API_KEY"]
        saved = workspace.load_settings()
        assert (saved.data_lake, saved.forward_keys) == (str(lake.resolve()), ["ANTHROPIC_API_KEY"])

        client.patch("/api/settings", json={"stream": False})
        assert workspace.load_settings().data_lake == str(lake.resolve())

        client.patch("/api/settings", json={"data_lake": "", "forward_keys": []})
        saved = workspace.load_settings()
        assert (saved.data_lake, saved.forward_keys) == ("", [])

    def test_a_data_lake_where_conversations_are_kept_is_refused(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        for where in (workspace.chats_dir, workspace.chats_dir / "inside", workspace.root):
            response = client.patch("/api/settings", json={"data_lake": str(where)})

            assert response.status_code == 422, where
            assert "conversations are kept" in error_of(response)["message"]
        assert workspace.load_settings().data_lake == ""

    def test_a_data_lake_path_that_is_too_long_is_refused_for_its_length(self, client: TestClient) -> None:
        response = client.patch("/api/settings", json={"data_lake": "/" + "x" * (MAX_PATH_CHARS + 1)})

        assert response.status_code == 422
        assert [item["field"] for item in error_of(response)["fields"]] == ["data_lake"]

    @pytest.mark.parametrize(
        "body",
        [
            {"model": "no-such-model"},
            {"code": "cloud"},
            {"max_cost": -1},
            {"colour": "red"},
            {"stream": "maybe"},
            {"data_lake": "relative/lake"},
            {"data_lake": "x" * 5000},
            {"forward_keys": ["PATH"]},
            {"forward_keys": "ANTHROPIC_API_KEY"},
            {"forward_keys": ["ANTHROPIC_API_KEY"] * 100},
        ],
    )
    def test_a_change_that_cannot_be_used_is_refused_and_keeps_nothing(
        self, client: TestClient, workspace: Workspace, body: dict[str, Any]
    ) -> None:
        before = workspace.load_settings()

        response = client.patch("/api/settings", json=body)

        assert response.status_code == 422
        assert error_of(response)["code"] == "invalid"
        assert workspace.load_settings() == before

    def test_the_models_are_listed_with_whether_they_can_be_reached(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LLM_SOURCE", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "set")

        shown = client.get("/api/models").json()

        assert shown["default"] == TEST_MODEL
        assert {"id": "gpt-5.2", "provider": "OpenAI", "ready": True} in shown["models"]


SONNET = "openrouter/anthropic/claude-sonnet-4.5"


def openrouter_list() -> Any:
    return models_from(
        {
            "data": [
                {
                    "id": "anthropic/claude-sonnet-4.5",
                    "name": "Anthropic: Claude Sonnet 4.5",
                    "context_length": 1_000_000,
                    "architecture": {"output_modalities": ["text"]},
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                    "supported_parameters": ["tools"],
                }
            ]
        }
    )


class TestOpenRouter:
    @pytest.fixture(autouse=True)
    def without_prices_left_behind(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(utils, "REGISTERED_PRICES", {})
        monkeypatch.delenv("LLM_SOURCE", raising=False)

    @pytest.fixture
    def asked(self) -> list[int]:
        return []

    @pytest.fixture
    def app(self, workspace: Workspace, asked: list[int]) -> FastAPI:
        def source() -> Any:
            asked.append(1)
            return openrouter_list()

        return create_app(workspace.root, token=TOKEN, check_keys=False, catalog=Catalog(fetch=source))

    def test_its_routers_and_best_known_models_are_offered_with_whether_the_key_is_set(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, asked: list[int]
    ) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        before = {item["id"]: item for item in client.get("/api/models").json()["models"]}
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        after = {item["id"]: item for item in client.get("/api/models").json()["models"]}

        assert before["openrouter/auto"] == {"id": "openrouter/auto", "provider": "OpenRouter", "ready": False}
        assert after[SONNET] == {"id": SONNET, "provider": "OpenRouter", "ready": True}
        # Offering them does not ask OpenRouter for its list
        assert asked == []

    def test_the_whole_list_is_read_from_openrouter_when_it_is_asked_for(
        self, client: TestClient, asked: list[int]
    ) -> None:
        shown = client.get("/api/models/openrouter").json()

        assert shown["problem"] is None
        assert shown["models"] == [
            {
                "id": SONNET,
                "name": "Anthropic: Claude Sonnet 4.5",
                "context_length": 1_000_000,
                "input_per_million": pytest.approx(3.0),
                "output_per_million": pytest.approx(15.0),
            }
        ]
        client.get("/api/models/openrouter")
        assert asked == [1]

    def test_the_trouble_in_reading_the_list_is_told(self, workspace: Workspace) -> None:
        def source() -> Any:
            raise requests.ConnectionError("no connection")

        broken = create_app(workspace.root, token=TOKEN, check_keys=False, catalog=Catalog(fetch=source))
        with TestClient(broken, base_url=LOCAL, headers=BEARER) as opened:
            shown = opened.get("/api/models/openrouter").json()

        assert shown["models"] == []
        assert "no connection" in shown["problem"]

    def test_choosing_one_of_its_models_in_the_settings_reads_what_they_cost(
        self, client: TestClient, asked: list[int]
    ) -> None:
        response = client.patch("/api/settings", json={"model": SONNET})

        assert response.status_code == 200 and response.json()["model"] == SONNET
        assert asked == [1]
        assert utils.compute_token_cost(SONNET, 10**6, 0) == pytest.approx(3.0)
        client.patch("/api/settings", json={"model": TEST_MODEL})
        assert asked == [1]

    def test_a_conversation_is_switched_to_another_model_and_goes_on_from_where_it_was(
        self, client: TestClient, workspace: Workspace, fake_client: FakeClient
    ) -> None:
        chat_id = new_chat(client)["id"]
        client.post(f"/api/chats/{chat_id}/messages", json={"text": "Before"})
        wait_idle(client, chat_id)

        response = client.put(f"/api/chats/{chat_id}/model", json={"model": SONNET})

        assert response.status_code == 200, response.text
        switched = response.json()
        assert switched["config"]["model"] == SONNET
        assert switched["turns"] == 1 and switched["state"] == "idle"
        assert client.get(f"/api/chats/{chat_id}").json()["config"]["model"] == SONNET
        assert [item["model"] for item in client.get("/api/chats").json()["chats"]] == [SONNET]
        client.post(f"/api/chats/{chat_id}/messages", json={"text": "After"})
        wait_idle(client, chat_id, turns=2)
        assert fake_client.completions.calls[-1]["model"] == SONNET

    def test_what_cannot_be_switched_is_refused_and_told_why(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chat_id = new_chat(client)["id"]

        assert client.put("/api/chats/no-such-chat/model", json={"model": SONNET}).status_code == 404
        assert client.put(f"/api/chats/{chat_id}/model", json={}).status_code == 422
        assert client.put(f"/api/chats/{chat_id}/model", json={"model": ""}).status_code == 422
        refused = client.put(f"/api/chats/{chat_id}/model", json={"model": "mystery-model"})
        assert refused.status_code == 422 and error_of(refused)["code"] == "invalid"
        assert client.get(f"/api/chats/{chat_id}").json()["config"]["model"] == TEST_MODEL

    def test_a_conversation_that_is_working_is_not_switched(
        self, client: TestClient, fake_client: FakeClient
    ) -> None:
        chat_id = new_chat(client)["id"]
        gate = hold_the_model(fake_client)
        client.post(f"/api/chats/{chat_id}/messages", json={"text": "Think"})
        assert gate.reached.wait(10)

        refused = client.put(f"/api/chats/{chat_id}/model", json={"model": SONNET})

        assert refused.status_code == 409 and error_of(refused)["code"] == "busy"
        gate.release()
        wait_idle(client, chat_id)


class TestKeys:
    def test_which_providers_have_their_keys_is_shown_without_any_key(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-never-shown")
        monkeypatch.delenv("GROQ_API_KEY", raising=False)

        response = client.get("/api/keys")

        shown = response.json()
        providers = {item["provider"]: item for item in shown["providers"]}
        assert providers["OpenAI"] == {
            "provider": "OpenAI",
            "variables": ["OPENAI_API_KEY"],
            "missing": [],
            "ready": True,
        }
        assert providers["Groq"]["missing"] == ["GROQ_API_KEY"] and providers["Groq"]["ready"] is False
        assert shown["settable"] == [
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "GROQ_API_KEY",
            "OPENROUTER_API_KEY",
        ]
        assert providers["OpenRouter"]["variables"] == ["OPENROUTER_API_KEY"]
        assert "sk-never-shown" not in response.text

    def test_a_key_is_set_until_the_server_stops_and_is_never_told_to_anyone(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, workspace: Workspace
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "placeholder")
        monkeypatch.delenv("GEMINI_API_KEY")

        response = client.put("/api/keys/GEMINI_API_KEY", json={"value": "  gem-secret-value \n"})

        assert response.status_code == 200
        assert os.environ["GEMINI_API_KEY"] == "gem-secret-value"
        assert "gem-secret-value" not in response.text
        assert {item["provider"]: item["ready"] for item in response.json()["providers"]}["Gemini"] is True
        # Nothing of it is written down
        assert not any(
            "gem-secret-value" in path.read_text(errors="ignore")
            for path in workspace.root.rglob("*")
            if path.is_file()
        )

    def test_a_key_is_taken_away(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "to-remove")

        response = client.delete("/api/keys/GROQ_API_KEY")

        assert "GROQ_API_KEY" not in os.environ
        assert {item["provider"]: item["ready"] for item in response.json()["providers"]}["Groq"] is False
        assert client.delete("/api/keys/GROQ_API_KEY").status_code == 200

    @pytest.mark.parametrize("value", ["", "   ", "two\nlines", "tab\tinside", "nul\x00byte", "del\x7fchar"])
    def test_a_key_that_is_not_on_one_line_is_refused_and_not_told_back(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "kept")

        response = client.put("/api/keys/GROQ_API_KEY", json={"value": value})

        assert response.status_code == 422
        assert os.environ["GROQ_API_KEY"] == "kept"
        assert value.strip() == "" or value not in response.text

    def test_only_the_keys_the_interface_sets_can_be_set(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", os.environ["PATH"])

        for name in ("PATH", "AWS_REGION", "openai_api_key"):
            put = client.put(f"/api/keys/{name}", json={"value": "x"})
            assert put.status_code == 422, name
            assert error_of(put)["code"] == "invalid"
            assert client.delete(f"/api/keys/{name}").status_code == 422
        assert os.environ["PATH"] != "x"

    def test_a_key_that_is_too_long_is_refused(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "kept")

        response = client.put("/api/keys/GROQ_API_KEY", json={"value": "k" * 5000})

        assert response.status_code == 422
        assert os.environ["GROQ_API_KEY"] == "kept"


class TestSetup:
    @pytest.fixture(autouse=True)
    def small_parts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "DATA_LAKE_CHUNK_BYTES", 256)

    @pytest.fixture
    def docker(self, tmp_path: Path) -> FakeDocker:
        return FakeDocker(tmp_path / "docker")

    @pytest.fixture
    def bucket(self) -> Iterator[Bucket]:
        served = Bucket()
        yield served
        served.close()

    @pytest.fixture
    def machine(self, workspace: Workspace, docker: FakeDocker, bucket: Bucket) -> Iterator[TestClient]:
        made = create_app(
            workspace.root, token=TOKEN, check_keys=False, docker_command=docker.command, release_url=bucket.url
        )
        with TestClient(made, base_url=LOCAL, headers=BEARER) as opened:
            yield opened

    def finished(self, machine: TestClient, job_id: str) -> dict[str, Any]:
        job: dict[str, Any] = {}

        def over() -> bool:
            nonlocal job
            job = machine.get(f"/api/setup/jobs/{job_id}").json()
            return job["state"] not in ("running", "stopping")

        wait_for(over)

        return job

    def test_what_there_is_to_set_up_is_shown_with_what_is_left_to_do(
        self, machine: TestClient, docker: FakeDocker, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "set")
        monkeypatch.delenv("LLM_SOURCE", raising=False)
        workspace.save_settings(Settings(model=TEST_MODEL, code="docker", sandbox="bio"))

        shown = machine.get("/api/setup").json()

        assert set(shown) == {"docker", "images", "data_lake", "jobs", "steps"}
        assert shown["docker"] == {"installed": True, "running": True, "version": "27.3.1", "message": None}
        assert [(stage["target"], stage["built"]) for stage in shown["images"]["stages"]] == [
            ("base", False),
            ("bio", False),
            ("full", False),
        ]
        assert shown["data_lake"]["directory"] == str(workspace.data_lake_dir)
        assert (shown["data_lake"]["present"], shown["data_lake"]["files"]) == (0, len(DATA_LAKE))
        assert shown["jobs"] == []
        assert {step["id"]: step["state"] for step in shown["steps"]} == {
            "docker": "done",
            "image": "todo",
            "data_lake": "todo",
            "model_key": "done",
        }
        monkeypatch.delenv("OPENAI_API_KEY")
        steps = machine.get("/api/setup").json()["steps"]
        assert {step["id"]: step["state"] for step in steps}["model_key"] == "todo"

    def test_docker_that_is_not_running_is_shown_and_nothing_is_said_of_the_images(
        self, machine: TestClient, docker: FakeDocker
    ) -> None:
        docker.configure(daemon="down")

        shown = machine.get("/api/setup").json()

        assert shown["docker"]["running"] is False
        assert all(stage["built"] is None for stage in shown["images"]["stages"])

    def test_an_image_is_built_in_the_background_and_shown_as_built_once_it_is(
        self, machine: TestClient, docker: FakeDocker
    ) -> None:
        docker.build(wait=True, lines=["#1 [1/3] FROM python", "#2 RUN pip install"])

        started = machine.post("/api/setup/images/bio")

        assert started.status_code == 202
        job = started.json()
        assert (job["kind"], job["subject"], job["state"]) == ("image", "bio", "running")
        assert job["log"]["from"] == 0
        wait_for(lambda: docker.started)
        building = machine.get("/api/setup").json()
        assert [(stage["target"], stage["building"]) for stage in building["images"]["stages"]] == [
            ("base", False),
            ("bio", True),
            ("full", False),
        ]
        assert [item["id"] for item in building["jobs"]] == [job["id"]]
        docker.release()

        done = self.finished(machine, job["id"])

        assert (done["state"], done["error"]) == ("succeeded", None)
        assert done["message"] == "Built Biomni's bio environment"
        assert docker.images == [sandbox_image("bio")]
        bio = machine.get("/api/setup").json()["images"]["stages"][1]
        assert (bio["built"], bio["building"]) == (True, False)

    def test_what_a_build_prints_is_read_from_where_the_page_got_to(
        self, machine: TestClient, docker: FakeDocker
    ) -> None:
        docker.build(lines=["first", "second", "third"])
        job = machine.post("/api/setup/images/base").json()
        self.finished(machine, job["id"])

        everything = machine.get(f"/api/setup/jobs/{job['id']}", params={"log_from": 0}).json()
        rest = machine.get(f"/api/setup/jobs/{job['id']}", params={"log_from": 2}).json()
        past = machine.get(f"/api/setup/jobs/{job['id']}", params={"log_from": 99}).json()
        unsaid = machine.get(f"/api/setup/jobs/{job['id']}").json()

        assert everything["log"] == {"from": 0, "lines": ["first", "second", "third"]}
        assert rest["log"] == {"from": 2, "lines": ["third"]}
        assert past["log"] == {"from": 3, "lines": []}
        assert unsaid["log"] == everything["log"]
        assert unsaid["log_total"] == 3

    def test_a_place_in_the_output_before_the_first_line_is_not_one(
        self, machine: TestClient, docker: FakeDocker
    ) -> None:
        job = machine.post("/api/setup/images/base").json()
        self.finished(machine, job["id"])

        for bad in ("-1", "first", ""):
            response = machine.get(f"/api/setup/jobs/{job['id']}", params={"log_from": bad})
            assert response.status_code == 422, bad
            assert error_of(response)["code"] == "invalid"

    def test_a_build_that_fails_says_so_and_the_image_is_not_built(
        self, machine: TestClient, docker: FakeDocker
    ) -> None:
        docker.build(exit=1, lines=["#5 ERROR: no space left on device"])
        job = machine.post("/api/setup/images/base").json()

        done = self.finished(machine, job["id"])

        assert done["state"] == "failed"
        assert done["error"]
        assert machine.get("/api/setup").json()["images"]["stages"][0]["built"] is False

    def test_an_image_that_is_built_is_not_built_again(self, machine: TestClient, docker: FakeDocker) -> None:
        docker.configure(images=[sandbox_image("base")])

        response = machine.post("/api/setup/images/base")

        assert response.status_code == 409
        assert error_of(response)["code"] == "already_built"
        assert docker.builds == []

    def test_an_image_is_not_built_while_docker_is_not_running(self, machine: TestClient, docker: FakeDocker) -> None:
        docker.configure(daemon="down")

        response = machine.post("/api/setup/images/base")

        assert response.status_code == 409
        assert error_of(response)["code"] == "docker_unavailable"
        assert error_of(response)["message"].startswith("Docker is installed but is not running")

    @pytest.mark.parametrize("target", ["huge", "BASE", "base%20", "full.py"])
    def test_a_stage_that_there_is_none_of_is_not_built(self, machine: TestClient, target: str) -> None:
        response = machine.post(f"/api/setup/images/{target}")

        assert response.status_code == 422
        assert error_of(response)["code"] == "invalid"

    def test_only_one_image_is_built_at_a_time_and_the_one_being_built_is_told(
        self, machine: TestClient, docker: FakeDocker
    ) -> None:
        docker.build(wait=True)
        first = machine.post("/api/setup/images/base").json()

        second = machine.post("/api/setup/images/bio")

        assert second.status_code == 409
        error = error_of(second)
        assert error["code"] == "busy"
        assert error["job"]["id"] == first["id"]
        assert error["job"]["state"] == "running"
        assert len(docker.builds) <= 1
        docker.release()
        self.finished(machine, first["id"])

    def test_a_build_is_stopped_and_says_it_was(self, machine: TestClient, docker: FakeDocker) -> None:
        docker.build(wait=True)
        job = machine.post("/api/setup/images/base").json()
        wait_for(lambda: docker.started)

        stopping = machine.post(f"/api/setup/jobs/{job['id']}/stop")

        assert stopping.status_code == 200
        assert stopping.json()["state"] in ("stopping", "stopped")
        done = self.finished(machine, job["id"])
        assert done["state"] == "stopped"
        assert docker.images == []
        again = machine.post(f"/api/setup/jobs/{job['id']}/stop")
        assert again.status_code == 200
        assert again.json()["state"] == "stopped"

    def test_a_job_there_is_none_of_is_not_found(self, machine: TestClient) -> None:
        for method, path in [("GET", "/api/setup/jobs/nothing"), ("POST", "/api/setup/jobs/nothing/stop")]:
            response = machine.request(method, path)
            assert response.status_code == 404, path
            assert error_of(response)["code"] == "not_found"

    def test_the_jobs_are_listed_latest_first_without_what_they_printed(
        self, machine: TestClient, docker: FakeDocker, bucket: Bucket
    ) -> None:
        assert machine.get("/api/setup/jobs").json() == {"jobs": []}
        bucket.files[next(iter(DATA_LAKE))] = b"data"
        built = machine.post("/api/setup/images/base").json()
        self.finished(machine, built["id"])
        fetched = machine.post("/api/setup/data-lake", json={"names": [next(iter(DATA_LAKE))]}).json()
        self.finished(machine, fetched["id"])

        jobs = machine.get("/api/setup/jobs").json()["jobs"]

        assert [job["id"] for job in jobs] == [fetched["id"], built["id"]]
        assert all("log" not in job for job in jobs)

    def test_the_data_lake_is_listed_with_which_files_are_there(
        self, machine: TestClient, workspace: Workspace
    ) -> None:
        names = list(DATA_LAKE)
        workspace.data_lake_dir.mkdir(parents=True)
        (workspace.data_lake_dir / names[0]).write_bytes(b"12345")

        shown = machine.get("/api/setup/data-lake").json()

        assert shown["data_lake"]["directory"] == str(workspace.data_lake_dir)
        assert shown["data_lake"]["present"] == 1
        assert [file["name"] for file in shown["files"]] == names
        assert (shown["files"][0]["present"], shown["files"][0]["bytes"]) == (True, 5)
        assert (shown["files"][1]["present"], shown["files"][1]["bytes"]) == (False, None)

    def test_the_data_lake_is_fetched_in_the_background_to_where_the_settings_say(
        self, machine: TestClient, bucket: Bucket, workspace: Workspace, tmp_path: Path
    ) -> None:
        names = list(DATA_LAKE)[:2]
        bucket.files.update({names[0]: b"first file", names[1]: b"second"})
        lake = tmp_path / "lake"
        machine.patch("/api/settings", json={"data_lake": str(lake)})

        started = machine.post("/api/setup/data-lake", json={"names": names})

        assert started.status_code == 202
        job = started.json()
        assert (job["kind"], job["state"]) == ("data_lake", "running")
        done = self.finished(machine, job["id"])
        assert (done["state"], done["error"]) == ("succeeded", None)
        assert done["progress"]["done"] == 2
        assert done["progress"]["total"] == 2
        assert done["progress"]["fetched"] == len(b"first file") + len(b"second")
        assert (lake.resolve() / names[0]).read_bytes() == b"first file"
        assert (lake.resolve() / names[1]).read_bytes() == b"second"
        assert not workspace.data_lake_dir.exists()
        assert machine.get("/api/setup/data-lake").json()["data_lake"]["present"] == 2

    def test_a_data_lake_fetched_without_naming_files_is_all_of_it(
        self, machine: TestClient, bucket: Bucket, workspace: Workspace
    ) -> None:
        job = machine.post("/api/setup/data-lake").json()
        done = self.finished(machine, job["id"])

        assert done["state"] == "failed"
        assert done["progress"]["total"] == len(DATA_LAKE)
        assert sorted(set(bucket.requests)) == sorted(DATA_LAKE)

    def test_a_fetch_that_is_stopped_part_of_the_way_says_so_and_leaves_no_part_of_a_file(
        self, machine: TestClient, bucket: Bucket, workspace: Workspace
    ) -> None:
        name = next(iter(DATA_LAKE))
        bucket.files[name] = b"x" * 100_000
        gate = bucket.gate(name)
        job = machine.post("/api/setup/data-lake", json={"names": [name]}).json()
        wait_for(lambda: machine.get(f"/api/setup/jobs/{job['id']}").json()["progress"].get("bytes", 0) > 0)

        machine.post(f"/api/setup/jobs/{job['id']}/stop")
        gate.set()
        done = self.finished(machine, job["id"])

        assert done["state"] == "stopped"
        assert list(workspace.data_lake_dir.iterdir()) == []

    def test_more_files_than_the_data_lake_has_are_not_fetched(self, machine: TestClient, bucket: Bucket) -> None:
        response = machine.post("/api/setup/data-lake", json={"names": [next(iter(DATA_LAKE))] * (len(DATA_LAKE) + 1)})

        assert response.status_code == 422
        assert [item["field"] for item in error_of(response)["fields"]] == ["names"]
        assert bucket.requests == []

    def test_only_one_fetch_runs_at_a_time(self, machine: TestClient, bucket: Bucket) -> None:
        name = next(iter(DATA_LAKE))
        bucket.files[name] = b"x" * 1000
        gate = bucket.gate(name)
        first = machine.post("/api/setup/data-lake", json={"names": [name]}).json()

        second = machine.post("/api/setup/data-lake", json={"names": [name]})

        assert second.status_code == 409
        assert error_of(second)["code"] == "busy"
        assert error_of(second)["job"]["id"] == first["id"]
        gate.set()
        self.finished(machine, first["id"])

    @pytest.mark.parametrize(
        "body",
        [
            {"names": []},
            {"names": ["not-in-the-data-lake.parquet"]},
            {"names": "all"},
            {"names": [1]},
            {"everything": True},
        ],
    )
    def test_files_that_are_not_in_the_data_lake_are_not_fetched(
        self, machine: TestClient, bucket: Bucket, body: dict[str, Any]
    ) -> None:
        response = machine.post("/api/setup/data-lake", json=body)

        assert response.status_code == 422
        assert error_of(response)["code"] == "invalid"
        assert bucket.requests == []
        assert machine.get("/api/setup/jobs").json() == {"jobs": []}

    def test_code_in_docker_is_not_given_a_conversation_until_what_it_needs_is_there(
        self, machine: TestClient, docker: FakeDocker, workspace: Workspace
    ) -> None:
        docker.configure(daemon="down")

        refused = machine.post("/api/chats", json={"team": [], "code": {"where": "docker", "sandbox": "bio"}})

        assert refused.status_code == 409
        error = error_of(refused)
        assert error["code"] == "setup_needed"
        assert error["missing"] == ["docker"]
        assert machine.get("/api/chats").json() == {"chats": []}

        docker.configure(daemon="up")
        refused = machine.post("/api/chats", json={"team": [], "code": {"where": "docker", "sandbox": "bio"}})
        assert error_of(refused)["missing"] == ["image"]

        docker.configure(images=[sandbox_image("bio")])
        made = machine.post("/api/chats", json={"team": [], "code": {"where": "docker", "sandbox": "bio"}})
        assert made.status_code == 201
        assert made.json()["config"]["code"]["where"] == "docker"

    def test_a_conversation_that_does_not_run_code_in_docker_is_made_without_docker(
        self, machine: TestClient, docker: FakeDocker
    ) -> None:
        docker.configure(daemon="down")

        assert machine.post("/api/chats", json={"team": []}).status_code == 201

    def test_where_the_page_asks_for_no_setup_check_a_conversation_is_made_without_one(
        self, workspace: Workspace, docker: FakeDocker
    ) -> None:
        docker.configure(daemon="down")
        unchecked = create_app(
            workspace.root, token=TOKEN, check_keys=False, check_setup=False, docker_command=docker.command
        )

        with TestClient(unchecked, base_url=LOCAL, headers=BEARER) as opened:
            made = opened.post("/api/chats", json={"team": [], "code": {"where": "docker", "sandbox": "bio"}})

        assert made.status_code == 201

    @pytest.mark.parametrize(
        "code",
        [
            {"data_lake": "relative"},
            {"data_lake": 3},
            {"forward_env": ["PATH"]},
            {"forward_env": "ANTHROPIC_API_KEY"},
            {"forward_env": ["not a name"]},
        ],
    )
    def test_a_conversations_code_that_cannot_be_given_what_it_asks_for_is_refused(
        self, machine: TestClient, docker: FakeDocker, code: dict[str, Any]
    ) -> None:
        docker.configure(images=[sandbox_image("bio")])

        response = machine.post("/api/chats", json={"team": [], "code": {"where": "docker", "sandbox": "bio", **code}})

        assert response.status_code == 422
        assert error_of(response)["code"] == "invalid"
        assert machine.get("/api/chats").json() == {"chats": []}

    def test_a_conversations_data_lake_path_that_is_too_long_is_refused_for_its_length(
        self, machine: TestClient
    ) -> None:
        code = {"where": "docker", "sandbox": "bio", "data_lake": "/" + "x" * (MAX_PATH_CHARS + 1)}

        response = machine.post("/api/chats", json={"team": [], "code": code})

        assert response.status_code == 422
        assert [item["field"] for item in error_of(response)["fields"]] == ["code.data_lake"]

    def test_the_setup_is_for_the_person_with_the_token(self, workspace: Workspace, docker: FakeDocker) -> None:
        guarded = create_app(workspace.root, token=TOKEN, check_keys=False, docker_command=docker.command)

        with TestClient(guarded, base_url=LOCAL) as anonymous:
            for method, path in [
                ("GET", "/api/setup"),
                ("POST", "/api/setup/images/base"),
                ("GET", "/api/setup/data-lake"),
                ("POST", "/api/setup/data-lake"),
                ("GET", "/api/setup/jobs"),
                ("GET", "/api/setup/jobs/x"),
                ("POST", "/api/setup/jobs/x/stop"),
            ]:
                response = anonymous.request(method, path)
                assert response.status_code == 401, path
        assert docker.builds == []

    def test_a_page_of_another_address_may_not_start_a_build_or_a_fetch(
        self, machine: TestClient, docker: FakeDocker, bucket: Bucket
    ) -> None:
        evil = {"Origin": "http://evil.example"}

        assert machine.post("/api/setup/images/base", headers=evil).status_code == 403
        assert machine.post("/api/setup/data-lake", headers=evil).status_code == 403
        assert machine.post("/api/setup/jobs/x/stop", headers=evil).status_code == 403
        assert docker.builds == []
        assert bucket.requests == []

    def test_jobs_that_are_running_when_the_server_stops_are_stopped_with_it(
        self, workspace: Workspace, docker: FakeDocker, bucket: Bucket
    ) -> None:
        docker.build(wait=True, ignore_term=False)
        made = create_app(
            workspace.root, token=TOKEN, check_keys=False, docker_command=docker.command, release_url=bucket.url
        )

        with TestClient(made, base_url=LOCAL, headers=BEARER) as opened:
            job = made.state.setup.jobs.get(opened.post("/api/setup/images/base").json()["id"])
            wait_for(lambda: docker.started)
            assert job.active

        assert job.state == "stopped"
        assert docker.images == []


class TestScientists:
    EXPERT = {"title": "Nanobody Engineer", "expertise": "nanobodies", "goal": "design binders", "role": "propose"}

    def test_the_library_is_shown_with_those_the_person_described(self, client: TestClient) -> None:
        before = client.get("/api/scientists").json()["scientists"]
        assert all(item["builtin"] for item in before)

        after = client.put("/api/scientists", json=self.EXPERT).json()["scientists"]

        assert len(after) == len(before) + 1
        assert {**self.EXPERT, "builtin": False} in after
        assert client.get("/api/scientists").json()["scientists"] == after

    def test_a_scientist_that_is_described_again_is_replaced(self, client: TestClient) -> None:
        client.put("/api/scientists", json=self.EXPERT)

        after = client.put("/api/scientists", json={**self.EXPERT, "title": "nanobody ENGINEER", "role": "new"}).json()

        mine = [item for item in after["scientists"] if not item["builtin"]]
        assert [item["role"] for item in mine] == ["new"]

    def test_a_scientist_with_a_part_missing_is_refused(self, client: TestClient) -> None:
        for body in (
            {**self.EXPERT, "goal": ""},
            {**self.EXPERT, "goal": "  "},
            {"title": "Only a title"},
            {**self.EXPERT, "extra": 1},
        ):
            response = client.put("/api/scientists", json=body)
            assert response.status_code == 422, body
            assert error_of(response)["code"] == "invalid"

    def test_a_scientist_the_person_described_is_removed_and_the_librarys_cannot_be(self, client: TestClient) -> None:
        client.put("/api/scientists", json=self.EXPERT)

        removed = client.delete("/api/scientists/nanobody engineer")

        assert removed.status_code == 200
        assert all(item["builtin"] for item in removed.json()["scientists"])
        for title in ("Nanobody Engineer", "Principal Investigator", "Immunologist"):
            response = client.delete(f"/api/scientists/{title}")
            assert response.status_code == 404, title
        assert any(item["title"] == "Immunologist" for item in client.get("/api/scientists").json()["scientists"])

    def test_one_the_person_described_that_stands_in_place_of_the_librarys_is_given_up_for_it(
        self, client: TestClient
    ) -> None:
        client.put("/api/scientists", json={**self.EXPERT, "title": "Immunologist", "role": "mine"})

        client.delete("/api/scientists/Immunologist")

        immunologist = next(
            item for item in client.get("/api/scientists").json()["scientists"] if item["title"] == "Immunologist"
        )
        assert immunologist["builtin"] is True
        assert immunologist["role"] != "mine"


class TestChats:
    def test_a_conversation_is_made_from_what_the_request_gives_and_the_settings_for_the_rest(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/api/chats",
            json={
                "title": "Nanobodies",
                "team": ["Scientific Critic", "Immunologist"],
                "lead": "Principal Investigator",
                "code": {"resources": "all"},
                "max_cost": 1.25,
                "commercial_mode": True,
            },
        )

        assert response.status_code == 201
        made = response.json()
        assert made["title"] == "Nanobodies"
        assert made["state"] == "idle"
        assert made["team"] == ["Scientific Critic", "Immunologist"]
        assert made["lead"] == "Principal Investigator"
        assert made["max_cost"] == 1.25
        assert made["turns"] == 0 and made["last_event_id"] == 0
        assert made["config"]["model"] == TEST_MODEL
        assert made["config"]["code"]["resources"] == "all"
        assert made["config"]["commercial_mode"] is True
        assert made["config"]["stream"] is True

    def test_what_a_new_conversation_leaves_out_is_what_the_settings_say_and_null_is_no_limit(
        self, client: TestClient
    ) -> None:
        client.patch("/api/settings", json={"max_cost": 2.0, "stream": False})

        left_out = client.post("/api/chats", json={"team": []}).json()
        unlimited = client.post("/api/chats", json={"team": [], "max_cost": None}).json()

        assert (left_out["max_cost"], left_out["config"]["stream"]) == (2.0, False)
        assert unlimited["max_cost"] is None

    def test_a_conversation_made_with_nothing_has_the_leader_and_the_default_team(self, client: TestClient) -> None:
        made = client.post("/api/chats", json={}).json()

        assert made["lead"] == "Principal Investigator"
        assert made["team"][0] == "Scientific Critic"
        assert len(made["team"]) > 3

    @pytest.mark.parametrize(
        "body",
        [
            {"team": ["Alchemist"]},
            {"code": {"where": "cloud"}},
            {"model": "no-such-model"},
            {"max_cost": -5},
            {"lead": "Principal Investigator", "team": ["Principal Investigator"]},
            {"lead": {"title": "T", "expertise": "e", "goal": "g", "role": "r"}, "team": [{"title": "t"}]},
        ],
    )
    def test_a_conversation_that_cannot_be_made_is_refused_and_leaves_nothing(
        self, client: TestClient, workspace: Workspace, body: dict[str, Any]
    ) -> None:
        response = client.post("/api/chats", json=body)

        assert response.status_code == 422, response.text
        assert error_of(response)["code"] == "invalid"
        assert list(workspace.chats_dir.iterdir()) == []

    def test_a_lead_and_a_team_may_be_described_instead_of_chosen(self, client: TestClient) -> None:
        described = {"expertise": "e", "goal": "g", "role": "r"}

        made = client.post(
            "/api/chats",
            json={"lead": {"title": "Lead", **described}, "team": [{"title": "Other", **described}, "Immunologist"]},
        )

        assert made.status_code == 201
        assert made.json()["lead"] == "Lead"
        assert made.json()["team"] == ["Other", "Immunologist"]

    def test_conversations_are_listed_latest_first(self, client: TestClient, fake_client: FakeClient) -> None:
        first = new_chat(client, title="First")
        second = new_chat(client, title="Second")
        client.post(f"/api/chats/{first['id']}/messages", json={"text": "Hello"})
        wait_idle(client, first["id"])

        listed = client.get("/api/chats").json()["chats"]

        assert [item["id"] for item in listed] == [first["id"], second["id"]]
        assert listed[0]["turns"] == 1 and listed[1]["turns"] == 0
        assert listed[0]["state"] == "idle"

    def test_a_conversation_is_shown_by_its_id(self, client: TestClient) -> None:
        made = new_chat(client, title="Shown")

        shown = client.get(f"/api/chats/{made['id']}")

        assert shown.status_code == 200
        assert shown.json() == made

    @pytest.mark.parametrize("chat_id", ["nothing", "..", "a%2fb", ".hidden", "x" * 300])
    def test_there_is_none_with_an_id_that_is_not_one(self, client: TestClient, chat_id: str) -> None:
        for method, suffix, body in [
            ("GET", "", None),
            ("PATCH", "", {"title": "x"}),
            ("DELETE", "", None),
            ("POST", "/messages", {"text": "x"}),
            ("POST", "/note", {"text": "x"}),
            ("POST", "/stop", None),
            ("GET", "/files", None),
            ("GET", "/files/x.txt", None),
            ("GET", "/events", None),
            ("GET", "/export", None),
            ("GET", "/export?format=pdf", None),
            ("POST", "/uploads?name=x", None),
        ]:
            response = client.request(method, f"/api/chats/{chat_id}{suffix}", json=body)
            assert response.status_code == 404, (method, suffix)
            assert error_of(response)["code"] == "not_found"

    def test_a_conversation_is_renamed(self, client: TestClient, app: FastAPI) -> None:
        made = new_chat(client, title="Before")

        response = client.patch(f"/api/chats/{made['id']}", json={"title": "  After \n all "})

        assert response.status_code == 200
        assert response.json()["title"] == "After all"
        assert client.get("/api/chats").json()["chats"][0]["title"] == "After all"
        events = handle_of(app, made["id"]).chat.events_since(0)
        assert [event.text for event in events if event.kind == "title"] == ["After all"]

    def test_a_title_is_kept_short_and_may_not_be_empty(self, client: TestClient) -> None:
        made = new_chat(client)

        assert len(client.patch(f"/api/chats/{made['id']}", json={"title": "word " * 100}).json()["title"]) <= 80
        for body in ({"title": ""}, {"title": "   \n "}, {}, {"title": 5}, {"title": "x", "other": 1}):
            response = client.patch(f"/api/chats/{made['id']}", json=body)
            assert response.status_code == 422, body

    def test_a_conversation_is_removed_with_everything_it_saved(self, client: TestClient, workspace: Workspace) -> None:
        made = new_chat(client)

        response = client.delete(f"/api/chats/{made['id']}")

        assert response.status_code == 204
        assert response.content == b""
        assert client.get(f"/api/chats/{made['id']}").status_code == 404
        assert client.get("/api/chats").json() == {"chats": []}
        assert list(workspace.chats_dir.iterdir()) == []
        assert client.delete(f"/api/chats/{made['id']}").status_code == 404


class TestLimits:
    def test_a_conversation_may_be_made_with_limits_of_its_own(self, client: TestClient) -> None:
        made = client.post("/api/chats", json={"team": [], "max_cost": 3, "max_delegations": 1, "max_rounds": 0}).json()

        assert (made["max_cost"], made["max_delegations"], made["max_rounds"]) == (3.0, 1, 0)
        assert made["config"]["max_delegations"] == 1 and made["config"]["max_rounds"] == 0

    def test_a_conversation_made_with_none_has_the_leads_own_limits(self, client: TestClient) -> None:
        made = new_chat(client)

        assert (made["max_delegations"], made["max_rounds"]) == (3, 3)
        assert made["config"]["max_delegations"] is None and made["config"]["max_rounds"] is None

    def test_the_limits_are_changed_kept_and_carried_on_when_it_is_opened_again(
        self, client: TestClient, app: FastAPI, workspace: Workspace
    ) -> None:
        made = new_chat(client, max_cost=1.0)
        url = f"/api/chats/{made['id']}/limits"

        changed = client.put(url, json={"max_cost": 7.5, "max_delegations": 5, "max_rounds": 2})

        assert changed.status_code == 200, changed.text
        shown = changed.json()
        assert (shown["max_cost"], shown["max_delegations"], shown["max_rounds"]) == (7.5, 5, 2)
        assert shown["config"]["max_cost"] == 7.5 and shown["config"]["max_delegations"] == 5
        assert client.get("/api/chats").json()["chats"][0]["max_cost"] == 7.5

        close_conversations(app)
        reopened = client.get(f"/api/chats/{made['id']}").json()
        assert (reopened["max_cost"], reopened["max_delegations"], reopened["max_rounds"]) == (7.5, 5, 2)
        assert reopened["config"]["max_rounds"] == 2

    def test_only_what_is_given_is_changed_and_null_is_no_spending_limit_or_the_leads_own(
        self, client: TestClient
    ) -> None:
        made = new_chat(client, max_cost=1.0, max_delegations=7)
        url = f"/api/chats/{made['id']}/limits"

        assert client.put(url, json={"max_rounds": 1}).json()["max_cost"] == 1.0
        assert client.put(url, json={"max_rounds": 1}).json()["max_delegations"] == 7

        cleared = client.put(url, json={"max_cost": None, "max_delegations": None}).json()

        assert cleared["max_cost"] is None and cleared["max_delegations"] == 3 and cleared["max_rounds"] == 1
        assert cleared["config"]["max_delegations"] is None

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"max_cost": -1},
            {"max_cost": "plenty"},
            {"max_cost": 1e999},
            {"max_delegations": -1},
            {"max_delegations": 21},
            {"max_delegations": 1.5},
            {"max_delegations": True},
            {"max_rounds": 11},
            {"max_rounds": "2"},
            {"max_cost": 1, "colour": "red"},
        ],
    )
    def test_a_limit_that_is_not_one_is_refused_and_nothing_is_changed(self, client: TestClient, body: Any) -> None:
        made = new_chat(client, max_cost=1.0)
        url = f"/api/chats/{made['id']}/limits"

        response = client.put(url, content=json.dumps(body), headers={"content-type": "application/json"})

        assert response.status_code == 422, response.text
        assert client.get(f"/api/chats/{made['id']}").json() == made

    def test_there_is_no_conversation_to_change_the_limits_of_if_there_is_none(self, client: TestClient) -> None:
        response = client.put("/api/chats/nothing/limits", json={"max_cost": 1})

        assert response.status_code == 404 and error_of(response)["code"] == "not_found"

    def test_the_limits_can_be_changed_while_the_conversation_works(
        self, client: TestClient, fake_client: FakeClient
    ) -> None:
        made = new_chat(client, max_cost=1.0)
        gate = hold_the_model(fake_client)
        client.post(f"/api/chats/{made['id']}/messages", json={"text": "Go"})
        wait_until(gate.reached.is_set)

        try:
            changed = client.put(f"/api/chats/{made['id']}/limits", json={"max_cost": 4})
        finally:
            gate.release()

        assert changed.status_code == 200 and changed.json()["max_cost"] == 4.0
        assert wait_idle(client, made["id"])["max_cost"] == 4.0

    def test_a_spending_limit_is_not_set_where_the_model_has_no_price(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        made = new_chat(client)

        def unpriced(*args: Any, **kwargs: Any) -> float:
            raise CostUnknownError("Prices for the model are not known")

        monkeypatch.setattr("virtual_lab.chat.compute_token_cost", unpriced)
        response = client.put(f"/api/chats/{made['id']}/limits", json={"max_cost": 2})

        assert response.status_code == 422 and error_of(response)["code"] == "unavailable"
        assert "cannot be enforced" in error_of(response)["message"]
        assert client.get(f"/api/chats/{made['id']}").json()["max_cost"] is None


def close_conversations(app: FastAPI) -> None:
    """Closes every open conversation, so that the next request opens it from what was saved."""
    app.state.conversations.close()


class TestDamagedFiles:
    def test_settings_of_the_wrong_kind_in_the_file_are_shown_as_the_defaults_and_can_be_changed(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        workspace.settings_path.write_text(
            json.dumps({"model": 123, "max_cost": "lots", "stream": "yes", "code": ["x"], "forward_keys": "ABC"})
        )

        shown = client.get("/api/settings")
        changed = client.patch("/api/settings", json={"stream": False})

        assert shown.status_code == 200 and shown.json()["max_cost"] == Settings().max_cost
        assert changed.status_code == 200
        saved = json.loads(workspace.settings_path.read_text())
        assert (saved["stream"], saved["max_cost"], saved["model"]) == (False, Settings().max_cost, Settings().model)

    def test_a_model_the_file_was_edited_to_is_said_to_be_wrong_when_it_is_used_not_when_another_setting_is_changed(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        workspace.settings_path.write_text(json.dumps({"model": "no-such-model"}))

        changed = client.patch("/api/settings", json={"stream": False})
        begun = client.post("/api/chats", json={"team": []})

        assert changed.status_code == 200 and changed.json()["model"] == "no-such-model"
        assert begun.status_code == 422
        assert error_of(begun)["code"] == "invalid" and "no-such-model" in error_of(begun)["message"]
        assert list(workspace.chats_dir.iterdir()) == []

    @pytest.mark.parametrize(
        ("name", "content", "said"),
        [
            ("chat.json", "[]", "chat.json cannot be used"),
            ("chat.json", "{oops", "chat.json cannot be read"),
            ("chat.json", '{"turns": "many"}', "its turns should be a whole number"),
            ("events.jsonl", "[]\n", "events.jsonl is not a JSON object"),
            ("events.jsonl", "5\n", "events.jsonl is not a JSON object"),
            ("events.jsonl", "{}\n", "Event 1 of"),
            ("messages.jsonl", "[]\n", "messages.jsonl is not a JSON object"),
            ("messages.jsonl", '{"x": 1}\n', "it has no role"),
        ],
    )
    def test_a_conversation_whose_files_hold_what_it_does_not_save_is_said_to_be_unusable_and_can_be_deleted(
        self, client: TestClient, app: FastAPI, workspace: Workspace, name: str, content: str, said: str
    ) -> None:
        damaged = new_chat(client)
        other = new_chat(client)
        close_conversations(app)
        (workspace.chats_dir / damaged["id"] / name).write_text(content)
        url = f"/api/chats/{damaged['id']}"

        for response in (
            client.get(url),
            client.get(f"{url}/files"),
            client.post(f"{url}/messages", json={"text": "Hello"}),
        ):
            assert response.status_code == 422, response.text
            assert error_of(response)["code"] == "unavailable"
            assert said in error_of(response)["message"]
            assert name in error_of(response)["message"] or name.split(".")[0] in error_of(response)["message"]
        assert client.get(f"/api/chats/{other['id']}").status_code == 200
        assert client.delete(url).status_code == 204
        assert [item["id"] for item in client.get("/api/chats").json()["chats"]] == [other["id"]]

    def test_a_list_of_conversations_is_shown_whatever_one_of_them_saved_in_its_details(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        fine = new_chat(client)
        odd = new_chat(client)
        for index, details in enumerate(
            [
                {"title": 5, "created_at": [], "updated_at": 5, "turns": "x", "spent": "NaN", "max_cost": True},
                {"updated_at": None, "turns": -3, "spent": float("nan"), "max_cost": float("inf")},
            ]
        ):
            path = workspace.chats_dir / odd["id"] / "chat.json"
            path.write_text(json.dumps(details))

            response = client.get("/api/chats")

            assert response.status_code == 200, (index, response.text)
            by_id = {item["id"]: item for item in response.json()["chats"]}
            assert set(by_id) == {fine["id"], odd["id"]}
            assert by_id[odd["id"]]["title"] == ""
            assert by_id[odd["id"]]["created_at"] is None and by_id[odd["id"]]["updated_at"] is None
            assert by_id[odd["id"]]["turns"] == 0
            assert by_id[odd["id"]]["spent"] is None and by_id[odd["id"]]["max_cost"] is None

    @pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="Root can write anywhere")
    def test_a_workspace_that_cannot_be_written_to_is_said_so_with_the_file_and_what_to_check(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        workspace.root.chmod(0o500)
        try:
            settings = client.patch("/api/settings", json={"stream": False})
            scientist = client.put("/api/scientists", json={"title": "T", "expertise": "e", "goal": "g", "role": "r"})
        finally:
            workspace.root.chmod(0o700)

        for response, file in ((settings, "settings.json"), (scientist, "scientists.json")):
            assert response.status_code == 500, response.text
            assert error_of(response)["code"] == "files"
            assert error_of(response)["message"].startswith(f"The server could not use {workspace.root}")
            assert f"{file}: Permission denied" in error_of(response)["message"]
            assert "can be changed by whoever started the server" in error_of(response)["message"]
        assert workspace.load_settings().stream is True
        assert not [item for item in workspace.root.iterdir() if item.name.endswith(".part")]

    @pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="Root can write anywhere")
    def test_a_conversation_cannot_be_begun_in_a_directory_that_cannot_be_written_to_and_leaves_nothing(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        workspace.chats_dir.chmod(0o500)
        try:
            response = client.post("/api/chats", json={"team": []})
        finally:
            workspace.chats_dir.chmod(0o700)

        assert response.status_code == 500
        assert error_of(response)["code"] == "files"
        assert "Permission denied" in error_of(response)["message"]
        assert list(workspace.chats_dir.iterdir()) == []

    @pytest.mark.parametrize(
        ("number", "hinted"),
        [(errno.EACCES, True), (errno.EPERM, True), (errno.EROFS, True), (errno.ENOSPC, False), (errno.ENOENT, False)],
    )
    def test_only_an_error_of_not_being_let_to_change_a_file_says_what_to_check(
        self, number: int, hinted: bool
    ) -> None:
        problem = file_error(OSError(number, os.strerror(number), "/the/workspace/tools.json"))

        assert problem is not None and (problem.status, problem.code) == (500, "files")
        assert problem.message.startswith(f"The server could not use /the/workspace/tools.json: {os.strerror(number)}.")
        assert ("Check that the workspace can be changed" in problem.message) is hinted

    def test_an_error_with_no_file_in_it_is_not_one_about_a_file(self) -> None:
        assert file_error(ConnectionResetError("reset")) is None
        assert file_error(OSError(errno.EACCES, "Permission denied")) is None

    def test_an_error_about_a_file_is_told_with_its_name_and_any_other_is_not_told_to_the_page(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        failures: list[OSError] = [
            OSError(errno.ENOSPC, "No space left on device", "/the/workspace/settings.json"),
            ConnectionResetError("secret detail of the machine"),
        ]

        def broken() -> None:
            raise failures.pop(0)

        monkeypatch.setattr(app.state.conversations, "summaries", broken)

        with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
            with TestClient(app, base_url=LOCAL, headers=BEARER, raise_server_exceptions=False) as quiet:
                full = quiet.get("/api/chats")
                other = quiet.get("/api/chats")

        assert full.status_code == 500 and error_of(full)["code"] == "files"
        assert error_of(full)["message"] == (
            "The server could not use /the/workspace/settings.json: No space left on device."
        )
        assert other.status_code == 500 and error_of(other)["code"] == "internal"
        assert "secret" not in other.text
        assert "GET /api/chats: The server could not use /the/workspace/settings.json" in caplog.text


class TestMessages:
    def test_a_message_is_answered_in_the_background(self, client: TestClient, fake_client: FakeClient) -> None:
        made = new_chat(client)
        fake_client.completions.responses.append(text_response("Nanobodies are small antibodies."))

        response = client.post(f"/api/chats/{made['id']}/messages", json={"text": "What is a nanobody?"})

        assert response.status_code == 202
        assert response.json()["turn"] == 1
        info = wait_idle(client, made["id"])
        assert info["title"] == "What is a nanobody?"
        assert info["spent"] is not None and info["spent"] > 0
        assert info["usage"]["cost"] is not None or info["usage"]
        assert info["last_event_id"] > 2

    def test_a_message_while_the_last_is_being_answered_is_turned_away(
        self, client: TestClient, fake_client: FakeClient
    ) -> None:
        made = new_chat(client)
        gate = hold_the_model(fake_client)
        client.post(f"/api/chats/{made['id']}/messages", json={"text": "First"})
        wait_until(gate.reached.is_set)

        response = client.post(f"/api/chats/{made['id']}/messages", json={"text": "Second"})

        assert response.status_code == 409
        assert error_of(response)["code"] == "busy"
        gate.release()
        assert wait_idle(client, made["id"])["turns"] == 1

    def test_a_message_can_take_the_place_of_the_last_one(self, client: TestClient, fake_client: FakeClient) -> None:
        made = new_chat(client)
        url = f"/api/chats/{made['id']}/messages"
        refused = client.post(url, json={"text": "Hello", "replace_last": True})
        assert refused.status_code == 422 and error_of(refused)["code"] == "invalid"
        assert client.get(f"/api/chats/{made['id']}").json()["turns"] == 0

        fake_client.completions.responses.extend([text_response("Nanobodies."), text_response("Antibodies.")])
        client.post(url, json={"text": "What is a nanobody?"})
        wait_idle(client, made["id"])

        response = client.post(url, json={"text": "What is an antibody?", "replace_last": True})

        assert response.status_code == 202 and response.json()["turn"] == 1
        info = wait_idle(client, made["id"])
        assert (info["turns"], info["title"]) == (1, "What is an antibody?")
        events = handle_of(client.app, made["id"]).chat.events_since()
        assert [event.kind for event in events if event.kind in ("user", "withdrawn", "answer")] == [
            "withdrawn",
            "user",
            "answer",
        ]
        assert [event.text for event in events if event.kind in ("user", "answer")] == [
            "What is an antibody?",
            "Antibodies.",
        ]

    def test_a_message_can_be_given_with_a_command(self, client: TestClient, fake_client: FakeClient) -> None:
        made = new_chat(client)
        assert made["directives"]["ask"] is None
        fake_client.completions.responses.append(text_response("From memory."))

        response = client.post(
            f"/api/chats/{made['id']}/messages", json={"text": "What is a nanobody?", "directive": "ask"}
        )

        assert response.status_code == 202
        wait_idle(client, made["id"])
        assert "tools" not in fake_client.completions.calls[0]
        (user,) = [event for event in handle_of(client.app, made["id"]).chat.events_since() if event.kind == "user"]
        assert (user.text, user.data["directive"]) == ("What is a nanobody?", "ask")

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ({"text": "Go", "directive": "dance"}, "/dance is not a command"),
            ({"text": "", "directive": "ask"}, "/ask needs what it is for written after it"),
            ({"text": "Go", "directive": "review"}, "/review cannot be given: the Scientific Critic is not on the team"),
            ({"text": "", "directive": "review"}, "/review cannot be given"),
            ({"text": "Go", "directive": "search"}, "/search cannot be given: no literature tool"),
        ],
    )
    def test_a_command_that_cannot_be_given_is_refused(
        self, body: dict[str, Any], message: str, client: TestClient, fake_client: FakeClient
    ) -> None:
        made = new_chat(client, tools=[])

        response = client.post(f"/api/chats/{made['id']}/messages", json=body)

        assert response.status_code == 422 and error_of(response)["code"] == "invalid"
        assert message in error_of(response)["message"]
        assert client.get(f"/api/chats/{made['id']}").json()["turns"] == 0
        assert fake_client.completions.calls == []

    def test_what_a_conversation_can_be_given_as_commands_is_told_of(self, client: TestClient) -> None:
        bare = new_chat(client, tools=[])
        assert bare["directives"]["search"] == "no literature tool is turned on for this conversation"
        assert bare["directives"]["review"] == "the Scientific Critic is not on the team"

        searching = new_chat(client, tools=["pubmed_search"])
        assert searching["directives"]["search"] is None

    def test_a_command_name_is_not_taken_for_anything_but_text(self, client: TestClient) -> None:
        made = new_chat(client)

        for directive in (5, ["ask"], "x" * 51):
            response = client.post(f"/api/chats/{made['id']}/messages", json={"text": "Go", "directive": directive})
            assert response.status_code == 422

    LAB = {"mode": "team", "members": ["Immunologist", "Nanobody Engineer"], "rounds": 0, "questions": ["Which?"]}
    ENGINEER = {"title": "Nanobody Engineer", "expertise": "nanobodies", "goal": "design binders", "role": "propose"}

    def test_a_scientist_of_the_library_who_is_chosen_for_a_lab_session_joins_the_team(
        self, client: TestClient, fake_client: FakeClient
    ) -> None:
        client.put("/api/scientists", json=self.ENGINEER)
        made = new_chat(client, team=["Immunologist", "Scientific Critic"])
        before = handle_of(client.app, made["id"])
        fake_client.completions.responses.extend(
            [
                tool_call_response("convene_team", {"agenda": "Design a binder."}),
                text_response("Together."),
                text_response("The team designed one."),
            ]
        )

        response = client.post(
            f"/api/chats/{made['id']}/messages", json={"text": "Design", "directive": "lab", "lab": self.LAB}
        )

        assert response.status_code == 202
        info = wait_idle(client, made["id"])
        assert [member["title"] for member in info["config"]["team"]] == [
            "Immunologist",
            "Scientific Critic",
            "Nanobody Engineer",
        ]
        after = handle_of(client.app, made["id"])
        assert after is not before
        events = after.chat.events_since()
        (user,) = [event for event in events if event.kind == "user"]
        assert user.data["lab"] == self.LAB and user.data["directive"] == "lab"
        assert [event.data["directive_met"] for event in events if event.kind == "answer"] == [True]
        # The team is kept, so the lead may bring them in later too
        assert [member["title"] for member in client.get(f"/api/chats/{made['id']}").json()["config"]["team"]][-1] == (
            "Nanobody Engineer"
        )

    def test_a_conversation_is_not_opened_again_when_those_chosen_are_on_its_team(
        self, client: TestClient, fake_client: FakeClient
    ) -> None:
        made = new_chat(client, team=["Immunologist", "Scientific Critic"])
        before = handle_of(client.app, made["id"])
        fake_client.completions.responses.extend(
            [tool_call_response("convene_team", {"agenda": "Go."}), text_response("Alone."), text_response("Done.")]
        )

        client.post(
            f"/api/chats/{made['id']}/messages",
            json={"text": "Go", "directive": "lab", "lab": {"members": ["immunologist"], "rounds": 0}},
        )

        wait_idle(client, made["id"])
        assert handle_of(client.app, made["id"]) is before

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ({"directive": "lab"}, "/lab needs who is to work on it chosen"),
            ({"lab": {"members": ["Immunologist"]}}, "chosen only with /lab"),
            ({"directive": "ask", "lab": {"members": ["Immunologist"]}}, "chosen only with /lab"),
            ({"directive": "lab", "lab": {"members": []}}, "at least one scientist"),
            ({"directive": "lab", "lab": {"members": ["Astrologer"]}}, 'There is no scientist titled "Astrologer"'),
            ({"directive": "lab", "lab": {"members": ["Nobody Here"]}}, "There is no scientist titled"),
            (
                {"directive": "lab", "lab": {"mode": "individual", "members": ["Scientific Critic"]}},
                "reviews, so choose another",
            ),
            ({"directive": "lab", "lab": {"members": ["Immunologist"], "rounds": 4}}, "at most 3 round"),
        ],
    )
    def test_a_lab_session_that_cannot_be_asked_for_is_refused_and_the_team_is_left_as_it_was(
        self, body: dict[str, Any], message: str, client: TestClient, fake_client: FakeClient
    ) -> None:
        made = new_chat(client, team=["Immunologist", "Scientific Critic"])

        response = client.post(f"/api/chats/{made['id']}/messages", json={"text": "Go", **body})

        assert response.status_code == 422 and error_of(response)["code"] == "invalid"
        assert message in error_of(response)["message"]
        info = client.get(f"/api/chats/{made['id']}").json()
        assert info["turns"] == 0 and len(info["config"]["team"]) == 2
        assert fake_client.completions.calls == []

    @pytest.mark.parametrize(
        "lab",
        [
            {"members": ["Immunologist"], "rounds": 11},
            {"members": ["Immunologist"], "rounds": 1.5},
            {"members": ["Immunologist"], "rounds": True},
            {"members": ["Immunologist"], "mode": "crowd"},
            {"members": "Immunologist"},
            {"members": ["x" * 201]},
            {"members": ["Immunologist"] * 51},
            {"members": ["Immunologist"], "questions": ["q"] * 11},
            {"members": ["Immunologist"], "extra": 1},
        ],
    )
    def test_the_choice_of_who_works_on_it_is_checked_for_its_shape(self, lab: dict[str, Any], client: TestClient) -> None:
        made = new_chat(client, team=["Immunologist", "Scientific Critic"])

        response = client.post(f"/api/chats/{made['id']}/messages", json={"text": "Go", "directive": "lab", "lab": lab})

        assert response.status_code == 422

    def test_a_conversation_that_is_working_does_not_take_scientists_onto_its_team(
        self, client: TestClient, fake_client: FakeClient
    ) -> None:
        made = new_chat(client, team=["Immunologist", "Scientific Critic"])
        gate = hold_the_model(fake_client)
        client.post(f"/api/chats/{made['id']}/messages", json={"text": "Think"})
        assert gate.reached.wait(10)

        refused = client.post(
            f"/api/chats/{made['id']}/messages",
            json={"text": "Go", "directive": "lab", "lab": {"members": ["Geneticist"], "rounds": 0}},
        )

        assert refused.status_code == 409 and error_of(refused)["code"] == "busy"
        assert len(client.get(f"/api/chats/{made['id']}").json()["config"]["team"]) == 2
        gate.release()
        wait_idle(client, made["id"])

    @pytest.mark.parametrize(
        "body",
        [{}, {"text": ""}, {"text": "  \n "}, {"text": "x", "attachments": ["missing.csv"]}, {"attachments": ["a"]}],
    )
    def test_a_message_with_nothing_in_it_or_a_file_that_was_not_attached_is_refused(
        self, client: TestClient, body: dict[str, Any]
    ) -> None:
        made = new_chat(client)

        response = client.post(f"/api/chats/{made['id']}/messages", json=body)

        assert response.status_code == 422
        assert error_of(response)["code"] == "invalid"
        assert client.get(f"/api/chats/{made['id']}").json()["turns"] == 0

    def test_a_message_that_is_too_long_or_not_as_asked_is_refused(self, client: TestClient) -> None:
        made = new_chat(client)

        for body in (
            {"text": "x" * (MAX_MESSAGE_CHARS + 1)},
            {"text": 5},
            {"text": "x", "attachments": "a.csv"},
            {"text": "x", "attachments": ["a"] * 101},
            {"text": "x", "mood": "hurried"},
        ):
            assert client.post(f"/api/chats/{made['id']}/messages", json=body).status_code == 422

    def test_a_message_is_not_taken_when_the_key_its_model_needs_is_not_set(
        self, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LLM_SOURCE", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        app = create_app(workspace.root, token=TOKEN)
        with TestClient(app, base_url=LOCAL, headers=BEARER) as client:
            made = new_chat(client)
            client.app.state.conversations.close()  # type: ignore[attr-defined]
            monkeypatch.delenv("OPENAI_API_KEY")

            response = client.post(f"/api/chats/{made['id']}/messages", json={"text": "Hello"})
            created = client.post("/api/chats", json={"team": []})
            read = client.get(f"/api/chats/{made['id']}")

        assert response.status_code == 422
        assert error_of(response)["code"] == "missing_keys"
        assert error_of(response)["missing"] == ["OPENAI_API_KEY"]
        assert created.status_code == 422 and error_of(created)["code"] == "missing_keys"
        # What was said before can still be read
        assert read.status_code == 200

    def test_a_conversation_closed_while_a_message_is_sent_is_told_so(self, client: TestClient, app: FastAPI) -> None:
        made = new_chat(client)
        handle_of(app, made["id"]).chat.close()

        response = client.post(f"/api/chats/{made['id']}/messages", json={"text": "Hello"})

        assert response.status_code == 409
        assert error_of(response)["code"] == "closed"


class TestSteering:
    def test_steering_a_conversation_that_is_not_working_is_not_accepted(self, client: TestClient) -> None:
        made = new_chat(client)

        for action, body in (("note", {"text": "Also this"}), ("pause", None), ("resume", None), ("stop", None)):
            response = client.post(f"/api/chats/{made['id']}/{action}", json=body)
            assert response.status_code == 200, action
            assert response.json() == {"accepted": False}, action

    def test_a_turn_is_paused_noted_resumed_and_stopped(self, client: TestClient, fake_client: FakeClient) -> None:
        made = new_chat(client)
        gate = hold_the_model(fake_client)
        client.post(f"/api/chats/{made['id']}/messages", json={"text": "Go"})
        wait_until(gate.reached.is_set)
        url = f"/api/chats/{made['id']}"

        assert client.post(f"{url}/pause").json() == {"accepted": True}
        assert client.get(url).json()["state"] == "pausing"
        assert client.post(f"{url}/note", json={"text": "Mind the length"}).json() == {"accepted": True}
        assert client.post(f"{url}/resume").json() == {"accepted": True}
        assert client.get(url).json()["state"] == "running"
        assert client.post(f"{url}/resume").json() == {"accepted": False}
        assert client.post(f"{url}/stop").json() == {"accepted": True}
        # A model that is asked and does not answer is given up on, so the turn may already be over
        assert client.get(url).json()["state"] in ("stopping", "idle")
        gate.release()

        assert wait_idle(client, made["id"])["state"] == "idle"

    def test_stopping_does_not_wait_for_a_model_that_says_nothing(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        made = new_chat(client)
        gate = hold_the_model(fake_client)
        url = f"/api/chats/{made['id']}"
        client.post(f"{url}/messages", json={"text": "Go"})
        wait_until(gate.reached.is_set)

        try:
            assert client.post(f"{url}/stop").json() == {"accepted": True}
            info = wait_idle(client, made["id"])
            kinds = [event.kind for event in handle_of(app, made["id"]).chat.events_since(0)]
        finally:
            gate.release()

        assert info["state"] == "idle"
        assert "stopped" in kinds and "failed" not in kinds

    def test_a_note_needs_something_in_it(self, client: TestClient) -> None:
        made = new_chat(client)

        for body in ({}, {"text": ""}, {"text": 5}, {"text": "x", "more": 1}):
            assert client.post(f"/api/chats/{made['id']}/note", json=body).status_code == 422

    def test_steering_a_conversation_there_is_none_of_is_not_found(self, client: TestClient) -> None:
        for action in ("note", "pause", "resume", "stop"):
            assert client.post(f"/api/chats/nothing/{action}", json={"text": "x"}).status_code == 404


class TestUploads:
    def upload(self, client: TestClient, chat_id: str, name: str, content: Any) -> httpx.Response:
        return client.post(f"/api/chats/{chat_id}/uploads", params={"name": name}, content=content)

    def test_a_file_is_kept_with_the_conversation_and_listed_and_read_back(self, client: TestClient) -> None:
        made = new_chat(client)

        response = self.upload(client, made["id"], "data.csv", b"a,b\n1,2\n")

        assert response.status_code == 201
        assert response.json() == {"name": "data.csv", "path": "uploads/data.csv", "size": 8}
        listed = client.get(f"/api/chats/{made['id']}/files").json()
        assert [item["path"] for item in listed["files"]] == ["uploads/data.csv"]
        assert listed["files"][0]["type"] == "text/csv" and listed["files"][0]["size"] == 8
        assert listed["truncated"] is False
        read = client.get(f"/api/chats/{made['id']}/files/uploads/data.csv")
        assert read.content == b"a,b\n1,2\n"
        assert read.headers["content-type"].startswith("text/csv")

    def test_a_file_is_never_replaced_and_the_same_file_is_not_kept_twice(self, client: TestClient) -> None:
        made = new_chat(client)

        names = [
            self.upload(client, made["id"], "data.csv", content).json()["name"]
            for content in (b"one", b"two", b"one", b"two", b"three")
        ]

        assert names == ["data.csv", "data (2).csv", "data.csv", "data (2).csv", "data (3).csv"]
        assert len(client.get(f"/api/chats/{made['id']}/files").json()["files"]) == 3

    @pytest.mark.parametrize(
        ("name", "saved"),
        [
            ("../../outside.txt", "outside.txt"),
            ("..\\..\\outside.txt", "outside.txt"),
            ("/etc/passwd", "passwd"),
            (".hidden", "hidden"),
            ("a\x00b\nc.txt", "abc.txt"),
            ("..", "upload"),
        ],
    )
    def test_a_name_that_would_leave_the_uploads_is_made_safe(
        self, client: TestClient, workspace: Workspace, name: str, saved: str
    ) -> None:
        made = new_chat(client)

        response = self.upload(client, made["id"], name, b"x")

        assert response.status_code == 201
        assert response.json()["name"] == saved
        assert not (workspace.root / "outside.txt").exists()
        assert not (workspace.chats_dir / "outside.txt").exists()

    def test_an_empty_file_is_kept_and_a_name_is_needed(self, client: TestClient) -> None:
        made = new_chat(client)

        assert self.upload(client, made["id"], "empty.txt", b"").json()["size"] == 0
        for params in ({}, {"name": ""}, {"name": "x" * 1001}):
            response = client.post(f"/api/chats/{made['id']}/uploads", params=params, content=b"x")
            assert response.status_code == 422

    def test_a_file_that_says_it_is_too_large_is_refused_without_a_byte_of_it_being_read(
        self, client: TestClient, app: FastAPI
    ) -> None:
        made = new_chat(client)
        handle_of(app, made["id"]).chat.max_upload_bytes = 5

        sent = asyncio.run(
            call_app(
                app,
                "POST",
                f"/api/chats/{made['id']}/uploads",
                "name=big.bin",
                {"content-length": "6"},
                lambda: fail("The body was read"),
            )
        )

        assert sent[0]["status"] == 413
        assert json.loads(sent[1]["body"])["error"]["code"] == "too_large"

    def test_a_file_exactly_as_large_as_may_be_attached_is_kept(self, client: TestClient, app: FastAPI) -> None:
        made = new_chat(client)
        handle_of(app, made["id"]).chat.max_upload_bytes = 5

        assert self.upload(client, made["id"], "fits.bin", b"01234").status_code == 201
        assert self.upload(client, made["id"], "over.bin", b"012345").status_code == 413

    def test_a_sender_that_goes_away_part_of_the_way_is_not_an_error_of_the_server(
        self, client: TestClient, app: FastAPI
    ) -> None:
        made = new_chat(client)
        messages = iter([{"type": "http.request", "body": b"abc", "more_body": True}, {"type": "http.disconnect"}])

        sent = asyncio.run(
            call_app(app, "POST", f"/api/chats/{made['id']}/uploads", "name=cut.bin", {}, lambda: next(messages))
        )

        assert [message["status"] for message in sent if message["type"] == "http.response.start"] == [499]
        assert self.leftovers(handle_of(app, made["id"])) == []

    def test_a_file_that_is_too_large_is_refused_before_it_is_read_and_leaves_nothing(
        self, client: TestClient, app: FastAPI, workspace: Workspace
    ) -> None:
        made = new_chat(client)
        handle_of(app, made["id"]).chat.max_upload_bytes = 5

        response = self.upload(client, made["id"], "big.bin", b"0123456789")

        assert response.status_code == 413
        assert error_of(response)["code"] == "too_large"
        assert self.leftovers(handle_of(app, made["id"])) == []

    def test_a_file_that_proves_too_large_as_it_arrives_is_refused_and_leaves_nothing(
        self, client: TestClient, app: FastAPI
    ) -> None:
        made = new_chat(client)
        handle_of(app, made["id"]).chat.max_upload_bytes = 5

        # With no length announced, which is how a body of unknown length is sent
        response = self.upload(client, made["id"], "big.bin", iter([b"abc", b"defg"]))

        assert response.status_code == 413
        assert error_of(response)["code"] == "too_large"
        assert self.leftovers(handle_of(app, made["id"])) == []

    def leftovers(self, handle: Any) -> list[str]:
        directory = handle.chat.uploads_dir
        return sorted(path.name for path in directory.iterdir()) if directory.exists() else []

    def test_a_file_is_attached_to_a_message_and_told_to_the_lead(
        self, client: TestClient, app: FastAPI, fake_client: FakeClient
    ) -> None:
        made = new_chat(client)
        attached = self.upload(client, made["id"], "data.csv", b"a,b\n").json()
        fake_client.completions.responses.append(text_response("I cannot open it here."))

        client.post(f"/api/chats/{made['id']}/messages", json={"text": "Look", "attachments": [attached["name"]]})
        wait_idle(client, made["id"])

        user = next(event for event in handle_of(app, made["id"]).chat.events_since(0) if event.kind == "user")
        assert user.data["attachments"] == [attached]

    def test_where_code_runs_files_are_kept_where_it_reads_them_and_shown_with_what_it_made(
        self, client: TestClient, app: FastAPI
    ) -> None:
        made = new_chat(client, code={"where": "local"})
        handle = handle_of(app, made["id"])
        self.upload(client, made["id"], "data.csv", b"a,b\n")
        (handle.session.directory / "result.txt").write_text("made by code")
        (handle.session.directory / "figures").mkdir()
        (handle.session.directory / "figures" / "plot.png").write_bytes(b"\x89PNG")

        listed = client.get(f"/api/chats/{made['id']}/files").json()["files"]

        assert [item["path"] for item in listed] == ["figures/plot.png", "result.txt", "uploads/data.csv"]
        assert (handle.session.directory / "uploads" / "data.csv").is_file()

    def test_a_file_arrives_whole_whatever_its_size(self, app: FastAPI) -> None:
        content = os.urandom(3 * 1024 * 1024 + 17)

        with serve(app) as (base, http):
            made = http.post("/api/chats", json={"team": []}).json()
            response = http.post(f"/api/chats/{made['id']}/uploads", params={"name": "big.bin"}, content=content)
            read = http.get(f"/api/chats/{made['id']}/files/uploads/big.bin", params={"download": "true"})

        assert response.json()["size"] == len(content)
        assert hashlib.sha256(read.content).hexdigest() == hashlib.sha256(content).hexdigest()
        assert read.headers["content-disposition"].startswith("attachment")

    def test_the_server_goes_on_answering_while_a_file_is_still_arriving(self, app: FastAPI) -> None:
        arrived = threading.Event()
        carry_on = threading.Event()

        def slowly() -> Iterator[bytes]:
            yield b"first part, "
            arrived.set()
            assert carry_on.wait(20)
            yield b"last part"

        with serve(app) as (base, http):
            made = http.post("/api/chats", json={"team": []}).json()
            results: list[httpx.Response] = []
            thread = threading.Thread(
                target=lambda: results.append(
                    http.post(f"/api/chats/{made['id']}/uploads", params={"name": "slow.txt"}, content=slowly())
                )
            )
            thread.start()
            assert arrived.wait(10)

            others = [httpx.get(f"{base}/api/health", timeout=5).status_code for _ in range(3)]
            carry_on.set()
            thread.join(20)

        assert others == [200, 200, 200]
        assert results[0].json()["size"] == len(b"first part, last part")

    def test_a_file_whose_sender_goes_away_leaves_nothing(self, app: FastAPI) -> None:
        def breaks() -> Iterator[bytes]:
            yield b"some of it"
            raise RuntimeError("the connection broke")

        with serve(app) as (base, http):
            made = http.post("/api/chats", json={"team": []}).json()
            with pytest.raises(RuntimeError, match="the connection broke"):
                http.post(f"/api/chats/{made['id']}/uploads", params={"name": "cut.txt"}, content=breaks())
            handle = handle_of(app, made["id"])
            time.sleep(0.3)

            assert self.leftovers(handle) == []
            assert http.get("/api/health").status_code == 200

    def test_a_file_that_stops_arriving_is_given_up_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(app_module, "UPLOAD_CHUNK_TIMEOUT", 0.2)

        class Stalled:
            async def _chunks(self) -> Any:
                yield b"abc"
                await asyncio.sleep(30)
                yield b"never"

            def stream(self) -> Any:
                return self._chunks()

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            reader = RequestBodyReader(Stalled(), loop)  # type: ignore[arg-type]
            with pytest.raises(ApiError) as caught:
                reader.read(10)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(5)

        assert (caught.value.status, caught.value.code) == (408, "timeout")

    def test_the_body_of_a_request_is_read_in_the_sizes_asked_for(self) -> None:
        class Pieces:
            async def _chunks(self) -> Any:
                for piece in (b"abc", b"", b"defgh", b"i"):
                    yield piece

            def stream(self) -> Any:
                return self._chunks()

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            reader = RequestBodyReader(Pieces(), loop)  # type: ignore[arg-type]
            read = [reader.read(2), reader.read(4), reader.read(100), reader.read(5), reader.read(-1)]
            whole = RequestBodyReader(Pieces(), loop).read(-1)
            empty = RequestBodyReader(Pieces(), loop)
            empty.read(-1)
            after = empty.read(3)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(5)

        assert read == [b"ab", b"cdef", b"ghi", b"", b""]
        assert whole == b"abcdefghi"
        assert after == b""


class TestFiles:
    def make(self, client: TestClient, app: FastAPI) -> tuple[str, Path]:
        made = new_chat(client, code={"where": "local"})
        root = handle_of(app, made["id"]).session.directory

        return made["id"], root

    def test_a_picture_is_shown_in_the_page_and_a_page_that_was_written_is_not_run(
        self, client: TestClient, app: FastAPI
    ) -> None:
        chat_id, root = self.make(client, app)
        (root / "plot.png").write_bytes(b"\x89PNG\r\n")
        (root / "report.html").write_text("<script>steal()</script>")
        (root / "plot.svg").write_text("<svg><script>steal()</script></svg>")

        png = client.get(f"/api/chats/{chat_id}/files/plot.png")
        html = client.get(f"/api/chats/{chat_id}/files/report.html")
        svg = client.get(f"/api/chats/{chat_id}/files/plot.svg")

        assert png.headers["content-type"] == "image/png"
        assert png.headers["content-disposition"].startswith("inline")
        assert html.headers["content-type"].startswith("text/plain")
        assert html.text == "<script>steal()</script>"
        for response in (png, html, svg):
            assert response.headers["x-content-type-options"] == "nosniff"
            assert "sandbox" in response.headers["content-security-policy"]
            assert "default-src 'none'" in response.headers["content-security-policy"]

    def test_a_file_can_be_asked_for_to_be_saved(self, client: TestClient, app: FastAPI) -> None:
        chat_id, root = self.make(client, app)
        (root / "plot.png").write_bytes(b"\x89PNG")

        response = client.get(f"/api/chats/{chat_id}/files/plot.png", params={"download": "true"})

        assert response.headers["content-disposition"].startswith("attachment")

    def test_a_file_in_a_folder_is_found_by_its_path(self, client: TestClient, app: FastAPI) -> None:
        chat_id, root = self.make(client, app)
        (root / "a" / "b").mkdir(parents=True)
        (root / "a" / "b" / "deep file.txt").write_text("deep")

        assert client.get(f"/api/chats/{chat_id}/files/a/b/deep%20file.txt").text == "deep"

    @pytest.mark.parametrize(
        "path",
        [
            "..%2f..%2fconfig.json",
            "%2e%2e/%2e%2e/config.json",
            "..%2fconfig.json",
            "a/../../config.json",
            "%2fetc%2fpasswd",
            "/etc/passwd",
            "link.txt",
            "folder/secret.txt",
            "nothing.txt",
            "figures",
            "figures/",
            "a%00b",
        ],
    )
    def test_nothing_outside_the_conversations_files_is_given(
        self, client: TestClient, app: FastAPI, tmp_path: Path, path: str
    ) -> None:
        chat_id, root = self.make(client, app)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("keys")
        (root / "link.txt").symlink_to(outside / "secret.txt")
        (root / "folder").symlink_to(outside, target_is_directory=True)
        (root / "figures").mkdir()

        response = client.get(f"/api/chats/{chat_id}/files/{path}")

        assert response.status_code == 404, response.text
        assert "keys" not in response.text and "model" not in response.text.lower()

    def test_a_conversation_without_a_session_shows_only_what_was_attached_to_it(self, client: TestClient) -> None:
        made = new_chat(client)
        client.post(f"/api/chats/{made['id']}/uploads", params={"name": "mine.txt"}, content=b"mine")

        for path in ("config.json", "chat.json", "messages.jsonl", "events.jsonl"):
            assert client.get(f"/api/chats/{made['id']}/files/{path}").status_code == 404, path
        assert client.get(f"/api/chats/{made['id']}/files/uploads/mine.txt").text == "mine"
        assert [item["path"] for item in client.get(f"/api/chats/{made['id']}/files").json()["files"]] == [
            "uploads/mine.txt"
        ]

    def test_a_listing_that_was_cut_short_says_so(
        self, client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chat_id, root = self.make(client, app)
        for name in ("a.txt", "b.txt", "c.txt"):
            (root / name).write_text(name)
        real = app_module.list_files
        monkeypatch.setattr(app_module, "list_files", lambda *args, **kwargs: real(*args, limit=2, **kwargs))

        listed = client.get(f"/api/chats/{chat_id}/files").json()

        assert listed["truncated"] is True
        assert len(listed["files"]) == 2

    def test_another_conversations_files_are_not_given(self, client: TestClient, app: FastAPI) -> None:
        first, root = self.make(client, app)
        second, _ = self.make(client, app)
        (root / "private.txt").write_text("first only")

        assert client.get(f"/api/chats/{first}/files/private.txt").status_code == 200
        assert client.get(f"/api/chats/{second}/files/private.txt").status_code == 404
        assert client.get(f"/api/chats/{second}/files/..%2f{first}%2fwork%2fprivate.txt").status_code == 404


class TestExport:
    def talk(self, client: TestClient, fake_client: FakeClient, **body: Any) -> str:
        made = new_chat(client, **body)
        fake_client.completions.responses.append(text_response("Nanobodies are small antibodies."))
        client.post(f"/api/chats/{made['id']}/messages", json={"text": "What is a nanobody?"})
        wait_idle(client, made["id"])

        return made["id"]

    def test_a_conversation_is_sent_as_a_page_to_be_saved(self, client: TestClient, fake_client: FakeClient) -> None:
        chat_id = self.talk(client, fake_client)

        response = client.get(f"/api/chats/{chat_id}/export")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert response.headers["content-disposition"] == (
            "attachment; filename=\"What is a nanobody.html\"; filename*=utf-8''What%20is%20a%20nanobody.html"
        )
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        assert "sandbox" in response.headers["content-security-policy"]
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert response.text.startswith("<!DOCTYPE html>")
        assert "What is a nanobody?" in response.text
        assert "Nanobodies are small antibodies." in response.text
        assert client.get(f"/api/chats/{chat_id}/export", params={"format": "html"}).content == response.content

    def test_a_conversation_is_sent_as_a_notebook(self, client: TestClient, fake_client: FakeClient) -> None:
        chat_id = self.talk(client, fake_client)

        response = client.get(f"/api/chats/{chat_id}/export", params={"format": "ipynb"})

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-ipynb+json"
        assert response.headers["content-disposition"] == (
            "attachment; filename=\"What is a nanobody.ipynb\"; filename*=utf-8''What%20is%20a%20nanobody.ipynb"
        )
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        notebook = response.json()
        assert notebook["nbformat"] == 4
        assert "What is a nanobody?" in "".join("".join(item["source"]) for item in notebook["cells"])
        assert "Nanobodies are small antibodies." in "".join("".join(item["source"]) for item in notebook["cells"])

    def test_a_conversation_is_sent_as_a_pdf_when_one_can_be_made(
        self, client: TestClient, fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chat_id = self.talk(client, fake_client)
        given: list[str] = []

        def make_pdf(page: str) -> bytes:
            given.append(page)

            return b"%PDF-1.7 a pretend one"

        monkeypatch.setattr(app_module, "make_pdf", make_pdf)

        response = client.get(f"/api/chats/{chat_id}/export", params={"format": "pdf"})

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"] == (
            "attachment; filename=\"What is a nanobody.pdf\"; filename*=utf-8''What%20is%20a%20nanobody.pdf"
        )
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.content == b"%PDF-1.7 a pretend one"
        assert len(given) == 1 and "Nanobodies are small antibodies." in given[0]

    def test_a_pdf_that_cannot_be_made_is_told_so_and_a_page_still_can_be_had(
        self, client: TestClient, fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chat_id = self.talk(client, fake_client)

        def make_pdf(page: str) -> bytes:
            raise PDFExportError("Making a PDF needs WeasyPrint. (ImportError: no module named weasyprint)")

        monkeypatch.setattr(app_module, "make_pdf", make_pdf)

        response = client.get(f"/api/chats/{chat_id}/export", params={"format": "pdf"})

        assert response.status_code == 501
        assert error_of(response) == {
            "code": "pdf_unavailable",
            "message": PDF_UNAVAILABLE,
            "reason": "Making a PDF needs WeasyPrint. (ImportError: no module named weasyprint)",
        }
        assert "print it to a PDF from the browser" in PDF_UNAVAILABLE
        assert "content-disposition" not in response.headers
        assert client.get(f"/api/chats/{chat_id}/export").status_code == 200

    @pytest.mark.parametrize("kind", ["docx", "", "HTML", "pdf,html", "html&format=pdf"])
    def test_a_kind_of_file_there_is_none_of_is_refused(
        self, client: TestClient, fake_client: FakeClient, kind: str
    ) -> None:
        chat_id = self.talk(client, fake_client)

        response = client.get(f"/api/chats/{chat_id}/export", params={"format": kind})

        assert response.status_code == 422
        assert error_of(response)["code"] == "invalid"

    def test_what_is_in_a_title_that_cannot_be_in_a_file_name_is_kept_out_of_it(
        self, client: TestClient, fake_client: FakeClient
    ) -> None:
        chat_id = self.talk(client, fake_client)
        client.patch(f"/api/chats/{chat_id}", json={"title": 'Ünïcode: 抗体 / "a" <b> \\ ..'})

        response = client.get(f"/api/chats/{chat_id}/export")

        assert response.headers["content-disposition"] == (
            "attachment; filename=\"Unicode- - -a- -b.html\"; "
            "filename*=utf-8''%C3%9Cn%C3%AFcode-%20%E6%8A%97%E4%BD%93%20-%20-a-%20-b.html"
        )

    def test_a_conversation_that_is_still_being_answered_is_saved_as_far_as_it_has_got(
        self, client: TestClient, fake_client: FakeClient
    ) -> None:
        made = new_chat(client)
        gate = hold_the_model(fake_client)
        client.post(f"/api/chats/{made['id']}/messages", json={"text": "Slow question"})
        wait_until(gate.reached.is_set)

        response = client.get(f"/api/chats/{made['id']}/export")
        gate.release()
        wait_idle(client, made["id"])

        assert response.status_code == 200
        assert "Slow question" in response.text
        assert client.get(f"/api/chats/{made['id']}").json()["turns"] == 1

    def test_a_conversation_is_saved_after_the_server_was_restarted(
        self, client: TestClient, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        chat_id = self.talk(client, fake_client)
        client.app.state.conversations.close()  # type: ignore[attr-defined]

        with TestClient(create_app(workspace.root, token=TOKEN, check_keys=False), base_url=LOCAL, headers=BEARER) as later:
            response = later.get(f"/api/chats/{chat_id}/export")

        assert response.status_code == 200
        assert "Nanobodies are small antibodies." in response.text

    def test_saving_a_conversation_does_not_change_what_it_saved(
        self, client: TestClient, fake_client: FakeClient, app: FastAPI
    ) -> None:
        chat_id = self.talk(client, fake_client)
        directory = handle_of(app, chat_id).directory
        before = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}

        for kind in ("html", "html"):
            assert client.get(f"/api/chats/{chat_id}/export", params={"format": kind}).status_code == 200

        assert {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()} == before

    def drew(self, client: TestClient, app: FastAPI, chat_id: str, tmp_path: Path) -> None:
        """Has the conversation's code draw a figure, and name another that is outside its files."""
        handle = handle_of(app, chat_id)
        (handle.files_root / "plots").mkdir()
        (handle.files_root / "plots" / "figure_1.png").write_bytes(PNG)
        (tmp_path / "outside.png").write_bytes(PNG)
        last = client.get(f"/api/chats/{chat_id}").json()["last_event_id"]
        happened = [
            ChatEvent(
                kind="tool_calls",
                id=last + 1,
                turn=1,
                speaker=None,
                text="",
                data={"calls": [{"id": "c1", "name": "run_code", "arguments": '{"code": "draw()"}'}]},
                time=0.0,
            ),
            ChatEvent(
                kind="cell",
                id=last + 2,
                turn=1,
                speaker=None,
                text="",
                data={
                    "call": "c1",
                    "language": "python",
                    "code": "draw()",
                    "status": "ok",
                    "output": "",
                    "duration": 0.1,
                    "plots": ["plots/figure_1.png", "../../../outside.png"],
                },
                time=0.0,
            ),
        ]
        with (handle.directory / "events.jsonl").open("a", encoding="utf-8") as saved:
            saved.writelines(json.dumps(event.to_dict()) + "\n" for event in happened)

    def test_the_figures_its_code_drew_are_in_the_page_and_nothing_else_of_the_session_is(
        self, client: TestClient, fake_client: FakeClient, app: FastAPI, tmp_path: Path
    ) -> None:
        chat_id = self.talk(client, fake_client, code={"where": "local"})
        self.drew(client, app, chat_id, tmp_path)

        response = client.get(f"/api/chats/{chat_id}/export")

        assert response.status_code == 200
        assert response.text.count("data:image/png;base64,") == 1
        assert "outside.png could not be found" in response.text

    def test_the_figures_are_found_where_the_workspace_is_now_and_not_where_it_was(
        self, client: TestClient, fake_client: FakeClient, app: FastAPI, workspace: Workspace, tmp_path: Path
    ) -> None:
        chat_id = self.talk(client, fake_client, code={"where": "local"})
        self.drew(client, app, chat_id, tmp_path)
        client.app.state.conversations.close()  # type: ignore[attr-defined]
        moved = tmp_path / "moved"
        shutil.move(workspace.root, moved)

        with TestClient(create_app(moved, token=TOKEN, check_keys=False), base_url=LOCAL, headers=BEARER) as later:
            response = later.get(f"/api/chats/{chat_id}/export")

        assert response.status_code == 200
        assert response.text.count("data:image/png;base64,") == 1


class TestDownloadHeaders:
    @pytest.mark.parametrize(
        ("title", "plain", "encoded"),
        [
            ("Nanobody design", "Nanobody design.html", "Nanobody%20design.html"),
            ("What is a nanobody?", "What is a nanobody.html", "What%20is%20a%20nanobody.html"),
            ("Plan: CRISPR / base editing", "Plan- CRISPR - base editing.html", "Plan-%20CRISPR%20-%20base%20editing.html"),
            ("a" * 200, "a" * 80 + ".html", "a" * 80 + ".html"),
            ("  ..hidden..  ", "hidden.html", "hidden.html"),
            ("", "conversation.html", "conversation.html"),
            ("???", "conversation.html", "conversation.html"),
            ("../../etc/passwd", "etc-passwd.html", "etc-passwd.html"),
            (
                'say "hi"\r\nSet-Cookie: x=1',
                "say -hi-Set-Cookie- x-1.html",
                "say%20-hi-Set-Cookie-%20x-1.html",
            ),
            ("抗体 design", "design.html", "%E6%8A%97%E4%BD%93%20design.html"),
            ("抗体", "conversation.html", "%E6%8A%97%E4%BD%93.html"),
            ("Café Ünïcode ²", "Cafe Unicode 2.html", "Caf%C3%A9%20%C3%9Cn%C3%AFcode%20%C2%B2.html"),
            ("x" * 79 + " .y", "x" * 79 + ".html", "x" * 79 + ".html"),
            ("." * 100 + "abc", "abc.html", "abc.html"),
        ],
    )
    def test_a_title_becomes_a_name_a_file_can_have(self, title: str, plain: str, encoded: str) -> None:
        headers = download_headers(title, "html")

        assert headers["Content-Disposition"] == f"attachment; filename=\"{plain}\"; filename*=utf-8''{encoded}"

    def test_a_page_sent_this_way_is_not_run_or_kept(self) -> None:
        headers = download_headers("A title", "pdf")

        assert headers["Content-Disposition"].endswith(".pdf")
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Cache-Control"] == "no-store"
        assert "default-src 'none'" in headers["Content-Security-Policy"]
        assert "sandbox" in headers["Content-Security-Policy"]


class TestPages:
    @pytest.fixture
    def pages(self, tmp_path: Path) -> Path:
        root = tmp_path / "pages"
        (root / "_next" / "static").mkdir(parents=True)
        (root / "index.html").write_text("<html>home</html>")
        (root / "settings.html").write_text("<html>settings</html>")
        (root / "chat").mkdir()
        (root / "chat" / "index.html").write_text("<html>chat</html>")
        (root / "_next" / "static" / "app.js").write_text("console.log(1)")
        (tmp_path / "secret.txt").write_text("not a page")

        return root

    @pytest.fixture
    def site(self, workspace: Workspace, pages: Path) -> Iterator[TestClient]:
        app = create_app(workspace.root, token=TOKEN, static_dir=pages, check_keys=False)
        with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
            yield opened

    def test_the_pages_of_the_interface_are_served_by_their_address(self, site: TestClient) -> None:
        assert site.get("/").text == "<html>home</html>"
        assert site.get("/settings").text == "<html>settings</html>"
        assert site.get("/chat").text == "<html>chat</html>"
        assert site.get("/chat/").text == "<html>chat</html>"
        assert site.get("/index.html").text == "<html>home</html>"
        assert site.get("/_next/static/app.js").text == "console.log(1)"

    def test_a_page_may_run_its_own_files_and_its_own_scripts_and_nothing_else(
        self, site: TestClient, pages: Path
    ) -> None:
        (pages / "scripted.html").write_text("<html><script>alert(1)</script></html>")

        for path in ("/", "/settings", "/chat", "/index.html", "/history", "/scripted"):
            policy = site.get(path).headers["content-security-policy"]
            assert "default-src 'self'" in policy and "frame-ancestors 'none'" in policy, path
        scripts = site.get("/scripted").headers["content-security-policy"]
        assert "script-src 'self' 'sha256-bhHHL3z2vDgxUt0W3dWQOrprscmda2Y5pLsLg4GF+pI='" in scripts
        assert "script-src 'self';" in site.get("/settings").headers["content-security-policy"]
        assert site.head("/scripted").headers["content-security-policy"] == scripts

    def test_a_script_added_to_a_page_that_was_served_is_named_the_next_time(
        self, site: TestClient, pages: Path
    ) -> None:
        assert "sha256" not in site.get("/settings").headers["content-security-policy"]

        (pages / "settings.html").write_text("<html><script>alert(1)</script> and more</html>")

        assert "sha256-bhHHL3z2vDgxUt0W3dWQOrprscmda2Y5pLsLg4GF+pI=" in site.get("/settings").headers[
            "content-security-policy"
        ]

    def test_a_script_changed_to_one_of_the_same_length_is_named_the_next_time(
        self, site: TestClient, pages: Path
    ) -> None:
        page = pages / "settings.html"
        page.write_text("<script>run(1)</script>")
        os.utime(page, ns=(1_000_000_000, 1_000_000_000))
        first = site.get("/settings").headers["content-security-policy"]

        page.write_text("<script>run(2)</script>")
        os.utime(page, ns=(2_000_000_000, 2_000_000_000))

        assert site.get("/settings").headers["content-security-policy"] != first

    def test_a_script_changed_to_one_of_another_length_in_the_same_second_is_named_the_next_time(
        self, site: TestClient, pages: Path
    ) -> None:
        page = pages / "settings.html"
        page.write_text("<script>run(1)</script>")
        os.utime(page, ns=(1_000_000_000, 1_000_000_000))
        first = site.get("/settings").headers["content-security-policy"]

        page.write_text("<script>run(10)</script>")
        os.utime(page, ns=(1_000_000_000, 1_000_000_000))

        assert site.get("/settings").headers["content-security-policy"] != first

    def test_only_a_page_has_a_policy_for_pages(self, site: TestClient) -> None:
        assert "content-security-policy" not in site.get("/_next/static/app.js").headers
        assert "content-security-policy" not in site.get("/api/health").headers

    def test_a_page_is_asked_for_by_head_as_well_as_by_get(self, site: TestClient) -> None:
        for path in ("/", "/chat", "/_next/static/app.js", "/chat/2026-10-07_1500_what-is-a-nanobody"):
            head = site.head(path)
            get = site.get(path)

            assert head.status_code == 200, path
            assert head.content == b""
            assert head.headers["content-length"] == get.headers["content-length"]
            assert head.headers["cache-control"] == get.headers["cache-control"]

    def test_the_api_does_not_answer_head_with_a_page(self, site: TestClient) -> None:
        assert site.head("/api/health").status_code == 405
        assert site.head("/api/missing").status_code == 405

    def test_an_address_of_no_page_shows_the_first_page_so_that_the_page_can_route_it(self, site: TestClient) -> None:
        assert site.get("/chat/2026-10-07_1500_what-is-a-nanobody").text == "<html>home</html>"
        assert site.get("/history").text == "<html>home</html>"

    def test_a_file_there_is_none_of_is_not_found(self, site: TestClient) -> None:
        response = site.get("/missing.js")

        assert response.status_code == 404
        assert error_of(response)["code"] == "not_found"

    def test_the_api_is_never_answered_with_a_page(self, site: TestClient) -> None:
        for path in ("/api/missing", "/api/chats/x/missing", "/api"):
            response = site.get(path)
            assert response.status_code == 404, path
            assert error_of(response)["code"] == "not_found"

    @pytest.mark.parametrize(
        "path", ["/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt", "//etc/passwd", "/a%00"]
    )
    def test_nothing_outside_the_pages_is_served(self, site: TestClient, path: str) -> None:
        response = site.get(path)

        assert "not a page" not in response.text
        assert "root:" not in response.text

    def test_a_link_in_the_pages_to_a_file_outside_them_is_not_followed(
        self, site: TestClient, pages: Path, tmp_path: Path
    ) -> None:
        (pages / "linked.txt").symlink_to(tmp_path / "secret.txt")
        (pages / "linked").symlink_to(tmp_path / "secret.txt")

        assert site.get("/linked.txt").status_code == 404
        assert "not a page" not in site.get("/linked").text

    def test_what_has_a_hash_in_its_name_is_kept_and_the_rest_is_looked_at_again(self, site: TestClient) -> None:
        assert site.get("/_next/static/app.js").headers["cache-control"] == "public, max-age=31536000, immutable"
        assert site.get("/").headers["cache-control"] == "no-cache"
        assert site.get("/chat").headers["cache-control"] == "no-cache"

    def test_the_link_with_the_token_opens_the_first_page_signed_in(self, workspace: Workspace, pages: Path) -> None:
        app = create_app(workspace.root, token=TOKEN, static_dir=pages, check_keys=False)

        with TestClient(app, base_url=LOCAL) as anonymous:
            opened = anonymous.get(f"/?token={TOKEN}", follow_redirects=True)

            assert opened.text == "<html>home</html>"
            assert anonymous.cookies.get(TOKEN_COOKIE) == TOKEN
            assert anonymous.get("/api/settings").status_code == 200

    def test_without_pages_the_server_serves_only_its_api(self, client: TestClient) -> None:
        assert client.get("/").status_code == 404
        assert client.get("/api/health").status_code == 200


class TestLifecycle:
    def test_the_conversations_are_told_where_the_loop_is_and_closed_when_the_server_stops(
        self, app: FastAPI, fake_client: FakeClient
    ) -> None:
        conversations = app.state.conversations
        assert conversations.loop is None

        with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
            assert conversations.loop is not None
            made = new_chat(opened)
            gate = hold_the_model(fake_client)
            opened.post(f"/api/chats/{made['id']}/messages", json={"text": "Go"})
            wait_until(gate.reached.is_set)
            handle = conversations.get(made["id"])
            threading.Timer(0.2, gate.release).start()

        assert handle.closed
        assert handle.chat.state == "idle"
        assert (handle.directory / "config.json").is_file()


@contextmanager
def serve(app: FastAPI, token: str | None = TOKEN) -> Iterator[tuple[str, httpx.Client]]:
    """The application served by a real server on a port of its own, and a client that is signed in to it."""
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", timeout_graceful_shutdown=2)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_until(lambda: server.started)
    base = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with httpx.Client(base_url=base, headers=headers, timeout=httpx.Timeout(15, read=15)) as http:
            yield base, http
    finally:
        server.should_exit = True
        thread.join(20)


def read_frames(
    http: httpx.Client,
    url: str,
    until: Any = None,
    quiet: float | None = None,
    headers: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """What a page following a conversation is told, as its frames, until one is the last wanted, or, if quiet
    is given, until nothing has come for that many seconds."""
    frames: list[dict[str, Any]] = []
    fields: dict[str, Any] = {}
    timeout = httpx.Timeout(15, read=quiet) if quiet else None
    try:
        with http.stream("GET", url, headers=headers, timeout=timeout) as response:
            assert response.status_code == 200, response.read()
            assert response.headers["content-type"].startswith("text/event-stream")
            for line in response.iter_lines():
                if line == "":
                    if fields:
                        if "data" in fields:
                            fields["data"] = json.loads(fields["data"])
                        frames.append(fields)
                        fields = {}
                        if until is not None and until(frames[-1]):
                            break
                    continue
                name, _, value = line.partition(": ")
                fields[name] = value
    except httpx.ReadTimeout:
        assert quiet, "The stream stopped sending"

    return frames


def wait_until_answered(http: httpx.Client, chat_id: str) -> None:
    wait_until(lambda: http.get(f"/api/chats/{chat_id}").json()["state"] == "idle")


def is_answer(frame: dict[str, Any]) -> bool:
    return frame.get("data", {}).get("kind") == "answer"


def is_idle(frame: dict[str, Any]) -> bool:
    """The conversation is told to be idle, which is the last thing said of a turn."""
    data = frame.get("data", {})

    return data.get("kind") == "status" and data["data"]["state"] == "idle" and data["turn"] >= 1


class TestEvents:
    def test_the_events_of_a_conversation_are_sent_as_they_happen_and_a_page_that_reconnects_misses_none(
        self, app: FastAPI, fake_client: FakeClient
    ) -> None:
        fake_client.completions.responses.append(text_response("The answer is here"))
        with serve(app) as (base, http):
            made = http.post("/api/chats", json={"team": []}).json()
            url = f"/api/chats/{made['id']}/events"
            http.post(f"/api/chats/{made['id']}/messages", json={"text": "Question"})
            wait_until_answered(http, made["id"])

            whole = read_frames(http, url, until=is_idle)
            ids = [int(frame["id"]) for frame in whole if "id" in frame]
            after_two = read_frames(http, f"{url}?after={ids[1]}", until=is_idle)
            by_header = read_frames(http, url, until=is_idle, headers={"Last-Event-ID": str(ids[2])})
            nothing_new = read_frames(http, f"{url}?after={ids[-1]}", quiet=0.5)

        assert whole[0] == {"retry": "2000"}
        assert [frame["event"] for frame in whole[1:]] == ["chat"] * (len(whole) - 1)
        assert ids == sorted(set(ids)) and len(ids) >= 3
        assert [frame["data"]["id"] for frame in whole[1:]] == ids
        assert [frame["data"]["kind"] for frame in whole[1:] if frame["data"]["kind"] in ("user", "answer")] == [
            "user",
            "answer",
        ]
        assert [frame["data"]["text"] for frame in whole[1:] if frame["data"]["kind"] == "answer"] == [
            "The answer is here"
        ]
        assert [int(frame["id"]) for frame in after_two[1:]] == [i for i in ids if i > ids[1]]
        assert [int(frame["id"]) for frame in by_header[1:]] == [i for i in ids if i > ids[2]]
        assert [frame for frame in nothing_new if "id" in frame] == []

    def test_the_greater_of_the_address_and_the_header_is_where_a_page_carries_on_from(
        self, app: FastAPI, fake_client: FakeClient
    ) -> None:
        with serve(app) as (base, http):
            made = http.post("/api/chats", json={"team": []}).json()
            http.post(f"/api/chats/{made['id']}/messages", json={"text": "Question"})
            wait_until_answered(http, made["id"])
            url = f"/api/chats/{made['id']}/events"
            ids = [int(f["id"]) for f in read_frames(http, url, until=is_idle) if "id" in f]

            frames = read_frames(http, f"{url}?after={ids[1]}", until=is_idle, headers={"Last-Event-ID": str(ids[0])})
            garbage = read_frames(http, url, quiet=0.5, headers={"Last-Event-ID": "not a number"})

        assert [int(f["id"]) for f in frames if "id" in f] == [i for i in ids if i > ids[1]]
        assert [int(f["id"]) for f in garbage if "id" in f] == ids

    @pytest.mark.parametrize(
        ("header", "number"), [(None, 0), ("", 0), ("7", 7), (" 12 ", 12), ("-3", 0), ("not a number", 0), ("1.5", 0)]
    )
    def test_the_last_event_a_browser_names_is_a_number_or_nothing(self, header: str | None, number: int) -> None:
        assert last_event(header) == number

    def test_a_page_already_following_is_told_of_a_message_sent_afterwards(
        self, app: FastAPI, fake_client: FakeClient
    ) -> None:
        fake_client.completions.responses.append(text_response("Told as it happens"))
        with serve(app) as (base, http):
            made = http.post("/api/chats", json={"team": []}).json()
            sender = threading.Timer(
                0.5, lambda: http.post(f"/api/chats/{made['id']}/messages", json={"text": "Later"})
            )
            sender.start()

            frames = read_frames(http, f"/api/chats/{made['id']}/events", until=is_answer)
            sender.join(10)

        assert [f["data"]["kind"] for f in frames if "data" in f and f["data"]["kind"] in ("user", "answer")] == [
            "user",
            "answer",
        ]

    def test_several_pages_follow_one_conversation(self, app: FastAPI, fake_client: FakeClient) -> None:
        fake_client.completions.responses.append(text_response("For everyone"))
        with serve(app) as (base, http):
            made = http.post("/api/chats", json={"team": []}).json()
            results: dict[int, list[dict[str, Any]]] = {}

            def follow(number: int) -> None:
                with httpx.Client(base_url=base, headers=BEARER, timeout=15) as own:
                    results[number] = read_frames(own, f"/api/chats/{made['id']}/events", until=is_answer)

            threads = [threading.Thread(target=follow, args=(number,)) for number in range(3)]
            for thread in threads:
                thread.start()
            wait_until(lambda: len(handle_of(app, made["id"])._waiters) == 3)
            http.post(f"/api/chats/{made['id']}/messages", json={"text": "Hello all"})
            for thread in threads:
                thread.join(20)

        assert len(results) == 3
        assert results[0] == results[1] == results[2]
        assert results[0][-1]["data"]["text"] == "For everyone"

    def test_a_page_that_goes_away_is_forgotten(self, app: FastAPI) -> None:
        with serve(app) as (base, http):
            made = http.post("/api/chats", json={"team": []}).json()
            handle = handle_of(app, made["id"])

            read_frames(http, f"/api/chats/{made['id']}/events", until=lambda frame: "retry" in frame)

            wait_until(lambda: not handle._waiters)

    def test_the_stream_ends_when_the_conversation_is_removed(self, app: FastAPI) -> None:
        with serve(app) as (base, http):
            made = http.post("/api/chats", json={"team": []}).json()
            remover = threading.Timer(0.5, lambda: http.delete(f"/api/chats/{made['id']}"))
            remover.start()

            frames = read_frames(http, f"/api/chats/{made['id']}/events")
            remover.join(10)

        assert frames[0] == {"retry": "2000"}

    def test_the_stream_needs_the_token_and_a_conversation_there_is(self, app: FastAPI) -> None:
        with serve(app, token=None) as (base, http):
            unsigned = http.get("/api/chats/anything/events")
            with httpx.Client(base_url=base, headers=BEARER) as signed:
                missing = signed.get("/api/chats/nothing/events")

        assert unsigned.status_code == 401
        assert unsigned.headers["content-type"].startswith("application/json")
        assert missing.status_code == 404
        assert error_of(missing)["code"] == "not_found"

    def test_the_stream_is_not_kept_or_buffered_on_the_way(self, app: FastAPI) -> None:
        with serve(app) as (base, http):
            made = http.post("/api/chats", json={"team": []}).json()
            with http.stream("GET", f"/api/chats/{made['id']}/events") as response:
                headers = dict(response.headers)

        assert headers["cache-control"] == "no-store"
        assert headers["x-accel-buffering"] == "no"
        assert headers["content-type"].startswith("text/event-stream")
