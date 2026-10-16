import { characters, count, dollars, whole, type Checked } from "./checks";
import { formatBytes } from "./files";
import { formatCost } from "./format";
import { tidy } from "./scientists";
import { isActive } from "./setup";
import type {
  FindingKind,
  FunctionStatus,
  Job,
  NewPaperRun,
  PaperFunctionsOptions,
  PaperReadOptions,
  PaperRunEntry,
  PaperSource,
  PaperSourceKind,
  PaperStatus,
} from "./types";

// What the server takes of a run's title, of the preprints asked of bioRxiv for one, and of the functions written
export const MAX_RUN_TITLE = 200;
export const MAX_BIORXIV_LIMIT = 500;
export const MAX_FUNCTIONS = 100;
export const MAX_MIN_PAPERS = 100_000;
export const DEFAULT_FUNCTIONS = 10;

// The jobs that work on a run, only one of which is at work on it at a time
export const WORK_KINDS = ["papers", "functions"];

export const SOURCE_LABELS: Record<PaperSourceKind, string> = {
  files: "Papers I upload",
  folder: "A folder on this machine",
  biorxiv: "bioRxiv",
};

export const SOURCE_KINDS = Object.keys(SOURCE_LABELS) as PaperSourceKind[];

export const FINDING_LABELS: Record<FindingKind, string> = {
  tasks: "Tasks",
  databases: "Databases",
  software: "Software",
};

const STATUS_LABELS: Record<PaperStatus, string> = {
  pending: "Not read",
  read: "Read",
  unavailable: "Unavailable",
  failed: "Failed",
};

export function statusLabel(status: PaperStatus): string {
  return STATUS_LABELS[status] ?? status;
}

const FUNCTION_LABELS: Record<FunctionStatus, string> = {
  verified: "Checked",
  unverified: "Not run",
  failed: "Failed",
};

// What a function was found to be, said as the page says it: one that passed was also imported in a container
export function functionLabel(status: FunctionStatus): string {
  return FUNCTION_LABELS[status] ?? status;
}

// Where a run's papers come from, in words
export function describeSource(source: PaperSource): string {
  if (source.kind === "files") return "Papers uploaded to it";
  if (source.kind === "folder") return `Papers in ${source.path}${source.recursive ? " and the folders in it" : ""}`;
  const period = source.until ? `from ${source.since} to ${source.until}` : `from ${source.since} on`;
  const subject = source.subject === "all" ? "of every subject" : `of ${source.subject}`;
  const chosen = source.random ? `${count(source.limit, "preprint")} chosen at random` : `up to ${count(source.limit, "preprint")}`;

  return `bioRxiv preprints ${subject}, ${period}, ${chosen}`;
}

// How far the reading of a run has got, as a line, with what has been made of what was read
export function runFacts(run: PaperRunEntry): string {
  const parts: string[] = [];
  if (run.read !== null && run.papers !== null) {
    parts.push(`Read ${run.read} of ${count(run.papers, "paper")}`);
    if (run.unavailable) parts.push(`${run.unavailable} unavailable`);
    if (run.failed) parts.push(`${run.failed} failed`);
    if (run.spent !== null) parts.push(`spent ${formatCost(run.spent)}`);
  } else if (run.finished > 0) {
    parts.push(`${count(run.finished, "paper")} dealt with so far`);
  } else if (run.files !== null) {
    parts.push(`${count(run.files, "paper")} uploaded, not read yet`);
  } else {
    parts.push("Not read yet");
  }
  if (run.function_count > 0) parts.push(count(run.function_count, "function"));

  return parts.join(" · ");
}

// The job at work on a run, which is reading its papers or writing its functions
export function workJob(jobs: readonly Job[], run: string): Job | undefined {
  return jobs.find((job) => isActive(job) && WORK_KINDS.includes(job.kind) && job.subject === run);
}

// The latest job on a run that is over, whose outcome is what the run was last done with
export function lastJob(jobs: readonly Job[], run: string): Job | undefined {
  return jobs.find((job) => !isActive(job) && WORK_KINDS.includes(job.kind) && job.subject === run);
}

// What changes as papers are read and functions are written, so that what a page shows of runs is looked at again
// when it does: which jobs are at work, and how far each has got, and how many have ended
export function workKey(jobs: readonly Job[] | null, ended: number, run?: string): string {
  const at = (jobs ?? [])
    .filter((job) => isActive(job) && WORK_KINDS.includes(job.kind) && (run === undefined || job.subject === run))
    .map((job) => `${job.id}:${job.progress.finished ?? ""}`);

  return `${ended}|${at.join(",")}`;
}

export interface ReadDraft {
  budget: string;
  perPaper: string;
  retryFailed: boolean;
}

export const EMPTY_READ: ReadDraft = { budget: "1", perPaper: "", retryFailed: false };

export function checkRead(draft: ReadDraft): Checked<PaperReadOptions, "budget" | "perPaper"> {
  const budget = dollars(draft.budget, "the most it may spend", false);
  const perPaper = dollars(draft.perPaper, "the most one paper may spend", true);
  const problems: Partial<Record<"budget" | "perPaper", string>> = {};
  if (budget.problem) problems.budget = budget.problem;
  if (perPaper.problem) problems.perPaper = perPaper.problem;
  if (Object.keys(problems).length > 0 || budget.value === null) return { value: null, problems };

  return {
    value: { max_cost: budget.value, max_cost_per_paper: perPaper.value, retry_failed: draft.retryFailed },
    problems,
  };
}

export interface FunctionsDraft {
  budget: string;
  perFunction: string;
  minPapers: string;
  limit: string;
  retryFailed: boolean;
  verify: boolean;
}

export const EMPTY_FUNCTIONS: FunctionsDraft = {
  budget: "1",
  perFunction: "",
  minPapers: "1",
  limit: String(DEFAULT_FUNCTIONS),
  retryFailed: false,
  verify: false,
};

type FunctionsKey = "budget" | "perFunction" | "minPapers" | "limit";

export function checkFunctions(draft: FunctionsDraft): Checked<PaperFunctionsOptions, FunctionsKey> {
  const budget = dollars(draft.budget, "the most it may spend", false);
  const perFunction = dollars(draft.perFunction, "the most one function may spend", true);
  const minPapers = whole(draft.minPapers, "The fewest papers a task is found in", 1, MAX_MIN_PAPERS);
  const limit = whole(draft.limit, "The number of functions", 1, MAX_FUNCTIONS);
  const problems: Partial<Record<FunctionsKey, string>> = {};
  if (budget.problem) problems.budget = budget.problem;
  if (perFunction.problem) problems.perFunction = perFunction.problem;
  if (minPapers.problem) problems.minPapers = minPapers.problem;
  if (limit.problem) problems.limit = limit.problem;
  if (Object.keys(problems).length > 0 || budget.value === null || minPapers.value === null || limit.value === null) {
    return { value: null, problems };
  }

  return {
    value: {
      max_cost: budget.value,
      max_cost_per_function: perFunction.value,
      min_papers: minPapers.value,
      limit: limit.value,
      retry_failed: draft.retryFailed,
      verify: draft.verify,
    },
    problems,
  };
}

export interface RunDraft {
  title: string;
  kind: PaperSourceKind;
  path: string;
  recursive: boolean;
  since: string;
  until: string;
  subject: string;
  limit: string;
  random: boolean;
  includeUnpublished: boolean;
}

export const EMPTY_RUN: RunDraft = {
  title: "",
  kind: "files",
  path: "",
  recursive: false,
  since: "",
  until: "",
  subject: "all",
  limit: "10",
  random: false,
  includeUnpublished: false,
};

type RunKey = "title" | "path" | "since" | "until" | "limit";

// Whether text is a day as YYYY-MM-DD, which the browser's date field gives and the server asks for
function isDay(text: string): boolean {
  const found = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (!found) return false;
  const [year, month, day] = [Number(found[1]), Number(found[2]), Number(found[3])];
  const date = new Date(Date.UTC(year, month - 1, day));

  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

export function checkRun(draft: RunDraft): Checked<NewPaperRun, RunKey> {
  const title = tidy(draft.title);
  const problems: Partial<Record<RunKey, string>> = {};
  if (title === "") problems.title = "Give the run a title.";
  else if (characters(title) > MAX_RUN_TITLE) {
    problems.title = `The title can be at most ${MAX_RUN_TITLE} characters, and this is ${characters(title)}.`;
  }
  let source: PaperSource = { kind: "files" };
  if (draft.kind === "folder") {
    const path = draft.path.trim();
    if (path === "") problems.path = "Give the full path of the folder.";
    source = { kind: "folder", path, recursive: draft.recursive };
  } else if (draft.kind === "biorxiv") {
    const since = draft.since.trim();
    const until = draft.until.trim();
    if (!isDay(since)) problems.since = "Say the first day, as a date.";
    if (until !== "" && !isDay(until)) problems.until = "Say the last day, as a date, or leave it blank.";
    else if (until !== "" && isDay(since) && until < since) problems.until = "The last day is before the first.";
    const limit = whole(draft.limit, "The number of preprints", 1, MAX_BIORXIV_LIMIT);
    if (limit.problem) problems.limit = limit.problem;
    source = {
      kind: "biorxiv",
      since,
      until: until === "" ? null : until,
      subject: draft.subject,
      limit: limit.value ?? 0,
      random: draft.random,
      include_unpublished: draft.includeUnpublished,
    };
  }

  return { value: Object.keys(problems).length === 0 ? { title, source } : null, problems };
}

// Whether a name of a file uploaded to a run is one the run takes: it ends as a paper does
export function isPaperName(name: string, suffixes: readonly string[]): boolean {
  const dot = name.lastIndexOf(".");

  return dot >= 0 && suffixes.includes(name.slice(dot).toLowerCase());
}

// Why a file cannot be uploaded to a run, or null if it can. The server holds the same limits and says it too, but a
// file that is too big is not sent first.
export function uploadProblem(
  file: { name: string; size: number },
  taken: readonly string[],
  limits: { bytes: number; suffixes: readonly string[]; files: number },
): string | null {
  if (!isPaperName(file.name, limits.suffixes)) {
    return `${file.name} is not a paper this reads: give a file that ends in ${limits.suffixes.join(", ")}.`;
  }
  if (file.size > limits.bytes) return `${file.name} is larger than the ${formatBytes(limits.bytes)} that can be uploaded.`;
  if (taken.some((name) => name.toLowerCase() === file.name.toLowerCase())) {
    return `There is a paper named ${file.name} in this run already. Remove it first, or rename this one.`;
  }
  if (taken.length >= limits.files) return `No more than ${limits.files} papers can be uploaded to one run.`;

  return null;
}
