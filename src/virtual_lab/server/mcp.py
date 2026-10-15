"""The MCP servers a person sets up for the lead of a conversation to be given the tools of, and what the settings
say of each.

A server is kept as its entry in a config, as connect_mcp reads one: the presets of the library's services, which are
turned on and off, and servers of the person's own, which are described in full. A conversation begins with the
servers that are on, and connects to them when its first message is sent, since that may take a sign-in or a
download; see virtual_lab.server.connections.
"""

import json
import os
import re
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from virtual_lab.mcp_auth import has_sign_in, sign_out_mcp
from virtual_lab.mcp_presets import MCP_PRESETS, preset_entry
from virtual_lab.mcp_tools import SERVER_KEYS, VARIABLE, MCPServerConfig, MCPTools, connect_mcp, parse_server

# What a server's name may be, which its tools' names start with, so that it is one of letters, digits, and "_"
SERVER_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")

# The most servers a person may set up, which is more than anyone would
MAX_SERVERS = 64

# Seconds a check of a server waits for it to start, or to answer, which is less than a conversation waits, since a
# person is watching for the answer
CHECK_TIMEOUT = 30.0


def with_defaults(value: Any) -> Any:
    """A config's value with every variable that has no default given one, so that it can be read, and so checked,
    where the variable is not set, as it is before a key is."""
    if isinstance(value, str):
        return VARIABLE.sub(lambda found: found[0] if found[2] is not None else f"${{{found[1]}:-x}}", value)
    if isinstance(value, list):
        return [with_defaults(item) for item in value]
    if isinstance(value, dict):
        return {key: with_defaults(item) for key, item in value.items()}

    return value


def variables_in(value: Any) -> list[str]:
    """The environment variables a config's value asks for, each once, in the order they are first asked for."""
    if isinstance(value, str):
        return [found[1] for found in VARIABLE.finditer(value) if found[2] is None]
    items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()

    return list(dict.fromkeys(name for item in items for name in variables_in(item)))


def service_keys() -> tuple[str, ...]:
    """The variables that hold the keys of the presets' services, which the interface may be given for the rest of the
    process, as it may the keys of the model providers. Only these: a server of a person's own asks for what it
    wants from the environment the server was started in."""
    return tuple(
        dict.fromkeys(
            name
            for preset in MCP_PRESETS.values()
            if preset.credential is not None
            for name in variables_in(preset.entry.get("headers", {}))
        )
    )


def is_on(entry: Mapping[str, Any]) -> bool:
    return entry.get("enabled", True) is True and entry.get("disabled", False) is not True


def server_title(name: str, entry: Mapping[str, Any] | None) -> str:
    """What to call a server: a preset by its title, and any other by its name."""
    if name in MCP_PRESETS and (entry is None or entry.get("preset") == name):
        return MCP_PRESETS[name].title

    return name


def read_server(name: str, entry: Mapping[str, Any], strict: bool = False) -> MCPServerConfig:
    """How to reach a server, as connect_mcp reads its entry, whether or not it is on.

    A variable that is not set is read as if it were, since a key is given after a server is turned on, and a setting
    that is not used, because of a typo, is an error, where connect_mcp would only warn of it.

    :param strict: Whether a variable that is not set is an error, as it is to connect_mcp, for what depends on what the
        variables are.
    :raises ValueError: If the entry is not one connect_mcp would read, saying what is wrong.
    """
    if unknown := sorted(str(key) for key in set(entry) - SERVER_KEYS):
        raise ValueError(f"The server {name} has settings that are not used: {', '.join(unknown)}")
    shape = {key: value for key, value in entry.items() if key not in ("enabled", "disabled")}
    try:
        # A preset is filled in first, so that the variables its entry asks for are given defaults too
        filled, preset = preset_entry(name, shape)
        parsed = parse_server(
            name, {**(filled if strict else with_defaults(filled)), **({"preset": shape["preset"]} if preset else {})}
        )
    except (ValueError, TypeError, OSError) as error:
        raise ValueError(str(error)) from None
    assert parsed is not None

    return parsed


def check_entry(name: Any, entry: Any) -> dict[str, Any]:
    """A server's entry as it is kept, if it is one that connect_mcp would read.

    Nothing is connected to, and a variable that is not set is not an error, as read_server says.

    :param name: The server's name.
    :param entry: How to reach it, as a config gives it, or {"preset": ...} for a preset's.
    :raises ValueError: If it is not, saying what is wrong.
    """
    if not isinstance(name, str) or not SERVER_NAME.fullmatch(name):
        raise ValueError(
            f"A server's name starts with a letter and is made of letters, digits, and _, at most 32, not {name!r}"
        )
    if not isinstance(entry, Mapping):
        raise ValueError(f"The server {name} is described by a mapping, such as {{'url': 'https://...'}}")
    try:
        # What is kept is JSON, and is the same when it is read back
        kept = json.loads(json.dumps(dict(entry)))
    except (TypeError, ValueError) as error:
        raise ValueError(f"The server {name} is described in JSON: {error}") from None
    if name in MCP_PRESETS and kept.get("preset") != name:
        raise ValueError(f"{name} is the name of a preset: name your own server something else, or use the preset")
    for key in ("enabled", "disabled"):
        if key in kept and not isinstance(kept[key], bool):
            raise ValueError(f"{key} of the server {name} must be true or false, not {kept[key]!r}")
    read_server(name, kept)

    return kept


def change_entry(name: str, entry: Mapping[str, Any] | None, enabled: bool | None, auth: str | None) -> dict[str, Any]:
    """A server's entry with it turned on or off, or with how it is signed in to chosen, and the rest as it was.

    :param name: The server's name.
    :param entry: What is kept for it, or None for one that has not been set up, which only a preset can be.
    :param enabled: Whether it is to be on, or None to leave that as it is.
    :param auth: "oauth" to sign in to a preset, or "key" to give it an API key, or None to leave that as it is.
    :raises KeyError: If there is no such server to change.
    :raises ValueError: If it cannot be changed so, saying why.
    """
    if entry is None:
        if name not in MCP_PRESETS:
            raise KeyError(name)
        entry = {"preset": name}
    changed = dict(entry)
    if enabled is not None:
        changed.pop("disabled", None)
        # Being on is how a server is, so that is said by leaving it out
        if enabled:
            changed.pop("enabled", None)
        else:
            changed["enabled"] = False
    if auth is not None:
        preset = MCP_PRESETS.get(name)
        if preset is None or changed.get("preset") != name or not (preset.credential and preset.signing_in):
            title = server_title(name, entry)
            raise ValueError(f"{title} is not one that is given a key or signed in to as you choose")
        if auth == "oauth":
            changed["auth"] = "oauth"
        else:
            changed.pop("auth", None)

    return check_entry(name, changed)


def program_missing(command: str | None, cwd: str | None) -> bool:
    """Whether the program a server is started with cannot be found where it would be started."""
    if not command:
        return False
    if os.sep in command or (os.altsep and os.altsep in command):
        return not (Path(cwd or ".") / command).expanduser().exists()

    return shutil.which(command) is None


def describe_server(name: str, entry: Mapping[str, Any] | None) -> dict[str, Any]:
    """A server as the settings show it.

    :param name: Its name.
    :param entry: What is kept for it, or None for a preset that has not been set up.
    :return: Its title, what it is for, whether it is on, how it is signed in to or given a key and which keys are
        missing, which of the keys the interface may give are set, whether it has tools that wait for the researcher's
        approval, whether a sign-in to it is kept (None for a server that is not signed in to), and, if it cannot work
        as it is, why.
    """
    preset = MCP_PRESETS.get(name)
    if preset is not None and (entry is None or entry.get("preset") == name):
        given: Mapping[str, Any] = entry if entry is not None else {"preset": name}
    else:
        preset, given = None, entry or {}
    added = entry is not None
    problem: str | None = None
    parsed = None
    try:
        parsed = read_server(name, given)
    except ValueError as error:
        problem = str(error)
    filled = preset_entry(name, dict(given))[0] if parsed is not None else {}
    missing = [
        {"name": variable, "settable": variable in service_keys()}
        for variable in variables_in(filled)
        if variable not in os.environ
    ]
    if parsed is not None and parsed.transport == "stdio" and program_missing(parsed.command, parsed.cwd):
        problem = f"The program {parsed.command} is not installed here, or is not where the server looks for it."
    choices = ["key", "oauth"] if preset is not None and preset.credential and preset.signing_in else []
    signs_in = parsed is not None and parsed.auth == "oauth"

    return {
        "name": name,
        "title": server_title(name, entry),
        "about": preset.about if preset is not None else None,
        "preset": preset is not None,
        "added": added,
        "enabled": added and is_on(given),
        "auth": "oauth" if signs_in else ("key" if choices else None),
        "auth_choices": choices,
        "transport": parsed.transport if parsed is not None else None,
        "target": parsed.shown if parsed is not None else None,
        "asks": bool(parsed is not None and parsed.ask),
        "signed_in": sign_in_kept(name, given) if signs_in else None,
        "missing": missing,
        "keys_set": [
            variable for variable in variables_in(filled) if variable in os.environ and variable in service_keys()
        ],
        "problem": problem,
        "setup": preset.setup_for(dict(given)) if preset is not None else None,
    }


def sign_in_url(name: str, entry: Mapping[str, Any] | None) -> str | None:
    """The address of a server that is signed in to, as its entry and the environment make it, or None for one that is
    not signed in to.

    :param entry: What is kept for it, or None for a preset that has not been set up.
    :raises ValueError: If the entry cannot be read, as read_server says.
    """
    given = entry if entry is not None else {"preset": name}
    parsed = read_server(name, given)
    if parsed.auth != "oauth":
        return None
    # A variable in the address that is not set is read as a placeholder, which would name another server's sign-in
    if variables_in(preset_entry(name, dict(given))[0].get("url")):
        return read_server(name, given, strict=True).url

    return parsed.url


def sign_in_kept(name: str, entry: Mapping[str, Any] | None) -> bool | None:
    """Whether a sign-in to a server is kept, or None where that is not known, because the server's address is not."""
    try:
        url = sign_in_url(name, entry)
    except ValueError:
        return None

    return None if url is None else has_sign_in(url)


def sign_out(name: str, entry: Mapping[str, Any] | None) -> bool:
    """Forgets the sign-in to a server, so that the next conversation to use it asks the researcher to sign in again.

    :param entry: What is kept for it, or None for a preset that has not been set up.
    :raises ValueError: If the server is not one that is signed in to, or its address cannot be read.
    :return: Whether there was a sign-in to forget.
    """
    url = sign_in_url(name, entry)
    if url is None:
        raise ValueError(f"{server_title(name, entry)} is not signed in to")

    return sign_out_mcp(url)


def check_connection(
    name: str, entry: Mapping[str, Any] | None, connect: Callable[..., MCPTools] = connect_mcp
) -> dict[str, Any]:
    """Connects to a server as a conversation would, to say whether it can be, and which tools it gives.

    The server is connected to whether or not it is on. Nobody is sent to a sign-in page: a server that is signed in to
    is connected to with the sign-in it has, and is said to need one where it has none. Nothing is called, and the
    connection is closed again.

    :param entry: What is kept for it, or None for a preset that has not been set up.
    :param connect: What connects to a server, as connect_mcp does, which is for tests.
    :return: Whether it was connected to, the names of the tools it gives, which the lead is given, and, if it was not,
        why.
    """
    title = server_title(name, entry)
    given = {key: value for key, value in (entry or {"preset": name}).items() if key not in ("enabled", "disabled")}
    failed = {"ok": False, "tools": []}
    try:
        if sign_in_kept(name, given) is False:
            return {
                **failed,
                "reason": f"{title} is not signed in to yet. A conversation that has it on asks you to sign in, "
                "when you send its first message.",
            }
        opened = connect(
            {"mcpServers": {name: given}},
            start_timeout=CHECK_TIMEOUT,
            approve=lambda request: False,
            answer=lambda question: None,
            may_sign_in=False,
        )
    except Exception as error:  # noqa: BLE001
        return {**failed, "reason": str(error) or type(error).__name__}
    try:
        return {"ok": True, "tools": [tool.name for tool in opened.tools], "reason": None}
    finally:
        opened.close()


def describe_servers(stored: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every server the settings show: the presets, in the library's order, whether or not they are set up, and then
    the person's own, in the order they were added.

    :param stored: The servers that are kept, by name.
    """
    own = [name for name in stored if name not in MCP_PRESETS]

    return [describe_server(name, stored.get(name)) for name in (*MCP_PRESETS, *own)]


def check_server_names(names: Any, stored: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """The names of servers to give a conversation, without repeats, each one that has been set up.

    :raises ValueError: If it is not a list of the names of servers that were set up.
    """
    if not isinstance(names, list | tuple):
        raise ValueError(f"The servers are a list of names, not {names!r}")
    if unknown := [name for name in names if not isinstance(name, str) or name not in stored]:
        raise ValueError(
            f"There is no server {', '.join(map(str, unknown))} set up: the servers are {', '.join(stored) or 'none'}"
        )

    return list(dict.fromkeys(names))


def servers_on(stored: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """The names of the servers that are on, which a new conversation is given."""
    return [name for name, entry in stored.items() if is_on(entry)]
