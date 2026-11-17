import { characters, count, dollars, whole, type Checked } from "./checks";
import { formatCost, timeAgo } from "./format";
import type { CheckEvidence, CheckedTool, CheckKind, CheckStatus, PaperAgentChecks, PaperAgentChecksOptions } from "./types";

// The kinds of check that ask a model, which the server names, and the one that asks a model to choose inputs
const NUMBERS = "paper_numbers";
const VERIFIER = "verifier";
// The longest name of a model that the server takes
const MOST_MODEL_CHARS = 200;

export interface ChecksDraft {
  minutes: string;
  totalMinutes: string;
  repeats: string;
  gigabytes: string;
  // The kinds of check that are asked for
  kinds: string[];
  // The most that asking a model may spend, which is only asked for when a kind that asks a model is
  budget: string;
  // The model that chooses inputs, which is only asked for when that kind is
  verifier: string;
}

type ChecksKey = "minutes" | "totalMinutes" | "repeats" | "gigabytes" | "kinds" | "budget" | "verifier";

export function emptyChecks(checks: Pick<PaperAgentChecks, "limits" | "kinds">): ChecksDraft {
  return {
    minutes: String(checks.limits.default_minutes),
    totalMinutes: String(checks.limits.default_total_minutes),
    repeats: String(checks.limits.default_repeats),
    gigabytes: String(checks.limits.default_gigabytes),
    kinds: checks.kinds.filter((kind) => kind.default).map((kind) => kind.kind),
    budget: "",
    verifier: "",
  };
}

// Whether any of the kinds that are asked for asks a model, which costs what the model charges
export function asksModel(draft: Pick<ChecksDraft, "kinds">, kinds: readonly CheckKind[]): boolean {
  return kinds.some((kind) => kind.model && draft.kinds.includes(kind.kind));
}

// Why a kind of check cannot be asked for now, if it cannot: the paper has no number to look for, or it is not known whose model the one
// in the settings is, so that no other can be told to be of another family
export function whyNot(kind: string, checks: Pick<PaperAgentChecks, "numbers" | "settings_model" | "settings_family">): string | null {
  if (kind === NUMBERS && checks.numbers === 0) {
    return "The paper has no number that it reports with digits enough to be looked for. Read the paper first, if it has not been read.";
  }
  if (kind === VERIFIER && checks.settings_family === null) {
    return `It is not known whose model ${checks.settings_model} is, so no model can be told to be of another family. Choose a model whose name says whose it is in the settings.`;
  }

  return null;
}

// What checking is asked for: the most time for one check of one tool and for all of them, how many times each call is made, the most
// one run may write, which kinds, and, for those that ask a model, the most that may be spent, and the model that chooses inputs
export function checkChecks(draft: ChecksDraft, checks: PaperAgentChecks): Checked<PaperAgentChecksOptions, ChecksKey> {
  const { limits } = checks;
  const problems: Partial<Record<ChecksKey, string>> = {};
  const asked = (key: ChecksKey, text: string, what: string, least: number, most: number) => {
    const checked = whole(text, what, least, most);
    if (checked.problem) problems[key] = checked.problem;

    return checked.value;
  };
  const minutes = asked("minutes", draft.minutes, "The most time for one check of one tool, in minutes,", 1, limits.max_minutes);
  const totalMinutes = asked("totalMinutes", draft.totalMinutes, "The most time for all of the checks, in minutes,", 1, limits.max_total_minutes);
  const repeats = asked("repeats", draft.repeats, "How many times each call is made", 1, limits.max_repeats);
  const gigabytes = asked("gigabytes", draft.gigabytes, "The most one run may write, in gigabytes,", 1, limits.max_gigabytes);

  const chosen = checks.kinds.filter((kind) => draft.kinds.includes(kind.kind));
  if (chosen.length === 0) problems.kinds = "Choose at least one kind of check.";
  const blocked = chosen.map((kind) => whyNot(kind.kind, checks)).find((why) => why !== null);
  if (blocked) problems.kinds = blocked;
  const model = chosen.some((kind) => kind.model);
  let budget: number | null = null;
  if (model) {
    const said = dollars(draft.budget, "the most it may spend", false);
    if (said.problem) problems.budget = said.problem;
    budget = said.value;
  }
  const choosing = chosen.some((kind) => kind.kind === VERIFIER);
  const name = draft.verifier.trim();
  if (choosing) {
    if (name === "") problems.verifier = "Name the model that chooses the inputs, of another family than the one in the settings.";
    else if (characters(name) > MOST_MODEL_CHARS) problems.verifier = `A model's name is at most ${MOST_MODEL_CHARS} characters.`;
    else if (/[\u0000-\u001f\u007f]/.test(name)) problems.verifier = "A model's name has no control characters.";
    else if (name.toLowerCase() === checks.settings_model.toLowerCase()) {
      problems.verifier = `${name} is the model in the settings. Name one of another family, so that it does not see what that one does not.`;
    }
  }
  if (Object.keys(problems).length > 0) return { value: null, problems };
  if (minutes === null || totalMinutes === null || repeats === null || gigabytes === null) return { value: null, problems };
  if (model && budget === null) return { value: null, problems };

  return {
    value: {
      minutes,
      total_minutes: totalMinutes,
      repeats,
      gigabytes,
      kinds: chosen.map((kind) => kind.kind),
      ...(model && budget !== null ? { max_cost: budget } : {}),
      ...(choosing ? { verifier_model: name } : {}),
    },
    problems: {},
  };
}

export const STATUS_TITLES: Record<CheckStatus, string> = {
  passed: "Passed",
  failed: "Failed",
  not_obtained: "Not obtained",
  stale: "Stale",
  not_run: "Not run",
};

export function statusTitle(status: string): string {
  return STATUS_TITLES[status as CheckStatus] ?? status;
}

// How many kinds of check were made of a tool and passed, of how many there are
export function describePassed(tool: CheckedTool): string {
  return `${tool.passed.length} of ${count(tool.evidence.length, "kind")} of check passed`;
}

// What a basis is, from what the server says each is, or its own name if it is not one the page knows
export function describeBasis(basis: string, bases: Record<string, string>): string {
  return bases[basis] ?? basis;
}

// The tier of a tool and how it came to be, in a sentence: the tier it was made as, and what has been checked since
export function describeStanding(tool: CheckedTool, checks: Pick<PaperAgentChecks, "bases" | "bases_for_b">): string {
  const made = `Made as tier ${tool.made_as}.`;
  if (tool.evidence.some((entry) => entry.status === "failed")) {
    return `${made} A check failed, which keeps it from tier B until it is checked again and none fails.`;
  }
  const things = tool.bases.map((basis) => describeBasis(basis, checks.bases));
  if (tool.tier === "B") return `${made} It passed checks against ${things.length} different things: ${things.join("; ")}.`;
  if (things.length === 0) return `${made} No check of it has passed.`;

  return `${made} It passed checks against ${count(things.length, "thing")} (${things.join("; ")}), and tier B needs ${checks.bases_for_b} different.`;
}

// What a tool that is not yet of tier B would need, which is a check that passes against something it has not passed one against, with
// the kinds of check that are against each. It is nothing for a tool of tier B, or one that has a check that failed
export function describeNeeds(tool: CheckedTool, checks: Pick<PaperAgentChecks, "bases" | "kinds" | "bases_for_b">): string | null {
  if (tool.tier === "B" || tool.evidence.some((entry) => entry.status === "failed")) return null;
  const missing = Object.keys(checks.bases).filter((basis) => !tool.bases.includes(basis));
  const missed = checks.bases_for_b - tool.bases.length;
  if (missing.length === 0 || missed <= 0) return null;
  const ways = missing.map((basis) => {
    const titles = checks.kinds.filter((kind) => kind.basis === basis).map((kind) => kind.title);

    return `${describeBasis(basis, checks.bases)} (${titles.join(" or ")})`;
  });

  return `To be of tier B it needs a check that passes against ${missed === 1 ? "one more" : `${missed} more`} of: ${ways.join("; ")}. A second check against what it has passed one against does not count.`;
}

// When a check was made, in words, or that it was not
export function describeWhen(entry: Pick<CheckEvidence, "checked_at">): string {
  if (entry.checked_at === null) return "Not made";

  return `Made ${timeAgo(entry.checked_at) || "a while ago"}`;
}

// How many tools are of each tier now, in a line
export function describeTiers(tools: readonly CheckedTool[]): string {
  if (tools.length === 0) return "There are no tools.";
  const tiers = new Map<string, number>();
  for (const tool of tools) tiers.set(tool.tier, (tiers.get(tool.tier) ?? 0) + 1);
  const parts = [...tiers.entries()].sort(([one], [other]) => one.localeCompare(other)).map(([tier, many]) => `${many} of tier ${tier}`);

  return `${count(tools.length, "tool")}: ${parts.join(", ")}.`;
}

// Whether anything has been checked, which is whether there is something to take away
export function hasChecks(tools: readonly CheckedTool[]): boolean {
  return tools.some((tool) => tool.evidence.some((entry) => entry.file !== null));
}

// One part of what a check was made of: what it is, and its lines
export interface DetailSection {
  title: string;
  lines: string[];
  // Whose words the lines are, where they are not what a program found, so that they are not taken for it
  words?: string;
}

const SHOWN = 160;

function cut(text: string, limit = SHOWN): string {
  return text.length <= limit ? text : `${text.slice(0, limit)}…`;
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function integer(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

const CASE_VERDICTS: Record<string, string> = {
  agree: "the tool and the code's own function gave the same",
  same_error: "both stopped with the same error",
  differs: "they gave something else",
  unstable: "not compared, as the code's own function gave something else each time",
  not_run: "not made in the time",
};

const LINK_VERDICTS: Record<string, string> = {
  match: "the tool gave it every time",
  differs: "the tool gave another number, or none",
  error: "the tool stopped with an error",
  not_run: "the tool was not called every time",
};

// The arguments of a call, which the server keeps as the text that Python shows them as, cut where they are long
function shownArgs(value: unknown): string {
  return cut(text(value) ?? "");
}

// The calls that were changed, or proposed, and how each one went, from the tool and the code's own function
function callLines(cases: unknown[]): string[] {
  return cases.flatMap((each) => {
    const one = record(each);
    if (one === null) return [];
    const verdict = CASE_VERDICTS[text(one.verdict) ?? ""] ?? text(one.verdict) ?? "?";
    const difference = text(list(one.differences)[0]);
    const reason = text(one.reason);

    return [
      `${text(one.change) ?? "Changed"}: ${shownArgs(one.args)}: ${verdict}${difference ? `. ${cut(difference)}` : ""}${reason ? `. Its reason: ${cut(reason)}` : ""}`,
    ];
  });
}

// What each way that a call comes out says of the calls that came out that way, as it follows their number
const COUNT_PHRASES: Record<string, (many: number) => string> = {
  agree: () => "gave the same through the tool as from the code's own function",
  same_error: () => "stopped with the same error from both",
  differs: () => "gave something else through the tool than the code's own function did",
  unstable: (many) => `${many === 1 ? "was" : "were"} not compared, as the code's own function gave something else each time`,
  not_run: (many) => `${many === 1 ? "was" : "were"} not made in the time`,
};

// How many of the calls came out each way, in a line
function describeCounts(counts: Record<string, unknown>, repeats: number | null): string {
  const parts = Object.entries(COUNT_PHRASES).flatMap(([name, phrase]) => {
    const many = integer(counts[name]);

    return many !== null && many > 0 ? [`${count(many, "call")} ${phrase(many)}`] : [];
  });
  const each = repeats === null ? "" : ` Each call was made ${count(repeats, "time")}.`;

  return `${parts.length > 0 ? `${parts.join("; ")}.` : "No call was compared."}${each}`;
}

// Which model was asked, and what that cost, where it is known
function modelLines(details: Record<string, unknown>): string[] {
  const model = text(details.model);
  if (model === null) return [];
  const spent = integer(details.cost);

  return [`Asked ${model}, and ${spent === null ? "what it cost is not known" : `it cost ${formatCost(spent) || "nothing"}`}.`];
}

// What a check was made of, as lines under a heading each, from what the server keeps of it. What the page does not know how to read
// is left out, and what a model said is marked as its words
export function describeDetails(kind: string, details: unknown): DetailSection[] {
  const found = record(details);
  if (found === null) return [];
  const sections: DetailSection[] = [];
  if (kind === "heldout" || kind === "verifier") {
    if (kind === "verifier") {
      const proposed = integer(found.proposed);
      const usable = integer(found.usable);
      const lines = modelLines(found);
      if (proposed !== null && usable !== null) lines.push(`It proposed ${count(proposed, "input")}, and ${usable} could be run.`);
      if (lines.length > 0) sections.push({ title: "The model", lines });
      const refused = list(found.refused).flatMap((each) => {
        const one = record(each);

        return one === null ? [] : [`${cut(text(one.arguments) ?? "", 100)}: ${cut(text(one.why) ?? "", 200)}`];
      });
      if (refused.length > 0) sections.push({ title: "Proposed inputs that were not run", lines: refused });
    }
    const counts = record(found.counts);
    if (counts !== null) sections.push({ title: "How the calls went", lines: [describeCounts(counts, integer(found.repeats))] });
    const calls = callLines(list(found.cases));
    if (calls.length > 0) sections.push({ title: kind === "verifier" ? "Inputs the model proposed that were run" : "Calls that were changed", lines: calls });
    const gaps = list(found.gaps).flatMap((each) => (typeof each === "string" ? [cut(each, 300)] : []));
    if (gaps.length > 0) {
      sections.push({
        title: "Where the model thought the wrapper and the code might differ",
        lines: gaps,
        words: "These are the model's words. They are no part of how the check came out.",
      });
    }

    return sections;
  }
  if (kind === "repo_tests") {
    const tests = integer(found.tests);
    if (tests !== null) {
      sections.push({
        title: "How the tests went",
        lines: [
          `${count(tests, "test")} ran: ${integer(found.passed) ?? 0} passed, ${integer(found.failed) ?? 0} failed, ${integer(found.errors) ?? 0} stopped with an error, and ${integer(found.skipped) ?? 0} were skipped.`,
        ],
      });
    }
    const failures = list(found.failures).flatMap((each) => {
      const one = record(each);

      return one === null ? [] : [`${text(one.name) ?? "?"}: ${cut(text(one.message) ?? "", 200)}`];
    });
    if (failures.length > 0) sections.push({ title: "Tests that did not pass", lines: failures });
    const ids = list(found.ids).flatMap((each) => (typeof each === "string" ? [each] : []));
    if (ids.length > 0) sections.push({ title: "Tests that call the function", lines: ids });

    return sections;
  }
  if (kind === NUMBERS) {
    const numbers = integer(found.numbers);
    const looked = [
      numbers !== null ? `${count(numbers, "number")} of the paper had digits enough to be looked for.` : null,
      integer(found.candidates) !== null ? `${count(integer(found.candidates) ?? 0, "place")} in what the calls gave held one.` : null,
      integer(found.accepted) !== null ? `The model said that ${integer(found.accepted)} of them hold the quantity that the paper's sentence is about.` : null,
      ...modelLines(found),
    ].filter((line): line is string => line !== null);
    if (looked.length > 0) sections.push({ title: "What was looked for", lines: looked });
    const links = list(found.links).flatMap((each) => {
      const one = record(each);
      if (one === null) return [];
      const number = text(record(one.number)?.text) ?? "?";
      const verdict = LINK_VERDICTS[text(one.verdict) ?? ""] ?? text(one.verdict) ?? "?";

      return [`${number} at ${text(one.at) ?? "?"} (“${cut(text(one.quote) ?? "", 100)}”): ${verdict}`];
    });
    if (links.length > 0) sections.push({ title: "Where the paper's numbers were looked for in what the tool gave", lines: links });
  }

  return sections;
}
