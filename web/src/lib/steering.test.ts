import { describe, expect, it } from "vitest";
import { controlsFor, currentTurn, holdNotice, unreadNotes } from "./steering";
import type { Outcome, Step, Turn } from "./transcript";
import type { ChatState } from "./types";

const note = (text: string): Step => ({ kind: "note", key: `note-${text}`, text, to: "lead", read: true });

const turn = (number: number, outcome: Outcome = "running", steps: Step[] = []): Turn => ({
  number,
  user: null,
  steps,
  writing: "",
  outcome,
  text: "",
  errorType: null,
});

describe("what can be done in each state", () => {
  it("writes a message when the lead is not at work, and can do nothing to a turn that is not there", () => {
    expect(controlsFor("idle")).toMatchObject({ writes: "message", canNote: false, canPause: false, canStop: false });
  });

  it("writes a note while the lead works, which can be held or stopped", () => {
    expect(controlsFor("running")).toMatchObject({
      writes: "note",
      canNote: true,
      pause: "pause",
      canPause: true,
      canStop: true,
    });
  });

  it("lets a turn that is being held, or is held, go on, and still takes notes and stops", () => {
    for (const state of ["pausing", "paused"] as const) {
      expect(controlsFor(state)).toMatchObject({ writes: "note", canNote: true, pause: "resume", canPause: true, canStop: true });
    }
  });

  it("can do nothing but wait for a turn that is being stopped", () => {
    expect(controlsFor("stopping")).toMatchObject({ writes: "note", canNote: false, canPause: false, canStop: false });
  });

  it("says what to write in each state", () => {
    const said = (["idle", "running", "pausing", "paused", "stopping"] as ChatState[]).map((state) => controlsFor(state).placeholder);

    expect(said).toEqual([
      "Ask the lead scientist…",
      "Add a note, which the lead reads before its next step…",
      "Add a note, which the lead reads before its next step…",
      "Add a note, then resume…",
      "Stopping…",
    ]);
  });

  it("treats a state it does not know as work going on, which can be stopped", () => {
    expect(controlsFor("compacting" as ChatState)).toEqual(controlsFor("running"));
  });
});

describe("what is said of a turn that is held or stopped", () => {
  it("says that it is being held, is held, or is being stopped, and nothing of a turn that goes on", () => {
    expect(holdNotice("pausing")).toBe("Pausing once this step is done…");
    expect(holdNotice("paused")).toBe("Paused. The lead goes on when you resume.");
    expect(holdNotice("stopping")).toBe("Stopping once this step is done…");
    expect(holdNotice("running")).toBeNull();
    expect(holdNotice("idle")).toBeNull();
    expect(holdNotice("compacting" as ChatState)).toBeNull();
  });
});

describe("the turn that is going on", () => {
  it("is the first when there is none yet", () => {
    expect(currentTurn([])).toBe(1);
  });

  it("is the last when it is not over", () => {
    expect(currentTurn([turn(1, "answered"), turn(2, "running")])).toBe(2);
  });

  it("is the next when the last is over, since the lead is at work on a message not yet told of", () => {
    for (const outcome of ["answered", "stopped", "failed"] as const) {
      expect(currentTurn([turn(1), turn(2, outcome)])).toBe(3);
    }
  });
});

describe("notes that have not been read", () => {
  const sent = (turnNumber: number, text: string) => ({ turn: turnNumber, text });

  it("are those sent that the conversation has not told of", () => {
    const turns = [turn(1, "running", [note("first")])];

    expect(unreadNotes([sent(1, "first"), sent(1, "second")], turns, true)).toEqual([sent(1, "second")]);
  });

  it("are none while the lead is not at work", () => {
    expect(unreadNotes([sent(1, "late")], [turn(1, "running")], false)).toEqual([]);
  });

  it("are none in a turn that is over, which has told of every note it was sent", () => {
    for (const outcome of ["answered", "stopped", "failed"] as const) {
      expect(unreadNotes([sent(1, "x")], [turn(1, outcome)], true)).toEqual([]);
    }
  });

  it("wait for a turn that has not been told of yet", () => {
    expect(unreadNotes([sent(2, "early")], [turn(1, "answered")], true)).toEqual([sent(2, "early")]);
  });

  it("are told of one at a time when the same words are sent twice", () => {
    const sentTwice = [sent(1, "again"), sent(1, "again")];

    expect(unreadNotes(sentTwice, [turn(1, "running")], true)).toEqual(sentTwice);
    expect(unreadNotes(sentTwice, [turn(1, "running", [note("again")])], true)).toEqual([sent(1, "again")]);
    expect(unreadNotes(sentTwice, [turn(1, "running", [note("again"), note("again")])], true)).toEqual([]);
  });

  it("are not taken for told of by the same words in another turn", () => {
    const turns = [turn(1, "answered", [note("words")]), turn(2, "running")];

    expect(unreadNotes([sent(2, "words")], turns, true)).toEqual([sent(2, "words")]);
  });

  it("are told of by notes that were not read too, which is a note that came late", () => {
    const late: Step = { kind: "note", key: "n", text: "late", to: null, read: false };

    expect(unreadNotes([sent(1, "late")], [turn(1, "running", [late])], true)).toEqual([]);
  });

  it("are not told of by what else the lead did", () => {
    const said: Step = { kind: "say", key: "s", text: "words" };

    expect(unreadNotes([sent(1, "words")], [turn(1, "running", [said])], true)).toEqual([sent(1, "words")]);
  });
});
