import { count, dollars, type Checked } from "./checks";
import { formatCost, timeAgo } from "./format";
import type {
  ClaimLink,
  ClaimOutcome,
  ClaimStatus,
  DivergenceClaim,
  DivergenceDifference,
  DivergenceSoftware,
  PaperAgentClaims,
  PaperAgentReproduction,
  PaperAgentReproductionOptions,
} from "./types";

export interface ClaimsDraft {
  // The most that asking a model may spend, which must be said
  budget: string;
}

type ClaimsKey = "budget";

export function emptyClaims(): ClaimsDraft {
  return { budget: "" };
}

// What trying the claims is asked for: the most that the model that says which place a sentence is about may spend
export function checkClaims(draft: ClaimsDraft): Checked<PaperAgentReproductionOptions, ClaimsKey> {
  const said = dollars(draft.budget, "the most it may spend", false);
  if (said.problem || said.value === null) return { value: null, problems: { budget: said.problem ?? "Say the most it may spend." } };

  return { value: { max_cost: said.value }, problems: {} };
}

// In the order that they are told of
export const STATUSES: readonly ClaimStatus[] = ["reproduced", "partly", "not_reproduced", "not_attempted", "stale"];

export const STATUS_TITLES: Record<ClaimStatus, string> = {
  reproduced: "Reproduced",
  partly: "Partly reproduced",
  not_reproduced: "Not reproduced",
  not_attempted: "Not attempted",
  stale: "Stale",
};

export function statusTitle(status: string): string {
  return STATUS_TITLES[status as ClaimStatus] ?? status;
}

// A claim's status in words, and for one that is stale what it was, so that it is not taken for what is kept now
export function claimStatusTitle(claim: Pick<ClaimOutcome, "status" | "was">): string {
  if (claim.status === "stale" && claim.was) return `Stale (was ${statusTitle(claim.was)})`;

  return statusTitle(claim.status);
}

// How many claims came out each way, in a line, and how many there are that were not listed
export function describeCounts(counts: Record<ClaimStatus, number>, more: number): string {
  const total = STATUSES.reduce((sum, status) => sum + (counts[status] ?? 0), 0);
  const parts = STATUSES.filter((status) => (counts[status] ?? 0) > 0).map((status) => `${counts[status]} ${statusTitle(status).toLowerCase()}`);
  const said = total === 0 ? "No claim of the paper is listed." : `${count(total, "claim")}: ${parts.join(", ")}.`;

  return more > 0 ? `${said} ${count(more, "claim")} more come after the ${total} that are listed, and are not tried.` : said;
}

// What trying the claims cost and how it ended, in a line
export function describeKept(kept: NonNullable<PaperAgentReproduction["kept"]>): string {
  const when = timeAgo(kept.finished_at ?? kept.started_at) || "a while ago";
  const spent = kept.cost === null ? "" : `, which cost ${formatCost(kept.cost)}`;
  const model = kept.requests === 0 ? "No model was asked" : `${kept.model} was asked ${count(kept.requests, "time")}${spent}`;

  return `Tried ${when}. ${model}.${kept.complete ? "" : " It did not come to its end."}`;
}

// How a place was found, in words
export function describeBasis(link: Pick<ClaimLink, "basis" | "figures">): string {
  const figures = link.figures.join(", ");
  if (link.basis === "both") return `It was found because a result rounds to the paper's number, and because the sentence and the tutorial both refer to ${figures}.`;
  if (link.basis === "figure") return `It was found because the sentence and the tutorial both refer to ${figures}. No result there rounds to the paper's number.`;

  return "It was found because a result rounds to the paper's number.";
}

// Whether the runs of a tutorial agreed, in words
export function describeRuns(tutorial: Pick<ClaimLink["tutorial"], "runs" | "stable">): string {
  if (tutorial.stable === true) return `The ${tutorial.runs} runs of the tutorial agreed.`;
  if (tutorial.stable === false) return "The runs of the tutorial did not agree with each other, so it may not give this again.";
  if (tutorial.runs <= 1) return "The tutorial was run once, so its runs were not compared.";

  return "The runs of the tutorial could not be compared.";
}

// What a claim was held to, one part to a line: the place, what it gave and what the paper reports, how it was found, who chose it, and
// whether the runs agreed
export function describeLink(link: ClaimLink): string[] {
  const lines = [
    `Held to ${link.where} in ${link.tutorial.path}.`,
    `It gave ${link.got}, and the paper reports ${link.number.text}.`,
    describeBasis(link),
    `${link.chosen_by} chose this place from the words alone, without being shown any value. A program held it to the number.`,
    describeRuns(link.tutorial),
  ];
  if (link.others.length > 0) {
    lines.push(`Other places hold the number too: ${link.others.map((each) => `${each.where} in ${each.tutorial}`).join("; ")}.`);
  }

  return lines;
}

export const KIND_TITLES: Record<DivergenceDifference["kind"], string> = {
  python: "Python",
  package: "Package",
  data: "Data",
  runs: "Runs",
  seed: "Seed",
  argument: "Argument",
};

export function differenceKind(kind: string): string {
  return KIND_TITLES[kind as DivergenceDifference["kind"]] ?? kind;
}

const SOFTWARE_STATES: Record<DivergenceSoftware["state"], string> = {
  same: "the same version",
  differs: "another version",
  no_version: "the paper gives no version",
  not_comparable: "versions that cannot be compared",
  not_installed: "not installed",
};

// Software that the paper names, as it stands against what is installed
export function describeSoftware(software: DivergenceSoftware): string {
  const installed = software.installed === null ? "none installed" : `installed: ${software.installed}`;

  return `${software.name}: the paper says ${software.paper || "no version"}, ${installed} (${SOFTWARE_STATES[software.state] ?? software.state}).`;
}

// Where the trying of the claims first parts from the paper is only said of a trying that is of what is kept now
export function divergenceOf(claims: PaperAgentClaims, id: string): DivergenceClaim | undefined {
  if (!claims.reproduction.current || !claims.divergence.current) return undefined;

  return claims.divergence.claims.find((each) => each.id === id);
}

// Which claims are shown: all of them, or those that came out one way
export type ClaimFilter = "all" | ClaimStatus;

export function filterClaims(claims: readonly ClaimOutcome[], filter: ClaimFilter): ClaimOutcome[] {
  return filter === "all" ? [...claims] : claims.filter((claim) => claim.status === filter);
}

// The ways that claims are told apart by, which are those that at least one came out
export function filtersOf(counts: Record<ClaimStatus, number>): ClaimFilter[] {
  return ["all", ...STATUSES.filter((status) => (counts[status] ?? 0) > 0)];
}

// What a person is told of a claim that is stale: that it was tried, and for what it is not
export function describeStale(claim: Pick<ClaimOutcome, "status" | "was">): string | null {
  if (claim.status !== "stale") return null;
  const was = claim.was ? ` It was ${statusTitle(claim.was).toLowerCase()} when it was tried.` : "";

  return `It was tried against another run of the tutorials, or other claims, than are kept now, so what came of it is not shown.${was} Try the claims again.`;
}
