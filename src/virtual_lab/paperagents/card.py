"""The method card as a person has corrected it: what they changed, added, and took off, and whether they approved it.

A reading makes a draft of the card from the paper (reading.py), and a draft is what it stays: a model made it, and all
that was checked of a fact is that its quote is in the paper, which is not that the model read the quote right. A person
reads it and puts right what is wrong. What they do is kept apart from what the reading made, and put over it when the
card is asked for, so that reading the paper again does not lose it, and so that every fact says whose it is:

- A fact that a person changed keeps the paper's words and where they are, since those are the evidence, says what it
  was read as, and is theirs.
- A fact that a person added has their own words, if they gave any, and no place in the paper. It is theirs.
- A fact that a person took off is not shown, and can be put back as it was read.

Approving is of the card as it is. It says that a person read it and let it stand, which is not that it is right, and
any change to the card, by them or by a reading, makes it a draft again, so that an approval never covers what the
person did not see.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from virtual_lab.paperagents.reading import (
    CARD_KINDS,
    FIELDS,
    ID_PREFIXES,
    KEYS,
    MAX_DETAIL_CHARS,
    MAX_QUOTE_CHARS,
    REQUIRED,
)

# What the edits of a card say of how they are kept, so that a later version can read what an earlier one wrote
SCHEMA = 1

# Whose a fact is
BY_READING = "reading"
BY_PERSON = "person"

# What a statement of scope may be about, as the reading says it
ASPECTS = ("species", "tissue", "assay", "sample size", "input", "other")

# The most facts that are a person's own, changed or added, which is more than a card has of the paper's
MAX_OWN = 200


class NoSuchFactError(LookupError):
    """Raised when something is said of a fact that the card does not have."""


def empty_edits() -> dict[str, Any]:
    """The edits of a card that has none: the facts that are a person's, those taken off, and the approval."""
    return {"facts": {}, "removed": {}, "approval": None}


def is_text(value: Any) -> bool:
    return isinstance(value, str)


def is_place(anchor: Any) -> bool:
    """Whether what was kept as the place of a fact in the paper is one."""
    return (
        isinstance(anchor, dict)
        and all(
            isinstance(anchor.get(name), int) and not isinstance(anchor.get(name), bool) for name in ("start", "end")
        )
        and (anchor.get("page") is None or (isinstance(anchor["page"], int) and not isinstance(anchor["page"], bool)))
        and (anchor.get("section") is None or is_text(anchor["section"]))
    )


def is_own(fact: Any) -> bool:
    """Whether what was kept as a fact that is a person's is one, so that a file that was edited by hand does not break
    what reads it."""
    if not isinstance(fact, dict) or fact.get("kind") not in CARD_KINDS or fact.get("by") != BY_PERSON:
        return False
    kind = fact["kind"]
    read_as = fact.get("read_as")

    return (
        is_text(fact.get("id"))
        and fact["id"].startswith(f"{ID_PREFIXES[kind]}-")
        and is_text(fact.get("quote"))
        and is_text(fact.get("at"))
        and all(is_text(fact.get(name)) for name in FIELDS[kind])
        and (fact.get("anchor") is None or is_place(fact["anchor"]))
        and (
            read_as is None or (isinstance(read_as, dict) and all(is_text(read_as.get(name)) for name in FIELDS[kind]))
        )
    )


def edits_of(record: Any) -> dict[str, Any]:
    """The edits of a card, as a record of them says, leaving out what is not in the shape that is written: so that a
    record that was edited by hand, or is of another version, has less in it and not something that breaks what reads
    it."""
    edits = empty_edits()
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        return edits
    facts = record.get("facts")
    if isinstance(facts, dict):
        edits["facts"] = {
            name: fact for name, fact in facts.items() if is_text(name) and is_own(fact) and fact["id"] == name
        }
    removed = record.get("removed")
    if isinstance(removed, dict):
        edits["removed"] = {name: when for name, when in removed.items() if is_text(name) and is_text(when)}
    approval = record.get("approval")
    if isinstance(approval, dict) and is_text(approval.get("at")) and is_text(approval.get("of")):
        edits["approval"] = {"at": approval["at"], "of": approval["of"]}

    return edits


def is_empty(edits: Mapping[str, Any]) -> bool:
    return not (edits["facts"] or edits["removed"] or edits["approval"])


def fields_of(kind: str, fact: Mapping[str, Any]) -> dict[str, str]:
    return {name: fact[name] for name in FIELDS[kind]}


def place(fact: Mapping[str, Any]) -> tuple[int, int, int]:
    """Where a fact comes among the others: in the order of the paper, and those that have no place in it after."""
    anchor = fact.get("anchor")

    return (0, anchor["start"], anchor["end"]) if isinstance(anchor, dict) else (1, 0, 0)


def own_shown(fact: Mapping[str, Any]) -> dict[str, Any]:
    """A fact that is a person's, as the card shows it."""
    kind = fact["kind"]

    return {
        "id": fact["id"],
        **fields_of(kind, fact),
        "quote": fact["quote"],
        "anchor": fact.get("anchor"),
        "by": BY_PERSON,
        "read_as": fact.get("read_as"),
        "at": fact["at"],
    }


def kinds_digest(kinds: Mapping[str, Iterable[Mapping[str, Any]]]) -> str:
    """What tells one card from another: its facts, what each says, whose it is, and the words it has."""
    content = {
        kind: [[fact["id"], fact["by"], fields_of(kind, fact), fact["quote"]] for fact in kinds[kind]]
        for kind in CARD_KINDS
    }

    return hashlib.sha256(json.dumps(content, sort_keys=True).encode("utf-8")).hexdigest()


def shown(read: Mapping[str, Any], edits: Mapping[str, Any]) -> dict[str, Any]:
    """The card as it is now: what the reading made, with what a person did to it put over.

    :param read: The card that a reading made, as assemble gives it.
    :param edits: A person's edits, as edits_of gives them.
    :return: The facts of each kind, each saying whose it is; the status, which is approved only if the card is as it
        was when the person approved it; when that was; whether it was approved and has changed since; whether any of
        it is a person's; and the facts that were taken off, by kind, which can be put back.
    """
    kinds: dict[str, list[dict[str, Any]]] = {}
    removed: dict[str, list[dict[str, Any]]] = {}
    for kind in CARD_KINDS:
        mine = {name: fact for name, fact in edits["facts"].items() if fact["kind"] == kind}
        found: list[dict[str, Any]] = []
        off: list[dict[str, Any]] = []
        read_ids = set()
        for fact in read[kind]:
            read_ids.add(fact["id"])
            if fact["id"] in mine:
                found.append(own_shown(mine[fact["id"]]))
            elif fact["id"] in edits["removed"]:
                off.append({**fact, "by": BY_READING})
            else:
                found.append({**fact, "by": BY_READING})
        # What a person changed of a fact that a reading no longer finds is kept, as it is theirs and has its own words
        found.extend(own_shown(fact) for name, fact in mine.items() if name not in read_ids)
        kinds[kind] = sorted(found, key=place)
        removed[kind] = off
    digest = kinds_digest(kinds)
    approval = edits["approval"]
    approved = approval is not None and approval["of"] == digest

    return {
        "status": "approved" if approved else "draft",
        "approved_at": approval["at"] if approved and approval is not None else None,
        "changed_since_approval": approval is not None and not approved,
        "edited": bool(edits["facts"] or edits["removed"]),
        **kinds,
        "removed": removed,
    }


def clean_text(name: str, value: Any, most: int) -> str:
    """Words a person gave, on one line, as a fact keeps them.

    :raises ValueError: If it is not text, or is too long.
    """
    if not isinstance(value, str):
        raise ValueError(f"{name} is words")
    words = " ".join(value.split())
    if len(words) > most:
        raise ValueError(f"{name} is at most {most:,} characters")

    return words


def check_fields(kind: str, given: Any, own_words: bool) -> tuple[dict[str, str], str | None]:
    """What a person says of a fact, if it is something a fact of this kind can be.

    :param given: The fields of the kind, by name, and the fact's own words as quote if those may be given.
    :param own_words: Whether the person may give the words of the fact, which they may of one that is theirs, since the
        words of one that was read are the paper's.
    :return: The fields, and the words, which are None if none were given and may not be.
    :raises ValueError: If it says what a fact of this kind does not take, leaves out what it must have, or gives an
        aspect that scope has none of.
    """
    if not isinstance(given, dict):
        raise ValueError("A fact is its fields, by name")
    allowed = (*FIELDS[kind], *(("quote",) if own_words else ()))
    if unknown := sorted(str(name) for name in set(given) - set(allowed)):
        raise ValueError(f"{', '.join(unknown)} is not something a fact of {kind} has: it has {', '.join(allowed)}")
    fields = {name: clean_text(name, given.get(name, ""), MAX_DETAIL_CHARS) for name in FIELDS[kind]}
    words = clean_text("quote", given["quote"], MAX_QUOTE_CHARS) if own_words and "quote" in given else None
    required = [*(("aspect",) if kind == "scope" else ()), *REQUIRED[kind]]
    if missing := [name for name in required if not fields[name]]:
        raise ValueError(f"{', '.join(missing)} must be filled in")
    if kind == "scope" and fields["aspect"] not in ASPECTS:
        raise ValueError(f"aspect is one of {', '.join(ASPECTS)}")

    return fields, words


def find(card: Mapping[str, Any], fact_id: str) -> tuple[str, dict[str, Any]] | None:
    """A fact of a card, as the reading or the card shows it, and its kind, or None if it has none with this id."""
    for kind in CARD_KINDS:
        for fact in card[kind]:
            if fact["id"] == fact_id:
                return kind, fact

    return None


def check_new(card: Mapping[str, Any], kind: str, fact: Mapping[str, Any], besides: str | None = None) -> None:
    """
    :raises ValueError: If the card has this fact already, as the reading tells facts apart.
    """
    key = KEYS[kind](fact)
    if any(KEYS[kind](other) == key for other in card[kind] if other["id"] != besides):
        raise ValueError("The card has that already")


def with_fact(edits: Mapping[str, Any], fact: dict[str, Any]) -> dict[str, Any]:
    return {**edits, "facts": {**edits["facts"], fact["id"]: fact}}


def add(
    read: Mapping[str, Any], edits: Mapping[str, Any], kind: Any, given: Any, at: str, token: str
) -> dict[str, Any]:
    """The edits with a fact that a person adds.

    :param token: What tells the fact's id from those of others they add, which is not the same for any two.
    :raises ValueError: If the kind is not one the card has, what is said is not a fact of it, the card has it already,
        or the person has as many facts of their own as are taken.
    """
    if kind not in CARD_KINDS:
        raise ValueError(f"Say which sort of fact it is: {', '.join(CARD_KINDS)}")
    fields, words = check_fields(kind, given, own_words=True)
    if kind == "limitations" and not words:
        raise ValueError("A limit is its words, which must be filled in")
    if len(edits["facts"]) >= MAX_OWN:
        raise ValueError(f"The card has as many facts of yours as it takes, which is {MAX_OWN}")
    fact = {
        "id": f"{ID_PREFIXES[kind]}-own{token}",
        "kind": kind,
        "by": BY_PERSON,
        **fields,
        "quote": words or "",
        "anchor": None,
        "read_as": None,
        "at": at,
    }
    check_new(shown(read, edits), kind, fact)

    return with_fact(edits, fact)


def change(read: Mapping[str, Any], edits: Mapping[str, Any], fact_id: str, given: Any, at: str) -> dict[str, Any]:
    """The edits with a fact changed, so that it says what the person says. A fact that was read keeps the paper's words
    and says what it was read as, and is the reading's again if it is changed back to that; one that is a person's may
    have its words changed as well.

    :raises NoSuchFactError: If the card has no fact with this id.
    :raises ValueError: If what is said is not a fact of its kind, is what the fact says already, or is a fact that
        the card has.
    """
    card = shown(read, edits)
    found = find(card, fact_id)
    if found is None:
        raise NoSuchFactError("The card has no fact with that id")
    kind, fact = found
    own_words = fact["by"] == BY_PERSON and fact["anchor"] is None
    if kind == "limitations" and not own_words:
        raise ValueError("A limit is the authors' sentence, which is not changed: take it off, and add yours")
    fields, words = check_fields(kind, given, own_words=own_words)
    changed = {**fact, **fields, "quote": words if words is not None else fact["quote"]}
    if fields_of(kind, changed) == fields_of(kind, fact) and changed["quote"] == fact["quote"]:
        raise ValueError("That is what the card says already")
    check_new(card, kind, changed, besides=fact_id)
    if fact["by"] == BY_PERSON and fact["read_as"] == fields and find(read, fact_id) is not None:
        # Changed back to what was read, which is no longer a change, and the fact is the reading's again
        return {**edits, "facts": {name: own for name, own in edits["facts"].items() if name != fact_id}}
    own = {
        "id": fact_id,
        "kind": kind,
        "by": BY_PERSON,
        **fields_of(kind, changed),
        "quote": changed["quote"],
        "anchor": fact["anchor"],
        "read_as": fact["read_as"] if fact["by"] == BY_PERSON else fields_of(kind, fact),
        "at": at,
    }

    return with_fact(edits, own)


def remove(read: Mapping[str, Any], edits: Mapping[str, Any], fact_id: str, at: str) -> dict[str, Any]:
    """The edits with a fact taken off the card. A fact that a person added is gone, and one that was read is kept
    aside, so that it can be put back; so is the one that a person changed, as it was read.

    :raises NoSuchFactError: If the card has no fact with this id.
    """
    found = find(shown(read, edits), fact_id)
    if found is None:
        raise NoSuchFactError("The card has no fact with that id")
    _, fact = found
    facts = {name: own for name, own in edits["facts"].items() if name != fact_id}
    removed = dict(edits["removed"])
    # What a person added is gone. What was read, or changed from what was read, is kept aside while the reading has it
    if fact["by"] == BY_READING or (fact["read_as"] is not None and find(read, fact_id) is not None):
        removed[fact_id] = at

    return {**edits, "facts": facts, "removed": removed}


def restore(read: Mapping[str, Any], edits: Mapping[str, Any], fact_id: str) -> dict[str, Any]:
    """The edits with a fact as it was read: one that was taken off is put back, and one that a person changed says what
    it was read as.

    :raises NoSuchFactError: If there is nothing of this id that was changed or taken off.
    :raises ValueError: If the reading no longer finds it, so that there is nothing to put it back as.
    """
    in_reading = find(read, fact_id)
    if fact_id in edits["removed"]:
        if in_reading is None:
            raise ValueError("The reading no longer finds that, so it cannot be put back")
        check_new(shown(read, edits), in_reading[0], in_reading[1])

        return {**edits, "removed": {name: when for name, when in edits["removed"].items() if name != fact_id}}
    own = edits["facts"].get(fact_id)
    if own is None or own["read_as"] is None:
        raise NoSuchFactError("The card has nothing with that id that was changed or taken off")
    if in_reading is None:
        raise ValueError("The reading no longer finds that, so it cannot be put back as it was read")

    return {**edits, "facts": {name: fact for name, fact in edits["facts"].items() if name != fact_id}}


def approve(read: Mapping[str, Any], edits: Mapping[str, Any], at: str) -> dict[str, Any]:
    """The edits with the card approved as it is now.

    :raises ValueError: If the card has no fact on it, so that there is nothing to approve.
    """
    card = shown(read, edits)
    if not any(card[kind] for kind in CARD_KINDS):
        raise ValueError("The card has no fact on it, so there is nothing to approve")

    return {**edits, "approval": {"at": at, "of": kinds_digest(card)}}


def withdraw(edits: Mapping[str, Any]) -> dict[str, Any]:
    """The edits without the approval."""
    return {**edits, "approval": None}
