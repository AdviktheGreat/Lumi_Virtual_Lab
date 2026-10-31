import { sameTitle, tidy } from "./scientists";
import type { LabChoice, LibraryScientist } from "./types";

// The scientist who reviews one that works alone, and who is therefore not one to choose to work alone
export const CRITIC_TITLE = "Scientific Critic";
// Who leads a conversation that has not begun, which is the lead of a new one unless it is told otherwise
export const DEFAULT_LEAD_TITLE = "Principal Investigator";

// What the server takes of /lab, which are far more than are of use
export const MOST_QUESTIONS = 10;
export const MOST_QUESTION_CHARS = 2000;

export type LabMode = LabChoice["mode"];

// Who is chosen, as a message that was given with /lab says it, which is read with care since it was written by a server
// that may be another one than this page was made for
export function labChoiceOf(data: unknown): LabChoice | null {
  if (typeof data !== "object" || data === null) return null;
  const { mode, members, rounds, questions } = data as Record<string, unknown>;
  if (mode !== "team" && mode !== "individual") return null;
  const named = Array.isArray(members) ? members.filter((member): member is string => typeof member === "string") : [];
  if (named.length === 0 || named.length !== (members as unknown[]).length) return null;
  if (typeof rounds !== "number" || !Number.isInteger(rounds) || rounds < 0) return null;

  return {
    mode,
    members: named,
    rounds,
    questions: Array.isArray(questions) ? questions.filter((question): question is string => typeof question === "string") : [],
  };
}

function roundsOf(count: number): string {
  return `${count} ${count === 1 ? "round" : "rounds"}`;
}

// Who works on a message and for how long, in a few words, for the message to show
export function describeChoice(choice: LabChoice): string {
  const who = choice.mode === "individual" ? `${choice.members[0]}, with the Critic reviewing` : choice.members.join(", ");

  return `${who} · ${roundsOf(choice.rounds)}`;
}

// The scientists to choose from: those of the library, but for the lead, who leads, and, for one who works alone, the
// Critic, who reviews
export function choosable(library: readonly LibraryScientist[], lead: string, mode: LabMode): LibraryScientist[] {
  return library.filter((scientist) => !sameTitle(scientist.title, lead) && (mode === "team" || !sameTitle(scientist.title, CRITIC_TITLE)));
}

// Those chosen who are not on the conversation's team, and who therefore join it
export function joining(members: readonly string[], team: readonly string[]): string[] {
  return members.filter((member) => !team.some((on) => sameTitle(on, member)));
}

// What is asked in the panel, as it is written there
export interface LabDraft {
  mode: LabMode;
  agenda: string;
  members: string[];
  rounds: string;
  // One to a line
  questions: string;
}

export function questionsOf(text: string): string[] {
  return text
    .split("\n")
    .map(tidy)
    .filter((line) => line !== "");
}

export interface LabProblems {
  agenda?: string;
  members?: string;
  rounds?: string;
  questions?: string;
}

// What the draft asks for, with what is wrong with it. A choice is given where nothing is.
export function checkLab(draft: LabDraft, ceiling: number): { choice: LabChoice | null; problems: LabProblems } {
  const problems: LabProblems = {};
  const agenda = draft.agenda.trim();
  if (agenda === "") problems.agenda = "Say what they are to work on.";

  if (draft.mode === "individual") {
    if (draft.members.length !== 1) problems.members = "Choose the one scientist who is to work on it.";
  } else if (draft.members.length === 0) {
    problems.members = "Choose at least one scientist.";
  }

  const rounds = draft.rounds.trim();
  const count = /^\d+$/.test(rounds) ? Number(rounds) : null;
  if (count === null || count > ceiling) {
    problems.rounds = `Rounds are a whole number from 0 to ${ceiling}, which is the most the lead may ask of a session.`;
  }

  const questions = questionsOf(draft.questions);
  if (questions.length > MOST_QUESTIONS) problems.questions = `Ask at most ${MOST_QUESTIONS} questions.`;
  else if (questions.some((question) => question.length > MOST_QUESTION_CHARS)) {
    problems.questions = `A question is at most ${MOST_QUESTION_CHARS} characters.`;
  }

  if (Object.keys(problems).length > 0 || count === null) return { choice: null, problems };

  return { choice: { mode: draft.mode, members: draft.members, rounds: count, questions }, problems };
}

// The draft with another mode: those chosen are kept, but for the Critic and all but one where a scientist works alone
export function withMode(draft: LabDraft, mode: LabMode): LabDraft {
  if (mode === draft.mode) return draft;
  const members = mode === "individual" ? draft.members.filter((member) => !sameTitle(member, CRITIC_TITLE)).slice(0, 1) : draft.members;

  return { ...draft, mode, members };
}

// With a scientist chosen or not: where one works alone, choosing another is changing who it is
export function withMember(draft: LabDraft, title: string, chosen: boolean): LabDraft {
  const others = draft.members.filter((member) => !sameTitle(member, title));
  if (!chosen) return { ...draft, members: others };

  return { ...draft, members: draft.mode === "individual" ? [title] : [...others, title] };
}

// What is kept of one panel for the next: who, and how, but not what they were to work on
export interface Remembered {
  mode: LabMode;
  members: string[];
  rounds: number;
}

const KEY = "vl-lab";

export function remembered(): Remembered | null {
  try {
    const kept: unknown = JSON.parse(localStorage.getItem(KEY) ?? "null");
    const choice = labChoiceOf(kept);

    return choice === null ? null : { mode: choice.mode, members: choice.members, rounds: choice.rounds };
  } catch {
    return null;
  }
}

export function remember(choice: LabChoice): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ mode: choice.mode, members: choice.members, rounds: choice.rounds }));
  } catch {
    // A page that may not keep anything asks again
  }
}

// The panel as it opens: what is to be worked on, as it was written in the box, and who and how as they were chosen last
// where those are still to be had
export function initialDraft(
  agenda: string,
  kept: Remembered | null,
  library: readonly LibraryScientist[],
  lead: string,
  ceiling: number,
): LabDraft {
  const mode = kept?.mode ?? "team";
  const there = choosable(library, lead, mode);
  const members = (kept?.members ?? [])
    .map((member) => there.find((scientist) => sameTitle(scientist.title, member))?.title)
    .filter((title): title is string => title !== undefined);
  const rounds = Math.min(kept?.rounds ?? 1, ceiling);

  return { mode, agenda, members: mode === "individual" ? members.slice(0, 1) : members, rounds: String(rounds), questions: "" };
}
