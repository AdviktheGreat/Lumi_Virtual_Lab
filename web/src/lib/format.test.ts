import { describe, expect, it } from "vitest";
import { formatCost, timeAgo } from "./format";

const NOW = new Date("2026-10-11T12:00:00Z");

function before(milliseconds: number): string {
  return new Date(NOW.getTime() - milliseconds).toISOString();
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

describe("when something happened", () => {
  it("is said as a person would say it", () => {
    expect(timeAgo(before(5_000), NOW)).toBe("just now");
    expect(timeAgo(before(MINUTE), NOW)).toBe("1 min ago");
    expect(timeAgo(before(59 * MINUTE), NOW)).toBe("59 min ago");
    expect(timeAgo(before(HOUR), NOW)).toBe("1 h ago");
    expect(timeAgo(before(23 * HOUR), NOW)).toBe("23 h ago");
    expect(timeAgo(before(DAY), NOW)).toBe("yesterday");
    expect(timeAgo(before(3 * DAY), NOW)).toBe("3 days ago");
  });

  it("changes at the day, and at the week", () => {
    expect(timeAgo(before(2 * DAY - 1), NOW)).toBe("yesterday");
    expect(timeAgo(before(2 * DAY), NOW)).toBe("2 days ago");
    expect(timeAgo(before(7 * DAY - 1), NOW)).toBe("6 days ago");
    expect(timeAgo(before(7 * DAY), NOW)).toBe("Oct 4");
  });

  it("is the date once it was a week ago, with the year if it was not this one", () => {
    expect(timeAgo(before(10 * DAY), NOW)).toBe("Oct 1");
    expect(timeAgo("2025-03-04T12:00:00Z", NOW)).toBe("Mar 4, 2025");
  });

  it("is nothing for a time that is not one", () => {
    expect(timeAgo(null, NOW)).toBe("");
    expect(timeAgo(undefined, NOW)).toBe("");
    expect(timeAgo("", NOW)).toBe("");
    expect(timeAgo("yesterday-ish", NOW)).toBe("");
  });
});

describe("what something cost", () => {
  it("is said in dollars, and as little as it is", () => {
    expect(formatCost(1.234)).toBe("$1.23");
    expect(formatCost(0.0123)).toBe("$0.01");
    expect(formatCost(0.004)).toBe("<$0.01");
    expect(formatCost(0.01)).toBe("$0.01");
    expect(formatCost(0)).toBe("$0.00");
  });

  it("is nothing where it is not known", () => {
    expect(formatCost(null)).toBe("");
    expect(formatCost(undefined)).toBe("");
  });
});
