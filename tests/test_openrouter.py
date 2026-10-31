"""Tests of the models OpenRouter serves: which a chat can use, what they cost, and how the list is kept."""

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from virtual_lab import llm, utils
from virtual_lab.openrouter import (
    SAVED_FORMAT,
    Catalog,
    OpenRouterModel,
    cache_prices_of,
    fetch_models,
    model_id,
    models_from,
    price_of,
)
from virtual_lab.utils import CostUnknownError, compute_token_cost, input_cost, register_prices


@pytest.fixture(autouse=True)
def no_prices_left_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utils, "REGISTERED_PRICES", {})
    monkeypatch.setattr(utils, "REGISTERED_CACHE_PRICES", {})
    monkeypatch.setattr(llm, "REGISTERED_IMAGE_MODELS", set())


def listed(
    name: str,
    prompt: str = "0.000002",
    completion: str = "0.00001",
    parameters: tuple[str, ...] = ("tools", "temperature"),
    outputs: tuple[str, ...] = ("text",),
    cache_read: str | None = None,
    cache_write: str | None = None,
    inputs: tuple[str, ...] | None = None,
    **more: Any,
) -> dict[str, Any]:
    cache = {"input_cache_read": cache_read} if cache_read is not None else {}
    cache |= {"input_cache_write": cache_write} if cache_write is not None else {}
    seen = {"input_modalities": list(inputs)} if inputs is not None else {}

    return {
        "id": name,
        "name": f"Name of {name}",
        "context_length": 200_000,
        "architecture": {"output_modalities": list(outputs), **seen},
        "pricing": {"prompt": prompt, "completion": completion, **cache},
        "supported_parameters": list(parameters),
        **more,
    }


def sample() -> dict[str, Any]:
    return {
        "data": [
            listed("anthropic/claude-sonnet-4.5", "0.000003", "0.000015", cache_read="0.0000003", cache_write="0.00000375"),
            listed("anthropic/claude-sonnet-4.5:batch", "0.0000015", "0.0000075"),
            listed("openai/gpt-5-image", outputs=("image", "text")),
            listed("some/no-tools", parameters=("temperature",)),
            listed("openrouter/auto", "-1", "-1", outputs=("text", "image")),
            listed("meta-llama/llama-3.3-70b-instruct:free", "0", "0"),
            {"id": "broken/model"},
            "not a model",
        ]
    }


class TestModelsFrom:
    def test_only_what_a_chat_can_use_is_kept_with_its_routers_first(self) -> None:
        models = models_from(sample())

        assert [model.id for model in models] == [
            "openrouter/auto",
            "openrouter/anthropic/claude-sonnet-4.5",
            "openrouter/meta-llama/llama-3.3-70b-instruct:free",
        ]

    def test_a_model_is_named_as_it_is_here_and_priced_per_token(self) -> None:
        sonnet = models_from(sample())[1]

        assert sonnet == OpenRouterModel(
            "openrouter/anthropic/claude-sonnet-4.5",
            "Name of anthropic/claude-sonnet-4.5",
            200_000,
            0.000003,
            0.000015,
            0.0000003,
            0.00000375,
        )
        assert sonnet.to_dict()["input_per_million"] == pytest.approx(3.0)
        assert sonnet.to_dict()["output_per_million"] == pytest.approx(15.0)

    def test_a_router_has_no_price_because_it_depends_on_what_it_chooses(self) -> None:
        auto = models_from(sample())[0]

        assert (auto.input_price, auto.output_price, auto.priced) == (None, None, False)
        assert auto.to_dict()["input_per_million"] is None

    def test_a_free_model_is_priced_at_nothing(self) -> None:
        free = models_from(sample())[2]

        assert (free.input_price, free.output_price, free.priced) == (0.0, 0.0, True)

    def test_what_a_model_charges_for_its_cache_is_read_where_it_says_so(self) -> None:
        sonnet, free = models_from(sample())[1:]
        only_reads = models_from({"data": [listed("a/b", cache_read="0.0000002")]})[0]
        wrong = models_from({"data": [listed("a/b", cache_read="-1", cache_write="free")]})[0]

        assert (sonnet.cache_read_price, sonnet.cache_write_price) == (0.0000003, 0.00000375)
        assert (free.cache_read_price, free.cache_write_price) == (None, None)
        assert (only_reads.cache_read_price, only_reads.cache_write_price) == (0.0000002, None)
        assert (wrong.cache_read_price, wrong.cache_write_price) == (None, None)
        assert cache_prices_of(models_from(sample())) == {
            "openrouter/anthropic/claude-sonnet-4.5": (0.0000003, 0.00000375)
        }

    def test_a_model_that_reads_images_is_known_by_what_openrouter_says_it_takes_in(self) -> None:
        data = {
            "data": [
                listed("a/sees", inputs=("text", "image", "file")),
                listed("a/reads-only", inputs=("text",)),
                listed("a/silent"),
                {**listed("a/wrong"), "architecture": {"input_modalities": "image", "output_modalities": ["text"]}},
            ]
        }

        models = {model.id: model.images for model in models_from(data)}

        assert models == {
            "openrouter/a/sees": True,
            "openrouter/a/reads-only": False,
            "openrouter/a/silent": False,
            "openrouter/a/wrong": False,
        }

    @pytest.mark.parametrize("data", [None, [], {}, {"data": "no"}, "text"])
    def test_what_is_not_a_list_of_models_is_refused(self, data: Any) -> None:
        with pytest.raises(ValueError, match="list of models"):
            models_from(data)

    @pytest.mark.parametrize(
        ("value", "price"),
        [("0.000002", 0.000002), (0, 0.0), ("0", 0.0), ("-1", None), (None, None), ("free", None), ("nan", None)],
    )
    def test_a_price_is_an_amount_or_nothing(self, value: Any, price: float | None) -> None:
        assert price_of(value) == price

    def test_a_router_that_is_already_named_for_openrouter_is_not_named_twice(self) -> None:
        assert model_id("openrouter/free") == "openrouter/free"
        assert model_id("openai/gpt-5.2") == "openrouter/openai/gpt-5.2"


class TestFetching:
    def test_the_list_is_read_from_openrouter_without_a_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        asked: list[dict[str, Any]] = []

        class Answer:
            def raise_for_status(self) -> None:
                pass

            def json(self) -> Any:
                return sample()

        def get(url: str, **kwargs: Any) -> Answer:
            asked.append({"url": url, **kwargs})
            return Answer()

        monkeypatch.setattr(requests, "get", get)

        assert len(fetch_models()) == 3
        assert asked[0]["url"] == "https://openrouter.ai/api/v1/models"
        assert "Authorization" not in asked[0]["headers"]


class Source:
    """Stands in for OpenRouter: what it lists, and how often it was asked."""

    def __init__(self) -> None:
        self.asked = 0
        self.fail = False

    def __call__(self) -> list[OpenRouterModel]:
        self.asked += 1
        if self.fail:
            raise requests.ConnectionError("no connection")
        return models_from(sample())


class TestCatalog:
    def test_the_list_is_read_when_it_is_first_wanted_and_its_prices_are_known_from_then(self) -> None:
        source = Source()
        catalog = Catalog(fetch=source)
        with pytest.raises(CostUnknownError):
            compute_token_cost("openrouter/anthropic/claude-sonnet-4.5", 1, 1)

        shown = catalog.listing()

        assert source.asked == 1
        assert [model["id"] for model in shown["models"]][0] == "openrouter/auto"
        assert shown["problem"] is None
        assert compute_token_cost("openrouter/anthropic/claude-sonnet-4.5", 10**6, 10**6) == pytest.approx(18.0)
        assert compute_token_cost("openrouter/meta-llama/llama-3.3-70b-instruct:free", 10**6, 10**6) == 0
        # A router is not priced, so a limit on spending cannot be enforced with one
        with pytest.raises(CostUnknownError):
            compute_token_cost("openrouter/auto", 1, 1)

    def test_a_list_that_is_not_old_is_not_read_again(self) -> None:
        source = Source()
        catalog = Catalog(fetch=source)

        catalog.listing()
        catalog.listing()
        catalog.ensure_prices()

        assert source.asked == 1

    def test_a_list_that_is_old_is_read_again(self) -> None:
        source = Source()
        catalog = Catalog(fetch=source, max_age=0)

        catalog.listing()
        catalog.listing()

        assert source.asked == 2

    def test_prices_are_known_without_reading_the_list_once_it_has_been_read(self) -> None:
        source = Source()
        catalog = Catalog(fetch=source)
        catalog.ensure_prices()
        catalog.ensure_prices()

        assert source.asked == 1
        assert catalog.known

    def test_when_openrouter_cannot_be_reached_the_old_list_is_used_and_the_trouble_is_said(self) -> None:
        source = Source()
        catalog = Catalog(fetch=source, max_age=0)
        catalog.listing()
        source.fail = True

        shown = catalog.listing()

        assert len(shown["models"]) == 3
        assert "could not be read" in shown["problem"] and "no connection" in shown["problem"]

    def test_after_a_failure_it_is_not_tried_for_again_at_once(self) -> None:
        source = Source()
        source.fail = True
        catalog = Catalog(fetch=source)

        first = catalog.listing()
        catalog.listing()
        catalog.ensure_prices()

        assert first["models"] == []
        assert first["problem"] is not None
        assert source.asked == 1
        assert not catalog.known

    def test_the_list_is_kept_in_a_file_and_is_there_without_a_connection_when_started_again(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "kept" / "models.json"
        Catalog(path, fetch=Source()).listing()
        utils.REGISTERED_PRICES.clear()
        source = Source()
        source.fail = True

        again = Catalog(path, fetch=source)

        assert again.known
        assert source.asked == 0
        assert compute_token_cost("openrouter/anthropic/claude-sonnet-4.5", 10**6, 0) == pytest.approx(3.0)
        assert len(again.listing()["models"]) == 3
        assert source.asked == 0

    @pytest.mark.parametrize("content", ["", "not json", "[]", '{"models": []}', '{"read_at": 1, "models": [{}]}'])
    def test_a_file_that_cannot_be_read_is_read_again_from_openrouter(self, tmp_path: Path, content: str) -> None:
        path = tmp_path / "models.json"
        path.write_text(content)
        source = Source()

        catalog = Catalog(path, fetch=source)
        assert not catalog.known
        catalog.listing()

        assert source.asked == 1
        assert json.loads(path.read_text())["models"][0]["id"] == "openrouter/auto"

    def test_what_the_cache_costs_is_known_from_the_list_and_from_the_file_it_is_kept_in(self, tmp_path: Path) -> None:
        sonnet = "openrouter/anthropic/claude-sonnet-4.5"
        path = tmp_path / "models.json"
        Catalog(path, fetch=Source()).listing()

        # 1M input tokens: 400k read from the cache, 100k written to it, the rest as input
        assert compute_token_cost(sonnet, 10**6, 0, 400_000, 100_000) == pytest.approx(0.5 * 3 + 0.4 * 0.3 + 0.1 * 3.75)
        assert json.loads(path.read_text())["format"] == SAVED_FORMAT
        utils.REGISTERED_PRICES.clear()
        utils.REGISTERED_CACHE_PRICES.clear()

        Catalog(path, fetch=Source())

        assert compute_token_cost(sonnet, 10**6, 0, 400_000, 100_000) == pytest.approx(0.5 * 3 + 0.4 * 0.3 + 0.1 * 3.75)

    def test_a_list_kept_before_it_said_what_the_cache_costs_is_used_and_read_again_at_once(
        self, tmp_path: Path
    ) -> None:
        sonnet = "openrouter/anthropic/claude-sonnet-4.5"
        path = tmp_path / "models.json"
        old = {
            "read_at": 9_999_999_999,
            "models": [
                {
                    "id": sonnet,
                    "name": "Sonnet",
                    "context_length": 200_000,
                    "input_price": 0.000003,
                    "output_price": 0.000015,
                }
            ],
        }
        path.write_text(json.dumps(old))
        source = Source()

        catalog = Catalog(path, fetch=source)

        assert catalog.known
        assert compute_token_cost(sonnet, 10**6, 0, 10**6) == pytest.approx(3.0)
        catalog.ensure_prices()
        catalog.ensure_prices()
        assert source.asked == 1
        assert compute_token_cost(sonnet, 10**6, 0, 10**6) == pytest.approx(0.3)
        assert json.loads(path.read_text())["format"] == SAVED_FORMAT

        Catalog(path, fetch=source).ensure_prices()
        assert source.asked == 1

    def test_which_models_read_images_is_known_from_the_list_and_from_the_file_it_is_kept_in(
        self, tmp_path: Path
    ) -> None:
        data = {"data": [listed("a/sees", inputs=("text", "image")), listed("a/blind", inputs=("text",))]}
        path = tmp_path / "models.json"
        Catalog(path, fetch=lambda: models_from(data)).listing()

        assert llm.accepts_images("openrouter/a/sees")
        assert not llm.accepts_images("openrouter/a/blind")
        assert json.loads(path.read_text())["models"][0]["images"] is True
        llm.REGISTERED_IMAGE_MODELS.clear()

        Catalog(path, fetch=lambda: models_from(data))

        assert llm.accepts_images("openrouter/a/sees")
        assert not llm.accepts_images("openrouter/a/blind")

    def test_a_list_kept_before_it_said_which_models_read_images_is_read_again_at_once(self, tmp_path: Path) -> None:
        path = tmp_path / "models.json"
        old = {
            "format": 2,
            "read_at": 9_999_999_999,
            "models": [{"id": "openrouter/a/sees", "name": "Sees", "input_price": 1e-6, "output_price": 2e-6}],
        }
        path.write_text(json.dumps(old))
        data = {"data": [listed("a/sees", inputs=("text", "image"))]}
        asked: list[int] = []

        def fetch() -> list[OpenRouterModel]:
            asked.append(1)
            return models_from(data)

        catalog = Catalog(path, fetch=fetch)
        assert catalog.known and not llm.accepts_images("openrouter/a/sees")
        catalog.ensure_prices()

        assert asked == [1]
        assert llm.accepts_images("openrouter/a/sees")
        Catalog(path, fetch=fetch).ensure_prices()
        assert asked == [1]

    def test_a_list_kept_before_that_that_cannot_be_read_again_is_still_used(self, tmp_path: Path) -> None:
        path = tmp_path / "models.json"
        path.write_text(
            json.dumps({"read_at": 1, "models": [{"id": "openrouter/a/b", "name": "B", "input_price": 1e-6, "output_price": 2e-6}]})
        )
        source = Source()
        source.fail = True

        catalog = Catalog(path, fetch=source)
        catalog.ensure_prices()
        catalog.ensure_prices()

        assert source.asked == 1
        assert compute_token_cost("openrouter/a/b", 10**6, 0) == pytest.approx(1.0)

    def test_a_list_that_cannot_be_kept_is_used_all_the_same(self, tmp_path: Path) -> None:
        blocked = tmp_path / "file"
        blocked.write_text("in the way")

        catalog = Catalog(blocked / "models.json", fetch=Source())

        assert len(catalog.listing()["models"]) == 3


class TestRegisteredPrices:
    def test_a_registered_price_is_by_the_name_given_and_no_part_of_it(self) -> None:
        register_prices({"some/model": (0.000001, 0.000002)})

        assert compute_token_cost("some/model", 1000, 500) == pytest.approx(0.002)
        with pytest.raises(CostUnknownError):
            compute_token_cost("some/model-pro", 1, 1)
        with pytest.raises(CostUnknownError):
            compute_token_cost("some/model-2025-01-01", 1, 1)

    @pytest.mark.parametrize("price", [-1.0, float("nan"), float("inf")])
    def test_a_price_that_is_not_an_amount_of_money_is_refused(self, price: float) -> None:
        with pytest.raises(ValueError, match="per token"):
            register_prices({"some/model": (price, 0.0)})
        assert "some/model" not in utils.REGISTERED_PRICES

    @pytest.mark.parametrize("price", [-1.0, float("nan"), float("inf")])
    def test_a_price_of_the_cache_that_is_not_an_amount_of_money_is_refused_and_nothing_is_registered(
        self, price: float
    ) -> None:
        with pytest.raises(ValueError, match="cache"):
            register_prices({"some/model": (1e-6, 2e-6)}, {"some/model": (price, None)})
        assert "some/model" not in utils.REGISTERED_PRICES
        assert "some/model" not in utils.REGISTERED_CACHE_PRICES

    def test_cached_tokens_cost_what_the_cache_costs_where_it_has_a_price_and_input_where_it_has_none(self) -> None:
        register_prices(
            {"some/model": (2e-6, 1e-5), "other/model": (2e-6, 1e-5), "third/model": (2e-6, 1e-5)},
            {"some/model": (2e-7, None), "other/model": (None, 4e-6)},
        )

        # 100 input tokens, 60 read from the cache and 30 written to it, and 10 output
        assert compute_token_cost("some/model", 100, 10, 60, 30) == pytest.approx(40 * 2e-6 + 60 * 2e-7 + 10 * 1e-5)
        assert compute_token_cost("other/model", 100, 10, 60, 30) == pytest.approx(70 * 2e-6 + 30 * 4e-6 + 10 * 1e-5)
        assert compute_token_cost("third/model", 100, 10, 60, 30) == pytest.approx(100 * 2e-6 + 10 * 1e-5)
        assert compute_token_cost("some/model", 100, 10) == pytest.approx(100 * 2e-6 + 10 * 1e-5)

    def test_what_was_said_of_a_models_cache_is_forgotten_when_it_is_priced_again(self) -> None:
        register_prices({"some/model": (2e-6, 1e-5)}, {"some/model": (2e-7, None)})
        register_prices({"some/model": (3e-6, 1e-5)})

        assert compute_token_cost("some/model", 100, 0, 100) == pytest.approx(100 * 3e-6)
        assert "some/model" not in utils.REGISTERED_CACHE_PRICES

    def test_a_cache_price_of_a_model_that_is_not_registered_is_not_kept(self) -> None:
        register_prices({}, {"some/model": (2e-7, None)})

        assert "some/model" not in utils.REGISTERED_CACHE_PRICES

    def test_a_model_of_the_tables_is_priced_with_cached_tokens_as_input(self) -> None:
        model = "gpt-4o"

        assert compute_token_cost(model, 1000, 100, 600, 100) == compute_token_cost(model, 1000, 100)

    def test_per_million_says_what_the_cache_costs_where_it_is_known(self) -> None:
        register_prices({"some/model": (2e-6, 1e-5), "other/model": (2e-6, 1e-5)}, {"some/model": (2e-7, 2.5e-6)})

        assert utils.price_per_million("some/model") == pytest.approx(
            {"input": 2.0, "output": 10.0, "cached_input": 0.2, "cache_write": 2.5}
        )
        assert utils.price_per_million("other/model") == pytest.approx({"input": 2.0, "output": 10.0})
        # The price of 1000 tokens at those prices is what compute_token_cost says
        assert utils.cost_at_prices(utils.price_per_million("some/model"), 1000, 100, 600, 100) == pytest.approx(
            compute_token_cost("some/model", 1000, 100, 600, 100)
        )


class TestInputCost:
    def test_each_kind_of_input_token_is_priced_at_its_own_rate(self) -> None:
        assert input_cost(2.0, 1000, 600, 0.2, 100, 2.5) == pytest.approx(300 * 2.0 + 600 * 0.2 + 100 * 2.5)

    def test_a_kind_with_no_price_is_input(self) -> None:
        assert input_cost(2.0, 1000, 600, None, 100, None) == pytest.approx(1000 * 2.0)
        assert input_cost(2.0, 1000) == pytest.approx(1000 * 2.0)

    def test_tokens_said_to_be_cached_that_are_more_than_the_input_are_not_counted_twice(self) -> None:
        assert input_cost(2.0, 100, 500, 0.2) == pytest.approx(100 * 0.2)
        assert input_cost(2.0, 100, 80, 0.2, 80, 2.5) == pytest.approx(80 * 0.2 + 20 * 2.5)

    def test_a_count_below_nothing_is_nothing(self) -> None:
        assert input_cost(2.0, 100, -5, 0.2, -5, 2.5) == pytest.approx(100 * 2.0)
