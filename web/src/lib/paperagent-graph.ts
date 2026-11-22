// The graph of how the papers of the agents relate: what is said of each kind of relation, of what it is found from, and of the
// papers that are in it, and where each paper is put in the picture of it

import type { GraphClaimStatus as ClaimStatus, GraphBy, GraphEvidence, GraphHow, GraphKind, GraphPaper, GraphPlace, GraphQuery, GraphRelation, PaperAgentGraph } from "./types";

export const GRAPH_ADDRESS = "/papers?view=graph";

// The graph with only the relations that an agent is in
export const graphAddress = (id: string) => `${GRAPH_ADDRESS}&of=${encodeURIComponent(id)}`;

export const KIND_TITLES: Record<GraphKind, string> = {
  refers: "Names the other",
  code: "Same code",
  dataset: "Same dataset",
  software: "Same software",
  method: "Same method",
  agrees: "Claims that agree",
  differs: "Claims that differ",
};

export const KIND_HINTS: Record<GraphKind, string> = {
  refers: "One paper's words name the other, by its DOI, the address of its code, its name, or its title.",
  code: "Their code is at the same address.",
  dataset: "Both used a dataset, by the same accession or the same name.",
  software: "Both name the same software.",
  method: "Both name the same method.",
  agrees: "Their claims have the same words and a number in common.",
  differs: "Their claims have the same words and no number in common.",
};

// The colour of a kind's lines in the picture, which is told apart by the legend and not by the colour alone
export const KIND_STROKES: Record<GraphKind, string> = {
  refers: "stroke-sky-500",
  code: "stroke-violet-500",
  dataset: "stroke-emerald-500",
  software: "stroke-amber-500",
  method: "stroke-teal-500",
  agrees: "stroke-lime-500",
  differs: "stroke-rose-500",
};

export const KIND_SWATCHES: Record<GraphKind, string> = {
  refers: "bg-sky-500",
  code: "bg-violet-500",
  dataset: "bg-emerald-500",
  software: "bg-amber-500",
  method: "bg-teal-500",
  agrees: "bg-lime-500",
  differs: "bg-rose-500",
};

const HOW_WORDS: Record<GraphHow, string> = {
  mentions: "names",
  builds_on: "says it builds on",
  replaces: "says it replaces or improves on",
  replicates: "says it replicates",
};

const BY_WORDS: Record<GraphBy, string> = {
  doi: "its DOI",
  code: "the address of its code",
  name: "the name of its code",
  title: "its title",
};

const STATUS_WORDS: Record<ClaimStatus, string> = {
  reproduced: "reproduced",
  partly: "partly reproduced",
  not_reproduced: "not reproduced",
  not_attempted: "not tried",
};

const FACT_WORDS: Record<string, [string, string]> = {
  methods: ["method", "methods"],
  datasets: ["dataset", "datasets"],
  software: ["piece of software", "pieces of software"],
};

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

// Whether the graph was asked for only some of its relations, so that none being shown says nothing of the rest
export function isNarrowed(query: GraphQuery): boolean {
  return Boolean(query.agent || query.kind || query.about?.trim());
}

// How many relations are shown, between how many papers
export function describeShown(graph: PaperAgentGraph): string {
  const total = graph.relations.length;
  if (total === 0) return "No relations";
  const papers = new Set(graph.relations.flatMap((each) => [each.a, each.b])).size;

  return `${plural(total, "relation", "relations")} between ${plural(papers, "paper", "papers")}`;
}

// What was not put in the graph: papers past the most that are put against each other, and relations past the most that are kept
export function describeLimits(graph: PaperAgentGraph): string[] {
  const said: string[] = [];
  if (graph.left_out > 0) {
    said.push(
      `Only the first ${graph.limits.most_papers} agents are put against each other, so ${plural(graph.left_out, "agent was", "agents were")} left out.`,
    );
  }
  if (graph.truncated) said.push(`Only the first ${graph.limits.most_relations} relations are kept, and there were more.`);

  return said;
}

// What was read of a paper that it can be related by
export function describeGraphPaper(paper: GraphPaper): string {
  if (!paper.read) return paper.code !== null ? "Not read, so only its code can relate it to the others." : "Not read, and it has no code, so nothing relates it.";
  const facts = Object.entries(FACT_WORDS)
    .map(([kind, [one, many]]) => plural(paper.facts[kind] ?? 0, one, many))
    .join(", ");

  return `Read: ${plural(paper.claims, "claim", "claims")}, ${facts}.`;
}

// What the trying of a paper's claims came to, if its code was held to them
export function describeReproduction(reproduction: GraphPaper["reproduction"]): string | null {
  if (reproduction === null) return null;
  const said = (Object.keys(STATUS_WORDS) as ClaimStatus[]).filter((status) => reproduction[status] > 0).map((status) => `${reproduction[status]} ${STATUS_WORDS[status]}`);

  return said.length === 0 ? null : `Of its claims that were tried: ${said.join(", ")}.`;
}

// How many relations a paper is in, and, if only some are shown, how many of those
export function describeRelationCount(count: number, shown: number | null = null): string {
  const all = count === 0 ? "In no relation" : `In ${plural(count, "relation", "relations")}`;

  return shown === null ? all : `${all}, ${shown} of them shown`;
}

// Where a place is in its paper
export function describeWhere(place: GraphPlace): string {
  const parts = [place.page !== null ? `page ${place.page}` : null, place.section ? place.section : null].filter((part) => part !== null);

  return parts.length === 0 ? "Where in the paper is not known" : parts.join(", ");
}

// How a paper names another, from the place it does
export function describeReference(evidence: GraphEvidence, from: string, to: string): string {
  const how = evidence.how !== undefined ? HOW_WORDS[evidence.how] : "names";
  const by = evidence.by !== undefined ? BY_WORDS[evidence.by] : "its name";

  return `${from} ${how} ${to}, by ${by}.`;
}

// Of code that is at the same address: whether it is at the same commit
export function describeCommits(evidence: GraphEvidence, titles: Record<string, string>): string {
  const commits = Object.entries(evidence.commits ?? {}).map(([id, commit]) => `${titles[id] ?? id} at ${commit !== null ? commit.slice(0, 7) : "a commit not fetched"}`);
  const same = evidence.same_commit === true ? "the same commit" : evidence.same_commit === false ? "different commits" : "commits that are not both known";

  return `${evidence.matched ?? "The same address"}, at ${same}${commits.length > 0 ? `: ${commits.join("; ")}` : ""}.`;
}

// Of software that both name: the version each says, and whether they are the same
export function describeVersions(evidence: GraphEvidence, titles: Record<string, string>): string | null {
  const versions = Object.entries(evidence.versions ?? {});
  if (versions.length === 0 || versions.every(([, version]) => version === null)) return null;
  const said = versions.map(([id, version]) => `${titles[id] ?? id} says ${version ?? "no version"}`).join("; ");
  const same = evidence.same_version === true ? "The same version" : evidence.same_version === false ? "Different versions" : "Versions not both said";

  return `${same}: ${said}.`;
}

// Of claims on the same words: the words and the numbers that they have in common
export function describeShared(evidence: GraphEvidence): string {
  const words = evidence.words ?? [];
  const numbers = evidence.numbers ?? [];
  const said = words.length > 0 ? `Words in common: ${words.join(", ")}.` : "";

  return numbers.length > 0 ? `${said} Numbers in common: ${numbers.join(", ")}.`.trim() : `${said} No number in common.`.trim();
}

export function describeClaimStatus(status: ClaimStatus | null | undefined): string | null {
  return status === null || status === undefined ? null : `Its code: ${STATUS_WORDS[status]}`;
}

// How a relation was found, beside what it says
export function describeBasis(relation: GraphRelation): string | null {
  if (relation.kind === "dataset") return relation.basis === "accession" ? "By the same accession" : "By the same name";
  if (relation.corroborated === true) return "Corroborated: the code of one of the papers gave the claim again";

  return null;
}

// Where each of the papers is put in the picture: around a circle, in the order they are given, the first at the top
export function circleLayout(ids: readonly string[], size: number, margin: number): Record<string, { x: number; y: number }> {
  const centre = size / 2;
  const radius = ids.length <= 1 ? 0 : centre - margin;
  const placed: Record<string, { x: number; y: number }> = {};
  ids.forEach((id, index) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * index) / ids.length;
    placed[id] = { x: Math.round((centre + radius * Math.cos(angle)) * 10) / 10, y: Math.round((centre + radius * Math.sin(angle)) * 10) / 10 };
  });

  return placed;
}

// The lines of the picture: one for each two papers and kind, however many relations of that kind there are between them, so that
// two kinds between the same papers are drawn apart, each a little to its side
export function linesOf(relations: readonly GraphRelation[]): { a: string; b: string; kind: GraphKind; offset: number }[] {
  const seen = new Map<string, GraphKind[]>();
  for (const each of relations) {
    const pair = [each.a, each.b].sort().join("\u0000");
    const kinds = seen.get(pair) ?? [];
    if (!kinds.includes(each.kind)) kinds.push(each.kind);
    seen.set(pair, kinds);
  }
  const lines: { a: string; b: string; kind: GraphKind; offset: number }[] = [];
  for (const [pair, kinds] of seen) {
    const [a, b] = pair.split("\u0000");
    kinds.forEach((kind, index) => lines.push({ a, b, kind, offset: index - (kinds.length - 1) / 2 }));
  }

  return lines;
}

// A paper's title as it is put under its point in the picture
export function shortTitle(title: string, most = 28): string {
  const text = title.trim();

  return text.length <= most ? text : `${text.slice(0, most - 1).trimEnd()}…`;
}
