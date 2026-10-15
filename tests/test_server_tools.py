"""Tests of the library's tools as the server gives them to a conversation, and as the settings turn them off."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from virtual_lab.artifacts import UnsafeFilenameError
from virtual_lab.server.app import create_app
from virtual_lab.server.config import ChatConfig, resolve_config
from virtual_lab.server.conversations import Conversations
from virtual_lab.server.tools import (
    GROUPS,
    MAX_SUMMARY_CHARS,
    NEEDS_CODE,
    NO_FILES_ATTACHED,
    attached_file_tools,
    check_tool_names,
    conversation_tools,
    describe_tools,
    summary,
    tool_names,
)
from virtual_lab.server.workspace import TOOLS_FILE_NAME, Settings, Workspace
from virtual_lab.tables import TableError
from virtual_lab.tools import DATABASE_TOOLS

from conftest import TEST_MODEL, FakeClient, text_response, tool_call_response

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}

CSV = b"gene,score\nTP53,0.91\nBRCA1,0.20\n"
SIZE = len(CSV)

# Every tool the library has that a conversation may be given: its lookups, and the tools that read files
EVERY_TOOL = {tool.name for tool in DATABASE_TOOLS} | {"data_files", "inspect_data_file", "fetch_structure_file"}


@pytest.fixture(autouse=True)
def model_client(fake_client: FakeClient) -> FakeClient:
    return fake_client


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    store = Workspace(tmp_path / "workspace")
    store.save_settings(Settings(model=TEST_MODEL, max_cost=None))

    return store


@pytest.fixture
def conversations(workspace: Workspace) -> Iterator[Conversations]:
    kept = Conversations(workspace, check_keys=False)
    yield kept
    kept.close()


@pytest.fixture
def client(workspace: Workspace) -> Iterator[TestClient]:
    app = create_app(workspace.root, token=TOKEN, check_keys=False)
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


def offered(fake_client: FakeClient, call: int = 0) -> list[str]:
    return [tool["function"]["name"] for tool in fake_client.completions.calls[call]["tools"]]


class TestTheCatalogue:
    def test_every_tool_of_the_library_a_conversation_may_be_given_is_listed_once_in_a_group(self) -> None:
        listed = [name for names in GROUPS.values() for name in names]

        assert sorted(listed) == sorted(EVERY_TOOL)
        assert tool_names() == tuple(listed)

    def test_each_tool_is_listed_with_its_group_what_it_does_and_whether_it_needs_code(self) -> None:
        tools = describe_tools([])

        assert [tool["name"] for tool in tools] == list(tool_names())
        assert {tool["group"] for tool in tools} == set(GROUPS)
        by_name = {tool["name"]: tool for tool in tools}
        assert by_name["uniprot_lookup"] == {
            "name": "uniprot_lookup",
            "group": "Proteins and structures",
            "summary": summary(DATABASE_TOOLS[1].description),
            "needs_code": False,
            "enabled": True,
        }
        assert [name for name, tool in by_name.items() if tool["needs_code"]] == sorted(NEEDS_CODE)
        assert all(tool["summary"] and not tool["summary"].endswith(".") for tool in tools)

    def test_the_tools_turned_off_are_not_enabled(self) -> None:
        tools = {tool["name"]: tool["enabled"] for tool in describe_tools(["arxiv_search", "chembl_lookup"])}

        assert [name for name, enabled in tools.items() if not enabled] == ["arxiv_search", "chembl_lookup"]

    def test_a_description_is_cut_to_its_first_sentence_and_to_a_length_the_settings_can_show(self) -> None:
        assert summary("Gets a thing.  It does more\nthan that. And more.") == "Gets a thing"
        assert summary("No full stop") == "No full stop"
        long = summary("word " * 100)
        assert len(long) == MAX_SUMMARY_CHARS
        assert long.endswith("…")

    def test_names_are_checked_and_put_in_the_order_they_are_listed(self) -> None:
        checked = check_tool_names(["chembl_lookup", "pubmed_search", "chembl_lookup"])

        assert checked == ["pubmed_search", "chembl_lookup"]
        assert check_tool_names([]) == []

    @pytest.mark.parametrize("names", ["pubmed_search", None, 3, {"pubmed_search": True}])
    def test_names_that_are_not_a_list_are_refused(self, names: Any) -> None:
        with pytest.raises(ValueError, match="list of names"):
            check_tool_names(names)

    @pytest.mark.parametrize("names", [["nothing"], ["pubmed_search", "nothing"], [3], [["pubmed_search"]]])
    def test_a_name_that_is_not_a_tool_is_refused_and_the_tools_there_are_are_said(self, names: list[Any]) -> None:
        with pytest.raises(ValueError, match="There is no tool .*the tools are pubmed_search, "):
            check_tool_names(names)


class TestTheToolsOfAConversation:
    def test_where_code_runs_the_tools_that_read_files_see_the_session_and_one_that_fetches_a_structure_is_given(
        self, tmp_path: Path
    ) -> None:
        work = tmp_path / "work"
        (work / "uploads").mkdir(parents=True)
        (work / "uploads" / "counts.csv").write_bytes(CSV)

        tools = conversation_tools(tmp_path / "chat", work)

        assert set(tools) == EVERY_TOOL
        assert list(tools) == list(tool_names())
        assert tools["data_files"].function() == f"1 files:\n  uploads/counts.csv ({SIZE} bytes)"
        assert "TP53" in tools["inspect_data_file"].function(filename="uploads/counts.csv")

    def test_where_no_code_runs_the_tool_that_fetches_a_structure_is_left_out(self, tmp_path: Path) -> None:
        tools = conversation_tools(tmp_path, None)

        assert set(tools) == EVERY_TOOL - NEEDS_CODE

    def test_the_tools_that_read_files_see_those_attached_by_the_names_the_lead_is_told(self, tmp_path: Path) -> None:
        (tmp_path / "uploads").mkdir()
        (tmp_path / "uploads" / "counts.csv").write_bytes(CSV)
        (tmp_path / "uploads" / "blob.bin").write_bytes(b"hello")
        (tmp_path / "chat.json").write_text("{}")
        listing, inspection = attached_file_tools(tmp_path)

        assert (listing.name, inspection.name) == ("data_files", "inspect_data_file")
        assert listing.function() == (
            "2 files:\n  uploads/blob.bin (5 bytes) - not a table; open it in code\n"
            f"  uploads/counts.csv ({SIZE} bytes)"
        )
        by_path = inspection.function(filename="uploads/counts.csv")
        assert by_path.startswith("counts.csv: 2 rows, 2 columns.")
        assert inspection.function(filename="counts.csv") == by_path

    def test_they_have_the_descriptions_and_parameters_the_library_gives_them(self, tmp_path: Path) -> None:
        library = conversation_tools(tmp_path, tmp_path)
        attached = conversation_tools(tmp_path, None)

        for name in ("data_files", "inspect_data_file"):
            assert attached[name].description == library[name].description
            assert attached[name].parameters == library[name].parameters

    def test_with_nothing_attached_they_say_so_rather_than_that_there_are_no_data_files_yet(
        self, tmp_path: Path
    ) -> None:
        listing, inspection = attached_file_tools(tmp_path)

        assert listing.function() == NO_FILES_ATTACHED
        with pytest.raises(TableError, match="There is no file called"):
            inspection.function(filename="uploads/counts.csv")

    def test_they_see_nothing_outside_the_files_attached(self, tmp_path: Path) -> None:
        (tmp_path / "uploads").mkdir()
        (tmp_path / "secret.csv").write_bytes(CSV)
        _, inspection = attached_file_tools(tmp_path)

        for name in ("../secret.csv", "uploads/../secret.csv", str(tmp_path / "secret.csv")):
            with pytest.raises(UnsafeFilenameError):
                inspection.function(filename=name)


class TestWhatTheWorkspaceKeeps:
    def test_no_tool_is_turned_off_until_one_is(self, workspace: Workspace) -> None:
        assert workspace.load_disabled_tools() == []
        assert not workspace.tools_path.exists()

    def test_the_tools_turned_off_are_kept(self, workspace: Workspace) -> None:
        workspace.save_disabled_tools(["arxiv_search"])

        assert workspace.tools_path == workspace.root / TOOLS_FILE_NAME
        assert json.loads(workspace.tools_path.read_text()) == {"disabled": ["arxiv_search"]}
        assert workspace.load_disabled_tools() == ["arxiv_search"]

    @pytest.mark.parametrize(
        "saved", ["not json", "[]", '"arxiv_search"', '{"disabled": "arxiv_search"}', '{"disabled": null}', "{}"]
    )
    def test_a_file_that_cannot_be_understood_turns_nothing_off(self, workspace: Workspace, saved: str) -> None:
        workspace.tools_path.write_text(saved)

        assert workspace.load_disabled_tools() == []

    def test_a_name_that_is_not_text_is_left_out(self, workspace: Workspace) -> None:
        workspace.tools_path.write_text('{"disabled": ["arxiv_search", 3, null, ["x"]]}')

        assert workspace.load_disabled_tools() == ["arxiv_search"]


class TestWhatAConversationIsSetUpWith:
    def test_it_has_every_tool_unless_the_workspace_turned_some_off(self, workspace: Workspace) -> None:
        config = resolve_config({}, workspace.load_settings(), workspace)

        assert config.tools == tool_names()

        workspace.save_disabled_tools(["arxiv_search", "pubmed_search"])
        config = resolve_config({}, workspace.load_settings(), workspace)

        assert config.tools == tuple(name for name in tool_names() if name not in ("arxiv_search", "pubmed_search"))

    def test_the_request_chooses_which_whatever_the_workspace_turned_off(self, workspace: Workspace) -> None:
        workspace.save_disabled_tools(["arxiv_search"])

        config = resolve_config({"tools": ["arxiv_search", "pubmed_search"]}, workspace.load_settings(), workspace)

        assert config.tools == ("pubmed_search", "arxiv_search")
        assert resolve_config({"tools": []}, workspace.load_settings(), workspace).tools == ()

    @pytest.mark.parametrize("tools", [["nothing"], "pubmed_search", 3])
    def test_a_tool_that_cannot_be_given_is_refused(self, workspace: Workspace, tools: Any) -> None:
        with pytest.raises(ValueError):
            resolve_config({"tools": tools}, workspace.load_settings(), workspace)

    def test_it_is_kept_with_the_conversation_as_it_was_and_read_back(self, workspace: Workspace) -> None:
        config = resolve_config({"tools": ["pubmed_search"]}, workspace.load_settings(), workspace)

        saved = config.to_dict()

        assert saved["tools"] == ["pubmed_search"]
        assert ChatConfig.from_dict(saved) == config

    def test_a_conversation_begun_before_the_lead_had_tools_goes_on_without_them(self, workspace: Workspace) -> None:
        saved = resolve_config({}, workspace.load_settings(), workspace).to_dict()
        del saved["tools"]

        assert ChatConfig.from_dict(saved).tools == ()

    def test_a_name_written_twice_in_what_was_kept_is_one_tool(self, workspace: Workspace) -> None:
        saved = resolve_config({}, workspace.load_settings(), workspace).to_dict()
        saved["tools"] = ["pubmed_search", "arxiv_search", "pubmed_search"]

        assert ChatConfig.from_dict(saved).tools == ("pubmed_search", "arxiv_search")


class TestWhatTheLeadIsGiven:
    def test_a_conversation_without_code_is_given_the_tools_but_the_one_that_fetches_a_structure(
        self, conversations: Conversations, fake_client: FakeClient
    ) -> None:
        handle = conversations.create({"team": []})

        handle.chat.start("Hello").join(20)

        names = offered(fake_client)
        assert set(names) == EVERY_TOOL - NEEDS_CODE
        assert [tool.name for tool in handle.chat.tools] == [name for name in tool_names() if name in names]

    def test_a_conversation_with_code_is_given_all_of_them_beside_the_ones_that_are_its_own(
        self, conversations: Conversations, fake_client: FakeClient
    ) -> None:
        handle = conversations.create({"team": [], "code": {"where": "local"}})

        handle.chat.start("Hello").join(20)

        names = offered(fake_client)
        assert EVERY_TOOL <= set(names)
        assert "run_code" in names

    def test_only_the_tools_it_was_set_up_with_are_given(
        self, conversations: Conversations, fake_client: FakeClient
    ) -> None:
        handle = conversations.create({"team": [], "tools": ["pubmed_search", "data_files"]})

        handle.chat.start("Hello").join(20)

        assert offered(fake_client) == ["pubmed_search", "data_files"]

    def test_a_conversation_set_up_with_none_is_given_none(
        self, conversations: Conversations, fake_client: FakeClient
    ) -> None:
        handle = conversations.create({"team": [], "tools": []})

        handle.chat.start("Hello").join(20)

        assert "tools" not in fake_client.completions.calls[0] or fake_client.completions.calls[0]["tools"] is None

    def test_the_lead_can_look_inside_a_file_attached_where_no_code_runs(
        self, conversations: Conversations, fake_client: FakeClient
    ) -> None:
        fake_client.completions.responses = [
            tool_call_response("inspect_data_file", {"filename": "uploads/counts.csv"}),
            text_response("Two genes."),
        ]
        handle = conversations.create({"team": []})
        attached = handle.chat.save_upload("counts.csv", CSV)

        handle.chat.start("What is in it?", [attached.name]).join(20)

        (output,) = [event for event in handle.chat.events_since() if event.kind == "tool_output"]
        assert output.data["name"] == "inspect_data_file"
        assert output.text.startswith("counts.csv: 2 rows, 2 columns.")
        assert "TP53" in output.text
        told = fake_client.completions.calls[0]["messages"][-1]["content"]
        assert "inspect_data_file can look inside a table or a spreadsheet" in told

    def test_the_lead_sees_the_files_of_the_session_where_code_runs(
        self, conversations: Conversations, fake_client: FakeClient
    ) -> None:
        fake_client.completions.responses = [tool_call_response("data_files", {}), text_response("One file.")]
        handle = conversations.create({"team": [], "code": {"where": "local"}})
        attached = handle.chat.save_upload("counts.csv", CSV)

        handle.chat.start("What do I have?", [attached.name]).join(20)

        (output,) = [event for event in handle.chat.events_since() if event.kind == "tool_output"]
        assert output.text == f"1 files:\n  uploads/counts.csv ({SIZE} bytes)"

    def test_a_conversation_opened_again_has_the_tools_it_was_set_up_with_and_not_the_workspaces_now(
        self, workspace: Workspace, fake_client: FakeClient
    ) -> None:
        first = Conversations(workspace, check_keys=False)
        handle = first.create({"team": []})
        chat_id = handle.id
        first.close()

        workspace.save_disabled_tools(list(tool_names()))
        second = Conversations(workspace, check_keys=False)
        try:
            reopened = second.get(chat_id)
            reopened.chat.start("Hello").join(20)
        finally:
            second.close()

        assert set(offered(fake_client)) == EVERY_TOOL - NEEDS_CODE

    def test_a_conversation_begun_before_the_lead_had_tools_is_opened_without_them(
        self, workspace: Workspace, fake_client: FakeClient
    ) -> None:
        first = Conversations(workspace, check_keys=False)
        handle = first.create({"team": []})
        config_path = handle.directory / "config.json"
        saved = json.loads(config_path.read_text())
        del saved["tools"]
        config_path.write_text(json.dumps(saved))
        chat_id = handle.id
        first.close()

        second = Conversations(workspace, check_keys=False)
        try:
            second.get(chat_id).chat.start("Hello").join(20)
        finally:
            second.close()

        assert fake_client.completions.calls[0].get("tools") is None

    def test_no_tool_has_a_name_the_conversation_keeps_for_its_own(self) -> None:
        assert not set(tool_names()) & {"run_code", "find_resources", "convene_team", "consult"}


class TestTheRoutes:
    def test_the_tools_are_listed_with_none_turned_off_to_begin_with(self, client: TestClient) -> None:
        response = client.get("/api/tools")

        assert response.status_code == 200
        tools = response.json()["tools"]
        assert [tool["name"] for tool in tools] == list(tool_names())
        assert all(tool["enabled"] for tool in tools)

    def test_turning_tools_off_is_kept_and_listed_back(self, client: TestClient, workspace: Workspace) -> None:
        changed = client.put("/api/tools", json={"disabled": ["chembl_lookup", "arxiv_search"]})

        assert changed.status_code == 200
        off = [tool["name"] for tool in changed.json()["tools"] if not tool["enabled"]]
        assert off == ["arxiv_search", "chembl_lookup"]
        assert client.get("/api/tools").json() == changed.json()
        assert workspace.load_disabled_tools() == ["arxiv_search", "chembl_lookup"]

    def test_turning_them_on_again_is_putting_none_in_the_list(self, client: TestClient) -> None:
        client.put("/api/tools", json={"disabled": ["arxiv_search"]})

        again = client.put("/api/tools", json={"disabled": []})

        assert all(tool["enabled"] for tool in again.json()["tools"])

    @pytest.mark.parametrize(
        "body",
        [
            {"disabled": ["nothing"]},
            {"disabled": "arxiv_search"},
            {"disabled": [3]},
            {"enabled": []},
            {"disabled": [""] * 65},
        ],
    )
    def test_what_cannot_be_used_is_refused_and_changes_nothing(
        self, client: TestClient, workspace: Workspace, body: dict[str, Any]
    ) -> None:
        client.put("/api/tools", json={"disabled": ["arxiv_search"]})

        response = client.put("/api/tools", json=body)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid"
        assert workspace.load_disabled_tools() == ["arxiv_search"]

    def test_the_tools_need_the_token_like_every_other_route(self, workspace: Workspace) -> None:
        with TestClient(create_app(workspace.root, token=TOKEN, check_keys=False), base_url=LOCAL) as bare:
            assert bare.get("/api/tools").status_code == 401
            assert bare.put("/api/tools", json={"disabled": []}).status_code == 401

    def test_a_new_conversation_is_set_up_with_the_tools_that_are_on(self, client: TestClient) -> None:
        client.put("/api/tools", json={"disabled": ["arxiv_search"]})

        made = client.post("/api/chats", json={"team": []}).json()

        assert made["config"]["tools"] == [name for name in tool_names() if name != "arxiv_search"]

    def test_a_new_conversation_can_be_given_tools_of_its_own_choosing(self, client: TestClient) -> None:
        made = client.post("/api/chats", json={"team": [], "tools": ["pubmed_search"]}).json()

        assert made["config"]["tools"] == ["pubmed_search"]

    def test_a_tool_that_cannot_be_given_to_a_conversation_is_refused_and_leaves_nothing_behind(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        response = client.post("/api/chats", json={"team": [], "tools": ["nothing"]})

        assert response.status_code == 422
        assert list(workspace.chats_dir.iterdir()) == []
        assert response.json()["error"]["code"] == "invalid"


WEB_SOURCES = Path(__file__).resolve().parents[1] / "web" / "src"


@pytest.mark.skipif(not WEB_SOURCES.is_dir(), reason="the web interface's sources are not here")
class TestWhatTheWebInterfaceKnowsOfThem:
    """The page says what each tool does as it is called, in a list of its own, which a new tool must be added to."""

    def test_each_tool_has_a_title_in_the_page(self) -> None:
        titles = (WEB_SOURCES / "lib" / "calls.ts").read_text()

        assert [name for name in tool_names() if f"  {name}: lookup(" not in titles] == []

    def test_each_tool_has_an_icon_in_the_page(self) -> None:
        icons = (WEB_SOURCES / "components" / "call-icon.tsx").read_text()

        assert [name for name in tool_names() if f'case "{name}":' not in icons] == []
