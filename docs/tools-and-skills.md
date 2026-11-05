# Tools, data, skills, and MCP servers

[Back to the README](../README.md). The databases and the web that agents can reach, your own tools, data, and software, skills, and tools from MCP servers.

## Querying scientific databases

Tools that look something up go through `virtual_lab.web`, which decides where a request may be sent. An agent chooses the arguments to a tool, which means a model's output determines part of every URL, so the destination cannot be left to the tool:

- Requests are allowed only to the scientific databases named in `ALLOWED_HOSTS`, over HTTPS. Membership is exact, so a host that merely ends in an allowed one (`evilrest.uniprot.org`) and a subdomain of one (`x.rest.uniprot.org`) are both refused, as are a plaintext address, a loopback or link-local address, a non-HTTPS scheme, and a URL carrying credentials.
- The URL is normalised through the HTTP client before it is checked, and the checked URL is the one requested. Validating with one parser and requesting with another is not safe: CPython ends a URL's authority at a slash, question mark, or hash, while urllib3 also ends it at a backslash, so `https://169.254.169.254\@rest.uniprot.org/` reads as an allowed host to the first and as the cloud metadata service to the second.
- Redirects are followed manually and the destination is checked at every hop. A client left to follow redirects itself checks the address it was given, not the address it ends up talking to, which turns one allowed host into a request to anywhere.
- Identifiers are percent-encoded into a fixed template by `build_url`, so an identifier containing `/`, `?`, or `#` becomes part of the path rather than reshaping the request. A segment that is `.` or `..` is refused outright, since a dot needs no encoding and the server would resolve it.
- Responses are capped at `MAX_RESPONSE_BYTES` whether or not the service declares a length, requests to one host are spaced by `MIN_SECONDS_BETWEEN_REQUESTS`, temporary failures are retried with backoff that honours `Retry-After`, and repeated questions are answered from an in-memory cache bounded by both entry count and total size.

```python
from virtual_lab import request_json

data = request_json("https://rest.uniprot.org/uniprotkb/P01308.json")
```

Adding a database means adding its host to `ALLOWED_HOSTS`. This is a deliberate edit rather than a parameter, so that widening what agents can reach is a visible change to the library.

The tests for this layer run offline against a faked transport, since redirects, rate limits, and oversized responses cannot be requested from a real service on demand. The handful that do query the real databases are skipped unless `VIRTUAL_LAB_LIVE_TESTS=1` is set.

## Giving agents tools

`all_tools` returns everything an agent can call. Pass a `save_dir` to include the structure download, which needs somewhere to write.

```python
from virtual_lab import all_tools, run_meeting

run_meeting(
    meeting_type="team",
    agenda="Which structures of the human insulin receptor are known, and which would suit docking a ligand?",
    save_dir=Path("results"),
    save_name="target_structure",
    team_lead=principal_investigator,
    team_members=(immunologist, computational_biologist),
    # The same two arguments, so downloads land where this meeting's code will run
    tools=all_tools(save_dir=Path("results"), save_name="target_structure"),
)
```

| Tool | What an agent uses it for |
| --- | --- |
| `uniprot_search` | Find proteins by name, gene, or organism and get their accessions |
| `uniprot_lookup` | A protein's sequence, function, domains, disulfide bonds, and known structures |
| `pdb_lookup` | An experimental structure's method, resolution, chains, ligands, and chain sequences |
| `alphafold_lookup` | A predicted structure and its pLDDT confidence, where no experimental one exists |
| `fetch_structure_file` | Download coordinates to disk for code to parse |
| `pubchem_lookup` | A small molecule's formula, weight, SMILES, and computed descriptors |
| `chembl_search` | Find drugs and compounds by name and get their ChEMBL identifiers |
| `chembl_lookup` | A drug's clinical status, route, mechanism of action, and drug-likeness |
| `chembl_target_search` | Find a protein target and get the identifier bioactivity is keyed by |
| `chembl_activities` | What binds a target, how tightly, and in what assay |
| `europepmc_search` | Find published articles and biology preprints, with citation counts |
| `europepmc_lookup` | One article's abstract and details, by PMID, PMCID, or DOI |
| `europepmc_fulltext` | Read an open access article, minus its references and front matter |
| `arxiv_search` | Find machine learning and computational preprints, which Europe PMC does not index |
| `pubmed_search` | Abstracts or full text from PubMed Central |
| `web_search` | Search the web for documentation, protocols, and what the curated databases do not hold |
| `web_fetch` | Read a web page or a PDF as text, in parts, from an address a search found |
| `data_files` | What data files are in the project directory, and how big |
| `inspect_data_file` | What is in a CSV, TSV, or Excel file, and how it will be read wrongly |
| `view_image` | What an image, or pages of a PDF, shows, which the lead's own model is asked (in the server's conversations) |

Use `tools_for("uniprot_lookup", "pdb_lookup")` to give a particular agent only part of the set, and `TOOL_REGISTRY` to see what is available. `web_search` and `web_fetch` are in `WEB_TOOLS` and not in the registry, because unlike every other lookup they are not limited to a few named services: give them with `tools=[*DATABASE_TOOLS, *WEB_TOOLS]`. `fetch_structure_file`, `data_files`, and `inspect_data_file` are not in the registry, because none of them can exist until it has been told which directory it may touch; get them from `all_tools(save_dir=...)` or build them with `structure_file_tool(work_dir)` and `data_file_tools(work_dir)`. `view_image` is not in it either, since it needs a model to ask as well: build it with `view_image_tool(work_dir, ask)`, where `ask` is a function that gives a model's answer to a question about pictures (`Chat.ask_about_images` is the one a conversation uses). Each underlying function can also be called directly, which is what tests and analysis scripts do:

```python
from virtual_lab import get_protein

protein = get_protein("P01308")
print(protein.length, protein.pdb_ids[:3])
print(protein.report())
```

Three things about this are deliberate:

**A record and its report are different things.** `get_protein` returns every field worth keeping, while `report()` returns what is worth paying for in a request. A sequence of 35,000 residues is on the record and not in the report, because it would be most of a context window spent on one field.

**Queries are built from named arguments, not written by a model.** A model asked to compose a query payload writes a plausible one whose mistakes come back as an empty result rather than as an error, which is the hardest kind to notice. The cost is a function signature per database, which is also what makes these testable.

**Coordinates go to disk, not into the conversation.** One moderate structure file is several hundred kilobytes, and code an agent writes runs in a sandbox with no network of its own. So `fetch_structure_file` fetches outside the sandbox and writes into `artifacts/<save_name>/structures`, which is inside the one directory mounted into the container, and reports back the path to use from there. A file written anywhere else is invisible to the code that needs it. Where it writes is bound when the tool is built and is not a parameter a model fills in, which is why `all_tools` takes the same `save_dir` and `save_name` that `run_meeting` does.

### The web

`web_search` and `web_fetch` are the one place a model chooses where a request goes, so they are built differently from the lookups above, which only ever reach the hosts in `ALLOWED_HOSTS`.

- **`web_search`** uses [Exa](https://exa.ai) if `EXA_API_KEY` is set, and otherwise DuckDuckGo's page for browsers without scripts, which needs nothing. It gives titles, addresses, the passages Exa quoted (or the snippet DuckDuckGo did), and the day a page was published when Exa knows it, and says which engine answered. If Exa fails (a refused key, no credit left, or an outage), DuckDuckGo is used and the result says so. DuckDuckGo answers a client that searches often with a challenge instead of results, so searches to it are spaced 1.5 seconds apart, and when it does refuse the failure says to set the key. The key can be in the environment the server is started with, or be given to a running server with `PUT /api/keys/EXA_API_KEY` (kept in the keychain like the model providers' keys).
- **`web_fetch`** reads HTML (as text, with headings, lists, and tables kept as lines), PDF (with `pip install -e ".[papers]"`), and plain text, in parts of about 16,000 characters, each saying what `start` to give for the next. `links=true` lists the page's links, so that the model can follow one.
- **What is refused:** a destination is refused unless every address its name leads to is on the public internet, which leaves out this machine, the network it is on, and a cloud's metadata service. That is checked for the address, for every redirect (followed by hand, up to 5), and for the address the socket is actually connected to, so a name that leads somewhere public when checked and somewhere private when connected to is stopped as well. Only http and https on their standard ports are read, with no login in the address and no proxy from the environment, and a page is cut off at 15 MB, or after 60 seconds.
- **What it says about itself:** both tools tell the model that what the web says was written by whoever runs the site, and is not to be obeyed.

The conversation's tool settings list them as "Web", and they are on until turned off, like the other tools.

### Your own tools

`tool_from_function` makes a tool of any Python function, the way Biomni's `add_tool` does. Biomni asks a model to read the function's source and write out its parameters. Here the parameters come from the signature and its type hints, and the descriptions from the docstring, so nothing is invented:

```python
from virtual_lab import tool_from_function

def gc_content(sequence: str, window: int = 100) -> list[float]:
    """The GC fraction of a DNA sequence, in windows along it.

    :param sequence: The sequence, as A, C, G, and T.
    :param window: How many bases each window spans.
    """
    ...

tool = tool_from_function(gc_content)
hold_meeting(..., tools=(tool,))     # the agents call it as a tool
```

A parameter without a default is required, and each is typed by its hint: `str`, `int`, `float`, `bool`, `list[str]`, `dict[str, float]`, `Literal["a", "b"]`, an `Enum`, a `Path`, a `date`, a pydantic model, or anything else pydantic can read from JSON. The arguments a model sends are converted to those types before the function is called, so `"5"` becomes `5` and `{"start": 1, ...}` becomes the model it describes. Arguments that are wrong are not passed on: the model is told what was wrong and can correct the call. The docstring can be in the reST, Google, or NumPy style. `name=` and `description=` override what the function says of itself. A `functools.partial` leaves the arguments it binds out of the tool, and an async function is waited for. A parameter whose type cannot come from JSON, such as a pandas DataFrame, is refused, since no model can pass one; take a path to the file instead.

A function with no docstring needs `description=`, or a model to describe it: `tool_from_function(f, model="gpt-4o")` asks it once, from the function's source, and prints what it wrote. Only the descriptions come from the model; the parameters still come from the signature. A model can describe the same function differently each time, and a project resumed with a tool described differently holds its meetings again, so keep a description you are happy with by adding it to the function as its docstring.

Give the tool to a session instead, and code in the session calls it like any other function, without importing it, as Biomni's agent calls the tools added to it:

```python
with DockerSession(Path("results/session"), tools=(tool,)) as session:
    session.run("profile = gc_content(sequence, window=50)")
    hold_meeting(..., session=session)  # the agents are told of gc_content, and their code calls it
```

The function runs on your machine, outside the container. When code in the sandbox calls it, the call comes out over the session's own connection as JSON, the function runs here, and what it returns goes back the same way. A tool can therefore use what the sandbox does not have: the network when the session has none, an API key the sandbox is never given, a GPU, a licensed program, or files outside the session's directory. That is also the risk: a tool can do whatever the function does, with your permissions, on arguments that code written by a model chose. Give a session only tools you would let that code call. Arguments and results are JSON. NumPy arrays, sets, and paths are converted, and anything else is refused with advice to convert it or pass a file instead. A failure in the tool raises `HostToolError` in the code. A call counts towards the time limit of the code that made it: code stopped at its limit while a tool runs keeps its session, and the tool is left to finish, its result unused. Each call is recorded with the cell that made it: the tool, its arguments, how it ended, and how long it took. The tools are listed to a meeting's agents ahead of Biomni's resources, as functions added for this work that they should prefer, again as Biomni lists the tools added to its agent. Changing a session's tools changes the inputs of every project step held with it. R and bash code cannot call them, and a tool cannot run code in the session whose code called it.

### Your own data and software

A session can also be given data and software of your own, in the form Biomni's `add_data` and `add_software` take them: a dict of each path, or each name, with what it is.

```python
with DockerSession(
    Path("results/session"),
    data={"inputs/counts.csv": "Read counts per gene and sample, from the 2024 RNA-seq run.",
          "inputs/images": "Microscopy of the knockout lines, one TIFF per field."},
    software={"pydeseq2": "Differential expression, a Python port of DESeq2."},
) as session:
    hold_meeting(..., session=session)
```

Biomni lists a file it was given by its name alone, and leaves the agent to find it. Here each file or directory is mounted read-only in the container at `/data/` and its name, `/data/counts.csv` and `/data/images` above, and the agents are told that path. A `LocalSession` reads the data where it is, and tells the agents that path instead. The data must exist when the session is made, no two pieces may share a file name, and in a `DockerSession` none may be in the session's directory, where code could change it, or hold it.

Software is not installed for you: it must be in the image, or in the `python` a `LocalSession` runs. A meeting first looks for each piece in the session, as a Python distribution, a module Python can find, an R package, or a command. Anything it cannot find is warned about and noted in the record as `software_not_found`, and the agents are still told of it, but as not found, since a name can differ from anything the check looks for.

The data and software are listed after the session's own tools, ahead of Biomni's resources, as added for this work and to be preferred, as Biomni lists what is added to its agent. Changing them changes the inputs of every project step held with the session. Data counts by name and description, not by where it is on your machine or what the files hold, so a project resumed with different contents under the same name does not notice the change.

### Skills

A skill is written guidance on a kind of work: a folder with a `SKILL.md`, which has a block of YAML at the top giving its `name` and a `description` of what it is for and when to use it, and then the instructions. Scripts, references, and templates may sit beside it. This is the [Agent Skills](https://agentskills.io) format, which Claude Code, Codex, and other tools read too, so a skill written for one of them works here, and there are libraries of them, such as [K-Dense's scientific skills](https://github.com/K-Dense-AI/scientific-agent-skills).

```python
from virtual_lab import Chat, discover_skills

library = discover_skills([("mine", Path("~/skills").expanduser())])
print([problem.message for problem in library.problems])  # a SKILL.md that could not be used, and why
chat = Chat(Path("results/chat"), lead, session=session, skills=library.skills)
```

The lead is told the name and purpose of each skill in every request, which is little, and reads the rest when a task calls for it: `activate_skill` gives a skill's instructions and lists the files that come with it, and `read_skill_file` reads one of them, in parts if it is long. When there is a session, an activated skill's folder is copied into the session's directory under `skills/`, so code can run its scripts. A skill never runs by itself, and the files read are those inside its folder: a path that leaves it, or a link that leads out of it (a `SKILL.md` too), is refused, and links are not copied. Each result stays under a tool's 25,000-character limit, with the files listed at most 40 and 3,000 characters long.

A folder is searched five levels down, so a whole repository of skills can be put in it. What is wrong with one skill leaves out that skill and not the others. A description or compatibility longer than the standard allows, or a name that is not lowercase, is noted and used (the compatibility is cut to the 500 characters it allows). Names that differ only in case are one name, since each skill is a folder in the session, so the first found is used. YAML that is not valid, such as a description with an unquoted colon, is read line by line, as other tools read it. A library with too many skills to list whole, such as 170, has each description cut to a share of `skills_catalog_chars` (20,000 by default, about 5,000 tokens in each request), and the lead sees all of a skill when it activates it. The team is not given the tools: the lead passes on what they need.

The server finds skills in the workspace's `skills/` folder, in `~/.agents/skills`, where other tools put theirs, and in `virtual_lab/builtin_skills`, which holds the seven that come with the lab (`builtin_skills()` returns them, for `Chat(skills=builtin_skills())`). Where two have one of a name the first of these is used, so a skill of yours takes the place of one that comes with the lab. Those that come with the lab are read from where they ship and never copied, cannot be deleted, and can be turned off like any other, on the Skills page or for one conversation. They add about 600 tokens to each request. A new conversation is given every skill that is on (see `GET /api/skills` in [Serving the conversation to a page](chat-and-server.md#serving-the-conversation-to-a-page)), or the ones named in `"skills"` in the request, and goes on with those of them that are still there when it is opened again. Set `VIRTUAL_LAB_USER_SKILLS_DIR` to look in another folder than `~/.agents/skills`, and `VIRTUAL_LAB_BUILTIN_SKILLS_DIR` to read the skills that come with the lab from another folder (an empty one gives the server none of them). Skills are instructions written by someone else, which the lead follows and whose scripts it may run, so install only those you would trust with that.

#### The Skills Nexus

The lab carries a library of skills, the 177 of K-Dense's [scientific agent skills](https://github.com/K-Dense-AI/scientific-agent-skills) (MIT, version 2.72.0), in `virtual_lab/scientific_skills`: about 2,000 files and 21 MB, in the same format, so nothing is fetched when one is put in. `index.json` beside them names the release they were taken from and gives each skill's group and category, which `scripts/update_scientific_skills.py <folder>` rewrites from a checkout of a newer release (it replaces only the `skills/` folder and the license beside it, and refuses a release whose catalog and folders disagree). Set `VIRTUAL_LAB_SKILL_LIBRARY_DIR` to read the library from another folder.

The Skills page of the web interface (`/skills`, called Skills Nexus) has two tabs. **Discover** is the library, which can be searched and narrowed to a category, with a box to tick for each skill, and a button to put in the ones ticked (or all that match). **Your skills** is what the lab has found, as it was on the Data page: the skills that come with the lab, those in the workspace, and those in `~/.agents/skills`, each of which can be turned on or off, read, or (in the workspace) deleted, with the means to install from a git repository or a folder. A skill put in from Discover is copied into the workspace's `skills/` folder and is on from then, so a conversation made after is given it. A skill whose name is taken is left as it is, and the page says so.

Every skill that is on costs tokens in every request, so both tabs show a meter of how much of the catalog (`skills_catalog_chars`, 20,000 characters) the skills that are on fill, and Discover says what a put-in will add before it is made. With all 184 skills on, the catalog is full and each description is cut to about 90 characters, so turn off the ones a piece of work does not need. The library's skills are under the licenses their authors chose, which are not all as free as K-Dense's: a few are under a GPL, a few are for noncommercial use only (`deepspot-m`, `what-if-oracle`), one needs a paid key (`rowan`), and some give none. Each shows its license, a noncommercial one is marked, and putting one in asks first. `NOTICE` lists them.

### Tools from MCP servers

`connect_mcp` makes tools of the tools of [MCP](https://modelcontextprotocol.io) servers, as Biomni's `add_mcp` does, from the same YAML config, or from the JSON config that Claude Desktop, Claude Code, Cursor, and others write. It needs the MCP SDK: `pip install -e ".[mcp]"`.

```yaml
mcp_servers:                      # or mcpServers, as Claude Desktop's config has it
  genes:                          # started here, and spoken to over its stdin and stdout
    command: ["python", "-m", "gene_server"]
    env: {GENE_API_KEY: "${GENE_API_KEY}"}
  search:                         # reached at a URL, over streamable HTTP
    url: "https://search.example.org/mcp"
    headers: {Authorization: "Bearer ${SEARCH_TOKEN}"}
```

```python
from virtual_lab import connect_mcp

with connect_mcp("mcp_config.yaml") as mcp:
    hold_meeting(..., tools=mcp.tools)                   # the agents call them as tools
    with DockerSession(Path("results/session"), tools=mcp.tools) as session:
        hold_meeting(..., session=session)               # or code in the session calls them
```

Each tool is named after its server and itself, `genes_lookup` for the tool `lookup` of the server `genes`, so that two servers' tools never share a name, with anything other than letters, digits, and `_` made `_`, so that code can call it. Its description and parameters are the ones the server gives it, and the server checks the arguments. `mcp.servers["genes"]` holds one server's tools.

A command is a list of the program and its arguments, as Biomni's config has it, or a program with its `args`, as Claude's has it. A server started here gets `env` as its environment, with a few variables of this process, such as `PATH` and `HOME`, and not the rest, so an API key reaches only the servers given it; `cwd` is where it starts. A server at a URL gets `headers` with every request, and one whose `type` is `sse`, or whose URL ends in `/sse`, is spoken to over the older SSE transport. `${NAME}` anywhere in these is replaced with the environment variable `NAME`, and `${NAME:-default}` with the default where it is not set. Errors, and what a server wrote to stderr, show `${NAME}` where its value would be, so a key in a URL or a header is not repeated in a traceback; what a tool returns is left as it is. A server with `enabled: false` or `disabled: true` is left out, and `connect_mcp(config, servers=["genes"])` connects to only the servers named. `tools: [lookup, search]` offers only those of a server's tools; an entry in Biomni's form, with `biomni_name` and `description`, gives that tool its description, and the parameters it lists are not used, since the server declares them.

Biomni starts a server again for every call to one of its tools, over stdio only, and returns the first piece of whatever the tool returned, an error included. Here:

- **A server is started once**, and kept running until the tools are closed, so what it loads stays loaded, and calls to it run at the same time. Any left open are closed when Python exits.
- **What a tool returns is given back whole.** Where the server gives a structured result, that is what code receives, such as a dict, and otherwise its text. An image, a recording, or a file in it is described, since none can be shown as text. A model is shown either as text.
- **A failure is a failure.** A tool the server says failed raises `MCPToolError` with what the server said, which the agent is told as an error, and can correct its call from. A call that takes longer than `timeout`, 300 seconds unless given, raises `TimeoutError`, and the server is kept.
- **A server that stops is started again**, or connected to again, at the next call to one of its tools, with a warning, since whatever it held is gone. Only a call that was running when it stopped fails, raising `MCPServerError`.
- **A config that cannot work fails at once.** A variable that is not set is an error, rather than an empty value, and so is a server that does not start, or a tool asked for that a server does not have. What a server writes to stderr is kept out of the way, and its end is shown when the server fails. Where one server fails, those already started are stopped again.

A server's tools run wherever the server does: one started here runs on your machine, with your permissions, on arguments a model chose, even when the code calling it is in a sandbox, so give a session only the servers you would let that code use. Changing a server's tools, or what it says of them, changes the inputs of every project step held with them.

#### Tools that wait for a person's approval

A tool that spends money, or does what cannot be undone, can be made to wait for a person to approve each call to it. A server's `approval` lists those tools by their names on the server, or by patterns such as `create_*`, or lists under `ask` the tools that wait and under `allow` those of them that do not after all:

```yaml
mcp_servers:
  lab:
    url: "https://lab.example.org/mcp"
    approval: {ask: ["*"], allow: ["list_*", "get_*"]}   # every tool waits but those that only read
    instructions: "Estimate an experiment's cost before creating it."
```

`{ask: ["*"], ...}` also holds for any tool the server adds later, which a list of names would let through. Before each call to a tool that waits, the person at the terminal is shown the tool and its arguments and asked to approve it. Where there is no terminal, as in a script run in the background or one whose stderr goes to a file, every such call is declined. A call made by code in a session that has stopped, such as by running out of time, before the person answers is not made, even if they approve it, since no one would receive its result. `connect_mcp(..., approve=decide)` decides another way: `decide` is called with an `ApprovalRequest`, and the call is made only if it returns `True`. A call that is not approved is not made. It raises `ApprovalDeclined`, which the agent is told of, along with not to make it again unchanged. A name in `ask` that the server has no tool of is warned of, since a call to the tool meant would not wait. The descriptions of the tools that wait say so, so that agents know.

A server can also ask a person something while one of its tools runs, as Proto's server asks before it deploys a tool. Its question is asked at the terminal, a form field by field, or, where it asks the person to go to a web page, by opening the page. `answer=` answers another way: it is called with a `ServerQuestion` and returns the answers by field name, `{}` once the person has gone to the page, or `None` to decline. Where there is no terminal, every question is declined. A question whose tool call has stopped waiting, such as by running out of time, is withdrawn, and the answer is not used.

What a server's `instructions` say, and what the server says itself of how to use its tools, are told to the agents of a meeting given its tools, or a session given them.

#### Paperclip, Adaptyv, and Proto

Three services built for agents doing biology have presets, a server's entry written out already, with what waits for approval and what the agents are told:

| Preset | Service | Needs |
| --- | --- | --- |
| `paperclip` | [Paperclip](https://paperclip.gxl.ai): searching and reading the full text of papers, trials, patents, and regulatory documents | An API key in `PAPERCLIP_API_KEY`, from https://paperclip.gxl.ai/keys, or signing in with `auth: oauth` |
| `adaptyv` | [Adaptyv's Foundry](https://foundry.adaptyvbio.com): proteins made and tested in a lab, which costs money | An API token in `FOUNDRY_API_TOKEN`, from the Foundry portal, or signing in with `auth: oauth` |
| `adaptyv_testing` | Adaptyv's testing sandbox, where nothing is made or charged for | A token in `FOUNDRY_TESTING_TOKEN`, from https://foundry.testing.adaptyvbio.com, or signing in with `auth: oauth` |
| `proto` | [Proto](https://github.com/evo-design/proto-tools): over a hundred tools for protein and sequence design, run on your own Modal account | `uv tool install "proto-tools[mcp] @ git+https://github.com/evo-design/proto-tools.git"`, then `modal token new` |
| `proto_hosted` | Proto's hosted server, at `https://mcp.evodesign.org/mcp`: the same tools, with nothing installed here | Signing in with a Proto account, from https://proto.evodesign.org |

```python
with connect_mcp(presets=["paperclip", "adaptyv_testing"]) as mcp:
    hold_meeting(..., tools=mcp.tools)

with connect_mcp(presets={"paperclip": {"auth": "oauth"}, "proto_hosted": {}}) as mcp:
    hold_meeting(..., tools=mcp.tools)                   # signed in to, with no API keys
```

Or a config names one with `preset`, and anything else its entry gives is used in place of the preset's, such as `lab: {preset: adaptyv, approval: ["*"]}` for every one of Adaptyv's tools to wait. The keys and tokens can be in the environment or in the `.env` file, and where one is missing, the error says where to get it. Every one of Adaptyv's tools waits for approval but those that list, get, or estimate a cost, so no experiment is created, submitted, or paid for without a person approving it. Proto's tools that search, describe, and run deployed tools do not wait, but `deploy_tool`, which builds a tool on Modal at your expense, does, as does any other tool either server has or adds. `MCP_PRESETS` lists the presets, with what each needs.

#### Signing in to a server

A server at a URL whose entry has `auth: oauth` is signed in to in your browser, the first time it is connected to, rather than sent an API key. Proto's hosted server is always signed in to; Paperclip's and Adaptyv's can be, in place of their keys, which a preset signed in to is then neither sent nor needs set:

```yaml
mcp_servers:
  proto: {preset: proto_hosted}
  papers: {preset: paperclip, auth: oauth}
  search:
    url: "https://search.example.org/mcp"
    auth: oauth
```

`connect_mcp` finds the server's authorization server, registers with it, and opens its sign-in page, with the MCP SDK's OAuth client, which uses PKCE. Once you have signed in, the browser is sent back to `http://127.0.0.1` on a port of this machine's, where the sign-in is received. The tokens are kept in `~/.virtual_lab/mcp_auth`, or the directory `VIRTUAL_LAB_MCP_AUTH_DIR` names, in a file for each server that only you can read, and are refreshed as they expire, so the next connection needs no sign-in. Anyone who can read the file can use the account, so treat it as you would a password. `sign_out_mcp("proto_hosted")`, or the server's URL, forgets a sign-in, so the next connection signs in again, as another account, say. `connect_mcp(..., may_sign_in=False)` is for a connection that is not to send anyone to a sign-in page, as one that checks a server: a server whose sign-in is not kept, or has run out and cannot be refreshed, fails at once and says so, without opening a browser or waiting.

Where no browser can be opened, as over SSH, the sign-in page's address is shown at the terminal, to be opened anywhere, and the address the browser ends at, which may not load, is pasted back. Where there is neither a browser nor a terminal, as in a script run in the background, the connection fails and says so: connect once where there is one, and the sign-in kept is used from then on. The time you take to sign in, up to 10 minutes, is not counted against `start_timeout` or `timeout`.

#### Proto's tools in code

Code in a session can also call Proto's tools as a Python library, rather than through its server, by running in the interpreter Proto is installed in. Its tools run on your Modal account with `device="modal"`, which finds your Modal token in your home directory, or on Proto's servers with `device="proto"`, which needs an API key in `PROTO_API_KEY`, from https://proto.evodesign.org/settings/workspace/keys:

```python
with LocalSession(
    Path("results/session"),
    python=str(Path.home() / ".local/share/uv/tools/proto-tools/bin/python"),   # where uv tool install puts it
    forward_env=("PROTO_API_KEY",),
    software={"proto_tools": "Proto: run_esmfold, run_alphafold2, and over a hundred more run_* functions, "
                             "each taking an Input and a Config, such as ESMFoldConfig(device='proto')."},
) as session:
    hold_meeting(..., session=session)
```

Code run this way is not asked about first, as a call through a server is, so give a session Proto's library only where you would let its code spend on your accounts.

### Serving tools over MCP

`virtual-lab-mcp` serves tools to any MCP client: Claude Desktop, Claude Code, Cursor, another agent, or `connect_mcp`. It can serve Biomni's tool functions, the `run_code` tool, the database and literature tools above, and tools of your own, in any combination. `python -m virtual_lab.mcp_server` is the same command.

```bash
virtual-lab-mcp --biomni-tools --code-tool --directory results/served            # over stdio, for a client that starts it
virtual-lab-mcp --biomni-tools --biomni-module database --data-lake data/biomni_data --directory results/served
virtual-lab-mcp --database-tools --tool my_tools:TOOLS --transport http             # at http://127.0.0.1:8000/mcp
```

For Claude Desktop, add the server to `claude_desktop_config.json`, giving the full path to the command if Claude does not find it on its own:

```json
{
  "mcpServers": {
    "virtual-lab": {
      "command": "virtual-lab-mcp",
      "args": ["--biomni-tools", "--code-tool", "--directory", "/Users/me/lab/served"]
    }
  }
}
```

Biomni's `create_mcp_server` runs its functions in the server's own process, passes every parameter whose type it does not recognise as a string, and reports a function that fails as if it had returned its error. Here:

- **Biomni's functions run in the sandbox.** Each call runs in one session, a `DockerSession` in the `full` image unless `--image-target` says otherwise, with its working directory at `--directory`, where files the functions write are kept. `--session local` runs them on your machine instead, with no isolation, and says so. `--data-lake`, `--no-network`, and `--forward-env` are as for `session_executor`. Only the modules that import in the session are served, and those that do not are named in a warning; `--biomni-module` serves only the modules given.
- **Parameters are typed.** Biomni's types become JSON schema, so an `int` is an integer, a `List[str]` an array of strings, and a `pd.DataFrame` an array of rows. Arrays are made the numpy arrays, data frames, or tuples the function expects before it is called. A default the schema can hold is given as the default, and a parameter that takes a function, which cannot be sent, is left out.
- **The session is shared.** With `--code-tool`, `run_code` runs code in the same session, which keeps its variables from one call to the next. Whatever a Biomni function returned last is there as `_`, and a file it wrote can be read.
- **Arguments are checked.** Each call's arguments are checked against the tool's parameters before it runs, and every problem found is listed for the client, which can correct its call.
- **What a tool returns is sent back whole.** A dict, or a pydantic model, is sent as the structured result as well as text. A Biomni function that returns nothing gives back what it printed instead.
- **A failure is a failure.** A tool that raises an error is reported as failed, with the error, and for a Biomni function with the end of what it printed. The server carries on.
- **Calls run at the same time**, each in a thread of its own, except that calls to one session wait their turn.

`--tool` serves one of the database tools by name (`--tool uniprot_lookup`), or `module:attribute` for a `Tool`, a list of them, what `connect_mcp` returns, or a function, which is made a tool as `tool_from_function` makes it. The module is imported from the working directory. In Python, `serve_mcp(tools)` serves a list of tools, and `create_mcp_server(tools)` returns the server for you to run.

Over HTTP the server listens at `127.0.0.1`, which only this machine can reach, and refuses requests that name another host, so a web page cannot reach it by DNS rebinding. To listen anywhere else, such as `--host 0.0.0.0`, set a token of at least 16 characters in `VIRTUAL_LAB_MCP_TOKEN`, in the environment or in the `.env` file. Every request must then carry it as `Authorization: Bearer <token>`, which `connect_mcp` sends from the `headers` of its config. A token can be set on this machine too. `--env-file` reads another `.env` file before the server starts.

The server stops when its client does, or at Ctrl-C or `SIGTERM`, and stops its session's container as it goes. A Biomni function runs on arguments a model chose, and with the network on it can reach anything the container can, so serve them in a session you would let any of the server's clients use.

### What these services will tell you that is not true

Each lookup refuses a particular confident wrong answer, because every one of these arrives as a successful response rather than as an error:

- **PubChem renamed its properties in 2025.** A request for `CanonicalSMILES` is answered with a key called `ConnectivitySMILES`, so code that reads back the name it asked for raises `KeyError` on a perfectly good response. `SMILES` is now the one carrying stereochemistry.
- **PubChem accepts a structure it has never seen**, answering 200 with `CID: 0` rather than an error. Only the identifier says nothing was found.
- **A SMILES cannot go in the URL path.** It carries `/` and `\` for stereochemistry, and percent-encoded into a path segment PubChem answers 400. Since PubChem keeps 400 for a request it could not parse, treating it as "no such compound" would report a real compound as nonexistent whenever a URL was built wrongly, so only 404 means missing here.
- **ChEMBL sends its numbers as strings**: `max_phase` arrives as `"4.0"` and molecular weight as `"180.16"`.
- **`max_phase` is -1 for 2,499 molecules** whose clinical status ChEMBL does not know, which sorts below a compound that was never tested.
- **Some ChEMBL measurements lost their units in standardisation.** The most potent IC50 against EGFR by raw value reads `5.012E-9 nM`, a hundred million times tighter than any real binding; its original value was 17.3 in units the record no longer names. Those rows are exactly the ones with no pChEMBL value, so `chembl_activities` requires one and orders by it.
- **Searching a gene symbol ranks the wrong thing first.** `EGFR` returns two protein-protein interactions and mouse EGFR above human EGFR, and restricting the organism alone does not fix it, which is why the target search tool passes `single_proteins_only` on by default. The library function it calls leaves the filter off unless asked, so a caller looking for a complex can still find one.

And the two literature searches read the same query in opposite ways, which is the one to know about:

- **arXiv reads loose words as alternatives.** `protein language model` sent as written returns 1,285,358 results, being everything mentioning any of the three words. Requiring all three returns 893 and the quoted phrase returns 344. The count misleads as much as the results do, so `arxiv_search` joins loose terms with `AND`, says in the report that it did, and passes through any query that already uses a field prefix or an operator.
- **Europe PMC reads the same words as requirements**, so a long query there finds less rather than more. Opposite defaults, same phrasing from an agent.
- **Europe PMC does not index arXiv**, which is why there are two searches rather than one. Most computational method work is only on arXiv, and much of it stays there.
- **A quoted identifier matches nothing.** `PMCID:"PMC3258128"` and `EXT_ID:"21937511"` both return zero hits while the same queries unquoted return the article, but a DOI needs the quotes because it carries slashes. The two that go unquoted are checked against their shape first, which is what makes that safe.
- **An unknown article is a 500, not a 404.** Asking Europe PMC for the full text of an article it does not hold gets the same status as an outage, so the retry logic spends three attempts and several seconds and then blames the service. `europepmc_fulltext` reads the record first, which says plainly whether the text exists.
- **`isOpenAccess` is the letter `Y` or the letter `N`**, as are ten other fields on the same record. `"N"` is a non-empty string, so every one of them is true when tested directly.
- **References are about 28% of an article's body text** and are a list of other people's titles, which reads to a model as though this article had discussed all of them. They are left out, along with funding and author contributions, and the report says which sections were dropped.
- **ElementTree expands internal entities.** That was checked rather than assumed. Neither service has any reason to send a `DOCTYPE`, so one is refused before parsing rather than the expansion being bounded.

**PubChem needs a particular TLS handshake.** Its edge answers this library's ordinary handshake with 503 and a "server too busy" body, while reporting the service as healthy to `curl` from the same address in the same second. `web.HOST_CIPHERS` offers it a cipher list it accepts. The connection is still TLS 1.3 with certificate verification on; only the list offered in the handshake differs. No other service needs this.

### Reading the project's own data

The tools above fetch what is known. A project also has data of its own: a spreadsheet from a collaborator, a table downloaded by hand, a file written by the last piece of code that ran. An agent that cannot see inside those files writes code against the columns it imagines are in them.

`inspect_data_file` answers the first question about a file, which is always the same question, without a round trip through the sandbox. It reads `.csv`, `.tsv`, `.tab`, `.txt`, `.xlsx`, and `.xlsm`, reports the shape and what each column holds, and shows the first few rows. It does not return data for computing with; the sandbox is still where analysis happens.

Excel files are read without a dependency, straight out of the archive, so there is nothing to install and nothing that runs while a file is being opened.

The filename comes from a model, so it is treated the way a filename a meeting asks to write is: checked for traversal, resolved, and checked again against the directory it must be inside. Resolving first also settles symbolic links, so a link pointing out of the directory is refused rather than followed.

### Looking at images and the pages of a PDF

A figure, a slide, a scanned page, or a screenshot says what the text of its file leaves out, and a model that is only sent text cannot read it. The lead is given `view_image`, which takes a file in the working directory, a question, and for a PDF the pages (`[45, 46, 47]`), and answers with what the question asks about. It does so by asking the lead's own model in a request of its own (`Chat.ask_about_images`): the images are sent in that request alone, so that they are not kept in the conversation, where every later request would carry them again, and what the request costs is counted and held to the conversation's spending limit like any other. What the lead reads is the model's text.

- **Only a model that reads images is given it.** For a model whose source is OpenRouter, that is what OpenRouter's list says it takes in (`architecture.input_modalities`, which the list kept in the workspace records); for the others it is told by the name, and a local or custom model is not assumed to. `accepts_images(model)` says which.
- **It stays inside the working directory,** as `inspect_data_file` does: the path is resolved, links are followed before it is checked, and what the code prints (`/workspace/uploads/slides.pdf`) is understood. Only PNG, JPEG, GIF, and WebP images and PDFs are opened, and none larger than 200 MB.
- **Pages are drawn on this machine** by pypdfium2, at a size where a model reads small print (the longest side is 1600 pixels), and every image is brought down to that size, flattened onto white, and sent as a PNG, or a JPEG if that is over 3 MB. An image already that small, of the kind its name says, and with pixels every provider takes is sent as it is. A 16-bit image is scaled to 8 bits rather than cut off, a moving one is sent as a still, and one of more than 80 million pixels is refused before it is decoded. At most six images or pages are sent at a time, and a PDF of more than one page has to be told which. A tool that fails, or a file that cannot be read, says why to the lead, which can correct the call.
- **Without pypdfium2 and Pillow** a PDF cannot be drawn and a large image cannot be made smaller; the lead is told so, with the line that installs them, and the rest of the conversation goes on.

### What a data file will tell you that is not true

The point of reading the file before the code is written is not the shape. It is that a table misleads quietly, and every one of these is a file that loads without complaint:

- **One `<0.001` makes the whole column text.** A measurement below the assay's detection limit is written as a bound, and a single one of them turns a column of numbers into a column of strings. Every mean taken afterwards is wrong or skipped, and the values dropped are not missing at random: they are the strongest and weakest samples.
- **A spreadsheet turns gene symbols into dates.** SEPT2 becomes 2-Sep as it is typed, and the symbol cannot be recovered from the file afterwards. A column holding both dates and text is the signature, so that is what is reported.
- **A date in a spreadsheet is an ordinary number.** `45902` is 2025-09-02 only if you follow the cell's style to its number format, and Excel records no flag saying a format means a date. Without that chase a corrupted gene column reads as a column of five digit integers.
- **A byte-order mark renames the first column.** Read as `utf-8` rather than `utf-8-sig`, the header is `\ufeffgene` and never matches `gene`.
- **Two columns with the same name leave one of them gone.** Readers that key rows by name keep the last, without a word.
- **Identifiers lose their leading zeros.** `00123` read as a number is `123`, and stops matching anything.
- **A row in a spreadsheet holds only its non-empty cells.** Taken in order rather than by cell reference, every value after a blank moves one column left, which produces a table that is wrong and looks right.
- **The cell reference is optional.** Writers that stream cells out in order leave it off, and a reader that places cells only by reference reads the whole sheet as empty. A cell without one goes in the column after the one before it, as Excel reads it.
- **A cell's text can be split into runs.** Asking for the first `<t>` under it returns nothing at all, because the runs are between them.
- **`float()` accepts more than anyone means by a number.** `float("1_000")` is 1000.0, `float("nan")` and `float("inf")` both succeed, and `float("١٢٣")` is 123.0. A column whose missing values are spelled `nan` is otherwise reported as numeric.
- **`csv.Sniffer` cannot read a one-column file** and raises rather than saying so, which a list of gene names is.
- **cp1252 decodes every possible byte**, so it never fails and a wrong guess at the encoding is silent. UTF-8 first is the only ordering that is ever right.
- **A 204 KB spreadsheet can declare a 200 MB sheet.** That was measured. The size is recorded inside the archive by whoever wrote it, so the cap is on the bytes actually unpacked.
- **A cell's position costs nothing to write.** A 5.7 KB sheet with one cell in column XFD of each row pads out to 600 MB, which no byte cap sees. Rows are held only as far as their last value, the cap is on the cells held, and a column past XFD is refused as damage.

A note on `uniprot_search`: `reviewed_only` is off by default. Curation covers a small fraction of UniProt, and for some classes of sequence it covers none of it, so a search for a nanobody with it on returns proteins whose reference titles mention one while filtering out every real camelid VHH.
