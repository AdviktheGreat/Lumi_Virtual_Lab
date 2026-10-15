import type { McpEntry, McpServer } from "./types";

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
