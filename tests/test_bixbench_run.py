"""Tests for asking BixBench questions of a server, saving what comes of them, and the command line."""

import json
import threading
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import requests

from virtual_lab import bixbench_cli, bixbench_run
from virtual_lab.bixbench import LENIENT, OFFICIAL, BixBenchError, BixQuestion, Grade
from virtual_lab.bixbench_run import (
    ANSWERED,
    FAILED,
    STOPPED,
    TIMED_OUT,
    LabClient,
    LabError,
    QuestionRecord,
    RunSettings,
    answer_question,
    describe_run,
    format_summary,
    grade_record,
    load_records,
    read_turn,
    regrade_bixbench,
    run_bixbench,
    summarize,
)

CAPSULE = {
    "CapsuleFolder-abc/CapsuleData-abc/counts.csv": b"gene,n\nTP53,4\n",
    "CapsuleFolder-abc/CapsuleNotebook-abc/analysis.ipynb": b'{"cells": []}',
}
Events = list[dict[str, Any]]


def question(question_id: str, ideal: str = "42", mode: str = "str_verifier") -> BixQuestion:
    return BixQuestion(
        id=question_id,
        question=f"What is the answer to {question_id}?",
        ideal=ideal,
        eval_mode=mode,
        capsule="abc",
        archive="CapsuleFolder-abc.zip",
    )


def make_data(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(directory / "CapsuleFolder-abc.zip", "w") as capsule:
        for name, content in CAPSULE.items():
            capsule.writestr(name, content)

    return directory


def event(kind: str, text: str = "", turn: int = 1, **data: Any) -> dict[str, Any]:
    return {"kind": kind, "turn": turn, "text": text, "data": data}


def answered(answer: str) -> Events:
    return [
        event("user", "the question"),
        event("tool_calls", calls=[{"name": "run_python"}, {"name": "run_python"}]),
        event("cell", language="python", code="print(1)"),
        event("answer", f"I analysed it.\nFINAL ANSWER: {answer}"),
    ]


class FakeLab(LabClient):
    """Stands in for the server: makes conversations, and when it is sent a message writes what the lead would have."""

    def __init__(self, workspace: Path, events: Callable[[str], Events] | None = None) -> None:
        super().__init__("http://fake-server", "token")
        self.workspace = workspace
        self.events = events or (lambda title: answered("42"))
        self.created: list[dict[str, Any]] = []
        self.messages: list[tuple[str, str]] = []
        self.stopped: list[str] = []
        self.uploads: dict[str, list[str]] = {}
        self.titles: dict[str, str] = {}
        self.spent = 0.25
        self.busy_polls = 1
        self.hangs = False
        self.refuses_to_stop = False
        self.create_error: Exception | None = None
        self.lock = threading.Lock()
        self.polls: dict[str, int] = {}

    def create_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.create_error is not None:
            raise self.create_error
        with self.lock:
            chat_id = f"chat-{len(self.created) + 1}"
            self.created.append(body)
            self.titles[chat_id] = body["title"]
        # The server makes a conversation's directory when it makes the conversation
        (self.workspace / "chats" / chat_id).mkdir(parents=True)

        return {"id": chat_id}

    def send_message(self, chat_id: str, text: str) -> dict[str, Any]:
        directory = self.workspace / "chats" / chat_id
        self.uploads[chat_id] = sorted(
            path.relative_to(directory / "work" / "uploads").as_posix()
            for path in (directory / "work" / "uploads").rglob("*")
            if path.is_file()
        )
        self.messages.append((chat_id, text))
        lines = [json.dumps(item) for item in self.events(self.titles[chat_id])]
        (directory / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

        return {"turn": 1, "state": "running"}

    def chat(self, chat_id: str) -> dict[str, Any]:
        self.polls[chat_id] = self.polls.get(chat_id, 0) + 1
        busy = self.hangs and chat_id not in self.stopped or self.refuses_to_stop
        busy = busy or self.polls[chat_id] <= self.busy_polls

        return {"id": chat_id, "state": "running" if busy else "idle", "spent": self.spent}

    def stop(self, chat_id: str) -> None:
        self.stopped.append(chat_id)


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, Path, FakeLab, RunSettings]:
    data = make_data(tmp_path / "data")
    workspace = tmp_path / "workspace"
    settings = RunSettings(chat={"model": "m", "max_cost": 2.0}, timeout=60.0, poll=0.0)

    return data, workspace, FakeLab(workspace), settings


class FakeJudge:
    def __init__(self, grade: str = "incorrect") -> None:
        self.grade = grade
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)

        return f"<grade>{self.grade}</grade>"


class TestReadTurn:
    def write(self, directory: Path, lines: list[str]) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

        return directory

    def test_a_missing_file_is_a_turn_with_nothing_in_it(self, tmp_path: Path) -> None:
        assert read_turn(tmp_path) == {"reply": "", "failed": None, "stopped": False, "tool_calls": 0, "cells": 0}

    def test_the_first_turn_is_counted_and_the_rest_and_what_cannot_be_read_are_not(self, tmp_path: Path) -> None:
        lines = [
            json.dumps(event("tool_calls", calls=[{"name": "a"}, {"name": "b"}])),
            "not json at all",
            json.dumps(event("cell")),
            json.dumps(event("answer", "first")),
            json.dumps(event("answer", "second, from a later message", turn=2)),
            json.dumps(event("tool_calls", turn=2, calls=[{"name": "c"}])),
            json.dumps(event("answer", "last of the first turn")),
        ]

        turn = read_turn(self.write(tmp_path / "chat", lines))

        assert turn == {
            "reply": "last of the first turn",
            "failed": None,
            "stopped": False,
            "tool_calls": 2,
            "cells": 1,
        }

    def test_a_failure_and_a_stop_are_noted(self, tmp_path: Path) -> None:
        failed = read_turn(self.write(tmp_path / "a", [json.dumps(event("failed", "APIError: no"))]))
        stopped = read_turn(self.write(tmp_path / "b", [json.dumps(event("stopped", "Stopped by you."))]))

        assert failed["failed"] == "APIError: no"
        assert stopped["stopped"] is True


class TestAnswerQuestion:
    def test_it_asks_in_a_conversation_of_its_own_with_the_data_in_place_and_grades_the_answer(
        self, setup: tuple[Path, Path, FakeLab, RunSettings]
    ) -> None:
        data, workspace, lab, settings = setup

        record = answer_question(question("bix-1-q1"), data, workspace, lab, settings, FakeJudge())

        assert lab.created == [{"model": "m", "max_cost": 2.0, "title": "bix-1-q1"}]
        assert lab.uploads["chat-1"] == ["counts.csv"]
        assert not list((workspace / "chats" / "chat-1").rglob("*.ipynb"))
        text = lab.messages[0][1]
        assert "What is the answer to bix-1-q1?" in text
        assert "- uploads/counts.csv" in text
        assert "42" not in text
        assert record.status == ANSWERED
        assert (record.chat_id, record.files, record.tool_calls, record.cells, record.spent) == (
            "chat-1",
            1,
            2,
            1,
            0.25,
        )
        assert (record.answer, record.answer_source) == ("42", "final_answer")
        assert record.correct(OFFICIAL) and record.correct(LENIENT)
        assert record.elapsed >= 0

    def test_an_answer_off_by_rounding_is_wrong_officially_and_right_leniently(
        self, setup: tuple[Path, Path, FakeLab, RunSettings]
    ) -> None:
        data, workspace, lab, settings = setup
        lab.events = lambda title: answered("2101")

        record = answer_question(question("bix-1-q1", ideal="2118"), data, workspace, lab, settings, FakeJudge())

        assert record.status == ANSWERED
        assert not record.correct(OFFICIAL)
        assert record.correct(LENIENT)
        assert record.grades[LENIENT].method == "numeric"

    def test_a_wrong_answer_is_wrong_both_ways(self, setup: tuple[Path, Path, FakeLab, RunSettings]) -> None:
        data, workspace, lab, settings = setup
        lab.events = lambda title: answered("7")

        record = answer_question(question("bix-1-q1"), data, workspace, lab, settings, FakeJudge())

        assert not record.correct(OFFICIAL) and not record.correct(LENIENT)

    def test_it_waits_until_the_conversation_is_idle(self, setup: tuple[Path, Path, FakeLab, RunSettings]) -> None:
        data, workspace, lab, settings = setup
        lab.busy_polls = 4

        record = answer_question(question("bix-1-q1"), data, workspace, lab, settings, FakeJudge())

        assert record.status == ANSWERED
        assert lab.polls["chat-1"] >= 5

    def test_a_failure_of_the_lead_is_kept_with_its_reason(
        self, setup: tuple[Path, Path, FakeLab, RunSettings]
    ) -> None:
        data, workspace, lab, settings = setup
        lab.events = lambda title: [event("user"), event("failed", "APIError: the model is down")]

        record = answer_question(question("bix-1-q1"), data, workspace, lab, settings, FakeJudge())

        assert (record.status, record.error) == (FAILED, "APIError: the model is down")
        assert record.answer == ""
        assert not record.correct(OFFICIAL)
        assert record.grades[OFFICIAL].method == "none"

    def test_a_conversation_that_was_stopped_is_stopped(self, setup: tuple[Path, Path, FakeLab, RunSettings]) -> None:
        data, workspace, lab, settings = setup
        lab.events = lambda title: [event("user"), event("answer", "Partial.\nFINAL ANSWER: 42"), event("stopped")]

        record = answer_question(question("bix-1-q1"), data, workspace, lab, settings, FakeJudge())

        assert record.status == STOPPED
        assert record.correct(OFFICIAL)

    def test_a_question_that_takes_too_long_is_stopped_and_what_it_said_is_still_graded(
        self, setup: tuple[Path, Path, FakeLab, RunSettings]
    ) -> None:
        data, workspace, lab, settings = setup
        lab.hangs = True
        lab.events = lambda title: [event("user"), event("answer", "Out of time.\nFINAL ANSWER: 42")]
        settings.timeout = 0.0

        record = answer_question(question("bix-1-q1"), data, workspace, lab, settings, FakeJudge())

        assert lab.stopped == ["chat-1"]
        assert record.status == TIMED_OUT
        assert record.error is not None and "took longer" in record.error
        assert record.answer == "42"

    def test_a_conversation_that_does_not_stop_when_asked_is_a_failure_and_not_a_hang(
        self, setup: tuple[Path, Path, FakeLab, RunSettings], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data, workspace, lab, settings = setup
        lab.refuses_to_stop = True
        settings.timeout = 0.0
        monkeypatch.setattr(bixbench_run, "STOP_GRACE_SECONDS", 0.0)

        record = answer_question(question("bix-1-q1"), data, workspace, lab, settings, FakeJudge())

        assert record.status == FAILED
        assert record.error is not None and "did not stop" in record.error

    def test_missing_data_is_a_failure_that_asks_nothing(self, setup: tuple[Path, Path, FakeLab, RunSettings]) -> None:
        data, workspace, lab, settings = setup
        (data / "CapsuleFolder-abc.zip").unlink()

        record = answer_question(question("bix-1-q1"), data, workspace, lab, settings, FakeJudge())

        assert record.status == FAILED
        assert record.error is not None and "virtual-lab-bixbench fetch" in record.error
        assert lab.created == [] and lab.messages == []

    def test_a_server_that_refuses_is_a_failure_that_is_recorded(
        self, setup: tuple[Path, Path, FakeLab, RunSettings]
    ) -> None:
        data, workspace, lab, settings = setup
        lab.create_error = LabError("POST /chats was refused with 401")

        record = answer_question(question("bix-1-q1"), data, workspace, lab, settings, FakeJudge())

        assert record.status == FAILED
        assert record.error == "LabError: POST /chats was refused with 401"

    def test_a_judge_that_cannot_be_reached_leaves_the_answer_ungraded_not_the_run_stopped(
        self, setup: tuple[Path, Path, FakeLab, RunSettings]
    ) -> None:
        data, workspace, lab, settings = setup
        lab.events = lambda title: answered("something only a judge can grade")

        def judge(prompt: str) -> str:
            raise ConnectionError("no route to the judge")

        record = answer_question(question("bix-1-q1"), data, workspace, lab, settings, judge)

        assert record.status == ANSWERED
        assert not record.correct(OFFICIAL)
        assert "not graded: ConnectionError: no route to the judge" in record.grades[OFFICIAL].note


class TestRecords:
    def test_a_record_is_the_same_after_it_is_saved_and_loaded(self, tmp_path: Path) -> None:
        asked = question("bix-1-q1")
        record = QuestionRecord(
            question_id="bix-1-q1",
            status=ANSWERED,
            reply="FINAL ANSWER: 42",
            answer="42",
            answer_source="final_answer",
            chat_id="chat-1",
            spent=0.5,
            elapsed=12.5,
            tool_calls=3,
            cells=2,
            files=4,
            grades={OFFICIAL: Grade(True, "exact"), LENIENT: Grade(True, "exact", "n")},
        )

        bixbench_run.save_record(tmp_path, asked, record)

        assert load_records(tmp_path, [asked, question("bix-2-q1")]) == {"bix-1-q1": record}

    def test_grading_again_takes_the_answer_from_the_reply_again(self) -> None:
        record = QuestionRecord(question_id="bix-1-q1", status=ANSWERED, reply="FINAL ANSWER: 42", answer="old")

        grade_record(question("bix-1-q1"), record, None)

        assert record.answer == "42"
        assert record.correct(OFFICIAL)


def graded(question_id: str, status: str, official: bool, lenient: bool, spent: float | None = 1.0) -> QuestionRecord:
    return QuestionRecord(
        question_id=question_id,
        status=status,
        spent=spent,
        elapsed=60.0,
        tool_calls=5,
        grades={OFFICIAL: Grade(official, "x"), LENIENT: Grade(lenient, "x")},
    )


class TestSummary:
    def test_scores_are_of_all_the_questions_asked_and_not_only_those_finished(self) -> None:
        questions = [question("a", mode="str_verifier"), question("b", mode="llm_verifier"), question("c")]
        records = {"a": graded("a", ANSWERED, True, True), "b": graded("b", FAILED, False, True)}

        summary = summarize(questions, records)

        assert (summary["questions"], summary["finished"]) == (3, 2)
        assert summary["status"] == {"answered": 1, "failed": 1}
        assert summary["scores"][OFFICIAL] == {"right": 1, "of_asked": 3, "accuracy": 1 / 3, "of_finished": 0.5}
        assert summary["scores"][LENIENT]["right"] == 2
        assert summary["by_mode"][OFFICIAL] == {
            "llm_verifier": {"right": 0, "of": 1},
            "str_verifier": {"right": 1, "of": 2},
        }
        assert summary["spent"] == 2.0
        assert (summary["elapsed"], summary["tool_calls"]) == (120.0, 10)

    def test_the_cost_is_unknown_when_any_of_it_is(self) -> None:
        records = {"a": graded("a", ANSWERED, True, True), "b": graded("b", ANSWERED, True, True, spent=None)}

        assert summarize([question("a"), question("b")], records)["spent"] is None

    def test_nothing_asked_has_no_score(self) -> None:
        summary = summarize([], {})

        assert summary["scores"][OFFICIAL]["accuracy"] is None
        assert "n/a" in format_summary(summary)

    def test_it_reads_as_both_scores_one_under_the_other(self) -> None:
        questions = [question("a"), question("b")]
        text = format_summary(summarize(questions, {"a": graded("a", ANSWERED, True, True)}))

        assert "1 of 2 questions finished" in text
        assert "official grading (FutureHouse's): 1/2 = 50.0%" in text
        assert "lenient grading" in text
        assert "cost of the lead: $1.00" in text


class TestRun:
    def run(
        self,
        setup: tuple[Path, Path, FakeLab, RunSettings],
        questions: list[BixQuestion],
        tmp_path: Path,
        **options: Any,
    ) -> dict[str, Any]:
        data, workspace, lab, settings = setup
        description = options.pop("description", describe_run(settings, "judge-model", "repo"))
        logged: list[str] = options.pop("logged", [])

        return run_bixbench(
            questions,
            data,
            tmp_path / "results",
            workspace,
            lab,
            settings,
            options.pop("judge", FakeJudge()),
            description,
            log=logged.append,
            **options,
        )

    def test_every_question_is_asked_and_saved_and_the_run_is_summarised(
        self, setup: tuple[Path, Path, FakeLab, RunSettings], tmp_path: Path
    ) -> None:
        logged: list[str] = []
        questions = [question("bix-1-q1"), question("bix-2-q1", ideal="7")]

        summary = self.run(setup, questions, tmp_path, logged=logged)

        results = tmp_path / "results"
        assert summary["finished"] == 2
        assert summary["scores"][OFFICIAL]["right"] == 1
        assert summary["stopped"] is None
        assert sorted(path.name for path in (results / "questions").iterdir()) == ["bix-1-q1.json", "bix-2-q1.json"]
        assert json.loads((results / "summary.json").read_text())["finished"] == 2
        assert json.loads((results / "run.json").read_text())["description"]["judge"] == "judge-model"
        assert logged[0].startswith("bix-1-q1: answered, right (lenient: right)")
        assert logged[1].startswith("bix-2-q1: answered, wrong")

    def test_what_is_answered_is_not_asked_again_when_the_run_is_run_again(
        self, setup: tuple[Path, Path, FakeLab, RunSettings], tmp_path: Path
    ) -> None:
        questions = [question("bix-1-q1"), question("bix-2-q1")]
        self.run(setup, questions[:1], tmp_path)
        lab = setup[2]
        assert len(lab.created) == 1

        summary = self.run(setup, questions, tmp_path)

        assert [body["title"] for body in lab.created] == ["bix-1-q1", "bix-2-q1"]
        assert summary["finished"] == 2

    def test_what_failed_is_asked_again_only_when_that_is_asked_for(
        self, setup: tuple[Path, Path, FakeLab, RunSettings], tmp_path: Path
    ) -> None:
        lab = setup[2]
        lab.events = lambda title: [event("user"), event("failed", "APIError: down")]
        questions = [question("bix-1-q1")]
        assert self.run(setup, questions, tmp_path)["status"] == {"failed": 1}

        self.run(setup, questions, tmp_path)
        assert len(lab.created) == 1

        lab.events = lambda title: answered("42")
        summary = self.run(setup, questions, tmp_path, retry_failed=True)

        assert len(lab.created) == 2
        assert summary["status"] == {"answered": 1}
        assert summary["scores"][OFFICIAL]["right"] == 1

    def test_a_run_is_not_carried_on_with_a_different_way_of_asking(
        self, setup: tuple[Path, Path, FakeLab, RunSettings], tmp_path: Path
    ) -> None:
        questions = [question("bix-1-q1")]
        self.run(setup, questions, tmp_path)
        other = RunSettings(chat={"model": "another-model", "max_cost": 2.0})

        with pytest.raises(BixBenchError, match="different chat"):
            self.run(setup, questions, tmp_path, description=describe_run(other, "judge-model", "repo"))
        with pytest.raises(BixBenchError, match="different judge"):
            self.run(setup, questions, tmp_path, description=describe_run(setup[3], "other-judge", "repo"))

    def test_raising_the_spending_limit_or_the_title_is_not_a_different_way_of_asking(self) -> None:
        a = RunSettings(chat={"model": "m", "max_cost": 2.0, "title": "x"}, timeout=10)
        b = RunSettings(chat={"model": "m", "max_cost": 9.0}, timeout=99)

        assert describe_run(a, "j", "r") == describe_run(b, "j", "r")

    def test_it_stops_starting_questions_once_it_has_spent_its_limit(
        self, setup: tuple[Path, Path, FakeLab, RunSettings], tmp_path: Path
    ) -> None:
        logged: list[str] = []
        questions = [question(f"bix-{number}-q1") for number in range(1, 5)]

        summary = self.run(setup, questions, tmp_path, max_total_cost=0.5, logged=logged)

        assert summary["finished"] == 2
        assert summary["stopped"] is not None and "limit of $0.50" in summary["stopped"]
        assert "Stopped early" in logged[-1]

    def test_the_spending_of_an_earlier_run_counts_towards_the_limit(
        self, setup: tuple[Path, Path, FakeLab, RunSettings], tmp_path: Path
    ) -> None:
        questions = [question("bix-1-q1"), question("bix-2-q1")]
        self.run(setup, questions[:1], tmp_path)

        summary = self.run(setup, questions, tmp_path, max_total_cost=0.2)

        assert summary["finished"] == 1
        assert summary["stopped"] is not None

    def test_it_stops_when_question_after_question_fails_since_that_is_the_setup(
        self, setup: tuple[Path, Path, FakeLab, RunSettings], tmp_path: Path
    ) -> None:
        lab = setup[2]
        lab.events = lambda title: [event("user"), event("failed", "AuthenticationError: bad key")]
        questions = [question(f"bix-{number}-q1") for number in range(1, 8)]

        summary = self.run(setup, questions, tmp_path)

        assert summary["finished"] == 3
        assert summary["stopped"] is not None and "3 questions in a row failed" in summary["stopped"]
        assert "AuthenticationError" in summary["stopped"]

    def test_a_success_between_failures_starts_the_count_again(
        self, setup: tuple[Path, Path, FakeLab, RunSettings], tmp_path: Path
    ) -> None:
        lab = setup[2]
        failing = {"bix-1-q1", "bix-2-q1", "bix-4-q1", "bix-5-q1"}
        lab.events = lambda title: [event("failed", "x")] if title in failing else answered("42")
        questions = [question(f"bix-{number}-q1") for number in range(1, 6)]

        summary = self.run(setup, questions, tmp_path)

        assert summary["finished"] == 5
        assert summary["stopped"] is None

    def test_questions_can_be_asked_at_once(
        self, setup: tuple[Path, Path, FakeLab, RunSettings], tmp_path: Path
    ) -> None:
        questions = [question(f"bix-{number}-q1") for number in range(1, 7)]

        summary = self.run(setup, questions, tmp_path, jobs=3)

        assert summary["finished"] == 6
        assert summary["scores"][OFFICIAL]["right"] == 6
        assert sorted(setup[2].titles.values()) == sorted(item.id for item in questions)

    def test_the_saved_answers_can_be_graded_again_without_asking_anything(
        self, setup: tuple[Path, Path, FakeLab, RunSettings], tmp_path: Path
    ) -> None:
        lab = setup[2]
        lab.events = lambda title: answered("It went up")
        asked = [question("bix-1-q1", ideal="up", mode="llm_verifier")]
        first = self.run(setup, asked, tmp_path, judge=FakeJudge("incorrect"))
        logged: list[str] = []

        second = regrade_bixbench(asked, tmp_path / "results", FakeJudge("correct"), log=logged.append)

        assert first["scores"][OFFICIAL]["right"] == 0
        assert second["scores"][OFFICIAL]["right"] == 1
        assert len(lab.created) == 1
        assert "official grading" in logged[0]
        saved = load_records(tmp_path / "results", asked)["bix-1-q1"]
        assert saved.correct(OFFICIAL) and saved.reply.endswith("FINAL ANSWER: It went up")

    def test_a_question_with_no_record_is_left_out_when_grading_again(self, tmp_path: Path) -> None:
        summary = regrade_bixbench([question("bix-1-q1")], tmp_path / "results", None, log=lambda text: None)

        assert summary["finished"] == 0


class FakeResponse:
    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.ok = status < 400
        self.status_code = status
        self.content = b"" if body is None else json.dumps(body).encode()
        self.text = self.content.decode()
        self._body = body

    def json(self) -> Any:
        return self._body


class TestLabClient:
    def test_it_makes_the_requests_a_run_needs_with_the_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[str, str, Any, dict[str, str]]] = []

        def request(method: str, url: str, json: Any = None, headers: Any = None, timeout: Any = None) -> FakeResponse:
            calls.append((method, url, json, headers))
            return (
                FakeResponse(200, {"id": "c1", "state": "idle"})
                if method != "POST" or url.endswith("/chats")
                else FakeResponse(202)
            )

        monkeypatch.setattr(requests, "request", request)
        client = LabClient("http://host:1/", "secret")

        client.create_chat({"title": "t"})
        client.send_message("c1", "hello")
        assert client.chat("c1")["state"] == "idle"
        client.stop("c1")

        assert [(method, url) for method, url, _, _ in calls] == [
            ("POST", "http://host:1/api/chats"),
            ("POST", "http://host:1/api/chats/c1/messages"),
            ("GET", "http://host:1/api/chats/c1"),
            ("POST", "http://host:1/api/chats/c1/stop"),
        ]
        assert calls[0][2] == {"title": "t"} and calls[1][2] == {"text": "hello"}
        assert all(headers == {"Authorization": "Bearer secret"} for _, _, _, headers in calls)

    def test_a_refusal_says_what_was_asked_and_what_the_server_said(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(requests, "request", lambda *args, **kwargs: FakeResponse(401, {"detail": "bad token"}))

        with pytest.raises(LabError, match=r"GET /chats/c1 was refused with 401.*bad token"):
            LabClient("http://host:1", "wrong").chat("c1")

    def test_a_server_that_is_not_there_says_where_it_looked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def request(*args: Any, **kwargs: Any) -> FakeResponse:
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(requests, "request", request)

        with pytest.raises(LabError, match="http://host:1/api could not be reached"):
            LabClient("http://host:1", "t").chat("c1")


class TestJudgeFor:
    def test_the_keys_the_server_keeps_are_recalled_and_an_openrouter_model_is_priced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from virtual_lab.server import keychain

        steps: list[str] = []
        monkeypatch.setattr(keychain.Keychain, "system", classmethod(lambda cls: "keychain"))
        monkeypatch.setattr(keychain, "recall", lambda store, keys: steps.append(f"recall {store}"))
        monkeypatch.setattr(
            bixbench_run,
            "Catalog",
            lambda: type("Catalog", (), {"ensure_prices": lambda self: steps.append("price")})(),
        )
        monkeypatch.setattr(bixbench_run, "ModelJudge", lambda model: ("judge", model))

        assert bixbench_run.judge_for("openrouter/moonshotai/kimi-k3.1-pro") == (
            "judge",
            "openrouter/moonshotai/kimi-k3.1-pro",
        )
        assert steps == ["recall keychain", "price"]

        steps.clear()
        assert bixbench_run.judge_for("gpt-5.2") == ("judge", "gpt-5.2")
        assert steps == ["recall keychain"]


class TestCommandLine:
    def dataset(self, tmp_path: Path) -> Path:
        directory = make_data(tmp_path / "data")
        rows = [
            {
                "question_id": number_id,
                "question": f"Question {number_id}?",
                "ideal": "42",
                "eval_mode": "str_verifier",
                "capsule_uuid": "abc",
                "data_folder": "CapsuleFolder-abc.zip",
            }
            for number_id in ("bix-1-q1", "bix-2-q1", "bix-3-q1")
        ]
        (directory / "BixBench-Verified-50.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")

        return directory

    def test_a_run_is_set_up_from_the_options_and_prints_both_scores(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        directory = self.dataset(tmp_path)
        seen: dict[str, Any] = {}

        def fake_run(
            questions: Any,
            data: Any,
            results: Any,
            workspace: Any,
            client: Any,
            settings: Any,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            seen.update(
                ids=[item.id for item in questions],
                results=results,
                workspace=workspace,
                client=client,
                settings=settings,
                judge=args[0],
                description=args[1],
                **kwargs,
            )
            return summarize(questions, {})

        monkeypatch.setattr(bixbench_cli, "run_bixbench", fake_run)
        monkeypatch.setattr(bixbench_cli, "judge_for", lambda model: f"judge:{model}")

        code = bixbench_cli.main(
            [
                "run", str(directory), "--token", "t", "--model", "openrouter/m", "--only", "bix-3-q1", "bix-1-q1",
                "--team", "Scientific Critic", "--max-cost", "5", "--max-total-cost", "40", "--timeout", "100",
                "--jobs", "2", "--retry-failed", "--workspace", str(tmp_path / "ws"),
            ]
        )  # fmt: skip

        assert code == 0
        assert seen["ids"] == ["bix-1-q1", "bix-3-q1"]
        assert seen["results"] == directory / "results"
        assert seen["workspace"] == tmp_path / "ws"
        assert seen["client"].base == "http://127.0.0.1:8765/api"
        assert seen["judge"] == "judge:openrouter/m"
        assert seen["settings"].timeout == 100.0
        assert seen["settings"].chat == {
            "model": "openrouter/m",
            "team": ["Scientific Critic"],
            "code": {"where": "docker", "sandbox": "bio", "network": True, "resources": "retrieve", "forward_env": []},
            "max_cost": 5.0,
        }
        assert (seen["jobs"], seen["retry_failed"], seen["max_total_cost"]) == (2, True, 40.0)
        assert seen["description"]["judge"] == "openrouter/m"
        output = capsys.readouterr().out
        assert "official grading" in output and "lenient grading" in output

    def test_the_judge_can_be_another_model(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        directory = self.dataset(tmp_path)
        judges: list[str] = []
        monkeypatch.setattr(bixbench_cli, "run_bixbench", lambda questions, *args, **kwargs: summarize(questions, {}))
        monkeypatch.setattr(bixbench_cli, "judge_for", lambda model: judges.append(model))

        bixbench_cli.main(["run", str(directory), "--token", "t", "--model", "a", "--judge-model", "b"])

        assert judges == ["b"]

    def test_a_run_without_the_token_says_so_and_asks_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        directory = self.dataset(tmp_path)
        monkeypatch.setattr(bixbench_cli, "run_bixbench", lambda *args, **kwargs: pytest.fail("it asked"))
        monkeypatch.setattr(bixbench_cli, "build_parser", bixbench_cli.build_parser)
        monkeypatch.delenv(bixbench_cli.TOKEN_VARIABLE, raising=False)

        assert bixbench_cli.main(["run", str(directory), "--model", "a", "--token", ""]) == 2
        assert "token is needed" in capsys.readouterr().err

    def test_a_question_that_does_not_exist_is_an_error_and_not_a_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        directory = self.dataset(tmp_path)

        assert bixbench_cli.main(["report", str(directory), "--only", "bix-99-q1"]) == 1
        assert "Error: There is no question bix-99-q1" in capsys.readouterr().err

    def test_the_report_is_of_what_has_been_saved(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        directory = self.dataset(tmp_path)
        asked = [question("bix-1-q1")]
        bixbench_run.save_record(directory / "results", asked[0], graded("bix-1-q1", ANSWERED, True, True))

        assert bixbench_cli.main(["report", str(directory)]) == 0

        output = capsys.readouterr().out
        assert "1 of 3 questions finished" in output
        assert "1/3 = 33.3%" in output

    def test_regrading_asks_the_judge_it_is_given(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        directory = self.dataset(tmp_path)
        seen: dict[str, Any] = {}
        monkeypatch.setattr(bixbench_cli, "judge_for", lambda model: f"judge:{model}")
        monkeypatch.setattr(
            bixbench_cli,
            "regrade_bixbench",
            lambda questions, results, judge: seen.update(count=len(questions), results=results, judge=judge),
        )

        assert (
            bixbench_cli.main(["regrade", str(directory), "--judge-model", "j", "--results", str(tmp_path / "r")]) == 0
        )
        assert seen == {"count": 3, "results": tmp_path / "r", "judge": "judge:j"}

    def test_fetching_reports_what_was_fetched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        seen: dict[str, Any] = {}

        def fetch(directory: Path, token: str | None, only: list[str], limit: int | None) -> list[BixQuestion]:
            seen.update(directory=directory, token=token, only=only, limit=limit)
            return [question("bix-1-q1")]

        monkeypatch.setattr(bixbench_cli, "download_bixbench", fetch)

        assert bixbench_cli.main(["fetch", str(tmp_path / "d"), "--hf-token", "hf_x", "--limit", "2"]) == 0
        assert seen == {"directory": tmp_path / "d", "token": "hf_x", "only": [], "limit": 2}
        assert "Fetched 1 questions" in capsys.readouterr().out

    def test_a_server_that_cannot_be_reached_is_an_error_and_not_a_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        directory = self.dataset(tmp_path)

        def refuse(*args: Any, **kwargs: Any) -> None:
            raise LabError("The server could not be reached")

        monkeypatch.setattr(bixbench_cli, "run_bixbench", refuse)
        monkeypatch.setattr(bixbench_cli, "judge_for", lambda model: None)

        assert bixbench_cli.main(["run", str(directory), "--token", "t", "--model", "a"]) == 1
        assert "Error: The server could not be reached" in capsys.readouterr().err

    def test_an_interruption_says_how_to_carry_on(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        directory = self.dataset(tmp_path)

        def interrupt(*args: Any, **kwargs: Any) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(bixbench_cli, "run_bixbench", interrupt)
        monkeypatch.setattr(bixbench_cli, "judge_for", lambda model: None)

        assert bixbench_cli.main(["run", str(directory), "--token", "t", "--model", "a"]) == bixbench_cli.INTERRUPTED
        assert "Run the same command again" in capsys.readouterr().err
