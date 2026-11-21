"""Tests of writing a function from the words of a paper that has none of its code, as the server does it: that the
person is shown the exact words the model would be given, which a program and never the model chooses, and agrees to
them by a key that is bound to them, that what is agreed to is what is sent or nothing is, that the writing keeps what
it cost whether a function came of it or not, that the model is asked to write from the paper's words and nothing else,
in a container with no network, and that what was written is shown with its code and is bound to the paper it is of.
The container the function is imported in is a stand-in, so what is looked at is what the server does with what it
says."""

import hashlib
import io
import json
import threading
from typing import Any

import pytest
import test_server_paperagent_environment as environment
from conftest import TEST_MODEL, FakeClient, text_response
from test_paperagents_reading import queue, reading
from test_server_paperagent_environment import Docker, agent_of, directory_of, finish
from test_server_paperagent_repository import refused

from virtual_lab.execution import DockerUnavailableError, ExecutionResult
from virtual_lab.paperagents import reimplementing
from virtual_lab.paperagents.reading import ReadClaim
from virtual_lab.server import paperagent_reimplementation as kept
from virtual_lab.server import paperagents as module
from virtual_lab.server.paperagents import PaperAgents
from virtual_lab.server.workspace import Workspace

agents = environment.agents
client = environment.client
docker = environment.docker
jobs = environment.jobs
workspace = environment.workspace

TITLE = "Adding and doubling: a method"
ABSTRACT = "We present a method that adds numbers and doubles them."
METHODS = "We take the numbers, add them one to another, and double the sum. The detail is left to the reader."
RESULTS = "The method reached 0.93 on the held-out set of sums."
PAPER = "\n\n".join(
    [
        TITLE,
        "Abstract",
        ABSTRACT,
        "Methods",
        METHODS,
        "Results",
        RESULTS,
        "References",
        "Smith, J. (2020). A paper.",
    ]
)

CODE = '''```python
def reimplemented_adding_and_doubling_a_method(numbers: list) -> float:
    """Adds the numbers and doubles the sum.

    :param numbers: The numbers to add and double.
    :return: The sum of the numbers, doubled.
    """
    return 2 * sum(numbers)
```'''


class Import:
    """Stands in for the container that the written function is imported in, and keeps how it was made."""

    def __init__(self, exit_code: int = 0, error: BaseException | None = None) -> None:
        self.exit_code = exit_code
        self.error = error
        self.options: dict[str, Any] = {}
        self.calls: list[tuple[str, ...]] = []
        self.gate: threading.Event | None = None

    def make(self, **options: Any) -> "Import":
        self.options = options

        return self

    def run(self, directory: Any, command: Any, timeout: Any = None) -> ExecutionResult:
        self.calls.append(tuple(command))
        if self.gate is not None:
            self.gate.wait(20)
        if self.error is not None:
            raise self.error

        return ExecutionResult(command=tuple(command), exit_code=self.exit_code, stdout="", stderr="", duration=0.1)


@pytest.fixture
def importer(monkeypatch: pytest.MonkeyPatch) -> Import:
    stand_in = Import()
    monkeypatch.setattr(module, "DockerExecutor", stand_in.make)

    return stand_in


def read_paper(agents: PaperAgents, agent_id: str, fake_client: FakeClient, claim: bool = True) -> None:
    agents.put_paper(agent_id, "paper.txt", io.BytesIO(PAPER.encode("utf-8")))
    answers = reading(claims=[ReadClaim(kind="number", value="0.93", quote=RESULTS)] if claim else [])
    queue(fake_client, answers)
    job = finish(agents.read(agent_id, 5))
    assert job.state == "succeeded", job.error


@pytest.fixture
def read(agents: PaperAgents, fake_client: FakeClient) -> str:
    """An agent with no code whose paper has been read and says one number."""
    agent_id = agent_of(agents, None, TITLE)
    read_paper(agents, agent_id, fake_client)

    return agent_id


def offer_of(agents: PaperAgents, agent_id: str, **choice: Any) -> dict[str, Any]:
    offer = agents.reimplementation(agent_id, **choice)["offer"]
    assert offer is not None

    return offer


def write(
    agents: PaperAgents, agent_id: str, fake_client: FakeClient, importer: Import, *replies: str, **choice: Any
) -> Any:
    """Agrees to what is offered and writes the function, with what the model says queued."""
    key = offer_of(agents, agent_id, **choice)["key"]
    for reply in replies:
        fake_client.completions.responses.append(text_response(reply))
    job = agents.start_reimplementation(agent_id, key, 1.0, **choice)

    return finish(job)


class TestWhatIsOffered:
    def test_nothing_until_the_paper_is_read(self, agents: PaperAgents) -> None:
        agent_id = agent_of(agents, None, TITLE)
        found = agents.reimplementation(agent_id)

        assert found["ready"] is False
        assert found["problem"]["code"] == "no_text"
        assert (found["offer"], found["kept"], found["job"]) == (None, None, None)
        assert found["tier"] == "C" and found["label"] == "Re-implementation"

    def test_nothing_until_the_papers_words_are_there(self, agents: PaperAgents) -> None:
        agent_id = agent_of(agents, None, TITLE)
        agents.put_paper(agent_id, "paper.txt", io.BytesIO(PAPER.encode("utf-8")))

        assert agents.reimplementation(agent_id)["problem"]["code"] == "no_text"

    def test_nothing_when_the_paper_reports_no_number_to_check_against(
        self, agents: PaperAgents, fake_client: FakeClient
    ) -> None:
        agent_id = agent_of(agents, None, TITLE)
        read_paper(agents, agent_id, fake_client, claim=False)

        assert agents.reimplementation(agent_id)["problem"]["code"] == "no_numbers"

    def test_an_agent_of_someone_elses_server_is_not_one(self, agents: PaperAgents, workspace: Workspace) -> None:
        agent = {"paper": {"kind": "doi", "file": None}, "imported": {"url": "https://elsewhere.example"}}

        problem = agents.reimplementation_problem(workspace.paperagents_dir, agent)  # type: ignore[arg-type]

        assert problem is not None and problem[0] == "imported"

    def test_an_agent_with_tools_of_the_authors_code_is_not_one(
        self, agents: PaperAgents, read: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(module, "kept_tools_of", lambda directory, agent: (None, {"tools": [{"name": "t"}]}))

        assert agents.reimplementation(read)["problem"]["code"] == "has_tools"

    def test_the_sections_and_the_words_the_model_would_be_given(self, agents: PaperAgents, read: str) -> None:
        found = agents.reimplementation(read)

        assert found["ready"] is True and found["problem"] is None
        assert [section["title"] for section in found["sections"]] == ["Abstract", "Methods", "Results"]
        assert found["default_sections"] == [1]
        offer = found["offer"]
        assert offer["name"] == "reimplemented_adding_and_doubling_a_method"
        assert offer["model"] == TEST_MODEL
        assert METHODS in offer["brief"] and f"The paper: {TITLE}" in offer["brief"]
        assert RESULTS not in offer["brief"] and ABSTRACT not in offer["brief"]
        assert len(offer["key"]) == 64
        json.dumps(found)

    def test_the_words_that_were_searched_for_are_given_as_well(self, agents: PaperAgents, read: str) -> None:
        offer = offer_of(agents, read, search="held-out set of sums")

        assert RESULTS in offer["brief"] and METHODS not in offer["brief"]

    def test_sections_and_a_search_come_together(self, agents: PaperAgents, read: str) -> None:
        offer = offer_of(agents, read, sections=[0], search="held-out set of sums")

        assert ABSTRACT in offer["brief"] and RESULTS in offer["brief"] and METHODS not in offer["brief"]

    def test_what_is_wanted_of_the_function_is_said_as_the_persons(self, agents: PaperAgents, read: str) -> None:
        offer = offer_of(agents, read, goal="I want the doubling, as one number.")

        assert "in their words: I want the doubling, as one number." in offer["brief"]
        assert offer["goal"] == "I want the doubling, as one number."

    def test_the_function_is_named_as_the_person_says(self, agents: PaperAgents, read: str) -> None:
        offer = offer_of(agents, read, name="double_the_sum")

        assert offer["name"] == "double_the_sum"

    def test_what_cannot_be_chosen_is_said_and_nothing_is_offered(self, agents: PaperAgents, read: str) -> None:
        found = agents.reimplementation(read, sections=[99])

        assert found["offer"] is None and found["choice_problem"] is not None

    def test_a_search_or_a_goal_with_a_control_character_is_not_fit(self, agents: PaperAgents, read: str) -> None:
        found = agents.reimplementation(read, search="a\x01b")
        assert found["offer"] is None and "a few words" in found["choice_problem"]
        found = agents.reimplementation(read, goal="a\x01b")
        assert found["offer"] is None and "said in words" in found["choice_problem"]

    def test_a_goal_as_long_as_can_be_is_fit_and_one_of_only_blanks_is_none(
        self, agents: PaperAgents, read: str
    ) -> None:
        offer = offer_of(agents, read, goal="g" * reimplementing.MAX_GOAL_CHARS)

        assert offer["goal"] == "g" * reimplementing.MAX_GOAL_CHARS
        assert offer_of(agents, read, goal="   ")["goal"] is None

    def test_the_key_changes_with_the_choice(self, agents: PaperAgents, read: str) -> None:
        key = offer_of(agents, read)["key"]

        assert offer_of(agents, read, goal="I want it.")["key"] != key
        assert offer_of(agents, read, sections=[1])["key"] == key
        assert offer_of(agents, read, sections=[0])["key"] != key
        assert offer_of(agents, read, name="another_name")["key"] != key


class TestAgreeing:
    def test_nothing_is_written_without_agreeing(self, agents: PaperAgents, read: str) -> None:
        error = refused(agents.start_reimplementation, read, None, 1.0)

        assert error.status == 422 and error.code == "not_agreed"

    def test_the_limit_must_be_said(self, agents: PaperAgents, read: str) -> None:
        key = offer_of(agents, read)["key"]
        error = refused(agents.start_reimplementation, read, key, None)

        assert error.status == 422 and error.code == "invalid"

    def test_docker_must_be_running(self, agents: PaperAgents, read: str, docker: Docker) -> None:
        docker.usable = (False, "Docker is not running")
        key = offer_of(agents, read)["key"]
        error = refused(agents.start_reimplementation, read, key, 1.0)

        assert error.status == 422 and error.code == "docker_missing"

    def test_what_is_agreed_to_is_what_is_sent(self, agents: PaperAgents, read: str) -> None:
        offer_of(agents, read)
        error = refused(agents.start_reimplementation, read, "f" * 64, 1.0)

        assert error.status == 409 and error.code == "changed"
        assert error.details["offer"]["key"] == offer_of(agents, read)["key"]

    def test_a_choice_made_after_agreeing_is_a_changed_offer(self, agents: PaperAgents, read: str) -> None:
        key = offer_of(agents, read)["key"]
        error = refused(agents.start_reimplementation, read, key, 1.0, goal="I want it.")

        assert error.status == 409 and error.code == "changed"


class TestWriting:
    def test_a_function_is_written_from_the_words_that_were_agreed_to(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, importer: Import
    ) -> None:
        job = write(agents, read, fake_client, importer, CODE)

        assert job.state == "succeeded", job.error
        # The function was imported in a container with no network
        assert importer.options["allow_network"] is False and len(importer.calls) == 1
        found = agents.reimplementation(read)
        kept_record = found["kept"]
        assert kept_record["status"] == "written" and kept_record["current"] is True
        assert kept_record["function"]["status"] == "verified"
        assert kept_record["model"] == TEST_MODEL and kept_record["attempts"] == 1
        assert kept_record["cost"] is not None and kept_record["cost"] > 0
        assert kept_record["limit"] == 1.0
        source = kept_record["source"]
        assert source is not None and "def reimplemented_adding_and_doubling_a_method" in source
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        assert kept_record["function"]["source_sha256"] == digest
        offer = offer_of(agents, read)
        assert kept_record["key"] == offer["key"]
        brief_hash = hashlib.sha256(offer["brief"].encode("utf-8")).hexdigest()
        assert kept_record["task"]["brief_sha256"] == brief_hash
        json.dumps(found)

    def test_the_model_that_writes_is_the_one_that_was_agreed_to(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, importer: Import, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # However the settings' model would be read now, what writes is the model of the offer that was agreed to
        monkeypatch.setattr(PaperAgents, "usable_model", lambda self: "another-model")
        job = write(agents, read, fake_client, importer, CODE)

        assert job.state == "succeeded", job.error
        assert agents.reimplementation(read)["kept"]["model"] == TEST_MODEL

    def test_the_model_is_asked_to_write_from_the_papers_words_and_nothing_else(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, importer: Import
    ) -> None:
        write(agents, read, fake_client, importer, CODE, goal="I want the doubling.")

        # The calls before the last are the paper being read, which the fixture did
        request = fake_client.completions.calls[-1]
        system = request["messages"][0]["content"]
        task = request["messages"][1]["content"]
        assert "the words of a scientific paper" in system
        assert "public repositories" not in system and "HuggingFace" not in system
        assert "Never put a number that the paper reports" in system
        assert METHODS in task and RESULTS not in task and "I want the doubling." in task

    def test_a_model_that_writes_no_code_is_a_failure_with_why(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, importer: Import
    ) -> None:
        job = write(agents, read, fake_client, importer, "No code today.", "Still none.")

        assert job.state == "failed"
        record = agents.reimplementation(read)["kept"]
        assert record["status"] == "failed" and record["function"] is None and record["source"] is None
        assert record["cost"] is not None and record["cost"] > 0
        assert any("no Python code" in problem for problem in record["problems"])
        assert importer.calls == []

    def test_a_function_that_cannot_be_imported_is_given_back_until_it_can(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        importer = Import(exit_code=1)
        monkeypatch.setattr(module, "DockerExecutor", importer.make)
        job = write(agents, read, fake_client, importer, CODE, CODE)

        assert job.state == "failed"
        record = agents.reimplementation(read)["kept"]
        assert record["status"] == "failed"
        assert any("Importing the file failed" in problem for problem in record["problems"])
        # The same fault twice running is not asked a third time
        assert len(importer.calls) == 2
        correction = fake_client.completions.calls[-1]["messages"][1]["content"]
        assert "It cannot be used, for these reasons" in correction

    def test_docker_stopping_during_the_import_is_a_failure_with_why(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        importer = Import(error=DockerUnavailableError("cannot connect"))
        monkeypatch.setattr(module, "DockerExecutor", importer.make)
        job = write(agents, read, fake_client, importer, CODE)

        assert job.state == "failed"
        record = agents.reimplementation(read)["kept"]
        assert record["status"] == "failed" and "Docker stopped being available" in (record["error"] or "")
        assert record["attempts"] == 1

    def test_the_limit_being_reached_is_kept(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, importer: Import
    ) -> None:
        key = offer_of(agents, read)["key"]
        fake_client.completions.responses.append(text_response(CODE))
        job = finish(agents.start_reimplementation(read, key, 0.0))

        assert job.state == "failed"
        record = agents.reimplementation(read)["kept"]
        assert record["status"] == "failed" and "limit" in (record["error"] or "")

    def test_the_limit_being_reached_after_an_answer_keeps_the_attempt(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An import that fails is given back for one correction, which the limit of one answer leaves no room for
        importer = Import(exit_code=1)
        monkeypatch.setattr(module, "DockerExecutor", importer.make)
        job = write(agents, read, fake_client, importer, CODE, CODE)
        assert job.state == "failed"
        one_answer = agents.reimplementation(read)["kept"]["cost"] / 2

        agents.clear_reimplementation(read)
        key = offer_of(agents, read)["key"]
        fake_client.completions.responses.append(text_response(CODE))
        job = finish(agents.start_reimplementation(read, key, one_answer))

        assert job.state == "failed"
        record = agents.reimplementation(read)["kept"]
        assert "limit" in (record["error"] or "") and record["attempts"] == 1

    def test_a_second_writing_is_not_started_while_one_goes(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, importer: Import
    ) -> None:
        importer.gate = threading.Event()
        key = offer_of(agents, read)["key"]
        fake_client.completions.responses.append(text_response(CODE))
        job = agents.start_reimplementation(read, key, 1.0)
        try:
            error = refused(agents.start_reimplementation, read, key, 1.0)
            assert error.status == 409 and error.code == "busy"
            assert agents.reimplementation(read)["job"] is not None
        finally:
            importer.gate.set()
        finish(job)

    def test_what_was_kept_is_taken_away_with_it(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, importer: Import, workspace: Workspace
    ) -> None:
        job = write(agents, read, fake_client, importer, CODE)
        assert job.state == "succeeded"
        directory = directory_of(workspace, read)
        assert kept.function_path(directory).is_file()

        agents.clear_reimplementation(read)

        assert agents.reimplementation(read)["kept"] is None
        assert not kept.function_path(directory).exists() and not kept.record_path(directory).exists()

    def test_a_function_of_another_paper_is_not_of_this_one(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, importer: Import, workspace: Workspace
    ) -> None:
        job = write(agents, read, fake_client, importer, CODE)
        assert job.state == "succeeded"
        directory = directory_of(workspace, read)
        record = kept.load(directory)
        assert record is not None

        assert kept.is_current(record, "f" * 64) is False
        assert kept.shown(directory, "f" * 64)["current"] is False  # type: ignore[index]

    def test_a_function_that_was_changed_since_is_not_shown_as_the_one_that_was_written(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, importer: Import, workspace: Workspace
    ) -> None:
        job = write(agents, read, fake_client, importer, CODE)
        assert job.state == "succeeded"
        directory = directory_of(workspace, read)
        kept.function_path(directory).write_text("def changed() -> None:\n    pass\n", encoding="utf-8")

        assert agents.reimplementation(read)["kept"]["source"] is None


class TestARecordThatWasTamperedWith:
    @pytest.mark.parametrize(
        "change",
        ["schema", "status", "paper_sha256", "key", "brief_sha256", "consistency", "source_sha256", "function_status"],
    )
    def test_is_not_shown(
        self,
        agents: PaperAgents,
        read: str,
        fake_client: FakeClient,
        importer: Import,
        workspace: Workspace,
        change: str,
    ) -> None:
        job = write(agents, read, fake_client, importer, CODE)
        assert job.state == "succeeded"
        directory = directory_of(workspace, read)
        record = kept.load(directory)
        assert record is not None
        if change == "schema":
            record["schema"] = "other"
        elif change == "status":
            record["status"] = "other"
        elif change == "paper_sha256":
            record["paper_sha256"] = "0" * 63
        elif change == "key":
            record["key"] = "0" * 63
        elif change == "brief_sha256":
            record["task"]["brief_sha256"] = "0" * 63
        elif change == "consistency":
            record["function"] = None
        elif change == "source_sha256":
            record["function"]["source_sha256"] = "0" * 63
        else:
            record["function"]["status"] = "other"
        kept.record_path(directory).write_text(json.dumps(record), encoding="utf-8")

        assert kept.load(directory) is None
        assert agents.reimplementation(read)["kept"] is None


class TestOverHttp:
    def test_an_unknown_agent_is_not_found(self, client: Any) -> None:
        answer = client.get("/api/paperagents/no-such-agent/reimplementation")

        assert answer.status_code == 404

    def test_nothing_is_written_without_agreeing(self, client: Any, agents: PaperAgents, read: str) -> None:
        answer = client.post(f"/api/paperagents/{read}/reimplementation", json={"agreed": "", "max_cost": 1.0})

        assert answer.status_code == 422
        assert answer.json()["error"]["code"] == "not_agreed"

    def test_nothing_is_written_with_no_key_at_all(self, client: Any, agents: PaperAgents, read: str) -> None:
        answer = client.post(f"/api/paperagents/{read}/reimplementation", json={"max_cost": 1.0})

        assert answer.status_code == 422
        assert answer.json()["error"]["code"] == "not_agreed"

    def test_what_is_offered_is_shown(self, client: Any, agents: PaperAgents, read: str) -> None:
        answer = client.get(f"/api/paperagents/{read}/reimplementation", params={"search": "held-out set of sums"})

        assert answer.status_code == 200
        found = answer.json()
        assert found["ready"] is True and RESULTS in found["offer"]["brief"]

    def test_a_changed_offer_says_so(self, client: Any, agents: PaperAgents, read: str) -> None:
        answer = client.post(f"/api/paperagents/{read}/reimplementation", json={"agreed": "f" * 64, "max_cost": 1.0})

        assert answer.status_code == 409
        assert answer.json()["error"]["code"] == "changed"

    def test_a_function_is_written_and_taken_away(
        self, client: Any, agents: PaperAgents, read: str, fake_client: FakeClient, importer: Import
    ) -> None:
        key = offer_of(agents, read)["key"]
        fake_client.completions.responses.append(text_response(CODE))
        started = client.post(f"/api/paperagents/{read}/reimplementation", json={"agreed": key, "max_cost": 1.0})

        assert started.status_code == 202
        job_id = started.json()["id"]
        for _ in range(2000):
            state = client.get(f"/api/setup/jobs/{job_id}").json()
            if state["state"] not in ("running", "pending"):
                break
        assert state["state"] == "succeeded", state
        kept_after = client.get(f"/api/paperagents/{read}/reimplementation").json()["kept"]
        assert kept_after["status"] == "written" and "def reimplemented" in kept_after["source"]

        deleted = client.delete(f"/api/paperagents/{read}/reimplementation")

        assert deleted.status_code == 200 and deleted.json()["kept"] is None
