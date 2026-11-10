"""Runs one tutorial or example of a paper's code, in the paper's environment, and says what happened.

This is not part of Lumi's own code, and nothing imports it. It is written into the folder that a run is given, and run
by the Python of the environment that was built for the paper's code, which can be any from 3.7. So it needs nothing but
the standard library, and is written in the syntax of the oldest of those.

It copies the project to a folder that can be written to, since a tutorial writes beside itself, and runs the script, or
the code cells of the notebook one after another in one namespace, from the folder that it is in. Then it writes one
file with what it saw: what each cell printed, the calls that the tutorial made to the project's own functions (what
went in, and what came out), and the files that the tutorial wrote. Everything it keeps is cut to a size, and what was
cut is said.

It does not make the run safe: the container it is run in does that. Nor does it grade anything. What it writes is what
a run did, and a later check says whether another run did the same.
"""

import argparse
import ast
import hashlib
import inspect
import json
import linecache
import math
import os
import re
import runpy
import shutil
import stat
import sys
import threading
import time
import traceback

SCHEMA = 1

REPO = "/opt/paper/repo"
WORK = "/workspace"
COPY_NAME = "repo"
RESULT_NAME = ".lumi-result"

# How much of anything is kept: of the text a cell printed or a value showed, how many cells, how many calls (and how
# many to one function, so that a loop that calls one a thousand times does not fill the record), how much of one
# call's values, how many cells of a table or an array are given as values, and how much is hashed
MAX_TEXT = 4000
MAX_REPR = 500
MAX_CELLS = 300
MAX_SKIPPED = 5
MAX_CALLS = 100
MAX_PER_FUNCTION = 4
MAX_CALL_CHARS = 40_000
MAX_VALUE_CELLS = 10_000
MAX_HASHED = 50 << 20
MAX_TABLE_CELLS = 5_000_000

# The files a tutorial wrote: how many are listed, how big one may be to be kept, how much is kept in all, and how big
# one may be to be hashed
MAX_FILES = 200
MAX_KEPT_FILE = 1 << 20
MAX_KEPT_TOTAL = 20 << 20
MAX_HASHED_FILE = 256 << 20
TRACE_LINES = 30

NOT_WRITTEN = ("__pycache__", ".ipynb_checkpoints", ".pytest_cache", ".git")
GENERATORS = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ITERABLE_COROUTINE | inspect.CO_ASYNC_GENERATOR
ADDRESS = re.compile(r" at 0x[0-9a-fA-F]+")
# What a notebook's cell magic leaves a cell that is Python after its first line
KEPT_MAGICS = ("%%time", "%%timeit", "%%capture", "%%prun")


def cut(text, limit=MAX_TEXT):
    return text if len(text) <= limit else text[:limit] + " [cut]"


def shown(value, limit=MAX_REPR):
    """What a value looks like, without the address that an object has in memory, which is not the same twice."""
    try:
        text = repr(value)
    except Exception:
        text = "<" + type(value).__name__ + " that could not be shown>"

    return cut(ADDRESS.sub(" at 0x", text), limit)


def type_name(value):
    kind = type(value)
    module = getattr(kind, "__module__", "")

    return kind.__qualname__ if module in ("builtins", "") else module + "." + kind.__qualname__


class NotPlain(Exception):
    """A value that is not made only of what JSON has, or is more than there is room for."""


def plain(value, room, depth=0):
    """A value as JSON, if it is made of nothing else: exact types only, since a subclass may mean more than its parent,
    and a tuple or a set is not a list. A number that is not finite is written out as a word, as JSON has none."""
    room[0] -= 8
    if room[0] < 0 or depth > 8:
        raise NotPlain()
    kind = type(value)
    if value is None or kind is bool or kind is int:
        return value
    if kind is float:
        return value if math.isfinite(value) else {"$float": repr(value)}
    if kind is str:
        room[0] -= len(value)
        if room[0] < 0:
            raise NotPlain()
        return value
    if kind is list:
        return [plain(item, room, depth + 1) for item in value]
    if kind is dict:
        kept = {}
        for key, item in value.items():
            if type(key) is not str:
                raise NotPlain()
            room[0] -= len(key)
            kept[key] = plain(item, room, depth + 1)
        return kept
    raise NotPlain()


def attribute(value, name):
    try:
        return getattr(value, name, None)
    except Exception:
        return None


def fingerprint(value):
    """A hash of an array or a table, which says whether two are the same without keeping them."""
    try:
        shape = attribute(value, "shape")
        dtype = attribute(value, "dtype")
        if dtype is not None and hasattr(value, "tobytes") and getattr(dtype, "kind", "O") != "O":
            if (attribute(value, "nbytes") or MAX_HASHED + 1) <= MAX_HASHED:
                return hashlib.sha256(value.tobytes()).hexdigest()
        elif hasattr(value, "to_csv") and isinstance(shape, tuple) and len(shape) == 2:
            if shape[0] * shape[1] <= MAX_TABLE_CELLS:
                return hashlib.sha256(value.to_csv().encode("utf-8")).hexdigest()
    except Exception:
        pass

    return None


def values_of(value, room):
    """The numbers in an array, or a table by its columns, if there are not many and are only plain values."""
    try:
        size = attribute(value, "size")
        if attribute(value, "dtype") is not None and hasattr(value, "tolist"):
            if isinstance(size, int) and size <= MAX_VALUE_CELLS:
                return plain(value.tolist(), room)
        shape = attribute(value, "shape")
        if hasattr(value, "to_dict") and attribute(value, "columns") is not None and isinstance(shape, tuple):
            if len(shape) == 2 and shape[0] * shape[1] <= MAX_VALUE_CELLS:
                return plain(value.to_dict("list"), room)
    except Exception:
        pass

    return None


def summarize(value, room):
    """What a value was, in a record that is bounded. A value that is plain JSON is kept as it is. Any other is given by
    its type and a short look at it, and by as much of what is in it as can be had: its shape, a hash of it, and its
    values if there are not many.

    :param room: How much is left of what one call may keep, which is lowered by what is kept.
    """
    name = type_name(value)
    trial = [room[0]]
    try:
        kept = plain(value, trial)
    except (NotPlain, RecursionError):
        pass
    else:
        room[0] = trial[0]
        return {"type": name, "plain": True, "value": kept}
    summary = {"type": name, "plain": False, "repr": shown(value)}
    shape = attribute(value, "shape")
    if isinstance(shape, tuple) and all(type(size) is int for size in shape):
        summary["shape"] = list(shape)
    dtype = attribute(value, "dtype")
    if dtype is not None:
        summary["dtype"] = cut(str(dtype), 40)
    digest = fingerprint(value)
    if digest is not None:
        summary["sha256"] = digest
    trial = [room[0]]
    values = values_of(value, trial)
    if values is not None:
        room[0] = trial[0]
        summary["values"] = values

    return summary


def relative(path, copy):
    """Where a file of code is, for the record: from the copy of the project, or from the site-packages it was installed
    to, and as it is otherwise."""
    prefix = copy.rstrip("/") + "/"
    if path.startswith(prefix):
        return path[len(prefix) :]
    marker = "site-packages/"
    if marker in path:
        return path[path.index(marker) + len(marker) :]

    return path


class Recorder(object):
    """Notes the calls that a tutorial makes to the project's own functions: those made from outside the project's code,
    and not those that its functions make to each other. Each is noted with what went in when it was made, and what came
    out. A call that ended by raising is noted with a result of None, as the profile hook is told no more than that."""

    def __init__(self, packages, copy):
        self.packages = packages
        self.copy = copy
        self.calls = []
        self.open = {}
        self.seen = 0
        self.per_function = {}
        self.busy = False
        self.cell = None

    def paper(self, frame):
        name = frame.f_globals.get("__name__")

        return isinstance(name, str) and name.split(".")[0] in self.packages

    def __call__(self, frame, event, argument):
        if self.busy:
            return
        try:
            if event == "call":
                self.entered(frame)
            elif event == "return":
                self.left(frame, argument)
        except Exception:
            self.busy = False

    def entered(self, frame):
        code = frame.f_code
        name = code.co_name
        if name[:1] in ("_", "<") or code.co_flags & GENERATORS or not self.paper(frame):
            return
        caller = frame.f_back
        if caller is None or self.paper(caller):
            return
        self.seen += 1
        module = frame.f_globals["__name__"]
        qualname = getattr(code, "co_qualname", name)
        key = (module, qualname)
        if len(self.calls) >= MAX_CALLS or self.per_function.get(key, 0) >= MAX_PER_FUNCTION:
            return
        self.per_function[key] = self.per_function.get(key, 0) + 1
        self.busy = True
        try:
            names = code.co_varnames[: code.co_argcount + code.co_kwonlyargcount]
            method = bool(names) and names[0] in ("self", "cls")
            room = [MAX_CALL_CHARS]
            local = frame.f_locals
            args = {}
            for argument in names[1:] if method else names:
                if argument in local:
                    args[argument] = summarize(local[argument], room)
            record = {
                "id": len(self.calls) + 1,
                "module": module,
                "function": name,
                "qualname": qualname,
                "method": method,
                "file": cut(relative(code.co_filename, self.copy), 300),
                "line": code.co_firstlineno,
                "args": args,
                "variadic": bool(code.co_flags & (inspect.CO_VARARGS | inspect.CO_VARKEYWORDS)),
                "result": None,
                "returned": False,
                "cell": self.cell,
                "from": {"file": cut(relative(caller.f_code.co_filename, self.copy), 300), "line": caller.f_lineno},
            }
        finally:
            self.busy = False
        self.calls.append(record)
        self.open[id(frame)] = (record, room)

    def left(self, frame, value):
        entry = self.open.pop(id(frame), None)
        if entry is None:
            return
        record, room = entry
        self.busy = True
        try:
            record["result"] = summarize(value, room)
            record["returned"] = True
        finally:
            self.busy = False


class Output(object):
    """Stands in for standard output while a cell runs: what is written goes on to where it was going, and a bounded
    part of it is kept for the record."""

    def __init__(self, real):
        self.real = real
        self.parts = []
        self.size = 0
        self.more = False

    def write(self, text):
        if self.real is not None:
            self.real.write(text)
        room = MAX_TEXT - self.size
        if room > 0:
            self.parts.append(text[:room])
            self.size += min(len(text), room)
        if len(text) > room:
            self.more = True

        return len(text)

    def flush(self):
        if self.real is not None:
            self.real.flush()

    def isatty(self):
        return False

    def __getattr__(self, name):
        return getattr(self.real, name)

    def text(self):
        return "".join(self.parts) + (" [cut]" if self.more else "")


def find_packages(copy):
    """The names that the project's code is imported by: its folders that are packages, at the top and in src/, and the
    modules at the top. Whether a function is the project's is whether its module is one of these."""
    found = set()
    for base in (copy, os.path.join(copy, "src")):
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            path = os.path.join(base, name)
            if os.path.isfile(os.path.join(path, "__init__.py")) and name.isidentifier():
                found.add(name)
            elif base == copy and name.endswith(".py") and name[:-3].isidentifier():
                if name not in ("setup.py", "conftest.py"):
                    found.add(name[:-3])

    return found


def copy_file(source, destination):
    shutil.copy2(source, destination, follow_symlinks=False)
    if not os.path.islink(destination):
        os.chmod(destination, os.lstat(destination).st_mode | stat.S_IWUSR)


def copy_project(source, destination):
    """Copies the project so that it can be written to. The files that were kept read-only are made writable in the
    copy, which is the one that the tutorial changes."""
    shutil.copytree(source, destination, symlinks=True, ignore=shutil.ignore_patterns(".git"), copy_function=copy_file)
    for current, directories, _ in os.walk(destination):
        for name in directories:
            path = os.path.join(current, name)
            if not os.path.islink(path):
                os.chmod(path, os.lstat(path).st_mode | stat.S_IRWXU)


def snapshot(root):
    """The files of a folder, by their paths from it, with their sizes and times, to tell what was written."""
    found = {}
    for current, directories, names in os.walk(root):
        directories[:] = [name for name in directories if name not in NOT_WRITTEN]
        for name in names:
            path = os.path.join(current, name)
            try:
                status = os.lstat(path)
            except OSError:
                continue
            if stat.S_ISREG(status.st_mode):
                found[os.path.relpath(path, root)] = (status.st_size, status.st_mtime_ns)

    return found


def digest_of(path):
    if os.path.getsize(path) > MAX_HASHED_FILE:
        return None
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)

    return hasher.hexdigest()


def written_files(copy, original, before, result_folder):
    """The files that the tutorial wrote: those that are new, and those whose contents are not what they were. The small
    ones are kept, in the folder of the result, beside the record of what they are."""
    listed = []
    kept_total = 0
    more = 0
    after = snapshot(copy)
    for relative_path in sorted(after):
        if before.get(relative_path) == after[relative_path]:
            continue
        path = os.path.join(copy, relative_path)
        try:
            digest = digest_of(path)
            is_new = relative_path not in before
            if not is_new and digest is not None and digest == digest_of(os.path.join(original, relative_path)):
                continue
        except OSError:
            continue
        if len(listed) >= MAX_FILES:
            more += 1
            continue
        size = after[relative_path][0]
        keep = size <= MAX_KEPT_FILE and kept_total + size <= MAX_KEPT_TOTAL
        if keep:
            target = os.path.join(result_folder, "files", relative_path)
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(path, target)
                kept_total += size
            except OSError:
                keep = False
        listed.append({"path": relative_path, "bytes": size, "sha256": digest, "new": is_new, "kept": keep})

    return listed, more


def error_of(error, trace, cell=None):
    """What went wrong, from the exception: its type and message, and the end of its traceback, without the frames that
    are this file's and Python's own for running a file."""
    # Python's own copy of runpy is frozen into it from 3.11, and has no file
    hidden = (os.path.abspath(__file__), runpy.__file__, "<frozen runpy>")
    frames = traceback.extract_tb(trace)
    while frames and (frames[0].filename in hidden or os.path.abspath(frames[0].filename) in hidden):
        frames = frames[1:]
    try:
        message = str(error)
    except Exception:
        message = ""
    lines = "".join(traceback.format_list(frames) + traceback.format_exception_only(type(error), error)).splitlines()

    return {
        "type": type(error).__name__,
        "message": cut(message, MAX_REPR),
        "traceback": [cut(line, 300) for line in lines[-TRACE_LINES:]],
        "cell": cell,
    }


def run_script(path, copy):
    directory = os.path.dirname(path)
    os.chdir(directory)
    sys.path[:0] = [directory, copy]
    sys.argv = [path]
    try:
        runpy.run_path(path, run_name="__main__")
    except SystemExit as error:
        if error.code not in (None, 0):
            return {"type": "SystemExit", "message": cut(str(error.code), MAX_REPR), "traceback": [], "cell": None}
    except BaseException as error:
        return error_of(error, sys.exc_info()[2])

    return None


def notebook_cells(path):
    with open(path, encoding="utf-8") as handle:
        notebook = json.load(handle)
    cells = notebook.get("cells")
    if cells is None:
        cells = [cell for sheet in notebook.get("worksheets", []) for cell in sheet.get("cells", [])]

    return cells


def cell_source(cell):
    source = cell.get("source", cell.get("input", ""))

    return "".join(source) if isinstance(source, list) else str(source)


def without_magics(source):
    """A cell's code without the lines that only a notebook's kernel reads: line magics, and shell lines. A cell that is
    one cell magic is not run, except the few that are only about how the rest of it is run.

    :return: The code, or None if the cell is not to be run, and the lines that were left out.
    """
    lines = source.splitlines()
    first = lines[0].strip() if lines else ""
    if first.startswith("%%"):
        if first.split()[0] not in KEPT_MAGICS:
            return None, [cut(first, 100)]
        lines = lines[1:]
    kept, left_out = [], []
    for line in lines:
        if line.lstrip().startswith(("%", "!")):
            left_out.append(cut(line.strip(), 100))
            kept.append(line[: len(line) - len(line.lstrip())] + "pass")
        else:
            kept.append(line)

    return "\n".join(kept), left_out


def run_notebook(path, copy, recorder):
    directory = os.path.dirname(path)
    os.chdir(directory)
    sys.path[:0] = [directory, copy]

    def display(*objects, **options):
        for item in objects:
            print(shown(item, MAX_TEXT))

    namespace = {"__name__": "__main__", "__file__": path, "display": display}
    cells = []
    try:
        listed = notebook_cells(path)
    except (OSError, ValueError, AttributeError) as error:
        return (
            {"type": "NotebookUnreadable", "message": cut(str(error), MAX_REPR), "traceback": [], "cell": None},
            [],
            0,
        )
    code_cells = [(index, cell_source(cell)) for index, cell in enumerate(listed) if cell.get("cell_type") == "code"]
    for index, source in code_cells:
        record = {
            "index": index,
            "ok": True,
            "seconds": 0.0,
            "output": "",
            "result": None,
            "skipped": [],
            "error": None,
        }
        if len(cells) < MAX_CELLS:
            cells.append(record)
        code, left_out = without_magics(source)
        record["skipped"] = left_out[:MAX_SKIPPED]
        if code is None or not code.strip():
            continue
        name = "<cell %d>" % (index + 1)
        linecache.cache[name] = (len(code), None, code.splitlines(True), name)
        recorder.cell = index
        out, err = Output(sys.__stdout__), Output(sys.__stderr__)
        sys.stdout, sys.stderr = out, err
        began = time.monotonic()
        try:
            tree = ast.parse(code, name)
            last = ast.Expression(tree.body.pop().value) if tree.body and isinstance(tree.body[-1], ast.Expr) else None
            exec(compile(tree, name, "exec"), namespace)
            if last is not None:
                value = eval(compile(last, name, "eval"), namespace)
                if value is not None:
                    record["result"] = shown(value, MAX_TEXT)
        except BaseException as error:
            record["ok"] = False
            if isinstance(error, SystemExit) and error.code in (None, 0):
                record["ok"] = True
            else:
                record["error"] = error_of(error, sys.exc_info()[2], index)
        finally:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
            record["seconds"] = round(time.monotonic() - began, 3)
            record["output"] = cut(out.text() + err.text(), MAX_TEXT)
            recorder.cell = None
        if not record["ok"]:
            return record["error"], cells, len(code_cells)

    return None, cells, len(code_cells)


def write_result(folder, result):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "result.json")
    try:
        text = json.dumps(result, allow_nan=False)
    except (TypeError, ValueError):
        text = json.dumps({**result, "calls": [], "cells": []}, allow_nan=False)
    with open(path + ".part", "w") as handle:
        handle.write(text)
    os.replace(path + ".part", path)


def main(arguments):
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("script", "notebook"))
    parser.add_argument("path")
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--work", default=WORK)
    options = parser.parse_args(arguments)
    result_folder = os.path.join(options.work, RESULT_NAME)
    copy = os.path.join(options.work, COPY_NAME)
    began = time.monotonic()
    limit = os.environ.get("LUMI_TIME_LIMIT", "")
    if limit.isdigit():
        # Ends the run if whoever started it is gone, since a container does not stop for that
        watchdog = threading.Timer(int(limit), os._exit, [124])
        watchdog.daemon = True
        watchdog.start()
    result = {
        "schema": SCHEMA,
        "kind": options.kind,
        "path": options.path,
        "python": sys.version.split()[0],
        "ok": False,
        "error": None,
        "seconds": 0.0,
        "cells": [],
        "cells_total": 0,
        "calls": [],
        "calls_seen": 0,
        "files": [],
        "files_more": 0,
        "packages": [],
    }
    try:
        os.makedirs(result_folder, exist_ok=True)
        copy_project(options.repo, copy)
        before = snapshot(copy)
        packages = find_packages(copy)
        result["packages"] = sorted(packages)[:20]
        recorder = Recorder(packages, copy)
        path = os.path.join(copy, options.path)
        sys.setprofile(recorder)
        try:
            if options.kind == "script":
                error, cells, total = run_script(path, copy), [], 0
            else:
                error, cells, total = run_notebook(path, copy, recorder)
        finally:
            sys.setprofile(None)
        os.chdir(options.work)
        result.update(ok=error is None, error=error, cells=cells, cells_total=total)
        result["calls"], result["calls_seen"] = recorder.calls, recorder.seen
        result["files"], result["files_more"] = written_files(copy, options.repo, before, result_folder)
    except BaseException as error:
        result["error"] = error_of(error, sys.exc_info()[2])
        result["error"]["runner"] = True
    result["seconds"] = round(time.monotonic() - began, 3)
    sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
    write_result(result_folder, result)
    sys.stdout.flush()

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
