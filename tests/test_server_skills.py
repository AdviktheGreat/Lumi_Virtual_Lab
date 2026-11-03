"""Tests of the skills the server gives a conversation: where they are found, how a conversation is set up with them,
and what it goes on with once it is opened again."""

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import TEST_MODEL, FakeClient, text_response
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_server_app import BEARER, LOCAL, TOKEN, handle_of, new_chat, wait_idle
from test_skills import write_skill

from virtual_lab.server.app import create_app
from virtual_lab.server.config import CONFIG_FILE_NAME, ChatConfig, load_config, resolve_config
from virtual_lab.server.conversations import Conversations
from virtual_lab.server.skills import (
    USER_SKILLS_DIR_VARIABLE,
    check_skill_names,
    load_skills,
    skill_roots,
    user_skills_dir,
)
from virtual_lab.server.workspace import Settings, Workspace


@pytest.fixture(autouse=True)
def model_client(fake_client: FakeClient) -> FakeClient:
    return fake_client


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    store = Workspace(tmp_path / "workspace")
    store.save_settings(Settings(model=TEST_MODEL, max_cost=None))

    return store


@pytest.fixture
def user_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "user-skills"
    monkeypatch.setenv(USER_SKILLS_DIR_VARIABLE, str(directory))

    return directory


@pytest.fixture
def conversations(workspace: Workspace) -> Iterator[Conversations]:
    kept = Conversations(workspace, check_keys=False)
    yield kept
    kept.close()


@pytest.fixture
def app(workspace: Workspace) -> FastAPI:
    return create_app(workspace.root, token=TOKEN, check_keys=False)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


class TestWhereSkillsAre:
    def test_the_workspaces_skills_are_in_a_folder_of_its_own(self, workspace: Workspace) -> None:
        assert workspace.skills_dir == workspace.root / "skills"

    def test_skills_are_found_in_the_workspace_and_in_the_persons_own_folder(
        self, workspace: Workspace, user_skills: Path
    ) -> None:
        write_skill(workspace.skills_dir, name="in-workspace")
        write_skill(user_skills, name="in-user-folder")

        library = load_skills(workspace)

        assert [(skill.name, skill.source) for skill in library.skills] == [
            ("in-user-folder", "user"),
            ("in-workspace", "workspace"),
        ]

    def test_of_two_skills_of_one_name_the_workspaces_is_used(self, workspace: Workspace, user_skills: Path) -> None:
        write_skill(workspace.skills_dir, name="shared", description="The workspace's.")
        write_skill(user_skills, name="shared", description="The person's.")

        (skill,) = load_skills(workspace).skills

        assert (skill.description, skill.source) == ("The workspace's.", "workspace")

    def test_the_persons_folder_is_agents_skills_in_their_home_unless_one_is_named(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv(USER_SKILLS_DIR_VARIABLE)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

        assert user_skills_dir() == tmp_path / "home" / ".agents" / "skills"
        monkeypatch.setenv(USER_SKILLS_DIR_VARIABLE, "~/elsewhere")
        assert user_skills_dir() == Path("~/elsewhere").expanduser()

    def test_the_workspace_is_searched_before_the_persons_folder_and_both_before_the_labs_own(
        self, workspace: Workspace
    ) -> None:
        assert [source for source, _ in skill_roots(workspace)] == ["workspace", "user", "builtin"]

    def test_names_are_checked_against_the_skills_there_are(self, workspace: Workspace) -> None:
        write_skill(workspace.skills_dir, name="alpha")
        write_skill(workspace.skills_dir, name="beta")
        library = load_skills(workspace)

        assert check_skill_names(["beta", "alpha", "beta"], library) == ["beta", "alpha"]
        assert check_skill_names([], library) == []
        with pytest.raises(ValueError, match="no skill called 'gamma'"):
            check_skill_names(["alpha", "gamma"], library)
        with pytest.raises(ValueError, match="a list of their names"):
            check_skill_names("alpha", library)
        with pytest.raises(ValueError, match="no skill called 7"):
            check_skill_names([7], library)


class TestSettingUpAConversation:
    def test_it_is_given_every_skill_there_is_unless_it_is_told_which(self, workspace: Workspace) -> None:
        write_skill(workspace.skills_dir, name="alpha")
        write_skill(workspace.skills_dir, name="beta")

        config = resolve_config({}, workspace.load_settings(), workspace)
        chosen = resolve_config({"skills": ["beta"]}, workspace.load_settings(), workspace)
        none = resolve_config({"skills": []}, workspace.load_settings(), workspace)

        assert config.skills == ("alpha", "beta")
        assert chosen.skills == ("beta",)
        assert none.skills == ()

    def test_a_skill_that_is_not_there_cannot_be_chosen(self, workspace: Workspace) -> None:
        with pytest.raises(ValueError, match="no skill called 'gone'"):
            resolve_config({"skills": ["gone"]}, workspace.load_settings(), workspace)

    def test_the_skills_are_kept_with_the_rest_of_the_setup(self, workspace: Workspace, tmp_path: Path) -> None:
        write_skill(workspace.skills_dir, name="alpha")
        config = resolve_config({}, workspace.load_settings(), workspace)
        directory = tmp_path / "chat"
        directory.mkdir()

        (directory / CONFIG_FILE_NAME).write_text(json.dumps(config.to_dict()))

        assert config.to_dict()["skills"] == ["alpha"]
        loaded = load_config(directory)
        assert loaded is not None and loaded.skills == ("alpha",)

    def test_a_conversation_begun_before_there_were_skills_has_none(self, workspace: Workspace) -> None:
        write_skill(workspace.skills_dir, name="alpha")
        saved = resolve_config({}, workspace.load_settings(), workspace).to_dict()
        del saved["skills"]

        assert ChatConfig.from_dict(saved).skills == ()


class TestGivingThemToAConversation:
    def test_a_new_conversation_has_the_skills_there_are(
        self, conversations: Conversations, workspace: Workspace
    ) -> None:
        write_skill(workspace.skills_dir, name="alpha")
        write_skill(workspace.skills_dir, name="beta")

        handle = conversations.create({"team": []})

        assert [skill.name for skill in handle.chat.skills] == ["alpha", "beta"]
        assert handle.info()["skills"] == ["alpha", "beta"]
        assert handle.info()["config"]["skills"] == ["alpha", "beta"]

    def test_a_conversation_can_be_given_some_or_none(self, conversations: Conversations, workspace: Workspace) -> None:
        write_skill(workspace.skills_dir, name="alpha")
        write_skill(workspace.skills_dir, name="beta")

        some = conversations.create({"team": [], "skills": ["beta"]})
        none = conversations.create({"team": [], "skills": []})

        assert [skill.name for skill in some.chat.skills] == ["beta"]
        assert none.chat.skills == ()

    def test_a_skill_that_cannot_be_given_is_a_refusal_before_anything_is_made(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        response = client.post("/api/chats", json={"team": [], "skills": ["gone"]})

        assert response.status_code == 422
        assert "no skill called 'gone'" in response.text
        assert not any(workspace.chats_dir.iterdir())

    def test_a_conversation_made_through_the_api_is_given_the_skills_chosen(
        self, client: TestClient, app: FastAPI, workspace: Workspace
    ) -> None:
        write_skill(workspace.skills_dir, name="alpha")
        write_skill(workspace.skills_dir, name="beta")

        chat = new_chat(client, skills=["alpha"])

        assert chat["skills"] == ["alpha"]
        assert [skill.name for skill in handle_of(app, chat["id"]).chat.skills] == ["alpha"]

    def test_the_lead_is_told_of_them_in_its_first_request(
        self, conversations: Conversations, workspace: Workspace, fake_client: FakeClient
    ) -> None:
        write_skill(workspace.skills_dir, name="alpha", description="Does the alpha thing.")
        fake_client.completions.responses = [text_response("Hello.")]
        handle = conversations.create({"team": []})

        handle.chat.send("Hi")

        system = fake_client.completions.calls[0]["messages"][0]["content"]
        assert "- alpha: Does the alpha thing." in system

    def test_a_conversation_opened_again_goes_on_with_those_of_its_skills_that_are_still_there(
        self, workspace: Workspace
    ) -> None:
        write_skill(workspace.skills_dir, name="alpha")
        write_skill(workspace.skills_dir, name="beta")
        first = Conversations(workspace, check_keys=False)
        chat_id = first.create({"team": []}).id
        first.close()

        shutil.rmtree(workspace.skills_dir / "alpha")
        write_skill(workspace.skills_dir, name="gamma")
        second = Conversations(workspace, check_keys=False)
        try:
            reopened = second.get(chat_id)

            # Not alpha, which is gone, and not gamma, which it was not given
            assert [skill.name for skill in reopened.chat.skills] == ["beta"]
        finally:
            second.close()

    def test_the_first_request_over_the_api_offers_the_tools_to_read_them(
        self, client: TestClient, app: FastAPI, workspace: Workspace, fake_client: FakeClient
    ) -> None:
        write_skill(workspace.skills_dir, name="alpha")
        fake_client.completions.responses = [text_response("Hello.")]
        chat = new_chat(client)

        response = client.post(f"/api/chats/{chat['id']}/messages", json={"text": "Hi"})
        assert response.status_code == 202, response.text
        wait_idle(client, chat["id"])

        names = {tool["function"]["name"] for tool in fake_client.completions.calls[0]["tools"]}
        assert {"activate_skill", "read_skill_file"} <= names
