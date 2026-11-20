"""Tests of a model proposing the call of a method of a bake-off, when the person would rather it did: that the model
is asked last of all that costs nothing, so that none is paid for a call that would not be made, that what it says is
data that a program checks as it checks the person's, and that nothing it says can make a call be made that the tool's
signature or the person's data does not allow, that the run says whose the call was, with the model's own words, and
that what asking it cost is paid out of the one limit, whichever way the job ends.

Docker, the containers that tools are called in, and the model are stand-ins, as they are in the tests of running."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MODEL, FakeClient, make_usage, parsed_response
from fastapi.testclient import TestClient
from test_server_bakeoff_building import (
    add,
    agents,
    bakeoffs,
    client,
    containers,
    docker,
    finish,
    git_is_installed,
    jobs,
    marker,
    model_client,
    papers,
    quick,
    remotes,
    replays,
    stack,
    workspace,
)
from test_server_bakeoff_running import (
    DATA,
    IN_CONTAINER,
    MAP,
    TALLY,
    built,
    damaged,
    file_of,
    hold,
    kept_of,
    own_data,
    reader,
    run,
    run_shown,
    say_outside,
    two,
)
from test_server_bakeoffs import CSV, OTHER_DOI, TASK, asked_of, job_done, record_of, refused, rewrite, unit_cost, why
from test_server_paperagent_tools import Replays

from virtual_lab.paperagents import applying
from virtual_lab.paperagents.applying import ProposedCall
from virtual_lab.server import bakeoff_running
from virtual_lab.server import bakeoff_runs as kept_runs
from virtual_lab.server.bakeoffs import RUN_JOB, Bakeoffs
from virtual_lab.server.jobs import Jobs
from virtual_lab.server.own import Own
from virtual_lab.server.paperagents import PaperAgents
from virtual_lab.server.workspace import Workspace
from virtual_lab.utils import MeetingUsage

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

PROPOSE = {"propose": True}
READ_TABLE = {"path": IN_CONTAINER}
# What the data was said to be on the Data page, which is what a model is told of it
DESCRIBED = "Read counts of mouse brain nuclei"


def proposal(
    tool: str = "read_table", arguments: Any = None, reason: str = "It reads the table.", **options: Any
) -> Any:
    """What a model says when it is asked for a call: by default, that the table is to be read from the data."""
    arguments = READ_TABLE if arguments is None else arguments

    return parsed_response(
        ProposedCall(
            tool=tool, arguments=arguments if isinstance(arguments, str) else json.dumps(arguments), reason=reason
        ),
        **options,
    )


def say(model: FakeClient, *answers: Any) -> int:
    """Makes the model say these in turn, and says how many requests it had had before, which building made."""
    before = len(model.completions.parse_calls)
    model.completions.parsed_responses = list(answers)

    return before


def spent_of(workspace: Workspace, bakeoff_id: str) -> float:
    return float(record_of(workspace, bakeoff_id)["spent"])


class TestTheModelProposesTheCall:
    def test_a_call_that_a_model_proposed_is_made_as_the_persons_would_be_and_the_run_says_it_was_the_models(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        model_client: FakeClient,
    ) -> None:
        bakeoff_id, candidate = built
        say(model_client, proposal(reason="  It reads\n the table. "))
        before = len(replays.runs)

        job = run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        assert job.kind == RUN_JOB and job.state == "succeeded", job.error
        assert job.message == "Ran 1 of 1 methods."
        [ran] = replays.runs[before:]
        assert ran["function"] == "read_table" and [case["args"] for case in ran["cases"]] == [READ_TABLE]
        assert ran["room"] == kept_runs.RESULT_ROOM
        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"], saved["reason"], saved["by"]) == ("ran", None, "", "model")
        assert saved["schema"] == 2
        assert saved["tool"] == {"name": "read_table", "called": "cellmapper.mapping.read_table", "tier": "A"}
        assert saved["arguments"] == READ_TABLE and saved["result"] == {"type": "str", "value": IN_CONTAINER}
        assert saved["proposed"] == {
            "model": TEST_MODEL,
            "reason": "It reads the table.",
            "cost": pytest.approx(unit_cost()),
            "tool": "read_table",
            "arguments": json.dumps(READ_TABLE),
        }
        assert saved["data"]["path"] == IN_CONTAINER and saved["method"]["commit"]

    def test_what_asking_cost_is_kept_with_the_run_and_added_to_what_the_bake_off_has_spent(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        earlier = spent_of(workspace, bakeoff_id)
        say(model_client, proposal(usage=make_usage(prompt_tokens=5_000, completion_tokens=100)))

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        cost = unit_cost(5_000, 100)
        assert kept_of(workspace, bakeoff_id, candidate)["proposed"]["cost"] == pytest.approx(cost)
        assert spent_of(workspace, bakeoff_id) == pytest.approx(earlier + cost)
        assert record_of(workspace, bakeoff_id)["cost_known"] is True

    def test_what_asking_cost_for_each_method_is_what_that_one_cost_and_not_what_had_been_spent_before_it(
        self, bakeoffs: Bakeoffs, workspace: Workspace, two: tuple[str, str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, first, second = two
        say(
            model_client,
            proposal(usage=make_usage(prompt_tokens=100, completion_tokens=20)),
            proposal(usage=make_usage(prompt_tokens=282, completion_tokens=20)),
        )

        run(bakeoffs, bakeoff_id, {first: PROPOSE, second: PROPOSE})

        # What is spent is added up as it is used, and what the second cost is what is left when the first is taken
        # from that, which is the price of 282 tokens and not a number that is that to the last digit that a float has
        assert kept_of(workspace, bakeoff_id, first)["proposed"]["cost"] == 0.00045
        assert kept_of(workspace, bakeoff_id, second)["proposed"]["cost"] == 0.000905

    def test_the_model_is_asked_once_for_each_method_and_is_told_the_task_the_data_and_the_tools(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        before = say(model_client, proposal())

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        assert len(model_client.completions.parse_calls) == before + 1
        request = model_client.completions.parse_calls[-1]
        assert request["response_format"] is ProposedCall and request["model"] == TEST_MODEL
        system, user = asked_of(model_client)[-2:]
        assert system == applying.APPLY_PROMPT
        assert f"The task: {TASK}\n" in user
        assert f"What the person says of their data: {DATA}: {DESCRIBED}\n" in user
        assert f"Where the data is, read-only: {IN_CONTAINER} (a file)" in user
        for name in ("map_cells", "tally", "read_table"):
            assert f"Tool: {name}\nCalls: cellmapper.mapping.{name}\n" in user
        assert "Parameters: path: " in user and "header: bool (has a default)" in user
        assert "A call that a tutorial made: {'counts': [1, 2, 3], 'scale': 2}" in user
        assert "A call that a tutorial made: {'path': 'example.csv'," in user

    def test_what_is_in_the_data_is_not_told_to_the_model(
        self, bakeoffs: Bakeoffs, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        say(model_client, proposal())

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        told = "\n".join(asked_of(model_client)[-2:])
        assert CSV.decode().splitlines()[0] not in told and "gene,a,b" not in told

    def test_data_that_is_a_folder_is_said_to_be_one_and_a_place_in_it_may_be_proposed(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        model_client: FakeClient,
        tmp_path: Path,
    ) -> None:
        bakeoff_id, candidate = built
        folder = tmp_path / "tables"
        folder.mkdir()
        (folder / "a.csv").write_text("x\n", "utf-8")
        Own(workspace, 10_000).add_path(str(folder), "Tables of counts")
        bakeoffs.change(bakeoff_id, data="tables")
        say(model_client, proposal(arguments={"path": "/data/tables/a.csv"}))

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        user = asked_of(model_client)[-1]
        assert (
            "Where the data is, read-only: /data/tables (a folder, of which what is in it is not shown to you)" in user
        )
        assert "a.csv" not in user
        saved = kept_of(workspace, bakeoff_id, candidate)
        assert saved["state"] == "ran" and saved["arguments"] == {"path": "/data/tables/a.csv"}

    def test_the_person_may_give_the_call_of_one_method_and_have_a_model_propose_the_call_of_another(
        self, bakeoffs: Bakeoffs, workspace: Workspace, two: tuple[str, str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, first, second = two
        before = say(model_client, proposal())

        job = run(bakeoffs, bakeoff_id, {first: TALLY, second: PROPOSE})

        assert job.message == "Ran 2 of 2 methods." and len(model_client.completions.parse_calls) == before + 1
        by_person, by_model = kept_of(workspace, bakeoff_id, first), kept_of(workspace, bakeoff_id, second)
        assert (by_person["by"], by_person["proposed"], by_person["tool"]["name"]) == ("person", None, "tally")
        assert (by_model["by"], by_model["proposed"]["tool"], by_model["tool"]["name"]) == (
            "model",
            "read_table",
            "read_table",
        )

    def test_calls_that_are_all_the_persons_ask_no_model_and_cost_nothing(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        earlier = spent_of(workspace, bakeoff_id)
        before = say(model_client)

        run(bakeoffs, bakeoff_id, {candidate: TALLY})

        assert len(model_client.completions.parse_calls) == before and spent_of(workspace, bakeoff_id) == earlier

    def test_a_call_that_is_the_persons_is_theirs_even_if_it_is_said_not_to_be_proposed(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        before = say(model_client)

        run(bakeoffs, bakeoff_id, {candidate: {**TALLY, "propose": False}})

        assert kept_of(workspace, bakeoff_id, candidate)["by"] == "person"
        assert len(model_client.completions.parse_calls) == before

    def test_running_again_with_the_persons_call_takes_the_place_of_the_models_and_the_other_way(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        say(model_client, proposal())

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})
        assert kept_of(workspace, bakeoff_id, candidate)["by"] == "model"
        run(bakeoffs, bakeoff_id, {candidate: TALLY})
        assert kept_of(workspace, bakeoff_id, candidate)["by"] == "person"
        assert kept_of(workspace, bakeoff_id, candidate)["proposed"] is None
        say(model_client, proposal())
        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        assert kept_of(workspace, bakeoff_id, candidate)["proposed"]["model"] == TEST_MODEL
        assert [each.name for each in (file_of(workspace, bakeoff_id, candidate)).parent.iterdir()] == [
            f"{candidate}.json"
        ]


class TestAModelIsNotAskedForACallThatWouldNotBeMade:
    def test_data_that_is_outside_the_card_is_not_run_on_and_the_model_is_not_asked(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        say_outside(bakeoffs, bakeoff_id, candidate)
        earlier = spent_of(workspace, bakeoff_id)
        before = say(model_client, proposal())

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"], saved["by"], saved["proposed"]) == ("not_run", "outside", "person", None)
        assert len(model_client.completions.parse_calls) == before and spent_of(workspace, bakeoff_id) == earlier

    def test_a_method_that_is_not_built_is_not_run_and_the_model_is_not_asked(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, _ = built
        unbuilt = add(bakeoffs, bakeoff_id, OTHER_DOI, "Unbuilt", None)
        before = say(model_client, proposal())

        run(bakeoffs, bakeoff_id, {unbuilt: PROPOSE})

        saved = kept_of(workspace, bakeoff_id, unbuilt)
        assert (saved["why"], saved["by"]) == ("not_built", "person")
        assert len(model_client.completions.parse_calls) == before


class TestWhatStandsInTheWayOfAsking:
    def test_a_model_that_has_no_key_is_not_asked_and_nothing_is_started_but_the_persons_calls_are_still_run(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        jobs: Jobs,
        built: tuple[str, str],
        model_client: FakeClient,
        replays: Replays,
    ) -> None:
        bakeoff_id, candidate = built
        keyless = Bakeoffs(PaperAgents(workspace, 100_000, jobs, lambda model: ["OPENAI_API_KEY"]))
        before = say(model_client, proposal())

        error = refused(keyless.start_run, bakeoff_id, {candidate: PROPOSE})

        assert (error.status, error.code) == (422, "missing_keys") and "OPENAI_API_KEY" in str(error)
        assert keyless.calling(bakeoff_id) is None and len(model_client.completions.parse_calls) == before
        run(keyless, bakeoff_id, {candidate: TALLY})
        assert kept_of(workspace, bakeoff_id, candidate)["state"] == "ran"

    def test_nothing_left_of_the_limit_is_refused_before_anything_is_started_but_the_persons_calls_are_still_run(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        bakeoffs.change(bakeoff_id, limit=spent_of(workspace, bakeoff_id))
        before = say(model_client, proposal())

        assert why(bakeoffs.start_run, bakeoff_id, {candidate: PROPOSE}) == (409, "limit")

        assert bakeoffs.calling(bakeoff_id) is None and len(model_client.completions.parse_calls) == before
        run(bakeoffs, bakeoff_id, {candidate: TALLY})
        assert kept_of(workspace, bakeoff_id, candidate)["state"] == "ran"

    def test_a_cost_that_is_not_known_is_refused_before_anything_is_started(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        rewrite(workspace, bakeoff_id, lambda record: record.update(cost_known=False))
        before = say(model_client, proposal())

        assert why(bakeoffs.start_run, bakeoff_id, {candidate: PROPOSE}) == (409, "cost_unknown")

        assert bakeoffs.calling(bakeoff_id) is None and len(model_client.completions.parse_calls) == before

    def test_the_model_is_asked_what_is_left_of_the_limit_and_not_the_whole_of_it(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        built: tuple[str, str],
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bakeoff_id, candidate = built
        given: list[float] = []
        real = bakeoffs.applier_of

        def spy(model: str, max_cost: float, usage: Any) -> Any:
            given.append(max_cost)

            return real(model, max_cost, usage)

        monkeypatch.setattr(bakeoffs, "applier_of", spy)
        say(model_client, proposal())

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        assert given == [pytest.approx(1.0 - spent_of(workspace, bakeoff_id) + unit_cost())]

    def test_what_asks_the_model_is_given_the_model_the_limit_the_client_and_the_usage_that_it_is_to_add_to(
        self, bakeoffs: Bakeoffs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        given: list[tuple[Any, ...]] = []

        class Applier:
            def __init__(self, *arguments: Any) -> None:
                given.append(arguments)

        monkeypatch.setattr(applying, "ModelApplier", Applier)
        monkeypatch.setattr(bakeoffs.paperagents, "client", object())
        usage = MeetingUsage()

        applier = bakeoffs.applier_of("some-model", 0.25, usage)

        assert isinstance(applier, Applier)
        assert given == [("some-model", 0.25, bakeoffs.paperagents.chat_models, bakeoffs.paperagents.client, usage)]

    def test_a_model_that_cannot_be_asked_is_refused_as_not_fit_and_says_why(
        self, bakeoffs: Bakeoffs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def cannot(*arguments: Any) -> Any:
            raise ValueError("No provider serves that model")

        monkeypatch.setattr(applying, "ModelApplier", cannot)

        error = refused(bakeoffs.applier_of, "some-model", 1.0, MeetingUsage())

        assert (error.status, error.code, error.message) == (422, "invalid", "No provider serves that model")

    def test_a_call_to_propose_that_no_model_was_given_for_is_a_job_that_failed_and_not_a_method_that_did(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built

        job = finish(
            bakeoffs.jobs.start(RUN_JOB, bakeoff_id, "Run", bakeoffs.runs.work(bakeoff_id, {candidate: PROPOSE}, 300))
        )

        assert job.state == "failed" and job.error is not None and "no model was given" in job.error
        assert not file_of(workspace, bakeoff_id, candidate).exists()


BAD = [
    ("nope", READ_TABLE, "no_tool", "The model chose 'nope', which is not one of the tools that it was shown"),
    ("read_table", "not json {", "bad_call", "The arguments that the model wrote cannot be used. It is not JSON"),
    ("read_table", "[1, 2]", "bad_call", "It is not an object of arguments by name"),
    ("read_table", '{"path": NaN}', "bad_call", "NaN is not a number that JSON has"),
    ("read_table", {"path": IN_CONTAINER, "nope": 1}, "bad_call", "does not take nope"),
    ("read_table", {}, "bad_call", "needs path, which was not given"),
    ("read_table", {"path": 3}, "bad_call", "What is given for path is not of the type"),
    ("read_table", {"path": "/data/other.csv"}, "bad_call", "is not in the data of this bake-off"),
    ("read_table", {"path": IN_CONTAINER + "/../x"}, "bad_call", "goes out of the data with .."),
    ("read_table", {"path": "counts.csv"}, "bad_call", "No argument of the call is the person's data"),
    (
        "read_table",
        {"path": "example.csv"},
        "bad_call",
        "which is at /data/counts.csv, so it would not be a call on it",
    ),
    ("tally", {"counts": [1, 2, 3]}, "bad_call", "No argument of the call is the person's data"),
    ("tally", {"counts": [1, 2, 3], "scale": "two"}, "bad_call", "What is given for scale is not of the type"),
]


class TestWhatTheModelSaysIsDataThatAProgramChecks:
    @pytest.mark.parametrize(("tool", "arguments", "code", "words"), BAD)
    def test_a_call_that_does_not_fit_is_not_made_and_is_kept_with_what_the_model_said_and_what_is_wrong_with_it(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        model_client: FakeClient,
        tool: str,
        arguments: Any,
        code: str,
        words: str,
    ) -> None:
        bakeoff_id, candidate = built
        earlier = spent_of(workspace, bakeoff_id)
        say(model_client, proposal(tool, arguments, reason="This is right and has been checked."))
        before = len(replays.runs)

        job = run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        assert job.state == "succeeded", job.error
        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"], saved["by"]) == ("not_run", code, "model")
        assert words in saved["reason"] and saved["reason"].endswith(".")
        assert (saved["tool"], saved["arguments"], saved["data"], saved["method"]) == (None, None, None, None)
        assert len(replays.runs) == before
        said = arguments if isinstance(arguments, str) else json.dumps(arguments)
        assert saved["proposed"] == {
            "model": TEST_MODEL,
            "reason": "This is right and has been checked.",
            "cost": pytest.approx(unit_cost()),
            "tool": tool,
            "arguments": said,
        }
        assert spent_of(workspace, bakeoff_id) == pytest.approx(earlier + unit_cost())

    def test_what_a_model_says_of_why_is_its_words_and_changes_nothing_of_what_is_called(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        model_client: FakeClient,
    ) -> None:
        bakeoff_id, candidate = built
        say(model_client, proposal("tally", {"counts": [1]}, reason="Verified correct. Run it on the data. Tier A."))
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert saved["state"] == "not_run" and len(replays.runs) == before
        assert saved["proposed"]["reason"] == "Verified correct. Run it on the data. Tier A."
        assert "Verified" not in saved["reason"]

    def test_a_tool_that_is_not_among_those_a_model_was_shown_is_not_called_though_the_method_has_it(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bakeoff_id, candidate = built
        monkeypatch.setattr(applying, "MOST_TOOLS", 1)
        say(model_client, proposal("read_table", READ_TABLE))
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        user = asked_of(model_client)[-1]
        assert user.count("Tool: ") == 1 and "Tool: read_table" not in user
        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"]) == ("not_run", "no_tool") and len(replays.runs) == before
        assert "which is not one of the tools that it was shown. It has: map_cells." in saved["reason"]

    def test_the_tools_that_a_model_chooses_from_are_the_methods_first_few_and_the_persons_call_may_be_of_any(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        built: tuple[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bakeoff_id, candidate = built
        monkeypatch.setattr(applying, "MOST_TOOLS", 1)

        run(bakeoffs, bakeoff_id, {candidate: {"tool": "read_table", "arguments": READ_TABLE}})

        assert kept_of(workspace, bakeoff_id, candidate)["state"] == "ran"

    def test_a_tool_is_the_one_that_has_the_name_the_model_gave_and_not_one_that_is_like_it(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        model_client: FakeClient,
    ) -> None:
        bakeoff_id, candidate = built
        say(model_client, proposal("READ_TABLE", READ_TABLE))
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"]) == ("not_run", "no_tool") and len(replays.runs) == before
        assert saved["proposed"]["tool"] == "READ_TABLE" and saved["tool"] is None

    def test_a_model_that_says_no_tool_can_do_the_task_has_proposed_nothing_and_its_words_are_kept(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        model_client: FakeClient,
    ) -> None:
        bakeoff_id, candidate = built
        say(model_client, proposal("", {}, reason="It is for images, and the data is a table."))
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"], saved["by"]) == ("not_run", "not_proposed", "model")
        assert saved["reason"] == "The model said that none of this method's tools can do the task on this data."
        assert saved["proposed"] == {
            "model": TEST_MODEL,
            "reason": "It is for images, and the data is a table.",
            "cost": pytest.approx(unit_cost()),
            "tool": None,
            "arguments": None,
        }
        assert len(replays.runs) == before

    def test_a_request_that_fails_is_a_method_not_run_that_says_so_and_costs_nothing(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        earlier = spent_of(workspace, bakeoff_id)
        say(model_client, RuntimeError("connection reset"))

        job = run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        assert job.state == "succeeded" and "Not run, each with why: 1." in job.message
        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"], saved["by"]) == ("not_run", "not_proposed", "model")
        assert "connection reset" in saved["reason"]
        assert saved["proposed"] == {"model": TEST_MODEL, "reason": "", "cost": 0.0, "tool": None, "arguments": None}
        assert spent_of(workspace, bakeoff_id) == earlier

    def test_a_model_that_refuses_is_a_method_not_run_and_what_it_used_is_still_paid_for(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        earlier = spent_of(workspace, bakeoff_id)
        say(model_client, parsed_response(None, refusal="No."))

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["why"], saved["by"]) == ("not_proposed", "model") and "refused" in saved["reason"]
        assert saved["proposed"]["cost"] == pytest.approx(unit_cost())
        assert spent_of(workspace, bakeoff_id) == pytest.approx(earlier + unit_cost())

    def test_a_tool_a_model_named_with_what_is_not_text_in_it_is_kept_as_text_and_the_run_is_still_one_that_is_used(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        say(model_client, proposal("read_\x00table\n", READ_TABLE, reason="Reads\x1b[31m it.\x07"))

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"]) == ("not_run", "no_tool")
        assert saved["proposed"]["tool"] == "read_ table" and saved["proposed"]["reason"] == "Reads [31m it."
        assert run_shown(bakeoffs, bakeoff_id, candidate)["proposed"] == saved["proposed"]

    def test_arguments_a_model_wrote_with_what_is_not_text_in_them_are_not_JSON_and_are_kept_as_text(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        say(model_client, proposal(arguments='{"path":\n "/data/counts.csv"\x07}'))

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"]) == ("not_run", "bad_call") and "It is not JSON" in saved["reason"]
        assert saved["proposed"]["arguments"] == '{"path": "/data/counts.csv" }'
        assert run_shown(bakeoffs, bakeoff_id, candidate)["proposed"] == saved["proposed"]

    def test_arguments_written_over_several_lines_are_the_same_arguments(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        model_client: FakeClient,
    ) -> None:
        bakeoff_id, candidate = built
        say(model_client, proposal(arguments='{\n  "path": "/data/counts.csv",\n  "names": ["a", "b"]\n}'))

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert saved["state"] == "ran" and saved["arguments"] == {"path": IN_CONTAINER, "names": ["a", "b"]}
        assert saved["proposed"]["arguments"] == '{ "path": "/data/counts.csv", "names": ["a", "b"] }'
        assert replays.runs[-1]["cases"][0]["args"] == saved["arguments"]

    def test_what_a_model_wrote_that_is_longer_than_is_kept_is_cut_and_the_call_is_not_made(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        model_client: FakeClient,
    ) -> None:
        bakeoff_id, candidate = built
        say(
            model_client,
            proposal(arguments='{"path": "/data/counts.csv", "names": [' + ", ".join(['"a"'] * 2000) + "]}"),
        )
        before = len(replays.runs)

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert (saved["state"], saved["why"]) == ("not_run", "bad_call") and "It is too long" in saved["reason"]
        assert len(saved["proposed"]["arguments"]) == kept_runs.MAX_SAID_ARGUMENTS_CHARS
        assert saved["proposed"]["arguments"].endswith("…") and len(replays.runs) == before

    def test_what_a_model_wrote_for_a_tool_that_is_longer_than_is_kept_is_cut(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        say(model_client, proposal("t" * 500, {}))

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert saved["why"] == "no_tool" and saved["proposed"]["tool"] == "t" * kept_runs.MAX_SAID_TOOL_CHARS
        assert f"The model chose '{'t' * 59}…'" in saved["reason"]


class TestWhatIsTheDataInACall:
    @pytest.mark.parametrize(
        "arguments",
        [
            {"path": IN_CONTAINER},
            {"paths": ["/data/other", f"{IN_CONTAINER}/part1.csv"]},
            {"nested": {"deeper": [{"path": IN_CONTAINER}]}},
        ],
    )
    def test_a_call_that_names_the_data_or_a_place_in_it_is_on_it(self, arguments: dict[str, Any]) -> None:
        assert bakeoff_running.names_data(arguments, DATA)

    @pytest.mark.parametrize(
        "arguments",
        [
            {},
            {"count": 3},
            {"path": "/data/other.csv"},
            {"path": f"{IN_CONTAINER}.bak"},
            {"path": f"{IN_CONTAINER}x/part1.csv"},
            {"path": "/data"},
            {"path": f"see {IN_CONTAINER}"},
            {"path": DATA},
        ],
    )
    def test_a_call_that_names_other_data_or_only_something_like_it_is_not(self, arguments: dict[str, Any]) -> None:
        assert not bakeoff_running.names_data(arguments, DATA)


class TestTheOneLimit:
    def dear(self, tool: str = "read_table") -> Any:
        return proposal(tool, usage=make_usage(prompt_tokens=1_000_000, completion_tokens=0))

    def test_a_limit_that_is_reached_in_the_middle_leaves_the_methods_not_got_to_not_run_and_says_why(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        two: tuple[str, str, str],
        model_client: FakeClient,
    ) -> None:
        bakeoff_id, first, second = two
        before = say(model_client, self.dear(), proposal())

        job = run(bakeoffs, bakeoff_id, {first: PROPOSE, second: PROPOSE})

        assert job.state == "succeeded" and job.message == "Ran 1 of 2 methods. Not run, each with why: 1."
        assert len(model_client.completions.parse_calls) == before + 1
        assert kept_of(workspace, bakeoff_id, first)["state"] == "ran"
        left = kept_of(workspace, bakeoff_id, second)
        assert (left["state"], left["why"], left["by"]) == ("not_run", "limit", "model")
        assert "was not asked: The limit on spending was reached" in left["reason"] and left["reason"].endswith(".")
        assert left["proposed"] == {"model": TEST_MODEL, "reason": "", "cost": 0.0, "tool": None, "arguments": None}
        record = record_of(workspace, bakeoff_id)
        assert record["spent"] > record["limit"] and record["cost_known"] is True
        assert bakeoffs.view(bakeoff_id)["left"] == 0

    def test_with_more_to_spend_the_methods_that_were_not_got_to_are_run_and_the_others_are_not_asked_again(
        self, bakeoffs: Bakeoffs, workspace: Workspace, two: tuple[str, str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, first, second = two
        say(model_client, self.dear(), proposal())
        run(bakeoffs, bakeoff_id, {first: PROPOSE, second: PROPOSE})
        bakeoffs.change(bakeoff_id, limit=spent_of(workspace, bakeoff_id) + 1)
        before = say(model_client, proposal())

        run(bakeoffs, bakeoff_id, {second: PROPOSE})

        assert len(model_client.completions.parse_calls) == before + 1
        assert (kept_of(workspace, bakeoff_id, second)["state"], kept_of(workspace, bakeoff_id, first)["state"]) == (
            "ran",
            "ran",
        )

    def test_a_response_that_does_not_say_what_it_used_makes_the_cost_not_known_and_no_more_is_asked(
        self, bakeoffs: Bakeoffs, workspace: Workspace, two: tuple[str, str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, first, second = two
        silent = proposal()
        silent.usage = None
        before = say(model_client, silent, proposal())

        job = run(bakeoffs, bakeoff_id, {first: PROPOSE, second: PROPOSE})

        assert job.state == "succeeded" and len(model_client.completions.parse_calls) == before + 1
        done = kept_of(workspace, bakeoff_id, first)
        assert done["state"] == "ran" and done["proposed"]["cost"] is None
        left = kept_of(workspace, bakeoff_id, second)
        assert left["why"] == "limit" and "did not report what it used" in left["reason"]
        assert record_of(workspace, bakeoff_id)["cost_known"] is False
        assert why(bakeoffs.start_run, bakeoff_id, {second: PROPOSE}) == (409, "cost_unknown")

    def test_what_was_spent_is_added_when_the_job_is_stopped_and_the_method_it_was_stopped_in_is_kept_unrun(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        two: tuple[str, str, str],
        model_client: FakeClient,
    ) -> None:
        bakeoff_id, first, second = two
        earlier = spent_of(workspace, bakeoff_id)
        before = say(model_client, proposal(), proposal())
        hold(replays, "read_table")

        job = bakeoffs.start_run(bakeoff_id, {first: PROPOSE, second: PROPOSE})
        assert replays.began["read_table"].wait(10)
        job.request_stop()
        finish(job)

        assert job.state == "stopped" and len(model_client.completions.parse_calls) == before + 1
        assert (
            not file_of(workspace, bakeoff_id, first).exists() and not file_of(workspace, bakeoff_id, second).exists()
        )
        assert spent_of(workspace, bakeoff_id) == pytest.approx(earlier + unit_cost())

    def test_what_was_spent_is_added_when_a_job_fails(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        replays: Replays,
        built: tuple[str, str],
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bakeoff_id, candidate = built
        earlier = spent_of(workspace, bakeoff_id)
        say(model_client, proposal())

        def breaks(*arguments: Any, **options: Any) -> Any:
            raise RuntimeError("the job broke")

        monkeypatch.setattr(bakeoffs.runs, "outcome_of", breaks)

        job = run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        assert job.state == "failed" and job.error is not None and "the job broke" in job.error
        assert spent_of(workspace, bakeoff_id) == pytest.approx(earlier + unit_cost())

    def test_what_is_spent_is_not_counted_twice_by_the_next_job(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        earlier = spent_of(workspace, bakeoff_id)
        say(model_client, proposal(), proposal())

        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})
        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

        assert spent_of(workspace, bakeoff_id) == pytest.approx(earlier + 2 * unit_cost())


class TestWhatIsKeptOfAModelsCall:
    def made(self, bakeoffs: Bakeoffs, built: tuple[str, str], model_client: FakeClient) -> None:
        bakeoff_id, candidate = built
        say(model_client, proposal())
        run(bakeoffs, bakeoff_id, {candidate: PROPOSE})

    @pytest.mark.parametrize(
        "change",
        [
            lambda saved: saved.update(by="person"),
            lambda saved: saved.update(by="a model"),
            lambda saved: saved.update(proposed=None),
            lambda saved: saved.pop("proposed"),
            lambda saved: saved["proposed"].update(model=""),
            lambda saved: saved["proposed"].update(model="gpt\x00"),
            lambda saved: saved["proposed"].update(model=3),
            lambda saved: saved["proposed"].update(reason="x" * 301),
            lambda saved: saved["proposed"].update(reason="a\nb"),
            lambda saved: saved["proposed"].update(cost=-0.5),
            lambda saved: saved["proposed"].update(cost="free"),
            lambda saved: saved["proposed"].update(cost=float("inf")),
            lambda saved: saved["proposed"].update(tool="t" * 101),
            lambda saved: saved["proposed"].update(tool="a\x07"),
            lambda saved: saved["proposed"].update(tool=3),
            lambda saved: saved["proposed"].update(arguments="x" * 2001),
            lambda saved: saved["proposed"].update(arguments="a\nb"),
            lambda saved: saved["proposed"].pop("cost"),
            lambda saved: saved["proposed"].pop("tool"),
            lambda saved: saved["proposed"].pop("arguments"),
        ],
    )
    def test_a_run_that_says_a_model_proposed_it_and_is_not_what_that_is_is_not_used(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        built: tuple[str, str],
        model_client: FakeClient,
        change: Callable[[dict[str, Any]], Any],
    ) -> None:
        self.made(bakeoffs, built, model_client)
        bakeoff_id, candidate = built
        assert run_shown(bakeoffs, bakeoff_id, candidate) is not None

        damaged(workspace, bakeoff_id, candidate, change)

        assert run_shown(bakeoffs, bakeoff_id, candidate) is None
        assert why(bakeoffs.run_of, bakeoff_id, candidate) == (404, "not_found")

    def test_the_most_that_is_kept_of_what_a_model_said_is_used_as_it_is(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        self.made(bakeoffs, built, model_client)
        bakeoff_id, candidate = built

        damaged(
            workspace,
            bakeoff_id,
            candidate,
            lambda saved: saved["proposed"].update(reason="x" * 300, tool="t" * 100, arguments="a" * 2000, cost=0.0),
        )

        assert run_shown(bakeoffs, bakeoff_id, candidate) is not None

    def test_a_cost_that_was_not_known_and_a_call_that_was_not_asked_for_are_kept_as_they_were(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        self.made(bakeoffs, built, model_client)
        bakeoff_id, candidate = built

        damaged(
            workspace,
            bakeoff_id,
            candidate,
            lambda saved: saved["proposed"].update(cost=None, tool=None, arguments=None),
        )

        shown = run_shown(bakeoffs, bakeoff_id, candidate)
        assert shown is not None and shown["proposed"]["cost"] is None

    @pytest.mark.parametrize("why_not", ["limit", "not_proposed"])
    def test_a_method_that_was_not_run_for_want_of_a_model_is_one_that_a_model_was_to_propose_for(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient, why_not: str
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: {"tool": "nope"}})
        assert kept_of(workspace, bakeoff_id, candidate)["why"] == "no_tool"

        damaged(workspace, bakeoff_id, candidate, lambda saved: saved.update(why=why_not))

        assert run_shown(bakeoffs, bakeoff_id, candidate) is None

    def test_a_run_that_an_earlier_version_kept_is_read_as_it_was_with_the_persons_call(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: TALLY})

        damaged(workspace, bakeoff_id, candidate, lambda saved: (saved.pop("proposed"), saved.update(schema=1)))

        shown = bakeoffs.run_of(bakeoff_id, candidate)
        assert (shown["schema"], shown["by"], shown["proposed"], shown["state"]) == (2, "person", None, "ran")
        assert run_shown(bakeoffs, bakeoff_id, candidate)["by"] == "person"

    @pytest.mark.parametrize("schema", [0, 3, "1"])
    def test_a_run_of_a_version_that_is_not_known_is_not_used_as_the_earlier_one_is(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], schema: Any
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: TALLY})

        damaged(workspace, bakeoff_id, candidate, lambda saved: (saved.pop("proposed"), saved.update(schema=schema)))

        assert run_shown(bakeoffs, bakeoff_id, candidate) is None

    def test_a_run_of_the_earlier_version_that_says_a_model_chose_it_is_not_used(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: TALLY})

        damaged(
            workspace, bakeoff_id, candidate, lambda saved: (saved.pop("proposed"), saved.update(schema=1, by="model"))
        )

        assert run_shown(bakeoffs, bakeoff_id, candidate) is None

    def test_a_run_of_the_earlier_version_is_kept_in_the_shape_of_this_one_when_it_is_run_again(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str]
    ) -> None:
        bakeoff_id, candidate = built
        run(bakeoffs, bakeoff_id, {candidate: TALLY})
        damaged(workspace, bakeoff_id, candidate, lambda saved: (saved.pop("proposed"), saved.update(schema=1)))

        run(bakeoffs, bakeoff_id, {candidate: TALLY})

        saved = kept_of(workspace, bakeoff_id, candidate)
        assert saved["schema"] == 2 and saved["proposed"] is None

    def test_the_whole_of_a_run_and_the_list_of_methods_both_say_what_the_model_proposed(
        self, bakeoffs: Bakeoffs, workspace: Workspace, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        self.made(bakeoffs, built, model_client)
        bakeoff_id, candidate = built

        whole = bakeoffs.run_of(bakeoff_id, candidate)
        listed = run_shown(bakeoffs, bakeoff_id, candidate)

        assert whole["proposed"] == listed["proposed"] == kept_of(workspace, bakeoff_id, candidate)["proposed"]
        assert whole["by"] == listed["by"] == "model" and whole["since"] == listed["since"] == []

    def test_a_method_that_is_taken_out_of_the_running_while_the_model_is_asked_has_no_run_kept_and_is_still_paid_for(
        self,
        bakeoffs: Bakeoffs,
        workspace: Workspace,
        two: tuple[str, str, str],
        model_client: FakeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bakeoff_id, first, second = two
        earlier = spent_of(workspace, bakeoff_id)
        say(model_client, proposal(), proposal())
        original = bakeoffs.runs.proposed_call

        def takes_it_out(*arguments: Any) -> Any:
            bakeoffs.remove_candidate(bakeoff_id, second)

            return original(*arguments)

        monkeypatch.setattr(bakeoffs.runs, "proposed_call", takes_it_out)

        run(bakeoffs, bakeoff_id, {second: PROPOSE})

        assert not file_of(workspace, bakeoff_id, second).exists()
        assert spent_of(workspace, bakeoff_id) == pytest.approx(earlier + unit_cost())


class TestWhatIsAskedFor:
    @pytest.mark.parametrize(
        "call",
        [
            {"propose": "yes"},
            {"propose": 1},
            {"propose": None},
            {"propose": [True]},
            {"propose": True, "tool": "map_cells"},
            {"propose": True, "arguments": {}},
            {"propose": True, "tool": "map_cells", "arguments": {"counts": [1]}},
            {"propose": True, "other": 1},
            {"propose": False},
            {"propose": False, "arguments": {}},
        ],
    )
    def test_a_call_to_propose_is_that_alone_and_a_call_that_is_not_to_be_proposed_has_a_tool(
        self, bakeoffs: Bakeoffs, built: tuple[str, str], model_client: FakeClient, call: Any
    ) -> None:
        bakeoff_id, candidate = built
        before = say(model_client, proposal())

        assert why(bakeoffs.start_run, bakeoff_id, {candidate: call}) == (422, "invalid")

        assert bakeoffs.calling(bakeoff_id) is None and len(model_client.completions.parse_calls) == before

    def test_as_many_methods_as_there_may_be_in_a_bake_off_may_be_proposed_for_and_not_one_more(
        self, bakeoffs: Bakeoffs, built: tuple[str, str]
    ) -> None:
        bakeoff_id, _ = built

        assert why(bakeoffs.start_run, bakeoff_id, {f"{number:08x}": PROPOSE for number in range(12)}) == (
            404,
            "not_found",
        )
        assert why(bakeoffs.start_run, bakeoff_id, {f"{number:08x}": PROPOSE for number in range(13)}) == (
            422,
            "invalid",
        )

    def test_a_method_that_is_not_in_the_bake_off_is_not_found_and_the_model_is_not_asked(
        self, bakeoffs: Bakeoffs, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        before = say(model_client, proposal())

        assert why(bakeoffs.start_run, bakeoff_id, {candidate: PROPOSE, "00000000": PROPOSE}) == (404, "not_found")

        assert len(model_client.completions.parse_calls) == before and bakeoffs.calling(bakeoff_id) is None


class TestTheApi:
    def test_a_call_to_propose_is_asked_for_over_the_api_and_what_came_of_it_says_so(
        self, client: TestClient, built: tuple[str, str], model_client: FakeClient, workspace: Workspace
    ) -> None:
        bakeoff_id, candidate = built
        say(model_client, proposal())
        url = f"/api/bakeoffs/{bakeoff_id}"

        started = client.post(f"{url}/run", json={"calls": {candidate: {"propose": True}}})

        assert started.status_code == 202
        assert job_done(client, started.json())["state"] == "succeeded"
        whole = client.get(f"{url}/candidates/{candidate}/run").json()
        assert (whole["state"], whole["by"], whole["proposed"]["model"]) == ("ran", "model", TEST_MODEL)
        assert whole["proposed"]["tool"] == "read_table" and whole["arguments"] == READ_TABLE
        listed = next(each for each in client.get(url).json()["candidates"] if each["id"] == candidate)
        assert listed["run"]["by"] == "model" and listed["run"]["proposed"] == whole["proposed"]
        assert client.get(url).json()["spent"] == pytest.approx(record_of(workspace, bakeoff_id)["spent"])

    def test_a_call_that_is_the_persons_is_made_as_it_was_over_the_api(
        self, client: TestClient, built: tuple[str, str], workspace: Workspace
    ) -> None:
        bakeoff_id, candidate = built
        url = f"/api/bakeoffs/{bakeoff_id}"

        job = client.post(f"{url}/run", json={"calls": {candidate: MAP}}).json()

        assert job_done(client, job)["state"] == "succeeded"
        found = client.get(f"{url}/candidates/{candidate}/run").json()
        assert (found["by"], found["proposed"], found["tool"]["name"]) == ("person", None, "map_cells")

    def test_what_is_asked_wrongly_is_refused_over_the_api_and_nothing_is_started(
        self, client: TestClient, built: tuple[str, str], model_client: FakeClient
    ) -> None:
        bakeoff_id, candidate = built
        url = f"/api/bakeoffs/{bakeoff_id}/run"
        before = say(model_client, proposal())

        for bad in (
            {"calls": {candidate: {"propose": "yes"}}},
            {"calls": {candidate: {"propose": 1}}},
            {"calls": {candidate: {"propose": None}}},
            {"calls": {candidate: {"propose": True, "tool": "map_cells"}}},
            {"calls": {candidate: {"propose": True, "arguments": {"counts": [1]}}}},
            {"calls": {candidate: {"propose": False}}},
            {"calls": {candidate: {"arguments": {}}}},
            {"calls": {candidate: {"tool": None}}},
        ):
            assert client.post(url, json=bad).status_code == 422, bad
        assert len(model_client.completions.parse_calls) == before

    def test_nothing_left_to_spend_is_a_conflict_over_the_api(
        self, client: TestClient, bakeoffs: Bakeoffs, built: tuple[str, str], workspace: Workspace
    ) -> None:
        bakeoff_id, candidate = built
        bakeoffs.change(bakeoff_id, limit=spent_of(workspace, bakeoff_id))

        answer = client.post(f"/api/bakeoffs/{bakeoff_id}/run", json={"calls": {candidate: {"propose": True}}})

        assert answer.status_code == 409 and answer.json()["error"]["code"] == "limit"
