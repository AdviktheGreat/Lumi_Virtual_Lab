"""What a conversation is set up with, which is kept with it so that it is carried on as it was set up.

A new conversation is given only what differs from the defaults in the workspace's settings. What
it is set up with is then written out in full, with each scientist as they were described then, so
that changing the library or the settings later does not change a conversation that has begun.
"""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from virtual_lab.agent import Agent
from virtual_lab.execution import ExecutionError, check_mountable
from virtual_lab.llm import detect_source
from virtual_lab.prompts import PRINCIPAL_INVESTIGATOR, SCIENTIFIC_CRITIC
from virtual_lab.schemas import normalize_title
from virtual_lab.scientists import SCIENTISTS
from virtual_lab.server.code import CodeSetup
from virtual_lab.server.library import SETTABLE_KEYS, missing_keys, models, provider_of
from virtual_lab.server.tools import check_tool_names, tool_names
from virtual_lab.server.workspace import SCIENTIST_FIELDS, Settings, Workspace, read_json
from virtual_lab.utils import write_atomically

CONFIG_FILE_NAME = "config.json"

# Who is on the team when none is chosen: the Scientific Critic, who reviews the others, and every
# other scientist of the library, so that the lead can bring in whoever a question needs
DEFAULT_TEAM = (
    SCIENTIFIC_CRITIC.title,
    *(
        agent.title
        for agent in SCIENTISTS
        if agent.title not in (PRINCIPAL_INVESTIGATOR.title, SCIENTIFIC_CRITIC.title)
    ),
)

# The settings a page shows and changes
PUBLIC_SETTINGS = (
    "model",
    "stream",
    "max_cost",
    "code",
    "sandbox",
    "network",
    "python",
    "data_lake",
    "forward_keys",
)

# What a team's scientist is described with
Spec = Mapping[str, Any]


def agent_from(data: Mapping[str, Any]) -> Agent:
    """An agent from its description, as describe_agent gives it, or as the page has it."""
    return Agent(
        title=str(data["title"]).strip(),
        expertise=str(data["expertise"]).strip(),
        goal=str(data["goal"]).strip(),
        role=str(data["role"]).strip(),
        model=str(data["model"]).strip(),
    )


@dataclass(frozen=True)
class ChatConfig:
    """What a conversation is set up with.

    :param model: The model the lead and the team use.
    :param lead: The head of the lab, as its title, expertise, goal, and role.
    :param team: The scientists the lead may bring in, each described the same way.
    :param code: Where code runs, and with what of Biomni's resources the agents are told of.
    :param max_cost: The most the conversation may spend in USD, or None for no limit.
    :param stream: Whether replies are shown as they are written.
    :param commercial_mode: Whether to leave out data and know-how that may not be used commercially.
    :param tools: The names of the library's tools the lead and the team may call, as the settings list them. Those
        that need code to run are given only where it does.
    """

    model: str
    lead: dict[str, str]
    team: tuple[dict[str, str], ...]
    code: CodeSetup
    max_cost: float | None
    stream: bool
    commercial_mode: bool
    tools: tuple[str, ...] = ()

    def lead_agent(self) -> Agent:
        return agent_from({**self.lead, "model": self.model})

    def team_agents(self) -> tuple[Agent, ...]:
        return tuple(agent_from({**member, "model": self.model}) for member in self.team)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "lead": dict(self.lead),
            "team": [dict(member) for member in self.team],
            "code": {
                "where": self.code.where,
                "sandbox": self.code.sandbox,
                "network": self.code.network,
                "python": self.code.python,
                "resources": self.code.resources,
                "data_lake": self.code.data_lake,
                "forward_env": list(self.code.forward_env),
            },
            "max_cost": self.max_cost,
            "stream": self.stream,
            "commercial_mode": self.commercial_mode,
            "tools": list(self.tools),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChatConfig":
        return cls(
            model=str(data["model"]),
            lead={key: str(data["lead"][key]) for key in SCIENTIST_FIELDS},
            team=tuple({key: str(member[key]) for key in SCIENTIST_FIELDS} for member in data["team"]),
            code=CodeSetup(**data["code"]),
            max_cost=data["max_cost"],
            stream=bool(data["stream"]),
            commercial_mode=bool(data["commercial_mode"]),
            # A conversation begun before the lead had tools of the library's has none, and goes on without
            tools=tuple(str(name) for name in data.get("tools", ())),
        )


def public_settings(settings: Settings) -> dict[str, Any]:
    return {key: getattr(settings, key) for key in PUBLIC_SETTINGS}


def data_lake_directory(settings: Settings, workspace: Workspace) -> Path:
    """Where Biomni's data lake is kept: where the settings say, or in the workspace."""
    return Path(settings.data_lake).expanduser() if settings.data_lake else workspace.data_lake_dir


def check_data_lake(value: Any, workspace: Workspace) -> str:
    """A directory for the data lake, made a full path, or "" for the workspace's own.

    :raises ValueError: If it is not a full path, is a file, cannot be mounted into a container, or is where
        conversations are kept or holds them, which would leave code able to change the data lake.
    """
    if not isinstance(value, str):
        raise ValueError(f"The data lake is a directory, not {value!r}")
    if not value.strip():
        return ""
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise ValueError(f"The data lake is a full path, which {value.strip()!r} is not")
    path = path.resolve()
    if path.is_file():
        raise ValueError(f"The data lake is a directory, and {path} is a file")
    try:
        check_mountable(path, "Choose another directory.")
    except ExecutionError as error:
        raise ValueError(str(error)) from error
    chats = workspace.chats_dir
    if path.is_relative_to(chats) or chats.is_relative_to(path):
        raise ValueError(f"The data lake cannot be where conversations are kept, {chats}, or hold them")

    return str(path)


def check_forward_keys(names: Any) -> list[str]:
    """The keys to give code, without repeats.

    :raises ValueError: If it is not a list of keys the interface can set.
    """
    if not isinstance(names, (list, tuple)):
        raise ValueError(f"The keys to give code are a list of names, not {names!r}")
    if unknown := [name for name in names if name not in SETTABLE_KEYS]:
        raise ValueError(f"A key to give code is one of {', '.join(SETTABLE_KEYS)}, not {', '.join(map(str, unknown))}")

    return list(dict.fromkeys(names))


def update_settings(settings: Settings, changes: Mapping[str, Any], workspace: Workspace) -> Settings:
    """The settings with these changed, which are not kept if one cannot be used.

    :param changes: Any of the public settings, with the value to give it.
    :param workspace: The workspace they are for, to check the data lake against where its conversations are.
    :raises ValueError: If a setting is not one that can be changed, or its value cannot be used.
    """
    if unknown := sorted(set(changes) - set(PUBLIC_SETTINGS)):
        raise ValueError(f"There is no setting {', '.join(unknown)}")
    changed = replace(settings, **changes)
    detect_source(changed.model)
    CodeSetup(where=changed.code, sandbox=changed.sandbox)
    if "data_lake" in changes:
        changed.data_lake = check_data_lake(changed.data_lake, workspace)
    if "forward_keys" in changes:
        changed.forward_keys = check_forward_keys(changed.forward_keys)
    if changed.max_cost is not None:
        changed.max_cost = float(changed.max_cost)
        if not (math.isfinite(changed.max_cost) and changed.max_cost >= 0):
            raise ValueError(f"max_cost must be a finite amount, zero or more, not {changed.max_cost}")

    return changed


def describe_models() -> list[dict[str, Any]]:
    """The models to choose from, each with its provider and whether the keys that provider needs are set."""
    return [{"id": model, "provider": provider_of(model), "ready": not missing_keys([model])} for model in models()]


def library(workspace: Workspace) -> list[dict[str, Any]]:
    """The scientists to choose from: the library's, then those the person described, which stand in
    place of any with the same title. Each has its title, expertise, goal, and role, and whether it is
    built in."""
    chosen: dict[str, dict[str, Any]] = {
        agent.title.casefold(): {**{key: getattr(agent, key) for key in SCIENTIST_FIELDS}, "builtin": True}
        for agent in SCIENTISTS
    }
    for item in workspace.load_scientists():
        chosen[item["title"].casefold()] = {**item, "builtin": False}

    return list(chosen.values())


def describe_scientist(choice: str | Spec, scientists: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """A scientist as the request names them, by title, or as it describes them.

    :raises ValueError: If a title is not in the library or a description lacks a part.
    """
    if isinstance(choice, str):
        found = next((item for item in scientists if str(item["title"]).casefold() == choice.strip().casefold()), None)
        if found is None:
            raise ValueError(f'There is no scientist titled "{choice}"')
        choice = found
    spec = {key: " ".join(str(choice.get(key) or "").split()) for key in SCIENTIST_FIELDS}
    if empty := [key for key, value in spec.items() if not value]:
        raise ValueError(f"A scientist needs {', '.join(empty)}")

    return spec


def resolve_config(request: Mapping[str, Any], settings: Settings, workspace: Workspace) -> ChatConfig:
    """What a new conversation is set up with: what the request gives, and the settings for the rest.

    :param request: What the person chose. A key left out is taken from the settings, or the library: "model",
        "lead" and each of "team", by title or described, "code" with any of where, sandbox, network, python,
        and resources, "max_cost" (null for no limit), "stream", "commercial_mode", and "tools", the names of the
        library's tools to give, which are all but those the workspace has turned off.
    :raises ValueError: If something chosen cannot be used.
    """
    scientists = library(workspace)
    model = str(request.get("model") or settings.model).strip()
    detect_source(model)

    lead = describe_scientist(request.get("lead") or PRINCIPAL_INVESTIGATOR.title, scientists)
    team_choice = request["team"] if request.get("team") is not None else DEFAULT_TEAM
    team = tuple(describe_scientist(choice, scientists) for choice in team_choice)
    titles = [normalize_title(member["title"]) for member in (lead, *team)]
    if len(set(titles)) != len(titles):
        raise ValueError("The lead and the team must have different titles")

    code = resolve_code(request.get("code") or {}, settings, workspace)

    max_cost = request["max_cost"] if "max_cost" in request else settings.max_cost
    if max_cost is not None:
        max_cost = float(max_cost)
        if not (math.isfinite(max_cost) and max_cost >= 0):
            raise ValueError(f"max_cost must be a finite amount, zero or more, not {max_cost}")

    stream = request["stream"] if request.get("stream") is not None else settings.stream
    if request.get("tools") is not None:
        tools = check_tool_names(request["tools"])
    else:
        disabled = workspace.load_disabled_tools()
        tools = [name for name in tool_names() if name not in disabled]

    return ChatConfig(
        model=model,
        lead=lead,
        team=team,
        code=code,
        max_cost=max_cost,
        stream=bool(stream),
        commercial_mode=bool(request.get("commercial_mode") or False),
        tools=tuple(tools),
    )


def resolve_code(request: Mapping[str, Any], settings: Settings, workspace: Workspace) -> CodeSetup:
    """Where code runs and what it has there: what the request gives, and the settings for the rest.

    Under Docker, Biomni's environments get the data lake, and the keys the settings give code are passed in.

    :raises ValueError: If something chosen cannot be used.
    """
    chosen = {
        "where": settings.code,
        "sandbox": settings.sandbox,
        "network": settings.network,
        "python": settings.python,
        **request,
    }
    docker = chosen["where"] == "docker"
    if "data_lake" in chosen:
        chosen["data_lake"] = check_data_lake(chosen["data_lake"], workspace)
    elif docker and chosen["sandbox"] != "python":
        chosen["data_lake"] = str(data_lake_directory(settings, workspace))
    if "forward_env" in chosen:
        chosen["forward_env"] = check_forward_keys(chosen["forward_env"])
    elif docker:
        chosen["forward_env"] = check_forward_keys(settings.forward_keys)

    return CodeSetup(**chosen)


def save_config(directory: Path, config: ChatConfig) -> None:
    write_atomically(directory / CONFIG_FILE_NAME, json.dumps(config.to_dict(), indent=4).encode("utf-8"))


def load_config(directory: Path) -> ChatConfig | None:
    """The configuration saved in a conversation's directory, or None if there is none that can be read."""
    try:
        return ChatConfig.from_dict(read_json(directory / CONFIG_FILE_NAME))
    except (KeyError, TypeError, ValueError):
        return None
