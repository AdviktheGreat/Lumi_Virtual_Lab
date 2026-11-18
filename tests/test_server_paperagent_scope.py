"""Tests of putting a person's data against the method card of a PaperAgent through the API: that data outside what the
card says is warned of with the card's words, and the paper's, that data inside it is not, that what a person did to the
card is what the data is put against and is marked as theirs, that it changes nothing, and that nothing is refused
because the data is outside. The paper is read with a model that is replaced by a stand-in, as in the tests of the
card."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_paperagents_reading import LIMIT, RESULT
from test_server_paperagent_card import agent_id, fact_of
from test_server_paperagent_reading import (
    agents,
    client,
    jobs,
    model_client,
    nothing_is_fetched,
    paper_agent,
    workspace,
)

from virtual_lab.paperagents import scope
from virtual_lab.server.paperagents import PaperAgents

# What the fixtures of the tests of reading and of the card are, which are used here as they are
__all__ = ["agent_id", "agents", "client", "jobs", "model_client", "nothing_is_fetched", "workspace"]


def check(client: TestClient, agent_id: str, **described: Any) -> dict[str, Any]:
    response = client.post(f"/api/paperagents/{agent_id}/scope-check", json=described)
    assert response.status_code == 200, response.text

    return response.json()


class TestWhatTheDataIsPutAgainst:
    def test_data_outside_what_the_card_says_is_warned_of_with_the_cards_words_and_the_papers(
        self, client: TestClient, agent_id: str
    ) -> None:
        found = check(client, agent_id, species="zebrafish")

        assert found["outcome"] == scope.OUTSIDE and found["id"] == agent_id
        assert len(found["warnings"]) == 1
        assert "the data's species is “zebrafish”" in found["warnings"][0]
        assert "“mouse” (the paper: “" in found["warnings"][0] and RESULT in found["warnings"][0]
        says = found["aspects"][0]["says"][0]
        assert (says["value"], says["by"], says["quote"]) == ("mouse", "reading", RESULT)
        assert isinstance(says["section"], str)

    def test_data_inside_it_has_no_warning(self, client: TestClient, agent_id: str) -> None:
        found = check(client, agent_id, species="Mus musculus", tissue="brain", sample_size=800, sample_unit="nuclei")

        assert found["outcome"] == scope.INSIDE and found["warnings"] == []
        assert [aspect["outcome"] for aspect in found["aspects"]] == [scope.INSIDE] * 3

    def test_a_size_below_the_range_is_outside_with_the_words_that_give_the_range(
        self, client: TestClient, agent_id: str
    ) -> None:
        found = check(client, agent_id, sample_size=300, sample_unit="nuclei")

        assert found["outcome"] == scope.OUTSIDE
        assert "“at least 500 nuclei” (the paper: “" + LIMIT in found["warnings"][0]

    def test_what_the_card_says_of_what_nothing_was_said_of_is_given(self, client: TestClient, agent_id: str) -> None:
        found = check(client, agent_id, species="mouse")

        assert sorted(each["aspect"] for each in found["not_checked"]) == ["sample size", "tissue"]

    def test_how_far_the_card_is_to_be_trusted_is_given_with_the_answer(
        self, client: TestClient, agents: PaperAgents, agent_id: str
    ) -> None:
        draft = check(client, agent_id, species="mouse")
        assert (draft["card"]["status"], draft["card"]["edited"], draft["card"]["scope_facts"]) == ("draft", False, 3)
        assert draft["reading"]["complete"] is True and "a model did not" in draft["notes"][0]

        agents.approve_card(agent_id)
        assert check(client, agent_id, species="mouse")["card"]["status"] == "approved"

    def test_the_answer_changes_nothing_and_nothing_is_refused_because_the_data_is_outside(
        self, client: TestClient, agents: PaperAgents, agent_id: str
    ) -> None:
        before = agents.reading(agent_id)

        found = check(client, agent_id, species="zebrafish", tissue="liver", sample_size=3)

        assert found["outcome"] == scope.OUTSIDE and len(found["warnings"]) == 3
        assert agents.reading(agent_id) == before


class TestWhatAPersonDidToTheCard:
    def test_data_is_put_against_what_the_card_says_now_and_what_a_person_changed_is_theirs(
        self, client: TestClient, agents: PaperAgents, agent_id: str
    ) -> None:
        mouse = fact_of(agents.reading(agent_id)["card"], "scope", "mouse")
        agents.change_card_fact(agent_id, mouse["id"], {"aspect": "species", "value": "rat"})

        rat = check(client, agent_id, species="rat")
        assert rat["outcome"] == scope.INSIDE and rat["card"]["edited"] is True
        assert rat["aspects"][0]["says"][0]["by"] == "person"

        mouse_now = check(client, agent_id, species="mouse")
        assert mouse_now["outcome"] == scope.OUTSIDE
        assert "“rat” (changed by a person; the paper's words: “" + RESULT in mouse_now["warnings"][0]

    def test_what_a_person_added_is_put_against_the_data_and_is_said_to_be_theirs(
        self, client: TestClient, agents: PaperAgents, agent_id: str
    ) -> None:
        agents.add_card_fact(agent_id, "scope", {"aspect": "species", "value": "zebrafish", "quote": "Our notebook"})

        zebrafish = check(client, agent_id, species="zebrafish")
        assert zebrafish["outcome"] == scope.INSIDE
        assert zebrafish["aspects"][0]["says"][0]["page"] is None
        rat = check(client, agent_id, species="rat")
        assert "“zebrafish” (added by a person: “Our notebook”)" in rat["warnings"][0]
        assert "“mouse” (the paper:" in rat["warnings"][0]

    def test_what_a_person_took_off_is_not_put_against_the_data(
        self, client: TestClient, agents: PaperAgents, agent_id: str
    ) -> None:
        mouse = fact_of(agents.reading(agent_id)["card"], "scope", "mouse")
        agents.remove_card_fact(agent_id, mouse["id"])

        found = check(client, agent_id, species="zebrafish")

        assert found["outcome"] == scope.NOT_COVERED and found["warnings"] == []
        assert found["aspects"][0]["says"] == []


class TestWhenThereIsNothingToPutItAgainst:
    def test_a_paper_that_has_not_been_read_has_a_card_that_covers_nothing(
        self, client: TestClient, agents: PaperAgents
    ) -> None:
        unread = paper_agent(agents)

        found = check(client, unread, species="mouse")

        assert found["outcome"] == scope.NOT_COVERED and found["warnings"] == []
        assert found["reading"]["chunks"] is None and found["card"]["scope_facts"] == 0

    def test_an_agent_with_no_paper_has_a_card_that_covers_nothing(self, client: TestClient) -> None:
        made = client.post("/api/paperagents", json={"title": "Cell", "paper": {"kind": "file"}}).json()["id"]

        assert check(client, made, species="mouse")["outcome"] == scope.NOT_COVERED

    def test_what_a_person_added_before_the_paper_was_read_is_put_against_the_data(
        self, client: TestClient, agents: PaperAgents
    ) -> None:
        unread = paper_agent(agents)
        agents.add_card_fact(unread, "scope", {"aspect": "species", "value": "mouse"})

        assert check(client, unread, species="mouse")["outcome"] == scope.INSIDE
        assert check(client, unread, species="rat")["outcome"] == scope.OUTSIDE


class TestWhatIsWrong:
    def test_something_must_be_said_of_the_data(self, client: TestClient, agent_id: str) -> None:
        for nothing in ({}, {"species": ""}, {"sample_size": 0}, {"species": None}):
            response = client.post(f"/api/paperagents/{agent_id}/scope-check", json=nothing)

            assert response.status_code == 422 and "Say something of the data" in response.json()["error"]["message"]

    @pytest.mark.parametrize(
        "body",
        [
            {"sample_size": "10"},
            {"sample_size": 1.5},
            {"sample_size": True},
            {"species": 5},
            {"species": "x" * 1001},
            {"unknown": "mouse"},
            {"species": "mouse", "sample_unit": "cells"},
            {"species": "the cells"},
            {"sample_size": -4},
        ],
    )
    def test_what_is_not_said_as_it_is_taken_is_refused(
        self, client: TestClient, agent_id: str, body: dict[str, Any]
    ) -> None:
        response = client.post(f"/api/paperagents/{agent_id}/scope-check", json=body)

        assert response.status_code == 422

    def test_an_agent_that_is_not_there_is_not_found_and_the_token_is_needed(
        self, client: TestClient, agent_id: str
    ) -> None:
        assert client.post("/api/paperagents/nowhere/scope-check", json={"species": "mouse"}).status_code == 404
        client.headers.pop("Authorization")

        assert client.post(f"/api/paperagents/{agent_id}/scope-check", json={"species": "mouse"}).status_code == 401


def test_what_is_read_of_the_card_in_these_tests_is_what_they_say(agents: PaperAgents, agent_id: str) -> None:
    card = agents.reading(agent_id)["card"]

    assert sorted((fact["aspect"], fact["value"]) for fact in card["scope"]) == [
        ("sample size", "at least 500 nuclei"),
        ("species", "mouse"),
        ("tissue", "mouse brain tissue"),
    ]
