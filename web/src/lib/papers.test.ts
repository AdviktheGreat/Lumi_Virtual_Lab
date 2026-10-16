import { describe, expect, it } from "vitest";
import {
  checkFunctions,
  checkRead,
  checkRun,
  describeSource,
  EMPTY_FUNCTIONS,
  EMPTY_READ,
  EMPTY_RUN,
  isPaperName,
  lastJob,
  runFacts,
  uploadProblem,
  workJob,
  workKey,
} from "./papers";
import type { Job, PaperRunEntry } from "./types";

function job(changes: Partial<Job> = {}): Job {
  return {
    id: "j1",
    kind: "papers",
    subject: "run-a",
    title: "Reading papers: Run A",
    state: "running",
    message: "",
    progress: {},
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    finished_at: null,
    log_total: 0,
    ...changes,
  };
}

function run(changes: Partial<PaperRunEntry> = {}): PaperRunEntry {
  return {
    id: "run-a",
    title: "Run A",
    source: { kind: "files" },
    created_at: "2026-01-01T00:00:00Z",
    files: 2,
    papers: null,
    finished: 0,
    read: null,
    unavailable: null,
    failed: null,
    spent: null,
    stopped: null,
    function_count: 0,
    given: false,
    job: null,
    job_kind: null,
    ...changes,
  };
}

describe("where papers come from, in words", () => {
  it("says what each source is", () => {
    expect(describeSource({ kind: "files" })).toBe("Papers uploaded to it");
    expect(describeSource({ kind: "folder", path: "/data/papers", recursive: false })).toBe("Papers in /data/papers");
    expect(describeSource({ kind: "folder", path: "/data/papers", recursive: true })).toBe(
      "Papers in /data/papers and the folders in it",
    );
  });

  it("says the period, the subject, and how many of a bioRxiv run", () => {
    const source = { kind: "biorxiv", since: "2025-01-01", until: null, subject: "all", limit: 1, random: false, include_unpublished: false } as const;

    expect(describeSource(source)).toBe("bioRxiv preprints of every subject, from 2025-01-01 on, up to 1 preprint");
    expect(describeSource({ ...source, until: "2025-02-01", subject: "genomics", limit: 5, random: true })).toBe(
      "bioRxiv preprints of genomics, from 2025-01-01 to 2025-02-01, 5 preprints chosen at random",
    );
  });
});

describe("how far a run has got", () => {
  it("says what was uploaded before anything is read", () => {
    expect(runFacts(run())).toBe("2 papers uploaded, not read yet");
    expect(runFacts(run({ files: 1 }))).toBe("1 paper uploaded, not read yet");
    expect(runFacts(run({ files: null }))).toBe("Not read yet");
  });

  it("says how many are dealt with while the first reading is going on", () => {
    expect(runFacts(run({ finished: 3 }))).toBe("3 papers dealt with so far");
  });

  it("says what was read, what was not, what it cost, and the functions written", () => {
    const read = run({ papers: 5, read: 3, unavailable: 1, failed: 1, spent: 0.5, function_count: 2 });

    expect(runFacts(read)).toBe("Read 3 of 5 papers · 1 unavailable · 1 failed · spent $0.50 · 2 functions");
    expect(runFacts(run({ papers: 1, read: 1, unavailable: 0, failed: 0, spent: null }))).toBe("Read 1 of 1 paper");
  });
});

describe("the work at hand on a run", () => {
  it("is the job at work on it, of the kinds that work on a run", () => {
    const jobs = [job({ id: "x", subject: "run-b" }), job({ id: "y", kind: "image" }), job({ id: "z", kind: "functions" })];

    expect(workJob(jobs, "run-a")?.id).toBe("z");
    expect(workJob(jobs, "run-c")).toBeUndefined();
    expect(workJob([job({ state: "succeeded" })], "run-a")).toBeUndefined();
  });

  it("is, once there is none, the latest that is over", () => {
    const jobs = [job({ id: "new", state: "stopped" }), job({ id: "old", state: "failed" })];

    expect(lastJob(jobs, "run-a")?.id).toBe("new");
    expect(lastJob([job()], "run-a")).toBeUndefined();
  });

  it("has a key that changes as a job gets on, and as one ends", () => {
    const before = workKey([job({ progress: { finished: 1 } })], 0);

    expect(workKey([job({ progress: { finished: 2 } })], 0)).not.toBe(before);
    expect(workKey([job({ state: "succeeded", progress: { finished: 2 } })], 1)).not.toBe(before);
    expect(workKey([job({ progress: { finished: 1 } })], 0)).toBe(before);
  });

  it("has a key for one run that does not change with the work on another", () => {
    const other = job({ id: "o", subject: "run-b", progress: { finished: 1 } });

    expect(workKey([other], 0, "run-a")).toBe(workKey([], 0, "run-a"));
    expect(workKey(null, 0)).toBe(workKey([], 0));
  });
});

describe("what reading may spend", () => {
  it("is asked for, and is dollars as they are typed", () => {
    expect(checkRead({ ...EMPTY_READ, budget: "" }).problems.budget).toBe("Say the most it may spend.");
    for (const typed of ["lots", "-1", "1e3", "1,5", "$", "NaN", "Infinity"]) {
      expect(checkRead({ ...EMPTY_READ, budget: typed }).value).toBeNull();
    }
    expect(checkRead({ ...EMPTY_READ, budget: "$ 2.50 " }).value?.max_cost).toBe(2.5);
    expect(checkRead({ ...EMPTY_READ, budget: ".5" }).value?.max_cost).toBe(0.5);
    expect(checkRead({ ...EMPTY_READ, budget: "0" }).value?.max_cost).toBe(0);
  });

  it("may leave out what one paper may spend, but not mistype it", () => {
    expect(checkRead(EMPTY_READ).value).toEqual({ max_cost: 1, max_cost_per_paper: null, retry_failed: false });
    expect(checkRead({ ...EMPTY_READ, perPaper: "0.1", retryFailed: true }).value).toEqual({
      max_cost: 1,
      max_cost_per_paper: 0.1,
      retry_failed: true,
    });
    expect(checkRead({ ...EMPTY_READ, perPaper: "x" }).problems.perPaper).toBe(
      "The most one paper may spend is an amount in dollars, such as 1 or 0.50.",
    );
  });
});

describe("what writing functions may spend, and which", () => {
  it("is what the library asks by default", () => {
    expect(checkFunctions(EMPTY_FUNCTIONS).value).toEqual({
      max_cost: 1,
      max_cost_per_function: null,
      min_papers: 1,
      limit: 10,
      retry_failed: false,
      verify: false,
    });
  });

  it("holds the number of functions and of papers to what the server takes", () => {
    for (const limit of ["0", "101", "1.5", "ten", ""]) {
      expect(checkFunctions({ ...EMPTY_FUNCTIONS, limit }).problems.limit).toBe("The number of functions is a whole number from 1 to 100.");
    }
    expect(checkFunctions({ ...EMPTY_FUNCTIONS, limit: "100" }).value?.limit).toBe(100);
    expect(checkFunctions({ ...EMPTY_FUNCTIONS, minPapers: "0" }).problems.minPapers).toBeDefined();
    expect(checkFunctions({ ...EMPTY_FUNCTIONS, minPapers: "100000" }).value?.min_papers).toBe(100000);
    expect(checkFunctions({ ...EMPTY_FUNCTIONS, minPapers: "100001" }).value).toBeNull();
  });

  it("says every thing that is wrong at once", () => {
    const checked = checkFunctions({ ...EMPTY_FUNCTIONS, budget: "", perFunction: "x", limit: "0" });

    expect(Object.keys(checked.problems).sort()).toEqual(["budget", "limit", "perFunction"]);
  });
});

describe("a run that is asked for", () => {
  it("needs a title, which is tidied", () => {
    expect(checkRun(EMPTY_RUN).problems.title).toBe("Give the run a title.");
    expect(checkRun({ ...EMPTY_RUN, title: "  Gene \n  papers " }).value).toEqual({ title: "Gene papers", source: { kind: "files" } });
    expect(checkRun({ ...EMPTY_RUN, title: "x".repeat(201) }).problems.title).toContain("at most 200 characters");
  });

  it("needs the path of the folder for a folder, which is trimmed", () => {
    const draft = { ...EMPTY_RUN, title: "T", kind: "folder" as const };

    expect(checkRun(draft).problems.path).toBe("Give the full path of the folder.");
    expect(checkRun({ ...draft, path: " /data ", recursive: true }).value?.source).toEqual({
      kind: "folder",
      path: "/data",
      recursive: true,
    });
  });

  it("needs a first day that is a day for bioRxiv, and a last that does not come before it", () => {
    const draft = { ...EMPTY_RUN, title: "T", kind: "biorxiv" as const, since: "2025-03-01" };

    expect(checkRun({ ...draft, since: "" }).problems.since).toBe("Say the first day, as a date.");
    expect(checkRun({ ...draft, since: "2025-02-30" }).problems.since).toBeDefined();
    expect(checkRun({ ...draft, until: "2025-02-01" }).problems.until).toBe("The last day is before the first.");
    expect(checkRun({ ...draft, until: "soon" }).problems.until).toBeDefined();
    expect(checkRun({ ...draft, until: "2025-03-01", limit: "5", random: true }).value?.source).toEqual({
      kind: "biorxiv",
      since: "2025-03-01",
      until: "2025-03-01",
      subject: "all",
      limit: 5,
      random: true,
      include_unpublished: false,
    });
    expect(checkRun(draft).value?.source).toMatchObject({ until: null });
  });

  it("holds the number of preprints to what the server takes", () => {
    const draft = { ...EMPTY_RUN, title: "T", kind: "biorxiv" as const, since: "2025-03-01" };

    for (const limit of ["0", "501", "many", ""]) expect(checkRun({ ...draft, limit }).problems.limit).toBeDefined();
    expect(checkRun({ ...draft, limit: "500" }).value).not.toBeNull();
  });

  it("does not ask of a source what is not for it", () => {
    expect(checkRun({ ...EMPTY_RUN, title: "T", since: "nonsense", path: "" }).value).not.toBeNull();
  });
});

describe("a paper that is uploaded", () => {
  const limits = { bytes: 1000, suffixes: [".pdf", ".txt"], files: 2 };

  it("is of a kind that is read, whatever the case", () => {
    expect(isPaperName("a.PDF", limits.suffixes)).toBe(true);
    expect(isPaperName("a.docx", limits.suffixes)).toBe(false);
    expect(isPaperName("txt", limits.suffixes)).toBe(false);
  });

  it("is refused before it is sent for what the server would refuse it for", () => {
    expect(uploadProblem({ name: "a.txt", size: 10 }, [], limits)).toBeNull();
    expect(uploadProblem({ name: "a.docx", size: 10 }, [], limits)).toContain("is not a paper this reads");
    expect(uploadProblem({ name: "a.txt", size: 2000 }, [], limits)).toContain("is larger than the 1000 B");
    expect(uploadProblem({ name: "A.TXT", size: 10 }, ["a.txt"], limits)).toContain("in this run already");
    expect(uploadProblem({ name: "c.txt", size: 10 }, ["a.txt", "b.txt"], limits)).toBe("No more than 2 papers can be uploaded to one run.");
  });
});
