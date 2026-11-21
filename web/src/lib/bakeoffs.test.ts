import { describe, expect, it } from "vitest";
import {
  BAKEOFFS_ADDRESS,
  bakeoffAddress,
  bakeoffJob,
  bakeoffKey,
  checkBakeoff,
  checkChange,
  checkLabels,
  describeLabels,
  describeLeft,
  describeMethods,
  describeScope,
  describeSpending,
  draftOf,
  EMPTY_BAKEOFF,
  isBlankScope,
  isNoChange,
  MAX_BAKEOFF_TASK,
  MAX_BAKEOFF_TITLE,
  MAX_COLUMN_CHARS,
  type BakeoffDraft,
} from "./bakeoffs";
import { EMPTY_SCOPE_DRAFT } from "./paperagent-scope";
import type { Bakeoff, BakeoffDescribed, BakeoffLabels, BakeoffLimits, Job } from "./types";

const LIMITS: BakeoffLimits = {
  max_bakeoffs: 50,
  max_candidates: 12,
  max_task_chars: 2000,
  max_title_chars: 120,
  max_name_chars: 200,
  max_queries: 6,
  most_found: 20,
  most_chosen: 6,
};

function job(changes: Partial<Job> = {}): Job {
  return {
    id: "j1",
    kind: "bakeoff-run",
    subject: "b1",
    title: "Running",
    state: "running",
    message: "",
    progress: { finished: 1, total: 3 },
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    finished_at: null,
    log_total: 0,
    ...changes,
  } as Job;
}

function bakeoff(changes: Partial<Bakeoff> = {}): Bakeoff {
  return {
    id: "b1",
    title: "Which clusters best",
    task: "Cluster my cells",
    created_at: "2026-01-01T00:00:00Z",
    candidates: [],
    shortlist: null,
    meaning: "",
    limit: 5,
    spent: 0,
    cost_known: true,
    job: null,
    data: null,
    described: null,
    labels: null,
    left: 5,
    limits: LIMITS,
    settings_model: "m",
    ...changes,
  };
}

// What a bake-off keeps of what was said of the data, which is every part: what was not said is an empty text, and a size of none
const kept = (changes: Partial<BakeoffDescribed>): BakeoffDescribed => ({
  species: "",
  tissue: "",
  assay: "",
  input_format: "",
  sample_unit: "",
  sample_size: 0,
  at: "2026-01-01T00:00:00Z",
  ...changes,
});

const typed = (changes: Partial<BakeoffDraft>): BakeoffDraft => ({ ...EMPTY_BAKEOFF, task: "Cluster my cells", limit: "5", ...changes });
const scope = (changes: Partial<typeof EMPTY_SCOPE_DRAFT>) => ({ ...EMPTY_SCOPE_DRAFT, ...changes });

describe("the addresses of the bake-offs", () => {
  it("are parts of the PaperAgents page, with the id of a bake-off made safe", () => {
    expect(BAKEOFFS_ADDRESS).toBe("/papers?view=bakeoffs");
    expect(bakeoffAddress("abc123")).toBe("/papers?bakeoff=abc123");
    expect(bakeoffAddress("a&b=c d")).toBe("/papers?bakeoff=a%26b%3Dc%20d");
  });
});

describe("the job at work on a bake-off", () => {
  it("is the one of its kinds that is at work on it, and no other", () => {
    expect(bakeoffJob([job()], "b1")?.id).toBe("j1");
    expect(bakeoffJob([job({ kind: "bakeoff-shortlist" })], "b1")).toBeDefined();
    expect(bakeoffJob([job({ kind: "bakeoff-build" })], "b1")).toBeDefined();
  });

  it.each([
    ["is for another bake-off", { subject: "b2" }],
    ["is of another kind", { kind: "papers" }],
    ["has finished", { state: "succeeded" as const }],
    ["has been stopped", { state: "stopped" as const }],
    ["has failed", { state: "failed" as const }],
  ])("is not one that %s", (_what, changes) => {
    expect(bakeoffJob([job(changes)], "b1")).toBeUndefined();
  });

  it("takes a job that is stopping as still at work, and no jobs as none", () => {
    expect(bakeoffJob([job({ state: "stopping" })], "b1")).toBeDefined();
    expect(bakeoffJob(null, "b1")).toBeUndefined();
  });
});

describe("what a page looks at again", () => {
  it("changes when a job ends, and when a job has done another thing", () => {
    const one = bakeoffKey([job()], 0, "b1");

    expect(bakeoffKey([job()], 1, "b1")).not.toBe(one);
    expect(bakeoffKey([job({ progress: { finished: 2, total: 3 } })], 0, "b1")).not.toBe(one);
    expect(bakeoffKey([job()], 0, "b1")).toBe(one);
  });

  it("is only of the bake-off that it is asked of, and of all of them if none is", () => {
    const other = job({ id: "j2", subject: "b2" });

    expect(bakeoffKey([job(), other], 0, "b1")).toBe(bakeoffKey([job()], 0, "b1"));
    expect(bakeoffKey([job(), other], 0)).not.toBe(bakeoffKey([job()], 0));
  });

  it("does not take a job that has finished, or one that is not of a bake-off, for work", () => {
    expect(bakeoffKey([job({ state: "succeeded" }), job({ id: "j3", kind: "papers" })], 2, "b1")).toBe("2|");
    expect(bakeoffKey(null, 0)).toBe("0|");
  });
});

describe("what a person says of where the right answers are", () => {
  it("is nothing when none of it is typed", () => {
    expect(checkLabels(typed({ answers: "  ", column: " " }))).toEqual({ value: null, problems: {} });
  });

  it("is sent as the file and its columns, with the column of what each answers left out if it is blank", () => {
    expect(checkLabels(typed({ answers: " truth.csv ", column: " label " })).value).toEqual({ own: "truth.csv", column: "label" });
    expect(checkLabels(typed({ answers: "truth.csv", column: "label", idColumn: " cell " })).value).toEqual({
      own: "truth.csv",
      column: "label",
      id_column: "cell",
    });
  });

  it("needs the file and the column of answers if either is said, or the column of what each answers", () => {
    expect(checkLabels(typed({ column: "label" })).problems.answers).toMatch(/which file/);
    expect(checkLabels(typed({ answers: "truth.csv" })).problems.column).toMatch(/which column/);
    expect(checkLabels(typed({ idColumn: "cell" }))).toEqual({
      value: null,
      problems: { answers: expect.any(String), column: expect.any(String) },
    });
  });

  it("does not take the column of the answers for the column of what each answers", () => {
    const checked = checkLabels(typed({ answers: "truth.csv", column: "label", idColumn: "label" }));

    expect(checked.value).toBeNull();
    expect(checked.problems.idColumn).toMatch(/another/);
  });

  it("takes a name of a column of the most that the server takes, and no more", () => {
    const most = "x".repeat(MAX_COLUMN_CHARS);
    const more = `${most}x`;

    expect(checkLabels(typed({ answers: "t.csv", column: most })).value).not.toBeNull();
    expect(checkLabels(typed({ answers: "t.csv", column: more })).problems.column).toMatch(/at most 200/);
    expect(checkLabels(typed({ answers: "t.csv", column: "a", idColumn: most })).value).not.toBeNull();
    expect(checkLabels(typed({ answers: "t.csv", column: "a", idColumn: more })).problems.idColumn).toMatch(/at most 200/);
    expect(checkLabels(typed({ answers: "t.csv", column: `${"🧬".repeat(MAX_COLUMN_CHARS)}` })).value).not.toBeNull();
  });
});

describe("whether something is said of the data", () => {
  it("is not, if every part is blank or only spaces", () => {
    expect(isBlankScope(EMPTY_SCOPE_DRAFT)).toBe(true);
    expect(isBlankScope(scope({ species: "  ", unit: " " }))).toBe(true);
  });

  it.each(["species", "tissue", "assay", "format", "size", "unit"] as const)("is, if only the %s is", (part) => {
    expect(isBlankScope(scope({ [part]: "x" }))).toBe(false);
  });
});

describe("making a bake-off of what was typed", () => {
  it("sends the task and the limit, and leaves out what was left blank", () => {
    expect(checkBakeoff(typed({ task: "  Cluster my cells " }), LIMITS)).toEqual({ value: { task: "Cluster my cells", limit: 5 }, problems: {} });
  });

  it("sends what else was typed, with the title tidied", () => {
    const checked = checkBakeoff(
      typed({
        title: "  Which   clusters best ",
        data: "cells.h5ad",
        scope: scope({ species: "human", size: "5,000", unit: "cells" }),
        answers: "truth.csv",
        column: "label",
        limit: "$2.50",
      }),
      LIMITS,
    );

    expect(checked.problems).toEqual({});
    expect(checked.value).toEqual({
      task: "Cluster my cells",
      title: "Which clusters best",
      data: "cells.h5ad",
      described: { species: "human", sample_size: 5000, sample_unit: "cells" },
      labels: { own: "truth.csv", column: "label" },
      limit: 2.5,
    });
  });

  it("takes a limit of nothing, which is the one that spends nothing", () => {
    expect(checkBakeoff(typed({ limit: "0" }), LIMITS).value?.limit).toBe(0);
  });

  it("needs something done and a limit said", () => {
    const checked = checkBakeoff(typed({ task: "   ", limit: "" }), LIMITS);

    expect(checked.value).toBeNull();
    expect(checked.problems.task).toBe("Say what you want done.");
    expect(checked.problems.limit).toMatch(/the most it may spend/);
  });

  it.each(["-1", "five", "1e3", "1,5"])("refuses %j as a limit", (limit) => {
    expect(checkBakeoff(typed({ limit }), LIMITS).problems.limit).toBeDefined();
  });

  it("takes a task and a title of the most that the server says, and no more", () => {
    expect(checkBakeoff(typed({ task: "x".repeat(2000) }), LIMITS).value).not.toBeNull();
    expect(checkBakeoff(typed({ task: "x".repeat(2001) }), LIMITS).problems.task).toBe("That is at most 2000 characters.");
    expect(checkBakeoff(typed({ title: "x".repeat(120) }), LIMITS).value).not.toBeNull();
    expect(checkBakeoff(typed({ title: "x".repeat(121) }), LIMITS).problems.title).toBe("That is at most 120 characters.");
    expect(checkBakeoff(typed({ task: "x".repeat(10) }), { ...LIMITS, max_task_chars: 9 }).problems.task).toBe("That is at most 9 characters.");
    expect(checkBakeoff(typed({ title: "x".repeat(10) }), { ...LIMITS, max_title_chars: 9 }).problems.title).toBe("That is at most 9 characters.");
  });

  it("keeps the task on one line with one space between words, and counts it so, as the server does", () => {
    expect(checkBakeoff(typed({ task: " Cluster\n\n  my\tcells " }), LIMITS).value?.task).toBe("Cluster my cells");
    // 2100 characters as they were typed, of which 1399 are kept
    expect(checkBakeoff(typed({ task: "a  ".repeat(700) }), LIMITS).value?.task).toBe(Array(700).fill("a").join(" "));
    expect(checkBakeoff(typed({ task: "a ".repeat(1001) }), LIMITS).problems.task).toBe("That is at most 2000 characters.");
  });

  it("goes by what the server has taught it, and by what it knows if it has not been told", () => {
    expect(MAX_BAKEOFF_TASK).toBe(2000);
    expect(MAX_BAKEOFF_TITLE).toBe(120);
    expect(checkBakeoff(typed({ task: "x".repeat(2001) }), null).problems.task).toBeDefined();
    expect(checkBakeoff(typed({ title: "x".repeat(121) }), null).problems.title).toBeDefined();
    expect(checkBakeoff(typed({}), null).value).not.toBeNull();
  });

  it("says what is wrong with what was said of the data and of the right answers, where it is", () => {
    const checked = checkBakeoff(typed({ scope: scope({ size: "many" }), answers: "truth.csv" }), LIMITS);

    expect(checked.value).toBeNull();
    expect(checked.problems.size).toBeDefined();
    expect(checked.problems.column).toBeDefined();
  });

  it("does not say there is nothing said of the data when it was left blank", () => {
    expect(checkBakeoff(typed({}), LIMITS).problems.form).toBeUndefined();
  });
});

describe("a bake-off as a person is shown it to change", () => {
  it("is what it is now, in the words a person types", () => {
    const now = bakeoff({
      data: { own: "cells.h5ad", missing: false },
      described: kept({ species: "human", input_format: "h5ad", sample_size: 5000, sample_unit: "cells" }),
      labels: { own: "truth.csv", column: "label", id_column: "cell" } as BakeoffLabels,
      limit: 2.5,
    });

    expect(draftOf(now)).toEqual({
      title: "Which clusters best",
      task: "Cluster my cells",
      data: "cells.h5ad",
      limit: "2.5",
      scope: { species: "human", tissue: "", assay: "", format: "h5ad", size: "5000", unit: "cells" },
      answers: "truth.csv",
      column: "label",
      idColumn: "cell",
    });
  });

  it("has no size for a size of none, which is how a bake-off keeps a size that was not said", () => {
    const draft = draftOf(bakeoff({ described: kept({ species: "human" }) }));

    expect(draft.scope).toEqual({ species: "human", tissue: "", assay: "", format: "", size: "", unit: "" });
    expect(checkChange(draft, bakeoff({ described: kept({ species: "human" }) }))).toEqual({ value: {}, problems: {} });
  });

  it("has nothing for what it has not", () => {
    expect(draftOf(bakeoff())).toEqual({ ...EMPTY_BAKEOFF, title: "Which clusters best", task: "Cluster my cells", limit: "5" });
  });

  it("has a limit that is very small or very large in digits, which is as it can be typed again", () => {
    expect(draftOf(bakeoff({ limit: 1e-7 })).limit).toBe("0.0000001");
    expect(draftOf(bakeoff({ limit: 1e21 })).limit).toBe("1000000000000000000000");
    expect(checkChange(draftOf(bakeoff({ limit: 1e-7 })), bakeoff({ limit: 1e-7 }))).toEqual({ value: {}, problems: {} });
  });
});

describe("changing a bake-off", () => {
  const was = bakeoff({
    data: { own: "cells.h5ad", missing: false },
    described: kept({ species: "human", sample_size: 5000, sample_unit: "cells" }),
    labels: { own: "truth.csv", column: "label", id_column: null } as BakeoffLabels,
    limit: 5,
    spent: 1,
  });

  it("is nothing when nothing differs, so what is said again is not sent", () => {
    const checked = checkChange(draftOf(was), was);

    expect(checked).toEqual({ value: {}, problems: {} });
    expect(isNoChange(checked.value!)).toBe(true);
    expect(isNoChange({ limit: 6 })).toBe(false);
  });

  it("sends only the parts that differ", () => {
    const base = draftOf(was);

    expect(checkChange({ ...base, title: "A new name" }, was).value).toEqual({ title: "A new name" });
    expect(checkChange({ ...base, task: "Something else" }, was).value).toEqual({ task: "Something else" });
    expect(checkChange({ ...base, limit: "7.5" }, was).value).toEqual({ limit: 7.5 });
    expect(checkChange({ ...base, data: "other.h5ad" }, was).value).toEqual({ data: "other.h5ad" });
    expect(checkChange({ ...base, answers: "other.csv" }, was).value).toEqual({ labels: { own: "other.csv", column: "label" } });
    expect(checkChange({ ...base, idColumn: "cell" }, was).value).toEqual({ labels: { own: "truth.csv", column: "label", id_column: "cell" } });
    expect(checkChange({ ...base, scope: { ...base.scope, tissue: "blood" } }, was).value).toEqual({
      described: { species: "human", tissue: "blood", sample_size: 5000, sample_unit: "cells" },
    });
  });

  it("takes the data, the description, and the right answers away with what says so", () => {
    const base = draftOf(was);
    const checked = checkChange({ ...base, data: "", scope: EMPTY_SCOPE_DRAFT, answers: "", column: "" }, was);

    expect(checked.problems).toEqual({});
    expect(checked.value).toEqual({ data: "", described: {}, labels: {} });
  });

  it("does not take the title away, which a bake-off has", () => {
    const checked = checkChange({ ...draftOf(was), title: "  " }, was);

    expect(checked.value).toBeNull();
    expect(checked.problems.title).toBe("Say what it is called.");
  });

  it("does not take a limit that is less than what has been spent, and says what has been", () => {
    const base = draftOf(was);
    const checked = checkChange({ ...base, limit: "0.50" }, was);

    expect(checked.value).toBeNull();
    expect(checked.problems.limit).toBe("$1.00 has been spent already, so the most it may spend is at least that.");
    expect(checkChange({ ...base, limit: "1" }, was).value).toEqual({ limit: 1 });
  });

  it("does not take the same task said again with other spaces for a change", () => {
    expect(checkChange({ ...draftOf(was), task: "  Cluster   my\ncells " }, was).value).toEqual({});
  });

  it("does not hold a limit that is not said again to be at least what was spent, which may be more than it", () => {
    const over = bakeoff({ limit: 1, spent: 1.4 });

    expect(checkChange({ ...draftOf(over), title: "Another name" }, over)).toEqual({ value: { title: "Another name" }, problems: {} });
    expect(checkChange({ ...draftOf(over), limit: "1.2" }, over).problems.limit).toBe(
      "$1.40 has been spent already, so the most it may spend is at least that.",
    );
    expect(checkChange({ ...draftOf(over), limit: "1.4" }, over).value).toEqual({ limit: 1.4 });
  });

  it("has what is wrong with it said even if the part is not one that differs", () => {
    const checked = checkChange({ ...draftOf(was), column: "" }, was);

    expect(checked.value).toBeNull();
    expect(checked.problems.column).toBeDefined();
  });

  it("is the same data when it was said again at another time, which is not a change", () => {
    const another = bakeoff({ described: kept({ sample_unit: "cells", species: "human", sample_size: 5000, at: "2027-02-02T00:00:00Z" }) });

    expect(checkChange(draftOf(was), { ...was, described: another.described }).value).toEqual({});
  });

  it("is a change of the description if the words are different, though the parts are the same", () => {
    const base = draftOf(was);

    expect(checkChange({ ...base, scope: { ...base.scope, species: "mouse" } }, was).value).toEqual({
      described: { species: "mouse", sample_size: 5000, sample_unit: "cells" },
    });
  });

  it("leaves a title alone that was changed by nothing but spaces", () => {
    expect(checkChange({ ...draftOf(was), title: "  Which   clusters best " }, was).value).toEqual({});
  });

  it("is not stopped by right answers that cannot be used now if they are not what is changed", () => {
    const gone = bakeoff({
      labels: { own: "truth.csv", column: "label", id_column: null, ok: false, why: "missing", problem: "It is gone." } as BakeoffLabels,
    });

    expect(checkChange({ ...draftOf(gone), title: "Another" }, gone).value).toEqual({ title: "Another" });
  });
});

describe("what is said of what has been spent", () => {
  it("is what was spent of what may be, in dollars", () => {
    expect(describeSpending({ spent: 0.5, limit: 5, cost_known: true })).toBe("$0.50 of $5.00 spent");
    expect(describeSpending({ spent: 0, limit: 0, cost_known: true })).toBe("$0.00 of $0.00 spent");
  });

  it("says that it is not all known when it is not", () => {
    expect(describeSpending({ spent: 0.5, limit: 5, cost_known: false })).toBe("$0.50 of $5.00 spent, and not all of what was spent is known");
  });

  it("says what is left, and that nothing is when what was spent is not known", () => {
    expect(describeLeft({ left: 4.5, limit: 5, cost_known: true })).toBe("$4.50 is left of $5.00.");
    expect(describeLeft({ left: 0, limit: 5, cost_known: false })).toMatch(/not known, and nothing more is spent/);
  });
});

describe("what is said of how many methods there are", () => {
  it("is none, one, or some", () => {
    expect(describeMethods(0)).toBe("No methods yet");
    expect(describeMethods(1)).toBe("1 method");
    expect(describeMethods(2)).toBe("2 methods");
    expect(describeMethods(12)).toBe("12 methods");
  });
});

describe("what is said of the data a person described", () => {
  it("is nothing if they said nothing", () => {
    expect(describeScope(null)).toEqual([]);
    expect(describeScope({})).toEqual([]);
  });

  it("is a line for each part, in the order of the card, with the size and what it counts at the end", () => {
    expect(describeScope({ sample_size: 12000, sample_unit: "cells", input_format: "h5ad", assay: "10x", tissue: "blood", species: "human" })).toEqual([
      { label: "Species", value: "human" },
      { label: "Tissue", value: "blood" },
      { label: "Assay", value: "10x" },
      { label: "Input format", value: "h5ad" },
      { label: "Sample size", value: "12,000 cells" },
    ]);
  });

  it("has a size without what it counts, as it was said", () => {
    expect(describeScope({ sample_size: 40 })).toEqual([{ label: "Sample size", value: "40" }]);
    expect(describeScope(kept({ sample_size: 40 }))).toEqual([{ label: "Sample size", value: "40" }]);
  });

  it("leaves out what a bake-off keeps for what was not said: an empty text, and a size of none", () => {
    expect(describeScope(kept({}))).toEqual([]);
    expect(describeScope(kept({ tissue: "blood", sample_unit: "cells" }))).toEqual([{ label: "Tissue", value: "blood" }]);
  });
});

describe("what is said of where the right answers are", () => {
  const labels = { own: "truth.csv", column: "label", id_column: null } as BakeoffLabels;

  it("says that the answers go by the order of the data when no column says what each is for", () => {
    expect(describeLabels(labels)).toBe('truth.csv, the answers in "label", in the order of the data');
  });

  it("says the column of what each is the answer to when there is one", () => {
    expect(describeLabels({ ...labels, id_column: "cell" })).toBe('truth.csv, the answers in "label", with what each is the answer to in "cell"');
  });
});
