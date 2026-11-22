import { describe, expect, it } from "vitest";
import { byTier, describeGiving, describeKind, describeLimits, describeTier, describeTools, runsCode, whyNone } from "./paperagent-given";
import type { GivenTool, PaperAgent, PaperAgentGiven } from "./types";

function tool(name: string, kind: GivenTool["kind"]): GivenTool {
  const tier = kind === "run" ? "A" : kind === "reimplementation" ? "C" : kind === "imported" ? "Imported" : "D";

  return { name, kind, tier, summary: "Does it.", parameters: [], label: kind === "reimplementation" ? "Re-implementation, not the authors' code" : null };
}

function agentOf(changes: Partial<PaperAgent> = {}): PaperAgent {
  return {
    id: "cell",
    title: "Cell",
    created_at: "2026-01-01T00:00:00Z",
    paper: { kind: "file" },
    repo: { url: "https://github.com/example/cell" },
    steps: { reading: "done", repository: "done", environment: "done", data: "skipped", tools: "done" },
    given: false,
    imported: null,
    ...changes,
  } as PaperAgent;
}

function givenOf(tools: GivenTool[], changes: Partial<PaperAgentGiven> = {}): PaperAgentGiven {
  return {
    id: "cell",
    given: false,
    tier: tools.some((one) => one.kind === "run")
      ? "A"
      : tools.some((one) => one.kind === "reimplementation")
        ? "C"
        : tools.some((one) => one.kind === "reading")
          ? "D"
          : tools.length > 0
            ? "Imported"
            : null,
    tools,
    problem: null,
    meaning: "",
    imported: null,
    limits: { call_seconds: 300, memory: "8g", cpus: "4" },
    seat: "PaperAgent: CellMapper",
    told: "You are a PaperAgent: CellMapper.",
    ...changes,
  };
}

describe("describeTier", () => {
  it("says what a tier is, and that there is none when there is nothing to give", () => {
    expect(describeTier("A")).toBe("Tier A: runs the authors' code");
    expect(describeTier("B")).toBe("Tier B: runs the authors' code, and passed checks that its tutorial did not give it");
    expect(describeTier("C")).toBe("Tier C: a re-implementation, not the authors' code, which gave a number that the paper reports");
    expect(describeTier("D")).toBe("Tier D: reads the paper");
    expect(describeTier("Imported")).toBe("Tier Imported: made by someone else, and not checked here");
    expect(describeTier(null)).toBe("Nothing to give yet");
  });

  it("does not make up what a tier it does not know is", () => {
    expect(describeTier("Z")).toBe("Tier Z: not known to this page");
  });
});

describe("byTier", () => {
  it("puts the tools of each tier together, in the order of the tiers, with what each tier is", () => {
    const checked = { ...tool("c", "run"), tier: "B" };
    const groups = byTier([tool("a", "reading"), tool("b", "run"), checked, tool("d", "reading"), tool("e", "imported"), tool("f", "reimplementation")]);

    expect(groups.map((group) => [group.tier, group.tools.map((one) => one.name)])).toEqual([
      ["A", ["b"]],
      ["B", ["c"]],
      ["C", ["f"]],
      ["D", ["a", "d"]],
      ["Imported", ["e"]],
    ]);
    expect(groups[0].title).toBe("Tier A: runs the authors' code");
    expect(byTier([])).toEqual([]);
  });

  it("puts a tier it does not know after those it does", () => {
    expect(byTier([{ ...tool("z", "run"), tier: "Z" }, tool("a", "reading")]).map((group) => group.tier)).toEqual(["D", "Z"]);
  });
});

describe("describeKind", () => {
  it("says what a tool does", () => {
    expect(describeKind("run")).toBe("Runs the authors' own function");
    expect(describeKind("reading")).toBe("Reads what was found in the paper");
    expect(describeKind("imported")).toBe("Calls the server that someone else runs, and asks you first");
    expect(describeKind("reimplementation")).toBe("Runs a function that a model wrote from the paper's words, in a sandbox with no network");
  });
});

describe("runsCode", () => {
  it("is so of the tools that run code when they are called, the authors' or a re-implementation", () => {
    expect(runsCode(tool("a", "run"))).toBe(true);
    expect(runsCode(tool("a", "reimplementation"))).toBe(true);
    expect(runsCode(tool("a", "reading"))).toBe(false);
    expect(runsCode(tool("a", "imported"))).toBe(false);
  });
});

describe("describeTools", () => {
  it("counts the tools of each kind", () => {
    expect(describeTools([])).toBe("No tool is given.");
    expect(describeTools([tool("a", "reading")])).toBe("1 tool that reads the paper.");
    expect(describeTools([tool("a", "reading"), tool("b", "reading"), tool("c", "run")])).toBe(
      "2 tools that read the paper and 1 that runs its code.",
    );
    expect(describeTools([tool("a", "reading"), tool("c", "run"), tool("d", "run")])).toBe("1 tool that reads the paper and 2 that run its code.");
  });

  it("counts the tools of a server that was imported, which neither read the paper nor run its code", () => {
    expect(describeTools([tool("a", "imported")])).toBe("1 tool that calls the server it was imported from.");
    expect(describeTools([tool("a", "imported"), tool("b", "imported")])).toBe("2 tools that call the server it was imported from.");
    expect(describeTools([tool("a", "reading"), tool("b", "imported"), tool("c", "imported")])).toBe(
      "1 tool that reads the paper and 2 that call the server it was imported from.",
    );
    expect(describeTools([tool("a", "run"), tool("b", "imported")])).toBe("1 tool that runs its code and 1 that calls the server it was imported from.");
  });

  it("counts a re-implementation apart from the tools that run the authors' code", () => {
    expect(describeTools([tool("a", "reading"), tool("b", "reimplementation")])).toBe(
      "1 tool that reads the paper and 1 that runs a re-implementation of it, not the authors' code.",
    );
    expect(describeTools([tool("a", "reading"), tool("b", "reimplementation"), tool("c", "reimplementation")])).toBe(
      "1 tool that reads the paper and 2 that run a re-implementation of it, not the authors' code.",
    );
  });
});

describe("describeLimits", () => {
  it("says what a call is allowed", () => {
    expect(describeLimits({ call_seconds: 300, memory: "8g", cpus: "4" })).toBe(
      "A call may take up to 5 minutes, in a container with no network, 8g of memory, and 4 processors.",
    );
    expect(describeLimits({ call_seconds: 60, memory: "2g", cpus: "1" })).toBe(
      "A call may take up to 1 minute, in a container with no network, 2g of memory, and 1 processor.",
    );
  });
});

describe("whyNone", () => {
  it("says nothing when the agent gives tools of both kinds", () => {
    expect(whyNone(agentOf(), givenOf([tool("a", "reading"), tool("b", "run")]))).toEqual([]);
  });

  it("says that the paper has not been read, and that it is being read", () => {
    expect(whyNone(agentOf({ repo: null }), givenOf([]))[0]).toContain("Read it under Reading");
    expect(whyNone(agentOf({ repo: null, steps: { ...agentOf().steps, reading: "running" } }), givenOf([]))[0]).toContain("is being read");
  });

  it("says nothing of tools that run when a re-implementation is given", () => {
    expect(whyNone(agentOf({ repo: null }), givenOf([tool("a", "reading"), tool("b", "reimplementation")]))).toEqual([]);
  });

  it("says why there is no tool that runs, by whether it has code, and where a function can be written from the paper", () => {
    expect(whyNone(agentOf({ repo: null }), givenOf([tool("a", "reading")]))).toEqual([
      "It has no code, so it has no tool that runs the authors' code. A function can be written from the paper's words under Re-implementation, and is given once it matches a number that the paper reports.",
    ]);
    const imported = agentOf({ repo: null, imported: { url: "https://example.org/mcp" } as PaperAgent["imported"] });
    expect(whyNone(imported, givenOf([tool("a", "imported")])).at(-1)).toBe("It has no code, so it has no tool that runs.");
    expect(whyNone(agentOf(), givenOf([tool("a", "reading")]))).toEqual([
      "It has no tool that runs. Tools that run are made of what the tutorials did, under Tools.",
    ]);
  });

  it("leaves it to the server's own words when it says why the tools that run cannot be called", () => {
    expect(whyNone(agentOf(), givenOf([tool("a", "reading")], { problem: "Docker is not running." }))).toEqual([]);
  });
});

describe("describeGiving", () => {
  it("says whether conversations are given the agent", () => {
    expect(describeGiving(true)).toBe("Given to the conversations that you start from now on.");
    expect(describeGiving(false)).toBe("Not given to conversations.");
  });
});
