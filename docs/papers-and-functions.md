# Growing the toolset from papers

[Back to the README](../README.md). Reading papers for the tasks, databases, and software in them, and writing a function for each task.

## Growing the toolset from papers

Biomni grows its toolset by reading papers for the computational tasks, databases, and software in them. `read_paper` and `extract_paper_findings` do the same reading. A PDF needs pypdf: `pip install -e ".[papers]"`. Plain text, Markdown, and LaTeX files need nothing.

```python
from virtual_lab import extract_paper_findings, read_paper

reading = extract_paper_findings(read_paper("paper.pdf"), model="gpt-5.2", max_cost=1.0)
for task in reading.findings.tasks:
    print(task.task_name, "|", task.inputs, "->", task.outputs)
print(reading.chunks, reading.cost, reading.failed_chunks)
```

- The text is cut into chunks of 4,000 characters with 400 repeated between them, as Biomni cuts it, at paragraph breaks where it can, then line breaks, sentences, and words. Each chunk is read with Biomni's guidelines: only tasks that are common across biomedical research, with clear inputs and outputs, implementable with Python or Linux code, and named with their exact methods. Then the findings of every chunk are merged, one to each name, and one more request applies the same filter to the paper as a whole.
- Every answer is asked for in a schema (`PaperFindings`: tasks, databases, and software, each with the fields Biomni records), and one that does not fit it is not used. Biomni reads each chunk as free text and parses the consolidation's reply as JSON, and when it cannot, returns the raw reply as a single "task" with an `error` field. Here a chunk the model refuses or cannot answer in the schema is recorded in `reading.failed_chunks` with why, and the rest are used; a paper none of whose chunks can be read is refused with `PaperReadingError`.
- Findings too many for one request, more than `max_consolidation_chars`, are consolidated in batches and then again as a whole, where Biomni joins every chunk's reply into one request, which fails once they outgrow the model's context. If the consolidation fails, `PaperReadingError` holds what the chunks found, merged but not filtered, in its `findings`.
- A paper is read as far as `max_chars` (200,000, as Biomni reads), cut at the end of a sentence, and `reading.truncated_from` says how long it was. A file over 100 MB, a PDF over 500 pages, a PDF that needs a password to open, and a file that is not a PDF, text, or Markdown are refused. A PDF locked only against copying and printing, as many publishers' are, is read.
- `max_cost` is checked before every request and stops the reading with `PaperBudgetExceededError`, which holds in `findings` what the chunks read so far showed, unfiltered, so that what was paid for is not lost. To keep one limit across many papers, pass the same `MeetingUsage` as `usage` to each. A model whose price is not known cannot be given a limit.
- A PDF's text is as pypdf finds it, so the columns of a two-column paper and the labels of its figures can be mixed into the prose, as in what Biomni reads. Read the tasks as suggestions to check, not as facts about the paper.

### Reading many papers, and counting what they share

Biomni reads the bioRxiv preprints of 25 subjects that have been published, and counts how many papers each task, database, and package turns up in, so that the ones in hundreds of papers can become tools. `read_papers` does the reading, and `virtual-lab-papers` runs it from the command line:

```bash
virtual-lab-papers read papers/ runs/mine --max-cost 5
virtual-lab-papers biorxiv runs/neuro --since 2024-01-01 --subject neuroscience --limit 20 --max-cost 5
virtual-lab-papers biorxiv runs/all --since 2024-01-01 --all-subjects --limit 100 --max-cost 50
virtual-lab-papers summarize runs/mine
virtual-lab-papers combine runs/neuro runs/mine --output runs/total
```

```python
from virtual_lab import biorxiv_papers, papers_in, read_papers, read_biorxiv_subjects

report = read_papers(papers_in("papers"), "runs/mine", model="gpt-5.2", max_cost=5.0)
report = read_papers(biorxiv_papers("2024-01-01", subject="neuroscience", limit=20), "runs/neuro")
everything = read_biorxiv_subjects("runs/all", "2024-01-01", papers_per_subject=100, max_cost=50.0)
```

- **Where the papers come from.** A directory of PDF, text, Markdown, and LaTeX files (`papers_in`, with `--recursive` for the folders within it), or bioRxiv's listing (`biorxiv_papers`), by period and subject, the first ones or a random sample with a fixed seed, as Biomni takes them. Biomni then downloads each PDF from bioRxiv, which now answers a script's request with HTTP 429 however politely it is made, and this does not work around that. The listing is bioRxiv's API, which does answer, and the text is that of each preprint's published version where Europe PMC holds it open access. A preprint that has not been published, or whose published version is not open, is recorded as `unavailable` and not read; in a trial on six January 2024 neuroscience preprints, half were open. That text is the abstract and the sections of the article, without its references, which is not quite what bioRxiv's PDF holds. To read papers from anywhere else, download them and point `read` at the directory.
- **A run that stops carries on.** Each paper's result is saved under `results/` as soon as it is read, so running the same command again reads only the rest, and nothing is paid for twice. A directory holding a run with another model or other reading options is refused, since its results could not be counted with these. A saved result is used only for the same paper: the same DOIs and, for a file, the same contents (a SHA-256 is kept with it), so the same files moved to another folder carry on, a file that has changed since is read again, and another paper under the same key (the same file names in a different folder, say) is refused before anything is read, rather than counted as the first. A paper that failed or had no text is not read again unless `--retry-failed` is given. A file's key is its path, with a few characters of a hash added when the path has anything but letters, digits, `.`, `_`, and `-`, so it does not change when other files are added. Ctrl-C is safe: the report and the counts are written as it ends.
- **What it spends.** `--max-cost` is for the run, including every subject, and a paper it stops is left unsaved to be read next time. `--max-cost-per-paper` fails the paper that reaches it and goes on. Three failed papers in a row stop the run, since that is more likely a missing key or no network than three bad papers (`--max-consecutive-failures`, or `--keep-going`); a paper with no text to read does not count. A paper that fails after some chunks were read keeps what they showed in its result, unfiltered and not counted. The command exits 0 when it did everything, 1 when a run stopped early, 2 on an error, and 130 on Ctrl-C.
- **What it writes.** In the run's directory: `results/<key>.json` for each paper, `report.json`, `run.json` (what it was read with), `tasks_summary.csv`, `databases_summary.csv`, and `software_summary.csv` with a row for each thing found in each paper, and `frequency_summary.json` with how many papers each name was found in, the most common first. Names are compared as `normalize_name` compares them, so `DESeq2` and `deseq2` are one, and one paper counts a name once. `combine` adds the counts of several runs into `combined_summary.json` and `tasks_frequency.csv`, `databases_frequency.csv`, and `software_frequency.csv`; a paper in two of them is counted twice. A cell that a spreadsheet would read as a formula, because a paper's text can make a model write `=...` or `@...`, is written with a leading quote.

### Writing a function for each task

Biomni turns the tasks its papers turn up into code. Its `FunctionGenerator` asks a model, as a senior Python engineer, for the code that does a task, keeps the first code block of the reply in a file named for the first six words of the task, and leaves a person to read it and add it to Biomni's tool modules. `generate_function` asks the same way, and `virtual-lab-functions` does it for every task a run found:

```bash
virtual-lab-functions generate functions/ --tasks tasks.json --max-cost 5
virtual-lab-functions generate functions/ --tasks runs/total --min-papers 5 --limit 20 --verify docker
virtual-lab-functions generate functions/ --task "Align paired-end reads with BWA-MEM"
virtual-lab-functions list functions/
```

```python
from pathlib import Path

from virtual_lab import DockerExecutor, DockerSession, function_tasks, generate_functions, tools_from_saved_functions

tasks = function_tasks("runs/total", min_papers=5, limit=20)
report = generate_functions(tasks, "functions", model="gpt-5.2", executor=DockerExecutor(), max_cost=5.0)

with DockerSession(Path("results/session")) as session:
    tools = tools_from_saved_functions("functions", session=session, verified_only=True)
    hold_meeting(..., tools=tools)    # the agents call the functions as tools, which run in the sandbox
```

- **The tasks.** Biomni's file, `{"tasks": ["description", ...]}`, or a list; a summary that `virtual-lab-papers` wrote (`frequency_summary.json` or `combined_summary.json`), in the order of its counts, with `--min-papers` and `--limit`; objects with a `task_name` and what it does, takes, and gives; or a directory papers were read into. For a directory, what the papers say of each task (what it does, takes, and gives, how it is implemented, and its standard methods) is added to what the model is told, where Biomni's file of names gives it only the name. Tasks that differ only as `normalize_name` compares names are written once.
- **What is asked.** Biomni's six requirements, in its words, and two more, because a function is going to be called as a tool by a program that sends JSON: one function named for the task, with a docstring and a type hint on every parameter of a type JSON has (a file is taken as a `str`), returning a value that can be written as JSON; and a file that only defines things when it is imported, with anything that runs the task under `main()`. The name is Biomni's, with a prefix `task_` for one that begins with a digit, a suffix `_task` for one that is a Python keyword or a standard module, and a few characters of a hash for tasks that share their first six words.
- **What is checked.** The reply is read, and none of it is run: the code must parse, define that function, document it, type every parameter as a tool needs, and run nothing when imported (no bare calls or loops at the top level, and no call in a default, which would be computed once on import), and have no decorator. Everything wrong with it is given back to the model with its code, so that it can correct it, up to `--max-attempts` (3) times, and no more if a correction fails for the same reason as the one before. A reply that ran out of tokens, or was never closed, is asked for again with less. `--verify docker` also imports the file in a sandbox container, which finds a library the code needs and the image does not have, and that failure is given back too. `--verify local` imports it on this machine with no isolation, for code you would run anyway.
- **What is saved.** `functions/<name>.py` for a function that passed, and `functions/records/<name>.json` for every task: what it was asked, the model, the attempts, what it cost, and its status. `verified` is a function that was imported in an executor, `unverified` one that was only read, and `failed` one that could not be made to pass, which has the last code written for it in its record and no file. Each is saved as soon as it is written, with `report.json` of the run.
- **A run that stops carries on.** Running the command again writes only what is not saved. A function saved without being run is imported when `--verify` is given later, and written again only if that fails. A task said differently is written again, but never over a file that has been changed by hand, or one that no record speaks of: that is refused, before the model is asked for anything. A function that failed is not tried again unless `--retry-failed` is given, and a failure that is not the task's, such as a wrong key, no network, or a response that did not report its usage so that a limit could not be kept, is not saved at all.
- **What it spends.** `--max-cost` is for the run, and a function it stops is left unsaved to be written next time. `--max-cost-per-function` fails the function that reaches it and goes on. Three failed functions in a row stop the run (`--max-consecutive-failures`, or `--keep-going`). The command exits 0 when it did everything, 1 when a run stopped early or a function could not be written, 2 on an error, and 130 on Ctrl-C.
- **As tools.** `tools_from_saved_functions` (and `tool_from_source` for one) makes a `Tool` of each saved function by `tool_from_function`, from its own signature and docstring, which are read from the code's syntax, so making the tool runs nothing of what the model wrote. A call runs the function in the session you give, with the arguments sent as JSON and the result sent back as JSON, so in the sandbox if it is a `DockerSession`. `run_here=True` runs it in this process instead, as you, which is for code you have read. A function that fails raises `FunctionToolError` with its error and the end of what it printed. The file is read as it is now, so a function you corrected by hand is the one used, in a session that is still open as well.

The functions are a model's, written from what a model made of a paper. Read them before you rely on them, as Biomni's own are read before they are added.
