"""The server the interface's end-to-end tests run against, with a script where the model would be.

It is the real server, with the built pages, a workspace made for the run, and a fixed token, whose lead answers
from a script: no key is needed, and every run says the same. What it says depends on what it is asked:

- "fail:" anywhere in the message makes the model fail, which is how a turn that ends in an error is tested.
- "slow:" anywhere in the message makes it write a long reply, slowly, so that a turn can be followed or stopped
  while it is still going.
- Anything else is answered with a short reply that repeats the question.

    python e2e/scripted_server.py --port 8799 --static-dir out
"""

import argparse
import shutil
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from conftest import FakeClient, FakeCompletions, FakeStream, stream_chunks, text_response  # noqa: E402

from virtual_lab.server import serve  # noqa: E402

TOKEN = "e2e-token"

# Seconds between the words of a reply, and how many words the long one has
WORD_DELAY = 0.04
LONG_REPLY_WORDS = 250


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


def reply_to(question: str) -> str:
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
