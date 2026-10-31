"""The conversations the server keeps: each in a directory of the workspace, opened when it is wanted
and kept open, with the session its code runs in, until the server stops or it is deleted.

    chats/2026-10-07_1500_what-is-a-nanobody/
        config.json     what it was set up with
        work/           where its code runs, which the files attached to it are saved in
        chat.json, messages.jsonl, events.jsonl, lab/    as Chat keeps them
"""

import asyncio
import math
import re
import shutil
import threading
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from openai import OpenAI, OpenAIError

from virtual_lab.chat import Chat, is_count
from virtual_lab.constants import (
    CHAT_FILE_NAME,
    CHAT_UPLOADS_DIR_NAME,
    MAX_CHAT_DELEGATION_ROUNDS,
    MAX_CHAT_DELEGATIONS,
    MAX_CHAT_TITLE_CHARS,
    MAX_UPLOAD_BYTES,
)
from virtual_lab.events import ChatEvent
from virtual_lab.llm import OPENROUTER_PREFIX, ModelSource, detect_source
from virtual_lab.mcp_tools import tool_prefix
from virtual_lab.openrouter import Catalog
from virtual_lab.server.asking import Asker
from virtual_lab.server.config import ChatConfig, check_limits, load_config, resolve_config, save_config
from virtual_lab.server.connections import Connections
from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.functions import function_tools
from virtual_lab.server.library import missing_keys
from virtual_lab.server.mcp import is_on, server_title
from virtual_lab.server.own import given
from virtual_lab.server.setup import Setup
from virtual_lab.server.tools import conversation_tools
from virtual_lab.server.workspace import Workspace, read_json
from virtual_lab.session import Session
from virtual_lab.utils import CostUnknownError, compute_token_cost

# What a conversation's code runs in, under its directory
WORK_DIR_NAME = "work"

# What a conversation's id may be, which is the name of its directory
CHAT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# Seconds to wait for a turn to end when a conversation is closed
CLOSE_TIMEOUT = 15.0


def text_or_none(value: Any) -> str | None:
    """What a conversation saved as text, for a list to show, or None where a file holds something else."""
    return value if isinstance(value, str) else None


def number_or_none(value: Any) -> float | None:
    """What a conversation saved as an amount, for a list to show, or None where a file holds something else."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value

    return None


class KeysNotSetError(RuntimeError):
    """Raised by the stand-in for a model whose provider's key is not set."""


class MissingKeysModel(BaseChatModel):
    """The model of a conversation that was opened to be read while the key of its model's provider is not set.

    Building the real model fails without the key, which would leave a conversation that can be read
    unreadable until it is set. A message is not sent to one that has this: the server says which keys are
    missing first, and opens the conversation again once they are set.
    """

    needs: tuple[str, ...] = ()

    @property
    def _llm_type(self) -> str:
        return "missing-keys"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "MissingKeysModel":
        return self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        raise KeysNotSetError(f"{', '.join(self.needs)} is not set")


class ChatHandle:
    """A conversation that is open: the Chat, the session its code runs in, and those following it.

    :param directory: The conversation's directory.
    :param config: What it was set up with.
    :param loop: The event loop those following it are on, which is told when anything happens.
    :param keyless: Whether it was opened with the key of its model's provider not set, so that it can be read
        but not asked anything.
    """

    def __init__(
        self, directory: Path, config: ChatConfig, loop: asyncio.AbstractEventLoop | None, keyless: bool = False
    ) -> None:
        self.directory = directory
        self.config = config
        self.id = directory.name
        self.chat: Chat
        self.session: Session | None = None
        # What connects to its MCP servers, and asks the researcher what they and their tools wait to be told, or None
        # for a conversation that has none
        self.connections: Connections | None = None
        self.keyless = keyless
        self.closed = False
        self._loop = loop
        self._waiters: set[asyncio.Event] = set()

    # Those following the conversation, who are on the event loop, are woken from whichever thread
    # something happens in, and look at the conversation for themselves

    def subscribe(self) -> asyncio.Event:
        """Registers someone following the conversation. Set when something has happened. Call it on the loop."""
        waiter = asyncio.Event()
        self._waiters.add(waiter)

        return waiter

    def unsubscribe(self, waiter: asyncio.Event) -> None:
        self._waiters.discard(waiter)

    def notify(self, event: ChatEvent | None = None) -> None:
        """Wakes everyone following the conversation. Safe from any thread, and the Chat's on_event."""
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._wake)
        except RuntimeError:
            # The loop has closed, and no one is left to tell
            pass

    def _wake(self) -> None:
        for waiter in list(self._waiters):
            waiter.set()

    @property
    def files_root(self) -> Path:
        """Where the conversation's files are, from which their paths are given: its session's directory, or,
        without a session, the conversation's own."""
        return self.chat.uploads_dir.parent

    @property
    def files_shown(self) -> tuple[str, ...] | None:
        """The parts of files_root that are shown, or None for all of it. Without a session, that is the files
        attached to the conversation, and not what it saves of itself."""
        return None if self.session is not None else (CHAT_UPLOADS_DIR_NAME,)

    def info(self) -> dict[str, Any]:
        return {**self.chat.describe(), "config": self.config.to_dict()}

    def tell(self, kind: Literal["connection", "approval", "question"], text: str = "", **data: Any) -> None:
        """Tells of what happens round the lead's work, as Chat.tell does."""
        self.chat.tell(kind, text, **data)

    def stopping(self) -> bool:
        """Whether the turn is being stopped."""
        return self.chat.state == "stopping"

    def stop(self) -> bool:
        """Ends the turn at the next point it can be, which includes the end of whatever it waits for the researcher
        to say. False if no turn is running."""
        accepted = self.chat.stop()
        if accepted and self.connections is not None:
            self.connections.asker.withdraw()

        return accepted

    def close(self) -> None:
        """Ends the turn that is running, if one is, closes the MCP servers and the session, keeping the files."""
        if self.closed:
            return
        self.closed = True
        try:
            self.chat.stop()
            # Before the turn is waited for, which something it waits to be told by the researcher would hold up
            if self.connections is not None:
                self.connections.interrupt()
            self.chat.close(timeout=CLOSE_TIMEOUT)
        finally:
            try:
                if self.connections is not None:
                    self.connections.close()
            finally:
                if self.session is not None:
                    self.session.close()
                self.notify()


class Conversations:
    """Every conversation in a workspace, and those of them that are open.

    :param workspace: Where they are kept.
    :param check_keys: Whether to say, before a conversation is made or a message sent, that the key its
        model needs is not set, rather than after something has gone wrong.
    :param client: An OpenAI client for every conversation, as Chat takes one.
    :param chat_models: Chat models for every conversation, as Chat takes them.
    :param setup: What code in Docker needs, to say before a conversation is made that it is not there, or None
        to leave that until the code is run.
    :param max_upload_bytes: The most bytes of one file that may be attached to a message.
    :param catalog: The models OpenRouter serves, whose prices a conversation that has one of them needs known to work
        out what it has cost, or None to leave that to whoever registered them.
    """

    def __init__(
        self,
        workspace: Workspace,
        check_keys: bool = True,
        client: OpenAI | None = None,
        chat_models: ModelSource | None = None,
        setup: Setup | None = None,
        max_upload_bytes: int = MAX_UPLOAD_BYTES,
        catalog: Catalog | None = None,
    ) -> None:
        self.workspace = workspace
        self.catalog = catalog
        self.check_keys = check_keys
        self.setup = setup
        self.max_upload_bytes = max_upload_bytes
        self.client = client
        self.chat_models = chat_models
        self.loop: asyncio.AbstractEventLoop | None = None
        self._open: dict[str, ChatHandle] = {}
        self._deleting: set[str] = set()
        self._lock = threading.RLock()

    def directory(self, chat_id: str) -> Path:
        """A conversation's directory, if there is one with this id."""
        with self._lock:
            deleting = chat_id in self._deleting
        if deleting or not CHAT_ID_PATTERN.fullmatch(chat_id):
            raise not_found("conversation with that id")
        directory = self.workspace.chats_dir / chat_id
        if directory.resolve().parent != self.workspace.chats_dir or not (directory / CHAT_FILE_NAME).is_file():
            raise not_found("conversation with that id")

        return directory

    def summaries(self) -> list[dict[str, Any]]:
        """Every conversation, the latest first, as a list shows them. Those that are open say what they are doing."""
        found: list[dict[str, Any]] = []
        for directory in self.workspace.chats_dir.iterdir():
            info = read_json(directory / CHAT_FILE_NAME)
            if not isinstance(info, dict):
                continue
            with self._lock:
                handle = self._open.get(directory.name)
            if handle is not None:
                state = handle.chat.state
            else:
                # A conversation not open is not running, so one saved as running was cut off
                state = "interrupted" if info.get("running") else "idle"
            config = load_config(directory)
            found.append(
                {
                    "id": directory.name,
                    "title": info["title"] if isinstance(info.get("title"), str) else "",
                    "created_at": text_or_none(info.get("created_at")),
                    "updated_at": text_or_none(info.get("updated_at")),
                    "state": state,
                    "turns": info["turns"] if is_count(info.get("turns")) else 0,
                    "spent": number_or_none(info.get("spent")),
                    "max_cost": number_or_none(info.get("max_cost")),
                    "model": config.model if config is not None else None,
                }
            )

        return sorted(found, key=lambda item: (item["updated_at"] or "", item["id"]), reverse=True)

    def create(self, request: Mapping[str, Any], title: str | None = None) -> ChatHandle:
        """Makes a conversation and opens it.

        :param request: What it is set up with, as resolve_config takes it.
        :param title: What to call it; by default its first message.
        :raises ApiError: If something chosen cannot be used, a key is not set, or code is to run in Docker and
            Docker or the image is not there.
        """
        title = " ".join((title or "").split())[:MAX_CHAT_TITLE_CHARS] or None
        try:
            config = resolve_config(request, self.workspace.load_settings(), self.workspace)
        except (ValueError, TypeError) as error:
            raise ApiError(422, "invalid", str(error)) from error
        self.require_keys(config)
        self.require_setup(config)

        directory = self.workspace.new_chat_directory(title or "New chat")
        try:
            save_config(directory, config)
            handle = self._start(directory, config, title)
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        with self._lock:
            self._open[handle.id] = handle

        return handle

    def get(self, chat_id: str) -> ChatHandle:
        """A conversation, opened if it is not.

        :raises ApiError: If there is none with this id, or it cannot be opened.
        """
        with self._lock:
            handle = self._open.get(chat_id)
            if handle is not None and not (handle.keyless and not self.missing_keys(handle.config)):
                return handle

            directory = self.directory(chat_id)
            config = load_config(directory)
            if config is None:
                raise ApiError(409, "unreadable", "This conversation's setup cannot be read, so it cannot be opened")
            reopened = self._start(directory, config, None, keyless=bool(self.missing_keys(config)))
            self._open[chat_id] = reopened

        # Its keys have been set since it was opened without them, so those following it are told it is
        # over and open it again, with no event missed, since the new one carries on from the same events
        if handle is not None:
            handle.close()

        return reopened

    def ready(self, chat_id: str) -> ChatHandle:
        """A conversation, opened to be asked something.

        :raises ApiError: If there is none with this id, it cannot be opened, or a key its model needs is not set.
        """
        handle = self.get(chat_id)
        self.require_keys(handle.config)
        if handle.keyless:
            # The keys were set between opening it and looking, so it is opened again with them
            handle = self.get(chat_id)

        return handle

    def switch_model(self, chat_id: str, model: str) -> ChatHandle:
        """Has a conversation go on with another model, from where it is: what was said is kept, and the lead and the
        team answer with the new model from now on. Its files stay, and code that was running starts afresh.

        :raises ApiError: If there is no such conversation, it is working, the model cannot be used, a key it needs is
            not set, or the conversation cannot be opened with it, in which case it goes on as it was.
        """
        model = model.strip()
        try:
            detect_source(model)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error
        # Before the lock is taken, since reading the prices can wait on the network
        self.know_prices(model)
        with self._lock:
            handle = self.get(chat_id)
            if handle.chat.state != "idle":
                raise ApiError(
                    409, "busy", "The conversation is working. Change its model once it has finished, or stop it first."
                )
            config = handle.config
            if model == config.model:
                return handle
            changed = replace(config, model=model)
            self.require_keys(changed)
            if config.max_cost is not None:
                try:
                    compute_token_cost(model, 0, 0)
                except CostUnknownError as error:
                    raise ApiError(
                        422,
                        "unavailable",
                        f"{error}, so this conversation's spending limit cannot be enforced with it. Choose a model "
                        f"that is priced, or start a conversation with no limit.",
                    ) from error
            directory = handle.directory
            handle.close()
            try:
                save_config(directory, changed)
                reopened = self._start(directory, changed, None)
            except BaseException:
                self._reopen_as_it_was(chat_id, directory, config)
                raise
            self._open[chat_id] = reopened

        return reopened

    def set_limits(self, chat_id: str, changes: Mapping[str, Any]) -> ChatHandle:
        """Changes what a conversation may spend, and how much of the team's time the lead may ask for: the most
        team sessions it may start in answering a message, and the most rounds it may ask one for. It goes on as it is,
        with no change to what was said or the code that is running, and it can be done while it is working.

        :param changes: What to change, which is any of max_cost (null for no limit), max_delegations, and max_rounds
            (null for what the lead is given unless it is told otherwise). What is not given is left as it was.
        :raises ApiError: If there is no such conversation, a limit is not valid, or a spending limit is asked for and
            the model is not priced.
        """
        try:
            checked = check_limits(changes)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error
        handle = self.get(chat_id)
        with self._lock:
            config = handle.config
            changed = replace(config, **checked)
            allowed = {
                "max_delegations": MAX_CHAT_DELEGATIONS if changed.max_delegations is None else changed.max_delegations,
                "max_rounds": MAX_CHAT_DELEGATION_ROUNDS if changed.max_rounds is None else changed.max_rounds,
            }
            try:
                handle.chat.set_limits(
                    **({"max_cost": changed.max_cost} if "max_cost" in checked else {}),
                    **{key: value for key, value in allowed.items() if key in checked},
                )
            except CostUnknownError as error:
                raise ApiError(
                    422,
                    "unavailable",
                    f"{error}, so this conversation's spending limit cannot be enforced with it. Choose a model "
                    f"that is priced, or start a conversation with no limit.",
                ) from error
            except ValueError as error:
                raise ApiError(422, "invalid", str(error)) from error
            handle.config = changed
            save_config(handle.directory, changed)

        return handle

    def _reopen_as_it_was(self, chat_id: str, directory: Path, config: ChatConfig) -> None:
        """Opens a conversation again with the setup it had, after a change of it could not be made."""
        try:
            save_config(directory, config)
            self._open[chat_id] = self._start(directory, config, None, keyless=bool(self.missing_keys(config)))
        except Exception:
            # What is not open is opened when it is next asked for, with what is saved, and told why not if it cannot be
            self._open.pop(chat_id, None)

    def know_prices(self, model: str) -> None:
        """Has what a model costs known, where it is one OpenRouter serves, whose prices are read from there."""
        if (
            self.catalog is not None
            and self.client is None
            and self.chat_models is None
            and model.startswith(OPENROUTER_PREFIX)
        ):
            self.catalog.ensure_prices()

    def delete(self, chat_id: str) -> None:
        """Stops a conversation, if it is running, and removes it and everything it saved."""
        with self._lock:
            directory = self.directory(chat_id)
            handle = self._open.pop(chat_id, None)
            # Until it is gone, it cannot be opened again, which would leave a conversation open on nothing
            self._deleting.add(chat_id)
        try:
            if handle is not None:
                handle.close()
            shutil.rmtree(directory)
        finally:
            with self._lock:
                self._deleting.discard(chat_id)

    def close(self) -> None:
        """Closes every conversation that is open, which the server does as it stops."""
        with self._lock:
            handles = list(self._open.values())
            self._open.clear()
        for handle in handles:
            handle.close()

    def missing_keys(self, config: ChatConfig) -> list[str]:
        """The variables its model's provider needs that are not set, which are none when keys are not checked
        or the conversation's models are given."""
        return self.missing_keys_for(config.model)

    def missing_keys_for(self, model: str) -> list[str]:
        """The variables a model's provider needs that are not set, which are none when keys are not checked or
        models are given."""
        if not self.check_keys or self.client is not None or self.chat_models is not None:
            return []

        return missing_keys([model])

    def require_keys(self, config: ChatConfig) -> None:
        """Says what is missing before something that spends is done, rather than after it has gone wrong.

        :raises ApiError: If a key the model needs is not set.
        """
        if missing := self.missing_keys(config):
            raise ApiError(
                422,
                "missing_keys",
                f"{config.model} needs {', '.join(missing)}, which is not set. Add it in the settings.",
                missing=missing,
            )

    def require_setup(self, config: ChatConfig) -> None:
        """Says what code cannot run without before a conversation is made, rather than when it first runs.

        :raises ApiError: If code is to run in Docker and Docker is not running or the image is not built.
        """
        if self.setup is None:
            return
        if issues := self.setup.missing(config):
            raise ApiError(
                409,
                "setup_needed",
                " ".join(issue["message"] for issue in issues),
                missing=[issue["id"] for issue in issues],
            )

    def _start(self, directory: Path, config: ChatConfig, title: str | None, keyless: bool = False) -> ChatHandle:
        self.know_prices(config.model)
        handle = ChatHandle(directory, config, self.loop, keyless)
        data, software = given(self.workspace, config.data, config.software)
        session = config.code.session(directory / WORK_DIR_NAME, data=data, software=software)
        chat_models = MissingKeysModel(needs=tuple(self.missing_keys(config))) if keyless else self.chat_models
        available = conversation_tools(directory, session.directory if session is not None else None)
        chosen = tuple(available[name] for name in config.tools if name in available)
        # Those still set up and on, and not those it was begun with that have been turned off since, which may be why
        # it is being opened again
        stored = self.workspace.load_mcp_servers()
        servers = {name: stored[name] for name in config.mcp if name in stored and is_on(stored[name])}
        # What the person had it write from papers, which runs where the code does, and so only where there is some
        written = function_tools(
            self.workspace,
            config.functions,
            session,
            {tool.name for tool in chosen},
            [f"{tool_prefix(name)}_" for name in servers],
        )
        if servers and not keyless:
            asker = Asker(handle.tell, handle.stopping, lambda name: server_title(name, servers.get(name)))
            handle.connections = Connections(servers, handle.tell, handle.stopping, asker)
        try:
            handle.chat = Chat(
                directory,
                config.lead_agent(),
                config.team_agents(),
                session=session,
                client=self.client,
                chat_models=chat_models,
                title=title,
                tools=(*chosen, *written),
                late_tools=handle.connections.tools if handle.connections is not None else None,
                max_cost=config.max_cost,
                max_delegations=MAX_CHAT_DELEGATIONS if config.max_delegations is None else config.max_delegations,
                max_rounds=MAX_CHAT_DELEGATION_ROUNDS if config.max_rounds is None else config.max_rounds,
                stream=config.stream,
                resources=config.code.resources if session is not None else "none",
                commercial_mode=config.commercial_mode,
                max_upload_bytes=self.max_upload_bytes,
                on_event=handle.notify,
            )
        except (ValueError, CostUnknownError, OpenAIError, ImportError) as error:
            if session is not None:
                session.close()
            raise ApiError(422, "unavailable", str(error)) from error
        handle.session = session

        return handle
