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
from virtual_lab.constants import CEILING_CHAT_DELEGATION_ROUNDS, MAX_CHAT_DELEGATION_ROUNDS
from virtual_lab.directives import LabRequest
from virtual_lab.environment import SANDBOX_TARGETS
from virtual_lab.prompts import SCIENTIFIC_CRITIC
from virtual_lab.schemas import normalize_title

PROGRAM = "virtual-lab-bixbench"
DEFAULT_URL = "http://127.0.0.1:8765"
# The group the server's settings put the tools that search papers in. The studies the questions are from are papers,
# and a lead that can find them is not answering from the data
LITERATURE_GROUP = "Literature"
# The group of the tools that search the web and read its pages, which can find a paper, and an analysis done as the
# dataset's authors did it, as the literature tools can
WEB_GROUP = "Web"
TOKEN_VARIABLE = "VIRTUAL_LAB_TOKEN"
INTERRUPTED = 130
# A question takes the lead from the data to a number, a step of code at a time, and the conversation's own limit of
# 20 is too few for that. What it may spend is held by --max-cost.
DEFAULT_MAX_TOOL_CALLS = 80
DEFAULT_LAB_ROUNDS = 1
CRITIC = normalize_title(SCIENTIFIC_CRITIC.title)


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
        required=True,
        help="the server's workspace, on this machine, which should be one made for the run",
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
    run.add_argument(
        "--sandbox", default="bio-r", choices=("python", *SANDBOX_TARGETS), help="must be built (default: bio-r)"
    )
    run.add_argument(
        "--no-result-check",
        action="store_true",
        help="do not have the lead check its result before it answers, as a conversation has it do unless it is made "
        "not to (it is asked once, after it writes an answer from code it ran)",
    )
    run.add_argument(
        "--lab",
        choices=("team", "individual"),
        help="give every question with /lab, so that the lead has the scientists --team names work on it: as a team "
        "session it leads (team), or one scientist with the Scientific Critic reviewing (individual, which needs "
        "exactly one besides the Critic, who is added to the team). By default the lead decides whether to call on "
        "them",
    )
    run.add_argument(
        "--lab-rounds",
        type=int,
        default=DEFAULT_LAB_ROUNDS,
        help="rounds of discussion, or of review, for --lab (default: %(default)s)",
    )
    run.add_argument("--resources", default="retrieve", choices=("retrieve", "all", "none"))
    run.add_argument(
        "--data-lake",
        type=Path,
        metavar="DIRECTORY",
        help="the directory of Biomni's data lake, which code can read, on the machine the server is on (default: "
        "the server's own, which is in its workspace unless its settings say where, and is empty in a workspace made "
        "for a run)",
    )
    run.add_argument(
        "--max-cost", type=float, default=3.0, help="most USD one question may cost (default: %(default)s)"
    )
    run.add_argument(
        "--max-tool-calls",
        type=int,
        default=DEFAULT_MAX_TOOL_CALLS,
        help="most tool calls and runs of code the lead makes for a question (default: %(default)s)",
    )
    run.add_argument("--max-total-cost", type=float, help="most USD the run may cost the lead before it stops")
    run.add_argument("--timeout", type=float, default=2400.0, help="seconds a question may take (default: %(default)s)")
    run.add_argument("--jobs", type=int, default=1, help="questions to ask at once (default: %(default)s)")
    run.add_argument("--retry-failed", action="store_true", help="ask again those that failed or timed out")
    run.add_argument(
        "--literature",
        action="store_true",
        help="let the lead search papers (by default it cannot, nor use the MCP servers, data, and software the "
        "server's workspace has)",
    )
    run.add_argument(
        "--web", action="store_true", help="let the lead search the web and read pages (by default it cannot)"
    )

    commands.add_parser("report", parents=[selection_parser(), results_parser()], help="the score of a run so far")

    regrade = commands.add_parser(
        "regrade", parents=[selection_parser(), results_parser()], help="grade the saved answers again, asking nothing"
    )
    regrade.add_argument("--judge-model", required=True, help="the model that judges answers")

    return parser


def allowed(arguments: argparse.Namespace, group: str | None) -> bool:
    """Whether the lead is given a tool of this group, which it is unless it is one of those a run is asked to hold
    back."""
    if group == LITERATURE_GROUP:
        return bool(arguments.literature)
    if group == WEB_GROUP:
        return bool(arguments.web)

    return True


def chat_request(arguments: argparse.Namespace, tools: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """What each question's conversation is made with: the lead's model, its team, and code in Docker with no keys of
    the user's passed in. It is given the server's tools except those that search papers, unless --literature, and those
    that search the web, unless --web, and none of the MCP servers, data, software, or functions the workspace has, so
    that the questions are answered from the data they come with. Everything else is the server's settings.

    :param tools: The server's tools, as it describes them.
    """
    code: dict[str, Any] = {
        "where": "docker",
        "sandbox": arguments.sandbox,
        "network": True,
        "resources": arguments.resources,
        "forward_env": [],
    }
    if arguments.data_lake is not None:
        code["data_lake"] = str(arguments.data_lake.expanduser().resolve())

    request: dict[str, Any] = {
        "model": arguments.model,
        "team": team_titles(arguments),
        "code": code,
        "tools": [tool["name"] for tool in tools if allowed(arguments, tool.get("group"))],
        "mcp": [],
        "data": [],
        "software": [],
        "functions": [],
        "max_cost": arguments.max_cost,
        "max_tool_iterations": arguments.max_tool_calls,
        # Always said, so that results of a server that has the check are not counted with those of one that does not
        "check_results": not arguments.no_result_check,
    }
    # A conversation allows a session a few rounds unless it is told it may have more
    if arguments.lab is not None and arguments.lab_rounds > MAX_CHAT_DELEGATION_ROUNDS:
        request["max_rounds"] = arguments.lab_rounds

    return request


def team_titles(arguments: argparse.Namespace) -> list[str]:
    """The scientists each conversation's team is made of: those --team names, and with --lab individual the Scientific
    Critic too, who reviews and who the server requires to be on the team for that."""
    team = list(arguments.team)
    if arguments.lab == "individual" and not any(normalize_title(title) == CRITIC for title in team):
        team.append(SCIENTIFIC_CRITIC.title)

    return team


def lab_request(arguments: argparse.Namespace) -> dict[str, Any] | None:
    """Who works on each question with /lab, and how, or None if the questions are not given with it.

    :raises BixBenchError: If it is one the server would refuse, which it would for every question once the run had
        begun: no scientists named with --team, --lab individual without exactly one besides the Scientific Critic, who
        reviews, or rounds outside what a conversation can be asked for.
    """
    if arguments.lab is None:
        return None
    named = list(arguments.team)
    if arguments.lab == "individual":
        named = [title for title in named if normalize_title(title) != CRITIC]
    # The server takes a title written two ways as one, and one named twice as one scientist
    titles: dict[str, str] = {}
    for title in named:
        if title.strip():
            titles.setdefault(normalize_title(title), " ".join(title.split()))
    if not titles:
        besides = " besides the Scientific Critic" if arguments.lab == "individual" else ""
        raise BixBenchError(f"--lab needs the scientists to work on each question{besides}, named with --team")
    if arguments.lab == "individual" and len(titles) != 1:
        raise BixBenchError(
            f"--lab individual is one scientist besides the Scientific Critic, who reviews, but --team names "
            f"{len(titles)}"
        )
    if not 0 <= arguments.lab_rounds <= CEILING_CHAT_DELEGATION_ROUNDS:
        raise BixBenchError(f"--lab-rounds is a whole number from 0 to {CEILING_CHAT_DELEGATION_ROUNDS}")
    try:
        lab = LabRequest.from_data(
            {"mode": arguments.lab, "members": list(titles.values()), "rounds": arguments.lab_rounds}
        )
    except ValueError as error:
        raise BixBenchError(f"--lab cannot be given: {error}") from error

    return {"mode": lab.mode, "members": list(lab.members), "rounds": lab.rounds}


def data_lake_warning(arguments: argparse.Namespace, client: LabClient) -> str | None:
    """What to tell the person starting a run when the lead will have no data lake to read, which is when the
    directory it is told to use has nothing in it, or when it is left to the server and the server's has none of its
    files. A server that does not say what its data lake holds is not told of, since this is only advice.

    :raises BixBenchError: If the directory it is told to use is not one, or cannot be read.
    """
    if arguments.resources == "none":
        return None
    if arguments.data_lake is not None:
        directory = arguments.data_lake.expanduser()
        if not directory.is_dir():
            raise BixBenchError(f"--data-lake {directory} is not a directory")
        try:
            empty = not any(not entry.name.startswith(".") for entry in directory.iterdir())
        except OSError as error:
            raise BixBenchError(f"--data-lake {directory} cannot be read: {error}") from error
        if empty:
            return f"The data lake {directory} is empty, so the lead has no data lake to read."
        return None
    try:
        lake = client.data_lake()
    except LabError:
        return None
    if lake.get("present") == 0:
        return (
            f"The server's data lake, {lake.get('directory', 'which it did not name')}, has none of its "
            f"{lake.get('files', 'data lake')} files, so the lead has no data lake to read. Pass --data-lake with the "
            "directory of yours."
        )

    return None


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
        lab = lab_request(arguments)
        client = LabClient(arguments.url, arguments.token)
        if (warning := data_lake_warning(arguments, client)) is not None:
            print(f"Warning: {warning}", file=sys.stderr)
        settings = RunSettings(
            chat=chat_request(arguments, client.tools()), timeout=arguments.timeout, lab=lab
        )
        judge_model = arguments.judge_model or arguments.model
        summary = run_bixbench(
            questions,
            directory,
            results,
            arguments.workspace,
            client,
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
