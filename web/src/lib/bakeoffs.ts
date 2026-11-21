import { characters, dollars, type Checked } from "./checks";
import { formatCost } from "./format";
import { checkScope, EMPTY_SCOPE_DRAFT, type ScopeDraft } from "./paperagent-scope";
import { tidy } from "./scientists";
import { isActive } from "./setup";
import type { Bakeoff, BakeoffChange, BakeoffLabels, BakeoffLabelsBody, BakeoffLimits, BakeoffSummary, Job, NewBakeoff, ScopeData } from "./types";

// What the server takes of a bake-off, which it says too, and which is only here for a page that has not been told
export const MAX_BAKEOFF_TASK = 2000;
export const MAX_BAKEOFF_TITLE = 120;
// How long the name of a column of right answers may be, as the server counts it
export const MAX_COLUMN_CHARS = 200;

// A bake-off is its own page, named in the address's query as an agent is, and the bake-offs are a part of the PaperAgents page
export const BAKEOFFS_ADDRESS = "/papers?view=bakeoffs";
export const bakeoffAddress = (id: string) => `/papers?bakeoff=${encodeURIComponent(id)}`;

// The jobs that find, build, or run the methods of a bake-off, of which one is at work on it at a time
export const BAKEOFF_JOBS = ["bakeoff-shortlist", "bakeoff-build", "bakeoff-run"];

// Of those, the ones that find and build the methods, which are shown where the methods are, and the one that runs them, which is shown
// where they are run
export const METHOD_JOBS = ["bakeoff-shortlist", "bakeoff-build"];
export const RUN_JOBS = ["bakeoff-run"];

// Which bake-off a job is at work on, if it is one that works on a bake-off, and, if kinds are given, of one of those kinds
export function bakeoffJob(jobs: readonly Job[] | null, id: string, kinds: readonly string[] = BAKEOFF_JOBS): Job | undefined {
  return (jobs ?? []).find((job) => isActive(job) && kinds.includes(job.kind) && job.subject === id);
}

// What changes as the methods of a bake-off are found, built, or run, so that what a page shows is looked at again when it does:
// which jobs are at work and how many things each has done, and how many jobs have ended
export function bakeoffKey(jobs: readonly Job[] | null, ended: number, id?: string): string {
  const at = (jobs ?? [])
    .filter((job) => isActive(job) && BAKEOFF_JOBS.includes(job.kind) && (id === undefined || job.subject === id))
    .map((job) => `${job.id}:${job.progress.finished ?? ""}`);

  return `${ended}|${at.join(",")}`;
}

// What a person typed of a bake-off: what it is for, which of their data it is run on, what that is, where the right answers are, and
// the most it may spend
export interface BakeoffDraft {
  title: string;
  task: string;
  data: string;
  limit: string;
  scope: ScopeDraft;
  // The file on the Data page that has the right answers, its column of them, and the column that says what each is the answer to
  answers: string;
  column: string;
  idColumn: string;
}

export const EMPTY_BAKEOFF: BakeoffDraft = {
  title: "",
  task: "",
  data: "",
  limit: "",
  scope: EMPTY_SCOPE_DRAFT,
  answers: "",
  column: "",
  idColumn: "",
};

export type BakeoffKey = "title" | "task" | "data" | "limit" | "answers" | "column" | "idColumn" | keyof ScopeDraft | "form";

const SCOPE_KEYS = Object.keys(EMPTY_SCOPE_DRAFT) as (keyof ScopeDraft)[];

// Whether nothing was typed of what the data is
export function isBlankScope(scope: ScopeDraft): boolean {
  return SCOPE_KEYS.every((key) => scope[key].trim() === "");
}

// What was typed of where the right answers are, or what is wrong with it. None of it typed is none said.
export function checkLabels(draft: BakeoffDraft): Checked<BakeoffLabelsBody | null, "answers" | "column" | "idColumn"> {
  const own = draft.answers.trim();
  const column = draft.column.trim();
  const id = draft.idColumn.trim();
  const problems: Partial<Record<"answers" | "column" | "idColumn", string>> = {};
  if (own === "" && column === "" && id === "") return { value: null, problems };
  if (own === "") problems.answers = "Say which file on the Data page has them, or leave the columns blank.";
  if (column === "") problems.column = "Say which column has the right answer for each row.";
  else if (characters(column) > MAX_COLUMN_CHARS) problems.column = `A column's name is at most ${MAX_COLUMN_CHARS} characters.`;
  if (id !== "" && characters(id) > MAX_COLUMN_CHARS) problems.idColumn = `A column's name is at most ${MAX_COLUMN_CHARS} characters.`;
  else if (id !== "" && id === column) problems.idColumn = "That is the column of the answers. It has to be another, or be left blank.";
  if (Object.keys(problems).length > 0) return { value: null, problems };

  return { value: { own, column, ...(id !== "" ? { id_column: id } : {}) }, problems };
}

interface Parts {
  title: string;
  task: string;
  limit: number;
  described: ScopeData | null;
  labels: BakeoffLabelsBody | null;
}

// What was typed, checked, part by part. A part that was left blank is nothing, and what is wrong is said where it is.
function checkParts(draft: BakeoffDraft, limits: Pick<BakeoffLimits, "max_task_chars" | "max_title_chars"> | null): Checked<Parts, BakeoffKey> {
  const problems: Partial<Record<BakeoffKey, string>> = {};
  const task = tidy(draft.task);
  const mostTask = limits?.max_task_chars ?? MAX_BAKEOFF_TASK;
  const mostTitle = limits?.max_title_chars ?? MAX_BAKEOFF_TITLE;
  if (task === "") problems.task = "Say what you want done.";
  else if (characters(task) > mostTask) problems.task = `That is at most ${mostTask} characters.`;
  const title = tidy(draft.title);
  if (characters(title) > mostTitle) problems.title = `That is at most ${mostTitle} characters.`;
  const spending = dollars(draft.limit, "the most it may spend", false);
  if (spending.problem) problems.limit = spending.problem;
  let described: ScopeData | null = null;
  if (!isBlankScope(draft.scope)) {
    const scope = checkScope(draft.scope);
    if (scope.value === null) Object.assign(problems, scope.problems);
    else described = scope.value;
  }
  const labels = checkLabels(draft);
  Object.assign(problems, labels.problems);
  if (Object.keys(problems).length > 0 || spending.value === null) return { value: null, problems };

  return { value: { title, task, limit: spending.value, described, labels: labels.value }, problems: {} };
}

// What is sent to make a bake-off of what was typed, or what is wrong with it. What was left blank is left out.
export function checkBakeoff(draft: BakeoffDraft, limits: BakeoffLimits | null): Checked<NewBakeoff, BakeoffKey> {
  const checked = checkParts(draft, limits);
  if (checked.value === null) return { value: null, problems: checked.problems };
  const { title, task, limit, described, labels } = checked.value;

  return {
    value: {
      task,
      limit,
      ...(title !== "" ? { title } : {}),
      ...(draft.data !== "" ? { data: draft.data } : {}),
      ...(described !== null ? { described } : {}),
      ...(labels !== null ? { labels } : {}),
    },
    problems: {},
  };
}

// An amount as a person types it: in digits, as a number that is very small or very large is not written with an exponent
function typed(amount: number): string {
  return amount.toLocaleString("en-US", { useGrouping: false, maximumFractionDigits: 20 });
}

// What a person is shown to change of a bake-off: what it is now
export function draftOf(bakeoff: Bakeoff): BakeoffDraft {
  const said = bakeoff.described;

  return {
    title: bakeoff.title,
    task: bakeoff.task,
    data: bakeoff.data?.own ?? "",
    limit: typed(bakeoff.limit),
    scope: {
      species: said?.species ?? "",
      tissue: said?.tissue ?? "",
      assay: said?.assay ?? "",
      format: said?.input_format ?? "",
      size: said !== null && said.sample_size > 0 ? String(said.sample_size) : "",
      unit: said?.sample_unit ?? "",
    },
    answers: bakeoff.labels?.own ?? "",
    column: bakeoff.labels?.column ?? "",
    idColumn: bakeoff.labels?.id_column ?? "",
  };
}

// The parts of what is said of the data that are words
const SCOPE_WORDS = ["species", "tissue", "assay", "input_format", "sample_unit"] as const;

// The same data said in the same words. A bake-off keeps every part, with what was not said as an empty text and a size of none, and
// when it was said, none of which is said again.
function sameData(one: ScopeData | null, other: ScopeData | null): boolean {
  const flat = (data: ScopeData | null) => JSON.stringify([...SCOPE_WORDS.map((key) => data?.[key] ?? ""), data?.sample_size ?? 0]);

  return flat(one) === flat(other);
}

// What to say again of a bake-off, of what was typed, or what is wrong with it. Only what differs from what the bake-off is now is
// said, so that a file of right answers that is gone does not stand in the way of changing the title. Nothing that differs is an empty
// change.
export function checkChange(draft: BakeoffDraft, was: Bakeoff): Checked<BakeoffChange, BakeoffKey> {
  const checked = checkParts(draft, was.limits);
  const problems: Partial<Record<BakeoffKey, string>> = { ...checked.problems };
  if (tidy(draft.title) === "") problems.title = "Say what it is called.";
  // What has been spent may be more than the limit, as the spending is looked at before a request and not after it, so only a limit
  // that is said again is held to be at least what has been spent
  if (checked.value !== null && checked.value.limit !== was.limit && checked.value.limit < was.spent) {
    problems.limit = `${formatCost(was.spent)} has been spent already, so the most it may spend is at least that.`;
  }
  if (Object.keys(problems).length > 0 || checked.value === null) return { value: null, problems };
  const { title, task, limit, described, labels } = checked.value;
  const before = checkLabels(draftOf(was)).value;
  const change: BakeoffChange = {};
  if (title !== was.title) change.title = title;
  if (task !== was.task) change.task = task;
  if (draft.data !== (was.data?.own ?? "")) change.data = draft.data;
  if (!sameData(described, was.described)) change.described = described ?? {};
  if (JSON.stringify(labels) !== JSON.stringify(before)) change.labels = labels ?? {};
  if (limit !== was.limit) change.limit = limit;

  return { value: change, problems: {} };
}

// Whether there is nothing in a change
export function isNoChange(change: BakeoffChange): boolean {
  return Object.keys(change).length === 0;
}

// What has been spent of what it may, in dollars
export function describeSpending(bakeoff: Pick<BakeoffSummary, "spent" | "limit" | "cost_known">): string {
  const text = `${formatCost(bakeoff.spent)} of ${formatCost(bakeoff.limit)} spent`;

  return bakeoff.cost_known ? text : `${text}, and not all of what was spent is known`;
}

// What may still be spent, and why there may be none that the limit does not say
export function describeLeft(bakeoff: Pick<Bakeoff, "left" | "limit" | "cost_known">): string {
  if (!bakeoff.cost_known) {
    return "Some requests did not say what they used, so what was spent is not known, and nothing more is spent. Say a higher limit to go on.";
  }

  return `${formatCost(bakeoff.left)} is left of ${formatCost(bakeoff.limit)}.`;
}

// How many methods are in the running
export function describeMethods(count: number): string {
  if (count === 0) return "No methods yet";

  return count === 1 ? "1 method" : `${count} methods`;
}

// The parts of what a person said their data is, as each is called
const SCOPE_LABELS: readonly (readonly [Exclude<keyof ScopeData, "sample_size" | "sample_unit">, string])[] = [
  ["species", "Species"],
  ["tissue", "Tissue"],
  ["assay", "Assay"],
  ["input_format", "Input format"],
];

// What the person said their data is, a line for each thing they said, or none if they said nothing. What was not said is an empty
// text, or a size of none.
export function describeScope(described: ScopeData | null): { label: string; value: string }[] {
  if (described === null) return [];
  const lines = SCOPE_LABELS.flatMap(([key, label]) => {
    const value = described[key];

    return value !== undefined && value !== "" ? [{ label, value }] : [];
  });
  if (described.sample_size !== undefined && described.sample_size > 0) {
    const unit = described.sample_unit !== undefined && described.sample_unit !== "" ? ` ${described.sample_unit}` : "";
    lines.push({ label: "Sample size", value: `${described.sample_size.toLocaleString("en-US")}${unit}` });
  }

  return lines;
}

// Where the right answers are, in a line: the file, its column of answers, and the column of what each is the answer to
export function describeLabels(labels: BakeoffLabels): string {
  const by = labels.id_column !== null ? `, with what each is the answer to in "${labels.id_column}"` : ", in the order of the data";

  return `${labels.own}, the answers in "${labels.column}"${by}`;
}
