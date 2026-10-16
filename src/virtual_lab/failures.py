"""Says what went wrong when a model provider does not answer, in words a researcher can act on.

A provider's own error is written for a programmer: "Error code: 401 - {'error': {...}}", or a whole
HTML page from a gateway that is down. describe_failure keeps that as the detail, shortened, and puts
before it what happened and what to do about it. An error that is not a provider's, or is one that
is not recognised, is left exactly as it was, since a guess about it would only mislead.

Providers are told apart by what their errors carry, not by importing their packages: a status code,
and the names of the error's classes. The OpenAI and Anthropic clients, the wrappers LangChain puts
around them, and httpx all say the same things in the same way.
"""

import re
from dataclasses import dataclass

# How much of a provider's own message is kept beside the advice
DETAIL_LIMIT = 240

CONTEXT_PHRASES = (
    "context_length_exceeded",
    "maximum context length",
    "context window",
    "prompt is too long",
    "too many tokens",
)
QUOTA_PHRASES = (
    "insufficient_quota",
    "exceeded your current quota",
    "credit balance is too low",
    "insufficient credit",
)

KEY_REFUSED = (
    "The model provider did not accept the API key. Check it under API keys in Settings, then send the message again."
)
NOT_ALLOWED = (
    "The model provider does not let this key use this model. Check what the key may use in the provider's account, "
    "or choose another model in Settings."
)
NOT_FOUND = "The model provider has no such model or address. Check the model name and the server address in Settings."
OUT_OF_CREDIT = (
    "The model provider says the account is out of credit, or over the limit of its plan. "
    "Add credit or raise the limit, then send the message again."
)
TOO_FAST = "The model provider is limiting how fast it will answer. Wait a minute, then send the message again."
TOO_LONG = (
    "The conversation is longer than the model can read. "
    "Start a new conversation, or choose a model that reads more in Settings."
)
UNWELL = (
    "The model provider had a problem of its own (HTTP {status}) and did not answer. "
    "Wait a little, then send the message again."
)
SLOW = "The model provider took too long to answer. Send the message again."
UNREACHED = (
    "The connection to the model provider failed. Check the internet connection and the server address in Settings, "
    "then send the message again."
)
BROKEN_OFF = "The connection to the model provider broke off before it had answered. Send the message again."
NOTHING = (
    "The model provider sent back nothing. Check the model name and the server address in Settings, "
    "then send the message again."
)

TIMEOUT_NAMES = frozenset({"APITimeoutError", "TimeoutException"})
BROKEN_NAMES = frozenset({"RemoteProtocolError", "ReadError"})
UNREACHED_NAMES = frozenset({"APIConnectionError", "NetworkError"})


@dataclass(frozen=True)
class Failure:
    """What a failure is called and how it is told.

    :param type: The name of the error's class.
    :param text: What the researcher is shown: advice first, then the detail, when the cause is known.
    :param detail: The error as "Type: message", shortened when the cause is known and otherwise whole.
    """

    type: str
    text: str
    detail: str


def describe_failure(error: BaseException) -> Failure:
    """Tells of a failure, with advice if it is a model provider's.

    :param error: What was raised.
    :return: How it is named and told.
    """
    name = type(error).__name__
    plain = f"{name}: {error}"
    advice = advice_for(error)
    if advice is None:
        return Failure(name, plain, plain)

    detail = shorten(plain)

    return Failure(name, f"{advice} ({detail})", detail)


def advice_for(error: BaseException) -> str | None:
    """What a researcher should do about a provider's error, or None if it is not recognised as one."""
    status = status_of(error)
    names = {kind.__name__ for kind in type(error).__mro__}
    said = str(error).lower()

    if "ContextOverflowError" in names or (status == 400 and any(phrase in said for phrase in CONTEXT_PHRASES)):
        return TOO_LONG
    if status == 402 or (status in (400, 429) and any(phrase in said for phrase in QUOTA_PHRASES)):
        return OUT_OF_CREDIT
    if status == 429 or "RateLimitError" in names:
        return TOO_FAST
    if status == 401 or "AuthenticationError" in names:
        return KEY_REFUSED
    if status == 403 or "PermissionDeniedError" in names:
        return NOT_ALLOWED
    if status == 404 or "NotFoundError" in names:
        return NOT_FOUND
    if status == 408 or names & TIMEOUT_NAMES:
        return SLOW
    if status is not None and status >= 500:
        return UNWELL.format(status=status)
    if names & BROKEN_NAMES:
        return BROKEN_OFF
    if names & UNREACHED_NAMES:
        return UNREACHED
    if isinstance(error, ValueError) and str(error).startswith("No generation chunks were returned"):
        return NOTHING

    return None


def status_of(error: BaseException) -> int | None:
    """The HTTP status an error carries, as the OpenAI and Anthropic clients and httpx give it."""
    for holder in (error, getattr(error, "response", None)):
        status = getattr(holder, "status_code", None)
        if isinstance(status, int) and not isinstance(status, bool):
            return status

    return None


def shorten(text: str, limit: int = DETAIL_LIMIT) -> str:
    """Puts a provider's message on one line, without the markup of a page a gateway sent in its place."""
    if re.search(r"<(?:!doctype|html|body)\b", text, re.IGNORECASE):
        text = re.sub(r"<(script|style|head)\b.*?</\1\s*>", " ", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]*>", " ", text)
    text = " ".join(text.split())

    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
