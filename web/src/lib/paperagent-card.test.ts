import { describe, expect, it } from "vitest";
import {
  approvalBlock,
  canChange,
  cardLines,
  cardSize,
  checkCardFact,
  describeEdits,
  describeStatus,
  describeWhose,
  draftOf,
  EMPTY_CARD_DRAFT,
  isAdded,
  MAX_DETAIL_CHARS,
  MAX_QUOTE_CHARS,
} from "./paperagent-card";
import type { CardFact, MethodCard, ReadAnchor } from "./types";

const anchor: ReadAnchor = { start: 10, end: 80, page: null, section: null };

// A fact as the server gives it when it is as it was read, which has no word of what it was read as
const read = (id: string): CardFact => ({ id, quote: `The words of ${id}.`, anchor, by: "reading" });
const added = (id: string, quote = ""): CardFact => ({ id, quote, anchor: null, by: "person", read_as: null, at: "2026-01-02T00:00:00Z" });
const changed = (id: string, readAs: Record<string, string>): CardFact => ({
  id,
  quote: `The words of ${id}.`,
  anchor,
  by: "person",
  read_as: readAs,
  at: "2026-01-02T00:00:00Z",
});

function card(changes: Partial<MethodCard> = {}): MethodCard {
  return {
    status: "draft",
    approved_at: null,
    changed_since_approval: false,
    edited: false,
    methods: [],
    datasets: [],
    scope: [],
    limitations: [],
    removed: { methods: [], datasets: [], scope: [], limitations: [] },
    ...changes,
  };
}

describe("the facts of the card", () => {
  it("are shown by what each says, with what it was read as if a person changed it", () => {
    const lines = cardLines(
      card({
        methods: [{ ...read("m1"), name: "STAR" }],
        datasets: [{ ...changed("d1", { name: "GEO", accession: "GSE1" }), name: "GEO", accession: "GSE2" }],
        scope: [{ ...changed("s1", { aspect: "species", value: "mouse" }), aspect: "species", value: "rat" }, { ...added("s2"), aspect: "sample size", value: "500" }],
        limitations: [read("l1")],
      }),
    );

    expect(lines.methods.map(({ title, tag, readAs }) => [title, tag, readAs])).toEqual([["STAR", null, null]]);
    expect(lines.datasets.map(({ title, tag, readAs }) => [title, tag, readAs])).toEqual([["GEO", "GSE2", "GEO, GSE1"]]);
    expect(lines.scope.map(({ title, tag, readAs }) => [title, tag, readAs])).toEqual([
      ["rat", "Species", "species: mouse"],
      ["500", "Sample size", null],
    ]);
    expect(lines.limitations.map(({ title, tag }) => [title, tag])).toEqual([[null, null]]);
    expect(lines.scope[0].fields).toEqual({ aspect: "species", value: "rat" });
    expect(lines.scope.map((line) => line.changed)).toEqual([true, false]);
    expect(lines.methods[0].changed).toBe(false);
  });

  it("are counted, and are the same shape when they were taken off", () => {
    const off = card({ methods: [{ ...read("m1"), name: "STAR" }], datasets: [{ ...read("d1"), name: "GEO", accession: "" }] });

    expect(cardSize(off)).toBe(2);
    expect(cardSize(card())).toBe(0);
    expect(cardLines(off.removed).methods).toEqual([]);
  });

  it("say whose they are, and a person's may be changed, and so may all but a limit that was read", () => {
    expect(describeWhose(read("m1"))).toBe("Read by the model");
    expect(describeWhose(added("m2"))).toBe("Added by you");
    expect(describeWhose(changed("m3", { name: "x" }))).toBe("Changed by you");
    expect(isAdded(added("m2"))).toBe(true);
    expect(isAdded(changed("m3", { name: "x" }))).toBe(false);
    expect(isAdded(read("m1"))).toBe(false);
    expect(canChange("methods", read("m1"))).toBe(true);
    expect(canChange("limitations", read("l1"))).toBe(false);
    expect(canChange("limitations", added("l2", "It is slow."))).toBe(true);
  });
});

describe("what the card is", () => {
  const now = new Date("2026-01-02T01:00:00Z");

  it("is a draft that a model made, until a person approves it", () => {
    const status = describeStatus(card(), now);

    expect(status.label).toBe("Draft");
    expect(status.text).toContain("all that was checked of a fact is that its words are in the paper");
  });

  it("is approved as a person reading it and letting it stand, which is not that it is right", () => {
    const status = describeStatus(card({ status: "approved", approved_at: "2026-01-02T00:00:00Z" }), now);

    expect(status.label).toBe("Approved");
    expect(status.text).toContain("You approved this card 1 h ago.");
    expect(status.text).toContain("which is not that it is right");
  });

  it("is a draft again if it was approved and has changed", () => {
    const status = describeStatus(card({ changed_since_approval: true }), now);

    expect(status.label).toBe("Draft");
    expect(status.text).toContain("has changed since");
  });

  it("says what a person did to it, and nothing if they did nothing", () => {
    expect(describeEdits(card())).toBeNull();
    expect(
      describeEdits(
        card({
          methods: [{ ...changed("m1", { name: "x" }), name: "y" }, { ...added("m2"), name: "z" }],
          scope: [{ ...added("s1"), aspect: "species", value: "rat" }],
          removed: { methods: [], datasets: [{ ...read("d1"), name: "GEO", accession: "" }], scope: [], limitations: [] },
        }),
      ),
    ).toBe("What you did to it: 1 changed, 2 added, 1 taken off.");
  });

  it("is not approved while the paper is being read, or with nothing on it", () => {
    const full = card({ methods: [{ ...read("m1"), name: "STAR" }] });

    expect(approvalBlock(full, false)).toBeNull();
    expect(approvalBlock(full, true)).toContain("being read");
    expect(approvalBlock(card(), false)).toContain("nothing on the card");
  });
});

describe("what a person says of a fact", () => {
  it("is a method with a name, which is tidied", () => {
    expect(checkCardFact("methods", { ...EMPTY_CARD_DRAFT, name: "  Our \n method  " }, true)).toEqual({
      value: { name: "Our method", quote: "" },
      problems: {},
    });
    expect(checkCardFact("methods", { ...EMPTY_CARD_DRAFT, name: "x" }, false).value).toEqual({ name: "x" });
  });

  it("is refused with nothing in the part that a fact must have", () => {
    expect(checkCardFact("methods", EMPTY_CARD_DRAFT, true).problems.name).toBe("Say what the method is called.");
    expect(checkCardFact("datasets", { ...EMPTY_CARD_DRAFT, accession: "GSE1" }, true).problems.name).toBe("Say what the dataset is called.");
    expect(checkCardFact("scope", EMPTY_CARD_DRAFT, true).problems.value).toBe("Say what it was tested on.");
    expect(checkCardFact("limitations", { ...EMPTY_CARD_DRAFT, quote: "   " }, true).problems.quote).toBe("Say the limit in words.");
  });

  it("is a dataset that may have no accession, and a scope that has an aspect", () => {
    expect(checkCardFact("datasets", { ...EMPTY_CARD_DRAFT, name: "GEO" }, false).value).toEqual({ name: "GEO", accession: "" });
    expect(checkCardFact("scope", { ...EMPTY_CARD_DRAFT, aspect: "assay", value: "snRNA-seq" }, false).value).toEqual({
      aspect: "assay",
      value: "snRNA-seq",
    });
    expect(checkCardFact("scope", { ...EMPTY_CARD_DRAFT, aspect: "colour", value: "red" }, false).problems.aspect).toContain("Say what it is about");
  });

  it("is a limit that is its words, and words are sent only of a fact that is a person's own", () => {
    expect(checkCardFact("limitations", { ...EMPTY_CARD_DRAFT, quote: " It is slow. " }, true).value).toEqual({ quote: "It is slow." });
    expect(checkCardFact("scope", { ...EMPTY_CARD_DRAFT, value: "rat", quote: "my words" }, false).value).toEqual({ aspect: "species", value: "rat" });
    expect(checkCardFact("scope", { ...EMPTY_CARD_DRAFT, value: "rat", quote: "my words" }, true).value).toEqual({
      aspect: "species",
      value: "rat",
      quote: "my words",
    });
  });

  it("has a limit to how long it is, counted as the server counts", () => {
    expect(checkCardFact("methods", { ...EMPTY_CARD_DRAFT, name: "x".repeat(MAX_DETAIL_CHARS) }, false).value).not.toBeNull();
    expect(checkCardFact("methods", { ...EMPTY_CARD_DRAFT, name: "x".repeat(MAX_DETAIL_CHARS + 1) }, false).problems.name).toContain("at most 300");
    expect(checkCardFact("methods", { ...EMPTY_CARD_DRAFT, name: "😀".repeat(MAX_DETAIL_CHARS) }, false).value).not.toBeNull();
    expect(checkCardFact("limitations", { ...EMPTY_CARD_DRAFT, quote: "x".repeat(MAX_QUOTE_CHARS + 1) }, true).problems.quote).toContain("at most 1,000");
  });

  it("begins, for a change, from what the fact says and its words", () => {
    const line = cardLines(card({ scope: [{ ...added("s1", "In the supplement"), aspect: "tissue", value: "liver" }] })).scope[0];

    expect(draftOf(line)).toEqual({ aspect: "tissue", name: "", accession: "", value: "liver", quote: "In the supplement" });
  });
});
