"""Tests of what a person does to the method card of a PaperAgent: changing, adding, and taking off facts, approving it,
that what they did is kept apart from what the reading made, is theirs and is marked so, and is not lost when the paper
is read again, and that it is lost when the paper is not the same. The paper is read with a model that is replaced by a
stand-in, as in the tests of reading."""

import io
import json
from pathlib import Path
from typing import Any, get_args

import pytest
from conftest import FakeClient
from fastapi.testclient import TestClient
from test_paperagents_reading import (
    DATA,
    LIMIT,
    METHOD,
    RESULT,
    ReadClaim,
    ReadDataset,
    ReadLimitation,
    ReadMethod,
    ReadScope,
    queue,
    reading,
)
from test_server_paperagent_reading import (
    BEARER,
    agents,
    chunks,
    client,
    finish,
    jobs,
    model_client,
    nothing_is_fetched,
    paper_agent,
    refused,
    workspace,
)

from virtual_lab.paperagents import card as method_card
from virtual_lab.paperagents.reading import ReadScope as Scope
from virtual_lab.server import paperagent_reading as kept_reading
from virtual_lab.server.paperagents import PaperAgents
from virtual_lab.server.workspace import Workspace

# What the fixtures of the tests of reading are, which are used here as they are
__all__ = ["agents", "client", "jobs", "model_client", "nothing_is_fetched", "workspace"]


def answers() -> list[Any]:
    """What a good model says of each chunk of the paper: a claim, a method, a dataset, three things that the method was
    tested on, and a limit."""
    replies = []
    for chunk in chunks():
        if chunk.skip:
            continue
        text = chunk.text
        replies.append(
            reading(
                claims=[ReadClaim(kind="number", value="0.93", quote=RESULT)] if RESULT in text else [],
                methods=[ReadMethod(name="STAR", quote=METHOD)] if METHOD in text else [],
                datasets=[ReadDataset(name="GEO", accession="GSE123456", quote=DATA)] if DATA in text else [],
                scope=[
                    *([ReadScope(aspect="species", value="mouse", quote=RESULT)] if RESULT in text else []),
                    *(
                        [
                            ReadScope(aspect="tissue", value="mouse brain tissue", quote=LIMIT),
                            ReadScope(aspect="sample size", value="at least 500 nuclei", quote=LIMIT),
                        ]
                        if LIMIT in text
                        else []
                    ),
                ],
                limitations=[ReadLimitation(quote=LIMIT)] if LIMIT in text else [],
            )
        )

    return replies


def only_a_method() -> list[Any]:
    """What a model says of a paper in which it finds a method and nothing else, for each chunk."""
    return [
        reading(methods=[ReadMethod(name="STAR", quote=METHOD)] if METHOD in chunk.text else [])
        for chunk in chunks()
        if not chunk.skip
    ]


def read_through(agents: PaperAgents, agent_id: str, fake_client: FakeClient, replies: list[Any] | None = None) -> None:
    queue(fake_client, *(replies if replies is not None else answers()))
    job = finish(agents.read(agent_id, 5))
    assert job.state == "succeeded", job.error


@pytest.fixture
def agent_id(agents: PaperAgents, fake_client: FakeClient) -> str:
    """An agent whose paper has been read, and whose card has not been touched."""
    found = paper_agent(agents)
    read_through(agents, found, fake_client)

    return found


def card_of(agents: PaperAgents, agent_id: str) -> dict[str, Any]:
    return agents.reading(agent_id)["card"]


def fact_of(card: dict[str, Any], kind: str, value: str) -> dict[str, Any]:
    """The fact of a kind that says this, which is the one whose name or value it is."""
    return next(fact for fact in card[kind] if value in (fact.get("value"), fact.get("name")))


def edits_file(workspace: Workspace, agent_id: str) -> Path:
    return workspace.paperagents_dir / agent_id / kept_reading.CARD_EDITS_FILE


class TestTheCardAsItIsRead:
    def test_it_is_a_draft_that_nobody_has_approved_and_every_fact_of_it_was_read(
        self, agents: PaperAgents, workspace: Workspace, agent_id: str
    ) -> None:
        card = card_of(agents, agent_id)

        assert (card["status"], card["approved_at"], card["changed_since_approval"], card["edited"]) == (
            "draft",
            None,
            False,
            False,
        )
        assert [len(card[kind]) for kind in method_card.CARD_KINDS] == [1, 1, 3, 1]
        assert all(fact["by"] == "reading" for kind in method_card.CARD_KINDS for fact in card[kind])
        assert all(not card["removed"][kind] for kind in method_card.CARD_KINDS)
        assert not edits_file(workspace, agent_id).exists()

    def test_what_the_reading_made_is_in_its_own_file_and_is_not_changed_by_what_a_person_does(
        self, agents: PaperAgents, workspace: Workspace, agent_id: str
    ) -> None:
        path = workspace.paperagents_dir / agent_id / kept_reading.CARD_FILE
        before = path.read_bytes()
        value = fact_of(card_of(agents, agent_id), "scope", "mouse")

        agents.change_card_fact(agent_id, value["id"], {"aspect": "species", "value": "mouse or rat"})
        agents.add_card_fact(agent_id, "methods", {"name": "Our own method"})
        agents.approve_card(agent_id)

        assert path.read_bytes() == before and json.loads(before)["status"] == "draft"


class TestChangingAFact:
    def test_a_fact_that_a_person_changes_is_theirs_and_keeps_the_papers_words_and_says_what_it_was_read_as(
        self, agents: PaperAgents, agent_id: str
    ) -> None:
        before = fact_of(card_of(agents, agent_id), "scope", "mouse")

        card = agents.change_card_fact(agent_id, before["id"], {"aspect": "species", "value": "mouse or rat"})["card"]

        changed = fact_of(card, "scope", "mouse or rat")
        assert changed["id"] == before["id"] and changed["by"] == "person"
        assert changed["read_as"] == {"aspect": "species", "value": "mouse"}
        assert changed["quote"] == before["quote"] == RESULT and changed["anchor"] == before["anchor"]
        assert card["edited"] is True and len(card["scope"]) == 3
        others = [fact for fact in card["scope"] if fact["id"] != before["id"]]
        assert all(fact["by"] == "reading" for fact in others)

    def test_it_stays_where_it_was_among_the_others(self, agents: PaperAgents, agent_id: str) -> None:
        before = [fact["id"] for fact in card_of(agents, agent_id)["scope"]]

        card = agents.change_card_fact(agent_id, before[0], {"aspect": "other", "value": "any kind of mouse"})["card"]

        assert [fact["id"] for fact in card["scope"]] == before

    def test_it_is_kept_when_the_server_is_started_again(
        self, agents: PaperAgents, workspace: Workspace, jobs: Any, agent_id: str
    ) -> None:
        mouse = fact_of(card_of(agents, agent_id), "scope", "mouse")
        agents.change_card_fact(agent_id, mouse["id"], {"aspect": "species", "value": "mouse or rat"})

        again = PaperAgents(workspace, 100_000, jobs, lambda model: [])

        assert fact_of(card_of(again, agent_id), "scope", "mouse or rat")["by"] == "person"

    def test_a_second_change_keeps_what_the_fact_was_read_as_and_not_the_first_change(
        self, agents: PaperAgents, agent_id: str
    ) -> None:
        mouse = fact_of(card_of(agents, agent_id), "scope", "mouse")
        agents.change_card_fact(agent_id, mouse["id"], {"aspect": "species", "value": "mouse or rat"})

        card = agents.change_card_fact(agent_id, mouse["id"], {"aspect": "species", "value": "rodents"})["card"]

        assert fact_of(card, "scope", "rodents")["read_as"] == {"aspect": "species", "value": "mouse"}

    def test_what_a_dataset_is_called_and_its_accession_are_both_changed_together(
        self, agents: PaperAgents, agent_id: str
    ) -> None:
        geo = card_of(agents, agent_id)["datasets"][0]

        card = agents.change_card_fact(agent_id, geo["id"], {"name": "GEO series", "accession": ""})["card"]

        assert (card["datasets"][0]["name"], card["datasets"][0]["accession"]) == ("GEO series", "")
        assert card["datasets"][0]["read_as"] == {"name": "GEO", "accession": "GSE123456"}

    @pytest.mark.parametrize(
        ("fields", "message"),
        [
            ({"aspect": "species", "value": ""}, "value must be filled in"),
            ({"aspect": "colour", "value": "blue"}, "aspect is one of"),
            ({"aspect": "species", "value": "mouse"}, "already"),
            ({"aspect": "species", "value": "x" * 301}, "at most 300"),
            ({"aspect": "species", "value": "rat", "quote": "mine"}, "not something a fact of scope has"),
            ({"aspect": "species", "value": "rat", "colour": "blue"}, "not something a fact of scope has"),
            ({"aspect": "species", "value": 3}, "is words"),
            ("species", "its fields, by name"),
        ],
    )
    def test_what_a_fact_cannot_say_is_refused_and_nothing_is_changed(
        self, agents: PaperAgents, workspace: Workspace, agent_id: str, fields: Any, message: str
    ) -> None:
        mouse = fact_of(card_of(agents, agent_id), "scope", "mouse")

        error = refused(agents.change_card_fact, agent_id, mouse["id"], fields)

        assert (error.status, error.code) == (422, "invalid") and message in error.message
        assert not edits_file(workspace, agent_id).exists()

    def test_a_fact_cannot_be_changed_to_say_what_another_fact_says(self, agents: PaperAgents, agent_id: str) -> None:
        tissue = fact_of(card_of(agents, agent_id), "scope", "mouse brain tissue")

        error = refused(agents.change_card_fact, agent_id, tissue["id"], {"aspect": "species", "value": "Mouse"})

        assert error.status == 422 and "The card has that already" in error.message

    def test_the_paper_says_a_limit_and_a_person_who_disagrees_takes_it_off_and_writes_their_own(
        self, agents: PaperAgents, agent_id: str
    ) -> None:
        limit = card_of(agents, agent_id)["limitations"][0]

        error = refused(agents.change_card_fact, agent_id, limit["id"], {})

        assert error.status == 422 and "take it off, and add yours" in error.message

    def test_a_fact_that_the_card_has_not_is_not_found(self, agents: PaperAgents, agent_id: str) -> None:
        assert (
            refused(agents.change_card_fact, agent_id, "scope-00000000", {"aspect": "other", "value": "x"}).status
            == 404
        )
        assert refused(agents.remove_card_fact, agent_id, "scope-00000000").status == 404
        assert refused(agents.restore_card_fact, agent_id, "scope-00000000").status == 404


class TestAddingAFact:
    def test_a_fact_that_a_person_adds_is_theirs_has_their_words_and_no_place_in_the_paper(
        self, agents: PaperAgents, agent_id: str
    ) -> None:
        card = agents.add_card_fact(
            agent_id, "scope", {"aspect": "assay", "value": "snRNA-seq", "quote": "  Table 1 of the supplement  "}
        )["card"]

        added = fact_of(card, "scope", "snRNA-seq")
        assert added["by"] == "person" and added["read_as"] is None and added["anchor"] is None
        assert added["quote"] == "Table 1 of the supplement" and added["id"].startswith("scope-own")
        assert [fact["by"] for fact in card["scope"]] == ["reading", "reading", "reading", "person"]
        assert card["edited"] is True

    def test_each_kind_takes_what_it_has_and_a_limit_is_its_words(self, agents: PaperAgents, agent_id: str) -> None:
        agents.add_card_fact(agent_id, "methods", {"name": "Our method"})
        agents.add_card_fact(agent_id, "datasets", {"name": "Our data", "accession": "PRJ1"})
        card = agents.add_card_fact(agent_id, "limitations", {"quote": "It was slow on large samples."})["card"]

        assert [fact["name"] for fact in card["methods"]] == ["STAR", "Our method"]
        assert card["datasets"][1]["accession"] == "PRJ1"
        assert card["limitations"][1]["quote"] == "It was slow on large samples."

    @pytest.mark.parametrize(
        ("kind", "fields", "message"),
        [
            ("scope", {"aspect": "species"}, "value must be filled in"),
            ("scope", {"value": "rat"}, "aspect must be filled in"),
            ("methods", {}, "name must be filled in"),
            ("limitations", {}, "its words"),
            ("limitations", {"quote": "x" * 1001}, "at most 1,000"),
            ("claims", {"value": "1"}, "Say which sort of fact"),
            ("scope", {"aspect": "species", "value": "mouse"}, "already"),
            ("limitations", {"quote": LIMIT}, "already"),
        ],
    )
    def test_what_is_not_a_fact_is_refused(
        self, agents: PaperAgents, workspace: Workspace, agent_id: str, kind: str, fields: Any, message: str
    ) -> None:
        error = refused(agents.add_card_fact, agent_id, kind, fields)

        assert (error.status, error.code) == (422, "invalid") and message in error.message
        assert not edits_file(workspace, agent_id).exists()

    def test_the_most_a_person_adds_is_limited(
        self, agents: PaperAgents, monkeypatch: pytest.MonkeyPatch, agent_id: str
    ) -> None:
        monkeypatch.setattr(method_card, "MAX_OWN", 2)
        agents.add_card_fact(agent_id, "methods", {"name": "One"})
        agents.add_card_fact(agent_id, "methods", {"name": "Two"})

        error = refused(agents.add_card_fact, agent_id, "methods", {"name": "Three"})

        assert error.status == 422 and "as many facts of yours as it takes" in error.message

    def test_a_card_can_be_made_by_hand_for_a_paper_that_was_not_read(self, agents: PaperAgents) -> None:
        agent_id = paper_agent(agents)

        card = agents.add_card_fact(agent_id, "scope", {"aspect": "species", "value": "human"})["card"]

        assert [fact["value"] for fact in card["scope"]] == ["human"] and card["methods"] == []

    def test_an_agent_with_no_paper_has_no_card_to_change(self, agents: PaperAgents) -> None:
        agent_id = agents.create("No paper yet", {"kind": "file"})

        error = refused(agents.add_card_fact, agent_id, "methods", {"name": "x"})

        assert (error.status, error.code) == (409, "no_paper")


class TestTakingAFactOff:
    def test_a_fact_that_was_read_is_kept_aside_and_can_be_put_back(self, agents: PaperAgents, agent_id: str) -> None:
        tissue = fact_of(card_of(agents, agent_id), "scope", "mouse brain tissue")

        card = agents.remove_card_fact(agent_id, tissue["id"])["card"]

        assert [fact["value"] for fact in card["scope"]] == ["mouse", "at least 500 nuclei"]
        assert [fact["id"] for fact in card["removed"]["scope"]] == [tissue["id"]] and card["edited"] is True
        back = agents.restore_card_fact(agent_id, tissue["id"])["card"]
        assert [fact["id"] for fact in back["scope"]] == [fact["id"] for fact in card_of(agents, agent_id)["scope"]]
        assert back["removed"]["scope"] == [] and back["edited"] is False

    def test_a_fact_that_a_person_added_is_gone_for_good(
        self, agents: PaperAgents, workspace: Workspace, agent_id: str
    ) -> None:
        added = fact_of(
            agents.add_card_fact(agent_id, "methods", {"name": "Our method"})["card"], "methods", "Our method"
        )

        card = agents.remove_card_fact(agent_id, added["id"])["card"]

        assert [fact["name"] for fact in card["methods"]] == ["STAR"] and card["removed"]["methods"] == []
        assert not edits_file(workspace, agent_id).exists()
        assert refused(agents.restore_card_fact, agent_id, added["id"]).status == 404

    def test_taking_off_a_fact_that_a_person_changed_puts_what_was_read_aside(
        self, agents: PaperAgents, agent_id: str
    ) -> None:
        mouse = fact_of(card_of(agents, agent_id), "scope", "mouse")
        agents.change_card_fact(agent_id, mouse["id"], {"aspect": "species", "value": "mouse or rat"})

        card = agents.remove_card_fact(agent_id, mouse["id"])["card"]

        assert all(fact["id"] != mouse["id"] for fact in card["scope"])
        assert [(fact["by"], fact["value"]) for fact in card["removed"]["scope"]] == [("reading", "mouse")]

    def test_putting_back_a_fact_that_a_person_changed_has_it_say_what_it_was_read_as(
        self, agents: PaperAgents, agent_id: str
    ) -> None:
        mouse = fact_of(card_of(agents, agent_id), "scope", "mouse")
        agents.change_card_fact(agent_id, mouse["id"], {"aspect": "species", "value": "mouse or rat"})

        card = agents.restore_card_fact(agent_id, mouse["id"])["card"]

        assert fact_of(card, "scope", "mouse")["by"] == "reading" and card["edited"] is False

    def test_a_fact_that_the_reading_no_longer_finds_cannot_be_put_back_but_what_a_person_changed_stays(
        self, agents: PaperAgents, agent_id: str, fake_client: FakeClient
    ) -> None:
        mouse = fact_of(card_of(agents, agent_id), "scope", "mouse")
        tissue = fact_of(card_of(agents, agent_id), "scope", "mouse brain tissue")
        agents.change_card_fact(agent_id, mouse["id"], {"aspect": "species", "value": "mouse or rat"})
        agents.remove_card_fact(agent_id, tissue["id"])
        agents.clear_reading(agent_id)
        # A reading that does not find them any more: it finds a method and nothing else
        read_through(agents, agent_id, fake_client, only_a_method())

        card = card_of(agents, agent_id)

        assert fact_of(card, "scope", "mouse or rat")["by"] == "person" and len(card["scope"]) == 1
        assert card["removed"]["scope"] == []
        error = refused(agents.restore_card_fact, agent_id, tissue["id"])
        assert error.status == 422 and "no longer finds" in error.message
        error = refused(agents.restore_card_fact, agent_id, mouse["id"])
        assert error.status == 422 and "no longer finds" in error.message


class TestWhatIsKeptWhenThePaperIsReadAgain:
    def test_what_a_person_did_is_kept_when_the_reading_is_cleared_and_the_paper_is_read_again(
        self, agents: PaperAgents, agent_id: str, fake_client: FakeClient
    ) -> None:
        mouse = fact_of(card_of(agents, agent_id), "scope", "mouse")
        tissue = fact_of(card_of(agents, agent_id), "scope", "mouse brain tissue")
        agents.change_card_fact(agent_id, mouse["id"], {"aspect": "species", "value": "mouse or rat"})
        agents.remove_card_fact(agent_id, tissue["id"])
        agents.add_card_fact(agent_id, "scope", {"aspect": "assay", "value": "snRNA-seq"})
        before = card_of(agents, agent_id)

        agents.clear_reading(agent_id)
        cleared = card_of(agents, agent_id)
        assert [fact["value"] for fact in cleared["scope"]] == ["mouse or rat", "snRNA-seq"]
        read_through(agents, agent_id, fake_client)

        assert card_of(agents, agent_id) == before

    def test_an_approval_holds_for_a_card_that_comes_out_the_same_and_not_for_one_that_does_not(
        self, agents: PaperAgents, agent_id: str, fake_client: FakeClient
    ) -> None:
        agents.approve_card(agent_id)
        agents.clear_reading(agent_id)
        read_through(agents, agent_id, fake_client)
        assert card_of(agents, agent_id)["status"] == "approved"

        agents.clear_reading(agent_id)
        read_through(agents, agent_id, fake_client, only_a_method())

        card = card_of(agents, agent_id)
        assert (card["status"], card["approved_at"], card["changed_since_approval"]) == ("draft", None, True)

    def test_what_a_person_did_is_taken_away_with_the_paper_it_was_done_to(
        self, agents: PaperAgents, workspace: Workspace, agent_id: str
    ) -> None:
        agents.add_card_fact(agent_id, "methods", {"name": "Our method"})
        assert edits_file(workspace, agent_id).is_file()

        agents.remove_paper(agent_id)

        assert not edits_file(workspace, agent_id).exists()

    def test_a_paper_that_is_put_in_place_of_it_has_none_of_it(
        self, agents: PaperAgents, workspace: Workspace, agent_id: str
    ) -> None:
        agents.add_card_fact(agent_id, "methods", {"name": "Our method"})

        agents.put_paper(agent_id, "other.txt", io.BytesIO(b"A different paper, with other words in it.\n"))

        assert not edits_file(workspace, agent_id).exists()
        assert card_of(agents, agent_id)["methods"] == [] and card_of(agents, agent_id)["edited"] is False

    def test_what_was_done_to_the_card_of_another_file_is_not_seen(
        self, agents: PaperAgents, workspace: Workspace, agent_id: str
    ) -> None:
        agents.add_card_fact(agent_id, "methods", {"name": "Our method"})
        path = edits_file(workspace, agent_id)
        record = json.loads(path.read_text())
        path.write_text(json.dumps({**record, "file_sha256": "0" * 64}))

        card = card_of(agents, agent_id)

        assert [fact["name"] for fact in card["methods"]] == ["STAR"] and card["edited"] is False


class TestApproving:
    def test_approving_says_when_and_a_change_afterwards_makes_the_card_a_draft_again(
        self, agents: PaperAgents, agent_id: str
    ) -> None:
        card = agents.approve_card(agent_id)["card"]

        assert card["status"] == "approved" and card["approved_at"] and card["changed_since_approval"] is False
        agents.add_card_fact(agent_id, "methods", {"name": "Our method"})
        card = card_of(agents, agent_id)
        assert (card["status"], card["approved_at"], card["changed_since_approval"]) == ("draft", None, True)

    def test_putting_the_change_back_makes_the_card_the_one_that_was_approved(
        self, agents: PaperAgents, agent_id: str
    ) -> None:
        agents.approve_card(agent_id)
        added = agents.add_card_fact(agent_id, "methods", {"name": "Our method"})["card"]["methods"][1]
        assert card_of(agents, agent_id)["status"] == "draft"

        card = agents.remove_card_fact(agent_id, added["id"])["card"]

        assert card["status"] == "approved"

    def test_an_approval_can_be_taken_back_and_then_it_is_a_draft_that_was_not_changed(
        self, agents: PaperAgents, workspace: Workspace, agent_id: str
    ) -> None:
        agents.approve_card(agent_id)

        card = agents.withdraw_card_approval(agent_id)["card"]

        assert (card["status"], card["changed_since_approval"]) == ("draft", False)
        assert not edits_file(workspace, agent_id).exists()

    def test_a_card_with_nothing_on_it_cannot_be_approved(self, agents: PaperAgents) -> None:
        agent_id = paper_agent(agents)

        error = refused(agents.approve_card, agent_id)

        assert (error.status, error.code) == (422, "invalid") and "nothing to approve" in error.message

    def test_a_card_cannot_be_approved_while_the_paper_is_being_read(
        self, agents: PaperAgents, monkeypatch: pytest.MonkeyPatch, agent_id: str
    ) -> None:
        monkeypatch.setattr(agents, "running", lambda found: type("Job", (), {"title": "Reading", "snapshot": dict})())

        error = refused(agents.approve_card, agent_id)

        assert (error.status, error.code) == (409, "busy")

    def test_what_a_person_did_can_be_discarded_whole_with_the_approval(
        self, agents: PaperAgents, workspace: Workspace, agent_id: str
    ) -> None:
        before = card_of(agents, agent_id)
        mouse = fact_of(before, "scope", "mouse")
        agents.change_card_fact(agent_id, mouse["id"], {"aspect": "species", "value": "mouse or rat"})
        agents.remove_card_fact(agent_id, fact_of(before, "scope", "mouse brain tissue")["id"])
        agents.add_card_fact(agent_id, "methods", {"name": "Our method"})
        agents.approve_card(agent_id)

        card = agents.discard_card_edits(agent_id)["card"]

        assert card == before and not edits_file(workspace, agent_id).exists()


class TestWhatIsKept:
    def test_a_record_that_was_edited_by_hand_has_what_is_wrong_left_out_and_the_rest_kept(
        self, agents: PaperAgents, workspace: Workspace, agent_id: str
    ) -> None:
        added = fact_of(
            agents.add_card_fact(agent_id, "methods", {"name": "Our method"})["card"], "methods", "Our method"
        )
        path = edits_file(workspace, agent_id)
        record = json.loads(path.read_text())
        record["facts"]["method-bad"] = {"id": "method-bad", "kind": "methods", "by": "person", "name": 3}
        record["facts"]["scope-liar"] = {**record["facts"][added["id"]], "id": "scope-other"}
        record["removed"] = {"method-x": 3}
        record["approval"] = {"at": 3}
        path.write_text(json.dumps(record))

        card = card_of(agents, agent_id)

        assert [fact["name"] for fact in card["methods"]] == ["STAR", "Our method"]
        assert card["status"] == "draft" and card["changed_since_approval"] is False

    @pytest.mark.parametrize("text", ["not json", "[]", '{"schema": 2}', '{"schema": 1, "facts": 3}'])
    def test_a_record_that_is_nothing_like_one_is_no_edits(
        self, agents: PaperAgents, workspace: Workspace, agent_id: str, text: str
    ) -> None:
        edits_file(workspace, agent_id).write_text(text)

        assert card_of(agents, agent_id)["edited"] is False

    def test_the_edits_hold_only_what_a_person_changed_and_the_ids_of_what_they_took_off(
        self, agents: PaperAgents, workspace: Workspace, agent_id: str
    ) -> None:
        mouse = fact_of(card_of(agents, agent_id), "scope", "mouse")
        tissue = fact_of(card_of(agents, agent_id), "scope", "mouse brain tissue")
        agents.change_card_fact(agent_id, mouse["id"], {"aspect": "species", "value": "mouse or rat"})
        agents.remove_card_fact(agent_id, tissue["id"])

        record = json.loads(edits_file(workspace, agent_id).read_text())

        assert set(record) == {"schema", "file_sha256", "facts", "removed", "approval"}
        assert list(record["removed"]) == [tissue["id"]] and list(record["facts"]) == [mouse["id"]]
        assert "GSE123456" not in json.dumps(record) and "STAR" not in json.dumps(record)


class TestAsTheApiHasIt:
    def test_a_person_changes_adds_takes_off_approves_and_discards_through_the_api(
        self, client: TestClient, agents: PaperAgents, agent_id: str
    ) -> None:
        base = f"/api/paperagents/{agent_id}"
        mouse = fact_of(card_of(agents, agent_id), "scope", "mouse")

        changed = client.put(f"{base}/card/facts/{mouse['id']}", json={"fields": {"aspect": "species", "value": "rat"}})
        added = client.post(f"{base}/card/facts", json={"kind": "methods", "fields": {"name": "Our method"}})
        approved = client.post(f"{base}/card/approval")

        assert changed.status_code == added.status_code == approved.status_code == 200
        assert approved.json()["card"]["status"] == "approved"
        assert [fact["by"] for fact in approved.json()["card"]["methods"]] == ["reading", "person"]
        assert client.get(f"{base}/reading").json()["card"] == approved.json()["card"]
        removed = client.delete(f"{base}/card/facts/{mouse['id']}")
        assert removed.json()["card"]["removed"]["scope"][0]["id"] == mouse["id"]
        restored = client.post(f"{base}/card/facts/{mouse['id']}/restore")
        assert restored.status_code == 200 and fact_of(restored.json()["card"], "scope", "mouse")["by"] == "reading"
        assert client.delete(f"{base}/card/approval").json()["card"]["status"] == "draft"
        discarded = client.delete(f"{base}/card/edits")
        assert discarded.json()["card"]["edited"] is False

    def test_a_dataset_that_a_person_adds_is_in_the_data_of_the_agent_as_theirs_and_is_not_said_to_be_the_paper_s(
        self, client: TestClient, agent_id: str
    ) -> None:
        base = f"/api/paperagents/{agent_id}"
        added = client.post(
            f"{base}/card/facts", json={"kind": "datasets", "fields": {"name": "Ours", "accession": "GSE5"}}
        )
        gse = fact_of(added.json()["card"], "datasets", "GEO")
        client.put(f"{base}/card/facts/{gse['id']}", json={"fields": {"name": "GEO", "accession": "GSE7"}})

        found = client.get(f"{base}/data")

        assert added.status_code == found.status_code == 200
        rows = {row["name"]: row for row in found.json()["datasets"]}
        assert (rows["Ours"]["by"], rows["Ours"]["anchor"], rows["Ours"]["candidate"]) == ("person", None, "geo:GSE5")
        assert (rows["GEO"]["by"], rows["GEO"]["anchor"] is None, rows["GEO"]["candidate"]) == (
            "person",
            False,
            "geo:GSE7",
        )
        places = {place["key"]: place for place in found.json()["candidates"]}
        assert places["geo:GSE5"]["facts"] == [] and places["geo:GSE7"]["facts"] == []
        assert "geo:GSE123456" not in places

    def test_what_is_wrong_is_told_as_the_api_tells_it(self, client: TestClient, agent_id: str) -> None:
        base = f"/api/paperagents/{agent_id}"

        assert client.post(f"{base}/card/facts", json={"kind": "claims", "fields": {}}).status_code == 422
        assert client.post(f"{base}/card/facts", json={"fields": {}}).status_code == 422
        assert (
            client.post(f"{base}/card/facts", json={"kind": "methods", "fields": {"name": "x"}, "by": "me"}).status_code
            == 422
        )
        assert client.put(f"{base}/card/facts/scope-00000000", json={"fields": {"value": "x"}}).status_code == 404
        assert client.put(f"{base}/card/facts/scope-00000000", json={"kind": "scope", "fields": {}}).status_code == 422
        assert client.post("/api/paperagents/nowhere/card/approval").status_code == 404

    def test_the_card_is_for_the_person_who_has_the_token(self, client: TestClient, agent_id: str) -> None:
        client.headers.pop("Authorization")

        assert client.post(f"/api/paperagents/{agent_id}/card/approval").status_code == 401
        assert client.post(f"/api/paperagents/{agent_id}/card/approval", headers=BEARER).status_code == 200


def test_the_aspects_of_scope_are_those_that_a_reading_says() -> None:
    assert method_card.ASPECTS == get_args(Scope.model_fields["aspect"].annotation)
