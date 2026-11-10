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
  answer with the names of the tools the model was offered, and "instructions:" has it answer with the instructions of
  a program of its own that it was given, or say that it was given none, and "campaign:" with the name and goal of the
  campaign that its program is one of, or say that it is one of none. "lab:team" makes it bring
  in the team for a round of discussion, and "lab:consult" ask one scientist, whose replies the script writes too.
  "lab:code" brings in one scientist who runs code in the session, if the conversation has one, before they reply.
  "lab:slow" brings in one scientist who writes a long reply, slowly, so that a session can be followed as it goes.
- "skill:build:" and a name make it write a skill of that name in the session's new_skills/ with code, and call
  save_skill for it, as it does for a program that builds a skill, and "skill:save:" and a name make it call save_skill
  for that folder alone, as it does once the researcher has agreed, and "skill:use:" and a name make it read that skill
  with activate_skill, as it does for a message that is given with the skill, which it is told to read first.
- A message given with a command, such as /ask, is answered as it is without one, except that /review has it bring in the
  Scientific Critic, that /lab has it hold the session that was asked for, with the agenda below (and "lab:skip" has it
  not), and that what the command, or the skill a message is given with, tells the lead is not repeated in the reply
  that repeats the question.
- "mcp:" and a word (echo, count, both, order, confirm, signed, gated) make it call the tools of the MCP servers that
  the tests of mcp/ set up, which are the test server of tests/mcp_test_server.py under the names genes, vault, and
  gate.
- Papers that are read are answered with the tasks, databases, and software their text names: a paper that names
  DESeq2 is found to use RNA-seq differential expression, one that names Scanpy single-cell clustering, and one that
  names neither the first. "slow:" in a paper's text makes reading it take a while, so that the work can be followed or
  stopped, and "fail:" makes reading it fail. A function asked for is written, whatever it is for.
- The paper of a PaperAgent is read a chunk at a time, and what a chunk is answered with is what its sentences say: a
  number after "AUROC of" is a claim, "Seurat v4.3" is software, "GSE" and digits is a dataset of GEO, an address at
  github.com is a link to code, "only tested on mouse" is a limitation and a species, each with its sentence as its
  quote. "fabricate:" in a chunk adds a claim whose quote is not in the paper, which is thrown away, "slow:" makes
  reading it take a while, "refuse:" has the model refuse it, and "fail:" makes it fail.
- The text of a PaperAgent whose paper is a DOI or a link is given by stand-ins for Europe PMC and the web, which give a
  paper that says what the one above does, under the DOI or the link. "closed" in a DOI or a link makes it a paper that
  cannot be had, as one is that is not open access or is behind a login, and "slow" makes it take a while to be got.
- The code of a PaperAgent is given by a stand-in for Git, which writes a small project for any address, at a commit
  that is the same for the same address and ref: one with a README that shows how it is used, an MIT license, pinned
  requirements, a tutorial, and a test, which a GPU is used by if there is one. "gpu" in the address makes it one that
  needs a GPU and has a license for non-commercial use only, and no tutorial, "slow" makes fetching it take a while,
  "missing" makes it a project that is not there, and "huge" makes it more than the most that was asked to be fetched,
  and "bare" makes it a project that no file says how to install.
- The environment of a PaperAgent's code is built by a stand-in for Docker, which says what the build prints and keeps
  the images there are by their names. What it does is from the agent's id, which is made of its title: "slow" makes
  building take a while, so that it can be followed and stopped, "zlib" makes it fail for want of the system package
  zlib1g-dev until that is asked to be installed, "oldpython" makes it fail for a Python that is too new until Python
  3.9 is asked for, and "broken" makes it fail with nothing to say why.
- The data of a PaperAgent is listed and fetched by stand-ins for the places it is kept at, which have a few records,
  named by their keys: Zenodo record 1000001 has files of which one is corrupt (what it sends is not what its checksum
  says), one gives no checksum, and one is restricted; 1000002 has a file larger than the most that is fetched at first;
  1000003 has a file that takes a while to be sent, so that it can be followed and stopped; and GEO series GSE123456 has
  files that give no checksum. Any other record is not found. An address at zenodo.org or osf.io in a paper's text is a
  link to data.
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
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import webbrowser
from collections.abc import Callable, Iterator
from dataclasses import dataclass
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
from test_papers import database, findings, package, task  # noqa: E402

from virtual_lab.constants import MCP_AUTH_DIRECTORY_VARIABLE  # noqa: E402
from virtual_lab.environment import DATA_LAKE  # noqa: E402
from virtual_lab.export import PDFExportError  # noqa: E402
from virtual_lab import openrouter  # noqa: E402
from virtual_lab.environment import StoppedError  # noqa: E402
from virtual_lab.paperagents import data as finding  # noqa: E402
from virtual_lab.paperagents import datahosts as hosting  # noqa: E402
from virtual_lab.paperagents import environment as building  # noqa: E402
from virtual_lab.paperagents import fetch as fetching  # noqa: E402
from virtual_lab.paperagents import repository as cloning  # noqa: E402
from virtual_lab.paperagents.reading import (  # noqa: E402
    ChunkReading,
    ReadClaim,
    ReadDataset,
    ReadLimitation,
    ReadLink,
    ReadScope,
    ReadSoftware,
)
from virtual_lab.papers import PaperFindings  # noqa: E402
from virtual_lab.prompts import result_check_prompt  # noqa: E402
from virtual_lab.server import app as server_app  # noqa: E402
from virtual_lab.server import serve  # noqa: E402
from virtual_lab.server.keychain import Keychain  # noqa: E402
from virtual_lab.server.skills import (  # noqa: E402
    BUILTIN_SKILLS_DIR_VARIABLE,
    SKILL_LIBRARY_DIR_VARIABLE,
    USER_SKILLS_DIR_VARIABLE,
)
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


def previous_answer(messages: list[dict[str, Any]]) -> str:
    """What the lead last wrote before it was asked something, which it gives again when it is asked to check it."""
    for message in reversed(messages):
        content = message.get("content")
        if message["role"] == "assistant" and isinstance(content, str) and content.strip():
            return content

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


def system_given(kwargs: dict[str, Any]) -> str:
    """What a request tells the model before the conversation."""
    return "\n\n".join(str(message["content"]) for message in kwargs["messages"] if message["role"] == "system")


def campaign_given(kwargs: dict[str, Any]) -> str:
    """The name and goal of the campaign that a request tells the model its program is one of, or what says it is one of
    none."""
    system = system_given(kwargs)
    marker = "which holds for every message in this program:\n\n"
    named = re.search(r"campaign called (.+?), which work toward one goal", system)
    if named is None or marker not in system:
        return "Given no campaign"

    return f"Given campaign {named.group(1)}: " + system.split(marker, 1)[1].split("\n\n")[0]


def instructions_given(kwargs: dict[str, Any]) -> str:
    """The instructions of a program of its own that a request gives the model, or what says there are none."""
    system = system_given(kwargs)
    marker = "what the researcher asks in a message is done within them:\n\n"
    if marker not in system:
        return "Given no instructions"

    return "Given instructions: " + system.split(marker, 1)[1].split("\n\n")[0]


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


def paper_findings(text: str) -> PaperFindings:
    """What a paper is found to use, from the words in its text."""
    names = [name for name, word in PAPER_TASKS if word in text] or [PAPER_TASKS[0][0]]

    return findings([task(name) for name in names], [database("GEO")], [package("STAR")])


def chunk_reading(text: str) -> ChunkReading:
    """What a chunk of a paper is read as, from its sentences and headings, each of which is its own quote."""
    start = text.find("<paper_chunk>")
    body = text[start + len("<paper_chunk>") : text.rfind("</paper_chunk>")] if start >= 0 else text
    kinds = ("claims", "datasets", "software", "links", "scope", "limitations")
    facts: dict[str, list[Any]] = {kind: [] for kind in kinds}
    for sentence in (part.strip() for part in re.split(r"(?<=[.!?])\s+|\n\s*\n", body)):
        if found := re.search(r"AUROC of (\d+(?:\.\d+)?)", sentence):
            facts["claims"].append(ReadClaim(kind="number", value=found.group(1), quote=sentence))
        if found := re.search(r"(Seurat) v(\d+(?:\.\d+)*)", sentence):
            facts["software"].append(ReadSoftware(name=found.group(1), version=found.group(2), quote=sentence))
        if found := re.search(r"\bGSE\d+\b", sentence):
            facts["datasets"].append(ReadDataset(name="GEO", accession=found.group(0), quote=sentence))
        if found := re.search(r"https://github\.com/[\w./-]*\w", sentence):
            facts["links"].append(ReadLink(url=found.group(0), role="code", quote=sentence))
        if found := re.search(r"https://(?:zenodo\.org|osf\.io)/[\w./-]*\w", sentence):
            facts["links"].append(ReadLink(url=found.group(0), role="data", quote=sentence))
        if "only tested on mouse" in sentence:
            facts["scope"].append(ReadScope(aspect="species", value="mouse", quote=sentence))
            facts["limitations"].append(ReadLimitation(quote=sentence))
    if "fabricate:" in body:
        facts["claims"].append(ReadClaim(kind="qualitative", value="", quote="This method works on every species."))

    return ChunkReading(
        claims=facts["claims"],
        methods=[],
        datasets=facts["datasets"],
        software=facts["software"],
        links=facts["links"],
        availability=[],
        licenses=[],
        scope=facts["scope"],
        limitations=facts["limitations"],
    )


# How long a paper that is "slow" takes to be fetched, which is long enough for the work to be followed and stopped
FETCH_DELAY = 2.0

# What a paper that is fetched says, which is what the scripted model reads a fact from; the title is where it is from,
# so that no two papers fetched are the same file
FETCHED_PAPER = (
    "# CellMapper: mapping cell types ({where})\n\n## Results\n\n"
    "CellMapper reached an AUROC of 0.93 on held-out mouse hippocampus nuclei, higher than the 0.88 of Seurat label "
    "transfer.\n\n## Methods\n\nClusters were found with Seurat v4.3 after the reads were aligned.\n\n"
    "## Data availability\n\nRaw sequencing data are available in GEO under accession GSE123456.\n\n"
    "## Code availability\n\nCode is available at https://github.com/example/cellmapper under the MIT license."
)


def stand_in_europe_pmc(doi: str) -> fetching.FetchedPaper:
    """The paper Europe PMC gives for a DOI, or why it cannot be had."""
    if "closed" in doi:
        raise fetching.PaperUnavailableError(
            f"The paper {doi} is not open access, so Europe PMC does not give out its full text. {fetching.UPLOAD}"
        )
    if "slow" in doi:
        time.sleep(FETCH_DELAY)

    return fetching.FetchedPaper(
        FETCHED_PAPER.format(where=doi),
        "europepmc-pmc7000001.txt",
        {"kind": "europepmc", "label": "Europe PMC, PMC7000001", "url": "https://europepmc.org/article/PMC/PMC7000001"},
    )


def stand_in_linked_paper(url: str) -> fetching.FetchedPaper:
    """The paper a link leads to, or why it cannot be had."""
    if "closed" in url:
        raise fetching.PaperUnavailableError(
            "The page holds 84 characters of text, which is too little to be a paper. It may ask for a login or a "
            f"payment, or be made by scripts that are not run here. {fetching.UPLOAD}"
        )
    if "slow" in url:
        time.sleep(FETCH_DELAY)
    host = url.split("//", 1)[-1].split("/", 1)[0]

    return fetching.FetchedPaper(
        FETCHED_PAPER.format(where=url),
        "linked-paper.txt",
        {"kind": "link", "label": f"The page at {host}", "url": url},
    )


MIT_LICENSE = (
    "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of this software, "
    "to deal in the Software without restriction.\n\n"
    'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.\n'
)
NONCOMMERCIAL_LICENSE = (
    "Creative Commons Attribution-NonCommercial 4.0 International\n\nThe work may be used for noncommercial "
    "purposes only.\n"
)
NOTEBOOK = json.dumps(
    {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"name": "python3", "language": "python"}},
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": ["# Map the cells of a sample"]},
            {
                "cell_type": "code",
                "metadata": {},
                "execution_count": None,
                "outputs": [],
                "source": ["import cellmapper\n", "cellmapper.map_cells('sample.h5ad')"],
            },
        ],
    }
)


def stand_in_clone(
    url: str,
    destination: Path,
    ref: str | None = None,
    max_bytes: int = cloning.DEFAULT_BYTES,
    seconds: float = cloning.GIT_SECONDS,
    should_stop: Any = None,
    protocols: str = "https",
) -> cloning.Cloned:
    """The project Git gives for an address, written in a folder, or why it cannot be had."""
    asked = cloning.check_ref(ref)
    if "missing" in url:
        raise cloning.RepositoryError(f"{url} was not found, or it is not public.")
    if "huge" in url:
        raise cloning.RepositoryTooBigError(
            f"{url} is bigger than the {max_bytes // cloning.MEGABYTE} megabytes that were asked to be fetched.",
            max_bytes + 1,
            max_bytes,
        )
    if "slow" in url:
        for _ in range(int(FETCH_DELAY * 10)):
            if should_stop is not None and should_stop():
                raise StoppedError("Stopped while the code was fetched.")
            time.sleep(0.1)
    needs_gpu = "gpu" in url
    if "bare" in url:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "README.md").write_text("# cellmapper\n\nMaps cells.\n")
        return cloning.Cloned(commit=hashlib.sha1(f"{url}@{asked}".encode()).hexdigest(), ref=asked)
    files = {
        "README.md": "# cellmapper\n\nMaps cells.\n"
        + ("" if needs_gpu else "\n## Usage\n\nRun `cellmapper sample.h5ad`.\n"),
        "LICENSE": NONCOMMERCIAL_LICENSE if needs_gpu else MIT_LICENSE,
        "requirements.txt": "cupy-cuda12x==13.0.0\ntorch==2.1.0\n" if needs_gpu else "scanpy==1.9.3\nnumpy==1.26.4\n",
        "cellmapper/__init__.py": "",
        "cellmapper/core.py": (
            "import torch\n\nmodel = torch.nn.Linear(2, 2).cuda()\n"
            if needs_gpu
            else 'import torch\n\ndevice = "cuda" if torch.cuda.is_available() else "cpu"\n'
        ),
    }
    if not needs_gpu:
        files["tutorials/quickstart.ipynb"] = NOTEBOOK
        files["tests/test_core.py"] = "def test_nothing():\n    assert True\n"
    for name, text in files.items():
        (destination / name).parent.mkdir(parents=True, exist_ok=True)
        (destination / name).write_text(text)

    return cloning.Cloned(commit=hashlib.sha1(f"{url}@{asked}".encode()).hexdigest(), ref=asked)


# How long a file of data that is "slow" takes to be sent, which is long enough for it to be followed and stopped
DATA_DELAY = 6.0

COUNTS = b"gene,cell1,cell2\nCd4,3,0\nCd8a,0,5\n"
METADATA = b"cell\tregion\ncell1\tCA1\ncell2\tDG\n"
LABELS = b"cell,label\ncell1,pyramidal\ncell2,granule\n"
CORRUPT_LABELS = b"cell,label\ncell1,pyramidal\ncell2,GRANULE\n"
README = b"These counts are of nuclei of the mouse hippocampus.\n"
SLOW_FILE = b"x" * 64
GEO_COUNTS = b"GSE123456 counts, as they are in a file\n"
GEO_MATRIX = b"GSE123456 series matrix, as it is in a file\n"

# What the stand-ins send for a file, by its address, which is not what its listing says for a file that is corrupt
DATA_SENT: dict[str, bytes] = {}


def data_file(
    record: str,
    name: str,
    body: bytes,
    algorithm: str | None = "md5",
    sends: bytes | None = None,
    why: str | None = None,
    size: int | None = None,
    url: str | None = None,
) -> finding.DataFile:
    """A file as a place lists it, which has a checksum of what it should be unless the place gives none."""
    where = url or f"https://zenodo.org/api/records/{record}/files/{name}/content"
    DATA_SENT[where] = body if sends is None else sends
    checksum = (algorithm, hashlib.new(algorithm, body).hexdigest()) if algorithm else None

    return finding.DataFile(name, len(body) if size is None else size, where, checksum, why)


GEO_FOLDER = "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE123nnn/GSE123456/"


@dataclass(frozen=True)
class StoodInPlace:
    title: str
    license: dict[str, str | None] | None
    files: list[finding.DataFile]
    notes: tuple[str, ...] = ()


CC_BY: dict[str, str | None] = {"name": "cc-by-4.0", "url": None}
DATA_PLACES = {
    "zenodo:1000001": StoodInPlace(
        "Nuclei of the mouse hippocampus",
        CC_BY,
        [
            data_file("1000001", "counts.csv", COUNTS),
            data_file("1000001", "metadata.tsv", METADATA),
            data_file("1000001", "labels.csv", LABELS, sends=CORRUPT_LABELS),
            data_file("1000001", "README.txt", README, algorithm=None),
            data_file(
                "1000001",
                "restricted.zip",
                b"",
                algorithm=None,
                size=5_000,
                why="Zenodo does not give this file to everyone, as it is restricted",
            ),
        ],
    ),
    "zenodo:1000002": StoodInPlace(
        "A large atlas",
        CC_BY,
        [
            finding.DataFile(
                "atlas.h5ad",
                600_000_000,
                "https://zenodo.org/api/records/1000002/files/atlas.h5ad/content",
                ("md5", "0" * 32),
            ),
            data_file("1000002", "small.h5ad", COUNTS),
        ],
    ),
    "zenodo:1000003": StoodInPlace(
        "A record that is slow to send", CC_BY, [data_file("1000003", "slow.bin", SLOW_FILE)]
    ),
    "geo:GSE123456": StoodInPlace(
        "GEO series GSE123456",
        None,
        [
            data_file(
                "",
                "suppl/GSE123456_counts.txt.gz",
                GEO_COUNTS,
                algorithm=None,
                url=f"{GEO_FOLDER}suppl/GSE123456_counts.txt.gz",
            ),
            data_file(
                "",
                "matrix/GSE123456_series_matrix.txt.gz",
                GEO_MATRIX,
                algorithm=None,
                url=f"{GEO_FOLDER}matrix/GSE123456_series_matrix.txt.gz",
            ),
        ],
        ("It also has files that are not listed here.",),
    ),
}


def stand_in_list_files(reference: finding.Reference, should_stop: Callable[[], bool] | None = None) -> finding.Listing:
    """What a place has, or why it cannot be had."""
    place = DATA_PLACES.get(reference.key)
    if place is None:
        raise finding.DataError(f"{reference.label} was not found", "missing")

    return finding.Listing(
        reference, place.title, place.license, list(place.files), len(place.files), list(place.notes)
    )


def stand_in_fetch_file(
    reference: finding.Reference,
    file: finding.DataFile,
    target: Path,
    on_bytes: Callable[[int], None],
    should_stop: Callable[[], bool] | None = None,
) -> hosting.Fetched:
    """Fetches a file as the real one does, from what the stand-in sends for it: it is kept only if it is as big as it
    was said to be and matches the checksum that was given."""
    if file.bytes is None or file.why is not None:
        raise finding.DataError(f"{file.name} cannot be fetched: {file.why or 'its size is not given'}", "refused")
    body = DATA_SENT[file.url]
    slow = "slow" in file.name
    part = 2 if slow else max(len(body), 1)
    pauses = -(-len(body) // part)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(target, "wb") as output:
            for start in range(0, len(body), part):
                if should_stop is not None and should_stop():
                    raise StoppedError("Stopped.")
                if slow:
                    time.sleep(DATA_DELAY / pauses)
                chunk = body[start : start + part]
                output.write(chunk)
                on_bytes(len(chunk))
        if len(body) != file.bytes:
            raise finding.DataError(f"Only {len(body):,} of the {file.bytes:,} bytes of {file.name} came", "size")
        if file.checksum is not None:
            algorithm, expected = file.checksum
            actual = hashlib.new(algorithm, body).hexdigest()
            if actual != expected:
                raise finding.DataError(
                    f"{file.name} is not what {finding.SOURCES[reference.source].name} says it is: its "
                    f"{algorithm.upper()} is {actual}, and the checksum given is {expected}. It was discarded.",
                    "checksum",
                )
    except BaseException:
        target.unlink(missing_ok=True)
        raise

    return hosting.Fetched(len(body), hashlib.sha256(body).hexdigest(), file.checksum)


# How long a build that is "slow" takes, which is long enough for it to be followed and stopped
BUILD_DELAY = 6.0

# The images that the stand-in for Docker has, by name
IMAGES: dict[str, str] = {}

ZLIB_OUTPUT = (
    "Collecting speedy\nsrc/_speed.c:1:10: fatal error: zlib.h: No such file or directory\n"
    "error: subprocess-exited-with-error"
)
OLD_PYTHON_OUTPUT = "ERROR: Package 'oldlib' requires a different Python: 3.11.9 not in '<3.10,>=3.8'"


def stand_in_ready(docker_command: Any = ("docker",)) -> tuple[bool, str | None]:
    return True, None


def stand_in_build(
    repo: Path,
    recipe: building.Recipe,
    tag: str,
    limits: building.Limits,
    scratch: Path,
    docker_command: Any = ("docker",),
    on_output: Any = None,
    stop: threading.Event | None = None,
    label: str = "",
) -> building.Built:
    """What building does for an agent of this id: what it prints, and an image kept by its name, or why not."""

    def say(line: str) -> None:
        if on_output is not None:
            on_output(line)

    say(f"Starting from {recipe.base_image}")
    for step in recipe.steps:
        say(f"== {step.title}")
        if "slow" in label:
            for number in range(int(BUILD_DELAY * 10)):
                if stop is not None and stop.is_set():
                    raise StoppedError("The build was stopped.")
                if number % 10 == 0:
                    say(f"Collecting package-{number // 10}")
                time.sleep(0.1)
    if "zlib" in label and "zlib1g-dev" not in recipe.system_packages:
        raise building.EnvironmentBuildError(building.classify(ZLIB_OUTPUT, "project", 1, recipe.python))
    if "oldpython" in label and recipe.python != "3.9":
        raise building.EnvironmentBuildError(building.classify(OLD_PYTHON_OUTPUT, "requirements", 1, recipe.python))
    if "broken" in label:
        raise building.EnvironmentBuildError(building.classify("Something odd happened", "project", 2, recipe.python))
    image = "sha256:" + hashlib.sha256(f"{tag}:{recipe.python}:{recipe.system_packages}".encode()).hexdigest()
    IMAGES[tag] = image

    return building.Built(
        tag=tag,
        image_id=image,
        base_id="sha256:" + "b" * 64,
        base_digests=("python@sha256:" + "c" * 64,),
        architecture="arm64",
        size_bytes=180_000_000,
        added_bytes=130_000_000,
        python=f"{recipe.python or '3.11'}.9",
        lock="numpy==1.26.4\nscanpy==1.9.3\n",
        lock_name="conda-explicit.txt" if recipe.kind == "conda" else "pip-freeze.txt",
        packages=2,
        pip_check={"ok": True, "problems": []},
        steps=tuple({"id": step.id, "title": step.title, "seconds": 1.5, "exit_code": 0} for step in recipe.steps),
        duration=4.0,
        log="",
    )


def stand_in_image_id_of(tag: str, docker_command: Any = ("docker",)) -> str | None:
    return IMAGES.get(tag)


def stand_in_remove_image(tag: str, docker_command: Any = ("docker",)) -> bool:
    IMAGES.pop(tag, None)

    return True


def stand_in_remove_images(label: str, docker_command: Any = ("docker",)) -> bool:
    for tag in [name for name in IMAGES if name.split(":", 1)[1].rsplit("-", 1)[0] == label]:
        del IMAGES[tag]

    return True


def stand_in_remove_builds(label: str, docker_command: Any = ("docker",)) -> int:
    return 0


def function_named(kwargs: dict[str, Any]) -> str | None:
    """The name of the function a request asks the model to write, if it asks for one."""
    system = next((message["content"] for message in kwargs["messages"] if message["role"] == "system"), "")
    found = re.search(r"one function named\s+`(\w+)`", system) if isinstance(system, str) else None

    return found.group(1) if found else None


def function_code(name: str) -> str:
    return FUNCTION_CODE.format(name=name)


SKILL_TRIGGER = re.compile(r"skill:(build|save|use):([a-z0-9-]+)")


def skill_scenario(step: str, name: str) -> list[tuple[str, str, dict[str, Any]]]:
    """What the lead does to build the skill of this name, or to save the one it built, or to read it."""
    if step == "use":
        return [("Reading the skill.", "activate_skill", {"name": name})]
    folder = f"new_skills/{name}"
    saves = ("Saving it.", "save_skill", {"path": folder})
    if step == "save":
        return [saves]
    code = (
        "import os\n"
        f"os.makedirs({folder!r}, exist_ok=True)\n"
        f"text = '---\\nname: {name}\\ndescription: Use when a dose-response curve is fitted to a drug screen.\\n---\\n"
        f"\\n# {name}\\n\\nFit a four-parameter logistic, and report the IC50 with its interval.\\n'\n"
        f"open({folder!r} + '/SKILL.md', 'w').write(text)\n"
        "print('written')"
    )

    return [("Writing the skill.", "run_code", {"code": code}), ("Seeing what would be saved.", *saves[1:])]


def scenario_for(question: str) -> list[tuple[str, str, dict[str, Any]]] | None:
    if "lab:skip" in question:
        return None
    if (skill := SKILL_TRIGGER.search(question)) is not None:
        return skill_scenario(*skill.groups())

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
    # What a command, or a skill, tells the lead goes after what the researcher wrote, and is not what they asked
    question = re.split(r"\n\nThe researcher (?:gave the /|asked for the skill )", question)[0]
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
        elif question == result_check_prompt() and previous_answer(kwargs["messages"]):
            # Asked to check the result that code gave, which it does, and gives the answer again in full, as it is asked to
            response = text_response(previous_answer(kwargs["messages"]))
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
        elif "instructions:" in question:
            response = text_response(instructions_given(kwargs))
        elif "campaign:" in question:
            response = text_response(campaign_given(kwargs))
        else:
            response = text_response(reply_to(question))
        if kwargs.get("stream"):
            include_usage = bool((kwargs.get("stream_options") or {}).get("include_usage"))

            return SlowStream(stream_chunks(response, include_usage), self.delay)

        return response

    def parse(self, **kwargs: Any) -> Any:
        schema = kwargs["response_format"]
        if schema is not PaperFindings and schema is not ChunkReading:
            return super().parse(**kwargs)
        text = " ".join(str(message["content"]) for message in kwargs["messages"] if message["role"] == "user")
        if schema is ChunkReading:
            if "slow:" in text:
                time.sleep(PAPER_DELAY)
            if "fail:" in text:
                raise RuntimeError("The scripted model failed to read the paper, as it was asked to")
            if "refuse:" in text:
                return parsed_response(None, refusal="The scripted model would not read this part of the paper")

            return parsed_response(chunk_reading(text))
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


# The skills the tests find in the library, each with the category and the license it says, and, so that a page has to show
# a few at a time, as many more of the same as there is room for
LIBRARY_SKILLS = [
    ("dose-curves", "Statistics", "MIT", "Fits dose-response curves to titration data and reports the IC50.", None),
    ("rna-counts", "Genomics", "Apache-2.0", "Counts reads per gene from aligned RNA-seq files.", "scripts/count.py"),
    ("cell-types", "Genomics", None, "Labels the cell types of a single-cell dataset.", None),
    ("pathway-flux", "Systems biology", "GPL-3.0-or-later", "Estimates the flux through a metabolic pathway.", None),
    ("spatial-guess", "Imaging", "PolyForm-Noncommercial-1.0.0", "Predicts spatial expression from a tissue image.", None),
]
LIBRARY_FILLERS = 45


def write_skill_library(folder: Path) -> None:
    """A library of skills of the shape that ships with the lab, with an index of what is in it."""
    entries = [*LIBRARY_SKILLS]
    entries += [(f"filler-{number:02d}", "Fillers", "MIT", f"Does filler job {number:02d}.", None) for number in range(LIBRARY_FILLERS)]
    index: dict[str, Any] = {
        "source": {
            "name": "Test Skills",
            "author": "The Tests",
            "url": "https://example.com/test-skills",
            "license": "MIT",
            "version": "1.2.3",
            "ref": "0" * 40,
        },
        "skills": {},
    }
    for name, category, license, description, script in entries:
        directory = folder / "skills" / name
        directory.mkdir(parents=True)
        fields = f"name: {name}\ndescription: {description}\n" + (f"license: {license}\n" if license else "")
        (directory / "SKILL.md").write_text(f"---\n{fields}---\n\n# {name}\n\nFollow the {name} steps.\n")
        files = 1
        if script:
            (directory / script).parent.mkdir(parents=True, exist_ok=True)
            (directory / script).write_text("print('count')\n")
            files += 1
        index["skills"][name] = {"group": "Groups of the tests", "category": category, "files": files, "bytes": 100}
    (folder / "index.json").write_text(json.dumps(index))


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
    fetching.europe_pmc_paper = stand_in_europe_pmc
    fetching.linked_paper = stand_in_linked_paper
    cloning.clone = stand_in_clone
    hosting.list_files = stand_in_list_files
    hosting.fetch_file = stand_in_fetch_file
    building.ready = stand_in_ready
    building.build_environment = stand_in_build
    building.image_id_of = stand_in_image_id_of
    building.remove_image = stand_in_remove_image
    building.remove_images = stand_in_remove_images
    building.remove_builds = stand_in_remove_builds
    openrouter.fetch_models = stand_in_openrouter_models
    workspace = Path(tempfile.mkdtemp(prefix="virtual-lab-e2e-"))
    # The sign-ins to MCP servers are kept away from those of the person running the tests, and no browser is opened
    # for one: a test follows the link the page shows, as a person would
    sign_ins = Path(tempfile.mkdtemp(prefix="virtual-lab-e2e-sign-ins-"))
    os.environ[MCP_AUTH_DIRECTORY_VARIABLE] = str(sign_ins)
    # The skills of the person running the tests are not the server's: it looks in a folder of its own, which is empty
    own_skills = Path(tempfile.mkdtemp(prefix="virtual-lab-e2e-skills-"))
    os.environ[USER_SKILLS_DIR_VARIABLE] = str(own_skills)
    # Nor are the skills that come with the lab, so that what the tests count is what they put in. Its folder is beside the
    # workspace, so that a test that is about those can put one in
    builtin_skills = workspace.parent / f"{workspace.name}-builtin-skills"
    builtin_skills.mkdir()
    os.environ[BUILTIN_SKILLS_DIR_VARIABLE] = str(builtin_skills)
    # Nor is the library of skills that can be put in, which has a few in it for the tests to choose from, and more than a
    # page shows at once. The tests that are about it read it from the same place
    skill_library = workspace.parent / f"{workspace.name}-skill-library"
    write_skill_library(skill_library)
    os.environ[SKILL_LIBRARY_DIR_VARIABLE] = str(skill_library)
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
        shutil.rmtree(own_skills, ignore_errors=True)
        shutil.rmtree(skill_library, ignore_errors=True)
        if setup is not None:
            shutil.rmtree(setup.docker.directory, ignore_errors=True)
            setup.bucket.close()


if __name__ == "__main__":
    main()
