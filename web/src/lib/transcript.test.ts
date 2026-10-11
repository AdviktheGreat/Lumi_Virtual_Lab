import { describe, expect, it } from "vitest";
import { emptyTranscript, reduce, replay } from "./transcript";
import type { ChatEvent, ChatEventKind } from "./types";

let next = 0;

function event(kind: ChatEventKind, turn: number, fields: Partial<ChatEvent> = {}): ChatEvent {
  next += 1;

  return { kind, id: next, turn, speaker: null, text: "", data: {}, time: 0, ...fields };
}

describe("a transcript", () => {
  it("is what the events of its turns say, from the researcher's message to the answer", () => {
    next = 0;
    const transcript = replay([
      event("status", 0, { data: { state: "running" } }),
      event("user", 1, { text: "What is a nanobody?", data: { attachments: [{ name: "a.csv", path: "uploads/a.csv", size: 3 }] } }),
      event("title", 1, { text: "What is a nanobody?" }),
      event("writing", 1, { text: "Nano" }),
      event("writing", 1, { text: "Nanobodies are small" }),
    ]);

    expect(transcript.state).toBe("running");
    expect(transcript.title).toBe("What is a nanobody?");
    expect(transcript.turns).toEqual([
      {
        number: 1,
        user: { text: "What is a nanobody?", attachments: [{ name: "a.csv", path: "uploads/a.csv", size: 3 }] },
        writing: "Nanobodies are small",
        outcome: "running",
        text: "",
        errorType: null,
      },
    ]);

    const done = replay(
      [event("answer", 1, { text: "Nanobodies are small antibodies." }), event("status", 0, { data: { state: "idle" } })],
      transcript,
    );

    expect(done.state).toBe("idle");
    expect(done.turns[0]).toMatchObject({ outcome: "answered", text: "Nanobodies are small antibodies.", writing: "" });
  });

  it("keeps the turns apart and in order", () => {
    next = 0;
    const transcript = replay([
      event("user", 1, { text: "one" }),
      event("answer", 1, { text: "first answer" }),
      event("user", 2, { text: "two" }),
      event("failed", 2, { text: "It broke", data: { type: "RuntimeError" } }),
      event("user", 3, { text: "three" }),
      event("stopped", 3, { text: "Stopped." }),
    ]);

    expect(transcript.turns.map((turn) => [turn.number, turn.outcome, turn.text, turn.errorType])).toEqual([
      [1, "answered", "first answer", null],
      [2, "failed", "It broke", "RuntimeError"],
      [3, "stopped", "Stopped.", null],
    ]);
  });

  it("is not changed by an event it has read, or one before it, so that a stream started again is harmless", () => {
    next = 0;
    const events = [event("user", 1, { text: "hello" }), event("writing", 1, { text: "Hi" }), event("answer", 1, { text: "Hi there" })];
    const once = replay(events);

    expect(replay(events, once)).toBe(once);
    expect(reduce(once, events[1])).toBe(once);
    expect(once.lastId).toBe(events[2].id);
  });

  it("has a turn for an event of a turn it was not told the beginning of", () => {
    next = 0;
    const transcript = replay([event("answer", 4, { text: "An answer" })]);

    expect(transcript.turns).toEqual([
      { number: 4, user: null, writing: "", outcome: "answered", text: "An answer", errorType: null },
    ]);
  });

  it("does not take what a scientist in a team session writes for the lead's reply", () => {
    next = 0;
    const transcript = replay([
      event("user", 1, { text: "Bring in the team" }),
      event("writing", 1, { text: "The Immunologist says", data: { meeting: "team-1", request: 1 } }),
    ]);

    expect(transcript.turns[0].writing).toBe("");
  });

  it("holds what has been spent and what may be", () => {
    next = 0;
    const transcript = replay([event("usage", 1, { data: { cost: 0.0123, max_cost: 2 } })]);

    expect([transcript.spent, transcript.maxCost]).toEqual([0.0123, 2]);

    const unknown = replay([event("usage", 1, { data: { cost: null, max_cost: null } })], transcript);

    expect([unknown.spent, unknown.maxCost]).toEqual([null, null]);
  });

  it("holds nothing for what the usage does not say", () => {
    next = 0;
    const transcript = replay([event("usage", 1, { data: { cost: 1, max_cost: 2 } }), event("usage", 1, { data: {} })]);

    expect(transcript.spent).toBeNull();
    expect(transcript.maxCost).toBeNull();
  });

  it("gives the kind of error only to a turn that failed", () => {
    next = 0;
    const transcript = replay([
      event("user", 1, { text: "one" }),
      event("stopped", 1, { text: "Stopped.", data: { type: "Interrupted" } }),
    ]);

    expect(transcript.turns[0]).toMatchObject({ outcome: "stopped", errorType: null });
  });

  it("has no files for a message whose files are not a list", () => {
    next = 0;
    const transcript = replay([event("user", 1, { text: "hi", data: { attachments: "a.csv" } })]);

    expect(transcript.turns[0].user?.attachments).toEqual([]);
  });

  it("reads past events it does not show yet", () => {
    next = 0;
    const transcript = replay([event("user", 1, { text: "hi" }), event("tool_calls", 1), event("cell", 1), event("lab", 1)]);

    expect(transcript.lastId).toBe(4);
    expect(transcript.turns).toHaveLength(1);
  });

  it("starts with nothing", () => {
    expect(emptyTranscript).toMatchObject({ title: "", state: "idle", turns: [], lastId: 0, spent: null, maxCost: null });
  });
});
