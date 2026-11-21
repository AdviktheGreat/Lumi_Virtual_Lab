"""Making an agent in one go: the steps that need no decision, one after another, as one job.

A PaperAgent is made by steps that a person asks for one at a time: reading the paper, fetching the code and looking at
it, building the environment, running the tutorials, making the tools, checking them, and giving the agent to the
conversations. Making it in one go does them in that order for the person, and stops where they are to say something.
Each step is the PaperAgent's own, started as a page would start it and waited for, so that what is made in one go is
what anyone could have made by hand, and can be looked at and carried on on the agent's page. A step that has been done
is not done again. Nothing here reaches into an agent's files to say that a step is done: what a step came to is asked
of the PaperAgent.

The order is the one that costs least. Where the code is known, it is fetched and looked at before the paper is read,
which is the one step that is paid for in model requests, so that code that cannot be used is not paid for; and looked
at again once the paper has been read, since what the paper says of the licence and the data bears on it. Reading is
given the most it may spend, which is the only spending there is: the other steps run on this machine and ask no model.

What stands in the way is one of these, and is said in words and kept with the agent:

- waiting: it is for the person to say. The paper's file, when the paper is a file that was not uploaded, or its text,
  when it could not be fetched; more to spend, when reading reached its limit, which carries on from where it stopped;
  where the code is, when nobody has said, with the places that the paper points to, which are never taken to be the
  code until the person says; whether to go on, when looking at the code says to ask or says no-go, which is said of
  the commit that was looked at and not of another; or that Docker or Git is to be started or installed.
- failed: a step went wrong, which may not go wrong the next time it is asked for.
- stopped: the person stopped it, the server did, or something else was started on the agent.

A step that cannot be done for what the code is, an environment that cannot be built here, no tutorial that can be run,
or none of the calls that the tutorials made coming to a tool, is skipped, with why, and so are those that need it. The
agent is then one of the paper only, as far as the code allows, and is given as that: it is not said to be made of more.

Nothing is run but by the steps, and each is the step of a PaperAgent, in the containers that it uses. The agent is
given to conversations as the last step, unless the request says not.

What was asked and how each step went is kept in the agent's directory as onego.json, so that it can be shown and
gone on from when the job is gone, which it is when the server has been stopped. A file that is not in the shape that
it is kept in is not used, as it may not be if it was edited.
"""

import json
import math
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from virtual_lab.environment import StoppedError
from virtual_lab.paperagents import checking as verifying
from virtual_lab.paperagents import repository as cloning
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_checks as kept_checks
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server.errors import ApiError
from virtual_lab.server.jobs import Job, JobConflictError
from virtual_lab.server.paperagents import (
    ONEGO_JOB,
    PaperAgents,
    check_repo,
    is_blank,
    is_given,
    kept_tools_of,
    steps_of,
)
from virtual_lab.server.papers import check_budget, check_flag, money
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import write_atomically

RECORD_FILE = "onego.json"
# What a record says of how it is kept, so that a later version can read what an earlier one wrote
SCHEMA = 1
STATES = ("running", "done", "waiting", "failed", "stopped")
STEP_STATES = ("pending", "running", "done", "skipped", "waiting", "failed", "stopped")
MAX_RECORD_BYTES = 1 << 20
MAX_TEXT_CHARS = 1200
MOST_CANDIDATES = 8

# Seconds between looks at a step that a PaperAgent is doing
POLL_SECONDS = 0.2
# How many times a step is waited for another that was in its way before it is said to be
MOST_WAITS = 3

# What each step is, and what it is called to the person
TITLES = {
    "repository": "Fetch the code",
    "reading": "Read the paper",
    "look": "Look at the code against the paper",
    "environment": "Build the environment",
    "reference": "Run the tutorials",
    "tools": "Make the tools",
    "checks": "Check the tools",
    "given": "Give it to your conversations",
}
# What is not done for a step that could not be, since it needs what that makes
NEEDS = {
    "environment": ("reference", "tools", "checks"),
    "reference": ("tools", "checks"),
    "tools": ("checks",),
}
# What is not done when the person goes on without the code
CODE_STEPS = ("repository", "look", "environment", "reference", "tools", "checks")
# What a PaperAgent refuses a step with when it is so of the code, and not of anything that was asked
BLOCKS = ("unsupported", "no_tutorials", "no_tools", "no_reference")
STOPPED = "Stopped. What was made is kept, and making it in one go again carries on from there."


class Stuck(Exception):
    """What stands in the way of making an agent, for it to end and say.

    :param state: Whether it is for the person to say (waiting), a step that went wrong (failed), or that making was
        stopped (stopped).
    :param step: Which step it was at.
    :param kind: A short name for the reason, which a page can go by.
    :param reason: What it is, in words.
    :param details: What a page may show of it, such as the places the paper points to for the code.
    """

    def __init__(self, state: str, step: str, kind: str, reason: str, **details: Any) -> None:
        super().__init__(reason)
        self.state = state
        self.step = step
        self.kind = kind
        self.reason = reason
        self.details = details


class Cannot(Exception):
    """A step cannot be done for what the code is, which is not a failure: it is skipped, and so are those that need
    it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def printable(text: str) -> str:
    """Text for a record: on one line and not long."""
    return " ".join(text.split())[:MAX_TEXT_CHARS]


def is_step(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("step") in TITLES
        and value.get("state") in STEP_STATES
        and (value.get("note") is None or isinstance(value["note"], str))
    )


def is_settings(value: Any) -> bool:
    """Whether what a record says was asked is in the shape that asking keeps it, and nothing else: a damaged record is
    not gone on from, as one whose settings say what was never asked would do what was never asked."""
    if not isinstance(value, dict) or set(value) != {"max_cost", "repo", "ref", "give", "without_code", "go_on"}:
        return False
    cost = value["max_cost"]

    return (
        (cost is None or (isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost)))
        and all(value[name] is None or isinstance(value[name], str) for name in ("repo", "ref", "go_on"))
        and isinstance(value["give"], bool)
        and isinstance(value["without_code"], bool)
    )


def is_record(value: Any) -> bool:
    """Whether what a file holds is a record of making an agent in one go: when it began, how it stands, what was asked,
    and how each step went."""
    return (
        isinstance(value, dict)
        and value.get("schema") == SCHEMA
        and value.get("state") in STATES
        and isinstance(value.get("started_at"), str)
        and is_settings(value.get("settings"))
        and isinstance(value.get("steps"), list)
        and all(is_step(step) for step in value["steps"])
        and (value.get("stuck") is None or isinstance(value["stuck"], dict))
        and (value.get("summary") is None or isinstance(value["summary"], str))
    )


class OneGo:
    """The making of agents in one go.

    :param paperagents: The PaperAgents, whose steps are started and waited for, and which keep the agents.
    """

    def __init__(self, paperagents: PaperAgents) -> None:
        self.paperagents = paperagents
        self.jobs = paperagents.jobs
        # Held while a record is begun or taken away, so that two do not undo each other
        self._lock = threading.Lock()

    # What there is

    def load(self, directory: Path) -> dict[str, Any] | None:
        path = directory / RECORD_FILE
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
            return None
        record = read_json(path)

        return record if is_record(record) else None

    def save(self, directory: Path, record: dict[str, Any]) -> None:
        write_atomically(directory / RECORD_FILE, json.dumps(record, indent=2).encode("utf-8"))

    def state_of(self, agent_id: str, record: dict[str, Any] | None) -> str:
        """How making the agent in one go stands: none if it has not been asked for, and interrupted if a record says it
        is going and no job is, as it is when the server was stopped."""
        if self.paperagents.onego_job(agent_id) is not None:
            return "running"
        if record is None:
            return "none"

        return "interrupted" if record["state"] == "running" else str(record["state"])

    def order_for(self, agent: dict[str, Any], settings: dict[str, Any]) -> list[str]:
        """The steps, in the order they are done: the code first where it is known, so that it is looked at before the
        paper is paid to be read."""
        known = settings["repo"] or (agent.get("repo") or {}).get("url")
        first = ["repository", "reading"] if known else ["reading", "repository"]

        return [*first, "look", "environment", "reference", "tools", "checks", "given"]

    def view(self, agent_id: str) -> dict[str, Any]:
        """How making the agent in one go stands: what was asked, how each step went, what stands in the way, and the
        job that is doing it, if one is.

        :raises ApiError: If there is no agent with this id.
        """
        directory, agent = self.paperagents.lookup(agent_id)
        record = self.load(directory)
        job = self.paperagents.onego_job(agent_id)
        settings = record["settings"] if record is not None else self.settings_of(None, {})
        steps = (
            record["steps"]
            if record is not None
            else [{"step": step, "state": "pending", "note": None} for step in self.order_for(agent, settings)]
        )

        return {
            "id": agent_id,
            "state": self.state_of(agent_id, record),
            "started_at": record["started_at"] if record is not None else None,
            "finished_at": record.get("finished_at") if record is not None else None,
            "settings": settings,
            "steps": [{**step, "title": TITLES[step["step"]]} for step in steps],
            "stuck": record.get("stuck") if record is not None else None,
            "summary": record.get("summary") if record is not None else None,
            "job": job.snapshot() if job is not None else None,
        }

    def clear(self, agent_id: str) -> None:
        """Takes away what is kept of making the agent in one go, so that it is as if it had not been asked for.

        :raises ApiError: If there is no agent with this id, or it is being made.
        """
        with self._lock:
            directory, _ = self.paperagents.lookup(agent_id)
            if (job := self.paperagents.onego_job(agent_id)) is not None:
                raise ApiError(409, "busy", f"{job.title} is still going. Stop that first", job=job.snapshot())
            (directory / RECORD_FILE).unlink(missing_ok=True)

    # Asking for it

    def settings_of(self, earlier: dict[str, Any] | None, given: dict[str, Any]) -> dict[str, Any]:
        """What is asked, which is what was asked of this time and, of what is left out, what was asked before it, which
        a person who goes on after being asked something does not say again."""
        before = earlier or {}

        def chosen(name: str, default: Any) -> Any:
            return given[name] if given.get(name) is not None else before.get(name, default)

        return {
            "max_cost": chosen("max_cost", None),
            "repo": chosen("repo", None),
            "ref": chosen("ref", None),
            "give": chosen("give", True),
            "without_code": chosen("without_code", False),
            "go_on": given["go_on"] if "go_on" in given else before.get("go_on"),
        }

    def start(
        self,
        agent_id: str,
        max_cost: Any = None,
        repo: Any = None,
        ref: Any = None,
        give: Any = None,
        without_code: Any = None,
        go_on: Any = None,
    ) -> dict[str, Any]:
        """Starts making an agent in one go, or carries on where it stopped.

        :param max_cost: The most that reading the paper may spend, in USD, which is always said unless the paper has
            been read. Left out, it is what it was before.
        :param repo: Where the code is, when the agent does not say. Left out, it is the agent's, or what it was before.
        :param ref: A branch, a tag, or a commit of the code to fetch.
        :param give: Whether the agent is given to the conversations that are made from now on when it is made, which it
            is unless this says not.
        :param without_code: Whether to go on without the code, as an agent of the paper only.
        :param go_on: Whether to go on with the code as it was looked at, which is said of the commit that was fetched;
            false takes that back.
        :raises ApiError: If there is no agent with this id, what is given is not fit, the agent is one that another
            server hosts, nothing is said to spend and the paper is not read, a key or a price is missing, the code has
            been fetched from another address, or the agent is being worked on.
        :return: How it stands, as view says it, with the job.
        """
        directory, agent = self.paperagents.lookup(agent_id)
        if agent.get("imported") is not None:
            raise ApiError(
                422, "imported", "This agent is hosted by another server, and has no paper or code here to make it of"
            )
        given: dict[str, Any] = {}
        if max_cost is not None:
            given["max_cost"] = check_budget(max_cost, "The most it may spend", required=True)
        if not is_blank(repo):
            given["repo"] = check_repo(repo)
        if not is_blank(ref):
            try:
                given["ref"] = cloning.check_ref(ref if isinstance(ref, str) else str(ref))
            except cloning.RepositoryError as error:
                raise ApiError(422, "invalid", str(error)) from error
        if give is not None:
            given["give"] = check_flag(give, "Whether it is given")
        if without_code is not None:
            given["without_code"] = check_flag(without_code, "Whether to go on without the code")
        current = (agent.get("repo") or {}).get("url")
        intake = kept_repository.load(directory, current) if current is not None else None
        if given.get("repo") not in (None, current) and intake is not None:
            raise ApiError(
                409,
                "code_fetched",
                f"The code of this agent has been fetched from {current}. Take it away on the page of its code first, "
                "to use another address",
            )
        if go_on is not None:
            if check_flag(go_on, "Whether to go on with the code as it is looked at"):
                if intake is None:
                    raise ApiError(409, "no_code", "The code has not been fetched, so there is nothing to go on with")
                given["go_on"] = intake["commit"]
            else:
                given["go_on"] = None

        with self.paperagents._lock, self._lock:
            # With the lock that deleting an agent takes, from the last look at it to the job being there to be seen,
            # so that one cannot be deleted between them, which would leave its directory made again with only this
            directory, agent = self.paperagents.lookup(agent_id)
            earlier = self.load(directory)
            settings = self.settings_of(earlier["settings"] if earlier is not None else None, given)
            if (
                intake is not None
                and settings["ref"] is not None
                and settings["ref"]
                not in (
                    intake.get("ref"),
                    intake["commit"],
                )
            ):
                raise ApiError(
                    409,
                    "code_fetched",
                    f"The code of this agent has been fetched at {intake['commit'][:12]}"
                    + (f" ({intake['ref']})" if intake.get("ref") is not None else "")
                    + ". Take it away on the page of its code first, to fetch another branch, tag, or commit",
                )
            if steps_of(agent)["reading"] != "done":
                if settings["max_cost"] is None:
                    raise ApiError(422, "invalid", "Say the most that reading the paper may spend, in dollars")
                self.paperagents.usable_model()
            self.paperagents.check_idle(agent_id)
            record = {
                "schema": SCHEMA,
                "state": "running",
                "started_at": utc_timestamp(),
                "finished_at": None,
                "settings": settings,
                "steps": [{"step": step, "state": "pending", "note": None} for step in self.order_for(agent, settings)],
                "stuck": None,
                "summary": None,
            }
            self.save(directory, record)
            try:
                job = self.jobs.start(
                    ONEGO_JOB,
                    agent_id,
                    f"Making an agent in one go: {agent['title']}",
                    self.worker(agent_id, record),
                    exclusive=f"{ONEGO_JOB}:{agent_id}",
                )
            except JobConflictError as error:
                if earlier is not None:
                    self.save(directory, earlier)
                else:
                    (directory / RECORD_FILE).unlink(missing_ok=True)
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

        # The job is the one that was started, which a page follows, even if it has ended by now
        return {**self.view(agent_id), "job": job.snapshot()}

    # Making it

    def worker(self, agent_id: str, record: dict[str, Any]) -> Callable[[Job], str | None]:
        """What the job does: each step, in order, until one stands in the way, and keeps how it went, whether it came
        to the end, was stopped, or went wrong."""

        def work(job: Job) -> str | None:
            with self.paperagents.driving(agent_id):
                return self.make(job, agent_id, record)

        return work

    def make(self, job: Job, agent_id: str, record: dict[str, Any]) -> str:
        directory = self.paperagents.workspace.paperagents_dir / agent_id
        settings = record["settings"]
        dropped: dict[str, str] = {}
        if settings["without_code"]:
            dropped = dict.fromkeys(CODE_STEPS, "You chose to go on without the code.")
        steps = [step["step"] for step in record["steps"]]
        at = steps[0]
        job.update(steps=len(steps), finished=0)
        try:
            for number, step in enumerate(steps):
                at = step
                self.stop_if_asked(job)
                job.update(TITLES[step], step=step, detail="", finished=number)
                if step in dropped:
                    self.mark(directory, record, step, "skipped", dropped[step])
                    continue
                self.mark(directory, record, step, "running")
                try:
                    state, note = getattr(self, f"do_{step}")(job, agent_id, settings)
                    self.mark(directory, record, step, state, note)
                    if step == "repository" and steps_of(self.paperagents.lookup(agent_id)[1])["reading"] != "done":
                        self.look(agent_id, settings, read=False)
                except Cannot as cannot:
                    self.mark(directory, record, step, "skipped", cannot.reason)
                    dropped.update(dict.fromkeys(NEEDS.get(step, ()), f"Not done: {cannot.reason}"))
            job.update("Done", step=None, detail="", finished=len(steps))
        except StoppedError:
            self.end(directory, record, "stopped", at, {"kind": "stopped", "reason": STOPPED})
            raise
        except Stuck as stuck:
            self.end(
                directory,
                record,
                stuck.state,
                stuck.step,
                {"kind": stuck.kind, "reason": stuck.reason, **stuck.details},
            )
            if stuck.state == "stopped":
                raise StoppedError(stuck.reason) from None
            if stuck.state == "failed":
                raise ValueError(stuck.reason) from None

            return f"{TITLES[stuck.step]}: {stuck.reason}"
        except Exception as error:
            self.end(directory, record, "failed", at, {"kind": "error", "reason": f"{type(error).__name__}: {error}"})
            raise

        return self.finish(directory, record)

    def mark(self, directory: Path, record: dict[str, Any], step: str, state: str, note: str | None = None) -> None:
        """Keeps how a step is going."""
        for each in record["steps"]:
            if each["step"] == step:
                each["state"] = state
                each["note"] = printable(note) if note else None
        self.save(directory, record)

    def end(self, directory: Path, record: dict[str, Any], state: str, step: str, stuck: dict[str, Any]) -> None:
        """Keeps what stood in the way, on the step that it stood at, and that making has ended."""
        stuck = {**stuck, "step": step, "reason": printable(str(stuck["reason"]))}
        for each in record["steps"]:
            if each["step"] == step and each["state"] in ("running", "pending"):
                each["state"] = state
                each["note"] = stuck["reason"]
        record.update(state=state, stuck=stuck, finished_at=utc_timestamp())
        self.save(directory, record)

    def finish(self, directory: Path, record: dict[str, Any]) -> str:
        """Keeps that every step has been got to, and says what it came to."""
        skipped = [step for step in record["steps"] if step["state"] == "skipped" and step["step"] != "given"]
        given = next(step for step in record["steps"] if step["step"] == "given")
        parts = []
        if skipped:
            first = next((step["note"] for step in skipped if step["note"]), "")
            parts.append(f"Made as far as the code allows. {first}".rstrip())
        else:
            parts.append("Every step is done.")
        if given["state"] == "done":
            parts.append("It is given to the conversations you start from now on.")
        summary = printable(" ".join(parts))
        record.update(state="done", summary=summary, finished_at=utc_timestamp())
        self.save(directory, record)

        return summary

    def stop_if_asked(self, job: Job) -> None:
        if job.stop.is_set():
            raise StoppedError(STOPPED)

    # The steps, each of which says how it came out, or what stands in its way

    def agent_of(self, agent_id: str) -> dict[str, Any]:
        return self.paperagents.lookup(agent_id)[1]

    def do_repository(self, job: Job, agent_id: str, settings: dict[str, Any]) -> tuple[str, str]:
        agent = self.agent_of(agent_id)
        address = settings["repo"] or (agent.get("repo") or {}).get("url")
        if address is None:
            raise self.without_address(agent_id)
        child = self.run(
            job,
            "repository",
            lambda: self.paperagents.fetch_repository(agent_id, settings["repo"], settings["ref"]),
        )
        if steps_of(self.agent_of(agent_id))["repository"] != "done":
            raise Stuck("failed", "repository", "failed", "The code was not fetched")

        return "done", child.message if child is not None else "The code had been fetched."

    def without_address(self, agent_id: str) -> Stuck:
        """What stands in the way when nobody has said where the code is: the paper's pointers are what the person may
        say it by, which are not the code until they do."""
        pointed = [
            {"url": each["url"], "role": each["role"], "quote": each["facts"][0]["quote"][:300]}
            for each in self.paperagents.repository(agent_id)["candidates"][:MOST_CANDIDATES]
        ]
        if pointed:
            reason = (
                "No address of the code was given. The paper points to the projects below. Say which, if any, is its "
                "code, or go on without the code."
            )
        else:
            reason = (
                "No address of the code was given, and the paper does not point to any. Say where it is, or go on "
                "without it."
            )

        return Stuck("waiting", "repository", "code", reason, candidates=pointed)

    def look(self, agent_id: str, settings: dict[str, Any], read: bool) -> str:
        """Looks at the code and what the paper says of it, and says whether it is worth going on.

        :param read: Whether the paper has been read, so that this is the look that the person is asked at. Before it,
            only a no-go is acted on, since what the paper says of the licence and the data may change the rest, and
            code that cannot be used is not worth reading the paper for.
        :raises Stuck: If the look says no-go, or ask once the paper has been read, and the person has not said to go on
            with the code that was looked at.
        """
        found = self.paperagents.repository(agent_id)
        flight, intake = found["preflight"], found["intake"]
        if flight is None or intake is None:
            raise Stuck("failed", "look", "no_code", "The code has not been fetched, so it cannot be looked at")
        verdict = flight["verdict"]
        if verdict == "go" or (verdict == "ask" and not read):
            return str(flight["summary"])
        if settings["go_on"] == intake["commit"]:
            return f"{flight['summary']} You said to go on."
        weighed = [
            {"title": each["title"], "status": each["status"], "detail": each["detail"]}
            for each in flight["checks"]
            if each["status"] in ("warn", "block", "unknown")
        ]
        raise Stuck(
            "waiting",
            "look",
            "preflight",
            f"{flight['summary']} Go on if you accept that, or go on without the code.",
            verdict=verdict,
            commit=intake["commit"],
            checks=weighed,
        )

    def do_reading(self, job: Job, agent_id: str, settings: dict[str, Any]) -> tuple[str, str]:
        if steps_of(self.agent_of(agent_id))["reading"] == "done":
            return "done", "The paper had been read."
        child = self.run(job, "reading", lambda: self.paperagents.read(agent_id, settings["max_cost"]))
        agent = self.agent_of(agent_id)
        status = steps_of(agent)["reading"]
        if status == "done":
            return "done", child.message if child is not None else "The paper had been read."
        if status == "pending":
            spent = self.paperagents.reading(agent_id)["cost"]
            raise Stuck(
                "waiting",
                "reading",
                "limit",
                "Reading reached the limit on spending before the paper was read through"
                + (f", having spent {money(spent)} of the {money(settings['max_cost'])}" if spent is not None else "")
                + ". Say how much more it may spend and go on: it carries on from where it stopped.",
                spent=spent,
                limit=settings["max_cost"],
            )
        raise Stuck("failed", "reading", "failed", "No part of the paper could be read")

    def do_look(self, job: Job, agent_id: str, settings: dict[str, Any]) -> tuple[str, str]:
        return "done", self.look(agent_id, settings, read=True)

    def do_environment(self, job: Job, agent_id: str, settings: dict[str, Any]) -> tuple[str, str]:
        child = self.run(job, "environment", lambda: self.paperagents.build_environment(agent_id))
        if steps_of(self.agent_of(agent_id))["environment"] != "done":
            raise Stuck("failed", "environment", "failed", "The environment was not built")

        return "done", child.message if child is not None else "The environment had been built."

    def do_reference(self, job: Job, agent_id: str, settings: dict[str, Any]) -> tuple[str, str]:
        child = self.run(job, "reference", lambda: self.paperagents.start_reference(agent_id))
        directory, agent = self.paperagents.lookup(agent_id)
        if kept_tools_of(directory, agent)[0] is None:
            raise Cannot("The tutorials did not run to their end, so no tool can be made of what they did.")

        return "done", child.message if child is not None else "The tutorials had been run."

    def do_tools(self, job: Job, agent_id: str, settings: dict[str, Any]) -> tuple[str, str]:
        child = self.run(job, "tools", lambda: self.paperagents.start_tools(agent_id))
        if steps_of(self.agent_of(agent_id))["tools"] != "done":
            raise Cannot(
                (child.message if child is not None else "")
                or "No call that the tutorials made came to a tool that gives again what the tutorial got."
            )

        return "done", child.message if child is not None else "The tools had been made."

    def checked(self, agent_id: str) -> bool:
        """Whether every tool has been checked in each of the ways that need no model, and the checks are of what is
        kept now."""
        tools = self.paperagents.checks(agent_id)["tools"]

        return bool(tools) and all(
            entry["status"] not in (kept_checks.NOT_RUN, kept_checks.STALE)
            for tool in tools
            for entry in tool["evidence"]
            if entry["kind"] in verifying.DEFAULT_KINDS
        )

    def do_checks(self, job: Job, agent_id: str, settings: dict[str, Any]) -> tuple[str, str]:
        if not self.paperagents.checks(agent_id)["tools"]:
            raise Cannot("There is no tool to check.")
        if self.checked(agent_id):
            return "done", "The tools had been checked."
        child = self.run(job, "checks", lambda: self.paperagents.start_checks(agent_id))
        if not self.checked(agent_id):
            raise Stuck(
                "failed",
                "checks",
                "failed",
                "Not every check ran"
                + (f": {child.message}" if child is not None and child.message else "")
                + ". Ask again to carry on with those that are left.",
            )

        return "done", child.message if child is not None else "The tools had been checked."

    def do_given(self, job: Job, agent_id: str, settings: dict[str, Any]) -> tuple[str, str]:
        if not settings["give"]:
            return "skipped", "You asked for it not to be given to your conversations."
        if is_given(self.agent_of(agent_id)):
            return "done", "It was given to your conversations already."
        self.paperagents.change(agent_id, given=True)

        return "done", "Given to the conversations that you start from now on."

    # Doing a step of a PaperAgent, and waiting for it

    def run(self, job: Job, step: str, begin: Callable[[], Job]) -> Job | None:
        """Starts a step of a PaperAgent and waits for it to end.

        :param begin: Starts it, as a page would, which raises what a page is told if it cannot be.
        :return: The step's job, or None if the step had been done.
        :raises Stuck: If it cannot be started, failed, or was stopped by someone else.
        :raises Cannot: If it is so of the code that the step cannot be done.
        :raises StoppedError: If making was stopped, after the step had stopped.
        """
        try:
            child = self.start_step(job, begin)
        except ApiError as error:
            if error.status == 409 and error.code == "done":
                return None
            raise self.refused(step, error) from None
        self.wait(job, child, step)
        if child.state == "failed":
            if step == "reading" and self.agent_of(job.subject)["paper"].get("file") is None:
                raise Stuck(
                    "waiting",
                    "reading",
                    "paper_text",
                    f"The text of the paper could not be had: {child.error or 'it failed'}. Upload its file on the "
                    "paper's page, and go on.",
                )
            raise Stuck("failed", step, "failed", child.error or "It failed")
        if child.state == "stopped":
            raise Stuck("stopped", step, "stopped", f"{child.title} was stopped.")

        return child

    def refused(self, step: str, error: ApiError) -> Exception:
        """What stands in the way of a step that a PaperAgent would not start."""
        if error.code == "no_file":
            return Stuck(
                "waiting", step, "paper_file", "The paper is a file that has not been uploaded. Upload it, and go on."
            )
        if error.code == "docker_missing":
            return Stuck("waiting", step, "docker", f"{error.message.rstrip('.')}. Start it, and go on.")
        if error.code == "git_missing":
            return Stuck("waiting", step, "git", f"{error.message.rstrip('.')}. Install it, and go on.")
        if error.code in ("missing_keys", "unavailable"):
            return Stuck("waiting", step, "model", error.message)
        if error.code in BLOCKS:
            return Cannot(error.message)

        return Stuck("failed", step, "refused", error.message)

    def start_step(self, job: Job, begin: Callable[[], Job]) -> Job:
        """Starts a step, after another that is in its way has ended, if one is, up to a few times."""
        for attempt in range(MOST_WAITS + 1):
            try:
                return begin()
            except ApiError as error:
                other = error.details.get("job") if error.status == 409 and error.code == "busy" else None
                if other is None or attempt == MOST_WAITS:
                    raise
                self.wait_for(job, str(other["id"]))
        raise AssertionError("unreachable")

    def wait_for(self, job: Job, job_id: str) -> None:
        """Waits for a job that someone else started, which is not stopped when making is."""
        try:
            other = self.jobs.get(job_id)
        except KeyError:
            return
        while other.active:
            self.stop_if_asked(job)
            job.update(detail=f"Waiting for: {other.title}")
            time.sleep(POLL_SECONDS)

    def wait(self, job: Job, child: Job, step: str) -> None:
        """Waits for a step to end, and asks it to stop if making is stopped.

        :raises StoppedError: Once the step has ended, if making was stopped.
        """
        asked = False
        while child.active:
            if job.stop.is_set() and not asked:
                child.request_stop()
                asked = True
            job.update(detail=child.message)
            time.sleep(POLL_SECONDS)
        self.stop_if_asked(job)
