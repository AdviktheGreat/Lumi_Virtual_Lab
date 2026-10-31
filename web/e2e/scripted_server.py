"""The server the interface's end-to-end tests run against, with a script where the model would be.

It is the real server, with the built pages, a workspace made for the run, and a fixed token, whose lead answers
from a script: no key is needed, and every run says the same. What it says depends on what it is asked:

- "fail:" anywhere in the message makes the model fail, which is how a turn that ends in an error is tested.
  "fail:key" has it fail as a provider does that will not accept the key.
- "slow:" anywhere in the message makes it write a long reply, slowly, so that a turn can be followed or stopped
  while it is still going.
- "markdown:" anywhere in the message makes it answer with a page of Markdown, with what a page must not trust in it,
  once it has done what else the message asks, so that the figure the page names can be one the code drew.
- "wide:" anywhere in the message makes it answer with a table, and with lines of code, that run past the width of the
  page, so that what scrolls in a reply can be reached from a keyboard.
- "code:" and a word (hello, error, two, plot, long, big, slow, files) make it run code in the conversation's session
  first, as the word says, and answer once the code has run. "tool:unknown" makes it call a tool it does not have, and
  "tool:resources" makes it look for resources, and choose the know-how documents there are. "tool:files" makes it
  look at the files attached to the conversation, with the library's own tools for that, and "tool:offered" makes it
  answer with the names of the tools the model was offered. "lab:team" makes it bring
  in the team for a round of discussion, and "lab:consult" ask one scientist, whose replies the script writes too.
  "lab:code" brings in one scientist who runs code in the session, if the conversation has one, before they reply.
  "lab:slow" brings in one scientist who writes a long reply, slowly, so that a session can be followed as it goes.
- A message given with a command, such as /ask, is answered as it is without one, except that /review has it bring in the
  Scientific Critic, that /lab has it hold the session that was asked for, with the agenda below (and "lab:skip" has it
  not), and that what the command tells the lead is not repeated in the reply that repeats the question.
- "mcp:" and a word (echo, count, both, order, confirm, signed, gated) make it call the tools of the MCP servers that
  the tests of mcp/ set up, which are the test server of tests/mcp_test_server.py under the names genes, vault, and
  gate.
- Papers that are read are answered with the tasks, databases, and software their text names: a paper that names
  DESeq2 is found to use RNA-seq differential expression, one that names Scanpy single-cell clustering, and one that
  names neither the first. "slow:" in a paper's text makes reading it take a while, so that the work can be followed or
  stopped, and "fail:" makes reading it fail. A function asked for is written, whatever it is for.
- Benchmarks' questions are answered from stand-ins for their files, whose questions the script answers right or wrong
  by their number, so that every run scores the same: of LAB-Bench's, the even ones right, and of Biomni-Eval1's, what
  its tasks' stand-ins make of one answer each. "pause:" in a question makes answering it take a while, so that a run
  can be followed or stopped.
- A project's lead chooses an Immunologist, plans two tasks, holds one meeting with them, and then puts its answer to
  the critic, who agrees, so that every project goes the same way. "hold:" in its goal makes each decision take a while,
  so that the work can be followed or stopped, "fail:" makes it fail, and "object:" has the critic not accept the first
  answer.
- Anything else is answered with a short reply that repeats the question.

A conversation is saved as a PDF by a stand-in that puts the page in a file that starts as a PDF does, so that no
WeasyPrint is needed and every run says the same. "pdf:unavailable" anywhere in the conversation has it fail as it does
where WeasyPrint is not installed.

    python e2e/scripted_server.py --port 8799 --static-dir out

With --setup-control-port, Docker and the place the data lake is fetched from are stand-ins too (see
tests/setup_fakes.py), which a test arranges and looks at by POSTing JSON to that port; see FakeSetup.control.

The keys a test gives are kept in a keychain that is a dictionary in this process, called the Test Keychain, so that the
machine's own is never touched. --no-keychain has the server keep none, as one on a machine without a keychain does.
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import webbrowser
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

import httpx  # noqa: E402
import openai  # noqa: E402
from conftest import (  # noqa: E402
    FakeClient,
    FakeCompletions,
    FakeStream,
    make_usage,
    parsed_response,
    stream_chunks,
    text_response,
)
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall  # noqa: E402
from openai.types.chat.chat_completion import ChatCompletion, Choice  # noqa: E402
from openai.types.chat.chat_completion_message_tool_call import Function  # noqa: E402

from setup_fakes import Bucket, FakeDocker  # noqa: E402
from test_benchmarks import benchmark_files, parquet_bytes, sha256  # noqa: E402
from test_papers import database, findings, package, task  # noqa: E402
from test_planning import found, plan, review, roster, step  # noqa: E402

from virtual_lab.benchmarks import MultipleChoiceOutput  # noqa: E402
from virtual_lab.constants import BENCHMARK_FILES, MCP_AUTH_DIRECTORY_VARIABLE  # noqa: E402
from virtual_lab.environment import DATA_LAKE  # noqa: E402
from virtual_lab.export import PDFExportError  # noqa: E402
from virtual_lab import openrouter  # noqa: E402
from virtual_lab.memory import Findings  # noqa: E402
from virtual_lab.papers import PaperFindings  # noqa: E402
from virtual_lab.planning import NextStep, PlanTask, ResearchPlan, Review  # noqa: E402
from virtual_lab.schemas import TeamRoster  # noqa: E402
from virtual_lab.server import app as server_app  # noqa: E402
from virtual_lab.server import benchmarks as benchmark_runs  # noqa: E402
from virtual_lab.server import serve  # noqa: E402
from virtual_lab.server.keychain import Keychain  # noqa: E402
from virtual_lab.server.workspace import Workspace  # noqa: E402

TOKEN = "e2e-token"
TEST_MODEL = "gpt-4o-2024-08-06"

# Seconds between the words of a reply, and how many words the long one has
WORD_DELAY = 0.04
LONG_REPLY_WORDS = 250

# The largest file a message can be sent with, which is small, so that one too large is quick to make
MAX_UPLOAD_BYTES = 20 * 1024

# What a paper is found to be about, by a word in its text, and how long a paper that says "slow:" takes to read
PAPER_TASKS = (
    ("RNA-seq differential expression with DESeq2", "DESeq2"),
    ("Single-cell clustering with Scanpy", "Scanpy"),
)
PAPER_DELAY = 2.0

# How long answering a question that says "pause:" takes, and the stand-in for Humanity's Last Exam, whose questions
# say it
BENCHMARK_DELAY = 1.5
HLE_FILE = "hle/test_sampled_biology_medicine.parquet"
HLE_ROWS = [
    {
        "id": f"h{number}",
        "question": f"pause: Which of these is {name}? Answer Choices: A. the first B. the second",
        "image": "data:image/png;base64,AAAA" if number == 3 else "",
        "answer": answer,
        "answer_type": "multipleChoice",
        "category": "Biology/Medicine",
    }
    for number, (name, answer) in enumerate(
        [
            ("a ligase", "B. the second"),
            ("a helicase", "B. the second"),
            ("a kinase", "A. the first"),
            ("a drawn one", "B. the second"),
        ]
    )
]

# What Biomni-Eval1's tasks are answered with, whatever is asked: the answer of the first question of each task, which
# is wrong for the second question of crispr_delivery
EVAL1_ANSWERS = {
    "CrisprDeliveryOutput": {"choice": "e"},
    "GeneOutput": {"gene": "HNF1A"},
    "VariantOutput": {"variant": "rs4253311"},
    "RareDiseaseOutput": {"disease_name": "Gordon syndrome", "OMIM_ID": "114300"},
    "PatientGeneOutput": {"causal_gene": ["ENSG1"]},
}

# What a project is scripted to do: its plan, what its one meeting finds, its answer, and how long each decision takes
# when its goal says "hold:"
PROJECT_TASKS = ("Compare how strongly the two nanobodies bind KP.3", "Check that the comparison holds")
PROJECT_FINDING = "Nanobody A binds KP.3 more strongly than nanobody B."
PROJECT_ANSWER = "Nanobody A binds KP.3 better, as the comparison shows."
PROJECT_OBJECTION = "Show the affinities that were measured."
PROJECT_DELAY = 1.5
PROJECT_SCHEMAS = (TeamRoster, ResearchPlan, NextStep, Findings, Review)

# What a function that is asked for is written as
FUNCTION_CODE = """```python
def {name}(path: str) -> int:
    \"\"\"Counts the reads in a file.

    Args:
        path: The file.
    \"\"\"
    return 1
```"""


# Code that draws a figure and makes a file, without matplotlib: a stand-in for the module, which saves a picture
PLOT_CODE = """\
import struct, sys, types, zlib

def png(width, height):
    rows = b"".join(
        b"\\x00" + b"".join(bytes((x * 255 // width, y * 255 // height, 180)) for x in range(width))
        for y in range(height)
    )
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    data = chunk(b"IDAT", zlib.compress(rows))
    return b"\\x89PNG\\r\\n\\x1a\\n" + chunk(b"IHDR", header) + data + chunk(b"IEND", b"")

class Figure:
    def savefig(self, path, **options):
        with open(path, "wb") as file:
            file.write(png(160, 100))

pyplot = types.ModuleType("matplotlib.pyplot")
shown = [1]
pyplot.get_fignums = lambda: list(shown)
pyplot.figure = lambda number=None: Figure()
pyplot.close = lambda figure=None: shown.clear()
sys.modules["matplotlib"] = types.ModuleType("matplotlib")
sys.modules["matplotlib.pyplot"] = pyplot

with open("results.csv", "w") as file:
    file.write("gene,score\\nTP53,0.91\\n")
print("drawn")
"""

# What "wide:" answers with: a table of ten columns whose cells cannot be broken, a line of code that is wider than any
# window, and a line that is wider than the page is with the sidebar beside it and narrower than it is without
WIDE_REPLY = """\
A table with more columns than a page has room for:

| Sample | Transcript | Variant | Position | Depth | Quality | Strand | Allele | Source | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ENSG00000141510.18 | ENST00000269305.9 | NM_000546.6:c.215C>G | chr17:7661779-7687550 | 1021.5x | Q38.25 | forward | rs1042522 | ClinVar-2024-03 | pathogenic |

A line of code that no window is wide enough for:

```python
print("%s")
```

And one that fits a wide window and not a narrow one:

```python
total = compute_total(alpha, beta, gamma, delta, epsilon, zeta, eta, theta)
```
""" % " ".join(f"word{number}" for number in range(1, 41))

TEAM_AGENDA = "Design a nanobody against TP53."
# What "code:files" writes, which is one of each of what the panel of files shows differently: a long table, a wide one
# divided by tabs, a log longer than is read to show it, a file that is not text, and an empty one
FILES_CODE = r"""
import os
os.makedirs("tables", exist_ok=True)
os.makedirs("logs", exist_ok=True)
with open("tables/long.csv", "w") as handle:
    handle.write("gene,score,note\n")
    for number in range(300):
        handle.write(f'G{number:03d},{number / 100:.2f},"row {number}, with a comma"\n')
with open("tables/wide.tsv", "w") as handle:
    handle.write("\t".join(f"c{number}" for number in range(50)) + "\n")
    handle.write("\t".join(str(number) for number in range(50)) + "\n")
with open("logs/big.log", "w") as handle:
    for number in range(8000):
        handle.write(f"line {number:05d} " + "x" * 30 + "\n")
with open("blob.bin", "wb") as handle:
    handle.write(bytes([137, 80, 0, 1, 2, 3]))
open("empty.txt", "w").close()
print("files written")
""".lstrip()
# How many words a scientist writes when the session is to be slow
LAB_SLOW_WORDS = 120
# What a scientist runs when the session they are in is asked for it, which makes a file for the page to list
LAB_CODE = 'print("lab code ran")\nopen("lab_notes.txt", "w").write("epitope: DNA-binding domain\\n")'

LONG_CODE = "\n".join([*(f"step_{number} = {number} * 2" for number in range(1, 31)), "print('ran', step_30)"])

# What the lead does for a message with "code:" or "tool:" in it: each step is what it says, the tool it calls, and
# what it calls it with
SCENARIOS: dict[str, list[tuple[str, str, dict[str, Any]]]] = {
    "code:hello": [("Let me run that.", "run_code", {"code": 'print("hello from the session")'})],
    "code:error": [("Trying it.", "run_code", {"code": 'print("\\x1b[31mabout to fail\\x1b[0m")\n1 / 0'})],
    "code:two": [
        ("First, one thing.", "run_code", {"code": 'x = 20\nprint("first", x)'}),
        ("Now the next.", "run_code", {"code": 'print("second", x + 22)'}),
    ],
    "code:plot": [("Drawing it.", "run_code", {"code": PLOT_CODE})],
    "code:long": [("A longer script.", "run_code", {"code": LONG_CODE})],
    "code:big": [
        (
            "That prints a lot.",
            "run_code",
            {"code": 'for number in range(2500):\n    print(f"row {number:05d} " + "x" * 40)'},
        )
    ],
    "code:slow": [("This will take a moment.", "run_code", {"code": "import time\ntime.sleep(3)\nprint('slept')"})],
    "code:files": [("Writing some files.", "run_code", {"code": FILES_CODE})],
    "mcp:echo": [("Echoing it.", "genes_echo", {"text": "ab"})],
    "mcp:count": [("Counting.", "genes_count", {})],
    "mcp:both": [("Counting first.", "genes_count", {}), ("Then echoing.", "genes_echo", {"text": "cd"})],
    "mcp:order": [("Placing the order.", "genes_order", {})],
    "mcp:confirm": [("Checking first.", "genes_confirm", {})],
    "mcp:signed": [("Echoing it, signed in.", "vault_echo", {"text": "ef"})],
    "mcp:gated": [("Echoing it, through the gate.", "gate_echo", {"text": "gh"})],
    "tool:unknown": [("", "mystery_tool", {"target": "TP53"})],
    "tool:resources": [("Looking for what suits it.", "find_resources", {"task": "Score a gene's expression"})],
    "tool:files": [
        ("Seeing what was attached.", "data_files", {}),
        ("Looking inside it.", "inspect_data_file", {"filename": "uploads/counts.csv"}),
    ],
    "/review command": [
        (
            "Asking the Critic to look.",
            "convene_team",
            {"agenda": TEAM_AGENDA, "members": ["Scientific Critic"], "rounds": 1},
        )
    ],
    "they want a team session on this": [("Bringing in the team you chose.", "convene_team", {"agenda": TEAM_AGENDA})],
    "to work on this on their own": [
        ("Asking the scientist you chose.", "consult", {"agenda": "Is a nanobody against TP53 immunogenic?"})
    ],
    "lab:team": [
        (
            "Bringing in the team.",
            "convene_team",
            {"agenda": TEAM_AGENDA, "members": ["Immunologist", "Scientific Critic"], "rounds": 1},
        )
    ],
    "lab:code": [
        (
            "Bringing in a scientist who can check.",
            "convene_team",
            {"agenda": f"lab:code {TEAM_AGENDA}", "members": ["Immunologist"], "rounds": 1},
        )
    ],
    "lab:slow": [
        (
            "Bringing in a scientist who takes their time.",
            "convene_team",
            {"agenda": f"slow: {TEAM_AGENDA}", "members": ["Immunologist"], "rounds": 1},
        )
    ],
    "lab:consult": [
        (
            "Asking one scientist.",
            "consult",
            {"member": "Immunologist", "agenda": "Is a nanobody against TP53 immunogenic?", "rounds": 1},
        )
    ],
}

# What the scientists say in a team session, by who they are: each says the same wherever it is asked
LAB_REPLIES = {
    "Principal Investigator": "Let us begin: which part of TP53 should a nanobody bind?",
    "Immunologist": "As the Immunologist, I would target the conserved DNA-binding epitope.",
    "Scientific Critic": "As the Scientific Critic, I ask what shows that the epitope is exposed.",
}
LAB_SUMMARY = "Summary: target the conserved DNA-binding epitope, and check that it is exposed."

# What the lead answers when it is asked which resources suit a task, which is what a search for them asks
RETRIEVAL_REPLY = "TOOLS: []\nDATA_LAKE: []\nLIBRARIES: []\nKNOW_HOW: [0, 1]"

MARKDOWN_REPLY = """\
## Findings

A paragraph with **bold**, *italic*, `inline code`, and [a paper](https://example.com/paper).

- first point
- second point

| Gene | Score |
| --- | --- |
| TP53 | 0.91 |

```python
print("hello")
```

```nonsense
plain text here
```

```
no language here
```

![The figure](plots/figure_1.png)

![A tracker](https://example.com/pixel.png)

<script>window.__pwned = true</script>

[Not a link](javascript:window.__pwned=true)

[A place here](#findings) and [an email](mailto:lab@example.com)
"""


class SlowStream(FakeStream):
    """A stream that takes its time over each chunk, as a model does."""

    def __init__(self, chunks: list[Any], delay: float) -> None:
        super().__init__(chunks)
        self.delay = delay

    def __iter__(self) -> Iterator[Any]:
        for chunk in self.chunks:
            time.sleep(self.delay)
            yield chunk


def asked(messages: list[dict[str, Any]]) -> str:
    """What the researcher last said, which is what the script answers."""
    for message in reversed(messages):
        if message["role"] == "user":
            content = message["content"]

            return content if isinstance(content, str) else ""

    return ""


def tool_results(messages: list[dict[str, Any]]) -> int:
    """How many of its tool calls the lead has been answered, since the researcher last spoke."""
    answered = 0
    for message in reversed(messages):
        if message["role"] == "user":
            break
        if message["role"] == "tool":
            answered += 1

    return answered


def scientist_of(kwargs: dict[str, Any]) -> str | None:
    """Who a request is for when it is a scientist's, in a team session, rather than the lead's."""
    tools = {tool["function"]["name"] for tool in kwargs.get("tools") or []}
    if tools & {"convene_team", "consult"}:
        return None
    system = next((message["content"] for message in kwargs["messages"] if message["role"] == "system"), "")
    # The lead is the one who is talking with the researcher, which it is when it has no tools too, as it has for /ask
    if isinstance(system, str) and "You are talking with a human researcher" in system:
        return None
    found = re.match(r"You are an? ([^.]+)\.", system) if isinstance(system, str) else None

    return found.group(1) if found else None


def offered(kwargs: dict[str, Any]) -> list[str]:
    """The names of the tools a request offers the model."""
    return sorted(tool["function"]["name"] for tool in kwargs.get("tools") or [])


def runs_code(title: str, kwargs: dict[str, Any]) -> bool:
    """Whether a scientist is to run code before they reply: when the agenda says so, and they have a tool to."""
    tools = {tool["function"]["name"] for tool in kwargs.get("tools") or []}
    said = " ".join(str(message["content"]) for message in kwargs["messages"] if message["role"] != "system")

    return title == "Immunologist" and "lab:code" in said and "run_code" in tools


def lab_reply(title: str, messages: list[dict[str, Any]]) -> str:
    """What a scientist says in a team session: the lead who has heard the others sums up."""
    said = " ".join(str(message["content"]) for message in messages if message["role"] != "system")
    if title == "Principal Investigator" and "As the Immunologist" in said:
        return LAB_SUMMARY
    if title == "Immunologist" and "slow:" in said:
        return " ".join(f"point{number}" for number in range(1, LAB_SLOW_WORDS + 1))

    return LAB_REPLIES.get(title, f"As the {title}, I have nothing to add.")


def choice_for(question: str) -> str:
    """The letter the script answers a multiple choice question with. LAB-Bench's stand-ins have their right option
    written "right N" and a wrong one "wrong N.0", and are answered right when N is even, and wrong when it is odd. The
    others are answered B."""
    found = re.search(r"Question (\d+)\?", question)
    if found is None:
        return "B"
    number = int(found.group(1))
    text = f"right {number}" if number % 2 == 0 else f"wrong {number}.0"
    option = re.search(rf"^([A-Z])\.{re.escape(text)}$", question, re.MULTILINE)

    return option.group(1) if option else "B"


def benchmark_output(schema: Any, question: str) -> Any:
    """The answer the script reads out of an attempt, in the schema of the question's benchmark."""
    if schema is MultipleChoiceOutput:
        return MultipleChoiceOutput(choice=choice_for(question))

    return schema.model_validate(EVAL1_ANSWERS[schema.__name__])


def paper_findings(text: str) -> PaperFindings:
    """What a paper is found to use, from the words in its text."""
    names = [name for name, word in PAPER_TASKS if word in text] or [PAPER_TASKS[0][0]]

    return findings([task(name) for name in names], [database("GEO")], [package("STAR")])


def project_decision(number: int) -> NextStep:
    """What the lead decides in a round: one meeting with the Immunologist, and then to finish."""

    def tasks(done: int) -> list[PlanTask]:
        return [
            PlanTask(task=task, status="done" if index < done else "to do") for index, task in enumerate(PROJECT_TASKS)
        ]

    if number == 1:
        return step(
            "individual_meeting",
            plan=tasks(0),
            participants=["Immunologist"],
            agenda="Compare how strongly the two nanobodies bind KP.3.",
            agenda_questions=["Which has the lower dissociation constant?"],
            rationale="The comparison is the first task.",
            progress="Nothing has been established yet.",
        )

    return step(
        "finish",
        plan=tasks(2),
        findings=["F1"],
        rationale="The comparison is done, and it holds.",
        progress="Nanobody A binds better.",
        answer=PROJECT_ANSWER,
    )


def project_response(schema: Any, kwargs: dict[str, Any]) -> Any:
    """What the lead and the critic say, as a project asks it, from what is asked of them: the team, the plan, the next
    step, the findings of a meeting, and the critic's review."""
    text = " ".join(str(message["content"]) for message in kwargs["messages"] if message["role"] != "system")
    if "fail:" in text:
        raise RuntimeError("The scripted model failed, as it was asked to")
    if schema is TeamRoster:
        return roster("Immunologist")
    if schema is ResearchPlan:
        return plan(*PROJECT_TASKS)
    if schema is Findings:
        return found(PROJECT_FINDING)
    if schema is Review:
        # The first answer is not accepted when the goal says so, and what is said of the answer after is its objection
        met = "object:" not in text or "did not accept" in text
        return review(met, *([] if met else [PROJECT_OBJECTION]))
    if "hold:" in text:
        time.sleep(PROJECT_DELAY)
    number = re.search(r"This is round (\d+) of the project", text)

    return parsed_response(parsed=project_decision(int(number.group(1)) if number else 1))


def function_named(kwargs: dict[str, Any]) -> str | None:
    """The name of the function a request asks the model to write, if it asks for one."""
    system = next((message["content"] for message in kwargs["messages"] if message["role"] == "system"), "")
    found = re.search(r"one function named\s+`(\w+)`", system) if isinstance(system, str) else None

    return found.group(1) if found else None


def function_code(name: str) -> str:
    return FUNCTION_CODE.format(name=name)


def scenario_for(question: str) -> list[tuple[str, str, dict[str, Any]]] | None:
    if "lab:skip" in question:
        return None

    return next((steps for word, steps in SCENARIOS.items() if word in question), None)


def call_response(narration: str, name: str, arguments: dict[str, Any], call_id: str) -> ChatCompletion:
    """A completion in which the model says something and calls a tool."""
    return ChatCompletion(
        id="scripted",
        model=TEST_MODEL,
        object="chat.completion",
        created=0,
        usage=make_usage(),
        choices=[
            Choice(
                finish_reason="tool_calls",
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    content=narration or None,
                    tool_calls=[
                        ChatCompletionMessageToolCall(
                            id=call_id,
                            type="function",
                            function=Function(name=name, arguments=json.dumps(arguments)),
                        )
                    ],
                ),
            )
        ],
    )


def reply_to(question: str) -> str:
    # What a command tells the lead goes after what the researcher wrote, and is not what they asked
    question = question.split("\n\nThe researcher gave the /")[0]
    if "USER QUERY:" in question and "AVAILABLE TOOLS:" in question:
        return RETRIEVAL_REPLY
    if "markdown:" in question:
        return MARKDOWN_REPLY
    if "slow:" in question:
        return " ".join(f"word{number}" for number in range(1, LONG_REPLY_WORDS + 1))

    return (
        f"You asked: {question}\n\nThis answer is from a script, so that the interface can be tested without a model."
    )


class ScriptedCompletions(FakeCompletions):
    def __init__(self, delay: float) -> None:
        super().__init__()
        self.delay = delay

    def create(self, **kwargs: Any) -> Any:
        question = asked(kwargs["messages"])
        if "fail:key" in question:
            request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
            raise openai.AuthenticationError(
                "Error code: 401 - Incorrect API key provided", response=httpx.Response(401, request=request), body=None
            )
        if "fail:flag" in question:
            # As OpenAI's safety check stops a reply that is being streamed: an error with no status of its own
            raise openai.APIError(
                "This content was flagged for possible biological risk. "
                "If this seems wrong, try rephrasing your request.",
                request=httpx.Request("POST", "https://api.example.test/v1/chat/completions"),
                body=None,
            )
        if "fail:" in question:
            raise RuntimeError("The scripted model failed, as it was asked to")
        searching = "USER QUERY:" in question and "AVAILABLE TOOLS:" in question
        scientist = None if searching else scientist_of(kwargs)
        steps = None if searching or scientist is not None else scenario_for(question)
        done = tool_results(kwargs["messages"])
        written = function_named(kwargs)
        if written is not None:
            response = text_response(function_code(written))
        elif "pause:" in question or "[ANSWER] and [/ANSWER]" in question:
            if "pause:" in question:
                time.sleep(BENCHMARK_DELAY)
            letter = choice_for(question)
            response = text_response(f"Working through the options, the answer is [ANSWER]{letter}[/ANSWER].")
        elif steps is not None and done < len(steps):
            narration, name, arguments = steps[done]
            response = call_response(narration, name, arguments, f"call_{done + 1}")
        elif scientist is not None and runs_code(scientist, kwargs) and done == 0:
            response = call_response("Let me check that.", "run_code", {"code": LAB_CODE}, "call_lab_1")
        elif scientist is not None:
            response = text_response(lab_reply(scientist, kwargs["messages"]))
        elif steps is not None and "markdown:" in question:
            response = text_response(MARKDOWN_REPLY)
        elif steps is not None:
            response = text_response(f"That is done: {len(steps)} step{'s' if len(steps) != 1 else ''} ran.")
        elif "wide:" in question:
            response = text_response(WIDE_REPLY)
        elif "tool:offered" in question:
            response = text_response("Offered: " + " ".join(offered(kwargs)))
        else:
            response = text_response(reply_to(question))
        if kwargs.get("stream"):
            include_usage = bool((kwargs.get("stream_options") or {}).get("include_usage"))

            return SlowStream(stream_chunks(response, include_usage), self.delay)

        return response

    def parse(self, **kwargs: Any) -> Any:
        schema = kwargs["response_format"]
        if schema.__module__ == "virtual_lab.benchmarks":
            # What the answer is read from is the question, which the request that reads it gives as what it is for
            system = next(str(message["content"]) for message in kwargs["messages"] if message["role"] == "system")

            return parsed_response(benchmark_output(schema, system))
        if schema in PROJECT_SCHEMAS:
            return project_response(schema, kwargs)
        if schema is not PaperFindings:
            return super().parse(**kwargs)
        text = " ".join(str(message["content"]) for message in kwargs["messages"] if message["role"] == "user")
        if "slow:" in text:
            time.sleep(PAPER_DELAY)
        if "fail:" in text:
            raise RuntimeError("The scripted model failed to read the paper, as it was asked to")

        return parsed_response(paper_findings(text))


class ScriptedClient(FakeClient):
    def __init__(self, delay: float = WORD_DELAY) -> None:
        super().__init__()
        self.chat = type("Chat", (), {"completions": ScriptedCompletions(delay)})()


# How big each file of the data lake is in the stand-in for the place it is fetched from, which is big enough for the
# part of it that has been fetched, when a fetch is held halfway, to be a size to read
DATA_LAKE_FILE_BYTES = 10 * 1024


class FakeSetup:
    """Docker and the release the data lake is fetched from, as stand-ins, and what a test does to them.

    :param directory: Where the stand-in for Docker is kept.
    :param workspace: The workspace of the server, whose data lake is what is fetched into.
    """

    def __init__(self, directory: Path, workspace: Path) -> None:
        self.docker = FakeDocker(directory)
        self.bucket = Bucket()
        self.files = {name: bytes(range(256)) * (DATA_LAKE_FILE_BYTES // 256) for name in DATA_LAKE}
        self.bucket.files = dict(self.files)
        self.lake = Workspace(workspace).data_lake_dir

    def settle(self) -> None:
        """Lets everything that is held go on, so that every job that is at work can end."""
        for gate in self.bucket.gates.values():
            gate.set()
        self.docker.release()

    def reset(self) -> None:
        """Puts everything as it was when the server began: Docker is up and has no image, and no file is fetched.
        Nothing may be at work, since what is would go on into what is put as it was."""
        self.bucket.gates.clear()
        self.bucket.files = dict(self.files)
        self.bucket.requests.clear()
        for name in ("started", "pid", "builds.jsonl"):
            (self.docker.directory / name).unlink(missing_ok=True)
        fresh = FakeDocker(self.docker.directory)
        self.docker.state = fresh.state
        self.docker.save()
        (self.docker.directory / "release").unlink(missing_ok=True)
        shutil.rmtree(self.lake, ignore_errors=True)

    def control(self, order: dict[str, Any]) -> dict[str, Any]:
        """Does what a test asks, each of these that it names, and says what it can be asked of.

        - "settle": lets everything that is held go on, which ends the jobs that are at work, once they are done.
        - "reset": puts everything as it began, which is done when no job is at work.
        - "docker": changes what Docker answers, as FakeDocker.configure does.
        - "build": changes how a build goes, as FakeDocker.build does.
        - "release": lets a build that is waiting end.
        - "hold": the names of files of the data lake whose fetch is held halfway, until they are named in "let".
        - "let": the names of files whose fetch goes on.
        - "withhold": the names of files that the release does not have, which makes fetching them fail.
        - "present": the names of files to put in the data lake as if they were fetched already.
        - "state": asks, and is answered with "builds" begun, whether a build "started", and the "images" built.
        """
        if order.get("settle"):
            self.settle()
        if order.get("reset"):
            self.reset()
        if "docker" in order:
            self.docker.configure(**order["docker"])
        if "build" in order:
            self.docker.build(**order["build"])
        for name in order.get("hold", []):
            self.bucket.gate(name)
        for name in order.get("let", []):
            self.bucket.gates[name].set()
        for name in order.get("withhold", []):
            del self.bucket.files[name]
        for name in order.get("present", []):
            self.lake.mkdir(parents=True, exist_ok=True)
            (self.lake / name).write_bytes(self.files[name])
        if order.get("release"):
            self.docker.release()

        return {
            "builds": self.docker.builds,
            "started": self.docker.started,
            "images": self.docker.images,
            "requests": list(self.bucket.requests),
        }


def serve_control(setup: FakeSetup, port: int) -> None:
    """Listens on a port for a test to arrange the stand-ins, which it does by POSTing the JSON control takes."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.dumps(setup.control(json.loads(self.rfile.read(length) or b"{}"))).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()


class MemoryKeyring:
    """Stands in for a backend of the keyring package, and keeps what it is given only as long as the server runs."""

    def __init__(self) -> None:
        self.kept: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, name: str) -> str | None:
        return self.kept.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        self.kept[(service, name)] = value

    def delete_password(self, service: str, name: str) -> None:
        del self.kept[(service, name)]


def stand_in_benchmark_files() -> None:
    """Pins small stand-ins for the benchmarks' files in place of the real ones, and has fetching the files put the
    stand-ins where they are kept, so that nothing is fetched."""
    files = benchmark_files()
    files[HLE_FILE] = parquet_bytes(HLE_ROWS)
    for name, data in files.items():
        BENCHMARK_FILES[name] = sha256(data)

    def download(directory: Path) -> None:
        for name, data in files.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    benchmark_runs.download_benchmarks = download


def stand_in_pdf(page: str) -> bytes:
    if "pdf:unavailable" in page:
        raise PDFExportError("Making a PDF needs WeasyPrint. (ImportError: the stand-in is told to fail)")

    return b"%PDF-1.7\n% made by the stand-in\n" + page.encode("utf-8")


def stand_in_openrouter_models(*arguments: Any, **keywords: Any) -> list[openrouter.OpenRouterModel]:
    """What OpenRouter lists, so that no test asks it: a router, and a few models with different prices."""

    def listed(name: str, label: str, prompt: str, completion: str, context: int) -> dict[str, Any]:
        return {
            "id": name,
            "name": label,
            "context_length": context,
            "architecture": {"output_modalities": ["text"]},
            "pricing": {"prompt": prompt, "completion": completion},
            "supported_parameters": ["tools"],
        }

    return openrouter.models_from(
        {
            "data": [
                listed("openrouter/auto", "Auto Router", "-1", "-1", 2_000_000),
                listed(
                    "anthropic/claude-sonnet-4.5", "Anthropic: Claude Sonnet 4.5", "0.000003", "0.000015", 1_000_000
                ),
                listed("google/gemini-2.5-pro", "Google: Gemini 2.5 Pro", "0.00000125", "0.00001", 1_048_576),
                listed("meta-llama/llama-3.3-70b-instruct:free", "Meta: Llama 3.3 70B (free)", "0", "0", 131_072),
            ]
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="The server the interface's end-to-end tests run against.")
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument(
        "--setup-control-port",
        type=int,
        default=None,
        help="stand in for Docker and where the data lake is fetched from, arranged by what is POSTed to this port",
    )
    parser.add_argument("--static-dir", default=str(ROOT / "web" / "out"))
    parser.add_argument("--word-delay", type=float, default=WORD_DELAY)
    parser.add_argument("--max-upload-bytes", type=int, default=MAX_UPLOAD_BYTES)
    parser.add_argument("--no-keychain", action="store_true", help="keep the keys given only until the server stops")
    options = parser.parse_args()

    server_app.make_pdf = stand_in_pdf
    openrouter.fetch_models = stand_in_openrouter_models
    stand_in_benchmark_files()
    workspace = Path(tempfile.mkdtemp(prefix="virtual-lab-e2e-"))
    # The sign-ins to MCP servers are kept away from those of the person running the tests, and no browser is opened
    # for one: a test follows the link the page shows, as a person would
    sign_ins = Path(tempfile.mkdtemp(prefix="virtual-lab-e2e-sign-ins-"))
    os.environ[MCP_AUTH_DIRECTORY_VARIABLE] = str(sign_ins)
    webbrowser.open = lambda *arguments, **keywords: False  # type: ignore[assignment]
    setup = None
    stand_ins: dict[str, Any] = {}
    if options.setup_control_port is not None:
        setup = FakeSetup(workspace.parent / f"{workspace.name}-docker", workspace)
        serve_control(setup, options.setup_control_port)
        stand_ins = {"docker_command": setup.docker.command, "release_url": setup.bucket.url}
    try:
        serve(
            workspace=workspace,
            port=options.port,
            token=TOKEN,
            static_dir=options.static_dir,
            open_browser=False,
            check_keys=False,
            client=ScriptedClient(options.word_delay),
            max_upload_bytes=options.max_upload_bytes,
            keychain=False if options.no_keychain else Keychain(MemoryKeyring(), "Test Keychain"),
            **stand_ins,
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(sign_ins, ignore_errors=True)
        if setup is not None:
            shutil.rmtree(setup.docker.directory, ignore_errors=True)
            setup.bucket.close()


if __name__ == "__main__":
    main()
