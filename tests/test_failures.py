"""Tests for telling a researcher what a model provider's failure means, and what to do about it."""

from typing import Any

import anthropic
import httpx
import openai
import pytest

from virtual_lab import failures
from virtual_lab.failures import DETAIL_LIMIT, Failure, describe_failure, shorten, status_of

REQUEST = httpx.Request("POST", "https://api.example.test/v1/chat/completions")


def refused(error_class: Any, status: int, message: str, body: Any = None) -> Any:
    """An error as the OpenAI and Anthropic clients raise it when a provider answers with a status."""
    return error_class(message, response=httpx.Response(status, request=REQUEST), body=body)


class ContextOverflowError(Exception):
    """Named as LangChain names the error it raises when the provider says a prompt is too long."""


def named(name: str, message: str = "Nothing but its name to go by") -> Exception:
    """An error of a class with a given name, which is all that some wrappers around a provider's errors keep."""
    return type(name, (Exception,), {})(message)


class Carrying(Exception):
    def __init__(self, status: Any) -> None:
        super().__init__("A status in a place that is not one")
        self.status_code = status


class TestAdvice:
    @pytest.mark.parametrize(
        ("error", "advice"),
        [
            pytest.param(
                refused(openai.AuthenticationError, 401, "Error code: 401"), failures.KEY_REFUSED, id="openai key"
            ),
            pytest.param(
                refused(anthropic.AuthenticationError, 401, "invalid x-api-key"),
                failures.KEY_REFUSED,
                id="anthropic key",
            ),
            pytest.param(
                refused(openai.PermissionDeniedError, 403, "Error code: 403"), failures.NOT_ALLOWED, id="forbidden"
            ),
            pytest.param(
                refused(openai.NotFoundError, 404, "The model does not exist"), failures.NOT_FOUND, id="no model"
            ),
            pytest.param(
                refused(openai.RateLimitError, 429, "Rate limit reached for gpt-5 on tokens per min"),
                failures.TOO_FAST,
                id="too fast",
            ),
            pytest.param(
                refused(
                    openai.RateLimitError,
                    429,
                    "Rate limit reached. You can raise your rate limit by adding a payment method at /account/billing.",
                ),
                failures.TOO_FAST,
                id="too fast, and billing is mentioned",
            ),
            pytest.param(
                refused(
                    openai.RateLimitError,
                    429,
                    "Error code: 429 - {'error': {'type': 'insufficient_quota'}}",
                ),
                failures.OUT_OF_CREDIT,
                id="quota",
            ),
            pytest.param(
                refused(openai.RateLimitError, 429, "You exceeded your current quota, please check your plan."),
                failures.OUT_OF_CREDIT,
                id="quota by its words",
            ),
            pytest.param(
                refused(anthropic.BadRequestError, 400, "Your credit balance is too low to access the Anthropic API."),
                failures.OUT_OF_CREDIT,
                id="anthropic credit",
            ),
            pytest.param(
                refused(openai.APIStatusError, 402, "Insufficient credits"),
                failures.OUT_OF_CREDIT,
                id="payment required",
            ),
            pytest.param(
                refused(openai.BadRequestError, 400, "Error code: 400 - {'code': 'context_length_exceeded'}"),
                failures.TOO_LONG,
                id="openai context",
            ),
            pytest.param(
                refused(anthropic.BadRequestError, 400, "prompt is too long: 250000 tokens > 200000 maximum"),
                failures.TOO_LONG,
                id="anthropic context",
            ),
            pytest.param(ContextOverflowError("The prompt is too long"), failures.TOO_LONG, id="context, by its class"),
            pytest.param(
                refused(openai.APIStatusError, 408, "Request Timeout"), failures.SLOW, id="request timeout status"
            ),
            pytest.param(openai.APITimeoutError(request=REQUEST), failures.SLOW, id="openai timeout"),
            pytest.param(httpx.ReadTimeout("The read operation timed out"), failures.SLOW, id="httpx read timeout"),
            pytest.param(httpx.ConnectTimeout("timed out"), failures.SLOW, id="httpx connect timeout"),
            pytest.param(openai.APIConnectionError(request=REQUEST), failures.UNREACHED, id="openai connection"),
            pytest.param(anthropic.APIConnectionError(request=REQUEST), failures.UNREACHED, id="anthropic connection"),
            pytest.param(httpx.ConnectError("Connection refused"), failures.UNREACHED, id="httpx connect"),
            pytest.param(httpx.RemoteProtocolError("peer closed connection"), failures.BROKEN_OFF, id="cut off"),
            pytest.param(httpx.ReadError("reset"), failures.BROKEN_OFF, id="read failed"),
            pytest.param(ValueError("No generation chunks were returned"), failures.NOTHING, id="empty stream"),
        ],
    )
    def test_a_provider_failure_gets_advice_for_what_it_means(self, error: BaseException, advice: str) -> None:
        assert describe_failure(error).text.startswith(advice + " (")

    @pytest.mark.parametrize(
        ("error", "status"),
        [
            (refused(openai.InternalServerError, 500, "Error code: 500"), 500),
            (refused(openai.InternalServerError, 502, "<html><body>502 Bad Gateway</body></html>"), 502),
            (refused(anthropic.InternalServerError, 529, "Overloaded"), 529),
            (refused(openai.APIStatusError, 503, "Service unavailable"), 503),
            (refused(openai.APIStatusError, 504, "Gateway timeout"), 504),
        ],
    )
    def test_a_provider_that_is_unwell_is_told_with_its_status(self, error: BaseException, status: int) -> None:
        assert describe_failure(error).text.startswith(f"The model provider had a problem of its own (HTTP {status})")

    @pytest.mark.parametrize(
        ("status", "name", "advice"),
        [
            (401, "AuthenticationError", failures.KEY_REFUSED),
            (403, "PermissionDeniedError", failures.NOT_ALLOWED),
            (404, "NotFoundError", failures.NOT_FOUND),
            (429, "RateLimitError", failures.TOO_FAST),
        ],
    )
    def test_the_status_alone_is_enough_and_so_is_the_name_of_the_class(
        self, status: int, name: str, advice: str
    ) -> None:
        assert describe_failure(Carrying(status)).text.startswith(advice)
        assert describe_failure(named(name)).text.startswith(advice)

    @pytest.mark.parametrize("name", ["APIConnectionError", "NetworkError"])
    def test_a_connection_that_failed_is_known_by_the_name_of_its_class(self, name: str) -> None:
        assert describe_failure(named(name)).text.startswith(failures.UNREACHED)

    def test_only_a_value_error_with_those_words_is_an_empty_reply(self) -> None:
        said = "No generation chunks were returned"

        assert describe_failure(RuntimeError(said)).text == f"RuntimeError: {said}"
        assert describe_failure(ValueError(f"{said} by the model")).text.startswith(failures.NOTHING)

    def test_the_status_is_read_from_the_response_of_an_httpx_error(self) -> None:
        error = httpx.HTTPStatusError("Server error", request=REQUEST, response=httpx.Response(503, request=REQUEST))

        assert status_of(error) == 503
        assert "(HTTP 503)" in describe_failure(error).text

    def test_a_status_error_with_nothing_to_say_of_it_is_left_as_it_was(self) -> None:
        error = refused(openai.BadRequestError, 400, "Error code: 400 - {'message': 'Unsupported parameter'}")

        assert describe_failure(error) == Failure(
            "BadRequestError",
            "BadRequestError: Error code: 400 - {'message': 'Unsupported parameter'}",
            "BadRequestError: Error code: 400 - {'message': 'Unsupported parameter'}",
        )

    @pytest.mark.parametrize(
        "error",
        [
            RuntimeError("The server went away"),
            ConnectionError("The server did not answer"),
            ConnectionRefusedError("Connection refused"),
            TimeoutError("The sandbox did not answer"),
            ValueError("Principal Investigator sent no answer"),
            KeyboardInterrupt(),
            Carrying(True),
            Carrying("401"),
            Carrying(None),
        ],
    )
    def test_an_error_that_is_not_recognised_as_a_providers_is_left_as_it_was(self, error: BaseException) -> None:
        plain = f"{type(error).__name__}: {error}"

        assert describe_failure(error) == Failure(type(error).__name__, plain, plain)

    def test_a_long_message_that_is_not_recognised_is_kept_whole(self) -> None:
        message = "word " * 200

        assert describe_failure(RuntimeError(message)).text == f"RuntimeError: {message}"


class TestStatus:
    def test_a_status_comes_from_the_error_or_its_response(self) -> None:
        assert status_of(Carrying(418)) == 418
        assert status_of(refused(openai.NotFoundError, 404, "gone")) == 404
        assert status_of(RuntimeError("no status")) is None

    @pytest.mark.parametrize("status", [True, "500", 500.0, None])
    def test_something_that_is_not_a_number_is_not_a_status(self, status: Any) -> None:
        assert status_of(Carrying(status)) is None


class TestTelling:
    def test_the_advice_comes_first_and_the_providers_own_words_follow_in_brackets(self) -> None:
        error = refused(
            openai.AuthenticationError,
            401,
            "Error code: 401 - {'error': {'message': 'Incorrect API key provided: sk-drill****'}}",
        )

        failure = describe_failure(error)

        assert failure.type == "AuthenticationError"
        assert failure.detail == (
            "AuthenticationError: Error code: 401 - {'error': {'message': 'Incorrect API key provided: sk-drill****'}}"
        )
        assert failure.text == f"{failures.KEY_REFUSED} ({failure.detail})"

    def test_the_providers_own_words_are_cut_short(self) -> None:
        failure = describe_failure(refused(openai.InternalServerError, 500, "oops " * 200))

        assert len(failure.detail) == 240 and failure.detail.endswith("…")
        assert failure.detail.startswith("InternalServerError: oops oops")

    def test_a_page_a_gateway_sent_in_place_of_an_answer_is_told_as_the_words_on_it(self) -> None:
        page = (
            "<!DOCTYPE html><html><head><title>Bad gateway</title><style>h1 { color: red }</style></head>"
            "<body><h1>502 Bad Gateway</h1><script>var tracking = 1</script><p>nginx</p></body></html>"
        )

        failure = describe_failure(refused(openai.InternalServerError, 502, page))

        assert failure.detail == "InternalServerError: 502 Bad Gateway nginx"
        assert failure.text == f"{failures.UNWELL.format(status=502)} (InternalServerError: 502 Bad Gateway nginx)"

    def test_a_provider_that_is_told_of_has_its_class_named_whatever_wraps_it(self) -> None:
        class OpenAIAuthenticationError(openai.AuthenticationError):
            pass

        failure = describe_failure(refused(OpenAIAuthenticationError, 401, "Error code: 401"))

        assert failure.type == "OpenAIAuthenticationError"
        assert failure.text.startswith(failures.KEY_REFUSED)


class TestShorten:
    def test_it_puts_the_message_on_one_line(self) -> None:
        assert shorten("one\n  two\t three\r\n") == "one two three"

    def test_a_message_of_up_to_240_characters_is_kept(self) -> None:
        assert DETAIL_LIMIT == 240
        assert shorten("x" * 240) == "x" * 240

    def test_a_longer_message_ends_in_an_ellipsis_within_240_characters(self) -> None:
        assert shorten("x" * 241) == "x" * 239 + "…"

    def test_a_limit_can_be_given(self) -> None:
        assert shorten("abc def ghi", limit=8) == "abc def…"

    def test_markup_is_taken_out_of_a_page_only(self) -> None:
        assert (
            shorten("Error code: 502 - <html><body><b>Bad</b> Gateway</body></html>") == "Error code: 502 - Bad Gateway"
        )
        assert shorten("Use <b>bold</b> and a < b > c") == "Use <b>bold</b> and a < b > c"

    def test_a_page_is_known_by_its_tags_in_any_case(self) -> None:
        assert shorten("Error code: 502 - <HTML><BODY>Bad Gateway</BODY></HTML>") == "Error code: 502 - Bad Gateway"
        assert shorten("<!DOCTYPE html>Bad Gateway") == "Bad Gateway"

    def test_the_head_and_the_scripts_of_a_page_are_not_part_of_what_it_says(self) -> None:
        page = "<html><HEAD><title>t</title></HEAD><body>Hello<SCRIPT type='x'>\nvar a;\n</SCRIPT> there</body></html>"

        assert shorten(page) == "Hello there"
