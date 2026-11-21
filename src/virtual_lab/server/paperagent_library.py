"""The lab's library of what PaperAgents made, and exporting an agent's tools as a package.

The library says, of each agent that has tools: which version of the authors' code it is (the commit), what environment
it is pinned to (the image, the lock, and a hash of the lock), each tool with the hash of its wrapper and its tier,
what the code's license is, and whether a package has been made of it and still is of what is kept.

A package (paperagents/exporting.py) is made of an agent's tools by a job, and is kept in the agent's folder only if it
passed a check made in a clean container: it is unpacked into a folder of its own, and run, with no network and none of
this machine but that folder, in the image that its tools were made in, by the package's own server asking itself for
the calls that were recorded of each tool. A package that was not checked, or did not give what its tutorials got, is
not kept, and says why. What the check says is what the package says of itself, made in a container that has nothing
else of this lab in it.

A package is kept with the record of how it was checked and of what it was made of (state), so that it is told to be
stale once the tools, their tiers, the commit, or the image are not what it was made of. Taking the tools or the
environment away takes it too.
"""

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NamedTuple
from uuid import uuid4

from virtual_lab.constants import SANDBOX_WORK_DIR
from virtual_lab.environment import StoppedError
from virtual_lab.execution import DockerUnavailableError
from virtual_lab.paperagents import checking, exporting
from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import reference as referencing
from virtual_lab.paperagents.stock import matches
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_checks as kept_checks
from virtual_lab.server import paperagent_environment as kept_environment
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server import paperagent_tools as kept_tools
from virtual_lab.server.jobs import Job
from virtual_lab.server.workspace import read_json
from virtual_lab.utils import write_atomically

EXPORTS_DIR = kept_tools.EXPORTS_DIR
EXPORT_FILE = "export.json"
SCHEMA = 1

# Where the unpacked package is in the container that checks it, and what the check writes of itself
PACKAGE_AT = "/opt/lumi-package"
REPORT_FILE = "report.json"
CALLS_FOLDER = "calls"
# How long the check may take in all, and the most that its report may be
CHECK_MINUTES = 20
MAX_REPORT_BYTES = 1 << 20
MAX_REPORT_TEXT = 300
GIGABYTES = 2
# How many of each tool's recorded calls the package's check is asked to make
MAX_CASES = 3

NUMBER = (int, float)
CASE = {"case": int, "status": str, "differences": [str], "message": (str, None), "seconds": NUMBER}
REPORT = {
    "schema": int,
    "ok": bool,
    "python": str,
    "name": str,
    "version": str,
    "problems": [str],
    "tools": [{"name": str, "cases": [CASE]}],
}
EXPORT = {
    "schema": int,
    "name": str,
    "file": str,
    "made_at": str,
    "bytes": int,
    "sha256": str,
    "state": str,
    "commit": str,
    "accepted_license": bool,
    "license": {"flag": (str, None), "name": (str, None), "kind": (str, None)},
    "tools": [{"name": str, "tier": str, "wrapper_sha256": str}],
    "repo": {"files": int, "bytes": int, "sha256": str},
    "tested": {
        "ok": bool,
        "python": str,
        "image_id": str,
        "at": str,
        "seconds": NUMBER,
        "calls": int,
        "tools": [{"name": str, "cases": [{"case": int, "status": str, "seconds": NUMBER}]}],
    },
}


class ExportError(RuntimeError):
    """Raised when a package cannot be made or did not pass its check, with why."""


def exports_path(directory: Path) -> Path:
    return directory / EXPORTS_DIR


def lock_sha256(directory: Path, built: dict[str, Any]) -> str:
    """A hash of what the environment was built to, which is what the pinned environment is told by."""
    path = kept_environment.env_path(directory) / built["lock"]["name"]
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def tools_now(directory: Path, kept: dict[str, Any]) -> list[dict[str, Any]]:
    """Each tool of an agent as it is kept, with its wrapper's code, and under `now` the tier that its checks come to
    and which kinds passed, which is what a conversation is given of it."""
    found = []
    for summary in kept["tools"]:
        tool = kept_tools.load_tool(directory, summary["name"])
        if tool is None:
            continue
        shown = kept_checks.with_tier(directory, tool, kept)
        found.append({**tool, "now": {"tier": shown["tier"], "passed": shown["passed"]}})

    return found


def state_of(
    commit: str,
    image_id: str,
    tools: Sequence[dict[str, Any]],
    flag: str | None,
    lock: str = "",
    data: bool = False,
) -> str:
    """What a package is made of, as a hash: so that one is stale when the commit, the image, the lock, a wrapper, the
    calls that it is held to, a tier, whether the tutorials were given data, or what is said of the license is not what
    it was made of."""
    parts = [
        commit,
        image_id,
        flag,
        lock,
        data,
        sorted(
            [
                tool["name"],
                tool["wrapper_sha256"],
                tool["now"]["tier"],
                sorted(tool["now"]["passed"]),
                hashlib.sha256(
                    json.dumps([tool["evidence"]["cases"], tool["evidence"]["tolerance"]], sort_keys=True).encode()
                ).hexdigest(),
            ]
            for tool in tools
        ),
    ]

    return hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()


def state_for(
    directory: Path,
    intake: dict[str, Any],
    built: dict[str, Any],
    kept: dict[str, Any],
    tools: Sequence[dict[str, Any]],
    flag: str | None,
) -> str:
    """What a package of an agent's tools would be made of now, as state_of hashes it."""
    return state_of(
        intake["commit"], built["image"]["id"], tools, flag, lock_sha256(directory, built), bool(kept["data"])
    )


def stored_export(directory: Path) -> dict[str, Any] | None:
    """The record of the package that is kept, if there is one that is as it was written and whose file is there and is
    what it was, which is a regular file of the size and the hash that the record says."""
    record = read_json(exports_path(directory) / EXPORT_FILE)
    if (
        not matches(EXPORT, record)
        or record["schema"] != SCHEMA
        or "/" in record["file"]
        or record["file"].startswith(".")
    ):
        return None
    path = exports_path(directory) / record["file"]
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size != record["bytes"]:
            return None
    except OSError:
        return None

    return record


def export_file(directory: Path) -> Path | None:
    """The file of the package that is kept, if there is one."""
    record = stored_export(directory)

    return exports_path(directory) / record["file"] if record is not None else None


def export_view(record: dict[str, Any] | None, state: str) -> dict[str, Any] | None:
    """What of a package a page is told: when it was made, how big it is, how it was checked, and whether it is of what
    is kept now."""
    if record is None:
        return None

    return {
        "name": record["name"],
        "file": record["file"],
        "made_at": record["made_at"],
        "bytes": record["bytes"],
        "sha256": record["sha256"],
        "commit": record["commit"],
        "current": record["state"] == state,
        "accepted_license": record["accepted_license"],
        "license": record["license"],
        "tools": record["tools"],
        "repo": record["repo"],
        "tested": record["tested"],
    }


def entry_of(
    directory: Path,
    agent_id: str,
    agent: dict[str, Any],
    intake: dict[str, Any],
    built: dict[str, Any],
    kept: dict[str, Any],
) -> dict[str, Any]:
    """One agent that has tools, as the library lists it.

    :param intake: What was found of the code when it was fetched.
    :param built: The record of the environment that was built.
    :param kept: The account of the tools that were made, which is complete.
    """
    tools = tools_now(directory, kept)
    found = exporting.license_of(intake["stock"].get("license"))
    state = state_for(directory, intake, built, kept, tools, found["flag"])
    tiers = [tool["now"]["tier"] for tool in tools]

    return {
        "id": agent_id,
        "title": agent["title"],
        "given": agent.get("given") is True,
        "tier": checking.TIER_B if checking.TIER_B in tiers else (tiers[0] if tiers else None),
        "version": {
            "commit": intake["commit"],
            "short": intake["commit"][:7],
            "ref": intake["ref"],
            "url": intake["url"],
            "fetched_at": intake["cloned_at"],
        },
        "environment": {
            "kind": built["recipe"]["kind"],
            "python": built["python"],
            "base_image": built["recipe"]["base_image"],
            "image": built["image"],
            "built_at": built["built_at"],
            "lock": {
                "name": built["lock"]["name"],
                "packages": built["lock"]["packages"],
                "sha256": lock_sha256(directory, built),
            },
            "pip_check": built["pip_check"]["ok"],
        },
        "license": found,
        "tools": [
            {
                "name": tool["name"],
                "function": f"{tool['repo']['module']}.{tool['repo']['function']}",
                "tier": tool["now"]["tier"],
                "made_as": tool["tier"],
                "passed": tool["now"]["passed"],
                "wrapper_sha256": tool["wrapper_sha256"],
                "calls": tool["evidence"]["checked"],
            }
            for tool in tools
        ],
        "dropped": len(kept["dropped"]),
        "export": export_view(stored_export(directory), state),
        "state": state,
    }


class PackageRunner(referencing.Runner):
    """What runs a package's own check in a container made from the image that its tools were made in: with no network,
    a root that cannot be written to, and none of this machine but the unpacked package, which is read only, and a
    folder to write in. The data that the tutorials were given is mounted, as it was for the tools.

    :param seconds: How long the check may take in all, which it is told so that each call is given its part.
    """

    def __init__(self, *arguments: Any, seconds: int = CHECK_MINUTES * 60, **options: Any) -> None:
        super().__init__(*arguments, **options)
        self.seconds = seconds

    def argv(self, item: referencing.Item) -> list[str]:
        return [
            "python",
            f"{PACKAGE_AT}/{exporting.SERVER_FILE}",
            "check",
            "--report",
            f"{SANDBOX_WORK_DIR}/{REPORT_FILE}",
            "--work",
            f"{SANDBOX_WORK_DIR}/{CALLS_FOLDER}",
            "--cases",
            str(MAX_CASES),
            "--seconds",
            str(self.seconds),
        ]

    def check(self) -> tuple[dict[str, Any] | None, str, int | None, list[str]]:
        """Runs the package's check in a container, and gives what it said of itself, if it said anything that is a
        report, how the container ended, its exit code, and the end of what it printed.

        :raises StoppedError: If whoever started it asked to stop it.
        :raises DockerUnavailableError: If Docker did not run it, which is not a failing of the package.
        """
        folder = self.scratch / f"check-{uuid4().hex[:12]}"
        folder.mkdir()
        (folder / CALLS_FOLDER).mkdir()
        try:
            ended, code, text = self.execute(folder, referencing.Item("package", REPORT_FILE, "check"), self.seconds)
            if ended == "stopped":
                raise StoppedError("Stopped.")
            report = read_report(folder / REPORT_FILE)
            if report is None and ended == "done" and code == referencing.DOCKER_FAILED:
                said = " ".join(referencing.lines_of(text)[-3:]) or "it gave no reason"
                raise DockerUnavailableError(f"Docker did not run the package: {said}")
        finally:
            referencing.remove_tree(folder)

        return report, ended, code, referencing.lines_of(text)


def read_report(path: Path) -> dict[str, Any] | None:
    """What a package's check wrote of itself, if it is a report. It is written by a process that ran the code of a
    paper, and so is not trusted to be anything."""
    try:
        status = path.lstat()
        if path.is_symlink() or not path.is_file() or status.st_size > MAX_REPORT_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None

    return value if matches(REPORT, value) and value["schema"] == 1 else None


def not_of_the_package(report: dict[str, Any], manifest: dict[str, Any]) -> str | None:
    """Why a report is not of the package that was checked, if it is not: it is of another package, or it does not
    report on the tools that the package holds, each with the recorded calls it holds. The report is written by a
    process that ran the paper's code, so that what it says of what it checked is held to what the package holds."""
    if report["name"] != manifest["name"] or report["version"] != manifest["version"]:
        return "Its check reported on another package than the one that was made."
    asked = {tool["name"]: min(len(tool["examples"]), MAX_CASES) for tool in manifest["tools"]}
    said = {tool["name"]: [case["case"] for case in tool["cases"]] for tool in report["tools"]}
    if len(report["tools"]) != len(said) or said.keys() != asked.keys():
        return "Its check did not report on the tools that the package holds."
    if any(cases != list(range(asked[name])) for name, cases in said.items()):
        return "Its check did not make the recorded calls of each tool that the package holds."

    return None


def why_not(
    report: dict[str, Any] | None,
    ended: str,
    code: int | None,
    lines: Sequence[str],
    manifest: dict[str, Any] | None = None,
) -> str | None:
    """Why a package did not pass its check, in a sentence, or None if it did.

    :param manifest: What the package holds, which the report is held to if it is given.
    """
    if ended == "timed_out":
        return f"Its check was stopped after {CHECK_MINUTES} minutes, which is what it was given."
    if ended == "too_big":
        return f"Its check was stopped for writing more than {GIGABYTES} gigabytes."
    if report is None:
        said = " ".join(lines[-3:]) or "it gave no reason"
        return f"Its check ended with code {code}, without a report. {said}"[: MAX_REPORT_TEXT * 2]
    reasons = [*report["problems"]]
    for tool in report["tools"]:
        for case in tool["cases"]:
            if case["status"] != "match":
                said = "; ".join(case["differences"]) or case["message"] or case["status"]
                reasons.append(f"{tool['name']}, call {case['case'] + 1}: {said}"[:MAX_REPORT_TEXT])
    if not reasons and manifest is not None and (other := not_of_the_package(report, manifest)) is not None:
        reasons.append(other)
    if not report["ok"] and not reasons:
        reasons.append("Its check did not say that it passed, and did not say why.")

    return " ".join(reasons[:3]) if reasons else None


def forget(directory: Path) -> None:
    """Removes the package that is kept, with its record. The record goes first, so that it never names a file that is
    gone."""
    folder = exports_path(directory)
    (folder / EXPORT_FILE).unlink(missing_ok=True)
    shutil.rmtree(folder, ignore_errors=True)


class Checked(NamedTuple):
    """A package that was made and run in a clean container, as it was, for as long as its folder is there.

    :param part: The package's file.
    :param manifest: What the package holds.
    :param size: The bytes of the file.
    :param report: What its own check wrote of itself, if it wrote a report.
    :param ended: How the container ended: done, timed_out, too_big, or stopped.
    :param code: The container's exit code.
    :param lines: The end of what it printed.
    :param began: When the check began.
    :param reason: Why it did not pass, or None if it did.
    :param state: What the package is made of, as state_of says.
    :param found: What is said of the code's license.
    """

    part: Path
    manifest: dict[str, Any]
    size: int
    report: dict[str, Any] | None
    ended: str
    code: int | None
    lines: list[str]
    began: str
    reason: str | None
    state: str
    found: dict[str, Any]


@contextmanager
def checked_package(
    job: Job,
    directory: Path,
    scratch_root: Path,
    agent_id: str,
    agent: dict[str, Any],
    intake: dict[str, Any],
    built: dict[str, Any],
    kept: dict[str, Any],
    data: Path | None,
    docker_command: Sequence[str],
) -> Iterator[Checked]:
    """Makes the package of an agent's tools and runs its own check in a clean container, in a folder of its own that is
    taken away after. What the check came to is given, whether or not it passed.

    :param data: The folder of the data that the tutorials were given, if they were, which the check is given too.
    :raises ExportError: If the package cannot be made or cannot be unpacked.
    :raises StoppedError: If the job was stopped.
    :raises DockerUnavailableError: If Docker did not run the check.
    """
    job.update("Making the package")
    tools = tools_now(directory, kept)
    if not tools or len(tools) != len(kept["tools"]):
        raise ExportError("A tool is not as it was made, so a package cannot be made of them. Make the tools again.")
    found = exporting.license_of(intake["stock"].get("license"))
    state = state_for(directory, intake, built, kept, tools, found["flag"])
    source = exporting.Source(
        agent_id=agent_id,
        title=agent["title"],
        paper={key: value for key, value in agent["paper"].items() if key in ("kind", "doi", "url")},
        intake=intake,
        environment=built,
        lock=kept_environment.read_lock(directory, built),
        tools=tools,
        repo=kept_repository.repo_path(directory),
        data=data is not None,
        made_at=utc_timestamp(),
    )
    referencing.remove_runs(agent_id, tuple(docker_command))
    with tempfile.TemporaryDirectory(prefix="paperagent.", dir=scratch_root) as scratch:
        part = Path(scratch) / "package.zip"
        try:
            manifest = exporting.build_package(source, part)
        except exporting.PackageError as error:
            raise ExportError(str(error)) from None
        size = part.stat().st_size
        job.log(
            f"Made {manifest['name']}: {len(manifest['tools'])} tool{'s' if len(manifest['tools']) != 1 else ''}, "
            f"{manifest['repo']['files']} files of the code, {size} bytes"
        )
        if job.stop.is_set():
            raise StoppedError("Stopped.")
        job.update("Checking it in a clean container")
        try:
            package = exporting.unpack(part, Path(scratch) / "unpacked")
        except (exporting.PackageError, OSError) as error:
            raise ExportError(f"The package cannot be unpacked: {error}") from None
        runner = PackageRunner(
            building.tag_of(agent_id, intake["commit"]),
            referencing.Limits(gigabytes=GIGABYTES),
            Path(scratch),
            data,
            tuple(docker_command),
            job.stop,
            agent_id,
            mounts=((package, PACKAGE_AT),),
        )
        began = utc_timestamp()
        report, ended, code, lines = runner.check()
        reason = why_not(report, ended, code, lines, manifest)
        yield Checked(part, manifest, size, report, ended, code, lines, began, reason, state, found)


def make_package(
    job: Job,
    directory: Path,
    scratch_root: Path,
    agent_id: str,
    agent: dict[str, Any],
    intake: dict[str, Any],
    built: dict[str, Any],
    kept: dict[str, Any],
    data: Path | None,
    docker_command: Sequence[str],
    accepted: bool,
) -> str:
    """Makes the package of an agent's tools, checks it in a clean container, and keeps it if it passed.

    :param data: The folder of the data that the tutorials were given, if they were, which the check is given too.
    :param accepted: Whether the person said to go on though the code's license is flagged.
    :return: What it came to, in a sentence.
    :raises ExportError: If the package cannot be made or did not pass.
    :raises StoppedError: If the job was stopped.
    :raises DockerUnavailableError: If Docker did not run the check.
    """
    with checked_package(
        job, directory, scratch_root, agent_id, agent, intake, built, kept, data, docker_command
    ) as checked:
        part, manifest, size, report, state, found = (
            checked.part,
            checked.manifest,
            checked.size,
            checked.report,
            checked.state,
            checked.found,
        )
        if checked.reason is not None or report is None:
            raise ExportError(
                f"The package was not kept, as it did not pass its check in a clean container. {checked.reason}"
            )
        began = checked.began
        calls = sum(len(tool["cases"]) for tool in report["tools"])
        job.log(f"Its check passed: {calls} recorded call{'s' if calls != 1 else ''} gave what the tutorials got")
        folder = exports_path(directory)
        forget(directory)
        folder.mkdir(exist_ok=True)
        file = f"{manifest['name']}.zip"
        shutil.copyfile(part, folder / f"{file}.part")
        os.replace(folder / f"{file}.part", folder / file)
        record = {
            "schema": SCHEMA,
            "name": manifest["name"],
            "file": file,
            "made_at": manifest["made_at"],
            "bytes": size,
            "sha256": hashlib.sha256((folder / file).read_bytes()).hexdigest(),
            "state": state,
            "commit": intake["commit"],
            "accepted_license": accepted,
            "license": {key: found[key] for key in ("flag", "name", "kind")},
            "tools": [
                {"name": tool["name"], "tier": tool["tier"], "wrapper_sha256": tool["wrapper_sha256"]}
                for tool in manifest["tools"]
            ],
            "repo": {key: manifest["repo"][key] for key in ("files", "bytes", "sha256")},
            "tested": {
                "ok": True,
                "python": report["python"],
                "image_id": built["image"]["id"],
                "at": began,
                "seconds": round(sum(case["seconds"] for tool in report["tools"] for case in tool["cases"]), 1),
                "calls": calls,
                "tools": [
                    {
                        "name": tool["name"],
                        "cases": [
                            {"case": case["case"], "status": case["status"], "seconds": case["seconds"]}
                            for case in tool["cases"]
                        ],
                    }
                    for tool in report["tools"]
                ],
            },
        }
        write_atomically(folder / EXPORT_FILE, json.dumps(record, indent=2).encode("utf-8"))

    return (
        f"Made {file}, {size} bytes, and checked it in a clean container: {calls} recorded "
        f"call{'s' if calls != 1 else ''} of {len(report['tools'])} tool{'s' if len(report['tools']) != 1 else ''} "
        "gave what the tutorials got."
    )
