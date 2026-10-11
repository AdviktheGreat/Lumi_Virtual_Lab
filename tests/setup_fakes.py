"""Stand-ins for what the setup talks to: a program that answers as Docker does, and a server that answers as
Biomni's release bucket does. Both are real, one a process and the other a socket, so that what is tested is
reading a process's output, ending it, and streaming a body, and not a stub of them.
"""

import json
import os
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

FAKE_DOCKER = """\
import json, os, signal, subprocess, sys, time
from pathlib import Path

here = Path(__file__).resolve().parent
state = json.loads((here / "state.json").read_text())
args = sys.argv[1:]

if args[:1] == ["info"]:
    if state["daemon"] == "hang":
        time.sleep(60)
    if state["daemon"] == "silent":
        sys.exit(1)
    if state["daemon"] == "down":
        sys.stderr.write("Cannot connect to the Docker daemon at unix:///var/run/docker.sock.\\nIs it running?\\n")
        sys.exit(1)
    print(state["version"])
elif args[:3] == ["image", "ls", "--quiet"]:
    if args[3] in state["images"]:
        print("d0572aed6cf0")
elif args[:1] == ["build"]:
    tag = args[args.index("--tag") + 1]
    with (here / "builds.jsonl").open("a") as record:
        record.write(json.dumps(args) + "\\n")
    (here / "pid").write_text(str(os.getpid()))
    if state["build"]["ignore_term"]:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if state["build"]["child"]:
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(25)"])
    for number, line in enumerate(state["build"]["lines"]):
        (sys.stderr if number % 2 else sys.stdout).write(line + "\\n")
        (sys.stderr if number % 2 else sys.stdout).flush()
    for raw in state["build"].get("raw", []):
        sys.stdout.flush()
        sys.stdout.buffer.write(bytes.fromhex(raw) + b"\\n")
        sys.stdout.buffer.flush()
    (here / "started").write_text("")
    if state["build"]["wait"]:
        deadline = time.monotonic() + 30
        while not (here / "release").exists():
            if time.monotonic() > deadline:
                sys.exit(3)
            time.sleep(0.02)
    if state["build"]["exit"] == 0:
        state["images"].append(tag)
        (here / "state.json").write_text(json.dumps(state))
    sys.exit(state["build"]["exit"])
else:
    sys.stderr.write("unknown command: " + " ".join(args) + "\\n")
    sys.exit(2)
"""


class FakeDocker:
    """A program that answers as the docker command does, as told by a file it reads each time it is run.

    :param directory: Where to put it.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "docker.py").write_text(FAKE_DOCKER)
        self.command: tuple[str, ...] = (sys.executable, str(directory / "docker.py"))
        self.state: dict[str, Any] = {
            "daemon": "up",
            "version": "27.3.1",
            "images": [],
            "build": {
                "lines": ["#1 [internal] load build definition", "#2 FROM python"],
                "exit": 0,
                "wait": False,
                "ignore_term": False,
                "child": False,
            },
        }
        self.save()

    def save(self) -> None:
        (self.directory / "state.json").write_text(json.dumps(self.state))

    def configure(self, **changes: Any) -> "FakeDocker":
        """Changes what it answers: "daemon" ("up", "down" with a reason, "silent" down, or "hang"), "version",
        and the "images" it has."""
        self.state.update(changes)
        self.save()

        return self

    def build(self, **changes: Any) -> "FakeDocker":
        """Changes how a build goes: the "lines" it prints, then the "raw" bytes it prints, as hex, its "exit"
        code, whether it "wait"s for release() before it ends, whether it ignores being asked to end
        ("ignore_term"), and whether it starts a "child" that holds its output open for 25 seconds."""
        self.state["build"].update(changes)
        self.save()

        return self

    def release(self) -> None:
        (self.directory / "release").write_text("")

    @property
    def running(self) -> bool:
        """Whether the build it was last asked for is still going on."""
        try:
            os.kill(int((self.directory / "pid").read_text()), 0)
        except (FileNotFoundError, ValueError, ProcessLookupError):
            return False

        return True

    @property
    def started(self) -> bool:
        return (self.directory / "started").exists()

    @property
    def images(self) -> list[str]:
        return json.loads((self.directory / "state.json").read_text())["images"]

    @property
    def builds(self) -> list[list[str]]:
        path = self.directory / "builds.jsonl"

        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class Bucket:
    """A server that answers as Biomni's release bucket does: /data_lake/{name}, for each file it is given.

    A file in gates is sent as far as its first half, and the rest once the gate is opened, so that a download can
    be looked at, and stopped, partway through. A file in unannounced is sent without its length.
    """

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.gates: dict[str, threading.Event] = {}
        self.unannounced: set[str] = set()
        self.requests: list[str] = []
        bucket = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                name = self.path.removeprefix("/data_lake/")
                bucket.requests.append(name)
                body = bucket.files.get(name)
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                if name not in bucket.unannounced:
                    self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                half = len(body) // 2
                try:
                    self.wfile.write(body[:half])
                    self.wfile.flush()
                    if name in bucket.gates:
                        bucket.gates[name].wait(30)
                    self.wfile.write(body[half:])
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, format: str, *args: Any) -> None:
                return None

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def gate(self, name: str) -> threading.Event:
        self.gates[name] = threading.Event()

        return self.gates[name]

    def close(self) -> None:
        for gate in self.gates.values():
            gate.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def wait_for(condition: Callable[[], Any], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "Waited for something that did not happen"
        time.sleep(0.005)


def in_thread(call: Callable[[], Any]) -> tuple[threading.Thread, dict[str, Any]]:
    """Runs a call in a thread, as a job does, keeping what it returned or raised."""
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["returned"] = call()
        except Exception as error:
            outcome["raised"] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    return thread, outcome
