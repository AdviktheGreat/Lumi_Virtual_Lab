"""The server of a PaperAgent's tools, as it is carried in the package that they are exported as (exporting.py).

This is not part of Lumi's own code, and nothing imports it but the tests. It is written into the package as
mcp_server.py, beside tool_runner.py and lumi_record.py, and is run by the Python of the environment that the tools
were made in, which can be any from 3.7, so it needs nothing but the standard library and is written in the syntax of
the oldest.

It speaks the Model Context Protocol over standard input and output, one JSON message to a line, and gives each tool of
the package as a tool. A call is made as it was made when the tool was made: in a process of its own, on a copy of the
code of its own (tool_runner.py), so that one call leaves nothing for the next, and what comes back is the value if it
is plain data, and what it is if it is not.

    python mcp_server.py            serves the tools
    python mcp_server.py check      starts the server, asks it for each tool's calls that were recorded, and holds what
                                    comes back to what the tutorials got, as it was when the tools were made

It does not make a call safe: the code of a paper is run as the user that runs this is allowed to run it. Run it in a
container.
"""

import argparse
import hashlib
import io
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

SCHEMA = 1
HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST_FILE = "package.json"
REPO_DIR = "repo"
RUNNER_FILE = "tool_runner.py"
RESULT_NAME = ".lumi-result"
# The versions of the protocol that this speaks, the latest first. A client that asks for another is answered with the
# latest, as the protocol has it
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_CALL_SECONDS = 1800
# How many of a tool's recorded calls a check makes, and how much of the time it is given each call may have
MAX_CASES = 3
CHECK_SECONDS = 1200
MAX_TEXT = 300
LOG_TAIL = 2000
NOT_PLAIN = "This is not plain data, so it is described and not sent."
FLOATS = ("nan", "inf", "-inf")
JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}

# What a record leaves in the look of a value that it could not keep whole, as comparing.py has it
CUT = " [cut]"
ADDRESS = " at 0x"
UNSHOWN = " that could not be shown>"
MAX_DIFFERENCES = 5
SHOWN_CHARS = 80


class RpcError(Exception):
    """A request that cannot be answered, which is answered with an error."""

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


class CheckError(Exception):
    """What stops a check from going on."""


def load_manifest(here=HERE):
    with io.open(os.path.join(here, MANIFEST_FILE), encoding="utf-8") as handle:
        return json.load(handle)


def cut(text, limit):
    return text if len(text) <= limit else text[:limit] + " [cut]"


def encode(value):
    """What a value is as JSON that the runner reads back as it was: a number that is not finite is written as a word,
    since JSON has none."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"$float": "nan" if math.isnan(value) else "inf" if value > 0 else "-inf"}
    if isinstance(value, dict):
        return dict((key, encode(item)) for key, item in value.items())
    if isinstance(value, list):
        return [encode(item) for item in value]

    return value


def is_word(value):
    return isinstance(value, dict) and len(value) == 1 and value.get("$float") in FLOATS


def fits(kind, value):
    if is_word(value):
        return kind in ("number", "integer")
    if kind == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and value.is_integer()
        )
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    expected = JSON_TYPES.get(kind)

    return expected is None or isinstance(value, expected)


def is_of(schema, value):
    """Whether a value is of what a schema of one parameter says, as far as its kind goes. What it is made of is not
    looked into, and a schema that does not say a kind takes anything."""
    if not isinstance(schema, dict):
        return True
    if isinstance(schema.get("anyOf"), list):
        return any(is_of(branch, value) for branch in schema["anyOf"])
    kind = schema.get("type")
    if isinstance(kind, list):
        return any(fits(one, value) for one in kind)
    if isinstance(kind, str):
        return fits(kind, value)

    return True


def check_arguments(schema, arguments):
    """What is wrong with the arguments of a call, if anything is: they are of what the tool takes, each that it must be
    given is, and none that it does not take is."""
    if not isinstance(arguments, dict):
        return "The arguments are an object that names each by its parameter."
    properties = schema.get("properties", {})
    unknown = sorted(name for name in arguments if name not in properties)
    if unknown:
        return "%s is not a parameter of this tool." % ", ".join(unknown)
    missing = [name for name in schema.get("required", []) if name not in arguments]
    if missing:
        return "%s must be given." % ", ".join(missing)
    for name, value in arguments.items():
        if not is_of(properties[name], value):
            return "%s is not of the kind that the tool takes." % name

    return None


def shown(value):
    """What a call gave, as the one that asked is told: the value if it is plain data, and what it is if it is not."""
    if value.get("plain"):
        return {"type": value["type"], "plain": True, "value": value.get("value")}
    described = dict(value)
    described["note"] = NOT_PLAIN

    return described


def failure_text(error, output):
    lines = ["%s: %s" % (error.get("type"), error.get("message"))]
    trace = error.get("traceback") or []
    if trace:
        lines += ["", "\n".join(str(line) for line in trace[-6:])]
    if output.strip():
        lines += ["", "What it printed:", cut(output.strip(), 2000)]

    return "\n".join(lines)


def kill(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, AttributeError):
        process.kill()


def read_result(work, name):
    path = os.path.join(work, RESULT_NAME, name)
    try:
        with io.open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return None

    return value if isinstance(value, dict) and "ok" in value else None


class Server(object):
    """What answers a client: the tools of the package, and a call of one."""

    def __init__(self, manifest, here=HERE):
        self.manifest = manifest
        self.here = here
        self.tools = dict((tool["name"], tool) for tool in manifest["tools"])
        limit = os.environ.get("LUMI_CALL_SECONDS", "")
        self.seconds = int(limit) if limit.isdigit() and int(limit) > 0 else DEFAULT_CALL_SECONDS

    def listed(self):
        return [
            {"name": tool["name"], "description": tool["description"], "inputSchema": tool["input_schema"]}
            for tool in self.manifest["tools"]
        ]

    def run(self, tool, arguments):
        """Calls the tool's function once, in a process of its own, and says what came of it: what the runner wrote of
        the call, or why it wrote none."""
        work = tempfile.mkdtemp(prefix="lumi-call-", dir=os.environ.get("LUMI_WORKDIR") or None)
        try:
            spec = {
                "schema": SCHEMA,
                "wrapper": os.path.join(self.here, tool["wrapper"]),
                "function": tool["name"],
                "repeats": 1,
                "seconds": self.seconds,
                "cases": [{"id": "call", "args": encode(arguments), "cwd": tool["cwd"]}],
            }
            with io.open(os.path.join(work, "spec.json"), "w", encoding="utf-8") as handle:
                json.dump(spec, handle)
            command = [
                sys.executable,
                os.path.join(self.here, RUNNER_FILE),
                "once",
                "spec.json",
                "--case",
                "0",
                "--repeat",
                "0",
                "--repo",
                os.path.join(self.here, REPO_DIR),
                "--work",
                work,
            ]
            environment = dict(os.environ)
            environment.setdefault("MPLBACKEND", "Agg")
            environment.setdefault("PYTHONHASHSEED", "0")
            log = os.path.join(work, "process.log")
            with open(log, "wb") as sink:
                process = subprocess.Popen(
                    command,
                    cwd=work,
                    stdin=subprocess.DEVNULL,
                    stdout=sink,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    start_new_session=True,
                )
                try:
                    process.wait(timeout=self.seconds)
                except subprocess.TimeoutExpired:
                    kill(process)
                    process.wait()
                    return {
                        "ok": False,
                        "error": {
                            "type": "TimedOut",
                            "message": "It was stopped after %s seconds." % self.seconds,
                            "traceback": [],
                        },
                        "output": "",
                    }
            result = read_result(work, "call-0.json")
            if result is not None:
                return result
            with open(log, "rb") as handle:
                tail = handle.read()[-LOG_TAIL:].decode("utf-8", "replace")

            return {
                "ok": False,
                "error": {
                    "type": "NoResult",
                    "message": "The process ended with code %s, without saying how." % process.returncode,
                    "traceback": [],
                },
                "output": tail,
            }
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def call(self, params):
        name = params.get("name")
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool is None:
            raise RpcError(-32602, "There is no tool called %s." % cut(str(name), 80))
        arguments = params.get("arguments")
        arguments = {} if arguments is None else arguments
        problem = check_arguments(tool["input_schema"], arguments)
        if problem:
            return text_result("Not run: " + problem, True)
        result = self.run(tool, arguments)
        if not result["ok"]:
            return text_result(failure_text(result["error"], result.get("output") or ""), True)
        answer = {
            "called": tool["function"],
            "tier": tool["tier"],
            "result": shown(result["result"]),
            "seconds": result.get("seconds"),
        }
        printed = (result.get("output") or "").strip()
        if printed:
            answer["printed"] = cut(printed, 2000)

        return text_result(json.dumps(answer), False)

    def initialize(self, params):
        asked = params.get("protocolVersion")
        manifest = self.manifest

        return {
            "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": manifest["name"], "version": manifest["version"]},
            "instructions": manifest["instructions"],
        }

    def handle(self, message):
        """The answer to one message, or None for one that is not asked anything."""
        if not isinstance(message, dict):
            return failure(None, -32600, "A message is an object.")
        number = message.get("id")
        if "method" not in message or "id" not in message:
            return None
        if message.get("jsonrpc") != "2.0" or not isinstance(message["method"], str):
            return failure(number, -32600, "Not a request.")
        params = message.get("params")
        params = {} if params is None else params
        if not isinstance(params, dict):
            return failure(number, -32602, "The parameters are an object.")
        method = message["method"]
        try:
            if method == "initialize":
                result = self.initialize(params)
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.listed()}
            elif method == "tools/call":
                result = self.call(params)
            else:
                raise RpcError(-32601, "This server does not do %s." % cut(method, 80))
        except RpcError as error:
            return failure(number, error.code, error.message)

        return {"jsonrpc": "2.0", "id": number, "result": result}


def text_result(text, is_error):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def failure(number, code, message):
    return {"jsonrpc": "2.0", "id": number, "error": {"code": code, "message": message}}


def serve(manifest, source=None, sink=None):
    """Answers what is sent on standard input, a line at a time, until it ends."""
    server = Server(manifest)
    source = source if source is not None else io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    sink = sink if sink is not None else sys.stdout

    def send(message):
        sink.write(json.dumps(message, allow_nan=False) + "\n")
        sink.flush()

    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            send(failure(None, -32700, "That is not JSON."))
            continue
        if isinstance(message, list):
            answers = [answer for answer in (server.handle(one) for one in message) if answer is not None]
            if answers:
                send(answers)
            continue
        answer = server.handle(message)
        if answer is not None:
            send(answer)

    return 0


# Holding a call to what the tutorial got, which is comparing.py's, in the syntax of the oldest Python


def shown_text(value, limit=SHOWN_CHARS):
    text = repr(value)

    return text if len(text) <= limit else text[:limit] + "..."


def is_whole(text):
    return isinstance(text, str) and not text.endswith(CUT) and ADDRESS not in text and not text.endswith(UNSHOWN)


def compare_values(expected, got, tolerance, path, found):
    if len(found) >= MAX_DIFFERENCES:
        return
    here = path or "the value"
    if type(expected) is not type(got):
        found.append("%s is %s where it was %s" % (here, type(got).__name__, type(expected).__name__))
    elif isinstance(expected, dict):
        if "$float" in expected or "$float" in got:
            if expected != got:
                found.append("%s is %s where it was %s" % (here, shown_text(got), shown_text(expected)))
            return
        if set(expected) != set(got):
            found.append(
                "%s has the keys %s where it had %s" % (here, shown_text(sorted(got)), shown_text(sorted(expected)))
            )
            return
        for key in expected:
            compare_values(expected[key], got[key], tolerance, "%s.%s" % (path, key) if path else key, found)
    elif isinstance(expected, list):
        if len(expected) != len(got):
            found.append("%s has %s items where it had %s" % (here, len(got), len(expected)))
            return
        for index in range(len(expected)):
            compare_values(expected[index], got[index], tolerance, "%s[%s]" % (path, index), found)
    elif isinstance(expected, float):
        if not math.isclose(expected, got, rel_tol=tolerance["relative"], abs_tol=tolerance["absolute"]):
            found.append("%s is %r where it was %r" % (here, got, expected))
    elif expected != got:
        found.append("%s is %s where it was %s" % (here, shown_text(got), shown_text(expected)))


def differences(expected, got, tolerance):
    """How a result differs from what was recorded, which is nothing if it is the same within the tolerance."""
    found = []
    if expected["type"] != got["type"]:
        return ["Its type is %s where it was %s" % (got["type"], expected["type"])]
    if expected["plain"] != got["plain"]:
        return ["It is plain data where it was not" if got["plain"] else "It is not plain data where it was"]
    if expected["plain"]:
        compare_values(expected["value"], got["value"], tolerance, "", found)
        return found
    for key in ("shape", "dtype"):
        if expected.get(key) != got.get(key):
            found.append(
                "The %s is %s where it was %s" % (key, shown_text(got.get(key)), shown_text(expected.get(key)))
            )
    if "values" in expected and "values" in got:
        compare_values(expected["values"], got["values"], tolerance, "values", found)
    elif "values" in expected or "values" in got:
        found.append("The values were kept of one and not of the other")
    elif "sha256" in expected or "sha256" in got:
        if expected.get("sha256") != got.get("sha256"):
            found.append("The hash of the values is not the same, and only a hash was kept, so there was no tolerance")
    elif "shape" in expected or "shape" in got or not (is_whole(expected.get("repr")) and is_whole(got.get("repr"))):
        found.append("Only how it shows itself was kept, and not all of it, so it cannot be told to be what it was")
    elif expected.get("repr") != got.get("repr"):
        found.append(
            "It shows as %s where it showed as %s" % (shown_text(got.get("repr")), shown_text(expected.get("repr")))
        )

    return found[:MAX_DIFFERENCES]


# Checking the package


def digest_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)

    return digest.hexdigest()


def tree_digest(folder):
    """What the files of a folder come to, as exporting.py works it out: a hash of each file's place and hash."""
    lines = []
    for current, names, files in os.walk(folder):
        names[:] = sorted(name for name in names if name != "__pycache__")
        for name in files:
            path = os.path.join(current, name)
            if name.endswith(".pyc") or os.path.islink(path) or not os.path.isfile(path):
                continue
            lines.append("%s\0%s\n" % (os.path.relpath(path, folder).replace(os.sep, "/"), digest_of(path)))

    return hashlib.sha256("".join(sorted(lines)).encode("utf-8")).hexdigest()


def files_problems(manifest, here=HERE):
    """What of the package is not as it was made: a file that was changed or taken away, and the code."""
    problems = []
    for name, digest in sorted(manifest.get("files", {}).items()):
        path = os.path.join(here, name)
        if os.path.islink(path) or not os.path.isfile(path):
            problems.append("%s is not there." % name)
        elif digest_of(path) != digest:
            problems.append("%s is not as it was made." % name)
    folder = os.path.join(here, REPO_DIR)
    if not os.path.isdir(folder):
        problems.append("%s/ is not there." % REPO_DIR)
    elif tree_digest(folder) != manifest.get("repo", {}).get("sha256"):
        problems.append("The code in %s/ is not as it was made." % REPO_DIR)

    return problems


class Client(object):
    """What asks a server that is run as a process, as a client of the protocol would."""

    def __init__(self, process):
        self.process = process
        self.number = 0

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def request(self, method, params=None):
        self.number += 1
        self.send({"jsonrpc": "2.0", "id": self.number, "method": method, "params": params or {}})
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise CheckError("The server ended without answering %s." % method)
            try:
                message = json.loads(line)
            except ValueError:
                raise CheckError("The server said something that is not JSON.")
            if isinstance(message, dict) and message.get("id") == self.number:
                if "error" in message:
                    raise CheckError("%s was refused: %s" % (method, cut(str(message["error"]), MAX_TEXT)))
                return message.get("result") or {}


def case_report(client, tool, example, number):
    """What one recorded call comes to when the server is asked it."""
    began = time.time()
    report = {"case": number, "status": "error", "differences": [], "message": None, "seconds": 0.0}
    answer = client.request("tools/call", {"name": tool["name"], "arguments": example["args"]})
    report["seconds"] = round(time.time() - began, 3)
    content = answer.get("content") or [{}]
    text = content[0].get("text") if isinstance(content[0], dict) else None
    if answer.get("isError") or not isinstance(text, str):
        report["message"] = cut(str(text), MAX_TEXT)
        return report
    try:
        got = json.loads(text)["result"]
        got = dict((key, value) for key, value in got.items() if key != "note")
        report["differences"] = differences(example["expected"], got, tool["tolerance"])
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        report["message"] = "What came back could not be held to what was recorded: %s" % cut(repr(error), MAX_TEXT)
        return report
    report["status"] = "differs" if report["differences"] else "match"

    return report


def run_check(manifest, cases, seconds, work, here=HERE):
    """Starts the server, asks it for the calls that were recorded of each tool, and holds what it says to what the
    tutorials got. The report is what the check says of itself: it is only as far to be believed as the package is."""
    report = {
        "schema": SCHEMA,
        "ok": False,
        "python": sys.version.split()[0],
        "name": manifest["name"],
        "version": manifest["version"],
        "problems": files_problems(manifest, here),
        "tools": [],
    }
    environment = dict(os.environ)
    environment["LUMI_CALL_SECONDS"] = str(max(1, seconds // max(1, len(manifest["tools"]) * cases)))
    if work:
        environment["LUMI_WORKDIR"] = work
    process = subprocess.Popen(
        [sys.executable, os.path.join(here, os.path.basename(__file__)), "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=environment,
        universal_newlines=True,
        encoding="utf-8",
    )
    # Ends the server if it does not answer, which a client that waited for it would wait for always
    watchdog = threading.Timer(seconds, process.kill)
    watchdog.daemon = True
    watchdog.start()
    try:
        client = Client(process)
        client.request(
            "initialize", {"protocolVersion": PROTOCOLS[0], "capabilities": {}, "clientInfo": {"name": "check"}}
        )
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        listed = sorted(tool["name"] for tool in client.request("tools/list").get("tools", []))
        if listed != sorted(tool["name"] for tool in manifest["tools"]):
            report["problems"].append("The server lists %s." % (", ".join(listed) or "no tools"))
        for tool in manifest["tools"]:
            calls = [
                case_report(client, tool, example, number) for number, example in enumerate(tool["examples"][:cases])
            ]
            report["tools"].append({"name": tool["name"], "cases": calls})
    except (CheckError, OSError, ValueError) as error:
        report["problems"].append(str(error))
    finally:
        watchdog.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()
    calls = [call for tool in report["tools"] for call in tool["cases"]]
    report["ok"] = (
        not report["problems"]
        and len(report["tools"]) == len(manifest["tools"])
        and bool(calls)
        and all(tool["cases"] for tool in report["tools"])
        and all(call["status"] == "match" for call in calls)
    )

    return report


def main(arguments):
    parser = argparse.ArgumentParser(prog="mcp_server.py", description="Serves the tools of this package.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "serve", help="Serve the tools over standard input and output. This is what is done without a command."
    )
    check = commands.add_parser("check", help="Hold what each tool gives to what its tutorial got.")
    check.add_argument("--report", help="A file to write what the check says of itself in.")
    check.add_argument("--cases", type=int, default=MAX_CASES, help="How many recorded calls of each tool to make.")
    check.add_argument("--seconds", type=int, default=CHECK_SECONDS, help="How long all of the calls may take.")
    check.add_argument("--work", help="A folder to make the copies of the code in.")
    options = parser.parse_args(arguments)
    manifest = load_manifest()
    if options.command != "check":
        return serve(manifest)
    report = run_check(manifest, max(1, options.cases), max(1, options.seconds), options.work)
    text = json.dumps(report, indent=2)
    if options.report:
        with io.open(options.report, "w", encoding="utf-8") as handle:
            handle.write(text)
    print(text)

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
