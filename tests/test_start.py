"""Tests of start.py, which starts the lab from a clone of the repository."""

import dataclasses
import importlib.util
import os
import subprocess
import sys
import types
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "start.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("start_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # A dataclass reads its own module while it is made
    sys.modules["start_script"] = module
    spec.loader.exec_module(module)

    return module


start = load()


def facts(**changes: Any) -> Any:
    """Facts about a machine on which everything is done, with changes."""
    done: dict[str, Any] = {
        "python": Path("/clone/.venv/bin/python"),
        "own": False,
        "made": True,
        "version": (3, 12),
        "installed": True,
        "pip": True,
        "uv": None,
        "node": (22, 17, 1),
        "npm": "/usr/bin/npm",
        "modules_current": True,
        "pages_exist": True,
        "pages_current": True,
    }

    return start.Facts(**{**done, **changes})


CLONE = Path("/clone")


def titles(chosen: Any) -> list[str]:
    return [step.title for step in chosen.steps]


class TestPlan:
    def test_when_everything_is_done_the_lab_is_started_and_nothing_else(self) -> None:
        chosen = start.plan(CLONE, facts())

        assert [step.command for step in chosen.steps] == [("/clone/.venv/bin/python", "-m", "virtual_lab.server")]
        assert chosen.steps[0].cwd == CLONE
        assert chosen.notes == []

    def test_what_the_person_asks_of_the_server_is_given_to_it(self) -> None:
        chosen = start.plan(CLONE, facts(), ["--port", "9000", "--no-browser"])

        assert chosen.steps[-1].command[-3:] == ("--port", "9000", "--no-browser")

    def test_on_a_machine_with_nothing_it_makes_an_environment_installs_builds_and_starts(self) -> None:
        chosen = start.plan(
            CLONE,
            facts(
                made=False,
                version=None,
                installed=False,
                pip=False,
                modules_current=False,
                pages_exist=False,
                pages_current=False,
            ),
        )

        assert titles(chosen) == [
            "Make a Python environment in .venv",
            "Install the Virtual Lab from this clone, and what its interface needs",
            "Install what the pages are built from",
            "Build the pages of the interface",
            "Start the Virtual Lab",
        ]
        make, install, modules, build, run = chosen.steps
        assert make.command == (sys.executable, "-m", "venv", "/clone/.venv")
        # The environment that has just been made has pip, whatever the machine's other environments have
        assert install.command == ("/clone/.venv/bin/python", "-m", "pip", "install", "-e", ".[server,mcp,papers,eval]")
        assert install.cwd == CLONE
        assert modules.command == ("/usr/bin/npm", "ci") and modules.cwd == CLONE / "web"
        assert build.command == ("/usr/bin/npm", "run", "package") and build.cwd == CLONE / "web"
        assert run.command[:3] == ("/clone/.venv/bin/python", "-m", "virtual_lab.server")

    def test_an_environment_without_the_lab_is_given_it_and_nothing_more(self) -> None:
        chosen = start.plan(CLONE, facts(installed=False))

        assert titles(chosen) == [
            "Install the Virtual Lab from this clone, and what its interface needs",
            "Start the Virtual Lab",
        ]

    def test_an_environment_that_is_not_made_is_installed_into_whatever_else_is_said(self) -> None:
        chosen = start.plan(CLONE, facts(made=False, version=None, installed=True))

        assert titles(chosen)[:2] == [
            "Make a Python environment in .venv",
            "Install the Virtual Lab from this clone, and what its interface needs",
        ]

    def test_an_environment_without_pip_is_installed_into_with_uv_if_there_is_uv(self) -> None:
        chosen = start.plan(CLONE, facts(installed=False, pip=False, uv="/bin/uv"))

        assert chosen.steps[0].command == (
            "/bin/uv", "pip", "install", "--python", "/clone/.venv/bin/python", "-e", ".[server,mcp,papers,eval]"
        )  # fmt: skip

    def test_an_environment_without_pip_and_no_uv_is_given_pip_first(self) -> None:
        chosen = start.plan(CLONE, facts(installed=False, pip=False))

        assert [step.command[:4] for step in chosen.steps[:2]] == [
            ("/clone/.venv/bin/python", "-m", "ensurepip", "--upgrade"),
            ("/clone/.venv/bin/python", "-m", "pip", "install"),
        ]

    def test_pages_older_than_what_they_are_built_from_are_built_again_without_installing_what_is_installed(
        self,
    ) -> None:
        chosen = start.plan(CLONE, facts(pages_current=False))

        assert titles(chosen) == ["Build the pages of the interface", "Start the Virtual Lab"]

    def test_what_npm_installs_is_not_looked_at_while_the_pages_are_current(self) -> None:
        chosen = start.plan(CLONE, facts(modules_current=False))

        assert titles(chosen) == ["Start the Virtual Lab"]

    def test_the_pages_are_built_again_when_asked_though_they_are_current(self) -> None:
        chosen = start.plan(CLONE, facts(), rebuild=True)

        assert titles(chosen) == ["Build the pages of the interface", "Start the Virtual Lab"]

    def test_without_node_the_pages_there_are_used_and_the_person_is_told(self) -> None:
        chosen = start.plan(CLONE, facts(node=None, npm=None, pages_current=False))

        assert titles(chosen) == ["Start the Virtual Lab"]
        assert len(chosen.notes) == 1 and "Node 22" in chosen.notes[0] and "already built" in chosen.notes[0]

    def test_a_rebuild_that_was_asked_for_is_refused_without_node_whatever_pages_there_are(self) -> None:
        with pytest.raises(start.StartError, match="Node 22"):
            start.plan(CLONE, facts(node=None, npm=None), rebuild=True)

    def test_with_no_pages_and_no_node_it_says_what_to_install(self) -> None:
        with pytest.raises(start.StartError) as refused:
            start.plan(CLONE, facts(node=None, npm=None, pages_exist=False, pages_current=False))

        assert "Node 22 or later" in str(refused.value) and "not installed" in str(refused.value)
        assert "nodejs.org" in str(refused.value)

    def test_with_no_pages_and_an_old_node_it_says_which_it_found(self) -> None:
        with pytest.raises(start.StartError, match=r"Node is 20\.11\.0"):
            start.plan(CLONE, facts(node=(20, 11, 0), pages_exist=False, pages_current=False))

    def test_node_without_npm_is_not_enough(self) -> None:
        with pytest.raises(start.StartError, match="without npm"):
            start.plan(CLONE, facts(npm=None, pages_exist=False, pages_current=False))

    def test_an_environment_made_by_the_lab_with_an_older_python_is_to_be_deleted(self) -> None:
        with pytest.raises(start.StartError) as refused:
            start.plan(CLONE, facts(version=(3, 10)))

        assert "Python 3.10" in str(refused.value) and "3.12 or later" in str(refused.value)
        assert "Delete /clone/.venv" in str(refused.value)

    def test_an_environment_the_person_is_in_with_an_older_python_is_theirs_to_change(self) -> None:
        with pytest.raises(start.StartError, match="Activate one that is"):
            start.plan(CLONE, facts(own=True, version=(3, 11)))

    def test_the_environment_the_person_is_in_is_said_to_be_the_one_used(self) -> None:
        chosen = start.plan(CLONE, facts(own=True))

        assert len(chosen.notes) == 1 and chosen.notes[0].startswith("Using the environment you are in")

    def test_an_environment_whose_python_could_not_be_asked_is_not_refused_for_its_version(self) -> None:
        chosen = start.plan(CLONE, facts(version=None, installed=False))

        assert titles(chosen)[0].startswith("Install the Virtual Lab")


class FakeRun:
    """A stand-in for subprocess.run that answers what start.py asks of the machine, and records it."""

    def __init__(
        self, probe: str = "3 12\n{origin}\n\n", pip: int = 0, node: str = "v22.17.1\n", root: Path | None = None
    ) -> None:
        self.probe = probe
        self.pip = pip
        self.node = node
        self.root = root
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command: list[str], **options: Any) -> Any:
        self.calls.append(tuple(command))
        if "-c" in command:
            assert self.root is not None
            origin = str(self.root / "src" / "virtual_lab" / "__init__.py")
            return subprocess.CompletedProcess(command, 0, self.probe.format(origin=origin), "")
        if command[1:3] == ["-m", "pip"]:
            return subprocess.CompletedProcess(command, self.pip, "", "")
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, self.node, "")
        raise AssertionError(f"Unexpected command {command}")


LONG_AGO = 1000


def clone(tmp_path: Path, environment: bool = True) -> Path:
    """A directory shaped like a clone: web/src with a page in it, and a .venv with a Python in it.

    Everything in it was last changed at time 1,000, so that a test says when pages were built, or a file changed,
    relative to that.
    """
    (tmp_path / "web" / "src" / "app").mkdir(parents=True)
    (tmp_path / "web" / "src" / "app" / "page.tsx").write_text("export default 1\n")
    (tmp_path / "web" / "package.json").write_text("{}\n")
    (tmp_path / "web" / "package-lock.json").write_text("{}\n")
    (tmp_path / "src" / "virtual_lab").mkdir(parents=True)
    if environment:
        python = start.interpreter(tmp_path / ".venv")
        python.parent.mkdir(parents=True)
        python.write_text("")
    for path in tmp_path.rglob("*"):
        if path.is_file():
            os.utime(path, (LONG_AGO, LONG_AGO))

    return tmp_path


def not_in_an_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "base_prefix", sys.prefix)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)


def which_of(**found: str) -> Callable[[str], str | None]:
    return lambda name: found.get(name)


class TestWhichEnvironment:
    def test_a_virtual_environment_the_person_is_in_is_the_one_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "base_prefix", "/somewhere/else")

        assert start.own_environment({}) is True

    def test_a_conda_environment_the_person_is_in_is_the_one_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "base_prefix", sys.prefix)

        assert start.own_environment({"CONDA_PREFIX": sys.prefix}) is True

    def test_a_conda_environment_that_is_not_the_one_python_runs_in_is_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "base_prefix", sys.prefix)

        assert start.own_environment({"CONDA_PREFIX": "/another/environment"}) is False
        assert start.own_environment({"CONDA_PREFIX": ""}) is False
        assert start.own_environment({}) is False

    def test_outside_any_environment_the_clones_own_is_looked_for(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        not_in_an_environment(monkeypatch)
        root = clone(tmp_path)

        found = start.gather(root, {}, FakeRun(root=root), which_of())

        assert found.own is False
        assert found.python == start.interpreter(root / ".venv") and found.made is True

    def test_no_environment_in_the_clone_is_one_to_make(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        not_in_an_environment(monkeypatch)
        root = clone(tmp_path, environment=False)
        run = FakeRun(root=root)

        found = start.gather(root, {}, run, which_of())

        assert found.made is False and found.installed is False and found.version is None and found.pip is False
        # Nothing is run in an environment that is not there
        assert not any("-c" in call or "pip" in call for call in run.calls)

    def test_the_interpreter_is_in_scripts_on_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(start, "os", types.SimpleNamespace(name="nt"))

        assert start.interpreter(Path("e")) == Path("e/Scripts/python.exe")


class TestProbe:
    def probe(self, tmp_path: Path, output: str, code: int = 0) -> Any:
        root = clone(tmp_path)

        def run(command: list[str], **options: Any) -> Any:
            return subprocess.CompletedProcess(command, code, output.format(root=root), "")

        return start.probe(Path(sys.executable), root, run)

    def test_the_lab_from_this_clone_with_everything_it_needs_is_installed(self, tmp_path: Path) -> None:
        assert self.probe(tmp_path, "3 12\n{root}/src/virtual_lab/__init__.py\n\n") == ((3, 12), True)

    def test_a_lab_from_somewhere_else_is_not_this_clones(self, tmp_path: Path) -> None:
        assert self.probe(tmp_path, "3 12\n/site-packages/virtual_lab/__init__.py\n\n") == ((3, 12), False)

    def test_an_environment_with_no_lab_is_not_installed(self, tmp_path: Path) -> None:
        assert self.probe(tmp_path, "3 12\n\nvirtual_lab fastapi\n") == ((3, 12), False)

    def test_a_missing_module_is_not_installed_though_the_lab_is(self, tmp_path: Path) -> None:
        assert self.probe(tmp_path, "3 12\n{root}/src/virtual_lab/__init__.py\nkeyring\n") == ((3, 12), False)

    def test_a_probe_that_failed_after_saying_its_version_is_not_installed(self, tmp_path: Path) -> None:
        assert self.probe(tmp_path, "3 12\n{root}/src/virtual_lab/__init__.py\n\n", code=1) == ((3, 12), False)

    def test_a_python_that_says_nothing_has_no_version(self, tmp_path: Path) -> None:
        assert self.probe(tmp_path, "", code=1) == (None, False)

    def test_a_python_that_says_something_else_has_no_version(self, tmp_path: Path) -> None:
        assert self.probe(tmp_path, "Segmentation fault\n") == (None, False)

    @pytest.mark.parametrize("error", [OSError("Exec format error"), subprocess.TimeoutExpired("python", 120)])
    def test_a_python_that_cannot_be_run_or_does_not_answer_has_no_version(
        self, tmp_path: Path, error: Exception
    ) -> None:
        def run(command: list[str], **options: Any) -> Any:
            raise error

        assert start.probe(Path("python"), clone(tmp_path), run) == (None, False)

    def test_the_probe_is_run_in_the_clone_and_not_where_the_person_happens_to_be(self, tmp_path: Path) -> None:
        root = clone(tmp_path)
        where: list[Any] = []

        def run(command: list[str], **options: Any) -> Any:
            where.append(options.get("cwd"))
            return subprocess.CompletedProcess(command, 0, "3 12\n\n\n", "")

        start.probe(Path("python"), root, run)

        assert where == [root]

    def test_the_probe_is_run_for_real_by_a_python_that_has_none_of_it(self, tmp_path: Path) -> None:
        root = clone(tmp_path)

        version, installed = start.probe(Path(sys.executable), root, subprocess.run)

        assert version == sys.version_info[:2]
        # This Python has the lab, but from the source tree the tests are run from, which is not this directory
        assert installed is False


class TestNodeAndNpm:
    @pytest.mark.parametrize(
        ("said", "version"),
        [
            ("v22.17.1\n", (22, 17, 1)),
            ("v20.0.0", (20, 0, 0)),
            ("22.1", (22, 1)),
            ("", None),
            ("node: not found", None),
        ],
    )
    def test_the_version_is_read_from_what_node_says(self, said: str, version: tuple[int, ...] | None) -> None:
        assert start.node_version("/bin/node", FakeRun(node=said)) == version

    def test_no_node_has_no_version_and_is_not_asked(self) -> None:
        run = FakeRun()

        assert start.node_version(None, run) is None
        assert run.calls == []

    @pytest.mark.parametrize("error", [OSError("gone"), subprocess.TimeoutExpired("node", 30)])
    def test_a_node_that_cannot_be_run_has_no_version(self, error: Exception) -> None:
        def run(command: list[str], **options: Any) -> Any:
            raise error

        assert start.node_version("/bin/node", run) is None

    def test_gather_reports_what_it_finds(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        not_in_an_environment(monkeypatch)
        root = clone(tmp_path)

        found = start.gather(root, {}, FakeRun(root=root), which_of(node="/bin/node", npm="/bin/npm", uv="/bin/uv"))

        assert found.node == (22, 17, 1) and found.npm == "/bin/npm" and found.uv == "/bin/uv"
        assert found.version == (3, 12) and found.installed is True and found.pip is True

    def test_gather_reports_what_it_does_not_find(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        not_in_an_environment(monkeypatch)
        root = clone(tmp_path)

        found = start.gather(root, {}, FakeRun(pip=1, root=root), which_of())

        assert found.node is None and found.npm is None and found.uv is None and found.pip is False

    def test_a_pip_that_cannot_be_run_is_no_pip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        not_in_an_environment(monkeypatch)
        root = clone(tmp_path)
        answer = FakeRun(root=root)

        def run(command: list[str], **options: Any) -> Any:
            if command[1:3] == ["-m", "pip"]:
                raise OSError("gone")
            return answer(command, **options)

        assert start.gather(root, {}, run, which_of()).pip is False


def touch(path: Path, when: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("x")
    os.utime(path, (when, when))


class TestPagesAndModules:
    def pages(self, root: Path, when: float) -> None:
        touch(root / start.PAGES / "index.html", when)

    def test_no_pages_are_not_current(self, tmp_path: Path) -> None:
        root = clone(tmp_path)

        assert start.pages_current(root) is False

    def test_pages_built_after_every_change_to_their_source_are_current(self, tmp_path: Path) -> None:
        root = clone(tmp_path)
        self.pages(root, 2000)

        assert start.pages_current(root) is True

    def test_a_changed_source_file_makes_them_not_current(self, tmp_path: Path) -> None:
        root = clone(tmp_path)
        self.pages(root, 2000)
        touch(root / "web" / "src" / "app" / "page.tsx", 3000)

        assert start.pages_current(root) is False

    def test_a_new_file_deep_in_the_source_makes_them_not_current(self, tmp_path: Path) -> None:
        root = clone(tmp_path)
        self.pages(root, 2000)
        touch(root / "web" / "src" / "components" / "deep" / "new.tsx", 3000)

        assert start.pages_current(root) is False

    @pytest.mark.parametrize("name", start.PAGE_INPUTS)
    def test_a_changed_configuration_makes_them_not_current(self, tmp_path: Path, name: str) -> None:
        root = clone(tmp_path)
        self.pages(root, 2000)
        touch(root / "web" / name, 3000)

        assert start.pages_current(root) is False

    def test_a_file_changed_when_they_were_built_does_not_make_them_not_current(self, tmp_path: Path) -> None:
        root = clone(tmp_path)
        touch(root / "web" / "src" / "app" / "page.tsx", 2000)
        self.pages(root, 2000)

        assert start.pages_current(root) is True

    def test_what_is_not_the_sources_does_not_count(self, tmp_path: Path) -> None:
        root = clone(tmp_path)
        self.pages(root, 2000)
        touch(root / "web" / "node_modules" / "left-pad" / "index.js", 3000)
        touch(root / "web" / "out" / "index.html", 3000)
        touch(root / "web" / "e2e" / "chat.spec.ts", 3000)

        assert start.pages_current(root) is True

    def test_what_npm_installed_after_the_lock_is_current(self, tmp_path: Path) -> None:
        root = clone(tmp_path)
        touch(root / "web" / "package-lock.json", 1000)
        touch(root / "web" / "node_modules" / ".package-lock.json", 2000)

        assert start.modules_current(root) is True

    def test_what_npm_installed_when_the_lock_last_changed_is_current(self, tmp_path: Path) -> None:
        root = clone(tmp_path)
        touch(root / "web" / "package-lock.json", 1500)
        touch(root / "web" / "node_modules" / ".package-lock.json", 1500)

        assert start.modules_current(root) is True

    def test_what_npm_installed_before_the_lock_changed_is_not(self, tmp_path: Path) -> None:
        root = clone(tmp_path)
        touch(root / "web" / "node_modules" / ".package-lock.json", 1000)
        touch(root / "web" / "package-lock.json", 2000)

        assert start.modules_current(root) is False

    def test_no_install_is_not_current(self, tmp_path: Path) -> None:
        assert start.modules_current(clone(tmp_path)) is False


class TestDescribe:
    def test_it_says_when_nothing_needs_doing_first(self) -> None:
        text = start.describe(start.plan(CLONE, facts()), CLONE)

        assert text.splitlines()[0] == "Nothing needs doing first."
        assert "Then it starts the Virtual Lab:" in text
        assert "/clone/.venv/bin/python -m virtual_lab.server" in text

    def test_it_numbers_what_it_would_do_with_the_command_and_where_it_is_run(self) -> None:
        chosen = start.plan(CLONE, facts(modules_current=False, pages_current=False))

        lines = start.describe(chosen, CLONE).splitlines()

        assert lines[0] == "First:"
        assert lines[1] == "  1. Install what the pages are built from (in web)"
        assert lines[2].strip() == "/usr/bin/npm ci"
        assert lines[3] == "  2. Build the pages of the interface (in web)"

    def test_a_command_with_a_space_in_it_is_quoted_so_it_can_be_copied(self) -> None:
        chosen = start.plan(Path("/my clone"), facts(python=Path("/my clone/.venv/bin/python")))

        assert "'/my clone/.venv/bin/python' -m virtual_lab.server" in start.describe(chosen, Path("/my clone"))

    def test_the_notes_come_first(self) -> None:
        chosen = start.plan(CLONE, facts(own=True))

        assert start.describe(chosen, CLONE).startswith("Using the environment you are in")


def program(source: str) -> tuple[str, ...]:
    return (sys.executable, "-c", source)


class TestExecute:
    def steps(self, *commands: tuple[str, ...], where: Path) -> Any:
        return start.Plan([start.Step(f"Step {number}", command, where) for number, command in enumerate(commands, 1)])

    def test_the_steps_are_run_in_order_and_then_the_lab_whose_exit_code_is_the_result(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log = tmp_path / "log"

        def note(text: str) -> tuple[str, ...]:
            return program(f"open({str(log)!r}, 'a').write({text!r})")

        chosen = self.steps(
            note("one "), note("two "), program(f"{note('lab')[2]}; import sys; sys.exit(7)"), where=tmp_path
        )

        assert start.execute(chosen) == 7

        assert log.read_text() == "one two lab"
        assert "[1/2] Step 1" in capsys.readouterr().out

    def test_each_step_is_run_where_it_says(self, tmp_path: Path) -> None:
        (tmp_path / "here").mkdir()
        (tmp_path / "there").mkdir()
        chosen = start.Plan(
            [
                start.Step(
                    "Where",
                    program(f"import os; open({str(tmp_path / 'where')!r}, 'w').write(os.getcwd())"),
                    tmp_path / "there",
                ),
                start.Step("Lab", program("pass"), tmp_path / "here"),
            ]
        )

        assert start.execute(chosen) == 0

        assert Path((tmp_path / "where").read_text()).resolve() == (tmp_path / "there").resolve()

    def test_the_lab_is_started_where_the_step_says_so_that_the_env_file_there_is_read(self, tmp_path: Path) -> None:
        (tmp_path / "clone").mkdir()
        report = tmp_path / "where"
        chosen = start.Plan(
            [
                start.Step(
                    "Lab", program(f"import os; open({str(report)!r}, 'w').write(os.getcwd())"), tmp_path / "clone"
                )
            ]
        )

        assert start.execute(chosen) == 0

        assert Path(report.read_text()).resolve() == (tmp_path / "clone").resolve()

    def test_a_step_that_fails_stops_everything_after_it_and_its_code_is_the_result(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        marker = tmp_path / "started"
        chosen = self.steps(program("import sys; sys.exit(3)"), program(f"open({str(marker)!r}, 'w')"), where=tmp_path)

        assert start.execute(chosen) == 3

        assert not marker.exists()
        error = capsys.readouterr().err
        assert "Step 1 failed, with exit code 3" in error and "not done twice" in error

    def test_a_step_that_cannot_be_run_is_said_so_and_stops_everything(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        chosen = self.steps(("/there/is/no/such/program",), program("pass"), where=tmp_path)

        assert start.execute(chosen) == 1

        assert "Step 1 could not be run" in capsys.readouterr().err

    def test_the_notes_are_printed_before_anything_is_done(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        chosen = self.steps(program("pass"), where=tmp_path)
        chosen = dataclasses.replace(chosen, notes=["A note."])

        start.execute(chosen)

        assert capsys.readouterr().out.startswith("A note.")

    def test_ctrl_c_while_the_lab_runs_ends_with_the_code_a_shell_gives_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def interrupted(*args: Any, **kwargs: Any) -> int:
            raise KeyboardInterrupt

        monkeypatch.setattr(start.subprocess, "call", interrupted)

        assert start.execute(self.steps(program("pass"), where=tmp_path)) == 130


class TestMain:
    def refuse_to_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def refused(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("Something was run")

        monkeypatch.setattr(start.subprocess, "run", refused)
        monkeypatch.setattr(start.subprocess, "call", refused)

    def test_plan_says_what_would_be_done_and_does_none_of_it(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(start, "gather", lambda root: facts(pages_current=False, modules_current=False))
        self.refuse_to_run(monkeypatch)

        assert start.main(["--plan"], CLONE) == 0

        output = capsys.readouterr().out
        assert "Install what the pages are built from" in output and "Then it starts the Virtual Lab" in output

    def test_what_is_not_its_own_is_given_to_the_server_and_what_is_its_own_is_not(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(start, "gather", lambda root: facts())
        self.refuse_to_run(monkeypatch)

        start.main(["--workspace", "/w", "--plan", "--port=9000", "--rebuild"], CLONE)

        output = capsys.readouterr().out
        assert "virtual_lab.server --workspace /w --port=9000" in output
        assert (
            "--plan" not in output.split("virtual_lab.server")[-1]
            and "--rebuild" not in output.split("virtual_lab.server")[-1]
        )
        assert "Build the pages of the interface" in output

    def test_the_start_of_its_own_option_is_not_taken_for_it(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(start, "gather", lambda root: facts())
        self.refuse_to_run(monkeypatch)

        start.main(["--pla", "--reb", "--plan"], CLONE)

        output = capsys.readouterr().out
        assert "virtual_lab.server --pla --reb" in output
        assert "Build the pages of the interface" not in output

    def test_a_start_with_nothing_to_do_runs_only_the_lab(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(start, "gather", lambda root: facts())
        ran: list[tuple[str, ...]] = []
        monkeypatch.setattr(start.subprocess, "call", lambda command, **kwargs: ran.append(tuple(command)) or 0)

        assert start.main(["--no-browser"], CLONE) == 0

        assert ran == [("/clone/.venv/bin/python", "-m", "virtual_lab.server", "--no-browser")]

    def test_what_cannot_be_started_is_said_on_stderr_and_nothing_is_run(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            start, "gather", lambda root: facts(node=None, npm=None, pages_exist=False, pages_current=False)
        )
        self.refuse_to_run(monkeypatch)

        assert start.main([], CLONE) == 1

        captured = capsys.readouterr()
        assert captured.out == "" and captured.err.startswith("start.py: Building the interface needs Node 22")

    def test_an_older_python_is_told_what_to_do_before_anything_is_looked_at(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(start.sys, "version_info", (3, 9, 6, "final", 0))

        def looked(root: Path) -> Any:
            raise AssertionError("Something was looked at")

        monkeypatch.setattr(start, "gather", looked)

        assert start.main([], CLONE) == 1

        assert "needs Python 3.12 or later, and this is Python 3.9" in capsys.readouterr().err

    def test_the_script_itself_is_run_with_help_by_a_python_that_runs_it(self) -> None:
        done = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, check=False, timeout=60
        )

        assert done.returncode == 0
        assert "--plan" in done.stdout and "--rebuild" in done.stdout and "virtual-lab-server" in done.stdout

    def test_the_script_is_run_for_real_and_says_what_it_would_do(self) -> None:
        done = subprocess.run(
            [sys.executable, str(SCRIPT), "--plan"], capture_output=True, text=True, check=False, timeout=120
        )

        assert done.returncode in (0, 1)
        # Whatever this machine has, it is told what happens next, or what to do about it
        assert "Then it starts the Virtual Lab:" in done.stdout or done.stderr.startswith("start.py: ")

    def test_the_script_is_read_by_a_python_that_is_too_old_to_run_it(self) -> None:
        # Syntax from after 3.9 would stop an older Python before it could say why it cannot go on
        import ast

        ast.parse(SCRIPT.read_text(), feature_version=(3, 9))
