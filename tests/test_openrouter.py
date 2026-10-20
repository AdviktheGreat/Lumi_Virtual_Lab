"""Tests of the models OpenRouter serves: which a chat can use, what they cost, and how the list is kept."""

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from virtual_lab import utils
from virtual_lab.openrouter import Catalog, OpenRouterModel, fetch_models, model_id, models_from, price_of
from virtual_lab.utils import CostUnknownError, compute_token_cost, register_prices


@pytest.fixture(autouse=True)
def no_prices_left_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utils, "REGISTERED_PRICES", {})


def listed(
    name: str,
    prompt: str = "0.000002",
    completion: str = "0.00001",
    parameters: tuple[str, ...] = ("tools", "temperature"),
    outputs: tuple[str, ...] = ("text",),
    **more: Any,
) -> dict[str, Any]:
    return {
        "id": name,
        "name": f"Name of {name}",
        "context_length": 200_000,
        "architecture": {"output_modalities": list(outputs)},
        "pricing": {"prompt": prompt, "completion": completion},
        "supported_parameters": list(parameters),
        **more,
    }


def sample() -> dict[str, Any]:
    return {
        "data": [
            listed("anthropic/claude-sonnet-4.5", "0.000003", "0.000015"),
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
            "openrouter/anthropic/claude-sonnet-4.5", "Name of anthropic/claude-sonnet-4.5", 200_000, 0.000003, 0.000015
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
