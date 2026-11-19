"""Tests of building the methods of a bake-off: that each method is given the PaperAgent of its paper and the steps of
one, in the order that costs least, what stands in the way of a method and is said so and kept, that the person is
asked where it is theirs to say and nothing the paper points to is taken for the code, that reading is paid for out of
the bake-off's one limit and out of nothing else, and that a build that was stopped or went wrong carries on from where
it was.

Git, Docker, the containers that tutorials and tools are run in, the services that give a paper's text, and the model
are replaced by stand-ins, as they are in the tests of the PaperAgents' steps, so that what the bake-off does is what is
looked at here, and what each step does is in the tests of that step."""

import json
import shutil
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import test_server_paperagent_environment as environment
import test_server_paperagent_reference as reference
import test_server_paperagent_tools as tools
from conftest import TEST_MODEL, FakeClient, make_usage, parsed_response
from fastapi.testclient import TestClient
from test_paperagents_reading import queue, reading
from test_paperagents_reference import failure_of, result_of
from test_paperagents_shortlisting import Services
from test_server_bakeoffs import (
    BEARER,
    DOI,
    LOCAL,
    OTHER_DOI,
    TASK,
    TOKEN,
    job_done,
    made,
    person_candidate,
    record_of,
    refused,
    rewrite,
    unit_cost,
    why,
)
from test_server_paperagent_environment import COMMIT, Docker
from test_server_paperagent_reference import NOTEBOOK, SCRIPT, Containers, writes
from test_server_paperagent_repository import Remote, project
from test_server_paperagent_tools import CALLS, MAPPING, Replays

from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import fetch as fetching
from virtual_lab.paperagents import repository as cloning
from virtual_lab.paperagents.anchors import document_from
from virtual_lab.paperagents.reading import ReadLicense, ReadLink, plan_chunks
from virtual_lab.server import bakeoff_building, imported_agents
from virtual_lab.server import paperagent_reading as kept_reading
from virtual_lab.server import paperagents as paperagents_module
from virtual_lab.server.app import create_app
from virtual_lab.server.bakeoffs import BUILD_JOB, Bakeoffs
from virtual_lab.server.errors import ApiError
from virtual_lab.server.jobs import Job, Jobs
from virtual_lab.server.paperagents import ENVIRONMENT_JOB, PaperAgents, steps_of
from virtual_lab.server.papers import money
from virtual_lab.server.workspace import Settings, Workspace
from virtual_lab.structured import StructuredOutputError
from virtual_lab.utils import compute_token_cost

# The stand-ins that a method is built with, which are fixtures of the modules that test the steps
docker = environment.docker
git_is_installed = environment.git_is_installed
marker = environment.marker
containers = reference.containers
replays = tools.replays

THIRD_DOI = "10.1000/third"
FIRST_CODE = "https://github.com/example/cellmapper"
SECOND_CODE = "https://github.com/example/labeller"
THIRD_CODE = "https://github.com/example/graphs"
OTHER_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"
SOURCE = {"kind": "europepmc", "label": "Europe PMC, PMC7000001", "url": "https://europepmc.org/article/PMC/PMC7000001"}


def paper_of(name: str, code: str | None) -> str:
    """What a paper says: what the method is, and, if it has any, where its code is and what it is licensed as."""
    words = f"{name} assigns a cell type to each cell of a single-nucleus RNA-seq sample."
    if code is None:
        return words

    return f"{words} The analysis code is at {code} and is released under the MIT license."


def answer_for(code: str | None) -> Any:
    """What a model that reads such a paper says of it: where its code is, and its license."""
    if code is None:
        return reading()

    return reading(
        links=[ReadLink(url=code, role="code", quote=f"The analysis code is at {code}")],
        licenses=[ReadLicense(name="MIT", covers="code", quote="is released under the MIT license")],
    )


class Papers:
    """Stands in for the services that give a paper's text: what each DOI is, and what was asked for."""

    def __init__(self) -> None:
        self.texts: dict[str, str] = {}
        self.asked: list[str] = []

    def europe_pmc_paper(self, doi: str) -> fetching.FetchedPaper:
        self.asked.append(doi)
        if doi not in self.texts:
            raise fetching.PaperUnavailableError(
                "Europe PMC does not give out the text of that paper. Upload its file."
            )

        return fetching.FetchedPaper(self.texts[doi], f"{doi.replace('/', '-')}.txt", SOURCE)


class Remotes(Remote):
    """Stands in for fetching code: what each address has in it, which is a project of files that none of it runs."""

    def __init__(self, files: dict[str, Any]) -> None:
        super().__init__(files)
        self.default = files
        self.by_address: dict[str, dict[str, Any]] = {}
        self.commit = COMMIT

    def __call__(self, url: str, destination: Path, ref: str | None = None, max_bytes: int = 0, **options: Any) -> Any:
        self.files = self.by_address.get(url, self.default)
        cloned = super().__call__(url, destination, ref, max_bytes, **options)

        return cloning.Cloned(self.commit, cloned.ref)

    def addresses(self) -> list[str]:
        return [each["url"] for each in self.calls]


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    """Looks at a step that is being done often, as it is done in a moment."""
    monkeypatch.setattr(bakeoff_building, "POLL_SECONDS", 0.002)


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    store = Workspace(tmp_path / "workspace")
    store.save_settings(Settings(model=TEST_MODEL, max_cost=None))

    return store


@pytest.fixture
def jobs() -> Iterator[Jobs]:
    kept_jobs = Jobs()
    yield kept_jobs
    kept_jobs.close()


@pytest.fixture
def agents(workspace: Workspace, jobs: Jobs) -> PaperAgents:
    return PaperAgents(workspace, 100_000, jobs, lambda model: [])


@pytest.fixture
def bakeoffs(agents: PaperAgents) -> Bakeoffs:
    return Bakeoffs(agents, Services({}, {}).search_articles, Services({}, {}).search_preprints)


@pytest.fixture
def model_client(fake_client: FakeClient) -> FakeClient:
    return fake_client


@pytest.fixture
def client(workspace: Workspace) -> Iterator[TestClient]:
    app = create_app(workspace.root, token=TOKEN, check_keys=False, max_upload_bytes=100_000)
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


@pytest.fixture
def papers(monkeypatch: pytest.MonkeyPatch) -> Papers:
    stand_in = Papers()
    monkeypatch.setattr(fetching, "europe_pmc_paper", stand_in.europe_pmc_paper)
    stand_in.texts = {
        DOI: paper_of("CellMapper", FIRST_CODE),
        OTHER_DOI: paper_of("Labeller", SECOND_CODE),
        THIRD_DOI: paper_of("GraphCells", None),
    }

    return stand_in


@pytest.fixture
def remotes(marker: Path, monkeypatch: pytest.MonkeyPatch) -> Remotes:
    files = {**project(marker), SCRIPT: "print(1)\n", "cellmapper/mapping.py": MAPPING}
    stand_in = Remotes(files)
    monkeypatch.setattr(cloning, "clone", stand_in)

    return stand_in


@pytest.fixture
def stack(remotes: Remotes, docker: Docker, containers: Containers, replays: Replays, papers: Papers) -> Remotes:
    """Everything that a method is built with: its code, Docker, the tutorials' and tools' containers, and its paper.
    The tutorials call two functions of the code, which tools are made of."""
    containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=CALLS))

    return remotes


def build(bakeoffs: Bakeoffs, bakeoff_id: str, *ids: str, go_on: list[str] | None = None) -> Job:
    return finish(bakeoffs.start_build(bakeoff_id, list(ids) or None, go_on))


def finish(job: Job, seconds: float = 30) -> Job:
    deadline = time.monotonic() + seconds
    while job.active:
        assert time.monotonic() < deadline, "the job did not finish"
        time.sleep(0.01)

    return job


def by_hand(agents: PaperAgents, agent_id: str, *steps: str) -> None:
    """Does steps to a PaperAgent as a person would from its page."""
    for step in steps:
        if step == "code":
            finish(agents.fetch_repository(agent_id))
        elif step == "environment":
            finish(agents.build_environment(agent_id))


def add(bakeoffs: Bakeoffs, bakeoff_id: str, doi: str = DOI, name: str | None = None, repo: str | None = None) -> str:
    return bakeoffs.add_candidate(bakeoff_id, {"kind": "doi", "doi": doi}, name, repo)


def read_by(model: FakeClient, *codes: str | None) -> None:
    """A model that says of each paper that is read, in turn, where its code is."""
    queue(model, *(answer_for(code) for code in codes))


CHUNK = 80


@pytest.fixture
def small_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Makes a paper be read in a few requests, so that a reading can end part of the way through."""
    monkeypatch.setattr(paperagents_module, "DEFAULT_PAPER_CHUNK_SIZE", CHUNK)
    monkeypatch.setattr(paperagents_module, "DEFAULT_PAPER_CHUNK_OVERLAP", 0)


def chunks_in(text: str) -> int:
    return len(plan_chunks(document_from([text], paged=False), CHUNK, 0))


def without(files: dict[str, Any], *names: str) -> dict[str, Any]:
    """A project's files, less some of them."""
    return {name: content for name, content in files.items() if name not in names}


def standing(bakeoffs: Bakeoffs, bakeoff_id: str, candidate_id: str) -> dict[str, Any]:
    return next(each for each in bakeoffs.view(bakeoff_id)["candidates"] if each["id"] == candidate_id)["standing"]


class TestBuildingAMethod:
    def test_a_method_whose_code_is_known_is_built_as_a_paperagent_by_the_steps_of_one(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        workspace: Workspace,
        stack: Remotes,
        papers: Papers,
        model_client: FakeClient,
    ) -> None:
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)

        job = build(bakeoffs, bakeoff_id)

        assert job.state == "succeeded", job.error
        assert job.kind == BUILD_JOB
        [agent] = agents.kept()
        assert agent[1]["title"] == "CellMapper" and agent[1]["repo"]["url"] == FIRST_CODE
        assert steps_of(agent[1]) == {
            "reading": "done",
            "repository": "done",
            "environment": "done",
            "data": "pending",
            "tools": "done",
        }
        assert standing(bakeoffs, bakeoff_id, method)["state"] == "built"
        assert record_of(workspace, bakeoff_id)["candidates"][0]["build"] is None
        assert record_of(workspace, bakeoff_id)["spent"] == pytest.approx(unit_cost())
        assert stack.addresses() == [FIRST_CODE]
        assert papers.asked == [DOI]

    def test_a_method_that_cannot_be_used_is_found_so_before_its_paper_is_read_and_costs_nothing(
        self, bakeoffs: Bakeoffs, workspace: Workspace, stack: Remotes, papers: Papers, model_client: FakeClient
    ) -> None:
        stack.by_address[SECOND_CODE] = {"README.md": "# Labeller\n\nNothing here but words.\n"}
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)

        job = build(bakeoffs, bakeoff_id)

        assert job.state == "succeeded"
        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("blocked", "preflight", "no_go")
        assert found["reason"].startswith("No-go: No code was found")
        assert model_client.completions.parse_calls == [] and papers.asked == []
        assert record_of(workspace, bakeoff_id)["spent"] == 0
        assert stack.addresses() == [SECOND_CODE]

    def test_methods_that_are_built_cannot_be_and_wait_for_the_person_are_each_said_so_with_why(
        self, bakeoffs: Bakeoffs, agents: PaperAgents, workspace: Workspace, stack: Remotes, model_client: FakeClient
    ) -> None:
        stack.by_address[SECOND_CODE] = {"README.md": "# Labeller\n\nNothing here but words.\n"}
        bakeoff_id = made(bakeoffs)
        first = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        second = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)
        third = add(bakeoffs, bakeoff_id, THIRD_DOI, "GraphCells")
        read_by(model_client, FIRST_CODE, None)

        job = build(bakeoffs, bakeoff_id)

        assert job.state == "succeeded"
        assert job.message == (
            "Built 1 of 3 methods. Waiting for you to say something: 1. Cannot be built here: 1. "
            f"{money(2 * unit_cost())} of the $1.0000 limit has been spent."
        )
        states = {each["id"]: each["standing"] for each in bakeoffs.view(bakeoff_id)["candidates"]}
        assert states[first]["state"] == "built"
        assert (states[second]["state"], states[second]["why"]) == ("blocked", "no_go")
        assert (states[third]["state"], states[third]["step"], states[third]["why"]) == ("waiting", "code", "no_code")
        assert "Say where it is" in states[third]["reason"]
        # Two papers were read, and the one whose code could not be used was not, and the one limit paid for both
        assert record_of(workspace, bakeoff_id)["spent"] == pytest.approx(2 * unit_cost())
        assert len(agents.kept()) == 3

    def test_what_the_paper_points_to_is_not_the_code_until_the_person_says_so(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        workspace: Workspace,
        stack: Remotes,
        papers: Papers,
        model_client: FakeClient,
    ) -> None:
        papers.texts[THIRD_DOI] = paper_of("GraphCells", THIRD_CODE)
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, THIRD_DOI, "GraphCells")
        read_by(model_client, THIRD_CODE)

        job = build(bakeoffs, bakeoff_id)

        assert job.state == "succeeded"
        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["why"]) == ("waiting", "choose_code")
        assert THIRD_CODE in found["reason"]
        assert stack.calls == []
        [(_, agent)] = agents.kept()
        assert agent["repo"] is None
        candidate = bakeoffs.view(bakeoff_id)["candidates"][0]
        assert candidate["repo"] is None and candidate["suggested"] == [THIRD_CODE]
        spent = record_of(workspace, bakeoff_id)["spent"]

        # They say which is the code, and what stood in the way is no longer, and the paper is not read again
        bakeoffs.change_candidate(bakeoff_id, method, repo=THIRD_CODE)
        assert standing(bakeoffs, bakeoff_id, method)["state"] == "new"
        assert build(bakeoffs, bakeoff_id).state == "succeeded"

        assert standing(bakeoffs, bakeoff_id, method)["state"] == "built"
        assert stack.addresses() == [THIRD_CODE]
        assert len(model_client.completions.parse_calls) == 1
        assert record_of(workspace, bakeoff_id)["spent"] == spent

    def test_what_the_abstract_pointed_to_is_kept_with_what_the_paper_does(
        self, bakeoffs: Bakeoffs, workspace: Workspace, stack: Remotes, papers: Papers, model_client: FakeClient
    ) -> None:
        papers.texts[THIRD_DOI] = paper_of("GraphCells", THIRD_CODE)
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, THIRD_DOI, "GraphCells")
        rewrite(workspace, bakeoff_id, lambda record: record["candidates"][0].update(suggested=[SECOND_CODE]))
        read_by(model_client, THIRD_CODE)

        build(bakeoffs, bakeoff_id)

        assert standing(bakeoffs, bakeoff_id, method)["why"] == "choose_code"
        assert bakeoffs.view(bakeoff_id)["candidates"][0]["suggested"] == [THIRD_CODE, SECOND_CODE]
        assert stack.calls == []


class TestWhatThePersonIsAskedAndSays:
    def test_code_with_things_to_weigh_is_not_gone_on_with_until_the_person_says_to(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        stack.by_address[FIRST_CODE] = without(stack.default, "LICENSE")
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)

        assert build(bakeoffs, bakeoff_id).state == "succeeded"

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("waiting", "preflight", "ask")
        assert found["reason"].startswith("Ask first.") and "license" in found["reason"]
        assert docker.builds == []
        assert record_of(workspace, bakeoff_id)["spent"] == pytest.approx(unit_cost())

        # Asked for again without saying, it is not gone on with, and the paper is not read again
        build(bakeoffs, bakeoff_id)
        assert standing(bakeoffs, bakeoff_id, method)["why"] == "ask"
        assert docker.builds == [] and len(model_client.completions.parse_calls) == 1

        # Said, it is, and nothing that was done is done again
        job = build(bakeoffs, bakeoff_id, go_on=[method])

        assert job.state == "succeeded" and standing(bakeoffs, bakeoff_id, method)["state"] == "built"
        assert len(docker.builds) == 1 and stack.addresses() == [FIRST_CODE]
        assert record_of(workspace, bakeoff_id)["spent"] == pytest.approx(unit_cost())
        assert record_of(workspace, bakeoff_id)["candidates"][0]["build"] is None

    def test_what_the_person_says_is_kept_with_the_commit_that_it_was_said_of_and_is_not_said_of_another(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        workspace: Workspace,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        stack.by_address[FIRST_CODE] = without(stack.default, "LICENSE", NOTEBOOK, SCRIPT)
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)
        build(bakeoffs, bakeoff_id)
        assert standing(bakeoffs, bakeoff_id, method)["why"] == "ask"

        build(bakeoffs, bakeoff_id, go_on=[method])

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("blocked", "tutorials", "no_tutorials")
        assert record_of(workspace, bakeoff_id)["candidates"][0]["build"]["go_on"] == COMMIT
        assert len(docker.builds) == 1

        # The code is fetched again, and it is of another commit, which they have not said to go on with
        [(directory, _)] = agents.kept()
        agents.clear_repository(directory.name)
        stack.commit = OTHER_COMMIT
        build(bakeoffs, bakeoff_id)

        assert standing(bakeoffs, bakeoff_id, method)["why"] == "ask"
        assert len(docker.builds) == 1
        build(bakeoffs, bakeoff_id, go_on=[method])
        assert record_of(workspace, bakeoff_id)["candidates"][0]["build"]["go_on"] == OTHER_COMMIT
        assert len(docker.builds) == 2
        assert len(model_client.completions.parse_calls) == 1

    def test_only_a_method_that_was_asked_about_can_be_said_to_go_on_with(
        self, bakeoffs: Bakeoffs, stack: Remotes, model_client: FakeClient
    ) -> None:
        stack.by_address[FIRST_CODE] = without(stack.default, "LICENSE")
        stack.by_address[SECOND_CODE] = {"README.md": "# Labeller\n\nNothing here but words.\n"}
        bakeoff_id = made(bakeoffs)
        asked = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        blocked = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)
        unsaid = add(bakeoffs, bakeoff_id, THIRD_DOI, "GraphCells")
        read_by(model_client, FIRST_CODE, None)

        # Not before it has been looked at
        assert why(bakeoffs.start_build, bakeoff_id, None, [asked]) == (409, "not_asking")

        build(bakeoffs, bakeoff_id)
        assert [standing(bakeoffs, bakeoff_id, each)["why"] for each in (asked, blocked, unsaid)] == [
            "ask",
            "no_go",
            "no_code",
        ]

        # Not if what stood in the way was another thing, nor one that is not being built now
        for other in (blocked, unsaid):
            assert why(bakeoffs.start_build, bakeoff_id, None, [other]) == (409, "not_asking")
        assert why(bakeoffs.start_build, bakeoff_id, [blocked], [asked]) == (409, "not_asking")
        assert bakeoffs.building(bakeoff_id) is None
        assert why(bakeoffs.start_build, bakeoff_id, None, ["00000000"]) == (404, "not_found")
        assert why(bakeoffs.start_build, bakeoff_id, ["00000000"]) == (404, "not_found")

    @pytest.mark.parametrize(
        "given", [{"candidates": "all"}, {"candidates": [7]}, {"candidates": ["a", "a"]}, {"go_on": "all"}]
    )
    def test_the_methods_are_given_as_a_list_of_ids_each_once(
        self, bakeoffs: Bakeoffs, stack: Remotes, given: dict[str, Any]
    ) -> None:
        bakeoff_id = made(bakeoffs)
        add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)

        assert why(bakeoffs.start_build, bakeoff_id, **given) == (422, "invalid")
        assert bakeoffs.building(bakeoff_id) is None and stack.calls == []

    def test_nothing_is_started_when_there_is_nothing_to_build_or_what_building_takes_is_not_there(
        self,
        bakeoffs: Bakeoffs,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        empty = made(bakeoffs)
        assert why(bakeoffs.start_build, empty) == (409, "nothing_to_build")
        assert why(bakeoffs.start_build, "00000000-none") == (404, "not_found")
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)

        docker.usable = (False, "Docker is not running. Start it and try again.")
        error = refused(bakeoffs.start_build, bakeoff_id)
        assert (error.status, error.code) == (422, "docker_missing") and "Start it" in error.message
        docker.usable = (True, None)
        real = shutil.which
        monkeypatch.setattr(
            shutil, "which", lambda name, *rest, **more: None if name == "git" else real(name, *rest, **more)
        )
        assert why(bakeoffs.start_build, bakeoff_id) == (422, "git_missing")
        monkeypatch.setattr(shutil, "which", real)
        assert bakeoffs.building(bakeoff_id) is None and stack.calls == []

        read_by(model_client, FIRST_CODE)
        build(bakeoffs, bakeoff_id)
        assert standing(bakeoffs, bakeoff_id, method)["state"] == "built"
        assert why(bakeoffs.start_build, bakeoff_id) == (409, "nothing_to_build")
        assert why(bakeoffs.start_build, bakeoff_id, [method]) == (409, "nothing_to_build")


class TestReadingIsPaidForOutOfTheOneLimit:
    def test_reading_is_given_what_is_left_and_what_it_spent_is_added_to_what_was_spent(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        workspace: Workspace,
        stack: Remotes,
        papers: Papers,
        model_client: FakeClient,
        small_chunks: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        given: list[float] = []
        real = agents.read

        def spy(agent_id: str, max_cost: Any, *rest: Any) -> Job:
            given.append(max_cost)

            return real(agent_id, max_cost, *rest)

        monkeypatch.setattr(agents, "read", spy)
        bakeoff_id = made(bakeoffs, limit=0.5)
        first = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        second = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)
        chunks = chunks_in(papers.texts[DOI]) + chunks_in(papers.texts[OTHER_DOI])
        read_by(model_client, *[None] * chunks)

        assert build(bakeoffs, bakeoff_id).state == "succeeded"

        spent = record_of(workspace, bakeoff_id)["spent"]
        assert chunks > 2 and len(model_client.completions.parse_calls) == chunks
        assert spent == pytest.approx(chunks * unit_cost())
        assert given == [pytest.approx(0.5), pytest.approx(0.5 - chunks_in(papers.texts[DOI]) * unit_cost())]
        assert [standing(bakeoffs, bakeoff_id, each)["state"] for each in (first, second)] == ["built", "built"]

    def test_a_paper_that_was_read_by_hand_is_not_read_again_nor_paid_for_by_the_bake_off(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        workspace: Workspace,
        stack: Remotes,
        papers: Papers,
        model_client: FakeClient,
    ) -> None:
        agent_id = agents.create("CellMapper", {"kind": "doi", "doi": DOI}, FIRST_CODE)
        read_by(model_client, FIRST_CODE)
        finish(agents.read(agent_id, 1))
        assert steps_of(agents.lookup(agent_id)[1])["reading"] == "done"
        bakeoff_id = made(bakeoffs, limit=0)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)

        job = build(bakeoffs, bakeoff_id)

        assert job.state == "succeeded" and standing(bakeoffs, bakeoff_id, method)["state"] == "built"
        assert len(model_client.completions.parse_calls) == 1 and papers.asked == [DOI]
        assert record_of(workspace, bakeoff_id)["spent"] == 0

    def test_a_reading_that_reaches_the_limit_keeps_what_was_spent_and_carries_on_when_it_is_raised(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
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
        each = compute_token_cost(TEST_MODEL, 1_000, 0)
        bakeoff_id = made(bakeoffs, limit=float(each) * 2.5)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        queue(model_client, *[reading()] * chunks, usage=make_usage(prompt_tokens=1_000, completion_tokens=0))

        job = build(bakeoffs, bakeoff_id)

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("pending", "paper", "limit")
        assert "limit on spending was reached" in found["reason"]
        done = len(model_client.completions.parse_calls)
        assert 0 < done < chunks
        record = record_of(workspace, bakeoff_id)
        assert record["spent"] == pytest.approx(done * float(each)) and record["cost_known"] is True
        assert "Not got to: 1." in job.message
        [(directory, agent)] = agents.kept()
        assert steps_of(agent)["reading"] == "pending" and steps_of(agent)["repository"] == "done"
        assert len(kept_reading.saved_chunks(directory)) == done
        assert why(bakeoffs.start_build, bakeoff_id) == (409, "limit")

        # With more to spend, what was read is not read again
        bakeoffs.change(bakeoff_id, limit=1)
        queue(model_client, *[reading()] * (chunks - done))
        assert build(bakeoffs, bakeoff_id).state == "succeeded"

        assert standing(bakeoffs, bakeoff_id, method)["state"] == "built"
        assert len(model_client.completions.parse_calls) == chunks
        assert record_of(workspace, bakeoff_id)["spent"] == pytest.approx(
            done * float(each) + (chunks - done) * unit_cost()
        )

    def test_a_response_that_does_not_say_what_it_used_makes_what_was_spent_not_known(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        stack: Remotes,
        model_client: FakeClient,
    ) -> None:
        bakeoff_id = made(bakeoffs)
        first = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        second = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)
        silent = parsed_response(answer_for(FIRST_CODE))
        silent.usage = None
        model_client.completions.parsed_responses = [silent]

        job = build(bakeoffs, bakeoff_id, first)

        assert job.state == "succeeded" and standing(bakeoffs, bakeoff_id, first)["state"] == "built"
        record = record_of(workspace, bakeoff_id)
        assert (record["spent"], record["cost_known"]) == (0, False)
        assert "an amount that cannot be worked out" not in job.message
        assert why(bakeoffs.start_build, bakeoff_id, [second]) == (409, "cost_unknown")
        assert len(model_client.completions.parse_calls) == 1

    def test_nothing_is_asked_of_a_model_when_nothing_is_left_and_a_method_that_needs_it_is_not_got_to(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        workspace: Workspace,
        stack: Remotes,
        papers: Papers,
        model_client: FakeClient,
    ) -> None:
        agent_id = agents.create("CellMapper", {"kind": "doi", "doi": DOI}, FIRST_CODE)
        read_by(model_client, FIRST_CODE)
        finish(agents.read(agent_id, 1))
        bakeoff_id = made(bakeoffs, limit=0)
        first = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        second = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)

        # Nothing to read paid for at all is refused, and one that is not read among those that are is not got to
        assert why(bakeoffs.start_build, bakeoff_id, [second]) == (409, "limit")
        job = build(bakeoffs, bakeoff_id)

        assert job.state == "succeeded"
        assert standing(bakeoffs, bakeoff_id, first)["state"] == "built"
        found = standing(bakeoffs, bakeoff_id, second)
        assert (found["state"], found["step"], found["why"]) == ("pending", "paper", "limit")
        assert papers.asked == [DOI] and len(model_client.completions.parse_calls) == 1

    def test_a_model_that_has_no_key_is_not_asked_and_a_method_that_needs_none_is_still_built(
        self,
        workspace: Workspace,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
    ) -> None:
        keyless_agents = PaperAgents(workspace, 100_000, jobs, lambda model: ["OPENAI_API_KEY"])
        keyless = Bakeoffs(keyless_agents)
        bakeoff_id = made(keyless)
        add(keyless, bakeoff_id, DOI, "CellMapper", FIRST_CODE)

        error = refused(keyless.start_build, bakeoff_id)

        assert (error.status, error.code) == (422, "missing_keys") and "OPENAI_API_KEY" in str(error)
        assert keyless.building(bakeoff_id) is None and model_client.completions.parse_calls == []
        assert stack.calls == []

    def test_a_paper_that_cannot_be_had_is_said_so_and_costs_nothing(
        self, bakeoffs: Bakeoffs, workspace: Workspace, stack: Remotes, papers: Papers, model_client: FakeClient
    ) -> None:
        papers.texts.pop(DOI)
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)

        build(bakeoffs, bakeoff_id)

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("failed", "paper", "no_paper")
        assert "Europe PMC does not give out the text of that paper" in found["reason"]
        assert record_of(workspace, bakeoff_id)["spent"] == 0 and model_client.completions.parse_calls == []

    def test_a_reading_that_went_wrong_after_some_of_the_paper_was_read_is_paid_for_as_far_as_it_got(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        stack: Remotes,
        papers: Papers,
        model_client: FakeClient,
        small_chunks: None,
    ) -> None:
        papers.texts[DOI] += "\n\n" + "\n\n".join(f"Paragraph {number} of the paper." for number in range(6))
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        queue(model_client, reading(), RuntimeError("The model's server went away"))

        job = build(bakeoffs, bakeoff_id)

        assert job.state == "succeeded"
        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("failed", "paper", "failed")
        assert "The model's server went away" in found["reason"]
        assert record_of(workspace, bakeoff_id)["spent"] == pytest.approx(unit_cost())

    def test_a_step_that_ended_without_doing_what_it_is_for_is_said_to_be_so(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def idle(agent_id: str, *arguments: Any, **options: Any) -> Job:
            return jobs.start(
                "idle", agent_id, "Doing nothing", lambda job: "It did nothing.", exclusive=f"idle:{agent_id}"
            )

        monkeypatch.setattr(agents, "build_environment", idle)
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)
        build(bakeoffs, bakeoff_id)

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"], found["reason"]) == (
            "failed",
            "environment",
            "failed",
            "It did nothing.",
        )

    def test_tools_that_were_not_made_by_a_step_that_ended_are_blocked_and_say_what_it_said(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def idle(agent_id: str, *arguments: Any, **options: Any) -> Job:
            return jobs.start(
                "idle", agent_id, "Doing nothing", lambda job: "No tool was made.", exclusive=f"idle:{agent_id}"
            )

        monkeypatch.setattr(agents, "start_tools", idle)
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)
        build(bakeoffs, bakeoff_id)

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"], found["reason"]) == (
            "blocked",
            "tools",
            "no_tools",
            "No tool was made.",
        )

    def test_a_paper_that_could_not_be_read_is_said_so_and_what_the_request_used_is_paid_for(
        self, bakeoffs: Bakeoffs, workspace: Workspace, stack: Remotes, model_client: FakeClient
    ) -> None:
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        queue(model_client, StructuredOutputError("The model refused to produce ChunkReading: No.", usage=make_usage()))

        build(bakeoffs, bakeoff_id)

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("failed", "paper", "failed")
        assert record_of(workspace, bakeoff_id)["spent"] == pytest.approx(unit_cost())


class TestGivenThePaperAgentOfThePaper:
    def test_what_was_done_by_hand_to_its_paperagent_is_not_done_again(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        stack: Remotes,
        docker: Docker,
        papers: Papers,
        model_client: FakeClient,
    ) -> None:
        agent_id = agents.create("Made by hand", {"kind": "doi", "doi": DOI}, FIRST_CODE)
        by_hand(agents, agent_id, "code", "environment")
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper")

        job = build(bakeoffs, bakeoff_id)

        assert job.state == "succeeded" and standing(bakeoffs, bakeoff_id, method)["state"] == "built"
        assert [each[1]["title"] for each in agents.kept()] == ["Made by hand"]
        assert stack.addresses() == [FIRST_CODE] and len(docker.builds) == 1
        assert papers.asked == [] and model_client.completions.parse_calls == []

    def test_a_paperagent_whose_code_is_said_to_be_elsewhere_waits_for_the_person_to_say_which(
        self, bakeoffs: Bakeoffs, agents: PaperAgents, workspace: Workspace, stack: Remotes, model_client: FakeClient
    ) -> None:
        agent_id = agents.create("Made by hand", {"kind": "doi", "doi": DOI}, SECOND_CODE)
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)

        build(bakeoffs, bakeoff_id)

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("waiting", "code", "code_differs")
        assert FIRST_CODE in found["reason"] and SECOND_CODE in found["reason"]
        assert stack.calls == [] and model_client.completions.parse_calls == []

        # They say it on the PaperAgent, and it is built, from the code that both now say
        agents.change(agent_id, repo=FIRST_CODE)
        read_by(model_client, FIRST_CODE)
        build(bakeoffs, bakeoff_id)
        assert standing(bakeoffs, bakeoff_id, method)["state"] == "built"
        assert stack.addresses() == [FIRST_CODE]

    def test_a_method_with_no_code_given_is_built_from_the_code_that_its_paperagent_has(
        self, bakeoffs: Bakeoffs, agents: PaperAgents, stack: Remotes, model_client: FakeClient
    ) -> None:
        agents.create("Made by hand", {"kind": "doi", "doi": DOI}, SECOND_CODE)
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper")
        read_by(model_client, None)

        build(bakeoffs, bakeoff_id)

        assert standing(bakeoffs, bakeoff_id, method)["state"] == "built"
        assert stack.addresses() == [SECOND_CODE]

    def test_a_paperagent_that_was_imported_is_blocked_and_nothing_is_done_to_it(
        self, bakeoffs: Bakeoffs, agents: PaperAgents, stack: Remotes, model_client: FakeClient
    ) -> None:
        hosted = imported_agents.record_of("https://mcp.example.org/mcp", [])
        agent_id = agents.create("Hosted elsewhere", {"kind": "doi", "doi": DOI}, None, imported=hosted)
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)

        build(bakeoffs, bakeoff_id)

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("blocked", "agent", "imported")
        assert "Hosted elsewhere" in found["reason"] and "hosted by another server" in found["reason"]
        assert stack.calls == [] and model_client.completions.parse_calls == []
        assert [each[0].name for each in agents.kept()] == [agent_id]

    def test_one_that_is_made_in_the_meantime_is_the_one_that_is_built_and_what_cannot_be_made_is_said(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        stack: Remotes,
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bakeoff_id = made(bakeoffs)
        raced = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        crowded = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)
        awkward = add(bakeoffs, bakeoff_id, THIRD_DOI, "GraphCells", THIRD_CODE)
        real = agents.create
        titles: list[str] = []

        def create(title: Any, paper: dict[str, Any], repo: Any = None, **options: Any) -> str:
            titles.append(title)
            if paper["doi"] == DOI:
                # Another made it between the look for one and this
                other = real("Made meanwhile", paper, repo)
                raise ApiError(409, "exists", "There is a PaperAgent of that paper", existing=other)
            if paper["doi"] == OTHER_DOI:
                raise ApiError(409, "too_many", "No more than 200 PaperAgents can be kept. Delete some first")
            if title == "GraphCells":
                raise ApiError(422, "invalid", "That is not a name")

            return real(title, paper, repo, **options)

        monkeypatch.setattr(agents, "create", create)
        read_by(model_client, FIRST_CODE, None, THIRD_CODE)

        build(bakeoffs, bakeoff_id)

        assert standing(bakeoffs, bakeoff_id, raced)["state"] == "built"
        found = standing(bakeoffs, bakeoff_id, crowded)
        assert (found["state"], found["step"], found["why"]) == ("blocked", "agent", "too_many")
        assert "No more than 200" in found["reason"]
        # A name that is refused is replaced by what a PaperAgent of that paper is called when it is not named
        assert standing(bakeoffs, bakeoff_id, awkward)["state"] == "built"
        assert titles == ["CellMapper", "Labeller", "GraphCells", THIRD_DOI]
        assert sorted(each[1]["title"] for each in agents.kept()) == sorted(["Made meanwhile", THIRD_DOI])

    def test_a_paperagent_that_cannot_be_made_is_a_failure_that_may_not_be_the_next_time(
        self, bakeoffs: Bakeoffs, agents: PaperAgents, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)

        def refuse(*arguments: Any, **options: Any) -> str:
            raise ApiError(500, "disk", "The disk is full")

        monkeypatch.setattr(agents, "create", refuse)

        build(bakeoffs, bakeoff_id)

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"], found["reason"]) == (
            "failed",
            "agent",
            "refused",
            "The disk is full",
        )


class TestWhenAStepDoesNotGoWell:
    def test_a_method_whose_environment_fails_is_said_so_and_the_next_is_built_and_it_is_asked_for_again(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        workspace: Workspace,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bakeoff_id = made(bakeoffs)
        first = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        second = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)
        read_by(model_client, FIRST_CODE, SECOND_CODE)
        asked: list[int] = []
        failure = building.EnvironmentBuildError(
            building.classify("Collecting x\nfatal error: zlib.h: No such file or directory", "project", 1)
        )

        def flaky(*arguments: Any, **options: Any) -> Any:
            asked.append(1)
            if len(asked) == 1:
                raise failure

            return docker.build(*arguments, **options)

        monkeypatch.setattr(building, "build_environment", flaky)

        job = build(bakeoffs, bakeoff_id)

        assert job.state == "succeeded" and job.message.startswith("Built 1 of 2 methods. Went wrong")
        found = standing(bakeoffs, bakeoff_id, first)
        assert (found["state"], found["step"], found["why"]) == ("failed", "environment", "failed")
        assert found["reason"].startswith("A system library is missing.")
        assert standing(bakeoffs, bakeoff_id, second)["state"] == "built"
        spent = record_of(workspace, bakeoff_id)["spent"]

        # Asked for again, it is built, and neither the paper nor the code is got again
        assert build(bakeoffs, bakeoff_id).state == "succeeded"

        assert standing(bakeoffs, bakeoff_id, first)["state"] == "built"
        assert stack.addresses() == [FIRST_CODE, SECOND_CODE] and len(model_client.completions.parse_calls) == 2
        assert record_of(workspace, bakeoff_id)["spent"] == spent

    def test_code_with_no_tutorials_is_blocked_once_the_person_has_gone_on_with_it(
        self, bakeoffs: Bakeoffs, stack: Remotes, containers: Containers, model_client: FakeClient
    ) -> None:
        stack.by_address[FIRST_CODE] = without(stack.default, NOTEBOOK, SCRIPT)
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)
        build(bakeoffs, bakeoff_id)
        assert standing(bakeoffs, bakeoff_id, method)["why"] == "ask"

        build(bakeoffs, bakeoff_id, go_on=[method])

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("blocked", "tutorials", "no_tutorials")
        assert containers.runs == []

    def test_code_that_has_no_environment_to_build_is_blocked(
        self, bakeoffs: Bakeoffs, stack: Remotes, docker: Docker, model_client: FakeClient
    ) -> None:
        stack.by_address[FIRST_CODE] = without(stack.default, "environment.yml", "setup.py")
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)
        build(bakeoffs, bakeoff_id)

        build(bakeoffs, bakeoff_id, go_on=[method])

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("blocked", "environment", "unsupported")
        assert docker.builds == []

    def test_tutorials_that_called_nothing_to_make_a_tool_of_are_blocked_and_say_why(
        self, bakeoffs: Bakeoffs, stack: Remotes, containers: Containers, replays: Replays, model_client: FakeClient
    ) -> None:
        broken = writes(result_of(ok=False, error=failure_of("ValueError"), calls=CALLS))
        containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = broken
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)

        build(bakeoffs, bakeoff_id)

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("blocked", "tools", "no_tools")
        assert "None of the tutorials that ran to their end called a function of the code." in found["reason"]
        assert replays.runs == []

    def test_something_that_was_not_expected_to_go_wrong_is_a_failure_at_the_step_that_it_was_at(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        stack: Remotes,
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def explode(*arguments: Any, **options: Any) -> Job:
            raise RuntimeError("Docker went away")

        monkeypatch.setattr(agents, "build_environment", explode)
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)

        job = build(bakeoffs, bakeoff_id)

        assert job.state == "succeeded"
        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("failed", "environment", "error")
        assert found["reason"] == "RuntimeError: Docker went away"

    def test_a_reason_is_kept_on_one_line_and_is_no_longer_than_it_may_be(
        self, bakeoffs: Bakeoffs, workspace: Workspace, agents: PaperAgents, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(*arguments: Any, **options: Any) -> str:
            raise ApiError(500, "disk", "The disk\x00 is\nfull. " * 200)

        monkeypatch.setattr(agents, "create", refuse)
        bakeoff_id = made(bakeoffs)
        add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)

        build(bakeoffs, bakeoff_id)

        reason = record_of(workspace, bakeoff_id)["candidates"][0]["build"]["reason"]
        assert reason.startswith("The disk is full. The disk is full.") and len(reason) == 600
        assert "\n" not in reason and "\x00" not in reason


def hold(docker: Docker) -> threading.Event:
    """Makes the next environment that is built wait to be let go on, which is set to let each go."""
    gate = threading.Event()
    docker.gate = gate
    docker.started.clear()

    return gate


def wait_until(condition: Any, seconds: float = 20) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "it did not come to be"
        time.sleep(0.01)


class TestStoppingAndCarryingOn:
    def test_a_build_that_is_stopped_keeps_what_was_done_and_building_again_carries_on_from_there(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        workspace: Workspace,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)
        gate = hold(docker)
        job = bakeoffs.start_build(bakeoff_id)
        assert docker.started.wait(10)
        building = standing(bakeoffs, bakeoff_id, method)
        assert (building["state"], building["step"]) == ("building", "environment")

        job.request_stop()
        finish(job)

        assert job.state == "stopped"
        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("pending", "environment", "stopped")
        [(directory, agent)] = agents.kept()
        assert [steps_of(agent)[step] for step in ("reading", "repository", "environment")] == [
            "done",
            "done",
            "pending",
        ]
        spent = record_of(workspace, bakeoff_id)["spent"]
        assert spent == pytest.approx(unit_cost())

        gate.set()
        assert build(bakeoffs, bakeoff_id).state == "succeeded"

        assert standing(bakeoffs, bakeoff_id, method)["state"] == "built"
        assert len(model_client.completions.parse_calls) == 1 and stack.addresses() == [FIRST_CODE]
        assert record_of(workspace, bakeoff_id)["spent"] == spent

    def test_what_was_built_before_the_stop_stays_built_and_the_methods_after_it_are_not_got_to(
        self, bakeoffs: Bakeoffs, stack: Remotes, docker: Docker, model_client: FakeClient
    ) -> None:
        bakeoff_id = made(bakeoffs)
        first = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        second = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)
        third = add(bakeoffs, bakeoff_id, THIRD_DOI, "GraphCells", THIRD_CODE)
        read_by(model_client, FIRST_CODE, SECOND_CODE, THIRD_CODE)
        gate = threading.Event()

        def hold_the_second() -> None:
            docker.started.clear()
            docker.gate = gate

        docker.during = hold_the_second
        job = bakeoffs.start_build(bakeoff_id)
        wait_until(lambda: len(docker.builds) == 2)
        job.request_stop()
        finish(job)

        assert job.state == "stopped"
        states = [standing(bakeoffs, bakeoff_id, each) for each in (first, second, third)]
        assert [each["state"] for each in states] == ["built", "pending", "new"]
        assert states[1]["why"] == "stopped" and stack.addresses() == [FIRST_CODE, SECOND_CODE]

        docker.during = None
        gate.set()
        assert build(bakeoffs, bakeoff_id).state == "succeeded"

        assert [standing(bakeoffs, bakeoff_id, each)["state"] for each in (first, second, third)] == ["built"] * 3
        assert len(docker.builds) == 4 and len(model_client.completions.parse_calls) == 3

    def test_a_step_that_someone_else_stopped_is_a_method_not_got_to_and_the_next_is_built(
        self,
        bakeoffs: Bakeoffs,
        jobs: Jobs,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        bakeoff_id = made(bakeoffs)
        first = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        second = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)
        read_by(model_client, FIRST_CODE, SECOND_CODE)
        gate = hold(docker)
        job = bakeoffs.start_build(bakeoff_id)
        assert docker.started.wait(10)

        [child] = jobs.active(ENVIRONMENT_JOB)
        child.request_stop()
        finish(child)
        gate.set()
        finish(job)

        assert job.state == "succeeded" and "Not got to: 1." in job.message
        found = standing(bakeoffs, bakeoff_id, first)
        assert (found["state"], found["step"], found["why"]) == ("pending", "environment", "stopped")
        assert standing(bakeoffs, bakeoff_id, second)["state"] == "built"

    def test_stopping_while_the_code_is_fetched_stops_the_fetching_too(
        self, bakeoffs: Bakeoffs, agents: PaperAgents, stack: Remotes, model_client: FakeClient
    ) -> None:
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        stack.gate = threading.Event()
        job = bakeoffs.start_build(bakeoff_id)
        assert stack.started.wait(10)

        job.request_stop()
        finish(job)

        assert job.state == "stopped"
        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("pending", "code", "stopped")
        assert steps_of(agents.kept()[0][1])["repository"] != "done" and model_client.completions.parse_calls == []


class TestWhileMethodsAreBuilt:
    def test_nothing_else_is_started_or_changed_in_the_bake_off_until_it_ends(
        self, bakeoffs: Bakeoffs, stack: Remotes, docker: Docker, model_client: FakeClient
    ) -> None:
        bakeoff_id = made(bakeoffs)
        add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)
        gate = hold(docker)
        job = bakeoffs.start_build(bakeoff_id)
        assert docker.started.wait(10)

        assert why(bakeoffs.start_build, bakeoff_id) == (409, "busy")
        assert why(bakeoffs.start_shortlist, bakeoff_id) == (409, "busy")
        assert why(bakeoffs.change, bakeoff_id, title="Another") == (409, "busy")
        assert why(bakeoffs.delete, bakeoff_id) == (409, "busy")
        added = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)
        assert bakeoffs.building(bakeoff_id) is job and bakeoffs.running(bakeoff_id) is job
        listed = bakeoffs.describe()["bakeoffs"][0]["job"]
        assert listed["kind"] == BUILD_JOB and listed["progress"]["step"] == "environment"
        assert bakeoffs.view(bakeoff_id)["job"]["id"] == job.id

        gate.set()
        finish(job)
        assert bakeoffs.building(bakeoff_id) is None and bakeoffs.view(bakeoff_id)["job"] is None
        # A method put in the running meanwhile is not one that the build was asked to do
        assert standing(bakeoffs, bakeoff_id, added)["state"] == "new" and stack.addresses() == [FIRST_CODE]

    def test_a_step_that_a_person_started_on_the_paperagent_is_waited_for_and_not_done_twice(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        agent_id = agents.create("Made by hand", {"kind": "doi", "doi": DOI}, FIRST_CODE)
        by_hand(agents, agent_id, "code")
        gate = hold(docker)
        hand = agents.build_environment(agent_id)
        assert docker.started.wait(10)
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper")
        read_by(model_client, None)

        job = bakeoffs.start_build(bakeoff_id)
        wait_until(lambda: "Waiting for" in str(job.snapshot()["progress"].get("detail")))
        assert job.active and hand.active

        gate.set()
        finish(job)

        assert job.state == "succeeded" and standing(bakeoffs, bakeoff_id, method)["state"] == "built"
        assert len(docker.builds) == 1

    def test_a_step_that_stays_in_the_way_is_waited_for_a_few_times_and_then_said_to_be_so(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        jobs: Jobs,
        stack: Remotes,
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        other = jobs.start("something-else", "x", "Something else", lambda job: None, exclusive="paperagent:x")
        finish(other)
        asked: list[int] = []

        def busy(agent_id: str, *arguments: Any, **options: Any) -> Job:
            asked.append(1)
            raise ApiError(409, "busy", "Something else is already running", job=other.snapshot())

        monkeypatch.setattr(agents, "build_environment", busy)
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)

        build(bakeoffs, bakeoff_id)

        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["step"], found["why"]) == ("failed", "environment", "refused")
        assert found["reason"] == "Something else is already running"
        assert len(asked) == bakeoff_building.MOST_WAITS + 1

    def test_a_method_that_is_taken_out_of_the_running_is_not_gone_on_with_and_nothing_is_kept_of_it(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        workspace: Workspace,
        stack: Remotes,
        docker: Docker,
        containers: Containers,
        model_client: FakeClient,
    ) -> None:
        bakeoff_id = made(bakeoffs)
        first = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        second = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)
        read_by(model_client, FIRST_CODE, SECOND_CODE)
        gate = hold(docker)
        job = bakeoffs.start_build(bakeoff_id)
        assert docker.started.wait(10)

        bakeoffs.remove_candidate(bakeoff_id, first)
        gate.set()
        finish(job)

        assert job.state == "succeeded" and job.message.startswith("Built 1 of 1 methods.")
        assert [each["id"] for each in record_of(workspace, bakeoff_id)["candidates"]] == [second]
        assert standing(bakeoffs, bakeoff_id, second)["state"] == "built"
        # Its environment was being built, which ended, and its tutorials were not run
        assert len(docker.builds) == 2 and {run["label"] for run in containers.runs} == {"labeller"}
        assert len(agents.kept()) == 2

    def test_a_method_whose_code_was_said_to_be_elsewhere_in_the_meantime_has_nothing_kept_of_the_old_code(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        workspace: Workspace,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)
        gate = hold(docker)
        job = bakeoffs.start_build(bakeoff_id)
        assert docker.started.wait(10)

        bakeoffs.change_candidate(bakeoff_id, method, repo=SECOND_CODE)
        docker.error = RuntimeError("Docker could not make the container: no space left on device")
        gate.set()
        finish(job)

        assert job.state == "succeeded"
        assert record_of(workspace, bakeoff_id)["candidates"][0]["build"] is None
        assert standing(bakeoffs, bakeoff_id, method)["state"] == "new"

    def test_a_method_built_from_other_code_than_is_now_said_is_not_built_and_the_person_is_asked_which(
        self,
        bakeoffs: Bakeoffs,
        agents: PaperAgents,
        stack: Remotes,
        docker: Docker,
        model_client: FakeClient,
    ) -> None:
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        read_by(model_client, FIRST_CODE)
        build(bakeoffs, bakeoff_id)
        assert standing(bakeoffs, bakeoff_id, method)["state"] == "built"

        bakeoffs.change_candidate(bakeoff_id, method, repo=SECOND_CODE)

        assert standing(bakeoffs, bakeoff_id, method)["state"] == "new"
        assert build(bakeoffs, bakeoff_id).state == "succeeded"
        found = standing(bakeoffs, bakeoff_id, method)
        assert (found["state"], found["why"]) == ("waiting", "code_differs")
        assert stack.addresses() == [FIRST_CODE]
        bakeoffs.change_candidate(bakeoff_id, method, repo=FIRST_CODE)
        assert standing(bakeoffs, bakeoff_id, method)["state"] == "built"
        bakeoffs.change_candidate(bakeoff_id, method, repo="")
        assert standing(bakeoffs, bakeoff_id, method)["state"] == "built"


VALID = {
    "state": "waiting",
    "step": "code",
    "why": "no_code",
    "reason": "No address of the code was given.",
    "at": "2024-01-01T00:00:00Z",
    "go_on": None,
}


class TestWhatIsKeptOfBuilding:
    def test_what_stands_in_the_way_of_a_method_is_kept_for_the_next_time_it_is_looked_at(
        self, bakeoffs: Bakeoffs, workspace: Workspace
    ) -> None:
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper")
        rewrite(workspace, bakeoff_id, lambda record: record["candidates"][0].update(build=VALID))

        assert len(bakeoffs.kept()) == 1
        found = standing(bakeoffs, bakeoff_id, method)
        assert found == {key: VALID[key] for key in ("state", "step", "why", "reason", "at")}
        assert json.dumps(bakeoffs.view(bakeoff_id))

    @pytest.mark.parametrize(
        "damage",
        [
            {"state": "stuck"},
            {"state": "built"},
            {"state": None},
            {"step": "nowhere"},
            {"why": "Has Space"},
            {"why": ""},
            {"why": "x" * 31},
            {"reason": ""},
            {"reason": "x" * 601},
            {"reason": "one\x1b[31mred"},
            {"at": "now\x00"},
            {"go_on": "not-a-commit"},
            {"go_on": "ABCDEF1"},
            {"go_on": 7},
        ],
        ids=range(14),
    )
    def test_what_is_kept_of_what_stands_in_the_way_is_in_the_shape_that_it_is_kept_in_or_the_file_is_not_used(
        self, bakeoffs: Bakeoffs, workspace: Workspace, damage: dict[str, Any]
    ) -> None:
        bakeoff_id = made(bakeoffs)
        add(bakeoffs, bakeoff_id, DOI, "CellMapper")

        rewrite(workspace, bakeoff_id, lambda record: record["candidates"][0].update(build={**VALID, **damage}))

        assert bakeoffs.kept() == []

    def test_a_build_with_a_key_missing_or_that_is_not_a_record_is_not_used(
        self, bakeoffs: Bakeoffs, workspace: Workspace
    ) -> None:
        bakeoff_id = made(bakeoffs)
        add(bakeoffs, bakeoff_id, DOI, "CellMapper")
        for build_of in ({key: value for key, value in VALID.items() if key != "go_on"}, "waiting", [VALID], 3):
            rewrite(workspace, bakeoff_id, lambda record, each=build_of: record["candidates"][0].update(build=each))
            assert bakeoffs.kept() == []

    def test_a_commit_that_the_person_went_on_with_is_kept_as_it_was_said(
        self, bakeoffs: Bakeoffs, workspace: Workspace
    ) -> None:
        bakeoff_id = made(bakeoffs)
        add(bakeoffs, bakeoff_id, DOI, "CellMapper")

        rewrite(
            workspace,
            bakeoff_id,
            lambda record: record["candidates"][0].update(build={**VALID, "go_on": COMMIT, "why": "ask"}),
        )

        assert len(bakeoffs.kept()) == 1

    def test_a_bake_off_that_was_kept_before_methods_were_built_is_read_as_one_whose_methods_were_not(
        self, bakeoffs: Bakeoffs, workspace: Workspace
    ) -> None:
        bakeoff_id = made(bakeoffs)
        add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)

        def earlier(record: dict[str, Any]) -> None:
            record["schema"] = 1
            for candidate in record["candidates"]:
                del candidate["build"]

        rewrite(workspace, bakeoff_id, earlier)

        [(_, loaded)] = bakeoffs.kept()
        assert loaded["schema"] == 2 and [each["build"] for each in loaded["candidates"]] == [None]
        bakeoffs.change(bakeoff_id, title="Changed")
        assert record_of(workspace, bakeoff_id)["schema"] == 2

    def test_a_file_of_the_earlier_kind_that_is_damaged_is_still_not_used(
        self, bakeoffs: Bakeoffs, workspace: Workspace
    ) -> None:
        bakeoff_id = made(bakeoffs)
        rewrite(workspace, bakeoff_id, lambda record: record.update(schema=1, candidates="none"))

        assert bakeoffs.kept() == []

    def test_saying_where_the_code_is_takes_away_what_stood_in_the_way_of_the_code_that_there_was(
        self, bakeoffs: Bakeoffs, workspace: Workspace
    ) -> None:
        bakeoff_id = made(bakeoffs)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
        rewrite(workspace, bakeoff_id, lambda record: record["candidates"][0].update(build={**VALID, "why": "ask"}))

        bakeoffs.change_candidate(bakeoff_id, method, name="Renamed")
        assert standing(bakeoffs, bakeoff_id, method)["why"] == "ask"
        bakeoffs.change_candidate(bakeoff_id, method, repo=FIRST_CODE)
        assert standing(bakeoffs, bakeoff_id, method)["why"] == "ask"
        bakeoffs.change_candidate(bakeoff_id, method, repo=SECOND_CODE)

        assert standing(bakeoffs, bakeoff_id, method)["state"] == "new"
        assert record_of(workspace, bakeoff_id)["candidates"][0]["build"] is None

    def test_a_candidate_that_has_what_was_kept_of_a_search_and_of_building_is_seen_with_both(
        self, bakeoffs: Bakeoffs, workspace: Workspace
    ) -> None:
        bakeoff_id = made(bakeoffs)
        rewrite(
            workspace,
            bakeoff_id,
            lambda record: record["candidates"].append({**person_candidate(DOI), "build": VALID}),
        )

        [seen] = bakeoffs.view(bakeoff_id)["candidates"]

        assert seen["build"] == VALID and seen["standing"]["why"] == "no_code" and seen["agent"] is None


class TestTheApiOfBuilding:
    def test_methods_are_built_as_a_job_that_is_followed_like_the_others_and_each_is_said_where_it_stands(
        self, client: TestClient, stack: Remotes, model_client: FakeClient
    ) -> None:
        stack.by_address[SECOND_CODE] = {"README.md": "# Labeller\n\nNothing here but words.\n"}
        bakeoff_id = client.post("/api/bakeoffs", json={"task": TASK, "limit": 1}).json()["id"]
        for doi, name, repo in (
            (DOI, "CellMapper", FIRST_CODE),
            (OTHER_DOI, "Labeller", SECOND_CODE),
            (THIRD_DOI, "GraphCells", None),
        ):
            body = {"paper": {"kind": "doi", "doi": doi}, "name": name, **({"repo": repo} if repo else {})}
            assert client.post(f"/api/bakeoffs/{bakeoff_id}/candidates", json=body).status_code == 201
        read_by(model_client, FIRST_CODE, None)

        started = client.post(f"/api/bakeoffs/{bakeoff_id}/build", json={})

        assert started.status_code == 202
        job = started.json()
        assert (job["kind"], job["subject"]) == (BUILD_JOB, bakeoff_id)
        assert job_done(client, job)["state"] == "succeeded"
        seen = client.get(f"/api/bakeoffs/{bakeoff_id}").json()
        standings = {each["name"]: each["standing"] for each in seen["candidates"]}
        assert standings["CellMapper"]["state"] == "built"
        assert (standings["Labeller"]["state"], standings["Labeller"]["why"]) == ("blocked", "no_go")
        assert (standings["GraphCells"]["state"], standings["GraphCells"]["why"]) == ("waiting", "no_code")
        assert seen["spent"] == pytest.approx(2 * unit_cost()) and seen["job"] is None
        agent = next(each for each in seen["candidates"] if each["name"] == "CellMapper")["agent"]
        assert agent["steps"]["tools"] == "done" and agent["repo"] == FIRST_CODE

    def test_what_is_asked_wrongly_is_refused_and_nothing_is_started(
        self, client: TestClient, stack: Remotes, model_client: FakeClient
    ) -> None:
        bakeoff_id = client.post("/api/bakeoffs", json={"task": TASK, "limit": 1}).json()["id"]
        body = {"paper": {"kind": "doi", "doi": DOI}, "name": "CellMapper", "repo": FIRST_CODE}
        method = client.post(f"/api/bakeoffs/{bakeoff_id}/candidates", json=body).json()["candidates"][0]["id"]
        url = f"/api/bakeoffs/{bakeoff_id}/build"

        for bad in (
            {"candidates": "all"},
            {"candidates": [3]},
            {"go_on": "yes"},
            {"other": 1},
            {"candidates": ["x"] * 40},
        ):
            assert client.post(url, json=bad).status_code == 422, bad
        assert client.post("/api/bakeoffs/nope/build", json={}).status_code == 404
        assert client.post(url, json={"candidates": ["00000000"]}).status_code == 404
        refused_to_go_on = client.post(url, json={"go_on": [method]})
        assert (refused_to_go_on.status_code, refused_to_go_on.json()["error"]["code"]) == (409, "not_asking")
        assert stack.calls == [] and model_client.completions.parse_calls == []

        read_by(model_client, FIRST_CODE)
        assert job_done(client, client.post(url, json={}).json())["state"] == "succeeded"
        again = client.post(url, json={"candidates": [method]})
        assert (again.status_code, again.json()["error"]["code"]) == (409, "nothing_to_build")

    def test_nothing_of_it_is_open_to_one_without_the_token(self, workspace: Workspace) -> None:
        app = create_app(workspace.root, token=TOKEN, check_keys=False, max_upload_bytes=100_000)
        with TestClient(app, base_url=LOCAL) as anyone:
            assert anyone.post("/api/bakeoffs/any/build", json={}).status_code == 401
