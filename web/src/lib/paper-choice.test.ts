import { describe, expect, it } from "vitest";
import { choosesPapers, papersButtonText, papersOf } from "./paper-choice";
import type { PaperAgent } from "./types";

const agent = (id: string, given: boolean) => ({ id, title: id, given }) as PaperAgent;
const AGENTS = [agent("a", true), agent("b", false), agent("c", true)];

describe("the PaperAgents of a conversation that is begun", () => {
  it("are those given to conversations and the one a link names, until some are chosen, in the order of the list", () => {
    expect(papersOf(AGENTS, null, "").map((each) => each.id)).toEqual(["a", "c"]);
    expect(papersOf(AGENTS, null, "b").map((each) => each.id)).toEqual(["a", "b", "c"]);
    expect(papersOf(AGENTS, ["c", "b", "gone"], "a").map((each) => each.id)).toEqual(["b", "c"]);
    expect(papersOf(AGENTS, [], "b")).toEqual([]);
  });

  it("are told to the server only where they are not those it gives by itself", () => {
    expect(choosesPapers(AGENTS, null, "")).toBe(false);
    expect(choosesPapers(AGENTS, null, "a")).toBe(false);
    expect(choosesPapers(AGENTS, null, "gone")).toBe(false);
    expect(choosesPapers(AGENTS, null, "b")).toBe(true);
    expect(choosesPapers(AGENTS, ["a", "c"], "")).toBe(true);
  });

  it("are counted on the button", () => {
    expect(papersButtonText(0)).toBe("No PaperAgents");
    expect(papersButtonText(1)).toBe("1 PaperAgent");
    expect(papersButtonText(2)).toBe("2 PaperAgents");
  });
});
