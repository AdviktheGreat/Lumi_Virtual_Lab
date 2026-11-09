"""Tests of building the environment of a paper's code: what is planned from a project's own files, which projects are
refused and why, how a failed build is told apart, what a build container is and is not given, and, where Docker is
there, that real builds keep to what they say: an image that is recorded, a failure that is classified, nothing of the
machine to be seen from inside, and the limits on time and disk."""

import json
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from test_paperagents_stock import tree

from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerExecutor
from virtual_lab.paperagents import environment as env
from virtual_lab.paperagents.environment import EnvironmentBuildError, EnvironmentUnsupportedError

DOCKER = DockerExecutor()
needs_docker = pytest.mark.skipif(not DOCKER.is_available(), reason="Docker daemon is not reachable")


def reachable(host: str, port: int = 443) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


needs_pypi = pytest.mark.skipif(not reachable("pypi.org"), reason="PyPI is not reachable")

# A backend that builds a wheel by hand, so that a project can be installed with no package fetched to do it
BACKEND = """
import os
import zipfile

NAME, VERSION = "fixture", "0.1"


def get_requires_for_build_wheel(config_settings=None):
    return []


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    dist = f"{NAME}-{VERSION}.dist-info"
    files = {
        "fixture/__init__.py": b"VALUE = 3\\n",
        f"{dist}/METADATA": f"Metadata-Version: 2.1\\nName: {NAME}\\nVersion: {VERSION}\\n".encode(),
        f"{dist}/WHEEL": b"Wheel-Version: 1.0\\nGenerator: backend\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n",
    }
    name = f"{NAME}-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(os.path.join(wheel_directory, name), "w") as wheel:
        for path, data in files.items():
            wheel.writestr(path, data)
        wheel.writestr(f"{dist}/RECORD", "".join(f"{path},,\\n" for path in files) + f"{dist}/RECORD,,\\n")
    return name
"""
BROKEN_BACKEND = """
def get_requires_for_build_wheel(config_settings=None):
    return []


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    print("src/fixture/_speed.c:1:10: fatal error: zlib.h: No such file or directory")
    raise SystemExit(1)
"""
PYPROJECT = """[build-system]
requires = []
build-backend = "backend"
backend-path = ["."]

[project]
name = "fixture"
version = "0.1"
"""
OFFLINE = {"pyproject.toml": PYPROJECT, "backend.py": BACKEND, ".python-version": "3.12\n", "README.md": "# Fixture\n"}
BROKEN = {**OFFLINE, "backend.py": BROKEN_BACKEND}


def stock_with(*kinds: str) -> dict[str, Any]:
    return {"environment": [{"path": f"file-{kind}", "kind": kind, "pins": None} for kind in kinds]}


def planned(tmp_path: Path, files: dict[str, Any], **options: Any) -> env.Recipe:
    return env.plan(tree(tmp_path / "project", files), **options)


def commands(recipe: env.Recipe) -> list[list[str]]:
    return [list(step.command) for step in recipe.steps]


class TestSpecifiers:
    @pytest.mark.parametrize(
        ("specifier", "allowed"),
        [
            (">=3.8,<3.11", {8, 9, 10}),
            (">=3.9", {9, 10, 11, 12, 13}),
            (">3.9", {9, 10, 11, 12, 13}),
            ("<3.9", {7, 8}),
            ("<=3.9", {7, 8, 9}),
            ("==3.10.*", {10}),
            ("==3.10", {10}),
            ("~=3.9", {9, 10, 11, 12, 13}),
            ("~=3.9.1", {9}),
            ("!=3.9.*,>=3.8", {8, 10, 11, 12, 13}),
            (">=3.7, !=3.8.*, <3.10", {7, 9}),
            ("", {7, 8, 9, 10, 11, 12, 13}),
            ("something else", {7, 8, 9, 10, 11, 12, 13}),
        ],
    )
    def test_which_versions_a_clause_allows(self, specifier: str, allowed: set[int]) -> None:
        found = {minor for minor in range(7, 14) if env.specifier_allows(specifier, minor)}
        assert found == allowed

    def test_the_nearest_to_the_default_that_a_range_allows(self) -> None:
        assert env.fitting_python(">=3.8,<3.11") == "3.10"
        assert env.fitting_python(">=3.12") == "3.12"
        assert env.fitting_python("<3.9") == "3.8"
        assert env.fitting_python(">=3.9") == "3.11"
        assert env.fitting_python(">=3.14") is None


class TestPython:
    def test_a_person_s_choice_is_first(self, tmp_path: Path) -> None:
        repo = tree(tmp_path, {".python-version": "3.9\n"})
        assert env.choose_python(repo, "3.12") == ("3.12", "chosen by you")

    def test_an_exact_version_before_a_range(self, tmp_path: Path) -> None:
        repo = tree(
            tmp_path, {".python-version": "3.9.7\n", "pyproject.toml": '[project]\nrequires-python = ">=3.8"\n'}
        )
        assert env.choose_python(repo, None)[0] == "3.9"
        assert env.choose_python(tree(tmp_path / "b", {"runtime.txt": "python-3.8.10\n"}), None)[0] == "3.8"

    def test_ranges_from_each_place_they_are_given(self, tmp_path: Path) -> None:
        cases = {
            "a": ({"pyproject.toml": '[project]\nrequires-python = ">=3.8,<3.11"\n'}, "3.10", "requires-python"),
            "b": ({"pyproject.toml": '[tool.poetry.dependencies]\npython = "^3.8"\n'}, "3.11", "pyproject.toml"),
            "c": ({"setup.py": 'setup(name="x", python_requires=">=3.12")\n'}, "3.12", "python_requires in setup.py"),
            "d": ({"setup.cfg": "[options]\npython_requires = >=3.7,<3.9\n"}, "3.8", "python_requires in setup.cfg"),
        }
        for name, (files, version, where) in cases.items():
            chosen, said = env.choose_python(tree(tmp_path / name, files), None)
            assert chosen == version, name
            assert where in said, name

    def test_the_default_when_nothing_is_said(self, tmp_path: Path) -> None:
        chosen, said = env.choose_python(tree(tmp_path, {"README.md": "hello"}), None)
        assert chosen == env.DEFAULT_PYTHON
        assert "does not say" in said

    def test_a_range_that_none_is_in_is_refused_with_it(self, tmp_path: Path) -> None:
        repo = tree(tmp_path, {"pyproject.toml": '[project]\nrequires-python = ">=3.14"\n'})
        with pytest.raises(EnvironmentUnsupportedError) as caught:
            env.choose_python(repo, None)
        assert caught.value.kind == "python_mismatch"
        assert ">=3.14" in str(caught.value)

    def test_a_version_that_is_not_offered_is_not_taken(self, tmp_path: Path) -> None:
        repo = tree(tmp_path, {".python-version": "3.6\n"})
        assert env.choose_python(repo, None)[0] == env.DEFAULT_PYTHON


class TestPlan:
    def test_pip_from_requirements_and_the_project_itself(self, tmp_path: Path) -> None:
        recipe = planned(
            tmp_path, {"requirements.txt": "numpy==1.26.4\n", "setup.py": "from setuptools import setup\nsetup()\n"}
        )
        assert recipe.kind == "pip"
        assert recipe.base_image == "python:3.11-slim"
        assert recipe.files == ("requirements.txt", "setup.py")
        assert [step.id for step in recipe.steps] == ["requirements", "project"]
        assert commands(recipe)[0][-2:] == ["-r", "./requirements.txt"]
        assert commands(recipe)[1][-1] == "./"
        assert "--no-input" in commands(recipe)[0]

    def test_requirements_alone(self, tmp_path: Path) -> None:
        recipe = planned(tmp_path, {"requirements.txt": "pandas\n", ".python-version": "3.9\n"})
        assert [step.id for step in recipe.steps] == ["requirements"]
        assert recipe.base_image == "python:3.9-slim"
        assert recipe.python == "3.9"

    def test_the_project_alone_when_it_has_metadata_and_no_requirements(self, tmp_path: Path) -> None:
        recipe = planned(tmp_path, {"pyproject.toml": PYPROJECT})
        assert [step.id for step in recipe.steps] == ["project"]
        assert recipe.files == ("pyproject.toml",)

    def test_poetry_metadata_is_a_project_to_install(self, tmp_path: Path) -> None:
        recipe = planned(tmp_path, {"pyproject.toml": '[tool.poetry]\nname = "x"\nversion = "1"\n'})
        assert [step.id for step in recipe.steps] == ["project"]

    def test_a_pyproject_without_a_project_is_not_one_to_install(self, tmp_path: Path) -> None:
        with pytest.raises(EnvironmentUnsupportedError) as caught:
            planned(tmp_path, {"pyproject.toml": "[tool.black]\nline-length = 100\n"})
        assert caught.value.kind == "no_environment"

    def test_requirements_in_a_folder(self, tmp_path: Path) -> None:
        recipe = planned(tmp_path, {"requirements/base.txt": "scipy\n"})
        assert commands(recipe)[0][-1] == "./requirements/base.txt"

    def test_a_requirements_file_that_is_a_link_is_not_read(self, tmp_path: Path) -> None:
        repo = tree(tmp_path / "project", {"elsewhere.txt": "numpy\n"})
        (repo / "requirements.txt").symlink_to(repo / "elsewhere.txt")
        with pytest.raises(EnvironmentUnsupportedError) as caught:
            env.plan(repo)
        assert caught.value.kind == "no_environment"

    def test_system_packages_come_first_as_one_checked_step(self, tmp_path: Path) -> None:
        recipe = planned(tmp_path, {"requirements.txt": "h5py\n"}, system_packages=("libhdf5-dev", "pkg-config"))
        first = recipe.steps[0]
        assert first.id == "system"
        assert first.command[:2] == ("sh", "-c")
        assert "apt-get install" in first.command[2]
        assert "libhdf5-dev pkg-config" in first.command[2]
        assert recipe.system_packages == ("libhdf5-dev", "pkg-config")

    def test_a_conda_file_that_says_its_python_makes_the_environment_as_it_is(self, tmp_path: Path) -> None:
        recipe = planned(tmp_path, {"environment.yml": "name: x\ndependencies:\n  - python=3.10\n  - numpy\n"})
        assert recipe.kind == "conda"
        assert recipe.python is None
        assert recipe.base_image == env.CONDA_IMAGE
        assert [step.id for step in recipe.steps] == ["requirements", "clean"]
        assert commands(recipe)[0][:3] == ["conda", "env", "create"]
        assert "environment.yml says" in recipe.python_from

    def test_a_conda_file_that_does_not_gets_the_python_chosen(self, tmp_path: Path) -> None:
        recipe = planned(
            tmp_path,
            {"environment.yml": "dependencies:\n  - numpy\n", ".python-version": "3.9\n"},
        )
        assert recipe.python == "3.9"
        assert [step.id for step in recipe.steps] == ["create", "requirements", "clean"]
        assert commands(recipe)[0][-1] == "python=3.9"
        assert commands(recipe)[1][:3] == ["conda", "env", "update"]

    def test_a_python_cannot_be_chosen_in_place_of_a_conda_file_s(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="says which Python"):
            planned(tmp_path, {"environment.yml": "dependencies:\n  - python=3.10\n"}, python="3.12")

    def test_the_project_is_installed_after_a_conda_file_that_does_not(self, tmp_path: Path) -> None:
        recipe = planned(
            tmp_path,
            {"environment.yml": "dependencies:\n  - python=3.11\n", "setup.py": "from setuptools import setup\n"},
        )
        assert "project" in [step.id for step in recipe.steps]
        assert "--no-deps" in commands(recipe)[1]
        assert any("itself" in note for note in recipe.notes)

    def test_not_again_after_a_conda_file_that_does(self, tmp_path: Path) -> None:
        text = "dependencies:\n  - python=3.11\n  - pip\n  - pip:\n    - -e .\n"
        recipe = planned(tmp_path, {"environment.yml": text, "setup.py": "from setuptools import setup\n"})
        assert "project" not in [step.id for step in recipe.steps]

    def test_a_conda_file_comes_before_requirements(self, tmp_path: Path) -> None:
        recipe = planned(tmp_path, {"environment.yml": "dependencies:\n  - python=3.11\n", "requirements.txt": "x\n"})
        assert recipe.kind == "conda"

    @pytest.mark.parametrize("name", ["conda-env.yaml", "environment.yaml", "environment-gpu.yml"])
    def test_a_conda_file_by_other_names(self, tmp_path: Path, name: str) -> None:
        recipe = planned(tmp_path, {name: "dependencies:\n  - python=3.11\n"})
        assert recipe.files == (name,)

    def test_a_conda_file_that_is_not_one_is_refused(self, tmp_path: Path) -> None:
        for number, text in enumerate(["{{ not yaml", "name: x\n", "- just\n- a list\n"]):
            with pytest.raises(EnvironmentUnsupportedError) as caught:
                planned(tmp_path / str(number), {"environment.yml": text})
            assert caught.value.kind == "no_environment"

    def test_lock_files_that_are_not_used_are_said_not_to_be(self, tmp_path: Path) -> None:
        recipe = planned(tmp_path, {"requirements.txt": "x\n", "poetry.lock": "# lock\n", "uv.lock": ""})
        said = " ".join(recipe.notes)
        assert "poetry.lock is not used" in said and "uv.lock is not used" in said

    @pytest.mark.parametrize(
        ("kinds", "files", "kind"),
        [
            (("renv",), {"renv.lock": "{}"}, "r"),
            (("r-package",), {"DESCRIPTION": "Package: x\n"}, "r"),
            (("julia",), {"Project.toml": "name = 'x'\n"}, "julia"),
            (("docker",), {"Dockerfile": "FROM python:3.11\n"}, "docker"),
            ((), {"Pipfile": "[packages]\n"}, "pipfile"),
            ((), {"README.md": "Install numpy and pandas, then run it.\n"}, "no_environment"),
        ],
    )
    def test_projects_that_are_not_built_here_say_why(
        self, tmp_path: Path, kinds: tuple[str, ...], files: dict[str, Any], kind: str
    ) -> None:
        with pytest.raises(EnvironmentUnsupportedError) as caught:
            env.plan(tree(tmp_path / "project", files), stock_with(*kinds))
        assert caught.value.kind == kind
        assert str(caught.value)

    def test_a_dockerfile_beside_python_files_is_not_used_and_is_said_not_to_be(self, tmp_path: Path) -> None:
        recipe = env.plan(tree(tmp_path / "project", {"requirements.txt": "x\n"}), stock_with("docker"))
        assert any("Dockerfile" in note for note in recipe.notes)

    def test_the_recipe_is_what_a_page_shows(self, tmp_path: Path) -> None:
        recipe = planned(tmp_path, {"requirements.txt": "x\n"}, system_packages=("zlib1g-dev",))
        shown = recipe.to_dict()
        json.dumps(shown)
        assert shown["steps"][0]["id"] == "system"
        assert shown["python"] == "3.11"


class TestChecks:
    def test_python(self) -> None:
        assert env.check_python(None) is None
        assert env.check_python("3.9") == "3.9"
        for bad in ("3.6", "3", "latest", 3.9, ["3.9"]):
            with pytest.raises(ValueError):
                env.check_python(bad)

    def test_system_packages(self) -> None:
        assert env.check_system_packages(None) == ()
        assert env.check_system_packages(["libhdf5-dev", "zlib1g-dev", "libhdf5-dev"]) == ("libhdf5-dev", "zlib1g-dev")
        for bad in (["Bad Name"], ["x; rm -rf /"], ["a"], [3], "libhdf5-dev", ["$(id)"], ["-y"], ["a" * 100]):
            with pytest.raises(ValueError):
                env.check_system_packages(bad)
        with pytest.raises(ValueError):
            env.check_system_packages([f"package-{number}" for number in range(env.MAX_SYSTEM_PACKAGES + 1)])

    def test_limits(self) -> None:
        assert env.check_limits(None, None) == env.Limits(env.DEFAULT_MINUTES, env.DEFAULT_GIGABYTES)
        assert env.check_limits(5, 2) == env.Limits(5, 2)
        for minutes, gigabytes in ((0, 1), (env.MAX_MINUTES + 1, 1), (1, 0), (1, env.MAX_GIGABYTES + 1), (True, 1)):
            with pytest.raises(ValueError):
                env.check_limits(minutes, gigabytes)
        for bad in ("5", 2.5):
            with pytest.raises(ValueError):
                env.check_limits(bad, 1)

    def test_what_a_tag_is(self) -> None:
        assert env.tag_of("My-Agent", "ABCDEF0123456789ffff") == "virtual-lab-paperagent:my-agent-abcdef012345"


PIP_NOT_FOUND = """Collecting numpyy==9.9
  ERROR: Could not find a version that satisfies the requirement numpyy==9.9 (from versions: none)
ERROR: No matching distribution found for numpyy==9.9"""
PIP_WHEEL = """Building wheels for collected packages: pycairo
  Building wheel for pycairo (pyproject.toml): finished with status 'error'
  error: subprocess-exited-with-error
  × Building wheel for pycairo (pyproject.toml) did not run successfully.
  ERROR: Failed building wheel for pycairo
Failed to build pycairo
ERROR: Could not build wheels for pycairo, which is required to install pyproject.toml-based projects"""
PIP_CONFLICT = """ERROR: Cannot install a==1 and b==2 because these package versions have conflicting dependencies.
ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/latest/topics/dependency-resolution/"""
CONDA_CONFLICT = """Solving environment: failed
LibMambaUnsatisfiableError: Encountered problems while solving:
  - package a-1.0 requires python <3.9, but none of the providers can be installed"""
PIP_OTHER_PYTHON = """ERROR: Package 'scanpy' requires a different Python: 3.12.3 not in '>=3.8,<3.11'"""
PIP_IGNORED = """ERROR: Ignored the following versions that require a different python version: 1.0 Requires-Python <3.9
ERROR: Could not find a version that satisfies the requirement oldlib==1.0 (from versions: none)
ERROR: No matching distribution found for oldlib==1.0"""
OLD_CODE = "ModuleNotFoundError: No module named 'distutils'\n  error: subprocess-exited-with-error"
NO_NETWORK = (
    "WARNING: Retrying (Retry(total=0)) after connection broken by "
    "'NewConnectionError: Temporary failure in name resolution'\n"
    "ERROR: Could not find a version that satisfies the requirement x"
)
PRIVATE = "git@github.com: Permission denied (publickey).\nfatal: Could not read from remote repository."
CONDA_MISSING = (
    "PackagesNotFoundError: The following packages are not available from current channels:\n\n  - nothere=1.0\n"
)


class TestClassify:
    def kind(self, output: str, **options: Any) -> env.Failure:
        return env.classify(output, "requirements", 1, **options)

    def test_a_missing_header_names_the_package_that_has_it(self) -> None:
        output = "gcc -c x.c\nx.c:1:10: fatal error: hdf5.h: No such file or directory\n    1 | #include <hdf5.h>"
        failure = self.kind(output)
        assert failure.kind == "missing_system_library"
        assert failure.system_packages == ("libhdf5-dev",)
        assert "hdf5.h" in failure.detail

    def test_a_header_that_is_not_known_has_no_suggestion(self) -> None:
        failure = self.kind("x.c:1:10: fatal error: weirdlib.h: No such file or directory")
        assert failure.kind == "missing_system_library"
        assert failure.system_packages == ()

    @pytest.mark.parametrize(
        ("output", "package"),
        [
            ("error: command 'gcc' failed: No such file or directory", "build-essential"),
            ("  'pkg-config' not found.", "pkg-config"),
            ("/bin/sh: 1: cmake: not found", "cmake"),
            ("Cannot find command 'git' - do you have 'git' installed and in your PATH?", "git"),
            ("FileNotFoundError: [Errno 2] No such file or directory: 'gfortran'", "gfortran"),
            ("/usr/bin/ld: cannot find -lz: No such file or directory", "zlib1g-dev"),
            ("Package cairo was not found in the pkg-config search path.", "libcairo2-dev"),
            ('meson.build:1:0: ERROR: Dependency "gsl" not found, tried pkgconfig', "libgsl-dev"),
        ],
    )
    def test_a_missing_tool_or_library(self, output: str, package: str) -> None:
        failure = self.kind(output)
        assert failure.kind == "missing_system_library"
        assert failure.system_packages == (package,)

    def test_a_compile_error_is_not_taken_for_a_missing_compiler(self) -> None:
        failure = self.kind("error: command '/usr/bin/gcc' failed with exit code 1\nERROR: Failed building wheel for x")
        assert failure.kind == "build_failed"
        assert failure.package == "x"

    def test_a_package_that_would_not_build(self) -> None:
        failure = self.kind(PIP_WHEEL)
        assert failure.kind == "build_failed"
        assert failure.package == "pycairo"

    def test_conflicts(self) -> None:
        assert self.kind(PIP_CONFLICT).kind == "version_conflict"
        assert self.kind(CONDA_CONFLICT).kind == "version_conflict"

    def test_a_package_that_needs_another_python_says_which_to_try(self) -> None:
        failure = self.kind(PIP_OTHER_PYTHON, python="3.12")
        assert failure.kind == "python_mismatch"
        assert failure.python == "3.10"

    def test_a_version_that_is_there_only_for_another_python(self) -> None:
        failure = self.kind(PIP_IGNORED, python="3.11")
        assert failure.kind == "python_mismatch"
        assert failure.package == "oldlib==1.0"

    def test_code_that_is_too_old_says_to_try_the_next_older_python(self) -> None:
        failure = self.kind(OLD_CODE, python="3.12")
        assert failure.kind == "python_mismatch"
        assert failure.python == "3.11"
        assert self.kind(OLD_CODE, python="3.7").python is None

    def test_a_package_that_is_not_there(self) -> None:
        for output, name in ((PIP_NOT_FOUND, "numpyy==9.9"), (CONDA_MISSING, "nothere=1.0")):
            failure = self.kind(output)
            assert failure.kind == "not_found"
            assert failure.package == name

    def test_the_network_not_answering_and_what_is_private(self) -> None:
        assert self.kind(NO_NETWORK).kind == "network"
        assert self.kind(PRIVATE).kind == "private_dependency"

    def test_memory(self) -> None:
        assert env.classify("", "requirements", 137).kind == "out_of_memory"
        assert self.kind("Killed").kind == "out_of_memory"

    def test_time_and_disk_are_told_from_the_flags(self) -> None:
        assert env.classify("anything", "requirements", None, timed_out=True).kind == "timeout"
        assert env.classify("anything", "requirements", None, too_big=True).kind == "too_big"

    def test_what_is_not_known_is_failed_and_has_the_end_of_the_output(self) -> None:
        output = "\n".join(f"line {number}" for number in range(200))
        failure = env.classify(output, "project", 2)
        assert failure.kind == "failed"
        assert failure.step == "project"
        assert failure.tail[-1] == "line 199"
        assert len(failure.tail) == env.TAIL_LINES
        assert "exit code 2" in failure.detail

    def test_every_kind_is_one_that_is_listed(self) -> None:
        outputs = [PIP_NOT_FOUND, PIP_WHEEL, PIP_CONFLICT, OLD_CODE, NO_NETWORK, PRIVATE, "nothing", "Killed"]
        for output in outputs:
            assert self.kind(output).kind in env.FAILURE_KINDS
        assert env.Failure("failed", "t", "d").to_dict()["system_packages"] == []


class TestContainer:
    """What a build is made with, which is read from the command that makes it."""

    def arguments(self) -> list[str]:
        return list(env.create_arguments("a-build", "python:3.11-slim"))

    def test_nothing_of_the_machine_is_mounted_or_passed(self) -> None:
        arguments = self.arguments()
        for flag in ("--mount", "--volume", "-v", "--volumes-from", "--env-file", "--device", "--privileged", "--pid"):
            assert flag not in arguments
        assert not any(argument.startswith(("--mount=", "--volume=", "--env-file=")) for argument in arguments)
        scratch = arguments[arguments.index("--tmpfs") + 1]
        assert not any(argument.startswith("/") and ":" in argument for argument in arguments if argument != scratch)

    def test_every_variable_is_given_a_value_so_that_none_is_taken_from_here(self) -> None:
        arguments = self.arguments()
        given = [arguments[number + 1] for number, argument in enumerate(arguments) if argument == "--env"]
        assert given
        assert all("=" in value for value in given)

    def test_it_has_what_installing_takes_and_no_more(self) -> None:
        arguments = self.arguments()
        assert arguments[arguments.index("--cap-drop") + 1] == "ALL"
        added = [arguments[number + 1] for number, argument in enumerate(arguments) if argument == "--cap-add"]
        assert sorted(added) == sorted(env.CAPABILITIES)
        assert "no-new-privileges" in arguments
        assert "SYS_ADMIN" not in added and "NET_ADMIN" not in added

    def test_it_has_ceilings(self) -> None:
        arguments = self.arguments()
        assert arguments[arguments.index("--memory") + 1] == env.MEMORY
        assert arguments[arguments.index("--memory-swap") + 1] == env.MEMORY
        assert arguments[arguments.index("--pids-limit") + 1] == str(env.PIDS)
        assert arguments[arguments.index("--cpus") + 1] == env.CPUS
        assert "--tmpfs" in arguments

    def test_the_processors_it_may_use_are_what_it_is_told_and_no_more_than_the_most(self) -> None:
        arguments = list(env.create_arguments("a-build", "python:3.11-slim", cpus="2"))
        assert arguments[arguments.index("--cpus") + 1] == "2"

    def test_it_says_whose_it_is_when_it_is_told(self) -> None:
        arguments = list(env.create_arguments("a-build", "python:3.11-slim", "my-agent"))
        assert arguments[arguments.index("--label") + 1] == f"{env.AGENT_LABEL}=my-agent"
        assert "--label" not in self.arguments()

    def test_it_has_the_network_and_the_project_is_copied_in_not_mounted(self) -> None:
        arguments = self.arguments()
        assert arguments[arguments.index("--network") + 1] == "bridge"
        assert arguments[-3:] == ["python:3.11-slim", "sleep", "infinity"]
        assert arguments[0] == "create"


def asking(tmp_path: Path, output: str, code: int = 0) -> list[str]:
    """A stand-in for the docker command, which prints what it is given and ends with the code it is given."""
    script = tmp_path / "docker"
    script.write_text(f"#!/bin/sh\nprintf '%s' '{output}'\nexit {code}\n")
    script.chmod(0o755)

    return [str(script)]


class TestProcessors:
    """A container that asks for more processors than Docker has is refused, and so the most is no more than it has."""

    def test_it_is_given_the_most_when_docker_has_that_many_or_more(self, tmp_path: Path) -> None:
        assert env.cpus_for(asking(tmp_path, "18")) == env.CPUS
        assert env.cpus_for(asking(tmp_path, str(env.CPUS))) == env.CPUS

    def test_it_is_given_what_docker_has_when_that_is_fewer(self, tmp_path: Path) -> None:
        assert env.cpus_for(asking(tmp_path, "2")) == "2"
        assert env.cpus_for(asking(tmp_path, "1")) == "1"

    def test_it_is_given_one_when_docker_does_not_say(self, tmp_path: Path) -> None:
        for command in (asking(tmp_path, "", 1), asking(tmp_path, "many"), asking(tmp_path, "0"), ["/no/such/docker"]):
            assert env.host_cpus(command) is None
            assert env.cpus_for(command) == "1"


class Watched(env.Builder):
    """A build whose container is not a real one, to see what it does about its limits."""

    def __init__(self, *args: Any, size: int = 0, **options: Any) -> None:
        super().__init__(*args, **options)
        self.written = size
        self.killed = 0

    def kill(self) -> None:
        self.killed += 1

    def size(self) -> int:
        return self.written


def builder(tmp_path: Path, **options: Any) -> Watched:
    recipe = planned(tmp_path, {"requirements.txt": "x\n"})
    return Watched(
        tmp_path / "project", recipe, "virtual-lab-paperagent:t", options.pop("limits", env.Limits(1, 1)), **options
    )


class TestWatching:
    def test_a_stop_kills_the_container_and_says_so(self, tmp_path: Path) -> None:
        stop = threading.Event()
        watched = builder(tmp_path, stop=stop)
        watched.watch([], "requirements")
        stop.set()
        with pytest.raises(StoppedError):
            watched.watch([], "requirements")
        assert watched.killed == 1

    def test_running_over_the_time_is_a_timeout_with_the_end_of_the_output(self, tmp_path: Path) -> None:
        watched = builder(tmp_path)
        watched.deadline = time.monotonic() - 1
        with pytest.raises(EnvironmentBuildError) as caught:
            watched.watch(["Collecting x", "Downloading x"], "requirements")
        assert caught.value.failure.kind == "timeout"
        assert caught.value.failure.step == "requirements"
        assert caught.value.failure.tail[-1] == "Downloading x"
        assert watched.killed == 1

    def test_writing_over_the_disk_is_too_big(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        watched = builder(tmp_path, size=2 * 1024**3)
        watched.last_size = time.monotonic() - env.SIZE_SECONDS - 1
        with pytest.raises(EnvironmentBuildError) as caught:
            watched.watch([], "project")
        assert caught.value.failure.kind == "too_big"
        assert watched.killed == 1

    def test_the_disk_is_not_looked_at_more_often_than_it_is_said_to_be(self, tmp_path: Path) -> None:
        watched = builder(tmp_path, size=2 * 1024**3)
        watched.watch([], "project")
        assert watched.killed == 0

    def test_a_label_is_checked(self, tmp_path: Path) -> None:
        recipe = planned(tmp_path, {"requirements.txt": "x\n"})
        assert env.Builder(tmp_path, recipe, "t:t", env.Limits(), label="my-agent").container.startswith(
            "virtual-lab-build-my-agent-"
        )
        for bad in ("My Agent", "a/b", "a;b", "A"):
            with pytest.raises(ValueError):
                env.Builder(tmp_path, recipe, "t:t", env.Limits(), label=bad)


class TestNeeding:
    """What the build cannot go on without is not run once the build was stopped or is out of time."""

    def test_nothing_is_run_after_a_stop(self, tmp_path: Path) -> None:
        marker = tmp_path / "ran"
        script = tmp_path / "docker"
        script.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        script.chmod(0o755)
        stop = threading.Event()
        watched = builder(tmp_path, stop=stop, docker_command=[str(script)])
        assert watched.need("copy the code in", "cp") == ""
        marker.unlink()
        stop.set()
        with pytest.raises(StoppedError):
            watched.need("copy the code in", "cp")
        assert not marker.exists()

    def test_nothing_is_run_after_the_time_is_over(self, tmp_path: Path) -> None:
        watched = builder(tmp_path, docker_command=asking(tmp_path, ""))
        watched.deadline = time.monotonic() - 1
        with pytest.raises(EnvironmentBuildError) as caught:
            watched.need("keep the image", "commit")
        assert caught.value.failure.kind == "timeout"

    def test_a_command_is_not_given_longer_than_what_is_left_of_the_time(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        given: list[float] = []

        def run(command: Any, *arguments: str, timeout: float = 0) -> Any:
            given.append(timeout)
            return subprocess.CompletedProcess([], 0, "", "")

        monkeypatch.setattr(env, "docker_run", run)
        watched = builder(tmp_path)
        watched.deadline = time.monotonic() + 100
        watched.need("copy the code in", "cp")
        assert 30 <= given[0] <= 100
        watched.deadline = time.monotonic() + 5
        watched.need("copy the code in", "cp")
        assert given[1] == 30


PYTHON = ["python3", "-u", "-c"]


class TestStreaming:
    def test_output_is_passed_on_as_it_comes_and_kept(self, tmp_path: Path) -> None:
        seen: list[str] = []
        watched = builder(tmp_path, on_output=seen.append)
        code, output = watched.stream([*PYTHON, "print('one'); print('two')"], "requirements")
        assert (code, output) == (0, "one\ntwo")
        assert seen == ["one", "two"]
        assert list(watched.log) == ["one", "two"]

    def test_what_a_command_ends_with_is_given(self, tmp_path: Path) -> None:
        code, output = builder(tmp_path).stream([*PYTHON, "import sys; print('bad'); sys.exit(3)"])
        assert (code, output) == (3, "bad")

    def test_quiet_keeps_it_out_of_the_log(self, tmp_path: Path) -> None:
        watched = builder(tmp_path)
        code, output = watched.stream([*PYTHON, "print('lock')"], quiet=True)
        assert output == "lock" and list(watched.log) == []

    def test_a_great_deal_of_output_keeps_the_last_of_it(self, tmp_path: Path) -> None:
        watched = builder(tmp_path)
        total = env.KEPT_LOG_LINES + 500
        _, output = watched.stream([*PYTHON, f"[print(n) for n in range({total})]"])
        lines = output.splitlines()
        assert len(lines) == env.KEPT_LOG_LINES
        assert lines[-1] == str(total - 1)
        assert len(watched.log) == env.KEPT_LOG_LINES

    def test_a_line_that_is_too_long_is_cut_and_the_ones_after_it_are_kept(self, tmp_path: Path) -> None:
        watched = builder(tmp_path)
        code, output = watched.stream(
            [*PYTHON, f"import sys; sys.stdout.write('x' * {50 * env.LINE_CHARS} + chr(10) + 'after' + chr(10))"]
        )
        first, last = output.splitlines()
        assert code == 0 and last == "after"
        assert first.startswith("x" * env.LINE_CHARS) and len(first) < env.LINE_CHARS + 100
        assert first.endswith("[the rest of the line is cut]")
        assert all(len(line) < env.LINE_CHARS + 100 for line in watched.log)

    def test_a_line_that_is_exactly_as_long_as_the_most_is_not_cut(self, tmp_path: Path) -> None:
        _, output = builder(tmp_path).stream([*PYTHON, f"print('y' * {env.LINE_CHARS - 1})"])
        assert output == "y" * (env.LINE_CHARS - 1)

    def test_output_that_never_has_a_line_end_is_not_piled_up_and_the_time_is_still_kept_to(
        self, tmp_path: Path
    ) -> None:
        watched = builder(tmp_path)
        watched.deadline = time.monotonic() + 2
        began = time.monotonic()
        with pytest.raises(EnvironmentBuildError) as caught:
            watched.stream([*PYTHON, "while True: print('z' * 100000, end='')"], "requirements")
        assert caught.value.failure.kind == "timeout"
        assert time.monotonic() - began < 15
        assert all(len(line) < env.LINE_CHARS + 100 for line in watched.log)

    def test_a_great_many_short_lines_wait_in_the_pipe_and_do_not_pile_up(self, tmp_path: Path) -> None:
        total = 20000
        watched = builder(tmp_path)
        code, output = watched.stream([*PYTHON, f"[print(n) for n in range({total})]"])
        assert code == 0 and output.splitlines()[-1] == str(total - 1)

    def test_a_stop_is_seen_while_output_never_stops_coming(self, tmp_path: Path) -> None:
        stop = threading.Event()
        watched = builder(tmp_path, stop=stop)
        threading.Timer(0.5, stop.set).start()
        began = time.monotonic()
        with pytest.raises(StoppedError):
            watched.stream([*PYTHON, "while True: print('x' * 50)"])
        assert time.monotonic() - began < 10

    def test_the_time_is_kept_to_while_output_never_stops_coming(self, tmp_path: Path) -> None:
        watched = builder(tmp_path)
        watched.deadline = time.monotonic() + 1
        began = time.monotonic()
        with pytest.raises(EnvironmentBuildError) as caught:
            watched.stream([*PYTHON, "while True: print('x' * 50)"], "requirements")
        assert caught.value.failure.kind == "timeout"
        assert time.monotonic() - began < 10

    def test_a_command_that_is_silent_is_still_watched(self, tmp_path: Path) -> None:
        watched = builder(tmp_path)
        watched.deadline = time.monotonic() + 1
        with pytest.raises(EnvironmentBuildError):
            watched.stream([*PYTHON, "import time; time.sleep(60)"])


def containers() -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "--all", "--filter", f"name={env.BUILD_PREFIX}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.split()


def inspected(reference: str, template: str) -> str:
    result = subprocess.run(
        ["docker", "inspect", "--format", template, reference], capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


@pytest.fixture
def tag() -> Any:
    name = f"virtual-lab-paperagent:test-{time.time_ns()}"
    yield name
    env.remove_image(name)


@needs_docker
class TestBuilding:
    """Builds that are real, in Docker. The project is installed by a backend that is its own, so nothing is fetched to
    build it but the image that Python is in."""

    def build(self, tmp_path: Path, files: dict[str, Any], tag: str, **options: Any) -> env.Built:
        repo = tree(tmp_path / "project", files)
        recipe = env.plan(repo, **options)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        return env.build_environment(repo, recipe, tag, env.Limits(10, 5), scratch)

    def test_a_project_is_built_and_what_it_made_is_recorded(self, tmp_path: Path, tag: str) -> None:
        lines: list[str] = []
        repo = tree(tmp_path / "project", OFFLINE)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        built = env.build_environment(repo, env.plan(repo), tag, env.Limits(10, 5), scratch, on_output=lines.append)

        assert built.tag == tag
        assert built.image_id.startswith("sha256:")
        assert env.image_id_of(tag) == built.image_id == inspected(tag, "{{.Id}}")
        assert built.python.startswith("3.12.")
        assert built.lock_name == "pip-freeze.txt"
        assert "fixture @ file:///opt/paper/repo" in built.lock
        assert built.packages >= 1
        assert built.pip_check == {"ok": True, "problems": []}
        assert built.base_id.startswith("sha256:")
        assert built.architecture
        assert [step["id"] for step in built.steps] == ["project"]
        assert all(step["exit_code"] == 0 for step in built.steps)
        assert any("Install the project itself" in line for line in lines)
        assert "fixture" in built.log
        assert containers() == []

    def test_the_image_runs_as_it_will_be_used_with_no_network(self, tmp_path: Path, tag: str) -> None:
        self.build(tmp_path, OFFLINE, tag)
        work = tmp_path / "work"
        work.mkdir()
        offline = DockerExecutor(image=tag, allow_network=False, timeout=60)
        shown = offline.run(
            work,
            [
                "python",
                "-c",
                "import fixture, socket\n"
                "print(fixture.VALUE)\n"
                "try:\n    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
                "except OSError:\n    print('no network')\n",
            ],
        )
        assert shown.succeeded, shown.stderr
        assert shown.stdout.split() == ["3", "no", "network"]

    def test_the_image_is_the_pin_and_is_not_taken_by_what_it_was_built_from(self, tmp_path: Path, tag: str) -> None:
        built = self.build(tmp_path, OFFLINE, tag)
        base = inspected(built.tag, "{{.Config.Image}}")
        assert "sleep" not in inspected(built.tag, "{{.Config.Cmd}}")
        assert base != tag

    def test_a_failing_install_is_classified_and_leaves_nothing(self, tmp_path: Path, tag: str) -> None:
        with pytest.raises(EnvironmentBuildError) as caught:
            self.build(tmp_path, BROKEN, tag)
        failure = caught.value.failure
        assert failure.kind == "missing_system_library"
        assert failure.system_packages == ("zlib1g-dev",)
        assert failure.step == "project"
        assert any("zlib.h" in line for line in failure.tail)
        assert env.image_id_of(tag) is None
        assert containers() == []

    @needs_pypi
    def test_a_package_that_is_not_there_is_classified(self, tmp_path: Path, tag: str) -> None:
        files = {**OFFLINE, "requirements.txt": "virtual-lab-there-is-no-such-package==9.9.9\n"}
        with pytest.raises(EnvironmentBuildError) as caught:
            self.build(tmp_path, files, tag)
        assert caught.value.failure.kind == "not_found"
        assert caught.value.failure.step == "requirements"

    @needs_pypi
    def test_a_system_package_that_was_asked_for_is_installed_first(self, tmp_path: Path, tag: str) -> None:
        built = self.build(tmp_path, OFFLINE, tag, system_packages=("file",))
        assert [step["id"] for step in built.steps] == ["system", "project"]

    def test_a_project_that_installs_but_does_not_import_offline_is_not_kept(
        self, tmp_path: Path, tag: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            env,
            "smoke",
            lambda *a, **k: env.Failure("does_not_run", "It does not run offline", "no", step="offline run"),
        )
        with pytest.raises(EnvironmentBuildError) as caught:
            self.build(tmp_path, OFFLINE, tag)
        assert caught.value.failure.kind == "does_not_run"
        assert env.image_id_of(tag) is None
        assert containers() == []

    def test_the_image_is_taken_away_by_its_name(self, tmp_path: Path, tag: str) -> None:
        self.build(tmp_path, OFFLINE, tag)
        assert env.remove_image(tag) is True
        assert env.image_id_of(tag) is None
        assert env.remove_image(tag) is True


@needs_docker
class TestIsolation:
    """What can be seen from inside a build: nothing of this machine, and no key."""

    def test_a_build_container_cannot_see_the_workspace_or_a_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        secret = "sk-or-this-must-never-be-seen-in-a-build"
        monkeypatch.setenv("OPENROUTER_API_KEY", secret)
        monkeypatch.setenv("VIRTUAL_LAB_TOKEN", secret)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "notes.txt").write_text(secret)
        name = f"{env.BUILD_PREFIX}isolation-{time.time_ns()}"
        created = subprocess.run(
            ["docker", *env.create_arguments(name, "python:3.12-slim", "isolation", env.cpus_for())],
            capture_output=True,
            text=True,
            check=False,
        )
        assert created.returncode == 0, created.stderr
        try:
            subprocess.run(["docker", "start", name], capture_output=True, check=True)

            def inside(*command: str) -> subprocess.CompletedProcess:
                return subprocess.run(["docker", "exec", name, *command], capture_output=True, text=True, check=False)

            assert inspected(name, "{{json .Mounts}}") == "[]"
            assert inspected(name, "{{json .HostConfig.Binds}}") in ("null", "[]")
            assert secret not in inspected(name, "{{json .Config.Env}}")
            assert secret not in inside("env").stdout
            assert secret not in inside("sh", "-c", "cat /proc/1/environ | tr '\\0' '\\n'").stdout
            assert inside("test", "-e", str(workspace)).returncode != 0
            assert inside("test", "-e", str(workspace / "notes.txt")).returncode != 0
            assert inside("test", "-e", "/Users").returncode != 0
            assert inside("ls", "-A", "/home").stdout.strip() == ""
            host = inspected(name, "{{.HostConfig.Privileged}} {{json .HostConfig.CapDrop}} {{.HostConfig.PidsLimit}}")
            assert host == f'false ["ALL"] {env.PIDS}'
            assert inspected(name, "{{.HostConfig.Memory}}") == str(8 * 1024**3)
            assert inspected(name, "{{.HostConfig.NanoCpus}}") == str(int(env.cpus_for()) * 10**9)
            assert inspected(name, '{{index .Config.Labels "virtual-lab.paperagent"}}') == "isolation"
            assert inspected(name, "{{json .HostConfig.SecurityOpt}}") == '["no-new-privileges"]'
            effective = inside("sh", "-c", "grep CapEff /proc/self/status").stdout.split()[-1]
            wanted = sum(1 << bit for bit in (0, 1, 3, 6, 7))
            assert int(effective, 16) == wanted
        finally:
            subprocess.run(["docker", "rm", "--force", "--volumes", name], capture_output=True, check=False)

    def test_a_build_does_not_pass_on_a_key_in_this_process_s_environment(
        self, tmp_path: Path, tag: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        secret = "sk-or-this-must-never-be-seen-in-an-image"
        monkeypatch.setenv("OPENROUTER_API_KEY", secret)
        backend = BACKEND.replace(
            '"fixture/__init__.py": b"VALUE = 3\\n"',
            '"fixture/__init__.py": b"import os\\nVALUE = dict(os.environ)\\n"',
        )
        files = {**OFFLINE, "backend.py": backend}
        repo = tree(tmp_path / "project", files)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        env.build_environment(repo, env.plan(repo), tag, env.Limits(10, 5), scratch)
        assert secret not in inspected(tag, "{{json .Config.Env}}")
        work = tmp_path / "work"
        work.mkdir()
        shown = DockerExecutor(image=tag, timeout=60).run(
            work, ["python", "-c", "import fixture; print(fixture.VALUE)"]
        )
        assert shown.succeeded, shown.stderr
        assert secret not in shown.stdout


@needs_docker
class TestLimits:
    """A build that goes over what it was allowed is stopped, and nothing of it stays."""

    def run(self, tmp_path: Path, command: tuple[str, ...], tag: str, **options: Any) -> Any:
        recipe = env.Recipe("pip", "3.12", "test", "python:3.12-slim", (), (), (env.Step("slow", "Do it", command),))
        watched = env.Builder(tmp_path, recipe, tag, options.pop("limits", env.Limits(5, 5)), **options)
        return watched

    def test_a_build_that_takes_too_long_is_stopped_as_a_timeout(self, tmp_path: Path, tag: str) -> None:
        watched = self.run(tmp_path, ("sleep", "120"), tag)
        watched.deadline = time.monotonic() + 8
        began = time.monotonic()
        with pytest.raises(EnvironmentBuildError) as caught:
            watched.run()
        assert caught.value.failure.kind == "timeout"
        assert caught.value.failure.step == "slow"
        assert time.monotonic() - began < 60
        assert env.image_id_of(tag) is None
        assert containers() == []

    def test_a_build_that_writes_too_much_is_stopped(
        self, tmp_path: Path, tag: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(env, "SIZE_SECONDS", 1.0)
        watched = self.run(
            tmp_path,
            ("sh", "-c", "dd if=/dev/zero of=/filler bs=1M count=64 2>/dev/null; sleep 120"),
            tag,
            limits=env.Limits(5, 0),
        )
        with pytest.raises(EnvironmentBuildError) as caught:
            watched.run()
        assert caught.value.failure.kind == "too_big"
        assert env.image_id_of(tag) is None
        assert containers() == []

    def test_a_build_that_is_stopped_keeps_nothing(self, tmp_path: Path, tag: str) -> None:
        stop = threading.Event()
        watched = self.run(tmp_path, ("sleep", "120"), tag, stop=stop)
        threading.Timer(4, stop.set).start()
        with pytest.raises(StoppedError):
            watched.run()
        assert env.image_id_of(tag) is None
        assert containers() == []

    def test_a_container_that_was_left_behind_is_found_by_whose_it_was(self, tmp_path: Path) -> None:
        stamp = time.time_ns()
        wanted = f"left-over-{stamp}"
        made = {f"{env.BUILD_PREFIX}{wanted}-{number:012d}": wanted for number in range(2)}
        # An agent whose id starts with another's, which a match on the name would take for the other's
        made[f"{env.BUILD_PREFIX}{wanted}-more-{0:012d}"] = f"{wanted}-more"
        made[f"{env.BUILD_PREFIX}someone-else-{stamp}"] = f"someone-else-{stamp}"
        for name, label in made.items():
            subprocess.run(
                ["docker", *env.create_arguments(name, "python:3.12-slim", label, env.cpus_for())],
                capture_output=True,
                check=True,
            )
        try:
            assert env.remove_builds(wanted) == 2
            remaining = set(containers())
            assert {name for name in made if made[name] == wanted}.isdisjoint(remaining)
            assert {name for name in made if made[name] != wanted} <= remaining
            assert env.remove_builds("") == 0
        finally:
            subprocess.run(["docker", "rm", "--force", *made], capture_output=True, check=False)

    def test_the_images_built_for_an_agent_are_found_by_the_label_they_carry(self, tmp_path: Path) -> None:
        stamp = time.time_ns()
        wanted = f"images-{stamp}"
        tags = {
            f"{env.IMAGE_REPOSITORY}:{wanted}-{'a' * 12}": wanted,
            f"{env.IMAGE_REPOSITORY}:{wanted}-more-{'b' * 12}": f"{wanted}-more",
        }
        for tagged, label in tags.items():
            name = f"{env.BUILD_PREFIX}{label}-{stamp}"
            subprocess.run(
                ["docker", *env.create_arguments(name, "python:3.12-slim", label, env.cpus_for())],
                capture_output=True,
                check=True,
            )
            subprocess.run(["docker", "commit", name, tagged], capture_output=True, check=True)
            subprocess.run(["docker", "rm", "--force", name], capture_output=True, check=False)
        try:
            assert env.remove_images(wanted) is True
            gone, kept = list(tags)
            assert env.image_id_of(gone) is None
            assert env.image_id_of(kept) is not None
            assert env.remove_images(wanted) is True
            assert env.remove_images("") is True
        finally:
            for tagged in tags:
                env.remove_image(tagged)
