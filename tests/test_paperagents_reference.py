"""Tests of the reference run: which tutorials would be run, what the runner inside the container records of one,
how what a run leaves behind is distrusted, how runs are compared and how a failure is told apart, the limits on the
runs, and, where Docker is there, that real runs keep to what they say: offline, with nothing of the machine to be
seen, the project copied and not changed, and time, disk, and stops that hold."""

import ast
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from test_paperagents_environment import PYPROJECT, needs_docker
from test_paperagents_stock import notebook, stock_of, tree

from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerUnavailableError
from virtual_lab.paperagents import environment as env
from virtual_lab.paperagents import reference as ref
from virtual_lab.paperagents.reference import Item, Limits, Runner

RUNNER = Path(ref.__file__).with_name(ref.RUNNER_FILE)

CORE = """
import random


def mean(values, scale=1.0):
    return sum(values) / len(values) * scale


def describe(values):
    return {"n": len(values), "mean": mean(values)}


def _hidden(x):
    return x


def numbers(n):
    for i in range(n):
        yield i


def jitter(x):
    return x + random.random()


def nonfinite(x):
    return {"a": float("nan"), "b": float("inf"), "c": x}


class Counter:
    def __init__(self, start):
        self.start = start

    def add(self, amount):
        return self.start + amount


def make_counter(start):
    return Counter(start)


def pair(a, b):
    return (a, b)
"""
PACKAGE = {"fixture/__init__.py": "from .core import *\n", "fixture/core.py": CORE}

# A backend that builds a wheel of the project's own folder, so that it is installed with nothing fetched
TREE_BACKEND = """
import os
import zipfile


def get_requires_for_build_wheel(config_settings=None):
    return []


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    dist = "fixture-0.1.dist-info"
    files = {}
    for current, _, names in os.walk("fixture"):
        for name in names:
            if name.endswith(".py"):
                path = os.path.join(current, name)
                with open(path, "rb") as handle:
                    files[path.replace(os.sep, "/")] = handle.read()
    files[dist + "/METADATA"] = b"Metadata-Version: 2.1\\nName: fixture\\nVersion: 0.1\\n"
    files[dist + "/WHEEL"] = b"Wheel-Version: 1.0\\nGenerator: backend\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n"
    name = "fixture-0.1-py3-none-any.whl"
    with zipfile.ZipFile(os.path.join(wheel_directory, name), "w") as wheel:
        for path, data in files.items():
            wheel.writestr(path, data)
        wheel.writestr(dist + "/RECORD", "".join(path + ",,\\n" for path in files) + dist + "/RECORD,,\\n")
    return name
"""
BASE = {
    "pyproject.toml": PYPROJECT,
    "backend.py": TREE_BACKEND,
    ".python-version": "3.12\n",
    "README.md": "# Fixture\n",
    **PACKAGE,
}

DEMO = """
import socket

import fixture

print(fixture.mean([1, 2, 3, 4]))
print(fixture.describe([1.0, 2.0]))
with open("out.txt", "w") as handle:
    handle.write("written beside it")
try:
    socket.create_connection(("1.1.1.1", 53), timeout=3)
    print("reached the network")
except OSError:
    print("no network")
"""
NOTEBOOK = notebook(
    [
        "%matplotlib inline\nimport fixture\ntotal = fixture.mean([2, 4])\nprint('total is', total)\ntotal",
        "!pip install anything",
        "counter = fixture.make_counter(5)\ncounter.add(2)",
    ],
    ["# A tutorial"],
)
EXAMPLES = {
    "examples/demo.py": DEMO,
    "examples/random_demo.py": "import fixture\nprint(fixture.jitter(1.0))\n",
    "examples/boom.py": "import fixture\nfixture.mean([1])\nraise ValueError('this tutorial breaks')\n",
    "examples/needs_net.py": "import urllib.request\nurllib.request.urlopen('https://example.com', timeout=5)\n",
    "examples/sleepy.py": "import time\nprint('started', flush=True)\ntime.sleep(120)\n",
    "examples/big.py": "import time\ntime.sleep(60)\n",
    "examples/changes_repo.py": "open('../README.md', 'w').write('changed')\nprint(open('../README.md').read())\n",
    "examples/data_demo.py": (
        "import os\n"
        "folder = os.environ.get('PAPER_DATA')\n"
        "print('data folder', folder)\n"
        "print(sorted(os.listdir(folder)) if folder else 'none')\n"
        "try:\n    open(os.path.join(folder, 'new.txt'), 'w')\n    print('wrote to the data')\n"
        "except OSError as error:\n    print('data is read only', type(error).__name__)\n"
    ),
    "examples/isolation.py": (
        "import os\n"
        "print('secrets', [key for key in os.environ if 'SECRET' in key])\n"
        "print('root', sorted(os.listdir('/')))\n"
        "print('workspace', sorted(os.listdir('/workspace')))\n"
        "try:\n    open('/etc/written', 'w')\n    print('wrote to the root')\n"
        "except OSError:\n    print('root is read only')\n"
    ),
    "tutorial.ipynb": NOTEBOOK,
}


def result_of(**changes: Any) -> dict[str, Any]:
    """What the runner writes of a run, as a run that went well and did nothing, with what is given in its place."""
    base: dict[str, Any] = {
        "schema": 1,
        "kind": "script",
        "path": "examples/demo.py",
        "python": "3.12.1",
        "ok": True,
        "error": None,
        "seconds": 0.5,
        "cells": [],
        "cells_total": 0,
        "calls": [],
        "calls_seen": 0,
        "files": [],
        "files_more": 0,
        "packages": ["fixture"],
    }

    return {**base, **changes}


def value_of(value: Any) -> dict[str, Any]:
    return {"type": type(value).__name__, "plain": True, "value": value}


def call_of(name: str, args: dict[str, Any], result: Any, number: int = 1) -> dict[str, Any]:
    return {
        "id": number,
        "module": "fixture.core",
        "function": name,
        "qualname": name,
        "method": False,
        "file": "fixture/core.py",
        "line": 1,
        "args": {key: value_of(value) for key, value in args.items()},
        "variadic": False,
        "result": value_of(result),
        "returned": True,
        "cell": None,
        "from": {"file": "examples/demo.py", "line": 3},
    }


def failure_of(kind: str, **changes: Any) -> dict[str, Any]:
    error = {"type": kind, "message": "bad", "traceback": [f"{kind}: bad"], "cell": None}

    return {**error, **changes}


@pytest.fixture
def processors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A runner asks Docker how many processors it has, which tests that run no container do not need to."""
    monkeypatch.setattr(env, "cpus_for", lambda *a, **k: "2")


class TestPlan:
    def test_python_scripts_and_notebooks_are_run_and_each_has_an_id_that_is_safe_as_a_name(
        self, tmp_path: Path
    ) -> None:
        found = stock_of(
            tmp_path,
            {
                "examples/Quick Start (v2).py": "print(1)\n",
                "tutorials/walk.ipynb": notebook(["x = 1"]),
                "README.md": "# Project\n",
            },
        )
        planned = ref.plan(found)

        assert [(item.path, item.kind) for item in planned.runnable] == [
            ("examples/Quick Start (v2).py", "script"),
            ("tutorials/walk.ipynb", "notebook"),
        ]
        assert [item.id for item in planned.runnable] == ["01-examples-quick-start-v2-py", "02-tutorials-walk-ipynb"]
        assert planned.skipped == () and planned.more == 0

    def test_what_is_not_python_is_listed_with_why(self, tmp_path: Path) -> None:
        found = stock_of(
            tmp_path,
            {
                "examples/run.R": "x <- 1\n",
                "examples/run.jl": "x = 1\n",
                "examples/run.sh": "echo hi\n",
                "examples/report.Rmd": "# report\n",
                "examples/r_notebook.ipynb": notebook(["x <- 1"], language="r"),
                "examples/ok.py": "x = 1\n",
            },
        )
        planned = ref.plan(found)

        assert [item.path for item in planned.runnable] == ["examples/ok.py"]
        reasons = {item["path"]: item["reason"] for item in planned.skipped}
        assert set(reasons) == {
            "examples/run.R",
            "examples/run.jl",
            "examples/run.sh",
            "examples/report.Rmd",
            "examples/r_notebook.ipynb",
        }
        assert "R" in reasons["examples/run.R"] and "Julia" in reasons["examples/run.jl"]
        assert "shell" in reasons["examples/run.sh"] and "Quarto" in reasons["examples/report.Rmd"]
        assert "notebook in R" in reasons["examples/r_notebook.ipynb"]
        assert all(item["reason"].endswith("only Python is run here.") for item in planned.skipped)

    def test_a_notebook_that_does_not_say_its_language_is_run_as_python(self, tmp_path: Path) -> None:
        bare = {"cells": [{"cell_type": "code", "source": ["x = 1"]}], "metadata": {}, "nbformat": 4}
        planned = ref.plan(stock_of(tmp_path, {"tutorials/bare.ipynb": bare}))

        assert [item.kind for item in planned.runnable] == ["notebook"]

    def test_tutorials_that_were_not_listed_are_counted(self) -> None:
        found = {
            "notebooks": {"count": 0, "listed": []},
            "tutorials": {
                "count": 40,
                "characters": 0,
                "listed": [{"path": "examples/a.py", "kind": "script", "bytes": 1, "characters": 1}],
            },
        }

        assert ref.plan(found).more == 39

    def test_a_name_that_is_not_letters_and_digits_cannot_make_a_place(self) -> None:
        assert ref.slug(3, "../../etc/passwd") == "03-etc-passwd"
        assert ref.slug(4, "///") == "04-tutorial"
        assert len(ref.slug(1, "a" * 500)) <= 53


class TestLimits:
    def test_what_is_left_out_is_the_default(self) -> None:
        assert ref.check_limits(None, None, None, None, None) == Limits()

    def test_what_is_given_is_taken(self) -> None:
        assert ref.check_limits(5, 60, 3, 1, 4) == Limits(5, 60, 3, 1, 4)

    @pytest.mark.parametrize("bad", [0, -1, 1.5, "5", True, 10_000, [3]])
    def test_a_number_that_is_not_a_whole_number_in_range_is_refused(self, bad: Any) -> None:
        for position in range(5):
            values: list[Any] = [None] * 5
            values[position] = bad
            with pytest.raises(ValueError, match="whole number from 1 to"):
                ref.check_limits(*values)

    def test_what_a_run_is_given_is_said(self) -> None:
        said = Limits().to_dict()
        assert said["memory"] == env.MEMORY and said["pids"] == env.PIDS and said["minutes"] == ref.DEFAULT_MINUTES


class TestClassify:
    def classify(self, error: dict[str, Any] | None = None, code: int | None = 1, text: str = "") -> dict[str, Any]:
        return ref.classify(error, code, text)

    @pytest.mark.parametrize(
        ("kind", "error"),
        [
            ("missing_package", failure_of("ModuleNotFoundError", message="No module named 'scanpy'")),
            ("missing_package", failure_of("ImportError", message="libGL.so.1: cannot open shared object file")),
            ("missing_file", failure_of("FileNotFoundError", message="[Errno 2] No such file: 'data/x.csv'")),
            ("needs_network", failure_of("URLError", message="<urlopen error [Errno -3] Name or service not known>")),
            ("needs_network", failure_of("ConnectionError", message="HTTPSConnectionPool: Max retries exceeded")),
            ("needs_gpu", failure_of("RuntimeError", message="Found no NVIDIA driver on your system")),
            ("needs_gpu", failure_of("AssertionError", message="Torch not compiled with CUDA enabled")),
            ("out_of_memory", failure_of("MemoryError", message="")),
            ("needs_notebook", failure_of("NameError", message="name 'get_ipython' is not defined")),
            ("notebook_unreadable", failure_of("NotebookUnreadable", message="Expecting value")),
            ("error", failure_of("ValueError", message="bad")),
        ],
    )
    def test_the_exception_says_what_kind_of_failure_it_is(self, kind: str, error: dict[str, Any]) -> None:
        found = self.classify(error)
        assert found["kind"] == kind and found["title"] == ref.TITLES[kind]
        assert found["kind"] in ref.FAILURE_KINDS

    def test_what_it_ended_with_and_printed_is_used_when_it_said_nothing_of_itself(self) -> None:
        assert self.classify(None, 137)["kind"] == "out_of_memory"
        assert self.classify(None, 1, "RuntimeError: Found no NVIDIA driver")["kind"] == "needs_gpu"
        assert (
            self.classify(None, 1, "socket.gaierror: Temporary failure in name resolution")["kind"] == "needs_network"
        )
        silent = self.classify(None, 3, "")
        assert silent["kind"] == "no_result" and "exit code was 3" in silent["detail"]

    def test_the_end_of_the_traceback_is_kept_for_the_person_to_read(self) -> None:
        error = failure_of("ValueError", traceback=[f"line {n}" for n in range(50)])
        found = self.classify(error)
        assert found["tail"][-1] == "line 49" and len(found["tail"]) == 20


class TestComparing:
    def marks(self, calls: str = "a", files: str = "b", output: str = "c") -> dict[str, str]:
        return {"calls": calls, "files": files, "output": output}

    def test_runs_that_did_the_same_agree(self) -> None:
        assert ref.compare(self.marks(), [self.marks()], True) == (True, [])

    def test_calls_or_files_that_differ_decide_that_they_do_not_agree(self) -> None:
        assert ref.compare(self.marks(), [self.marks(calls="x")], True) == (False, ["calls"])
        assert ref.compare(self.marks(), [self.marks(files="x")], True) == (False, ["files"])

    def test_what_was_printed_is_said_to_differ_and_does_not_decide(self) -> None:
        assert ref.compare(self.marks(), [self.marks(output="x")], True) == (True, ["output"])

    def test_a_later_run_that_did_not_end_well_is_a_difference(self) -> None:
        assert ref.compare(self.marks(), [None], True) == (False, ["status", "calls", "files", "output"])

    def test_runs_that_made_no_call_and_wrote_no_file_have_nothing_to_agree_on(self) -> None:
        assert ref.compare(self.marks(), [self.marks()], False) == (None, [])

    def test_a_single_run_is_compared_with_nothing(self) -> None:
        assert ref.compare(self.marks(), [], True) == (None, [])

    def test_the_digest_of_a_run_does_not_depend_on_the_order_keys_were_written_in(self) -> None:
        one = result_of(calls=[call_of("mean", {"a": 1, "b": 2}, 3.0)])
        other = result_of(calls=[call_of("mean", {"b": 2, "a": 1}, 3.0)])
        assert ref.digests_of(one, "") == ref.digests_of(other, "")
        assert ref.digests_of(one, "")["calls"] != ref.digests_of(result_of(), "")["calls"]


class TestShapes:
    def test_what_the_runner_writes_is_a_result(self) -> None:
        assert ref.valid_result(result_of(calls=[call_of("mean", {"values": [1]}, 1.0)]))

    @pytest.mark.parametrize(
        "change",
        [
            {"schema": 2},
            {"kind": "shell"},
            {"ok": "yes"},
            {"seconds": "fast"},
            {"calls": [{"id": 1}]},
            {"files": [{"path": "a"}]},
            {"cells": {"a": 1}},
            {"packages": "fixture"},
            {"error": {"type": 1, "message": "", "traceback": [], "cell": None}},
        ],
    )
    def test_what_is_not_in_that_shape_is_not(self, change: dict[str, Any]) -> None:
        assert not ref.valid_result(result_of(**change))

    def test_a_call_whose_values_are_not_described_is_not(self) -> None:
        bad = call_of("mean", {"values": [1]}, 1.0)
        bad["args"]["values"] = "a list"
        assert not ref.valid_result(result_of(calls=[bad]))
        bad = call_of("mean", {}, 1.0)
        bad["result"] = {"type": 3}
        assert not ref.valid_result(result_of(calls=[bad]))

    def test_a_result_with_more_than_the_runner_keeps_is_not_one(self) -> None:
        calls = [call_of("f", {}, 1, number) for number in range(ref.MAX_RESULT_CALLS + 1)]
        assert ref.valid_result(result_of(calls=calls[:-1])) and not ref.valid_result(result_of(calls=calls))
        files = [kept_file(f"f{number}.txt", b"") for number in range(ref.MAX_RESULT_FILES + 1)]
        assert ref.valid_result(result_of(files=files[:-1])) and not ref.valid_result(result_of(files=files))
        cell = {"index": 0, "ok": True, "seconds": 0.1, "output": "", "result": None, "skipped": [], "error": None}
        cells = [{**cell, "index": number} for number in range(ref.MAX_RESULT_CELLS + 1)]
        assert ref.valid_result(result_of(cells=cells[:-1])) and not ref.valid_result(result_of(cells=cells))

    def test_a_value_nested_deeper_than_the_runner_ever_makes_is_not_one_and_is_not_recursed_into(self) -> None:
        def nested(levels: int) -> list[Any]:
            value: list[Any] = []
            for _ in range(levels):
                value = [value]

            return value

        assert ref.valid_result(result_of(calls=[call_of("f", {}, nested(8))]))
        assert not ref.valid_result(result_of(calls=[call_of("f", {}, nested(ref.MAX_DEPTH))]))
        assert not ref.valid_result(result_of(calls=[call_of("f", {}, nested(100_000))]))
        assert ref.is_shallow(5) and ref.is_shallow({"a": [1, {"b": []}]}, 4)
        assert not ref.is_shallow({"a": [1, {"b": []}]}, 3)

    def test_a_tutorial_is_kept_only_under_an_id_made_of_its_place_and_its_name(self) -> None:
        assert ref.ITEM_ID.fullmatch(ref.slug(1, "examples/Quick Start (v2).py"))
        assert ref.ITEM_ID.fullmatch(ref.slug(12, "***"))
        for bad in ("", "..", "../x", "01-A", "a-01", "01/x", "01-x\n"):
            assert ref.ITEM_ID.fullmatch(bad) is None, bad

    def test_nothing_that_is_not_a_dictionary_is_a_result(self) -> None:
        for value in (None, [], "text", 3):
            assert not ref.valid_result(value)


def run_here(
    tmp_path: Path, files: dict[str, Any], kind: str, path: str, **variables: str
) -> tuple[dict[str, Any] | None, subprocess.CompletedProcess[str]]:
    """Runs the runner on this machine, on a project in a folder, which is how it is tested without a container."""
    repo = tree(tmp_path / "repo", files)
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    done = subprocess.run(
        [sys.executable, str(RUNNER), kind, path, "--repo", str(repo), "--work", str(work)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={**os.environ, **variables},
    )
    written = work / ref.RESULT_FOLDER / "result.json"
    result = json.loads(written.read_text()) if written.exists() else None
    if result is not None:
        assert ref.valid_result(result), result

    return result, done


def calls_of(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    assert result is not None
    return result["calls"]


class TestRunnerCalls:
    def test_a_call_to_the_projects_function_is_recorded_with_what_went_in_and_what_came_out(
        self, tmp_path: Path
    ) -> None:
        result, _ = run_here(
            tmp_path,
            {**BASE, "examples/a.py": "import fixture\nfixture.mean([1, 2, 3, 4], scale=2)\n"},
            "script",
            "examples/a.py",
        )
        assert result is not None and result["ok"]
        (call,) = calls_of(result)
        assert (call["module"], call["qualname"], call["method"]) == ("fixture.core", "mean", False)
        assert call["args"] == {"values": value_of([1, 2, 3, 4]), "scale": value_of(2)}
        assert call["result"] == {"type": "float", "plain": True, "value": 5.0}
        assert call["returned"] is True
        assert call["from"] == {"file": "examples/a.py", "line": 2}
        assert call["file"] == "fixture/core.py" and call["line"] == 5

    def test_a_call_the_project_makes_to_itself_is_not_recorded_but_is_counted_by_its_caller(
        self, tmp_path: Path
    ) -> None:
        result, _ = run_here(
            tmp_path,
            {**BASE, "examples/a.py": "import fixture\nfixture.describe([1.0, 2.0])\n"},
            "script",
            "examples/a.py",
        )
        assert [call["qualname"] for call in calls_of(result)] == ["describe"]

    def test_private_functions_generators_and_what_is_not_the_projects_are_not_recorded(self, tmp_path: Path) -> None:
        script = (
            "import json, fixture\nfrom fixture.core import _hidden\n_hidden(1)\nlist(fixture.numbers(3))\n"
            "json.dumps([1])\nsorted([3, 1], key=lambda x: x)\nfixture.mean([1])\n"
        )
        result, _ = run_here(tmp_path, {**BASE, "examples/a.py": script}, "script", "examples/a.py")
        assert [call["qualname"] for call in calls_of(result)] == ["mean"]

    def test_one_function_is_recorded_only_so_many_times_but_every_call_is_counted(self, tmp_path: Path) -> None:
        script = "import fixture\nfor n in range(20):\n    fixture.mean([n + 1])\n"
        result, _ = run_here(tmp_path, {**BASE, "examples/a.py": script}, "script", "examples/a.py")
        assert result is not None
        assert len(result["calls"]) == 4 and result["calls_seen"] == 20
        assert [call["id"] for call in result["calls"]] == [1, 2, 3, 4]

    def test_a_method_is_marked_and_its_object_is_not_described_as_an_argument(self, tmp_path: Path) -> None:
        script = "import fixture\ncounter = fixture.make_counter(5)\ncounter.add(2)\n"
        result, _ = run_here(tmp_path, {**BASE, "examples/a.py": script}, "script", "examples/a.py")
        made, added = calls_of(result)
        assert made["qualname"] == "make_counter" and made["method"] is False
        assert (added["qualname"], added["method"], list(added["args"])) == ("Counter.add", True, ["amount"])
        assert added["result"]["value"] == 7

    def test_a_value_that_is_not_json_is_described_without_an_address_that_changes_between_runs(
        self, tmp_path: Path
    ) -> None:
        script = "import fixture\nfixture.make_counter(1)\nfixture.pair(1, 2)\n"
        result, _ = run_here(tmp_path, {**BASE, "examples/a.py": script}, "script", "examples/a.py")
        made, paired = calls_of(result)
        assert made["result"]["plain"] is False and made["result"]["type"] == "fixture.core.Counter"
        assert made["result"]["repr"] == "<fixture.core.Counter object at 0x>"
        assert (paired["result"]["type"], paired["result"]["plain"]) == ("tuple", False)

    def test_a_number_that_is_not_finite_is_written_as_a_word_since_json_has_none(self, tmp_path: Path) -> None:
        script = "import fixture\nfixture.nonfinite(1.5)\n"
        result, _ = run_here(tmp_path, {**BASE, "examples/a.py": script}, "script", "examples/a.py")
        (call,) = calls_of(result)
        assert call["result"]["value"] == {"a": {"$float": "nan"}, "b": {"$float": "inf"}, "c": 1.5}

    def test_an_array_is_described_by_its_shape_a_hash_and_its_values(self, tmp_path: Path) -> None:
        numpy = {
            "numpy_like.py": (
                "import hashlib\n\n\nclass Array:\n    shape = (2, 2)\n    size = 4\n"
                "    class dtype:\n        kind = 'f'\n\n        def __str__(self):\n            return 'float64'\n"
                "    dtype = dtype()\n    nbytes = 32\n\n    def tobytes(self):\n        return b'x' * 32\n\n"
                "    def tolist(self):\n        return [[1.0, 2.0], [3.0, 4.0]]\n\n\n"
                "def make():\n    return Array()\n"
            ),
            "examples/a.py": "import numpy_like\nnumpy_like.make()\n",
        }
        result, _ = run_here(tmp_path, {**BASE, **numpy}, "script", "examples/a.py")
        (call,) = calls_of(result)
        shown = call["result"]
        assert shown["plain"] is False
        assert shown["shape"] == [2, 2] and shown["dtype"] == "float64"
        assert shown["values"] == [[1.0, 2.0], [3.0, 4.0]]
        assert len(shown["sha256"]) == 64

    def test_what_a_call_keeps_is_bounded(self, tmp_path: Path) -> None:
        script = "import fixture\nfixture.mean([1.5] * 200_000)\n"
        result, _ = run_here(tmp_path, {**BASE, "examples/a.py": script}, "script", "examples/a.py")
        (call,) = calls_of(result)
        assert call["args"]["values"]["plain"] is False and len(call["args"]["values"]["repr"]) <= 510
        assert len(json.dumps(call)) < 50_000


class TestRunnerScripts:
    def test_the_project_is_copied_so_that_a_tutorial_can_write_and_what_was_kept_is_not_changed(
        self, tmp_path: Path
    ) -> None:
        files = {
            **BASE,
            "examples/a.py": "open('../README.md', 'w').write('changed')\nopen('new.txt', 'w').write('x')\n",
        }
        result, _ = run_here(tmp_path, files, "script", "examples/a.py")
        assert result is not None and result["ok"]
        assert (tmp_path / "repo" / "README.md").read_text() == "# Fixture\n"
        assert [(file["path"], file["new"]) for file in result["files"]] == [
            ("README.md", False),
            ("examples/new.txt", True),
        ]

    def test_a_file_that_is_written_with_what_it_had_is_not_a_change(self, tmp_path: Path) -> None:
        files = {**BASE, "examples/a.py": "open('../README.md', 'w').write('# Fixture\\n')\n"}
        result, _ = run_here(tmp_path, files, "script", "examples/a.py")
        assert result is not None and result["files"] == []

    def test_files_that_were_written_are_listed_with_a_hash_and_the_small_ones_are_kept(self, tmp_path: Path) -> None:
        script = (
            "open('small.txt', 'w').write('hello')\nopen('big.bin', 'wb').write(b'x' * (2 << 20))\n"
            "import os\nos.makedirs('sub/deeper')\nopen('sub/deeper/c.txt', 'w').write('c')\n"
        )
        result, _ = run_here(tmp_path, {**BASE, "examples/a.py": script}, "script", "examples/a.py")
        assert result is not None
        listed = {file["path"]: file for file in result["files"]}
        assert set(listed) == {"examples/small.txt", "examples/big.bin", "examples/sub/deeper/c.txt"}
        assert listed["examples/small.txt"]["sha256"] == hashlib.sha256(b"hello").hexdigest()
        assert listed["examples/small.txt"]["kept"] is True and listed["examples/big.bin"]["kept"] is False
        kept = tmp_path / "work" / ref.RESULT_FOLDER / "files"
        assert (kept / "examples/small.txt").read_text() == "hello"
        assert not (kept / "examples/big.bin").exists()

    def test_a_script_that_raises_is_a_failure_with_the_end_of_its_traceback_and_none_of_the_runners_frames(
        self, tmp_path: Path
    ) -> None:
        script = "import fixture\n\n\ndef go():\n    raise ValueError('this breaks')\n\n\ngo()\n"
        result, done = run_here(tmp_path, {**BASE, "examples/a.py": script}, "script", "examples/a.py")
        assert result is not None and result["ok"] is False and done.returncode == 1
        error = result["error"]
        assert (error["type"], error["message"]) == ("ValueError", "this breaks")
        text = "\n".join(error["traceback"])
        assert "examples/a.py" in text and "go()" in text and "tutorial_runner" not in text and "runpy" not in text

    def test_calls_made_before_the_failure_are_kept(self, tmp_path: Path) -> None:
        script = "import fixture\nfixture.mean([1])\nraise ValueError('late')\n"
        result, _ = run_here(tmp_path, {**BASE, "examples/a.py": script}, "script", "examples/a.py")
        assert result is not None and not result["ok"]
        assert [call["qualname"] for call in result["calls"]] == ["mean"]

    def test_a_script_that_exits_with_a_code_is_a_failure_and_one_that_exits_with_none_is_not(
        self, tmp_path: Path
    ) -> None:
        bad, _ = run_here(
            tmp_path / "one", {**BASE, "examples/a.py": "import sys\nsys.exit(3)\n"}, "script", "examples/a.py"
        )
        good, _ = run_here(
            tmp_path / "two", {**BASE, "examples/a.py": "import sys\nsys.exit()\n"}, "script", "examples/a.py"
        )
        assert bad is not None and bad["ok"] is False and bad["error"]["type"] == "SystemExit"
        assert bad["error"]["message"] == "3"
        assert good is not None and good["ok"] is True

    def test_it_runs_from_its_own_folder_and_can_import_what_is_beside_it(self, tmp_path: Path) -> None:
        files = {
            **BASE,
            "examples/helper.py": "VALUE = 41\n",
            "examples/a.py": "import helper, os\nprint(helper.VALUE + 1, os.getcwd().endswith('examples'))\n",
        }
        result, done = run_here(tmp_path, files, "script", "examples/a.py")
        assert result is not None and result["ok"] and "42 True" in done.stdout

    def test_the_project_is_found_by_its_folders_in_the_top_and_in_src(self, tmp_path: Path) -> None:
        files = {
            "pkg/__init__.py": "",
            "src/inner/__init__.py": "def go(x):\n    return x\n",
            "toplevel.py": "def go(x):\n    return x\n",
            "setup.py": "",
            "docs/x.py": "",
            "examples/a.py": (
                "import sys\nsys.path.insert(0, '../src')\nimport inner, toplevel\ninner.go(1)\ntoplevel.go(2)\n"
            ),
        }
        result, _ = run_here(tmp_path, files, "script", "examples/a.py")
        assert result is not None
        assert result["packages"] == ["inner", "pkg", "toplevel"]
        assert [call["module"] for call in result["calls"]] == ["inner", "toplevel"]

    def test_it_ends_itself_when_the_time_it_was_told_of_is_over(self, tmp_path: Path) -> None:
        began = time.monotonic()
        result, done = run_here(
            tmp_path,
            {**BASE, "examples/a.py": "import time\ntime.sleep(60)\n"},
            "script",
            "examples/a.py",
            LUMI_TIME_LIMIT="1",
        )
        assert done.returncode == 124 and result is None
        assert time.monotonic() - began < 30

    def test_a_project_that_cannot_be_copied_is_a_failure_of_the_runner_and_says_so(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        done = subprocess.run(
            [sys.executable, str(RUNNER), "script", "a.py", "--repo", str(tmp_path / "nothing"), "--work", str(work)],
            capture_output=True,
            text=True,
            check=False,
        )
        result = json.loads((work / ref.RESULT_FOLDER / "result.json").read_text())
        assert done.returncode == 1 and result["ok"] is False and result["error"]["runner"] is True

    def test_the_runner_is_written_for_the_oldest_python_that_environments_are_built_for(self) -> None:
        source = RUNNER.read_text()
        ast.parse(source, feature_version=(3, 7))
        assert ":=" not in source and "match " not in source


class TestRunnerNotebooks:
    def run(self, tmp_path: Path, cells: list[str], **options: Any) -> tuple[dict[str, Any], str]:
        files = {**BASE, "tutorial.ipynb": notebook(cells, **options)}
        result, done = run_here(tmp_path, files, "notebook", "tutorial.ipynb")
        assert result is not None
        return result, done.stdout

    def test_cells_run_in_one_namespace_and_each_keeps_what_it_printed_and_its_last_value(self, tmp_path: Path) -> None:
        result, _ = self.run(tmp_path, ["x = 20", "print('x is', x)\nx + 1", "x = None\nx"], markdown=["# Title"])
        assert result["ok"] and result["cells_total"] == 3
        assert [(cell["index"], cell["ok"], cell["output"], cell["result"]) for cell in result["cells"]] == [
            (1, True, "", None),
            (2, True, "x is 20\n", "21"),
            (3, True, "", None),
        ]

    def test_magics_and_shell_lines_are_left_out_and_said_and_the_rest_runs(self, tmp_path: Path) -> None:
        result, _ = self.run(
            tmp_path,
            ["%matplotlib inline\nx = 1\n!pip install nothing\nprint(x)", "%%bash\necho hi", "%%time\ny = 2\nprint(y)"],
        )
        first, second, third = result["cells"]
        assert first["skipped"] == ["%matplotlib inline", "!pip install nothing"] and first["output"] == "1\n"
        assert second["skipped"] == ["%%bash"] and second["output"] == ""
        assert third["skipped"] == [] and third["output"] == "2\n"

    def test_it_stops_at_the_first_cell_that_fails_and_says_which(self, tmp_path: Path) -> None:
        result, _ = self.run(tmp_path, ["x = 1", "raise KeyError('a')", "print('never')"])
        assert result["ok"] is False and result["cells_total"] == 3
        assert [cell["ok"] for cell in result["cells"]] == [True, False]
        assert result["error"]["type"] == "KeyError" and result["error"]["cell"] == 1
        assert "never" not in json.dumps(result)
        assert any("<cell 2>" in line for line in result["error"]["traceback"])

    def test_a_cell_that_does_not_parse_fails_and_says_where(self, tmp_path: Path) -> None:
        result, _ = self.run(tmp_path, ["def broken(:\n    pass"])
        assert result["ok"] is False and result["error"]["type"] == "SyntaxError"

    def test_a_call_says_which_cell_made_it(self, tmp_path: Path) -> None:
        result, _ = self.run(tmp_path, ["import fixture", "fixture.mean([1, 3])"])
        (call,) = result["calls"]
        assert call["cell"] == 1 and call["result"]["value"] == 2.0

    def test_display_shows_what_it_is_given(self, tmp_path: Path) -> None:
        result, _ = self.run(tmp_path, ["display({'a': 1})"])
        assert result["cells"][0]["output"] == "{'a': 1}\n"

    def test_a_notebook_that_is_not_json_is_not_run_and_says_so(self, tmp_path: Path) -> None:
        files = {**BASE, "tutorial.ipynb": "this is not json"}
        result, _ = run_here(tmp_path, files, "notebook", "tutorial.ipynb")
        assert result is not None and result["ok"] is False and result["error"]["type"] == "NotebookUnreadable"

    def test_a_notebook_of_the_older_format_is_read_too(self, tmp_path: Path) -> None:
        old = {"worksheets": [{"cells": [{"cell_type": "code", "input": ["print(7)"]}]}], "nbformat": 3}
        result, _ = run_here(tmp_path, {**BASE, "tutorial.ipynb": old}, "notebook", "tutorial.ipynb")
        assert result is not None and result["ok"] and result["cells"][0]["output"] == "7\n"

    def test_what_a_cell_keeps_of_a_long_output_is_cut_and_says_so(self, tmp_path: Path) -> None:
        result, _ = self.run(tmp_path, ["print('x' * 100_000)"])
        assert len(result["cells"][0]["output"]) < 4100 and result["cells"][0]["output"].endswith("[cut]")


class Scripted(Runner):
    """A runner whose container is a function: it is given the folder of the run and does what a run would."""

    def __init__(
        self, *arguments: Any, plays: list[Callable[[Path], tuple[str, int | None, str]]], **options: Any
    ) -> None:
        super().__init__(*arguments, **options)
        self.plays = list(plays)
        self.folders: list[Path] = []
        self.seconds: list[float] = []

    def execute(self, folder: Path, item: Item, seconds: float) -> tuple[str, int | None, str]:
        self.folders.append(folder)
        self.seconds.append(seconds)
        assert (folder / ref.RUNNER_AT).is_file()
        return self.plays.pop(0)(folder)


def writes(result: dict[str, Any] | None, files: dict[str, bytes] | None = None, text: str = "printed") -> Any:
    def play(folder: Path) -> tuple[str, int | None, str]:
        where = folder / ref.RESULT_FOLDER
        where.mkdir()
        if result is not None:
            (where / "result.json").write_text(json.dumps(result))
        for name, data in (files or {}).items():
            (where / "files" / name).parent.mkdir(parents=True, exist_ok=True)
            (where / "files" / name).write_bytes(data)
        return "done", 0 if result is not None and result["ok"] else 1, text

    return play


def kept_file(path: str, data: bytes, **changes: Any) -> dict[str, Any]:
    return {
        "path": path,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "new": True,
        "kept": True,
    } | changes


ITEM = Item("01-examples-demo-py", "examples/demo.py", "script")


@pytest.mark.usefixtures("processors")
class TestRunning:
    def runner(self, tmp_path: Path, plays: list[Any], **options: Any) -> Scripted:
        scratch = tmp_path / "scratch"
        scratch.mkdir(exist_ok=True)
        return Scripted("image:tag", options.pop("limits", Limits(repeats=1)), scratch, plays=plays, **options)

    def test_a_run_that_went_well_is_ok_and_keeps_what_it_did_and_its_folder_is_removed(self, tmp_path: Path) -> None:
        data = b"hello"
        done = result_of(calls=[call_of("mean", {"values": [1]}, 1.0)], files=[kept_file("examples/out.txt", data)])
        runner = self.runner(tmp_path, [writes(done, {"examples/out.txt": data})])
        keep = tmp_path / "kept"
        outcome = runner.tutorial(ITEM, 60, keep)
        detail = outcome.detail
        assert ref.is_detail(detail)
        assert (detail["status"], detail["failure"], detail["python"]) == ("ok", None, "3.12.1")
        assert [call["qualname"] for call in detail["calls"]] == ["mean"]
        assert detail["files"][0]["kept"] is True and (keep / "examples/out.txt").read_bytes() == data
        assert detail["output"] == ["printed"] and detail["runs"][0]["digest"] is not None
        assert not runner.folders[0].exists()

    def test_a_run_that_raised_is_failed_and_says_why(self, tmp_path: Path) -> None:
        bad = result_of(ok=False, error=failure_of("FileNotFoundError", message="data/x.csv"))
        detail = self.runner(tmp_path, [writes(bad)]).tutorial(ITEM, 60).detail
        assert ref.is_detail(detail) and detail["status"] == "failed"
        assert detail["failure"]["kind"] == "missing_file" and detail["stable"] is None

    def test_a_run_that_wrote_no_result_is_failed_and_what_it_printed_is_what_there_is(self, tmp_path: Path) -> None:
        detail = self.runner(tmp_path, [writes(None, text="Killed")]).tutorial(ITEM, 60).detail
        assert detail["status"] == "failed" and detail["failure"]["kind"] == "no_result"
        assert detail["output"] == ["Killed"] and detail["calls"] == [] and detail["python"] is None

    def test_a_run_that_is_over_its_time_is_timed_out_and_its_files_are_not_trusted(self, tmp_path: Path) -> None:
        data = b"x"
        partial = result_of(files=[kept_file("a.txt", data)])

        def over(folder: Path) -> tuple[str, int | None, str]:
            writes(partial, {"a.txt": data})(folder)
            return "timed_out", None, "going"

        keep = tmp_path / "kept"
        detail = self.runner(tmp_path, [over]).tutorial(ITEM, 30, keep).detail
        assert detail["status"] == "timed_out" and detail["failure"]["kind"] == "timeout"
        assert "30 seconds" in detail["failure"]["detail"]
        assert not keep.exists()

    def test_a_run_that_wrote_too_much_is_stopped_and_says_so(self, tmp_path: Path) -> None:
        detail = (
            self.runner(tmp_path, [lambda folder: ("too_big", None, "")], limits=Limits(gigabytes=3))
            .tutorial(ITEM, 30)
            .detail
        )
        assert detail["status"] == "too_big" and "3 gigabytes" in detail["failure"]["detail"]

    def test_docker_failing_to_run_one_is_not_a_failure_of_the_tutorial(self, tmp_path: Path) -> None:
        runner = self.runner(tmp_path, [lambda folder: ("done", 125, "docker: Cannot connect to the Docker daemon")])
        with pytest.raises(DockerUnavailableError, match="Cannot connect to the Docker daemon"):
            runner.tutorial(ITEM, 30)
        assert not runner.folders[0].exists()

    def test_a_stopped_run_raises_and_leaves_nothing(self, tmp_path: Path) -> None:
        runner = self.runner(tmp_path, [lambda folder: ("stopped", None, "")])
        with pytest.raises(StoppedError):
            runner.tutorial(ITEM, 30)
        assert not runner.folders[0].exists()

    def test_a_file_that_is_not_what_the_run_said_is_not_kept(self, tmp_path: Path) -> None:
        files = [
            kept_file("good.txt", b"good"),
            kept_file("wrong-hash.txt", b"abc", sha256="0" * 64),
            kept_file("wrong-size.txt", b"abc", bytes=4),
            kept_file("../escape.txt", b"abc"),
            kept_file("/absolute.txt", b"abc"),
            kept_file("missing.txt", b"abc"),
            kept_file("too-big.bin", b"x" * 10, bytes=2 << 20),
        ]
        data = {
            "good.txt": b"good",
            "wrong-hash.txt": b"abc",
            "wrong-size.txt": b"abc",
            "../escape.txt": b"abc",
            "absolute.txt": b"abc",
        }
        keep = tmp_path / "kept"
        detail = self.runner(tmp_path, [writes(result_of(files=files), data)]).tutorial(ITEM, 60, keep).detail
        assert {file["path"]: file["kept"] for file in detail["files"]} == {
            "good.txt": True,
            "wrong-hash.txt": False,
            "wrong-size.txt": False,
            "../escape.txt": False,
            "/absolute.txt": False,
            "missing.txt": False,
            "too-big.bin": False,
        }
        assert sorted(path.name for path in keep.rglob("*") if path.is_file()) == ["good.txt"]
        assert not (tmp_path / "escape.txt").exists()

    def test_a_file_reached_through_a_link_is_not_kept(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_bytes(b"a secret of this machine")

        def play(folder: Path) -> tuple[str, int | None, str]:
            where = folder / ref.RESULT_FOLDER
            where.mkdir()
            (where / "files").mkdir()
            (where / "files" / "link.txt").symlink_to(outside / "secret.txt")
            (where / "files" / "folder").symlink_to(outside, target_is_directory=True)
            (where / "result.json").write_text(
                json.dumps(
                    result_of(
                        files=[
                            kept_file("link.txt", b"a secret of this machine"),
                            kept_file("folder/secret.txt", b"a secret of this machine"),
                        ]
                    )
                )
            )
            return "done", 0, ""

        keep = tmp_path / "kept"
        detail = self.runner(tmp_path, [play]).tutorial(ITEM, 60, keep).detail
        assert [file["kept"] for file in detail["files"]] == [False, False]
        assert not keep.exists() or not any(keep.rglob("*"))

    def test_a_folder_of_the_result_that_is_a_link_is_not_followed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        (outside / "files").mkdir(parents=True)
        (outside / "files" / "a.txt").write_bytes(b"data")
        (outside / "result.json").write_text(json.dumps(result_of(files=[kept_file("a.txt", b"data")])))

        def play(folder: Path) -> tuple[str, int | None, str]:
            (folder / ref.RESULT_FOLDER).symlink_to(outside, target_is_directory=True)
            return "done", 0, ""

        keep = tmp_path / "kept"
        detail = self.runner(tmp_path, [play]).tutorial(ITEM, 60, keep).detail
        assert detail["status"] == "failed" and detail["failure"]["kind"] == "no_result"
        assert not keep.exists()

    def test_a_result_that_is_a_link_or_too_big_or_not_json_is_not_read(self, tmp_path: Path) -> None:
        outside = tmp_path / "result.json"
        outside.write_text(json.dumps(result_of()))

        def link(folder: Path) -> tuple[str, int | None, str]:
            (folder / ref.RESULT_FOLDER).mkdir()
            (folder / ref.RESULT_FOLDER / "result.json").symlink_to(outside)
            return "done", 0, ""

        def big(folder: Path) -> tuple[str, int | None, str]:
            (folder / ref.RESULT_FOLDER).mkdir()
            (folder / ref.RESULT_FOLDER / "result.json").write_text(" " * (ref.MAX_RESULT_BYTES + 1))
            return "done", 0, ""

        def garbage(folder: Path) -> tuple[str, int | None, str]:
            (folder / ref.RESULT_FOLDER).mkdir()
            (folder / ref.RESULT_FOLDER / "result.json").write_text("{not json")
            return "done", 0, ""

        def deep(folder: Path) -> tuple[str, int | None, str]:
            (folder / ref.RESULT_FOLDER).mkdir()
            (folder / ref.RESULT_FOLDER / "result.json").write_text("[" * 200_000 + "]" * 200_000)
            return "done", 0, ""

        for play in (link, big, garbage, deep):
            detail = self.runner(tmp_path, [play]).tutorial(ITEM, 60).detail
            assert detail["status"] == "failed" and detail["failure"]["kind"] == "no_result"

    def test_a_folder_that_a_tutorial_made_unwritable_is_still_removed(self, tmp_path: Path) -> None:
        def play(folder: Path) -> tuple[str, int | None, str]:
            writes(result_of(), None)(folder)
            locked = folder / "repo" / "locked"
            locked.mkdir(parents=True)
            (locked / "f").write_text("x")
            locked.chmod(0o500)
            (folder / "repo").chmod(0o500)
            return "done", 0, ""

        runner = self.runner(tmp_path, [play])
        runner.tutorial(ITEM, 60)
        assert not runner.folders[0].exists()


@pytest.mark.usefixtures("processors")
class TestRepeating:
    def runner(self, tmp_path: Path, plays: list[Any], repeats: int = 2) -> Scripted:
        scratch = tmp_path / "scratch"
        scratch.mkdir(exist_ok=True)
        return Scripted("image:tag", Limits(repeats=repeats), scratch, plays=plays)

    def same(self) -> Any:
        return writes(result_of(calls=[call_of("mean", {"values": [1, 2]}, 1.5)]))

    def test_runs_that_agree_are_said_to_be_stable(self, tmp_path: Path) -> None:
        detail = self.runner(tmp_path, [self.same(), self.same()]).tutorial(ITEM, 60).detail
        assert detail["stable"] is True and detail["differs"] == [] and len(detail["runs"]) == 2

    def test_runs_that_differ_in_what_the_function_gave_are_not_and_say_which(self, tmp_path: Path) -> None:
        other = writes(result_of(calls=[call_of("mean", {"values": [1, 2]}, 1.6)]))
        detail = self.runner(tmp_path, [self.same(), other]).tutorial(ITEM, 60).detail
        assert detail["stable"] is False and detail["differs"] == ["calls"]

    def test_a_run_that_fails_the_second_time_is_not_stable(self, tmp_path: Path) -> None:
        failed = writes(result_of(ok=False, error=failure_of("ValueError")))
        detail = self.runner(tmp_path, [self.same(), failed]).tutorial(ITEM, 60).detail
        assert detail["stable"] is False and detail["differs"][0] == "status"
        assert [run["status"] for run in detail["runs"]] == ["ok", "failed"]
        assert detail["status"] == "ok"

    def test_a_run_that_failed_the_first_time_is_not_run_again(self, tmp_path: Path) -> None:
        failed = writes(result_of(ok=False, error=failure_of("ValueError")))
        runner = self.runner(tmp_path, [failed])
        assert runner.tutorial(ITEM, 60).detail["runs"][0]["status"] == "failed"
        assert len(runner.folders) == 1

    def test_the_most_it_is_run_is_what_was_allowed(self, tmp_path: Path) -> None:
        runner = self.runner(tmp_path, [self.same()] * 3, repeats=3)
        assert len(runner.tutorial(ITEM, 60).detail["runs"]) == 3
        runner = self.runner(tmp_path, [self.same()], repeats=1)
        detail = runner.tutorial(ITEM, 60).detail
        assert len(detail["runs"]) == 1 and detail["stable"] is None

    def test_what_is_printed_differing_does_not_make_them_unstable(self, tmp_path: Path) -> None:
        one = writes(result_of(calls=[call_of("mean", {"values": [1]}, 1.0)]), text="took 1.2 s")
        two = writes(result_of(calls=[call_of("mean", {"values": [1]}, 1.0)]), text="took 1.3 s")
        detail = self.runner(tmp_path, [one, two]).tutorial(ITEM, 60).detail
        assert detail["stable"] is True and detail["differs"] == ["output"]

    def test_runs_that_did_nothing_that_is_recorded_have_nothing_to_agree_on(self, tmp_path: Path) -> None:
        detail = self.runner(tmp_path, [writes(result_of()), writes(result_of())]).tutorial(ITEM, 60).detail
        assert detail["stable"] is None

    def test_a_repeat_is_not_started_when_too_little_of_the_time_is_left(self, tmp_path: Path) -> None:
        runner = self.runner(tmp_path, [self.same(), self.same()])
        detail = runner.tutorial(ITEM, 60, until=time.monotonic() + 5).detail
        assert len(detail["runs"]) == 1

    def test_a_repeat_is_given_no_more_than_the_time_that_is_left(self, tmp_path: Path) -> None:
        runner = self.runner(tmp_path, [self.same(), self.same()])
        runner.tutorial(ITEM, 600, until=time.monotonic() + 100)
        assert runner.seconds[0] == 600 and 90 < runner.seconds[1] <= 100

    def test_only_the_first_run_keeps_files(self, tmp_path: Path) -> None:
        data = b"hello"
        play = writes(result_of(files=[kept_file("a.txt", data)]), {"a.txt": data})
        keep = tmp_path / "kept"
        self.runner(tmp_path, [play, play]).tutorial(ITEM, 60, keep)
        assert [path.name for path in keep.rglob("*") if path.is_file()] == ["a.txt"]


@pytest.mark.usefixtures("processors")
class TestAllOfThem:
    def items(self, count: int) -> list[Item]:
        return [Item(ref.slug(n, f"examples/t{n}.py"), f"examples/t{n}.py", "script") for n in range(1, count + 1)]

    def go(self, runner: Scripted, items: list[Item]) -> tuple[list[tuple[str, str]], list[dict[str, str]]]:
        events: list[tuple[str, str]] = []
        not_run = ref.run_reference(
            runner,
            items,
            lambda item, number, total: events.append(("start", f"{number}/{total} {item.path}")),
            lambda item, outcome: events.append(("done", f"{item.path} {outcome.detail['status']}")),
            lambda item: None,
        )

        return events, not_run

    def runner(self, tmp_path: Path, count: int, **limits: Any) -> Scripted:
        scratch = tmp_path / "scratch"
        scratch.mkdir(exist_ok=True)
        return Scripted(
            "image:tag", Limits(repeats=1, **limits), scratch, plays=[writes(result_of()) for _ in range(count)]
        )

    def test_each_is_run_in_turn_and_reported_as_it_ends(self, tmp_path: Path) -> None:
        events, not_run = self.go(self.runner(tmp_path, 2), self.items(2))
        assert events == [
            ("start", "1/2 examples/t1.py"),
            ("done", "examples/t1.py ok"),
            ("start", "2/2 examples/t2.py"),
            ("done", "examples/t2.py ok"),
        ]
        assert not_run == []

    def test_no_more_are_run_than_were_allowed_and_the_rest_are_listed(self, tmp_path: Path) -> None:
        runner = self.runner(tmp_path, 5, tutorials=2)
        events, not_run = self.go(runner, self.items(5))
        assert [event for event in events if event[0] == "done"] == [
            ("done", "examples/t1.py ok"),
            ("done", "examples/t2.py ok"),
        ]
        assert [item["path"] for item in not_run] == ["examples/t3.py", "examples/t4.py", "examples/t5.py"]
        assert "Only 2 tutorials" in not_run[0]["reason"]

    def test_the_time_for_all_of_them_is_not_exceeded_and_those_left_are_listed(self, tmp_path: Path) -> None:
        clock = [1000.0]
        runner = self.runner(tmp_path, 3, total_minutes=1, minutes=1)
        runner.clock = lambda: clock[0]

        def slow(folder: Path) -> tuple[str, int | None, str]:
            clock[0] += 50
            return writes(result_of())(folder)

        runner.plays = [slow, slow, slow]
        events, not_run = self.go(runner, self.items(3))
        assert [event[1] for event in events if event[0] == "done"] == ["examples/t1.py ok"]
        assert [item["path"] for item in not_run] == ["examples/t2.py", "examples/t3.py"]
        assert "1 minutes for all" in not_run[0]["reason"]
        assert runner.seconds == [60]

    def test_each_is_given_no_more_than_the_time_that_is_left(self, tmp_path: Path) -> None:
        clock = [0.0]
        runner = self.runner(tmp_path, 2, total_minutes=2, minutes=10)
        runner.clock = lambda: clock[0]

        def slow(folder: Path) -> tuple[str, int | None, str]:
            clock[0] += 60
            return writes(result_of())(folder)

        runner.plays = [slow, slow]
        self.go(runner, self.items(2))
        assert runner.seconds == [120, 60]

    def test_a_stop_before_one_starts_raises_and_what_was_done_was_reported(self, tmp_path: Path) -> None:
        runner = self.runner(tmp_path, 2)
        events: list[str] = []

        def done(item: Item, outcome: ref.Outcome) -> None:
            events.append(item.path)
            runner.stop.set()

        with pytest.raises(StoppedError):
            ref.run_reference(runner, self.items(2), lambda *a: None, done, lambda item: None)
        assert events == ["examples/t1.py"] and len(runner.folders) == 1


@pytest.mark.usefixtures("processors")
class TestCommand:
    def command(self, tmp_path: Path, **options: Any) -> tuple[str, ...]:
        scratch = tmp_path / "scratch"
        scratch.mkdir(exist_ok=True)
        runner = Runner("image:tag", Limits(), scratch, **options)
        folder = tmp_path / "folder"
        folder.mkdir(exist_ok=True)

        return runner.command(folder, Item("01-a", "examples/a.py", "script"), 100, "virtual-lab-run-x")

    def test_it_is_run_with_no_network_a_root_that_cannot_be_written_and_no_capabilities(self, tmp_path: Path) -> None:
        command = self.command(tmp_path)
        text = " ".join(command)
        assert "--network none" in text and "--read-only" in text
        assert "--cap-drop ALL" in text and "--security-opt no-new-privileges" in text
        assert "--memory 8g" in text and "--pids-limit 1024" in text and "--cpus 2" in text
        assert "--cap-add" not in text and "--privileged" not in text and "--volume" not in text

    def test_it_is_given_only_its_own_folder_and_no_variable_of_this_process(self, tmp_path: Path) -> None:
        command = self.command(tmp_path)
        mounts = [part for part in command if part.startswith("type=bind")]
        assert len(mounts) == 1 and f"source={tmp_path / 'folder'}" in mounts[0] and "readonly" not in mounts[0]
        assert "--env" in command and not any("KEY" in part or "TOKEN" in part for part in command)
        assert "LUMI_TIME_LIMIT=130" in command and "PYTHONHASHSEED=0" in command and "MPLBACKEND=Agg" in command
        assert command[-5:] == ("image:tag", "python", "/workspace/" + ref.RUNNER_AT, "script", "examples/a.py")

    def test_data_is_given_to_read_and_not_to_write_and_the_runner_is_told_where(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        data.mkdir()
        command = self.command(tmp_path, data=data)
        mounts = [part for part in command if part.startswith("type=bind")]
        assert len(mounts) == 2
        assert f"source={data.resolve()},target={ref.DATA_PATH},readonly" in mounts[1]
        assert f"PAPER_DATA={ref.DATA_PATH}" in command

    def test_without_data_there_is_no_variable_that_says_where_it_is(self, tmp_path: Path) -> None:
        assert not any(part.startswith("PAPER_DATA") for part in self.command(tmp_path))

    def test_the_container_is_labelled_with_whose_it_is_so_that_one_that_is_left_can_be_found(
        self, tmp_path: Path
    ) -> None:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        runner = Runner("image:tag", Limits(), scratch, label="abc-1")
        folder = tmp_path / "folder"
        folder.mkdir()
        command = runner.command(folder, ITEM, 10, "virtual-lab-run-x")
        at = command.index("--label")
        assert command[at - 1] == "run" and command[at + 1] == f"{env.AGENT_LABEL}=abc-1"

    def test_a_label_that_is_not_lower_case_letters_digits_and_hyphens_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="label"):
            Runner("image:tag", Limits(), tmp_path, label="Not Allowed")


@pytest.fixture(scope="module")
def image(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """An image of the fixture project, built as environments are, which every real run below is made in."""
    work = tmp_path_factory.mktemp("image")
    repo = tree(work / "project", {**BASE, **EXAMPLES})
    scratch = work / "scratch"
    scratch.mkdir()
    tag = f"virtual-lab-paperagent:reference-{time.time_ns()}"
    env.build_environment(repo, env.plan(repo), tag, env.Limits(10, 5), scratch)
    try:
        yield tag
    finally:
        env.remove_image(tag)


def run_ids(label: str) -> list[str]:
    done = subprocess.run(
        ["docker", "ps", "--all", "--filter", f"label={env.AGENT_LABEL}={label}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.split()


def tutorial(path: str) -> Item:
    return Item(ref.slug(1, path), path, "notebook" if path.endswith(".ipynb") else "script")


@needs_docker
class TestInContainers:
    """Runs that are real, in Docker, of the fixture project that was built into an image."""

    def runner(self, image: str, tmp_path: Path, **options: Any) -> Runner:
        scratch = tmp_path / "scratch"
        scratch.mkdir(exist_ok=True)
        return Runner(image, options.pop("limits", Limits(repeats=2)), scratch, label="reftest", **options)

    def test_a_tutorial_is_run_and_what_it_did_is_kept_and_a_second_run_agrees(
        self, image: str, tmp_path: Path
    ) -> None:
        keep = tmp_path / "kept"
        detail = self.runner(image, tmp_path).tutorial(tutorial("examples/demo.py"), 120, keep).detail
        assert ref.is_detail(detail)
        assert detail["status"] == "ok" and detail["failure"] is None and detail["python"].startswith("3.12.")
        assert [call["qualname"] for call in detail["calls"]] == ["mean", "describe"]
        assert detail["calls"][0]["result"]["value"] == 2.5 and detail["calls"][1]["result"]["value"] == {
            "n": 2,
            "mean": 1.5,
        }
        assert detail["calls"][0]["module"] == "fixture.core" and detail["calls"][0]["file"] == "fixture/core.py"
        assert [(file["path"], file["kept"]) for file in detail["files"]] == [("examples/out.txt", True)]
        assert (keep / "examples/out.txt").read_text() == "written beside it"
        assert detail["stable"] is True and len(detail["runs"]) == 2 and detail["differs"] == []
        assert "no network" in "\n".join(detail["output"]) and "reached the network" not in "\n".join(detail["output"])
        assert run_ids("reftest") == []

    def test_the_second_run_starts_from_the_project_as_it_was_built_and_not_from_the_first(
        self, image: str, tmp_path: Path
    ) -> None:
        runner = self.runner(image, tmp_path, limits=Limits(repeats=1))
        first = runner.tutorial(tutorial("examples/changes_repo.py"), 120).detail
        second = runner.tutorial(tutorial("examples/changes_repo.py"), 120).detail
        assert first["output"] == second["output"] == ["changed"]
        assert [file["path"] for file in first["files"]] == ["README.md"]

    def test_a_tutorial_that_gives_something_else_each_time_is_not_stable(self, image: str, tmp_path: Path) -> None:
        detail = self.runner(image, tmp_path).tutorial(tutorial("examples/random_demo.py"), 120).detail
        assert detail["status"] == "ok" and detail["stable"] is False and "calls" in detail["differs"]

    def test_a_tutorial_that_raises_is_failed_with_what_it_said_and_the_calls_before_it(
        self, image: str, tmp_path: Path
    ) -> None:
        detail = self.runner(image, tmp_path).tutorial(tutorial("examples/boom.py"), 120).detail
        assert detail["status"] == "failed" and detail["failure"]["kind"] == "error"
        assert "this tutorial breaks" in detail["failure"]["detail"]
        assert [call["qualname"] for call in detail["calls"]] == ["mean"] and len(detail["runs"]) == 1

    def test_a_tutorial_that_needs_the_network_says_so(self, image: str, tmp_path: Path) -> None:
        detail = self.runner(image, tmp_path).tutorial(tutorial("examples/needs_net.py"), 120).detail
        assert detail["status"] == "failed" and detail["failure"]["kind"] == "needs_network"

    def test_a_notebook_is_run_cell_by_cell(self, image: str, tmp_path: Path) -> None:
        detail = self.runner(image, tmp_path).tutorial(tutorial("tutorial.ipynb"), 120).detail
        assert detail["status"] == "ok" and detail["cells_total"] == 3 and len(detail["cells"]) == 3
        assert detail["cells"][0]["output"] == "total is 3.0\n" and detail["cells"][0]["result"] == "3.0"
        assert detail["cells"][0]["skipped"] == ["%matplotlib inline"]
        assert detail["cells"][1]["skipped"] == ["!pip install anything"]
        assert [call["qualname"] for call in detail["calls"]] == ["mean", "make_counter", "Counter.add"]
        assert [call["cell"] for call in detail["calls"]] == [1, 3, 3]
        assert detail["stable"] is True

    def test_a_tutorial_that_runs_too_long_is_stopped_and_nothing_is_left_running(
        self, image: str, tmp_path: Path
    ) -> None:
        began = time.monotonic()
        detail = self.runner(image, tmp_path).tutorial(tutorial("examples/sleepy.py"), 4).detail
        assert detail["status"] == "timed_out" and detail["failure"]["kind"] == "timeout"
        assert "started" in "\n".join(detail["output"])
        assert time.monotonic() - began < 60
        assert run_ids("reftest") == []

    def test_a_tutorial_that_writes_more_than_is_allowed_is_stopped(
        self, image: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ref, "SIZE_SECONDS", 0.5)
        monkeypatch.setattr(ref, "folder_size", lambda folder: 5 * 1024**3)
        detail = self.runner(image, tmp_path).tutorial(tutorial("examples/big.py"), 60).detail
        assert detail["status"] == "too_big" and detail["failure"]["kind"] == "too_big"
        assert run_ids("reftest") == []

    def test_a_stop_ends_the_run_and_raises(self, image: str, tmp_path: Path) -> None:
        runner = self.runner(image, tmp_path)
        threading.Timer(4, runner.stop.set).start()
        with pytest.raises(StoppedError):
            runner.tutorial(tutorial("examples/sleepy.py"), 120)
        assert run_ids("reftest") == []
        assert list((tmp_path / "scratch").iterdir()) == []

    def test_nothing_of_this_machine_is_to_be_seen_from_inside(
        self, image: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LUMI_TEST_SECRET", "do-not-pass-on")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-not-for-code")
        detail = (
            self.runner(image, tmp_path, limits=Limits(repeats=1))
            .tutorial(tutorial("examples/isolation.py"), 120)
            .detail
        )
        printed = "\n".join(detail["output"])
        assert "secrets []" in printed and "do-not-pass-on" not in printed and "sk-not-for-code" not in printed
        assert "root is read only" in printed
        root = next(line for line in detail["output"] if line.startswith("root "))
        assert "Users" not in root and "Volumes" not in root and "workspace" in root
        assert "workspace ['.lumi-result', '.lumi-runner.py', 'repo']" in printed

    def test_data_is_there_to_read_and_cannot_be_written(self, image: str, tmp_path: Path) -> None:
        data = tmp_path / "data"
        (data / "zenodo-1").mkdir(parents=True)
        (data / "zenodo-1" / "table.csv").write_text("a,b\n1,2\n")
        runner = self.runner(image, tmp_path, data=data, limits=Limits(repeats=1))
        detail = runner.tutorial(tutorial("examples/data_demo.py"), 120).detail
        printed = "\n".join(detail["output"])
        assert f"data folder {ref.DATA_PATH}" in printed and "['zenodo-1']" in printed
        assert "data is read only" in printed and "wrote to the data" not in printed
        assert not (data / "new.txt").exists()

    def test_a_tutorial_that_asks_for_data_that_was_not_given_finds_no_folder(self, image: str, tmp_path: Path) -> None:
        detail = (
            self.runner(image, tmp_path, limits=Limits(repeats=1))
            .tutorial(tutorial("examples/data_demo.py"), 120)
            .detail
        )
        assert detail["status"] == "failed" and "data folder None" in "\n".join(detail["output"])

    def test_containers_that_were_left_by_a_server_that_was_stopped_are_found_and_removed(self, image: str) -> None:
        name = f"{ref.RUN_PREFIX}left-{time.time_ns()}"
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                name,
                "--label",
                f"{env.AGENT_LABEL}=left-over",
                image,
                "sleep",
                "300",
            ],
            capture_output=True,
            check=True,
        )
        try:
            assert run_ids("left-over") == [name]
            assert ref.remove_runs("left-over") == 1
            assert run_ids("left-over") == []
            assert ref.remove_runs("left-over") == 0
        finally:
            subprocess.run(["docker", "rm", "--force", name], capture_output=True, check=False)

    def test_what_is_not_a_label_removes_nothing(self) -> None:
        assert ref.remove_runs("") == 0 and ref.remove_runs("Not A Label") == 0
