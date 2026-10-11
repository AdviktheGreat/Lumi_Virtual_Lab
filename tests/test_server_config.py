"""Tests of what a conversation is set up with, and that it is carried on as it was set up."""

import json
from pathlib import Path
from typing import Any

import pytest

from virtual_lab.prompts import PRINCIPAL_INVESTIGATOR, SCIENTIFIC_CRITIC
from virtual_lab.scientists import SCIENTISTS
from virtual_lab.server.config import (
    CONFIG_FILE_NAME,
    DEFAULT_TEAM,
    PUBLIC_SETTINGS,
    ChatConfig,
    check_data_lake,
    check_forward_keys,
    data_lake_directory,
    describe_models,
    describe_scientist,
    library,
    load_config,
    public_settings,
    resolve_config,
    save_config,
    update_settings,
)
from virtual_lab.ui.runs import CodeSetup
from virtual_lab.ui.workspace import Settings, Workspace

from conftest import TEST_MODEL

NANOBODY_EXPERT = {
    "title": "Nanobody Engineer",
    "expertise": "single-domain antibodies",
    "goal": "design binders",
    "role": "propose sequences",
}


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "workspace")


def settings(**changes: Any) -> Settings:
    return Settings(**{"model": TEST_MODEL, **changes})


def titles(members: Any) -> list[str]:
    return [member["title"] for member in members]


class TestResolving:
    def test_what_the_request_leaves_out_is_what_the_settings_and_the_library_say(self, workspace: Workspace) -> None:
        chosen = settings(
            max_cost=1.5, stream=False, code="local", sandbox="bio", network=False, python="/usr/bin/python3"
        )

        config = resolve_config({}, chosen, workspace)

        assert config.model == TEST_MODEL
        assert config.lead["title"] == PRINCIPAL_INVESTIGATOR.title
        assert titles(config.team) == list(DEFAULT_TEAM)
        assert config.code == CodeSetup(
            where="local", sandbox="bio", network=False, python="/usr/bin/python3", resources="retrieve"
        )
        assert config.max_cost == 1.5
        assert config.stream is False
        assert config.commercial_mode is False

    def test_what_the_request_gives_is_what_it_is_set_up_with(self, workspace: Workspace) -> None:
        config = resolve_config(
            {
                "model": "gpt-5.2",
                "team": ["Scientific Critic"],
                "code": {"where": "docker", "resources": "all"},
                "max_cost": 0.25,
                "stream": False,
                "commercial_mode": True,
            },
            settings(code="none", sandbox="full", stream=True),
            workspace,
        )

        assert config.model == "gpt-5.2"
        assert titles(config.team) == ["Scientific Critic"]
        # What the request names of the code is changed, and the rest is the settings'
        assert config.code == CodeSetup(
            where="docker",
            sandbox="full",
            network=True,
            python="",
            resources="all",
            data_lake=str(workspace.data_lake_dir),
        )
        assert config.max_cost == 0.25
        assert config.stream is False
        assert config.commercial_mode is True

    def test_no_limit_on_what_is_spent_is_asked_for_by_null_and_not_by_leaving_it_out(
        self, workspace: Workspace
    ) -> None:
        assert resolve_config({"max_cost": None}, settings(max_cost=2.0), workspace).max_cost is None
        assert resolve_config({}, settings(max_cost=2.0), workspace).max_cost == 2.0
        assert resolve_config({}, settings(max_cost=None), workspace).max_cost is None

    def test_a_lead_with_no_team_works_alone(self, workspace: Workspace) -> None:
        config = resolve_config({"team": []}, settings(), workspace)

        assert config.team == ()
        assert resolve_config({"team": None}, settings(), workspace).team != ()

    def test_the_lead_and_the_team_are_chosen_by_title_whatever_its_case_or_spacing(self, workspace: Workspace) -> None:
        config = resolve_config(
            {"lead": "  principal INVESTIGATOR ", "team": ["scientific critic", "Immunologist"]},
            settings(),
            workspace,
        )

        assert config.lead["title"] == PRINCIPAL_INVESTIGATOR.title
        assert titles(config.team) == [SCIENTIFIC_CRITIC.title, "Immunologist"]
        assert config.lead["role"] == PRINCIPAL_INVESTIGATOR.role

    def test_a_scientist_may_be_described_instead_of_chosen(self, workspace: Workspace) -> None:
        described = {key: f"  {value}\n  indeed " for key, value in NANOBODY_EXPERT.items()}

        config = resolve_config({"lead": described, "team": [described | {"title": "Second"}]}, settings(), workspace)

        assert config.lead == {key: f"{value} indeed" for key, value in NANOBODY_EXPERT.items()}
        assert config.team[0] == {**config.lead, "title": "Second"}

    def test_a_scientist_the_person_described_stands_in_place_of_the_librarys_with_the_title(
        self, workspace: Workspace
    ) -> None:
        mine = {**NANOBODY_EXPERT, "title": "Immunologist"}
        workspace.save_scientist(mine)
        workspace.save_scientist(NANOBODY_EXPERT)

        config = resolve_config({"team": ["immunologist", "Nanobody Engineer"]}, settings(), workspace)

        assert config.team == (mine, NANOBODY_EXPERT)

    @pytest.mark.parametrize(
        ("request_", "message"),
        [
            ({"team": ["Alchemist"]}, 'There is no scientist titled "Alchemist"'),
            ({"lead": "Nobody"}, 'There is no scientist titled "Nobody"'),
            ({"lead": {"title": "Lead", "expertise": "x", "goal": "y"}}, "A scientist needs role"),
            ({"lead": {"title": "Lead", "expertise": "x", "goal": " ", "role": ""}}, "A scientist needs goal, role"),
            ({"team": ["Immunologist", "immunologist"]}, "must have different titles"),
            ({"team": ["Principal Investigator"]}, "must have different titles"),
            ({"model": "not-a-model-anyone-serves"}, "Unable to determine the source"),
            ({"code": {"where": "cloud"}}, "Code runs in one of"),
            ({"code": {"sandbox": "huge"}}, "The sandbox is one of"),
            ({"code": {"resources": "some"}}, "The resources are one of"),
            ({"code": {"gpu": True}}, "unexpected keyword"),
            ({"max_cost": -1}, "max_cost must be a finite amount"),
            ({"max_cost": float("nan")}, "max_cost must be a finite amount"),
            ({"max_cost": float("inf")}, "max_cost must be a finite amount"),
            ({"max_cost": "plenty"}, "could not convert string to float"),
        ],
    )
    def test_something_that_cannot_be_used_is_refused_and_says_what(
        self, workspace: Workspace, request_: dict[str, Any], message: str
    ) -> None:
        with pytest.raises((ValueError, TypeError), match=message):
            resolve_config(request_, settings(), workspace)

    def test_the_default_team_is_the_critic_and_then_everyone_but_the_lead(self) -> None:
        assert DEFAULT_TEAM[0] == SCIENTIFIC_CRITIC.title
        assert PRINCIPAL_INVESTIGATOR.title not in DEFAULT_TEAM
        assert len(set(DEFAULT_TEAM)) == len(DEFAULT_TEAM)
        assert set(DEFAULT_TEAM) | {PRINCIPAL_INVESTIGATOR.title} == {agent.title for agent in SCIENTISTS} | {
            SCIENTIFIC_CRITIC.title,
            PRINCIPAL_INVESTIGATOR.title,
        }

    def test_the_agents_are_given_the_model(self, workspace: Workspace) -> None:
        config = resolve_config({"model": "gpt-5.2", "team": ["Immunologist"]}, settings(), workspace)

        assert config.lead_agent().model == "gpt-5.2"
        assert config.lead_agent().title == PRINCIPAL_INVESTIGATOR.title
        assert [agent.model for agent in config.team_agents()] == ["gpt-5.2"]


class TestDescribing:
    def test_the_library_is_the_built_in_scientists_and_then_those_the_person_described(
        self, workspace: Workspace
    ) -> None:
        workspace.save_scientist(NANOBODY_EXPERT)
        workspace.save_scientist({**NANOBODY_EXPERT, "title": "Immunologist", "role": "my own role"})

        found = library(workspace)

        by_title = {item["title"]: item for item in found}
        assert len(found) == len(by_title)
        assert by_title["Nanobody Engineer"]["builtin"] is False
        assert by_title["Immunologist"]["builtin"] is False
        assert by_title["Immunologist"]["role"] == "my own role"
        assert by_title[PRINCIPAL_INVESTIGATOR.title]["builtin"] is True
        assert {key for key in by_title[PRINCIPAL_INVESTIGATOR.title]} == {
            "title",
            "expertise",
            "goal",
            "role",
            "builtin",
        }

    def test_a_scientist_is_described_by_the_parts_every_one_has(self) -> None:
        assert describe_scientist(NANOBODY_EXPERT | {"extra": "ignored", "builtin": False}, []) == NANOBODY_EXPERT

    def test_a_title_is_looked_up_in_the_scientists_given(self) -> None:
        assert describe_scientist("NANOBODY engineer", [{**NANOBODY_EXPERT, "builtin": True}]) == NANOBODY_EXPERT


class TestKeeping:
    def test_what_a_conversation_is_set_up_with_is_kept_whole_and_read_back_the_same(
        self, workspace: Workspace, tmp_path: Path
    ) -> None:
        config = resolve_config(
            {"team": ["Immunologist"], "code": {"where": "local", "python": "/opt/python"}, "max_cost": None},
            settings(),
            workspace,
        )
        directory = tmp_path / "chat"
        directory.mkdir()

        save_config(directory, config)

        assert load_config(directory) == config
        assert not list(directory.glob("*.tmp"))
        assert json.loads((directory / CONFIG_FILE_NAME).read_text())["code"]["python"] == "/opt/python"

    def test_a_conversation_that_was_set_not_to_stream_or_to_leave_out_what_is_not_for_commerce_is_read_back_so(
        self, workspace: Workspace, tmp_path: Path
    ) -> None:
        directory = tmp_path / "chat"
        directory.mkdir()
        for request in ({"stream": False, "commercial_mode": True}, {"stream": True, "commercial_mode": False}):
            config = resolve_config({"team": [], **request}, settings(), workspace)

            save_config(directory, config)
            loaded = load_config(directory)

            assert loaded is not None
            assert (loaded.stream, loaded.commercial_mode) == (request["stream"], request["commercial_mode"])

    def test_a_conversation_that_has_begun_is_not_changed_by_changing_the_library_or_the_settings(
        self, workspace: Workspace, tmp_path: Path
    ) -> None:
        config = resolve_config({"team": ["Immunologist"]}, settings(), workspace)
        directory = tmp_path / "chat"
        directory.mkdir()
        save_config(directory, config)
        was = config.team[0]

        workspace.save_scientist({**NANOBODY_EXPERT, "title": "Immunologist", "role": "something else entirely"})
        workspace.save_settings(settings(model="gpt-5.2", max_cost=99))

        loaded = load_config(directory)
        assert loaded is not None
        assert loaded.team[0] == was
        assert loaded.model == TEST_MODEL

    def test_nothing_is_read_from_a_conversation_without_a_setup_that_can_be_read(self, tmp_path: Path) -> None:
        directory = tmp_path / "chat"
        directory.mkdir()
        assert load_config(directory) is None

        good = ChatConfig(
            model=TEST_MODEL,
            lead=NANOBODY_EXPERT,
            team=(),
            code=CodeSetup(),
            max_cost=None,
            stream=True,
            commercial_mode=False,
        ).to_dict()
        broken: list[Any] = [
            "not json at all {",
            "[]",
            "null",
            json.dumps({key: value for key, value in good.items() if key != "model"}),
            json.dumps({**good, "lead": {"title": "only a title"}}),
            json.dumps({**good, "code": {"where": "cloud"}}),
            json.dumps({**good, "code": {"where": "none", "unknown": 1}}),
            json.dumps({**good, "team": None}),
            json.dumps({**good, "stream": None, "max_cost": None, "model": None, "code": None}),
        ]
        for text in broken:
            (directory / CONFIG_FILE_NAME).write_text(text)
            assert load_config(directory) is None, text

        (directory / CONFIG_FILE_NAME).write_text(json.dumps(good))
        assert load_config(directory) is not None


class TestSettings:
    def test_settings_are_shown_without_the_mcp_config_the_interface_keeps(self) -> None:
        shown = public_settings(Settings(mcp_config="/somewhere/servers.json"))

        assert tuple(shown) == PUBLIC_SETTINGS
        assert "mcp_config" not in shown

    def test_the_data_lake_and_the_keys_code_may_read_are_among_them(self) -> None:
        shown = public_settings(Settings(data_lake="/lake", forward_keys=["ANTHROPIC_API_KEY"]))

        assert shown["data_lake"] == "/lake"
        assert shown["forward_keys"] == ["ANTHROPIC_API_KEY"]
        assert public_settings(Settings())["data_lake"] == ""
        assert public_settings(Settings())["forward_keys"] == []

    def test_a_change_gives_settings_with_it_made_and_leaves_the_old_ones_as_they_were(
        self, workspace: Workspace
    ) -> None:
        old = Settings(max_cost=2.0, mcp_config="/keep/this.json")

        new = update_settings(
            old, {"model": "claude-sonnet-4-5", "max_cost": 3, "code": "docker", "sandbox": "bio"}, workspace
        )

        assert (new.model, new.max_cost, new.code, new.sandbox) == ("claude-sonnet-4-5", 3.0, "docker", "bio")
        assert isinstance(new.max_cost, float)
        assert new.mcp_config == "/keep/this.json"
        assert (old.max_cost, old.model, old.code) == (2.0, Settings().model, "none")

    def test_a_limit_of_nothing_may_be_spent_can_be_set(self, workspace: Workspace) -> None:
        assert update_settings(Settings(max_cost=2.0), {"max_cost": 0}, workspace).max_cost == 0.0

    def test_no_limit_can_be_set(self, workspace: Workspace) -> None:
        assert update_settings(Settings(max_cost=2.0), {"max_cost": None}, workspace).max_cost is None

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"colour": "red"}, "There is no setting colour"),
            ({"mcp_config": "/x.json"}, "There is no setting mcp_config"),
            ({"model": ""}, "Unable to determine the source"),
            ({"model": "no-such-model"}, "Unable to determine the source"),
            ({"code": "cloud"}, "Code runs in one of"),
            ({"sandbox": "huge"}, "The sandbox is one of"),
            ({"max_cost": -0.01}, "max_cost must be a finite amount"),
            ({"max_cost": float("nan")}, "max_cost must be a finite amount"),
            ({"max_cost": float("inf")}, "max_cost must be a finite amount"),
        ],
    )
    def test_a_change_that_cannot_be_used_is_refused(
        self, workspace: Workspace, changes: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            update_settings(Settings(), changes, workspace)


class TestModels:
    def test_the_models_say_whether_the_keys_they_need_are_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_SOURCE", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "set")

        found = {item["id"]: item for item in describe_models()}

        assert found["gpt-5.2"] == {"id": "gpt-5.2", "provider": "OpenAI", "ready": False}
        claude = next(item for item in found.values() if item["provider"] == "Anthropic")
        assert claude["ready"] is True

        monkeypatch.setenv("OPENAI_API_KEY", "set")
        assert {item["id"]: item for item in describe_models()}["gpt-5.2"]["ready"] is True

    def test_the_default_model_comes_first(self) -> None:
        assert describe_models()[0]["id"] == Settings().model


class TestWhatCodeHas:
    def test_code_in_one_of_biomnis_environments_is_given_the_data_lake_in_the_workspace(
        self, workspace: Workspace
    ) -> None:
        for sandbox in ("base", "bio", "full"):
            config = resolve_config({"code": {"where": "docker", "sandbox": sandbox}}, settings(), workspace)

            assert config.code.data_lake == str(workspace.data_lake_dir)

    def test_the_data_lake_the_settings_name_is_the_one_given(self, workspace: Workspace, tmp_path: Path) -> None:
        elsewhere = tmp_path / "biomni" / "data_lake"

        config = resolve_config(
            {"code": {"where": "docker", "sandbox": "bio"}}, settings(data_lake=str(elsewhere)), workspace
        )

        assert config.code.data_lake == str(elsewhere)

    @pytest.mark.parametrize(
        "code",
        [
            {"where": "docker", "sandbox": "python"},
            {"where": "local", "sandbox": "bio"},
            {"where": "none", "sandbox": "full"},
        ],
    )
    def test_code_not_in_one_of_biomnis_environments_is_given_none(
        self, workspace: Workspace, code: dict[str, str]
    ) -> None:
        assert resolve_config({"code": code}, settings(), workspace).code.data_lake == ""

    def test_what_the_settings_say_of_where_and_which_environment_decides_it_too(self, workspace: Workspace) -> None:
        chosen = settings(code="docker", sandbox="bio")

        assert resolve_config({}, chosen, workspace).code.data_lake == str(workspace.data_lake_dir)
        assert resolve_config({"code": {"sandbox": "python"}}, chosen, workspace).code.data_lake == ""

    def test_a_request_may_leave_the_data_lake_out_or_give_another(self, workspace: Workspace, tmp_path: Path) -> None:
        docker = {"where": "docker", "sandbox": "bio"}
        elsewhere = tmp_path / "mine"

        none = resolve_config({"code": {**docker, "data_lake": ""}}, settings(), workspace)
        other = resolve_config({"code": {**docker, "data_lake": str(elsewhere)}}, settings(), workspace)
        plain = resolve_config(
            {"code": {"where": "docker", "sandbox": "python", "data_lake": str(elsewhere)}}, settings(), workspace
        )

        assert none.code.data_lake == ""
        assert other.code.data_lake == str(elsewhere.resolve())
        assert plain.code.data_lake == str(elsewhere.resolve())

    def test_a_data_lake_that_cannot_be_used_is_refused(self, workspace: Workspace) -> None:
        with pytest.raises(ValueError, match="full path"):
            resolve_config({"code": {"where": "docker", "data_lake": "relative/lake"}}, settings(), workspace)

    def test_the_keys_the_settings_give_code_are_passed_in_where_code_is_in_docker(self, workspace: Workspace) -> None:
        chosen = settings(forward_keys=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"])

        for sandbox in ("python", "bio"):
            config = resolve_config({"code": {"where": "docker", "sandbox": sandbox}}, chosen, workspace)

            assert config.code.forward_env == ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]

    @pytest.mark.parametrize("where", ["none", "local"])
    def test_no_key_is_passed_where_code_is_not_in_docker(self, workspace: Workspace, where: str) -> None:
        chosen = settings(forward_keys=["ANTHROPIC_API_KEY"])

        assert resolve_config({"code": {"where": where}}, chosen, workspace).code.forward_env == []

    def test_no_key_is_passed_unless_one_is_chosen(self, workspace: Workspace) -> None:
        assert resolve_config({"code": {"where": "docker"}}, settings(), workspace).code.forward_env == []

    def test_a_request_may_choose_its_own_keys_or_none(self, workspace: Workspace) -> None:
        chosen = settings(forward_keys=["ANTHROPIC_API_KEY"])
        docker = {"where": "docker", "sandbox": "bio"}

        none = resolve_config({"code": {**docker, "forward_env": []}}, chosen, workspace)
        other = resolve_config({"code": {**docker, "forward_env": ["GROQ_API_KEY", "GROQ_API_KEY"]}}, chosen, workspace)

        assert none.code.forward_env == []
        assert other.code.forward_env == ["GROQ_API_KEY"]

    def test_a_key_that_is_not_one_the_interface_sets_cannot_be_passed_in(self, workspace: Workspace) -> None:
        with pytest.raises(ValueError, match="A key to give code is one of"):
            resolve_config({"code": {"where": "docker", "forward_env": ["HOME"]}}, settings(), workspace)

    def test_what_code_has_is_kept_with_the_conversation_and_read_back(
        self, workspace: Workspace, tmp_path: Path
    ) -> None:
        config = resolve_config(
            {"code": {"where": "docker", "sandbox": "bio", "forward_env": ["ANTHROPIC_API_KEY"]}},
            settings(),
            workspace,
        )
        directory = tmp_path / "chat"
        directory.mkdir()

        save_config(directory, config)

        saved = json.loads((directory / CONFIG_FILE_NAME).read_text())["code"]
        assert saved["data_lake"] == str(workspace.data_lake_dir)
        assert saved["forward_env"] == ["ANTHROPIC_API_KEY"]
        assert load_config(directory) == config

    def test_a_conversation_set_up_before_these_existed_is_read_with_none(
        self, workspace: Workspace, tmp_path: Path
    ) -> None:
        directory = tmp_path / "chat"
        directory.mkdir()
        old = resolve_config({"team": []}, settings(), workspace).to_dict()
        for name in ("data_lake", "forward_env"):
            del old["code"][name]
        (directory / CONFIG_FILE_NAME).write_text(json.dumps(old))

        loaded = load_config(directory)

        assert loaded is not None
        assert (loaded.code.data_lake, loaded.code.forward_env) == ("", [])

    def test_the_data_lake_is_the_one_the_settings_name_or_the_workspaces(
        self, workspace: Workspace, tmp_path: Path
    ) -> None:
        assert data_lake_directory(settings(), workspace) == workspace.data_lake_dir
        assert data_lake_directory(settings(data_lake=str(tmp_path / "x")), workspace) == tmp_path / "x"
        assert data_lake_directory(settings(data_lake="~/lake"), workspace) == Path.home() / "lake"


class TestCheckingTheDataLake:
    def test_nothing_is_the_workspaces_own(self, workspace: Workspace) -> None:
        assert check_data_lake("", workspace) == ""
        assert check_data_lake("   ", workspace) == ""

    def test_a_full_path_is_kept_as_it_resolves(self, workspace: Workspace, tmp_path: Path) -> None:
        assert check_data_lake(f"  {tmp_path}/biomni/../lake  ", workspace) == str(tmp_path.resolve() / "lake")

    def test_a_path_that_is_not_there_yet_is_allowed(self, workspace: Workspace, tmp_path: Path) -> None:
        assert check_data_lake(str(tmp_path / "not" / "yet"), workspace) == str(tmp_path.resolve() / "not" / "yet")

    def test_the_home_directory_is_expanded(self, workspace: Workspace) -> None:
        assert check_data_lake("~/biomni/data_lake", workspace) == str((Path.home() / "biomni" / "data_lake").resolve())

    @pytest.mark.parametrize("value", ["lake", "./lake", "../lake", "biomni/data_lake"])
    def test_a_path_that_is_not_a_full_one_is_refused(self, workspace: Workspace, value: str) -> None:
        with pytest.raises(ValueError, match="full path"):
            check_data_lake(value, workspace)

    def test_a_file_is_refused(self, workspace: Workspace, tmp_path: Path) -> None:
        (tmp_path / "file").write_text("")

        with pytest.raises(ValueError, match="is a file"):
            check_data_lake(str(tmp_path / "file"), workspace)

    @pytest.mark.parametrize("value", [None, 5, ["/x"], {"a": 1}])
    def test_what_is_not_text_is_refused(self, workspace: Workspace, value: Any) -> None:
        with pytest.raises(ValueError, match="The data lake is a directory, not"):
            check_data_lake(value, workspace)

    @pytest.mark.parametrize("name", ["with,comma", 'with"quote', "with\nbreak"])
    def test_a_path_that_docker_cannot_mount_is_refused(self, workspace: Workspace, tmp_path: Path, name: str) -> None:
        with pytest.raises(ValueError, match="cannot mount a path containing a comma"):
            check_data_lake(str(tmp_path / name), workspace)

    def test_where_conversations_are_kept_is_refused_and_so_is_what_holds_them(self, workspace: Workspace) -> None:
        for where in (
            workspace.chats_dir,
            workspace.chats_dir / "a-chat" / "work",
            workspace.root,
            workspace.root.parent,
        ):
            with pytest.raises(ValueError, match="cannot be where conversations are kept"):
                check_data_lake(str(where), workspace)

    def test_beside_the_conversations_is_where_the_data_lake_is_kept_by_default(self, workspace: Workspace) -> None:
        assert check_data_lake(str(workspace.data_lake_dir), workspace) == str(workspace.data_lake_dir)

    def test_a_directory_whose_name_only_starts_as_the_conversations_does_is_allowed(
        self, workspace: Workspace
    ) -> None:
        beside = workspace.root / "chats-and-more"

        assert check_data_lake(str(beside), workspace) == str(beside)


class TestCheckingTheKeys:
    def test_the_keys_the_interface_sets_are_kept_once_each_in_the_order_given(self) -> None:
        assert check_forward_keys(["GROQ_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY"]) == [
            "GROQ_API_KEY",
            "ANTHROPIC_API_KEY",
        ]
        assert check_forward_keys(("OPENAI_API_KEY",)) == ["OPENAI_API_KEY"]
        assert check_forward_keys([]) == []

    def test_a_name_that_is_not_one_of_them_is_refused_and_named(self) -> None:
        with pytest.raises(ValueError, match="not HOME, PATH$"):
            check_forward_keys(["ANTHROPIC_API_KEY", "HOME", "PATH"])

    @pytest.mark.parametrize("names", ["ANTHROPIC_API_KEY", None, 3, {"ANTHROPIC_API_KEY": 1}])
    def test_what_is_not_a_list_is_refused(self, names: Any) -> None:
        with pytest.raises(ValueError, match="a list of names"):
            check_forward_keys(names)


class TestChangingWhatCodeHas:
    def test_a_data_lake_and_keys_can_be_set_and_are_kept_in_the_form_code_uses(
        self, workspace: Workspace, tmp_path: Path
    ) -> None:
        new = update_settings(
            Settings(),
            {"data_lake": f"{tmp_path}/a/../lake", "forward_keys": ["GROQ_API_KEY", "GROQ_API_KEY"]},
            workspace,
        )

        assert new.data_lake == str(tmp_path.resolve() / "lake")
        assert new.forward_keys == ["GROQ_API_KEY"]

    def test_the_workspaces_own_data_lake_is_asked_for_by_nothing(self, workspace: Workspace) -> None:
        assert update_settings(Settings(data_lake="/old/lake"), {"data_lake": ""}, workspace).data_lake == ""

    def test_what_is_not_changed_is_not_looked_at_again(self, workspace: Workspace) -> None:
        old = Settings(data_lake="relative", forward_keys=["HOME"])

        new = update_settings(old, {"stream": False}, workspace)

        assert (new.data_lake, new.forward_keys) == ("relative", ["HOME"])

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"data_lake": "relative"}, "full path"),
            ({"data_lake": 5}, "The data lake is a directory"),
            ({"forward_keys": ["HOME"]}, "A key to give code is one of"),
            ({"forward_keys": "ANTHROPIC_API_KEY"}, "a list of names"),
        ],
    )
    def test_a_data_lake_or_keys_that_cannot_be_used_are_refused(
        self, workspace: Workspace, changes: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            update_settings(Settings(), changes, workspace)

    def test_the_data_lake_is_looked_for_where_conversations_are_kept(self, workspace: Workspace) -> None:
        with pytest.raises(ValueError, match="cannot be where conversations are kept"):
            update_settings(Settings(), {"data_lake": str(workspace.root)}, workspace)
