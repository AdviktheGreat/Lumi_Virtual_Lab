"""Tests for where the agents' code runs in a conversation."""

from pathlib import Path

import pytest

from virtual_lab.constants import SANDBOX_DATA_LAKE_DIR
from virtual_lab.environment import sandbox_image
from virtual_lab.execution import DockerExecutor
from virtual_lab.server.code import CodeSetup
from virtual_lab.session import DockerSession, LocalSession


class TestCodeSetup:
    def test_code_runs_where_it_is_asked_to(self, tmp_path: Path) -> None:
        assert CodeSetup().session(tmp_path) is None

        local = CodeSetup(where="local", python="/usr/bin/python3")
        session = local.session(tmp_path / "local")
        assert isinstance(session, LocalSession) and session.python == "/usr/bin/python3"

        plain = CodeSetup(where="docker", network=False)
        assert isinstance(plain.session(tmp_path / "plain"), DockerSession)
        executor = plain.docker_executor()
        assert isinstance(executor, DockerExecutor)
        assert executor.image == DockerExecutor().image and not executor.allow_network
        assert CodeSetup(where="docker", sandbox="bio").docker_executor().image == sandbox_image("bio")

        with pytest.raises(ValueError):
            CodeSetup(where="cloud")
        with pytest.raises(ValueError):
            CodeSetup(sandbox="huge")

    def test_what_the_agents_are_told_of_biomnis_resources_is_one_of_three_and_leaves_the_lead_to_pick_by_default(
        self,
    ) -> None:
        assert CodeSetup().resources == "retrieve"
        assert [CodeSetup(resources=mode).resources for mode in ("retrieve", "all", "none")] == [
            "retrieve",
            "all",
            "none",
        ]
        with pytest.raises(ValueError, match="resources are one of retrieve, all, none, not 'some'"):
            CodeSetup(resources="some")

    def test_a_data_lake_that_is_there_is_mounted_in_every_docker_environment(self, tmp_path: Path) -> None:
        lake = tmp_path / "lake"
        lake.mkdir()

        for sandbox in ("python", "base", "bio", "full"):
            executor = CodeSetup(where="docker", sandbox=sandbox, data_lake=str(lake)).docker_executor()

            assert executor.data_lake == lake

    def test_a_data_lake_that_is_not_there_yet_is_left_out_so_that_code_runs_without_it(self, tmp_path: Path) -> None:
        for sandbox in ("python", "bio"):
            executor = CodeSetup(where="docker", sandbox=sandbox, data_lake=str(tmp_path / "not-yet")).docker_executor()

            assert executor.data_lake is None

    def test_a_file_where_the_data_lake_should_be_is_not_mounted(self, tmp_path: Path) -> None:
        (tmp_path / "lake").write_text("")

        assert (
            CodeSetup(where="docker", sandbox="bio", data_lake=str(tmp_path / "lake")).docker_executor().data_lake
            is None
        )

    def test_no_data_lake_is_none(self) -> None:
        assert CodeSetup(where="docker", sandbox="bio").docker_executor().data_lake is None
        assert CodeSetup(where="docker").docker_executor().data_lake is None

    def test_the_variables_to_pass_in_reach_the_container_in_every_docker_environment(self) -> None:
        names = ["ANTHROPIC_API_KEY", "GROQ_API_KEY"]

        for sandbox in ("python", "bio"):
            executor = CodeSetup(where="docker", sandbox=sandbox, forward_env=names).docker_executor()

            assert executor.forward_env == ("ANTHROPIC_API_KEY", "GROQ_API_KEY")

    def test_none_are_passed_in_unless_chosen(self) -> None:
        assert CodeSetup(where="docker", sandbox="bio").docker_executor().forward_env == ()
        assert CodeSetup(where="docker").docker_executor().forward_env == ()

    def test_a_data_lake_and_the_variables_are_in_what_a_session_runs_with(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
        lake = tmp_path / "lake"
        lake.mkdir()
        session = CodeSetup(
            where="docker", sandbox="bio", data_lake=str(lake), forward_env=["ANTHROPIC_API_KEY"]
        ).session(tmp_path / "work")

        assert isinstance(session, DockerSession)
        command = session.executor.build_command(tmp_path / "work", ("true",), "probe")
        assert f"type=bind,source={lake.resolve()},target={SANDBOX_DATA_LAKE_DIR},readonly" in command
        assert "ANTHROPIC_API_KEY" in command
        assert "sk-secret" not in " ".join(command)

    def test_the_names_of_variables_are_checked_and_listed_once_each(self) -> None:
        assert CodeSetup(forward_env=["A_KEY", "A_KEY", "B_KEY"]).forward_env == ["A_KEY", "B_KEY"]
        assert CodeSetup(forward_env=("A_KEY",)).forward_env == ["A_KEY"]
        for bad in (["has space"], ["1STARTS_WITH_DIGIT"], [""], [5], ["A=B"], ["OK", None]):
            with pytest.raises(ValueError, match="is not a valid environment variable name"):
                CodeSetup(forward_env=bad)
        with pytest.raises(ValueError, match="a list of names"):
            CodeSetup(forward_env="ANTHROPIC_API_KEY")

    def test_the_data_lake_is_text(self) -> None:
        with pytest.raises(ValueError, match="The data lake is a directory"):
            CodeSetup(data_lake=5)  # type: ignore[arg-type]
