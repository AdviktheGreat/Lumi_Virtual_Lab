import { describe, expect, it } from "vitest";
import { belowSpent, checkLimits, formatAmount, limitsDraftOf, parseCount, raisedBy, type CurrentLimits } from "./limits";
import type { ChatLimits } from "./types";

const LIMITS: ChatLimits = { max_delegations: { default: 3, ceiling: 20 }, max_rounds: { default: 3, ceiling: 10 } };
const CURRENT: CurrentLimits = { max_cost: 5, max_delegations: 3, max_rounds: 2 };

describe("what the panel shows of the limits", () => {
  it("is what is typed where it is typed, and nothing for no spending limit", () => {
    expect(limitsDraftOf(CURRENT)).toEqual({ cost: "5", sessions: "3", rounds: "2" });
    expect(limitsDraftOf({ ...CURRENT, max_cost: null }).cost).toBe("");
    expect(limitsDraftOf({ ...CURRENT, max_cost: 0 }).cost).toBe("0");
  });

  it("does not show a price with the noise of a sum in it", () => {
    expect(formatAmount(0.1 + 0.2)).toBe("0.3");
    expect(formatAmount(12.5)).toBe("12.5");
    expect(formatAmount(7)).toBe("7");
  });
});

describe("a count of team sessions or rounds", () => {
  it("is a whole number from none to the most", () => {
    expect(parseCount("0", 10)).toBe(0);
    expect(parseCount(" 7 ", 10)).toBe(7);
    expect(parseCount("10", 10)).toBe(10);
    for (const typed of ["", "  ", "11", "-1", "1.5", "two", "1e1", "+2"]) expect(parseCount(typed, 10)).toBeUndefined();
  });
});

describe("what the panel asks for", () => {
  const draft = { cost: "5", sessions: "3", rounds: "2" };

  it("is nothing when nothing was changed", () => {
    expect(checkLimits(draft, CURRENT, LIMITS)).toEqual({ changes: {}, problems: {} });
  });

  it("is only what was changed", () => {
    expect(checkLimits({ ...draft, cost: "$ 12.50" }, CURRENT, LIMITS).changes).toEqual({ max_cost: 12.5 });
    expect(checkLimits({ ...draft, rounds: "4" }, CURRENT, LIMITS).changes).toEqual({ max_rounds: 4 });
    expect(checkLimits({ cost: "6", sessions: "0", rounds: "10" }, CURRENT, LIMITS).changes).toEqual({
      max_cost: 6,
      max_delegations: 0,
      max_rounds: 10,
    });
  });

  it("takes an empty limit as the limit being taken away, and asks for it only if there was one", () => {
    expect(checkLimits({ ...draft, cost: "" }, CURRENT, LIMITS).changes).toEqual({ max_cost: null });
    expect(checkLimits({ ...draft, cost: "" }, { ...CURRENT, max_cost: null }, LIMITS).changes).toEqual({});
  });

  it("says what is wrong with what was typed, and asks for none of it", () => {
    const checked = checkLimits({ cost: "plenty", sessions: "21", rounds: "-1" }, CURRENT, LIMITS);

    expect(checked.changes).toEqual({});
    expect(checked.problems.cost).toMatch(/amount in dollars/);
    expect(checked.problems.sessions).toBe("A whole number from 0 to 20.");
    expect(checked.problems.rounds).toBe("A whole number from 0 to 10.");
  });
});

describe("raising the limit", () => {
  it("adds to what is typed", () => {
    expect(raisedBy("5", 1, 0.2)).toBe("6");
    expect(raisedBy("$2.50", 5, null)).toBe("7.5");
  });

  it("adds to what is spent where there is no limit, or what is typed is not one", () => {
    expect(raisedBy("", 1, 0.42)).toBe("1.42");
    expect(raisedBy("lots", 5, 2)).toBe("7");
    expect(raisedBy("", 1, null)).toBe("1");
  });
});

describe("a limit below what is spent", () => {
  it("is told of, which has the lead stop at its next request", () => {
    expect(belowSpent("1", 2.5)).toBe(true);
    expect(belowSpent("2.5", 2.5)).toBe(false);
    expect(belowSpent("", 2.5)).toBe(false);
    expect(belowSpent("1", null)).toBe(false);
    expect(belowSpent("lots", 3)).toBe(false);
  });
});
