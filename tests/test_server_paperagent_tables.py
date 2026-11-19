"""Tests of the tables of an agent's claims and variants, as the server gives them: that they are made from what is kept
with nothing run and no model asked, that a row is there for each claim of the paper and for each variant, that what a
variant came to is beside the claim's own result and is said not to be the paper's, that a claim that is stale is shown
to be and given nothing of what an earlier trying said, and what the request is answered with."""

import csv
import io

import test_server_paperagent_variants as made
from conftest import FakeClient
from fastapi.testclient import TestClient
from test_server_paperagent_environment import LOCAL, directory_of
from test_server_paperagent_reference import why
from test_server_paperagent_reproduction import GOT, SCRIPT
from test_server_paperagent_tools import Replays

from virtual_lab.paperagents import reporting, reproducing, varying
from virtual_lab.server import paperagent_reproduction as kept_reproduction
from virtual_lab.server.paperagents import PaperAgents
from virtual_lab.server.workspace import Workspace

# What the tests of making a variant are made with, which are fixtures of that module
agents = made.agents
built = made.built
client = made.client
containers = made.containers
docker = made.docker
git_is_installed = made.git_is_installed
jobs = made.jobs
mapped = made.mapped
marker = made.marker
ran = made.ran
ready = made.ready
remote = made.remote
replays = made.replays
small_chunks = made.small_chunks
tried = made.tried
varied = made.varied
workspace = made.workspace


def read(agents: PaperAgents, agent_id: str, kind: str) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    """A table as a spreadsheet would read it: its header, and each row by the name of its column."""
    _, content = agents.table(agent_id, kind)
    rows = list(csv.reader(io.StringIO(content.decode("utf-8"))))

    return tuple(rows[0]), [dict(zip(rows[0], row, strict=True)) for row in rows[1:]]


def by_value(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """The rows by the number that the paper reports, and by "words" for the claim that is not one."""
    return {row["Paper reports"] or "words": row for row in rows}


def listing(workspace: Workspace, agent_id: str) -> list[tuple[str, int]]:
    root = directory_of(workspace, agent_id)

    return sorted((str(path.relative_to(root)), path.stat().st_size) for path in root.rglob("*") if path.is_file())


class TestTheClaims:
    def test_there_is_a_row_for_each_claim_of_the_paper_in_its_order(self, agents: PaperAgents, tried: str) -> None:
        header, rows = read(agents, tried, "claims")

        shown = agents.reproduction(tried)["claims"]
        assert header == reporting.CLAIM_COLUMNS
        assert [row["Claim"] for row in rows] == [each["id"] for each in shown]
        assert [row["Paper reports"] for row in rows] == [each["value"] for each in shown]
        assert [row["Sentence"] for row in rows] == [each["quote"] for each in shown]
        assert len(rows) >= 3

    def test_what_each_claim_came_to_and_was_held_to_is_the_same_as_is_shown(
        self, agents: PaperAgents, tried: str
    ) -> None:
        _, rows = read(agents, tried, "claims")
        shown = {each["id"]: each for each in agents.reproduction(tried)["claims"]}

        for row in rows:
            entry = shown[row["Claim"]]
            assert row["Status"] == reproducing.TITLES[entry["status"]]
            assert row["What it came to"] == entry["summary"]
            link = entry["link"]
            if link is None:
                assert (row["Tutorial"], row["Call"], row["What the tutorial gave"]) == ("", "", "")
                assert row["Why it was not attempted"] == reproducing.REASONS[entry["reason"]]
            else:
                assert (row["Tutorial"], row["Call"], row["Where in what it gave"]) == (
                    link["tutorial"]["path"],
                    str(link["call"]),
                    link["where"],
                )
                assert float(row["What the tutorial gave"]) == link["got"]
                assert row["Why it was not attempted"] == ""

    def test_the_claim_that_reproduced_and_the_one_that_did_not_and_the_one_not_attempted_are_each_said(
        self, agents: PaperAgents, tried: str
    ) -> None:
        _, rows = read(agents, tried, "claims")
        found = by_value(rows)

        assert found["0.93"]["Status"] == "Reproduced" and found["0.93"]["Tutorial"] == SCRIPT
        assert float(found["0.93"]["What the tutorial gave"]) == GOT
        assert found["0.88"]["Status"] == "Not reproduced"
        assert found["words"]["Status"] == "Not attempted"
        assert found["words"]["Why it was not attempted"] == reproducing.REASONS["not_a_number"]

    def test_where_a_claim_first_parts_and_what_differs_are_what_the_divergence_says(
        self, agents: PaperAgents, tried: str
    ) -> None:
        _, rows = read(agents, tried, "claims")
        looked = {each["id"]: each for each in agents.divergence(tried)["claims"]}

        assert any(each["point"] is not None for each in looked.values())
        for row in rows:
            each = looked.get(row["Claim"])
            point = each["point"]["text"] if each is not None and each["point"] is not None else ""
            differs = " ".join(one["text"] for one in each["differences"]) if each is not None else ""
            assert row["Where it first parts from the paper"] == point, row["Claim"]
            assert row["Differences found (not shown to be why)"] == differs, row["Claim"]

    def test_before_the_claims_are_tried_each_is_not_attempted_and_has_not_been_tried(
        self, agents: PaperAgents, varied: str
    ) -> None:
        _, rows = read(agents, varied, "claims")

        assert len(rows) >= 3
        assert {row["Status"] for row in rows} == {"Not attempted"}
        assert {row["Why it was not attempted"] for row in rows} == {reproducing.REASONS["not_tried"]}
        assert {row["Variants made"] for row in rows} == {"0"}

    def test_claims_that_were_tried_against_other_claims_are_stale_and_are_given_nothing_that_was_said(
        self, agents: PaperAgents, tried: str, workspace: Workspace
    ) -> None:
        made.trying.rewrite(workspace, tried, claims_sha256="0" * 64)

        _, rows = read(agents, tried, "claims")

        stale = [row for row in rows if row["Status"].startswith("Stale")]
        assert {row["Status"] for row in stale} >= {"Stale (was Reproduced)", "Stale (was Not reproduced)"}
        for row in stale:
            for column in reporting.CLAIM_COLUMNS[4:12]:
                assert row[column] == "", (row["Claim"], column)
        assert kept_reproduction.STALE == reporting.STALE

    def test_how_many_variants_were_made_of_a_claim_is_counted_and_what_was_said_of_it_is_as_it_was(
        self, agents: PaperAgents, tried: str
    ) -> None:
        _, before = read(agents, tried, "claims")

        made.vary(agents, tried, {"scale": 3})
        made.vary(agents, tried, {"scale": 4})
        _, after = read(agents, tried, "claims")

        assert by_value(after)["0.93"]["Variants made"] == "2"
        assert [{**row, "Variants made": "0"} for row in after] == [{**row, "Variants made": "0"} for row in before]
        assert by_value(after)["0.93"]["Status"] == "Reproduced"


class TestTheVariants:
    def test_before_any_is_made_there_is_a_header_and_no_row(self, agents: PaperAgents, tried: str) -> None:
        header, rows = read(agents, tried, "variants")

        assert header == reporting.VARIANT_COLUMNS and rows == []

    def test_each_variant_is_a_row_beside_the_claim_s_own_result_and_is_not_the_paper_s(
        self, agents: PaperAgents, tried: str
    ) -> None:
        made.vary(agents, tried, {"scale": 3}, note="What if the scale were three?")
        made.vary(agents, tried, {"scale": 4})

        header, rows = read(agents, tried, "variants")

        shown = made.made_of(agents, tried)
        assert header == reporting.VARIANT_COLUMNS and len(rows) == 2
        assert [row["Made"] for row in rows] == [each["made_at"] for each in shown]
        first = rows[0]
        assert first["Claim"] == made.claim_of(agents, tried) and first["Paper reports"] == "0.93"
        assert first["The claim's own result"] == "Reproduced"
        assert first["Changed"] == "scale = 3 in place of 2"
        assert first["The call with nothing changed"] == "Gave what the tutorial got"
        assert first["The variant"] == "Gave a number"
        assert float(first["Number the tutorial's call gave"]) == GOT
        assert float(first["Number with nothing changed"]) == GOT
        assert float(first["Number the variant gave"]) == GOT * 3 / 2
        assert (first["Comparable"], first["Rounds to the paper's number"]) == ("Yes", "No")
        assert first["Is it the paper's result"] == "No" and first["Note"] == "What if the scale were three?"
        assert all(row["What it came to"].endswith(varying.CLOSING) for row in rows)

    def test_a_variant_of_another_trying_is_not_given(
        self, agents: PaperAgents, tried: str, workspace: Workspace
    ) -> None:
        made.vary(agents, tried, {"scale": 3})
        made.trying.rewrite(workspace, tried, started_at="2000-01-01T00:00:00Z")

        _, rows = read(agents, tried, "variants")

        assert rows == []

    def test_a_call_that_stopped_and_one_that_was_not_comparable_are_said_so(
        self, agents: PaperAgents, tried: str, replays: Replays
    ) -> None:
        replays.plays["lumi_direct"] = lambda case, repeat: (
            made.stopped_with("ValueError", "scale must be small")
            if case["args"]["scale"] == 99
            else made.gave(GOT + 1)
        )

        made.vary(agents, tried, {"scale": 99})
        made.vary(agents, tried, {"scale": 3})

        _, rows = read(agents, tried, "variants")
        stopped, different = rows
        assert stopped["The variant"] == "Stopped with an error" and stopped["Number the variant gave"] == ""
        assert different["The call with nothing changed"] == "Did not give what the tutorial got"
        assert (different["Comparable"], different["Is it the paper's result"]) == ("No", "No")


class TestWhatItTakes:
    def test_nothing_is_run_nothing_is_asked_and_nothing_is_kept_to_make_one(
        self, agents: PaperAgents, tried: str, replays: Replays, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        before = listing(workspace, tried)
        asked = len(fake_client.completions.calls)

        for kind in reporting.KINDS:
            agents.table(tried, kind)

        assert replays.runs == [] and len(fake_client.completions.calls) == asked
        assert listing(workspace, tried) == before

    def test_a_table_that_is_not_one_or_an_agent_that_is_not_there_is_not_found(
        self, agents: PaperAgents, tried: str
    ) -> None:
        for kind in ("", "claim", "Claims", "../claims", "variants.csv"):
            assert why(agents.table, tried, kind) == (404, "not_found"), kind
        assert why(agents.table, "nothing", "claims") == (404, "not_found")

    def test_the_file_is_named_for_the_agent_and_the_table(self, agents: PaperAgents, tried: str) -> None:
        name, content = agents.table(tried, "claims")

        assert name == f"{agents.lookup(tried)[1]['title']} - claims"
        assert content.startswith(",".join(reporting.CLAIM_COLUMNS[:3]).encode())


class TestOverHttp:
    def test_a_table_is_sent_to_be_saved_as_a_file_that_a_spreadsheet_opens(
        self, client: TestClient, agents: PaperAgents, tried: str
    ) -> None:
        made.vary(agents, tried, {"scale": 3})

        for kind, columns in (("claims", reporting.CLAIM_COLUMNS), ("variants", reporting.VARIANT_COLUMNS)):
            response = client.get(f"/api/paperagents/{tried}/tables/{kind}")

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/csv; charset=utf-8"
            disposition = response.headers["content-disposition"]
            assert disposition.startswith("attachment;") and f"{kind}.csv" in disposition
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["cache-control"] == "no-store"
            rows = list(csv.reader(io.StringIO(response.text)))
            assert tuple(rows[0]) == columns and len(rows) >= 2

    def test_what_is_not_there_is_not_found_and_what_is_not_asked_for_with_the_token_is_not_given(
        self, client: TestClient, tried: str
    ) -> None:
        assert client.get(f"/api/paperagents/{tried}/tables/other").status_code == 404
        assert client.get("/api/paperagents/nothing/tables/claims").status_code == 404
        bare = TestClient(client.app, base_url=LOCAL)
        assert bare.get(f"/api/paperagents/{tried}/tables/claims").status_code == 401

    def test_it_is_only_a_read_of_what_is_kept(self, client: TestClient, tried: str, workspace: Workspace) -> None:
        before = listing(workspace, tried)

        for kind in reporting.KINDS:
            assert client.get(f"/api/paperagents/{tried}/tables/{kind}").status_code == 200

        assert listing(workspace, tried) == before
