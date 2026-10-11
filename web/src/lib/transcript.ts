import type { Attachment, ChatEvent, ChatState } from "./types";

// How a turn stands: it begins with the researcher's message and ends with the lead's answer, the researcher
// stopping it, or an error
export type Outcome = "running" | "answered" | "stopped" | "failed";

// Code that ran in the session, as the server tells of it
export interface Cell {
  language: string;
  code: string;
  // "ok", "error", "timeout", or "lost"; anything else the server may one day say is shown as it is
  status: string;
  output: string;
  error: string | null;
  duration: number;
  // Figures, and every file that appeared while it ran, relative to the conversation's files
  plots: string[];
  producedFiles: string[];
  // Bytes dropped from the middle of the output to bound it
  outputDropped: number;
  value: unknown;
}

// "interrupted" is a call that the turn ended before it was answered
export type CallStatus = "running" | "done" | "interrupted";

// A tool the lead called
export interface Call {
  id: string;
  name: string;
  // As written, which is JSON where the model wrote it well
  arguments: string;
  status: CallStatus;
  output: string | null;
  // The code it ran in the session, which is what a call to run code is
  cells: Cell[];
}

export interface Resources {
  // How they were chosen: "all", "retrieve", "none", or "given"
  mode: string;
  // How many of each kind there are, and the names of those the lead was told of
  available: Record<string, number>;
  selected: Record<string, string[]>;
  // What the lead asked for them for, when it did
  task: string | null;
}

// What the lead did in a turn, in the order it did it
export type Step =
  | { kind: "say"; key: string; text: string }
  | { kind: "call"; key: string; call: Call }
  | { kind: "resources"; key: string; resources: Resources }
  | { kind: "note"; key: string; text: string; to: "lead" | "lab" | null; read: boolean };

export interface Turn {
  number: number;
  user: { text: string; attachments: Attachment[] } | null;
  steps: Step[];
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
  return { number, user: null, steps: [], writing: "", outcome: "running", text: "", errorType: null };
}

function withTurn(transcript: Transcript, number: number, change: (turn: Turn) => Turn): Turn[] {
  const index = transcript.turns.findIndex((turn) => turn.number === number);
  if (index === -1) {
    return [...transcript.turns, change(blankTurn(number))].sort((a, b) => a.number - b.number);
  }

  return transcript.turns.map((turn, at) => (at === index ? change(turn) : turn));
}

// What an event says, which a server of another version may say otherwise: each is the value if it is of the kind
// asked for, and what is given instead if not

function asText(value: unknown, otherwise = ""): string {
  return typeof value === "string" ? value : otherwise;
}

function asNumber(value: unknown, otherwise = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : otherwise;
}

function asStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function attachmentsOf(event: ChatEvent): Attachment[] {
  const given = event.data.attachments;

  return Array.isArray(given) ? (given as Attachment[]) : [];
}

function cellOf(data: Record<string, unknown>): Cell {
  return {
    language: asText(data.language, "python"),
    code: asText(data.code),
    status: asText(data.status, "ok"),
    output: asText(data.output),
    error: typeof data.error === "string" && data.error !== "" ? data.error : null,
    duration: asNumber(data.duration),
    plots: asStrings(data.plots),
    producedFiles: asStrings(data.produced_files),
    outputDropped: asNumber(data.output_dropped),
    value: data.value ?? null,
  };
}

function resourcesOf(data: Record<string, unknown>): Resources {
  const available: Record<string, number> = {};
  for (const [kind, count] of Object.entries(asRecord(data.available))) available[kind] = asNumber(count);
  const selected: Record<string, string[]> = {};
  for (const [kind, names] of Object.entries(asRecord(data.selected))) selected[kind] = asStrings(names);
  const task = asText(asRecord(data.retrieval).task);

  return { mode: asText(data.mode, "all"), available, selected, task: task === "" ? null : task };
}

function callsOf(data: Record<string, unknown>): Call[] {
  if (!Array.isArray(data.calls)) return [];

  return data.calls.map((given, at) => {
    const call = asRecord(given);

    return {
      // A call with no id of its own cannot be told of again, so it is named by where it came
      id: asText(call.id, `call-${at}`),
      name: asText(call.name),
      arguments: asText(call.arguments),
      status: "running",
      output: null,
      cells: [],
    };
  });
}

// What a step is once change has been made to the call it names, which is that call's alone
function changeCall(turn: Turn, id: string, change: (call: Call) => Call): Turn {
  return {
    ...turn,
    steps: turn.steps.map((step) =>
      step.kind === "call" && step.call.id === id ? { ...step, call: change(step.call) } : step,
    ),
  };
}

function hasCall(turn: Turn, id: string): boolean {
  return turn.steps.some((step) => step.kind === "call" && step.call.id === id);
}

// A turn that is over has no call still running: one that was answered was left unfinished by an event that was lost,
// and one that was stopped or failed was cut short
function settle(turn: Turn, to: CallStatus): Turn {
  return {
    ...turn,
    steps: turn.steps.map((step) =>
      step.kind === "call" && step.call.status === "running" ? { ...step, call: { ...step.call, status: to } } : step,
    ),
  };
}

// Between what the lead has done and what it does next, it is thinking: it has nothing it is writing to show, and no
// call is running, which would say what is being waited for
export function isThinking(turn: Turn, working: boolean): boolean {
  return (
    turn.outcome === "running" &&
    working &&
    turn.writing === "" &&
    !turn.steps.some((step) => step.kind === "call" && step.call.status === "running")
  );
}

// What the transcript is once the event has happened. An event it has read already changes nothing, so that a
// stream that starts again from an earlier event is harmless.
export function reduce(transcript: Transcript, event: ChatEvent): Transcript {
  if (event.id <= transcript.lastId) {
    return transcript;
  }
  const next = { ...transcript, lastId: event.id };
  const inTurn = (change: (turn: Turn) => Turn): Transcript =>
    // What happens outside a turn is not part of one
    event.turn < 1 ? next : { ...next, turns: withTurn(next, event.turn, change) };

  switch (event.kind) {
    case "user":
      return inTurn((turn) => ({ ...turn, user: { text: event.text, attachments: attachmentsOf(event) } }));
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
    case "tool_calls":
      return inTurn((turn) => {
        const said: Step[] = event.text.trim() === "" ? [] : [{ kind: "say", key: `say-${event.id}`, text: event.text }];
        const calls = callsOf(event.data).filter((call) => !hasCall(turn, call.id));

        return {
          ...turn,
          // What was being written is now said, beside the calls
          writing: "",
          steps: [...turn.steps, ...said, ...calls.map((call): Step => ({ kind: "call", key: `call-${call.id}`, call }))],
        };
      });
    case "tool_output": {
      const id = asText(event.data.call);

      return inTurn((turn) => {
        const answered = (call: Call): Call => ({ ...call, status: "done", output: event.text });
        if (hasCall(turn, id)) return changeCall(turn, id, answered);

        // The call it answers was not told of, so it is shown as the answer alone
        const call = answered({
          id,
          name: asText(event.data.name),
          arguments: "",
          status: "running",
          output: null,
          cells: [],
        });

        return { ...turn, steps: [...turn.steps, { kind: "call", key: `call-${id || event.id}`, call }] };
      });
    }
    case "cell": {
      const id = asText(event.data.call);
      const cell = cellOf(event.data);

      return inTurn((turn) => (hasCall(turn, id) ? changeCall(turn, id, (call) => ({ ...call, cells: [...call.cells, cell] })) : turn));
    }
    case "resources":
      return inTurn((turn) => ({
        ...turn,
        steps: [...turn.steps, { kind: "resources", key: `resources-${event.id}`, resources: resourcesOf(event.data) }],
      }));
    case "note":
      return inTurn((turn) => ({
        ...turn,
        steps: [
          ...turn.steps,
          {
            kind: "note",
            key: `note-${event.id}`,
            text: event.text,
            to: event.data.to === "lead" || event.data.to === "lab" ? event.data.to : null,
            read: event.data.read === true,
          },
        ],
      }));
    case "answer":
    case "stopped":
    case "failed": {
      const outcome = event.kind === "answer" ? "answered" : event.kind;
      const errorType = event.kind === "failed" && typeof event.data.type === "string" ? event.data.type : null;

      return {
        ...next,
        turns: withTurn(next, event.turn, (turn) => ({
          ...settle(turn, event.kind === "answer" ? "done" : "interrupted"),
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
