import { describe, expect, it } from "vitest";
import {
  checkReference,
  describeAgreement,
  describeCall,
  describeGiven,
  describeKept,
  describeOutcome,
  describePlan,
  describeResult,
  describeRun,
  describeValue,
  emptyReference,
  FAILURE_ADVICE,
  STATUS_TITLES,
  type ReferenceDraft,
} from "./paperagent-reference";
import type { PaperAgentReference, ReferenceKept, TutorialCall, TutorialSummary } from "./types";

const limits: PaperAgentReference["limits"] = {
  default_minutes: 10,
  max_minutes: 60,
  default_total_minutes: 30,
  max_total_minutes: 240,
  default_tutorials: 10,
  max_tutorials: 25,
  default_repeats: 2,
  max_repeats: 3,
  default_gigabytes: 2,
  max_gigabytes: 20,
  memory: "8g",
  cpus: "4",
  pids: 1024,
};

const reference = (data: PaperAgentReference["data"] = null): Pick<PaperAgentReference, "limits" | "data"> => ({ limits, data });
const draft = (part: Partial<ReferenceDraft> = {}): ReferenceDraft => ({ ...emptyReference(limits), ...part });

function summary(part: Partial<TutorialSummary> = {}): TutorialSummary {
  return {
    id: "01-examples-demo-py",
    path: "examples/demo.py",
    kind: "script",
    status: "ok",
    failure: null,
    seconds: 3.2,
    runs: 2,
    stable: true,
    differs: [],
    calls: 3,
    files: 1,
    cells: 0,
    cells_total: 0,
    ...part,
  };
}

function kept(part: Partial<ReferenceKept> = {}): ReferenceKept {
  return {
    commit: "a".repeat(40),
    image_id: `sha256:${"b".repeat(64)}`,
    started_at: "2026-01-01T00:00:00Z",
    finished_at: "2026-01-01T00:02:05Z",
    complete: true,
    limits: { minutes: 10, total_minutes: 30, tutorials: 10, repeats: 2, gigabytes: 2, memory: "8g", cpus: "4", pids: 1024 },
    data: null,
    tutorials: [summary()],
    skipped: [],
    more: 0,
    not_run: [],
    ...part,
  };
}

describe("what running the tutorials is asked for", () => {
  it("begins with what the server defaults to, and with the data given", () => {
    expect(emptyReference(limits)).toEqual({ minutes: "10", totalMinutes: "30", tutorials: "10", repeats: "2", gigabytes: "2", useData: true });
  });

  it("is the numbers as whole numbers, with no word about data if there is none to give", () => {
    expect(checkReference(draft(), reference())).toEqual({
      value: { minutes: 10, total_minutes: 30, tutorials: 10, repeats: 2, gigabytes: 2 },
      problems: {},
    });
  });

  it("says whether the data is given, if there is any", () => {
    const data = { files: 3, bytes: 1000 };

    expect(checkReference(draft(), reference(data)).value?.data).toBe(true);
    expect(checkReference(draft({ useData: false }), reference(data)).value?.data).toBe(false);
    expect(checkReference(draft({ useData: false }), reference()).value).not.toHaveProperty("data");
  });

  it("takes numbers with spaces round them, and no other", () => {
    expect(checkReference(draft({ minutes: " 5 ", repeats: "3" }), reference()).value).toMatchObject({ minutes: 5, repeats: 3 });
    for (const typed of ["", "0", "-1", "1.5", "ten", "1e2"]) {
      expect(checkReference(draft({ minutes: typed }), reference()).value).toBeNull();
    }
  });

  it("says which are wrong, and each of them, by the most that the server takes", () => {
    const checked = checkReference(draft({ minutes: "61", totalMinutes: "241", tutorials: "26", repeats: "4", gigabytes: "21" }), reference());

    expect(checked.value).toBeNull();
    expect(Object.keys(checked.problems).sort()).toEqual(["gigabytes", "minutes", "repeats", "totalMinutes", "tutorials"]);
    expect(checked.problems.minutes).toContain("from 1 to 60");
    expect(checked.problems.repeats).toContain("from 1 to 3");
  });

  it("does not let all of the runs have less time than one", () => {
    const checked = checkReference(draft({ minutes: "20", totalMinutes: "10" }), reference());

    expect(checked.value).toBeNull();
    expect(checked.problems.totalMinutes).toMatch(/cannot be less than the time for one/);
    expect(checkReference(draft({ minutes: "10", totalMinutes: "10" }), reference()).value).not.toBeNull();
  });
});

describe("what is said of the tutorials", () => {
  it("says how many can be run, and how many cannot or are not listed", () => {
    expect(describePlan(1, 0, 0)).toBe("1 tutorial can be run here.");
    expect(describePlan(3, 2, 0)).toBe("3 tutorials can be run here, 2 cannot.");
    expect(describePlan(0, 1, 4)).toBe("0 tutorials can be run here, 1 cannot, 4 more are not listed.");
  });

  it("says what the runs were given of the data", () => {
    expect(describeGiven(null)).toBe("None");
    expect(describeGiven({ files: 1, bytes: 2048 })).toMatch(/^1 file, 2(\.0)? ?KB/i);
    expect(describeGiven({ files: 3, bytes: 0 })).toMatch(/^3 files, /);
  });

  it("says how long a run took, and that one that did not end did not", () => {
    expect(describeRun(kept())).toMatch(/^Run .+, in 2 minutes 5 seconds$/);
    expect(describeRun(kept({ finished_at: null }))).toMatch(/^Begun .+, and not ended$/);
    expect(describeRun(kept({ finished_at: "2025-01-01T00:00:00Z" }))).toMatch(/^Run [^,]+$/);
  });

  it("counts the tutorials that ran to their end and those that gave the same each time", () => {
    const tutorials = [summary(), summary({ id: "02-b", stable: false }), summary({ id: "03-c", status: "failed", stable: null })];

    expect(describeOutcome(kept({ tutorials }))).toBe("3 tutorials were run: 2 to the end, 1 not. 1 gave the same each time it was run.");
    expect(describeOutcome(kept({ tutorials: [summary()] }))).toBe("1 tutorial was run: 1 to the end, 0 not. 1 gave the same each time it was run.");
    expect(describeOutcome(kept({ tutorials: [] }))).toBe("No tutorial was run.");
  });

  it("says whether the runs of a tutorial agreed, and does not say so of one that did not end or was run once", () => {
    expect(describeAgreement(summary())).toBe("The same each of 2 times");
    expect(describeAgreement(summary({ stable: false, differs: ["calls", "files"] }))).toBe(
      "Not the same each of 2 times: the calls to the code and the files it wrote differed",
    );
    expect(describeAgreement(summary({ stable: false, differs: ["status"] }))).toBe("Not the same each of 2 times: whether it ended differed");
    expect(describeAgreement(summary({ stable: true, differs: ["output"] }))).toBe(
      "The calls and the files were the same each of 2 times, but what it printed was not",
    );
    expect(describeAgreement(summary({ stable: null, runs: 1 }))).toBe("Run once, so not compared");
    expect(describeAgreement(summary({ stable: null, status: "timed_out" }))).toBe("Not compared, as it did not end");
    expect(describeAgreement(summary({ stable: null, runs: 2 }))).toBe("Not compared");
  });

  it("says what was kept of a tutorial", () => {
    expect(describeKept(summary())).toBe("3 calls to the code, 1 file written");
    expect(describeKept(summary({ calls: 1, files: 2, cells: 4, cells_total: 6 }))).toBe(
      "1 call to the code, 2 files written, 4 of 6 cells kept",
    );
  });

  it("has a title for each way a tutorial can end, and advice for each way it can fail", () => {
    expect(Object.keys(STATUS_TITLES).sort()).toEqual(["failed", "ok", "timed_out", "too_big"]);
    expect(Object.keys(FAILURE_ADVICE)).toHaveLength(11);
    for (const advice of Object.values(FAILURE_ADVICE)) expect(advice).not.toBe("");
  });
});

describe("what a call is shown as", () => {
  const value = (part: object) => ({ type: "int", plain: true, ...part });

  function call(part: Partial<TutorialCall> = {}): TutorialCall {
    return {
      id: 1,
      module: "pkg.core",
      function: "mean",
      qualname: "mean",
      method: false,
      file: "pkg/core.py",
      line: 4,
      args: { values: value({ type: "list", value: [1, 2, 3] }), scale: value({ type: "float", value: 2.5 }) },
      cwd: "examples",
      variadic: false,
      result: value({ type: "float", value: 4.5 }),
      returned: true,
      cell: null,
      from: { file: "examples/demo.py", line: 3 },
      ...part,
    };
  }

  it("is a value itself if it is plain, and cut if it is long", () => {
    expect(describeValue(value({ value: 5 }))).toBe("5");
    expect(describeValue(value({ type: "str", value: "text" }))).toBe('"text"');
    expect(describeValue(value({ type: "NoneType", value: null }))).toBe("null");
    const long = describeValue(value({ type: "list", value: Array.from({ length: 200 }, (_, index) => index) }));
    expect(long.length).toBeLessThanOrEqual(121);
    expect(long.endsWith("…")).toBe(true);
  });

  it("is what it was and a look at it if it is not", () => {
    expect(describeValue({ type: "numpy.ndarray", plain: false, shape: [3, 4], dtype: "float64", sha256: "a".repeat(64) })).toBe(
      "numpy.ndarray, shape 3×4, float64",
    );
    expect(describeValue({ type: "tuple", plain: false, repr: "(1, 2)" })).toBe("tuple, (1, 2)");
    expect(describeValue({ type: "pkg.Model", plain: false })).toBe("pkg.Model");
  });

  it("is a call as it would be written, with its arguments by name", () => {
    expect(describeCall(call())).toBe("pkg.core.mean(values=[1,2,3], scale=2.5)");
    expect(describeCall(call({ args: {} }))).toBe("pkg.core.mean()");
  });

  it("says what a call gave, or that it raised, or that nothing was kept", () => {
    expect(describeResult(call())).toBe("4.5");
    expect(describeResult(call({ returned: false, result: null }))).toBe("It raised.");
    expect(describeResult(call({ result: null }))).toBe("Nothing was kept of what it gave.");
  });
});
