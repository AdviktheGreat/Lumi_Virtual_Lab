"""Tests of the runs that answer Biomni's benchmarks: fetching their files, making a run, answering it as a job, and
what is found."""

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import requests
from conftest import TEST_MODEL, FakeClient, parsed_response, text_response
from fastapi.testclient import TestClient
from test_benchmarks import benchmark_files, sha256

from virtual_lab.benchmarks import BenchmarkError, LabBench, MultipleChoiceOutput
from virtual_lab.constants import BENCHMARK_FILES
from virtual_lab.server.app import create_app
from virtual_lab.server.benchmarks import FILES_DIR, LAB_FILE, RUNS_DIR, BenchmarkRuns
from virtual_lab.server.errors import ApiError
from virtual_lab.server.jobs import Job, Jobs
from virtual_lab.server.workspace import Settings, Workspace

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}

DBQA = "lab_bench_dbqa"


@pytest.fixture(autouse=True)
def model_client(fake_client: FakeClient) -> FakeClient:
    return fake_client


@pytest.fixture
def stand_ins(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Small stand-ins for the benchmarks' files, pinned in place of the real ones."""
    made = benchmark_files()
    for name, data in made.items():
        monkeypatch.setitem(BENCHMARK_FILES, name, sha256(data))

    return made


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    store = Workspace(tmp_path / "workspace")
    store.save_settings(Settings(model=TEST_MODEL, max_cost=None))

    return store


@pytest.fixture
def jobs() -> Iterator[Jobs]:
    kept = Jobs()
    yield kept
    kept.close()


@pytest.fixture
def runs(workspace: Workspace, jobs: Jobs) -> BenchmarkRuns:
    return BenchmarkRuns(workspace, jobs, lambda model: [])


def put_files(workspace: Workspace, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        path = workspace.benchmarks_dir / FILES_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


@pytest.fixture
def fetched(workspace: Workspace, stand_ins: dict[str, bytes]) -> dict[str, bytes]:
    put_files(workspace, stand_ins)

    return stand_ins


@pytest.fixture
def client(workspace: Workspace) -> Iterator[TestClient]:
    app = create_app(workspace.root, token=TOKEN, check_keys=False)
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


def refused(call: Any, *args: Any, **kwargs: Any) -> ApiError:
    with pytest.raises(ApiError) as caught:
        call(*args, **kwargs)

    return caught.value


def finish(job: Job, seconds: float = 20) -> Job:
    deadline = time.monotonic() + seconds
    while job.active:
        assert time.monotonic() < deadline, "the job did not finish"
        time.sleep(0.01)

    return job


def the_questions(workspace: Workspace, subset: str = "test") -> list[Any]:
    return list(LabBench(workspace.benchmarks_dir / FILES_DIR, "DbQA", subset))  # type: ignore[arg-type]


def answer(fake_client: FakeClient, *letters: str) -> None:
    """Queues, for each question, what the agent says and what the extractor reads out of it."""
    fake_client.completions.responses = [text_response(f"[ANSWER]{letter}[/ANSWER]") for letter in letters]
    fake_client.completions.parsed_responses = [
        parsed_response(parsed=MultipleChoiceOutput(choice=letter)) for letter in letters
    ]


def wrong(letter: str) -> str:
    return "A" if letter != "A" else "B"


def start(runs: BenchmarkRuns, run: str, **options: Any) -> Job:
    options = {"max_cost": 5, "max_cost_per_question": None, "retry_failed": False, **options}

    return finish(runs.start(run, **options))


def make(runs: BenchmarkRuns, title: str = "DbQA", benchmark: str = DBQA, solver: str = "single", **kwargs: Any) -> str:
    return runs.create(title, benchmark, solver, **kwargs)


class TestFiles:
    def test_nothing_is_ready_before_the_files_are_fetched(
        self, runs: BenchmarkRuns, stand_ins: dict[str, bytes]
    ) -> None:
        described = runs.describe()

        assert described["files"]["ready"] is False
        assert sorted(described["files"]["missing"]) == sorted(BENCHMARK_FILES)
        assert described["runs"] == []
        assert [benchmark["id"] for benchmark in described["benchmarks"]] == [
            "biomni_eval1",
            "lab_bench_dbqa",
            "lab_bench_seqqa",
            "hle",
        ]
        assert all(benchmark["questions"] is None for benchmark in described["benchmarks"])

    def test_a_run_needs_the_files(self, runs: BenchmarkRuns, stand_ins: dict[str, bytes]) -> None:
        error = refused(make, runs)

        assert (error.status, error.code) == (409, "files_missing")

    def test_fetching_puts_the_files_where_they_are_kept_and_says_what_they_hold(
        self, runs: BenchmarkRuns, workspace: Workspace, stand_ins: dict[str, bytes]
    ) -> None:
        runs.download = lambda directory: put_files(workspace, stand_ins)

        described = runs.fetch_files()

        assert described["files"] == {
            "ready": True,
            "directory": str(workspace.benchmarks_dir / FILES_DIR),
            "missing": [],
            "problem": None,
        }
        by_id = {benchmark["id"]: benchmark for benchmark in described["benchmarks"]}
        assert by_id["biomni_eval1"]["questions"] == 6
        assert {task["name"]: task["questions"] for task in by_id["biomni_eval1"]["tasks"]} == {
            "crispr_delivery": 2,
            "gwas_causal_gene_opentargets": 1,
            "gwas_variant_prioritization": 1,
            "rare_disease_diagnosis": 1,
            "patient_gene_detection": 1,
        }
        assert {subset["id"]: subset["questions"] for subset in by_id["lab_bench_dbqa"]["subsets"]} == {
            "test": 5,
            "sampled": 3,
            "all": 9,
        }
        assert {subset["id"]: subset["questions"] for subset in by_id["lab_bench_seqqa"]["subsets"]} == {
            "test": 5,
            "sampled": 3,
            "all": 7,
        }
        assert by_id["lab_bench_dbqa"]["questions"] == 5
        assert (by_id["hle"]["questions"], by_id["hle"]["images"]) == (2, 1)

    def test_a_file_that_is_not_the_pinned_one_is_not_ready(
        self, runs: BenchmarkRuns, workspace: Workspace, fetched: dict[str, bytes]
    ) -> None:
        assert runs.describe()["files"]["ready"] is True
        changed = next(iter(fetched))
        (workspace.benchmarks_dir / FILES_DIR / changed).write_bytes(b"not it")

        described = runs.describe()

        assert described["files"]["ready"] is False
        assert described["files"]["missing"] == [changed]

    def test_files_that_cannot_be_fetched_say_why(self, runs: BenchmarkRuns, stand_ins: dict[str, bytes]) -> None:
        def changed(directory: Path) -> None:
            raise BenchmarkError("the publisher has changed it")

        def unreachable(directory: Path) -> None:
            raise requests.ConnectionError("no route")

        runs.download = changed
        error = refused(runs.fetch_files)
        assert (error.status, error.code) == (502, "unexpected_files")
        assert "the publisher has changed it" in error.message

        runs.download = unreachable
        error = refused(runs.fetch_files)
        assert (error.status, error.code) == (502, "unreachable")
        assert "no route" in error.message


class TestMakingARun:
    def test_a_run_keeps_what_it_asks_and_who_answers(
        self, runs: BenchmarkRuns, workspace: Workspace, fetched: Any
    ) -> None:
        run = make(runs, "DbQA test")

        lab = json.loads((workspace.benchmarks_dir / RUNS_DIR / run / LAB_FILE).read_text())
        assert run == "dbqa-test"
        assert (lab["benchmark"], lab["solver"], lab["rounds"], lab["limit"], lab["questions"]) == (
            DBQA,
            "single",
            0,
            None,
            5,
        )
        assert lab["options"] == {"subset": "test"}
        assert lab["config"]["model"] == TEST_MODEL
        assert lab["config"]["lead"]["title"] == "Principal Investigator"
        assert lab["config"]["tools"] == []
        assert make(runs, "  DbQA   test ") == "dbqa-test-2"

    def test_the_team_discusses_for_a_round_unless_it_is_told_not_to(self, runs: BenchmarkRuns, fetched: Any) -> None:
        assert runs.view(make(runs, solver="team"))["rounds"] == 1
        assert runs.view(make(runs, solver="team", rounds=0))["rounds"] == 0
        assert runs.view(make(runs, solver="single", rounds=2))["rounds"] == 2

    def test_a_run_can_be_narrowed(self, runs: BenchmarkRuns, fetched: Any) -> None:
        assert runs.view(make(runs, limit=2))["questions"] == 2
        assert runs.view(make(runs, options={"subset": "all"}))["questions"] == 9
        eval1 = make(runs, benchmark="biomni_eval1", options={"tasks": ["crispr_delivery", "crispr_delivery"]})
        assert runs.view(eval1)["questions"] == 2
        assert runs.view(eval1)["options"] == {"tasks": ["crispr_delivery"]}
        assert runs.view(make(runs, benchmark="biomni_eval1", limit=4))["questions"] == 4
        assert runs.view(make(runs, benchmark="hle"))["questions"] == 2
        assert runs.view(make(runs, benchmark="hle", options={"leave_out_images": True}))["questions"] == 1

    @pytest.mark.parametrize("title", ["", "   ", "a" * 201, "bell\x07"])
    def test_a_title_that_cannot_name_a_run_is_refused(self, runs: BenchmarkRuns, fetched: Any, title: str) -> None:
        assert refused(make, runs, title).status == 422

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"benchmark": "mmlu"},
            {"solver": "committee"},
            {"rounds": 6},
            {"rounds": -1},
            {"rounds": True},
            {"limit": 0},
            {"limit": "3"},
            {"options": {"tasks": ["crispr_delivery"]}},
            {"options": {"subset": "everything"}},
            {"options": {"leave_out_images": True}},
            {"benchmark": "biomni_eval1", "options": {"tasks": []}},
            {"benchmark": "biomni_eval1", "options": {"tasks": ["alchemy"]}},
            {"benchmark": "biomni_eval1", "options": {"tasks": "crispr_delivery"}},
            {"benchmark": "hle", "options": {"leave_out_images": "yes"}},
        ],
    )
    def test_what_does_not_fit_the_benchmark_is_refused(
        self, runs: BenchmarkRuns, fetched: Any, kwargs: dict[str, Any]
    ) -> None:
        error = refused(make, runs, **kwargs)

        assert (error.status, error.code) == (422, "invalid")
        assert not (runs.runs_dir.exists() and any(runs.runs_dir.iterdir()))

    def test_runs_are_listed_with_the_latest_first(self, runs: BenchmarkRuns, fetched: Any) -> None:
        first = make(runs, "First")
        second = make(runs, "Second")

        listed = runs.describe()["runs"]

        assert [run["id"] for run in listed] == [second, first]
        assert listed[0] == {
            "id": second,
            "title": "Second",
            "benchmark": DBQA,
            "solver": "single",
            "rounds": 0,
            "model": TEST_MODEL,
            "created_at": listed[0]["created_at"],
            "questions": 5,
            "finished": 0,
            "failed": None,
            "accuracy": None,
            "cost": None,
            "spent": None,
            "stopped": None,
            "job": None,
        }


class TestAnswering:
    def test_each_question_is_asked_read_and_scored(
        self, runs: BenchmarkRuns, workspace: Workspace, fetched: Any, fake_client: FakeClient
    ) -> None:
        run = make(runs, limit=3)
        correct = [question.answer for question in the_questions(workspace)[:3]]
        answer(fake_client, correct[0], wrong(correct[1]), correct[2])

        job = start(runs, run)

        assert job.state == "succeeded"
        assert job.message.startswith("Answered 3 of 3 questions, 66.7% right, spending $")
        view = runs.view(run)
        assert (view["finished"], view["failed"], view["accuracy"]) == (3, 0, pytest.approx(2 / 3))
        assert view["metrics"]["accuracy"] == pytest.approx(2 / 3)
        assert [row["state"] for row in view["results"]] == ["answered"] * 3
        assert [row["score"] for row in view["results"]] == [1.0, 0.0, 1.0]
        assert view["results"][0]["prompt"].startswith("The following is a multiple choice question")
        assert view["tasks"] == [{"task": DBQA, "questions": 3, "finished": 3, "accuracy": pytest.approx(2 / 3)}]
        assert view["cost"] > 0
        entry = runs.describe()["runs"][0]
        assert (entry["finished"], entry["accuracy"], entry["failed"], entry["job"]) == (
            3,
            pytest.approx(2 / 3),
            0,
            None,
        )
        assert entry["spent"] == pytest.approx(view["cost"])

    def test_a_question_shows_what_was_asked_what_was_said_and_what_was_read(
        self, runs: BenchmarkRuns, workspace: Workspace, fetched: Any, fake_client: FakeClient
    ) -> None:
        run = make(runs, limit=1)
        correct = the_questions(workspace)[0].answer
        answer(fake_client, correct)
        start(runs, run)

        question = runs.question(run, DBQA, "0")

        assert question["state"] == "answered"
        assert question["prompt"].startswith("The following is a multiple choice question")
        assert question["answer"] == question["correct_answer"] == correct
        assert question["output"] == {"choice": correct}
        assert question["turns"][-1]["message"] == f"[ANSWER]{correct}[/ANSWER]"
        assert question["truncated"] is False
        assert question["usage"]["num_calls"] == 2

    def test_an_unanswered_question_is_shown_with_its_prompt(self, runs: BenchmarkRuns, fetched: Any) -> None:
        run = make(runs, limit=2)

        question = runs.question(run, DBQA, "1")

        assert question["state"] == "unanswered"
        assert question["prompt"].startswith("The following is a multiple choice question")
        assert question["turns"] is None
        assert refused(runs.question, run, DBQA, "2").status == 404

    def test_a_question_that_cannot_be_named_is_not_found(self, runs: BenchmarkRuns, fetched: Any) -> None:
        run = make(runs)

        for task, number in (("../x", "0"), ("", "0"), (DBQA, "x"), (DBQA, "-1"), (DBQA, "1" * 10), ("other", "0")):
            assert refused(runs.question, run, task, number).status == 404
        assert refused(runs.question, "nothing", DBQA, "0").status == 404

    def test_the_team_can_answer(
        self, runs: BenchmarkRuns, fetched: Any, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        run = make(runs, solver="team", rounds=0, limit=1)
        correct = the_questions(workspace)[0].answer
        answer(fake_client, correct)

        job = start(runs, run)

        assert job.message.startswith("Answered 1 of 1 questions, 100.0% right")
        run_file = json.loads((runs.runs_dir / run / "run.json").read_text())
        assert run_file["solver"]["type"] == "team_meeting"
        assert run_file["solver"]["team_lead"]["title"] == "Principal Investigator"

    def test_the_most_it_may_spend_stops_the_run_and_is_said(self, runs: BenchmarkRuns, fetched: Any) -> None:
        run = make(runs)

        job = start(runs, run, max_cost=0)

        assert job.state == "succeeded"
        assert "Stopped:" in job.message and "max_cost" in job.message
        assert runs.describe()["runs"][0]["stopped"] is not None
        assert runs.view(run)["finished"] == 0

    def test_a_request_to_stop_keeps_what_was_answered_and_starting_again_carries_on(
        self, runs: BenchmarkRuns, workspace: Workspace, fetched: Any, fake_client: FakeClient
    ) -> None:
        run = make(runs, limit=3)
        correct = [question.answer for question in the_questions(workspace)[:3]]
        answer(fake_client, correct[0], correct[1], correct[2])
        started, release = threading.Event(), threading.Event()
        real = fake_client.completions.create
        calls = []

        def slow(**kwargs: Any) -> Any:
            calls.append(kwargs)
            # The first question is answered; the second waits
            if len(calls) == 2:
                started.set()
                assert release.wait(10)

            return real(**kwargs)

        fake_client.completions.create = slow

        job = runs.start(run, 5, None, False)
        assert started.wait(10)
        job.request_stop()
        # The meeting leaves while its request is still waiting for a reply
        finish(job)
        release.set()

        assert job.state == "stopped"
        assert job.message == "Stopped. What was answered is kept, and starting again carries on from there."
        view = runs.view(run)
        assert [row["state"] for row in view["results"]] == ["answered", "unanswered", "unanswered"]
        entry = runs.describe()["runs"][0]
        assert (entry["finished"], entry["accuracy"], entry["stopped"]) == (1, 1.0, "Stopped at the person's request")

        fake_client.completions.create = real
        answer(fake_client, correct[1], correct[2])
        job = start(runs, run)

        assert job.message.startswith("Answered 3 of 3 questions, 100.0% right")
        assert runs.describe()["runs"][0]["stopped"] is None

    def test_a_question_that_fails_is_saved_as_a_failure(
        self, runs: BenchmarkRuns, fetched: Any, fake_client: FakeClient
    ) -> None:
        run = make(runs, limit=2)
        fake_client.completions.responses = [text_response("[ANSWER]A[/ANSWER]")] * 2
        fake_client.completions.parsed_responses = [RuntimeError("the extractor is down")] * 2

        job = start(runs, run)

        assert job.state == "succeeded"
        assert "(2 failed)" in job.message
        view = runs.view(run)
        assert (view["finished"], view["failed"], view["accuracy"]) == (2, 2, 0.0)
        assert [row["state"] for row in view["results"]] == ["failed", "failed"]
        assert "the extractor is down" in view["results"][0]["error"]

    def test_one_run_is_answered_at_a_time(self, runs: BenchmarkRuns, jobs: Jobs, fetched: Any) -> None:
        first, second = make(runs, "First"), make(runs, "Second")
        release = threading.Event()
        jobs.start("benchmark", first, "Answering First", lambda job: release.wait(10) and None, exclusive="benchmark")
        try:
            error = refused(runs.start, second, 5, None, False)
            assert (error.status, error.code) == (409, "busy")
            assert error.details["job"]["subject"] == first
            assert refused(runs.delete, first).code == "busy"
        finally:
            release.set()

    def test_a_run_is_answered_with_what_it_was_made_with(
        self, runs: BenchmarkRuns, workspace: Workspace, fetched: Any, fake_client: FakeClient
    ) -> None:
        run = make(runs, limit=1)
        workspace.save_settings(Settings(model="gpt-4.1-mini", max_cost=None))
        answer(fake_client, "A")

        start(runs, run)

        assert {call["model"] for call in fake_client.completions.calls} == {TEST_MODEL}

    @pytest.mark.parametrize("amount", [-1, "5", None, True, float("nan")])
    def test_the_most_it_may_spend_is_an_amount(self, runs: BenchmarkRuns, fetched: Any, amount: Any) -> None:
        run = make(runs)

        assert refused(runs.start, run, amount, None, False).status == 422
        assert refused(runs.start, run, 5, "1", False).status == 422
        assert refused(runs.start, run, 5, None, "yes").status == 422

    def test_a_missing_key_is_said_before_anything_is_spent(
        self, workspace: Workspace, jobs: Jobs, fetched: Any, fake_client: FakeClient
    ) -> None:
        runs = BenchmarkRuns(workspace, jobs, lambda model: ["OPENAI_API_KEY"])
        run = make(runs)

        error = refused(runs.start, run, 5, None, False)

        assert (error.status, error.code) == (422, "missing_keys")
        assert error.details["missing"] == ["OPENAI_API_KEY"]
        assert fake_client.completions.calls == []

    def test_code_in_docker_needs_docker(self, workspace: Workspace, jobs: Jobs, fetched: Any) -> None:
        workspace.save_settings(Settings(model=TEST_MODEL, max_cost=None, code="docker"))
        runs = BenchmarkRuns(
            workspace,
            jobs,
            lambda model: [],
            docker_missing=lambda code: [{"id": "docker", "message": "Docker is off"}],
        )
        run = make(runs)

        error = refused(runs.start, run, 5, None, False)

        assert (error.status, error.code, error.message) == (409, "setup_needed", "Docker is off")

    def test_what_was_answered_can_still_be_seen_without_the_files(
        self, runs: BenchmarkRuns, workspace: Workspace, fetched: Any, fake_client: FakeClient
    ) -> None:
        run = make(runs, limit=1)
        answer(fake_client, the_questions(workspace)[0].answer)
        start(runs, run)
        for name in fetched:
            (workspace.benchmarks_dir / FILES_DIR / name).unlink()

        view = runs.view(run)

        assert view["problem"] and "files" in view["problem"]
        assert [row["state"] for row in view["results"]] == ["answered"]
        assert view["results"][0]["prompt"] is None
        assert view["metrics"]["accuracy"] == 1.0
        assert refused(runs.start, run, 5, None, False).code == "files_missing"

    def test_a_transcript_outside_the_run_is_not_read(self, runs: BenchmarkRuns, tmp_path: Path) -> None:
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps([{"agent": "x", "message": "secret"}]))
        directory = tmp_path / "run"
        directory.mkdir()

        assert runs.turns_of(directory, "../outside.json") == (None, False)
        assert runs.turns_of(directory, str(outside)) == (None, False)

    def test_a_long_transcript_is_cut_short_and_says_so(self, runs: BenchmarkRuns, tmp_path: Path) -> None:
        (tmp_path / "talk.json").write_text(
            json.dumps(
                [
                    {"agent": "a", "message": "x" * 150_000},
                    {"agent": "b", "message": "y" * 150_000},
                    {"agent": "c", "message": "z"},
                ]
            )
        )

        turns, truncated = runs.turns_of(tmp_path, "talk.json")

        assert truncated is True
        assert [turn["agent"] for turn in turns or []] == ["a", "b"]
        assert sum(len(turn["message"]) for turn in turns or []) == 200_000


class TestDeleting:
    def test_a_run_is_deleted_with_what_was_answered(self, runs: BenchmarkRuns, fetched: Any) -> None:
        run = make(runs)

        runs.delete(run)

        assert runs.describe()["runs"] == []
        assert not (runs.runs_dir / run).exists()
        assert refused(runs.delete, run).status == 404
        assert refused(runs.view, run).status == 404


class TestRoutes:
    def test_the_benchmarks_are_fetched_made_into_a_run_answered_and_deleted(
        self, client: TestClient, workspace: Workspace, stand_ins: dict[str, bytes], fake_client: FakeClient
    ) -> None:
        client.app.state.benchmarks.download = lambda directory: put_files(workspace, stand_ins)  # type: ignore[attr-defined]
        assert client.get("/api/benchmarks").json()["files"]["ready"] is False
        assert client.post("/api/benchmarks/runs", json={"title": "x", "benchmark": DBQA}).status_code == 409

        assert client.post("/api/benchmarks/files").json()["files"]["ready"] is True

        made = client.post("/api/benchmarks/runs", json={"title": "DbQA", "benchmark": DBQA, "limit": 1})
        assert made.status_code == 201
        run = made.json()["id"]
        answer(fake_client, the_questions(workspace)[0].answer)
        started = client.post(f"/api/benchmarks/runs/{run}/start", json={"max_cost": 5})
        assert started.status_code == 202
        job = started.json()
        while client.get(f"/api/setup/jobs/{job['id']}").json()["state"] in {"running", "stopping"}:
            time.sleep(0.01)

        assert client.get(f"/api/setup/jobs/{job['id']}").json()["state"] == "succeeded"
        assert client.get(f"/api/benchmarks/runs/{run}").json()["accuracy"] == 1.0
        assert client.get(f"/api/benchmarks/runs/{run}/questions/{DBQA}/0").json()["state"] == "answered"
        assert client.delete(f"/api/benchmarks/runs/{run}").json()["runs"] == []

    @pytest.mark.parametrize(
        "body",
        [
            {"title": "x"},
            {"title": "x", "benchmark": DBQA, "rounds": 1.5},
            {"title": "x", "benchmark": DBQA, "limit": "3"},
            {"title": "x", "benchmark": DBQA, "surprise": 1},
            {"title": "x", "benchmark": DBQA, "tasks": "all"},
        ],
    )
    def test_a_run_is_made_only_from_what_is_asked_for(
        self, client: TestClient, fetched: Any, body: dict[str, Any]
    ) -> None:
        assert client.post("/api/benchmarks/runs", json=body).status_code == 422

    @pytest.mark.parametrize(
        "body",
        [{}, {"max_cost": "5"}, {"max_cost": -1}, {"max_cost": 5, "retry_failed": "yes"}, {"max_cost": 5, "more": 1}],
    )
    def test_answering_is_asked_for_with_what_it_may_spend(
        self, client: TestClient, fetched: Any, body: dict[str, Any]
    ) -> None:
        run = client.post("/api/benchmarks/runs", json={"title": "x", "benchmark": DBQA}).json()["id"]

        assert client.post(f"/api/benchmarks/runs/{run}/start", json=body).status_code == 422

    def test_a_run_that_is_not_there_is_not_found(self, client: TestClient, fetched: Any) -> None:
        assert client.get("/api/benchmarks/runs/nothing").status_code == 404
        assert client.delete("/api/benchmarks/runs/nothing").status_code == 404
        assert client.post("/api/benchmarks/runs/nothing/start", json={"max_cost": 1}).status_code == 404
        assert client.get(f"/api/benchmarks/runs/nothing/questions/{DBQA}/0").status_code == 404
