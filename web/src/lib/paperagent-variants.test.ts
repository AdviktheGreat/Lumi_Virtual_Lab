import { describe, expect, it } from "vitest";
import {
  checkVariant,
  claimLabel,
  describeChange,
  describeComparable,
  describeCounts,
  describeMade,
  describeOutcome,
  describeRun,
  describeRounds,
  emptyVariant,
  hasVariants,
  isPlain,
  offeredFor,
  parseValue,
  showValue,
  statusTitle,
  unusable,
  usable,
  type VariantDraft,
} from "./paperagent-variants";
import type { PaperAgentVariants, Variant, VariantArgument, VariantOption } from "./types";

const limits: PaperAgentVariants["limits"] = {
  most_changes: 2,
  max_value_chars: 40,
  max_note_chars: 20,
  most_kept: 100,
  default_minutes: 5,
  max_minutes: 30,
  default_repeats: 2,
  max_repeats: 5,
  default_gigabytes: 1,
  max_gigabytes: 4,
};

function argument(name: string, value: unknown, text: string, plain = true): VariantArgument {
  return { name, text, value, plain };
}

const scored: VariantOption = {
  claim: "c1",
  can: true,
  refused: null,
  function: "cellmapper.core.score",
  arguments: [
    argument("values", [1, 2, 3], "[1, 2, 3]"),
    argument("scale", 2, "2"),
    argument("weight", 0.5, "0.5"),
    argument("method", "mean", "'mean'"),
    argument("flag", null, "None"),
    argument("handle", null, "<object at 0x>", false),
    argument("big", null, "[" + "1, ".repeat(300) + "...", true),
    argument("ratio", 1, "1.0"),
  ],
};
const refused: VariantOption = { claim: "c2", can: false, refused: { code: "not_attempted", message: "That claim was not attempted" } };

function variants(part: Partial<PaperAgentVariants> = {}): PaperAgentVariants {
  return {
    id: "demo",
    ready: true,
    problem: null,
    reproduction: null,
    claims: [scored, refused],
    variants: [],
    stale: 0,
    counts: { variants: 0, comparable: 0, rounds_to_paper: 0 },
    job: null,
    meaning: "A variant is the call again.",
    limits,
    ...part,
  };
}

function draft(part: Partial<VariantDraft> = {}): VariantDraft {
  return { ...emptyVariant({ limits }, "c1"), ...part };
}

function variant(part: Partial<Variant> = {}): Variant {
  return {
    id: "0123456789ab",
    made_at: "2026-01-01T00:00:00Z",
    seconds: 12.4,
    limits: { minutes: 5, repeats: 2, gigabytes: 1 },
    note: null,
    claim: "c1",
    quote: "It reached an AUROC of 0.93.",
    number: "0.93",
    tutorial: { id: "01", path: "examples/demo.py" },
    call: 3,
    function: "cellmapper.core.score",
    where: "a call of cellmapper.core.score, at the result",
    path: [],
    changes: [{ name: "scale", was: 2, now: 3 }],
    claim_run: 0.93,
    control: { verdict: "match", gave: 0.93, differences: [], error: null },
    variant: { status: "gave", gave: 0.93, values: [0.93, 0.93], type: "float", error: null, differences: [] },
    comparable: true,
    rounds_to_paper: true,
    repeats: 2,
    tolerance: { relative: 0.001, absolute: 0.000001 },
    text: "With scale = 3 in place of 2, the call gave 0.93. This is a variant. It is not the paper's result, and the claim's own result is as it was.",
    ...part,
  };
}

describe("what may be changed", () => {
  it("is offered for the claims that a variant can be made of, and not for those that it cannot", () => {
    const some = variants();

    expect(usable(some).map((each) => each.claim)).toEqual(["c1"]);
    expect(unusable(some).map((each) => each.refused.message)).toEqual(["That claim was not attempted"]);
    expect(offeredFor(some, "c1")?.function).toBe("cellmapper.core.score");
    expect(offeredFor(some, "c2")).toBeUndefined();
    expect(offeredFor(some, "nope")).toBeUndefined();
  });

  it("starts with what the server says a call may take", () => {
    expect(emptyVariant({ limits })).toEqual({ claim: "", values: {}, minutes: "5", repeats: "2", gigabytes: "1", note: "" });
    expect(emptyVariant({ limits }, "c1").claim).toBe("c1");
  });
});

describe("a value that is typed", () => {
  it("is written as JSON", () => {
    expect(parseValue('"abc"', "method", 40)).toEqual({ ok: true, value: "abc" });
    expect(parseValue(" 2.5", "scale", 40)).toEqual({ ok: true, value: 2.5 });
    expect(parseValue("[1, 2]", "values", 40)).toEqual({ ok: true, value: [1, 2] });
    expect(parseValue("null", "flag", 40)).toEqual({ ok: true, value: null });
    expect(parseValue("false", "flag", 40)).toEqual({ ok: true, value: false });
    expect(parseValue('{"a": [1]}', "table", 40)).toEqual({ ok: true, value: { a: [1] } });
  });

  it("is refused if it is not, and says how it is written", () => {
    for (const typed of ["abc", "[1, 2", "'abc'", "1,5", "NaN"]) {
      const parsed = parseValue(typed, "method", 40);

      expect(parsed.ok).toBe(false);
      expect(!parsed.ok && parsed.problem).toContain("The new value for method is written as JSON");
    }
  });

  it("is refused if an argument cannot be given it, as a number that is not finite or a list that is too deep", () => {
    expect(parseValue("1e999", "scale", 40)).toEqual({ ok: false, problem: expect.stringContaining("not one that an argument is given as") });
    expect(parseValue("[[[[[[1]]]]]]", "values", 40).ok).toBe(false);
    expect(parseValue("[[[[[1]]]]]", "values", 40).ok).toBe(false);
    expect(parseValue("[[[[1]]]]", "values", 40).ok).toBe(true);
    expect(parseValue('{"$float": "nan"}', "table", 40).ok).toBe(false);
  });

  it("is refused if it is more JSON than the server takes", () => {
    const long = JSON.stringify("x".repeat(40));

    expect(parseValue(long, "method", 40)).toEqual({ ok: false, problem: "The new value for method is at most 40 characters of JSON." });
    expect(parseValue(JSON.stringify("x".repeat(38)), "method", 40).ok).toBe(true);
  });

  it("is plain if an argument can be given it", () => {
    expect(isPlain(null)).toBe(true);
    expect(isPlain([1, "a", true, null, { b: 2.5 }])).toBe(true);
    expect(isPlain(Number.POSITIVE_INFINITY)).toBe(false);
    expect(isPlain(undefined)).toBe(false);
    expect(isPlain(() => 1)).toBe(false);
  });
});

describe("what making a variant is asked for", () => {
  it("is the claim, the new value of each argument that was given one, and what the calls may take", () => {
    const checked = checkVariant(draft({ values: { values: "[4, 5, 6]", scale: "", method: ' "median" ' }, note: "  to see  " }), variants());

    expect(checked.problems).toEqual({});
    expect(checked.value).toEqual({
      claim: "c1",
      changes: { values: [4, 5, 6], method: "median" },
      minutes: 5,
      repeats: 2,
      gigabytes: 1,
      note: "to see",
    });
  });

  it("sends no note if there is none", () => {
    const checked = checkVariant(draft({ values: { scale: "3" }, note: "   " }), variants());

    expect(checked.value).toEqual({ claim: "c1", changes: { scale: 3 }, minutes: 5, repeats: 2, gigabytes: 1 });
    expect(checked.value).not.toHaveProperty("note");
  });

  it("needs a claim that a variant can be made of", () => {
    expect(checkVariant(draft({ claim: "" }), variants()).problems.claim).toBe("Choose the claim whose call is made again.");
    expect(checkVariant(draft({ claim: "gone" }), variants()).problems.claim).toBe("Choose the claim whose call is made again.");
    expect(checkVariant(draft({ claim: "c2" }), variants()).problems.claim).toBe("That claim was not attempted.");
    expect(checkVariant(draft({ claim: "c2" }), variants()).value).toBeNull();
  });

  it("needs at least one argument to change, and no more than the server takes", () => {
    expect(checkVariant(draft(), variants()).problems.changes).toBe("Give at least one argument a new value.");
    expect(checkVariant(draft({ values: { scale: "  " } }), variants()).problems.changes).toBe("Give at least one argument a new value.");
    const three = checkVariant(draft({ values: { scale: "3", weight: "0.7", method: '"median"' } }), variants());

    expect(three.problems.changes).toBe("At most 2 arguments are changed at once.");
    expect(three.value).toBeNull();
  });

  it("says which argument has a value that is wrong, and does not also say that none was given", () => {
    const checked = checkVariant(draft({ values: { scale: "three", method: '"median"' } }), variants());

    expect(checked.value).toBeNull();
    expect(checked.problems["value:scale"]).toContain("The new value for scale is written as JSON");
    expect(checked.problems["value:method"]).toBeUndefined();
    expect(checked.problems.changes).toBeUndefined();
  });

  it("is refused for a value that is what the argument was given", () => {
    const same = (name: string, typed: string) => checkVariant(draft({ values: { [name]: typed } }), variants()).problems[`value:${name}`];

    expect(same("scale", "2")).toBe("scale was given that value, so it is not a change.");
    expect(same("values", "[1,2,3]")).toBe("values was given that value, so it is not a change.");
    expect(same("method", '"mean"')).toBe("method was given that value, so it is not a change.");
    expect(same("flag", "null")).toBe("flag was given that value, so it is not a change.");
    expect(same("scale", "2.5")).toBeUndefined();
    expect(same("method", '"Mean"')).toBeUndefined();
  });

  it("is left to the server where the page cannot tell whether a number is the same, as 1 is not 1.0 to the code", () => {
    // The argument was given 1.0, which JSON read here gives as 1, which is a change to the call
    const checked = checkVariant(draft({ values: { ratio: "1" } }), variants());

    expect(checked.problems).toEqual({});
    expect(checked.value?.changes).toEqual({ ratio: 1 });
  });

  it("is left to the server for a value that was too long to be offered", () => {
    const checked = checkVariant(draft({ values: { big: "[1]" } }), variants());

    expect(checked.problems).toEqual({});
    expect(checked.value?.changes).toEqual({ big: [1] });
  });

  it("does not change an argument that cannot be", () => {
    const checked = checkVariant(draft({ values: { handle: "5", scale: "3" } }), variants());

    expect(checked.value?.changes).toEqual({ scale: 3 });
    expect(checkVariant(draft({ values: { handle: "5" } }), variants()).problems.changes).toBe("Give at least one argument a new value.");
  });

  it("is refused for time, repeats, and gigabytes that are not whole numbers within what the server takes", () => {
    const base = { values: { scale: "3" } };
    const problems = (part: Partial<VariantDraft>) => checkVariant(draft({ ...base, ...part }), variants()).problems;

    expect(problems({ minutes: "0" }).minutes).toBe("The most time that both calls may take together, in minutes, is a whole number from 1 to 30.");
    expect(problems({ minutes: "31" }).minutes).toContain("from 1 to 30");
    expect(problems({ minutes: "1.5" }).minutes).toContain("whole number");
    expect(problems({ minutes: "" }).minutes).toContain("whole number");
    expect(problems({ repeats: "6" }).repeats).toBe("How many times each call is made is a whole number from 1 to 5.");
    expect(problems({ gigabytes: "5" }).gigabytes).toBe("The most that a call may write, in gigabytes, is a whole number from 1 to 4.");
    expect(checkVariant(draft({ ...base, minutes: "30", repeats: "5", gigabytes: "4" }), variants()).value).toMatchObject({ minutes: 30, repeats: 5, gigabytes: 4 });
  });

  it("is refused for a note that is too long or has a line break", () => {
    const base = { values: { scale: "3" } };

    expect(checkVariant(draft({ ...base, note: "x".repeat(20) }), variants()).problems.note).toBeUndefined();
    expect(checkVariant(draft({ ...base, note: "x".repeat(21) }), variants()).problems.note).toBe("A note is at most 20 characters.");
    // A character of more than one UTF-16 unit is one, as the server counts
    expect(checkVariant(draft({ ...base, note: "😀".repeat(20) }), variants()).problems.note).toBeUndefined();
    expect(checkVariant(draft({ ...base, note: "one\ntwo" }), variants()).problems.note).toBe("A note has no line breaks or other control characters.");
  });
});

describe("what is said of a variant", () => {
  it("says what happened to each, in words and not only a colour", () => {
    expect(statusTitle("gave")).toBe("Gave a number");
    expect(statusTitle("no_place")).toBe("Gave no number at the place");
    expect(statusTitle("unstable")).toBe("Gave something else each time");
    expect(statusTitle("error")).toBe("Stopped with an error");
    expect(statusTitle("not_run")).toBe("Was not made in the time");
    expect(statusTitle("new")).toBe("new");
  });

  it("says what the call gave with the changes, beside what the claim was held to gave", () => {
    expect(describeOutcome(variant())).toBe("It gave 0.93, where the call that the claim was held to gave 0.93.");
    const other = (part: Partial<Variant["variant"]>) => describeOutcome(variant({ variant: { ...variant().variant, gave: null, ...part } }));

    expect(other({ status: "no_place", type: "list" })).toBe("It ran, and gave a list with no number at the place that the claim was held to.");
    expect(other({ status: "no_place", type: null })).toBe("It ran, and gave something with no number at the place that the claim was held to.");
    expect(other({ status: "unstable" })).toBe("It gave something else each time it was made, so no one number is said.");
    expect(other({ status: "error", error: { type: "ValueError", message: "bad scale" } })).toBe("It stopped with ValueError: bad scale.");
    expect(other({ status: "error", error: null })).toBe("It stopped with an error.");
    expect(other({ status: "not_run" })).toBe("It was not made in the time that was given.");
  });

  it("says what was changed and what it was", () => {
    expect(describeChange({ name: "scale", was: 2, now: 3 })).toBe("scale: 3 in place of 2");
    expect(describeChange({ name: "method", was: "mean", now: "median" })).toBe('method: "median" in place of "mean"');
    expect(describeChange({ name: "values", was: [1, 2, 3], now: null })).toBe("values: null in place of [1,2,3]");
    expect(showValue("x".repeat(100)).length).toBe(61);
    expect(showValue(undefined)).toBe("");
  });

  it("says whether it can be set beside what the claim was held to, and why not", () => {
    expect(describeComparable(variant())).toContain("Comparable: the same call with nothing changed gave what the tutorial got");
    const differs = describeComparable(variant({ comparable: false, control: { verdict: "differs", gave: null, differences: [], error: null } }));

    expect(differs).toBe("Not comparable: the same call with nothing changed did not give what the tutorial got, so the call alone does not stand for what the tutorial did.");
    expect(describeComparable(variant({ comparable: false, control: { verdict: "error", gave: null, differences: [], error: null } }))).toContain("stopped with an error");
    expect(describeComparable(variant({ comparable: false, control: { verdict: "not_run", gave: null, differences: [], error: null } }))).toContain("was not made");
    expect(
      describeComparable(variant({ comparable: false, variant: { ...variant().variant, status: "no_place", gave: null } })),
    ).toBe("Not comparable: the same call with nothing changed gave what the tutorial got, but the variant gave no number to set beside the claim's.");
  });

  it("says that a number that rounds to the paper's is not a reproduction, and says nothing if there is no number", () => {
    expect(describeRounds(variant())).toBe("The number that it gave rounds to the paper's 0.93. That is not a reproduction of the paper's result.");
    expect(describeRounds(variant({ rounds_to_paper: false }))).toBe("The number that it gave does not round to the paper's 0.93.");
    expect(describeRounds(variant({ rounds_to_paper: null }))).toBeNull();
  });

  it("says how it was made", () => {
    const made = describeMade(variant({ made_at: new Date().toISOString() }));

    expect(made).toBe("Made just now, which took 12 s. Each call was made 2 times, for at most 5 minutes and 1 gigabyte written.");
    expect(describeMade(variant({ made_at: "nonsense", seconds: -1, repeats: 1, limits: { minutes: 1, repeats: 1, gigabytes: 2 } }))).toBe(
      "Made a while ago. Each call was made 1 time, for at most 1 minute and 2 gigabytes written.",
    );
  });

  it("says what it was made of, and where what it gave parted from what the tutorial got", () => {
    expect(describeRun(variant())).toEqual([
      "The claim was held to a call of cellmapper.core.score, at the result, run by examples/demo.py, which gave 0.93.",
      "With the changes, the 2 times it was made gave: 0.93, 0.93.",
      "With nothing changed, it gave 0.93 at the same place.",
      "Numbers are taken as the same within a relative difference of 0.001 or an absolute one of 0.000001.",
    ]);
    const worse = describeRun(
      variant({
        control: { verdict: "differs", gave: null, differences: ["result: 0.7 against 0.93"], error: null },
        variant: { status: "error", gave: null, values: [], type: null, error: { type: "ValueError", message: "bad scale" }, differences: [] },
      }),
    );

    expect(worse).toContain("With nothing changed, it differs from what the tutorial got: result: 0.7 against 0.93.");
    expect(worse).toContain("With the changes, it stopped with ValueError: bad scale.");
    expect(worse.some((line) => line.startsWith("With nothing changed, it gave"))).toBe(false);
    expect(worse.some((line) => line.startsWith("With the changes, the"))).toBe(false);
    const unlike = describeRun(
      variant({
        control: { verdict: "error", gave: null, differences: [], error: { type: "KeyError", message: "x" } },
        variant: { status: "unstable", gave: null, values: [0.5, null], type: "float", error: null, differences: ["result: 0.5 against 0.6"] },
      }),
    );

    expect(unlike).toContain("With nothing changed, it stopped with KeyError: x.");
    expect(describeRun(variant({ variant: { ...variant().variant, status: "error", gave: null, error: { type: "E", message: "No more." }, differences: [] } }))).toContain(
      "With the changes, it stopped with E: No more.",
    );
    expect(unlike).toContain("With the changes, the 2 times it was made gave: 0.5, no number.");
    expect(unlike).toContain("With the changes, the times it was made differ: result: 0.5 against 0.6.");
  });

  it("counts them, and says how many are kept that are not shown", () => {
    expect(describeCounts({ variants: 0, comparable: 0, rounds_to_paper: 0 }, 0)).toBe("No variant has been made.");
    expect(describeCounts({ variants: 3, comparable: 2, rounds_to_paper: 1 }, 0)).toBe(
      "3 variants: 2 comparable, 1 that gives a number that rounds to the paper's. None of them is the paper's result.",
    );
    expect(describeCounts({ variants: 1, comparable: 1, rounds_to_paper: 0 }, 0)).toContain("1 variant: 1 comparable, 0 that give a number");
    expect(describeCounts({ variants: 0, comparable: 0, rounds_to_paper: 0 }, 1)).toBe(
      "No variant has been made. 1 variant made of another run of the tutorials, other claims, or another trying is kept and not shown.",
    );
    expect(describeCounts({ variants: 0, comparable: 0, rounds_to_paper: 0 }, 4)).toContain("4 variants made of another run");
    expect(describeCounts({ variants: 0, comparable: 0, rounds_to_paper: 0 }, 4)).toContain("are kept and not shown");
  });

  it("is something to take away if any is kept, shown or not", () => {
    expect(hasVariants({ variants: [], stale: 0 })).toBe(false);
    expect(hasVariants({ variants: [variant()], stale: 0 })).toBe(true);
    expect(hasVariants({ variants: [], stale: 2 })).toBe(true);
  });

  it("names a claim by its number and what it says, cut if it is long", () => {
    expect(claimLabel({ value: "0.93", quote: "It reached 0.93." }, "c1")).toBe("0.93: It reached 0.93.");
    expect(claimLabel({ value: "", quote: "No number." }, "c1")).toBe("No number.");
    expect(claimLabel({ value: "1", quote: "x".repeat(100) }, "c1")).toBe(`1: ${"x".repeat(60)}…`);
    expect(claimLabel(undefined, "c9")).toBe("c9");
  });
});
