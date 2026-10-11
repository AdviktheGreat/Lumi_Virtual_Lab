import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { MAX_ATTACHMENTS } from "./attachments";
import type { Attachment } from "./types";
import { createUploader } from "./uploader";

interface Sent {
  chatId: string;
  file: File;
  signal: AbortSignal;
  onProgress: (fraction: number) => void;
  take: (attachment: Attachment) => void;
  refuse: (error: unknown) => void;
}

const file = (name: string, size = 3, lastModified = 1) => new File([new Uint8Array(size)], name, { lastModified });
const kept = (name: string): Attachment => ({ name, path: `uploads/${name}`, size: 3 });
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

// The real uploader, with a connection that sends nothing anywhere until a test says how each file went
function setup() {
  const sent: Sent[] = [];
  const uploader = createUploader(
    (chatId, chosen, options) =>
      new Promise<Attachment>((take, refuse) => {
        sent.push({ chatId, file: chosen, signal: options.signal, onProgress: options.onProgress, take, refuse });
      }),
  );
  const heard = { count: 0 };
  uploader.subscribe(() => (heard.count += 1));
  // Chooses files for no conversation, so that they wait, and gives the items they became
  const wait = (...names: string[]) => {
    uploader.choose(names.map((name) => file(name)), null, null);

    return uploader.items().slice(-names.length);
  };

  return { uploader, sent, heard, wait };
}

describe("choosing files", () => {
  it("holds them, queued, without sending them when there is no conversation for them yet", () => {
    const { uploader, sent, wait } = setup();

    const refused = uploader.choose([file("a.csv"), file("b.csv")], null, null);

    expect(refused).toEqual([]);
    expect(uploader.items().map((item) => [item.file.name, item.status])).toEqual([
      ["a.csv", "queued"],
      ["b.csv", "queued"],
    ]);
    expect(sent).toEqual([]);
    expect(wait("c.csv")[0].id).toBe(2);
  });

  it("sends each at once when there is a conversation for them", () => {
    const { uploader, sent } = setup();

    uploader.choose([file("a.csv"), file("b.csv")], "chat-1", null);

    expect(sent.map((each) => [each.chatId, each.file.name])).toEqual([
      ["chat-1", "a.csv"],
      ["chat-1", "b.csv"],
    ]);
    expect(uploader.items().map((item) => item.status)).toEqual(["uploading", "uploading"]);
  });

  it("numbers them from where the last choosing ended, even when some were turned away", () => {
    const { uploader } = setup();
    uploader.choose([file("a.csv")], null, null);
    uploader.choose([file("a.csv"), file("b.csv")], null, null);
    uploader.choose([file("c.csv")], null, null);

    expect(uploader.items().map((item) => [item.id, item.file.name])).toEqual([
      [0, "a.csv"],
      [2, "b.csv"],
      [3, "c.csv"],
    ]);
  });

  it("says why a file was turned away, and holds and sends the rest", () => {
    const { uploader, sent } = setup();

    const refused = uploader.choose([file("big.csv", 50), file("small.csv", 5)], "chat-1", 10);

    expect(refused).toEqual(["big.csv is larger than the 10 B that can be attached"]);
    expect(uploader.items().map((item) => item.file.name)).toEqual(["small.csv"]);
    expect(sent.map((each) => each.file.name)).toEqual(["small.csv"]);
  });

  it("holds no more than a message can go with", () => {
    const { uploader } = setup();
    const many = Array.from({ length: MAX_ATTACHMENTS + 1 }, (_, at) => file(`f${at}.csv`));

    const refused = uploader.choose(many, null, null);

    expect(uploader.items()).toHaveLength(MAX_ATTACHMENTS);
    expect(refused).toEqual([`Only ${MAX_ATTACHMENTS} files can go with one message`]);
  });

  it("tells those that watch only when something changed", () => {
    const { uploader, heard } = setup();

    uploader.choose([], null, null);
    expect(heard.count).toBe(0);
    uploader.choose([file("a.csv")], null, null);
    expect(heard.count).toBe(1);
    uploader.choose([file("a.csv")], null, null);
    expect(heard.count).toBe(1);
  });

  it("stops telling a watcher that has stopped watching", () => {
    const { uploader } = setup();
    let told = 0;
    const stop = uploader.subscribe(() => (told += 1));

    uploader.choose([file("a.csv")], null, null);
    stop();
    uploader.choose([file("b.csv")], null, null);

    expect(told).toBe(1);
  });
});

describe("sending a file", () => {
  it("begins it, follows its progress, and has it ready with the name the server gave it", async () => {
    const { uploader, sent } = setup();

    uploader.choose([file("a.csv")], "chat-1", null);
    expect(uploader.items()[0].status).toBe("uploading");
    sent[0].onProgress(0.5);
    expect(uploader.items()[0].progress).toBe(0.5);
    sent[0].take(kept("a (1).csv"));
    await settle();

    expect(uploader.items()[0]).toMatchObject({ status: "ready", progress: 1, attachment: kept("a (1).csv") });
  });

  it("fails it, with why in words and whether trying again can work", async () => {
    const { uploader, sent } = setup();

    uploader.choose([file("a.csv"), file("b.csv")], "chat-1", null);
    sent[0].refuse(new ApiError(413, "too_large", "a.csv is too large"));
    sent[1].refuse(new Error("The file could not be sent."));
    await settle();

    expect(uploader.items().map((each) => [each.status, each.error, each.retryable])).toEqual([
      ["failed", "a.csv is too large", false],
      ["failed", "The file could not be sent.", true],
    ]);
  });
});

describe("taking files away", () => {
  it("calls off those that are on their way, takes them all out of the tray, and leaves the others be", async () => {
    const { uploader, sent, wait } = setup();
    uploader.choose([file("a.csv"), file("b.csv"), file("c.csv")], "chat-1", null);
    const [first, second, third] = uploader.items();
    const [waiting] = wait("d.csv");

    uploader.remove([first.id, third.id, waiting.id, 99]);
    await settle();

    expect(sent.map((each) => each.signal.aborted)).toEqual([true, false, true]);
    expect(uploader.items().map((item) => item.id)).toEqual([second.id]);
    expect(uploader.items()[0].status).toBe("uploading");
  });

  it("calls off all that are on their way, and none that have finished", async () => {
    const { uploader, sent } = setup();
    uploader.choose([file("a.csv"), file("b.csv")], "chat-1", null);
    sent[0].take(kept("a.csv"));
    await settle();

    uploader.cancelAll();
    await settle();

    expect(sent.map((each) => each.signal.aborted)).toEqual([false, true]);
  });

  it("calls off a file that is sent again after it failed", async () => {
    const { uploader, sent } = setup();
    uploader.choose([file("a.csv")], "chat-1", null);
    sent[0].refuse(new Error("gone"));
    await settle();
    uploader.retry(uploader.items()[0].id, "chat-1");

    uploader.remove([uploader.items()[0].id]);
    await settle();

    expect(sent.map((each) => each.signal.aborted)).toEqual([false, true]);
  });
});

describe("trying a file again", () => {
  async function failed() {
    const parts = setup();
    parts.uploader.choose([file("a.csv")], "chat-1", null);
    parts.sent[0].refuse(new Error("lost"));
    await settle();

    return parts;
  }

  it("sends one that failed to its conversation again", async () => {
    const { uploader, sent } = await failed();

    uploader.retry(uploader.items()[0].id, "chat-1");

    expect(sent).toHaveLength(2);
    expect(uploader.items()[0].status).toBe("uploading");
    sent[1].take(kept("a.csv"));
    await settle();
    expect(uploader.items()[0].status).toBe("ready");
  });

  it("leaves it to be sent with the others when there is no conversation yet", async () => {
    const { uploader, sent } = await failed();

    uploader.retry(uploader.items()[0].id, null);

    expect(sent).toHaveLength(1);
    expect(uploader.items()[0]).toMatchObject({ status: "queued", error: null });
  });

  it("does nothing for a file that has not failed, or is not there", () => {
    const { uploader, sent, heard, wait } = setup();
    const [waiting] = wait("a.csv");
    uploader.choose([file("b.csv")], "chat-1", null);
    const going = uploader.items()[1];
    const before = heard.count;

    uploader.retry(waiting.id, "chat-1");
    uploader.retry(going.id, "chat-1");
    uploader.retry(99, "chat-1");
    uploader.retry(waiting.id, null);

    expect(sent).toHaveLength(1);
    expect(heard.count).toBe(before);
  });
});

describe("sending the files that wait", () => {
  it("sends those that are queued and no others, and names every file there is in the order they were chosen", async () => {
    const { uploader, sent, wait } = setup();
    wait("b.csv", "c.csv");
    uploader.choose([file("a.csv")], "chat-1", null);
    sent[0].take(kept("a.csv"));
    await settle();
    expect(uploader.items().map((each) => each.status)).toEqual(["queued", "queued", "ready"]);

    const result = uploader.upload("chat-2");
    expect(sent.slice(1).map((each) => [each.chatId, each.file.name])).toEqual([
      ["chat-2", "b.csv"],
      ["chat-2", "c.csv"],
    ]);
    sent[2].take(kept("c (1).csv"));
    sent[1].take(kept("b.csv"));

    expect(await result).toEqual(["b.csv", "c (1).csv", "a.csv"]);
  });

  it("names a file once, though the server may have given two the same name", async () => {
    const { uploader, sent, wait } = setup();
    wait("a.csv", "b.csv");

    const result = uploader.upload("chat-1");
    sent[0].take(kept("same.csv"));
    sent[1].take(kept("same.csv"));

    expect(await result).toEqual(["same.csv"]);
  });

  it("sends nothing and names nothing when nothing waits", async () => {
    const { uploader, sent } = setup();

    expect(await uploader.upload("chat-1")).toEqual([]);
    expect(sent).toEqual([]);
  });

  it("gives every file the time to finish before it raises the first error", async () => {
    const { uploader, sent, wait } = setup();
    wait("a.csv", "b.csv", "c.csv");

    let outcome = "pending";
    const result = uploader.upload("chat-1").then(
      () => (outcome = "named"),
      (error: Error) => (outcome = error.message),
    );
    sent[0].refuse(new Error("first"));
    sent[1].refuse(new Error("second"));
    await settle();
    expect(outcome).toBe("pending");
    sent[2].take(kept("c.csv"));
    await result;

    expect(outcome).toBe("first");
    expect(uploader.items().map((each) => each.status)).toEqual(["failed", "failed", "ready"]);
  });

  it("sends again those that were sent and are waiting again", async () => {
    const { uploader, sent, wait } = setup();
    wait("a.csv");
    const first = uploader.upload("chat-1");
    sent[0].take(kept("a.csv"));
    await first;

    uploader.requeue();
    expect(uploader.items()[0]).toMatchObject({ status: "queued", attachment: null });
    const second = uploader.upload("chat-2");
    sent[1].take(kept("a.csv"));

    expect(await second).toEqual(["a.csv"]);
    expect(sent.map((each) => each.chatId)).toEqual(["chat-1", "chat-2"]);
  });
});
