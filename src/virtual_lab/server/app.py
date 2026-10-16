"""The server's application: what a page asks of the lab, and what the lab tells it.

Every route is under /api and answers in JSON, and errors do too, in one shape:
{"error": {"code": ..., "message": ...}}. The conversation's events come as server-sent events,
and everything else is a request and an answer.

    GET    /api/health                  that the server is there, which needs no token
    GET    /api/settings, PATCH         what a new conversation starts with, and the largest file it can be sent
    GET    /api/models                  the models to choose from, and whether they can be reached
    GET    /api/keys                    which providers have their keys
    PUT    /api/keys/{name}, DELETE     a key, set until the server stops, or taken away
    GET    /api/setup                   Docker, the sandbox images, the data lake, the jobs, and what is left to do
    POST   /api/setup/images/{stage}    start building a stage of the sandbox image, as a job
    GET    /api/setup/data-lake         the files of the data lake, and which are there; POST fetches them, as a job
    GET    /api/setup/jobs              the jobs; /jobs/{id} is one, with what it printed from ?log_from=
    POST   /api/setup/jobs/{id}/stop    ask a job to stop
    GET    /api/scientists, PUT         the library and the scientists the person described
    DELETE /api/scientists/{title}      one of those the person described
    GET    /api/tools, PUT              the library's tools a conversation can be given, and which are turned off
    GET    /api/own                     the data and software the person gave the lab to use in every conversation
    POST   /api/own/data/files          a file to give, as the body, with ?name= and ?description=
    POST   /api/own/data/paths          a file or folder to give where it is on this machine
    PATCH  /api/own/data/{name}         say again what it is; DELETE gives it up, deleting it only if it was uploaded
    GET    /api/own/data/{name}/preview what is at the start of it
    PUT    /api/own/software            some software to give, and what it is for; DELETE /software/{name} gives it up
    GET    /api/papers                  the runs that read papers, and what a page needs to make one
    POST   /api/papers/runs             a run, whose papers are uploaded, in a folder on this machine, or from bioRxiv
    GET    /api/papers/runs/{id}        one run, with each paper and what they share; DELETE deletes it
    POST   /api/papers/runs/{id}/files  a paper to upload to it, as the body, named by ?name=; DELETE /files/{name}
    POST   /api/papers/runs/{id}/read   read its papers, as a job, with the most it may spend; again to carry on
    GET    /api/papers/runs/{id}/tables/{kind}   what was found, as a table to open in a spreadsheet
    POST   /api/papers/runs/{id}/functions   write functions for the tasks the papers share, as a job
    GET    /api/papers/runs/{id}/functions/{name}   one function, with its code; DELETE takes it away
    PATCH  /api/papers/runs/{id}        whether its functions are given to the conversations that are made from now on
    GET    /api/benchmarks              the runs that answer Biomni's benchmarks, and whether their files are there
    POST   /api/benchmarks/files        fetch the benchmarks' files
    POST   /api/benchmarks/runs         a run: a benchmark, put to the lead alone or to the team
    GET    /api/benchmarks/runs/{id}    one run, with how each question was answered; DELETE deletes it
    POST   /api/benchmarks/runs/{id}/start   answer its questions, as a job, with the most it may spend
    GET    /api/benchmarks/runs/{id}/questions/{task}/{number}   one question, with its answer and what was said
    GET    /api/projects                the research projects, and what a page needs to make one
    POST   /api/projects                a project: a goal for the lead to carry out, with a team, a plan, and a critic
    GET    /api/projects/{id}           one project, with its team, plan, rounds, findings, and steps; DELETE deletes it
    POST   /api/projects/{id}/start     work on it, as a job, with the most it may spend; again to carry on
    GET    /api/projects/{id}/steps/{name}   one step, with what it produced and what was said or run in it
    GET    /api/projects/{id}/report    the report of how it ended, as a document to save
    GET    /api/mcp                     the MCP servers: the presets, and those the person set up, and what each needs
    PUT    /api/mcp/servers/{name}      set a server up in full, or replace it, DELETE forgets it
    PATCH  /api/mcp/servers/{name}      turn it on or off, or choose how a preset is signed in to
    POST   /api/mcp/servers/{name}/check   connect to it, to say whether it can be and which tools it gives
    DELETE /api/mcp/servers/{name}/sign-in   forget the sign-in to it, so that the next conversation asks for one
    GET    /api/chats, POST             the conversations, and a new one
    GET    /api/chats/{id}              one conversation, which PATCH renames and DELETE removes
    POST   /api/chats/{id}/messages     a message for the lead, which is answered in the background, and
                                        which with replace_last takes the place of the last one
    POST   /api/chats/{id}/note         a note for the lead or the team, which they read as they work
    POST   /api/chats/{id}/pause        also resume and stop, steering the turn that is running
    POST   /api/chats/{id}/approvals/{request}   allow or decline a call that waits for it, which the events tell of
    POST   /api/chats/{id}/questions/{request}   answer or decline what an MCP server asks, which the events tell of
    GET    /api/chats/{id}/events       the events of the conversation, as they happen
    POST   /api/chats/{id}/uploads      a file for the conversation, as the body, named by ?name=
    GET    /api/chats/{id}/files        what the conversation made or was given, and /files/{path} one of them
    GET    /api/chats/{id}/export       the conversation to save, as ?format=html (the default), pdf, or ipynb
"""

import asyncio
import logging
import os
import threading
from collections.abc import AsyncIterator, Collection, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, BinaryIO, Literal, cast

import anyio.to_thread
from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect

from virtual_lab.__about__ import __version__
from virtual_lab.chat import ChatBusyError, ChatClosedError, UploadTooLargeError
from virtual_lab.constants import BIOMNI_RELEASE_URL, MAX_CHAT_TITLE_CHARS, MAX_UPLOAD_BYTES
from virtual_lab.environment import DATA_LAKE
from virtual_lab.export import PDFExportError, make_pdf
from virtual_lab.export_chat import chat_html
from virtual_lab.export_notebook import chat_notebook, notebook_text
from virtual_lab.mcp_presets import MCP_PRESETS
from virtual_lab.server.asking import not_waiting
from virtual_lab.server.benchmarks import BenchmarkRuns
from virtual_lab.server.config import describe_models, library, public_settings, update_settings
from virtual_lab.server.conversations import Conversations
from virtual_lab.server.errors import ApiError, file_error, not_found
from virtual_lab.server.files import download_headers, file_response, list_files, resolve_inside
from virtual_lab.server.keychain import Keychain, KeychainError, recall
from virtual_lab.server.library import SETTABLE_KEYS, provider_statuses
from virtual_lab.server.mcp import (
    MAX_SERVERS,
    change_entry,
    check_connection,
    check_entry,
    describe_servers,
    server_title,
    service_keys,
    sign_out,
)
from virtual_lab.server.own import MAX_DESCRIPTION_CHARS, MAX_OWN_ITEMS, MAX_SOFTWARE_NAME_CHARS, Own
from virtual_lab.server.papers import DEFAULT_FUNCTIONS, MAX_FUNCTIONS, MAX_MIN_PAPERS, MAX_TITLE_CHARS, Papers
from virtual_lab.server.projects import MAX_GOAL_CHARS, Projects
from virtual_lab.server.security import LOCAL_HOSTS, Guard, policy_of_file
from virtual_lab.server.setup import Setup
from virtual_lab.server.stream import follow
from virtual_lab.server.tools import check_tool_names, describe_tools
from virtual_lab.server.workspace import DEFAULT_WORKSPACE, Settings, Workspace

# The most characters of a message, which no one writes by hand
# Where the server's own messages go, which the server shows as it runs
LOG = logging.getLogger("uvicorn.error")

MAX_MESSAGE_CHARS = 200_000

# Seconds the server waits for the next part of a file that is being uploaded
UPLOAD_CHUNK_TIMEOUT = 120.0

# What a key may be at most, and the characters it may not hold, which an environment variable cannot
MAX_KEY_CHARS = 4096

# The most characters of a path a page may give
MAX_PATH_CHARS = 4096

# The most tools a request may name, which is more than there are
MAX_TOOLS = 64

# What a page of the interface is given to keep: what has a hash in its name never changes
IMMUTABLE_PREFIX = "_next/static/"

# What a page is told when a conversation cannot be saved as a PDF, which is so where WeasyPrint is not installed
PDF_UNAVAILABLE = (
    "A PDF cannot be made on this machine, because WeasyPrint and the Pango library it draws text with are not "
    "installed. Save the page instead, and print it to a PDF from the browser."
)


class RequestModel(BaseModel):
    """What the body of a request is: nothing may be in it that is not asked for."""

    model_config = ConfigDict(extra="forbid")


class ScientistBody(RequestModel):
    title: str = Field(min_length=1, max_length=200)
    expertise: str = Field(min_length=1, max_length=4000)
    goal: str = Field(min_length=1, max_length=4000)
    role: str = Field(min_length=1, max_length=4000)


class CodeBody(RequestModel):
    where: str = "none"
    sandbox: str = "python"
    network: bool = True
    python: str = ""
    resources: str = "retrieve"
    data_lake: str = Field("", max_length=MAX_PATH_CHARS)
    forward_env: list[str] = Field(default_factory=list, max_length=len(SETTABLE_KEYS))


class ChatBody(RequestModel):
    """A new conversation. What is left out is what the settings say, or the library's lead and team."""

    title: str | None = Field(None, max_length=500)
    model: str = ""
    lead: str | ScientistBody | None = None
    team: list[str | ScientistBody] | None = None
    code: CodeBody | None = None
    max_cost: float | None = None
    stream: bool | None = None
    commercial_mode: bool = False
    tools: list[str] | None = Field(None, max_length=MAX_TOOLS)
    mcp: list[str] | None = Field(None, max_length=MAX_SERVERS)
    data: list[str] | None = Field(None, max_length=MAX_OWN_ITEMS)
    software: list[str] | None = Field(None, max_length=MAX_OWN_ITEMS)


class SettingsBody(RequestModel):
    model: str = ""
    stream: bool = True
    max_cost: float | None = None
    code: str = "none"
    sandbox: str = "python"
    network: bool = True
    python: str = ""
    data_lake: str = Field("", max_length=MAX_PATH_CHARS)
    forward_keys: list[str] = Field(default_factory=list, max_length=len(SETTABLE_KEYS))


class ToolsBody(RequestModel):
    """The tools a new conversation is not given, which are none until some are turned off."""

    disabled: list[str] = Field(default_factory=list, max_length=MAX_TOOLS)


class OwnPathBody(RequestModel):
    """A file or folder on this machine to give the lab, and what it is."""

    path: str = Field(min_length=1, max_length=MAX_PATH_CHARS)
    description: str = Field(max_length=MAX_DESCRIPTION_CHARS * 4)


class OwnDescriptionBody(RequestModel):
    description: str = Field(max_length=MAX_DESCRIPTION_CHARS * 4)


class OwnSoftwareBody(RequestModel):
    name: str = Field(min_length=1, max_length=MAX_SOFTWARE_NAME_CHARS * 4)
    description: str = Field(max_length=MAX_DESCRIPTION_CHARS * 4)


class PapersSourceBody(RequestModel):
    """Where a run's papers come from. Which of these are asked for depends on the kind, and the server says which."""

    kind: str = Field(max_length=20)
    path: str | None = Field(None, max_length=MAX_PATH_CHARS)
    recursive: StrictBool | None = None
    since: str | None = Field(None, max_length=20)
    until: str | None = Field(None, max_length=20)
    subject: str | None = Field(None, max_length=100)
    limit: StrictInt | None = None
    random: StrictBool | None = None
    include_unpublished: StrictBool | None = None


class PapersRunBody(RequestModel):
    title: str = Field(max_length=MAX_TITLE_CHARS * 4)
    source: PapersSourceBody


class PapersReadBody(RequestModel):
    """How much reading a run's papers may cost, which is always said, and whether to read again those that failed."""

    max_cost: float = Field(strict=True, ge=0, allow_inf_nan=False)
    max_cost_per_paper: float | None = Field(None, strict=True, ge=0, allow_inf_nan=False)
    retry_failed: StrictBool = False


class PapersFunctionsBody(RequestModel):
    """What writing functions for the tasks a run's papers share may cost, which is always said, and which tasks."""

    max_cost: float = Field(strict=True, ge=0, allow_inf_nan=False)
    max_cost_per_function: float | None = Field(None, strict=True, ge=0, allow_inf_nan=False)
    min_papers: StrictInt = Field(1, ge=1, le=MAX_MIN_PAPERS)
    limit: StrictInt = Field(DEFAULT_FUNCTIONS, ge=1, le=MAX_FUNCTIONS)
    retry_failed: StrictBool = False
    verify: StrictBool = False


class PapersGiveBody(RequestModel):
    given: StrictBool


class BenchmarkRunBody(RequestModel):
    """A run of a benchmark. Which options are asked for depends on the benchmark, and the server says which."""

    title: str = Field(max_length=MAX_TITLE_CHARS * 4)
    benchmark: str = Field(max_length=100)
    solver: str = Field("single", max_length=100)
    rounds: StrictInt | None = None
    limit: StrictInt | None = None
    tasks: list[str] | None = Field(None, max_length=100)
    subset: str | None = Field(None, max_length=100)
    leave_out_images: StrictBool | None = None


class BenchmarkStartBody(RequestModel):
    """How much answering a run's questions may cost, which is always said, and whether to ask the failed ones again."""

    max_cost: float = Field(strict=True, ge=0, allow_inf_nan=False)
    max_cost_per_question: float | None = Field(None, strict=True, ge=0, allow_inf_nan=False)
    retry_failed: StrictBool = False


class ProjectBody(RequestModel):
    """A research project: a goal, and how its team is chosen and what its steps are given."""

    goal: str = Field(max_length=MAX_GOAL_CHARS * 2)
    title: str | None = Field(None, max_length=MAX_TITLE_CHARS * 4)
    team: str = Field("chosen", max_length=100)
    max_team_size: StrictInt | None = None
    meeting_rounds: StrictInt | None = None
    memory: str = Field("pick", max_length=100)
    findings_per_step: StrictInt | None = None


class ProjectStartBody(RequestModel):
    """How much working on a project may cost in all, which is always said, and the rounds it may take."""

    max_cost: float = Field(strict=True, ge=0, allow_inf_nan=False)
    max_rounds: StrictInt | None = None
    max_stalled_rounds: StrictInt | None = None


class McpServerBody(RequestModel):
    """How to reach an MCP server, as a config gives it, or {"preset": ...} for one of the library's."""

    entry: dict[str, Any]


class McpChangeBody(RequestModel):
    """A change to a server that is set up, or is a preset: any of these, and what is not given is left as it is."""

    enabled: StrictBool | None = None
    auth: Literal["key", "oauth"] | None = None


class ApprovalBody(RequestModel):
    # Strictly true or false: a call is not to be made because a word was read as a yes
    allow: StrictBool


class AnswerBody(RequestModel):
    """What an MCP server asked: the form's fields by name, or {} for what was answered at a web page; null declines."""

    answer: dict[str, Any] | None


class RenameBody(RequestModel):
    title: str = Field(min_length=1, max_length=500)


class MessageBody(RequestModel):
    text: str = Field("", max_length=MAX_MESSAGE_CHARS)
    attachments: list[str] = Field(default_factory=list, max_length=100)
    replace_last: bool = False


class NoteBody(RequestModel):
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class KeyBody(RequestModel):
    value: str = Field(max_length=MAX_KEY_CHARS)
    # Whether to keep it in the keychain, or only until the server stops; None is as the keychain allows
    remember: bool | None = None


class DataLakeBody(RequestModel):
    """What to fetch of the data lake, which is all of it unless files are named."""

    names: list[str] | None = Field(None, max_length=len(DATA_LAKE))


class RequestBodyReader:
    """The body of a request, read from a worker thread as it arrives, so that a file is never held whole
    and the server goes on answering others while it comes.

    :param request: The request.
    :param loop: The event loop the request is being received on.
    """

    def __init__(self, request: Request, loop: asyncio.AbstractEventLoop) -> None:
        self._chunks = request.stream().__aiter__()
        self._loop = loop
        self._pending = b""
        self._done = False

    async def _next(self) -> bytes | None:
        try:
            return await self._chunks.__anext__()
        except StopAsyncIteration:
            return None

    def read(self, size: int = -1) -> bytes:
        """Up to size bytes, or all that is left if size is negative."""
        while (size < 0 or len(self._pending) < size) and not self._done:
            try:
                chunk = asyncio.run_coroutine_threadsafe(self._next(), self._loop).result(UPLOAD_CHUNK_TIMEOUT)
            except TimeoutError as error:
                raise ApiError(408, "timeout", "The file stopped arriving") from error
            if chunk is None:
                self._done = True
            else:
                self._pending += chunk
        if size < 0:
            size = len(self._pending)
        data, self._pending = self._pending[:size], self._pending[size:]

        return data


def validation_error(error: RequestValidationError) -> ApiError:
    fields = [
        {"field": ".".join(str(part) for part in item["loc"] if part != "body"), "message": item["msg"]}
        for item in error.errors()
    ]
    message = "; ".join(f"{item['field']}: {item['message']}" if item["field"] else item["message"] for item in fields)

    return ApiError(422, "invalid", message, fields=fields)


def last_event(header: str | None) -> int:
    """The number of the last event a page saw, as the browser sends it when it opens a stream again."""
    try:
        return max(int(header or 0), 0)
    except ValueError:
        return 0


def static_file(root: Path, path: str) -> Path | None:
    """The page or file of the interface that a path is: itself, or a page by its name, if there is one."""
    if "\x00" in path or ".." in Path(path).parts:
        return None
    resolved = root.resolve()
    candidates = (path, f"{path}.html", f"{path}/index.html") if path else ("index.html",)
    for candidate in candidates:
        found = (resolved / candidate).resolve()
        if found.is_relative_to(resolved) and found.is_file():
            return found

    return None


def create_app(
    workspace: Path | str = DEFAULT_WORKSPACE,
    token: str | None = None,
    allowed_hosts: Collection[str] = LOCAL_HOSTS,
    static_dir: Path | str | None = None,
    check_keys: bool = True,
    client: Any = None,
    chat_models: Any = None,
    check_setup: bool = True,
    docker_command: Sequence[str] = ("docker",),
    release_url: str = BIOMNI_RELEASE_URL,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
    keychain: Keychain | None = None,
) -> FastAPI:
    """The server's application.

    Anyone who can reach it can spend on the keys of whoever started it and, where code runs, run code on
    their machine, so it is for one person: see virtual_lab.server.security for what it turns away.

    :param workspace: Where conversations and settings are kept.
    :param token: What the API wants from every request but the health check, or None to want none, which is
        for tests.
    :param allowed_hosts: The names the server may be reached by.
    :param static_dir: The built pages of the interface, to serve, with any address that is not a file or the
        API's showing its first page, or None to serve none.
    :param check_keys: Whether to say a key is not set before something is paid for, as Conversations does.
    :param client: An OpenAI client for every conversation, as Chat takes one.
    :param chat_models: Chat models for every conversation, as Chat takes them.
    :param check_setup: Whether to say Docker or the sandbox image is not there before a conversation that runs
        code in Docker is made, rather than when its code first runs.
    :param docker_command: How the setup invokes Docker, which is for tests: code runs with "docker".
    :param release_url: Where the data lake is fetched from, which is for tests.
    :param max_upload_bytes: The most bytes of one file that may be attached to a message, which the settings tell
        the interface, so that it does not send a file the server would turn away.
    :param keychain: Where the keys a person gives are kept, so that they are there when the server is started
        again, and are read from now, or None to keep them only until the server stops. It is never the machine's
        own unless it is given: virtual_lab.server.serve gives it.
    """
    store = Workspace(Path(workspace))
    setup = Setup(store, docker_command, release_url)
    conversations = Conversations(
        store,
        check_keys=check_keys,
        client=client,
        chat_models=chat_models,
        setup=setup if check_setup else None,
        max_upload_bytes=max_upload_bytes,
    )
    own = Own(store, max_upload_bytes)
    papers = Papers(
        store,
        setup.jobs,
        max_upload_bytes,
        conversations.missing_keys_for,
        client=client,
        chat_models=chat_models,
        docker_missing=setup.missing_for if check_setup else None,
    )
    benchmarks = BenchmarkRuns(
        store,
        setup.jobs,
        conversations.missing_keys_for,
        client=client,
        chat_models=chat_models,
        docker_missing=setup.missing_for if check_setup else None,
    )
    projects = Projects(
        store,
        setup.jobs,
        conversations.missing_keys_for,
        client=client,
        chat_models=chat_models,
        docker_missing=setup.missing_for if check_setup else None,
    )
    vault = keychain if keychain is not None else Keychain.missing()
    # How each key the server has was given it: "keychain", or "session" for one kept only until the server stops; a
    # key that is not here was in the environment the server was started with
    kept: dict[str, str] = {}
    recalled, unread = recall(vault, (*SETTABLE_KEYS, *service_keys()))
    kept.update(dict.fromkeys(recalled, "keychain"))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        conversations.loop = asyncio.get_running_loop()
        try:
            yield
        finally:
            await anyio.to_thread.run_sync(conversations.close)
            await anyio.to_thread.run_sync(setup.close)

    app = FastAPI(
        title="Virtual Lab", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.conversations = conversations
    app.state.setup = setup
    app.state.workspace = store
    app.state.benchmarks = benchmarks
    app.state.projects = projects

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(error.body(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        return await api_error(request, validation_error(error))

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed"}
        messages = {404: "There is no such address", 405: "That address does not take this kind of request"}
        message = messages.get(error.status_code, str(error.detail))
        body = ApiError(error.status_code, codes.get(error.status_code, "error"), message).body()

        return JSONResponse(body, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(OSError)
    async def file_trouble(request: Request, error: OSError) -> JSONResponse:
        problem = file_error(error)
        if problem is None:
            # Left to be what it was, and to be logged as any other is
            raise error
        # What a page is told is all there is to say of it, so this is what the log has
        LOG.warning("%s %s: %s", request.method, request.url.path, problem.message)

        return await api_error(request, problem)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        # What went wrong is in the server's log, where Starlette puts it, and not in what a page is told
        body = ApiError(500, "internal", "Something went wrong in the server. Its log says what.").body()

        return JSONResponse(body, status_code=500)

    api = APIRouter(prefix="/api")

    @api.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    def settings_view(settings: Settings) -> dict[str, Any]:
        return {**public_settings(settings), "workspace": str(store.root), "max_upload_bytes": max_upload_bytes}

    @api.get("/settings")
    def get_settings() -> dict[str, Any]:
        return settings_view(store.load_settings())

    @api.patch("/settings")
    def change_settings(body: SettingsBody) -> dict[str, Any]:
        try:
            changed = update_settings(store.load_settings(), body.model_dump(exclude_unset=True), store)
        except (ValueError, TypeError) as error:
            raise ApiError(422, "invalid", str(error)) from error
        store.save_settings(changed)

        return settings_view(changed)

    @api.get("/models")
    def get_models() -> dict[str, Any]:
        return {"default": store.load_settings().model, "models": describe_models()}

    def key_statuses(problem: str | None = None) -> dict[str, Any]:
        """What the keys are, without any of them. A problem is what went wrong with the keychain in a change that
        was otherwise made."""
        return {
            "settable": list(SETTABLE_KEYS),
            "providers": [
                {
                    "provider": status.provider,
                    "variables": list(status.variables),
                    "missing": list(status.missing),
                    "ready": status.ready,
                }
                for status in provider_statuses()
            ],
            "keychain": {
                "available": vault.available,
                "name": vault.name if vault.available else None,
                "problem": unread or (None if vault.available else vault.problem),
            },
            "sources": {
                name: kept.get(name, "environment")
                for name in (*SETTABLE_KEYS, *service_keys())
                if os.environ.get(name)
            },
            "problem": problem,
        }

    @api.get("/keys")
    def get_keys() -> dict[str, Any]:
        return key_statuses()

    @api.put("/keys/{name}")
    def set_key(name: str, body: KeyBody) -> dict[str, Any]:
        # The keys of the services the MCP presets reach are given the same way, and nothing else is: a name that is
        # not one of these is not a variable the process may be told to change
        if name not in (*SETTABLE_KEYS, *service_keys()):
            raise ApiError(422, "invalid", f"A key is one of {', '.join((*SETTABLE_KEYS, *service_keys()))}")
        value = body.value.strip()
        if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ApiError(422, "invalid", "A key is on one line, with nothing else in it")
        # It is never told to a page. It is kept in the keychain if that is wanted, and for the rest of this process
        # in any case
        os.environ[name] = value
        remember = body.remember if body.remember is not None else vault.available
        problem = None
        try:
            if remember:
                vault.write(name, value)
            elif vault.available:
                # A key kept earlier would come back, in place of this one, when the server is started again
                vault.erase(name)
        except KeychainError as error:
            problem = f"The key is set until the server stops. {error}"
        kept[name] = "keychain" if remember and problem is None else "session"

        return key_statuses(problem)

    @api.delete("/keys/{name}")
    def remove_key(name: str) -> dict[str, Any]:
        if name not in (*SETTABLE_KEYS, *service_keys()):
            raise ApiError(422, "invalid", f"A key is one of {', '.join((*SETTABLE_KEYS, *service_keys()))}")
        os.environ.pop(name, None)
        problem = None
        if vault.available:
            try:
                vault.erase(name)
            except KeychainError as error:
                problem = f"The key is taken away until the server is started again, and may be back then. {error}"

        return key_statuses(problem)

    @api.get("/setup")
    def get_setup() -> dict[str, Any]:
        return setup.status(store.load_settings())

    @api.post("/setup/images/{target}", status_code=202)
    def build_image(target: str) -> dict[str, Any]:
        return setup.build_image(target).snapshot(0)

    @api.get("/setup/data-lake")
    def get_data_lake() -> dict[str, Any]:
        settings = store.load_settings()

        return {"data_lake": setup.data_lake(settings), "files": setup.data_lake_files(settings)}

    @api.post("/setup/data-lake", status_code=202)
    def fetch_data_lake(body: DataLakeBody | None = None) -> dict[str, Any]:
        names = body.names if body is not None else None

        return setup.download_data_lake(store.load_settings(), names).snapshot(0)

    @api.get("/setup/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": setup.jobs.snapshots()}

    @api.get("/setup/jobs/{job_id}")
    def get_job(job_id: str, log_from: int = Query(0, ge=0)) -> dict[str, Any]:
        try:
            return setup.jobs.get(job_id).snapshot(log_from)
        except KeyError:
            raise not_found("job with that id") from None

    @api.post("/setup/jobs/{job_id}/stop")
    def stop_job(job_id: str) -> dict[str, Any]:
        try:
            return setup.jobs.stop(job_id).snapshot(0)
        except KeyError:
            raise not_found("job with that id") from None

    @api.get("/scientists")
    def get_scientists() -> dict[str, Any]:
        return {"scientists": library(store)}

    @api.put("/scientists")
    def save_scientist(body: ScientistBody) -> dict[str, Any]:
        try:
            store.save_scientist(body.model_dump())
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error

        return {"scientists": library(store)}

    @api.delete("/scientists/{title:path}")
    def remove_scientist(title: str) -> dict[str, Any]:
        if not any(item["title"].casefold() == title.casefold() for item in store.load_scientists()):
            raise not_found("scientist of yours with that title")
        store.remove_scientist(title)

        return {"scientists": library(store)}

    @api.get("/tools")
    def get_tools() -> dict[str, Any]:
        return {"tools": describe_tools(store.load_disabled_tools())}

    @api.put("/tools")
    def change_tools(body: ToolsBody) -> dict[str, Any]:
        try:
            disabled = check_tool_names(body.disabled)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error
        store.save_disabled_tools(disabled)

        return {"tools": describe_tools(disabled)}

    @api.get("/own")
    def get_own() -> dict[str, Any]:
        return own.describe()

    @api.post("/own/data/files", status_code=201)
    async def upload_own_file(
        request: Request,
        name: str = Query(min_length=1, max_length=1000),
        description: str = Query(max_length=MAX_DESCRIPTION_CHARS * 4),
    ) -> Any:
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > max_upload_bytes:
            raise ApiError(
                413, "too_large", f"The file is larger than the {max_upload_bytes} bytes that can be uploaded"
            )
        reader = RequestBodyReader(request, asyncio.get_running_loop())
        try:
            await run_in_threadpool(own.add_upload, name, cast(BinaryIO, reader), description)
        except ClientDisconnect:
            return Response(status_code=499)

        return await run_in_threadpool(own.describe)

    @api.post("/own/data/paths", status_code=201)
    def add_own_path(body: OwnPathBody) -> dict[str, Any]:
        own.add_path(body.path, body.description)

        return own.describe()

    @api.patch("/own/data/{name}")
    def change_own_data(name: str, body: OwnDescriptionBody) -> dict[str, Any]:
        own.change_description(name, body.description)

        return own.describe()

    @api.delete("/own/data/{name}")
    def remove_own_data(name: str) -> dict[str, Any]:
        own.remove(name)

        return own.describe()

    @api.get("/own/data/{name}/preview")
    def preview_own_data(name: str) -> dict[str, Any]:
        return own.preview(name)

    @api.put("/own/software")
    def put_own_software(body: OwnSoftwareBody) -> dict[str, Any]:
        own.put_software(body.name, body.description)

        return own.describe()

    @api.delete("/own/software/{name:path}")
    def remove_own_software(name: str) -> dict[str, Any]:
        own.remove_software(name)

        return own.describe()

    @api.get("/papers")
    def get_papers() -> dict[str, Any]:
        return papers.describe()

    @api.post("/papers/runs", status_code=201)
    def make_paper_run(body: PapersRunBody) -> dict[str, Any]:
        return papers.view(papers.create(body.title, body.source.model_dump(exclude_none=True)))

    @api.get("/papers/runs/{run_id}")
    def get_paper_run(run_id: str) -> dict[str, Any]:
        return papers.view(run_id)

    @api.patch("/papers/runs/{run_id}")
    def give_paper_run(run_id: str, body: PapersGiveBody) -> dict[str, Any]:
        papers.give(run_id, body.given)

        return papers.view(run_id)

    @api.delete("/papers/runs/{run_id}")
    def delete_paper_run(run_id: str) -> dict[str, Any]:
        papers.delete(run_id)

        return papers.describe()

    @api.post("/papers/runs/{run_id}/files", status_code=201)
    async def upload_paper(request: Request, run_id: str, name: str = Query(min_length=1, max_length=1000)) -> Any:
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > papers.max_upload_bytes:
            raise ApiError(
                413, "too_large", f"The file is larger than the {papers.max_upload_bytes} bytes that can be uploaded"
            )
        reader = RequestBodyReader(request, asyncio.get_running_loop())
        try:
            await run_in_threadpool(papers.add_file, run_id, name, cast(BinaryIO, reader))
        except ClientDisconnect:
            return Response(status_code=499)

        return await run_in_threadpool(papers.view, run_id)

    @api.delete("/papers/runs/{run_id}/files/{name}")
    def delete_paper_file(run_id: str, name: str) -> dict[str, Any]:
        papers.remove_file(run_id, name)

        return papers.view(run_id)

    @api.post("/papers/runs/{run_id}/read", status_code=202)
    def read_paper_run(run_id: str, body: PapersReadBody) -> dict[str, Any]:
        job = papers.read(run_id, body.max_cost, body.max_cost_per_paper, body.retry_failed)

        return job.snapshot(0)

    @api.post("/papers/runs/{run_id}/functions", status_code=202)
    def write_paper_functions(run_id: str, body: PapersFunctionsBody) -> dict[str, Any]:
        job = papers.generate(
            run_id,
            body.max_cost,
            body.max_cost_per_function,
            body.min_papers,
            body.limit,
            body.retry_failed,
            body.verify,
        )

        return job.snapshot(0)

    @api.get("/papers/runs/{run_id}/functions/{name}")
    def get_paper_function(run_id: str, name: str) -> dict[str, Any]:
        return papers.function(run_id, name)

    @api.delete("/papers/runs/{run_id}/functions/{name}")
    def delete_paper_function(run_id: str, name: str) -> dict[str, Any]:
        papers.remove_function(run_id, name)

        return papers.view(run_id)

    @api.get("/papers/runs/{run_id}/tables/{kind}")
    def paper_table(run_id: str, kind: str) -> FileResponse:
        return file_response(papers.summary_file(run_id, kind), download=True)

    @api.get("/benchmarks")
    def get_benchmarks() -> dict[str, Any]:
        return benchmarks.describe()

    @api.post("/benchmarks/files")
    def fetch_benchmark_files() -> dict[str, Any]:
        return benchmarks.fetch_files()

    @api.post("/benchmarks/runs", status_code=201)
    def make_benchmark_run(body: BenchmarkRunBody) -> dict[str, Any]:
        options = body.model_dump(include={"tasks", "subset", "leave_out_images"}, exclude_none=True)
        run_id = benchmarks.create(body.title, body.benchmark, body.solver, body.rounds, body.limit, options)

        return benchmarks.view(run_id)

    @api.get("/benchmarks/runs/{run_id}")
    def get_benchmark_run(run_id: str) -> dict[str, Any]:
        return benchmarks.view(run_id)

    @api.delete("/benchmarks/runs/{run_id}")
    def delete_benchmark_run(run_id: str) -> dict[str, Any]:
        benchmarks.delete(run_id)

        return benchmarks.describe()

    @api.post("/benchmarks/runs/{run_id}/start", status_code=202)
    def start_benchmark_run(run_id: str, body: BenchmarkStartBody) -> dict[str, Any]:
        job = benchmarks.start(run_id, body.max_cost, body.max_cost_per_question, body.retry_failed)

        return job.snapshot(0)

    @api.get("/benchmarks/runs/{run_id}/questions/{task}/{number}")
    def get_benchmark_question(run_id: str, task: str, number: str) -> dict[str, Any]:
        return benchmarks.question(run_id, task, number)

    @api.get("/projects")
    def get_projects() -> dict[str, Any]:
        return projects.describe()

    @api.post("/projects", status_code=201)
    def make_project(body: ProjectBody) -> dict[str, Any]:
        project_id = projects.create(
            body.goal,
            body.title,
            body.team,
            body.max_team_size,
            body.meeting_rounds,
            body.memory,
            body.findings_per_step,
        )

        return projects.view(project_id)

    @api.get("/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        return projects.view(project_id)

    @api.delete("/projects/{project_id}")
    def delete_project(project_id: str) -> dict[str, Any]:
        projects.delete(project_id)

        return projects.describe()

    @api.post("/projects/{project_id}/start", status_code=202)
    def start_project(project_id: str, body: ProjectStartBody) -> dict[str, Any]:
        job = projects.start(project_id, body.max_cost, body.max_rounds, body.max_stalled_rounds)

        return job.snapshot(0)

    @api.get("/projects/{project_id}/steps/{name}")
    def get_project_step(project_id: str, name: str) -> dict[str, Any]:
        return projects.step(project_id, name)

    @api.get("/projects/{project_id}/report")
    def project_report(project_id: str) -> FileResponse:
        return file_response(projects.report_file(project_id), download=True)

    @api.get("/mcp")
    def get_mcp() -> dict[str, Any]:
        return {"servers": describe_servers(store.load_mcp_servers())}

    @api.put("/mcp/servers/{name}")
    def set_mcp_server(name: str, body: McpServerBody) -> dict[str, Any]:
        try:
            entry = check_entry(name, body.entry)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error
        stored = store.load_mcp_servers()
        if name not in stored and len(stored) >= MAX_SERVERS:
            raise ApiError(422, "invalid", f"At most {MAX_SERVERS} servers can be set up")
        store.put_mcp_server(name, entry)

        return {"servers": describe_servers(store.load_mcp_servers())}

    @api.patch("/mcp/servers/{name}")
    def change_mcp_server(name: str, body: McpChangeBody) -> dict[str, Any]:
        if body.enabled is None and body.auth is None:
            raise ApiError(422, "invalid", "Say what to change: enabled, or auth")
        try:
            store.update_mcp_server(name, lambda entry: change_entry(name, entry, body.enabled, body.auth))
        except KeyError:
            raise not_found("server of yours with that name") from None
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error

        return {"servers": describe_servers(store.load_mcp_servers())}

    @api.delete("/mcp/servers/{name}")
    def remove_mcp_server(name: str) -> dict[str, Any]:
        if not store.remove_mcp_server(name):
            raise not_found("server of yours with that name")

        return {"servers": describe_servers(store.load_mcp_servers())}

    def known_mcp_server(name: str) -> dict[str, Any] | None:
        """What is kept for a server that is set up, or None for a preset that is not; any other name is not found."""
        entry = store.load_mcp_servers().get(name)
        if entry is None and name not in MCP_PRESETS:
            raise not_found("server of yours with that name")

        return entry

    checking: set[str] = set()
    checking_lock = threading.Lock()

    @api.post("/mcp/servers/{name}/check")
    def check_mcp_server(name: str) -> dict[str, Any]:
        entry = known_mcp_server(name)
        with checking_lock:
            if name in checking:
                raise ApiError(409, "busy", f"{server_title(name, entry)} is being checked")
            checking.add(name)
        try:
            return check_connection(name, entry)
        finally:
            with checking_lock:
                checking.discard(name)

    @api.delete("/mcp/servers/{name}/sign-in")
    def sign_out_of_mcp_server(name: str) -> dict[str, Any]:
        try:
            sign_out(name, known_mcp_server(name))
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error

        return {"servers": describe_servers(store.load_mcp_servers())}

    @api.get("/chats")
    def list_chats() -> dict[str, Any]:
        return {"chats": conversations.summaries()}

    @api.post("/chats", status_code=201)
    def create_chat(body: ChatBody) -> dict[str, Any]:
        return conversations.create(body.model_dump(exclude_unset=True), body.title).info()

    @api.get("/chats/{chat_id}")
    def get_chat(chat_id: str) -> dict[str, Any]:
        return conversations.get(chat_id).info()

    @api.patch("/chats/{chat_id}")
    def rename_chat(chat_id: str, body: RenameBody) -> dict[str, Any]:
        title = " ".join(body.title.split())[:MAX_CHAT_TITLE_CHARS]
        if not title:
            raise ApiError(422, "invalid", "A conversation needs a title with something in it")
        handle = conversations.get(chat_id)
        handle.chat.rename(title)

        return handle.info()

    @api.delete("/chats/{chat_id}")
    def delete_chat(chat_id: str) -> Response:
        conversations.delete(chat_id)

        return Response(status_code=204)

    @api.post("/chats/{chat_id}/messages", status_code=202)
    def send_message(chat_id: str, body: MessageBody) -> dict[str, Any]:
        handle = conversations.ready(chat_id)
        try:
            handle.chat.start(body.text, body.attachments, body.replace_last)
        except ChatBusyError as error:
            raise ApiError(409, "busy", str(error)) from error
        except ChatClosedError as error:
            raise ApiError(409, "closed", str(error)) from error
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from error

        return {"turn": handle.chat.turns, "state": handle.chat.state}

    @api.post("/chats/{chat_id}/note")
    def add_note(chat_id: str, body: NoteBody) -> dict[str, bool]:
        return {"accepted": conversations.get(chat_id).chat.add_note(body.text)}

    @api.post("/chats/{chat_id}/pause")
    def pause(chat_id: str) -> dict[str, bool]:
        return {"accepted": conversations.get(chat_id).chat.pause()}

    @api.post("/chats/{chat_id}/resume")
    def resume(chat_id: str) -> dict[str, bool]:
        return {"accepted": conversations.get(chat_id).chat.resume()}

    @api.post("/chats/{chat_id}/stop")
    def stop(chat_id: str) -> dict[str, bool]:
        return {"accepted": conversations.get(chat_id).stop()}

    @api.post("/chats/{chat_id}/approvals/{request_id}")
    def approve_call(chat_id: str, request_id: str, body: ApprovalBody) -> dict[str, str]:
        connections = conversations.get(chat_id).connections
        if connections is None:
            raise not_waiting(request_id)

        return {"state": connections.asker.approval(request_id, body.allow)}

    @api.post("/chats/{chat_id}/questions/{request_id}")
    def answer_question(chat_id: str, request_id: str, body: AnswerBody) -> dict[str, str]:
        connections = conversations.get(chat_id).connections
        if connections is None:
            raise not_waiting(request_id)

        return {"state": connections.asker.reply(request_id, body.answer)}

    @api.get("/chats/{chat_id}/events")
    async def follow_chat(
        chat_id: str,
        after: int = Query(0, ge=0),
        last_event_id: str | None = Header(None),
    ) -> StreamingResponse:
        handle = await run_in_threadpool(conversations.get, chat_id)

        return StreamingResponse(
            follow(handle, max(after, last_event(last_event_id))),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @api.post("/chats/{chat_id}/uploads", status_code=201)
    async def upload(chat_id: str, request: Request, name: str = Query(min_length=1, max_length=1000)) -> Any:
        handle = await run_in_threadpool(conversations.get, chat_id)
        limit = handle.chat.max_upload_bytes
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            raise ApiError(413, "too_large", f"The file is larger than the {limit} bytes that can be attached")
        reader = RequestBodyReader(request, asyncio.get_running_loop())
        try:
            attachment = await run_in_threadpool(handle.chat.save_upload, name, cast(BinaryIO, reader))
        except UploadTooLargeError as error:
            raise ApiError(413, "too_large", str(error)) from error
        except ClientDisconnect:
            return Response(status_code=499)

        return attachment.to_dict()

    @api.get("/chats/{chat_id}/files")
    def chat_files(chat_id: str) -> dict[str, Any]:
        handle = conversations.get(chat_id)
        found, truncated = list_files(handle.files_root, shown=handle.files_shown)

        return {"files": found, "truncated": truncated}

    @api.get("/chats/{chat_id}/files/{path:path}")
    def chat_file(chat_id: str, path: str, download: bool = False) -> FileResponse:
        handle = conversations.get(chat_id)

        return file_response(resolve_inside(handle.files_root, path, handle.files_shown), download=download)

    @api.get("/chats/{chat_id}/export")
    def export_chat(chat_id: str, kind: Literal["html", "pdf", "ipynb"] = Query("html", alias="format")) -> Response:
        handle = conversations.get(chat_id)
        if kind == "ipynb":
            notebook = notebook_text(chat_notebook(handle.directory, files_dir=handle.files_root))

            return Response(
                notebook.encode("utf-8"),
                media_type="application/x-ipynb+json",
                headers=download_headers(handle.chat.title, kind),
            )
        page = chat_html(handle.directory, files_dir=handle.files_root)
        if kind == "html":
            content, media_type = page.encode("utf-8"), "text/html; charset=utf-8"
        else:
            try:
                content, media_type = make_pdf(page), "application/pdf"
            except PDFExportError as error:
                raise ApiError(501, "pdf_unavailable", PDF_UNAVAILABLE, reason=str(error)) from error

        return Response(content, media_type=media_type, headers=download_headers(handle.chat.title, kind))

    app.include_router(api)

    if static_dir is not None:
        pages = Path(static_dir)

        # HEAD as well as GET, which the page's router asks of an address before it goes to it
        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        def page(request: Request, path: str) -> FileResponse:
            if path == "api" or path.startswith("api/"):
                # What the API has no address for, and, for HEAD, what it has but does not answer that to
                raise HTTPException(404 if request.method == "GET" else 405)
            found = static_file(pages, path)
            if found is None and not Path(path).suffix:
                found = static_file(pages, "")
            if found is None:
                raise not_found("page at this address")
            cache = "public, max-age=31536000, immutable" if path.startswith(IMMUTABLE_PREFIX) else "no-cache"

            headers = {"Cache-Control": cache}
            if found.suffix == ".html":
                changed = found.stat()
                headers["Content-Security-Policy"] = policy_of_file(str(found), changed.st_mtime_ns, changed.st_size)

            return FileResponse(found, headers=headers)

    app.add_middleware(Guard, token=token, allowed_hosts=allowed_hosts)

    return app
