"""Where the agents' code runs in a conversation, if anywhere."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from virtual_lab.execution import ENVIRONMENT_VARIABLE_NAME, DockerExecutor
from virtual_lab.session import DockerSession, LocalSession, Session, session_executor

CODE_PLACES = ("none", "docker", "local")
SANDBOXES = ("python", "base", "bio", "full")
RESOURCE_MODES = ("retrieve", "all", "none")


@dataclass
class CodeSetup:
    """Where agents' code runs, if anywhere.

    :param where: "none" for nowhere, "docker" for a container, or "local" for this machine,
        with no isolation.
    :param sandbox: With Docker, "python" for a plain Python image, or the stage of Biomni's
        environment to run in: "base", "bio", or "full", which must have been built.
    :param network: With Docker, whether code can reach the network.
    :param python: On this machine, the interpreter to run, or "" for this one.
    :param resources: What of Biomni's tools, data, and know-how the agents are told they can use
        in the session: "retrieve" for what the agenda needs, as the lead picks it, "all", or "none".
    :param data_lake: With Docker, the directory of Biomni's data lake to mount read-only, or "" for none.
        It is left out while the directory is not there, so a session set up before the data lake was
        fetched runs without it.
    :param forward_env: With Docker, the names of this machine's environment variables to pass in, such as
        the API keys some of Biomni's tools use to call a model. Code can read them, and with the network,
        send them anywhere, and a session whose variable is not set will not start.
    """

    where: str = "none"
    sandbox: str = "python"
    network: bool = True
    python: str = ""
    resources: str = "retrieve"
    data_lake: str = ""
    forward_env: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.where not in CODE_PLACES:
            raise ValueError(f"Code runs in one of {', '.join(CODE_PLACES)}, not {self.where!r}")
        if self.sandbox not in SANDBOXES:
            raise ValueError(f"The sandbox is one of {', '.join(SANDBOXES)}, not {self.sandbox!r}")
        if self.resources not in RESOURCE_MODES:
            raise ValueError(f"The resources are one of {', '.join(RESOURCE_MODES)}, not {self.resources!r}")
        if not isinstance(self.data_lake, str):
            raise ValueError(f"The data lake is a directory, not {self.data_lake!r}")
        if isinstance(self.forward_env, str):
            raise ValueError(f"The variables to forward are a list of names, not {self.forward_env!r}")
        for name in self.forward_env:
            if not isinstance(name, str) or not ENVIRONMENT_VARIABLE_NAME.match(name):
                raise ValueError(f"{name!r} is not a valid environment variable name")
        self.forward_env = list(dict.fromkeys(self.forward_env))

    def docker_executor(self) -> DockerExecutor:
        lake = Path(self.data_lake) if self.data_lake else None
        data_lake = lake if lake is not None and lake.is_dir() else None
        forward_env = tuple(self.forward_env)
        if self.sandbox == "python":
            return DockerExecutor(allow_network=self.network, data_lake=data_lake, forward_env=forward_env)
        return session_executor(self.sandbox, data_lake=data_lake, allow_network=self.network, forward_env=forward_env)

    def session(
        self, directory: Path, data: Mapping[str, str] | None = None, software: Mapping[str, str] | None = None
    ) -> Session | None:
        """A session for agents to run code in, in directory, or None where code is not run.

        :param data: Files and folders for the code to read, each by its path, with what it is.
        :param software: Software the code can use, each by its name, with what it does.
        """
        if self.where == "docker":
            return DockerSession(directory, executor=self.docker_executor(), data=data, software=software)
        if self.where == "local":
            return LocalSession(directory, python=self.python or None, warn=False, data=data, software=software)
        return None
