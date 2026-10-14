"""The server the interface's end-to-end tests run against, with a script where the model would be.

It is the real server, with the built pages, a workspace made for the run, and a fixed token, whose lead answers
from a script: no key is needed, and every run says the same. What it says depends on what it is asked:

- "fail:" anywhere in the message makes the model fail, which is how a turn that ends in an error is tested.
- "slow:" anywhere in the message makes it write a long reply, slowly, so that a turn can be followed or stopped
  while it is still going.
- "markdown:" anywhere in the message makes it answer with a page of Markdown, with what a page must not trust in it,
  once it has done what else the message asks, so that the figure the page names can be one the code drew.
- "code:" and a word (hello, error, two, plot, long, big, slow, files) make it run code in the conversation's session
  first, as the word says, and answer once the code has run. "tool:unknown" makes it call a tool it does not have, and
  "tool:resources" makes it look for resources, and choose the know-how documents there are. "lab:team" makes it bring
  in the team for a round of discussion, and "lab:consult" ask one scientist, whose replies the script writes too.
  "lab:code" brings in one scientist who runs code in the session, if the conversation has one, before they reply.
  "lab:slow" brings in one scientist who writes a long reply, slowly, so that a session can be followed as it goes.
- Anything else is answered with a short reply that repeats the question.

A conversation is saved as a PDF by a stand-in that puts the page in a file that starts as a PDF does, so that no
WeasyPrint is needed and every run says the same. "pdf:unavailable" anywhere in the conversation has it fail as it does
where WeasyPrint is not installed.

    python e2e/scripted_server.py --port 8799 --static-dir out

With --setup-control-port, Docker and the place the data lake is fetched from are stand-ins too (see
tests/setup_fakes.py), which a test arranges and looks at by POSTing JSON to that port; see FakeSetup.control.
"""

import argparse
import json
import re
import shutil
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from conftest import FakeClient, FakeCompletions, FakeStream, make_usage, stream_chunks, text_response  # noqa: E402
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall  # noqa: E402
from openai.types.chat.chat_completion import ChatCompletion, Choice  # noqa: E402
from openai.types.chat.chat_completion_message_tool_call import Function  # noqa: E402

from setup_fakes import Bucket, FakeDocker  # noqa: E402

from virtual_lab.environment import DATA_LAKE  # noqa: E402
from virtual_lab.export import PDFExportError  # noqa: E402
from virtual_lab.server import app as server_app  # noqa: E402
from virtual_lab.server import serve  # noqa: E402
from virtual_lab.ui.workspace import Workspace  # noqa: E402

TOKEN = "e2e-token"
TEST_MODEL = "gpt-4o-2024-08-06"

# Seconds between the words of a reply, and how many words the long one has
WORD_DELAY = 0.04
LONG_REPLY_WORDS = 250

# The largest file a message can be sent with, which is small, so that one too large is quick to make
MAX_UPLOAD_BYTES = 20 * 1024


# Code that draws a figure and makes a file, without matplotlib: a stand-in for the module, which saves a picture
PLOT_CODE = """\
import struct, sys, types, zlib

def png(width, height):
    rows = b"".join(
        b"\\x00" + b"".join(bytes((x * 255 // width, y * 255 // height, 180)) for x in range(width))
        for y in range(height)
    )
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    data = chunk(b"IDAT", zlib.compress(rows))
    return b"\\x89PNG\\r\\n\\x1a\\n" + chunk(b"IHDR", header) + data + chunk(b"IEND", b"")

class Figure:
    def savefig(self, path, **options):
        with open(path, "wb") as file:
            file.write(png(160, 100))

pyplot = types.ModuleType("matplotlib.pyplot")
shown = [1]
pyplot.get_fignums = lambda: list(shown)
pyplot.figure = lambda number=None: Figure()
pyplot.close = lambda figure=None: shown.clear()
sys.modules["matplotlib"] = types.ModuleType("matplotlib")
sys.modules["matplotlib.pyplot"] = pyplot

with open("results.csv", "w") as file:
    file.write("gene,score\\nTP53,0.91\\n")
print("drawn")
"""

TEAM_AGENDA = "Design a nanobody against TP53."
# What "code:files" writes, which is one of each of what the panel of files shows differently: a long table, a wide one
# divided by tabs, a log longer than is read to show it, a file that is not text, and an empty one
FILES_CODE = r"""
import os
os.makedirs("tables", exist_ok=True)
os.makedirs("logs", exist_ok=True)
with open("tables/long.csv", "w") as handle:
    handle.write("gene,score,note\n")
    for number in range(300):
        handle.write(f'G{number:03d},{number / 100:.2f},"row {number}, with a comma"\n')
with open("tables/wide.tsv", "w") as handle:
    handle.write("\t".join(f"c{number}" for number in range(50)) + "\n")
    handle.write("\t".join(str(number) for number in range(50)) + "\n")
with open("logs/big.log", "w") as handle:
    for number in range(8000):
        handle.write(f"line {number:05d} " + "x" * 30 + "\n")
with open("blob.bin", "wb") as handle:
    handle.write(bytes([137, 80, 0, 1, 2, 3]))
open("empty.txt", "w").close()
print("files written")
""".lstrip()
# How many words a scientist writes when the session is to be slow
LAB_SLOW_WORDS = 120
# What a scientist runs when the session they are in is asked for it, which makes a file for the page to list
LAB_CODE = 'print("lab code ran")\nopen("lab_notes.txt", "w").write("epitope: DNA-binding domain\\n")'

LONG_CODE = "\n".join([*(f"step_{number} = {number} * 2" for number in range(1, 31)), "print('ran', step_30)"])

# What the lead does for a message with "code:" or "tool:" in it: each step is what it says, the tool it calls, and
# what it calls it with
SCENARIOS: dict[str, list[tuple[str, str, dict[str, Any]]]] = {
    "code:hello": [("Let me run that.", "run_code", {"code": 'print("hello from the session")'})],
    "code:error": [("Trying it.", "run_code", {"code": 'print("\\x1b[31mabout to fail\\x1b[0m")\n1 / 0'})],
    "code:two": [
        ("First, one thing.", "run_code", {"code": 'x = 20\nprint("first", x)'}),
        ("Now the next.", "run_code", {"code": 'print("second", x + 22)'}),
    ],
    "code:plot": [("Drawing it.", "run_code", {"code": PLOT_CODE})],
    "code:long": [("A longer script.", "run_code", {"code": LONG_CODE})],
    "code:big": [
        (
            "That prints a lot.",
            "run_code",
            {"code": 'for number in range(2500):\n    print(f"row {number:05d} " + "x" * 40)'},
        )
    ],
    "code:slow": [("This will take a moment.", "run_code", {"code": "import time\ntime.sleep(3)\nprint('slept')"})],
    "code:files": [("Writing some files.", "run_code", {"code": FILES_CODE})],
    "tool:unknown": [("", "mystery_tool", {"target": "TP53"})],
    "tool:resources": [("Looking for what suits it.", "find_resources", {"task": "Score a gene's expression"})],
    "lab:team": [
        (
            "Bringing in the team.",
            "convene_team",
            {"agenda": TEAM_AGENDA, "members": ["Immunologist", "Scientific Critic"], "rounds": 1},
        )
    ],
    "lab:code": [
        (
            "Bringing in a scientist who can check.",
            "convene_team",
            {"agenda": f"lab:code {TEAM_AGENDA}", "members": ["Immunologist"], "rounds": 1},
        )
    ],
    "lab:slow": [
        (
            "Bringing in a scientist who takes their time.",
            "convene_team",
            {"agenda": f"slow: {TEAM_AGENDA}", "members": ["Immunologist"], "rounds": 1},
        )
    ],
    "lab:consult": [
        (
            "Asking one scientist.",
            "consult",
            {"member": "Immunologist", "agenda": "Is a nanobody against TP53 immunogenic?", "rounds": 1},
        )
    ],
}

# What the scientists say in a team session, by who they are: each says the same wherever it is asked
LAB_REPLIES = {
    "Principal Investigator": "Let us begin: which part of TP53 should a nanobody bind?",
    "Immunologist": "As the Immunologist, I would target the conserved DNA-binding epitope.",
    "Scientific Critic": "As the Scientific Critic, I ask what shows that the epitope is exposed.",
}
LAB_SUMMARY = "Summary: target the conserved DNA-binding epitope, and check that it is exposed."

# What the lead answers when it is asked which resources suit a task, which is what a search for them asks
RETRIEVAL_REPLY = "TOOLS: []\nDATA_LAKE: []\nLIBRARIES: []\nKNOW_HOW: [0, 1]"

MARKDOWN_REPLY = """\
## Findings

A paragraph with **bold**, *italic*, `inline code`, and [a paper](https://example.com/paper).

- first point
- second point

| Gene | Score |
| --- | --- |
| TP53 | 0.91 |

```python
print("hello")
```

```nonsense
plain text here
```

```
no language here
```

![The figure](plots/figure_1.png)

![A tracker](https://example.com/pixel.png)

<script>window.__pwned = true</script>

[Not a link](javascript:window.__pwned=true)

[A place here](#findings) and [an email](mailto:lab@example.com)
"""


class SlowStream(FakeStream):
    """A stream that takes its time over each chunk, as a model does."""

    def __init__(self, chunks: list[Any], delay: float) -> None:
        super().__init__(chunks)
        self.delay = delay

    def __iter__(self) -> Iterator[Any]:
        for chunk in self.chunks:
            time.sleep(self.delay)
            yield chunk


def asked(messages: list[dict[str, Any]]) -> str:
    """What the researcher last said, which is what the script answers."""
    for message in reversed(messages):
        if message["role"] == "user":
            content = message["content"]

            return content if isinstance(content, str) else ""

    return ""


def tool_results(messages: list[dict[str, Any]]) -> int:
    """How many of its tool calls the lead has been answered, since the researcher last spoke."""
    answered = 0
    for message in reversed(messages):
        if message["role"] == "user":
            break
        if message["role"] == "tool":
            answered += 1

    return answered


def scientist_of(kwargs: dict[str, Any]) -> str | None:
    """Who a request is for when it is a scientist's, in a team session, rather than the lead's."""
    tools = {tool["function"]["name"] for tool in kwargs.get("tools") or []}
    if tools & {"convene_team", "consult"}:
        return None
    system = next((message["content"] for message in kwargs["messages"] if message["role"] == "system"), "")
    found = re.match(r"You are an? ([^.]+)\.", system) if isinstance(system, str) else None

    return found.group(1) if found else None


def runs_code(title: str, kwargs: dict[str, Any]) -> bool:
    """Whether a scientist is to run code before they reply: when the agenda says so, and they have a tool to."""
    tools = {tool["function"]["name"] for tool in kwargs.get("tools") or []}
    said = " ".join(str(message["content"]) for message in kwargs["messages"] if message["role"] != "system")

    return title == "Immunologist" and "lab:code" in said and "run_code" in tools


def lab_reply(title: str, messages: list[dict[str, Any]]) -> str:
    """What a scientist says in a team session: the lead who has heard the others sums up."""
    said = " ".join(str(message["content"]) for message in messages if message["role"] != "system")
    if title == "Principal Investigator" and "As the Immunologist" in said:
        return LAB_SUMMARY
    if title == "Immunologist" and "slow:" in said:
        return " ".join(f"point{number}" for number in range(1, LAB_SLOW_WORDS + 1))

    return LAB_REPLIES.get(title, f"As the {title}, I have nothing to add.")


def scenario_for(question: str) -> list[tuple[str, str, dict[str, Any]]] | None:
    return next((steps for word, steps in SCENARIOS.items() if word in question), None)


def call_response(narration: str, name: str, arguments: dict[str, Any], call_id: str) -> ChatCompletion:
    """A completion in which the model says something and calls a tool."""
    return ChatCompletion(
        id="scripted",
        model=TEST_MODEL,
        object="chat.completion",
        created=0,
        usage=make_usage(),
        choices=[
            Choice(
                finish_reason="tool_calls",
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    content=narration or None,
                    tool_calls=[
                        ChatCompletionMessageToolCall(
                            id=call_id,
                            type="function",
                            function=Function(name=name, arguments=json.dumps(arguments)),
                        )
                    ],
                ),
            )
        ],
    )


def reply_to(question: str) -> str:
    if "USER QUERY:" in question and "AVAILABLE TOOLS:" in question:
        return RETRIEVAL_REPLY
    if "markdown:" in question:
        return MARKDOWN_REPLY
    if "slow:" in question:
        return " ".join(f"word{number}" for number in range(1, LONG_REPLY_WORDS + 1))

    return (
        f"You asked: {question}\n\nThis answer is from a script, so that the interface can be tested without a model."
    )


class ScriptedCompletions(FakeCompletions):
    def __init__(self, delay: float) -> None:
        super().__init__()
        self.delay = delay

    def create(self, **kwargs: Any) -> Any:
        question = asked(kwargs["messages"])
        if "fail:" in question:
            raise RuntimeError("The scripted model failed, as it was asked to")
        searching = "USER QUERY:" in question and "AVAILABLE TOOLS:" in question
        scientist = None if searching else scientist_of(kwargs)
        steps = None if searching or scientist is not None else scenario_for(question)
        done = tool_results(kwargs["messages"])
        if steps is not None and done < len(steps):
            narration, name, arguments = steps[done]
            response = call_response(narration, name, arguments, f"call_{done + 1}")
        elif scientist is not None and runs_code(scientist, kwargs) and done == 0:
            response = call_response("Let me check that.", "run_code", {"code": LAB_CODE}, "call_lab_1")
        elif scientist is not None:
            response = text_response(lab_reply(scientist, kwargs["messages"]))
        elif steps is not None and "markdown:" in question:
            response = text_response(MARKDOWN_REPLY)
        elif steps is not None:
            response = text_response(f"That is done: {len(steps)} step{'s' if len(steps) != 1 else ''} ran.")
        else:
            response = text_response(reply_to(question))
        if kwargs.get("stream"):
            include_usage = bool((kwargs.get("stream_options") or {}).get("include_usage"))

            return SlowStream(stream_chunks(response, include_usage), self.delay)

        return response


class ScriptedClient(FakeClient):
    def __init__(self, delay: float = WORD_DELAY) -> None:
        super().__init__()
        self.chat = type("Chat", (), {"completions": ScriptedCompletions(delay)})()


# How big each file of the data lake is in the stand-in for the place it is fetched from, which is big enough for the
# part of it that has been fetched, when a fetch is held halfway, to be a size to read
DATA_LAKE_FILE_BYTES = 10 * 1024


class FakeSetup:
    """Docker and the release the data lake is fetched from, as stand-ins, and what a test does to them.

    :param directory: Where the stand-in for Docker is kept.
    :param workspace: The workspace of the server, whose data lake is what is fetched into.
    """

    def __init__(self, directory: Path, workspace: Path) -> None:
        self.docker = FakeDocker(directory)
        self.bucket = Bucket()
        self.files = {name: bytes(range(256)) * (DATA_LAKE_FILE_BYTES // 256) for name in DATA_LAKE}
        self.bucket.files = dict(self.files)
        self.lake = Workspace(workspace).data_lake_dir

    def settle(self) -> None:
        """Lets everything that is held go on, so that every job that is at work can end."""
        for gate in self.bucket.gates.values():
            gate.set()
        self.docker.release()

    def reset(self) -> None:
        """Puts everything as it was when the server began: Docker is up and has no image, and no file is fetched.
        Nothing may be at work, since what is would go on into what is put as it was."""
        self.bucket.gates.clear()
        self.bucket.files = dict(self.files)
        self.bucket.requests.clear()
        for name in ("started", "pid", "builds.jsonl"):
            (self.docker.directory / name).unlink(missing_ok=True)
        fresh = FakeDocker(self.docker.directory)
        self.docker.state = fresh.state
        self.docker.save()
        (self.docker.directory / "release").unlink(missing_ok=True)
        shutil.rmtree(self.lake, ignore_errors=True)

    def control(self, order: dict[str, Any]) -> dict[str, Any]:
        """Does what a test asks, each of these that it names, and says what it can be asked of.

        - "settle": lets everything that is held go on, which ends the jobs that are at work, once they are done.
        - "reset": puts everything as it began, which is done when no job is at work.
        - "docker": changes what Docker answers, as FakeDocker.configure does.
        - "build": changes how a build goes, as FakeDocker.build does.
        - "release": lets a build that is waiting end.
        - "hold": the names of files of the data lake whose fetch is held halfway, until they are named in "let".
        - "let": the names of files whose fetch goes on.
        - "withhold": the names of files that the release does not have, which makes fetching them fail.
        - "present": the names of files to put in the data lake as if they were fetched already.
        - "state": asks, and is answered with "builds" begun, whether a build "started", and the "images" built.
        """
        if order.get("settle"):
            self.settle()
        if order.get("reset"):
            self.reset()
        if "docker" in order:
            self.docker.configure(**order["docker"])
        if "build" in order:
            self.docker.build(**order["build"])
        for name in order.get("hold", []):
            self.bucket.gate(name)
        for name in order.get("let", []):
            self.bucket.gates[name].set()
        for name in order.get("withhold", []):
            del self.bucket.files[name]
        for name in order.get("present", []):
            self.lake.mkdir(parents=True, exist_ok=True)
            (self.lake / name).write_bytes(self.files[name])
        if order.get("release"):
            self.docker.release()

        return {
            "builds": self.docker.builds,
            "started": self.docker.started,
            "images": self.docker.images,
            "requests": list(self.bucket.requests),
        }


def serve_control(setup: FakeSetup, port: int) -> None:
    """Listens on a port for a test to arrange the stand-ins, which it does by POSTing the JSON control takes."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.dumps(setup.control(json.loads(self.rfile.read(length) or b"{}"))).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()


def stand_in_pdf(page: str) -> bytes:
    if "pdf:unavailable" in page:
        raise PDFExportError("Making a PDF needs WeasyPrint. (ImportError: the stand-in is told to fail)")

    return b"%PDF-1.7\n% made by the stand-in\n" + page.encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="The server the interface's end-to-end tests run against.")
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument(
        "--setup-control-port",
        type=int,
        default=None,
        help="stand in for Docker and where the data lake is fetched from, arranged by what is POSTed to this port",
    )
    parser.add_argument("--static-dir", default=str(ROOT / "web" / "out"))
    parser.add_argument("--word-delay", type=float, default=WORD_DELAY)
    parser.add_argument("--max-upload-bytes", type=int, default=MAX_UPLOAD_BYTES)
    options = parser.parse_args()

    server_app.make_pdf = stand_in_pdf
    workspace = Path(tempfile.mkdtemp(prefix="virtual-lab-e2e-"))
    setup = None
    stand_ins: dict[str, Any] = {}
    if options.setup_control_port is not None:
        setup = FakeSetup(workspace.parent / f"{workspace.name}-docker", workspace)
        serve_control(setup, options.setup_control_port)
        stand_ins = {"docker_command": setup.docker.command, "release_url": setup.bucket.url}
    try:
        serve(
            workspace=workspace,
            port=options.port,
            token=TOKEN,
            static_dir=options.static_dir,
            open_browser=False,
            check_keys=False,
            client=ScriptedClient(options.word_delay),
            max_upload_bytes=options.max_upload_bytes,
            **stand_ins,
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        if setup is not None:
            shutil.rmtree(setup.docker.directory, ignore_errors=True)
            setup.bucket.close()


if __name__ == "__main__":
    main()
