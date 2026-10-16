import { describe, expect, it } from "vitest";
import {
  benchmarkJob,
  benchmarkKey,
  checkRun,
  checkStart,
  describeCode,
  describeNarrowing,
  describeSolver,
  EMPTY_RUN,
  EMPTY_START,
  filterRows,
  lastBenchmarkJob,
  outcomeOf,
  overallMetrics,
  percent,
  roundsText,
  runFacts,
  usageText,
} from "./benchmarks";
import type { BenchmarkInfo, BenchmarkQuestionRow, BenchmarkRunEntry, Job } from "./types";

function job(changes: Partial<Job> = {}): Job {
  return {
    id: "j1",
    kind: "benchmark",
    subject: "run-a",
    title: "Answering Run A",
    state: "running",
    message: "",
    progress: {},
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    finished_at: null,
    log_total: 0,
    ...changes,
  };
}

function run(changes: Partial<BenchmarkRunEntry> = {}): BenchmarkRunEntry {
  return {
    id: "run-a",
    title: "Run A",
    benchmark: "lab_bench_dbqa",
    solver: "single",
    rounds: 0,
    model: "gpt-5.2",
    created_at: "2026-01-01T00:00:00Z",
    questions: 5,
    finished: 0,
    failed: null,
    accuracy: null,
    cost: null,
    spent: null,
    stopped: null,
    job: null,
    ...changes,
  };
}

function row(changes: Partial<BenchmarkQuestionRow> = {}): BenchmarkQuestionRow {
  return {
    key: "t/0",
    task: "t",
    id: 0,
    prompt: "What?",
    state: "answered",
    answer: "A",
    correct_answer: "A",
    score: 1,
    cost: 0.01,
    elapsed: 1,
    error: null,
    ...changes,
  };
}

const benchmarks: BenchmarkInfo[] = [
  {
    id: "biomni_eval1",
    title: "Biomni-Eval1",
    summary: "",
    tasks: [
      { name: "crispr_delivery", questions: 2 },
      { name: "rare_disease_diagnosis", questions: 1 },
    ],
    subsets: null,
    images: null,
    questions: 3,
  },
];
const list = { benchmarks, max_rounds: 5, max_questions: 1000 };

describe("how far a run has got", () => {
  it("says that nothing is answered before anything is", () => {
    expect(runFacts(run())).toBe("5 questions, none answered yet");
  });

  it("says what was answered, how right it was, what failed, and what it spent", () => {
    expect(runFacts(run({ finished: 3, accuracy: 0.6, failed: 1, cost: 0.123 }))).toBe(
      "Answered 3 of 5 questions · 60.0% right · 1 failed · spent $0.12",
    );
  });

  it("leaves out what is not known", () => {
    expect(runFacts(run({ finished: 1, questions: 1 }))).toBe("Answered 1 of 1 question");
    expect(runFacts(run({ finished: 1, spent: 2 }))).toBe("Answered 1 of 5 questions · spent $2.00");
  });
});

describe("who answers, and what was asked", () => {
  it("says who answers and how many rounds", () => {
    expect(describeSolver(run())).toBe("The lead alone with gpt-5.2, no criticism");
    expect(describeSolver(run({ solver: "team", rounds: 2, model: null }))).toBe("The lead and the team, 2 rounds of discussion");
    expect(roundsText("single", 1)).toBe("1 round of criticism");
    expect(roundsText("team", 1)).toBe("1 round of discussion");
  });

  it("says what a run was narrowed to, and nothing where it was not", () => {
    expect(describeNarrowing("biomni_eval1", {}, null)).toEqual([]);
    expect(describeNarrowing("biomni_eval1", { tasks: ["a", "b"] }, 10)).toEqual(["Only 2 tasks: a, b", "The first 10 questions"]);
    expect(describeNarrowing("lab_bench_dbqa", { subset: "sampled" }, null)).toEqual(["The sample"]);
    expect(describeNarrowing("hle", { leave_out_images: true }, 1)).toEqual([
      "Without the questions that refer to an image",
      "The first 1 question",
    ]);
  });

  it("says where code runs", () => {
    expect(describeCode({ where: "none", sandbox: null })).toBe("no code is run");
    expect(describeCode({ where: null, sandbox: null })).toBe("no code is run");
    expect(describeCode({ where: "local", sandbox: null })).toBe("code runs on this computer");
    expect(describeCode({ where: "docker", sandbox: "python" })).toBe("code runs in a Docker container, in the Plain Python image");
    expect(describeCode({ where: "docker", sandbox: null })).toBe("code runs in a Docker container");
  });
});

describe("scores", () => {
  it("are shares, said as percentages, or a dash where there is none", () => {
    expect(percent(0.5)).toBe("50.0%");
    expect(percent(1 / 3)).toBe("33.3%");
    expect(percent(null)).toBe("–");
    expect(percent(Number.NaN)).toBe("–");
  });

  it("leave out the measures of one task, which a table of the tasks shows", () => {
    expect(overallMetrics({ accuracy: 0.5, "accuracy/crispr_delivery": 1, coverage: 0.8, extra: null })).toEqual([
      { name: "accuracy", label: "Accuracy", value: 0.5 },
      { name: "coverage", label: "Answered, not refused", value: 0.8 },
      { name: "extra", label: "extra", value: null },
    ]);
  });
});

describe("how a question was answered", () => {
  it("is right at 1, wrong at 0, and partly right between, whatever is not answered or failed", () => {
    expect(outcomeOf(row())).toBe("right");
    expect(outcomeOf(row({ score: 0 }))).toBe("wrong");
    expect(outcomeOf(row({ score: 0.5 }))).toBe("partly");
    expect(outcomeOf(row({ score: null }))).toBe("wrong");
    expect(outcomeOf(row({ state: "failed", score: 0 }))).toBe("failed");
    expect(outcomeOf(row({ state: "unanswered", score: null }))).toBe("unanswered");
  });

  it("can be told apart by task and by how it was answered", () => {
    const rows = [row(), row({ key: "u/0", task: "u", score: 0 }), row({ key: "u/1", task: "u", id: 1, state: "unanswered", score: null })];

    expect(filterRows(rows, "", "all")).toHaveLength(3);
    expect(filterRows(rows, "u", "all").map((one) => one.key)).toEqual(["u/0", "u/1"]);
    expect(filterRows(rows, "", "wrong").map((one) => one.key)).toEqual(["u/0"]);
    expect(filterRows(rows, "t", "wrong")).toEqual([]);
  });

  it("says what it used", () => {
    expect(usageText(null)).toBe("");
    expect(usageText({ input_tokens: 1200, output_tokens: 30, num_calls: 2, cost: 0.5 })).toBe("1,200 tokens in, 30 out · 2 calls · $0.50");
    expect(usageText({ num_calls: 1, cost: null })).toBe("1 call");
  });
});

describe("the work at hand on a run", () => {
  it("is the job at work on it, of the kind that answers", () => {
    const jobs = [job({ id: "j2", subject: "run-b" }), job({ id: "j3", kind: "papers" }), job({ id: "j4" })];

    expect(benchmarkJob(jobs, "run-a")?.id).toBe("j4");
    expect(benchmarkJob(jobs, "run-c")).toBeUndefined();
  });

  it("is, once there is none, the latest that is over", () => {
    const jobs = [job({ id: "j2", state: "stopped" }), job({ id: "j1", state: "succeeded" })];

    expect(benchmarkJob(jobs, "run-a")).toBeUndefined();
    expect(lastBenchmarkJob(jobs, "run-a")?.id).toBe("j2");
  });

  it("has a key that changes as a job gets on, and as one ends, and for one run only with that run's", () => {
    const at = (finished: number) => [job({ progress: { finished } }), job({ id: "j9", subject: "run-b", progress: { finished: 7 } })];

    expect(benchmarkKey(at(1), 0)).not.toBe(benchmarkKey(at(2), 0));
    expect(benchmarkKey(at(1), 0)).not.toBe(benchmarkKey(at(1), 1));
    expect(benchmarkKey(at(1), 0, "run-a")).toBe(benchmarkKey([...at(1), job({ id: "j8", subject: "run-c", progress: { finished: 4 } })], 0, "run-a"));
    expect(benchmarkKey(null, 0)).toBe("0|");
  });
});

describe("a run that is asked for", () => {
  const draft = { ...EMPTY_RUN, title: "  Gene   run " };

  it("needs a title, which is tidied", () => {
    expect(checkRun({ ...draft, title: "  " }, list).problems.title).toBe("Give the run a title.");
    expect(checkRun({ ...draft, title: "x".repeat(201) }, list).problems.title).toContain("at most 200");
    expect(checkRun(draft, list).value).toEqual({ title: "Gene run", benchmark: "biomni_eval1", solver: "single" });
  });

  it("holds the rounds and the number of questions to what the server takes, and leaves them out when blank", () => {
    expect(checkRun({ ...draft, rounds: "6" }, list).problems.rounds).toContain("0 to 5");
    expect(checkRun({ ...draft, rounds: "-1" }, list).problems.rounds).toBeDefined();
    expect(checkRun({ ...draft, limit: "0" }, list).problems.limit).toContain("1 to 1000");
    expect(checkRun({ ...draft, limit: "1.5" }, list).value).toBeNull();
    expect(checkRun({ ...draft, rounds: "0", limit: "7", solver: "team" }, list).value).toEqual({
      title: "Gene run",
      benchmark: "biomni_eval1",
      solver: "team",
      rounds: 0,
      limit: 7,
    });
  });

  it("names the tasks of Biomni-Eval1 only when some are left out, and needs one", () => {
    expect(checkRun({ ...draft, left: ["crispr_delivery"] }, list).value?.tasks).toEqual(["rare_disease_diagnosis"]);
    expect(checkRun({ ...draft, left: ["crispr_delivery", "rare_disease_diagnosis"] }, list).problems.tasks).toBe("Choose at least one task.");
    expect(checkRun({ ...draft, left: ["not_a_task"] }, list).value).not.toHaveProperty("tasks");
  });

  it("asks of a benchmark only what is for it", () => {
    const lab = checkRun({ ...draft, benchmark: "lab_bench_seqqa", subset: "all", left: ["crispr_delivery"], leaveOutImages: true }, list).value;
    const exam = checkRun({ ...draft, benchmark: "hle", subset: "all", left: ["crispr_delivery"], leaveOutImages: true }, list).value;

    expect(lab).toEqual({ title: "Gene run", benchmark: "lab_bench_seqqa", solver: "single", subset: "all" });
    expect(exam).toEqual({ title: "Gene run", benchmark: "hle", solver: "single", leave_out_images: true });
  });
});

describe("what answering may spend", () => {
  it("is asked for, and is dollars as they are typed", () => {
    expect(checkStart(EMPTY_START).value).toEqual({ max_cost: 1, max_cost_per_question: null, retry_failed: false });
    expect(checkStart({ ...EMPTY_START, budget: "$2.50", retryFailed: true }).value).toEqual({
      max_cost: 2.5,
      max_cost_per_question: null,
      retry_failed: true,
    });
    expect(checkStart({ ...EMPTY_START, budget: "" }).problems.budget).toBe("Say the most it may spend.");
    expect(checkStart({ ...EMPTY_START, budget: "lots" }).value).toBeNull();
  });

  it("may leave out what one question may spend, but not mistype it", () => {
    expect(checkStart({ ...EMPTY_START, perQuestion: "0.05" }).value?.max_cost_per_question).toBe(0.05);
    expect(checkStart({ ...EMPTY_START, perQuestion: "-1" }).problems.perQuestion).toBeDefined();
  });
});
