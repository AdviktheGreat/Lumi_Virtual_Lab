import { cellOf, type Cell } from "./cell";
import { reduceLab, settleLab, writeLab, type LabSession } from "./lab";
import { asNumber, asRecord, asStrings, asText } from "./read";
import type { Attachment, ChatEvent, ChatState } from "./types";

export type { Cell };

// How a turn stands: it begins with the researcher's message and ends with the lead's answer, the researcher
// stopping it, or an error
export type Outcome = "running" | "answered" | "stopped" | "failed";

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
  // What the team did, which is what a call to bring in the team, or to ask one scientist, is
  lab: LabSession | null;
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

export type ConnectionState = "connecting" | "signing_in" | "ready" | "failed";

// A server whose tools the lead is to be given, as it is being connected to
export interface Connection {
  // Its name, which is what the settings call it, and what to call it
  server: string;
  title: string;
  state: ConnectionState;
  // The page to sign in at, when it waits for the researcher to
  url: string | null;
  // How many tools it gave, once it has
  tools: number | null;
  // Why it could not be connected to
  text: string;
}

// "withdrawn" is a request that no one answered before the turn ended
export type ApprovalState = "waiting" | "approved" | "declined" | "withdrawn";
export type QuestionState = "waiting" | "answered" | "declined" | "withdrawn";

// A call to a tool that waits for the researcher to allow it
export interface Approval {
  // What the page answers it by
  request: string;
  state: ApprovalState;
  tool: string;
  server: string;
  title: string;
  description: string;
  // What it is to be called with, as text
  arguments: string;
}

// What a server asks while one of its tools runs
export interface Question {
  request: string;
  state: QuestionState;
  server: string;
  title: string;
  text: string;
  // The form's fields, each as the JSON schema the server gave, and which of them must be filled in
  fields: Record<string, Record<string, unknown>>;
  required: string[];
  // The page it asks the researcher to go to, for one that is answered there
  url: string | null;
}

// What the lead did in a turn, in the order it did it
export type Step =
  | { kind: "say"; key: string; text: string }
  | { kind: "call"; key: string; call: Call }
  | { kind: "resources"; key: string; resources: Resources }
  | { kind: "note"; key: string; text: string; to: "lead" | "lab" | null; read: boolean }
  | { kind: "connection"; key: string; connection: Connection }
  | { kind: "approval"; key: string; approval: Approval }
  | { kind: "question"; key: string; question: Question };

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

function attachmentsOf(event: ChatEvent): Attachment[] {
  const given = event.data.attachments;

  return Array.isArray(given) ? (given as Attachment[]) : [];
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
      lab: null,
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

const CONNECTION_STATES: readonly string[] = ["connecting", "signing_in", "ready", "failed"];
const APPROVAL_STATES: readonly string[] = ["waiting", "approved", "declined", "withdrawn"];
const QUESTION_STATES: readonly string[] = ["waiting", "answered", "declined", "withdrawn"];

function connectionOf(event: ChatEvent): Connection {
  const state = asText(event.data.state);
  const url = asText(event.data.url);

  return {
    server: asText(event.data.server),
    title: asText(event.data.title, asText(event.data.server)),
    state: (CONNECTION_STATES.includes(state) ? state : "connecting") as ConnectionState,
    url: url === "" ? null : url,
    tools: typeof event.data.tools === "number" ? event.data.tools : null,
    text: event.text,
  };
}

function approvalOf(event: ChatEvent): Approval {
  const state = asText(event.data.state);
  const server = asText(event.data.server);

  return {
    request: asText(event.data.request),
    state: (APPROVAL_STATES.includes(state) ? state : "waiting") as ApprovalState,
    tool: asText(event.data.tool),
    server,
    title: asText(event.data.title, server),
    description: asText(event.data.description),
    arguments: asText(event.data.arguments),
  };
}

function questionOf(event: ChatEvent): Question {
  const state = asText(event.data.state);
  const server = asText(event.data.server);
  const fields: Record<string, Record<string, unknown>> = {};
  for (const [name, schema] of Object.entries(asRecord(event.data.fields))) fields[name] = asRecord(schema);
  const url = asText(event.data.url);

  return {
    request: asText(event.data.request),
    state: (QUESTION_STATES.includes(state) ? state : "waiting") as QuestionState,
    server,
    title: asText(event.data.title, server),
    text: event.text,
    fields,
    required: asStrings(event.data.required),
    url: url === "" ? null : url,
  };
}

// Whether the step is the approval or the question that a request is of
function hasRequest(step: Step, kind: "approval" | "question", request: string): boolean {
  if (step.kind !== kind) return false;

  return (step.kind === "approval" ? step.approval.request : step.question.request) === request;
}

// A turn that is over has no call still running: one that was answered was left unfinished by an event that was lost,
// and one that was stopped or failed was cut short. Nor does it wait for the researcher, or for a server, and what it
// waited for was never answered or connected.
function settle(turn: Turn, to: CallStatus): Turn {
  return {
    ...turn,
    steps: turn.steps.map((step): Step => {
      switch (step.kind) {
        case "call": {
          const lab = step.call.lab === null ? null : settleLab(step.call.lab);

          return { ...step, call: { ...step.call, status: step.call.status === "running" ? to : step.call.status, lab } };
        }
        case "approval":
          return step.approval.state === "waiting" ? { ...step, approval: { ...step.approval, state: "withdrawn" } } : step;
        case "question":
          return step.question.state === "waiting" ? { ...step, question: { ...step.question, state: "withdrawn" } } : step;
        case "connection": {
          const open = step.connection.state === "connecting" || step.connection.state === "signing_in";

          return open
            ? { ...step, connection: { ...step.connection, state: "failed", text: "Not connected: the turn ended before it was." } }
            : step;
        }
        default:
          return step;
      }
    }),
  };
}

// How many things wait for the researcher in a turn that is still going on: calls to allow, questions to answer, and
// sign-ins to make
export function waitingOnYou(turns: Turn[]): number {
  return turns
    .filter((turn) => turn.outcome === "running")
    .reduce(
      (count, turn) =>
        count +
        turn.steps.filter(
          (step) =>
            (step.kind === "approval" && step.approval.state === "waiting") ||
            (step.kind === "question" && step.question.state === "waiting") ||
            (step.kind === "connection" && step.connection.state === "signing_in"),
        ).length,
      0,
    );
}

// Between what the lead has done and what it does next, it is thinking: it has nothing it is writing to show, and no
// call is running, which would say what is being waited for
export function isThinking(turn: Turn, working: boolean): boolean {
  return (
    turn.outcome === "running" &&
    working &&
    turn.writing === "" &&
    !turn.steps.some(
      (step) =>
        (step.kind === "call" && step.call.status === "running") ||
        // A server being connected to is what is waited for, and is shown as it is
        (step.kind === "connection" && (step.connection.state === "connecting" || step.connection.state === "signing_in")),
    )
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
  // What happens to a call that is there, since there is nothing to show what happens to one that is not
  const inCall = (id: string, change: (call: Call) => Call): Transcript => {
    const turn = next.turns.find((candidate) => candidate.number === event.turn);

    return turn !== undefined && hasCall(turn, id) ? inTurn((found) => changeCall(found, id, change)) : next;
  };

  switch (event.kind) {
    case "user":
      return inTurn((turn) => ({ ...turn, user: { text: event.text, attachments: attachmentsOf(event) } }));
    case "withdrawn": {
      // The turn is begun again by the event that follows, so what it had is not kept
      const number = typeof event.data.turn === "number" ? event.data.turn : event.turn;

      return { ...next, turns: next.turns.filter((turn) => turn.number !== number) };
    }
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
      // A scientist writing in a team session is not the lead's reply, but what the session is shown with
      if (event.data.meeting !== undefined && event.data.meeting !== null) {
        return inCall(asText(event.data.call), (call) => ({ ...call, lab: call.lab === null ? null : writeLab(call.lab, event) }));
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
          lab: null,
        });

        return { ...turn, steps: [...turn.steps, { kind: "call", key: `call-${id || event.id}`, call }] };
      });
    }
    case "cell": {
      const id = asText(event.data.call);
      const cell = cellOf(event.data);

      return inTurn((turn) => (hasCall(turn, id) ? changeCall(turn, id, (call) => ({ ...call, cells: [...call.cells, cell] })) : turn));
    }
    case "lab":
      // A session whose call was not told of is not shown, for want of a call to show it with
      return inCall(asText(event.data.call), (call) => ({ ...call, lab: reduceLab(call.lab, event) }));
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
    case "connection":
      return inTurn((turn) => {
        const server = asText(event.data.server);
        const at = turn.steps.findLastIndex((step) => step.kind === "connection" && step.connection.server === server);
        const found = at === -1 ? null : turn.steps[at];
        // A server that is connected to again, as a retry is, is shown as a new connection, and what it says after is
        // of that one
        if (found === null || found.kind !== "connection" || event.data.state === "connecting") {
          const step: Step = { kind: "connection", key: `connection-${event.id}`, connection: connectionOf(event) };

          return { ...turn, steps: [...turn.steps, step] };
        }

        return {
          ...turn,
          steps: turn.steps.map((step, place) =>
            place === at && step.kind === "connection" ? { ...step, connection: connectionOf(event) } : step,
          ),
        };
      });
    case "approval":
      return inTurn((turn) => {
        const request = asText(event.data.request);
        if (!turn.steps.some((step) => hasRequest(step, "approval", request))) {
          // What it asked is said when it asked, so an end with nothing to end has nothing to show
          if (event.data.state !== "waiting") return turn;
          const step: Step = { kind: "approval", key: `approval-${request || event.id}`, approval: approvalOf(event) };

          return { ...turn, steps: [...turn.steps, step] };
        }
        const state = approvalOf(event).state;

        return {
          ...turn,
          steps: turn.steps.map((step) =>
            hasRequest(step, "approval", request) && step.kind === "approval" ? { ...step, approval: { ...step.approval, state } } : step,
          ),
        };
      });
    case "question":
      return inTurn((turn) => {
        const request = asText(event.data.request);
        if (!turn.steps.some((step) => hasRequest(step, "question", request))) {
          // A question that was declined without being asked is told of in one event, with what it asked. Anything
          // else that ends has said what it asked already, so one that has nothing to end is not shown.
          if (event.data.state !== "waiting" && event.text === "") return turn;
          const step: Step = { kind: "question", key: `question-${request || event.id}`, question: questionOf(event) };

          return { ...turn, steps: [...turn.steps, step] };
        }
        const state = questionOf(event).state;

        return {
          ...turn,
          steps: turn.steps.map((step) =>
            hasRequest(step, "question", request) && step.kind === "question" ? { ...step, question: { ...step.question, state } } : step,
          ),
        };
      });
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
