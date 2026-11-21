"""Tests of where a bake-off says its right answers are: that the person says it, that only the names of a file and its
columns are kept and the file stays where the Data page has it, that what is said is held to the file as it is, that
the file is read from where it is each time and so a page says when it has changed, and that what an earlier version
kept is read as having none. Nothing is scored here: this is only where the answers are."""

import io
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_server_bakeoffs import (
    CSV,
    DOI,
    TASK,
    agents,
    bakeoffs,
    client,
    jobs,
    made,
    model_client,
    person_candidate,
    record_of,
    rewrite,
    services,
    why,
    workspace,
)

from virtual_lab.paperagents import labelling
from virtual_lab.server import paperagent_bakeoff as kept
from virtual_lab.server.bakeoffs import Bakeoffs
from virtual_lab.server.own import Own
from virtual_lab.server.workspace import Workspace

__all__ = ["agents", "bakeoffs", "client", "jobs", "model_client", "services", "workspace"]

TRUTH = b"cell,type,note\nc1,T,x\nc2,B,y\n"
SAID = {"own": "truth.csv", "column": "type", "id_column": "cell"}
UPLOAD_LIMIT = 20 << 20


def give(workspace: Workspace, name: str = "truth.csv", content: bytes = TRUTH) -> None:
    Own(workspace, UPLOAD_LIMIT).add_upload(name, io.BytesIO(content), "Right answers of the cells")


@pytest.fixture
def truth(workspace: Workspace) -> Workspace:
    give(workspace)

    return workspace


def labels_of(workspace: Workspace, bakeoff_id: str) -> Any:
    return record_of(workspace, bakeoff_id)["labels"]


class TestSaying:
    def test_where_the_right_answers_are_is_kept_by_the_names_of_a_file_and_its_columns_and_nothing_more(
        self, bakeoffs: Bakeoffs, truth: Workspace
    ) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, None, SAID)

        assert labels_of(truth, bakeoff_id) == SAID
        assert sorted(path.name for path in (truth.bakeoffs_dir / bakeoff_id).iterdir()) == [kept.RECORD_FILE]
        shown = bakeoffs.view(bakeoff_id)["labels"]
        assert (shown["own"], shown["column"], shown["id_column"]) == ("truth.csv", "type", "cell")
        assert (shown["ok"], shown["why"], shown["problem"], shown["bytes"]) == (True, None, None, len(TRUTH))

    def test_the_column_that_says_what_each_is_the_answer_to_may_be_left_out(
        self, bakeoffs: Bakeoffs, truth: Workspace
    ) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, None, {"own": "truth.csv", "column": "type"})

        assert labels_of(truth, bakeoff_id) == {"own": "truth.csv", "column": "type", "id_column": None}
        assert bakeoffs.view(bakeoff_id)["labels"]["ok"] is True

    def test_names_of_columns_are_kept_without_the_space_round_them_and_blank_is_not_said(
        self, bakeoffs: Bakeoffs, truth: Workspace
    ) -> None:
        said = {"own": "truth.csv", "column": "  type ", "id_column": "   "}

        assert labels_of(truth, bakeoffs.create(None, TASK, None, 1.0, None, said)) == {
            "own": "truth.csv",
            "column": "type",
            "id_column": None,
        }

    def test_a_bake_off_that_is_not_told_where_they_are_has_none_and_a_view_says_so(
        self, bakeoffs: Bakeoffs, workspace: Workspace
    ) -> None:
        bakeoff_id = made(bakeoffs)

        assert labels_of(workspace, bakeoff_id) is None
        assert bakeoffs.view(bakeoff_id)["labels"] is None

    @pytest.mark.parametrize("nothing", [{}, {"own": ""}, {"own": " ", "column": "\n", "id_column": None}])
    def test_saying_none_of_it_says_that_there_are_none(
        self, bakeoffs: Bakeoffs, truth: Workspace, nothing: dict[str, Any]
    ) -> None:
        assert labels_of(truth, bakeoffs.create(None, TASK, None, 1.0, None, nothing)) is None

    def test_they_may_be_said_before_the_data_is_and_the_data_is_not_changed_by_it(
        self, bakeoffs: Bakeoffs, truth: Workspace
    ) -> None:
        give(truth, "counts.csv", CSV)
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, None, SAID)

        bakeoffs.change(bakeoff_id, data="counts.csv")

        assert record_of(truth, bakeoff_id)["data"] == {"own": "counts.csv"}
        assert labels_of(truth, bakeoff_id) == SAID


class TestChanging:
    def test_they_are_said_again_and_what_else_is_left_as_it_was(self, bakeoffs: Bakeoffs, truth: Workspace) -> None:
        bakeoff_id = bakeoffs.create("Cells", TASK, None, 2.0, {"species": "mouse"}, SAID)
        before = record_of(truth, bakeoff_id)

        bakeoffs.change(bakeoff_id, labels={"own": "truth.csv", "column": "note"})

        assert labels_of(truth, bakeoff_id) == {"own": "truth.csv", "column": "note", "id_column": None}
        assert {**record_of(truth, bakeoff_id), "labels": SAID} == before

    def test_changing_something_else_leaves_them_as_they_were(self, bakeoffs: Bakeoffs, truth: Workspace) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, None, SAID)

        bakeoffs.change(bakeoff_id, title="Other", limit=3.0, described={"species": "mouse"})

        assert labels_of(truth, bakeoff_id) == SAID

    def test_saying_none_of_it_takes_them_away(self, bakeoffs: Bakeoffs, truth: Workspace) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, None, SAID)

        bakeoffs.change(bakeoff_id, labels={})

        assert labels_of(truth, bakeoff_id) is None
        assert bakeoffs.view(bakeoff_id)["labels"] is None

    def test_they_are_something_to_change_on_their_own(self, bakeoffs: Bakeoffs, truth: Workspace) -> None:
        bakeoff_id = made(bakeoffs)

        bakeoffs.change(bakeoff_id, labels=SAID)

        assert labels_of(truth, bakeoff_id) == SAID
        assert why(bakeoffs.change, bakeoff_id) == (422, "invalid")

    def test_what_is_refused_leaves_the_bake_off_as_it_was(self, bakeoffs: Bakeoffs, truth: Workspace) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, None, SAID)
        before = record_of(truth, bakeoff_id)

        assert why(bakeoffs.change, bakeoff_id, labels={"own": "truth.csv", "column": "nothing"}) == (422, "invalid")
        assert why(bakeoffs.change, bakeoff_id, title="Fine", labels={"own": "nope.csv", "column": "a"}) == (
            422,
            "unknown_data",
        )

        assert record_of(truth, bakeoff_id) == before


class TestRefusing:
    @pytest.mark.parametrize(
        "said",
        [
            "truth.csv",
            ["truth.csv", "type"],
            3,
            {"own": "truth.csv"},
            {"column": "type"},
            {"id_column": "cell"},
            {"own": "truth.csv", "id_column": "cell"},
            {"own": "truth.csv", "column": "type", "extra": 1},
            {"own": ["truth.csv"], "column": "type"},
            {"own": "truth.csv", "column": 5},
            {"own": "truth.csv", "column": "type", "id_column": ["cell"]},
            {"own": "truth.csv", "column": "ty\x00pe"},
            {"own": "truth.csv", "column": "type", "id_column": "ce\nll"},
            {"own": "truth.csv", "column": "x" * (labelling.MAX_COLUMN_CHARS + 1)},
            {"own": "truth\x00.csv", "column": "type"},
        ],
    )
    def test_what_is_not_a_file_and_a_column_of_it_is_refused(
        self, bakeoffs: Bakeoffs, truth: Workspace, said: Any
    ) -> None:
        assert why(bakeoffs.create, None, TASK, None, 1.0, None, said) == (422, "invalid")
        assert bakeoffs.kept() == []

    def test_a_file_that_is_not_on_the_data_page_is_refused(self, bakeoffs: Bakeoffs, truth: Workspace) -> None:
        assert why(bakeoffs.create, None, TASK, None, 1.0, None, {"own": "other.csv", "column": "type"}) == (
            422,
            "unknown_data",
        )

    def test_a_file_that_the_data_page_has_but_is_not_there_is_refused(
        self, bakeoffs: Bakeoffs, truth: Workspace
    ) -> None:
        (truth.own_data_dir / "truth.csv").unlink()

        assert why(bakeoffs.create, None, TASK, None, 1.0, None, SAID) == (422, "missing_data")

    def test_a_folder_is_refused_since_the_answers_are_in_one_file(
        self, bakeoffs: Bakeoffs, truth: Workspace, tmp_path: Path
    ) -> None:
        (tmp_path / "answers").mkdir()
        Own(truth, UPLOAD_LIMIT).add_path(str(tmp_path / "answers"), "A folder of answers")

        assert why(bakeoffs.create, None, TASK, None, 1.0, None, {"own": "answers", "column": "type"}) == (
            422,
            "invalid",
        )

    @pytest.mark.parametrize("name", ["truth.txt", "truth.xlsx", "truth", "truth.csv.gz"])
    def test_a_file_of_a_kind_that_is_not_read_is_refused(
        self, bakeoffs: Bakeoffs, workspace: Workspace, name: str
    ) -> None:
        give(workspace, name)

        assert why(bakeoffs.create, None, TASK, None, 1.0, None, {"own": name, "column": "type"}) == (422, "invalid")

    def test_a_file_that_is_too_big_is_refused(self, bakeoffs: Bakeoffs, workspace: Workspace) -> None:
        give(workspace, "big.csv", b"cell,type\n" + b"x" * labelling.MAX_BYTES)

        assert why(bakeoffs.create, None, TASK, None, 1.0, None, {"own": "big.csv", "column": "type"}) == (
            422,
            "invalid",
        )

    def test_a_column_that_is_not_in_the_file_is_refused_with_the_ones_that_are(
        self, bakeoffs: Bakeoffs, truth: Workspace
    ) -> None:
        for said in (
            {"own": "truth.csv", "column": "label"},
            {"own": "truth.csv", "column": "type", "id_column": "id"},
        ):
            error = pytest.raises(Exception, bakeoffs.create, None, TASK, None, 1.0, None, said).value
            assert getattr(error, "code", None) == "invalid"
            assert "'cell', 'type', 'note'" in str(error)

    def test_the_same_column_for_both_is_refused(self, bakeoffs: Bakeoffs, truth: Workspace) -> None:
        assert why(
            bakeoffs.create, None, TASK, None, 1.0, None, {"own": "truth.csv", "column": "type", "id_column": "type"}
        ) == (422, "invalid")

    def test_a_name_that_two_columns_have_is_refused(self, bakeoffs: Bakeoffs, workspace: Workspace) -> None:
        give(workspace, "twice.csv", b"a,a,b\n1,2,3\n")

        assert why(bakeoffs.create, None, TASK, None, 1.0, None, {"own": "twice.csv", "column": "a"}) == (
            422,
            "invalid",
        )
        assert bakeoffs.view(bakeoffs.create(None, TASK, None, 1.0, None, {"own": "twice.csv", "column": "b"}))[
            "labels"
        ]["ok"]


class TestReadWhereItIs:
    def test_the_file_is_looked_at_each_time_and_a_page_is_told_when_it_is_not_as_it_was_said(
        self, bakeoffs: Bakeoffs, truth: Workspace
    ) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, None, SAID)
        path = truth.own_data_dir / "truth.csv"

        path.write_bytes(b"cell,kind\nc1,T\n")
        changed = bakeoffs.view(bakeoff_id)["labels"]
        assert (changed["ok"], changed["why"]) == (False, "invalid")
        assert "There is no column called 'type'" in changed["problem"] and changed["bytes"] == path.stat().st_size

        path.unlink()
        gone = bakeoffs.view(bakeoff_id)["labels"]
        assert (gone["ok"], gone["why"], gone["bytes"]) == (False, "missing_data", None)

        path.write_bytes(TRUTH)
        assert bakeoffs.view(bakeoff_id)["labels"]["ok"] is True
        assert labels_of(truth, bakeoff_id) == SAID

    def test_a_file_that_is_taken_off_the_data_page_is_said_to_be_gone_and_the_names_stay(
        self, bakeoffs: Bakeoffs, truth: Workspace
    ) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, None, SAID)

        truth.update_own(lambda kept_own: kept_own["data"].pop("truth.csv"))

        shown = bakeoffs.view(bakeoff_id)["labels"]
        assert (shown["ok"], shown["why"], shown["bytes"]) == (False, "unknown_data", None)
        assert labels_of(truth, bakeoff_id) == SAID

    def test_a_file_that_is_a_pipe_now_is_said_to_be_gone_and_is_not_waited_for(
        self, bakeoffs: Bakeoffs, truth: Workspace
    ) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, None, SAID)
        path = truth.own_data_dir / "truth.csv"
        path.unlink()
        os.mkfifo(path)

        shown = bakeoffs.view(bakeoff_id)["labels"]

        assert (shown["ok"], shown["why"]) == (False, "missing_data")
        assert why(bakeoffs.create, None, TASK, None, 1.0, None, SAID) == (422, "missing_data")

    def test_a_file_that_is_a_folder_now_is_said_to_be_that(self, bakeoffs: Bakeoffs, truth: Workspace) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, None, SAID)
        path = truth.own_data_dir / "truth.csv"
        path.unlink()
        path.mkdir()

        shown = bakeoffs.view(bakeoff_id)["labels"]

        assert (shown["ok"], shown["why"]) == (False, "invalid")
        assert "is a folder" in shown["problem"]

    def test_it_is_not_given_to_a_method_unless_it_is_the_data_and_the_page_says_when_it_is(
        self, bakeoffs: Bakeoffs, truth: Workspace
    ) -> None:
        give(truth, "counts.csv", CSV)
        apart = bakeoffs.create(None, TASK, "counts.csv", 1.0, None, SAID)
        same = bakeoffs.create(None, TASK, "truth.csv", 1.0, None, SAID)

        assert bakeoffs.view(apart)["labels"]["in_data"] is False
        assert "a method is able to read" not in bakeoffs.view(apart)["labels"]["says"]
        shown = bakeoffs.view(same)["labels"]
        assert shown["in_data"] is True and "a method is able to read the answers" in shown["says"]
        assert "the person's word" in shown["says"] and "nothing here checks them" in shown["says"]

    def test_a_file_taken_off_the_data_page_while_the_data_is_there_is_shown_and_is_not_in_the_data(
        self, bakeoffs: Bakeoffs, truth: Workspace
    ) -> None:
        give(truth, "counts.csv", CSV)
        bakeoff_id = bakeoffs.create(None, TASK, "counts.csv", 1.0, None, SAID)

        truth.update_own(lambda kept_own: kept_own["data"].pop("truth.csv"))

        shown = bakeoffs.view(bakeoff_id)["labels"]
        assert (shown["ok"], shown["why"], shown["in_data"]) == (False, "unknown_data", False)

    def test_a_link_to_a_file_in_the_data_is_in_the_data_too(
        self, bakeoffs: Bakeoffs, workspace: Workspace, tmp_path: Path
    ) -> None:
        (tmp_path / "study").mkdir()
        (tmp_path / "study" / "truth.csv").write_bytes(TRUTH)
        (tmp_path / "link.csv").symlink_to(tmp_path / "study" / "truth.csv")
        Own(workspace, UPLOAD_LIMIT).add_path(str(tmp_path / "study"), "A study")
        Own(workspace, UPLOAD_LIMIT).add_path(str(tmp_path / "link.csv"), "A link to its answers")

        bakeoff_id = bakeoffs.create(None, TASK, "study", 1.0, None, {"own": "link.csv", "column": "type"})

        assert bakeoffs.view(bakeoff_id)["labels"]["in_data"] is True

    def test_a_folder_that_has_the_file_in_it_is_the_data_as_much_as_the_file_is(
        self, bakeoffs: Bakeoffs, workspace: Workspace, tmp_path: Path
    ) -> None:
        (tmp_path / "study").mkdir()
        (tmp_path / "study" / "truth.csv").write_bytes(TRUTH)
        (tmp_path / "elsewhere").mkdir()
        (tmp_path / "elsewhere" / "other.csv").write_bytes(TRUTH)
        for path in ("study", "study/truth.csv", "elsewhere"):
            Own(workspace, UPLOAD_LIMIT).add_path(str(tmp_path / path), "Something of the person's")
        said = {"own": "truth.csv", "column": "type"}

        inside = bakeoffs.view(bakeoffs.create(None, TASK, "study", 1.0, None, said))["labels"]
        outside = bakeoffs.view(bakeoffs.create(None, TASK, "elsewhere", 1.0, None, said))["labels"]
        no_data = bakeoffs.view(bakeoffs.create(None, TASK, None, 1.0, None, said))["labels"]

        assert (inside["ok"], inside["in_data"]) == (True, True)
        assert "or is in it" in inside["says"]
        assert (outside["in_data"], no_data["in_data"]) == (False, False)
        assert "a method is able to read" not in outside["says"] + no_data["says"]


class TestWhatIsKept:
    def test_a_bake_off_kept_before_the_answers_could_be_said_is_read_as_one_with_none(
        self, bakeoffs: Bakeoffs, truth: Workspace
    ) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, {"species": "mouse"}, SAID)

        def earlier(record: dict[str, Any]) -> None:
            record["schema"] = 3
            del record["labels"]
            record["candidates"].append(
                {**person_candidate(DOI), "went_on": {"key": "a" * 64, "at": "2024-01-01T00:00:00Z"}}
            )

        rewrite(truth, bakeoff_id, earlier)

        [(_, loaded)] = bakeoffs.kept()
        assert (loaded["schema"], loaded["labels"]) == (kept.SCHEMA, None)
        assert loaded["described"]["species"] == "mouse"
        assert [each["went_on"] for each in loaded["candidates"]] == [{"key": "a" * 64, "at": "2024-01-01T00:00:00Z"}]
        bakeoffs.change(bakeoff_id, labels=SAID)
        assert (record_of(truth, bakeoff_id)["schema"], labels_of(truth, bakeoff_id)) == (kept.SCHEMA, SAID)

    @pytest.mark.parametrize("earlier", [1, 2])
    def test_so_is_one_of_the_first_two_kinds_which_had_no_saying_what_the_data_is_either(
        self, bakeoffs: Bakeoffs, truth: Workspace, earlier: int
    ) -> None:
        bakeoff_id = made(bakeoffs)

        def go_back(record: dict[str, Any]) -> None:
            record["schema"] = earlier
            del record["labels"], record["described"]

        rewrite(truth, bakeoff_id, go_back)

        [(_, loaded)] = bakeoffs.kept()
        assert (loaded["schema"], loaded["labels"], loaded["described"]) == (kept.SCHEMA, None, None)

    @pytest.mark.parametrize(
        "damage",
        [
            lambda record: record.update(labels={}),
            lambda record: record.update(labels="truth.csv"),
            lambda record: record.update(labels=[SAID]),
            lambda record: record["labels"].update(own=""),
            lambda record: record["labels"].update(own="truth\x00.csv"),
            lambda record: record["labels"].update(own=None),
            lambda record: record["labels"].update(column=""),
            lambda record: record["labels"].update(column=" type"),
            lambda record: record["labels"].update(column="type "),
            lambda record: record["labels"].update(column="ty\npe"),
            lambda record: record["labels"].update(column="x" * (labelling.MAX_COLUMN_CHARS + 1)),
            lambda record: record["labels"].update(column=3),
            lambda record: record["labels"].update(id_column=""),
            lambda record: record["labels"].update(id_column=" cell"),
            lambda record: record["labels"].update(id_column="ce\x00ll"),
            lambda record: record["labels"].update(id_column="type"),
            lambda record: record["labels"].update(id_column=4),
            lambda record: record["labels"].pop("id_column"),
            lambda record: record.pop("labels"),
        ],
        ids=range(19),
    )
    def test_a_file_that_says_it_in_a_shape_that_is_not_kept_is_not_used(
        self, bakeoffs: Bakeoffs, truth: Workspace, damage: Any
    ) -> None:
        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, None, SAID)
        assert len(bakeoffs.kept()) == 1

        rewrite(truth, bakeoff_id, damage)

        assert bakeoffs.kept() == []

    def test_a_column_of_the_longest_name_is_kept(self, bakeoffs: Bakeoffs, workspace: Workspace) -> None:
        name = "x" * labelling.MAX_COLUMN_CHARS
        give(workspace, "long.csv", f"{name},b\n1,2\n".encode())

        bakeoff_id = bakeoffs.create(None, TASK, None, 1.0, None, {"own": "long.csv", "column": name})

        assert len(bakeoffs.kept()) == 1
        assert labels_of(workspace, bakeoff_id)["column"] == name


class TestRoutes:
    def test_they_are_said_when_a_bake_off_is_made_and_again_and_taken_away_through_the_api(
        self, client: TestClient, truth: Workspace
    ) -> None:
        made_one = client.post("/api/bakeoffs", json={"task": TASK, "limit": 1.0, "labels": SAID})
        assert made_one.status_code == 201
        bakeoff_id = made_one.json()["id"]
        assert made_one.json()["labels"]["ok"] is True and labels_of(truth, bakeoff_id) == SAID

        again = client.patch(f"/api/bakeoffs/{bakeoff_id}", json={"labels": {"own": "truth.csv", "column": "note"}})
        assert again.status_code == 200 and again.json()["labels"]["column"] == "note"
        assert again.json()["labels"]["id_column"] is None
        assert client.get(f"/api/bakeoffs/{bakeoff_id}").json()["labels"]["column"] == "note"

        away = client.patch(f"/api/bakeoffs/{bakeoff_id}", json={"labels": {}})
        assert away.status_code == 200 and away.json()["labels"] is None
        assert client.patch(f"/api/bakeoffs/{bakeoff_id}", json={}).status_code == 422

    def test_what_is_wrong_with_them_is_a_refusal_that_says_what(self, client: TestClient, truth: Workspace) -> None:
        for said, code in (
            ({"own": "truth.csv"}, "invalid"),
            ({"own": "truth.csv", "column": "nope"}, "invalid"),
            ({"own": "nothing.csv", "column": "type"}, "unknown_data"),
            ({"own": "truth.csv", "column": "type", "other": 1}, None),
            ({"own": 4, "column": "type"}, None),
        ):
            response = client.post("/api/bakeoffs", json={"task": TASK, "limit": 1.0, "labels": said})

            assert response.status_code == 422
            if code is not None:
                assert response.json()["error"]["code"] == code
        assert client.get("/api/bakeoffs").json()["bakeoffs"] == []
