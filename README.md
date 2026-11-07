# Lumi Virtual Lab

A chat-first workbench for computational biology. You talk to the head of a lab, a lead agent. It answers directly when it can. When a question needs a computation, it writes and runs code in a sandbox. When it needs a second opinion, it brings in a team of scientist agents.

Lumi has two parts that work together:

- **A chat interface**, served by a local server, for working with the lead: files you attach, figures and files it makes, notes you can leave it while it works, and a spending limit for each program. A program is one conversation with its files and what it made: a quick task, a custom program with a name and instructions of its own, or one that builds a skill with you and saves it when you agree. Programs that work toward one goal can be grouped in a campaign, which has a goal that the lead is told in every program of it.
- **A Python library**, `virtual_lab`, underneath it, for running meetings from a script, giving agents tools, and measuring them on benchmarks.

Lumi began as a fork of the [Virtual Lab](https://github.com/zou-group/virtual-lab) by Kyle Swanson and colleagues, and builds on [Biomni](https://github.com/snap-stanford/Biomni) from Stanford SNAP. See [Licenses and acknowledgements](#licenses-and-acknowledgements).

## What it does

- **Talks to a lead agent that can use a team.** The lead can hold a team meeting, or ask one scientist with a Scientific Critic reviewing, and is given what they conclude. Slash commands (`/ask`, `/plan`, `/search`, `/code`, `/plot`, `/review`, `/lab`) say how to answer a message.
- **Runs code it writes**, in Python, R, and shell, in a Docker container with no access to your files or keys. The container can hold Biomni's bioinformatics software, 223 of Biomni's tool functions, and its 76-file data lake. See [Running code](docs/running-code.md).
- **Looks things up** in UniProt, the PDB, AlphaFold, PubChem, ChEMBL, Europe PMC, PubMed, and arXiv, and searches and reads the web. It also looks at images and the pages of PDFs. See [Tools, data, skills, and MCP servers](docs/tools-and-skills.md).
- **Follows skills**: written guidance in the [Agent Skills](https://agentskills.io) format. Seven come with Lumi, and the [Skills Nexus](docs/tools-and-skills.md#the-skills-nexus) page has 177 more scientific skills to add with a click. You can also upload a skill folder of your own, or add skills from a git repository or a folder, and choose which a conversation is given.
- **Connects to MCP servers** for more tools, with approval before a call that costs money or cannot be undone.
- **Uses any model**: OpenAI, Anthropic, Google, Groq, Azure, OpenRouter, Ollama, and Amazon Bedrock. See [Models and API keys](docs/models-and-keys.md).
- **Saves a conversation or a meeting** as a Jupyter notebook, a PDF, or a page of HTML.
- **Measures itself** on Biomni's benchmarks. See [Benchmarks](docs/benchmarks.md).

## Quick start

You need Python 3.12 or later, Node 22 or later (the first time only, to build the pages), Docker (to run code), and a key for at least one model provider.

```bash
git clone https://github.com/AdviktheGreat/Lumi_Virtual_Lab.git
cd Lumi_Virtual_Lab
python3 start.py
```

`start.py` makes a Python environment in `.venv`, installs Lumi in it, builds the pages, and starts the server. Each step is skipped when it is already done, so the first start takes a few minutes and later ones a moment. It prints a link with a token in it, and opens it. The server is at `http://127.0.0.1:8765` unless that port is taken.

Add your keys in Settings. They are kept in your machine's own keychain. A key in the environment, or in a `.env` file in the clone, is used too. The interface also builds the Docker image that code runs in and fetches the data lake, showing what each prints.

```bash
python3 start.py --workspace ~/lab --port 9000 --no-browser
python3 start.py --plan         # what it would do, without doing it
python3 start.py --rebuild      # build the pages again
```

Conversations, settings, and files are kept in a workspace, `~/virtual_lab_workspace` unless `--workspace` says otherwise. The server is for one person on one machine: it answers only requests that carry its token, and it runs code you did not read, so keep it on your own machine. See [Conversations, the server, and the chat interface](docs/chat-and-server.md).

## Using the library

Install from a clone. The `virtual-lab` package on PyPI is the original Virtual Lab, a different project that does not contain this code.

```bash
pip install -e .                          # the library
pip install -e ".[server,mcp,papers,eval]"
```

| Extra | Adds |
| --- | --- |
| `server` | The server and chat interface: FastAPI, Uvicorn, the keychain, and image reading |
| `mcp` | Tools from MCP servers, and serving Lumi's tools over MCP |
| `papers` | Reading papers saved as PDFs |
| `vision` | Looking at images and the pages of PDFs (`server` includes it) |
| `pdf` | Saving meetings and conversations as PDFs (also needs the Pango library) |
| `eval` | Biomni's benchmarks |
| `ollama`, `bedrock` | Local models through Ollama, and models on Amazon Bedrock |
| `dev` | What the tests need |

A conversation from Python:

```python
from pathlib import Path

from virtual_lab import Agent, Chat, LocalSession

lead = Agent(
    title="Principal Investigator",
    expertise="computational biology",
    goal="answer the researcher's questions about their data",
    role="lead the lab and run the analyses",
    model="gpt-5.2",
)

with LocalSession(Path("work")) as session:
    chat = Chat(Path("chats/example"), lead=lead, session=session, max_cost=5.0)
    counts = chat.save_upload("counts.csv", open("counts.csv", "rb"))
    reply = chat.send("Which genes are higher in the treated samples?", attachments=[counts])
    print(reply.status, reply.text)
```

`LocalSession` runs code on your machine with no isolation. Use `DockerSession` to run it in the sandbox.

## Documentation

| Page | What is in it |
| --- | --- |
| [Models and API keys](docs/models-and-keys.md) | Which provider each model name goes to, OpenRouter, keys and `.env` files |
| [Meetings](docs/meetings.md) | Team and individual meetings, spending limits, following and steering a meeting, saving documents |
| [Running code](docs/running-code.md) | The Docker sandbox, sessions, Biomni's software, data lake, and tools |
| [Repairing code and running steps within one budget](docs/projects.md) | Fixing code that fails, and many meetings within one budget |
| [Conversations, the server, and the chat interface](docs/chat-and-server.md) | The lead, its limits, the server's API, and building the pages |
| [Growing the toolset from papers](docs/papers-and-functions.md) | Reading papers, and writing a function for each task |
| [Benchmarks](docs/benchmarks.md) | Measuring an agent or a team on Biomni's benchmarks |
| [Tools, data, skills, and MCP servers](docs/tools-and-skills.md) | Databases, the web, your own tools, data, and software, skills, MCP |

The web interface has its own notes for people who change it, in [`web/README.md`](web/README.md).

## Development

```bash
pip install -e ".[dev]"
pytest
```

The interface is tested from `web/`: `npm run lint`, `npm run typecheck`, `npm test`, and `npm run test:e2e`, which drives a browser against the real server with a script in place of the model, so it needs no key.

## Licenses and acknowledgements

Lumi's own code is released under the [MIT License](LICENSE). It includes and builds on the work of others, each under its own license. [`NOTICE`](NOTICE) lists what, where it is, and under which license. In short:

- **Virtual Lab** (MIT; Kyle Swanson, Wu, Bulaong, and colleagues in James Zou's group). Lumi's meetings, agents, and prompts began there. The authors' nanobody design study, which Lumi once kept, is now in [virtual-lab-nanobody-design](https://github.com/AdviktheGreat/virtual-lab-nanobody-design), with its history. If you use the meeting framework, please cite:

  Swanson, K., Wu, W., Bulaong, N.L., Pak, J.E. & Zou, J. The Virtual Lab of AI agents designs new SARS-CoV-2 nanobodies. *Nature* **646**, 716–723 (2025). https://doi.org/10.1038/s41586-025-09442-9

- **Biomni** (Apache License 2.0; Stanford SNAP). The sandbox is built from Biomni's environment files, and Biomni's tool package is mounted in it, both copied without modification. Parts of Lumi follow Biomni's code, prompts, and data tables, and say so in their files. If you use Biomni's tools, data, or environment, please cite:

  Huang, K., Zhang, S., Wang, H. et al. Biomni: A General-Purpose Biomedical AI Agent. *bioRxiv* (2025).

**Before any commercial use**, read [`license_info.md`](src/virtual_lab/sandbox/biomni_package/license_info.md). Lumi's own license permits commercial use, but the data lake and tools it can fetch are other people's datasets and software. Several are licensed for non-commercial use only (such as DDInter, DisGeNET, McPAS-TCR, miRDB, and miRTarBase), and others need a license for commercial use (such as COSMIC, BindingDB, MSigDB, and OMIM). Lumi does not ship the data lake: `download_data_lake` fetches it from Biomni's release bucket on request. `commercial_mode=True` leaves out what Biomni's own commercial mode leaves out. It does not check the licenses of the databases a tool queries.

Lumi is an independent project. It is not affiliated with or endorsed by the authors of the Virtual Lab, Biomni, or any model provider or service it connects to, whose names are their owners' trademarks.
