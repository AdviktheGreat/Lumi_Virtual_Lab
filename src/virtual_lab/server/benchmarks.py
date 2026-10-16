"""What the researcher has the lab answer of Biomni's benchmarks, and how well it does.

A run is one benchmark, put to the lab's lead alone or to its team, kept in a directory of its own in the workspace's
benchmarks/runs/ beside the files of the benchmarks, which are fetched once into benchmarks/files/. The answering is the
library's: each question's result is saved as it is scored, so a run that stops, for its budget, a run of failures, or a
request to stop, carries on where it stopped when it is started again. It takes minutes or hours, so it is a job, which
a page follows and may stop.

A run is set up when it is made, with who answers and where code runs, and keeps that, so that answering it later is
answering the same questions in the same way, as the library requires of a run that is carried on.
"""

import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from virtual_lab.benchmarks import (
    Benchmark,
    BenchmarkError,
    BiomniEval1Benchmark,
    HumanitysLastExam,
    LabBench,
    Question,
    download_benchmarks,
    is_verified,
)
from virtual_lab.constants import BENCHMARK_FILES
from virtual_lab.environment import StoppedError
from virtual_lab.evaluation import (
    RESULTS_DIR,
    SUMMARY_FILE,
    EvaluationReport,
    QuestionResult,
    SingleAgent,
    SolverContext,
    TeamMeeting,
    run_benchmark,
    save_json,
)
from virtual_lab.llm import ModelSource
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server.code import CodeSetup
from virtual_lab.server.config import ChatConfig, resolve_config
from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.jobs import Job, JobConflictError, Jobs
from virtual_lab.server.papers import StopWork, check_budget, check_count, check_flag, check_model, money
from virtual_lab.server.transcripts import read_turns
from virtual_lab.server.workspace import Workspace, claim_directory, has_control_character, read_json

# What a run is, kept beside what the library saves of it, and where code runs for it
LAB_FILE = "lab.json"
SESSION_DIR = "session"
FILES_DIR = "files"
RUNS_DIR = "runs"

# The one kind of job, of which only one is running at a time, since each may start a container and spends
JOB_KIND = "benchmark"

# The most runs, questions to ask in one, and rounds of discussion or criticism
MAX_RUNS = 200
MAX_QUESTIONS = 100_000
MAX_ROUNDS = 5

MAX_TITLE_CHARS = 200

# The most of a question's prompt a list shows, in characters
PROMPT_PREVIEW_CHARS = 160

# Of a run's id and a question's task, which name the directories and files that hold them
NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")

# The benchmarks, each with what it is
BENCHMARKS = {
    "biomni_eval1": (
        "Biomni-Eval1",
        "433 questions in ten tasks: CRISPR delivery, causal genes from three GWAS sources, variant prioritization, "
        "LAB-Bench's DbQA and SeqQA, patient gene detection, rare disease diagnosis, and screen gene retrieval. Each "
        "task is scored by its own rule.",
    ),
    "lab_bench_dbqa": (
        "LAB-Bench: DbQA",
        "Multiple choice questions about biological databases, with a choice to say there is not enough information.",
    ),
    "lab_bench_seqqa": (
        "LAB-Bench: SeqQA",
        "Multiple choice questions about sequences, with a choice to say there is not enough information.",
    ),
    "hle": (
        "Humanity's Last Exam",
        "The multiple choice questions in biology and medicine that Biomni samples, asked as the exam asks them.",
    ),
}

# Which of LAB-Bench's files Biomni reads, and what each is
SUBSETS = {
    "test": "The questions Biomni's own agent is asked",
    "sampled": "Biomni's sample of all of them",
    "all": "All of LAB-Bench's questions of this kind",
}

# Who answers each question
SOLVERS = {
    "single": (
        "The lead alone",
        "The lead answers each question alone, as Biomni's agent does, with no critic unless "
        "rounds of criticism are asked for.",
    ),
    "team": (
        "The lead and the team",
        "The lead holds a team meeting on each question, and its closing answer is read.",
    ),
}

# What is asked of a run for each benchmark, besides those of every one: the solver, the rounds, and how many questions
OPTIONS = {
    "biomni_eval1": {"tasks"},
    "lab_bench_dbqa": {"subset"},
    "lab_bench_seqqa": {"subset"},
    "hle": {"leave_out_images"},
}


def check_name(text: str) -> bool:
    return bool(text) and all(char in NAME_CHARS for char in text) and text not in {".", ".."}


def is_lab(value: Any) -> bool:
    """Whether what a run's file holds is a run's: its title, benchmark, solver, rounds, options, how many questions,
    the configuration it answers with, and when it was made."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("title"), str)
        and isinstance(value.get("created_at"), str)
        and value.get("benchmark") in BENCHMARKS
        and value.get("solver") in SOLVERS
        and isinstance(value.get("rounds"), int)
        and isinstance(value.get("options"), dict)
        and (value.get("limit") is None or isinstance(value["limit"], int))
        and isinstance(value.get("questions"), int)
        and isinstance(value.get("config"), dict)
    )


def finite(value: Any) -> float | None:
    """A measure as a page is sent it: a number, or None where it is not defined."""
    if isinstance(value, bool) or not isinstance(value, int | float) or value != value or abs(value) == float("inf"):
        return None

    return float(value)


def saved_result(path: Path) -> QuestionResult | None:
    """A result as the library saved it, or None where there is none that can be read."""
    saved = read_json(path)
    if not isinstance(saved, dict):
        return None
    try:
        return QuestionResult.from_dict(saved)
    except (KeyError, TypeError):
        return None


def saved_results(directory: Path, asked: list[Question]) -> dict[Question, QuestionResult]:
    """The results saved for the questions that were asked."""
    found = {}
    for question in asked:
        if (result := saved_result(directory / RESULTS_DIR / question.task / f"{question.id}.json")) is not None:
            found[question] = result

    return found


def total_cost(results: list[QuestionResult]) -> float | None:
    """What the finished questions cost, or None if any one's cost cannot be worked out."""
    costs = [result.cost for result in results]

    return None if any(cost is None for cost in costs) else sum(costs)  # type: ignore[misc]


def tally(directory: Path, chosen: "Selection") -> tuple[dict[Question, QuestionResult], dict[str, float | None]]:
    """The results saved for a run's questions, and the benchmark's measures over them, as the library works them out
    at the end of a run: a question not yet answered is not counted."""
    found = saved_results(directory, chosen.asked)
    answers = [(question, found[question].answer) for question in chosen.asked if question in found]
    metrics = {name: finite(value) for name, value in chosen.benchmark.metrics(answers).items()}

    return found, metrics


def describe_report(report: EvaluationReport) -> str:
    """What a run did, in a sentence or two."""
    line = f"Answered {report.finished} of {report.questions} questions"
    if report.failed:
        line += f" ({report.failed} failed)"
    if (accuracy := finite(report.metrics.get("accuracy"))) is not None:
        line += f", {accuracy:.1%} right"
    line += f", spending {money(report.spent)}."
    if report.stopped is not None:
        line += f" Stopped: {report.stopped}"

    return line


@dataclass
class Selection:
    """The questions a run asks, of a benchmark."""

    benchmark: Benchmark
    asked: list[Question]


class Watched:
    """A solver that tells the job which question it is on, and leaves when it is asked to stop. What it describes is
    the solver's own, so that a run it was begun with is carried on with it."""

    def __init__(self, solver: Any, job: Job, finished: Callable[[], int]) -> None:
        self.solver = solver
        self.job = job
        self.finished = finished

    def __call__(self, question: Question, context: SolverContext) -> Any:
        if self.job.stop.is_set():
            raise StopWork
        self.job.update(f"Answering {question.key}", finished=self.finished())

        return self.solver(question, context)

    def describe(self) -> Any:
        return self.solver.describe()


class BenchmarkRuns:
    """The runs that ask the lab Biomni's benchmarks, and the files of the benchmarks, kept in a workspace.

    :param workspace: Where they are kept.
    :param jobs: Where the answering is done, which a page follows.
    :param missing_keys: Says which variables a model's provider needs that are not set.
    :param client: An OpenAI client to answer with, which is for tests.
    :param chat_models: The chat models to answer with, which is for tests.
    :param docker_missing: Says what code in Docker, set up as it is given, cannot run without, or None to leave that
        until the code first runs.
    """

    def __init__(
        self,
        workspace: Workspace,
        jobs: Jobs,
        missing_keys: Callable[[str], list[str]],
        client: Any = None,
        chat_models: ModelSource | None = None,
        docker_missing: Callable[[CodeSetup], list[dict[str, str]]] | None = None,
    ) -> None:
        self.workspace = workspace
        self.jobs = jobs
        self.missing_keys = missing_keys
        self.client = client
        self.chat_models = chat_models
        self.docker_missing = docker_missing
        # What fetches the benchmarks' files, which is for tests
        self.download = download_benchmarks
        # Held while a file is fetched, and from checking that nothing is being done to a run to starting something,
        # so that nothing is begun in a run that is being removed
        self._lock = threading.Lock()
        self._fetching = threading.Lock()
        # What was found of the files, and of what they hold, for the files as they were
        self._seen: tuple[tuple[Any, ...], dict[str, Any]] | None = None

    # Files

    @property
    def files_dir(self) -> Path:
        return self.workspace.benchmarks_dir / FILES_DIR

    @property
    def runs_dir(self) -> Path:
        return self.workspace.benchmarks_dir / RUNS_DIR

    def files(self) -> dict[str, Any]:
        """Whether the benchmarks' files are there, and what they hold, which is not known until they are."""
        stamp = tuple(
            (name, stat.st_mtime_ns, stat.st_size) if (stat := self._stat(name)) is not None else (name,)
            for name in BENCHMARK_FILES
        )
        if self._seen is None or self._seen[0] != stamp:
            missing = [name for name in BENCHMARK_FILES if not is_verified(self.files_dir / name, name)]
            held: dict[str, Any] = {"tasks": None, "subsets": None, "images": None, "problem": None}
            if not missing:
                try:
                    held = self.contents()
                except (ImportError, BenchmarkError, OSError, ValueError, KeyError) as error:
                    held["problem"] = str(error)
            self._seen = (stamp, {"directory": str(self.files_dir), "missing": missing, **held})

        return dict(self._seen[1])

    def _stat(self, name: str) -> Any:
        try:
            return (self.files_dir / name).stat()
        except OSError:
            return None

    def contents(self) -> dict[str, Any]:
        """What the files hold: Biomni-Eval1's tasks, how many questions each subset of LAB-Bench has, and how many
        questions of Humanity's Last Exam need an image."""
        eval1 = BiomniEval1Benchmark(self.files_dir)
        counts: dict[str, int] = {}
        for question in eval1:
            counts[question.task] = counts.get(question.task, 0) + 1
        subsets = {
            f"lab_bench_{dataset.lower()}": {
                subset: len(LabBench(self.files_dir, dataset, subset))  # type: ignore[arg-type]
                for subset in SUBSETS
            }
            for dataset in ("DbQA", "SeqQA")
        }
        exam = HumanitysLastExam(self.files_dir)

        return {
            "tasks": counts,
            "subsets": subsets,
            "images": {"questions": len(exam), "with_images": sum(question.metadata["has_image"] for question in exam)},
            "problem": None,
        }

    def fetch_files(self) -> dict[str, Any]:
        """Fetches the benchmarks' files, which are about 4 MB, and checks them against the ones that are pinned. What
        is there already is left alone.

        :raises ApiError: If a file cannot be fetched, or is not the one that is pinned.
        """
        with self._fetching:
            try:
                self.download(self.files_dir)
            except BenchmarkError as error:
                raise ApiError(502, "unexpected_files", str(error)) from None
            except (requests.RequestException, OSError) as error:
                raise ApiError(502, "unreachable", f"The benchmarks' files could not be fetched: {error}") from None

        return self.describe()

    # Runs

    def describe(self) -> dict[str, Any]:
        """Every run, the latest first, and what a page needs to make one."""
        files = self.files()
        ready = not files["missing"]
        runs = []
        if self.runs_dir.is_dir():
            for directory in self.runs_dir.iterdir():
                lab = read_json(directory / LAB_FILE)
                if check_name(directory.name) and directory.is_dir() and is_lab(lab):
                    runs.append(self.entry(directory, lab))

        benchmarks = []
        for name, (title, summary) in BENCHMARKS.items():
            counts = files["subsets"].get(name) if files["subsets"] is not None else None
            benchmarks.append(
                {
                    "id": name,
                    "title": title,
                    "summary": summary,
                    "tasks": (
                        [{"name": task, "questions": count} for task, count in files["tasks"].items()]
                        if name == "biomni_eval1" and files["tasks"] is not None
                        else None
                    ),
                    "subsets": (
                        [
                            {"id": subset, "summary": SUBSETS[subset], "questions": count}
                            for subset, count in counts.items()
                        ]
                        if counts is not None
                        else None
                    ),
                    "images": (
                        files["images"]["with_images"] if name == "hle" and files["images"] is not None else None
                    ),
                    "questions": self.size_of(name, files),
                }
            )

        settings = self.workspace.load_settings()

        return {
            "runs": sorted(runs, key=lambda run: (run["created_at"], run["id"]), reverse=True),
            "benchmarks": benchmarks,
            "files": {
                "ready": ready,
                "directory": files["directory"],
                "missing": files["missing"],
                "problem": files["problem"],
            },
            "solvers": [{"id": name, "title": title, "summary": summary} for name, (title, summary) in SOLVERS.items()],
            "max_rounds": MAX_ROUNDS,
            "max_questions": MAX_QUESTIONS,
            "model": settings.model,
            "code": {"where": settings.code, "sandbox": settings.sandbox},
        }

    @staticmethod
    def size_of(name: str, files: dict[str, Any]) -> int | None:
        """How many questions a benchmark has, before it is narrowed."""
        if name == "biomni_eval1":
            return sum(files["tasks"].values()) if files["tasks"] is not None else None
        if name == "hle":
            return files["images"]["questions"] if files["images"] is not None else None

        return files["subsets"][name]["test"] if files["subsets"] is not None else None

    def entry(self, directory: Path, lab: dict[str, Any]) -> dict[str, Any]:
        """A run as a list shows it: what it is, who answers, and how far the answering has got."""
        summary = read_json(directory / SUMMARY_FILE)
        summary = summary if isinstance(summary, dict) else {}
        results = directory / RESULTS_DIR
        job = self.running(directory.name)
        metrics = summary.get("metrics")

        return {
            "id": directory.name,
            "title": lab["title"],
            "benchmark": lab["benchmark"],
            "solver": lab["solver"],
            "rounds": lab["rounds"],
            "model": lab["config"].get("model"),
            "created_at": lab["created_at"],
            "questions": lab["questions"],
            "finished": len(list(results.glob("*/*.json"))) if results.is_dir() else 0,
            "failed": summary.get("failed"),
            "accuracy": finite(metrics.get("accuracy")) if isinstance(metrics, dict) else None,
            "cost": finite(summary.get("cost")),
            "spent": finite(summary.get("spent")),
            "stopped": summary.get("stopped"),
            "job": job.id if job is not None else None,
        }

    def lookup(self, run_id: str) -> tuple[Path, dict[str, Any]]:
        """Where a run is kept, and what it is.

        :raises ApiError: If there is no run with this id.
        """
        directory = self.runs_dir / run_id
        lab = read_json(directory / LAB_FILE) if check_name(run_id) else None
        if not is_lab(lab):
            raise not_found("benchmark run with that id")

        return directory, lab

    def running(self, run_id: str) -> Job | None:
        """The job that is answering a run's questions, if one is."""
        return next((job for job in self.jobs.active() if job.kind == JOB_KIND and job.subject == run_id), None)

    def ready(self) -> dict[str, Any]:
        """What the benchmarks' files hold, once they are there.

        :raises ApiError: If they are not there, or cannot be read.
        """
        files = self.files()
        if files["missing"]:
            raise ApiError(409, "files_missing", "Fetch the benchmarks' files first", missing=files["missing"])
        if files["problem"] is not None:
            raise ApiError(422, "unavailable", files["problem"])

        return files

    def selection(self, benchmark_id: str, options: dict[str, Any], limit: int | None) -> Selection:
        """The questions a run asks, from the benchmark's files.

        :raises ApiError: If the files are not there, cannot be read, or the options do not fit the benchmark.
        """
        self.ready()
        try:
            if benchmark_id == "biomni_eval1":
                benchmark: Benchmark = BiomniEval1Benchmark(self.files_dir, options.get("tasks"))
            elif benchmark_id == "hle":
                benchmark = HumanitysLastExam(self.files_dir)
            else:
                dataset = "DbQA" if benchmark_id == "lab_bench_dbqa" else "SeqQA"
                benchmark = LabBench(self.files_dir, dataset, options.get("subset", "test"))
        except (ImportError, BenchmarkError, OSError, ValueError) as error:
            raise ApiError(422, "unavailable", str(error)) from None
        asked = [
            question
            for question in benchmark
            if not (options.get("leave_out_images") and question.metadata.get("has_image"))
        ]
        if limit is not None:
            asked = asked[:limit]

        return Selection(benchmark, asked)

    @staticmethod
    def check_options(benchmark_id: str, options: dict[str, Any], files: dict[str, Any]) -> dict[str, Any]:
        """What a run is asked of its benchmark, as it is kept: what was sent, made sure of and without what is not for
        that benchmark.

        :raises ApiError: If something is sent that is not for the benchmark, or what is sent is wrong.
        """
        title = BENCHMARKS[benchmark_id][0]
        if extra := sorted(set(options) - OPTIONS[benchmark_id]):
            raise ApiError(422, "invalid", f"{', '.join(extra)} is not asked for when the benchmark is {title}")
        kept: dict[str, Any] = {}
        if benchmark_id == "biomni_eval1":
            tasks = options.get("tasks")
            if tasks is not None:
                known = files["tasks"] or {}
                if not isinstance(tasks, list) or not tasks or not all(isinstance(task, str) for task in tasks):
                    raise ApiError(422, "invalid", "Choose at least one task, by name")
                if unknown := [task for task in dict.fromkeys(tasks) if task not in known]:
                    raise ApiError(422, "invalid", f"{title} has no task {', '.join(unknown)}")
                kept["tasks"] = list(dict.fromkeys(tasks))
        elif benchmark_id == "hle":
            kept["leave_out_images"] = check_flag(options.get("leave_out_images", False), "leave_out_images")
        else:
            subset = options.get("subset", "test")
            if subset not in SUBSETS:
                raise ApiError(422, "invalid", f"The subset is one of {', '.join(SUBSETS)}, not {subset!r}")
            kept["subset"] = subset

        return kept

    def create(
        self,
        title: str,
        benchmark: str,
        solver: str,
        rounds: Any = None,
        limit: Any = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Makes a run with nothing answered yet, which keeps who answers and where code runs, as they are in the
        settings now.

        :param title: What it is called.
        :param benchmark: Which benchmark.
        :param solver: "single" for the lead alone, or "team" for the lead and the team.
        :param rounds: How many rounds of criticism the lead alone has, or of discussion the team has, or None for
            none of criticism and one of discussion.
        :param limit: How many questions to ask, the first ones, or None for all.
        :param options: What is asked of this benchmark: its tasks, subset, or whether to leave out the questions that
            refer to an image.
        :raises ApiError: If the title or an option is not fit, the files are not there, or there are too many runs.
        :return: Its id.
        """
        named = " ".join(title.split())
        if not named or len(named) > MAX_TITLE_CHARS or has_control_character(named):
            raise ApiError(422, "invalid", f"A run is called by one to {MAX_TITLE_CHARS} characters, not {title!r}")
        if benchmark not in BENCHMARKS:
            raise ApiError(422, "invalid", f"The benchmark is one of {', '.join(BENCHMARKS)}, not {benchmark!r}")
        if solver not in SOLVERS:
            raise ApiError(422, "invalid", f"Who answers is one of {', '.join(SOLVERS)}, not {solver!r}")
        turns = (1 if solver == "team" else 0) if rounds is None else check_count(rounds, "The rounds", 0, MAX_ROUNDS)
        asked_for = None if limit is None else check_count(limit, "The number of questions", 1, MAX_QUESTIONS)
        files = self.ready()
        kept = self.check_options(benchmark, options or {}, files)
        chosen = self.selection(benchmark, kept, asked_for)
        if not chosen.asked:
            raise ApiError(422, "invalid", "That leaves no question to ask")

        settings = self.workspace.load_settings()
        try:
            config = resolve_config(
                {"model": settings.model, "tools": [], "mcp": [], "data": [], "software": [], "functions": []},
                settings,
                self.workspace,
            )
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from None

        root = self.runs_dir
        root.mkdir(parents=True, exist_ok=True)
        if sum(1 for path in root.iterdir() if path.is_dir()) >= MAX_RUNS:
            raise ApiError(409, "too_many", f"No more than {MAX_RUNS} runs can be kept. Delete some first")
        directory = claim_directory(root, named)
        try:
            lab = {
                "title": named,
                "benchmark": benchmark,
                "solver": solver,
                "rounds": turns,
                "options": kept,
                "limit": asked_for,
                "questions": len(chosen.asked),
                "config": config.to_dict(),
                "created_at": utc_timestamp(),
            }
            save_json(directory / LAB_FILE, lab)
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise

        return directory.name

    def delete(self, run_id: str) -> None:
        """Deletes a run, with everything answered in it.

        :raises ApiError: If there is no run with this id, or its questions are being answered.
        """
        with self._lock:
            directory, _ = self.lookup(run_id)
            self.check_idle(run_id)
            shutil.rmtree(directory)

    def check_idle(self, run_id: str) -> None:
        if (job := self.running(run_id)) is not None:
            raise ApiError(409, "busy", f"{job.title} is running. Stop it first", job=job.snapshot())

    # What was answered

    def loaded(self, lab: dict[str, Any]) -> Selection | None:
        """The questions a run asks, or None where the benchmark's files cannot be read now."""
        try:
            return self.selection(lab["benchmark"], lab["options"], lab["limit"])
        except ApiError:
            return None

    def view(self, run_id: str) -> dict[str, Any]:
        """A run, with how each question was answered and the benchmark's measures over them.

        :raises ApiError: If there is no run with this id.
        """
        directory, lab = self.lookup(run_id)
        chosen = self.loaded(lab)
        rows: list[dict[str, Any]] = []
        tasks: dict[str, dict[str, Any]] = {}
        if chosen is not None:
            found, metrics = tally(directory, chosen)
            for question in chosen.asked:
                result = found.get(question)
                rows.append(self.row(question.task, question.id, question.prompt, result))
                task = tasks.setdefault(
                    question.task, {"task": question.task, "questions": 0, "finished": 0, "score": 0.0}
                )
                task["questions"] += 1
                if result is not None:
                    task["finished"] += 1
                    task["score"] += result.score
            results = list(found.values())
        else:
            # Without the benchmark's files only what was saved can be shown, with the measures it was left with
            summary = read_json(directory / SUMMARY_FILE)
            metrics = summary.get("metrics", {}) if isinstance(summary, dict) else {}
            results = []
            for path in sorted((directory / RESULTS_DIR).glob("*/*.json")):
                if (result := saved_result(path)) is not None:
                    results.append(result)
                    rows.append(self.row(result.task, result.id, None, result))

        code = lab["config"].get("code", {})

        return {
            **self.entry(directory, lab),
            "options": lab["options"],
            "limit": lab["limit"],
            "code": {key: code.get(key) for key in ("where", "sandbox", "network", "resources")},
            "lead": lab["config"].get("lead", {}).get("title"),
            "team": [member["title"] for member in lab["config"].get("team", [])] if lab["solver"] == "team" else [],
            "finished": len(results),
            "failed": sum(result.failed for result in results),
            "cost": finite(total_cost(results)),
            "accuracy": finite(metrics.get("accuracy")),
            "metrics": metrics,
            "tasks": [
                {
                    "task": task["task"],
                    "questions": task["questions"],
                    "finished": task["finished"],
                    "accuracy": task["score"] / task["finished"] if task["finished"] else None,
                }
                for task in tasks.values()
            ],
            "results": rows,
            "problem": None
            if chosen is not None
            else "The benchmarks' files cannot be read, so only what was saved is shown",
        }

    @staticmethod
    def row(task: str, number: int, prompt: str | None, result: QuestionResult | None) -> dict[str, Any]:
        """A question as a list shows it: what it is, and how it was answered if it was."""
        text = " ".join(prompt.split()) if prompt is not None else None
        if text is not None and len(text) > PROMPT_PREVIEW_CHARS:
            text = text[: PROMPT_PREVIEW_CHARS - 1].rstrip() + "…"

        return {
            "key": f"{task}/{number}",
            "task": task,
            "id": number,
            "prompt": text,
            "state": "unanswered" if result is None else "failed" if result.failed else "answered",
            "answer": result.answer if result is not None else None,
            "correct_answer": result.correct_answer if result is not None else None,
            "score": finite(result.score) if result is not None else None,
            "cost": finite(result.cost) if result is not None else None,
            "elapsed": finite(result.elapsed) if result is not None else None,
            "error": result.error if result is not None else None,
        }

    def question(self, run_id: str, task: str, number: str) -> dict[str, Any]:
        """One question of a run: what was asked, the answer that was read, and what was said in answering it.

        :raises ApiError: If there is no run with this id, or it neither asked nor can ask that question.
        """
        directory, lab = self.lookup(run_id)
        if not check_name(task) or not (number.isascii() and number.isdecimal()) or len(number) > 9:
            raise not_found("question with that name in the run")
        result = saved_result(directory / RESULTS_DIR / task / f"{number}.json")
        chosen = self.loaded(lab)
        asked = None
        if chosen is not None:
            asked = next((q for q in chosen.asked if q.task == task and q.id == int(number)), None)
        if asked is None and result is None:
            raise not_found("question with that name in the run")

        turns, truncated = None, False
        if result is not None and result.transcript:
            turns, truncated = self.turns_of(directory, result.transcript)
        correct = asked.answer if asked is not None else result.correct_answer if result is not None else None

        return {
            **self.row(task, int(number), None, result),
            "prompt": asked.prompt if asked is not None else None,
            "correct_answer": correct,
            "output": result.output if result is not None else None,
            "usage": result.usage if result is not None else None,
            "turns": turns,
            "truncated": truncated,
        }

    @staticmethod
    def turns_of(directory: Path, relative: str) -> tuple[list[dict[str, str]] | None, bool]:
        """What was said in answering a question, from the transcript the library saved, and whether it was cut short
        to be sent."""
        return read_turns(directory, relative)

    # Answering

    def start(self, run_id: str, max_cost: Any, max_cost_per_question: Any, retry_failed: Any) -> Job:
        """Starts answering the questions of a run that have not been, which are all of them the first time. A run that
        stopped carries on from there.

        :param max_cost: The most the run may spend, in USD, in all.
        :param max_cost_per_question: The most one question may spend, or None for no limit on one.
        :param retry_failed: Whether to ask again the questions an earlier run failed on.
        :raises ApiError: If there is no run with this id, a limit is not an amount, a key or a price is missing, Docker
            is needed and is not there, the benchmarks' files are not, or a run is being answered.
        """
        directory, lab = self.lookup(run_id)
        budget = check_budget(max_cost, "The most it may spend", required=True)
        per_question = check_budget(max_cost_per_question, "The most one question may spend", required=False)
        again = check_flag(retry_failed, "retry_failed")
        try:
            config = ChatConfig.from_dict(lab["config"])
        except (KeyError, TypeError, ValueError):
            raise ApiError(
                409, "invalid", "What this run answers with was not kept in a way that can be read"
            ) from None
        check_model(config.model, self.missing_keys)
        if self.docker_missing is not None and (missing := self.docker_missing(config.code)):
            raise ApiError(
                409,
                "setup_needed",
                " ".join(issue["message"] for issue in missing),
                missing=[issue["id"] for issue in missing],
            )
        chosen = self.selection(lab["benchmark"], lab["options"], lab["limit"])

        work = self.runner(directory, lab, config, chosen, budget, per_question, again)
        with self._lock:
            # Looked for again, as a run that was deleted while the checks above were made has no place to answer in
            self.lookup(run_id)
            try:
                return self.jobs.start(JOB_KIND, run_id, f"Answering {lab['title']}", work, exclusive=JOB_KIND)
            except JobConflictError as error:
                raise ApiError(
                    409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()
                ) from error

    def runner(
        self,
        directory: Path,
        lab: dict[str, Any],
        config: ChatConfig,
        chosen: Selection,
        max_cost: float | None,
        max_cost_per_question: float | None,
        retry_failed: bool,
    ) -> Callable[[Job], str | None]:
        """What a job does to answer a run: asks each question that has no result, reads and scores the answer, and
        says how it went."""

        def finished() -> int:
            return sum(
                1
                for question in chosen.asked
                if (directory / RESULTS_DIR / question.task / f"{question.id}.json").is_file()
            )

        def work(job: Job) -> str | None:
            if job.stop.is_set():
                raise StoppedError("Stopped before any question was asked.")
            job.update("Starting", questions=len(chosen.asked), finished=finished())

            def check_stop() -> None:
                if job.stop.is_set():
                    raise StopWork

            code = config.code
            options: dict[str, Any] = {"before_request": check_stop, "interrupt": check_stop}
            if code.where != "none":
                options.update(code_actions="tags", resources=code.resources)
            else:
                options["resources"] = "none"
            if lab["solver"] == "single":
                solver: Any = SingleAgent(config.lead_agent(), num_rounds=lab["rounds"], **options)
            else:
                solver = TeamMeeting(config.lead_agent(), config.team_agents(), num_rounds=lab["rounds"], **options)

            session = None
            if code.where != "none":
                (directory / SESSION_DIR).mkdir(parents=True, exist_ok=True)
                session = code.session(directory / SESSION_DIR)
            try:
                report = run_benchmark(
                    chosen.benchmark,
                    Watched(solver, job, finished),
                    directory,
                    extractor=config.model,
                    questions=chosen.asked,
                    session=session,
                    chat_models=self.chat_models,
                    client=self.client,
                    max_cost=max_cost,
                    max_cost_per_question=max_cost_per_question,
                    retry_failed=retry_failed,
                )
            except StopWork:
                self.settle(directory, chosen)
                raise StoppedError(
                    "Stopped. What was answered is kept, and starting again carries on from there."
                ) from None
            finally:
                if session is not None:
                    session.close()
            job.update(finished=finished())

            return describe_report(report)

        return work

    @staticmethod
    def settle(directory: Path, chosen: Selection) -> None:
        """Writes down how a run that was stopped stands, as the library does when it stops itself, so that a list of
        runs shows what was answered."""
        found, metrics = tally(directory, chosen)
        results = list(found.values())
        cost = total_cost(results)
        save_json(
            directory / SUMMARY_FILE,
            {
                "benchmark": chosen.benchmark.name,
                "metrics": metrics,
                "questions": len(chosen.asked),
                "finished": len(results),
                "failed": sum(result.failed for result in results),
                "cost": cost,
                "spent": cost,
                "stopped": "Stopped at the person's request",
            },
        )
