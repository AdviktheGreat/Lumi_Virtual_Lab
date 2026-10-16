"""Tests of the research projects the server carries out: making one, working on it as a job, stopping it and carrying
it on, and what is found."""

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MODEL, FakeClient
from fastapi.testclient import TestClient
from test_planning import GOAL, decide, found, plan, queue, review, roster, sent

from virtual_lab.server.app import create_app
from virtual_lab.server.errors import ApiError
from virtual_lab.server.jobs import Job, Jobs
from virtual_lab.server.projects import LAB_FILE, Projects
from virtual_lab.server.workspace import Settings, Workspace

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}


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
def projects(workspace: Workspace, jobs: Jobs) -> Projects:
    return Projects(workspace, jobs, lambda model: [])


@pytest.fixture
def client(workspace: Workspace) -> Iterator[TestClient]:
    app = create_app(workspace.root, token=TOKEN, check_keys=False)
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


def refused(call: Any, *args: Any, **kwargs: Any) -> ApiError:
    with pytest.raises(ApiError) as caught:
        call(*args, **kwargs)

    return caught.value


def finish(job: Job, seconds: float = 30) -> Job:
    deadline = time.monotonic() + seconds
    while job.active:
        assert time.monotonic() < deadline, "the job did not finish"
        time.sleep(0.01)

    return job


def make(projects: Projects, goal: str = GOAL, **kwargs: Any) -> str:
    return projects.create(goal, **kwargs)


def start(projects: Projects, project: str, **options: Any) -> Job:
    options = {"max_cost": 5, **options}

    return finish(projects.start(project, **options))


def block_call(fake_client: FakeClient, method: str, which: int | str) -> tuple[threading.Event, Callable[[], None]]:
    """Makes a call to the model, of create or parse, wait before it is answered: the one of this number, or the first
    that mentions this text. Gives an event that is set once it is waiting, and what lets it go and waits until it has
    been answered."""
    waiting, release, ended = threading.Event(), threading.Event(), threading.Event()
    real = getattr(fake_client.completions, method)
    calls: list[Any] = []

    def slow(**kwargs: Any) -> Any:
        calls.append(kwargs)
        chosen = len(calls) == which if isinstance(which, int) else which in sent(kwargs) and not waiting.is_set()
        if chosen:
            waiting.set()
            assert release.wait(10)
            try:
                return real(**kwargs)
            finally:
                ended.set()

        return real(**kwargs)

    setattr(fake_client.completions, method, slow)

    def let_go() -> None:
        release.set()
        assert ended.wait(10)
        setattr(fake_client.completions, method, real)

    return waiting, let_go


def finishing(*, tasks: int = 1) -> list[Any]:
    """What the lab is asked, in order, for a project in which the lead chooses a team of one, plans, and finishes in
    its first round."""
    return [
        roster("Immunologist"),
        plan(*[f"Task {number}" for number in range(1, tasks + 1)]),
        decide("finish", done=tasks, answer="Nanobody A binds better."),
        review(True),
    ]


class TestMaking:
    def test_a_project_keeps_its_goal_and_how_it_is_run(self, projects: Projects) -> None:
        project = make(projects, title="Nanobodies", max_team_size=2, meeting_rounds=2, memory="bm25")

        view = projects.view(project)

        assert (view["id"], view["title"], view["goal"], view["state"]) == (project, "Nanobodies", GOAL, "new")
        assert (view["team_mode"], view["max_team_size"], view["meeting_rounds"]) == ("chosen", 2, 2)
        assert (view["memory"], view["findings_per_step"], view["model"]) == ("bm25", 8, TEST_MODEL)
        assert (view["spent"], view["max_cost"], view["rounds_taken"], view["job"]) == (0.0, None, 0, None)
        assert view["lead"]["title"] == "Principal Investigator"
        assert view["critic"]["title"] == "Scientific Critic"
        assert (view["team"], view["plan"], view["steps"], view["answer"], view["report"]) == ([], [], [], None, False)
        assert json.loads((projects.workspace.projects_dir / project / LAB_FILE).read_text())["goal"] == GOAL

    def test_a_project_without_a_title_is_called_by_the_start_of_its_goal(self, projects: Projects) -> None:
        long = "Find out " + "which of the nanobodies binds better " * 6

        assert projects.view(make(projects))["title"] == GOAL
        assert projects.view(make(projects, long))["title"].endswith("…")
        assert len(projects.view(make(projects, long + "again"))["title"]) <= 80

    def test_a_project_can_have_the_whole_lab_as_its_team(self, projects: Projects) -> None:
        described = projects.describe()
        project = make(projects, team="lab")

        view = projects.view(project)

        assert described["team"] and "Scientific Critic" not in described["team"]
        assert described["lead"] == "Principal Investigator"
        assert view["team_mode"] == "lab"
        assert [member["title"] for member in view["team"]] == described["team"]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"goal": ""},
            {"goal": "   "},
            {"goal": "a" * 20_001},
            {"goal": "bell\x07"},
            {"title": "x" * 201},
            {"title": "tab\x07"},
            {"team": "everyone"},
            {"memory": "everything"},
            {"max_team_size": 7},
            {"max_team_size": True},
            {"meeting_rounds": -1},
            {"findings_per_step": 0},
            {"findings_per_step": "8"},
        ],
    )
    def test_what_does_not_fit_is_refused(self, projects: Projects, kwargs: dict[str, Any]) -> None:
        error = refused(make, projects, **{"goal": GOAL, **kwargs})

        assert (error.status, error.code) == (422, "invalid")
        assert projects.describe()["projects"] == []

    def test_a_goal_may_run_over_lines(self, projects: Projects) -> None:
        goal = "Find out which binds better.\n\nTry the affinities first.\tThen the structures."

        assert projects.view(make(projects, goal))["goal"] == goal

    def test_projects_are_listed_latest_first_with_what_a_page_needs(self, projects: Projects) -> None:
        first, second = make(projects, title="First"), make(projects, title="Second")

        described = projects.describe()

        assert [project["id"] for project in described["projects"]] == [second, first]
        assert [team["id"] for team in described["teams"]] == ["chosen", "lab"]
        assert [memory["id"] for memory in described["memories"]] == ["pick", "bm25", "summaries"]
        assert described["limits"]["max_rounds"] == {
            "label": "The most rounds",
            "default": 10,
            "least": 1,
            "most": 100,
        }
        assert (described["default_team"], described["default_memory"], described["model"]) == (
            "chosen",
            "pick",
            TEST_MODEL,
        )

    def test_a_project_is_deleted_with_what_it_found(self, projects: Projects) -> None:
        project = make(projects)

        projects.delete(project)

        assert projects.describe()["projects"] == []
        assert refused(projects.view, project).status == 404
        assert not (projects.workspace.projects_dir / project).exists()


class TestWorking:
    def test_a_project_is_staffed_planned_worked_on_and_finished(
        self, projects: Projects, fake_client: FakeClient
    ) -> None:
        project = make(projects)
        queue(
            fake_client,
            roster("Immunologist"),
            plan("Task 1", "Task 2"),
            decide("team_meeting", participants=["Immunologist"], agenda="Compare the binding data."),
            found("A binds KP.3 at 2 nM"),
            decide("finish", done=2, answer="Nanobody A binds better."),
            review(True),
        )

        job = start(projects, project)

        assert job.state == "succeeded"
        assert job.message.startswith("Finished after 2 rounds, with 2 of 2 tasks done, spending $")
        view = projects.view(project)
        assert (view["state"], view["answer"], view["rounds_taken"], view["job"]) == (
            "finished",
            "Nanobody A binds better.",
            2,
            None,
        )
        assert [member["title"] for member in view["team"]] == ["Immunologist"]
        assert [(task["task"], task["status"]) for task in view["plan"]] == [("Task 1", "done"), ("Task 2", "done")]
        assert [(row["number"], row["action"], row["outcome"]) for row in view["rounds"]] == [
            (1, "team_meeting", "done"),
            (2, "finish", "finished"),
        ]
        assert view["rounds"][0]["participants"] == ["Immunologist"]
        assert view["rounds"][0]["agenda"] == "Compare the binding data."
        assert view["rounds"][0]["steps"] == ["round_01_meeting"]
        assert view["rounds"][1]["answer"] == "Nanobody A binds better."
        assert [(row["claim"], row["source"]) for row in view["findings"]] == [
            ("A binds KP.3 at 2 nM", "round_01_meeting")
        ]
        assert [row["name"] for row in view["steps"]] == [
            "team",
            "plan",
            "round_01_decision",
            "round_01_meeting",
            "round_02_decision",
            "round_02_review",
        ]
        assert [row["round"] for row in view["steps"]] == [None, None, 1, 1, 2, 2]
        assert all(row["status"] == "completed" and row["cost"] > 0 for row in view["steps"])
        assert view["spent"] == pytest.approx(sum(row["cost"] for row in view["steps"]))
        assert (view["max_cost"], view["report"], view["error"]) == (5.0, True, None)
        assert "Nanobody A binds better." in projects.report_file(project).read_text()

    def test_the_job_tells_what_the_project_is_doing(self, projects: Projects, fake_client: FakeClient) -> None:
        project = make(projects)
        queue(fake_client, *finishing())

        job = start(projects, project)

        lines = job.snapshot(0)["log"]["lines"]
        assert lines[0] == "The team: Immunologist"
        assert lines[1] == "The plan has 1 task"
        assert "Round 1: finish" in lines
        assert lines[-1].startswith("The project ended: ")
        assert job.progress["round"] == 1 and job.progress["max_rounds"] == 10
        assert job.progress["spent"] > 0 and job.progress["max_cost"] == 5

    def test_a_step_shows_what_it_produced_and_what_was_said(self, projects: Projects, fake_client: FakeClient) -> None:
        project = make(projects)
        queue(
            fake_client,
            roster("Immunologist"),
            plan("Task 1"),
            decide("team_meeting", participants=["Immunologist"], agenda="Compare the binding data."),
            found("A binds KP.3 at 2 nM"),
            decide("finish", done=1, answer="A."),
            review(True),
        )
        start(projects, project)

        decision = projects.step(project, "round_01_decision")
        meeting = projects.step(project, "round_01_meeting")

        assert (decision["kind"], decision["status"], decision["round"]) == ("meeting", "completed", 1)
        assert decision["output"]["action"] == "team_meeting"
        assert decision["usage"]["cost"] == decision["cost"]
        assert meeting["turns"] and all({"agent", "message"} <= set(turn) for turn in meeting["turns"])
        assert meeting["truncated"] is False
        assert (meeting["code"], meeting["attempts"], meeting["succeeded"]) == (None, None, None)

    def test_a_step_that_was_not_taken_is_not_found(self, projects: Projects) -> None:
        project = make(projects)

        for name in ("round_01_meeting", "../lab", ""):
            assert refused(projects.step, project, name).status == 404

    def test_a_project_that_has_not_ended_has_no_report(self, projects: Projects) -> None:
        project = make(projects)

        assert refused(projects.report_file, project).status == 404

    def test_the_most_it_may_spend_ends_the_project_and_raising_it_carries_on(
        self, projects: Projects, fake_client: FakeClient
    ) -> None:
        project = make(projects)

        job = start(projects, project, max_cost=0)

        assert job.state == "succeeded"
        assert job.message.startswith("Out of budget after 0 rounds")
        assert projects.view(project)["state"] == "out_of_budget"
        assert fake_client.completions.calls == []

        queue(fake_client, *finishing())
        job = start(projects, project, max_cost=5)

        assert job.message.startswith("Finished after 1 round, ")
        assert projects.view(project)["state"] == "finished"

    def test_a_project_that_ran_out_of_rounds_is_carried_on_by_raising_them(
        self, projects: Projects, fake_client: FakeClient
    ) -> None:
        project = make(projects)
        queue(
            fake_client,
            roster("Immunologist"),
            plan("Task 1"),
            decide("individual_meeting", participants=["Immunologist"], agenda="Look at the data."),
            found("Something"),
        )

        job = start(projects, project, max_rounds=1)

        assert job.message.startswith("Out of rounds after 1 round, ")
        assert projects.view(project)["state"] == "out_of_rounds"

        queue(fake_client, decide("finish", done=1, answer="A."), review(True))
        job = start(projects, project, max_rounds=3)

        assert job.message.startswith("Finished after 2 rounds, ")

    def test_a_request_to_stop_between_steps_ends_the_project_with_its_report(
        self, projects: Projects, fake_client: FakeClient
    ) -> None:
        project = make(projects)
        queue(fake_client, *finishing())
        waiting, let_go = block_call(fake_client, "parse", 3)

        job = projects.start(project, 5)
        assert waiting.wait(10)
        # A request that has been sent is waited for, so the stop is made known before it is answered
        job.request_stop()
        let_go()
        finish(job)

        assert job.state == "stopped"
        assert job.message == "Stopped. What was done is kept, and starting again carries on from there."
        view = projects.view(project)
        assert (view["state"], view["error"], view["report"]) == ("stopped", None, True)
        assert view["reason"] == "Stopped at the person's request."
        assert [row["name"] for row in view["steps"] if row["status"] == "completed"] == [
            "team",
            "plan",
            "round_01_decision",
        ]
        assert projects.describe()["projects"][0]["state"] == "stopped"

        job = start(projects, project)

        assert job.message.startswith("Finished after 1 round, ")
        view = projects.view(project)
        assert (view["state"], view["answer"]) == ("finished", "Nanobody A binds better.")
        assert [row["name"] for row in view["steps"]].count("team") == 1

    def test_a_request_to_stop_in_the_middle_of_a_step_keeps_the_steps_before_it(
        self, projects: Projects, fake_client: FakeClient
    ) -> None:
        project = make(projects)
        queue(
            fake_client,
            roster("Immunologist"),
            plan("Task 1"),
            decide("team_meeting", participants=["Immunologist"], agenda="Compare the binding data."),
            found("A binds KP.3 at 2 nM"),
            decide("finish", done=1, answer="Nanobody A binds better."),
            review(True),
        )
        waiting, let_go = block_call(fake_client, "create", "Compare the binding data.")

        job = projects.start(project, 5)
        assert waiting.wait(10)
        job.request_stop()
        let_go()
        finish(job)

        assert job.state == "stopped"
        view = projects.view(project)
        assert (view["state"], view["error"], view["report"]) == ("stopped", None, False)
        assert {row["name"]: row["status"] for row in view["steps"]}["round_01_meeting"] == "failed"
        assert view["rounds"][0]["outcome"] == "interrupted"

        job = start(projects, project)

        assert job.message.startswith("Finished after 2 rounds, ")
        view = projects.view(project)
        assert (view["state"], view["answer"]) == ("finished", "Nanobody A binds better.")
        assert {row["name"]: row["status"] for row in view["steps"]}["round_01_meeting"] == "completed"

    def test_a_project_that_was_working_when_the_server_stopped_is_shown_as_interrupted(
        self, projects: Projects, fake_client: FakeClient
    ) -> None:
        project = make(projects)
        queue(fake_client, *finishing())
        start(projects, project)
        log = projects.workspace.projects_dir / project / "research_log.json"
        saved = json.loads(log.read_text())
        saved["status"] = "running"
        saved["rounds"][0]["outcome"] = "running"
        log.write_text(json.dumps(saved))

        view = projects.view(project)

        assert (view["state"], view["rounds"][0]["outcome"]) == ("interrupted", "interrupted")

    def test_a_failure_is_said(self, projects: Projects, fake_client: FakeClient) -> None:
        project = make(projects)
        queue(fake_client, RuntimeError("the model is down"))

        job = start(projects, project)

        assert job.state == "failed"
        assert "the model is down" in (job.error or "")
        view = projects.view(project)
        assert view["state"] == "failed"
        assert "the model is down" in view["error"]

    def test_the_whole_lab_works_without_the_lead_choosing_a_team(
        self, projects: Projects, fake_client: FakeClient
    ) -> None:
        project = make(projects, team="lab")
        queue(fake_client, plan("Task 1"), decide("finish", done=1, answer="A."), review(True))

        job = start(projects, project)

        assert job.state == "succeeded"
        view = projects.view(project)
        assert view["state"] == "finished"
        assert [member["title"] for member in view["team"]] == projects.describe()["team"]

    def test_a_project_is_worked_on_with_what_it_was_made_with(
        self, projects: Projects, workspace: Workspace, fake_client: FakeClient
    ) -> None:
        project = make(projects)
        workspace.save_settings(Settings(model="gpt-4.1-mini", max_cost=None))
        queue(fake_client, *finishing())

        start(projects, project)

        assert {call["model"] for call in fake_client.completions.calls} == {TEST_MODEL}

    def test_one_project_is_worked_on_at_a_time(self, projects: Projects, jobs: Jobs) -> None:
        first, second = make(projects, title="First"), make(projects, title="Second")
        release = threading.Event()
        jobs.start("project", first, "Working on First", lambda job: release.wait(10) and None, exclusive="project")
        try:
            error = refused(projects.start, second, 5)
            assert (error.status, error.code) == (409, "busy")
            assert error.details["job"]["subject"] == first
            assert refused(projects.delete, first).code == "busy"
            assert projects.view(first)["state"] == "running"
        finally:
            release.set()

    @pytest.mark.parametrize("amount", [-1, "5", None, True, float("nan")])
    def test_the_most_it_may_spend_is_an_amount(self, projects: Projects, amount: Any) -> None:
        project = make(projects)

        assert refused(projects.start, project, amount).status == 422

    @pytest.mark.parametrize(
        "limits",
        [
            {"max_rounds": 0},
            {"max_rounds": 101},
            {"max_rounds": "3"},
            {"max_stalled_rounds": 0},
            {"max_stalled_rounds": True},
        ],
    )
    def test_the_limits_on_rounds_are_whole_numbers_in_range(self, projects: Projects, limits: dict[str, Any]) -> None:
        project = make(projects)

        assert refused(projects.start, project, 5, **limits).status == 422

    def test_a_missing_key_is_said_before_anything_is_spent(
        self, workspace: Workspace, jobs: Jobs, fake_client: FakeClient
    ) -> None:
        projects = Projects(workspace, jobs, lambda model: ["OPENAI_API_KEY"])
        project = make(projects)

        error = refused(projects.start, project, 5)

        assert (error.status, error.code) == (422, "missing_keys")
        assert error.details["missing"] == ["OPENAI_API_KEY"]
        assert fake_client.completions.calls == []

    def test_code_in_docker_needs_docker(self, workspace: Workspace, jobs: Jobs) -> None:
        workspace.save_settings(Settings(model=TEST_MODEL, max_cost=None, code="docker"))
        projects = Projects(
            workspace,
            jobs,
            lambda model: [],
            docker_missing=lambda code: [{"id": "docker", "message": "Docker is off"}],
        )
        project = make(projects)

        error = refused(projects.start, project, 5)

        assert (error.status, error.code, error.message) == (409, "setup_needed", "Docker is off")


class TestWhatWasSaved:
    def test_a_project_whose_files_are_damaged_is_still_shown(
        self, projects: Projects, fake_client: FakeClient
    ) -> None:
        project = make(projects)
        queue(fake_client, *finishing())
        start(projects, project)
        directory = projects.workspace.projects_dir / project
        for name in ("research_log.json", "project.json", "report.json", "memory.json"):
            (directory / name).write_text("[1, 2")

        view = projects.view(project)

        assert (view["state"], view["rounds"], view["steps"], view["findings"], view["answer"]) == (
            "new",
            [],
            [],
            [],
            None,
        )

    def test_a_status_that_is_not_text_is_taken_for_an_interrupted_project(self, projects: Projects) -> None:
        project = make(projects)
        (projects.workspace.projects_dir / project / "research_log.json").write_text(json.dumps({"status": ["failed"]}))

        assert projects.view(project)["state"] == "interrupted"
        assert projects.describe()["projects"][0]["state"] == "interrupted"

    def test_a_file_the_ledger_names_outside_the_project_is_not_read(self, projects: Projects, tmp_path: Path) -> None:
        project = make(projects)
        directory = projects.workspace.projects_dir / project
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps({"secret": True}))
        step = {
            "name": "team",
            "kind": "meeting",
            "status": "completed",
            "usage": {"cost": 0.1},
            "files": {"transcript": "../../../outside.json", "output": str(outside), "record": "../../../outside.json"},
        }
        (directory / "project.json").write_text(json.dumps({"steps": [step], "spent": 0.1, "max_cost": 1}))

        shown = projects.step(project, "team")

        assert (shown["turns"], shown["output"], shown["code"]) == (None, None, None)

    def test_the_code_a_step_ran_is_shown_with_what_it_printed(self, projects: Projects) -> None:
        project = make(projects)
        directory = projects.workspace.projects_dir / project
        (directory / "meetings" / "executions").mkdir(parents=True)
        record = {
            "succeeded": True,
            "num_attempts": 2,
            "final_files": [
                {"filename": "analysis.py", "language": "python", "description": "", "contents": "print(1)"}
            ],
            "attempts": [
                {"attempt": 1, "runs": [{"filename": "analysis.py", "stdout": "", "stderr": "Traceback"}]},
                {"attempt": 2, "runs": [{"filename": "analysis.py", "stdout": "1\n", "stderr": ""}]},
            ],
        }
        (directory / "meetings" / "executions" / "round_01_code.json").write_text(json.dumps(record))
        step = {
            "name": "round_01_code",
            "kind": "repair",
            "status": "completed",
            "usage": {"cost": 0.2},
            "files": {"record": "meetings/executions/round_01_code.json"},
        }
        (directory / "project.json").write_text(json.dumps({"steps": [step], "spent": 0.2, "max_cost": 1}))

        shown = projects.step(project, "round_01_code")

        assert (shown["kind"], shown["round"], shown["attempts"], shown["succeeded"]) == ("repair", 1, 2, True)
        assert shown["code"] == [
            {"filename": "analysis.py", "language": "python", "contents": "print(1)", "output": "1\n"}
        ]


class TestRoutes:
    def test_a_project_is_made_worked_on_and_deleted(self, client: TestClient, fake_client: FakeClient) -> None:
        assert client.get("/api/projects").json()["projects"] == []
        assert client.get("/api/projects/nothing/report").status_code == 404

        made = client.post("/api/projects", json={"goal": GOAL, "title": "Nanobodies", "max_team_size": 2})
        assert made.status_code == 201
        project = made.json()["id"]
        queue(fake_client, *finishing())
        started = client.post(f"/api/projects/{project}/start", json={"max_cost": 5, "max_rounds": 4})
        assert started.status_code == 202
        job = started.json()
        while client.get(f"/api/setup/jobs/{job['id']}").json()["state"] in {"running", "stopping"}:
            time.sleep(0.01)

        assert client.get(f"/api/setup/jobs/{job['id']}").json()["state"] == "succeeded"
        view = client.get(f"/api/projects/{project}").json()
        assert (view["state"], view["answer"], view["max_team_size"]) == ("finished", "Nanobody A binds better.", 2)
        assert client.get(f"/api/projects/{project}/steps/round_01_decision").json()["output"]["action"] == "finish"
        report = client.get(f"/api/projects/{project}/report")
        assert report.status_code == 200
        assert "attachment" in report.headers["content-disposition"]
        assert "Nanobody A binds better." in report.text
        assert client.delete(f"/api/projects/{project}").json()["projects"] == []

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"goal": 1},
            {"goal": GOAL, "surprise": 1},
            {"goal": GOAL, "max_team_size": 1.5},
            {"goal": GOAL, "meeting_rounds": "1"},
            {"goal": GOAL, "team": "lab", "memory": ["pick"]},
            {"goal": GOAL, "memory": "everything"},
        ],
    )
    def test_a_project_is_made_only_from_what_is_asked_for(self, client: TestClient, body: dict[str, Any]) -> None:
        assert client.post("/api/projects", json=body).status_code == 422

    @pytest.mark.parametrize(
        "body",
        [{}, {"max_cost": "5"}, {"max_cost": -1}, {"max_cost": 5, "max_rounds": 2.5}, {"max_cost": 5, "more": 1}],
    )
    def test_working_is_asked_for_with_what_it_may_spend(self, client: TestClient, body: dict[str, Any]) -> None:
        project = client.post("/api/projects", json={"goal": GOAL}).json()["id"]

        assert client.post(f"/api/projects/{project}/start", json=body).status_code == 422

    def test_a_project_that_is_not_there_is_not_found(self, client: TestClient) -> None:
        assert client.get("/api/projects/nothing").status_code == 404
        assert client.delete("/api/projects/nothing").status_code == 404
        assert client.post("/api/projects/nothing/start", json={"max_cost": 1}).status_code == 404
        assert client.get("/api/projects/nothing/steps/team").status_code == 404
