"""Tests of making a PaperAgent in one go: that the steps are the PaperAgent's own, done in the order that costs
least and none done again, that it stops where the person is to say something and says what, and carries on from there
when they have, that what was asked is kept and not asked again, that nothing else is done to the agent while it goes,
that a step that cannot be done for what the code is is skipped with why, and that it can be stopped and left, and
looked at again, whatever happened to it.

Git, Docker, the containers that tutorials, tools, and checks are run in, the services that give a paper's text, and the
model are replaced by stand-ins, as they are in the tests of the PaperAgent's steps, so that what making in one go does
is what is looked at here, and what each step does is in the tests of that step."""

import io
import json
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import test_server_bakeoff_building as building_tests
import test_server_paperagent_checks as checking
import test_server_paperagent_environment as environment
import test_server_paperagent_reference as reference
from conftest import TEST_MODEL, FakeClient, make_usage
from fastapi.testclient import TestClient
from test_paperagents_reading import queue, reading
from test_paperagents_reference import result_of
from test_server_bakeoff_building import (
    FIRST_CODE,
    OTHER_COMMIT,
    SECOND_CODE,
    THIRD_CODE,
    THIRD_DOI,
    Papers,
    Remotes,
    chunks_in,
    paper_of,
    read_by,
    without,
)
from test_server_bakeoffs import BEARER, DOI, LOCAL, OTHER_DOI, TOKEN, refused, why
from test_server_paperagent_checks import Checks
from test_server_paperagent_environment import COMMIT, Docker
from test_server_paperagent_reference import NOTEBOOK, SCRIPT, Containers, writes
from test_server_paperagent_repository import project
from test_server_paperagent_tools import CALLS, MAPPING

from virtual_lab.paperagents import checking as verifying
from virtual_lab.paperagents import repository as cloning
from virtual_lab.server import imported_agents
from virtual_lab.server import paperagent_checks as kept_checks
from virtual_lab.server import paperagent_onego as kept_onego
from virtual_lab.server.app import create_app
from virtual_lab.server.errors import ApiError
from virtual_lab.server.jobs import Job, JobConflictError, Jobs
from virtual_lab.server.paperagent_onego import RECORD_FILE, SCHEMA, OneGo
from virtual_lab.server.paperagents import ONEGO_JOB, READING_JOB, PaperAgents, is_given, steps_of
from virtual_lab.server.papers import money
from virtual_lab.server.workspace import Workspace
from virtual_lab.structured import StructuredOutputError
from virtual_lab.utils import compute_token_cost

# What the tests of the steps are made with, which are fixtures of the modules that test them
agents = building_tests.agents
client = building_tests.client
jobs = building_tests.jobs
model_client = building_tests.model_client
papers = building_tests.papers
small_chunks = building_tests.small_chunks
workspace = building_tests.workspace
docker = environment.docker
git_is_installed = environment.git_is_installed
marker = environment.marker
containers = reference.containers
replays = checking.replays

ORDER = ["repository", "reading", "look", "environment", "reference", "tools", "checks", "given"]
STEPS = ("fetch_repository", "read", "build_environment", "start_reference", "start_tools", "start_checks")
NO_LICENSE = "LICENSE"
NOTHING = {"README.md": "# CellMapper\n\nNothing here but words.\n"}


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    """Looks at a step that is being done often, as it is done in a moment."""
    monkeypatch.setattr(kept_onego, "POLL_SECONDS", 0.002)


@pytest.fixture
def onego(agents: PaperAgents) -> OneGo:
    return OneGo(agents)


@pytest.fixture
def remotes(marker: Path, monkeypatch: pytest.MonkeyPatch) -> Remotes:
    files = {
        **project(marker),
        SCRIPT: "print(1)\n",
        "cellmapper/mapping.py": MAPPING,
        "tests/test_mapping.py": checking.TESTS,
    }
    stand_in = Remotes(files)
    monkeypatch.setattr(cloning, "clone", stand_in)

    return stand_in


@pytest.fixture
def stack(
    remotes: Remotes, docker: Docker, containers: Containers, replays: Checks, papers: Papers, git_is_installed: None
) -> Remotes:
    """Everything that an agent is made with: its code, Docker, the containers, and its paper. The tutorials call two
    functions of the code, which tools are made of and checked by its tests."""
    containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=CALLS))

    return remotes


@pytest.fixture
def started(agents: PaperAgents, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The steps that were started, in order, by whatever started them."""
    order: list[str] = []
    for name in STEPS:

        def spy(*arguments: Any, _real: Any = getattr(agents, name), _name: str = name, **options: Any) -> Job:
            order.append(_name)

            return _real(*arguments, **options)

        monkeypatch.setattr(agents, name, spy)

    return order


def agent_of(agents: PaperAgents, repo: str | None = FIRST_CODE, doi: str = DOI, title: str = "CellMapper") -> str:
    return agents.create(title, {"kind": "doi", "doi": doi}, repo)


def settle(jobs: Jobs, agent_id: str, seconds: float = 30) -> None:
    """Waits for making an agent in one go to end, as it does when it is done or has to stop."""
    deadline = time.monotonic() + seconds
    while any(job.subject == agent_id for job in jobs.active(ONEGO_JOB)):
        assert time.monotonic() < deadline, "making it in one go did not end"
        time.sleep(0.01)


def does_nothing(jobs: Jobs, agent_id: str, message: str = "Doing nothing") -> Callable[..., Job]:
    """A step of a PaperAgent that goes to its end having done none of what it is for."""
    return lambda *arguments, **options: jobs.start("something-else", agent_id, message, lambda job: None)


def hold(release: threading.Event) -> None:
    """What a job does that is something else, which is to be in the way until it is let go."""
    release.wait(10)


def busy_with(other: Job) -> Job:
    """What a step of a PaperAgent says when another job is in its way."""
    raise ApiError(409, "busy", f"{other.title} is going", job=other.snapshot())


def waiting_for(onego: OneGo, agent_id: str, message: str, seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while (job := onego.view(agent_id)["job"]) is None or job["progress"].get("detail") != message:
        assert time.monotonic() < deadline, f"it did not say {message!r}"
        time.sleep(0.01)


def go(onego: OneGo, jobs: Jobs, agent_id: str, max_cost: float | None = 1, **options: Any) -> dict[str, Any]:
    """Asks for the agent to be made in one go, and says how it stands once it has ended."""
    onego.start(agent_id, max_cost, **options)
    settle(jobs, agent_id)

    return onego.view(agent_id)


def states(view: dict[str, Any]) -> dict[str, str]:
    return {step["step"]: step["state"] for step in view["steps"]}


def note_of(view: dict[str, Any], step: str) -> str:
    return str(next(each for each in view["steps"] if each["step"] == step)["note"])


def kept_record(workspace: Workspace, agent_id: str) -> dict[str, Any]:
    loaded = json.loads((workspace.paperagents_dir / agent_id / RECORD_FILE).read_text("utf-8"))
    assert isinstance(loaded, dict)

    return loaded


def rewrite(workspace: Workspace, agent_id: str, **changes: Any) -> None:
    """Edits what is kept, as a person or a process that has the files might."""
    path = workspace.paperagents_dir / agent_id / RECORD_FILE
    path.write_text(json.dumps({**json.loads(path.read_text("utf-8")), **changes}))


def tools_checked(agents: PaperAgents, agent_id: str) -> list[str]:
    return [
        entry["status"]
        for tool in agents.checks(agent_id)["tools"]
        for entry in tool["evidence"]
        if entry["kind"] in checking.RUN
    ]


class TestMakingAnAgent:
    def test_an_agent_whose_code_is_known_is_made_by_each_step_in_the_order_that_costs_least(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        papers: Papers,
        model_client: FakeClient,
        started: list[str],
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)

        view = go(onego, jobs, agent_id)

        assert view["state"] == "done" and view["stuck"] is None
        assert [step["step"] for step in view["steps"]] == ORDER
        assert set(states(view).values()) == {"done"}
        assert [step["title"] for step in view["steps"]][:3] == [
            "Fetch the code",
            "Read the paper",
            "Look at the code against the paper",
        ]
        # The code is fetched before the paper is read, which is the step that is paid for
        assert started == list(STEPS)
        agent = agents.lookup(agent_id)[1]
        assert steps_of(agent) == {
            "reading": "done",
            "repository": "done",
            "environment": "done",
            "data": "pending",
            "tools": "done",
        }
        assert is_given(agent)
        statuses = tools_checked(agents, agent_id)
        assert statuses and kept_checks.NOT_RUN not in statuses and kept_checks.STALE not in statuses
        assert view["summary"] == "Every step is done. It is given to the conversations you start from now on."
        assert view["job"] is None and view["started_at"] and view["finished_at"]
        assert len(model_client.completions.parse_calls) == 1 and papers.asked == [DOI]
        assert stack.addresses() == [FIRST_CODE]
        assert kept_record(workspace, agent_id) == {
            key: view[key] for key in ("state", "started_at", "finished_at", "settings", "stuck", "summary")
        } | {"schema": SCHEMA, "steps": [{k: v for k, v in step.items() if k != "title"} for step in view["steps"]]}
        json.dumps(view)

    def test_each_step_is_asked_of_the_agent_as_a_page_would_and_the_job_follows_where_it_is(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        docker.gate = threading.Event()

        begun = onego.start(agent_id, 1)

        assert begun["state"] == "running" and begun["job"]["kind"] == ONEGO_JOB
        assert (begun["job"]["subject"], begun["job"]["state"]) == (agent_id, "running")
        assert docker.started.wait(10)
        deadline = time.monotonic() + 10
        while (seen := onego.view(agent_id))["job"]["progress"].get("step") != "environment":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert seen["job"]["message"] == "Build the environment"
        assert seen["job"]["progress"]["steps"] == len(ORDER) and seen["job"]["progress"]["finished"] == 3
        assert states(seen) == {
            "repository": "done",
            "reading": "done",
            "look": "done",
            "environment": "running",
            "reference": "pending",
            "tools": "pending",
            "checks": "pending",
            "given": "pending",
        }
        assert seen["state"] == "running" and agents.view(agent_id)["onego"]["id"] == begun["job"]["id"]

        docker.gate.set()
        settle(jobs, agent_id)

        assert onego.view(agent_id)["state"] == "done" and agents.view(agent_id)["onego"] is None
        ended = jobs.get(begun["job"]["id"]).snapshot()
        assert ended["state"] == "succeeded" and ended["message"].startswith("Every step is done.")
        assert ended["progress"]["finished"] == len(ORDER) == ended["progress"]["steps"]

    def test_what_was_done_is_not_done_again(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
        started: list[str],
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        assert go(onego, jobs, agent_id)["state"] == "done"
        started.clear()

        view = go(onego, jobs, agent_id, max_cost=None)

        assert view["state"] == "done" and set(states(view).values()) == {"done"}
        assert note_of(view, "reading") == "The paper had been read."
        assert note_of(view, "given") == "It was given to your conversations already."
        assert started == ["fetch_repository", "build_environment", "start_reference", "start_tools"]
        assert len(docker.builds) == 1 and len(model_client.completions.parse_calls) == 1
        assert stack.addresses() == [FIRST_CODE]

    def test_what_a_person_did_by_hand_is_taken_as_done(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
        started: list[str],
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        building_tests.finish(agents.fetch_repository(agent_id))
        building_tests.finish(agents.build_environment(agent_id))
        started.clear()

        view = go(onego, jobs, agent_id)

        assert view["state"] == "done" and view["steps"][0]["step"] == "repository"
        assert note_of(view, "repository") == "The code had been fetched."
        assert note_of(view, "environment") == "The environment had been built."
        assert len(docker.builds) == 1 and stack.addresses() == [FIRST_CODE]
        assert started == [
            "fetch_repository",
            "read",
            "build_environment",
            "start_reference",
            "start_tools",
            "start_checks",
        ]

    def test_checks_that_are_of_something_else_are_done_again(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        model_client: FakeClient,
        started: list[str],
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        assert go(onego, jobs, agent_id)["state"] == "done"
        started.clear()
        tool = agents.checks(agent_id)["tools"][0]
        which = next(entry["kind"] for entry in tool["evidence"] if entry["kind"] in verifying.DEFAULT_KINDS)
        path = kept_checks.record_path(workspace.paperagents_dir / agent_id, tool["name"], which)
        path.write_text(json.dumps({**json.loads(path.read_text()), "commit": "b" * 40}))
        assert kept_checks.STALE in tools_checked(agents, agent_id)

        view = go(onego, jobs, agent_id, max_cost=None)

        assert view["state"] == "done" and "start_checks" in started
        assert kept_checks.STALE not in tools_checked(agents, agent_id)

    def test_an_agent_is_not_given_to_conversations_when_that_is_not_asked_for(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)

        view = go(onego, jobs, agent_id, give=False)

        assert view["state"] == "done" and states(view)["given"] == "skipped" and view["settings"]["give"] is False
        assert not is_given(agents.lookup(agent_id)[1])
        assert view["summary"] == "Every step is done."

    def test_an_agent_that_a_person_gave_is_not_taken_back_by_asking_for_it_not_to_be_given(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        agents.change(agent_id, given=True)
        read_by(model_client, FIRST_CODE)

        go(onego, jobs, agent_id, give=False)

        assert is_given(agents.lookup(agent_id)[1])


class TestWhatTheCodeAllows:
    def test_code_with_no_tutorial_is_made_as_far_as_it_allows_and_is_said_to_be_so(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
        containers: Containers,
    ) -> None:
        stack.by_address[FIRST_CODE] = without(stack.default, NOTEBOOK, SCRIPT)
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)

        asked = go(onego, jobs, agent_id)

        # Code that shows no tutorial is for the person to say whether to go on with, as no tool can be checked against
        # how its authors ran it
        assert (asked["state"], asked["stuck"]["kind"], asked["stuck"]["verdict"]) == ("waiting", "preflight", "ask")
        assert any("no notebook or example script" in each["detail"] for each in asked["stuck"]["checks"])

        view = go(onego, jobs, agent_id, go_on=True)

        assert view["state"] == "done" and view["stuck"] is None
        assert states(view) == {
            "repository": "done",
            "reading": "done",
            "look": "done",
            "environment": "done",
            "reference": "skipped",
            "tools": "skipped",
            "checks": "skipped",
            "given": "done",
        }
        assert "no tutorial" in note_of(view, "reference")
        assert note_of(view, "tools").startswith("Not done: ") and note_of(view, "checks").startswith("Not done: ")
        assert view["summary"].startswith("Made as far as the code allows.")
        assert view["summary"].endswith("It is given to the conversations you start from now on.")
        assert containers.runs == [] and is_given(agents.lookup(agent_id)[1])

    def test_tutorials_that_made_no_call_that_comes_to_a_tool_leave_the_agent_of_the_paper_and_its_environment(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
        containers: Containers,
    ) -> None:
        containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=[]))
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)

        view = go(onego, jobs, agent_id)

        assert view["state"] == "done" and states(view)["reference"] == "done"
        assert states(view)["tools"] == "skipped" and states(view)["checks"] == "skipped"
        assert steps_of(agents.lookup(agent_id)[1])["tools"] == "pending"
        assert note_of(view, "checks").startswith("Not done: ")
        assert view["summary"].startswith("Made as far as the code allows.")

    def test_an_environment_that_cannot_be_built_here_skips_what_needs_it(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
        containers: Containers,
    ) -> None:
        stack.by_address[FIRST_CODE] = {
            "README.md": "# CellMapper\n\nMaps cells.\n\n## Usage\n\nSee the script.\n",
            "LICENSE": stack.default["LICENSE"],
            "renv.lock": "{}",
            "analysis.R": "library(Seurat)\n",
        }
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)

        assert go(onego, jobs, agent_id)["stuck"]["kind"] == "preflight"

        view = go(onego, jobs, agent_id, go_on=True)

        assert view["state"] == "done" and states(view)["environment"] == "skipped"
        assert note_of(view, "environment").startswith("The code is in R") and "Only Python is built" in view["summary"]
        assert {states(view)[step] for step in ("reference", "tools", "checks")} == {"skipped"}
        assert all(note_of(view, step).startswith("Not done: ") for step in ("reference", "tools", "checks"))
        assert containers.runs == []

    def test_going_on_without_the_code_makes_an_agent_of_the_paper_only(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents, None, DOI)
        read_by(model_client, FIRST_CODE)

        view = go(onego, jobs, agent_id, without_code=True)

        assert view["state"] == "done"
        assert states(view) == {
            "reading": "done",
            "repository": "skipped",
            "look": "skipped",
            "environment": "skipped",
            "reference": "skipped",
            "tools": "skipped",
            "checks": "skipped",
            "given": "done",
        }
        assert {
            note_of(view, step) for step in ("repository", "look", "environment", "reference", "tools", "checks")
        } == {"You chose to go on without the code."}
        assert stack.calls == [] and docker.builds == []
        assert steps_of(agents.lookup(agent_id)[1])["reading"] == "done"
        assert view["summary"].startswith("Made as far as the code allows. You chose")


class TestWhereThePersonIsToSay:
    def test_code_that_cannot_be_used_is_found_so_before_the_paper_is_read_and_costs_nothing(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        papers: Papers,
        model_client: FakeClient,
    ) -> None:
        stack.by_address[FIRST_CODE] = NOTHING
        agent_id = agent_of(agents)

        view = go(onego, jobs, agent_id)

        assert view["state"] == "waiting"
        stuck = view["stuck"]
        assert (stuck["step"], stuck["kind"], stuck["verdict"], stuck["commit"]) == (
            "look",
            "preflight",
            "no-go",
            COMMIT,
        )
        assert stuck["reason"].startswith("No-go: No code was found") and "Go on if you accept that" in stuck["reason"]
        assert any(each["status"] == "block" for each in stuck["checks"])
        assert states(view)["repository"] == "done" and states(view)["look"] == "waiting"
        assert states(view)["reading"] == "pending" and states(view)["environment"] == "pending"
        assert model_client.completions.parse_calls == [] and papers.asked == []
        assert kept_record(workspace, agent_id)["state"] == "waiting"
        assert steps_of(agents.lookup(agent_id)[1])["reading"] == "pending"

    def test_going_on_with_the_code_that_was_looked_at_carries_on_and_nothing_is_done_again(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
        started: list[str],
    ) -> None:
        stack.by_address[FIRST_CODE] = NOTHING
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        assert go(onego, jobs, agent_id)["state"] == "waiting"

        # Asked for again without saying, it is asked again, and nothing was paid for
        again = go(onego, jobs, agent_id)
        assert again["state"] == "waiting" and again["stuck"]["kind"] == "preflight"
        assert model_client.completions.parse_calls == [] and started == ["fetch_repository", "fetch_repository"]

        view = go(onego, jobs, agent_id, go_on=True)

        assert view["settings"]["go_on"] == COMMIT
        assert "You said to go on." in note_of(view, "look")
        # Nothing in the code says what to install, so what is left cannot be done, and is said so
        assert view["state"] == "done" and states(view)["reading"] == "done"
        assert {states(view)[step] for step in ("environment", "reference", "tools", "checks")} == {"skipped"}
        assert view["summary"].startswith("Made as far as the code allows. No file in the code says what to install")
        assert len(model_client.completions.parse_calls) == 1
        assert stack.addresses() == [FIRST_CODE]
        assert kept_record(workspace, agent_id)["settings"]["go_on"] == COMMIT

    def test_code_with_things_to_weigh_is_asked_about_once_the_paper_has_been_read_and_not_before(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
        started: list[str],
    ) -> None:
        stack.by_address[FIRST_CODE] = without(stack.default, NO_LICENSE)
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)

        view = go(onego, jobs, agent_id)

        assert view["state"] == "waiting"
        stuck = view["stuck"]
        assert (stuck["step"], stuck["kind"], stuck["verdict"]) == ("look", "preflight", "ask")
        assert stuck["reason"].startswith("Ask first.") and "license" in stuck["reason"]
        assert {each["status"] for each in stuck["checks"]} <= {"warn", "block", "unknown"}
        # The paper was read, since what it says may bear on what is asked, and nothing was built
        assert states(view)["reading"] == "done" and states(view)["look"] == "waiting"
        assert docker.builds == [] and len(model_client.completions.parse_calls) == 1

        done = go(onego, jobs, agent_id, go_on=True)

        assert done["state"] == "done" and len(docker.builds) == 1
        assert len(model_client.completions.parse_calls) == 1 and started.count("read") == 1
        assert done["settings"]["go_on"] == COMMIT

    def test_what_the_person_says_is_of_the_commit_that_was_looked_at_and_not_of_another(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        stack.by_address[FIRST_CODE] = without(stack.default, NO_LICENSE)
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        go(onego, jobs, agent_id)
        assert go(onego, jobs, agent_id, go_on=True)["state"] == "done"

        agents.clear_repository(agent_id)
        stack.commit = OTHER_COMMIT
        view = go(onego, jobs, agent_id)

        assert view["state"] == "waiting" and view["stuck"]["commit"] == OTHER_COMMIT
        assert view["settings"]["go_on"] == COMMIT
        assert len(docker.builds) == 1
        assert go(onego, jobs, agent_id, go_on=True)["settings"]["go_on"] == OTHER_COMMIT

    def test_what_the_person_said_can_be_taken_back(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        stack.by_address[FIRST_CODE] = without(stack.default, NO_LICENSE)
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        go(onego, jobs, agent_id)
        go(onego, jobs, agent_id, go_on=True, give=False)
        agents.clear_environment(agent_id)

        view = go(onego, jobs, agent_id, go_on=False)

        assert view["settings"]["go_on"] is None
        assert view["state"] == "waiting" and view["stuck"]["kind"] == "preflight"
        assert view["settings"]["give"] is False

    def test_going_on_is_refused_before_there_is_code_to_go_on_with(
        self, onego: OneGo, agents: PaperAgents, stack: Remotes
    ) -> None:
        agent_id = agent_of(agents)

        assert why(onego.start, agent_id, 1, go_on=True) == (409, "no_code")
        assert onego.view(agent_id)["state"] == "none"

    def test_where_the_code_is_is_for_the_person_to_say_and_what_the_paper_points_to_is_not_taken_for_it(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        papers: Papers,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        papers.texts[THIRD_DOI] = paper_of("GraphCells", THIRD_CODE)
        agent_id = agent_of(agents, None, THIRD_DOI, "GraphCells")
        read_by(model_client, THIRD_CODE)

        view = go(onego, jobs, agent_id)

        assert view["state"] == "waiting"
        assert [step["step"] for step in view["steps"]][:2] == ["reading", "repository"]
        stuck = view["stuck"]
        assert (stuck["step"], stuck["kind"]) == ("repository", "code")
        assert [each["url"] for each in stuck["candidates"]] == [THIRD_CODE]
        assert stuck["candidates"][0]["role"] == "code" and THIRD_CODE in stuck["candidates"][0]["quote"]
        assert "Say which, if any, is its code" in stuck["reason"]
        assert states(view)["reading"] == "done" and states(view)["repository"] == "waiting"
        assert stack.calls == [] and agents.lookup(agent_id)[1]["repo"] is None

        # They say which it is, and the paper is not read again
        done = go(onego, jobs, agent_id, max_cost=None, repo=THIRD_CODE)

        assert done["state"] == "done" and done["settings"]["repo"] == THIRD_CODE
        assert stack.addresses() == [THIRD_CODE] and len(model_client.completions.parse_calls) == 1
        assert agents.lookup(agent_id)[1]["repo"]["url"] == THIRD_CODE
        assert kept_record(workspace, agent_id)["state"] == "done"

    def test_a_paper_that_points_to_no_code_says_so_and_what_can_be_done(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents, None, THIRD_DOI, "GraphCells")
        read_by(model_client, None)

        view = go(onego, jobs, agent_id)

        assert view["state"] == "waiting" and view["stuck"]["kind"] == "code"
        assert view["stuck"]["candidates"] == []
        assert "does not point to any" in view["stuck"]["reason"] and "without it" in view["stuck"]["reason"]

    def test_the_paper_is_read_when_the_code_is_not_known_and_not_before_the_code_is_when_it_is(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
        started: list[str],
    ) -> None:
        agent_id = agent_of(agents, None)
        read_by(model_client, FIRST_CODE)

        go(onego, jobs, agent_id)
        assert started == ["read"]

        started.clear()
        view = go(onego, jobs, agent_id, repo=FIRST_CODE)
        assert view["state"] == "done" and [step["step"] for step in view["steps"]][:2] == ["repository", "reading"]
        assert started[:2] == ["fetch_repository", "build_environment"]

    def test_reading_that_reaches_the_limit_waits_for_more_to_spend_and_carries_on_from_where_it_stopped(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        papers: Papers,
        model_client: FakeClient,
        small_chunks: None,
    ) -> None:
        papers.texts[DOI] += "\n\n" + "\n\n".join(
            f"Paragraph {number} of the methods of the paper." for number in range(12)
        )
        chunks = chunks_in(papers.texts[DOI])
        each = float(compute_token_cost(TEST_MODEL, 1_000, 0))
        agent_id = agent_of(agents)
        queue(model_client, *[reading()] * chunks, usage=make_usage(prompt_tokens=1_000, completion_tokens=0))

        view = go(onego, jobs, agent_id, max_cost=each * 2.5)

        assert view["state"] == "waiting"
        stuck = view["stuck"]
        assert (stuck["step"], stuck["kind"]) == ("reading", "limit")
        done = len(model_client.completions.parse_calls)
        assert 0 < done < chunks
        assert stuck["limit"] == pytest.approx(each * 2.5) and stuck["spent"] == pytest.approx(done * each)
        assert f"having spent {money(done * each)} of the {money(each * 2.5)}" in stuck["reason"]
        assert "carries on from where it stopped" in stuck["reason"]
        assert states(view)["reading"] == "waiting" and states(view)["look"] == "pending"
        assert steps_of(agents.lookup(agent_id)[1])["reading"] == "pending"

        # With more to spend, what was read is not read again
        queue(model_client, *[reading()] * (chunks - done))
        again = go(onego, jobs, agent_id, max_cost=1)

        assert again["state"] == "done" and again["settings"]["max_cost"] == 1
        assert len(model_client.completions.parse_calls) == chunks
        assert stack.addresses() == [FIRST_CODE]

    def test_a_paper_whose_text_could_not_be_had_waits_for_its_file(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        papers: Papers,
        model_client: FakeClient,
    ) -> None:
        papers.texts.clear()
        agent_id = agent_of(agents)

        view = go(onego, jobs, agent_id)

        assert view["state"] == "waiting"
        assert (view["stuck"]["step"], view["stuck"]["kind"]) == ("reading", "paper_text")
        assert (
            "Europe PMC does not give out the text" in view["stuck"]["reason"] and "Upload" in view["stuck"]["reason"]
        )
        assert model_client.completions.parse_calls == [] and states(view)["repository"] == "done"

        papers.texts[DOI] = paper_of("CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)
        again = go(onego, jobs, agent_id, max_cost=None)

        assert again["state"] == "done" and again["settings"]["max_cost"] == 1

    def test_a_paper_that_is_a_file_that_was_not_uploaded_waits_for_it(
        self, onego: OneGo, agents: PaperAgents, jobs: Jobs, stack: Remotes, model_client: FakeClient
    ) -> None:
        agent_id = agents.create("No paper yet", {"kind": "file"}, FIRST_CODE)

        view = go(onego, jobs, agent_id)

        assert view["state"] == "waiting" and (view["stuck"]["step"], view["stuck"]["kind"]) == (
            "reading",
            "paper_file",
        )
        assert view["stuck"]["reason"].startswith("The paper is a file that has not been uploaded")
        assert model_client.completions.parse_calls == []

    def test_docker_that_is_not_running_waits_for_it_to_be_and_what_was_done_is_kept(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        docker.usable = (False, "Docker is not running. Start it and try again.")

        view = go(onego, jobs, agent_id)

        assert view["state"] == "waiting"
        assert (view["stuck"]["step"], view["stuck"]["kind"]) == ("environment", "docker")
        assert view["stuck"]["reason"] == "Docker is not running. Start it and try again. Start it, and go on."
        assert states(view)["reading"] == "done" and states(view)["environment"] == "waiting"
        assert view["finished_at"]

        docker.usable = (True, None)
        assert go(onego, jobs, agent_id, max_cost=None)["state"] == "done"
        assert len(model_client.completions.parse_calls) == 1

    @pytest.mark.parametrize(
        ("starter", "step", "reason"),
        [
            ("fetch_repository", "repository", "The code was not fetched"),
            ("build_environment", "environment", "The environment was not built"),
        ],
    )
    def test_a_step_that_ends_without_what_it_was_for_is_failed_and_says_so(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
        starter: str,
        step: str,
        reason: str,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        monkeypatch.setattr(agents, starter, does_nothing(jobs, agent_id))

        view = go(onego, jobs, agent_id)

        assert view["state"] == "failed" and (view["stuck"]["step"], view["stuck"]["kind"]) == (step, "failed")
        assert view["stuck"]["reason"] == reason

    @pytest.mark.parametrize(
        ("starter", "step", "reason"),
        [
            (
                "start_reference",
                "reference",
                "The tutorials did not run to their end, so no tool can be made of what they did.",
            ),
            (
                "start_tools",
                "tools",
                "No call that the tutorials made came to a tool that gives again what the tutorial got.",
            ),
        ],
    )
    def test_a_step_that_ends_without_what_the_code_allows_is_skipped_with_why(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
        starter: str,
        step: str,
        reason: str,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        monkeypatch.setattr(agents, starter, does_nothing(jobs, agent_id, ""))

        view = go(onego, jobs, agent_id)

        assert view["state"] == "done" and states(view)[step] == "skipped" and note_of(view, step) == reason
        assert states(view)["checks"] == "skipped" and note_of(view, "checks").startswith("Not done: ")

    def test_a_step_that_goes_wrong_in_a_way_that_was_not_looked_for_ends_it_as_failed_with_what_it_was(
        self, onego: OneGo, agents: PaperAgents, jobs: Jobs, stack: Remotes, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_id = agent_of(agents)

        def breaks(*arguments: Any, **options: Any) -> Job:
            raise RuntimeError("it broke")

        monkeypatch.setattr(agents, "fetch_repository", breaks)

        view = go(onego, jobs, agent_id)

        assert view["state"] == "failed" and (view["stuck"]["step"], view["stuck"]["kind"]) == ("repository", "error")
        assert view["stuck"]["reason"] == "RuntimeError: it broke"
        assert states(view)["repository"] == "failed"

    def test_code_that_has_not_been_looked_at_is_not_gone_on_from(
        self, onego: OneGo, agents: PaperAgents, jobs: Jobs, stack: Remotes, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_id = agent_of(agents)
        real = agents.repository
        monkeypatch.setattr(
            agents, "repository", lambda *arguments, **options: {**real(*arguments, **options), "preflight": None}
        )

        view = go(onego, jobs, agent_id)

        assert view["state"] == "failed" and view["stuck"]["kind"] == "no_code"
        assert view["stuck"]["reason"] == "The code has not been fetched, so it cannot be looked at"

    def test_git_that_is_not_installed_waits_for_it_to_be(
        self, onego: OneGo, agents: PaperAgents, jobs: Jobs, stack: Remotes, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_id = agent_of(agents)
        monkeypatch.setattr(shutil, "which", lambda name, *rest, **options: None)

        view = go(onego, jobs, agent_id)

        assert view["state"] == "waiting" and (view["stuck"]["step"], view["stuck"]["kind"]) == ("repository", "git")
        assert view["stuck"]["reason"] == (
            "Git is not installed on this machine, and fetching code takes it. Install it, and go on."
        )
        assert stack.calls == []

    @pytest.mark.parametrize(("status", "code"), [(422, "missing_keys"), (502, "unavailable")])
    def test_a_model_that_a_step_finds_without_its_key_or_out_of_reach_waits_for_it(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        monkeypatch: pytest.MonkeyPatch,
        status: int,
        code: str,
    ) -> None:
        agent_id = agent_of(agents)

        def refuse(*arguments: Any, **options: Any) -> Job:
            raise ApiError(status, code, "The model cannot be had")

        monkeypatch.setattr(agents, "read", refuse)

        view = go(onego, jobs, agent_id)

        assert view["state"] == "waiting" and (view["stuck"]["step"], view["stuck"]["kind"]) == ("reading", "model")
        assert view["stuck"]["reason"] == "The model cannot be had" and states(view)["repository"] == "done"

    def test_a_model_that_has_no_key_is_refused_before_anything_is_started(
        self,
        workspace: Workspace,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
    ) -> None:
        keyless_agents = PaperAgents(workspace, 100_000, jobs, lambda model: ["OPENAI_API_KEY"])
        keyless = OneGo(keyless_agents)
        agent_id = agent_of(keyless_agents)

        error = refused(keyless.start, agent_id, 1)

        assert (error.status, error.code) == (422, "missing_keys")
        assert keyless.view(agent_id)["state"] == "none" and stack.calls == []
        assert model_client.completions.parse_calls == []

    def test_a_step_that_goes_wrong_ends_it_as_failed_with_why_and_it_can_be_tried_again(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        docker.error = RuntimeError("the build broke")

        onego.start(agent_id, 1)
        settle(jobs, agent_id)
        view = onego.view(agent_id)

        assert view["state"] == "failed"
        assert (view["stuck"]["step"], view["stuck"]["kind"]) == ("environment", "failed")
        assert "the build broke" in view["stuck"]["reason"]
        assert states(view)["environment"] == "failed" and states(view)["reference"] == "pending"
        job = next(each for each in jobs.snapshots() if each["kind"] == ONEGO_JOB)
        assert job["state"] == "failed" and "the build broke" in job["error"]

        docker.error = None
        assert go(onego, jobs, agent_id, max_cost=None)["state"] == "done"
        assert len(model_client.completions.parse_calls) == 1 and kept_record(workspace, agent_id)["stuck"] is None

    def test_a_paper_none_of_which_could_be_read_and_a_reading_that_went_wrong_each_say_so(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
    ) -> None:
        refusing = agent_of(agents)
        queue(model_client, StructuredOutputError("The model refused", usage=make_usage()))

        view = go(onego, jobs, refusing)

        assert view["state"] == "failed"
        assert (view["stuck"]["step"], view["stuck"]["kind"]) == ("reading", "failed")
        assert view["stuck"]["reason"] == "No part of the paper could be read"
        assert states(view)["reading"] == "failed" and states(view)["look"] == "pending"

        broken = agent_of(agents, SECOND_CODE, OTHER_DOI, "Labeller")
        queue(model_client, RuntimeError("the network went away"))

        again = go(onego, jobs, broken)

        assert again["state"] == "failed" and again["stuck"]["reason"] == "the network went away"
        assert (again["stuck"]["step"], again["stuck"]["kind"]) == ("reading", "failed")
        assert steps_of(agents.lookup(broken)[1])["reading"] == "failed"


class TestWhatIsAskedFor:
    def test_what_is_asked_wrongly_is_refused_and_nothing_is_kept_or_started(
        self, onego: OneGo, agents: PaperAgents, stack: Remotes, model_client: FakeClient
    ) -> None:
        agent_id = agent_of(agents)

        assert why(onego.start, agent_id, None) == (422, "invalid")
        for bad in (-1, "a lot", True, float("inf"), float("nan")):
            assert why(onego.start, agent_id, bad) == (422, "invalid"), bad
        assert why(onego.start, agent_id, 1, "not an address") == (422, "invalid")
        assert why(onego.start, agent_id, 1, None, "-bad-ref") == (422, "invalid")
        assert why(onego.start, agent_id, 1, give="yes") == (422, "invalid")
        assert why(onego.start, agent_id, 1, without_code="no") == (422, "invalid")
        assert why(onego.start, agent_id, 1, go_on="yes") == (422, "invalid")
        assert why(onego.start, "00000000-none", 1) == (404, "not_found")
        assert onego.view(agent_id)["state"] == "none" and stack.calls == []
        assert model_client.completions.parse_calls == []

    def test_nothing_need_be_said_to_spend_when_the_paper_has_been_read(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        building_tests.finish(agents.read(agent_id, 1))

        view = go(onego, jobs, agent_id, max_cost=None)

        assert view["state"] == "done" and view["settings"]["max_cost"] is None

    def test_what_was_asked_before_is_what_is_asked_unless_it_is_said_again(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        stack.by_address[FIRST_CODE] = without(stack.default, NO_LICENSE)
        agent_id = agent_of(agents, None)
        read_by(model_client, FIRST_CODE)
        first = go(onego, jobs, agent_id, 0.75, repo=FIRST_CODE, ref="main", give=False)
        assert first["state"] == "waiting"
        assert first["settings"] == {
            "max_cost": 0.75,
            "repo": FIRST_CODE,
            "ref": "main",
            "give": False,
            "without_code": False,
            "go_on": None,
        }

        view = go(onego, jobs, agent_id, max_cost=None, go_on=True)

        assert view["settings"] == {**first["settings"], "go_on": COMMIT}
        assert view["state"] == "done" and not is_given(agents.lookup(agent_id)[1])
        assert stack.calls[0]["ref"] == "main"

    def test_code_that_was_fetched_from_one_address_is_not_made_of_another(
        self, onego: OneGo, agents: PaperAgents, jobs: Jobs, stack: Remotes, model_client: FakeClient
    ) -> None:
        agent_id = agent_of(agents)
        building_tests.finish(agents.fetch_repository(agent_id))

        error = refused(onego.start, agent_id, 1, SECOND_CODE)

        assert (error.status, error.code) == (409, "code_fetched") and FIRST_CODE in error.message
        assert onego.view(agent_id)["state"] == "none"
        read_by(model_client, FIRST_CODE)
        assert go(onego, jobs, agent_id, repo=FIRST_CODE)["state"] == "done"

    def test_an_agent_that_another_server_hosts_has_nothing_here_to_make_it_of(
        self, onego: OneGo, agents: PaperAgents, stack: Remotes
    ) -> None:
        hosted = imported_agents.record_of("https://mcp.example.org/mcp", [])
        agent_id = agents.create("Hosted elsewhere", {"kind": "doi", "doi": DOI}, None, imported=hosted)

        assert why(onego.start, agent_id, 1) == (422, "imported")
        assert onego.view(agent_id)["state"] == "none" and stack.calls == []


class TestWhileItGoes:
    def test_nothing_else_is_done_to_the_agent_while_it_is_made_and_it_can_be_afterwards(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        release = threading.Event()
        other = jobs.start("something-else", agent_id, "Something else", lambda job: hold(release))
        real = agents.fetch_repository
        monkeypatch.setattr(
            agents,
            "fetch_repository",
            lambda *arguments, **options: real(*arguments, **options) if not other.active else busy_with(other),
        )
        onego.start(agent_id, 1)
        waiting_for(onego, agent_id, "Waiting for: Something else")
        # Between its steps, when no step of the agent is going, only what it is stands in the way
        assert [each.kind for each in jobs.active() if each.subject == agent_id] == ["something-else", ONEGO_JOB]

        for call in (
            lambda: agents.read(agent_id, 1),
            lambda: agents.clear_repository(agent_id),
            lambda: agents.clear_reading(agent_id),
            lambda: agents.put_paper(agent_id, "paper.txt", io.BytesIO(b"A paper.")),
            lambda: agents.change(agent_id, repo=SECOND_CODE),
            lambda: agents.delete(agent_id),
            lambda: onego.start(agent_id, 1),
            lambda: onego.clear(agent_id),
        ):
            error = refused(call)
            assert (error.status, error.code) == (409, "busy")
            assert error.details["job"]["kind"] == ONEGO_JOB and error.details["job"]["subject"] == agent_id
        agents.change(agent_id, title="Renamed")
        assert agents.lookup(agent_id)[1]["title"] == "Renamed"
        assert steps_of(agents.lookup(agent_id)[1])["reading"] == "pending"

        release.set()
        settle(jobs, agent_id)

        assert onego.view(agent_id)["state"] == "done"
        assert why(agents.read, agent_id, 1) == (409, "done")
        onego.clear(agent_id)
        assert onego.view(agent_id)["state"] == "none"

    def test_nothing_is_refused_to_the_steps_that_it_starts_itself(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        assert agents.going(agent_id) is None

        view = go(onego, jobs, agent_id)

        assert view["state"] == "done" and agents.going(agent_id) is None
        with agents.driving(agent_id):
            assert agents.going(agent_id) is None
        assert agents.going(agent_id) is None

    def test_it_is_not_started_while_the_agent_is_being_worked_on(
        self, onego: OneGo, agents: PaperAgents, jobs: Jobs, stack: Remotes
    ) -> None:
        agent_id = agent_of(agents)
        release = threading.Event()
        jobs.start(READING_JOB, agent_id, "Reading the paper", lambda job: hold(release))
        try:
            error = refused(onego.start, agent_id, 1)
            assert (error.status, error.code) == (409, "busy")
            assert error.details["job"]["kind"] == READING_JOB
            assert onego.view(agent_id)["state"] == "none"
        finally:
            release.set()

    def test_the_driver_is_the_driver_of_it_only_while_it_is_made(
        self, onego: OneGo, agents: PaperAgents, jobs: Jobs, stack: Remotes, docker: Docker, model_client: FakeClient
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        docker.gate = threading.Event()
        onego.start(agent_id, 1)
        assert docker.started.wait(10)
        try:
            with agents.driving(agent_id):
                assert agents.going(agent_id) is None
            assert agents.going(agent_id) is not None
        finally:
            docker.gate.set()
            settle(jobs, agent_id)

        assert onego.view(agent_id)["state"] == "done" and agents.going(agent_id) is None

    def test_the_job_of_one_agent_is_not_the_job_of_another(
        self, onego: OneGo, agents: PaperAgents, jobs: Jobs, stack: Remotes, docker: Docker, model_client: FakeClient
    ) -> None:
        agent_id = agent_of(agents)
        other_id = agent_of(agents, SECOND_CODE, OTHER_DOI, "Other")
        read_by(model_client, FIRST_CODE)
        docker.gate = threading.Event()
        onego.start(agent_id, 1)
        assert docker.started.wait(10)
        try:
            assert agents.going(agent_id) is not None and agents.view(agent_id)["onego"] is not None
            assert agents.going(other_id) is None and agents.view(other_id)["onego"] is None
        finally:
            docker.gate.set()
            settle(jobs, agent_id)

    def test_a_step_that_someone_else_started_is_waited_for_and_not_failed_by(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        release = threading.Event()
        other = jobs.start("something-else", agent_id, "Something else", lambda job: hold(release))
        real = agents.fetch_repository
        asked: list[int] = []

        def blocked(*arguments: Any, **options: Any) -> Job:
            asked.append(1)

            return busy_with(other) if other.active else real(*arguments, **options)

        monkeypatch.setattr(agents, "fetch_repository", blocked)
        onego.start(agent_id, 1)
        waiting_for(onego, agent_id, "Waiting for: Something else")
        assert onego.view(agent_id)["state"] == "running" and len(asked) == 1

        release.set()
        settle(jobs, agent_id)

        assert onego.view(agent_id)["state"] == "done" and len(asked) == 2

    def test_it_is_stopped_while_it_waits_for_a_step_that_someone_else_started_which_goes_on(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        agent_id = agent_of(agents)
        release = threading.Event()
        other = jobs.start("something-else", agent_id, "Something else", lambda job: hold(release))
        monkeypatch.setattr(agents, "fetch_repository", lambda *arguments, **options: busy_with(other))
        begun = onego.start(agent_id, 1)
        waiting_for(onego, agent_id, "Waiting for: Something else")

        jobs.stop(begun["job"]["id"])
        try:
            settle(jobs, agent_id, seconds=5)
            assert other.active
        finally:
            release.set()

        view = onego.view(agent_id)
        assert view["state"] == "stopped" and view["stuck"]["step"] == "repository"
        assert stack.calls == []

    def test_a_step_that_stays_in_the_way_of_another_is_said_to_be_in_the_way_after_a_few_waits(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        agent_id = agent_of(agents)
        other = jobs.start("something-else", agent_id, "Something else", lambda job: None)
        building_tests.finish(other)
        asked: list[int] = []

        def blocked(*arguments: Any, **options: Any) -> Job:
            asked.append(1)

            return busy_with(other)

        monkeypatch.setattr(agents, "fetch_repository", blocked)

        view = go(onego, jobs, agent_id)

        assert view["state"] == "failed" and view["stuck"]["kind"] == "refused"
        assert len(asked) == kept_onego.MOST_WAITS + 1

    def test_it_is_stopped_where_it_is_and_the_step_that_was_going_is_stopped_with_it(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        docker.gate = threading.Event()
        begun = onego.start(agent_id, 1)
        assert docker.started.wait(10)

        jobs.stop(begun["job"]["id"])
        settle(jobs, agent_id)

        view = onego.view(agent_id)
        assert view["state"] == "stopped" and view["stuck"]["kind"] == "stopped"
        assert view["stuck"]["step"] == "environment" and states(view)["environment"] == "stopped"
        assert view["stuck"]["reason"].startswith("Stopped. What was made is kept")
        assert jobs.get(begun["job"]["id"]).state == "stopped"
        assert agents.making(agent_id) is None
        assert steps_of(agents.lookup(agent_id)[1])["environment"] == "pending"
        assert steps_of(agents.lookup(agent_id)[1])["reading"] == "done"
        assert kept_record(workspace, agent_id)["state"] == "stopped"

        # Going on is from where it stopped: nothing that was done is done again
        docker.gate = None
        assert go(onego, jobs, agent_id, max_cost=None)["state"] == "done"
        assert len(model_client.completions.parse_calls) == 1 and stack.addresses() == [FIRST_CODE]

    def test_a_step_that_someone_else_stopped_ends_it_as_stopped_and_says_so(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        docker.gate = threading.Event()
        begun = onego.start(agent_id, 1)
        assert docker.started.wait(10)
        step = agents.making(agent_id)
        assert step is not None

        step.request_stop()
        settle(jobs, agent_id)

        view = onego.view(agent_id)
        assert view["state"] == "stopped" and view["stuck"]["step"] == "environment"
        assert view["stuck"]["kind"] == "stopped" and "was stopped" in view["stuck"]["reason"]
        assert jobs.get(begun["job"]["id"]).state == "stopped"

    def test_the_server_stopping_stops_it_and_it_is_kept_as_stopped(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        docker.gate = threading.Event()
        onego.start(agent_id, 1)
        assert docker.started.wait(10)

        jobs.close()

        assert kept_record(workspace, agent_id)["state"] == "stopped"
        assert onego.view(agent_id)["state"] == "stopped"


class TestWhatIsKept:
    def test_nothing_is_said_of_an_agent_that_was_not_made_in_one_go_but_what_it_would_do(
        self, onego: OneGo, agents: PaperAgents, stack: Remotes
    ) -> None:
        agent_id = agent_of(agents)

        view = onego.view(agent_id)

        assert view["state"] == "none" and view["job"] is None and view["stuck"] is None and view["summary"] is None
        assert [step["step"] for step in view["steps"]] == ORDER and set(states(view).values()) == {"pending"}
        assert view["settings"]["give"] is True and view["settings"]["max_cost"] is None
        assert [step["step"] for step in onego.view(agent_of(agents, None, THIRD_DOI, "Other"))["steps"]][:2] == [
            "reading",
            "repository",
        ]
        assert why(onego.view, "00000000-none") == (404, "not_found")

    def test_a_record_that_says_it_is_going_when_no_job_is_is_said_to_be_interrupted_and_can_be_gone_on_from(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        go(onego, jobs, agent_id)
        rewrite(workspace, agent_id, state="running", finished_at=None)

        assert onego.view(agent_id)["state"] == "interrupted"
        view = go(onego, jobs, agent_id, max_cost=None)

        assert view["state"] == "done" and len(model_client.completions.parse_calls) == 1

    @pytest.mark.parametrize(
        "damage",
        [
            {"schema": 2},
            {"state": "finished"},
            {"started_at": 3},
            {"settings": []},
            {"steps": {}},
            {"steps": [{"step": "nothing", "state": "done", "note": None}]},
            {"steps": [{"step": "reading", "state": "ended", "note": None}]},
            {"steps": [{"step": "reading", "state": "done", "note": 7}]},
            {"steps": ["reading"]},
            {"stuck": "words"},
            {"summary": 5},
        ],
    )
    def test_a_record_that_is_not_in_the_shape_that_it_is_kept_in_is_not_used(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        model_client: FakeClient,
        damage: dict[str, Any],
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        go(onego, jobs, agent_id)
        rewrite(workspace, agent_id, **damage)

        view = onego.view(agent_id)

        assert view["state"] == "none" and view["started_at"] is None and view["summary"] is None
        assert set(states(view).values()) == {"pending"}

    def test_a_record_that_is_not_json_or_is_too_big_or_is_a_link_is_not_used(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        model_client: FakeClient,
        tmp_path: Path,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        go(onego, jobs, agent_id)
        path = workspace.paperagents_dir / agent_id / RECORD_FILE
        good = path.read_text("utf-8")

        path.write_text("{not json")
        assert onego.view(agent_id)["state"] == "none"
        path.write_text(good + " " * kept_onego.MAX_RECORD_BYTES)
        assert onego.view(agent_id)["state"] == "none"
        path.unlink()
        elsewhere = tmp_path / "elsewhere.json"
        elsewhere.write_text(good)
        path.symlink_to(elsewhere)
        assert onego.view(agent_id)["state"] == "none"

    def test_what_is_kept_says_what_stood_in_the_way_in_a_line_that_is_not_long(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        docker.error = RuntimeError("line one\n" + "a very long line " * 400)

        view = go(onego, jobs, agent_id)

        reason = view["stuck"]["reason"]
        assert view["state"] == "failed" and "\n" not in reason and len(reason) <= kept_onego.MAX_TEXT_CHARS
        assert note_of(view, "environment") == reason

    def test_what_was_made_of_it_is_taken_away_when_asked_and_not_while_it_goes(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        go(onego, jobs, agent_id)
        assert (workspace.paperagents_dir / agent_id / RECORD_FILE).is_file()

        onego.clear(agent_id)
        onego.clear(agent_id)

        assert not (workspace.paperagents_dir / agent_id / RECORD_FILE).exists()
        assert onego.view(agent_id)["state"] == "none"
        assert steps_of(agents.lookup(agent_id)[1])["tools"] == "done"
        assert why(onego.clear, "00000000-none") == (404, "not_found")

    def test_it_is_kept_in_the_agents_own_directory_and_goes_with_it(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        model_client: FakeClient,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        go(onego, jobs, agent_id)
        assert [path.name for path in workspace.paperagents_dir.rglob(RECORD_FILE)] == [RECORD_FILE]

        agents.delete(agent_id)

        assert list(workspace.paperagents_dir.rglob(RECORD_FILE)) == []

    def test_the_record_is_kept_before_the_job_starts_and_not_if_the_job_cannot_be_started(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        agent_id = agent_of(agents)
        read_by(model_client, FIRST_CODE)
        stack.by_address[FIRST_CODE] = NOTHING
        go(onego, jobs, agent_id)
        before = kept_record(workspace, agent_id)
        other = jobs.start("something-else", agent_id, "Something else", lambda job: None)
        building_tests.finish(other)
        seen: list[dict[str, Any]] = []
        real = jobs.start

        def started(kind: str, *arguments: Any, **options: Any) -> Job:
            seen.append(kept_record(workspace, agent_id))
            return real(kind, *arguments, **options)

        monkeypatch.setattr(jobs, "start", started)
        go(onego, jobs, agent_id, go_on=True)
        assert seen[0]["state"] == "running" and seen[0]["settings"]["go_on"] == COMMIT

        def conflict(kind: str, *arguments: Any, **options: Any) -> Job:
            raise JobConflictError(other)

        after = kept_record(workspace, agent_id)
        monkeypatch.setattr(jobs, "start", conflict)

        assert why(onego.start, agent_id, 1, go_on=False) == (409, "busy")

        assert kept_record(workspace, agent_id) == after
        assert after != before

    def test_a_job_that_cannot_be_started_the_first_time_leaves_nothing_behind(
        self,
        onego: OneGo,
        agents: PaperAgents,
        jobs: Jobs,
        workspace: Workspace,
        stack: Remotes,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        agent_id = agent_of(agents)
        other = jobs.start("something-else", agent_id, "Something else", lambda job: None)
        building_tests.finish(other)

        def conflict(kind: str, *arguments: Any, **options: Any) -> Job:
            raise JobConflictError(other)

        monkeypatch.setattr(jobs, "start", conflict)

        assert why(onego.start, agent_id, 1) == (409, "busy")
        assert onego.view(agent_id)["state"] == "none"
        assert not (workspace.paperagents_dir / agent_id / RECORD_FILE).exists()


class TestTheApi:
    def make(self, client: TestClient, agent_id: str, **body: Any) -> Any:
        return client.post(f"/api/paperagents/{agent_id}/make", json=body)

    def test_an_agent_is_made_in_one_go_over_http_and_looked_at_and_forgotten(
        self, client: TestClient, stack: Remotes, model_client: FakeClient, papers: Papers
    ) -> None:
        created = client.post(
            "/api/paperagents", json={"title": "CellMapper", "paper": {"kind": "doi", "doi": DOI}, "repo": FIRST_CODE}
        )
        assert created.status_code == 201, created.text
        agent_id = created.json()["id"]
        url = f"/api/paperagents/{agent_id}/make"
        assert client.get(url).json()["state"] == "none"
        read_by(model_client, FIRST_CODE)

        started = client.post(url, json={"max_cost": 1})

        assert started.status_code == 202, started.text
        body = started.json()
        assert body["job"]["kind"] == ONEGO_JOB and body["job"]["subject"] == agent_id
        assert job_done(client, body["job"])["state"] == "succeeded"
        seen = client.get(url).json()
        assert seen["state"] == "done" and set(states(seen).values()) == {"done"} and seen["job"] is None
        listed = client.get(f"/api/paperagents/{agent_id}").json()
        assert listed["steps"]["tools"] == "done" and listed["given"] is True and listed["onego"] is None
        assert papers.asked == [DOI]

        cleared = client.delete(url)

        assert cleared.status_code == 200 and cleared.json()["state"] == "none"
        assert client.get(url).json()["state"] == "none"

    def test_what_is_asked_wrongly_is_refused(
        self, client: TestClient, stack: Remotes, model_client: FakeClient
    ) -> None:
        agent_id = client.post(
            "/api/paperagents", json={"title": "CellMapper", "paper": {"kind": "doi", "doi": DOI}, "repo": FIRST_CODE}
        ).json()["id"]
        url = f"/api/paperagents/{agent_id}/make"

        for bad in (
            {},
            {"max_cost": "a lot"},
            {"max_cost": -1},
            {"max_cost": 1, "give": "yes"},
            {"max_cost": 1, "without_code": 1},
            {"max_cost": 1, "go_on": "yes"},
            {"max_cost": 1, "other": 1},
            {"max_cost": 1, "repo": "x" * 5000},
            {"max_cost": 1, "ref": "x" * 500},
        ):
            assert client.post(url, json=bad).status_code == 422, bad
        assert client.post("/api/paperagents/nope/make", json={"max_cost": 1}).status_code == 404
        assert client.get("/api/paperagents/nope/make").status_code == 404
        assert client.delete("/api/paperagents/nope/make").status_code == 404
        gone = client.post(url, json={"max_cost": 1, "go_on": True})
        assert (gone.status_code, gone.json()["error"]["code"]) == (409, "no_code")
        assert stack.calls == [] and model_client.completions.parse_calls == []

    def test_it_says_where_the_person_is_to_say_something_over_http(
        self, client: TestClient, stack: Remotes, model_client: FakeClient
    ) -> None:
        stack.by_address[FIRST_CODE] = NOTHING
        agent_id = client.post(
            "/api/paperagents", json={"title": "CellMapper", "paper": {"kind": "doi", "doi": DOI}, "repo": FIRST_CODE}
        ).json()["id"]
        url = f"/api/paperagents/{agent_id}/make"

        body = client.post(url, json={"max_cost": 1}).json()
        job_done(client, body["job"])

        seen = client.get(url).json()
        assert (
            seen["state"] == "waiting" and seen["stuck"]["kind"] == "preflight" and seen["stuck"]["verdict"] == "no-go"
        )
        refused_while_going = client.delete(url)
        assert refused_while_going.status_code == 200

    def test_none_of_it_is_open_to_one_without_the_token(self, workspace: Workspace) -> None:
        app = create_app(workspace.root, token=TOKEN, check_keys=False, max_upload_bytes=100_000)
        with TestClient(app, base_url=LOCAL) as anyone:
            assert anyone.post("/api/paperagents/any/make", json={"max_cost": 1}).status_code == 401
            assert anyone.get("/api/paperagents/any/make").status_code == 401
            assert anyone.delete("/api/paperagents/any/make").status_code == 401
        with TestClient(app, base_url=LOCAL, headers=BEARER) as person:
            assert person.get("/api/paperagents/any/make").status_code == 404


def job_done(client: TestClient, job: dict[str, Any], seconds: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while (state := client.get(f"/api/setup/jobs/{job['id']}").json())["state"] in ("running", "stopping"):
        assert time.monotonic() < deadline, "the job did not finish"
        time.sleep(0.02)

    return dict(state)
