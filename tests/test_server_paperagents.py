"""Tests of the PaperAgents: making one of a paper, keeping the paper uploaded to it, and telling papers apart."""

import hashlib
import io
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from virtual_lab.server import paperagents as module
from virtual_lab.server.app import create_app
from virtual_lab.server.errors import ApiError
from virtual_lab.server.paperagents import (
    AGENT_FILE,
    MAX_URL_CHARS,
    PAPER_DIR,
    STEPS,
    PaperAgents,
    check_doi,
    check_paper,
    check_repo,
    check_title,
    check_url,
    is_agent,
    steps_of,
)
from virtual_lab.server.workspace import Workspace

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}

LIMIT = 1024
DOI = "10.1038/s41586-020-2649-2"
TEXT = b"Differential expression was found with DESeq2, from samples in GEO, aligned with STAR."


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "workspace")


@pytest.fixture
def agents(workspace: Workspace) -> PaperAgents:
    return PaperAgents(workspace, LIMIT)


@pytest.fixture
def client(workspace: Workspace) -> Iterator[TestClient]:
    app = create_app(workspace.root, token=TOKEN, check_keys=False, max_upload_bytes=LIMIT)
    with TestClient(app, base_url=LOCAL, headers=BEARER) as opened:
        yield opened


def refused(call: Any, *args: Any, **kwargs: Any) -> ApiError:
    with pytest.raises(ApiError) as caught:
        call(*args, **kwargs)

    return caught.value


def doi_agent(agents: PaperAgents, doi: str = DOI, title: str = "") -> str:
    return agents.create(title, {"kind": "doi", "doi": doi})


def file_agent(agents: PaperAgents, title: str = "A paper") -> str:
    return agents.create(title, {"kind": "file"})


class TestDois:
    @pytest.mark.parametrize(
        "given",
        [DOI, f"  {DOI}  ", f"doi:{DOI}", f"DOI: {DOI}", f"https://doi.org/{DOI}", f"http://dx.doi.org/{DOI}"],
    )
    def test_a_doi_is_kept_without_what_a_link_to_it_begins_with(self, given: str) -> None:
        assert check_doi(given) == DOI

    def test_a_doi_is_kept_in_lower_case(self) -> None:
        assert check_doi("10.1002/ABC.123") == "10.1002/abc.123"

    @pytest.mark.parametrize(
        "given", ["", "   ", "10.1/x", "11.1038/abc", "10.1038/", "10.1038/a b", "not a doi", None, 7, "10.1038/a\x00b"]
    )
    def test_what_is_not_a_doi_is_refused(self, given: Any) -> None:
        assert refused(check_doi, given).status == 422

    def test_one_too_long_is_refused(self) -> None:
        assert refused(check_doi, "10.1038/" + "a" * 300).status == 422


class TestUrls:
    def test_a_link_is_kept_with_its_host_in_lower_case_and_without_a_fragment_or_a_slash_at_the_end(self) -> None:
        assert check_url("  HTTPS://Example.ORG/Papers/One/#intro ") == "https://example.org/Papers/One"
        assert check_url("https://example.org") == "https://example.org/"
        assert check_url("http://example.org/a?x=1&y=2") == "http://example.org/a?x=1&y=2"

    @pytest.mark.parametrize(
        "given",
        [
            "",
            "ftp://example.org/a",
            "file:///etc/passwd",
            "example.org/a",
            "https://",
            "https://user:secret@example.org/a",
            "https://user@example.org/a",
            "https://example.org/a b",
            "https://example.org:99999999/a",
            "https://example.org/a\nb",
            None,
            3,
        ],
    )
    def test_what_is_not_a_web_address_that_leads_somewhere_by_http_is_refused(self, given: Any) -> None:
        assert refused(check_url, given).status == 422

    def test_a_password_in_a_link_is_not_repeated_in_what_is_said_of_it(self) -> None:
        error = refused(check_url, "https://user:secret@example.org/a")

        assert "secret" not in error.message

    def test_a_link_that_is_too_long_is_refused(self) -> None:
        assert refused(check_url, "https://example.org/" + "a" * MAX_URL_CHARS).status == 422


class TestRepos:
    @pytest.mark.parametrize(
        ("given", "kept"),
        [
            ("https://github.com/Owner/Repo", "https://github.com/Owner/Repo"),
            ("https://github.com/Owner/Repo.git", "https://github.com/Owner/Repo"),
            ("https://github.com/Owner/Repo/tree/main/src?x=1#top", "https://github.com/Owner/Repo"),
            ("https://www.github.com/owner/repo/", "https://github.com/owner/repo"),
            ("HTTPS://GitHub.com/owner/repo", "https://github.com/owner/repo"),
            ("https://bitbucket.org/team/project/src/main", "https://bitbucket.org/team/project"),
            ("https://codeberg.org/user/tool.git", "https://codeberg.org/user/tool"),
            ("https://gitlab.com/group/project", "https://gitlab.com/group/project"),
            ("https://gitlab.com/group/sub/project/-/tree/main", "https://gitlab.com/group/sub/project"),
            ("https://gitlab.com/group/sub/project.git", "https://gitlab.com/group/sub/project"),
        ],
    )
    def test_the_address_of_code_is_kept_as_far_as_the_project(self, given: str, kept: str) -> None:
        assert check_repo(given) == kept

    @pytest.mark.parametrize(
        "given",
        [
            "http://github.com/owner/repo",
            "https://example.org/owner/repo",
            "https://github.com.evil.org/owner/repo",
            "https://github.com/owner",
            "https://github.com/",
            "https://github.com/owner/../repo",
            "https://github.com/ow ner/repo",
            "https://gitlab.com/group/-/tree/main",
            "git@github.com:owner/repo.git",
            "https://user:pass@github.com/owner/repo",
            "",
            None,
        ],
    )
    def test_what_is_not_the_address_of_a_project_at_a_host_of_code_is_refused(self, given: Any) -> None:
        assert refused(check_repo, given).status == 422


class TestPapers:
    def test_a_paper_is_given_by_its_doi_a_link_or_a_file(self) -> None:
        assert check_paper({"kind": "doi", "doi": f"doi:{DOI.upper()}"}) == {"kind": "doi", "doi": DOI}
        assert check_paper({"kind": "url", "url": "https://example.org/a/"}) == {
            "kind": "url",
            "url": "https://example.org/a",
        }
        assert check_paper({"kind": "file"}) == {"kind": "file", "file": None}

    def test_a_link_to_a_doi_is_kept_as_the_doi(self) -> None:
        assert check_paper({"kind": "url", "url": f"https://doi.org/{DOI}"}) == {"kind": "doi", "doi": DOI}
        assert check_paper({"kind": "url", "url": f"https://dx.doi.org/{DOI.replace('/', '%2F')}"}) == {
            "kind": "doi",
            "doi": DOI,
        }

    @pytest.mark.parametrize(
        "paper",
        [
            {},
            {"kind": "pmid", "pmid": "1"},
            {"kind": "doi"},
            {"kind": "url"},
            {"kind": "doi", "doi": DOI, "url": "https://example.org"},
            {"kind": "file", "doi": DOI},
            {"kind": "doi", "doi": "nonsense"},
        ],
    )
    def test_what_is_not_fit_to_say_which_paper_is_refused(self, paper: dict[str, Any]) -> None:
        assert refused(check_paper, paper).status == 422

    def test_a_value_that_is_none_is_taken_for_one_not_given(self) -> None:
        assert check_paper({"kind": "doi", "doi": DOI, "url": None}) == {"kind": "doi", "doi": DOI}


class TestTitles:
    def test_a_title_is_one_line(self) -> None:
        assert check_title("  A   paper \n here ") == "A paper here"

    def test_a_doi_or_a_link_is_what_an_agent_is_called_if_it_is_not_told(self) -> None:
        assert check_title("", {"kind": "doi", "doi": DOI}) == DOI
        assert check_title(None, {"kind": "url", "url": "https://example.org/a/b"}) == "example.org/a/b"

    def test_a_file_needs_a_title(self) -> None:
        assert refused(check_title, "", {"kind": "file", "file": None}).status == 422
        assert refused(check_title, "   ").status == 422

    def test_a_title_that_is_too_long_or_has_a_control_character_is_refused(self) -> None:
        assert refused(check_title, "a" * 201).status == 422
        assert refused(check_title, "a\x07b").status == 422
        assert refused(check_title, 4).status == 422


class TestMakingAnAgent:
    def test_an_agent_is_named_by_its_title_and_a_number_if_that_is_taken(self, agents: PaperAgents) -> None:
        assert file_agent(agents, "Gene paper") == "gene-paper"
        assert file_agent(agents, "  Gene   paper ") == "gene-paper-2"
        assert doi_agent(agents, title="Gene paper") == "gene-paper-3"

    def test_an_agent_has_nothing_done_to_it_yet(self, agents: PaperAgents) -> None:
        agent = agents.view(agents.create("Cells", {"kind": "doi", "doi": DOI}, "https://github.com/owner/repo.git"))

        assert agent["title"] == "Cells"
        assert agent["paper"] == {"kind": "doi", "doi": DOI}
        assert agent["repo"] == {"url": "https://github.com/owner/repo"}
        assert agent["steps"] == dict.fromkeys(STEPS, "pending")
        assert agent["created_at"]

    def test_the_code_is_left_out_if_it_is_not_known(self, agents: PaperAgents) -> None:
        assert agents.view(doi_agent(agents))["repo"] is None
        assert agents.view(agents.create("", {"kind": "doi", "doi": "10.1000/abcd1"}, ""))["repo"] is None

    def test_what_is_kept_says_how_it_is_kept(self, agents: PaperAgents, workspace: Workspace) -> None:
        agent_id = doi_agent(agents)

        record = json.loads((workspace.paperagents_dir / agent_id / AGENT_FILE).read_text())

        assert record["schema"] == module.SCHEMA
        assert is_agent(record)

    def test_a_title_a_paper_or_code_that_is_not_fit_makes_nothing(
        self, agents: PaperAgents, workspace: Workspace
    ) -> None:
        assert refused(agents.create, "", {"kind": "file"}).status == 422
        assert refused(agents.create, "x", {"kind": "doi", "doi": "nope"}).status == 422
        assert refused(agents.create, "x", {"kind": "doi", "doi": DOI}, "https://example.org/a/b").status == 422

        assert agents.describe()["agents"] == []
        assert not workspace.paperagents_dir.exists()

    def test_a_paper_that_has_an_agent_is_refused_with_the_agent_it_has(self, agents: PaperAgents) -> None:
        first = doi_agent(agents, title="First")

        error = refused(agents.create, "Again", {"kind": "doi", "doi": f"https://doi.org/{DOI.upper()}"})

        assert (error.status, error.code) == (409, "exists")
        assert error.details["existing"] == first
        assert "First" in error.message
        assert len(agents.describe()["agents"]) == 1

    def test_a_link_that_is_said_differently_is_the_same_link(self, agents: PaperAgents) -> None:
        first = agents.create("", {"kind": "url", "url": "https://Example.org/paper/"})

        error = refused(agents.create, "", {"kind": "url", "url": "https://example.org/paper#abstract"})

        assert error.details["existing"] == first

    def test_a_doi_and_a_link_are_not_taken_for_each_other(self, agents: PaperAgents) -> None:
        doi_agent(agents)
        agents.create("", {"kind": "url", "url": "https://example.org/paper"})

        assert len(agents.describe()["agents"]) == 2

    def test_of_two_agents_of_one_paper_made_at_once_one_is_made(self, agents: PaperAgents) -> None:
        results: list[object] = []
        barrier = threading.Barrier(6)

        def make() -> None:
            barrier.wait()
            try:
                results.append(doi_agent(agents))
            except ApiError as error:
                results.append(error)

        threads = [threading.Thread(target=make) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sum(isinstance(result, str) for result in results) == 1
        assert all(result.code == "exists" for result in results if isinstance(result, ApiError))
        assert len(agents.describe()["agents"]) == 1

    def test_there_is_a_most_that_can_be_kept(self, agents: PaperAgents, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(module, "MAX_AGENTS", 2)
        file_agent(agents, "One")
        file_agent(agents, "Two")

        error = refused(file_agent, agents, "Three")

        assert (error.status, error.code) == (409, "too_many")
        assert len(agents.describe()["agents"]) == 2


class TestListing:
    def test_agents_are_listed_with_the_latest_first_and_what_a_page_needs_to_make_one(
        self, agents: PaperAgents
    ) -> None:
        first = file_agent(agents, "First")
        second = file_agent(agents, "Second")

        described = agents.describe()

        assert [agent["id"] for agent in described["agents"]] == [second, first]
        assert described["max_agents"] == module.MAX_AGENTS
        assert described["max_paper_bytes"] == LIMIT
        assert ".pdf" in described["suffixes"]
        assert "github.com" in described["repo_hosts"]

    def test_nothing_is_listed_before_there_is_an_agent(self, agents: PaperAgents) -> None:
        assert agents.describe()["agents"] == []

    def test_what_is_not_an_agent_is_left_out(self, agents: PaperAgents, workspace: Workspace) -> None:
        kept = file_agent(agents, "Kept")
        root = workspace.paperagents_dir
        (root / "empty").mkdir()
        (root / "broken").mkdir()
        (root / "broken" / AGENT_FILE).write_text("{not json")
        (root / "wrong").mkdir()
        (root / "wrong" / AGENT_FILE).write_text(json.dumps({"schema": 1, "title": 4}))
        (root / "Not A Name").mkdir()
        (root / "Not A Name" / AGENT_FILE).write_text((root / kept / AGENT_FILE).read_text())
        (root / "stray.txt").write_text("x")

        assert [agent["id"] for agent in agents.describe()["agents"]] == [kept]
        assert refused(agents.view, "broken").status == 404
        assert refused(agents.view, "Not A Name").status == 404
        assert refused(agents.view, "../paperagents").status == 404

    def test_an_unknown_agent_is_not_found(self, agents: PaperAgents) -> None:
        assert refused(agents.view, "nothing").status == 404


class TestSteps:
    def test_a_step_that_is_not_said_or_is_said_wrongly_is_pending(self) -> None:
        said = {"steps": {"reading": "done", "tools": "exploded", "other": "done"}}

        steps = steps_of(said)

        assert steps == {
            "reading": "done",
            "repository": "pending",
            "environment": "pending",
            "data": "pending",
            "tools": "pending",
        }
        assert steps_of({}) == dict.fromkeys(STEPS, "pending")
        assert steps_of({"steps": "no"}) == dict.fromkeys(STEPS, "pending")


class TestChanging:
    def test_the_title_and_the_code_can_be_said_again(self, agents: PaperAgents) -> None:
        agent_id = doi_agent(agents)

        agents.change(agent_id, title="  A better   name ")
        agents.change(agent_id, repo="https://github.com/owner/repo")

        agent = agents.view(agent_id)
        assert agent["title"] == "A better name"
        assert agent["repo"] == {"url": "https://github.com/owner/repo"}
        assert agent["id"] == agent_id
        assert agent["paper"] == {"kind": "doi", "doi": DOI}

    def test_what_is_not_given_is_left_as_it_was_and_an_empty_address_takes_the_code_away(
        self, agents: PaperAgents
    ) -> None:
        agent_id = agents.create("Cells", {"kind": "doi", "doi": DOI}, "https://github.com/owner/repo")

        agents.change(agent_id, title="Cells again")
        assert agents.view(agent_id)["repo"] == {"url": "https://github.com/owner/repo"}

        agents.change(agent_id, repo="")
        assert agents.view(agent_id)["repo"] is None
        assert agents.view(agent_id)["title"] == "Cells again"

    def test_a_change_that_is_not_fit_changes_nothing(self, agents: PaperAgents) -> None:
        agent_id = agents.create("Cells", {"kind": "doi", "doi": DOI}, "https://github.com/owner/repo")
        before = agents.view(agent_id)

        assert refused(agents.change, agent_id).status == 422
        assert refused(agents.change, agent_id, title="").status == 422
        assert refused(agents.change, agent_id, repo="https://example.org/a/b").status == 422
        assert refused(agents.change, agent_id, title="Fine", repo="nope").status == 422

        assert agents.view(agent_id) == before

    def test_an_agent_that_is_not_there_is_not_found(self, agents: PaperAgents) -> None:
        assert refused(agents.change, "nothing", title="x").status == 404


class TestDeleting:
    def test_an_agent_is_deleted_with_its_paper(self, agents: PaperAgents, workspace: Workspace) -> None:
        agent_id = file_agent(agents)
        agents.put_paper(agent_id, "a.txt", io.BytesIO(TEXT))

        agents.delete(agent_id)

        assert not (workspace.paperagents_dir / agent_id).exists()
        assert agents.describe()["agents"] == []
        assert refused(agents.view, agent_id).status == 404

    def test_the_paper_of_a_deleted_agent_can_be_given_to_another(self, agents: PaperAgents) -> None:
        first = doi_agent(agents)
        agents.delete(first)

        assert doi_agent(agents) == first

    def test_an_agent_that_is_not_there_is_not_found(self, agents: PaperAgents) -> None:
        assert refused(agents.delete, "nothing").status == 404


class TestKeepingAPaper:
    def test_a_paper_that_is_uploaded_is_kept_and_what_is_in_it_is_recorded(
        self, agents: PaperAgents, workspace: Workspace
    ) -> None:
        agent_id = file_agent(agents)

        agents.put_paper(agent_id, "a.txt", io.BytesIO(TEXT))

        kept = agents.view(agent_id)["paper"]
        assert kept == {
            "kind": "file",
            "file": {"name": "a.txt", "bytes": len(TEXT), "sha256": hashlib.sha256(TEXT).hexdigest()},
        }
        assert (workspace.paperagents_dir / agent_id / PAPER_DIR / "a.txt").read_bytes() == TEXT

    def test_a_name_with_a_path_is_kept_as_its_last_part(self, agents: PaperAgents, workspace: Workspace) -> None:
        agent_id = file_agent(agents)

        agents.put_paper(agent_id, "../../elsewhere/paper.md", io.BytesIO(TEXT))

        assert agents.view(agent_id)["paper"]["file"]["name"] == "paper.md"
        assert (workspace.paperagents_dir / agent_id / PAPER_DIR / "paper.md").is_file()
        assert not (workspace.root / "elsewhere").exists()

    def test_a_paper_uploaded_again_takes_the_place_of_the_one_before(
        self, agents: PaperAgents, workspace: Workspace
    ) -> None:
        agent_id = file_agent(agents)
        agents.put_paper(agent_id, "a.txt", io.BytesIO(TEXT))

        agents.put_paper(agent_id, "b.md", io.BytesIO(b"Another paper."))

        folder = workspace.paperagents_dir / agent_id / PAPER_DIR
        assert [path.name for path in folder.iterdir()] == ["b.md"]
        assert agents.view(agent_id)["paper"]["file"]["name"] == "b.md"

    def test_the_same_paper_uploaded_to_its_own_agent_again_is_not_a_second_agent(self, agents: PaperAgents) -> None:
        agent_id = file_agent(agents)
        agents.put_paper(agent_id, "a.txt", io.BytesIO(TEXT))

        agents.put_paper(agent_id, "a.txt", io.BytesIO(TEXT))

        assert agents.view(agent_id)["paper"]["file"]["name"] == "a.txt"

    def test_a_paper_another_agent_has_is_refused_with_that_agent(
        self, agents: PaperAgents, workspace: Workspace
    ) -> None:
        first = file_agent(agents, "First")
        second = file_agent(agents, "Second")
        agents.put_paper(first, "a.txt", io.BytesIO(TEXT))

        error = refused(agents.put_paper, second, "copy.txt", io.BytesIO(TEXT))

        assert (error.status, error.code) == (409, "exists")
        assert error.details["existing"] == first
        assert agents.view(second)["paper"]["file"] is None
        assert not (workspace.paperagents_dir / second / PAPER_DIR).exists()

    def test_a_paper_that_is_too_big_is_refused_and_leaves_nothing(
        self, agents: PaperAgents, workspace: Workspace
    ) -> None:
        agent_id = file_agent(agents)
        agents.put_paper(agent_id, "a.txt", io.BytesIO(TEXT))

        error = refused(agents.put_paper, agent_id, "big.txt", io.BytesIO(b"x" * (LIMIT + 1)))

        assert (error.status, error.code) == (413, "too_large")
        assert agents.view(agent_id)["paper"]["file"]["name"] == "a.txt"
        assert (workspace.paperagents_dir / agent_id / PAPER_DIR / "a.txt").read_bytes() == TEXT
        assert not any(path.name.startswith("paperagent.") for path in workspace.root.iterdir())

    def test_what_is_not_a_paper_is_refused(self, agents: PaperAgents) -> None:
        agent_id = file_agent(agents)

        assert refused(agents.put_paper, agent_id, "data.csv", io.BytesIO(b"a,b")).status == 422
        assert refused(agents.put_paper, agent_id, "noextension", io.BytesIO(b"a")).status == 422
        assert agents.view(agent_id)["paper"]["file"] is None

    def test_a_paper_is_uploaded_only_to_an_agent_whose_paper_is_a_file(self, agents: PaperAgents) -> None:
        agent_id = doi_agent(agents)

        error = refused(agents.put_paper, agent_id, "a.txt", io.BytesIO(TEXT))

        assert (error.status, error.code) == (409, "invalid")

    def test_an_agent_that_is_not_there_is_not_found(self, agents: PaperAgents) -> None:
        assert refused(agents.put_paper, "nothing", "a.txt", io.BytesIO(TEXT)).status == 404

    def test_a_paper_can_be_taken_away_and_the_agent_stays(self, agents: PaperAgents, workspace: Workspace) -> None:
        agent_id = file_agent(agents)
        agents.put_paper(agent_id, "a.txt", io.BytesIO(TEXT))

        agents.remove_paper(agent_id)

        assert agents.view(agent_id)["paper"] == {"kind": "file", "file": None}
        assert not (workspace.paperagents_dir / agent_id / PAPER_DIR).exists()

    def test_a_paper_that_was_taken_away_can_be_given_to_another_agent(self, agents: PaperAgents) -> None:
        first = file_agent(agents, "First")
        second = file_agent(agents, "Second")
        agents.put_paper(first, "a.txt", io.BytesIO(TEXT))
        agents.remove_paper(first)

        agents.put_paper(second, "a.txt", io.BytesIO(TEXT))

        assert agents.view(second)["paper"]["file"]["name"] == "a.txt"

    def test_there_is_nothing_to_take_away_from_an_agent_with_no_paper_uploaded(self, agents: PaperAgents) -> None:
        assert refused(agents.remove_paper, file_agent(agents)).status == 404
        assert refused(agents.remove_paper, doi_agent(agents)).status == 404
        assert refused(agents.remove_paper, "nothing").status == 404


class TestTheApi:
    def make(self, client: TestClient, **body: Any) -> Any:
        return client.post("/api/paperagents", json={"paper": {"kind": "doi", "doi": DOI}, **body})

    def test_an_agent_is_made_listed_shown_and_deleted(self, client: TestClient) -> None:
        made = self.make(client, title="Cells", repo="https://github.com/owner/repo")

        assert made.status_code == 201
        agent = made.json()
        assert agent["id"] == "cells"
        assert agent["steps"] == dict.fromkeys(STEPS, "pending")

        listed = client.get("/api/paperagents").json()
        assert [item["id"] for item in listed["agents"]] == ["cells"]
        assert listed["max_agents"] == module.MAX_AGENTS
        assert client.get("/api/paperagents/cells").json() == agent

        deleted = client.delete("/api/paperagents/cells")
        assert deleted.status_code == 200
        assert deleted.json()["agents"] == []
        assert client.get("/api/paperagents/cells").status_code == 404

    def test_a_paper_that_has_an_agent_is_refused_with_which(self, client: TestClient) -> None:
        self.make(client, title="Cells")

        again = self.make(client, title="Again")

        assert again.status_code == 409
        assert again.json()["error"]["code"] == "exists"
        assert again.json()["error"]["existing"] == "cells"

    def test_what_is_not_fit_is_refused_and_so_is_what_is_not_asked_for(self, client: TestClient) -> None:
        assert client.post("/api/paperagents", json={"paper": {"kind": "doi", "doi": "nope"}}).status_code == 422
        assert client.post("/api/paperagents", json={"paper": {"kind": "file"}}).status_code == 422
        assert self.make(client, repo="https://example.org/a/b").status_code == 422
        assert self.make(client, surprise=1).status_code == 422
        assert (
            client.post("/api/paperagents", json={"paper": {"kind": "doi", "doi": DOI, "extra": 1}}).status_code == 422
        )
        assert client.post("/api/paperagents", json={}).status_code == 422
        assert client.get("/api/paperagents").json()["agents"] == []

    def test_the_title_and_the_code_are_said_again(self, client: TestClient) -> None:
        self.make(client, title="Cells")

        changed = client.patch(
            "/api/paperagents/cells", json={"title": "Cells again", "repo": "https://github.com/a/b"}
        )
        assert changed.status_code == 200
        assert changed.json()["title"] == "Cells again"
        assert changed.json()["repo"] == {"url": "https://github.com/a/b"}

        cleared = client.patch("/api/paperagents/cells", json={"repo": ""})
        assert cleared.json()["repo"] is None
        assert cleared.json()["title"] == "Cells again"

        assert client.patch("/api/paperagents/cells", json={}).status_code == 422
        assert client.patch("/api/paperagents/cells", json={"nope": 1}).status_code == 422
        assert client.patch("/api/paperagents/missing", json={"title": "x"}).status_code == 404

    def test_a_paper_is_uploaded_replaced_and_taken_away(self, client: TestClient) -> None:
        client.post("/api/paperagents", json={"title": "Upload", "paper": {"kind": "file"}})

        put = client.post("/api/paperagents/upload/paper?name=a.txt", content=TEXT)
        assert put.status_code == 200
        assert put.json()["paper"]["file"] == {
            "name": "a.txt",
            "bytes": len(TEXT),
            "sha256": hashlib.sha256(TEXT).hexdigest(),
        }

        again = client.post("/api/paperagents/upload/paper?name=b.md", content=b"Another paper.")
        assert again.json()["paper"]["file"]["name"] == "b.md"

        removed = client.delete("/api/paperagents/upload/paper")
        assert removed.status_code == 200
        assert removed.json()["paper"] == {"kind": "file", "file": None}
        assert client.delete("/api/paperagents/upload/paper").status_code == 404

    def test_a_paper_that_is_too_big_is_refused_by_its_size_before_it_is_read(self, client: TestClient) -> None:
        client.post("/api/paperagents", json={"title": "Upload", "paper": {"kind": "file"}})

        refused_by_size = client.post("/api/paperagents/upload/paper?name=a.txt", content=b"x" * (LIMIT + 1))

        assert refused_by_size.status_code == 413
        assert refused_by_size.json()["error"]["code"] == "too_large"

    def test_a_paper_is_not_uploaded_without_a_name_or_to_an_agent_that_is_not_there(self, client: TestClient) -> None:
        client.post("/api/paperagents", json={"title": "Upload", "paper": {"kind": "file"}})

        assert client.post("/api/paperagents/upload/paper", content=TEXT).status_code == 422
        assert client.post("/api/paperagents/missing/paper?name=a.txt", content=TEXT).status_code == 404

    def test_a_request_without_the_token_is_refused(self, workspace: Workspace) -> None:
        app = create_app(workspace.root, token=TOKEN, check_keys=False, max_upload_bytes=LIMIT)
        with TestClient(app, base_url=LOCAL) as bare:
            assert bare.get("/api/paperagents").status_code == 401
            assert bare.post("/api/paperagents", json={"paper": {"kind": "doi", "doi": DOI}}).status_code == 401
