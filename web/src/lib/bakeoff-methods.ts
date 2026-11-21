import { BAKEOFF_JOBS } from "./bakeoffs";
import { characters, count, sentence, type Checked } from "./checks";
import { formatCost } from "./format";
import { doiOf, isLink, repoProblem } from "./paperagents";
import { tidy } from "./scientists";
import { isActive } from "./setup";
import type {
  BakeoffDropped,
  BakeoffFound,
  BakeoffLimits,
  BakeoffMethod,
  BakeoffMethodChange,
  BakeoffPaper,
  BakeoffScope,
  BakeoffShortlist,
  BakeoffState,
  BakeoffStanding,
  Job,
  NewBakeoffMethod,
  ScopeView,
} from "./types";

// The latest job on a bake-off's methods that is over, which is how finding, building, or running them was last ended. If kinds are
// given, it is the latest of one of those.
export function lastBakeoffJob(jobs: readonly Job[] | null, id: string, kinds: readonly string[] = BAKEOFF_JOBS): Job | undefined {
  return (jobs ?? []).find((job) => !isActive(job) && kinds.includes(job.kind) && job.subject === id);
}

// What the paper of a method is, in the words a person gave it: its DOI, or its link
export function describeMethodPaper(paper: BakeoffPaper): string {
  return paper.kind === "doi" ? `DOI ${paper.doi}` : paper.url;
}

// Where a person can read about a method's paper
export function methodPaperLink(paper: BakeoffPaper): string {
  return paper.kind === "doi" ? `https://doi.org/${paper.doi}` : paper.url;
}

// What a person typed of a method that they add: its paper, what it is called, and where its code is
export interface MethodDraft {
  paper: string;
  name: string;
  repo: string;
}

export const EMPTY_METHOD: MethodDraft = { paper: "", name: "", repo: "" };

export type MethodKey = keyof MethodDraft;

const DOI_ORG = /^https?:\/\/(?:dx\.)?doi\.org(?:[/?#:]|$)/i;

// A name as it is typed, which may be left blank where the server gives the method the name of its paper: the problem with it, or null
function nameProblem(name: string, most: number): string | null {
  return characters(name) > most ? `A method's name is at most ${most} characters, and this is ${characters(name)}.` : null;
}

// What is sent to put a method in the running, of what was typed, or what is wrong with it. A paper is given by its DOI, or by the
// link to it, as the server keeps a link to doi.org as the DOI in it.
export function checkMethod(draft: MethodDraft, limits: Pick<BakeoffLimits, "max_name_chars">): Checked<NewBakeoffMethod, MethodKey> {
  const problems: Partial<Record<MethodKey, string>> = {};
  const typed = draft.paper.trim();
  const doi = doiOf(typed);
  let paper: BakeoffPaper = { kind: "doi", doi: doi ?? typed };
  if (doi === null) {
    if (typed === "") problems.paper = "Give the DOI of its paper, such as 10.1038/s41586-020-2649-2, or a link to it.";
    else if (!isLink(typed)) problems.paper = "Give a DOI, such as 10.1038/s41586-020-2649-2, or a link, which begins with http:// or https://.";
    else if (DOI_ORG.test(typed)) problems.paper = "That link is to doi.org but has no DOI in it, such as 10.1038/s41586-020-2649-2.";
    paper = { kind: "url", url: typed };
  }
  const name = tidy(draft.name);
  const wrongName = nameProblem(name, limits.max_name_chars);
  if (wrongName !== null) problems.name = wrongName;
  const wrongRepo = repoProblem(draft.repo);
  if (wrongRepo !== null) problems.repo = wrongRepo;
  if (Object.keys(problems).length > 0) return { value: null, problems };
  const repo = draft.repo.trim();

  return { value: { paper, ...(name !== "" ? { name } : {}), ...(repo !== "" ? { repo } : {}) }, problems: {} };
}

// What a method is now, as a person is shown it to change: its name and where its code is
export function methodDraftOf(method: BakeoffMethod): Pick<MethodDraft, "name" | "repo"> {
  return { name: method.name, repo: method.repo ?? "" };
}

// What to say again of a method, of what was typed, or what is wrong with it. Only what differs from what the method is now is said,
// and taking the code away is saying an empty address. Nothing that differs is an empty change.
export function checkMethodChange(
  draft: Pick<MethodDraft, "name" | "repo">,
  was: BakeoffMethod,
  limits: Pick<BakeoffLimits, "max_name_chars">,
): Checked<BakeoffMethodChange, "name" | "repo"> {
  const problems: Partial<Record<"name" | "repo", string>> = {};
  const name = tidy(draft.name);
  if (name === "") problems.name = "Say what it is called.";
  else {
    const wrong = nameProblem(name, limits.max_name_chars);
    if (wrong !== null) problems.name = wrong;
  }
  const wrongRepo = repoProblem(draft.repo);
  if (wrongRepo !== null) problems.repo = wrongRepo;
  if (Object.keys(problems).length > 0) return { value: null, problems };
  const repo = draft.repo.trim();
  const change: BakeoffMethodChange = {};
  if (name !== was.name) change.name = name;
  if (repo !== (was.repo ?? "")) change.repo = repo;

  return { value: change, problems: {} };
}

// The words of what a step is, where a method stood in the way at one or is at it
const STEP_WORDS: Record<string, string> = {
  agent: "finding its PaperAgent",
  code: "fetching its code",
  paper: "reading its paper",
  preflight: "looking at its code",
  environment: "building its environment",
  tutorials: "running its tutorials",
  tools: "making its tools",
};

// What a step is, in words, or the step as the server named it if it is not one that is known
export function describeStep(step: string): string {
  return STEP_WORDS[step] ?? step;
}

export const STANDING_LABELS: Record<BakeoffState, string> = {
  new: "Not built",
  building: "Being built",
  built: "Built",
  waiting: "Waiting for you",
  blocked: "Cannot be built",
  failed: "Went wrong",
  pending: "Not got to",
};

// What a method's standing is called, and where it was at, if it was at a step
export function describeStanding(standing: BakeoffStanding): { label: string; step: string | null } {
  return { label: STANDING_LABELS[standing.state], step: standing.step !== null ? sentence(describeStep(standing.step)) : null };
}

// Whether a method may be built, which is if it is not built already and is not being built
export function isBuildable(method: Pick<BakeoffMethod, "standing">): boolean {
  return method.standing.state !== "built" && method.standing.state !== "building";
}

// How many of the methods may be built
export function buildableCount(methods: readonly Pick<BakeoffMethod, "standing">[]): number {
  return methods.filter(isBuildable).length;
}

// What the button that builds the methods that are not built says
export function describeBuildAll(buildable: number, total: number): string {
  if (buildable === 0) return "All are built";
  if (buildable === total) return total === 1 ? "Build it" : "Build all";

  return buildable === 1 ? "Build the one that is not built" : `Build the ${buildable} that are not built`;
}

// Whether looking at a method's code found things to ask the person about, which they say to go on with and it is built
export function isAsking(method: Pick<BakeoffMethod, "standing">): boolean {
  return method.standing.state === "waiting" && method.standing.why === "ask";
}

// The addresses that the abstract of a method's paper points to, which are not its code until the person says so, and are only offered
// while they have not said where it is
export function pointedTo(method: Pick<BakeoffMethod, "repo" | "suggested">): string[] {
  return method.repo === null ? method.suggested : [];
}

// What a method's data was put against its card as, if it was, in the form that an answer of a scope check is shown in
export function scopeViewOf(scope: BakeoffScope): ScopeView | null {
  if (!scope.checked || scope.outcome === null || scope.card === null || scope.reading === null) return null;

  return {
    outcome: scope.outcome,
    aspects: scope.of,
    warnings: scope.warnings,
    not_checked: scope.not_checked,
    card: scope.card,
    reading: scope.reading,
    notes: scope.notes,
  };
}

// Whether the person may go on with a method whose card the data is outside of: it is outside, and they have not said so already
export function canGoOn(scope: BakeoffScope): boolean {
  return scope.checked && scope.outcome === "outside" && scope.key !== null && !scope.went_on;
}

// Where a method was found and how it stands there, in a line: the service, the journal and year, how often it is cited, and whether it
// is a preprint
export function describeFound(found: BakeoffFound): string {
  const service = found.source === "arxiv" ? "arXiv" : found.source === "europepmc" ? "Europe PMC" : found.source;
  const where = [found.venue, found.year !== null ? String(found.year) : ""].filter((part) => part !== "").join(", ");
  const parts = [
    service,
    ...(where !== "" ? [where] : []),
    ...(found.cited_by > 0 ? [`cited ${count(found.cited_by, "time")}`] : []),
    ...(found.preprint ? ["a preprint, which has not been peer reviewed unless it says it was published"] : []),
  ];

  return parts.join(", ");
}

// Whether reading the paper of a method is likely to fail for want of its text, which is said of a paper that Europe PMC does not hold
// the full text of. Nothing is said of the others, which may not be.
export function describeFullText(found: BakeoffFound): string | null {
  return found.full_text === false ? "Europe PMC does not hold its full text, which reading it needs, so it may not be able to be built." : null;
}

// The words of a search, as the server keeps them: letters and digits, with a hyphen between those of one word, and none of what a
// search service reads as its own syntax
const SEARCH_WORD = /[\p{L}\p{N}]+(?:-[\p{L}\p{N}]+)*/gu;
const SEARCH_OPERATORS = new Set(["and", "or", "not", "andnot"]);
// What the server keeps of a search: its first words, as long as it is
export const MAX_SEARCH_WORDS = 8;
export const MAX_SEARCH_CHARS = 100;
// How long one that is typed may be, which the server refuses beyond
export const MAX_SEARCH_TYPED = 400;
// How many it takes of those that are sent, at most
export const MAX_SEARCHES_SENT = 20;

// A search as the server makes it, which is only words to look for
export function plainSearch(text: string): string {
  const words = (text.match(SEARCH_WORD) ?? []).filter((word) => !SEARCH_OPERATORS.has(word.toLowerCase())).slice(0, MAX_SEARCH_WORDS);

  return [...words.join(" ")].slice(0, MAX_SEARCH_CHARS).join("").trim();
}

// The searches that a person typed, a line for each, or what is wrong with them. Nothing typed is nothing sent, and a model writes
// them. What is sent is each as the server makes it, once, so that what is shown is what is searched for.
export function checkSearches(text: string, limits: Pick<BakeoffLimits, "max_queries">): Checked<string[] | null, "searches"> {
  const lines = text
    .split(/\r?\n/)
    .map((line) => tidy(line))
    .filter((line) => line !== "");
  if (lines.length === 0) return { value: null, problems: {} };
  const long = lines.find((line) => characters(line) > MAX_SEARCH_TYPED);
  if (long !== undefined) return { value: null, problems: { searches: `A search is short, at most ${MAX_SEARCH_TYPED} characters.` } };
  const made: string[] = [];
  for (const line of lines) {
    const plain = plainSearch(line);
    if (plain === "") {
      return { value: null, problems: { searches: `"${line}" has no word to look for. A search is words, not AND, OR, NOT, or marks.` } };
    }
    if (!made.some((each) => each.toLowerCase() === plain.toLowerCase())) made.push(plain);
  }
  if (made.length > limits.max_queries) {
    return { value: null, problems: { searches: `At most ${limits.max_queries === 1 ? "one search" : `${limits.max_queries} searches`}, a line for each, and these are ${made.length}.` } };
  }

  return { value: made, problems: {} };
}

// Why choices that the model made were thrown away, as each is said, for those that there were
export function describeDropped(dropped: BakeoffDropped): string[] {
  const parts: [keyof BakeoffDropped, (number: number) => string][] = [
    ["not_shown", (number) => `${count(number, "choice")} of a paper that it was not shown`],
    ["twice", (number) => `${count(number, "choice")} of a paper it had chosen already`],
    ["quote", (number) => `${count(number, "choice")} whose quoted words are not in the abstract`],
    ["more", (number) => `${count(number, "choice")} beyond the most it may choose`],
    ["already", (number) => `${count(number, "method")} already in the running`],
    ["no_room", (number) => `${count(number, "method")} for which there was no room`],
  ];

  return parts.filter(([key]) => dropped[key] > 0).map(([key, say]) => say(dropped[key]));
}

// What finding methods came to, in the lines that say it: who wrote the searches, what they found, what was chosen and added, what was
// thrown away, and what it cost
export function describeShortlist(shortlist: BakeoffShortlist): string[] {
  const lines = [
    shortlist.written_by === "person" ? "The searches were yours." : `The searches were written by ${shortlist.model}.`,
    `${count(shortlist.found, "paper")} ${shortlist.found === 1 ? "was" : "were"} shown to ${shortlist.model}${shortlist.total > shortlist.found ? `, of the ${shortlist.total} that the searches found` : ""}.`,
    `${shortlist.chosen} chosen, ${shortlist.added} added to the methods.`,
  ];
  const dropped = describeDropped(shortlist.dropped);
  if (dropped.length > 0) lines.push(`Thrown away: ${dropped.join("; ")}.`);
  if (shortlist.note !== null) lines.push(shortlist.note);
  lines.push(`It spent ${formatCost(shortlist.cost)}.`);

  return lines;
}
