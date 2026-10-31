"""Tests for token accounting and cost reporting."""

import pytest

from virtual_lab.constants import (
    DEFAULT_ENCODING,
    FINETUNING_MODEL_TO_INPUT_PRICE_PER_TOKEN,
    FINETUNING_MODEL_TO_OUTPUT_PRICE_PER_TOKEN,
    MODEL_TO_INPUT_PRICE_PER_TOKEN,
    MODEL_TO_OUTPUT_PRICE_PER_TOKEN,
)
from virtual_lab import utils
from virtual_lab.utils import (
    CostUnknownError,
    MeetingUsage,
    count_discussion_tokens,
    count_tokens,
    compute_token_cost,
)

from conftest import TEST_MODEL, make_usage


def test_default_encoding_matches_the_default_model() -> None:
    # gpt-4o and later use o200k_base; cl100k_base undercounts their tokens
    assert DEFAULT_ENCODING == "o200k_base"
    assert count_tokens("hello world") == count_tokens("hello world", "o200k_base")


class TestDiscussionTokenCounts:
    """Tool output is sent to the model, so it is input, and it is never model output."""

    @staticmethod
    def discussion() -> list[dict[str, str]]:
        return [
            {"agent": "User", "message": "Here is the agenda."},
            {"agent": "Immunologist", "message": "I will search the literature."},
            {"agent": "Tool", "message": "A very long article " * 500},
            {"agent": "Immunologist", "message": "Based on that article, here is my answer."},
        ]

    def test_tool_output_is_not_counted_as_model_output(self) -> None:
        counts = count_discussion_tokens(self.discussion())
        agent_output = count_tokens("I will search the literature.") + count_tokens(
            "Based on that article, here is my answer."
        )

        assert counts["output"] == agent_output

    def test_tool_output_is_reported_separately(self) -> None:
        counts = count_discussion_tokens(self.discussion())

        assert counts["tool"] == count_tokens("A very long article " * 500)

    def test_tool_output_is_counted_once_within_input(self) -> None:
        # The tool turn reaches the model as part of the prefix of the following turn, so it
        # already appears in the input count and must not be added again.
        counts = count_discussion_tokens(self.discussion())

        assert counts["input"] > counts["tool"]
        assert counts["input"] < 2 * counts["tool"]

    def test_tool_key_present_when_no_tools_were_used(self) -> None:
        counts = count_discussion_tokens([{"agent": "Immunologist", "message": "Hello."}])

        assert counts["tool"] == 0


class TestMeetingUsage:
    """MeetingUsage records what the API reports rather than re-tokenizing the transcript."""

    def test_accumulates_across_calls(self) -> None:
        usage = MeetingUsage()
        usage.add(TEST_MODEL, make_usage(prompt_tokens=100, completion_tokens=20))
        usage.add(TEST_MODEL, make_usage(prompt_tokens=300, completion_tokens=40))

        assert usage.input_tokens == 400
        assert usage.output_tokens == 60
        assert usage.num_calls == 2
        assert usage.max_input_tokens == 300

    def test_tracks_each_model_separately(self) -> None:
        usage = MeetingUsage()
        usage.add(TEST_MODEL, make_usage(prompt_tokens=100, completion_tokens=10))
        usage.add("o3-mini-2025-01-31", make_usage(prompt_tokens=50, completion_tokens=5))

        assert set(usage.per_model) == {TEST_MODEL, "o3-mini-2025-01-31"}
        assert usage.per_model[TEST_MODEL].input_tokens == 100
        assert usage.per_model["o3-mini-2025-01-31"].input_tokens == 50

    def test_prices_each_model_at_its_own_rate(self) -> None:
        cheap, expensive = "gpt-4o-mini-2024-07-18", TEST_MODEL
        usage = MeetingUsage()
        usage.add(cheap, make_usage(prompt_tokens=1000, completion_tokens=0))
        usage.add(expensive, make_usage(prompt_tokens=1000, completion_tokens=0))

        expected = 1000 * (
            MODEL_TO_INPUT_PRICE_PER_TOKEN[cheap] + MODEL_TO_INPUT_PRICE_PER_TOKEN[expensive]
        )

        assert usage.compute_cost() == pytest.approx(expected)
        # A single blended rate would have produced the same number for both models
        assert compute_token_cost(cheap, 1000, 0) != compute_token_cost(expensive, 1000, 0)

    def test_cached_input_is_reported_but_not_double_counted(self) -> None:
        usage = MeetingUsage()
        usage.add(TEST_MODEL, make_usage(prompt_tokens=1000, cached_tokens=400))

        assert usage.input_tokens == 1000
        assert usage.cached_input_tokens == 400

    @pytest.fixture
    def kimi(self, monkeypatch: pytest.MonkeyPatch) -> str:
        monkeypatch.setattr(utils, "REGISTERED_PRICES", {})
        monkeypatch.setattr(utils, "REGISTERED_CACHE_PRICES", {})
        utils.register_prices({"openrouter/kimi": (2e-6, 1e-5)}, {"openrouter/kimi": (2e-7, None)})

        return "openrouter/kimi"

    def test_cached_input_costs_what_the_provider_charges_for_it(self, kimi: str) -> None:
        # What a long conversation reported: nearly all of its input was read from the cache
        usage = MeetingUsage()
        usage.add(kimi, make_usage(prompt_tokens=961_851, completion_tokens=10_612, cached_tokens=897_536))

        assert usage.compute_cost() == pytest.approx(64_315 * 2e-6 + 897_536 * 2e-7 + 10_612 * 1e-5)
        assert usage.compute_cost() < 0.42
        assert usage.to_dict()["cost"] == pytest.approx(usage.compute_cost())

    def test_cached_input_costs_as_input_where_the_model_has_no_price_for_the_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(utils, "REGISTERED_PRICES", {})
        monkeypatch.setattr(utils, "REGISTERED_CACHE_PRICES", {})
        utils.register_prices({"openrouter/plain": (2e-6, 1e-5)})
        usage = MeetingUsage()
        usage.add("openrouter/plain", make_usage(prompt_tokens=1000, completion_tokens=100, cached_tokens=900))
        usage.add(TEST_MODEL, make_usage(prompt_tokens=1000, completion_tokens=100, cached_tokens=900))

        assert usage.compute_cost() == pytest.approx(
            1000 * 2e-6 + 100 * 1e-5 + compute_token_cost(TEST_MODEL, 1000, 100)
        )

    def test_tokens_written_to_the_cache_are_counted_and_kept(self, kimi: str) -> None:
        usage = MeetingUsage()
        usage.add(kimi, make_usage(prompt_tokens=1000, cached_tokens=100, cache_write_tokens=200))
        usage.add(kimi, make_usage(prompt_tokens=1000, cache_write_tokens=50))

        assert usage.per_model[kimi].cache_write_tokens == 250
        assert usage.to_dict()["per_model"][kimi]["cache_write_tokens"] == 250
        assert MeetingUsage.from_dict(usage.to_dict()).per_model[kimi].cache_write_tokens == 250
        # Usage kept before it was counted is read all the same
        old = usage.to_dict()
        del old["per_model"][kimi]["cache_write_tokens"]
        assert MeetingUsage.from_dict(old).per_model[kimi].cache_write_tokens == 0

    def test_a_count_of_tokens_written_that_is_not_one_is_not_counted(self, kimi: str) -> None:
        usage = MeetingUsage()
        details = make_usage(prompt_tokens=10).prompt_tokens_details
        assert details is not None
        for written in (None, -5, "many", 1.5):
            object.__setattr__(details, "cache_write_tokens", written)
            usage.add(kimi, make_usage(prompt_tokens=10).model_copy(update={"prompt_tokens_details": details}))

        assert usage.per_model[kimi].cache_write_tokens == 0

    def test_reasoning_tokens_are_a_subset_of_output(self) -> None:
        usage = MeetingUsage()
        usage.add(TEST_MODEL, make_usage(completion_tokens=100, reasoning_tokens=70))

        assert usage.output_tokens == 100
        assert usage.reasoning_tokens == 70

    def test_a_call_that_reports_no_usage_makes_the_cost_unknown(self) -> None:
        # Skipping it made the call free, which a spending limit reads as room to spend more
        usage = MeetingUsage()
        usage.add(TEST_MODEL, make_usage())
        usage.add(TEST_MODEL, None)

        assert usage.num_calls == 2
        assert usage.unreported_calls == 1

        with pytest.raises(CostUnknownError, match="did not report usage for 1 of the calls"):
            usage.compute_cost()

        assert usage.to_dict()["cost"] is None
        assert usage.to_dict()["unreported_calls"] == 1

    def test_unknown_model_cost_is_an_error(self) -> None:
        usage = MeetingUsage()
        usage.add("some-unreleased-model", make_usage())

        assert usage.num_calls == 1

        with pytest.raises(ValueError, match="some-unreleased-model"):
            usage.compute_cost()

    def test_unknown_model_does_not_break_the_summary(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        # An unpriced model must still report its token counts rather than crashing the meeting
        usage = MeetingUsage()
        usage.add("some-unreleased-model", make_usage(prompt_tokens=123))
        usage.print_summary(elapsed_time=1.0)

        output = capsys.readouterr().out

        assert "123" in output
        assert "Warning" in output

    def test_every_priced_model_is_priced_for_what_it_takes_in_and_what_it_gives_out(self) -> None:
        assert set(MODEL_TO_INPUT_PRICE_PER_TOKEN) == set(MODEL_TO_OUTPUT_PRICE_PER_TOKEN)
        assert all(price > 0 for price in MODEL_TO_INPUT_PRICE_PER_TOKEN.values())
        # What a model gives out costs more than what it takes in, for every model there is
        assert all(
            MODEL_TO_OUTPUT_PRICE_PER_TOKEN[model] > price for model, price in MODEL_TO_INPUT_PRICE_PER_TOKEN.items()
        )

    def test_a_dated_snapshot_is_priced_as_its_model(self) -> None:
        assert compute_token_cost("gpt-5.2-2025-12-11", 1000, 0) == pytest.approx(
            1000 * MODEL_TO_INPUT_PRICE_PER_TOKEN["gpt-5.2"]
        )

    @pytest.mark.parametrize("model", ["gpt-5-codex", "gpt-5.2-2025", "gpt-5.5-codex", "gpt-5.4-pro-preview"])
    def test_a_model_that_only_starts_like_a_priced_one_is_not_priced_as_it(self, model) -> None:
        # Matched as prefixes these all cost what gpt-5, gpt-5.2, or gpt-5.5 does, and a pro model is
        # several times that
        with pytest.raises(CostUnknownError, match=model):
            compute_token_cost(model, 1000, 0)

    def test_a_fine_tuned_model_is_priced_at_the_fine_tuned_rate(self) -> None:
        model = "ft:gpt-4o-2024-08-06:lab::abc123"

        assert compute_token_cost(model, 1000, 1000) == pytest.approx(
            1000 * FINETUNING_MODEL_TO_INPUT_PRICE_PER_TOKEN[TEST_MODEL]
            + 1000 * FINETUNING_MODEL_TO_OUTPUT_PRICE_PER_TOKEN[TEST_MODEL]
        )
        assert compute_token_cost(model, 1000, 0) > compute_token_cost(TEST_MODEL, 1000, 0)

    def test_a_fine_tuned_model_of_an_unpriced_base_is_not_priced(self) -> None:
        with pytest.raises(CostUnknownError):
            compute_token_cost("ft:gpt-5-pro:lab::abc123", 1000, 0)

    def test_summary_reports_every_model(self, capsys: pytest.CaptureFixture) -> None:
        usage = MeetingUsage()
        usage.add(TEST_MODEL, make_usage())
        usage.add("o3-mini-2025-01-31", make_usage())
        usage.print_summary(elapsed_time=1.0)

        output = capsys.readouterr().out

        assert TEST_MODEL in output
        assert "o3-mini-2025-01-31" in output
