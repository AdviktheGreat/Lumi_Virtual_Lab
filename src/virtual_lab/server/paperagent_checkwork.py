"""The work of checking an agent's tools by what their tutorials did not give them: the job that makes each check and
keeps it as it is made.

This is what PaperAgents does with the pieces: the tools that are kept are called with inputs that no tutorial chose,
and the tests that the code came with are run, in the environment's image (paperagents/checking.py), and each check is
kept, bound to what it was made of (paperagent_checks.py). A tool's tier is worked out from what is kept, and not
here.
"""

import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from virtual_lab.paperagents import checking
from virtual_lab.paperagents import environment as building
from virtual_lab.paperagents import reference as referencing
from virtual_lab.paperagents.comparing import Tolerance
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server import paperagent_checks as kept_checks
from virtual_lab.server.jobs import Job


def limits_of() -> dict[str, int | str]:
    """What a person may allow, by default and at most, and what each run is kept to."""
    return {
        "default_minutes": checking.DEFAULT_MINUTES,
        "max_minutes": checking.MAX_MINUTES,
        "default_total_minutes": checking.DEFAULT_TOTAL_MINUTES,
        "max_total_minutes": checking.MAX_TOTAL_MINUTES,
        "default_repeats": checking.DEFAULT_REPEATS,
        "max_repeats": checking.MAX_REPEATS,
        "default_gigabytes": checking.DEFAULT_GIGABYTES,
        "max_gigabytes": checking.MAX_GIGABYTES,
        "memory": building.MEMORY,
        "cpus": building.CPUS,
        "pids": building.PIDS,
    }


def kinds_of(kinds: Any) -> tuple[str, ...]:
    """The kinds of check that were asked for, in the order that they are made, which is all of them if none were named.

    :raises ValueError: If it is not a list of kinds of check, each named once.
    """
    if kinds is None:
        return checking.KINDS
    if (
        not isinstance(kinds, (list, tuple))
        or not kinds
        or any(not isinstance(kind, str) or kind not in checking.KINDS for kind in kinds)
        or len(set(kinds)) != len(kinds)
    ):
        raise ValueError(f"The kinds of check are some of {', '.join(checking.KINDS)}, each named once")

    return tuple(kind for kind in checking.KINDS if kind in kinds)


def describe_check(name: str, kind: str, outcome: checking.Outcome) -> str:
    title = checking.KIND_INFO[kind]["title"].lower()

    return f"{name}, {title}: {outcome.status.replace('_', ' ')}. {outcome.summary}"[:600]


def run_kind(
    runner: checking.CheckRunner, tool: dict[str, Any], kind: str, repo: Path, seconds: float
) -> checking.Outcome:
    """Makes one kind of check of one tool.

    :raises StoppedError: If the job was stopped.
    :raises DockerUnavailableError: If Docker did not run a call.
    """
    if kind == checking.HELDOUT:
        tolerance = Tolerance(**tool["evidence"]["tolerance"])

        return checking.check_held_out(runner, tool, repo, seconds, tolerance)

    return checking.check_repo_tests(runner, tool, repo, seconds)


def check_all(
    job: Job,
    directory: Path,
    scratch_root: Path,
    agent_id: str,
    kept: dict[str, Any],
    tools: Sequence[dict[str, Any]],
    kinds: Sequence[str],
    limits: checking.CheckLimits,
    repo: Path,
    data: Path | None,
    docker_command: tuple[str, ...],
) -> tuple[str, dict[str, int]]:
    """Makes the checks one after another, keeping each as it is made, so that a job that is stopped keeps what it had
    made. A check that is made again takes the place of the one that was kept.

    :param kept: The account of the making of the tools, which says the commit, the image, and the reference run that
        the tools are of, and so what each check is bound to.
    :param tools: The tools to check, each as it is kept, with its wrapper's code.
    :param repo: The code that was fetched, which is read for what each function takes and never run.
    :param data: The folder of the data that the tutorials were given, if they were, which the calls are given too.
    :return: What it came to, in a sentence, and how many checks came to each status.
    :raises StoppedError: If the job was stopped.
    :raises DockerUnavailableError: If Docker did not run a call.
    """
    job.update("Checking the tools")
    # What an earlier check left of itself, which only a server that was stopped hard would
    referencing.remove_runs(agent_id, docker_command)
    counts = dict.fromkeys(checking.STATUSES, 0)
    work = [(tool, kind) for tool in tools for kind in kinds]
    began = time.monotonic()
    done = 0
    with tempfile.TemporaryDirectory(prefix="paperagent.", dir=scratch_root) as scratch:
        runner = checking.CheckRunner(
            building.tag_of(agent_id, kept["commit"]),
            limits.for_runs(),
            Path(scratch),
            data,
            docker_command,
            job.stop,
            agent_id,
        )
        for number, (tool, kind) in enumerate(work, 1):
            left = limits.total_minutes * 60 - (time.monotonic() - began)
            if left < referencing.LEAST_SECONDS:
                break
            job.update(f"Checking the tools: {tool['name']} ({number} of {len(work)})")
            started = time.monotonic()
            outcome = run_kind(runner, tool, kind, repo, min(limits.minutes * 60, left))
            kept_checks.keep(
                directory,
                kept_checks.record_of(
                    tool, kept, kind, outcome, utc_timestamp(), time.monotonic() - started, limits.to_dict()
                ),
            )
            counts[outcome.status] += 1
            done += 1
            job.log(describe_check(tool["name"], kind, outcome))
    left_over = len(work) - done
    said = f" {left_over} were not made, as the time was used." if left_over else ""

    return (
        f"Made {done} check{'s' if done != 1 else ''} of {len(tools)} tool{'s' if len(tools) != 1 else ''}: "
        f"{counts[checking.PASSED]} passed, {counts[checking.FAILED]} failed, {counts[checking.NOT_OBTAINED]} not "
        f"obtained.{said}",
        counts,
    )
