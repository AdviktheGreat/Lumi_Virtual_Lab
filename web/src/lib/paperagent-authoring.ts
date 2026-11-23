// What is said to the person who wrote a paper, or reviews it, of what a reader who takes its code as a stranger would hit: the
// verdict, the findings by how bad they are, the steps that were not run, and the package for the authors

import { formatBytes } from "./files";
import type { AuthorArea, AuthorFinding, AuthorSeverity, AuthorUnchecked, AuthorVerdict, PaperAgentAuthor } from "./types";
import type { Loaded } from "./use-settings-data";

export const SEVERITIES: AuthorSeverity[] = ["block", "warn", "note"];

export const VERDICT_TITLES: Record<AuthorVerdict, string> = {
  not_checked: "Not looked at",
  blocked: "A reader is stopped",
  to_fix: "To fix",
  unfinished: "Not every step was run",
  ready: "Ready for a reader",
};

export const SEVERITY_TITLES: Record<AuthorSeverity, string> = {
  block: "Would stop a reader",
  warn: "Would probably stop or mislead a reader",
  note: "For a reader to know",
};

// A severity in a word, beside each finding, so that it is not told by its colour alone
export const SEVERITY_WORDS: Record<AuthorSeverity, string> = {
  block: "Stops",
  warn: "Warns",
  note: "Note",
};

export const AREA_TITLES: Record<AuthorArea, string> = {
  code: "Code",
  license: "License",
  environment: "Environment",
  examples: "Examples",
  data: "Data",
  claims: "The paper's numbers",
  steps: "Steps",
};

// The part of the agent's page that runs a step that was not run
const STEP_PARTS: Record<AuthorUnchecked["id"], string> = {
  reading: "Reading",
  repository: "Code",
  environment: "Environment",
  reference: "Tutorials",
  reproduction: "Claims",
};

export function verdictVariant(verdict: AuthorVerdict): "default" | "secondary" | "destructive" | "outline" {
  if (verdict === "ready") return "default";
  if (verdict === "blocked") return "destructive";

  return verdict === "to_fix" ? "secondary" : "outline";
}

export function severityVariant(severity: AuthorSeverity): "secondary" | "destructive" | "outline" {
  if (severity === "block") return "destructive";

  return severity === "warn" ? "secondary" : "outline";
}

// How many findings there are of each severity, in words
export function describeCounts(counts: Record<AuthorSeverity, number>): string {
  return `${counts.block} would stop a reader, ${counts.warn} may, and ${counts.note} ${counts.note === 1 ? "is" : "are"} for them to know.`;
}

// The findings of each severity, the worst first, leaving out the severities that have none
export function bySeverity(findings: readonly AuthorFinding[]): { severity: AuthorSeverity; findings: AuthorFinding[] }[] {
  return SEVERITIES.map((severity) => ({ severity, findings: findings.filter((item) => item.severity === severity) })).filter(
    (group) => group.findings.length > 0,
  );
}

// A step that was not run, and where on the page it is run
export function describeUnchecked(item: AuthorUnchecked): string {
  return `${item.title}. It is run in the ${STEP_PARTS[item.id]} part of this page.`;
}

export const authorPackageAddress = (id: string) => `/api/paperagents/${encodeURIComponent(id)}/author/package`;

export function describeFile(file: { name: string; bytes: number }): string {
  return `${file.name}, ${formatBytes(file.bytes)}`;
}

// What the package carries of the tools, and why it would not
export function describeCarried(view: PaperAgentAuthor): string {
  if (view.package.carries_tools) return "It carries the package of the tools, under mcp/.";

  return `It does not carry a package of the tools: none was made of what is kept now, or the one that was is larger than ${formatBytes(view.limits.most_carried_package_bytes)}. One is made in the Package part of this page.`;
}

// Why there is no package for the authors yet
export function whyNoAuthorPackage(view: PaperAgentAuthor): string | null {
  if (view.package.ready) return null;

  return view.verdict === "not_checked" ? "Fetch the code first: until it is, nothing is known of what a reader would hit." : "There is nothing to put in a package yet.";
}

// What the page has of the parts that what a reader would hit is made of, as text, so that it is looked at again when that changes
// and not each time a part is looked at again and found the same. It is nothing while a part is still being looked at for the
// first time; a part that could not be looked at counts as that.
export function partsSignature(parts: readonly Loaded<unknown>[]): string | null {
  if (parts.some((part) => part.kind === "loading")) return null;

  return JSON.stringify(parts.map((part) => (part.kind === "ready" ? part.value : null)));
}
