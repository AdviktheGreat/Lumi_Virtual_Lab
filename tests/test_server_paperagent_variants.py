"""Tests of making a variant of a PaperAgent's claim, as the server does it: that one is made only of a claim that was
tried and was held to a call, and only of a trying of the claims that is of what is kept now, that the call is made in
the environment as the code's own function with nothing changed and with the changes, what is kept and that it is kept
beside the claim and never in place of what was said of it, what the variants are bound to and when they are stale, that
what is kept and is not in the shape that is written adds nothing, and what the other operations do while one is made.
Docker and its containers are replaced by stand-ins, as in the tests of making tools, so what is looked at is what the
server does with what they gave; the real calls are in test_paperagents_varying."""

import copy
import json
import shutil
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import test_server_paperagent_reproduction as trying
import test_server_paperagent_tools as tools
from conftest import FakeClient
from fastapi.testclient import TestClient
from test_paperagents_reference import result_of
from test_server_paperagent_environment import LOCAL, Docker, Remote, agent_of, directory_of, finish, refused
from test_server_paperagent_reference import NOTEBOOK, SCRIPT, Containers, keep_data, run, why, writes
from test_server_paperagent_reproduction import GOT, pick, read_paper, reproduce
from test_server_paperagent_tools import MAPPING, Replays, value_of

from virtual_lab.execution import DockerUnavailableError
from virtual_lab.paperagents import reference as referencing
from virtual_lab.paperagents import varying
from virtual_lab.server import paperagent_data as kept_data
from virtual_lab.server import paperagent_reading as kept_reading
from virtual_lab.server import paperagent_reference as kept_reference
from virtual_lab.server import paperagent_reproduction as kept_reproduction
from virtual_lab.server import paperagent_variants as kept_variants
from virtual_lab.server.paperagents import VARIANT_JOB, PaperAgents, kept_tools_of
from virtual_lab.server.workspace import Workspace

# What the tests of trying the claims are made with, which are fixtures of that module, and of making tools
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
replays = tools.replays
small_chunks = trying.small_chunks
workspace = trying.workspace

# The places that a model is told to choose by, which are named in full as the same tutorial gave the same calls
TALLIED = f"{SCRIPT}: a call of cellmapper.mapping.tally("
AUROCED = f"{SCRIPT}: a call of cellmapper.mapping.auroc("
CAUSE_WORDS = ("because", "caused", "due to", "the reason", "proves", "verified")
# What the tutorial's call of tally gave, which is the 0.93 of the paper rounded
SAME_CALL = {"counts": [1, 2, 3], "scale": 2}


def scaled(case: dict[str, Any], repeat: int) -> dict[str, Any]:
    """What the code's own function gives here: what the tutorial got when the call is as the tutorial made it, and in
    proportion to the scale when it is not."""
    return gave(GOT * case["args"]["scale"] / 2)


def gave(value: Any) -> dict[str, Any]:
    return {"schema": 1, "ok": True, "error": None, "result": value_of(value), "seconds": 0.1, "output": ""}


def stopped_with(kind: str, message: str) -> dict[str, Any]:
    return {
        "schema": 1,
        "ok": False,
        "error": {"type": kind, "message": message, "traceback": [f"{kind}: {message}"], "cell": None},
        "result": None,
        "seconds": 0.1,
        "output": "",
    }


@pytest.fixture
def mapped(remote: Remote) -> None:
    """The code has the module that the tutorials' calls were of, so that a function can be read from it."""
    remote.files = {**remote.files, "cellmapper/mapping.py": MAPPING}


@pytest.fixture
def varied(mapped: None, ready: str, replays: Replays) -> str:
    """An agent whose tutorials were run, whose paper was read, and whose code has the functions that were called."""
    replays.plays["lumi_direct"] = scaled

    return ready


@pytest.fixture
def tried(agents: PaperAgents, varied: str, fake_client: FakeClient) -> str:
    """The same agent, whose claims were tried: the 0.93 was held to what the tutorial's call of tally gave and the
    0.88 to what its call of auroc did, which the code that was fetched does not have."""
    pick(fake_client, TALLIED, AUROCED)
    job = reproduce(agents, varied)
    assert job.state == "succeeded", job.error

    return varied


def claim_of(agents: PaperAgents, agent_id: str, value: str = "0.93") -> str:
    return trying.tried(agents, agent_id)[value]["id"]


def vary(agents: PaperAgents, agent_id: str, changes: dict[str, Any] | None = None, **options: Any) -> Any:
    claim = options.pop("claim", None) or claim_of(agents, agent_id)

    return finish(agents.start_variant(agent_id, claim, changes if changes is not None else {"scale": 3}, **options))


def kept_path(workspace: Workspace, agent_id: str) -> Path:
    return kept_variants.record_path(directory_of(workspace, agent_id))


def made_of(agents: PaperAgents, agent_id: str) -> list[dict[str, Any]]:
    return agents.variants(agent_id)["variants"]


def reproduction_bytes(workspace: Workspace, agent_id: str) -> bytes:
    return kept_reproduction.record_path(directory_of(workspace, agent_id)).read_bytes()


class TestWhenOneCanBeMade:
    def test_nothing_can_be_varied_before_the_claims_are_tried(
        self, agents: PaperAgents, varied: str, replays: Replays
    ) -> None:
        shown = agents.variants(varied)

        assert (shown["ready"], shown["problem"]["code"]) == (False, "no_reproduction")
        assert (shown["claims"], shown["variants"], shown["stale"], shown["job"]) == ([], [], 0, None)
        assert shown["counts"] == {"variants": 0, "comparable": 0, "rounds_to_paper": 0}
        assert shown["reproduction"] is None
        assert "not the paper's" in shown["meaning"] and "not a reproduction" in shown["meaning"]
        limits = shown["limits"]
        assert (limits["most_changes"], limits["default_repeats"], limits["max_minutes"]) == (5, 2, 30)
        claim = kept_reading.claims_of(directory_of(agents.workspace, varied))[0]["id"]
        assert why(agents.start_variant, varied, claim, {"scale": 3}) == (422, "no_reproduction")
        assert replays.runs == []
        json.dumps(shown)

    def test_a_claim_that_the_paper_does_not_have_is_not_found(self, agents: PaperAgents, tried: str) -> None:
        assert why(agents.start_variant, tried, "claim-nothing", {"scale": 3}) == (404, "not_found")
        assert why(agents.variants, "nothing") == (404, "not_found")
        assert why(agents.start_variant, "nothing", "claim-nothing", {"scale": 3}) == (404, "not_found")
        assert why(agents.clear_variants, "nothing") == (404, "not_found")

    def test_it_is_for_a_trying_of_the_claims_that_is_of_what_is_kept_now(
        self, agents: PaperAgents, tried: str, workspace: Workspace, replays: Replays
    ) -> None:
        trying.rewrite(workspace, tried, claims_sha256="0" * 64)

        shown = agents.variants(tried)

        assert (shown["ready"], shown["problem"]["code"], shown["claims"]) == (False, "stale", [])
        assert why(agents.start_variant, tried, claim_of(agents, tried, "0.93"), {"scale": 3}) == (409, "stale")
        assert replays.runs == []

    def test_the_tutorials_must_have_been_run_first(
        self, agents: PaperAgents, built: str, fake_client: FakeClient, replays: Replays
    ) -> None:
        read_paper(agents, built, fake_client)
        claim = kept_reading.claims_of(directory_of(agents.workspace, built))[0]["id"]

        assert why(agents.start_variant, built, claim, {"scale": 3}) == (422, "no_reference")
        assert agents.variants(built)["problem"]["code"] == "no_reproduction"
        assert replays.runs == []

    def test_the_code_must_have_been_fetched_and_the_environment_built(
        self, agents: PaperAgents, docker: Docker
    ) -> None:
        agent_id = agent_of(agents)

        assert why(agents.start_variant, agent_id, "claim-x", {"scale": 3}) == (422, "no_code")

    def test_docker_that_is_not_running_is_said_and_nothing_is_called(
        self, agents: PaperAgents, tried: str, docker: Docker, replays: Replays
    ) -> None:
        docker.usable = (False, "Docker is not running.")

        assert why(agents.start_variant, tried, claim_of(agents, tried), {"scale": 3}) == (422, "docker_missing")
        assert replays.runs == []

    @pytest.mark.parametrize(
        "options",
        [
            {"minutes": 0},
            {"minutes": 31},
            {"minutes": True},
            {"minutes": 1.5},
            {"repeats": 0},
            {"repeats": 4},
            {"gigabytes": 0},
            {"gigabytes": 21},
            {"note": "x" * (varying.MAX_NOTE_CHARS + 1)},
            {"note": "a\x00b"},
            {"note": 3},
            {"claim": ""},
            {"claim": 3},
        ],
    )
    def test_what_is_asked_that_is_not_fit_is_refused_before_anything_is_called(
        self, agents: PaperAgents, tried: str, replays: Replays, options: dict[str, Any]
    ) -> None:
        claim = options.pop("claim", claim_of(agents, tried))

        assert why(agents.start_variant, tried, claim, {"scale": 3}, **options) == (422, "invalid")
        assert replays.runs == [] and not kept_variants.record_path(directory_of(agents.workspace, tried)).exists()

    @pytest.mark.parametrize(
        ("changes", "said"),
        [
            ({}, "Name the arguments"),
            (None, "Name the arguments"),
            ({"nothing": 3}, "was not given an argument called nothing"),
            ({"scale": 2}, "so it is not a change"),
            ({"scale": float("nan")}, "not one that an argument is given as"),
            ({"scale": object()}, "not one that an argument is given as"),
            ({"counts": [1, 2, 3], "scale": 3, "a": 1, "b": 1, "c": 1, "d": 1}, "At most 5"),
        ],
    )
    def test_changes_that_are_not_fit_are_refused_with_why(
        self, agents: PaperAgents, tried: str, replays: Replays, changes: Any, said: str
    ) -> None:
        error = refused(agents.start_variant, tried, claim_of(agents, tried), changes)

        assert (error.status, error.code) == (422, "invalid") and said in error.message
        assert replays.runs == []

    def test_a_claim_that_was_not_attempted_has_no_call_to_make_again(
        self, agents: PaperAgents, tried: str, replays: Replays
    ) -> None:
        assert trying.statuses(agents, tried)["words"] == "not_attempted"

        assert why(agents.start_variant, tried, claim_of(agents, tried, "words"), {"scale": 3}) == (
            422,
            "not_attempted",
        )

    def test_a_claim_that_is_not_in_the_trying_was_not_tried(
        self, agents: PaperAgents, tried: str, workspace: Workspace
    ) -> None:
        claim = claim_of(agents, tried)
        record = trying.record_of(workspace, tried)
        trying.rewrite(workspace, tried, claims=[each for each in record["claims"] if each["id"] != claim])

        assert why(agents.start_variant, tried, claim, {"scale": 3}) == (422, "not_tried")

    def test_a_function_that_the_code_does_not_have_cannot_be_called_alone(
        self, agents: PaperAgents, tried: str, replays: Replays
    ) -> None:
        assert trying.statuses(agents, tried)["0.88"] == "not_reproduced"
        error = refused(agents.start_variant, tried, claim_of(agents, tried, "0.88"), {"method": "x"})

        assert (error.status, error.code) == (422, "cannot_call") and "cannot be read from the code" in error.message
        assert replays.runs == []

    def test_what_may_be_changed_of_each_claim_is_offered_or_why_not(self, agents: PaperAgents, tried: str) -> None:
        shown = agents.variants(tried)

        assert (shown["ready"], shown["problem"]) == (True, None)
        assert shown["reproduction"] == agents.reproduction(tried)["reference"] is not None
        by_claim = {each["claim"]: each for each in shown["claims"]}
        assert len(by_claim) == len(agents.reproduction(tried)["claims"])
        offered = by_claim[claim_of(agents, tried)]
        assert offered["can"] is True and offered["function"] == "cellmapper.mapping.tally"
        assert [(each["name"], each["value"], each["plain"]) for each in offered["arguments"]] == [
            ("counts", [1, 2, 3], True),
            ("scale", 2, True),
        ]
        assert by_claim[claim_of(agents, tried, "0.88")]["refused"]["code"] == "cannot_call"
        assert by_claim[claim_of(agents, tried, "words")]["refused"]["code"] == "not_attempted"
        assert shown["limits"] == {
            "most_changes": 5,
            "max_value_chars": 2000,
            "max_note_chars": 300,
            "most_kept": 100,
            "default_minutes": 5,
            "max_minutes": 30,
            "default_repeats": 2,
            "max_repeats": 3,
            "default_gigabytes": 2,
            "max_gigabytes": 20,
        }
        json.dumps(shown)

    def test_the_record_of_a_tutorial_is_read_once_however_many_claims_were_held_to_it(
        self, agents: PaperAgents, tried: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reads: list[str] = []
        read = kept_reference.load_detail
        monkeypatch.setattr(
            kept_reference,
            "load_detail",
            lambda directory, reference, tutorial: reads.append(tutorial) or read(directory, reference, tutorial),
        )
        held = [each["link"]["tutorial"]["id"] for each in agents.reproduction(tried)["claims"] if each["link"]]
        assert len(held) >= 2 and len(set(held)) < len(held)

        agents.variants(tried)

        assert sorted(reads) == sorted(set(held))


class TestMakingOne:
    def test_the_call_is_made_with_nothing_changed_and_with_the_changes_as_the_code_s_own_function(
        self, agents: PaperAgents, tried: str, replays: Replays, workspace: Workspace
    ) -> None:
        job = vary(agents, tried, {"scale": 3})

        assert job.state == "succeeded" and job.title.startswith("Making a variant of a claim")
        [seen] = replays.runs
        assert seen["function"] == "lumi_direct" and "import_module('cellmapper.mapping')" in seen["source"]
        assert [case["args"] for case in seen["cases"]] == [SAME_CALL, {"counts": [1, 2, 3], "scale": 3}]
        assert (seen["tag"], seen["label"], seen["data"]) == (trying.reference.tag_of(tried), tried, None)
        assert seen["repeats"] == 2 and 4 * 60 < seen["spec_seconds"] <= 5 * 60
        assert replays.functions() == ["lumi_direct"]

    def test_what_came_of_it_is_kept_as_a_variant_with_what_it_was_held_to(
        self, agents: PaperAgents, tried: str, workspace: Workspace
    ) -> None:
        vary(agents, tried, {"scale": 3}, note="What if the scale were three?")

        [made] = made_of(agents, tried)
        assert made["claim"] == claim_of(agents, tried) and made["number"] == "0.93"
        assert (made["function"], made["call"], made["claim_run"]) == ("cellmapper.mapping.tally", 2, GOT)
        assert made["tutorial"]["path"] == SCRIPT
        assert made["changes"] == [{"name": "scale", "was": 2, "now": 3}]
        assert (made["variant"]["status"], made["variant"]["gave"]) == ("gave", GOT * 3 / 2)
        assert made["control"] == {"verdict": "match", "gave": GOT, "differences": [], "error": None}
        assert (made["comparable"], made["rounds_to_paper"], made["note"]) == (
            True,
            False,
            "What if the scale were three?",
        )
        assert made["limits"] == {"minutes": 5, "repeats": 2, "gigabytes": 2} and made["repeats"] == 2
        assert (
            len(made["id"]) == 12
            and datetime.fromisoformat(made["made_at"]).tzinfo is not None
            and made["seconds"] >= 0
        )
        assert made["text"].endswith(varying.CLOSING)
        assert "With scale = 3 in place of 2" in made["text"]
        assert agents.variants(tried)["counts"] == {"variants": 1, "comparable": 1, "rounds_to_paper": 0}
        assert kept_variants.load(directory_of(workspace, tried)) is not None
        json.dumps(agents.variants(tried))

    def test_what_was_said_of_the_claim_is_not_changed(
        self, agents: PaperAgents, tried: str, workspace: Workspace
    ) -> None:
        before = (reproduction_bytes(workspace, tried), agents.reproduction(tried)["claims"])

        vary(agents, tried, {"scale": 3})
        vary(agents, tried, {"scale": 4})

        assert (reproduction_bytes(workspace, tried), agents.reproduction(tried)["claims"]) == before
        assert trying.statuses(agents, tried)["0.93"] == "reproduced"
        assert len(made_of(agents, tried)) == 2

    def test_a_variant_that_rounds_to_the_paper_s_number_is_said_to_and_the_claim_is_not_made_reproduced(
        self, agents: PaperAgents, tried: str, replays: Replays, workspace: Workspace
    ) -> None:
        replays.plays["lumi_direct"] = lambda case, repeat: gave(0.9304)
        before = agents.reproduction(tried)["claims"]

        vary(agents, tried, {"scale": 3})

        [made] = made_of(agents, tried)
        assert (made["rounds_to_paper"], made["comparable"]) == (True, False)
        assert made["control"]["verdict"] == "differs"
        replays.plays["lumi_direct"] = scaled
        vary(agents, tried, {"scale": 2.0})
        assert made_of(agents, tried)[-1]["rounds_to_paper"] is True
        assert "which is not a reproduction of the paper's result" in made_of(agents, tried)[-1]["text"]
        assert agents.reproduction(tried)["claims"] == before

    def test_a_call_that_does_not_give_what_the_tutorial_got_alone_is_not_comparable(
        self, agents: PaperAgents, tried: str, replays: Replays
    ) -> None:
        replays.plays["lumi_direct"] = lambda case, repeat: gave(GOT + 1 if case["args"]["scale"] == 2 else 5.0)

        vary(agents, tried, {"scale": 3})

        [made] = made_of(agents, tried)
        assert (made["control"]["verdict"], made["comparable"]) == ("differs", False)
        assert made["variant"]["gave"] == 5.0
        assert "did not give what the tutorial got" in made["text"] and "cannot be held to what it got" in made["text"]

    def test_a_call_that_stops_with_an_error_is_said_with_it(
        self, agents: PaperAgents, tried: str, replays: Replays
    ) -> None:
        replays.plays["lumi_direct"] = lambda case, repeat: (
            stopped_with("ValueError", "scale must be small") if case["args"]["scale"] == 99 else gave(GOT)
        )

        vary(agents, tried, {"scale": 99})

        [made] = made_of(agents, tried)
        assert made["variant"]["status"] == "error" and made["variant"]["error"]["type"] == "ValueError"
        assert made["comparable"] is False and made["control"]["verdict"] == "match"
        assert "stopped with ValueError: scale must be small" in made["text"]
        assert made["rounds_to_paper"] is None

    def test_how_long_how_many_times_and_how_much_may_be_written_are_what_the_person_allowed(
        self, agents: PaperAgents, tried: str, replays: Replays
    ) -> None:
        vary(agents, tried, {"scale": 3}, minutes=2, repeats=3, gigabytes=1)

        [seen] = replays.runs
        assert seen["repeats"] == 3 and 90 < seen["spec_seconds"] <= 2 * 60
        assert (seen["limits"].gigabytes, seen["limits"].repeats) == (1, 3)
        assert made_of(agents, tried)[0]["limits"] == {"minutes": 2, "repeats": 3, "gigabytes": 1}

    def test_the_data_that_the_tutorials_were_given_is_given_to_the_call_too(
        self,
        agents: PaperAgents,
        mapped: None,
        built: str,
        containers: Containers,
        fake_client: FakeClient,
        replays: Replays,
        workspace: Workspace,
    ) -> None:
        keep_data(workspace, built)
        containers.plays[NOTEBOOK] = containers.plays[SCRIPT] = writes(result_of(calls=trying.CALLED))
        run(agents, built, repeats=1)
        read_paper(agents, built, fake_client)
        replays.plays["lumi_direct"] = scaled
        pick(fake_client, TALLIED, AUROCED)
        assert reproduce(agents, built).state == "succeeded"

        vary(agents, built, {"scale": 3})
        data = replays.runs[-1]["data"]
        assert data is not None and data.name == "data"

        shutil.rmtree(kept_data.data_path(directory_of(workspace, built)))
        assert why(agents.start_variant, built, claim_of(agents, built), {"scale": 4}) == (409, "no_data")

    def test_docker_that_stops_answering_fails_the_job_and_keeps_nothing(
        self, agents: PaperAgents, tried: str, replays: Replays, workspace: Workspace
    ) -> None:
        replays.broken = DockerUnavailableError("Docker did not run the tool: Cannot connect to the Docker daemon")

        job = vary(agents, tried, {"scale": 3})

        assert job.state == "failed" and job.error is not None and "Cannot connect" in job.error
        assert made_of(agents, tried) == [] and not kept_path(workspace, tried).exists()

    def test_a_variant_that_is_stopped_keeps_nothing(
        self, agents: PaperAgents, tried: str, replays: Replays, workspace: Workspace
    ) -> None:
        replays.gates["lumi_direct"] = threading.Event()
        job = agents.start_variant(tried, claim_of(agents, tried), {"scale": 3})
        assert replays.began["lumi_direct"].wait(10)
        job.request_stop()
        finish(job)

        assert job.state == "stopped"
        assert made_of(agents, tried) == [] and not kept_path(workspace, tried).exists()
        assert agents.variants(tried)["job"] is None

    def test_what_came_of_it_is_put_in_the_job_s_output(self, agents: PaperAgents, tried: str) -> None:
        job = vary(agents, tried, {"scale": 3})

        [made] = made_of(agents, tried)
        assert job.snapshot(log_from=0)["log"]["lines"] == [made["text"]]

    def test_leftover_containers_of_the_agent_are_taken_away_before_the_calls(
        self, agents: PaperAgents, tried: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        removed: list[str] = []
        monkeypatch.setattr(referencing, "remove_runs", lambda agent_id, command: removed.append(agent_id))

        vary(agents, tried, {"scale": 3})

        assert removed == [tried]

    def test_how_many_of_them_are_comparable_and_round_to_the_paper_s_number_are_counted(
        self, agents: PaperAgents, tried: str, replays: Replays
    ) -> None:
        vary(agents, tried, {"scale": 3})
        replays.plays["lumi_direct"] = lambda case, repeat: gave(0.9304)
        vary(agents, tried, {"scale": 4})
        replays.plays["lumi_direct"] = scaled
        vary(agents, tried, {"scale": 2.0})

        assert [(made["comparable"], made["rounds_to_paper"]) for made in made_of(agents, tried)] == [
            (True, False),
            (False, True),
            (True, True),
        ]
        assert agents.variants(tried)["counts"] == {"variants": 3, "comparable": 2, "rounds_to_paper": 2}

    def test_variants_are_kept_in_the_order_that_they_were_made_and_the_oldest_go_beyond_the_most(
        self, agents: PaperAgents, tried: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kept_variants, "MOST_KEPT", 2)

        for scale in (3, 4, 5):
            vary(agents, tried, {"scale": scale})

        assert [made["changes"][0]["now"] for made in made_of(agents, tried)] == [4, 5]

    def test_what_is_said_of_a_variant_never_says_why(self, agents: PaperAgents, tried: str, replays: Replays) -> None:
        for play in (scaled, lambda case, repeat: stopped_with("ValueError", "bad")):
            replays.plays["lumi_direct"] = play
            vary(agents, tried, {"scale": 3})

        for made in made_of(agents, tried):
            assert not any(word in made["text"].lower() for word in CAUSE_WORDS), made["text"]


class TestWhileOneIsMade:
    def test_nothing_that_would_change_what_it_is_made_from_is_done_until_it_has_ended(
        self, agents: PaperAgents, tried: str, replays: Replays
    ) -> None:
        replays.gates["lumi_direct"] = threading.Event()
        claim = claim_of(agents, tried)
        job = agents.start_variant(tried, claim, {"scale": 3})
        assert replays.began["lumi_direct"].wait(10)

        assert agents.variants(tried)["job"]["id"] == job.id
        assert agents.variants(tried)["job"]["kind"] == VARIANT_JOB
        assert why(agents.start_variant, tried, claim, {"scale": 4}) == (409, "busy")
        assert why(agents.clear_variants, tried) == (409, "busy")
        assert why(agents.start_reproduction, tried, max_cost=1) == (409, "busy")
        assert why(agents.clear_reproduction, tried) == (409, "busy")
        assert why(agents.clear_reference, tried) == (409, "busy")
        assert why(agents.start_tools, tried) == (409, "busy")

        replays.gates["lumi_direct"].set()
        finish(job)
        assert job.state == "succeeded" and len(made_of(agents, tried)) == 1

    def test_nothing_else_that_holds_the_agent_is_run_alongside(self, agents: PaperAgents, tried: str) -> None:
        held = threading.Event()
        other = agents.jobs.start(
            "something-else",
            tried,
            "Holding the agent",
            lambda job: held.wait(10) and "",
            exclusive=f"paperagent:{tried}",
        )
        try:
            assert why(agents.start_variant, tried, claim_of(agents, tried), {"scale": 3}) == (409, "busy")
        finally:
            held.set()
            finish(other)
        assert made_of(agents, tried) == []


class TestWhatTheyAreBoundTo:
    def test_trying_the_claims_again_takes_the_variants_away(
        self, agents: PaperAgents, tried: str, fake_client: FakeClient, workspace: Workspace
    ) -> None:
        vary(agents, tried, {"scale": 3})
        assert kept_path(workspace, tried).exists()

        pick(fake_client, TALLIED, AUROCED)
        assert reproduce(agents, tried).state == "succeeded"

        assert not kept_path(workspace, tried).exists()
        assert (made_of(agents, tried), agents.variants(tried)["stale"]) == ([], 0)

    @pytest.mark.parametrize("take_away", ["clear_reproduction", "clear_reference", "clear_environment"])
    def test_taking_away_the_trying_or_the_tutorials_it_was_held_to_takes_the_variants_away(
        self, agents: PaperAgents, tried: str, workspace: Workspace, take_away: str
    ) -> None:
        vary(agents, tried, {"scale": 3})
        assert kept_path(workspace, tried).exists()

        getattr(agents, take_away)(tried)

        assert not kept_path(workspace, tried).exists() and made_of(agents, tried) == []

    def test_running_the_tutorials_again_takes_the_variants_away(
        self, agents: PaperAgents, tried: str, workspace: Workspace
    ) -> None:
        vary(agents, tried, {"scale": 3})
        directory = directory_of(workspace, tried)
        account = kept_reference.checks_path(directory) / kept_reference.RECORD_FILE
        account.write_text(json.dumps({**json.loads(account.read_text()), "complete": False}))
        assert kept_path(workspace, tried).exists()

        assert run(agents, tried, repeats=1).state == "succeeded"

        assert not kept_path(workspace, tried).exists()

    def test_taking_away_the_variants_leaves_what_was_said_of_the_claims(
        self, agents: PaperAgents, tried: str, workspace: Workspace
    ) -> None:
        vary(agents, tried, {"scale": 3})
        before = (reproduction_bytes(workspace, tried), agents.reproduction(tried)["claims"])

        agents.clear_variants(tried)

        assert made_of(agents, tried) == [] and not kept_path(workspace, tried).exists()
        assert (reproduction_bytes(workspace, tried), agents.reproduction(tried)["claims"]) == before
        agents.clear_variants(tried)

    def test_variants_of_another_trying_of_the_same_claims_are_stale_and_the_next_one_replaces_them(
        self, agents: PaperAgents, tried: str, workspace: Workspace
    ) -> None:
        vary(agents, tried, {"scale": 3})
        trying.rewrite(workspace, tried, started_at="2000-01-01T00:00:00Z")

        shown = agents.variants(tried)
        assert (shown["variants"], shown["stale"], shown["counts"]["variants"]) == ([], 1, 0)
        assert shown["ready"] is True

        vary(agents, tried, {"scale": 4})
        shown = agents.variants(tried)
        assert [made["changes"][0]["now"] for made in shown["variants"]] == [4] and shown["stale"] == 0
        record = kept_variants.load(directory_of(workspace, tried))
        assert record is not None and record["reproduction"] == {"started_at": "2000-01-01T00:00:00Z"}

    @pytest.mark.parametrize("key", ["commit", "image_id", "claims_sha256"])
    def test_variants_of_another_commit_image_or_claims_are_stale(
        self, agents: PaperAgents, tried: str, workspace: Workspace, key: str
    ) -> None:
        vary(agents, tried, {"scale": 3})
        path = kept_path(workspace, tried)
        record = json.loads(path.read_text())
        record[key] = "0" * 40 if key == "commit" else "sha256:" + "0" * 64 if key == "image_id" else "0" * 64
        path.write_text(json.dumps(record))

        shown = agents.variants(tried)

        assert (shown["variants"], shown["stale"]) == ([], 1)

    def test_variants_are_of_nothing_that_is_not_there(
        self, agents: PaperAgents, tried: str, workspace: Workspace
    ) -> None:
        vary(agents, tried, {"scale": 3})
        directory = directory_of(workspace, tried)
        reference, _ = kept_tools_of(directory, agents.lookup(tried)[1])
        trying, claims = kept_reproduction.load(directory), kept_reading.claims_of(directory)
        record = kept_variants.load(directory)

        assert record is not None and trying is not None
        assert kept_variants.is_current(record, reference, trying, claims) is True
        assert kept_variants.is_current(record, None, trying, claims) is False
        assert kept_variants.is_current(record, reference, None, claims) is False

    def test_claims_that_were_read_again_make_the_trying_and_so_the_variants_stale(
        self, agents: PaperAgents, tried: str, workspace: Workspace
    ) -> None:
        vary(agents, tried, {"scale": 3})
        trying.rewrite(workspace, tried, claims_sha256="0" * 64)

        shown = agents.variants(tried)

        assert (shown["ready"], shown["variants"], shown["stale"]) == (False, [], 1)
        assert why(agents.start_variant, tried, claim_of(agents, tried), {"scale": 4}) == (409, "stale")


def edited(record: dict[str, Any], change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    value = copy.deepcopy(record)
    change(value)

    return value


MADE_UP = [
    ("a status that is not one", lambda v: v["variants"][0]["variant"].update(status="best")),
    ("a control that is not one", lambda v: v["variants"][0]["control"].update(verdict="fine")),
    ("a number that was not given", lambda v: v["variants"][0]["variant"].update(gave=None)),
    ("a number that was given when it was not", lambda v: v["variants"][0]["variant"].update(status="no_place")),
    ("comparable when it was not", lambda v: v["variants"][0]["control"].update(verdict="differs")),
    ("an error that is not said", lambda v: v["variants"][0]["variant"].update(status="error", gave=None, error=None)),
    (
        "a rounding said of what gave no number",
        lambda v: (
            v["variants"][0]["variant"].update(status="no_place", gave=None),
            v["variants"][0].update(comparable=False),
        ),
    ),
    (
        "a status that is not one and gave no number",
        lambda v: (
            v["variants"][0]["variant"].update(status="best", gave=None),
            v["variants"][0].update(comparable=False, rounds_to_paper=None),
        ),
    ),
    (
        "a control that is not one and so was not comparable",
        lambda v: (
            v["variants"][0]["control"].update(verdict="fine"),
            v["variants"][0].update(comparable=False),
        ),
    ),
    (
        "an error that is not said and no number",
        lambda v: (
            v["variants"][0]["variant"].update(status="error", gave=None, error=None),
            v["variants"][0].update(comparable=False, rounds_to_paper=None),
        ),
    ),
    (
        "an error said of a number that was given",
        lambda v: v["variants"][0]["variant"].update(error={"type": "ValueError", "message": "x"}),
    ),
    (
        "a name that is too long",
        lambda v: v["variants"][0].update(changes=[{"name": "n" * 101, "was": 1, "now": 2}]),
    ),
    ("a text that does not say what it is", lambda v: v["variants"][0].update(text="It reproduced.")),
    ("no changes", lambda v: v["variants"][0].update(changes=[])),
    (
        "too many changes",
        lambda v: v["variants"][0].update(changes=[{"name": f"a{n}", "was": 1, "now": 2} for n in range(6)]),
    ),
    (
        "a change twice",
        lambda v: v["variants"][0].update(
            changes=[{"name": "a", "was": 1, "now": 2}, {"name": "a", "was": 1, "now": 3}]
        ),
    ),
    ("a change to what is not plain", lambda v: v["variants"][0]["changes"][0].update(now={"$float": "nan"})),
    ("a path that is not places", lambda v: v["variants"][0].update(path=[True])),
    ("an id that is not one", lambda v: v["variants"][0].update(id="x")),
    ("a note that is too long", lambda v: v["variants"][0].update(note="n" * 301)),
    ("no repeats", lambda v: v["variants"][0].update(repeats=0)),
    ("a commit that is not one", lambda v: v.update(commit="main")),
    ("an image that is not one", lambda v: v.update(image_id="abc")),
    ("a hash that is not one", lambda v: v.update(claims_sha256="abc")),
    ("another schema", lambda v: v.update(schema=2)),
    ("a missing field", lambda v: v["variants"][0].pop("tolerance")),
    ("a call that is a truth value", lambda v: v["variants"][0].update(call=True)),
    ("variants twice", lambda v: v["variants"].append(copy.deepcopy(v["variants"][0]))),
    ("too many variants", lambda v: v.update(variants=[{**v["variants"][0], "id": f"{n:012x}"} for n in range(101)])),
]


class TestWhatIsKeptThatIsNotWhatIsWritten:
    @pytest.mark.parametrize(("name", "change"), MADE_UP, ids=[name for name, _ in MADE_UP])
    def test_a_file_that_is_not_in_the_shape_that_is_written_adds_nothing(
        self, agents: PaperAgents, tried: str, workspace: Workspace, name: str, change: Callable[[dict[str, Any]], None]
    ) -> None:
        vary(agents, tried, {"scale": 3})
        path = kept_path(workspace, tried)
        record = json.loads(path.read_text())
        assert kept_variants.is_record(record)

        path.write_text(json.dumps(edited(record, change)))

        shown = agents.variants(tried)
        assert (shown["variants"], shown["stale"], shown["counts"]["variants"]) == ([], 0, 0), name
        assert kept_variants.load(directory_of(workspace, tried)) is None

    def test_a_file_that_is_not_json_or_is_a_link_or_is_too_big_is_not_used(
        self, agents: PaperAgents, tried: str, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vary(agents, tried, {"scale": 3})
        path = kept_path(workspace, tried)
        good = path.read_text()

        path.write_text("{not json")
        assert made_of(agents, tried) == []
        path.write_text(good)
        assert len(made_of(agents, tried)) == 1
        monkeypatch.setattr(kept_variants, "MAX_RECORD_BYTES", 10)
        assert made_of(agents, tried) == []
        monkeypatch.setattr(kept_variants, "MAX_RECORD_BYTES", 8 << 20)
        path.unlink()
        elsewhere = path.parent / "elsewhere.json"
        elsewhere.write_text(good)
        path.symlink_to(elsewhere)
        assert made_of(agents, tried) == []

    def test_a_variant_that_is_made_when_the_file_is_not_usable_starts_the_file_again(
        self, agents: PaperAgents, tried: str, workspace: Workspace
    ) -> None:
        vary(agents, tried, {"scale": 3})
        kept_path(workspace, tried).write_text("[]")

        vary(agents, tried, {"scale": 4})

        assert [made["changes"][0]["now"] for made in made_of(agents, tried)] == [4]


class TestOverHttp:
    def wait_until(self, done: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 20
        while not done():
            assert time.monotonic() < deadline
            time.sleep(0.02)

    def test_making_looking_and_taking_away(
        self, client: TestClient, agents: PaperAgents, tried: str, workspace: Workspace
    ) -> None:
        base = f"/api/paperagents/{tried}/variants"
        claim = claim_of(agents, tried)
        before = reproduction_bytes(workspace, tried)

        shown = client.get(base).json()
        assert shown["ready"] is True and shown["variants"] == []
        started = client.post(
            base,
            json={"claim": claim, "changes": {"scale": 3}, "note": "n", "minutes": 2, "repeats": 3, "gigabytes": 1},
        )
        assert started.status_code == 202 and started.json()["kind"] == VARIANT_JOB
        self.wait_until(lambda: client.get(base).json()["job"] is None)
        shown = client.get(base).json()
        assert [made["variant"]["gave"] for made in shown["variants"]] == [GOT * 3 / 2]
        assert (shown["variants"][0]["note"], shown["variants"][0]["limits"]) == (
            "n",
            {"minutes": 2, "repeats": 3, "gigabytes": 1},
        )
        assert shown["variants"][0]["claim"] == claim
        assert shown["counts"] == {"variants": 1, "comparable": 1, "rounds_to_paper": 0}

        removed = client.delete(base)
        assert removed.status_code == 200 and removed.json()["variants"] == []
        assert reproduction_bytes(workspace, tried) == before

    def test_a_request_that_cannot_be_made_is_refused_with_why(
        self, client: TestClient, agents: PaperAgents, tried: str
    ) -> None:
        base = f"/api/paperagents/{tried}/variants"
        claim = claim_of(agents, tried)

        refused = client.post(base, json={"claim": claim, "changes": {"scale": 2}})
        assert (refused.status_code, refused.json()["error"]["code"]) == (422, "invalid")
        refused = client.post(base, json={"claim": "claim-nothing", "changes": {"scale": 3}})
        assert (refused.status_code, refused.json()["error"]["code"]) == (404, "not_found")
        refused = client.post(base, json={"claim": claim, "changes": {"scale": 3}, "minutes": 0})
        assert (refused.status_code, refused.json()["error"]["code"]) == (422, "invalid")

    def test_a_body_that_is_not_what_is_asked_for_is_refused(
        self, client: TestClient, agents: PaperAgents, tried: str, replays: Replays
    ) -> None:
        base = f"/api/paperagents/{tried}/variants"
        claim = claim_of(agents, tried)

        for body in (
            {},
            {"claim": claim},
            {"changes": {"scale": 3}},
            {"claim": claim, "changes": [["scale", 3]]},
            {"claim": claim, "changes": "scale"},
            {"claim": 3, "changes": {"scale": 3}},
            {"claim": claim, "changes": {"scale": 3}, "minutes": "5"},
            {"claim": claim, "changes": {"scale": 3}, "minutes": 1.5},
            {"claim": claim, "changes": {"scale": 3}, "note": 5},
            {"claim": claim, "changes": {"scale": 3}, "note": "n" * 301},
            {"claim": claim, "changes": {"scale": 3}, "surprise": 1},
        ):
            assert client.post(base, json=body).status_code == 422, body
        assert replays.runs == []

    def test_it_is_not_there_without_the_token_or_for_an_agent_that_is_not(self, client: TestClient) -> None:
        assert client.get("/api/paperagents/nothing/variants").status_code == 404
        assert (
            client.post("/api/paperagents/nothing/variants", json={"claim": "c", "changes": {"a": 1}}).status_code
            == 404
        )
        assert client.delete("/api/paperagents/nothing/variants").status_code == 404
        bare = TestClient(client.app, base_url=LOCAL)
        assert bare.get("/api/paperagents/nothing/variants").status_code == 401
        assert (
            bare.post("/api/paperagents/nothing/variants", json={"claim": "c", "changes": {"a": 1}}).status_code == 401
        )
        assert bare.delete("/api/paperagents/nothing/variants").status_code == 401
