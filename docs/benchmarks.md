# Benchmarks

[Back to the README](../README.md). Measuring an agent or a team on Biomni's benchmarks, and the lab on BixBench-Verified-50.

## Measuring an agent or a team on Biomni's benchmarks

Biomni is measured on three benchmarks, and so can an agent or a team here, on the same questions and by the same rules. Reading them needs `pip install -e ".[eval]"`. Their files, about 4 MB, are fetched once from where Biomni fetches them, under their own licenses, and are not shipped with this package:

```python
from pathlib import Path
from virtual_lab import BiomniEval1Benchmark, HumanitysLastExam, LabBench, download_benchmarks

download_benchmarks(Path("data/benchmarks"))
eval1 = BiomniEval1Benchmark(Path("data/benchmarks"))        # 433 questions in 10 tasks
dbqa = LabBench(Path("data/benchmarks"), "DbQA")             # 60 questions; "SeqQA" has 70
hle = HumanitysLastExam(Path("data/benchmarks"))             # 52 questions
```

| Benchmark | Questions | Scored by |
| --- | --- | --- |
| Biomni-Eval1 | 433, in ten tasks: CRISPR delivery, causal genes from three GWAS sources, variant prioritization, LAB-Bench's DbQA and SeqQA, patient gene detection, rare disease diagnosis, and screen gene retrieval | Each task's own rule, as in Biomni's `BiomniEval1`: a letter, gene, or variant compared as Biomni compares it, a diagnosis by its OMIM ID, and a patient's genes by any overlap. Reported overall and per task. |
| LAB-Bench | DbQA or SeqQA, from the file Biomni's `lab_bench` reads (`subset="test"`), its sampled file, or all of LAB-Bench (`subset="all"`, 520 and 600) | Accuracy, coverage, the share refused, and precision, as Biomni computes them |
| Humanity's Last Exam | The 52 multiple choice questions in biology and medicine that Biomni samples | Accuracy |

Each file is checked against a hash pinned in `virtual_lab.constants` whenever it is read, and one that differs is refused, so two scores made here were made on the same questions. LAB-Bench's options are shuffled exactly as Biomni shuffles them, with a refusal option added, so each question has the letters it has in Biomni and in Biomni-Eval1. Five of the Humanity's Last Exam questions refer to an image that Biomni does not show its agent, and neither does this; their `metadata["has_image"]` is true, so they can be left out.

`run_benchmark` asks each question of an agent or a team, reads the answer out of what was said, and scores it:

```python
from virtual_lab import DockerSession, SingleAgent, TeamMeeting, run_benchmark, session_executor

with DockerSession(Path("results/session"), executor=session_executor("bio")) as session:
    report = run_benchmark(
        eval1,
        SingleAgent(bioinformatician, code_actions="tags"),
        save_dir=Path("results/eval1"),
        extractor="gpt-5.2",
        session=session,
        max_cost=50.0,
    )
print(report.metrics["accuracy"], report.cost)

run_benchmark(hle, TeamMeeting(principal_investigator, (geneticist, scientific_critic), num_rounds=2), ...)
```

- `SingleAgent` holds an individual meeting on each question, with the question as its agenda, and by default no rounds of criticism, which is how Biomni's agent answers. `TeamMeeting` holds a team meeting, one round by default. Both take anything else `hold_meeting` does, such as `code_actions`, `resources`, or `tools`. Any function of a question and a `SolverContext` that returns a transcript, or an `Attempt`, can be the solver instead.
- The answer is read as Biomni reads it: in one more request, a model is told it is "evaluateGPT", given the question as the task's output requirement and the whole transcript as the history, and asked for the answer in the benchmark's schema for the question. `extractor` names that model; Biomni uses the agent's own. It runs at temperature 0, which `extractor_temperature` changes.
- A session is shared by every question, as Biomni's agent keeps one interpreter across its tasks, so a question can find what an earlier one left in it. Pass a function that makes a session, such as `lambda: DockerSession(...)`, for a fresh one per question, closed when the question is done.
- `max_cost` is what the run may spend, and `max_cost_per_question` what one question may. A question is not started once the run's limit is spent, and one running when it is reached is left unfinished. A question that reaches its own limit fails, and the run goes on. Both count the reading of the answer.
- Each question's result is saved under `save_dir/results/` as soon as it is scored, with its answer, score, usage, cost, and where its transcript is. Running again on the same directory carries on where the last run stopped and asks nothing already answered. A directory holding a run of a different benchmark, solver, or extractor is refused, so its results are never mixed with another's.
- A question whose solver fails, or whose answer cannot be read, is saved as a failure and scored 0, and the run goes on. Three failures in a row stop it, since that is more likely a missing key than three hard questions; `max_consecutive_failures` changes that. `retry_failed=True` asks the failed questions again.
- The report, also saved as `summary.json`, holds the benchmark's measures, how many questions were finished and failed, what the finished ones cost, what this run spent, and why it stopped, if it did.

Code written against Biomni's own classes runs against these: `BiomniEval1` has the methods of Biomni's (`evaluate`, `get_instance`, `list_tasks`, `get_task_stats`, `batch_evaluate`, `get_instances_by_task`), and `LabBench` and `HumanitysLastExam` have `get_example`, `get_iterator`, `evaluate`, and `output_class`.

`tests/test_benchmark_parity.py` checks this against Biomni's own classes, on the real files: the same questions, prompts, answers, tables, and schemas, and the same score for over 7,000 answers to Biomni-Eval1 (the right answer written several ways, and many that are wrong or are not answers), and the same measures for LAB-Bench and Humanity's Last Exam answers. It is skipped unless it is told where the files and a clone of Biomni are, and scikit-learn, which Biomni's scoring uses, is installed:

```bash
pip install scikit-learn
git clone https://github.com/snap-stanford/Biomni
VIRTUAL_LAB_BENCHMARK_DIR=data/benchmarks VIRTUAL_LAB_BIOMNI_DIR=Biomni pytest tests/test_benchmark_parity.py
```

The one difference found: when a model refuses every LAB-Bench question, Biomni's precision is the mean of nothing, which current scikit-learn raises on, and here it is `None`.

## Measuring the lab on BixBench-Verified-50

[BixBench](https://arxiv.org/abs/2503.00096) (FutureHouse, Apache 2.0) asks questions that need real analysis of real data, each with the files of a published study. [BixBench-Verified-50](https://huggingface.co/datasets/phylobio/BixBench-Verified-50) (Phylo) is 50 of them, over 33 datasets, whose wording and answers experts checked. Unlike Biomni's benchmarks, a question comes with files, and a person would answer it in a conversation with the lab, so `virtual-lab-bixbench` asks each one of a running server, in a conversation of its own, and nothing in it says it is a benchmark. Install it with `pip install -e ".[eval]"`.

The dataset is gated. Accept its terms on its Hugging Face page while logged in, make a token with Read access at <https://huggingface.co/settings/tokens>, and give it to your own terminal with `hf auth login`, so that it is never typed anywhere else:

```bash
hf auth login
virtual-lab-bixbench fetch ~/bixbench                  # the questions and 33 datasets, 2.8 GB; --limit 3 or --only bix-12-q2 fetch fewer

virtual-lab-server --workspace ~/bixbench_workspace --token bench      # a workspace of its own, in another terminal
virtual-lab-bixbench run ~/bixbench --workspace ~/bixbench_workspace --token bench \
    --model openrouter/moonshotai/kimi-k3.1-pro --only bix-12-q2 --results ~/bixbench/smoke
virtual-lab-bixbench run ~/bixbench --workspace ~/bixbench_workspace --token bench \
    --model openrouter/moonshotai/kimi-k3.1-pro --max-total-cost 150 --results ~/bixbench/kimi
virtual-lab-bixbench report ~/bixbench --results ~/bixbench/kimi
```

- Each question's data is unpacked into its conversation's `uploads/`, from the dataset's `CapsuleData-*` folder. The `CapsuleNotebook-*` folder, which holds the analysis the answer was taken from, and any `.ipynb` file, are never given to the lead. The message names the files, says nobody is there to answer questions, and asks for a last line of the form `FINAL ANSWER: ...`. The question's ideal answer and the dataset's hypothesis are not in it.
- The lead has what a conversation has: the model, the sandbox (`--sandbox`, `bio-r` by default, which has R and must be built first: `build_sandbox_image("bio-r")`, a few minutes after `bio`), the data lake and tools of `--resources`, and `--team` if a team is named. It is not given the tools that search papers (the studies the questions come from are papers), nor the tools that search the web and read its pages, nor any MCP server, data, software, or functions of the server's workspace, unless `--literature` is given for the first and `--web` for the second. Give the server a workspace of its own; `--workspace` is required for that reason. The code runs in Docker with network access, and none of your keys passed in. Each conversation may spend `--max-cost` (3 dollars by default), may make `--max-tool-calls` tool calls and runs of code (80, where a conversation's own limit is 20), and may take `--timeout` seconds (2,400) before it is stopped and what it has said is graded.
- The data lake is the server's own, which is `data_lake/` in its workspace unless its settings say where, and a workspace made for a run has none. `--data-lake DIRECTORY` gives every conversation a directory you already have instead, which the server mounts read-only, so it is a path on the machine the server is on. A run says so on stderr, and goes on, when the lead would have no data lake to read: the directory has nothing in it (hidden files do not count), or none was given and the server's has none of its files (one that has some is not warned of). A directory that is not one, or cannot be read, stops the run. The directory is part of what a run is set up with, so carrying on a run needs the same `--data-lake`.
- The lead is asked to check its result before it answers a question it ran code for (the conversation's `check_results`, see [Talking to the head of a lab](chat-and-server.md#talking-to-the-head-of-a-lab)), so `--no-result-check` turns that off, which is what to pass to measure a lead as it was before the check existed. A run always says which, so that results with and without the check are not counted together.
- `--skills` says which skills every conversation is given, which is none unless named: any of `builtin` (the skills that come with the lab), and folders of skills on the machine, such as a clone of a skill library. The server puts a folder's skills in its workspace as copies, leaving any whose name it already has, so give the run a workspace of its own, and the run stops before it asks anything if the server does not end up with a skill it was asked to give (a server of older code does not have the built-in ones). The names are sent as the conversation's own list, so what the server has turned on does not matter, and they are part of what a run is set up with: results with other skills are refused, and a run without `--skills` carries on one made before there were skills.
- `--multiple-choice` asks each question with options to choose from, as BixBench's own multiple-choice form does and as others who report scores on this set have: the ideal answer among the three distractors the dataset has for it, in an order that is fixed for each question, and an option, always the last, that says there is not enough information (`--no-refusal-option` leaves it out). The lead answers with a letter, and the answer is right if it is the ideal's. Choosing the last option is never right, and is counted in the summary. This is an easier test than an open answer, since a wrong option can be ruled out and a number the analysis came to can be looked for among the options, so the summary calls it multiple choice and its score is never to be counted with an open answer's. A record keeps its options and the right letter, so grading again needs no judge, and a directory that holds a run of the other kind is refused.
- By default each question is asked plainly, and it is up to the lead whether to call on the scientists `--team` names. `--lab team` gives every question as a researcher would with `/lab`, so the lead has those scientists work on it in a team session it leads, and `--lab individual` has the one scientist `--team` names work on it with the Scientific Critic reviewing (the Critic is put on each conversation's team, and is not counted among the scientists `--team` names); `--lab-rounds` (1 by default, up to 10, and a conversation is allowed more than its usual 3 when it is asked for more) is the rounds of discussion or review. Naming no scientists, or other than one besides the Critic for `individual`, or rounds outside 0 to 10, stops the run before anything is asked. Nothing else of the message changes, and `--lab` is part of what a run is set up with, so its results are not counted with those of a run without it.
- `--max-total-cost` stops the run from starting more questions once the lead has spent that much. What the questions under way may still spend, up to `--max-cost` each, counts as spent. Three questions in a row that fail stop it too, since that is more likely a bad key than three hard questions. A question that could not be set up, because the server refused or the data was missing, was never asked and is not recorded, so running the command again asks it. A run saves each question under `--results` as soon as it is graded, so running the same command again carries on, `--retry-failed` asks again those that were asked and failed, and a directory that holds a run set up differently (another model, team, sandbox, or judge) is refused, which the limits are not part of, so raising `--max-cost`, `--max-tool-calls`, or `--timeout` to ask again those that ran out is allowed. `--jobs` asks several at once, and each of them has a sandbox that may use as much memory as sandboxes are allowed.
- Every answer is graded two ways, and both scores are always reported together. **Official** is FutureHouse's grader (`bixbench/graders.py`) with its judge prompts word for word: a `str_verifier` answer is the ideal once everything but letters and digits is dropped and case is ignored, and otherwise a model judges it; a `range_verifier` answer is a number in the ideal's range, and otherwise a model judges it; an `llm_verifier` answer is judged. One deliberate difference: FutureHouse's accepts an answer that is only a piece of the ideal, so "CDK" passes for "CDKN1A", and here that is left to the judge. **Lenient** accepts in addition what rounding or an R-versus-Python difference in the last digits fails: the first number in the answer when it is within half a unit of the ideal's last digit or 1% of it, or is a decimal fraction written as a percentage, any number in the answer that is in the range (numbers that are part of a name, such as the 5 of chr5, are not counted), and a judge that allows 3%. Names and ratios get no leeway. Others who report scores on this set have loosened the grading in similar ways, so say which you mean when you quote one.
- The judge is `--judge-model`, by default the lead's model, and what it costs is not counted in the lead's. `virtual-lab-bixbench regrade ~/bixbench --results ... --judge-model ...` grades the saved answers again without asking anything.
- Each record in `questions/<id>.json` holds the lead's whole last message, the answer taken from it, both grades and how they were reached, the time, the cost, the tools called, and the conversation's id, so the conversation can be opened in the interface and read. `summary.json` holds the scores, overall and by kind of question.

The questions, their data, and their answers are the dataset's, under its own license, and are not shipped with this package. The dataset's canary string asks that it be kept out of training data.
