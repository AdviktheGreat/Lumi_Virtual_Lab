import { describe, expect, it } from "vitest";
import { followsEnd } from "./use-stick-to-bottom";

describe("whether a list that has grown is kept at its end", () => {
  it("is not for a reader who has scrolled up, as the list said it", () => {
    expect(followsEnd(false, { top: 0, gap: 900 }, 0)).toBe(false);
    expect(followsEnd(false, { top: 0, gap: 0 }, 0)).toBe(false);
  });

  it("is for a reader at the end, whose list has grown below them", () => {
    // The list grew by 120 pixels where the reader was, and has not been scrolled
    expect(followsEnd(true, { top: 600, gap: 120 }, 600)).toBe(true);
    // Which is also so of a list that was not yet scrolled at all
    expect(followsEnd(true, { top: 0, gap: 300 }, 0)).toBe(true);
  });

  it("is not for a reader who has scrolled up before the list said so, and whose list grew", () => {
    expect(followsEnd(true, { top: 0, gap: 1000 }, 600)).toBe(false);
    expect(followsEnd(true, { top: 200, gap: 800 }, 600)).toBe(false);
  });

  it("is, for a list that grew, whatever pixel the reader is on, so long as they have not gone up", () => {
    expect(followsEnd(true, { top: 599, gap: 500 }, 600)).toBe(true);
    expect(followsEnd(true, { top: 598, gap: 500 }, 600)).toBe(false);
  });

  it("is for a reader at the end of a list that shrank, which leaves them higher up than they were seen to be", () => {
    expect(followsEnd(true, { top: 300, gap: 0 }, 600)).toBe(true);
    expect(followsEnd(true, { top: 300, gap: 48 }, 600)).toBe(true);
    expect(followsEnd(true, { top: 300, gap: 49 }, 600)).toBe(false);
  });
});
