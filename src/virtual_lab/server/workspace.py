"""Where the server keeps what it runs: a conversation in a directory of its own, and its settings, all under
one workspace directory.

    virtual_lab_workspace/
        settings.json                                    what every new conversation starts with
        scientists.json                                  the scientists the person described
        tools.json                                       which of the library's tools a new conversation is not given
        mcp.json                                         the MCP servers the person set up, each as a config gives it
        own.json                                         the data and software the person gave every conversation
        own_data/                                        the files the person uploaded, which own.json describes
        chats/2026-10-07_1500_what-is-a-nanobody/        a conversation with the head of a lab, as Chat saves it
        data_lake/                                       Biomni's data lake, unless the settings keep it elsewhere

A conversation is shown from the files it was saved in.
"""

import json
import math
import re
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from virtual_lab.constants import DEFAULT_MODEL
from virtual_lab.utils import write_atomically

DEFAULT_WORKSPACE = Path.home() / "virtual_lab_workspace"

SETTINGS_FILE_NAME = "settings.json"

# Where the workspace keeps Biomni's data lake, beside the conversations and not in any of them
DATA_LAKE_DIR_NAME = "data_lake"

# The scientists the person described, to put on a team beside the library's
SCIENTISTS_FILE_NAME = "scientists.json"
SCIENTIST_FIELDS = ("title", "expertise", "goal", "role")

# The tools the person turned off, to leave out of a new conversation
TOOLS_FILE_NAME = "tools.json"

# The MCP servers the person set up, by name, each as a config gives it
MCP_FILE_NAME = "mcp.json"

# The data and software the person gave the lab to use in every conversation, and where the files they uploaded are kept
OWN_FILE_NAME = "own.json"
OWN_DATA_DIR_NAME = "own_data"

# The most characters of a title a directory is named after
MAX_SLUG_CHARS = 48


def is_text(value: Any) -> bool:
    return isinstance(value, str)


def is_flag(value: Any) -> bool:
    return isinstance(value, bool)


def is_budget(value: Any) -> bool:
    """Whether it is None, for no limit, or an amount of money."""
    if value is None:
        return True

    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def is_names(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(name, str) for name in value)


@dataclass
class Settings:
    """What every new conversation starts with, kept in the workspace's settings.json.

    :param model: The model every new agent is given.
    :param stream: Whether replies are shown word by word as they are written.
    :param max_cost: The budget a conversation starts with, in USD, or None for none.
    :param code: Where agents' code runs: "none", "docker", or "local".
    :param sandbox: The sandbox image a session runs in with Docker: "python", or a stage of
        Biomni's environment, "base", "bio", or "full".
    :param network: Whether code in a session can reach the network.
    :param python: The interpreter code runs with on this machine, or "" for this one.
    :param data_lake: The directory Biomni's data lake is kept in, or "" for the workspace's own.
    :param forward_keys: The API keys code in a Docker session may read, by name. Code can send what it reads
        anywhere the network reaches, so none is given unless chosen.
    """

    model: str = DEFAULT_MODEL
    stream: bool = True
    max_cost: float | None = 2.0
    code: str = "none"
    sandbox: str = "python"
    network: bool = True
    python: str = ""
    data_lake: str = ""
    forward_keys: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        """The settings a file holds. A value that is not of the kind its setting is, which a file edited by hand can
        have, is left out and takes the default, so that one cannot make every change to the settings fail."""
        known = {item.name for item in fields(cls)}

        return cls(**{key: value for key, value in data.items() if key in known and SETTING_KINDS[key](value)})


# What each setting is, for what a file holds to be checked against
SETTING_KINDS: dict[str, Callable[[Any], bool]] = {
    "model": lambda value: is_text(value) and bool(value.strip()),
    "stream": is_flag,
    "max_cost": is_budget,
    "code": is_text,
    "sandbox": is_text,
    "network": is_flag,
    "python": is_text,
    "data_lake": is_text,
    "forward_keys": is_names,
}


def slug(text: str) -> str:
    """Text made into a short name for a directory: lower case words joined by "-"."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    name = ""
    for word in words:
        if len(name) + len(word) + 1 > MAX_SLUG_CHARS:
            break
        name = f"{name}-{word}" if name else word

    return name or "untitled"


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Workspace:
    """The directory the server saves conversations in.

    :param root: The directory, created if missing.
    """

    def __init__(self, root: Path = DEFAULT_WORKSPACE) -> None:
        self.root = Path(root).expanduser().resolve()
        self.chats_dir.mkdir(parents=True, exist_ok=True)
        # Held while the MCP servers are read, changed, and written back, so that two changes do not undo each other
        self._mcp_lock = threading.Lock()
        # Likewise for the data and software the person gave
        self._own_lock = threading.Lock()

    @property
    def chats_dir(self) -> Path:
        return self.root / "chats"

    @property
    def data_lake_dir(self) -> Path:
        """Where Biomni's data lake is kept unless the settings say otherwise."""
        return self.root / DATA_LAKE_DIR_NAME

    @property
    def settings_path(self) -> Path:
        return self.root / SETTINGS_FILE_NAME

    def load_settings(self) -> Settings:
        data = read_json(self.settings_path)
        return Settings.from_dict(data) if isinstance(data, dict) else Settings()

    def save_settings(self, settings: Settings) -> None:
        write_atomically(self.settings_path, json.dumps(asdict(settings), indent=4).encode("utf-8"))

    @property
    def scientists_path(self) -> Path:
        return self.root / SCIENTISTS_FILE_NAME

    def load_scientists(self) -> list[dict[str, str]]:
        """The scientists the person described, each with a title, expertise, goal, and role."""
        data = read_json(self.scientists_path)
        if not isinstance(data, list):
            return []

        return [
            {key: str(item[key]) for key in SCIENTIST_FIELDS}
            for item in data
            if isinstance(item, dict) and all(str(item.get(key) or "").strip() for key in SCIENTIST_FIELDS)
        ]

    def save_scientist(self, scientist: dict[str, str]) -> None:
        """Keeps a scientist the person described, in place of any with the same title.

        :raises ValueError: If a field is empty.
        """
        described = {key: " ".join(str(scientist.get(key) or "").split()) for key in SCIENTIST_FIELDS}
        if empty := [key for key, value in described.items() if not value]:
            raise ValueError(f"A scientist needs {', '.join(empty)}")
        kept = [item for item in self.load_scientists() if item["title"].casefold() != described["title"].casefold()]
        write_atomically(self.scientists_path, json.dumps([*kept, described], indent=4).encode("utf-8"))

    def remove_scientist(self, title: str) -> None:
        kept = [item for item in self.load_scientists() if item["title"].casefold() != title.casefold()]
        write_atomically(self.scientists_path, json.dumps(kept, indent=4).encode("utf-8"))

    @property
    def tools_path(self) -> Path:
        return self.root / TOOLS_FILE_NAME

    def load_disabled_tools(self) -> list[str]:
        """The names of the tools that a new conversation is not given, which is none until some are turned off.

        Those turned off are kept, and not those on, so that a tool the library gains later is on.
        """
        data = read_json(self.tools_path)
        disabled = data.get("disabled") if isinstance(data, dict) else None

        return [name for name in disabled if isinstance(name, str)] if isinstance(disabled, list) else []

    def save_disabled_tools(self, names: list[str]) -> None:
        write_atomically(self.tools_path, json.dumps({"disabled": names}, indent=4).encode("utf-8"))

    @property
    def mcp_path(self) -> Path:
        return self.root / MCP_FILE_NAME

    def load_mcp_servers(self) -> dict[str, dict[str, Any]]:
        """The MCP servers the person set up, by name, in the order they were set up. A preset is kept as the entry
        {"preset": its name}, with whether it is on and how it is signed in to."""
        data = read_json(self.mcp_path)
        servers = data.get("servers") if isinstance(data, dict) else None
        if not isinstance(servers, dict):
            return {}

        return {name: entry for name, entry in servers.items() if isinstance(name, str) and isinstance(entry, dict)}

    def put_mcp_server(self, name: str, entry: dict[str, Any]) -> None:
        """Keeps a server's entry, in place of any it had, or after the others if it had none."""
        with self._mcp_lock:
            servers = self.load_mcp_servers()
            servers[name] = entry
            write_atomically(self.mcp_path, json.dumps({"servers": servers}, indent=4).encode("utf-8"))

    def update_mcp_server(self, name: str, change: Callable[[dict[str, Any] | None], dict[str, Any]]) -> dict[str, Any]:
        """Changes a server's entry as `change` says, which is given what is kept for it, or None, and what to keep. A
        change made at the same time by another is not lost, and one that fails keeps nothing."""
        with self._mcp_lock:
            servers = self.load_mcp_servers()
            entry = change(servers.get(name))
            servers[name] = entry
            write_atomically(self.mcp_path, json.dumps({"servers": servers}, indent=4).encode("utf-8"))

        return entry

    def remove_mcp_server(self, name: str) -> bool:
        """Forgets a server. Whether there was one."""
        with self._mcp_lock:
            servers = self.load_mcp_servers()
            if name not in servers:
                return False
            del servers[name]
            write_atomically(self.mcp_path, json.dumps({"servers": servers}, indent=4).encode("utf-8"))

        return True

    @property
    def own_path(self) -> Path:
        return self.root / OWN_FILE_NAME

    @property
    def own_data_dir(self) -> Path:
        """Where the files the person uploaded are kept, each under the name code finds it by."""
        return self.root / OWN_DATA_DIR_NAME

    def load_own(self) -> dict[str, dict[str, Any]]:
        """What the person gave the lab, as {"data": {name: {"description": ..., "path": ...}}, "software": {name:
        description}}. A piece of data has a path if it is somewhere else on this machine, and has none if it was
        uploaded, and so is in own_data. What a file edited by hand holds that is not of this kind is left out."""
        data = read_json(self.own_path)
        if not isinstance(data, dict):
            data = {}
        kept_data: dict[str, dict[str, Any]] = {}
        entries = data.get("data")
        for name, entry in (entries if isinstance(entries, dict) else {}).items():
            if not (isinstance(name, str) and name and isinstance(entry, dict)):
                continue
            description = entry.get("description")
            path = entry.get("path")
            if not (isinstance(description, str) and description.strip()) or not (path is None or is_text(path)):
                continue
            kept_data[name] = {"description": description, **({"path": path} if path is not None else {})}
        kept_software: dict[str, str] = {}
        entries = data.get("software")
        for name, description in (entries if isinstance(entries, dict) else {}).items():
            if isinstance(name, str) and name and isinstance(description, str) and description.strip():
                kept_software[name] = description

        return {"data": kept_data, "software": kept_software}

    def update_own(self, change: Callable[[dict[str, dict[str, Any]]], None]) -> None:
        """Changes what the person gave the lab as `change` says, which is given what is kept, to change in place. A
        change made at the same time by another is not lost, and one that fails keeps nothing."""
        with self._own_lock:
            kept = self.load_own()
            change(kept)
            write_atomically(self.own_path, json.dumps(kept, indent=4).encode("utf-8"))

    def new_chat_directory(self, title: str, now: datetime | None = None) -> Path:
        """A new directory for a conversation, named after when it began and what it is called.

        :param title: What the conversation is called.
        :param now: When it begins, defaulting to now.
        """
        base = f"{(now or datetime.now()).strftime('%Y-%m-%d_%H%M')}_{slug(title)}"
        path = self.chats_dir / base
        number = 2
        while True:
            # Made, not looked for first: of two requests that begin at once with the same name, one makes it
            # and the other takes the next
            try:
                path.mkdir(parents=True)
            except FileExistsError:
                path = self.chats_dir / f"{base}-{number}"
                number += 1
            else:
                return path
