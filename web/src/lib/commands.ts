import { EXPORT_CHOICES } from "./export";
import { controlsFor } from "./steering";
import type { ChatState } from "./types";

// Where a command can be given: in a conversation, or on the page where one is begun
export type Place = "home" | "chat";

export type CommandName = "budget" | "model" | "files" | "export" | "rename" | "new" | "pause" | "resume" | "stop" | "help";

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
  takes?: { kind: "choice"; choices: Choice[] } | { kind: "text"; hint: string };
}

// The commands, in the order the menu lists them
export const COMMANDS: Command[] = [
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
}

// Why a command cannot be run now, in words, or null if it can
export function unavailableWhy(command: Command, { place, state, turns }: Surroundings): string | null {
  const controls = controlsFor(state);
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

// A command is the whole of the box, on one line: a slash, a name, and what the command takes. What is written to the lead
// that begins with a slash, such as the path of a file, is not one unless a command has that name.
export function typedCommand(draft: string, place: Place): Typed {
  const naming = /^\/([a-z]*)$/i.exec(draft);
  if (naming) return { kind: "naming", query: naming[1].toLowerCase() };
  const arguing = /^\/([a-z]+)[ \t]+(.*)$/i.exec(draft);
  if (!arguing) return { kind: "none" };
  const name = arguing[1].toLowerCase();
  const command = commandsFor(place).find((candidate) => candidate.name === name);

  return command ? { kind: "arguing", command, rest: arguing[2] } : { kind: "none" };
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
    action: command.takes ? { fill: `/${command.name} ` } : { run: { name: command.name, arg: "" } },
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

    return [
      {
        key: command.name,
        label: `/${command.name}`,
        summary: text === "" ? `Type ${takes.hint}` : `${command.summary}: ${text}`,
        reason: reason ?? (text === "" ? `Type ${takes.hint}` : null),
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
