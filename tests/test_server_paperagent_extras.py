"""Tests of what comes with a PaperAgent's paper besides it: its supplementary files, which are kept beside it and read
with it; more addresses of its code, which are tried in turn when one cannot be fetched, with only one fetched; and
places for its data that the person adds, which are shown with those the paper names, and fetched from only as any
other is. Git and the internet are replaced by the stand-ins of the tests of fetching code and data."""

import hashlib
import io
import json
import threading
from pathlib import Path
from typing import Any

import pytest
import test_paperagents_datahosts as hosts
import test_server_paperagent_repository as repository
from conftest import FakeClient
from fastapi.testclient import TestClient
from test_paperagents_datahosts import Web, zenodo
from test_paperagents_reading import RESULT, ReadClaim, ReadLink, queue, reading
from test_papers import pdf_of
from test_server_paperagent_repository import (
    COMMIT,
    OTHER_URL,
    URL,
    Remote,
    agent_of,
    directory_of,
    fetch,
    finish,
    project,
    refused,
)

from virtual_lab.paperagents import repository as cloning
from virtual_lab.paperagents.anchors import document_from
from virtual_lab.paperagents.reading import plan_chunks
from virtual_lab.server import paperagent_data as kept_data
from virtual_lab.server import paperagent_reading as kept_reading
from virtual_lab.server import paperagent_supplementary as kept_supplementary
from virtual_lab.server.paperagents import AGENT_FILE, PAPER_DIR, PaperAgents, is_agent, steps_of
from virtual_lab.server.workspace import Workspace

agents = repository.agents
client = repository.client
jobs = repository.jobs
marker = repository.marker
remote = repository.remote
workspace = repository.workspace
git_is_installed = repository.git_is_installed
model_client = repository.model_client
web = hosts.web

THIRD_URL = "https://gitlab.com/example/cellmapper-mirror"
PAPER = "Abstract\n\nWe present CellMapper, a method for mapping cell types.\n\nResults\n\n" + RESULT
SUPPLEMENT = "Supplementary methods\n\nOn a second atlas of mouse cortex nuclei, CellMapper reached an AUROC of 0.81."
FOUND_IN = "The extended benchmark is at https://zenodo.org/records/7654321 for those who wish to see it."


def with_paper(agents: PaperAgents, text: str = PAPER) -> str:
    agent_id = agents.create("CellMapper", {"kind": "file"})
    agents.put_paper(agent_id, "paper.txt", io.BytesIO(text.encode("utf-8")))

    return agent_id


def supplement(agents: PaperAgents, agent_id: str, name: str = "notes.txt", text: str = SUPPLEMENT) -> None:
    agents.put_supplementary(agent_id, name, io.BytesIO(text.encode("utf-8")))


def read_through(agents: PaperAgents, agent_id: str, fake_client: FakeClient, *answers: Any) -> None:
    """Reads the paper with what a model says of each chunk, or with nothing found if it is not said."""
    directory = agents.lookup(agent_id)[0]
    count = sum(1 for chunk in plan_chunks(text_read(agents, agent_id), repository.SIZE, 0) if not chunk.skip)
    queue(fake_client, *(answers or [reading() for _ in range(count)]))
    job = finish(agents.read(agent_id, 5))
    assert job.state == "succeeded", job.error
    assert (directory / PAPER_DIR / kept_reading.TEXT_FILE).is_file()


def text_read(agents: PaperAgents, agent_id: str) -> Any:
    """The text that a reading of the agent's paper is of now, which is what its chunks are counted from."""
    directory, agent = agents.lookup(agent_id)
    pages = [(directory / PAPER_DIR / agent["paper"]["file"]["name"]).read_text(encoding="utf-8")]
    extras = [
        (item["name"], [(kept_supplementary.folder_of(directory) / item["name"]).read_text(encoding="utf-8")])
        for item in kept_supplementary.listed(agent)
    ]

    return kept_supplementary.document_with(pages, False, extras)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestSupplementaryFiles:
    def test_a_file_is_kept_beside_the_paper_and_listed_with_the_agent(
        self, agents: PaperAgents, workspace: Workspace
    ) -> None:
        agent_id = with_paper(agents)

        supplement(agents, agent_id)
        supplement(agents, agent_id, "tables.md", "| a | b |")

        assert agents.view(agent_id)["supplementary"] == [
            {"name": "notes.txt", "bytes": len(SUPPLEMENT), "sha256": digest(SUPPLEMENT)},
            {"name": "tables.md", "bytes": 9, "sha256": digest("| a | b |")},
        ]
        folder = directory_of(workspace, agent_id) / kept_supplementary.SUPPLEMENTARY_DIR
        assert sorted(path.name for path in folder.iterdir()) == ["notes.txt", "tables.md"]
        assert (folder / "notes.txt").read_text() == SUPPLEMENT
        assert agents.describe()["max_supplementary"] == kept_supplementary.MAX_FILES
        # The paper is where it was, and its folder has nothing else in it
        assert sorted(path.name for path in (directory_of(workspace, agent_id) / PAPER_DIR).iterdir()) == ["paper.txt"]

    def test_a_file_of_a_name_that_is_kept_takes_its_place_where_it_was(self, agents: PaperAgents) -> None:
        agent_id = with_paper(agents)
        supplement(agents, agent_id, "a.txt", "first")
        supplement(agents, agent_id, "b.txt", "second")

        supplement(agents, agent_id, "a.txt", "first, again")

        assert [(item["name"], item["sha256"]) for item in agents.view(agent_id)["supplementary"]] == [
            ("a.txt", digest("first, again")),
            ("b.txt", digest("second")),
        ]

    def test_a_name_in_another_case_is_the_same_file(self, agents: PaperAgents, workspace: Workspace) -> None:
        agent_id = with_paper(agents)
        supplement(agents, agent_id, "notes.txt", "first")
        supplement(agents, agent_id, "tables.md", "second")

        supplement(agents, agent_id, "NOTES.txt", "first, again")

        assert [(item["name"], item["sha256"]) for item in agents.view(agent_id)["supplementary"]] == [
            ("NOTES.txt", digest("first, again")),
            ("tables.md", digest("second")),
        ]
        folder = directory_of(workspace, agent_id) / kept_supplementary.SUPPLEMENTARY_DIR
        assert sorted(path.name for path in folder.iterdir()) == ["NOTES.txt", "tables.md"]
        assert (folder / "NOTES.txt").read_text() == "first, again"
        assert "first, again" in text_read(agents, agent_id).text

    def test_a_paper_that_is_a_supplementary_file_is_refused(self, agents: PaperAgents) -> None:
        agent_id = with_paper(agents)
        supplement(agents, agent_id, "notes.txt")

        error = refused(agents.put_paper, agent_id, "new.txt", io.BytesIO(SUPPLEMENT.encode("utf-8")))

        assert (error.status, error.code) == (409, "exists") and "supplementary file notes.txt" in error.message
        assert agents.view(agent_id)["paper"]["file"]["name"] == "paper.txt"

    def test_a_file_that_is_kept_already_or_is_the_paper_is_refused(self, agents: PaperAgents) -> None:
        agent_id = with_paper(agents)
        supplement(agents, agent_id, "a.txt", "the same words")

        twice = refused(supplement, agents, agent_id, "b.txt", "the same words")
        paper = refused(supplement, agents, agent_id, "copy.txt", PAPER)

        assert (twice.status, twice.code) == (409, "exists") and "as a.txt" in twice.message
        assert (paper.status, paper.code) == (409, "exists") and "the paper itself" in paper.message
        assert [item["name"] for item in agents.view(agent_id)["supplementary"]] == ["a.txt"]

    def test_only_files_that_are_read_and_no_more_than_may_be_are_kept(
        self, agents: PaperAgents, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kept_supplementary, "MAX_FILES", 2)
        agent_id = with_paper(agents)

        kind = refused(supplement, agents, agent_id, "table.xlsx", "cells")
        large = refused(supplement, agents, agent_id, "big.txt", "x" * (repository.LIMIT_BYTES + 1))
        supplement(agents, agent_id, "a.txt", "one")
        supplement(agents, agent_id, "b.txt", "two")
        many = refused(supplement, agents, agent_id, "c.txt", "three")
        # One that is in place of a file that is kept is not one more
        supplement(agents, agent_id, "b.txt", "two, again")

        assert (kind.status, kind.code) == (422, "invalid") and "table.xlsx" in kind.message
        assert (large.status, large.code) == (413, "too_large") and "a supplementary file" in large.message
        assert (many.status, many.code) == (409, "too_many")
        assert [item["name"] for item in agents.view(agent_id)["supplementary"]] == ["a.txt", "b.txt"]

    def test_a_name_with_a_path_is_kept_as_the_file_alone(self, agents: PaperAgents, workspace: Workspace) -> None:
        agent_id = with_paper(agents)

        supplement(agents, agent_id, "../../elsewhere/notes.txt")

        assert [item["name"] for item in agents.view(agent_id)["supplementary"]] == ["notes.txt"]
        assert (directory_of(workspace, agent_id) / kept_supplementary.SUPPLEMENTARY_DIR / "notes.txt").is_file()
        assert not (workspace.paperagents_dir.parent / "elsewhere").exists()

    def test_a_file_is_read_after_the_paper_under_a_heading_that_names_it(
        self, agents: PaperAgents, workspace: Workspace, fake_client: FakeClient
    ) -> None:
        agent_id = agents.create("A PDF", {"kind": "file"})
        agents.put_paper(agent_id, "paper.pdf", io.BytesIO(pdf_of("Abstract", RESULT)))
        supplement(agents, agent_id, "notes.txt")
        second = "On a second atlas of mouse cortex nuclei, CellMapper reached an AUROC of 0.81."
        queue(
            fake_client,
            reading(
                claims=[
                    ReadClaim(kind="number", value="0.93", quote=RESULT),
                    ReadClaim(kind="number", value="0.81", quote=second),
                ]
            ),
        )

        job = finish(agents.read(agent_id, 5))

        assert job.state == "succeeded", job.error
        text = (directory_of(workspace, agent_id) / PAPER_DIR / kept_reading.TEXT_FILE).read_text(encoding="utf-8")
        assert text.index(RESULT) < text.index("# Supplementary file: notes.txt") < text.index(second)
        # A fact of the paper is on its page, and one of the file is in the file, and on no page of the paper
        assert [
            (claim["value"], claim["anchor"]["page"], claim["anchor"]["section"])
            for claim in agents.reading(agent_id)["claims"]
        ] == [("0.93", 2, "Abstract"), ("0.81", None, "Supplementary file: notes.txt")]

    def test_a_link_in_a_file_is_a_place_for_the_data(self, agents: PaperAgents, fake_client: FakeClient) -> None:
        agent_id = with_paper(agents)
        supplement(agents, agent_id, "notes.txt", FOUND_IN)
        link = ReadLink(url="https://zenodo.org/records/7654321", role="data", quote=FOUND_IN)
        chunks = [chunk for chunk in plan_chunks(text_read(agents, agent_id), repository.SIZE, 0) if not chunk.skip]
        read_through(
            agents,
            agent_id,
            fake_client,
            *(reading(links=[link] if FOUND_IN in chunk.text else []) for chunk in chunks),
        )

        candidates = agents.data(agent_id)["candidates"]

        assert [(item["key"], item["facts"][0]["anchor"]["section"]) for item in candidates] == [
            ("zenodo:7654321", "Supplementary file: notes.txt")
        ]

    def test_adding_or_removing_a_file_clears_the_reading_and_keeps_what_the_person_did_to_the_card(
        self, agents: PaperAgents, workspace: Workspace, fake_client: FakeClient
    ) -> None:
        agent_id = with_paper(agents)
        directory = directory_of(workspace, agent_id)
        read_through(agents, agent_id, fake_client)
        agents.add_card_fact(agent_id, "methods", {"name": "Our own method"})
        assert agents.view(agent_id)["steps"]["reading"] == "done"

        supplement(agents, agent_id)

        assert agents.view(agent_id)["steps"]["reading"] == "pending"
        assert not agents.reading(agent_id)["complete"] and not agents.reading(agent_id)["has_text"]
        assert not (directory / "claims.json").exists()
        assert (directory / kept_reading.CARD_EDITS_FILE).is_file()

        read_through(agents, agent_id, fake_client)
        assert agents.view(agent_id)["steps"]["reading"] == "done"

        agents.remove_supplementary(agent_id, "notes.txt")

        assert agents.view(agent_id)["steps"]["reading"] == "pending"
        assert not agents.reading(agent_id)["has_text"]
        assert (directory / kept_reading.CARD_EDITS_FILE).is_file()
        # The last of them goes with its folder, and the agent says there are none
        assert agents.view(agent_id)["supplementary"] == []
        assert "supplementary" not in json.loads((directory / AGENT_FILE).read_text())
        assert not (directory / kept_supplementary.SUPPLEMENTARY_DIR).exists()

    def test_removing_one_leaves_the_others_and_one_that_is_not_there_is_not_found(self, agents: PaperAgents) -> None:
        agent_id = with_paper(agents)
        supplement(agents, agent_id, "a.txt", "one")
        supplement(agents, agent_id, "b.txt", "two")

        agents.remove_supplementary(agent_id, "a.txt")
        missing = refused(agents.remove_supplementary, agent_id, "a.txt")

        assert [item["name"] for item in agents.view(agent_id)["supplementary"]] == ["b.txt"]
        assert missing.status == 404

    def test_a_file_that_has_gone_from_its_folder_fails_the_reading_with_its_name(
        self, agents: PaperAgents, workspace: Workspace
    ) -> None:
        agent_id = with_paper(agents)
        supplement(agents, agent_id)
        (directory_of(workspace, agent_id) / kept_supplementary.SUPPLEMENTARY_DIR / "notes.txt").unlink()

        job = finish(agents.read(agent_id, 5))

        assert job.state == "failed"
        assert "notes.txt is missing" in (job.error or "") and str(workspace.root) not in (job.error or "")
        assert agents.view(agent_id)["steps"]["reading"] == "failed"

    def test_nothing_is_added_or_removed_while_the_agent_is_worked_on(
        self, agents: PaperAgents, remote: Remote
    ) -> None:
        agent_id = agent_of(agents)
        supplement(agents, agent_id, "a.txt", "one")
        remote.gate = threading.Event()
        started = agents.fetch_repository(agent_id)
        assert remote.started.wait(10)

        adding = refused(supplement, agents, agent_id, "b.txt", "two")
        removing = refused(agents.remove_supplementary, agent_id, "a.txt")
        remote.gate.set()
        finish(started)

        assert (adding.status, adding.code) == (409, "busy") and (removing.status, removing.code) == (409, "busy")
        assert [item["name"] for item in agents.view(agent_id)["supplementary"]] == ["a.txt"]

    @pytest.mark.parametrize(
        "listing",
        [
            "notes.txt",
            [{"name": "notes.txt", "bytes": 1}],
            [{"name": "a/notes.txt", "bytes": 1, "sha256": "0" * 64}],
            [{"name": "notes.txt", "bytes": True, "sha256": "0" * 64}],
            [{"name": "notes.txt", "bytes": 1, "sha256": "0" * 64}] * 2,
            [
                {"name": "notes.txt", "bytes": 1, "sha256": "0" * 64},
                {"name": "Notes.txt", "bytes": 1, "sha256": "1" * 64},
            ],
            [{"name": f"{number}.txt", "bytes": 1, "sha256": "0" * 64} for number in range(11)],
        ],
    )
    def test_an_agent_whose_record_of_them_was_edited_to_be_unfit_is_not_one(self, listing: Any) -> None:
        agent = {
            "schema": 1,
            "title": "A paper",
            "created_at": "2026-01-01T00:00:00Z",
            "paper": {"kind": "file", "file": None},
        }

        assert is_agent(agent) and is_agent({**agent, "supplementary": None})
        assert not is_agent({**agent, "supplementary": listing})

    def test_the_page_adds_and_removes_them(self, agents: PaperAgents, client: TestClient) -> None:
        agent_id = with_paper(agents)

        added = client.post(
            f"/api/paperagents/{agent_id}/supplementary", params={"name": "notes.txt"}, content=SUPPLEMENT.encode()
        )
        wrong = client.post(f"/api/paperagents/{agent_id}/supplementary", params={"name": "notes.exe"}, content=b"MZ")
        removed = client.delete(f"/api/paperagents/{agent_id}/supplementary", params={"name": "notes.txt"})
        again = client.delete(f"/api/paperagents/{agent_id}/supplementary", params={"name": "notes.txt"})

        assert added.status_code == 201
        assert [item["name"] for item in added.json()["supplementary"]] == ["notes.txt"]
        assert wrong.status_code == 422
        assert removed.status_code == 200 and removed.json()["supplementary"] == []
        assert again.status_code == 404


class TestTheTextThatIsRead:
    def test_without_files_it_is_the_paper_as_it_was(self) -> None:
        assert kept_supplementary.document_with(["One.", "Two."], True, [], 100) == document_from(
            ["One.", "Two."], True, 100
        )
        cut = kept_supplementary.document_with(["One. Two. Three.", "Four."], True, [], 10)
        assert cut == document_from(["One. Two. Three.", "Four."], True, 10) and cut.truncated_from is not None

    def test_the_pages_are_the_papers_and_a_place_in_a_file_is_on_none(self) -> None:
        document = kept_supplementary.document_with(["Page one.", "Page two."], True, [("s.txt", ["Extra words."])])

        assert document.text == "Page one.\n\nPage two.\n\n# Supplementary file: s.txt\n\nExtra words."
        assert document.pages == ((0, 9), (11, 20))
        assert document.page_at(document.text.index("two")) == 2
        assert document.page_at(document.text.index("Extra")) is None
        assert document.section_at(document.text.index("Extra")) == "Supplementary file: s.txt"

    def test_what_is_more_than_is_read_is_cut_from_the_end(self) -> None:
        document = kept_supplementary.document_with(
            ["The paper ends here."], True, [("s.txt", ["The file goes on. " * 20])], 60
        )

        assert len(document.text) <= 60 and document.truncated_from is not None and document.truncated_from > 60
        assert document.text.startswith("The paper ends here.") and document.pages == ((0, 20),)

    def test_the_pages_of_a_paper_that_is_cut_end_where_it_is(self) -> None:
        document = kept_supplementary.document_with(
            ["One. Two. Three. Four.", "Five."], True, [("s.txt", ["The file goes on."])], 10
        )

        assert document.truncated_from is not None and len(document.text) <= 10
        assert document.pages == ((0, len(document.text)),)

    def test_a_long_name_is_cut_so_that_its_heading_is_found(self) -> None:
        name = "n" * 300 + ".txt"
        document = kept_supplementary.document_with(["Paper."], False, [(name, ["Words."])])

        section = document.section_at(document.text.index("Words."))
        assert section is not None and section.startswith("Supplementary file: nnn")


class Mirrors(Remote):
    """Stands in for fetching with Git, from some addresses only: the others are not found."""

    def __init__(self, files: dict[str, Any], failing: set[str]) -> None:
        super().__init__(files)
        self.failing = failing

    def __call__(self, url: str, destination: Path, ref: str | None = None, max_bytes: int = 0, **options: Any) -> Any:
        if url in self.failing:
            self.calls.append({"url": url, "ref": ref, "max_bytes": max_bytes, "options": sorted(options)})
            raise cloning.RepositoryError(f"{url} was not found, or is private.")

        return super().__call__(url, destination, ref, max_bytes, **options)


@pytest.fixture
def mirrors(marker: Path, monkeypatch: pytest.MonkeyPatch) -> Mirrors:
    fetching = Mirrors(project(marker), set())
    monkeypatch.setattr(cloning, "clone", fetching)

    return fetching


class TestMoreAddressesOfTheCode:
    def test_they_are_kept_as_addresses_once_each_in_order_and_without_the_agents_own(
        self, agents: PaperAgents
    ) -> None:
        agent_id = agent_of(agents)

        agents.change(
            agent_id,
            also=[
                f"{OTHER_URL}.git",
                "",
                URL,
                "https://www.gitlab.com/example/cellmapper-mirror/-/tree/main",
                OTHER_URL,
            ],
        )

        assert agents.view(agent_id)["repo"] == {"url": URL, "also": [OTHER_URL, THIRD_URL]}

        agents.change(agent_id, also=[])

        assert agents.view(agent_id)["repo"] == {"url": URL}

    @pytest.mark.parametrize(
        "also",
        [
            "https://github.com/example/plots",
            [3],
            ["https://example.org/code"],
            [f"https://github.com/example/mirror{number}" for number in range(5)],
        ],
    )
    def test_what_is_not_a_list_of_addresses_of_code_or_is_too_many_is_refused(
        self, agents: PaperAgents, also: Any
    ) -> None:
        agent_id = agent_of(agents)

        error = refused(agents.change, agent_id, also=also)

        assert (error.status, error.code) == (422, "invalid")
        assert agents.view(agent_id)["repo"] == {"url": URL}

    def test_there_are_none_without_an_address_of_its_own(self, agents: PaperAgents) -> None:
        agent_id = agent_of(agents, repo=None)

        error = refused(agents.change, agent_id, also=[OTHER_URL])
        agents.change(agent_id, also=[])

        assert error.status == 422 and "Say where the code is first" in error.message
        assert agents.view(agent_id)["repo"] is None

    def test_saying_them_again_leaves_the_code_that_was_fetched(self, agents: PaperAgents, remote: Remote) -> None:
        agent_id = agent_of(agents)
        fetch(agents, agent_id)

        agents.change(agent_id, also=[OTHER_URL])

        assert agents.view(agent_id)["repo"] == {"url": URL, "also": [OTHER_URL], "ref": "HEAD", "commit": COMMIT}
        assert agents.repository(agent_id)["cloned"] and steps_of(agents.lookup(agent_id)[1])["repository"] == "done"

    def test_a_new_address_keeps_the_others_but_itself_and_no_address_takes_them_away(
        self, agents: PaperAgents
    ) -> None:
        agent_id = agent_of(agents)
        agents.change(agent_id, also=[OTHER_URL, THIRD_URL])

        agents.change(agent_id, repo=OTHER_URL)
        assert agents.view(agent_id)["repo"] == {"url": OTHER_URL, "also": [THIRD_URL]}

        agents.change(agent_id, repo=URL, also=[THIRD_URL, OTHER_URL])
        assert agents.view(agent_id)["repo"] == {"url": URL, "also": [THIRD_URL, OTHER_URL]}

        agents.change(agent_id, repo="")
        assert agents.view(agent_id)["repo"] is None

    def test_the_first_address_that_can_be_fetched_is_and_is_kept_as_the_agents(
        self, agents: PaperAgents, mirrors: Mirrors
    ) -> None:
        agent_id = agent_of(agents)
        agents.change(agent_id, also=[OTHER_URL, THIRD_URL])
        mirrors.failing = {URL}

        job = fetch(agents, agent_id)

        assert job.state == "succeeded", job.error
        # Only one is fetched: the one after it is not asked
        assert [call["url"] for call in mirrors.calls] == [URL, OTHER_URL]
        assert job.message.startswith(f"{URL} could not be fetched, so {OTHER_URL} was. Fetched ")
        lines = job.snapshot(0)["log"]["lines"]
        assert any(f"{URL} could not be fetched: {URL} was not found" in line for line in lines)
        assert any(line == f"Trying {OTHER_URL} in its place" for line in lines)
        # The one that was fetched is the agent's, and the one that could not be is first of the others
        assert agents.view(agent_id)["repo"] == {
            "url": OTHER_URL,
            "also": [URL, THIRD_URL],
            "ref": "HEAD",
            "commit": COMMIT,
        }
        found = agents.repository(agent_id)
        assert found["cloned"] and found["intake"]["url"] == OTHER_URL
        assert steps_of(agents.lookup(agent_id)[1])["repository"] == "done"

    def test_when_none_can_be_fetched_each_says_why_and_the_agent_is_as_it_was(
        self, agents: PaperAgents, mirrors: Mirrors
    ) -> None:
        agent_id = agent_of(agents)
        agents.change(agent_id, also=[OTHER_URL])
        mirrors.failing = {URL, OTHER_URL}

        job = fetch(agents, agent_id)

        assert job.state == "failed"
        assert job.error == (
            f"The code could not be fetched from any of its 2 addresses. {URL}: {URL} was not found, or is private. "
            f"{OTHER_URL}: {OTHER_URL} was not found, or is private."
        )
        assert agents.view(agent_id)["repo"] == {"url": URL, "also": [OTHER_URL]}
        assert steps_of(agents.lookup(agent_id)[1])["repository"] == "failed"

    def test_an_agent_with_one_address_fails_as_it_did(self, agents: PaperAgents, mirrors: Mirrors) -> None:
        agent_id = agent_of(agents)
        mirrors.failing = {URL}

        job = fetch(agents, agent_id)

        assert job.state == "failed" and job.error == f"{URL} was not found, or is private."

    def test_an_address_that_is_asked_for_is_fetched_first_and_the_others_after(
        self, agents: PaperAgents, mirrors: Mirrors
    ) -> None:
        agent_id = agent_of(agents)
        agents.change(agent_id, also=[OTHER_URL, THIRD_URL])
        mirrors.failing = {THIRD_URL, URL}

        job = fetch(agents, agent_id, repo=THIRD_URL)

        assert job.state == "succeeded", job.error
        assert [call["url"] for call in mirrors.calls] == [THIRD_URL, OTHER_URL]
        # The address that it was asked for in place of is not the agent's any more, nor one of the others
        assert agents.view(agent_id)["repo"]["url"] == OTHER_URL
        assert agents.view(agent_id)["repo"]["also"] == [THIRD_URL]

    def test_a_stop_is_not_taken_for_an_address_that_cannot_be_fetched(
        self, agents: PaperAgents, mirrors: Mirrors
    ) -> None:
        agent_id = agent_of(agents)
        agents.change(agent_id, also=[OTHER_URL])
        mirrors.gate = threading.Event()
        started = agents.fetch_repository(agent_id)
        assert mirrors.started.wait(10)

        started.stop.set()
        job = finish(started)

        assert job.state == "stopped" and [call["url"] for call in mirrors.calls] == [URL]

    def test_clearing_the_code_keeps_them(self, agents: PaperAgents, remote: Remote) -> None:
        agent_id = agent_of(agents)
        agents.change(agent_id, also=[OTHER_URL])
        fetch(agents, agent_id)

        agents.clear_repository(agent_id)

        assert agents.view(agent_id)["repo"] == {"url": URL, "also": [OTHER_URL]}

    def test_they_are_not_said_again_while_the_code_is_fetched(self, agents: PaperAgents, remote: Remote) -> None:
        agent_id = agent_of(agents)
        remote.gate = threading.Event()
        started = agents.fetch_repository(agent_id)
        assert remote.started.wait(10)

        error = refused(agents.change, agent_id, also=[OTHER_URL])
        remote.gate.set()
        finish(started)

        assert (error.status, error.code) == (409, "busy")
        assert "also" not in agents.view(agent_id)["repo"]

    @pytest.mark.parametrize(
        "also",
        [
            [],
            "x",
            [OTHER_URL, OTHER_URL],
            [URL],
            [f"{OTHER_URL}.git"],
            [f"https://github.com/e/m{n}" for n in range(5)],
        ],
    )
    def test_an_agent_whose_others_were_edited_to_be_unfit_is_not_one(self, also: Any) -> None:
        agent = {
            "schema": 1,
            "title": "A paper",
            "created_at": "2026-01-01T00:00:00Z",
            "paper": {"kind": "file", "file": None},
            "repo": {"url": URL},
        }

        assert is_agent(agent) and is_agent({**agent, "repo": {"url": URL, "also": [OTHER_URL]}})
        assert not is_agent({**agent, "repo": {"url": URL, "also": also}})

    def test_the_page_says_them(self, agents: PaperAgents, client: TestClient) -> None:
        agent_id = agent_of(agents)

        changed = client.patch(f"/api/paperagents/{agent_id}", json={"also": [OTHER_URL]})
        wrong = client.patch(f"/api/paperagents/{agent_id}", json={"also": "nope"})

        assert changed.status_code == 200 and changed.json()["repo"] == {"url": URL, "also": [OTHER_URL]}
        assert wrong.status_code == 422


class TestPlacesForTheData:
    def test_a_place_that_is_added_is_shown_with_those_the_paper_names_and_nothing_is_asked_of_it(
        self, agents: PaperAgents, web: Web
    ) -> None:
        agent_id = agent_of(agents)

        agents.add_data_link(agent_id, "  10.5281/zenodo.1234567 ")
        agents.add_data_link(agent_id, "GSE123456")

        found = agents.data(agent_id)
        assert [(item["key"], item["added"], item["supported"], item["facts"]) for item in found["candidates"]] == [
            ("geo:GSE123456", True, True, []),
            ("zenodo:1234567", True, True, []),
        ]
        assert [(link["key"], link["text"]) for link in found["links"]] == [
            ("zenodo:1234567", "10.5281/zenodo.1234567"),
            ("geo:GSE123456", "GSE123456"),
        ]
        assert found["limits"]["max_links"] == kept_data.MAX_LINKS
        assert web.asked == []

    def test_a_place_that_the_paper_names_too_is_shown_once(self, agents: PaperAgents, fake_client: FakeClient) -> None:
        agent_id = with_paper(agents, FOUND_IN)
        link = ReadLink(url="https://zenodo.org/records/7654321", role="data", quote=FOUND_IN)
        read_through(agents, agent_id, fake_client, reading(links=[link]))

        agents.add_data_link(agent_id, "https://zenodo.org/records/7654321")

        candidates = agents.data(agent_id)["candidates"]
        assert [(item["key"], item["added"], len(item["facts"])) for item in candidates] == [
            ("zenodo:7654321", True, 1)
        ]

    def test_its_files_are_seen_and_fetched_as_those_of_any_place(self, agents: PaperAgents, web: Web) -> None:
        zenodo(web, {"counts.csv": b"gene,score\nTP53,0.91\n"})
        agent_id = agent_of(agents)
        agents.add_data_link(agent_id, "https://zenodo.org/records/1234567")

        listed = agents.data_files(agent_id, "https://zenodo.org/records/1234567")
        job = finish(agents.download_data(agent_id, "https://zenodo.org/records/1234567", ["counts.csv"], 21))

        assert [file["name"] for file in listed["files"]] == ["counts.csv"]
        assert job.state == "succeeded", job.error
        found = agents.data(agent_id)
        assert [(item["key"], item["added"], item["fetched"]) for item in found["candidates"]] == [
            ("zenodo:1234567", True, 1)
        ]

    def test_a_place_that_is_not_fetched_from_or_is_added_already_is_refused(self, agents: PaperAgents) -> None:
        agent_id = agent_of(agents)
        agents.add_data_link(agent_id, "https://zenodo.org/records/1234567")

        twice = refused(agents.add_data_link, agent_id, "https://zenodo.org/record/1234567")
        elsewhere = refused(agents.add_data_link, agent_id, "https://example.org/data.csv")
        controlled = refused(agents.add_data_link, agent_id, "EGAS00001000001")
        nothing = refused(agents.add_data_link, agent_id, "   ")

        assert (twice.status, twice.code) == (409, "exists")
        assert (elsewhere.status, elsewhere.code) == (422, "unsupported")
        assert (controlled.status, controlled.code) == (422, "unsupported") and "EGA" in controlled.message
        assert (nothing.status, nothing.code) == (422, "invalid")
        assert len(agents.data(agent_id)["links"]) == 1

    def test_no_more_than_may_be_are_added(self, agents: PaperAgents, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(kept_data, "MAX_LINKS", 1)
        agent_id = agent_of(agents)
        agents.add_data_link(agent_id, "GSE1")

        error = refused(agents.add_data_link, agent_id, "GSE2")

        assert (error.status, error.code) == (409, "too_many")

    def test_one_that_is_taken_away_is_not_shown_and_what_was_fetched_from_it_is_kept(
        self, agents: PaperAgents, web: Web
    ) -> None:
        zenodo(web, {"counts.csv": b"gene,score\nTP53,0.91\n"})
        agent_id = agent_of(agents)
        agents.add_data_link(agent_id, "https://zenodo.org/records/1234567")
        agents.add_data_link(agent_id, "GSE123456")
        finish(agents.download_data(agent_id, "https://zenodo.org/records/1234567", ["counts.csv"], 21))

        agents.remove_data_link(agent_id, "zenodo:1234567")
        missing = refused(agents.remove_data_link, agent_id, "zenodo:1234567")

        found = agents.data(agent_id)
        assert [item["key"] for item in found["candidates"]] == ["geo:GSE123456"]
        assert found["kept"]["files"] == 1 and steps_of(agents.lookup(agent_id)[1])["data"] == "done"
        assert missing.status == 404

    def test_clearing_the_data_keeps_the_places_that_were_added(self, agents: PaperAgents, web: Web) -> None:
        zenodo(web, {"counts.csv": b"gene,score\nTP53,0.91\n"})
        agent_id = agent_of(agents)
        agents.add_data_link(agent_id, "https://zenodo.org/records/1234567")
        finish(agents.download_data(agent_id, "https://zenodo.org/records/1234567", ["counts.csv"], 21))

        agents.clear_data(agent_id)

        assert [link["key"] for link in agents.data(agent_id)["links"]] == ["zenodo:1234567"]

    def test_a_record_of_one_that_was_edited_to_be_unfit_is_left_out(
        self, agents: PaperAgents, workspace: Workspace
    ) -> None:
        agent_id = agent_of(agents)
        agents.add_data_link(agent_id, "GSE123456")
        path = directory_of(workspace, agent_id) / kept_data.RECORD_FILE
        record = json.loads(path.read_text())
        record["links"] += [
            {"key": "geo:GSE999", "text": "GSE123456", "added_at": "2026-01-01T00:00:00Z"},
            {"key": "link:example.org", "text": "https://example.org/data.csv", "added_at": "2026-01-01T00:00:00Z"},
            {"key": "geo:GSE5", "text": 5, "added_at": "2026-01-01T00:00:00Z"},
            "GSE5",
        ]
        path.write_text(json.dumps(record))

        assert [link["key"] for link in agents.data(agent_id)["links"]] == ["geo:GSE123456"]

    def test_a_record_of_more_than_may_be_kept_is_cut(self, agents: PaperAgents, workspace: Workspace) -> None:
        agent_id = agent_of(agents)
        agents.add_data_link(agent_id, "GSE1")
        path = directory_of(workspace, agent_id) / kept_data.RECORD_FILE
        record = json.loads(path.read_text())
        record["links"] = [
            {"key": f"geo:GSE{index}", "text": f"GSE{index}", "added_at": "2026-01-01T00:00:00Z"}
            for index in range(1, kept_data.MAX_LINKS + 2)
        ]
        path.write_text(json.dumps(record))

        assert len(agents.data(agent_id)["links"]) == kept_data.MAX_LINKS

    def test_the_page_adds_and_takes_them_away(self, agents: PaperAgents, client: TestClient) -> None:
        agent_id = agent_of(agents)

        added = client.post(f"/api/paperagents/{agent_id}/data/links", json={"reference": "GSE123456"})
        wrong = client.post(f"/api/paperagents/{agent_id}/data/links", json={"reference": "https://example.org/x.csv"})
        removed = client.delete(f"/api/paperagents/{agent_id}/data/links", params={"key": "geo:GSE123456"})

        assert added.status_code == 201 and [link["key"] for link in added.json()["links"]] == ["geo:GSE123456"]
        assert wrong.status_code == 422
        assert removed.status_code == 200 and removed.json()["links"] == []
