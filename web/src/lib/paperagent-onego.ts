import { count, dollars, type Checked } from "./checks";
import { formatCost } from "./format";
import { REPO_HOSTS, repoProblem } from "./paperagents";
import type {
  OneGoCandidate,
  OneGoSettings,
  OneGoState,
  OneGoStepName,
  OneGoStepState,
  OneGoStuck,
  PaperAgent,
  PaperAgentMakeOptions,
  PaperAgentOneGo,
  PreflightStatus,
  PreflightVerdict,
} from "./types";

export const ONEGO_STATE_LABELS: Record<OneGoState, string> = {
  none: "Not asked for",
  running: "Going on",
  waiting: "Waiting for you",
  done: "Done",
  failed: "Failed",
  stopped: "Stopped",
  interrupted: "Interrupted",
};

export const ONEGO_STEP_LABELS: Record<OneGoStepState, string> = {
  pending: "Not started",
  running: "Going on",
  done: "Done",
  skipped: "Skipped",
  waiting: "Waiting for you",
  failed: "Failed",
  stopped: "Stopped",
};

// The steps that are of the code, which going on without it leaves out
const CODE_STEPS: readonly OneGoStepName[] = ["repository", "look", "environment", "reference", "tools", "checks"];

// What making an agent in one go is first asked for
export interface OneGoDraft {
  budget: string;
  repo: string;
  give: boolean;
  withoutCode: boolean;
}

// What is asked is what was asked the last time, as the server keeps it, and a dollar to read the paper when nothing was
export function emptyOneGo(settings: OneGoSettings): OneGoDraft {
  return {
    budget: settings.max_cost === null ? "1" : String(settings.max_cost),
    repo: settings.repo ?? "",
    give: settings.give,
    withoutCode: settings.without_code,
  };
}

// Whether the paper is still to be read, which is the only step that spends money, so the most it may spend is asked for
export function spends(agent: PaperAgent): boolean {
  return agent.steps.reading !== "done";
}

type OneGoKey = "budget" | "repo";

// What starting it is asked for. The most to spend is said only where the paper is to be read, and where the code is only where
// the agent does not say and it is not left out. What is left blank is asked of the person when the steps get to it.
export function checkOneGo(
  draft: OneGoDraft,
  { reads, asksRepo, hosts = REPO_HOSTS }: { reads: boolean; asksRepo: boolean; hosts?: readonly string[] },
): Checked<PaperAgentMakeOptions, OneGoKey> {
  const problems: Partial<Record<OneGoKey, string>> = {};
  const options: PaperAgentMakeOptions = { give: draft.give, without_code: draft.withoutCode };
  if (reads) {
    const budget = dollars(draft.budget, "the most reading the paper may spend", false);
    if (budget.problem || budget.value === null) problems.budget = budget.problem;
    else options.max_cost = budget.value;
  }
  const repo = draft.repo.trim();
  if (asksRepo && !draft.withoutCode && repo !== "") {
    const wrong = repoProblem(repo, hosts);
    if (wrong !== null) problems.repo = wrong;
    else options.repo = repo;
  }

  return Object.keys(problems).length > 0 ? { value: null, problems } : { value: options, problems };
}

// More to spend on reading, which is asked for when reading reached its limit, as an amount of its own
export function checkMore(text: string): Checked<PaperAgentMakeOptions, "budget"> {
  const budget = dollars(text, "how much more reading may spend", false);
  if (budget.problem || budget.value === null) return { value: null, problems: { budget: budget.problem } };

  return { value: { max_cost: budget.value }, problems: {} };
}

// What the person is asked, for what stands in the way, or what there is for them to do once it has ended
export type OneGoDecision =
  // Nothing has been asked for, so it can be started
  | { kind: "start" }
  // It is going, and there is nothing to say but stop it
  | { kind: "going" }
  // Where the code is, with the places that the paper points to, none of which is taken for it until the person says
  | { kind: "code"; candidates: OneGoCandidate[] }
  // Whether to go on with the code that was looked at, at the commit it was looked at
  | { kind: "preflight"; verdict: PreflightVerdict | null; commit: string | null; checks: { title: string; status: PreflightStatus; detail: string }[] }
  // How much more reading may spend
  | { kind: "limit"; spent: number | null; limit: number | null }
  // The paper's file, which is uploaded on this page
  | { kind: "paper" }
  // Something on this machine to put right, or a step to ask for again, which is done by going on
  | { kind: "again"; label: string }
  // Every step has been got to
  | { kind: "over" };

// What the person is asked of how making the agent in one go stands
export function decisionOf(view: PaperAgentOneGo): OneGoDecision {
  if (view.state === "running") return { kind: "going" };
  if (view.state === "none") return { kind: "start" };
  if (view.state === "done") return { kind: "over" };
  const stuck = view.stuck;
  if (view.state === "waiting" && stuck !== null) {
    if (stuck.kind === "code") return { kind: "code", candidates: stuck.candidates ?? [] };
    if (stuck.kind === "preflight") {
      return { kind: "preflight", verdict: stuck.verdict ?? null, commit: stuck.commit ?? null, checks: stuck.checks ?? [] };
    }
    if (stuck.kind === "limit") return { kind: "limit", spent: stuck.spent ?? null, limit: stuck.limit ?? null };
    if (stuck.kind === "paper_file" || stuck.kind === "paper_text") return { kind: "paper" };
  }

  return { kind: "again", label: view.state === "failed" ? "Try again" : "Go on" };
}

// Whether going on without the code is offered: where the code is what stands in the way, and not once it has been left out
export function offersWithoutCode(view: PaperAgentOneGo): boolean {
  const stuck: OneGoStuck | null = view.stuck;
  if (view.settings.without_code || stuck === null || view.state === "done" || view.state === "running" || view.state === "none") return false;

  return CODE_STEPS.includes(stuck.step) && stuck.kind !== "stopped";
}

// How far it has got, in a few words: the steps that are over, of how many, and those that were skipped
export function describeOneGo(view: PaperAgentOneGo): string {
  const over = view.steps.filter((step) => step.state === "done" || step.state === "skipped").length;
  const skipped = view.steps.filter((step) => step.state === "skipped").length;

  return `${over} of ${count(view.steps.length, "step")} over${skipped > 0 ? `, of which ${skipped} skipped` : ""}`;
}

// What reading spent and may spend, in a few words, for asking for more
export function describeLimit(spent: number | null, limit: number | null): string | null {
  if (spent === null) return limit === null ? null : `It was given ${formatCost(limit)}.`;

  return `It spent ${formatCost(spent)}${limit === null ? "" : ` of the ${formatCost(limit)} it was given`}.`;
}
