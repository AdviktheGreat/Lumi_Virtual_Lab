"""Tests of looking at an MCP server from the settings: connecting to it to say whether it can be, whether a sign-in
to it is kept, and forgetting that sign-in."""

import sys
import threading
import webbrowser
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mcp")

from virtual_lab import connect_mcp  # noqa: E402
from virtual_lab.mcp_auth import SignInStorage  # noqa: E402
from virtual_lab.mcp_tools import MCPServerError  # noqa: E402
from virtual_lab.server.app import create_app  # noqa: E402
from virtual_lab.server.mcp import (  # noqa: E402
    CHECK_TIMEOUT,
    check_connection,
    describe_server,
    read_server,
    sign_in_kept,
    sign_in_url,
    sign_out,
)
from virtual_lab.server.workspace import Settings, Workspace  # noqa: E402

from conftest import TEST_MODEL, FakeClient  # noqa: E402
from test_mcp_auth import Browser, OAuthServer, running  # noqa: E402

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}
SERVER = str(Path(__file__).with_name("mcp_test_server.py"))
GENES = {"command": [sys.executable, SERVER]}
SIGNED_IN = {"tokens": {"access_token": "kept", "token_type": "Bearer"}}


@pytest.fixture(autouse=True)
def model_client(fake_client: FakeClient) -> FakeClient:
    return fake_client


@pytest.fixture(autouse=True)
def auth_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "mcp_auth"
    monkeypatch.setenv("VIRTUAL_LAB_MCP_AUTH_DIR", str(directory))
    return directory


@pytest.fixture(autouse=True)
def no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PAPERCLIP_API_KEY", "FOUNDRY_API_TOKEN", "FOUNDRY_TESTING_TOKEN", "SEARCH_TOKEN"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> Browser:
    opened = Browser()
    monkeypatch.setattr(webbrowser, "open", opened.open)
    return opened


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    store = Workspace(tmp_path / "workspace")
    store.save_settings(Settings(model=TEST_MODEL, max_cost=None))

    return store


@pytest.fixture
def client(workspace: Workspace) -> Iterator[TestClient]:
    app = create_app(workspace.root, token=TOKEN, check_keys=False)
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


@pytest.fixture
def oauth_server() -> Iterator[OAuthServer]:
    yield from running("--token-path", "/auth/token")


def signs_in(server: OAuthServer, **entry: Any) -> dict[str, Any]:
    return {"url": server.url, "auth": "oauth", **entry}


def sign_in_to(server: OAuthServer) -> None:
    with connect_mcp({"mcp_servers": {"genes": signs_in(server)}}, start_timeout=30):
        pass


class Connecting:
    """In place of connect_mcp: what it was asked, and tools that are told when they are closed."""

    def __init__(self, names: tuple[str, ...] = ("genes_echo", "genes_count"), error: Exception | None = None) -> None:
        self.asked: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.error = error
        self.tools = SimpleNamespace(tools=tuple(SimpleNamespace(name=name) for name in names), closed=0)
        self.tools.close = lambda: setattr(self.tools, "closed", self.tools.closed + 1)

    def __call__(self, config: dict[str, Any], **options: Any) -> Any:
        self.asked.append((config, options))
        if self.error is not None:
            raise self.error

        return self.tools


class TestConnectingToLook:
    def test_the_tools_it_gives_are_named_as_the_lead_is_given_them_and_the_connection_is_closed(self) -> None:
        connect = Connecting()

        result = check_connection("genes", GENES, connect)

        assert result == {"ok": True, "tools": ["genes_echo", "genes_count"], "reason": None}
        assert connect.tools.closed == 1

    def test_it_is_connected_to_as_a_conversation_would_be_but_without_asking_anyone_anything(self) -> None:
        connect = Connecting()

        check_connection("genes", {**GENES, "approval": {"ask": ["*"]}}, connect)

        [(config, options)] = connect.asked
        assert config == {"mcpServers": {"genes": {**GENES, "approval": {"ask": ["*"]}}}}
        assert options["start_timeout"] == CHECK_TIMEOUT
        assert options["may_sign_in"] is False
        assert options["approve"](object()) is False
        assert options["answer"](object()) is None

    @pytest.mark.parametrize("off", [{"enabled": False}, {"disabled": True}])
    def test_a_server_that_is_off_is_connected_to_as_well(self, off: dict[str, Any]) -> None:
        connect = Connecting()

        assert check_connection("genes", {**GENES, **off}, connect)["ok"] is True

        assert connect.asked[0][0] == {"mcpServers": {"genes": GENES}}

    def test_a_preset_that_was_not_set_up_is_connected_to_as_its_own(self) -> None:
        connect = Connecting()

        check_connection("paperclip", None, connect)

        assert connect.asked[0][0] == {"mcpServers": {"paperclip": {"preset": "paperclip"}}}

    def test_why_it_could_not_be_is_said_and_nothing_is_left_open(self) -> None:
        connect = Connecting(error=MCPServerError("Could not connect to the MCP server genes: refused."))

        result = check_connection("genes", GENES, connect)

        assert result == {"ok": False, "tools": [], "reason": "Could not connect to the MCP server genes: refused."}

    def test_an_error_that_says_nothing_is_said_by_its_kind(self) -> None:
        assert check_connection("genes", GENES, Connecting(error=TimeoutError()))["reason"] == "TimeoutError"

    def test_an_entry_that_cannot_be_read_is_why(self) -> None:
        result = check_connection("genes", {"transport": "stdio"})

        assert result["ok"] is False and "command" in result["reason"]


class TestAgainstARealServer:
    def test_a_program_that_starts_gives_its_tools(self) -> None:
        result = check_connection("genes", GENES)

        assert result["ok"] is True and result["reason"] is None
        assert {"genes_echo", "genes_lookup"} <= set(result["tools"])

    def test_a_server_that_is_not_there_says_it_could_not_be_connected_to(self) -> None:
        result = check_connection("genes", {"url": "http://127.0.0.1:9/mcp"})

        assert result["ok"] is False and result["tools"] == []
        assert "Could not connect to the MCP server genes" in result["reason"]

    def test_a_program_that_is_not_installed_says_so(self, tmp_path: Path) -> None:
        result = check_connection("genes", {"command": [str(tmp_path / "no-such-program")]})

        assert result["ok"] is False
        assert "Could not start the MCP server genes" in result["reason"]

    def test_a_key_that_is_not_set_is_why_a_preset_cannot_be_connected_to(self) -> None:
        result = check_connection("paperclip", None)

        assert result["ok"] is False
        assert "PAPERCLIP_API_KEY" in result["reason"]

    def test_a_key_that_is_set_is_not_shown_in_what_goes_wrong(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SEARCH_TOKEN", "the-secret-value")
        entry = {"url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": "Bearer ${SEARCH_TOKEN}"}}

        result = check_connection("search", entry)

        assert result["ok"] is False
        assert "the-secret-value" not in result["reason"]


class TestSigningIn:
    def test_a_server_not_signed_in_to_is_said_to_need_it_and_nobody_is_sent_to_a_page(
        self, oauth_server: OAuthServer, browser: Browser
    ) -> None:
        connect = Connecting()

        result = check_connection("genes", signs_in(oauth_server), connect)

        assert result["ok"] is False
        assert "not signed in to yet" in result["reason"] and "genes" in result["reason"]
        assert connect.asked == [] and browser.opened == []

    def test_a_preset_that_is_signed_in_to_is_said_so_by_its_title(self) -> None:
        connect = Connecting()

        result = check_connection("proto_hosted", {"preset": "proto_hosted"}, connect)

        assert result["ok"] is False and "Proto" in result["reason"] and "not signed in to yet" in result["reason"]
        assert connect.asked == []

    def test_a_server_that_is_signed_in_to_is_connected_to_with_the_sign_in_kept(
        self, oauth_server: OAuthServer, browser: Browser
    ) -> None:
        sign_in_to(oauth_server)

        result = check_connection("genes", signs_in(oauth_server))

        assert result["ok"] is True and "genes_authorization" in result["tools"]
        assert len(browser.opened) == 1
        assert oauth_server.stats()["signed_in"] == 1

    def test_a_sign_in_that_can_no_longer_be_used_says_to_sign_in_and_nobody_is_sent_to_a_page(
        self, oauth_server: OAuthServer, browser: Browser, auth_dir: Path
    ) -> None:
        sign_in_to(oauth_server)
        storage = SignInStorage(oauth_server.url)
        tokens = {key: value for key, value in storage.read()["tokens"].items() if key != "refresh_token"}
        storage.update(tokens=tokens, expires_at=1.0)

        result = check_connection("genes", signs_in(oauth_server))

        assert result["ok"] is False
        assert "needs you to sign in, which this connection does not ask of you" in result["reason"]
        assert len(browser.opened) == 1

    def test_whether_a_sign_in_is_kept_is_shown_for_a_server_that_is_signed_in_to_and_not_for_any_other(
        self, oauth_server: OAuthServer, browser: Browser
    ) -> None:
        entry = signs_in(oauth_server)

        assert describe_server("genes", entry)["signed_in"] is False
        assert describe_server("proto_hosted", {"preset": "proto_hosted"})["signed_in"] is False
        sign_in_to(oauth_server)
        assert describe_server("genes", entry)["signed_in"] is True
        assert describe_server("other", GENES)["signed_in"] is None
        assert describe_server("paperclip", None)["signed_in"] is None
        assert describe_server("proto_hosted", None)["auth"] == "oauth"

    def test_a_sign_in_is_kept_for_the_address_the_entry_makes_in_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = {"url": "https://${HOST}/mcp", "auth": "oauth"}

        assert sign_in_kept("genes", entry) is None
        assert describe_server("genes", entry)["signed_in"] is None

        monkeypatch.setenv("HOST", "mcp.example.org")
        SignInStorage("https://mcp.example.org/mcp").update(**SIGNED_IN)

        assert sign_in_url("genes", entry) == "https://mcp.example.org/mcp"
        assert sign_in_kept("genes", entry) is True

    def test_a_sign_in_that_is_forgotten_is_asked_for_again(self, oauth_server: OAuthServer, browser: Browser) -> None:
        sign_in_to(oauth_server)

        assert sign_out("genes", signs_in(oauth_server)) is True
        assert sign_out("genes", signs_in(oauth_server)) is False

        assert sign_in_kept("genes", signs_in(oauth_server)) is False
        assert "not signed in to yet" in check_connection("genes", signs_in(oauth_server))["reason"]

    def test_only_a_sign_in_to_that_server_is_forgotten(self, oauth_server: OAuthServer, browser: Browser) -> None:
        sign_in_to(oauth_server)
        other = "https://mcp.example.org/mcp"
        SignInStorage(other).update(**SIGNED_IN)

        sign_out("genes", signs_in(oauth_server))

        assert sign_in_kept("other", {"url": other, "auth": "oauth"}) is True

    def test_a_server_that_is_not_signed_in_to_has_nothing_to_forget(self) -> None:
        with pytest.raises(ValueError, match="Paperclip.* is not signed in to"):
            sign_out("paperclip", None)
        with pytest.raises(ValueError, match="genes is not signed in to"):
            sign_out("genes", GENES)

    def test_a_server_whose_address_is_not_known_cannot_be_signed_out_of(self) -> None:
        with pytest.raises(ValueError, match="HOST"):
            sign_out("genes", {"url": "https://${HOST}/mcp", "auth": "oauth"})

    def test_a_server_is_read_strictly_where_the_address_matters(self) -> None:
        with pytest.raises(ValueError, match="HOST"):
            read_server("genes", {"url": "https://${HOST}/mcp"}, strict=True)
        assert read_server("genes", {"url": "https://${HOST}/mcp"}).url == "https://x/mcp"


class TestTheRoutes:
    def test_a_server_is_checked(self, client: TestClient) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})

        response = client.post("/api/mcp/servers/genes/check")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True and "genes_echo" in body["tools"] and body["reason"] is None

    def test_a_server_that_is_off_is_checked_and_stays_off(self, client: TestClient) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": {**GENES, "enabled": False}})

        assert client.post("/api/mcp/servers/genes/check").json()["ok"] is True

        [server] = [s for s in client.get("/api/mcp").json()["servers"] if s["name"] == "genes"]
        assert server["enabled"] is False

    def test_a_preset_that_was_not_set_up_is_checked_and_not_set_up_by_it(self, client: TestClient) -> None:
        body = client.post("/api/mcp/servers/paperclip/check").json()

        assert body["ok"] is False and "PAPERCLIP_API_KEY" in body["reason"]
        assert client.get("/api/mcp").json()["servers"][0]["added"] is False

    def test_a_server_that_is_not_there_is_not_found(self, client: TestClient) -> None:
        checked = client.post("/api/mcp/servers/nothing/check")
        signed_out = client.delete("/api/mcp/servers/nothing/sign-in")

        assert checked.status_code == 404 and signed_out.status_code == 404

    def test_it_takes_the_token_like_the_rest(self, client: TestClient) -> None:
        with TestClient(client.app, base_url=LOCAL) as bare:
            assert bare.post("/api/mcp/servers/genes/check").status_code == 401
            assert bare.delete("/api/mcp/servers/proto_hosted/sign-in").status_code == 401

    def test_a_server_is_not_checked_twice_at_once_and_can_be_when_the_check_is_over(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})
        began, release = threading.Event(), threading.Event()
        results: list[dict[str, Any]] = []

        def slow(name: str, entry: Any) -> dict[str, Any]:
            began.set()
            release.wait(10)
            return {"ok": True, "tools": [], "reason": None}

        monkeypatch.setattr("virtual_lab.server.app.check_connection", slow)
        first = threading.Thread(target=lambda: results.append(client.post("/api/mcp/servers/genes/check").json()))
        first.start()
        assert began.wait(10)

        second = client.post("/api/mcp/servers/genes/check")
        release.set()
        first.join(10)

        assert second.status_code == 409 and second.json()["error"]["code"] == "busy"
        assert results == [{"ok": True, "tools": [], "reason": None}]
        assert client.post("/api/mcp/servers/genes/check").status_code == 200

    def test_a_check_that_fails_in_a_way_nobody_expected_can_be_made_again(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})

        def broken(name: str, entry: Any) -> dict[str, Any]:
            raise RuntimeError("not expected")

        with monkeypatch.context() as patch:
            patch.setattr("virtual_lab.server.app.check_connection", broken)
            with pytest.raises(RuntimeError, match="not expected"):
                client.post("/api/mcp/servers/genes/check")

        assert client.post("/api/mcp/servers/genes/check").status_code == 200

    def test_a_sign_in_is_shown_and_forgotten(
        self, client: TestClient, oauth_server: OAuthServer, browser: Browser
    ) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": signs_in(oauth_server)})
        sign_in_to(oauth_server)

        def shown() -> Any:
            return [s for s in client.get("/api/mcp").json()["servers"] if s["name"] == "genes"][0]["signed_in"]

        assert shown() is True
        assert client.post("/api/mcp/servers/genes/check").json()["ok"] is True

        response = client.delete("/api/mcp/servers/genes/sign-in")

        assert response.status_code == 200
        assert [s for s in response.json()["servers"] if s["name"] == "genes"][0]["signed_in"] is False
        assert shown() is False
        assert "not signed in to yet" in client.post("/api/mcp/servers/genes/check").json()["reason"]

    def test_forgetting_a_sign_in_that_is_not_kept_is_not_an_error(
        self, client: TestClient, oauth_server: OAuthServer
    ) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": signs_in(oauth_server)})

        assert client.delete("/api/mcp/servers/genes/sign-in").status_code == 200

    def test_a_server_that_is_not_signed_in_to_has_no_sign_in_to_forget(self, client: TestClient) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})

        for name in ("genes", "paperclip"):
            response = client.delete(f"/api/mcp/servers/{name}/sign-in")
            assert response.status_code == 422 and "is not signed in to" in response.json()["error"]["message"]

    def test_a_preset_that_is_signed_in_to_is_forgotten_without_having_been_set_up(self, client: TestClient) -> None:
        servers = {s["name"]: s for s in client.get("/api/mcp").json()["servers"]}

        assert servers["proto_hosted"]["signed_in"] is False
        assert client.delete("/api/mcp/servers/proto_hosted/sign-in").status_code == 200
