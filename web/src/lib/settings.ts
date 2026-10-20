import type { KeyStatuses, Models, Settings, SettingsChange } from "./types";

// Where code can run, as the server names them
export const CODE_PLACES = [
  { value: "none", label: "Nowhere", about: "The lab reasons and writes, and runs no code." },
  { value: "docker", label: "In a Docker container", about: "Code runs apart from this computer, in an image." },
  {
    value: "local",
    label: "On this computer",
    about: "Code runs as you do, with nothing to hold it back: it can read and change your files.",
  },
] as const;

// The images code can run in under Docker, as the server names them
export const SANDBOXES = [
  { value: "python", label: "Plain Python", about: "Python alone, which needs nothing built." },
  { value: "base", label: "Biomni base", about: "Biomni's analysis libraries. Built first, in a few minutes." },
  { value: "bio", label: "Biomni bio", about: "Adds Biomni's bioinformatics tools. Built first, in about half an hour." },
  { value: "full", label: "Biomni full", about: "Adds R and the command-line tools. Built first, in hours." },
] as const;

// What the form shows of the settings, which is what is typed where it is typed
export interface Draft {
  model: string;
  stream: boolean;
  // The most a conversation may spend, in dollars, as it is typed: nothing for no limit
  limit: string;
  code: string;
  sandbox: string;
  network: boolean;
  python: string;
  dataLake: string;
  forwardKeys: string[];
}

export function draftOf(settings: Settings): Draft {
  return {
    model: settings.model,
    stream: settings.stream,
    limit: settings.max_cost === null ? "" : String(settings.max_cost),
    code: settings.code,
    sandbox: settings.sandbox,
    network: settings.network,
    python: settings.python,
    dataLake: settings.data_lake,
    forwardKeys: [...settings.forward_keys],
  };
}

// An amount in dollars as it is typed: digits with a point in them at most
const AMOUNT = /^(\d+(\.\d*)?|\.\d+)$/;

// The amount a limit says, null for none, or undefined when what was typed is not one
export function parseLimit(typed: string): number | null | undefined {
  if (typed.trim() === "") return null;
  const text = typed.trim().replace(/^\$\s*/, "");
  if (!AMOUNT.test(text)) return undefined;
  const amount = Number(text);

  return Number.isFinite(amount) ? amount : undefined;
}

export interface Problems {
  model?: string;
  limit?: string;
}

export interface Changes {
  // What differs from the settings, as the server is asked for it
  changes: SettingsChange;
  // What is wrong with what was typed, so that it is not sent
  problems: Problems;
}

// Whether two lists have the same names, whatever the order
function sameNames(one: readonly string[], other: readonly string[]): boolean {
  const sorted = [...other].sort();

  return one.length === other.length && [...one].sort().every((name, at) => name === sorted[at]);
}

// What the form says, as a change to the settings it began from: nothing is said of what was left as it was, so that a
// setting someone else changed meanwhile is not undone
export function changesOf(draft: Draft, settings: Settings): Changes {
  const changes: SettingsChange = {};
  const problems: Problems = {};

  const model = draft.model.trim();
  if (model === "") problems.model = "Choose a model.";
  else if (model !== settings.model) changes.model = model;

  const limit = parseLimit(draft.limit);
  if (limit === undefined) problems.limit = "A limit is an amount in dollars, such as 5 or 12.50. Leave it empty for none.";
  else if (limit !== settings.max_cost) changes.max_cost = limit;

  if (draft.stream !== settings.stream) changes.stream = draft.stream;
  if (draft.code !== settings.code) changes.code = draft.code;
  if (draft.sandbox !== settings.sandbox) changes.sandbox = draft.sandbox;
  if (draft.network !== settings.network) changes.network = draft.network;
  if (draft.python.trim() !== settings.python) changes.python = draft.python.trim();
  if (draft.dataLake.trim() !== settings.data_lake) changes.data_lake = draft.dataLake.trim();
  if (!sameNames(draft.forwardKeys, settings.forward_keys)) changes.forward_keys = draft.forwardKeys;

  return { changes, problems };
}

// Whether a model is one of those the server offers
export function isOffered(model: string, models: Models | null): boolean {
  return models !== null && models.models.some((choice) => choice.id === model);
}

// The keys that the model's provider needs and that are not set, or none if they are, or if the model is not one that
// the server knows the provider of
export function keysMissingFor(model: string, models: Models | null, keys: KeyStatuses | null): string[] {
  // OpenRouter serves far more models than the server lists, all of them named openrouter/<author>/<model>
  const provider =
    models?.models.find((choice) => choice.id === model)?.provider ?? (model.startsWith("openrouter/") ? "OpenRouter" : null);
  if (!provider || keys === null) return [];

  return keys.providers.find((status) => status.provider === provider)?.missing ?? [];
}
