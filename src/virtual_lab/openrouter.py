"""OpenRouter's models: which there are for a chat, and what each costs.

One OpenRouter key reaches hundreds of models from many providers. They are named here
openrouter/<author>/<model>, as openrouter/anthropic/claude-sonnet-4.5, so that no other source takes them
(see virtual_lab.llm.detect_source). OpenRouter publishes the list, with prices, without a key. Prices change
and models come and go, so they are read from there, kept for a day, and given to virtual_lab.utils, which a
spending limit needs to work out what a conversation has cost.
"""

import json
import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from virtual_lab.llm import OPENROUTER_PREFIX
from virtual_lab.utils import register_prices, write_atomically

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# How long the list is used before it is read again, and how long to wait after a failure to read it before trying again
MAX_AGE_SECONDS = 24 * 60 * 60
RETRY_AFTER_SECONDS = 5 * 60
FETCH_TIMEOUT_SECONDS = 10

# What the file a list is kept in says of how it was written, so that a list kept before it said what the cache costs is
# read again at once, rather than a day later
SAVED_FORMAT = 2

# What a chat is for: the lead calls tools, and replies are text. A model of a batch is answered later, not as asked
BATCH_SUFFIX = ":batch"


@dataclass(frozen=True)
class OpenRouterModel:
    """A model OpenRouter serves.

    :param id: Its name here: openrouter/<author>/<model>, or openrouter/<name> for one of OpenRouter's routers.
    :param name: What OpenRouter calls it, for people.
    :param context_length: How many tokens it reads and writes in all, if said.
    :param input_price: USD per input token, or None where it depends on what is chosen for the request, as a
        router's does.
    :param output_price: USD per output token, as for input_price.
    :param cache_read_price: USD per input token that it reads from its cache, which is less than input_price, or None
        where it does not cache or does not say.
    :param cache_write_price: USD per input token that it writes to its cache, which some models charge more for than
        for input, or None where it does not say.
    """

    id: str
    name: str
    context_length: int | None
    input_price: float | None
    output_price: float | None
    cache_read_price: float | None = None
    cache_write_price: float | None = None

    @property
    def priced(self) -> bool:
        return self.input_price is not None and self.output_price is not None

    def to_dict(self) -> dict[str, Any]:
        """As the interface is told of it, with prices per million tokens, which is how they are quoted."""
        return {
            "id": self.id,
            "name": self.name,
            "context_length": self.context_length,
            "input_per_million": None if self.input_price is None else self.input_price * 10**6,
            "output_per_million": None if self.output_price is None else self.output_price * 10**6,
        }

    def to_saved(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "context_length": self.context_length,
            "input_price": self.input_price,
            "output_price": self.output_price,
            "cache_read_price": self.cache_read_price,
            "cache_write_price": self.cache_write_price,
        }


def model_id(listed: str) -> str:
    """A model's name here, from the name OpenRouter lists it by."""
    return listed if listed.startswith(OPENROUTER_PREFIX) else f"{OPENROUTER_PREFIX}{listed}"


def price_of(value: Any) -> float | None:
    """USD per token from what OpenRouter says, which is a string, or None if it is not a price: a router says -1."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None

    return price if math.isfinite(price) and price >= 0 else None


def count_of(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def models_from(data: Any) -> list[OpenRouterModel]:
    """The models of what OpenRouter lists that a chat can use, those of its routers first, then newest first.

    :raises ValueError: If it is not a list of models.
    """
    listed = data.get("data") if isinstance(data, Mapping) else None
    if not isinstance(listed, list):
        raise ValueError("OpenRouter's list of models is not in the shape it has had")

    found: list[OpenRouterModel] = []
    for item in listed:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str) or not item["id"]:
            continue
        name = item["id"]
        parameters = item.get("supported_parameters")
        architecture = item.get("architecture")
        outputs = architecture.get("output_modalities") if isinstance(architecture, Mapping) else None
        router = name.startswith(OPENROUTER_PREFIX)
        # A router may send an image back as well, which it is the router's business to do or not
        if (
            name.endswith(BATCH_SUFFIX)
            or not isinstance(parameters, list)
            or "tools" not in parameters
            or not isinstance(outputs, list)
            or "text" not in outputs
            or (outputs != ["text"] and not router)
        ):
            continue
        pricing = item.get("pricing")
        pricing = pricing if isinstance(pricing, Mapping) else {}
        label = item.get("name")
        found.append(
            OpenRouterModel(
                id=model_id(name),
                name=label if isinstance(label, str) and label else name,
                context_length=count_of(item.get("context_length")),
                input_price=price_of(pricing.get("prompt")),
                output_price=price_of(pricing.get("completion")),
                cache_read_price=price_of(pricing.get("input_cache_read")),
                cache_write_price=price_of(pricing.get("input_cache_write")),
            )
        )

    return sorted(found, key=lambda model: "/" in model.id.removeprefix(OPENROUTER_PREFIX))


def fetch_models(url: str = OPENROUTER_MODELS_URL, timeout: float = FETCH_TIMEOUT_SECONDS) -> list[OpenRouterModel]:
    """Reads the models OpenRouter serves, which it lists for anyone.

    :raises requests.RequestException: If OpenRouter cannot be reached or does not answer well.
    :raises ValueError: If what it sends is not a list of models.
    """
    response = requests.get(url, timeout=timeout, headers={"Accept": "application/json"})
    response.raise_for_status()

    return models_from(response.json())


def prices_of(models: list[OpenRouterModel]) -> dict[str, tuple[float, float]]:
    return {
        model.id: (model.input_price, model.output_price)
        for model in models
        if model.input_price is not None and model.output_price is not None
    }


def cache_prices_of(models: list[OpenRouterModel]) -> dict[str, tuple[float | None, float | None]]:
    """What the models that prices_of gives charge for their cache, for those that say."""
    return {
        model.id: (model.cache_read_price, model.cache_write_price)
        for model in models
        if model.priced and (model.cache_read_price is not None or model.cache_write_price is not None)
    }


class Catalog:
    """The models OpenRouter serves, read when they are first wanted and again when they are a day old.

    A list read before is kept in a file, so that it is there when the server is started again, with no connection, and
    what the models cost is known from the start. When OpenRouter cannot be reached, the list there is, however old, is
    what is used, and it is tried for again a few minutes later.

    :param path: The file the list is kept in, or None to keep it only while this runs.
    :param fetch: What reads the list, which is for tests. By default it is fetch_models.
    :param max_age: How many seconds a list is used before it is read again.
    """

    def __init__(
        self,
        path: Path | None = None,
        fetch: Callable[[], list[OpenRouterModel]] | None = None,
        max_age: float = MAX_AGE_SECONDS,
    ) -> None:
        self.path = path
        self._fetch = fetch
        self._max_age = max_age
        self._lock = threading.Lock()
        self._models: list[OpenRouterModel] = []
        self._read_at: float | None = None
        self._failed_at: float | None = None
        self._problem: str | None = None
        self._outdated = False
        self._load()

    @property
    def known(self) -> bool:
        """Whether there is a list, however old, so that the prices of its models are known."""
        return self._read_at is not None

    def listing(self) -> dict[str, Any]:
        """The models, and what went wrong in reading them if they are not as new as they should be."""
        with self._lock:
            self._refresh()

            return {"models": [model.to_dict() for model in self._models], "problem": self._problem}

    def ensure_prices(self) -> None:
        """Makes sure the prices of its models are known, which reads them if they never were."""
        if not self.known or self._outdated:
            with self._lock:
                self._refresh()

    def _refresh(self) -> None:
        now = time.time()
        if self._read_at is not None and not self._outdated and now - self._read_at < self._max_age:
            return
        if self._failed_at is not None and now - self._failed_at < RETRY_AFTER_SECONDS:
            return
        try:
            models = (self._fetch or fetch_models)()
        except (requests.RequestException, ValueError) as error:
            self._failed_at = now
            self._problem = f"OpenRouter's list of models could not be read, so it may be out of date. ({error})"
            return
        self._failed_at = None
        self._problem = None
        self._outdated = False
        self._use(models, now)
        self._save()

    def _use(self, models: list[OpenRouterModel], read_at: float) -> None:
        self._models = models
        self._read_at = read_at
        register_prices(prices_of(models), cache_prices_of(models))

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            # Not later than now, which a clock set back would otherwise keep from ever reading it again
            read_at = min(float(saved["read_at"]), time.time())
            models = [
                OpenRouterModel(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    context_length=count_of(item.get("context_length")),
                    input_price=price_of(item.get("input_price")),
                    output_price=price_of(item.get("output_price")),
                    cache_read_price=price_of(item.get("cache_read_price")),
                    cache_write_price=price_of(item.get("cache_write_price")),
                )
                for item in saved["models"]
            ]
            outdated = saved.get("format") != SAVED_FORMAT
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # A list that cannot be read is read again, from OpenRouter
            return
        self._outdated = outdated
        self._use(models, read_at)

    def _save(self) -> None:
        if self.path is None:
            return
        saved = {
            "format": SAVED_FORMAT,
            "read_at": self._read_at,
            "models": [model.to_saved() for model in self._models],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_atomically(self.path, json.dumps(saved).encode("utf-8"))
        except OSError:
            # Kept in memory all the same, and read again when the server is started again
            pass
