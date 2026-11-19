"""What an agent's claims came to, as tables to open in a spreadsheet, in the way that the tables of a survey of papers
are: one row for each claim, and one for each variant that was made of one.

The rows are made of what the server shows of the trying of the claims, of where each first parts from the paper, and
of the variants, and say no more than they do: a claim that is stale is not given what the earlier trying said of it,
a difference is given as one that was found and not as why, and a variant is given beside the claim's own result and is
said not to be the paper's. A paper's own words are in some cells, which are cleaned when the table is written, as a
spreadsheet would read one that begins with '=' as a formula.
"""

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from virtual_lab.paperagents import reproducing, varying

CLAIMS = "claims"
VARIANTS = "variants"
KINDS = (CLAIMS, VARIANTS)

# The status that a claim is shown as when what was said of it is of another run of the tutorials or other claims
STALE = "stale"

CLAIM_COLUMNS = (
    "Claim",
    "Paper reports",
    "Sentence",
    "Status",
    "Why it was not attempted",
    "What it came to",
    "Tutorial",
    "Call",
    "Where in what it gave",
    "What the tutorial gave",
    "Where it first parts from the paper",
    "Differences found (not shown to be why)",
    "Variants made",
)

VARIANT_COLUMNS = (
    "Claim",
    "Paper reports",
    "Sentence",
    "The claim's own result",
    "Made",
    "Changed",
    "The call with nothing changed",
    "The variant",
    "Number the tutorial's call gave",
    "Number with nothing changed",
    "Number the variant gave",
    "Where",
    "Comparable",
    "Rounds to the paper's number",
    "Is it the paper's result",
    "Note",
    "What it came to",
)

CONTROL_TITLES = {
    varying.MATCH: "Gave what the tutorial got",
    "differs": "Did not give what the tutorial got",
    varying.ERROR: "Stopped with an error",
    varying.NOT_RUN: "Was not made in the time",
}

VARIANT_TITLES = {
    varying.GAVE: "Gave a number",
    varying.NO_PLACE: "Gave no number at the place",
    varying.UNSTABLE: "Gave something else each time",
    varying.ERROR: "Stopped with an error",
    varying.NOT_RUN: "Was not made in the time",
}


def status_title(entry: Mapping[str, Any]) -> str:
    """A claim's status in words, and for one that is stale what it was, so that a table does not pass for what is
    kept now what was said of another run."""
    status = entry["status"]
    if status == STALE:
        was = entry.get("was")

        return f"Stale (was {reproducing.TITLES.get(was, was)})" if was else "Stale"

    return reproducing.TITLES.get(status, status)


def claim_rows(
    reproduction: Mapping[str, Any], divergence: Mapping[str, Any], variants: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """One row for each claim that the trying lists, in order: what came of it, what it was held to, where it first
    parts from the paper and what differs that was found, if it did not reproduce, and how many variants were made of
    it. The trying lists the first reproducing.MOST_CLAIMS of a paper's claims, and the rows are those, so a paper with
    more has no row for the rest, as it has no entry for them in what the server shows.

    :param reproduction: What PaperAgents.reproduction gives.
    :param divergence: What PaperAgents.divergence gives, which has no claims if there is no trying that is current.
    :param variants: What PaperAgents.variants gives, of which the variants that are shown are of the current trying.
    """
    looked = {each["id"]: each for each in divergence["claims"]}
    made = Counter(each["claim"] for each in variants["variants"])
    rows = []
    for entry in reproduction["claims"]:
        stale = entry["status"] == STALE
        link = None if stale else entry["link"]
        found = None if stale else looked.get(entry["id"])
        reason = None if stale else entry["reason"]
        rows.append(
            {
                "Claim": entry["id"],
                "Paper reports": entry["value"],
                "Sentence": entry["quote"],
                "Status": status_title(entry),
                "Why it was not attempted": reproducing.REASONS.get(reason, reason) if reason else "",
                "What it came to": "" if stale else entry["summary"],
                "Tutorial": link["tutorial"]["path"] if link is not None else "",
                "Call": link["call"] if link is not None and link["call"] is not None else "",
                "Where in what it gave": link["where"] if link is not None else "",
                "What the tutorial gave": link["got"] if link is not None else "",
                "Where it first parts from the paper": found["point"]["text"]
                if found is not None and found["point"] is not None
                else "",
                "Differences found (not shown to be why)": " ".join(each["text"] for each in found["differences"])
                if found is not None
                else "",
                "Variants made": made.get(entry["id"], 0),
            }
        )

    return rows


def changes_in_words(changes: Sequence[Mapping[str, Any]]) -> str:
    """What was changed in a call, with every value in full, as JSON gives it."""
    return "; ".join(
        f"{each['name']} = {json.dumps(each['now'], ensure_ascii=False)} in place of "
        f"{json.dumps(each['was'], ensure_ascii=False)}"
        for each in changes
    )


def variant_rows(reproduction: Mapping[str, Any], variants: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row for each variant that is shown, in the order that they were made, beside what came of the claim itself,
    which a variant never changes.

    :param reproduction: What PaperAgents.reproduction gives.
    :param variants: What PaperAgents.variants gives.
    """
    own = {each["id"]: each for each in reproduction["claims"]}
    rows = []
    for each in variants["variants"]:
        claim = own.get(each["claim"])
        control, variant = each["control"], each["variant"]
        rows.append(
            {
                "Claim": each["claim"],
                "Paper reports": each["number"],
                "Sentence": each["quote"],
                "The claim's own result": status_title(claim) if claim is not None else "",
                "Made": each["made_at"],
                "Changed": changes_in_words(each["changes"]),
                "The call with nothing changed": CONTROL_TITLES.get(control["verdict"], control["verdict"]),
                "The variant": VARIANT_TITLES.get(variant["status"], variant["status"]),
                "Number the tutorial's call gave": each["claim_run"],
                "Number with nothing changed": "" if control["gave"] is None else control["gave"],
                "Number the variant gave": "" if variant["gave"] is None else variant["gave"],
                "Where": each["where"],
                "Comparable": "Yes" if each["comparable"] else "No",
                "Rounds to the paper's number": ""
                if each["rounds_to_paper"] is None
                else ("Yes" if each["rounds_to_paper"] else "No"),
                "Is it the paper's result": "No",
                "Note": each["note"] or "",
                "What it came to": each["text"],
            }
        )

    return rows
