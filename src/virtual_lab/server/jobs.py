"""Work the server does for a page in the background, which takes minutes or hours: building a sandbox
image, fetching the data lake.

A page starts a job and asks about it, as often as it likes while it runs, and can ask for it to stop. The
server keeps nothing of one beyond what it shows a page, since what a job makes, an image or a file, is what
is looked at to know whether it is there. A job that was running when the server stopped is stopped with it.
"""

import threading
from collections import deque
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from virtual_lab.environment import StoppedError
from virtual_lab.provenance import utc_timestamp

# The most lines of what a job printed that are kept, the oldest dropped first, and of each line
MAX_LOG_LINES = 2000
MAX_LOG_LINE_CHARS = 1000

# The most characters of the line saying what a job is doing
MAX_MESSAGE_CHARS = 300

# The most jobs that are kept once they have finished, the oldest dropped first
MAX_FINISHED_JOBS = 20

# Seconds the server gives jobs to stop when it stops itself
CLOSE_TIMEOUT = 20.0

ACTIVE_STATES = ("running", "stopping")


class JobConflictError(Exception):
    """Raised when a job cannot start because one that excludes it is running.

    :param job: The job that is running.
    """

    def __init__(self, job: "Job") -> None:
        super().__init__(f"{job.title} is already running")
        self.job = job


class Job:
    """One piece of background work, as a page is shown it.

    :param kind: What sort of work it is, such as "image" or "data_lake".
    :param subject: What it is for, such as the stage of the image.
    :param title: What it is, for a person to read.
    :param exclusive: Jobs that have this are never run together.
    """

    def __init__(self, kind: str, subject: str, title: str, exclusive: str) -> None:
        self.id = uuid4().hex[:12]
        self.kind = kind
        self.subject = subject
        self.title = title
        self.exclusive = exclusive
        self.state = "running"
        self.message = ""
        self.progress: dict[str, Any] = {}
        self.error: str | None = None
        self.created_at = utc_timestamp()
        self.finished_at: str | None = None
        self.stop = threading.Event()
        self._log: deque[str] = deque(maxlen=MAX_LOG_LINES)
        self._logged = 0
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        with self._lock:
            return self.state in ACTIVE_STATES

    def snapshot(self, log_from: int | None = None) -> dict[str, Any]:
        """How the job is, as a page is told.

        :param log_from: The number of the first line of its output to give, counting from 0 at the first it
            printed, or None to give none. A line that has been dropped is not given, so the lines may begin
            later, as "from" says.
        """
        with self._lock:
            body: dict[str, Any] = {
                "id": self.id,
                "kind": self.kind,
                "subject": self.subject,
                "title": self.title,
                "state": self.state,
                "message": self.message,
                "progress": dict(self.progress),
                "error": self.error,
                "created_at": self.created_at,
                "finished_at": self.finished_at,
                "log_total": self._logged,
            }
            if log_from is not None:
                dropped = self._logged - len(self._log)
                first = min(max(log_from, dropped), self._logged)
                body["log"] = {"from": first, "lines": list(self._log)[first - dropped :]}

            return body

    def log(self, line: str) -> None:
        with self._lock:
            self._log.append(line[:MAX_LOG_LINE_CHARS])
            self._logged += 1

    def update(self, message: str | None = None, **progress: Any) -> None:
        with self._lock:
            if message is not None:
                self.message = message[:MAX_MESSAGE_CHARS]
            self.progress.update(progress)

    def finish(self, state: str, message: str | None = None, error: str | None = None) -> None:
        with self._lock:
            self.state = state
            if message is not None:
                self.message = message[:MAX_MESSAGE_CHARS]
            self.error = error
            self.finished_at = utc_timestamp()

    def request_stop(self) -> None:
        with self._lock:
            if self.state == "running":
                self.state = "stopping"
        self.stop.set()


class Jobs:
    """The jobs the server is running and has run, which are started in a thread each."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def start(
        self, kind: str, subject: str, title: str, work: Callable[[Job], str | None], exclusive: str | None = None
    ) -> Job:
        """Starts work in a thread, unless a job that excludes it is running.

        :param work: What to do, given the job to report to and to watch for a request to stop. It returns what
            to say it did, or raises StoppedError once it has stopped. Whatever else it raises is the job's error.
        :param exclusive: What it may not be run with, which is its kind if not given.
        :raises JobConflictError: If a job with the same exclusive is running.
        """
        job = Job(kind, subject, title, exclusive or kind)
        with self._lock:
            for other in self._jobs.values():
                if other.exclusive == job.exclusive and other.active:
                    raise JobConflictError(other)
            self._jobs[job.id] = job
            thread = threading.Thread(target=self._run, args=(job, work), name=f"virtual-lab-job-{job.id}", daemon=True)
            self._threads[job.id] = thread
            self._forget_old()
        thread.start()

        return job

    def get(self, job_id: str) -> Job:
        """The job with this id.

        :raises KeyError: If there is none.
        """
        with self._lock:
            return self._jobs[job_id]

    def snapshots(self) -> list[dict[str, Any]]:
        """Every job, the latest first, without what they printed."""
        with self._lock:
            jobs = list(self._jobs.values())

        return [job.snapshot() for job in reversed(jobs)]

    def active(self, kind: str | None = None) -> list[Job]:
        """The jobs that are running, of this kind if one is given."""
        with self._lock:
            jobs = list(self._jobs.values())

        return [job for job in jobs if job.active and (kind is None or job.kind == kind)]

    def stop(self, job_id: str) -> Job:
        """Asks a job to stop, if it is running. It goes on until it has, which may take a moment.

        :raises KeyError: If there is no job with this id.
        """
        job = self.get(job_id)
        job.request_stop()

        return job

    def close(self, timeout: float = CLOSE_TIMEOUT) -> None:
        """Stops every job that is running, and waits for them, for the server to stop."""
        with self._lock:
            jobs = list(self._jobs.values())
            threads = list(self._threads.values())
        for job in jobs:
            if job.active:
                job.request_stop()
        for thread in threads:
            thread.join(timeout)

    def _run(self, job: Job, work: Callable[[Job], str | None]) -> None:
        try:
            message = work(job)
        except StoppedError as error:
            job.finish("stopped", str(error))
        except Exception as error:
            job.finish("failed", error=str(error) or type(error).__name__)
        else:
            job.finish("succeeded", message)
        finally:
            with self._lock:
                self._threads.pop(job.id, None)

    def _forget_old(self) -> None:
        """Drops the oldest jobs that have finished, past the most that are kept. Called with the lock held."""
        finished = [job for job in self._jobs.values() if not job.active]
        for job in finished[: max(len(finished) - MAX_FINISHED_JOBS, 0)]:
            del self._jobs[job.id]
