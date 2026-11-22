import { sameTitle, tidy } from "./scientists";
import type { LabChoice, LibraryScientist, PaperSeat } from "./types";

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

// One who can be chosen to work on a message: a scientist of the library, or the one who speaks for a PaperAgent's paper
export interface Candidate {
  title: string;
  // What they know, in a few words
  about: string;
  kind: "builtin" | "yours" | "paper";
}

// Who can be chosen: those who speak for the papers of the conversation's PaperAgents, first, since a conversation that has
// them was begun for them, and then the scientists of the library, but for the lead, who leads, for one who works alone,
// the Critic, who reviews, and one who has the title of a seat, which names the seat on the conversation's team
export function choosable(library: readonly LibraryScientist[], lead: string, mode: LabMode, papers: readonly PaperSeat[] = []): Candidate[] {
  const seats: Candidate[] = [];
  for (const paper of papers) {
    if (sameTitle(paper.seat, lead) || seats.some((each) => sameTitle(each.title, paper.seat))) continue;
    seats.push({ title: paper.seat, about: `Speaks for the paper “${paper.title}”, from what was read of it and its tools`, kind: "paper" });
  }
  const scientists: Candidate[] = library
    .filter((scientist) => !sameTitle(scientist.title, lead) && (mode === "team" || !sameTitle(scientist.title, CRITIC_TITLE)))
    .filter((scientist) => !seats.some((seat) => sameTitle(seat.title, scientist.title)))
    .map((scientist) => ({ title: scientist.title, about: scientist.expertise, kind: scientist.builtin ? "builtin" : "yours" }));

  return [...seats, ...scientists];
}

// The seats that agents would have on the team of a conversation that is begun with them, as the list of the agents says
// them, where two that would have the same are told apart by the end of the id, as the server tells them apart
export function seatsOf(agents: readonly { id: string; title: string; seat?: string }[], lead: string): PaperSeat[] {
  const seats: PaperSeat[] = [];
  for (const { id, title, seat } of agents) {
    if (seat === undefined) continue;
    const taken = sameTitle(seat, lead) || seats.some((each) => sameTitle(each.seat, seat));
    seats.push({ id, title, seat: taken ? `${seat} (${id.slice(-6)})` : seat });
  }

  return seats;
}

// The choice with each who was chosen by the seat that an agent was to have named by the seat it has, which the server
// may have made unlike the title of another on the team
export function reseated(choice: LabChoice, planned: readonly PaperSeat[], seated: readonly PaperSeat[]): LabChoice {
  const members = choice.members.map((member) => {
    const agent = planned.find((each) => sameTitle(each.seat, member));
    const now = agent === undefined ? undefined : seated.find((each) => each.id === agent.id);

    return now === undefined ? member : now.seat;
  });

  return { ...choice, members };
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
// where those are still to be had, with those that are wanted chosen too, or in place of the one who works alone
export function initialDraft(
  agenda: string,
  kept: Remembered | null,
  library: readonly LibraryScientist[],
  lead: string,
  ceiling: number,
  papers: readonly PaperSeat[] = [],
  wanted: readonly string[] = [],
): LabDraft {
  const mode = kept?.mode ?? "team";
  const there = choosable(library, lead, mode, papers);
  const named = (titles: readonly string[]) =>
    titles.map((title) => there.find((each) => sameTitle(each.title, title))?.title).filter((title): title is string => title !== undefined);
  const before = named(kept?.members ?? []);
  const asked = named(wanted);
  const members =
    mode === "individual"
      ? (asked.length > 0 ? asked : before).slice(0, 1)
      : [...before, ...asked.filter((title) => !before.some((member) => sameTitle(member, title)))];
  const rounds = Math.min(kept?.rounds ?? 1, ceiling);

  return { mode, agenda, members, rounds: String(rounds), questions: "" };
}
