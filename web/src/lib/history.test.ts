import { describe, expect, it } from "vitest";
import { cleanTitle, inDays, matchingTitles, TITLE_LIMIT } from "./history";

describe("a title as it is kept", () => {
  it("is its words one space apart, with nothing round them", () => {
    expect(cleanTitle("  A  nanobody\tfor \n TP53  ")).toBe("A nanobody for TP53");
  });

  it("is nothing for a title with nothing in it", () => {
    expect(cleanTitle("")).toBeNull();
    expect(cleanTitle(" \t\n ")).toBeNull();
  });

  it("is cut to the most it may be, in characters rather than in the halves of one", () => {
    expect(TITLE_LIMIT).toBe(80);
    expect(cleanTitle("a".repeat(100))).toBe("a".repeat(80));
    expect(cleanTitle("a".repeat(80))).toBe("a".repeat(80));
    expect(cleanTitle("😀".repeat(100))).toBe("😀".repeat(80));
  });

  it("does not end in a space that the cut left", () => {
    expect(cleanTitle(`${"a".repeat(79)} bbb`)).toBe("a".repeat(79));
  });
});

describe("finding a conversation by its title", () => {
  const chats = [{ title: "Design a nanobody for TP53" }, { title: "Compare two RNA-seq runs" }, { title: "" }];

  it("is by the words typed, in any order and whatever their case, all of which a title must have", () => {
    expect(matchingTitles(chats, "nanobody").map((chat) => chat.title)).toEqual(["Design a nanobody for TP53"]);
    expect(matchingTitles(chats, "TP53 DESIGN").map((chat) => chat.title)).toEqual(["Design a nanobody for TP53"]);
    expect(matchingTitles(chats, "rna runs").map((chat) => chat.title)).toEqual(["Compare two RNA-seq runs"]);
    expect(matchingTitles(chats, "nanobody rna")).toEqual([]);
  });

  it("takes a conversation with no title for the name it is listed by", () => {
    expect(matchingTitles(chats, "new chat")).toEqual([{ title: "" }]);
  });

  it("gives all of them for nothing typed", () => {
    expect(matchingTitles(chats, "")).toBe(chats);
    expect(matchingTitles(chats, "  ")).toBe(chats);
  });
});

describe("conversations by day", () => {
  // Wednesday, in the time zone the tests are run in
  const now = new Date(2026, 4, 13, 15, 30);
  const at = (...parts: [number, number, number, number?, number?]) => new Date(...(parts as [number, number, number])).toISOString();
  const chat = (name: string, when: string | null, created: string | null = null) => ({ name, updated_at: when, created_at: created });
  const names = (days: ReturnType<typeof inDays<ReturnType<typeof chat>>>) => days.map((day) => [day.name, day.chats.map((each) => each.name)]);

  it("are today's, yesterday's, those of the week before that, and the rest, which come first in that order", () => {
    const days = inDays(
      [
        chat("old", at(2026, 3, 1, 10)),
        chat("week", at(2026, 4, 8, 23, 59)),
        chat("yesterday", at(2026, 4, 12, 0, 0)),
        chat("early today", at(2026, 4, 13, 0, 0)),
        chat("today", at(2026, 4, 13, 9, 0)),
      ],
      now,
    );

    expect(names(days)).toEqual([
      ["Today", ["early today", "today"]],
      ["Yesterday", ["yesterday"]],
      ["Previous 7 days", ["week"]],
      ["Earlier", ["old"]],
    ]);
  });

  it("have the days run from midnight, so that the last second of a day is not the next", () => {
    const days = inDays([chat("a", at(2026, 4, 12, 23, 59)), chat("b", at(2026, 4, 11, 23, 59)), chat("c", at(2026, 4, 5, 23, 59)), chat("d", at(2026, 4, 6, 0, 0))], now);

    expect(names(days)).toEqual([
      ["Yesterday", ["a"]],
      ["Previous 7 days", ["b", "d"]],
      ["Earlier", ["c"]],
    ]);
  });

  it("leave out a day with none, and keep the order given within a day", () => {
    const days = inDays([chat("second", at(2026, 4, 13, 9)), chat("first", at(2026, 4, 13, 14))], now);

    expect(names(days)).toEqual([["Today", ["second", "first"]]]);
    expect(inDays([], now)).toEqual([]);
  });

  it("go by when a conversation was last at work, or when it began if it has not been", () => {
    const days = inDays([chat("a", null, at(2026, 4, 13, 8)), chat("b", at(2026, 4, 1, 8), at(2026, 4, 13, 8))], now);

    expect(names(days)).toEqual([
      ["Today", ["a"]],
      ["Earlier", ["b"]],
    ]);
  });

  it("have a conversation with no date that can be read among the earlier ones, and one dated after now today's", () => {
    const days = inDays([chat("none", null), chat("bad", "yesterday-ish"), chat("future", at(2026, 4, 20, 8))], now);

    expect(names(days)).toEqual([
      ["Today", ["future"]],
      ["Earlier", ["none", "bad"]],
    ]);
  });

  it("are counted by the calendar across a month's end", () => {
    const early = new Date(2026, 5, 2, 12);

    expect(names(inDays([chat("a", at(2026, 4, 31, 12)), chat("b", at(2026, 4, 26, 12)), chat("c", at(2026, 4, 25, 12))], early))).toEqual([
      ["Previous 7 days", ["a", "b"]],
      ["Earlier", ["c"]],
    ]);
  });
});
