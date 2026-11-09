"""Tests of fetching a PaperAgent's code: the projects its paper points to, the job that fetches one at a commit and
takes stock of it, what is kept and how, the check of whether to go on, what the address and the agent's other
operations do to it, and that nothing in the code is run. Git is replaced by a stand-in that writes a project's files,
except where a test says it is the real one."""

import io
import json
import os
import shutil
import stat
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MODEL, FakeClient
from fastapi.testclient import TestClient
from test_paperagents_reading import ReadLicense, ReadLink, reading
from test_paperagents_stock import MIT, notebook, tree

from virtual_lab.environment import StoppedError
from virtual_lab.paperagents import repository as cloning
from virtual_lab.paperagents.anchors import document_from
from virtual_lab.paperagents.reading import plan_chunks
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server import paperagents as module
from virtual_lab.server.app import create_app
from virtual_lab.server.errors import ApiError
from virtual_lab.server.jobs import Job, Jobs
from virtual_lab.server.paperagents import AGENT_FILE, REPOSITORY_JOB, PaperAgents, is_agent
from virtual_lab.server.workspace import Settings, Workspace

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}

LIMIT_BYTES = 100_000
SIZE = 400
URL = "https://github.com/example/cellmapper"
OTHER_URL = "https://github.com/example/plots"
COMMIT = "0123456789abcdef0123456789abcdef01234567"

PLOTS = "The plotting helpers are at https://github.com/example/plots/tree/main in a project of their own."
FIGURES = "The code of every figure is at https://github.com/example/cellmapper."
DATA = "The data are deposited at https://zenodo.org/records/1234567."
LAB = "More of the lab's work is at https://github.com/orgs/example/people."
CODE = "The analysis code is at https://github.com/example/cellmapper.git and is released under the MIT license."
PAPER = "\n\n".join(
    [
        "CellMapper: mapping cell types",
        "Abstract",
        "We present CellMapper, a method for mapping cell types in single-nucleus RNA-seq data.",
        "Methods",
        PLOTS,
        FIGURES,
        "Data availability",
        DATA,
        LAB,
        "Code availability",
        CODE,
    ]
)


def project(marker: Path) -> dict[str, str | bytes | dict[str, Any]]:
    """What a project's files are, some of which would leave a mark if they were run."""
    leaves = f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n"

    return {
        "README.md": "# CellMapper\n\nMaps cell types.\n\n## Usage\n\nSee the tutorial.\n",
        "LICENSE": MIT,
        "environment.yml": "name: cellmapper\ndependencies:\n  - python=3.11\n  - numpy=1.26.4\n",
        "setup.py": leaves,
        "conftest.py": leaves,
        "cellmapper/__init__.py": leaves,
        "cellmapper/mapping.py": "def map_cells(counts):\n    return counts\n",
        "tests/test_mapping.py": "def test_maps():\n    assert True\n",
        "tutorials/quickstart.ipynb": notebook(
            ["import cellmapper\n" + leaves], ["# Quickstart", "Map the cells of a sample."]
        ),
    }


class Remote:
    """Stands in for fetching with Git: writes a project's files where it is told to, and says what it was asked."""

    def __init__(self, files: dict[str, str | bytes | dict[str, Any]]) -> None:
        self.files = files
        self.calls: list[dict[str, Any]] = []
        self.error: BaseException | None = None
        self.started = threading.Event()
        self.gate: threading.Event | None = None
        self.during: Any = None

    def __call__(
        self, url: str, destination: Path, ref: str | None = None, max_bytes: int = 0, **options: Any
    ) -> cloning.Cloned:
        self.calls.append({"url": url, "ref": ref, "max_bytes": max_bytes, "options": sorted(options)})
        self.started.set()
        if self.gate is not None:
            while not self.gate.wait(0.01):
                if options["should_stop"]():
                    raise StoppedError("Stopped while the code was fetched.")
        if self.during is not None:
            self.during()
        if self.error is not None:
            raise self.error
        tree(destination, self.files)

        return cloning.Cloned(COMMIT, ref or "HEAD")


@pytest.fixture(autouse=True)
def model_client(fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    monkeypatch.setattr(module, "DEFAULT_PAPER_CHUNK_SIZE", SIZE)
    monkeypatch.setattr(module, "DEFAULT_PAPER_CHUNK_OVERLAP", 0)

    return fake_client


@pytest.fixture(autouse=True)
def git_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fetching asks for Git to be there, which the stand-in does not need."""
    real = shutil.which

    def which(name: str, *rest: Any, **options: Any) -> str | None:
        return "/usr/bin/git" if name == "git" else real(name, *rest, **options)

    monkeypatch.setattr(shutil, "which", which)


@pytest.fixture
def marker(tmp_path: Path) -> Path:
    """A file that comes to be if any of the project's code is run."""
    return tmp_path / "code-ran"


@pytest.fixture
def remote(marker: Path, monkeypatch: pytest.MonkeyPatch) -> Remote:
    fetching = Remote(project(marker))
    monkeypatch.setattr(cloning, "clone", fetching)

    return fetching


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
def agents(workspace: Workspace, jobs: Jobs) -> PaperAgents:
    return PaperAgents(workspace, LIMIT_BYTES, jobs, lambda model: [])


@pytest.fixture
def client(workspace: Workspace) -> Iterator[TestClient]:
    app = create_app(workspace.root, token=TOKEN, check_keys=False, max_upload_bytes=LIMIT_BYTES)
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


def agent_of(agents: PaperAgents, repo: str | None = URL, title: str = "CellMapper") -> str:
    return agents.create(title, {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}, repo)


def fetch(agents: PaperAgents, agent_id: str, **options: Any) -> Job:
    return finish(agents.fetch_repository(agent_id, **options))


def directory_of(workspace: Workspace, agent_id: str) -> Path:
    return workspace.paperagents_dir / agent_id


def read_paper(agents: PaperAgents, agent_id: str, fake_client: FakeClient) -> None:
    """Reads the paper, with what a good model says of the places it links to and of the license of its code."""
    agents.put_paper(agent_id, "paper.txt", io.BytesIO(PAPER.encode("utf-8")))
    document = document_from([PAPER], paged=False)
    links = [
        (PLOTS, "https://github.com/example/plots/tree/main", "other"),
        (FIGURES, URL, "other"),
        (DATA, "https://zenodo.org/records/1234567", "data"),
        (LAB, "https://github.com/orgs/example/people", "other"),
        (CODE, f"{URL}.git", "code"),
    ]
    answers = []
    seen = set()
    for chunk in plan_chunks(document, SIZE, 0):
        if chunk.skip:
            continue
        here = [(quote, url, role) for quote, url, role in links if quote in chunk.text]
        seen.update(quote for quote, _, _ in here)
        answers.append(
            reading(
                links=[ReadLink(url=url, role=role, quote=quote) for quote, url, role in here],  # type: ignore[arg-type]
                licenses=[ReadLicense(name="MIT", covers="code", quote=CODE)] if CODE in chunk.text else [],
            )
        )
    assert seen == {quote for quote, _, _ in links}, "a quote falls between chunks"
    from test_paperagents_reading import queue

    queue(fake_client, *answers)
    job = finish(agents.read(agent_id, 5))
    assert job.state == "succeeded", job.error


class TestTheProjectsThePaperPointsTo:
    def test_there_are_none_until_the_paper_has_been_read(self, agents: PaperAgents) -> None:
        found = agents.repository(agent_of(agents, repo=None))

        assert found["candidates"] == []
        assert (found["repo"], found["cloned"], found["intake"], found["stock"], found["preflight"]) == (
            None,
            False,
            None,
            None,
            None,
        )
        assert (found["job"], found["git"]) == (None, True)
        assert found["limits"] == {"default_megabytes": 200, "min_megabytes": 10, "max_megabytes": 1000}

    def test_the_projects_in_the_links_are_listed_once_each_with_the_words_that_say_them(
        self, agents: PaperAgents, fake_client: FakeClient
    ) -> None:
        agent_id = agent_of(agents, repo=None)
        read_paper(agents, agent_id, fake_client)

        candidates = agents.repository(agent_id)["candidates"]

        # The one that the paper says is its code first, though another mention of it came before; not the data's
        # address, which is not at a host that holds code, nor the pages of the host that look like projects
        assert [(item["url"], item["role"], item["chosen"]) for item in candidates] == [
            (URL, "code", False),
            (OTHER_URL, "other", False),
        ]
        assert sorted(fact["quote"] for fact in candidates[0]["facts"]) == sorted([CODE, FIGURES])
        assert [fact["quote"] for fact in candidates[1]["facts"]] == [PLOTS]
        assert all(set(fact["anchor"]) >= {"start", "end"} for item in candidates for fact in item["facts"])

    def test_the_one_the_agent_has_is_said_to_be_the_chosen(self, agents: PaperAgents, fake_client: FakeClient) -> None:
        agent_id = agent_of(agents, repo=OTHER_URL)
        read_paper(agents, agent_id, fake_client)

        chosen = {item["url"]: item["chosen"] for item in agents.repository(agent_id)["candidates"]}

        assert chosen == {URL: False, OTHER_URL: True}

    def test_a_link_that_is_not_to_a_project_is_not_one(self, agents: PaperAgents) -> None:
        assert agents.as_repo("https://github.com/example/cellmapper/tree/main/src.") == URL
        assert agents.as_repo("http://github.com/example/cellmapper.git") == URL
        assert agents.as_repo("github.com/example/cellmapper") == URL
        for link in (
            "https://zenodo.org/records/1",
            "https://github.com/example",
            "https://github.com/orgs/example/people",
            "https://github.com/sponsors/example",
            "https://github.com/features/actions",
            "https://example.org/a/b",
            "https://user:pass@github.com/a/b",
            "not a link",
            "",
        ):
            assert agents.as_repo(link) is None, link


class TestFetching:
    def test_the_code_is_fetched_as_a_job_and_what_was_found_of_it_is_kept(
        self, agents: PaperAgents, workspace: Workspace, remote: Remote
    ) -> None:
        agent_id = agent_of(agents, title="Cell mapper")

        started = agents.fetch_repository(agent_id)
        assert (started.kind, started.subject, started.title) == (
            REPOSITORY_JOB,
            agent_id,
            "Fetching the code and taking stock of it: Cell mapper",
        )
        job = finish(started)

        assert job.state == "succeeded"
        assert job.message.startswith("Fetched ") and f"at commit {COMMIT[:12]}" in job.message
        assert "9 files" in job.message
        assert any(line.startswith(f"Fetched {URL} at commit {COMMIT}") for line in job.snapshot(0)["log"]["lines"])
        assert remote.calls == [{"url": URL, "ref": "HEAD", "max_bytes": 200 * 1024 * 1024, "options": ["should_stop"]}]
        found = agents.repository(agent_id)
        assert found["cloned"] is True and found["job"] is None
        assert found["repo"] == {"url": URL, "ref": "HEAD", "commit": COMMIT}
        assert (found["intake"] or {}).keys() == {"url", "ref", "commit", "cloned_at", "limit_bytes"}
        assert (found["intake"] or {})["limit_bytes"] == 200 * 1024 * 1024
        assert agents.view(agent_id)["steps"]["repository"] == "done"
        assert agents.view(agent_id)["repo"] == {"url": URL, "ref": "HEAD", "commit": COMMIT}
        stock = found["stock"]
        assert stock["files"] == 9 and stock["complete"] is True
        assert [language["name"] for language in stock["languages"]][0] == "Python"
        assert stock["license"]["name"] == "MIT" and stock["tests"]["listed"] == [
            "conftest.py",
            "tests/test_mapping.py",
        ]
        assert stock["tutorials"]["count"] == 1 and stock["environment"][0]["path"] == "environment.yml"
        assert found["preflight"]["verdict"] in ("go", "ask") and found["preflight"]["summary"]
        assert found["preflight"]["summary"] in job.message

    def test_the_files_are_kept_to_be_read_and_not_written_to_beside_where_they_came_from(
        self, agents: PaperAgents, workspace: Workspace, remote: Remote
    ) -> None:
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        folder = directory_of(workspace, agent_id)
        assert {path.name for path in folder.iterdir()} == {AGENT_FILE, "repo", "intake.json"}
        assert (folder / "repo" / "cellmapper" / "mapping.py").read_text().startswith("def map_cells")
        files = [path for path in (folder / "repo").rglob("*") if path.is_file()]
        assert len(files) == 9 and all(not os.access(path, os.W_OK) for path in files)
        assert all(not path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) for path in files)
        written = json.loads((folder / "intake.json").read_text())
        assert written["schema"] == 1 and written["commit"] == COMMIT and written["stock"]["files"] == 9
        assert kept_repository.is_intake(written)
        # Nothing of the fetching is left where it was made
        assert not [path for path in workspace.root.iterdir() if path.name.startswith("paperagent.")]

    def test_none_of_the_code_is_run_to_fetch_it_or_to_take_stock_of_it_or_to_check_it(
        self, agents: PaperAgents, remote: Remote, marker: Path
    ) -> None:
        agent_id = agent_of(agents)

        fetch(agents, agent_id)
        agents.repository(agent_id)

        assert remote.calls and not marker.exists()

    def test_the_code_is_asked_for_at_the_commit_and_with_the_limit_that_was_given(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        agent_id = agent_of(agents)

        fetch(agents, agent_id, ref="v1.2", max_megabytes=50)

        assert (remote.calls[0]["ref"], remote.calls[0]["max_bytes"]) == ("v1.2", 50 * 1024 * 1024)
        assert agents.view(agent_id)["repo"] == {"url": URL, "ref": "v1.2", "commit": COMMIT}
        assert (agents.repository(agent_id)["intake"] or {})["ref"] == "v1.2"

    def test_the_address_that_was_chosen_from_the_paper_becomes_the_agents(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        agent_id = agent_of(agents, repo=None)

        fetch(agents, agent_id, repo=f"{URL}.git")

        assert remote.calls[0]["url"] == URL
        assert agents.view(agent_id)["repo"] == {"url": URL, "ref": "HEAD", "commit": COMMIT}
        assert agents.view(agent_id)["steps"]["repository"] == "done"

    def test_another_address_than_the_agents_replaces_it_and_the_code_that_was_fetched_from_it(
        self, agents: PaperAgents, workspace: Workspace, remote: Remote
    ) -> None:
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        job = fetch(agents, agent_id, repo=OTHER_URL)

        assert job.state == "succeeded" and [call["url"] for call in remote.calls] == [URL, OTHER_URL]
        assert agents.repository(agent_id)["intake"]["url"] == OTHER_URL  # type: ignore[index]
        assert agents.view(agent_id)["repo"] == {"url": OTHER_URL, "ref": "HEAD", "commit": COMMIT}
        assert not (directory_of(workspace, agent_id) / "repo.old").exists()

    def test_code_that_was_fetched_is_not_fetched_again_until_it_is_removed(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        error = refused(agents.fetch_repository, agent_id)
        assert (error.status, error.code) == (409, "done") and "Remove it" in str(error)
        # Naming the same address again does not fetch it again either
        assert refused(agents.fetch_repository, agent_id, repo=f"{URL}.git").code == "done"

        agents.clear_repository(agent_id)
        fetch(agents, agent_id)

        assert len(remote.calls) == 2

    def test_the_check_is_made_again_from_what_the_paper_says_once_it_has_been_read(
        self, agents: PaperAgents, remote: Remote, fake_client: FakeClient
    ) -> None:
        agent_id = agent_of(agents)
        fetch(agents, agent_id)
        before = {item["id"]: item for item in agents.repository(agent_id)["preflight"]["checks"]}
        assert "The paper has not been read through" in before["data"]["detail"]
        assert "The paper says" not in before["license"]["detail"]

        read_paper(agents, agent_id, fake_client)

        after = {item["id"]: item for item in agents.repository(agent_id)["preflight"]["checks"]}
        assert "The paper says the code is under MIT" in after["license"]["detail"]
        assert "The paper has not been read through" not in after["data"]["detail"]
        assert "link to data in the paper" in after["data"]["detail"]

    def test_code_with_nothing_to_use_is_a_no_go_that_says_so(self, agents: PaperAgents, remote: Remote) -> None:
        remote.files = {"README.md": "# Just words\n", "paper.pdf": b"%PDF-1.4"}
        agent_id = agent_of(agents)

        job = fetch(agents, agent_id)

        found = agents.repository(agent_id)
        assert job.state == "succeeded" and job.message.endswith(found["preflight"]["summary"])
        assert found["preflight"]["verdict"] == "no-go" and found["preflight"]["summary"].startswith("No-go:")
        assert agents.view(agent_id)["steps"]["repository"] == "done"

    def test_what_the_check_costs_is_estimated_at_the_price_of_the_model(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        estimate = agents.repository(agent_id)["preflight"]["estimate"]

        assert estimate is not None and 0 < estimate["low"] <= estimate["high"]

    def test_an_agent_that_is_not_there_is_not_found(self, agents: PaperAgents) -> None:
        for call in (agents.fetch_repository, agents.repository, agents.clear_repository):
            assert refused(call, "nothing").status == 404


class TestRefusals:
    def test_there_is_nothing_to_fetch_without_an_address(self, agents: PaperAgents, remote: Remote) -> None:
        agent_id = agent_of(agents, repo=None)

        error = refused(agents.fetch_repository, agent_id)

        assert (error.status, error.code) == (422, "no_repo") and "Say where the code is" in str(error)
        assert refused(agents.fetch_repository, agent_id, repo="  ").code == "no_repo"
        assert remote.calls == []

    @pytest.mark.parametrize(
        "repo",
        ["https://example.org/a/b", "http://github.com/a/b", "https://github.com/a", "not a link", 5, ["x"]],
    )
    def test_an_address_that_is_not_a_project_at_a_host_that_holds_code_is_refused(
        self, agents: PaperAgents, remote: Remote, repo: Any
    ) -> None:
        agent_id = agent_of(agents, repo=None)

        assert refused(agents.fetch_repository, agent_id, repo=repo).status == 422
        assert remote.calls == [] and agents.view(agent_id)["repo"] is None

    @pytest.mark.parametrize("ref", ["--upload-pack=x", "-x", "a..b", "a b", "a;b", "x" * 300, "~1", "a\nb", "/etc"])
    def test_a_branch_tag_or_commit_that_could_be_taken_for_an_option_or_a_path_is_refused(
        self, agents: PaperAgents, remote: Remote, ref: str
    ) -> None:
        error = refused(agents.fetch_repository, agent_of(agents), ref=ref)

        assert (error.status, error.code) == (422, "invalid") and remote.calls == []

    @pytest.mark.parametrize("megabytes", [0, 9, 1001, -5, "50", True, 50.5, [], float("nan")])
    def test_a_limit_that_is_not_a_whole_number_of_megabytes_in_range_is_refused(
        self, agents: PaperAgents, remote: Remote, megabytes: Any
    ) -> None:
        assert refused(agents.fetch_repository, agent_of(agents), max_megabytes=megabytes).status == 422
        assert remote.calls == []

    @pytest.mark.parametrize("megabytes", [10, 1000])
    def test_the_least_and_the_most_that_can_be_asked_for_are_allowed(
        self, agents: PaperAgents, remote: Remote, megabytes: int
    ) -> None:
        agent_id = agent_of(agents)

        assert fetch(agents, agent_id, max_megabytes=megabytes).state == "succeeded"
        assert remote.calls[0]["max_bytes"] == megabytes * 1024 * 1024

    def test_without_git_nothing_is_started_and_it_is_said_why(
        self, agents: PaperAgents, remote: Remote, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(shutil, "which", lambda name, *rest, **options: None)
        agent_id = agent_of(agents)

        error = refused(agents.fetch_repository, agent_id)

        assert (error.status, error.code) == (422, "git_missing") and "Git is not installed" in str(error)
        assert agents.repository(agent_id)["git"] is False and remote.calls == []


class TestWhenItGoesWrong:
    def test_code_that_cannot_be_fetched_says_why_and_leaves_nothing(
        self, agents: PaperAgents, workspace: Workspace, remote: Remote
    ) -> None:
        remote.error = cloning.RepositoryError("The project at that address was not found.")
        agent_id = agent_of(agents)

        job = fetch(agents, agent_id)

        assert job.state == "failed" and job.error == "The project at that address was not found."
        assert agents.view(agent_id)["steps"]["repository"] == "failed"
        assert agents.view(agent_id)["repo"] == {"url": URL}
        folder = directory_of(workspace, agent_id)
        assert {path.name for path in folder.iterdir()} == {AGENT_FILE}
        assert not [path for path in workspace.root.iterdir() if path.name.startswith("paperagent.")]

    def test_it_can_be_tried_again_after_it_failed(self, agents: PaperAgents, remote: Remote) -> None:
        remote.error = cloning.RepositoryError("The network was down.")
        agent_id = agent_of(agents)
        assert fetch(agents, agent_id).state == "failed"
        remote.error = None

        assert fetch(agents, agent_id).state == "succeeded"
        assert agents.view(agent_id)["steps"]["repository"] == "done"

    def test_code_that_is_too_big_is_refused_with_how_big_it_is(self, agents: PaperAgents, remote: Remote) -> None:
        remote.error = cloning.RepositoryTooBigError(
            "The code is more than 10 MB, which is the most that is fetched. It had come to 31 MB.",
            31 * 1024 * 1024,
            10 * 1024 * 1024,
        )
        agent_id = agent_of(agents)

        job = fetch(agents, agent_id, max_megabytes=10)

        assert job.state == "failed" and "more than 10 MB" in job.error and "31 MB" in job.error
        assert agents.view(agent_id)["steps"]["repository"] == "failed"
        assert agents.repository(agent_id)["cloned"] is False

    def test_a_request_to_stop_while_it_is_fetched_keeps_nothing(
        self, agents: PaperAgents, workspace: Workspace, remote: Remote
    ) -> None:
        remote.gate = threading.Event()
        agent_id = agent_of(agents)
        job = agents.fetch_repository(agent_id)
        assert remote.started.wait(20)
        assert agents.view(agent_id)["steps"]["repository"] == "running"
        job.request_stop()
        finish(job)

        assert job.state == "stopped"
        assert agents.view(agent_id)["steps"]["repository"] == "pending"
        assert {path.name for path in directory_of(workspace, agent_id).iterdir()} == {AGENT_FILE}
        assert agents.repository(agent_id)["job"] is None

    def test_a_request_to_stop_after_it_is_fetched_and_before_it_is_kept_keeps_nothing(
        self, agents: PaperAgents, workspace: Workspace, remote: Remote, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_id = agent_of(agents)
        jobs_of = agents.cloning

        def stop_when_stock_is_taken(root: Path) -> dict[str, Any]:
            job = jobs_of(agent_id)
            assert job is not None
            job.request_stop()

            return real(root)

        real = module.stocking.take_stock
        monkeypatch.setattr(module.stocking, "take_stock", stop_when_stock_is_taken)

        job = fetch(agents, agent_id)

        assert job.state == "stopped"
        assert {path.name for path in directory_of(workspace, agent_id).iterdir()} == {AGENT_FILE}
        assert agents.view(agent_id)["steps"]["repository"] == "pending"

    def test_code_whose_address_was_changed_while_it_was_fetched_is_not_kept_for_the_new_one(
        self, agents: PaperAgents, workspace: Workspace, remote: Remote
    ) -> None:
        agent_id = agent_of(agents)

        def change_the_file() -> None:
            directory, agent = agents.lookup(agent_id)
            agents.save(directory, {**agent, "repo": {"url": OTHER_URL}})

        remote.during = change_the_file

        job = fetch(agents, agent_id)

        assert job.state == "failed" and "address of the code was changed" in job.error
        assert agents.repository(agent_id)["cloned"] is False
        assert {path.name for path in directory_of(workspace, agent_id).iterdir()} == {AGENT_FILE}
        assert agents.view(agent_id)["repo"] == {"url": OTHER_URL}


class TestWhileItIsFetched:
    def start(self, agents: PaperAgents, remote: Remote) -> tuple[str, Job]:
        remote.gate = threading.Event()
        agent_id = agent_of(agents)
        agents.put_paper(agent_id, "paper.txt", io.BytesIO(PAPER.encode()))
        job = agents.fetch_repository(agent_id)
        assert remote.started.wait(20)

        return agent_id, job

    def test_what_changes_the_code_or_the_agent_waits_for_it(self, agents: PaperAgents, remote: Remote) -> None:
        agent_id, job = self.start(agents, remote)

        try:
            for call in (
                lambda: agents.fetch_repository(agent_id),
                lambda: agents.clear_repository(agent_id),
                lambda: agents.delete(agent_id),
                lambda: agents.change(agent_id, repo=OTHER_URL),
                lambda: agents.read(agent_id, 5),
                lambda: agents.put_paper(agent_id, "paper.txt", io.BytesIO(b"A paper")),
            ):
                error = refused(call)
                assert (error.status, error.code) == (409, "busy"), error
            assert refused(lambda: agents.fetch_repository(agent_id, repo=OTHER_URL)).code == "busy"
            assert agents.view(agent_id)["repo"] == {"url": URL}
            # What does not touch the code can still be done
            agents.change(agent_id, title="Renamed")
            assert agents.repository(agent_id)["job"]["id"] == job.id
        finally:
            assert remote.gate is not None
            remote.gate.set()
            finish(job)
        assert job.state == "succeeded"

    def test_the_same_address_said_again_is_let_be_while_it_is_fetched(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        agent_id, job = self.start(agents, remote)

        try:
            agents.change(agent_id, repo=f"{URL}.git")
        finally:
            assert remote.gate is not None
            remote.gate.set()
            finish(job)

        assert job.state == "succeeded" and agents.repository(agent_id)["cloned"] is True


class TestWhatChangesTheCode:
    def fetched(self, agents: PaperAgents, remote: Remote) -> tuple[str, Path]:
        agent_id = agent_of(agents)
        fetch(agents, agent_id)
        folder = directory_of(agents.workspace, agent_id)
        assert (folder / "repo").is_dir()

        return agent_id, folder

    def test_clearing_it_takes_away_the_files_and_what_was_found_and_keeps_the_address(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        agent_id, folder = self.fetched(agents, remote)

        cleared = agents.clear_repository(agent_id)

        assert cleared is None
        assert {path.name for path in folder.iterdir()} == {AGENT_FILE}
        assert agents.view(agent_id)["repo"] == {"url": URL}
        assert agents.view(agent_id)["steps"]["repository"] == "pending"
        found = agents.repository(agent_id)
        assert (found["cloned"], found["stock"], found["preflight"], found["intake"]) == (False, None, None, None)

    def test_clearing_what_was_never_fetched_is_nothing(self, agents: PaperAgents) -> None:
        agent_id = agent_of(agents)

        agents.clear_repository(agent_id)

        assert agents.view(agent_id)["repo"] == {"url": URL}

    def test_another_address_takes_away_the_code_of_the_one_it_replaces(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        agent_id, folder = self.fetched(agents, remote)

        agents.change(agent_id, repo=OTHER_URL)

        assert {path.name for path in folder.iterdir()} == {AGENT_FILE}
        assert agents.view(agent_id)["repo"] == {"url": OTHER_URL}
        assert agents.view(agent_id)["steps"]["repository"] == "pending"
        assert agents.repository(agent_id)["cloned"] is False

    def test_taking_the_address_away_takes_away_the_code_too(self, agents: PaperAgents, remote: Remote) -> None:
        agent_id, folder = self.fetched(agents, remote)

        agents.change(agent_id, repo="")

        assert {path.name for path in folder.iterdir()} == {AGENT_FILE} and agents.view(agent_id)["repo"] is None

    def test_the_same_address_or_a_new_title_leaves_it_as_it_is(self, agents: PaperAgents, remote: Remote) -> None:
        agent_id, folder = self.fetched(agents, remote)

        agents.change(agent_id, repo=f"{URL}.git")
        agents.change(agent_id, title="A new title")

        assert agents.repository(agent_id)["cloned"] is True
        assert agents.view(agent_id)["title"] == "A new title"
        assert agents.view(agent_id)["repo"] == {"url": URL, "ref": "HEAD", "commit": COMMIT}
        assert agents.view(agent_id)["steps"]["repository"] == "done"

    def test_deleting_the_agent_removes_the_code_whose_files_cannot_be_written_to(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        agent_id, folder = self.fetched(agents, remote)

        agents.delete(agent_id)

        assert not folder.exists()

    def test_code_that_was_fetched_for_another_address_is_not_shown_for_this_one(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        agent_id, folder = self.fetched(agents, remote)
        directory, agent = agents.lookup(agent_id)
        # Edited by hand, since the agent's own operations would have taken the code away
        agents.save(directory, {**agent, "repo": {"url": OTHER_URL}})

        found = agents.repository(agent_id)

        assert (found["cloned"], found["stock"], found["preflight"]) == (False, None, None)
        # The code of the other address is replaced, not taken to be this one's
        assert fetch(agents, agent_id).state == "succeeded"
        assert agents.repository(agent_id)["intake"]["url"] == OTHER_URL  # type: ignore[index]

    @pytest.mark.parametrize(
        "damage",
        [
            lambda written: written.pop("stock"),
            lambda written: written.update(commit="not-a-commit"),
            lambda written: written.update(ref="--upload-pack=x"),
            lambda written: written.update(schema=99),
            lambda written: written.update(limit_bytes="a lot"),
            lambda written: written["stock"].update(files="many"),
        ],
    )
    def test_a_record_that_was_edited_into_something_it_is_not_is_not_taken_for_one(
        self, agents: PaperAgents, remote: Remote, damage: Any
    ) -> None:
        agent_id, folder = self.fetched(agents, remote)
        written = json.loads((folder / "intake.json").read_text())
        damage(written)
        (folder / "intake.json").write_text(json.dumps(written))

        found = agents.repository(agent_id)

        assert (found["cloned"], found["stock"], found["preflight"]) == (False, None, None)

    def test_a_record_without_its_files_is_not_taken_for_code(self, agents: PaperAgents, remote: Remote) -> None:
        agent_id, folder = self.fetched(agents, remote)
        kept_repository.remove_tree(folder / "repo")

        assert agents.repository(agent_id)["cloned"] is False

    def test_a_link_in_place_of_the_files_is_not_taken_for_code(
        self, agents: PaperAgents, remote: Remote, tmp_path: Path
    ) -> None:
        agent_id, folder = self.fetched(agents, remote)
        kept_repository.remove_tree(folder / "repo")
        (folder / "repo").symlink_to(tmp_path)

        assert agents.repository(agent_id)["cloned"] is False


class TestWhatAnAgentKeepsOfItsCode:
    GOOD = {"url": URL, "ref": "main", "commit": COMMIT}

    def agent(self, **changes: Any) -> dict[str, Any]:
        return {
            "schema": 1,
            "title": "A",
            "created_at": "2025-01-01T00:00:00Z",
            "paper": {"kind": "file"},
            "repo": {**self.GOOD, **changes},
            "steps": {},
        }

    def test_a_pin_is_a_commit_and_what_was_asked_for_to_get_it(self) -> None:
        assert is_agent(self.agent())
        assert is_agent({**self.agent(), "repo": {"url": URL}})
        assert is_agent({**self.agent(), "repo": None})

    @pytest.mark.parametrize(
        "changes",
        [
            {"commit": None},
            {"ref": None},
            {"commit": "abc"},
            {"commit": "G" * 40},
            {"commit": COMMIT.upper()},
            {"commit": 5},
            {"ref": "--upload-pack=x"},
            {"ref": "a..b"},
            {"ref": 5},
            {"url": "https://example.org/a/b"},
        ],
    )
    def test_a_pin_that_a_hand_edit_made_into_something_else_is_not_an_agent(self, changes: dict[str, Any]) -> None:
        assert not is_agent(self.agent(**changes))

    def test_an_agent_with_such_a_pin_is_not_listed(self, agents: PaperAgents, workspace: Workspace) -> None:
        agent_id = agent_of(agents)
        directory, agent = agents.lookup(agent_id)
        agents.save(directory, {**agent, "repo": {"url": URL, "commit": "abc"}})

        assert agents.kept() == []


class TestTheApi:
    def make(self, client: TestClient, repo: str | None = URL) -> str:
        body: dict[str, Any] = {"title": "CellMapper", "paper": {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}}
        if repo is not None:
            body["repo"] = repo
        made = client.post("/api/paperagents", json=body)
        assert made.status_code == 201
        agent_id: str = made.json()["id"]

        return agent_id

    def wait_for(self, client: TestClient, job: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + 20
        while (state := client.get(f"/api/setup/jobs/{job['id']}").json())["state"] == "running":
            assert time.monotonic() < deadline
            time.sleep(0.02)

        return dict(state)

    def test_the_code_is_fetched_asked_for_and_removed(self, client: TestClient, remote: Remote) -> None:
        agent_id = self.make(client)
        before = client.get(f"/api/paperagents/{agent_id}/repository")
        assert before.status_code == 200 and before.json()["cloned"] is False and before.json()["git"] is True

        started = client.post(f"/api/paperagents/{agent_id}/repository", json={"ref": "main", "max_megabytes": 20})

        assert started.status_code == 202
        job = started.json()
        assert (job["kind"], job["subject"]) == (REPOSITORY_JOB, agent_id)
        assert client.get(f"/api/paperagents/{agent_id}").json()["steps"]["repository"] in ("running", "done")
        assert self.wait_for(client, job)["state"] == "succeeded"
        found = client.get(f"/api/paperagents/{agent_id}/repository").json()
        assert found["cloned"] is True and found["intake"]["ref"] == "main"
        assert found["stock"]["files"] == 9 and found["preflight"]["verdict"] in ("go", "ask")
        assert remote.calls[0]["max_bytes"] == 20 * 1024 * 1024
        assert client.get(f"/api/paperagents/{agent_id}").json()["steps"]["repository"] == "done"
        again = client.post(f"/api/paperagents/{agent_id}/repository", json={})
        assert again.status_code == 409 and again.json()["error"]["code"] == "done"

        cleared = client.delete(f"/api/paperagents/{agent_id}/repository")

        assert cleared.status_code == 200 and cleared.json()["cloned"] is False and cleared.json()["stock"] is None
        assert client.get(f"/api/paperagents/{agent_id}").json()["steps"]["repository"] == "pending"

    def test_the_address_chosen_from_the_paper_is_sent_with_the_request(
        self, client: TestClient, remote: Remote
    ) -> None:
        agent_id = self.make(client, repo=None)

        started = client.post(f"/api/paperagents/{agent_id}/repository", json={"repo": URL})

        assert started.status_code == 202 and self.wait_for(client, started.json())["state"] == "succeeded"
        assert client.get(f"/api/paperagents/{agent_id}").json()["repo"]["url"] == URL

    def test_a_failed_fetch_says_why_through_the_job(self, client: TestClient, remote: Remote) -> None:
        remote.error = cloning.RepositoryError("The project at that address was not found.")
        agent_id = self.make(client)

        started = client.post(f"/api/paperagents/{agent_id}/repository", json={})
        done = self.wait_for(client, started.json())

        assert done["state"] == "failed" and done["error"] == "The project at that address was not found."
        assert client.get(f"/api/paperagents/{agent_id}").json()["steps"]["repository"] == "failed"

    @pytest.mark.parametrize(
        "body",
        [
            {"max_megabytes": "50"},
            {"max_megabytes": 50.5},
            {"max_megabytes": True},
            {"max_megabytes": 5},
            {"max_megabytes": 5000},
            {"ref": "--x"},
            {"ref": 5},
            {"ref": "x" * 401},
            {"repo": "https://example.org/a/b"},
            {"repo": 5},
            {"more": 1},
        ],
    )
    def test_what_is_not_fit_to_ask_for_is_refused(
        self, client: TestClient, remote: Remote, body: dict[str, Any]
    ) -> None:
        agent_id = self.make(client)

        assert client.post(f"/api/paperagents/{agent_id}/repository", json=body).status_code == 422
        assert remote.calls == []

    def test_there_is_no_fetching_without_an_address(self, client: TestClient, remote: Remote) -> None:
        agent_id = self.make(client, repo=None)

        refusal = client.post(f"/api/paperagents/{agent_id}/repository", json={})

        assert refusal.status_code == 422 and refusal.json()["error"]["code"] == "no_repo"

    def test_an_agent_that_is_not_there_is_not_found(self, client: TestClient) -> None:
        assert client.post("/api/paperagents/nothing/repository", json={}).status_code == 404
        assert client.get("/api/paperagents/nothing/repository").status_code == 404
        assert client.delete("/api/paperagents/nothing/repository").status_code == 404

    def test_the_code_of_an_agent_is_not_given_to_a_request_without_the_token(
        self, client: TestClient, remote: Remote
    ) -> None:
        agent_id = self.make(client)

        unsigned = TestClient(client.app, base_url=LOCAL)

        assert unsigned.get(f"/api/paperagents/{agent_id}/repository").status_code == 401
        assert unsigned.post(f"/api/paperagents/{agent_id}/repository", json={}).status_code == 401
        assert unsigned.delete(f"/api/paperagents/{agent_id}/repository").status_code == 401
        assert remote.calls == []


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is not installed")
class TestWithGit:
    """The whole way, with Git itself fetching a project made in a folder, which a test is let do and the server does
    not (it fetches by https only)."""

    def git(self, folder: Path, *arguments: str) -> str:
        environment = {
            **os.environ,
            "GIT_AUTHOR_NAME": "A. Author",
            "GIT_AUTHOR_EMAIL": "author@example.org",
            "GIT_COMMITTER_NAME": "A. Author",
            "GIT_COMMITTER_EMAIL": "author@example.org",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        done = subprocess.run(
            ["git", *arguments], cwd=folder, env=environment, capture_output=True, text=True, check=True
        )

        return done.stdout.strip()

    @pytest.fixture
    def source(self, tmp_path: Path, marker: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        folder = tmp_path / "source"
        tree(folder, project(marker))
        self.git(folder, "init", "--quiet", "-b", "main")
        self.git(folder, "add", "--all")
        self.git(folder, "commit", "--quiet", "-m", "first")
        self.git(folder, "tag", "v1")
        real = cloning.clone

        def from_the_folder(
            url: str, destination: Path, ref: str | None = None, max_bytes: int = 0, **rest: Any
        ) -> Any:
            return real(f"file://{folder}", destination, ref, max_bytes, protocols="file", **rest)

        monkeypatch.setattr(cloning, "clone", from_the_folder)

        return folder

    def test_the_project_is_fetched_at_a_commit_and_stock_is_taken_without_running_any_of_it(
        self, agents: PaperAgents, workspace: Workspace, source: Path, marker: Path
    ) -> None:
        first = self.git(source, "rev-parse", "HEAD")
        (source / "cellmapper" / "mapping.py").write_text("def map_cells(counts):\n    return 2\n")
        self.git(source, "commit", "--quiet", "-am", "second")
        agent_id = agent_of(agents)

        job = fetch(agents, agent_id, ref="v1")

        assert job.state == "succeeded", job.error
        found = agents.repository(agent_id)
        assert found["repo"] == {"url": URL, "ref": "v1", "commit": first}
        folder = directory_of(workspace, agent_id) / "repo"
        assert (folder / "cellmapper" / "mapping.py").read_text().endswith("return counts\n")
        assert not (folder / ".git").exists() and not marker.exists()
        assert found["stock"]["files"] == 9 and found["stock"]["license"]["name"] == "MIT"

    def test_a_project_that_is_more_than_the_limit_is_refused_with_how_big_it_came_to(
        self, agents: PaperAgents, workspace: Workspace, source: Path
    ) -> None:
        (source / "data.bin").write_bytes(os.urandom(12 * 1024 * 1024))
        self.git(source, "add", "--all")
        self.git(source, "commit", "--quiet", "-m", "big")
        agent_id = agent_of(agents)

        job = fetch(agents, agent_id, max_megabytes=10)

        assert job.state == "failed" and "more than 10.0 MB" in job.error and "had come to" in job.error
        assert agents.view(agent_id)["steps"]["repository"] == "failed"
        assert {path.name for path in directory_of(workspace, agent_id).iterdir()} == {AGENT_FILE}
        assert not [path for path in workspace.root.iterdir() if path.name.startswith("paperagent.")]
