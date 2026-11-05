"""Tests of the library of skills that comes with the lab: that what ships is whole and as it was released, how its
licenses are told apart, and offering its skills, previewing them, and putting them in."""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MODEL
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_server_app import BEARER, LOCAL, TOKEN
from test_skills import write_skill

from virtual_lab.server.app import create_app
from virtual_lab.server.skills import SKILL_LIBRARY_DIR_VARIABLE, Skills, skill_library_dir
from virtual_lab.server.workspace import Settings, Workspace
from virtual_lab.skill_library import (
    INDEX_FILE_NAME,
    LIBRARY_DIR_NAME,
    check_library_names,
    library_directory,
    license_kind,
    read_library,
)
from virtual_lab.skills import MAX_SKILLS

SHIPPED = library_directory()


def make_library(
    directory: Path,
    skills: dict[str, dict[str, Any]],
    source: dict[str, str] | None = None,
) -> Path:
    """A library of the shape that ships: an index, and the skills in a skills/ folder. Each skill is given its
    description and license, with its group, category, and any other file to write."""
    index: dict[str, Any] = {"source": source or {"name": "Test skills", "version": "1.0"}, "skills": {}}
    for name, options in skills.items():
        license = options.get("license", "MIT")
        extra = f"license: {license}\n" if license is not None else ""
        write_skill(
            directory / "skills",
            name=name,
            description=options.get("description", f"Does {name} things."),
            extra=extra + options.get("extra", ""),
            files=options.get("files"),
        )
        index["skills"][name] = {
            "group": options.get("group", "Packages"),
            "category": options.get("category", "Statistics"),
            "files": 1 + len(options.get("files") or {}),
            "bytes": 10,
        }
    (directory / INDEX_FILE_NAME).write_text(json.dumps(index))

    return directory


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = make_library(
        tmp_path / "library",
        {
            "alpha": {
                "description": "Fits alpha.",
                "category": "Statistics",
                "files": {"scripts/run.py": "print(1)\n"},
            },
            "beta": {"description": "Fits beta.", "category": "Statistics", "license": "GPL-3.0-or-later"},
            "gamma": {"description": "Reads gamma.", "category": "Imaging", "group": "Biology", "license": None},
            "delta": {
                "description": "Draws delta.",
                "category": "Imaging",
                "group": "Biology",
                "license": "CC BY-NC-SA 4.0",
            },
        },
        source={"name": "Test skills", "author": "Someone", "version": "1.2.3", "ref": "abc123", "license": "MIT"},
    )
    monkeypatch.setenv(SKILL_LIBRARY_DIR_VARIABLE, str(directory))

    return directory


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    store = Workspace(tmp_path / "workspace")
    store.save_settings(Settings(model=TEST_MODEL, max_cost=None))

    return store


@pytest.fixture
def app(workspace: Workspace) -> FastAPI:
    return create_app(workspace.root, token=TOKEN, check_keys=False)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


def names_of(listing: dict[str, Any]) -> list[str]:
    return [skill["name"] for skill in listing["skills"]]


class TestWhatShips:
    def test_the_library_is_beside_the_code_and_is_where_the_server_looks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(SKILL_LIBRARY_DIR_VARIABLE, raising=False)

        assert SHIPPED.name == LIBRARY_DIR_NAME and SHIPPED.is_dir()
        assert skill_library_dir() == SHIPPED

    def test_every_skill_in_it_can_be_used_and_is_in_the_index_and_the_index_is_of_what_is_there(self) -> None:
        offered = read_library(SHIPPED)
        folders = sorted(path.name for path in (SHIPPED / "skills").iterdir() if path.is_dir())

        assert offered.problems == ()
        assert sorted(entry.skill.name for entry in offered.skills) == folders
        assert len(folders) >= 100
        for entry in offered.skills:
            files = [path for path in entry.skill.directory.rglob("*") if path.is_file()]
            assert entry.skill.directory.name == entry.skill.name
            assert entry.skill.notes == (), f"{entry.skill.name} departs from the standard: {entry.skill.notes}"
            assert (entry.files, entry.bytes) == (len(files), sum(path.stat().st_size for path in files)), (
                f"The index is not of what is in {entry.skill.name}. Run scripts/update_scientific_skills.py"
            )
            assert entry.group and entry.category

    def test_it_says_which_release_it_is_and_keeps_that_release_s_license(self) -> None:
        offered = read_library(SHIPPED)

        assert offered.source["name"] == "Scientific Agent Skills"
        assert offered.source["author"] == "K-Dense Inc."
        assert offered.source["license"] == "MIT"
        assert re.fullmatch(r"\d+\.\d+\.\d+", offered.source["version"])
        assert re.fullmatch(r"[0-9a-f]{40}", offered.source["ref"])
        text = (SHIPPED / "LICENSE.md").read_text(encoding="utf-8")
        assert text.startswith("MIT License") and "K-Dense Inc." in text

    def test_it_has_no_links_and_nothing_a_machine_made(self) -> None:
        found = list(SHIPPED.rglob("*"))

        assert not [path for path in found if path.is_symlink()]
        assert not [
            path for path in found if path.name in {".DS_Store", "__pycache__", ".git"} or path.suffix == ".pyc"
        ]

    def test_the_notice_names_each_skill_whose_license_is_not_a_plain_one(self) -> None:
        notice = (Path(__file__).parent.parent / "NOTICE").read_text(encoding="utf-8")
        offered = read_library(SHIPPED)

        for entry in offered.skills:
            if entry.kind in {"noncommercial", "copyleft"}:
                assert entry.skill.name in notice, (
                    f"NOTICE does not name {entry.skill.name}, which is {entry.skill.license}"
                )

    def test_every_skill_of_it_can_be_put_in_whole(self, workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(SKILL_LIBRARY_DIR_VARIABLE, raising=False)
        skills = Skills(workspace)
        everything = names_of(skills.library())

        done = skills.install_from_library(everything)

        assert [skill["name"] for skill in done["installed"]] == everything
        assert done["skipped"] == []
        assert [skill for skill in done["installed"] if skill["left_out"]] == []
        assert sorted(names_of(done)) == sorted(everything)
        assert all(entry["installed"] for entry in skills.library()["skills"])
        assert done["catalog"]["skills"] == len(everything) <= MAX_SKILLS


class TestLicenses:
    @pytest.mark.parametrize(
        ("license", "kind"),
        [
            ("MIT", "other"),
            ("MIT license", "other"),
            ("Apache-2.0 license", "other"),
            ("BSD-3-Clause", "other"),
            ("CC-BY-4.0", "other"),
            ("Proprietary (API key required)", "other"),
            ("https://github.com/sympy/sympy/blob/master/LICENSE", "other"),
            ("PolyForm-Noncommercial-1.0.0", "noncommercial"),
            ("CC BY-NC-SA 4.0", "noncommercial"),
            ("CC-BY-NC-4.0", "noncommercial"),
            ("GPLv3 license", "copyleft"),
            ("GPL-2.0 license", "copyleft"),
            ("GPL-3.0-or-later", "copyleft"),
            ("LGPL-3.0", "copyleft"),
            ("Unknown", "none"),
            ("unknown", "none"),
            ("None", "none"),
            ("", "none"),
            (None, "none"),
            ("  ", "none"),
        ],
    )
    def test_a_license_is_told_apart_by_what_a_person_ought_to_know_of_it(self, license: str | None, kind: str) -> None:
        assert license_kind(license) == kind

    def test_a_sentence_about_the_data_a_skill_reads_is_not_taken_for_the_skill_s_own_license(self) -> None:
        sentence = (
            "This skill is provided under the MIT License. IDC data itself has individual licensing (mostly CC-BY, "
            "some CC-NC) that must be respected when using the data."
        )

        assert license_kind(sentence) == "other"


class TestReadingALibrary:
    def test_a_folder_with_no_index_has_no_skills_and_no_complaint(self, tmp_path: Path) -> None:
        offered = read_library(tmp_path)

        assert offered.skills == () and offered.problems == () and offered.source == {}
        assert offered.categories() == []

    @pytest.mark.parametrize("text", ["{", "[]", '{"skills": []}', '{"skills": "x"}'])
    def test_an_index_that_cannot_be_read_is_said_of_and_offers_nothing(self, tmp_path: Path, text: str) -> None:
        (tmp_path / INDEX_FILE_NAME).write_text(text)

        offered = read_library(tmp_path)

        assert offered.skills == () and len(offered.problems) == 1

    def test_a_skill_that_cannot_be_used_is_left_out_and_said_of_and_the_rest_are_offered(self, tmp_path: Path) -> None:
        make_library(tmp_path, {"good": {}, "broken": {}})
        (tmp_path / "skills" / "broken" / "SKILL.md").write_text("no front matter")
        index = json.loads((tmp_path / INDEX_FILE_NAME).read_text())
        index["skills"]["missing"] = {"group": "G", "category": "C"}
        index["skills"]["odd"] = "not an object"
        (tmp_path / INDEX_FILE_NAME).write_text(json.dumps(index))

        offered = read_library(tmp_path)

        assert [entry.skill.name for entry in offered.skills] == ["good"]
        assert sorted(problem.split(":")[0] for problem in offered.problems) == ["broken", "missing", "odd"]

    def test_a_skill_the_index_does_not_list_is_not_offered(self, tmp_path: Path) -> None:
        make_library(tmp_path, {"listed": {}})
        write_skill(tmp_path / "skills", name="stray")

        assert [entry.skill.name for entry in read_library(tmp_path).skills] == ["listed"]

    def test_categories_are_counted_in_the_order_they_are_first_listed(self, library: Path) -> None:
        assert read_library(library).categories() == [
            {"name": "Statistics", "group": "Packages", "count": 2},
            {"name": "Imaging", "group": "Biology", "count": 2},
        ]

    def test_a_skill_with_no_category_is_in_its_group(self, tmp_path: Path) -> None:
        make_library(tmp_path, {"loose": {}})
        index = json.loads((tmp_path / INDEX_FILE_NAME).read_text())
        del index["skills"]["loose"]["category"]
        (tmp_path / INDEX_FILE_NAME).write_text(json.dumps(index))

        assert read_library(tmp_path).skills[0].category == "Packages"

    def test_names_to_put_in_are_checked_against_the_library(self, library: Path) -> None:
        offered = read_library(library)

        assert check_library_names(["beta", "alpha", "beta"], offered) == ["beta", "alpha"]
        with pytest.raises(ValueError, match="no skill called 'nope'"):
            check_library_names(["alpha", "nope"], offered)
        with pytest.raises(ValueError, match="list of their names"):
            check_library_names("alpha", offered)
        with pytest.raises(ValueError, match="no skill called"):
            check_library_names([3], offered)


class TestOfferingAndPuttingIn:
    def test_the_library_is_offered_with_each_skill_s_license_and_where_it_came_from(
        self, client: TestClient, library: Path
    ) -> None:
        offered = client.get("/api/skill-library").json()

        assert offered["source"]["version"] == "1.2.3" and offered["source"]["author"] == "Someone"
        assert names_of(offered) == ["alpha", "beta", "gamma", "delta"]
        alpha, beta, gamma, delta = offered["skills"]
        assert alpha == {
            "name": "alpha",
            "description": "Fits alpha.",
            "group": "Packages",
            "category": "Statistics",
            "license": "MIT",
            "license_kind": "other",
            "compatibility": None,
            "files": 2,
            "bytes": 10,
            "installed": False,
        }
        assert (beta["license_kind"], gamma["license_kind"], delta["license_kind"]) == (
            "copyleft",
            "none",
            "noncommercial",
        )
        assert [(each["name"], each["count"]) for each in offered["categories"]] == [("Statistics", 2), ("Imaging", 2)]
        assert offered["problems"] == []
        assert str(library) not in json.dumps(offered)

    def test_an_empty_library_is_offered_as_nothing(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(SKILL_LIBRARY_DIR_VARIABLE, str(tmp_path / "nowhere"))

        assert client.get("/api/skill-library").json() == {"source": {}, "skills": [], "categories": [], "problems": []}

    def test_skills_put_in_are_copies_in_the_workspace_and_are_on_and_then_are_marked_as_in(
        self, client: TestClient, workspace: Workspace, library: Path
    ) -> None:
        done = client.post("/api/skill-library/install", json={"names": ["alpha", "gamma"]})

        assert done.status_code == 200
        body = done.json()
        assert body["installed"] == [{"name": "alpha", "left_out": 0}, {"name": "gamma", "left_out": 0}]
        assert body["skipped"] == []
        assert (workspace.skills_dir / "alpha" / "scripts" / "run.py").read_text() == "print(1)\n"
        assert names_of(body) == ["alpha", "gamma"]
        assert all(
            skill["enabled"] and skill["removable"] and skill["source"] == "workspace" for skill in body["skills"]
        )
        assert body["catalog"]["skills"] == 2
        offered = client.get("/api/skill-library").json()
        assert [(skill["name"], skill["installed"]) for skill in offered["skills"]] == [
            ("alpha", True),
            ("beta", False),
            ("gamma", True),
            ("delta", False),
        ]

    def test_a_skill_that_is_in_already_is_left_and_the_rest_are_put_in(
        self, client: TestClient, library: Path
    ) -> None:
        client.post("/api/skill-library/install", json={"names": ["alpha"]})

        again = client.post("/api/skill-library/install", json={"names": ["alpha", "beta"]}).json()

        assert again["installed"] == [{"name": "beta", "left_out": 0}]
        assert again["skipped"] == [{"name": "alpha", "reason": "you already have a skill with that name"}]

    def test_a_skill_put_in_can_be_turned_off_and_deleted_as_any_other(self, client: TestClient, library: Path) -> None:
        client.post("/api/skill-library/install", json={"names": ["alpha", "beta"]})

        off = client.put("/api/skills", json={"disabled": ["beta"]}).json()
        assert off["catalog"]["skills"] == 1
        gone = client.delete("/api/skills/alpha").json()

        assert names_of(gone) == ["beta"]
        assert [
            (skill["name"], skill["installed"]) for skill in client.get("/api/skill-library").json()["skills"][:2]
        ] == [
            ("alpha", False),
            ("beta", True),
        ]

    @pytest.mark.parametrize(
        "body",
        [{"names": []}, {"names": ["nope"]}, {"names": ["alpha", "nope"]}, {"names": [3]}, {}, {"names": "alpha"}],
    )
    def test_names_that_are_not_skills_of_the_library_are_refused_and_nothing_is_put_in(
        self, client: TestClient, workspace: Workspace, library: Path, body: dict[str, Any]
    ) -> None:
        refused = client.post("/api/skill-library/install", json=body)

        assert refused.status_code == 422
        assert not workspace.skills_dir.exists() or not list(workspace.skills_dir.iterdir())

    def test_more_names_than_there_can_be_skills_are_refused(self, client: TestClient, library: Path) -> None:
        refused = client.post(
            "/api/skill-library/install", json={"names": [f"s{number}" for number in range(MAX_SKILLS + 1)]}
        )

        assert refused.status_code == 422

    def test_a_skill_can_be_read_before_it_is_put_in(self, client: TestClient, library: Path) -> None:
        read = client.get("/api/skill-library/alpha")

        assert read.status_code == 200
        body = read.json()
        assert body["name"] == "alpha" and "Fit a four-parameter logistic." in body["instructions"]
        assert body["files"] == ["scripts/run.py"]
        assert client.get("/api/skill-library/nope").status_code == 404
        assert client.get("/api/skills/alpha").status_code == 404

    def test_a_skill_of_the_library_is_not_one_of_the_lab_s_until_it_is_put_in(
        self, client: TestClient, library: Path
    ) -> None:
        assert client.get("/api/skills").json()["skills"] == []

    def test_the_routes_need_the_token(self, app: FastAPI, library: Path) -> None:
        with TestClient(app, base_url=LOCAL) as anonymous:
            assert anonymous.get("/api/skill-library").status_code == 401
            assert anonymous.post("/api/skill-library/install", json={"names": ["alpha"]}).status_code == 401
            assert anonymous.get("/api/skill-library/alpha").status_code == 401


class TestWhatTheSkillsTake:
    def test_the_skills_that_are_on_are_counted_for_what_they_take_of_every_conversation(
        self, client: TestClient, library: Path
    ) -> None:
        assert client.get("/api/skills").json()["catalog"] == {
            "skills": 0,
            "chars": 0,
            "budget": 20_000,
            "description_chars": 250,
            "without_description": 0,
        }

        client.post("/api/skill-library/install", json={"names": ["alpha", "beta", "gamma"]})
        two = client.put("/api/skills", json={"disabled": ["gamma"]}).json()["catalog"]

        assert two["skills"] == 2
        assert two["chars"] == len("- alpha: Fits alpha.\n- beta: Fits beta.\n")
