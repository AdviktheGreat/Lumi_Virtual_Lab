import { describe, expect, it } from "vitest";
import { graphQuery } from "./api";
import {
  circleLayout,
  describeBasis,
  describeClaimStatus,
  describeCommits,
  describeGraphPaper,
  describeLimits,
  describeReference,
  describeRelationCount,
  describeReproduction,
  describeShared,
  describeShown,
  describeVersions,
  describeWhere,
  graphAddress,
  isNarrowed,
  linesOf,
  shortTitle,
} from "./paperagent-graph";
import type { GraphPaper, GraphPlace, GraphRelation, PaperAgentGraph } from "./types";

const relation = (part: Partial<GraphRelation>): GraphRelation => ({
  kind: "dataset",
  a: "one",
  b: "two",
  directed: false,
  how: null,
  basis: null,
  corroborated: null,
  summary: "",
  evidence: [],
  ...part,
});

const graph = (part: Partial<PaperAgentGraph>): PaperAgentGraph => ({
  papers: [],
  relations: [],
  counts: { refers: 0, code: 0, dataset: 0, software: 0, method: 0, agrees: 0, differs: 0 },
  truncated: false,
  left_out: 0,
  kinds: ["refers", "code", "dataset", "software", "method", "agrees", "differs"],
  meaning: "",
  limits: { most_papers: 40, most_relations: 400 },
  ...part,
});

const paper = (part: Partial<GraphPaper>): GraphPaper => ({
  id: "one",
  title: "One",
  read: true,
  code: null,
  claims: 0,
  facts: {},
  reproduction: null,
  relations: 0,
  ...part,
});

const place = (part: Partial<GraphPlace>): GraphPlace => ({ agent: "one", kind: "claims", fact: "c1", name: "", quote: "", page: null, section: null, ...part });

const titles = { one: "Paper one", two: "Paper two" };

describe("graphQuery", () => {
  it("leaves out what is not asked for, and words that are only spaces", () => {
    expect(graphQuery({})).toBe("");
    expect(graphQuery({ about: "   " })).toBe("");
    expect(graphQuery({ agent: "a b", kind: "code", about: "  GEO data " })).toBe("?agent=a+b&kind=code&about=GEO+data");
  });
});

describe("graphAddress", () => {
  it("is the graph of one agent", () => {
    expect(graphAddress("10-1/x y")).toBe("/papers?view=graph&of=10-1%2Fx%20y");
  });
});

describe("isNarrowed", () => {
  it("is whether any part is asked for", () => {
    expect(isNarrowed({})).toBe(false);
    expect(isNarrowed({ about: " " })).toBe(false);
    expect(isNarrowed({ agent: "one" })).toBe(true);
    expect(isNarrowed({ kind: "code" })).toBe(true);
    expect(isNarrowed({ about: "GEO" })).toBe(true);
  });
});

describe("describeShown", () => {
  it("counts the relations and the papers they are between", () => {
    expect(describeShown(graph({}))).toBe("No relations");
    expect(describeShown(graph({ relations: [relation({})] }))).toBe("1 relation between 2 papers");
    expect(describeShown(graph({ relations: [relation({}), relation({ a: "two", b: "three" }), relation({ kind: "code" })] }))).toBe(
      "3 relations between 3 papers",
    );
  });
});

describe("describeLimits", () => {
  it("says what was left out", () => {
    expect(describeLimits(graph({}))).toEqual([]);
    expect(describeLimits(graph({ left_out: 1 }))).toEqual(["Only the first 40 agents are put against each other, so 1 agent was left out."]);
    expect(describeLimits(graph({ left_out: 3, truncated: true }))).toEqual([
      "Only the first 40 agents are put against each other, so 3 agents were left out.",
      "Only the first 400 relations are kept, and there were more.",
    ]);
  });
});

describe("describeGraphPaper", () => {
  it("says what was read of a paper", () => {
    expect(describeGraphPaper(paper({ claims: 1, facts: { methods: 1, datasets: 2, software: 0, links: 4 } }))).toBe(
      "Read: 1 claim, 1 method, 2 datasets, 0 pieces of software.",
    );
    expect(describeGraphPaper(paper({ claims: 3, facts: { software: 1 } }))).toBe("Read: 3 claims, 0 methods, 0 datasets, 1 piece of software.");
  });

  it("says that a paper that was not read is related only by its code", () => {
    expect(describeGraphPaper(paper({ read: false, code: "https://github.com/a/b" }))).toBe("Not read, so only its code can relate it to the others.");
    expect(describeGraphPaper(paper({ read: false }))).toBe("Not read, and it has no code, so nothing relates it.");
  });
});

describe("describeReproduction", () => {
  it("says only the statuses that some claims have", () => {
    expect(describeReproduction(null)).toBeNull();
    expect(describeReproduction({ reproduced: 0, partly: 0, not_reproduced: 0, not_attempted: 0 })).toBeNull();
    expect(describeReproduction({ reproduced: 2, partly: 0, not_reproduced: 1, not_attempted: 3 })).toBe(
      "Of its claims that were tried: 2 reproduced, 1 not reproduced, 3 not tried.",
    );
    expect(describeReproduction({ reproduced: 0, partly: 1, not_reproduced: 0, not_attempted: 0 })).toBe("Of its claims that were tried: 1 partly reproduced.");
  });
});

describe("describeRelationCount", () => {
  it("counts", () => {
    expect(describeRelationCount(0)).toBe("In no relation");
    expect(describeRelationCount(1)).toBe("In 1 relation");
    expect(describeRelationCount(5)).toBe("In 5 relations");
    expect(describeRelationCount(5, 2)).toBe("In 5 relations, 2 of them shown");
    expect(describeRelationCount(1, 1)).toBe("In 1 relation, 1 of them shown");
    expect(describeRelationCount(1, null)).toBe("In 1 relation");
  });
});

describe("describeWhere", () => {
  it("says the page and the section that are known", () => {
    expect(describeWhere(place({ page: 3, section: "Methods" }))).toBe("page 3, Methods");
    expect(describeWhere(place({ page: 0 }))).toBe("page 0");
    expect(describeWhere(place({ section: "Results" }))).toBe("Results");
    expect(describeWhere(place({ section: "" }))).toBe("Where in the paper is not known");
  });
});

describe("describeReference", () => {
  it("says how one paper names the other, and by what", () => {
    expect(describeReference({ by: "code", how: "builds_on" }, "B", "A")).toBe("B says it builds on A, by the address of its code.");
    expect(describeReference({ by: "doi", how: "replicates" }, "B", "A")).toBe("B says it replicates A, by its DOI.");
    expect(describeReference({ by: "title", how: "replaces" }, "B", "A")).toBe("B says it replaces or improves on A, by its title.");
    expect(describeReference({ by: "name", how: "mentions" }, "B", "A")).toBe("B names A, by the name of its code.");
    expect(describeReference({}, "B", "A")).toBe("B names A, by its name.");
  });
});

describe("describeCommits", () => {
  it("says whether code at one address is at one commit", () => {
    expect(describeCommits({ matched: "github.com/a/b", commits: { one: "0123456789abc", two: "0123456789abc" }, same_commit: true }, titles)).toBe(
      "github.com/a/b, at the same commit: Paper one at 0123456; Paper two at 0123456.",
    );
    expect(describeCommits({ matched: "github.com/a/b", commits: { one: "aaaaaaaaa", three: null }, same_commit: null }, titles)).toBe(
      "github.com/a/b, at commits that are not both known: Paper one at aaaaaaa; three at a commit not fetched.",
    );
    expect(describeCommits({ same_commit: false }, titles)).toBe("The same address, at different commits.");
  });
});

describe("describeVersions", () => {
  it("says the version each paper says of software", () => {
    expect(describeVersions({}, titles)).toBeNull();
    expect(describeVersions({ versions: { one: null, two: null } }, titles)).toBeNull();
    expect(describeVersions({ versions: { one: "4.3", two: "4.3" }, same_version: true }, titles)).toBe("The same version: Paper one says 4.3; Paper two says 4.3.");
    expect(describeVersions({ versions: { one: "4.3", two: "5.0" }, same_version: false }, titles)).toBe(
      "Different versions: Paper one says 4.3; Paper two says 5.0.",
    );
    expect(describeVersions({ versions: { one: "4.3", two: null }, same_version: null }, titles)).toBe(
      "Versions not both said: Paper one says 4.3; Paper two says no version.",
    );
  });
});

describe("describeShared", () => {
  it("says the words and numbers two claims have in common", () => {
    expect(describeShared({ words: ["auroc", "cells"], numbers: ["0.91"] })).toBe("Words in common: auroc, cells. Numbers in common: 0.91.");
    expect(describeShared({ words: ["auroc"], numbers: [] })).toBe("Words in common: auroc. No number in common.");
    expect(describeShared({})).toBe("No number in common.");
  });
});

describe("describeClaimStatus", () => {
  it("says what the paper's code gave of a claim, if it was tried", () => {
    expect(describeClaimStatus(undefined)).toBeNull();
    expect(describeClaimStatus(null)).toBeNull();
    expect(describeClaimStatus("reproduced")).toBe("Its code: reproduced");
    expect(describeClaimStatus("not_attempted")).toBe("Its code: not tried");
  });
});

describe("describeBasis", () => {
  it("says what a dataset is matched by, and what corroborated means", () => {
    expect(describeBasis(relation({ basis: "accession" }))).toBe("By the same accession");
    expect(describeBasis(relation({ basis: "name" }))).toBe("By the same name");
    expect(describeBasis(relation({ basis: null }))).toBe("By the same name");
    expect(describeBasis(relation({ kind: "agrees", corroborated: true }))).toBe("Corroborated: the code of one of the papers gave the claim again");
    expect(describeBasis(relation({ kind: "agrees", corroborated: false }))).toBeNull();
    expect(describeBasis(relation({ kind: "method", basis: "name" }))).toBeNull();
  });
});

describe("circleLayout", () => {
  it("puts one paper in the middle, and more around a circle from the top", () => {
    expect(circleLayout(["one"], 100, 10)).toEqual({ one: { x: 50, y: 50 } });
    expect(circleLayout(["a", "b"], 100, 10)).toEqual({ a: { x: 50, y: 10 }, b: { x: 50, y: 90 } });
    const four = circleLayout(["a", "b", "c", "d"], 100, 20);
    expect(four).toEqual({ a: { x: 50, y: 20 }, b: { x: 80, y: 50 }, c: { x: 50, y: 80 }, d: { x: 20, y: 50 } });
    expect(circleLayout([], 100, 10)).toEqual({});
  });
});

describe("linesOf", () => {
  it("draws one line for each two papers and kind, and sets the kinds between two papers side by side", () => {
    const lines = linesOf([
      relation({ kind: "dataset", a: "one", b: "two" }),
      relation({ kind: "refers", a: "two", b: "one" }),
      relation({ kind: "dataset", a: "two", b: "one" }),
      relation({ kind: "code", a: "one", b: "three" }),
    ]);
    expect(lines).toEqual([
      { a: "one", b: "two", kind: "dataset", offset: -0.5 },
      { a: "one", b: "two", kind: "refers", offset: 0.5 },
      { a: "one", b: "three", kind: "code", offset: 0 },
    ]);
    expect(linesOf([])).toEqual([]);
  });

  it("sets three kinds about the middle", () => {
    const lines = linesOf([relation({ kind: "dataset" }), relation({ kind: "software" }), relation({ kind: "method" })]);
    expect(lines.map((line) => line.offset)).toEqual([-1, 0, 1]);
  });
});

describe("shortTitle", () => {
  it("cuts a long title", () => {
    expect(shortTitle(" Short ")).toBe("Short");
    expect(shortTitle("abcdefghij", 10)).toBe("abcdefghij");
    expect(shortTitle("abcdefghijk", 10)).toBe("abcdefghi…");
    expect(shortTitle("abcd efghi jk", 10)).toBe("abcd efgh…");
    expect(shortTitle("abcd      jk", 6)).toBe("abcd…");
  });
});
