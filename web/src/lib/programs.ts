import { cleanTitle } from "./history";
import type { NewChat, ProgramKind } from "./types";

// The most that the instructions of a custom program may be, which is what the server keeps, in characters
export const INSTRUCTIONS_LIMIT = 8000;

export interface ProgramKindInfo {
  kind: ProgramKind;
  name: string;
  // What a person should know to choose it
  about: string;
}

// What a program may be begun as, with the one that most are first
export const PROGRAM_KINDS: ProgramKindInfo[] = [
  {
    kind: "quick_task",
    name: "Quick task",
    about: "Ask the lead for something and follow it through.",
  },
  {
    kind: "custom",
    name: "Custom program",
    about: "A named program with instructions of its own, which the lead follows in all that it does there.",
  },
];

export function kindName(kind: ProgramKind): string {
  return PROGRAM_KINDS.find((known) => known.kind === kind)?.name ?? PROGRAM_KINDS[0].name;
}

// What is typed of a program that is to begin
export interface ProgramDraft {
  kind: ProgramKind;
  name: string;
  instructions: string;
}

export interface ProgramProblems {
  name?: string;
  instructions?: string;
}

export interface CheckedProgram {
  // What the server is asked for, besides what the settings say, which is nothing for a quick task
  begin: Pick<NewChat, "kind" | "title" | "instructions">;
  // What is wrong with what was typed, so that nothing is sent
  problems: ProgramProblems;
}

// How many characters text is, as the server counts them, where a box counts the units of two for some
export function lengthOf(text: string): number {
  return [...text].length;
}

// What a program is begun with, from what was typed. A custom program has a name, which is what it is called from the
// start, and instructions that are not empty or longer than the most there may be.
export function checkProgram(draft: ProgramDraft): CheckedProgram {
  if (draft.kind !== "custom") return { begin: {}, problems: {} };

  const problems: ProgramProblems = {};
  const title = cleanTitle(draft.name);
  if (title === null) problems.name = "A custom program needs a name.";

  const instructions = draft.instructions.trim();
  const length = lengthOf(instructions);
  if (length === 0) problems.instructions = "A custom program needs instructions, which the lead follows in all that it does there.";
  else if (length > INSTRUCTIONS_LIMIT) {
    problems.instructions = `Instructions are at most ${INSTRUCTIONS_LIMIT.toLocaleString("en-US")} characters, and these are ${length.toLocaleString("en-US")}.`;
  }
  if (title === null || Object.keys(problems).length > 0) return { begin: {}, problems };

  return { begin: { kind: "custom", title, instructions }, problems };
}
