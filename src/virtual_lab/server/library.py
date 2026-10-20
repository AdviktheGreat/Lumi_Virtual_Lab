"""What the server offers to choose from: models, and the keys of the providers that reach them."""

import os
from dataclasses import dataclass

from virtual_lab.constants import DEFAULT_MODEL, MODEL_TO_INPUT_PRICE_PER_TOKEN
from virtual_lab.llm import detect_source

# The environment variables each provider's models are reached with, as the README lists them
PROVIDER_KEYS: dict[str, tuple[str, ...]] = {
    "OpenAI": ("OPENAI_API_KEY",),
    "Anthropic": ("ANTHROPIC_API_KEY",),
    "Gemini": ("GEMINI_API_KEY",),
    "Groq": ("GROQ_API_KEY",),
    "OpenRouter": ("OPENROUTER_API_KEY",),
    "AzureOpenAI": ("OPENAI_API_KEY", "OPENAI_ENDPOINT"),
    "Bedrock": ("AWS_REGION",),
}

# The keys a person may give the interface for the rest of the process
SETTABLE_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")

# OpenRouter's routers and a few of the models most often wanted through it, so that there is something to choose before
# its whole list has been read. The rest of its models are searched for in that list.
FEATURED_OPENROUTER_MODELS = (
    "openrouter/auto",
    "openrouter/free",
    "openrouter/anthropic/claude-sonnet-4.5",
    "openrouter/openai/gpt-5.2",
    "openrouter/google/gemini-2.5-pro",
    "openrouter/deepseek/deepseek-v3.2",
)


@dataclass(frozen=True)
class ProviderStatus:
    """Whether a provider's models can be reached, by whether its variables are set.

    :param provider: The provider, as detect_source names it.
    :param variables: The variables it needs.
    :param missing: Those of them not set.
    """

    provider: str
    variables: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.missing


def models() -> list[str]:
    """The models to choose from: the default, then every priced one, newest families first, then OpenRouter's."""
    return list(
        dict.fromkeys(
            [DEFAULT_MODEL, *sorted(MODEL_TO_INPUT_PRICE_PER_TOKEN, key=model_order), *FEATURED_OPENROUTER_MODELS]
        )
    )


MODEL_FAMILIES = ("gpt-6", "gpt-5", "claude-", "gemini-", "gpt-4", "o")


def model_order(model: str) -> tuple[int, str]:
    family = next(
        (index for index, prefix in enumerate(MODEL_FAMILIES) if model.startswith(prefix)), len(MODEL_FAMILIES)
    )
    return family, model


def provider_of(model: str) -> str | None:
    try:
        return detect_source(model)
    except ValueError:
        return None


def provider_statuses() -> list[ProviderStatus]:
    """Every provider, with the variables it needs that are not set. No value is read out."""
    return [
        ProviderStatus(provider, variables, tuple(name for name in variables if not os.environ.get(name)))
        for provider, variables in PROVIDER_KEYS.items()
    ]


def missing_keys(models_used: list[str]) -> list[str]:
    """The variables the providers of these models need that are not set, to say so before a run."""
    statuses = {status.provider: status for status in provider_statuses()}
    missing: list[str] = []
    for model in models_used:
        status = statuses.get(provider_of(model) or "")
        if status is not None:
            missing += [name for name in status.missing if name not in missing]

    return missing
