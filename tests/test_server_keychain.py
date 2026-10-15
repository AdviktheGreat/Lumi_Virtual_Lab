"""Tests of keeping the keys a person gives the interface in the machine's keychain, so that they are there when the
server is started again."""

import json
import os
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_server_cli import RecordingServer

from virtual_lab.server import cli
from virtual_lab.server.app import create_app
from virtual_lab.server.keychain import MAX_ERROR_CHARS, SERVICE, Keychain, KeychainError, recall, said
from virtual_lab.server.library import SETTABLE_KEYS
from virtual_lab.server.mcp import service_keys

TOKEN = "the-token-of-the-person-who-started-it"
LOCAL = "http://localhost"
BEARER = {"Authorization": f"Bearer {TOKEN}"}
SECRET = "sk-the-secret-that-no-response-may-repeat"
OPENAI = "OPENAI_API_KEY"
GROQ = "GROQ_API_KEY"
SETTABLE = SETTABLE_KEYS


class FakeBackend:
    """Stands in for a backend of the keyring package, which keeps keys in a dictionary and can be made to fail."""

    def __init__(self, kept: dict[str, str] | None = None) -> None:
        self.kept = {(SERVICE, name): value for name, value in (kept or {}).items()}
        self.calls: list[tuple[str, str, str]] = []
        self.failures: dict[str, Exception] = {}
        self.hold: threading.Event | None = None

    def act(self, action: str, service: str, name: str) -> None:
        self.calls.append((action, service, name))
        if self.hold is not None:
            self.hold.wait(5)
        if action in self.failures:
            raise self.failures[action]

    def get_password(self, service: str, name: str) -> str | None:
        self.act("get", service, name)

        return self.kept.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        self.act("set", service, name)
        self.kept[(service, name)] = value

    def delete_password(self, service: str, name: str) -> None:
        self.act("delete", service, name)
        del self.kept[(service, name)]

    def names(self, action: str) -> list[str]:
        return [name for kind, _, name in self.calls if kind == action]

    def stored(self) -> dict[str, str]:
        return {name: value for (_, name), value in self.kept.items()}


def keychain_of(backend: FakeBackend, name: str = "Test Keychain", **options: Any) -> Keychain:
    return Keychain(backend, name, **options)


class TestKeepingKeys:
    def test_a_key_is_kept_under_the_service_and_the_name_of_its_variable_and_is_given_back(self) -> None:
        backend = FakeBackend()
        keychain = keychain_of(backend)

        keychain.write(OPENAI, SECRET)

        assert backend.kept == {(SERVICE, OPENAI): SECRET}
        assert keychain.read(OPENAI) == SECRET

    def test_a_key_that_is_not_kept_is_none_and_so_is_one_that_is_empty(self) -> None:
        keychain = keychain_of(FakeBackend({GROQ: ""}))

        assert keychain.read(OPENAI) is None
        assert keychain.read(GROQ) is None

    def test_a_key_is_forgotten_and_forgetting_what_is_not_kept_asks_nothing_of_the_keychain_to_delete(self) -> None:
        backend = FakeBackend({OPENAI: SECRET})
        keychain = keychain_of(backend)

        keychain.erase(OPENAI)
        keychain.erase(OPENAI)

        assert backend.kept == {}
        assert backend.names("delete") == [OPENAI]

    def test_the_service_is_the_one_asked_for(self) -> None:
        backend = FakeBackend()

        keychain_of(backend, service="another-lab").write(OPENAI, SECRET)

        assert backend.kept == {("another-lab", OPENAI): SECRET}

    @pytest.mark.parametrize(
        ("problem", "said_so"),
        [("There is no keychain here", "There is no keychain here"), (None, "There is no keychain to keep keys in")],
    )
    @pytest.mark.parametrize(
        "use",
        [
            lambda keychain: keychain.read(OPENAI),
            lambda keychain: keychain.write(OPENAI, SECRET),
            lambda keychain: keychain.erase(OPENAI),
        ],
    )
    def test_a_keychain_that_is_missing_says_why_it_cannot_keep_anything(
        self, use: Any, problem: str | None, said_so: str
    ) -> None:
        keychain = Keychain.missing(problem)

        assert keychain.available is False
        with pytest.raises(KeychainError, match=said_so):
            use(keychain)

    def test_a_keychain_that_is_there_is_available(self) -> None:
        assert keychain_of(FakeBackend()).available is True


class TestWhenTheKeychainFails:
    @pytest.mark.parametrize(
        ("use", "what"),
        [
            (lambda keychain: keychain.read(OPENAI), "read the key"),
            (lambda keychain: keychain.write(OPENAI, SECRET), "keep the key"),
            (lambda keychain: keychain.erase(OPENAI), "forget the key"),
        ],
    )
    def test_what_went_wrong_is_said_with_what_was_being_asked_and_no_key(self, use: Any, what: str) -> None:
        backend = FakeBackend({OPENAI: SECRET})
        action = {"read the key": "get", "keep the key": "set", "forget the key": "delete"}[what]
        backend.failures[action] = RuntimeError("locked")

        with pytest.raises(KeychainError) as raised:
            use(keychain_of(backend))

        assert str(raised.value) == f"The Test Keychain would not {what}: locked"

    def test_a_key_that_an_error_repeats_is_not_repeated(self) -> None:
        backend = FakeBackend()
        backend.failures["set"] = RuntimeError(f"cannot keep {SECRET}")

        with pytest.raises(KeychainError) as raised:
            keychain_of(backend).write(OPENAI, SECRET)

        assert SECRET not in str(raised.value)
        assert str(raised.value) == "The Test Keychain would not keep the key: cannot keep …"

    def test_an_error_is_on_one_line_and_is_not_long(self) -> None:
        text = said(RuntimeError("first\n  second\tthird " + "x" * 1000))

        assert "\n" not in text and "\t" not in text
        assert text.startswith("first second third x")
        assert len(text) == MAX_ERROR_CHARS

    def test_an_error_that_says_nothing_is_named(self) -> None:
        assert said(PermissionError()) == "PermissionError"

    def test_a_keychain_that_does_not_answer_is_given_up_on_and_said_to_wait_to_be_unlocked(self) -> None:
        backend = FakeBackend()
        backend.hold = threading.Event()
        keychain = keychain_of(backend, timeout=0.05)
        started = time.monotonic()

        with pytest.raises(KeychainError, match=r"The Test Keychain did not answer in 0\.05 seconds: .*unlocked"):
            keychain.read(OPENAI)

        assert time.monotonic() - started < 2
        backend.hold.set()

    def test_a_keychain_that_answers_late_but_in_time_is_waited_for(self) -> None:
        backend = FakeBackend({OPENAI: SECRET})
        backend.hold = threading.Event()
        threading.Timer(0.05, backend.hold.set).start()

        assert keychain_of(backend, timeout=3).read(OPENAI) == SECRET


class TestTheKeychainOfThisMachine:
    def test_none_is_found_while_a_test_runs_so_that_no_test_reaches_the_real_one(self) -> None:
        pytest.importorskip("keyring")

        found = Keychain.system()

        assert found.available is False
        assert found.problem == "This machine has no keychain that the keyring package can use"

    @pytest.mark.parametrize(
        ("module", "shown"),
        [
            ("keyring.backends.macOS", "macOS Keychain"),
            ("keyring.backends.Windows", "Windows Credential Manager"),
            ("keyring.backends.SecretService", "Secret Service"),
            ("keyring.backends.kwallet", "KWallet"),
            ("somewhere.else", "Keyring"),
        ],
    )
    def test_a_backend_is_called_what_a_person_knows_it_by(
        self, monkeypatch: pytest.MonkeyPatch, module: str, shown: str
    ) -> None:
        keyring = pytest.importorskip("keyring")
        backend = type("Keyring", (FakeBackend,), {"__module__": module})()
        monkeypatch.setattr(keyring, "get_keyring", lambda: backend)

        found = Keychain.system()

        assert found.available is True
        assert found.name == shown
        assert found.backend is backend
        assert found.service == SERVICE

    @pytest.mark.parametrize("module", ["fail", "null"])
    def test_a_backend_that_keeps_nothing_is_no_keychain(self, monkeypatch: pytest.MonkeyPatch, module: str) -> None:
        keyring = pytest.importorskip("keyring")
        from keyring.backends import fail, null

        monkeypatch.setattr(keyring, "get_keyring", lambda: {"fail": fail, "null": null}[module].Keyring())

        found = Keychain.system()

        assert found.available is False
        assert found.problem == "This machine has no keychain that the keyring package can use"

    def test_a_keyring_package_that_is_not_installed_is_said_to_be_the_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "keyring", None)

        found = Keychain.system()

        assert found.available is False
        assert found.problem is not None and "keyring package is not installed" in found.problem
        assert 'pip install "virtual-lab[server]"' in found.problem

    def test_a_keyring_that_cannot_be_looked_into_is_no_keychain_and_says_why(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keyring = pytest.importorskip("keyring")

        def broken() -> None:
            raise RuntimeError("no session bus")

        monkeypatch.setattr(keyring, "get_keyring", broken)

        found = Keychain.system()

        assert found.available is False
        assert found.problem == "The keychain would not be looked into: no session bus"


class TestRecalling:
    def test_the_keys_kept_are_given_to_the_environment_unless_it_has_them(self) -> None:
        backend = FakeBackend({OPENAI: "kept-openai", GROQ: "kept-groq"})
        environment = {GROQ: "from-the-shell"}

        recalled, problem = recall(keychain_of(backend), SETTABLE, environment)

        assert (recalled, problem) == ({OPENAI}, None)
        assert environment == {GROQ: "from-the-shell", OPENAI: "kept-openai"}
        # What the environment has is not even asked for
        assert GROQ not in backend.names("get")

    def test_only_the_keys_that_may_be_kept_are_read(self) -> None:
        backend = FakeBackend({OPENAI: "kept-openai", "PATH": "/elsewhere"})
        environment: dict[str, str] = {}

        recall(keychain_of(backend), SETTABLE, environment)

        assert "PATH" not in environment
        assert sorted(backend.names("get")) == sorted(SETTABLE)

    def test_an_empty_variable_in_the_environment_is_not_a_key_it_has(self) -> None:
        environment = {OPENAI: ""}

        recall(keychain_of(FakeBackend({OPENAI: "kept"})), SETTABLE, environment)

        assert environment == {OPENAI: "kept"}

    def test_a_keychain_that_will_not_be_read_ends_the_reading_and_is_said_to_have_not_been(self) -> None:
        backend = FakeBackend({"ANTHROPIC_API_KEY": "kept-anthropic"})
        backend.failures["get"] = RuntimeError("locked")
        environment: dict[str, str] = {}

        recalled, problem = recall(keychain_of(backend), SETTABLE, environment)

        assert recalled == set() and environment == {}
        assert problem == "Keys kept earlier were not read. The Test Keychain would not read the key: locked"
        # The first it would not give was the last it was asked for
        assert backend.names("get") == [OPENAI]

    def test_what_was_read_before_it_failed_is_kept(self) -> None:
        backend = FakeBackend({OPENAI: "kept-openai"})
        environment: dict[str, str] = {}
        original = backend.get_password

        def fail_second(service: str, name: str) -> str | None:
            if name == "ANTHROPIC_API_KEY":
                raise RuntimeError("locked")

            return original(service, name)

        backend.get_password = fail_second  # type: ignore[method-assign]

        recalled, problem = recall(keychain_of(backend), SETTABLE, environment)

        assert recalled == {OPENAI} and environment == {OPENAI: "kept-openai"}
        assert problem is not None and "locked" in problem

    def test_a_keychain_that_is_missing_says_why_and_reads_nothing(self) -> None:
        environment: dict[str, str] = {}

        assert recall(Keychain.missing("none here"), SETTABLE, environment) == (set(), "none here")
        assert recall(Keychain.missing(), SETTABLE, environment) == (set(), None)
        assert environment == {}

    def test_the_environment_of_the_process_is_the_one_given_to_unless_another_is(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(GROQ, "x")
        monkeypatch.delenv(GROQ)

        recall(keychain_of(FakeBackend({GROQ: "kept-groq"})), (GROQ,))

        assert os.environ[GROQ] == "kept-groq"


@pytest.fixture
def no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Has the process begin with none of the keys the interface may set, and puts back what it had."""
    for name in (*SETTABLE, *service_keys()):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)


def opened(tmp_path: Path, keychain: Keychain | None) -> Iterator[TestClient]:
    app = create_app(tmp_path / "workspace", token=TOKEN, check_keys=False, keychain=keychain)
    with TestClient(app, base_url=LOCAL, headers=BEARER) as client:
        yield client


@pytest.fixture
def recording(monkeypatch: pytest.MonkeyPatch) -> type[RecordingServer]:
    RecordingServer.started = []
    monkeypatch.setattr(cli.uvicorn, "Server", RecordingServer)

    return RecordingServer


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def client(tmp_path: Path, backend: FakeBackend, no_keys: None) -> Iterator[TestClient]:
    yield from opened(tmp_path, keychain_of(backend))


def keys(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/keys")
    assert response.status_code == 200

    return response.json()


class TestTheKeysTheServerIsStartedWith:
    def test_the_keys_kept_are_there_when_the_server_is_started_and_are_said_to_be_from_the_keychain(
        self, tmp_path: Path, no_keys: None
    ) -> None:
        backend = FakeBackend({GROQ: "kept-groq"})

        for client in opened(tmp_path, keychain_of(backend)):
            shown = keys(client)

        assert os.environ[GROQ] == "kept-groq"
        assert shown["sources"] == {GROQ: "keychain"}
        assert {item["provider"]: item["ready"] for item in shown["providers"]}["Groq"] is True
        assert shown["keychain"] == {"available": True, "name": "Test Keychain", "problem": None}

    def test_a_key_in_the_environment_is_not_replaced_by_the_one_kept_and_is_said_to_be_from_it(
        self, tmp_path: Path, no_keys: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(GROQ, "from-the-shell")

        for client in opened(tmp_path, keychain_of(FakeBackend({GROQ: "kept-groq"}))):
            shown = keys(client)

        assert os.environ[GROQ] == "from-the-shell"
        assert shown["sources"] == {GROQ: "environment"}

    def test_a_key_of_a_service_an_mcp_preset_reaches_is_kept_the_same_way(self, tmp_path: Path, no_keys: None) -> None:
        name = service_keys()[0]

        for client in opened(tmp_path, keychain_of(FakeBackend({name: "kept-service-key"}))):
            shown = keys(client)

        assert os.environ[name] == "kept-service-key"
        assert shown["sources"] == {name: "keychain"}

    def test_a_keychain_that_will_not_be_read_is_said_so_and_is_still_there_to_keep_keys_in(
        self, tmp_path: Path, no_keys: None
    ) -> None:
        backend = FakeBackend({GROQ: "kept-groq"})
        backend.failures["get"] = RuntimeError("locked")

        for client in opened(tmp_path, keychain_of(backend)):
            shown = keys(client)

        assert GROQ not in os.environ
        assert shown["sources"] == {}
        assert shown["keychain"]["available"] is True
        assert shown["keychain"]["problem"] == (
            "Keys kept earlier were not read. The Test Keychain would not read the key: locked"
        )

    def test_without_a_keychain_there_is_nothing_to_say_of_one(self, tmp_path: Path, no_keys: None) -> None:
        for client in opened(tmp_path, None):
            shown = keys(client)

        assert shown["keychain"] == {"available": False, "name": None, "problem": None}
        assert shown["sources"] == {}
        assert shown["problem"] is None

    def test_a_keychain_that_is_not_there_says_why(self, tmp_path: Path, no_keys: None) -> None:
        for client in opened(tmp_path, Keychain.missing("This machine has none")):
            shown = keys(client)

        assert shown["keychain"] == {"available": False, "name": None, "problem": "This machine has none"}

    def test_keys_of_the_environment_the_server_has_are_said_to_be_from_it(
        self, tmp_path: Path, no_keys: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(OPENAI, "from-the-shell")

        for client in opened(tmp_path, None):
            shown = keys(client)

        assert shown["sources"] == {OPENAI: "environment"}
        assert "from-the-shell" not in json.dumps(shown)


class TestGivingAKey:
    def test_a_key_is_kept_in_the_keychain_unless_it_is_said_not_to_be_and_is_not_told_back(
        self, client: TestClient, backend: FakeBackend
    ) -> None:
        response = client.put(f"/api/keys/{OPENAI}", json={"value": f"  {SECRET} \n"})

        assert response.status_code == 200
        assert backend.stored() == {OPENAI: SECRET}
        assert os.environ[OPENAI] == SECRET
        shown = response.json()
        assert shown["sources"] == {OPENAI: "keychain"}
        assert shown["problem"] is None
        assert SECRET not in response.text
        assert SECRET not in client.get("/api/keys").text

    def test_a_key_is_kept_in_the_keychain_when_it_is_said_to_be(
        self, client: TestClient, backend: FakeBackend
    ) -> None:
        response = client.put(f"/api/keys/{GROQ}", json={"value": SECRET, "remember": True})

        assert backend.stored() == {GROQ: SECRET}
        assert response.json()["sources"] == {GROQ: "keychain"}

    def test_a_key_that_is_not_to_be_kept_is_set_for_the_session_alone(
        self, client: TestClient, backend: FakeBackend
    ) -> None:
        response = client.put(f"/api/keys/{GROQ}", json={"value": SECRET, "remember": False})

        assert response.status_code == 200
        assert os.environ[GROQ] == SECRET
        assert backend.stored() == {}
        assert response.json()["sources"] == {GROQ: "session"}
        assert response.json()["problem"] is None

    def test_a_key_that_is_not_to_be_kept_takes_the_one_kept_earlier_away_so_that_it_does_not_come_back(
        self, client: TestClient, backend: FakeBackend
    ) -> None:
        client.put(f"/api/keys/{GROQ}", json={"value": "the-first"})
        assert backend.stored() == {GROQ: "the-first"}

        response = client.put(f"/api/keys/{GROQ}", json={"value": SECRET, "remember": False})

        assert backend.stored() == {}
        assert os.environ[GROQ] == SECRET
        assert response.json()["sources"] == {GROQ: "session"}

    def test_a_key_that_replaces_one_kept_is_kept_in_its_place(self, client: TestClient, backend: FakeBackend) -> None:
        client.put(f"/api/keys/{GROQ}", json={"value": "the-first"})

        client.put(f"/api/keys/{GROQ}", json={"value": SECRET})

        assert backend.stored() == {GROQ: SECRET}

    def test_a_key_the_keychain_will_not_keep_is_set_until_the_server_stops_and_the_reason_is_said_without_it(
        self, client: TestClient, backend: FakeBackend
    ) -> None:
        backend.failures["set"] = RuntimeError(f"User canceled the request for {SECRET}")

        response = client.put(f"/api/keys/{OPENAI}", json={"value": SECRET})

        assert response.status_code == 200
        assert os.environ[OPENAI] == SECRET
        shown = response.json()
        assert shown["sources"] == {OPENAI: "session"}
        assert shown["problem"] == (
            "The key is set until the server stops. "
            "The Test Keychain would not keep the key: User canceled the request for …"
        )
        assert SECRET not in response.text

    def test_a_key_the_keychain_will_not_forget_is_set_and_the_one_kept_is_said_to_come_back(
        self, client: TestClient, backend: FakeBackend
    ) -> None:
        client.put(f"/api/keys/{GROQ}", json={"value": "the-first"})
        backend.failures["delete"] = RuntimeError("denied")

        response = client.put(f"/api/keys/{GROQ}", json={"value": SECRET, "remember": False})

        assert os.environ[GROQ] == SECRET
        assert response.json()["sources"] == {GROQ: "session"}
        assert response.json()["problem"] == (
            "The key is set until the server stops. The Test Keychain would not forget the key: denied"
        )
        assert backend.stored() == {GROQ: "the-first"}

    def test_a_key_that_is_to_be_kept_where_there_is_no_keychain_is_set_and_the_reason_is_said(
        self, tmp_path: Path, no_keys: None
    ) -> None:
        for client in opened(tmp_path, Keychain.missing("This machine has no keychain")):
            asked = client.put(f"/api/keys/{GROQ}", json={"value": SECRET, "remember": True})
            unasked = client.put(f"/api/keys/{OPENAI}", json={"value": SECRET})

        assert os.environ[GROQ] == os.environ[OPENAI] == SECRET
        assert asked.json()["problem"] == "The key is set until the server stops. This machine has no keychain"
        assert asked.json()["sources"][GROQ] == "session"
        assert unasked.json()["problem"] is None
        assert unasked.json()["sources"][OPENAI] == "session"

    def test_a_key_is_set_for_the_session_where_the_server_has_no_keychain_given(
        self, tmp_path: Path, no_keys: None
    ) -> None:
        for client in opened(tmp_path, None):
            response = client.put(f"/api/keys/{GROQ}", json={"value": SECRET})

        assert response.json()["sources"] == {GROQ: "session"}
        assert response.json()["problem"] is None

    def test_a_key_the_server_was_started_with_is_replaced_by_the_one_given_and_kept(
        self, tmp_path: Path, no_keys: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(GROQ, "from-the-shell")
        backend = FakeBackend()

        for client in opened(tmp_path, keychain_of(backend)):
            response = client.put(f"/api/keys/{GROQ}", json={"value": SECRET})

        assert os.environ[GROQ] == SECRET
        assert response.json()["sources"] == {GROQ: "keychain"}
        assert backend.stored() == {GROQ: SECRET}

    def test_a_key_of_a_service_an_mcp_preset_reaches_is_kept_too(
        self, client: TestClient, backend: FakeBackend
    ) -> None:
        name = service_keys()[0]

        client.put(f"/api/keys/{name}", json={"value": SECRET})

        assert backend.stored() == {name: SECRET}

    def test_a_key_that_is_refused_is_not_kept_or_asked_of_the_keychain(
        self, client: TestClient, backend: FakeBackend
    ) -> None:
        for name, value in ((GROQ, "two\nlines"), (GROQ, "  "), ("PATH", SECRET)):
            assert client.put(f"/api/keys/{name}", json={"value": value}).status_code == 422
        assert client.put(f"/api/keys/{GROQ}", json={"value": SECRET, "remember": "sometimes"}).status_code == 422

        assert backend.calls == [("get", SERVICE, name) for name in (*SETTABLE, *service_keys())]
        assert backend.stored() == {}

    def test_a_key_is_kept_until_the_server_is_started_again_and_then_is_there(
        self, tmp_path: Path, no_keys: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = FakeBackend()
        for client in opened(tmp_path, keychain_of(backend)):
            client.put(f"/api/keys/{GROQ}", json={"value": SECRET})
            client.put(f"/api/keys/{OPENAI}", json={"value": "not-kept", "remember": False})
        # What a new process has to begin with: nothing it was given before
        monkeypatch.delenv(GROQ)
        monkeypatch.delenv(OPENAI)

        for again in opened(tmp_path, keychain_of(backend)):
            shown = keys(again)

        assert os.environ[GROQ] == SECRET
        assert OPENAI not in os.environ
        assert shown["sources"] == {GROQ: "keychain"}


class TestTakingAKeyAway:
    def test_a_key_is_taken_away_from_the_environment_and_the_keychain(
        self, client: TestClient, backend: FakeBackend
    ) -> None:
        client.put(f"/api/keys/{GROQ}", json={"value": SECRET})
        client.put(f"/api/keys/{OPENAI}", json={"value": "stays"})

        response = client.delete(f"/api/keys/{GROQ}")

        assert response.status_code == 200
        assert GROQ not in os.environ
        assert backend.stored() == {OPENAI: "stays"}
        shown = response.json()
        assert shown["sources"] == {OPENAI: "keychain"}
        assert shown["problem"] is None

    def test_a_key_that_was_not_kept_is_taken_away_and_nothing_is_deleted_from_the_keychain(
        self, client: TestClient, backend: FakeBackend
    ) -> None:
        client.put(f"/api/keys/{GROQ}", json={"value": SECRET, "remember": False})

        response = client.delete(f"/api/keys/{GROQ}")

        assert response.status_code == 200 and GROQ not in os.environ
        assert backend.names("delete") == []

    def test_a_key_the_server_was_started_with_is_taken_away_and_is_back_when_it_is_started_again(
        self, tmp_path: Path, no_keys: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(GROQ, "from-the-shell")
        backend = FakeBackend({GROQ: "kept-groq"})

        for client in opened(tmp_path, keychain_of(backend)):
            response = client.delete(f"/api/keys/{GROQ}")

        assert GROQ not in os.environ
        assert response.json()["sources"] == {}
        # What was kept is forgotten too, since a key that is taken away is not to come back from the keychain
        assert backend.stored() == {}

    def test_a_key_the_keychain_will_not_forget_is_taken_away_for_now_and_may_come_back(
        self, client: TestClient, backend: FakeBackend
    ) -> None:
        client.put(f"/api/keys/{GROQ}", json={"value": SECRET})
        backend.failures["delete"] = RuntimeError("denied")

        response = client.delete(f"/api/keys/{GROQ}")

        assert response.status_code == 200
        assert GROQ not in os.environ
        assert response.json()["sources"] == {}
        assert response.json()["problem"] == (
            "The key is taken away until the server is started again, and may be back then. "
            "The Test Keychain would not forget the key: denied"
        )
        assert backend.stored() == {GROQ: SECRET}

    def test_a_key_is_taken_away_where_there_is_no_keychain_without_a_word_of_one(
        self, tmp_path: Path, no_keys: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(GROQ, "to-remove")

        for client in opened(tmp_path, Keychain.missing("none")):
            response = client.delete(f"/api/keys/{GROQ}")

        assert GROQ not in os.environ
        assert response.json()["problem"] is None

    def test_a_name_that_is_not_a_key_is_refused(self, client: TestClient, backend: FakeBackend) -> None:
        before = list(backend.calls)

        assert client.delete("/api/keys/PATH").status_code == 422
        assert backend.calls == before


class TestStartingTheServer:
    def serving(self, tmp_path: Path, recording: type[RecordingServer], **options: Any) -> TestClient:
        cli.serve(tmp_path / "ws", token=TOKEN, open_browser=False, check_keys=False, **options)
        started = recording.started[-1]
        assert started.sockets is not None
        started.sockets[0].close()

        return TestClient(started.config.app, base_url=LOCAL, headers=BEARER)

    def test_the_keychain_that_is_given_is_the_one_the_keys_are_kept_in(
        self, tmp_path: Path, recording: type[RecordingServer], no_keys: None
    ) -> None:
        backend = FakeBackend()

        with self.serving(tmp_path, recording, keychain=keychain_of(backend, "Given")) as client:
            shown = client.put(f"/api/keys/{GROQ}", json={"value": SECRET}).json()

        assert shown["keychain"]["name"] == "Given"
        assert backend.stored() == {GROQ: SECRET}

    def test_this_machines_own_keychain_is_used_unless_it_is_said_not_to_be(
        self, tmp_path: Path, recording: type[RecordingServer], monkeypatch: pytest.MonkeyPatch, no_keys: None
    ) -> None:
        backend = FakeBackend({GROQ: "kept-groq"})
        asked: list[bool] = []

        def system() -> Keychain:
            asked.append(True)

            return keychain_of(backend, "This Machine's")

        monkeypatch.setattr(cli.Keychain, "system", staticmethod(system))

        with self.serving(tmp_path, recording) as client:
            shown = keys(client)
        assert asked == [True]
        assert shown["keychain"]["name"] == "This Machine's"
        assert os.environ[GROQ] == "kept-groq"

        monkeypatch.delenv(GROQ)
        with self.serving(tmp_path, recording, keychain=False) as client:
            shown = keys(client)
        assert asked == [True]
        assert shown["keychain"] == {"available": False, "name": None, "problem": None}
        assert GROQ not in os.environ

    def test_the_options_of_the_command_line_say_whether_the_keychain_is_used(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        given: list[dict[str, Any]] = []
        monkeypatch.setattr(cli, "serve", lambda **kwargs: given.append(kwargs))

        cli.main([])
        cli.main(["--no-keychain"])

        assert [options["keychain"] for options in given] == [True, False]
