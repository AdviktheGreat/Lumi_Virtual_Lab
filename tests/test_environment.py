"""Tests for the sandbox image built from Biomni's environment, and Biomni's data lake."""

import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import requests

import virtual_lab.environment as environment
from virtual_lab.__about__ import __version__
from virtual_lab.constants import BIOMNI_RELEASE_URL, SANDBOX_DATA_LAKE_DIR
from virtual_lab.environment import (
    DATA_LAKE,
    SANDBOX_LIBRARIES,
    SANDBOX_TARGETS,
    StoppedError,
    build_command,
    build_sandbox_image,
    download_data_lake,
    end_build,
    sandbox_context,
    sandbox_image,
)
from virtual_lab.execution import DockerExecutor, DockerUnavailableError, ExecutionError
from virtual_lab.repair import describe_executor

from setup_fakes import FakeDocker as FakeDockerProgram, in_thread, wait_for

DOCKERFILE = sandbox_context() / "Dockerfile"


class TestImageDefinition:
    def test_the_stages_are_the_targets(self) -> None:
        stages = re.findall(r"^FROM \S+ AS (\w+)$", DOCKERFILE.read_text(), flags=re.MULTILINE)

        assert tuple(stages) == SANDBOX_TARGETS

    def test_every_copied_file_ships_with_the_package(self) -> None:
        copied = [
            source
            for line in DOCKERFILE.read_text().splitlines()
            if line.startswith("COPY ")
            for source in line.split()[1:-1]
        ]

        assert copied
        for source in copied:
            assert (sandbox_context() / source).is_file(), source

    def test_biomnis_files_are_attributed(self) -> None:
        notice = (sandbox_context() / "NOTICE").read_text()

        assert "Apache License, Version 2.0" in notice
        assert "snap-stanford/Biomni" in notice

    def test_the_descriptions_cover_the_data_lake_and_libraries(self) -> None:
        assert len(DATA_LAKE) == 76
        assert "DisGeNET.parquet" in DATA_LAKE
        assert "scanpy" in SANDBOX_LIBRARIES


def full_stage_runs() -> list[str]:
    """The RUN steps of the full stage, in order, with their continued lines joined."""
    steps, current = [], ""
    for line in DOCKERFILE.read_text().splitlines():
        if not current and (not line.strip() or line.lstrip().startswith("#")):
            continue

        if current and line.lstrip().startswith("#"):
            continue

        if line.rstrip().endswith("\\"):
            current += line.rstrip()[:-1] + " "
            continue

        steps.append(current + line)
        current = ""

    start = next(index for index, step in enumerate(steps) if step.startswith("FROM ") and step.endswith("AS full"))
    return [step[len("RUN ") :] for step in steps[start + 1 :] if step.startswith("RUN ")]


def names_in(script: str, variable: str) -> list[str]:
    """The strings in a vector the R script assigns, such as cran_packages <- c("a", "b")."""
    vector = re.search(rf"{variable}\s*<-\s*c\((.*?)\)", script, flags=re.DOTALL)
    assert vector, variable
    return re.findall(r'"([^"]+)"', vector.group(1))


class TestFullStage:
    """Biomni's R and command-line installers report success for what they did not install, which
    is what these steps are for. They are tested as text; the image's own build runs them."""

    def test_what_the_builds_need_is_installed_before_they_run(self) -> None:
        runs = full_stage_runs()
        needs = next(index for index, run in enumerate(runs) if "apt-get install" in run)
        r_install = next(index for index, run in enumerate(runs) if "Rscript install_r_packages.R" in run)
        cli_install = next(index for index, run in enumerate(runs) if "install_cli_tools.sh" in run)

        assert needs < r_install < cli_install
        for package in ("cmake", "zip", "zlib1g-dev"):
            assert re.search(rf"apt-get install .*\b{package}\b", runs[needs]), package

    def test_the_libraries_r_packages_link_against_are_installed_before_they_are_built(self) -> None:
        r_install = next(run for run in full_stage_runs() if "Rscript install_r_packages.R" in run)

        before = r_install[: r_install.index("Rscript install_r_packages.R")]
        for library in ("xz", "libxml2-devel", "libnetcdf", "r-gdtools"):
            assert re.search(rf"conda install .*\b{library}\b", before), library

    def test_every_r_package_the_script_installs_is_checked_for_at_the_end(self) -> None:
        script = (sandbox_context() / "biomni_env" / "install_r_packages.R").read_text()
        installed = {*names_in(script, "cran_packages"), *names_in(script, "bioc_packages"), "WGCNA", "clusterProfiler"}

        check = full_stage_runs()[-1]

        assert "stop(" in check
        assert installed <= set(names_in(check, "wanted")), installed - set(names_in(check, "wanted"))

    def test_every_tool_in_the_config_is_checked_for_at_the_end(self) -> None:
        check = full_stage_runs()[-1]

        assert ".tools[].binary_path" in check and "cli_tools_config.json" in check
        assert "jq -e '.tools | length > 0'" in check, "a config with no tools must not pass as checked"
        assert 'test -x "/opt/biomni_tools/bin/' in check and "exit 1" in check
        for program in ("plink2", "iqtree2", "gcta64", "bwa", "findMotifs.pl"):
            assert re.search(rf"\b{re.escape(program)}\b", check), program

    def test_the_check_is_not_in_a_step_whose_failure_would_discard_the_builds(self) -> None:
        builds = [
            run for run in full_stage_runs()[:-1] if re.search(r"install_r_packages\.R|install_cli_tools\.sh", run)
        ]

        assert len(builds) == 2
        assert all("stop(" not in run and "requireNamespace" not in run for run in builds)

    def test_gcta_is_fetched_from_where_it_can_be_and_checked_against_a_hash(self) -> None:
        run = next(run for run in full_stage_runs() if "gcta64" in run and "curl" in run)

        assert "github.com/jianyangqt/gcta/releases/download/" in run
        assert re.search(r"echo \"[0-9a-f]{64}  /opt/biomni_tools/bin/gcta64\" +\| +sha256sum -c -", run)

    def test_homer_is_installed_by_its_documented_command_and_linked_beside_the_other_tools(self) -> None:
        run = next(run for run in full_stage_runs() if "configureHomer.pl" in run)

        assert "perl configureHomer.pl -install" in run
        assert "-local" not in run
        assert "test -x bin/findMotifs.pl" in run
        assert 'ln -sf "$PWD/$program" "/opt/biomni_tools/bin/' in run
        assert '$(basename "$program")" || exit 1' in run, "a link that cannot be made must fail the step"

    def test_biomnis_script_still_gives_homer_the_options_that_make_the_step_above_necessary(self) -> None:
        script = (sandbox_context() / "biomni_env" / "install_cli_tools.sh").read_text()

        assert 'configureHomer.pl" -install -local' in script


class TestTags:
    def test_the_tag_names_the_stage_and_version(self) -> None:
        assert sandbox_image("bio") == f"virtual-lab-sandbox:bio-{__version__}-linux-amd64"

    def test_a_native_build_has_a_tag_of_its_own(self) -> None:
        assert sandbox_image("base", platform=None) == f"virtual-lab-sandbox:base-{__version__}-native"

    def test_an_unknown_stage_is_refused(self) -> None:
        with pytest.raises(ValueError, match="target must be one of"):
            sandbox_image("everything")

    def test_the_build_command_ends_with_the_context(self) -> None:
        command = build_command(
            "full", "tag:1", platform="linux/amd64", build_args={"MINIFORGE_VERSION": "1"}
        )

        assert command == (
            "docker", "build", "--target", "full", "--tag", "tag:1", "--platform", "linux/amd64",
            "--build-arg", "MINIFORGE_VERSION=1", str(sandbox_context()),
        )

    def test_images_are_built_for_x86_64_by_default(self) -> None:
        command = build_command("bio", "tag:1")

        assert command[command.index("--platform") + 1] == "linux/amd64"

    def test_the_machine_s_own_platform_can_be_asked_for(self) -> None:
        assert "--platform" not in build_command("base", "tag:1", platform=None)


class FakeDocker:
    """Records docker commands and answers them as told."""

    def __init__(self, has_image: bool = False, build_code: int = 0) -> None:
        self.has_image = has_image
        self.build_code = build_code
        self.commands: list[list[str]] = []

    def run(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.commands.append(list(command))
        if command[1:4] == ["image", "ls", "--quiet"]:
            # Docker lists nothing, successfully, for an image it does not have
            return subprocess.CompletedProcess(command, 0, "d0572aed6cf0\n" if self.has_image else "", "")
        return subprocess.CompletedProcess(command, self.build_code)

    @property
    def builds(self) -> list[list[str]]:
        return [command for command in self.commands if command[1] == "build"]


@pytest.fixture
def docker(monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    fake = FakeDocker()
    monkeypatch.setattr(environment.subprocess, "run", fake.run)
    monkeypatch.setattr(environment.shutil, "which", lambda name: f"/usr/bin/{name}")
    return fake


class TestBuild:
    def test_an_image_is_built_when_missing(self, docker: FakeDocker) -> None:
        tag = build_sandbox_image("base")

        assert tag == sandbox_image("base")
        assert docker.builds == [list(build_command("base", tag))]

    def test_a_native_build_does_not_reuse_the_x86_64_image(self, docker: FakeDocker) -> None:
        tag = build_sandbox_image("base", platform=None)

        assert tag == sandbox_image("base", platform=None)
        assert ["docker", "image", "ls", "--quiet", tag] in docker.commands
        assert "--platform" not in docker.builds[0]

    def test_an_existing_image_is_reused(self, docker: FakeDocker) -> None:
        docker.has_image = True

        build_sandbox_image("base")

        assert docker.builds == []

    def test_a_rebuild_can_be_forced(self, docker: FakeDocker) -> None:
        docker.has_image = True

        build_sandbox_image("base", rebuild=True)

        assert len(docker.builds) == 1

    def test_a_failed_build_says_what_was_run(self, docker: FakeDocker) -> None:
        docker.build_code = 2

        with pytest.raises(ExecutionError, match="exit code 2.*docker build --target bio"):
            build_sandbox_image("bio")

    def test_missing_docker_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment.shutil, "which", lambda name: None)

        with pytest.raises(DockerUnavailableError, match="Install Docker"):
            build_sandbox_image("base")


class FakeDownload:
    """Stands in for a streamed response from Biomni's release bucket."""

    def __init__(self, body: bytes, length: int | None = None, status: int = 200) -> None:
        self.body = body
        self.status = status
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} Error")

    def iter_content(self, chunk_size: int) -> Any:
        for start in range(0, len(self.body), 3):
            yield self.body[start : start + 3]

    def __enter__(self) -> "FakeDownload":
        return self

    def __exit__(self, *args: object) -> None:
        return None


@pytest.fixture
def bucket(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Serves files by name; anything not listed is a 404."""
    served: dict[str, Any] = {"files": {}, "urls": []}

    def get(url: str, **kwargs: Any) -> FakeDownload:
        served["urls"].append(url)
        name = url.rsplit("/", 1)[1]
        answer = served["files"].get(name)
        if isinstance(answer, FakeDownload):
            return answer
        if answer is None:
            return FakeDownload(b"", status=404)
        return FakeDownload(answer, length=len(answer))

    monkeypatch.setattr(environment.requests, "get", get)
    return served


class TestDownloadDataLake:
    def test_files_are_fetched_from_biomnis_bucket(self, bucket: dict[str, Any], tmp_path: Path) -> None:
        bucket["files"] = {"gene_info.parquet": b"genes", "hp.obo": b"terms"}
        finished = []

        outcome = download_data_lake(
            tmp_path, names=["gene_info.parquet", "hp.obo"], on_file=lambda *args: finished.append(args)
        )

        assert outcome.complete
        assert outcome.downloaded == ["gene_info.parquet", "hp.obo"]
        assert (tmp_path / "gene_info.parquet").read_bytes() == b"genes"
        assert bucket["urls"][0] == f"{BIOMNI_RELEASE_URL}/data_lake/gene_info.parquet"
        assert finished == [("gene_info.parquet", 5, 5), ("hp.obo", 5, 5)]

    def test_everything_is_fetched_by_default(self, bucket: dict[str, Any], tmp_path: Path) -> None:
        bucket["files"] = {name: b"x" for name in DATA_LAKE}

        outcome = download_data_lake(tmp_path)

        assert sorted(outcome.downloaded) == sorted(DATA_LAKE)

    def test_present_files_are_left_alone(self, bucket: dict[str, Any], tmp_path: Path) -> None:
        (tmp_path / "hp.obo").write_bytes(b"mine")

        outcome = download_data_lake(tmp_path, names=["hp.obo"])

        assert outcome.present == ["hp.obo"]
        assert bucket["urls"] == []
        assert (tmp_path / "hp.obo").read_bytes() == b"mine"

    def test_a_short_body_is_not_kept(self, bucket: dict[str, Any], tmp_path: Path) -> None:
        bucket["files"] = {"kg.csv": FakeDownload(b"trunc", length=100)}

        outcome = download_data_lake(tmp_path, names=["kg.csv"])

        assert "Received 5 of the 100 bytes" in outcome.failed["kg.csv"]
        assert list(tmp_path.iterdir()) == []

    def test_a_failed_request_is_reported_and_the_rest_continue(self, bucket: dict[str, Any], tmp_path: Path) -> None:
        bucket["files"] = {"hp.obo": b"terms"}

        outcome = download_data_lake(tmp_path, names=["missing.csv", "hp.obo"])

        assert not outcome.complete
        assert "404" in outcome.failed["missing.csv"]
        assert outcome.downloaded == ["hp.obo"]
        assert sorted(path.name for path in tmp_path.iterdir()) == ["hp.obo"]

    def test_a_body_of_unannounced_length_is_kept(self, bucket: dict[str, Any], tmp_path: Path) -> None:
        bucket["files"] = {"hp.obo": FakeDownload(b"terms")}

        outcome = download_data_lake(tmp_path, names=["hp.obo"])

        assert outcome.downloaded == ["hp.obo"]

    def test_a_compressed_body_is_not_measured_against_its_encoded_length(
        self, bucket: dict[str, Any], tmp_path: Path
    ) -> None:
        response = FakeDownload(b"decoded terms", length=4)
        response.headers["Content-Encoding"] = "gzip"
        bucket["files"] = {"hp.obo": response}

        outcome = download_data_lake(tmp_path, names=["hp.obo"])

        assert outcome.downloaded == ["hp.obo"]
        assert (tmp_path / "hp.obo").read_bytes() == b"decoded terms"

    @pytest.mark.parametrize("name", ["../escape.csv", "sub/file.csv", "..", "", "a\\b"])
    def test_a_name_that_leaves_the_directory_is_refused(self, bucket: dict[str, Any], tmp_path: Path, name: str) -> None:
        with pytest.raises(ValueError, match="Not a data lake file name"):
            download_data_lake(tmp_path / "lake", names=["hp.obo", name])

        assert bucket["urls"] == []


class TestDataLakeMount:
    def arguments(self, executor: DockerExecutor, tmp_path: Path) -> tuple[str, ...]:
        work = tmp_path / "work"
        work.mkdir(exist_ok=True)
        return executor.build_command(directory=work, command=("python3", "./a.py"), container_name="probe")

    def test_the_data_lake_is_mounted_read_only(self, tmp_path: Path) -> None:
        lake = tmp_path / "lake"
        lake.mkdir()

        arguments = self.arguments(DockerExecutor(data_lake=lake), tmp_path)

        assert f"type=bind,source={lake.resolve()},target={SANDBOX_DATA_LAKE_DIR},readonly" in arguments
        assert f"BIOMNI_DATA_LAKE={SANDBOX_DATA_LAKE_DIR}" in arguments
        # Options, so before the image
        assert arguments.index(f"BIOMNI_DATA_LAKE={SANDBOX_DATA_LAKE_DIR}") < arguments.index(DockerExecutor().image)

    def test_no_data_lake_means_no_mount(self, tmp_path: Path) -> None:
        arguments = self.arguments(DockerExecutor(), tmp_path)

        assert not any(SANDBOX_DATA_LAKE_DIR in argument for argument in arguments)

    def test_a_missing_directory_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ExecutionError, match="not a directory"):
            self.arguments(DockerExecutor(data_lake=tmp_path / "absent"), tmp_path)

    def test_a_path_docker_cannot_mount_is_refused(self, tmp_path: Path) -> None:
        lake = tmp_path / "a,readonly=false"
        lake.mkdir()

        with pytest.raises(ExecutionError, match="comma"):
            self.arguments(DockerExecutor(data_lake=lake), tmp_path)

    @pytest.mark.parametrize("where", ["inside", "same", "around"])
    def test_a_data_lake_overlapping_the_working_directory_is_refused(self, tmp_path: Path, where: str) -> None:
        work = tmp_path / "work"
        lake = {"inside": work / "lake", "same": work, "around": tmp_path}[where]
        lake.mkdir(parents=True, exist_ok=True)

        with pytest.raises(ExecutionError, match="overlaps the directory code runs in"):
            self.arguments(DockerExecutor(data_lake=lake), tmp_path)

    def test_a_sibling_whose_name_extends_the_work_directory_is_allowed(self, tmp_path: Path) -> None:
        lake = tmp_path / "work-lake"
        lake.mkdir()

        assert f"BIOMNI_DATA_LAKE={SANDBOX_DATA_LAKE_DIR}" in self.arguments(DockerExecutor(data_lake=lake), tmp_path)

    def test_the_record_says_which_data_lake_was_used(self, tmp_path: Path) -> None:
        assert describe_executor(DockerExecutor(data_lake=tmp_path))["data_lake"] == str(tmp_path)


class TestRunPlatform:
    def arguments(self, executor: DockerExecutor, tmp_path: Path) -> tuple[str, ...]:
        return executor.build_command(directory=tmp_path, command=("true",), container_name="probe")

    def test_the_platform_is_passed_before_the_image(self, tmp_path: Path) -> None:
        executor = DockerExecutor(image="virtual-lab-sandbox:bio", platform="linux/amd64")
        arguments = self.arguments(executor, tmp_path)

        position = arguments.index("--platform")
        assert arguments[position + 1] == "linux/amd64"
        assert position < arguments.index("virtual-lab-sandbox:bio")

    def test_no_platform_leaves_the_choice_to_docker(self, tmp_path: Path) -> None:
        assert "--platform" not in self.arguments(DockerExecutor(), tmp_path)

    def test_the_record_says_which_platform_was_used(self) -> None:
        assert describe_executor(DockerExecutor(platform="linux/amd64"))["platform"] == "linux/amd64"


@pytest.fixture
def program(tmp_path: Path) -> FakeDockerProgram:
    """A program that answers as docker does, which is run for real."""
    return FakeDockerProgram(tmp_path / "docker")


class TestBuildOutput:
    def test_what_docker_prints_is_passed_on_a_line_at_a_time_errors_with_the_rest(
        self, program: FakeDockerProgram
    ) -> None:
        program.build(lines=["#1 first", "#2 second, to the error stream", "#3 third"])
        lines: list[str] = []

        tag = build_sandbox_image("base", docker_command=program.command, on_output=lines.append)

        assert lines == ["#1 first", "#2 second, to the error stream", "#3 third"]
        assert tag == sandbox_image("base")
        assert program.images == [tag]
        assert program.builds == [list(build_command("base", tag, docker_command=("docker",)))[1:]]

    def test_a_build_that_fails_says_so_after_its_output_has_been_passed_on(self, program: FakeDockerProgram) -> None:
        program.build(lines=["#1 step", "ERROR: it broke"], exit=1)
        lines: list[str] = []

        with pytest.raises(ExecutionError, match="exit code 1.*docker.py build --target bio"):
            build_sandbox_image("bio", docker_command=program.command, on_output=lines.append)

        assert lines == ["#1 step", "ERROR: it broke"]
        assert program.images == []

    def test_a_built_image_is_not_built_again(self, program: FakeDockerProgram) -> None:
        program.configure(images=[sandbox_image("base")])
        lines: list[str] = []

        build_sandbox_image("base", docker_command=program.command, on_output=lines.append)

        assert program.builds == []
        assert lines == []

    def test_a_build_asked_to_stop_and_not_asked_for_its_output_goes_on_to_the_end(
        self, program: FakeDockerProgram
    ) -> None:
        build_sandbox_image("base", docker_command=program.command, stop=threading.Event())

        assert program.images == [sandbox_image("base")]

    def test_a_line_ends_at_a_carriage_return_as_a_progress_display_ends_it(self, program: FakeDockerProgram) -> None:
        program.build(lines=["one\rtwo"])
        lines: list[str] = []

        build_sandbox_image("base", docker_command=program.command, on_output=lines.append)

        assert lines == ["one", "two"]

    def test_the_build_is_ended_if_what_takes_its_output_fails(self, program: FakeDockerProgram) -> None:
        program.build(wait=True)

        def refuse(line: str) -> None:
            raise RuntimeError("no room for output")

        thread, outcome = in_thread(
            lambda: build_sandbox_image("base", docker_command=program.command, on_output=refuse)
        )
        thread.join(10)

        assert not thread.is_alive()
        assert isinstance(outcome["raised"], RuntimeError)
        assert program.images == []
        wait_for(lambda: not program.running, timeout=5)

    def test_output_that_is_not_text_is_passed_on_with_what_cannot_be_read_replaced(
        self, program: FakeDockerProgram
    ) -> None:
        program.build(lines=["before"], raw=["fffe", "6166746572"])
        lines: list[str] = []

        build_sandbox_image("base", docker_command=program.command, on_output=lines.append)

        assert lines == ["before", "\ufffd\ufffd", "after"]

    def test_no_thread_is_kept_to_watch_for_a_stop_that_cannot_come_or_has_not_to_be_waited_for(
        self, program: FakeDockerProgram
    ) -> None:
        def watchers() -> list[str]:
            return [thread.name for thread in threading.enumerate() if thread.name == "virtual-lab-build-stop"]

        seen: list[list[str]] = []
        build_sandbox_image("base", docker_command=program.command, on_output=lambda line: seen.append(watchers()))
        assert seen and all(not found for found in seen)

        build_sandbox_image(
            "bio",
            docker_command=program.command,
            on_output=lambda line: seen.append(watchers()),
            stop=threading.Event(),
        )

        assert seen[-1] == ["virtual-lab-build-stop"]
        assert watchers() == []


class TestStoppingABuild:
    def start(self, program: FakeDockerProgram, stop: threading.Event) -> tuple[threading.Thread, dict[str, Any]]:
        thread, outcome = in_thread(
            lambda: build_sandbox_image("full", docker_command=program.command, on_output=lambda line: None, stop=stop)
        )
        wait_for(lambda: program.started)

        return thread, outcome

    def test_a_build_is_ended_when_asked_to_stop(self, program: FakeDockerProgram) -> None:
        program.build(wait=True)
        stop = threading.Event()
        thread, outcome = self.start(program, stop)

        stop.set()
        thread.join(10)

        assert not thread.is_alive()
        assert isinstance(outcome["raised"], StoppedError)
        assert "was stopped" in str(outcome["raised"])
        assert program.images == []

    def test_a_build_is_ended_when_asked_to_stop_long_after_it_began(self, program: FakeDockerProgram) -> None:
        program.build(wait=True)
        stop = threading.Event()
        thread, outcome = self.start(program, stop)

        time.sleep(0.5)
        assert thread.is_alive()
        stop.set()
        thread.join(10)

        assert not thread.is_alive()
        assert isinstance(outcome["raised"], StoppedError)
        wait_for(lambda: not program.running, timeout=5)

    def test_a_build_that_ignores_being_asked_is_killed_after_the_time_it_is_given(
        self, program: FakeDockerProgram, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(environment, "BUILD_STOP_GRACE_SECONDS", 0.3)
        program.build(wait=True, ignore_term=True)
        stop = threading.Event()
        thread, outcome = self.start(program, stop)

        started = time.monotonic()
        stop.set()
        thread.join(10)

        assert not thread.is_alive()
        assert isinstance(outcome["raised"], StoppedError)
        assert time.monotonic() - started >= 0.3

    def test_what_the_build_started_is_ended_with_it(self, program: FakeDockerProgram) -> None:
        # Docker's client starts a plugin that does the build, and that holds its output open
        program.build(wait=True, child=True)
        stop = threading.Event()
        thread, outcome = self.start(program, stop)

        stop.set()
        thread.join(10)

        assert not thread.is_alive()
        assert isinstance(outcome["raised"], StoppedError)

    def test_a_build_that_fails_when_not_asked_to_stop_is_a_failure_and_not_a_stop(
        self, program: FakeDockerProgram
    ) -> None:
        program.build(exit=1)

        with pytest.raises(ExecutionError):
            build_sandbox_image("base", docker_command=program.command, stop=threading.Event())

    def test_ending_a_build_that_has_ended_is_not_an_error(self) -> None:
        process = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
        process.wait()

        end_build(process, force=False)
        end_build(process, force=True)

    def test_a_build_finished_before_it_is_asked_to_stop_is_a_build(self, program: FakeDockerProgram) -> None:
        stop = threading.Event()

        tag = build_sandbox_image("base", docker_command=program.command, on_output=lambda line: None, stop=stop)
        stop.set()

        assert program.images == [tag]


class TestFetchProgress:
    def test_progress_is_reported_as_each_part_is_written(self, bucket: dict[str, Any], tmp_path: Path) -> None:
        bucket["files"] = {"hp.obo": FakeDownload(b"abcdefgh", length=8)}
        seen: list[tuple[str, int, int | None]] = []

        download_data_lake(tmp_path, names=["hp.obo"], on_progress=lambda *args: seen.append(args))

        assert seen == [("hp.obo", 0, 8), ("hp.obo", 3, 8), ("hp.obo", 6, 8), ("hp.obo", 8, 8)]

    def test_a_length_the_server_did_not_announce_is_reported_as_none(
        self, bucket: dict[str, Any], tmp_path: Path
    ) -> None:
        bucket["files"] = {"hp.obo": FakeDownload(b"abcd")}
        seen: list[tuple[str, int, int | None]] = []

        download_data_lake(tmp_path, names=["hp.obo"], on_progress=lambda *args: seen.append(args))

        assert seen == [("hp.obo", 0, None), ("hp.obo", 3, None), ("hp.obo", 4, None)]

    def test_a_file_already_there_is_not_reported(self, bucket: dict[str, Any], tmp_path: Path) -> None:
        (tmp_path / "hp.obo").write_bytes(b"mine")
        seen: list[Any] = []

        download_data_lake(tmp_path, names=["hp.obo"], on_progress=seen.append)

        assert seen == []

    def test_the_file_each_report_is_of_is_named(self, bucket: dict[str, Any], tmp_path: Path) -> None:
        bucket["files"] = {"a.csv": b"aa", "b.csv": b"bbbb"}
        seen: list[tuple[str, int, int | None]] = []

        download_data_lake(tmp_path, names=["a.csv", "b.csv"], on_progress=lambda *args: seen.append(args))

        assert [item[0] for item in seen] == ["a.csv", "a.csv", "b.csv", "b.csv", "b.csv"]


class TestStoppingADownload:
    def test_a_file_being_fetched_is_dropped_when_asked_to_stop_and_none_is_left_partway(
        self, bucket: dict[str, Any], tmp_path: Path
    ) -> None:
        bucket["files"] = {"hp.obo": b"abcdefghij", "kg.csv": b"next"}
        stop = threading.Event()

        def progress(name: str, written: int, announced: int | None) -> None:
            if written >= 3:
                stop.set()

        with pytest.raises(StoppedError, match="hp.obo was stopped"):
            download_data_lake(tmp_path, names=["hp.obo", "kg.csv"], on_progress=progress, stop=stop)

        assert list(tmp_path.iterdir()) == []
        assert bucket["urls"] == [f"{BIOMNI_RELEASE_URL}/data_lake/hp.obo"]

    def test_files_fetched_before_the_stop_are_kept_and_the_rest_are_not_asked_for(
        self, bucket: dict[str, Any], tmp_path: Path
    ) -> None:
        bucket["files"] = {"a.csv": b"aa", "b.csv": b"bb", "c.csv": b"cc"}
        stop = threading.Event()

        with pytest.raises(StoppedError, match="Fetching the data lake was stopped"):
            download_data_lake(tmp_path, names=["a.csv", "b.csv", "c.csv"], on_file=lambda *args: stop.set(), stop=stop)

        assert [path.name for path in tmp_path.iterdir()] == ["a.csv"]
        assert len(bucket["urls"]) == 1

    def test_a_stop_asked_for_before_it_begins_fetches_nothing(self, bucket: dict[str, Any], tmp_path: Path) -> None:
        bucket["files"] = {"a.csv": b"aa"}
        stop = threading.Event()
        stop.set()

        with pytest.raises(StoppedError):
            download_data_lake(tmp_path, names=["a.csv"], stop=stop)

        assert bucket["urls"] == []

    def test_an_unset_stop_does_not_stop_it(self, bucket: dict[str, Any], tmp_path: Path) -> None:
        bucket["files"] = {"a.csv": b"aa"}

        outcome = download_data_lake(tmp_path, names=["a.csv"], stop=threading.Event())

        assert outcome.downloaded == ["a.csv"]
