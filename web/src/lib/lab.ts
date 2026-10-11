import { cellOf, type Cell } from "./cell";
import { asRecord, asStrings, asText } from "./read";
import type { ChatEvent } from "./types";

// A tool a scientist in a team session called
export interface LabCall {
  id: string;
  name: string;
  // As written, which is JSON where the model wrote it well
  arguments: string;
}

// What a scientist did in a turn, in the order they did it
export type LabStep =
  // What they said, which ends the turn
  | { kind: "reply"; key: string; text: string }
  // Tools they called, with what came back where it was not code that ran, which a run says for itself
  | { kind: "tools"; key: string; said: string; calls: LabCall[]; output: string | null }
  // Code they wrote in their reply, which runs in the session once it is written; the run is there once it has
  | { kind: "code"; key: string; said: string; code: string; language: string; cell: Cell | null }
  // Code that ran in the session because they called a tool to run it
  | { kind: "cell"; key: string; cell: Cell };

export interface LabTurn {
  key: string;
  speaker: string;
  // From 1, where the last is one more than the rounds there were to be, which is the lead's summing up
  round: number | null;
  steps: LabStep[];
}

// "interrupted" is a session that the turn ended before it did, or that the researcher stopped
export type LabStatus = "running" | "finished" | "failed" | "interrupted";

// The kind of error that a session the researcher stopped fails with, which is the name of what the server raises
const STOPPED_BY_RESEARCHER = "ChatStopped";

// A team session the lead started with convene_team or consult
export interface LabSession {
  // The name it is saved under
  meeting: string;
  // "team" for a discussion the lead leads, "individual" for one scientist reviewed by the critic
  type: string | null;
  agenda: string;
  questions: string[];
  rounds: number | null;
  // Who is in it, by title
  team: string[];
  turns: LabTurn[];
  // What a scientist is writing now, which the reply that is final replaces
  writing: { speaker: string | null; text: string } | null;
  status: LabStatus;
  // What the team found, once it has
  summary: string;
  // What stopped it, if it failed
  error: string | null;
}

function blankSession(meeting: string): LabSession {
  return {
    meeting,
    type: null,
    agenda: "",
    questions: [],
    rounds: null,
    team: [],
    turns: [],
    writing: null,
    status: "running",
    summary: "",
    error: null,
  };
}

function callsOf(details: Record<string, unknown>): LabCall[] {
  if (!Array.isArray(details.calls)) return [];

  return details.calls.map((given, at) => {
    const call = asRecord(given);

    return {
      // A call with no id of its own cannot be told of again, so it is named by where it came
      id: asText(call.id, `call-${at}`),
      name: asText(call.name),
      arguments: asText(call.arguments),
    };
  });
}

function roundOf(event: ChatEvent): number | null {
  return typeof event.data.round === "number" && Number.isFinite(event.data.round) ? event.data.round : null;
}

// What becomes of the turn that is going on, which an event of the session that does not say whose turn it is belongs to.
// There is none for a session that was not told of from its start, so one is made of what the event says.
function inLastTurn(session: LabSession, event: ChatEvent, change: (turn: LabTurn) => LabTurn): LabSession {
  const last = session.turns.at(-1);
  if (last === undefined) {
    const made: LabTurn = { key: `turn-${event.id}`, speaker: event.speaker ?? "", round: roundOf(event), steps: [] };

    return { ...session, turns: [change(made)] };
  }

  return { ...session, turns: [...session.turns.slice(0, -1), change(last)] };
}

function addStep(session: LabSession, event: ChatEvent, step: LabStep): LabSession {
  return inLastTurn(session, event, (turn) => ({ ...turn, steps: [...turn.steps, step] }));
}

// Whether code ran for the tools that were called, which is so when a run comes right after them. Their output is the
// run's then, so that it is not shown twice.
function ranFor(steps: LabStep[], tools: number): boolean {
  return steps[tools + 1]?.kind === "cell";
}

function withOutput(session: LabSession, event: ChatEvent): LabSession {
  return inLastTurn(session, event, (turn) => {
    const at = turn.steps.findLastIndex((step) => step.kind === "tools" && step.output === null);
    if (at === -1 || ranFor(turn.steps, at)) return turn;

    return {
      ...turn,
      steps: turn.steps.map((step, place) => (place === at && step.kind === "tools" ? { ...step, output: event.text } : step)),
    };
  });
}

function withCell(session: LabSession, event: ChatEvent): LabSession {
  const cell = cellOf(asRecord(asRecord(event.data).details));

  return inLastTurn(session, event, (turn) => {
    const last = turn.steps.at(-1);
    // Code written in a reply has not said how it ran until now
    if (last?.kind === "code" && last.cell === null) {
      return { ...turn, steps: [...turn.steps.slice(0, -1), { ...last, cell }] };
    }

    return { ...turn, steps: [...turn.steps, { kind: "cell", key: `cell-${event.id}`, cell }] };
  });
}

// What the session is once something has happened in it, which the event of a "lab" kind tells of. An event of a kind
// it does not know, which a server of another version may send, changes nothing.
export function reduceLab(given: LabSession | null, event: ChatEvent): LabSession {
  const session = given ?? blankSession(asText(event.data.meeting));
  const details = asRecord(event.data.details);

  switch (asText(event.data.event)) {
    case "started":
      return {
        ...session,
        type: asText(details.meeting_type) || null,
        agenda: asText(details.agenda),
        questions: asStrings(details.agenda_questions),
        rounds: typeof details.num_rounds === "number" ? details.num_rounds : null,
        team: Array.isArray(details.team) ? details.team.map((member) => asText(asRecord(member).title)).filter(Boolean) : [],
      };
    case "turn":
      return {
        ...session,
        writing: null,
        turns: [
          ...session.turns,
          {
            key: `turn-${event.id}`,
            speaker: event.speaker ?? asText(details.name),
            round: roundOf(event),
            steps: [],
          },
        ],
      };
    case "message":
      switch (asText(details.kind)) {
        case "response":
          return { ...addStep(session, event, { kind: "reply", key: `reply-${event.id}`, text: event.text }), writing: null };
        case "tool_output":
          return withOutput(session, event);
        // A note is the researcher's, which the conversation shows where they wrote it, and the rest of what is said in
        // the session, such as what code printed, is shown as the run that it is
        default:
          return session;
      }
    case "tool_calls":
      return addStep(session, event, {
        kind: "tools",
        key: `tools-${event.id}`,
        said: event.text,
        calls: callsOf(details),
        output: null,
      });
    case "code":
      return addStep(session, event, {
        kind: "code",
        key: `code-${event.id}`,
        said: event.text,
        code: asText(details.code),
        language: asText(details.language, "python"),
        cell: null,
      });
    case "cell":
      return withCell(session, event);
    case "finished":
      return { ...session, status: "finished", writing: null, summary: event.text };
    case "failed":
      // A session the researcher stopped is told of as one that failed, with the kind of error that stopped it, but it
      // did not go wrong: it was cut short
      if (asText(details.type) === STOPPED_BY_RESEARCHER) return { ...session, status: "interrupted", writing: null };

      return { ...session, status: "failed", writing: null, error: event.text };
    default:
      return session;
  }
}

// What the session is once a scientist has written some of a reply, which is all of it so far
export function writeLab(session: LabSession, event: ChatEvent): LabSession {
  if (session.status !== "running") return session;

  return { ...session, writing: { speaker: event.speaker, text: event.text } };
}

// A session that was not finished when the turn ended was cut short
export function settleLab(session: LabSession): LabSession {
  return session.status === "running" ? { ...session, status: "interrupted", writing: null } : session;
}

// Whose turn it is in a session that is going on
export function speaking(session: LabSession): { speaker: string; round: number | null } | null {
  const last = session.turns.at(-1);

  return session.status === "running" && last !== undefined ? { speaker: last.speaker, round: last.round } : null;
}

// What a round is called: the last is the lead's summing up in a team discussion, and the scientist's answer, after the
// critic's review, in the other
export function roundName(round: number | null, session: Pick<LabSession, "rounds" | "type">): string | null {
  if (round === null) return null;
  if (session.rounds !== null && round === session.rounds + 1) return session.type === "individual" ? "Final answer" : "Summary";

  return `Round ${round}`;
}

// The tools a scientist called in a turn that are worth listing. A call to run code is shown by the run that it made,
// which is there once the code has run, so that the code is not shown twice.
export function listedCalls(turn: LabTurn, at: number): LabCall[] {
  const step = turn.steps[at];
  if (step?.kind !== "tools") return [];
  const shownByRun = ranFor(turn.steps, at);

  return step.calls.filter((call) => !(call.name === "run_code" && shownByRun));
}

export interface Round {
  round: number | null;
  turns: LabTurn[];
}

// The turns of a session by the round they were in, which is what a discussion is read in
export function inRounds(turns: LabTurn[]): Round[] {
  const rounds: Round[] = [];
  for (const turn of turns) {
    const last = rounds.at(-1);
    if (last !== undefined && last.round === turn.round) {
      last.turns.push(turn);
    } else {
      rounds.push({ round: turn.round, turns: [turn] });
    }
  }

  return rounds;
}

// How many colours a scientist may be given to be told apart by
export const SPEAKER_TONES = 6;

// A colour for a scientist, from 0 to one less than SPEAKER_TONES, which is the same for the same name every time
export function speakerTone(name: string): number {
  let hash = 0;
  for (const letter of name.toLowerCase()) hash = (hash * 31 + (letter.codePointAt(0) ?? 0)) % 1_000_003;

  return hash % SPEAKER_TONES;
}

// The letters a scientist is marked by: the first of up to two words, which are the first and last where there are more
export function initialsOf(name: string): string {
  const words = name.split(/[\s_-]+/).filter(Boolean);
  if (words.length === 0) return "?";
  const first = words[0];
  const last = words.length > 1 ? words[words.length - 1] : "";

  return `${[...first][0] ?? ""}${[...last][0] ?? ""}`.toUpperCase();
}
