"""Tests of a program for building a skill: that it needs code, what it is given, and how a skill built in it is saved
among the workspace's skills."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MODEL, FakeClient, text_response, tool_call_response
from fastapi.testclient import TestClient
from test_server_app import BEARER, LOCAL, TOKEN, error_of
from test_skills import write_skill

from virtual_lab.prompts import build_skill_prompt
from virtual_lab.server import skills as server_skills
from virtual_lab.server.app import create_app
from virtual_lab.server.config import CONFIG_FILE_NAME, ChatConfig, check_program, resolve_config
from virtual_lab.server.conversations import WORK_DIR_NAME, ChatHandle, Conversations
from virtual_lab.server.errors import ApiError
from virtual_lab.server.skills import USER_SKILLS_DIR_VARIABLE, Skills, load_skills
from virtual_lab.server.workspace import Settings, Workspace

CODE = {"where": "local"}


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
def client(workspace: Workspace) -> Iterator[TestClient]:
    with TestClient(
        create_app(workspace.root, token=TOKEN, check_keys=False), base_url=LOCAL, headers=BEARER
    ) as opened:
        yield opened


def say(handle: ChatHandle, message: str = "Hello") -> None:
    handle.chat.start(message).join(20)
    assert handle.chat.state == "idle"


def built(handle: ChatHandle, name: str = "dose-response", **options: Any) -> Path:
    """A skill that the lead has built in the program's session."""
    return write_skill(handle.directory / WORK_DIR_NAME / "new_skills", name=name, **options)


class TestSavingWhatWasBuilt:
    def test_a_skill_is_copied_whole_among_the_workspaces_skills_and_is_then_found(self, workspace: Workspace) -> None:
        folder = write_skill(
            workspace.root / "built", files={"scripts/fit.py": "print('fitted')", "references/guide.md": "Guide."}
        )

        saved = Skills(workspace).save_built(folder)

        assert saved["name"] == "dose-response"
        assert saved["files"] == ["SKILL.md", "references/guide.md", "scripts/fit.py"]
        assert saved["directory"] == str(workspace.skills_dir / "dose-response")
        assert (workspace.skills_dir / "dose-response" / "scripts" / "fit.py").read_text() == "print('fitted')"
        found = load_skills(workspace).named("dose-response")
        assert found is not None and found.source == "workspace"
        assert folder.is_dir()

    def test_without_saving_it_says_what_would_be_and_copies_nothing(self, workspace: Workspace) -> None:
        folder = write_skill(workspace.root / "built")

        said = Skills(workspace).save_built(folder, commit=False)

        assert said["name"] == "dose-response" and said["files"] == ["SKILL.md"]
        assert "directory" not in said
        assert not workspace.skills_dir.exists()

    def test_a_name_that_a_skill_has_already_is_refused_wherever_the_skill_is(
        self, workspace: Workspace, user_skills: Path
    ) -> None:
        write_skill(workspace.skills_dir, name="mine")
        write_skill(user_skills, name="theirs")
        saving = Skills(workspace)

        for name in ("mine", "theirs"):
            with pytest.raises(ValueError, match=f"There is a skill called {name} already"):
                saving.save_built(write_skill(workspace.root / "built", name=name))

        assert sorted(path.name for path in workspace.skills_dir.iterdir()) == ["mine"]

    def test_a_name_that_differs_only_in_case_from_one_there_is_is_refused(self, workspace: Workspace) -> None:
        write_skill(workspace.skills_dir, name="Mine")

        with pytest.raises(ValueError, match="There is a skill called mine already"):
            Skills(workspace).save_built(write_skill(workspace.root / "built", name="mine"))

    def test_a_skill_saved_once_cannot_be_saved_over_by_a_second_of_its_name(self, workspace: Workspace) -> None:
        saving = Skills(workspace)
        saving.save_built(write_skill(workspace.root / "one", description="First. Use it for one thing."))

        with pytest.raises(ValueError, match="already"):
            saving.save_built(write_skill(workspace.root / "two", description="Second. Use it for another."))

        assert "First." in (workspace.skills_dir / "dose-response" / "SKILL.md").read_text()

    def test_a_folder_without_a_skill_file_is_refused(self, workspace: Workspace) -> None:
        (workspace.root / "empty").mkdir(parents=True)

        with pytest.raises(ValueError, match="There is no SKILL.md in empty"):
            Skills(workspace).save_built(workspace.root / "empty")

    def test_a_skill_file_that_cannot_be_read_as_one_is_refused_with_why(self, workspace: Workspace) -> None:
        folder = workspace.root / "broken"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("Just some words, with no block of fields.")

        with pytest.raises(ValueError, match="This cannot be used as a skill"):
            Skills(workspace).save_built(folder)

    def test_a_folder_that_is_not_called_what_the_skill_is_is_refused(self, workspace: Workspace) -> None:
        folder = write_skill(workspace.root / "built", name="dose-response", folder="curves")

        with pytest.raises(ValueError, match="The folder is called curves and the skill dose-response"):
            Skills(workspace).save_built(folder)

    def test_a_skill_that_departs_from_the_standard_is_refused_and_not_just_noted(self, workspace: Workspace) -> None:
        folder = write_skill(workspace.root / "built", name="Dose-Response")

        with pytest.raises(ValueError, match="This departs from the format of a skill"):
            Skills(workspace).save_built(folder)

    def test_a_skill_of_more_files_or_bytes_than_may_be_copied_is_refused(
        self, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        folder = write_skill(workspace.root / "built", files={"a.md": "A", "b.md": "B"})
        monkeypatch.setattr(server_skills, "MAX_COPIED_FILES", 2)

        with pytest.raises(ValueError, match="at most 2 files"):
            Skills(workspace).save_built(folder)

        monkeypatch.setattr(server_skills, "MAX_COPIED_FILES", 10)
        monkeypatch.setattr(server_skills, "MAX_COPIED_BYTES", 3_000_000)
        write_skill(workspace.root / "built", files={"big.bin": b"x" * 3_100_000})
        with pytest.raises(ValueError, match="3 MB"):
            Skills(workspace).save_built(folder)

    def test_no_more_skills_are_saved_than_are_used(
        self, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_skill(workspace.skills_dir, name="mine")
        monkeypatch.setattr(server_skills, "MAX_SKILLS", 1)

        with pytest.raises(ValueError, match="Only 1 skills are used"):
            Skills(workspace).save_built(write_skill(workspace.root / "built"))


class TestBeginning:
    def test_a_program_for_building_a_skill_is_one_of_the_kinds_and_has_no_instructions(self) -> None:
        assert check_program("build_skill", None) == ("build_skill", "")
        assert check_program("build_skill", "  ") == ("build_skill", "")
        with pytest.raises(ValueError, match="Only a custom program has instructions"):
            check_program("build_skill", "Be brief.")
        with pytest.raises(ValueError, match="quick_task, custom, build_skill, not 'campaign'"):
            check_program("campaign", None)

    def test_it_needs_code_to_run_and_says_where_to_turn_it_on(self, workspace: Workspace) -> None:
        for code in ({}, {"where": "none"}):
            with pytest.raises(ValueError, match="Turn it on in the settings, under Code, and begin again"):
                resolve_config({"team": [], "kind": "build_skill", "code": code}, workspace.load_settings(), workspace)

        config = resolve_config({"team": [], "kind": "build_skill", "code": CODE}, workspace.load_settings(), workspace)

        assert (config.kind, config.instructions, config.code.where) == ("build_skill", "", "local")

    def test_it_is_given_the_skill_that_says_how_to_write_one_if_the_person_has_it(
        self, workspace: Workspace, user_skills: Path
    ) -> None:
        write_skill(user_skills, name="skill-creator", description="Use it to write a skill.")
        write_skill(user_skills, name="other")
        workspace.save_disabled_skills(["skill-creator"])
        request = {"team": [], "kind": "build_skill", "code": CODE}

        config = resolve_config(request, workspace.load_settings(), workspace)
        named = resolve_config({**request, "skills": ["other"]}, workspace.load_settings(), workspace)
        quick = resolve_config({"team": [], "code": CODE}, workspace.load_settings(), workspace)

        assert config.skills == ("other", "skill-creator")
        assert named.skills == ("other",)
        assert quick.skills == ("other",)

    def test_it_is_given_it_once_and_not_at_all_where_the_person_has_none(
        self, workspace: Workspace, user_skills: Path
    ) -> None:
        request = {"team": [], "kind": "build_skill", "code": CODE}
        assert resolve_config(request, workspace.load_settings(), workspace).skills == ()

        write_skill(user_skills, name="skill-creator", description="Use it to write a skill.")

        assert resolve_config(request, workspace.load_settings(), workspace).skills == ("skill-creator",)

    def test_the_kind_is_kept_and_a_program_with_a_kind_that_is_not_known_is_a_quick_task(
        self, workspace: Workspace
    ) -> None:
        config = resolve_config({"team": [], "kind": "build_skill", "code": CODE}, workspace.load_settings(), workspace)

        assert ChatConfig.from_dict(config.to_dict()).kind == "build_skill"
        assert ChatConfig.from_dict({**config.to_dict(), "kind": "campaign"}).kind == "quick_task"

    def test_it_is_made_and_listed_as_one_without_a_name_and_not_made_where_code_is_off(
        self, conversations: Conversations, workspace: Workspace
    ) -> None:
        with pytest.raises(ApiError, match="Building a skill needs code to run") as refused:
            conversations.create({"team": [], "kind": "build_skill"})
        assert (refused.value.status, refused.value.code) == (422, "invalid")
        assert not workspace.chats_dir.exists() or list(workspace.chats_dir.iterdir()) == []

        handle = conversations.create({"team": [], "kind": "build_skill", "code": CODE})

        assert handle.config.kind == "build_skill"
        assert json.loads((handle.directory / CONFIG_FILE_NAME).read_text())["kind"] == "build_skill"
        assert {item["id"]: item["kind"] for item in conversations.summaries()} == {handle.id: "build_skill"}

    def test_the_lead_is_told_how_and_has_the_tool_to_save_what_it_built(
        self, conversations: Conversations, fake_client: FakeClient
    ) -> None:
        fake_client.completions.responses = [text_response("What is it for?")]
        handle = conversations.create({"team": [], "kind": "build_skill", "code": CODE})

        say(handle, "I want a skill")

        first = fake_client.completions.calls[0]
        assert "save_skill" in [tool["function"]["name"] for tool in first["tools"]]
        folder = f"{handle.chat.session.where_code_runs().rstrip('/')}/new_skills"  # type: ignore[union-attr]
        assert build_skill_prompt(folder) in first["messages"][0]["content"]
        assert handle.chat.skill_saver is not None

    def test_a_program_of_another_kind_has_neither_the_tool_nor_the_words(
        self, conversations: Conversations, fake_client: FakeClient
    ) -> None:
        fake_client.completions.responses = [text_response("Hi.")]
        handle = conversations.create({"team": [], "code": CODE})

        say(handle)

        first = fake_client.completions.calls[0]
        assert "save_skill" not in [tool["function"]["name"] for tool in first["tools"]]
        assert "build a skill with you" not in first["messages"][0]["content"]
        assert handle.chat.skill_saver is None

    def test_it_is_opened_again_as_one_that_can_save(
        self, workspace: Workspace, conversations: Conversations, fake_client: FakeClient
    ) -> None:
        handle = conversations.create({"team": [], "kind": "build_skill", "code": CODE})
        conversations.close()
        fake_client.completions.responses = [text_response("Hi.")]

        with_a_new_server = Conversations(workspace, check_keys=False)
        try:
            reopened = with_a_new_server.get(handle.id)
            say(reopened)

            assert "save_skill" in [tool["function"]["name"] for tool in fake_client.completions.calls[0]["tools"]]
        finally:
            with_a_new_server.close()


class TestSavingInAProgram:
    def test_a_skill_is_saved_only_after_the_researcher_has_been_asked_and_has_answered(
        self, conversations: Conversations, workspace: Workspace, fake_client: FakeClient
    ) -> None:
        handle = conversations.create({"team": [], "kind": "build_skill", "code": CODE})
        built(handle)
        fake_client.completions.responses = [
            tool_call_response("save_skill", {"path": "new_skills/dose-response"}),
            text_response("Here it is. Shall I save it?"),
            tool_call_response("save_skill", {"path": "new_skills/dose-response"}),
            text_response("Saved."),
        ]

        say(handle, "Make a dose-response skill")
        assert not workspace.skills_dir.exists()
        say(handle, "Yes, save it")

        saved = workspace.skills_dir / "dose-response" / "SKILL.md"
        assert saved.is_file()
        outputs = [message for message in handle.chat.messages if message.get("role") == "tool"]
        assert [json.loads(message["content"])["saved"] for message in outputs] == [False, True]
        assert load_skills(workspace).named("dose-response") is not None

    def test_a_lead_that_calls_again_in_the_same_message_saves_nothing(
        self, conversations: Conversations, workspace: Workspace, fake_client: FakeClient
    ) -> None:
        handle = conversations.create({"team": [], "kind": "build_skill", "code": CODE})
        built(handle)
        fake_client.completions.responses = [
            tool_call_response("save_skill", {"path": "new_skills/dose-response"}),
            tool_call_response("save_skill", {"path": "new_skills/dose-response"}),
            text_response("I will wait for your answer."),
        ]

        say(handle, "Make a dose-response skill, and save it, do not ask")

        assert not workspace.skills_dir.exists()
        outputs = [json.loads(message["content"]) for message in handle.chat.messages if message.get("role") == "tool"]
        assert [output["saved"] for output in outputs] == [False, False]
        assert "has not answered" in outputs[1]["message"]

    def test_a_name_that_is_taken_is_refused_to_the_lead_and_nothing_is_changed(
        self, conversations: Conversations, workspace: Workspace, fake_client: FakeClient
    ) -> None:
        write_skill(workspace.skills_dir, name="dose-response", description="Mine. Use it for my curves.")
        handle = conversations.create({"team": [], "kind": "build_skill", "code": CODE})
        built(handle)
        fake_client.completions.responses = [
            tool_call_response("save_skill", {"path": "new_skills/dose-response"}),
            text_response("That name is taken."),
        ]

        say(handle, "Make a dose-response skill")

        (output,) = [message for message in handle.chat.messages if message.get("role") == "tool"]
        assert "There is a skill called dose-response already" in output["content"]
        assert "Mine." in (workspace.skills_dir / "dose-response" / "SKILL.md").read_text()


class TestOverTheApi:
    def test_a_program_for_building_a_skill_is_made_and_listed_with_its_kind(self, client: TestClient) -> None:
        made = client.post("/api/chats", json={"team": [], "kind": "build_skill", "code": CODE})

        assert made.status_code == 201
        assert made.json()["config"]["kind"] == "build_skill"
        assert made.json()["config"]["instructions"] == ""
        listed = client.get("/api/chats").json()["chats"]
        assert [(item["id"], item["kind"]) for item in listed] == [(made.json()["id"], "build_skill")]

    def test_it_is_refused_where_code_is_off_and_nothing_is_made(self, client: TestClient) -> None:
        response = client.post("/api/chats", json={"team": [], "kind": "build_skill", "code": {"where": "none"}})

        assert response.status_code == 422
        assert "Building a skill needs code to run" in error_of(response)["message"]
        assert client.get("/api/chats").json() == {"chats": []}

    def test_it_has_no_instructions_of_its_own(self, client: TestClient) -> None:
        response = client.post(
            "/api/chats", json={"team": [], "kind": "build_skill", "code": CODE, "instructions": "Be brief."}
        )

        assert response.status_code == 422
        assert "Only a custom program has instructions" in error_of(response)["message"]
