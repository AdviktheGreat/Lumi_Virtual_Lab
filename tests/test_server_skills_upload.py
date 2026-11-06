"""Tests of putting in skills from a folder that a page uploads, as its files each with where it is in the folder."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MODEL
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_server_app import BEARER, LOCAL, TOKEN

from virtual_lab.server import app as app_module
from virtual_lab.server import skills as server_skills
from virtual_lab.server.app import create_app
from virtual_lab.server.skills import USER_SKILLS_DIR_VARIABLE, check_upload_folder, check_upload_path
from virtual_lab.server.workspace import Settings, Workspace

SKILL = "---\nname: fit\ndescription: Fits a curve. Use it when a potency is asked for.\n---\n\n# Fit\n\nDo it well.\n"


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    store = Workspace(tmp_path / "workspace")
    store.save_settings(Settings(model=TEST_MODEL, max_cost=None))

    return store


@pytest.fixture(autouse=True)
def user_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "user-skills"
    monkeypatch.setenv(USER_SKILLS_DIR_VARIABLE, str(directory))

    return directory


@pytest.fixture
def app(workspace: Workspace) -> FastAPI:
    return create_app(workspace.root, token=TOKEN, check_keys=False)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


def upload(client: TestClient, folder: Any, files: dict[str, str | bytes]) -> Any:
    """Sends a folder as a page does: its name, and each file's path beside the file."""
    return client.post(
        "/api/skills/upload",
        data={"folder": folder, "paths": list(files)},
        files=[("files", (path.rsplit("/", 1)[-1], content)) for path, content in files.items()],
    )


class TestUploadingAFolder:
    def test_a_folder_that_is_a_skill_is_kept_as_a_copy_that_is_on(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        response = upload(
            client, "fit", {"SKILL.md": SKILL, "scripts/fit.py": "print('fit')", "data/blob.bin": b"\x00\xff"}
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["installed"] == [{"name": "fit", "left_out": 0}] and body["skipped"] == []
        assert [(skill["name"], skill["enabled"], skill["removable"]) for skill in body["skills"]] == [
            ("fit", True, True)
        ]
        kept = workspace.skills_dir / "fit"
        assert (kept / "SKILL.md").read_text() == SKILL
        assert (kept / "scripts" / "fit.py").read_text() == "print('fit')"
        assert (kept / "data" / "blob.bin").read_bytes() == b"\x00\xff"

    def test_a_folder_of_skills_is_searched_for_them(self, client: TestClient, workspace: Workspace) -> None:
        other = SKILL.replace("name: fit", "name: other")
        files = {"skills/fit/SKILL.md": SKILL, "skills/other/SKILL.md": other, "skills/other/notes.md": "Notes."}

        body = upload(client, "collection", files).json()

        assert sorted(item["name"] for item in body["installed"]) == ["fit", "other"]
        assert (workspace.skills_dir / "other" / "notes.md").read_text() == "Notes."

    def test_a_skill_with_no_name_is_called_what_its_folder_is(self, client: TestClient, workspace: Workspace) -> None:
        nameless = "---\ndescription: Fits a curve.\n---\n\nBody.\n"

        body = upload(client, "my-skill", {"SKILL.md": nameless}).json()

        assert body["installed"] == [{"name": "my-skill", "left_out": 0}]
        assert (workspace.skills_dir / "my-skill" / "SKILL.md").is_file()

    def test_the_folder_is_called_the_last_of_what_it_was_given(self, client: TestClient, workspace: Workspace) -> None:
        nameless = "---\ndescription: Fits a curve.\n---\n\nBody.\n"

        body = upload(client, "../../outside/my-skill/", {"SKILL.md": nameless}).json()

        assert body["installed"] == [{"name": "my-skill", "left_out": 0}]
        assert not (workspace.root.parent / "outside").exists()

    def test_a_name_that_is_taken_is_left_and_said(self, client: TestClient, workspace: Workspace) -> None:
        assert upload(client, "fit", {"SKILL.md": SKILL}).json()["installed"] == [{"name": "fit", "left_out": 0}]

        body = upload(client, "fit", {"SKILL.md": SKILL.replace("Do it well.", "Changed.")}).json()

        assert body["installed"] == []
        assert body["skipped"] == [{"name": "fit", "reason": "you already have a skill with that name"}]
        assert "Do it well." in (workspace.skills_dir / "fit" / "SKILL.md").read_text()

    def test_a_skill_with_no_description_is_left_and_why_is_said(self, client: TestClient) -> None:
        body = upload(client, "fit", {"SKILL.md": "---\nname: fit\n---\n\nBody.\n"}).json()

        assert body["installed"] == []
        assert "no description" in body["skipped"][0]["reason"]

    def test_a_folder_with_no_skill_in_it_is_refused(self, client: TestClient, workspace: Workspace) -> None:
        response = upload(client, "notes", {"README.md": "Not a skill."})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "no_skills"
        assert "There is no skill in the folder notes" in response.json()["error"]["message"]
        assert not workspace.skills_dir.exists() or list(workspace.skills_dir.iterdir()) == []

    def test_what_a_repository_holds_that_a_skill_does_not_need_is_not_kept(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        files = {
            "SKILL.md": SKILL,
            ".git/config": "[core]",
            "node_modules/pkg/index.js": "x",
            "scripts/__pycache__/fit.pyc": b"x",
            ".DS_Store": b"x",
            "scripts/.DS_Store": b"x",
            "scripts/fit.py": "print('fit')",
        }

        assert upload(client, "fit", files).status_code == 200

        kept = workspace.skills_dir / "fit"
        found = sorted(path.relative_to(kept).as_posix() for path in kept.rglob("*") if path.is_file())
        assert found == ["SKILL.md", "scripts/fit.py"]

    @pytest.mark.parametrize(
        "path",
        [
            "../evil.md",
            "a/../../evil.md",
            "/etc/evil.md",
            "a\\evil.md",
            "a//evil.md",
            "./evil.md",
            "a/./evil.md",
            "",
            "a/",
        ],
    )
    def test_a_file_that_leads_out_of_the_folder_is_refused_and_nothing_is_kept(
        self, client: TestClient, workspace: Workspace, tmp_path: Path, path: str
    ) -> None:
        response = upload(client, "fit", {"SKILL.md": SKILL, path: "x"})

        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "invalid"
        assert not (workspace.skills_dir / "fit").exists()
        assert not list(tmp_path.rglob("evil.md"))

    def test_a_path_twice_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/api/skills/upload",
            data={"folder": "fit", "paths": ["SKILL.md", "SKILL.md"]},
            files=[("files", ("SKILL.md", SKILL)), ("files", ("SKILL.md", SKILL))],
        )

        assert response.status_code == 422
        assert "twice" in response.json()["error"]["message"]

    def test_a_file_that_is_also_a_folder_of_the_others_is_refused(self, client: TestClient) -> None:
        response = upload(client, "fit", {"SKILL.md": SKILL, "scripts": "x", "scripts/fit.py": "y"})

        assert response.status_code == 422, response.text
        assert "scripts/fit.py" in response.json()["error"]["message"]

    def test_a_file_without_a_path_or_a_path_without_a_file_is_refused(self, client: TestClient) -> None:
        missing_path = client.post("/api/skills/upload", data={"folder": "fit"}, files=[("files", ("SKILL.md", SKILL))])
        missing_file = client.post("/api/skills/upload", data={"folder": "fit", "paths": ["SKILL.md"]})
        not_a_file = client.post("/api/skills/upload", data={"folder": "fit", "paths": ["SKILL.md"], "files": [SKILL]})

        assert [response.status_code for response in (missing_path, missing_file, not_a_file)] == [422, 422, 422]
        assert "same order" in missing_path.json()["error"]["message"]

    def test_a_folder_with_no_name_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/api/skills/upload", data={"paths": ["SKILL.md"]}, files=[("files", ("SKILL.md", SKILL))]
        )

        assert response.status_code == 422
        assert "what the folder is called" in response.json()["error"]["message"]

    def test_too_many_files_are_refused(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server_skills, "MAX_COPIED_FILES", 3)

        response = upload(client, "fit", {"SKILL.md": SKILL, "a.txt": "a", "b.txt": "b", "c.txt": "c"})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "too_many_files"

    def test_a_folder_that_is_too_big_is_refused_and_nothing_is_kept(
        self, client: TestClient, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(server_skills, "MAX_COPIED_BYTES", 100)

        response = upload(client, "fit", {"SKILL.md": SKILL, "big.bin": b"x" * 200})

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "too_large"
        assert not (workspace.skills_dir / "fit").exists()

    def test_a_request_with_no_length_is_not_taken(self, client: TestClient, workspace: Workspace) -> None:
        body = b'--x\r\nContent-Disposition: form-data; name="folder"\r\n\r\nfit\r\n--x--\r\n'

        response = client.post(
            "/api/skills/upload",
            content=iter([body]),
            headers={"content-type": "multipart/form-data; boundary=x"},
        )

        assert response.status_code == 411, response.text
        assert response.json()["error"]["code"] == "length_required"

    def test_a_request_that_says_it_is_too_big_is_refused_before_it_is_read(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(app_module, "MAX_COPIED_BYTES", 100)
        monkeypatch.setattr(app_module, "UPLOAD_OVERHEAD_BYTES", 0)

        response = upload(client, "fit", {"SKILL.md": SKILL, "big.bin": b"x" * 200})

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "too_large"

    def test_more_parts_than_a_folder_may_have_are_refused_as_too_many_files(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(app_module, "MAX_COPIED_FILES", 2)

        # Files that are passed over are parts of the form too
        response = upload(client, "fit", {"SKILL.md": SKILL, "a/.git/x": "x", "b/.git/y": "y", "c/.git/z": "z"})

        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "too_many_files"

    def test_it_is_asked_with_the_token_as_the_other_routes_are(self, app: FastAPI) -> None:
        with TestClient(app, base_url=LOCAL) as anonymous:
            response = anonymous.post("/api/skills/upload", data={"folder": "fit"})

        assert response.status_code == 401


class TestCheckingWhatIsUploaded:
    @pytest.mark.parametrize("path", ["SKILL.md", "scripts/fit.py", "a/b/c/d.txt", "name with spaces.md", "é/ü.md"])
    def test_a_path_down_into_the_folder_is_kept(self, path: str) -> None:
        assert check_upload_path(path) is not None

    @pytest.mark.parametrize("path", [".git/config", "a/node_modules/b.js", ".DS_Store", "x/.DS_Store", "venv/lib.py"])
    def test_what_is_not_needed_is_passed_over(self, path: str) -> None:
        assert check_upload_path(path) is None

    def test_a_path_that_is_too_long_or_too_deep_or_not_text_is_refused(self) -> None:
        from virtual_lab.server.errors import ApiError

        for path in ["a/" * 20 + "b", "x" * 600, None, 3, "a\x00b"]:
            with pytest.raises(ApiError):
                check_upload_path(path)

    @pytest.mark.parametrize(
        ("given", "called"),
        [
            ("fit", "fit"),
            ("a/b/fit", "fit"),
            ("a\\b\\fit", "fit"),
            ("fit/", "fit"),
            ("..", "skill"),
            ("", "skill"),
            ("x" * 300, "x" * 100),
        ],
    )
    def test_a_folder_is_called_the_last_of_its_name(self, given: str, called: str) -> None:
        assert check_upload_folder(given) == called
