"""What code needs on this machine to run in Biomni's environment, and getting it.

Code runs in a container, in an image of Biomni's environment, and can be given Biomni's data lake to read. Docker
has to be installed and running, an image has to be built, which takes minutes to hours, and the data lake, about
11 GB, has to be fetched. A page is shown what is there and what is not, and starts the building and the fetching,
which go on in the background as jobs it can ask about and stop.
"""

import platform
import shutil
import subprocess
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from virtual_lab.constants import BIOMNI_RELEASE_URL, SANDBOX_PLATFORM
from virtual_lab.environment import (
    DATA_LAKE,
    SANDBOX_TARGETS,
    build_sandbox_image,
    download_data_lake,
    sandbox_image,
    sandbox_image_exists,
)
from virtual_lab.resources import commercial_data_lake
from virtual_lab.server.config import ChatConfig, data_lake_directory
from virtual_lab.server.errors import ApiError
from virtual_lab.server.jobs import Job, JobConflictError, Jobs
from virtual_lab.ui.library import missing_keys
from virtual_lab.ui.workspace import Settings, Workspace

# Seconds Docker is given to say whether it is running
DOCKER_TIMEOUT = 10.0

# What each stage of the image adds, and about how long it takes to build
STAGES = {
    "base": ("Biomni's analysis libraries", "a few minutes"),
    "bio": ("Adds Biomni's bioinformatics tools", "about half an hour"),
    "full": ("Adds R and the command-line tools", "hours"),
}

# The architectures that run the image without being emulated
NATIVE_MACHINES = ("x86_64", "amd64")


def free_space(directory: Path) -> int | None:
    """The bytes free on the disk a directory is, or will be, on, or None if that cannot be told."""
    for candidate in (directory, *directory.parents):
        try:
            return shutil.disk_usage(candidate).free
        except OSError:
            continue

    return None


def file_size(path: Path) -> int | None:
    """The size of a file, or None if there is none."""
    try:
        return path.stat().st_size if path.is_file() else None
    except OSError:
        return None


def checklist(
    settings: Settings,
    docker: dict[str, Any],
    images: dict[str, Any],
    data_lake: dict[str, Any],
    jobs: Iterable[dict[str, Any]],
    keys_missing: Sequence[str],
) -> list[dict[str, Any]]:
    """What is done and what is left to do, in the order to do it, for the code the settings run.

    Each step has an id, a title, a state ("done", "todo", "running" while a job does it, or "blocked" until a step
    before it is done), what is worth saying about it, and whether code in Docker cannot run without it.
    """
    wanted = settings.code == "docker"
    running = {(job["kind"], job["subject"]) for job in jobs if job["state"] in ("running", "stopping")}

    def step(key: str, title: str, state: str, detail: str, required: bool) -> dict[str, Any]:
        return {"id": key, "title": title, "state": state, "detail": detail, "required": required}

    if docker["running"]:
        version = f" {docker['version']}" if docker["version"] else ""
        steps = [step("docker", "Docker", "done", f"Docker{version} is running", wanted)]
    else:
        steps = [step("docker", "Docker", "todo", docker["message"], wanted)]

    if settings.sandbox in SANDBOX_TARGETS:
        stage = next(item for item in images["stages"] if item["target"] == settings.sandbox)
        title = f"Biomni's {settings.sandbox} environment"
        if stage["built"]:
            steps.append(step("image", title, "done", "Built", wanted))
        elif ("image", settings.sandbox) in running:
            steps.append(step("image", title, "running", "Being built", wanted))
        elif not docker["running"]:
            steps.append(step("image", title, "blocked", "Needs Docker", wanted))
        else:
            steps.append(step("image", title, "todo", f"Takes {stage['estimate']} to build", wanted))

    present = f"{data_lake['present']} of {data_lake['files']} files"
    if data_lake["complete"]:
        steps.append(step("data_lake", "Biomni's data lake", "done", present, False))
    elif ("data_lake", "data_lake") in running:
        steps.append(step("data_lake", "Biomni's data lake", "running", present, False))
    else:
        steps.append(step("data_lake", "Biomni's data lake", "todo", present, False))

    if keys_missing:
        steps.append(step("model_key", "Model key", "todo", f"{', '.join(keys_missing)} is not set", True))
    else:
        steps.append(step("model_key", "Model key", "done", f"The key {settings.model} needs is set", True))

    return steps


class Setup:
    """What a page needs to show and do about Docker, the sandbox images, and the data lake.

    :param workspace: Where the data lake is kept unless the settings say otherwise.
    :param docker_command: How to invoke Docker.
    :param release_url: Where Biomni publishes its data lake.
    """

    def __init__(
        self,
        workspace: Workspace,
        docker_command: Sequence[str] = ("docker",),
        release_url: str = BIOMNI_RELEASE_URL,
    ) -> None:
        self.workspace = workspace
        self.docker_command = tuple(docker_command)
        self.release_url = release_url
        self.jobs = Jobs()

    def close(self) -> None:
        """Stops the jobs that are running, for the server to stop."""
        self.jobs.close()

    def docker(self) -> dict[str, Any]:
        """Whether Docker is installed and running, with its version, and what is wrong if it is not."""
        command = self.docker_command
        if shutil.which(command[0]) is None:
            message = f'Docker was not found: "{command[0]}" is not installed or not on the path'
            return {"installed": False, "running": False, "version": None, "message": message}
        try:
            probe = subprocess.run(
                [*command, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=DOCKER_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            message = f"Docker did not answer: {error}"
            return {"installed": True, "running": False, "version": None, "message": message}
        if probe.returncode != 0:
            said = probe.stderr.strip().splitlines()
            message = "Docker is installed but is not running" + (f". It said: {said[0]}" if said else "")
            return {"installed": True, "running": False, "version": None, "message": message}

        return {"installed": True, "running": True, "version": probe.stdout.strip() or None, "message": None}

    def images(self, docker: dict[str, Any]) -> dict[str, Any]:
        """The stages of the sandbox image, each with whether it is built, which is None while Docker is not running."""
        stages = []
        building = {job.subject for job in self.jobs.active("image")}
        for target in SANDBOX_TARGETS:
            tag = sandbox_image(target)
            built = sandbox_image_exists(tag, self.docker_command) if docker["running"] else None
            summary, estimate = STAGES[target]
            stages.append(
                {
                    "target": target,
                    "tag": tag,
                    "summary": summary,
                    "estimate": estimate,
                    "built": built,
                    "building": target in building,
                }
            )

        return {
            "platform": SANDBOX_PLATFORM,
            "emulated": platform.machine().lower() not in NATIVE_MACHINES,
            "stages": stages,
        }

    def data_lake(self, settings: Settings) -> dict[str, Any]:
        """Where the data lake is kept, and how much of it is there."""
        directory = data_lake_directory(settings, self.workspace)
        sizes = [size for name in DATA_LAKE if (size := file_size(directory / name)) is not None]

        return {
            "directory": str(directory),
            "custom": bool(settings.data_lake),
            "files": len(DATA_LAKE),
            "present": len(sizes),
            "complete": len(sizes) == len(DATA_LAKE),
            "bytes": sum(sizes),
            "free_bytes": free_space(directory),
        }

    def data_lake_files(self, settings: Settings) -> list[dict[str, Any]]:
        """Every file of the data lake, with what it is, whether it is there, and whether commercial use is allowed."""
        directory = data_lake_directory(settings, self.workspace)
        commercial = set(commercial_data_lake())
        files = []
        for name, description in DATA_LAKE.items():
            size = file_size(directory / name)
            files.append(
                {
                    "name": name,
                    "description": description,
                    "present": size is not None,
                    "bytes": size,
                    "commercial": name in commercial,
                }
            )

        return files

    def status(self, settings: Settings) -> dict[str, Any]:
        """Everything a page shows of the setup: Docker, the images, the data lake, the jobs, and what is left to do."""
        docker = self.docker()
        images = self.images(docker)
        data_lake = self.data_lake(settings)
        jobs = self.jobs.snapshots()
        keys_missing = missing_keys([settings.model])

        return {
            "docker": docker,
            "images": images,
            "data_lake": data_lake,
            "jobs": jobs,
            "steps": checklist(settings, docker, images, data_lake, jobs, keys_missing),
        }

    def build_image(self, target: str) -> Job:
        """Starts building a stage of the sandbox image.

        :raises ApiError: If there is no such stage, Docker is not running, the image is built, or an image is
            being built, which only one is at a time.
        """
        if target not in SANDBOX_TARGETS:
            raise ApiError(422, "invalid", f"A stage of the image is one of {', '.join(SANDBOX_TARGETS)}")
        docker = self.docker()
        if not docker["running"]:
            raise ApiError(409, "docker_unavailable", docker["message"])
        if sandbox_image_exists(sandbox_image(target), self.docker_command):
            raise ApiError(409, "already_built", f"Biomni's {target} environment is already built")

        def work(job: Job) -> str:
            job.update(f"Building Biomni's {target} environment")

            def output(line: str) -> None:
                job.log(line)
                if line.strip():
                    job.update(line.strip())

            build_sandbox_image(target, docker_command=self.docker_command, on_output=output, stop=job.stop)

            return f"Built Biomni's {target} environment"

        return self._start("image", target, f"Building Biomni's {target} environment", work)

    def download_data_lake(self, settings: Settings, names: Sequence[str] | None = None) -> Job:
        """Starts fetching the data lake, or some of it. What is there already is left alone.

        :param names: The files to fetch, or None for all.
        :raises ApiError: If a file is not in the data lake, none is asked for, or it is being fetched.
        """
        wanted = list(DATA_LAKE) if names is None else list(dict.fromkeys(names))
        if not wanted:
            raise ApiError(422, "invalid", "Choose at least one file of the data lake to fetch")
        if unknown := [name for name in wanted if name not in DATA_LAKE]:
            raise ApiError(422, "invalid", f"The data lake has no file {', '.join(unknown)}")
        directory = data_lake_directory(settings, self.workspace)
        total = len(wanted)

        def work(job: Job) -> str:
            job.update(
                "Fetching the data lake", done=0, total=total, current=None, bytes=0, bytes_total=None, fetched=0
            )
            fetched = 0

            def progress(name: str, written: int, announced: int | None) -> None:
                job.update(
                    f"Fetching {name}",
                    done=wanted.index(name),
                    current=name,
                    bytes=written,
                    bytes_total=announced,
                    fetched=fetched + written,
                )

            def finished(name: str, size: int, announced: int | None) -> None:
                nonlocal fetched
                fetched += size
                job.log(f"Fetched {name}, {size:,} bytes")

            outcome = download_data_lake(
                directory,
                wanted,
                self.release_url,
                on_file=finished,
                on_progress=progress,
                stop=job.stop,
            )
            job.update(done=total, current=None, bytes=0, bytes_total=None)
            for name, reason in outcome.failed.items():
                job.log(f"Could not fetch {name}: {reason}")
            if outcome.failed:
                first, reason = next(iter(outcome.failed.items()))
                raise RuntimeError(f"{len(outcome.failed)} of {total} files could not be fetched. {first}: {reason}")

            return f"Fetched {len(outcome.downloaded)} files, and {len(outcome.present)} were there already"

        return self._start("data_lake", "data_lake", "Fetching Biomni's data lake", work)

    def missing(self, config: ChatConfig) -> list[dict[str, str]]:
        """What a conversation's code cannot run without, which is nothing unless it runs in Docker.

        Each is an id, "docker" or "image", with what to say of it.
        """
        if config.code.where != "docker":
            return []
        docker = self.docker()
        if not docker["running"]:
            return [{"id": "docker", "message": docker["message"]}]
        target = config.code.sandbox
        if target in SANDBOX_TARGETS and not sandbox_image_exists(sandbox_image(target), self.docker_command):
            message = (
                f"Biomni's {target} environment is not built. Build it in the setup, which takes {STAGES[target][1]}"
            )
            return [{"id": "image", "message": message}]

        return []

    def _start(self, kind: str, subject: str, title: str, work: Callable[[Job], str | None]) -> Job:
        try:
            return self.jobs.start(kind, subject, title, work)
        except JobConflictError as error:
            raise ApiError(409, "busy", f"{error.job.title} is already running", job=error.job.snapshot()) from error
