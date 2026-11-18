"""Tests of looking at the claims that did not reproduce, as the server does it: that it is of a trying of the
claims that is of what is kept now, that a claim that did not reproduce is named with the first output of its tutorial
that parts from the paper and a claim that did is not listed, that what differs between what the paper says it used and
what was used here is found from what is kept, that nothing is run, asked, or written by asking for it, and that what
is kept and is not in the shape that is written adds nothing. Docker and its containers are replaced by stand-ins, as in
the tests of running the tutorials."""

import json
from pathlib import Path
from typing import Any

import pytest
import test_server_paperagent_reproduction as trying
from conftest import FakeClient
from fastapi.testclient import TestClient
from test_paperagents_reading import RESULT
from test_paperagents_reference import result_of
from test_server_paperagent_environment import LOCAL, Docker, directory_of
from test_server_paperagent_reference import NOTEBOOK, SCRIPT, Containers, run, why, writes
from test_server_paperagent_reproduction import BASELINE, GOT, PAPER, SEURAT, TALLY, pick, read_paper, reproduce
from test_server_paperagent_tools import call

from virtual_lab.paperagents import diverging
from virtual_lab.server import paperagent_divergence as kept_divergence
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server import paperagent_reproduction as kept_reproduction
from virtual_lab.server.paperagents import PaperAgents, kept_tools_of
from virtual_lab.server.workspace import Workspace

# What the tests of trying the claims are made with, which are fixtures of that module
agents = trying.agents
built = trying.built
client = trying.client
containers = trying.containers
docker = trying.docker
git_is_installed = trying.git_is_installed
jobs = trying.jobs
marker = trying.marker
ran = trying.ran
ready = trying.ready
remote = trying.remote
small_chunks = trying.small_chunks
workspace = trying.workspace

# The places that a model is told to choose by, which are named in full as the same tutorial gave the same calls
TALLIED = f"{SCRIPT}: a call of cellmapper.mapping.tally("
AUROCED = f"{SCRIPT}: a call of cellmapper.mapping.auroc("
ZERO = {"python": 0, "package": 0, "data": 0, "runs": 0, "seed": 0, "argument": 0}


def tried_both(agents: PaperAgents, agent_id: str, fake_client: FakeClient) -> None:
    """Tries the claims, with the 0.93 held to what the script gave for tally, which it did, and the 0.88 to what it
    gave for auroc, which it did not."""
    pick(fake_client, TALLIED, AUROCED)
    job = reproduce(agents, agent_id)
    assert job.state == "succeeded", job.error


def keep_file(workspace: Workspace, agent_id: str, name: str, value: Any) -> None:
    (directory_of(workspace, agent_id) / name).write_text(json.dumps(value))


def listing(directory: Path) -> list[tuple[str, int]]:
    return sorted(
        (str(path.relative_to(directory)), path.stat().st_mtime_ns) for path in directory.rglob("*") if path.is_file()
    )


class TestWhenItIsAsFor:
    def test_there_is_nothing_to_look_at_before_the_claims_are_tried(self, agents: PaperAgents, ready: str) -> None:
        shown = agents.divergence(ready)

        assert (shown["ready"], shown["problem"]["code"], shown["current"]) == (False, "no_reproduction", False)
        assert (shown["claims"], shown["software"], shown["differences"], shown["run"]) == ([], [], [], None)
        assert shown["counts"] == {"claims": 0, "points": 0, "differences": ZERO}
        assert shown["meaning"] == diverging.MEANING and "not a cause" in shown["meaning"]
        json.dumps(shown)

    def test_a_trying_of_other_claims_or_another_run_of_the_tutorials_is_not_looked_at(
        self, agents: PaperAgents, ready: str, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        tried_both(agents, ready, fake_client)
        path = kept_reproduction.record_path(directory_of(workspace, ready))
        path.write_text(json.dumps({**json.loads(path.read_text()), "claims_sha256": "0" * 64}))

        shown = agents.divergence(ready)

        assert (shown["ready"], shown["problem"]["code"], shown["current"]) == (False, "stale", False)
        assert shown["claims"] == [] and shown["reproduction"] is None

    def test_an_agent_that_is_not_there_is_refused(self, agents: PaperAgents) -> None:
        assert why(agents.divergence, "nothing") == (404, "not_found")


class TestWhereItParts:
    def test_a_claim_that_did_not_reproduce_is_named_with_the_first_output_that_parts_and_one_that_did_is_not_listed(
        self, agents: PaperAgents, ready: str, fake_client: FakeClient
    ) -> None:
        tried_both(agents, ready, fake_client)
        assert trying.statuses(agents, ready)["0.93"] == "reproduced"
        assert trying.statuses(agents, ready)["0.88"] == "not_reproduced"

        shown = agents.divergence(ready)

        assert (shown["ready"], shown["problem"], shown["current"]) == (True, None, True)
        [claim] = shown["claims"]
        assert (claim["value"], claim["status"], claim["tutorial"], claim["quote"]) == (
            "0.88",
            "not_reproduced",
            SCRIPT,
            BASELINE,
        )
        point = claim["point"]
        assert point["ordered"] is True and point["first"]["call"] == 3
        assert (point["first"]["got"], point["first"]["number"], point["first"]["quote"]) == (SEURAT, "0.88", BASELINE)
        assert "auroc" in point["first"]["where"]
        # The tutorial agreed with the paper at the call before it
        assert point["agreed_count"] == 1
        assert (point["agreed"][0]["got"], point["agreed"][0]["number"], point["agreed"][0]["call"]) == (GOT, "0.93", 2)
        assert point["text"].startswith(
            f"In {SCRIPT}, the first output, in the order that it made its calls, that parts"
        )
        assert f"it gave {SEURAT}, and the paper reports 0.88." in point["text"]
        assert shown["counts"] == {"claims": 1, "points": 1, "differences": ZERO}
        assert shown["reproduction"] == agents.reproduction(ready)["reference"] is not None
        json.dumps(shown)

    def test_what_the_run_was_made_in_is_said(self, agents: PaperAgents, ready: str, fake_client: FakeClient) -> None:
        tried_both(agents, ready, fake_client)

        shown = agents.divergence(ready)

        assert shown["run"] == {"python": "3.11.9", "packages": 2, "data": None, "tutorials": 1}

    def test_nothing_is_run_asked_or_written_by_asking_for_it(
        self, agents: PaperAgents, ready: str, fake_client: FakeClient, workspace: Workspace, containers: Containers
    ) -> None:
        tried_both(agents, ready, fake_client)
        directory = directory_of(workspace, ready)
        before = (listing(directory), len(fake_client.completions.calls), len(containers.runs))

        agents.divergence(ready)
        agents.divergence(ready)

        assert (listing(directory), len(fake_client.completions.calls), len(containers.runs)) == before

    def test_a_tutorial_whose_record_is_gone_still_has_its_point_and_no_differences_of_its_runs(
        self, agents: PaperAgents, ready: str, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        tried_both(agents, ready, fake_client)
        first = agents.divergence(ready)["claims"][0]["point"]["first"]
        for detail in (directory_of(workspace, ready) / "checks" / "reference").glob("*/detail.json"):
            detail.unlink()

        shown = agents.divergence(ready)

        assert shown["claims"][0]["point"]["first"] == first
        assert shown["claims"][0]["differences"] == [] and shown["run"]["tutorials"] == 0


class TestWhatDiffers:
    def test_what_the_paper_says_it_used_and_what_was_used_are_put_together_from_what_is_kept(
        self,
        agents: PaperAgents,
        ran: str,
        fake_client: FakeClient,
        workspace: Workspace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(trying, "PAPER", PAPER + "\n\nThe tally used scale = 5, as in the methods.")
        read_paper(agents, ran, fake_client)
        keep_file(
            workspace,
            ran,
            "resources.json",
            {
                "schema": 1,
                "software": [
                    {"id": "sw-1", "name": "numpy", "version": "1.20", "quote": "numpy 1.20"},
                    {"id": "sw-2", "name": "Python", "version": "3.8", "quote": "Python 3.8"},
                    {"id": "sw-3", "name": "six", "version": "1.16", "quote": "six 1.16"},
                    {"id": "sw-4", "name": "Seurat", "version": "4.3", "quote": "Seurat 4.3"},
                ],
            },
        )
        keep_file(
            workspace,
            ran,
            "method_card.json",
            {"schema": 1, "datasets": [{"id": "d-1", "name": "PBMC", "accession": "GSE1", "quote": "PBMC (GSE1)"}]},
        )
        tried_both(agents, ran, fake_client)

        shown = agents.divergence(ran)

        assert [each["kind"] for each in shown["differences"]] == ["package", "python", "data"]
        assert {each["name"]: each["state"] for each in shown["software"]} == {
            "numpy": "differs",
            "Python": "differs",
            "six": "same",
            "Seurat": "not_installed",
        }
        assert shown["differences"][0]["text"] == "The paper names numpy 1.20, and 1.26.4 is installed here."
        assert shown["differences"][1]["text"] == "The paper names Python 3.8, and 3.11.9 is installed here."
        [claim] = shown["claims"]
        [argument] = claim["differences"]
        assert argument["kind"] == "argument"
        assert argument["text"] == "The paper gives scale as 5, and the call of tally was given 2."
        assert "scale = 5" in argument["quote"]
        assert shown["counts"]["differences"] == {**ZERO, "python": 1, "package": 1, "data": 1, "argument": 1}

    def test_runs_that_did_not_agree_are_a_difference_for_a_claim_that_is_partly_for_that(
        self, agents: PaperAgents, built: str, containers: Containers, fake_client: FakeClient
    ) -> None:
        containers.plays[NOTEBOOK] = writes(result_of(calls=trying.CALLED[:1]))
        containers.plays[SCRIPT] = lambda count, folder, item: writes(
            result_of(
                calls=[
                    trying.CALLED[0],
                    call("tally", {"counts": [1, 2, 3], "scale": 2}, GOT if count == 1 else 0.5, 2),
                ]
            )
        )(count, folder, item)
        run(agents, built, repeats=2)
        read_paper(agents, built, fake_client, [("number", "0.93", RESULT)])
        pick(fake_client, TALLY)
        reproduce(agents, built)

        shown = agents.divergence(built)

        [claim] = shown["claims"]
        assert claim["status"] == "partly" and claim["point"] is None
        assert [each["kind"] for each in claim["differences"]] == ["runs", "seed"]
        assert claim["differences"][0]["text"] == "The 2 runs of the tutorial did not give the same calls."
        assert shown["counts"] == {"claims": 1, "points": 0, "differences": {**ZERO, "runs": 1, "seed": 1}}

    def test_files_of_the_reading_that_are_not_in_the_shape_that_is_written_add_nothing(
        self, agents: PaperAgents, ready: str, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        tried_both(agents, ready, fake_client)
        for value in (
            [],
            "text",
            {"software": "numpy"},
            {
                "software": [
                    3,
                    None,
                    {"name": 5, "version": "1", "quote": "q"},
                    {"name": "numpy"},
                    {"name": " ", "version": "1", "quote": "q"},
                    {"name": "", "version": "", "quote": ""},
                ]
            },
            {"software": [{"name": "numpy", "version": 1, "quote": "q"}], "datasets": {"x": 1}},
        ):
            keep_file(workspace, ready, "resources.json", value)
            keep_file(workspace, ready, "method_card.json", value)

            shown = agents.divergence(ready)

            assert shown["software"] == [] and shown["differences"] == [], value
            assert [each["value"] for each in shown["claims"]] == ["0.88"]
        (directory_of(workspace, ready) / "resources.json").write_text("{not json")
        assert agents.divergence(ready)["software"] == []

    def test_an_environment_that_is_not_the_image_that_the_tutorials_were_run_in_is_not_looked_at(
        self, agents: PaperAgents, ready: str, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        tried_both(agents, ready, fake_client)
        directory = directory_of(workspace, ready)
        reference = agents.reproduction(ready)["reference"]

        assert kept_divergence.environment_of(directory, reference) == ("3.11.9", "numpy==1.26.4\nsix==1.16.0\n")
        assert kept_divergence.environment_of(directory, {**reference, "image_id": "sha256:" + "9" * 64}) == (
            None,
            None,
        )
        assert kept_divergence.environment_of(directory, {**reference, "commit": "f" * 40}) == (None, None)

    def test_no_more_of_the_facts_and_of_the_paper_are_read_than_the_limits_say(
        self,
        agents: PaperAgents,
        ready: str,
        fake_client: FakeClient,
        workspace: Workspace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        tried_both(agents, ready, fake_client)
        directory = directory_of(workspace, ready)
        facts = [{"id": f"sw-{number}", "name": f"pkg{number}", "version": "1", "quote": "q"} for number in range(3)]
        keep_file(workspace, ready, "resources.json", {"software": facts})
        monkeypatch.setattr(kept_divergence, "MOST_FACTS", 2)
        assert [each["name"] for each in kept_divergence.software_of(directory)] == ["pkg0", "pkg1"]
        monkeypatch.setattr(diverging, "MAX_PAPER_CHARS", 20)
        whole = kept_divergence.paper_text(directory / "paper")
        assert whole is not None and len(whole) == 20

    def test_only_the_tutorials_of_the_claims_that_did_not_reproduce_are_read_and_the_data_given_is_kept(
        self, agents: PaperAgents, ready: str, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        tried_both(agents, ready, fake_client)
        directory, agent = agents.lookup(ready)
        reference, _ = kept_tools_of(directory, agent)
        record = kept_reproduction.load(directory)
        assert reference is not None and record is not None
        other = next(each for each in reference["tutorials"] if each["path"] != SCRIPT)
        reproduced, failed = record["claims"][0], record["claims"][1]
        assert (reproduced["status"], failed["status"]) == ("reproduced", "not_reproduced")
        link = {
            **reproduced["link"],
            "tutorial": {**reproduced["link"]["tutorial"], "id": other["id"], "path": other["path"]},
        }
        data = {"given": ["x"]}

        found = kept_divergence.evidence_of(
            directory,
            directory / "paper",
            {**reference, "data": data},
            {**record, "claims": [{**reproduced, "link": link}, failed]},
            kept_repository.repo_path(directory),
        )

        assert list(found.details) == [SCRIPT] and found.data == data

    def test_the_paper_text_that_is_not_kept_is_not_looked_in(
        self, agents: PaperAgents, ready: str, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        tried_both(agents, ready, fake_client)
        directory = directory_of(workspace, ready)
        assert kept_divergence.paper_text(directory / "paper") is not None
        (directory / "paper" / "text.txt").unlink()
        assert kept_divergence.paper_text(directory / "paper") is None
        assert agents.divergence(ready)["claims"][0]["point"] is not None


class TestOverHttp:
    def test_it_is_asked_for_by_an_agent_and_not_without_the_token_or_for_one_that_is_not_there(
        self, client: TestClient, docker: Docker
    ) -> None:
        made = client.post(
            "/api/paperagents",
            json={"title": "CellMapper", "paper": {"kind": "doi", "doi": "10.1038/s41586-020-2649-2"}},
        )
        base = f"/api/paperagents/{made.json()['id']}/divergence"

        shown = client.get(base)

        assert shown.status_code == 200
        assert (shown.json()["ready"], shown.json()["problem"]["code"]) == (False, "no_reproduction")
        assert client.get("/api/paperagents/nothing/divergence").status_code == 404
        bare = TestClient(client.app, base_url=LOCAL)
        assert bare.get(base).status_code == 401
        assert client.post(base, json={}).status_code == 405
        assert client.delete(base).status_code == 405
