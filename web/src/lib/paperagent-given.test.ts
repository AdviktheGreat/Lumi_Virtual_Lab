import { describe, expect, it } from "vitest";
import { describeGiving, describeKind, describeLimits, describeTier, describeTools, whyNone } from "./paperagent-given";
import type { GivenTool, PaperAgent, PaperAgentGiven } from "./types";

function tool(name: string, kind: GivenTool["kind"]): GivenTool {
  return { name, kind, tier: kind === "run" ? "A" : "D", summary: "Does it.", parameters: [] };
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
    ...changes,
  } as PaperAgent;
}

function givenOf(tools: GivenTool[], changes: Partial<PaperAgentGiven> = {}): PaperAgentGiven {
  return {
    id: "cell",
    given: false,
    tier: tools.some((one) => one.kind === "run") ? "A" : tools.length > 0 ? "D" : null,
    tools,
    problem: null,
    meaning: "",
    limits: { call_seconds: 300, memory: "8g", cpus: "4" },
    ...changes,
  };
}

describe("describeTier", () => {
  it("says what a tier is, and that there is none when there is nothing to give", () => {
    expect(describeTier("A")).toBe("Tier A: runs the authors' code");
    expect(describeTier("D")).toBe("Tier D: reads the paper");
    expect(describeTier(null)).toBe("Nothing to give yet");
  });

  it("does not make up what a tier it does not know is", () => {
    expect(describeTier("Z")).toBe("Tier Z: not known to this page");
  });
});

describe("describeKind", () => {
  it("says what a tool does", () => {
    expect(describeKind("run")).toBe("Runs the authors' own function");
    expect(describeKind("reading")).toBe("Reads what was found in the paper");
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

  it("says why there is no tool that runs, by whether it has code", () => {
    expect(whyNone(agentOf({ repo: null }), givenOf([tool("a", "reading")]))).toEqual(["It has no code, so it has no tool that runs."]);
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
