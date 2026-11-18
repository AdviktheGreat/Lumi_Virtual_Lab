import { describe, expect, it } from "vitest";
import {
  answersOf,
  cardVersion,
  checkScope,
  describeAspect,
  describeOutcome,
  describeReading,
  describeStatementPlace,
  describeStatementWhose,
  EMPTY_SCOPE_DRAFT,
  MAX_SCOPE_CHARS,
  MAX_SIZE,
  MAX_UNIT_CHARS,
  OUTCOME_TEXT,
} from "./paperagent-scope";
import type { CardScope, MethodCard, ScopeAnswer, ScopeCheck, ScopeStatement } from "./types";

const said = (changes: Partial<typeof EMPTY_SCOPE_DRAFT>) => ({ ...EMPTY_SCOPE_DRAFT, ...changes });

describe("what a person says of their data", () => {
  it("is sent as the parts they filled in, and what was left blank is left out", () => {
    const { value, problems } = checkScope(said({ species: "  Mus   musculus ", format: "h5ad", size: "500", unit: " nuclei " }));

    expect(problems).toEqual({});
    expect(value).toEqual({ species: "Mus musculus", input_format: "h5ad", sample_size: 500, sample_unit: "nuclei" });
  });

  it("takes a size with commas between its thousands, and no other", () => {
    expect(checkScope(said({ size: "12,000" })).value).toEqual({ sample_size: 12000 });
    expect(checkScope(said({ size: "1,2,3" })).problems.size).toBeDefined();
    expect(checkScope(said({ size: "1,00" })).problems.size).toBeDefined();
  });

  it.each(["0", "-5", "1.5", "ten", "1e3", `${MAX_SIZE + 1}`, "99999999999999999999"])("refuses %s as a size", (size) => {
    const checked = checkScope(said({ species: "human", size }));

    expect(checked.value).toBeNull();
    expect(checked.problems.size).toBe("The sample size is a whole number, one or more.");
  });

  it("takes the largest size that the server takes", () => {
    expect(checkScope(said({ size: `${MAX_SIZE}` })).value).toEqual({ sample_size: MAX_SIZE });
  });

  it("needs a size to be said for what it counts", () => {
    const checked = checkScope(said({ species: "human", unit: "cells" }));

    expect(checked.value).toBeNull();
    expect(checked.problems.unit).toBe("Say the sample size as well, or leave this out.");
  });

  it("is not sent without something said of the data", () => {
    const checked = checkScope(said({ species: "  ", unit: "" }));

    expect(checked.value).toBeNull();
    expect(checked.problems.form).toMatch(/Say something of your data/);
  });

  it("has what is too long refused, in characters as the server counts them", () => {
    expect(checkScope(said({ tissue: "x".repeat(MAX_SCOPE_CHARS) })).value).not.toBeNull();
    expect(checkScope(said({ tissue: "x".repeat(MAX_SCOPE_CHARS + 1) })).problems.tissue).toBe(`That is at most ${MAX_SCOPE_CHARS} characters.`);
    expect(checkScope(said({ tissue: "🧬".repeat(MAX_SCOPE_CHARS) })).value).not.toBeNull();
    expect(checkScope(said({ size: "5", unit: "x".repeat(MAX_UNIT_CHARS + 1) })).problems.unit).toBe(`That is at most ${MAX_UNIT_CHARS} characters.`);
  });

  it("does not say there is nothing said when a part that was said is wrong", () => {
    expect(checkScope(said({ size: "many" })).problems.form).toBeUndefined();
  });
});

const statement = (changes: Partial<ScopeStatement> = {}): ScopeStatement => ({
  id: "scope-1",
  value: "mouse",
  quote: "We used mouse.",
  by: "reading",
  changed: false,
  page: 2,
  section: "Methods",
  ...changes,
});

const answer = (outcome: ScopeAnswer["outcome"], aspect: ScopeAnswer["aspect"] = "species"): ScopeAnswer => ({
  aspect,
  given: "rat",
  outcome,
  says: [statement()],
  reason: "",
});

function check(changes: Partial<ScopeCheck> = {}): ScopeCheck {
  return {
    id: "a1",
    outcome: "inside",
    aspects: [],
    warnings: [],
    not_checked: [],
    card: { status: "draft", approved_at: null, changed_since_approval: false, edited: false, scope_facts: 1 },
    reading: { complete: true, chunks: 4, read: 4, failed: 0 },
    notes: [],
    ...changes,
  };
}

describe("what the card says of the data", () => {
  it("is outside with the number of things that are, and never that the method fails", () => {
    expect(describeOutcome(check({ outcome: "outside", warnings: ["a"] })).text).toMatch(/^One thing is outside\./);
    expect(describeOutcome(check({ outcome: "outside", warnings: ["a", "b"] })).text).toMatch(/^2 things are outside\./);
    expect(describeOutcome(check({ outcome: "outside", warnings: ["a"] })).text).toContain("You can go on.");
    expect(OUTCOME_TEXT.outside.text).toContain("not that it fails");
  });

  it("is inside without saying that the method works on it", () => {
    expect(describeOutcome(check({ outcome: "inside" })).text).toContain("not that it works on yours");
  });

  it("is not covered without being called inside or warned of", () => {
    const text = describeOutcome(check({ outcome: "not covered" })).text;

    expect(text).toContain("not called inside");
    expect(text).toContain("not warned of");
  });

  it("has its answers told apart by outcome, in the order they were checked", () => {
    const aspects = [answer("outside", "species"), answer("inside", "tissue"), answer("outside", "assay")];

    expect(answersOf(check({ aspects }), "outside").map((a) => a.aspect)).toEqual(["species", "assay"]);
    expect(describeAspect("sample size")).toBe("Sample size");
  });
});

describe("a statement of the card that data was put against", () => {
  it("is the model's, or the person's if they changed it or added it", () => {
    expect(describeStatementWhose(statement())).toBe("Read by the model");
    expect(describeStatementWhose(statement({ by: "person", changed: true }))).toBe("Changed by you");
    expect(describeStatementWhose(statement({ by: "person", changed: false, page: null, section: null }))).toBe("Added by you");
  });

  it("has the place in the paper that it has, and none if it has none", () => {
    expect(describeStatementPlace(statement())).toBe("Page 2, Methods");
    expect(describeStatementPlace(statement({ section: null }))).toBe("Page 2");
    expect(describeStatementPlace(statement({ page: null }))).toBe("Methods");
    expect(describeStatementPlace(statement({ page: null, section: "" }))).toBeNull();
    expect(describeStatementPlace(statement({ page: null, section: null }))).toBeNull();
  });
});

describe("how far the paper was read, where the card is from it", () => {
  it("is not said when the paper was read to its end", () => {
    expect(describeReading(check())).toBeNull();
  });

  it("is said when the paper was read in part, with the parts that could not be", () => {
    expect(describeReading(check({ reading: { complete: false, chunks: 5, read: 3, failed: 1 } }))).toBe(
      "The paper was not read to its end (3 of 5 parts were read, 1 could not be), so the card may lack some of what it says.",
    );
    expect(describeReading(check({ reading: { complete: false, chunks: 5, read: 3, failed: 0 } }))).not.toContain("could not be");
  });

  it("is said when the paper was not read", () => {
    expect(describeReading(check({ reading: { complete: false, chunks: null, read: 0, failed: 0 } }))).toBe(
      "The paper has not been read, so the card is what a person put on it.",
    );
  });
});

const scopeFact = (changes: Partial<CardScope> = {}): CardScope => ({
  id: "s1",
  quote: "We used mouse.",
  anchor: null,
  by: "reading",
  aspect: "species",
  value: "mouse",
  ...changes,
});

function card(changes: Partial<MethodCard> = {}): MethodCard {
  return {
    status: "draft",
    approved_at: null,
    changed_since_approval: false,
    edited: false,
    methods: [],
    datasets: [],
    scope: [scopeFact()],
    limitations: [],
    removed: { methods: [], datasets: [], scope: [], limitations: [] },
    ...changes,
  };
}

describe("the version of the card that an answer is of", () => {
  it("is the same for the same card", () => {
    expect(cardVersion(card())).toBe(cardVersion(card()));
  });

  it("differs when a statement is changed, added, or taken off, or whose it is", () => {
    const was = cardVersion(card());

    expect(cardVersion(card({ scope: [scopeFact({ value: "rat" })] }))).not.toBe(was);
    expect(cardVersion(card({ scope: [scopeFact({ aspect: "tissue" })] }))).not.toBe(was);
    expect(cardVersion(card({ scope: [scopeFact({ quote: "Another." })] }))).not.toBe(was);
    expect(cardVersion(card({ scope: [scopeFact({ by: "person" })] }))).not.toBe(was);
    expect(cardVersion(card({ scope: [scopeFact(), scopeFact({ id: "s2", value: "rat" })] }))).not.toBe(was);
    expect(cardVersion(card({ scope: [] }))).not.toBe(was);
  });

  it("differs when the card is approved, or approved and changed", () => {
    const was = cardVersion(card());

    expect(cardVersion(card({ status: "approved", approved_at: "2026-01-02T00:00:00Z" }))).not.toBe(was);
    expect(cardVersion(card({ changed_since_approval: true }))).not.toBe(was);
  });

  it("does not differ for what the answer does not depend on", () => {
    expect(cardVersion(card({ methods: [{ id: "m1", quote: "", anchor: null, by: "person", name: "STAR" }] }))).toBe(cardVersion(card()));
  });

  it("does not run two statements together into one", () => {
    expect(cardVersion(card({ scope: [scopeFact({ id: "s1", value: "a" }), scopeFact({ id: "s2", value: "b" })] }))).not.toBe(
      cardVersion(card({ scope: [scopeFact({ id: "s1", value: "a\u0002s2" })] })),
    );
  });
});
