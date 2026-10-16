"""The research projects the researcher gives the lab to carry out, and what they found.

A project is one goal, put to the lab's lead, who chooses a team (or leads the one in the settings), makes a plan, and
decides each step, a meeting or code, until the critic accepts its answer, or its budget or its rounds run out, or the
plan stops moving forward. It is kept in a directory of its own in the workspace's projects/. The work is the library's:
every step is saved as it is taken, so a project that stopped, for its budget, its rounds, a failure, or a request to
stop, carries on where it stopped when it is started again, reading back for nothing the steps it took. It takes
minutes or hours, so it is a job, which a page follows and may stop.

A project is set up when it is made, with who leads and where code runs, and keeps that, so that carrying it on is
carrying on the same project, as the library requires: it refuses steps that were taken with another lead, team, or
memory.
"""

import json
import re
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from virtual_lab.constants import (
    MEMORY_FILE_NAME,
    PROJECT_FILE_NAME,
    REPORT_FILE_NAME,
    REPORT_MARKDOWN_FILE_NAME,
    RESEARCH_LOG_FILE_NAME,
)
from virtual_lab.environment import StoppedError
from virtual_lab.events import MeetingEvent, ProjectEvent
from virtual_lab.execution import LocalExecutor
from virtual_lab.llm import ModelSource
from virtual_lab.planning import NextStep, ProjectReport, check_titles_are_free, run_project
from virtual_lab.project import Project
from virtual_lab.prompts import SCIENTIFIC_CRITIC
from virtual_lab.provenance import describe_agent, utc_timestamp
from virtual_lab.schemas import normalize_title
from virtual_lab.server.benchmarks import finite
from virtual_lab.server.code import CodeSetup
from virtual_lab.server.config import ChatConfig, resolve_config
from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.jobs import Job, JobConflictError, Jobs
from virtual_lab.server.papers import StopWork, check_budget, check_count, check_model, money
from virtual_lab.server.transcripts import read_turns
from virtual_lab.server.workspace import Workspace, claim_directory, has_control_character, read_json
from virtual_lab.utils import write_atomically

# What a project is, kept beside what the library saves of it, and where code runs for it
LAB_FILE = "lab.json"
SESSION_DIR = "session"

# The one kind of job, of which only one is running at a time, since each may start a container and spends
JOB_KIND = "project"

MAX_PROJECTS = 200
MAX_TITLE_CHARS = 200
MAX_GOAL_CHARS = 20_000

# The most findings a page is sent, and of a step's output or file, in characters
MAX_FINDINGS = 1000
MAX_STEP_CHARS = 100_000

# How long a title made of the goal is, in characters
DERIVED_TITLE_CHARS = 80

# Of a project's id and a step's name, which name the directories and files that hold them
NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")

# Who is on the project, each with what it is
TEAMS = {
    "chosen": (
        "The lead chooses",
        "The lead chooses the scientists the goal needs, and changes the team as the work goes on.",
    ),
    "lab": (
        "The whole lab",
        "The lead works with every scientist the lab has, and may change the team as the work goes on.",
    ),
}

# How each step is given what the work before it found
MEMORIES = {
    "pick": (
        "The lead picks",
        "The lead sees every finding and names those each step needs, which the step is given in full.",
    ),
    "bm25": ("The best matches", "Each step is given the findings that best match what it is asked to do."),
    "summaries": (
        "Every summary",
        "Each step is given the summary of every step before it, so what it is given grows with the work.",
    ),
}

# What is asked of a project that the library lets be raised to carry on, and of one that it does not, with the default
# and the least and most of each
LIMITS = {
    "max_team_size": (3, 0, 6),
    "meeting_rounds": (1, 0, 5),
    "findings_per_step": (8, 1, 50),
    "max_rounds": (10, 1, 100),
    "max_stalled_rounds": (3, 1, 100),
}
LABELS = {
    "max_team_size": "The most scientists on the team",
    "meeting_rounds": "The rounds of discussion in a meeting",
    "findings_per_step": "The most findings a step is given",
    "max_rounds": "The most rounds",
    "max_stalled_rounds": "The most rounds in a row without more of the plan done",
}
DEFAULT_MEMORY = "pick"
DEFAULT_TEAM = "chosen"

# What a project that was stopped says of why, for the library's report says the hook that asks before each round did
STOPPED_REASON = "Stopped at the person's request."

# How a step's name says which round it was taken in
ROUND_STEP = re.compile(r"round_(\d+)_")

# What a project's log says it ended as, besides "running", which a log left by a process that stopped says
ENDINGS = frozenset({"finished", "out_of_budget", "out_of_rounds", "stalled", "stopped", "failed"})


def check_name(text: str) -> bool:
    return bool(text) and all(char in NAME_CHARS for char in text) and text not in {".", ".."}


def is_lab(value: Any) -> bool:
    """Whether what a project's file holds is a project's: its title, goal, who is on the team, how the team is
    limited, how findings are given, the configuration it works with, and when it was made."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("title"), str)
        and isinstance(value.get("goal"), str)
        and isinstance(value.get("created_at"), str)
        and value.get("team") in TEAMS
        and value.get("memory") in MEMORIES
        and all(isinstance(value.get(name), int) for name in ("max_team_size", "meeting_rounds", "findings_per_step"))
        and isinstance(value.get("config"), dict)
    )


def text_of(value: Any) -> str:
    return value if isinstance(value, str) else ""


def words(value: Any) -> list[str]:
    """A list of text, as a page is sent one, of whatever was saved: what is not text is left out."""
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def member_row(value: Any) -> dict[str, str] | None:
    """A scientist as a page is shown one: who it is and what it knows."""
    if not isinstance(value, dict) or not isinstance(value.get("title"), str):
        return None

    return {"title": value["title"], "expertise": text_of(value.get("expertise"))}


def members(value: Any) -> list[dict[str, str]]:
    return [row for item in value if (row := member_row(item)) is not None] if isinstance(value, list) else []


def round_row(value: Any) -> dict[str, Any] | None:
    """A round as a page is shown one: what the lead decided and how it went, from the research log."""
    if not isinstance(value, dict) or isinstance(value.get("number"), bool) or not isinstance(value.get("number"), int):
        return None
    proposed = value["proposed"] if isinstance(value.get("proposed"), dict) else {}
    decided = value["approved"] if isinstance(value.get("approved"), dict) else proposed

    return {
        "number": value["number"],
        "action": text_of(decided.get("action")),
        "participants": words(decided.get("participants")),
        "agenda": text_of(decided.get("agenda")),
        "questions": words(decided.get("agenda_questions")),
        "rationale": text_of(decided.get("rationale")),
        "progress": text_of(proposed.get("progress")),
        "answer": text_of(decided.get("answer")),
        "outcome": text_of(value.get("outcome")),
        "note": text_of(value.get("note")),
        "steps": words(value.get("steps")),
        "tasks_done": value["tasks_done"] if isinstance(value.get("tasks_done"), int) else 0,
        "findings": words(value.get("findings")),
        "found": words(value.get("found")),
    }


def finding_row(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not isinstance(value.get("claim"), str):
        return None

    return {
        "id": value["id"],
        "claim": value["claim"],
        "evidence": text_of(value.get("evidence")),
        "source": text_of(value.get("source")),
        "round": value["round"] if isinstance(value.get("round"), int) else None,
    }


def describe_event(event: ProjectEvent) -> str:
    """What happened in a project, in a line, as the job tells a page of it."""
    data = event.data
    where = f"Round {event.round}: " if event.round else ""
    if event.kind == "team":
        titles = [member["title"] for member in members(data.get("team"))]

        return f"The team: {', '.join(titles)}" if titles else "The lead works without a team"
    if event.kind == "plan":
        count = len(data["plan"]) if isinstance(data.get("plan"), list) else 0

        return f"The plan has {count} task{'s' if count != 1 else ''}"
    if event.kind == "decided":
        proposed = data.get("proposed")
        proposed = proposed if isinstance(proposed, dict) else {}
        action = text_of(proposed.get("action")).replace("_", " ")
        agenda = " ".join(text_of(proposed.get("agenda")).split())
        agenda = agenda[:117] + "..." if len(agenda) > 120 else agenda

        return f"{where}{action}{': ' + agenda if agenda else ''}"
    if event.kind == "code":
        return f"{where}code was run, and it {'worked' if data.get('succeeded') else 'did not'}"
    if event.kind == "round":
        saved = data.get("round")
        outcome = text_of(saved.get("outcome")) if isinstance(saved, dict) else ""

        return f"{where}ended: {outcome.replace('_', ' ')}"

    return f"The project ended: {event.text}"


def describe_report(report: ProjectReport) -> str:
    """What a project did, in a sentence or two."""
    done = sum(task.get("status") == "done" for task in report.plan)
    line = f"{report.status.replace('_', ' ').capitalize()} after {len(report.rounds)} round"
    line += "" if len(report.rounds) == 1 else "s"
    line += f", with {done} of {len(report.plan)} tasks done, spending {money(report.spent)}."

    return line


class Projects:
    """The research projects the lab is given, kept in a workspace.

    :param workspace: Where they are kept.
    :param jobs: Where the work is done, which a page follows.
    :param missing_keys: Says which variables a model's provider needs that are not set.
    :param client: An OpenAI client to work with, which is for tests.
    :param chat_models: The chat models to work with, which is for tests.
    :param docker_missing: Says what code in Docker, set up as it is given, cannot run without, or None to leave that
        until the code first runs.
    """

    def __init__(
        self,
        workspace: Workspace,
        jobs: Jobs,
        missing_keys: Callable[[str], list[str]],
        client: Any = None,
        chat_models: ModelSource | None = None,
        docker_missing: Callable[[CodeSetup], list[dict[str, str]]] | None = None,
    ) -> None:
        self.workspace = workspace
        self.jobs = jobs
        self.missing_keys = missing_keys
        self.client = client
        self.chat_models = chat_models
        self.docker_missing = docker_missing
        # Held from checking that nothing is being done to a project to starting something, so that nothing is begun in
        # a project that is being removed
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self.workspace.projects_dir

    # Projects

    def describe(self) -> dict[str, Any]:
        """Every project, the latest first, and what a page needs to make one."""
        projects = []
        if self.root.is_dir():
            for directory in self.root.iterdir():
                lab = read_json(directory / LAB_FILE)
                if check_name(directory.name) and directory.is_dir() and is_lab(lab):
                    projects.append(self.entry(directory, lab))

        settings = self.workspace.load_settings()
        try:
            config = self.settings_config()
            lead: str | None = config.lead["title"]
            team = [member["title"] for member in config.team if member["title"] != SCIENTIFIC_CRITIC.title]
        except ApiError:
            lead, team = None, []

        return {
            "projects": sorted(projects, key=lambda project: (project["created_at"], project["id"]), reverse=True),
            "teams": [{"id": name, "title": title, "summary": summary} for name, (title, summary) in TEAMS.items()],
            "memories": [
                {"id": name, "title": title, "summary": summary} for name, (title, summary) in MEMORIES.items()
            ],
            "limits": {
                name: {"label": LABELS[name], "default": default, "least": least, "most": most}
                for name, (default, least, most) in LIMITS.items()
            },
            "default_team": DEFAULT_TEAM,
            "default_memory": DEFAULT_MEMORY,
            "max_goal_chars": MAX_GOAL_CHARS,
            "model": settings.model,
            "code": {"where": settings.code, "sandbox": settings.sandbox},
            "lead": lead,
            "team": team,
        }

    def settings_config(self) -> ChatConfig:
        """What the lab is set up with in the settings now, with nothing a conversation is given besides the lab.

        :raises ApiError: If the settings cannot be used.
        """
        settings = self.workspace.load_settings()
        try:
            return resolve_config(
                {"model": settings.model, "tools": [], "mcp": [], "data": [], "software": [], "functions": []},
                settings,
                self.workspace,
            )
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from None

    def saved(self, directory: Path) -> tuple[Any, Any, Any, Any]:
        """What the library saved of a project, each as it was read, which is None where there is none that can be
        read: the research log, the ledger of steps, the report, and the findings."""
        log, ledger, report, memory = (
            read_json(directory / name)
            for name in (RESEARCH_LOG_FILE_NAME, PROJECT_FILE_NAME, REPORT_FILE_NAME, MEMORY_FILE_NAME)
        )

        return (
            log if isinstance(log, dict) else None,
            ledger if isinstance(ledger, dict) else None,
            report if isinstance(report, dict) else None,
            memory if isinstance(memory, dict) else None,
        )

    @staticmethod
    def state_of(log: dict[str, Any] | None, job: Job | None) -> str:
        """How a project stands: new, running, how it ended, or interrupted if the process working on it stopped."""
        if job is not None:
            return "running"
        if log is None:
            return "new"

        return log["status"] if log.get("status") in ENDINGS else "interrupted"

    def entry(self, directory: Path, lab: dict[str, Any]) -> dict[str, Any]:
        """A project as a list shows it: what it is, how it stands, and what it has spent."""
        log, ledger, _, _ = self.saved(directory)
        job = self.running(directory.name)
        plan = log.get("plan") if log is not None else None
        tasks = [task for task in plan if isinstance(task, dict)] if isinstance(plan, list) else []
        rounds = log.get("rounds") if log is not None else None

        return {
            "id": directory.name,
            "title": lab["title"],
            "goal": lab["goal"],
            "created_at": lab["created_at"],
            "model": lab["config"].get("model"),
            "state": self.state_of(log, job),
            "rounds_taken": len(rounds) if isinstance(rounds, list) else 0,
            "tasks": len(tasks),
            "tasks_done": sum(task.get("status") == "done" for task in tasks),
            "spent": finite(ledger.get("spent")) if ledger is not None else 0.0,
            "max_cost": finite(ledger.get("max_cost")) if ledger is not None else None,
            "job": job.id if job is not None else None,
        }

    def lookup(self, project_id: str) -> tuple[Path, dict[str, Any]]:
        """Where a project is kept, and what it is.

        :raises ApiError: If there is no project with this id.
        """
        directory = self.root / project_id
        lab = read_json(directory / LAB_FILE) if check_name(project_id) else None
        if not is_lab(lab):
            raise not_found("project with that id")

        return directory, lab

    def running(self, project_id: str) -> Job | None:
        """The job that is working on a project, if one is."""
        return next((job for job in self.jobs.active() if job.kind == JOB_KIND and job.subject == project_id), None)

    @staticmethod
    def check_limit(name: str, value: Any) -> int:
        """A limit, which is its default if it is not given.

        :raises ApiError: If it is not a whole number in its range.
        """
        default, least, most = LIMITS[name]

        return default if value is None else check_count(value, LABELS[name], least, most)

    def create(
        self,
        goal: str,
        title: str | None = None,
        team: str = DEFAULT_TEAM,
        max_team_size: Any = None,
        meeting_rounds: Any = None,
        memory: str = DEFAULT_MEMORY,
        findings_per_step: Any = None,
    ) -> str:
        """Makes a project with nothing done yet, which keeps who leads and where code runs, as they are in the
        settings now.

        :param goal: What the project is for.
        :param title: What it is called, or None for the start of the goal.
        :param team: "chosen" for the lead to choose the team, or "lab" for every scientist the lab has.
        :param max_team_size: The most scientists the lead may choose, or None for the default.
        :param meeting_rounds: The rounds of discussion in a meeting, and of criticism in an individual one, or None
            for the default.
        :param memory: How each step is given what the work before it found: "pick", "bm25", or "summaries".
        :param findings_per_step: The most findings a step is given with "bm25", or None for the default.
        :raises ApiError: If the goal, title, or an option is not fit, the settings cannot be used, the team is not
            fit, or there are too many projects.
        :return: Its id.
        """
        asked = goal.strip() if isinstance(goal, str) else ""
        if not asked or len(asked) > MAX_GOAL_CHARS or any(
            has_control_character(line) for line in asked.replace("\t", " ").splitlines()
        ):
            raise ApiError(422, "invalid", f"A project's goal is one to {MAX_GOAL_CHARS} characters of text")
        if title is None or not title.strip():
            named = " ".join(asked.split())
            named = named if len(named) <= DERIVED_TITLE_CHARS else named[: DERIVED_TITLE_CHARS - 1].rstrip() + "…"
        else:
            named = " ".join(title.split())
        if len(named) > MAX_TITLE_CHARS or has_control_character(named):
            raise ApiError(422, "invalid", f"A project is called by one to {MAX_TITLE_CHARS} characters, not {title!r}")
        if team not in TEAMS:
            raise ApiError(422, "invalid", f"The team is one of {', '.join(TEAMS)}, not {team!r}")
        if memory not in MEMORIES:
            raise ApiError(422, "invalid", f"The memory is one of {', '.join(MEMORIES)}, not {memory!r}")

        config = self.settings_config()
        lab = {
            "title": named,
            "goal": asked,
            "team": team,
            "max_team_size": self.check_limit("max_team_size", max_team_size),
            "meeting_rounds": self.check_limit("meeting_rounds", meeting_rounds),
            "memory": memory,
            "findings_per_step": self.check_limit("findings_per_step", findings_per_step),
            "config": config.to_dict(),
            "created_at": utc_timestamp(),
        }
        self.arguments(lab, config)

        self.root.mkdir(parents=True, exist_ok=True)
        if sum(1 for path in self.root.iterdir() if path.is_dir()) >= MAX_PROJECTS:
            raise ApiError(409, "too_many", f"No more than {MAX_PROJECTS} projects can be kept. Delete some first")
        directory = claim_directory(self.root, named)
        try:
            write_atomically(directory / LAB_FILE, json.dumps(lab, indent=4).encode("utf-8"))
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise

        return directory.name

    @staticmethod
    def arguments(lab: dict[str, Any], config: ChatConfig) -> tuple[Any, Any, Any]:
        """Who leads a project, who is its critic, and its team, or None for the lead to choose one.

        :raises ApiError: If the titles of the lead, the critic, and the team are not all different.
        """
        lead = config.lead_agent()
        critic = SCIENTIFIC_CRITIC.with_model(config.model)
        team = None
        if lab["team"] == "lab":
            # The critic is on every project, so it is not on the team as well
            team = tuple(
                agent for agent in config.team_agents() if normalize_title(agent.title) != normalize_title(critic.title)
            )
        try:
            if normalize_title(lead.title) == normalize_title(critic.title):
                raise ValueError(f"The lead and the critic must have different titles, and both are {lead.title}")
            if team is not None:
                check_titles_are_free(team, taken=(lead, critic))
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from None

        return lead, critic, team

    def delete(self, project_id: str) -> None:
        """Deletes a project, with everything it found.

        :raises ApiError: If there is no project with this id, or it is being worked on.
        """
        with self._lock:
            directory, _ = self.lookup(project_id)
            self.check_idle(project_id)
            shutil.rmtree(directory)

    def check_idle(self, project_id: str) -> None:
        if (job := self.running(project_id)) is not None:
            raise ApiError(409, "busy", f"{job.title} is running. Stop it first", job=job.snapshot())

    # What was done

    def view(self, project_id: str) -> dict[str, Any]:
        """A project, with its team, plan, rounds, findings, steps, and how it ended.

        :raises ApiError: If there is no project with this id.
        """
        directory, lab = self.lookup(project_id)
        log, ledger, report, memory = self.saved(directory)
        log, report, memory = log or {}, report or {}, memory or {}
        entry = self.entry(directory, lab)
        config = lab["config"]
        code = config.get("code") if isinstance(config.get("code"), dict) else {}
        lead = members([log.get("team_lead")])
        critic = members([log.get("critic")])
        # Before the lab has worked, the team is the settings' if that is what it is to have, and the lead's choice
        # is not known
        if log:
            team = members(log.get("team"))
        else:
            team = [row for row in members(config.get("team")) if row["title"] != SCIENTIFIC_CRITIC.title]
            team = team if lab["team"] == "lab" else []
        plan = [task for task in log["plan"] if isinstance(task, dict)] if isinstance(log.get("plan"), list) else []
        rounds = log["rounds"] if isinstance(log.get("rounds"), list) else []
        found = memory["findings"] if isinstance(memory.get("findings"), list) else []
        steps = ledger["steps"] if ledger is not None and isinstance(ledger.get("steps"), list) else []
        error = log.get("error")

        return {
            **entry,
            "team_mode": lab["team"],
            "max_team_size": lab["max_team_size"],
            "meeting_rounds": lab["meeting_rounds"],
            "memory": lab["memory"],
            "findings_per_step": lab["findings_per_step"],
            "code": {key: code.get(key) for key in ("where", "sandbox", "network", "resources")},
            "lead": lead[0] if lead else member_row(config.get("lead")),
            "critic": critic[0] if critic else member_row(describe_agent(SCIENTIFIC_CRITIC)),
            "team": team,
            "plan": [
                {"task": task["task"], "status": text_of(task.get("status"))}
                for task in plan
                if isinstance(task.get("task"), str)
            ],
            "rounds": [
                self.settled_round(row, entry["state"])
                for row in (round_row(raw) for raw in rounds)
                if row is not None
            ],
            "findings": [row for row in (finding_row(raw) for raw in found) if row is not None][:MAX_FINDINGS],
            "answer": text_of(report.get("answer")) or None,
            "proposed_answer": text_of(report.get("proposed_answer")) or None,
            "objections": words(report.get("objections")),
            "reason": STOPPED_REASON if report.get("status") == "stopped" else text_of(report.get("reason")) or None,
            "report": bool(report) and (directory / REPORT_MARKDOWN_FILE_NAME).is_file(),
            "error": text_of(error.get("message")) if isinstance(error, dict) else None,
            "steps": [row for row in (self.step_row(raw) for raw in steps) if row is not None],
        }

    @staticmethod
    def settled_round(row: dict[str, Any], state: str) -> dict[str, Any]:
        """A round as it stands: one the log says is running is not, if nothing is working on the project."""
        if row["outcome"] == "running" and state != "running":
            return {**row, "outcome": "interrupted"}

        return row

    @staticmethod
    def step_row(value: Any) -> dict[str, Any] | None:
        """A step as a list shows it: what it is, how it ended, and what it cost."""
        if not isinstance(value, dict) or not isinstance(value.get("name"), str):
            return None
        usage = value["usage"] if isinstance(value.get("usage"), dict) else {}
        error = value.get("error")
        numbered = ROUND_STEP.match(value["name"])

        return {
            "name": value["name"],
            "kind": text_of(value.get("kind")),
            "status": text_of(value.get("status")),
            "round": int(numbered.group(1)) if numbered else None,
            "cost": finite(usage.get("cost")),
            "elapsed": finite(value.get("elapsed_seconds")),
            "started_at": text_of(value.get("started_at")) or None,
            "error": text_of(error.get("message")) if isinstance(error, dict) else None,
        }

    def step(self, project_id: str, name: str) -> dict[str, Any]:
        """One step of a project: what it cost, what it produced, and what was said, or the code that was run.

        :raises ApiError: If there is no project with this id, or it took no step of that name.
        """
        directory, _ = self.lookup(project_id)
        _, ledger, _, _ = self.saved(directory)
        steps = ledger["steps"] if ledger is not None and isinstance(ledger.get("steps"), list) else []
        taken = next((raw for raw in steps if isinstance(raw, dict) and raw.get("name") == name), None)
        row = self.step_row(taken)
        if taken is None or row is None:
            raise not_found("step of that name in the project")

        files = taken.get("files") if isinstance(taken.get("files"), dict) else {}
        turns, truncated = None, False
        if isinstance(files.get("transcript"), str):
            turns, truncated = read_turns(directory, files["transcript"])
        output = self.saved_file(directory, files.get("output"))
        # A meeting's record is of a meeting, which the turns and output say more of; only code has an execution record
        record = self.saved_file(directory, files.get("record")) if row["kind"] == "repair" else None
        code = attempts = succeeded = None
        if isinstance(record, dict):
            attempts = record["num_attempts"] if isinstance(record.get("num_attempts"), int) else None
            succeeded = record["succeeded"] if isinstance(record.get("succeeded"), bool) else None
            code = [
                {
                    "filename": text_of(file.get("filename")),
                    "language": text_of(file.get("language")),
                    "contents": text_of(file.get("contents"))[:MAX_STEP_CHARS],
                    "output": self.last_output(record, text_of(file.get("filename"))),
                }
                for file in (record.get("final_files") if isinstance(record.get("final_files"), list) else [])
                if isinstance(file, dict)
            ]
        usage = taken["usage"] if isinstance(taken.get("usage"), dict) else None

        return {
            **row,
            "usage": usage,
            "turns": turns,
            "truncated": truncated,
            "output": output,
            "code": code,
            "attempts": attempts,
            "succeeded": succeeded,
        }

    @staticmethod
    def last_output(record: dict[str, Any], filename: str) -> str | None:
        """What a file printed the last time it was run, as the execution record has it."""
        attempts = record.get("attempts")
        if not isinstance(attempts, list) or not attempts or not isinstance(attempts[-1], dict):
            return None
        for run in attempts[-1].get("runs", []):
            if isinstance(run, dict) and run.get("filename") == filename:
                shown = "\n".join(text for text in (text_of(run.get("stdout")), text_of(run.get("stderr"))) if text)

                return shown[:MAX_STEP_CHARS]

        return None

    @staticmethod
    def saved_file(directory: Path, relative: Any) -> Any:
        """What a file a step saved holds, as JSON, if it is in the project and not too long to send, or None."""
        if not isinstance(relative, str):
            return None
        path = (directory / relative).resolve()
        # What the ledger names is read only if it is in the project, which a file edited by hand may not be
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            return None
        found = read_json(path)

        return found if len(json.dumps(found)) <= MAX_STEP_CHARS else None

    def report_file(self, project_id: str) -> Path:
        """The report of how a project ended, as the library wrote it, for the person to keep.

        :raises ApiError: If there is no project with this id, or it has not ended.
        """
        directory, _ = self.lookup(project_id)
        path = directory / REPORT_MARKDOWN_FILE_NAME
        if not path.is_file():
            raise not_found("report of that project, which has not ended")

        return path

    # Working

    def start(self, project_id: str, max_cost: Any, max_rounds: Any = None, max_stalled_rounds: Any = None) -> Job:
        """Starts working on a project, or carries it on from the step it stopped at, reading back for nothing the
        steps it took.

        :param max_cost: The most the project may spend, in USD, over every time it is worked on. Raising it carries
            on a project that ran out.
        :param max_rounds: The most rounds, each a decision and its step, or None for the default. Raising it carries on
            a project that ran out.
        :param max_stalled_rounds: How many rounds in a row may pass without one more task done, or None for the
            default.
        :raises ApiError: If there is no project with this id, a limit is not fit, a key or a price is missing, Docker
            is needed and is not there, or the project is being worked on.
        """
        directory, lab = self.lookup(project_id)
        budget = check_budget(max_cost, "The most it may spend", required=True)
        rounds = self.check_limit("max_rounds", max_rounds)
        stalled = self.check_limit("max_stalled_rounds", max_stalled_rounds)
        try:
            config = ChatConfig.from_dict(lab["config"])
        except (KeyError, TypeError, ValueError):
            raise ApiError(
                409, "invalid", "What this project works with was not kept in a way that can be read"
            ) from None
        check_model(config.model, self.missing_keys)
        if self.docker_missing is not None and (missing := self.docker_missing(config.code)):
            raise ApiError(
                409,
                "setup_needed",
                " ".join(issue["message"] for issue in missing),
                missing=[issue["id"] for issue in missing],
            )
        lead, critic, team = self.arguments(lab, config)

        work = self.runner(directory, lab, config, (lead, critic, team), budget, rounds, stalled)
        with self._lock:
            # Looked for again, as a project that was deleted while the checks above were made has no place to work in
            self.lookup(project_id)
            try:
                return self.jobs.start(JOB_KIND, project_id, f"Working on {lab['title']}", work, exclusive=JOB_KIND)
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def runner(
        self,
        directory: Path,
        lab: dict[str, Any],
        config: ChatConfig,
        who: tuple[Any, Any, Any],
        max_cost: float,
        max_rounds: int,
        max_stalled_rounds: int,
    ) -> Callable[[Job], str | None]:
        """What a job does to work on a project: runs it to its goal, round by round, telling the job as it goes."""
        lead, critic, team = who

        def work(job: Job) -> str | None:
            if job.stop.is_set():
                raise StoppedError("Stopped before anything was done.")
            job.update("Starting", round=0, max_rounds=max_rounds, max_cost=max_cost)

            def check_stop() -> None:
                if job.stop.is_set():
                    raise StopWork

            code = config.code
            options: dict[str, Any] = {"before_request": check_stop, "interrupt": check_stop}
            session = executor = None
            if code.where != "none":
                options.update(code_actions="tags", resources=code.resources)
                (directory / SESSION_DIR).mkdir(parents=True, exist_ok=True)
                session = code.session(directory / SESSION_DIR)
                executor = code.docker_executor() if code.where == "docker" else LocalExecutor(warn=False)
            else:
                options["resources"] = "none"
            try:
                project = Project(
                    directory,
                    lab["goal"],
                    max_cost=max_cost,
                    session=session,
                    chat_models=self.chat_models,
                    client=self.client,
                    **options,
                )

                def approve(number: int, decision: NextStep) -> NextStep | None:
                    # Asked before each round, so that a request to stop ends the project with a report, rather than
                    # in the middle of a step
                    return None if job.stop.is_set() else decision

                def tell(event: MeetingEvent | ProjectEvent) -> None:
                    job.update(spent=finite(project.spent))
                    if isinstance(event, MeetingEvent):
                        if event.kind == "turn" and event.speaker:
                            job.update(f"{event.speaker} is speaking")
                    else:
                        line = describe_event(event)
                        job.log(line)
                        job.update(line)
                        if event.round is not None:
                            job.update(round=event.round)

                job.update(spent=finite(project.spent))
                report = run_project(
                    project,
                    team_lead=lead,
                    critic=critic,
                    team=team,
                    max_team_size=lab["max_team_size"],
                    max_rounds=max_rounds,
                    max_stalled_rounds=max_stalled_rounds,
                    meeting_rounds=lab["meeting_rounds"],
                    executor=executor,
                    approve=approve,
                    repair_options={"before_request": check_stop},
                    memory=lab["memory"],
                    findings_per_step=lab["findings_per_step"],
                    on_event=tell,
                )
            except StopWork:
                self.settle(directory)
                raise StoppedError(
                    "Stopped. What was done is kept, and starting again carries on from there."
                ) from None
            finally:
                if session is not None:
                    session.close()
            if report.status == "stopped":
                raise StoppedError("Stopped. What was done is kept, and starting again carries on from there.")

            return describe_report(report)

        return work

    @staticmethod
    def settle(directory: Path) -> None:
        """Writes down that a project was stopped, which the library, whose log says it failed with the request that
        stopped it, does not, so that a page shows it as stopped."""
        path = directory / RESEARCH_LOG_FILE_NAME
        log = read_json(path)
        if not isinstance(log, dict):
            return
        error = log.get("error")
        if log.get("status") == "failed" and isinstance(error, dict) and error.get("type") == StopWork.__name__:
            log.update(status="stopped", error=None)
            write_atomically(path, json.dumps(log, indent=4).encode("utf-8"))
