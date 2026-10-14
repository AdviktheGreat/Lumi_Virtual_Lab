"""Tests of what code needs to run in Biomni's environment, and of getting it, against a program that answers as
Docker does and a server that answers as Biomni's release bucket does."""

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import virtual_lab.environment as environment
from virtual_lab.constants import SANDBOX_PLATFORM
from virtual_lab.environment import DATA_LAKE, SANDBOX_TARGETS, sandbox_image
from virtual_lab.resources import commercial_data_lake
from virtual_lab.server import setup as server_setup
from virtual_lab.server.config import resolve_config
from virtual_lab.server.errors import ApiError
from virtual_lab.server.jobs import Job
from virtual_lab.server.setup import STAGES, Setup, checklist, file_size, free_space
from virtual_lab.server.workspace import Settings, Workspace

from conftest import TEST_MODEL
from setup_fakes import Bucket, FakeDocker, wait_for

NAMES = list(DATA_LAKE)[:3]


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "workspace")


@pytest.fixture
def docker(tmp_path: Path) -> FakeDocker:
    return FakeDocker(tmp_path / "docker")


@pytest.fixture
def bucket() -> Iterator[Bucket]:
    served = Bucket()
    yield served
    served.close()


@pytest.fixture
def machine(workspace: Workspace, docker: FakeDocker, bucket: Bucket) -> Iterator[Setup]:
    kept = Setup(workspace, docker.command, bucket.url)
    yield kept
    kept.close()


def settings(**changes: Any) -> Settings:
    return Settings(**{"model": TEST_MODEL, **changes})


def done(job: Job) -> bool:
    return not job.active


class TestDocker:
    def test_a_running_docker_says_which_version(self, machine: Setup) -> None:
        assert machine.docker() == {"installed": True, "running": True, "version": "27.3.1", "message": None}

    def test_a_version_it_does_not_give_is_none(self, machine: Setup, docker: FakeDocker) -> None:
        docker.configure(version="")

        assert machine.docker()["version"] is None
        assert machine.docker()["running"] is True

    def test_docker_that_is_not_installed_is_said_to_be_missing(self, workspace: Workspace) -> None:
        found = Setup(workspace, ("no-such-docker-program",)).docker()

        assert found["installed"] is False
        assert found["running"] is False
        assert found["version"] is None
        assert found["message"] == 'Docker was not found: "no-such-docker-program" is not installed or not on the path'

    def test_a_daemon_that_is_down_says_why_in_the_first_line_it_gave(self, machine: Setup, docker: FakeDocker) -> None:
        docker.configure(daemon="down")

        found = machine.docker()

        assert found["installed"] is True
        assert found["running"] is False
        assert found["message"] == (
            "Docker is installed but is not running. It said: Cannot connect to the Docker daemon at "
            "unix:///var/run/docker.sock."
        )

    def test_a_daemon_that_is_down_and_says_nothing_is_still_down(self, machine: Setup, docker: FakeDocker) -> None:
        docker.configure(daemon="silent")

        found = machine.docker()

        assert found["running"] is False
        assert found["message"] == "Docker is installed but is not running"

    def test_a_daemon_that_does_not_answer_is_given_a_time_and_then_not_running(
        self, machine: Setup, docker: FakeDocker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(server_setup, "DOCKER_TIMEOUT", 0.3)
        docker.configure(daemon="hang")

        found = machine.docker()

        assert found["installed"] is True
        assert found["running"] is False
        assert found["message"].startswith("Docker did not answer: ")

    def test_a_docker_that_cannot_be_run_is_not_running(self, workspace: Workspace, tmp_path: Path) -> None:
        program = tmp_path / "not-executable"
        program.write_bytes(b"\x7fELF-but-not-really")
        program.chmod(0o755)

        found = Setup(workspace, (str(program),)).docker()

        assert found["running"] is False
        assert found["message"].startswith("Docker did not answer: ")


class TestImages:
    def test_every_stage_is_shown_with_what_it_adds_and_whether_it_is_built(
        self, machine: Setup, docker: FakeDocker
    ) -> None:
        docker.configure(images=[sandbox_image("bio")])

        shown = machine.images(machine.docker())

        assert shown["platform"] == SANDBOX_PLATFORM
        assert [stage["target"] for stage in shown["stages"]] == list(SANDBOX_TARGETS)
        assert [stage["built"] for stage in shown["stages"]] == [False, True, False]
        assert [stage["tag"] for stage in shown["stages"]] == [sandbox_image(target) for target in SANDBOX_TARGETS]
        assert all(stage["building"] is False for stage in shown["stages"])
        base = shown["stages"][0]
        assert (base["summary"], base["estimate"]) == STAGES["base"]

    def test_the_stages_described_are_the_stages_that_can_be_built(self) -> None:
        assert tuple(STAGES) == SANDBOX_TARGETS

    def test_nothing_is_said_of_whether_an_image_is_built_while_docker_is_not_running(
        self, machine: Setup, docker: FakeDocker
    ) -> None:
        docker.configure(daemon="down", images=[sandbox_image("base")])

        shown = machine.images(machine.docker())

        assert [stage["built"] for stage in shown["stages"]] == [None, None, None]

    @pytest.mark.parametrize(
        ("architecture", "emulated"),
        [("x86_64", False), ("AMD64", False), ("amd64", False), ("arm64", True), ("aarch64", True)],
    )
    def test_an_image_is_emulated_on_a_machine_that_is_not_x86_64(
        self, machine: Setup, monkeypatch: pytest.MonkeyPatch, architecture: str, emulated: bool
    ) -> None:
        monkeypatch.setattr(server_setup.platform, "machine", lambda: architecture)

        assert machine.images(machine.docker())["emulated"] is emulated

    def test_the_stage_being_built_is_said_to_be(self, machine: Setup, docker: FakeDocker) -> None:
        docker.build(wait=True)
        job = machine.build_image("bio")
        wait_for(lambda: docker.started)

        stages = {stage["target"]: stage for stage in machine.images(machine.docker())["stages"]}

        assert [stages[target]["building"] for target in SANDBOX_TARGETS] == [False, True, False]
        docker.release()
        wait_for(lambda: done(job))
        assert machine.images(machine.docker())["stages"][1]["building"] is False


class TestDataLake:
    def test_none_of_it_is_there_at_first(self, machine: Setup, workspace: Workspace) -> None:
        shown = machine.data_lake(settings())

        assert shown["directory"] == str(workspace.root / "data_lake")
        assert shown["custom"] is False
        assert (shown["files"], shown["present"], shown["bytes"]) == (len(DATA_LAKE), 0, 0)
        assert shown["complete"] is False
        assert isinstance(shown["free_bytes"], int) and shown["free_bytes"] > 0

    def test_the_files_that_are_there_are_counted_and_measured(self, machine: Setup, workspace: Workspace) -> None:
        lake = workspace.data_lake_dir
        lake.mkdir()
        (lake / NAMES[0]).write_bytes(b"12345")
        (lake / NAMES[1]).write_bytes(b"123")
        (lake / "something-else.csv").write_bytes(b"not in the data lake")
        (lake / f".{NAMES[2]}.part").write_bytes(b"not finished")

        shown = machine.data_lake(settings())

        assert (shown["present"], shown["bytes"], shown["complete"]) == (2, 8, False)

    def test_a_directory_with_a_files_name_is_not_the_file(self, machine: Setup, workspace: Workspace) -> None:
        (workspace.data_lake_dir / NAMES[0]).mkdir(parents=True)

        assert machine.data_lake(settings())["present"] == 0

    def test_it_is_complete_when_every_file_is_there(self, machine: Setup, workspace: Workspace) -> None:
        workspace.data_lake_dir.mkdir()
        for name in DATA_LAKE:
            (workspace.data_lake_dir / name).write_bytes(b"x")

        shown = machine.data_lake(settings())

        assert (shown["present"], shown["bytes"], shown["complete"]) == (len(DATA_LAKE), len(DATA_LAKE), True)

    def test_a_directory_the_settings_name_is_the_one_looked_in(self, machine: Setup, tmp_path: Path) -> None:
        elsewhere = tmp_path / "biomni-data" / "data_lake"
        elsewhere.mkdir(parents=True)
        (elsewhere / NAMES[0]).write_bytes(b"abc")

        shown = machine.data_lake(settings(data_lake=str(elsewhere)))

        assert (shown["directory"], shown["custom"], shown["present"]) == (str(elsewhere), True, 1)

    def test_every_file_is_listed_with_what_it_is_and_whether_it_is_there(
        self, machine: Setup, workspace: Workspace
    ) -> None:
        workspace.data_lake_dir.mkdir()
        (workspace.data_lake_dir / NAMES[1]).write_bytes(b"abcd")

        files = machine.data_lake_files(settings())

        assert [item["name"] for item in files] == list(DATA_LAKE)
        assert files[1] == {
            "name": NAMES[1],
            "description": DATA_LAKE[NAMES[1]],
            "present": True,
            "bytes": 4,
            "commercial": NAMES[1] in commercial_data_lake(),
        }
        assert (files[0]["present"], files[0]["bytes"]) == (False, None)
        assert {item["name"] for item in files if item["commercial"]} == set(commercial_data_lake())
        assert any(not item["commercial"] for item in files)

    def test_the_space_left_is_that_of_the_nearest_directory_there_is(self, tmp_path: Path) -> None:
        assert free_space(tmp_path / "not" / "yet" / "made") == shutil.disk_usage(tmp_path).free

    def test_no_space_is_given_where_it_cannot_be_told(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def refuse(path: Path) -> None:
            raise OSError("no")

        monkeypatch.setattr(server_setup.shutil, "disk_usage", refuse)

        assert free_space(tmp_path) is None

    def test_a_size_is_given_for_a_file_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "a").write_bytes(b"abc")
        (tmp_path / "directory").mkdir()

        assert file_size(tmp_path / "a") == 3
        assert file_size(tmp_path / "directory") is None
        assert file_size(tmp_path / "missing") is None

        def vanished(self: Path, **kwargs: Any) -> None:
            raise FileNotFoundError

        monkeypatch.setattr(Path, "stat", vanished)
        assert file_size(tmp_path / "a") is None


class TestBuildingAnImage:
    def test_a_build_goes_on_in_the_background_and_what_it_prints_is_kept(
        self, machine: Setup, docker: FakeDocker
    ) -> None:
        docker.build(lines=["#1 first", "#2 second", "#3 third"], wait=True)

        job = machine.build_image("bio")
        wait_for(lambda: docker.started)
        wait_for(lambda: job.snapshot()["log_total"] == 3)

        body = job.snapshot(0)
        assert (body["kind"], body["subject"], body["state"]) == ("image", "bio", "running")
        assert body["title"] == "Building Biomni's bio environment"
        assert body["log"] == {"from": 0, "lines": ["#1 first", "#2 second", "#3 third"]}
        assert body["message"] == "#3 third"
        docker.release()
        wait_for(lambda: done(job))
        assert job.snapshot()["state"] == "succeeded"
        assert job.snapshot()["message"] == "Built Biomni's bio environment"
        assert docker.images == [sandbox_image("bio")]
        assert docker.builds[0][docker.builds[0].index("--target") + 1] == "bio"

    def test_blank_lines_are_kept_but_do_not_replace_what_is_said_of_it(
        self, machine: Setup, docker: FakeDocker
    ) -> None:
        docker.build(lines=["#1 step", "   "], wait=True)

        job = machine.build_image("base")
        wait_for(lambda: job.snapshot()["log_total"] == 2)

        assert job.snapshot(0)["log"]["lines"] == ["#1 step", "   "]
        assert job.snapshot()["message"] == "#1 step"
        docker.release()
        wait_for(lambda: done(job))
        assert job.snapshot()["message"] == "Built Biomni's base environment"

    def test_an_image_that_is_built_is_then_shown_as_built(self, machine: Setup) -> None:
        job = machine.build_image("base")
        wait_for(lambda: done(job))

        assert machine.images(machine.docker())["stages"][0]["built"] is True

    def test_a_build_that_fails_is_a_failure_that_says_how_and_keeps_what_it_printed(
        self, machine: Setup, docker: FakeDocker
    ) -> None:
        docker.build(lines=["#1 step", "ERROR: no space left on device"], exit=1)

        job = machine.build_image("base")
        wait_for(lambda: done(job))

        body = job.snapshot(0)
        assert body["state"] == "failed"
        assert "exit code 1" in body["error"]
        assert body["log"]["lines"] == ["#1 step", "ERROR: no space left on device"]
        assert docker.images == []

    def test_a_build_asked_to_stop_is_stopped_and_another_can_then_be_started(
        self, machine: Setup, docker: FakeDocker
    ) -> None:
        docker.build(wait=True)
        job = machine.build_image("base")
        wait_for(lambda: docker.started)

        machine.jobs.stop(job.id)
        wait_for(lambda: done(job))

        assert job.snapshot()["state"] == "stopped"
        assert docker.images == []
        docker.build(wait=False)
        again = machine.build_image("base")
        wait_for(lambda: done(again))
        assert again.snapshot()["state"] == "succeeded"

    def test_a_second_build_while_one_runs_is_refused_and_the_one_running_is_named(
        self, machine: Setup, docker: FakeDocker
    ) -> None:
        docker.build(wait=True)
        job = machine.build_image("base")
        wait_for(lambda: docker.started)

        with pytest.raises(ApiError) as refused:
            machine.build_image("bio")

        assert (refused.value.status, refused.value.code) == (409, "busy")
        assert refused.value.message == "Building Biomni's base environment is already running"
        assert refused.value.details["job"]["id"] == job.id
        assert len(docker.builds) == 1
        docker.release()
        wait_for(lambda: done(job))

    def test_no_build_is_started_while_docker_is_not_running(self, machine: Setup, docker: FakeDocker) -> None:
        docker.configure(daemon="down")

        with pytest.raises(ApiError) as refused:
            machine.build_image("base")

        assert (refused.value.status, refused.value.code) == (409, "docker_unavailable")
        assert refused.value.message.startswith("Docker is installed but is not running")
        assert machine.jobs.snapshots() == []

    def test_an_image_already_built_is_not_built_again(self, machine: Setup, docker: FakeDocker) -> None:
        docker.configure(images=[sandbox_image("base")])

        with pytest.raises(ApiError) as refused:
            machine.build_image("base")

        assert (refused.value.status, refused.value.code) == (409, "already_built")
        assert refused.value.message == "Biomni's base environment is already built"
        assert machine.jobs.snapshots() == []

    @pytest.mark.parametrize("target", ["python", "huge", "", "BASE"])
    def test_a_stage_that_is_not_one_is_refused(self, machine: Setup, target: str) -> None:
        with pytest.raises(ApiError) as refused:
            machine.build_image(target)

        assert (refused.value.status, refused.value.code) == (422, "invalid")
        assert refused.value.message == "A stage of the image is one of base, bio, full"

    def test_a_build_does_not_keep_the_data_lake_from_being_fetched(
        self, machine: Setup, docker: FakeDocker, bucket: Bucket
    ) -> None:
        docker.build(wait=True)
        bucket.files = {NAMES[0]: b"abc"}
        build = machine.build_image("base")
        wait_for(lambda: docker.started)

        fetch = machine.download_data_lake(settings(), [NAMES[0]])
        wait_for(lambda: done(fetch))

        assert fetch.snapshot()["state"] == "succeeded"
        assert build.active
        docker.release()
        wait_for(lambda: done(build))


class TestFetchingTheDataLake:
    @pytest.fixture(autouse=True)
    def small_parts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "DATA_LAKE_CHUNK_BYTES", 256)

    def test_the_files_asked_for_are_fetched_into_the_data_lake(
        self, machine: Setup, workspace: Workspace, bucket: Bucket
    ) -> None:
        bucket.files = {name: f"contents of {name}".encode() for name in NAMES}

        job = machine.download_data_lake(settings(), NAMES)
        wait_for(lambda: done(job))

        body = job.snapshot(0)
        assert (body["state"], body["error"]) == ("succeeded", None)
        assert body["kind"] == "data_lake"
        assert body["title"] == "Fetching Biomni's data lake"
        assert body["message"] == "Fetched 3 files, and 0 were there already"
        for name in NAMES:
            assert (workspace.data_lake_dir / name).read_bytes() == f"contents of {name}".encode()
        assert body["log"]["lines"] == [f"Fetched {name}, {len(f'contents of {name}'):,} bytes" for name in NAMES]
        assert (body["progress"]["done"], body["progress"]["total"]) == (3, 3)
        assert body["progress"]["current"] is None
        assert body["progress"]["fetched"] == sum(len(f"contents of {name}") for name in NAMES)
        assert bucket.requests == NAMES

    def test_all_of_it_is_fetched_when_no_files_are_named(self, machine: Setup, bucket: Bucket) -> None:
        bucket.files = {name: b"x" for name in DATA_LAKE}

        job = machine.download_data_lake(settings())
        wait_for(lambda: done(job))

        assert job.snapshot()["state"] == "succeeded"
        assert job.snapshot()["progress"]["total"] == len(DATA_LAKE)
        assert machine.data_lake(settings())["complete"] is True

    def test_what_is_fetched_so_far_is_shown_as_each_file_comes(
        self, machine: Setup, bucket: Bucket, workspace: Workspace
    ) -> None:
        bucket.files = {NAMES[0]: b"a" * 100, NAMES[1]: b"b" * 2000}
        gate = bucket.gate(NAMES[1])

        job = machine.download_data_lake(settings(), NAMES[:2])
        wait_for(
            lambda: job.snapshot()["progress"].get("current") == NAMES[1] and job.snapshot()["progress"]["bytes"] > 0
        )

        progress = job.snapshot()["progress"]
        assert progress["done"] == 1
        assert progress["total"] == 2
        assert progress["bytes_total"] == 2000
        assert 0 < progress["bytes"] < 2000
        assert progress["fetched"] == 100 + progress["bytes"]
        assert job.snapshot()["message"] == f"Fetching {NAMES[1]}"
        assert job.snapshot()["log_total"] == 1
        gate.set()
        wait_for(lambda: done(job))
        assert job.snapshot()["state"] == "succeeded"

    def test_files_already_there_are_left_alone_and_counted_as_done(
        self, machine: Setup, bucket: Bucket, workspace: Workspace
    ) -> None:
        workspace.data_lake_dir.mkdir()
        (workspace.data_lake_dir / NAMES[0]).write_bytes(b"mine")
        bucket.files = {name: b"theirs" for name in NAMES}
        gate = bucket.gate(NAMES[1])

        job = machine.download_data_lake(settings(), NAMES)
        wait_for(lambda: job.snapshot()["progress"].get("current") == NAMES[1])

        assert job.snapshot()["progress"]["done"] == 1
        gate.set()
        wait_for(lambda: done(job))
        assert job.snapshot()["message"] == "Fetched 2 files, and 1 were there already"
        assert (workspace.data_lake_dir / NAMES[0]).read_bytes() == b"mine"
        assert bucket.requests == NAMES[1:]

    def test_a_file_that_cannot_be_fetched_fails_the_job_after_the_rest_are_fetched(
        self, machine: Setup, bucket: Bucket, workspace: Workspace
    ) -> None:
        bucket.files = {NAMES[0]: b"abc", NAMES[2]: b"ghi"}

        job = machine.download_data_lake(settings(), NAMES)
        wait_for(lambda: done(job))

        body = job.snapshot(0)
        assert body["state"] == "failed"
        assert body["error"].startswith(f"1 of 3 files could not be fetched. {NAMES[1]}: 404")
        assert sorted(path.name for path in workspace.data_lake_dir.iterdir()) == sorted([NAMES[0], NAMES[2]])
        assert body["log"]["lines"][-1].startswith(f"Could not fetch {NAMES[1]}: 404")
        assert body["progress"]["done"] == 3

    def test_a_download_asked_to_stop_is_stopped_with_no_partial_file_left(
        self, machine: Setup, bucket: Bucket, workspace: Workspace
    ) -> None:
        bucket.files = {NAMES[0]: b"a" * 50, NAMES[1]: b"b" * 4000, NAMES[2]: b"c"}
        gate = bucket.gate(NAMES[1])

        job = machine.download_data_lake(settings(), NAMES)
        wait_for(
            lambda: job.snapshot()["progress"].get("current") == NAMES[1] and job.snapshot()["progress"]["bytes"] > 0
        )
        machine.jobs.stop(job.id)
        gate.set()
        wait_for(lambda: done(job))

        assert job.snapshot()["state"] == "stopped"
        assert job.snapshot()["error"] is None
        assert sorted(path.name for path in workspace.data_lake_dir.iterdir()) == [NAMES[0]]
        assert NAMES[2] not in bucket.requests

    def test_a_second_fetch_while_one_runs_is_refused(self, machine: Setup, bucket: Bucket) -> None:
        bucket.files = {NAMES[0]: b"a" * 1000}
        gate = bucket.gate(NAMES[0])
        job = machine.download_data_lake(settings(), NAMES[:1])
        wait_for(lambda: job.snapshot()["progress"].get("bytes", 0) > 0)

        with pytest.raises(ApiError) as refused:
            machine.download_data_lake(settings(), NAMES[1:2])

        assert (refused.value.status, refused.value.code) == (409, "busy")
        assert refused.value.message == "Fetching Biomni's data lake is already running"
        gate.set()
        wait_for(lambda: done(job))

    def test_files_that_are_not_in_the_data_lake_are_refused_and_none_is_fetched(
        self, machine: Setup, bucket: Bucket
    ) -> None:
        with pytest.raises(ApiError) as refused:
            machine.download_data_lake(settings(), [NAMES[0], "../escape.csv", "nothing.csv"])

        assert (refused.value.status, refused.value.code) == (422, "invalid")
        assert refused.value.message == "The data lake has no file ../escape.csv, nothing.csv"
        assert machine.jobs.snapshots() == []
        assert bucket.requests == []

    def test_no_files_at_all_is_refused(self, machine: Setup) -> None:
        with pytest.raises(ApiError) as refused:
            machine.download_data_lake(settings(), [])

        assert (refused.value.status, refused.value.code) == (422, "invalid")
        assert refused.value.message == "Choose at least one file of the data lake to fetch"

    def test_a_file_named_twice_is_fetched_once(self, machine: Setup, bucket: Bucket) -> None:
        bucket.files = {NAMES[0]: b"abc"}

        job = machine.download_data_lake(settings(), [NAMES[0], NAMES[0]])
        wait_for(lambda: done(job))

        assert job.snapshot()["progress"]["total"] == 1
        assert bucket.requests == [NAMES[0]]

    def test_the_directory_the_settings_name_is_where_it_is_fetched_to(
        self, machine: Setup, bucket: Bucket, tmp_path: Path, workspace: Workspace
    ) -> None:
        bucket.files = {NAMES[0]: b"abc"}
        elsewhere = tmp_path / "elsewhere" / "data_lake"

        job = machine.download_data_lake(settings(data_lake=str(elsewhere)), NAMES[:1])
        wait_for(lambda: done(job))

        assert (elsewhere / NAMES[0]).read_bytes() == b"abc"
        assert not workspace.data_lake_dir.exists() or list(workspace.data_lake_dir.iterdir()) == []

    def test_a_directory_that_cannot_be_made_fails_the_job(
        self, machine: Setup, bucket: Bucket, tmp_path: Path
    ) -> None:
        blocker = tmp_path / "a-file"
        blocker.write_text("")

        job = machine.download_data_lake(settings(data_lake=str(blocker / "inside")), NAMES[:1])
        wait_for(lambda: done(job))

        assert job.snapshot()["state"] == "failed"
        assert job.snapshot()["error"]

    def test_the_server_stopping_stops_a_fetch_that_is_running(self, workspace: Workspace, bucket: Bucket) -> None:
        kept = Setup(workspace, ("docker",), bucket.url)
        bucket.files = {NAMES[0]: b"a" * 4000}
        gate = bucket.gate(NAMES[0])
        job = kept.download_data_lake(settings(), NAMES[:1])
        wait_for(lambda: job.snapshot()["progress"].get("bytes", 0) > 0)

        gate.set()
        kept.close()

        assert job.snapshot()["state"] in ("stopped", "succeeded")
        assert not job.active


class TestWhatCodeCannotRunWithout:
    def config(self, workspace: Workspace, **code: Any) -> Any:
        return resolve_config({"code": code}, settings(), workspace)

    @pytest.mark.parametrize("where", ["none", "local"])
    def test_code_that_is_not_in_docker_needs_nothing_and_docker_is_not_asked(
        self, machine: Setup, docker: FakeDocker, workspace: Workspace, where: str
    ) -> None:
        docker.configure(daemon="down")

        assert machine.missing(self.config(workspace, where=where, sandbox="full")) == []

    def test_docker_that_is_not_running_is_what_is_missing(
        self, machine: Setup, docker: FakeDocker, workspace: Workspace
    ) -> None:
        docker.configure(daemon="down")

        missing = machine.missing(self.config(workspace, where="docker", sandbox="bio"))

        assert [item["id"] for item in missing] == ["docker"]
        assert missing[0]["message"].startswith("Docker is installed but is not running")

    def test_an_image_that_is_not_built_is_what_is_missing_and_how_long_it_takes_is_said(
        self, machine: Setup, workspace: Workspace
    ) -> None:
        missing = machine.missing(self.config(workspace, where="docker", sandbox="bio"))

        assert missing == [
            {
                "id": "image",
                "message": (
                    "Biomni's bio environment is not built. Build it in the setup, which takes about half an hour"
                ),
            }
        ]

    def test_nothing_is_missing_once_the_image_is_built(
        self, machine: Setup, docker: FakeDocker, workspace: Workspace
    ) -> None:
        docker.configure(images=[sandbox_image("bio")])

        assert machine.missing(self.config(workspace, where="docker", sandbox="bio")) == []

    def test_only_the_stage_asked_for_has_to_be_built(
        self, machine: Setup, docker: FakeDocker, workspace: Workspace
    ) -> None:
        docker.configure(images=[sandbox_image("base")])

        assert machine.missing(self.config(workspace, where="docker", sandbox="base")) == []
        assert [item["id"] for item in machine.missing(self.config(workspace, where="docker", sandbox="full"))] == [
            "image"
        ]

    def test_the_plain_python_image_needs_none_built(self, machine: Setup, workspace: Workspace) -> None:
        assert machine.missing(self.config(workspace, where="docker", sandbox="python")) == []


def images_of(*built: bool | None) -> dict[str, Any]:
    return {
        "platform": SANDBOX_PLATFORM,
        "emulated": False,
        "stages": [
            {"target": target, "tag": sandbox_image(target), "summary": "s", "estimate": "an hour", "built": state}
            for target, state in zip(SANDBOX_TARGETS, built, strict=True)
        ],
    }


def lake(present: int = 0) -> dict[str, Any]:
    return {"files": 76, "present": present, "complete": present == 76}


DOCKER_UP = {"installed": True, "running": True, "version": "27.3.1", "message": None}
DOCKER_DOWN = {
    "installed": True,
    "running": False,
    "version": None,
    "message": "Docker is installed but is not running",
}


def job_of(kind: str, subject: str, state: str = "running") -> dict[str, Any]:
    return {"kind": kind, "subject": subject, "state": state}


def by_id(steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {step["id"]: step for step in steps}


class TestChecklist:
    def test_everything_still_to_do_for_code_in_biomni_s_environment(self) -> None:
        steps = checklist(
            settings(code="docker", sandbox="bio"),
            DOCKER_DOWN,
            images_of(None, None, None),
            lake(),
            [],
            ["OPENAI_API_KEY"],
        )

        assert steps == [
            {
                "id": "docker",
                "title": "Docker",
                "state": "todo",
                "detail": "Docker is installed but is not running",
                "required": True,
            },
            {
                "id": "image",
                "title": "Biomni's bio environment",
                "state": "blocked",
                "detail": "Needs Docker",
                "required": True,
            },
            {
                "id": "data_lake",
                "title": "Biomni's data lake",
                "state": "todo",
                "detail": "0 of 76 files",
                "required": False,
            },
            {
                "id": "model_key",
                "title": "Model key",
                "state": "todo",
                "detail": "OPENAI_API_KEY is not set",
                "required": True,
            },
        ]

    def test_everything_done(self) -> None:
        steps = checklist(
            settings(code="docker", sandbox="base"), DOCKER_UP, images_of(True, False, False), lake(76), [], []
        )

        assert [(step["id"], step["state"]) for step in steps] == [
            ("docker", "done"),
            ("image", "done"),
            ("data_lake", "done"),
            ("model_key", "done"),
        ]
        found = by_id(steps)
        assert found["docker"]["detail"] == "Docker 27.3.1 is running"
        assert found["image"]["detail"] == "Built"
        assert found["data_lake"]["detail"] == "76 of 76 files"
        assert found["model_key"]["detail"] == f"The key {TEST_MODEL} needs is set"

    def test_docker_without_a_version_is_still_running(self) -> None:
        steps = checklist(
            settings(code="docker", sandbox="base"),
            {**DOCKER_UP, "version": None},
            images_of(False, False, False),
            lake(),
            [],
            [],
        )

        assert by_id(steps)["docker"]["detail"] == "Docker is running"

    def test_an_image_not_built_while_docker_runs_says_how_long_it_takes(self) -> None:
        steps = checklist(
            settings(code="docker", sandbox="full"), DOCKER_UP, images_of(True, True, False), lake(), [], []
        )

        assert by_id(steps)["image"] == {
            "id": "image",
            "title": "Biomni's full environment",
            "state": "todo",
            "detail": "Takes an hour to build",
            "required": True,
        }

    def test_it_is_the_chosen_stage_that_counts(self) -> None:
        steps = checklist(
            settings(code="docker", sandbox="bio"), DOCKER_UP, images_of(True, False, True), lake(), [], []
        )

        assert by_id(steps)["image"]["state"] == "todo"

    def test_an_image_being_built_is_running_and_one_being_built_for_another_stage_is_not(self) -> None:
        mine = checklist(
            settings(code="docker", sandbox="bio"),
            DOCKER_UP,
            images_of(False, False, False),
            lake(),
            [job_of("image", "bio")],
            [],
        )
        other = checklist(
            settings(code="docker", sandbox="bio"),
            DOCKER_UP,
            images_of(False, False, False),
            lake(),
            [job_of("image", "full")],
            [],
        )

        assert (by_id(mine)["image"]["state"], by_id(mine)["image"]["detail"]) == ("running", "Being built")
        assert by_id(other)["image"]["state"] == "todo"

    def test_a_job_that_has_ended_is_not_running_and_one_stopping_still_is(self) -> None:
        ended = checklist(
            settings(code="docker", sandbox="bio"),
            DOCKER_UP,
            images_of(False, False, False),
            lake(),
            [job_of("image", "bio", "failed"), job_of("data_lake", "data_lake", "succeeded")],
            [],
        )
        stopping = checklist(
            settings(code="docker", sandbox="bio"),
            DOCKER_UP,
            images_of(False, False, False),
            lake(),
            [job_of("image", "bio", "stopping"), job_of("data_lake", "data_lake", "stopping")],
            [],
        )

        assert (by_id(ended)["image"]["state"], by_id(ended)["data_lake"]["state"]) == ("todo", "todo")
        assert (by_id(stopping)["image"]["state"], by_id(stopping)["data_lake"]["state"]) == ("running", "running")

    def test_a_built_image_is_done_though_a_build_is_somehow_running(self) -> None:
        steps = checklist(
            settings(code="docker", sandbox="bio"),
            DOCKER_UP,
            images_of(False, True, False),
            lake(),
            [job_of("image", "bio")],
            [],
        )

        assert by_id(steps)["image"]["state"] == "done"

    def test_the_plain_python_image_has_no_step_for_an_image(self) -> None:
        steps = checklist(
            settings(code="docker", sandbox="python"), DOCKER_UP, images_of(False, False, False), lake(), [], []
        )

        assert [step["id"] for step in steps] == ["docker", "data_lake", "model_key"]

    def test_the_data_lake_being_fetched_is_running_and_is_never_required(self) -> None:
        steps = checklist(
            settings(code="docker", sandbox="bio"),
            DOCKER_UP,
            images_of(True, True, True),
            lake(10),
            [job_of("data_lake", "data_lake")],
            [],
        )

        assert by_id(steps)["data_lake"] == {
            "id": "data_lake",
            "title": "Biomni's data lake",
            "state": "running",
            "detail": "10 of 76 files",
            "required": False,
        }

    def test_docker_and_the_image_are_required_only_where_code_runs_in_docker(self) -> None:
        for where, required in (("docker", True), ("local", False), ("none", False)):
            steps = by_id(
                checklist(
                    settings(code=where, sandbox="bio"), DOCKER_UP, images_of(False, False, False), lake(), [], []
                )
            )

            assert (steps["docker"]["required"], steps["image"]["required"]) == (required, required)
            assert steps["model_key"]["required"] is True
            assert steps["data_lake"]["required"] is False

    def test_the_data_lake_is_never_required_whether_or_not_it_is_there(self) -> None:
        for present in (0, 30, 76):
            steps = by_id(
                checklist(settings(code="docker"), DOCKER_UP, images_of(True, True, True), lake(present), [], [])
            )

            assert steps["data_lake"]["required"] is False
        assert steps["data_lake"]["state"] == "done"


class TestStatus:
    def test_it_is_everything_a_page_shows(
        self, machine: Setup, docker: FakeDocker, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        docker.configure(images=[sandbox_image("base")])

        status = machine.status(settings(code="docker", sandbox="base"))

        assert set(status) == {"docker", "images", "data_lake", "jobs", "steps"}
        assert status["docker"]["running"] is True
        assert status["images"]["stages"][0]["built"] is True
        assert status["data_lake"]["directory"] == str(workspace.data_lake_dir)
        assert status["jobs"] == []
        assert [(step["id"], step["state"]) for step in status["steps"]] == [
            ("docker", "done"),
            ("image", "done"),
            ("data_lake", "todo"),
            ("model_key", "done"),
        ]

    def test_a_key_that_is_not_set_is_a_step_to_do(self, machine: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        steps = by_id(machine.status(settings(code="docker", sandbox="python"))["steps"])

        assert steps["model_key"]["state"] == "todo"
        assert steps["model_key"]["detail"] == "OPENAI_API_KEY is not set"

    def test_the_jobs_are_listed_and_the_steps_follow_them(self, machine: Setup, docker: FakeDocker) -> None:
        docker.build(wait=True)
        job = machine.build_image("base")
        wait_for(lambda: docker.started)

        status = machine.status(settings(code="docker", sandbox="base"))

        assert [item["id"] for item in status["jobs"]] == [job.id]
        assert status["images"]["stages"][0]["building"] is True
        assert by_id(status["steps"])["image"]["state"] == "running"
        docker.release()
        wait_for(lambda: done(job))
