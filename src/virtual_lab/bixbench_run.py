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
    Choices,
    Grade,
    Judge,
    ModelJudge,
    chose_refusal,
    final_answer,
    grade_answer,
    grade_choice,
    multiple_choice,
    question_message,
    stage_capsule,
)
from virtual_lab.llm import OPENROUTER_PREFIX
from virtual_lab.openrouter import Catalog
from virtual_lab.skills import MAX_SKILLS, builtin_skills, discover_skills
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
# Setting up the question failed before the lead was asked anything, so it has not been attempted and is not recorded
NOT_ASKED = "not_asked"

# What --skills takes besides the folder of some skills
NO_SKILLS = "none"
BUILTIN_SKILLS = "builtin"


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

    def send_message(self, chat_id: str, text: str, lab: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Sends a message, given with /lab if the lead is to have scientists work on it, which lab names: its mode,
        members, and rounds."""
        body: dict[str, Any] = {"text": text}
        if lab is not None:
            body.update(directive="lab", lab=dict(lab))

        return self._call("POST", f"/chats/{chat_id}/messages", body)

    def chat(self, chat_id: str) -> dict[str, Any]:
        return self._call("GET", f"/chats/{chat_id}")

    def stop(self, chat_id: str) -> None:
        self._call("POST", f"/chats/{chat_id}/stop")

    def close_chat(self, chat_id: str) -> None:
        """Has the server free what a conversation holds, its container, keeping what it saved."""
        self._call("POST", f"/chats/{chat_id}/close")

    def tools(self) -> list[dict[str, Any]]:
        """The tools the server has, each with its name and the group the settings put it in."""
        return list(self._call("GET", "/tools")["tools"])

    def skills(self) -> list[dict[str, Any]]:
        """The skills the server has, each with its name and where it was found."""
        return list(self._call("GET", "/skills")["skills"])

    def install_skills(self, path: str) -> dict[str, Any]:
        """Has the server put in the skills of a folder on the machine it is on, as copies, leaving those whose names
        it has, and say which it put in and which it left."""
        return self._call("POST", "/skills/install", {"path": path})

    def data_lake(self) -> dict[str, Any]:
        """Where the server keeps Biomni's data lake, and how many of its files are there."""
        lake = (self._call("GET", "/setup/data-lake") or {}).get("data_lake")
        if not isinstance(lake, dict):
            raise LabError("The server did not say where its data lake is")

        return lake


@dataclass
class QuestionRecord:
    """What asking one question came to, saved as questions/<id>.json.

    :param question_id: The question.
    :param status: "answered", "failed" (with the error), "stopped", or "timeout", or "not_asked" for a question whose
        setup failed before the lead was asked, which is never saved.
    :param reply: The lead's last message, whole.
    :param answer: The answer taken from it, and answer_source where it was found.
    :param chat_id: The conversation, which is in the server's workspace to be opened and read.
    :param spent: What the conversation cost in USD, or None if that is not known.
    :param elapsed: Seconds from asking to the end.
    :param tool_calls: The tools the lead called, and cells the code it ran came to.
    :param grades: How the answer was graded, under each of the gradings.
    :param choices: For a question asked as multiple choice, its options in the order of their letters, and right_choice
        the letter of the right one; none and empty for a question that was asked for an open answer.
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
    choices: list[str] = field(default_factory=list)
    right_choice: str = ""

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
            "choices": list(self.choices),
            "right_choice": self.right_choice,
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
            choices=[str(option) for option in data.get("choices", ())],
            right_choice=str(data.get("right_choice", "")),
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
    :param lab: With each question given as the researcher would give it with /lab, who works on it and how, as the
        server takes it: a mode, the members' titles, and the rounds. None for the question to be asked plainly, which
        leaves it to the lead whether to call on its team.
    :param multiple_choice: Whether to ask each question with options to choose from, the ideal answer among the
        distractors the dataset has for it, rather than for an answer of the lead's own.
    :param refusal_option: With multiple_choice, whether the options include one that says there is not enough
        information.
    """

    chat: dict[str, Any]
    timeout: float = 2400.0
    poll: float = POLL_SECONDS
    lab: dict[str, Any] | None = None
    multiple_choice: bool = False
    refusal_option: bool = True


def answer_question(
    question: BixQuestion,
    data_directory: Path,
    workspace: Path,
    client: LabClient,
    settings: RunSettings,
    judge: Judge | None,
) -> QuestionRecord:
    """Asks the lead one question in a conversation of its own, and grades its answer.

    A failure to ask, or the lead's failing, is part of the record rather than raised, so that the run goes on. A
    failure before the lead was sent the question has the status NOT_ASKED, and one after it, FAILED.
    """
    start = time.monotonic()
    record = QuestionRecord(question_id=question.id, status=NOT_ASKED)
    try:
        choices: Choices | None = None
        if settings.multiple_choice:
            choices = multiple_choice(question, settings.refusal_option)
            record.choices, record.right_choice = list(choices.options), choices.right
        archive = Path(data_directory) / question.archive
        if not archive.is_file():
            raise BixBenchError(f"{archive} is not there. Fetch it with: virtual-lab-bixbench fetch {data_directory}")
        chat = client.create_chat({**settings.chat, "title": question.id})
        record.chat_id = chat_id = str(chat["id"])
        chat_directory = Path(workspace) / CHATS_DIRECTORY / chat_id
        staged = stage_capsule(archive, chat_directory / WORK_DIRECTORY / UPLOADS_DIRECTORY)
        record.files = len(staged.files)
        client.send_message(chat_id, question_message(question, staged.files, choices), settings.lab)
        record.status = FAILED

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
        record.error = f"{type(error).__name__}: {error}"

    record.elapsed = round(time.monotonic() - start, 1)
    if record.chat_id:
        # Each question's container stays up with what it loaded until it is closed, and fifty of them are more than
        # the machine holds. What the conversation saved, which is what is read from it, is kept.
        try:
            client.close_chat(record.chat_id)
        except LabError:
            pass
    grade_record(question, record, judge)

    return record


def grade_record(question: BixQuestion, record: QuestionRecord, judge: Judge | None) -> None:
    """Takes the answer out of a record's reply and grades it, both ways. A record with no reply is not correct. One
    that was asked as multiple choice is right if the answer chooses the right option, which both ways agree on."""
    record.answer, record.answer_source = final_answer(record.reply)
    try:
        if record.choices:
            record.grades = dict.fromkeys(PROFILES, grade_choice(record.answer, record.choices, record.right_choice))
        else:
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
    if choosing := [records[question.id] for question in finished if records[question.id].choices]:
        # Left out of a run of open answers, whose scores are not these
        summary["multiple_choice"] = {
            "questions": len(choosing),
            "refused": sum(chose_refusal(record.answer, record.choices) for record in choosing),
        }

    return summary


def format_summary(summary: Mapping[str, Any]) -> str:
    """A summary as the lines a person reads."""
    lines = [f"{summary['finished']} of {summary['questions']} questions finished"]
    if summary["status"]:
        lines.append("status: " + ", ".join(f"{name} {count}" for name, count in sorted(summary["status"].items())))
    labels = {OFFICIAL: "official grading (FutureHouse's)", LENIENT: "lenient grading (rounding and R/Python noise)"}
    choice = summary.get("multiple_choice")
    # What was asked as multiple choice has one grading, the letter, which the two gradings agree on, and a score that
    # is not an open answer's and is called what it is
    only_choices = choice is not None and choice["questions"] == summary["finished"]
    for profile in PROFILES[:1] if only_choices else PROFILES:
        score = summary["scores"][profile]
        accuracy = score["accuracy"]
        text = "n/a" if accuracy is None else f"{score['right']}/{score['of_asked']} = {100 * accuracy:.1f}%"
        by_mode = summary["by_mode"][profile]
        modes = ", ".join(f"{mode} {entry['right']}/{entry['of']}" for mode, entry in by_mode.items())
        label = "multiple choice (the letter of the right option; not comparable with an open answer's score)"
        lines.append(f"{label if only_choices else labels[profile]}: {text}  ({modes})")
    if choice is not None:
        lines.append(f'chose "insufficient information": {choice["refused"]} of {choice["questions"]} multiple choice')
    if summary["spent"] is not None:
        lines.append(f"cost of the lead: ${summary['spent']:.2f}")
    lines.append(f"time: {summary['elapsed'] / 60:.0f} minutes of work, {summary['tool_calls']} tool calls")

    return "\n".join(lines)


def describe_run(settings: RunSettings, judge_model: str, repo: str) -> dict[str, Any]:
    """What identifies a run, which a run carried on from the same directory must match, so that its results are of one
    way of asking. The time limit, the spending limit, and the most tool calls for a message are left out, since raising
    them to try a question again does not change what the answers of the others mean."""
    left_out = ("max_cost", "max_tool_iterations", "title")
    chat = {key: value for key, value in settings.chat.items() if key not in left_out}
    # Left out when there are none, as the lab is, so that a run made before skills could be given matches one without
    if not chat.get("skills"):
        chat.pop("skills", None)

    description: dict[str, Any] = {"dataset": repo, "chat": chat, "judge": judge_model}
    if settings.lab is not None:
        description["lab"] = settings.lab
    if settings.multiple_choice:
        description["multiple_choice"] = {"refusal_option": settings.refusal_option}

    return json.loads(json.dumps(description, sort_keys=True))


def choose_skills(specs: Sequence[str], client: LabClient, log: Callable[[str], None] = print) -> list[str]:
    """The names of the skills every conversation of a run is to be given, which the server is asked to put in where
    they are folders.

    :param specs: What --skills was given: "none", or any of "builtin" (the skills that come with the lab) and folders
        of skills on this machine, which the server, which is on it too, puts in its workspace, leaving any whose
        names it has already, so that a workspace made for the run is one whose skills are these.
    :raises BixBenchError: If one is not a folder with skills in it, "none" is given with others, or the server does
        not have a skill that was asked for, as a server of older code does not have the built-in ones.
    """
    if not specs or list(specs) == [NO_SKILLS]:
        return []
    if NO_SKILLS in specs:
        raise BixBenchError(f"--skills {NO_SKILLS} is for no skills, and cannot be given with others")

    # Every spec is checked before the server is asked to put anything in, so that a mistake in a later one does not
    # leave the skills of an earlier one in its workspace
    wanted: list[str] = []
    folders: list[Path] = []
    for spec in specs:
        if spec == BUILTIN_SKILLS:
            wanted += [skill.name for skill in builtin_skills()]
            continue
        folder = Path(spec).expanduser().resolve()
        if not folder.is_dir():
            raise BixBenchError(f"--skills {spec} is not a folder, nor {BUILTIN_SKILLS!r}, nor {NO_SKILLS!r}")
        found = discover_skills([("folder", folder)])
        if not found.skills:
            raise BixBenchError(f"There is no skill in {folder}: a skill is a folder with a SKILL.md in it")
        folders.append(folder)
        wanted += [skill.name for skill in found.skills]
    if len(set(wanted)) > MAX_SKILLS:
        raise BixBenchError(f"A conversation can be given {MAX_SKILLS} skills, and {len(set(wanted))} were asked for")
    for folder in folders:
        result = client.install_skills(str(folder))
        log(
            f"{folder}: {len(result.get('installed', ()))} skills put in the server's workspace, "
            f"{len(result.get('skipped', ()))} left as they were or not put in"
        )

    names = list(dict.fromkeys(wanted))
    has = {skill["name"] for skill in client.skills()}
    if missing := [name for name in names if name not in has]:
        shown = ", ".join(missing[:8]) + (f", and {len(missing) - 8} more" if len(missing) > 8 else "")
        raise BixBenchError(f"The server does not have the skills {shown}. Is it running the lab's latest code?")

    return names


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
    :param retry_failed: Whether to ask again those that failed, were stopped, or timed out. A question that could not
        be set up was never recorded, and is asked again whether or not this is set.
    :param max_total_cost: The most the run may spend on the lead, in USD, before no more questions are started. What
        questions under way may still spend, up to the limit each conversation has, is counted as spent.
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
    reserve = float(settings.chat.get("max_cost") or 0.0)
    state: dict[str, Any] = {
        "spent": sum(record.spent or 0.0 for record in records.values()),
        "failures": 0,
        "in_flight": 0,
        "stopped": None,
        "warned": False,
    }

    def work(question: BixQuestion) -> None:
        with lock:
            if state["stopped"] is not None:
                return
            committed = state["spent"] + reserve * state["in_flight"]
            if max_total_cost is not None and committed >= max_total_cost:
                state["stopped"] = (
                    f"The run has spent ${state['spent']:.2f}, and ${committed - state['spent']:.2f} more may be "
                    f"spent by questions under way, which reaches its limit of ${max_total_cost:.2f}"
                )
                return
            state["in_flight"] += 1
        try:
            record = answer_question(question, data_directory, workspace, client, settings, judge)
        finally:
            with lock:
                state["in_flight"] -= 1
        with lock:
            if record.status != NOT_ASKED:
                records[question.id] = record
                save_record(results, question, record)
            state["spent"] += record.spent or 0.0
            # A question that was never asked has no cost to know
            unpriced = record.status != NOT_ASKED and record.spent is None
            if unpriced and max_total_cost is not None and not state["warned"]:
                state["warned"] = True
                log("The cost of a question is not known, so the limit on the run's cost cannot be kept to.")
            failed = record.status in (FAILED, NOT_ASKED)
            state["failures"] = state["failures"] + 1 if failed else 0
            if max_consecutive_failures is not None and state["failures"] >= max_consecutive_failures:
                state["stopped"] = f"{state['failures']} questions in a row failed, the last with {record.error}"
            verdict = {name: "right" if record.correct(name) else "wrong" for name in PROFILES}
            log(
                f"{question.id}: {record.status}, {verdict[OFFICIAL]} (lenient: {verdict[LENIENT]}), "
                f"{record.elapsed / 60:.1f} min, ${record.spent or 0.0:.3f}, answer: {record.answer[:80]!r}"
            )
            if record.status == NOT_ASKED:
                log(f"{question.id} was not asked, and is not counted: {record.error}")

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        list(pool.map(work, pending))

    summary = summarize(questions, records)
    summary["stopped"] = state["stopped"]
    write_atomically(results / SUMMARY_FILE, json.dumps(summary, indent=2).encode("utf-8"))
    if state["stopped"] is not None:
        log(
            f"Stopped early: {state['stopped']}. Run it again on {results} to carry on, adding --retry-failed to ask "
            "again the questions that failed."
        )

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
