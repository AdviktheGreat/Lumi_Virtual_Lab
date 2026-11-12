import type { McpPromptArgument, McpServer } from "./types";

// A prompt of an MCP server that can be written after a slash, which the server writes out as the words to begin a message with
export interface PromptChoice {
  // The server it is of, by the name it is kept under and by the name it is shown as
  server: string;
  serverTitle: string;
  // What it is written as after a slash
  command: string;
  // Its name on the server, which is what the server is asked to write out
  name: string;
  description: string;
  arguments: McpPromptArgument[];
}

// The prompts that can be written after a slash: those of the servers a conversation has, which are named, or where none are
// named, of the servers that are on for new conversations. Only the prompts of a server that was connected to are known.
export function promptChoices(servers: readonly McpServer[] | null, named: readonly string[] | null): PromptChoice[] {
  if (servers === null) return [];

  return servers
    .filter((server) => (named === null ? server.added && server.enabled : named.includes(server.name)))
    .flatMap((server) =>
      (server.holds?.prompts ?? []).map((prompt) => ({
        server: server.name,
        serverTitle: server.title,
        command: prompt.command,
        name: prompt.name,
        description: prompt.description,
        arguments: prompt.arguments,
      })),
    );
}

// The box, with the words of a prompt put in it: in place of what was there if that was nothing, and where the person has written
// something since the prompt was asked for, after it
export function withPrompt(draft: string, text: string): string {
  return draft.trim() === "" ? text : `${draft}\n\n${text}`;
}

export type PromptArguments = { ok: true; values: Record<string, string> } | { ok: false; problem: string };

function escaped(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// What was written after a prompt's name, as the arguments it is given. The words that come first are for the first argument
// that is needed, or the first it takes, and each argument after them is written name=words, with the words going on to the
// next name that is written. A prompt that takes none is written alone.
export function readPromptArguments(prompt: PromptChoice, written: string): PromptArguments {
  const text = written.trim();
  const taken = prompt.arguments;
  if (taken.length === 0) return text === "" ? { ok: true, values: {} } : { ok: false, problem: "It takes no arguments" };
  const first = taken.find((argument) => argument.required) ?? taken[0];
  const marks = [...text.matchAll(new RegExp(`(?:^|\\s)(${taken.map((argument) => escaped(argument.name)).join("|")})=`, "g"))];
  // A map, since the names of the arguments are the server's, and a name such as constructor is not one that is there already
  const values = new Map<string, string>();
  const lead = (marks.length === 0 ? text : text.slice(0, marks[0].index)).trim();
  if (lead !== "") values.set(first.name, lead);
  for (const [at, mark] of marks.entries()) {
    const name = mark[1];
    const words = text.slice(mark.index + mark[0].length, at + 1 < marks.length ? marks[at + 1].index : text.length).trim();
    if (values.has(name)) return { ok: false, problem: `${name} is given twice` };
    if (words !== "") values.set(name, words);
  }
  const lacking = taken.find((argument) => argument.required && !values.has(argument.name));
  if (lacking === undefined) return { ok: true, values: Object.fromEntries(values) };

  return { ok: false, problem: lacking === first ? `Type ${lacking.name}` : `Add ${lacking.name}=…` };
}
