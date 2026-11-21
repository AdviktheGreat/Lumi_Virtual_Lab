"""Tests of making a package of a PaperAgent's tools and of the server that is in it: what the package holds and
that it is the same each time, what it does not hold, what is flagged of a license first, the Dockerfile and the
lock, and that the server, run as it is after the package is unpacked, speaks the protocol, calls the authors'
function, holds what it gives to what the tutorial got, and says when a file of the package is not as it was made.
The server is run by this machine's Python, and once in a container, if there is Docker and an image to run it in."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from virtual_lab.paperagents import comparing, exporting
from virtual_lab.paperagents import toolmaking as making

WRAPPER = '''def tally(counts: list[int], scale: int = 1) -> int:
    """Adds up counts.

    :param counts: The counts.
    :param scale: What the sum is multiplied by.
    """
    import calc.mapping as _repo
    return _repo.tally(counts=counts, scale=scale)
'''
SCALE = '''def scaled(values: list[float], factor: float) -> list[float]:
    """Multiplies each value.

    :param values: The values.
    :param factor: What each is multiplied by.
    """
    import calc.mapping as _repo
    return _repo.scaled(values=values, factor=factor)
'''
MAPPING = """import os


def tally(counts, scale=1):
    print("adding", len(counts))
    return sum(counts) * scale


def scaled(values, factor):
    return [value * factor for value in values]


def read_note():
    return open("note.txt").read()


def leaves_a_file(counts):
    open("left.txt", "w").write("x")
    return os.listdir(".")
"""
PAPER_SENTENCE = "The mapper separates cells of the mouse brain better than any method before it."
COMMIT = "a" * 40
SHA = "sha256:" + "b" * 64
EXPECTED_SCALED = {"type": "list", "plain": True, "value": [0.5, 1.0, 1.5]}


def case_of(args: dict[str, Any], expected: dict[str, Any], cwd: str = ".") -> dict[str, Any]:
    return {
        "call": 1,
        "tutorial": "tutorial.py",
        "cell": None,
        "origin": {},
        "cwd": cwd,
        "args": args,
        "expected": expected,
        "repeats": 2,
        "matched": 2,
        "verdict": "match",
        "differences": [],
        "got": None,
        "error": None,
    }


def tool_of(name: str, function: str, source: str, cases: list[dict[str, Any]], tier: str = "A") -> dict[str, Any]:
    return {
        "schema": 1,
        "name": name,
        "tier": "A",
        "repo": {"module": "calc.mapping", "function": function, "file": "calc/mapping.py", "line": 1},
        "wrapper": "wrapper.py",
        "wrapper_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "signature": [],
        "description": "",
        "evidence": {
            "kind": "reference_run",
            "image_id": SHA,
            "tolerance": {"relative": 1e-6, "absolute": 1e-9},
            "repeats": 2,
            "checked": len(cases),
            "recorded": len(cases),
            "cases": cases,
            "skipped": [],
            "repairs": [],
        },
        "source": source,
        "now": {"tier": tier, "passed": ["heldout", "paper_numbers"] if tier == "B" else []},
    }


TALLY = tool_of(
    "tally", "tally", WRAPPER, [case_of({"counts": [1, 2, 3], "scale": 2}, {"type": "int", "plain": True, "value": 12})]
)
NOTE_WRAPPER = '''def read_note() -> str:
    """Reads the note."""
    import calc.mapping as _repo
    return _repo.read_note()
'''
NOTE = tool_of(
    "read_note",
    "read_note",
    NOTE_WRAPPER,
    [case_of({}, {"type": "str", "plain": True, "value": "hello"}, cwd="docs")],
)
SCALED = tool_of("scaled", "scaled", SCALE, [case_of({"values": [1.0, 2.0, 3.0], "factor": 0.5}, EXPECTED_SCALED)])


def repo_in(folder: Path) -> Path:
    repo = folder / "repo"
    (repo / "calc").mkdir(parents=True, exist_ok=True)
    (repo / "calc" / "__init__.py").write_text("")
    (repo / "calc" / "mapping.py").write_text(MAPPING)
    (repo / "LICENSE").write_text("MIT License\n")
    (repo / "run.sh").write_text("#!/bin/sh\n")
    (repo / "run.sh").chmod(0o755)

    return repo


def source_in(folder: Path, **changes: Any) -> exporting.Source:
    pieces: dict[str, Any] = {
        "agent_id": "calc",
        "title": "Calc: a mapper",
        "paper": {"kind": "doi", "doi": "10.1000/calc"},
        "intake": {
            "url": "https://github.com/example/calc",
            "commit": COMMIT,
            "ref": "HEAD",
            "cloned_at": "2025-01-01T00:00:00Z",
            "stock": {"license": {"files": ["LICENSE"], "name": "MIT", "kind": "permissive", "from": "file"}},
        },
        "environment": {
            "python": "3.11.9",
            "recipe": {"kind": "pip", "base_image": "python:3.11-slim", "system_packages": []},
            "lock": {"name": "pip-freeze.txt", "packages": 2},
            "image": {"tag": "virtual-lab-paperagent:calc", "id": SHA},
        },
        "lock": "numpy==1.26.4\ncalc @ file:///opt/paper/repo\n# a comment\n-e /opt/x\n\nscipy==1.11.0\n",
        "tools": [TALLY, SCALED],
        "repo": repo_in(folder),
        "data": False,
        "made_at": "2025-02-02T00:00:00Z",
    }
    pieces.update(changes)

    return exporting.Source(**pieces)


@pytest.fixture
def built(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    target = tmp_path / "package.zip"
    manifest = exporting.build_package(source_in(tmp_path), target)

    return target, manifest


@pytest.fixture
def unpacked(tmp_path: Path, built: tuple[Path, dict[str, Any]]) -> Path:
    return exporting.unpack(built[0], tmp_path / "out")


class TestWhatIsMade:
    def test_it_holds_the_code_the_wrappers_the_lock_and_what_a_person_needs(
        self, built: tuple[Path, dict[str, Any]]
    ) -> None:
        target, manifest = built

        with zipfile.ZipFile(target) as archive:
            names = set(archive.namelist())

        root = manifest["name"]
        assert root == "calc-a-mapper-aaaaaaa"
        assert {
            f"{root}/{name}"
            for name in (
                "README.md",
                "package.json",
                "Dockerfile",
                "requirements.lock.txt",
                "mcp_server.py",
                "tool_runner.py",
                "lumi_record.py",
                "tools/tally/wrapper.py",
                "tools/tally/tool.json",
                "tools/scaled/wrapper.py",
                "repo/calc/mapping.py",
                "repo/LICENSE",
            )
        } <= names
        assert all(name.startswith(f"{root}/") for name in names)

    def test_a_long_title_is_cut_in_the_name_of_the_package(self) -> None:
        name = exporting.package_name("A very long title " * 10, COMMIT)

        assert name == "a-very-long-title-a-very-long-title-a-ve-aaaaaaa"
        assert exporting.package_name("???", COMMIT) == "paperagent-aaaaaaa"

    def test_it_is_the_same_each_time(self, tmp_path: Path) -> None:
        first = exporting.build_package(source_in(tmp_path), tmp_path / "one.zip")
        second = exporting.build_package(source_in(tmp_path), tmp_path / "two.zip")

        assert first == second
        assert (tmp_path / "one.zip").read_bytes() == (tmp_path / "two.zip").read_bytes()

    def test_each_file_is_hashed_in_the_manifest_and_the_code_by_one_hash(
        self, built: tuple[Path, dict[str, Any]], unpacked: Path
    ) -> None:
        manifest = json.loads((unpacked / "package.json").read_text())

        assert manifest == built[1]
        for name, digest in manifest["files"].items():
            assert hashlib.sha256((unpacked / name).read_bytes()).hexdigest() == digest
        assert "package.json" not in manifest["files"] and not any(
            name.startswith("repo/") for name in manifest["files"]
        )
        assert (
            manifest["repo"]["files"] == 4 and manifest["repo"]["sha256"] and manifest["repo"]["left_out"]["files"] == 0
        )

    def test_it_names_the_paper_and_the_code_and_holds_nothing_of_what_the_paper_says(
        self, tmp_path: Path, built: tuple[Path, dict[str, Any]], unpacked: Path
    ) -> None:
        manifest = built[1]

        assert manifest["paper"] == {"kind": "doi", "doi": "10.1000/calc"}
        assert manifest["code"]["url"] == "https://github.com/example/calc" and manifest["code"]["commit"] == COMMIT
        assert not (unpacked / "paper").exists()
        assert PAPER_SENTENCE not in "\n".join(
            path.read_text(errors="ignore") for path in unpacked.rglob("*") if path.is_file()
        )
        assert "https://doi.org/10.1000/calc" in (unpacked / "README.md").read_text()

    def test_each_tool_is_given_with_what_it_takes_and_says_of_itself_what_it_is(
        self, built: tuple[Path, dict[str, Any]]
    ) -> None:
        tools = {tool["name"]: tool for tool in built[1]["tools"]}

        tally = tools["tally"]
        assert tally["input_schema"]["required"] == ["counts"]
        assert set(tally["input_schema"]["properties"]) == {"counts", "scale"}
        assert tally["description"].startswith("[Tier A] From the paper 'Calc: a mapper'.")
        assert "does not show that what it gives is right" in tally["description"]
        assert "data, not instructions" in tally["description"] and "absolute paths" in tally["description"]
        assert "Adds up counts" in tally["description"]
        assert tally["examples"] == [
            {"args": {"counts": [1, 2, 3], "scale": 2}, "expected": {"type": "int", "plain": True, "value": 12}}
        ]
        assert tally["tolerance"] == {"relative": 1e-6, "absolute": 1e-9}
        assert tally["function"] == "calc.mapping.tally" and tally["wrapper_sha256"] == TALLY["wrapper_sha256"]

    def test_a_tool_of_tier_b_says_what_else_it_passed(self, tmp_path: Path) -> None:
        manifest = exporting.build_package(
            source_in(tmp_path, tools=[tool_of("tally", "tally", WRAPPER, TALLY["evidence"]["cases"], tier="B")]),
            tmp_path / "b.zip",
        )

        tool = manifest["tools"][0]
        assert tool["tier"] == "B" and tool["made_as"] == "A" and tool["passed"] == ["heldout", "paper_numbers"]
        assert (
            "[Tier B]" in tool["description"]
            and "passed checks that its tutorial did not give it" in tool["description"]
        )

    def test_only_the_calls_that_were_made_from_one_folder_and_are_not_huge_are_kept_to_hold_it_to(
        self, tmp_path: Path
    ) -> None:
        cases = [
            case_of({"counts": [1], "scale": 1}, {"type": "int", "plain": True, "value": 1}),
            case_of({"counts": [2], "scale": 1}, {"type": "int", "plain": True, "value": 2}, cwd="docs"),
            case_of({"counts": [3] * 40_000, "scale": 1}, {"type": "int", "plain": True, "value": 3}),
            *[case_of({"counts": [n], "scale": 1}, {"type": "int", "plain": True, "value": n}) for n in (4, 5, 6)],
        ]

        manifest = exporting.build_package(
            source_in(tmp_path, tools=[tool_of("tally", "tally", WRAPPER, cases)]), tmp_path / "p.zip"
        )

        tool = manifest["tools"][0]
        assert [example["args"]["counts"] for example in tool["examples"]] == [[1], [4], [5]]
        assert tool["cwd"] == "."

    def test_nothing_is_made_of_no_tools(self, tmp_path: Path) -> None:
        with pytest.raises(exporting.PackageError, match="no tools"):
            exporting.build_package(source_in(tmp_path, tools=[]), tmp_path / "p.zip")

    def test_a_call_is_made_from_the_folder_that_the_tutorial_made_it_from(self, tmp_path: Path) -> None:
        source = source_in(tmp_path, tools=[NOTE])
        (source.repo / "docs").mkdir()
        (source.repo / "docs" / "note.txt").write_text("hello")
        manifest = exporting.build_package(source, tmp_path / "p.zip")
        folder = exporting.unpack(tmp_path / "p.zip", tmp_path / "o")

        _, report = run_check(folder)

        assert manifest["tools"][0]["cwd"] == "docs"
        assert report["ok"] is True and report["tools"][0]["cases"][0]["status"] == "match"

    def test_a_tool_with_no_call_that_can_be_carried_is_left_out_and_the_package_says_so(self, tmp_path: Path) -> None:
        too_big = case_of({"counts": [3] * 40_000, "scale": 1}, {"type": "int", "plain": True, "value": 3})
        source = source_in(tmp_path, tools=[TALLY, tool_of("scaled", "scaled", SCALE, [too_big])])

        manifest = exporting.build_package(source, tmp_path / "p.zip")

        assert [tool["name"] for tool in manifest["tools"]] == ["tally"] and manifest["left_out_tools"] == ["scaled"]
        folder = exporting.unpack(tmp_path / "p.zip", tmp_path / "o")
        assert not (folder / "tools" / "scaled").exists() and "`scaled`" in (folder / "README.md").read_text()
        _, report = run_check(folder)
        assert report["ok"] is True and [tool["name"] for tool in report["tools"]] == ["tally"]

    def test_a_package_of_tools_none_of_whose_calls_can_be_carried_is_not_made(self, tmp_path: Path) -> None:
        source = source_in(tmp_path, tools=[tool_of("tally", "tally", WRAPPER, [])])

        with pytest.raises(exporting.PackageError, match="None of the calls"):
            exporting.build_package(source, tmp_path / "p.zip")

    def test_a_wrapper_that_is_not_a_function_is_not_made_a_tool(self, tmp_path: Path) -> None:
        broken = {**TALLY, "source": "x = 1\n"}

        with pytest.raises(exporting.PackageError, match="cannot be read"):
            exporting.build_package(source_in(tmp_path, tools=[broken]), tmp_path / "p.zip")


class TestTheCode:
    def test_what_a_version_control_system_and_python_leave_is_not_put_in(self, tmp_path: Path) -> None:
        source = source_in(tmp_path)
        (source.repo / ".git").mkdir()
        (source.repo / ".git" / "config").write_text("[core]")
        (source.repo / "calc" / "__pycache__").mkdir()
        (source.repo / "calc" / "__pycache__" / "mapping.cpython-311.pyc").write_bytes(b"\0")
        (source.repo / "calc" / "old.pyc").write_bytes(b"\0")

        manifest = exporting.build_package(source, tmp_path / "p.zip")

        with zipfile.ZipFile(tmp_path / "p.zip") as archive:
            names = archive.namelist()
        assert not any(".git" in name or "pycache" in name or name.endswith(".pyc") for name in names)
        assert manifest["repo"]["files"] == 4

    def test_a_link_is_not_followed_so_that_nothing_outside_the_code_is_put_in(self, tmp_path: Path) -> None:
        source = source_in(tmp_path)
        secret = tmp_path / "secret.txt"
        secret.write_text("a secret")
        (source.repo / "link.txt").symlink_to(secret)
        (source.repo / "linked").symlink_to(tmp_path)

        manifest = exporting.build_package(source, tmp_path / "p.zip")

        with zipfile.ZipFile(tmp_path / "p.zip") as archive:
            names = archive.namelist()
            text = b"".join(archive.read(name) for name in names)
        assert not any("link" in name for name in names) and b"a secret" not in text
        assert manifest["repo"]["links_not_followed"] == 2

    def test_a_file_that_is_too_big_is_left_out_and_the_package_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(exporting, "MAX_FILE_BYTES", 1000)
        source = source_in(tmp_path)
        (source.repo / "data.bin").write_bytes(b"x" * 1001)

        manifest = exporting.build_package(source, tmp_path / "p.zip")

        assert manifest["repo"]["left_out"] == {"files": 1, "names": ["data.bin"]}
        readme = (exporting.unpack(tmp_path / "p.zip", tmp_path / "o") / "README.md").read_text()
        assert "`data.bin`" in readme and "left out" in readme

    def test_code_that_is_more_than_a_package_holds_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(exporting.PackageError, match="more than 0 megabytes"):
            exporting.build_package(source_in(tmp_path), tmp_path / "p.zip", budget=10)

    def test_a_file_keeps_whether_it_can_be_run(self, tmp_path: Path, unpacked: Path) -> None:
        with zipfile.ZipFile(tmp_path / "package.zip") as archive:
            modes = {info.filename.rsplit("/", 1)[-1]: info.external_attr >> 16 for info in archive.infolist()}

        assert modes["run.sh"] & 0o111 and modes["mcp_server.py"] & 0o111 and not modes["LICENSE"] & 0o111


class TestTheLicense:
    @pytest.mark.parametrize(
        ("found", "flag"),
        [
            (None, "none"),
            ({"files": ["LICENSE"], "name": "MIT", "kind": "permissive"}, None),
            ({"files": ["LICENSE"], "name": "Unlicense", "kind": "public domain"}, None),
            ({"files": ["LICENSE"], "name": "GPL-3.0", "kind": "copyleft"}, "copyleft"),
            ({"files": ["LICENSE"], "name": "CC-BY-NC", "kind": "noncommercial"}, "noncommercial"),
            ({"files": ["LICENSE"], "name": None, "kind": "noncommercial"}, "noncommercial"),
            ({"files": ["LICENSE"], "name": None, "kind": "other"}, "unrecognized"),
            ({"files": [], "name": "Custom", "kind": "other"}, "unrecognized"),
        ],
    )
    def test_what_limits_or_does_not_say_what_may_be_done_is_flagged(self, found: Any, flag: str | None) -> None:
        said = exporting.license_of(found)

        assert said["flag"] == flag
        assert (said["said"] is not None) == (flag is not None)

    def test_the_readme_and_the_server_say_it_first(self, tmp_path: Path) -> None:
        found = {"files": ["COPYING"], "name": "GPL-3.0", "kind": "copyleft", "from": "file"}
        source = source_in(tmp_path)
        source = exporting.Source(**{**source.__dict__, "intake": {**source.intake, "stock": {"license": found}}})

        manifest = exporting.build_package(source, tmp_path / "p.zip")

        readme = (exporting.unpack(tmp_path / "p.zip", tmp_path / "o") / "README.md").read_text()
        lines = readme.splitlines()
        assert lines[0].startswith("# ") and lines[2].startswith("> **Read this first. License: copyleft.**")
        assert "copyleft" in manifest["instructions"] and manifest["code"]["license"]["flag"] == "copyleft"

    def test_a_license_that_is_not_flagged_is_not_a_banner(self, tmp_path: Path, unpacked: Path) -> None:
        assert "Read this first" not in (unpacked / "README.md").read_text()
        assert "License of the code: MIT (permissive)" in (unpacked / "README.md").read_text()


class TestTheEnvironment:
    def test_the_lock_is_what_the_tools_were_made_in_without_what_is_of_this_machine(self, unpacked: Path) -> None:
        assert (unpacked / "requirements.lock.txt").read_text() == "numpy==1.26.4\nscipy==1.11.0\n"

    def test_a_pip_environment_is_built_from_its_lock_and_serves_the_package(self, unpacked: Path) -> None:
        lines = (unpacked / "Dockerfile").read_text().splitlines()

        assert "FROM python:3.11-slim" in lines
        assert "RUN python -m pip install --no-input --no-cache-dir -r requirements.lock.txt" in lines
        assert lines[-1] == 'ENTRYPOINT ["python", "/opt/package/mcp_server.py"]'
        assert not any("apt-get" in line for line in lines)

    def test_a_conda_environment_is_built_from_its_explicit_lock(self, tmp_path: Path) -> None:
        environment = {
            "python": "3.11.9",
            "recipe": {
                "kind": "conda",
                "base_image": "condaforge/miniforge3:25.3.1-0",
                "system_packages": ["libfoo-dev"],
            },
            "lock": {"name": "conda-explicit.txt", "packages": 3},
            "image": {"tag": "t", "id": SHA},
        }

        manifest = exporting.build_package(
            source_in(tmp_path, environment=environment, lock="@EXPLICIT\nhttps://example/pkg.conda\n"),
            tmp_path / "p.zip",
        )

        folder = exporting.unpack(tmp_path / "p.zip", tmp_path / "o")
        dockerfile = (folder / "Dockerfile").read_text()
        assert manifest["environment"]["lock_file"] == "environment.lock.txt"
        assert (folder / "environment.lock.txt").read_text() == "@EXPLICIT\nhttps://example/pkg.conda\n"
        assert "FROM condaforge/miniforge3:25.3.1-0" in dockerfile
        assert "conda create --yes --quiet -n paper --file environment.lock.txt" in dockerfile
        assert "apt-get install -y --no-install-recommends -qq libfoo-dev" in dockerfile
        assert "What pip installed into it is not in the lock" in (folder / "README.md").read_text()

    @pytest.mark.parametrize(
        "change",
        [
            {"recipe": {"kind": "pip", "base_image": "python:3.11-slim\nRUN evil", "system_packages": []}},
            {"recipe": {"kind": "pip", "base_image": "python:3.11-slim", "system_packages": ["a; rm -rf /"]}},
        ],
    )
    def test_what_cannot_be_put_in_a_dockerfile_is_refused(self, tmp_path: Path, change: dict[str, Any]) -> None:
        environment = {**source_in(tmp_path).environment, **change}

        with pytest.raises(exporting.PackageError, match="Dockerfile|system packages"):
            exporting.build_package(source_in(tmp_path, environment=environment), tmp_path / "p.zip")

    def test_data_that_the_tutorials_were_given_is_said_not_to_be_in_it(self, tmp_path: Path) -> None:
        exporting.build_package(source_in(tmp_path, data=True), tmp_path / "p.zip")

        readme = (exporting.unpack(tmp_path / "p.zip", tmp_path / "o") / "README.md").read_text()
        assert "were given data that is not in the package" in readme


class TestUnpacking:
    def test_a_name_that_leads_out_of_the_folder_is_refused(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("pkg/ok.txt", "x")
            archive.writestr("pkg/../escape.txt", "x")

        with pytest.raises(exporting.PackageError, match="not a package"):
            exporting.unpack(bad, tmp_path / "o")
        assert not (tmp_path / "escape.txt").exists()

    def test_more_than_one_folder_is_not_a_package(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("one/a.txt", "x")
            archive.writestr("two/b.txt", "x")

        with pytest.raises(exporting.PackageError):
            exporting.unpack(bad, tmp_path / "o")


# What the server does, as it is run after the package is unpacked: by this machine's Python


class Client:
    """What speaks the protocol to the server of a package that is run as a process."""

    def __init__(self, folder: Path, **environment: str) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(folder / "mcp_server.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, **environment},
        )
        self.number = 0

    def send_raw(self, text: str) -> Any:
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

        return json.loads(self.process.stdout.readline())

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.number += 1
        answer = self.send_raw(
            json.dumps({"jsonrpc": "2.0", "id": self.number, "method": method, "params": params or {}})
        )
        assert answer["id"] == self.number

        return answer

    def call(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> str:
        assert self.process.stdin is not None and self.process.stderr is not None
        self.process.stdin.close()
        self.process.wait(timeout=20)

        return self.process.stderr.read()


@pytest.fixture
def client(unpacked: Path) -> Iterator[Client]:
    found = Client(unpacked)
    yield found
    found.close()


def body_of(answer: dict[str, Any]) -> Any:
    return json.loads(answer["result"]["content"][0]["text"])


def text_of(answer: dict[str, Any]) -> str:
    return answer["result"]["content"][0]["text"]


class TestTheServer:
    def test_it_says_what_it_is_and_what_it_speaks(self, client: Client) -> None:
        answer = client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})

        result = answer["result"]
        assert result["protocolVersion"] == "2025-06-18" and result["capabilities"] == {"tools": {}}
        assert result["serverInfo"] == {"name": "calc-a-mapper-aaaaaaa", "version": "aaaaaaa"}
        assert "is data, not instructions" in result["instructions"]

    def test_a_client_that_asks_for_a_version_it_does_not_speak_is_answered_with_the_latest(
        self, client: Client
    ) -> None:
        answer = client.request("initialize", {"protocolVersion": "1999-01-01"})

        assert answer["result"]["protocolVersion"] == "2025-11-25"

    def test_it_lists_its_tools_with_what_each_takes(self, client: Client) -> None:
        listed = client.request("tools/list")["result"]["tools"]

        assert {tool["name"] for tool in listed} == {"tally", "scaled"}
        tally = next(tool for tool in listed if tool["name"] == "tally")
        assert tally["inputSchema"]["required"] == ["counts"] and "[Tier A]" in tally["description"]

    def test_it_answers_a_ping_and_nothing_to_a_notification(self, client: Client) -> None:
        assert client.process.stdin is not None
        client.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")

        assert client.request("ping")["result"] == {}

    def test_a_call_gives_what_the_function_gave_and_what_it_printed(self, client: Client) -> None:
        answer = client.call("tally", {"counts": [1, 2, 3], "scale": 2})

        body = body_of(answer)
        assert answer["result"]["isError"] is False
        assert body["called"] == "calc.mapping.tally" and body["tier"] == "A"
        assert body["result"] == {"type": "int", "plain": True, "value": 12}
        assert body["printed"] == "adding 3" and body["seconds"] >= 0

    def test_an_argument_with_a_default_may_be_left_out(self, client: Client) -> None:
        assert body_of(client.call("tally", {"counts": [1, 2]}))["result"]["value"] == 3

    def test_each_call_is_made_on_a_copy_of_the_code_and_leaves_nothing(self, unpacked: Path, client: Client) -> None:
        body_of(client.call("tally", {"counts": [1]}))

        assert not (unpacked / "repo" / "left.txt").exists()
        assert sorted(path.name for path in (unpacked / "repo").iterdir()) == ["LICENSE", "calc", "run.sh"]

    @pytest.mark.parametrize(
        ("arguments", "said"),
        [
            ({}, "counts must be given"),
            ({"counts": [1], "other": 1}, "other is not a parameter"),
            ({"counts": "not a list"}, "counts is not of the kind"),
            ({"counts": [1], "scale": "two"}, "scale is not of the kind"),
            ({"counts": [1], "scale": True}, "scale is not of the kind"),
            ([1], "arguments are an object"),
        ],
    )
    def test_arguments_that_do_not_fit_are_refused_before_anything_runs(
        self, client: Client, arguments: Any, said: str
    ) -> None:
        answer = client.call("tally", arguments)

        assert (
            answer["result"]["isError"] is True and said in text_of(answer) and text_of(answer).startswith("Not run:")
        )

    def test_a_number_that_is_not_finite_is_taken_as_a_number(self, client: Client) -> None:
        answer = client.send_raw(
            '{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"scaled","arguments":'
            '{"values":[1.0],"factor":NaN}}}'
        )

        assert answer["result"]["isError"] is False
        assert json.loads(text_of(answer))["result"]["value"] == [{"$float": "nan"}]

    def test_a_function_that_fails_says_how(self, client: Client) -> None:
        answer = client.call("tally", {"counts": ["a", "b"]})

        assert answer["result"]["isError"] is True and "TypeError" in text_of(answer)

    def test_a_tool_that_is_not_there_is_an_error_of_the_protocol(self, client: Client) -> None:
        answer = client.call("nothing", {})

        assert answer["error"]["code"] == -32602 and "nothing" in answer["error"]["message"]

    def test_a_method_that_it_does_not_do_is_an_error_of_the_protocol(self, client: Client) -> None:
        assert client.request("resources/list")["error"]["code"] == -32601

    def test_what_is_not_json_is_an_error_and_the_server_goes_on(self, client: Client) -> None:
        assert client.send_raw("{not json")["error"]["code"] == -32700
        assert client.request("ping")["result"] == {}

    def test_what_is_not_a_request_of_the_protocol_is_refused(self, client: Client) -> None:
        for message in (
            {"id": 1, "method": "ping"},
            {"jsonrpc": "1.0", "id": 2, "method": "ping"},
            {"jsonrpc": "2.0", "id": 3, "method": 5},
        ):
            answer = client.send_raw(json.dumps(message))
            assert answer["error"]["code"] == -32600 and answer["id"] == message["id"], message
        assert client.send_raw("[1]")  # a batch holds objects, and what is not one is answered as such
        assert client.request("ping")["result"] == {}

    def test_a_batch_is_answered_with_a_batch(self, client: Client) -> None:
        answer = client.send_raw(
            json.dumps(
                [
                    {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                ]
            )
        )

        assert [one["id"] for one in answer] == [1, 2]

    def test_a_call_that_takes_too_long_is_stopped(self, unpacked: Path) -> None:
        (unpacked / "repo" / "calc" / "mapping.py").write_text(
            MAPPING + "\n\ndef tally(counts, scale=1):\n    while True:\n        pass\n"
        )
        found = Client(unpacked, LUMI_CALL_SECONDS="1")
        try:
            answer = found.call("tally", {"counts": [1]})
        finally:
            found.close()

        assert answer["result"]["isError"] is True and "TimedOut" in text_of(answer)

    def test_a_server_that_is_told_to_end_takes_the_call_that_it_is_running_with_it(
        self, unpacked: Path, tmp_path: Path
    ) -> None:
        mark = tmp_path / "pid"
        (unpacked / "repo" / "calc" / "mapping.py").write_text(
            MAPPING
            + "\n\ndef tally(counts, scale=1):\n    import os, time\n"
            + f"    open({str(mark)!r}, 'w').write(str(os.getpid()))\n"
            + "    time.sleep(120)\n"
        )
        found = Client(unpacked, LUMI_CALL_SECONDS="100")
        assert found.process.stdin is not None
        found.process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "tally", "arguments": {"counts": [1]}},
                }
            )
            + "\n"
        )
        found.process.stdin.flush()
        deadline = time.monotonic() + 30
        while not (mark.exists() and mark.read_text()) and time.monotonic() < deadline:
            time.sleep(0.05)
        pid = int(mark.read_text())

        found.process.terminate()
        found.process.wait(timeout=20)

        gone = False
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                gone = True
                break
            time.sleep(0.05)
        assert gone, "the call is still running"

    def test_a_value_that_is_not_plain_data_is_described_and_not_sent(self, unpacked: Path) -> None:
        (unpacked / "repo" / "calc" / "mapping.py").write_text(
            MAPPING + "\n\ndef tally(counts, scale=1):\n    return {1, 2, 3}\n"
        )
        found = Client(unpacked)
        try:
            body = body_of(found.call("tally", {"counts": [1]}))
        finally:
            found.close()

        assert body["result"]["plain"] is False and "described and not sent" in body["result"]["note"]


def run_check(folder: Path, *options: str) -> tuple[int, dict[str, Any]]:
    done = subprocess.run(
        [sys.executable, str(folder / "mcp_server.py"), "check", *options], capture_output=True, text=True, timeout=120
    )

    return done.returncode, json.loads(done.stdout)


def retarget(folder: Path) -> None:
    """Says in the manifest that the code is as it is now, so that only what the calls give is what is looked at."""
    manifest = json.loads((folder / "package.json").read_text())
    manifest["repo"]["sha256"] = server_module(folder).tree_digest(str(folder / "repo"))
    (folder / "package.json").write_text(json.dumps(manifest))


class TestEndingAServer:
    def test_a_server_that_ends_when_asked_is_not_killed(self, unpacked: Path) -> None:
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])

        server_module(unpacked).stop_server(process)

        assert process.returncode == -15

    def test_a_server_that_does_not_end_when_asked_is_killed_after_the_time_it_is_given(self, unpacked: Path) -> None:
        module = server_module(unpacked)
        module.STOP_SECONDS = 1
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('up', flush=True); time.sleep(60)",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert process.stdout is not None and process.stdout.readline().strip() == "up"

        module.stop_server(process)
        process.wait(timeout=10)

        assert process.returncode == -9


class TestTheCheck:
    def test_it_holds_what_each_tool_gives_to_what_the_tutorial_got(self, unpacked: Path, tmp_path: Path) -> None:
        code, report = run_check(unpacked, "--report", str(tmp_path / "report.json"))

        assert code == 0 and report["ok"] is True and report["problems"] == []
        assert {tool["name"]: [case["status"] for case in tool["cases"]] for tool in report["tools"]} == {
            "tally": ["match"],
            "scaled": ["match"],
        }
        assert json.loads((tmp_path / "report.json").read_text()) == report

    def test_a_tool_that_gives_something_else_is_said_to_differ_and_how(self, unpacked: Path) -> None:
        (unpacked / "repo" / "calc" / "mapping.py").write_text(
            MAPPING.replace("sum(counts) * scale", "sum(counts) * scale + 1")
        )
        retarget(unpacked)

        code, report = run_check(unpacked)

        assert report["problems"] == [] and code == 1 and report["ok"] is False
        tally = next(tool for tool in report["tools"] if tool["name"] == "tally")
        assert (
            tally["cases"][0]["status"] == "differs" and "is 13 where it was 12" in tally["cases"][0]["differences"][0]
        )

    def test_code_that_is_not_what_it_was_made_as_is_said_whatever_it_gives(self, unpacked: Path) -> None:
        (unpacked / "repo" / "calc" / "mapping.py").write_text(MAPPING + "\n# changed\n")

        code, report = run_check(unpacked)

        assert code == 1 and report["ok"] is False
        assert any("The code in repo/ is not as it was made" in problem for problem in report["problems"])
        assert all(case["status"] == "match" for tool in report["tools"] for case in tool["cases"])

    def test_a_file_that_was_changed_or_taken_away_is_said(self, unpacked: Path) -> None:
        (unpacked / "tools" / "tally" / "wrapper.py").write_text(WRAPPER + "\n# changed\n")
        (unpacked / "Dockerfile").unlink()

        code, report = run_check(unpacked)

        assert code == 1
        assert "tools/tally/wrapper.py is not as it was made." in report["problems"]
        assert "Dockerfile is not there." in report["problems"]

    def test_a_tool_that_there_is_no_call_to_hold_it_to_is_not_a_pass(self, unpacked: Path) -> None:
        manifest = json.loads((unpacked / "package.json").read_text())
        manifest["tools"][0]["examples"] = []
        (unpacked / "package.json").write_text(json.dumps(manifest))

        code, report = run_check(unpacked)

        assert code == 1 and report["ok"] is False

    def test_a_number_within_the_tolerance_is_what_it_was(self, unpacked: Path) -> None:
        (unpacked / "repo" / "calc" / "mapping.py").write_text(
            MAPPING.replace("value * factor", "value * factor * (1 + 1e-9)")
        )

        _, report = run_check(unpacked)

        scaled = next(tool for tool in report["tools"] if tool["name"] == "scaled")
        assert scaled["cases"][0]["status"] == "match"

    def test_a_function_that_fails_is_an_error_of_the_check(self, unpacked: Path) -> None:
        (unpacked / "repo" / "calc" / "mapping.py").write_text("raise RuntimeError('broken')\n")
        retarget(unpacked)

        code, report = run_check(unpacked)

        assert report["problems"] == [] and code == 1 and report["ok"] is False
        assert all(
            case["status"] == "error" and "RuntimeError" in case["message"]
            for tool in report["tools"]
            for case in tool["cases"]
        )

    def test_only_so_many_calls_of_a_tool_are_made(self, tmp_path: Path) -> None:
        cases = [case_of({"counts": [n], "scale": 1}, {"type": "int", "plain": True, "value": n}) for n in (1, 2, 3)]
        exporting.build_package(
            source_in(tmp_path, tools=[tool_of("tally", "tally", WRAPPER, cases)]), tmp_path / "p.zip"
        )
        folder = exporting.unpack(tmp_path / "p.zip", tmp_path / "o")

        _, one = run_check(folder, "--cases", "1")
        _, all_of_them = run_check(folder)

        assert [len(tool["cases"]) for tool in one["tools"]] == [1]
        assert [len(tool["cases"]) for tool in all_of_them["tools"]] == [3]


def server_module(folder: Path) -> Any:
    spec = importlib.util.spec_from_file_location("package_server", folder / "mcp_server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


RECORDED = [
    {"type": "int", "plain": True, "value": 12},
    {"type": "float", "plain": True, "value": 1.5},
    {"type": "list", "plain": True, "value": [1.0, 2.0, {"a": [1, 2]}]},
    {"type": "dict", "plain": True, "value": {"a": 1.0, "b": {"$float": "nan"}}},
    {"type": "str", "plain": True, "value": "x"},
    {"type": "ndarray", "plain": False, "repr": "array([1, 2])", "shape": [2], "dtype": "int64", "values": [1.0, 2.0]},
    {"type": "ndarray", "plain": False, "repr": "array(...) [cut]", "shape": [200], "dtype": "float64", "sha256": "ab"},
    {"type": "Thing", "plain": False, "repr": "<Thing at 0x1234>"},
    {"type": "Thing", "plain": False, "repr": "Thing(1)"},
    {"type": "Thing", "plain": False, "repr": "Thing(2)"},
    {"type": "Thing", "plain": True, "value": 1},
    {"type": "list", "plain": True, "value": [1]},
    {"type": "list", "plain": True, "value": ["1"]},
    {"type": "list", "plain": True, "value": [1.0]},
    {"type": "list", "plain": True, "value": [True]},
    {"type": "list", "plain": True, "value": [1, 2]},
    {"type": "dict", "plain": True, "value": {"a": 1}},
    {"type": "dict", "plain": True, "value": {"b": 1}},
    {"type": "dict", "plain": True, "value": {"a": 1, "b": 2}},
    {
        "type": "ndarray",
        "plain": False,
        "repr": "array([1, 2])",
        "shape": [3],
        "dtype": "int64",
        "values": [1.0, 2.0, 3.0],
    },
]


class TestHoldingToWhatTheTutorialGot:
    def test_it_judges_as_the_lab_does(self, unpacked: Path) -> None:
        """The server in a package cannot import the lab's own code, so it has a copy of how a result is compared.
        This holds the two to each other on pairs of results that are the same, close, and different in each
        way that there is."""
        server = server_module(unpacked)
        tolerance = {"relative": 1e-6, "absolute": 1e-9}
        mine = comparing.Tolerance(**tolerance)

        for expected in RECORDED:
            for got in RECORDED:
                assert server.differences(expected, got, tolerance) == comparing.differences(expected, got, mine), (
                    expected,
                    got,
                )
        close = {"type": "float", "plain": True, "value": 1.5 * (1 + 1e-7)}
        far = {"type": "float", "plain": True, "value": 1.5 * (1 + 1e-4)}
        assert (
            server.differences(RECORDED[1], close, tolerance) == comparing.differences(RECORDED[1], close, mine) == []
        )
        assert server.differences(RECORDED[1], far, tolerance) == comparing.differences(RECORDED[1], far, mine) != []

    @pytest.mark.parametrize(
        ("schema", "value", "fits"),
        [
            ({"type": "integer"}, 3, True),
            ({"type": "integer"}, 3.0, True),
            ({"type": "integer"}, 3.5, False),
            ({"type": "integer"}, True, False),
            ({"type": "integer"}, "3", False),
            ({"type": "number"}, 1, True),
            ({"type": "number"}, 1.5, True),
            ({"type": "number"}, True, False),
            ({"type": "number"}, {"$float": "nan"}, True),
            ({"type": "string"}, {"$float": "nan"}, False),
            ({"type": "string"}, "a", True),
            ({"type": "boolean"}, 1, False),
            ({"type": "array"}, [1], True),
            ({"type": "array"}, {}, False),
            ({"type": "object"}, {}, True),
            ({"type": ["integer", "null"]}, None, True),
            ({"type": ["integer", "null"]}, "a", False),
            ({"anyOf": [{"type": "integer"}, {"type": "string"}]}, 1, True),
            ({"anyOf": [{"type": "integer"}, {"type": "string"}]}, "a", True),
            ({"anyOf": [{"type": "integer"}, {"type": "string"}]}, [], False),
            ({}, [1, "a"], True),
        ],
    )
    def test_what_a_tool_takes_is_held_to_the_kind_it_says(
        self, unpacked: Path, schema: dict[str, Any], value: Any, fits: bool
    ) -> None:
        server = server_module(unpacked)

        problem = server.check_arguments({"properties": {"x": schema}}, {"x": value})

        assert (problem is None) is fits, problem

    def test_what_is_not_given_or_is_not_taken_is_said(self, unpacked: Path) -> None:
        server = server_module(unpacked)
        schema = {"properties": {"a": {}, "b": {}}, "required": ["a"]}

        assert server.check_arguments(schema, {"a": 1}) is None
        assert "b must be given" in server.check_arguments({**schema, "required": ["a", "b"]}, {"a": 1})
        assert "c is not a parameter" in server.check_arguments(schema, {"a": 1, "c": 2})
        assert "object" in server.check_arguments(schema, [1])

    def test_a_link_is_not_followed_and_is_not_what_it_points_to(self, unpacked: Path) -> None:
        server = server_module(unpacked)
        manifest = json.loads((unpacked / "package.json").read_text())
        (unpacked / "repo" / "calc" / "alias.py").symlink_to(unpacked / "repo" / "calc" / "mapping.py")
        assert server.tree_digest(str(unpacked / "repo")) == manifest["repo"]["sha256"]

        (unpacked / "Dockerfile").rename(unpacked / "Dockerfile.real")
        (unpacked / "Dockerfile").symlink_to(unpacked / "Dockerfile.real")

        assert "Dockerfile is not there." in server.files_problems(manifest, str(unpacked))

    def test_the_hash_of_the_code_is_worked_out_as_the_package_works_it_out(self, unpacked: Path) -> None:
        server = server_module(unpacked)
        manifest = json.loads((unpacked / "package.json").read_text())

        assert server.tree_digest(str(unpacked / "repo")) == manifest["repo"]["sha256"]
        assert server.files_problems(manifest, str(unpacked)) == []


# The same, in a container, where there is Docker and an image to run it in


def docker_has(image: str) -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


IMAGE = "python:3.11-slim"
needs_docker = pytest.mark.skipif(not docker_has(IMAGE), reason=f"Docker and the image {IMAGE} are not here")


@needs_docker
class TestInAContainer:
    def test_the_package_is_checked_as_the_lab_checks_it_in_a_clean_container(
        self, tmp_path: Path, unpacked: Path
    ) -> None:
        from virtual_lab.paperagents import reference as referencing
        from virtual_lab.server import paperagent_library as library

        runner = library.PackageRunner(
            IMAGE,
            referencing.Limits(gigabytes=1),
            tmp_path,
            None,
            ("docker",),
            None,
            "calc",
            mounts=((unpacked, library.PACKAGE_AT),),
            seconds=120,
        )

        report, ended, code, lines = runner.check()

        assert (ended, code) == ("done", 0), lines
        assert report is not None and report["ok"] is True and library.why_not(report, ended, code, lines) is None
        assert {tool["name"] for tool in report["tools"]} == {"tally", "scaled"}
        assert not list(tmp_path.glob("check-*"))
        assert not (unpacked / "repo" / "left.txt").exists()

    def test_the_server_is_spoken_to_in_a_container_with_no_network(self, unpacked: Path) -> None:
        command = [
            "docker", "run", "-i", "--rm", "--network", "none", "-v", f"{unpacked}:/opt/package:ro", IMAGE,
            "python", "/opt/package/mcp_server.py",
        ]  # fmt: skip
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "tally", "arguments": {"counts": [4, 5]}},
            },
        ]

        done = subprocess.run(
            command,
            input="\n".join(json.dumps(message) for message in messages) + "\n",
            capture_output=True,
            text=True,
            timeout=120,
        )

        answers = [json.loads(line) for line in done.stdout.splitlines()]
        assert done.returncode == 0, done.stderr
        assert answers[0]["result"]["serverInfo"]["version"] == "aaaaaaa"
        assert json.loads(answers[1]["result"]["content"][0]["text"])["result"]["value"] == 9

    def test_a_package_that_is_not_what_it_was_made_as_does_not_pass_in_a_container_either(
        self, tmp_path: Path, unpacked: Path
    ) -> None:
        from virtual_lab.paperagents import reference as referencing
        from virtual_lab.server import paperagent_library as library

        (unpacked / "repo" / "calc" / "mapping.py").write_text(MAPPING.replace("sum(counts)", "sum(counts) + 1"))
        runner = library.PackageRunner(
            IMAGE, referencing.Limits(gigabytes=1), tmp_path, None, ("docker",), None, "calc",
            mounts=((unpacked, library.PACKAGE_AT),), seconds=120,
        )  # fmt: skip

        report, ended, code, lines = runner.check()

        assert code == 1 and report is not None and report["ok"] is False
        assert "tally, call 1" in (library.why_not(report, ended, code, lines) or "")


def test_a_tool_runner_that_the_package_carries_is_the_one_the_lab_makes_tools_with(unpacked: Path) -> None:
    here = Path(making.__file__).parent

    assert (unpacked / "tool_runner.py").read_bytes() == (here / "tool_runner.py").read_bytes()
    assert (unpacked / "lumi_record.py").read_bytes() == (here / "tutorial_runner.py").read_bytes()
    assert (unpacked / "mcp_server.py").read_bytes() == (here / "export_server.py").read_bytes()
