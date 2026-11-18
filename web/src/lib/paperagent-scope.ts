import { characters, sentence, type Checked } from "./checks";
import { tidy } from "./scientists";
import type { MethodCard, ScopeCheck, ScopeData, ScopeOutcome, ScopeStatement } from "./types";

// How long what is said of the data may be, as the server counts it: words, and the words for what a size counts
export const MAX_SCOPE_CHARS = 200;
export const MAX_UNIT_CHARS = 40;
// The largest sample size, so that a number that is a typing slip is not sent
export const MAX_SIZE = 10 ** 12;

// What a person typed of their data
export interface ScopeDraft {
  species: string;
  tissue: string;
  assay: string;
  format: string;
  size: string;
  unit: string;
}

export const EMPTY_SCOPE_DRAFT: ScopeDraft = { species: "", tissue: "", assay: "", format: "", size: "", unit: "" };

export type ScopeKey = keyof ScopeDraft | "form";

// The parts that are said in words, and the field of the server that each is
const WORDS: readonly (readonly [keyof ScopeDraft, "species" | "tissue" | "assay" | "input_format"])[] = [
  ["species", "species"],
  ["tissue", "tissue"],
  ["assay", "assay"],
  ["format", "input_format"],
];

// What is sent of what a person typed of their data, or what is wrong with it. A part that was left blank is left out, since
// what is not said is not checked. A size may be typed with commas between its thousands.
export function checkScope(draft: ScopeDraft): Checked<ScopeData, ScopeKey> {
  const problems: Partial<Record<ScopeKey, string>> = {};
  const data: ScopeData = {};
  for (const [part, field] of WORDS) {
    const words = tidy(draft[part]);
    if (words === "") continue;
    if (characters(words) > MAX_SCOPE_CHARS) problems[part] = `That is at most ${MAX_SCOPE_CHARS} characters.`;
    else if (!/[\p{L}\p{N}]/u.test(words)) problems[part] = "Say it in words, with a letter or a digit in them.";
    data[field] = words;
  }
  const unit = tidy(draft.unit);
  if (characters(unit) > MAX_UNIT_CHARS) problems.unit = `That is at most ${MAX_UNIT_CHARS} characters.`;
  const typed = tidy(draft.size).replace(/(?<=\d),(?=\d{3}(?!\d))/g, "");
  if (typed !== "") {
    const size = /^\d+$/.test(typed) ? Number(typed) : Number.NaN;
    if (!Number.isSafeInteger(size) || size < 1 || size > MAX_SIZE) {
      problems.size = "The sample size is a whole number, one or more.";
    } else {
      data.sample_size = size;
      if (unit !== "") data.sample_unit = unit;
    }
  } else if (unit !== "") {
    problems.unit = "Say the sample size as well, or leave this out.";
  }
  if (Object.keys(problems).length === 0 && Object.keys(data).length === 0) {
    problems.form = "Say something of your data: its species, tissue, assay, input format, or sample size.";
  }

  return Object.keys(problems).length > 0 ? { value: null, problems } : { value: data, problems: {} };
}

export interface ScopeOutcomeText {
  label: string;
  text: string;
}

// What an outcome is called, and what it says, which is never that the method works on the data or fails on it
export const OUTCOME_TEXT: Record<ScopeOutcome, ScopeOutcomeText> = {
  inside: {
    label: "Inside",
    text: "The card says the method was used on data like this. That is not that it works on yours.",
  },
  outside: {
    label: "Outside",
    text: "The card does not say the method was used on data like this. That is not that it fails on yours. You can go on.",
  },
  "not covered": {
    label: "Not covered",
    text: "The card does not say enough to tell, in words that a program can compare, so this is not called inside and not warned of.",
  },
};

// What the card says as a whole of what was put against it, with how many things were outside if any
export function describeOutcome(check: ScopeCheck): ScopeOutcomeText {
  const base = OUTCOME_TEXT[check.outcome];
  if (check.outcome !== "outside") return base;
  const count = check.warnings.length;

  return { label: base.label, text: `${count === 1 ? "One thing is" : `${count} things are`} outside. ${base.text}` };
}

// What a thing that was said of the data is called, as the answer for it is headed
export function describeAspect(aspect: string): string {
  return sentence(aspect);
}

// What was put against a statement of the card: whose it is, which is the person's if they changed it or added it
export function describeStatementWhose(statement: ScopeStatement): string {
  if (statement.by === "reading") return "Read by the model";

  return statement.changed ? "Changed by you" : "Added by you";
}

// Where in the paper a statement is, or null if it has no place there, as one that a person added has none
export function describeStatementPlace(statement: ScopeStatement): string | null {
  const parts = [
    ...(statement.page !== null ? [`page ${statement.page}`] : []),
    ...(statement.section !== null && statement.section !== "" ? [statement.section] : []),
  ];

  return parts.length > 0 ? sentence(parts.join(", ")) : null;
}

// How far the paper was read, in a sentence that is said where the card may lack what the paper says, or null where it was read
// to its end
export function describeReading(check: ScopeCheck): string | null {
  const { complete, chunks, read, failed } = check.reading;
  if (chunks === null) return "The paper has not been read, so the card is what a person put on it.";
  if (complete) return null;
  const parts = [`${read} of ${chunks} parts were read`, ...(failed > 0 ? [`${failed} could not be`] : [])];

  return `The paper was not read to its end (${parts.join(", ")}), so the card may lack some of what it says.`;
}

// What the card was when data was put against it, as one string that differs when what the answer depends on does: the statements
// of scope with what they say and whose they are, and whether the card is approved. An answer is kept only while it is the same.
export function cardVersion(card: MethodCard): string {
  const facts = card.scope.map((fact) => [fact.id, fact.by, fact.aspect, fact.value, fact.quote].join("\u0001"));

  return [card.status, card.approved_at ?? "", card.changed_since_approval ? "changed" : "", ...facts].join("\u0002");
}
