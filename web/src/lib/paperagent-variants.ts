import { characters, count, whole, type Checked } from "./checks";
import { formatDuration, timeAgo } from "./format";
import type {
  ClaimOutcome,
  ControlVerdict,
  PaperAgentVariantOptions,
  PaperAgentVariants,
  Variant,
  VariantArgument,
  VariantOption,
  VariantStatus,
} from "./types";

// How deep a list or table may be that holds a value, as the server takes it
const MOST_DEPTH = 4;
// The one key of a table that the server keeps for a number that JSON does not have
const RESERVED_KEY = "$float";
// How much of a value is shown in a line
const SHOWN = 60;

export type VariantKey = "claim" | "changes" | "minutes" | "repeats" | "gigabytes" | "note" | `value:${string}`;

export interface VariantDraft {
  // The id of the claim whose call is made again
  claim: string;
  // What each argument that is to change is to be, as it was typed, by the argument's name. An argument with nothing typed is not changed.
  values: Record<string, string>;
  minutes: string;
  repeats: string;
  gigabytes: string;
  note: string;
}

export function emptyVariant(variants: Pick<PaperAgentVariants, "limits">, claim = ""): VariantDraft {
  return {
    claim,
    values: {},
    minutes: String(variants.limits.default_minutes),
    repeats: String(variants.limits.default_repeats),
    gigabytes: String(variants.limits.default_gigabytes),
    note: "",
  };
}

type Offered = Extract<VariantOption, { can: true }>;

// What may be changed of a claim's call, if a variant of the claim can be made
export function offeredFor(variants: Pick<PaperAgentVariants, "claims">, claim: string): Offered | undefined {
  const option = variants.claims.find((each) => each.claim === claim);

  return option !== undefined && option.can ? option : undefined;
}

// The claims that a variant can be made of, and those that it cannot with why
export function usable(variants: Pick<PaperAgentVariants, "claims">): Offered[] {
  return variants.claims.filter((each): each is Offered => each.can);
}

export function unusable(variants: Pick<PaperAgentVariants, "claims">): Extract<VariantOption, { can: false }>[] {
  return variants.claims.filter((each): each is Extract<VariantOption, { can: false }> => !each.can);
}

// A claim in a few words, as it is chosen by: the number that the paper reports and what it says
export function claimLabel(claim: Pick<ClaimOutcome, "value" | "quote"> | undefined, id: string): string {
  if (claim === undefined) return id;
  const quote = claim.quote.length <= SHOWN ? claim.quote : `${claim.quote.slice(0, SHOWN)}…`;

  return claim.value ? `${claim.value}: ${quote}` : quote;
}

// A value as it is shown in a line, which is cut if it is long
export function showValue(value: unknown, limit = SHOWN): string {
  const text = JSON.stringify(value) ?? "";

  return text.length <= limit ? text : `${text.slice(0, limit)}…`;
}

// Whether a value is one that an argument can be given as: text, true or false, nothing, a finite number, or a list or a table of those, not
// nested too deep. This is what the server takes, so that a value that is not is said so before it is sent.
export function isPlain(value: unknown, depth = 0): boolean {
  if (depth > MOST_DEPTH) return false;
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every((item) => isPlain(item, depth + 1));
  if (typeof value === "object") {
    return Object.entries(value).every(([key, item]) => key !== RESERVED_KEY && isPlain(item, depth + 1));
  }

  return false;
}

function hasWholeNumber(value: unknown): boolean {
  if (typeof value === "number") return Number.isInteger(value);
  if (Array.isArray(value)) return value.some(hasWholeNumber);
  if (typeof value === "object" && value !== null) return Object.values(value).some(hasWholeNumber);

  return false;
}

// Whether a new value is what the argument was given. The server tells 1 from 1.0, which JSON read here cannot, so a number that may have
// been written with a point is left for the server to judge, as it would otherwise be refused here when it is a change.
function isUnchanged(value: unknown, argument: VariantArgument): boolean {
  if (argument.value === null && argument.text !== "None") return false;
  if (hasWholeNumber(argument.value) && /\d[.eE]/.test(argument.text)) return false;

  return JSON.stringify(value) === JSON.stringify(argument.value);
}

export type Parsed = { ok: true; value: unknown } | { ok: false; problem: string };

// A new value as it was typed, which is written as JSON: text in double quotes, a number, true, false, null, or a list or table of those
export function parseValue(text: string, name: string, mostChars: number): Parsed {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return {
      ok: false,
      problem: `The new value for ${name} is written as JSON: text in double quotes, such as "abc", a number, true, false, null, or a list such as [1, 2, 3].`,
    };
  }
  if (!isPlain(value)) {
    return {
      ok: false,
      problem: `The new value for ${name} is not one that an argument is given as: text, true or false, null, a finite number, or a list or table of those, nested at most ${MOST_DEPTH} deep.`,
    };
  }
  if (JSON.stringify(value).length > mostChars) return { ok: false, problem: `The new value for ${name} is at most ${mostChars} characters of JSON.` };

  return { ok: true, value };
}

// What making a variant is asked for: the claim, the new value of each argument to change, and how long and how often the call is made
export function checkVariant(draft: VariantDraft, variants: PaperAgentVariants): Checked<PaperAgentVariantOptions, VariantKey> {
  const { limits } = variants;
  const problems: Partial<Record<VariantKey, string>> = {};
  const option = variants.claims.find((each) => each.claim === draft.claim);
  const changes: Record<string, unknown> = {};
  if (option === undefined) problems.claim = "Choose the claim whose call is made again.";
  else if (!option.can) problems.claim = `${option.refused.message}.`;
  else {
    for (const argument of option.arguments) {
      const typed = (draft.values[argument.name] ?? "").trim();
      if (typed === "" || !argument.plain) continue;
      const parsed = parseValue(typed, argument.name, limits.max_value_chars);
      if (!parsed.ok) problems[`value:${argument.name}`] = parsed.problem;
      else if (isUnchanged(parsed.value, argument)) problems[`value:${argument.name}`] = `${argument.name} was given that value, so it is not a change.`;
      else changes[argument.name] = parsed.value;
    }
    const wrong = Object.keys(problems).some((key) => key.startsWith("value:"));
    const changed = Object.keys(changes).length;
    if (!wrong && changed === 0) problems.changes = "Give at least one argument a new value.";
    else if (changed > limits.most_changes) problems.changes = `At most ${limits.most_changes} arguments are changed at once.`;
  }
  const asked = (key: "minutes" | "repeats" | "gigabytes", what: string, most: number) => {
    const checked = whole(draft[key], what, 1, most);
    if (checked.problem) problems[key] = checked.problem;

    return checked.value;
  };
  const minutes = asked("minutes", "The most time that both calls may take together, in minutes,", limits.max_minutes);
  const repeats = asked("repeats", "How many times each call is made", limits.max_repeats);
  const gigabytes = asked("gigabytes", "The most that a call may write, in gigabytes,", limits.max_gigabytes);
  const note = draft.note.trim();
  if (characters(note) > limits.max_note_chars) problems.note = `A note is at most ${limits.max_note_chars} characters.`;
  else if (/[\u0000-\u001f\u007f]/.test(note)) problems.note = "A note has no line breaks or other control characters.";
  if (Object.keys(problems).length > 0 || minutes === null || repeats === null || gigabytes === null || option === undefined) {
    return { value: null, problems };
  }

  return { value: { claim: draft.claim, changes, minutes, repeats, gigabytes, ...(note !== "" ? { note } : {}) }, problems: {} };
}

export const STATUS_TITLES: Record<VariantStatus, string> = {
  gave: "Gave a number",
  no_place: "Gave no number at the place",
  unstable: "Gave something else each time",
  error: "Stopped with an error",
  not_run: "Was not made in the time",
};

export function statusTitle(status: string): string {
  return STATUS_TITLES[status as VariantStatus] ?? status;
}

const CONTROL_WHY: Record<ControlVerdict, string> = {
  match: "gave what the tutorial got",
  differs: "did not give what the tutorial got",
  error: "stopped with an error",
  not_run: "was not made in the time",
};

// What the server says of an error or a difference, which does not end with a stop, as the end of a sentence
function ended(text: string): string {
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

function errorText(error: { type: string; message: string }): string {
  return ended(`${error.type}: ${error.message}`);
}

// What the call gave with the changes, in a sentence, beside what the call that the claim was held to gave
export function describeOutcome(variant: Pick<Variant, "variant" | "claim_run">): string {
  const made = variant.variant;
  if (made.status === "gave") return `It gave ${made.gave}, where the call that the claim was held to gave ${variant.claim_run}.`;
  if (made.status === "no_place") {
    return `It ran, and gave ${made.type === null ? "something" : `a ${made.type}`} with no number at the place that the claim was held to.`;
  }
  if (made.status === "unstable") return "It gave something else each time it was made, so no one number is said.";
  if (made.status === "error") return made.error !== null ? `It stopped with ${errorText(made.error)}` : "It stopped with an error.";

  return "It was not made in the time that was given.";
}

// What was changed in a variant, one argument to a line, with what it was
export function describeChange(change: Variant["changes"][number]): string {
  return `${change.name}: ${showValue(change.now)} in place of ${showValue(change.was)}`;
}

// Whether a variant can be set beside what the claim was held to, and if it cannot, why. Only a call that gives what the tutorial got when it
// is made alone stands for what the tutorial did.
export function describeComparable(variant: Pick<Variant, "comparable" | "control" | "variant">): string {
  if (variant.comparable) return "Comparable: the same call with nothing changed gave what the tutorial got, and the variant gave a number.";
  if (variant.control.verdict !== "match") {
    const why = CONTROL_WHY[variant.control.verdict] ?? variant.control.verdict;

    return `Not comparable: the same call with nothing changed ${why}, so the call alone does not stand for what the tutorial did.`;
  }

  return "Not comparable: the same call with nothing changed gave what the tutorial got, but the variant gave no number to set beside the claim's.";
}

// Whether the number that a variant gave rounds to the paper's, which is never a reproduction. It is nothing if the variant gave no number.
export function describeRounds(variant: Pick<Variant, "rounds_to_paper" | "number">): string | null {
  if (variant.rounds_to_paper === null) return null;

  return variant.rounds_to_paper
    ? `The number that it gave rounds to the paper's ${variant.number}. That is not a reproduction of the paper's result.`
    : `The number that it gave does not round to the paper's ${variant.number}.`;
}

// How a variant was made, in a line: when, how long it took, and what the calls were allowed
export function describeMade(variant: Pick<Variant, "made_at" | "seconds" | "repeats" | "limits">): string {
  const took = formatDuration(variant.seconds);
  const when = timeAgo(variant.made_at) || "a while ago";

  return `Made ${when}${took ? `, which took ${took}` : ""}. Each call was made ${count(variant.repeats, "time")}, for at most ${count(variant.limits.minutes, "minute")} and ${count(variant.limits.gigabytes, "gigabyte")} written.`;
}

// How a number is shown, which is not shown if there is none
function shownNumber(value: number | null): string {
  return value === null ? "no number" : String(value);
}

// What a variant was made of, one part to a line: the call and what the claim was held to, what each time it was made gave, what the call with
// nothing changed gave and where it parted from what the tutorial got, what went wrong, and what counted as the same number
export function describeRun(variant: Variant): string[] {
  const { control, variant: made } = variant;
  const lines = [`The claim was held to ${variant.where}, run by ${variant.tutorial.path}, which gave ${variant.claim_run}.`];
  if (made.values.length > 0) lines.push(`With the changes, the ${count(made.values.length, "time")} it was made gave: ${made.values.map(shownNumber).join(", ")}.`);
  if (control.gave !== null) lines.push(`With nothing changed, it gave ${control.gave} at the same place.`);
  for (const difference of control.differences) lines.push(ended(`With nothing changed, it differs from what the tutorial got: ${difference}`));
  if (control.error !== null) lines.push(`With nothing changed, it stopped with ${errorText(control.error)}`);
  if (made.error !== null) lines.push(`With the changes, it stopped with ${errorText(made.error)}`);
  for (const difference of made.differences) lines.push(ended(`With the changes, the times it was made differ: ${difference}`));
  lines.push(`Numbers are taken as the same within a relative difference of ${variant.tolerance.relative} or an absolute one of ${variant.tolerance.absolute}.`);

  return lines;
}

// How many variants there are, how many are comparable, and how many round to the paper's number, in a line, and how many are kept that are not shown
export function describeCounts(counts: PaperAgentVariants["counts"], stale: number): string {
  const said =
    counts.variants === 0
      ? "No variant has been made."
      : `${count(counts.variants, "variant")}: ${counts.comparable} comparable, ${counts.rounds_to_paper} that give${counts.rounds_to_paper === 1 ? "s" : ""} a number that rounds to the paper's. None of them is the paper's result.`;
  if (stale === 0) return said;

  return `${said} ${count(stale, "variant")} made of another run of the tutorials, other claims, or another trying ${stale === 1 ? "is" : "are"} kept and not shown.`;
}

// Whether there is anything to take away, which is any variant that is kept, whether it is shown or not
export function hasVariants(variants: Pick<PaperAgentVariants, "variants" | "stale">): boolean {
  return variants.variants.length > 0 || variants.stale > 0;
}
