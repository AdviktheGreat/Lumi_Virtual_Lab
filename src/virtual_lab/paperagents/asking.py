"""Asking a model, for the checks of a tool that need one, within a limit on what it may cost.

Two of the checks of a tool ask a model: the one against the numbers that the paper reports (linking.py), and the one
in which a model of another family chooses inputs to try (proposing.py). What they have in common is kept here, so that
it is kept the same: a limit on spending that is checked before every request, that holds over both of them when they
are given the same record of what was used, and that stops the asking when it cannot be told what has been spent. And a
model's family, which is what the one that chooses inputs must not be the same as.

What a model answers is never what decides a check. Each check says what the model was allowed to do, and does the rest
with a program.
"""

import re
from typing import Any, TypeVar

from pydantic import BaseModel

from virtual_lab.constants import CONSISTENT_TEMPERATURE
from virtual_lab.export import money
from virtual_lab.llm import OPENROUTER_PREFIX, ModelSource, resolve_chat_models
from virtual_lab.structured import StructuredOutputError, request_structured_output
from virtual_lab.utils import CostUnknownError, MeetingUsage

MAX_NOTE_CHARS = 300

Answer = TypeVar("Answer", bound=BaseModel)

# Who made a model, by what its name begins with. The names are those that the providers give, and a name that is none
# of these is of no family that is known, since a model that is not known to be of another family is not taken for one
FAMILY_NAMES = (
    ("anthropic", re.compile(r"(anthropic\.)?claude")),
    ("openai", re.compile(r"(gpt-|chatgpt|o[1-9]\d?(-|$)|ft:|azure-|text-davinci)")),
    ("google", re.compile(r"(gemini|gemma|palm)")),
    ("meta", re.compile(r"llama")),
    ("mistral", re.compile(r"(mistral|mixtral|codestral|ministral)")),
    ("deepseek", re.compile(r"deepseek")),
    ("qwen", re.compile(r"(qwen|qwq)")),
    ("xai", re.compile(r"grok")),
    ("cohere", re.compile(r"(command|cohere)")),
)
# What OpenRouter, and other hosts that name a model <maker>/<model>, call each maker, as a family of the above
MAKERS = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google",
    "meta-llama": "meta",
    "meta": "meta",
    "mistralai": "mistral",
    "deepseek": "deepseek",
    "deepseek-ai": "deepseek",
    "qwen": "qwen",
    "x-ai": "xai",
    "cohere": "cohere",
}


def family_of(model: str) -> str | None:
    """Who made a model, as far as its name says: anthropic, openai, google, meta, mistral, deepseek, qwen, xai, or
    cohere, and None if the name does not say. A provider that serves other makers' models, as OpenRouter does, is
    not a family; the maker that its name has in it is.

    :param model: The model's name, as it is given to the provider.
    """
    name = model.strip().lower().removeprefix(OPENROUTER_PREFIX)
    maker, slash, rest = name.partition("/")
    if slash:
        if maker in MAKERS:
            return MAKERS[maker]
        name = rest.rsplit("/", 1)[-1]
    for family, pattern in FAMILY_NAMES:
        if pattern.match(name):
            return family

    return None


class LimitReached(RuntimeError):
    """Raised before a request, when asking a model again would go beyond what may be spent, or when what has been spent
    can no longer be told."""


class Asker:
    """A model that is asked, within a limit on what is spent.

    :param model: The model to ask.
    :param max_cost: The most to spend, in USD, over all of the requests of every asker that is given the same usage,
        checked before every request.
    :param chat_models: The chat model to ask, as hold_meeting takes it.
    :param client: An OpenAI client, as hold_meeting takes it.
    :param usage: What has been used, to which this adds. Askers that are given the same one keep to one limit.
    :raises ValueError: If the model cannot be asked, as when it is not known which provider serves it.
    """

    def __init__(
        self,
        model: str,
        max_cost: float,
        chat_models: ModelSource | None = None,
        client: Any = None,
        usage: MeetingUsage | None = None,
    ) -> None:
        self.model = model
        self.max_cost = max_cost
        self.usage = usage if usage is not None else MeetingUsage()
        self.llm = resolve_chat_models([model], chat_models=chat_models, client=client)[model]

    def spent(self) -> float | None:
        """What has been spent, over every model that this usage is of, or None if it cannot be told."""
        try:
            return self.usage.compute_cost()
        except CostUnknownError:
            return None

    def check_limit(self) -> None:
        """:raises LimitReached: If the limit has been reached, or what has been spent cannot be told."""
        spent = self.spent()
        if spent is None:
            raise LimitReached("A response did not report what it used, so the limit on spending can no longer be kept")
        if spent >= self.max_cost:
            raise LimitReached(
                f"The limit on spending was reached: {money(spent)} of the {money(self.max_cost)} allowed"
            )

    def ask(self, system: str, user: str, schema: type[Answer], max_tokens: int) -> tuple[Answer | None, str | None]:
        """Asks once, for an answer of a shape.

        :return: The answer, or None and why there is none: the model's answer was not of the shape, or the request
            failed, as when a key is refused, which is the check's alone and not the job's.
        :raises LimitReached: Before the request, if the limit has been reached.
        """
        self.check_limit()
        try:
            answer, reply = request_structured_output(
                llm=self.llm,
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                schema=schema,
                temperature=CONSISTENT_TEMPERATURE,
                max_completion_tokens=max_tokens,
            )
        except StructuredOutputError as error:
            self.usage.add(self.model, error.usage)
            return None, str(error)[:MAX_NOTE_CHARS]
        except Exception as error:
            return None, f"The request failed: {type(error).__name__}: {str(error)[:MAX_NOTE_CHARS]}"
        self.usage.add(self.model, reply.usage)

        return answer, None


def neutralize(text: str, tag: str) -> str:
    """Text that cannot close the tags it is given in, so that nothing in it is taken for what follows them."""
    return re.sub(rf"<\s*(/?)\s*{tag}", rf"<\1 {tag}", text, flags=re.IGNORECASE)
