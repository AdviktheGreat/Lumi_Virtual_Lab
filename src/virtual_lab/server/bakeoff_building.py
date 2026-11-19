"""Building the methods of a bake-off: making each one a PaperAgent that has tools, as far as it can be.

A method in a bake-off is built by being given the PaperAgent of its paper, which is the one there is, or one that is
made, and then having done to it the steps that a PaperAgent has, in the order that costs least and with the person
asked where they are the person's to say. Each step is the PaperAgent's own, started as a page would start it and
waited for, so that what a bake-off builds is what anyone could have built by hand, and can be looked at, and carried
on, on the PaperAgent's page, and a step that has been done by hand is not done again. Nothing here reaches into a
PaperAgent's files to say that a step is done: what a step came to is asked of the PaperAgent.

The order is: where the code is, and fetching it, and what looking at it says, then reading the paper, which is the one
step that is paid for in model requests, and what looking at the code says with what the paper says, and then the
environment, the tutorials, and the tools. The code is looked at before the paper is read so that a method that cannot
be used is not paid for, and again after, since what the paper says of the licence and the data bears on it.

What stands in the way of a method is one of four things, and it is said in words and kept with the method:

- waiting: it is for the person to say. Where its code is, when none was given and the paper points to some or to none,
  which is never taken to be the code until they say; which of two addresses is, when the PaperAgent has one and the
  bake-off another; and whether to go on, when looking at the code found things to weigh. What they say is kept with
  the commit of the code that it was said of, and is not said of another.
- blocked: it is so of the method, and nobody can change it here: the look at the code says no-go, the environment is
  one that cannot be built here, there is no tutorial to make tools from, or none of the calls made a tool.
- failed: a step went wrong, which may not go wrong the next time it is asked for.
- pending: it was not got to, because the limit on spending was reached or building was stopped.

Reading is paid for out of what is left of the bake-off's one limit. It is given what is left, as the most it may spend,
and what it spent is found in what it kept, chunk by chunk, and added to what the bake-off has spent whether it came to
its end or not. The other steps ask no model.
"""

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from virtual_lab.environment import StoppedError
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_bakeoff as kept_bakeoff
from virtual_lab.server import paperagent_reading as kept_reading
from virtual_lab.server.errors import ApiError
from virtual_lab.server.jobs import Job
from virtual_lab.server.paperagents import default_title, steps_of
from virtual_lab.server.papers import money

if TYPE_CHECKING:
    from virtual_lab.server.bakeoffs import Bakeoffs

# Seconds between looks at a step that a PaperAgent is doing
POLL_SECONDS = 0.2
# How many times a step is waited for another that was in its way before it is said to be
MOST_WAITS = 3
# What each step is, as the page says it is being done
STEP_WORDS = {
    "agent": "finding its PaperAgent",
    "code": "fetching its code",
    "paper": "reading its paper",
    "preflight": "looking at its code",
    "environment": "building its environment",
    "tutorials": "running its tutorials",
    "tools": "making its tools",
}
# What a PaperAgent refuses a step with when it is so of the method, and not of anything that was asked
BLOCKS = ("unsupported", "no_tutorials", "no_tools")
STOPPED = "Stopped. What was built is kept, and building again carries on from there."


class Stuck(Exception):
    """What stands in the way of a method, for building it to say and go on to the next.

    :param state: Whether it is for the person to say (waiting), so of the method (blocked), a step that went wrong
        (failed), or not got to (pending).
    :param step: Which step it was at.
    :param why: A short name for the reason, which a page can go by.
    :param reason: What it is, in words.
    :param suggested: Addresses of code that the paper points to, for the person to say which, if any, is the code.
    """

    def __init__(self, state: str, step: str, why: str, reason: str, suggested: list[str] | None = None) -> None:
        super().__init__(reason)
        self.state = state
        self.step = step
        self.why = why
        self.reason = reason
        self.suggested = suggested


class Gone(Exception):
    """The method was taken out of the running while it was built."""


class Builder:
    """Builds the methods of bake-offs, for the bake-offs that were given.

    :param bakeoffs: The bake-offs, which say what a method is and keep what stands in the way of it, and whose
        PaperAgents each step is done to.
    """

    def __init__(self, bakeoffs: "Bakeoffs") -> None:
        self.bakeoffs = bakeoffs
        self.paperagents = bakeoffs.paperagents

    def work(self, bakeoff_id: str, candidate_ids: list[str]) -> Callable[[Job], str]:
        """What a job does to build methods: builds each of them, one after another, whatever came of the one before."""

        def run(job: Job) -> str:
            return self.build_all(job, bakeoff_id, candidate_ids)

        return run

    def build_all(self, job: Job, bakeoff_id: str, candidate_ids: list[str]) -> str:
        counts: dict[str, int] = {}
        job.update(candidates=len(candidate_ids), finished=0)
        for number, candidate_id in enumerate(candidate_ids, 1):
            self.stop_if_asked(job)
            candidate = self.bakeoffs.candidate(bakeoff_id, candidate_id)
            if candidate is None:
                continue
            job.update(
                f"Building {candidate['name']} ({number} of {len(candidate_ids)})",
                candidate=candidate_id,
                step="agent",
                detail="",
                finished=number - 1,
            )
            try:
                self.build_one(job, bakeoff_id, candidate_id)
            except Gone:
                continue
            except Stuck as stuck:
                outcome = stuck
            except StoppedError:
                stopped = Stuck("pending", self.step_of(job), "stopped", "Building was stopped before this was done.")
                self.keep(bakeoff_id, candidate_id, stopped, candidate["repo"])
                raise
            except Exception as error:
                outcome = Stuck("failed", self.step_of(job), "error", f"{type(error).__name__}: {error}".rstrip(": "))
            else:
                self.bakeoffs.edit_candidate(bakeoff_id, candidate_id, lambda each: {**each, "build": None})
                counts["built"] = counts.get("built", 0) + 1
                job.log(f"{candidate['name']}: built")
                continue
            self.keep(bakeoff_id, candidate_id, outcome, candidate["repo"])
            counts[outcome.state] = counts.get(outcome.state, 0) + 1
            job.log(f"{candidate['name']}: {outcome.state}, {STEP_WORDS[outcome.step]}: {outcome.reason}")
        job.update("Done", candidate=None, step=None, detail="", finished=len(candidate_ids))

        return self.describe(bakeoff_id, counts)

    def describe(self, bakeoff_id: str, counts: dict[str, int]) -> str:
        """What building came to, in a sentence or two."""
        parts = [f"Built {counts.get('built', 0)} of {sum(counts.values())} methods."]
        for state, words in (
            ("waiting", "Waiting for you to say something"),
            ("blocked", "Cannot be built here"),
            ("failed", "Went wrong, which may not be so if it is asked for again"),
            ("pending", "Not got to"),
        ):
            if counts.get(state):
                parts.append(f"{words}: {counts[state]}.")
        try:
            _, record = self.bakeoffs.lookup(bakeoff_id)
        except ApiError:
            return " ".join(parts)
        parts.append(f"{money(record['spent'])} of the {money(record['limit'])} limit has been spent.")

        return " ".join(parts)

    # One method

    def build_one(self, job: Job, bakeoff_id: str, candidate_id: str) -> None:
        """Does to a method's PaperAgent what is left to be done to it, and ends if it is built.

        :raises Stuck: If something stands in the way.
        :raises Gone: If the method was taken out of the running.
        :raises StoppedError: If building was stopped.
        """
        agent_id = self.agent_of(bakeoff_id, candidate_id)
        if self.is_done(agent_id, "tools"):
            return
        if not self.is_done(agent_id, "environment"):
            read = self.is_done(agent_id, "reading")
            if self.address_of(bakeoff_id, candidate_id, agent_id) is not None:
                self.fetch(job, bakeoff_id, candidate_id, agent_id)
                if not read:
                    self.look(job, bakeoff_id, candidate_id, agent_id, last=False)
            if not read:
                self.read(job, bakeoff_id, agent_id)
            if self.address_of(bakeoff_id, candidate_id, agent_id) is None:
                raise self.without_code(bakeoff_id, candidate_id, agent_id)
            self.fetch(job, bakeoff_id, candidate_id, agent_id)
            self.look(job, bakeoff_id, candidate_id, agent_id, last=True)
            self.environment(job, agent_id)
        self.tutorials(job, agent_id)
        self.tools(job, agent_id)

    def agent_of(self, bakeoff_id: str, candidate_id: str) -> str:
        """The id of the PaperAgent of a method's paper, which is made if there is none.

        :raises Stuck: If it cannot be made or is not one that is built here, or its code is said to be elsewhere.
        """
        candidate = self.current(bakeoff_id, candidate_id)
        found = kept_bakeoff.agent_for(candidate["paper"], self.paperagents.kept())
        if found is None:
            found = self.make_agent(candidate)
        agent_id, agent = found
        if agent.get("imported") is not None:
            raise Stuck(
                "blocked",
                "agent",
                "imported",
                f"The PaperAgent of this paper, {agent['title']}, is hosted by another server, and has no code here to "
                "build",
            )
        theirs = (agent.get("repo") or {}).get("url")
        if candidate["repo"] is not None and theirs is not None and candidate["repo"] != theirs:
            raise Stuck(
                "waiting",
                "code",
                "code_differs",
                f"The PaperAgent of this paper, {agent['title']}, has its code at {theirs}, and the bake-off says it "
                f"is at {candidate['repo']}. Say which, here or on the PaperAgent's page, and build again",
            )

        return agent_id

    def make_agent(self, candidate: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Makes the PaperAgent of a method's paper, named as the method is, with its code if it was said.

        :raises Stuck: If it cannot be made.
        """
        for title in (candidate["name"], default_title(candidate["paper"])):
            try:
                agent_id = self.paperagents.create(title, candidate["paper"], candidate["repo"])
            except ApiError as error:
                if error.code == "exists":
                    agent_id = str(error.details["existing"])
                elif error.code == "too_many":
                    raise Stuck("blocked", "agent", "too_many", error.message) from None
                elif error.status == 422 and title == candidate["name"]:
                    continue
                else:
                    raise Stuck("failed", "agent", "refused", error.message) from None
            return agent_id, self.paperagents.lookup(agent_id)[1]
        raise Stuck("failed", "agent", "refused", "A PaperAgent could not be made of the paper")

    def address_of(self, bakeoff_id: str, candidate_id: str, agent_id: str) -> str | None:
        """Where the method's code is, if anyone has said: the bake-off, or else the PaperAgent."""
        candidate = self.current(bakeoff_id, candidate_id)
        theirs = (self.paperagents.lookup(agent_id)[1].get("repo") or {}).get("url")

        return candidate["repo"] or theirs

    def without_code(self, bakeoff_id: str, candidate_id: str, agent_id: str) -> Stuck:
        """What stands in the way when nobody has said where the code is: the person is to, and the paper's pointers
        are what they may say it by, which are not the code until they do."""
        candidate = self.current(bakeoff_id, candidate_id)
        pointed = [each["url"] for each in self.paperagents.repository(agent_id)["candidates"]]
        suggested = list(dict.fromkeys([*pointed, *candidate["suggested"]]))[: kept_bakeoff.MAX_SUGGESTED]
        if suggested:
            return Stuck(
                "waiting",
                "code",
                "choose_code",
                f"No address of the code was given. The paper or its abstract points to {', '.join(suggested)}. Say "
                "which, if any, is its code, and build again",
                suggested,
            )

        return Stuck(
            "waiting",
            "code",
            "no_code",
            "No address of the code was given, and the paper does not point to any. Say where it is, and build again",
            [],
        )

    def current(self, bakeoff_id: str, candidate_id: str) -> dict[str, Any]:
        """The method as it is kept now.

        :raises Gone: If it, or the bake-off, is gone.
        """
        candidate = self.bakeoffs.candidate(bakeoff_id, candidate_id)
        if candidate is None:
            raise Gone

        return candidate

    def keep(self, bakeoff_id: str, candidate_id: str, stuck: Stuck, repo: str | None) -> None:
        """Keeps what stands in the way of a method, and what the person has said to it.

        :param repo: Where the method's code was said to be when it was started on. If it has been said to be elsewhere
            since, what stood in the way was of the other code, and nothing is kept.
        """

        def change(candidate: dict[str, Any]) -> dict[str, Any]:
            if candidate["repo"] != repo:
                return candidate
            build = candidate["build"]
            reason = kept_bakeoff.printable(stuck.reason)[: kept_bakeoff.MAX_REASON_CHARS] or "It did not say why"

            return {
                **candidate,
                "suggested": candidate["suggested"] if stuck.suggested is None else stuck.suggested,
                "build": {
                    "state": stuck.state,
                    "step": stuck.step,
                    "why": stuck.why,
                    "reason": reason,
                    "at": utc_timestamp(),
                    "go_on": build["go_on"] if build is not None else None,
                },
            }

        self.bakeoffs.edit_candidate(bakeoff_id, candidate_id, change)

    # The steps

    def is_done(self, agent_id: str, step: str) -> bool:
        return steps_of(self.paperagents.lookup(agent_id)[1])[step] == "done"

    def fetch(self, job: Job, bakeoff_id: str, candidate_id: str, agent_id: str) -> None:
        """Fetches the method's code, if it has not been, from where the method says it is."""
        address = self.address_of(bakeoff_id, candidate_id, agent_id)
        agent = self.paperagents.lookup(agent_id)[1]
        if steps_of(agent)["repository"] == "done" and (agent.get("repo") or {}).get("url") == address:
            return
        self.run(job, "code", lambda: self.paperagents.fetch_repository(agent_id, repo=address))
        if not self.is_done(agent_id, "repository"):
            raise Stuck("failed", "code", "failed", "The code was not fetched")

    def look(self, job: Job, bakeoff_id: str, candidate_id: str, agent_id: str, last: bool) -> None:
        """Looks at the code and what the paper says of it, and says whether it is worth going on.

        :param last: Whether the paper has been read, so that this is the look that the person is asked at. Before it,
            only a no-go is acted on, since what the paper says of the licence and the data may change the rest, and a
            method that cannot be used is not worth reading the paper of.
        :raises Stuck: If the look says no-go, or ask and the person has not said to go on.
        """
        job.update(step="preflight", detail="")
        found = self.paperagents.repository(agent_id)
        flight = found["preflight"]
        if flight is None or found["intake"] is None:
            raise Stuck("failed", "preflight", "no_code", "The code has not been fetched, so it cannot be looked at")
        if flight["verdict"] == "no-go":
            raise Stuck("blocked", "preflight", "no_go", flight["summary"])
        if flight["verdict"] == "ask" and last:
            build = self.current(bakeoff_id, candidate_id)["build"]
            if build is None or build["go_on"] != found["intake"]["commit"]:
                raise Stuck("waiting", "preflight", "ask", flight["summary"])

    def read(self, job: Job, bakeoff_id: str, agent_id: str) -> None:
        """Reads the method's paper, within what is left of the limit, and adds what that cost to what is spent.

        :raises Stuck: If nothing is left to spend, the paper cannot be had or read, or the limit was reached before
            it was read through.
        """
        job.update(step="paper", detail="")
        directory = self.paperagents.workspace.paperagents_dir / agent_id
        before: dict[int, dict[str, Any]] | None = None

        def begin() -> Job:
            nonlocal before
            before = None
            # Looked at each time it is started, since what is left may be less after a step that was in the way
            record = self.bakeoffs.lookup(bakeoff_id)[1]
            try:
                self.bakeoffs.check_money(record)
            except ApiError as error:
                raise Stuck("pending", "paper", error.code, error.message) from None
            saved = kept_reading.saved_chunks(directory)
            started = self.paperagents.read(agent_id, kept_bakeoff.left_of(record))
            before = saved

            return started

        def failed(child: Job) -> Stuck:
            filed = self.paperagents.lookup(agent_id)[1]["paper"].get("file") is not None
            return Stuck("failed", "paper", "failed" if filed else "no_paper", child.error or "It failed")

        child = None
        try:
            child = self.run(job, "paper", begin, failed)
        finally:
            if before is not None:
                self.charge(bakeoff_id, directory, before)
        status = steps_of(self.paperagents.lookup(agent_id)[1])["reading"]
        if status == "pending":
            raise Stuck(
                "pending",
                "paper",
                "limit",
                "The limit on spending was reached before the paper was read through. "
                + (child.message if child is not None else ""),
            )
        if status != "done":
            raise Stuck("failed", "paper", "failed", "No part of the paper could be read")

    def charge(self, bakeoff_id: str, directory: Any, before: dict[int, dict[str, Any]]) -> None:
        """Adds what the reading has cost since `before` to what the bake-off has spent: that of the chunks that are not
        as they were, which is not known if one of them does not say."""
        cost = 0.0
        known = True
        for number, record in kept_reading.saved_chunks(directory).items():
            if before.get(number) == record:
                continue
            spent = record["usage"].get("cost")
            if isinstance(spent, bool) or not isinstance(spent, int | float):
                known = False
            else:
                cost += spent
        self.bakeoffs.settle_cost(bakeoff_id, cost, known)

    def environment(self, job: Job, agent_id: str) -> None:
        """Builds the environment of the code."""
        child = self.run(job, "environment", lambda: self.paperagents.build_environment(agent_id))
        if not self.is_done(agent_id, "environment"):
            raise Stuck(
                "failed",
                "environment",
                "failed",
                (child.message if child is not None else "") or "The environment was not built",
            )

    def tutorials(self, job: Job, agent_id: str) -> None:
        """Runs the tutorials of the code, which tools are made of."""
        self.run(job, "tutorials", lambda: self.paperagents.start_reference(agent_id))

    def tools(self, job: Job, agent_id: str) -> None:
        """Makes tools of what the tutorials did."""
        child = self.run(job, "tools", lambda: self.paperagents.start_tools(agent_id))
        if not self.is_done(agent_id, "tools"):
            raise Stuck(
                "blocked",
                "tools",
                "no_tools",
                (child.message if child is not None else "")
                or "No call that the tutorials made came to a tool that gives again what the tutorial got",
            )

    # Doing a step of a PaperAgent, and waiting for it

    def run(
        self, job: Job, step: str, begin: Callable[[], Job], failed: Callable[[Job], Stuck] | None = None
    ) -> Job | None:
        """Starts a step of a PaperAgent and waits for it to end.

        :param begin: Starts it, as a page would, which raises what a page is told if it cannot be.
        :param failed: Says what stands in the way if it failed, when that is more than that it did.
        :return: The step's job, or None if the step had been done.
        :raises Stuck: If it cannot be started, failed, or was stopped by someone else.
        :raises StoppedError: If building was stopped, after the step had stopped.
        """
        job.update(step=step, detail="")
        self.stop_if_asked(job)
        self.check_still_in(job)
        try:
            child = self.start(job, begin)
        except ApiError as error:
            if error.status == 409 and error.code == "done":
                return None
            if error.code in BLOCKS:
                raise Stuck("blocked", step, error.code, error.message) from None
            raise Stuck("failed", step, "refused", error.message) from None
        self.wait(job, child)
        if child.state == "failed":
            raise failed(child) if failed is not None else Stuck("failed", step, "failed", child.error or "It failed")
        if child.state == "stopped":
            raise Stuck("pending", step, "stopped", f"{child.title} was stopped")

        return child

    def start(self, job: Job, begin: Callable[[], Job]) -> Job:
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
        """Waits for a job that someone else started, which is not stopped when building is."""
        try:
            other = self.paperagents.jobs.get(job_id)
        except KeyError:
            return
        while other.active:
            self.stop_if_asked(job)
            job.update(detail=f"Waiting for: {other.title}")
            time.sleep(POLL_SECONDS)

    def wait(self, job: Job, child: Job) -> None:
        """Waits for a step to end, and asks it to stop if building is stopped.

        :raises StoppedError: Once the step has ended, if building was stopped.
        """
        asked = False
        while child.active:
            if job.stop.is_set() and not asked:
                child.request_stop()
                asked = True
            job.update(detail=child.message)
            time.sleep(POLL_SECONDS)
        self.stop_if_asked(job)

    def stop_if_asked(self, job: Job) -> None:
        if job.stop.is_set():
            raise StoppedError(STOPPED)

    def check_still_in(self, job: Job) -> None:
        """
        :raises Gone: If the method that the job is building was taken out of the running, so that nothing more is done
            to it.
        """
        candidate_id = job.snapshot()["progress"].get("candidate")
        if candidate_id is not None:
            self.current(job.subject, candidate_id)

    def step_of(self, job: Job) -> str:
        """The step that building a method is at, as the job says."""
        step = job.snapshot()["progress"].get("step")

        return step if step in kept_bakeoff.BUILD_STEPS else "agent"
