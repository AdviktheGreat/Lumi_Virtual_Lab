"""The graph of how PaperAgents' papers relate to one another, made from what is kept of each.

Nothing is run and no model is asked: the facts that were read of each paper, its claims, the address and commit of its
code, and what the trying of its claims came to are put to paperagents/relating.py, which finds where papers name the
same dataset, method, or software, have the same code, name one another, or have claims that agree or differ. It is made
when it is asked for, from what is kept then, so it never shows what is not kept now.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from virtual_lab.paperagents import relating
from virtual_lab.paperagents.reading import CARD_KINDS, RESOURCE_KINDS
from virtual_lab.server import paperagent_reading as kept_reading
from virtual_lab.server import paperagent_repository as kept_repository
from virtual_lab.server import paperagent_reproduction as kept_reproduction
from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.paperagent_given import find
from virtual_lab.server.paperagents import PaperAgents, kept_tools_of, made_with
from virtual_lab.server.workspace import Workspace

# The most papers that are put against each other, as the work grows with the square of them
MOST_PAPERS = 40


def reproduction_of(directory: Path, agent: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, str] | None:
    """What the trying of a paper's claims came to, by claim, if the account is of the code and claims that are kept
    now."""
    record = kept_reproduction.load(directory)
    if record is None or not kept_reproduction.is_current(record, kept_tools_of(directory, agent)[0], claims):
        return None

    return {entry["id"]: entry["status"] for entry in record["claims"]}


def paper_of(workspace: Workspace, agent_id: str) -> dict[str, Any] | None:
    """An agent as relating.build takes a paper, or None if the agent is gone."""
    found = find(workspace, agent_id)
    if found is None:
        return None
    directory, agent = found
    paper = agent["paper"]
    file = paper.get("file")
    described = kept_reading.describe(directory, file["sha256"] if file is not None else None, made_with())
    read = described["chunks"] is not None
    facts: dict[str, list[dict[str, Any]]] = {}
    for kind in (*CARD_KINDS, *RESOURCE_KINDS):
        source = described["card"] if kind in CARD_KINDS else described["resources"]
        facts[kind] = list(source.get(kind, ())) if read else []
    claims = kept_reading.claims_of(directory) if read else []
    code = agent.get("repo")
    intake = kept_repository.load(directory, code["url"] if code is not None else None)

    return {
        "id": agent_id,
        "title": agent["title"],
        "doi": paper.get("doi"),
        "url": paper.get("url"),
        "code": code["url"] if code is not None else None,
        "commit": intake["commit"] if intake is not None else None,
        "read": read,
        "facts": facts,
        "claims": claims,
        "reproduction": reproduction_of(directory, agent, claims),
    }


def graph_of(workspace: Workspace, agent_ids: Iterable[str]) -> dict[str, Any]:
    """How the papers of these agents relate to one another, of the first MOST_PAPERS of them that there are.

    :return: As relating.build gives it, with `left_out`: how many papers were not put against the others.
    """
    ids = [agent_id for agent_id in dict.fromkeys(agent_ids) if find(workspace, agent_id) is not None]
    papers = [paper_of(workspace, agent_id) for agent_id in ids[:MOST_PAPERS]]
    built = relating.build([paper for paper in papers if paper is not None])

    return {**built, "left_out": max(0, len(ids) - MOST_PAPERS)}


def view(
    paperagents: PaperAgents,
    agent_ids: list[str] | None = None,
    agent: str | None = None,
    kind: str | None = None,
    about: str | None = None,
) -> dict[str, Any]:
    """The graph of the agents there are, or of those that are asked for, as a page shows it.

    :param agent_ids: Which agents to put against each other, or None for all of them.
    :param agent: Only the relations that this agent (its id, or a part of its title) is in.
    :param kind: Only the relations of this kind.
    :param about: Only the relations that have these words in what they say.
    :raises ApiError: If an agent that is asked for is not there, or the kind or the words are not ones.
    """
    if agent_ids is not None:
        missing = [agent_id for agent_id in agent_ids if find(paperagents.workspace, agent_id) is None]
        if missing:
            raise not_found(f"PaperAgent {missing[0]}")
    ids = agent_ids if agent_ids is not None else paperagents.agent_ids()
    graph = graph_of(paperagents.workspace, ids)
    try:
        chosen = relating.select(graph, agent, kind, about)
    except ValueError as error:
        raise ApiError(422, "invalid", str(error)) from error

    return {
        **chosen,
        "left_out": graph["left_out"],
        "kinds": list(relating.KINDS),
        "meaning": relating.MEANING,
        "limits": {"most_papers": MOST_PAPERS, "most_relations": relating.MOST_RELATIONS},
    }
