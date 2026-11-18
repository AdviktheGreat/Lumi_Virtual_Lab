"""Holding a run of a PaperAgent's tool for the person to go on, when the data it is run on is outside the method card.

A conversation's lead is told to put the person's data against the agent's method card (the tool check_scope) before it
runs a tool of the authors' code on it. What it said the data was is kept here, for the conversation, by agent. When a
tool that runs is called, what was said is put against the card as it is then, and:

- if nothing was said of the data, the tool runs, and what it gives says that the data was not put against the card;
- if the data is inside what the card says, or the card does not say enough to tell, the tool runs, and what it gives
  says which, and what it was put against;
- if the data is outside, the run is held and the person is asked, with the card's words and the paper's, whether to go
  on. Going on is theirs to say, and nothing that the lead says is taken for it. If they go on, the tool runs, and what
  it gives says that they did, when, and what was outside. If they do not, or no one could be asked, or no one
  answered, the tool does not run, and the lead is told.

A warning does not block: the person can always go on. What is held is the run, until they have said. They are asked
once for the same data against the same words on the card, and again if either changes, including while they are asked:
once they have answered, the data and the card are looked at again, and the run is made only on what they went on with.
A go-on is for the agent's tools, and not for the one that was asked about, so a second tool is run on the same data
without asking, and says that they went on. The lead is not taken to know
that a tool is run on the person's data and not on the authors' own, so a run that was not checked is only said to be.
"""

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from virtual_lab.approval import ApprovalDeclined, ScopeHold
from virtual_lab.paperagents import scope
from virtual_lab.provenance import utc_timestamp

# Says whether to go on with a run that is held, which is the person's to say, or raises ApprovalDeclined if there was
# no one to ask or no answer
GoOn = Callable[[ScopeHold], bool]

# Puts what was said of the data against the card as it is now, as paperagent_reading.scope_check does
Compare = Callable[[Mapping[str, Any]], dict[str, Any]]

CHECKED_NOTE = (
    "The data that was described to check_scope was put against the method card as it is now. Inside is not that the "
    "tool works on it, and outside is not that it fails."
)


# How many times one run asks the person, before it is given up since what the lead says the data is, or what the card
# says, keeps changing while they are asked
MOST_QUESTIONS = 3


class NotRun(RuntimeError):
    """Raised in place of a run that is held and was not gone on with, with why."""


@dataclass
class Said:
    """What was said of the data, and whether the person went on with it being outside.

    :param described: What was said of the data, as check_scope was given it.
    :param went_on: What the person went on with, which is the data and the warnings together, or None.
    :param went_on_at: When they said so.
    """

    described: dict[str, Any]
    went_on: str | None = None
    went_on_at: str | None = None


def key_of(described: Mapping[str, Any], warnings: list[str]) -> str:
    """What a person is asked about: the data and what the card said it is outside of, in its words, so that a change
    to either is a new question."""
    return hashlib.sha256(json.dumps([dict(described), warnings], sort_keys=True).encode("utf-8")).hexdigest()


def record_of(result: Mapping[str, Any], went_on_at: str | None = None) -> dict[str, Any]:
    """What a run says of the data it was put against the card with: the answer for the whole and for each thing that
    was said, the warnings, and whether the card was approved, and, for one that the person went on with, that they
    did and when."""
    record: dict[str, Any] = {
        "checked": True,
        "outcome": result["outcome"],
        "of": [
            {"aspect": each["aspect"], "given": each["given"], "outcome": each["outcome"]} for each in result["aspects"]
        ],
        "card": result["card"]["status"],
    }
    if result["warnings"]:
        record["warnings"] = list(result["warnings"])
    if went_on_at is not None:
        record["person_went_on"] = True
        record["went_on_at"] = went_on_at
    record["note"] = CHECKED_NOTE

    return record


def unchecked(check_tool: str | None) -> dict[str, Any]:
    how = f" If it is the person's own data, {check_tool} puts it against the card." if check_tool else ""

    return {
        "checked": False,
        "note": (
            "The data was not put against the method card before this run, so it is not known whether it is inside "
            f"what the card says.{how}"
        ),
    }


class Hold:
    """What a conversation has put against the cards of the agents it is given, and what the person said to going on.

    :param ask: Asks the person whether to go on, or None if there is no one to ask, in which case a run that is held
        is not made, since nothing is done that no one agreed to.
    """

    def __init__(self, ask: GoOn | None) -> None:
        self._ask = ask
        self._lock = threading.Lock()
        self._said: dict[str, Said] = {}
        self._asking: dict[str, threading.Lock] = {}

    def remember(self, agent_id: str, described: Mapping[str, Any]) -> None:
        """Keeps what the lead said the data is, as what the next run of the agent's tools is put against the card
        with. The same data said again is the same, and the person's go-on stays."""
        said = dict(described)
        with self._lock:
            previous = self._said.get(agent_id)
            if previous is not None and previous.described == said:
                return
            self._said[agent_id] = Said(said)

    def before_run(
        self,
        agent_id: str,
        title: str,
        tool: str,
        arguments: Mapping[str, Any],
        compare: Compare,
        check_tool: str | None,
    ) -> dict[str, Any]:
        """Puts what was said of the data against the card, and holds the run for the person if it is outside.

        :param tool: The tool's name, as the conversation calls it.
        :param compare: Puts what was said against the card as it is now.
        :param check_tool: The name of the tool that says what the data is, if the agent has one, for what the lead is
            told if it did not.
        :raises NotRun: If the run is held and the person did not go on, or could not be asked, or what was said of the
            data kept changing while they were asked.
        :return: What the run says of the data.
        """
        questions = 0
        while True:
            with self._lock:
                said = self._said.get(agent_id)
                asking = self._asking.setdefault(agent_id, threading.Lock())
            if said is None:
                return unchecked(check_tool)
            try:
                result = compare(said.described)
            except ValueError as error:
                raise NotRun(f"What was said of the data could not be put against the card: {error}") from None
            if result["outcome"] != scope.OUTSIDE:
                return record_of(result)
            key = key_of(said.described, result["warnings"])
            if said.went_on == key:
                return record_of(result, said.went_on_at)
            # One question at a time for an agent, so that calls that are made together ask once
            with asking:
                with self._lock:
                    current = self._said.get(agent_id) is said
                # What was said of the data has changed since it was read, and the person is asked of what it is now
                if not current:
                    continue
                if said.went_on != key:
                    if questions == MOST_QUESTIONS:
                        raise NotRun(
                            f"{tool} was not run: what was said of the data, or what the card says, changed while the "
                            "person was asked whether to go on. Put the data against the card again, and run it once "
                            "that is settled."
                        )
                    questions += 1
                    self._go_on(said, key, ScopeHold(agent_id, title, tool, dict(arguments), tuple(result["warnings"])))
            # The person's answer is of the data and the words that they were shown, so what the data is and what the
            # card says are looked at again, and the run is made only on what they went on with

    def _go_on(self, said: Said, key: str, hold: ScopeHold) -> None:
        if self._ask is None:
            raise NotRun(
                f"{hold.tool} was not run: the data is outside what the method card says, and there is no one here to "
                "ask whether to go on."
            )
        try:
            allowed = self._ask(hold)
        except ApprovalDeclined as error:
            raise NotRun(str(error)) from None
        if not allowed:
            raise NotRun(
                f"{hold.tool} was not run: the data is outside what the method card says, and the person chose not "
                "to go on. Do not ask again for this data unless they say that they want to, or that the data is "
                "different."
            )
        said.went_on, said.went_on_at = key, utc_timestamp()
