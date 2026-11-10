"""The work of making an agent's tools: which functions that its tutorials called can be tools, and the job that makes
them and keeps each as it is made.

This is what PaperAgents does with the pieces: the reference run that was kept says what the tutorials called, the
wrappers are made and called again in the environment's image (paperagents/toolmaking.py), and each tool that holds is
kept (paperagent_tools.py).
"""

import tempfile
from pathlib import Path
from typing import Any

from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import reference as referencing
from virtual_lab.paperagents import toolmaking as making
from virtual_lab.paperagents import wrappers
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_reference as kept_reference
from virtual_lab.server import paperagent_tools as kept_tools
from virtual_lab.server.jobs import Job

# Most of the reasons that a function is not made a tool that a message gives, and how long each may be
MOST_REASONS = 3
MAX_REASON_CHARS = 200


def gather_kept(directory: Path, reference: dict[str, Any], repo: Path, most: int) -> wrappers.Gathered:
    """Which functions that the tutorials of the reference run called can be tools, and which cannot, with why.

    :param reference: The account of the reference run that is kept, which is complete.
    :param repo: The code that was fetched, which is read for the parameters of each function and never run.
    :param most: How many tools are made at most.
    """
    details = []
    missing = []
    for summary in reference["tutorials"]:
        detail = kept_reference.load_detail(directory, reference, summary["id"])
        if detail is None:
            if summary["calls"]:
                missing.append({"tutorial": summary["id"], "reason": "What was kept of it cannot be read."})
            continue
        details.append(detail)
    gathered = wrappers.gather(details, repo, most)
    gathered.unused.extend(missing)

    return gathered


def reasons_of(gathered: wrappers.Gathered) -> str:
    """Why nothing can be made, in a sentence, from what was dropped."""
    found = [f"{item['name']}: {item['reason']}"[:MAX_REASON_CHARS] for item in gathered.dropped[:MOST_REASONS]] or [
        "None of the tutorials that ran to their end called a function of the code."
    ]

    return " ".join(found)


def preview_of(gathered: wrappers.Gathered) -> dict[str, Any]:
    """What would be made, and what would not and why, as a page shows it before anything is run."""
    return {
        "candidates": [candidate.to_dict() for candidate in gathered.candidates],
        "dropped": gathered.dropped,
        "unused": gathered.unused,
    }


def limits_of() -> dict[str, int | str]:
    """What a person may allow, by default and at most, and what each replay is kept to."""
    return {
        "default_minutes": making.DEFAULT_MINUTES,
        "max_minutes": making.MAX_MINUTES,
        "default_total_minutes": making.DEFAULT_TOTAL_MINUTES,
        "max_total_minutes": making.MAX_TOTAL_MINUTES,
        "default_tools": making.DEFAULT_TOOLS,
        "max_tools": making.MAX_TOOLS,
        "default_repeats": making.DEFAULT_REPEATS,
        "max_repeats": making.MAX_REPEATS,
        "default_repairs": making.DEFAULT_REPAIRS,
        "max_repairs": making.MAX_REPAIRS,
        "default_gigabytes": making.DEFAULT_GIGABYTES,
        "max_gigabytes": making.MAX_GIGABYTES,
        "memory": building.MEMORY,
        "cpus": building.CPUS,
        "pids": building.PIDS,
    }


def describe_made(candidate: wrappers.Candidate, made: making.Made) -> str:
    if made.record is not None:
        checked = made.record["evidence"]["checked"]
        calls = f"{checked} call{'s' if checked != 1 else ''}"
        return f"{candidate.name}: tier A. {calls} gave again what the tutorials got."
    assert made.dropped is not None
    details = f" {made.dropped['details'][0]}" if made.dropped["details"] else ""

    return f"{candidate.name}: dropped. {made.dropped['reason']}{details}"[:400]


def make_all(
    job: Job,
    directory: Path,
    scratch_root: Path,
    agent_id: str,
    commit: str,
    image_id: str,
    reference: dict[str, Any],
    limits: making.ToolLimits,
    gathered: wrappers.Gathered,
    data: Path | None,
    docker_command: tuple[str, ...],
) -> tuple[str, int]:
    """Makes the tools one after another, keeping each as it is made, so that a job that is stopped keeps what it had
    made.

    :param reference: The account of the reference run that the tools are made from.
    :param data: The folder of the data that the tutorials were given, if they were, which the calls are given too.
    :return: What it came to, in a sentence, and how many tools were made.
    :raises StoppedError: If the job was stopped.
    :raises DockerUnavailableError: If Docker did not run a call.
    """
    job.update("Making the tools")
    # What an earlier making left of itself, which only a server that was stopped hard would
    referencing.remove_runs(agent_id, docker_command)
    account: dict[str, Any] = {
        "schema": kept_tools.SCHEMA,
        "commit": commit,
        "image_id": image_id,
        "reference": {"started_at": reference["started_at"], "finished_at": reference["finished_at"]},
        "started_at": utc_timestamp(),
        "finished_at": None,
        "complete": False,
        "limits": limits.to_dict(),
        "data": data is not None,
        "tools": [],
        "dropped": list(gathered.dropped),
        "unused": list(gathered.unused),
    }
    kept_tools.begin(directory, account)

    def started(candidate: wrappers.Candidate, number: int, total: int) -> None:
        job.update(f"Making the tools: {candidate.name} ({number} of {total})")
        calls = len(candidate.cases)
        job.log(f"Calling {candidate.name} again, {calls} call{'s' if calls != 1 else ''} of the tutorials")

    def made(candidate: wrappers.Candidate, one: making.Made) -> None:
        nonlocal account
        if one.record is not None and one.source is not None:
            account = kept_tools.keep_tool(directory, account, one.record, one.source)
        elif one.dropped is not None:
            account = kept_tools.keep_dropped(directory, account, one.dropped)
        job.log(describe_made(candidate, one))

    with tempfile.TemporaryDirectory(prefix="paperagent.", dir=scratch_root) as scratch:
        runner = making.ToolRunner(
            building.tag_of(agent_id, commit), limits, Path(scratch), data, docker_command, job.stop, agent_id
        )
        not_tried = making.make_tools(runner, gathered, image_id, started, made)
    account = kept_tools.finish(directory, account, not_tried, utc_timestamp())
    count = len(account["tools"])
    dropped = len(account["dropped"])
    left = f" {len(not_tried)} were not tried, as the time was used." if not_tried else ""

    return (
        f"Made {count} tool{'s' if count != 1 else ''} of tier A. {dropped} "
        f"function{'s were' if dropped != 1 else ' was'} not made into a tool.{left}",
        count,
    )
