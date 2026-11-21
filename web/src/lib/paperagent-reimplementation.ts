import { characters, count, dollars, whole, type Checked } from "./checks";
import { formatCost, timeAgo } from "./format";
import type {
  MatchingEntry,
  MatchingParameter,
  MatchingStatus,
  PaperAgentMatching,
  PaperAgentMatchingOptions,
  PaperAgentReimplementation,
  ReimplementationChoice,
  ReimplementationKept,
  ReimplementationOffer,
  ReimplementationPlace,
  ReimplementationSpan,
  ReimplementationStatus,
} from "./types";

// The most characters a function's name may have, as the server says
export const MAX_NAME_CHARS = 64;
const NAME = /^[a-z_][a-z0-9_]*$/;

// What the person chose of what the model is given, as they typed it
export interface OfferDraft {
  sections: number[];
  search: string;
  name: string;
  goal: string;
}

type OfferKey = "sections" | "search" | "name" | "goal";

// What is chosen to begin with: what the offer that the server made is of, which is the sections whose headings say that they are of how
// something was done, under the name made from the paper's title
export function draftOf(reimplementation: Pick<PaperAgentReimplementation, "offer" | "default_sections">): OfferDraft {
  const { offer } = reimplementation;
  if (offer === null) return { sections: [...reimplementation.default_sections], search: "", name: "", goal: "" };

  return { sections: [...offer.sections].sort((one, other) => one - other), search: offer.search ?? "", name: offer.name, goal: offer.goal ?? "" };
}

// What the offer is asked for, from what was chosen. Words to search for stand in for sections, and the server takes no sections and no
// words to mean those of the method, which is not what a person who chose none meant
export function checkChoice(draft: OfferDraft, limits: PaperAgentReimplementation["limits"]): Checked<ReimplementationChoice, OfferKey> {
  const problems: Partial<Record<OfferKey, string>> = {};
  const search = draft.search.trim();
  const name = draft.name.trim();
  const goal = draft.goal.trim();
  if (draft.sections.length === 0 && search === "") problems.sections = "Choose a section of the paper, or say words to look for in it.";
  else if (draft.sections.length > limits.most_sections) problems.sections = `Choose at most ${limits.most_sections} sections.`;
  if (characters(search) > limits.most_search_chars) problems.search = `The words to look for are at most ${limits.most_search_chars} characters.`;
  if (name === "") problems.name = "Say what the function is called.";
  else if (!NAME.test(name) || name.length > MAX_NAME_CHARS) {
    problems.name = `A function's name is lowercase letters, digits, and underscores, not beginning with a digit, at most ${MAX_NAME_CHARS} of them.`;
  }
  if (characters(goal) > limits.most_goal_chars) problems.goal = `What you want of it is at most ${limits.most_goal_chars} characters.`;
  if (Object.keys(problems).length > 0) return { value: null, problems };

  return {
    value: {
      ...(draft.sections.length > 0 ? { sections: [...draft.sections].sort((one, other) => one - other) } : {}),
      ...(search !== "" ? { search } : {}),
      name,
      ...(goal !== "" ? { goal } : {}),
    },
    problems: {},
  };
}

// Whether the offer that is shown is of what is chosen now, which is what the person reads and agrees to
export function sameChoice(choice: ReimplementationChoice, offer: ReimplementationOffer): boolean {
  const chosen = [...(choice.sections ?? [])].sort((one, other) => one - other);
  const offered = [...offer.sections].sort((one, other) => one - other);

  return (
    chosen.length === offered.length &&
    chosen.every((section, index) => section === offered[index]) &&
    (choice.search ?? null) === offer.search &&
    choice.name === offer.name &&
    (choice.goal ?? null) === offer.goal
  );
}

// What the form that writes starts over by: another function is kept, or what it would be given by default is not what it was, as the
// paper or the model or the agent's title is not what it was
export function offerFormKey(reimplementation: Pick<PaperAgentReimplementation, "kept" | "offer">): string {
  return `${reimplementation.kept?.finished_at ?? "none"}|${reimplementation.offer?.key ?? "none"}`;
}

// The most that writing the function may spend, which must be said
export function checkBudget(budget: string): { value: number | null; problem?: string } {
  return dollars(budget, "the most it may spend", false);
}

// Where in the paper its words are from, by the headings: those of the sections that were chosen, in the order of the paper, and then
// those of the places that a search found. Sections that touch one another are one place, which has only the first of their headings
function sectionsOf(
  places: readonly ReimplementationPlace[],
  chosen: readonly number[],
  spans: readonly Pick<ReimplementationSpan, "index" | "title">[],
): string {
  const titles = new Map(spans.map((span) => [span.index, span.title]));
  const chosenTitles = [...chosen].sort((one, other) => one - other).map((index) => titles.get(index));
  const named = [
    ...new Set([...chosenTitles, ...places.map((place) => place.section)].filter((title): title is string => typeof title === "string")),
  ];
  if (named.length === 0) return "";

  return ` (${named.join(", ")})`;
}

// What the model would be given, in a line: how much of the paper, from where, and what the function would be called
export function describeOffer(offer: ReimplementationOffer, mostChars: number, spans: readonly Pick<ReimplementationSpan, "index" | "title">[]): string {
  const places =
    offer.places.length === 0
      ? "no place of the paper"
      : `${count(offer.places.length, "place")} of the paper${sectionsOf(offer.places, offer.sections, spans)}`;
  const goal = offer.goal !== null ? ", with what you want of it, as your words" : "";

  return `${places}, ${offer.chars.toLocaleString("en-US")} characters in all of the most ${mostChars.toLocaleString("en-US")}${goal}. The function would be called ${offer.name}.`;
}

export const WRITING_TITLES: Record<ReimplementationStatus, string> = { written: "Written", failed: "Not written", stopped: "Stopped" };

export function writingTitle(status: string): string {
  return WRITING_TITLES[status as ReimplementationStatus] ?? status;
}

// How the writing went, in a line: when, by which model, in how many attempts, what it cost, and how much of the function was run
export function describeWriting(kept: ReimplementationKept): string {
  const when = timeAgo(kept.finished_at) || "a while ago";
  const cost = kept.cost === null ? "" : `, which cost ${formatCost(kept.cost)}`;
  if (kept.status === "stopped") return `Stopped ${when}, before a function was written${cost}.`;
  if (kept.status === "failed") return `No function was written ${when}. ${kept.model} was asked in ${count(kept.attempts, "attempt")}${cost}.`;
  const run =
    kept.function?.status === "verified"
      ? "It was imported in a container with no network, and nothing else of it was run."
      : "It was read as Python, and was not run.";

  return `Written ${when} by ${kept.model} in ${count(kept.attempts, "attempt")}${cost}. ${run}`;
}

// What the model was given when it wrote it, in a line
export function describeTask(task: ReimplementationKept["task"], spans: readonly Pick<ReimplementationSpan, "index" | "title">[]): string {
  const cut = task.cut ? ", cut to the most that is given" : "";
  const search = task.search !== null ? ` The places found for "${task.search}" were among them.` : "";
  const goal = task.goal !== null ? " It was told what you want of it, as your words." : "";

  return `It was given ${count(task.places.length, "place")} of the paper${sectionsOf(task.places, task.sections, spans)}, ${task.chars.toLocaleString("en-US")} characters in all${cut}, and nothing else of it.${search}${goal}`;
}

// Whether the function that is kept is one that can be checked: it was written, from the paper that is there now, and its file is as it
// was written
export function canCheck(reimplementation: Pick<PaperAgentReimplementation, "ready" | "kept">): boolean {
  const { kept } = reimplementation;

  return reimplementation.ready && kept !== null && kept.status === "written" && kept.current && kept.source !== null;
}

// In the order that they are told of
export const MATCHING_STATUSES: readonly MatchingStatus[] = ["matched", "not_found", "ambiguous", "unstable", "error", "not_run", "hard_coded", "no_inputs"];

export const MATCHING_TITLES: Record<MatchingStatus, string> = {
  matched: "Matched",
  not_found: "Not found",
  ambiguous: "Ambiguous",
  unstable: "Unstable",
  error: "Error",
  not_run: "Not run",
  hard_coded: "Hard-coded",
  no_inputs: "No inputs",
};

export function matchingTitle(status: string): string {
  return MATCHING_TITLES[status as MatchingStatus] ?? status;
}

// How many claims came to each, in a line
export function describeMatchingCounts(counts: Record<MatchingStatus, number>): string {
  const parts = MATCHING_STATUSES.filter((status) => (counts[status] ?? 0) > 0).map((status) => `${counts[status]} ${matchingTitle(status).toLowerCase()}`);

  return parts.length === 0 ? "No claim was tried." : `${parts.join(", ")}.`;
}

// How the last checking went, in a line: when, whether a model was asked and what it cost, and whether it came to its end
export function describeChecking(kept: NonNullable<PaperAgentMatching["kept"]>): string {
  const when = timeAgo(kept.finished_at) || "a while ago";
  const cost = kept.cost === null ? "" : `, which cost ${formatCost(kept.cost)}`;
  const model =
    kept.model === null || kept.requests === 0 ? "No model was asked for inputs" : `${kept.model} was asked for inputs ${count(kept.requests, "time")}${cost}`;
  const ended = kept.status === "stopped" ? " It was stopped before it came to its end." : kept.status === "failed" ? ` It failed: ${kept.error ?? "no reason was given"}` : "";

  return `Checked ${when}. ${model}.${ended}`;
}

function shownArguments(args: Record<string, unknown>): string {
  return JSON.stringify(args);
}

// What came of one claim, one part to a line: what it was called with and whose that was, and what it gave
export function describeEntry(entry: MatchingEntry): string[] {
  const lines: string[] = [];
  if (entry.arguments !== null) {
    const whose = entry.by === "person" ? "the inputs that you gave" : "the inputs that the model read in the passage";
    lines.push(`Called with ${whose}: ${shownArguments(entry.arguments)}.`);
    if (entry.by === "model" && entry.where !== null) lines.push(`The model said that the passage gives them in: "${entry.where}".`);
  } else if (entry.note !== null) {
    lines.push(entry.note);
  }
  if (entry.hard_coded.length > 0) {
    lines.push(`The code has ${entry.hard_coded.join(", ")} in it, which rounds to the paper's number, so finding the number in what it gave would show nothing.`);
  }
  if (entry.status === "matched" && entry.found !== null) {
    lines.push(`It gave ${entry.gave ?? "a value"}, and ${entry.found.value} at ${entry.found.text} rounds to the paper's ${entry.value}.`);
  } else if (entry.status === "ambiguous") {
    lines.push(`It gave ${entry.gave ?? "a value"}, which has the number in ${entry.places} places.`);
  } else if (entry.gave !== null) {
    lines.push(`It gave ${entry.gave}.`);
  }
  if (entry.error !== null) lines.push(`It raised ${entry.error}`);

  return lines;
}

// The function's parameters, in a line, which are what inputs are given for
export function describeParameters(parameters: readonly MatchingParameter[]): string {
  if (parameters.length === 0) return "It takes no parameters.";
  const each = parameters.map((parameter) => `${parameter.name} (${parameter.hint}, ${parameter.required ? "must be given" : `${parameter.default ?? "has a default"} if not given`})`);

  return `Its parameters: ${each.join("; ")}.`;
}

// What the inputs of a claim begin as in the box they are typed in: those that the person gave, or else those that the model read, or
// else each parameter that must be given, with nothing yet
export function inputsText(
  claim: { inputs: { arguments: Record<string, unknown> } | null; entry: Pick<MatchingEntry, "arguments"> | null },
  parameters: readonly MatchingParameter[],
): string {
  const given = claim.inputs?.arguments ?? claim.entry?.arguments ?? Object.fromEntries(parameters.filter((one) => one.required).map((one) => [one.name, null]));

  return JSON.stringify(given, null, 2);
}

// Whether a number is in the value that would not be sent as it was typed: it is not finite, or a whole number beyond what a JSON number of
// the page holds exactly
function hasUnsafeNumber(value: unknown): boolean {
  if (typeof value === "number") return !Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value));
  if (Array.isArray(value)) return value.some(hasUnsafeNumber);
  if (typeof value === "object" && value !== null) return Object.values(value).some(hasUnsafeNumber);

  return false;
}

// The inputs that the person typed for a claim, read as JSON and held to the function's parameters. What else the server checks, such as
// a value that holds the claim's number, it says
export function checkInputs(text: string, parameters: readonly MatchingParameter[], mostChars: number): { value: Record<string, unknown> | null; problem?: string } {
  const typed = text.trim();
  if (typed === "") return { value: null, problem: 'Give the inputs as JSON, by the names of the parameters, such as {"numbers": [1, 2]}.' };
  let parsed: unknown;
  try {
    parsed = JSON.parse(typed);
  } catch {
    return { value: null, problem: "This is not JSON. Give the inputs as an object, by the names of the parameters." };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { value: null, problem: "The inputs are a JSON object, by the names of the parameters." };
  }
  const args = parsed as Record<string, unknown>;
  // The server counts the characters of the inputs as JSON, which are at least those of the compact form, so what is over the most in
  // the compact form is over it there, and what is under it here is for the server to count
  if (characters(JSON.stringify(args)) > mostChars) return { value: null, problem: `The inputs are at most ${mostChars.toLocaleString("en-US")} characters as JSON.` };
  if (hasUnsafeNumber(args)) return { value: null, problem: "A number in the inputs is too big to be sent exactly. Give it as text if the function takes text." };
  const names = new Set(parameters.map((parameter) => parameter.name));
  const unknown = Object.keys(args).filter((name) => !names.has(name));
  if (unknown.length > 0) return { value: null, problem: `The function has no parameter named ${unknown.join(", ")}.` };
  const missing = parameters.filter((parameter) => parameter.required && !(parameter.name in args)).map((parameter) => parameter.name);
  if (missing.length > 0) return { value: null, problem: `Give ${missing.join(", ")}, which ${missing.length === 1 ? "has" : "have"} no default.` };

  return { value: args };
}

export interface MatchingDraft {
  // Whether a model reads the inputs of the claims that the person gave none for
  ask: boolean;
  budget: string;
  minutes: string;
}

type MatchingKey = "ask" | "budget" | "minutes";

export function emptyMatching(checks: Pick<PaperAgentMatching, "limits">): MatchingDraft {
  return { ask: true, budget: "", minutes: String(checks.limits.default_minutes) };
}

// What checking the function is asked for. Without a model, only the claims that the person gave inputs for can be tried
export function checkMatching(draft: MatchingDraft, checks: Pick<PaperAgentMatching, "limits" | "claims">): Checked<PaperAgentMatchingOptions, MatchingKey> {
  const problems: Partial<Record<MatchingKey, string>> = {};
  const minutes = whole(draft.minutes, "The most minutes the calls may take", 1, checks.limits.most_minutes);
  if (minutes.problem) problems.minutes = minutes.problem;
  let budget: number | null = null;
  if (draft.ask) {
    const said = checkBudget(draft.budget);
    if (said.problem) problems.budget = said.problem;
    budget = said.value;
  } else if (!checks.claims.some((claim) => claim.inputs !== null)) {
    problems.ask = "Give the inputs of a claim first, or let a model read them from the paper, as the function has nothing to be called with otherwise.";
  }
  if (Object.keys(problems).length > 0 || minutes.value === null) return { value: null, problems };

  return { value: { ask: draft.ask, ...(budget !== null ? { max_cost: budget } : {}), minutes: minutes.value }, problems: {} };
}
