"""Tests of the background work the server does for a page."""

import threading
import time

import pytest

from virtual_lab.environment import StoppedError
from virtual_lab.server import jobs as jobs_module
from virtual_lab.server.jobs import Job, JobConflictError, Jobs

from setup_fakes import wait_for


@pytest.fixture
def jobs() -> Jobs:
    kept = Jobs()
    yield kept
    kept.close(timeout=5)


def finished(job: Job) -> bool:
    return not job.active


def hold(job: Job) -> str:
    """Work that goes on until it is asked to stop."""
    job.stop.wait(10)
    raise StoppedError("Held, then stopped")


class TestRunning:
    def test_work_is_done_in_a_thread_of_its_own_and_what_it_returns_is_said_of_it(self, jobs: Jobs) -> None:
        gate = threading.Event()
        threads: list[threading.Thread] = []

        def work(job: Job) -> str:
            threads.append(threading.current_thread())
            gate.wait(10)
            return "Did it"

        job = jobs.start("image", "base", "Building the base image", work)
        wait_for(lambda: threads)

        assert threads[0] is not threading.current_thread()
        assert job.snapshot()["state"] == "running"
        assert job.snapshot()["finished_at"] is None
        gate.set()
        wait_for(lambda: finished(job))
        body = job.snapshot()
        assert (body["state"], body["message"], body["error"]) == ("succeeded", "Did it", None)
        assert (body["kind"], body["subject"], body["title"]) == ("image", "base", "Building the base image")
        assert body["finished_at"] >= body["created_at"]
        assert len(body["id"]) == 12

    def test_each_job_has_an_id_of_its_own(self, jobs: Jobs) -> None:
        first = jobs.start("a", "x", "A", lambda job: None)
        second = jobs.start("b", "x", "B", lambda job: None)

        assert first.id != second.id
        assert jobs.get(first.id) is first

    def test_work_that_returns_nothing_leaves_what_it_said_as_the_message(self, jobs: Jobs) -> None:
        def work(job: Job) -> None:
            job.update("Almost there")

        job = jobs.start("a", "x", "A", work)
        wait_for(lambda: finished(job))

        assert job.snapshot()["message"] == "Almost there"
        assert job.snapshot()["state"] == "succeeded"

    def test_progress_and_the_message_are_shown_as_the_work_goes(self, jobs: Jobs) -> None:
        proceed, seen = threading.Event(), threading.Event()

        def work(job: Job) -> None:
            job.update("Fetching a file", done=1, total=5)
            seen.set()
            proceed.wait(10)
            job.update(done=2)

        job = jobs.start("a", "x", "A", work)
        seen.wait(10)
        assert job.snapshot()["message"] == "Fetching a file"
        assert job.snapshot()["progress"] == {"done": 1, "total": 5}
        proceed.set()
        wait_for(lambda: finished(job))

        assert job.snapshot()["progress"] == {"done": 2, "total": 5}
        assert job.snapshot()["message"] == "Fetching a file"

    def test_a_snapshot_is_a_copy_of_the_progress(self, jobs: Jobs) -> None:
        job = jobs.start("a", "x", "A", lambda job: None)
        wait_for(lambda: finished(job))
        job.update(done=1)

        body = job.snapshot()
        body["progress"]["done"] = 99

        assert job.snapshot()["progress"] == {"done": 1}

    def test_a_message_is_cut_to_a_line(self, jobs: Jobs) -> None:
        job = jobs.start("a", "x", "A", lambda job: job.update("m" * 1000))
        wait_for(lambda: finished(job))

        assert job.snapshot()["message"] == "m" * jobs_module.MAX_MESSAGE_CHARS

    def test_a_returned_message_is_cut_to_a_line_too(self, jobs: Jobs) -> None:
        job = jobs.start("a", "x", "A", lambda job: "r" * 1000)
        wait_for(lambda: finished(job))

        assert job.snapshot()["message"] == "r" * jobs_module.MAX_MESSAGE_CHARS


class TestEnding:
    def test_work_that_raises_is_a_failure_that_says_what_was_raised(self, jobs: Jobs) -> None:
        def work(job: Job) -> None:
            job.update("Working")
            raise RuntimeError("the disk is full")

        job = jobs.start("a", "x", "A", work)
        wait_for(lambda: finished(job))

        body = job.snapshot()
        assert (body["state"], body["error"]) == ("failed", "the disk is full")
        assert body["message"] == "Working"
        assert body["finished_at"] is not None

    def test_an_error_with_nothing_to_say_is_named(self, jobs: Jobs) -> None:
        def work(job: Job) -> None:
            raise KeyError

        job = jobs.start("a", "x", "A", work)
        wait_for(lambda: finished(job))

        assert job.snapshot()["error"] == "KeyError"

    def test_work_that_stops_is_stopped_and_not_a_failure(self, jobs: Jobs) -> None:
        def work(job: Job) -> None:
            raise StoppedError("Fetching the data lake was stopped")

        job = jobs.start("a", "x", "A", work)
        wait_for(lambda: finished(job))

        body = job.snapshot()
        assert (body["state"], body["message"], body["error"]) == (
            "stopped",
            "Fetching the data lake was stopped",
            None,
        )

    def test_a_failure_clears_nothing_it_was_told_before(self, jobs: Jobs) -> None:
        def work(job: Job) -> None:
            job.update(done=3)
            job.log("a line")
            raise RuntimeError("boom")

        job = jobs.start("a", "x", "A", work)
        wait_for(lambda: finished(job))

        assert job.snapshot(0)["progress"] == {"done": 3}
        assert job.snapshot(0)["log"]["lines"] == ["a line"]


class TestStopping:
    def test_a_job_asked_to_stop_is_stopping_until_it_has(self, jobs: Jobs) -> None:
        job = jobs.start("a", "x", "A", hold)

        stopped = jobs.stop(job.id)

        assert stopped is job
        assert job.stop.is_set()
        assert job.snapshot()["state"] in ("stopping", "stopped")
        wait_for(lambda: finished(job))
        assert job.snapshot()["state"] == "stopped"

    def test_the_state_is_stopping_while_the_work_has_not_yet_ended(self, jobs: Jobs) -> None:
        release = threading.Event()

        def work(job: Job) -> None:
            job.stop.wait(10)
            release.wait(10)
            raise StoppedError("done")

        job = jobs.start("a", "x", "A", work)
        jobs.stop(job.id)

        assert job.snapshot()["state"] == "stopping"
        assert job.active
        assert job.snapshot()["finished_at"] is None
        release.set()
        wait_for(lambda: finished(job))

    def test_asking_again_changes_nothing(self, jobs: Jobs) -> None:
        release = threading.Event()

        def work(job: Job) -> None:
            job.stop.wait(10)
            release.wait(10)
            raise StoppedError("done")

        job = jobs.start("a", "x", "A", work)
        jobs.stop(job.id)
        jobs.stop(job.id)

        assert job.snapshot()["state"] == "stopping"
        release.set()
        wait_for(lambda: finished(job))

    def test_a_job_that_has_ended_is_left_as_it_ended(self, jobs: Jobs) -> None:
        job = jobs.start("a", "x", "A", lambda job: "Done")
        wait_for(lambda: finished(job))

        jobs.stop(job.id)

        assert job.snapshot()["state"] == "succeeded"

    def test_a_job_that_finishes_though_asked_to_stop_is_a_success(self, jobs: Jobs) -> None:
        release = threading.Event()

        def work(job: Job) -> str:
            release.wait(10)
            return "Finished anyway"

        job = jobs.start("a", "x", "A", work)
        jobs.stop(job.id)
        release.set()
        wait_for(lambda: finished(job))

        assert job.snapshot()["state"] == "succeeded"

    def test_there_is_no_stopping_a_job_that_is_not_there(self, jobs: Jobs) -> None:
        with pytest.raises(KeyError):
            jobs.stop("nosuchjob")

        with pytest.raises(KeyError):
            jobs.get("nosuchjob")


class TestExclusion:
    def test_a_job_of_a_kind_already_running_is_refused_and_the_one_running_is_named(self, jobs: Jobs) -> None:
        first = jobs.start("image", "base", "Building base", hold)

        with pytest.raises(JobConflictError) as refused:
            jobs.start("image", "bio", "Building bio", hold)

        assert refused.value.job is first
        assert str(refused.value) == "Building base is already running"
        assert len(jobs.snapshots()) == 1

    def test_jobs_of_other_kinds_run_together(self, jobs: Jobs) -> None:
        jobs.start("image", "base", "Building", hold)

        other = jobs.start("data_lake", "data_lake", "Fetching", hold)

        assert other.active

    def test_jobs_that_share_what_is_exclusive_are_refused_though_their_kinds_differ(self, jobs: Jobs) -> None:
        jobs.start("a", "x", "A", hold, exclusive="disk")

        with pytest.raises(JobConflictError):
            jobs.start("b", "x", "B", hold, exclusive="disk")

    def test_once_it_has_ended_another_may_start(self, jobs: Jobs) -> None:
        first = jobs.start("image", "base", "Building", lambda job: None)
        wait_for(lambda: finished(first))

        second = jobs.start("image", "bio", "Building", lambda job: None)

        assert second is not first

    def test_a_job_that_is_stopping_still_excludes_another(self, jobs: Jobs) -> None:
        release = threading.Event()

        def work(job: Job) -> None:
            job.stop.wait(10)
            release.wait(10)

        first = jobs.start("image", "base", "Building", work)
        jobs.stop(first.id)

        with pytest.raises(JobConflictError):
            jobs.start("image", "base", "Building again", hold)
        release.set()


class TestListing:
    def test_the_latest_is_first_and_what_they_printed_is_left_out(self, jobs: Jobs) -> None:
        first = jobs.start("a", "x", "A", lambda job: job.log("x"))
        wait_for(lambda: finished(first))
        second = jobs.start("b", "x", "B", lambda job: None)
        wait_for(lambda: finished(second))

        listed = jobs.snapshots()

        assert [item["id"] for item in listed] == [second.id, first.id]
        assert all("log" not in item for item in listed)
        assert listed[1]["log_total"] == 1

    def test_the_active_are_those_running_of_the_kind_asked_for(self, jobs: Jobs) -> None:
        running = jobs.start("image", "base", "Building", hold)
        done = jobs.start("data_lake", "data_lake", "Fetching", lambda job: None)
        wait_for(lambda: finished(done))

        assert jobs.active() == [running]
        assert jobs.active("image") == [running]
        assert jobs.active("data_lake") == []

    def test_the_oldest_that_have_finished_are_forgotten_and_those_running_never_are(
        self, jobs: Jobs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jobs_module, "MAX_FINISHED_JOBS", 2)
        running = jobs.start("image", "x", "Held", hold)
        ended = []
        for number in range(4):
            job = jobs.start("kind", str(number), f"Quick {number}", lambda job: None)
            wait_for(lambda job=job: finished(job))
            ended.append(job)
        jobs.start("kind", "last", "Last", lambda job: None)

        kept = [item["id"] for item in jobs.snapshots()]

        assert running.id in kept
        assert ended[0].id not in kept
        assert ended[1].id not in kept
        assert ended[3].id in kept

    def test_the_thread_of_a_job_is_not_kept_once_it_has_ended(self, jobs: Jobs) -> None:
        for number in range(3):
            jobs.start("kind", str(number), f"Quick {number}", lambda job: None)

        wait_for(lambda: not jobs._threads)

        assert len(jobs.snapshots()) == 3


class TestLog:
    def make(self, jobs: Jobs, lines: int) -> Job:
        def work(job: Job) -> None:
            for number in range(lines):
                job.log(f"line {number}")

        job = jobs.start("a", "x", "A", work)
        wait_for(lambda: finished(job))

        return job

    def test_no_lines_are_given_unless_asked_for(self, jobs: Jobs) -> None:
        job = self.make(jobs, 3)

        assert "log" not in job.snapshot()
        assert job.snapshot()["log_total"] == 3

    def test_lines_are_given_from_the_one_asked_for(self, jobs: Jobs) -> None:
        job = self.make(jobs, 5)

        assert job.snapshot(0)["log"] == {"from": 0, "lines": ["line 0", "line 1", "line 2", "line 3", "line 4"]}
        assert job.snapshot(3)["log"] == {"from": 3, "lines": ["line 3", "line 4"]}
        assert job.snapshot(5)["log"] == {"from": 5, "lines": []}

    def test_asking_for_more_than_there_is_gives_none_from_the_end(self, jobs: Jobs) -> None:
        job = self.make(jobs, 2)

        assert job.snapshot(99)["log"] == {"from": 2, "lines": []}

    def test_the_oldest_lines_are_dropped_past_the_most_that_are_kept_and_the_count_goes_on(
        self, jobs: Jobs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jobs_module, "MAX_LOG_LINES", 3)
        job = self.make(jobs, 10)

        assert job.snapshot()["log_total"] == 10
        assert job.snapshot(0)["log"] == {"from": 7, "lines": ["line 7", "line 8", "line 9"]}
        assert job.snapshot(8)["log"] == {"from": 8, "lines": ["line 8", "line 9"]}
        assert job.snapshot(10)["log"] == {"from": 10, "lines": []}

    def test_a_long_line_is_cut(self, jobs: Jobs) -> None:
        job = jobs.start("a", "x", "A", lambda job: job.log("c" * 5000))
        wait_for(lambda: finished(job))

        assert job.snapshot(0)["log"]["lines"] == ["c" * jobs_module.MAX_LOG_LINE_CHARS]


class TestClosing:
    def test_every_job_running_is_stopped_and_waited_for(self) -> None:
        kept = Jobs()
        first = kept.start("image", "x", "A", hold)
        second = kept.start("data_lake", "x", "B", hold)

        kept.close(timeout=5)

        assert first.snapshot()["state"] == "stopped"
        assert second.snapshot()["state"] == "stopped"

    def test_a_job_that_will_not_stop_is_given_the_time_and_then_left(self) -> None:
        kept = Jobs()
        release = threading.Event()
        stuck = kept.start("image", "x", "A", lambda job: "Released" if release.wait(10) else None)

        started = time.monotonic()
        kept.close(timeout=0.2)

        assert time.monotonic() - started < 5
        assert stuck.stop.is_set()
        assert stuck.active
        release.set()
        wait_for(lambda: finished(stuck))
        assert stuck.snapshot()["message"] == "Released"

    def test_jobs_that_have_ended_are_left_as_they_ended(self) -> None:
        kept = Jobs()
        done = kept.start("image", "x", "A", lambda job: "Done")
        wait_for(lambda: finished(done))

        kept.close(timeout=5)

        assert done.snapshot()["state"] == "succeeded"
        assert not done.stop.is_set()
