"""Tests of the catalog of other people's MCP servers that a person adds with one click."""

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from virtual_lab.mcp_presets import MCP_PRESETS
from virtual_lab.server.app import create_app
from virtual_lab.server.config import Settings
from virtual_lab.server.mcp import MAX_SERVERS, check_entry, describe_servers, is_on, read_server, variables_in
from virtual_lab.server.mcp_catalog import GROUPS, MCP_CATALOG, SERVERS, describe_catalog
from virtual_lab.server.workspace import Workspace

from conftest import TEST_MODEL, FakeClient

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
def client(workspace: Workspace) -> Iterator[TestClient]:
    app = create_app(workspace.root, token=TOKEN, check_keys=False)
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


class TestTheCatalog:
    def test_every_server_is_one_that_can_be_set_up_as_it_is_listed(self) -> None:
        assert MCP_CATALOG
        for name, found in MCP_CATALOG.items():
            assert found.name == name
            kept = check_entry(name, found.entry)
            assert is_on(kept)
            assert read_server(name, kept, strict=True).url == found.entry["url"]

    def test_every_server_is_reached_over_https_with_nothing_to_give_it_but_a_sign_in(self) -> None:
        for found in MCP_CATALOG.values():
            address = urlsplit(found.entry["url"])
            assert address.scheme == "https" and address.hostname
            assert not (address.username or address.password or address.query)
            assert "headers" not in found.entry
            assert variables_in(found.entry) == []
            assert set(found.entry) <= {"url", "auth", "approval"}

    def test_no_server_is_named_as_a_preset_nor_twice_and_each_is_described(self) -> None:
        assert len(MCP_CATALOG) == len(SERVERS)
        assert not set(MCP_CATALOG) & set(MCP_PRESETS)
        for found in MCP_CATALOG.values():
            assert found.group in GROUPS
            assert found.title and found.about and found.maker
            assert urlsplit(found.site).scheme == "https"
        assert [group for group in GROUPS if all(found.group != group for found in MCP_CATALOG.values())] == []

    def test_a_server_that_changes_what_is_kept_where_it_is_signed_in_to_asks_before_every_call(self) -> None:
        signing_in = [found for found in MCP_CATALOG.values() if found.signs_in]

        assert signing_in
        for found in signing_in:
            assert found.entry["approval"] == {"ask": ["*"]}
            assert read_server(found.name, check_entry(found.name, found.entry)).auth == "oauth"

    def test_it_is_described_in_the_order_it_was_written_with_what_is_set_up_marked(self) -> None:
        stored = {"string_db": check_entry("string_db", MCP_CATALOG["string_db"].entry)}
        described = describe_catalog(stored)

        assert [each["name"] for each in described] == list(MCP_CATALOG)
        assert [each["name"] for each in described if each["added"]] == ["string_db"]
        string = next(each for each in described if each["name"] == "string_db")
        assert string["target"] == "https://mcp.string-db.org/"
        assert string["signs_in"] is False and string["asks"] is False
        synapse = next(each for each in described if each["name"] == "synapse")
        assert synapse["signs_in"] is True and synapse["asks"] is True

    def test_a_server_of_the_same_name_that_a_person_made_is_said_to_be_set_up(self) -> None:
        described = describe_catalog({"ols": {"url": "https://example.org/mcp"}})

        assert [each["name"] for each in described if each["added"]] == ["ols"]


class TestTheRoutes:
    def test_the_catalog_is_listed_with_none_set_up_to_begin_with(self, client: TestClient) -> None:
        response = client.get("/api/mcp/catalog")

        assert response.status_code == 200
        servers = response.json()["servers"]
        assert [server["name"] for server in servers] == list(MCP_CATALOG)
        assert not any(server["added"] for server in servers)
        assert set(servers[0]) == {
            "name",
            "title",
            "about",
            "group",
            "maker",
            "site",
            "target",
            "signs_in",
            "asks",
            "added",
        }

    def test_a_server_is_added_on_and_listed_with_the_others_and_in_the_catalog_as_added(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        added = client.post("/api/mcp/catalog/open_targets")

        assert added.status_code == 200
        listed = {server["name"]: server for server in added.json()["servers"]}
        assert listed["open_targets"]["enabled"] is True
        assert (listed["open_targets"]["preset"], listed["open_targets"]["added"]) == (False, True)
        assert listed["open_targets"]["target"] == "https://mcp.platform.opentargets.org/mcp"
        assert listed["open_targets"]["title"] == "Open Targets"
        assert listed["open_targets"]["about"] == MCP_CATALOG["open_targets"].about
        assert workspace.load_mcp_servers() == {"open_targets": dict(MCP_CATALOG["open_targets"].entry)}
        assert client.get("/api/mcp").json() == added.json()
        catalog = client.get("/api/mcp/catalog").json()["servers"]
        assert [server["name"] for server in catalog if server["added"]] == ["open_targets"]

    def test_a_server_that_is_signed_in_to_is_added_and_says_it_is_not_signed_in_yet(self, client: TestClient) -> None:
        added = client.post("/api/mcp/catalog/synapse")

        synapse = next(server for server in added.json()["servers"] if server["name"] == "synapse")
        assert (synapse["auth"], synapse["signed_in"], synapse["asks"]) == ("oauth", False, True)
        assert synapse["missing"] == [] and synapse["problem"] is None

    def test_a_server_is_not_added_twice_nor_over_one_that_is_set_up_under_its_name(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        mine = {"url": "https://example.org/mcp", "enabled": False}
        assert client.put("/api/mcp/servers/ols", json={"entry": mine}).status_code == 200
        assert client.post("/api/mcp/catalog/interpro").status_code == 200

        again = client.post("/api/mcp/catalog/interpro")
        over = client.post("/api/mcp/catalog/ols")

        assert (again.status_code, again.json()["error"]["code"]) == (409, "exists")
        assert over.status_code == 409
        assert workspace.load_mcp_servers()["ols"] == mine

    def test_a_server_added_from_the_catalog_keeps_its_title_and_what_it_is_for_whether_or_not_it_is_on(self) -> None:
        kept = check_entry("ols", MCP_CATALOG["ols"].entry)

        for entry in (kept, {**kept, "enabled": False}):
            (server,) = (each for each in describe_servers({"ols": entry}) if each["name"] == "ols")
            assert server["title"] == MCP_CATALOG["ols"].title
            assert server["about"] == MCP_CATALOG["ols"].about

    def test_a_server_of_a_persons_that_has_the_name_of_one_of_the_catalog_is_called_by_its_name(self) -> None:
        mine = {"url": "https://example.org/mcp"}

        (server,) = (each for each in describe_servers({"ols": mine}) if each["name"] == "ols")

        assert (server["title"], server["about"]) == ("ols", None)

    def test_a_server_that_is_not_in_the_catalog_is_not_found(self, client: TestClient) -> None:
        for name in ("nothing", "paperclip", "adaptyv"):
            assert client.post(f"/api/mcp/catalog/{name}").status_code == 404

    def test_no_more_servers_are_added_than_there_may_be(self, client: TestClient, workspace: Workspace) -> None:
        for number in range(MAX_SERVERS):
            workspace.put_mcp_server(f"mine{number}", {"url": "https://example.org/mcp"})

        response = client.post("/api/mcp/catalog/context7")

        assert response.status_code == 422
        assert "context7" not in workspace.load_mcp_servers()

    def test_the_catalog_needs_the_token_like_every_route(self, workspace: Workspace) -> None:
        with TestClient(create_app(workspace.root, token=TOKEN, check_keys=False), base_url=LOCAL) as bare:
            assert bare.get("/api/mcp/catalog").status_code == 401
            assert bare.post("/api/mcp/catalog/ols").status_code == 401

    def test_a_server_added_from_the_catalog_is_one_that_can_be_removed(self, client: TestClient) -> None:
        client.post("/api/mcp/catalog/deepwiki")

        removed = client.delete("/api/mcp/servers/deepwiki")

        assert removed.status_code == 200
        assert "deepwiki" not in {server["name"] for server in removed.json()["servers"]}
        assert [server["name"] for server in describe_servers({})] == ["paperclip", "proto", "proto_hosted"]
