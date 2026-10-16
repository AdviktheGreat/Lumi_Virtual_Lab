"""Tests for the workspace, where conversations and settings are kept, and for what the server offers to choose
from."""

import errno
import json
import os
import threading
from dataclasses import fields
from datetime import datetime
from pathlib import Path

import pytest

from virtual_lab.constants import DEFAULT_MODEL
from virtual_lab.server import library
from virtual_lab.server.workspace import MAX_SLUG_CHARS, SETTING_KINDS, Settings, Workspace, slug
from virtual_lab.utils import write_atomically

from conftest import TEST_MODEL

NOW = datetime(2026, 10, 7, 15, 30)


class TestSlug:
    def test_a_title_becomes_lower_case_words_joined_by_dashes(self) -> None:
        assert slug("Design Nanobodies for KP.3!") == "design-nanobodies-for-kp-3"

    def test_a_long_title_is_cut_at_a_word(self) -> None:
        name = slug("word " * 40)
        assert len(name) <= MAX_SLUG_CHARS
        assert name.endswith("word")

    def test_a_title_with_no_letters_is_untitled(self) -> None:
        assert slug("?!") == "untitled"


class TestWorkspace:
    def test_a_new_directory_is_named_after_when_and_what_and_never_reused(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)

        first = workspace.new_chat_directory("Choose the epitopes", now=NOW)
        second = workspace.new_chat_directory("Choose the epitopes", now=NOW)

        assert first == workspace.chats_dir / "2026-10-07_1530_choose-the-epitopes"
        assert second.name == "2026-10-07_1530_choose-the-epitopes-2"
        assert first.is_dir() and second.is_dir()

    def test_a_directory_made_by_another_request_in_the_meantime_is_not_taken(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspace = Workspace(tmp_path)
        real_mkdir = Path.mkdir
        rivals: list[Path] = []

        def racing(self: Path, *args: object, **kwargs: object) -> None:
            if self.name.startswith("2026-10-07_1530_") and not rivals:
                # Another request began between this one looking for a name and making it
                rivals.append(self)
                real_mkdir(self, parents=True)
            real_mkdir(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "mkdir", racing)

        made = workspace.new_chat_directory("Race", now=NOW)

        assert rivals[0].name == "2026-10-07_1530_race"
        assert made.name == "2026-10-07_1530_race-2"
        assert made.is_dir() and rivals[0].is_dir()

    def test_requests_that_begin_at_once_each_get_a_directory_of_their_own(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        starting = threading.Barrier(16)
        made: list[Path] = []
        failures: list[BaseException] = []

        def begin() -> None:
            try:
                starting.wait()
                made.append(workspace.new_chat_directory("New chat", now=NOW))
            except BaseException as error:
                failures.append(error)

        threads = [threading.Thread(target=begin) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert failures == []
        assert len({path.name for path in made}) == 16
        assert all(path.is_dir() for path in made)

    def test_settings_are_kept_and_unknown_or_unreadable_ones_ignored(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        assert workspace.load_settings() == Settings()

        workspace.save_settings(Settings(model=TEST_MODEL, max_cost=None, code="docker"))
        assert workspace.load_settings() == Settings(model=TEST_MODEL, max_cost=None, code="docker")

        workspace.settings_path.write_text(json.dumps({"stream": False, "colour": "blue"}))
        assert workspace.load_settings() == Settings(stream=False)

        workspace.settings_path.write_text("{not json")
        assert workspace.load_settings() == Settings()

    def test_a_setting_of_the_wrong_kind_in_the_file_takes_the_default_and_the_rest_are_kept(
        self, tmp_path: Path
    ) -> None:
        workspace = Workspace(tmp_path)
        workspace.settings_path.write_text(
            json.dumps(
                {
                    "model": 123,
                    "max_cost": "lots",
                    "stream": "yes",
                    "code": ["x"],
                    "network": 5,
                    "forward_keys": "ABC",
                    "data_lake": 7,
                    "python": None,
                    "sandbox": {},
                }
            )
        )

        assert workspace.load_settings() == Settings()

        workspace.settings_path.write_text(json.dumps({"stream": "no", "code": "docker", "forward_keys": [1, "A"]}))

        assert workspace.load_settings() == Settings(code="docker")

    @pytest.mark.parametrize("budget", ["-4", "1e999", "NaN", "-Infinity", "true", '"2"'])
    def test_a_budget_that_is_not_an_amount_of_money_takes_the_default(self, tmp_path: Path, budget: str) -> None:
        workspace = Workspace(tmp_path)
        workspace.settings_path.write_text(f'{{"max_cost": {budget}}}')

        assert workspace.load_settings().max_cost == Settings().max_cost

    @pytest.mark.parametrize(("budget", "kept"), [("null", None), ("0", 0), ("3", 3), ("0.25", 0.25)])
    def test_no_budget_and_any_amount_of_money_are_kept(self, tmp_path: Path, budget: str, kept: float | None) -> None:
        workspace = Workspace(tmp_path)
        workspace.settings_path.write_text(f'{{"max_cost": {budget}}}')

        assert workspace.load_settings().max_cost == kept

    def test_a_model_that_is_empty_takes_the_default(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        workspace.settings_path.write_text(json.dumps({"model": "  "}))

        assert workspace.load_settings().model == DEFAULT_MODEL

    def test_every_setting_has_a_kind_its_values_are_checked_against(self) -> None:
        assert set(SETTING_KINDS) == {item.name for item in fields(Settings)}

    def test_the_data_lake_and_the_keys_code_may_read_are_kept_and_are_none_by_default(self, tmp_path: Path) -> None:
        workspace = Workspace(tmp_path)
        assert (Settings().data_lake, Settings().forward_keys) == ("", [])

        workspace.save_settings(Settings(data_lake="/my/lake", forward_keys=["GROQ_API_KEY"]))

        loaded = workspace.load_settings()
        assert (loaded.data_lake, loaded.forward_keys) == ("/my/lake", ["GROQ_API_KEY"])
        assert Settings().forward_keys is not Settings().forward_keys

    def test_the_data_lake_is_kept_beside_the_conversations_unless_the_settings_say_otherwise(
        self, tmp_path: Path
    ) -> None:
        workspace = Workspace(tmp_path)

        assert workspace.data_lake_dir == workspace.root / "data_lake"
        assert workspace.data_lake_dir.parent == workspace.chats_dir.parent


class TestWritingFiles:
    def test_a_file_is_written_whole_and_no_temporary_one_is_left(self, tmp_path: Path) -> None:
        path = tmp_path / "kept" / "file.json"

        write_atomically(path, b"one")
        write_atomically(path, b"two")

        assert path.read_bytes() == b"two"
        assert [item.name for item in path.parent.iterdir()] == ["file.json"]

    @pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="Root can write anywhere")
    def test_a_file_that_cannot_be_written_is_an_error_that_names_it_and_not_a_temporary_one(
        self, tmp_path: Path
    ) -> None:
        folder = tmp_path / "locked"
        folder.mkdir()
        folder.chmod(0o500)
        try:
            with pytest.raises(PermissionError) as caught:
                write_atomically(folder / "settings.json", b"{}")
        finally:
            folder.chmod(0o700)

        assert caught.value.filename == str(folder / "settings.json")
        assert caught.value.filename2 is None
        assert list(folder.iterdir()) == []

    def test_a_file_that_cannot_be_put_in_place_is_an_error_that_names_it_and_leaves_nothing_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "settings.json"

        def refuse(source: str, destination: Path) -> None:
            raise OSError(errno.EXDEV, "Invalid cross-device link", source, None, str(destination))

        monkeypatch.setattr(os, "replace", refuse)

        with pytest.raises(OSError, match="Invalid cross-device link") as caught:
            write_atomically(target, b"{}")

        assert (caught.value.filename, caught.value.filename2) == (str(target), None)
        assert list(tmp_path.iterdir()) == []


class TestLibrary:
    def test_the_default_model_comes_first_and_none_twice(self) -> None:
        models = library.models()

        assert models[0] == DEFAULT_MODEL
        assert len(set(models)) == len(models)
        assert TEST_MODEL in models

    def test_the_newest_families_are_listed_before_the_older_ones(self) -> None:
        models = library.models()

        assert models.index("gpt-6-astra") < models.index("gpt-5.5") < models.index("claude-opus-5-5")
        assert models.index("claude-opus-5-5") < models.index("gemini-4-argon") < models.index("gpt-4.1")

    def test_a_provider_is_ready_once_its_variables_are_set_and_no_value_is_read_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        statuses = {status.provider: status for status in library.provider_statuses()}

        assert statuses["OpenAI"].ready
        assert not statuses["Anthropic"].ready
        assert "sk-secret" not in repr(library.provider_statuses())
        assert library.missing_keys([TEST_MODEL, "claude-sonnet-4-5", "claude-opus-4-1"]) == ["ANTHROPIC_API_KEY"]
