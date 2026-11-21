import { STANDING_LABELS } from "./bakeoff-methods";
import { characters, count, sentence, whole, type Checked } from "./checks";
import { formatCost, formatDuration } from "./format";
import { formatBytes } from "./files";
import type {
  Bakeoff,
  BakeoffCallBody,
  BakeoffComparedMethod,
  BakeoffComparedState,
  BakeoffComparison,
  BakeoffGroundTruth,
  BakeoffKept,
  BakeoffMethod,
  BakeoffPair,
  BakeoffRunBody,
  BakeoffRunOf,
  BakeoffRunPreview,
  BakeoffScore,
  BakeoffTolerance,
  BakeoffVerdict,
} from "./types";

// What the server takes of a call, which it says again if it is not so, and which is only here so that a page can say it first. How long
// a call may take is a whole number of minutes, five if it is not said.
export const DEFAULT_RUN_MINUTES = 5;
export const MAX_RUN_MINUTES = 30;
export const MAX_TOOL_NAME_CHARS = 100;
export const MAX_ARGUMENTS_CHARS = 20_000;

// Whether a method can be run: it is built, which is what it has tools to be called for. A method that is not is not offered, since the
// server keeps a method that was told to run and was not built as one that was not run, in place of the run that it had.
export function isRunnable(method: Pick<BakeoffMethod, "standing" | "agent">): boolean {
  return method.standing.state === "built" && method.agent !== null;
}

// How many of the methods can be run
export function runnableCount(methods: readonly Pick<BakeoffMethod, "standing" | "agent">[]): number {
  return methods.filter(isRunnable).length;
}

// Where in the container the person's data is, which is where a tool is told to look for it
export function dataPlace(own: string): string {
  return `/data/${own}`;
}

// What a person said of how to run one method: whether to run it, who chooses the call, and the call if it is theirs
export interface CallDraft {
  run: boolean;
  mode: "say" | "propose";
  tool: string;
  // The arguments as JSON text, which is nothing, for none, if it is blank
  args: string;
}

export const EMPTY_CALL: CallDraft = { run: false, mode: "say", tool: "", args: "" };

// What a person said of how to run the methods: each method's call, by its id, and the most minutes that one call may take
export interface RunDraft {
  calls: Record<string, CallDraft>;
  minutes: string;
}

export const EMPTY_RUN: RunDraft = { calls: {}, minutes: String(DEFAULT_RUN_MINUTES) };

// The call that was said for a method, or the one that says nothing
export function callOf(draft: RunDraft, id: string): CallDraft {
  return draft.calls[id] ?? EMPTY_CALL;
}

// A number that is written in JSON, whether it is a string or not being told by the pattern, which tries a string first so that what is in
// one is not taken for a number
const TOKEN = /"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;

// What is wrong with the numbers in arguments that are JSON, which a page sends on as JavaScript writes them. A number that is too big
// to be exact, or is not one, is not sent as it was typed. A decimal that is a whole number is sent without its .0, which would make
// a call that the tool refuses (a whole number is not a decimal to a tool that wants one) one that it takes; so it is not sent, and the
// person writes it as a whole number, which a tool that wants a decimal takes.
function numberProblem(text: string): string | null {
  for (const [token] of text.matchAll(TOKEN)) {
    if (token.startsWith('"')) continue;
    const number = Number(token);
    if (!Number.isFinite(number)) return `${token} is too big to be a number here.`;
    // Too big to be exact whether it was typed with a point or not, so a rewrite of it would be refused for the same reason
    if (Number.isInteger(number) && !Number.isSafeInteger(number)) {
      return `${token} has too many digits to be sent exactly. Give it as text if the tool takes text.`;
    }
    if (!/^-?\d+$/.test(token) && Number.isInteger(number)) {
      return `${token} is a whole number written as a decimal, and is sent without its decimal point. Write it as ${number}, which a tool that wants a decimal takes too.`;
    }
  }

  return null;
}

const EXAMPLE = '{"path": "/data/counts.csv"}';

// The arguments of a call, as they were typed: an object of JSON, by the names of the tool's parameters, which is empty if it is blank, or
// what is wrong with them. The size is counted as JSON is written without spaces, which is a little less than the server counts, and
// the server says if it is over.
export function checkArguments(text: string): { value: Record<string, unknown> | null; problem?: string } {
  if (text.trim() === "") return { value: {} };
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { value: null, problem: `The arguments are JSON, an object such as ${EXAMPLE}, and this is not.` };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { value: null, problem: `The arguments are an object, by the names of the tool's parameters, such as ${EXAMPLE}.` };
  }
  const wrongNumber = numberProblem(text);
  if (wrongNumber !== null) return { value: null, problem: wrongNumber };
  const size = characters(JSON.stringify(parsed));
  if (size > MAX_ARGUMENTS_CHARS) {
    return { value: null, problem: `The arguments are at most ${MAX_ARGUMENTS_CHARS.toLocaleString("en-US")} characters, and these are ${size.toLocaleString("en-US")}.` };
  }

  return { value: parsed as Record<string, unknown> };
}

export type RunKey = "minutes" | "calls" | `${string}:tool` | `${string}:args`;

// What is sent to run the methods, of what was said, or what is wrong with it. Only a method that can be run, and that was said to be
// run, is in it: one that was said to be and has since been taken away, or is not built any more, is left out.
export function checkRun(draft: RunDraft, methods: readonly BakeoffMethod[], limits: Pick<Bakeoff["limits"], "max_candidates">): Checked<BakeoffRunBody, RunKey> {
  const problems: Partial<Record<RunKey, string>> = {};
  const calls: Record<string, BakeoffCallBody> = {};
  let chosen = 0;
  for (const method of methods) {
    const call = callOf(draft, method.id);
    if (!call.run || !isRunnable(method)) continue;
    chosen += 1;
    if (call.mode === "propose") {
      calls[method.id] = { propose: true };
      continue;
    }
    const tool = call.tool.trim();
    if (tool === "") problems[`${method.id}:tool`] = `Choose which of ${method.name}'s tools to call.`;
    else if (characters(tool) > MAX_TOOL_NAME_CHARS) problems[`${method.id}:tool`] = `A tool's name is at most ${MAX_TOOL_NAME_CHARS} characters.`;
    const args = checkArguments(call.args);
    if (args.problem !== undefined) problems[`${method.id}:args`] = args.problem;
    if (tool !== "" && args.value !== null) calls[method.id] = { tool, arguments: args.value };
  }
  if (chosen === 0) problems.calls = "Choose at least one method to run.";
  else if (chosen > limits.max_candidates) problems.calls = `No more than ${count(limits.max_candidates, "method")} can be run at once.`;
  const minutes = whole(draft.minutes, "The most minutes that a call may take", 1, MAX_RUN_MINUTES);
  if (minutes.problem !== undefined) problems.minutes = minutes.problem;
  if (Object.keys(problems).length > 0 || minutes.value === null) return { value: null, problems };

  return { value: { calls, minutes: minutes.value }, problems: {} };
}

// How many of the calls are for a model to propose
export function proposedCount(body: BakeoffRunBody): number {
  return Object.values(body.calls).filter((call) => "propose" in call).length;
}

// How many methods a draft says to run, whether or not what was said of them is fit
export function chosenCount(draft: RunDraft, methods: readonly BakeoffMethod[]): number {
  return methods.filter((method) => isRunnable(method) && callOf(draft, method.id).run).length;
}

// How many of the methods that are chosen are for a model to propose calls for
export function proposingCount(draft: RunDraft, methods: readonly BakeoffMethod[]): number {
  return methods.filter((method) => isRunnable(method) && callOf(draft, method.id).run && callOf(draft, method.id).mode === "propose").length;
}

// What the button that runs the methods says
export function describeRunAll(chosen: number): string {
  return chosen === 0 ? "Run the methods" : `Run ${count(chosen, "method")}`;
}

// What asking a model to propose calls spends, which is from the one limit that finding, reading, and proposing share
export function describeProposing(proposals: number): string {
  return proposals === 0
    ? "Nothing is spent by running a method that you give the call of. It uses your machine's time."
    : `${count(proposals, "model call")} will be paid for out of the limit, one for each method that a model proposes the call of. A call that a model proposes is checked as yours is before it is made, and what asking cost is kept with the run.`;
}

// The words for how a call ended and why, where a short name is all that the server gives of it
const WHY_WORDS: Record<string, string> = {
  error: "The tool raised an error",
  timed_out: "It ran out of time",
  too_big: "It wrote more than was allowed",
  no_answer: "It gave no answer that could be kept",
  outside: "Your data is outside what its card says",
  no_data: "No data was named",
  data_missing: "The data was not found",
  cannot_mount: "The container could not be given the data",
  not_built: "It is not built",
  no_tool: "It has no such tool",
  bad_call: "The call did not fit the tool",
  not_proposed: "No call was proposed",
  limit: "The limit was reached",
  not_yet: "It has not been run",
};

export const RUN_STATE_LABELS: Record<BakeoffComparedState, string> = {
  ran: "Ran",
  failed: "Failed",
  not_run: "Not run",
  not_built: "Not built",
};

// Why a method failed or was not run, as a short phrase, or nothing if it did neither. A method that is not built says where it stands.
export function describeWhy(state: BakeoffComparedState, why: string | null): string | null {
  if (why === null || state === "ran") return null;
  if (state === "not_built") return (STANDING_LABELS as Record<string, string | undefined>)[why] ?? sentence(why.replaceAll("_", " "));

  return WHY_WORDS[why] ?? sentence(why.replaceAll("_", " "));
}

// How much of a result a run kept, as the server tells it: all of it if it is plain data, only a size and a hash if there was more than
// could be kept, and otherwise a look at it
export function keptAs(result: Record<string, unknown>): BakeoffKept {
  if ("value" in result) return "whole";

  return "chars" in result && !("repr" in result) ? "hash" : "look";
}

// How much of an answer was kept, in a table's words
export const KEPT_LABELS: Record<BakeoffKept, string> = {
  whole: "All of it",
  look: "A look at it",
  hash: "Its size and a hash",
};

export function describeKept(kept: BakeoffKept): string {
  if (kept === "whole") return "All of it was kept";
  if (kept === "look") return "A look at it was kept, and not all of it";

  return "Only its size and a hash were kept";
}

// What a result is, from the start of it that a list of methods has
export function describePreview(preview: BakeoffRunPreview): string {
  const size = `${preview.chars.toLocaleString("en-US")} characters as JSON`;
  if (preview.plain) return `A ${preview.type}, ${size}.`;

  return `A ${preview.type}, ${size}. It was more than could be kept as it was, so what is kept of it is a look at it, or its size and a hash.`;
}

// Who chose a call, and what it cost to have a model choose it
export function describeBy(run: Pick<BakeoffRunOf<unknown>, "by" | "proposed">): string {
  if (run.by === "person" || run.proposed === null) return "You chose the call.";
  const cost = run.proposed.cost === null ? "What asking it cost is not known." : `Asking it cost ${formatCost(run.proposed.cost)}.`;

  return `${run.proposed.model} proposed the call, and a program checked it as it checks yours. ${cost}`;
}

// What on the data or the method is not as it was when a run was made, which makes what it gave a thing about what it was
export function describeSince(since: readonly ("data" | "method")[]): string[] {
  return since.map((what) =>
    what === "data"
      ? "Your data is not as it was when this ran: a file was changed, added, or taken away, or it is gone. What it gave may not be of the data as it is."
      : "The method was built again, or from other code, since this ran, so what it gave may not be of the method as it is.",
  );
}

// What is not as it was when a method ran, in a table's words
export function describeSinceShort(since: readonly ("data" | "method")[]): string[] {
  return since.map((what) => (what === "data" ? "Your data is not as it was when it ran" : "It was built again since it ran"));
}

// What data a call was made on, as it was listed then
export function describeRunData(data: NonNullable<BakeoffRunOf<unknown>["data"]>): string {
  const files = `${count(data.files, "file")}, ${formatBytes(data.bytes)}`;

  return `${data.own}, at ${data.path}: ${files}${data.complete ? "" : " (there were more files than were listed)"}`;
}

// How long a call took, or nothing if it was not made
export function describeSeconds(seconds: number | null): string {
  return seconds === null ? "" : formatDuration(seconds);
}

// The arguments of a call, as the person would write them
export function describeArguments(args: Record<string, unknown> | null): string {
  if (args === null) return "";
  try {
    return JSON.stringify(args, null, 2) ?? "";
  } catch {
    return "";
  }
}

// Tolerance

// What was typed of how closely two numbers must be to be the same. Blank is what the server holds to, which is said back with the table.
export interface ToleranceDraft {
  relative: string;
  absolute: string;
}

export const EMPTY_TOLERANCE: ToleranceDraft = { relative: "", absolute: "" };

const DECIMAL = /^(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;

// A number as it was typed, which is not negative, or what is wrong with it. Nothing is a number that the server holds to.
function plainNumber(text: string, what: string): { value: number | null; problem?: string } {
  const typed = text.trim();
  if (typed === "") return { value: null };
  const value = DECIMAL.test(typed) ? Number(typed) : Number.NaN;
  if (!Number.isFinite(value)) return { value: null, problem: `${sentence(what)} is a number that is not negative, such as 0.001.` };

  return { value };
}

// How closely two numbers must be, of what was typed, or what is wrong with it. The relative one is a part of the larger of the two, and is
// less than 1.
export function checkTolerance(draft: ToleranceDraft): Checked<Partial<BakeoffTolerance>, "relative" | "absolute"> {
  const problems: Partial<Record<"relative" | "absolute", string>> = {};
  const relative = plainNumber(draft.relative, "the relative tolerance");
  const absolute = plainNumber(draft.absolute, "the absolute tolerance");
  if (relative.problem !== undefined) problems.relative = relative.problem;
  else if (relative.value !== null && relative.value >= 1) problems.relative = "The relative tolerance is a part of the larger number, so it is less than 1.";
  if (absolute.problem !== undefined) problems.absolute = absolute.problem;
  if (Object.keys(problems).length > 0) return { value: null, problems };

  return {
    value: { ...(relative.value !== null ? { relative: relative.value } : {}), ...(absolute.value !== null ? { absolute: absolute.value } : {}) },
    problems: {},
  };
}

// What to put on an address to ask for a tolerance, which is nothing for the server's own
export function toleranceQuery(tolerance: Partial<BakeoffTolerance> | null | undefined): string {
  const parts: string[] = [];
  if (tolerance?.relative !== undefined) parts.push(`relative=${encodeURIComponent(String(tolerance.relative))}`);
  if (tolerance?.absolute !== undefined) parts.push(`absolute=${encodeURIComponent(String(tolerance.absolute))}`);

  return parts.length === 0 ? "" : `?${parts.join("&")}`;
}

export type TableKind = "methods" | "pairs";

// Where the methods, or each two of them, can be had as a table to open in a spreadsheet, made with the tolerance that was asked for
export function tableAddress(id: string, kind: TableKind, tolerance: Partial<BakeoffTolerance> | null | undefined): string {
  return `/api/bakeoffs/${encodeURIComponent(id)}/tables/${kind}${toleranceQuery(tolerance)}`;
}

// How closely two numbers must be to be the same, in words
export function describeTolerance(tolerance: BakeoffTolerance): string {
  return `Two numbers are the same if they are within ${tolerance.relative} of the larger of the two, or within ${tolerance.absolute} of each other when both are near zero. Anything else is the same only if it is equal.`;
}

// What the comparison is asked again by: what changes of the bake-off that the table is made of, and what finds, builds, or runs its
// methods, so that the table is looked at again when any does
export function comparisonKey(bakeoff: Bakeoff, again: string): string {
  const methods = bakeoff.candidates.map((method) => [method.id, method.standing.state, method.run?.at ?? null, method.run?.since ?? null]);

  return JSON.stringify([again, bakeoff.limit, bakeoff.spent, bakeoff.cost_known, bakeoff.data, bakeoff.labels, methods]);
}

// The table

// A place as it is said: first, second, third, and so on
export function ordinal(number: number): string {
  const rest = number % 100;
  if (rest >= 11 && rest <= 13) return `${number}th`;
  const last = number % 10;

  return `${number}${last === 1 ? "st" : last === 2 ? "nd" : last === 3 ? "rd" : "th"}`;
}

// Where a method is ranked, and that it shares the place if another is ranked the same. A method that is not ranked says so, and not that
// it is last: only the methods that were scored are ranked.
export function describeRank(method: Pick<BakeoffComparedMethod, "id" | "score">, methods: readonly Pick<BakeoffComparedMethod, "id" | "score">[]): string {
  const rank = method.score?.rank ?? null;
  if (rank === null) return "Not ranked";
  const shared = methods.some((other) => other.id !== method.id && other.score?.rank === rank);

  return shared ? `${ordinal(rank)}, shared` : ordinal(rank);
}

// A score as a person reads it: how many of the labels it matched, of how many there are. A method that was not held to the labels is not
// scored, which is not a score of nothing.
export function describeScore(score: BakeoffScore): string {
  if (!score.scored || score.matched === null || score.of === null || score.score === null) {
    return `Not scored. ${score.reason}`.trim();
  }
  const percent = Math.round(score.score * 1000) / 10;

  return `${score.matched} of ${score.of} (${percent}%)`;
}

// How a score was made, which is what to know to trust it: how answers were matched to labels, how many labels it gave no answer to,
// and how many answers there was no label for
export function describeScoreDetail(score: BakeoffScore): string[] {
  if (!score.scored) return [];
  const lines = [score.by === "id" ? "Its answers were matched to the labels by what each is the answer to." : "Its answers were matched to the labels by their place, in the order of the data."];
  if (score.missing !== null && score.missing > 0) lines.push(`${count(score.missing, "label")} had no answer from it, and each counts as wrong.`);
  if (score.extra !== null && score.extra > 0) lines.push(`${count(score.extra, "answer")} had no label, and were not counted.`);

  return lines;
}

// A method's name by its id, which is its id if no method has it
export function nameOf(id: string, methods: readonly Pick<BakeoffComparedMethod, "id" | "name">[]): string {
  return methods.find((method) => method.id === id)?.name ?? id;
}

// Which of the other methods a method gave the same answer as, another answer than, and not a known same or other as
export function describeAgreement(
  method: Pick<BakeoffComparedMethod, "agrees" | "differs" | "unknown">,
  methods: readonly Pick<BakeoffComparedMethod, "id" | "name">[],
): { label: string; names: string[] }[] {
  const lines = [
    { label: "Agrees with", ids: method.agrees },
    { label: "Differs from", ids: method.differs },
    { label: "Not known against", ids: method.unknown },
  ];

  return lines.filter((line) => line.ids.length > 0).map((line) => ({ label: line.label, names: line.ids.map((id) => nameOf(id, methods)) }));
}

export const VERDICT_LABELS: Record<BakeoffVerdict, string> = {
  agree: "Agree",
  differ: "Differ",
  unknown: "Not known",
};

// How much of each answer of a pair was kept, which is what decides whether they can be compared
export function describePairKept(pair: Pick<BakeoffPair, "kept">): string {
  const [first, second] = pair.kept;

  return first === second ? `Both: ${describeKept(first).toLowerCase()}` : `First: ${describeKept(first).toLowerCase()}. Second: ${describeKept(second).toLowerCase()}`;
}

// What it cost to read a method's paper, which may have been paid before the bake-off was made; nothing is said if it was not read
export function describeReading(method: Pick<BakeoffComparedMethod, "cost">): string {
  return method.cost.reading === null ? "—" : formatCost(method.cost.reading);
}

// What it cost to have a model propose the call, which is nothing if the person chose it, and is not said if the method was not run
export function describeAsking(method: Pick<BakeoffComparedMethod, "by" | "cost">): string {
  if (method.by === null) return "—";
  if (method.by === "person") return "None, your call";

  return method.cost.asking === null ? "Not known" : formatCost(method.cost.asking);
}

// Where the right answers are, how many there are, and which file they were, in a line or two
export function describeGroundTruth(truth: BakeoffGroundTruth): string[] {
  const by = truth.id_column !== null ? `, with what each is the answer to in "${truth.id_column}"` : ", in the order of the data";
  const lines = [`${truth.own}, the answers in "${truth.column}"${by}.`];
  if (truth.ok && truth.rows !== null && truth.labelled !== null) {
    const unlabelled = truth.unlabelled !== null && truth.unlabelled > 0 ? `, and ${truth.unlabelled} had none` : "";
    lines.push(`${truth.rows} rows, ${truth.labelled} with an answer${unlabelled}.`);
  }
  if (truth.sha256 !== null) lines.push(`The file is the one with the hash ${truth.sha256.slice(0, 12)}…, so a score says which labels it is of.`);

  return lines;
}

// How the methods came out, in a line: how many ran, failed, were not run, and were not built
export function describeOutcomes(methods: readonly Pick<BakeoffComparedMethod, "state">[]): string {
  if (methods.length === 0) return "There are no methods to compare.";
  const counts = new Map<BakeoffComparedState, number>();
  for (const method of methods) counts.set(method.state, (counts.get(method.state) ?? 0) + 1);
  const parts = (["ran", "failed", "not_run", "not_built"] as const).flatMap((state) => {
    const many = counts.get(state);

    return many === undefined ? [] : [`${many} ${RUN_STATE_LABELS[state].toLowerCase()}`];
  });

  return `${count(methods.length, "method")}: ${parts.join(", ")}.`;
}

// How many of the methods gave an answer, which is how many the table has anything to say of between
export function answeredCount(comparison: Pick<BakeoffComparison, "methods">): number {
  return comparison.methods.filter((method) => method.state === "ran").length;
}
