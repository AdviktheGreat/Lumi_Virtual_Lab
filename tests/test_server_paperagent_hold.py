"""Tests of holding a run of a PaperAgent's tool for the person to go on, when the data it is run on is outside what the
agent's method card says: that a run that is not held says it was not checked, or what it was put against, that one
that is outside waits for the person and only they can say to go on, that what they said is kept and says so in what the
run gives, and that a conversation asks them as it asks them to approve a call. Docker is replaced by stand-ins, as in
the tests of giving an agent."""

import json
import threading
from collections.abc import Callable
from typing import Any

import pytest
import test_server_paperagent_given as base
from conftest import FakeClient, text_response, tool_call_response
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_paperagents_reading import LIMIT, queue
from test_server_app import handle_of, new_chat, wait_idle
from test_server_chat_mcp import approve, events, say, wait_for_event
from test_server_paperagent_repository import finish
from test_server_paperagent_tools import Replays

from virtual_lab.approval import ApprovalDeclined, ScopeHold
from virtual_lab.server import paperagent_given as given
from virtual_lab.server import paperagent_hold as holding
from virtual_lab.server.paperagent_hold import Hold, NotRun
from virtual_lab.server.paperagents import PaperAgents
from virtual_lab.server.workspace import Workspace

# What the tests of giving an agent are made with, which are fixtures of that module
agents = base.agents
client = base.client
containers = base.containers
conversations = base.conversations
docker = base.docker
git_is_installed = base.git_is_installed
jobs = base.jobs
marker = base.marker
model_client = base.model_client
prepared = base.prepared
referenced = base.referenced
remote = base.remote
replays = base.replays
workspace = base.workspace

ID = base.ID
WARNING = "the data's tissue is “liver”"


@pytest.fixture
def held(agents: PaperAgents, referenced: str, fake_client: FakeClient) -> str:
    """An agent with two tools of tier A, whose paper has been read and whose card says what the method was tested
    on: mouse brain, and at least 500 nuclei."""
    base.make(agents, referenced)
    base.put_paper(agents, referenced)
    queue(fake_client, *base.scoped_answers())
    job = finish(agents.read(referenced, 5))
    assert job.state == "succeeded", job.error

    return referenced


Calls = Callable[[], list[str]]


@pytest.fixture
def calls(held: str, replays: Replays) -> Calls:
    """What the authors' functions have been run for since the agent's tools were made."""
    start = len(replays.runs)

    return lambda: [run["function"] for run in replays.runs[start:]]


class Person:
    """Stands for the person who is asked whether to go on: what they were asked, and what they say, in turn, or what
    is raised in place of an answer."""

    def __init__(self, *answers: bool | BaseException) -> None:
        self.answers = list(answers)
        self.asked: list[ScopeHold] = []

    def __call__(self, hold: ScopeHold) -> bool:
        self.asked.append(hold)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer

        return answer


def result(outcome: str = "outside", warnings: tuple[str, ...] = ("The tissue is outside.",)) -> dict[str, Any]:
    """What putting the data against a card gives, as scope_check does, with what a run says of it."""
    return {
        "outcome": outcome,
        "warnings": list(warnings),
        "aspects": [{"aspect": "tissue", "given": "liver", "outcome": outcome, "detail": "left out of the record"}],
        "card": {"status": "draft"},
    }


class Card:
    """A card that data is put against, which can be changed."""

    def __init__(self, found: dict[str, Any] | None = None) -> None:
        self.found = found if found is not None else result()
        self.compared: list[dict[str, Any]] = []

    def __call__(self, described: Any) -> dict[str, Any]:
        self.compared.append(dict(described))

        return self.found


def before(hold: Hold, card: Card, agent: str = "cell", **changes: Any) -> dict[str, Any]:
    given_ = {"agent": agent, "title": "Cell", "tool": "cell_tally", "arguments": {"counts": [1]}, **changes}

    return hold.before_run(
        given_["agent"], given_["title"], given_["tool"], given_["arguments"], card, "cell_check_scope"
    )


DESCRIBED = {"species": None, "tissue": "liver", "assay": None, "sample_size": None, "sample_unit": None}


class TestTheHoldOnItsOwn:
    def test_a_run_of_data_that_was_not_put_against_the_card_goes_on_and_says_so_and_how_to_do_it(self) -> None:
        person, card = Person(), Card()

        said = before(Hold(person), card)

        assert said["checked"] is False and "cell_check_scope" in said["note"]
        assert "outcome" not in said and "person_went_on" not in said
        assert person.asked == [] and card.compared == []

    @pytest.mark.parametrize("outcome", ["inside", "not covered"])
    def test_a_run_of_data_that_is_inside_or_that_the_card_does_not_cover_goes_on_without_asking(
        self, outcome: str
    ) -> None:
        person, card = Person(), Card(result(outcome, ()))
        hold = Hold(person)
        hold.remember("cell", DESCRIBED)

        said = before(hold, card)

        assert said["checked"] is True and said["outcome"] == outcome and said["card"] == "draft"
        assert said["of"] == [{"aspect": "tissue", "given": "liver", "outcome": outcome}]
        assert "warnings" not in said and "person_went_on" not in said
        assert "Inside is not that the tool works on it" in said["note"]
        assert person.asked == [] and card.compared == [DESCRIBED]

    def test_a_run_of_data_that_is_outside_is_held_and_the_person_is_asked_with_the_cards_words(self) -> None:
        person, card = Person(True), Card(result(warnings=("First.", "Second.")))
        hold = Hold(person)
        hold.remember("cell", DESCRIBED)

        said = before(hold, card, arguments={"counts": [1, 2]})

        (asked,) = person.asked
        assert asked == ScopeHold("cell", "Cell", "cell_tally", {"counts": [1, 2]}, ("First.", "Second."))
        assert said["outcome"] == "outside" and said["warnings"] == ["First.", "Second."]
        assert said["person_went_on"] is True and said["went_on_at"].endswith("+00:00")

    def test_a_person_who_does_not_go_on_has_the_run_not_made_and_is_asked_again_if_it_is_tried_again(self) -> None:
        person, card = Person(False, True), Card()
        hold = Hold(person)
        hold.remember("cell", DESCRIBED)

        with pytest.raises(NotRun, match="person chose not to go on. Do not ask again"):
            before(hold, card)
        said = before(hold, card)

        assert len(person.asked) == 2 and said["person_went_on"] is True

    def test_a_run_is_not_made_where_there_is_no_one_to_ask(self) -> None:
        card = Card()
        hold = Hold(None)
        hold.remember("cell", DESCRIBED)

        with pytest.raises(NotRun, match="no one here to ask whether to go on"):
            before(hold, card)

    @pytest.mark.parametrize("why", ["The turn was ending.", "No one said within 600 seconds."])
    def test_a_person_who_could_not_be_asked_or_did_not_answer_has_the_run_not_made_with_why(self, why: str) -> None:
        hold = Hold(Person(ApprovalDeclined(why)))
        hold.remember("cell", DESCRIBED)

        with pytest.raises(NotRun) as caught:
            before(hold, Card())

        assert str(caught.value) == why

    def test_the_person_is_asked_once_for_the_same_data_against_the_same_words(self) -> None:
        person, card = Person(True), Card()
        hold = Hold(person)
        hold.remember("cell", DESCRIBED)

        first, second = before(hold, card), before(hold, card)
        hold.remember("cell", dict(DESCRIBED))
        third = before(hold, card)

        assert len(person.asked) == 1
        assert first["went_on_at"] == second["went_on_at"] == third["went_on_at"]

    def test_other_data_is_another_question_and_so_are_other_words_on_the_card(self) -> None:
        person, card = Person(True, True, True), Card()
        hold = Hold(person)
        hold.remember("cell", DESCRIBED)
        before(hold, card)

        hold.remember("cell", {**DESCRIBED, "tissue": "kidney"})
        before(hold, card)
        card.found = result(warnings=("The card now says something else.",))
        before(hold, card)

        assert [asked.warnings for asked in person.asked] == [
            ("The tissue is outside.",),
            ("The tissue is outside.",),
            ("The card now says something else.",),
        ]

    def test_it_is_put_against_the_card_as_it_is_when_the_tool_runs_and_not_when_the_data_was_said(self) -> None:
        person, card = Person(), Card()
        hold = Hold(person)
        hold.remember("cell", DESCRIBED)
        card.found = result("inside", ())

        said = before(hold, card)

        assert said["outcome"] == "inside" and person.asked == []

    def test_what_one_agent_was_gone_on_with_is_not_gone_on_with_for_another(self) -> None:
        person, card = Person(True, True), Card()
        hold = Hold(person)
        hold.remember("cell", DESCRIBED)
        hold.remember("other", DESCRIBED)

        before(hold, card)
        before(hold, card, agent="other", title="Other", tool="other_tally")

        assert [asked.agent for asked in person.asked] == ["cell", "other"]

    def test_data_that_cannot_be_put_against_the_card_is_a_run_not_made(self) -> None:
        def broken(described: Any) -> dict[str, Any]:
            raise ValueError("Say something of the data")

        hold = Hold(Person())
        hold.remember("cell", DESCRIBED)

        with pytest.raises(NotRun, match="could not be put against the card: Say something of the data"):
            hold.before_run("cell", "Cell", "cell_tally", {}, broken, None)

    def test_calls_made_together_ask_once_and_each_is_made_when_the_person_goes_on(self) -> None:
        release, asking = threading.Event(), threading.Event()
        asked: list[ScopeHold] = []

        def person(hold: ScopeHold) -> bool:
            asked.append(hold)
            asking.set()
            assert release.wait(10)

            return True

        card, hold = Card(), Hold(person)
        hold.remember("cell", DESCRIBED)
        found: list[dict[str, Any]] = []
        threads = [threading.Thread(target=lambda: found.append(before(hold, card))) for _ in range(3)]
        for thread in threads:
            thread.start()
        assert asking.wait(10)
        release.set()
        for thread in threads:
            thread.join(10)

        assert len(asked) == 1 and len(found) == 3
        assert all(each["person_went_on"] is True for each in found)

    def test_what_is_asked_is_the_data_and_the_words_and_not_what_the_person_could_not_have_seen(self) -> None:
        assert holding.key_of(DESCRIBED, ["a"]) == holding.key_of(dict(reversed(list(DESCRIBED.items()))), ["a"])
        assert holding.key_of(DESCRIBED, ["a"]) != holding.key_of(DESCRIBED, ["b"])
        assert holding.key_of(DESCRIBED, ["a"]) != holding.key_of({**DESCRIBED, "tissue": "kidney"}, ["a"])


def run_tools(workspace: Workspace, agent_id: str, person: Callable[[ScopeHold], bool] | None) -> dict[str, Any]:
    """The tools a conversation with code is given of an agent, asking the person with what is given."""
    found = given.agent_tools(workspace, [agent_id], base.SESSION, go_on=person)

    return {tool.name: tool.function for tool in found}


class TestTheToolsThatRun:
    def test_data_that_was_not_put_against_the_card_is_run_and_what_it_gives_says_it_was_not(
        self, workspace: Workspace, held: str, calls: Calls
    ) -> None:
        person = Person()
        found = run_tools(workspace, held, person)

        answer = found[f"{ID}_tally"](counts=[1, 2], scale=3)

        assert answer["result"]["value"] == 9
        assert answer["scope"]["checked"] is False and f"{ID}_check_scope" in answer["scope"]["note"]
        assert person.asked == [] and calls().count("tally") == 1
        json.dumps(answer)

    def test_data_inside_what_the_card_says_is_run_with_what_it_was_put_against_and_no_one_is_asked(
        self, workspace: Workspace, held: str, calls: Calls
    ) -> None:
        person = Person()
        found = run_tools(workspace, held, person)
        found[f"{ID}_check_scope"](tissue="brain", sample_size=900, sample_unit="nuclei")

        for name, arguments in (("map_cells", {"counts": [1]}), ("tally", {"counts": [1], "scale": 1})):
            answer = found[f"{ID}_{name}"](**arguments)
            assert answer["scope"]["checked"] is True and answer["scope"]["outcome"] == "inside"
            assert answer["scope"]["of"] == [
                {"aspect": "tissue", "given": "brain", "outcome": "inside"},
                {"aspect": "sample size", "given": "900 nuclei", "outcome": "inside"},
            ]
            assert answer["scope"]["card"] == "draft" and "warnings" not in answer["scope"]
        assert person.asked == []

    def test_data_that_the_card_says_nothing_of_is_run_and_the_run_says_the_card_did_not_cover_it(
        self, workspace: Workspace, held: str
    ) -> None:
        person = Person()
        found = run_tools(workspace, held, person)
        found[f"{ID}_check_scope"](assay="Smart-seq2")

        answer = found[f"{ID}_tally"](counts=[1], scale=1)

        assert answer["scope"]["outcome"] == "not covered" and person.asked == []

    def test_data_outside_is_held_until_the_person_goes_on_and_then_the_run_says_they_did(
        self, workspace: Workspace, held: str, calls: Calls
    ) -> None:
        person = Person(True)
        found = run_tools(workspace, held, person)
        checked = found[f"{ID}_check_scope"](tissue="liver", species="mouse")
        assert checked["outcome"] == "outside" and person.asked == []

        answer = found[f"{ID}_tally"](counts=[1, 2, 3], scale=2)

        (asked,) = person.asked
        assert (asked.agent, asked.title, asked.tool) == (held, "CellMapper", f"{ID}_tally")
        assert asked.arguments == {"counts": [1, 2, 3], "scale": 2}
        assert len(asked.warnings) == 1 and WARNING in asked.warnings[0] and LIMIT in asked.warnings[0]
        assert answer["result"]["value"] == 12 and calls().count("tally") == 1
        said = answer["scope"]
        assert said["outcome"] == "outside" and said["warnings"] == list(asked.warnings)
        assert said["person_went_on"] is True and said["went_on_at"].endswith("+00:00")
        assert [(each["aspect"], each["outcome"]) for each in said["of"]] == [
            ("species", "not covered"),
            ("tissue", "outside"),
        ]
        json.dumps(answer)

    def test_the_person_is_asked_once_for_the_data_and_each_run_of_it_says_they_went_on(
        self, workspace: Workspace, held: str
    ) -> None:
        person = Person(True)
        found = run_tools(workspace, held, person)
        found[f"{ID}_check_scope"](tissue="liver")

        first = found[f"{ID}_tally"](counts=[1], scale=1)
        second = found[f"{ID}_map_cells"](counts=[1])
        found[f"{ID}_check_scope"](tissue="liver")
        third = found[f"{ID}_tally"](counts=[2], scale=1)

        assert len(person.asked) == 1
        assert first["scope"]["went_on_at"] == second["scope"]["went_on_at"] == third["scope"]["went_on_at"]

    def test_other_data_is_asked_about_again(self, workspace: Workspace, held: str) -> None:
        person = Person(True, True)
        found = run_tools(workspace, held, person)
        found[f"{ID}_check_scope"](tissue="liver")
        found[f"{ID}_tally"](counts=[1], scale=1)

        found[f"{ID}_check_scope"](tissue="kidney")
        found[f"{ID}_tally"](counts=[1], scale=1)

        assert [WARNING in asked.warnings[0] for asked in person.asked] == [True, False]
        assert "kidney" in person.asked[1].warnings[0]

    def test_a_person_who_does_not_go_on_has_the_tool_not_run_and_the_lead_told_so(
        self, workspace: Workspace, held: str, calls: Calls
    ) -> None:
        found = run_tools(workspace, held, Person(False))
        found[f"{ID}_check_scope"](tissue="liver")

        with pytest.raises(given.PaperAgentToolError) as caught:
            found[f"{ID}_tally"](counts=[1], scale=1)

        assert f"{ID}_tally was not run" in str(caught.value) and "chose not to go on" in str(caught.value)
        assert calls() == []

    def test_a_tool_is_not_run_on_data_that_is_outside_where_there_is_no_one_to_ask(
        self, workspace: Workspace, held: str, calls: Calls
    ) -> None:
        found = run_tools(workspace, held, None)
        found[f"{ID}_check_scope"](tissue="liver")

        with pytest.raises(given.PaperAgentToolError, match="no one here to ask whether to go on"):
            found[f"{ID}_tally"](counts=[1], scale=1)
        assert calls() == []

    def test_a_person_who_could_not_be_asked_has_the_tool_not_run_and_the_lead_told_why(
        self, workspace: Workspace, held: str, calls: Calls
    ) -> None:
        found = run_tools(workspace, held, Person(ApprovalDeclined("The turn ended, so it was not run.")))
        found[f"{ID}_check_scope"](tissue="liver")

        with pytest.raises(given.PaperAgentToolError, match="The turn ended, so it was not run."):
            found[f"{ID}_tally"](counts=[1], scale=1)
        assert calls() == []

    def test_the_lead_has_no_way_to_say_to_go_on_for_the_person(
        self, workspace: Workspace, held: str, calls: Calls
    ) -> None:
        tools_given = given.agent_tools(workspace, [held], base.SESSION, go_on=Person(False))
        tally = next(tool for tool in tools_given if tool.name == f"{ID}_tally")
        found = {tool.name: tool.function for tool in tools_given}
        found[f"{ID}_check_scope"](tissue="liver")

        assert set(tally.parameters["properties"]) == {"counts", "scale"}
        with pytest.raises(ValueError, match="person_went_on: Extra inputs are not permitted"):
            found[f"{ID}_tally"](counts=[1], person_went_on=True)
        assert calls() == []

    def test_a_card_that_a_person_changed_since_is_what_the_data_is_put_against_when_the_tool_runs(
        self, agents: PaperAgents, workspace: Workspace, held: str
    ) -> None:
        person = Person(True)
        found = run_tools(workspace, held, person)
        found[f"{ID}_check_scope"](tissue="liver")
        assert found[f"{ID}_tally"](counts=[1], scale=1)["scope"]["person_went_on"] is True

        agents.add_card_fact(held, "scope", {"aspect": "tissue", "value": "liver", "quote": "Our notes"})
        answer = found[f"{ID}_tally"](counts=[1], scale=1)

        assert answer["scope"]["outcome"] == "inside" and "person_went_on" not in answer["scope"]
        assert len(person.asked) == 1

    def test_the_tools_that_read_are_not_held_and_nor_is_the_check(self, workspace: Workspace, held: str) -> None:
        person = Person()
        found = run_tools(workspace, held, person)
        found[f"{ID}_check_scope"](tissue="liver")

        for name, arguments in (
            ("search_paper", {"query": "cell"}),
            ("show_claim", {}),
            ("show_method_card", {}),
            ("check_scope", {"tissue": "liver"}),
        ):
            # The method card has its own scope in what it shows, which is not what a run says of the data
            assert found[f"{ID}_{name}"](**arguments).get("scope", {}).get("checked") is None, name
        assert person.asked == []

    def test_data_that_could_not_be_put_against_the_card_is_not_taken_for_what_was_said(
        self, workspace: Workspace, held: str
    ) -> None:
        person = Person()
        found = run_tools(workspace, held, person)
        with pytest.raises(given.PaperAgentToolError, match="Say something of the data"):
            found[f"{ID}_check_scope"]()

        assert found[f"{ID}_tally"](counts=[1], scale=1)["scope"]["checked"] is False

    def test_an_agent_that_was_deleted_since_is_gone_before_anyone_is_asked(
        self, agents: PaperAgents, workspace: Workspace, held: str, calls: Calls
    ) -> None:
        person = Person(True)
        found = run_tools(workspace, held, person)
        found[f"{ID}_check_scope"](tissue="liver")
        agents.delete(held)

        with pytest.raises(given.PaperAgentToolError, match="gone"):
            found[f"{ID}_tally"](counts=[1], scale=1)
        assert person.asked == [] and calls() == []

    def test_a_tool_is_not_put_through_the_hold_where_nothing_is_called(self, workspace: Workspace, held: str) -> None:
        offer = given.offer_of(workspace, held)

        assert offer is not None and [entry.kind for entry in offer.entries] == ["reading"] * 4 + ["run"] * 2
        tally = next(entry.tool for entry in offer.entries if entry.tool.name == f"{ID}_tally")
        assert tally.function(counts=[1], scale=1).get("scope") is None


class TestInConversations:
    def chat(self, client: TestClient, **more: Any) -> str:
        made = new_chat(client, code={"where": "local", "resources": "none"}, **more)

        return made["id"]

    def output(self, app: FastAPI, chat_id: str) -> str:
        return "\n".join(event.text for event in events(app, chat_id, "tool_output"))

    def go(self, client: TestClient, fake_client: FakeClient, held: str) -> tuple[str, FastAPI]:
        """A conversation whose lead puts liver data against the card and runs a tool on it, which waits."""
        fake_client.completions.responses = [
            tool_call_response(f"{ID}_check_scope", {"tissue": "liver"}, "call_1"),
            tool_call_response(f"{ID}_tally", {"counts": [1, 2], "scale": 2}, "call_2"),
            text_response("Done."),
        ]
        chat_id = self.chat(client, paperagents=[held])
        say(client, chat_id)

        return chat_id, client.app  # type: ignore[return-value]

    def test_a_conversation_with_an_agent_has_what_it_asks_the_researcher_with_and_one_with_none_has_not(
        self, client: TestClient, held: str
    ) -> None:
        app = client.app
        with_agent = self.chat(client, paperagents=[held])
        without = self.chat(client, paperagents=[])

        assert handle_of(app, with_agent).asker is not None and handle_of(app, with_agent).connections is None
        assert handle_of(app, without).asker is None

    def test_the_servers_and_the_agent_of_a_conversation_are_asked_with_the_same_asker(
        self, client: TestClient, held: str
    ) -> None:
        response = client.put(
            "/api/mcp/servers/genes", json={"entry": {"command": ["python", "-c", "pass"], "approval": {"ask": ["x"]}}}
        )
        assert response.status_code == 200, response.text

        both = handle_of(client.app, self.chat(client, paperagents=[held], mcp=["genes"]))

        assert both.connections is not None and both.connections.asker is both.asker

    def test_a_run_on_data_outside_waits_for_the_person_and_is_made_when_they_go_on(
        self, client: TestClient, fake_client: FakeClient, held: str, calls: Calls
    ) -> None:
        chat_id, app = self.go(client, fake_client, held)

        waiting = wait_for_event(app, chat_id, "approval", "waiting")

        assert waiting.data["about"] == "scope" and waiting.data["tool"] == f"{ID}_tally"
        assert waiting.data["server"] == f"paperagent:{held}" and waiting.data["title"] == "CellMapper"
        assert WARNING in waiting.data["warnings"][0] and LIMIT in waiting.data["warnings"][0]
        assert waiting.data["description"] == " ".join(waiting.data["warnings"])
        assert json.loads(waiting.data["arguments"]) == {"counts": [1, 2], "scale": 2}
        assert client.get(f"/api/chats/{chat_id}").json()["state"] == "running"
        assert calls() == []

        response = approve(client, chat_id, waiting.data["request"], True)
        wait_idle(client, chat_id)

        assert (response.status_code, response.json()) == (200, {"state": "approved"})
        assert [event.data["state"] for event in events(app, chat_id, "approval")] == ["waiting", "approved"]
        assert calls() == ["tally"]
        shown = self.output(app, chat_id)
        assert '"person_went_on": true' in shown and '"value": 6' in shown

    def test_a_person_who_does_not_go_on_has_the_tool_not_run_and_the_lead_told_so(
        self, client: TestClient, fake_client: FakeClient, held: str, calls: Calls
    ) -> None:
        chat_id, app = self.go(client, fake_client, held)
        waiting = wait_for_event(app, chat_id, "approval", "waiting")

        response = approve(client, chat_id, waiting.data["request"], False)
        wait_idle(client, chat_id)

        assert response.json() == {"state": "declined"}
        assert calls() == []
        assert "was not run" in self.output(app, chat_id) and "chose not to go on" in self.output(app, chat_id)
        assert [event.data["state"] for event in events(app, chat_id, "approval")] == ["waiting", "declined"]

    def test_stopping_the_turn_withdraws_the_question_and_the_tool_is_not_run(
        self, client: TestClient, fake_client: FakeClient, held: str, calls: Calls
    ) -> None:
        chat_id, app = self.go(client, fake_client, held)
        waiting = wait_for_event(app, chat_id, "approval", "waiting")

        assert client.post(f"/api/chats/{chat_id}/stop").json() == {"accepted": True}
        wait_idle(client, chat_id)

        assert [event.data["state"] for event in events(app, chat_id, "approval")] == ["waiting", "withdrawn"]
        assert calls() == []
        assert approve(client, chat_id, waiting.data["request"], True).status_code == 409

    def test_deleting_the_conversation_ends_the_question_that_waits(
        self, client: TestClient, fake_client: FakeClient, held: str, calls: Calls
    ) -> None:
        chat_id, app = self.go(client, fake_client, held)
        wait_for_event(app, chat_id, "approval", "waiting")
        asker = handle_of(app, chat_id).asker
        assert asker is not None and len(asker.waiting()) == 1

        assert client.delete(f"/api/chats/{chat_id}").status_code == 204

        assert asker.waiting() == [] and calls() == []

    def test_a_run_on_data_inside_is_not_held_in_a_conversation(
        self, client: TestClient, fake_client: FakeClient, held: str, calls: Calls
    ) -> None:
        fake_client.completions.responses = [
            tool_call_response(f"{ID}_check_scope", {"tissue": "brain"}, "call_1"),
            tool_call_response(f"{ID}_tally", {"counts": [1, 2], "scale": 2}, "call_2"),
            text_response("Done."),
        ]
        chat_id = self.chat(client, paperagents=[held])
        say(client, chat_id)
        wait_idle(client, chat_id)

        assert events(client.app, chat_id, "approval") == []
        assert calls() == ["tally"]
        assert '"outcome": "inside"' in self.output(client.app, chat_id)

    def test_a_request_to_go_on_cannot_be_answered_as_a_question(
        self, client: TestClient, fake_client: FakeClient, held: str, calls: Calls
    ) -> None:
        chat_id, app = self.go(client, fake_client, held)
        waiting = wait_for_event(app, chat_id, "approval", "waiting")

        mixed = client.post(f"/api/chats/{chat_id}/questions/{waiting.data['request']}", json={"answer": {}})

        assert mixed.status_code == 409
        assert approve(client, chat_id, waiting.data["request"], True).status_code == 200
        wait_idle(client, chat_id)
