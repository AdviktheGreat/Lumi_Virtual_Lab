import { describe, expect, it } from "vitest";
import {
  checkWatch,
  describeAffects,
  describeDependencies,
  describeFile,
  describeHours,
  describeImage,
  describeLooked,
  describeNotLooked,
  describeTool,
  describeUpdate,
  describeWatch,
  lineKind,
  nextLook,
  shortCommit,
  statusVariant,
  toolHeld,
} from "./paperagent-living";
import { HEALTH_JOB, healthJob, lastHealthJob, readingKey } from "./paperagents";
import type { HealthRecord, Job, UpdateFile } from "./types";

const OLD = "a".repeat(40);
const NEW = "b".repeat(40);

const job = (part: Partial<Job> = {}): Job =>
  ({
    id: "j1",
    kind: HEALTH_JOB,
    subject: "cells",
    title: "Looking at the agent: Cells",
    state: "running",
    created_at: "2026-01-01T00:00:00Z",
    progress: {},
    error: null,
    ...part,
  }) as Job;

const pins = (part: Partial<NonNullable<HealthRecord["dependencies"]>> = {}): Pick<HealthRecord, "dependencies" | "dependencies_message"> => ({
  dependencies: { kind: "pip", total: 3, looked_at: 3, unsaid: 0, problems: [], ...part },
  dependencies_message: null,
});

const file = (part: Partial<UpdateFile> = {}): UpdateFile => ({
  path: "cellmapper/core.py",
  change: "changed",
  added: 2,
  removed: 1,
  diff: "--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y",
  cut: false,
  binary: false,
  ...part,
});

describe("the job of a look", () => {
  it("is the one at work for the agent, or the last one that is over", () => {
    const running = job();
    const over = job({ id: "j0", state: "succeeded" });
    const other = job({ id: "j2", subject: "other" });
    const checks = job({ id: "j3", kind: "paperagent-checks" });
    expect(healthJob([other, checks, over, running], "cells")).toBe(running);
    expect(healthJob([over, other], "cells")).toBeUndefined();
    expect(lastHealthJob([running, over], "cells")).toBe(over);
    expect(lastHealthJob([running, other], "cells")).toBeUndefined();
  });

  it("changes what the page is looked at again by, while a look goes on", () => {
    expect(readingKey([job()], 0, "cells")).not.toBe(readingKey([], 0, "cells"));
    expect(readingKey([job()], 0, "cells")).toContain("health:j1");
    expect(readingKey([job({ subject: "other" })], 0, "cells")).toBe(readingKey([], 0, "cells"));
    expect(readingKey([job({ state: "succeeded" })], 0, "cells")).toBe(readingKey([], 0, "cells"));
  });
});

describe("what a look found", () => {
  it("gives each word a badge, and a broken one stands out", () => {
    expect(statusVariant("healthy")).toBe("default");
    expect(statusVariant("degraded")).toBe("secondary");
    expect(statusVariant("broken")).toBe("destructive");
    expect(statusVariant("unchecked")).toBe("outline");
  });

  it("says when it was looked at and how long that took", () => {
    const now = new Date("2026-01-01T03:00:00Z");
    expect(describeLooked({ checked_at: "2026-01-01T01:00:00Z", seconds: 12.4 }, now)).toBe("Looked at 2 h ago, which took 12 s.");
    expect(describeLooked({ checked_at: "2026-01-01T02:59:30Z", seconds: 0.3 }, now)).toBe("Looked at just now, which took under a second.");
    expect(describeLooked({ checked_at: "not a time", seconds: 1 }, now)).toBe("Looked at a while ago, which took 1 s.");
  });

  it("says why there is nothing to show", () => {
    expect(describeNotLooked({ watchable: false, health: null })).toBe("Make the tools first. An agent is looked at by running its tools again.");
    expect(describeNotLooked({ watchable: true, health: null })).toContain("not since its code, environment, or tools were made again");
    expect(describeNotLooked({ watchable: true, health: {} as HealthRecord })).toBeNull();
  });

  it("says whether the image is there, and that Docker not answering is not its being gone", () => {
    expect(describeImage(true)).toBe("The image of the environment is in Docker.");
    expect(describeImage(false)).toBe("The image of the environment is not in Docker any more.");
    expect(describeImage(null)).toContain("could not be asked");
  });

  it("says what PyPI said of the pins", () => {
    expect(describeDependencies(pins())).toBe("All 3 pinned versions were asked of PyPI, and none is gone or yanked.");
    expect(describeDependencies(pins({ looked_at: 2, problems: [{ name: "scanpy", version: "1.9.3", state: "yanked" }] }))).toBe(
      "2 of 3 pinned versions were asked of PyPI, and 1 cannot be installed again as it is.",
    );
    const two = [
      { name: "a", version: "1", state: "yanked" },
      { name: "b", version: "2", state: "missing" },
    ];
    expect(describeDependencies(pins({ problems: two, unsaid: 1 }))).toBe(
      "All 3 pinned versions were asked of PyPI, and 2 cannot be installed again as they are. PyPI did not say of 1, which is not held against it.",
    );
    expect(describeDependencies(pins({ total: 0, looked_at: 0 }))).toBe("The lock pins no version that the index can be asked of.");
    expect(describeDependencies({ dependencies: null, dependencies_message: "It is a conda one." })).toBe("It is a conda one.");
    expect(describeDependencies({ dependencies: null, dependencies_message: null })).toBe("The pinned versions were not asked of.");
  });

  it("says how each tool did, and that one with no recorded call was not held to anything", () => {
    const tool = (calls: number, matched: number, message: string | null = null) => ({ name: "scale", calls, matched, message });
    expect(describeTool(tool(3, 3))).toBe("Gave again what its tutorials got, 3 of 3 calls.");
    expect(describeTool(tool(1, 1))).toBe("Gave again what its tutorials got, 1 of 1 call.");
    expect(describeTool(tool(3, 1, "gave 0.91 where its tutorial got 0.93"))).toBe(
      "1 of 3 calls gave again what its tutorials got. gave 0.91 where its tutorial got 0.93",
    );
    expect(describeTool(tool(2, 0))).toBe("0 of 2 calls gave again what its tutorials got.");
    expect(describeTool(tool(0, 0))).toContain("not held to anything");
    expect(toolHeld(tool(3, 3))).toBe("matched");
    expect(toolHeld(tool(3, 2))).toBe("differs");
    expect(toolHeld(tool(0, 0))).toBe("unheld");
  });
});

describe("the schedule", () => {
  it("says hours as a person would", () => {
    expect(describeHours(1)).toBe("hour");
    expect(describeHours(6)).toBe("6 hours");
    expect(describeHours(24)).toBe("day");
    expect(describeHours(168)).toBe("7 days");
    expect(describeHours(36)).toBe("36 hours");
  });

  it("is looked at next the hours after it was last started, or at once if it never was", () => {
    expect(nextLook({ every_hours: 6, last_started_at: null })).toBeNull();
    expect(nextLook({ every_hours: 6, last_started_at: "nonsense" })).toBeNull();
    expect(nextLook({ every_hours: 6, last_started_at: "2026-01-01T00:00:00Z" })?.toISOString()).toBe("2026-01-01T06:00:00.000Z");
  });

  it("says what it is, and when the next look is", () => {
    const now = new Date("2026-01-01T03:00:00Z");
    expect(describeWatch(null, now)).toBe("It is not looked at on a schedule. It is looked at when you ask.");
    const fresh = { every_hours: 24, set_at: "2026-01-01T00:00:00Z", last_started_at: null };
    expect(describeWatch(fresh, now)).toBe(
      "It is looked at every day while the server is running. It is looked at the next time the server checks the schedules, which it does once a minute.",
    );
    const late = { ...fresh, every_hours: 2, last_started_at: "2026-01-01T00:00:00Z" };
    expect(describeWatch(late, now)).toContain("the next time the server checks");
    const later = { ...fresh, every_hours: 6, last_started_at: "2026-01-01T00:00:00Z" };
    expect(describeWatch(later, now)).toMatch(/^It is looked at every 6 hours while the server is running\. It is looked at next Jan 1, /);
  });

  it("takes a whole number of hours in range", () => {
    const limits = { min_hours: 1, max_hours: 2160 };
    expect(checkWatch("6", limits)).toEqual({ value: 6 });
    expect(checkWatch(" 2160 ", limits)).toEqual({ value: 2160 });
    expect(checkWatch("1", limits)).toEqual({ value: 1 });
    for (const typed of ["0", "2161", "1.5", "", "six", "-3"]) {
      expect(checkWatch(typed, limits)).toEqual({ value: null, problem: "How often it is looked at, in hours, is a whole number from 1 to 2160." });
    }
  });
});

describe("a newer version", () => {
  it("is said in a line, with short commits", () => {
    expect(shortCommit(NEW)).toBe("bbbbbbb");
    expect(describeUpdate({ from_commit: OLD, to_commit: NEW, changed: 3 })).toBe("From aaaaaaa to bbbbbbb: 3 files changed.");
    expect(describeUpdate({ from_commit: OLD, to_commit: NEW, changed: 1 })).toBe("From aaaaaaa to bbbbbbb: 1 file changed.");
  });

  it("says which tools and environment files it touches, and what is not told", () => {
    expect(describeAffects({ affects: ["scale"], environment_files: [] })).toEqual(["The file of the tool scale changed."]);
    expect(describeAffects({ affects: ["scale", "embed"], environment_files: ["requirements.txt"] })).toEqual([
      "The file of the tools scale, embed changed.",
      "Files that say what the environment is made of changed: requirements.txt.",
    ]);
    expect(describeAffects({ affects: [], environment_files: [] })[0]).toContain("is not told of by this");
  });

  it("says of each file what is shown of it", () => {
    expect(describeFile(file())).toBe("2 added, 1 taken away.");
    expect(describeFile(file({ cut: true }))).toBe("2 added, 1 taken away. Its diff is cut, as it is long.");
    expect(describeFile(file({ binary: true, diff: null }))).toBe("Not text, so its lines are not shown.");
    expect(describeFile(file({ added: null, removed: null, diff: null }))).toBe("Its lines were not compared, as only the first files' are.");
    expect(describeFile(file({ change: "added", added: 4, removed: 0 }))).toBe("4 added, 0 taken away.");
    expect(describeFile(file({ added: 4, removed: null }))).toBe("Its lines were not compared, as only the first files' are.");
  });

  it("tells the lines of a diff apart", () => {
    expect(lineKind("--- a/cellmapper/core.py")).toBe("meta");
    expect(lineKind("+++ b/cellmapper/core.py")).toBe("meta");
    expect(lineKind("@@ -1,3 +1,3 @@")).toBe("hunk");
    expect(lineKind("+    return 1")).toBe("added");
    expect(lineKind("-    return 0")).toBe("removed");
    expect(lineKind("     same")).toBe("same");
    expect(lineKind("")).toBe("same");
  });
});
