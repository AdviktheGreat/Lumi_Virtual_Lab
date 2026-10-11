import type { Turn } from "./transcript";
import type { ChatState } from "./types";

// What the researcher can do about the conversation in a state it is in
export interface Controls {
  // What is written goes as a message, or as a note for the lead, who is at work and reads it before its next step
  writes: "message" | "note";
  canNote: boolean;
  // The button that holds the turn or lets it go on. A turn that is being held, and one that is held, are let go the
  // same way.
  pause: "pause" | "resume";
  canPause: boolean;
  canStop: boolean;
  placeholder: string;
}

const ASK = "Ask the lead scientist…";
const NOTE = "Add a note, which the lead reads before its next step…";

const CONTROLS: Record<ChatState, Controls> = {
  idle: { writes: "message", canNote: false, pause: "pause", canPause: false, canStop: false, placeholder: ASK },
  running: { writes: "note", canNote: true, pause: "pause", canPause: true, canStop: true, placeholder: NOTE },
  pausing: { writes: "note", canNote: true, pause: "resume", canPause: true, canStop: true, placeholder: NOTE },
  paused: {
    writes: "note",
    canNote: true,
    pause: "resume",
    canPause: true,
    canStop: true,
    placeholder: "Add a note, then resume…",
  },
  stopping: { writes: "note", canNote: false, pause: "pause", canPause: false, canStop: false, placeholder: "Stopping…" },
};

// A state that a server of another version has may not be one that is known, which is treated as work going on, since
// stopping is then the way out
export function controlsFor(state: ChatState): Controls {
  return CONTROLS[state] ?? CONTROLS.running;
}

const HELD: Partial<Record<ChatState, string>> = {
  pausing: "Pausing once this step is done…",
  paused: "Paused. The lead goes on when you resume.",
  stopping: "Stopping once this step is done…",
};

// What to say of a turn that is not going on as it was, because it is being held or stopped, which it does not do at
// once: what is running is carried through first
export function holdNotice(state: ChatState): string | null {
  return HELD[state] ?? null;
}

// A note the researcher sent while a turn was going on
export interface SentNote {
  turn: number;
  text: string;
}

// The turn that is going on, which is the next one if the conversation has been told it is at work but not yet what
// the researcher said to begin it
export function currentTurn(turns: Turn[]): number {
  const last = turns.at(-1);
  if (last === undefined) return 1;

  return last.outcome === "running" ? last.number : last.number + 1;
}

// The notes that were sent and have not been read, or found to have come too late, which the conversation tells of
// once it has. Of the same words sent twice, the first is told of first. A turn that is over has told of every note it
// was sent, so nothing is waiting in it, and neither is anything while the lead is not at work.
export function unreadNotes(sent: SentNote[], turns: Turn[], working: boolean): SentNote[] {
  if (!working) return [];
  const told = new Map<string, number>();
  for (const turn of turns) {
    for (const step of turn.steps) {
      if (step.kind === "note") {
        const key = `${turn.number}\n${step.text}`;
        told.set(key, (told.get(key) ?? 0) + 1);
      }
    }
  }

  return sent.filter((note) => {
    const turn = turns.find((candidate) => candidate.number === note.turn);
    if (turn !== undefined && turn.outcome !== "running") return false;
    const key = `${note.turn}\n${note.text}`;
    const left = told.get(key) ?? 0;
    if (left > 0) {
      told.set(key, left - 1);

      return false;
    }

    return true;
  });
}
