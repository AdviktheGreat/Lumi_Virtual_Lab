"""Tests of checking a function that was written from a paper's words against the numbers that the paper reports, as
the server does it: which claims are tried and with whose inputs, that a model's inputs are held to the passage and the
person's to the function, that the function is called with them and the number looked for by a program, that a function
whose code holds the number does not count, that what was found makes the function of tier C only if it matched, and
that it is bound to the function, the paper, and the claims it is of. The container the function is called in is a
stand-in that calls it here, so what is looked at is what the server does with what it gives."""

import io
import json
import threading
from pathlib import Path
from typing import Any

import pytest
import test_server_paperagent_environment as environment
import test_server_paperagent_reimplementation as reimplementation_tests
from conftest import TEST_MODEL, FakeClient, parsed_response, text_response
from test_paperagents_reading import queue, reading
from test_server_paperagent_environment import Docker, agent_of, directory_of, finish
from test_server_paperagent_reimplementation import Import, offer_of
from test_server_paperagent_repository import refused

from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerUnavailableError
from virtual_lab.paperagents import matching
from virtual_lab.paperagents import toolmaking as making
from virtual_lab.paperagents.matching import ProposedArgument, ProposedInputs
from virtual_lab.paperagents.reading import ReadClaim
from virtual_lab.server import paperagent_matching as kept
from virtual_lab.server import paperagent_reimplementation as kept_reimplementation
from virtual_lab.server.paperagents import PaperAgents
from virtual_lab.server.workspace import Workspace

agents = environment.agents
client = environment.client
docker = environment.docker
jobs = environment.jobs
workspace = environment.workspace
importer = reimplementation_tests.importer

TITLE = "Adding and doubling: a method"
METHODS = "We take the numbers 0.2, 0.25 and 0.015, add them one to another, and double the sum."
RESULTS = "The doubled sum of the numbers was 0.930 on the held-out set."
OTHER = "Doubled once more, the same numbers gave 1.860 in all."
PAPER = "\n\n".join(
    [
        TITLE,
        "Abstract",
        "A method that doubles.",
        "Methods",
        METHODS,
        "Results",
        RESULTS,
        OTHER,
        "References",
        "A. One.",
    ]
)
NAME = "reimplemented_adding_and_doubling_a_method"
FUNCTION = f'''def {NAME}(numbers: list[float], times: int = 2) -> float:
    """Adds the numbers and doubles the sum.

    :param numbers: The numbers to add.
    :param times: How many times the sum is taken.
    :return: The sum, so many times over.
    """
    return times * sum(numbers)
'''
HARD_CODED = f'''def {NAME}(numbers: list[float], times: int = 2) -> float:
    """Gives what the paper says."""
    return 0.93
'''


def code(source: str = FUNCTION) -> str:
    return f"```python\n{source}```"


class Container:
    """Stands in for the container that the function is called in: calls it here, as the runner would, and keeps what
    it was asked."""

    def __init__(self) -> None:
        self.made: list[tuple[str, list[dict[str, Any]], float]] = []
        self.labels: list[str] = []
        self.error: BaseException | None = None
        self.gate: threading.Event | None = None
        self.started = threading.Event()
        self.ended = "done"

    def runner(self, scratch: Path, docker_command: Any, stop: threading.Event, label: str) -> Any:
        self.labels.append(label)
        self.stop = stop

        return self

    def run(self, runner: Any, source: str, name: str, calls: list[dict[str, Any]], seconds: float) -> making.Replay:
        self.made.append((name, [dict(each) for each in calls], seconds))
        self.started.set()
        if self.gate is not None:
            self.gate.wait(20)
            if self.stop.is_set():
                raise StoppedError("Stopped.")
        if self.error is not None:
            raise self.error
        namespace: dict[str, Any] = {}
        exec(source, namespace)  # noqa: S102
        results = []
        for arguments in calls:
            each: list[dict[str, Any] | None] = []
            for _ in range(matching.REPEATS):
                try:
                    value = namespace[name](**arguments)
                except Exception as error:
                    failure = {"type": type(error).__name__, "message": str(error), "traceback": [], "cell": None}
                    each.append(
                        {"schema": 1, "ok": False, "error": failure, "result": None, "seconds": 0.1, "output": ""}
                    )
                    each += [None] * (matching.REPEATS - len(each))
                    break
                described = {"type": type(value).__name__, "plain": True, "value": value}
                each.append({"schema": 1, "ok": True, "error": None, "result": described, "seconds": 0.1, "output": ""})
            results.append(each)

        return making.Replay(self.ended, 0, results, ["runner: done"])


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch) -> Container:
    stand_in = Container()
    monkeypatch.setattr(matching, "runner_for", stand_in.runner)
    monkeypatch.setattr(matching, "run_calls", stand_in.run)

    return stand_in


def read_paper(agents: PaperAgents, agent_id: str, fake_client: FakeClient, *claims: ReadClaim) -> None:
    agents.put_paper(agent_id, "paper.txt", io.BytesIO(PAPER.encode("utf-8")))
    queue(fake_client, reading(claims=list(claims)))
    job = finish(agents.read(agent_id, 5))
    assert job.state == "succeeded", job.error


CLAIM = ReadClaim(kind="number", value="0.930", quote=RESULTS)
SECOND = ReadClaim(kind="number", value="1.860", quote=OTHER)


@pytest.fixture
def read(agents: PaperAgents, fake_client: FakeClient, docker: Docker) -> str:
    """An agent with no code whose paper has been read and says one number."""
    agent_id = agent_of(agents, None, TITLE)
    read_paper(agents, agent_id, fake_client, CLAIM)

    return agent_id


def write(
    agents: PaperAgents, agent_id: str, fake_client: FakeClient, importer: Import, source: str = FUNCTION
) -> None:
    key = offer_of(agents, agent_id)["key"]
    fake_client.completions.responses.append(text_response(code(source)))
    job = finish(agents.start_reimplementation(agent_id, key, 1.0))
    assert job.state == "succeeded", job.error


@pytest.fixture
def written(agents: PaperAgents, read: str, fake_client: FakeClient, importer: Import) -> str:
    """An agent whose function has been written from its paper."""
    write(agents, read, fake_client, importer)

    return read


def proposed(*arguments: tuple[str, str], found: bool = True, where: str = "the numbers 0.2, 0.25 and 0.015") -> Any:
    return parsed_response(
        ProposedInputs(
            found=found,
            arguments=[ProposedArgument(name=name, value=value) for name, value in arguments],
            where=where,
        )
    )


GOOD = ("numbers", "[0.2, 0.25, 0.015]")


def check(agents: PaperAgents, agent_id: str, fake_client: FakeClient, *answers: Any, **options: Any) -> Any:
    fake_client.completions.parsed_responses = list(answers)
    options.setdefault("max_cost", 1.0)

    return finish(agents.start_matching(agent_id, **options))


def checks_of(agents: PaperAgents, agent_id: str) -> dict[str, Any]:
    return agents.reimplementation(agent_id)["checks"]


class TestWhatIsShown:
    def test_before_a_function_is_written_the_claims_are_listed_and_nothing_is_checked(
        self, agents: PaperAgents, read: str
    ) -> None:
        checks = checks_of(agents, read)

        assert checks["kept"] is None and checks["current"] is False and checks["job"] is None
        assert checks["tier"] is None and checks["label"] == "Re-implementation, not checked against the paper"
        assert checks["parameters"] is None
        [listed] = checks["claims"]
        assert listed["value"] == "0.930" and listed["quote"] == RESULTS
        assert RESULTS in listed["passage"] and METHODS in listed["passage"]
        assert listed["inputs"] is None and listed["entry"] is None
        assert checks["limits"]["most_tried"] == 10 and checks["limits"]["repeats"] == 2
        assert set(checks["meaning"]) == set(matching.STATUSES)
        json.dumps(checks)

    def test_once_it_is_written_its_parameters_are_listed(self, agents: PaperAgents, written: str) -> None:
        assert checks_of(agents, written)["parameters"] == [
            {"name": "numbers", "hint": "list[float]", "required": True, "default": None},
            {"name": "times", "hint": "int", "required": False, "default": "2"},
        ]

    def test_nothing_can_be_checked_before_a_function_is_written(self, agents: PaperAgents, read: str) -> None:
        error = refused(agents.start_matching, read, 1.0)

        assert error.status == 422 and error.code == "no_function"


class TestAModelsInputs:
    def test_inputs_that_the_passage_gives_are_called_with_and_the_number_matched_makes_it_tier_c(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        job = check(agents, written, fake_client, proposed(GOOD))

        assert job.state == "succeeded", job.error
        assert job.message == "Re-implementation, matched 1 of 1 tried"
        [(name, calls, seconds)] = container.made
        assert name == NAME and calls == [{"numbers": [0.2, 0.25, 0.015]}]
        assert seconds == matching.DEFAULT_MINUTES * 60 and container.labels == [written]
        checks = checks_of(agents, written)
        assert checks["current"] is True and checks["tier"] == "C"
        assert checks["label"] == "Re-implementation, matched 1 of 1 tried"
        record = checks["kept"]
        assert record["status"] == "done" and record["model"] == TEST_MODEL and record["limit"] == 1.0
        assert record["requests"] == 1 and record["cost"] is not None and record["cost"] > 0
        assert record["ended"] == "done" and record["output"] == ["runner: done"]
        [listed] = checks["claims"]
        entry = listed["entry"]
        assert entry["status"] == "matched" and entry["by"] == "model"
        assert entry["arguments"] == {"numbers": [0.2, 0.25, 0.015]}
        assert entry["where"] == "the numbers 0.2, 0.25 and 0.015"
        assert entry["found"]["text"] == "result" and entry["found"]["how"] == "as written"
        assert checks["counts"]["matched"] == 1
        json.dumps(checks)

    def test_the_model_is_shown_the_function_and_the_passage_of_the_claim(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        check(agents, written, fake_client, proposed(GOOD))

        request = fake_client.completions.parse_calls[-1]
        system, user = [message["content"] for message in request["messages"]]
        assert system == matching.INPUTS_PROMPT and request["response_format"] is ProposedInputs
        assert f"The function: {NAME}" in user and METHODS in user and "The number: 0.930" in user

    def test_inputs_that_the_passage_does_not_give_are_refused_and_nothing_is_called(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        job = check(agents, written, fake_client, proposed(("numbers", "[0.2, 0.25, 0.016]")))

        assert job.state == "succeeded", job.error
        assert container.made == []
        checks = checks_of(agents, written)
        entry = checks["claims"][0]["entry"]
        assert entry["status"] == "no_inputs" and entry["reason"] == "refused" and "0.016" in entry["note"]
        assert checks["tier"] is None
        assert checks["label"] == "Re-implementation, could not be checked: no number of the paper was tried"

    def test_a_model_that_finds_none_has_none(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        check(agents, written, fake_client, proposed(found=False, where="It says no numbers."))

        entry = checks_of(agents, written)["claims"][0]["entry"]
        assert entry["status"] == "no_inputs" and entry["reason"] == "none_found"
        assert entry["where"] == "It says no numbers." and container.made == []

    def test_a_function_that_does_not_give_the_number_is_of_no_tier(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        check(agents, written, fake_client, proposed(("numbers", "[0.2, 0.25]")))

        checks = checks_of(agents, written)
        assert checks["claims"][0]["entry"]["status"] == "not_found"
        assert checks["tier"] is None
        assert checks["label"] == "Re-implementation, could not match a number of the paper (1 tried)"

    def test_inputs_of_another_type_than_the_function_says_are_refused(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        check(agents, written, fake_client, proposed(("numbers", '["0.2"]')))

        entry = checks_of(agents, written)["claims"][0]["entry"]
        # A list of words is not a list of numbers, so it is refused before the function is called
        assert entry["status"] == "no_inputs" and "not of the type" in entry["note"]

    def test_once_the_limit_is_reached_no_model_is_asked(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        job = check(agents, written, fake_client, proposed(GOOD), max_cost=0.0)

        assert job.state == "succeeded", job.error
        entry = checks_of(agents, written)["claims"][0]["entry"]
        assert entry["status"] == "no_inputs" and entry["reason"] == "limit" and "limit" in entry["note"]
        assert fake_client.completions.parse_calls[-1]["response_format"] is not ProposedInputs
        assert container.made == []

    def test_the_limit_must_be_said_if_a_model_is_to_be_asked(self, agents: PaperAgents, written: str) -> None:
        error = refused(agents.start_matching, written, None)

        assert error.status == 422 and error.code == "invalid"

    @pytest.mark.parametrize("minutes", [0, 31, True, "5", 2.5])
    def test_the_minutes_are_a_whole_number_that_is_allowed(
        self, agents: PaperAgents, written: str, minutes: Any
    ) -> None:
        error = refused(agents.start_matching, written, 1.0, True, minutes)

        assert error.status == 422 and error.code == "invalid"

    def test_the_minutes_that_are_allowed_are_given_to_the_calls(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        check(agents, written, fake_client, proposed(GOOD), minutes=2)

        assert container.made[0][2] == 120
        assert checks_of(agents, written)["kept"]["minutes"] == 2


class TestThePersonsInputs:
    def test_are_kept_and_called_with_and_no_model_is_asked(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        claim_id = checks_of(agents, written)["claims"][0]["id"]
        agents.give_inputs(written, claim_id, {"numbers": [0.4, 0.065]})
        asked = len(fake_client.completions.parse_calls)

        job = check(agents, written, fake_client, ask=False, max_cost=None)

        assert job.state == "succeeded", job.error
        assert len(fake_client.completions.parse_calls) == asked
        assert container.made[0][1] == [{"numbers": [0.4, 0.065]}]
        checks = checks_of(agents, written)
        listed = checks["claims"][0]
        assert listed["inputs"]["arguments"] == {"numbers": [0.4, 0.065]}
        assert listed["entry"]["by"] == "person" and listed["entry"]["status"] == "matched"
        assert checks["kept"]["model"] is None and checks["kept"]["requests"] == 0
        assert checks["tier"] == "C"

    def test_are_used_in_place_of_a_models_for_their_claim_and_the_model_is_asked_for_the_others(
        self, agents: PaperAgents, fake_client: FakeClient, importer: Import, docker: Docker, container: Container
    ) -> None:
        agent_id = agent_of(agents, None, TITLE)
        read_paper(agents, agent_id, fake_client, CLAIM, SECOND)
        write(agents, agent_id, fake_client, importer)
        second = next(each["id"] for each in checks_of(agents, agent_id)["claims"] if each["value"] == "1.860")
        agents.give_inputs(agent_id, second, {"numbers": [0.2, 0.25, 0.015], "times": 4})

        job = check(agents, agent_id, fake_client, proposed(GOOD))

        assert job.state == "succeeded", job.error
        checks = checks_of(agents, agent_id)
        # The claim that the person gave inputs for is tried first, and the model is asked only for the other
        assert [each["value"] for each in checks["claims"]] == ["1.860", "0.930"]
        assert [each["entry"]["by"] for each in checks["claims"]] == ["person", "model"]
        assert [each["entry"]["status"] for each in checks["claims"]] == ["matched", "matched"]
        assert checks["kept"]["requests"] == 1
        assert checks["label"] == "Re-implementation, matched 2 of 2 tried"

    @pytest.mark.parametrize(
        ("arguments", "said"),
        [
            ({"numbers": [0.93]}, "holds 0.930"),
            ({"numbers": [0.2], "seed": 3}, "does not take"),
            ({"times": 2}, "leave out numbers"),
            ({"numbers": "0.2"}, "not of the type"),
        ],
    )
    def test_that_cannot_be_called_with_are_refused(
        self, agents: PaperAgents, written: str, arguments: dict[str, Any], said: str
    ) -> None:
        claim_id = checks_of(agents, written)["claims"][0]["id"]

        error = refused(agents.give_inputs, written, claim_id, arguments)

        assert error.status == 422 and error.code == "invalid" and said in error.message
        assert checks_of(agents, written)["claims"][0]["inputs"] is None

    def test_for_a_claim_that_is_not_tried_are_not_found(self, agents: PaperAgents, written: str) -> None:
        error = refused(agents.give_inputs, written, "no-such-claim", {"numbers": [0.2]})

        assert error.status == 404

    def test_need_a_function_to_be_given_to(self, agents: PaperAgents, read: str) -> None:
        claim_id = checks_of(agents, read)["claims"][0]["id"]

        error = refused(agents.give_inputs, read, claim_id, {"numbers": [0.2]})

        assert error.status == 422 and error.code == "no_function"

    def test_can_be_taken_away(self, agents: PaperAgents, written: str) -> None:
        claim_id = checks_of(agents, written)["claims"][0]["id"]
        agents.give_inputs(written, claim_id, {"numbers": [0.2]})

        agents.give_inputs(written, claim_id, None)

        assert checks_of(agents, written)["claims"][0]["inputs"] is None

    def test_without_them_and_without_a_model_there_is_nothing_to_call_with(
        self, agents: PaperAgents, written: str
    ) -> None:
        error = refused(agents.start_matching, written, None, False)

        assert error.status == 422 and error.code == "no_inputs"

    def test_go_with_the_function_when_it_is_taken_away(
        self, agents: PaperAgents, written: str, workspace: Workspace
    ) -> None:
        claim_id = checks_of(agents, written)["claims"][0]["id"]
        agents.give_inputs(written, claim_id, {"numbers": [0.2]})
        directory = directory_of(workspace, written)
        assert kept.inputs_path(directory).is_file()

        agents.clear_reimplementation(written)

        assert not kept.inputs_path(directory).exists()


class TestCodeThatHoldsTheNumber:
    def test_does_not_count_and_is_not_asked_for_or_called(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, importer: Import, container: Container
    ) -> None:
        write(agents, read, fake_client, importer, HARD_CODED)
        asked = len(fake_client.completions.parse_calls)

        job = check(agents, read, fake_client, proposed(GOOD))

        assert job.state == "succeeded", job.error
        assert len(fake_client.completions.parse_calls) == asked and container.made == []
        checks = checks_of(agents, read)
        entry = checks["claims"][0]["entry"]
        assert entry["status"] == "hard_coded" and entry["hard_coded"] == ["0.93 on line 3"]
        assert checks["tier"] is None


class TestWhatTheEvidenceIsBoundTo:
    def checked(self, agents: PaperAgents, agent_id: str, fake_client: FakeClient) -> None:
        job = check(agents, agent_id, fake_client, proposed(GOOD))
        assert job.state == "succeeded", job.error
        assert checks_of(agents, agent_id)["tier"] == "C"

    def test_a_function_that_was_changed_since_is_not_of_tier_c(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container, workspace: Workspace
    ) -> None:
        self.checked(agents, written, fake_client)
        path = kept_reimplementation.function_path(directory_of(workspace, written))
        path.write_text(path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

        checks = checks_of(agents, written)

        assert checks["current"] is False and checks["tier"] is None and checks["parameters"] is None
        assert checks["label"] == "Re-implementation, not checked against the paper"
        assert checks["claims"][0]["entry"] is None and checks["counts"] is None
        claim_id = checks["claims"][0]["id"]
        for refusal in (
            lambda: agents.start_matching(written, 1.0),
            lambda: agents.give_inputs(written, claim_id, {"numbers": [0.2]}),
        ):
            error = refused(refusal)
            assert error.status == 422 and error.code == "no_function"

    def test_a_kept_file_that_is_a_link_is_not_read(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container, workspace: Workspace
    ) -> None:
        self.checked(agents, written, fake_client)
        path = kept.checks_path(directory_of(workspace, written))
        elsewhere = path.with_name("elsewhere.json")
        path.rename(elsewhere)
        path.symlink_to(elsewhere)

        assert kept.load_checks(directory_of(workspace, written)) is None
        assert checks_of(agents, written)["tier"] is None

    def test_a_function_that_cannot_be_read_has_no_parameters_to_give(self) -> None:
        assert kept.parameters_of("def (", NAME) is None
        assert kept.parameters_of(FUNCTION, "another_name") is None

    def test_a_function_written_again_is_not_of_tier_c_until_it_is_checked(
        self,
        agents: PaperAgents,
        written: str,
        fake_client: FakeClient,
        container: Container,
        importer: Import,
        workspace: Workspace,
    ) -> None:
        self.checked(agents, written, fake_client)

        write(agents, written, fake_client, importer)

        assert checks_of(agents, written)["kept"] is None and checks_of(agents, written)["tier"] is None

    def test_claims_that_were_read_again_and_differ_are_not_of_what_was_checked(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container, workspace: Workspace
    ) -> None:
        self.checked(agents, written, fake_client)
        record = kept.load_checks(directory_of(workspace, written))
        assert record is not None

        record["claims_sha256"] = "0" * 64
        kept.keep_checks(directory_of(workspace, written), record)

        assert checks_of(agents, written)["current"] is False and checks_of(agents, written)["tier"] is None

    def test_a_record_of_another_paper_is_not_of_this_one(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container, workspace: Workspace
    ) -> None:
        self.checked(agents, written, fake_client)
        directory = directory_of(workspace, written)
        record = kept.load_checks(directory)
        assert record is not None
        source = kept_reimplementation.source_of(directory, kept_reimplementation.load(directory))  # type: ignore[arg-type]

        assert kept.is_current(record, source, "f" * 64, []) is False
        assert kept.is_current(record, None, record["paper_sha256"], []) is False

    @pytest.mark.parametrize("change", ["schema", "status", "entry_status", "entries"])
    def test_a_record_that_was_tampered_with_is_not_shown(
        self,
        agents: PaperAgents,
        written: str,
        fake_client: FakeClient,
        container: Container,
        workspace: Workspace,
        change: str,
    ) -> None:
        self.checked(agents, written, fake_client)
        directory = directory_of(workspace, written)
        record = kept.load_checks(directory)
        assert record is not None
        if change == "schema":
            record["schema"] = 2
        elif change == "status":
            record["status"] = "other"
        elif change == "entry_status":
            record["entries"][0]["status"] = "other"
        else:
            record["entries"] = "all matched"
        kept.checks_path(directory).write_text(json.dumps(record), encoding="utf-8")

        checks = checks_of(agents, written)

        assert checks["kept"] is None and checks["tier"] is None

    def test_what_was_kept_can_be_taken_away_and_the_persons_inputs_stay(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        claim_id = checks_of(agents, written)["claims"][0]["id"]
        agents.give_inputs(written, claim_id, {"numbers": [0.4, 0.065]})
        check(agents, written, fake_client, ask=False, max_cost=None)

        agents.clear_matching(written)

        checks = checks_of(agents, written)
        assert checks["kept"] is None and checks["tier"] is None
        assert checks["claims"][0]["inputs"]["arguments"] == {"numbers": [0.4, 0.065]}


class TestTheJob:
    def test_docker_must_be_running(self, agents: PaperAgents, written: str, docker: Docker) -> None:
        docker.usable = (False, "Docker is not running")

        error = refused(agents.start_matching, written, 1.0)

        assert error.status == 422 and error.code == "docker_missing"

    def test_docker_stopping_during_the_calls_is_a_failure_with_why(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        container.error = DockerUnavailableError("cannot connect")

        job = check(agents, written, fake_client, proposed(GOOD))

        assert job.state == "failed" and "Docker stopped being available" in (job.error or "")
        checks = checks_of(agents, written)
        assert checks["kept"]["status"] == "failed" and checks["tier"] is None
        assert checks["claims"][0]["entry"]["status"] == "not_run"

    def test_a_job_that_is_stopped_keeps_what_it_cost_and_is_of_no_tier(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        container.gate = threading.Event()
        fake_client.completions.parsed_responses = [proposed(GOOD)]
        job = agents.start_matching(written, 1.0)
        try:
            assert container.started.wait(20)
            error = refused(agents.start_matching, written, 1.0)
            assert error.status == 409 and error.code == "busy"
            assert checks_of(agents, written)["job"] is not None
            job.request_stop()
        finally:
            container.gate.set()
        finish(job)

        assert job.state == "stopped"
        checks = checks_of(agents, written)
        assert checks["kept"]["status"] == "stopped" and checks["kept"]["requests"] == 1
        assert checks["tier"] is None and checks["label"] == "Re-implementation, not checked against the paper"

    def test_nothing_else_is_done_to_the_agent_while_it_goes(
        self, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        container.gate = threading.Event()
        fake_client.completions.parsed_responses = [proposed(GOOD)]
        job = agents.start_matching(written, 1.0)
        try:
            assert container.started.wait(20)
            error = refused(agents.clear_reimplementation, written)
            assert error.status == 409 and error.code == "busy"
        finally:
            container.gate.set()
        finish(job)


class TestOverHttp:
    def test_checks_are_started_and_shown_and_taken_away(
        self, client: Any, agents: PaperAgents, written: str, fake_client: FakeClient, container: Container
    ) -> None:
        claim_id = checks_of(agents, written)["claims"][0]["id"]

        given = client.put(
            f"/api/paperagents/{written}/reimplementation/inputs/{claim_id}", json={"arguments": {"numbers": [0.465]}}
        )
        assert given.status_code == 200
        assert given.json()["checks"]["claims"][0]["inputs"]["arguments"] == {"numbers": [0.465]}

        started = client.post(f"/api/paperagents/{written}/reimplementation/checks", json={"ask": False})
        assert started.status_code == 202
        job_id = started.json()["id"]
        for _ in range(2000):
            state = client.get(f"/api/setup/jobs/{job_id}").json()
            if state["state"] not in ("running", "pending"):
                break
        assert state["state"] == "succeeded", state
        shown = client.get(f"/api/paperagents/{written}/reimplementation").json()["checks"]
        assert shown["tier"] == "C" and shown["claims"][0]["entry"]["status"] == "matched"

        deleted = client.delete(f"/api/paperagents/{written}/reimplementation/checks")
        assert deleted.status_code == 200 and deleted.json()["checks"]["kept"] is None

        removed = client.delete(f"/api/paperagents/{written}/reimplementation/inputs/{claim_id}")
        assert removed.status_code == 200 and removed.json()["checks"]["claims"][0]["inputs"] is None

    def test_inputs_that_are_not_an_object_are_not_fit(self, client: Any, agents: PaperAgents, written: str) -> None:
        claim_id = checks_of(agents, written)["claims"][0]["id"]

        answer = client.put(f"/api/paperagents/{written}/reimplementation/inputs/{claim_id}", json={"arguments": [0.2]})

        assert answer.status_code == 422

    def test_inputs_that_hold_the_number_are_refused(self, client: Any, agents: PaperAgents, written: str) -> None:
        claim_id = checks_of(agents, written)["claims"][0]["id"]

        answer = client.put(
            f"/api/paperagents/{written}/reimplementation/inputs/{claim_id}", json={"arguments": {"numbers": [0.93]}}
        )

        assert answer.status_code == 422 and answer.json()["error"]["code"] == "invalid"

    def test_ask_is_yes_or_no(self, client: Any, agents: PaperAgents, written: str) -> None:
        answer = client.post(f"/api/paperagents/{written}/reimplementation/checks", json={"ask": "yes"})

        assert answer.status_code == 422
