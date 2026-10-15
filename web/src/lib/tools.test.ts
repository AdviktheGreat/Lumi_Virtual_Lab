import { describe, expect, it } from "vitest";
import { disabledWhen, groupTools, howManyOn } from "./tools";
import type { ToolInfo } from "./types";

const tool = (name: string, group: string, enabled = true): ToolInfo => ({
  name,
  group,
  summary: `${name} does something`,
  needs_code: false,
  enabled,
});

const tools = [tool("a", "Literature"), tool("b", "Chemistry", false), tool("c", "Literature"), tool("d", "Files")];

describe("the tools by what they are for", () => {
  it("are grouped in the order the server listed them, which keeps the tools of a group together", () => {
    expect(groupTools(tools).map((group) => [group.name, group.tools.map((one) => one.name)])).toEqual([
      ["Literature", ["a", "c"]],
      ["Chemistry", ["b"]],
      ["Files", ["d"]],
    ]);
  });

  it("are no groups when there are none", () => {
    expect(groupTools([])).toEqual([]);
  });
});

describe("which tools are off", () => {
  it("are those that are off, and the names given turned off too when they are to be turned off", () => {
    expect(disabledWhen(tools, ["a"], false)).toEqual(["a", "b"]);
  });

  it("are those that are off, less the names given when they are to be turned on", () => {
    expect(disabledWhen(tools, ["b", "c"], true)).toEqual([]);
  });

  it("are as they were for the names that are not given, and stay in the order of the tools", () => {
    expect(disabledWhen(tools, ["d", "a"], false)).toEqual(["a", "b", "d"]);
    expect(disabledWhen(tools, [], true)).toEqual(["b"]);
  });

  it("do not count a name that is not a tool", () => {
    expect(disabledWhen(tools, ["nothing"], false)).toEqual(["b"]);
  });
});

describe("how many tools are on", () => {
  it("is said as a person says it", () => {
    expect(howManyOn(tools)).toBe("3 of 4 are on");
    expect(howManyOn(tools.map((one) => ({ ...one, enabled: true })))).toBe("All 4 are on");
    expect(howManyOn(tools.map((one) => ({ ...one, enabled: false })))).toBe("None are on");
  });
});
