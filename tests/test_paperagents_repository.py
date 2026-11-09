"""Tests of fetching the code of a paper: that it is pinned to one commit, that nothing in it is run, that what Git is
given and what it is run with are the safe ones, and that it is refused when it is too big, takes too long, or is
stopped. They use Git itself on projects made in a folder, fetched by `file`, which a test allows and the code does not
(it fetches by https only)."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from virtual_lab.environment import StoppedError
from virtual_lab.paperagents import repository as cloning
from virtual_lab.paperagents.repository import RepositoryError, RepositoryTooBigError, check_ref, clone

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="Git is not installed")

AUTHOR = {
    "GIT_AUTHOR_NAME": "A. Author",
    "GIT_AUTHOR_EMAIL": "author@example.org",
    "GIT_COMMITTER_NAME": "A. Author",
    "GIT_COMMITTER_EMAIL": "author@example.org",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(folder: Path, *arguments: str) -> str:
    done = subprocess.run(
        ["git", *arguments], cwd=folder, env={**os.environ, **AUTHOR}, capture_output=True, text=True, check=True
    )

    return done.stdout.strip()


def make_project(folder: Path, files: dict[str, str | bytes] | None = None) -> Path:
    """A project with one commit, in a folder, with these files."""
    folder.mkdir(parents=True)
    git(folder, "init", "--quiet", "-b", "main")
    for name, content in (files or {"README.md": "# A project\n", "analysis.py": "print(1)\n"}).items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
    git(folder, "add", "--all")
    git(folder, "commit", "--quiet", "-m", "first")

    return folder


def fetch(source: Path, destination: Path, **options: object) -> cloning.Cloned:
    return clone(f"file://{source}", destination, protocols="file", **options)  # type: ignore[arg-type]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return make_project(tmp_path / "project")


class TestFetching:
    def test_fetches_the_files_at_the_commit_and_says_which(self, project: Path, tmp_path: Path) -> None:
        got = fetch(project, tmp_path / "out")

        assert got.commit == git(project, "rev-parse", "HEAD")
        assert got.ref == "HEAD"
        assert (tmp_path / "out" / "analysis.py").read_text() == "print(1)\n"

    def test_leaves_no_git_files_so_that_nothing_later_is_run_in_a_folder_git_acts_on(
        self, project: Path, tmp_path: Path
    ) -> None:
        fetch(project, tmp_path / "out")

        assert not (tmp_path / "out" / ".git").exists()

    def test_fetches_a_tag_and_a_commit_and_not_the_branch_head(self, project: Path, tmp_path: Path) -> None:
        first = git(project, "rev-parse", "HEAD")
        git(project, "tag", "v1")
        (project / "analysis.py").write_text("print(2)\n")
        git(project, "commit", "--quiet", "-am", "second")

        tagged = fetch(project, tmp_path / "tag", ref="v1")
        pinned = fetch(project, tmp_path / "commit", ref=first)
        latest = fetch(project, tmp_path / "latest")

        assert tagged.commit == pinned.commit == first
        assert (tmp_path / "tag" / "analysis.py").read_text() == "print(1)\n"
        assert (tmp_path / "commit" / "analysis.py").read_text() == "print(1)\n"
        assert latest.commit == git(project, "rev-parse", "HEAD") != first
        assert (tagged.ref, pinned.ref) == ("v1", first)

    def test_a_ref_that_is_not_there_is_said_not_to_be(self, project: Path, tmp_path: Path) -> None:
        with pytest.raises(RepositoryError, match=r"has no 'nope' that can be fetched"):
            fetch(project, tmp_path / "out", ref="nope")

    def test_a_symbolic_link_is_written_as_a_file_and_leads_nowhere(self, tmp_path: Path) -> None:
        source = tmp_path / "project"
        source.mkdir()
        git(source, "init", "--quiet", "-b", "main")
        (source / "link").symlink_to("/etc/passwd")
        (source / "a.py").write_text("x = 1\n")
        git(source, "add", "--all")
        git(source, "commit", "--quiet", "-m", "first")

        fetch(source, tmp_path / "out")

        assert not (tmp_path / "out" / "link").is_symlink()
        assert (tmp_path / "out" / "link").read_text() == "/etc/passwd"

    def test_a_submodule_is_not_fetched(self, tmp_path: Path) -> None:
        source = make_project(tmp_path / "project", {"a.py": "x = 1\n"})
        (source / ".gitmodules").write_text(f'[submodule "deep"]\n\tpath = deep\n\turl = file://{tmp_path}/missing\n')
        git(source, "add", ".gitmodules")
        git(source, "update-index", "--add", "--cacheinfo", f"160000,{git(source, 'rev-parse', 'HEAD')},deep")
        git(source, "commit", "--quiet", "-m", "with a submodule")

        fetch(source, tmp_path / "out")

        assert (tmp_path / "out" / ".gitmodules").is_file()
        deep = tmp_path / "out" / "deep"
        assert not deep.exists() or not any(deep.iterdir())

    def test_a_file_kept_in_lfs_stays_the_pointer_to_it(self, tmp_path: Path) -> None:
        pointer = "version https://git-lfs.github.com/spec/v1\noid sha256:" + "a" * 64 + "\nsize 123456789\n"
        source = make_project(
            tmp_path / "project", {".gitattributes": "*.h5ad filter=lfs diff=lfs merge=lfs -text\n", "d.h5ad": pointer}
        )

        fetch(source, tmp_path / "out")

        assert (tmp_path / "out" / "d.h5ad").read_text() == pointer

    def test_the_files_are_not_changed_by_what_the_person_has_set_for_git(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sentinel = tmp_path / "SENTINEL"
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        hook = hooks / "post-checkout"
        hook.write_text(f"#!/bin/sh\ntouch {sentinel}\n")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        settings = tmp_path / "gitconfig"
        settings.write_text(
            f'[filter "sneaky"]\n\tsmudge = sh -c "touch {sentinel}; cat"\n\tclean = cat\n'
            f"[core]\n\thooksPath = {hooks}\n"
            f"[init]\n\ttemplateDir = {hooks}\n"
            '[url "file:///nowhere/"]\n\tinsteadOf = file://\n'
        )
        source = make_project(tmp_path / "project", {".gitattributes": "*.txt filter=sneaky\n", "a.txt": "text\n"})
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(settings))
        monkeypatch.setenv("HOME", str(tmp_path))

        fetch(source, tmp_path / "out")

        assert not sentinel.exists()
        assert (tmp_path / "out" / "a.txt").read_text() == "text\n"

    def test_nothing_in_the_project_is_run_whatever_it_asks_git_to_do(self, tmp_path: Path) -> None:
        sentinel = tmp_path / "RAN"
        program = f"open({str(sentinel)!r}, 'w').close()\n"
        hook = f"#!/bin/sh\ntouch {sentinel}\n"
        source = make_project(
            tmp_path / "project",
            {
                "setup.py": program,
                "conftest.py": program,
                "__init__.py": program,
                "run.sh": hook,
                # What a project can ask of Git, which is nothing that is run: filters and drivers need a program that
                # only a person's own settings can name, and hooks are not part of what is fetched
                ".gitattributes": "* filter=sneaky diff=sneaky merge=sneaky\n*.txt export-subst\n",
                "hooks/post-checkout": hook,
                ".githooks/post-checkout": hook,
                ".gitmodules": (
                    f'[submodule "x"]\n\tpath = x\n\turl = file://{tmp_path}/missing\n\tupdate = !touch {sentinel}\n'
                ),
                "a.txt": "text\n",
            },
        )
        (source / "hooks" / "post-checkout").chmod(0o755)
        git(source, "add", "--all")
        git(source, "commit", "--quiet", "-m", "executable")

        fetch(source, tmp_path / "out")

        assert not sentinel.exists()
        assert (tmp_path / "out" / "a.txt").read_text() == "text\n"

    def test_only_https_is_fetched_by_default(self, project: Path, tmp_path: Path) -> None:
        with pytest.raises(RepositoryError, match="not fetched by a way that is allowed here"):
            clone(f"file://{project}", tmp_path / "out")

    def test_a_folder_that_has_files_is_not_fetched_into(self, project: Path, tmp_path: Path) -> None:
        (tmp_path / "out").mkdir()
        (tmp_path / "out" / "mine.txt").write_text("keep")

        with pytest.raises(RepositoryError, match="has files in it already"):
            fetch(project, tmp_path / "out")

        assert (tmp_path / "out" / "mine.txt").read_text() == "keep"

    def test_a_project_that_is_not_there_is_said_not_to_be(self, tmp_path: Path) -> None:
        with pytest.raises(RepositoryError, match="Git could not fetch"):
            fetch(tmp_path / "missing", tmp_path / "out")

    def test_what_git_says_does_not_give_the_folders_of_this_machine(self, tmp_path: Path) -> None:
        with pytest.raises(RepositoryError) as caught:
            fetch(tmp_path / "missing", tmp_path / "out")

        assert str(tmp_path / "out") not in str(caught.value) and "git-home." not in str(caught.value)

    def test_folders_are_taken_out_of_what_is_said_longest_first(self, tmp_path: Path) -> None:
        said = f"fatal: {tmp_path}/out/.git is not a repository, and {tmp_path}/out has none"

        assert cloning.scrub(said, tmp_path / "out", tmp_path / "out" / ".git") == (
            "fatal: <folder> is not a repository, and <folder> has none"
        )


class TestWhatGitIsRunWith:
    def test_it_has_none_of_the_persons_keys_or_settings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
        monkeypatch.setenv("GIT_DIR", "/somewhere/else")

        environment = cloning.git_environment(tmp_path / "home", "https")

        assert "sk-secret" not in environment.values() and "ghp_secret" not in environment.values()
        assert environment["HTTPS_PROXY"] == "http://proxy.example:3128"
        assert "GIT_DIR" not in environment
        assert environment["HOME"] == str(tmp_path / "home")
        assert environment["GIT_CONFIG_GLOBAL"] == os.devnull and environment["GIT_CONFIG_NOSYSTEM"] == "1"
        assert environment["GIT_TERMINAL_PROMPT"] == "0" and environment["GIT_ALLOW_PROTOCOL"] == "https"
        assert environment["GIT_LFS_SKIP_SMUDGE"] == "1"

    def test_every_command_turns_off_hooks_links_and_credential_helpers(self) -> None:
        assert {"core.hooksPath=/dev/null", "core.symlinks=false", "credential.helper="} <= set(cloning.SAFE_SETTINGS)


class TestSize:
    def test_code_over_the_limit_is_refused_with_how_far_it_got(self, tmp_path: Path) -> None:
        source = make_project(tmp_path / "project", {"big.bin": os.urandom(400_000), "a.py": "x = 1\n"})

        with pytest.raises(RepositoryTooBigError) as caught:
            fetch(source, tmp_path / "out", max_bytes=100_000)

        assert caught.value.limit == 100_000
        assert caught.value.seen > 100_000
        assert "is more than" in str(caught.value) and "KB" in str(caught.value)

    def test_files_that_take_more_than_the_limit_once_written_are_refused_too(self, tmp_path: Path) -> None:
        # What is fetched is small, since zeros pack well, and what is written out is not
        source = make_project(tmp_path / "project", {"zeros.dat": bytes(3_000_000)})

        with pytest.raises(RepositoryTooBigError):
            fetch(source, tmp_path / "out", max_bytes=1_000_000)

    def test_what_the_files_would_take_is_told_before_any_is_written(self, tmp_path: Path) -> None:
        source = make_project(tmp_path / "project", {"zeros.dat": bytes(3_000_000), "a.py": "x = 1\n"})

        with pytest.raises(RepositoryTooBigError) as caught:
            fetch(source, tmp_path / "out", max_bytes=1_000_000)

        assert caught.value.seen >= 3_000_000 and "had come to 2.9 MB" in str(caught.value)
        assert not (tmp_path / "out" / "zeros.dat").exists() and not (tmp_path / "out" / "a.py").exists()

    def test_a_project_of_very_many_files_is_refused_before_any_is_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cloning, "MAX_TREE_FILES", 5)
        source = make_project(tmp_path / "project", {f"f{number}.txt": "" for number in range(9)})

        with pytest.raises(RepositoryError, match=r"more than 5 files"):
            fetch(source, tmp_path / "out")

        assert not (tmp_path / "out" / "f0.txt").exists()

    def test_a_project_with_as_many_files_as_are_kept_is_fetched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cloning, "MAX_TREE_FILES", 9)
        source = make_project(tmp_path / "project", {f"f{number}.txt": "x" for number in range(9)})

        fetch(source, tmp_path / "out")

        assert len(list((tmp_path / "out").iterdir())) == 9

    def test_a_submodule_and_a_link_are_listed_with_no_size_to_add(self, tmp_path: Path) -> None:
        source = make_project(tmp_path / "project", {"a.py": "x = 1\n"})
        git(source, "update-index", "--add", "--cacheinfo", f"160000,{git(source, 'rev-parse', 'HEAD')},deep")
        git(source, "commit", "--quiet", "-m", "with a submodule")

        got = fetch(source, tmp_path / "out", max_bytes=1_000_000)

        assert got.commit == git(source, "rev-parse", "HEAD")

    def test_code_under_the_limit_is_fetched(self, tmp_path: Path) -> None:
        source = make_project(tmp_path / "project", {"small.bin": os.urandom(20_000)})

        fetch(source, tmp_path / "out", max_bytes=1_000_000)

        assert (tmp_path / "out" / "small.bin").stat().st_size == 20_000


class TestARunThatIsCutShort:
    @pytest.fixture
    def slow_git(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        folder = tmp_path / "bin"
        folder.mkdir()
        program = folder / "git"
        program.write_text("#!/bin/sh\nsleep 30\n")
        program.chmod(0o755)
        monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")

        return folder

    @pytest.mark.usefixtures("slow_git")
    def test_git_that_takes_too_long_is_stopped(self, tmp_path: Path) -> None:
        with pytest.raises(RepositoryError, match="did not finish in 1 seconds"):
            clone("https://github.com/owner/name", tmp_path / "out", seconds=1)

    @pytest.mark.usefixtures("slow_git")
    def test_a_request_to_stop_stops_git_and_raises_stopped(self, tmp_path: Path) -> None:
        with pytest.raises(StoppedError):
            clone("https://github.com/owner/name", tmp_path / "out", should_stop=lambda: True)

    def test_git_that_is_not_installed_is_said_not_to_be(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PATH", str(tmp_path))

        with pytest.raises(RepositoryError, match="Git is not installed"):
            clone("https://github.com/owner/name", tmp_path / "out")


class TestAskingForAPlace:
    @pytest.mark.parametrize("ref", [None, "", "  ", "HEAD"])
    def test_none_means_the_default_branch(self, ref: str | None) -> None:
        assert check_ref(ref) == "HEAD"

    @pytest.mark.parametrize("ref", ["main", "v1.2.3", "feature/new-thing", "release@2024", "a" * 40])
    def test_names_of_branches_tags_and_commits_are_taken(self, ref: str) -> None:
        assert check_ref(f" {ref} ") == ref

    @pytest.mark.parametrize(
        "ref",
        [
            "--upload-pack=evil",
            "-x",
            "a..b",
            "a b",
            "ends/",
            "x.lock",
            "a//b",
            "tab\there",
            "é",
            "x" * 201,
            "a;b",
            "$(id)",
        ],
    )
    def test_anything_else_is_refused_and_never_reaches_git_as_an_option(self, ref: str) -> None:
        with pytest.raises(RepositoryError, match="is not the name of a branch or a tag, or a commit"):
            check_ref(ref)
