# Models and API keys

[Back to the README](../README.md). Which model and provider each agent uses, and where the keys go.

## Models and API keys

Lumi uses GPT-5.2 from OpenAI by default, and any agent can use a model from another provider. Each model is reached through LangChain, and its provider is worked out from its name by the rules [Biomni](https://github.com/snap-stanford/Biomni) uses, so an agent created with `model="claude-sonnet-4-5"` is sent to Anthropic and one with `model="gemini-2.5-pro"` to Google. Agents in the same meeting can use different providers.

| Provider | Model names | Key or setting |
| --- | --- | --- |
| OpenAI | `gpt-*`, `o1*`, `o3*`, `o4*`, `ft:*` | `OPENAI_API_KEY` |
| Anthropic | `claude-*` | `ANTHROPIC_API_KEY` |
| Google Gemini | `gemini-*` | `GEMINI_API_KEY` |
| Groq | any name containing `groq` | `GROQ_API_KEY` |
| Azure OpenAI | `azure-<deployment>` | `OPENAI_API_KEY`, `OPENAI_ENDPOINT` |
| OpenRouter | `openrouter/<author>/<model>`, such as `openrouter/anthropic/claude-sonnet-4.5`, and its routers, such as `openrouter/auto` | `OPENROUTER_API_KEY` |
| Ollama (local) | `llama*`, `qwen*`, `mistral*`, `gpt-oss*`, and names with a `/` (but not a name that begins `openrouter/`) | `pip install -e ".[ollama]"` |
| Amazon Bedrock | `anthropic.claude-*`, `us.*`, and other Bedrock IDs | `AWS_REGION`, `pip install -e ".[bedrock]"` |

[OpenRouter](https://openrouter.ai) is one key for a few hundred models from many providers, which makes it the easiest way to try another model. A name that begins `openrouter/` is sent there, with the rest of the name as OpenRouter knows the model (`openrouter/anthropic/claude-sonnet-4.5` is `anthropic/claude-sonnet-4.5`), through its OpenAI-compatible API. `fetch_models()` in `virtual_lab.openrouter` lists the models that can call tools, which an agent needs, with their prices, read from OpenRouter's public list with no key. The server keeps that list for a day in the workspace's `openrouter-models.json` and works out what a model costs from its prices, including those of its cache, so a spending limit works with any model in the list; a script does the same with `register_prices(prices_of(models), cache_prices_of(models))` for `models = fetch_models()` (`register_prices` is in `virtual_lab.utils`), since a model whose price is not known cannot be given a limit (`CostUnknownError`). OpenRouter's routers (`openrouter/auto`, `openrouter/free`) choose a model for each request, so their price is not known beforehand: they are listed, and work, but a conversation or project with a spending limit refuses them. The library does not set OpenRouter's own fallback or moderation options, and has not been checked against them.

Set `LLM_SOURCE` to one of those providers to override the rules for every model. A meeting sends a name the rules do not recognise, such as `chatgpt-4o-latest`, to OpenAI as it always has, and while `OPENAI_BASE_URL` points at a server of your own it sends names that look like open models there rather than to Ollama. For anything else, including a self-hosted server with an OpenAI-compatible API, build the model yourself and pass it in:

```python
from virtual_lab import get_llm, hold_meeting

served = get_llm("biomni-r0", source="Custom", base_url="http://localhost:30000/v1")
result = hold_meeting(..., chat_models={"biomni-r0": served})
```

`chat_models` also takes a single LangChain chat model for every agent, or a function from model name to chat model. The record of each meeting names the class that answered for each model and the server it was sent to.

OpenAI's API is told which agent wrote each earlier turn. Other providers have no field for this, so for them the other agents' turns are passed as user messages that begin with the speaker's name, rather than as the reader's own words. A model can copy that format, writing a line such as `[Name called a_tool with {...}]` as though it were calling the tool, which runs nothing and would end its turn there with only that text. A turn like that is not taken as the agent's answer: it is told that nothing ran and asked again, up to `MAX_FAKED_CALL_RETRIES` (2) times, and what it wrote by mistake is not kept in the meeting for the others to read. A name that a reply begins with, which a model also copies, is taken off it.

Keys can be kept in a `.env` file, one `NAME=value` per line. As Biomni does, `import virtual_lab` reads the `.env` file in the directory Python was started in, if there is one, and sets each variable that is not already set, so a key set in the shell outranks the file's. It prints nothing. `load_env("keys.env")` reads another file, `load_env(override=True)` replaces what is set, and each returns the names of the variables it set. Setting `VIRTUAL_LAB_LOAD_ENV=0` stops the file being read on import. What is read reaches this process alone: a session's code gets a variable only when it is forwarded by name (see `forward_env` below).
