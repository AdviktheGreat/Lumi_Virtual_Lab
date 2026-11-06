import { describe, expect, it } from "vitest";
import { checkProgram, INSTRUCTIONS_LIMIT, kindName, lengthOf, NO_CODE_FOR_SKILL, PROGRAM_KINDS } from "./programs";

describe("kinds", () => {
  it("names a quick task first, then a custom program, then one that builds a skill", () => {
    expect(PROGRAM_KINDS.map((known) => known.kind)).toEqual(["quick_task", "custom", "build_skill"]);
    expect(kindName("quick_task")).toBe("Quick task");
    expect(kindName("custom")).toBe("Custom program");
    expect(kindName("build_skill")).toBe("Build skill");
  });

  it("names one that is not known as a quick task, which is what the server takes it for", () => {
    expect(kindName("something else" as never)).toBe("Quick task");
  });
});

describe("lengthOf", () => {
  it("counts characters, and not the units a box counts two for", () => {
    expect(lengthOf("abc")).toBe(3);
    expect(lengthOf("😀😀")).toBe(2);
  });
});

describe("checkProgram", () => {
  it("asks for nothing of a quick task, whatever was typed for a custom one", () => {
    expect(checkProgram({ kind: "quick_task", name: "", instructions: "" })).toEqual({ begin: {}, problems: {} });
    expect(checkProgram({ kind: "quick_task", name: "Named", instructions: "Typed" })).toEqual({ begin: {}, problems: {} });
  });

  it("asks for a custom program with the name tidied and the instructions trimmed", () => {
    expect(checkProgram({ kind: "custom", name: "  Weekly   review ", instructions: "\n Be brief. \n" })).toEqual({
      begin: { kind: "custom", title: "Weekly review", instructions: "Be brief." },
      problems: {},
    });
  });

  it("needs a custom program to have a name and instructions, and says which is missing", () => {
    expect(checkProgram({ kind: "custom", name: "  ", instructions: "Be brief." })).toEqual({
      begin: {},
      problems: { name: "A custom program needs a name." },
    });
    const none = checkProgram({ kind: "custom", name: "Review", instructions: " \n " });
    expect(none.begin).toEqual({});
    expect(none.problems.name).toBeUndefined();
    expect(none.problems.instructions).toContain("needs instructions");
    expect(Object.keys(checkProgram({ kind: "custom", name: "", instructions: "" }).problems)).toEqual(["name", "instructions"]);
  });

  it("takes instructions of the most there may be, and not more", () => {
    expect(checkProgram({ kind: "custom", name: "Review", instructions: "a".repeat(INSTRUCTIONS_LIMIT) }).problems).toEqual({});
    const long = checkProgram({ kind: "custom", name: "Review", instructions: `${"a".repeat(INSTRUCTIONS_LIMIT)}b` });
    expect(long.begin).toEqual({});
    expect(long.problems.instructions).toBe("Instructions are at most 8,000 characters, and these are 8,001.");
  });

  it("asks for a name and instructions of no program that builds a skill, and says so where there is no code to run", () => {
    const draft = { kind: "build_skill" as const, name: "", instructions: "" };

    expect(checkProgram(draft)).toEqual({ begin: { kind: "build_skill" }, problems: {} });
    expect(checkProgram({ ...draft, name: "Typed", instructions: "Typed" }).begin).toEqual({ kind: "build_skill" });
    expect(checkProgram(draft, true).begin).toEqual({ kind: "build_skill" });
    expect(checkProgram(draft, false)).toEqual({ begin: {}, problems: { code: NO_CODE_FOR_SKILL } });
  });

  it("does not ask for code of a program that does not build a skill", () => {
    expect(checkProgram({ kind: "quick_task", name: "", instructions: "" }, false)).toEqual({ begin: {}, problems: {} });
    expect(checkProgram({ kind: "custom", name: "Review", instructions: "Be brief." }, false).problems).toEqual({});
  });

  it("counts the instructions as the server does, by characters", () => {
    expect(checkProgram({ kind: "custom", name: "Review", instructions: "😀".repeat(INSTRUCTIONS_LIMIT) }).problems).toEqual({});
  });
});
