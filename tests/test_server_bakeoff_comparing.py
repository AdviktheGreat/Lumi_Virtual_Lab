"""Tests of putting the methods of a bake-off side by side: that each is a row with how it came out or why it did not,
what it cost in reading its paper and in asking a model for the call, and the tier of its tool, that methods that gave
answers are held to each other within a tolerance the person can set, that what was kept only as a hash or a look is
not said to agree, that two runs on the data as it was listed at different times are not compared, and that nothing is
ranked unless the person has said where the right answers are, and that then each method is held to them, and ranked
by that and nothing else. Docker, the containers that tools are called in, and the model are stand-ins, as they are in
the tests of running."""

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeClient, make_usage
from fastapi.testclient import TestClient
from test_paperagents_reading import queue, reading
from test_server_bakeoff_applying import PROPOSE, proposal, say
from test_server_bakeoff_building import (
    FIRST_CODE,
    SECOND_CODE,
    THIRD_CODE,
    THIRD_DOI,
    Papers,
    Remotes,
    add,
    agents,
    bakeoffs,
    build,
    client,
    containers,
    docker,
    git_is_installed,
    jobs,
    marker,
    model_client,
    paper_of,
    papers,
    quick,
    remotes,
    replays,
    stack,
    workspace,
)
from test_server_bakeoff_running import (
    DATA,
    MAP,
    TALLY,
    answer,
    built,
    file_of,
    own_data,
    read_as_mouse_brain,
    reader,
    run,
    text_of,
    two,
)
from test_server_bakeoffs import DOI, OTHER_DOI, TASK, TOKEN, unit_cost
from test_server_paperagent_tools import Replays, gives

from virtual_lab.paperagents import agreeing, labelling, scoring
from virtual_lab.paperagents import bakeoff_table as table
from virtual_lab.paperagents.reading import ReadLicense, ReadLink, ReadScope
from virtual_lab.server import bakeoff_comparing as comparing_says
from virtual_lab.server.app import create_app
from virtual_lab.server.bakeoffs import Bakeoffs
from virtual_lab.server.own import Own
from virtual_lab.server.workspace import Workspace

# What the fixtures of the tests of building and of running are, which are used here as they are
__all__ = [
    "agents",
    "bakeoffs",
    "built",
    "client",
    "containers",
    "docker",
    "git_is_installed",
    "jobs",
    "marker",
    "model_client",
    "own_data",
    "papers",
    "quick",
    "reader",
    "remotes",
    "replays",
    "stack",
    "two",
    "workspace",
]

ZEBRAFISH = "tested on zebrafish embryos"
SAYS_WITHOUT = comparing_says.SAYS
RIGHT = b"cell,type\nc1,T\nc2,B\nc3,T\n"
SAID = {"own": "truth.csv", "column": "type"}
SAID_BY_CELL = {**SAID, "id_column": "cell"}


def rows_of(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8"))))


def by_name(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {method["name"]: method for method in found["methods"]}


def give_right_answers(workspace: Workspace, content: bytes = RIGHT, name: str = "truth.csv") -> Path:
    Own(workspace, 1_000_000).add_upload(name, io.BytesIO(content), "What each cell is")

    return workspace.own_data_dir / name


def scores_of(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {name: method["score"] for name, method in by_name(found).items()}


@pytest.fixture
def three(
    bakeoffs: Bakeoffs,
    own_data: Path,
    reader: None,
    papers: Papers,
    stack: Remotes,
    model_client: FakeClient,
) -> tuple[str, str, str, str]:
    """A bake-off of three methods on the person's counts.csv, which is of mouse: the first is built and its card says
    mouse, the second is built and its card says zebrafish, and the third cannot be built, as its code is only words."""
    papers.texts[DOI] = text_of("CellMapper", FIRST_CODE)
    papers.texts[OTHER_DOI] = f"{paper_of('Labeller', SECOND_CODE)} It was developed and {ZEBRAFISH}."
    papers.texts[THIRD_DOI] = paper_of("GraphCells", THIRD_CODE)
    stack.by_address[THIRD_CODE] = {"README.md": "# GraphCells\n\nNothing here but words.\n"}
    bakeoff_id = bakeoffs.create(None, TASK, DATA, 1.0)
    first = add(bakeoffs, bakeoff_id, DOI, "CellMapper", FIRST_CODE)
    second = add(bakeoffs, bakeoff_id, OTHER_DOI, "Labeller", SECOND_CODE)
    third = add(bakeoffs, bakeoff_id, THIRD_DOI, "GraphCells", THIRD_CODE)
    queue(
        model_client,
        read_as_mouse_brain(FIRST_CODE),
        reading(
            links=[ReadLink(url=SECOND_CODE, role="code", quote=f"The analysis code is at {SECOND_CODE}")],
            licenses=[ReadLicense(name="MIT", covers="code", quote="is released under the MIT license")],
            scope=[ReadScope(aspect="species", value="zebrafish", quote=ZEBRAFISH)],
        ),
    )
    assert build(bakeoffs, bakeoff_id).state == "succeeded"
    bakeoffs.change(bakeoff_id, described={"species": "mouse"})

    return bakeoff_id, first, second, third


class TestTheMethodsSideBySide:
    def test_a_method_that_cannot_be_built_one_that_is_outside_its_card_and_one_that_runs_are_each_a_row_with_why(
        self, bakeoffs: Bakeoffs, replays: Replays, three: tuple[str, str, str, str]
    ) -> None:
        bakeoff_id, first, second, third = three
        replays.plays["map_cells"] = gives([1, 2, 3])

        run(bakeoffs, bakeoff_id, {first: MAP, second: MAP})
        found = bakeoffs.comparison(bakeoff_id)

        assert [method["id"] for method in found["methods"]] == [first, second, third]
        ran, outside, unbuilt = found["methods"]
        assert (ran["name"], ran["state"], ran["why"], ran["reason"]) == ("CellMapper", "ran", None, "")
        assert (ran["tier"], ran["tool"], ran["by"], ran["kept"], ran["since"]) == (
            "A",
            "map_cells",
            "person",
            "whole",
            [],
        )
        assert ran["seconds"] == 0.1 and ran["cost"]["asking"] == 0.0
        assert ran["cost"]["reading"] == pytest.approx(unit_cost())
        assert (outside["name"], outside["state"], outside["why"]) == ("Labeller", "not_run", "outside")
        assert "outside what the method card of this method's paper says" in outside["reason"]
        assert (outside["tier"], outside["tool"], outside["seconds"], outside["kept"]) == (None, None, None, None)
        assert (unbuilt["name"], unbuilt["state"], unbuilt["why"]) == ("GraphCells", "not_built", "no_go")
        assert unbuilt["reason"].startswith("No-go: No code was found")
        assert unbuilt["by"] is None and unbuilt["cost"]["asking"] is None and unbuilt["cost"]["reading"] == 0
        assert found["pairs"] == []
        assert all(method[each] == [] for method in found["methods"] for each in ("agrees", "differs", "unknown"))

    def test_nothing_is_ranked_and_the_comparison_says_that_there_is_no_answer_that_is_known_to_be_right(
        self, bakeoffs: Bakeoffs, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, *_ = two

        found = bakeoffs.comparison(bakeoff_id)

        assert found["ranked"] is False and found["ground_truth"] is None
        assert "not ranked" in found["says"] and "Agreeing is not being right" in found["says"]
        assert found["meaning"] == agreeing.MEANING
        assert found["tolerance"] == {"relative": 1e-6, "absolute": 1e-9}
        assert found["task"] == TASK and found["limit"] == 1.0
        assert not any("rank" in column.lower() for column in table.PAIR_COLUMNS)
        assert [method["score"] for method in found["methods"]] == [None] * len(found["methods"])
        rows = table.method_rows(found)
        assert {row[column] for row in rows for column in ("Score", "Matched", "Of labels", "Rank")} == {""}

    def test_methods_that_are_built_and_were_not_run_are_said_to_be_so_and_are_not_left_out(
        self, bakeoffs: Bakeoffs, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two

        found = bakeoffs.comparison(bakeoff_id)

        assert [(each["state"], each["why"]) for each in found["methods"]] == [("not_run", "not_yet")] * 2
        assert found["methods"][0]["reason"] == "It is built, and has not been run."
        assert found["pairs"] == []

    def test_a_method_that_failed_is_a_row_with_the_way_it_failed(
        self, bakeoffs: Bakeoffs, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        replays.plays["map_cells"] = gives([1, 2, 3])
        replays.plays["tally"] = answer(
            None, ok=False, error={"type": "ValueError", "message": "no", "traceback": [], "cell": None}
        )

        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})
        found = by_name(bakeoffs.comparison(bakeoff_id))

        assert (found["CellMapper"]["state"], found["Labeller"]["state"], found["Labeller"]["why"]) == (
            "ran",
            "failed",
            "error",
        )
        assert "ValueError" in found["Labeller"]["reason"] and found["Labeller"]["tier"] == "A"
        assert bakeoffs.comparison(bakeoff_id)["pairs"] == []

    def test_methods_that_gave_answers_are_held_to_each_other_within_the_tolerance_that_is_given(
        self, bakeoffs: Bakeoffs, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        replays.plays["map_cells"] = gives([1.0, 2.0, 3.0])
        replays.plays["tally"] = gives([1.0 + 1e-8, 2.0, 3.0])
        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        near = bakeoffs.comparison(bakeoff_id)
        exact = bakeoffs.comparison(bakeoff_id, relative=1e-12, absolute=0)

        [pair] = near["pairs"]
        assert (pair["first"], pair["second"], pair["verdict"], pair["differences"]) == (first, second, "agree", [])
        assert pair["kept"] == ["whole", "whole"]
        assert [(each["agrees"], each["differs"]) for each in near["methods"]] == [([second], []), ([first], [])]
        [apart] = exact["pairs"]
        assert apart["verdict"] == "differ" and apart["differences"] == ["[0] is 1.0 against 1.00000001"]
        assert exact["tolerance"] == {"relative": 1e-12, "absolute": 0}
        assert [(each["agrees"], each["differs"]) for each in exact["methods"]] == [([], [second]), ([], [first])]

    def test_what_was_kept_only_as_a_look_is_not_said_to_agree_or_to_differ(
        self, bakeoffs: Bakeoffs, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        replays.plays["map_cells"] = gives([1, 2])
        replays.plays["tally"] = answer({"type": "list", "plain": False, "repr": "[array([1, 2])]"})
        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        found = bakeoffs.comparison(bakeoff_id)

        [pair] = found["pairs"]
        assert pair["verdict"] == "unknown" and pair["kept"] == ["whole", "look"]
        assert [(each["agrees"], each["differs"], each["unknown"]) for each in found["methods"]] == [
            ([], [], [second]),
            ([], [], [first]),
        ]
        assert [each["kept"] for each in found["methods"]] == ["whole", "look"]

    def test_two_runs_on_the_data_as_it_was_listed_at_different_times_are_not_compared(
        self, bakeoffs: Bakeoffs, replays: Replays, two: tuple[str, str, str], own_data: Path
    ) -> None:
        bakeoff_id, first, second = two
        replays.plays["map_cells"] = gives([1, 2, 3])
        replays.plays["tally"] = gives([1, 2, 3])
        run(bakeoffs, bakeoff_id, {first: MAP})
        own_data.write_bytes(own_data.read_bytes() + b"more\n")
        run(bakeoffs, bakeoff_id, {second: TALLY})

        found = bakeoffs.comparison(bakeoff_id)

        [pair] = found["pairs"]
        assert pair["verdict"] == "unknown" and "different times" in pair["how"]
        assert found["methods"][0]["since"] == ["data"] and found["methods"][1]["since"] == []

    def test_what_asking_a_model_for_the_call_cost_is_kept_apart_from_what_reading_the_paper_did(
        self, bakeoffs: Bakeoffs, replays: Replays, two: tuple[str, str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, first, second = two
        replays.plays["map_cells"] = gives([1, 2, 3])
        say(model_client, proposal(usage=make_usage(300, 50)))

        run(bakeoffs, bakeoff_id, {first: MAP, second: PROPOSE})
        found = by_name(bakeoffs.comparison(bakeoff_id))

        assert found["CellMapper"]["cost"] == {"reading": pytest.approx(unit_cost()), "asking": 0.0}
        assert found["Labeller"]["cost"] == {
            "reading": pytest.approx(unit_cost()),
            "asking": pytest.approx(unit_cost(300, 50)),
        }
        assert (found["CellMapper"]["by"], found["Labeller"]["by"]) == ("person", "model")

    def test_a_tolerance_that_is_not_one_is_refused(self, bakeoffs: Bakeoffs, two: tuple[str, str, str]) -> None:
        bakeoff_id, *_ = two

        for relative, absolute in ((1, 0), (-1e-3, 0), (1e-6, -1), (float("nan"), 0), (1e-6, float("inf"))):
            with pytest.raises(Exception) as caught:
                bakeoffs.comparison(bakeoff_id, relative, absolute)
            assert getattr(caught.value, "status", None) == 422, (relative, absolute)

    def test_a_bakeoff_that_is_not_there_is_not_found(self, bakeoffs: Bakeoffs) -> None:
        with pytest.raises(Exception) as caught:
            bakeoffs.comparison("0" * 8)

        assert getattr(caught.value, "status", None) == 404


class TestHeldToTheRightAnswers:
    def test_each_method_that_gave_an_answer_is_scored_by_how_many_labels_it_matched_and_ranked_by_that(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "T", "T"])
        replays.plays["tally"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        found = bakeoffs.comparison(bakeoff_id)

        mapped, labelled = scores_of(found)["CellMapper"], scores_of(found)["Labeller"]
        assert (mapped["by"], mapped["matched"], mapped["of"], mapped["rank"]) == ("position", 2, 3, 2)
        assert mapped["score"] == pytest.approx(2 / 3) and mapped["examples"] == [
            "row 2: the label is 'B' and it gave 'T'"
        ]
        assert (labelled["matched"], labelled["of"], labelled["score"], labelled["rank"]) == (3, 3, 1.0, 1)
        assert found["ranked"] is True and found["limit"] == 1.0

    def test_the_comparison_says_which_file_the_labels_are_of_and_that_they_are_the_persons_word(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, _ = two
        path = give_right_answers(workspace, b"cell,type\nc1,T\nc2,\nc3,T\n\n")
        bakeoffs.change(bakeoff_id, labels=SAID_BY_CELL)
        replays.plays["map_cells"] = gives(["T", "T", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP})

        found = bakeoffs.comparison(bakeoff_id)

        truth = found["ground_truth"]
        assert (truth["own"], truth["column"], truth["id_column"], truth["ok"], truth["why"]) == (
            "truth.csv",
            "type",
            "cell",
            True,
            None,
        )
        assert (truth["rows"], truth["labelled"], truth["unlabelled"]) == (3, 2, 1)
        assert truth["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest() and truth["in_data"] is False
        assert "word" in found["says"] and "not checked" in found["says"] and "Agreeing" in found["says"]
        assert found["meaning"].endswith(scoring.MEANING) and found["meaning"].startswith(agreeing.MEANING)
        assert scores_of(found)["CellMapper"]["of"] == 2

    def test_a_method_that_gave_nothing_for_a_row_is_wrong_for_it_and_one_that_gave_more_is_not_helped(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID_BY_CELL)
        replays.plays["map_cells"] = gives({"c1": "T", "c2": "B", "c3": "X", "c9": "Z"})
        replays.plays["tally"] = gives({"c3": "T"})
        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        found = scores_of(bakeoffs.comparison(bakeoff_id))

        assert [(found[name][key]) for name in ("CellMapper", "Labeller") for key in ("by", "matched", "of")] == [
            "id",
            2,
            3,
            "id",
            1,
            3,
        ]
        assert (found["CellMapper"]["missing"], found["CellMapper"]["extra"]) == (0, 1)
        assert (found["Labeller"]["missing"], found["Labeller"]["extra"]) == (2, 0)
        assert (found["CellMapper"]["rank"], found["Labeller"]["rank"]) == (1, 2)
        assert found["Labeller"]["examples"][0] == "'c1': the label is 'T' and it gave nothing"

    def test_methods_that_matched_the_same_number_share_a_rank(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B", "B"])
        replays.plays["tally"] = gives(["T", "T", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        found = scores_of(bakeoffs.comparison(bakeoff_id))

        assert (found["CellMapper"]["matched"], found["Labeller"]["matched"]) == (2, 2)
        assert (found["CellMapper"]["rank"], found["Labeller"]["rank"]) == (1, 1)

    def test_numbers_are_held_to_labels_within_the_tolerance_that_is_given_for_the_comparison(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, _ = two
        give_right_answers(workspace, b"cell,value\nc1,1\nc2,2.5\nc3,3\n")
        bakeoffs.change(bakeoff_id, labels={"own": "truth.csv", "column": "value"})
        replays.plays["map_cells"] = gives([1.05, 2.5, 3])
        run(bakeoffs, bakeoff_id, {first: MAP})

        strict = scores_of(bakeoffs.comparison(bakeoff_id))["CellMapper"]
        loose = scores_of(bakeoffs.comparison(bakeoff_id, relative=0.1, absolute=0))["CellMapper"]

        assert (strict["matched"], loose["matched"]) == (2, 3)

    def test_a_method_that_could_not_be_held_to_the_labels_is_not_scored_or_ranked_and_the_others_are(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        replays.plays["tally"] = answer({"type": "list", "plain": False, "repr": "[array(['T', 'B'])]"})
        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        found = scores_of(bakeoffs.comparison(bakeoff_id))

        assert found["CellMapper"]["rank"] == 1 and found["CellMapper"]["scored"] is True
        assert found["Labeller"]["scored"] is False and found["Labeller"]["why"] == "not_kept"
        assert found["Labeller"]["rank"] is None and found["Labeller"]["score"] is None
        assert "only a look" in found["Labeller"]["reason"].lower()

    def test_a_method_that_gave_a_list_of_the_wrong_length_is_not_scored_as_though_it_got_them_wrong(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, _ = two
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B"])
        run(bakeoffs, bakeoff_id, {first: MAP})

        found = bakeoffs.comparison(bakeoff_id)

        assert scores_of(found)["CellMapper"]["why"] == "length" and found["ranked"] is False

    def test_a_method_that_failed_or_was_not_run_or_not_built_is_not_scored_and_the_one_that_ran_is_ranked_alone(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, three: tuple[str, str, str, str]
    ) -> None:
        bakeoff_id, first, second, third = three
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP, second: MAP})

        found = bakeoffs.comparison(bakeoff_id)

        ran, outside, unbuilt = found["methods"]
        assert (ran["score"]["rank"], ran["score"]["matched"], ran["score"]["of"]) == (1, 3, 3)
        for method in (outside, unbuilt):
            assert method["score"]["scored"] is False and method["score"]["why"] == "no_answer"
            assert method["score"]["rank"] is None
        assert found["ranked"] is True

    def test_a_method_that_failed_has_no_answer_to_hold_to_the_labels(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        replays.plays["tally"] = answer(
            None, ok=False, error={"type": "ValueError", "message": "no", "traceback": [], "cell": None}
        )
        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        found = scores_of(bakeoffs.comparison(bakeoff_id))

        assert (found["Labeller"]["why"], found["Labeller"]["rank"]) == ("no_answer", None)
        assert found["CellMapper"]["rank"] == 1

    def test_a_run_on_data_that_is_not_as_it_was_listed_is_not_held_to_labels_that_may_be_of_other_rows(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str], own_data: Path
    ) -> None:
        bakeoff_id, first, second = two
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        replays.plays["tally"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP})
        own_data.write_bytes(own_data.read_bytes() + b"more\n")
        run(bakeoffs, bakeoff_id, {second: TALLY})

        found = bakeoffs.comparison(bakeoff_id)

        old, new = scores_of(found)["CellMapper"], scores_of(found)["Labeller"]
        assert (old["scored"], old["why"], old["rank"]) == (False, "data_changed", None)
        assert "Run it again" in old["reason"]
        assert (new["scored"], new["rank"]) == (True, 1)

    def test_when_the_labels_cannot_be_used_now_no_method_is_scored_and_the_comparison_says_why(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        path = give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP})
        path.write_bytes(b"cell,kind\nc1,T\n")

        found = bakeoffs.comparison(bakeoff_id)

        truth = found["ground_truth"]
        assert truth["ok"] is False and truth["why"] == "invalid" and "no column called 'type'" in truth["problem"]
        assert truth["rows"] is None and truth["labelled"] is None and truth["sha256"] is None
        assert found["ranked"] is False and "cannot be used now" in found["says"] and "no column" in found["says"]
        assert "not scored or ranked" in found["says"] and found["meaning"] == agreeing.MEANING
        for method in found["methods"]:
            assert method["score"]["scored"] is False and method["score"]["why"] == "labels_unusable"
            assert method["score"]["rank"] is None and "no column called 'type'" in method["score"]["reason"]

    def test_labels_that_are_gone_from_the_data_page_are_said_to_be_gone_and_nothing_is_ranked(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, _ = two
        path = give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP})
        path.unlink()

        found = bakeoffs.comparison(bakeoff_id)

        assert found["ground_truth"]["why"] == "missing_data" and found["ranked"] is False
        assert scores_of(found)["CellMapper"]["why"] == "labels_unusable"

    def test_a_file_with_more_rows_than_can_be_held_whole_or_with_no_answer_in_it_is_not_used(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, _ = two
        path = give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP})
        path.write_bytes(b"cell,type\nc1,\nc2,\n")

        found = bakeoffs.comparison(bakeoff_id)

        assert (
            found["ground_truth"]["ok"] is False
            and "No row of the file has an answer" in found["ground_truth"]["problem"]
        )
        assert found["ranked"] is False

    def test_the_labels_are_read_again_each_time_so_a_change_to_them_is_a_change_to_the_scores_and_to_the_hash(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, _ = two
        path = give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP})
        before = bakeoffs.comparison(bakeoff_id)

        path.write_bytes(b"cell,type\nc1,T\nc2,T\nc3,T\n")
        after = bakeoffs.comparison(bakeoff_id)

        assert scores_of(before)["CellMapper"]["matched"] == 3 and scores_of(after)["CellMapper"]["matched"] == 2
        assert before["ground_truth"]["sha256"] != after["ground_truth"]["sha256"]

    def test_a_file_that_has_grown_past_what_is_read_since_it_was_said_is_not_used_whole_or_cut(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, _ = two
        path = give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP})
        head, row = b"type\n", b"a" * 99 + b"\n"
        grown = head + row * ((labelling.MAX_BYTES + 1 - len(head)) // len(row))
        path.write_bytes(grown + b"a" * (labelling.MAX_BYTES + 1 - len(grown)))

        found = bakeoffs.comparison(bakeoff_id)

        assert path.stat().st_size == labelling.MAX_BYTES + 1
        assert found["ground_truth"]["ok"] is False and f"more than {labelling.MAX_BYTES:,} bytes" in found["says"]
        assert scores_of(found)["CellMapper"]["why"] == "labels_unusable" and found["ranked"] is False

    def test_a_run_of_a_method_that_was_made_again_since_is_still_held_to_the_labels_and_says_that_it_was(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, _ = two
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP})
        path = file_of(workspace, bakeoff_id, first)
        saved = json.loads(path.read_text("utf-8"))
        saved["method"]["commit"] = "f" * 40
        path.write_text(json.dumps(saved), "utf-8")

        found = by_name(bakeoffs.comparison(bakeoff_id))["CellMapper"]

        assert found["since"] == ["method"]
        assert (found["score"]["scored"], found["score"]["matched"], found["score"]["rank"]) == (True, 3, 1)

    def test_labels_in_a_file_that_is_tab_separated_are_read_at_tabs(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, _ = two
        give_right_answers(workspace, b"cell\ttype\nc1\tT\nc2\tB\nc3\tT\n", "truth.tsv")
        bakeoffs.change(bakeoff_id, labels={"own": "truth.tsv", "column": "type"})
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP})

        assert scores_of(bakeoffs.comparison(bakeoff_id))["CellMapper"]["matched"] == 3

    def test_labels_that_are_the_data_the_methods_are_run_on_are_scored_and_the_comparison_says_so(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, _ = two
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, data="truth.csv", labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP})

        found = bakeoffs.comparison(bakeoff_id)

        assert (
            found["ground_truth"]["in_data"] is True
            and "a method is able to read the answers" in found["ground_truth"]["says"]
        )
        assert scores_of(found)["CellMapper"]["rank"] == 1

    def test_without_labels_nothing_is_scored_and_nothing_is_ranked_whatever_the_methods_gave(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        give_right_answers(workspace)
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        replays.plays["tally"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        found = bakeoffs.comparison(bakeoff_id)

        assert found["ground_truth"] is None and found["ranked"] is False and found["says"] == SAYS_WITHOUT
        assert [each["score"] for each in found["methods"]] == [None, None] and found["pairs"][0]["verdict"] == "agree"

    def test_taking_the_labels_away_takes_the_ranking_away_with_them(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, _ = two
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP})
        assert bakeoffs.comparison(bakeoff_id)["ranked"] is True

        bakeoffs.change(bakeoff_id, labels={})

        found = bakeoffs.comparison(bakeoff_id)
        assert found["ranked"] is False and found["ground_truth"] is None and found["methods"][0]["score"] is None


class TestTheTablesOfTheScores:
    def test_the_table_of_methods_has_the_score_the_rank_and_where_it_differs_for_each_method_that_was_scored(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "T", "T"])
        replays.plays["tally"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        _, content = bakeoffs.table(bakeoff_id, "methods")

        mapped, labelled = rows_of(content)
        assert (mapped["Score"], mapped["Matched"], mapped["Of labels"], mapped["Rank"]) == ("0.666667", "2", "3", "2")
        assert mapped["Held to the labels"] == "By position, in the order of the rows"
        assert mapped["Where it differs from the labels"] == "row 2: the label is 'B' and it gave 'T'"
        assert (labelled["Score"], labelled["Matched"], labelled["Rank"]) == ("1.0", "3", "1")
        assert labelled["Where it differs from the labels"] == "" and labelled["Not scored because"] == ""

    def test_how_the_answer_was_held_to_the_labels_and_every_place_it_differs_are_in_the_table(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID_BY_CELL)
        replays.plays["map_cells"] = gives({"c1": "x", "c2": "y", "c3": "z"})
        replays.plays["tally"] = gives({"c1": "T", "c2": "B", "c3": "T"})
        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        _, content = bakeoffs.table(bakeoff_id, "methods")

        wrong, right = rows_of(content)
        assert wrong["Held to the labels"] == right["Held to the labels"] == "By what each row is the answer to"
        assert (wrong["Score"], wrong["Matched"], wrong["Of labels"], wrong["Rank"]) == ("0.0", "0", "3", "2")
        assert wrong["Where it differs from the labels"] == (
            "'c1': the label is 'T' and it gave 'x'; 'c2': the label is 'B' and it gave 'y'; "
            "'c3': the label is 'T' and it gave 'z'"
        )
        assert (right["Score"], right["Rank"]) == ("1.0", "1")

    def test_a_method_that_was_not_scored_has_no_score_or_rank_and_says_why(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, three: tuple[str, str, str, str]
    ) -> None:
        bakeoff_id, first, second, third = three
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives(["T", "B"])
        run(bakeoffs, bakeoff_id, {first: MAP, second: MAP})

        _, content = bakeoffs.table(bakeoff_id, "methods")

        for row in rows_of(content):
            assert {row[each] for each in ("Score", "Matched", "Of labels", "Rank", "Held to the labels")} == {""}
        ran, outside, unbuilt = rows_of(content)
        assert "2 items" in ran["Not scored because"] and "3 rows" in ran["Not scored because"]
        assert outside["Not scored because"].startswith("It gave no answer")
        assert unbuilt["Not scored because"].startswith("It gave no answer")

    def test_a_table_of_a_bakeoff_that_was_not_given_labels_has_those_cells_empty(
        self, bakeoffs: Bakeoffs, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, *_ = two

        _, content = bakeoffs.table(bakeoff_id, "methods")

        for row in rows_of(content):
            assert {row[each] for each in table.METHOD_COLUMNS[table.METHOD_COLUMNS.index("Score") :][:7]} == {""}

    def test_a_label_or_an_answer_that_a_spreadsheet_would_read_as_a_formula_is_shown_in_quotes_inside_a_sentence(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, _ = two
        give_right_answers(workspace, b"cell,type\nc1,=1+1\nc2,B\nc3,T\n")
        bakeoffs.change(bakeoff_id, labels={"own": "truth.csv", "column": "type", "id_column": "cell"})
        replays.plays["map_cells"] = gives({"=c1": "=2+2", "c2": "B", "c3": "T"})
        run(bakeoffs, bakeoff_id, {first: MAP})

        _, content = bakeoffs.table(bakeoff_id, "methods")

        row, _ = rows_of(content)
        assert not any(cell.startswith(("=", "+", "-", "@")) for cell in row.values())
        assert row["Where it differs from the labels"].startswith("'c1': the label is '=1+1' and it gave nothing")


class TestTheAcceptance:
    def test_all_three_methods_are_in_the_table_with_why_and_only_the_one_that_ran_is_ranked_with_right_answers(
        self, bakeoffs: Bakeoffs, replays: Replays, workspace: Workspace, three: tuple[str, str, str, str]
    ) -> None:
        bakeoff_id, first, second, third = three
        replays.plays["map_cells"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP, second: MAP})

        without = bakeoffs.comparison(bakeoff_id)
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        with_labels = bakeoffs.comparison(bakeoff_id)

        for found in (without, with_labels):
            assert [(each["name"], each["state"], each["why"]) for each in found["methods"]] == [
                ("CellMapper", "ran", None),
                ("Labeller", "not_run", "outside"),
                ("GraphCells", "not_built", "no_go"),
            ]
            assert found["limit"] == 1.0 and found["spent"] == without["spent"]
        assert without["ranked"] is False and [each["score"] for each in without["methods"]] == [None] * 3
        assert with_labels["ranked"] is True
        assert [each["score"]["rank"] for each in with_labels["methods"]] == [1, None, None]
        _, content = bakeoffs.table(bakeoff_id, "methods")
        assert [row["Rank"] for row in rows_of(content)] == ["1", "", ""]


class TestScoresOverTheApi:
    def test_the_labels_the_scores_and_the_ranks_are_in_the_comparison_and_in_its_table(
        self,
        client: TestClient,
        bakeoffs: Bakeoffs,
        replays: Replays,
        workspace: Workspace,
        two: tuple[str, str, str],
    ) -> None:
        bakeoff_id, first, second = two
        give_right_answers(workspace)
        bakeoffs.change(bakeoff_id, labels=SAID)
        replays.plays["map_cells"] = gives([1.0, 2.0])
        replays.plays["tally"] = gives(["T", "B", "T"])
        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        found = client.get(f"/api/bakeoffs/{bakeoff_id}/comparison").json()
        methods = client.get(f"/api/bakeoffs/{bakeoff_id}/tables/methods")

        assert found["ranked"] is True and found["ground_truth"]["rows"] == 3
        assert [each["score"]["rank"] for each in found["methods"]] == [None, 1]
        assert found["methods"][0]["score"]["why"] == "length" and found["methods"][1]["score"]["score"] == 1.0
        assert [row["Rank"] for row in rows_of(methods.content)] == ["", "1"]


class TestTheTables:
    def test_the_table_of_methods_has_a_row_for_each_with_how_it_came_out_what_it_cost_and_whom_it_agrees_with(
        self, bakeoffs: Bakeoffs, replays: Replays, three: tuple[str, str, str, str]
    ) -> None:
        bakeoff_id, first, second, third = three
        replays.plays["map_cells"] = gives([1, 2, 3])

        run(bakeoffs, bakeoff_id, {first: MAP, second: MAP})
        name, content = bakeoffs.table(bakeoff_id, "methods")

        assert content.decode("utf-8").splitlines()[0] == ",".join(table.METHOD_COLUMNS)
        ran, outside, unbuilt = rows_of(content)
        assert name.endswith(" - methods")
        assert (ran["Method"], ran["State"], ran["Trust tier"], ran["Tool called"], ran["Seconds"]) == (
            "CellMapper",
            "Ran",
            "A",
            "map_cells",
            "0.1",
        )
        assert float(ran["Cost of reading its paper"]) == pytest.approx(unit_cost())
        assert (ran["Cost of asking a model for the call"], ran["The call was made by"]) == ("0.0", "The person")
        assert ran["What was kept of its answer"] == "All of it" and ran["Since it ran"] == ""
        assert (outside["State"], outside["Why (kind)"], outside["Trust tier"], outside["Seconds"]) == (
            "Not run",
            "outside",
            "",
            "",
        )
        assert "outside what the method card" in outside["Why"]
        assert (unbuilt["State"], unbuilt["Why (kind)"], unbuilt["Cost of asking a model for the call"]) == (
            "Not built",
            "no_go",
            "",
        )
        assert unbuilt["Why"].startswith("No-go:") and unbuilt["Cost of reading its paper"] == "0"

    def test_the_table_of_pairs_says_for_each_two_whether_they_agree_and_how_that_is_known(
        self, bakeoffs: Bakeoffs, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        replays.plays["map_cells"] = gives([1.0, 2.0, 3.0])
        replays.plays["tally"] = gives([1.0, 2.0, 4.0])
        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})

        name, content = bakeoffs.table(bakeoff_id, "pairs", relative=0.5, absolute=0)

        assert content.decode("utf-8").splitlines()[0] == ",".join(table.PAIR_COLUMNS)
        [row] = rows_of(content)
        assert name.endswith(" - pairs")
        assert (row["Method"], row["Other method"], row["Agree"]) == ("CellMapper", "Labeller", "Agree")
        assert row["How that is known"] == "They give the same answer, within the tolerance for numbers."
        assert (row["Kept of the method's answer"], row["Kept of the other's answer"]) == ("All of it", "All of it")
        assert (row["Relative tolerance"], row["Absolute tolerance"]) == ("0.5", "0")
        _, strict = bakeoffs.table(bakeoff_id, "pairs")
        [apart] = rows_of(strict)
        assert (apart["Agree"], apart["What differs"]) == ("Differ", "[2] is 3.0 against 4.0")

    def test_a_table_of_a_bakeoff_with_no_pairs_is_the_header_alone(
        self, bakeoffs: Bakeoffs, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, *_ = two

        _, content = bakeoffs.table(bakeoff_id, "pairs")

        assert content.decode("utf-8") == ",".join(table.PAIR_COLUMNS) + "\n"

    def test_a_name_that_a_spreadsheet_would_read_as_a_formula_is_written_as_text(
        self, bakeoffs: Bakeoffs, built: tuple[str, str]
    ) -> None:
        bakeoff_id, _ = built
        add(bakeoffs, bakeoff_id, OTHER_DOI, "=HYPERLINK(1)", SECOND_CODE)

        _, content = bakeoffs.table(bakeoff_id, "methods")

        built_row, formula_row = rows_of(content)
        assert (built_row["Method"], formula_row["Method"]) == ("CellMapper", "'=HYPERLINK(1)")
        assert (formula_row["State"], formula_row["Why (kind)"], formula_row["Why"]) == (
            "Not built",
            "new",
            "It has not been built.",
        )
        assert formula_row["Cost of reading its paper"] == "" and built_row["Cost of reading its paper"] != ""

    def test_a_table_that_there_is_not_is_not_found(self, bakeoffs: Bakeoffs, two: tuple[str, str, str]) -> None:
        bakeoff_id, *_ = two

        for kind in ("ranking", "", "Methods"):
            with pytest.raises(Exception) as caught:
                bakeoffs.table(bakeoff_id, kind)
            assert getattr(caught.value, "status", None) == 404


class TestOverTheApi:
    def test_the_comparison_and_its_tables_are_given_with_the_tolerance_that_is_asked_for(
        self, client: TestClient, bakeoffs: Bakeoffs, replays: Replays, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, first, second = two
        replays.plays["map_cells"] = gives([1.0, 2.0])
        replays.plays["tally"] = gives([1.0, 2.1])
        run(bakeoffs, bakeoff_id, {first: MAP, second: TALLY})
        url = f"/api/bakeoffs/{bakeoff_id}"

        strict = client.get(f"{url}/comparison")
        loose = client.get(f"{url}/comparison", params={"relative": 0.1, "absolute": 0})
        pairs = client.get(f"{url}/tables/pairs", params={"relative": 0.1, "absolute": 0})
        methods = client.get(f"{url}/tables/methods")

        assert strict.status_code == 200 and strict.json()["pairs"][0]["verdict"] == "differ"
        assert loose.json()["pairs"][0]["verdict"] == "agree"
        assert loose.json()["tolerance"] == {"relative": 0.1, "absolute": 0}
        assert strict.json()["ranked"] is False and strict.json()["ground_truth"] is None
        assert pairs.status_code == 200 and pairs.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in pairs.headers["content-disposition"] and ".csv" in pairs.headers["content-disposition"]
        assert rows_of(pairs.content)[0]["Agree"] == "Agree"
        assert [row["Method"] for row in rows_of(methods.content)] == ["CellMapper", "Labeller"]

    def test_what_is_asked_wrongly_is_refused_and_what_is_not_there_is_not_found(
        self, client: TestClient, workspace: Workspace, two: tuple[str, str, str]
    ) -> None:
        bakeoff_id, *_ = two
        url = f"/api/bakeoffs/{bakeoff_id}"

        assert client.get(f"{url}/comparison", params={"relative": 1}).status_code == 422
        assert client.get(f"{url}/tables/pairs", params={"absolute": -1}).status_code == 422
        assert client.get(f"{url}/comparison", params={"relative": "much"}).status_code == 422
        assert client.get(f"{url}/tables/ranking").status_code == 404
        assert client.get("/api/bakeoffs/nope/comparison").status_code == 404
        assert client.get("/api/bakeoffs/nope/tables/methods").status_code == 404
        app = create_app(workspace.root, token=TOKEN, check_keys=False, max_upload_bytes=100_000)
        with TestClient(app, base_url="http://127.0.0.1") as anyone:
            assert anyone.get(f"{url}/comparison").status_code == 401
            assert anyone.get(f"{url}/tables/methods").status_code == 401
