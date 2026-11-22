import { count, whole, type Checked } from "./checks";
import { formatBytes } from "./files";
import { doiOf, isRepo, MAX_AGENT_TITLE, REPO_HOSTS } from "./paperagents";
import { isDay } from "./papers";
import { isActive } from "./setup";
import type {
  Job,
  NewPaperAgent,
  NewTriage,
  PaperAgent,
  PreflightStatus,
  TriageCheck,
  TriageCounts,
  TriageEntry,
  TriageLimits,
  TriagePaperBody,
  TriageSource,
  TriageState,
  TriageTier,
} from "./types";

// A triage is its own page, named in the address's query as a bake-off is, and the triages are a part of the PaperAgents page
export const TRIAGES_ADDRESS = "/papers?view=triage";
export const triageAddress = (id: string) => `/papers?triage=${encodeURIComponent(id)}`;

// The most papers given by DOI alone whose abstracts the server looks up, which it does not say
export const MOST_LOOKED_UP = 30;

// The job that makes a triage, of which one is at work at a time, with the triage's id as its subject
export const TRIAGE_JOB = "paperagent-triage";

// The job at work on a triage, if one is
export function triageJob(jobs: readonly Job[] | null, id: string): Job | undefined {
  return (jobs ?? []).find((job) => isActive(job) && job.kind === TRIAGE_JOB && job.subject === id);
}

// The last job that worked on a triage, once it has ended
export function lastTriageJob(jobs: readonly Job[] | null, id: string): Job | undefined {
  return (jobs ?? []).find((job) => !isActive(job) && job.kind === TRIAGE_JOB && job.subject === id);
}

// What changes as a triage is made, so that what a page shows is looked at again when it does: which triages are being made,
// and how many jobs have ended. Its papers are kept only when the job ends, so how far it has got does not change them.
export function triageKey(jobs: readonly Job[] | null, ended: number, id?: string): string {
  const at = (jobs ?? []).filter((job) => isActive(job) && job.kind === TRIAGE_JOB && (id === undefined || job.subject === id)).map((job) => job.id);

  return `${ended}|${at.join(",")}`;
}

export const TIER_LABELS: Record<TriageTier, string> = {
  go: "Go",
  ask: "Ask first",
  "no-go": "No-go",
  not_looked_at: "Not looked at",
  no_code: "No code found",
};

export const TIERS = Object.keys(TIER_LABELS) as TriageTier[];

export const STATE_LABELS: Record<TriageState, string> = {
  running: "Looking",
  done: "Done",
  stopped: "Stopped",
  failed: "Failed",
  interrupted: "Interrupted",
};

// What each check of the pre-flight is of, which a triage does not keep, as it is the same for every paper
const CHECK_TITLES: Record<string, string> = {
  code: "There is code the sandbox runs",
  license: "It has a license to use it under",
  tutorials: "It shows how it is used",
  tests: "It has its own tests",
  environment: "It says what it needs installed",
  gpu: "It runs without a GPU",
  data: "Its data can be found",
  portability: "Its examples do not depend on one machine",
  submodules: "All of its code is here",
  size: "All of it was looked at",
};

export function checkTitle(check: Pick<TriageCheck, "id">): string {
  return CHECK_TITLES[check.id] ?? check.id;
}

// The checks in the order a person weighs them: what stops it, what to weigh, what is not known, what to know, and what is fine
const CHECK_ORDER: PreflightStatus[] = ["block", "warn", "unknown", "note", "ok"];

export function orderedTriageChecks(checks: readonly TriageCheck[]): TriageCheck[] {
  return [...checks].sort((a, b) => CHECK_ORDER.indexOf(a.status) - CHECK_ORDER.indexOf(b.status));
}

// Where the papers came from, in a few words
export function describeTriageSource(source: TriageSource): string {
  const parts: string[] = [];
  if (source.papers > 0) parts.push(`${count(source.papers, "paper")} given`);
  const listing = source.listing;
  if (listing !== null) {
    const subject = listing.subject === "all" ? "" : ` in ${listing.subject}`;
    const period = listing.until === null ? `from ${listing.since} on` : listing.until === listing.since ? `on ${listing.since}` : `from ${listing.since} to ${listing.until}`;
    parts.push(`up to ${listing.limit} bioRxiv preprints${subject} posted ${period}`);
  }

  return parts.length === 0 ? "No papers" : parts.join(" and ").replace(/^./, (first) => first.toUpperCase());
}

// How many papers there are of each tier, in a few words, leaving out the tiers that have none
export function describeCounts(counts: TriageCounts): string {
  const tiers = TIERS.filter((tier) => counts[tier] > 0).map((tier) => `${counts[tier]} ${TIER_LABELS[tier].toLowerCase()}`);

  return tiers.length === 0 ? count(counts.papers, "paper") : `${count(counts.papers, "paper")}: ${tiers.join(", ")}`;
}

// What was found in a paper's code, in a few words: its languages, its license, how much of it there is, and which commit it was
export function describeStock(stock: NonNullable<TriageEntry["stock"]>): string {
  const parts = [
    stock.languages.length > 0 ? stock.languages.join(", ") : "No language found",
    stock.license !== null ? `License: ${stock.license}` : "No license found",
    `${count(stock.files, "file")}, ${formatBytes(stock.bytes)}`,
    `at ${stock.commit.slice(0, 12)}`,
  ];

  return parts.join(" · ");
}

// Whose address of the code it is, in a few words
export function describeCodeFrom(entry: Pick<TriageEntry, "code_from">): string | null {
  if (entry.code_from === "person") return "the address you gave";
  if (entry.code_from === "abstract") return "the first address in its abstract";

  return null;
}

// The agent there is of a paper, by its DOI, if there is one
export function agentOf(agents: readonly PaperAgent[], doi: string | null): PaperAgent | undefined {
  if (doi === null) return undefined;
  const wanted = doi.toLowerCase();

  return agents.find((agent) => agent.paper.kind === "doi" && agent.paper.doi.toLowerCase() === wanted);
}

// The agent to make of a paper that was triaged: its paper by its DOI, with the code that the triage found, and called by its title,
// which is cut to what an agent may be called
export function agentFrom(entry: TriageEntry): NewPaperAgent | null {
  if (entry.paper === null) return null;
  const title = [...(entry.title.trim() || entry.paper.doi)].slice(0, MAX_AGENT_TITLE).join("").trimEnd();

  return { title, paper: entry.paper, ...(entry.code !== null ? { repo: entry.code } : {}) };
}

// What a person typed to ask for a triage: papers, a line each, and, if they asked for it, a listing of bioRxiv, with how many papers'
// code is looked at and the most that is fetched of one
export interface TriageDraft {
  papers: string;
  listing: boolean;
  since: string;
  until: string;
  subject: string;
  limit: string;
  lookedAt: string;
  megabytes: string;
}

export function emptyTriage(limits: TriageLimits): TriageDraft {
  return {
    papers: "",
    listing: false,
    since: "",
    until: "",
    subject: "all",
    limit: String(limits.default_listed),
    lookedAt: String(limits.default_looked_at),
    megabytes: String(limits.default_megabytes),
  };
}

export type TriageKey = "papers" | "since" | "until" | "limit" | "lookedAt" | "megabytes" | "form";

// The papers typed, a line each: its DOI, and after it, if it is known, the address of its code. A paper whose DOI was typed before is
// left out, as the server would.
export function checkGiven(text: string, most: number, hosts: readonly string[] = REPO_HOSTS): { value: TriagePaperBody[]; problem?: string } {
  const found = new Map<string, TriagePaperBody>();
  const lines = text.split(/\r?\n/);
  for (const [index, line] of lines.entries()) {
    const parts = line.split(/[\s,]+/).filter(Boolean);
    if (parts.length === 0) continue;
    const at = `Line ${index + 1}`;
    if (parts.length > 2) return { value: [], problem: `${at} has more than a DOI and the address of its code.` };
    const doi = doiOf(parts[0]);
    if (doi === null) return { value: [], problem: `${at}: ${parts[0]} is not a DOI, such as 10.1101/2024.01.01.123456.` };
    const code = parts[1];
    if (code !== undefined && !isRepo(code, hosts)) {
      return { value: [], problem: `${at}: ${code} is not the address of a project's code, such as https://github.com/owner/name.` };
    }
    if (!found.has(doi)) found.set(doi, code === undefined ? { doi } : { doi, code });
  }
  if (found.size > most) return { value: [], problem: `At most ${most} papers can be given, and these are ${found.size}.` };

  return { value: [...found.values()] };
}

export function checkTriage(draft: TriageDraft, limits: TriageLimits, hosts: readonly string[] = REPO_HOSTS): Checked<NewTriage, TriageKey> {
  const problems: Partial<Record<TriageKey, string>> = {};
  const given = checkGiven(draft.papers, limits.most_given, hosts);
  if (given.problem) problems.papers = given.problem;
  const body: NewTriage = {};
  if (given.value.length > 0) body.papers = given.value;
  if (draft.listing) {
    const since = draft.since.trim();
    const until = draft.until.trim();
    if (!isDay(since)) problems.since = "Say the first day, as a date.";
    if (until !== "" && !isDay(until)) problems.until = "Say the last day, as a date, or leave it blank.";
    else if (until !== "" && isDay(since) && until < since) problems.until = "The last day is before the first.";
    const limit = whole(draft.limit, "The number of preprints", 1, limits.most_listed);
    if (limit.problem) problems.limit = limit.problem;
    body.listing = { since, ...(until !== "" ? { until } : {}), subject: draft.subject, limit: limit.value ?? 0 };
  } else if (given.problem === undefined && given.value.length === 0) {
    problems.form = "Give papers to look at, list the preprints of bioRxiv, or both.";
  }
  const lookedAt = whole(draft.lookedAt, "The most papers whose code is looked at", 1, limits.most_looked_at);
  if (lookedAt.problem) problems.lookedAt = lookedAt.problem;
  const megabytes = whole(draft.megabytes, "The most that is fetched of one project", limits.min_megabytes, limits.max_megabytes);
  if (megabytes.problem) problems.megabytes = megabytes.problem.replace(/\.$/, ", in megabytes.");
  body.most_looked_at = lookedAt.value ?? 0;
  body.max_megabytes = megabytes.value ?? 0;

  return { value: Object.keys(problems).length === 0 ? body : null, problems };
}
