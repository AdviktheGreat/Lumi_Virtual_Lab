"""How papers relate to one another, found from what was read of each and from nothing else.

A relation is between two papers (two PaperAgents), and comes with the places in them that it was found from, each with
its quote and where the paper says it. Nothing is asked of a model, nothing is run, and nothing outside what was kept is
looked at, so a relation is as good as the matching of names, accessions, addresses, and words that finds it, and is a
place to read and not a finding:

- **dataset**: both papers used a dataset with the same accession, or, failing that, the same name.
- **software** and **method**: both papers name the same software or method (and, for software, the versions they say).
- **code**: both papers' code is at the same address, and whether it is at the same commit.
- **refers**: one paper's own words name the other: its DOI, the address of its code, the name of its code, or its
  title. How it is said (`mentions`, `builds_on`, `replaces`, `replicates`) is read from the words of the quote.
- **agrees** and **differs**: claims of two papers that have the same words, and have a number in common or none.

A claim that its own paper's code gave again, when the code was run (what the account of reproduction says), is said
beside it, so that two papers that agree on a number that one of them reproduced is told from two that only say so.
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from itertools import combinations
from typing import Any

from virtual_lab.papers import normalize_name

KINDS = ("refers", "code", "dataset", "software", "method", "agrees", "differs")
# How a paper says it refers to another, from the least to the most that it says
HOWS = ("mentions", "builds_on", "replaces", "replicates")
# How a paper's words name another, from the surest
BYS = ("doi", "code", "name", "title")

MOST_EVIDENCE = 3
MOST_RELATIONS = 400
MOST_CLAIMS_EACH = 150
QUOTE_CHARS = 240
MIN_NAME_CHARS = 3
MIN_CODE_NAME_CHARS = 5
MIN_TITLE_CHARS = 25
# Words in common that two claims need before they are taken to say the same of something, as a share of the words that
# the two have, and the least that is a few
SAME_WORDS = 0.4
MIN_SAME = 2
# A word that this many claims have, or more, and a quarter of them, is not what two claims are found to be alike by
COMMON_WORD_CLAIMS = 50

STOP_WORDS = frozenset(
    "a an and are as at be by for from in is it its of on or that the this to was were with which than then".split()
)
WORD = re.compile(r"[a-z0-9][a-z0-9\-]*")
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:e-?\d+)?")
# Names that are of nothing in particular: shared by many papers that have nothing to do with each other
GENERIC_NAMES = frozenset(
    "data dataset datasets cells samples human mouse rna dna sequencing analysis model models method methods "
    "code paper tool tools pipeline workflow scripts notebooks tutorial tutorials examples project".split()
)
COMMON_SOFTWARE = frozenset("python r numpy scipy pandas matplotlib jupyter linux windows macos excel matlab".split())

REPLICATES = re.compile(
    r"\b(?:replicat\w*|reproduc(?:e|es|ed|ing|tion)|re-?analy[sz]\w*|re-?implement\w*)\b", re.IGNORECASE
)
REPLACES = re.compile(
    r"\b(?:replac\w*|supersed\w*|succe(?:ed|eds|ssor)|outperform\w*|improv\w+ (?:on|upon)|instead of|better than)\b",
    re.IGNORECASE,
)
BUILDS_ON = re.compile(r"\b(?:builds? (?:on|upon)|built (?:on|upon)|based on|extend\w*|adapt\w*)\b", re.IGNORECASE)

MEANING = (
    "A relation is found by matching what was read of two papers: the accession or name of a dataset, the name of a "
    "method or of software, the address of code, a paper's own words that name another paper (its DOI, its code, or "
    "its title), and claims that have the same words and a number in common (agrees) or none (differs). Each comes "
    "with the quotes it was found from and where the papers say them. A program that matches words has not understood "
    "either paper, so a relation is a place to read and not a finding; a relation that is not here may still be there, "
    "and a paper that was not read has few of them. A claim that its own paper's code gave again when the code was run "
    "is said beside it, and a number that two papers agree on that one of them reproduced is marked corroborated."
)


def words_of(text: str) -> frozenset[str]:
    return frozenset(word for word in WORD.findall(text.lower()) if word not in STOP_WORDS and not word.isdigit())


def numbers_of(text: str) -> frozenset[str]:
    found = set()
    for each in NUMBER.findall(text):
        try:
            found.add(format(float(each), "g"))
        except ValueError:
            continue

    return frozenset(found)


def is_telling(number: str) -> bool:
    """Whether a number that two claims have in common is one that says they are alike: not a single digit or a year,
    which many things have."""
    digits = number.lstrip("-")

    return len(digits) >= 2 and not (digits.isdigit() and 1900 <= int(digits) <= 2100)


def cut(text: str, most: int) -> str:
    text = " ".join(text.split())

    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def key_of(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def code_key(url: str | None) -> str | None:
    """What a code address is by, so that https://github.com/Owner/Name.git and github.com/owner/name are one."""
    if not isinstance(url, str):
        return None
    text = re.sub(r"^https?://", "", url.strip().lower()).removeprefix("www.").rstrip("/").removesuffix(".git")

    return text if "/" in text else None


def how_it_refers(quote: str) -> str:
    """How the words around a name say that a paper refers to another: it replicates it, replaces or improves on it,
    builds on it, or only names it."""
    for how, pattern in (("replicates", REPLICATES), ("replaces", REPLACES), ("builds_on", BUILDS_ON)):
        if pattern.search(quote):
            return how

    return "mentions"


def anchor_of(item: Mapping[str, Any]) -> Mapping[str, Any]:
    anchor = item.get("anchor")

    return anchor if isinstance(anchor, dict) else {}


def label_of(fact: Mapping[str, Any]) -> str:
    for key in ("name", "accession", "url", "value"):
        if isinstance(fact.get(key), str) and fact[key].strip():
            return cut(fact[key], 80)

    return ""


def seen(agent_id: str, kind: str, fact: Mapping[str, Any]) -> dict[str, Any]:
    """A place in a paper that a relation is found from: what it names, and its quote and where that is."""
    anchor = anchor_of(fact)

    return {
        "agent": agent_id,
        "kind": kind,
        "fact": fact.get("id"),
        "name": label_of(fact),
        "quote": cut(str(fact.get("quote") or ""), QUOTE_CHARS),
        "page": anchor.get("page"),
        "section": anchor.get("section"),
    }


def text_of(fact: Mapping[str, Any]) -> str:
    """What a fact says, in one string: what it names and its quote."""
    skipped = {"id", "by", "at", "read_as", "anchor"}

    return " ".join(value for key, value in fact.items() if key not in skipped and isinstance(value, str))


def pairs(indexes: Iterable[int]) -> list[tuple[int, int]]:
    """Each two of the papers that are given by where they are, the earlier one first."""
    return list(combinations(sorted(indexes), 2))


def relation(kind: str, first: Mapping[str, Any], second: Mapping[str, Any], **more: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "a": first["id"],
        "b": second["id"],
        "directed": kind == "refers",
        "how": None,
        "basis": None,
        "corroborated": None,
        "summary": "",
        "evidence": [],
        **more,
    }


def shared_names(
    papers: Sequence[Mapping[str, Any]], kind: str, relation_kind: str, keys: Any, generic: frozenset[str]
) -> list[dict[str, Any]]:
    """The relations between papers that name the same thing among the facts of one kind.

    :param keys: What a fact is matched by, as a list of (basis, key).
    :param generic: Names that are not matched, as they are of nothing in particular.
    """
    buckets: dict[tuple[str, str], dict[int, Mapping[str, Any]]] = {}
    for index, paper in enumerate(papers):
        for fact in paper["facts"].get(kind, ()):
            for basis, key in keys(fact):
                if len(key) >= MIN_NAME_CHARS and key not in generic:
                    buckets.setdefault((basis, key), {}).setdefault(index, fact)
    found: dict[tuple[int, int], dict[str, Any]] = {}
    for (basis, _), holders in sorted(buckets.items()):
        for left, right in pairs(holders):
            one, other = holders[left], holders[right]
            entry = found.setdefault((left, right), relation(relation_kind, papers[left], papers[right]))
            if len(entry["evidence"]) < MOST_EVIDENCE:
                entry["evidence"].append(
                    {
                        "matched": str(one.get(basis)) if basis == "accession" else label_of(one),
                        "basis": basis,
                        "a": seen(papers[left]["id"], kind, one),
                        "b": seen(papers[right]["id"], kind, other),
                    }
                )
    for entry in found.values():
        entry["basis"] = "accession" if any(item["basis"] == "accession" for item in entry["evidence"]) else "name"

    return list(found.values())


def dataset_keys(fact: Mapping[str, Any]) -> list[tuple[str, str]]:
    keys = []
    if isinstance(fact.get("accession"), str):
        keys.append(("accession", normalize_name(fact["accession"])))
    if isinstance(fact.get("name"), str):
        keys.append(("name", normalize_name(fact["name"])))

    return keys


def name_keys(fact: Mapping[str, Any]) -> list[tuple[str, str]]:
    return [("name", normalize_name(fact["name"]))] if isinstance(fact.get("name"), str) else []


def versions_of(papers: Sequence[Mapping[str, Any]], found: list[dict[str, Any]]) -> None:
    """Puts the versions that two papers say of the software they share beside it."""
    said = {
        (paper["id"], fact.get("id")): fact.get("version")
        for paper in papers
        for fact in paper["facts"].get("software", ())
    }
    for each in found:
        for evidence in each["evidence"]:
            one, other = said.get((each["a"], evidence["a"]["fact"])), said.get((each["b"], evidence["b"]["fact"]))
            evidence["versions"] = {each["a"]: one or None, each["b"]: other or None}
            evidence["same_version"] = (one == other) if one and other else None


def finders_of(named: Mapping[str, str | None]) -> list[tuple[str, re.Pattern[str]]]:
    """How a paper is looked for in a text, by the surest way first: the pattern of each way is of the lowercased text,
    and of the text as words only for the title."""
    finders = []
    if named["doi"]:
        finders.append(("doi", re.compile(re.escape(named["doi"]) + r"(?![\w-])")))
    if named["code"]:
        finders.append(("code", re.compile(re.escape(named["code"]) + r"(?![\w-])")))
    if named["name"]:
        finders.append(("name", re.compile(r"(?<![\w-])" + re.escape(named["name"]) + r"(?![\w-])")))
    if named["title"]:
        finders.append(("title", re.compile(re.escape(named["title"]))))

    return finders


def refers_between(papers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The relations where the words of one paper name another: its DOI, the address of its code, the name of its code,
    or its title. A paper whose code is at the same address as another's names that code in its own words, which says
    nothing, so the address and the name of the code are not looked for between them."""
    names = []
    for paper in papers:
        key = code_key(paper.get("code"))
        name = key.rsplit("/", 1)[-1] if key is not None else None
        title = key_of(paper["title"])
        names.append(
            {
                "doi": paper["doi"].lower() if paper.get("doi") else None,
                "code": key,
                "name": name if name and len(name) >= MIN_CODE_NAME_CHARS and name not in GENERIC_NAMES else None,
                "title": title if len(title) >= MIN_TITLE_CHARS else None,
            }
        )
    finders = [finders_of(named) for named in names]
    found = []
    for first, said in enumerate(papers):
        items = [(kind, fact) for kind, facts in said["facts"].items() for fact in facts]
        items += [("claims", claim) for claim in said["claims"]]
        texts = []
        for kind, fact in items:
            text = text_of(fact)
            texts.append((kind, fact, text.lower(), key_of(text)))
        for second in range(len(papers)):
            if first == second:
                continue
            same_address = names[first]["code"] is not None and names[first]["code"] == names[second]["code"]
            ways = finders_of({**names[second], "code": None, "name": None}) if same_address else finders[second]
            evidence = []
            for kind, fact, lowered, keyed in texts:
                by = mention_of(lowered, keyed, ways)
                if by is not None:
                    how = how_it_refers(str(fact.get("quote") or ""))
                    evidence.append({"by": by, "how": how, "at": seen(said["id"], kind, fact)})
            if evidence:
                evidence.sort(key=lambda item: (BYS.index(item["by"]), -HOWS.index(item["how"])))
                found.append(
                    relation(
                        "refers",
                        said,
                        papers[second],
                        how=max((item["how"] for item in evidence), key=HOWS.index),
                        basis=min((item["by"] for item in evidence), key=BYS.index),
                        evidence=evidence[:MOST_EVIDENCE],
                    )
                )

    return found


def mention_of(lowered: str, keyed: str, finders: Sequence[tuple[str, re.Pattern[str]]]) -> str | None:
    """How a text names a paper, if it does, by the surest way: its DOI, the address of its code, the name of its code
    as a word of its own, or its title.

    :param lowered: The text in lowercase.
    :param keyed: The text as key_of gives it, which is what a title is looked for in.
    """
    for by, pattern in finders:
        if pattern.search(keyed if by == "title" else lowered):
            return by

    return None


def same_code(papers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    found = []
    keys = [code_key(paper.get("code")) for paper in papers]
    for first, second in pairs(range(len(papers))):
        if keys[first] is not None and keys[first] == keys[second]:
            commits = (papers[first].get("commit"), papers[second].get("commit"))
            found.append(
                relation(
                    "code",
                    papers[first],
                    papers[second],
                    basis="address",
                    evidence=[
                        {
                            "matched": keys[first],
                            "commits": {papers[first]["id"]: commits[0], papers[second]["id"]: commits[1]},
                            "same_commit": commits[0] == commits[1] if all(commits) else None,
                        }
                    ],
                )
            )

    return found


def claims_between(papers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The claims of two papers that have the same words, and either a number in common that says they are alike
    (agrees) or no number in common (differs). Only claims that have a number are set against each other."""
    prepared: list[list[dict[str, Any]]] = []
    postings: dict[str, list[tuple[int, int]]] = {}
    for index, paper in enumerate(papers):
        items = []
        for claim in paper["claims"]:
            text = f"{claim.get('value', '')} {claim.get('quote', '')}"
            numbers = numbers_of(text)
            if numbers and len(items) < MOST_CLAIMS_EACH:
                items.append({"claim": claim, "words": words_of(text), "numbers": numbers})
        for place, item in enumerate(items):
            for word in item["words"]:
                postings.setdefault(word, []).append((index, place))
        prepared.append(items)
    total = sum(len(items) for items in prepared)
    common = {word for word, places in postings.items() if len(places) > max(COMMON_WORD_CLAIMS, total // 4)}
    best: dict[tuple[int, int, str], list[tuple[float, str, str, dict[str, Any]]]] = {}
    for first, items in enumerate(prepared):
        for place, item in enumerate(items):
            counts: Counter[tuple[int, int]] = Counter()
            for word in item["words"] - common:
                counts.update(other for other in postings[word] if other[0] > first)
            for (second, there), few in counts.items():
                if few < MIN_SAME:
                    continue
                other = prepared[second][there]
                shared = item["words"] & other["words"]
                share = len(shared) / len(item["words"] | other["words"])
                if share < SAME_WORDS:
                    continue
                in_common = item["numbers"] & other["numbers"]
                if any(is_telling(number) for number in in_common):
                    kind = "agrees"
                elif not in_common:
                    kind = "differs"
                else:
                    continue
                evidence = {
                    "a": claim_seen(papers[first], item["claim"]),
                    "b": claim_seen(papers[second], other["claim"]),
                    "words": sorted(shared)[:8],
                    "numbers": sorted(in_common),
                }
                best.setdefault((first, second, kind), []).append(
                    (share, str(item["claim"].get("id")), str(other["claim"].get("id")), evidence)
                )
    found = []
    for (first, second, kind), places in sorted(best.items()):
        places.sort(key=lambda each: (-each[0], each[1], each[2]))
        kept = [each[3] for each in places[:MOST_EVIDENCE]]
        found.append(
            relation(
                kind,
                papers[first],
                papers[second],
                basis="words",
                corroborated=(
                    any("reproduced" in (each["a"]["reproduction"], each["b"]["reproduction"]) for each in kept)
                    if kind == "agrees"
                    else None
                ),
                evidence=kept,
            )
        )

    return found


def claim_seen(paper: Mapping[str, Any], claim: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **seen(paper["id"], "claims", claim),
        "name": cut(str(claim.get("value") or ""), 80),
        "reproduction": (paper.get("reproduction") or {}).get(claim.get("id")),
    }


def summary_of(each: Mapping[str, Any], titles: Mapping[str, str]) -> str:
    first, second = (cut(titles.get(each[side], each[side]), 60) for side in ("a", "b"))
    kind = each["kind"]
    first_evidence = each["evidence"][0] if each["evidence"] else {}
    if kind == "dataset":
        return f"{first} and {second} both used the dataset {first_evidence.get('matched', '')} (by {each['basis']})."
    if kind in ("software", "method"):
        return f"{first} and {second} both name the {kind} {first_evidence.get('matched', '')}."
    if kind == "code":
        said = {True: "at the same commit", False: "at different commits", None: "at commits not both known"}
        return f"{first} and {second} have code at {first_evidence['matched']}, {said[first_evidence['same_commit']]}."
    if kind == "refers":
        verb = {
            "mentions": "names",
            "builds_on": "says it builds on or extends",
            "replaces": "says it replaces or improves on",
            "replicates": "says it replicates or reproduces",
        }[each["how"]]
        return f"{first} {verb} {second} (its words name {second} by its {each['basis']})."
    said = "with a number in common" if kind == "agrees" else "with other numbers"
    return f"{first} and {second} have claims on the same words, {said}."


def build(papers: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The relations between papers, and a line for each paper.

    :param papers: Each as the server makes it from what is kept: its `id`, `title`, `doi`, `url`, `code` (the address
        of its code), `commit`, `read`, its `facts` by kind (each with an `id`, its fields, a `quote`, and an `anchor`),
        its `claims`, and its `reproduction`: the status of each claim that the code was held to, by claim id, if there
        is an account of it that is of what is kept now, and None if there is not.
    :return: The `papers`, the `relations` (the most that there are room for, with `truncated` if there were more), and
        how many there are of each kind.
    """
    found = [
        *refers_between(papers),
        *same_code(papers),
        *shared_names(papers, "datasets", "dataset", dataset_keys, GENERIC_NAMES),
        *shared_names(papers, "methods", "method", name_keys, GENERIC_NAMES),
        *claims_between(papers),
    ]
    software = shared_names(papers, "software", "software", name_keys, COMMON_SOFTWARE)
    versions_of(papers, software)
    found += software
    order = {paper["id"]: index for index, paper in enumerate(papers)}
    found.sort(key=lambda each: (KINDS.index(each["kind"]), order[each["a"]], order[each["b"]]))
    titles = {paper["id"]: paper["title"] for paper in papers}
    for each in found:
        each["summary"] = summary_of(each, titles)
    truncated = len(found) > MOST_RELATIONS
    shown = found[:MOST_RELATIONS]
    degrees = Counter(side for each in found for side in (each["a"], each["b"]))

    return {
        "papers": [
            {
                "id": paper["id"],
                "title": paper["title"],
                "read": paper["read"],
                "code": paper.get("code"),
                "claims": len(paper["claims"]),
                "facts": {kind: len(facts) for kind, facts in paper["facts"].items()},
                "reproduction": counts_of(paper.get("reproduction")),
                "relations": degrees[paper["id"]],
            }
            for paper in papers
        ],
        "relations": shown,
        "counts": {kind: sum(1 for each in found if each["kind"] == kind) for kind in KINDS},
        "truncated": truncated,
    }


def counts_of(statuses: Mapping[str, str] | None) -> dict[str, int] | None:
    """How many claims were reproduced, partly, not, or not attempted, if the code was held to the claims."""
    if statuses is None:
        return None
    counted = Counter(statuses.values())

    return {status: counted[status] for status in ("reproduced", "partly", "not_reproduced", "not_attempted")}


def select(
    graph: Mapping[str, Any], agent: str | None = None, kind: str | None = None, about: str | None = None
) -> dict[str, Any]:
    """The relations of a graph that are of a paper, of a kind, or on words, and the papers that they are between, or
    every paper if none of these is asked for.

    :param agent: The id or a part of the title of a paper; only the relations that it is in are kept.
    :param kind: One of KINDS.
    :param about: Words; only the relations that have them in what they say or in their quotes are kept.
    :raises ValueError: If the kind is not one, or there are no words in `about`.
    """
    if kind and kind not in KINDS:
        raise ValueError(f"A kind of relation is one of {', '.join(KINDS)}, not {kind!r}")
    wanted = words_of(about) if about else frozenset()
    if about and about.strip() and not wanted:
        raise ValueError("Give some words to look for, such as a dataset, a method, or a measure")
    ids = {
        paper["id"]
        for paper in graph["papers"]
        if agent and (agent == paper["id"] or agent.casefold() in paper["title"].casefold())
    }
    shown = []
    for each in graph["relations"]:
        if kind and each["kind"] != kind:
            continue
        if agent and not {each["a"], each["b"]} & ids:
            continue
        if wanted and not wanted & words_of(f"{each['summary']} {text_of_evidence(each)}"):
            continue
        shown.append(each)
    named = {side for each in shown for side in (each["a"], each["b"])}
    chosen = bool(agent or kind or wanted)

    return {
        "papers": [
            paper for paper in graph["papers"] if not chosen or paper["id"] in named or (agent and paper["id"] in ids)
        ],
        "relations": shown,
        "counts": {name: sum(1 for each in shown if each["kind"] == name) for name in KINDS},
        "truncated": graph["truncated"],
    }


def text_of_evidence(each: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for evidence in each["evidence"]:
        for place in (evidence, evidence.get("a"), evidence.get("b"), evidence.get("at")):
            if isinstance(place, dict):
                parts.extend(value for key in ("matched", "name", "quote") if isinstance(value := place.get(key), str))

    return " ".join(parts)
