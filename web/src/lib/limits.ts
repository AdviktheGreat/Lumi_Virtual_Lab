import { parseLimit } from "./settings";
import type { ChatLimits, LimitsChange } from "./types";

// What a conversation may spend and what the lead may ask of the team, as it stands
export interface CurrentLimits {
  max_cost: number | null;
  max_delegations: number;
  max_rounds: number;
}

// What the panel shows of them, which is what is typed where it is typed
export interface LimitsDraft {
  cost: string;
  sessions: string;
  rounds: string;
}

export interface LimitProblems {
  cost?: string;
  sessions?: string;
  rounds?: string;
}

// An amount in dollars as it is typed back: no more digits than a price has, and no point where it is whole
export function formatAmount(amount: number): string {
  return Number.isInteger(amount) ? String(amount) : String(Number(amount.toFixed(4)));
}

export function limitsDraftOf(current: CurrentLimits): LimitsDraft {
  return {
    cost: current.max_cost === null ? "" : formatAmount(current.max_cost),
    sessions: String(current.max_delegations),
    rounds: String(current.max_rounds),
  };
}

// A whole number from none to the most, as it is typed, or undefined when what was typed is not one
export function parseCount(typed: string, ceiling: number): number | undefined {
  const text = typed.trim();
  if (!/^\d+$/.test(text)) return undefined;
  const count = Number(text);

  return count <= ceiling ? count : undefined;
}

export interface Checked {
  // What differs from what the conversation has, as the server is asked for it
  changes: LimitsChange;
  // What is wrong with what was typed, so that nothing is sent
  problems: LimitProblems;
}

// What the panel says, as a change to the limits it began from: nothing is said of what was left as it was
export function checkLimits(draft: LimitsDraft, current: CurrentLimits, limits: ChatLimits): Checked {
  const changes: LimitsChange = {};
  const problems: LimitProblems = {};

  const cost = parseLimit(draft.cost);
  if (cost === undefined) problems.cost = "A limit is an amount in dollars, such as 5 or 12.50. Leave it empty for none.";
  else if (cost !== current.max_cost) changes.max_cost = cost;

  const sessions = parseCount(draft.sessions, limits.max_delegations.ceiling);
  if (sessions === undefined) problems.sessions = `A whole number from 0 to ${limits.max_delegations.ceiling}.`;
  else if (sessions !== current.max_delegations) changes.max_delegations = sessions;

  const rounds = parseCount(draft.rounds, limits.max_rounds.ceiling);
  if (rounds === undefined) problems.rounds = `A whole number from 0 to ${limits.max_rounds.ceiling}.`;
  else if (rounds !== current.max_rounds) changes.max_rounds = rounds;

  return { changes, problems };
}

// The limit typed with some more allowed, from what is typed, or from what is spent where nothing is: more than the
// conversation has used is what a limit is raised for
export function raisedBy(typed: string, more: number, spent: number | null): string {
  const limit = parseLimit(typed);
  const base = typeof limit === "number" ? limit : Math.max(spent ?? 0, 0);

  return formatAmount(Math.round((base + more) * 100) / 100);
}

// Whether a limit is below what is spent already, which stops the lead at its next request
export function belowSpent(typed: string, spent: number | null): boolean {
  const limit = parseLimit(typed);

  return typeof limit === "number" && spent !== null && limit < spent;
}
