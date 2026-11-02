"""virtual-lab-bixbench: measures the lab on BixBench-Verified-50 from the command line.

    hf auth login                      # once, after accepting the dataset's terms on huggingface.co
    virtual-lab-bixbench fetch ~/bixbench
    virtual-lab-server --workspace ~/bixbench_workspace --token bench          # in another terminal
    virtual-lab-bixbench run ~/bixbench --workspace ~/bixbench_workspace --token bench \\
        --model openrouter/moonshotai/kimi-k3.1-pro --only bix-12-q2 --results ~/bixbench/smoke
    virtual-lab-bixbench run ~/bixbench --workspace ~/bixbench_workspace --token bench \\
        --model openrouter/moonshotai/kimi-k3.1-pro --results ~/bixbench/kimi
    virtual-lab-bixbench report ~/bixbench --results ~/bixbench/kimi
    virtual-lab-bixbench regrade ~/bixbench --results ~/bixbench/kimi --judge-model <model>

Questions are asked of a running server, in a conversation each, so the lead has what a conversation in the interface
has. Give the server a workspace of its own, or its conversations are mixed with yours. A run saves each question as it
is graded, so one that stops carries on where it stopped when the same command is run again.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from virtual_lab.bixbench import DATASET_REPO, BixBenchError, choose_questions, download_bixbench, load_questions
from virtual_lab.bixbench_run import (
    SUMMARY_FILE,
    LabClient,
    LabError,
    RunSettings,
    describe_run,
    format_summary,
    judge_for,
    load_records,
    regrade_bixbench,
    run_bixbench,
    summarize,
)

PROGRAM = "virtual-lab-bixbench"
DEFAULT_URL = "http://127.0.0.1:8765"
DEFAULT_WORKSPACE = Path.home() / "virtual_lab_workspace"
TOKEN_VARIABLE = "VIRTUAL_LAB_TOKEN"
INTERRUPTED = 130


def selection_parser() -> argparse.ArgumentParser:
    """The options that choose which questions, which most commands share."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("directory", type=Path, help="where the dataset is, or is to be fetched to")
    parser.add_argument(
        "--only", nargs="+", default=[], metavar="ID", help="ask only these questions, such as bix-12-q2"
    )
    parser.add_argument("--limit", type=int, help="ask only the first N of the questions chosen")

    return parser


def results_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--results", type=Path, help="where the run is saved (default: <directory>/results)")

    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROGRAM, description="Measures the lab on BixBench-Verified-50.")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", parents=[selection_parser()], help="fetch the questions and their data")
    fetch.add_argument("--hf-token", help="a Hugging Face token (default: the one hf auth login saved)")

    run = commands.add_parser(
        "run", parents=[selection_parser(), results_parser()], help="ask the questions of a running server"
    )
    run.add_argument("--url", default=DEFAULT_URL, help="where the server is (default: %(default)s)")
    run.add_argument(
        "--token", default=os.environ.get(TOKEN_VARIABLE), help=f"the server's token (default: ${TOKEN_VARIABLE})"
    )
    run.add_argument(
        "--workspace",
        type=Path,
        default=DEFAULT_WORKSPACE,
        help="the server's workspace, on this machine (default: %(default)s)",
    )
    run.add_argument("--model", required=True, help="the model the lead answers with")
    run.add_argument("--judge-model", help="the model that judges answers (default: the lead's)")
    run.add_argument(
        "--team",
        nargs="*",
        default=[],
        metavar="TITLE",
        help="scientists the lead may consult (default: it works alone)",
    )
    run.add_argument("--sandbox", default="bio", choices=("python", "base", "bio", "full"), help="(default: bio)")
    run.add_argument("--resources", default="retrieve", choices=("retrieve", "all", "none"))
    run.add_argument(
        "--max-cost", type=float, default=3.0, help="most USD one question may cost (default: %(default)s)"
    )
    run.add_argument("--max-total-cost", type=float, help="most USD the run may cost the lead before it stops")
    run.add_argument("--timeout", type=float, default=2400.0, help="seconds a question may take (default: %(default)s)")
    run.add_argument("--jobs", type=int, default=1, help="questions to ask at once (default: %(default)s)")
    run.add_argument("--retry-failed", action="store_true", help="ask again those that failed or timed out")

    commands.add_parser("report", parents=[selection_parser(), results_parser()], help="the score of a run so far")

    regrade = commands.add_parser(
        "regrade", parents=[selection_parser(), results_parser()], help="grade the saved answers again, asking nothing"
    )
    regrade.add_argument("--judge-model", required=True, help="the model that judges answers")

    return parser


def chat_request(arguments: argparse.Namespace) -> dict[str, Any]:
    """What each question's conversation is made with: the lead's model, its team, and code in Docker with no keys of
    the user's passed in. Everything else is the server's settings."""
    return {
        "model": arguments.model,
        "team": list(arguments.team),
        "code": {
            "where": "docker",
            "sandbox": arguments.sandbox,
            "network": True,
            "resources": arguments.resources,
            "forward_env": [],
        },
        "max_cost": arguments.max_cost,
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    directory: Path = arguments.directory
    try:
        if arguments.command == "fetch":
            questions = download_bixbench(directory, arguments.hf_token, arguments.only, arguments.limit)
            print(f"Fetched {len(questions)} questions and the data they need into {directory}")
            return 0

        questions = choose_questions(load_questions(directory), arguments.only, arguments.limit)
        results = arguments.results or directory / "results"
        if arguments.command == "report":
            summary = summarize(questions, load_records(results, questions))
            print(format_summary(summary))
            return 0
        if arguments.command == "regrade":
            regrade_bixbench(questions, results, judge_for(arguments.judge_model))
            return 0

        if not arguments.token:
            print(f"The server's token is needed: pass --token or set ${TOKEN_VARIABLE}", file=sys.stderr)
            return 2
        settings = RunSettings(chat=chat_request(arguments), timeout=arguments.timeout)
        judge_model = arguments.judge_model or arguments.model
        summary = run_bixbench(
            questions,
            directory,
            results,
            arguments.workspace,
            LabClient(arguments.url, arguments.token),
            settings,
            judge_for(judge_model),
            describe_run(settings, judge_model, DATASET_REPO),
            jobs=arguments.jobs,
            retry_failed=arguments.retry_failed,
            max_total_cost=arguments.max_total_cost,
        )
        print()
        print(format_summary(summary))
        print(f"Saved in {results / SUMMARY_FILE}")
    except (BixBenchError, LabError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Run the same command again to carry on.", file=sys.stderr)
        return INTERRUPTED

    return 0


if __name__ == "__main__":
    sys.exit(main())
