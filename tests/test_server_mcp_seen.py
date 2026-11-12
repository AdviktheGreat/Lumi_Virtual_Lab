"""Tests of what the settings show of the resources and prompts of MCP servers: what is kept of what a server held when
it was connected to, which a check keeps and which a prompt is rendered from, and the slash menu's prompts."""

import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mcp")

from virtual_lab.mcp_context import MCPPrompt, MCPPromptArgument, MCPResource, RenderedPrompt  # noqa: E402
from virtual_lab.mcp_tools import Held, MCPServerError, MCPToolError  # noqa: E402
from virtual_lab.server.app import create_app  # noqa: E402
from virtual_lab.server.mcp import (  # noqa: E402
    CHECK_TIMEOUT,
    ServerUnavailableError,
    check_connection,
    describe_server,
    describe_servers,
    render_prompt,
)
from virtual_lab.server.mcp_seen import describe_held, fingerprint, recall_held, seen_record  # noqa: E402
from virtual_lab.server.workspace import Settings, Workspace  # noqa: E402

from conftest import TEST_MODEL, FakeClient  # noqa: E402

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}
SERVER = str(Path(__file__).with_name("mcp_test_server.py"))
GENES = {"command": [sys.executable, SERVER, "--context"]}
THEN = datetime(2026, 5, 1, 12, 30, 5, tzinfo=UTC)


@pytest.fixture(autouse=True)
def model_client(fake_client: FakeClient) -> FakeClient:
    return fake_client


@pytest.fixture(autouse=True)
def auth_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "mcp_auth"
    monkeypatch.setenv("VIRTUAL_LAB_MCP_AUTH_DIR", str(directory))
    return directory


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


def held_of(resources: tuple[MCPResource, ...] = (), prompts: tuple[MCPPrompt, ...] = (), **more: Any) -> Held:
    return Held(resources=resources, prompts=prompts, **more)


def prompt_of(name: str = "summarize", *arguments: MCPPromptArgument, **fields: Any) -> MCPPrompt:
    return MCPPrompt("genes", name, f"genes_{name}", arguments=arguments, **fields)


def shown(client: TestClient, name: str = "genes") -> dict[str, Any]:
    return next(server for server in client.get("/api/mcp").json()["servers"] if server["name"] == name)


class Looking:
    """In place of connect_mcp: what it was asked, and a server that holds what it is given."""

    def __init__(
        self,
        held: Held | None = None,
        rendered: RenderedPrompt | Exception | None = None,
        error: Exception | None = None,
    ) -> None:
        self.asked: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.error = error
        held = held or Held()
        self.rendered = rendered
        self.rendering: list[tuple[MCPPrompt, Any]] = []
        self.opened = SimpleNamespace(
            tools=(),
            held={"genes": held},
            prompts=held.prompts,
            closed=0,
        )
        self.opened.close = lambda: setattr(self.opened, "closed", self.opened.closed + 1)
        self.opened.render_prompt = self.render

    def render(self, prompt: MCPPrompt, arguments: Any) -> RenderedPrompt:
        self.rendering.append((prompt, arguments))
        if isinstance(self.rendered, Exception):
            raise self.rendered
        assert self.rendered is not None

        return self.rendered

    def __call__(self, config: dict[str, Any], **options: Any) -> Any:
        self.asked.append((config, options))
        if self.error is not None:
            raise self.error

        return self.opened


class TestWhatIsKept:
    def test_how_a_server_is_reached_is_marked_the_same_whether_it_is_on_or_off(self) -> None:
        entry = {"url": "https://genes.example.org/mcp"}

        assert fingerprint("genes", entry) == fingerprint("genes", {**entry, "enabled": False})
        assert fingerprint("genes", entry) == fingerprint("genes", {**entry, "disabled": True})

    def test_a_change_to_how_it_is_reached_is_a_change_of_mark(self) -> None:
        entry = {"url": "https://genes.example.org/mcp"}

        assert fingerprint("genes", entry) != fingerprint("genes", {"url": "https://other.example.org/mcp"})
        assert fingerprint("genes", entry) != fingerprint("other", entry)

    def test_what_a_server_held_is_described_with_each_of_its_words_on_one_line_and_cut_short(self) -> None:
        held = held_of(
            resources=(
                MCPResource("genes", "panel\nok", "genes://panel", description="a\n\nb " + "x" * 900, title="Panel"),
                MCPResource("genes", "card", "genes://{id}", template=True, mime_type="text/plain"),
            ),
            prompts=(
                prompt_of(
                    "summarize",
                    MCPPromptArgument("symbol", "the gene\nsymbol", required=True),
                    MCPPromptArgument("depth"),
                    title="Summarize",
                    description="Summarize " + "y" * 900,
                ),
            ),
            problems=("It said\nno",),
            more=True,
        )

        described = describe_held(held)

        [panel, card] = described["resources"]
        assert panel["name"] == "panel ok" and panel["title"] == "Panel" and panel["template"] is False
        assert panel["description"].startswith("a b xxx") and len(panel["description"]) <= 500
        assert panel["description"].endswith("…")
        assert card == {
            "name": "card",
            "title": None,
            "uri": "genes://{id}",
            "description": "",
            "mime_type": "text/plain",
            "template": True,
        }
        [summarize] = described["prompts"]
        assert summarize["command"] == "genes_summarize" and summarize["title"] == "Summarize"
        assert len(summarize["description"]) <= 500
        assert summarize["arguments"] == [
            {"name": "symbol", "description": "the gene symbol", "required": True},
            {"name": "depth", "description": "", "required": False},
        ]
        assert described["problems"] == ["It said no"] and described["more"] is True

    def test_it_is_recalled_while_the_server_is_set_up_as_it_was_with_when_it_was_seen(self) -> None:
        entry = {"url": "https://genes.example.org/mcp"}
        record = seen_record("genes", entry, describe_held(held_of(prompts=(prompt_of(),))), THEN)

        recalled = recall_held({"genes": record}, "genes", {**entry, "enabled": False})

        assert record["seen"] == "2026-05-01T12:30:05Z"
        assert recalled is not None
        assert [prompt["command"] for prompt in recalled["prompts"]] == ["genes_summarize"]
        assert recalled["seen"] == "2026-05-01T12:30:05Z" and recalled["more"] is False
        assert "fingerprint" not in recalled

    def test_nothing_is_recalled_of_a_server_that_was_changed_or_not_seen_or_is_not_set_up(self) -> None:
        entry = {"url": "https://genes.example.org/mcp"}
        record = seen_record("genes", entry, describe_held(held_of()), THEN)

        assert recall_held({"genes": record}, "genes", {"url": "https://other.example.org/mcp"}) is None
        assert recall_held({"genes": record}, "other", entry) is None
        assert recall_held({"genes": record}, "genes", None) is None
        assert recall_held({}, "genes", entry) is None

    @pytest.mark.parametrize(
        "damage",
        [
            {"resources": "none"},
            {"resources": [{"name": "x"}]},
            {"prompts": [{"name": "p", "command": "genes_p", "arguments": [{"description": ""}]}]},
            {"prompts": [{"name": "p", "command": "genes_p"}]},
            {"problems": [1]},
            {"problems": None},
        ],
    )
    def test_what_was_kept_and_cannot_be_read_is_not_recalled(self, damage: dict[str, Any]) -> None:
        entry = {"url": "https://genes.example.org/mcp"}
        record = {**seen_record("genes", entry, describe_held(held_of()), THEN), **damage}

        assert recall_held({"genes": record}, "genes", entry) is None

    def test_a_record_that_is_not_one_is_not_recalled(self) -> None:
        assert recall_held({"genes": "text"}, "genes", {"url": "https://x"}) is None


class TestWhatTheWorkspaceKeeps:
    def entry(self) -> dict[str, Any]:
        return {"url": "https://genes.example.org/mcp"}

    def test_nothing_is_kept_until_something_is(self, workspace: Workspace) -> None:
        assert workspace.load_mcp_seen() == {}

    def test_what_a_server_held_is_kept_for_a_server_that_is_set_up(self, workspace: Workspace) -> None:
        workspace.put_mcp_server("genes", self.entry())
        record = seen_record("genes", self.entry(), describe_held(held_of(prompts=(prompt_of(),))), THEN)

        workspace.put_mcp_seen("genes", record)

        assert workspace.load_mcp_seen() == {"genes": record}

    def test_nothing_is_kept_for_a_server_that_is_not_set_up(self, workspace: Workspace) -> None:
        workspace.put_mcp_seen("genes", seen_record("genes", self.entry(), describe_held(held_of()), THEN))

        assert workspace.load_mcp_seen() == {}
        assert not workspace.mcp_seen_path.exists()

    def test_what_is_kept_of_one_server_is_replaced_and_not_that_of_the_others(self, workspace: Workspace) -> None:
        for name in ("genes", "other"):
            workspace.put_mcp_server(name, self.entry())
            workspace.put_mcp_seen(name, seen_record(name, self.entry(), describe_held(held_of()), THEN))
        newer = seen_record("genes", self.entry(), describe_held(held_of(prompts=(prompt_of(),))), THEN)

        workspace.put_mcp_seen("genes", newer)

        kept = workspace.load_mcp_seen()
        assert kept["genes"] == newer and kept["other"]["prompts"] == []

    def test_what_a_server_held_is_forgotten_with_the_server(self, workspace: Workspace) -> None:
        workspace.put_mcp_server("genes", self.entry())
        workspace.put_mcp_seen("genes", seen_record("genes", self.entry(), describe_held(held_of()), THEN))

        assert workspace.remove_mcp_server("genes") is True

        assert workspace.load_mcp_seen() == {}

    @pytest.mark.parametrize("saved", ["not json", "[]", '{"servers": []}', '{"servers": {"1": 1}}'])
    def test_a_file_that_cannot_be_understood_keeps_nothing(self, workspace: Workspace, saved: str) -> None:
        workspace.mcp_seen_path.write_text(saved, encoding="utf-8")

        seen = workspace.load_mcp_seen()

        assert recall_held(seen, "genes", self.entry()) is None

    def test_the_settings_show_what_a_server_held_while_it_is_set_up_as_it_was(self) -> None:
        entry = self.entry()
        seen = {"genes": seen_record("genes", entry, describe_held(held_of(prompts=(prompt_of(),))), THEN)}

        assert describe_server("genes", entry, seen)["holds"]["prompts"][0]["command"] == "genes_summarize"
        assert describe_server("genes", {**entry, "enabled": False}, seen)["holds"] is not None
        assert describe_server("genes", {"url": "https://other.example.org/mcp"}, seen)["holds"] is None
        assert describe_server("genes", entry)["holds"] is None
        [listed] = [server for server in describe_servers({"genes": entry}, seen) if server["name"] == "genes"]
        assert listed["holds"] is not None


class TestChecking:
    def test_a_check_tells_what_the_server_holds_as_the_settings_show_it(self) -> None:
        looking = Looking(held_of(resources=(MCPResource("genes", "panel", "genes://panel"),), prompts=(prompt_of(),)))

        result = check_connection("genes", GENES, looking)

        assert result["ok"] is True
        assert result["holds"] == describe_held(looking.opened.held["genes"])
        assert result["holds"]["resources"][0]["uri"] == "genes://panel"
        assert looking.opened.closed == 1

    def test_a_check_that_fails_holds_nothing(self) -> None:
        result = check_connection("genes", GENES, Looking(error=RuntimeError("no")))

        assert result == {"ok": False, "tools": [], "reason": "no"}

    def test_a_real_server_with_resources_and_prompts_says_what_it_holds(self) -> None:
        result = check_connection("genes", GENES)

        assert result["ok"] is True, result
        holds = result["holds"]
        assert {resource["uri"] for resource in holds["resources"]} == {
            "genes://panel",
            "genes://logo",
            "genes://gene/{symbol}",
        }
        [template] = [resource for resource in holds["resources"] if resource["template"]]
        assert template["name"] == "gene-card"
        prompts = {prompt["name"]: prompt for prompt in holds["prompts"]}
        assert prompts["summarize_gene"]["command"] == "genes_summarize_gene"
        assert prompts["summarize_gene"]["title"] == "Summarize a gene"
        assert [(a["name"], a["required"]) for a in prompts["summarize_gene"]["arguments"]] == [
            ("symbol", True),
            ("depth", False),
        ]
        assert prompts["compare-genes"]["command"] == "genes_compare_genes"
        assert holds["problems"] == [] and holds["more"] is False

    def test_a_real_server_without_them_holds_none(self) -> None:
        result = check_connection("genes", {"command": [sys.executable, SERVER]})

        assert result["ok"] is True
        assert result["holds"] == {"resources": [], "prompts": [], "problems": [], "more": False}


class TestTheChecksKeepWhatIsHeld:
    def test_a_check_keeps_what_the_server_held_and_the_settings_show_it(self, client: TestClient) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})
        assert shown(client)["holds"] is None

        body = client.post("/api/mcp/servers/genes/check").json()

        assert body["ok"] is True
        holds = shown(client)["holds"]
        assert {prompt["command"] for prompt in holds["prompts"]} == {"genes_summarize_gene", "genes_compare_genes"}
        assert len(holds["resources"]) == 3
        assert holds["seen"].endswith("Z") and "fingerprint" not in holds

    def test_what_was_kept_is_shown_while_the_server_is_turned_off_and_on(self, client: TestClient) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})
        client.post("/api/mcp/servers/genes/check")

        client.patch("/api/mcp/servers/genes", json={"enabled": False})
        assert shown(client)["enabled"] is False and shown(client)["holds"] is not None

        client.patch("/api/mcp/servers/genes", json={"enabled": True})
        assert shown(client)["holds"] is not None

    def test_a_server_that_is_changed_is_shown_as_not_seen_until_it_is_checked_again(self, client: TestClient) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})
        client.post("/api/mcp/servers/genes/check")

        client.put("/api/mcp/servers/genes", json={"entry": {**GENES, "env": {"A": "b"}}})

        assert shown(client)["holds"] is None
        client.post("/api/mcp/servers/genes/check")
        assert shown(client)["holds"] is not None

    def test_a_server_that_is_removed_and_set_up_again_is_shown_as_not_seen(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})
        client.post("/api/mcp/servers/genes/check")

        client.delete("/api/mcp/servers/genes")
        client.put("/api/mcp/servers/genes", json={"entry": GENES})

        assert shown(client)["holds"] is None
        assert workspace.load_mcp_seen() == {}

    def test_a_check_that_fails_keeps_what_was_kept(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})
        client.post("/api/mcp/servers/genes/check")
        before = shown(client)["holds"]

        monkeypatch.setattr(
            "virtual_lab.server.app.check_connection", lambda name, entry: {"ok": False, "tools": [], "reason": "down"}
        )
        assert client.post("/api/mcp/servers/genes/check").json()["ok"] is False

        assert shown(client)["holds"] == before

    def test_a_server_set_up_as_it_was_again_is_shown_what_it_held_then(self, client: TestClient) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})
        client.post("/api/mcp/servers/genes/check")
        before = shown(client)["holds"]

        client.put("/api/mcp/servers/genes", json={"entry": {**GENES, "env": {"A": "b"}}})
        client.put("/api/mcp/servers/genes", json={"entry": GENES})

        assert shown(client)["holds"] == before

    def test_a_preset_that_is_not_set_up_is_checked_and_nothing_is_kept(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        client.post("/api/mcp/servers/paperclip/check")

        assert workspace.load_mcp_seen() == {}


class TestRenderingAPrompt:
    def render(self, client: TestClient, prompt: str, arguments: Any = None, name: str = "genes") -> Any:
        body: dict[str, Any] = {"prompt": prompt}
        if arguments is not None:
            body["arguments"] = arguments

        return client.post(f"/api/mcp/servers/{name}/render", json=body)

    @pytest.fixture
    def genes(self, client: TestClient) -> TestClient:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})

        return client

    def test_a_prompt_is_written_out_by_the_server_for_the_arguments_and_comes_as_text(self, genes: TestClient) -> None:
        response = self.render(genes, "summarize_gene", {"symbol": "TP53"})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["text"] == "Summarize what is known of the gene TP53, in a short answer."
        assert body["messages"] == [{"role": "user", "text": body["text"]}]

    def test_an_argument_that_is_given_is_used(self, genes: TestClient) -> None:
        body = self.render(genes, "summarize_gene", {"symbol": "BRCA1", "depth": "long"}).json()

        assert body["text"] == "Summarize what is known of the gene BRCA1, in a long answer."

    def test_a_prompt_with_a_part_that_the_assistant_says_tells_who_says_each_part(self, genes: TestClient) -> None:
        body = self.render(genes, "compare-genes", {"first": "TP53", "second": "BRCA1"}).json()

        assert body["text"] == (
            "User: Compare the genes TP53 and BRCA1.\n\n"
            "Assistant: I will compare what each does, and where they differ."
        )
        assert [message["role"] for message in body["messages"]] == ["user", "assistant"]

    def test_a_server_that_is_off_is_rendered_from_all_the_same(self, genes: TestClient) -> None:
        genes.patch("/api/mcp/servers/genes", json={"enabled": False})

        assert self.render(genes, "summarize_gene", {"symbol": "TP53"}).status_code == 200

    def test_an_argument_that_is_needed_and_not_given_is_said_so(self, genes: TestClient) -> None:
        response = self.render(genes, "summarize_gene", {})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid"
        assert "needs symbol" in response.json()["error"]["message"]

    def test_an_argument_the_prompt_does_not_take_is_said_so(self, genes: TestClient) -> None:
        response = self.render(genes, "summarize_gene", {"symbol": "TP53", "colour": "red"})

        assert response.status_code == 422
        assert "does not take colour" in response.json()["error"]["message"]

    def test_a_prompt_the_server_does_not_have_is_said_so_with_those_it_has(self, genes: TestClient) -> None:
        response = self.render(genes, "nothing")

        assert response.status_code == 422
        message = response.json()["error"]["message"]
        assert "has no prompt nothing" in message and "summarize_gene" in message

    def test_a_server_that_cannot_be_connected_to_is_unavailable_and_says_why(self, client: TestClient) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": {"command": [sys.executable, "-c", "raise SystemExit(3)"]}})

        response = self.render(client, "summarize_gene", {"symbol": "TP53"})

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "unavailable"
        assert "Could not start" in response.json()["error"]["message"]

    def test_a_prompt_that_comes_out_too_long_for_a_message_is_refused(
        self, genes: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("virtual_lab.server.mcp.MAX_RENDERED_CHARS", 20)

        response = self.render(genes, "summarize_gene", {"symbol": "TP53"})

        assert response.status_code == 422
        assert "more than the 20" in response.json()["error"]["message"]

    @pytest.mark.parametrize(
        "body",
        [{}, {"prompt": ""}, {"prompt": "x", "arguments": {"a": 1}}, {"prompt": "x", "arguments": []}, {"prompt": 3}],
    )
    def test_what_is_asked_for_is_a_prompt_and_text_arguments(self, genes: TestClient, body: dict[str, Any]) -> None:
        assert genes.post("/api/mcp/servers/genes/render", json=body).status_code == 422

    def test_there_are_no_more_arguments_than_a_prompt_could_take(self, genes: TestClient) -> None:
        arguments = {f"a{n}": "x" for n in range(33)}

        assert self.render(genes, "summarize_gene", arguments).status_code == 422

    def test_a_server_that_is_not_there_is_not_found(self, client: TestClient) -> None:
        assert self.render(client, "x", name="nothing").status_code == 404

    def test_it_takes_the_token_like_the_rest(self, genes: TestClient) -> None:
        with TestClient(genes.app, base_url=LOCAL) as bare:
            assert bare.post("/api/mcp/servers/genes/render", json={"prompt": "x"}).status_code == 401


class TestRenderingWithoutAServer:
    def rendered(self, text: str = "Say it.") -> RenderedPrompt:
        return RenderedPrompt("genes", "summarize", (("user", text),), "About it")

    def test_it_is_connected_to_as_a_check_would_be_with_the_time_a_check_has_and_closed_after(self) -> None:
        looking = Looking(held_of(prompts=(prompt_of(),)), self.rendered())

        result = render_prompt("genes", GENES, "summarize", {"symbol": "x"}, looking)

        [(config, options)] = looking.asked
        assert config == {"mcpServers": {"genes": GENES}}
        assert options["start_timeout"] == CHECK_TIMEOUT and options["timeout"] == CHECK_TIMEOUT
        assert options["may_sign_in"] is False
        assert options["approve"](object()) is False
        assert result == {
            "text": "Say it.",
            "messages": [{"role": "user", "text": "Say it."}],
            "description": "About it",
        }
        assert looking.rendering == [(looking.opened.prompts[0], {"symbol": "x"})]
        assert looking.opened.closed == 1

    def test_the_server_is_closed_when_there_is_no_such_prompt(self) -> None:
        looking = Looking(held_of(prompts=(prompt_of(),)))

        with pytest.raises(ValueError, match="no prompt other: it has summarize"):
            render_prompt("genes", GENES, "other", None, looking)

        assert looking.opened.closed == 1

    @pytest.mark.parametrize("error", [MCPToolError("refused"), MCPServerError("stopped"), TimeoutError("too slow")])
    def test_a_server_that_does_not_write_it_out_is_unavailable_and_is_closed(self, error: Exception) -> None:
        looking = Looking(held_of(prompts=(prompt_of(),)), error)

        with pytest.raises(ServerUnavailableError, match=str(error)):
            render_prompt("genes", GENES, "summarize", None, looking)

        assert looking.opened.closed == 1

    def test_a_server_that_cannot_be_connected_to_is_unavailable(self) -> None:
        with pytest.raises(ServerUnavailableError, match="no route"):
            render_prompt("genes", GENES, "summarize", None, Looking(error=OSError("no route")))
