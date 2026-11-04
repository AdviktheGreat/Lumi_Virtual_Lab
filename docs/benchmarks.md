# Benchmarks

[Back to the README](../README.md). Measuring an agent or a team on Biomni's benchmarks.

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
