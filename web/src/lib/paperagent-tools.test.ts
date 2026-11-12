import { describe, expect, it } from "vitest";
import {
  checkTools,
  describeArgs,
  describeCase,
  describeChecked,
  describeMade,
  describeParameter,
  describePreview,
  describeTolerance,
  droppedLines,
  DROPPED_ADVICE,
  DROPPED_TITLES,
  emptyTools,
  type ToolsDraft,
} from "./paperagent-tools";
import type { PaperAgentTools, ToolCase, ToolDropped, ToolsKept } from "./types";

const limits: PaperAgentTools["limits"] = {
  default_minutes: 5,
  max_minutes: 30,
  default_total_minutes: 20,
  max_total_minutes: 120,
  default_tools: 20,
  max_tools: 50,
  default_repeats: 2,
  max_repeats: 3,
  default_repairs: 2,
  max_repairs: 3,
  default_gigabytes: 2,
  max_gigabytes: 20,
  memory: "8g",
  cpus: "4",
  pids: 1024,
};

const draft = (part: Partial<ToolsDraft> = {}): ToolsDraft => ({ ...emptyTools(limits), ...part });

function dropped(part: Partial<ToolDropped> = {}): ToolDropped {
  return { name: "embed", module: "cellmapper.core", function: "embed", kind: "replay_differs", reason: "It gave something else.", details: [], calls: 1, ...part };
}

function kept(part: Partial<ToolsKept> = {}): ToolsKept {
  return {
    commit: "a".repeat(40),
    image_id: `sha256:${"b".repeat(64)}`,
    reference: { started_at: "2026-01-01T00:00:00Z", finished_at: "2026-01-01T00:02:00Z" },
    started_at: "2026-01-01T00:03:00Z",
    finished_at: "2026-01-01T00:03:09Z",
    complete: true,
    limits: { minutes: 5, total_minutes: 20, tools: 20, repeats: 2, repairs: 2, gigabytes: 2, memory: "8g", cpus: "4", pids: 1024 },
    data: false,
    tools: [],
    dropped: [],
    unused: [],
    ...part,
  };
}

function made(part: Partial<ToolCase> = {}): ToolCase {
  return {
    call: 1,
    tutorial: "01-demo-py",
    cell: null,
    origin: { file: "demo.py", line: 3 },
    cwd: ".",
    args: { values: [1, 2, 3], factor: 2.5 },
    expected: { type: "list", plain: true, value: [2.5, 5, 7.5] },
    repeats: 2,
    matched: 2,
    verdict: "match",
    differences: [],
    got: null,
    error: null,
    ...part,
  };
}

describe("what making tools is asked for", () => {
  it("begins with what the server defaults to", () => {
    expect(emptyTools(limits)).toEqual({ minutes: "5", totalMinutes: "20", tools: "20", repeats: "2", repairs: "2", gigabytes: "2" });
  });

  it("is the numbers as whole numbers", () => {
    expect(checkTools(draft(), limits)).toEqual({
      value: { minutes: 5, total_minutes: 20, tools: 20, repeats: 2, repairs: 2, gigabytes: 2 },
      problems: {},
    });
  });

  it("may have no rewriting, which is a number too, but not no time or no tools", () => {
    expect(checkTools(draft({ repairs: "0" }), limits).value?.repairs).toBe(0);
    const none = checkTools(draft({ minutes: "0", tools: "0", repeats: "0" }), limits);

    expect(none.value).toBeNull();
    expect(Object.keys(none.problems).sort()).toEqual(["minutes", "repeats", "tools"]);
  });

  it("says what is wrong with each, with the most that is allowed", () => {
    const bad = checkTools(draft({ minutes: "31", totalMinutes: "many", tools: "51", repeats: "4", repairs: "4", gigabytes: "21" }), limits);

    expect(bad.value).toBeNull();
    expect(bad.problems.minutes).toMatch(/whole number from 1 to 30/);
    expect(bad.problems.totalMinutes).toMatch(/whole number from 1 to 120/);
    expect(bad.problems.tools).toMatch(/whole number from 1 to 50/);
    expect(bad.problems.repeats).toMatch(/whole number from 1 to 3/);
    expect(bad.problems.repairs).toMatch(/whole number from 0 to 3/);
    expect(bad.problems.gigabytes).toMatch(/whole number from 1 to 20/);
  });

  it("does not take less time for all of the tools than for one", () => {
    const less = checkTools(draft({ minutes: "20", totalMinutes: "10" }), limits);

    expect(less.value).toBeNull();
    expect(less.problems).toEqual({ totalMinutes: "The time for all of the tools cannot be less than the time for one." });
  });
});

describe("what is said of the functions that were called", () => {
  it("says how many can be tools and how many cannot", () => {
    expect(describePreview(2, 0)).toBe("2 functions can be made into tools.");
    expect(describePreview(1, 3)).toBe("1 function can be made into a tool, 3 cannot.");
    expect(describePreview(0, 1)).toBe("0 functions can be made into tools, 1 cannot.");
  });

  it("has a few words for each way a function is not made a tool, and advice for those that can be helped", () => {
    for (const title of Object.values(DROPPED_TITLES)) expect(title.length).toBeGreaterThan(5);
    expect(Object.keys(DROPPED_ADVICE).every((kind) => kind in DROPPED_TITLES)).toBe(true);
    expect(DROPPED_ADVICE.out_of_time).toMatch(/more time/);
  });

  it("gives what the check found, without saying the reason again", () => {
    const item = dropped({ details: ["It gave something else.", "Its type is int where it was float"] });

    expect(droppedLines(item)).toEqual(["Its type is int where it was float"]);
  });
});

describe("what is said of the tools that were made", () => {
  it("says how many tools and how many functions were left out, and that no tool held when none did", () => {
    expect(describeMade(kept({ tools: [], dropped: [dropped()] }))).toBe("No tool held. 1 function was not made into a tool.");
    const tools = [{ name: "scale", tier: "A", module: "m", function: "scale", parameters: ["values"], checked: 2, recorded: 2, repeats: 2, tutorials: ["01"] }];

    expect(describeMade(kept({ tools, dropped: [dropped(), dropped({ name: "other" })] }))).toBe("1 tool of tier A. 2 functions were not made into a tool.");
    expect(describeMade(kept({ tools }))).toBe("1 tool of tier A. 0 functions were not made into a tool.");
    expect(describeMade(kept({ tools: [], complete: false }))).toBe("No tool was made. 0 functions were not made into a tool.");
  });

  it("says that each call was made again and gave what the tutorial got, and how many could not be", () => {
    expect(describeChecked({ checked: 2, recorded: 2, repeats: 2 })).toBe("2 calls, each made again 2 times, gave what the tutorial got every time");
    expect(describeChecked({ checked: 1, recorded: 1, repeats: 1 })).toBe("1 call, each made again once, gave what the tutorial got every time");
    expect(describeChecked({ checked: 1, recorded: 3, repeats: 2 })).toBe(
      "1 call, each made again 2 times, gave what the tutorial got every time. 2 other calls could not be made again",
    );
  });

  it("writes what a call was given as the tutorial wrote it, and cuts what is long", () => {
    expect(describeArgs({ values: [1, 2, 3], factor: 2.5 })).toBe("values=[1,2,3], factor=2.5");
    expect(describeArgs({ text: "x".repeat(300) }).length).toBeLessThan(130);
    expect(describeArgs({})).toBe("");
  });

  it("says what came of making a call again", () => {
    expect(describeCase(made())).toBe("Gave what the tutorial got, 2 of 2 times");
    expect(describeCase(made({ repeats: 1, matched: 1 }))).toBe("Gave what the tutorial got, 1 of 1 time");
    expect(describeCase(made({ verdict: "differs", matched: 1 }))).toBe("Gave something else. It gave what the tutorial got 1 of 2 times");
    expect(describeCase(made({ verdict: "error", error: { type: "FileNotFoundError", message: "No such file: x.csv" } }))).toBe(
      "Raised FileNotFoundError: No such file: x.csv",
    );
    expect(describeCase(made({ verdict: "not_run", matched: 0 }))).toBe("Was not made again");
  });

  it("says how close a number has to be, and writes a parameter as a signature does", () => {
    expect(describeTolerance({ relative: 1e-6, absolute: 1e-9 })).toContain("within 0.000001 of the other, or 1e-9 from it");
    expect(describeParameter({ name: "values", type: "list[float]", required: true, default: null })).toBe("values: list[float]");
    expect(describeParameter({ name: "factor", type: "float", required: false, default: 1.5 })).toBe("factor: float = 1.5");
    expect(describeParameter({ name: "name", type: "Optional[str]", required: false, default: null })).toBe("name: Optional[str] = None");
  });
});
