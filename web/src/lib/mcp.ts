import type { McpCheck, McpEntry, McpServer } from "./types";

// What a server's name may be, as the server says: it starts the names of the server's tools
const SERVER_NAME = /^[A-Za-z][A-Za-z0-9_]{0,31}$/;

// What is wrong with the name a person gave a server of their own, which the server would refuse, or null
export function nameProblem(name: string, servers: McpServer[]): string | null {
  const given = name.trim();
  if (given === "") return "Give the server a name.";
  if (!SERVER_NAME.test(given)) return "A name starts with a letter and is made of letters, digits, and _, at most 32.";
  if (servers.some((server) => server.preset && server.name === given)) {
    return `${given} is the name of one of the library's servers: name yours something else.`;
  }

  return null;
}

export type ReadEntry = { ok: true; entry: McpEntry } | { ok: false; problem: string };

const EXAMPLE = '{"url": "https://example.com/mcp"}';

// A server's entry as it was typed, which is JSON, as a config of any other tool gives it
export function readEntry(text: string): ReadEntry {
  if (text.trim() === "") return { ok: false, problem: `Describe the server in JSON, such as ${EXAMPLE}.` };
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (error) {
    return { ok: false, problem: `That is not JSON: ${error instanceof Error ? error.message : "it could not be read"}.` };
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return { ok: false, problem: `A server is described by an object, such as ${EXAMPLE}.` };
  }

  return { ok: true, entry: value as McpEntry };
}

// How many servers are turned on, as a person reads it
export function howManyOn(servers: McpServer[]): string {
  const on = servers.filter((server) => server.enabled).length;
  if (on === 0) return "None are on";
  if (on === servers.length) return `All ${servers.length} are on`;

  return `${on} of ${servers.length} are on`;
}

const TRANSPORTS = {
  stdio: "Runs a program on this computer",
  http: "Reached over HTTP",
  sse: "Reached over SSE",
} as const;

export function describeTransport(server: McpServer): string | null {
  return server.transport === null ? null : TRANSPORTS[server.transport];
}

// The keys a server asks for that the person must give where the server was started, since this page gives only the keys
// of the library's services
export function keysToSetElsewhere(server: McpServer): string[] {
  return server.missing.filter((key) => !key.settable).map((key) => key.name);
}

// The keys of a server that this page may give or take away, whether or not they are set, in the order the server
// asks for them, those that are not set first
export function keysToGive(server: McpServer): { name: string; set: boolean }[] {
  return [
    ...server.missing.filter((key) => key.settable).map((key) => ({ name: key.name, set: false })),
    ...server.keys_set.map((name) => ({ name, set: true })),
  ];
}

// The most tools a check names, so that a server with a great many does not fill the page
export const MOST_TOOLS_NAMED = 12;

// What a check found, as a person reads it, with the names of the tools to show, which are named in full only so far
export function describeCheck(check: McpCheck): { text: string; tools: string[]; more: number } {
  if (!check.ok) return { text: check.reason ?? "It could not be connected to.", tools: [], more: 0 };
  if (check.tools.length === 0) return { text: "Connected, but it gives no tools.", tools: [], more: 0 };
  const count = check.tools.length === 1 ? "1 tool" : `${check.tools.length} tools`;

  return {
    text: `Connected. It gives ${count}:`,
    tools: check.tools.slice(0, MOST_TOOLS_NAMED),
    more: Math.max(0, check.tools.length - MOST_TOOLS_NAMED),
  };
}

// What a server's sign-in is, for what is shown beside it, or null for a server that is not signed in to
export function describeSignIn(server: McpServer): string | null {
  if (server.signed_in === null) return null;

  return server.signed_in
    ? "Signed in. Conversations use it without asking you."
    : "Not signed in yet. A conversation that has it on asks you to sign in when you send its first message.";
}
