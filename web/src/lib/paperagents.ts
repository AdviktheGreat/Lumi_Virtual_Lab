import { ApiError } from "./api";
import { characters, type Checked } from "./checks";
import { formatBytes } from "./files";
import { tidy } from "./scientists";
import type {
  NewPaperAgent,
  PaperAgent,
  PaperAgentPaper,
  PaperAgentPaperKind,
  PaperAgentStatus,
  PaperAgentStep,
} from "./types";

// What the server takes of an agent's title, a link, and a DOI
export const MAX_AGENT_TITLE = 200;
export const MAX_LINK_CHARS = 2000;
export const MAX_DOI_CHARS = 200;

// Where the code of a paper may be, which the server says too, and which is only here for a page that has not been told
export const REPO_HOSTS = ["github.com", "gitlab.com", "bitbucket.org", "codeberg.org"];

export const PAPER_KIND_LABELS: Record<PaperAgentPaperKind, string> = {
  doi: "A DOI",
  url: "A link",
  file: "A file I upload",
};

export const PAPER_KINDS = Object.keys(PAPER_KIND_LABELS) as PaperAgentPaperKind[];

// The steps of making an agent, in the order they are done, each as a person is told it
export const STEP_LABELS: Record<PaperAgentStep, string> = {
  reading: "Read the paper",
  repository: "Take stock of its code",
  environment: "Build what the code needs",
  data: "Get the data",
  tools: "Build the tools",
};

export const STEPS = Object.keys(STEP_LABELS) as PaperAgentStep[];

export const STATUS_LABELS: Record<PaperAgentStatus, string> = {
  pending: "Not started",
  running: "Going on",
  done: "Done",
  failed: "Failed",
  skipped: "Skipped",
};

// Where the agents are, which is the page of PaperAgents as it opens
export const AGENTS_ADDRESS = "/papers";

export const agentAddress = (id: string) => `/papers?agent=${encodeURIComponent(id)}`;

// The DOI in what was typed, in lower case and without what a link to it begins with, or null if there is none
export function doiOf(text: string): string | null {
  const typed = text
    .trim()
    .replace(/^(?:doi:\s*|https?:\/\/(?:dx\.)?doi\.org\/)/i, "")
    .trim();

  return /^10\.\d{4,9}\/\S+$/.test(typed) && typed.length <= MAX_DOI_CHARS ? typed.toLowerCase() : null;
}

// Whether text is a web address that leads somewhere by http or https, with no name and password in it
export function isLink(text: string): boolean {
  const typed = text.trim();
  if (typed === "" || typed.length > MAX_LINK_CHARS || /\s/.test(typed)) return false;
  try {
    const link = new URL(typed);

    return (link.protocol === "http:" || link.protocol === "https:") && link.hostname !== "" && link.username === "" && link.password === "";
  } catch {
    return false;
  }
}

// Whether text is the address of a project at a host that holds code, such as https://github.com/owner/name
export function isRepo(text: string, hosts: readonly string[] = REPO_HOSTS): boolean {
  const typed = text.trim();
  if (!isLink(typed)) return false;
  const link = new URL(typed);
  const host = link.hostname.toLowerCase().replace(/^www\./, "");
  const segments = link.pathname.split("/").filter(Boolean);

  return link.protocol === "https:" && hosts.includes(host) && segments.length >= 2 && !segments.some((part) => part === "." || part === "..");
}

export interface AgentDraft {
  title: string;
  kind: PaperAgentPaperKind;
  doi: string;
  url: string;
  repo: string;
}

export const EMPTY_AGENT: AgentDraft = { title: "", kind: "doi", doi: "", url: "", repo: "" };

type AgentKey = "title" | "doi" | "url" | "repo";

// A repo as it is typed, which may be left blank: the problem with it, or null
export function repoProblem(text: string, hosts: readonly string[] = REPO_HOSTS): string | null {
  const typed = text.trim();
  if (typed === "" || isRepo(typed, hosts)) return null;

  return `Give the address of the project, such as https://github.com/owner/name, at ${hosts.join(", ")}.`;
}

// A title as it is typed, where one is needed: the problem with it, or null
export function titleProblem(text: string, needed: boolean): string | null {
  const title = tidy(text);
  if (title === "") return needed ? "Give the agent a title." : null;

  return characters(title) > MAX_AGENT_TITLE ? `The title can be at most ${MAX_AGENT_TITLE} characters, and this is ${characters(title)}.` : null;
}

export function checkAgent(draft: AgentDraft, hosts: readonly string[] = REPO_HOSTS): Checked<NewPaperAgent, AgentKey> {
  const problems: Partial<Record<AgentKey, string>> = {};
  const title = tidy(draft.title);
  const wrongTitle = titleProblem(draft.title, draft.kind === "file");
  if (wrongTitle !== null) problems.title = wrongTitle;
  const wrongRepo = repoProblem(draft.repo, hosts);
  if (wrongRepo !== null) problems.repo = wrongRepo;
  let paper: NewPaperAgent["paper"] = { kind: "file" };
  if (draft.kind === "doi") {
    const doi = doiOf(draft.doi);
    if (doi === null) problems.doi = "Give a DOI, such as 10.1038/s41586-020-2649-2.";
    paper = { kind: "doi", doi: doi ?? draft.doi.trim() };
  } else if (draft.kind === "url") {
    const url = draft.url.trim();
    if (!isLink(url)) problems.url = "Give the link, which begins with http:// or https://.";
    paper = { kind: "url", url };
  }
  const repo = draft.repo.trim();
  if (Object.keys(problems).length > 0) return { value: null, problems };

  return { value: { title, paper, ...(repo === "" ? {} : { repo }) }, problems };
}

// Which paper an agent is of, in a few words
export function describePaper(paper: PaperAgentPaper): string {
  if (paper.kind === "doi") return `DOI ${paper.doi}`;
  if (paper.kind === "url") return paper.url;

  return paper.file === null ? "A file that has not been uploaded yet" : `${paper.file.name}, ${formatBytes(paper.file.bytes)}`;
}

// Where the paper can be opened, if it is anywhere
export function paperLink(paper: PaperAgentPaper): string | null {
  if (paper.kind === "doi") return `https://doi.org/${paper.doi}`;

  return paper.kind === "url" ? paper.url : null;
}

// The owner and name of a project, from its address
export function repoName(url: string): string {
  try {
    return new URL(url).pathname.replace(/^\/+|\/+$/g, "");
  } catch {
    return url;
  }
}

// How far an agent has got, in a few words: how many of its steps are done
export function describeSteps(agent: PaperAgent): string {
  const done = STEPS.filter((step) => agent.steps[step] === "done").length;
  const going = STEPS.find((step) => agent.steps[step] === "running");
  if (going !== undefined) return `${STEP_LABELS[going]} is going on`;
  if (done === 0) return "Nothing has been done to it yet";

  return `${done} of ${STEPS.length} steps done`;
}

// The agent that already has a paper, if that is why the server refused an agent or a file, which it says
export function existingOf(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.code !== "exists") return null;

  return typeof error.details.existing === "string" ? error.details.existing : null;
}
