import type { LibraryScientist, Scientist } from "./types";

// The most the server takes of each part of a scientist
export const MAX_TITLE = 200;
export const MAX_PART = 4000;

export const PARTS = [
  { key: "title", label: "Title", hint: "What the lead calls them, such as Structural Biologist." },
  { key: "expertise", label: "Expertise", hint: "What they know." },
  { key: "goal", label: "Goal", hint: "What they work toward." },
  { key: "role", label: "Role", hint: "What they do in the lab, and how." },
] as const;

export type Part = (typeof PARTS)[number]["key"];

export type ScientistDraft = Record<Part, string>;

export const EMPTY_SCIENTIST: ScientistDraft = { title: "", expertise: "", goal: "", role: "" };

// Words with one space between them, which is how the server keeps every part, so that what is shown is what is kept
export function tidy(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ");
}

export function sameTitle(one: string, other: string): boolean {
  return tidy(one).toLowerCase() === tidy(other).toLowerCase();
}

export function draftOfScientist(scientist: Scientist): ScientistDraft {
  return { title: scientist.title, expertise: scientist.expertise, goal: scientist.goal, role: scientist.role };
}

export interface Checked {
  // What to send, or null while a part is wrong
  scientist: Scientist | null;
  problems: Partial<Record<Part, string>>;
}

// Whether what was written can be saved. Someone new takes a title that none has, since saving with one that is taken
// would put them in the place of the one that has it, which is what editing is for.
export function checkScientist(draft: ScientistDraft, library: readonly LibraryScientist[], isNew: boolean): Checked {
  const scientist: Scientist = {
    title: tidy(draft.title),
    expertise: tidy(draft.expertise),
    goal: tidy(draft.goal),
    role: tidy(draft.role),
  };
  const problems: Checked["problems"] = {};
  for (const { key, label } of PARTS) {
    if (scientist[key] === "") problems[key] = `${label} is needed.`;
  }
  if (isNew && scientist.title !== "" && library.some((existing) => sameTitle(existing.title, scientist.title))) {
    problems.title = "There is a scientist with this title. Edit them instead, or choose another title.";
  }

  return { scientist: Object.keys(problems).length === 0 ? scientist : null, problems };
}

// Whether what was written is not what the scientist is
export function isChanged(draft: ScientistDraft, scientist: Scientist): boolean {
  return PARTS.some(({ key }) => tidy(draft[key]) !== tidy(scientist[key]));
}
