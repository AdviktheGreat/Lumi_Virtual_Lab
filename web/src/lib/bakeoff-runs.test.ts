import { describe, expect, it } from "vitest";
import {
  answeredCount,
  callOf,
  checkArguments,
  checkRun,
  checkTolerance,
  chosenCount,
  comparisonKey,
  dataPlace,
  describeAgreement,
  describeArguments,
  describeAsking,
  describeBy,
  describeGroundTruth,
  describeKept,
  describeOutcomes,
  describePairKept,
  describePreview,
  describeProposing,
  describeRank,
  describeReading,
  describeRunAll,
  describeRunData,
  describeScore,
  describeScoreDetail,
  describeSeconds,
  describeSince,
  describeSinceShort,
  describeTolerance,
  describeWhy,
  EMPTY_RUN,
  EMPTY_TOLERANCE,
  isRunnable,
  KEPT_LABELS,
  keptAs,
  MAX_ARGUMENTS_CHARS,
  nameOf,
  ordinal,
  proposedCount,
  proposingCount,
  runnableCount,
  tableAddress,
  toleranceQuery,
  type CallDraft,
  type RunDraft,
} from "./bakeoff-runs";
import type {
  Bakeoff,
  BakeoffComparedMethod,
  BakeoffGroundTruth,
  BakeoffMethod,
  BakeoffRunSummary,
  BakeoffScore,
} from "./types";

const LIMITS = { max_candidates: 3 };

function method(id: string, built = true, changes: Partial<BakeoffMethod> = {}): BakeoffMethod {
  return {
    id,
    name: `Method ${id}`,
    paper: { kind: "doi", doi: "10.1/x" },
    title: "",
    repo: null,
    suggested: [],
    added_by: "person",
    added_at: "2026-01-01T00:00:00Z",
    found: null,
    fit: null,
    agent: built ? ({ id: `agent-${id}`, title: "Agent", repo: null, steps: {} } as unknown as BakeoffMethod["agent"]) : null,
    standing: { state: built ? "built" : "new", step: null, reason: "" },
    scope: {} as BakeoffMethod["scope"],
    run: null,
    ...changes,
  };
}

function draft(calls: Record<string, Partial<CallDraft>>, minutes = "5"): RunDraft {
  return {
    minutes,
    calls: Object.fromEntries(Object.entries(calls).map(([id, call]) => [id, { run: true, mode: "say" as const, tool: "", args: "", ...call }])),
  };
}

function score(changes: Partial<BakeoffScore> = {}): BakeoffScore {
  return {
    scored: true,
    why: null,
    reason: "",
    by: "position",
    matched: 8,
    of: 10,
    score: 0.8,
    missing: 0,
    extra: 0,
    examples: [],
    rank: 1,
    ...changes,
  };
}

function compared(id: string, changes: Partial<BakeoffComparedMethod> = {}): BakeoffComparedMethod {
  return {
    id,
    name: `Method ${id}`,
    title: "",
    agent: null,
    state: "ran",
    why: null,
    reason: "",
    tier: "A",
    tool: "run",
    seconds: 1,
    cost: { reading: 0.5, asking: 0 },
    by: "person",
    kept: "whole",
    since: [],
    score: null,
    agrees: [],
    differs: [],
    unknown: [],
    ...changes,
  };
}

describe("which methods can be run", () => {
  it("is only a method that is built and has a PaperAgent", () => {
    expect(isRunnable(method("a"))).toBe(true);
    expect(isRunnable(method("b", false))).toBe(false);
    expect(isRunnable(method("c", true, { standing: { state: "building", step: "tools", reason: "" } }))).toBe(false);
    expect(isRunnable(method("d", true, { agent: null }))).toBe(false);
  });

  it("counts them", () => {
    expect(runnableCount([method("a"), method("b", false), method("c")])).toBe(2);
    expect(runnableCount([])).toBe(0);
  });

  it("says where the data is in the container", () => {
    expect(dataPlace("counts.csv")).toBe("/data/counts.csv");
  });
});

describe("the arguments of a call", () => {
  it("are none if they are blank", () => {
    expect(checkArguments("")).toEqual({ value: {} });
    expect(checkArguments("  \n ")).toEqual({ value: {} });
  });

  it("are an object of JSON", () => {
    expect(checkArguments('{"path": "/data/a.csv", "n": 3, "flags": [true, null], "nested": {"x": 1.5}}').value).toEqual({
      path: "/data/a.csv",
      n: 3,
      flags: [true, null],
      nested: { x: 1.5 },
    });
  });

  it("are refused when they are not JSON", () => {
    expect(checkArguments("{path: 1}").problem).toMatch(/JSON/);
    expect(checkArguments("{").value).toBeNull();
    expect(checkArguments("NaN").value).toBeNull();
  });

  it("are refused when they are not an object", () => {
    for (const text of ["[1, 2]", "null", "3", '"text"', "true"]) {
      const checked = checkArguments(text);
      expect(checked.value).toBeNull();
      expect(checked.problem).toMatch(/object/);
    }
  });

  it("are refused when a number would not be sent as it was typed", () => {
    expect(checkArguments('{"n": 1e999}').problem).toMatch(/too big/);
    expect(checkArguments('{"n": 12345678901234567890}').problem).toMatch(/too many digits/);
    expect(checkArguments('{"n": 3.0}').problem).toMatch(/Write it as 3/);
    expect(checkArguments('{"n": 1e3}').problem).toMatch(/Write it as 1000/);
    expect(checkArguments('{"n": -2.00}').problem).toMatch(/Write it as -2/);
  });

  it("takes a number that is exact, and ones that are not whole", () => {
    expect(checkArguments('{"n": 9007199254740991}').value).toEqual({ n: 9007199254740991 });
    expect(checkArguments('{"n": 0.5, "m": 1e-7, "k": -0}').problem).toBeUndefined();
    expect(checkArguments('{"n": 0.1}').value).toEqual({ n: 0.1 });
  });

  it("do not take what is in a string for a number", () => {
    expect(checkArguments('{"name": "3.0 and 12345678901234567890 and 1e999"}').value).toEqual({
      name: "3.0 and 12345678901234567890 and 1e999",
    });
    expect(checkArguments('{"a\\"1.0": 2}').value).toEqual({ 'a"1.0': 2 });
  });

  it("are at most as many characters as the server takes", () => {
    // {"text":"…"} is eleven characters of its own
    const fits = `{"text": "${"a".repeat(MAX_ARGUMENTS_CHARS - 11)}"}`;
    expect(checkArguments(fits).value === null).toBe(false);
    const over = `{"text": "${"a".repeat(MAX_ARGUMENTS_CHARS - 10)}"}`;
    expect(checkArguments(over).value === null).toBe(true);
    expect(checkArguments(over).problem).toMatch(/20,000/);
  });

  it("are counted by what is sent, and not by the spaces typed", () => {
    const spaced = `{"text":${" ".repeat(MAX_ARGUMENTS_CHARS)}"a"}`;
    expect(checkArguments(spaced).value).toEqual({ text: "a" });
  });
});

describe("what is sent to run the methods", () => {
  const methods = [method("a"), method("b"), method("c", false), method("d")];

  it("is the call of each method that was chosen, and the minutes", () => {
    const checked = checkRun(draft({ a: { tool: "run", args: '{"path": "/data/x"}' }, b: { mode: "propose" } }, "10"), methods, LIMITS);
    expect(checked.problems).toEqual({});
    expect(checked.value).toEqual({ calls: { a: { tool: "run", arguments: { path: "/data/x" } }, b: { propose: true } }, minutes: 10 });
  });

  it("gives no arguments as an empty object", () => {
    expect(checkRun(draft({ a: { tool: " run " } }), methods, LIMITS).value?.calls.a).toEqual({ tool: "run", arguments: {} });
  });

  it("leaves out a method that was not chosen", () => {
    const checked = checkRun(draft({ a: { tool: "run" }, b: { run: false, tool: "other" } }), methods, LIMITS);
    expect(Object.keys(checked.value?.calls ?? {})).toEqual(["a"]);
  });

  it("leaves out a method that is not built, as the server would keep it as not run in place of its last run", () => {
    const checked = checkRun(draft({ a: { tool: "run" }, c: { tool: "run" } }), methods, LIMITS);
    expect(Object.keys(checked.value?.calls ?? {})).toEqual(["a"]);
  });

  it("leaves out what was said of a method that is no longer there", () => {
    const checked = checkRun(draft({ a: { tool: "run" }, gone: { tool: "run" } }), methods, LIMITS);
    expect(Object.keys(checked.value?.calls ?? {})).toEqual(["a"]);
  });

  it("asks for a method to be chosen", () => {
    expect(checkRun(EMPTY_RUN, methods, LIMITS)).toEqual({ value: null, problems: { calls: "Choose at least one method to run." } });
    expect(checkRun(draft({ c: { tool: "run" } }), methods, LIMITS).problems.calls).toBeDefined();
    expect(checkRun(draft({ a: { run: false, tool: "run" } }), methods, LIMITS).problems.calls).toBeDefined();
  });

  it("asks for a tool where the person chooses the call", () => {
    const checked = checkRun(draft({ a: { tool: "  " }, b: { tool: "run" } }), methods, LIMITS);
    expect(checked.value).toBeNull();
    expect(checked.problems["a:tool"]).toMatch(/Method a/);
    expect(checked.problems["b:tool"]).toBeUndefined();
    expect(checked.problems.calls).toBeUndefined();
  });

  it("does not ask for a tool where a model proposes the call", () => {
    expect(checkRun(draft({ a: { mode: "propose", tool: "", args: "not json" } }), methods, LIMITS).value).toEqual({
      calls: { a: { propose: true } },
      minutes: 5,
    });
  });

  it("does not send a tool and arguments along with a proposal", () => {
    const call = checkRun(draft({ a: { mode: "propose", tool: "run", args: '{"x": 1}' } }), methods, LIMITS).value?.calls.a;
    expect(call).toEqual({ propose: true });
  });

  it("says what is wrong with the arguments of a method", () => {
    const checked = checkRun(draft({ a: { tool: "run", args: "[1]" }, b: { tool: "run" } }), methods, LIMITS);
    expect(checked.value).toBeNull();
    expect(checked.problems["a:args"]).toMatch(/object/);
    expect(checked.problems["b:args"]).toBeUndefined();
  });

  it("refuses a tool name that is longer than the server takes", () => {
    expect(checkRun(draft({ a: { tool: "t".repeat(100) } }), methods, LIMITS).value).not.toBeNull();
    expect(checkRun(draft({ a: { tool: "t".repeat(101) } }), methods, LIMITS).problems["a:tool"]).toMatch(/100/);
  });

  it("refuses more methods than there can be", () => {
    const many = [method("a"), method("b"), method("c"), method("d")];
    const checked = checkRun(draft({ a: { tool: "x" }, b: { tool: "x" }, c: { tool: "x" }, d: { tool: "x" } }), many, LIMITS);
    expect(checked.value).toBeNull();
    expect(checked.problems.calls).toMatch(/3 methods/);
    expect(checkRun(draft({ a: { tool: "x" }, b: { tool: "x" }, c: { tool: "x" } }), many, LIMITS).value).not.toBeNull();
  });

  it("takes the minutes as a whole number from 1 to 30", () => {
    const calls = { a: { tool: "run" } };
    expect(checkRun(draft(calls, "1"), methods, LIMITS).value?.minutes).toBe(1);
    expect(checkRun(draft(calls, "30"), methods, LIMITS).value?.minutes).toBe(30);
    for (const bad of ["0", "31", "", "2.5", "-1", "five"]) {
      const checked = checkRun(draft(calls, bad), methods, LIMITS);
      expect(checked.value).toBeNull();
      expect(checked.problems.minutes).toMatch(/1 to 30/);
    }
  });

  it("starts with five minutes and no method chosen", () => {
    expect(EMPTY_RUN.minutes).toBe("5");
    expect(callOf(EMPTY_RUN, "a")).toEqual({ run: false, mode: "say", tool: "", args: "" });
  });

  it("counts what was chosen, and what a model is to propose", () => {
    const chosen = draft({ a: { tool: "run" }, b: { mode: "propose" }, c: { mode: "propose" }, d: { run: false, mode: "propose" } });
    expect(chosenCount(chosen, methods)).toBe(2);
    expect(proposingCount(chosen, methods)).toBe(1);
    // One that the person gives the call of is not one that a model is to propose, whatever else is counted
    const more = draft({ a: { tool: "run" }, b: { tool: "run" }, d: { mode: "propose" } });
    expect(proposingCount(more, methods)).toBe(1);
    expect(proposingCount(draft({ a: { tool: "run" }, b: { tool: "run" } }), methods)).toBe(0);
    const checked = checkRun(chosen, methods, LIMITS);
    expect(checked.value !== null && proposedCount(checked.value)).toBe(1);
  });

  it("says what the button does", () => {
    expect(describeRunAll(0)).toBe("Run the methods");
    expect(describeRunAll(1)).toBe("Run 1 method");
    expect(describeRunAll(3)).toBe("Run 3 methods");
  });

  it("says what is spent only when a model proposes", () => {
    expect(describeProposing(0)).toMatch(/Nothing is spent/);
    expect(describeProposing(1)).toMatch(/^1 model call will be paid for/);
    expect(describeProposing(2)).toMatch(/^2 model calls will be paid for/);
  });
});

describe("how a run ended", () => {
  it("says why a call failed or was not made, in words", () => {
    expect(describeWhy("failed", "timed_out")).toBe("It ran out of time");
    expect(describeWhy("not_run", "outside")).toBe("Your data is outside what its card says");
    expect(describeWhy("not_run", "not_yet")).toBe("It has not been run");
    expect(describeWhy("failed", "something_new")).toBe("Something new");
  });

  it("says nothing of why for a method that ran", () => {
    expect(describeWhy("ran", null)).toBeNull();
    expect(describeWhy("ran", "error")).toBeNull();
    expect(describeWhy("failed", null)).toBeNull();
  });

  it("says where a method that is not built stands", () => {
    expect(describeWhy("not_built", "waiting")).toBe("Waiting for you");
    expect(describeWhy("not_built", "blocked")).toBe("Cannot be built");
    expect(describeWhy("not_built", "odd_reason")).toBe("Odd reason");
  });

  it("tells how much of a result was kept as the server does", () => {
    expect(keptAs({ type: "list", value: [1] })).toBe("whole");
    expect(keptAs({ type: "list", value: null })).toBe("whole");
    expect(keptAs({ type: "DataFrame", shape: [2, 2], values: [[1]], repr: "…" })).toBe("look");
    expect(keptAs({ type: "DataFrame", chars: 900000, sha256: "a".repeat(64) })).toBe("hash");
    expect(keptAs({ type: "DataFrame", chars: 12, repr: "x" })).toBe("look");
    expect(keptAs({ type: "object" })).toBe("look");
  });

  it("says what was kept", () => {
    expect(describeKept("whole")).toBe("All of it was kept");
    expect(describeKept("look")).toMatch(/not all of it/);
    expect(describeKept("hash")).toMatch(/hash/);
  });

  it("describes the start of a result", () => {
    const preview = { type: "dict", plain: true, chars: 1234, start: "{}", cut: true };
    expect(describePreview(preview)).toBe("A dict, 1,234 characters as JSON.");
    expect(describePreview({ ...preview, plain: false })).toMatch(/more than could be kept as it was/);
  });

  it("says who chose the call and what it cost", () => {
    const person = { by: "person", proposed: null } as const;
    expect(describeBy(person)).toBe("You chose the call.");
    const proposed = { model: "m", reason: "r", cost: 0.034, tool: "t", arguments: "{}" };
    expect(describeBy({ by: "model", proposed })).toBe("m proposed the call, and a program checked it as it checks yours. Asking it cost $0.03.");
    expect(describeBy({ by: "model", proposed: { ...proposed, cost: null } })).toMatch(/What asking it cost is not known/);
    expect(describeBy({ by: "model", proposed: { ...proposed, cost: 0 } })).toMatch(/Asking it cost \$0\.00/);
    // A run that says a model chose it and has nothing of what it proposed is not made out to be one that has
    expect(describeBy({ by: "model", proposed: null })).toBe("You chose the call.");
  });

  it("says what is not as it was", () => {
    expect(describeSince([])).toEqual([]);
    const both = describeSince(["data", "method"]);
    expect(both).toHaveLength(2);
    expect(both[0]).toMatch(/data is not as it was/);
    expect(both[1]).toMatch(/built again/);
  });

  it("says in a table's words what is not as it was, and how much was kept", () => {
    expect(describeSinceShort([])).toEqual([]);
    expect(describeSinceShort(["method", "data"])).toEqual(["It was built again since it ran", "Your data is not as it was when it ran"]);
    expect(KEPT_LABELS).toEqual({ whole: "All of it", look: "A look at it", hash: "Its size and a hash" });
  });

  it("says what data it was on, and when not all of its files were listed", () => {
    const data = { own: "counts.csv", path: "/data/counts.csv", files: 1, bytes: 2048, fingerprint: "f", complete: true };
    expect(describeRunData(data)).toBe("counts.csv, at /data/counts.csv: 1 file, 2.0 KB");
    expect(describeRunData({ ...data, files: 5001, complete: false })).toMatch(/more files than were listed/);
  });

  it("says how long it took, or nothing if it was not made", () => {
    expect(describeSeconds(null)).toBe("");
    expect(describeSeconds(2.34)).toBe("2.3 s");
    expect(describeSeconds(0)).toBe("<1 ms");
  });

  it("writes the arguments as they would be written", () => {
    expect(describeArguments(null)).toBe("");
    expect(describeArguments({})).toBe("{}");
    expect(describeArguments({ a: 1 })).toBe('{\n  "a": 1\n}');
  });
});

describe("how closely two numbers must be", () => {
  it("is the server's own where nothing is typed", () => {
    expect(checkTolerance({ relative: "", absolute: "  " })).toEqual({ value: {}, problems: {} });
    expect(checkTolerance(EMPTY_TOLERANCE)).toEqual({ value: {}, problems: {} });
    expect(EMPTY_TOLERANCE).toEqual({ relative: "", absolute: "" });
  });

  it("takes numbers that are not negative", () => {
    expect(checkTolerance({ relative: "0.001", absolute: "1e-9" }).value).toEqual({ relative: 0.001, absolute: 1e-9 });
    expect(checkTolerance({ relative: ".5", absolute: "0" }).value).toEqual({ relative: 0.5, absolute: 0 });
    expect(checkTolerance({ relative: "0", absolute: "" }).value).toEqual({ relative: 0 });
  });

  it("refuses what is not a number, or is negative or infinite", () => {
    for (const bad of ["-1", "abc", "1,5", "Infinity", "NaN", "0x10", "1e999", "+1"]) {
      expect(checkTolerance({ relative: "", absolute: bad }).problems.absolute).toBeDefined();
      expect(checkTolerance({ relative: bad, absolute: "" }).value).toBeNull();
    }
  });

  it("holds the relative one under 1", () => {
    expect(checkTolerance({ relative: "1", absolute: "" }).problems.relative).toMatch(/less than 1/);
    expect(checkTolerance({ relative: "2", absolute: "" }).value).toBeNull();
    expect(checkTolerance({ relative: "0.999", absolute: "" }).value).toEqual({ relative: 0.999 });
    expect(checkTolerance({ relative: "", absolute: "5" }).value).toEqual({ absolute: 5 });
  });

  it("says what is wrong with each", () => {
    const checked = checkTolerance({ relative: "x", absolute: "y" });
    expect(Object.keys(checked.problems).sort()).toEqual(["absolute", "relative"]);
  });

  it("is put on an address only for what was said", () => {
    expect(toleranceQuery(undefined)).toBe("");
    expect(toleranceQuery({})).toBe("");
    expect(toleranceQuery({ relative: 0.01 })).toBe("?relative=0.01");
    expect(toleranceQuery({ absolute: 1e-9 })).toBe("?absolute=1e-9");
    expect(toleranceQuery({ relative: 0, absolute: 0.5 })).toBe("?relative=0&absolute=0.5");
  });

  it("says where a table is, with the tolerance that it was made with", () => {
    expect(tableAddress("b 1", "methods", undefined)).toBe("/api/bakeoffs/b%201/tables/methods");
    expect(tableAddress("b1", "pairs", { relative: 0.5 })).toBe("/api/bakeoffs/b1/tables/pairs?relative=0.5");
  });

  it("says in words what it is", () => {
    expect(describeTolerance({ relative: 1e-6, absolute: 1e-9 })).toBe(
      "Two numbers are the same if they are within 0.000001 of the larger of the two, or within 1e-9 of each other when both are near zero. Anything else is the same only if it is equal.",
    );
  });
});

describe("when the comparison is looked at again", () => {
  const base = {
    limit: 5,
    spent: 1,
    cost_known: true,
    data: { own: "d", missing: false },
    labels: null,
    candidates: [method("a", true, { run: { at: "t1", since: [] } as unknown as BakeoffRunSummary })],
  } as unknown as Bakeoff;

  it("is the same for the same bake-off", () => {
    expect(comparisonKey(base, "x")).toBe(comparisonKey({ ...base }, "x"));
  });

  it("changes with what the jobs are doing", () => {
    expect(comparisonKey(base, "x")).not.toBe(comparisonKey(base, "y"));
  });

  it("changes with what is spent, the limit, the data, and the labels", () => {
    const key = comparisonKey(base, "x");
    expect(comparisonKey({ ...base, spent: 2 }, "x")).not.toBe(key);
    expect(comparisonKey({ ...base, limit: 6 }, "x")).not.toBe(key);
    expect(comparisonKey({ ...base, cost_known: false }, "x")).not.toBe(key);
    expect(comparisonKey({ ...base, data: null }, "x")).not.toBe(key);
    expect(comparisonKey({ ...base, labels: { own: "l", column: "c" } as Bakeoff["labels"] }, "x")).not.toBe(key);
  });

  it("changes with how a method stands and what came of running it", () => {
    const key = comparisonKey(base, "x");
    const stands = { ...base, candidates: [method("a", false)] };
    expect(comparisonKey(stands, "x")).not.toBe(key);
    const ranAgain = { ...base, candidates: [method("a", true, { run: { at: "t2", since: [] } as unknown as BakeoffRunSummary })] };
    expect(comparisonKey(ranAgain, "x")).not.toBe(key);
    const changed = { ...base, candidates: [method("a", true, { run: { at: "t1", since: ["data"] } as unknown as BakeoffRunSummary })] };
    expect(comparisonKey(changed, "x")).not.toBe(key);
  });
});

describe("the table", () => {
  it("says places as they are said", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111].map(ordinal)).toEqual([
      "1st",
      "2nd",
      "3rd",
      "4th",
      "11th",
      "12th",
      "13th",
      "21st",
      "22nd",
      "23rd",
      "101st",
      "111th",
    ]);
  });

  it("says a rank, and that it is shared", () => {
    const methods = [
      compared("a", { score: score({ rank: 1 }) }),
      compared("b", { score: score({ rank: 1 }) }),
      compared("c", { score: score({ rank: 3, matched: 2 }) }),
      compared("d", { score: score({ scored: false, rank: null }) }),
      compared("e"),
    ];
    expect(describeRank(methods[0], methods)).toBe("1st, shared");
    expect(describeRank(methods[1], methods)).toBe("1st, shared");
    expect(describeRank(methods[2], methods)).toBe("3rd");
    expect(describeRank(methods[3], methods)).toBe("Not ranked");
    expect(describeRank(methods[4], methods)).toBe("Not ranked");
  });

  it("says a score as how many labels were matched", () => {
    expect(describeScore(score())).toBe("8 of 10 (80%)");
    expect(describeScore(score({ matched: 1, of: 3, score: 1 / 3 }))).toBe("1 of 3 (33.3%)");
    expect(describeScore(score({ matched: 0, of: 4, score: 0 }))).toBe("0 of 4 (0%)");
  });

  it("does not say that a method that was not scored scored nothing", () => {
    const unscored = score({ scored: false, why: "no_answer", reason: "It gave no answer.", matched: null, of: null, score: null, rank: null });
    expect(describeScore(unscored)).toBe("Not scored. It gave no answer.");
    expect(describeScore(unscored)).not.toMatch(/0/);
    expect(describeScore({ ...unscored, reason: "" })).toBe("Not scored.");
    expect(describeScoreDetail(unscored)).toEqual([]);
  });

  it("says how a score was made", () => {
    expect(describeScoreDetail(score())).toEqual(["Its answers were matched to the labels by their place, in the order of the data."]);
    expect(describeScoreDetail(score({ by: "id", missing: 1, extra: 2 }))).toEqual([
      "Its answers were matched to the labels by what each is the answer to.",
      "1 label had no answer from it, and each counts as wrong.",
      "2 answers had no label, and were not counted.",
    ]);
    expect(describeScoreDetail(score({ missing: 3 }))[1]).toBe("3 labels had no answer from it, and each counts as wrong.");
  });

  it("names the methods by their ids, or the id if there is none", () => {
    const methods = [compared("a", { name: "Alpha" })];
    expect(nameOf("a", methods)).toBe("Alpha");
    expect(nameOf("zz", methods)).toBe("zz");
  });

  it("says which methods agree, differ, and are not known to", () => {
    const methods = [compared("a", { name: "A" }), compared("b", { name: "B" }), compared("c", { name: "C" }), compared("d", { name: "D" })];
    expect(describeAgreement({ agrees: ["b"], differs: ["c", "d"], unknown: [] }, methods)).toEqual([
      { label: "Agrees with", names: ["B"] },
      { label: "Differs from", names: ["C", "D"] },
    ]);
    expect(describeAgreement({ agrees: [], differs: [], unknown: ["c"] }, methods)).toEqual([{ label: "Not known against", names: ["C"] }]);
    expect(describeAgreement({ agrees: [], differs: [], unknown: [] }, methods)).toEqual([]);
  });

  it("says how much of each answer of a pair was kept", () => {
    expect(describePairKept({ kept: ["whole", "whole"] })).toBe("Both: all of it was kept");
    expect(describePairKept({ kept: ["whole", "hash"] })).toBe("First: all of it was kept. Second: only its size and a hash were kept");
  });

  it("says what reading cost, and what asking did", () => {
    expect(describeReading(compared("a", { cost: { reading: 0.5, asking: 0 } }))).toBe("$0.50");
    expect(describeReading(compared("a", { cost: { reading: null, asking: null } }))).toBe("—");
    expect(describeAsking(compared("a", { by: "person" }))).toBe("None, your call");
    expect(describeAsking(compared("a", { by: "model", cost: { reading: 0, asking: 0.2 } }))).toBe("$0.20");
    expect(describeAsking(compared("a", { by: "model", cost: { reading: 0, asking: null } }))).toBe("Not known");
    expect(describeAsking(compared("a", { by: null, cost: { reading: 0, asking: null } }))).toBe("—");
  });

  const truth: BakeoffGroundTruth = {
    own: "labels.csv",
    column: "cell_type",
    id_column: null,
    ok: true,
    why: null,
    problem: null,
    bytes: 100,
    in_data: false,
    says: "",
    rows: 10,
    labelled: 8,
    unlabelled: 2,
    sha256: "0123456789abcdef0123",
  };

  it("says where the right answers are and how many there are", () => {
    expect(describeGroundTruth(truth)).toEqual([
      'labels.csv, the answers in "cell_type", in the order of the data.',
      "10 rows, 8 with an answer, and 2 had none.",
      "The file is the one with the hash 0123456789ab…, so a score says which labels it is of.",
    ]);
  });

  it("says which column says what each is the answer to, and leaves out what is not known of one that cannot be used", () => {
    const lines = describeGroundTruth({ ...truth, id_column: "cell", ok: false, rows: null, labelled: null, unlabelled: null, sha256: null });
    expect(lines).toEqual(['labels.csv, the answers in "cell_type", with what each is the answer to in "cell".']);
    expect(describeGroundTruth({ ...truth, unlabelled: 0 })[1]).toBe("10 rows, 8 with an answer.");
    // Counts are not said of a file that cannot be used, nor are they made up where the server has none
    expect(describeGroundTruth({ ...truth, ok: false, sha256: null })).toHaveLength(1);
    expect(describeGroundTruth({ ...truth, rows: null, sha256: null })).toHaveLength(1);
  });

  it("says how the methods came out", () => {
    expect(describeOutcomes([])).toBe("There are no methods to compare.");
    expect(describeOutcomes([compared("a"), compared("b", { state: "failed" }), compared("c", { state: "not_built" }), compared("d")])).toBe(
      "4 methods: 2 ran, 1 failed, 1 not built.",
    );
    expect(describeOutcomes([compared("a", { state: "not_run" })])).toBe("1 method: 1 not run.");
  });

  it("counts the methods that gave an answer", () => {
    expect(answeredCount({ methods: [compared("a"), compared("b", { state: "failed" }), compared("c")] })).toBe(2);
  });
});
