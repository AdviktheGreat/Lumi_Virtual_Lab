"""What a bake-off's data is, and whether the method card of each method's paper covers it.

The person says what their data is, in the words that a PaperAgent's scope check takes: its species, tissue, assay,
input format, and sample size with what that counts. They are the ones who say it, as only they or the data's own
description know it, and what a model might make of the description is not used here: a fact about the data that a
model wrote would be a model's say-so in the place that decides whether to warn.

Each method's paper, once it has been read, has a method card, and a program puts what was said of the data against it
(paperagents/scope.py). The answer is worked out from what is kept at the time, each time, and is not kept: the card of
a PaperAgent may be changed, or approved, or made again, and the data may be said again, and an answer that was kept
would say what is no longer so. What is kept is the person's going on with a method that the data is outside of, which
is theirs to say and nothing else's. It is kept with the key of what they were shown, which is made of the data as it
was said and the card's words that it was outside of, so that it is not going on with the data said otherwise, or with
a card that says something else now, and the person is asked again of that.

Outside is a warning and not a refusal: the person may go on, and the answer says what the card says, in its words and
in the paper's, so that they see what it is against. Inside is not that the method works on the data, and outside is not
that it fails on it, which the answer says.
"""

from collections.abc import Mapping
from typing import Any

from virtual_lab.paperagents import scope
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_bakeoff as kept_bakeoff
from virtual_lab.server.errors import ApiError
from virtual_lab.server.paperagent_hold import key_of
from virtual_lab.server.paperagents import PaperAgents, is_blank
from virtual_lab.server.workspace import has_control_character

OUTSIDE = scope.OUTSIDE
# What may be said of the data
FIELDS = ("species", "tissue", "assay", "input_format", "sample_size", "sample_unit")

NOT_CHECKED = {
    "no_description": "Nothing has been said of what the data is, so it was not put against the method card. Say what "
    "it is, and it will be.",
    "no_agent": "This method has no PaperAgent yet, so there is no card to put the data against. Building the method "
    "makes one.",
    "not_read": "The paper has not been read yet, so there is no method card to put the data against. Reading it is "
    "part of building the method.",
}


def is_zero(value: Any) -> bool:
    """Whether a size says that it is not known, which is a whole number that is none."""
    return type(value) is int and value == 0


def check_described(said: Any) -> dict[str, Any] | None:
    """What the person said of their data, as it is kept, or None if they said that there is nothing to say.

    :param said: What was said, by the species, tissue, assay, input format, and sample size with what it counts. What
        is left out, or is nothing but space, or is a size of none, is not said.
    :raises ApiError: If it is not that, a thing is not said as a scope check takes it, or has what is not text in it.
    """
    if not isinstance(said, Mapping):
        raise ApiError(
            422,
            "invalid",
            "What the data is, is said by its species, tissue, assay, input format, and sample size with what it "
            "counts",
        )
    unknown = [str(key)[:40] for key in said if key not in FIELDS]
    if unknown:
        raise ApiError(422, "invalid", f"{', '.join(unknown[:3])} is not something that is said of the data")
    given = {key: value for key, value in said.items() if not (is_blank(value) or is_zero(value))}
    if not given:
        return None
    if any(isinstance(value, str) and has_control_character(value) for value in given.values()):
        raise ApiError(422, "invalid", "What is said of the data is words, with no control character in them")
    try:
        scope.clean(given)
    except ValueError as error:
        raise ApiError(422, "invalid", str(error)) from None

    return {
        **{key: " ".join(str(given.get(key, "")).split()) for key in kept_bakeoff.DESCRIBED_WORDS},
        "sample_size": given.get("sample_size", 0),
        "at": utc_timestamp(),
    }


def not_checked(why: str) -> dict[str, Any]:
    """What a method says of the data when it was not put against a card, and why."""
    return {
        "checked": False,
        "why": why,
        "reason": NOT_CHECKED[why],
        "outcome": None,
        "of": [],
        "not_checked": [],
        "warnings": [],
        "card": None,
        "reading": None,
        "notes": [],
        "key": None,
        "went_on": False,
        "went_on_at": None,
    }


def scope_of(
    paperagents: PaperAgents, described: dict[str, Any] | None, candidate: dict[str, Any], agent_id: str | None
) -> dict[str, Any]:
    """Puts the data against the method card of a method's paper as it is now, and says whether the person has gone on
    with it being outside.

    :param described: What the person said of their data, as it is kept, or None.
    :param agent_id: The PaperAgent of the method's paper, or None if there is none.
    """
    if described is None:
        return not_checked("no_description")
    if agent_id is None:
        return not_checked("no_agent")
    facts = kept_bakeoff.facts_of(described)
    try:
        result = paperagents.check_scope(agent_id, facts)
    except ApiError as error:
        if error.status == 404:
            return not_checked("no_agent")
        raise
    if result["reading"]["chunks"] is None:
        return not_checked("not_read")
    key = key_of(facts, result["warnings"])
    said = candidate["went_on"]
    went_on = result["outcome"] == OUTSIDE and said is not None and said["key"] == key

    return {
        "checked": True,
        "why": None,
        "reason": "",
        "outcome": result["outcome"],
        "of": result["aspects"],
        "not_checked": result["not_checked"],
        "warnings": result["warnings"],
        "card": result["card"],
        "reading": result["reading"],
        "notes": result["notes"],
        "key": key,
        "went_on": went_on,
        "went_on_at": said["at"] if went_on and said is not None else None,
    }
