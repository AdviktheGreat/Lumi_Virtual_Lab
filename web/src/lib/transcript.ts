import type { Attachment, ChatEvent, ChatState } from "./types";

// How a turn stands: it begins with the researcher's message and ends with the lead's answer, the researcher
// stopping it, or an error
export type Outcome = "running" | "answered" | "stopped" | "failed";

export interface Turn {
  number: number;
  user: { text: string; attachments: Attachment[] } | null;
  // What the lead is writing now, which the reply that is final replaces
  writing: string;
  outcome: Outcome;
  // The answer, or what stopped or failed the turn
  text: string;
  // What kind of error ended a turn that failed
  errorType: string | null;
}

export interface Transcript {
  title: string;
  state: ChatState;
  turns: Turn[];
  // The number of the last event read, which a repeat of an event is told from a new one by
  lastId: number;
  // What the conversation has spent so far, if it has said
  spent: number | null;
  maxCost: number | null;
}

export const emptyTranscript: Transcript = {
  title: "",
  state: "idle",
  turns: [],
  lastId: 0,
  spent: null,
  maxCost: null,
};

function blankTurn(number: number): Turn {
  return { number, user: null, writing: "", outcome: "running", text: "", errorType: null };
}

function withTurn(transcript: Transcript, number: number, change: (turn: Turn) => Turn): Turn[] {
  const index = transcript.turns.findIndex((turn) => turn.number === number);
  if (index === -1) {
    return [...transcript.turns, change(blankTurn(number))].sort((a, b) => a.number - b.number);
  }

  return transcript.turns.map((turn, at) => (at === index ? change(turn) : turn));
}

function attachmentsOf(event: ChatEvent): Attachment[] {
  const given = event.data.attachments;

  return Array.isArray(given) ? (given as Attachment[]) : [];
}

// What the transcript is once the event has happened. An event it has read already changes nothing, so that a
// stream that starts again from an earlier event is harmless.
export function reduce(transcript: Transcript, event: ChatEvent): Transcript {
  if (event.id <= transcript.lastId) {
    return transcript;
  }
  const next = { ...transcript, lastId: event.id };
  switch (event.kind) {
    case "user":
      return {
        ...next,
        turns: withTurn(next, event.turn, (turn) => ({
          ...turn,
          user: { text: event.text, attachments: attachmentsOf(event) },
        })),
      };
    case "title":
      return { ...next, title: event.text };
    case "status":
      return { ...next, state: event.data.state as ChatState };
    case "usage":
      return {
        ...next,
        spent: typeof event.data.cost === "number" ? event.data.cost : null,
        maxCost: typeof event.data.max_cost === "number" ? event.data.max_cost : null,
      };
    case "writing":
      // A scientist writing in a team session is not the lead's reply
      if (event.data.meeting !== undefined && event.data.meeting !== null) {
        return next;
      }

      return { ...next, turns: withTurn(next, event.turn, (turn) => ({ ...turn, writing: event.text })) };
    case "answer":
    case "stopped":
    case "failed": {
      const outcome = event.kind === "answer" ? "answered" : event.kind;
      const errorType = event.kind === "failed" && typeof event.data.type === "string" ? event.data.type : null;

      return {
        ...next,
        turns: withTurn(next, event.turn, (turn) => ({
          ...turn,
          writing: "",
          outcome,
          text: event.text,
          errorType,
        })),
      };
    }
    default:
      return next;
  }
}

export function replay(events: ChatEvent[], from: Transcript = emptyTranscript): Transcript {
  return events.reduce(reduce, from);
}
