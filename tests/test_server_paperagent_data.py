"""Tests of the data a PaperAgent's paper used: the places that are found to fetch it from, which are only ever listed
until a person chooses files and agrees to their size, the job that fetches them, what is kept and how it was checked,
what stands in for data that is the person's own, and what the agent's other operations do while data is fetched and
after. The internet is replaced by the stand-in of test_paperagents_datahosts, so what is looked at here is what the
server does with the real way of asking each place."""

import io
import json
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

import pytest
import test_paperagents_datahosts as hosts
import test_server_paperagent_repository as repository
from conftest import FakeClient
from fastapi.testclient import TestClient
from test_paperagents_datahosts import Web, md5, sha256, zenodo
from test_paperagents_reading import ReadDataset, ReadLink, queue, reading
from test_server_paperagent_repository import (
    LOCAL,
    SIZE,
    URL,
    Remote,
    agent_of,
    directory_of,
    fetch,
    finish,
    project,
    refused,
)

from virtual_lab.paperagents import data as finding
from virtual_lab.paperagents.anchors import document_from
from virtual_lab.paperagents.reading import plan_chunks
from virtual_lab.server import paperagent_data as kept_data
from virtual_lab.server import paperagents as module
from virtual_lab.server.jobs import Job, Jobs
from virtual_lab.server.own import Own
from virtual_lab.server.paperagents import DATA_JOB, PaperAgents, steps_of
from virtual_lab.server.workspace import Workspace

# What the tests of fetching code and of the internet are made with, which are fixtures of those modules
web = hosts.web
agents = repository.agents
client = repository.client
jobs = repository.jobs
marker = repository.marker
remote = repository.remote
workspace = repository.workspace
git_is_installed = repository.git_is_installed
model_client = repository.model_client

REFERENCE = "https://zenodo.org/records/1234567"
BASE = "https://zenodo.org/api/records/1234567"
COUNTS = b"gene,score\n" + b"TP53,0.91\n" * 300
NOTES = b"Read the counts first.\n"
FILES = {"counts.csv": COUNTS, "notes.txt": NOTES}

GEO = "The hippocampus sequencing data are available in GEO under accession GSE123456."
ZENODO = "The processed counts are deposited at https://zenodo.org/records/1234567."
ARRAY = "The expression profiles are in ArrayExpress under accession E-MTAB-1234."
OWNED = "A cortex atlas was also made from samples of the authors' own."
PAPER = "\n\n".join(
    [
        "CellMapper: mapping cell types",
        "Abstract",
        "We present CellMapper, a method for mapping cell types in single-nucleus RNA-seq data.",
        "Methods",
        OWNED,
        "Data availability",
        GEO,
        ZENODO,
        ARRAY,
    ]
)
DATASETS = [
    ReadDataset(name="hippocampus sequencing data", accession="GSE123456", quote=GEO),
    ReadDataset(name="expression profiles", accession="E-MTAB-1234", quote=ARRAY),
    ReadDataset(name="cortex atlas", accession="", quote=OWNED),
]
LINKS = [ReadLink(url=REFERENCE, role="data", quote=ZENODO)]
CSV = b"gene,score\nTP53,0.91\nBRCA1,0.20\n"


@pytest.fixture(autouse=True)
def room(monkeypatch: pytest.MonkeyPatch) -> None:
    """The disk that the tests run on is not what they are of, so none of it is held back from them."""
    monkeypatch.setattr(module, "DISK_RESERVE_BYTES", 0)


@pytest.fixture
def hosted(web: Web) -> Web:
    zenodo(web, FILES)

    return web


@pytest.fixture
def read(agents: PaperAgents, fake_client: FakeClient) -> str:
    """An agent whose paper has been read, as a good model would, for the data it says it used."""
    agent_id = agent_of(agents)
    agents.put_paper(agent_id, "paper.txt", io.BytesIO(PAPER.encode("utf-8")))
    document = document_from([PAPER], paged=False)
    answers = []
    seen: set[str] = set()
    for chunk in plan_chunks(document, SIZE, 0):
        if chunk.skip:
            continue
        datasets = [item for item in DATASETS if item.quote in chunk.text]
        links = [item for item in LINKS if item.quote in chunk.text]
        seen.update(item.quote for item in [*datasets, *links])
        answers.append(reading(datasets=datasets, links=links))
    assert seen == {item.quote for item in [*DATASETS, *LINKS]}, "a quote falls between chunks"
    queue(fake_client, *answers)
    job = finish(agents.read(agent_id, 5))
    assert job.state == "succeeded", job.error

    return agent_id


def content_url(name: str) -> str:
    return f"{BASE}/files/{urllib.parse.quote(name)}/content"


def contents_asked(web: Web) -> list[str]:
    """The files that were fetched, as opposed to the lists of them."""
    return [url for _, url in web.asked if url.endswith("/content")]


def keeps(workspace: Workspace, agent_id: str) -> dict[str, bytes]:
    """What is in the data of an agent, by where it is."""
    root = directory_of(workspace, agent_id) / "data"

    return (
        {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}
        if root.is_dir()
        else {}
    )


def leftovers(workspace: Workspace) -> list[str]:
    """What is left in the workspace of what was fetched on the way."""
    return sorted(path.name for path in workspace.root.glob("paperagent.*"))


def shown(agents: PaperAgents, agent_id: str, *names: str, reference: str = REFERENCE) -> int:
    """What the files come to as a person is shown them, which is what they agree to."""
    listed = agents.data_files(agent_id, reference)

    return sum(file["bytes"] for file in listed["files"] if file["name"] in names)


def start(
    agents: PaperAgents,
    agent_id: str,
    *names: str,
    reference: str = REFERENCE,
    expected: int | None = None,
    megabytes: Any = None,
) -> Job:
    """What a person does: sees the files, chooses some, and agrees to what they come to."""
    agreed = shown(agents, agent_id, *names, reference=reference) if expected is None else expected

    return agents.download_data(agent_id, reference, list(names), agreed, megabytes)


def get(agents: PaperAgents, agent_id: str, *names: str, **options: Any) -> Job:
    return finish(start(agents, agent_id, *names, **options))


def step_of(agents: PaperAgents, agent_id: str) -> str:
    return steps_of(agents.lookup(agent_id)[1])["data"]


def step_shown(agents: PaperAgents, agent_id: str) -> str:
    """The step as the agent is shown, which says it is running while the files are fetched."""
    return str(agents.entry(agent_id, agents.lookup(agent_id)[1])["steps"]["data"])


class TestWhatThereIsToFetch:
    def test_an_agent_that_has_read_nothing_has_no_places_to_fetch_from_and_none_is_asked(
        self, agents: PaperAgents, web: Web
    ) -> None:
        found = agents.data(agent_of(agents))

        assert found["read"] is False and found["datasets"] == [] and found["candidates"] == []
        assert found["kept"] == {"files": 0, "bytes": 0, "sources": []}
        assert found["stand_ins"] == [] and found["own"] == [] and found["job"] is None
        assert [item["source"] for item in found["sources"]] == [
            "zenodo",
            "figshare",
            "dryad",
            "github",
            "huggingface",
            "geo",
            "ena",
        ]
        assert found["limits"] == {
            "default_megabytes": 500,
            "min_megabytes": 1,
            "max_megabytes": 20_000,
            "max_kept_megabytes": 50_000,
            "max_files": 100,
        }
        assert web.asked == []

    def test_what_the_paper_says_of_its_data_is_found_with_the_words_that_say_it(
        self, agents: PaperAgents, read: str, web: Web
    ) -> None:
        found = agents.data(read)

        by_key = {candidate["key"]: candidate for candidate in found["candidates"]}
        assert sorted(by_key) == ["accession:E-MTAB-1234", "geo:GSE123456", "zenodo:1234567"]
        geo, zenodo_record, array = by_key["geo:GSE123456"], by_key["zenodo:1234567"], by_key["accession:E-MTAB-1234"]
        assert (geo["supported"], geo["source"], geo["reference"]) == (True, "geo", "GSE123456")
        assert geo["facts"][0]["quote"] == GEO and geo["in_code"] is False
        assert zenodo_record["reference"] == "1234567" and zenodo_record["facts"][0]["quote"] == ZENODO
        assert array["supported"] is False and array["source"] is None and array["reason"]
        assert [candidate["supported"] for candidate in found["candidates"]] == [True, True, False]
        assert {dataset["name"]: dataset["candidate"] for dataset in found["datasets"]} == {
            "hippocampus sequencing data": "geo:GSE123456",
            "expression profiles": "accession:E-MTAB-1234",
            "cortex atlas": None,
        }
        assert found["read"] is True and all(dataset["stand_in"] is None for dataset in found["datasets"])
        assert web.asked == []
        json.dumps(found)

    def test_what_the_code_points_to_is_added_once_it_is_fetched(
        self, agents: PaperAgents, read: str, remote: Remote, marker: Path, web: Web
    ) -> None:
        remote.files = {
            **project(marker),
            "README.md": "# CellMapper\n\nData: https://zenodo.org/records/7654321 and GSE99999\n",
        }
        fetch(agents, read)

        found = agents.data(read)

        by_key = {candidate["key"]: candidate for candidate in found["candidates"]}
        assert by_key["zenodo:7654321"]["in_code"] is True and by_key["zenodo:7654321"]["facts"] == []
        assert by_key["geo:GSE99999"]["in_code"] is True
        assert by_key["zenodo:1234567"]["in_code"] is False
        assert web.asked == []

    def test_the_files_of_a_place_are_listed_without_any_being_fetched(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        listed = agents.data_files(read, REFERENCE)

        assert (listed["key"], listed["title"], listed["license"]) == (
            "zenodo:1234567",
            "Cell atlas",
            {"name": "cc-by-4.0", "url": None},
        )
        assert [(file["name"], file["bytes"], file["downloadable"], file["kept"]) for file in listed["files"]] == [
            ("counts.csv", len(COUNTS), True, False),
            ("notes.txt", len(NOTES), True, False),
        ]
        assert listed["files"][0]["checksum"] == {"algorithm": "md5", "value": md5(COUNTS)}
        assert listed["total_files"] == 2 and listed["truncated"] is False and listed["downloads"] is True
        assert hosted.asked == [("GET", BASE)] and contents_asked(hosted) == []
        assert keeps(workspace, read) == {} and step_of(agents, read) == "pending"

    def test_a_doi_is_listed_as_well_as_an_address(self, agents: PaperAgents, web: Web) -> None:
        zenodo(web, FILES)

        by_doi = agents.data_files(agent_of(agents), "10.5281/zenodo.1234567")

        assert by_doi["key"] == "zenodo:1234567" and [file["name"] for file in by_doi["files"]] == list(FILES)

    @pytest.mark.parametrize(
        "reference",
        [
            "https://evil.example.org/records/1",
            "https://example.org/data.csv",
            "https://zenodo.org.evil.example/records/1",
            "E-MTAB-1234",
            "EGAD00001000001",
            "not a place",
            "",
            5,
            None,
        ],
    )
    def test_a_place_that_is_not_on_the_approved_list_is_refused_and_not_asked(
        self, agents: PaperAgents, web: Web, reference: Any
    ) -> None:
        agent_id = agent_of(agents)

        error = refused(agents.data_files, agent_id, reference)

        assert error.status == 422 and error.code in ("invalid", "unsupported", "refused")
        assert web.asked == []
        assert refused(agents.download_data, agent_id, reference, ["a"], 1).status == 422
        assert web.asked == []

    @pytest.mark.parametrize(
        "address", ["https://user:pass@zenodo.org/records/5", "ftp://zenodo.org/records/5", "zenodo.org/records/5"]
    )
    def test_an_address_only_says_which_place_and_what_is_asked_is_the_place_s_own_address_without_what_it_carried(
        self, agents: PaperAgents, web: Web, address: str
    ) -> None:
        web.json("https://zenodo.org/api/records/5", {"metadata": {"title": "Five"}, "files": []})

        agents.data_files(agent_of(agents), address)

        assert web.asked == [("GET", "https://zenodo.org/api/records/5")]
        assert all("Authorization" not in headers and "Cookie" not in headers for headers in web.headers)

    def test_a_place_that_sends_the_request_on_to_a_host_outside_the_list_is_refused(
        self, agents: PaperAgents, web: Web
    ) -> None:
        web.redirect(BASE, "https://evil.example.org/records/1234567")

        error = refused(agents.data_files, agent_of(agents), REFERENCE)

        assert error.status == 422 and error.code == "refused" and "evil.example.org" in error.message
        assert web.hosts == {"zenodo.org"}

    @pytest.mark.parametrize(("status", "code", "answer"), [(404, "missing", 404), (500, "unreachable", 502)])
    def test_a_place_that_cannot_be_had_from_says_so(
        self, agents: PaperAgents, web: Web, status: int, code: str, answer: int
    ) -> None:
        web.add(BASE, b"", status)

        error = refused(agents.data_files, agent_of(agents), REFERENCE)

        assert (error.status, error.code) == (answer, code)

    def test_an_agent_that_is_not_there_is_not_found(self, agents: PaperAgents, web: Web) -> None:
        assert refused(agents.data, "nothing").status == 404
        assert refused(agents.data_files, "nothing", REFERENCE).status == 404
        assert refused(agents.download_data, "nothing", REFERENCE, ["a"], 0).status == 404
        assert refused(agents.clear_data, "nothing").status == 404
        assert web.asked == []


class TestFetching:
    def test_nothing_is_fetched_until_files_are_chosen_and_their_size_is_agreed_to(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace, jobs: Jobs
    ) -> None:
        agents.data(read)
        agents.data_files(read, REFERENCE)
        agents.data_files(read, REFERENCE)

        assert contents_asked(hosted) == [] and keeps(workspace, read) == {} and jobs.active() == []
        assert refused(agents.download_data, read, REFERENCE, [], 0).status == 422
        assert refused(agents.download_data, read, REFERENCE, ["counts.csv"], None).status == 422
        assert refused(agents.download_data, read, REFERENCE, "counts.csv", len(COUNTS)).status == 422
        assert refused(agents.download_data, read, REFERENCE, [3], len(COUNTS)).status == 422
        assert contents_asked(hosted) == [] and keeps(workspace, read) == {}

    def test_the_chosen_files_are_fetched_as_a_job_and_kept_with_where_they_came_from(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        started = start(agents, read, "counts.csv")
        assert (started.kind, started.subject, started.title) == (DATA_JOB, read, "Fetching data: CellMapper")
        job = finish(started)

        assert job.state == "succeeded", job.error
        assert job.message is not None and job.message.startswith("Kept 1 file, ")
        assert "data/zenodo/1234567/" in job.message and "matched the checksum that the place gave" in job.message
        assert keeps(workspace, read) == {"zenodo/1234567/counts.csv": COUNTS}
        assert contents_asked(hosted) == [content_url("counts.csv")]
        found = agents.data(read)
        assert found["kept"]["files"] == 1 and found["kept"]["bytes"] == len(COUNTS)
        (source,) = found["kept"]["sources"]
        assert (source["key"], source["label"], source["url"], source["folder"]) == (
            "zenodo:1234567",
            "Zenodo record 1234567",
            REFERENCE,
            "zenodo/1234567",
        )
        assert (source["title"], source["license"]) == ("Cell atlas", {"name": "cc-by-4.0", "url": None})
        (file,) = source["files"]
        assert (file["name"], file["path"], file["bytes"], file["present"]) == (
            "counts.csv",
            "zenodo/1234567/counts.csv",
            len(COUNTS),
            True,
        )
        assert file["sha256"] == sha256(COUNTS) and file["checksum"] == {"algorithm": "md5", "value": md5(COUNTS)}
        assert file["url"] == content_url("counts.csv") and file["fetched_at"]
        assert step_of(agents, read) == "done"
        assert [item["fetched"] for item in found["candidates"] if item["key"] == "zenodo:1234567"] == [1]
        assert agents.data_files(read, REFERENCE)["files"][0]["kept"] is True

    def test_the_totals_that_are_shown_are_the_bytes_that_were_written(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        listed = agents.data_files(read, REFERENCE)
        shown_total = sum(file["bytes"] for file in listed["files"])

        job = get(agents, read, "counts.csv", "notes.txt")

        written = keeps(workspace, read)
        assert sorted(written) == ["zenodo/1234567/counts.csv", "zenodo/1234567/notes.txt"]
        assert shown_total == sum(len(body) for body in written.values()) == len(COUNTS) + len(NOTES)
        assert job.progress["bytes_total"] == job.progress["bytes_done"] == shown_total
        assert (job.progress["files_total"], job.progress["files_done"]) == (2, 2)
        assert agents.data(read)["kept"]["bytes"] == shown_total

    def test_what_is_fetched_is_what_the_place_says_now_and_not_what_was_shown(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        agreed = shown(agents, read, "counts.csv")
        zenodo(hosted, {"counts.csv": COUNTS + b"TP53,0.91\n", "notes.txt": NOTES})

        error = refused(agents.download_data, read, REFERENCE, ["counts.csv"], agreed)

        assert error.status == 409 and error.code == "changed" and "Look at them again" in error.message
        assert contents_asked(hosted) == [] and keeps(workspace, read) == {}

    @pytest.mark.parametrize("expected", [0, 1, len(COUNTS) - 1, len(COUNTS) + 1, len(COUNTS) + len(NOTES)])
    def test_a_size_that_is_not_the_size_of_the_files_is_not_agreed_to(
        self, agents: PaperAgents, read: str, hosted: Web, expected: int
    ) -> None:
        error = refused(agents.download_data, read, REFERENCE, ["counts.csv"], expected)

        assert error.status == 409 and error.code == "changed" and contents_asked(hosted) == []

    @pytest.mark.parametrize("expected", ["10", -1, 1.5, True, [], None, 10**12])
    def test_a_size_that_is_not_a_size_is_refused(
        self, agents: PaperAgents, read: str, hosted: Web, expected: Any
    ) -> None:
        assert refused(agents.download_data, read, REFERENCE, ["counts.csv"], expected).status == 422
        assert contents_asked(hosted) == []

    def test_more_than_the_limit_is_refused_before_anything_is_fetched(
        self, agents: PaperAgents, read: str, web: Web, workspace: Workspace
    ) -> None:
        big = b"x" * (2 * finding.MEGABYTE)
        zenodo(web, {"big.bin": big, "small.txt": NOTES})

        error = refused(agents.download_data, read, REFERENCE, ["big.bin"], len(big), 1)

        assert error.status == 422 and error.code == "too_big" and "more than the 1,048,576" in error.message
        assert contents_asked(web) == [] and keeps(workspace, read) == {}
        # The same files are fetched with the room for them, and a file within the limit is fetched with it
        assert get(agents, read, "small.txt", megabytes=1).state == "succeeded"
        assert get(agents, read, "big.bin", megabytes=2).state == "succeeded"
        assert keeps(workspace, read)["zenodo/1234567/big.bin"] == big

    @pytest.mark.parametrize("megabytes", [0, -1, 20_001, "5", 5.5, True, []])
    def test_a_limit_that_is_not_one_is_refused(
        self, agents: PaperAgents, read: str, hosted: Web, megabytes: Any
    ) -> None:
        assert refused(agents.download_data, read, REFERENCE, ["notes.txt"], len(NOTES), megabytes).status == 422
        assert contents_asked(hosted) == []

    def test_with_no_limit_said_what_may_be_fetched_is_the_default(
        self, agents: PaperAgents, read: str, web: Web
    ) -> None:
        size = (finding.DEFAULT_MEGABYTES + 1) * finding.MEGABYTE
        web.json(
            BASE,
            {
                "metadata": {"title": "Huge"},
                "files": [{"key": "huge.bin", "size": size, "links": {"self": content_url("huge.bin")}}],
            },
        )

        error = refused(agents.download_data, read, REFERENCE, ["huge.bin"], size)

        assert error.code == "too_big" and contents_asked(web) == []

    def test_files_that_are_kept_already_are_not_fetched_again(
        self, agents: PaperAgents, read: str, hosted: Web
    ) -> None:
        get(agents, read, "counts.csv")

        error = refused(agents.download_data, read, REFERENCE, ["counts.csv", "notes.txt"], len(COUNTS) + len(NOTES))

        assert error.status == 409 and error.code == "kept" and "Remove it first" in error.message
        assert contents_asked(hosted) == [content_url("counts.csv")]
        assert get(agents, read, "notes.txt").state == "succeeded"
        assert agents.data(read)["kept"]["files"] == 2

    @pytest.mark.parametrize("names", [["missing.csv"], ["counts.csv", "counts.csv.gz"], [""]])
    def test_a_file_that_the_place_does_not_have_is_refused(
        self, agents: PaperAgents, read: str, hosted: Web, names: list[str]
    ) -> None:
        error = refused(agents.download_data, read, REFERENCE, names, 0)

        assert error.status == 422 and error.code == "invalid" and contents_asked(hosted) == []

    def test_a_file_at_a_host_that_the_place_may_not_send_to_is_not_fetched(
        self, agents: PaperAgents, read: str, web: Web
    ) -> None:
        web.json(
            BASE,
            {
                "metadata": {"title": "Cell atlas"},
                "files": [
                    {"key": "counts.csv", "size": 5, "links": {"self": "https://evil.example.org/counts.csv"}},
                    {"key": "notes.txt", "size": 5, "links": {"self": "https://zenodo.org/a/notes.txt"}},
                ],
            },
        )
        listed = agents.data_files(read, REFERENCE)
        assert [(file["name"], file["downloadable"]) for file in listed["files"]] == [
            ("counts.csv", False),
            ("notes.txt", True),
        ]
        assert "not at a host" in listed["files"][0]["why"]

        error = refused(agents.download_data, read, REFERENCE, ["counts.csv"], 5)

        assert error.status == 422 and error.code == "refused" and "not at a host" in error.message
        assert "evil.example.org" not in web.hosts

    def test_a_file_that_is_sent_on_to_a_host_outside_the_list_is_not_kept(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        hosted.redirect(content_url("notes.txt"), "https://evil.example.org/notes.txt")

        job = get(agents, read, "notes.txt")

        assert job.state == "failed" and job.error is not None and "evil.example.org" in job.error
        assert "evil.example.org" not in hosted.hosts
        assert keeps(workspace, read) == {} and agents.data(read)["kept"]["files"] == 0
        assert step_of(agents, read) == "failed" and leftovers(workspace) == []

    def test_a_corrupt_file_is_caught_by_its_checksum_and_is_not_kept(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        corrupt = bytes([COUNTS[0] ^ 1]) + COUNTS[1:]
        hosted.add(content_url("counts.csv"), corrupt)

        job = get(agents, read, "counts.csv")

        assert job.state == "failed" and job.error is not None
        assert "counts.csv" in job.error and "not what Zenodo says it is" in job.error
        assert md5(corrupt) in job.error and md5(COUNTS) in job.error and "discarded" in job.error
        assert keeps(workspace, read) == {} and leftovers(workspace) == []
        assert agents.data(read)["kept"]["files"] == 0 and step_of(agents, read) == "failed"
        assert not (directory_of(workspace, read) / "data" / "zenodo" / "1234567" / "counts.csv").exists()

    def test_a_file_that_is_cut_short_is_not_kept(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        hosted.add(content_url("counts.csv"), COUNTS[:-10])

        job = get(agents, read, "counts.csv")

        assert job.state == "failed" and job.error is not None and "counts.csv" in job.error
        assert keeps(workspace, read) == {} and agents.data(read)["kept"]["files"] == 0

    def test_one_bad_file_does_not_take_the_good_ones_with_it_and_is_said(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        hosted.add(content_url("counts.csv"), bytes([COUNTS[0] ^ 1]) + COUNTS[1:])

        job = get(agents, read, "counts.csv", "notes.txt")

        assert job.state == "failed" and job.error is not None
        assert job.error.startswith("1 of 2 files were kept, and 1 were not. counts.csv:")
        assert keeps(workspace, read) == {"zenodo/1234567/notes.txt": NOTES}
        found = agents.data(read)
        assert found["kept"]["files"] == 1 and found["kept"]["bytes"] == len(NOTES)
        assert job.progress["bytes_done"] == len(NOTES) and step_of(agents, read) == "done"
        assert any(line.startswith("Not kept: ") for line in job.snapshot(0)["log"]["lines"])

    def test_a_file_with_no_checksum_is_kept_if_it_is_the_size_said_and_says_it_was_checked_by_size_only(
        self, agents: PaperAgents, read: str, web: Web, workspace: Workspace
    ) -> None:
        web.json(
            BASE,
            {
                "metadata": {"title": "Cell atlas"},
                "files": [{"key": "notes.txt", "size": len(NOTES), "links": {"self": content_url("notes.txt")}}],
            },
        )
        web.add(content_url("notes.txt"), NOTES)

        job = get(agents, read, "notes.txt")

        assert job.state == "succeeded" and job.message is not None
        assert "checked against their size only" in job.message and "matched the checksum" not in job.message
        (file,) = agents.data(read)["kept"]["sources"][0]["files"]
        assert file["checksum"] is None and file["sha256"] == sha256(NOTES)
        assert keeps(workspace, read) == {"zenodo/1234567/notes.txt": NOTES}

    def test_a_file_that_is_bigger_than_the_place_said_is_not_kept(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        hosted.add(content_url("counts.csv"), COUNTS + b"more", content_length=False)

        job = get(agents, read, "counts.csv")

        assert job.state == "failed" and job.error is not None and "more than the" in job.error
        assert keeps(workspace, read) == {} and leftovers(workspace) == []

    def test_a_name_that_would_leave_the_folder_is_not_fetched(
        self, agents: PaperAgents, read: str, web: Web, workspace: Workspace
    ) -> None:
        names = ["../escape.txt", "/abs.txt", ".hidden", "a/../b.txt", "back\\slash.txt", "x" * 400]
        web.json(
            BASE,
            {
                "metadata": {"title": "Cell atlas"},
                "files": [
                    {"key": name, "size": 3, "links": {"self": f"{BASE}/files/{index}/content"}}
                    for index, name in enumerate(names)
                ],
            },
        )

        listed = agents.data_files(read, REFERENCE)

        assert all(not file["downloadable"] for file in listed["files"])
        for name in names:
            assert refused(agents.download_data, read, REFERENCE, [name], 3).status == 422
        assert contents_asked(web) == [] and not (workspace.root / "escape.txt").exists()

    def test_a_file_whose_place_is_taken_by_a_folder_is_not_kept_and_is_said_not_to_be(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        (directory_of(workspace, read) / "data" / "zenodo" / "1234567" / "counts.csv").mkdir(parents=True)

        job = get(agents, read, "counts.csv")

        assert job.state == "failed" and job.error is not None and "a folder is where it would be" in job.error
        assert keeps(workspace, read) == {} and leftovers(workspace) == []
        assert agents.data(read)["kept"]["files"] == 0

    def test_a_file_that_differs_only_in_capitals_from_one_that_is_kept_is_not_fetched(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        assert get(agents, read, "counts.csv").state == "succeeded"
        zenodo(hosted, {"counts.csv": COUNTS, "Counts.csv": CSV})
        asked = len(contents_asked(hosted))

        error = refused(agents.download_data, read, REFERENCE, ["Counts.csv"], len(CSV))

        assert error.status == 422 and "differ only in their capital letters" in error.message
        assert len(contents_asked(hosted)) == asked and keeps(workspace, read) == {"zenodo/1234567/counts.csv": COUNTS}

    def test_progress_is_told_as_bytes_arrive(self, agents: PaperAgents, read: str, web: Web) -> None:
        body = b"x" * (3 * 65_536)
        zenodo(web, {"big.bin": body})
        seen: list[tuple[int, int, str | None]] = []

        def between() -> None:
            running = agents.downloading(read)
            assert running is not None
            progress = running.snapshot()["progress"]
            seen.append((progress["bytes_done"], progress["bytes_total"], progress["current"]))

        web.add(content_url("big.bin"), body, between=between)

        job = get(agents, read, "big.bin")

        assert job.state == "succeeded"
        assert seen == [(65_536, len(body), "big.bin"), (2 * 65_536, len(body), "big.bin")]
        assert job.progress["bytes_done"] == len(body)

    def test_a_fetch_that_is_stopped_keeps_nothing_of_the_file_it_was_in(
        self, agents: PaperAgents, read: str, web: Web, workspace: Workspace, jobs: Jobs
    ) -> None:
        body = b"x" * (3 * 65_536)
        zenodo(web, {"big.bin": body})
        reached = threading.Event()

        def between() -> None:
            reached.set()
            time.sleep(0.05)

        web.add(content_url("big.bin"), body, between=between)
        job = start(agents, read, "big.bin")
        assert reached.wait(10)

        jobs.stop(job.id)
        finish(job)

        assert job.state == "stopped"
        assert keeps(workspace, read) == {} and leftovers(workspace) == []
        assert agents.data(read)["kept"]["files"] == 0 and step_of(agents, read) == "pending"

    def test_a_stop_between_files_keeps_the_ones_that_were_done(
        self, agents: PaperAgents, read: str, web: Web, workspace: Workspace, jobs: Jobs
    ) -> None:
        body = b"x" * (3 * 65_536)
        zenodo(web, {"a.bin": NOTES, "b.bin": body})
        reached = threading.Event()

        def between() -> None:
            reached.set()
            time.sleep(0.05)

        web.add(content_url("b.bin"), body, between=between)
        job = start(agents, read, "a.bin", "b.bin")
        assert reached.wait(10)

        jobs.stop(job.id)
        finish(job)

        assert job.state == "stopped"
        assert keeps(workspace, read) == {"zenodo/1234567/a.bin": NOTES}
        assert step_of(agents, read) == "done"

    def test_there_is_no_starting_without_the_room(
        self, agents: PaperAgents, read: str, hosted: Web, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(module, "DISK_RESERVE_BYTES", 1 << 60)

        error = refused(agents.download_data, read, REFERENCE, ["notes.txt"], len(NOTES))

        assert error.status == 409 and error.code == "disk_full" and "is free on this machine" in error.message
        assert contents_asked(hosted) == []

    def test_an_agent_keeps_no_more_than_it_may(
        self, agents: PaperAgents, read: str, hosted: Web, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(finding, "MAX_KEPT_MEGABYTES", 0)

        error = refused(agents.download_data, read, REFERENCE, ["notes.txt"], len(NOTES))

        assert error.status == 409 and error.code == "too_big" and "Remove some first" in error.message
        assert contents_asked(hosted) == []

    def test_the_files_of_another_place_are_not_written_over_by_one_that_has_the_same_folder(
        self, agents: PaperAgents
    ) -> None:
        kept = finding.Reference("huggingface", "a/b")
        record = kept_data.with_file(
            kept_data.empty(),
            kept,
            kept.label,
            "A",
            None,
            {
                "name": "x.csv",
                "path": f"{finding.folder_of(kept)}/x.csv",
                "bytes": 1,
                "sha256": "0" * 64,
                "checksum": None,
                "url": "https://huggingface.co/x",
                "fetched_at": "2025-01-01T00:00:00Z",
            },
        )
        other = finding.Reference("huggingface", "a_b")

        assert finding.folder_of(kept) == finding.folder_of(other) and kept.key != other.key
        error = refused(agents.check_room, record, other, 1)
        assert error.status == 409 and error.code == "exists"
        agents.check_room(record, kept, 1)


class TestWhileDataIsFetched:
    def hold(self, web: Web) -> tuple[threading.Event, threading.Event]:
        """Has the file be slow to arrive, until it is let go."""
        reached, release = threading.Event(), threading.Event()
        body = b"x" * (3 * 65_536)
        zenodo(web, {"big.bin": body, "other.txt": NOTES})

        def between() -> None:
            reached.set()
            release.wait(20)

        web.add(content_url("big.bin"), body, between=between)

        return reached, release

    def test_the_agent_cannot_be_worked_on_until_the_files_are_fetched(
        self, agents: PaperAgents, read: str, web: Web, workspace: Workspace, remote: Remote
    ) -> None:
        reached, release = self.hold(web)
        job = start(agents, read, "big.bin")
        try:
            assert reached.wait(10)

            assert agents.downloading(read) is job
            assert steps_of(agents.lookup(read)[1])["data"] == "pending"
            assert agents.data(read)["job"]["id"] == job.id
            assert step_shown(agents, read) == "running"
            for call, arguments in [
                (agents.download_data, (read, REFERENCE, ["other.txt"], len(NOTES))),
                (agents.fetch_repository, (read,)),
                (agents.clear_data, (read,)),
                (agents.clear_repository, (read,)),
                (agents.clear_reading, (read,)),
                (agents.remove_paper, (read,)),
                (agents.delete, (read,)),
                (agents.put_paper, (read, "paper.txt", io.BytesIO(b"x"))),
            ]:
                error = refused(call, *arguments)
                assert error.status == 409 and error.code == "busy", call
            assert directory_of(workspace, read).is_dir()
        finally:
            release.set()
        finish(job)

        assert job.state == "succeeded" and agents.downloading(read) is None
        assert step_shown(agents, read) == "done"

    def test_what_else_is_going_on_with_the_agent_keeps_data_from_being_fetched(
        self, agents: PaperAgents, read: str, hosted: Web, remote: Remote
    ) -> None:
        remote.gate = threading.Event()
        cloning = agents.fetch_repository(read)
        try:
            error = refused(agents.download_data, read, REFERENCE, ["notes.txt"], len(NOTES))
            assert error.status == 409 and error.code == "busy" and contents_asked(hosted) == []
        finally:
            remote.gate.set()
        finish(cloning)

        assert get(agents, read, "notes.txt").state == "succeeded"

    def test_two_agents_fetch_at_the_same_time(
        self, agents: PaperAgents, read: str, web: Web, workspace: Workspace
    ) -> None:
        reached, release = self.hold(web)
        other = agents.create("Other", {"kind": "doi", "doi": "10.1038/s41586-020-2649-3"}, None)
        job = start(agents, read, "big.bin")
        try:
            assert reached.wait(10)

            quick = get(agents, other, "other.txt")
        finally:
            release.set()
        finish(job)

        assert quick.state == "succeeded" and keeps(workspace, other) == {"zenodo/1234567/other.txt": NOTES}


class TestWhatIsKept:
    def test_the_files_of_one_place_are_taken_away_with_what_is_said_of_them(
        self, agents: PaperAgents, read: str, web: Web, workspace: Workspace
    ) -> None:
        zenodo(web, FILES)
        zenodo(web, {"table.tsv": b"a\tb\n"}, record=7654321)
        get(agents, read, "counts.csv", "notes.txt")
        get(agents, read, "table.tsv", reference="https://zenodo.org/records/7654321")
        assert sorted(keeps(workspace, read)) == [
            "zenodo/1234567/counts.csv",
            "zenodo/1234567/notes.txt",
            "zenodo/7654321/table.tsv",
        ]

        agents.clear_data(read, "zenodo:1234567")

        assert sorted(keeps(workspace, read)) == ["zenodo/7654321/table.tsv"]
        found = agents.data(read)
        assert [source["key"] for source in found["kept"]["sources"]] == ["zenodo:7654321"]
        assert found["kept"]["files"] == 1 and step_of(agents, read) == "done"
        assert not (directory_of(workspace, read) / "data" / "zenodo" / "1234567").exists()

    def test_all_the_files_are_taken_away_and_the_step_is_not_done_again(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        get(agents, read, "counts.csv", "notes.txt")

        agents.clear_data(read)

        assert keeps(workspace, read) == {} and not (directory_of(workspace, read) / "data").exists()
        assert agents.data(read)["kept"] == {"files": 0, "bytes": 0, "sources": []}
        assert step_of(agents, read) == "pending"
        # What was fetched is fetched again if it is asked for again
        assert get(agents, read, "counts.csv").state == "succeeded"

    def test_data_that_stands_in_is_left_when_the_files_are_taken_away(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        Own(workspace, 10_000).add_upload("counts.csv", io.BytesIO(CSV), "Read counts")
        agents.set_stand_in(read, "cortex atlas", "counts.csv")
        get(agents, read, "counts.csv")

        agents.clear_data(read)

        assert [stand_in["own"] for stand_in in agents.data(read)["stand_ins"]] == ["counts.csv"]
        assert step_of(agents, read) == "done"

    def test_there_is_nothing_to_take_away_of_a_place_that_was_not_fetched(
        self, agents: PaperAgents, read: str, hosted: Web
    ) -> None:
        get(agents, read, "notes.txt")

        for source in ("zenodo:999", "", "../..", 5):
            assert refused(agents.clear_data, read, source).status == 404
        assert agents.data(read)["kept"]["files"] == 1

    def test_a_file_that_was_taken_away_by_hand_is_said_to_be_gone(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        get(agents, read, "counts.csv", "notes.txt")
        root = directory_of(workspace, read) / "data" / "zenodo" / "1234567"
        (root / "notes.txt").unlink()
        (root / "counts.csv").write_bytes(b"changed")

        files = {file["name"]: file["present"] for file in agents.data(read)["kept"]["sources"][0]["files"]}

        assert files == {"counts.csv": False, "notes.txt": False}

    def test_what_is_kept_is_the_same_after_the_server_is_started_again(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace, jobs: Jobs
    ) -> None:
        get(agents, read, "counts.csv")
        before = agents.data(read)["kept"]

        again = PaperAgents(workspace, 100_000, jobs, lambda model: [])

        assert again.data(read)["kept"] == before

    @pytest.mark.parametrize(
        ("damage", "left"),
        [
            (lambda record: record["sources"][0]["files"][0].update(path="../../escape.txt"), 0),
            (
                lambda record: record["sources"][0]["files"][0].update(
                    name="../escape.txt", path="zenodo/1234567/../escape.txt"
                ),
                0,
            ),
            (lambda record: record["sources"][0].update(folder="../escape"), 0),
            (lambda record: record["sources"][0].update(source="evil", key="evil:1"), 0),
            (lambda record: record["sources"][0]["files"][0].update(sha256="short"), 0),
            (lambda record: record["sources"][0]["files"][0].update(bytes=-1), 0),
            (lambda record: record["sources"][0]["files"][0].update(checksum={"algorithm": "crc", "value": "x"}), 0),
            (lambda record: record["sources"].append("text"), 1),
        ],
    )
    def test_a_record_edited_by_hand_that_says_what_is_not_fit_is_not_believed(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace, damage: Any, left: int
    ) -> None:
        get(agents, read, "counts.csv")
        path = directory_of(workspace, read) / kept_data.RECORD_FILE
        record = json.loads(path.read_text())
        damage(record)
        path.write_text(json.dumps(record))

        found = agents.data(read)

        assert found["kept"]["files"] == left
        assert not (workspace.root / "escape.txt").exists()
        agents.clear_data(read)
        assert keeps(workspace, read) == {}

    @pytest.mark.parametrize(
        "content", ["", "not json", "[]", '{"schema": 2, "sources": []}', '{"schema": 1, "sources": 3}']
    )
    def test_a_record_that_is_not_one_gives_nothing_and_does_not_stop_the_agent_from_being_shown(
        self, agents: PaperAgents, read: str, workspace: Workspace, content: str
    ) -> None:
        (directory_of(workspace, read) / kept_data.RECORD_FILE).write_text(content)

        found = agents.data(read)

        assert found["kept"] == {"files": 0, "bytes": 0, "sources": []} and found["stand_ins"] == []

    def test_deleting_the_agent_deletes_what_was_fetched_for_it(
        self, agents: PaperAgents, read: str, hosted: Web, workspace: Workspace
    ) -> None:
        get(agents, read, "counts.csv")
        directory = directory_of(workspace, read)
        assert (directory / "data").is_dir() and (directory / kept_data.RECORD_FILE).is_file()

        agents.delete(read)

        assert not directory.exists()

    def test_a_download_that_comes_after_the_agent_was_deleted_is_not_kept(
        self, agents: PaperAgents, read: str, web: Web, workspace: Workspace, jobs: Jobs
    ) -> None:
        reached, release = threading.Event(), threading.Event()
        body = b"x" * (3 * 65_536)
        zenodo(web, {"big.bin": body})

        def between() -> None:
            reached.set()
            release.wait(20)

        web.add(content_url("big.bin"), body, between=between)
        job = start(agents, read, "big.bin")
        try:
            assert reached.wait(10)
            assert refused(agents.delete, read).status == 409
        finally:
            release.set()
        finish(job)
        agents.delete(read)

        assert not directory_of(workspace, read).exists() and leftovers(workspace) == []


class TestStandIns:
    def own(self, workspace: Workspace, name: str = "counts.csv", content: bytes = CSV) -> None:
        Own(workspace, 10_000).add_upload(name, io.BytesIO(content), "Read counts")

    def test_data_of_the_person_s_own_stands_in_for_a_dataset_of_the_paper_without_being_copied(
        self, agents: PaperAgents, read: str, workspace: Workspace, web: Web
    ) -> None:
        self.own(workspace)
        key = next(dataset["key"] for dataset in agents.data(read)["datasets"] if dataset["name"] == "cortex atlas")
        before = sorted(path.name for path in workspace.own_data_dir.iterdir())

        agents.set_stand_in(read, key, "counts.csv")

        found = agents.data(read)
        (stand_in,) = found["stand_ins"]
        assert (stand_in["key"], stand_in["name"], stand_in["own"]) == (key, "cortex atlas", "counts.csv")
        assert stand_in["own_data"]["name"] == "counts.csv" and stand_in["own_data"]["bytes"] == len(CSV)
        assert [item["name"] for item in found["own"]] == ["counts.csv"]
        assert {dataset["name"]: (dataset["stand_in"] or {}).get("own") for dataset in found["datasets"]} == {
            "hippocampus sequencing data": None,
            "expression profiles": None,
            "cortex atlas": "counts.csv",
        }
        assert keeps(workspace, read) == {} and not (directory_of(workspace, read) / "data").exists()
        assert sorted(path.name for path in workspace.own_data_dir.iterdir()) == before
        assert found["kept"]["files"] == 0 and step_of(agents, read) == "done" and web.asked == []

    def test_a_stand_in_can_be_changed_and_taken_away(
        self, agents: PaperAgents, read: str, workspace: Workspace
    ) -> None:
        self.own(workspace)
        self.own(workspace, "other.csv")
        key = next(dataset["key"] for dataset in agents.data(read)["datasets"] if dataset["name"] == "cortex atlas")
        agents.set_stand_in(read, key, "counts.csv")

        agents.set_stand_in(read, key, "other.csv")

        assert [stand_in["own"] for stand_in in agents.data(read)["stand_ins"]] == ["other.csv"]
        agents.clear_stand_in(read, key)
        assert agents.data(read)["stand_ins"] == [] and step_of(agents, read) == "pending"
        assert refused(agents.clear_stand_in, read, key).status == 404

    def test_a_dataset_that_the_paper_does_not_name_can_have_a_stand_in_by_what_it_is_called(
        self, agents: PaperAgents, read: str, workspace: Workspace
    ) -> None:
        self.own(workspace)

        agents.set_stand_in(read, "  Spatial   Atlas ", "counts.csv")
        agents.set_stand_in(read, "spatial atlas", "counts.csv")

        (stand_in,) = agents.data(read)["stand_ins"]
        assert (stand_in["key"], stand_in["name"]) == ("name:spatial atlas", "spatial atlas")
        agents.clear_stand_in(read, "name:spatial atlas")
        assert agents.data(read)["stand_ins"] == []

    def test_data_that_is_not_the_person_s_cannot_stand_in(
        self, agents: PaperAgents, read: str, workspace: Workspace
    ) -> None:
        self.own(workspace)

        for own in ("missing.csv", "", "../counts.csv", 5, None):
            error = refused(agents.set_stand_in, read, "cortex atlas", own)
            assert error.status == 422 and error.code == "no_data"
        assert agents.data(read)["stand_ins"] == []

    @pytest.mark.parametrize("dataset", ["", "   ", "x" * 201, "a\x00b", "a\nb", 5, None, ["a"]])
    def test_a_dataset_that_is_not_named_fit_is_refused(
        self, agents: PaperAgents, read: str, workspace: Workspace, dataset: Any
    ) -> None:
        self.own(workspace)

        assert refused(agents.set_stand_in, read, dataset, "counts.csv").status == 422
        assert agents.data(read)["stand_ins"] == []

    def test_no_more_than_the_most_can_stand_in(self, agents: PaperAgents, read: str, workspace: Workspace) -> None:
        self.own(workspace)
        for number in range(kept_data.MAX_STAND_INS):
            agents.set_stand_in(read, f"dataset {number}", "counts.csv")

        error = refused(agents.set_stand_in, read, "one more", "counts.csv")

        assert error.status == 409 and error.code == "too_many"
        agents.set_stand_in(read, "dataset 0", "counts.csv")

    def test_a_stand_in_whose_data_is_gone_is_shown_without_it(
        self, agents: PaperAgents, read: str, workspace: Workspace
    ) -> None:
        self.own(workspace)
        agents.set_stand_in(read, "cortex atlas", "counts.csv")
        Own(workspace, 10_000).remove("counts.csv")

        (stand_in,) = agents.data(read)["stand_ins"]

        assert stand_in["own"] == "counts.csv" and stand_in["own_data"] is None

    def test_a_stand_in_cannot_be_set_for_an_agent_that_is_not_there(
        self, agents: PaperAgents, workspace: Workspace
    ) -> None:
        self.own(workspace)

        assert refused(agents.set_stand_in, "nothing", "x", "counts.csv").status == 404
        assert refused(agents.clear_stand_in, "nothing", "x").status == 404


class TestTheApi:
    def make(self, client: TestClient) -> str:
        made = client.post(
            "/api/paperagents",
            json={"title": "CellMapper", "paper": {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}, "repo": URL},
        )
        assert made.status_code == 201
        agent_id: str = made.json()["id"]

        return agent_id

    def wait_for(self, client: TestClient, job: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + 20
        while (state := client.get(f"/api/setup/jobs/{job['id']}").json())["state"] == "running":
            assert time.monotonic() < deadline
            time.sleep(0.02)

        return dict(state)

    def test_data_is_listed_chosen_fetched_and_removed(
        self, client: TestClient, hosted: Web, workspace: Workspace
    ) -> None:
        agent_id = self.make(client)
        before = client.get(f"/api/paperagents/{agent_id}/data")
        assert before.status_code == 200 and before.json()["kept"]["files"] == 0

        listed = client.get(f"/api/paperagents/{agent_id}/data/files", params={"reference": REFERENCE})
        assert listed.status_code == 200
        names = [file["name"] for file in listed.json()["files"]]
        assert names == ["counts.csv", "notes.txt"] and contents_asked(hosted) == []

        started = client.post(
            f"/api/paperagents/{agent_id}/data",
            json={"reference": REFERENCE, "files": names, "expected_bytes": len(COUNTS) + len(NOTES)},
        )

        assert started.status_code == 202
        job = started.json()
        assert (job["kind"], job["subject"]) == (DATA_JOB, agent_id)
        assert self.wait_for(client, job)["state"] == "succeeded"
        found = client.get(f"/api/paperagents/{agent_id}/data").json()
        assert found["kept"]["files"] == 2 and found["kept"]["bytes"] == len(COUNTS) + len(NOTES)
        assert client.get(f"/api/paperagents/{agent_id}").json()["steps"]["data"] == "done"
        assert sorted(keeps(workspace, agent_id)) == ["zenodo/1234567/counts.csv", "zenodo/1234567/notes.txt"]

        one = client.delete(f"/api/paperagents/{agent_id}/data", params={"source": "zenodo:1234567"})

        assert one.status_code == 200 and one.json()["kept"]["files"] == 0
        assert client.get(f"/api/paperagents/{agent_id}").json()["steps"]["data"] == "pending"
        assert keeps(workspace, agent_id) == {}
        assert (
            client.delete(f"/api/paperagents/{agent_id}/data", params={"source": "zenodo:1234567"}).status_code == 404
        )
        assert client.delete(f"/api/paperagents/{agent_id}/data").status_code == 200

    def test_a_corrupt_file_is_a_failed_job_that_says_why(self, client: TestClient, hosted: Web) -> None:
        agent_id = self.make(client)
        hosted.add(content_url("notes.txt"), b"x" * len(NOTES))

        started = client.post(
            f"/api/paperagents/{agent_id}/data",
            json={"reference": REFERENCE, "files": ["notes.txt"], "expected_bytes": len(NOTES), "max_megabytes": 5},
        )
        done = self.wait_for(client, started.json())

        assert done["state"] == "failed" and "not what Zenodo says it is" in done["error"]
        assert client.get(f"/api/paperagents/{agent_id}").json()["steps"]["data"] == "failed"

    def test_stand_ins_are_set_and_taken_away(self, client: TestClient, workspace: Workspace) -> None:
        agent_id = self.make(client)
        Own(workspace, 10_000).add_upload("counts.csv", io.BytesIO(CSV), "Read counts")

        put = client.put(f"/api/paperagents/{agent_id}/data/stand-ins", json={"dataset": "Atlas", "own": "counts.csv"})

        assert put.status_code == 200 and put.json()["stand_ins"][0]["own"] == "counts.csv"
        assert client.get(f"/api/paperagents/{agent_id}").json()["steps"]["data"] == "done"
        gone = client.delete(f"/api/paperagents/{agent_id}/data/stand-ins", params={"dataset": "name:atlas"})
        assert gone.status_code == 200 and gone.json()["stand_ins"] == []
        assert (
            client.delete(f"/api/paperagents/{agent_id}/data/stand-ins", params={"dataset": "name:atlas"}).status_code
            == 404
        )
        missing = client.put(f"/api/paperagents/{agent_id}/data/stand-ins", json={"dataset": "Atlas", "own": "no.csv"})
        assert missing.status_code == 422 and missing.json()["error"]["code"] == "no_data"

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"reference": REFERENCE},
            {"reference": REFERENCE, "files": ["a"]},
            {"reference": REFERENCE, "files": "a", "expected_bytes": 1},
            {"reference": REFERENCE, "files": ["a"], "expected_bytes": "1"},
            {"reference": REFERENCE, "files": ["a"], "expected_bytes": 1, "max_megabytes": 0},
            {"reference": REFERENCE, "files": ["a"], "expected_bytes": 1, "max_megabytes": 20_001},
            {"reference": REFERENCE, "files": ["a"], "expected_bytes": 1, "more": 1},
            {"reference": "x" * 501, "files": ["a"], "expected_bytes": 1},
            {"reference": REFERENCE, "files": ["a"] * 1001, "expected_bytes": 1},
            {"reference": REFERENCE, "files": ["x" * 2001], "expected_bytes": 1},
        ],
    )
    def test_what_is_not_fit_to_ask_for_is_refused_and_nothing_is_asked_of_any_host(
        self, client: TestClient, web: Web, body: dict[str, Any]
    ) -> None:
        agent_id = self.make(client)

        assert client.post(f"/api/paperagents/{agent_id}/data", json=body).status_code == 422
        assert web.asked == []

    def test_what_is_not_fit_to_ask_the_places_of_is_refused(self, client: TestClient, web: Web) -> None:
        agent_id = self.make(client)

        assert client.get(f"/api/paperagents/{agent_id}/data/files").status_code == 422
        assert client.get(f"/api/paperagents/{agent_id}/data/files", params={"reference": "x" * 501}).status_code == 422
        assert (
            client.get(f"/api/paperagents/{agent_id}/data/files", params={"reference": "https://evil.example.org/a"})
        ).status_code == 422
        assert client.put(f"/api/paperagents/{agent_id}/data/stand-ins", json={"dataset": "a"}).status_code == 422
        assert client.delete(f"/api/paperagents/{agent_id}/data/stand-ins").status_code == 422
        assert web.asked == []

    def test_an_agent_that_is_not_there_is_not_found(self, client: TestClient, web: Web) -> None:
        body = {"reference": REFERENCE, "files": ["a"], "expected_bytes": 1}

        assert client.get("/api/paperagents/nothing/data").status_code == 404
        assert client.get("/api/paperagents/nothing/data/files", params={"reference": REFERENCE}).status_code == 404
        assert client.post("/api/paperagents/nothing/data", json=body).status_code == 404
        assert client.delete("/api/paperagents/nothing/data").status_code == 404
        assert (
            client.put("/api/paperagents/nothing/data/stand-ins", json={"dataset": "a", "own": "b"}).status_code == 404
        )
        assert web.asked == []

    def test_the_data_of_an_agent_is_not_given_to_a_request_without_the_token(
        self, client: TestClient, web: Web
    ) -> None:
        agent_id = self.make(client)
        unsigned = TestClient(client.app, base_url=LOCAL)
        body = {"reference": REFERENCE, "files": ["a"], "expected_bytes": 1}

        assert unsigned.get(f"/api/paperagents/{agent_id}/data").status_code == 401
        assert (
            unsigned.get(f"/api/paperagents/{agent_id}/data/files", params={"reference": REFERENCE}).status_code == 401
        )
        assert unsigned.post(f"/api/paperagents/{agent_id}/data", json=body).status_code == 401
        assert unsigned.delete(f"/api/paperagents/{agent_id}/data").status_code == 401
        assert (
            unsigned.put(f"/api/paperagents/{agent_id}/data/stand-ins", json={"dataset": "a", "own": "b"}).status_code
            == 401
        )
        assert (
            unsigned.delete(f"/api/paperagents/{agent_id}/data/stand-ins", params={"dataset": "a"}).status_code == 401
        )
        assert web.asked == []
