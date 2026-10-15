"""Where the server keeps what it runs: a conversation in a directory of its own, and its settings, all under
one workspace directory.

    virtual_lab_workspace/
        settings.json                                    what every new conversation starts with
        scientists.json                                  the scientists the person described
        tools.json                                       which of the library's tools a new conversation is not given
        chats/2026-10-07_1500_what-is-a-nanobody/        a conversation with the head of a lab, as Chat saves it
        data_lake/                                       Biomni's data lake, unless the settings keep it elsewhere

A conversation is shown from the files it was saved in.
"""

import json
import re
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

# The most characters of a title a directory is named after
MAX_SLUG_CHARS = 48


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
        known = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})


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
