import { describe, expect, it } from "vitest";
import { fold } from "./fold";

const lines = (count: number) => Array.from({ length: count }, (_, at) => `line ${at + 1}`).join("\n");

describe("folding code", () => {
  it("shows the first lines of code that has more, and says how many are left", () => {
    const folding = fold(lines(20), 14, false);

    expect(folding.foldable).toBe(true);
    expect(folding.hidden).toBe(6);
    expect(folding.text).toBe(lines(14));
  });

  it("shows all of it once it is opened, and still says it can be folded", () => {
    const folding = fold(lines(20), 14, true);

    expect(folding.foldable).toBe(true);
    expect(folding.text).toBe(lines(20));
  });

  it("does not fold code that has no more than a line past the first lines", () => {
    expect(fold(lines(14), 14, false)).toEqual({ text: lines(14), foldable: false, hidden: 0 });
    expect(fold(lines(15), 14, false)).toEqual({ text: lines(15), foldable: false, hidden: 0 });
    expect(fold(lines(16), 14, false).foldable).toBe(true);
  });

  it("does not fold where it was not asked to", () => {
    expect(fold(lines(500), undefined, false)).toEqual({ text: lines(500), foldable: false, hidden: 0 });
  });

  it("keeps blank lines, which are lines too", () => {
    const code = `${"\n".repeat(20)}end`;

    expect(fold(code, 5, false).text).toBe("\n".repeat(4));
    expect(fold(code, 5, false).hidden).toBe(16);
  });
});
