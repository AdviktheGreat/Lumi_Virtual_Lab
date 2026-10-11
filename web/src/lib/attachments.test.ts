import { describe, expect, it } from "vitest";
import { ApiError, NetworkError } from "./api";
import {
  MAX_ATTACHMENTS,
  attachedNames,
  canRetry,
  counts,
  intake,
  readiness,
  tray,
  type TrayAction,
  type TrayItem,
} from "./attachments";

const file = (name: string, size = 10, lastModified = 1) => new File([new Uint8Array(size)], name, { lastModified });

const item = (id: number, fields: Partial<TrayItem> = {}): TrayItem => ({
  id,
  file: file(`file-${id}.csv`),
  status: "queued",
  progress: 0,
  attachment: null,
  error: null,
  retryable: true,
  ...fields,
});

const run = (items: TrayItem[], ...actions: TrayAction[]) => actions.reduce(tray, items);

describe("choosing files", () => {
  it("queues each file, numbered from where the last batch ended by its place among those chosen", () => {
    const { items, refused } = intake([], [file("a.csv"), file("b.csv")], null, 5);

    expect(refused).toEqual([]);
    expect(items.map((added) => [added.id, added.file.name, added.status, added.progress, added.retryable])).toEqual([
      [5, "a.csv", "queued", 0, true],
      [6, "b.csv", "queued", 0, true],
    ]);
  });

  it("numbers the files that are taken by their place among those chosen, so that none of the next batch shares a number", () => {
    const { items } = intake([], [file("big.bin", 100), file("small.bin", 5)], 50, 0);

    expect(items.map((added) => added.id)).toEqual([1]);
  });

  it("turns a file away that is larger than may be attached, with its name and the size it may be, and takes the rest", () => {
    const { items, refused } = intake([], [file("big.bin", 3 * 1024 * 1024), file("ok.bin", 1024 * 1024)], 2 * 1024 * 1024, 0);

    expect(items.map((added) => added.file.name)).toEqual(["ok.bin"]);
    expect(refused).toEqual(["big.bin is larger than the 2.0 MB that can be attached"]);
  });

  it("takes a file exactly as large as may be attached, and any when the server has not said", () => {
    expect(intake([], [file("fits.bin", 5)], 5, 0).items).toHaveLength(1);
    expect(intake([], [file("huge.bin", 10 ** 6)], null, 0).items).toHaveLength(1);
  });

  it("does not take a file again that is there, by its name, size and date, whether it is waiting, on its way, or done", () => {
    for (const status of ["queued", "uploading", "ready"] as const) {
      const existing = [item(1, { file: file("a.csv", 10, 7), status })];

      expect(intake(existing, [file("a.csv", 10, 7)], null, 2).items).toEqual([]);
    }
  });

  it("takes a file of the same name that is not the same file, or that failed before", () => {
    const existing = [item(1, { file: file("a.csv", 10, 7) })];

    expect(intake(existing, [file("a.csv", 11, 7), file("a.csv", 10, 8)], null, 2).items).toHaveLength(2);
    expect(intake([item(1, { file: file("a.csv", 10, 7), status: "failed" })], [file("a.csv", 10, 7)], null, 2).items).toHaveLength(1);
  });

  it("does not take the same file twice from one batch", () => {
    expect(intake([], [file("a.csv"), file("a.csv")], null, 0).items).toHaveLength(1);
  });

  it("takes no more than the most that go with a message, and says so once", () => {
    const existing = Array.from({ length: MAX_ATTACHMENTS - 1 }, (_, id) => item(id));

    const { items, refused } = intake(existing, [file("last.csv"), file("one-too-many.csv"), file("another.csv")], null, 500);

    expect(items.map((added) => added.file.name)).toEqual(["last.csv"]);
    expect(refused).toEqual([`Only ${MAX_ATTACHMENTS} files can go with one message`]);
  });

  it("says nothing of the most when it was not reached", () => {
    expect(intake([], [file("a.csv")], null, 0).refused).toEqual([]);
  });
});

describe("how a file gets on", () => {
  const attachment = { name: "a (2).csv", path: "uploads/a (2).csv", size: 10 };

  it("starts a file, which clears what was wrong the last time", () => {
    const [started] = run([item(1, { status: "failed", progress: 0.4, error: "no" })], { type: "begin", id: 1 });

    expect(started).toMatchObject({ status: "uploading", progress: 0, error: null });
  });

  it("follows how much of a file has gone, never back, and never past all of it", () => {
    const started = run([item(1)], { type: "begin", id: 1 });

    expect(run(started, { type: "progress", id: 1, progress: 0.5 })[0].progress).toBe(0.5);
    expect(run(started, { type: "progress", id: 1, progress: 0.5 }, { type: "progress", id: 1, progress: 0.2 })[0].progress).toBe(0.5);
    expect(run(started, { type: "progress", id: 1, progress: 7 })[0].progress).toBe(1);
  });

  it("keeps the name the server gave a file once it has it", () => {
    const [done] = run([item(1)], { type: "begin", id: 1 }, { type: "ready", id: 1, attachment });

    expect(done).toMatchObject({ status: "ready", progress: 1, attachment });
  });

  it("keeps what went wrong with a file, and whether it is worth another try", () => {
    const [failed] = run([item(1)], { type: "begin", id: 1 }, { type: "fail", id: 1, error: "Too big", retryable: false });

    expect(failed).toMatchObject({ status: "failed", error: "Too big", retryable: false });
  });

  it("leaves a file as it is when it is told of what happened to one that is not on its way", () => {
    const waiting = [item(1)];
    const ready = run([item(1)], { type: "begin", id: 1 }, { type: "ready", id: 1, attachment });
    const failed = run([item(1)], { type: "begin", id: 1 }, { type: "fail", id: 1, error: "x", retryable: true });

    expect(run(waiting, { type: "progress", id: 1, progress: 0.5 }, { type: "ready", id: 1, attachment }, { type: "fail", id: 1, error: "x", retryable: true })).toEqual(waiting);
    expect(run(ready, { type: "progress", id: 1, progress: 0.1 }, { type: "fail", id: 1, error: "x", retryable: true })).toEqual(ready);
    expect(run(failed, { type: "ready", id: 1, attachment }, { type: "progress", id: 1, progress: 1 })).toEqual(failed);
  });

  it("changes only the file that is named", () => {
    const [first, second] = run([item(1), item(2)], { type: "begin", id: 2 });

    expect([first.status, second.status]).toEqual(["queued", "uploading"]);
  });

  it("is not changed by what is said of a file that has been taken away", () => {
    const items = run([item(1)], { type: "remove", ids: [1] });

    expect(run(items, { type: "begin", id: 1 }, { type: "progress", id: 1, progress: 1 })).toEqual([]);
  });

  it("adds files after those there, and takes away those named", () => {
    const added = run([item(1)], { type: "add", items: [item(2), item(3)] });

    expect(added.map((each) => each.id)).toEqual([1, 2, 3]);
    expect(run(added, { type: "remove", ids: [1, 3] }).map((each) => each.id)).toEqual([2]);
    expect(run(added, { type: "remove", ids: [] })).toHaveLength(3);
  });

  it("puts files that were sent or failed back to wait, but not one that is on its way", () => {
    const items = [
      item(1, { status: "ready", progress: 1, attachment }),
      item(2, { status: "failed", error: "x", retryable: false }),
      item(3, { status: "uploading", progress: 0.5 }),
      item(4, { status: "ready", progress: 1, attachment }),
    ];

    const [one, two, three, four] = run(items, { type: "requeue", ids: [1, 2, 3] });

    expect(one).toMatchObject({ status: "queued", progress: 0, attachment: null, error: null, retryable: true });
    expect(two).toMatchObject({ status: "queued", error: null, retryable: true });
    expect(three).toMatchObject({ status: "uploading", progress: 0.5 });
    expect(four.status).toBe("ready");
  });

  it("puts every file that is there back to wait, and leaves the rest as they are", () => {
    const items = [
      item(1, { status: "ready", progress: 1, attachment }),
      item(2, { status: "failed", error: "x", retryable: false }),
      item(3, { status: "uploading", progress: 0.5 }),
      item(4),
    ];

    const [one, two, three, four] = run(items, { type: "requeueReady" });

    expect(one).toMatchObject({ status: "queued", progress: 0, attachment: null, error: null, retryable: true });
    expect([two, three, four]).toEqual(items.slice(1));
  });
});

describe("what the files add up to", () => {
  const ready = (id: number, name: string) =>
    item(id, { status: "ready", attachment: { name, path: `uploads/${name}`, size: 1 } });

  it("counts the files in each state", () => {
    const items = [item(1), item(2, { status: "uploading" }), ready(3, "c"), ready(4, "d"), item(5, { status: "failed" })];

    expect(counts(items)).toEqual({ queued: 1, uploading: 1, ready: 2, failed: 1 });
    expect(counts([])).toEqual({ queued: 0, uploading: 0, ready: 0, failed: 0 });
  });

  it("names the files that are there as the server named them, once each, in order", () => {
    const items = [ready(1, "b.csv"), item(2), ready(3, "a.csv"), ready(4, "b.csv"), item(5, { status: "failed" })];

    expect(attachedNames(items)).toEqual(["b.csv", "a.csv"]);
  });

  it("does not name a file that says it is ready and has no name", () => {
    expect(attachedNames([item(1, { status: "ready" })])).toEqual([]);
  });

  it("holds a message up for files on their way, and says how many", () => {
    expect(readiness([item(1, { status: "uploading" })])).toBe("Uploading a file…");
    expect(readiness([item(1, { status: "uploading" }), item(2, { status: "uploading" }), ready(3, "c")])).toBe(
      "Uploading 2 files…",
    );
  });

  it("holds a message up for a file that failed, until it is tried again or taken away", () => {
    expect(readiness([ready(1, "a"), item(2, { status: "failed" })])).toBe("Retry or remove the file that failed");
  });

  it("waits for the files that are on their way before it speaks of one that failed", () => {
    expect(readiness([item(1, { status: "failed" }), item(2, { status: "uploading" })])).toBe("Uploading a file…");
  });

  it("holds a message up for nothing when files are done, waiting for a conversation, or not there", () => {
    expect(readiness([])).toBeNull();
    expect(readiness([ready(1, "a"), item(2)])).toBeNull();
  });
});

describe("trying a file again", () => {
  it("is worth it when the connection was lost or the server failed, and not when the server turned the file away", () => {
    expect(canRetry(new NetworkError(new TypeError("Failed to fetch")))).toBe(true);
    expect(canRetry(new Error("The file could not be sent."))).toBe(true);
    expect(canRetry(new ApiError(500, "internal", "Something went wrong"))).toBe(true);
    expect(canRetry(new ApiError(502, "error", "The server answered 502"))).toBe(true);
    expect(canRetry(new ApiError(300, "error", "Somewhere else"))).toBe(true);
    expect(canRetry(new ApiError(400, "invalid", "Not like that"))).toBe(false);
    expect(canRetry(new ApiError(499, "error", "Gone"))).toBe(false);
    expect(canRetry(new ApiError(413, "too_large", "Too big"))).toBe(false);
    expect(canRetry(new ApiError(422, "invalid", "No"))).toBe(false);
    expect(canRetry(new ApiError(404, "not_found", "Gone"))).toBe(false);
  });
});
