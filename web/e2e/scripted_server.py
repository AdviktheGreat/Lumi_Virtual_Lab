"""The server the interface's end-to-end tests run against, with a script where the model would be.

It is the real server, with the built pages, a workspace made for the run, and a fixed token, whose lead answers
from a script: no key is needed, and every run says the same. What it says depends on what it is asked:

- "fail:" anywhere in the message makes the model fail, which is how a turn that ends in an error is tested.
- "slow:" anywhere in the message makes it write a long reply, slowly, so that a turn can be followed or stopped
  while it is still going.
- "markdown:" anywhere in the message makes it answer with a page of Markdown, with what a page must not trust in it,
  once it has done what else the message asks, so that the figure the page names can be one the code drew.
- "code:" and a word (hello, error, two, plot, long, big, slow) make it run code in the conversation's session first, as
  the word says, and answer once the code has run. "tool:unknown" makes it call a tool it does not have, and
  "tool:resources" makes it look for resources, and choose the know-how documents there are.
- Anything else is answered with a short reply that repeats the question.

    python e2e/scripted_server.py --port 8799 --static-dir out
"""

import argparse
import json
import shutil
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from conftest import FakeClient, FakeCompletions, FakeStream, make_usage, stream_chunks, text_response  # noqa: E402
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall  # noqa: E402
from openai.types.chat.chat_completion import ChatCompletion, Choice  # noqa: E402
from openai.types.chat.chat_completion_message_tool_call import Function  # noqa: E402

from virtual_lab.server import serve  # noqa: E402

TOKEN = "e2e-token"
TEST_MODEL = "gpt-4o-2024-08-06"

# Seconds between the words of a reply, and how many words the long one has
WORD_DELAY = 0.04
LONG_REPLY_WORDS = 250


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
    "tool:unknown": [("", "mystery_tool", {"target": "TP53"})],
    "tool:resources": [("Looking for what suits it.", "find_resources", {"task": "Score a gene's expression"})],
}

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
        steps = None if searching else scenario_for(question)
        done = tool_results(kwargs["messages"])
        if steps is not None and done < len(steps):
            narration, name, arguments = steps[done]
            response = call_response(narration, name, arguments, f"call_{done + 1}")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="The server the interface's end-to-end tests run against.")
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--static-dir", default=str(ROOT / "web" / "out"))
    parser.add_argument("--word-delay", type=float, default=WORD_DELAY)
    options = parser.parse_args()

    workspace = Path(tempfile.mkdtemp(prefix="virtual-lab-e2e-"))
    try:
        serve(
            workspace=workspace,
            port=options.port,
            token=TOKEN,
            static_dir=options.static_dir,
            open_browser=False,
            check_keys=False,
            client=ScriptedClient(options.word_delay),
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    main()
