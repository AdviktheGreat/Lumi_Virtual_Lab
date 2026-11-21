"""Tests of giving a conversation the function that was written from a paper's words, once it is of tier C: that it is
given only then, only where code runs, and only to an agent that has none of the authors' code, that it says it is a
re-implementation in its description, in what it gives, and in every error, that it is called once in the lab's
sandbox image with no network and nothing but an empty folder, that it is held for data outside the card as a tool of
the authors' code is, and that a tool that was given does nothing once the function or its checks change. The
container is a stand-in that calls the function here, so what is looked at is what the server does with what it
gives."""

import io
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
import test_server_paperagent_matching as base
from conftest import FakeClient, text_response
from fastapi.testclient import TestClient
from test_paperagents_reading import queue, reading
from test_server_paperagent_environment import Docker, agent_of, finish
from test_server_paperagent_hold import Person
from test_server_paperagent_matching import (
    CLAIM,
    FUNCTION,
    GOOD,
    NAME,
    OTHER,
    PAPER,
    SECOND,
    TITLE,
    check,
    proposed,
    write,
)
from test_server_paperagent_reimplementation import Import, offer_of

from virtual_lab.constants import DEFAULT_SANDBOX_IMAGE
from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerUnavailableError
from virtual_lab.paperagents import matching
from virtual_lab.paperagents import toolmaking as making
from virtual_lab.paperagents.reading import ReadScope
from virtual_lab.server import paperagent_given as given
from virtual_lab.server.conversations import Conversations
from virtual_lab.server.paperagents import PaperAgents
from virtual_lab.server.workspace import Workspace
from virtual_lab.session import Session
from virtual_lab.tools import Tool, tool_instructions_prompt

# What the tests of checking the function are made with, which are fixtures of that module
agents = base.agents
client = base.client
container = base.container
docker = base.docker
importer = base.importer
jobs = base.jobs
read = base.read
workspace = base.workspace
written = base.written

SESSION = cast(Session, MagicMock(spec=Session))
LABEL = "Re-implementation, not the authors' code"
RUNNER_FOR = matching.runner_for
RUN_CALLS = matching.run_calls
LIMIT = "The method was tested on mouse brain alone."


class Sandbox:
    """Stands in for the container of the sandbox image that the tool is called in: keeps what the runner was made
    with and asked, and calls the function here, as the runner would."""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.printed = ""
        self.failure: dict[str, Any] | None = None
        self.error: BaseException | None = None
        self.ended = "done"
        self.gate: threading.Event | None = None

    def replay(self, runner: making.ToolRunner, source: str, function: str, cases: Any, seconds: float, *_: Any) -> Any:
        project = runner.scratch / matching.PROJECT_DIR
        self.runs.append(
            {
                "tag": runner.tag,
                "data": runner.data,
                "repeats": runner.tools.repeats,
                "label": runner.label,
                "mounts": list(runner.mounts),
                "empty": project.is_dir() and not any(project.iterdir()),
                "scratch": runner.scratch,
                "source": source,
                "function": function,
                "arguments": [case.args for case in cases],
                "seconds": seconds,
            }
        )
        if self.gate is not None:
            self.gate.wait(20)
        if runner.stop.is_set():
            raise StoppedError("Stopped.")
        if self.error is not None:
            raise self.error
        if self.ended != "done":
            return making.Replay(self.ended, 0, [[None] for _ in cases], [])
        namespace: dict[str, Any] = {}
        exec(source, namespace)  # noqa: S102
        results = []
        for case in cases:
            if self.failure is not None:
                call = {"ok": False, "error": self.failure, "result": None}
            else:
                value = namespace[function](**case.args)
                call = {
                    "ok": True,
                    "error": None,
                    "result": {"type": type(value).__name__, "plain": True, "value": value},
                }
            results.append([{"schema": 1, **call, "seconds": 0.1, "output": self.printed}])

        return making.Replay("done", 0, results, ["runner: done"])


@pytest.fixture
def tier_c(
    agents: PaperAgents,
    written: str,
    fake_client: FakeClient,
    container: base.Container,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """An agent with no code whose function was written from its paper and matched the number the paper reports."""
    job = check(agents, written, fake_client, proposed(GOOD))
    assert job.state == "succeeded" and job.message == "Re-implementation, matched 1 of 1 tried", job.error
    # What the tool is called with is the runner of the lab's sandbox image, and not the stand-in that the checks had
    monkeypatch.setattr(matching, "runner_for", RUNNER_FOR)
    monkeypatch.setattr(matching, "run_calls", RUN_CALLS)

    return written


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    stand_in = Sandbox()
    monkeypatch.setattr(making.ToolRunner, "replay", lambda runner, *arguments: stand_in.replay(runner, *arguments))

    return stand_in


@pytest.fixture
def conversations(workspace: Workspace) -> Iterator[Conversations]:
    kept = Conversations(workspace, check_keys=False)
    yield kept
    kept.close()


def name_of(agent_id: str) -> str:
    return given.tool_name(agent_id, NAME)


def tools_of(workspace: Workspace, agent_id: str, **options: Any) -> dict[str, Tool]:
    found = given.agent_tools(workspace, [agent_id], options.pop("session", SESSION), **options)

    return {tool.name: tool for tool in found}


def tool_of(workspace: Workspace, agent_id: str, **options: Any) -> Tool:
    return tools_of(workspace, agent_id, **options)[name_of(agent_id)]


def said(error: pytest.ExceptionInfo[BaseException]) -> str:
    return str(error.value)


class TestWhatIsGiven:
    def test_a_function_of_tier_c_is_a_tool_that_says_first_that_it_is_a_reimplementation(
        self, workspace: Workspace, tier_c: str
    ) -> None:
        found = tools_of(workspace, tier_c)

        assert list(found)[4:] == [name_of(tier_c)]
        tool = found[name_of(tier_c)]
        assert tool.description.startswith(
            f'[Tier C, re-implementation, not the authors\' code] From the PaperAgent "{TITLE}". A model wrote this '
            "function from the paper's words, and none of the authors' code is in it"
        )
        assert "Checked against the paper: matched 1 of 1 tried, which is that it gave a number" in tool.description
        assert "does not show that what it gives is right" in tool.description and "no network" in tool.description
        assert "Adds the numbers and doubles the sum." in tool.description
        assert set(tool.parameters["properties"]) == {"numbers", "times"} and tool.parameters["required"] == ["numbers"]
        assert tool.instructions is not None and "The tool of tier C is a re-implementation" in tool.instructions
        assert "say that it came from a re-implementation" in tool.instructions
        assert "A tool of tier A" not in tool.instructions
        assert "Before you run the re-implementation on the person's own data" in tool.instructions
        assert all(each.instructions == tool.instructions for each in found.values())

    def test_it_is_given_only_where_the_conversation_may_run_code(self, workspace: Workspace, tier_c: str) -> None:
        found = tools_of(workspace, tier_c, session=None)

        assert len(found) == 4 and name_of(tier_c) not in found
        assert all("re-implementation" not in (tool.instructions or "") for tool in found.values())

    def test_a_function_that_was_not_checked_or_that_matched_nothing_is_not_given(
        self,
        agents: PaperAgents,
        workspace: Workspace,
        written: str,
        fake_client: FakeClient,
        container: base.Container,
    ) -> None:
        assert name_of(written) not in tools_of(workspace, written)
        offer = given.offer_of(workspace, written)
        assert offer is not None and offer.tier == "D"

        job = check(agents, written, fake_client, proposed(("numbers", "[0.2, 0.25]")))

        assert job.state == "succeeded" and "could not match" in job.message
        assert name_of(written) not in tools_of(workspace, written)

    def test_a_function_whose_checks_no_longer_hold_is_not_given(
        self, agents: PaperAgents, workspace: Workspace, tier_c: str, fake_client: FakeClient, importer: Import
    ) -> None:
        assert name_of(tier_c) in tools_of(workspace, tier_c)

        write(agents, tier_c, fake_client, importer, FUNCTION.replace("return times * sum", "return 1.0 * times * sum"))

        assert name_of(tier_c) not in tools_of(workspace, tier_c)
        offer = given.offer_of(workspace, tier_c)
        assert offer is not None and offer.tier == "D"

    def test_a_function_that_was_taken_away_or_whose_claims_were_read_again_and_differ_is_not_given(
        self, agents: PaperAgents, workspace: Workspace, tier_c: str, fake_client: FakeClient
    ) -> None:
        base.read_paper(agents, tier_c, fake_client, CLAIM, SECOND)

        assert given.reimplemented(workspace, tier_c) is None and name_of(tier_c) not in tools_of(workspace, tier_c)

        agents.clear_reimplementation(tier_c)

        assert given.reimplemented(workspace, tier_c) is None and name_of(tier_c) not in tools_of(workspace, tier_c)

    def test_a_function_named_as_a_tool_that_reads_is_left_to_that_tool_and_the_lead_is_not_told_of_it(
        self, agents: PaperAgents, workspace: Workspace, read: str, fake_client: FakeClient, importer: Import
    ) -> None:
        stand_in = base.Container()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(matching, "runner_for", stand_in.runner)
            patch.setattr(matching, "run_calls", stand_in.run)
            key = offer_of(agents, read, name="search_paper")["key"]
            fake_client.completions.responses.append(text_response(base.code(FUNCTION.replace(NAME, "search_paper"))))
            assert finish(agents.start_reimplementation(read, key, 1.0, name="search_paper")).state == "succeeded"
            assert check(agents, read, fake_client, proposed(GOOD)).message == "Re-implementation, matched 1 of 1 tried"

        offer = given.offer_of(workspace, read)

        assert given.reimplemented(workspace, read) is not None
        assert offer is not None and offer.tier == "D" and [entry.kind for entry in offer.entries] == ["reading"] * 4
        assert all("re-implementation" not in (entry.tool.instructions or "") for entry in offer.entries)

    def test_checks_that_were_taken_away_or_did_not_come_to_their_end_leave_no_tool(
        self, agents: PaperAgents, workspace: Workspace, tier_c: str
    ) -> None:
        checks = workspace.paperagents_dir / tier_c / "reimplementation" / "checks.json"
        record = json.loads(checks.read_text())
        checks.write_text(json.dumps({**record, "status": "stopped"}))
        assert name_of(tier_c) not in tools_of(workspace, tier_c)

        checks.write_text(json.dumps(record))
        assert name_of(tier_c) in tools_of(workspace, tier_c)

        agents.clear_matching(tier_c)
        assert name_of(tier_c) not in tools_of(workspace, tier_c)

    def test_an_agent_with_tools_of_the_authors_code_is_not_given_it(
        self, workspace: Workspace, tier_c: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kept = {"complete": False, "tools": [{"name": "tally"}]}
        monkeypatch.setattr(given, "kept_tools_of", lambda directory, agent: (None, kept))

        assert given.reimplemented(workspace, tier_c) is None
        assert name_of(tier_c) not in tools_of(workspace, tier_c)

    def test_the_agent_is_of_tier_c_and_the_tool_is_shown_with_its_label(self, client: TestClient, tier_c: str) -> None:
        found = client.get(f"/api/paperagents/{tier_c}/given").json()

        assert found["tier"] == "C" and found["problem"] is None
        assert [(tool["kind"], tool["tier"], tool["label"]) for tool in found["tools"]] == [
            *[("reading", "D", None)] * 4,
            ("reimplementation", "C", LABEL),
        ]
        shown = found["tools"][4]
        assert shown["name"] == name_of(tier_c) and shown["parameters"] == ["numbers", "times"]
        assert "a re-implementation, not the authors' code" in shown["summary"]
        assert "A tool of tier C is a re-implementation" in found["meaning"]


class TestACall:
    def test_runs_the_function_once_in_the_sandbox_image_with_no_network_and_an_empty_folder(
        self, workspace: Workspace, tier_c: str, sandbox: Sandbox
    ) -> None:
        answer = tool_of(workspace, tier_c).function(numbers=[0.2, 0.25, 0.015])

        assert answer["label"] == LABEL and answer["tier"] == "C"
        assert answer["called"] == f"{NAME}, which a model wrote from the paper"
        assert answer["checked"] == "Re-implementation, matched 1 of 1 tried"
        assert answer["result"]["type"] == "float" and answer["result"]["value"] == pytest.approx(0.93)
        assert answer["seconds"] == 0.1 and "printed" not in answer
        assert answer["scope"]["checked"] is False
        [run] = sandbox.runs
        assert run["tag"] == DEFAULT_SANDBOX_IMAGE and run["data"] is None and run["repeats"] == 1
        assert run["label"] == tier_c and run["empty"] is True
        assert run["mounts"] == [(run["scratch"] / matching.PROJECT_DIR, matching.REPO_PATH)]
        assert run["source"] == FUNCTION and run["function"] == NAME
        assert run["arguments"] == [{"numbers": [0.2, 0.25, 0.015]}] and run["seconds"] == given.CALL_SECONDS
        assert run["scratch"].parent == workspace.root and not run["scratch"].exists()
        json.dumps(answer)

    def test_what_it_printed_is_given_beside_what_it_gave(
        self, workspace: Workspace, tier_c: str, sandbox: Sandbox
    ) -> None:
        sandbox.printed = "added 2 numbers\n"

        answer = tool_of(workspace, tier_c).function(numbers=[1, 2], times=3)

        assert answer["result"]["value"] == 9 and answer["printed"] == "added 2 numbers"
        assert list(answer)[0] == "label"

    @pytest.mark.parametrize(
        "how, words",
        [
            ("raised", "ValueError: the numbers are wrong"),
            ("timed_out", "It was stopped after 300 seconds"),
            ("docker", "no daemon"),
            ("arguments", "ValueError: Invalid arguments for"),
            ("stopping", "The call was stopped."),
        ],
    )
    def test_every_error_begins_by_saying_that_it_is_a_reimplementation(
        self, workspace: Workspace, tier_c: str, sandbox: Sandbox, how: str, words: str
    ) -> None:
        sandbox.failure = {"type": "ValueError", "message": "the numbers are wrong", "traceback": [], "cell": None}
        sandbox.ended = "timed_out" if how == "timed_out" else "done"
        sandbox.error = DockerUnavailableError("Docker did not run the tool: no daemon") if how == "docker" else None
        tool = tool_of(workspace, tier_c, stopping=(lambda: True) if how == "stopping" else None)
        arguments: dict[str, Any] = {"numbers": "many"} if how == "arguments" else {"numbers": [1.0]}

        with pytest.raises(given.PaperAgentToolError) as caught:
            tool.function(**arguments)

        assert said(caught).startswith(f"[{LABEL}] ") and words in said(caught)
        assert len(sandbox.runs) == (0 if how == "arguments" else 1)
        assert not list(workspace.root.glob("paperagent.*"))

    def test_a_tool_that_was_given_does_nothing_once_the_function_is_written_again_or_its_checks_are_gone(
        self,
        agents: PaperAgents,
        workspace: Workspace,
        tier_c: str,
        sandbox: Sandbox,
        fake_client: FakeClient,
        importer: Import,
        container: base.Container,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        tool = tool_of(workspace, tier_c)
        agents.clear_matching(tier_c)

        with pytest.raises(given.PaperAgentToolError, match=r"^\[Re-implementation, not the authors' code\] This tool"):
            tool.function(numbers=[1.0])

        changed = FUNCTION.replace("return times * sum", "return 1.0 * times * sum")
        write(agents, tier_c, fake_client, importer, changed)
        monkeypatch.setattr(matching, "runner_for", container.runner)
        monkeypatch.setattr(matching, "run_calls", container.run)
        job = check(agents, tier_c, fake_client, proposed(GOOD))
        assert job.state == "succeeded" and job.message == "Re-implementation, matched 1 of 1 tried", job.error

        with pytest.raises(given.PaperAgentToolError, match="written again"):
            tool.function(numbers=[1.0])
        assert sandbox.runs == []

    def test_an_agent_that_is_deleted_leaves_no_tool_and_one_that_was_given_says_it_is_gone(
        self, agents: PaperAgents, workspace: Workspace, tier_c: str, sandbox: Sandbox
    ) -> None:
        tool = tool_of(workspace, tier_c)
        agents.delete(tier_c)

        assert tools_of(workspace, tier_c) == {}
        with pytest.raises(given.PaperAgentToolError, match="gone"):
            tool.function(numbers=[1.0])
        assert sandbox.runs == []


@pytest.fixture
def scoped(
    agents: PaperAgents,
    fake_client: FakeClient,
    docker: Docker,
    importer: Import,
    container: base.Container,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """An agent of tier C whose card says what the method was used on: mouse brain."""
    agent_id = agent_of(agents, None, TITLE)
    agents.put_paper(agent_id, "paper.txt", io.BytesIO(PAPER.replace(OTHER, f"{OTHER}\n\n{LIMIT}").encode("utf-8")))
    queue(fake_client, reading(claims=[CLAIM], scope=[ReadScope(aspect="tissue", value="mouse brain", quote=LIMIT)]))
    job = finish(agents.read(agent_id, 5))
    assert job.state == "succeeded", job.error
    write(agents, agent_id, fake_client, importer)
    job = check(agents, agent_id, fake_client, proposed(GOOD))
    assert job.state == "succeeded" and job.message == "Re-implementation, matched 1 of 1 tried", job.error
    monkeypatch.setattr(matching, "runner_for", RUNNER_FOR)
    monkeypatch.setattr(matching, "run_calls", RUN_CALLS)

    return agent_id


class TestTheHold:
    def run_tools(self, workspace: Workspace, agent_id: str, person: Person) -> dict[str, Any]:
        return {tool.name: tool.function for tool in given.agent_tools(workspace, [agent_id], SESSION, go_on=person)}

    def test_data_outside_the_card_is_held_until_the_person_goes_on_and_then_the_run_says_they_did(
        self, workspace: Workspace, scoped: str, sandbox: Sandbox
    ) -> None:
        person = Person(True)
        found = self.run_tools(workspace, scoped, person)
        assert found[given.tool_name(scoped, "check_scope")](tissue="liver")["outcome"] == "outside"

        answer = found[name_of(scoped)](numbers=[1.0, 2.0])

        (asked,) = person.asked
        assert (asked.agent, asked.tool, asked.arguments) == (scoped, name_of(scoped), {"numbers": [1.0, 2.0]})
        assert answer["label"] == LABEL and answer["result"]["value"] == 6.0 and len(sandbox.runs) == 1
        assert answer["scope"]["outcome"] == "outside" and answer["scope"]["person_went_on"] is True

    def test_a_person_who_does_not_go_on_has_the_function_not_run_and_the_lead_told_so_with_the_label(
        self, workspace: Workspace, scoped: str, sandbox: Sandbox
    ) -> None:
        found = self.run_tools(workspace, scoped, Person(False))
        found[given.tool_name(scoped, "check_scope")](tissue="liver")

        with pytest.raises(given.PaperAgentToolError) as caught:
            found[name_of(scoped)](numbers=[1.0])

        assert said(caught).startswith(f"[{LABEL}] {name_of(scoped)} was not run: the data is outside")
        assert "the person chose not" in said(caught)
        assert sandbox.runs == []

    def test_checks_that_are_cleared_while_the_person_is_asked_leave_the_function_not_run(
        self, agents: PaperAgents, workspace: Workspace, scoped: str, sandbox: Sandbox
    ) -> None:
        class Clearing(Person):
            def __call__(self, hold: Any) -> bool:
                agents.clear_matching(scoped)
                return super().__call__(hold)

        person = Clearing(True)
        found = self.run_tools(workspace, scoped, person)
        found[given.tool_name(scoped, "check_scope")](tissue="liver")

        with pytest.raises(given.PaperAgentToolError, match=r"^\[Re-implementation, not the authors' code\] This tool"):
            found[name_of(scoped)](numbers=[1.0])

        assert len(person.asked) == 1 and sandbox.runs == []

    def test_data_inside_is_run_without_asking(self, workspace: Workspace, scoped: str, sandbox: Sandbox) -> None:
        person = Person()
        found = self.run_tools(workspace, scoped, person)
        found[given.tool_name(scoped, "check_scope")](tissue="brain")

        answer = found[name_of(scoped)](numbers=[1.0])

        assert answer["scope"]["outcome"] == "inside" and person.asked == []


class TestInConversations:
    def local(self, **more: Any) -> dict[str, Any]:
        return {"team": [], "code": {"where": "local", "resources": "none"}, **more}

    def test_a_conversation_where_code_runs_is_given_the_tool_and_the_lead_is_told_once_what_it_is(
        self, conversations: Conversations, tier_c: str, sandbox: Sandbox
    ) -> None:
        handle = conversations.create(self.local(paperagents=[tier_c]))
        tool = next(tool for tool in handle.chat.tools if tool.name == name_of(tier_c))

        told = tool_instructions_prompt(handle.chat.tools)
        assert told.count(f'The tools of the PaperAgent "{TITLE}"') == 1
        assert "The tool of tier C is a re-implementation" in told
        assert tool.function(numbers=[1.0])["label"] == LABEL

    def test_where_no_code_runs_it_is_not_given(self, conversations: Conversations, tier_c: str) -> None:
        handle = conversations.create({"team": [], "paperagents": [tier_c]})

        assert handle.session is None and name_of(tier_c) not in [tool.name for tool in handle.chat.tools]


def test_the_real_runner_has_the_ceilings_of_a_tool_and_one_call(tmp_path: Path) -> None:
    runner = matching.runner_for(tmp_path, ("docker",), threading.Event(), "agent", 1)

    assert runner.tools.repeats == 1 and runner.tag == DEFAULT_SANDBOX_IMAGE and runner.data is None
