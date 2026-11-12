"""What MCP servers held when they were last connected to, so that the settings and the slash menu can show it without
connecting.

A server's resources and prompts are known only once it has been connected to, which a conversation does when its first
message is sent, and a check does when it is asked to. What each listed is kept then, with a fingerprint of how the
server is reached, and is shown while the server is set up as it was. A server that is changed is shown as one that has
not been looked at, until it is connected to again. What is kept is only for showing: nothing is read or rendered from
it, and a prompt is rendered by asking the server.
"""

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from virtual_lab.mcp_context import one_line
from virtual_lab.mcp_tools import Held

# What the entry of a server says that is not about how it is reached, which does not change what it holds
NOT_ABOUT_REACHING = ("enabled", "disabled")

# Most characters of what is kept of a server's words, each as one line, so that a server cannot fill a page
MAX_NAME_CHARS = 200
MAX_URI_CHARS = 500
MAX_ABOUT_CHARS = 500
MAX_ARGUMENT_ABOUT_CHARS = 300


def fingerprint(name: str, entry: Mapping[str, Any] | None) -> str:
    """A short mark of how a server is reached, which is the same while it is set up the same way, whether it is on
    or off."""
    given = {key: value for key, value in (entry or {}).items() if key not in NOT_ABOUT_REACHING}

    return hashlib.sha256(json.dumps([name, given], sort_keys=True, default=str).encode("utf-8")).hexdigest()


def describe_held(held: Held) -> dict[str, Any]:
    """What a server listed besides its tools, as the settings show it: each resource and prompt as one line of what
    the server said, cut short."""
    return {
        "resources": [
            {
                "name": one_line(resource.name, MAX_NAME_CHARS),
                "title": one_line(resource.title, MAX_NAME_CHARS) or None,
                "uri": one_line(resource.uri, MAX_URI_CHARS),
                "description": one_line(resource.description, MAX_ABOUT_CHARS),
                "mime_type": one_line(resource.mime_type, MAX_NAME_CHARS) or None,
                "template": resource.template,
            }
            for resource in held.resources
        ],
        "prompts": [
            {
                "name": one_line(prompt.name, MAX_NAME_CHARS),
                "command": prompt.command,
                "title": one_line(prompt.title, MAX_NAME_CHARS) or None,
                "description": one_line(prompt.description, MAX_ABOUT_CHARS),
                "arguments": [
                    {
                        "name": one_line(argument.name, MAX_NAME_CHARS),
                        "description": one_line(argument.description, MAX_ARGUMENT_ABOUT_CHARS),
                        "required": argument.required,
                    }
                    for argument in prompt.arguments
                ],
            }
            for prompt in held.prompts
        ],
        "problems": [one_line(problem, MAX_ABOUT_CHARS) for problem in held.problems],
        "more": held.more,
    }


def seen_record(
    name: str, entry: Mapping[str, Any] | None, held: Mapping[str, Any], now: datetime | None = None
) -> dict[str, Any]:
    """What is kept of a server that was connected to: what it held, with the mark of how it was reached and when."""
    return {
        "fingerprint": fingerprint(name, entry),
        "seen": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **held,
    }


def is_listed(value: Any, keys: tuple[str, ...]) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict) and all(key in item for key in keys) for item in value
    )


def recall_held(records: Mapping[str, Any], name: str, entry: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """What a server held when it was last connected to, if it is still set up as it was, and None if it has not been
    connected to, has been changed since, or what was kept cannot be read."""
    record = records.get(name)
    if entry is None or not isinstance(record, dict) or record.get("fingerprint") != fingerprint(name, entry):
        return None
    problems = record.get("problems")
    if (
        not is_listed(record.get("resources"), ("name", "uri"))
        or not is_listed(record.get("prompts"), ("name", "command", "arguments"))
        or not all(is_listed(prompt["arguments"], ("name",)) for prompt in record["prompts"])
        or not isinstance(problems, list)
        or not all(isinstance(problem, str) for problem in problems)
    ):
        return None
    seen = record.get("seen")

    return {
        "resources": record["resources"],
        "prompts": record["prompts"],
        "problems": problems,
        "more": record.get("more") is True,
        "seen": seen if isinstance(seen, str) else None,
    }
