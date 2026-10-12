import { describe, expect, it } from "vitest";
import {
  activeJob,
  DATA_LAKE_BYTES,
  EMPTY_LOG,
  filterFiles,
  finishedSince,
  isActive,
  jobCounts,
  jobFraction,
  latestJob,
  LOG_LIMIT,
  logEnd,
  mergeLog,
  missingNames,
  roomWarning,
  stageLabel,
  startedText,
  stateLabel,
  stepLabel,
  stepsLeft,
  withJob,
} from "./setup";
import type { DataLakeFile, DataLakeSummary, Job, SetupStep } from "./types";

function job(changes: Partial<Job> = {}): Job {
  return {
    id: "abc",
    kind: "data_lake",
    subject: "data_lake",
    title: "Fetching Biomni's data lake",
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

describe("a job at work", () => {
  it("is at work while it runs or is being stopped, and not once it is over", () => {
    expect(isActive(job({ state: "running" }))).toBe(true);
    expect(isActive(job({ state: "stopping" }))).toBe(true);
    for (const state of ["succeeded", "failed", "stopped"] as const) expect(isActive(job({ state }))).toBe(false);
  });

  it("is told in a word for each state", () => {
    expect(["running", "stopping", "succeeded", "failed", "stopped"].map((state) => stateLabel(state as Job["state"]))).toEqual([
      "Running",
      "Stopping",
      "Done",
      "Failed",
      "Stopped",
    ]);
  });

  it("is told by its own word when it is in a state this does not know, which a newer server may have", () => {
    expect(stateLabel("paused" as Job["state"])).toBe("paused");
  });

  it("is found by what it does, and by what it does it for, when that is asked", () => {
    const jobs = [
      job({ id: "1", kind: "image", subject: "base", state: "succeeded" }),
      job({ id: "2", kind: "image", subject: "bio" }),
      job({ id: "3", kind: "data_lake", subject: "data_lake", state: "stopping" }),
    ];

    expect(activeJob(jobs, "image")?.id).toBe("2");
    expect(activeJob(jobs, "image", "bio")?.id).toBe("2");
    expect(activeJob(jobs, "image", "base")).toBeUndefined();
    expect(activeJob(jobs, "data_lake")?.id).toBe("3");
    expect(activeJob([], "image")).toBeUndefined();
  });
});

describe("what is left to do", () => {
  const step = (id: string, state: SetupStep["state"], required: boolean): SetupStep => ({ id, title: id, state, detail: "", required });

  it("is the steps that code cannot run without, not done, in order", () => {
    const steps = [
      step("docker", "done", true),
      step("image", "running", true),
      step("data_lake", "todo", false),
      step("model_key", "todo", true),
    ];

    expect(stepsLeft(steps).map((left) => left.id)).toEqual(["image", "model_key"]);
  });

  it("is nothing when what is needed is done, whatever else is not", () => {
    expect(stepsLeft([step("docker", "done", true), step("data_lake", "todo", false)])).toEqual([]);
    expect(stepsLeft([])).toEqual([]);
  });

  it("counts a step that is blocked as left", () => {
    expect(stepsLeft([step("image", "blocked", true)])).toHaveLength(1);
  });
});

describe("the name of a stage of the image", () => {
  it("is as the settings give it, and made from the stage if they do not know it", () => {
    expect(stageLabel("base")).toBe("Biomni base");
    expect(stageLabel("full")).toBe("Biomni full");
    expect(stageLabel("huge")).toBe("Biomni huge");
  });
});

describe("when a job began", () => {
  it("is said in words, as long ago as it was", () => {
    expect(startedText(new Date().toISOString())).toBe("Started just now");
    expect(startedText(new Date(Date.now() - 5 * 60_000).toISOString())).toBe("Started 5 min ago");
  });

  it("is said to be a while ago when the time cannot be read", () => {
    expect(startedText("")).toBe("Started a while ago");
    expect(startedText("not a time")).toBe("Started a while ago");
  });
});

describe("how far a job has got", () => {
  it("is all of it once it has succeeded, whatever it counted", () => {
    expect(jobFraction(job({ state: "succeeded" }))).toBe(1);
    expect(jobFraction(job({ state: "succeeded", progress: { done: 1, total: 4 } }))).toBe(1);
  });

  it("cannot be told of a job that counts nothing, as a build does", () => {
    expect(jobFraction(job({ kind: "image" }))).toBeNull();
    expect(jobFraction(job({ progress: { done: 0, total: 0 } }))).toBeNull();
    expect(jobFraction(job({ progress: { done: 2 } }))).toBeNull();
    expect(jobFraction(job({ progress: { total: 2 } }))).toBeNull();
  });

  it("is the files done, with the part of the one being fetched", () => {
    expect(jobFraction(job({ progress: { done: 1, total: 4 } }))).toBe(0.25);
    expect(jobFraction(job({ progress: { done: 1, total: 4, bytes: 50, bytes_total: 100 } }))).toBe(0.375);
  });

  it("leaves out the part of a file whose size is not announced", () => {
    expect(jobFraction(job({ progress: { done: 1, total: 4, bytes: 50, bytes_total: null } }))).toBe(0.25);
    expect(jobFraction(job({ progress: { done: 1, total: 4, bytes: 50, bytes_total: 0 } }))).toBe(0.25);
  });

  it("counts no more of a file than all of it, however much is said to be fetched", () => {
    expect(jobFraction(job({ progress: { done: 0, total: 4, bytes: 300, bytes_total: 100 } }))).toBe(0.25);
  });

  it("is never more than all of it, nor less than none", () => {
    expect(jobFraction(job({ progress: { done: 1, total: 2, bytes: 500, bytes_total: 100 } }))).toBe(1);
    expect(jobFraction(job({ progress: { done: 9, total: 2 } }))).toBe(1);
    expect(jobFraction(job({ progress: { done: -3, total: 2 } }))).toBe(0);
  });

  it("stays where a job that failed or was stopped got to", () => {
    expect(jobFraction(job({ state: "failed", progress: { done: 3, total: 4 } }))).toBe(0.75);
    expect(jobFraction(job({ state: "stopped", progress: { done: 1, total: 4 } }))).toBe(0.25);
  });
});

describe("what a job has counted", () => {
  it("is files and bytes, and how much of the file it is on", () => {
    const counted = job({
      progress: { done: 3, total: 76, fetched: 2 * 1024 * 1024, current: "a.csv", bytes: 1024, bytes_total: 4096 },
    });

    expect(jobCounts(counted)).toBe("3 of 76 files · 2.0 MB fetched · 1.0 KB of 4.0 KB of this file");
  });

  it("says file for one file, and says nothing of bytes before any are fetched", () => {
    expect(jobCounts(job({ progress: { done: 0, total: 1, fetched: 0 } }))).toBe("0 of 1 file");
  });

  it("says nothing of the file it is on once it is over, or when its size is not announced", () => {
    const over = job({ state: "succeeded", progress: { done: 2, total: 2, current: "a.csv", bytes: 5, bytes_total: 10 } });

    expect(jobCounts(over)).toBe("2 of 2 files");
    expect(jobCounts(job({ progress: { done: 0, total: 2, current: "a.csv", bytes: 5, bytes_total: null } }))).toBe("0 of 2 files");
    expect(jobCounts(job({ progress: { done: 0, total: 2, current: null, bytes: 5, bytes_total: 10 } }))).toBe("0 of 2 files");
  });

  it("is nothing for a job that counts nothing", () => {
    expect(jobCounts(job({ kind: "image" }))).toBe("");
    expect(jobCounts(job({ progress: { total: 0, done: 0 } }))).toBe("");
  });
});

describe("what a job printed", () => {
  const lines = (from: number, count: number) => Array.from({ length: count }, (_, at) => `line ${from + at}`);

  it("begins with nothing held, which ends at 0", () => {
    expect(EMPTY_LOG).toEqual({ start: 0, lines: [] });
    expect(logEnd(EMPTY_LOG)).toBe(0);
  });

  it("is added to by what comes after what is held", () => {
    const first = mergeLog(EMPTY_LOG, { from: 0, lines: lines(0, 3) });
    const second = mergeLog(first, { from: 3, lines: lines(3, 2) });

    expect(second).toEqual({ start: 0, lines: lines(0, 5) });
    expect(logEnd(second)).toBe(5);
  });

  it("does not add again what is held, however the answers overlap", () => {
    const held = mergeLog(EMPTY_LOG, { from: 0, lines: lines(0, 5) });

    expect(mergeLog(held, { from: 3, lines: lines(3, 4) })).toEqual({ start: 0, lines: lines(0, 7) });
    expect(mergeLog(held, { from: 0, lines: lines(0, 5) })).toBe(held);
    expect(mergeLog(held, { from: 1, lines: lines(1, 2) })).toBe(held);
  });

  it("adds a single line that comes after what is held, even when the answer begins before it", () => {
    const held = mergeLog(EMPTY_LOG, { from: 0, lines: lines(0, 3) });

    expect(mergeLog(held, { from: 2, lines: lines(2, 2) })).toEqual({ start: 0, lines: lines(0, 4) });
    expect(mergeLog(held, { from: 3, lines: lines(3, 1) })).toEqual({ start: 0, lines: lines(0, 4) });
  });

  it("starts again where the server has dropped what came between", () => {
    const held = mergeLog(EMPTY_LOG, { from: 0, lines: lines(0, 3) });

    expect(mergeLog(held, { from: 10, lines: lines(10, 2) })).toEqual({ start: 10, lines: lines(10, 2) });
  });

  it("holds no more than the server does, dropping the oldest and saying where it begins", () => {
    const held = mergeLog(EMPTY_LOG, { from: 0, lines: lines(0, LOG_LIMIT) });
    const more = mergeLog(held, { from: LOG_LIMIT, lines: lines(LOG_LIMIT, 5) });

    expect(more.lines).toHaveLength(LOG_LIMIT);
    expect(more.start).toBe(5);
    expect(more.lines[0]).toBe("line 5");
    expect(more.lines.at(-1)).toBe(`line ${LOG_LIMIT + 4}`);
    expect(logEnd(more)).toBe(LOG_LIMIT + 5);
  });

  it("holds as many lines as the server does, 2000, and drops the first of one more", () => {
    expect(LOG_LIMIT).toBe(2000);
    expect(mergeLog(EMPTY_LOG, { from: 0, lines: lines(0, 2000) }).start).toBe(0);

    const over = mergeLog(EMPTY_LOG, { from: 0, lines: lines(0, 2001) });

    expect(over.start).toBe(1);
    expect(over.lines).toHaveLength(2000);
  });

  it("holds no more than the server does when it has dropped lines and gives more than it holds", () => {
    const given = mergeLog(EMPTY_LOG, { from: 50, lines: lines(50, LOG_LIMIT + 3) });

    expect(given.start).toBe(53);
    expect(given.lines).toHaveLength(LOG_LIMIT);
  });
});

describe("the files of the data lake", () => {
  const file = (name: string, description: string, present: boolean, commercial = true): DataLakeFile => ({
    name,
    description,
    present,
    bytes: present ? 10 : null,
    commercial,
  });
  const files = [
    file("DepMap_Model.csv", "Cell line models and their lineage", true),
    file("BindingDB_All.tsv", "Measured binding affinities between proteins and small molecules", false, false),
    file("gwas_catalog.parquet", "Associations between variants and traits", false),
  ];

  it("are all there is with nothing typed", () => {
    expect(filterFiles(files, "", false)).toHaveLength(3);
    expect(filterFiles(files, "   ", false)).toHaveLength(3);
  });

  it("are those with every word typed, in the name or in what they are, in any order and whatever the case", () => {
    expect(filterFiles(files, "binding AFFINITIES", false).map((found) => found.name)).toEqual(["BindingDB_All.tsv"]);
    expect(filterFiles(files, "traits variants", false).map((found) => found.name)).toEqual(["gwas_catalog.parquet"]);
    expect(filterFiles(files, "depmap", false).map((found) => found.name)).toEqual(["DepMap_Model.csv"]);
    expect(filterFiles(files, "depmap affinities", false)).toEqual([]);
  });

  it("are only those not there when that is asked", () => {
    expect(filterFiles(files, "", true).map((found) => found.name)).toEqual(["BindingDB_All.tsv", "gwas_catalog.parquet"]);
    expect(filterFiles(files, "depmap", true)).toEqual([]);
  });

  it("have their names given, for those not there, and for those of them that may be used commercially", () => {
    expect(missingNames(files)).toEqual(["BindingDB_All.tsv", "gwas_catalog.parquet"]);
    expect(missingNames(files, true)).toEqual(["gwas_catalog.parquet"]);
    expect(missingNames([])).toEqual([]);
  });
});

describe("jobs that have finished", () => {
  it("is told when a job that was at work has finished since", () => {
    expect(finishedSince([job({ id: "a" })], [job({ id: "a", state: "succeeded" })])).toBe(true);
    expect(finishedSince([job({ id: "a", state: "stopping" })], [job({ id: "a", state: "stopped" })])).toBe(true);
    expect(finishedSince([job({ id: "a" })], [job({ id: "a", state: "failed" })])).toBe(true);
  });

  it("is told when a job that was at work is gone, as when the server has started again", () => {
    expect(finishedSince([job({ id: "a" })], [])).toBe(true);
    expect(finishedSince([job({ id: "a" })], [job({ id: "b" })])).toBe(true);
  });

  it("is not told while the jobs at work are at work still, or of one that had finished before", () => {
    expect(finishedSince([job({ id: "a" })], [job({ id: "a", log_total: 4 })])).toBe(false);
    expect(finishedSince([job({ id: "a", state: "running" })], [job({ id: "a", state: "stopping" })])).toBe(false);
    expect(finishedSince([job({ id: "a", state: "succeeded" })], [])).toBe(false);
    expect(finishedSince([], [job({ id: "a" })])).toBe(false);
  });
});

describe("a job added to the jobs", () => {
  it("is first when it is new", () => {
    const old = job({ id: "old", state: "succeeded" });
    const fresh = job({ id: "new" });

    expect(withJob([old], fresh)).toEqual([fresh, old]);
    expect(withJob([], fresh)).toEqual([fresh]);
  });

  it("takes the place of the one it is, and leaves the order", () => {
    const first = job({ id: "a" });
    const second = job({ id: "b" });
    const done = job({ id: "a", state: "succeeded" });

    expect(withJob([first, second], done)).toEqual([done, second]);
    expect(withJob([second, first], done)).toEqual([second, done]);
  });
});

describe("the words for a step", () => {
  it("has one for each state, and the state itself for one it does not know", () => {
    expect(stepLabel("done")).toBe("Done");
    expect(stepLabel("todo")).toBe("To do");
    expect(stepLabel("running")).toBe("In progress");
    expect(stepLabel("blocked")).toBe("Waiting");
    expect(stepLabel("other" as never)).toBe("other");
  });
});

describe("the latest job of a subject", () => {
  it("is the first the list gives of its kind and subject, at work or not", () => {
    const newer = job({ id: "new", kind: "image", subject: "base", state: "failed" });
    const older = job({ id: "old", kind: "image", subject: "base", state: "succeeded" });
    const other = job({ id: "other", kind: "image", subject: "bio" });

    expect(latestJob([other, newer, older], "image", "base")).toBe(newer);
    expect(latestJob([other, newer, older], "image", "bio")).toBe(other);
  });

  it("is none when no job is of both the kind and the subject", () => {
    const base = job({ kind: "image", subject: "base" });

    expect(latestJob([base], "data_lake", "base")).toBeUndefined();
    expect(latestJob([base], "image", "full")).toBeUndefined();
    expect(latestJob([], "image", "base")).toBeUndefined();
  });
});

describe("the warning of too little room", () => {
  function lake(changes: Partial<DataLakeSummary>): DataLakeSummary {
    return { directory: "/data", custom: false, files: 76, present: 0, complete: false, bytes: 0, free_bytes: null, ...changes };
  }

  it("says how much is left to fetch and how much is free when it will not fit", () => {
    expect(roomWarning(lake({ free_bytes: 2 * 1024 ** 3 }))).toBe(
      "The rest of the data lake takes up to about 11 GB, and 2.0 GB is free where it is kept.",
    );
  });

  it("takes off what is there already from what is left to fetch", () => {
    const text = roomWarning(lake({ bytes: 4 * 1024 ** 3, free_bytes: 2 * 1024 ** 3 }));

    expect(text).toContain("up to about 7.0 GB");
  });

  it("says nothing when it fits, exactly, or when it is all there, or when the room is not known", () => {
    expect(roomWarning(lake({ free_bytes: DATA_LAKE_BYTES }))).toBeNull();
    expect(roomWarning(lake({ free_bytes: DATA_LAKE_BYTES * 2 }))).toBeNull();
    expect(roomWarning(lake({ complete: true, present: 76, free_bytes: 1 }))).toBeNull();
    expect(roomWarning(lake({ free_bytes: null }))).toBeNull();
  });

  it("says nothing of a data lake that has more than the whole there, which is left to finish", () => {
    expect(roomWarning(lake({ bytes: DATA_LAKE_BYTES * 2, free_bytes: 0 }))).toBeNull();
  });
});
