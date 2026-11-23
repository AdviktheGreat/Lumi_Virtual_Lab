import { describe, expect, it } from "vitest";
import {
  AREA_TITLES,
  authorPackageAddress,
  bySeverity,
  describeCarried,
  describeCounts,
  describeFile,
  describeUnchecked,
  partsSignature,
  SEVERITIES,
  SEVERITY_TITLES,
  SEVERITY_WORDS,
  severityVariant,
  VERDICT_TITLES,
  verdictVariant,
  whyNoAuthorPackage,
} from "./paperagent-authoring";
import type { AuthorArea, AuthorFinding, AuthorVerdict, PaperAgentAuthor } from "./types";

const finding = (part: Partial<AuthorFinding>): AuthorFinding => ({
  id: "no_license",
  area: "license",
  severity: "warn",
  title: "No license",
  detail: "A reader may not use the code.",
  where: [],
  fix: null,
  ...part,
});

const view = (part: Partial<PaperAgentAuthor>): PaperAgentAuthor => ({
  id: "10-1-x",
  title: "A paper",
  verdict: "to_fix",
  summary: "Some things to fix.",
  counts: { block: 0, warn: 1, note: 0 },
  findings: [finding({})],
  not_checked: [],
  steps: { read: true, code: true, environment: true, tutorials: true, claims: true },
  card: "# Card",
  statement: "# Statement",
  package: { ready: true, files: [{ name: "REPRODUCIBILITY.md", bytes: 2048 }], carries_tools: false },
  meaning: "Nothing was run.",
  limits: { most_files_read: 4000, most_carried_package_bytes: 50 * 1024 * 1024 },
  ...part,
});

describe("paperagent authoring", () => {
  it("names every verdict, severity, and area", () => {
    const verdicts: AuthorVerdict[] = ["not_checked", "blocked", "to_fix", "unfinished", "ready"];
    const areas: AuthorArea[] = ["code", "license", "environment", "examples", "data", "claims", "steps"];
    for (const verdict of verdicts) expect(VERDICT_TITLES[verdict]).toBeTruthy();
    for (const area of areas) expect(AREA_TITLES[area]).toBeTruthy();
    for (const severity of SEVERITIES) {
      expect(SEVERITY_TITLES[severity]).toBeTruthy();
      expect(SEVERITY_WORDS[severity]).toBeTruthy();
    }
    expect(SEVERITIES).toEqual(["block", "warn", "note"]);
  });

  it("gives each verdict and severity a badge that tells them apart", () => {
    expect(verdictVariant("ready")).toBe("default");
    expect(verdictVariant("blocked")).toBe("destructive");
    expect(verdictVariant("to_fix")).toBe("secondary");
    expect(verdictVariant("unfinished")).toBe("outline");
    expect(verdictVariant("not_checked")).toBe("outline");
    expect(severityVariant("block")).toBe("destructive");
    expect(severityVariant("warn")).toBe("secondary");
    expect(severityVariant("note")).toBe("outline");
  });

  it("says the counts in words", () => {
    expect(describeCounts({ block: 0, warn: 7, note: 1 })).toBe("0 would stop a reader, 7 may, and 1 is for them to know.");
    expect(describeCounts({ block: 2, warn: 0, note: 3 })).toBe("2 would stop a reader, 0 may, and 3 are for them to know.");
    expect(describeCounts({ block: 0, warn: 0, note: 0 })).toBe("0 would stop a reader, 0 may, and 0 are for them to know.");
  });

  it("groups the findings by severity, the worst first, leaving out the empty ones", () => {
    const groups = bySeverity([
      finding({ id: "a", severity: "note" }),
      finding({ id: "b", severity: "block" }),
      finding({ id: "c", severity: "note" }),
    ]);
    expect(groups.map((group) => group.severity)).toEqual(["block", "note"]);
    expect(groups[1].findings.map((item) => item.id)).toEqual(["a", "c"]);
    expect(bySeverity([])).toEqual([]);
  });

  it("says where on the page a step that was not run is run", () => {
    const base = { title: "The code was not fetched", how: "POST /api/paperagents/x/repository" };
    expect(describeUnchecked({ id: "repository", ...base })).toBe("The code was not fetched. It is run in the Code part of this page.");
    expect(describeUnchecked({ id: "reading", ...base })).toContain("Reading part");
    expect(describeUnchecked({ id: "environment", ...base })).toContain("Environment part");
    expect(describeUnchecked({ id: "reference", ...base })).toContain("Tutorials part");
    expect(describeUnchecked({ id: "reproduction", ...base })).toContain("Claims part");
  });

  it("gives the address of the package with the id encoded", () => {
    expect(authorPackageAddress("10-1/x y")).toBe("/api/paperagents/10-1%2Fx%20y/author/package");
  });

  it("says a file with its size", () => {
    expect(describeFile({ name: "REPRODUCIBILITY.md", bytes: 2048 })).toBe("REPRODUCIBILITY.md, 2.0 KB");
    expect(describeFile({ name: "a.txt", bytes: 12 })).toBe("a.txt, 12 B");
  });

  it("says whether the package carries the tools, and the most it would carry", () => {
    expect(describeCarried(view({ package: { ready: true, files: [], carries_tools: true } }))).toContain("under mcp/");
    const not = describeCarried(view({}));
    expect(not).toContain("does not carry");
    expect(not).toContain("50 MB");
  });

  it("says why there is no package", () => {
    expect(whyNoAuthorPackage(view({}))).toBeNull();
    expect(whyNoAuthorPackage(view({ verdict: "not_checked", package: { ready: false, files: [], carries_tools: false } }))).toContain(
      "Fetch the code first",
    );
    expect(whyNoAuthorPackage(view({ verdict: "blocked", package: { ready: false, files: [], carries_tools: false } }))).toBe(
      "There is nothing to put in a package yet.",
    );
    expect(whyNoAuthorPackage(view({ verdict: "to_fix", package: { ready: false, files: [], carries_tools: false } }))).toBe(
      "There is nothing to put in a package yet.",
    );
  });

  it("says what the page has of the parts only once none is being looked at for the first time", () => {
    expect(partsSignature([{ kind: "ready", value: 1 }, { kind: "loading" }])).toBeNull();
    const one = partsSignature([{ kind: "ready", value: { a: 1 } }, { kind: "failed", error: new Error("x") }]);
    expect(one).not.toBeNull();
    // Looked at again and found the same, it is the same
    expect(partsSignature([{ kind: "ready", value: { a: 1 } }, { kind: "failed", error: new Error("y") }])).toBe(one);
    expect(partsSignature([{ kind: "ready", value: { a: 2 } }, { kind: "failed", error: new Error("x") }])).not.toBe(one);
    expect(partsSignature([{ kind: "ready", value: { a: 1 } }, { kind: "ready", value: 0 }])).not.toBe(one);
  });
});
