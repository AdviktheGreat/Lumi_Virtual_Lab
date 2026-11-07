import { webSearchRow } from "./keys";
import { keysToGive, keysToSetElsewhere } from "./mcp";
import type { KeyStatuses, McpCatalogServer, McpServer, ToolInfo } from "./types";

// Whether a server can be used as it is, or what stands in the way, in the word its card shows
export interface Readiness {
  tone: "ready" | "needs" | "problem";
  label: string;
}

export function readiness(server: McpServer): Readiness {
  if (server.problem !== null) return { tone: "problem", label: "Problem" };
  if (server.missing.some((key) => key.settable)) return { tone: "needs", label: "Needs a key" };
  if (server.missing.length > 0) return { tone: "needs", label: "Needs setup" };
  if (server.signed_in === false) return { tone: "needs", label: "Needs sign-in" };

  return { tone: "ready", label: "Ready" };
}

const SIGNED_IN = "Your account, signed in to in the browser";

// What it takes to use a server, in a few words: an account to sign in to, a key, or a program on this computer
export function needsText(server: McpServer): string {
  if (server.auth_choices.length > 0) return "An API key, or your account signed in to in the browser";
  if (server.auth === "oauth") return SIGNED_IN;
  const needs: string[] = [];
  if (server.transport === "stdio") needs.push("a program installed on this computer");
  if (keysToGive(server).length > 0) needs.push("an API key");
  if (keysToSetElsewhere(server).length > 0) needs.push("a key set where the server was started");
  if (needs.length === 0) return "Nothing";
  const text = needs.join(", and ");

  return text.charAt(0).toUpperCase() + text.slice(1);
}

// What it takes to use a server of the catalog, which is nothing or a sign-in
export function catalogNeeds(server: McpCatalogServer): string {
  return server.signs_in ? SIGNED_IN : "Nothing";
}

// The servers of the catalog that are not set up, by what they are for, in the order the catalog gives them
export function catalogToAdd(servers: McpCatalogServer[]): { group: string; servers: McpCatalogServer[] }[] {
  const groups: { group: string; servers: McpCatalogServer[] }[] = [];
  for (const server of servers.filter((each) => !each.added)) {
    const found = groups.find((each) => each.group === server.group);
    if (found) found.servers.push(server);
    else groups.push({ group: server.group, servers: [server] });
  }

  return groups;
}

// The group of the library's tools that search the web and read pages
export const WEB_GROUP = "Web";

export function webTools(tools: ToolInfo[]): ToolInfo[] {
  return tools.filter((tool) => tool.group === WEB_GROUP);
}

export interface WebSearchState {
  // Whether a new conversation is given any of the tools of the web
  on: boolean;
  // Which engine the lead searches with
  engine: "Exa" | "DuckDuckGo";
}

export function webSearchState(tools: ToolInfo[], keys: KeyStatuses): WebSearchState {
  return {
    on: webTools(tools).some((tool) => tool.enabled),
    engine: webSearchRow(keys).set ? "Exa" : "DuckDuckGo",
  };
}

// What is said of how the web is searched
export function engineSaid(engine: WebSearchState["engine"]): string {
  return engine === "Exa"
    ? "Searches with Exa, for which a key is set."
    : "Searches with DuckDuckGo, which needs no key but turns away a client that searches often. A key for Exa searches with Exa.";
}
