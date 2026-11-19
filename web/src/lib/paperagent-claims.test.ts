import { describe, expect, it } from "vitest";
import {
  checkClaims,
  claimStatusTitle,
  describeBasis,
  describeCounts,
  describeKept,
  describeLink,
  describeRuns,
  describeSoftware,
  describeStale,
  differenceKind,
  divergenceOf,
  emptyClaims,
  filterClaims,
  filtersOf,
  statusTitle,
} from "./paperagent-claims";
import type { ClaimLink, ClaimOutcome, ClaimStatus, DivergenceSoftware, PaperAgentClaims } from "./types";

const counts = (part: Partial<Record<ClaimStatus, number>> = {}): Record<ClaimStatus, number> => ({
  reproduced: 0,
  partly: 0,
  not_reproduced: 0,
  not_attempted: 0,
  stale: 0,
  ...part,
});

function link(part: Partial<ClaimLink> = {}): ClaimLink {
  return {
    basis: "number",
    tutorial: { id: "01", path: "examples/demo.py", kind: "script", runs: 2, stable: true },
    source: "call",
    where: "the call of score in examples/demo.py",
    call: 3,
    got: 0.93,
    number: { text: "0.93", value: 0.93, decimals: 2, percent: false },
    share: 0,
    figures: [],
    chosen_by: "gpt-5.2",
    others: [],
    ...part,
  };
}

function claim(part: Partial<ClaimOutcome> = {}): ClaimOutcome {
  return {
    id: "c1",
    kind: "number",
    value: "0.93",
    quote: "It reached an AUROC of 0.93.",
    anchor: null,
    figures: [],
    status: "reproduced",
    reason: null,
    summary: "The tutorial gave 0.93.",
    link: link(),
    ...part,
  };
}

describe("what trying the claims is asked for", () => {
  it("is the most that asking a model may spend, which must be said", () => {
    expect(checkClaims(emptyClaims())).toEqual({ value: null, problems: { budget: "Say the most it may spend." } });
    expect(checkClaims({ budget: "  " }).problems.budget).toBe("Say the most it may spend.");
    expect(checkClaims({ budget: "$1.50" })).toEqual({ value: { max_cost: 1.5 }, problems: {} });
    expect(checkClaims({ budget: "0" })).toEqual({ value: { max_cost: 0 }, problems: {} });
    expect(checkClaims({ budget: ".5" }).value).toEqual({ max_cost: 0.5 });
  });

  it("is refused for what is not an amount", () => {
    for (const typed of ["many", "-1", "1e3", "1,5", "NaN"]) {
      const checked = checkClaims({ budget: typed });

      expect(checked.value).toBeNull();
      expect(checked.problems.budget).toBe("The most it may spend is an amount in dollars, such as 1 or 0.50.");
    }
  });
});

describe("how a claim came out, in words", () => {
  it("is told by a title for each status, and by the word it is for one that is not known", () => {
    expect(statusTitle("reproduced")).toBe("Reproduced");
    expect(statusTitle("partly")).toBe("Partly reproduced");
    expect(statusTitle("not_reproduced")).toBe("Not reproduced");
    expect(statusTitle("not_attempted")).toBe("Not attempted");
    expect(statusTitle("stale")).toBe("Stale");
    expect(statusTitle("something_new")).toBe("something_new");
  });

  it("says, of a claim that is stale, what it was, as the table that is saved does", () => {
    expect(claimStatusTitle({ status: "stale", was: "reproduced" })).toBe("Stale (was Reproduced)");
    expect(claimStatusTitle({ status: "stale" })).toBe("Stale");
    expect(claimStatusTitle({ status: "partly" })).toBe("Partly reproduced");
  });

  it("says of a claim that is stale that what came of it is not shown, and nothing of one that is not", () => {
    expect(describeStale({ status: "stale", was: "not_reproduced" })).toBe(
      "It was tried against another run of the tutorials, or other claims, than are kept now, so what came of it is not shown. It was not reproduced when it was tried. Try the claims again.",
    );
    expect(describeStale({ status: "stale" })).not.toContain("when it was tried");
    expect(describeStale({ status: "reproduced" })).toBeNull();
  });
});

describe("how many claims came out each way", () => {
  it("is said for each that at least one did, in order, and how many were not listed", () => {
    expect(describeCounts(counts({ reproduced: 3, not_reproduced: 1, not_attempted: 2 }), 0)).toBe("6 claims: 3 reproduced, 1 not reproduced, 2 not attempted.");
    expect(describeCounts(counts({ partly: 1 }), 0)).toBe("1 claim: 1 partly reproduced.");
    expect(describeCounts(counts({ stale: 2 }), 0)).toBe("2 claims: 2 stale.");
    expect(describeCounts(counts({ reproduced: 300 }), 12)).toBe("300 claims: 300 reproduced. 12 claims more come after the 300 that are listed, and are not tried.");
    expect(describeCounts(counts({ reproduced: 300 }), 1)).toBe("300 claims: 300 reproduced. 1 claim more comes after the 300 that are listed, and is not tried.");
  });

  it("says that none is listed when none is", () => {
    expect(describeCounts(counts(), 0)).toBe("No claim of the paper is listed.");
  });

  it("offers a way to tell the claims apart for each status that at least one has, after all of them", () => {
    expect(filtersOf(counts({ reproduced: 1, not_attempted: 2 }))).toEqual(["all", "reproduced", "not_attempted"]);
    expect(filtersOf(counts())).toEqual(["all"]);
  });

  it("shows the claims that came out one way, or all of them, as they are", () => {
    const claims = [claim({ id: "a" }), claim({ id: "b", status: "partly" }), claim({ id: "c", status: "partly" })];

    expect(filterClaims(claims, "all").map((one) => one.id)).toEqual(["a", "b", "c"]);
    expect(filterClaims(claims, "partly").map((one) => one.id)).toEqual(["b", "c"]);
    expect(filterClaims(claims, "stale")).toEqual([]);
    expect(filterClaims(claims, "all")).not.toBe(claims);
  });
});

describe("how the trying went", () => {
  const kept = {
    started_at: "2026-01-01T00:00:00Z",
    finished_at: "2026-01-01T00:01:00Z",
    complete: true,
    model: "gpt-5.2",
    cost: 0.0123,
    requests: 3,
    limit: null,
    notes: [],
  };

  it("says which model was asked, how many times, and what it cost", () => {
    const said = describeKept(kept);

    expect(said).toMatch(/^Tried .+\. gpt-5\.2 was asked 3 times, which cost \$0\.01\.$/);
    expect(describeKept({ ...kept, requests: 1, cost: null })).toMatch(/gpt-5\.2 was asked 1 time\.$/);
  });

  it("says that no model was asked when none was, and that it did not come to its end when it did not", () => {
    expect(describeKept({ ...kept, requests: 0, cost: 0 })).toMatch(/No model was asked\.$/);
    expect(describeKept({ ...kept, complete: false })).toMatch(/It did not come to its end\.$/);
  });
});

describe("what a claim was held to", () => {
  it("says the place, what it gave and what the paper reports, how it was found, who chose it, and whether the runs agreed", () => {
    const lines = describeLink(link());

    expect(lines[0]).toBe("Held to the call of score in examples/demo.py in examples/demo.py.");
    expect(lines[1]).toBe("It gave 0.93, and the paper reports 0.93.");
    expect(lines[2]).toBe("It was found because a result rounds to the paper's number.");
    expect(lines[3]).toBe("gpt-5.2 chose this place from the words alone, without being shown any value. A program held it to the number.");
    expect(lines[4]).toBe("The 2 runs of the tutorial agreed.");
    expect(lines).toHaveLength(5);
  });

  it("names the other places that hold the number, if there are any", () => {
    const lines = describeLink(link({ others: [{ tutorial: "b.py", where: "the call of f", value: 0.93 }, { tutorial: "c.py", where: "a printed line", value: 0.93 }] }));

    expect(lines[5]).toBe("Other places hold the number too: the call of f in b.py; a printed line in c.py.");
  });

  it("says how a place was found, by the number, by the figure, or by both", () => {
    expect(describeBasis({ basis: "number", figures: [] })).toBe("It was found because a result rounds to the paper's number.");
    expect(describeBasis({ basis: "figure", figures: ["figure 2"] })).toBe(
      "It was found because the sentence and the tutorial both refer to figure 2. No result there rounds to the paper's number.",
    );
    expect(describeBasis({ basis: "both", figures: ["figure 2", "table 1"] })).toBe(
      "It was found because a result rounds to the paper's number, and because the sentence and the tutorial both refer to figure 2, table 1.",
    );
  });

  it("says whether the runs of the tutorial agreed, did not, or were not compared", () => {
    expect(describeRuns({ runs: 2, stable: true })).toBe("The 2 runs of the tutorial agreed.");
    expect(describeRuns({ runs: 2, stable: false })).toBe("The runs of the tutorial did not agree with each other, so it may not give this again.");
    expect(describeRuns({ runs: 1, stable: null })).toBe("The tutorial was run once, so its runs were not compared.");
    expect(describeRuns({ runs: 2, stable: null })).toBe("The runs of the tutorial could not be compared.");
  });
});

describe("what differs, which is found and is not said to be why", () => {
  it("names the kind of a difference, and a kind that is not known by itself", () => {
    expect(differenceKind("python")).toBe("Python");
    expect(differenceKind("argument")).toBe("Argument");
    expect(differenceKind("something_new")).toBe("something_new");
  });

  it("says what software the paper names stands as against what is installed", () => {
    const software = (part: Partial<DivergenceSoftware>): DivergenceSoftware => ({ name: "Seurat", paper: "4.3", installed: null, state: "not_installed", quote: "q", ...part });

    expect(describeSoftware(software({}))).toBe("Seurat: the paper says 4.3, none installed (not installed).");
    expect(describeSoftware(software({ installed: "4.1", state: "differs" }))).toBe("Seurat: the paper says 4.3, installed: 4.1 (another version).");
    expect(describeSoftware(software({ paper: "", installed: "4.1", state: "no_version" }))).toBe("Seurat: the paper says no version, installed: 4.1 (the paper gives no version).");
  });

  it("is only said of a trying that is of what is kept now", () => {
    const found = { id: "c1", quote: "q", value: "0.9", status: "not_reproduced" as const, tutorial: "a.py", point: null, differences: [] };
    const claims = (reproduction: boolean, divergence: boolean): PaperAgentClaims =>
      ({ reproduction: { current: reproduction }, divergence: { current: divergence, claims: [found] } }) as unknown as PaperAgentClaims;

    expect(divergenceOf(claims(true, true), "c1")).toBe(found);
    expect(divergenceOf(claims(true, true), "other")).toBeUndefined();
    expect(divergenceOf(claims(false, true), "c1")).toBeUndefined();
    expect(divergenceOf(claims(true, false), "c1")).toBeUndefined();
  });
});
