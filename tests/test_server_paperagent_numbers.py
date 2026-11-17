"""Tests of checking a PaperAgent's tools against the numbers that its paper reports, as the server does it: that the
check is asked for by name and says what it may spend, that nothing is asked of a model without that, that a tool is
checked only against the numbers that were read from the paper and a check is stale once they are not, what a model that
says no, a limit that is reached, and a tool that gives another number each come to, and that a tool of tier B by this
kind says what it passed. Docker and its containers are replaced by stand-ins, as in the tests of the other kinds."""

import json
from typing import Any

import pytest
import test_server_paperagent_checks as checks
import test_server_paperagent_given as papers
from conftest import FakeClient, parsed_response
from test_paperagents_reference import result_of
from test_server_paperagent_checks import SESSION, Checks, check, record_of, rewrite, statuses, tools_of
from test_server_paperagent_reference import NOTEBOOK, SCRIPT, run, why, writes
from test_server_paperagent_repository import directory_of
from test_server_paperagent_tools import CALLS, FUNCTIONS, call, gives, make

from virtual_lab.paperagents import linking
from virtual_lab.server import paperagent_checks as kept_checks
from virtual_lab.server import paperagent_given as given
from virtual_lab.server import paperagent_reading as kept_reading
from virtual_lab.server import paperagents as module
from virtual_lab.server.paperagents import PaperAgents
from virtual_lab.server.workspace import Workspace

# What the tests of the other kinds are made with, which are fixtures of those modules
agents = checks.agents
client = checks.client
containers = checks.containers
docker = checks.docker
git_is_installed = checks.git_is_installed
jobs = checks.jobs
marker = checks.marker
prepared = checks.prepared
remote = checks.remote
replays = checks.replays
workspace = checks.workspace

KIND = "paper_numbers"
# What the paper's tutorial got for one call of one tool, which the paper's 0.93 is rounded from
RATE = 0.931
REPORTED = [CALLS[0], call("tally", {"counts": [1, 2, 3], "scale": 2}, RATE, 2)]


@pytest.fixture(autouse=True)
def small_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "DEFAULT_PAPER_CHUNK_SIZE", papers.SIZE)
    monkeypatch.setattr(module, "DEFAULT_PAPER_CHUNK_OVERLAP", 0)


@pytest.fixture
def made(agents: PaperAgents, prepared: str, containers: Any, monkeypatch: pytest.MonkeyPatch) -> str:
    """An agent whose tutorial got 0.931 from one of its two tools, and whose two tools have been made, and whose paper
    has not been read."""
    monkeypatch.setitem(FUNCTIONS, "tally", lambda args: RATE)
    containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=REPORTED))
    run(agents, prepared, repeats=1)
    make(agents, prepared)

    return prepared


@pytest.fixture
def read(agents: PaperAgents, made: str, fake_client: FakeClient) -> str:
    """The same agent, whose paper has been read, and that says 0.93 and 0.88 of the cells."""
    papers.read_paper(agents, made, fake_client)

    return made


def say(fake_client: FakeClient, *answers: tuple[int, bool]) -> None:
    """What a model will say of the candidates of one tool, after what it said when it read the paper."""
    judgement = linking.Judgement(answers=[linking.CandidateAnswer(id=id, same_quantity=same) for id, same in answers])
    fake_client.completions.parsed_responses.append(parsed_response(judgement))


def asked(fake_client: FakeClient) -> list[dict[str, Any]]:
    """The requests that asked of candidates, and not those that read the paper."""
    return [each for each in fake_client.completions.parse_calls if each["response_format"] is linking.Judgement]


def numbers(agents: PaperAgents, agent_id: str, name: str = "tally") -> dict[str, Any]:
    return next(entry for entry in tools_of(agents, agent_id)[name]["evidence"] if entry["kind"] == KIND)


class TestAskingForIt:
    def test_it_is_a_kind_that_is_listed_and_that_is_not_made_unless_it_is_asked_for(
        self, agents: PaperAgents, read: str, replays: Checks, fake_client: FakeClient
    ) -> None:
        shown = agents.checks(read)

        assert {kind["kind"]: (kind["default"], kind["model"]) for kind in shown["kinds"]} == {
            "heldout": (True, False),
            "repo_tests": (True, False),
            KIND: (False, True),
        }
        assert shown["numbers"] == 1
        check(agents, read)
        assert asked(fake_client) == []
        assert {entry["kind"]: entry["status"] for entry in tools_of(agents, read)["tally"]["evidence"]} == {
            "heldout": "passed",
            "repo_tests": "passed",
            KIND: "not_run",
        }

    def test_what_it_may_spend_is_said_for_it_and_for_nothing_else(
        self, agents: PaperAgents, read: str, replays: Checks, fake_client: FakeClient
    ) -> None:
        before = len(replays.runs)

        assert why(agents.start_checks, read, kinds=[KIND]) == (422, "invalid")
        assert why(agents.start_checks, read, kinds=[KIND], max_cost=-1) == (422, "invalid")
        assert why(agents.start_checks, read, kinds=[KIND], max_cost=True) == (422, "invalid")
        assert why(agents.start_checks, read, kinds=["heldout"], max_cost=1) == (422, "invalid")
        assert why(agents.start_checks, read, max_cost=1) == (422, "invalid")
        assert asked(fake_client) == [] and len(replays.runs) == before

    def test_there_must_be_a_number_of_the_paper_to_check_against(
        self, agents: PaperAgents, made: str, replays: Checks, fake_client: FakeClient
    ) -> None:
        assert why(agents.start_checks, made, kinds=[KIND], max_cost=1) == (422, "no_numbers")
        assert asked(fake_client) == []

    def test_a_model_that_has_no_key_is_refused_before_anything_is_made(
        self, agents: PaperAgents, read: str, replays: Checks, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(agents, "missing_keys", lambda model: ["OPENAI_API_KEY"])
        before = len(replays.runs)

        assert why(agents.start_checks, read, kinds=[KIND], max_cost=1)[0] == 422
        assert len(replays.runs) == before


class TestChecking:
    def test_a_number_that_was_found_and_that_the_model_accepted_is_given_again_by_the_tool(
        self, agents: PaperAgents, read: str, replays: Checks, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        say(fake_client, (1, True))
        before = len(replays.runs)

        job = check(agents, read, kinds=[KIND], max_cost=1)

        assert job.state == "succeeded"
        assert job.message is not None and job.message.startswith("Made 2 checks of 2 tools: 1 passed, 0 failed, 1 not")
        # One request, for the one tool that has a place where the paper's number was found
        [request] = asked(fake_client)
        text = request["messages"][1]["content"]
        assert "0.93" in text and "tally" in text and "map_cells" not in text
        # The tool was called again, with the arguments of the call that was found to have given it
        ran = replays.runs[before:]
        assert [one["function"] for one in ran] == ["tally"]
        assert [case["args"] for case in ran[0]["cases"]] == [{"counts": [1, 2, 3], "scale": 2}]
        found = numbers(agents, read)
        assert found["status"] == "passed" and "0.93" in found["summary"]
        assert numbers(agents, read, "map_cells")["status"] == "not_obtained"
        [link] = record_of(workspace, read, "tally", KIND)["details"]["links"]
        assert (link["verdict"], link["got"], link["at"]) == ("match", [RATE, RATE], "result")

    def test_what_was_kept_is_bound_to_the_numbers_it_was_made_from(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        say(fake_client, (1, True))
        check(agents, read, kinds=[KIND], max_cost=1)
        claims = kept_reading.number_claims(directory_of(workspace, read))

        record = record_of(workspace, read, "tally", KIND)

        assert len(claims) == 1 and record["claims_sha256"] == kept_checks.numbers_sha256(claims)
        assert record["details"]["model"] and record["details"]["accepted"] == 1
        assert record["details"]["cost"] is not None and record["details"]["cost"] >= 0
        assert numbers(agents, read)["file"] == "checks/independent/tally/paper_numbers.json"

    def test_with_another_kind_that_passed_the_tool_is_of_tier_b_and_says_what_it_passed(
        self, agents: PaperAgents, read: str, replays: Checks, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        say(fake_client, (1, True))
        check(agents, read, kinds=["heldout", KIND], max_cost=1)

        assert tools_of(agents, read)["tally"]["tier"] == "B"
        assert tools_of(agents, read)["tally"]["passed"] == ["heldout", KIND]
        assert tools_of(agents, read)["map_cells"]["tier"] == "A"
        tool = {each.name: each for each in given.agent_tools(workspace, [read], SESSION)}[f"{read}_tally"]
        assert tool.description.startswith("[Tier B]")
        assert "gave a number that the paper reports, for the arguments its tutorial passed" in tool.description

    def test_it_alone_is_not_enough_for_tier_b(self, agents: PaperAgents, read: str, fake_client: FakeClient) -> None:
        say(fake_client, (1, True))
        check(agents, read, kinds=[KIND], max_cost=1)

        assert numbers(agents, read)["status"] == "passed"
        assert tools_of(agents, read)["tally"]["tier"] == "A"

    def test_a_model_that_says_no_makes_it_not_obtained_and_nothing_is_called_again(
        self, agents: PaperAgents, read: str, replays: Checks, fake_client: FakeClient
    ) -> None:
        say(fake_client, (1, False))
        before = len(replays.runs)

        check(agents, read, kinds=[KIND], max_cost=1)

        assert numbers(agents, read)["status"] == "not_obtained" and "none of the" in numbers(agents, read)["summary"]
        assert len(replays.runs) == before

    def test_a_model_cannot_add_a_place_that_was_not_found(
        self, agents: PaperAgents, read: str, replays: Checks, fake_client: FakeClient
    ) -> None:
        say(fake_client, (2, True), (0, True), (99, True))
        before = len(replays.runs)

        check(agents, read, kinds=[KIND], max_cost=1)

        assert numbers(agents, read)["status"] == "not_obtained"
        assert len(replays.runs) == before

    def test_a_tool_that_gives_another_number_when_it_is_called_again_fails_and_is_kept_from_tier_b(
        self, agents: PaperAgents, read: str, replays: Checks, fake_client: FakeClient
    ) -> None:
        say(fake_client, (1, True))
        check(agents, read, kinds=["heldout"])
        replays.plays["tally"] = gives(0.5)

        check(agents, read, kinds=[KIND], max_cost=1)

        found = numbers(agents, read)
        assert found["status"] == "failed" and "did not give the number that the paper reports" in found["summary"]
        assert tools_of(agents, read)["tally"]["tier"] == "A"
        assert statuses(agents, read, "tally")["heldout"] == "passed"

    def test_a_limit_that_is_reached_stops_that_kind_and_not_the_others(
        self, agents: PaperAgents, read: str, replays: Checks, fake_client: FakeClient
    ) -> None:
        job = check(agents, read, kinds=["heldout", KIND], max_cost=0)

        assert job.state == "succeeded" and job.message is not None
        assert "were not made" in job.message and "limit on spending was reached" in job.message
        assert asked(fake_client) == []
        assert statuses(agents, read, "tally") == {"heldout": "passed", "repo_tests": "not_run"}
        assert numbers(agents, read)["status"] == "not_run"
        # The tool that has no place where a number of the paper's was found needs no model, and is made
        assert numbers(agents, read, "map_cells")["status"] == "not_obtained"

    def test_a_request_that_fails_ends_this_kind_for_the_tool_and_not_the_job(
        self, agents: PaperAgents, read: str, fake_client: FakeClient
    ) -> None:
        fake_client.completions.parsed_responses.append(RuntimeError("connection reset"))

        job = check(agents, read, kinds=["heldout", KIND], max_cost=1)

        assert job.state == "succeeded"
        found = numbers(agents, read)
        assert found["status"] == "not_obtained" and "The request failed" in found["summary"]
        assert statuses(agents, read, "tally")["heldout"] == "passed"
        assert tools_of(agents, read)["tally"]["tier"] == "A"

    def test_a_check_that_is_made_again_takes_the_place_of_the_one_that_was_kept(
        self, agents: PaperAgents, read: str, fake_client: FakeClient
    ) -> None:
        say(fake_client, (1, True))
        check(agents, read, kinds=[KIND], max_cost=1)
        say(fake_client, (1, False))
        check(agents, read, kinds=[KIND], max_cost=1)

        assert numbers(agents, read)["status"] == "not_obtained"
        assert len(asked(fake_client)) == 2

    def test_what_the_paper_says_is_not_taken_as_an_instruction(
        self, agents: PaperAgents, read: str, fake_client: FakeClient
    ) -> None:
        say(fake_client, (1, False))
        check(agents, read, kinds=[KIND], max_cost=1)

        [request] = asked(fake_client)
        text = request["messages"][1]["content"]
        assert text.startswith("<candidates>") and text.endswith("</candidates>")
        assert "IGNORE ALL PREVIOUS INSTRUCTIONS" not in text


class TestWhenTheNumbersAreNotWhatWasChecked:
    def checked(self, agents: PaperAgents, agent_id: str, fake_client: FakeClient) -> None:
        say(fake_client, (1, True))
        check(agents, agent_id, kinds=["heldout", KIND], max_cost=1)
        assert tools_of(agents, agent_id)["tally"]["tier"] == "B"

    def test_a_check_is_current_right_after_it_is_made(
        self, agents: PaperAgents, read: str, fake_client: FakeClient
    ) -> None:
        self.checked(agents, read, fake_client)

        assert numbers(agents, read)["status"] == "passed" and numbers(agents, read)["was"] is None

    def test_a_number_of_the_paper_that_is_not_what_was_checked_leaves_it_stale_and_the_tool_at_tier_a(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        self.checked(agents, read, fake_client)
        path = directory_of(workspace, read) / "claims.json"
        kept = json.loads(path.read_text())
        for claim in kept["claims"]:
            if claim["kind"] == "number" and claim["value"] == "0.93":
                claim["value"] = "0.94"
        path.write_text(json.dumps(kept))

        found = numbers(agents, read)
        assert (found["status"], found["was"]) == ("stale", "passed")
        assert "numbers of the paper" in found["summary"]
        assert tools_of(agents, read)["tally"]["tier"] == "A"
        assert tools_of(agents, read)["tally"]["passed"] == ["heldout"]

    def test_a_paper_whose_reading_was_taken_away_leaves_it_stale(
        self, agents: PaperAgents, read: str, fake_client: FakeClient
    ) -> None:
        self.checked(agents, read, fake_client)
        agents.clear_reading(read)

        assert numbers(agents, read)["status"] == "stale"
        assert tools_of(agents, read)["tally"]["tier"] == "A"

    def test_a_paper_that_is_read_again_to_the_same_numbers_leaves_it_as_it_was(
        self, agents: PaperAgents, read: str, fake_client: FakeClient
    ) -> None:
        self.checked(agents, read, fake_client)
        agents.clear_reading(read)
        papers.read_paper(agents, read, fake_client)

        assert numbers(agents, read)["status"] == "passed"
        assert tools_of(agents, read)["tally"]["tier"] == "B"

    def test_a_check_of_the_other_kinds_does_not_depend_on_the_paper(
        self, agents: PaperAgents, read: str, fake_client: FakeClient
    ) -> None:
        self.checked(agents, read, fake_client)
        agents.clear_reading(read)

        assert statuses(agents, read, "tally") == {"heldout": "passed", "repo_tests": "not_run"}

    def test_a_record_of_it_that_has_no_hash_of_the_numbers_is_not_a_check_that_was_made(
        self, agents: PaperAgents, read: str, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        self.checked(agents, read, fake_client)
        for changes in ({"claims_sha256": None}, {"claims_sha256": "abc"}, {"claims_sha256": 7}):
            rewrite(workspace, read, "tally", KIND, changes)
            assert numbers(agents, read)["status"] == "not_run", changes
        path = kept_checks.record_path(directory_of(workspace, read), "tally", KIND)
        record = json.loads(path.read_text())
        del record["claims_sha256"]
        path.write_text(json.dumps(record))
        assert numbers(agents, read)["status"] == "not_run"
        assert tools_of(agents, read)["tally"]["tier"] == "A"
