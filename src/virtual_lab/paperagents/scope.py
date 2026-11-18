"""A check of what a person's data is against what the method card says the method was used on.

The card has statements of scope (card.py): the species, the tissue, the assay, the sample size, and the input that the
authors say the method was used on or needs. Before an agent's tool is run on a person's data, what the data is, as the
person or its description says, is put against them, and the answer is one of three, for each thing that was said of the
data:

- inside: a statement on the card covers it.
- outside: the card has statements of this sort that can be compared with it, and none covers it. This is the one that
  is warned of, with the card's own words (and the paper's, where it has them) so that the person sees what it is
  against, and may go on.
- not covered: the card says nothing of this sort, or says it in words that a program cannot compare (it says what the
  method was not used on, or gives one size and not a range, or counts something else). It is not called inside, and it
  is not warned of as outside either, since neither is known. What the card does say is shown.

A program does this and a model does not: it compares words after putting the names that mean one thing as one (mouse
and Mus musculus, scRNA-seq and single-cell RNA sequencing), and compares a sample size with the range that a statement
gives ("at least 500 nuclei", "1,000 to 10,000 cells"). A model says what the data is, since only it or the person
knows that, and the card is what it is: a draft that a model made from the paper, unless a person approved it. That
data is inside the card says that it is within what the paper tested. It does not say that the method works on it, nor
that data outside the card does not.

A choice that errs on the side of the warning: data is inside only if every word that says what it is, apart from small
words, is among those of the statements, so that "mouse or rat" is not inside a card that says "mouse".
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

INSIDE = "inside"
OUTSIDE = "outside"
NOT_COVERED = "not covered"

# What of the data may be said, in the order that they are checked, with the kind of statement of scope on the card that
# each is compared with
TEXT_FIELDS = {"species": "species", "tissue": "tissue", "assay": "assay", "input_format": "input"}
SIZE_ASPECT = "sample size"
ASPECTS = ("species", "tissue", "assay", SIZE_ASPECT, "input")
LABELS = {
    "species": "species",
    "tissue": "tissue",
    "assay": "assay",
    "input_format": "input format",
    "sample_size": "sample size",
}

# What a kind of statement of scope is called where it is not what it is called on the card
NAMES = {"input": "input format"}

MAX_WORDS_CHARS = 200
MAX_UNIT_CHARS = 40
MAX_SIZE = 10**12
# How much of a quote is given in a warning
QUOTE_CHARS = 240

# Names that mean one thing, as they are written, so that the data and the card are not told apart by how they spell it
ALIASES: dict[str, tuple[str, ...]] = {
    "human": ("human", "humans", "homo sapiens", "h sapiens"),
    "mouse": ("mouse", "mice", "murine", "mus musculus", "m musculus"),
    "rat": ("rat", "rats", "rattus norvegicus", "r norvegicus"),
    "zebrafish": ("zebrafish", "danio rerio", "d rerio"),
    "fly": ("fly", "flies", "fruit fly", "fruit flies", "drosophila", "drosophila melanogaster", "d melanogaster"),
    "worm": ("worm", "worms", "nematode", "c elegans", "caenorhabditis elegans"),
    "yeast": ("yeast", "budding yeast", "saccharomyces cerevisiae", "s cerevisiae"),
    "arabidopsis": ("arabidopsis", "arabidopsis thaliana", "a thaliana"),
    "ecoli": ("e coli", "escherichia coli"),
    "pig": ("pig", "pigs", "swine", "porcine", "sus scrofa"),
    "macaque": ("macaque", "macaques", "rhesus", "rhesus macaque", "macaca mulatta"),
    "chicken": ("chicken", "chickens", "gallus gallus"),
    "cow": ("cow", "cows", "cattle", "bovine", "bos taurus"),
    "pbmc": ("pbmc", "pbmcs", "peripheral blood mononuclear cell", "peripheral blood mononuclear cells"),
    "blood": ("blood", "whole blood", "peripheral blood"),
    "scrnaseq": (
        "scrna seq",
        "scrnaseq",
        "scrna",
        "single cell rna seq",
        "single cell rna sequencing",
        "single cell rna",
        "single cell transcriptomics",
        "single cell transcriptome",
    ),
    "snrnaseq": (
        "snrna seq",
        "snrnaseq",
        "snrna",
        "single nucleus rna seq",
        "single nuclei rna seq",
        "single nucleus rna sequencing",
        "single nuclei rna sequencing",
        "single nucleus rna",
    ),
    "rnaseq": (
        "rna seq",
        "rnaseq",
        "rna sequencing",
        "bulk rna seq",
        "bulk rna sequencing",
        "transcriptome sequencing",
    ),
    "scatacseq": ("scatac seq", "scatacseq", "single cell atac seq", "single cell atac"),
    "atacseq": ("atac seq", "atacseq"),
    "chipseq": ("chip seq", "chipseq"),
    "wgs": ("wgs", "whole genome sequencing", "whole genome seq"),
    "wes": ("wes", "exome sequencing", "exome seq", "whole exome sequencing", "whole exome seq"),
    "hic": ("hi c", "hic"),
    "citeseq": ("cite seq", "citeseq"),
    "spatial": ("spatial transcriptomics", "visium"),
    "proteomics": ("proteomics", "mass spectrometry", "mass spec"),
    "h5ad": ("h5ad", "anndata"),
    "fastq": ("fastq", "fq"),
}

# Words that do not say what a thing is, and so are not compared. A compressed file is of the same format
STOP_WORDS = frozenset(
    "the a an of and or in on at from with for to by as is are was were be cell tissue sample data dataset type "
    "derived using used use based like such including e g eg ie gz gzip zip compressed file format object".split()
)

# Words that make a statement of scope say that it is of anything, if they are all it has besides words that only say
# what it is about, so that it covers whatever is said of the data
WILDCARD_WORDS = frozenset({"any", "all", "every", "agnostic", "independent", "universal", "general"})
GENERIC_WORDS = frozenset(
    {"species", "organism", "tissue", "assay", "technology", "method", "kind", "input", "format", "type"}
)

# Words that make a statement say what was not so, which a program does not read: such a statement is shown, and is not
# compared
NEGATING_WORDS = frozenset(
    {"not", "no", "non", "never", "without", "except", "excluding", "exclude", "excludes", "unlike", "cannot", "nor"}
)

IRREGULAR_PLURALS = {"nuclei": "nucleus"}


def singular(word: str) -> str:
    """A word as it is for one, as far as ending with s says, so that the data and the card say it the same way. It is
    not the word's right form, and need not be, since it is only that both are put into it."""
    if word in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[word]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]

    return word


def plain_words(text: str) -> list[str]:
    """What is said in words, lower case, with what is not a letter or a digit as a space."""
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKC", text).casefold()).split()


# One pass, longest names first, so that a name that is part of a longer one is not taken for it
_ALIAS_OF = {" ".join(plain_words(name)): canon for canon, names in ALIASES.items() for name in names}
_ALIAS_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:"
    + "|".join(re.escape(name) for name in sorted(_ALIAS_OF, key=len, reverse=True))
    + r")(?![a-z0-9])"
)
_WILDCARD = frozenset(singular(word) for word in WILDCARD_WORDS)
_GENERIC = frozenset(singular(word) for word in GENERIC_WORDS)


def tokens(text: str) -> list[str]:
    """The words of a statement that say what it is about: the names that mean one thing as one, and the other words as
    one of them, without the small ones."""
    said = " ".join(plain_words(text))
    found: list[str] = []

    def other(part: str) -> None:
        found.extend(word for word in map(singular, part.split()) if word not in STOP_WORDS)

    start = 0
    for match in _ALIAS_PATTERN.finditer(said):
        other(said[start : match.start()])
        found.append(_ALIAS_OF[match.group(0)])
        start = match.end()
    other(said[start:])

    return found


def is_negated(text: str) -> bool:
    words = plain_words(text)

    return any(word in NEGATING_WORDS for word in words) or "other than" in " ".join(words)


def is_wildcard(found: set[str]) -> bool:
    return bool(found & _WILDCARD) and not found - _WILDCARD - _GENERIC


# A sample size


class Size:
    """What a statement says of a sample size: a range, from one end to the other (either may be open, and either may be
    left out of what is in it), or one number.

    :param low: The least that is inside, or None if there is no least.
    :param high: The most that is inside, or None.
    :param low_open: Whether low itself is outside, as "more than 500" says.
    :param high_open: Whether high itself is outside.
    :param exact: Whether the statement is one number, which says what was used and not a range.
    :param unit: What is counted, as the statement says it, or an empty string.
    """

    def __init__(
        self,
        low: float | None,
        high: float | None,
        low_open: bool = False,
        high_open: bool = False,
        exact: bool = False,
        unit: str = "",
    ) -> None:
        self.low = low
        self.high = high
        self.low_open = low_open
        self.high_open = high_open
        self.exact = exact
        self.unit = unit

    def holds(self, number: int) -> bool:
        if self.low is not None and (number < self.low or (self.low_open and number == self.low)):
            return False

        return not (self.high is not None and (number > self.high or (self.high_open and number == self.high)))


_SYMBOLS = (
    (">=", " at least "),
    ("≥", " at least "),
    ("<=", " at most "),
    ("≤", " at most "),
    (">", " more than "),
    ("<", " fewer than "),
)
_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(k\b|m(?![a-z])| thousand\b| million\b)?")
_MULTIPLIERS = {"k": 1e3, "m": 1e6, "thousand": 1e3, "million": 1e6}
_BEFORE_PHRASES = (
    ("at least", False, True),
    ("no fewer than", False, True),
    ("no less than", False, True),
    ("minimum of", False, True),
    ("minimum", False, True),
    ("more than", True, True),
    ("greater than", True, True),
    ("over", True, True),
    ("above", True, True),
    ("exceeding", True, True),
    ("at most", False, False),
    ("up to", False, False),
    ("no more than", False, False),
    ("maximum of", False, False),
    ("maximum", False, False),
    ("fewer than", True, False),
    ("less than", True, False),
    ("under", True, False),
    ("below", True, False),
)
_AFTER_PHRASES = (
    ("or more", False, True),
    ("or greater", False, True),
    ("or larger", False, True),
    ("and above", False, True),
    ("and up", False, True),
    ("+", False, True),
    ("or fewer", False, False),
    ("or less", False, False),
    ("or smaller", False, False),
    ("and below", False, False),
    ("and under", False, False),
)
# A longer phrase is looked for before a shorter one that ends it, as "no more than" is before "more than"
_BEFORE = sorted(_BEFORE_PHRASES, key=lambda phrase: -len(phrase[0]))
_AFTER = sorted(_AFTER_PHRASES, key=lambda phrase: -len(phrase[0]))
_JOINERS = frozenset({"to", "-", "through"})
_NOT_UNITS = frozenset({"or", "and", "to", "of", "per", "each", "from", "in", "at", "with", "more", "fewer", "less"})


def unit_of(after: str) -> str:
    """What is counted, as the first word after a number says it, if it is a word that says it."""
    match = re.match(r"[^a-z]*([a-z]+)", after)
    if match is None or match.group(1) in _NOT_UNITS:
        return ""

    return singular(match.group(1))


def size_of(text: str) -> Size | None:
    """What a statement says of a sample size, or None if it is not in words that a program reads: no number, more than
    two, or two that are not a range."""
    said = unicodedata.normalize("NFKC", text).casefold()
    for symbol, words in _SYMBOLS:
        said = said.replace(symbol, words)
    said = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", said)
    said = re.sub(r"\s*[–—−]\s*", "-", said)
    numbers = list(_NUMBER.finditer(said))
    if not 1 <= len(numbers) <= 2:
        return None

    def value(match: re.Match[str]) -> float:
        times = _MULTIPLIERS[match.group(2).strip()] if match.group(2) else 1
        return float(match.group(1)) * times

    unit = unit_of(said[numbers[-1].end() :])
    if len(numbers) == 2:
        between = said[numbers[0].end() : numbers[1].start()].strip()
        # "and" is a range only as in "between 3 and 5": "10 and 20 donors" is two sizes, and so is "5 or 10"
        said_between = " ".join(said[: numbers[0].start()].split()).endswith("between")
        if between not in _JOINERS and not (between == "and" and said_between):
            return None
        first, second = sorted((value(numbers[0]), value(numbers[1])))

        return Size(first, second, unit=unit)
    number = value(numbers[0])
    before = " " + " ".join(said[: numbers[0].start()].split())
    after = said[numbers[0].end() :].lstrip()
    for phrase, strict, lower in _BEFORE:
        if before.endswith(" " + phrase):
            return bounded(number, strict, lower, unit)
    for phrase, strict, lower in _AFTER:
        if after.startswith(phrase):
            return bounded(number, strict, lower, unit_of(after[len(phrase) :]))

    return Size(number, number, exact=True, unit=unit)


def bounded(number: float, strict: bool, lower: bool, unit: str) -> Size:
    """A range that is open at one end: from the number up if lower, and from it down if not."""
    if lower:
        return Size(number, None, low_open=strict, unit=unit)

    return Size(None, number, high_open=strict, unit=unit)


# What the data is, as it is given


def clean(described: Mapping[str, Any]) -> dict[str, Any]:
    """The things that were said of the data, by the kind of statement of scope each is compared with: words for the
    species, tissue, assay, and input, and for the sample size a number and what it counts.

    :raises ValueError: If nothing is said of it, or a thing is not said in words, or a size is not a whole number of
        one or more, or what is counted is said without a size.
    """
    given: dict[str, Any] = {}
    for name, aspect in TEXT_FIELDS.items():
        value = described.get(name)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"The {LABELS[name]} is said in words")
        words = " ".join(value.split())
        if not words:
            continue
        if len(words) > MAX_WORDS_CHARS:
            raise ValueError(f"The {LABELS[name]} can be at most {MAX_WORDS_CHARS} characters")
        if not tokens(words):
            raise ValueError(f"The {LABELS[name]} has no words that say what it is")
        given[aspect] = words
    size = described.get("sample_size")
    unit = described.get("sample_unit")
    if unit is not None and not isinstance(unit, str):
        raise ValueError("What the sample size counts is said in words")
    unit = " ".join((unit or "").split())
    if len(unit) > MAX_UNIT_CHARS:
        raise ValueError(f"What the sample size counts can be at most {MAX_UNIT_CHARS} characters")
    if size is not None and size != 0:
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= MAX_SIZE:
            raise ValueError(f"The sample size is a whole number from 1 to {MAX_SIZE:,}")
        given[SIZE_ASPECT] = (size, unit)
    elif unit:
        raise ValueError("Say the sample size as well, or leave out what it counts")
    if not given:
        raise ValueError("Say something of the data: its species, tissue, assay, sample size, or input format")

    return given


# The statements of scope that are on the card


def quote_of(fact: Mapping[str, Any]) -> str:
    text = " ".join(str(fact.get("quote") or "").split())

    return text if len(text) <= QUOTE_CHARS else text[: QUOTE_CHARS - 1] + "…"


def view(fact: Mapping[str, Any]) -> dict[str, Any]:
    """A statement of scope as it is given back: what it says, the words and the place in the paper that it is of, and
    whose it is."""
    anchor = fact.get("anchor") if isinstance(fact.get("anchor"), Mapping) else None

    return {
        "id": fact["id"],
        "value": fact["value"],
        "quote": fact.get("quote") or "",
        "by": fact.get("by"),
        "changed": fact.get("read_as") is not None,
        "page": anchor.get("page") if anchor else None,
        "section": anchor.get("section") if anchor else None,
    }


def says(fact: Mapping[str, Any]) -> str:
    """A statement of scope in a line, with whose it is: a fact that a person changed is theirs and has the paper's
    words, and one that they added has no place in the paper, and the words that they gave if they gave some."""
    quote = quote_of(fact)
    value = f"“{fact['value']}”"
    if fact.get("by") != "person":
        return f"{value} (the paper: “{quote}”)" if quote else value
    if fact.get("read_as") is not None:
        return (
            f"{value} (changed by a person; the paper's words: “{quote}”)"
            if quote
            else f"{value} (changed by a person)"
        )

    return f"{value} (added by a person: “{quote}”)" if quote else f"{value} (added by a person)"


def given_words(aspect: str, value: Any) -> str:
    if aspect != SIZE_ASPECT:
        return str(value)
    number, unit = value

    return f"{number:,} {unit}".strip()


def compare_words(words: str, facts: Sequence[Mapping[str, Any]]) -> tuple[str, list[Mapping[str, Any]], str]:
    """Whether the statements of scope that are of one sort cover what the data is, as words.

    The words are covered if each of those that say what it is is among those of the statements, taken together, so
    that data that is of two things is inside a card that has a statement of each. A statement that says what was not
    so, or that has no word that says what it is, is not compared, and if what is not covered is what such a statement
    names, the answer is that it is not covered, since it is not known to be outside.
    """
    wanted = set(tokens(words))
    union: set[str] = set()
    covering: list[Mapping[str, Any]] = []
    comparable: list[Mapping[str, Any]] = []
    unclear: list[Mapping[str, Any]] = []
    anything: list[Mapping[str, Any]] = []
    named: set[str] = set()
    for fact in facts:
        found = set(tokens(fact["value"]))
        if is_negated(fact["value"]) or not found:
            unclear.append(fact)
            named |= found
            continue
        if is_wildcard(found):
            anything.append(fact)
            continue
        comparable.append(fact)
        union |= found
        if found & wanted:
            covering.append(fact)
    # Said before anything else covers it, since a statement of "any" does not cover what another one rules out
    if wanted & named:
        return (
            NOT_COVERED,
            list(facts),
            "A statement on the card says what it was not, in words that a program cannot compare.",
        )
    if anything:
        return INSIDE, anything, "A statement on the card says it is of any."
    if wanted <= union:
        return INSIDE, covering, "Statements on the card name it."
    if not comparable:
        return NOT_COVERED, list(unclear), "The card says nothing of this that a program can compare."

    return OUTSIDE, list(facts), "No statement on the card names it."


def compare_size(
    number: int, unit: str, facts: Sequence[Mapping[str, Any]]
) -> tuple[str, list[Mapping[str, Any]], str]:
    """Whether the statements of scope that are of the sample size cover this one.

    A statement that is a range, or that is open at one end, is compared with it. A statement that is one number says
    what was used and not a range, so it covers a size only if that is the size, and is not compared otherwise. What
    is counted is compared as the words say it, and a size of one kind is not put against a range of another: not one
    that counts something against a size that is not said to count anything.
    """
    counted = {singular(word) for word in plain_words(unit)}
    covering: list[Mapping[str, Any]] = []
    ranges: list[Mapping[str, Any]] = []
    unclear: list[Mapping[str, Any]] = []
    counts_something = False
    for fact in facts:
        size = size_of(fact["value"])
        counts_something = counts_something or bool(size and size.unit)
        if size is None or (size.exact and not size.holds(number)):
            unclear.append(fact)
        elif size.unit and size.unit not in counted:
            unclear.append(fact)
        elif size.holds(number):
            covering.append(fact)
        else:
            ranges.append(fact)
    if covering:
        return INSIDE, covering, "A statement on the card gives a size or a range that has it."
    if ranges:
        return OUTSIDE, [*ranges, *unclear], "The ranges that the card gives do not have it."
    if facts and not counted and counts_something:
        return NOT_COVERED, list(facts), "The card gives the size as a count of something. Say what the size counts."
    if facts:
        return NOT_COVERED, list(facts), "The card gives sizes in words that a program cannot put against this one."

    return NOT_COVERED, [], ""


def warning_of(aspect: str, given: str, facts: Sequence[Mapping[str, Any]]) -> str:
    """What a person is told when the data is outside what the card says, with the card's words."""
    stated = "; ".join(says(fact) for fact in facts)
    name = NAMES.get(aspect, aspect)

    return f"Outside what the card says: the data's {name} is “{given}”, and the card gives the {name} as {stated}."


def check(facts: Sequence[Mapping[str, Any]], described: Mapping[str, Any]) -> dict[str, Any]:
    """Puts what the data is against what the statements of scope on a card say.

    :param facts: The statements of scope on the card, as card.shown gives them, with what is not of the card, as a
        statement that was taken off, left out.
    :param described: What is said of the data, as clean takes it.
    :return: The answer for the whole, which is outside if the data is outside in anything, inside if it is inside in
        all that was said of it, and not covered otherwise; the answer for each thing that was said, with the card's
        statements that it is of; the warnings, each with the card's words; and the statements on the card of the
        sorts that nothing was said of, so that what else the card has can be seen.
    :raises ValueError: If what is said of the data is not as clean takes it.
    """
    given = clean(described)
    by_aspect = {aspect: [fact for fact in facts if fact["aspect"] == aspect] for aspect in (*ASPECTS, "other")}
    answers: list[dict[str, Any]] = []
    warnings: list[str] = []
    for aspect in ASPECTS:
        if aspect not in given:
            continue
        value = given[aspect]
        if aspect == SIZE_ASPECT:
            outcome, evidence, reason = compare_size(value[0], value[1], by_aspect[aspect])
        else:
            outcome, evidence, reason = compare_words(value, by_aspect[aspect])
        words = given_words(aspect, value)
        if outcome == NOT_COVERED and not by_aspect[aspect]:
            reason = f"The card has no statement of the {aspect}."
        answers.append(
            {
                "aspect": aspect,
                "given": words,
                "outcome": outcome,
                "says": [view(fact) for fact in evidence],
                "reason": reason,
            }
        )
        if outcome == OUTSIDE:
            warnings.append(warning_of(aspect, words, evidence))
    outcomes = {answer["outcome"] for answer in answers}
    whole = OUTSIDE if OUTSIDE in outcomes else INSIDE if outcomes == {INSIDE} else NOT_COVERED

    return {
        "outcome": whole,
        "aspects": answers,
        "warnings": warnings,
        "not_checked": [
            {"aspect": aspect, "says": [view(fact) for fact in by_aspect[aspect]]}
            for aspect in (*ASPECTS, "other")
            if aspect not in given and by_aspect[aspect]
        ],
    }
