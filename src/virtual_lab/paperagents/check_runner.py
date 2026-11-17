"""Runs some of the tests that a paper's own code comes with, in the paper's environment, and says how they went.

This is not part of Lumi's own code, and nothing imports it. It is written into the folder that a run is given, beside a
copy of tutorial_runner.py (as lumi_record.py), whose way of copying the project it uses. It is run by the Python of the
environment that was built for the paper's code, which can be any from 3.7, so it needs nothing but the standard
library and is written in the syntax of the oldest.

It is given a file that lists tests by their ids, as pytest names them. It copies the project, so that what the tests
write is left in the copy, and runs pytest on those tests in the copy, if pytest is in the environment: nothing is
installed, as the container has no network. What the tests came to is read from the report that pytest writes, and
written to a file, with a short account of each that did not pass.

It does not make the run safe: the container it is run in does that. Nor does it say whether the tests prove anything.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ElementTree

import lumi_record as record

SCHEMA = 1
RESULT_FILE = "tests.json"
REPORT_FILE = "junit.xml"
MAX_FAILURES = 10
MAX_MESSAGE = 300
MAX_OUTPUT = 4000
NO_PYTEST = "No module named pytest"


def clip(text, limit):
    text = " ".join(str(text).split())

    return text if len(text) <= limit else text[: limit - 3] + "..."


def read_report(path):
    """How many of the tests passed, failed, raised an error, or were skipped, and what the first that did not pass
    said, from the report that pytest wrote, or None if there is no report that can be read."""
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return None
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    failures = []
    for case in root.iter("testcase"):
        name = "%s::%s" % (case.get("classname", ""), case.get("name", ""))
        problem = None
        if case.find("failure") is not None:
            counts["failed"] += 1
            problem = case.find("failure")
        elif case.find("error") is not None:
            counts["errors"] += 1
            problem = case.find("error")
        elif case.find("skipped") is not None:
            counts["skipped"] += 1
        else:
            counts["passed"] += 1
        if problem is not None and len(failures) < MAX_FAILURES:
            said = problem.get("message") or problem.text or ""
            failures.append({"name": clip(name, 200), "message": clip(said, MAX_MESSAGE)})
    counts["tests"] = sum(counts.values())

    return counts, failures


def finish(options, **fields):
    result = {
        "schema": SCHEMA,
        "ran": False,
        "reason": None,
        "tests": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "failures": [],
        "seconds": 0.0,
        "output": "",
    }
    result.update(fields)
    folder = os.path.join(options.work, record.RESULT_NAME)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, RESULT_FILE)
    with open(path + ".part", "w") as handle:
        json.dump(result, handle)
    os.replace(path + ".part", path)

    return 0


def run_tests(options, spec):
    copy = os.path.join(options.work, "copy-tests")
    report = os.path.join(options.work, record.RESULT_NAME, REPORT_FILE)
    os.makedirs(os.path.dirname(report), exist_ok=True)
    record.copy_project(options.repo, copy)
    command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--junitxml=" + report, "--"]
    command += spec["tests"]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(item for item in (copy, environment.get("PYTHONPATH", "")) if item)
    began = time.monotonic()
    process = subprocess.Popen(
        command, cwd=copy, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    timer = threading.Timer(spec["seconds"], process.kill)
    timer.daemon = True
    timer.start()
    try:
        text = process.communicate()[0].decode("utf-8", "replace")
    finally:
        timer.cancel()
    seconds = round(time.monotonic() - began, 3)
    shutil.rmtree(copy, ignore_errors=True)
    output = text[-MAX_OUTPUT:]
    if NO_PYTEST in text and not os.path.exists(report):
        return finish(
            options,
            reason="pytest is not in the environment, and nothing can be installed",
            seconds=seconds,
            output=output,
        )
    read = read_report(report)
    if read is None:
        return finish(
            options, reason="pytest did not write a report of how the tests went", seconds=seconds, output=output
        )
    counts, failures = read

    return finish(options, ran=True, failures=failures, seconds=seconds, output=output, **counts)


def main(arguments):
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("run",))
    parser.add_argument("spec")
    parser.add_argument("--repo", default=record.REPO)
    parser.add_argument("--work", default=record.WORK)
    options = parser.parse_args(arguments)
    with open(os.path.join(options.work, options.spec), encoding="utf-8") as handle:
        spec = json.load(handle)
    limit = os.environ.get("LUMI_TIME_LIMIT", "")
    if limit.isdigit():
        # Ends the run if whoever started it is gone, since a container does not stop for that
        watchdog = threading.Timer(int(limit), os._exit, [124])
        watchdog.daemon = True
        watchdog.start()

    return run_tests(options, spec)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
