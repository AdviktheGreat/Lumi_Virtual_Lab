"""Asks a running Virtual Lab server the questions of BixBench-Verified-50, and grades what the lead answers.

Each question is asked in a conversation of its own, as a person would ask it in the interface: the lead has the tools,
the code sandbox, and the team a conversation is set up with, and the question's data is in the working directory's
uploads/. Nothing in the conversation says it is a benchmark. What a question takes is saved as soon as it is graded,
so a run that stops carries on where it stopped, and the grading can be redone later, without asking anything again,
because the answers are kept.
"""

import json
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from virtual_lab.bixbench import (
    LENIENT,
    OFFICIAL,
    PROFILES,
    BixBenchError,
    BixQuestion,
    Grade,
    Judge,
    ModelJudge,
    final_answer,
    grade_answer,
    question_message,
    stage_capsule,
)
from virtual_lab.llm import OPENROUTER_PREFIX
from virtual_lab.openrouter import Catalog
from virtual_lab.utils import write_atomically

RUN_FILE = "run.json"
SUMMARY_FILE = "summary.json"
QUESTIONS_DIRECTORY = "questions"
CHATS_DIRECTORY = "chats"
WORK_DIRECTORY = "work"
UPLOADS_DIRECTORY = "uploads"
EVENTS_FILE = "events.jsonl"

POLL_SECONDS = 5.0
STOP_GRACE_SECONDS = 120.0
REQUEST_TIMEOUT_SECONDS = 120.0

ANSWERED = "answered"
FAILED = "failed"
STOPPED = "stopped"
TIMED_OUT = "timeout"


class LabError(RuntimeError):
    """Raised when the server cannot be reached or refuses a request."""


class LabClient:
    """The few requests of the server's interface a run needs.

    :param url: Where the server is, such as http://127.0.0.1:8765.
    :param token: The token the server was started with.
    """

    def __init__(self, url: str, token: str) -> None:
        self.base = url.rstrip("/") + "/api"
        self._headers = {"Authorization": f"Bearer {token}"}

    def _call(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        try:
            response = requests.request(
                method, self.base + path, json=body, headers=self._headers, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except requests.RequestException as error:
            raise LabError(f"The server at {self.base} could not be reached: {error}") from error
        if not response.ok:
            raise LabError(f"{method} {path} was refused with {response.status_code}: {response.text[:500]}")

        return response.json() if response.content else None

    def create_chat(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/chats", body)

    def send_message(self, chat_id: str, text: str) -> dict[str, Any]:
        return self._call("POST", f"/chats/{chat_id}/messages", {"text": text})

    def chat(self, chat_id: str) -> dict[str, Any]:
        return self._call("GET", f"/chats/{chat_id}")

    def stop(self, chat_id: str) -> None:
        self._call("POST", f"/chats/{chat_id}/stop")


@dataclass
class QuestionRecord:
    """What asking one question came to, saved as questions/<id>.json.

    :param question_id: The question.
    :param status: "answered", "failed" (with the error), "stopped", or "timeout".
    :param reply: The lead's last message, whole.
    :param answer: The answer taken from it, and answer_source where it was found.
    :param chat_id: The conversation, which is in the server's workspace to be opened and read.
    :param spent: What the conversation cost in USD, or None if that is not known.
    :param elapsed: Seconds from asking to the end.
    :param tool_calls: The tools the lead called, and cells the code it ran came to.
    :param grades: How the answer was graded, under each of the gradings.
    """

    question_id: str
    status: str
    reply: str = ""
    answer: str = ""
    answer_source: str = "none"
    error: str | None = None
    chat_id: str | None = None
    spent: float | None = None
    elapsed: float = 0.0
    tool_calls: int = 0
    cells: int = 0
    files: int = 0
    grades: dict[str, Grade] = field(default_factory=dict)

    def correct(self, profile: str) -> bool:
        grade = self.grades.get(profile)

        return grade is not None and grade.correct

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "status": self.status,
            "reply": self.reply,
            "answer": self.answer,
            "answer_source": self.answer_source,
            "error": self.error,
            "chat_id": self.chat_id,
            "spent": self.spent,
            "elapsed": self.elapsed,
            "tool_calls": self.tool_calls,
            "cells": self.cells,
            "files": self.files,
            "grades": {name: grade.to_dict() for name, grade in self.grades.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QuestionRecord":
        return cls(
            question_id=str(data["question_id"]),
            status=str(data["status"]),
            reply=str(data.get("reply", "")),
            answer=str(data.get("answer", "")),
            answer_source=str(data.get("answer_source", "none")),
            error=data.get("error"),
            chat_id=data.get("chat_id"),
            spent=data.get("spent"),
            elapsed=float(data.get("elapsed", 0.0)),
            tool_calls=int(data.get("tool_calls", 0)),
            cells=int(data.get("cells", 0)),
            files=int(data.get("files", 0)),
            grades={name: Grade.from_dict(grade) for name, grade in data.get("grades", {}).items()},
        )


def record_path(results: Path, question: BixQuestion) -> Path:
    return Path(results) / QUESTIONS_DIRECTORY / f"{question.id}.json"


def load_records(results: Path, questions: Iterable[BixQuestion]) -> dict[str, QuestionRecord]:
    """The records saved for these questions, by question id."""
    records: dict[str, QuestionRecord] = {}
    for question in questions:
        path = record_path(results, question)
        if path.is_file():
            records[question.id] = QuestionRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    return records


def save_record(results: Path, question: BixQuestion, record: QuestionRecord) -> None:
    path = record_path(results, question)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomically(path, json.dumps(record.to_dict(), indent=2).encode("utf-8"))


def read_turn(chat_directory: Path) -> dict[str, Any]:
    """What a conversation's first turn came to, from the events it saved: the lead's last message, why it failed or
    was stopped, and how many tools and cells it called and ran."""
    outcome: dict[str, Any] = {"reply": "", "failed": None, "stopped": False, "tool_calls": 0, "cells": 0}
    path = chat_directory / EVENTS_FILE
    if not path.is_file():
        return outcome
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("turn") != 1:
            continue
        kind = event.get("kind")
        if kind == "answer":
            outcome["reply"] = str(event.get("text") or "")
        elif kind == "failed":
            outcome["failed"] = str(event.get("text") or "failed")
        elif kind == "stopped":
            outcome["stopped"] = True
        elif kind == "tool_calls":
            outcome["tool_calls"] += len((event.get("data") or {}).get("calls", ()))
        elif kind == "cell":
            outcome["cells"] += 1

    return outcome


@dataclass
class RunSettings:
    """How a run asks.

    :param chat: What each conversation is set up with, as the server takes it when one is made: the model, the team,
        the code, and the most it may spend. Its title is the question's.
    :param timeout: The most seconds a question may take before it is stopped.
    :param poll: Seconds between looks at a conversation.
    """

    chat: dict[str, Any]
    timeout: float = 2400.0
    poll: float = POLL_SECONDS


def answer_question(
    question: BixQuestion,
    data_directory: Path,
    workspace: Path,
    client: LabClient,
    settings: RunSettings,
    judge: Judge | None,
) -> QuestionRecord:
    """Asks the lead one question in a conversation of its own, and grades its answer.

    A failure to ask, or the lead's failing, is part of the record rather than raised, so that the run goes on.
    """
    start = time.monotonic()
    record = QuestionRecord(question_id=question.id, status=FAILED)
    try:
        archive = Path(data_directory) / question.archive
        if not archive.is_file():
            raise BixBenchError(f"{archive} is not there. Fetch it with: virtual-lab-bixbench fetch {data_directory}")
        chat = client.create_chat({**settings.chat, "title": question.id})
        record.chat_id = chat_id = str(chat["id"])
        chat_directory = Path(workspace) / CHATS_DIRECTORY / chat_id
        staged = stage_capsule(archive, chat_directory / WORK_DIRECTORY / UPLOADS_DIRECTORY)
        record.files = len(staged.files)
        client.send_message(chat_id, question_message(question, staged.files))

        timed_out = False
        deadline = start + settings.timeout
        while client.chat(chat_id)["state"] != "idle":
            if not timed_out and time.monotonic() > deadline:
                timed_out = True
                client.stop(chat_id)
                deadline = time.monotonic() + STOP_GRACE_SECONDS
            elif timed_out and time.monotonic() > deadline:
                raise LabError(f"The conversation {chat_id} did not stop when it was asked to")
            time.sleep(settings.poll)

        turn = read_turn(chat_directory)
        info = client.chat(chat_id)
        record.reply = turn["reply"]
        record.tool_calls, record.cells = turn["tool_calls"], turn["cells"]
        record.spent = info.get("spent")
        if turn["failed"] is not None:
            record.status, record.error = FAILED, turn["failed"]
        elif timed_out:
            record.status, record.error = TIMED_OUT, f"It took longer than {settings.timeout:.0f} seconds"
        elif turn["stopped"]:
            record.status = STOPPED
        else:
            record.status = ANSWERED
    except (BixBenchError, LabError, OSError, KeyError) as error:
        record.status, record.error = FAILED, f"{type(error).__name__}: {error}"

    record.elapsed = round(time.monotonic() - start, 1)
    grade_record(question, record, judge)

    return record


def grade_record(question: BixQuestion, record: QuestionRecord, judge: Judge | None) -> None:
    """Takes the answer out of a record's reply and grades it, both ways. A record with no reply is not correct."""
    record.answer, record.answer_source = final_answer(record.reply)
    try:
        record.grades = grade_answer(question, record.answer, judge)
    except Exception as error:
        # A judge that cannot be reached leaves the answer ungraded, which regrading can put right, and a note of why
        note = f"not graded: {type(error).__name__}: {error}"
        record.grades = {name: Grade(False, "none", note) for name in PROFILES}


def summarize(questions: Sequence[BixQuestion], records: Mapping[str, QuestionRecord]) -> dict[str, Any]:
    """Counts what a run has come to, over the questions it was asked.

    A question without a record has not been asked yet, and is counted as not right in the scores, which are therefore
    of all the questions asked of the run and not only of those finished.
    """
    finished = [question for question in questions if question.id in records]
    summary: dict[str, Any] = {
        "questions": len(questions),
        "finished": len(finished),
        "status": {},
        "scores": {},
        "by_mode": {},
        "spent": None,
        "elapsed": round(sum(records[question.id].elapsed for question in finished), 1),
        "tool_calls": sum(records[question.id].tool_calls for question in finished),
    }
    for question in finished:
        status = records[question.id].status
        summary["status"][status] = summary["status"].get(status, 0) + 1
    costs = [records[question.id].spent for question in finished]
    if finished and all(cost is not None for cost in costs):
        summary["spent"] = round(sum(cost for cost in costs if cost is not None), 4)

    for profile in PROFILES:
        right = sum(records[question.id].correct(profile) for question in finished)
        summary["scores"][profile] = {
            "right": right,
            "of_asked": len(questions),
            "accuracy": right / len(questions) if questions else None,
            "of_finished": right / len(finished) if finished else None,
        }
        modes: dict[str, list[int]] = {}
        for question in questions:
            counts = modes.setdefault(question.eval_mode, [0, 0])
            counts[1] += 1
            if question.id in records and records[question.id].correct(profile):
                counts[0] += 1
        summary["by_mode"][profile] = {
            mode: {"right": counts[0], "of": counts[1]} for mode, counts in sorted(modes.items())
        }

    return summary


def format_summary(summary: Mapping[str, Any]) -> str:
    """A summary as the lines a person reads."""
    lines = [f"{summary['finished']} of {summary['questions']} questions finished"]
    if summary["status"]:
        lines.append("status: " + ", ".join(f"{name} {count}" for name, count in sorted(summary["status"].items())))
    labels = {OFFICIAL: "official grading (FutureHouse's)", LENIENT: "lenient grading (rounding and R/Python noise)"}
    for profile in PROFILES:
        score = summary["scores"][profile]
        accuracy = score["accuracy"]
        text = "n/a" if accuracy is None else f"{score['right']}/{score['of_asked']} = {100 * accuracy:.1f}%"
        by_mode = summary["by_mode"][profile]
        modes = ", ".join(f"{mode} {entry['right']}/{entry['of']}" for mode, entry in by_mode.items())
        lines.append(f"{labels[profile]}: {text}  ({modes})")
    if summary["spent"] is not None:
        lines.append(f"cost of the lead: ${summary['spent']:.2f}")
    lines.append(f"time: {summary['elapsed'] / 60:.0f} minutes of work, {summary['tool_calls']} tool calls")

    return "\n".join(lines)


def describe_run(settings: RunSettings, judge_model: str, repo: str) -> dict[str, Any]:
    """What identifies a run, which a run carried on from the same directory must match, so that its results are of one
    way of asking. The time limit and the spending limit are left out, since raising them to try a question again does
    not change what the answers of the others mean."""
    chat = {key: value for key, value in settings.chat.items() if key not in ("max_cost", "title")}

    return json.loads(json.dumps({"dataset": repo, "chat": chat, "judge": judge_model}, sort_keys=True))


def run_bixbench(
    questions: Sequence[BixQuestion],
    data_directory: Path,
    results: Path,
    workspace: Path,
    client: LabClient,
    settings: RunSettings,
    judge: Judge | None,
    description: Mapping[str, Any],
    jobs: int = 1,
    retry_failed: bool = False,
    max_total_cost: float | None = None,
    max_consecutive_failures: int | None = 3,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Asks the questions that have not been answered, and returns the summary of the run.

    :param questions: The questions to ask, which a question already answered in results is not asked again.
    :param data_directory: Where the dataset was fetched.
    :param results: Where the run is saved, and where an earlier run of it was.
    :param workspace: The server's workspace, whose conversations' directories the questions' data is put in.
    :param description: What describes the run, as describe_run gives it.
    :param jobs: How many questions to ask at once. Each has its own sandbox, which may use as much memory as the
        sandbox is allowed, so more than one needs Docker to have that much for each.
    :param retry_failed: Whether to ask again those that failed, were stopped, or timed out.
    :param max_total_cost: The most the run may spend on the lead, in USD, before no more questions are started.
    :param max_consecutive_failures: How many questions in a row may fail before the run stops, since that is more
        likely a mistake in setting it up than in the questions. None never stops.
    :raises BixBenchError: If results holds a run of a different kind.
    """
    results = Path(results)
    run_path = results / RUN_FILE
    if run_path.is_file():
        earlier = json.loads(run_path.read_text(encoding="utf-8"))
        if earlier.get("description") != description:
            different = ", ".join(
                key for key in description if (earlier.get("description") or {}).get(key) != description[key]
            )
            raise BixBenchError(
                f"{results} holds a run with a different {different or 'setup'}, whose results cannot be counted "
                "with this one's. Save this run somewhere else."
            )
    else:
        results.mkdir(parents=True, exist_ok=True)
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        write_atomically(run_path, json.dumps({"description": description, "started": started}, indent=2).encode())

    records = load_records(results, questions)
    pending = [
        question
        for question in questions
        if question.id not in records or (retry_failed and records[question.id].status != ANSWERED)
    ]
    lock = threading.Lock()
    state = {"spent": sum(record.spent or 0.0 for record in records.values()), "failures": 0, "stopped": None}

    def work(question: BixQuestion) -> None:
        with lock:
            if state["stopped"] is not None:
                return
            if max_total_cost is not None and state["spent"] >= max_total_cost:
                state["stopped"] = (
                    f"The run has spent ${state['spent']:.2f}, which reaches its limit of ${max_total_cost:.2f}"
                )
                return
        record = answer_question(question, data_directory, workspace, client, settings, judge)
        with lock:
            records[question.id] = record
            save_record(results, question, record)
            state["spent"] += record.spent or 0.0
            state["failures"] = state["failures"] + 1 if record.status == FAILED else 0
            if max_consecutive_failures is not None and state["failures"] >= max_consecutive_failures:
                state["stopped"] = f"{state['failures']} questions in a row failed, the last with {record.error}"
            verdict = {name: "right" if record.correct(name) else "wrong" for name in PROFILES}
            log(
                f"{question.id}: {record.status}, {verdict[OFFICIAL]} (lenient: {verdict[LENIENT]}), "
                f"{record.elapsed / 60:.1f} min, ${record.spent or 0.0:.3f}, answer: {record.answer[:80]!r}"
            )

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        list(pool.map(work, pending))

    summary = summarize(questions, records)
    summary["stopped"] = state["stopped"]
    write_atomically(results / SUMMARY_FILE, json.dumps(summary, indent=2).encode("utf-8"))
    if state["stopped"] is not None:
        log(f"Stopped early: {state['stopped']}. Run it again on {results} to carry on.")

    return summary


def regrade_bixbench(
    questions: Sequence[BixQuestion], results: Path, judge: Judge | None, log: Callable[[str], None] = print
) -> dict[str, Any]:
    """Grades the saved answers again, with the answers taken from the replies again, without asking anything."""
    results = Path(results)
    records = load_records(results, questions)
    for question in questions:
        if question.id in records:
            grade_record(question, records[question.id], judge)
            save_record(results, question, records[question.id])
    summary = summarize(questions, records)
    write_atomically(results / SUMMARY_FILE, json.dumps(summary, indent=2).encode("utf-8"))
    log(format_summary(summary))

    return summary


def judge_for(model: str) -> ModelJudge:
    """A model to judge answers, with the keys the server keeps and the prices of OpenRouter's models known, as a
    server would have them, so that what the judging cost can be told."""
    try:
        from virtual_lab.server.keychain import Keychain, recall
        from virtual_lab.server.library import SETTABLE_KEYS

        recall(Keychain.system(), SETTABLE_KEYS)
    except ImportError:
        # Without the server's package the keys have to be in the environment, as for any use of a model
        pass
    if model.startswith(OPENROUTER_PREFIX):
        Catalog().ensure_prices()

    return ModelJudge(model)
