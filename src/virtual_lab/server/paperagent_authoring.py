"""What a reader of an agent's paper would hit, and a package for the person who wrote it, made from what is kept.

Nothing is run and no model is asked: the checks that were made of the code when it was fetched, what building its
environment came to, how its tutorials ran, where its data is, and what trying the paper's numbers came to are put to
paperagents/authoring.py, and the imports of the code are looked at against the files that say what to install. It is
made when it is asked for, so it never says more than what is kept now: a step that has not been run is said not to
have been, and the call that runs it is given.
"""

import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from virtual_lab.paperagents import authoring, exporting
from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import stock as stocking
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_environment as kept_environment
from virtual_lab.server import paperagent_library as kept_library
from virtual_lab.server import paperagent_reference as kept_reference
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server.errors import ApiError
from virtual_lab.server.paperagents import PaperAgents

# The most that is read of one file of code, of one that says what to install, and of a package of the tools that is
# carried in the package: a file that is larger is left out, as it is not what a person wrote
MAX_CODE_BYTES = 1 << 20
MAX_NOTEBOOK_BYTES = 5 << 20
MAX_REQUIREMENT_BYTES = 200_000
MAX_CARRIED_PACKAGE_BYTES = 20 << 20
MAX_TOP = 5
MAX_PLACES = 6
# The kinds of file that say what to install, of those that are of Python
PYTHON_ENVIRONMENTS = ("pip", "conda")
# What the trying of the numbers says of a paper that was read and has nothing to try, which is not a step left undone
NOTHING_TO_TRY = ("no_claims", "no_numbers")


def read_text(path: Path, limit: int) -> str | None:
    """What a file says, or None if it is not a regular file of the project, or is larger than is read."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        with path.open("rb") as handle:
            content = handle.read(limit + 1)
    except OSError:
        return None

    return content.decode("utf-8", errors="replace") if len(content) <= limit else None


def is_inside(path: str) -> bool:
    """Whether a path that was kept is one that stays in the project's folder."""
    parts = Path(path).parts

    return bool(parts) and not Path(path).is_absolute() and ".." not in parts


def code_of(repo: Path, listed: list[tuple[str, int]]) -> Iterator[tuple[str, str]]:
    """The files of code of a project that a reader runs, one at a time, each by its place in the project."""
    for path, size in listed:
        if not authoring.is_read(path) or size > (MAX_NOTEBOOK_BYTES if path.endswith(".ipynb") else MAX_CODE_BYTES):
            continue
        text = read_text(repo / path, MAX_NOTEBOOK_BYTES)
        if text is not None:
            yield path, text


def missing_requirements(directory: Path, stock: dict[str, Any]) -> list[dict[str, Any]]:
    """What the code of a Python project imports that no file that says what to install names. None is found if there
    is no such file, as that is said of it already, and nothing of a project that is not Python."""
    repo = kept_repository.repo_path(directory)
    named = [
        item["path"] for item in stock["environment"] if item["kind"] in PYTHON_ENVIRONMENTS and is_inside(item["path"])
    ]
    texts = [text for path in named if (text := read_text(repo / path, MAX_REQUIREMENT_BYTES)) is not None]
    if not texts:
        return []
    listed, _ = stocking.walk(repo)

    return authoring.undeclared(
        authoring.imports_in(code_of(repo, listed)),
        authoring.local_names(path for path, _ in listed),
        authoring.declared_words(texts),
    )


def build_of(
    paperagents: PaperAgents, directory: Path, intake: dict[str, Any] | None, stock: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, str] | None, dict[str, Any]]:
    """What there is of the building of the environment: what was built, why a build that was made after it failed, why
    one is not made here, and whether Docker is there, which is only asked when nothing says.

    :return: The record of what was built, the failure, the reason that it is not built here, and Docker.
    """
    docker: dict[str, Any] = {"ready": True, "message": None}
    if intake is None or stock is None:
        return None, None, None, docker
    commit = intake["commit"]
    built = kept_environment.load(directory, commit)
    record = kept_environment.load_failure(directory, commit)
    failure = record["failure"] if record is not None else None
    if built is not None and record is not None and record["failed_at"] <= built["built_at"]:
        failure = None
    if built is not None and failure is None:
        return built, None, None, docker
    if failure is not None:
        return None, failure, None, docker
    try:
        building.plan(
            kept_repository.repo_path(directory),
            stock,
            building.check_python(None),
            building.check_system_packages(None),
        )
    except building.EnvironmentUnsupportedError as error:
        return None, None, {"kind": error.kind, "message": str(error)}, docker
    except ValueError:
        pass
    usable, problem = building.ready(paperagents.docker_command)

    return None, None, None, {"ready": usable, "message": problem}


def lock_of(directory: Path, built: dict[str, Any]) -> tuple[str, bytes]:
    """The exact versions that the environment was built to, as they are carried in the package, and what that file is
    called there."""
    text = exporting.lock_lines(kept_environment.read_lock(directory, built), built["recipe"]["kind"])

    return exporting.LOCKS[built["lock"]["name"]], text.encode("utf-8")


def environment_of(directory: Path, built: dict[str, Any] | None) -> dict[str, Any] | None:
    """What an environment that was built is, as the card says it, with the lock as it is carried."""
    if built is None:
        return None
    name, content = lock_of(directory, built)

    return {
        "kind": built["recipe"]["kind"],
        "python": built["python"],
        "base_image": built["recipe"]["base_image"],
        "lock": {
            "name": name,
            "packages": built["lock"]["packages"],
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        "pip_check": built["pip_check"]["ok"],
    }


def tutorials_of(reference: dict[str, Any] | None) -> dict[str, int] | None:
    if reference is None:
        return None
    ran = reference["tutorials"]
    ok = [each for each in ran if each["status"] == "ok"]

    return {
        "ran": len(ran),
        "ok": len(ok),
        "failed": len(ran) - len(ok),
        "unstable": sum(1 for each in ok if each["stable"] is False),
    }


def data_of(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """The datasets that the paper names with where each is, and the places that the paper and the code give for
    data."""
    urls = {candidate["key"]: candidate["url"] for candidate in data["candidates"]}
    datasets = [
        {
            "name": item["name"],
            "accession": item["accession"],
            "place": urls.get(item["candidate"]) if item["candidate"] is not None else None,
        }
        for item in data["datasets"]
    ]
    places = [
        {"label": candidate["label"], "url": candidate["url"]}
        for candidate in data["candidates"]
        if candidate["facts"] or candidate["in_code"]
    ]

    return datasets[: authoring.MAX_EACH], places[:MAX_PLACES]


def tried_of(reproduction: dict[str, Any]) -> dict[str, Any] | None:
    """What trying the paper's numbers came to, if it was of what is kept now."""
    if not reproduction["current"] or reproduction["kept"] is None:
        return None
    tried = [claim for claim in reproduction["claims"] if claim["status"] != "not_attempted"]

    return {
        "counts": reproduction["counts"],
        "rows": [
            {"value": claim["value"], "status": claim["status"], "quote": claim["quote"]}
            for claim in tried[: authoring.MAX_CLAIM_ROWS]
        ],
        "entries": reproduction["claims"],
    }


def gather(paperagents: PaperAgents, agent_id: str) -> dict[str, Any]:
    """Everything that is kept of an agent that bears on what a reader would hit, and what is made of it.

    :raises ApiError: If there is no agent with this id.
    """
    directory, agent = paperagents.lookup(agent_id)
    repository = paperagents.repository(agent_id)
    data = paperagents.data(agent_id)
    reproduction = paperagents.reproduction(agent_id)
    intake, stock = repository["intake"], repository["stock"]
    built, failure, unsupported, docker = build_of(paperagents, directory, intake, stock)
    # What is kept while the tutorials are being run is the run so far, which would be said to have stopped early
    running = paperagents.reference_job(agent_id) is not None
    reference = (
        kept_reference.load(directory, intake["commit"], built["image"]["id"])
        if built is not None and intake is not None and not running
        else None
    )
    claims = tried_of(reproduction)
    pieces = paperagents.library_pieces(directory, agent)
    entry = kept_library.entry_of(directory, agent_id, agent, *pieces) if pieces is not None else None
    found: list[dict[str, Any]] = []
    if intake is not None:
        found += authoring.check_findings(repository["preflight"]["checks"], stock)
        found += authoring.requirement_findings(missing_requirements(directory, stock))
    found += authoring.build_findings(built, failure, unsupported, docker, intake is not None)
    found += authoring.tutorial_findings(reference, built is not None, running)
    found += authoring.data_findings(data, data["read"])
    found += authoring.claim_findings(claims["entries"] if claims is not None else [])
    found = authoring.ordered(found)
    cannot_build = unsupported is not None
    nothing_to_try = (reproduction["problem"] or {}).get("code") in NOTHING_TO_TRY
    steps = {
        "read": data["read"],
        "code": intake is not None,
        "environment": built is not None or cannot_build,
        "tutorials": reference is not None or cannot_build or running,
        "claims": claims is not None or cannot_build or (data["read"] and nothing_to_try),
    }
    unchecked = authoring.not_checked(steps, agent_id)
    verdict, summary = authoring.verdict_of(found, intake is not None, len(unchecked))
    counts = {severity: sum(1 for item in found if item["severity"] == severity) for severity in authoring.SEVERITIES}
    datasets, places = data_of(data)
    carried = entry["export"] if entry is not None and entry["export"] is not None else None
    facts = {
        "title": agent["title"],
        "doi": agent["paper"].get("doi"),
        "url": agent["paper"].get("url"),
        "made_at": utc_timestamp(),
        "code": (
            {"url": intake["url"], "commit": intake["commit"], "ref": intake["ref"]} if intake is not None else None
        ),
        "license": exporting.license_of(stock["license"] if stock is not None else None),
        "environment": environment_of(directory, built),
        "tutorials": tutorials_of(reference),
        "tutorials_running": running,
        "claims": claims,
        "datasets": datasets,
        "places": places,
        "tools": [{"name": tool["name"], "tier": tool["tier"]} for tool in entry["tools"]] if entry is not None else [],
        "package": (
            {"file": carried["file"], "bytes": carried["bytes"], "sha256": carried["sha256"]}
            if carried is not None and carried["current"]
            else None
        ),
        "findings": counts,
        "top": [{"severity": item["severity"], "title": item["title"]} for item in found[:MAX_TOP]],
    }

    return {
        "directory": directory,
        "agent": agent,
        "built": built,
        "facts": facts,
        "findings": found,
        "counts": counts,
        "verdict": verdict,
        "summary": summary,
        "not_checked": unchecked,
        "steps": steps,
    }


def carried_files(gathered: dict[str, Any], with_tools: bool = True) -> list[tuple[str, bytes, bool]]:
    """The files of the package for the person who wrote the paper: each by its name, what is in it, and whether it is
    already compressed.

    :param with_tools: Whether the package of the tools is read and carried, when there is one of what is kept now that
        is not too large.
    """
    facts, directory, built = gathered["facts"], gathered["directory"], gathered["built"]
    record = {
        "verdict": gathered["verdict"],
        "summary": gathered["summary"],
        "made_at": facts["made_at"],
        "commit": facts["code"]["commit"] if facts["code"] is not None else None,
        "counts": gathered["counts"],
        "findings": gathered["findings"],
        "not_checked": gathered["not_checked"],
        "meaning": authoring.MEANING,
    }
    files: list[tuple[str, bytes, bool]] = [
        ("reproducibility_card.md", authoring.card_of(facts).encode("utf-8"), False),
        ("availability_statement.md", authoring.statement_of(facts).encode("utf-8"), False),
        ("findings.json", json.dumps(record, indent=2).encode("utf-8"), False),
    ]
    if built is not None:
        name, content = lock_of(directory, built)
        files.append((name, content, False))
    package = facts["package"]
    if with_tools and package is not None and package["bytes"] <= MAX_CARRIED_PACKAGE_BYTES:
        content = read_package(directory, package)
        if content is not None:
            files.append((f"mcp/{package['file']}", content, True))

    return files


def read_package(directory: Path, package: dict[str, Any]) -> bytes | None:
    """The package of the tools that was made, if the file is what the record says it is."""
    path = kept_library.export_file(directory)
    if path is None or path.name != package["file"]:
        return None
    try:
        content = path.read_bytes()
    except OSError:
        return None

    return content if len(content) == package["bytes"] else None


def zipped(stem: str, files: list[tuple[str, bytes, bool]]) -> bytes:
    """A ZIP of the files in a folder of this name, with the times and the permissions that every one has, so that the
    same files give the same bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content, compressed in files:
            info = zipfile.ZipInfo(f"{stem}/{name}", date_time=exporting.STAMP)
            info.compress_type = zipfile.ZIP_STORED if compressed else zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)

    return buffer.getvalue()


def view(paperagents: PaperAgents, agent_id: str) -> dict[str, Any]:
    """What a reader of an agent's paper would hit, what was not looked at, and what the package would hold.

    :raises ApiError: If there is no agent with this id.
    """
    gathered = gather(paperagents, agent_id)
    facts = gathered["facts"]
    files = [(name, len(content)) for name, content, _ in carried_files(gathered, with_tools=False)]
    tools = facts["package"]
    carries = tools is not None and tools["bytes"] <= MAX_CARRIED_PACKAGE_BYTES
    if carries:
        files.append((f"mcp/{tools['file']}", tools["bytes"]))
    if gathered["verdict"] == "not_checked":
        files, carries = [], False

    return {
        "id": agent_id,
        "title": facts["title"],
        "verdict": gathered["verdict"],
        "summary": gathered["summary"],
        "counts": gathered["counts"],
        "findings": gathered["findings"],
        "not_checked": gathered["not_checked"],
        "steps": gathered["steps"],
        "card": authoring.card_of(facts),
        "statement": authoring.statement_of(facts),
        "package": {
            "ready": bool(files),
            "files": [{"name": name, "bytes": size} for name, size in files],
            "carries_tools": carries,
        },
        "meaning": authoring.MEANING,
        "limits": {
            "most_files_read": authoring.MAX_FILES_READ,
            "most_carried_package_bytes": MAX_CARRIED_PACKAGE_BYTES,
        },
    }


def package(paperagents: PaperAgents, agent_id: str) -> tuple[str, bytes]:
    """The package for the person who wrote the paper: a reproducibility card, a statement of availability, what was
    found as a file, the exact versions of the environment, and the package of the tools if one was made of what is kept
    now.

    :return: What to call the file, and what is in it.
    :raises ApiError: If there is no agent with this id, or the code has not been fetched, so that there is nothing to
        say.
    """
    gathered = gather(paperagents, agent_id)
    if gathered["verdict"] == "not_checked":
        raise ApiError(409, "not_ready", gathered["summary"])
    facts = gathered["facts"]
    stem = f"{exporting.package_name(facts['title'], facts['code']['commit'])}-reproducibility"

    return f"{facts['title']} - reproducibility package", zipped(stem, carried_files(gathered))
