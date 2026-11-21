"""The kinds of files that one PaperAgent's tool gives and another's takes, so that a join between them can be checked.

An agent's tool is a function of the authors' code, which takes the names of files and gives back values. Whether what
one gives can be what another takes is said only in the words of their docstrings, so the kinds are read from those
words, and a join is checked against them. There are four kinds: an AnnData file (h5ad), a VCF, a table of summary
statistics, and a table. A table of summary statistics is a table, so a tool that takes a table takes one.

This is a check of the declared kinds and of the names of files, and it is not a look at what is in a file: a tool
whose docstring does not say what it takes or gives has no kind, and a join with it is not checked, which is said.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

H5AD = "h5ad"
VCF = "vcf"
SUMMARY_STATISTICS = "summary_statistics"
TABLE = "table"
TYPES = (H5AD, VCF, SUMMARY_STATISTICS, TABLE)

LABELS = {
    H5AD: "an h5ad file (AnnData)",
    VCF: "a VCF file",
    SUMMARY_STATISTICS: "a table of summary statistics",
    TABLE: "a table",
}

# What the words of a docstring or a parameter name for each kind
WORDS = {
    H5AD: re.compile(r"\bh5ad\b|\banndata\b|\badata\b", re.IGNORECASE),
    VCF: re.compile(r"\bvcf\b", re.IGNORECASE),
    SUMMARY_STATISTICS: re.compile(r"summary[ _-]?stat|sumstat|\bgwas\b", re.IGNORECASE),
    TABLE: re.compile(r"\b(?:csv|tsv|table|dataframe|parquet)\b", re.IGNORECASE),
}

TABLE_SUFFIXES = (".csv", ".tsv", ".parquet", ".csv.gz", ".tsv.gz")
# A .txt is anything, so it is of a kind only where its name says that it is of summary statistics
TEXT_SUFFIXES = (".txt", ".txt.gz")
SUFFIXES = {".h5ad": H5AD, ".vcf": VCF, ".vcf.gz": VCF}
STATISTICS_NAME = re.compile(r"sumstat|summary[ _-]?stat|gwas", re.IGNORECASE)
FIELD = re.compile(r"^\s*:returns?\b[^:]*:(.*)$", re.IGNORECASE)
HEADING = re.compile(r"^\s*(returns?|yields?)\s*:?\s*$", re.IGNORECASE)
# What else a docstring has a section of, which ends the section of what it returns
SECTIONS = frozenset(
    "parameters args arguments other-parameters raises notes note examples example see-also references warns "
    "attributes receives yields".split()
)
# The most characters of a name or docstring that are read
MOST_READ = 4000


def kinds_in(text: str) -> frozenset[str]:
    """The kinds that words name. A table of summary statistics is not also a table here, so that a tool that gives
    one is told from one that gives any table."""
    # A name is made of words with underscores between them, which are not what a word ends at in a pattern
    words = text[:MOST_READ].replace("_", " ")
    found = {kind for kind, pattern in WORDS.items() if pattern.search(words)}
    if SUMMARY_STATISTICS in found:
        found.discard(TABLE)

    return frozenset(found)


def declared_inputs(parameters: Mapping[str, Any]) -> dict[str, frozenset[str]]:
    """What each parameter that takes the name of a file, or a list of them, is declared to take, from its name and
    the first sentence of its description, for those that say. A parameter that says nothing of a kind is not here.

    :param parameters: The tool's properties, each parameter's JSON schema by name.
    """
    taken: dict[str, frozenset[str]] = {}
    for name, schema in parameters.items():
        if not isinstance(schema, Mapping) or schema.get("type") not in ("string", "array", None):
            continue
        first = re.split(r"(?<=[.!?])\s", str(schema.get("description") or "").strip(), maxsplit=1)[0]
        kinds = kinds_in(f"{name} {first}")
        if kinds:
            taken[str(name)] = kinds

    return taken


def returns_of(docstring: str) -> str | None:
    """The words of the section of a docstring that says what it returns, in the reST, Google, or NumPy style, or None
    if it has none: from its heading to the next section, or, in reST, to the next field."""
    lines = docstring.splitlines()
    for index, line in enumerate(lines):
        if (field := FIELD.match(line)) is not None:
            taken = [field.group(1)]
            for follow in lines[index + 1 :]:
                if follow.strip().startswith(":"):
                    break
                taken.append(follow)
            return "\n".join(taken)
        if HEADING.match(line):
            taken = []
            for follow in lines[index + 1 :]:
                stripped = follow.strip()
                if stripped and set(stripped) <= {"-", "="}:
                    continue
                if stripped.rstrip(":").lower().replace(" ", "-") in SECTIONS:
                    break
                taken.append(follow)
            return "\n".join(taken)

    return None


def declared_output(docstring: str) -> frozenset[str] | None:
    """What a tool is declared to give, from what its docstring says it returns, or None if it does not say."""
    said = returns_of(docstring)

    return (kinds_in(said) or None) if said is not None else None


def type_of_name(name: str) -> str | None:
    """What a file's name says it is, or None if it says nothing of a kind here: an h5ad or a VCF by its end, and a
    table by its end, as one of summary statistics if its name says so."""
    lowered = name.strip().lower()
    for suffix, kind in SUFFIXES.items():
        if lowered.endswith(suffix):
            return kind
    base = lowered.rsplit("/", 1)[-1]
    if lowered.endswith(TABLE_SUFFIXES):
        return SUMMARY_STATISTICS if STATISTICS_NAME.search(base) else TABLE
    if lowered.endswith(TEXT_SUFFIXES) and STATISTICS_NAME.search(base):
        return SUMMARY_STATISTICS

    return None


def accepts(wanted: str, given: str) -> bool:
    return wanted == given or (wanted == TABLE and given == SUMMARY_STATISTICS)


def fits(takes: Iterable[str], gives: Iterable[str]) -> bool:
    """Whether something of one of the kinds that is given is taken by one of the kinds that is taken."""
    wanted = tuple(takes)

    return any(accepts(one, kind) for kind in gives for one in wanted)


def say(kinds: Iterable[str]) -> str:
    return " or ".join(LABELS[kind] for kind in TYPES if kind in set(kinds))


def check_arguments(takes: Mapping[str, frozenset[str]], arguments: Mapping[str, Any]) -> str | None:
    """Why the names of files that were passed are not of the kinds that the tool takes, or None if they are, or are not
    of a kind that can be told from the name."""
    for name, wanted in takes.items():
        value = arguments.get(name)
        names = (
            [value]
            if isinstance(value, str)
            else [one for one in value if isinstance(one, str)]
            if isinstance(value, list)
            else []
        )
        for each in names:
            kind = type_of_name(each)
            if kind is not None and not fits(wanted, (kind,)):
                return f"{name} takes {say(wanted)}, and {each} is {LABELS[kind]}."

    return None


def check_join(gives: frozenset[str] | None, takes: frozenset[str] | None) -> dict[str, Any]:
    """Whether what one tool gives can be what another takes.

    :param gives: What the first is declared to give, or None if its docstring does not say.
    :param takes: What the parameter of the second is declared to take, or None if its docstring does not say.
    :return: ``fits``, which is True or False, or None where either is not declared, so that it is not known; and why.
    """
    if gives is None:
        return {"fits": None, "why": "The first tool's docstring does not say what kind of file it gives."}
    if takes is None:
        return {"fits": None, "why": "The parameter's description does not say what kind of file it takes."}
    if fits(takes, gives):
        return {"fits": True, "why": f"It gives {say(gives)}, which the parameter takes ({say(takes)})."}

    return {"fits": False, "why": f"It gives {say(gives)}, and the parameter takes {say(takes)}."}
