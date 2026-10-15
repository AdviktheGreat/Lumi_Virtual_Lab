import { asRecord, asText } from "./read";
import type { Question } from "./transcript";

// What a server's question is answered with. The server describes each field of its form as a JSON schema, and a form
// is made of them here as the terminal makes one: a field is text, a number, a whole number, yes or no, one of some
// choices, or a list.

export type FieldKind = "string" | "number" | "integer" | "boolean" | "choice" | "array";

export interface Option {
  value: unknown;
  label: string;
}

// What a field holds while it is being filled in: yes or no, text, or the numbers of the options chosen, which are
// given as text so that a choice is told from another by where it is, and is given back as the value it was
export type FormValue = string | boolean | string[];

export interface FormField {
  name: string;
  label: string;
  description: string;
  kind: FieldKind;
  required: boolean;
  // The values a choice may take, or that the items of a list may, where they are a choice
  options: Option[];
  // What the items of a list are, where they are not a choice
  item: FieldKind;
  initial: FormValue;
}

function labelOf(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

// The values a field may take, where it is a choice
function optionsOf(schema: Record<string, unknown>): Option[] | null {
  if (Array.isArray(schema.enum)) return schema.enum.map((value) => ({ value, label: labelOf(value) }));
  for (const key of ["oneOf", "anyOf"]) {
    const given = schema[key];
    if (Array.isArray(given) && given.length > 0 && given.every((option) => "const" in asRecord(option))) {
      return given.map((option) => {
        const one = asRecord(option);

        return { value: one.const, label: asText(one.title, labelOf(one.const)) };
      });
    }
  }

  return null;
}

function kindOf(schema: Record<string, unknown>): FieldKind {
  if (schema.type === "array") return "array";
  if (optionsOf(schema) !== null) return "choice";

  return schema.type === "boolean" || schema.type === "integer" || schema.type === "number" ? schema.type : "string";
}

function textOf(value: unknown): string {
  if (typeof value === "string") return value;

  return typeof value === "number" && Number.isFinite(value) ? String(value) : "";
}

// Where a value is among the options, which is the same value of the same kind, so that 1 is not taken for true
function placeOf(options: Option[], value: unknown): number {
  return options.findIndex((option) => typeof option.value === typeof value && option.value === value);
}

function initialOf(schema: Record<string, unknown>, kind: FieldKind, options: Option[]): FormValue {
  switch (kind) {
    case "boolean":
      return schema.default === true;
    case "choice": {
      const at = placeOf(options, schema.default);

      return at === -1 ? "" : String(at);
    }
    case "array": {
      const given = Array.isArray(schema.default) ? schema.default : [];
      if (options.length > 0) return given.map((value) => placeOf(options, value)).filter((at) => at !== -1).map(String);

      return given.map(textOf).filter((text) => text !== "").join(", ");
    }
    case "string":
      return typeof schema.default === "string" ? schema.default : "";
    default:
      return typeof schema.default === "number" ? textOf(schema.default) : "";
  }
}

// The fields of a question's form, in the order the server gave them
export function formFields(question: Pick<Question, "fields" | "required">): FormField[] {
  return Object.entries(question.fields).map(([name, schema]) => {
    const kind = kindOf(schema);
    const items = asRecord(schema.items);
    const options = (kind === "choice" ? optionsOf(schema) : kind === "array" ? optionsOf(items) : null) ?? [];
    const item = kind === "array" ? kindOf(items) : "string";

    return {
      name,
      label: asText(schema.title, name),
      description: asText(schema.description),
      kind,
      required: question.required.includes(name),
      options,
      item: item === "array" || item === "choice" ? "string" : item,
      initial: initialOf(schema, kind, options),
    };
  });
}

export function initialValues(fields: FormField[]): Record<string, FormValue> {
  return Object.fromEntries(fields.map((field) => [field.name, field.initial]));
}

// Whether a number names one of the options
function isOption(options: Option[], at: number): boolean {
  return Number.isInteger(at) && at >= 0 && at < options.length;
}

type Read = { ok: true; value: unknown } | { ok: false; error: string };

const WHOLE = /^[+-]?\d+$/;
const DECIMAL = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

// One value typed as text, as the kind it is of
function readText(text: string, kind: FieldKind, label: string): Read {
  if (kind === "integer") {
    const value = Number(text);

    return WHOLE.test(text) && Number.isSafeInteger(value) ? { ok: true, value } : { ok: false, error: `${label} is a whole number` };
  }
  if (kind === "number") {
    const value = Number(text);

    return DECIMAL.test(text) && Number.isFinite(value) ? { ok: true, value } : { ok: false, error: `${label} is a number` };
  }
  if (kind === "boolean") {
    const yes = ["y", "yes", "true"].includes(text.toLowerCase());
    const no = ["n", "no", "false"].includes(text.toLowerCase());

    return yes || no ? { ok: true, value: yes } : { ok: false, error: `${label} is yes or no` };
  }

  return { ok: true, value: text };
}

export type Answer = { ok: true; answer: Record<string, unknown> } | { ok: false; errors: Record<string, string> };

// What the form is filled in with, as the answer the server takes, or what is wrong with it. A field that is left empty
// is left out, if it need not be filled in.
export function readAnswer(fields: FormField[], values: Record<string, FormValue>): Answer {
  const answer: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  const empty = (field: FormField) => {
    if (field.required) errors[field.name] = `${field.label} must be filled in`;
  };

  for (const field of fields) {
    const value = values[field.name] ?? field.initial;
    if (field.kind === "boolean") {
      answer[field.name] = value === true;
    } else if (field.kind === "choice") {
      const at = typeof value === "string" ? Number(value) : NaN;
      if (value === "" || !isOption(field.options, at)) empty(field);
      else answer[field.name] = field.options[at].value;
    } else if (field.kind === "array" && field.options.length > 0) {
      const chosen = Array.isArray(value) ? value.map(Number).filter((at) => isOption(field.options, at)) : [];
      if (chosen.length === 0) empty(field);
      else answer[field.name] = chosen.map((at) => field.options[at].value);
    } else if (field.kind === "array") {
      const parts = (typeof value === "string" ? value : "")
        .split(",")
        .map((part) => part.trim())
        .filter((part) => part !== "");
      if (parts.length === 0) {
        empty(field);
        continue;
      }
      const read = parts.map((part) => readText(part, field.item, field.label));
      const bad = read.find((one) => !one.ok);
      if (bad !== undefined && !bad.ok) errors[field.name] = bad.error;
      else answer[field.name] = read.map((one) => (one.ok ? one.value : null));
    } else {
      const text = typeof value === "string" ? value : "";
      if (text.trim() === "") {
        empty(field);
        continue;
      }
      const read = readText(field.kind === "string" ? text : text.trim(), field.kind, field.label);
      if (read.ok) answer[field.name] = read.value;
      else errors[field.name] = read.error;
    }
  }

  return Object.keys(errors).length > 0 ? { ok: false, errors } : { ok: true, answer };
}

// Whether a page may be sent to an address, which only a web page may: anything else, such as javascript:, is one that a
// link must not follow
export function isWebAddress(url: string | null): url is string {
  if (url === null) return false;
  try {
    const parsed = new URL(url);

    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}
