import { EXPORT_CHOICES } from "./export";
import { controlsFor } from "./steering";
import type { ChatState } from "./types";

// Where a command can be given: in a conversation, or on the page where one is begun
export type Place = "home" | "chat";

// The commands that are given with a message, which say how the lead is to answer it
export const DIRECTIVE_NAMES = ["ask", "plan", "search", "code", "plot", "review", "lab"] as const;
export type DirectiveName = (typeof DIRECTIVE_NAMES)[number];

export type CommandName =
  | DirectiveName
  | "budget"
  | "model"
  | "files"
  | "export"
  | "rename"
  | "new"
  | "pause"
  | "resume"
  | "stop"
  | "help";

export function isDirective(name: string): name is DirectiveName {
  return (DIRECTIVE_NAMES as readonly string[]).includes(name);
}

export interface Choice {
  value: string;
  label: string;
  hint: string;
}

export interface Command {
  name: CommandName;
  summary: string;
  places: Place[];
  // What may follow the name: one of a few things, or words of the person's own. A command that takes something is not
  // run by choosing it from the menu, which has what it takes written after it first.
  // Words that may be left out are for a command that asks the rest in a panel of its own.
  takes?: { kind: "choice"; choices: Choice[] } | { kind: "text"; hint: string; optional?: boolean };
}

// The commands, in the order the menu lists them
export const COMMANDS: Command[] = [
  { name: "ask", summary: "Have the lead answer from what it knows, with no tools", places: ["home", "chat"], takes: { kind: "text", hint: "your question" } },
  { name: "plan", summary: "Have the lead plan the work, and not do it yet", places: ["home", "chat"], takes: { kind: "text", hint: "what to plan" } },
  {
    name: "search",
    summary: "Have the lead search the literature first, and cite what it finds",
    places: ["home", "chat"],
    takes: { kind: "text", hint: "what to look for" },
  },
  { name: "code", summary: "Have the lead do it by writing and running code", places: ["home", "chat"], takes: { kind: "text", hint: "what to work out" } },
  { name: "plot", summary: "Have the lead make a figure with code", places: ["home", "chat"], takes: { kind: "text", hint: "what to plot" } },
  { name: "review", summary: "Have the Scientific Critic review the lead's last answer", places: ["chat"] },
  {
    name: "lab",
    summary: "Choose who works on it: a team that discusses it, or one scientist the Critic reviews",
    places: ["home", "chat"],
    takes: { kind: "text", hint: "what they are to work on", optional: true },
  },
  { name: "budget", summary: "Set what the conversation may spend, and what the lead may ask of the team", places: ["home", "chat"] },
  { name: "model", summary: "Change the model the lead and the team answer with", places: ["home", "chat"] },
  { name: "rename", summary: "Give the conversation a new title", places: ["chat"], takes: { kind: "text", hint: "the new title" } },
  {
    name: "export",
    summary: "Save the conversation as a document",
    places: ["chat"],
    takes: {
      kind: "choice",
      choices: EXPORT_CHOICES.map(({ format, label, hint }) => ({ value: format, label, hint })),
    },
  },
  { name: "files", summary: "Show or hide the conversation's files", places: ["chat"] },
  { name: "new", summary: "Begin another conversation", places: ["chat"] },
  { name: "pause", summary: "Hold the lead after the step it is on", places: ["chat"] },
  { name: "resume", summary: "Let a held lead go on", places: ["chat"] },
  { name: "stop", summary: "Stop the lead after the step it is on", places: ["chat"] },
  { name: "help", summary: "List the commands", places: ["home", "chat"] },
];

export function commandsFor(place: Place): Command[] {
  return COMMANDS.filter((command) => command.places.includes(place));
}

// What a command is given when it is run: what it takes, which is nothing for most
export interface Invocation {
  name: CommandName;
  arg: string;
}

// Where the person is, as far as what a command can do depends on it
export interface Surroundings {
  place: Place;
  state: ChatState;
  // How many turns the conversation has had
  turns: number;
  // How many of them the lead answered, which a command that works on an answer needs one of
  answered: number;
  // What keeps a message from being sent, which a command that is given with one waits for
  holdUp: string | null;
  // Why the conversation cannot be given each of the commands that are given with a message, as it says, or null where
  // it is not begun, so that it is not known
  directives: Record<string, string | null> | null;
}

function sentence(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// What the person is told when the lead answered without doing what a command asked for, which is nothing for a command
// that asks for nothing that is checked
export function unmetNote(name: string): string | null {
  switch (name) {
    case "code":
      return "The lead answered without running any code, though /code asked for it.";
    case "plot":
      return "The lead answered without making a figure, though /plot asked for one.";
    case "search":
      return "The lead answered without searching the literature, though /search asked for it.";
    case "review":
      return "The Scientific Critic did not review the answer, though /review asked for it.";
    case "lab":
      return "The lead answered without bringing in the scientists you chose, though /lab asked for it.";
    default:
      return null;
  }
}

// What a command is as it was written in the box, to put back there when it could not be run
export function written({ name, arg }: Invocation): string {
  return arg === "" ? `/${name}` : `/${name} ${arg}`;
}

// Whether a command is given with words of the person's own: a message that says nothing is not one, unless the command is
export function takesText(name: string): boolean {
  return COMMANDS.find((command) => command.name === name)?.takes?.kind === "text";
}

// Whether a command has more to be written after its name before it can be run, which one that asks for it in a panel of its
// own does not
function needsWords(command: Command): boolean {
  return command.takes !== undefined && !(command.takes.kind === "text" && command.takes.optional === true);
}

// Why a command cannot be run now, in words, or null if it can
export function unavailableWhy(command: Command, { place, state, turns, answered, holdUp, directives }: Surroundings): string | null {
  const controls = controlsFor(state);
  if (isDirective(command.name)) {
    if (state !== "idle") return "It is given when the lead has finished";
    if (holdUp !== null) return holdUp;
    if (command.name === "review" && answered === 0) return "There is no answer to review yet";
    const why = directives?.[command.name];

    return why ? sentence(why) : null;
  }
  switch (command.name) {
    case "model":
      return place === "chat" && state !== "idle" ? "The model can be changed when the lead has finished" : null;
    case "export":
      return turns === 0 ? "There is nothing to save yet" : null;
    case "pause":
      if (state === "idle") return "Nothing is running";
      if (controls.pause === "resume") return "It is held already";

      return controls.canPause ? null : "It is stopping";
    case "resume":
      return controls.pause === "resume" && controls.canPause ? null : "Nothing is held";
    case "stop":
      return controls.canStop ? null : state === "idle" ? "Nothing is running" : "It is stopping";
    default:
      return null;
  }
}

// What the box has in it, as far as it is for a command
export type Typed =
  // Not a command, so it is a message
  | { kind: "none" }
  // A slash and the first letters of a name, which is being chosen
  | { kind: "naming"; query: string }
  // The name of a command, and what has been written after it
  | { kind: "arguing"; command: Command; rest: string };

// A command is the whole of the box, on one line unless it is given with a message: a slash, a name, and what the command takes. What is written to the lead
// that begins with a slash, such as the path of a file, is not one unless a command has that name.
export function typedCommand(draft: string, place: Place): Typed {
  const naming = /^\/([a-z]*)$/i.exec(draft);
  if (naming) return { kind: "naming", query: naming[1].toLowerCase() };
  const arguing = /^\/([a-z]+)[ \t]+([\s\S]*)$/i.exec(draft);
  if (!arguing) return { kind: "none" };
  const name = arguing[1].toLowerCase();
  const command = commandsFor(place).find((candidate) => candidate.name === name);
  // What is given to the lead can be several lines, which what is given to the page cannot
  if (!command || (arguing[2].includes("\n") && !isDirective(command.name))) return { kind: "none" };

  return { kind: "arguing", command, rest: arguing[2] };
}

// A line of the menu
export interface Row {
  key: string;
  // What it is called, which is what typing it in full is
  label: string;
  summary: string;
  // Why it cannot be chosen now, if it cannot
  reason: string | null;
  // What choosing it does: puts the start of the command in the box to be finished, or runs it
  action: { fill: string } | { run: Invocation };
}

function nameRow(command: Command, surroundings: Surroundings): Row {
  return {
    key: command.name,
    label: `/${command.name}`,
    summary: command.summary,
    reason: unavailableWhy(command, surroundings),
    action: needsWords(command) ? { fill: `/${command.name} ` } : { run: { name: command.name, arg: "" } },
  };
}

// The lines of the menu for what is in the box, which is none when it is not for a command. What can be chosen comes first,
// and what is named from its first letter before what has the letters elsewhere in its name.
export function rowsFor(draft: string, surroundings: Surroundings): Row[] {
  const typed = typedCommand(draft, surroundings.place);
  if (typed.kind === "none") return [];

  if (typed.kind === "naming") {
    const named = commandsFor(surroundings.place).filter((command) => command.name.includes(typed.query));
    const rows = [
      ...named.filter((command) => command.name.startsWith(typed.query)),
      ...named.filter((command) => !command.name.startsWith(typed.query)),
    ].map((command) => nameRow(command, surroundings));

    return [...rows.filter((row) => row.reason === null), ...rows.filter((row) => row.reason !== null)];
  }

  const { command, rest } = typed;
  const reason = unavailableWhy(command, surroundings);
  const takes = command.takes;
  if (takes === undefined) return rest.trim() === "" ? [nameRow(command, surroundings)] : [];

  if (takes.kind === "text") {
    const text = rest.trim();

    const needed = text === "" && takes.optional !== true;

    return [
      {
        key: command.name,
        label: `/${command.name}`,
        summary: text === "" ? (needed ? `Type ${takes.hint}` : command.summary) : `${command.summary}: ${text}`,
        reason: reason ?? (needed ? `Type ${takes.hint}` : null),
        action: { run: { name: command.name, arg: text } },
      },
    ];
  }

  const query = rest.trim().toLowerCase();
  const chosen = takes.choices.filter(
    (choice) => query === "" || choice.value.startsWith(query) || choice.label.toLowerCase().includes(query),
  );
  if (chosen.length === 0) {
    return [
      {
        key: command.name,
        label: `/${command.name}`,
        summary: command.summary,
        reason: `Choose ${takes.choices.map((choice) => choice.value).join(", ")}`,
        action: { run: { name: command.name, arg: "" } },
      },
    ];
  }

  return chosen.map((choice) => ({
    key: `${command.name} ${choice.value}`,
    label: `/${command.name} ${choice.value}`,
    summary: choice.hint,
    reason,
    action: { run: { name: command.name, arg: choice.value } },
  }));
}
