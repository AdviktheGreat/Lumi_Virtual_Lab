import { ApiError } from "./api";
import { characters, count, dollars, sentence, whole, type Checked } from "./checks";
import { formatBytes } from "./files";
import { formatCost, timeAgo } from "./format";
import { tidy } from "./scientists";
import { isActive } from "./setup";
import type {
  Job,
  NewPaperAgent,
  PaperAgent,
  PaperAgentFile,
  PaperAgentPaper,
  PaperAgentFetchOptions,
  PaperAgentPaperKind,
  PaperAgentReadOptions,
  PaperAgentReading,
  PaperAgentRepository,
  PaperAgentSource,
  PaperAgentStatus,
  PaperAgentStep,
  Preflight,
  PreflightEstimate,
  PreflightStatus,
  PreflightVerdict,
  ReadAnchor,
  ReadFact,
  RepositoryStock,
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
  // `new URL` takes http:/host and http:host, which the server does not, so the two slashes are asked for
  if (!/^https?:\/\//i.test(typed) || typed.length > MAX_LINK_CHARS || /\s/.test(typed)) return false;
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
  if (link.protocol !== "https:" || !hosts.includes(host)) return false;
  let segments: string[];
  try {
    segments = link.pathname.split("/").filter(Boolean).map(decodeURIComponent);
  } catch {
    return false;
  }
  // As the server cuts it: a GitLab project may be in groups, and what follows /-/ is a page of the project, and at the
  // other hosts the project is the first two parts
  if (host === "gitlab.com") {
    const page = segments.indexOf("-");
    if (page >= 0) segments = segments.slice(0, page);
  } else {
    segments = segments.slice(0, 2);
  }
  if (segments.length > 0) segments[segments.length - 1] = segments[segments.length - 1].replace(/\.git$/, "");

  return segments.length >= 2 && segments.every((part) => /^[A-Za-z0-9_.-]+$/.test(part) && part !== "." && part !== "..");
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
    // The server keeps a link to doi.org as the DOI in it, and refuses one that holds none
    else if (/^https?:\/\/(?:dx\.)?doi\.org(?:[/?#:]|$)/i.test(url) && doiOf(url) === null) {
      problems.url = "That link is to doi.org but has no DOI in it, such as 10.1038/s41586-020-2649-2.";
    }
    paper = { kind: "url", url };
  }
  const repo = draft.repo.trim();
  if (Object.keys(problems).length > 0) return { value: null, problems };

  return { value: { title, paper, ...(repo === "" ? {} : { repo }) }, problems };
}

// The file that was uploaded to an agent, which is the paper that is read. A DOI or a link has none until one is uploaded
// beside it, and then it is not said to be missing.
export function paperFile(paper: PaperAgentPaper): PaperAgentFile | null {
  return paper.file ?? null;
}

// Which paper an agent is of, in a few words
export function describePaper(paper: PaperAgentPaper): string {
  if (paper.kind === "doi") return `DOI ${paper.doi}`;
  if (paper.kind === "url") return paper.url;

  return paper.file === null ? "A file that has not been uploaded yet" : `${paper.file.name}, ${formatBytes(paper.file.bytes)}`;
}

// Where the text of a paper was fetched from, in a few words
export function describeSource(source: PaperAgentSource): string {
  return `Fetched from ${source.label}`;
}

// Where the paper can be opened, if it is anywhere. A link is only given if it leads somewhere by http or https, as the
// server holds it, so that a record that was edited by hand cannot send the page elsewhere.
export function paperLink(paper: PaperAgentPaper): string | null {
  if (paper.kind === "doi") return `https://doi.org/${paper.doi}`;

  return paper.kind === "url" && isLink(paper.url) ? paper.url : null;
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

// The job that reads the paper of an agent, which the server runs with the agent's id as its subject
export const READING_JOB = "paperagent-reading";

// The job at work reading an agent's paper, which nothing else is done to the agent in the meantime
export function readingJob(jobs: readonly Job[], agent: string): Job | undefined {
  return jobs.find((job) => isActive(job) && job.kind === READING_JOB && job.subject === agent);
}

// The latest reading of an agent's paper that is over, whose outcome is what it was last done with
export function lastReadingJob(jobs: readonly Job[], agent: string): Job | undefined {
  return jobs.find((job) => !isActive(job) && job.kind === READING_JOB && job.subject === agent);
}

// What changes as a paper is read, its code is fetched, an environment is built, or data is fetched, so that what a page shows of
// the agent, its reading, its code, its environment, and its data is looked at again when it does: which reading is at work, how
// many chunks it has done, which fetching, building, and fetching of data are, and how many jobs have ended
export function readingKey(jobs: readonly Job[] | null, ended: number, agent: string): string {
  const at = (jobs ?? [])
    .filter((job) => isActive(job) && job.kind === READING_JOB && job.subject === agent)
    .map((job) => `${job.id}:${job.progress.finished ?? ""}`);
  const fetching = (jobs ?? []).filter((job) => isActive(job) && job.kind === REPOSITORY_JOB && job.subject === agent).map((job) => job.id);
  const building = (jobs ?? []).filter((job) => isActive(job) && job.kind === ENVIRONMENT_JOB && job.subject === agent).map((job) => job.id);
  const getting = (jobs ?? []).filter((job) => isActive(job) && job.kind === DATA_JOB && job.subject === agent).map((job) => job.id);
  const running = (jobs ?? []).filter((job) => isActive(job) && job.kind === REFERENCE_JOB && job.subject === agent).map((job) => job.id);

  return `${ended}|${at.join(",")}${fetching.length > 0 ? `|${fetching.join(",")}` : ""}${building.length > 0 ? `|building:${building.join(",")}` : ""}${getting.length > 0 ? `|data:${getting.join(",")}` : ""}${running.length > 0 ? `|reference:${running.join(",")}` : ""}`;
}

// The job that fetches the code of an agent, which the server runs with the agent's id as its subject
export const REPOSITORY_JOB = "paperagent-repository";

// The job at work fetching an agent's code, which nothing else is done to the agent in the meantime
export function repositoryJob(jobs: readonly Job[], agent: string): Job | undefined {
  return jobs.find((job) => isActive(job) && job.kind === REPOSITORY_JOB && job.subject === agent);
}

// The latest fetching of an agent's code that is over, whose outcome is what it was last done with
export function lastRepositoryJob(jobs: readonly Job[], agent: string): Job | undefined {
  return jobs.find((job) => !isActive(job) && job.kind === REPOSITORY_JOB && job.subject === agent);
}

// The job that builds the environment of an agent's code, which the server runs with the agent's id as its subject
export const ENVIRONMENT_JOB = "paperagent-environment";

// The job at work building an agent's environment, which nothing else is done to the agent in the meantime
export function environmentJob(jobs: readonly Job[], agent: string): Job | undefined {
  return jobs.find((job) => isActive(job) && job.kind === ENVIRONMENT_JOB && job.subject === agent);
}

// The latest building of an agent's environment that is over, whose outcome is what it was last done with
export function lastEnvironmentJob(jobs: readonly Job[], agent: string): Job | undefined {
  return jobs.find((job) => !isActive(job) && job.kind === ENVIRONMENT_JOB && job.subject === agent);
}

// The job that fetches the data of an agent, which the server runs with the agent's id as its subject
export const DATA_JOB = "paperagent-data";

// The job at work fetching an agent's data, which nothing else is done to the agent in the meantime
export function dataJob(jobs: readonly Job[], agent: string): Job | undefined {
  return jobs.find((job) => isActive(job) && job.kind === DATA_JOB && job.subject === agent);
}

// The latest fetching of an agent's data that is over, whose outcome is what it was last done with
export function lastDataJob(jobs: readonly Job[], agent: string): Job | undefined {
  return jobs.find((job) => !isActive(job) && job.kind === DATA_JOB && job.subject === agent);
}

// The job that runs the tutorials of an agent's code, which the server runs with the agent's id as its subject
export const REFERENCE_JOB = "paperagent-reference";

// The job at work running an agent's tutorials, which nothing else is done to the agent in the meantime
export function referenceJob(jobs: readonly Job[], agent: string): Job | undefined {
  return jobs.find((job) => isActive(job) && job.kind === REFERENCE_JOB && job.subject === agent);
}

// The latest running of an agent's tutorials that is over, whose outcome is what it was last done with
export function lastReferenceJob(jobs: readonly Job[], agent: string): Job | undefined {
  return jobs.find((job) => !isActive(job) && job.kind === REFERENCE_JOB && job.subject === agent);
}

export interface ReadingDraft {
  budget: string;
  retryFailed: boolean;
}

export const EMPTY_READING: ReadingDraft = { budget: "1", retryFailed: false };

export function checkReading(draft: ReadingDraft): Checked<PaperAgentReadOptions, "budget"> {
  const budget = dollars(draft.budget, "the most it may spend", false);
  if (budget.problem || budget.value === null) return { value: null, problems: { budget: budget.problem } };

  return { value: { max_cost: budget.value, retry_failed: draft.retryFailed }, problems: {} };
}

// Whether a reading has been made of the paper, which it has once it has been begun, however far it got
export function hasReading(reading: PaperAgentReading): boolean {
  return reading.chunks !== null;
}

// Whether the paper has been read through, so that reading it again would spend money for what is there, unless the
// chunks that failed are read again, which is asked for
export function readThrough(reading: PaperAgentReading, retryFailed: boolean): boolean {
  return reading.complete && !(retryFailed && reading.failed > 0);
}

// How far the reading of a paper has got, in a few words
export function describeReading(reading: PaperAgentReading): string {
  if (reading.chunks === null) return "The paper has not been read.";
  const parts = [`Read ${reading.read} of ${count(reading.chunks, "chunk")}`];
  if (reading.skipped > 0) parts.push(`${reading.skipped} left out (the references)`);
  if (reading.failed > 0) parts.push(`${reading.failed} could not be read`);
  parts.push(reading.cost === null ? "cost unknown" : `spent ${formatCost(reading.cost) || "$0.00"}`);

  return parts.join(" · ");
}

// How many facts were left out for want of the paper's own words, which is said so that the reading is not taken for
// more than it is
export function describeLeftOut(reading: PaperAgentReading): string | null {
  const left = reading.dropped.quote + reading.dropped.detail;
  if (left === 0) return null;

  return `${count(left, "fact")} the model gave ${left === 1 ? "was" : "were"} left out, because the paper does not bear ${left === 1 ? "it" : "them"} out.`;
}

// How much of a paper was read, when it was too long to be read through
export function describeLength(reading: PaperAgentReading): string | null {
  if (reading.truncated_from === null || reading.characters === null) return null;

  return `The paper is long, so only its first ${reading.characters.toLocaleString("en-US")} of ${reading.truncated_from.toLocaleString("en-US")} characters were read.`;
}

// Where in the paper a fact is, in words: its page, if it has one, and its section, if it is in one
export function describeAnchor(anchor: ReadAnchor): string {
  const parts: string[] = [];
  if (anchor.page !== null) parts.push(`Page ${anchor.page}`);
  if (anchor.section) parts.push(anchor.section);

  return parts.length > 0 ? parts.join(", ") : `Characters ${anchor.start.toLocaleString("en-US")} to ${anchor.end.toLocaleString("en-US")}`;
}

// A fact as it is shown: what it says in a few words, what sort it is, and the paper's words, which are always shown
export interface FactLine {
  fact: ReadFact;
  title: string | null;
  tag: string | null;
}

// Each sort of fact, with what it is called and how its facts are shown
export interface FactGroup {
  key: string;
  label: string;
  facts: FactLine[];
}

const CLAIM_KINDS = { number: "A number", comparison: "A comparison", qualitative: "Another conclusion" } as const;

// The facts of a reading in the groups they are shown in, which are only those that have some, in the order a person
// reads them: what the authors claim, what they did and tested it on, where it falls short, and what it was done with
export function factGroups(reading: PaperAgentReading): FactGroup[] {
  const { card, resources } = reading;
  const groups: FactGroup[] = [
    {
      key: "claims",
      label: "What the authors report",
      facts: reading.claims.map((fact) => ({ fact, title: fact.value || null, tag: CLAIM_KINDS[fact.kind] ?? null })),
    },
    { key: "methods", label: "Methods", facts: card.methods.map((fact) => ({ fact, title: fact.name, tag: null })) },
    {
      key: "datasets",
      label: "Data used",
      facts: card.datasets.map((fact) => ({ fact, title: fact.name, tag: fact.accession || null })),
    },
    {
      key: "scope",
      label: "What the method was tested on",
      facts: card.scope.map((fact) => ({ fact, title: fact.value, tag: sentence(fact.aspect) })),
    },
    { key: "limitations", label: "Where the authors say it falls short", facts: card.limitations.map((fact) => ({ fact, title: null, tag: null })) },
    {
      key: "software",
      label: "Software",
      facts: resources.software.map((fact) => ({ fact, title: fact.name, tag: fact.version ? `Version ${fact.version}` : null })),
    },
    {
      key: "links",
      label: "Links",
      facts: resources.links.map((fact) => ({ fact, title: fact.url, tag: sentence(fact.role) })),
    },
    {
      key: "availability",
      label: "Where the data and code are said to be",
      facts: resources.availability.map((fact) => ({ fact, title: null, tag: fact.kind === "data" ? "Data" : "Code" })),
    },
    {
      key: "licenses",
      label: "Licenses",
      facts: resources.licenses.map((fact) => ({ fact, title: fact.name, tag: sentence(fact.covers) })),
    },
  ];

  return groups.filter((group) => group.facts.length > 0);
}

// How many facts a reading holds, of every sort
export function factCount(reading: PaperAgentReading): number {
  return factGroups(reading).reduce((sum, group) => sum + group.facts.length, 0);
}

// How many facts of a sort are shown before the rest are asked for
export const FACTS_SHOWN = 10;

// What of a branch, a tag, or a commit the server takes: it does not begin with a dash, which could be taken for an option,
// and has no "..", no "//", and no ending of ".", "/", or ".lock"
const REF = /^[A-Za-z0-9_][A-Za-z0-9_./@+-]{0,199}$/;

export function refProblem(text: string): string | null {
  const ref = text.trim();
  if (ref === "") return null;
  if (!REF.test(ref) || ref.includes("..") || ref.includes("//") || /(\.|\/|\.lock)$/.test(ref)) {
    return "That is not the name of a branch or a tag, or a commit.";
  }

  return null;
}

export interface FetchDraft {
  ref: string;
  megabytes: string;
}

export function emptyFetch(limits: PaperAgentRepository["limits"]): FetchDraft {
  return { ref: "", megabytes: String(limits.default_megabytes) };
}

type FetchKey = "ref" | "megabytes";

// What fetching the code is asked for: which branch, tag, or commit, which is left out for the project's default, and the
// most to fetch, in megabytes
export function checkFetch(draft: FetchDraft, limits: PaperAgentRepository["limits"]): Checked<PaperAgentFetchOptions, FetchKey> {
  const ref = refProblem(draft.ref);
  const size = whole(draft.megabytes, "The most to fetch, in megabytes,", limits.min_megabytes, limits.max_megabytes);
  if (ref !== null || size.problem || size.value === null) {
    return { value: null, problems: { ...(ref !== null ? { ref } : {}), ...(size.problem ? { megabytes: size.problem } : {}) } };
  }
  const named = draft.ref.trim();

  return { value: { ...(named !== "" ? { ref: named } : {}), max_megabytes: size.value }, problems: {} };
}

// What a verdict is called, and what a check that came out as each is called, as a person is told them
export const VERDICT_LABELS: Record<PreflightVerdict, string> = {
  go: "Go on",
  ask: "Ask first",
  "no-go": "Do not go on",
};

export const CHECK_LABELS: Record<PreflightStatus, string> = {
  ok: "Fine",
  note: "Note",
  warn: "Weigh this",
  block: "Stops it",
  unknown: "Not known",
};

// The checks in the order a person weighs them: what stops it, what to weigh, what is not known, what to know, and what is
// fine
const CHECK_ORDER: PreflightStatus[] = ["block", "warn", "unknown", "note", "ok"];

export function orderedChecks(preflight: Preflight): Preflight["checks"] {
  return [...preflight.checks].sort((a, b) => CHECK_ORDER.indexOf(a.status) - CHECK_ORDER.indexOf(b.status));
}

// What making tools from the code's tutorials is guessed to cost, in a few words, or null if it cannot be told
export function describeEstimate(estimate: PreflightEstimate): string | null {
  if (estimate.low === null || estimate.high === null || estimate.tutorials === 0) return null;
  const low = formatCost(estimate.low) || "$0.00";
  const high = formatCost(estimate.high) || "$0.00";

  return `Making tools from ${count(estimate.tutorials, "tutorial")} is guessed at ${low === high ? low : `${low} to ${high}`} in model requests.`;
}

// Which commit was fetched, and what was asked for to get it, in a few words
export function describeCommit(url: string, ref: string, commit: string): string {
  const asked = ref === "HEAD" ? "the default branch" : ref;

  return `${repoName(url)} at ${commit.slice(0, 12)} (${asked})`;
}

// When the code was fetched, in a few words
export function describeFetched(at: string): string {
  return `Fetched ${timeAgo(at) || "a while ago"}`;
}

const PINS: Record<string, string> = {
  locked: "versions locked",
  all: "versions given",
  some: "some versions given",
  none: "no versions given",
};

// One line of what was found in a project: what it is, what was found, and the paths that it is of, the first of them
export interface StockRow {
  label: string;
  value: string;
  items: string[];
}

// How many paths of a row are listed
export const STOCK_ITEMS_SHOWN = 5;

// What was found in a project, as rows for a person to read, each with what it is and what was found, and where
export function stockRows(stock: RepositoryStock): StockRow[] {
  const bigFiles = (found: number, bytes: number) => `${count(found, "file")}, ${formatBytes(bytes)}`;
  const rows: StockRow[] = [
    {
      label: "Size",
      value: `${bigFiles(stock.files, stock.bytes)}${stock.complete ? "" : ". It is large, and only part of it was looked at"}`,
      items: [],
    },
    {
      label: "Languages",
      value:
        stock.languages.length === 0
          ? "No code was found"
          : stock.languages
              .slice(0, 4)
              .map((language) => `${language.name} (${count(language.files, "file")})`)
              .join(", "),
      items: [],
    },
    {
      label: "Tutorials",
      value:
        stock.tutorials.count === 0
          ? stock.readme?.example
            ? "None, but the README shows how it is used"
            : "None"
          : `${stock.tutorials.count.toLocaleString("en-US")}, of which ${count(stock.notebooks.count, "notebook")}`,
      items: stock.tutorials.listed.map((item) => item.path),
    },
    {
      label: "Tests",
      value: stock.tests.count === 0 ? "None" : stock.tests.count.toLocaleString("en-US"),
      items: stock.tests.listed,
    },
    {
      label: "What to install",
      value:
        stock.environment.length === 0
          ? "No file says"
          : stock.environment.map((item) => `${item.path}${item.pins !== null && PINS[item.pins] ? ` (${PINS[item.pins]})` : ""}`).join(", "),
      items: [],
    },
    { label: "License", value: describeLicense(stock), items: stock.license?.files ?? [] },
    {
      label: "GPU",
      value:
        stock.gpu.required.length > 0
          ? "Needed"
          : stock.gpu.optional.length > 0
            ? "Used if there is one, and not needed"
            : "Not asked for",
      items: [...stock.gpu.required, ...stock.gpu.optional].map((item) => `${item.signal} (${item.path})`),
    },
    { label: "Data", value: describeData(stock), items: stock.data.listed.map((item) => item.path) },
  ];
  if (stock.submodules.length > 0) {
    rows.push({ label: "Submodules, which are not fetched", value: stock.submodules.length.toLocaleString("en-US"), items: stock.submodules.map((item) => item.path) });
  }
  if (stock.absolute_paths.count > 0) {
    rows.push({
      label: "Examples that read from someone's computer",
      value: stock.absolute_paths.count.toLocaleString("en-US"),
      items: stock.absolute_paths.listed.map((item) => `${item.example} (${item.path})`),
    });
  }

  return rows;
}

// What the license is, in a few words
export function describeLicense(stock: RepositoryStock): string {
  const found = stock.license;
  if (found === null) return "None";
  const kinds: Record<string, string> = { permissive: "permissive", copyleft: "copyleft", noncommercial: "for non-commercial use" };
  const kind = kinds[found.kind];
  if (found.name === null) return `Not recognized${kind ? `, ${kind}` : ""}`;

  return `${found.name}${kind ? ` (${kind})` : ""}`;
}

// What there is of data in the project or pointed to from it, in a few words
export function describeData(stock: RepositoryStock): string {
  const { data } = stock;
  const parts: string[] = [];
  if (data.count > 0) parts.push(`${count(data.count, "data or model file")} (${formatBytes(data.bytes)})`);
  if (data.lfs_pointers > 0) parts.push(`${count(data.lfs_pointers, "file")} in Git LFS, which are not fetched`);
  if (data.dvc) parts.push("kept with DVC, which is not fetched");
  if (data.links.length > 0) parts.push(`${count(data.links.length, "link")} to where data is kept`);
  if (data.accessions.length > 0) parts.push(`accessions ${data.accessions.slice(0, 3).join(", ")}`);

  return parts.length > 0 ? parts.join("; ") : "Nothing says where it is";
}
