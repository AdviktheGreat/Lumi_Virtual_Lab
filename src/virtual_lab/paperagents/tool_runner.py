"""Calls one function of a paper's code again, through the wrapper that was made of it, in the paper's environment, and
says what came back.

This is not part of Lumi's own code, and nothing imports it. It is written into the folder that a run is given, beside a
copy of tutorial_runner.py (as lumi_record.py), whose way of describing a value it uses so that what a call gave is
described as the tutorial's call was. It is run by the Python of the environment that was built for the paper's code,
which can be any from 3.7, so it needs nothing but the standard library and is written in the syntax of the oldest.

It is given a file that names the wrapper and lists the calls to make, each with the arguments that went in and the
folder that it was made from. Each call is made in a process of its own, on a copy of the project of its own, as a
person's call would be, and so one call cannot leave anything for the next. What each gave is written to a file, with
its type and a look at what it is, and the arguments are the only thing it is given: the answer that the tutorial got is
kept on the other side, and is not here to be seen.

It does not make the run safe: the container it is run in does that. Nor does it grade anything.
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import lumi_record as record

SCHEMA = 1
RESULT_NAME = record.RESULT_NAME
FLOATS = ("nan", "inf", "-inf")


def decode(value):
    """What a plain value was before it was written as JSON: a number that is not finite is written out as a word, as
    JSON has none."""
    if isinstance(value, dict):
        if len(value) == 1 and value.get("$float") in FLOATS:
            return float(value["$float"])
        return dict((key, decode(item)) for key, item in value.items())
    if isinstance(value, list):
        return [decode(item) for item in value]

    return value


def load_wrapper(path):
    spec = importlib.util.spec_from_file_location("lumi_wrapper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def write_call(folder, case, repeat, result):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "%s-%s.json" % (case, repeat))
    try:
        text = json.dumps(result, allow_nan=False)
    except (TypeError, ValueError):
        text = json.dumps(dict(result, result=None, ok=False), allow_nan=False)
    with open(path + ".part", "w") as handle:
        handle.write(text)
    os.replace(path + ".part", path)


def failure(kind, message):
    return {"type": kind, "message": record.cut(message, record.MAX_REPR), "traceback": [], "cell": None}


def once(options, spec, index, repeat):
    """Makes one call, in this process, and writes what it did."""
    case = spec["cases"][index]
    folder = os.path.join(options.work, RESULT_NAME)
    result = {"schema": SCHEMA, "ok": False, "error": None, "result": None, "seconds": 0.0, "output": ""}
    out, err = record.Output(sys.__stdout__), record.Output(sys.__stderr__)
    copy = os.path.join(options.work, "copy-%s-%s" % (case["id"], repeat))
    began = time.monotonic()
    try:
        record.copy_project(options.repo, copy)
        where = case["cwd"]
        target = where if os.path.isabs(where) else os.path.normpath(os.path.join(copy, where))
        os.chdir(target)
        sys.path[:0] = [target, copy]
        function = getattr(load_wrapper(os.path.join(options.work, spec["wrapper"])), spec["function"])
        arguments = dict((name, decode(value)) for name, value in case["args"].items())
        # What the arguments used of the room that one call may keep is what they used when the call was recorded, so
        # that a result is described as it was then, by what it is and not by how much was left
        room = [record.MAX_CALL_CHARS]
        for value in arguments.values():
            record.summarize(value, room)
        sys.stdout, sys.stderr = out, err
        try:
            value = function(**arguments)
        finally:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
        result["result"] = record.summarize(value, room)
        result["ok"] = True
    except BaseException as error:
        trace = sys.exc_info()[2]
        result["error"] = record.error_of(error, trace.tb_next if trace is not None else None)
    result["seconds"] = round(time.monotonic() - began, 3)
    result["output"] = record.cut(out.text() + err.text(), record.MAX_TEXT)
    os.chdir(options.work)
    shutil.rmtree(copy, ignore_errors=True)
    write_call(folder, case["id"], repeat, result)

    return 0 if result["ok"] else 1


def run_all(options, spec):
    """Makes each call the number of times that was asked, one process at a time, within the time that was given. A call
    that does not work is not made again, since a second try would only say it again."""
    folder = os.path.join(options.work, RESULT_NAME)
    deadline = time.monotonic() + spec["seconds"]
    for index, case in enumerate(spec["cases"]):
        for repeat in range(spec["repeats"]):
            left = deadline - time.monotonic()
            if left < 1:
                return
            command = [
                sys.executable,
                os.path.abspath(__file__),
                "once",
                options.spec,
                "--case",
                str(index),
                "--repeat",
                str(repeat),
                "--repo",
                options.repo,
                "--work",
                options.work,
            ]
            process = subprocess.Popen(command, cwd=options.work, stdin=subprocess.DEVNULL)
            try:
                code = process.wait(timeout=left)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                write_call(
                    folder,
                    case["id"],
                    repeat,
                    {
                        "schema": SCHEMA,
                        "ok": False,
                        "error": failure("TimedOut", "It was stopped, as the time for this tool was used."),
                        "result": None,
                        "seconds": round(left, 3),
                        "output": "",
                    },
                )
                return
            written = os.path.join(folder, "%s-%s.json" % (case["id"], repeat))
            if not os.path.exists(written):
                write_call(
                    folder,
                    case["id"],
                    repeat,
                    {
                        "schema": SCHEMA,
                        "ok": False,
                        "error": failure("NoResult", "The process ended with code %s, without saying how." % code),
                        "result": None,
                        "seconds": 0.0,
                        "output": "",
                    },
                )
            if code != 0:
                break


def main(arguments):
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("run", "once"))
    parser.add_argument("spec")
    parser.add_argument("--case", type=int, default=0)
    parser.add_argument("--repeat", type=int, default=0)
    parser.add_argument("--repo", default=record.REPO)
    parser.add_argument("--work", default=record.WORK)
    options = parser.parse_args(arguments)
    with open(os.path.join(options.work, options.spec), encoding="utf-8") as handle:
        spec = json.load(handle)
    if options.mode == "once":
        return once(options, spec, options.case, options.repeat)
    limit = os.environ.get("LUMI_TIME_LIMIT", "")
    if limit.isdigit():
        # Ends the run if whoever started it is gone, since a container does not stop for that
        watchdog = threading.Timer(int(limit), os._exit, [124])
        watchdog.daemon = True
        watchdog.start()
    os.makedirs(os.path.join(options.work, RESULT_NAME), exist_ok=True)
    run_all(options, spec)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
