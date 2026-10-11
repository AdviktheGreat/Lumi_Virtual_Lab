import { describe, expect, it } from "vitest";
import { formatCost, formatDuration, stripAnsi, timeAgo, timeAgoFromEpoch } from "./format";

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

describe("how long something took", () => {
  it("is said in the unit that fits", () => {
    expect(formatDuration(0.25)).toBe("250 ms");
    expect(formatDuration(0)).toBe("<1 ms");
    expect(formatDuration(0.0004)).toBe("<1 ms");
    expect(formatDuration(0.001)).toBe("1 ms");
    expect(formatDuration(0.9996)).toBe("1.0 s");
    expect(formatDuration(1)).toBe("1.0 s");
    expect(formatDuration(9.94)).toBe("9.9 s");
    expect(formatDuration(9.96)).toBe("10 s");
    expect(formatDuration(10)).toBe("10 s");
    expect(formatDuration(59.4)).toBe("59 s");
    expect(formatDuration(59.6)).toBe("1 min");
    expect(formatDuration(60)).toBe("1 min");
    expect(formatDuration(119.6)).toBe("2 min");
    expect(formatDuration(125)).toBe("2 min 5 s");
  });

  it("is nothing for a time that is not one", () => {
    expect(formatDuration(-1)).toBe("");
    expect(formatDuration(Number.NaN)).toBe("");
    expect(formatDuration(Infinity)).toBe("");
  });
});

describe("output written for a terminal", () => {
  it("has its colours and cursor movements taken out", () => {
    const escape = String.fromCharCode(27);

    expect(stripAnsi(`${escape}[31mred${escape}[0m and ${escape}[1;32mbold green${escape}[0m`)).toBe("red and bold green");
    expect(stripAnsi(`line${escape}[2K${escape}[1A done`)).toBe("line done");
    expect(stripAnsi(`${escape}[?25lhidden cursor${escape}[?25h`)).toBe("hidden cursor");
    expect(stripAnsi(`${escape}[0 qshaped${escape}[2 q cursor`)).toBe("shaped cursor");
    expect(stripAnsi("plain [31m text, with no escape")).toBe("plain [31m text, with no escape");
  });
});

describe("when a file was changed", () => {
  it("is said as any time is, from the seconds since the epoch", () => {
    const seconds = NOW.getTime() / 1000;

    expect(timeAgoFromEpoch(seconds - 5, NOW)).toBe("just now");
    expect(timeAgoFromEpoch(seconds - 5 * 60, NOW)).toBe("5 min ago");
    expect(timeAgoFromEpoch(seconds - 3 * 3600, NOW)).toBe("3 h ago");
  });

  it("is not said for what is not a time", () => {
    expect(timeAgoFromEpoch(Number.NaN, NOW)).toBe("");
    expect(timeAgoFromEpoch(Number.POSITIVE_INFINITY, NOW)).toBe("");
    // A time too far off for a date to hold
    expect(timeAgoFromEpoch(1e20, NOW)).toBe("");
  });
});
