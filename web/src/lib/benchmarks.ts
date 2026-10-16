import { characters, count, dollars, whole, type Checked } from "./checks";
import { formatCost } from "./format";
import { tidy } from "./scientists";
import { SANDBOXES } from "./settings";
import { isActive } from "./setup";
import type {
  BenchmarkId,
  BenchmarkOptions,
  BenchmarkQuestion,
  BenchmarkQuestionRow,
  BenchmarkRunEntry,
  BenchmarksList,
  BenchmarkSolver,
  BenchmarkStartOptions,
  BenchmarkSubset,
  Job,
  NewBenchmarkRun,
} from "./types";

// What the server takes of a run's title
export const MAX_RUN_TITLE = 200;

// The kind of the job that answers a run's questions, of which one is at work at a time
export const JOB_KIND = "benchmark";

// How many questions are shown of a run's, before more are asked for
export const ROWS_SHOWN = 100;

export const SOLVER_LABELS: Record<BenchmarkSolver, string> = {
  single: "The lead alone",
  team: "The lead and the team",
};

export const SUBSET_LABELS: Record<BenchmarkSubset, string> = {
  test: "The test questions",
  sampled: "The sample",
  all: "All of them",
};

// Which of the options a benchmark takes are asked of a run of it
export const TAKES_TASKS: readonly BenchmarkId[] = ["biomni_eval1"];
export const TAKES_SUBSET: readonly BenchmarkId[] = ["lab_bench_dbqa", "lab_bench_seqqa"];
export const TAKES_IMAGES: readonly BenchmarkId[] = ["hle"];

export function solverLabel(solver: BenchmarkSolver): string {
  return SOLVER_LABELS[solver] ?? solver;
}

// What the rounds of a run are: criticism of the lead's answer when the lead is alone, or discussion in the team
export function roundsText(solver: BenchmarkSolver, rounds: number): string {
  if (solver === "team") return rounds === 1 ? "1 round of discussion" : `${rounds} rounds of discussion`;
  if (rounds === 0) return "no criticism";

  return rounds === 1 ? "1 round of criticism" : `${rounds} rounds of criticism`;
}

// A share, which is said as a percentage, or as a dash where there is nothing to take a share of
export function percent(share: number | null | undefined): string {
  if (share === null || share === undefined || !Number.isFinite(share)) return "–";

  return `${(share * 100).toFixed(1)}%`;
}

const METRIC_LABELS: Record<string, string> = {
  accuracy: "Accuracy",
  coverage: "Answered, not refused",
  refrain_ratio: "Refused",
  precision: "Right of those answered",
};

// The measures of a run that are not of one of Biomni-Eval1's tasks, which a table of the tasks shows
export function overallMetrics(
  metrics: Record<string, number | null>,
): { name: string; label: string; value: number | null }[] {
  return Object.entries(metrics)
    .filter(([name]) => !name.includes("/"))
    .map(([name, value]) => ({ name, label: METRIC_LABELS[name] ?? name, value }));
}

// How far a run has got, as a line: what was answered, how right it was, and what it spent
export function runFacts(run: BenchmarkRunEntry): string {
  const parts = [
    run.finished === 0
      ? `${count(run.questions, "question")}, none answered yet`
      : `Answered ${run.finished} of ${count(run.questions, "question")}`,
  ];
  if (run.finished > 0 && run.accuracy !== null) parts.push(`${percent(run.accuracy)} right`);
  if (run.failed) parts.push(`${run.failed} failed`);
  const spent = run.cost ?? run.spent;
  if (spent !== null && run.finished > 0) parts.push(`spent ${formatCost(spent)}`);

  return parts.join(" · ");
}

// Who answers a run, and how, in words
export function describeSolver(run: Pick<BenchmarkRunEntry, "solver" | "rounds" | "model">): string {
  const model = run.model ? ` with ${run.model}` : "";

  return `${solverLabel(run.solver)}${model}, ${roundsText(run.solver, run.rounds)}`;
}

// Where the code that answers questions runs, in words, as it was kept with the run
export function describeCode(code: { where: string | null; sandbox: string | null }): string {
  if (code.where === "docker") {
    const image = SANDBOXES.find((stage) => stage.value === code.sandbox)?.label ?? code.sandbox;

    return image ? `code runs in a Docker container, in the ${image} image` : "code runs in a Docker container";
  }
  if (code.where === "local") return "code runs on this computer";

  return "no code is run";
}

// What a run was narrowed to, in words, or nothing where it asks all of its benchmark
export function describeNarrowing(benchmark: BenchmarkId, options: BenchmarkOptions, limit: number | null): string[] {
  const parts: string[] = [];
  if (benchmark === "biomni_eval1" && options.tasks) {
    parts.push(`Only ${count(options.tasks.length, "task")}: ${options.tasks.join(", ")}`);
  }
  if (TAKES_SUBSET.includes(benchmark) && options.subset) parts.push(SUBSET_LABELS[options.subset] ?? options.subset);
  if (benchmark === "hle" && options.leave_out_images) parts.push("Without the questions that refer to an image");
  if (limit !== null) parts.push(`The first ${count(limit, "question")}`);

  return parts;
}

// The job at work on a run, which is answering its questions
export function benchmarkJob(jobs: readonly Job[], run: string): Job | undefined {
  return jobs.find((job) => isActive(job) && job.kind === JOB_KIND && job.subject === run);
}

// The latest job on a run that is over, whose outcome is how the run was last answered
export function lastBenchmarkJob(jobs: readonly Job[], run: string): Job | undefined {
  return jobs.find((job) => !isActive(job) && job.kind === JOB_KIND && job.subject === run);
}

// What changes as questions are answered, so that what a page shows of runs is looked at again when it does: which jobs
// are at work, and how far each has got, and how many have ended
export function benchmarkKey(jobs: readonly Job[] | null, ended: number, run?: string): string {
  const at = (jobs ?? [])
    .filter((job) => isActive(job) && job.kind === JOB_KIND && (run === undefined || job.subject === run))
    .map((job) => `${job.id}:${job.progress.finished ?? ""}`);

  return `${ended}|${at.join(",")}`;
}

export type Outcome = "right" | "partly" | "wrong" | "failed" | "unanswered";

export const OUTCOME_LABELS: Record<Outcome, string> = {
  right: "Right",
  partly: "Partly right",
  wrong: "Wrong",
  failed: "Failed",
  unanswered: "Not answered",
};

export const OUTCOMES = Object.keys(OUTCOME_LABELS) as Outcome[];

// How a question was answered: a score of 1 is right and one of 0 is wrong, and between them it was partly right
export function outcomeOf(row: Pick<BenchmarkQuestionRow, "state" | "score">): Outcome {
  if (row.state === "unanswered") return "unanswered";
  if (row.state === "failed") return "failed";
  if (row.score === null) return "wrong";
  if (row.score >= 1) return "right";

  return row.score > 0 ? "partly" : "wrong";
}

// The questions of a task, if one is chosen, that were answered as asked, if that is
export function filterRows(
  rows: readonly BenchmarkQuestionRow[],
  task: string,
  outcome: Outcome | "all",
): BenchmarkQuestionRow[] {
  return rows.filter((row) => (task === "" || row.task === task) && (outcome === "all" || outcomeOf(row) === outcome));
}

// The tokens a question used, and what they cost, as a line
export function usageText(usage: BenchmarkQuestion["usage"]): string {
  if (usage === null) return "";
  const parts: string[] = [];
  if (typeof usage.input_tokens === "number" && typeof usage.output_tokens === "number") {
    const [tokensIn, tokensOut] = [usage.input_tokens, usage.output_tokens].map((tokens) => tokens.toLocaleString("en-US"));
    parts.push(`${tokensIn} tokens in, ${tokensOut} out`);
  }
  if (typeof usage.num_calls === "number") parts.push(count(usage.num_calls, "call"));
  if (typeof usage.cost === "number") parts.push(formatCost(usage.cost) || "no cost");

  return parts.join(" · ");
}

export interface RunDraft {
  title: string;
  benchmark: BenchmarkId;
  solver: BenchmarkSolver;
  rounds: string;
  limit: string;
  // The tasks of Biomni-Eval1 that are left out, which is none of them to ask all, as a run does by default
  left: string[];
  subset: BenchmarkSubset;
  leaveOutImages: boolean;
}

export const EMPTY_RUN: RunDraft = {
  title: "",
  benchmark: "biomni_eval1",
  solver: "single",
  rounds: "",
  limit: "",
  left: [],
  subset: "test",
  leaveOutImages: false,
};

type RunKey = "title" | "rounds" | "limit" | "tasks";

export function checkRun(
  draft: RunDraft,
  list: Pick<BenchmarksList, "benchmarks" | "max_rounds" | "max_questions">,
): Checked<NewBenchmarkRun, RunKey> {
  const title = tidy(draft.title);
  const problems: Partial<Record<RunKey, string>> = {};
  if (title === "") problems.title = "Give the run a title.";
  else if (characters(title) > MAX_RUN_TITLE) {
    problems.title = `The title can be at most ${MAX_RUN_TITLE} characters, and this is ${characters(title)}.`;
  }
  const rounds = draft.rounds.trim() === "" ? { value: null } : whole(draft.rounds, "The number of rounds", 0, list.max_rounds);
  if (rounds.problem) problems.rounds = rounds.problem;
  const limit =
    draft.limit.trim() === "" ? { value: null } : whole(draft.limit, "The number of questions", 1, list.max_questions);
  if (limit.problem) problems.limit = limit.problem;

  const body: NewBenchmarkRun = { title, benchmark: draft.benchmark, solver: draft.solver };
  if (rounds.value !== null) body.rounds = rounds.value;
  if (limit.value !== null) body.limit = limit.value;
  if (TAKES_TASKS.includes(draft.benchmark)) {
    const known = list.benchmarks.find((benchmark) => benchmark.id === draft.benchmark)?.tasks ?? [];
    const chosen = known.map((task) => task.name).filter((name) => !draft.left.includes(name));
    if (chosen.length === 0) problems.tasks = "Choose at least one task.";
    // All of them is what a run asks when it is not told which, so it is not told
    else if (chosen.length < known.length) body.tasks = chosen;
  } else if (TAKES_SUBSET.includes(draft.benchmark)) {
    body.subset = draft.subset;
  } else if (TAKES_IMAGES.includes(draft.benchmark)) {
    body.leave_out_images = draft.leaveOutImages;
  }

  return { value: Object.keys(problems).length === 0 ? body : null, problems };
}

export interface StartDraft {
  budget: string;
  perQuestion: string;
  retryFailed: boolean;
}

export const EMPTY_START: StartDraft = { budget: "1", perQuestion: "", retryFailed: false };

export function checkStart(draft: StartDraft): Checked<BenchmarkStartOptions, "budget" | "perQuestion"> {
  const budget = dollars(draft.budget, "the most it may spend", false);
  const perQuestion = dollars(draft.perQuestion, "the most one question may spend", true);
  const problems: Partial<Record<"budget" | "perQuestion", string>> = {};
  if (budget.problem) problems.budget = budget.problem;
  if (perQuestion.problem) problems.perQuestion = perQuestion.problem;
  if (Object.keys(problems).length > 0 || budget.value === null) return { value: null, problems };

  return {
    value: { max_cost: budget.value, max_cost_per_question: perQuestion.value, retry_failed: draft.retryFailed },
    problems,
  };
}
