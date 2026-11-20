"""Tests of what a bake-off says its data is and of putting it against the method card of each method's paper: that
the person says what the data is and nothing else does, that each method is shown with what its card says (inside,
outside, not covered, or why it was not put against one), that nothing of that answer is kept and so it follows the card
as it is, and that going on with a method whose card the data is outside of is the person's, is of what they were shown,
and is of that method only. The papers are read with a model that is replaced by a stand-in, and no method is built."""

import threading
from typing import Any

import pytest
from conftest import FakeClient
from fastapi.testclient import TestClient
from test_paperagents_reading import queue, reading
from test_server_bakeoff_building import (
    DOI,
    OTHER_DOI,
    add,
    agents,
    bakeoffs,
    build,
    client,
    containers,
    docker,
    finish,
    git_is_installed,
    jobs,
    marker,
    model_client,
    papers,
    quick,
    remotes,
    replays,
    stack,
    workspace,
)
from test_server_bakeoffs import TASK, person_candidate, record_of, rewrite, why
from test_server_paperagent_card import fact_of

from virtual_lab.paperagents import scope
from virtual_lab.paperagents.reading import ReadScope
from virtual_lab.server import paperagent_bakeoff as kept
from virtual_lab.server.bakeoff_scope import scope_of
from virtual_lab.server.bakeoffs import BUILD_JOB, Bakeoffs
from virtual_lab.server.errors import ApiError
from virtual_lab.server.paperagent_hold import key_of
from virtual_lab.server.paperagents import PaperAgents
from virtual_lab.server.workspace import Workspace

# What the fixtures of the tests of building are, which are used here as they are
__all__ = [
    "agents",
    "bakeoffs",
    "client",
    "containers",
    "docker",
    "git_is_installed",
    "jobs",
    "marker",
    "model_client",
    "papers",
    "quick",
    "remotes",
    "replays",
    "stack",
    "workspace",
]

MOUSE = "tested on mouse brain tissue"
SIZES = "800 to 5,000 nuclei in each sample"
PAPER = (
    "CellMapper assigns a cell type to each cell of a single-nucleus RNA-seq sample. It was developed and "
    f"{MOUSE}, and it was used on {SIZES}."
)
KEY = "a" * 64
WHEN = "2024-01-01T00:00:00Z"


def read_as_mouse_brain() -> Any:
    """What a model says of a paper that says what CellMapper was used on."""
    return reading(
        scope=[
            ReadScope(aspect="species", value="mouse", quote=MOUSE),
            ReadScope(aspect="tissue", value="brain", quote=MOUSE),
            ReadScope(aspect="sample size", value="800 to 5,000 nuclei", quote=SIZES),
        ]
    )


@pytest.fixture
def method(bakeoffs: Bakeoffs, stack: Any, papers: Any, model_client: FakeClient) -> tuple[str, str]:
    """A bake-off of one method whose paper has been read, and which has not been built, since nobody has said where its
    code is. It says nothing of its data."""
    papers.texts[DOI] = PAPER
    bakeoff_id = bakeoffs.create(None, TASK, None, 1.0)
    candidate = add(bakeoffs, bakeoff_id, DOI, "CellMapper")
    queue(model_client, read_as_mouse_brain())
    assert build(bakeoffs, bakeoff_id).state == "succeeded"

    return bakeoff_id, candidate


def shown_scope(bakeoffs: Bakeoffs, bakeoff_id: str, candidate: str) -> dict[str, Any]:
    return dict(next(each for each in bakeoffs.view(bakeoff_id)["candidates"] if each["id"] == candidate)["scope"])


def said(bakeoffs: Bakeoffs, bakeoff_id: str, **facts: Any) -> None:
    bakeoffs.change(bakeoff_id, described=facts)


def described_of(bakeoffs: Bakeoffs, bakeoff_id: str) -> dict[str, Any] | None:
    described = bakeoffs.view(bakeoff_id)["described"]

    return dict(described) if described is not None else None


def agent_of(bakeoffs: Bakeoffs, bakeoff_id: str) -> str:
    return str(bakeoffs.view(bakeoff_id)["candidates"][0]["agent"]["id"])


class TestWhatTheDataIs:
    def test_what_the_person_says_is_kept_as_a_scope_check_takes_it_and_when_they_said_it(
        self, bakeoffs: Bakeoffs, workspace: Workspace
    ) -> None:
        bakeoff_id = bakeoffs.create(
            None,
            TASK,
            None,
            1.0,
            {"species": "  Mus   musculus ", "assay": "snRNA-seq", "sample_size": 800, "sample_unit": " nuclei "},
        )

        saved = record_of(workspace, bakeoff_id)["described"]

        assert saved == {
            "species": "Mus musculus",
            "tissue": "",
            "assay": "snRNA-seq",
            "input_format": "",
            "sample_size": 800,
            "sample_unit": "nuclei",
            "at": saved["at"],
        }
        assert saved["at"] > "2020"
        assert bakeoffs.view(bakeoff_id)["described"] == saved

    def test_a_bake_off_says_nothing_of_its_data_until_the_person_does(self, bakeoffs: Bakeoffs) -> None:
        assert described_of(bakeoffs, bakeoffs.create(None, TASK, None, 1.0)) is None
        for nothing in ({}, {"species": "  ", "sample_size": 0}, {"tissue": None, "sample_unit": ""}):
            assert described_of(bakeoffs, bakeoffs.create(None, TASK, None, 1.0, nothing)) is None

    def test_it_is_said_again_left_as_it_was_or_taken_away(self, bakeoffs: Bakeoffs) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, {"species": "mouse"})

        said(bakeoffs, bakeoff_id, tissue="liver")
        again = described_of(bakeoffs, bakeoff_id)
        assert again is not None and (again["species"], again["tissue"]) == ("", "liver")

        bakeoffs.change(bakeoff_id, title="Another")
        unchanged = described_of(bakeoffs, bakeoff_id)
        assert unchanged is not None and unchanged["tissue"] == "liver"

        said(bakeoffs, bakeoff_id)
        assert described_of(bakeoffs, bakeoff_id) is None

    @pytest.mark.parametrize(
        "given",
        [
            "mouse",
            ["mouse"],
            {"organism": "mouse"},
            {"organism": "mouse", "species": "mouse"},
            ["species"],
            {"species": 3},
            {"species": ["mouse"]},
            {"species": "x" * 201},
            {"species": "mouse\x00"},
            {"tissue": "---"},
            {"sample_size": -3, "sample_unit": "cells"},
            {"sample_size": True, "sample_unit": "cells"},
            {"sample_size": 2.5, "sample_unit": "cells"},
            {"sample_size": "800", "sample_unit": "cells"},
            {"sample_size": 10**13, "sample_unit": "cells"},
            {"sample_unit": "cells"},
            {"sample_size": 5, "sample_unit": "c" * 41},
        ],
        ids=range(17),
    )
    def test_what_is_not_said_as_a_scope_check_takes_it_is_refused_and_nothing_is_kept(
        self, bakeoffs: Bakeoffs, workspace: Workspace, given: Any
    ) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, {"species": "mouse"})
        before = record_of(workspace, bakeoff_id)

        assert why(bakeoffs.change, bakeoff_id, described=given) == (422, "invalid")
        assert why(bakeoffs.create, None, TASK, None, 1.0, given) == (422, "invalid")

        assert record_of(workspace, bakeoff_id) == before
        assert len(bakeoffs.kept()) == 1

    def test_it_is_not_said_again_while_the_methods_are_being_built(self, bakeoffs: Bakeoffs) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, {"species": "mouse"})
        gate = threading.Event()
        job = bakeoffs.jobs.start(
            BUILD_JOB, bakeoff_id, "Building", lambda running: gate.wait(10) and None, exclusive=f"bakeoff:{bakeoff_id}"
        )
        try:
            assert why(bakeoffs.change, bakeoff_id, described={"species": "rat"}) == (409, "busy")
        finally:
            gate.set()
            finish(job)

        assert (described_of(bakeoffs, bakeoff_id) or {})["species"] == "mouse"

    def test_a_person_says_it_through_the_api(self, client: TestClient) -> None:
        said_of = {"species": "mouse", "sample_size": 800, "sample_unit": "nuclei"}
        made = client.post("/api/bakeoffs", json={"task": TASK, "limit": 1, "described": said_of})
        assert made.status_code == 201
        bakeoff_id = made.json()["id"]
        assert made.json()["described"]["species"] == "mouse"

        again = client.patch(f"/api/bakeoffs/{bakeoff_id}", json={"described": {"tissue": "brain"}})
        assert (again.status_code, again.json()["described"]["tissue"], again.json()["described"]["species"]) == (
            200,
            "brain",
            "",
        )
        untouched = client.patch(f"/api/bakeoffs/{bakeoff_id}", json={"title": "Another"})
        assert (untouched.status_code, untouched.json()["described"]["tissue"]) == (200, "brain")
        for bad in ({"species": 3}, {"sample_size": "many"}, {"organism": "mouse"}, "mouse"):
            assert client.patch(f"/api/bakeoffs/{bakeoff_id}", json={"described": bad}).status_code == 422
        cleared = client.patch(f"/api/bakeoffs/{bakeoff_id}", json={"described": {}})
        assert (cleared.status_code, cleared.json()["described"]) == (200, None)


class TestWhatTheCardSays:
    def test_a_method_is_not_put_against_a_card_before_there_is_one_and_it_says_why(
        self, bakeoffs: Bakeoffs, agents: PaperAgents
    ) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0)
        method = add(bakeoffs, bakeoff_id, DOI, "CellMapper")

        nothing = shown_scope(bakeoffs, bakeoff_id, method)
        assert (nothing["checked"], nothing["why"], nothing["outcome"], nothing["key"]) == (
            False,
            "no_description",
            None,
            None,
        )
        assert "Say what it is" in nothing["reason"]
        assert (nothing["went_on"], nothing["went_on_at"]) == (False, None)

        said(bakeoffs, bakeoff_id, species="mouse")
        none_yet = shown_scope(bakeoffs, bakeoff_id, method)
        assert (none_yet["checked"], none_yet["why"]) == (False, "no_agent")
        assert "Building the method makes one" in none_yet["reason"]
        assert none_yet["went_on"] is False

        agents.create("CellMapper", {"kind": "doi", "doi": DOI})
        unread = shown_scope(bakeoffs, bakeoff_id, method)
        assert (unread["checked"], unread["why"], unread["warnings"], unread["of"]) == (False, "not_read", [], [])
        assert "has not been read" in unread["reason"]
        assert unread["went_on"] is False

    def test_data_outside_what_the_card_says_is_warned_of_with_the_cards_words_and_the_papers(
        self, bakeoffs: Bakeoffs, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = method
        said(bakeoffs, bakeoff_id, species="zebrafish", tissue="brain")

        found = shown_scope(bakeoffs, bakeoff_id, candidate)

        assert (found["checked"], found["why"], found["outcome"]) == (True, None, scope.OUTSIDE)
        assert len(found["warnings"]) == 1
        assert "the data's species is “zebrafish”" in found["warnings"][0]
        assert f"“mouse” (the paper: “{MOUSE}”)" in found["warnings"][0]
        assert [(each["aspect"], each["outcome"]) for each in found["of"]] == [
            ("species", scope.OUTSIDE),
            ("tissue", scope.INSIDE),
        ]
        assert found["of"][0]["says"][0]["quote"] == MOUSE
        assert (found["card"]["status"], found["reading"]["complete"]) == ("draft", True)
        assert "a model did not" in found["notes"][0]
        assert (found["went_on"], found["went_on_at"]) == (False, None)
        assert len(found["key"]) == 64

    def test_data_inside_it_has_no_warning_and_nothing_to_go_on_with(
        self, bakeoffs: Bakeoffs, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = method
        said(bakeoffs, bakeoff_id, species="Mus musculus", tissue="brain", sample_size=1000, sample_unit="nuclei")

        found = shown_scope(bakeoffs, bakeoff_id, candidate)

        assert (found["outcome"], found["warnings"], found["went_on"]) == (scope.INSIDE, [], False)
        assert [each["outcome"] for each in found["of"]] == [scope.INSIDE] * 3

    def test_what_the_card_does_not_say_of_is_not_covered_and_is_not_warned_of(
        self, bakeoffs: Bakeoffs, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = method
        said(bakeoffs, bakeoff_id, assay="snRNA-seq")

        found = shown_scope(bakeoffs, bakeoff_id, candidate)

        assert (found["outcome"], found["warnings"]) == (scope.NOT_COVERED, [])
        assert found["of"][0]["reason"] == "The card has no statement of the assay."

    def test_what_the_card_says_of_what_nothing_was_said_of_is_given(
        self, bakeoffs: Bakeoffs, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = method
        said(bakeoffs, bakeoff_id, species="mouse")

        found = shown_scope(bakeoffs, bakeoff_id, candidate)

        assert sorted(each["aspect"] for each in found["not_checked"]) == ["sample size", "tissue"]

    def test_the_answer_follows_the_card_as_it_is_and_is_not_kept(
        self, bakeoffs: Bakeoffs, agents: PaperAgents, workspace: Workspace, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = method
        said(bakeoffs, bakeoff_id, species="zebrafish")
        file = workspace.bakeoffs_dir / bakeoff_id / kept.RECORD_FILE
        before = file.read_bytes()
        assert shown_scope(bakeoffs, bakeoff_id, candidate)["outcome"] == scope.OUTSIDE

        agent_id = agent_of(bakeoffs, bakeoff_id)
        agents.add_card_fact(agent_id, "scope", {"aspect": "species", "value": "zebrafish", "quote": "Our notebook"})
        now = shown_scope(bakeoffs, bakeoff_id, candidate)
        assert (now["outcome"], now["warnings"]) == (scope.INSIDE, [])
        assert now["card"]["edited"] is True and now["of"][0]["says"][0]["by"] == "person"

        agents.approve_card(agent_id)
        assert shown_scope(bakeoffs, bakeoff_id, candidate)["card"]["status"] == "approved"
        assert file.read_bytes() == before

    def test_a_paper_that_the_agent_has_not_been_read_of_is_not_a_card_that_covers_nothing(
        self, bakeoffs: Bakeoffs, agents: PaperAgents, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = method
        said(bakeoffs, bakeoff_id, species="zebrafish")
        agents.clear_reading(agent_of(bakeoffs, bakeoff_id))

        found = shown_scope(bakeoffs, bakeoff_id, candidate)

        assert (found["checked"], found["why"], found["outcome"]) == (False, "not_read", None)

    def test_an_agent_that_is_taken_away_as_it_is_looked_at_is_a_method_with_none(
        self, bakeoffs: Bakeoffs, monkeypatch: pytest.MonkeyPatch, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = method
        said(bakeoffs, bakeoff_id, species="zebrafish")

        def gone(agent_id: str, facts: dict[str, Any]) -> Any:
            raise ApiError(404, "not_found", "no PaperAgent with that id")

        monkeypatch.setattr(bakeoffs.paperagents, "check_scope", gone)

        found = shown_scope(bakeoffs, bakeoff_id, candidate)

        assert (found["checked"], found["why"], found["went_on"]) == (False, "no_agent", False)

    def test_what_goes_wrong_in_the_check_other_than_there_being_no_agent_is_not_hidden(
        self, bakeoffs: Bakeoffs, monkeypatch: pytest.MonkeyPatch, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = method
        said(bakeoffs, bakeoff_id, species="zebrafish")

        def broken(agent_id: str, facts: dict[str, Any]) -> Any:
            raise ApiError(409, "busy", "in the middle of something")

        monkeypatch.setattr(bakeoffs.paperagents, "check_scope", broken)

        assert why(shown_scope, bakeoffs, bakeoff_id, candidate) == (409, "busy")

    @pytest.mark.parametrize(
        ("outcome", "warnings", "went_on"),
        [(scope.OUTSIDE, ["the data is outside"], True), (scope.INSIDE, [], False), (scope.NOT_COVERED, [], False)],
    )
    def test_going_on_counts_only_where_the_data_is_outside_even_if_its_key_is_that_of_what_was_shown(
        self, outcome: str, warnings: list[str], went_on: bool
    ) -> None:
        described = {"species": "zebrafish", "tissue": "", "assay": "", "input_format": "", "sample_size": 0}
        described = {**described, "sample_unit": "", "at": WHEN}
        result = {
            "outcome": outcome,
            "aspects": [],
            "not_checked": [],
            "warnings": warnings,
            "card": {"status": "draft"},
            "reading": {"chunks": 3, "complete": True},
            "notes": [],
        }

        class Stand:
            def check_scope(self, agent_id: str, facts: dict[str, Any]) -> dict[str, Any]:
                return result

        key = key_of(kept.facts_of(described), warnings)
        candidate = {"went_on": {"key": key, "at": WHEN}}

        found = scope_of(Stand(), described, candidate, "agent")  # type: ignore[arg-type]

        assert (found["checked"], found["outcome"], found["key"], found["went_on"]) == (True, outcome, key, went_on)
        assert found["went_on_at"] == (WHEN if went_on else None)

    def test_each_method_is_put_against_the_card_of_its_own_paper(
        self, bakeoffs: Bakeoffs, papers: Any, stack: Any, model_client: FakeClient
    ) -> None:
        papers.texts[DOI] = PAPER
        papers.texts[OTHER_DOI] = PAPER.replace("mouse", "zebrafish").replace("CellMapper", "Labeller")
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, {"species": "zebrafish"})
        first = add(bakeoffs, bakeoff_id, DOI, "CellMapper")
        second = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller")
        queue(
            model_client,
            read_as_mouse_brain(),
            reading(scope=[ReadScope(aspect="species", value="zebrafish", quote=MOUSE.replace("mouse", "zebrafish"))]),
        )
        build(bakeoffs, bakeoff_id)

        assert shown_scope(bakeoffs, bakeoff_id, first)["outcome"] == scope.OUTSIDE
        assert shown_scope(bakeoffs, bakeoff_id, second)["outcome"] == scope.INSIDE


class TestGoingOn:
    def outside(self, bakeoffs: Bakeoffs, method: tuple[str, str]) -> tuple[str, str, str]:
        bakeoff_id, candidate = method
        said(bakeoffs, bakeoff_id, species="zebrafish")

        return bakeoff_id, candidate, str(shown_scope(bakeoffs, bakeoff_id, candidate)["key"])

    def test_the_person_goes_on_with_what_they_were_shown_and_it_is_kept_with_when(
        self, bakeoffs: Bakeoffs, workspace: Workspace, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate, key = self.outside(bakeoffs, method)

        bakeoffs.go_on_with(bakeoff_id, candidate, key)

        found = shown_scope(bakeoffs, bakeoff_id, candidate)
        assert (found["outcome"], found["went_on"]) == (scope.OUTSIDE, True)
        went_on = record_of(workspace, bakeoff_id)["candidates"][0]["went_on"]
        assert went_on == {"key": key, "at": found["went_on_at"]}

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            (3, (422, "invalid")),
            ("zz", (422, "invalid")),
            ("A" * 64, (422, "invalid")),
            ("b" * 64, (409, "changed")),
        ],
    )
    def test_what_is_not_the_key_of_what_they_were_shown_is_not_gone_on_with(
        self, bakeoffs: Bakeoffs, workspace: Workspace, method: tuple[str, str], key: Any, expected: tuple[int, str]
    ) -> None:
        bakeoff_id, candidate, _ = self.outside(bakeoffs, method)

        assert why(bakeoffs.go_on_with, bakeoff_id, candidate, key) == expected

        assert record_of(workspace, bakeoff_id)["candidates"][0]["went_on"] is None
        assert shown_scope(bakeoffs, bakeoff_id, candidate)["went_on"] is False

    def test_there_is_nothing_to_go_on_with_where_the_data_is_not_outside_the_card(
        self, bakeoffs: Bakeoffs, workspace: Workspace, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = method
        key = shown_scope(bakeoffs, bakeoff_id, candidate)["key"]
        assert key is None and why(bakeoffs.go_on_with, bakeoff_id, candidate, KEY) == (409, "not_outside")

        said(bakeoffs, bakeoff_id, species="mouse")
        inside = shown_scope(bakeoffs, bakeoff_id, candidate)
        assert inside["outcome"] == scope.INSIDE
        assert why(bakeoffs.go_on_with, bakeoff_id, candidate, inside["key"]) == (409, "not_outside")

        said(bakeoffs, bakeoff_id, assay="snRNA-seq")
        not_covered = shown_scope(bakeoffs, bakeoff_id, candidate)
        assert not_covered["outcome"] == scope.NOT_COVERED
        assert why(bakeoffs.go_on_with, bakeoff_id, candidate, not_covered["key"]) == (409, "not_outside")
        assert record_of(workspace, bakeoff_id)["candidates"][0]["went_on"] is None

    def test_going_on_is_of_every_fact_that_was_said_of_the_data_and_not_only_of_what_it_is_outside_of(
        self, bakeoffs: Bakeoffs, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate, key = self.outside(bakeoffs, method)
        bakeoffs.go_on_with(bakeoff_id, candidate, key)
        shown = shown_scope(bakeoffs, bakeoff_id, candidate)

        said(bakeoffs, bakeoff_id, species="zebrafish", assay="snRNA-seq")

        other = shown_scope(bakeoffs, bakeoff_id, candidate)
        assert (other["outcome"], other["went_on"]) == (scope.OUTSIDE, False)
        assert other["warnings"] == shown["warnings"]
        assert other["key"] != key
        assert why(bakeoffs.go_on_with, bakeoff_id, candidate, key) == (409, "changed")

    def test_there_is_no_going_on_with_what_is_not_there(self, bakeoffs: Bakeoffs, method: tuple[str, str]) -> None:
        bakeoff_id, candidate, key = self.outside(bakeoffs, method)

        assert why(bakeoffs.go_on_with, bakeoff_id, "00000000", key) == (404, "not_found")
        assert why(bakeoffs.go_on_with, "00000000", candidate, key) == (404, "not_found")
        assert why(bakeoffs.take_back, bakeoff_id, "00000000") == (404, "not_found")
        assert why(bakeoffs.take_back, "00000000", candidate) == (404, "not_found")

    def test_going_on_is_of_the_data_as_it_was_said_and_holds_again_if_it_is_said_so_again(
        self, bakeoffs: Bakeoffs, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate, key = self.outside(bakeoffs, method)
        bakeoffs.go_on_with(bakeoff_id, candidate, key)

        said(bakeoffs, bakeoff_id, species="rat")
        other = shown_scope(bakeoffs, bakeoff_id, candidate)
        assert (other["outcome"], other["went_on"], other["went_on_at"]) == (scope.OUTSIDE, False, None)
        assert other["key"] != key
        assert why(bakeoffs.go_on_with, bakeoff_id, candidate, key) == (409, "changed")

        said(bakeoffs, bakeoff_id, species="zebrafish")
        assert shown_scope(bakeoffs, bakeoff_id, candidate)["went_on"] is True

    def test_going_on_is_of_the_words_of_the_card_that_they_were_shown(
        self, bakeoffs: Bakeoffs, agents: PaperAgents, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate, key = self.outside(bakeoffs, method)
        bakeoffs.go_on_with(bakeoff_id, candidate, key)
        card = agents.reading(agent_of(bakeoffs, bakeoff_id))["card"]

        agents.change_card_fact(
            agent_of(bakeoffs, bakeoff_id), fact_of(card, "scope", "mouse")["id"], {"aspect": "species", "value": "rat"}
        )

        now = shown_scope(bakeoffs, bakeoff_id, candidate)
        assert (now["outcome"], now["went_on"]) == (scope.OUTSIDE, False)
        assert "“rat” (changed by a person" in now["warnings"][0] and now["key"] != key

    def test_going_on_is_not_kept_up_once_the_data_is_inside_the_card(
        self, bakeoffs: Bakeoffs, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate, key = self.outside(bakeoffs, method)
        bakeoffs.go_on_with(bakeoff_id, candidate, key)

        said(bakeoffs, bakeoff_id, species="mouse")

        found = shown_scope(bakeoffs, bakeoff_id, candidate)
        assert (found["outcome"], found["went_on"], found["went_on_at"]) == (scope.INSIDE, False, None)

    def test_the_person_may_take_it_back_and_taking_back_what_was_not_said_changes_nothing(
        self, bakeoffs: Bakeoffs, workspace: Workspace, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate, key = self.outside(bakeoffs, method)
        bakeoffs.take_back(bakeoff_id, candidate)
        assert record_of(workspace, bakeoff_id)["candidates"][0]["went_on"] is None

        bakeoffs.go_on_with(bakeoff_id, candidate, key)
        assert shown_scope(bakeoffs, bakeoff_id, candidate)["went_on"] is True
        bakeoffs.take_back(bakeoff_id, candidate)

        assert shown_scope(bakeoffs, bakeoff_id, candidate)["went_on"] is False
        assert record_of(workspace, bakeoff_id)["candidates"][0]["went_on"] is None

    def test_going_on_is_with_one_method_and_not_with_the_others(
        self, bakeoffs: Bakeoffs, papers: Any, stack: Any, model_client: FakeClient
    ) -> None:
        papers.texts[DOI] = PAPER
        papers.texts[OTHER_DOI] = PAPER.replace("CellMapper", "Labeller")
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, {"species": "zebrafish"})
        first = add(bakeoffs, bakeoff_id, DOI, "CellMapper")
        second = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller")
        queue(model_client, read_as_mouse_brain(), read_as_mouse_brain())
        build(bakeoffs, bakeoff_id)
        key = shown_scope(bakeoffs, bakeoff_id, first)["key"]
        assert key == shown_scope(bakeoffs, bakeoff_id, second)["key"]

        bakeoffs.go_on_with(bakeoff_id, first, key)

        assert shown_scope(bakeoffs, bakeoff_id, first)["went_on"] is True
        assert shown_scope(bakeoffs, bakeoff_id, second)["went_on"] is False

    def test_a_person_goes_on_and_takes_it_back_through_the_api(
        self, client: TestClient, bakeoffs: Bakeoffs, method: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = method
        client.patch(f"/api/bakeoffs/{bakeoff_id}", json={"described": {"species": "zebrafish"}})
        url = f"/api/bakeoffs/{bakeoff_id}/candidates/{candidate}/go-on"
        shown = next(each for each in client.get(f"/api/bakeoffs/{bakeoff_id}").json()["candidates"])["scope"]
        assert shown["outcome"] == scope.OUTSIDE

        assert client.post(url, json={}).status_code == 422
        assert client.post(url, json={"key": "b" * 64}).status_code == 409
        went = client.post(url, json={"key": shown["key"]})
        assert went.status_code == 200 and went.json()["candidates"][0]["scope"]["went_on"] is True

        taken = client.delete(url)
        assert taken.status_code == 200 and taken.json()["candidates"][0]["scope"]["went_on"] is False
        assert client.post(url.replace(candidate, "00000000"), json={"key": shown["key"]}).status_code == 404


class TestWhatIsKept:
    def test_a_bake_off_kept_before_the_data_could_be_said_is_read_as_one_whose_data_is_not_said(
        self, bakeoffs: Bakeoffs, workspace: Workspace
    ) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0)
        rewrite(workspace, bakeoff_id, lambda record: record["candidates"].append(person_candidate(DOI)))

        def earlier(record: dict[str, Any]) -> None:
            record["schema"] = 2
            del record["described"]
            for candidate in record["candidates"]:
                del candidate["went_on"]

        rewrite(workspace, bakeoff_id, earlier)

        [(_, loaded)] = bakeoffs.kept()
        assert (loaded["schema"], loaded["described"]) == (kept.SCHEMA, None)
        assert [each["went_on"] for each in loaded["candidates"]] == [None]
        bakeoffs.change(bakeoff_id, described={"species": "mouse"})
        assert record_of(workspace, bakeoff_id)["schema"] == kept.SCHEMA

    @pytest.mark.parametrize(
        "damage",
        [
            lambda record: record.update(described={}),
            lambda record: record["described"].update(species="", sample_size=0),
            lambda record: record["described"].update(species="mouse\x00"),
            lambda record: record["described"].update(at="2024\x00"),
            lambda record: record["described"].update(sample_size=True),
            lambda record: record["described"].update(sample_size=2.5),
            lambda record: record["described"].update(sample_size=-1),
            lambda record: record["described"].update(sample_unit="nuclei", sample_size=0),
            lambda record: record["described"].update(species=3),
            lambda record: record["described"].pop("tissue"),
            lambda record: record["candidates"][0].update(went_on={"key": "xyz", "at": WHEN}),
            lambda record: record["candidates"][0].update(went_on={"key": "A" * 64, "at": WHEN}),
            lambda record: record["candidates"][0].update(went_on={"key": KEY, "at": "2024\x00"}),
            lambda record: record["candidates"][0].update(went_on={"key": KEY}),
            lambda record: record["candidates"][0].update(went_on="yes"),
            lambda record: record["candidates"][0].pop("went_on"),
        ],
        ids=range(16),
    )
    def test_a_file_that_says_what_the_data_is_or_what_was_gone_on_with_in_another_shape_is_not_used(
        self, bakeoffs: Bakeoffs, workspace: Workspace, damage: Any
    ) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, {"species": "mouse"})
        rewrite(workspace, bakeoff_id, lambda record: record["candidates"].append(person_candidate(DOI)))
        assert len(bakeoffs.kept()) == 1

        rewrite(workspace, bakeoff_id, damage)

        assert bakeoffs.kept() == []

    def test_a_file_of_the_second_version_with_a_method_that_has_no_saying_of_its_building_is_not_used(
        self, bakeoffs: Bakeoffs, workspace: Workspace
    ) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0)
        rewrite(workspace, bakeoff_id, lambda record: record["candidates"].append(person_candidate(DOI)))

        def earlier(record: dict[str, Any]) -> None:
            record["schema"] = 2
            del record["described"]
            for candidate in record["candidates"]:
                del candidate["went_on"]
                del candidate["build"]

        rewrite(workspace, bakeoff_id, earlier)

        assert bakeoffs.kept() == []

    def test_what_was_gone_on_with_is_read_back_as_it_was_kept(self, bakeoffs: Bakeoffs, workspace: Workspace) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0)
        rewrite(
            workspace,
            bakeoff_id,
            lambda record: record["candidates"].append({**person_candidate(DOI), "went_on": {"key": KEY, "at": WHEN}}),
        )

        [(_, loaded)] = bakeoffs.kept()

        assert loaded["candidates"][0]["went_on"] == {"key": KEY, "at": WHEN}
