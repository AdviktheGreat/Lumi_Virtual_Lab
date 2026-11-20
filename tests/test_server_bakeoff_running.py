"""Tests of running the methods of a bake-off on the person's data: that a tool of a built method is called once, in the
container that tools are called in, with the person's data read-only and nothing else of theirs, that a program checks
the call against the tool's signature before anything runs, that data outside the card of a method's paper is not run on
until the person has gone on and that a method that was not run is kept and shown with why, that whatever came of a call
is kept with what it ran and on what, and that a run says whether the data and the method are as they were.

Docker, the containers that tools are called in, and the model that reads the papers are stand-ins, as they are in the
tests of building, so that what the bake-off does is what is looked at here."""

import copy
import hashlib
import io
import json
import os
import shutil
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeClient
from fastapi.testclient import TestClient
from test_paperagents_reading import queue, reading
from test_paperagents_reference import result_of
from test_server_bakeoff_building import (
    FIRST_CODE,
    SECOND_CODE,
    Docker,
    Papers,
    Remotes,
    add,
    agents,
    bakeoffs,
    build,
    client,
    containers,
    docker,
    finish,
    git_is_installed,
    jobs,
    marker,
    model_client,
    paper_of,
    papers,
    quick,
    remotes,
    replays,
    stack,
    workspace,
)
from test_server_bakeoffs import CSV, DOI, OTHER_DOI, TASK, TOKEN, job_done, refused, rewrite, why
from test_server_paperagent_reference import NOTEBOOK, SCRIPT, Containers, writes
from test_server_paperagent_repository import COMMIT
from test_server_paperagent_tools import CALLS, FUNCTIONS, MAPPING, Replays, call, gives

from virtual_lab.execution import DockerUnavailableError, ExecutionError
from virtual_lab.function_checks import FunctionSourceError
from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import toolmaking as making
from virtual_lab.paperagents.reading import ReadLicense, ReadLink, ReadScope
from virtual_lab.server import bakeoff_running as running
from virtual_lab.server import bakeoff_runs as kept_runs
from virtual_lab.server import bakeoff_scope
from virtual_lab.server.app import create_app
from virtual_lab.server.bakeoffs import RUN_JOB, Bakeoffs
from virtual_lab.server.own import Own
from virtual_lab.server.paperagents import PaperAgents
from virtual_lab.server.workspace import Workspace

# What the fixtures of the tests of building are, which are used here as they are
__all__ = [
    "agents",
    "bakeoffs",
    "client",
    "containers",
    "docker",
    "git_is_installed",
    "jobs",
    "marker",
    "model_client",
    "papers",
    "quick",
    "remotes",
    "replays",
    "stack",
    "workspace",
]

MOUSE = "tested on mouse brain tissue"
DATA = "counts.csv"
IN_CONTAINER = "/data/counts.csv"
# Calls of the two tools that were made of the tutorials' calls
MAP = {"tool": "map_cells", "arguments": {"counts": [1, 2, 3]}}
TALLY = {"tool": "tally", "arguments": {"counts": [1, 2, 3], "scale": 2}}
WHEN = "2024-01-01T00:00:00+00:00"


def read_as_mouse_brain(code: str) -> Any:
    """What a model says of a paper that says where its code is, what it is licensed as, and what it was tested on."""
    return reading(
        links=[ReadLink(url=code, role="code", quote=f"The analysis code is at {code}")],
        licenses=[ReadLicense(name="MIT", covers="code", quote="is released under the MIT license")],
        scope=[ReadScope(aspect="species", value="mouse", quote=MOUSE)],
    )


def text_of(name: str, code: str) -> str:
    return f"{paper_of(name, code)} It was developed and {MOUSE}."


# A function that takes a place and other things, which a call may name a place in the data in
READER = '''

def read_table(path, header=True, names=None, options=None):
    """Reads a table."""
    return path
'''
READ = call(
    "read_table", {"path": "example.csv", "header": True, "names": ["a"], "options": {"sep": ","}}, "example.csv", 3
)
READ_ARGUMENTS = {"path": "/data/counts.csv", "header": False, "names": ["a", "b"], "options": {"sep": ";"}}


@pytest.fixture
def reader(stack: Remotes, containers: Containers, monkeypatch: pytest.MonkeyPatch) -> None:
    """Makes the code of the methods have a third function, which the tutorials call, so that a tool of it is made."""
    stack.default = {**stack.default, "cellmapper/mapping.py": MAPPING + READER}
    containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=[*CALLS, READ]))
    monkeypatch.setitem(FUNCTIONS, "read_table", lambda args: args["path"])


def hold(replays: Replays, function: str) -> threading.Event:
    """Makes the calls of a tool wait to be let go on, and forgets that it began, which making the tool did too."""
    replays.began[function].clear()
    gate = replays.gates[function] = threading.Event()

    return gate


@pytest.fixture
def own_data(workspace: Workspace) -> Path:
    Own(workspace, 10_000).add_upload(DATA, io.BytesIO(CSV), "Read counts of mouse brain nuclei")

    return workspace.own_data_dir / DATA


@pytest.fixture
def built(
    bakeoffs: Bakeoffs, own_data: Path, reader: None, papers: Papers, model_client: FakeClient
) -> tuple[str, str]:
    """A bake-off of one method that is built, whose paper says that it was tested on mouse brain tissue, and which is
    to be run on the person's counts.csv. Nothing is said of what that data is."""
    papers.texts[DOI] = text_of("CellMapper", FIRST_CODE)
    bakeoff_id = bakeoffs.create(None, TASK, DATA, 1.0)
    candidate = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
    queue(model_client, read_as_mouse_brain(FIRST_CODE))
    assert build(bakeoffs, bakeoff_id).state == "succeeded"

    return bakeoff_id, candidate


@pytest.fixture
def two(
    bakeoffs: Bakeoffs, own_data: Path, reader: None, papers: Papers, model_client: FakeClient
) -> tuple[str, str, str]:
    """A bake-off of two methods that are built, each of whose paper says mouse brain tissue."""
    papers.texts[DOI] = text_of("CellMapper", FIRST_CODE)
    papers.texts[OTHER_DOI] = text_of("Labeller", SECOND_CODE)
    bakeoff_id = bakeoffs.create(None, TASK, DATA, 1.0)
    first = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
    second = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)
    queue(model_client, read_as_mouse_brain(FIRST_CODE), read_as_mouse_brain(SECOND_CODE))
    assert build(bakeoffs, bakeoff_id).state == "succeeded"

    return bakeoff_id, first, second


def run(bakeoffs: Bakeoffs, bakeoff_id: str, calls: dict[str, Any], **options: Any) -> Any:
    return finish(bakeoffs.start_run(bakeoff_id, calls, **options))


def folder_of(workspace: Workspace, bakeoff_id: str) -> Path:
    return workspace.bakeoffs_dir / bakeoff_id


def file_of(workspace: Workspace, bakeoff_id: str, candidate_id: str) -> Path:
    return folder_of(workspace, bakeoff_id) / "runs" / f"{candidate_id}.json"


def kept_of(workspace: Workspace, bakeoff_id: str, candidate_id: str) -> dict[str, Any]:
    return dict(json.loads(file_of(workspace, bakeoff_id, candidate_id).read_text("utf-8")))


def seen(bakeoffs: Bakeoffs, bakeoff_id: str, candidate_id: str) -> dict[str, Any]:
    return dict(next(each for each in bakeoffs.view(bakeoff_id)["candidates"] if each["id"] == candidate_id))


def run_shown(bakeoffs: Bakeoffs, bakeoff_id: str, candidate_id: str) -> dict[str, Any] | None:
    return seen(bakeoffs, bakeoff_id, candidate_id)["run"]  # type: ignore[no-any-return]


def say_outside(bakeoffs: Bakeoffs, bakeoff_id: str, candidate_id: str, species: str = "zebrafish") -> str:
    """Says that the data is of a species that the card says the method was not tested on, and gives the key of what the
    person is then shown of it."""
    bakeoffs.change(bakeoff_id, described={"species": species})

    return str(seen(bakeoffs, bakeoff_id, candidate_id)["scope"]["key"])


def answer(
    result: Any = None, seconds: float = 0.1, ok: bool = True, error: Any = None, output: str = ""
) -> Callable[[dict[str, Any], int], dict[str, Any]]:
    """A play in which a call writes what it came to, as the runner would, or something else than the runner would."""

    def play(case: dict[str, Any], repeat: int) -> dict[str, Any]:
        return {
            "schema": 1,
            "ok": ok,
            "error": error,
            "result": result if ok else None,
            "seconds": seconds,
            "output": output,
        }

    return play


def plain(value: Any) -> dict[str, Any]:
    return {"type": type(value).__name__, "plain": True, "value": value}


def damaged(workspace: Workspace, bakeoff_id: str, candidate_id: str, change: Callable[[dict[str, Any]], Any]) -> None:
    """Edits what is kept of a run, as someone might by hand."""
    path = file_of(workspace, bakeoff_id, candidate_id)
    saved = json.loads(path.read_text("utf-8"))
    change(saved)
    path.write_text(json.dumps(saved), "utf-8")


class TestRunningAMethod:
    def test_a_tool_is_called_once_with_the_arguments_that_were_said_in_the_container_of_its_method(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        before = len(replays.runs)

        job = run(bakeoffs, bakeoff_id, {candidate: TALLY})

        assert job.kind == RUN_JOB and job.state == "succeeded", job.error
        assert job.message == "Ran 1 of 1 methods."
        [ran] = replays.runs[before:]
        assert ran["function"] == "tally" and ran["repeats"] == 1
        assert [case["args"] for case in ran["cases"]] == [{"counts": [1, 2, 3], "scale": 2}]
        assert ran["seconds"] == making.DEFAULT_MINUTES * 60 and ran["data"] is None
        assert not ran["scratch"].exists()
        agent_id = seen(bakeoffs, bakeoff_id, candidate)["agent"]["id"]
        assert ran["label"] == agent_id

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"], saved["reason"], saved["by"]) == ("ran", None, "", "person")
        assert saved["candidate"] == candidate and saved["schema"] == 1
        assert saved["tool"] == {"name": "tally", "called": "cellmapper.mapping.tally", "tier": "A"}
        assert saved["arguments"] == {"counts": [1, 2, 3], "scale": 2}
        assert saved["result"] == {"type": "int", "value": 12} and saved["seconds"] == 0.1
        assert saved["printed"] is None
        assert saved["method"] == {"agent": agent_id, "commit": COMMIT, "image_id": saved["method"]["image_id"]}
        assert saved["method"]["image_id"].startswith("sha256:")
        assert saved["scope"]["checked"] is False and saved["scope"]["why"] == "no_description"
        assert saved["scope"]["went_on"] is False and saved["at"] > "2020"

    def test_the_data_is_given_to_the_container_to_read_where_the_lead_is_given_it_and_is_described(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str], own_data: Path
    ) -> None:
        bakeoff_id, candidate = built

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        [(source, target)] = replays.runs[-1]["mounts"]
        assert (source.resolve(), target) == (own_data.resolve(), IN_CONTAINER)
        data = kept_of(workspace, bakeoff_id, candidate)["data"]
        assert (data["own"], data["path"], data["files"], data["bytes"], data["complete"]) == (
            DATA,
            IN_CONTAINER,
            1,
            len(CSV),
            True,
        )
        assert data["fingerprint"] == kept_runs.listing_of(own_data)["fingerprint"]

    def test_a_result_that_is_not_plain_data_is_kept_as_it_is_described_with_what_it_printed(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        described = {"type": "ndarray", "plain": False, "repr": "array([1, 2])", "shape": [2]}
        replays.plays["map_cells"] = answer(described, 0.2, output="mapped 3 cells\n")

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert saved["state"] == "ran" and saved["printed"] == "mapped 3 cells" and saved["seconds"] == 0.2
        assert saved["result"]["note"] == "This is not plain data, so it is described and not sent."
        assert saved["result"]["shape"] == [2] and "plain" not in saved["result"]
        shown = run_shown(bakeoffs, bakeoff_id, candidate)
        assert shown is not None and shown["result"]["plain"] is False and shown["result"]["type"] == "ndarray"

    def test_what_a_page_is_shown_of_a_result_is_its_start_and_the_whole_is_asked_for_apart(
        self, bakeoffs: Bakeoffs, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        replays.plays["map_cells"] = gives(list(range(1000)))

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        shown = run_shown(bakeoffs, bakeoff_id, candidate)
        assert shown is not None and shown["state"] == "ran" and shown["since"] == []
        assert shown["result"]["type"] == "list" and shown["result"]["plain"] is True
        assert shown["result"]["cut"] is True and len(shown["result"]["start"]) == kept_runs.PREVIEW_CHARS
        assert shown["result"]["chars"] > kept_runs.PREVIEW_CHARS
        assert shown["arguments"] == MAP["arguments"] and shown["tool"]["name"] == "map_cells"
        whole = bakeoffs.run_of(bakeoff_id, candidate)
        assert whole["result"]["value"] == list(range(1000)) and whole["since"] == []

    def test_a_result_that_is_more_than_can_be_kept_is_described_with_a_hash_and_the_run_still_ran(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str], monkeypatch: Any
    ) -> None:
        bakeoff_id, candidate = built
        monkeypatch.setattr(kept_runs, "MAX_RUN_BYTES", 6000)
        replays.plays["map_cells"] = gives(list(range(1000)))

        job = run(bakeoffs, bakeoff_id, {candidate: MAP})

        assert job.state == "succeeded", job.error
        saved = kept_of(workspace, bakeoff_id, candidate)
        assert saved["state"] == "ran" and saved["seconds"] == 0.1
        result = saved["result"]
        assert result["type"] == "list" and "value" not in result and "more than can be kept" in result["note"]
        text = json.dumps({"type": "list", "value": list(range(1000))}, sort_keys=True)
        assert result["chars"] == len(text) and result["sha256"] == hashlib.sha256(text.encode()).hexdigest()
        shown = run_shown(bakeoffs, bakeoff_id, candidate)
        assert shown is not None and shown["result"]["plain"] is False

        replays.plays["map_cells"] = gives([4, 5])
        run(bakeoffs, bakeoff_id, {candidate: MAP})
        assert kept_of(workspace, bakeoff_id, candidate)["result"]["value"] == [4, 5]

    def test_a_method_that_was_not_run_has_no_run_and_asking_for_it_is_not_found(
        self, bakeoffs: Bakeoffs, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built

        assert run_shown(bakeoffs, bakeoff_id, candidate) is None
        assert why(bakeoffs.run_of, bakeoff_id, candidate) == (404, "not_found")
        assert why(bakeoffs.run_of, bakeoff_id, "00000000") == (404, "not_found")
        assert why(bakeoffs.run_of, "00000000-none", candidate) == (404, "not_found")

    def test_running_again_takes_the_place_of_the_last_run(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: MAP})

        run(bakeoffs, bakeoff_id, {candidate: {"tool": "map_cells", "arguments": {"counts": [4, 5]}}})

        assert kept_of(workspace, bakeoff_id, candidate)["result"]["value"] == [4, 5]
        assert [each.name for each in (folder_of(workspace, bakeoff_id) / "runs").iterdir()] == [f"{candidate}.json"]

    def test_a_call_may_be_given_more_minutes_and_not_more_than_there_may_be(
        self, bakeoffs: Bakeoffs, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built

        run(bakeoffs, bakeoff_id, {candidate: MAP}, minutes=12)
        assert replays.runs[-1]["seconds"] == 12 * 60
        for most in (1, making.MAX_MINUTES):
            run(bakeoffs, bakeoff_id, {candidate: MAP}, minutes=most)
            assert replays.runs[-1]["seconds"] == most * 60

        for wrong in (0, making.MAX_MINUTES + 1, True, "5", 2.5, -1):
            assert why(bakeoffs.start_run, bakeoff_id, {candidate: MAP}, wrong) == (422, "invalid")

    def test_what_is_run_is_what_is_asked_and_a_method_that_was_not_asked_for_is_left_as_it_was(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two

        run(bakeoffs, bakeoff_id, {second: MAP})

        assert not file_of(workspace, bakeoff_id, first).exists() and file_of(workspace, bakeoff_id, second).is_file()
        assert run_shown(bakeoffs, bakeoff_id, first) is None
        shown = run_shown(bakeoffs, bakeoff_id, second)
        assert shown is not None and shown["state"] == "ran"

    def test_each_method_is_run_in_the_order_it_was_asked_and_what_comes_of_one_is_not_what_comes_of_the_next(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        before = len(replays.runs)
        replays.plays["map_cells"] = answer(
            None,
            ok=False,
            error={"type": "ValueError", "message": "no cells", "traceback": ["File x.py", "  boom"], "cell": None},
        )

        job = run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        assert job.state == "succeeded" and job.message == "Ran 1 of 2 methods. Failed on the data: 1."
        assert [each["function"] for each in replays.runs[before:]] == ["map_cells", "tally"]
        assert kept_of(workspace, bakeoff_id, first)["state"] == "failed"
        assert kept_of(workspace, bakeoff_id, second)["state"] == "ran"
        assert kept_of(workspace, bakeoff_id, second)["arguments"] == TALLY["arguments"]


class TestWhatIsKeptOfWhatCameOfACall:
    def test_what_a_call_printed_is_kept_to_a_most_and_a_call_of_no_seconds_is_one_that_took_none(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        replays.plays["map_cells"] = answer(plain([1]), 0, output="x" * 3000)

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert saved["state"] == "ran" and saved["seconds"] == 0
        assert len(saved["printed"]) == kept_runs.MAX_PRINTED_CHARS and saved["printed"].endswith("…")

    def test_what_a_failing_call_printed_is_given_to_the_most_of_its_last_lines(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bakeoff_id, candidate = built
        text = "".join(f"line {number}\n\n" for number in range(1, 8))
        monkeypatch.setattr(making.ToolRunner, "execute", lambda *arguments: ("done", None, text))

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        reason = kept_of(workspace, bakeoff_id, candidate)["reason"]
        assert reason.endswith("line 3\nline 4\nline 5\nline 6\nline 7") and "line 2" not in reason


class TestWhatCameOfACallThatDidNotComeToAnAnswer:
    def test_a_function_that_raised_is_kept_with_what_it_raised_and_printed(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        error = {"type": "ValueError", "message": "scale must be positive", "traceback": ["File x.py", "  boom"]}
        replays.plays["tally"] = answer(None, 0.3, False, {**error, "cell": None}, "partial\n")

        job = run(bakeoffs, bakeoff_id, {candidate: TALLY})

        assert job.state == "succeeded" and job.message == "Ran 0 of 1 methods. Failed on the data: 1."
        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"], saved["result"], saved["seconds"]) == ("failed", "error", None, 0.3)
        assert saved["reason"].startswith("ValueError: scale must be positive")
        assert "File x.py" in saved["reason"] and "What it printed:\npartial" in saved["reason"]
        assert saved["tool"]["name"] == "tally" and saved["arguments"] == TALLY["arguments"]
        assert saved["method"] is not None and saved["data"] is not None
        shown = run_shown(bakeoffs, bakeoff_id, candidate)
        assert shown is not None and shown["result"] is None and shown["state"] == "failed"
        whole = bakeoffs.run_of(bakeoff_id, candidate)
        assert (whole["state"], whole["why"], whole["result"]) == ("failed", "error", None)

    @pytest.mark.parametrize(
        ("ended", "why_not", "words"),
        [
            ("timed_out", "timed_out", "stopped after 300 seconds"),
            ("too_big", "too_big", "writing more than 2 gigabytes"),
            ("done", "no_answer", "ended without saying how it went"),
        ],
    )
    def test_a_call_that_wrote_nothing_or_was_stopped_for_time_or_size_says_which(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        built: tuple[str, str],
        monkeypatch: pytest.MonkeyPatch,
        ended: str,
        why_not: str,
        words: str,
    ) -> None:
        bakeoff_id, candidate = built
        monkeypatch.setattr(making.ToolRunner, "execute", lambda *arguments: (ended, None, "last words\n"))

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"], saved["seconds"], saved["result"]) == ("failed", why_not, None, None)
        assert words in saved["reason"] and "The end of what the container printed:\nlast words" in saved["reason"]

    @pytest.mark.parametrize(
        "play",
        [
            answer(plain(float("nan"))),
            answer(plain([1, float("inf")])),
            answer(plain(1), seconds=float("nan")),
            answer(plain(1), seconds=float("inf")),
            answer(plain(1), seconds=-1),
        ],
    )
    def test_what_a_call_wrote_that_is_not_what_a_runner_writes_is_no_answer_and_does_not_end_the_run(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str], play: Any
    ) -> None:
        bakeoff_id, first, second = two
        replays.plays["map_cells"] = play

        job = run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        assert job.state == "succeeded", job.error
        saved = kept_of(workspace, bakeoff_id, first)
        assert (saved["state"], saved["why"]) == ("failed", "no_answer")
        assert kept_of(workspace, bakeoff_id, second)["state"] == "ran"

    def test_a_call_that_printed_nothing_has_nothing_printed_to_say_the_end_of(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        built: tuple[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bakeoff_id, candidate = built
        monkeypatch.setattr(making.ToolRunner, "execute", lambda *arguments: ("done", None, ""))

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        reason = kept_of(workspace, bakeoff_id, candidate)["reason"]
        assert reason.endswith("cannot be kept.") and "printed" not in reason

    def test_what_a_function_raised_is_no_more_than_can_be_kept(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        error = {"type": "ValueError", "message": "m" * 6000, "traceback": [], "cell": None}
        replays.plays["tally"] = answer(None, 0.3, False, error)

        job = run(bakeoffs, bakeoff_id, {candidate: TALLY})

        assert job.state == "succeeded", job.error
        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"], saved["seconds"]) == ("failed", "error", 0.3)
        assert len(saved["reason"]) == kept_runs.MAX_REASON_CHARS and saved["reason"].endswith("…")

    def test_a_container_that_could_not_be_started_with_the_data_in_it_is_a_method_not_run_and_the_next_is(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        replays.broken = ExecutionError("/data/counts.csv, given to the code to read, is not there any more")

        run(bakeoffs, bakeoff_id, {first: MAP})
        replays.broken = None
        run(bakeoffs, bakeoff_id, {second: MAP})

        saved = kept_of(workspace, bakeoff_id, first)
        assert (saved["state"], saved["why"], saved["tool"], saved["result"]) == ("not_run", "cannot_mount", None, None)
        assert "could not be started with the data in it" in saved["reason"] and "not there any more" in saved["reason"]
        assert kept_of(workspace, bakeoff_id, second)["state"] == "ran"

    def test_docker_that_does_not_run_it_is_not_a_failing_of_the_method_and_what_was_run_before_is_kept(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        replays.plays["tally"] = gives(7)
        original = replays.execute

        def broken_on_the_second(runner: Any, folder: Path, item: Any, seconds: float) -> Any:
            if json.loads((folder / making.CALL_FILE).read_text())["function"] == "map_cells":
                raise DockerUnavailableError("Docker did not run the tool: no daemon")

            return original(runner, folder, item, seconds)

        replays.execute = broken_on_the_second  # type: ignore[method-assign]

        job = run(bakeoffs, bakeoff_id, {first: TALLY, second: MAP})

        assert job.state == "failed" and "no daemon" in str(job.error)
        assert kept_of(workspace, bakeoff_id, first)["result"]["value"] == 7
        assert not file_of(workspace, bakeoff_id, second).exists()
        assert run_shown(bakeoffs, bakeoff_id, second) is None


class TestWhatIsNotRunBecauseOfTheCard:
    def test_data_that_is_outside_the_card_is_not_run_on_and_the_tool_is_not_called_and_it_is_shown_why(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        key = say_outside(bakeoffs, bakeoff_id, candidate)
        before = len(replays.runs)

        job = run(bakeoffs, bakeoff_id, {candidate: MAP})

        assert job.state == "succeeded" and job.message == "Ran 0 of 1 methods. Not run, each with why: 1."
        assert len(replays.runs) == before
        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"], saved["by"]) == ("not_run", "outside", "person")
        assert "outside what the method card of this method's paper says" in saved["reason"]
        assert "you have not said to go on with this method" in saved["reason"]
        assert saved["scope"]["outcome"] == "outside" and saved["scope"]["key"] == key
        assert saved["scope"]["went_on"] is False and saved["scope"]["warnings"]
        assert saved["scope"]["warnings"][0] in saved["reason"]
        assert (saved["tool"], saved["arguments"], saved["data"], saved["method"]) == (None, None, None, None)
        assert (saved["result"], saved["seconds"], saved["printed"]) == (None, None, None)
        shown = run_shown(bakeoffs, bakeoff_id, candidate)
        assert shown is not None and (shown["state"], shown["why"], shown["since"]) == ("not_run", "outside", [])

    def test_going_on_with_the_method_lets_it_run_and_the_run_says_it_was_gone_on_with(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        key = say_outside(bakeoffs, bakeoff_id, candidate)
        bakeoffs.go_on_with(bakeoff_id, candidate, key)

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert saved["state"] == "ran" and replays.functions()[-1] == "map_cells"
        assert (saved["scope"]["outcome"], saved["scope"]["went_on"], saved["scope"]["key"]) == ("outside", True, key)

    def test_going_on_is_of_that_method_and_of_what_the_data_was_said_to_be_when_they_went_on(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        key = say_outside(bakeoffs, bakeoff_id, first)
        bakeoffs.go_on_with(bakeoff_id, first, key)
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {first: MAP, second: MAP})

        assert (kept_of(workspace, bakeoff_id, first)["state"], kept_of(workspace, bakeoff_id, second)["why"]) == (
            "ran",
            "outside",
        )
        assert len(replays.runs) == before + 1
        say_outside(bakeoffs, bakeoff_id, first, "human")

        run(bakeoffs, bakeoff_id, {first: MAP})

        saved = kept_of(workspace, bakeoff_id, first)
        assert (saved["state"], saved["why"], saved["scope"]["went_on"]) == ("not_run", "outside", False)
        assert len(replays.runs) == before + 1

    def test_taking_back_the_going_on_stops_it_being_run_on_that_data_again(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        bakeoffs.go_on_with(bakeoff_id, candidate, say_outside(bakeoffs, bakeoff_id, candidate))
        run(bakeoffs, bakeoff_id, {candidate: MAP})
        assert kept_of(workspace, bakeoff_id, candidate)["state"] == "ran"

        bakeoffs.take_back(bakeoff_id, candidate)
        run(bakeoffs, bakeoff_id, {candidate: MAP})

        assert kept_of(workspace, bakeoff_id, candidate)["why"] == "outside"

    def test_data_that_is_inside_the_card_is_run_on_and_the_run_says_it_was_put_against_it(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        bakeoffs.change(bakeoff_id, described={"species": "mouse"})

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        scope = kept_of(workspace, bakeoff_id, candidate)["scope"]
        assert (scope["checked"], scope["outcome"], scope["went_on"], scope["warnings"]) == (True, "inside", False, [])

    def test_the_warnings_kept_with_a_run_are_the_first_few_and_cut(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bakeoff_id, candidate = built
        real = bakeoff_scope.scope_of

        def with_many_warnings(*arguments: Any) -> dict[str, Any]:
            return {**real(*arguments), "warnings": [f"{number} " + "w" * 700 for number in range(8)]}

        monkeypatch.setattr(bakeoff_scope, "scope_of", with_many_warnings)

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        warnings = kept_of(workspace, bakeoff_id, candidate)["scope"]["warnings"]
        assert len(warnings) == kept_runs.MAX_WARNINGS == 5
        assert all(len(each) == kept_runs.MAX_WARNING_CHARS and each.endswith("…") for each in warnings)
        assert [each[0] for each in warnings] == ["0", "1", "2", "3", "4"]

    def test_data_that_the_card_does_not_cover_is_run_on_and_its_warnings_are_kept_with_the_run(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        bakeoffs.change(bakeoff_id, described={"assay": "snRNA-seq"})
        shown = seen(bakeoffs, bakeoff_id, candidate)["scope"]
        assert shown["outcome"] != "outside"

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        scope = kept_of(workspace, bakeoff_id, candidate)["scope"]
        assert scope["checked"] is True and scope["outcome"] == shown["outcome"]
        assert scope["warnings"] == shown["warnings"][: kept_runs.MAX_WARNINGS]
        assert kept_of(workspace, bakeoff_id, candidate)["state"] == "ran"


class TestWhatStandsInTheWayOfARun:
    def test_there_is_nothing_to_run_on_where_no_data_is_named_and_nothing_is_started(
        self, bakeoffs: Bakeoffs, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        bakeoffs.change(bakeoff_id, data="")
        before = len(replays.runs)

        assert why(bakeoffs.start_run, bakeoff_id, {candidate: MAP}) == (422, "no_data")

        assert bakeoffs.calling(bakeoff_id) is None and len(replays.runs) == before

    def test_data_that_is_gone_from_the_data_page_is_not_run_on_and_nothing_is_started(
        self, bakeoffs: Bakeoffs, replays: Replays, built: tuple[str, str], own_data: Path
    ) -> None:
        bakeoff_id, candidate = built
        own_data.unlink()
        before = len(replays.runs)

        assert why(bakeoffs.start_run, bakeoff_id, {candidate: MAP}) == (422, "missing_data")

        assert bakeoffs.calling(bakeoff_id) is None and len(replays.runs) == before

    def test_data_that_goes_while_methods_are_being_run_is_a_method_not_run_that_says_so(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str], own_data: Path
    ) -> None:
        bakeoff_id, first, second = two
        gate = hold(replays, "tally")
        job = bakeoffs.start_run(bakeoff_id, {first: TALLY, second: MAP})
        assert replays.began["tally"].wait(10)

        own_data.unlink()
        gate.set()
        finish(job)

        assert kept_of(workspace, bakeoff_id, first)["state"] == "ran"
        saved = kept_of(workspace, bakeoff_id, second)
        assert (saved["state"], saved["why"]) == ("not_run", "data_missing")
        assert "not where the Data page says it is" in saved["reason"]

    def test_a_method_that_was_never_built_is_not_run_and_is_said_not_to_be_built(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, _ = built
        other = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {other: MAP})

        saved = kept_of(workspace, bakeoff_id, other)
        assert (saved["state"], saved["why"]) == ("not_run", "not_built")
        assert "Labeller is not built" in saved["reason"] and len(replays.runs) == before

    def test_a_method_whose_image_is_gone_from_docker_is_not_run_and_is_told_to_be_built_again(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str], docker: Docker
    ) -> None:
        bakeoff_id, candidate = built
        docker.images.clear()
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"]) == ("not_run", "not_built")
        assert "image of the environment is not in it" in saved["reason"] and len(replays.runs) == before

    def test_a_method_whose_tools_were_taken_away_is_not_run(
        self, bakeoffs: Bakeoffs, workspace: Workspace, agents: PaperAgents, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        [(directory, _)] = agents.kept()
        shutil.rmtree(directory / "tools")
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"]) == ("not_run", "not_built")
        assert "Build it again" in saved["reason"] and len(replays.runs) == before

    def test_a_method_whose_code_is_now_said_to_be_elsewhere_is_not_the_method_that_was_built(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        bakeoffs.change_candidate(bakeoff_id, candidate, repo="https://github.com/example/another")
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"]) == ("not_run", "not_built") and len(replays.runs) == before

    def test_data_that_is_taken_off_the_bake_off_while_it_is_run_is_a_method_not_run_that_says_so(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        gate = hold(replays, "tally")
        job = bakeoffs.start_run(bakeoff_id, {first: TALLY, second: MAP})
        assert replays.began["tally"].wait(10)

        rewrite(workspace, bakeoff_id, lambda record: record.update(data=None))
        gate.set()
        finish(job)

        saved = kept_of(workspace, bakeoff_id, second)
        assert (saved["state"], saved["why"]) == ("not_run", "no_data")
        assert "No data is named for this bake-off" in saved["reason"]

    def test_docker_that_is_not_running_is_said_before_anything_is_started(
        self, bakeoffs: Bakeoffs, replays: Replays, built: tuple[str, str], docker: Docker
    ) -> None:
        bakeoff_id, candidate = built
        docker.usable = (False, "Docker is not running. Start it and try again.")

        error = why(bakeoffs.start_run, bakeoff_id, {candidate: MAP})

        assert error == (422, "docker_missing") and bakeoffs.calling(bakeoff_id) is None

    def test_a_tool_that_the_method_does_not_have_is_not_called_and_the_ones_it_has_are_named(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {candidate: {"tool": "cluster", "arguments": {}}})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"]) == ("not_run", "no_tool")
        assert "no tool called 'cluster'" in saved["reason"]
        assert all(name in saved["reason"] for name in ("map_cells", "tally", "read_table"))
        assert len(replays.runs) == before


def reading_of(path: str, **more: Any) -> dict[str, Any]:
    return {"tool": "read_table", "arguments": {"path": path, **more}}


class TestCheckingTheCall:
    @pytest.mark.parametrize(
        ("call", "words"),
        [
            ({"tool": "tally", "arguments": {"counts": [1], "scal": 2}}, "does not take scal"),
            ({"tool": "tally", "arguments": {"scale": 2}}, "needs counts, which was not given"),
            ({"tool": "tally", "arguments": {}}, "needs counts, which was not given"),
            ({"tool": "tally", "arguments": [1, 2]}, "arguments are an object of values"),
            ({"tool": "tally", "arguments": "counts"}, "arguments are an object of values"),
            ({"tool": "tally", "arguments": None}, "arguments are an object of values"),
            ({"tool": "tally", "arguments": {1: [1]}}, "arguments are an object of values"),
            ({"tool": "tally", "arguments": {"counts": "abc"}}, "What is given for counts is not of the type"),
            (
                {"tool": "tally", "arguments": {"counts": [1], "scale": "2"}},
                "What is given for scale is not of the type",
            ),
            ({"tool": "read_table", "arguments": {"path": 3}}, "What is given for path is not of the type"),
            (reading_of("/data/counts.csv", names="a"), "What is given for names is not of the type"),
            ({"tool": "tally", "arguments": {"counts": [float("nan")]}}, "are not JSON"),
            ({"tool": "tally", "arguments": {"counts": float("inf")}}, "are not JSON"),
            ({"tool": "tally", "arguments": {"counts": {1, 2}}}, "are not JSON"),
            (reading_of("/data/other.csv"), "is not in the data of this bake-off"),
            (reading_of("/data"), "is not in the data of this bake-off"),
            (reading_of("/data/counts.csv/../x"), "goes out of the data with .."),
            (reading_of("/data/counts.csv/inner"), "is not in the data"),
            (reading_of("/data/counts.csv", names=["a", "/data/elsewhere"]), "not in the data of this bake-off"),
            (reading_of("x", options={"deep": {"here": ["/data/elsewhere"]}}), "not in the data of this bake-off"),
        ],
    )
    def test_what_the_signature_does_not_allow_is_not_called_and_is_kept_with_what_is_wrong(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        call: dict[str, Any],
        words: str,
    ) -> None:
        bakeoff_id, candidate = built
        before = len(replays.runs)

        job = run(bakeoffs, bakeoff_id, {candidate: call})

        assert job.state == "succeeded", job.error
        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"], saved["by"]) == ("not_run", "bad_call", "person")
        assert words in saved["reason"] and saved["reason"].endswith(".")
        assert (saved["tool"], saved["arguments"], saved["data"], saved["method"]) == (None, None, None, None)
        assert len(replays.runs) == before

    def test_a_place_in_the_data_is_given_to_the_tool_as_it_is_said_wherever_in_the_arguments_it_is(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        call = {"tool": "read_table", "arguments": READ_ARGUMENTS}

        run(bakeoffs, bakeoff_id, {candidate: call})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["result"]) == ("ran", {"type": "str", "value": "/data/counts.csv"})
        assert saved["arguments"] == READ_ARGUMENTS
        assert replays.runs[-1]["cases"][0]["args"] == READ_ARGUMENTS

    def test_the_place_of_the_data_may_be_named_with_a_slash_after_it_and_in_what_is_nested(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        call = reading_of(
            "/data/counts.csv/",
            names=["/data/counts.csv", "/data/counts.csv/"],
            options={"a": [{"b": "/data/counts.csv"}]},
        )

        run(bakeoffs, bakeoff_id, {candidate: call})

        assert kept_of(workspace, bakeoff_id, candidate)["state"] == "ran"

    def test_text_that_only_looks_like_a_place_in_the_data_is_not_one(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        call = reading_of(
            "/database/x", names=["data/other.csv", "/datastore", "see /data/other.csv", "/DATA/x", "//data/x"]
        )

        run(bakeoffs, bakeoff_id, {candidate: call})

        assert kept_of(workspace, bakeoff_id, candidate)["state"] == "ran"

    def test_no_more_than_a_few_of_the_places_that_are_wrong_are_said(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        places = [f"/data/other{number}.csv" for number in range(6)]

        run(bakeoffs, bakeoff_id, {candidate: reading_of("/data/counts.csv", names=places)})

        reason = kept_of(workspace, bakeoff_id, candidate)["reason"]
        assert reason.count("is not in the data of this bake-off") == 3
        assert "and 3 more places that are not as they should be" in reason

    @pytest.mark.parametrize(("wrappers", "why_not"), [(running.MAX_DEPTH - 1, "bad_call"), (running.MAX_DEPTH, None)])
    def test_places_that_are_wrong_are_looked_for_to_a_depth_of_what_is_nested_and_no_deeper(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], wrappers: int, why_not: str | None
    ) -> None:
        bakeoff_id, candidate = built
        deep: Any = "/data/elsewhere"
        for _ in range(wrappers):
            deep = [deep]

        run(bakeoffs, bakeoff_id, {candidate: reading_of("/data/counts.csv", names=deep)})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert saved["why"] == why_not and saved["state"] == ("not_run" if why_not else "ran")

    def test_arguments_of_the_most_that_can_be_kept_are_called_and_of_one_more_are_not(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        built: tuple[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bakeoff_id, candidate = built
        arguments = {"counts": [1, 2, 3]}
        size = len(json.dumps(arguments))
        monkeypatch.setattr(kept_runs, "MAX_ARGUMENTS_CHARS", size)

        run(bakeoffs, bakeoff_id, {candidate: {"tool": "map_cells", "arguments": arguments}})
        assert kept_of(workspace, bakeoff_id, candidate)["state"] == "ran"

        monkeypatch.setattr(kept_runs, "MAX_ARGUMENTS_CHARS", size - 1)
        run(bakeoffs, bakeoff_id, {candidate: {"tool": "map_cells", "arguments": arguments}})
        assert kept_of(workspace, bakeoff_id, candidate)["why"] == "bad_call"

    def test_a_wrapper_that_cannot_be_read_for_its_types_is_a_call_that_cannot_be_checked_and_is_not_called(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bakeoff_id, candidate = built

        def unreadable(*arguments: Any) -> Any:
            raise FunctionSourceError("no")

        monkeypatch.setattr(running, "read_function", unreadable)
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["why"], len(replays.runs)) == ("bad_call", before)
        assert "cannot be read for its types" in saved["reason"]

    def test_arguments_that_are_more_than_can_be_kept_are_not_called(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bakeoff_id, candidate = built
        monkeypatch.setattr(kept_runs, "MAX_ARGUMENTS_CHARS", 50)
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {candidate: {"tool": "map_cells", "arguments": {"counts": list(range(100))}}})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["why"], len(replays.runs)) == ("bad_call", before)
        assert "more than 50 characters" in saved["reason"]

    def test_a_reason_that_is_long_is_cut_to_what_can_be_kept(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bakeoff_id, candidate = built
        monkeypatch.setattr(kept_runs, "MAX_REASON_CHARS", 60)

        run(bakeoffs, bakeoff_id, {candidate: {"tool": "cluster", "arguments": {}}})

        reason = kept_of(workspace, bakeoff_id, candidate)["reason"]
        assert len(reason) == 60 and reason.endswith("…")


class TestWhatIsAskedFor:
    @pytest.mark.parametrize(
        "calls",
        [
            None,
            [],
            {},
            "all",
            {"a": "map_cells"},
            {"a": {}},
            {"a": {"tool": ""}},
            {"a": {"tool": " map_cells"}},
            {"a": {"tool": 3}},
            {"a": {"tool": "x" * 101}},
            {1: {"tool": "map_cells"}},
            {"a": {"tool": "map_cells", "other": 1}},
            {"a" * 1: {"tool": "map_cells"}, **{str(number): {"tool": "t"} for number in range(40)}},
        ],
    )
    def test_calls_that_are_not_an_object_of_a_tool_and_arguments_by_the_id_of_a_method_are_refused(
        self, bakeoffs: Bakeoffs, replays: Replays, built: tuple[str, str], calls: Any
    ) -> None:
        bakeoff_id, _ = built

        assert why(bakeoffs.start_run, bakeoff_id, calls) == (422, "invalid")

        assert bakeoffs.calling(bakeoff_id) is None

    def test_as_many_methods_as_there_may_be_in_a_bake_off_may_be_asked_for_and_not_one_more(
        self, bakeoffs: Bakeoffs, built: tuple[str, str]
    ) -> None:
        bakeoff_id, _ = built

        assert why(bakeoffs.start_run, bakeoff_id, {f"{number:08x}": MAP for number in range(12)}) == (404, "not_found")
        assert why(bakeoffs.start_run, bakeoff_id, {f"{number:08x}": MAP for number in range(13)}) == (422, "invalid")

    def test_a_tool_may_be_named_by_as_many_characters_as_there_may_be_and_not_one_more(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built

        run(bakeoffs, bakeoff_id, {candidate: {"tool": "x" * running.MAX_TOOL_NAME_CHARS}})

        assert kept_of(workspace, bakeoff_id, candidate)["why"] == "no_tool"
        assert why(bakeoffs.start_run, bakeoff_id, {candidate: {"tool": "x" * 101}}) == (422, "invalid")

    def test_a_method_that_is_not_in_the_bake_off_is_not_found_and_nothing_is_run(
        self, bakeoffs: Bakeoffs, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        before = len(replays.runs)

        assert why(bakeoffs.start_run, bakeoff_id, {candidate: MAP, "00000000": MAP}) == (404, "not_found")
        assert why(bakeoffs.start_run, "00000000-none", {candidate: MAP}) == (404, "not_found")

        assert len(replays.runs) == before and bakeoffs.calling(bakeoff_id) is None

    def test_a_call_without_arguments_is_one_with_none_which_a_tool_that_needs_some_does_not_allow(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {candidate: {"tool": "map_cells"}})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["why"], len(replays.runs)) == ("bad_call", before) and "needs counts" in saved["reason"]


class TestWhileItIsGoingOn:
    def test_methods_are_run_as_a_job_that_the_bake_off_says_it_is_and_that_what_is_done_to_it_waits_for(
        self, bakeoffs: Bakeoffs, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        gate = hold(replays, "map_cells")

        job = bakeoffs.start_run(bakeoff_id, {candidate: MAP})
        assert replays.began["map_cells"].wait(10)

        assert why(bakeoffs.start_run, bakeoff_id, {candidate: MAP}) == (409, "busy")
        assert why(bakeoffs.start_build, bakeoff_id) == (409, "busy")
        assert why(bakeoffs.start_shortlist, bakeoff_id) == (409, "busy")
        assert why(bakeoffs.change, bakeoff_id, title="Another") == (409, "busy")
        assert why(bakeoffs.delete, bakeoff_id) == (409, "busy")
        assert bakeoffs.calling(bakeoff_id) is job and bakeoffs.running(bakeoff_id) is job
        assert bakeoffs.building(bakeoff_id) is None
        shown = bakeoffs.view(bakeoff_id)["job"]
        assert shown["kind"] == RUN_JOB and shown["progress"]["candidate"] == candidate
        assert shown["message"] == "Running CellMapper (1 of 1)" and shown["progress"]["finished"] == 0
        assert shown["progress"]["candidates"] == 1
        listed = bakeoffs.describe()["bakeoffs"][0]["job"]
        assert listed["kind"] == RUN_JOB

        gate.set()
        finish(job)

        assert bakeoffs.calling(bakeoff_id) is None and bakeoffs.view(bakeoff_id)["job"] is None
        assert job.state == "succeeded" and job.progress["finished"] == 1 and job.message == "Ran 1 of 1 methods."

    def test_a_run_that_is_stopped_keeps_what_was_run_and_not_the_method_it_was_stopped_in(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        run(bakeoffs, bakeoff_id, {second: TALLY})
        earlier = kept_of(workspace, bakeoff_id, second)
        hold(replays, "map_cells")

        job = bakeoffs.start_run(bakeoff_id, {first: TALLY, second: MAP})
        assert replays.began["map_cells"].wait(10)
        job.request_stop()
        finish(job)

        assert job.state == "stopped" and "What was run is kept" in job.message
        assert kept_of(workspace, bakeoff_id, first)["state"] == "ran"
        assert kept_of(workspace, bakeoff_id, second) == earlier
        assert bakeoffs.calling(bakeoff_id) is None

    def test_a_run_that_is_stopped_while_a_method_is_run_does_not_get_to_the_next(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        hold(replays, "tally")
        before = len(replays.runs)

        job = bakeoffs.start_run(bakeoff_id, {first: TALLY, second: MAP})
        assert replays.began["tally"].wait(10)
        job.request_stop()
        finish(job)

        assert job.state == "stopped" and len(replays.runs) == before + 1
        assert (
            not file_of(workspace, bakeoff_id, first).exists() and not file_of(workspace, bakeoff_id, second).exists()
        )

    def test_a_run_that_is_stopped_between_two_methods_keeps_the_first_and_does_not_get_to_the_second(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        before = len(replays.runs)
        box: list[Any] = []
        start = hold(replays, "tally")

        def stops_the_run(case: dict[str, Any], repeat: int) -> dict[str, Any]:
            box[0].request_stop()

            return replays.gives("tally", case)

        replays.plays["tally"] = stops_the_run
        job = bakeoffs.start_run(bakeoff_id, {first: TALLY, second: MAP})
        box.append(job)
        start.set()
        finish(job)

        assert job.state == "stopped" and len(replays.runs) == before + 1
        assert kept_of(workspace, bakeoff_id, first)["state"] == "ran"
        assert not file_of(workspace, bakeoff_id, second).exists()

    def test_a_method_taken_out_of_the_running_while_it_is_run_has_no_run_kept(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        gate = hold(replays, "tally")
        job = bakeoffs.start_run(bakeoff_id, {first: TALLY, second: MAP})
        assert replays.began["tally"].wait(10)

        bakeoffs.remove_candidate(bakeoff_id, first)
        gate.set()
        finish(job)

        assert job.state == "succeeded" and job.message == "Ran 1 of 1 methods."
        assert not file_of(workspace, bakeoff_id, first).exists()
        assert kept_of(workspace, bakeoff_id, second)["state"] == "ran"

    def test_a_method_taken_out_of_the_running_before_its_turn_is_not_got_to_and_the_rest_are(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        gate = hold(replays, "tally")
        job = bakeoffs.start_run(bakeoff_id, {first: TALLY, second: MAP})
        assert replays.began["tally"].wait(10)

        bakeoffs.remove_candidate(bakeoff_id, second)
        gate.set()
        finish(job)

        assert job.state == "succeeded" and job.message == "Ran 1 of 1 methods."
        assert kept_of(workspace, bakeoff_id, first)["state"] == "ran"
        assert not file_of(workspace, bakeoff_id, second).exists()
        assert [each["function"] for each in replays.runs[-1:]] == ["tally"]

    def test_a_bake_off_that_is_gone_while_it_is_run_ends_the_run_and_keeps_nothing(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        gate = hold(replays, "tally")
        job = bakeoffs.start_run(bakeoff_id, {first: TALLY, second: MAP})
        assert replays.began["tally"].wait(10)

        shutil.rmtree(folder_of(workspace, bakeoff_id))
        gate.set()
        finish(job)

        assert job.state == "succeeded" and job.message == "Ran 0 of 0 methods."
        assert replays.runs[-1]["function"] == "tally" and not folder_of(workspace, bakeoff_id).exists()

    def test_what_came_of_each_method_is_said_in_the_log_of_the_job(
        self, bakeoffs: Bakeoffs, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        say_outside(bakeoffs, bakeoff_id, first)
        bakeoffs.go_on_with(bakeoff_id, second, str(seen(bakeoffs, bakeoff_id, second)["scope"]["key"]))
        replays.plays["tally"] = answer(
            None, ok=False, error={"type": "ValueError", "message": "x", "traceback": [], "cell": None}
        )

        job = run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        lines = job.snapshot(0)["log"]["lines"]
        assert lines == ["CellMapper: not run, outside", "Labeller: failed, error"]

    def test_taking_a_method_out_of_the_running_takes_its_run_with_it_and_not_another_methods(
        self, bakeoffs: Bakeoffs, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        run(bakeoffs, bakeoff_id, {first: MAP, second: MAP})

        bakeoffs.remove_candidate(bakeoff_id, first)

        assert not file_of(workspace, bakeoff_id, first).exists() and file_of(workspace, bakeoff_id, second).is_file()

    def test_a_bake_off_that_is_taken_away_takes_its_runs_with_it(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: MAP})

        bakeoffs.delete(bakeoff_id)

        assert not folder_of(workspace, bakeoff_id).exists()
        assert why(bakeoffs.run_of, bakeoff_id, candidate) == (404, "not_found")

    def test_a_run_may_be_made_while_another_bake_off_is_being_run(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        papers: Papers,
        model_client: FakeClient,
    ) -> None:
        bakeoff_id, candidate = built
        other_id = bakeoffs.create("Other", TASK, DATA, 1.0)
        other = add(bakeoffs, other_id, DOI, "CellMapper", FIRST_CODE)
        gate = hold(replays, "map_cells")
        job = bakeoffs.start_run(bakeoff_id, {candidate: MAP})
        assert replays.began["map_cells"].wait(10)

        try:
            second = bakeoffs.start_run(other_id, {other: TALLY})
            finish(second)
        finally:
            gate.set()
        finish(job)

        assert second.state == "succeeded" and job.state == "succeeded"
        assert kept_of(workspace, other_id, other)["state"] == "ran"


class TestWhatIsSaidOfWhetherItIsAsItWas:
    def test_a_run_says_nothing_has_changed_until_the_data_or_the_method_is_not_as_it_was(
        self, bakeoffs: Bakeoffs, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: MAP})

        shown = run_shown(bakeoffs, bakeoff_id, candidate)

        assert shown is not None and shown["since"] == []
        assert bakeoffs.run_of(bakeoff_id, candidate)["since"] == []

    def test_data_whose_size_or_time_has_changed_is_said_not_to_be_as_it_was(
        self, bakeoffs: Bakeoffs, built: tuple[str, str], own_data: Path
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: MAP})

        own_data.write_bytes(CSV + b"Y,3,4\n")

        shown = run_shown(bakeoffs, bakeoff_id, candidate)
        assert shown is not None and shown["since"] == ["data"]
        assert bakeoffs.run_of(bakeoff_id, candidate)["since"] == ["data"]

    def test_data_that_was_touched_but_has_the_same_size_is_said_not_to_be_as_it_was(
        self, bakeoffs: Bakeoffs, built: tuple[str, str], own_data: Path
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: MAP})
        status = own_data.stat()

        os.utime(own_data, ns=(status.st_atime_ns, status.st_mtime_ns + 5_000_000_000))

        assert bakeoffs.run_of(bakeoff_id, candidate)["since"] == ["data"]

    def test_data_that_is_gone_or_is_another_piece_is_said_not_to_be_as_it_was(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], own_data: Path
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: MAP})
        Own(workspace, 10_000).add_upload("other.csv", io.BytesIO(CSV), "The same bytes by another name")

        bakeoffs.change(bakeoff_id, data="other.csv")
        assert bakeoffs.run_of(bakeoff_id, candidate)["since"] == ["data"]

        bakeoffs.change(bakeoff_id, data=DATA)
        assert bakeoffs.run_of(bakeoff_id, candidate)["since"] == []

        own_data.unlink()
        shown = run_shown(bakeoffs, bakeoff_id, candidate)
        assert shown is not None and shown["since"] == ["data"]

    def test_a_method_that_was_made_again_or_is_gone_is_said_not_to_be_as_it_was(
        self, bakeoffs: Bakeoffs, workspace: Workspace, agents: PaperAgents, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: MAP})
        original = kept_of(workspace, bakeoff_id, candidate)

        for field, other in (("commit", "f" * 40), ("image_id", "sha256:" + "e" * 64), ("agent", "another-agent")):
            damaged(
                workspace,
                bakeoff_id,
                candidate,
                lambda saved, field=field, other=other: saved["method"].update({field: other}),
            )
            assert bakeoffs.run_of(bakeoff_id, candidate)["since"] == ["method"]
            file_of(workspace, bakeoff_id, candidate).write_text(json.dumps(original), "utf-8")
            assert bakeoffs.run_of(bakeoff_id, candidate)["since"] == []

        [(directory, _)] = agents.kept()
        shutil.rmtree(directory / "tools")
        shown = run_shown(bakeoffs, bakeoff_id, candidate)
        assert shown is not None and shown["since"] == ["method"]

    def test_a_method_that_was_not_run_has_nothing_that_is_not_as_it_was(
        self, bakeoffs: Bakeoffs, built: tuple[str, str], own_data: Path
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: {"tool": "cluster", "arguments": {}}})
        own_data.write_bytes(CSV + b"Z,5,6\n")

        shown = run_shown(bakeoffs, bakeoff_id, candidate)

        assert shown is not None and shown["state"] == "not_run" and shown["since"] == []


class TestWhatIsKeptIsOnlyWhatIsInTheShapeOfARun:
    def valid(self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]) -> dict[str, Any]:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: TALLY})

        return kept_of(workspace, bakeoff_id, candidate)

    @pytest.mark.parametrize(
        "change",
        [
            lambda saved: saved.update(schema=2),
            lambda saved: saved.update(candidate="00000000"),
            lambda saved: saved.update(state="done"),
            lambda saved: saved.update(state="failed"),
            lambda saved: saved.update(state="not_run", why="outside"),
            lambda saved: saved.update(by="a model"),
            lambda saved: saved.update(at="2024\x00"),
            lambda saved: saved.update(reason="something"),
            lambda saved: saved.update(why="error"),
            lambda saved: saved.update(result=None),
            lambda saved: saved.update(result={"value": 1}),
            lambda saved: saved.update(result=[1]),
            lambda saved: saved.update(seconds=None),
            lambda saved: saved.update(seconds=-1),
            lambda saved: saved.update(seconds="fast"),
            lambda saved: saved.update(arguments=None),
            lambda saved: saved.update(arguments=[1]),
            lambda saved: saved.update(printed="x" * 2001),
            lambda saved: saved.update(tool=None),
            lambda saved: saved["tool"].update(name=3),
            lambda saved: saved["tool"].update(tier="A\x07"),
            lambda saved: saved.update(data=None),
            lambda saved: saved["data"].update(fingerprint="abc"),
            lambda saved: saved["data"].update(files=-1),
            lambda saved: saved["data"].update(bytes=-1),
            lambda saved: saved["data"].update(own="a\x00"),
            lambda saved: saved["data"].pop("complete"),
            lambda saved: saved.update(method=None),
            lambda saved: saved["method"].update(commit="not a commit"),
            lambda saved: saved["method"].update(agent=""),
            lambda saved: saved["method"].update(image_id="sha\x00"),
            lambda saved: saved["scope"].update(key="short"),
            lambda saved: saved["scope"].update(warnings=["w"] * 6),
            lambda saved: saved["scope"].update(warnings=["w" * 601]),
            lambda saved: saved["scope"].update(outcome="inside", checked=False),
            lambda saved: saved["scope"].update(went_on=True),
            lambda saved: saved["scope"].update(why="a\x00"),
            lambda saved: saved.pop("scope"),
        ],
    )
    def test_a_run_that_is_not_what_a_run_is_is_not_used(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        built: tuple[str, str],
        change: Callable[[dict[str, Any]], Any],
    ) -> None:
        self.valid(bakeoffs, workspace, built)
        bakeoff_id, candidate = built

        damaged(workspace, bakeoff_id, candidate, change)

        assert run_shown(bakeoffs, bakeoff_id, candidate) is None
        assert why(bakeoffs.run_of, bakeoff_id, candidate) == (404, "not_found")

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "not json",
            "[]",
            "null",
            '{"schema": 1',
            "[" * 100_000,
        ],
    )
    def test_a_file_that_is_not_json_or_not_an_object_is_not_used(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], text: str
    ) -> None:
        self.valid(bakeoffs, workspace, built)
        bakeoff_id, candidate = built

        file_of(workspace, bakeoff_id, candidate).write_text(text, "utf-8")

        assert run_shown(bakeoffs, bakeoff_id, candidate) is None

    @pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
    def test_a_number_that_json_does_not_have_is_not_used(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], constant: str
    ) -> None:
        saved = self.valid(bakeoffs, workspace, built)
        bakeoff_id, candidate = built
        text = json.dumps({**saved, "result": {"type": "float", "value": 0}}).replace(
            '"value": 0', f'"value": {constant}'
        )

        file_of(workspace, bakeoff_id, candidate).write_text(text, "utf-8")

        assert run_shown(bakeoffs, bakeoff_id, candidate) is None

    def test_a_file_that_is_too_big_a_link_or_not_a_file_is_not_used(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], tmp_path: Path
    ) -> None:
        saved = self.valid(bakeoffs, workspace, built)
        bakeoff_id, candidate = built
        path = file_of(workspace, bakeoff_id, candidate)

        path.write_text(json.dumps({**saved, "printed": "x" * (kept_runs.MAX_RUN_BYTES + 1)}), "utf-8")
        assert run_shown(bakeoffs, bakeoff_id, candidate) is None

        elsewhere = tmp_path / "elsewhere.json"
        elsewhere.write_text(json.dumps(saved), "utf-8")
        path.unlink()
        path.symlink_to(elsewhere)
        assert run_shown(bakeoffs, bakeoff_id, candidate) is None
        path.unlink()
        path.mkdir()
        assert run_shown(bakeoffs, bakeoff_id, candidate) is None
        path.rmdir()
        path.write_text(json.dumps(saved), "utf-8")
        assert run_shown(bakeoffs, bakeoff_id, candidate) is not None

    def test_a_folder_of_runs_that_is_a_link_is_not_read_from_or_written_to(
        self, bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str], tmp_path: Path
    ) -> None:
        saved = self.valid(bakeoffs, workspace, built)
        bakeoff_id, candidate = built
        folder = folder_of(workspace, bakeoff_id) / "runs"
        elsewhere = tmp_path / "elsewhere"
        shutil.move(folder, elsewhere)
        folder.symlink_to(elsewhere)

        assert run_shown(bakeoffs, bakeoff_id, candidate) is None
        assert why(bakeoffs.run_of, bakeoff_id, candidate) == (404, "not_found")
        job = run(bakeoffs, bakeoff_id, {candidate: MAP})

        assert job.state == "failed" and "link" in str(job.error)
        assert json.loads((elsewhere / f"{candidate}.json").read_text("utf-8")) == saved
        assert run_shown(bakeoffs, bakeoff_id, candidate) is None
        bakeoffs.remove_candidate(bakeoff_id, candidate)
        assert (elsewhere / f"{candidate}.json").is_file()

    def test_what_is_not_the_id_of_a_method_is_not_a_place_to_read_or_take_away(
        self, workspace: Workspace, tmp_path: Path
    ) -> None:
        (tmp_path / "runs").mkdir()
        (tmp_path / "outside.json").write_text("{}", "utf-8")
        (tmp_path / "runs" / "..json").write_text("{}", "utf-8")

        for bad in ("../outside", "..", "", "ABCDEF01", "abc", "00000000/../x", "0000000g"):
            assert kept_runs.load(tmp_path, bad) is None
            kept_runs.forget(tmp_path, bad)
        assert (tmp_path / "outside.json").is_file() and (tmp_path / "runs" / "..json").is_file()

    def test_what_is_not_a_run_is_not_kept(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not a run"):
            kept_runs.keep(tmp_path, {"candidate": "00000000"})
        with pytest.raises(ValueError, match="not a run"):
            kept_runs.keep(tmp_path, {})
        assert not (tmp_path / "runs").exists()


class TestHowDataIsListed:
    def test_a_file_is_listed_by_its_name_size_and_time_and_not_its_contents(self, tmp_path: Path) -> None:
        path = tmp_path / "a.csv"
        path.write_bytes(b"abc")

        listing = kept_runs.listing_of(path)

        assert (listing["files"], listing["bytes"], listing["complete"]) == (1, 3, True)
        assert len(listing["fingerprint"]) == 64
        assert kept_runs.listing_of(path) == listing
        status = path.stat()
        path.write_bytes(b"abd")
        os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns))
        assert kept_runs.listing_of(path)["fingerprint"] == listing["fingerprint"]
        path.write_bytes(b"abcd")
        assert kept_runs.listing_of(path)["fingerprint"] != listing["fingerprint"]

    def test_a_file_that_is_of_another_size_and_of_the_time_that_it_was_is_not_the_same_file(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "a.csv"
        path.write_bytes(b"abc")
        listing = kept_runs.listing_of(path)
        status = path.stat()

        path.write_bytes(b"abcd")
        os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns))

        assert kept_runs.listing_of(path)["fingerprint"] != listing["fingerprint"]

    def test_a_file_in_a_folder_that_was_changed_at_another_time_is_not_the_same_file(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        path = tmp_path / "sub" / "a.csv"
        path.write_bytes(b"abc")
        listing = kept_runs.listing_of(tmp_path)
        status = path.stat()

        os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns + 10**9))

        assert kept_runs.listing_of(tmp_path)["fingerprint"] != listing["fingerprint"]

    def test_a_file_that_is_in_another_folder_is_not_the_same_file(self, tmp_path: Path) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / "a" / "x.csv").write_bytes(b"abc")
        listing = kept_runs.listing_of(tmp_path)

        (tmp_path / "a" / "x.csv").rename(tmp_path / "b" / "x.csv")

        assert kept_runs.listing_of(tmp_path)["fingerprint"] != listing["fingerprint"]

    def test_what_is_listed_does_not_depend_on_the_order_that_a_folder_is_read_in(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ("a/x.txt", "a/z.txt", "b/y.txt", "c/w.txt", "m.txt", "n.txt"):
            (tmp_path / name).parent.mkdir(exist_ok=True)
            (tmp_path / name).write_bytes(b"1")
        first = kept_runs.listing_of(tmp_path)

        def backwards(top: str, followlinks: bool = False) -> Any:
            names = sorted(os.listdir(top), reverse=True)
            folders = [name for name in names if (Path(top) / name).is_dir()]
            yield top, folders, [name for name in names if name not in folders]
            for folder in folders:
                yield from backwards(os.path.join(top, folder))

        monkeypatch.setattr(kept_runs.os, "walk", backwards)

        assert kept_runs.listing_of(tmp_path) == first

    def test_a_folder_is_not_gone_through_any_more_once_the_most_that_are_listed_are(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kept_runs, "MAX_LISTED", 2)
        for number in range(6):
            (tmp_path / f"d{number}").mkdir()
            (tmp_path / f"d{number}" / "f.txt").write_bytes(b"1")
        gone: list[str] = []
        walk = os.walk

        def counting(*arguments: Any, **options: Any) -> Any:
            for entry in walk(*arguments, **options):
                gone.append(entry[0])
                yield entry

        monkeypatch.setattr(kept_runs.os, "walk", counting)

        listing = kept_runs.listing_of(tmp_path)

        assert (listing["files"], listing["complete"]) == (2, False)
        assert len(gone) == 4

    def test_a_folder_is_listed_with_what_is_in_it_and_the_names_are_part_of_what_is_told_apart(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "x.txt").write_bytes(b"12")
        (tmp_path / "sub" / "y.txt").write_bytes(b"345")
        first = kept_runs.listing_of(tmp_path)

        assert (first["files"], first["bytes"], first["complete"]) == (2, 5, True)
        (tmp_path / "sub" / "y.txt").rename(tmp_path / "sub" / "z.txt")
        second = kept_runs.listing_of(tmp_path)
        assert (second["files"], second["bytes"]) == (2, 5) and second["fingerprint"] != first["fingerprint"]

    def test_a_link_is_not_followed_and_is_not_listed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "big.txt").write_bytes(b"x" * 100)
        folder = tmp_path / "folder"
        folder.mkdir()
        (folder / "a.txt").write_bytes(b"12")
        (folder / "link").symlink_to(outside)
        (folder / "file-link").symlink_to(outside / "big.txt")

        listing = kept_runs.listing_of(folder)

        assert (listing["files"], listing["bytes"]) == (1, 2)
        assert kept_runs.listing_of(folder / "link")["files"] == 0

    def test_no_more_files_than_the_most_are_listed_and_it_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kept_runs, "MAX_LISTED", 3)
        for number in range(5):
            (tmp_path / f"{number}.txt").write_bytes(b"1")

        listing = kept_runs.listing_of(tmp_path)

        assert (listing["files"], listing["complete"]) == (3, False)

    def test_what_is_not_there_is_listed_as_nothing(self, tmp_path: Path) -> None:
        listing = kept_runs.listing_of(tmp_path / "gone")

        assert (listing["files"], listing["bytes"], listing["complete"]) == (0, 0, True)

    def test_a_result_as_long_as_the_start_that_is_shown_of_it_is_not_cut(self) -> None:
        at = kept_runs.PREVIEW_CHARS

        exact = kept_runs.preview_of({"type": "str", "value": "x" * (at - 2)})
        over = kept_runs.preview_of({"type": "str", "value": "x" * (at - 1)})

        assert exact is not None and over is not None
        assert (exact["chars"], exact["cut"], len(exact["start"])) == (at, False, at)
        assert (over["chars"], over["cut"], len(over["start"])) == (at + 1, True, at)

    def test_a_result_that_is_nothing_is_shown_as_nothing(self) -> None:
        assert kept_runs.preview_of(None) is None
        shown = kept_runs.preview_of({"type": "int", "value": 3})
        assert shown == {"type": "int", "plain": True, "chars": 1, "start": "3", "cut": False}


@pytest.fixture
def shapes(bakeoffs: Bakeoffs, workspace: Workspace, replays: Replays, built: tuple[str, str]) -> dict[str, Any]:
    """A run of a method of each of the three states, of data that was put against a card and that the person went on
    with, so that each has all that a run of its state has, and a scope that was checked."""
    bakeoff_id, candidate = built
    bakeoffs.go_on_with(bakeoff_id, candidate, say_outside(bakeoffs, bakeoff_id, candidate))
    found = {}
    run(bakeoffs, bakeoff_id, {candidate: TALLY})
    found["ran"] = kept_of(workspace, bakeoff_id, candidate)
    replays.plays["tally"] = answer(
        None, ok=False, error={"type": "ValueError", "message": "x", "traceback": [], "cell": None}
    )
    run(bakeoffs, bakeoff_id, {candidate: TALLY})
    found["failed"] = kept_of(workspace, bakeoff_id, candidate)
    run(bakeoffs, bakeoff_id, {candidate: {"tool": "nothing", "arguments": {}}})
    found["not_run"] = kept_of(workspace, bakeoff_id, candidate)

    return found


AN_OBJECT = {"type": "int", "value": 1}
WRONG_FOR_ONE_STATE: dict[str, tuple[str, Callable[[dict[str, Any]], Any]]] = {
    "ran-with-why": ("ran", lambda saved: saved.update(why="error")),
    "ran-with-reason": ("ran", lambda saved: saved.update(reason="x")),
    "ran-without-arguments": ("ran", lambda saved: saved.update(arguments=None)),
    "ran-without-seconds": ("ran", lambda saved: saved.update(seconds=None)),
    "ran-without-result": ("ran", lambda saved: saved.update(result=None)),
    "ran-with-a-result-of-no-type": ("ran", lambda saved: saved.update(result={"value": 1})),
    "ran-without-tool": ("ran", lambda saved: saved.update(tool=None)),
    "ran-without-data": ("ran", lambda saved: saved.update(data=None)),
    "ran-without-method": ("ran", lambda saved: saved.update(method=None)),
    "ran-in-no-time": ("ran", lambda saved: saved.update(seconds=float("inf"))),
    "ran-in-less-than-no-time": ("ran", lambda saved: saved.update(seconds=-0.5)),
    "ran-with-arguments-that-are-not-json": ("ran", lambda saved: saved.update(arguments={"a": float("nan")})),
    "ran-with-a-result-that-is-not-json": (
        "ran",
        lambda saved: saved.update(result={"type": "float", "value": float("nan")}),
    ),
    "ran-with-too-long-arguments": (
        "ran",
        lambda saved: saved.update(arguments={"a": "x" * kept_runs.MAX_ARGUMENTS_CHARS}),
    ),
    "failed-without-tool": ("failed", lambda saved: saved.update(tool=None)),
    "failed-without-data": ("failed", lambda saved: saved.update(data=None)),
    "failed-without-method": ("failed", lambda saved: saved.update(method=None)),
    "failed-for-no-reason-that-there-is": ("failed", lambda saved: saved.update(why="outside")),
    "failed-for-a-reason-that-is-not-one": ("failed", lambda saved: saved.update(why="because")),
    "failed-without-saying-why-in-words": ("failed", lambda saved: saved.update(reason="")),
    "failed-saying-more-than-can-be-kept": (
        "failed",
        lambda saved: saved.update(reason="x" * (kept_runs.MAX_REASON_CHARS + 1)),
    ),
    "failed-without-arguments": ("failed", lambda saved: saved.update(arguments=None)),
    "failed-with-a-result": ("failed", lambda saved: saved.update(result=AN_OBJECT)),
    "not-run-for-a-reason-that-is-one-of-failing": ("not_run", lambda saved: saved.update(why="error")),
    "not-run-for-a-reason-that-is-not-one": ("not_run", lambda saved: saved.update(why="because")),
    "not-run-without-saying-why-in-words": ("not_run", lambda saved: saved.update(reason="")),
    "not-run-saying-more-than-can-be-kept": (
        "not_run",
        lambda saved: saved.update(reason="x" * (kept_runs.MAX_REASON_CHARS + 1)),
    ),
    "not-run-in-some-time": ("not_run", lambda saved: saved.update(seconds=1.0)),
    "not-run-with-a-result": ("not_run", lambda saved: saved.update(result=AN_OBJECT)),
    "not-run-with-what-was-printed": ("not_run", lambda saved: saved.update(printed="x")),
    "of-a-state-that-is-not-one": ("not_run", lambda saved: saved.update(state="done")),
    "ran-with-the-method-of-no-agent-it-says": ("ran", lambda saved: saved["method"].update(agent="a\x00")),
    "failed-with-the-data-at-a-place-with-a-control-character": (
        "failed",
        lambda saved: saved["data"].update(path="/data/a\x00"),
    ),
}
WRONG_FOR_EVERY_STATE: dict[str, Callable[[dict[str, Any]], Any]] = {
    "with-a-key-that-is-not-a-hash": lambda saved: saved["scope"].update(key="short"),
    "with-a-key-for-what-was-not-put-against-a-card": lambda saved: saved["scope"].update(
        checked=False, outcome=None, went_on=False, key="a" * 64
    ),
    "with-an-outcome-for-what-was-not-put-against-a-card": lambda saved: saved["scope"].update(
        checked=False, went_on=False, key=None
    ),
    "with-a-going-on-for-what-was-not-put-against-a-card": lambda saved: saved["scope"].update(
        checked=False, outcome=None, went_on=True, key=None
    ),
}
WRONG_SHAPES = {
    **WRONG_FOR_ONE_STATE,
    **{
        f"{state}-{name}": (state, change)
        for state in ("ran", "failed", "not_run")
        for name, change in WRONG_FOR_EVERY_STATE.items()
    },
}


class TestWhatEachStateOfARunHas:
    @pytest.mark.parametrize("state", ["ran", "failed", "not_run"])
    def test_a_run_of_each_state_as_it_is_kept_is_one(self, shapes: dict[str, Any], state: str) -> None:
        saved = shapes[state]

        assert saved["state"] == state and saved["scope"]["checked"] and saved["scope"]["key"] is not None
        assert kept_runs.is_run(saved, saved["candidate"])

    @pytest.mark.parametrize(
        ("state", "change"), [pytest.param(state, change, id=name) for name, (state, change) in WRONG_SHAPES.items()]
    )
    def test_what_does_not_have_what_a_run_of_its_state_has_is_not_one(
        self, shapes: dict[str, Any], state: str, change: Callable[[dict[str, Any]], Any]
    ) -> None:
        saved = copy.deepcopy(shapes[state])

        change(saved)

        assert not kept_runs.is_run(saved, saved["candidate"])

    def test_a_file_of_the_most_that_is_kept_is_used_and_of_one_byte_more_is_not(
        self, workspace: Workspace, shapes: dict[str, Any], built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        saved = shapes["ran"]
        wrapper = len(json.dumps({**saved, "result": {"type": "str", "value": ""}}))
        text = json.dumps({**saved, "result": {"type": "str", "value": "x" * (kept_runs.MAX_RUN_BYTES - wrapper - 99)}})
        path = file_of(workspace, bakeoff_id, candidate)

        path.write_text(text + " " * (kept_runs.MAX_RUN_BYTES - len(text)), "utf-8")
        assert path.stat().st_size == kept_runs.MAX_RUN_BYTES
        assert kept_runs.load(folder_of(workspace, bakeoff_id), candidate) is not None

        path.write_text(text + " " * (kept_runs.MAX_RUN_BYTES + 1 - len(text)), "utf-8")
        assert path.stat().st_size == kept_runs.MAX_RUN_BYTES + 1
        assert kept_runs.load(folder_of(workspace, bakeoff_id), candidate) is None

    def test_a_run_of_the_most_that_can_be_kept_is_kept_and_of_one_byte_more_is_not(
        self, shapes: dict[str, Any]
    ) -> None:
        def with_value(length: int) -> dict[str, Any]:
            return {**shapes["ran"], "result": {"type": "str", "value": "x" * length}}

        most = kept_runs.MAX_RUN_BYTES - len(kept_runs.encode(with_value(0)))

        assert len(kept_runs.encode(with_value(most))) == kept_runs.MAX_RUN_BYTES
        with pytest.raises(ValueError, match="too big"):
            kept_runs.encode(with_value(most + 1))

    def test_what_is_not_the_id_of_a_method_does_not_find_a_run_even_where_one_is_that_says_it_is_of_it(
        self, shapes: dict[str, Any], tmp_path: Path
    ) -> None:
        (tmp_path / "runs").mkdir()
        (tmp_path / "outside.json").write_text(json.dumps({**shapes["ran"], "candidate": "../outside"}), "utf-8")

        assert kept_runs.load(tmp_path, "../outside") is None

    def test_what_is_not_as_it_was_is_told_by_the_name_and_listing_of_the_data_and_by_the_method(
        self, shapes: dict[str, Any]
    ) -> None:
        ran, not_run = shapes["ran"], shapes["not_run"]
        same = {key: ran["data"][key] for key in ("own", "files", "bytes", "fingerprint", "complete")}

        assert kept_runs.since(ran, same, ran["method"]) == []
        assert kept_runs.since(ran, {**same, "own": "other.csv"}, ran["method"]) == ["data"]
        assert kept_runs.since(ran, {**same, "fingerprint": "0" * 64}, ran["method"]) == ["data"]
        assert kept_runs.since(ran, None, ran["method"]) == ["data"]
        assert kept_runs.since(ran, same, {**ran["method"], "commit": "0" * 7}) == ["method"]
        assert kept_runs.since(ran, same, None) == ["method"]
        assert kept_runs.since(not_run, None, None) == []
        assert kept_runs.since(not_run, same, ran["method"]) == []


def method_of(function: str, source: str, parameters: list[tuple[str, str, bool]]) -> dict[str, Any]:
    """A tool as it is kept, of a function that has these parameters, each with its name, type, and whether it is needed
    to be given."""
    return {
        "name": function,
        "source": source,
        "signature": [
            {"name": name, "type": kind, "required": required, "default": None} for name, kind, required in parameters
        ],
    }


FOUR = method_of(
    "f",
    'def f(a: int, b: int, c: int, d: int, x: float = 1.0) -> int:\n    """Does it."""\n    return a\n',
    [("a", "int", True), ("b", "int", True), ("c", "int", True), ("d", "int", True), ("x", "float", False)],
)
ONE_AND_A_PLACE = method_of(
    "g",
    'def g(x: int, p: str) -> int:\n    """Does it."""\n    return x\n',
    [("x", "int", True), ("p", "str", True)],
)


class TestWhatTheCheckOfACallLooksAt:
    def test_no_more_than_three_of_what_is_not_taken_or_not_given_are_named(self, tmp_path: Path) -> None:
        assert running.check_call(FOUR, {}, "own", tmp_path) == ["The tool needs a, b, c, which was not given"]
        given_all = {"a": 1, "b": 1, "c": 1, "d": 1}

        assert running.check_call(FOUR, {**given_all, "q": 1, "r": 2, "s": 3, "t": 4}, "own", tmp_path) == [
            "The tool does not take q, r, s"
        ]

    def test_a_number_that_json_writes_as_a_word_is_a_number_of_the_type_it_is(self, tmp_path: Path) -> None:
        arguments = {"a": 1, "b": 1, "c": 1, "d": 1, "x": {"$float": "inf"}}

        assert running.check_call(FOUR, arguments, "own", tmp_path) == []
        assert running.check_call(FOUR, {**arguments, "a": {"$float": "inf"}}, "own", tmp_path) == [
            "What is given for a is not of the type that the tool says"
        ]

    def test_the_places_in_the_data_are_looked_at_only_when_nothing_else_is_wrong(self, tmp_path: Path) -> None:
        assert running.check_call(ONE_AND_A_PLACE, {"x": "no", "p": "/data/elsewhere"}, "own", tmp_path) == [
            "What is given for x is not of the type that the tool says"
        ]
        assert running.check_call(ONE_AND_A_PLACE, {"x": 1, "p": "/data/elsewhere"}, "own", tmp_path) == [
            "'/data/elsewhere' is not in the data of this bake-off, which is at /data/own"
        ]

    def test_arguments_that_are_nested_past_what_can_be_written_are_not_json_and_are_not_a_crash(
        self, tmp_path: Path
    ) -> None:
        deep: Any = []
        for _ in range(100_000):
            deep = [deep]

        problems = running.check_call(FOUR, {"a": deep}, "own", tmp_path)

        assert len(problems) == 1 and "are not JSON" in problems[0]

    @pytest.mark.parametrize("wrap", [lambda value: [value], lambda value: {"k": value}], ids=["lists", "objects"])
    def test_a_place_is_looked_for_in_what_is_nested_to_a_depth_and_not_in_what_is_deeper(
        self, wrap: Callable[[Any], Any]
    ) -> None:
        for levels, found in ((running.MAX_DEPTH, ["x"]), (running.MAX_DEPTH + 1, [])):
            value: Any = "x"
            for _ in range(levels):
                value = wrap(value)

            assert list(running.strings_in(value)) == found

    def test_a_place_that_only_starts_as_the_data_does_is_not_in_it(self, tmp_path: Path) -> None:
        (tmp_path / "2").mkdir()
        (tmp_path / "2" / "x").write_bytes(b"")

        problems = running.check_places({"p": "/data/own2/x"}, "own", tmp_path)

        assert problems == ["'/data/own2/x' is not in the data of this bake-off, which is at /data/own"]

    @pytest.mark.parametrize(("wrong", "said"), [(3, 3), (4, 4)])
    def test_up_to_three_places_that_are_wrong_are_all_said_and_of_more_the_number_that_are_left_out_is(
        self, tmp_path: Path, wrong: int, said: int
    ) -> None:
        places = {f"p{number}": f"/data/other{number}" for number in range(wrong)}

        problems = running.check_places(places, "own", tmp_path)

        assert len(problems) == said
        assert problems[3:] == (["and 1 more places that are not as they should be"] if wrong == 4 else [])
        assert all("is not in the data of this bake-off" in each for each in problems[:3])


class TestWhatIsSaidOfAMethodThatIsNotRun:
    def test_the_name_of_a_tool_that_is_not_there_is_said_as_far_as_it_is_useful_to(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built

        run(bakeoffs, bakeoff_id, {candidate: {"tool": "x" * 100}})

        reason = kept_of(workspace, bakeoff_id, candidate)["reason"]
        assert f"no tool called '{'x' * 59}…'" in reason and "x" * 60 not in reason

    def test_data_that_is_outside_with_nothing_said_of_why_is_still_not_run_on(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bakeoff_id, candidate = built
        scope_of = bakeoff_scope.scope_of

        def without_warnings(*arguments: Any) -> dict[str, Any]:
            return {
                **scope_of(*arguments),
                "checked": True,
                "outcome": bakeoff_scope.OUTSIDE,
                "key": "a" * 64,
                "warnings": [],
            }

        monkeypatch.setattr(bakeoff_scope, "scope_of", without_warnings)

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"]) == ("not_run", "outside")
        assert saved["reason"].endswith("The method card does not cover it.")

    def test_a_log_says_why_a_method_was_not_run_in_words(self, bakeoffs: Bakeoffs, two: tuple[str, str, str]) -> None:
        bakeoff_id, first, second = two

        job = run(bakeoffs, bakeoff_id, {first: {"tool": "nothing"}, second: MAP})

        assert job.snapshot(0)["log"]["lines"] == ["CellMapper: not run, no tool", "Labeller: ran"]

    def test_the_tier_of_the_tool_is_the_tool_s_and_is_not_said_to_be_another(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        built: tuple[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bakeoff_id, candidate = built
        runnable = running.given.runnable

        def of_tier_b(*arguments: Any) -> Any:
            found, problem = runnable(*arguments)
            assert found is not None
            return replace(found, tools=tuple({**tool, "tier": "B"} for tool in found.tools)), problem

        monkeypatch.setattr(running.given, "runnable", of_tier_b)

        run(bakeoffs, bakeoff_id, {candidate: MAP})

        assert kept_of(workspace, bakeoff_id, candidate)["tool"]["tier"] == "B"

    def test_a_method_whose_tools_are_not_all_made_is_not_the_method_that_a_run_was_of(
        self, bakeoffs: Bakeoffs, built: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: MAP})
        assert seen(bakeoffs, bakeoff_id, candidate)["run"]["since"] == []
        kept_tools_of = running.kept_tools_of

        def unfinished(*arguments: Any) -> Any:
            first, kept = kept_tools_of(*arguments)
            return first, {**kept, "complete": False}

        monkeypatch.setattr(running, "kept_tools_of", unfinished)

        assert seen(bakeoffs, bakeoff_id, candidate)["run"]["since"] == ["method"]


class TestStartingARun:
    def test_docker_that_does_not_say_what_is_wrong_with_it_is_said_not_to_be_running(
        self, bakeoffs: Bakeoffs, built: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bakeoff_id, candidate = built
        monkeypatch.setattr(building, "ready", lambda *arguments: (False, None))

        error = refused(bakeoffs.start_run, bakeoff_id, {candidate: MAP})

        assert (error.status, error.code) == (422, "docker_missing") and "Docker is not running" in str(error)

    def test_a_run_that_is_started_as_another_is_is_busy_whatever_was_looked_at_first(
        self, bakeoffs: Bakeoffs, replays: Replays, built: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bakeoff_id, candidate = built
        gate = hold(replays, "map_cells")
        job = bakeoffs.start_run(bakeoff_id, {candidate: MAP})
        assert replays.began["map_cells"].wait(10)
        monkeypatch.setattr(bakeoffs, "check_idle", lambda bakeoff_id: None)

        error = refused(bakeoffs.start_run, bakeoff_id, {candidate: MAP})

        assert (error.status, error.code) == (409, "busy") and job.title in str(error)
        gate.set()
        finish(job)

    def test_a_call_that_is_not_an_object_is_refused_by_whatever_asks_for_it(
        self, bakeoffs: Bakeoffs, replays: Replays, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        before = len(replays.runs)

        assert why(bakeoffs.start_run, bakeoff_id, {candidate: ["tool"]}) == (422, "invalid")
        assert len(replays.runs) == before and bakeoffs.calling(bakeoff_id) is None

    def test_the_job_says_what_it_is_for(self, bakeoffs: Bakeoffs, built: tuple[str, str]) -> None:
        bakeoff_id, candidate = built

        job = bakeoffs.start_run(bakeoff_id, {candidate: MAP})
        finish(job)

        assert job.title == f"Running the methods: {bakeoffs.view(bakeoff_id)['title']}"


class TestTheApi:
    def test_methods_are_run_as_a_job_and_what_came_of_each_is_seen_in_the_list_and_asked_for_whole(
        self, client: TestClient, built: tuple[str, str], replays: Replays
    ) -> None:
        bakeoff_id, candidate = built
        replays.plays["map_cells"] = gives(list(range(300)))
        url = f"/api/bakeoffs/{bakeoff_id}"

        started = client.post(f"{url}/run", json={"calls": {candidate: MAP}, "minutes": 2})

        assert started.status_code == 202
        job = started.json()
        assert (job["kind"], job["subject"]) == (RUN_JOB, bakeoff_id)
        assert job_done(client, job)["state"] == "succeeded"
        assert replays.runs[-1]["seconds"] == 120
        listed = next(each for each in client.get(url).json()["candidates"] if each["id"] == candidate)
        assert listed["run"]["state"] == "ran" and listed["run"]["result"]["cut"] is True
        assert listed["run"]["since"] == [] and "value" not in listed["run"]["result"]
        whole = client.get(f"{url}/candidates/{candidate}/run")
        assert whole.status_code == 200
        assert whole.json()["result"]["value"] == list(range(300)) and whole.json()["since"] == []

    def test_what_is_asked_wrongly_is_refused_and_nothing_is_started(
        self, client: TestClient, built: tuple[str, str], replays: Replays
    ) -> None:
        bakeoff_id, candidate = built
        url = f"/api/bakeoffs/{bakeoff_id}/run"
        before = len(replays.runs)

        for bad in (
            {},
            {"minutes": 2},
            {"calls": {}},
            {"calls": []},
            {"calls": {candidate: {}}},
            {"calls": {candidate: {"tool": 3}}},
            {"calls": {candidate: ["tool"]}},
            {"calls": {candidate: {"tool": "map_cells", "other": 1}}},
            {"calls": {candidate: {"tool": "map_cells", "arguments": [1]}}},
            {"calls": {candidate: MAP}, "minutes": "2"},
            {"calls": {candidate: MAP}, "minutes": True},
            {"calls": {candidate: MAP}, "minutes": 0},
            {"calls": {candidate: MAP}, "minutes": 2.5},
            {"calls": {candidate: MAP}, "other": 1},
            {"calls": {candidate: {"tool": "x" * 300}}},
            {"calls": {"x" * 65: MAP}},
        ):
            assert client.post(url, json=bad).status_code == 422, bad
        assert client.post("/api/bakeoffs/nope/run", json={"calls": {candidate: MAP}}).status_code == 404
        assert client.post(url, json={"calls": {"00000000": MAP}}).status_code == 404
        assert len(replays.runs) == before

    def test_a_run_that_is_not_there_is_not_found_and_nothing_of_it_is_open_to_one_without_the_token(
        self, client: TestClient, built: tuple[str, str], workspace: Workspace
    ) -> None:
        bakeoff_id, candidate = built

        assert client.get(f"/api/bakeoffs/{bakeoff_id}/candidates/{candidate}/run").status_code == 404
        assert client.get(f"/api/bakeoffs/nope/candidates/{candidate}/run").status_code == 404
        app = create_app(workspace.root, token=TOKEN, check_keys=False, max_upload_bytes=100_000)
        with TestClient(app, base_url="http://127.0.0.1") as anyone:
            assert anyone.post(f"/api/bakeoffs/{bakeoff_id}/run", json={"calls": {candidate: MAP}}).status_code == 401
            assert anyone.get(f"/api/bakeoffs/{bakeoff_id}/candidates/{candidate}/run").status_code == 401

    def test_a_method_that_is_not_run_says_why_over_the_api_too(
        self, client: TestClient, built: tuple[str, str], workspace: Workspace
    ) -> None:
        bakeoff_id, candidate = built
        client.patch(f"/api/bakeoffs/{bakeoff_id}", json={"described": {"species": "zebrafish"}})
        url = f"/api/bakeoffs/{bakeoff_id}"

        job = client.post(f"{url}/run", json={"calls": {candidate: MAP}}).json()

        assert job_done(client, job)["state"] == "succeeded"
        found = client.get(f"{url}/candidates/{candidate}/run").json()
        assert (found["state"], found["why"], found["tool"], found["result"]) == ("not_run", "outside", None, None)
        assert found["scope"]["outcome"] == "outside"
