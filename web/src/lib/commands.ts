import { EXPORT_CHOICES } from "./export";
import { readPromptArguments, type PromptChoice } from "./prompts";
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
  | "skills"
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
  { name: "budget", summary: "Set what the program may spend, and what the lead may ask of the team", places: ["home", "chat"] },
  { name: "model", summary: "Change the model the lead and the team answer with", places: ["home", "chat"] },
  { name: "skills", summary: "Choose the skills the lead can read, which a program keeps from its start", places: ["home", "chat"] },
  { name: "rename", summary: "Give the program a new title", places: ["chat"], takes: { kind: "text", hint: "the new title" } },
  {
    name: "export",
    summary: "Save the program as a document",
    places: ["chat"],
    takes: {
      kind: "choice",
      choices: EXPORT_CHOICES.map(({ format, label, hint }) => ({ value: format, label, hint })),
    },
  },
  { name: "files", summary: "Show or hide the program's files", places: ["chat"] },
  { name: "new", summary: "Begin another program", places: ["chat"] },
  { name: "pause", summary: "Hold the lead after the step it is on", places: ["chat"] },
  { name: "resume", summary: "Let a held lead go on", places: ["chat"] },
  { name: "stop", summary: "Stop the lead after the step it is on", places: ["chat"] },
  { name: "help", summary: "List the commands", places: ["home", "chat"] },
];

export function commandsFor(place: Place): Command[] {
  return COMMANDS.filter((command) => command.places.includes(place));
}

// A skill of the conversation that can be written after a slash, with what it is for
export interface SkillChoice {
  name: string;
  description: string;
}

// How many skills the menu lists for the letters of a name, so that a library of hundreds does not fill it
export const SKILL_ROWS = 8;

// How many prompts the menu lists for the letters of a name, so that servers with a great many do not fill it
export const PROMPT_ROWS = 8;

// What a command is given when it is run: what it takes, which is nothing for most. A skill is given the words that say what
// it is to be used for, and goes with a message as a command does.
export type Sendable = { name: CommandName; arg: string } | { skill: string; arg: string };

// A prompt of an MCP server that is run: it is not sent, but written out by the server for its arguments, by name, into the
// box, to be read and sent by the person. What was written after its name is kept, to put back in the box if it could not be.
export interface PromptInvocation {
  prompt: PromptChoice;
  values: Record<string, string>;
  arg: string;
}

export type Invocation = Sendable | PromptInvocation;

// What a message is sent to the server with for an invocation: the command it names, or the skill
export function givenAs(invocation: Sendable | undefined): { directive?: string; skill?: string } {
  if (invocation === undefined) return {};

  return "skill" in invocation ? { skill: invocation.skill } : { directive: invocation.name };
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
  // The skills the conversation has, or will be begun with, which can be written after a slash
  skills?: readonly SkillChoice[];
  // The prompts of the MCP servers the conversation has, or will be begun with, which can be written after a slash
  prompts?: readonly PromptChoice[];
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

// What the person is told when the lead answered a message given with a skill without having read it
export function skillUnmetNote(name: string): string {
  return `The lead answered without reading the skill ${name}, though /${name} asked for it.`;
}

// What a command is as it was written in the box, to put back there when it could not be run
export function written(invocation: Invocation): string {
  const name = "skill" in invocation ? invocation.skill : "prompt" in invocation ? invocation.prompt.command : invocation.name;

  return invocation.arg === "" ? `/${name}` : `/${name} ${invocation.arg}`;
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

// Why what goes with a message cannot be given now, which is the same for a command and a skill
function givenWhy({ state, holdUp }: Pick<Surroundings, "state" | "holdUp">): string | null {
  if (state !== "idle") return "It is given when the lead has finished";

  return holdUp;
}

// Why a command cannot be run now, in words, or null if it can
export function unavailableWhy(command: Command, { place, state, turns, answered, holdUp, directives }: Surroundings): string | null {
  const controls = controlsFor(state);
  if (isDirective(command.name)) {
    const held = givenWhy({ state, holdUp });
    if (held !== null) return held;
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
  | { kind: "arguing"; command: Command; rest: string }
  // The name of one of the skills, and what has been written after it
  | { kind: "skilling"; skill: SkillChoice; rest: string }
  // The name of one of the prompts of an MCP server, and what has been written after it
  | { kind: "prompting"; prompt: PromptChoice; rest: string };

// A command is the whole of the box, on one line unless it is given with a message: a slash, a name, and what the command
// takes. A skill is the same, with the words it is to be used for, and its name is letters, digits, hyphens, dots, and
// underscores. What is written to the lead that begins with a slash, such as the path of a file, is not one unless a command
// or a skill has that name, which a command is where both have.
export function typedCommand(
  draft: string,
  place: Place,
  skills: readonly SkillChoice[] = [],
  prompts: readonly PromptChoice[] = [],
): Typed {
  const naming = /^\/([a-z0-9._-]*)$/i.exec(draft);
  if (naming) return { kind: "naming", query: naming[1].toLowerCase() };
  const arguing = /^\/([a-z0-9._-]+)[ \t]+([\s\S]*)$/i.exec(draft);
  if (!arguing) return { kind: "none" };
  const name = arguing[1].toLowerCase();
  const command = commandsFor(place).find((candidate) => candidate.name === name);
  if (command) {
    // What is given to the lead can be several lines, which what is given to the page cannot
    if (arguing[2].includes("\n") && !isDirective(command.name)) return { kind: "none" };

    return { kind: "arguing", command, rest: arguing[2] };
  }
  const skill = skills.find((candidate) => candidate.name.toLowerCase() === name);
  if (skill) return { kind: "skilling", skill, rest: arguing[2] };
  const prompt = prompts.find((candidate) => candidate.command.toLowerCase() === name);

  return prompt ? { kind: "prompting", prompt, rest: arguing[2] } : { kind: "none" };
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

const SKILL_NEEDS = "Type what to use it for";

// The skills whose names have the letters written after a slash, which are not listed until there are some, since there may
// be hundreds. Those named from the first letter come first.
function skillRows(query: string, surroundings: Surroundings): Row[] {
  if (query === "") return [];
  const named = (surroundings.skills ?? []).filter((skill) => skill.name.toLowerCase().includes(query));
  const reason = givenWhy(surroundings);

  return [
    ...named.filter((skill) => skill.name.toLowerCase().startsWith(query)),
    ...named.filter((skill) => !skill.name.toLowerCase().startsWith(query)),
  ]
    .slice(0, SKILL_ROWS)
    .map((skill) => ({
      key: `skill ${skill.name}`,
      label: `/${skill.name}`,
      summary: skill.description === "" ? "Have the lead read this skill first" : `Skill: ${skill.description}`,
      reason,
      action: { fill: `/${skill.name} ` },
    }));
}

// The prompts whose commands have the letters written after a slash, listed as the skills are, with the server each is of. One
// that takes arguments is begun in the box to be finished, and one that takes none is written out at once.
function promptRows(query: string, surroundings: Surroundings): Row[] {
  if (query === "") return [];
  const named = (surroundings.prompts ?? []).filter((prompt) => prompt.command.toLowerCase().includes(query));

  return [
    ...named.filter((prompt) => prompt.command.toLowerCase().startsWith(query)),
    ...named.filter((prompt) => !prompt.command.toLowerCase().startsWith(query)),
  ]
    .slice(0, PROMPT_ROWS)
    .map((prompt) => ({
      key: `prompt ${prompt.command}`,
      label: `/${prompt.command}`,
      summary: promptSummary(prompt),
      reason: null,
      action: prompt.arguments.length > 0 ? { fill: `/${prompt.command} ` } : { run: { prompt, values: {}, arg: "" } },
    }));
}

function promptSummary(prompt: PromptChoice): string {
  return prompt.description === "" ? `Prompt of ${prompt.serverTitle}` : `Prompt of ${prompt.serverTitle}: ${prompt.description}`;
}

// The lines of the menu for what is in the box, which is none when it is not for a command. What can be chosen comes first,
// and what is named from its first letter before what has the letters elsewhere in its name.
export function rowsFor(draft: string, surroundings: Surroundings): Row[] {
  const typed = typedCommand(draft, surroundings.place, surroundings.skills, surroundings.prompts);
  if (typed.kind === "none") return [];

  if (typed.kind === "naming") {
    const named = commandsFor(surroundings.place).filter((command) => command.name.includes(typed.query));
    const rows = [
      ...named.filter((command) => command.name.startsWith(typed.query)),
      ...named.filter((command) => !command.name.startsWith(typed.query)),
    ].map((command) => nameRow(command, surroundings));

    return [...rows.filter((row) => row.reason === null), ...rows.filter((row) => row.reason !== null),
      ...skillRows(typed.query, surroundings),
      ...promptRows(typed.query, surroundings),
    ];
  }

  if (typed.kind === "skilling") {
    const { skill, rest } = typed;
    const text = rest.trim();

    return [
      {
        key: `skill ${skill.name}`,
        label: `/${skill.name}`,
        summary: text === "" ? SKILL_NEEDS : `Use the skill ${skill.name} for: ${text}`,
        reason: givenWhy(surroundings) ?? (text === "" ? SKILL_NEEDS : null),
        action: { run: { skill: skill.name, arg: text } },
      },
    ];
  }

  if (typed.kind === "prompting") {
    const { prompt, rest } = typed;
    const read = readPromptArguments(prompt, rest);

    return [
      {
        key: `prompt ${prompt.command}`,
        label: `/${prompt.command}`,
        summary: `Write the prompt of ${prompt.serverTitle} out in the box, to read before sending`,
        reason: read.ok ? null : read.problem,
        action: { run: { prompt, values: read.ok ? read.values : {}, arg: rest.trim() } },
      },
    ];
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
