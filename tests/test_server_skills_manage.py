"""Tests of keeping skills from a page: listing them, turning them off for new conversations, putting in those of a Git
repository or a folder, and deleting them."""

import errno
import os
import shlex
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MODEL
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_server_app import BEARER, LOCAL, TOKEN
from test_skills import write_skill

from virtual_lab.server import skills as server_skills
from virtual_lab.server.app import create_app
from virtual_lab.server.config import resolve_config
from virtual_lab.server.skills import USER_SKILLS_DIR_VARIABLE, Skills, check_git_address, fetch_repository
from virtual_lab.server.workspace import Settings, Workspace


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
def app(workspace: Workspace) -> FastAPI:
    return create_app(workspace.root, token=TOKEN, check_keys=False)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


def names_of(listing: dict[str, Any]) -> list[str]:
    return [skill["name"] for skill in listing["skills"]]


def fake_git(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fetch: Callable[[Path], object] | None = None,
    returncode: int = 0,
    stderr: str = "",
    waits: int = 0,
    missing: bool = False,
) -> dict[str, Any]:
    """Stands in for the Git that fetches: it runs `fetch` on the folder the clone is to go in, takes `waits` looks at
    it before it is done (-1 is for ever), and then ends as it is said to. What it was started with, and how many
    times it was stopped, are in what is returned."""
    seen: dict[str, Any] = {"stopped": 0}

    class Process:
        pid = 0

        def __init__(self, command: list[str], **options: Any) -> None:
            if missing:
                raise FileNotFoundError("git")
            seen.update(command=command, **options)
            self.returncode: int | None = None
            self.waited = 0
            if fetch is not None:
                fetch(Path(command[-1]))

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            if waits < 0 or self.waited < waits:
                self.waited += 1
                raise subprocess.TimeoutExpired("git", timeout or 0)
            self.returncode = returncode
            return "", stderr

        def poll(self) -> int | None:
            return self.returncode

    def stop(process: Process) -> None:
        seen["stopped"] += 1
        process.returncode = -9

    monkeypatch.setattr(server_skills.subprocess, "Popen", Process)
    monkeypatch.setattr(server_skills, "stop_git", stop)

    return seen


class TestListing:
    def test_each_skill_says_what_it_is_where_it_is_and_whether_it_is_on_and_can_be_deleted(
        self, client: TestClient, workspace: Workspace, user_skills: Path
    ) -> None:
        write_skill(workspace.skills_dir, name="mine", extra="license: MIT\n")
        write_skill(user_skills, name="shared")

        listing = client.get("/api/skills").json()

        mine, shared = listing["skills"]
        assert (mine["name"], mine["source"], mine["license"], mine["enabled"], mine["removable"]) == (
            "mine",
            "workspace",
            "MIT",
            True,
            True,
        )
        assert (shared["name"], shared["source"], shared["enabled"], shared["removable"]) == (
            "shared",
            "user",
            True,
            False,
        )
        assert mine["directory"] == str(workspace.skills_dir / "mine")
        assert listing["folders"] == [
            {"source": "workspace", "path": str(workspace.skills_dir), "exists": True},
            {"source": "user", "path": str(user_skills), "exists": True},
        ]

    def test_there_are_none_to_list_before_any_is_put_in(
        self, client: TestClient, workspace: Workspace, user_skills: Path
    ) -> None:
        listing = client.get("/api/skills").json()

        assert listing["skills"] == [] and listing["problems"] == []
        assert [folder["exists"] for folder in listing["folders"]] == [False, False]

    def test_a_skill_that_cannot_be_used_is_listed_as_a_problem(self, client: TestClient, workspace: Workspace) -> None:
        write_skill(workspace.skills_dir, name="good")
        (workspace.skills_dir / "broken").mkdir()
        (workspace.skills_dir / "broken" / "SKILL.md").write_text("No fields.")

        listing = client.get("/api/skills").json()

        assert names_of(listing) == ["good"]
        (problem,) = listing["problems"]
        assert problem["path"] == str(workspace.skills_dir / "broken" / "SKILL.md") and "YAML" in problem["message"]

    def test_a_skill_the_workspace_has_hides_one_of_the_persons_with_its_name_and_is_deleted_alone(
        self, client: TestClient, workspace: Workspace, user_skills: Path
    ) -> None:
        write_skill(workspace.skills_dir, name="shared", description="The workspace's.")
        write_skill(user_skills, name="shared", description="The person's.")

        (skill,) = client.get("/api/skills").json()["skills"]

        assert (skill["description"], skill["removable"]) == ("The workspace's.", True)


class TestTurningThemOff:
    def test_a_skill_turned_off_is_not_given_to_a_new_conversation_unless_it_is_asked_for(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        write_skill(workspace.skills_dir, name="alpha")
        write_skill(workspace.skills_dir, name="beta")

        listing = client.put("/api/skills", json={"disabled": ["alpha"]}).json()

        assert [(skill["name"], skill["enabled"]) for skill in listing["skills"]] == [("alpha", False), ("beta", True)]
        assert client.get("/api/skills").json() == listing
        settings = workspace.load_settings()
        assert resolve_config({}, settings, workspace).skills == ("beta",)
        assert resolve_config({"skills": ["alpha"]}, settings, workspace).skills == ("alpha",)

    def test_all_can_be_turned_on_again(self, client: TestClient, workspace: Workspace) -> None:
        write_skill(workspace.skills_dir, name="alpha")
        client.put("/api/skills", json={"disabled": ["alpha"]})

        listing = client.put("/api/skills", json={"disabled": []}).json()

        assert listing["skills"][0]["enabled"] is True
        assert resolve_config({}, workspace.load_settings(), workspace).skills == ("alpha",)

    def test_a_skill_that_is_not_there_cannot_be_turned_off(self, client: TestClient, workspace: Workspace) -> None:
        write_skill(workspace.skills_dir, name="alpha")

        response = client.put("/api/skills", json={"disabled": ["alpha", "gone"]})

        assert response.status_code == 422 and "no skill called 'gone'" in response.json()["error"]["message"]
        assert workspace.load_disabled_skills() == []

    def test_a_skill_that_is_missing_stays_turned_off_for_when_it_is_back(
        self, client: TestClient, workspace: Workspace, user_skills: Path
    ) -> None:
        write_skill(workspace.skills_dir, name="alpha")
        write_skill(user_skills, name="beta")
        client.put("/api/skills", json={"disabled": ["beta"]})
        (user_skills / "beta" / "SKILL.md").rename(user_skills / "beta" / "OLD.md")

        client.put("/api/skills", json={"disabled": ["alpha"]})

        assert sorted(workspace.load_disabled_skills()) == ["alpha", "beta"]
        (user_skills / "beta" / "OLD.md").rename(user_skills / "beta" / "SKILL.md")
        assert [(skill["name"], skill["enabled"]) for skill in client.get("/api/skills").json()["skills"]] == [
            ("alpha", False),
            ("beta", False),
        ]

    def test_a_file_that_is_not_what_it_should_be_leaves_none_turned_off(self, workspace: Workspace) -> None:
        workspace.skills_path.write_text('{"disabled": "alpha"}')

        assert workspace.load_disabled_skills() == []
        workspace.skills_path.write_text("not json")
        assert workspace.load_disabled_skills() == []
        workspace.skills_path.write_text('{"disabled": ["alpha", 3, null]}')
        assert workspace.load_disabled_skills() == ["alpha"]

    def test_the_names_are_a_list_of_text(self, client: TestClient) -> None:
        assert client.put("/api/skills", json={"disabled": "alpha"}).status_code == 422
        assert client.put("/api/skills", json={"disabled": [1]}).status_code == 422


class TestPuttingInAFolder:
    def test_a_folder_that_is_a_skill_is_copied_into_the_workspace(
        self, client: TestClient, workspace: Workspace, tmp_path: Path
    ) -> None:
        source = write_skill(tmp_path / "elsewhere", name="fit", files={"scripts/fit.py": "print('fit')"})

        response = client.post("/api/skills/install", json={"path": str(source)})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["installed"] == [{"name": "fit", "left_out": 0}] and body["skipped"] == []
        assert names_of(body) == ["fit"] and body["skills"][0]["removable"] is True
        assert (workspace.skills_dir / "fit" / "scripts" / "fit.py").read_text() == "print('fit')"
        assert (source / "SKILL.md").is_file()

    def test_a_folder_of_skills_is_searched_for_them_and_those_whose_names_are_taken_are_left(
        self, client: TestClient, workspace: Workspace, tmp_path: Path
    ) -> None:
        write_skill(workspace.skills_dir, name="taken", description="Already here.")
        source = tmp_path / "repository"
        write_skill(source / "skills", name="taken", description="From the repository.")
        write_skill(source / "skills", name="new-one")
        write_skill(source / "more", name="Taken", folder="upper")
        broken = source / "skills" / "broken"
        broken.mkdir()
        (broken / "SKILL.md").write_text("No fields.")

        body = client.post("/api/skills/install", json={"path": str(source)}).json()

        assert [item["name"] for item in body["installed"]] == ["new-one"]
        reasons = {item["name"]: item["reason"] for item in body["skipped"]}
        assert reasons["taken"] == "you already have a skill with that name"
        assert reasons["Taken"] == "you already have a skill with that name"
        assert "YAML" in reasons["broken"]
        assert sorted(path.name for path in workspace.skills_dir.iterdir()) == ["new-one", "taken"]
        assert {skill["name"]: skill["description"] for skill in body["skills"]}["taken"] == "Already here."

    def test_a_tilde_stands_for_the_home_folder(
        self, client: TestClient, workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        write_skill(tmp_path / "home" / "mine", name="fit")

        body = client.post("/api/skills/install", json={"path": "~/mine"}).json()

        assert [item["name"] for item in body["installed"]] == ["fit"]

    def test_links_in_a_skill_are_not_copied(self, client: TestClient, workspace: Workspace, tmp_path: Path) -> None:
        secret = tmp_path / "secret.txt"
        secret.write_text("private")
        source = write_skill(tmp_path / "elsewhere", name="fit", files={".git/config": "x"})
        (source / "leak.txt").symlink_to(secret)

        client.post("/api/skills/install", json={"path": str(source)})

        assert sorted(path.name for path in (workspace.skills_dir / "fit").iterdir()) == ["SKILL.md"]

    def test_a_skill_that_is_a_link_to_a_file_outside_it_is_left(
        self, client: TestClient, workspace: Workspace, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside.md"
        outside.write_text("---\nname: leak\ndescription: Not in the folder.\n---\nsecret")
        source = tmp_path / "elsewhere" / "leak"
        source.mkdir(parents=True)
        (source / "SKILL.md").symlink_to(outside)

        body = client.post("/api/skills/install", json={"path": str(source.parent)}).json()

        assert body["installed"] == [] and "outside its folder" in body["skipped"][0]["reason"]
        assert not workspace.skills_dir.exists()

    def test_files_that_are_too_many_to_copy_are_counted(
        self, client: TestClient, workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("virtual_lab.skills.MAX_COPIED_FILES", 2)
        source = write_skill(tmp_path / "elsewhere", name="fit", files={f"d{n}.csv": "1" for n in range(5)})

        body = client.post("/api/skills/install", json={"path": str(source)}).json()

        assert body["installed"] == [{"name": "fit", "left_out": 4}]

    def test_a_skill_whose_instructions_are_a_link_to_a_file_in_it_is_copied_with_them(
        self, client: TestClient, workspace: Workspace, tmp_path: Path
    ) -> None:
        source = write_skill(tmp_path / "elsewhere", name="fit", files={"real.md": "kept"})
        (source / "SKILL.md").rename(source / "text.md")
        (source / "SKILL.md").symlink_to("text.md")

        body = client.post("/api/skills/install", json={"path": str(source)}).json()

        assert [item["name"] for item in body["installed"]] == ["fit"]
        copy = workspace.skills_dir / "fit"
        assert (copy / "SKILL.md").is_file() and not (copy / "SKILL.md").is_symlink()
        assert "name: fit" in (copy / "SKILL.md").read_text()
        assert names_of(client.get("/api/skills").json()) == ["fit"]

    def test_the_instructions_are_copied_however_many_files_there_are(
        self, client: TestClient, workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("virtual_lab.skills.MAX_COPIED_FILES", 1)
        source = write_skill(tmp_path / "elsewhere", name="fit", files={"AAA.md": "a", "BBB.md": "b"})

        body = client.post("/api/skills/install", json={"path": str(source)}).json()

        assert body["installed"] == [{"name": "fit", "left_out": 2}]
        assert (workspace.skills_dir / "fit" / "SKILL.md").is_file()

    def test_a_skill_that_cannot_be_copied_is_left_and_the_rest_are_put_in(
        self, client: TestClient, workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_skill(tmp_path / "elsewhere", name="bad", files={"a.txt": "x"})
        write_skill(tmp_path / "elsewhere", name="good")
        copy = shutil.copy2

        def refuse_bad(source: Any, destination: Any, **options: Any) -> Any:
            if "bad" in Path(source).parts:
                raise OSError(errno.ENOSPC, "No space left on device")
            return copy(source, destination, **options)

        monkeypatch.setattr("virtual_lab.skills.shutil.copy2", refuse_bad)

        body = client.post("/api/skills/install", json={"path": str(tmp_path / "elsewhere")}).json()

        assert [item["name"] for item in body["installed"]] == ["good"]
        assert body["skipped"] == [{"name": "bad", "reason": "it could not be copied: No space left on device"}]
        assert sorted(path.name for path in workspace.skills_dir.iterdir()) == ["good"], "A half copy was left"

    def test_the_skills_in_the_persons_own_folder_count_toward_the_most_there_can_be(
        self,
        client: TestClient,
        workspace: Workspace,
        user_skills: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("virtual_lab.skills.MAX_SKILLS", 2)
        monkeypatch.setattr(server_skills, "MAX_SKILLS", 2)
        write_skill(user_skills, name="shared")
        write_skill(tmp_path / "elsewhere", name="first")
        write_skill(tmp_path / "elsewhere", name="second")

        body = client.post("/api/skills/install", json={"path": str(tmp_path / "elsewhere")}).json()

        assert [item["name"] for item in body["installed"]] == ["first"]
        assert body["skipped"] == [{"name": "second", "reason": "only 2 skills are used"}]
        assert sorted(names_of(body)) == ["first", "shared"]

    def test_a_name_a_skill_of_the_persons_own_has_is_put_in_without_being_counted_again(
        self,
        client: TestClient,
        workspace: Workspace,
        user_skills: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("virtual_lab.skills.MAX_SKILLS", 1)
        monkeypatch.setattr(server_skills, "MAX_SKILLS", 1)
        write_skill(user_skills, name="shared", description="Theirs.")
        write_skill(tmp_path / "elsewhere", name="shared", description="Copied.")

        body = client.post("/api/skills/install", json={"path": str(tmp_path / "elsewhere")}).json()

        assert [item["name"] for item in body["installed"]] == ["shared"]
        assert {skill["name"]: skill["description"] for skill in body["skills"]} == {"shared": "Copied."}

    def test_a_folder_with_too_many_folders_in_it_is_not_searched_all_the_way(
        self, client: TestClient, workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(server_skills, "MAX_SEARCHED_FOLDERS", 5)
        for number in range(10):
            (tmp_path / "wide" / f"folder-{number:02d}").mkdir(parents=True)
        write_skill(tmp_path / "wide", name="zzz-last")

        response = client.post("/api/skills/install", json={"path": str(tmp_path / "wide")})

        assert response.status_code == 422 and response.json()["error"]["code"] == "too_many_folders"
        assert not workspace.skills_dir.exists()

    def test_a_link_back_to_a_folder_does_not_make_the_search_go_on_for_ever(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        root = tmp_path / "loop"
        (root / "a").mkdir(parents=True)
        (root / "a" / "back").symlink_to(root, target_is_directory=True)
        write_skill(root, name="fit")

        body = client.post("/api/skills/install", json={"path": str(root)}).json()

        assert [item["name"] for item in body["installed"]] == ["fit"]

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ({}, "not both"),
            ({"path": "/a", "git": "https://example.org/r.git"}, "not both"),
            ({"path": "relative/folder"}, "full path"),
            ({"path": ""}, "full path"),
            ({"path": "/this/folder/is/not/there"}, "There is no folder"),
        ],
    )
    def test_what_cannot_be_put_in_from_is_refused(
        self, client: TestClient, body: dict[str, str], message: str
    ) -> None:
        response = client.post("/api/skills/install", json=body)

        assert response.status_code == 422 and message in response.json()["error"]["message"]

    def test_a_folder_with_no_skill_in_it_is_refused(self, client: TestClient, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        (tmp_path / "empty" / "README.md").write_text("Nothing.")

        response = client.post("/api/skills/install", json={"path": str(tmp_path / "empty")})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "no_skills"

    def test_a_file_is_not_a_folder(self, client: TestClient, tmp_path: Path) -> None:
        (tmp_path / "file.md").write_text("x")

        response = client.post("/api/skills/install", json={"path": str(tmp_path / "file.md")})

        assert response.status_code == 422 and "There is no folder" in response.json()["error"]["message"]

    def test_what_is_put_in_is_given_to_new_conversations(
        self, client: TestClient, workspace: Workspace, tmp_path: Path
    ) -> None:
        client.post("/api/skills/install", json={"path": str(write_skill(tmp_path / "x", name="fit"))})

        assert resolve_config({}, workspace.load_settings(), workspace).skills == ("fit",)


class TestPuttingInARepository:
    @pytest.mark.parametrize(
        "address",
        [
            "http://example.org/skills.git",
            "git://example.org/skills.git",
            "ssh://git@example.org/skills.git",
            "git@github.com:owner/skills.git",
            "file:///etc",
            "/home/me/skills",
            "ext::sh -c touch% /tmp/pwned",
            "-uhttps://example.org",
            "https://",
            "https:///skills.git",
            "https://example.org/a b",
            "https://[::1/skills.git",
            "",
        ],
    )
    def test_only_the_address_of_a_repository_over_https_is_fetched(self, address: str) -> None:
        with pytest.raises(Exception, match="https://"):
            check_git_address(address)

    def test_an_address_with_a_name_or_a_password_in_it_is_refused(self) -> None:
        with pytest.raises(Exception, match="name or a password"):
            check_git_address("https://me:secret@example.org/skills.git")
        with pytest.raises(Exception, match="name or a password"):
            check_git_address("https://token@example.org/skills.git")

    def test_a_good_address_is_kept_as_it_is_without_the_spaces_round_it(self) -> None:
        assert check_git_address("  https://github.com/owner/skills.git\n") == "https://github.com/owner/skills.git"

    def test_the_repository_is_fetched_without_its_history_and_with_nothing_that_asks_or_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = fake_git(monkeypatch, fetch=lambda destination: write_skill(destination, name="fetched"))

        destination = fetch_repository("https://example.org/skills.git", tmp_path)

        assert (destination / "fetched" / "SKILL.md").is_file()
        command = seen["command"]
        assert command[0] == "git" and "--depth" in command and "--" in command
        assert command[command.index("--") + 1] == "https://example.org/skills.git"
        assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0" and seen["env"]["GIT_ALLOW_PROTOCOL"] == "https"
        assert seen["stdin"] == subprocess.DEVNULL
        assert seen["start_new_session"] is True, (
            "Git is not in a group of its own, so what it starts cannot be stopped"
        )
        assert seen["stopped"] == 0

    def test_a_fetch_that_is_slow_but_within_its_time_and_size_is_waited_for(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(server_skills, "GIT_WATCH_SECONDS", 0.01)
        seen = fake_git(monkeypatch, fetch=lambda destination: write_skill(destination, name="slow"), waits=3)

        destination = fetch_repository("https://example.org/skills.git", tmp_path)

        assert (destination / "slow" / "SKILL.md").is_file() and seen["stopped"] == 0

    @pytest.mark.parametrize(
        ("git", "status", "code", "message"),
        [
            ({"missing": True}, 422, "git_missing", "Git is not installed"),
            ({"waits": -1}, 504, "timeout", "did not finish"),
            ({"returncode": 128, "stderr": "fatal: repository not found\n"}, 422, "fetch_failed", "not found"),
            ({"returncode": 1}, 422, "fetch_failed", "status 1"),
        ],
    )
    def test_a_repository_that_cannot_be_fetched_is_said_why(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        git: dict[str, Any],
        status: int,
        code: str,
        message: str,
    ) -> None:
        monkeypatch.setattr(server_skills, "GIT_SECONDS", 0)
        seen = fake_git(monkeypatch, **git)

        response = client.post("/api/skills/install", json={"git": "https://example.org/skills.git"})

        assert response.status_code == status
        assert response.json()["error"]["code"] == code and message in response.json()["error"]["message"]
        assert seen["stopped"] == (1 if code == "timeout" else 0)

    def test_a_fetch_that_fills_the_disk_is_stopped(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server_skills, "GIT_BYTES", 10)
        monkeypatch.setattr(server_skills, "GIT_WATCH_SECONDS", 0.01)

        def fill(destination: Path) -> None:
            destination.mkdir(parents=True)
            (destination / "big.bin").write_bytes(b"x" * 100)

        seen = fake_git(monkeypatch, fetch=fill, waits=-1)

        response = client.post("/api/skills/install", json={"git": "https://example.org/skills.git"})

        assert response.status_code == 422 and response.json()["error"]["code"] == "too_big"
        assert seen["stopped"] == 1

    @pytest.mark.skipif(os.name != "posix", reason="Git is stopped as a group of processes where there are such")
    def test_stopping_git_stops_what_it_started_too(self, tmp_path: Path) -> None:
        marker = tmp_path / "child.pid"
        process = subprocess.Popen(
            ["sh", "-c", f"sleep 60 & echo $! > {shlex.quote(str(marker))}; wait"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        for _ in range(200):
            if marker.exists() and marker.read_text().strip():
                break
            time.sleep(0.05)
        child = int(marker.read_text())
        try:
            server_skills.stop_git(process)
            for _ in range(200):
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                pytest.fail("What Git started was left running")
            assert process.poll() is not None
        finally:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_the_skills_of_a_repository_are_put_in_and_what_was_fetched_is_not_kept(
        self, client: TestClient, workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scratch: list[Path] = []

        def fetch(destination: Path) -> None:
            scratch.append(destination.parent)
            write_skill(destination / "skills", name="one")
            write_skill(destination / "skills", name="two")
            (destination / ".git").mkdir()
            (destination / ".git" / "config").write_text("x")

        fake_git(monkeypatch, fetch=fetch)

        body = client.post("/api/skills/install", json={"git": "https://example.org/skills.git"}).json()

        assert [item["name"] for item in body["installed"]] == ["one", "two"]
        assert sorted(path.name for path in workspace.skills_dir.iterdir()) == ["one", "two"]
        assert not scratch[0].exists()

    def test_the_skills_are_not_held_up_while_a_repository_is_being_fetched(
        self, client: TestClient, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_skill(workspace.skills_dir, name="mine")
        outcome: dict[str, Any] = {}

        def fetch(destination: Path) -> None:
            write_skill(destination, name="fetched")

            def meanwhile() -> None:
                outcome["turned_off"] = client.put("/api/skills", json={"disabled": ["mine"]}).status_code

            thread = threading.Thread(target=meanwhile)
            thread.start()
            thread.join(timeout=10)
            outcome["finished"] = not thread.is_alive()

        fake_git(monkeypatch, fetch=fetch)

        body = client.post("/api/skills/install", json={"git": "https://example.org/skills.git"}).json()

        assert outcome == {"turned_off": 200, "finished": True}
        assert [item["name"] for item in body["installed"]] == ["fetched"]

    def test_a_refused_address_runs_nothing(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        def fail(*args: Any, **options: Any) -> None:
            raise AssertionError("Git was run")

        monkeypatch.setattr(server_skills.subprocess, "Popen", fail)

        response = client.post("/api/skills/install", json={"git": "ext::sh -c id"})

        assert response.status_code == 422


class TestDeleting:
    def test_a_skill_in_the_workspace_is_deleted_with_its_files(self, client: TestClient, workspace: Workspace) -> None:
        write_skill(workspace.skills_dir, name="alpha", files={"scripts/a.py": "x"})
        write_skill(workspace.skills_dir, name="beta")

        listing = client.delete("/api/skills/alpha").json()

        assert names_of(listing) == ["beta"]
        assert not (workspace.skills_dir / "alpha").exists() and (workspace.skills_dir / "beta").is_dir()

    def test_it_is_not_left_turned_off_for_when_one_of_its_name_is_put_in(
        self, client: TestClient, workspace: Workspace, tmp_path: Path
    ) -> None:
        write_skill(workspace.skills_dir, name="alpha")
        client.put("/api/skills", json={"disabled": ["alpha"]})

        client.delete("/api/skills/alpha")
        body = client.post("/api/skills/install", json={"path": str(write_skill(tmp_path / "x", name="alpha"))}).json()

        assert body["skills"][0]["enabled"] is True

    def test_what_the_one_deleted_hid_is_as_it_was_turned_on_or_off(
        self, client: TestClient, workspace: Workspace, user_skills: Path
    ) -> None:
        write_skill(workspace.skills_dir, name="both", description="In the workspace.")
        write_skill(user_skills, name="both", description="In the person's own folder.")
        client.put("/api/skills", json={"disabled": ["both"]})

        body = client.delete("/api/skills/both").json()

        assert [(skill["description"], skill["enabled"]) for skill in body["skills"]] == [
            ("In the person's own folder.", False)
        ]
        assert workspace.load_disabled_skills() == ["both"]

    def test_a_skill_in_the_persons_own_folder_is_not_deleted_from_here(
        self, client: TestClient, user_skills: Path
    ) -> None:
        write_skill(user_skills, name="shared")

        response = client.delete("/api/skills/shared")

        assert response.status_code == 409 and response.json()["error"]["code"] == "not_yours"
        assert (user_skills / "shared" / "SKILL.md").is_file()

    def test_a_skill_that_is_not_there_is_not_found(self, client: TestClient) -> None:
        assert client.delete("/api/skills/gone").status_code == 404
        assert client.get("/api/skills/gone").status_code == 404

    def test_a_skill_in_a_repository_put_in_whole_is_deleted_without_the_rest(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        write_skill(workspace.skills_dir / "repository" / "skills", name="one")
        write_skill(workspace.skills_dir / "repository" / "skills", name="two")

        client.delete("/api/skills/one")

        assert not (workspace.skills_dir / "repository" / "skills" / "one").exists()
        assert (workspace.skills_dir / "repository" / "skills" / "two" / "SKILL.md").is_file()

    def test_a_link_to_a_skill_is_removed_and_what_it_led_to_is_not(
        self, client: TestClient, workspace: Workspace, tmp_path: Path
    ) -> None:
        kept = write_skill(tmp_path / "elsewhere", name="linked")
        workspace.skills_dir.mkdir(parents=True)
        (workspace.skills_dir / "linked").symlink_to(kept, target_is_directory=True)

        (skill,) = client.get("/api/skills").json()["skills"]
        listing = client.delete("/api/skills/linked").json()

        assert skill["removable"] is True and listing["skills"] == []
        assert not (workspace.skills_dir / "linked").exists() and (kept / "SKILL.md").is_file()

    def test_the_folder_that_is_a_skill_itself_is_not_deleted(self, client: TestClient, workspace: Workspace) -> None:
        write_skill(workspace.root, name="itself", folder="skills")

        (skill,) = client.get("/api/skills").json()["skills"]
        response = client.delete("/api/skills/itself")

        assert skill["removable"] is False and response.status_code == 409
        assert (workspace.skills_dir / "SKILL.md").is_file()

    def test_a_skill_that_cannot_be_deleted_is_said_so(
        self, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_skill(workspace.skills_dir, name="alpha")

        def refuse(path: Path) -> None:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(server_skills.shutil, "rmtree", refuse)

        with pytest.raises(Exception, match="could not be deleted: Permission denied"):
            Skills(workspace).remove("alpha")


class TestPreview:
    def test_it_gives_the_instructions_without_the_fields_and_the_files(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        write_skill(
            workspace.skills_dir,
            name="alpha",
            body="# Alpha\n\nDo the thing.\n",
            files={"scripts/a.py": "x", "references/r.md": "y"},
        )

        preview = client.get("/api/skills/alpha").json()

        assert preview == {
            "name": "alpha",
            "instructions": "# Alpha\n\nDo the thing.",
            "characters": 22,
            "files": ["references/r.md", "scripts/a.py"],
            "more_files": 0,
        }

    def test_long_instructions_are_cut_and_say_how_long_they_are(
        self, client: TestClient, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(server_skills, "PREVIEW_CHARS", 10)
        write_skill(workspace.skills_dir, name="alpha", body="0123456789" * 5)

        preview = client.get("/api/skills/alpha").json()

        assert preview["instructions"] == "0123456789" and preview["characters"] == 50

    def test_the_skill_may_be_one_of_the_persons_own(self, client: TestClient, user_skills: Path) -> None:
        write_skill(user_skills, name="shared")

        assert client.get("/api/skills/shared").status_code == 200

    def test_a_skill_that_can_no_longer_be_read_is_no_longer_found(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        directory = write_skill(workspace.skills_dir, name="alpha")
        assert names_of(client.get("/api/skills").json()) == ["alpha"]
        (directory / "SKILL.md").write_bytes(b"\xff\xfe")

        assert client.get("/api/skills/alpha").status_code == 404
        assert names_of(client.get("/api/skills").json()) == []


class TestWhoMayAsk:
    @pytest.mark.parametrize(
        ("method", "path"),
        [("GET", "/api/skills"), ("PUT", "/api/skills"), ("POST", "/api/skills/install"), ("DELETE", "/api/skills/a")],
    )
    def test_nothing_is_done_without_the_token(self, app: FastAPI, method: str, path: str) -> None:
        with TestClient(app, base_url=LOCAL) as anonymous:
            assert anonymous.request(method, path, json={}).status_code == 401
