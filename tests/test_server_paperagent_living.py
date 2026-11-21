"""Tests of watching a PaperAgent: what a look at it finds and how that is said (healthy, degraded, broken, unchecked),
that a look changes nothing that is kept, a newer version of the code that is shown as a diff and taken only when the
person approves that commit, the schedule that the person sets, and what the other operations do while an agent is
looked at. Git, the package index, Docker, and the containers are replaced by stand-ins, as in the tests of making the
tools; what the watching does itself is in test_paperagents_watching."""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import test_server_paperagent_library as library_tests
import test_server_paperagent_tools as tools
from fastapi.testclient import TestClient
from test_paperagents_stock import tree
from test_server_paperagent_repository import (
    COMMIT,
    LOCAL,
    URL,
    Remote,
    directory_of,
    finish,
    refused,
)
from test_server_paperagent_tools import MAPPING

from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import repository as cloning
from virtual_lab.paperagents import watching
from virtual_lab.paperagents.repository import RepositoryError
from virtual_lab.server import paperagent_environment as kept_environment
from virtual_lab.server import paperagent_library as library
from virtual_lab.server import paperagent_living as living
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server.app import create_app
from virtual_lab.server.paperagents import HEALTH_JOB, REPOSITORY_JOB, PaperAgents, steps_of
from virtual_lab.server.workspace import Workspace

# What the tests of the library are made with, which are fixtures of that module and of the ones before it
agents = tools.agents
client = tools.client
containers = tools.containers
docker = tools.docker
git_is_installed = tools.git_is_installed
jobs = tools.jobs
marker = tools.marker
prepared = tools.prepared
referenced = tools.referenced
remote = tools.remote
replays = tools.replays
workspace = tools.workspace
made = library_tests.made
packages = library_tests.packages
Docker = tools.Docker
Containers = tools.Containers
Packages = library_tests.Packages

NEWER = "89abcdef" * 5
EVEN_NEWER = "76543210" * 5
SIX_HOURS = 6


class Source:
    """Stands in for asking where the code is now: it says what it is told, and what it was asked."""

    def __init__(self) -> None:
        self.state = watching.SAME
        self.commit: str | None = COMMIT
        self.asked: list[tuple[str, str, str]] = []

    def __call__(self, url: str, ref: str, commit: str, *rest: Any, **options: Any) -> watching.Probe:
        self.asked.append((url, ref, commit))

        return watching.Probe(self.state, self.commit, f"It is {self.state}.")


class Pins:
    """Stands in for the package index: each version is there unless it is said not to be."""

    def __init__(self) -> None:
        self.says: dict[tuple[str, str], str | None] = {}
        self.asked: list[tuple[str, str]] = []
        self.during: Any = None

    def status(self, name: str, version: str) -> str | None:
        self.asked.append((name, version))
        if self.during is not None:
            self.during()

        return self.says.get((name, version), watching.FOUND)


class Newer:
    """Stands in for fetching the code once it has moved: it gives the files it is given, as the commit it is at."""

    def __init__(self, files: dict[str, Any], commit: str = NEWER) -> None:
        self.files = files
        self.commit = commit
        self.calls: list[dict[str, Any]] = []
        self.error: BaseException | None = None

    def __call__(
        self, url: str, destination: Path, ref: str | None = None, max_bytes: int = 0, **options: Any
    ) -> cloning.Cloned:
        self.calls.append({"url": url, "ref": ref, "max_bytes": max_bytes, "options": sorted(options)})
        if self.error is not None:
            raise self.error
        tree(destination, self.files)

        return cloning.Cloned(self.commit, ref or "HEAD")


EDITED = MAPPING.replace("return counts", "return list(counts)")


@pytest.fixture
def source(agents: PaperAgents) -> Source:
    stand_in = Source()
    agents.probe_source = stand_in

    return stand_in


@pytest.fixture
def pins(agents: PaperAgents) -> Pins:
    stand_in = Pins()
    agents.pin_index = stand_in  # type: ignore[assignment]

    return stand_in


@pytest.fixture
def moved(remote: Remote, source: Source, monkeypatch: pytest.MonkeyPatch) -> Newer:
    """The code has moved: the source says so, and what is fetched of it is the files with the mapping edited."""
    source.state, source.commit = watching.MOVED, NEWER
    newer = Newer({**remote.files, "cellmapper/mapping.py": EDITED})
    monkeypatch.setattr(cloning, "clone", newer)

    return newer


def differing(
    names: set[str], status: str = "differs", differences: list[str] | None = None, message: str | None = None
) -> Any:
    """A play of the container in which the package's own check ran, and its report says that the tools it names gave
    something other than the tutorials got, as it would if the code or the environment had changed."""

    def play(folder: Path, package: Path) -> tuple[str, int | None, str]:
        ended, code, text = library_tests.run_check(folder, package)
        path = folder / library.REPORT_FILE
        report = json.loads(path.read_text())
        for tool in report["tools"]:
            if tool["name"] in names:
                tool["cases"] = [
                    {
                        **case,
                        "status": status,
                        "differences": ["got 13, the tutorial got 12"] if differences is None else differences,
                        "message": message,
                    }
                    for case in tool["cases"]
                ]
        report["ok"] = False
        path.write_text(json.dumps(report))

        return ended, 1, text

    return play


def look(agents: PaperAgents, agent_id: str) -> Any:
    return finish(agents.start_health(agent_id))


def found_of(agents: PaperAgents, agent_id: str) -> dict[str, Any]:
    found = agents.health(agent_id)["health"]
    assert found is not None

    return found


def kept_things(agents: PaperAgents, workspace: Workspace, agent_id: str) -> dict[str, Any]:
    """What is kept of an agent that a look must not change."""
    directory = directory_of(workspace, agent_id)
    _, agent = agents.lookup(agent_id)
    intake, built, kept = agents.library_pieces(directory, agent) or (None, None, None)

    return {
        "commit": intake["commit"] if intake else None,
        "ref": intake["ref"] if intake else None,
        "image": built["image"]["id"] if built else None,
        "tools": kept,
        "code": (kept_repository.repo_path(directory) / "cellmapper" / "mapping.py").read_text(),
        "steps": steps_of(agent),
        "repo": agent["repo"],
        "package": library.stored_export(directory),
    }


class TestWhatIsFound:
    def test_an_agent_that_was_not_looked_at_is_unchecked_and_has_nothing_found(
        self, agents: PaperAgents, made: str, source: Source
    ) -> None:
        shown = agents.health(made)

        assert shown["watchable"] is True and shown["health"] is None and shown["watch"] is None
        assert shown["update"] is None and shown["job"] is None and shown["meaning"]
        assert shown["version"] == {"commit": COMMIT, "ref": "HEAD", "url": URL}
        assert shown["limits"] == {"min_hours": 1, "max_hours": 24 * 90}
        (entry,) = agents.library()["agents"]
        assert entry["health"] == {
            "status": "unchecked",
            "checked_at": None,
            "update": False,
            "watched_every_hours": None,
        }
        assert source.asked == []

    def test_an_agent_whose_tools_give_again_what_their_tutorials_got_is_healthy(
        self, agents: PaperAgents, made: str, source: Source, pins: Pins, packages: Packages, workspace: Workspace
    ) -> None:
        job = look(agents, made)

        assert job.state == "succeeded" and job.kind == HEALTH_JOB, job.error
        assert job.message.startswith("Healthy: 2 tools gave again what their tutorials got")
        found = found_of(agents, made)
        assert found["status"] == "healthy" and found["reasons"] == []
        assert (
            found["commit"] == COMMIT
            and found["image_id"] == agents.library()["agents"][0]["environment"]["image"]["id"]
        )
        assert found["source"]["state"] == "same" and found["image"] == {"present": True}
        assert [(tool["name"], tool["matched"] == tool["calls"] >= 1) for tool in found["tools"]] == [
            ("map_cells", True),
            ("tally", True),
        ]
        assert found["history"] == [{"at": found["checked_at"], "status": "healthy"}]
        assert source.asked == [(URL, "HEAD", COMMIT)]
        (entry,) = agents.library()["agents"]
        assert entry["health"]["status"] == "healthy" and entry["health"]["checked_at"] == found["checked_at"]

    def test_the_tools_are_run_again_in_the_environment_that_is_kept_in_a_container_that_is_taken_away(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages, workspace: Workspace
    ) -> None:
        look(agents, made)

        (run,) = packages.runs
        assert run["tag"] == building.tag_of(made, COMMIT) and run["label"] == made
        assert run["argv"][:3] == ["python", f"{library.PACKAGE_AT}/mcp_server.py", "check"]
        assert not run["mounts"][0][0].exists() and not list(run["scratch"].glob("check-*"))

    def test_looking_changes_nothing_that_is_kept_and_makes_no_package(
        self, agents: PaperAgents, made: str, source: Source, pins: Pins, packages: Packages, workspace: Workspace
    ) -> None:
        before = kept_things(agents, workspace, made)

        look(agents, made)

        assert kept_things(agents, workspace, made) == before
        assert before["package"] is None
        assert not library.exports_path(directory_of(workspace, made)).exists()

    def test_a_conda_environment_says_that_its_versions_were_not_asked_of(
        self, agents: PaperAgents, made: str, source: Source, pins: Pins, packages: Packages
    ) -> None:
        look(agents, made)

        found = found_of(agents, made)
        assert found["dependencies"] is None and "conda" in found["dependencies_message"]
        assert pins.asked == []

    def test_a_tool_that_gives_something_else_makes_the_agent_degraded_and_says_which(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        packages.play = differing({"tally"})

        job = look(agents, made)

        found = found_of(agents, made)
        assert found["status"] == "degraded" and job.message.startswith("Degraded.")
        tally = next(tool for tool in found["tools"] if tool["name"] == "tally")
        assert tally["matched"] == 0 and tally["calls"] >= 1 and "got 13" in tally["message"]
        map_cells = next(tool for tool in found["tools"] if tool["name"] == "map_cells")
        assert map_cells["matched"] == map_cells["calls"] >= 1
        assert "tally" in found["reasons"][0] and "Some tools" in found["reasons"][0]

    def test_no_tool_that_gives_again_what_it_did_makes_it_broken(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        packages.play = differing({"tally", "map_cells"})

        look(agents, made)

        found = found_of(agents, made)
        assert found["status"] == "broken" and found["reasons"][-1].startswith("No tool gave again")
        assert {tool["matched"] for tool in found["tools"]} == {0}
        assert agents.library()["agents"][0]["health"]["status"] == "broken"

    def test_a_tool_that_errored_is_said_by_what_it_said(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        packages.play = differing({"tally"}, status="error", differences=[], message="ZeroDivisionError")

        look(agents, made)

        found = found_of(agents, made)
        assert found["status"] == "degraded"
        assert next(tool for tool in found["tools"] if tool["name"] == "tally")["message"] == "ZeroDivisionError"

    def test_a_package_whose_files_are_not_what_it_says_is_not_taken_as_the_tools_giving_again_what_they_did(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        def play(folder: Path, package: Path) -> tuple[str, int | None, str]:
            ended, code, text = library_tests.run_check(folder, package)
            path = folder / library.REPORT_FILE
            path.write_text(json.dumps({**json.loads(path.read_text()), "problems": ["a file is not what it says"]}))
            return ended, code, text

        packages.play = play

        look(agents, made)

        found = found_of(agents, made)
        assert found["status"] == "unchecked" and found["tools"] == []
        assert "a file is not what it says" in found["tools_message"]

    @pytest.mark.parametrize(
        ("play", "said"),
        [
            (lambda folder, package: ("timed_out", None, ""), "was stopped after"),
            (lambda folder, package: ("too_big", None, ""), "for writing more than"),
            (lambda folder, package: ("done", 1, "Traceback: boom"), "without a report"),
        ],
    )
    def test_a_check_that_gave_no_report_is_unchecked_and_is_not_every_tool_failing(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages, play: Any, said: str
    ) -> None:
        packages.play = play

        look(agents, made)

        found = found_of(agents, made)
        assert found["status"] == "unchecked" and found["tools"] == []
        assert found["tools_message"].startswith("The check did not report") and said in found["tools_message"]

    def test_a_report_that_is_of_another_package_is_not_taken_as_the_tools_giving_again_what_they_did(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        def play(folder: Path, package: Path) -> tuple[str, int | None, str]:
            ended, code, text = library_tests.run_check(folder, package)
            path = folder / library.REPORT_FILE
            path.write_text(json.dumps({**json.loads(path.read_text()), "name": "another"}))
            return ended, code, text

        packages.play = play

        look(agents, made)

        found = found_of(agents, made)
        assert found["status"] == "unchecked" and "another package" in found["tools_message"]

    def test_a_source_that_is_gone_makes_it_degraded_though_its_tools_work(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        source.state, source.commit = watching.GONE, None

        look(agents, made)

        found = found_of(agents, made)
        assert found["status"] == "degraded" and found["reasons"][0].startswith("The source is gone")
        assert all(tool["matched"] == tool["calls"] >= 1 for tool in found["tools"])

    @pytest.mark.parametrize("state", [watching.SAME, watching.UNKNOWN, watching.PINNED])
    def test_a_source_that_is_the_same_or_could_not_be_asked_or_is_one_commit_is_not_a_fault(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages, state: str
    ) -> None:
        source.state = state

        look(agents, made)

        assert found_of(agents, made)["status"] == "healthy"

    def test_an_image_that_is_gone_makes_it_broken_and_the_tools_are_not_run(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages, docker: Docker
    ) -> None:
        docker.images.clear()

        look(agents, made)

        found = found_of(agents, made)
        assert found["status"] == "broken" and found["image"] == {"present": False}
        assert packages.runs == [] and "not in Docker" in found["tools_message"]

    def test_docker_that_is_not_running_is_said_and_is_not_an_image_that_is_gone(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages, docker: Docker
    ) -> None:
        docker.usable = (False, "Docker is not running.")

        job = look(agents, made)

        found = found_of(agents, made)
        assert job.state == "succeeded" and found["status"] == "unchecked" and found["image"] == {"present": None}
        assert "Docker is not running" in found["tools_message"] and packages.runs == []
        assert agents.health(made)["docker"] == {"ready": False, "message": "Docker is not running."}

    def test_docker_that_does_not_answer_about_the_image_is_not_an_image_that_is_gone(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages, docker: Docker
    ) -> None:
        docker.unanswering = True

        look(agents, made)

        found = found_of(agents, made)
        assert found["status"] == "unchecked" and found["image"] == {"present": None}
        assert packages.runs == [] and "could not be asked" in found["tools_message"]

    def test_each_look_is_added_to_how_the_agent_has_been_and_the_last_ten_are_kept(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        for _ in range(living.HISTORY + 2):
            look(agents, made)
        source.state = watching.GONE

        look(agents, made)

        found = found_of(agents, made)
        assert len(found["history"]) == living.HISTORY
        assert [one["status"] for one in found["history"]] == ["healthy"] * (living.HISTORY - 1) + ["degraded"]

    def test_what_was_found_is_not_shown_for_another_commit_or_another_image(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages, workspace: Workspace
    ) -> None:
        look(agents, made)
        directory = directory_of(workspace, made)
        record = living.load_health(directory)
        _, agent = agents.lookup(made)
        intake, built, _ = agents.library_pieces(directory, agent)

        _, _, kept = agents.library_pieces(directory, agent)

        assert living.health_view(record, intake, built, kept) == record
        assert living.health_view(record, {**intake, "commit": NEWER}, built, kept) is None
        other_image = {**built, "image": {**built["image"], "id": "sha256:" + "f" * 64}}
        assert living.health_view(record, intake, other_image, kept) is None
        assert living.health_view(record, intake, built, {**kept, "started_at": "2001-01-01T00:00:00+00:00"}) is None
        assert living.health_view(record, intake, built, {**kept, "finished_at": "2001-01-01T00:00:00+00:00"}) is None
        assert living.health_view(None, intake, built, kept) is None
        assert living.health_view(record, None, None, None) is None
        assert living.health_view(record, intake, built, None) is None

    def test_what_was_found_is_not_shown_for_tools_that_were_made_again(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages, docker: Docker
    ) -> None:
        look(agents, made)
        assert agents.health(made)["health"] is not None
        directory = agents.workspace.paperagents_dir / made
        record = living.load_health(directory)

        agents.clear_tools(made)
        tools.make(agents, made)

        assert agents.health(made)["health"] is None
        assert agents.library()["agents"][0]["health"]["status"] == "unchecked"
        assert living.load_health(directory) == record


class TestPins:
    @pytest.fixture
    def pip_agent(
        self, agents: PaperAgents, remote: Remote, containers: Containers, replays: Any, docker: Docker
    ) -> str:
        return library_tests.made_without(
            agents, remote, containers, "environment.yml", {"requirements.txt": "numpy==1.26.4\nsix==1.16.0\n"}
        )

    def test_the_versions_that_a_pip_lock_pins_are_asked_of_the_index(
        self, agents: PaperAgents, pip_agent: str, source: Source, pins: Pins, packages: Packages
    ) -> None:
        look(agents, pip_agent)

        found = found_of(agents, pip_agent)
        assert pins.asked == [("numpy", "1.26.4"), ("six", "1.16.0")]
        assert found["dependencies"] == {"kind": "pip", "total": 2, "looked_at": 2, "unsaid": 0, "problems": []}
        assert found["status"] == "healthy"

    def test_a_version_that_is_gone_or_was_yanked_makes_it_degraded_and_is_named(
        self, agents: PaperAgents, pip_agent: str, source: Source, pins: Pins, packages: Packages
    ) -> None:
        pins.says = {("numpy", "1.26.4"): watching.MISSING, ("six", "1.16.0"): watching.YANKED}

        look(agents, pip_agent)

        found = found_of(agents, pip_agent)
        assert found["status"] == "degraded"
        assert [(one["name"], one["state"]) for one in found["dependencies"]["problems"]] == [
            ("numpy", "missing"),
            ("six", "yanked"),
        ]
        assert "numpy==1.26.4 (missing)" in found["reasons"][0]

    def test_a_version_that_the_index_did_not_say_of_is_counted_and_is_not_a_fault(
        self, agents: PaperAgents, pip_agent: str, source: Source, pins: Pins, packages: Packages
    ) -> None:
        pins.says = {("numpy", "1.26.4"): None}

        look(agents, pip_agent)

        found = found_of(agents, pip_agent)
        assert found["status"] == "healthy" and found["dependencies"]["unsaid"] == 1

    def test_a_look_that_is_stopped_while_the_index_is_asked_keeps_nothing_and_runs_no_tool(
        self, agents: PaperAgents, pip_agent: str, source: Source, pins: Pins, packages: Packages, workspace: Workspace
    ) -> None:
        pins.during = lambda: agents.jobs.active(HEALTH_JOB)[0].request_stop()

        job = finish(agents.start_health(pip_agent))

        assert job.state == "stopped" and len(pins.asked) == 1
        assert living.load_health(directory_of(workspace, pip_agent)) is None and packages.runs == []


class TestANewerVersion:
    def test_the_code_that_has_moved_is_fetched_to_be_shown_and_what_is_kept_is_not_changed(
        self, agents: PaperAgents, made: str, moved: Newer, pins: Pins, packages: Packages, workspace: Workspace
    ) -> None:
        before = kept_things(agents, workspace, made)

        job = look(agents, made)

        assert job.state == "succeeded" and "A newer version of the code is proposed" in job.message
        assert "89abcde" in job.message and "Nothing was changed." in job.message
        assert [call["ref"] for call in moved.calls] == ["HEAD"]
        assert kept_things(agents, workspace, made) == before
        shown = agents.update(made)
        update = shown["update"]
        assert update["from_commit"] == COMMIT and update["to_commit"] == NEWER
        assert update["diff"]["changed"] == 1 and update["affects"] == ["map_cells", "tally"]
        assert update["environment_files"] == []
        (changed,) = update["diff"]["files"]
        assert changed["path"] == "cellmapper/mapping.py" and changed["change"] == "changed"
        assert "-    return counts" in changed["diff"] and "+    return list(counts)" in changed["diff"]
        assert "stay as they are" in shown["pinned"] and shown["version"]["commit"] == COMMIT

    def test_a_look_that_is_stopped_while_the_newer_version_is_compared_keeps_no_proposal(
        self,
        agents: PaperAgents,
        made: str,
        moved: Newer,
        packages: Packages,
        workspace: Workspace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        compare = watching.diff_trees

        def stopping(old: Path, new: Path, should_stop: Any = None) -> Any:
            agents.jobs.active(HEALTH_JOB)[0].request_stop()
            return compare(old, new, should_stop)

        monkeypatch.setattr(watching, "diff_trees", stopping)

        job = look(agents, made)

        assert job.state == "stopped"
        directory = directory_of(workspace, made)
        assert living.load_update(directory) is None and living.load_health(directory) is None

    def test_the_agent_is_still_as_healthy_as_its_kept_version_is_and_a_newer_version_is_not_a_state(
        self, agents: PaperAgents, made: str, moved: Newer, pins: Pins, packages: Packages
    ) -> None:
        look(agents, made)

        assert found_of(agents, made)["status"] == "healthy"
        summary = agents.library()["agents"][0]["health"]
        assert summary["status"] == "healthy" and summary["update"] is True
        shown = agents.health(made)["update"]
        assert shown["to_commit"] == NEWER and shown["changed"] == 1 and "diff" not in shown
        assert found_of(agents, made)["source"]["state"] == "moved"

    def test_the_files_of_the_environment_that_changed_are_said(
        self, agents: PaperAgents, made: str, remote: Remote, source: Source, packages: Packages, monkeypatch: Any
    ) -> None:
        source.state, source.commit = watching.MOVED, NEWER
        newer = Newer({**remote.files, "environment.yml": "name: x\ndependencies:\n  - python=3.12\n"})
        monkeypatch.setattr(cloning, "clone", newer)

        look(agents, made)

        update = agents.update(made)["update"]
        assert update["environment_files"] == ["environment.yml"] and update["affects"] == []

    def test_a_proposal_that_was_made_is_not_fetched_again_for_the_same_commit(
        self, agents: PaperAgents, made: str, moved: Newer, packages: Packages
    ) -> None:
        look(agents, made)
        look(agents, made)

        assert len(moved.calls) == 1
        assert agents.update(made)["update"]["to_commit"] == NEWER

    def test_a_commit_after_that_replaces_the_proposal(
        self, agents: PaperAgents, made: str, moved: Newer, source: Source, packages: Packages
    ) -> None:
        look(agents, made)
        source.commit = EVEN_NEWER
        moved.commit = EVEN_NEWER

        look(agents, made)

        assert len(moved.calls) == 2 and agents.update(made)["update"]["to_commit"] == EVEN_NEWER

    def test_a_proposal_goes_when_the_code_is_found_to_be_where_it_was_fetched_from_again(
        self, agents: PaperAgents, made: str, moved: Newer, source: Source, packages: Packages
    ) -> None:
        look(agents, made)
        source.state, source.commit = watching.SAME, COMMIT

        look(agents, made)

        assert agents.update(made)["update"] is None

    def test_a_proposal_is_not_kept_when_the_fetching_of_the_code_gave_the_commit_that_is_kept(
        self, agents: PaperAgents, made: str, moved: Newer, packages: Packages
    ) -> None:
        moved.commit = COMMIT

        look(agents, made)

        assert agents.update(made)["update"] is None

    def test_code_that_could_not_be_fetched_is_said_and_does_not_end_the_look(
        self, agents: PaperAgents, made: str, moved: Newer, packages: Packages
    ) -> None:
        moved.error = RepositoryError("Git could not reach github.com.")

        job = look(agents, made)

        assert job.state == "succeeded"
        found = found_of(agents, made)
        assert found["source"]["state"] == "moved" and "reach github.com" in found["source"]["update_error"]
        assert agents.update(made)["update"] is None and found["status"] == "healthy"

    def test_a_proposal_is_dismissed_and_is_proposed_again_at_the_next_look(
        self, agents: PaperAgents, made: str, moved: Newer, packages: Packages
    ) -> None:
        look(agents, made)

        shown = agents.dismiss_update(made)

        assert shown["update"] is None
        assert agents.library()["agents"][0]["health"]["update"] is False
        look(agents, made)
        assert agents.update(made)["update"]["to_commit"] == NEWER

    def test_a_proposal_is_of_the_commit_that_is_kept_and_the_address_it_was_fetched_from(
        self, agents: PaperAgents, made: str, moved: Newer, packages: Packages, workspace: Workspace
    ) -> None:
        look(agents, made)
        record = living.load_update(directory_of(workspace, made))
        intake = {"commit": COMMIT, "url": URL}

        assert living.update_view(record, intake) == record
        assert living.update_view(record, {**intake, "commit": NEWER}) is None
        assert living.update_view(record, {**intake, "url": "https://github.com/other/cellmapper"}) is None
        assert living.update_view(None, intake) is None and living.update_view(record, None) is None


class TestApprovingIt:
    def test_the_commit_that_the_person_approves_is_fetched_and_replaces_what_is_kept_and_what_was_made_of_it_goes(
        self, agents: PaperAgents, made: str, moved: Newer, packages: Packages, workspace: Workspace
    ) -> None:
        look(agents, made)
        directory = directory_of(workspace, made)

        job = finish(agents.apply_update(made, NEWER))

        assert job.state == "succeeded" and job.kind == REPOSITORY_JOB, job.error
        assert moved.calls[-1]["ref"] == NEWER
        _, agent = agents.lookup(made)
        assert agent["repo"] == {"url": URL, "ref": "HEAD", "commit": NEWER}
        intake = kept_repository.load(directory, URL)
        assert intake["commit"] == NEWER and intake["ref"] == "HEAD"
        assert (kept_repository.repo_path(directory) / "cellmapper" / "mapping.py").read_text() == EDITED
        assert steps_of(agent)["repository"] == "done"
        assert steps_of(agent)["environment"] == "pending" and steps_of(agent)["tools"] == "pending"
        assert kept_environment.stored(directory) is None
        assert agents.library()["agents"] == []
        assert agents.update(made)["update"] is None
        assert living.load_health(directory) is None and living.load_update(directory) is None

    def test_the_schedule_is_kept_when_a_newer_version_is_taken(
        self, agents: PaperAgents, made: str, moved: Newer, packages: Packages, workspace: Workspace
    ) -> None:
        agents.set_watch(made, SIX_HOURS)
        look(agents, made)

        finish(agents.apply_update(made, NEWER))

        assert living.load_watch(directory_of(workspace, made))["every_hours"] == SIX_HOURS

    def test_a_commit_that_is_not_the_one_that_was_proposed_is_not_taken(
        self, agents: PaperAgents, made: str, moved: Newer, packages: Packages, workspace: Workspace
    ) -> None:
        look(agents, made)
        before = kept_things(agents, workspace, made)
        calls = len(moved.calls)

        error = refused(agents.apply_update, made, EVEN_NEWER)

        assert error.status == 409 and error.code == "changed"
        assert len(moved.calls) == calls and kept_things(agents, workspace, made) == before
        assert agents.update(made)["update"]["to_commit"] == NEWER

    def test_nothing_is_taken_when_none_is_proposed(self, agents: PaperAgents, made: str, source: Source) -> None:
        error = refused(agents.apply_update, made, NEWER)

        assert error.status == 409 and error.code == "no_update"

    def test_nothing_is_taken_that_was_put_aside(
        self, agents: PaperAgents, made: str, moved: Newer, packages: Packages
    ) -> None:
        look(agents, made)
        agents.dismiss_update(made)

        assert refused(agents.apply_update, made, NEWER).code == "no_update"

    @pytest.mark.parametrize("value", [None, 5, "abc1234", NEWER[:39], NEWER + "0", NEWER.upper(), "HEAD", ["x"]])
    def test_the_commit_has_to_be_given_in_full(self, agents: PaperAgents, made: str, value: Any) -> None:
        error = refused(agents.apply_update, made, value)

        assert error.status == 422 and error.code == "invalid"

    def test_an_agent_that_is_not_there_has_nothing_to_take(self, agents: PaperAgents) -> None:
        assert refused(agents.apply_update, "nothing", NEWER).status == 404
        assert refused(agents.update, "nothing").status == 404
        assert refused(agents.dismiss_update, "nothing").status == 404

    def test_a_newer_version_that_cannot_be_fetched_leaves_what_is_kept_as_it_was(
        self, agents: PaperAgents, made: str, moved: Newer, packages: Packages, workspace: Workspace
    ) -> None:
        look(agents, made)
        before = kept_things(agents, workspace, made)
        moved.error = RepositoryError("Git could not reach github.com.")

        job = finish(agents.apply_update(made, NEWER))

        assert job.state == "failed" and "github.com" in (job.error or "")
        assert kept_things(agents, workspace, made) == before
        assert agents.update(made)["update"]["to_commit"] == NEWER


class TestTheSchedule:
    def test_how_often_it_is_looked_at_is_kept_and_shown(
        self, agents: PaperAgents, made: str, source: Source, workspace: Workspace
    ) -> None:
        shown = agents.set_watch(made, SIX_HOURS)

        assert shown["watch"]["every_hours"] == SIX_HOURS and shown["watch"]["last_started_at"] is None
        assert agents.library()["agents"][0]["health"]["watched_every_hours"] == SIX_HOURS
        assert (
            json.loads((living.living_path(directory_of(workspace, made)) / living.WATCH_FILE).read_text())["schema"]
            == 1
        )

    def test_the_hours_are_changed_without_losing_when_it_was_last_started(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        agents.set_watch(made, SIX_HOURS)
        agents.start_due_checks()
        started = agents.health(made)["watch"]["last_started_at"]

        shown = agents.set_watch(made, 12)

        assert shown["watch"]["every_hours"] == 12 and shown["watch"]["last_started_at"] == started

    @pytest.mark.parametrize("value", [0, -1, living.MAX_HOURS + 1, True, 1.5, "6", None, [6]])
    def test_the_hours_are_a_whole_number_within_the_range(self, agents: PaperAgents, made: str, value: Any) -> None:
        error = refused(agents.set_watch, made, value)

        assert error.status == 422 and error.code == "invalid"
        assert agents.health(made)["watch"] is None

    @pytest.mark.parametrize("value", [living.MIN_HOURS, living.MAX_HOURS])
    def test_the_least_and_the_most_are_allowed(self, agents: PaperAgents, made: str, value: int) -> None:
        assert agents.set_watch(made, value)["watch"]["every_hours"] == value

    def test_an_agent_with_no_tools_is_not_looked_at_on_a_schedule(self, agents: PaperAgents, prepared: str) -> None:
        assert refused(agents.set_watch, prepared, SIX_HOURS).code == "no_tools"
        assert refused(agents.start_health, prepared).code == "no_tools"
        assert agents.health(prepared)["watchable"] is False and agents.health(prepared)["health"] is None

    def test_an_agent_that_is_not_there_is_not_watched(self, agents: PaperAgents) -> None:
        for call in (
            lambda: agents.set_watch("nothing", 6),
            lambda: agents.clear_watch("nothing"),
            lambda: agents.health("nothing"),
        ):
            assert refused(call).status == 404
        assert refused(agents.start_health, "nothing").status == 404

    def test_stopping_the_schedule_leaves_what_was_found(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        agents.set_watch(made, SIX_HOURS)
        look(agents, made)

        shown = agents.clear_watch(made)

        assert shown["watch"] is None and shown["health"]["status"] == "healthy"
        assert agents.start_due_checks(datetime.now(timezone.utc) + timedelta(days=30)) == []

    def test_an_agent_that_has_a_schedule_is_looked_at_when_the_server_checks_and_not_before_the_hours_have_passed(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        agents.set_watch(made, SIX_HOURS)
        now = datetime.now(timezone.utc)

        started = agents.start_due_checks(now)
        assert started == [made]
        finish(agents.health_job(made)) if agents.health_job(made) else None
        assert agents.start_due_checks(now + timedelta(hours=5, minutes=59)) == []
        assert agents.start_due_checks(now + timedelta(hours=6, minutes=1)) == [made]
        finish(agents.health_job(made)) if agents.health_job(made) else None
        assert found_of(agents, made)["status"] == "healthy" and len(found_of(agents, made)["history"]) >= 1

    def test_an_agent_that_has_no_schedule_is_not_looked_at_by_it(
        self, agents: PaperAgents, made: str, source: Source
    ) -> None:
        assert agents.start_due_checks(datetime.now(timezone.utc) + timedelta(days=400)) == []
        assert source.asked == []

    def test_an_agent_that_is_being_worked_on_is_left_and_looked_at_next_time(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        agents.set_watch(made, SIX_HOURS)
        packages.gate = threading.Event()
        job = agents.start_health(made)
        assert packages.began.wait(10)

        started = agents.health(made)["watch"]["last_started_at"]

        assert agents.start_due_checks(datetime.now(timezone.utc) + timedelta(days=1)) == []
        assert agents.health(made)["watch"]["last_started_at"] == started

        packages.gate.set()
        finish(job)
        assert agents.start_due_checks(datetime.now(timezone.utc) + timedelta(days=1)) == [made]

    def test_the_loop_that_the_server_runs_looks_at_what_is_due_and_goes_on_after_a_failure(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agents.set_watch(made, SIX_HOURS)
        real = agents.start_due_checks
        calls: list[int] = []

        def start_due_checks(now: Any = None) -> list[str]:
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("one failed")
            return real(now)

        monkeypatch.setattr(agents, "start_due_checks", start_due_checks)
        stopping = threading.Event()
        thread = threading.Thread(target=agents.watch_schedules, args=(stopping, 0.01), daemon=True)
        thread.start()
        deadline = time.monotonic() + 20
        while not packages.runs and time.monotonic() < deadline:
            time.sleep(0.01)
        stopping.set()
        thread.join(10)

        assert not thread.is_alive() and len(calls) >= 2 and packages.runs

    def test_the_loop_ends_when_it_is_told_to_stop(self, agents: PaperAgents) -> None:
        stopping = threading.Event()
        thread = threading.Thread(target=agents.watch_schedules, args=(stopping, 3600), daemon=True)
        thread.start()

        stopping.set()
        thread.join(10)

        assert not thread.is_alive()


class TestWhenItIsDue:
    @staticmethod
    def watch(last: str | None, hours: int = 2) -> dict[str, Any]:
        return {"every_hours": hours, "last_started_at": last}

    NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)

    def test_it_is_due_when_it_never_was_started(self) -> None:
        assert living.is_due(self.watch(None), self.NOW) is True

    def test_it_is_due_once_the_hours_have_passed_and_not_before(self) -> None:
        assert living.is_due(self.watch((self.NOW - timedelta(hours=2)).isoformat()), self.NOW) is True
        assert living.is_due(self.watch((self.NOW - timedelta(hours=2, seconds=-1)).isoformat()), self.NOW) is False
        assert living.is_due(self.watch((self.NOW + timedelta(hours=1)).isoformat()), self.NOW) is False

    def test_a_time_that_cannot_be_read_is_a_look_that_is_due(self) -> None:
        assert living.is_due(self.watch("yesterday"), self.NOW) is True
        assert living.is_due(self.watch(""), self.NOW) is True

    def test_a_time_with_no_zone_is_taken_as_utc(self) -> None:
        assert living.is_due(self.watch("2030-01-01T09:00:00"), self.NOW) is True
        assert living.is_due(self.watch("2030-01-01T11:00:00"), self.NOW) is False

    def test_no_schedule_is_never_due(self) -> None:
        assert living.is_due(None, self.NOW) is False


class TestWhileItIsLookedAt:
    def test_nothing_that_changes_what_is_looked_at_is_done_and_it_is_not_looked_at_twice(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        packages.gate = threading.Event()
        job = agents.start_health(made)
        assert packages.began.wait(10)

        assert agents.health(made)["job"]["id"] == job.id
        for action in (
            lambda: agents.start_health(made),
            lambda: agents.start_export(made),
            lambda: agents.apply_update(made, NEWER),
            lambda: agents.clear_export(made),
            lambda: agents.clear_tools(made),
            lambda: agents.clear_reference(made),
            lambda: agents.clear_environment(made),
            lambda: agents.clear_repository(made),
            lambda: agents.start_tools(made),
            lambda: agents.delete(made),
        ):
            error = refused(action)
            assert error.status == 409 and error.code == "busy", action

        packages.gate.set()
        finish(job)
        assert job.state == "succeeded" and agents.health(made)["job"] is None

    def test_what_is_set_and_read_is_not_held_up_by_it(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        packages.gate = threading.Event()
        job = agents.start_health(made)
        assert packages.began.wait(10)

        assert agents.set_watch(made, SIX_HOURS)["watch"]["every_hours"] == SIX_HOURS
        assert agents.clear_watch(made)["watch"] is None
        assert agents.library()["agents"][0]["id"] == made and agents.update(made)["update"] is None

        packages.gate.set()
        finish(job)

    def test_a_look_that_is_stopped_keeps_nothing(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages, workspace: Workspace
    ) -> None:
        packages.gate = threading.Event()
        job = agents.start_health(made)
        assert packages.began.wait(10)

        job.request_stop()
        finish(job)

        assert job.state == "stopped"
        assert living.load_health(directory_of(workspace, made)) is None
        assert agents.health(made)["health"] is None and agents.health(made)["job"] is None

    def test_a_look_that_is_stopped_once_the_tools_were_run_keeps_nothing_either(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages, workspace: Workspace
    ) -> None:
        def play(folder: Path, package: Path) -> tuple[str, int | None, str]:
            done = library_tests.run_check(folder, package)
            agents.jobs.active(HEALTH_JOB)[0].request_stop()
            return done

        packages.play = play

        job = finish(agents.start_health(made))

        assert job.state == "stopped" and living.load_health(directory_of(workspace, made)) is None

    def test_the_look_is_given_to_the_job_as_it_goes(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages
    ) -> None:
        job = look(agents, made)

        assert job.title == "Looking at the agent: CellMapper"


class TestWhatGoesWithWhatIsWatched:
    def test_taking_the_environment_away_takes_how_it_was_found_and_not_the_schedule_or_a_proposal(
        self, agents: PaperAgents, made: str, moved: Newer, packages: Packages, workspace: Workspace
    ) -> None:
        agents.set_watch(made, SIX_HOURS)
        look(agents, made)
        directory = directory_of(workspace, made)

        agents.clear_environment(made)

        assert living.load_health(directory) is None
        assert living.load_watch(directory)["every_hours"] == SIX_HOURS

    def test_taking_the_code_away_takes_a_proposal_for_it(
        self, agents: PaperAgents, made: str, moved: Newer, packages: Packages, workspace: Workspace
    ) -> None:
        look(agents, made)
        directory = directory_of(workspace, made)
        assert living.load_update(directory) is not None

        agents.clear_repository(made)

        assert living.load_update(directory) is None and living.load_health(directory) is None

    def test_an_agent_that_is_removed_takes_what_was_found_with_it(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages, workspace: Workspace
    ) -> None:
        agents.set_watch(made, SIX_HOURS)
        look(agents, made)

        agents.delete(made)

        assert not directory_of(workspace, made).exists()
        assert agents.start_due_checks(datetime.now(timezone.utc) + timedelta(days=30)) == []

    def test_a_record_that_was_edited_to_be_something_else_is_not_believed(
        self, agents: PaperAgents, made: str, source: Source, packages: Packages, workspace: Workspace
    ) -> None:
        look(agents, made)
        directory = directory_of(workspace, made)
        path = living.living_path(directory) / living.HEALTH_FILE
        record = json.loads(path.read_text())

        for changed in (
            {**record, "status": 5},
            {**record, "schema": 2},
            {key: value for key, value in record.items() if key != "tools"},
            [record],
        ):
            path.write_text(json.dumps(changed))
            assert living.load_health(directory) is None
        path.write_text("{not json")
        assert living.load_health(directory) is None
        path.write_text(json.dumps(record))
        assert living.load_health(directory) == record
        elsewhere = directory / "elsewhere.json"
        path.rename(elsewhere)
        path.symlink_to(elsewhere)
        assert living.load_health(directory) is None

    def test_a_schedule_that_was_edited_to_be_out_of_range_is_not_followed(
        self, agents: PaperAgents, made: str, source: Source, workspace: Workspace
    ) -> None:
        agents.set_watch(made, SIX_HOURS)
        directory = directory_of(workspace, made)
        path = living.living_path(directory) / living.WATCH_FILE
        record = json.loads(path.read_text())

        for hours in (0, living.MAX_HOURS + 1, -5):
            path.write_text(json.dumps({**record, "every_hours": hours}))
            assert living.load_watch(directory) is None
        assert agents.start_due_checks(datetime.now(timezone.utc) + timedelta(days=400)) == []


class TestEachToolAsItWasRun:
    def checked(self, examples: int, cases: list[dict[str, Any]], reason: str | None = None) -> Any:
        manifest = {"tools": [{"name": "a", "examples": [{}] * examples}]}
        report = {"tools": [{"name": "a", "cases": cases}]}

        return SimpleNamespace(manifest=manifest, report=report, reason=reason)

    @staticmethod
    def case(number: int, status: str = "match", differences: list[str] | None = None) -> dict[str, Any]:
        return {"case": number, "status": status, "differences": differences or [], "message": None, "seconds": 1}

    def test_a_tool_is_held_to_the_most_calls_that_the_check_makes_and_not_to_all_that_were_recorded(self) -> None:
        cases = [self.case(number) for number in range(library.MAX_CASES)]

        (found,) = living.tools_found(self.checked(library.MAX_CASES + 2, cases))

        assert found == {"name": "a", "calls": library.MAX_CASES, "matched": library.MAX_CASES, "message": None}

    def test_the_first_call_that_differed_is_said_by_what_differed(self) -> None:
        cases = [self.case(0), self.case(1, "differs", ["got 2, not 1", "other"]), self.case(2, "error")]

        (found,) = living.tools_found(self.checked(3, cases))

        assert (found["calls"], found["matched"], found["message"]) == (3, 1, "got 2, not 1; other")

    def test_a_tool_that_the_report_does_not_name_has_matched_none_and_says_why_the_check_did_not_pass(self) -> None:
        checked = self.checked(2, [], "Its check was stopped.")
        checked.report = {"tools": []}

        (found,) = living.tools_found(checked)

        assert found == {"name": "a", "calls": 2, "matched": 0, "message": "Its check was stopped."}


class TestWhatIsSaidOfIt:
    def test_a_healthy_look_says_how_many_tools_gave_again_what_they_did(self) -> None:
        tools = [{"name": "a", "calls": 1, "matched": 1}, {"name": "b", "calls": 0, "matched": 0}]

        assert living.summary_of("healthy", [], tools, None) == "Healthy: 1 tool gave again what their tutorials got."

    def test_the_first_reason_is_what_a_look_that_is_not_healthy_says(self) -> None:
        assert living.summary_of("broken", ["first", "second"], [], None) == "Broken. first"
        assert living.summary_of("unchecked", [], None, None) == "Unchecked."

    def test_a_proposal_is_said_with_the_commits_and_that_nothing_was_changed(self) -> None:
        proposal = {"from_commit": "a" * 40, "to_commit": "b" * 40, "diff": {"changed": 1}}

        said = living.summary_of("healthy", [], [], proposal)

        assert "aaaaaaa to bbbbbbb, 1 file changed" in said and said.endswith("Nothing was changed.")
        proposal["diff"]["changed"] = 3
        assert "3 files changed" in living.summary_of("healthy", [], [], proposal)


class TestOverHttp:
    def test_it_is_looked_at_watched_and_a_newer_version_is_shown_and_taken(
        self,
        client: TestClient,
        remote: Remote,
        docker: Docker,
        containers: Containers,
        replays: Any,
        packages: Packages,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        agent_id = library_tests.made_over_http(client, remote, containers)
        base = f"/api/paperagents/{agent_id}"
        source = Source()
        client.app.state.paperagents.probe_source = source

        shown = client.get(f"{base}/health")
        assert shown.status_code == 200 and shown.json()["health"] is None and shown.json()["watchable"] is True
        assert client.get("/api/paperagents/library").json()["agents"][0]["health"]["status"] == "unchecked"

        started = client.post(f"{base}/health")
        assert started.status_code == 202 and started.json()["kind"] == HEALTH_JOB
        library_tests.wait_for_job(client, started.json()["id"])
        assert client.get(f"{base}/health").json()["health"]["status"] == "healthy"

        watched = client.put(f"{base}/watch", json={"every_hours": SIX_HOURS})
        assert watched.status_code == 200 and watched.json()["watch"]["every_hours"] == SIX_HOURS

        source.state, source.commit = watching.MOVED, NEWER
        monkeypatch.setattr(cloning, "clone", Newer({**remote.files, "cellmapper/mapping.py": EDITED}))
        again = client.post(f"{base}/health")
        library_tests.wait_for_job(client, again.json()["id"])
        update = client.get(f"{base}/update").json()["update"]
        assert update["to_commit"] == NEWER and update["diff"]["changed"] == 1

        wrong = client.post(f"{base}/update/apply", json={"commit": EVEN_NEWER})
        assert wrong.status_code == 409 and wrong.json()["error"]["code"] == "changed"
        taken = client.post(f"{base}/update/apply", json={"commit": NEWER})
        assert taken.status_code == 202 and taken.json()["kind"] == REPOSITORY_JOB
        library_tests.wait_for_job(client, taken.json()["id"])
        assert client.get(f"{base}/update").json()["update"] is None
        assert client.get("/api/paperagents/library").json()["agents"] == []

        stopped = client.delete(f"{base}/watch")
        assert stopped.status_code == 200 and stopped.json()["watch"] is None

    def test_a_proposal_is_dismissed(
        self,
        client: TestClient,
        remote: Remote,
        docker: Docker,
        containers: Containers,
        replays: Any,
        packages: Packages,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        agent_id = library_tests.made_over_http(client, remote, containers)
        base = f"/api/paperagents/{agent_id}"
        source = Source()
        source.state, source.commit = watching.MOVED, NEWER
        client.app.state.paperagents.probe_source = source
        monkeypatch.setattr(cloning, "clone", Newer({**remote.files, "cellmapper/mapping.py": EDITED}))
        library_tests.wait_for_job(client, client.post(f"{base}/health").json()["id"])
        assert client.get(f"{base}/update").json()["update"] is not None

        gone = client.delete(f"{base}/update")

        assert gone.status_code == 200 and gone.json()["update"] is None

    def test_a_body_that_is_not_what_is_asked_for_is_refused(
        self, client: TestClient, docker: Docker, containers: Containers, remote: Remote, replays: Any
    ) -> None:
        agent_id = library_tests.made_over_http(client, remote, containers)
        base = f"/api/paperagents/{agent_id}"

        for body in (
            {},
            {"every_hours": "6"},
            {"every_hours": 1.5},
            {"every_hours": True},
            {"every_hours": None},
            {"every_hours": 6, "x": 1},
        ):
            assert client.put(f"{base}/watch", json=body).status_code == 422, body
        for body in ({"every_hours": 0}, {"every_hours": living.MAX_HOURS + 1}):
            error = client.put(f"{base}/watch", json=body)
            assert error.status_code == 422 and error.json()["error"]["code"] == "invalid", body
        for body in ({}, {"commit": 5}, {"commit": None}, {"commit": "x" * 101}, {"commit": NEWER, "x": 1}):
            assert client.post(f"{base}/update/apply", json=body).status_code == 422, body
        assert client.post(f"{base}/update/apply", json={"commit": "abc"}).json()["error"]["code"] == "invalid"

    def test_it_is_not_there_without_the_token_or_for_an_agent_that_is_not(self, client: TestClient) -> None:
        for method, path, body in (
            ("get", "health", None),
            ("post", "health", None),
            ("put", "watch", {"every_hours": 6}),
            ("delete", "watch", None),
            ("get", "update", None),
            ("post", "update/apply", {"commit": NEWER}),
            ("delete", "update", None),
        ):
            url = f"/api/paperagents/nothing/{path}"
            assert getattr(client, method)(url, **({"json": body} if body is not None else {})).status_code == 404, url
            bare = TestClient(client.app, base_url=LOCAL)
            assert getattr(bare, method)(url, **({"json": body} if body is not None else {})).status_code == 401, url

    def test_the_server_looks_at_what_is_due_while_it_runs_and_stops_when_it_does(self, workspace: Workspace) -> None:
        app = create_app(workspace.root, token="the-token", check_keys=False, max_upload_bytes=100_000)

        def running() -> bool:
            return any(thread.name == "paperagent-schedule" and thread.is_alive() for thread in threading.enumerate())

        assert not running()
        with TestClient(app, base_url=LOCAL, headers={"Authorization": "Bearer the-token"}):
            assert running()
        deadline = time.monotonic() + 10
        while running() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not running()
