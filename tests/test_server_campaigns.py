"""Tests of campaigns: that they are kept, that a program is one of at most one, and that the lead of each of its
programs is told the goal they share."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MODEL, FakeClient, text_response
from fastapi.testclient import TestClient
from test_server_app import BEARER, LOCAL, TOKEN, error_of
from test_server_conversations import hold_the_model, wait_until

from virtual_lab.server import campaigns as campaigns_module
from virtual_lab.server.app import create_app
from virtual_lab.server.campaigns import Campaigns
from virtual_lab.server.config import CONFIG_FILE_NAME, ChatConfig, load_config, resolve_config
from virtual_lab.server.conversations import ChatHandle, Conversations
from virtual_lab.server.errors import ApiError
from virtual_lab.server.workspace import CAMPAIGN_ID_PATTERN, Settings, Workspace


@pytest.fixture(autouse=True)
def model_client(fake_client: FakeClient) -> FakeClient:
    return fake_client


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    store = Workspace(tmp_path / "workspace")
    store.save_settings(Settings(model=TEST_MODEL, max_cost=None))

    return store


@pytest.fixture
def campaigns(workspace: Workspace) -> Campaigns:
    return Campaigns(workspace)


@pytest.fixture
def conversations(workspace: Workspace) -> Iterator[Conversations]:
    kept = Conversations(workspace, check_keys=False)
    yield kept
    kept.close()


@pytest.fixture
def client(workspace: Workspace) -> Iterator[TestClient]:
    with TestClient(
        create_app(workspace.root, token=TOKEN, check_keys=False), base_url=LOCAL, headers=BEARER
    ) as opened:
        yield opened


def say(handle: ChatHandle, message: str = "Hello") -> None:
    handle.chat.start(message).join(20)
    assert handle.chat.state == "idle"


def system_of(fake_client: FakeClient, call: int = -1) -> str:
    return fake_client.completions.calls[call]["messages"][0]["content"]


def refused(problem: ApiError, status: int) -> str:
    assert problem.status == status
    return problem.message


class TestKeepingCampaigns:
    def test_a_campaign_is_made_with_a_name_and_a_goal_and_is_found_again(
        self, campaigns: Campaigns, workspace: Workspace
    ) -> None:
        made = campaigns.create("  Nanobody   screen ", "  Find a binder for KP.3.\n")

        assert made["name"] == "Nanobody screen"
        assert made["brief"] == "Find a binder for KP.3."
        assert CAMPAIGN_ID_PATTERN.fullmatch(made["id"]) and made["id"].startswith("nanobody-screen-")
        assert made["created_at"] and made["updated_at"] == made["created_at"]
        assert campaigns.get(made["id"]) == made
        assert Campaigns(workspace).load() == [made]

    def test_a_goal_may_be_left_out(self, campaigns: Campaigns) -> None:
        assert campaigns.create("Just a group")["brief"] == ""

    def test_campaigns_are_listed_in_the_order_they_were_made(self, campaigns: Campaigns) -> None:
        names = ["Zebra", "Antelope", "Marmot"]
        for name in names:
            campaigns.create(name)

        assert [item["name"] for item in campaigns.load()] == names

    @pytest.mark.parametrize("name", ["", "   \n ", "x" * 81, "bell\x07", None, 7])
    def test_a_name_with_nothing_in_it_or_too_long_or_not_text_is_refused(
        self, campaigns: Campaigns, name: Any
    ) -> None:
        with pytest.raises(ApiError) as caught:
            campaigns.create(name)

        assert caught.value.status == 422
        assert campaigns.load() == []

    def test_a_goal_that_is_too_long_is_refused_and_one_at_the_limit_is_not(self, campaigns: Campaigns) -> None:
        campaigns.create("At the limit", "x" * 8000)

        with pytest.raises(ApiError) as caught:
            campaigns.create("Over it", "x" * 8001)

        assert "at most 8,000 characters" in refused(caught.value, 422)
        with pytest.raises(ApiError):
            campaigns.create("Not text", ["a goal"])

    def test_two_campaigns_may_not_have_a_name_that_differs_only_in_case(self, campaigns: Campaigns) -> None:
        campaigns.create("Nanobody screen")

        with pytest.raises(ApiError) as caught:
            campaigns.create(" nanobody  SCREEN")

        assert "called nanobody SCREEN already" in refused(caught.value, 409)
        assert len(campaigns.load()) == 1

    def test_there_may_be_only_so_many(self, campaigns: Campaigns, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(campaigns_module, "MAX_CAMPAIGNS", 2)
        campaigns.create("One")
        campaigns.create("Two")

        with pytest.raises(ApiError) as caught:
            campaigns.create("Three")

        assert "at most 2 campaigns" in refused(caught.value, 409)

    def test_a_campaign_made_after_one_of_its_name_was_deleted_has_another_id(self, campaigns: Campaigns) -> None:
        first = campaigns.create("Screen")
        campaigns.remove(first["id"])

        assert campaigns.create("Screen")["id"] != first["id"]

    def test_the_name_and_the_goal_are_changed_alone_or_together_and_the_time_it_was_changed_is_kept(
        self, campaigns: Campaigns
    ) -> None:
        made = campaigns.create("Screen", "Old goal.")

        renamed = campaigns.update(made["id"], {"name": " Binder   screen "})
        reworded = campaigns.update(made["id"], {"brief": "  New goal. "})
        both = campaigns.update(made["id"], {"name": "Final", "brief": ""})

        assert (renamed["name"], renamed["brief"]) == ("Binder screen", "Old goal.")
        assert (reworded["name"], reworded["brief"]) == ("Binder screen", "New goal.")
        assert (both["name"], both["brief"]) == ("Final", "")
        assert both["id"] == made["id"] and both["created_at"] == made["created_at"]
        assert both["updated_at"] >= made["updated_at"]
        assert campaigns.get(made["id"]) == both

    def test_a_change_that_changes_nothing_leaves_the_time_alone(self, campaigns: Campaigns) -> None:
        made = campaigns.create("Screen", "Goal.")

        assert campaigns.update(made["id"], {"name": "Screen", "brief": "Goal."}) == made

    def test_a_campaign_may_be_given_its_own_name_in_another_case(self, campaigns: Campaigns) -> None:
        made = campaigns.create("screen")

        assert campaigns.update(made["id"], {"name": "Screen"})["name"] == "Screen"

    def test_a_campaign_may_not_be_given_the_name_of_another(self, campaigns: Campaigns) -> None:
        campaigns.create("Taken")
        other = campaigns.create("Other")

        with pytest.raises(ApiError) as caught:
            campaigns.update(other["id"], {"name": "taken"})

        assert refused(caught.value, 409).startswith("There is a campaign called taken")
        assert campaigns.get(other["id"])["name"] == "Other"

    @pytest.mark.parametrize("changes", [{}, {"other": "x"}, {"name": ""}, {"name": None}, {"brief": 5}])
    def test_a_change_that_says_nothing_or_gives_what_cannot_be_used_is_refused(
        self, campaigns: Campaigns, changes: dict[str, Any]
    ) -> None:
        made = campaigns.create("Screen", "Goal.")

        with pytest.raises(ApiError) as caught:
            campaigns.update(made["id"], changes)

        assert caught.value.status == 422
        assert campaigns.get(made["id"]) == made

    @pytest.mark.parametrize("campaign_id", ["missing", "../escape", "", "UPPER", "x" * 200])
    def test_a_campaign_that_is_not_there_is_not_found_to_get_change_or_delete(
        self, campaigns: Campaigns, campaign_id: str
    ) -> None:
        campaigns.create("Screen")

        assert campaigns.find(campaign_id) is None
        for act in (
            lambda: campaigns.get(campaign_id),
            lambda: campaigns.update(campaign_id, {"name": "New"}),
            lambda: campaigns.remove(campaign_id),
        ):
            with pytest.raises(ApiError) as caught:
                act()
            assert caught.value.status == 404

    def test_a_campaign_is_forgotten_and_the_others_are_kept(self, campaigns: Campaigns) -> None:
        keep = campaigns.create("Keep")
        gone = campaigns.create("Gone")

        campaigns.remove(gone["id"])

        assert campaigns.load() == [keep]

    def test_what_a_file_edited_by_hand_holds_that_is_not_a_campaign_is_left_out(
        self, campaigns: Campaigns, workspace: Workspace
    ) -> None:
        good = {"id": "good-1", "name": "Good", "brief": "Goal.", "created_at": "2026-01-01T00:00:00+00:00"}
        entries = [
            good,
            {**good, "name": "Duplicate id"},
            {"id": "../bad", "name": "Bad id", "brief": ""},
            {"id": "no-name", "name": " ", "brief": ""},
            {"id": "no-brief", "name": "No brief"},
            {"id": "other-2", "name": "Other", "brief": "", "created_at": 5},
            "text",
        ]
        workspace.campaigns_path.write_text(json.dumps({"campaigns": entries}), encoding="utf-8")

        assert campaigns.load() == [
            {**good, "updated_at": good["created_at"]},
            {"id": "other-2", "name": "Other", "brief": "", "created_at": "", "updated_at": ""},
        ]

    @pytest.mark.parametrize("content", ["", "not json", "[]", '{"campaigns": 5}', '{"campaigns": {}}'])
    def test_a_file_that_cannot_be_read_holds_none(
        self, campaigns: Campaigns, workspace: Workspace, content: str
    ) -> None:
        workspace.campaigns_path.write_text(content, encoding="utf-8")

        assert campaigns.load() == []
        assert campaigns.create("Fresh")["name"] == "Fresh"


class TestProgramsInCampaigns:
    def test_a_program_begun_in_a_campaign_is_one_of_it_and_the_lead_is_told_the_goal(
        self, conversations: Conversations, campaigns: Campaigns, fake_client: FakeClient
    ) -> None:
        screen = campaigns.create("Nanobody screen", "Find a binder for KP.3.")

        handle = conversations.create({"team": [], "campaign": screen["id"]}, "Panning")
        say(handle)

        assert handle.config.campaign == screen["id"]
        assert load_config(handle.directory).campaign == screen["id"]  # type: ignore[union-attr]
        assert "campaign called Nanobody screen" in system_of(fake_client)
        assert "Find a binder for KP.3." in system_of(fake_client)
        assert handle.info()["config"]["campaign"] == screen["id"]

    def test_a_program_is_one_of_no_campaign_unless_it_is_begun_in_one(
        self, conversations: Conversations, campaigns: Campaigns, fake_client: FakeClient
    ) -> None:
        campaigns.create("Nanobody screen", "Find a binder for KP.3.")

        handle = conversations.create({"team": [], "campaign": None}, "Alone")
        say(handle)

        assert handle.config.campaign == ""
        assert "campaign called" not in system_of(fake_client)
        assert conversations.summaries()[0]["campaign"] is None

    def test_a_program_cannot_be_begun_in_a_campaign_that_is_not_there(self, conversations: Conversations) -> None:
        for campaign in ("missing", 7):
            with pytest.raises(ApiError) as caught:
                conversations.create({"team": [], "campaign": campaign}, "Lost")

            assert caught.value.status == 422
        assert conversations.summaries() == []
        assert list(conversations.workspace.chats_dir.iterdir()) == []

    def test_a_program_begun_with_a_campaign_that_has_a_goal_with_nothing_in_it_is_told_nothing(
        self, conversations: Conversations, campaigns: Campaigns, fake_client: FakeClient
    ) -> None:
        group = campaigns.create("Only a group")

        say(conversations.create({"team": [], "campaign": group["id"]}, "Member"))

        assert "campaign called" not in system_of(fake_client)

    def test_a_program_set_up_before_there_were_campaigns_is_one_of_none(
        self, conversations: Conversations, workspace: Workspace
    ) -> None:
        handle = conversations.create({"team": []}, "Old")
        path = handle.directory / CONFIG_FILE_NAME
        old = json.loads(path.read_text(encoding="utf-8"))
        del old["campaign"]
        path.write_text(json.dumps(old), encoding="utf-8")

        assert load_config(handle.directory).campaign == ""  # type: ignore[union-attr]

    def test_the_summaries_say_which_campaign_each_program_is_one_of(
        self, conversations: Conversations, campaigns: Campaigns
    ) -> None:
        screen = campaigns.create("Screen")
        inside = conversations.create({"team": [], "campaign": screen["id"]}, "Inside")
        outside = conversations.create({"team": []}, "Outside")

        found = {item["id"]: item["campaign"] for item in conversations.summaries()}

        assert found == {inside.id: screen["id"], outside.id: None}

    def test_a_program_is_moved_into_a_campaign_and_the_lead_is_told_from_the_next_message(
        self, conversations: Conversations, campaigns: Campaigns, fake_client: FakeClient
    ) -> None:
        screen = campaigns.create("Screen", "Find a binder.")
        handle = conversations.create({"team": []}, "Moving")
        say(handle, "Before")

        assert conversations.set_campaign(handle.id, screen["id"]) == screen["id"]
        say(handle, "After")

        assert "campaign called" not in system_of(fake_client, 0)
        assert "Find a binder." in system_of(fake_client, 1)
        assert handle.config.campaign == screen["id"]
        assert load_config(handle.directory).campaign == screen["id"]  # type: ignore[union-attr]

    def test_a_program_is_moved_from_one_campaign_to_another_and_out_of_it(
        self, conversations: Conversations, campaigns: Campaigns, fake_client: FakeClient
    ) -> None:
        first = campaigns.create("First", "The first goal.")
        second = campaigns.create("Second", "The second goal.")
        handle = conversations.create({"team": [], "campaign": first["id"]}, "Moving")
        say(handle)

        conversations.set_campaign(handle.id, second["id"])
        say(handle)
        assert conversations.set_campaign(handle.id, None) is None
        say(handle)

        assert "The first goal." in system_of(fake_client, 0)
        assert "The second goal." in system_of(fake_client, 1)
        assert "campaign called" not in system_of(fake_client, 2)
        assert handle.config.campaign == "" and conversations.summaries()[0]["campaign"] is None

    def test_a_program_that_is_not_open_is_moved_without_being_opened(
        self, conversations: Conversations, campaigns: Campaigns, fake_client: FakeClient
    ) -> None:
        screen = campaigns.create("Screen", "Find a binder.")
        handle = conversations.create({"team": []}, "Closed")
        conversations.release(handle.id)

        conversations.set_campaign(handle.id, screen["id"])

        assert handle.id not in conversations._open
        assert load_config(handle.directory).campaign == screen["id"]  # type: ignore[union-attr]
        reopened = conversations.get(handle.id)
        assert reopened.config.campaign == screen["id"]
        say(reopened)
        assert "Find a binder." in system_of(fake_client)

    def test_a_program_that_is_working_is_moved_and_goes_on_with_what_it_was_told(
        self, conversations: Conversations, campaigns: Campaigns, fake_client: FakeClient
    ) -> None:
        screen = campaigns.create("Screen", "Find a binder.")
        handle = conversations.create({"team": []}, "Busy")
        gate = hold_the_model(fake_client)

        handle.chat.start("Go")
        assert gate.reached.wait(20)
        conversations.set_campaign(handle.id, screen["id"])
        gate.release()
        wait_until(lambda: handle.chat.state == "idle")
        say(handle, "Again")

        assert "campaign called" not in system_of(fake_client, 0)
        assert "Find a binder." in system_of(fake_client, 1)

    def test_a_move_to_a_campaign_that_is_not_there_or_for_a_program_that_is_not_is_refused(
        self, conversations: Conversations, campaigns: Campaigns
    ) -> None:
        handle = conversations.create({"team": []}, "Moving")

        with pytest.raises(ApiError) as no_campaign:
            conversations.set_campaign(handle.id, "missing")
        with pytest.raises(ApiError) as no_program:
            conversations.set_campaign("missing", None)

        assert no_campaign.value.status == 422 and no_program.value.status == 404
        assert handle.config.campaign == ""

    def test_a_program_whose_setup_cannot_be_read_is_not_moved(
        self, conversations: Conversations, campaigns: Campaigns
    ) -> None:
        screen = campaigns.create("Screen")
        handle = conversations.create({"team": []}, "Broken")
        conversations.release(handle.id)
        (handle.directory / CONFIG_FILE_NAME).write_text("{}", encoding="utf-8")

        with pytest.raises(ApiError) as caught:
            conversations.set_campaign(handle.id, screen["id"])

        assert caught.value.status == 409

    def test_the_lead_is_told_a_goal_that_was_changed_from_the_next_message(
        self, conversations: Conversations, campaigns: Campaigns, fake_client: FakeClient
    ) -> None:
        screen = campaigns.create("Screen", "Find a binder.")
        member = conversations.create({"team": [], "campaign": screen["id"]}, "Member")
        outsider = conversations.create({"team": []}, "Outsider")
        say(member, "One")

        campaigns.update(screen["id"], {"name": "Binder screen", "brief": "Find a binder that is stable."})
        conversations.campaign_changed(screen["id"])
        say(member, "Two")
        say(outsider, "Three")

        assert "Find a binder." in system_of(fake_client, 0)
        assert "campaign called Binder screen" in system_of(fake_client, 1)
        assert "Find a binder that is stable." in system_of(fake_client, 1)
        assert "campaign called" not in system_of(fake_client, 2)

    def test_a_program_that_is_opened_again_is_told_the_goal_as_it_is_now(
        self, conversations: Conversations, campaigns: Campaigns, fake_client: FakeClient
    ) -> None:
        screen = campaigns.create("Screen", "Find a binder.")
        handle = conversations.create({"team": [], "campaign": screen["id"]}, "Member")
        say(handle)
        conversations.release(handle.id)

        campaigns.update(screen["id"], {"brief": "Find two binders."})
        say(conversations.get(handle.id), "Again")

        assert "Find two binders." in system_of(fake_client)

    def test_deleting_a_campaign_keeps_its_programs_and_they_are_one_of_none(
        self, conversations: Conversations, campaigns: Campaigns, fake_client: FakeClient
    ) -> None:
        screen = campaigns.create("Screen", "Find a binder.")
        other = campaigns.create("Other", "Map epitopes.")
        open_one = conversations.create({"team": [], "campaign": screen["id"]}, "Open")
        closed_one = conversations.create({"team": [], "campaign": screen["id"]}, "Closed")
        elsewhere = conversations.create({"team": [], "campaign": other["id"]}, "Elsewhere")
        conversations.release(closed_one.id)
        say(open_one)

        conversations.delete_campaign(screen["id"])
        say(open_one, "After")

        assert [item["id"] for item in campaigns.load()] == [other["id"]]
        found = {item["id"]: item["campaign"] for item in conversations.summaries()}
        assert found == {open_one.id: None, closed_one.id: None, elsewhere.id: other["id"]}
        assert load_config(open_one.directory).campaign == ""  # type: ignore[union-attr]
        assert load_config(closed_one.directory).campaign == ""  # type: ignore[union-attr]
        assert load_config(elsewhere.directory).campaign == other["id"]  # type: ignore[union-attr]
        assert open_one.config.campaign == ""
        assert "campaign called" not in system_of(fake_client)

    def test_deleting_a_campaign_that_is_not_there_is_not_found(self, conversations: Conversations) -> None:
        with pytest.raises(ApiError) as caught:
            conversations.delete_campaign("missing")

        assert caught.value.status == 404

    def test_a_program_left_pointing_at_a_campaign_that_is_gone_is_one_of_none_and_is_told_nothing(
        self, conversations: Conversations, campaigns: Campaigns, fake_client: FakeClient
    ) -> None:
        screen = campaigns.create("Screen", "Find a binder.")
        handle = conversations.create({"team": [], "campaign": screen["id"]}, "Stale")
        conversations.release(handle.id)
        campaigns.remove(screen["id"])

        assert conversations.summaries()[0]["campaign"] is None
        say(conversations.get(handle.id))
        assert "campaign called" not in system_of(fake_client)

    def test_a_campaign_is_described_with_its_programs_and_what_they_have_spent_between_them(
        self, conversations: Conversations, campaigns: Campaigns, fake_client: FakeClient
    ) -> None:
        screen = campaigns.create("Screen", "Find a binder.")
        first = conversations.create({"team": [], "campaign": screen["id"]}, "First")
        second = conversations.create({"team": [], "campaign": screen["id"]}, "Second")
        outside = conversations.create({"team": []}, "Outside")
        for handle in (first, second, outside):
            fake_client.completions.responses.append(text_response("Done."))
            say(handle)

        described = conversations.describe_campaign(screen["id"])

        assert {key: described[key] for key in ("id", "name", "brief")} == {
            "id": screen["id"],
            "name": "Screen",
            "brief": "Find a binder.",
        }
        assert sorted(item["id"] for item in described["programs"]) == sorted([first.id, second.id])
        spent = [item["spent"] for item in described["programs"]]
        assert all(amount and amount > 0 for amount in spent)
        assert described["spent"] == pytest.approx(sum(spent))

    def test_a_campaign_with_no_programs_has_spent_nothing(
        self, conversations: Conversations, campaigns: Campaigns
    ) -> None:
        empty = campaigns.create("Empty")

        assert conversations.describe_campaign(empty["id"])["programs"] == []
        assert conversations.describe_campaign(empty["id"])["spent"] == 0

    def test_the_campaign_a_config_names_is_kept_whole_with_the_rest_of_its_setup(self, workspace: Workspace) -> None:
        screen = Campaigns(workspace).create("Screen")
        config = resolve_config({"team": [], "campaign": screen["id"]}, workspace.load_settings(), workspace)

        assert ChatConfig.from_dict(config.to_dict()) == config
        assert config.to_dict()["campaign"] == screen["id"]
        assert ChatConfig.from_dict({**config.to_dict(), "campaign": 5}).campaign == ""


class TestCampaignEndpoints:
    def make(self, client: TestClient, name: str = "Nanobody screen", brief: str = "Find a binder.") -> dict[str, Any]:
        response = client.post("/api/campaigns", json={"name": name, "brief": brief})
        assert response.status_code == 201, response.text

        return response.json()

    def test_a_campaign_is_made_listed_read_changed_and_deleted(self, client: TestClient) -> None:
        assert client.get("/api/campaigns").json() == {"campaigns": []}

        made = self.make(client)
        assert made["name"] == "Nanobody screen" and made["programs"] == [] and made["spent"] == 0
        listed = client.get("/api/campaigns").json()["campaigns"]
        assert [item["id"] for item in listed] == [made["id"]]
        assert set(listed[0]) == {"id", "name", "brief", "created_at", "updated_at"}
        assert client.get(f"/api/campaigns/{made['id']}").json() == made

        changed = client.patch(f"/api/campaigns/{made['id']}", json={"brief": "Find two binders."})
        assert changed.status_code == 200 and changed.json()["brief"] == "Find two binders."
        assert changed.json()["name"] == "Nanobody screen"

        assert client.delete(f"/api/campaigns/{made['id']}").status_code == 204
        assert client.get("/api/campaigns").json() == {"campaigns": []}
        assert error_of(client.get(f"/api/campaigns/{made['id']}"))["code"] == "not_found"

    def test_a_goal_may_be_left_out_when_one_is_made(self, client: TestClient) -> None:
        made = client.post("/api/campaigns", json={"name": "Group"})

        assert made.status_code == 201 and made.json()["brief"] == ""

    @pytest.mark.parametrize(
        ("body", "status", "code"),
        [
            ({}, 422, "invalid"),
            ({"name": ""}, 422, "invalid"),
            ({"name": "  "}, 422, "invalid"),
            ({"name": "x" * 400}, 422, "invalid"),
            ({"name": "Fine", "brief": "x" * 16001}, 422, "invalid"),
            ({"name": "Fine", "extra": 1}, 422, "invalid"),
        ],
    )
    def test_a_campaign_that_cannot_be_made_is_refused(
        self, client: TestClient, body: dict[str, Any], status: int, code: str
    ) -> None:
        response = client.post("/api/campaigns", json=body)

        assert response.status_code == status and error_of(response)["code"] == code
        assert client.get("/api/campaigns").json() == {"campaigns": []}

    def test_a_name_that_is_taken_is_a_conflict_whether_it_is_made_or_given(self, client: TestClient) -> None:
        self.make(client, "Taken")
        other = self.make(client, "Other")

        made = client.post("/api/campaigns", json={"name": "TAKEN"})
        renamed = client.patch(f"/api/campaigns/{other['id']}", json={"name": "taken"})

        for response in (made, renamed):
            assert response.status_code == 409 and error_of(response)["code"] == "exists"

    def test_a_change_that_says_nothing_is_refused(self, client: TestClient) -> None:
        made = self.make(client)

        for body in ({}, {"other": 1}, {"name": None}):
            assert client.patch(f"/api/campaigns/{made['id']}", json=body).status_code == 422
        assert client.get(f"/api/campaigns/{made['id']}").json() == made

    def test_a_campaign_that_is_not_there_is_not_found(self, client: TestClient) -> None:
        for response in (
            client.get("/api/campaigns/missing"),
            client.patch("/api/campaigns/missing", json={"name": "New"}),
            client.delete("/api/campaigns/missing"),
        ):
            assert response.status_code == 404 and error_of(response)["code"] == "not_found"

    def test_a_program_is_begun_in_a_campaign_moved_and_taken_out_of_it(
        self, client: TestClient, fake_client: FakeClient
    ) -> None:
        screen = self.make(client)
        other = self.make(client, "Other", "Something else.")

        begun = client.post("/api/chats", json={"team": [], "campaign": screen["id"], "title": "Panning"})
        assert begun.status_code == 201 and begun.json()["config"]["campaign"] == screen["id"]
        chat_id = begun.json()["id"]
        assert [item["campaign"] for item in client.get("/api/chats").json()["chats"]] == [screen["id"]]
        assert [item["id"] for item in client.get(f"/api/campaigns/{screen['id']}").json()["programs"]] == [chat_id]

        moved = client.put(f"/api/chats/{chat_id}/campaign", json={"campaign": other["id"]})
        assert moved.status_code == 200 and moved.json() == {"id": chat_id, "campaign": other["id"]}
        assert client.get(f"/api/campaigns/{screen['id']}").json()["programs"] == []
        assert client.get(f"/api/chats/{chat_id}").json()["config"]["campaign"] == other["id"]

        out = client.put(f"/api/chats/{chat_id}/campaign", json={"campaign": None})
        assert out.status_code == 200 and out.json() == {"id": chat_id, "campaign": None}
        assert client.get("/api/chats").json()["chats"][0]["campaign"] is None

    def test_a_program_cannot_be_begun_or_moved_into_a_campaign_that_is_not_there(self, client: TestClient) -> None:
        begun = client.post("/api/chats", json={"team": [], "campaign": "missing"})
        assert begun.status_code == 422 and error_of(begun)["code"] == "invalid"
        chat_id = client.post("/api/chats", json={"team": [], "title": "Plain"}).json()["id"]

        moved = client.put(f"/api/chats/{chat_id}/campaign", json={"campaign": "missing"})
        assert moved.status_code == 422 and error_of(moved)["code"] == "invalid"
        assert client.put("/api/chats/missing/campaign", json={"campaign": None}).status_code == 404
        assert client.put(f"/api/chats/{chat_id}/campaign", json={}).status_code == 422
        assert client.get(f"/api/chats/{chat_id}").json()["config"]["campaign"] == ""

    def test_deleting_a_campaign_keeps_its_programs(self, client: TestClient) -> None:
        screen = self.make(client)
        chat_id = client.post("/api/chats", json={"team": [], "campaign": screen["id"], "title": "Keep"}).json()["id"]

        assert client.delete(f"/api/campaigns/{screen['id']}").status_code == 204

        (listed,) = client.get("/api/chats").json()["chats"]
        assert listed["id"] == chat_id and listed["campaign"] is None
        assert client.get(f"/api/chats/{chat_id}").json()["config"]["campaign"] == ""

    def test_the_lead_is_told_the_goal_and_the_new_one_after_it_is_changed(
        self, client: TestClient, fake_client: FakeClient
    ) -> None:
        screen = self.make(client)
        chat_id = client.post("/api/chats", json={"team": [], "campaign": screen["id"]}).json()["id"]

        def send(text: str) -> None:
            assert client.post(f"/api/chats/{chat_id}/messages", json={"text": text}).status_code == 202
            wait_until(lambda: client.get(f"/api/chats/{chat_id}").json()["state"] == "idle")

        send("One")
        client.patch(f"/api/campaigns/{screen['id']}", json={"brief": "Find two binders."})
        send("Two")

        assert "Find a binder." in system_of(fake_client, 0)
        assert "Find two binders." in system_of(fake_client, 1)

    def test_campaigns_need_the_token_like_everything_else(self, workspace: Workspace) -> None:
        with TestClient(create_app(workspace.root, token=TOKEN, check_keys=False), base_url=LOCAL) as bare:
            assert bare.get("/api/campaigns").status_code == 401
            assert bare.post("/api/campaigns", json={"name": "No"}).status_code == 401
