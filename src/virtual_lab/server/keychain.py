"""The operating system's keychain, where the keys a person gives the interface are kept, so that they are there again
when the server is started again."""

import os
import threading
from collections.abc import Callable, Collection, MutableMapping
from typing import Any

# What a key is kept under, with the name of its environment variable as the account
SERVICE = "virtual-lab"

# Seconds the keychain has to answer. A locked one can wait for the person to unlock it, which a server starting up, or
# a page that has asked to save a key, must not wait for
TIMEOUT_SECONDS = 5.0

# The longest an error from the keychain is repeated, which a person reads beside the key
MAX_ERROR_CHARS = 200

# What the backends of the keyring package are called, by the module they are in
BACKEND_NAMES = {
    "keyring.backends.macOS": "macOS Keychain",
    "keyring.backends.Windows": "Windows Credential Manager",
    "keyring.backends.SecretService": "Secret Service",
    "keyring.backends.kwallet": "KWallet",
}


class KeychainError(Exception):
    """The keychain would not keep, give, or forget a key. The message is for a person to read, and has no key in it."""


class Keychain:
    """Keeps keys in a store of the operating system, by the name of the variable each is given to code in.

    :param backend: What keeps them, which has the get_password, set_password, and delete_password of the keyring
        package's backends, or None for no keychain.
    :param name: What a person calls it, as in "the macOS Keychain".
    :param service: What the keys are kept under.
    :param timeout: Seconds to wait for each answer.
    :param problem: Why there is no keychain, if there is none and a person should be told.
    """

    def __init__(
        self,
        backend: Any,
        name: str | None = None,
        service: str = SERVICE,
        timeout: float = TIMEOUT_SECONDS,
        problem: str | None = None,
    ) -> None:
        self.backend = backend
        self.name = name or "keychain"
        self.service = service
        self.timeout = timeout
        self.problem = problem

    @classmethod
    def missing(cls, problem: str | None = None) -> "Keychain":
        """No keychain: keys are kept until the server stops, and no further."""
        return cls(None, problem=problem)

    @classmethod
    def system(cls) -> "Keychain":
        """The keychain of this machine, as the keyring package finds it, or none, with the reason, where there is
        none to use."""
        try:
            import keyring
            from keyring.backends import fail, null
        except ImportError:
            return cls.missing('The keyring package is not installed: pip install "virtual-lab[server]"')
        try:
            found = cls(None).call(keyring.get_keyring, "be looked into")
        except KeychainError as error:
            return cls.missing(str(error))
        if isinstance(found, fail.Keyring | null.Keyring):
            return cls.missing("This machine has no keychain that the keyring package can use")
        module = type(found).__module__
        name = next((shown for prefix, shown in BACKEND_NAMES.items() if module.startswith(prefix)), None)

        return cls(found, name or type(found).__name__)

    @property
    def available(self) -> bool:
        return self.backend is not None

    def read(self, key: str) -> str | None:
        """The key kept as this variable, or None if none is.

        :raises KeychainError: If the keychain would not give it.
        """
        value = self.call(self.require().get_password, "read the key", self.service, key)

        return value if isinstance(value, str) and value else None

    def write(self, key: str, value: str) -> None:
        """Keeps a key as this variable, in place of one that was.

        :raises KeychainError: If the keychain would not keep it.
        """
        self.call(self.require().set_password, "keep the key", self.service, key, value, secret=value)

    def erase(self, key: str) -> None:
        """Forgets the key kept as this variable, if one is.

        :raises KeychainError: If the keychain would not forget it.
        """
        backend = self.require()
        if self.call(backend.get_password, "read the key", self.service, key) is None:
            return
        self.call(backend.delete_password, "forget the key", self.service, key)

    def require(self) -> Any:
        if self.backend is None:
            raise KeychainError(self.problem or "There is no keychain to keep keys in")

        return self.backend

    def call(self, action: Callable[..., Any], what: str, *arguments: Any, secret: str | None = None) -> Any:
        """Calls the keychain, giving up if it does not answer, and saying what went wrong without the key.

        :param what: What was asked of it, as the message completes "The keychain would not".
        :param secret: A value the message must not repeat.
        """
        outcome: dict[str, Any] = {}

        def run() -> None:
            try:
                outcome["value"] = action(*arguments)
            except Exception as error:  # noqa: BLE001
                outcome["error"] = error

        worker = threading.Thread(target=run, name="keychain", daemon=True)
        worker.start()
        worker.join(self.timeout)
        if worker.is_alive():
            raise KeychainError(
                f"The {self.name} did not answer in {self.timeout:g} seconds: it may be waiting to be unlocked"
            )
        if "error" in outcome:
            raise KeychainError(f"The {self.name} would not {what}: {said(outcome['error'], secret)}")

        return outcome.get("value")


def said(error: Exception, secret: str | None = None) -> str:
    """What an error says, on one line, without a key that it repeats."""
    text = " ".join(str(error).split()) or type(error).__name__
    if secret:
        text = text.replace(secret, "…")

    return text[:MAX_ERROR_CHARS]


def recall(
    keychain: Keychain, names: Collection[str], environment: MutableMapping[str, str] = os.environ
) -> tuple[set[str], str | None]:
    """Gives the environment the keys the keychain keeps, except for those it has already, which are the person's to
    have said another way.

    The first the keychain will not give ends it: what is wrong with one is wrong with the rest, and each would wait.

    :param names: The variables a key may be kept as.
    :return: The variables that were set from the keychain, and why it was not read, if it was not.
    """
    recalled: set[str] = set()
    if not keychain.available:
        return recalled, keychain.problem
    for name in names:
        if environment.get(name):
            continue
        try:
            value = keychain.read(name)
        except KeychainError as error:
            return recalled, f"Keys kept earlier were not read. {error}"
        if value is not None:
            environment[name] = value
            recalled.add(name)

    return recalled, None
