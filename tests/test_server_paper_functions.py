"""The functions written from the papers of a run, and the conversations that are given them."""

import io
import json
import shutil
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MODEL, FakeClient
from fastapi.testclient import TestClient
from test_function_generator import StubExecutor, code, good, succeeded
from test_function_generator import queue as queue_functions
from test_papers import DESEQ
from test_papers import queue as queue_papers

from virtual_lab.function_checks import script_name
from virtual_lab.function_generator import UNVERIFIED, FunctionTask, GeneratedFunction, save_function
from virtual_lab.server import papers as papers_module
from virtual_lab.server.app import create_app
from virtual_lab.server.config import ChatConfig, resolve_config
from virtual_lab.server.conversations import Conversations
from virtual_lab.server.errors import ApiError
from virtual_lab.server.functions import given_runs, runs_with_functions
from virtual_lab.server.jobs import Job, Jobs
from virtual_lab.server.papers import FUNCTIONS_DIR, LAB_FILE, Papers
from virtual_lab.server.workspace import Settings, Workspace

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}

TEXT = b"Differential expression was found with DESeq2, from samples in GEO, aligned with STAR."
TASK = "RNA-seq differential expression with DESeq2"
NAME = script_name(TASK)


@pytest.fixture(autouse=True)
def model_client(fake_client: FakeClient) -> FakeClient:
    return fake_client


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
def papers(workspace: Workspace, jobs: Jobs) -> Papers:
    return Papers(workspace, jobs, 1024, lambda model: [])


@pytest.fixture
def conversations(workspace: Workspace) -> Iterator[Conversations]:
    kept = Conversations(workspace, check_keys=False)
    yield kept
    kept.close()


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


def read_run(papers: Papers, fake_client: FakeClient, title: str = "Gene papers") -> str:
    """A run whose two papers were read, and found one task in both."""
    run = papers.create(title, {"kind": "files"})
    for name in ("a.txt", "b.txt"):
        papers.add_file(run, name, io.BytesIO(TEXT))
    queue_papers(fake_client, *[DESEQ] * 20)
    finish(papers.read(run, 5, None, False))

    return run


def write(papers: Papers, run: str, **options: Any) -> Job:
    options = {
        "max_cost": 5,
        "max_cost_per_function": None,
        "min_papers": 1,
        "limit": 10,
        "retry_failed": False,
        "verify": False,
        **options,
    }

    return finish(papers.generate(run, **options))


def saved(workspace: Workspace, run: str, name: str, source: str | None = None, title: str = "A run") -> None:
    """A function that was written, put in a run, which is made if it is not there."""
    directory = workspace.papers_dir / run
    if not (directory / LAB_FILE).is_file():
        directory.mkdir(parents=True)
        lab = {"title": title, "source": {"kind": "files"}, "created_at": "2025-01-01T00:00:00+00:00"}
        (directory / LAB_FILE).write_text(json.dumps(lab))
    function = GeneratedFunction(
        task=FunctionTask(name=name, brief=name), name=name, status=UNVERIFIED, source=source or code(name)
    )
    save_function(directory / FUNCTIONS_DIR, function)


class TestWritingFunctions:
    def test_a_function_is_written_for_each_task_the_papers_share_as_a_job(
        self, papers: Papers, fake_client: FakeClient
    ) -> None:
        run = read_run(papers, fake_client)
        queue_functions(fake_client, good(NAME))

        job = papers.generate(run, 5, None, 1, 10, False, False)
        assert (job.kind, job.subject, job.title) == ("functions", run, "Writing functions: Gene papers")
        finish(job)

        assert job.state == "succeeded"
        assert job.message.startswith("Wrote 1 of 1 functions (1 not run), spending $")
        assert job.progress["functions"] == 1 and job.progress["finished"] == 1
        view = papers.view(run)
        assert [(row["name"], row["task"], row["papers"], row["status"]) for row in view["functions"]] == [
            (NAME, TASK, 2, "unverified")
        ]
        assert view["function_count"] == 1 and view["given"] is False
        assert (papers.workspace.papers_dir / run / FUNCTIONS_DIR / f"{NAME}.py").is_file()

    def test_writing_again_writes_nothing_that_is_already_written(
        self, papers: Papers, fake_client: FakeClient
    ) -> None:
        run = read_run(papers, fake_client)
        queue_functions(fake_client, good(NAME))
        write(papers, run)
        asked = len(fake_client.completions.calls)

        job = write(papers, run)

        assert len(fake_client.completions.calls) == asked
        assert job.message.startswith("Wrote 1 of 1 functions") and "spending $0.0000" in job.message

    def test_a_function_can_be_read_before_it_is_relied_on(self, papers: Papers, fake_client: FakeClient) -> None:
        run = read_run(papers, fake_client)
        queue_functions(fake_client, good(NAME))
        write(papers, run)

        shown = papers.function(run, NAME)

        assert shown["name"] == NAME and shown["status"] == "unverified" and shown["task"] == TASK
        assert shown["source"] == code(NAME) + "\n"
        assert TASK in shown["brief"] and shown["problems"] == []

    @pytest.mark.parametrize("name", ["missing", "../lab", "..", "a/b", "", "a b", "1x"])
    def test_a_function_that_is_not_there_is_not_found(
        self, papers: Papers, fake_client: FakeClient, name: str
    ) -> None:
        run = read_run(papers, fake_client)

        assert refused(papers.function, run, name).status == 404
        assert refused(papers.remove_function, run, name).status == 404

    def test_a_function_is_taken_away_with_its_record_and_written_again_when_asked_for(
        self, papers: Papers, fake_client: FakeClient
    ) -> None:
        run = read_run(papers, fake_client)
        queue_functions(fake_client, good(NAME), good(NAME))
        write(papers, run)

        papers.remove_function(run, NAME)

        assert papers.view(run)["functions"] == []
        assert not list((papers.workspace.papers_dir / run / FUNCTIONS_DIR).rglob(f"{NAME}.*"))
        assert write(papers, run).message.startswith("Wrote 1 of 1")

    def test_only_the_tasks_found_in_enough_papers_are_written_for(
        self, papers: Papers, fake_client: FakeClient
    ) -> None:
        run = read_run(papers, fake_client)

        error = refused(papers.generate, run, 5, None, 3, 10, False, False)

        assert (error.status, error.code) == (422, "invalid")
        assert "No task was found in 3 papers or more" in error.message

    def test_the_papers_must_be_read_first(self, papers: Papers) -> None:
        run = papers.create("Unread", {"kind": "files"})

        error = refused(papers.generate, run, 5, None, 1, 10, False, False)

        assert (error.status, error.code) == (422, "invalid") and "Read the papers" in error.message

    @pytest.mark.parametrize(
        "options",
        [
            {"max_cost": None},
            {"max_cost": -1},
            {"max_cost": "5"},
            {"max_cost": float("nan")},
            {"max_cost_per_function": -1},
            {"min_papers": 0},
            {"min_papers": True},
            {"min_papers": 1.5},
            {"limit": 0},
            {"limit": 101},
            {"limit": "3"},
            {"retry_failed": "yes"},
            {"verify": 1},
        ],
    )
    def test_what_it_may_spend_must_be_said_and_every_option_be_of_its_kind(
        self, papers: Papers, fake_client: FakeClient, options: dict[str, Any]
    ) -> None:
        run = read_run(papers, fake_client)
        asked = len(fake_client.completions.calls)

        error = refused(write, papers, run, **options)

        assert (error.status, error.code) == (422, "invalid")
        assert len(fake_client.completions.calls) == asked

    def test_a_model_whose_key_is_not_set_is_said_before_anything_is_spent(
        self, workspace: Workspace, jobs: Jobs, fake_client: FakeClient
    ) -> None:
        papers = Papers(workspace, jobs, 1024, lambda model: ["OPENAI_API_KEY"])
        run = papers.create("Gene papers", {"kind": "files"})
        (workspace.papers_dir / run / "frequency_summary.json").write_text('{"papers": 1, "tasks": {"x": 1}}')

        error = refused(papers.generate, run, 5, None, 1, 10, False, False)

        assert (error.status, error.code) == (422, "missing_keys") and error.details["missing"] == ["OPENAI_API_KEY"]

    def test_a_run_that_runs_out_of_money_stops_and_says_so(self, papers: Papers, fake_client: FakeClient) -> None:
        run = read_run(papers, fake_client)

        job = write(papers, run, max_cost=0)

        assert job.state == "succeeded" and "Stopped:" in job.message and "Wrote 0 of 1" in job.message

    def test_a_request_to_stop_ends_the_writing_before_the_next_function_and_keeps_what_was_written(
        self, workspace: Workspace, papers: Papers, fake_client: FakeClient
    ) -> None:
        run = papers.create("Gene papers", {"kind": "files"})
        summary = {"papers": 2, "tasks": {"Count reads": 2, "Align reads": 1}}
        (workspace.papers_dir / run / "frequency_summary.json").write_text(json.dumps(summary))
        queue_functions(fake_client, good("count_reads"), good("align_reads"))
        started, release = threading.Event(), threading.Event()
        real = fake_client.completions.create

        def slow(**kwargs: Any) -> Any:
            started.set()
            assert release.wait(10)

            return real(**kwargs)

        fake_client.completions.create = slow

        job = papers.generate(run, 5, None, 1, 10, False, False)
        assert started.wait(10)
        job.request_stop()
        release.set()
        finish(job)

        assert job.state == "stopped"
        assert job.message == "Stopped. What was written is kept, and writing again carries on from there."
        assert [row["name"] for row in papers.view(run)["functions"]] == ["count_reads"]
        fake_client.completions.create = real
        assert write(papers, run).message.startswith("Wrote 2 of 2")
        assert len(fake_client.completions.calls) == 2

    def test_a_run_is_not_read_and_written_at_once_and_is_not_changed_meanwhile(
        self, papers: Papers, jobs: Jobs, fake_client: FakeClient
    ) -> None:
        run = read_run(papers, fake_client)
        queue_functions(fake_client, good(NAME))
        write(papers, run)
        release = threading.Event()
        jobs.start(
            "functions", run, "Writing functions", lambda job: release.wait(10) and None, exclusive=f"papers:{run}"
        )
        try:
            for call in (
                lambda: papers.read(run, 5, None, False),
                lambda: papers.generate(run, 5, None, 1, 10, False, False),
                lambda: papers.remove_function(run, NAME),
                lambda: papers.delete(run),
                lambda: papers.add_file(run, "c.txt", io.BytesIO(TEXT)),
            ):
                error = refused(call)
                assert (error.status, error.code) == (409, "busy")
            assert papers.describe()["runs"][0]["job_kind"] == "functions"
        finally:
            release.set()

    def test_the_functions_are_checked_in_a_container_when_asked(
        self, papers: Papers, fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = read_run(papers, fake_client)
        queue_functions(fake_client, good(NAME))
        executor = StubExecutor(succeeded())
        monkeypatch.setattr(papers_module.CodeSetup, "docker_executor", lambda self: executor)

        job = write(papers, run, verify=True)

        assert executor.checked == 1 and len(executor.runs) == 1
        assert job.message.startswith("Wrote 1 of 1 functions, spending $")
        assert papers.view(run)["functions"][0]["status"] == "verified"

    def test_a_check_in_a_container_is_refused_while_docker_is_not_there(
        self, workspace: Workspace, jobs: Jobs, fake_client: FakeClient
    ) -> None:
        papers = Papers(
            workspace,
            jobs,
            1024,
            lambda model: [],
            docker_missing=lambda code: [{"id": "docker", "message": "Docker is not running"}],
        )
        run = read_run(papers, fake_client)
        asked = len(fake_client.completions.calls)

        error = refused(papers.generate, run, 5, None, 1, 10, False, True)

        assert (error.status, error.code) == (409, "setup_needed")
        assert error.message == "Docker is not running" and error.details["missing"] == ["docker"]
        assert len(fake_client.completions.calls) == asked


class TestGivingFunctions:
    def test_a_run_gives_its_functions_only_when_the_person_says(self, workspace: Workspace, papers: Papers) -> None:
        saved(workspace, "run-a", "count_reads")

        assert runs_with_functions(workspace) == {"run-a": False} and given_runs(workspace) == []

        papers.give("run-a", True)
        assert given_runs(workspace) == ["run-a"] and papers.view("run-a")["given"] is True
        papers.give("run-a", False)
        assert given_runs(workspace) == []

    def test_a_run_with_no_function_that_passed_is_not_one_to_give(self, workspace: Workspace, papers: Papers) -> None:
        run = papers.create("Empty", {"kind": "files"})
        papers.give(run, True)

        assert runs_with_functions(workspace) == {} and given_runs(workspace) == []

    @pytest.mark.parametrize("given", ["yes", 1, None])
    def test_giving_is_yes_or_no(self, workspace: Workspace, papers: Papers, given: Any) -> None:
        saved(workspace, "run-a", "count_reads")

        assert refused(papers.give, "run-a", given).status == 422
        assert refused(papers.give, "nowhere", True).status == 404

    def test_a_run_whose_file_says_it_is_given_in_nonsense_is_left_out(
        self, workspace: Workspace, papers: Papers
    ) -> None:
        saved(workspace, "run-a", "count_reads")
        lab = json.loads((workspace.papers_dir / "run-a" / LAB_FILE).read_text())
        (workspace.papers_dir / "run-a" / LAB_FILE).write_text(json.dumps({**lab, "given": "yes"}))

        assert runs_with_functions(workspace) == {}

    def test_what_is_given_is_what_a_new_conversation_is_set_up_with_unless_it_names_runs(
        self, workspace: Workspace, papers: Papers
    ) -> None:
        saved(workspace, "run-a", "count_reads")
        saved(workspace, "run-b", "align_reads")
        papers.give("run-b", True)
        settings = workspace.load_settings()

        assert resolve_config({}, settings, workspace).functions == ("run-b",)
        assert resolve_config({"functions": ["run-a", "run-a"]}, settings, workspace).functions == ("run-a",)
        assert resolve_config({"functions": []}, settings, workspace).functions == ()
        for wrong in (["nowhere"], "run-a", [1]):
            with pytest.raises(ValueError, match="no run of papers|list of their ids"):
                resolve_config({"functions": wrong}, settings, workspace)

    def test_what_a_conversation_is_given_is_kept_with_it_and_an_older_one_has_none(self, workspace: Workspace) -> None:
        saved(workspace, "run-a", "count_reads")
        config = resolve_config({"functions": ["run-a"]}, workspace.load_settings(), workspace)

        again = ChatConfig.from_dict(json.loads(json.dumps(config.to_dict())))
        older = config.to_dict()
        del older["functions"]

        assert again == config and config.to_dict()["functions"] == ["run-a"]
        assert ChatConfig.from_dict(older).functions == ()


class TestFunctionsInConversations:
    def local(self, **more: Any) -> dict[str, Any]:
        return {"team": [], "code": {"where": "local", "resources": "none"}, **more}

    def names(self, conversations: Conversations, request: dict[str, Any]) -> list[str]:
        return [tool.name for tool in conversations.create(request).chat.tools]

    def test_the_functions_of_a_run_are_tools_where_code_runs(
        self, workspace: Workspace, conversations: Conversations
    ) -> None:
        saved(workspace, "run-a", "count_reads")
        saved(workspace, "run-a", "align_reads")

        names = self.names(conversations, self.local(functions=["run-a"]))

        assert {"count_reads", "align_reads"} <= set(names)

    def test_where_no_code_runs_there_is_nowhere_to_run_them_and_they_are_kept_for_later(
        self, workspace: Workspace, conversations: Conversations
    ) -> None:
        saved(workspace, "run-a", "count_reads")

        handle = conversations.create({"team": [], "functions": ["run-a"]})

        assert handle.session is None and "count_reads" not in [tool.name for tool in handle.chat.tools]
        assert handle.config.functions == ("run-a",)

    def test_a_function_is_run_in_the_conversations_own_session(
        self, workspace: Workspace, conversations: Conversations
    ) -> None:
        saved(workspace, "run-a", "count_reads")

        handle = conversations.create(self.local(functions=["run-a"]))
        tool = next(tool for tool in handle.chat.tools if tool.name == "count_reads")

        assert tool.function(path="x") == 1

    def test_a_name_a_tool_has_already_is_left_to_that_tool_and_the_first_run_keeps_a_name(
        self, workspace: Workspace, conversations: Conversations
    ) -> None:
        saved(workspace, "run-a", "pubmed_search")
        saved(workspace, "run-a", "count_reads")
        saved(workspace, "run-b", "count_reads", source=code("count_reads").replace("return 1", "return 2"))

        handle = conversations.create(self.local(functions=["run-a", "run-b"]))
        names = [tool.name for tool in handle.chat.tools]
        count = next(tool for tool in handle.chat.tools if tool.name == "count_reads")

        assert names.count("pubmed_search") == 1 and names.count("count_reads") == 1
        assert count.function(path="x") == 1
        pubmed = next(tool for tool in handle.chat.tools if tool.name == "pubmed_search")
        assert "Counts the reads" not in pubmed.description

    def test_a_function_that_has_gone_or_was_changed_into_nonsense_does_not_stop_the_conversation(
        self, workspace: Workspace, conversations: Conversations
    ) -> None:
        saved(workspace, "run-a", "count_reads")
        saved(workspace, "run-a", "align_reads")
        (workspace.papers_dir / "run-a" / FUNCTIONS_DIR / "align_reads.py").write_text("this is not python (")

        names = self.names(conversations, self.local(functions=["run-a"]))

        assert "count_reads" in names and "align_reads" not in names

    def test_a_run_that_was_deleted_since_is_left_out_when_the_conversation_is_opened_again(
        self, workspace: Workspace, conversations: Conversations
    ) -> None:
        saved(workspace, "run-a", "count_reads")
        handle = conversations.create(self.local(functions=["run-a"]))
        chat_id = handle.id
        conversations.close()

        shutil.rmtree(workspace.papers_dir / "run-a")

        reopened = conversations.get(chat_id)

        assert reopened.config.functions == ("run-a",)
        assert "count_reads" not in [tool.name for tool in reopened.chat.tools]


class TestTheApi:
    def make(self, client: TestClient) -> str:
        response = client.post("/api/papers/runs", json={"title": "Gene papers", "source": {"kind": "files"}})
        assert response.status_code == 201

        return response.json()["id"]

    def test_functions_are_written_as_a_job_and_listed_with_the_run(
        self, client: TestClient, workspace: Workspace, fake_client: FakeClient
    ) -> None:
        run = self.make(client)
        for name in ("a.txt", "b.txt"):
            assert client.post(f"/api/papers/runs/{run}/files?name={name}", content=TEXT).status_code == 201
        queue_papers(fake_client, *[DESEQ] * 20)
        queue_functions(fake_client, good(NAME))
        job = client.post(f"/api/papers/runs/{run}/read", json={"max_cost": 5}).json()
        self.wait(client, job["id"])

        response = client.post(f"/api/papers/runs/{run}/functions", json={"max_cost": 5, "limit": 3})
        assert response.status_code == 202 and response.json()["kind"] == "functions"
        self.wait(client, response.json()["id"])

        shown = client.get(f"/api/papers/runs/{run}").json()
        assert [row["name"] for row in shown["functions"]] == [NAME]
        detail = client.get(f"/api/papers/runs/{run}/functions/{NAME}").json()
        assert detail["source"] == code(NAME) + "\n"
        assert client.patch(f"/api/papers/runs/{run}", json={"given": True}).json()["given"] is True
        chat = client.post("/api/chats", json={"team": [], "code": {"where": "local", "resources": "none"}})
        assert chat.status_code == 201 and chat.json()["config"]["functions"] == [run]
        removed = client.delete(f"/api/papers/runs/{run}/functions/{NAME}")
        assert removed.status_code == 200 and removed.json()["functions"] == []

    def wait(self, client: TestClient, job_id: str) -> None:
        deadline = time.monotonic() + 20
        while True:
            state = client.get(f"/api/setup/jobs/{job_id}").json()["state"]
            if state != "running":
                assert state == "succeeded"
                return
            assert time.monotonic() < deadline
            time.sleep(0.02)

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"max_cost": -1},
            {"max_cost": "5"},
            {"max_cost": 5, "min_papers": 0},
            {"max_cost": 5, "min_papers": "2"},
            {"max_cost": 5, "limit": 101},
            {"max_cost": 5, "limit": 1.5},
            {"max_cost": 5, "verify": "yes"},
            {"max_cost": 5, "other": 1},
        ],
    )
    def test_how_much_it_may_spend_is_always_said_and_nothing_else_is_taken(
        self, client: TestClient, body: dict[str, Any]
    ) -> None:
        run = self.make(client)

        assert client.post(f"/api/papers/runs/{run}/functions", json=body).status_code == 422

    @pytest.mark.parametrize("body", [{}, {"given": "yes"}, {"given": 1}, {"given": True, "title": "x"}])
    def test_giving_is_yes_or_no_and_nothing_else_is_changed(self, client: TestClient, body: dict[str, Any]) -> None:
        run = self.make(client)

        assert client.patch(f"/api/papers/runs/{run}", json=body).status_code == 422

    def test_a_run_that_is_not_there_is_not_found_whatever_is_done_to_it(self, client: TestClient) -> None:
        for call in (
            lambda: client.post("/api/papers/runs/nowhere/functions", json={"max_cost": 5}),
            lambda: client.get("/api/papers/runs/nowhere/functions/x"),
            lambda: client.delete("/api/papers/runs/nowhere/functions/x"),
            lambda: client.patch("/api/papers/runs/nowhere", json={"given": True}),
        ):
            assert call().status_code == 404

    def test_a_conversation_is_refused_runs_that_have_no_functions(self, client: TestClient) -> None:
        run = self.make(client)

        response = client.post("/api/chats", json={"team": [], "functions": [run]})

        assert response.status_code == 422 and response.json()["error"]["code"] == "invalid"
