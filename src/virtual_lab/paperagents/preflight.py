"""The check before any code of a paper is set up: whether it is worth going on, from what was found in it.

It is the first look at the failures that stop a paper's code from becoming something usable, which are mostly not
in the method: there is no code, or no license to use it under, or nothing to show how it is used; what it needs cannot
be installed, or needs a GPU that the sandbox does not have; the data it was made for is not where anyone can get it;
the examples read from one person's computer. Each is a check that says ok, a thing to know (note), a thing to weigh
(warn), a reason to stop (block), or that it is not known (unknown), and says why in words.

The answer is `go` if no check is a warning or a block, `ask` if some are warnings and none is a block, and `no-go` if
one is a block. It is advice: it is made from what the files say, and nothing was run, so it can be wrong in either
direction, and says what it went by. A person decides.
"""

from collections.abc import Callable
from typing import Any

from virtual_lab.chat import describe_size

# What the sandbox runs, so that code in anything else is not something tools can be made from
RUNNABLE = ("Python", "R")
RUNNABLE_SHARE = 0.5

# What it takes to make tools of a tutorial, as a rough guess: its text goes in with instructions and the signatures
# of what it calls, a wrapper comes out, and it is asked again with what went wrong up to this many times
CHARACTERS_PER_TOKEN = 4
TOKENS_IN_PER_TUTORIAL = 3_000
TOKENS_OUT_PER_TUTORIAL = 2_000
MAX_ATTEMPTS = 3
MAX_TUTORIALS_COSTED = 20
MAX_CHARACTERS_PER_TUTORIAL = 60_000

STATUSES = ("ok", "note", "warn", "block", "unknown")
VERDICTS = ("go", "ask", "no-go")


def check(name: str, title: str, status: str, detail: str) -> dict[str, str]:
    return {"id": name, "title": title, "status": status, "detail": detail}


def plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count:,} {one if count == 1 else many or one + 's'}"


def code_check(stock: dict[str, Any]) -> dict[str, str]:
    languages = stock["languages"]
    total = sum(language["bytes"] for language in languages)
    if not languages or total == 0:
        return check(
            "code",
            "There is code",
            "block",
            f"No code was found in its {plural(stock['files'], 'file')}. A project of data or of text has nothing to "
            "make tools from.",
        )
    runnable = sum(language["bytes"] for language in languages if language["name"] in RUNNABLE)
    first = languages[0]["name"]
    if runnable == 0:
        return check(
            "code",
            "There is code the sandbox runs",
            "block",
            f"It is written in {', '.join(language['name'] for language in languages[:3])}, and the sandbox runs "
            f"{' and '.join(RUNNABLE)}. Tools are made from code that can be called from there.",
        )
    if runnable / total < RUNNABLE_SHARE:
        return check(
            "code",
            "There is code the sandbox runs",
            "warn",
            f"Most of it is {first}, and only part is {' or '.join(RUNNABLE)}, which are what the sandbox runs. Tools "
            "can be made of that part and not of the rest.",
        )

    return check(
        "code", "There is code the sandbox runs", "ok", f"Mostly {first}, in {plural(languages[0]['files'], 'file')}."
    )


def license_check(stock: dict[str, Any], paper: dict[str, Any] | None) -> dict[str, str]:
    found = stock["license"]
    said = [fact["name"] for fact in (paper or {}).get("licenses", []) if fact.get("covers") == "code"]
    paper_says = f" The paper says the code is under {', '.join(said[:2])}." if said else ""
    title = "It has a license to use it under"
    if found is None:
        return check(
            "license",
            title,
            "warn",
            "It has no license. Code with none is not free to use or to share, even if it is public: the authors keep "
            f"the rights. Ask them, or go on only if you are sure of your use.{paper_says}",
        )
    name, kind = found["name"], found["kind"]
    if name is None and kind == "noncommercial":
        return check(
            "license", title, "note", "It has a license that limits use to research, or forbids use for money. Read it."
        )
    if name is None:
        return check(
            "license",
            title,
            "warn",
            f"It has a license file ({', '.join(found['files']) or 'in its manifest'}) that was not recognized. "
            f"Read it before using the code.{paper_says}",
        )
    if kind == "noncommercial":
        return check(
            "license",
            title,
            "note",
            f"{name}: for non-commercial use only. Fine for research, not for a product.{paper_says}",
        )
    if kind == "copyleft":
        return check(
            "license",
            title,
            "note",
            f"{name}: it can be used, and what is built on it and shared has to be shared on the same terms."
            f"{paper_says}",
        )

    return check("license", title, "ok", f"{name}.{paper_says}")


def tutorials_check(stock: dict[str, Any]) -> dict[str, str]:
    title = "It shows how it is used"
    count = stock["tutorials"]["count"]
    if count:
        notebooks = stock["notebooks"]["count"]
        return check(
            "tutorials",
            title,
            "ok",
            f"{plural(count, 'tutorial or example')}, of which {plural(notebooks, 'notebook')}. They are what tools "
            "are made from, and what they are checked against.",
        )
    if stock["readme"] and stock["readme"]["example"]:
        return check(
            "tutorials",
            title,
            "warn",
            "It has no notebook or example script, only a README that shows its use. There is nothing to run as a "
            "reference, so a tool could not be checked against how the authors ran it.",
        )

    return check(
        "tutorials",
        title,
        "warn",
        "It has no notebook, example, or tutorial, and its README does not show how to use it. There is nothing to "
        "run as a reference, and nothing to make tools from.",
    )


def tests_check(stock: dict[str, Any]) -> dict[str, str]:
    count = stock["tests"]["count"]
    if count:
        return check(
            "tests",
            "It has its own tests",
            "ok",
            f"{plural(count, 'test file')}, which are one more thing to check tools against.",
        )

    return check("tests", "It has its own tests", "note", "It has none, so one kind of check is not there to be made.")


def environment_check(stock: dict[str, Any]) -> dict[str, str]:
    title = "It says what it needs installed"
    files = stock["environment"]
    if not files:
        return check(
            "environment",
            title,
            "warn",
            "No file says what to install: no requirements, environment, lock, or Dockerfile. What it needs would "
            "have to be guessed from what the code imports, which is not done.",
        )
    pinned = [item for item in files if item["pins"] in ("locked", "all")]
    names = ", ".join(item["path"] for item in files[:3])
    if pinned:
        return check("environment", title, "ok", f"{names}, with versions given, so it can be set up as it was.")

    return check(
        "environment",
        title,
        "note",
        f"{names}. The versions are not all given, so what is set up today may not be what the authors used, and can "
        "fail where their code changed under it.",
    )


def gpu_check(stock: dict[str, Any]) -> dict[str, str]:
    title = "It runs without a GPU"
    required, optional = stock["gpu"]["required"], stock["gpu"]["optional"]
    if required:
        reasons = "; ".join(f"{item['signal']} ({item['path']})" for item in required[:3])
        return check(
            "gpu",
            title,
            "block",
            f"It needs a GPU: {reasons}. The sandbox has none, and the check can be wrong where code only prefers one.",
        )
    if optional:
        return check("gpu", title, "note", "It can use a GPU and looks for one, so it should run on a CPU, slower.")

    return check("gpu", title, "ok", "Nothing in it asks for a GPU.")


def data_check(stock: dict[str, Any], paper: dict[str, Any] | None) -> dict[str, str]:
    title = "Its data can be found"
    data = stock["data"]
    if data["lfs_pointers"] or data["dvc"]:
        what = "Git LFS" if data["lfs_pointers"] else "DVC"
        return check(
            "data",
            title,
            "warn",
            f"Some of its files are kept in {what}, which is not fetched: what is here are pointers to them. "
            "They would have to be fetched from where they are kept.",
        )
    signals = []
    if data["count"]:
        signals.append(f"{plural(data['count'], 'data or model file')} in the code ({describe_size(data['bytes'])})")
    if data["links"]:
        signals.append(f"{plural(len(data['links']), 'link')} to where data is kept")
    if data["accessions"]:
        signals.append(f"accessions {', '.join(data['accessions'][:3])}")
    if paper is not None:
        accessions = [fact for fact in paper.get("datasets", []) if fact.get("accession")]
        places = [fact for fact in paper.get("links", []) if fact.get("role") == "data"]
        statements = [fact for fact in paper.get("availability", []) if fact.get("kind") == "data"]
        if accessions:
            signals.append(f"{plural(len(accessions), 'accession')} in the paper")
        if places:
            signals.append(f"{plural(len(places), 'link')} to data in the paper")
        if statements:
            signals.append("a statement of where the data is in the paper")
    if signals:
        found = "; ".join(signals)

        return check(
            "data", title, "ok", f"{found[0].upper()}{found[1:]}. Whether they can be had is not yet looked at."
        )
    if paper is None:
        return check(
            "data",
            title,
            "unknown",
            "Nothing in the code says where its data is. The paper has not been read through, and may say.",
        )

    return check(
        "data",
        title,
        "unknown",
        "Nothing in the code or the paper says where its data is. If the tutorials need data that is not in the code, "
        "it will have to be found.",
    )


def portability_check(stock: dict[str, Any]) -> dict[str, str] | None:
    if not stock["tutorials"]["count"]:
        return None
    title = "Its examples do not depend on one machine"
    found = stock["absolute_paths"]
    if found["count"]:
        first = found["listed"][0]
        return check(
            "portability",
            title,
            "warn",
            f"{plural(found['count'], 'example')} read from a place on someone's computer, such as "
            f"{first['example']} in {first['path']}. They will fail until that is changed to something that exists "
            "here.",
        )

    return check("portability", title, "ok", "No example reads from a path on someone's computer.")


def parts_check(stock: dict[str, Any]) -> dict[str, str] | None:
    if not stock["submodules"]:
        return None

    paths = ", ".join(item["path"] for item in stock["submodules"][:3])

    return check(
        "submodules",
        "All of its code is here",
        "note",
        f"It has {plural(len(stock['submodules']), 'submodule')} ({paths}), which are not fetched, so the code in "
        "them is missing.",
    )


def size_check(stock: dict[str, Any]) -> dict[str, str]:
    title = "All of it was looked at"
    sizes = f"{plural(stock['files'], 'file')}, {describe_size(stock['bytes'])}."
    if not stock["complete"]:
        return check(
            "size",
            title,
            "note",
            f"{sizes} It is large, and only part of it was looked at, so what is said here may miss some.",
        )

    return check("size", title, "ok", sizes)


def estimate(stock: dict[str, Any], price: Callable[[int, int], float] | None) -> dict[str, Any]:
    """A rough guess of what making tools from the tutorials would cost in model requests, as a low and a high, and what
    it is a guess from. The low is one request for each tutorial and the high is every one asked again until it has
    been asked the most times.

    :param price: Gives the cost in dollars of a count of input tokens and of output tokens, or raises ValueError if
        the model's price is not known. None if there is no model to say it of.
    """
    tutorials = stock["tutorials"]
    count = min(tutorials["count"], MAX_TUTORIALS_COSTED)
    if count == 0:
        return {"low": None, "high": None, "tutorials": 0, "basis": "There are no tutorials to make tools from."}
    characters = min(tutorials["characters"], count * MAX_CHARACTERS_PER_TUTORIAL)
    tokens_in = characters // CHARACTERS_PER_TOKEN + count * TOKENS_IN_PER_TUTORIAL
    tokens_out = count * TOKENS_OUT_PER_TUTORIAL
    basis = (
        f"A guess from {plural(count, 'tutorial')} of about {characters // 1000:,} thousand characters: one request "
        f"for each, to {MAX_ATTEMPTS} asked again with what went wrong. Building the environment and running the "
        "tutorials cost time, not model requests, and are not in it."
    )
    if price is None:
        return {"low": None, "high": None, "tutorials": count, "basis": f"{basis} The model's price is not known."}
    try:
        low = price(tokens_in, tokens_out)
        high = price(tokens_in * MAX_ATTEMPTS, tokens_out * MAX_ATTEMPTS)
    except ValueError as error:
        return {"low": None, "high": None, "tutorials": count, "basis": f"{basis} {error}"}

    return {"low": round(low, 4), "high": round(high, 4), "tutorials": count, "basis": basis}


def preflight(
    stock: dict[str, Any], paper: dict[str, Any] | None = None, price: Callable[[int, int], float] | None = None
) -> dict[str, Any]:
    """Whether it is worth going on with a project's code, with the checks that say why.

    :param stock: What `take_stock` found.
    :param paper: What reading the paper found that bears on this, as its lists of `datasets`, `links`, `availability`,
        and `licenses`, or None if it has not been read.
    :param price: Prices the model's requests, as `estimate` takes it.
    :return: The `verdict` (go, ask, or no-go), a `summary` of it in words, the `checks` it is made from, and the
        `estimate`.
    """
    checks = [
        code_check(stock),
        license_check(stock, paper),
        tutorials_check(stock),
        tests_check(stock),
        environment_check(stock),
        gpu_check(stock),
        data_check(stock, paper),
        portability_check(stock),
        parts_check(stock),
        size_check(stock),
    ]
    kept = [item for item in checks if item is not None]
    blocks = [item for item in kept if item["status"] == "block"]
    warnings = [item for item in kept if item["status"] == "warn"]
    unknown = [item for item in kept if item["status"] == "unknown"]
    if blocks:
        verdict = "no-go"
        summary = "No-go: " + "; ".join(item["detail"] for item in blocks[:2])
    elif warnings:
        verdict = "ask"
        summary = (
            f"Ask first. {plural(len(warnings), 'thing')} to weigh: "
            + "; ".join(item["title"].lower() for item in warnings)
            + "."
        )
    else:
        verdict = "go"
        summary = "Go: nothing in the files stands in the way of making tools from this code."
    if unknown and verdict != "no-go":
        summary += (
            f" {plural(len(unknown), 'thing')} not known yet: {', '.join(item['title'].lower() for item in unknown)}."
        )

    return {"verdict": verdict, "summary": summary, "checks": kept, "estimate": estimate(stock, price)}
