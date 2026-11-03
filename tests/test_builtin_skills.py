"""Tests of the skills that come with the lab: what is shipped, and how the server lists, turns off, and gives them."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import TEST_MODEL
from fastapi.testclient import TestClient
from test_server_app import BEARER, LOCAL, TOKEN
from test_skills import tools_of, write_skill

from virtual_lab.server.app import create_app
from virtual_lab.server.config import resolve_config
from virtual_lab.server.skills import (
    BUILTIN_SKILLS_DIR_VARIABLE,
    Skills,
    builtin_skills_dir,
    load_skills,
    skill_roots,
)
from virtual_lab.server.workspace import Settings, Workspace
from virtual_lab.skills import (
    BUILTIN_SOURCE,
    CATALOG_DESCRIPTION_CHARS,
    STANDARD_NAME,
    builtin_skills,
    builtin_skills_directory,
    read_body,
    skills_prompt,
)

NAMES = [
    "dependency-screen-scores",
    "enrichment-analysis-conventions",
    "multiple-testing-small-panels",
    "quantitative-answer-checklist",
    "sample-ids-and-pca",
    "software-versions-and-definitions",
    "variant-call-statistics",
]


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    store = Workspace(tmp_path / "workspace")
    store.save_settings(Settings(model=TEST_MODEL, max_cost=None))

    return store


@pytest.fixture
def shipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The server reads the skills that ship with the lab, which the other tests keep out of what they count."""
    monkeypatch.delenv(BUILTIN_SKILLS_DIR_VARIABLE)


@pytest.fixture
def client(workspace: Workspace) -> Iterator[TestClient]:
    with TestClient(
        create_app(workspace.root, token=TOKEN, check_keys=False), base_url=LOCAL, headers=BEARER
    ) as opened:
        yield opened


class TestWhatIsShipped:
    def test_the_lab_comes_with_seven_skills_that_are_all_found_and_have_nothing_wrong(self) -> None:
        skills = builtin_skills()

        assert [skill.name for skill in skills] == NAMES
        assert all(skill.source == BUILTIN_SOURCE for skill in skills)
        assert all(skill.notes == () for skill in skills), [skill.notes for skill in skills]

    def test_each_is_in_a_folder_of_its_name_under_a_standard_name_with_a_license_and_an_author(self) -> None:
        for skill in builtin_skills():
            assert skill.directory == builtin_skills_directory() / skill.name
            assert STANDARD_NAME.fullmatch(skill.name)
            assert skill.license == "MIT"
            assert skill.metadata["author"] == "virtual_lab contributors"
            assert skill.metadata["version"] and skill.metadata["source"]

    def test_each_says_when_to_use_it_in_less_than_the_catalog_shows(self) -> None:
        for skill in builtin_skills():
            assert skill.description.startswith("Use "), skill.name
            assert 100 <= len(skill.description) <= CATALOG_DESCRIPTION_CHARS, skill.name

    def test_each_has_instructions_that_begin_with_a_title_and_no_metadata_section_of_the_old_format(self) -> None:
        for skill in builtin_skills():
            body = read_body(skill)
            assert body.startswith("# "), skill.name
            assert "## Metadata" not in body and "**Commercial Use**" not in body, skill.name
            assert len(body) > 1_000, skill.name

    def test_the_readme_beside_them_is_not_a_skill(self) -> None:
        assert (builtin_skills_directory() / "README.md").is_file()
        assert "README" not in [skill.name for skill in builtin_skills()]

    def test_the_lead_is_told_of_all_of_them_whole_in_a_few_hundred_tokens(self) -> None:
        told = skills_prompt(builtin_skills())

        for skill in builtin_skills():
            assert f"- {skill.name}: {skill.description}\n" in told + "\n"
        assert len(told) < 3_000

    def test_the_lead_activates_one_and_is_given_its_instructions(self) -> None:
        activate = tools_of(*builtin_skills())["activate_skill"]

        given = activate("quantitative-answer-checklist")

        assert given.startswith('<skill_content name="quantitative-answer-checklist">')
        assert "Restate what is asked" in given
        assert "name: quantitative-answer-checklist" not in given


class TestWhereTheServerFindsThem:
    def test_the_folder_is_the_one_that_ships_unless_another_is_named(
        self, shipped: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        assert builtin_skills_dir() == builtin_skills_directory()
        monkeypatch.setenv(BUILTIN_SKILLS_DIR_VARIABLE, str(tmp_path / "mine"))
        assert builtin_skills_dir() == tmp_path / "mine"

    def test_they_are_looked_for_last_so_that_a_persons_own_skill_takes_their_place(self, workspace: Workspace) -> None:
        roots = skill_roots(workspace)

        assert [source for source, _ in roots] == ["workspace", "user", "builtin"]
        assert roots[-1][1] == builtin_skills_dir()

    def test_they_are_in_the_library_with_the_others(self, shipped: None, workspace: Workspace) -> None:
        write_skill(workspace.skills_dir, name="mine")

        library = load_skills(workspace)

        assert [skill.name for skill in library.skills] == sorted([*NAMES, "mine"])
        assert {skill.source for skill in library.skills} == {"workspace", "builtin"}
        assert library.problems == ()

    def test_a_skill_of_the_same_name_that_a_person_puts_in_is_used_in_place_of_one(
        self, shipped: None, workspace: Workspace
    ) -> None:
        write_skill(workspace.skills_dir, name="sample-ids-and-pca", description="Mine.")

        library = load_skills(workspace)

        skill = library.named("sample-ids-and-pca")
        assert skill is not None and (skill.description, skill.source) == ("Mine.", "workspace")
        assert len(library.skills) == len(NAMES)
        assert [problem.path.parent.name for problem in library.problems] == ["sample-ids-and-pca"]

    def test_an_empty_folder_does_away_with_them(self, workspace: Workspace) -> None:
        assert load_skills(workspace).skills == ()


class TestListingThem:
    def test_each_is_listed_as_on_and_not_to_be_deleted_with_where_it_came_from(
        self, shipped: None, workspace: Workspace
    ) -> None:
        listing = Skills(workspace).describe()

        assert [skill["name"] for skill in listing["skills"]] == NAMES
        for skill in listing["skills"]:
            assert (skill["source"], skill["enabled"], skill["removable"]) == ("builtin", True, False)
            assert skill["directory"] == str(builtin_skills_directory() / skill["name"])
        assert {"source": "builtin", "path": str(builtin_skills_directory()), "exists": True} in listing["folders"]

    def test_a_skill_that_replaces_one_of_them_can_be_deleted_and_they_come_back(
        self, shipped: None, workspace: Workspace
    ) -> None:
        write_skill(workspace.skills_dir, name="sample-ids-and-pca", description="Mine.")
        skills = Skills(workspace)
        mine = next(skill for skill in skills.describe()["skills"] if skill["name"] == "sample-ids-and-pca")
        assert (mine["source"], mine["removable"]) == ("workspace", True)

        after = skills.remove("sample-ids-and-pca")

        back = next(skill for skill in after["skills"] if skill["name"] == "sample-ids-and-pca")
        assert (back["source"], back["removable"]) == ("builtin", False)

    def test_they_cannot_be_deleted_and_the_reason_is_that_they_come_with_the_lab(
        self, shipped: None, client: TestClient
    ) -> None:
        reply = client.delete("/api/skills/sample-ids-and-pca")

        assert reply.status_code == 409
        assert "comes with the lab" in reply.text and "Turn it off" in reply.text
        assert (builtin_skills_directory() / "sample-ids-and-pca" / "SKILL.md").is_file()
        assert len(client.get("/api/skills").json()["skills"]) == len(NAMES)

    def test_they_are_shown_with_what_they_tell_the_lead(self, shipped: None, client: TestClient) -> None:
        preview = client.get("/api/skills/variant-call-statistics").json()

        assert preview["instructions"].startswith("# Variant Call Summary Statistics")
        assert preview["files"] == [] and preview["more_files"] == 0


class TestGivingThemToAConversation:
    def test_a_new_conversation_is_given_all_of_them_that_are_on(self, shipped: None, workspace: Workspace) -> None:
        config = resolve_config({}, workspace.load_settings(), workspace)

        assert list(config.skills) == NAMES

    def test_one_turned_off_is_not_given_and_it_can_still_be_chosen_for_a_conversation(
        self, shipped: None, workspace: Workspace
    ) -> None:
        Skills(workspace).set_disabled(["sample-ids-and-pca"])

        by_default = resolve_config({}, workspace.load_settings(), workspace)
        chosen = resolve_config({"skills": ["sample-ids-and-pca"]}, workspace.load_settings(), workspace)

        assert "sample-ids-and-pca" not in by_default.skills and len(by_default.skills) == len(NAMES) - 1
        assert list(chosen.skills) == ["sample-ids-and-pca"]

    def test_turning_one_off_over_the_api_is_kept(self, shipped: None, client: TestClient) -> None:
        reply = client.put("/api/skills", json={"disabled": ["software-versions-and-definitions"]})

        assert reply.status_code == 200
        off = [skill["name"] for skill in reply.json()["skills"] if not skill["enabled"]]
        assert off == ["software-versions-and-definitions"]

    def test_a_person_can_put_in_a_skill_of_the_name_of_one_and_it_is_not_refused(
        self, shipped: None, workspace: Workspace, tmp_path: Path
    ) -> None:
        write_skill(tmp_path / "source", name="sample-ids-and-pca", description="Mine.")

        result = Skills(workspace).install(None, str(tmp_path / "source"))

        assert [skill["name"] for skill in result["installed"]] == ["sample-ids-and-pca"]
        assert result["skipped"] == []
        assert (workspace.skills_dir / "sample-ids-and-pca" / "SKILL.md").is_file()
