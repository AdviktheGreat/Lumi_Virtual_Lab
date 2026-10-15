"""Tests of the MCP servers a person sets up for conversations, and what the settings say of each."""

import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from virtual_lab.mcp_presets import MCP_PRESETS
from virtual_lab.server.app import create_app
from virtual_lab.server.config import ChatConfig, resolve_config
from virtual_lab.server.mcp import (
    MAX_SERVERS,
    change_entry,
    check_entry,
    check_server_names,
    describe_server,
    describe_servers,
    is_on,
    program_missing,
    read_server,
    server_title,
    servers_on,
    service_keys,
    variables_in,
    with_defaults,
)
from virtual_lab.server.workspace import MCP_FILE_NAME, Settings, Workspace

from conftest import TEST_MODEL, FakeClient

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}

SERVICE_KEYS = ("PAPERCLIP_API_KEY", "FOUNDRY_API_TOKEN", "FOUNDRY_TESTING_TOKEN")

GENES = {"command": ["python", "genes.py"], "approval": {"ask": ["order"]}}
SEARCH = {"url": "https://search.example.org/mcp", "headers": {"Authorization": "Bearer ${SEARCH_TOKEN}"}}


@pytest.fixture(autouse=True)
def model_client(fake_client: FakeClient) -> FakeClient:
    return fake_client


@pytest.fixture(autouse=True)
def no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*SERVICE_KEYS, "SEARCH_TOKEN"):
        monkeypatch.delenv(name, raising=False)


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


def by_name(servers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {server["name"]: server for server in servers}


class TestReadingAnEntry:
    def test_variables_that_are_not_set_are_read_as_if_they_were(self) -> None:
        assert with_defaults("Bearer ${KEY}") == "Bearer ${KEY:-x}"
        assert with_defaults("${KEY:-given}") == "${KEY:-given}"
        assert with_defaults({"a": ["${A}", 3, {"b": "${B}"}], "c": None}) == {
            "a": ["${A:-x}", 3, {"b": "${B:-x}"}],
            "c": None,
        }

    def test_the_variables_an_entry_asks_for_are_those_without_a_default_each_once_in_order(self) -> None:
        entry = {"headers": {"A": "Bearer ${ONE}", "B": "${TWO}-${ONE}"}, "args": ["${THREE:-x}", "${FOUR}"], "n": 3}

        assert variables_in(entry) == ["ONE", "TWO", "FOUR"]
        assert variables_in("nothing") == []

    def test_a_server_is_read_as_connect_mcp_reads_it_whether_or_not_it_is_on(self) -> None:
        parsed = read_server("genes", {**GENES, "enabled": False})

        assert (parsed.name, parsed.transport) == ("genes", "stdio")
        assert (parsed.command, parsed.args) == ("python", ("genes.py",))
        assert parsed.needs_approval("order")

    def test_a_preset_is_read_with_its_own_entry_filled_in(self) -> None:
        parsed = read_server("paperclip", {"preset": "paperclip"})

        assert parsed.url == "https://paperclip.gxl.ai/mcp"
        assert parsed.headers == {"X-API-Key": "x"}

    def test_a_setting_that_is_not_used_is_an_error_where_connect_mcp_only_warns(self) -> None:
        with pytest.raises(ValueError, match="settings that are not used: colour"):
            read_server("genes", {**GENES, "colour": "red"})

    def test_an_entry_that_cannot_be_read_says_what_is_wrong(self) -> None:
        with pytest.raises(ValueError, match="needs a command to start it, or a url to reach it at"):
            read_server("genes", {})
        with pytest.raises(ValueError, match="not an http:// or https:// URL"):
            read_server("genes", {"url": "ftp://example.org"})


class TestCheckingAnEntry:
    def test_a_server_of_ones_own_is_kept_as_it_was_given(self) -> None:
        assert check_entry("genes", GENES) == GENES
        assert check_entry("search", SEARCH) == SEARCH

    def test_what_is_kept_is_a_copy(self) -> None:
        given = {"command": ["python", "genes.py"]}

        kept = check_entry("genes", given)
        kept["command"].append("changed")

        assert given == {"command": ["python", "genes.py"]}

    def test_a_key_that_is_not_set_yet_is_not_an_error(self) -> None:
        assert check_entry("search", SEARCH) == SEARCH
        assert "SEARCH_TOKEN" not in os.environ

    def test_a_preset_is_kept_by_its_own_name_and_may_be_turned_off_or_signed_in_to(self) -> None:
        assert check_entry("paperclip", {"preset": "paperclip"}) == {"preset": "paperclip"}
        assert check_entry("paperclip", {"preset": "paperclip", "enabled": False, "auth": "oauth"}) == {
            "preset": "paperclip",
            "enabled": False,
            "auth": "oauth",
        }

    @pytest.mark.parametrize("name", ["", "1genes", "_genes", "my-genes", "my genes", "genes!", "g" * 33, 3, None])
    def test_a_name_starts_with_a_letter_and_is_made_of_letters_digits_and_underscores(self, name: Any) -> None:
        with pytest.raises(ValueError, match="starts with a letter and is made of letters, digits, and _, at most 32"):
            check_entry(name, GENES)

    def test_the_name_of_a_preset_is_for_the_preset(self) -> None:
        with pytest.raises(ValueError, match="paperclip is the name of a preset"):
            check_entry("paperclip", GENES)
        with pytest.raises(ValueError, match="paperclip is the name of a preset"):
            check_entry("paperclip", {"preset": "adaptyv"})

    def test_a_preset_that_is_not_one_is_refused_and_the_presets_there_are_are_said(self) -> None:
        with pytest.raises(ValueError, match="uses the preset 'nothing', which is not one. The presets are: paperclip"):
            check_entry("mine", {"preset": "nothing"})

    @pytest.mark.parametrize("entry", [None, [], "genes.py", 3])
    def test_it_is_a_mapping(self, entry: Any) -> None:
        with pytest.raises(ValueError, match="described by a mapping"):
            check_entry("genes", entry)

    def test_it_is_json(self) -> None:
        with pytest.raises(ValueError, match="described in JSON"):
            check_entry("genes", {"command": ["python"], "env": {"A": object()}})

    @pytest.mark.parametrize("key", ["enabled", "disabled"])
    def test_whether_it_is_on_is_true_or_false(self, key: str) -> None:
        with pytest.raises(ValueError, match=f"{key} of the server genes must be true or false, not 'no'"):
            check_entry("genes", {**GENES, key: "no"})

    def test_a_setting_that_is_not_used_is_refused(self) -> None:
        with pytest.raises(ValueError, match="settings that are not used: colour"):
            check_entry("genes", {**GENES, "colour": "red"})

    def test_a_program_started_here_has_no_sign_in_or_headers(self) -> None:
        with pytest.raises(ValueError, match="is started here, so headers is not used"):
            check_entry("genes", {**GENES, "headers": {"A": "b"}})

    def test_a_directory_it_starts_in_is_one_that_is_there(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="is not a directory"):
            check_entry("genes", {**GENES, "cwd": str(tmp_path / "nowhere")})

        assert check_entry("genes", {**GENES, "cwd": str(tmp_path)})["cwd"] == str(tmp_path)


class TestWhatTheSettingsShow:
    def test_the_presets_are_listed_first_in_the_librarys_order_and_none_is_on_until_set_up(self) -> None:
        servers = describe_servers({})

        assert [server["name"] for server in servers] == list(MCP_PRESETS)
        assert [server["title"] for server in servers] == [preset.title for preset in MCP_PRESETS.values()]
        assert not any(server["added"] or server["enabled"] for server in servers)
        assert all(server["preset"] for server in servers)
        assert [server["about"] for server in servers] == [preset.about for preset in MCP_PRESETS.values()]

    def test_servers_of_ones_own_follow_in_the_order_they_were_set_up(self) -> None:
        servers = describe_servers({"genes": GENES, "paperclip": {"preset": "paperclip"}, "search": SEARCH})

        assert [server["name"] for server in servers] == [*MCP_PRESETS, "genes", "search"]
        own = by_name(servers)["genes"]
        assert (own["title"], own["about"], own["preset"]) == ("genes", None, False)
        assert (own["added"], own["enabled"]) == (True, True)
        assert (own["transport"], own["target"], own["asks"], own["setup"]) == ("stdio", "python genes.py", True, None)

    def test_a_preset_that_was_set_up_is_on_unless_it_was_turned_off(self) -> None:
        stored = {"paperclip": {"preset": "paperclip"}, "adaptyv": {"preset": "adaptyv", "enabled": False}}
        servers = by_name(describe_servers(stored))

        assert servers["paperclip"]["added"] and servers["paperclip"]["enabled"]
        assert servers["adaptyv"]["added"] and not servers["adaptyv"]["enabled"]
        assert servers["adaptyv"]["target"] == "https://mcp.adaptyvbio.com/mcp/"

    def test_a_key_that_is_not_set_is_missing_and_may_be_given_in_the_interface(self) -> None:
        paperclip = by_name(describe_servers({}))["paperclip"]

        assert paperclip["missing"] == [{"name": "PAPERCLIP_API_KEY", "settable": True}]
        assert paperclip["auth"] == "key"
        assert paperclip["auth_choices"] == ["key", "oauth"]
        assert paperclip["transport"] == "http"
        assert paperclip["problem"] is None
        assert "PAPERCLIP_API_KEY" in paperclip["setup"]

    def test_a_key_that_is_set_is_not_missing_and_is_never_shown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PAPERCLIP_API_KEY", "gxl_the-secret")

        servers = describe_servers({"paperclip": {"preset": "paperclip"}})

        assert by_name(servers)["paperclip"]["missing"] == []
        assert "gxl_the-secret" not in json.dumps(servers)

    def test_a_key_that_is_set_and_may_be_given_in_the_interface_is_said_to_be(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PAPERCLIP_API_KEY", "gxl_the-secret")
        monkeypatch.setenv("SEARCH_TOKEN", "the-other-secret")

        servers = by_name(describe_servers({"paperclip": {"preset": "paperclip"}, "search": SEARCH}))

        assert servers["paperclip"]["keys_set"] == ["PAPERCLIP_API_KEY"]
        # A server of a person's own asks for what it wants from the environment, which the interface does not change
        assert servers["search"]["keys_set"] == []
        assert servers["adaptyv"]["keys_set"] == []
        assert "the-other-secret" not in json.dumps(servers)

    def test_a_server_that_is_signed_in_to_needs_no_key(self) -> None:
        servers = by_name(describe_servers({"paperclip": {"preset": "paperclip", "auth": "oauth"}}))

        assert servers["paperclip"]["missing"] == []
        assert servers["paperclip"]["auth"] == "oauth"
        assert "signed in to" in servers["paperclip"]["setup"]
        assert servers["proto_hosted"]["auth"] == "oauth"
        assert servers["proto_hosted"]["auth_choices"] == []
        assert servers["proto_hosted"]["missing"] == []

    def test_a_key_of_a_server_of_ones_own_is_missing_but_cannot_be_given_in_the_interface(self) -> None:
        search = by_name(describe_servers({"search": SEARCH}))["search"]

        assert search["missing"] == [{"name": "SEARCH_TOKEN", "settable": False}]
        assert search["auth"] is None
        assert search["transport"] == "http"
        assert search["target"] == "https://search.example.org/mcp"

    def test_the_servers_whose_tools_wait_for_approval_say_so(self) -> None:
        servers = by_name(describe_servers({"genes": GENES, "search": SEARCH}))

        assert servers["adaptyv"]["asks"] is True
        assert servers["proto"]["asks"] is True
        assert servers["genes"]["asks"] is True
        assert servers["paperclip"]["asks"] is False
        assert servers["search"]["asks"] is False

    def test_a_program_that_is_not_installed_is_a_problem_with_what_to_do_about_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda command: None)

        proto = by_name(describe_servers({}))["proto"]

        assert proto["transport"] == "stdio"
        assert proto["target"] == "proto-tools-mcp"
        assert proto["problem"] == (
            "The program proto-tools-mcp is not installed here, or is not where the server looks for it."
        )
        assert "uv tool install" in proto["setup"]

    def test_a_program_that_is_installed_is_no_problem(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda command: f"/usr/bin/{command}")

        assert by_name(describe_servers({}))["proto"]["problem"] is None

    def test_a_program_is_looked_for_on_the_path_or_where_it_is_given(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda command: None)
        (tmp_path / "server.sh").write_text("")

        assert program_missing("proto-tools-mcp", None)
        assert not program_missing("./server.sh", str(tmp_path))
        assert program_missing("./other.sh", str(tmp_path))
        assert not program_missing(str(tmp_path / "server.sh"), None)
        assert not program_missing(None, None)

    def test_an_entry_that_cannot_be_read_is_a_problem_and_the_server_is_still_listed(self) -> None:
        genes = by_name(describe_servers({"genes": {"colour": "red"}}))["genes"]

        assert genes["problem"] == "The server genes has settings that are not used: colour"
        assert genes["transport"] is None
        assert genes["target"] is None
        assert genes["missing"] == []
        assert genes["enabled"] is True

    def test_a_server_is_described_whether_or_not_it_is_listed(self) -> None:
        assert describe_server("genes", GENES) == by_name(describe_servers({"genes": GENES}))["genes"]
        assert describe_server("paperclip", None) == by_name(describe_servers({}))["paperclip"]

    def test_a_preset_name_with_an_entry_that_is_not_its_own_is_shown_as_what_it_is(self) -> None:
        shown = describe_server("paperclip", GENES)

        assert (shown["preset"], shown["title"], shown["target"]) == (False, "paperclip", "python genes.py")

    def test_a_preset_is_called_by_its_title_and_any_other_server_by_its_name(self) -> None:
        assert server_title("proto_hosted", {"preset": "proto_hosted"}) == "Proto, hosted"
        assert server_title("proto_hosted", None) == "Proto, hosted"
        assert server_title("genes", GENES) == "genes"
        assert server_title("lab", {"preset": "adaptyv_testing"}) == "lab"
        assert server_title("paperclip", GENES) == "paperclip"

    def test_a_server_is_on_unless_it_says_it_is_off(self) -> None:
        assert is_on({})
        assert is_on({"enabled": True})
        assert not is_on({"enabled": False})
        assert not is_on({"disabled": True})
        assert not is_on({"enabled": "no"})

    def test_the_servers_that_are_on_are_those_a_new_conversation_is_given(self) -> None:
        stored = {"genes": GENES, "search": {**SEARCH, "enabled": False}, "paperclip": {"preset": "paperclip"}}

        assert servers_on(stored) == ["genes", "paperclip"]

    def test_the_servers_to_give_a_conversation_are_checked_against_those_set_up(self) -> None:
        stored = {"genes": GENES, "search": SEARCH}

        assert check_server_names(["search", "genes", "search"], stored) == ["search", "genes"]
        assert check_server_names([], stored) == []
        with pytest.raises(ValueError, match="There is no server paperclip set up: the servers are genes, search"):
            check_server_names(["genes", "paperclip"], stored)
        with pytest.raises(ValueError, match="list of names"):
            check_server_names("genes", stored)
        with pytest.raises(ValueError, match="There is no server 3"):
            check_server_names([3], stored)

    def test_the_keys_that_can_be_given_are_those_of_the_presets_services_and_no_more(self) -> None:
        assert service_keys() == SERVICE_KEYS


class TestChangingAnEntry:
    def test_a_preset_that_was_not_set_up_is_set_up_by_being_turned_on_or_off(self) -> None:
        assert change_entry("paperclip", None, True, None) == {"preset": "paperclip"}
        assert change_entry("paperclip", None, False, None) == {"preset": "paperclip", "enabled": False}

    def test_being_on_is_said_by_leaving_out_whether_it_is(self) -> None:
        assert change_entry("paperclip", {"preset": "paperclip", "enabled": False}, True, None) == {
            "preset": "paperclip"
        }
        assert change_entry("genes", {**GENES, "disabled": True}, True, None) == GENES
        assert change_entry("genes", {**GENES, "disabled": True}, False, None) == {**GENES, "enabled": False}

    def test_nothing_else_of_the_entry_is_changed(self) -> None:
        entry = {"preset": "paperclip", "auth": "oauth", "instructions": "Mine.", "approval": {"ask": ["*"]}}

        assert change_entry("paperclip", entry, False, None) == {**entry, "enabled": False}
        assert change_entry("genes", {**GENES, "env": {"A": "b"}}, False, None) == {
            **GENES,
            "env": {"A": "b"},
            "enabled": False,
        }

    def test_a_preset_is_signed_in_to_or_given_a_key(self) -> None:
        assert change_entry("paperclip", None, None, "oauth") == {"preset": "paperclip", "auth": "oauth"}
        assert change_entry("paperclip", {"preset": "paperclip", "auth": "oauth"}, None, "key") == {
            "preset": "paperclip"
        }
        assert change_entry("paperclip", None, False, "oauth") == {
            "preset": "paperclip",
            "enabled": False,
            "auth": "oauth",
        }

    @pytest.mark.parametrize("name", ["genes", "proto", "proto_hosted"])
    def test_only_a_preset_that_has_a_key_and_a_sign_in_has_the_choice(self, name: str) -> None:
        entry = {"preset": name} if name in MCP_PRESETS else GENES

        with pytest.raises(ValueError, match="is not one that is given a key or signed in to as you choose"):
            change_entry(name, entry, None, "oauth")

    def test_a_server_that_is_not_there_cannot_be_changed(self) -> None:
        with pytest.raises(KeyError):
            change_entry("genes", None, True, None)

    def test_what_is_made_is_checked_like_any_other_entry(self) -> None:
        with pytest.raises(ValueError, match="has settings that are not used: colour"):
            change_entry("genes", {**GENES, "colour": "red"}, True, None)

    def test_the_entry_given_is_not_changed(self) -> None:
        entry = {**GENES, "enabled": False}

        change_entry("genes", entry, True, None)

        assert entry == {**GENES, "enabled": False}


class TestWhatTheWorkspaceKeeps:
    def test_nothing_is_set_up_until_something_is(self, workspace: Workspace) -> None:
        assert workspace.load_mcp_servers() == {}
        assert not workspace.mcp_path.exists()

    def test_servers_are_kept_in_the_order_they_were_set_up_and_a_change_keeps_a_place(
        self, workspace: Workspace
    ) -> None:
        workspace.put_mcp_server("genes", GENES)
        workspace.put_mcp_server("search", SEARCH)
        workspace.put_mcp_server("genes", {**GENES, "enabled": False})

        assert workspace.mcp_path == workspace.root / MCP_FILE_NAME
        assert list(workspace.load_mcp_servers()) == ["genes", "search"]
        assert workspace.load_mcp_servers()["genes"]["enabled"] is False
        assert list(json.loads(workspace.mcp_path.read_text())) == ["servers"]

    def test_a_server_that_is_forgotten_is_gone(self, workspace: Workspace) -> None:
        workspace.put_mcp_server("genes", GENES)

        assert workspace.remove_mcp_server("genes") is True
        assert workspace.remove_mcp_server("genes") is False
        assert workspace.load_mcp_servers() == {}

    @pytest.mark.parametrize("saved", ["not json", "[]", '"genes"', '{"servers": []}', '{"servers": null}', "{}"])
    def test_a_file_that_cannot_be_understood_sets_up_nothing(self, workspace: Workspace, saved: str) -> None:
        workspace.mcp_path.write_text(saved)

        assert workspace.load_mcp_servers() == {}

    def test_an_entry_that_is_not_a_mapping_is_left_out(self, workspace: Workspace) -> None:
        workspace.mcp_path.write_text(json.dumps({"servers": {"genes": GENES, "bad": "x", "worse": [1], "3": None}}))

        assert list(workspace.load_mcp_servers()) == ["genes"]

    def test_changes_made_at_the_same_time_do_not_undo_each_other(self, workspace: Workspace) -> None:
        threads = [
            threading.Thread(target=workspace.put_mcp_server, args=(f"server{number}", GENES)) for number in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(workspace.load_mcp_servers()) == sorted(f"server{number}" for number in range(20))


class TestUpdatingAServerThatIsKept:
    def test_the_change_is_given_what_is_kept_and_what_it_gives_is_kept_in_its_place(
        self, workspace: Workspace
    ) -> None:
        workspace.put_mcp_server("genes", GENES)
        workspace.put_mcp_server("search", SEARCH)
        seen: list[Any] = []

        def change(entry: Any) -> dict[str, Any]:
            seen.append(entry)
            return {**entry, "enabled": False}

        kept = workspace.update_mcp_server("genes", change)

        assert seen == [GENES]
        assert kept == {**GENES, "enabled": False}
        assert workspace.load_mcp_servers() == {"genes": {**GENES, "enabled": False}, "search": SEARCH}

    def test_a_server_that_is_not_kept_is_given_as_none_and_is_added_last(self, workspace: Workspace) -> None:
        workspace.put_mcp_server("genes", GENES)

        workspace.update_mcp_server("paperclip", lambda entry: {"preset": "paperclip"} if entry is None else entry)

        assert list(workspace.load_mcp_servers()) == ["genes", "paperclip"]

    def test_a_change_that_fails_keeps_nothing(self, workspace: Workspace) -> None:
        workspace.put_mcp_server("genes", GENES)

        def fails(entry: Any) -> dict[str, Any]:
            raise ValueError("no")

        with pytest.raises(ValueError, match="no"):
            workspace.update_mcp_server("genes", fails)

        assert workspace.load_mcp_servers() == {"genes": GENES}

    def test_changes_made_at_the_same_time_all_take_effect(self, workspace: Workspace) -> None:
        workspace.put_mcp_server("genes", {"command": ["python"], "env": {}})

        def add(number: int) -> None:
            workspace.update_mcp_server("genes", lambda entry: {**entry, "env": {**entry["env"], f"V{number}": "x"}})

        threads = [threading.Thread(target=add, args=(number,)) for number in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(workspace.load_mcp_servers()["genes"]["env"]) == sorted(f"V{number}" for number in range(20))


class TestWhatAConversationIsSetUpWith:
    def test_it_has_the_servers_that_are_on(self, workspace: Workspace) -> None:
        workspace.put_mcp_server("genes", GENES)
        workspace.put_mcp_server("search", {**SEARCH, "enabled": False})

        config = resolve_config({}, workspace.load_settings(), workspace)

        assert config.mcp == ("genes",)

    def test_it_has_none_until_one_is_set_up(self, workspace: Workspace) -> None:
        assert resolve_config({}, workspace.load_settings(), workspace).mcp == ()

    def test_the_request_chooses_which_whether_or_not_they_are_on(self, workspace: Workspace) -> None:
        workspace.put_mcp_server("genes", GENES)
        workspace.put_mcp_server("search", {**SEARCH, "enabled": False})

        config = resolve_config({"mcp": ["search"]}, workspace.load_settings(), workspace)

        assert config.mcp == ("search",)
        assert resolve_config({"mcp": []}, workspace.load_settings(), workspace).mcp == ()

    @pytest.mark.parametrize("mcp", [["nothing"], "genes", 3])
    def test_a_server_that_was_not_set_up_is_refused(self, workspace: Workspace, mcp: Any) -> None:
        workspace.put_mcp_server("genes", GENES)

        with pytest.raises(ValueError):
            resolve_config({"mcp": mcp}, workspace.load_settings(), workspace)

    def test_it_is_kept_with_the_conversation_as_it_was_and_read_back(self, workspace: Workspace) -> None:
        workspace.put_mcp_server("genes", GENES)
        config = resolve_config({}, workspace.load_settings(), workspace)

        saved = config.to_dict()

        assert saved["mcp"] == ["genes"]
        assert ChatConfig.from_dict(saved) == config

    def test_a_conversation_begun_before_the_lead_could_be_given_servers_goes_on_without_them(
        self, workspace: Workspace
    ) -> None:
        saved = resolve_config({}, workspace.load_settings(), workspace).to_dict()
        del saved["mcp"]

        assert ChatConfig.from_dict(saved).mcp == ()

    def test_a_name_written_twice_in_what_was_kept_is_one_server(self, workspace: Workspace) -> None:
        saved = resolve_config({}, workspace.load_settings(), workspace).to_dict()
        saved["mcp"] = ["genes", "search", "genes"]

        assert ChatConfig.from_dict(saved).mcp == ("genes", "search")


class TestTheRoutes:
    def test_the_presets_are_listed_with_none_set_up_to_begin_with(self, client: TestClient) -> None:
        response = client.get("/api/mcp")

        assert response.status_code == 200
        servers = response.json()["servers"]
        assert [server["name"] for server in servers] == list(MCP_PRESETS)
        assert not any(server["enabled"] for server in servers)

    def test_a_preset_is_turned_on_and_listed_back(self, client: TestClient, workspace: Workspace) -> None:
        changed = client.put("/api/mcp/servers/paperclip", json={"entry": {"preset": "paperclip"}})

        assert changed.status_code == 200
        assert by_name(changed.json()["servers"])["paperclip"]["enabled"] is True
        assert client.get("/api/mcp").json() == changed.json()
        assert workspace.load_mcp_servers() == {"paperclip": {"preset": "paperclip"}}

    def test_a_preset_is_turned_off_and_signed_in_to_instead_of_given_a_key(self, client: TestClient) -> None:
        client.put("/api/mcp/servers/paperclip", json={"entry": {"preset": "paperclip"}})

        changed = client.put(
            "/api/mcp/servers/paperclip", json={"entry": {"preset": "paperclip", "enabled": False, "auth": "oauth"}}
        )

        paperclip = by_name(changed.json()["servers"])["paperclip"]
        assert (paperclip["enabled"], paperclip["auth"], paperclip["missing"]) == (False, "oauth", [])

    def test_a_preset_is_turned_on_by_a_change_without_it_having_been_set_up(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        changed = client.patch("/api/mcp/servers/paperclip", json={"enabled": True})

        assert changed.status_code == 200
        assert by_name(changed.json()["servers"])["paperclip"]["enabled"] is True
        assert workspace.load_mcp_servers() == {"paperclip": {"preset": "paperclip"}}

    def test_a_change_leaves_the_rest_of_the_entry_as_it_was(self, client: TestClient, workspace: Workspace) -> None:
        entry = {"preset": "paperclip", "instructions": "Mine."}
        assert client.put("/api/mcp/servers/paperclip", json={"entry": entry}).status_code == 200
        assert client.put("/api/mcp/servers/genes", json={"entry": GENES}).status_code == 200

        off = client.patch("/api/mcp/servers/paperclip", json={"enabled": False})
        signed = client.patch("/api/mcp/servers/paperclip", json={"auth": "oauth"})
        genes = client.patch("/api/mcp/servers/genes", json={"enabled": False})

        assert by_name(off.json()["servers"])["paperclip"]["enabled"] is False
        paperclip = by_name(signed.json()["servers"])["paperclip"]
        assert (paperclip["enabled"], paperclip["auth"]) == (False, "oauth")
        assert by_name(genes.json()["servers"])["genes"]["enabled"] is False
        assert workspace.load_mcp_servers() == {
            "paperclip": {**entry, "enabled": False, "auth": "oauth"},
            "genes": {**GENES, "enabled": False},
        }

    def test_a_server_that_is_not_there_is_not_found(self, client: TestClient) -> None:
        response = client.patch("/api/mcp/servers/genes", json={"enabled": True})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    @pytest.mark.parametrize(
        ("name", "body"),
        [
            ("paperclip", {}),
            ("paperclip", {"enabled": None, "auth": None}),
            ("paperclip", {"enabled": "yes"}),
            ("paperclip", {"enabled": 1}),
            ("paperclip", {"auth": "password"}),
            ("paperclip", {"enabled": True, "other": 1}),
            ("proto", {"auth": "oauth"}),
            ("genes", {"auth": "oauth"}),
        ],
    )
    def test_a_change_that_cannot_be_made_is_refused_and_changes_nothing(
        self, client: TestClient, workspace: Workspace, name: str, body: dict[str, Any]
    ) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})
        client.put("/api/mcp/servers/proto", json={"entry": {"preset": "proto"}})
        before = workspace.load_mcp_servers()

        response = client.patch(f"/api/mcp/servers/{name}", json=body)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid"
        assert workspace.load_mcp_servers() == before

    def test_a_server_of_ones_own_is_set_up_listed_and_forgotten(self, client: TestClient) -> None:
        added = client.put("/api/mcp/servers/genes", json={"entry": GENES})

        assert [server["name"] for server in added.json()["servers"]][-1] == "genes"
        removed = client.delete("/api/mcp/servers/genes")
        assert removed.status_code == 200
        assert "genes" not in by_name(removed.json()["servers"])

    def test_a_preset_that_is_forgotten_is_as_if_it_had_not_been_set_up(self, client: TestClient) -> None:
        client.put("/api/mcp/servers/paperclip", json={"entry": {"preset": "paperclip"}})

        removed = client.delete("/api/mcp/servers/paperclip")

        paperclip = by_name(removed.json()["servers"])["paperclip"]
        assert not paperclip["added"] and not paperclip["enabled"]

    def test_forgetting_a_server_that_was_not_set_up_is_not_found(self, client: TestClient) -> None:
        response = client.delete("/api/mcp/servers/genes")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    @pytest.mark.parametrize(
        ("name", "body"),
        [
            ("genes", {"entry": {}}),
            ("genes", {"entry": {"command": 3}}),
            ("genes", {"entry": {**GENES, "colour": "red"}}),
            ("my-genes", {"entry": GENES}),
            ("paperclip", {"entry": GENES}),
            ("genes", {"entry": "genes.py"}),
            ("genes", {"entry": GENES, "extra": 1}),
            ("genes", {}),
        ],
    )
    def test_what_cannot_be_used_is_refused_and_changes_nothing(
        self, client: TestClient, workspace: Workspace, name: str, body: dict[str, Any]
    ) -> None:
        client.put("/api/mcp/servers/search", json={"entry": SEARCH})

        response = client.put(f"/api/mcp/servers/{name}", json=body)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid"
        assert list(workspace.load_mcp_servers()) == ["search"]

    def test_the_message_says_what_is_wrong_with_the_entry(self, client: TestClient) -> None:
        response = client.put("/api/mcp/servers/genes", json={"entry": {"url": "ftp://example.org"}})

        assert "not an http:// or https:// URL" in response.json()["error"]["message"]

    def test_no_more_servers_than_the_limit_can_be_set_up(self, client: TestClient, workspace: Workspace) -> None:
        for number in range(MAX_SERVERS):
            workspace.put_mcp_server(f"server{number}", GENES)

        response = client.put("/api/mcp/servers/one_more", json={"entry": GENES})

        assert response.status_code == 422
        assert f"At most {MAX_SERVERS} servers" in response.json()["error"]["message"]
        assert client.put("/api/mcp/servers/server0", json={"entry": {**GENES, "enabled": False}}).status_code == 200

    def test_the_servers_need_the_token_like_every_other_route(self, workspace: Workspace) -> None:
        with TestClient(create_app(workspace.root, token=TOKEN, check_keys=False), base_url=LOCAL) as bare:
            assert bare.get("/api/mcp").status_code == 401
            assert bare.put("/api/mcp/servers/genes", json={"entry": GENES}).status_code == 401
            assert bare.patch("/api/mcp/servers/paperclip", json={"enabled": True}).status_code == 401
            assert bare.delete("/api/mcp/servers/genes").status_code == 401

    def test_a_new_conversation_is_set_up_with_the_servers_that_are_on(self, client: TestClient) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})
        client.put("/api/mcp/servers/search", json={"entry": {**SEARCH, "enabled": False}})

        made = client.post("/api/chats", json={"team": []}).json()

        assert made["config"]["mcp"] == ["genes"]

    def test_a_new_conversation_can_be_given_servers_of_its_own_choosing(self, client: TestClient) -> None:
        client.put("/api/mcp/servers/genes", json={"entry": GENES})
        client.put("/api/mcp/servers/search", json={"entry": SEARCH})

        made = client.post("/api/chats", json={"team": [], "mcp": ["search"]}).json()

        assert made["config"]["mcp"] == ["search"]

    def test_a_server_that_was_not_set_up_cannot_be_given_to_a_conversation_and_nothing_is_left_behind(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        response = client.post("/api/chats", json={"team": [], "mcp": ["nothing"]})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid"
        assert list(workspace.chats_dir.iterdir()) == []


class TestTheKeysOfTheServices:
    def test_a_key_is_given_for_the_rest_of_the_process_and_is_then_not_missing(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = client.put("/api/keys/PAPERCLIP_API_KEY", json={"value": "  gxl_secret  "})

        assert response.status_code == 200
        assert os.environ["PAPERCLIP_API_KEY"] == "gxl_secret"
        servers = client.get("/api/mcp").json()["servers"]
        assert by_name(servers)["paperclip"]["missing"] == []
        assert "gxl_secret" not in response.text
        assert "gxl_secret" not in json.dumps(servers)
        assert "PAPERCLIP_API_KEY" not in response.json()["settable"]

    def test_a_key_that_is_taken_away_is_missing_again(self, client: TestClient) -> None:
        client.put("/api/keys/FOUNDRY_API_TOKEN", json={"value": "token"})

        assert client.delete("/api/keys/FOUNDRY_API_TOKEN").status_code == 200

        assert "FOUNDRY_API_TOKEN" not in os.environ
        assert by_name(client.get("/api/mcp").json()["servers"])["adaptyv"]["missing"] == [
            {"name": "FOUNDRY_API_TOKEN", "settable": True}
        ]

    @pytest.mark.parametrize("name", ["PATH", "SEARCH_TOKEN", "LD_PRELOAD", "HOME", "paperclip_api_key"])
    def test_no_other_variable_can_be_set_or_removed(self, client: TestClient, name: str) -> None:
        before = dict(os.environ)

        assert client.put(f"/api/keys/{name}", json={"value": "x"}).status_code == 422
        assert client.delete(f"/api/keys/{name}").status_code == 422

        assert dict(os.environ) == before

    def test_the_keys_of_the_model_providers_are_given_as_they_were(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)

        response = client.put("/api/keys/GROQ_API_KEY", json={"value": "gsk_secret"})

        assert response.status_code == 200
        assert response.json()["settable"] == ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"]
        monkeypatch.delenv("GROQ_API_KEY")
