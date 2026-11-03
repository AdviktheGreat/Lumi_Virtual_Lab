# Running code

[Back to the README](../README.md). How the code that agents write is run: in a Docker sandbox, in a shared session, with Biomni's software, data lake, and tools.

## Running the code that agents write

Agents can write code, and Lumi can run it. Because that code is written by a model and read by nobody before it runs, it is executed in a container rather than on your machine. Install [Docker](https://docs.docker.com/get-started/get-docker/) and make sure it is running.

```python
from pathlib import Path
from virtual_lab import DockerExecutor, run_files, save_artifacts

paths = save_artifacts(save_dir=Path("results"), save_name="discussion", artifacts=code)
results = run_files(
    directory=paths[0].parent, files=code.files, executor=DockerExecutor()
)
```

The container has no network access, no view of your filesystem beyond the meeting's own output directory, a read-only root filesystem, and hard limits on memory, processes, and wall clock time. It is not given your environment, so the code cannot read your API key. Scripts that genuinely need to reach the internet require `DockerExecutor(allow_network=True)`. The one place besides the meeting's directory that code can write is a scratch space at `/tmp`, which is also its home directory. It is emptied when the container stops, so a session that is to keep a library installs it with `--target` under the meeting's directory.

Docker mounts a scratch space of this kind so that nothing in it can run, and this sandbox turns that off, so that a library `pip install` adds for the user, such as one with a compiled part, loads from it. Nothing is lost by that: code can run what it writes to the meeting's directory in any case, and the container has no capabilities and cannot gain any.

The first run pulls the sandbox image, which takes a minute. Files the code writes into its working directory appear on your machine; everything else it does is discarded with the container.

### Biomni's software and data in the sandbox

The default sandbox image is plain Python. For the software Biomni's agent works with, build a sandbox image from Biomni's own environment files, which ship with this package, and fetch Biomni's data lake to mount into it:

```python
from pathlib import Path
from virtual_lab import SANDBOX_PLATFORM, DockerExecutor, build_sandbox_image, download_data_lake

image = build_sandbox_image("bio")
lake = download_data_lake(Path("data/biomni_data/data_lake"))
executor = DockerExecutor(image=image, data_lake=lake.directory, platform=SANDBOX_PLATFORM)
```

| Stage | Adds | Size, roughly |
| --- | --- | --- |
| `base` | Python 3.11 with Biomni's analysis libraries (pandas, scikit-learn, statsmodels, transformers, and the rest of its `environment.yml`) | 3 GB |
| `bio` | Biomni's bioinformatics tools and libraries: samtools, BWA, BLAST, Bowtie 2, scanpy, RDKit, pysam, scvi-tools, and the rest of its `bio_env.yml` | 18 GB |
| `bio-r` | R 4.5 with the packages analyses of published studies most often use (tidyverse, lme4, glmnet, survival, vegan, DESeq2, edgeR, limma, clusterProfiler, fgsea, the human and mouse annotation databases, and others, listed in `bio_r_env.yml`), and the Python packages `bio` lacks: pydeseq2, PhyKIT, mygene, harmonypy, and ete3. This stage is this project's, not Biomni's | about 1.5 GB more than `bio`, built in minutes |
| `full` | R with Biomni's CRAN and Bioconductor packages, its command-line tools (PLINK 2, IQ-TREE, GCTA, and others), and the software added in Biomni 0.0.8 | tens of GB, hours to build |

Each stage includes the one before, except that `bio-r` and `full` are both built on `bio`, so `full` does not have what `bio-r` adds. `bio-r` puts R in an environment of its own, `r_e1`, after Biomni's on the path, so `python3` is still Biomni's and `Rscript` is that environment's; its packages come built from conda-forge and Bioconda, which is why it takes minutes where `full`, which compiles Biomni's R packages from source, takes hours. An image is built once and reused, and is tagged with the package version and platform, so that an upgrade builds a new one. Biomni publishes its environment for x86-64 Linux only, so the images are built for `linux/amd64` even on an ARM machine, where Docker runs them under emulation (slower, but complete). Pass the same platform to `DockerExecutor`, as above, or Docker warns about the mismatch on every run's stderr. `build_sandbox_image("base", platform=None)` builds for the machine's own architecture instead, under a tag of its own; run it with `DockerExecutor(platform=None)`. The `bio`, `bio-r`, and `full` stages do not build on ARM.

Biomni's installers for R and its command-line tools print a failure and go on, and report success, so the last step of `full` checks that every R package they name, and every program in `cli_tools_config.json`, is there, and a build that is missing one fails. Building the stage for x86-64 found what Biomni's scripts assume a machine has, and the Dockerfile now installs it: `cmake` (for `lme4`), zlib's headers (for BWA), `zip` (for HOMER), and the libraries xz, libxml2, and netcdf for R's `igraph`, `Rhtslib`, `XML`, and `ncdf4`, which `clusterProfiler`, `dada2`, and `xcms` need. Two programs are installed differently. GCTA is version 1.94.1 from its authors' GitHub release, checked against a hash, where Biomni's script asks for 1.94.4 from a server that gives the file only to a browser. HOMER is installed with its installer's own command, since Biomni's script gives it options it no longer takes and so installs nothing.

The data lake is 76 files and about 11 GB. `download_data_lake` takes a list of names to fetch only some of them (see `DATA_LAKE` for what each holds), skips files already present, and never leaves a partial file under a real name, so an interrupted download is resumed by calling it again. The sandbox sees the directory read-only at `/biomni_data/data_lake`, which is also in the `BIOMNI_DATA_LAKE` environment variable. Keep it outside the directory meetings are saved to: a data lake that overlaps the directory code runs in is refused, since the code could write to it there.

If you do not have Docker, `LocalExecutor` runs code directly on your machine instead. It is not a sandbox: code run through it can read and write any file you can. It applies a timeout and withholds your API key, and that is the extent of it.

### A shared session for exploratory analysis

A finished script is run once. An analysis is explored instead: load the data, look at it, decide what to do next. A session keeps one Python interpreter running for the length of a meeting, the way Biomni's agent keeps its REPL, so a table one agent loads is still there for the next agent to use:

```python
from pathlib import Path
from virtual_lab import DockerSession, session_executor, session_tool

with DockerSession(Path("results/session"), executor=session_executor("bio")) as session:
    session.run("import pandas as pd\ndf = pd.read_csv('counts.csv')")
    print(session.run("df.shape").output)          # the value of a final expression is printed
    session.run("samtools --version", language="bash")
    tool = session_tool(session)                   # a run_code tool to give the meeting's agents
```

Each run returns a `CellResult` holding what the code printed (standard output and standard error together, in order), its status, the figures it drew, and the files it wrote. Code that fails or runs out of time is a result, not an exception. A matplotlib figure left open is saved under `plots/` and closed. R and bash code runs as a fresh `Rscript` or `bash` process in the same directory each time, as it does in Biomni.

By default a session runs in Biomni's `full` image with the network on, since Biomni's agent queries databases as it works. Pass `session_executor("bio")` or `session_executor("base")` for a stage you have built, `allow_network=False` to cut the network, and `data_lake=` to mount the data lake. Everything else about the container matches `DockerExecutor`. The limits are higher (8 GB of memory, 4 CPUs, 2 GB of scratch space) because a session holds a whole analysis in memory at once.

Code is stopped at its time limit (`timeout=`, 300 seconds by default) and the session keeps everything it had defined. Code that ignores the stop, and code that crashes the interpreter or runs out of memory, costs the session: the result's status is `"lost"`, and the next run starts a fresh interpreter, which its `start` number shows. Starting a session in an image Docker emulates takes about half a minute. `LocalSession` runs the same interpreter on your machine, with no isolation, like `LocalExecutor`. Pass `python=` to use an environment already installed there, such as Biomni's `biomni_e1`.

### Running code during a meeting

Give a meeting a session and its agents can run code in it as they talk, checking a claim against the data or computing a number instead of estimating it:

```python
from virtual_lab import DockerSession, hold_meeting, session_executor

with DockerSession(Path("results/session"), executor=session_executor("bio")) as session:
    result = hold_meeting(
        meeting_type="team",
        agenda="Which genes separate the two clusters in counts.csv?",
        save_dir=Path("results"),
        team_lead=principal_investigator,
        team_members=(bioinformatician, scientific_critic),
        num_rounds=2,
        session=session,
    )
```

Everyone in the meeting shares the one interpreter, so what one agent loads or computes, the next can use. By default each agent runs code by calling a `run_code` tool. With `code_actions="tags"` it instead writes the code between `<execute>` and `</execute>` in its reply and is answered between `<observation>` and `</observation>`, as Biomni's agent is. That works with any model, including ones served without tool calling. A block starting with `#!R` is R and one starting with `#!BASH` is a shell script.

An agent may run code, or call tools, up to 20 times in a turn with a session (5 without), after which it is asked to answer without them; `max_tool_iterations=` changes that. The session is started before the first request, so one that cannot start costs nothing, and it is left running afterwards, so the next meeting can pick up where this one left off. Every piece of code the meeting ran, with its full output, is saved to `sessions/<save_name>.json`, and each turn in the meeting's record lists the cells it ran and how each ended. The transcript shows the code beside its output.

### Biomni's tools, data, and know-how in a meeting

Biomni's package ships with this one, unchanged, so code in a session can import its tool functions (223 of them, from database queries to CRISPR screen design) the way Biomni's agent does: `from biomni.tool.database import query_uniprot`. The package is mounted read-only into the container. It is not imported on your machine: its descriptions are read as data, and only its know-how loader, which needs nothing beyond the standard library, is run there. Each meeting tells its agents what they can use: Biomni's tools, the data lake files that are mounted, the software in the image, and Biomni's know-how documents, which are given in full.

virtual_lab adds guidance of its own, as skills that come with it, in `virtual_lab/builtin_skills` (see [Skills](tools-and-skills.md#skills)). It is general practice for kinds of analysis where a number is easy to get wrong: reading the sign of dependency scores, enrichment analysis, sample ids and PCA, multiple-testing corrections in small panels, variant call statistics, what a tool's function computes, and a checklist for any question that asks for a number from data. A conversation has them as skills, which its lead is told of in every request. A meeting has no skills, so `all_know_how()` lists them after Biomni's documents (`builtin_know_how()` is the part that is theirs), and a meeting is given the ones its task suits, as it is for Biomni's. A conversation that has one as a skill is not offered it again as know-how. To add one, put a folder with a `SKILL.md` there; see `builtin_skills/README.md`.

Biomni lists all of its software to its agent, whose environment has all of it. A session may run in the `bio` or `base` stage, which has only some, so before a meeting lists anything it checks, in the session, which of Biomni's software is installed and which of its tool modules import. It lists only those, and its record names what was left out and why: in the `bio` stage, for instance, R and its packages, and the genomics and bioimaging tools, whose modules need libraries only the `full` stage has. The check takes a few seconds, is not part of the session's history, and runs the imports in a process of its own, so it leaves the session as it found it. If it cannot be done, everything is listed, with a warning.

Listing everything adds about 40,000 tokens to every request, so by default the agent who closes the meeting is first asked which resources the agenda needs, as Biomni's agent asks before each task, and only those are listed. That costs one request of about 12,000 tokens, which counts towards `max_cost` and the meeting's usage. An answer that cannot be read lists everything, with a warning.

```python
from virtual_lab import Resources, available_resources

hold_meeting(..., session=session)                     # the lead picks what the agenda needs
hold_meeting(..., session=session, resources="all")    # list everything
hold_meeting(..., session=session, resources="none")   # list nothing

everything = available_resources(session)
chosen = Resources(tools=tuple(t for t in everything.tools if t["module"] == "biomni.tool.database"))
hold_meeting(..., session=session, resources=chosen)   # list exactly these
```

Tools and software are listed only when the session can import Biomni's tools (`biomni_tools=False` in `session_executor` or `LocalSession` turns this off), and data lake files only when the data lake is mounted. The meeting's record says which resources were available, which were listed, and, when they were retrieved, what the agent answered and what that request cost.

About forty of Biomni's tools call a model themselves, most of them the database tools that turn a question into a query. They need an API key inside the container, which is otherwise given none. Pass the names of the variables to forward, and set Biomni's own settings with `environment`:

```python
executor = session_executor(
    "bio",
    data_lake=lake.directory,
    forward_env=("ANTHROPIC_API_KEY",),
    environment={"BIOMNI_LLM": "claude-sonnet-4-5"},
)
```

A forwarded variable is passed to Docker by name, so its value never appears in a command line, and the record lists only its name. It must be set on your machine, or the session refuses to start. Code in the session can read it, and with the network on it can send it anywhere, so forward only a key you are prepared to have used by the code agents write. Values in `environment` are recorded in full, so they are not for secrets.

`commercial_mode=True` leaves out the data lake files and know-how documents that Biomni's commercial mode leaves out because their licenses forbid commercial use, and describes the data lake as that mode does. `download_data_lake(directory, names=commercial_data_lake())` fetches only the files it uses. It does not check the licenses of the tools themselves or of the databases they query; see `license_info.md` in `virtual_lab/sandbox/biomni_package`.
