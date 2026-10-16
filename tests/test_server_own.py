"""Tests of the data and software the researcher gives the lab, and of what a conversation is given of them."""

import asyncio
import io
import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MODEL, FakeClient
from fastapi.testclient import TestClient
from test_server_app import call_app

from virtual_lab import session as session_module
from virtual_lab.server import own as own_module
from virtual_lab.server import workspace as workspace_module
from virtual_lab.server.app import create_app
from virtual_lab.server.config import ChatConfig, resolve_config
from virtual_lab.server.conversations import Conversations
from virtual_lab.server.errors import ApiError
from virtual_lab.server.own import (
    MAX_DESCRIPTION_CHARS,
    PREVIEW_ENTRIES,
    PREVIEW_LINE_CHARS,
    PREVIEW_LINES,
    Own,
    check_name,
    check_own_names,
    given,
)
from virtual_lab.server.workspace import (
    OWN_DATA_DIR_NAME,
    OWN_FILE_NAME,
    Settings,
    Workspace,
    is_file_name,
    is_full_path,
)

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}

CSV = b"gene,score\nTP53,0.91\nBRCA1,0.20\n"
LIMIT = 1024


@pytest.fixture(autouse=True)
def model_client(fake_client: FakeClient) -> FakeClient:
    return fake_client


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    store = Workspace(tmp_path / "workspace")
    store.save_settings(Settings(model=TEST_MODEL, max_cost=None))

    return store


@pytest.fixture
def own(workspace: Workspace) -> Own:
    return Own(workspace, LIMIT)


@pytest.fixture
def client(workspace: Workspace) -> Iterator[TestClient]:
    app = create_app(workspace.root, token=TOKEN, check_keys=False, max_upload_bytes=LIMIT)
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


@pytest.fixture
def conversations(workspace: Workspace) -> Iterator[Conversations]:
    kept = Conversations(workspace, check_keys=False)
    yield kept
    kept.close()


def upload(own: Own, name: str = "counts.csv", content: bytes = CSV, description: str = "Read counts") -> None:
    own.add_upload(name, io.BytesIO(content), description)


def data(own: Own) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in own.describe()["data"]}


def refused(call: Any, *args: Any) -> ApiError:
    with pytest.raises(ApiError) as caught:
        call(*args)

    return caught.value


def made(tmp_path: Path, name: str = "table.tsv", content: bytes = b"a\tb\n1\t2\n") -> Path:
    path = tmp_path / "elsewhere" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    return path


def fail(message: str) -> Any:
    raise AssertionError(message)


def parts(workspace: Workspace) -> list[str]:
    """What is left in the folder of uploads that is not an upload: what is written on the way."""
    directory = workspace.own_data_dir
    return sorted(path.name for path in directory.iterdir() if path.name.startswith(".")) if directory.is_dir() else []


class TestWhatIsKept:
    def test_nothing_is_given_until_something_is(self, workspace: Workspace, own: Own) -> None:
        assert workspace.load_own() == {"data": {}, "software": {}}
        assert own.describe() == {"data": [], "software": [], "max_upload_bytes": LIMIT}

    @pytest.mark.parametrize("content", ["", "not json", "[]", '"text"', '{"data": [], "software": 3}'])
    def test_a_file_that_is_not_what_it_should_be_gives_nothing(self, workspace: Workspace, content: str) -> None:
        workspace.own_path.write_text(content)

        assert workspace.load_own() == {"data": {}, "software": {}}

    def test_what_a_file_edited_by_hand_has_wrong_is_left_out_and_the_rest_is_kept(self, workspace: Workspace) -> None:
        workspace.own_path.write_text(
            json.dumps(
                {
                    "data": {
                        "good.csv": {"description": "Fine"},
                        "linked.csv": {"description": "Elsewhere", "path": "/somewhere/linked.csv"},
                        "empty.csv": {"description": "  "},
                        "none.csv": {},
                        "number.csv": {"description": 3},
                        "path.csv": {"description": "Odd", "path": 3},
                        "entry.csv": "Fine",
                        "": {"description": "No name"},
                    },
                    "software": {"samtools": "Reads", "blank": " ", "number": 3, "": "No name"},
                }
            )
        )

        kept = workspace.load_own()

        assert kept == {
            "data": {
                "good.csv": {"description": "Fine"},
                "linked.csv": {"description": "Elsewhere", "path": "/somewhere/linked.csv"},
            },
            "software": {"samtools": "Reads"},
        }

    def test_data_not_named_as_a_file_or_not_at_a_full_path_is_left_out_as_it_could_be_a_place_elsewhere(
        self, workspace: Workspace
    ) -> None:
        odd = ["../victim.txt", "/etc/victim.txt", "a/b.csv", "a/", "..", ".", "a\x00b", "a\nb.csv"]
        workspace.own_path.write_text(
            json.dumps(
                {
                    "data": {
                        **{name: {"description": "Odd"} for name in odd},
                        "relative.csv": {"description": "Odd", "path": "somewhere/relative.csv"},
                        "home.csv": {"description": "Odd", "path": "~/home.csv"},
                        "nul.csv": {"description": "Odd", "path": "/somewhere/a\x00b.csv"},
                        "fine.csv": {"description": "Fine", "path": "/somewhere/fine.csv"},
                        "plain.csv": {"description": "Fine"},
                    }
                }
            )
        )

        assert list(workspace.load_own()["data"]) == ["fine.csv", "plain.csv"]

    def test_a_change_is_written_and_a_change_that_fails_writes_nothing(self, workspace: Workspace) -> None:
        workspace.update_own(lambda kept: kept["software"].update(samtools="Reads"))

        def fail(kept: dict[str, dict[str, Any]]) -> None:
            kept["software"]["bwa"] = "Aligns"
            raise RuntimeError("no")

        with pytest.raises(RuntimeError):
            workspace.update_own(fail)

        assert workspace.load_own()["software"] == {"samtools": "Reads"}
        assert json.loads(workspace.own_path.read_text())["software"] == {"samtools": "Reads"}

    def test_changes_made_at_the_same_time_are_not_lost(self, workspace: Workspace) -> None:
        names = [f"tool{number}" for number in range(40)]
        threads = [
            threading.Thread(
                target=workspace.update_own, args=(lambda kept, name=name: kept["software"].update({name: "x"}),)
            )
            for name in names
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(workspace.load_own()["software"]) == sorted(names)

    def test_it_is_kept_in_the_workspace_beside_the_rest(self, workspace: Workspace) -> None:
        assert workspace.own_path == workspace.root / OWN_FILE_NAME
        assert workspace.own_data_dir == workspace.root / OWN_DATA_DIR_NAME


class TestUploading:
    def test_a_file_is_kept_in_the_workspace_and_described(self, workspace: Workspace, own: Own) -> None:
        upload(own, description="  Read counts \n of the screen ")

        item = data(own)["counts.csv"]
        assert (workspace.own_data_dir / "counts.csv").read_bytes() == CSV
        assert item == {
            "name": "counts.csv",
            "description": "Read counts of the screen",
            "source": "uploaded",
            "path": None,
            "kind": "file",
            "bytes": len(CSV),
            "modified": pytest.approx((workspace.own_data_dir / "counts.csv").stat().st_mtime),
        }
        assert parts(workspace) == []

    @pytest.mark.parametrize(
        ("sent", "kept"),
        [
            ("C:\\Users\\me\\Desktop\\counts.csv", "counts.csv"),
            ("some/folder/counts.csv", "counts.csv"),
            (".hidden.csv", "hidden.csv"),
            ("two words.csv", "two words.csv"),
        ],
    )
    def test_a_file_is_named_as_a_browser_names_it_but_for_the_path(
        self, workspace: Workspace, own: Own, sent: str, kept: str
    ) -> None:
        upload(own, sent)

        assert list(data(own)) == [kept]
        assert (workspace.own_data_dir / kept).is_file()

    def test_a_name_that_is_taken_is_not_given_to_another_and_the_first_is_left_as_it_was(
        self, workspace: Workspace, own: Own
    ) -> None:
        upload(own, content=CSV, description="First")

        error = refused(upload, own, "counts.csv", b"other", "Second")

        assert (error.status, error.code) == (409, "name_taken")
        assert "counts.csv" in error.message
        assert (workspace.own_data_dir / "counts.csv").read_bytes() == CSV
        assert data(own)["counts.csv"]["description"] == "First"
        assert parts(workspace) == []

    def test_a_name_taken_while_the_file_arrives_is_refused_when_it_has_and_leaves_the_one_that_got_there(
        self, workspace: Workspace, own: Own
    ) -> None:
        class Slow(io.BytesIO):
            first = True

            def read(self, size: int | None = -1) -> bytes:
                if self.first:
                    self.first = False
                    upload(own, content=b"quicker", description="Quicker")

                return super().read(size)

        error = refused(own.add_upload, "counts.csv", Slow(CSV), "Slower")

        assert (error.status, error.code) == (409, "name_taken")
        assert (workspace.own_data_dir / "counts.csv").read_bytes() == b"quicker"
        assert data(own)["counts.csv"]["description"] == "Quicker"
        assert parts(workspace) == []

    def test_a_file_larger_than_may_be_uploaded_is_refused_and_nothing_of_it_is_kept(
        self, workspace: Workspace, own: Own
    ) -> None:
        error = refused(upload, own, "big.bin", b"x" * (LIMIT + 1))

        assert (error.status, error.code) == (413, "too_large")
        assert "Point to it" in error.message
        assert data(own) == {}
        assert not (workspace.own_data_dir / "big.bin").exists()
        assert parts(workspace) == []

    def test_a_name_is_made_into_the_name_of_a_file_as_a_browser_may_send_it(self, own: Own) -> None:
        upload(own, "C:\\sheets\\a\x07b.csv")
        upload(own, "../up/one.csv")
        upload(own, "..")

        assert sorted(data(own)) == ["ab.csv", "one.csv", "upload"]

    def test_a_file_as_large_as_may_be_uploaded_is_kept(self, own: Own) -> None:
        upload(own, "edge.bin", b"x" * LIMIT)

        assert data(own)["edge.bin"]["bytes"] == LIMIT

    def test_a_file_whose_record_cannot_be_written_is_not_left_behind_and_a_name_that_was_taken_is_not_touched(
        self, workspace: Workspace, own: Own, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upload(own, "kept.csv", b"first")

        def full(path: Path, data: bytes) -> None:
            raise OSError("no space left on device")

        monkeypatch.setattr(workspace_module, "write_atomically", full)
        with pytest.raises(OSError, match="no space"):
            upload(own, "new.csv")
        assert refused(upload, own, "kept.csv", b"second").code == "name_taken"
        monkeypatch.undo()

        assert sorted(data(own)) == ["kept.csv"]
        assert sorted(path.name for path in workspace.own_data_dir.iterdir()) == ["kept.csv"]
        assert (workspace.own_data_dir / "kept.csv").read_bytes() == b"first"

    def test_a_file_that_stops_arriving_leaves_nothing_behind(self, workspace: Workspace, own: Own) -> None:
        class Broken(io.BytesIO):
            def read(self, size: int | None = -1) -> bytes:
                if self.tell():
                    raise ConnectionResetError("gone")

                return super().read(4)

        with pytest.raises(ConnectionResetError):
            own.add_upload("counts.csv", Broken(CSV), "Counts")

        assert data(own) == {}
        assert not (workspace.own_data_dir / "counts.csv").exists()
        assert parts(workspace) == []

    @pytest.mark.parametrize("description", ["", "   \n ", None, 3])
    def test_what_a_file_is_has_to_be_said(self, workspace: Workspace, own: Own, description: Any) -> None:
        error = refused(own.add_upload, "counts.csv", io.BytesIO(CSV), description)

        assert (error.status, error.code) == (422, "invalid")
        assert "Say what" in error.message
        assert data(own) == {}
        assert not workspace.own_data_dir.exists()

    def test_what_a_file_is_can_be_so_long_and_no_longer(self, own: Own) -> None:
        upload(own, "long.csv", description="x" * MAX_DESCRIPTION_CHARS)

        error = refused(upload, own, "longer.csv", CSV, "x" * (MAX_DESCRIPTION_CHARS + 1))

        assert (error.status, error.code) == (422, "invalid")
        assert list(data(own)) == ["long.csv"]

    @pytest.mark.parametrize("name", ["a,b.csv", 'say "so".csv'])
    def test_a_name_docker_cannot_mount_is_refused_before_the_file_is_read(self, own: Own, name: str) -> None:
        class Unread(io.BytesIO):
            def read(self, size: int | None = -1) -> bytes:
                raise AssertionError("it should not have been read")

        error = refused(own.add_upload, name, Unread(CSV), "Counts")

        assert (error.status, error.code) == (422, "invalid")
        assert "another name" in error.message
        assert data(own) == {}

    def test_a_name_that_is_taken_is_refused_before_the_file_is_read(self, own: Own) -> None:
        upload(own)

        class Unread(io.BytesIO):
            def read(self, size: int | None = -1) -> bytes:
                raise AssertionError("it should not have been read")

        error = refused(own.add_upload, "counts.csv", Unread(CSV), "Counts")

        assert error.code == "name_taken"

    def test_no_more_may_be_given_than_there_is_room_for(self, own: Own, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(own_module, "MAX_OWN_ITEMS", 2)
        upload(own, "one.csv")
        upload(own, "two.csv")

        error = refused(upload, own, "three.csv")

        assert (error.status, error.code) == (409, "too_many")
        assert sorted(data(own)) == ["one.csv", "two.csv"]


class TestPointingToWhatIsThere:
    def test_a_file_is_kept_where_it_is_and_left_alone(self, tmp_path: Path, workspace: Workspace, own: Own) -> None:
        path = made(tmp_path)

        own.add_path(str(path), "A table")

        assert data(own)["table.tsv"] == {
            "name": "table.tsv",
            "description": "A table",
            "source": "path",
            "path": str(path),
            "kind": "file",
            "bytes": path.stat().st_size,
            "modified": pytest.approx(path.stat().st_mtime),
        }
        assert path.read_bytes() == b"a\tb\n1\t2\n"
        assert not workspace.own_data_dir.exists()

    def test_a_folder_is_kept_where_it_is(self, tmp_path: Path, own: Own) -> None:
        folder = tmp_path / "elsewhere" / "fastq"
        folder.mkdir(parents=True)
        (folder / "a.fastq").write_text("@read")

        own.add_path(str(folder), "Reads")

        item = data(own)["fastq"]
        assert (item["kind"], item["bytes"], item["path"]) == ("folder", None, str(folder))

    def test_a_path_may_begin_with_the_home_folder(
        self, tmp_path: Path, own: Own, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        (home / "data").mkdir(parents=True)
        (home / "data" / "table.tsv").write_text("a")
        monkeypatch.setenv("HOME", str(home))

        own.add_path("~/data/table.tsv", "A table")

        assert data(own)["table.tsv"]["path"] == str(home / "data" / "table.tsv")

    def test_a_link_is_found_by_its_own_name_and_is_kept_as_the_link_it_is(self, tmp_path: Path, own: Own) -> None:
        target = made(tmp_path, "v2.csv")
        link = target.parent / "latest.csv"
        link.symlink_to(target)

        own.add_path(str(link), "The latest")

        assert list(data(own)) == ["latest.csv"]
        assert data(own)["latest.csv"]["path"] == str(link)
        assert given(own.workspace, ["latest.csv"], [])[0] == {str(link): "The latest"}

    @pytest.mark.parametrize("path", ["", "   ", "table.tsv", "./table.tsv", "elsewhere/table.tsv", "a\x00b"])
    def test_a_path_that_is_not_a_full_path_is_refused(self, own: Own, path: str) -> None:
        error = refused(own.add_path, path, "A table")

        assert (error.status, error.code) == (422, "invalid")
        assert "full path" in error.message
        assert data(own) == {}

    def test_a_path_to_a_home_folder_of_nobody_is_refused(self, own: Own) -> None:
        error = refused(own.add_path, "~nobody-has-this-name-xyz/table.tsv", "A table")

        assert error.status == 422

    def test_nothing_there_is_refused(self, tmp_path: Path, own: Own) -> None:
        error = refused(own.add_path, str(tmp_path / "nowhere.csv"), "Nothing")

        assert (error.status, error.code) == (422, "invalid")
        assert f"There is nothing at {tmp_path / 'nowhere.csv'}" in error.message

    def test_a_link_that_leads_nowhere_is_refused(self, tmp_path: Path, own: Own) -> None:
        link = tmp_path / "broken.csv"
        link.symlink_to(tmp_path / "gone.csv")

        assert refused(own.add_path, str(link), "Broken").status == 422

    def test_what_is_neither_a_file_nor_a_folder_is_refused(self, tmp_path: Path, own: Own) -> None:
        pipe = tmp_path / "pipe"
        os.mkfifo(pipe)

        error = refused(own.add_path, str(pipe), "A pipe")

        assert (error.status, error.code) == (422, "invalid")
        assert "neither a file nor a folder" in error.message

    def test_the_whole_of_the_file_system_is_refused_for_having_no_name(self, own: Own) -> None:
        error = refused(own.add_path, "/", "Everything")

        assert error.status == 422
        assert "not all of it" in error.message

    def test_where_conversations_are_kept_and_what_holds_them_is_refused(
        self, tmp_path: Path, workspace: Workspace, own: Own
    ) -> None:
        inside = workspace.chats_dir / "2026-01-01_0000_x" / "work"
        inside.mkdir(parents=True)
        (inside / "plot.png").write_bytes(b"x")

        for path in (workspace.chats_dir, inside, inside / "plot.png", workspace.root, tmp_path):
            error = refused(own.add_path, str(path), "Mine")
            assert (error.status, error.code) == (422, "invalid"), path
            assert "is where conversations are kept, or holds them" in error.message, path
        assert data(own) == {}

    def test_what_was_uploaded_is_not_given_a_second_time_by_where_it_is_kept(
        self, workspace: Workspace, own: Own
    ) -> None:
        upload(own)

        for path in (workspace.own_data_dir, workspace.own_data_dir / "counts.csv"):
            error = refused(own.add_path, str(path), "Again")
            assert error.status == 422, path
            assert "is where uploaded files are kept, or holds them" in error.message, path
        assert list(data(own)) == ["counts.csv"]

    def test_what_holds_the_uploads_is_refused_wherever_they_are_kept(
        self, tmp_path: Path, workspace: Workspace, own: Own, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        away = tmp_path / "away"
        (away / "uploads").mkdir(parents=True)
        (away / "uploads" / "a.csv").write_text("a")
        monkeypatch.setattr(Workspace, "own_data_dir", property(lambda self: away / "uploads"))

        for path in (away, away / "uploads", away / "uploads" / "a.csv"):
            error = refused(own.add_path, str(path), "Again")
            assert "is where uploaded files are kept, or holds them" in error.message, path
        assert data(own) == {}

    def test_a_name_taken_while_it_is_being_kept_is_refused_and_leaves_the_one_that_got_there(
        self, tmp_path: Path, own: Own, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = made(tmp_path)
        looked = own.check_room
        interrupted = []

        def meanwhile(name: str, kept: Any = None) -> None:
            looked(name, kept)
            if not interrupted:
                interrupted.append(name)
                upload(own, "table.tsv", description="Quicker")

        monkeypatch.setattr(own, "check_room", meanwhile)

        error = refused(own.add_path, str(path), "Slower")

        assert (error.status, error.code) == (409, "name_taken")
        assert data(own)["table.tsv"]["description"] == "Quicker"
        assert data(own)["table.tsv"]["source"] == "uploaded"

    def test_a_path_with_a_control_character_in_it_is_refused_even_if_what_holds_it_is_what_has_it(
        self, tmp_path: Path, own: Own
    ) -> None:
        holder = tmp_path / "bell\x07"
        holder.mkdir()
        (holder / "table.tsv").write_text("a")

        error = refused(own.add_path, str(holder / "table.tsv"), "Mine")

        assert (error.status, error.code) == (422, "invalid")
        assert "full path" in error.message
        assert data(own) == {}

    @pytest.mark.parametrize("name", ["a,b.csv", 'say "so".csv'])
    def test_a_name_docker_cannot_mount_is_refused(self, tmp_path: Path, own: Own, name: str) -> None:
        error = refused(own.add_path, str(made(tmp_path, name)), "Mine")

        assert (error.status, error.code) == (422, "invalid")
        assert "another name" in error.message

    def test_a_path_docker_cannot_mount_is_refused(self, tmp_path: Path, own: Own) -> None:
        path = tmp_path / "a,b" / "table.tsv"
        path.parent.mkdir()
        path.write_text("a")

        error = refused(own.add_path, str(path), "Mine")

        assert (error.status, error.code) == (422, "invalid")
        assert "Move it" in error.message

    def test_a_name_that_is_taken_is_refused_whether_it_was_uploaded_or_pointed_to(
        self, tmp_path: Path, own: Own
    ) -> None:
        upload(own, "table.tsv")
        first = made(tmp_path, "other.tsv")
        own.add_path(str(first), "First")

        assert refused(own.add_path, str(made(tmp_path, "table.tsv")), "Second").code == "name_taken"
        elsewhere = tmp_path / "second" / "other.tsv"
        elsewhere.parent.mkdir()
        elsewhere.write_text("b")
        assert refused(own.add_path, str(elsewhere), "Second").code == "name_taken"
        assert refused(upload, own, "other.tsv").code == "name_taken"
        assert data(own)["other.tsv"]["path"] == str(first)

    @pytest.mark.parametrize("description", ["", "  ", None])
    def test_what_it_is_has_to_be_said(self, tmp_path: Path, own: Own, description: Any) -> None:
        error = refused(own.add_path, str(made(tmp_path)), description)

        assert (error.status, error.code) == (422, "invalid")
        assert data(own) == {}

    def test_no_more_may_be_given_than_there_is_room_for(
        self, tmp_path: Path, own: Own, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(own_module, "MAX_OWN_ITEMS", 1)
        own.add_path(str(made(tmp_path, "one.tsv")), "One")

        assert refused(own.add_path, str(made(tmp_path, "two.tsv")), "Two").code == "too_many"


class TestChangingAndGivingUp:
    def test_what_it_is_can_be_said_again(self, own: Own) -> None:
        upload(own, description="Old")

        own.change_description("counts.csv", "  New \n words ")

        assert data(own)["counts.csv"]["description"] == "New words"

    def test_what_it_is_cannot_be_said_again_as_nothing_or_of_what_is_not_there(self, own: Own) -> None:
        upload(own, description="Old")

        assert refused(own.change_description, "counts.csv", " ").status == 422
        assert refused(own.change_description, "nothing.csv", "New").status == 404
        assert data(own)["counts.csv"]["description"] == "Old"

    def test_a_file_that_was_uploaded_is_deleted_when_given_up(self, workspace: Workspace, own: Own) -> None:
        upload(own)

        own.remove("counts.csv")

        assert data(own) == {}
        assert not (workspace.own_data_dir / "counts.csv").exists()

    def test_what_was_pointed_to_is_left_where_it_is_when_given_up(self, tmp_path: Path, own: Own) -> None:
        path = made(tmp_path)
        folder = tmp_path / "elsewhere" / "reads"
        folder.mkdir()
        (folder / "a.fastq").write_text("@")
        own.add_path(str(path), "A table")
        own.add_path(str(folder), "Reads")

        own.remove("table.tsv")
        own.remove("reads")

        assert data(own) == {}
        assert path.read_bytes() == b"a\tb\n1\t2\n"
        assert (folder / "a.fastq").read_text() == "@"

    def test_a_link_that_was_pointed_to_is_given_up_without_its_target(self, tmp_path: Path, own: Own) -> None:
        target = made(tmp_path, "v2.csv")
        link = target.parent / "latest.csv"
        link.symlink_to(target)
        own.add_path(str(link), "Latest")

        own.remove("latest.csv")

        assert link.is_symlink() and target.read_bytes()

    def test_a_name_that_is_a_place_elsewhere_in_a_file_edited_by_hand_deletes_nothing(
        self, tmp_path: Path, workspace: Workspace, own: Own
    ) -> None:
        victim = tmp_path / "victim.txt"
        victim.write_text("keep me")
        workspace.own_path.write_text(json.dumps({"data": {"../../victim.txt": {"description": "Odd"}}}))

        error = refused(own.remove, "../../victim.txt")

        assert error.status == 404
        assert victim.read_text() == "keep me"

    def test_a_file_that_is_gone_is_given_up_all_the_same(self, workspace: Workspace, own: Own) -> None:
        upload(own)
        (workspace.own_data_dir / "counts.csv").unlink()

        own.remove("counts.csv")

        assert data(own) == {}

    def test_what_is_not_there_cannot_be_given_up(self, own: Own) -> None:
        error = refused(own.remove, "nothing.csv")

        assert (error.status, error.code) == (404, "not_found")

    def test_a_name_may_be_used_again_once_it_is_given_up(self, own: Own) -> None:
        upload(own, content=b"first")
        own.remove("counts.csv")

        upload(own, content=b"second")

        assert data(own)["counts.csv"]["bytes"] == len(b"second")


class TestWhatIsSaidOfIt:
    def test_data_that_is_gone_is_said_to_be_missing(self, tmp_path: Path, workspace: Workspace, own: Own) -> None:
        path = made(tmp_path)
        own.add_path(str(path), "A table")
        upload(own)
        path.unlink()
        (workspace.own_data_dir / "counts.csv").unlink()

        shown = data(own)

        for name in ("table.tsv", "counts.csv"):
            assert (shown[name]["kind"], shown[name]["bytes"], shown[name]["modified"]) == ("missing", None, None)
            assert shown[name]["description"]

    def test_a_file_that_has_become_neither_a_file_nor_a_folder_is_said_to_be_missing(
        self, tmp_path: Path, own: Own
    ) -> None:
        path = made(tmp_path)
        own.add_path(str(path), "A table")
        path.unlink()
        os.mkfifo(path)

        assert data(own)["table.tsv"]["kind"] == "missing"

    def test_the_data_is_listed_in_the_order_it_was_given(self, tmp_path: Path, own: Own) -> None:
        upload(own, "b.csv")
        own.add_path(str(made(tmp_path, "a.tsv")), "A")
        upload(own, "c.csv")

        assert [item["name"] for item in own.describe()["data"]] == ["b.csv", "a.tsv", "c.csv"]


class TestPreviewing:
    def preview(self, own: Own, content: bytes) -> dict[str, Any]:
        upload(own, "file.txt", content)

        return own.preview("file.txt")

    def test_the_first_lines_of_a_text_file_are_shown(self, own: Own) -> None:
        assert self.preview(own, CSV) == {
            "kind": "text",
            "lines": ["gene,score", "TP53,0.91", "BRCA1,0.20"],
            "truncated": False,
        }

    def test_a_file_with_nothing_in_it_has_no_lines(self, own: Own) -> None:
        assert self.preview(own, b"") == {"kind": "text", "lines": [], "truncated": False}

    def test_a_file_with_as_many_lines_as_are_shown_is_shown_whole(self, own: Own) -> None:
        shown = self.preview(own, "".join(f"line {number}\n" for number in range(PREVIEW_LINES)).encode())

        assert len(shown["lines"]) == PREVIEW_LINES
        assert shown["truncated"] is False

    def test_a_file_with_more_lines_is_cut_and_said_to_be(self, own: Own) -> None:
        shown = self.preview(own, "".join(f"line {number}\n" for number in range(PREVIEW_LINES + 1)).encode())

        assert shown["lines"] == [f"line {number}" for number in range(PREVIEW_LINES)]
        assert shown["truncated"] is True

    def test_a_line_that_is_too_long_is_cut_and_the_file_said_to_be(self, own: Own) -> None:
        shown = self.preview(own, b"short\n" + b"x" * (PREVIEW_LINE_CHARS + 1) + b"\n")

        assert shown["lines"] == ["short", "x" * PREVIEW_LINE_CHARS]
        assert shown["truncated"] is True

    def test_a_line_as_long_as_is_shown_is_not_cut(self, own: Own) -> None:
        shown = self.preview(own, b"x" * PREVIEW_LINE_CHARS)

        assert shown["lines"] == ["x" * PREVIEW_LINE_CHARS]
        assert shown["truncated"] is False

    def test_only_the_start_of_a_big_file_is_read(self, own: Own, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(own_module, "PREVIEW_BYTES", 16)
        monkeypatch.setattr(own, "max_upload_bytes", 1 << 20)

        shown = self.preview(own, b"x" * 15 + b"\n" + b"y" * 100)

        assert shown == {"kind": "text", "lines": ["x" * 15], "truncated": True}

    def test_a_file_with_as_many_bytes_as_are_read_is_not_said_to_be_cut(
        self, own: Own, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(own_module, "PREVIEW_BYTES", 16)

        assert self.preview(own, b"x" * 16) == {"kind": "text", "lines": ["x" * 16], "truncated": False}

    def test_what_is_not_utf8_is_shown_as_what_could_be_read(self, own: Own) -> None:
        shown = self.preview(own, b"caf\xe9,1\n")

        assert shown["kind"] == "text"
        assert shown["lines"] == ["caf\ufffd,1"]

    def test_a_file_with_a_zero_byte_is_binary_and_none_of_it_is_shown(self, own: Own) -> None:
        assert self.preview(own, b"BAM\x01\x00\x00records") == {"kind": "binary"}

    def test_a_folder_shows_what_is_in_it_with_folders_first(self, tmp_path: Path, own: Own) -> None:
        folder = tmp_path / "elsewhere" / "reads"
        (folder / "lanes").mkdir(parents=True)
        (folder / "b.fastq").write_text("@")
        (folder / "A.fastq").write_text("@")
        own.add_path(str(folder), "Reads")

        assert own.preview("reads") == {
            "kind": "folder",
            "entries": [
                {"name": "lanes", "folder": True},
                {"name": "A.fastq", "folder": False},
                {"name": "b.fastq", "folder": False},
            ],
            "more": 0,
        }

    def test_a_folder_with_a_lot_in_it_shows_some_and_says_how_many_more(self, tmp_path: Path, own: Own) -> None:
        folder = tmp_path / "elsewhere" / "many"
        folder.mkdir(parents=True)
        for number in range(PREVIEW_ENTRIES + 3):
            (folder / f"{number:04}.txt").write_text("x")
        own.add_path(str(folder), "Many")

        shown = own.preview("many")

        assert len(shown["entries"]) == PREVIEW_ENTRIES
        assert shown["more"] == 3

    def test_data_that_is_gone_has_nothing_to_show(self, tmp_path: Path, own: Own) -> None:
        path = made(tmp_path)
        own.add_path(str(path), "A table")
        path.unlink()

        assert own.preview("table.tsv") == {"kind": "missing"}

    def test_a_file_that_cannot_be_read_has_nothing_to_show(self, tmp_path: Path, own: Own) -> None:
        path = made(tmp_path)
        own.add_path(str(path), "A table")
        path.chmod(0)
        try:
            shown = own.preview("table.tsv")
        finally:
            path.chmod(0o600)

        # Where nothing stops a file being read, as for root, it is read
        assert shown["kind"] in ("missing", "text")

    def test_what_is_not_given_has_nothing_to_show(self, own: Own) -> None:
        assert refused(own.preview, "nothing.csv").status == 404


class TestSoftware:
    def test_software_is_kept_with_what_it_is_for(self, workspace: Workspace, own: Own) -> None:
        own.put_software("samtools", "Reads and writes alignments")

        assert own.describe()["software"] == [{"name": "samtools", "description": "Reads and writes alignments"}]
        assert workspace.load_own()["software"] == {"samtools": "Reads and writes alignments"}

    def test_software_given_again_is_replaced_and_keeps_its_place(self, own: Own) -> None:
        own.put_software("samtools", "Old")
        own.put_software("bwa", "Aligns")

        own.put_software("samtools", "New")

        assert own.describe()["software"] == [
            {"name": "samtools", "description": "New"},
            {"name": "bwa", "description": "Aligns"},
        ]

    def test_a_name_and_what_it_is_for_are_made_one_line_of_words(self, own: Own) -> None:
        own.put_software("  my \n tool ", " does \t a thing ")

        assert own.describe()["software"] == [{"name": "my tool", "description": "does a thing"}]

    @pytest.mark.parametrize("name", ["", "   ", "x" * 101, "bell\x07", "nul\x00"])
    def test_a_name_that_cannot_be_kept_is_refused(self, own: Own, name: str) -> None:
        error = refused(own.put_software, name, "Does a thing")

        assert (error.status, error.code) == (422, "invalid")
        assert own.describe()["software"] == []

    def test_a_name_as_long_as_may_be_kept_is_kept(self, own: Own) -> None:
        own.put_software("x" * 100, "Does a thing")

        assert len(own.describe()["software"]) == 1

    @pytest.mark.parametrize("description", ["", "  ", "x" * (MAX_DESCRIPTION_CHARS + 1)])
    def test_what_it_is_for_has_to_be_said_in_a_few_words(self, own: Own, description: str) -> None:
        assert refused(own.put_software, "samtools", description).status == 422

    def test_no_more_may_be_given_than_there_is_room_for_but_one_that_is_there_may_be_said_again(
        self, own: Own, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(own_module, "MAX_OWN_ITEMS", 1)
        own.put_software("samtools", "Old")

        own.put_software("samtools", "New")

        assert refused(own.put_software, "bwa", "Aligns").code == "too_many"
        assert own.describe()["software"] == [{"name": "samtools", "description": "New"}]

    def test_software_is_given_up(self, own: Own) -> None:
        own.put_software("samtools", "Reads")

        own.remove_software("samtools")

        assert own.describe()["software"] == []

    def test_software_that_is_not_given_cannot_be_given_up(self, own: Own) -> None:
        assert refused(own.remove_software, "samtools").status == 404


class TestWhatASessionIsGiven:
    def test_each_piece_of_data_is_given_by_its_path_with_what_it_is_and_software_by_its_name(
        self, tmp_path: Path, workspace: Workspace, own: Own
    ) -> None:
        upload(own, description="Counts")
        path = made(tmp_path)
        own.add_path(str(path), "A table")
        own.put_software("samtools", "Reads")

        files, software = given(workspace, ["counts.csv", "table.tsv"], ["samtools"])

        assert files == {str(workspace.own_data_dir / "counts.csv"): "Counts", str(path): "A table"}
        assert software == {"samtools": "Reads"}

    def test_only_what_is_asked_for_is_given(self, workspace: Workspace, own: Own) -> None:
        upload(own, "a.csv")
        upload(own, "b.csv")
        own.put_software("samtools", "Reads")
        own.put_software("bwa", "Aligns")

        files, software = given(workspace, ["b.csv"], ["bwa"])

        assert list(files) == [str(workspace.own_data_dir / "b.csv")]
        assert software == {"bwa": "Aligns"}

    def test_what_is_not_given_to_the_lab_any_more_or_is_not_there_any_more_is_left_out(
        self, tmp_path: Path, workspace: Workspace, own: Own
    ) -> None:
        upload(own, "kept.csv")
        upload(own, "gone.csv")
        path = made(tmp_path)
        own.add_path(str(path), "A table")
        (workspace.own_data_dir / "gone.csv").unlink()
        path.unlink()

        files, software = given(workspace, ["kept.csv", "gone.csv", "table.tsv", "never.csv"], ["nothing"])

        assert list(files) == [str(workspace.own_data_dir / "kept.csv")]
        assert software == {}

    def test_data_whose_path_is_not_called_what_it_is_is_left_out_since_code_would_find_it_by_another_name(
        self, tmp_path: Path, workspace: Workspace
    ) -> None:
        path = made(tmp_path, "real.csv")
        workspace.own_path.write_text(json.dumps({"data": {"other.csv": {"description": "Odd", "path": str(path)}}}))

        assert given(workspace, ["other.csv"], []) == ({}, {})

    def test_a_link_that_has_come_to_lead_where_docker_cannot_mount_is_left_out(
        self, tmp_path: Path, workspace: Workspace, own: Own
    ) -> None:
        good = made(tmp_path, "v1.csv")
        link = good.parent / "latest.csv"
        link.symlink_to(good)
        own.add_path(str(link), "The latest")
        upload(own)
        commas = tmp_path / "a,b"
        commas.mkdir()
        (commas / "v2.csv").write_text("x")
        link.unlink()
        link.symlink_to(commas / "v2.csv")

        files, _ = given(workspace, ["latest.csv", "counts.csv"], [])

        assert list(files) == [str(workspace.own_data_dir / "counts.csv")]

    def test_a_link_that_has_come_to_lead_to_where_conversations_are_kept_or_to_what_holds_them_is_left_out(
        self, tmp_path: Path, workspace: Workspace, own: Own
    ) -> None:
        good = made(tmp_path, "v1.csv")
        inside = workspace.chats_dir / "2026-01-01_0000_x"
        inside.mkdir()
        links = {}
        for name, target in (("into", inside), ("around", workspace.root), ("chats", workspace.chats_dir)):
            link = good.parent / name
            link.symlink_to(good)
            own.add_path(str(link), name)
            link.unlink()
            link.symlink_to(target)
            links[name] = link
        upload(own)

        files, _ = given(workspace, [*links, "counts.csv"], [])

        assert list(files) == [str(workspace.own_data_dir / "counts.csv")]

    def test_nothing_is_given_when_nothing_is_asked_for(self, workspace: Workspace, own: Own) -> None:
        upload(own)

        assert given(workspace, [], []) == ({}, {})


class TestCheckingNames:
    def test_names_are_kept_once_each_in_the_order_given(self) -> None:
        assert check_own_names(["b", "a", "b"], ["a", "b", "c"], "data") == ["b", "a"]

    def test_a_name_that_was_not_given_to_the_lab_is_refused_and_what_there_is_is_said(self) -> None:
        with pytest.raises(ValueError, match="no data named x.csv given to the lab: there is a.csv, b.csv"):
            check_own_names(["x.csv"], ["a.csv", "b.csv"], "data")

    def test_it_is_said_when_nothing_was_given_at_all(self) -> None:
        with pytest.raises(ValueError, match="there is none"):
            check_own_names(["x"], [], "software")

    @pytest.mark.parametrize("names", ["a", None, {"a": 1}, 3])
    def test_names_that_are_not_a_list_are_refused(self, names: Any) -> None:
        with pytest.raises(ValueError, match="a list of names"):
            check_own_names(names, ["a"], "data")

    def test_a_name_that_is_not_text_is_refused(self) -> None:
        with pytest.raises(ValueError, match="no data named 3"):
            check_own_names([3], ["a"], "data")

    @pytest.mark.parametrize("name", [["a"], {"a": 1}])
    def test_a_name_that_cannot_even_be_looked_up_is_refused_the_same_way(self, name: Any) -> None:
        with pytest.raises(ValueError, match="no data named"):
            check_own_names([name], {"a": 1}, "data")


class TestWhatIsAFileNameAndAFullPath:
    @pytest.mark.parametrize("name", ["counts.csv", "my counts (2).csv", "séquences.fa", ".hidden", "a\\b", "a..b"])
    def test_a_name_of_one_file_is_one(self, name: str) -> None:
        assert is_file_name(name)

    @pytest.mark.parametrize(
        "name", ["", ".", "..", "a/b", "/a", "a/", "../a", "a\x00b", "a\x1fb", "a\x7fb", "a\x01", "a\n", 3, None, ["a"]]
    )
    def test_what_is_not_the_name_of_one_file_is_not_one(self, name: Any) -> None:
        assert not is_file_name(name)

    def test_a_full_path_is_one_that_begins_at_the_root_and_is_text_without_control_characters(self) -> None:
        assert is_full_path("/data/a b.csv")
        for path in ("a.csv", "./a.csv", "~/a.csv", "", "/a\x00b", "/a\x1fb", "/a\nb", 3, None):
            assert not is_full_path(path), path


class TestNamesOfData:
    @pytest.mark.parametrize("name", ["", ".", "..", "a\x07b", "a\nb", "a\x7f"])
    def test_what_cannot_be_the_name_of_a_file_that_code_is_given_is_refused(self, name: str) -> None:
        with pytest.raises(ApiError) as caught:
            check_name(name)

        assert (caught.value.status, caught.value.code) == (422, "invalid")

    @pytest.mark.parametrize("name", ["counts.csv", "my counts (2).csv", "séquences.fa", "a-b_c.tar.gz"])
    def test_an_ordinary_name_is_kept_as_it_is(self, name: str) -> None:
        assert check_name(name) == name


class TestConfiguring:
    def test_a_conversation_is_given_all_of_what_was_given_to_the_lab_unless_it_is_told_which(
        self, workspace: Workspace, own: Own
    ) -> None:
        upload(own, "a.csv")
        upload(own, "b.csv")
        own.put_software("samtools", "Reads")

        config = resolve_config({}, workspace.load_settings(), workspace)

        assert (config.data, config.software) == (("a.csv", "b.csv"), ("samtools",))

    def test_a_conversation_may_be_given_some_of_it_or_none(self, workspace: Workspace, own: Own) -> None:
        upload(own, "a.csv")
        upload(own, "b.csv")
        own.put_software("samtools", "Reads")
        settings = workspace.load_settings()

        some = resolve_config({"data": ["b.csv"], "software": []}, settings, workspace)
        none = resolve_config({"data": [], "software": ["samtools"]}, settings, workspace)

        assert (some.data, some.software) == (("b.csv",), ())
        assert (none.data, none.software) == ((), ("samtools",))

    def test_what_was_not_given_to_the_lab_cannot_be_chosen(self, workspace: Workspace, own: Own) -> None:
        upload(own, "a.csv")
        settings = workspace.load_settings()

        with pytest.raises(ValueError, match="no data named x.csv"):
            resolve_config({"data": ["x.csv"]}, settings, workspace)
        with pytest.raises(ValueError, match="no software named x"):
            resolve_config({"software": ["x"]}, settings, workspace)

    def test_what_a_conversation_is_given_is_kept_with_it(self, workspace: Workspace, own: Own) -> None:
        upload(own, "a.csv")
        own.put_software("samtools", "Reads")
        config = resolve_config({}, workspace.load_settings(), workspace)

        again = ChatConfig.from_dict(json.loads(json.dumps(config.to_dict())))

        assert again == config
        assert config.to_dict()["data"] == ["a.csv"]
        assert config.to_dict()["software"] == ["samtools"]

    def test_a_conversation_begun_before_the_lab_could_be_given_any_has_none(self, workspace: Workspace) -> None:
        saved = resolve_config({}, workspace.load_settings(), workspace).to_dict()
        del saved["data"], saved["software"]

        again = ChatConfig.from_dict(saved)

        assert (again.data, again.software) == ((), ())

    def test_a_name_written_twice_by_hand_is_one(self, workspace: Workspace) -> None:
        saved = resolve_config({}, workspace.load_settings(), workspace).to_dict()
        saved["data"] = ["a.csv", "a.csv"]

        assert ChatConfig.from_dict(saved).data == ("a.csv",)


class TestConversing:
    def local(self, **more: Any) -> dict[str, Any]:
        return {"team": [], "code": {"where": "local", "resources": "none"}, **more}

    def test_code_in_a_conversation_is_given_what_was_given_to_the_lab(
        self, tmp_path: Path, workspace: Workspace, own: Own, conversations: Conversations
    ) -> None:
        upload(own, description="Counts")
        path = made(tmp_path)
        own.add_path(str(path), "A table")
        own.put_software("samtools", "Reads")

        handle = conversations.create(self.local())

        assert handle.session is not None
        assert {item.name: (item.source, item.description) for item in handle.session.data} == {
            "counts.csv": ((workspace.own_data_dir / "counts.csv").resolve(), "Counts"),
            "table.tsv": (path.resolve(), "A table"),
        }
        assert handle.session.software == {"samtools": "Reads"}

    def test_a_conversation_may_be_given_only_some_of_it(
        self, workspace: Workspace, own: Own, conversations: Conversations
    ) -> None:
        upload(own, "a.csv")
        upload(own, "b.csv")
        own.put_software("samtools", "Reads")

        handle = conversations.create(self.local(data=["b.csv"], software=[]))

        assert handle.session is not None
        assert [item.name for item in handle.session.data] == ["b.csv"]
        assert handle.session.software == {}

    def test_a_conversation_that_runs_no_code_keeps_what_it_was_given_and_has_no_session(
        self, own: Own, conversations: Conversations
    ) -> None:
        upload(own)

        handle = conversations.create({"team": []})

        assert handle.session is None
        assert handle.config.data == ("counts.csv",)

    def test_the_lead_is_told_what_each_piece_is_and_where_code_reads_it(
        self, workspace: Workspace, own: Own, conversations: Conversations, fake_client: FakeClient
    ) -> None:
        upload(own, description="Read counts of the screen")
        fake_client.completions.queue = []
        handle = conversations.create(self.local(software=[]))

        handle.chat.start("Look at the counts").join(30)

        system = fake_client.completions.calls[0]["messages"][0]["content"]
        assert "Read counts of the screen" in system
        assert str((workspace.own_data_dir / "counts.csv").resolve()) in system

    def test_the_lead_is_told_of_software_that_is_not_there_so_that_it_is_checked_before_it_is_relied_on(
        self, own: Own, conversations: Conversations, fake_client: FakeClient
    ) -> None:
        own.put_software("no-such-software-xyz", "Does a thing")
        handle = conversations.create(self.local(data=[]))

        handle.chat.start("Use it").join(60)

        system = fake_client.completions.calls[0]["messages"][0]["content"]
        assert "no-such-software-xyz" in system
        assert "not found in the session" in system

    def test_a_conversation_is_opened_again_without_what_has_been_given_up_or_has_gone(
        self, tmp_path: Path, workspace: Workspace, own: Own, conversations: Conversations
    ) -> None:
        upload(own, "given-up.csv")
        upload(own, "deleted.csv")
        upload(own, "kept.csv")
        path = made(tmp_path)
        own.add_path(str(path), "A table")
        own.put_software("samtools", "Reads")
        handle = conversations.create(self.local())
        conversations.close()
        own.remove("given-up.csv")
        (workspace.own_data_dir / "deleted.csv").unlink()
        path.unlink()
        own.remove_software("samtools")

        again = Conversations(workspace, check_keys=False)
        try:
            reopened = again.get(handle.id)

            assert reopened.session is not None
            assert [item.name for item in reopened.session.data] == ["kept.csv"]
            assert reopened.session.software == {}
        finally:
            again.close()

    def test_a_conversation_begun_before_data_was_given_does_not_have_it_when_opened_again(
        self, workspace: Workspace, own: Own, conversations: Conversations
    ) -> None:
        handle = conversations.create(self.local())
        conversations.close()
        upload(own)

        again = Conversations(workspace, check_keys=False)
        try:
            reopened = again.get(handle.id)

            assert reopened.session is not None
            assert reopened.session.data == ()
        finally:
            again.close()

    @pytest.mark.parametrize(
        "code", [{"where": "docker", "sandbox": "python"}, {"where": "local", "resources": "none"}]
    )
    def test_a_conversation_is_made_though_a_link_that_was_pointed_to_now_leads_around_where_it_is_kept(
        self, tmp_path: Path, workspace: Workspace, own: Own, conversations: Conversations, code: dict[str, Any]
    ) -> None:
        good = made(tmp_path, "v1.csv")
        link = good.parent / "latest.csv"
        link.symlink_to(good)
        own.add_path(str(link), "The latest")
        upload(own, description="Counts")
        link.unlink()
        link.symlink_to(workspace.root)

        handle = conversations.create({"team": [], "code": code})

        assert handle.session is not None
        assert [item.name for item in handle.session.data] == ["counts.csv"]

    def test_the_session_of_docker_is_given_it_to_mount_where_code_finds_it(
        self, tmp_path: Path, workspace: Workspace, own: Own, conversations: Conversations
    ) -> None:
        upload(own, description="Counts")
        path = made(tmp_path)
        own.add_path(str(path), "A table")
        own.put_software("samtools", "Reads")

        handle = conversations.create({"team": [], "code": {"where": "docker", "sandbox": "python"}})

        assert isinstance(handle.session, session_module.DockerSession)
        assert sorted(target for _, target in handle.session.mounts()) == ["/data/counts.csv", "/data/table.tsv"]
        assert handle.session.software == {"samtools": "Reads"}


class TestTheApi:
    def test_nothing_of_it_is_answered_without_the_token(self, workspace: Workspace) -> None:
        app = create_app(workspace.root, token=TOKEN, check_keys=False)
        with TestClient(app, base_url=LOCAL) as anonymous:
            for method, path in [
                ("get", "/api/own"),
                ("post", "/api/own/data/paths"),
                ("patch", "/api/own/data/x"),
                ("delete", "/api/own/data/x"),
                ("get", "/api/own/data/x/preview"),
                ("put", "/api/own/software"),
                ("delete", "/api/own/software/x"),
            ]:
                assert getattr(anonymous, method)(path).status_code == 401, path
            assert anonymous.post("/api/own/data/files?name=x&description=y", content=b"x").status_code == 401

    def test_it_begins_empty(self, client: TestClient) -> None:
        assert client.get("/api/own").json() == {"data": [], "software": [], "max_upload_bytes": LIMIT}

    def test_a_file_is_uploaded_as_the_body_and_the_list_is_the_answer(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        response = client.post(
            "/api/own/data/files", params={"name": "my counts.csv", "description": "Read counts"}, content=CSV
        )

        assert response.status_code == 201
        (item,) = response.json()["data"]
        assert (item["name"], item["description"], item["source"], item["kind"], item["bytes"]) == (
            "my counts.csv",
            "Read counts",
            "uploaded",
            "file",
            len(CSV),
        )
        assert (workspace.own_data_dir / "my counts.csv").read_bytes() == CSV
        assert client.get("/api/own").json()["data"] == [item]

    def test_a_name_that_is_taken_is_a_conflict_in_the_shape_of_every_error(self, client: TestClient) -> None:
        client.post("/api/own/data/files", params={"name": "a.csv", "description": "A"}, content=CSV)

        response = client.post("/api/own/data/files", params={"name": "a.csv", "description": "B"}, content=b"x")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "name_taken"

    def test_a_file_that_says_it_is_too_big_is_turned_away_before_it_is_read(self, client: TestClient) -> None:
        response = client.post(
            "/api/own/data/files", params={"name": "big.bin", "description": "Big"}, content=b"x" * (LIMIT + 1)
        )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "too_large"
        assert client.get("/api/own").json()["data"] == []

    def test_a_file_that_says_it_is_too_big_is_turned_away_without_a_byte_of_it_being_read(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        sent = asyncio.run(
            call_app(
                client.app,
                "POST",
                "/api/own/data/files",
                "name=big.bin&description=Big",
                {"content-length": str(LIMIT + 1)},
                lambda: fail("The body was read"),
            )
        )

        assert sent[0]["status"] == 413
        assert json.loads(sent[1]["body"])["error"]["code"] == "too_large"
        assert client.get("/api/own").json()["data"] == []
        assert parts(workspace) == []

    def test_a_sender_that_goes_away_part_of_the_way_is_not_an_error_of_the_server_and_leaves_nothing(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        messages = iter([{"type": "http.request", "body": b"abc", "more_body": True}, {"type": "http.disconnect"}])

        sent = asyncio.run(
            call_app(
                client.app, "POST", "/api/own/data/files", "name=cut.bin&description=Cut", {}, lambda: next(messages)
            )
        )

        assert [message["status"] for message in sent if message["type"] == "http.response.start"] == [499]
        assert client.get("/api/own").json()["data"] == []
        assert not (workspace.own_data_dir / "cut.bin").exists()
        assert parts(workspace) == []

    def test_a_file_that_does_not_say_how_big_it_is_is_cut_off_when_it_is_too_big(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        def chunks() -> Iterator[bytes]:
            for _ in range(LIMIT // 100 + 2):
                yield b"x" * 100

        response = client.post(
            "/api/own/data/files", params={"name": "big.bin", "description": "Big"}, content=chunks()
        )

        assert response.status_code == 413
        assert client.get("/api/own").json()["data"] == []
        assert parts(workspace) == []

    @pytest.mark.parametrize(
        "params",
        [
            {"name": "a.csv"},
            {"description": "A"},
            {"name": "", "description": "A"},
            {"name": "a.csv", "description": ""},
            {"name": "a.csv", "description": "  "},
            {"name": "a.csv", "description": "x" * (MAX_DESCRIPTION_CHARS * 4 + 1)},
        ],
    )
    def test_an_upload_that_lacks_what_it_needs_is_refused(self, client: TestClient, params: dict[str, str]) -> None:
        response = client.post("/api/own/data/files", params=params, content=CSV)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid"
        assert client.get("/api/own").json()["data"] == []

    def test_a_file_is_pointed_to_by_its_path(self, client: TestClient, tmp_path: Path) -> None:
        path = made(tmp_path)

        response = client.post("/api/own/data/paths", json={"path": str(path), "description": "A table"})

        assert response.status_code == 201
        (item,) = response.json()["data"]
        assert (item["name"], item["source"], item["path"]) == ("table.tsv", "path", str(path))

    @pytest.mark.parametrize(
        "body",
        [
            {"path": "", "description": "A"},
            {"path": "/x"},
            {"description": "A"},
            {"path": "/x", "description": "A", "name": "y"},
            {"path": 3, "description": "A"},
        ],
    )
    def test_a_path_that_is_not_asked_for_properly_is_refused(self, client: TestClient, body: dict[str, Any]) -> None:
        response = client.post("/api/own/data/paths", json=body)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid"

    def test_a_path_that_is_not_there_is_refused_with_what_is_wrong(self, client: TestClient, tmp_path: Path) -> None:
        response = client.post("/api/own/data/paths", json={"path": str(tmp_path / "no.csv"), "description": "A"})

        assert response.status_code == 422
        assert "no.csv" in response.json()["error"]["message"]

    def test_what_it_is_is_said_again(self, client: TestClient) -> None:
        client.post("/api/own/data/files", params={"name": "my counts.csv", "description": "Old"}, content=CSV)

        response = client.patch("/api/own/data/my%20counts.csv", json={"description": "New"})

        assert response.status_code == 200
        assert response.json()["data"][0]["description"] == "New"

    def test_what_is_not_given_is_not_found_whatever_is_done_to_it(self, client: TestClient) -> None:
        for response in (
            client.patch("/api/own/data/x.csv", json={"description": "New"}),
            client.delete("/api/own/data/x.csv"),
            client.get("/api/own/data/x.csv/preview"),
            client.delete("/api/own/software/x"),
        ):
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "not_found"

    def test_what_is_changed_with_more_than_a_description_is_refused(self, client: TestClient) -> None:
        client.post("/api/own/data/files", params={"name": "a.csv", "description": "A"}, content=CSV)

        response = client.patch("/api/own/data/a.csv", json={"description": "B", "name": "c.csv"})

        assert response.status_code == 422

    def test_data_is_given_up_and_the_list_without_it_is_the_answer(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        client.post("/api/own/data/files", params={"name": "a.csv", "description": "A"}, content=CSV)
        client.post("/api/own/data/files", params={"name": "b.csv", "description": "B"}, content=CSV)

        response = client.delete("/api/own/data/a.csv")

        assert response.status_code == 200
        assert [item["name"] for item in response.json()["data"]] == ["b.csv"]
        assert not (workspace.own_data_dir / "a.csv").exists()

    def test_data_is_found_by_its_name_as_it_was_written(self, client: TestClient) -> None:
        client.post("/api/own/data/files", params={"name": "Counts.CSV", "description": "Old"}, content=CSV)

        preview = client.get("/api/own/data/Counts.CSV/preview")
        changed = client.patch("/api/own/data/Counts.CSV", json={"description": "New"})
        lowercase = client.delete("/api/own/data/counts.csv")
        removed = client.delete("/api/own/data/Counts.CSV")

        assert preview.json()["kind"] == "text"
        assert changed.json()["data"][0]["description"] == "New"
        assert lowercase.status_code == 404
        assert removed.json()["data"] == []

    def test_what_is_at_the_start_of_data_is_shown(self, client: TestClient) -> None:
        client.post("/api/own/data/files", params={"name": "a.csv", "description": "A"}, content=CSV)

        response = client.get("/api/own/data/a.csv/preview")

        assert response.status_code == 200
        assert response.json() == {
            "kind": "text",
            "lines": ["gene,score", "TP53,0.91", "BRCA1,0.20"],
            "truncated": False,
        }

    def test_software_is_given_said_again_and_given_up(self, client: TestClient) -> None:
        added = client.put("/api/own/software", json={"name": "samtools", "description": "Reads"})
        again = client.put("/api/own/software", json={"name": "samtools", "description": "Reads and writes"})

        assert added.status_code == again.status_code == 200
        assert again.json()["software"] == [{"name": "samtools", "description": "Reads and writes"}]
        removed = client.delete("/api/own/software/samtools")
        assert removed.status_code == 200
        assert removed.json()["software"] == []

    def test_software_with_a_slash_in_its_name_is_given_up_by_that_name(self, client: TestClient) -> None:
        client.put("/api/own/software", json={"name": "bio/tool", "description": "Does a thing"})

        response = client.delete("/api/own/software/bio%2Ftool")

        assert response.status_code == 200
        assert response.json()["software"] == []

    @pytest.mark.parametrize(
        "body",
        [
            {"name": "", "description": "A"},
            {"name": "x"},
            {"name": "x", "description": ""},
            {"name": "x", "description": "A", "extra": 1},
            {"name": "x" * 401, "description": "A"},
        ],
    )
    def test_software_that_is_not_given_properly_is_refused(self, client: TestClient, body: dict[str, Any]) -> None:
        assert client.put("/api/own/software", json=body).status_code == 422

    def test_a_conversation_may_be_made_with_some_of_what_was_given_and_is_told_of_what_it_is_given(
        self, client: TestClient
    ) -> None:
        client.post("/api/own/data/files", params={"name": "a.csv", "description": "A"}, content=CSV)
        client.post("/api/own/data/files", params={"name": "b.csv", "description": "B"}, content=CSV)
        client.put("/api/own/software", json={"name": "samtools", "description": "Reads"})

        some = client.post("/api/chats", json={"team": [], "data": ["b.csv"], "software": []})
        everything = client.post("/api/chats", json={"team": []})

        assert some.status_code == everything.status_code == 201
        assert (some.json()["config"]["data"], some.json()["config"]["software"]) == (["b.csv"], [])
        assert (everything.json()["config"]["data"], everything.json()["config"]["software"]) == (
            ["a.csv", "b.csv"],
            ["samtools"],
        )

    def test_a_conversation_may_be_made_with_all_of_what_was_given_named_one_by_one(self, client: TestClient) -> None:
        client.post("/api/own/data/files", params={"name": "a.csv", "description": "A"}, content=CSV)
        client.post("/api/own/data/files", params={"name": "b.csv", "description": "B"}, content=CSV)

        response = client.post("/api/chats", json={"team": [], "data": ["b.csv", "a.csv"]})

        assert response.status_code == 201
        assert response.json()["config"]["data"] == ["b.csv", "a.csv"]

    def test_a_conversation_cannot_be_made_with_what_was_not_given(self, client: TestClient) -> None:
        response = client.post("/api/chats", json={"team": [], "data": ["x.csv"]})

        assert response.status_code == 422
        assert "x.csv" in response.json()["error"]["message"]
