# Meetings

[Back to the README](../README.md). Holding a team or an individual meeting from Python, limiting what it spends, following and steering it, and saving it as a document.

## Holding a meeting and limiting what it spends

`hold_meeting` takes the same arguments as `run_meeting` and returns everything the meeting produced: the summary, the structured output if a schema was given, the usage, the provenance record, and where each was saved. `run_meeting` is kept for existing notebooks and returns only one of these.

```python
from virtual_lab import BudgetExceededError, hold_meeting

try:
    result = hold_meeting(
        meeting_type="individual",
        agenda="Propose three candidate drug targets.",
        save_dir=Path("results"),
        team_member=immunologist,
        num_rounds=2,
        max_cost=0.50,
        max_completion_tokens=4_000,
    )
    print(result.summary, result.cost)
except BudgetExceededError as error:
    print(f"Stopped at ${error.spent:.2f}; the turns so far are in results/partial/")
```

- `max_cost` is checked before every request, including each tool call and the structured output, so a meeting stops before the request it has no money left for. It can overrun by at most one request, which `max_completion_tokens` bounds.
- A limit is refused outright if any model in the meeting has no price in `virtual_lab.constants`, and a response that reports no usage stops a limited meeting with `CostUnknownError`. Either would otherwise count as free. Without a limit, `result.cost` is `None` rather than a wrong number.
- OpenAI, Anthropic, and Gemini models are priced, as of October 2026. A model with two rates, by how long the prompt is, or with a rise announced for a date, is priced at the higher one, so its cost is an upper bound. `gpt-5.6-sol` is at a promotional price that is to last at least through November 21, 2026.
- Input tokens that a provider read from its cache are counted at what it charges for them where the price says so, which OpenRouter's does for the models that cache (`pricing.input_cache_read`, and `input_cache_write` for those it wrote). In a long conversation most of the input is read that way, at a tenth of the input price for some models, so counting it as input would stop a conversation at five times what it had cost. For the models in the tables, and any that does not say, cached input is counted as input, an upper bound. `register_prices` takes the cache prices as a second argument, and the record of a meeting's prices has them as `cached_input` and `cache_write` per million tokens.
- Prices are matched exactly or to a dated snapshot of a listed model (`gpt-4o-2024-08-06`, `claude-sonnet-4-5-20250929`). A name that merely starts with a listed one, such as `gpt-5-codex` or `gpt-5.5-codex`, is unpriced rather than billed at the cheaper model's rate.
- `on_usage` is called with the running usage after every response, for a caller keeping a total across meetings. An exception it raises stops the meeting like any other failure.
- `before_request` is called before every request, after `max_cost` is checked. An exception it raises stops the meeting before the request is sent, which is how several meetings sharing one budget are stopped together (see `Project` below).
- A failed or interrupted meeting, including one stopped by its limit or by Ctrl-C, saves its turns and its record, with the usage up to that point, under `save_dir/partial/`.
- Several models (GPT-5 and its mini, nano, and pro versions among them) refuse any temperature but their default. When the API refuses the temperature, the request is sent again without it, the model is remembered for the rest of the process, and the record lists it under `models_at_default_temperature`.

### Following a meeting as it happens

Biomni's agent yields each step of its work once the step is done, which is what its web interface shows. A meeting does the same through `on_event`, which is called with a `MeetingEvent` for everything that happens, and with `stream=True` it is also told of each reply as it is written, word by word:

```python
from virtual_lab import MeetingEvent, hold_meeting

def show(event: MeetingEvent) -> None:
    if event.kind == "turn":
        print(f"\n--- {event.speaker}, round {event.round} ---")
    elif event.kind == "writing":
        print(event.text, end="\r")
    elif event.kind == "cell":
        print(f"Ran {event.data['language']} ({event.data['status']}), figures: {event.data['plot_paths']}")
    elif event.kind == "usage" and event.data["cost"] is not None:
        print(f"Spent so far: ${event.data['cost']:.4f}")

hold_meeting(..., on_event=show, stream=True)
```

| Kind | When | What it holds |
| --- | --- | --- |
| `started` | The meeting begins | `data`: the meeting type, agenda, questions, rounds, team, tools, `max_cost`, and session |
| `resources` | The resources of Biomni's environment are chosen | `data`: what the record says of them |
| `turn` | An agent's turn begins | `speaker`, `round`, and `data`: its name and model |
| `writing` | More of a reply is written, with `stream` | `text`: the reply so far, which replaces the last with the same `data["request"]` |
| `message` | A message is added to the transcript | `speaker`, `text`, and `data`: its kind (`prompt`, `response`, `code_action`, `code_output`, `tool_output`, or `structured_output`) and its index |
| `tool_calls` | Tools are about to run | `data["calls"]`: each call's id, name, and arguments, in full |
| `code` | Code from `<execute>` tags is about to run | `data`: the code and its language |
| `cell` | Code ran in the session, from tags or `run_code` | `data`: the run, as `CellResult.to_dict` gives it, and `plot_paths`, where its figures are |
| `usage` | A response came back | `data`: the usage so far, with its `cost`, or `None` if unknown |
| `finished` | The meeting is saved | `text`: the summary, and `data`: where it was saved, the structured output, the usage, and how long it took |
| `failed` | The meeting stopped with an error | `text`: the error, and `data`: its type, where the partial transcript is, and the usage |

- An exception `on_event` raises stops the meeting the way any other failure does, saving what was done under `save_dir/partial/`, even while a reply is being written. This is how a person can stop a meeting part way through a reply. One it raises when told the meeting finished, which is saved by then, or failed, which would hide the error that ended it, is only warned about.
- With `stream`, every reply is asked for with its usage, so what it cost is still known. OpenAI-compatible servers that leave the usage of a streamed reply out make the cost unknown, as they would without streaming, and one that refuses to be asked fails the request; a model told not to stream its usage (`stream_usage=False`) is left as told. A model that cannot stream sends its reply whole, as one `writing` event. Structured outputs, and the request that chooses resources, are not streamed.
- `Project` takes `on_event` and `stream` as options for its meetings, and neither makes a finished meeting a different one, so a project carried on with or without them reads its meetings back. A meeting read back is told of by one `read_back` event, with its summary and where it is saved.

### Steering a meeting as it happens

A person following a meeting can steer it as well as watch it. `steer` is called before every agent's turn with a `NextTurn`, which names the meeting, the round, and the agent about to speak, and returns a note or `None`:

```python
from virtual_lab import NextTurn, hold_meeting

def steer(turn: NextTurn) -> str | None:
    if turn.speaker == "Scientific Critic":
        return "Check the controls in the binding assay before anything else."
    return None

hold_meeting(..., steer=steer)
```

- A note is added to the discussion after the agent's prompt, introduced as from the human researcher overseeing the meeting, so the agent about to speak reads it last, and everyone after it reads it too. It is kept in the transcript as from `Human researcher`, with the kind `note` in the record and in the `message` event, and saved documents show it, so no agent may have that title. A note that is empty or only spaces is not added.
- The meeting waits while `steer` does, which is how it is paused: a function that waits for a person to resume holds the meeting before the turn, with nothing sent. `steer` is asked only between turns, so an agent running code or calling tools finishes its turn first.
- An exception `steer` raises stops the meeting the way any other failure does, saving what was done under `save_dir/partial/`.
- `interrupt` is called about every fifth of a second while a request waits for its reply, which is how a meeting is stopped while a provider says nothing: what it raises ends the meeting at once, the way an exception from `steer` does, and the request is left to end as it will, with its reply dropped. A `Chat` gives its meetings its own check for a stop. Like `steer`, it does not make a finished meeting a different one.
- `Project` takes `steer` as an option for its meetings. Like `on_event`, it does not make a finished meeting a different one: what was said is in the meeting's transcript, and a project carried on reads it back.

### Saving a meeting or a conversation as a document

Biomni saves its agent's conversation as a PDF. A meeting can be saved as one too, or as a page of HTML, laid out as a meeting: its agenda, team, and summary first, then the discussion round by round, each agent in a colour of its own, with the code each agent ran, what it printed, and the figures it drew, then what the meeting cost. A conversation with the head of a lab, as the web interface has it, is saved as what was asked and answered, turn by turn.

```python
from virtual_lab import save_chat_html, save_chat_notebook, save_chat_pdf, save_meeting_html, save_meeting_pdf

save_meeting_pdf("results/discussion.json")            # results/discussion.pdf
save_meeting_html("results/discussion.json")           # results/discussion.html, which needs no extra
save_chat_pdf("workspace/chats/2025-03-04_0912_counts")   # conversation.pdf in that folder
save_chat_notebook("workspace/chats/2025-03-04_0912_counts")   # conversation.ipynb, which needs no extra
```

- A PDF needs WeasyPrint, which `pip install -e ".[pdf]"` installs, and the Pango library it draws text with, which pip cannot: `brew install pango` on macOS, or `apt install libpango-1.0-0 libpangoft2-1.0-0` on Debian and Ubuntu. Without them a PDF is refused with `PDFExportError`, saying what to install, and HTML can still be saved.
- Everything is read from what was saved, so any meeting can be saved as a document at any time, including one that failed, from `partial/`, and a transcript saved before meetings kept records, which is shown from the transcript alone.
- The prompts each agent was given are left out, since the agenda stands for them; `include_prompts=True` shows them. Notes a person gave through `steer` are always shown. A tool's or the session's output is cut to `max_output_chars`, 6,000 characters by default, from the middle.
- What the agents wrote is rendered as Markdown, with any HTML in it shown as text, and the document carries its figures, so neither the HTML nor the PDF fetches anything: an image an agent linked to, on the web or on disk, is shown as a link to it. A figure is read only from the session's own directory.
- `meeting_html` and `chat_html` return the document rather than saving it.
- A conversation is saved as it went. Each turn has what the researcher wrote and attached, then what the lead did, in order: what it said, the code it ran with what it printed and the figures it drew, the files it made, and the tools it called with what they gave back. Each time the lead brought in the team, the call links to the team's session, which is added after the conversation as a meeting is. A conversation that is still going is saved as far as it has got, and saving it changes nothing in what it saved.
- A conversation can also be saved as a Jupyter notebook, as Biomni's agent works: what the researcher and the lead wrote are Markdown cells, each piece of code the lead ran is a code cell holding what it printed, the value it came to, and the figures it drew as its outputs, and what else the lead called is told in Markdown. R and shell code is a cell that starts with `%%R` (which needs rpy2) or `%%bash`. `chat_notebook` returns the notebook rather than saving it.
- A conversation is read from its folder under the workspace's `chats/`, so `save_chat_html`, `save_chat_pdf`, and `save_chat_notebook` take that folder and save `conversation.html`, `conversation.pdf`, or `conversation.ipynb` in it unless told where. The figures are read from the session's directory, which is where the conversation says it was; if the folder has been moved, `files_dir` says where it is now.
