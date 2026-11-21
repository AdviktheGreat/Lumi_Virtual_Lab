"""Tests of watching what an agent is pinned to: asking where the code's ref is now, asking an index of the versions
that a lock pins, holding two versions of the code side by side as a bounded diff, and the one word for how an agent
is."""

import http.client
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from virtual_lab.paperagents import repository, watching

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="Git is not installed")


def git(folder: Path, *arguments: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *arguments],
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )

    return done.stdout.strip()


def commit(folder: Path, name: str, text: str) -> str:
    (folder / name).write_text(text)
    git(folder, "add", name)
    git(folder, "commit", "-q", "-m", name)

    return git(folder, "rev-parse", "HEAD")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    folder = tmp_path / "project"
    folder.mkdir()
    git(folder, "init", "-q", "-b", "main")

    return folder


def ask(project: Path, ref: str, at: str) -> watching.Probe:
    return watching.probe_source(str(project), ref, at, protocols="file")


@needs_git
class TestAskingWhereTheCodeIs:
    def test_a_ref_that_is_at_the_commit_that_was_fetched_has_not_moved(self, project: Path) -> None:
        first = commit(project, "a.py", "1")

        found = ask(project, "HEAD", first)

        assert (found.state, found.commit) == (watching.SAME, first)

    def test_a_ref_that_is_at_another_commit_has_moved_and_says_which(self, project: Path) -> None:
        first = commit(project, "a.py", "1")
        second = commit(project, "b.py", "2")

        found = ask(project, "main", first)

        assert (found.state, found.commit) == (watching.MOVED, second)
        assert first[:12] in found.message and second[:12] in found.message

    def test_a_tag_is_asked_of_by_the_commit_it_is_of(self, project: Path) -> None:
        first = commit(project, "a.py", "1")
        git(project, "tag", "-a", "-m", "v1", "v1")
        second = commit(project, "b.py", "2")

        assert ask(project, "v1", first).state == watching.SAME
        assert ask(project, "v1", second) == watching.Probe(
            watching.MOVED, first, f"'v1' is now at {first[:12]}, and the code that is kept is of {second[:12]}."
        )

    def test_a_ref_that_is_not_there_is_gone(self, project: Path) -> None:
        first = commit(project, "a.py", "1")

        found = ask(project, "removed-branch", first)

        assert found.state == watching.GONE and found.commit is None and "removed-branch" in found.message

    def test_a_commit_does_not_move_and_is_not_asked_of(self, project: Path) -> None:
        first = commit(project, "a.py", "1")

        found = watching.probe_source(str(project / "nowhere"), first, first, protocols="file")

        assert found.state == watching.PINNED and found.commit is None

    def test_a_project_that_cannot_be_reached_is_unknown_and_not_gone(self, tmp_path: Path) -> None:
        found = ask(tmp_path / "nothing-here", "HEAD", "a" * 40)

        assert found.state == watching.UNKNOWN and "could not be asked" in found.message

    def test_only_https_is_asked_by_unless_a_test_says_otherwise(self, project: Path) -> None:
        first = commit(project, "a.py", "1")

        found = watching.probe_source(str(project), "HEAD", first)

        assert found.state == watching.UNKNOWN

    @pytest.mark.parametrize(
        "said, state",
        [
            ("remote: Repository not found.\nfatal: repository 'https://github.com/a/b/' not found", watching.GONE),
            ("fatal: could not resolve host: github.com", watching.UNKNOWN),
            ("Git did not finish in 60 seconds", watching.UNKNOWN),
        ],
    )
    def test_what_git_says_of_a_project_that_is_gone_is_told_from_what_it_says_of_one_that_is_not_reached(
        self, monkeypatch: pytest.MonkeyPatch, said: str, state: str
    ) -> None:
        def fails(*arguments: Any, **options: Any) -> str:
            raise repository.RepositoryError(said)

        monkeypatch.setattr(watching, "run_git", fails)

        assert watching.probe_source("https://github.com/a/b", "HEAD", "a" * 40).state == state

    def test_it_is_not_asked_when_git_is_not_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda name, *rest, **options: None)

        found = watching.probe_source("https://github.com/a/b", "HEAD", "a" * 40)

        assert found.state == watching.UNKNOWN and "Git is not installed" in found.message

    def test_the_command_is_for_the_refs_it_names_and_what_comes_back_is_not_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[list[str]] = []

        def asks(arguments: list[str], *rest: Any, **options: Any) -> str:
            seen.append(arguments)
            return ""

        monkeypatch.setattr(watching, "run_git", asks)

        watching.probe_source("https://github.com/a/b", "v1.0", "a" * 40)
        watching.probe_source("https://github.com/a/b", "HEAD", "a" * 40)

        assert seen == [
            ["ls-remote", "--", "https://github.com/a/b", "refs/heads/v1.0", "refs/tags/v1.0", "refs/tags/v1.0^{}"],
            ["ls-remote", "--", "https://github.com/a/b", "HEAD"],
        ]

    @pytest.mark.parametrize(
        "ref, expected",
        [
            ("v1", "b" * 40),
            ("main", "c" * 40),
            ("light", "d" * 40),
            ("none", None),
            ("HEAD", "e" * 40),
        ],
    )
    def test_a_tag_is_of_the_commit_it_points_to_and_not_of_the_tag_object(
        self, ref: str, expected: str | None
    ) -> None:
        said = "\n".join(
            [
                f"{'a' * 40}\trefs/tags/v1",
                f"{'b' * 40}\trefs/tags/v1^{{}}",
                f"{'c' * 40}\trefs/heads/main",
                f"{'d' * 40}\trefs/tags/light",
                f"{'e' * 40}\tHEAD",
                "not a line",
                f"{'z' * 40}\trefs/heads/none",
            ]
        )

        assert watching.commit_of(said, ref) == expected

    def test_a_name_that_is_a_tag_and_a_branch_is_the_tag_as_git_takes_it(self) -> None:
        said = "\n".join(
            [
                f"{'1' * 40}\trefs/heads/v2",
                f"{'2' * 40}\trefs/tags/v2",
                f"{'3' * 40}\trefs/tags/v2^{{}}",
                f"{'4' * 40}\trefs/heads/dev",
                f"{'5' * 40}\trefs/tags/dev",
            ]
        )

        assert watching.commit_of(said, "v2") == "3" * 40
        assert watching.commit_of(said, "dev") == "5" * 40


class Answering:
    """Stands in for a connection to the index: what it was asked, and what it answers."""

    asked: list[tuple[str, str, dict[str, str]]]

    def __init__(self, status: int = 200, body: bytes = b"{}", error: BaseException | None = None) -> None:
        self.status = status
        self.body = body
        self.error = error
        self.asked = []
        self.closed = False
        self.host = ""

    def __call__(self, host: str, **options: Any) -> "Answering":
        self.host = host

        return self

    def request(self, method: str, path: str, headers: dict[str, str]) -> None:
        self.asked.append((method, path, headers))
        if self.error is not None:
            raise self.error

    def getresponse(self) -> "Answering":
        return self

    def read(self, amount: int) -> bytes:
        return self.body[:amount]

    def close(self) -> None:
        self.closed = True


def indexed(monkeypatch: pytest.MonkeyPatch, **options: Any) -> Answering:
    answer = Answering(**options)
    monkeypatch.setattr(http.client, "HTTPSConnection", answer)

    return answer


def files_of_index(*yanked: bool) -> bytes:
    return json.dumps({"urls": [{"yanked": one} for one in yanked]}).encode()


class TestAskingTheIndex:
    def test_a_version_that_is_there_is_found_and_only_one_host_is_asked_at_an_address_made_of_the_pin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        answer = indexed(monkeypatch, body=files_of_index(False, True))

        assert watching.Index().status("scikit-learn", "1.4.2") == watching.FOUND
        assert answer.host == "pypi.org" and answer.closed
        assert [(method, path) for method, path, _ in answer.asked] == [("GET", "/pypi/scikit-learn/1.4.2/json")]

    def test_a_version_all_of_whose_files_were_yanked_is_yanked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        indexed(monkeypatch, body=files_of_index(True, True))

        assert watching.Index().status("numpy", "1.0") == watching.YANKED

    @pytest.mark.parametrize(
        "options, expected",
        [
            ({"status": 404}, watching.MISSING),
            ({"body": files_of_index()}, watching.MISSING),
            ({"status": 500}, None),
            ({"body": b"not json"}, None),
            ({"body": b"[]"}, None),
            ({"body": b'{"urls": 3}'}, None),
            ({"body": b"[" * 100_000}, None),
            ({"error": OSError("no route")}, None),
            ({"error": http.client.HTTPException("bad")}, None),
            ({"body": b" " * (watching.MAX_INDEX_BYTES + 5)}, None),
        ],
    )
    def test_what_the_index_does_not_say_is_not_said(
        self, monkeypatch: pytest.MonkeyPatch, options: dict[str, Any], expected: str | None
    ) -> None:
        answer = indexed(monkeypatch, **options)

        assert watching.Index().status("numpy", "1.0") == expected
        assert answer.closed

    @pytest.mark.parametrize(
        "name, version", [("../x", "1"), ("a b", "1"), ("numpy", "1/../2"), ("numpy", ""), ("", "1")]
    )
    def test_a_name_or_a_version_that_is_not_one_is_not_asked_of(
        self, monkeypatch: pytest.MonkeyPatch, name: str, version: str
    ) -> None:
        answer = indexed(monkeypatch, body=files_of_index(False))

        assert watching.Index().status(name, version) is None
        assert answer.asked == []


class Asked(watching.Index):
    def __init__(self, says: dict[str, str | None]) -> None:
        self.says = says
        self.asked: list[str] = []

    def status(self, name: str, version: str) -> str | None:
        self.asked.append(f"{name}=={version}")

        return self.says.get(name, watching.FOUND)


class TestThePins:
    LOCK = "# a comment\nnumpy==1.26.4\nNumpy==1.26.4\nscipy==1.11.0 ; python_version > '3.8'\n-e .\nproject @ file:///x\npandas>=2\nnumpy==1.26.4\n"

    def test_the_pins_are_the_exact_versions_each_once(self) -> None:
        assert watching.pins_of(self.LOCK) == [("numpy", "1.26.4"), ("Numpy", "1.26.4"), ("scipy", "1.11.0")]

    def test_those_that_are_gone_or_yanked_are_told_and_those_that_are_not_said_of_are_counted(self) -> None:
        index = Asked({"numpy": watching.MISSING, "Numpy": watching.YANKED, "scipy": None})

        found = watching.look_at_pins(self.LOCK, index)

        assert found == {
            "total": 3,
            "looked_at": 3,
            "unsaid": 1,
            "problems": [
                {"name": "numpy", "version": "1.26.4", "state": "missing"},
                {"name": "Numpy", "version": "1.26.4", "state": "yanked"},
            ],
        }

    def test_no_more_are_asked_of_than_the_most_and_none_after_a_stop(self) -> None:
        lock = "".join(f"p{number}==1.0\n" for number in range(10))
        index = Asked({})

        found = watching.look_at_pins(lock, index, most=4)

        assert (found["total"], found["looked_at"], len(index.asked)) == (10, 4, 4)
        stopped = Asked({})
        assert watching.look_at_pins(lock, stopped, should_stop=lambda: True)["looked_at"] == 0 and stopped.asked == []

    def test_none_are_asked_of_after_the_time_is_out(self) -> None:
        index = Asked({})

        found = watching.look_at_pins("a==1\nb==1\n", index, seconds=-1)

        assert found["looked_at"] == 0 and index.asked == []


def tree(root: Path, files: dict[str, str | bytes]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())

    return root


class TestTheDifferenceOfTwoVersions:
    def test_what_was_added_taken_away_and_changed_is_told_with_the_lines(self, tmp_path: Path) -> None:
        old = tree(tmp_path / "old", {"same.py": "x\n", "gone.py": "a\nb\n", "edit.py": "a\nb\nc\n"})
        new = tree(tmp_path / "new", {"same.py": "x\n", "new.py": "1\n2\n", "edit.py": "a\nB\nc\nd\n"})

        found = watching.diff_trees(old, new)

        by_path = {entry["path"]: entry for entry in found["files"]}
        assert sorted(by_path) == ["edit.py", "gone.py", "new.py"]
        assert (found["changed"], found["added"], found["removed"]) == (3, 1, 1)
        assert by_path["edit.py"]["change"] == "changed" and (
            by_path["edit.py"]["added"],
            by_path["edit.py"]["removed"],
        ) == (2, 1)
        assert "-b" in by_path["edit.py"]["diff"] and "+B" in by_path["edit.py"]["diff"]
        assert by_path["gone.py"]["change"] == "removed" and by_path["gone.py"]["removed"] == 2
        assert by_path["new.py"]["change"] == "added" and by_path["new.py"]["added"] == 2
        assert found["truncated"] is False

    def test_the_same_files_are_no_difference(self, tmp_path: Path) -> None:
        old = tree(tmp_path / "old", {"a.py": "x", "d/b.py": "y"})
        new = tree(tmp_path / "new", {"a.py": "x", "d/b.py": "y"})

        assert watching.diff_trees(old, new) == {
            "changed": 0,
            "added": 0,
            "removed": 0,
            "files": [],
            "paths": [],
            "truncated": False,
        }

    def test_git_files_and_links_are_not_looked_at(self, tmp_path: Path) -> None:
        old = tree(tmp_path / "old", {"a.py": "x"})
        new = tree(tmp_path / "new", {"a.py": "x", ".git/config": "c"})
        (new / "link.py").symlink_to(tmp_path / "old" / "a.py")
        (new / "folder-link").symlink_to(tmp_path / "old")

        assert watching.diff_trees(old, new)["changed"] == 0

    def test_a_file_that_is_not_text_or_is_too_big_is_changed_and_not_read(self, tmp_path: Path) -> None:
        big = "x" * (watching.MAX_FILE_BYTES + 1)
        old = tree(tmp_path / "old", {"data.bin": b"\0\1", "big.txt": big, "ok.py": "a"})
        new = tree(tmp_path / "new", {"data.bin": b"\0\2", "big.txt": big + "y", "ok.py": "b"})

        by_path = {entry["path"]: entry for entry in watching.diff_trees(old, new)["files"]}

        assert by_path["data.bin"]["binary"] is True and by_path["data.bin"]["diff"] is None
        assert by_path["big.txt"]["binary"] is True and by_path["big.txt"]["diff"] is None
        assert by_path["ok.py"]["binary"] is False and "+b" in by_path["ok.py"]["diff"]

    def test_how_much_is_shown_is_bounded_by_file_by_count_and_in_all(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(watching, "MAX_ALL_DIFF", 10_000_000)
        old = tree(tmp_path / "old", {f"f{number:03}.py": "a\n" for number in range(60)})
        lines = "".join(f"line {n}\n" for n in range(2000))
        new = tree(tmp_path / "new", {f"f{number:03}.py": lines for number in range(60)})

        found = watching.diff_trees(old, new)

        shown = [entry for entry in found["files"] if entry["diff"] is not None]
        assert found["changed"] == 60 and len(found["files"]) == 60 and found["truncated"] is True
        assert len(shown) == watching.MOST_SHOWN and all(entry["cut"] for entry in shown)
        assert all(len(entry["diff"]) <= watching.MAX_FILE_DIFF for entry in shown)
        assert all(entry["added"] == 2000 for entry in found["files"])
        monkeypatch.setattr(watching, "MOST_LISTED", 5)
        listed = watching.diff_trees(old, new)
        assert len(listed["files"]) == 5 and listed["changed"] == 60 and listed["truncated"] is True
        assert len(listed["paths"]) == 60

    def test_a_diff_that_is_all_shown_is_not_said_to_be_cut(self, tmp_path: Path) -> None:
        old = tree(tmp_path / "old", {f"f{number}.py": "a\n" for number in range(3)})
        new = tree(tmp_path / "new", {f"f{number}.py": "b\n" for number in range(3)})

        found = watching.diff_trees(old, new)

        assert found["truncated"] is False and all(entry["cut"] is False for entry in found["files"])

    def test_the_total_that_is_shown_stops_at_the_most(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(watching, "MAX_ALL_DIFF", 700)
        monkeypatch.setattr(watching, "MAX_FILE_DIFF", 500)
        old = tree(tmp_path / "old", {f"f{number}.py": "a\n" for number in range(4)})
        new = tree(tmp_path / "new", {f"f{number}.py": "b\n" * 300 for number in range(4)})

        found = watching.diff_trees(old, new)

        shown = [len(entry["diff"]) for entry in found["files"] if entry["diff"] is not None]
        assert sum(shown) == 700 and shown[0] == 500 and shown[1] == 200


class TestWhichToolsAFileIsOf:
    TOOLS = [
        {"name": "map_cells", "repo": {"module": "cellmapper.mapping", "function": "map_cells"}},
        {"name": "pkg_tool", "repo": {"module": "cellmapper.pkg", "function": "f"}},
        {"name": "top", "repo": {"module": "top", "function": "f"}},
    ]

    @pytest.mark.parametrize(
        "paths, expected",
        [
            (["cellmapper/mapping.py"], ["map_cells"]),
            (["src/cellmapper/mapping.py"], ["map_cells"]),
            (["cellmapper/pkg/__init__.py"], ["pkg_tool"]),
            (["top.py"], ["top"]),
            (["notcellmapper/mapping.py", "cellmapper/mapping.txt", "README.md", "mytop.py"], []),
            (["cellmapper/mapping.py", "top.py"], ["map_cells", "top"]),
        ],
    )
    def test_a_tool_is_of_the_file_of_its_function_s_module(self, paths: list[str], expected: list[str]) -> None:
        assert watching.affected(self.TOOLS, paths) == expected

    def test_the_files_that_say_what_an_environment_is_are_known_by_name(self) -> None:
        paths = [
            "requirements.txt",
            "docs/requirements-dev.txt",
            "Environment.yml",
            "sub/pyproject.toml",
            "setup.py",
            "Dockerfile",
            "mapping.py",
            "requirements/base.in",
            "notrequirements.txt",
            "README.md",
        ]

        assert watching.environment_files(paths) == [
            "requirements.txt",
            "docs/requirements-dev.txt",
            "Environment.yml",
            "sub/pyproject.toml",
            "setup.py",
            "Dockerfile",
            "requirements/base.in",
        ]


def tool(name: str, calls: int, matched: int, message: str | None = None) -> dict[str, Any]:
    return {"name": name, "calls": calls, "matched": matched, "message": message}


SAME = {"state": watching.SAME, "message": "same"}
NO_PINS = {"total": 2, "looked_at": 2, "unsaid": 0, "problems": []}


class TestHowAnAgentIs:
    def test_one_whose_tools_all_gave_again_what_they_got_and_has_nothing_wrong_is_healthy(self) -> None:
        assert watching.health_of(SAME, True, NO_PINS, [tool("a", 2, 2), tool("b", 1, 1)], None) == (
            watching.HEALTHY,
            [],
        )

    def test_a_source_that_moved_and_pins_that_were_not_asked_of_do_not_make_it_less_so(self) -> None:
        moved = {"state": watching.MOVED, "message": "moved"}

        assert watching.health_of(moved, True, None, [tool("a", 1, 1)], None) == (watching.HEALTHY, [])

    def test_an_image_that_is_gone_is_broken_whatever_else_is_found(self) -> None:
        status, reasons = watching.health_of(SAME, False, NO_PINS, [tool("a", 1, 1)], None)

        assert status == watching.BROKEN and "not in Docker" in reasons[0] and len(reasons) == 1

    def test_an_image_that_could_not_be_asked_about_is_not_called_gone(self) -> None:
        status, reasons = watching.health_of(SAME, None, NO_PINS, None, "Docker is not running.")

        assert status == watching.UNCHECKED and reasons == ["Docker is not running."]

    def test_a_source_that_is_gone_is_degraded(self) -> None:
        status, reasons = watching.health_of(
            {"state": watching.GONE, "message": "It is not there."}, True, NO_PINS, [tool("a", 1, 1)], None
        )

        assert status == watching.DEGRADED and reasons == ["The source is gone: It is not there."]

    def test_a_pin_that_cannot_be_installed_again_is_degraded_and_is_named(self) -> None:
        pins = {**NO_PINS, "problems": [{"name": "numpy", "version": "1.0", "state": "yanked"}]}

        status, reasons = watching.health_of(SAME, True, pins, [tool("a", 1, 1)], None)

        assert (
            status == watching.DEGRADED
            and "numpy==1.0 (yanked)" in reasons[0]
            and reasons[0].startswith("1 pinned version ")
        )

    def test_a_tool_that_gave_something_else_is_degraded_and_all_of_them_is_broken(self) -> None:
        status, reasons = watching.health_of(
            SAME, True, NO_PINS, [tool("a", 2, 1, "it differs"), tool("b", 1, 1)], None
        )
        assert status == watching.DEGRADED and "a (1 of 2 calls): it differs" in reasons[0]

        status, reasons = watching.health_of(SAME, True, NO_PINS, [tool("a", 2, 0), tool("b", 1, 0)], None)
        assert status == watching.BROKEN and "No tool gave again" in reasons[0]

    def test_a_tool_with_no_recorded_call_has_not_been_held_to_anything_and_is_not_said_to_be_wrong(self) -> None:
        assert watching.health_of(SAME, True, NO_PINS, [tool("a", 0, 0), tool("b", 1, 1)], None)[0] == watching.HEALTHY

    def test_tools_none_of_which_has_a_call_to_run_again_leave_it_unchecked(self) -> None:
        status, reasons = watching.health_of(SAME, True, NO_PINS, [tool("a", 0, 0)], None)

        assert status == watching.UNCHECKED and reasons == ["No tool has a recorded call that could be run again."]

    def test_tools_that_were_not_run_leave_it_unchecked_unless_something_was_found_wrong(self) -> None:
        assert watching.health_of(SAME, True, NO_PINS, None, "Docker is not running.") == (
            watching.UNCHECKED,
            ["Docker is not running."],
        )
        assert watching.health_of(SAME, True, NO_PINS, None, None)[1] == ["The tools were not run."]
        pins = {**NO_PINS, "problems": [{"name": "numpy", "version": "1.0", "state": "missing"}]}
        assert watching.health_of(SAME, True, pins, None, "Docker is not running.")[0] == watching.DEGRADED

    def test_the_reasons_name_at_most_three_tools_and_five_pins(self) -> None:
        pins = {**NO_PINS, "problems": [{"name": f"p{n}", "version": "1", "state": "missing"} for n in range(9)]}
        tools = [tool(f"t{n}", 2, 1) for n in range(6)] + [tool("fine", 1, 1)]

        status, reasons = watching.health_of(SAME, True, pins, tools, None)

        assert (
            status == watching.DEGRADED
            and "9 pinned versions" in reasons[0]
            and "p4==1" in reasons[0]
            and "p5==1" not in reasons[0]
        )
        assert "t2 (" in reasons[1] and "t3 (" not in reasons[1]
