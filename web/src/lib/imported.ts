import type { Checked } from "./checks";
import { count } from "./checks";
import { timeAgo } from "./format";
import { checkAgent, EMPTY_AGENT, REPO_HOSTS, type AgentDraft } from "./paperagents";
import type { ImportableAgent, NewImport, PaperAgent, PaperAgentImported, PaperAgentsList } from "./types";

// The longest address of a server that the server keeps
export const MAX_ADDRESS_CHARS = 2000;

const KEY_PROBLEM =
  "The address is without a name, a password, or a query in it. A server that wants a key in its address is set up under Add MCP server in the Tools Nexus, where keys are kept.";

// The address of a server as it is typed: what is wrong with it, or null. The server holds it to the same.
export function addressProblem(text: string): string | null {
  const typed = text.trim();
  if (typed === "") return "Give the address of the server.";
  // The server refuses a control character as well as a space
  if (typed.length > MAX_ADDRESS_CHARS || /[\s\u0000-\u001f\u007f]/.test(typed)) return `The address is up to ${MAX_ADDRESS_CHARS} characters, with no spaces.`;
  if (!/^https?:\/\//i.test(typed)) return "The address begins with http:// or https://.";
  // A config puts the value of a variable that is named in an address in its place, which would send it to the server
  if (/[${}]/.test(typed)) return "The address has no $, {, or } in it, which would be read as the name of a variable.";
  let link: URL;
  try {
    link = new URL(typed);
  } catch {
    return "That is not a web address.";
  }
  if (link.hostname === "") return "That is not a web address.";
  // An @ before the host is a name, even an empty one, which `new URL` leaves as an empty username
  const authority = typed.replace(/^https?:\/\//i, "").split(/[/?#]/, 1)[0];
  if (authority.includes("@") || link.username !== "" || link.password !== "" || link.search !== "" || link.hash !== "") return KEY_PROBLEM;

  return null;
}

// A server that is imported as it is typed: where it is, and which paper it is of, as an agent is made
export interface ImportDraft extends AgentDraft {
  address: string;
}

export const EMPTY_IMPORT: ImportDraft = { ...EMPTY_AGENT, address: "" };

export type ImportKey = "address" | "title" | "doi" | "url" | "repo";

export function checkImport(draft: ImportDraft, hosts: readonly string[] = REPO_HOSTS): Checked<NewImport, ImportKey> {
  const agent = checkAgent(draft, hosts);
  const problems: Partial<Record<ImportKey, string>> = { ...agent.problems };
  const wrong = addressProblem(draft.address);
  if (wrong !== null) problems.address = wrong;
  if (agent.value === null || wrong !== null) return { value: null, problems };

  return { value: { url: draft.address.trim(), ...agent.value }, problems };
}

// Who made an agent, as far as is known, which only the servers that Paper2Agent hosts say, since the name of a host does not
// show who made what it holds
export function describeMaker(imported: Pick<PaperAgentImported, "origin">): string {
  return imported.origin ? `Made by ${imported.origin}` : "Made by someone else";
}

// Where it runs
export function describeHost(imported: Pick<PaperAgentImported, "host">): string {
  return `Runs on ${imported.host}, a machine that is not this one and is not run by Lumi.`;
}

// How many tools it listed
export function describeListed(tools: PaperAgentImported["tools"]): string {
  return tools.length === 0 ? "It listed no tools." : `It listed ${count(tools.length, "tool")}.`;
}

// When it was imported and its server last connected to
export function describeWhen(imported: Pick<PaperAgentImported, "imported_at" | "checked_at">, now: Date = new Date()): string {
  const imports = timeAgo(imported.imported_at, now);
  const checks = timeAgo(imported.checked_at, now);
  const first = imports === "" ? "Imported" : `Imported ${imports}`;

  return checks === "" ? `${first}.` : `${first}. Its server was last connected to ${checks}.`;
}

// What a server that others host is said to be, which says that it is not Lumi's
export function describeHosted(server: Pick<ImportableAgent, "made_by" | "url">): string {
  let host = server.url;
  try {
    host = new URL(server.url).hostname.toLowerCase();
  } catch {
    // The address is shown as it is given
  }

  // A .hf.space address is a Space on Hugging Face, which is where Paper2Agent runs its servers
  const where = host.endsWith(".hf.space") ? `${host}, a Space on Hugging Face` : host;

  return `Made by ${server.made_by}, and run on ${where}, which is not run by Lumi. What a call is given is sent there, so each call asks you first.`;
}

// What else is known of using a server that Paper2Agent hosts, which they say themselves and the lab has not changed: their tools
// read files that are on their server, where the lab does not upload files, and AlphaGenome's take a key as an argument
export function describeNote(server: Pick<ImportableAgent, "key" | "made_by">): string | null {
  if (server.made_by !== "Paper2Agent") return null;
  const files = "Its tools read files that are on its server, and the lab does not upload files to it, so they work on data that is already there.";

  return server.key === "alphagenome"
    ? `${files} They take your AlphaGenome API key as an argument, which is sent to that server, so read each call before you approve it.`
    : files;
}

// What there is to do with a server that is listed: it has an agent already, there is an agent of its paper that it can be added
// to, or it makes an agent
export type ImportState =
  | { kind: "imported"; agent: string }
  | { kind: "add"; agent: string }
  | { kind: "new" };

export function importState(server: Pick<ImportableAgent, "agent" | "paper_agent">): ImportState {
  if (server.agent !== null) return { kind: "imported", agent: server.agent };
  if (server.paper_agent !== null) return { kind: "add", agent: server.paper_agent };

  return { kind: "new" };
}

// What a quick pick asks of the server: the server added to the agent of its paper, or an agent made of the paper
export function quickImport(server: ImportableAgent, state: ImportState): NewImport {
  if (state.kind === "add") return { url: server.url, agent: state.agent };

  return { url: server.url, title: server.title, paper: server.paper, repo: server.repo };
}

// The title of an agent that there is, as the list has it
export function titleOf(list: Pick<PaperAgentsList, "agents">, id: string): string {
  return list.agents.find((agent: PaperAgent) => agent.id === id)?.title ?? id;
}
