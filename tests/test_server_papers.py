"""Tests of the runs that read papers: making one, uploading papers to it, reading them as a job, and what is found."""

import io
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MODEL, FakeClient
from fastapi.testclient import TestClient
from test_papers import DESEQ, queue

from virtual_lab.paper_batch import Paper
from virtual_lab.server import papers as papers_module
from virtual_lab.server.app import create_app
from virtual_lab.server.errors import ApiError
from virtual_lab.server.jobs import Job, Jobs
from virtual_lab.server.papers import LAB_FILE, MAX_RUN_FILES, Papers, check_source
from virtual_lab.server.workspace import Settings, Workspace

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}

LIMIT = 1024
TEXT = b"Differential expression was found with DESeq2, from samples in GEO, aligned with STAR."
TASK = "RNA-seq differential expression with DESeq2"


@pytest.fixture(autouse=True)
def model_client(fake_client: FakeClient) -> FakeClient:
    return fake_client


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    store = Workspace(tmp_path / "workspace")
    store.save_settings(Settings(model=TEST_MODEL, max_cost=None))

    return store


@pytest.fixture
def jobs() -> Iterator[Jobs]:
    kept = Jobs()
    yield kept
    kept.close()


@pytest.fixture
def papers(workspace: Workspace, jobs: Jobs) -> Papers:
    return Papers(workspace, jobs, LIMIT, lambda model: [])


@pytest.fixture
def client(workspace: Workspace) -> Iterator[TestClient]:
    app = create_app(workspace.root, token=TOKEN, check_keys=False, max_upload_bytes=LIMIT)
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


def refused(call: Any, *args: Any, **kwargs: Any) -> ApiError:
    with pytest.raises(ApiError) as caught:
        call(*args, **kwargs)

    return caught.value


def finish(job: Job, seconds: float = 20) -> Job:
    deadline = time.monotonic() + seconds
    while job.active:
        assert time.monotonic() < deadline, "the job did not finish"
        time.sleep(0.01)

    return job


def upload(papers: Papers, run: str, name: str = "a.txt", content: bytes = TEXT) -> None:
    papers.add_file(run, name, io.BytesIO(content))


def uploaded_run(papers: Papers, *names: str, title: str = "Gene papers") -> str:
    run = papers.create(title, {"kind": "files"})
    for name in names:
        upload(papers, run, name)

    return run


def read(papers: Papers, run: str, **options: Any) -> Job:
    options = {"max_cost": 5, "max_cost_per_paper": None, "retry_failed": False, **options}

    return finish(papers.read(run, **options))


class TestMakingARun:
    def test_a_run_is_named_by_its_title_and_a_number_if_that_is_taken(self, papers: Papers) -> None:
        assert papers.create("Gene papers", {"kind": "files"}) == "gene-papers"
        assert papers.create("  Gene   papers ", {"kind": "files"}) == "gene-papers-2"
        assert papers.create("Gene papers", {"kind": "files"}) == "gene-papers-3"

    def test_runs_are_listed_with_the_latest_first_and_what_a_page_needs_to_make_one(self, papers: Papers) -> None:
        first = papers.create("First", {"kind": "files"})
        second = papers.create("Second", {"kind": "files"})

        described = papers.describe()

        assert [run["id"] for run in described["runs"]] == [second, first]
        assert described["runs"][0] == {
            "id": second,
            "title": "Second",
            "source": {"kind": "files"},
            "created_at": described["runs"][0]["created_at"],
            "files": 0,
            "papers": 0,
            "finished": 0,
            "read": None,
            "unavailable": None,
            "failed": None,
            "spent": None,
            "stopped": None,
            "function_count": 0,
            "given": False,
            "job": None,
            "job_kind": None,
        }
        assert "neuroscience" in described["subjects"]
        assert described["max_paper_bytes"] == LIMIT
        assert described["max_files"] == MAX_RUN_FILES
        assert ".pdf" in described["suffixes"] and ".txt" in described["suffixes"]

    def test_nothing_is_listed_before_a_run_is_made(self, papers: Papers) -> None:
        assert papers.describe()["runs"] == []

    @pytest.mark.parametrize("title", ["", "   ", "a" * 201, "bell\x07"])
    def test_a_title_that_cannot_name_a_run_is_refused(self, papers: Papers, title: str) -> None:
        error = refused(papers.create, title, {"kind": "files"})

        assert (error.status, error.code) == (422, "invalid")

    def test_nothing_is_left_when_the_source_is_refused(self, papers: Papers, workspace: Workspace) -> None:
        refused(papers.create, "Bad", {"kind": "somewhere"})

        assert papers.describe()["runs"] == []
        assert not workspace.papers_dir.exists() or not any(workspace.papers_dir.iterdir())

    def test_no_more_runs_are_made_than_may_be_kept(self, papers: Papers, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(papers_module, "MAX_RUNS", 2)
        papers.create("One", {"kind": "files"})
        papers.create("Two", {"kind": "files"})

        error = refused(papers.create, "Three", {"kind": "files"})

        assert (error.status, error.code) == (409, "too_many")

    def test_a_run_whose_file_was_edited_into_nonsense_is_left_out_and_not_found(
        self, papers: Papers, workspace: Workspace
    ) -> None:
        good = papers.create("Good", {"kind": "files"})
        bad = papers.create("Bad", {"kind": "files"})
        (workspace.papers_dir / bad / LAB_FILE).write_text(json.dumps({"title": 5}))
        (workspace.papers_dir / "Not-A-Run").mkdir()

        assert [run["id"] for run in papers.describe()["runs"]] == [good]
        assert refused(papers.view, bad).status == 404

    @pytest.mark.parametrize("run", ["..", "a/b", "Gene-papers", "nothing-here", "-x"])
    def test_an_id_that_is_not_a_run_is_not_found(self, papers: Papers, run: str) -> None:
        assert (refused(papers.view, run).status, refused(papers.delete, run).status) == (404, 404)


class TestWhereThePapersComeFrom:
    def test_a_folder_is_a_full_path_with_papers_in_it(self, papers: Papers, tmp_path: Path) -> None:
        folder = tmp_path / "mine"
        folder.mkdir()
        (folder / "a.txt").write_text("text")

        source = check_source({"kind": "folder", "path": f" {folder} ", "recursive": True})

        assert source == {"kind": "folder", "path": str(folder), "recursive": True}
        assert check_source({"kind": "folder", "path": str(folder)})["recursive"] is False

    @pytest.mark.parametrize("path", [None, "", "relative/folder", "bad\nname", 5])
    def test_a_path_that_is_not_in_full_is_refused(self, path: Any) -> None:
        assert refused(check_source, {"kind": "folder", "path": path}).status == 422

    def test_a_folder_that_is_not_there_or_has_no_papers_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        (tmp_path / "pictures").mkdir()
        (tmp_path / "pictures" / "a.png").write_text("x")

        assert "There is no folder" in refused(check_source, {"kind": "folder", "path": str(tmp_path / "no")}).message
        assert "no papers" in refused(check_source, {"kind": "folder", "path": str(tmp_path / "empty")}).message
        assert "no papers" in refused(check_source, {"kind": "folder", "path": str(tmp_path / "pictures")}).message

    def test_a_papers_in_a_folder_inside_it_are_found_only_if_asked_for(self, tmp_path: Path) -> None:
        (tmp_path / "inside").mkdir()
        (tmp_path / "inside" / "a.txt").write_text("text")

        assert refused(check_source, {"kind": "folder", "path": str(tmp_path)}).status == 422
        assert check_source({"kind": "folder", "path": str(tmp_path), "recursive": True})["recursive"] is True

    def test_biorxiv_is_a_period_a_subject_and_how_many(self) -> None:
        source = check_source(
            {
                "kind": "biorxiv",
                "since": "2024-01-01",
                "until": "2024-02-01",
                "subject": " Neuroscience ",
                "limit": 20,
                "random": True,
                "include_unpublished": True,
            }
        )

        assert source == {
            "kind": "biorxiv",
            "since": "2024-01-01",
            "until": "2024-02-01",
            "subject": "neuroscience",
            "limit": 20,
            "random": True,
            "include_unpublished": True,
        }

    def test_what_is_left_out_of_biorxiv_is_what_the_library_takes_when_it_is_left_out(self) -> None:
        assert check_source({"kind": "biorxiv", "since": "2024-01-01"}) == {
            "kind": "biorxiv",
            "since": "2024-01-01",
            "until": None,
            "subject": "all",
            "limit": 10,
            "random": False,
            "include_unpublished": False,
        }

    @pytest.mark.parametrize(
        "changes",
        [
            {"since": None},
            {"since": "01/02/2024"},
            {"since": "2024-13-01"},
            {"since": "20240101"},
            {"until": "2023-12-31"},
            {"until": "tomorrow"},
            {"subject": "astrology"},
            {"subject": 5},
            {"limit": 0},
            {"limit": 501},
            {"limit": True},
            {"limit": "10"},
            {"random": "yes"},
            {"include_unpublished": 1},
        ],
    )
    def test_a_period_subject_or_choice_that_is_wrong_is_refused(self, changes: dict[str, Any]) -> None:
        source = {"kind": "biorxiv", "since": "2024-01-01", **changes}

        assert refused(check_source, {key: value for key, value in source.items() if value is not None}).status == 422

    @pytest.mark.parametrize(
        "source",
        [
            {"kind": "files", "path": "/tmp"},
            {"kind": "folder", "path": "/tmp", "limit": 5},
            {"kind": "biorxiv", "since": "2024-01-01", "path": "/tmp"},
            {"kind": "unknown"},
            {},
        ],
    )
    def test_what_is_not_for_the_kind_of_source_is_refused_rather_than_ignored(self, source: dict[str, Any]) -> None:
        assert refused(check_source, source).status == 422


class TestUploadingPapers:
    def test_a_paper_is_kept_and_listed_with_its_size(self, papers: Papers) -> None:
        run = papers.create("Gene papers", {"kind": "files"})

        upload(papers, run, "folder\\Deseq paper.txt")

        view = papers.view(run)
        assert view["uploads"] == [{"name": "Deseq paper.txt", "bytes": len(TEXT)}]
        assert view["files"] == 1 and view["papers"] == 1
        assert [(row["title"], row["status"]) for row in view["results"]] == [("Deseq paper", "pending")]

    def test_only_what_the_library_reads_is_kept(self, papers: Papers) -> None:
        run = papers.create("Gene papers", {"kind": "files"})

        for name in ["table.csv", "image.png", "notes", ".txt"]:
            assert refused(upload, papers, run, name).status == 422
        for name in ["a.PDF", "b.md", "c.tex", "d.text", "e.markdown"]:
            upload(papers, run, name)

        assert [item["name"] for item in papers.view(run)["uploads"]] == [
            "a.PDF",
            "b.md",
            "c.tex",
            "d.text",
            "e.markdown",
        ]

    def test_a_name_that_is_taken_is_refused_whatever_its_case(self, papers: Papers) -> None:
        run = uploaded_run(papers, "a.txt")

        error = refused(upload, papers, run, "A.TXT", b"other")

        assert (error.status, error.code) == (409, "name_taken")
        assert papers.view(run)["uploads"] == [{"name": "a.txt", "bytes": len(TEXT)}]

    def test_a_paper_that_is_too_big_is_refused_and_leaves_nothing(self, papers: Papers, workspace: Workspace) -> None:
        run = papers.create("Gene papers", {"kind": "files"})

        error = refused(upload, papers, run, "big.txt", b"x" * (LIMIT + 1))

        assert (error.status, error.code) == (413, "too_large")
        assert papers.view(run)["uploads"] == []
        assert not list((workspace.papers_dir / run / "files").glob("*"))
        upload(papers, run, "exact.txt", b"x" * LIMIT)

    def test_no_more_papers_are_kept_than_a_run_may_have(self, papers: Papers, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(papers_module, "MAX_RUN_FILES", 2)
        run = uploaded_run(papers, "a.txt", "b.txt")

        error = refused(upload, papers, run, "c.txt")

        assert (error.status, error.code) == (409, "too_many")

    def test_papers_are_not_uploaded_to_a_run_whose_papers_come_from_elsewhere(
        self, papers: Papers, tmp_path: Path
    ) -> None:
        (tmp_path / "a.txt").write_text("text")
        run = papers.create("Folder", {"kind": "folder", "path": str(tmp_path)})

        assert refused(upload, papers, run).status == 409

    def test_a_paper_is_taken_away_by_its_name_and_only_those_uploaded(
        self, papers: Papers, workspace: Workspace
    ) -> None:
        run = uploaded_run(papers, "a.txt", "b.txt")

        papers.remove_file(run, "a.txt")

        assert [item["name"] for item in papers.view(run)["uploads"]] == ["b.txt"]
        for name in ["a.txt", "../lab.json", "..", "files", "nothing.txt"]:
            assert refused(papers.remove_file, run, name).status == 404
        assert (workspace.papers_dir / run / LAB_FILE).is_file()

    def test_papers_are_not_changed_while_the_run_is_being_read(self, papers: Papers, jobs: Jobs) -> None:
        run = uploaded_run(papers, "a.txt")
        release = threading.Event()
        jobs.start("papers", run, "Reading papers: Gene papers", lambda job: release.wait(10) and None)
        try:
            for call in (
                lambda: upload(papers, run, "b.txt"),
                lambda: papers.remove_file(run, "a.txt"),
                lambda: papers.delete(run),
            ):
                error = refused(call)
                assert (error.status, error.code) == (409, "busy")
        finally:
            release.set()


class TestReading:
    def test_the_papers_are_read_as_a_job_and_what_they_share_is_counted(
        self, papers: Papers, fake_client: FakeClient
    ) -> None:
        run = uploaded_run(papers, "a.txt", "b.txt")
        queue(fake_client, *[DESEQ] * 20)

        job = papers.read(run, 5, None, False)
        assert (job.kind, job.subject, job.title) == ("papers", run, "Reading papers: Gene papers")
        assert papers.running(run) is job or not job.active
        finish(job)

        assert job.state == "succeeded"
        assert job.message.startswith("Read 2 of 2 papers, spending $")
        assert job.progress["papers"] == 2 and job.progress["finished"] == 2
        assert any(line.startswith("Paper 1 of 2") for line in job.snapshot(0)["log"]["lines"])
        view = papers.view(run)
        assert [
            (row["title"], row["status"], row["tasks"], row["databases"], row["software"]) for row in view["results"]
        ] == [
            ("a", "read", 1, 1, 1),
            ("b", "read", 1, 1, 1),
        ]
        assert all(row["cost"] > 0 and row["error"] is None for row in view["results"])
        assert view["summary"]["papers"] == 2
        assert view["summary"]["tasks"] == [{"name": TASK, "papers": 2}]
        assert view["summary"]["databases"] == [{"name": "GEO", "papers": 2}]
        assert view["summary"]["software"] == [{"name": "STAR", "papers": 2}]
        assert view["summary"]["more"] == {"tasks": 0, "databases": 0, "software": 0}
        assert (view["read"], view["unavailable"], view["failed"], view["finished"], view["stopped"]) == (
            2,
            0,
            0,
            2,
            None,
        )
        assert view["spent"] > 0 and view["job"] is None

    def test_reading_again_reads_only_the_papers_that_have_not_been_read(
        self, papers: Papers, fake_client: FakeClient
    ) -> None:
        run = uploaded_run(papers, "a.txt")
        queue(fake_client, *[DESEQ] * 20)
        read(papers, run)
        used = len(fake_client.completions.parse_calls)
        upload(papers, run, "b.txt", b"A second paper about DESeq2.")

        job = read(papers, run)

        assert job.message.startswith("Read 2 of 2 papers")
        assert len(fake_client.completions.parse_calls) == used * 2
        assert [row["status"] for row in papers.view(run)["results"]] == ["read", "read"]

    def test_a_paper_that_has_no_text_is_said_to_be_unavailable_and_the_rest_are_read(
        self, papers: Papers, fake_client: FakeClient
    ) -> None:
        run = uploaded_run(papers, "a.txt")
        upload(papers, run, "b.pdf", b"not really a pdf")
        queue(fake_client, *[DESEQ] * 20)

        job = read(papers, run)

        rows = {row["title"]: row for row in papers.view(run)["results"]}
        assert rows["a"]["status"] == "read" and rows["b"]["status"] in {"unavailable", "failed"}
        assert rows["b"]["error"]
        assert "1 of 2" in job.message or "Read 1 of 2" in job.message

    def test_a_run_of_a_folder_reads_what_is_in_it_and_lists_what_is_not_yet_read(
        self, papers: Papers, tmp_path: Path, fake_client: FakeClient
    ) -> None:
        folder = tmp_path / "mine"
        folder.mkdir()
        (folder / "a.txt").write_bytes(TEXT)
        run = papers.create("Folder", {"kind": "folder", "path": str(folder)})
        assert [(row["title"], row["status"]) for row in papers.view(run)["results"]] == [("a", "pending")]
        queue(fake_client, *[DESEQ] * 10)

        read(papers, run)

        assert [row["status"] for row in papers.view(run)["results"]] == ["read"]

    def test_a_paper_read_that_is_no_longer_asked_for_is_still_listed(
        self, papers: Papers, fake_client: FakeClient
    ) -> None:
        run = uploaded_run(papers, "a.txt")
        queue(fake_client, *[DESEQ] * 10)
        read(papers, run)

        papers.remove_file(run, "a.txt")

        assert [(row["title"], row["status"]) for row in papers.view(run)["results"]] == [("a", "read")]

    def test_bioRxiv_is_listed_when_the_reading_begins_with_the_choices_that_were_made(
        self, papers: Papers, tmp_path: Path, fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        text = tmp_path / "preprint.txt"
        text.write_bytes(TEXT)
        listed: list[dict[str, Any]] = []

        def listing(since: str, until: str | None, **options: Any) -> list[Paper]:
            listed.append({"since": since, "until": until, **options})

            return [Paper(key="10.1101_x", title="A preprint", doi="10.1101/x", path=text)]

        monkeypatch.setattr(papers_module, "biorxiv_papers", listing)
        run = papers.create(
            "Brain",
            {"kind": "biorxiv", "since": "2024-01-01", "until": "2024-02-01", "subject": "neuroscience", "limit": 3},
        )
        queue(fake_client, *[DESEQ] * 10)
        assert listed == []

        job = read(papers, run)

        assert listed == [
            {
                "since": "2024-01-01",
                "until": "2024-02-01",
                "subject": "neuroscience",
                "limit": 3,
                "published_only": True,
                "random_sample": False,
                "max_pages": papers_module.MAX_BIORXIV_PAGES,
            }
        ]
        assert job.state == "succeeded"
        assert [(row["title"], row["doi"], row["status"]) for row in papers.view(run)["results"]] == [
            ("A preprint", "10.1101/x", "read")
        ]

    def test_a_period_with_no_preprints_is_nothing_to_read_and_not_a_failure(
        self, papers: Papers, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(papers_module, "biorxiv_papers", lambda *args, **options: [])
        run = papers.create("Brain", {"kind": "biorxiv", "since": "2024-01-01"})

        job = read(papers, run)

        assert (job.state, job.message) == ("succeeded", "There are no papers to read.")

    def test_a_job_fails_with_what_went_wrong_when_the_papers_cannot_be_got(
        self, papers: Papers, tmp_path: Path
    ) -> None:
        folder = tmp_path / "mine"
        folder.mkdir()
        (folder / "a.txt").write_text("text")
        run = papers.create("Folder", {"kind": "folder", "path": str(folder)})
        (folder / "a.txt").unlink()
        folder.rmdir()

        job = read(papers, run)

        assert job.state == "failed" and "There is no directory of papers" in (job.error or "")

    def test_the_most_it_may_spend_stops_the_run_and_is_said(self, papers: Papers, fake_client: FakeClient) -> None:
        run = uploaded_run(papers, "a.txt", "b.txt")
        queue(fake_client, *[DESEQ] * 20)

        job = read(papers, run, max_cost=0)

        assert job.state == "succeeded" and "Stopped:" in job.message and "max_cost" in job.message
        view = papers.view(run)
        assert view["stopped"] and "max_cost" in view["stopped"]
        assert [row["status"] for row in view["results"]] == ["pending", "pending"]

    def test_a_request_to_stop_ends_the_reading_and_keeps_what_was_read(
        self, papers: Papers, fake_client: FakeClient
    ) -> None:
        run = uploaded_run(papers, "a.txt", "b.txt")
        queue(fake_client, *[DESEQ] * 20)
        started, release = threading.Event(), threading.Event()
        real = fake_client.completions.parse

        def slow(**kwargs: Any) -> Any:
            started.set()
            assert release.wait(10)

            return real(**kwargs)

        fake_client.completions.parse = slow

        job = papers.read(run, 5, None, False)
        assert started.wait(10)
        job.request_stop()
        release.set()
        finish(job)

        assert job.state == "stopped"
        assert job.message == "Stopped. What was read is kept, and reading again carries on from there."
        # The paper it was in is not saved as one that failed, so that it is read again
        assert [row["status"] for row in papers.view(run)["results"]] == ["pending", "pending"]
        fake_client.completions.parse = real
        assert read(papers, run).message.startswith("Read 2 of 2 papers")

    def test_a_run_is_not_read_twice_at_once_but_two_runs_can_be(self, papers: Papers, jobs: Jobs) -> None:
        first = uploaded_run(papers, "a.txt", title="First")
        second = uploaded_run(papers, "a.txt", title="Second")
        release = threading.Event()
        jobs.start(
            "papers", first, "Reading papers: First", lambda job: release.wait(10) and None, exclusive=f"papers:{first}"
        )
        try:
            error = refused(papers.read, first, 5, None, False)
            assert (error.status, error.code) == (409, "busy") and error.details["job"]["subject"] == first
            assert papers.describe()["runs"][1]["job"] is not None
            assert papers.view(second)["job"] is None
            assert papers.read(second, 5, None, False) is not None
        finally:
            release.set()

    def test_what_it_may_spend_must_be_said_and_be_an_amount(self, papers: Papers) -> None:
        run = uploaded_run(papers, "a.txt")

        for value in [None, -1, float("nan"), float("inf"), True, "5"]:
            assert refused(papers.read, run, value, None, False).status == 422
        for value in [-1, float("inf"), True, "5"]:
            assert refused(papers.read, run, 5, value, False).status == 422
        assert refused(papers.read, run, 5, None, "yes").status == 422

    def test_a_run_with_no_papers_uploaded_is_not_read(self, papers: Papers) -> None:
        run = papers.create("Gene papers", {"kind": "files"})

        error = refused(papers.read, run, 5, None, False)

        assert (error.status, "Upload the papers" in error.message) == (422, True)

    def test_a_model_whose_key_is_not_set_is_said_before_anything_is_spent(
        self, workspace: Workspace, jobs: Jobs
    ) -> None:
        papers = Papers(workspace, jobs, LIMIT, lambda model: ["OPENAI_API_KEY"])
        run = uploaded_run(papers, "a.txt")

        error = refused(papers.read, run, 5, None, False)

        assert (error.status, error.code, error.details["missing"]) == (422, "missing_keys", ["OPENAI_API_KEY"])
        assert TEST_MODEL in error.message and "OPENAI_API_KEY" in error.message

    def test_a_model_whose_price_is_not_known_is_said_since_the_limit_could_not_be_kept(
        self, workspace: Workspace, papers: Papers
    ) -> None:
        workspace.save_settings(Settings(model="a-model-nobody-priced"))
        run = uploaded_run(papers, "a.txt")

        error = refused(papers.read, run, 5, None, False)

        assert (error.status, error.code) == (422, "unavailable") and "a limit on spending" in error.message

    def test_a_run_is_not_carried_on_with_another_model_which_would_count_what_is_not_alike(
        self, workspace: Workspace, papers: Papers, fake_client: FakeClient
    ) -> None:
        run = uploaded_run(papers, "a.txt")
        queue(fake_client, *[DESEQ] * 10)
        read(papers, run)
        workspace.save_settings(Settings(model="gpt-5.2"))

        error = refused(papers.read, run, 5, None, False)

        assert (error.status, error.code) == (409, "different_model")
        assert TEST_MODEL in error.message and "gpt-5.2" in error.message

    def test_a_run_that_is_deleted_goes_with_everything_in_it(
        self, papers: Papers, workspace: Workspace, fake_client: FakeClient
    ) -> None:
        run = uploaded_run(papers, "a.txt")
        queue(fake_client, *[DESEQ] * 10)
        read(papers, run)

        papers.delete(run)

        assert not (workspace.papers_dir / run).exists()
        assert papers.describe()["runs"] == []

    def test_the_tables_are_the_librarys_and_only_those_that_were_written(
        self, papers: Papers, fake_client: FakeClient
    ) -> None:
        run = uploaded_run(papers, "a.txt")
        assert refused(papers.summary_file, run, "tasks").status == 404
        queue(fake_client, *[DESEQ] * 10)
        read(papers, run)

        path = papers.summary_file(run, "tasks")

        assert path.name == "tasks_summary.csv" and TASK in path.read_text()
        assert refused(papers.summary_file, run, "papers").status == 404
        assert refused(papers.summary_file, run, "../lab").status == 404

    def test_the_counts_a_page_is_shown_are_cut_to_the_most_common(
        self, papers: Papers, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(papers_module, "MAX_SUMMARY_ROWS", 2)
        run = papers.create("Gene papers", {"kind": "files"})
        counted = {"papers": 3, "tasks": {"a": 3, "b": 2, "c": 1}, "databases": {"d": 1}, "software": {}}
        (workspace.papers_dir / run / "frequency_summary.json").write_text(json.dumps(counted))

        summary = papers.view(run)["summary"]

        assert summary["tasks"] == [{"name": "a", "papers": 3}, {"name": "b", "papers": 2}]
        assert summary["more"] == {"tasks": 1, "databases": 0, "software": 0}

    def test_a_summary_file_with_nonsense_in_it_is_no_summary(self, papers: Papers, workspace: Workspace) -> None:
        run = papers.create("Gene papers", {"kind": "files"})
        (workspace.papers_dir / run / "frequency_summary.json").write_text(json.dumps({"papers": "x", "tasks": [1]}))

        assert papers.view(run)["summary"] == {
            "papers": 0,
            "tasks": [],
            "databases": [],
            "software": [],
            "more": {"tasks": 0, "databases": 0, "software": 0},
        }


class TestTheApi:
    def make(self, client: TestClient, title: str = "Gene papers", source: Any = None) -> dict[str, Any]:
        response = client.post("/api/papers/runs", json={"title": title, "source": source or {"kind": "files"}})
        assert response.status_code == 201, response.text

        return response.json()

    def send(self, client: TestClient, run: str, name: str = "a.txt", content: bytes = TEXT) -> Any:
        return client.post(f"/api/papers/runs/{run}/files", params={"name": name}, content=content)

    def test_the_runs_and_what_a_page_needs_are_listed(self, client: TestClient) -> None:
        assert client.get("/api/papers").json()["runs"] == []

        made = self.make(client)

        assert made["id"] == "gene-papers" and made["uploads"] == [] and made["results"] == []
        assert [run["id"] for run in client.get("/api/papers").json()["runs"]] == ["gene-papers"]
        assert client.get("/api/papers/runs/gene-papers").json() == made

    def test_papers_are_uploaded_as_the_body_and_taken_away(self, client: TestClient) -> None:
        run = self.make(client)["id"]

        sent = self.send(client, run, "deseq paper.txt")

        assert sent.status_code == 201
        assert sent.json()["uploads"] == [{"name": "deseq paper.txt", "bytes": len(TEXT)}]
        assert self.send(client, run, "deseq paper.txt").json()["error"]["code"] == "name_taken"
        assert self.send(client, run, "big.txt", b"x" * (LIMIT + 1)).status_code == 413
        assert self.send(client, run, "table.csv").status_code == 422

        removed = client.delete(f"/api/papers/runs/{run}/files/deseq paper.txt")

        assert removed.status_code == 200 and removed.json()["uploads"] == []
        assert client.delete(f"/api/papers/runs/{run}/files/deseq paper.txt").status_code == 404

    def test_a_paper_whose_size_is_said_to_be_too_big_is_refused_before_it_is_read(self, client: TestClient) -> None:
        run = self.make(client)["id"]

        response = client.post(
            f"/api/papers/runs/{run}/files", params={"name": "a.txt"}, content=b"x", headers={"Content-Length": "5000"}
        )

        assert response.status_code in {400, 413}

    def test_reading_is_a_job_that_the_setup_jobs_tell_of_as_well(
        self, client: TestClient, fake_client: FakeClient
    ) -> None:
        run = self.make(client)["id"]
        self.send(client, run)
        queue(fake_client, *[DESEQ] * 10)

        started = client.post(f"/api/papers/runs/{run}/read", json={"max_cost": 5})

        assert started.status_code == 202
        job = started.json()
        assert (job["kind"], job["subject"]) == ("papers", run)
        deadline = time.monotonic() + 20
        while client.get(f"/api/setup/jobs/{job['id']}").json()["state"] in {"running", "stopping"}:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert client.get(f"/api/setup/jobs/{job['id']}").json()["state"] == "succeeded"
        assert any(item["id"] == job["id"] for item in client.get("/api/setup/jobs").json()["jobs"])
        view = client.get(f"/api/papers/runs/{run}").json()
        assert view["results"][0]["status"] == "read"
        assert view["summary"]["tasks"] == [{"name": TASK, "papers": 1}]

        table = client.get(f"/api/papers/runs/{run}/tables/tasks")

        assert table.status_code == 200
        assert table.headers["content-disposition"].startswith("attachment")
        assert TASK in table.text

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"max_cost": -1},
            {"max_cost": "5"},
            {"max_cost": 5, "retry_failed": "true"},
            {"max_cost": 5, "max_cost_per_paper": -1},
            {"max_cost": 5, "other": 1},
        ],
    )
    def test_how_much_it_may_spend_is_always_said_and_nothing_else_is_taken(
        self, client: TestClient, body: dict[str, Any]
    ) -> None:
        run = self.make(client)["id"]
        self.send(client, run)

        response = client.post(f"/api/papers/runs/{run}/read", json=body)

        assert response.status_code == 422
        assert client.get("/api/setup/jobs").json()["jobs"] == []

    @pytest.mark.parametrize(
        "body",
        [
            {"title": "x"},
            {"source": {"kind": "files"}},
            {"title": "x", "source": {"kind": "files", "since": "2024-01-01"}},
            {"title": "x", "source": {"kind": "biorxiv", "since": "2024-01-01", "limit": "5"}},
            {"title": "x", "source": {"kind": "files"}, "other": 1},
        ],
    )
    def test_a_run_is_made_only_from_what_it_asks_for(self, client: TestClient, body: dict[str, Any]) -> None:
        assert client.post("/api/papers/runs", json=body).status_code == 422
        assert client.get("/api/papers").json()["runs"] == []

    def test_a_run_that_is_not_there_is_not_found_whatever_is_done_to_it(self, client: TestClient) -> None:
        for method, path in [
            ("get", "/api/papers/runs/nothing"),
            ("delete", "/api/papers/runs/nothing"),
            ("delete", "/api/papers/runs/nothing/files/a.txt"),
            ("get", "/api/papers/runs/nothing/tables/tasks"),
        ]:
            assert getattr(client, method)(path).status_code == 404
        assert client.post("/api/papers/runs/nothing/files", params={"name": "a.txt"}, content=b"x").status_code == 404
        assert client.post("/api/papers/runs/nothing/read", json={"max_cost": 1}).status_code == 404

    def test_a_run_is_deleted_and_the_runs_that_are_left_are_told(self, client: TestClient) -> None:
        self.make(client, "One")
        two = self.make(client, "Two")["id"]

        deleted = client.delete("/api/papers/runs/one")

        assert deleted.status_code == 200
        assert [run["id"] for run in deleted.json()["runs"]] == [two]

    def test_the_papers_are_not_reached_without_the_token(self, client: TestClient) -> None:
        bare = TestClient(client.app, base_url=LOCAL)

        assert bare.get("/api/papers").status_code == 401
