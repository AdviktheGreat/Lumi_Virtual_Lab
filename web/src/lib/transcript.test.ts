import { describe, expect, it } from "vitest";
import { emptyTranscript, isThinking, reduce, replay, waitingOnYou } from "./transcript";
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
        steps: [],
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

  it("drops a turn that is withdrawn, and shows the message that begins it again", () => {
    next = 0;
    const transcript = replay([
      event("user", 1, { text: "one" }),
      event("answer", 1, { text: "first answer" }),
      event("user", 2, { text: "two" }),
      event("failed", 2, { text: "It broke", data: { type: "RuntimeError" } }),
      event("withdrawn", 2, { data: { turn: 2 } }),
    ]);

    expect(transcript.turns.map((turn) => turn.number)).toEqual([1]);

    const again = replay([event("user", 2, { text: "two, changed" }), event("answer", 2, { text: "second answer" })], transcript);

    expect(again.turns.map((turn) => [turn.number, turn.user?.text, turn.outcome])).toEqual([
      [1, "one", "answered"],
      [2, "two, changed", "answered"],
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
      { number: 4, user: null, steps: [], writing: "", outcome: "answered", text: "An answer", errorType: null },
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
    const transcript = replay([event("user", 1, { text: "hi" }), event("lab", 1), event("status", 0, { data: { state: "idle" } })]);

    expect(transcript.lastId).toBe(3);
    expect(transcript.turns).toHaveLength(1);
    expect(transcript.turns[0].steps).toEqual([]);
  });

  it("starts with nothing", () => {
    expect(emptyTranscript).toMatchObject({ title: "", state: "idle", turns: [], lastId: 0, spent: null, maxCost: null });
  });
});

const call = (id: string, name: string, args: unknown = {}) => ({ id, name, arguments: JSON.stringify(args) });

const cellData = (fields: Record<string, unknown> = {}) => ({
  language: "python",
  code: "print(1)",
  status: "ok",
  output: "1\n",
  error: null,
  duration: 0.25,
  plots: [],
  produced_files: [],
  output_dropped: 0,
  sandboxed: false,
  tool_calls: [],
  value: null,
  plot_paths: [],
  call: "call_1",
  ...fields,
});

describe("what the lead does in a turn", () => {
  it("is what it says beside its calls, and the calls, in the order they were told of", () => {
    next = 0;
    const transcript = replay([
      event("user", 1, { text: "Count" }),
      event("writing", 1, { text: "Let me run" }),
      event("tool_calls", 1, { text: "Let me run that.", data: { calls: [call("call_1", "run_code", { code: "print(1)" }), call("call_2", "other")] } }),
    ]);
    const turn = transcript.turns[0];

    expect(turn.writing).toBe("");
    expect(turn.steps.map((step) => step.kind)).toEqual(["say", "call", "call"]);
    expect(turn.steps[0]).toMatchObject({ kind: "say", text: "Let me run that." });
    expect(turn.steps[1]).toMatchObject({
      kind: "call",
      call: { id: "call_1", name: "run_code", arguments: '{"code":"print(1)"}', status: "running", output: null, cells: [] },
    });
  });

  it("says nothing for a call made with no words beside it", () => {
    next = 0;
    const transcript = replay([event("user", 1), event("tool_calls", 1, { text: "  \n", data: { calls: [call("a", "run_code")] } })]);

    expect(transcript.turns[0].steps.map((step) => step.kind)).toEqual(["call"]);
  });

  it("has the code a call ran, and what it returned, with the call", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      event("tool_calls", 1, { data: { calls: [call("call_1", "run_code")] } }),
      event("cell", 1, { data: cellData({ output: "1\n", plots: ["plots/figure_1.png"], produced_files: ["plots/figure_1.png", "out.csv"], error: "", output_dropped: 12, value: 3 }) }),
      event("cell", 1, { data: cellData({ status: "error", error: "NameError: x", duration: 1.5 }) }),
      event("tool_output", 1, { text: "1", data: { call: "call_1", name: "run_code" } }),
    ]);
    const step = transcript.turns[0].steps[0];

    expect(step.kind === "call" && step.call.status).toBe("done");
    expect(step.kind === "call" && step.call.output).toBe("1");
    expect(step.kind === "call" && step.call.cells).toEqual([
      {
        language: "python",
        code: "print(1)",
        status: "ok",
        output: "1\n",
        error: null,
        duration: 0.25,
        plots: ["plots/figure_1.png"],
        producedFiles: ["plots/figure_1.png", "out.csv"],
        outputDropped: 12,
        value: 3,
      },
      expect.objectContaining({ status: "error", error: "NameError: x", duration: 1.5 }),
    ]);
  });

  it("keeps each call's cells and output with that call", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      event("tool_calls", 1, { data: { calls: [call("a", "run_code")] } }),
      event("cell", 1, { data: cellData({ call: "a", code: "a()" }) }),
      event("tool_output", 1, { text: "A", data: { call: "a" } }),
      event("tool_calls", 1, { data: { calls: [call("b", "run_code")] } }),
      event("cell", 1, { data: cellData({ call: "b", code: "b()" }) }),
    ]);
    const [first, second] = transcript.turns[0].steps.map((step) => (step.kind === "call" ? step.call : null));

    expect([first?.status, first?.output, first?.cells.map((cell) => cell.code)]).toEqual(["done", "A", ["a()"]]);
    expect([second?.status, second?.output, second?.cells.map((cell) => cell.code)]).toEqual(["running", null, ["b()"]]);
  });

  it("tells of a call again without making another of it", () => {
    next = 0;
    const calls = { data: { calls: [call("a", "run_code")] } };
    const transcript = replay([event("user", 1), event("tool_calls", 1, calls), event("tool_calls", 1, calls)]);

    expect(transcript.turns[0].steps).toHaveLength(1);
  });

  it("shows an answer to a call it was not told of, and drops a cell of one", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      event("cell", 1, { data: cellData({ call: "ghost" }) }),
      event("tool_output", 1, { text: "Unseen", data: { call: "ghost", name: "run_code" } }),
    ]);
    const steps = transcript.turns[0].steps;

    expect(steps).toHaveLength(1);
    expect(steps[0]).toMatchObject({ kind: "call", call: { id: "ghost", name: "run_code", status: "done", output: "Unseen", cells: [] } });
  });

  it("gives a call that came with no id one of its own by where it came", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      event("tool_calls", 1, { data: { calls: [{ name: "a", arguments: "{}" }, { name: "b", arguments: "{}" }] } }),
    ]);

    expect(transcript.turns[0].steps.map((step) => (step.kind === "call" ? step.call.id : null))).toEqual(["call-0", "call-1"]);
  });

  it("makes nothing of calls that are not a list, or are not calls", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      event("tool_calls", 1, { data: { calls: "run_code" } }),
      event("tool_calls", 1, { data: { calls: [null, 4, { id: "ok", name: "x", arguments: 3 }] } }),
    ]);
    const calls = transcript.turns[0].steps.map((step) => (step.kind === "call" ? step.call : null));

    expect(calls).toHaveLength(3);
    expect(calls[2]).toMatchObject({ id: "ok", name: "x", arguments: "" });
  });

  it("fills in what a cell leaves out", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      event("tool_calls", 1, { data: { calls: [call("a", "run_code")] } }),
      event("cell", 1, { data: { call: "a", plots: "none", duration: "fast", output_dropped: Infinity } }),
    ]);
    const step = transcript.turns[0].steps[0];

    expect(step.kind === "call" && step.call.cells[0]).toEqual({
      language: "python",
      code: "",
      status: "ok",
      output: "",
      error: null,
      duration: 0,
      plots: [],
      producedFiles: [],
      outputDropped: 0,
      value: null,
    });
  });

  it("is told of the resources the lead has, and of what it chose them for", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      event("resources", 1, {
        data: {
          mode: "retrieve",
          available: { tools: 3, data_lake: "many" },
          selected: { tools: ["m.a", 7, "m.b"], libraries: "numpy" },
          retrieval: { task: "Align reads", model: "m", reply: "..." },
        },
      }),
      event("resources", 1, { data: { mode: "all", available: {}, selected: {}, retrieval: null } }),
    ]);
    const [first, second] = transcript.turns[0].steps;

    expect(first).toMatchObject({
      kind: "resources",
      resources: { mode: "retrieve", available: { tools: 3, data_lake: 0 }, selected: { tools: ["m.a", "m.b"], libraries: [] }, task: "Align reads" },
    });
    expect(second).toMatchObject({ kind: "resources", resources: { mode: "all", task: null } });
  });

  it("takes resources that come with no mode as all that were named", () => {
    next = 0;
    const transcript = replay([event("user", 1), event("resources", 1, { data: { available: { tools: 2 } } })]);

    expect(transcript.turns[0].steps[0]).toMatchObject({ kind: "resources", resources: { mode: "all", available: { tools: 2 } } });
  });

  it("makes nothing of resources named outside a turn", () => {
    next = 0;
    const transcript = replay([event("resources", 0, { data: { mode: "all" } })]);

    expect(transcript.turns).toEqual([]);
    expect(transcript.lastId).toBe(1);
  });

  it("is told of a note, and whether anyone read it", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      event("note", 1, { text: "Look at B cells", data: { to: "lead", read: true } }),
      event("note", 1, { text: "Too late", data: { to: null, read: false } }),
      event("note", 1, { text: "Odd", data: { to: "somebody", read: "yes" } }),
    ]);

    expect(transcript.turns[0].steps).toEqual([
      { kind: "note", key: "note-2", text: "Look at B cells", to: "lead", read: true },
      { kind: "note", key: "note-3", text: "Too late", to: null, read: false },
      { kind: "note", key: "note-4", text: "Odd", to: null, read: false },
    ]);
  });

  it("settles what is still running when the turn ends: done for an answer, cut short for the rest", () => {
    next = 0;
    const running = (turn: number, id: string) => [
      event("user", turn),
      event("tool_calls", turn, { data: { calls: [call(id, "run_code")] } }),
    ];
    const statuses = (transcript: ReturnType<typeof replay>, turn: number) =>
      transcript.turns[turn].steps.map((step) => (step.kind === "call" ? step.call.status : null));

    const transcript = replay([
      ...running(1, "a"),
      event("answer", 1, { text: "Done" }),
      ...running(2, "b"),
      event("stopped", 2, { text: "Stopped." }),
      ...running(3, "c"),
      event("failed", 3, { text: "Failed" }),
    ]);

    expect(statuses(transcript, 0)).toEqual(["done"]);
    expect(statuses(transcript, 1)).toEqual(["interrupted"]);
    expect(statuses(transcript, 2)).toEqual(["interrupted"]);
  });

  it("does not change a call that was answered when the turn ends", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      event("tool_calls", 1, { data: { calls: [call("a", "run_code")] } }),
      event("tool_output", 1, { text: "ok", data: { call: "a" } }),
      event("stopped", 1, { text: "Stopped." }),
    ]);
    const step = transcript.turns[0].steps[0];

    expect(step.kind === "call" && step.call.status).toBe("done");
  });

  it("is not changed by a cell, an output, or a call it has read", () => {
    next = 0;
    const events = [
      event("user", 1),
      event("tool_calls", 1, { data: { calls: [call("a", "run_code")] } }),
      event("cell", 1, { data: cellData({ call: "a" }) }),
      event("tool_output", 1, { text: "x", data: { call: "a" } }),
    ];
    const once = replay(events);

    expect(replay(events, once)).toBe(once);
    expect(once.turns[0].steps).toHaveLength(1);
  });
});

describe("what a team does for the lead", () => {
  const labEvent = (turn: number, kind: string, fields: Partial<ChatEvent> & { details?: Record<string, unknown>; round?: number; call?: string } = {}) => {
    const { details, round, call: of, ...rest } = fields;

    return event("lab", turn, {
      data: { call: of ?? "call_1", event: kind, meeting: "lab_001", round: round ?? null, details: details ?? {} },
      ...rest,
    });
  };
  const convening = (id = "call_1") => event("tool_calls", 1, { data: { calls: [call(id, "convene_team", { agenda: "Design" })] } });
  const labOf = (transcript: ReturnType<typeof replay>, at = 0) => {
    const step = transcript.turns[0].steps[at];

    return step.kind === "call" ? step.call.lab : null;
  };

  it("is shown with the call that brought the team in, as it goes on", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      convening(),
      labEvent(1, "started", { details: { meeting_type: "team", agenda: "Design", num_rounds: 1, team: [{ title: "Immunologist" }] } }),
      labEvent(1, "turn", { speaker: "Immunologist", round: 1 }),
      labEvent(1, "message", { speaker: "Immunologist", round: 1, text: "Target it.", details: { kind: "response" } }),
    ]);
    const lab = labOf(transcript);

    expect(lab).toMatchObject({ meeting: "lab_001", status: "running", team: ["Immunologist"], rounds: 1 });
    expect(lab?.turns).toHaveLength(1);
    expect(lab?.turns[0]).toMatchObject({ speaker: "Immunologist", round: 1, steps: [{ kind: "reply", text: "Target it." }] });
  });

  it("is no turn of the lead's, and does not change what the lead has said or what the call returned", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      event("writing", 1, { text: "Let me" }),
      event("tool_calls", 1, { text: "Let me ask.", data: { calls: [call("call_1", "convene_team")] } }),
      event("writing", 1, { text: "I will wait" }),
      labEvent(1, "started", { details: { agenda: "x" } }),
      labEvent(1, "turn", { speaker: "Immunologist", round: 1 }),
      event("writing", 1, { speaker: "Immunologist", text: "Target", data: { call: "call_1", meeting: "lab_001", request: 1 } }),
    ]);
    const step = transcript.turns[0].steps.find((candidate) => candidate.kind === "call");

    expect(transcript.turns).toHaveLength(1);
    expect(transcript.turns[0].writing).toBe("I will wait");
    expect(transcript.turns[0].steps.map((candidate) => candidate.kind)).toEqual(["say", "call"]);
    expect(step?.kind === "call" && [step.call.status, step.call.output, step.call.cells]).toEqual(["running", null, []]);
    expect(labOf(transcript, 1)?.writing).toEqual({ speaker: "Immunologist", text: "Target" });
  });

  it("is told of by the call it belongs to, among several", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      event("tool_calls", 1, { data: { calls: [call("a", "consult"), call("b", "convene_team")] } }),
      labEvent(1, "started", { call: "b", details: { agenda: "Team" } }),
      labEvent(1, "started", { call: "a", details: { agenda: "One" } }),
    ]);

    expect(labOf(transcript, 0)?.agenda).toBe("One");
    expect(labOf(transcript, 1)?.agenda).toBe("Team");
  });

  it("is not shown for a call that was not told of, and makes no turn or call of its own", () => {
    next = 0;
    const before = replay([event("user", 1)]);
    const transcript = replay([
      labEvent(1, "started", { call: "ghost", details: { agenda: "x" } }),
      event("writing", 1, { speaker: "Immunologist", text: "x", data: { call: "ghost", meeting: "m" } }),
    ], before);

    expect(transcript.turns).toEqual(before.turns);
    // A turn that was not told of is not made for a session either
    expect(replay([labEvent(2, "started", { call: "ghost" })]).turns).toEqual([]);
    expect(replay([labEvent(0, "started", { call: "ghost" })]).turns).toEqual([]);
  });

  it("has no session before the team has started, however much of a reply is written", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      convening(),
      event("writing", 1, { speaker: "Immunologist", text: "early", data: { call: "call_1", meeting: "lab_001" } }),
    ]);

    expect(labOf(transcript)).toBeNull();
  });

  it("is told of again without being changed, so that a stream started again is harmless", () => {
    next = 0;
    const events = [event("user", 1), convening(), labEvent(1, "started", { details: { agenda: "x" } }), labEvent(1, "turn", { speaker: "Critic", round: 1 })];
    const once = replay(events);

    expect(replay(events, once)).toBe(once);
    expect(labOf(once)?.turns).toHaveLength(1);
  });

  it("is over with the summary, and the call that brought it in is answered with it", () => {
    next = 0;
    const transcript = replay([
      event("user", 1),
      convening(),
      labEvent(1, "started"),
      labEvent(1, "finished", { text: "The summary." }),
      event("tool_output", 1, { text: "The summary.", data: { call: "call_1", name: "convene_team" } }),
      event("answer", 1, { text: "Done." }),
    ]);
    const step = transcript.turns[0].steps[0];

    expect(labOf(transcript)).toMatchObject({ status: "finished", summary: "The summary." });
    expect(step.kind === "call" && step.call.status).toBe("done");
  });

  it("is cut short when the turn is, whether the researcher stopped it or it failed, and is not when it was over", () => {
    next = 0;
    const going = (turn: number, id: string) => [
      event("user", turn),
      event("tool_calls", turn, { data: { calls: [call(id, "convene_team")] } }),
      labEvent(turn, "started", { call: id }),
    ];
    const statusOf = (transcript: ReturnType<typeof replay>, turn: number) => {
      const step = transcript.turns[turn].steps[0];

      return step.kind === "call" ? step.call.lab?.status : undefined;
    };

    const transcript = replay([
      ...going(1, "a"),
      event("answer", 1, { text: "Done" }),
      ...going(2, "b"),
      event("stopped", 2, { text: "Stopped." }),
      ...going(3, "c"),
      event("failed", 3, { text: "Failed" }),
      event("user", 4),
      event("tool_calls", 4, { data: { calls: [call("d", "convene_team")] } }),
      labEvent(4, "started", { call: "d" }),
      labEvent(4, "finished", { call: "d", text: "Summary" }),
      event("stopped", 4, { text: "Stopped." }),
    ]);

    expect(statusOf(transcript, 0)).toBe("interrupted");
    expect(statusOf(transcript, 1)).toBe("interrupted");
    expect(statusOf(transcript, 2)).toBe("interrupted");
    expect(statusOf(transcript, 3)).toBe("finished");
  });
});

describe("when the lead is thinking", () => {
  const turnOf = (...events: ChatEvent[]) => {
    next = 0;

    return replay([event("user", 1), ...events]).turns[0];
  };
  const calling = (id: string) => event("tool_calls", 1, { data: { calls: [call(id, "run_code")] } });

  it("is so when it is at work and has shown nothing of what comes next", () => {
    expect(isThinking(turnOf(), true)).toBe(true);
    expect(isThinking(turnOf(calling("a"), event("tool_output", 1, { text: "ok", data: { call: "a" } })), true)).toBe(true);
  });

  it("is not so once it is writing", () => {
    expect(isThinking(turnOf(event("writing", 1, { text: "The" })), true)).toBe(false);
  });

  it("is not so while a call is running, which says what is being waited for", () => {
    expect(isThinking(turnOf(calling("a")), true)).toBe(false);
    expect(
      isThinking(turnOf(calling("a"), calling("b"), event("tool_output", 1, { text: "ok", data: { call: "b" } })), true),
    ).toBe(false);
  });

  it("is not so when the lead is not at work, or the turn is over", () => {
    expect(isThinking(turnOf(), false)).toBe(false);
    expect(isThinking(turnOf(event("answer", 1, { text: "Done" })), true)).toBe(false);
    expect(isThinking(turnOf(event("stopped", 1, { text: "Stopped" })), true)).toBe(false);
    expect(isThinking(turnOf(event("failed", 1, { text: "Broke" })), true)).toBe(false);
  });
});

describe("what the lead's servers and tools ask of the researcher", () => {
  // The events are numbered as they come, after the researcher's message
  const play = (...events: ChatEvent[]) => replay([event("user", 1), ...events].map((one, at) => ({ ...one, id: at + 1 })));
  const turnOf = (...events: ChatEvent[]) => play(...events).turns[0];
  const connection = (state: string, fields: Partial<ChatEvent> = {}, data: Record<string, unknown> = {}) =>
    event("connection", 1, { data: { server: "lit", title: "Literature", state, ...data }, ...fields });
  const asking = (request: string, fields: Record<string, unknown> = {}) =>
    event("approval", 1, {
      data: {
        request,
        state: "waiting",
        tool: "order",
        server: "lit",
        title: "Literature",
        description: "Orders a sample.",
        arguments: '{\n  "n": 2\n}',
        ...fields,
      },
    });
  const approval = (request: string, state: string) => event("approval", 1, { data: { request, state, server: "lit", title: "Literature" } });
  const question = (request: string, fields: Partial<ChatEvent> = {}, data: Record<string, unknown> = {}) =>
    event("question", 1, {
      text: "How many?",
      data: { request, state: "waiting", server: "lit", title: "Literature", fields: { n: { type: "integer" } }, required: ["n"], url: null, ...data },
      ...fields,
    });
  const ended = (request: string, state: string) => event("question", 1, { data: { request, state, server: "lit", title: "Literature" } });

  it("shows a server as it is connected to, and what came of it", () => {
    expect(turnOf(connection("connecting")).steps).toEqual([
      {
        kind: "connection",
        key: "connection-2",
        connection: { server: "lit", title: "Literature", state: "connecting", url: null, tools: null, text: "" },
      },
    ]);
    const steps = turnOf(connection("connecting"), connection("signing_in", {}, { url: "https://sign.in/x" }), connection("ready", {}, { tools: 4 })).steps;

    expect(steps).toHaveLength(1);
    expect(steps[0]).toMatchObject({ kind: "connection", connection: { state: "ready", tools: 4, url: null } });
  });

  it("has the sign-in page while the server waits for the researcher to sign in", () => {
    const [step] = turnOf(connection("connecting"), connection("signing_in", {}, { url: "https://sign.in/x" })).steps;

    expect(step).toMatchObject({ connection: { state: "signing_in", url: "https://sign.in/x" } });
  });

  it("says why a server could not be connected to", () => {
    const [step] = turnOf(connection("connecting"), connection("failed", { text: "It refused the connection." })).steps;

    expect(step).toMatchObject({ connection: { state: "failed", text: "It refused the connection." } });
  });

  it("keeps the servers apart, and shows one that is tried again as a new connection", () => {
    const steps = turnOf(
      connection("connecting"),
      connection("connecting", {}, { server: "geo", title: "Gene expression" }),
      connection("failed", { text: "Down." }),
      connection("ready", {}, { server: "geo", title: "Gene expression", tools: 2 }),
      connection("connecting"),
    ).steps;

    expect(steps.map((step) => step.kind === "connection" && [step.connection.server, step.connection.state])).toEqual([
      ["lit", "failed"],
      ["geo", "ready"],
      ["lit", "connecting"],
    ]);
  });

  it("is not thinking while a server is being connected to, and is once it has been", () => {
    expect(isThinking(turnOf(connection("connecting")), true)).toBe(false);
    expect(isThinking(turnOf(connection("connecting"), connection("signing_in", {}, { url: "https://sign.in/x" })), true)).toBe(false);
    expect(isThinking(turnOf(connection("connecting"), connection("ready", {}, { tools: 1 })), true)).toBe(true);
  });

  it("does not leave a server being connected to when the turn ends", () => {
    const [step] = turnOf(connection("connecting"), event("stopped", 1, { text: "Stopped." })).steps;

    expect(step).toMatchObject({ connection: { state: "failed", text: "Not connected: the turn ended before it was." } });
  });

  it("asks whether a call may be made, and shows how it was answered", () => {
    const [step] = turnOf(asking("r1")).steps;

    expect(step).toEqual({
      kind: "approval",
      key: "approval-r1",
      approval: {
        request: "r1",
        state: "waiting",
        tool: "order",
        server: "lit",
        title: "Literature",
        description: "Orders a sample.",
        arguments: '{\n  "n": 2\n}',
      },
    });
    for (const state of ["approved", "declined", "withdrawn"]) {
      const [ended] = turnOf(asking("r1"), approval("r1", state)).steps;

      expect(ended).toMatchObject({ approval: { request: "r1", state, tool: "order", arguments: '{\n  "n": 2\n}' } });
    }
  });

  it("answers the request an event is of, and no other", () => {
    const steps = turnOf(asking("r1"), asking("r2", { tool: "buy" }), approval("r2", "approved")).steps;

    expect(steps.map((step) => step.kind === "approval" && [step.approval.request, step.approval.state])).toEqual([
      ["r1", "waiting"],
      ["r2", "approved"],
    ]);
  });

  it("is not shown an end for a request that was never told of, and shows a request told of twice once", () => {
    expect(turnOf(approval("r9", "approved")).steps).toEqual([]);
    expect(turnOf(ended("r9", "answered")).steps).toEqual([]);
    expect(turnOf(asking("r1"), asking("r1")).steps).toHaveLength(1);
    expect(turnOf(question("q1"), question("q1")).steps).toHaveLength(1);
  });

  it("shows what a server asks, and how it ended", () => {
    const [step] = turnOf(question("q1")).steps;

    expect(step).toEqual({
      kind: "question",
      key: "question-q1",
      question: {
        request: "q1",
        state: "waiting",
        server: "lit",
        title: "Literature",
        text: "How many?",
        fields: { n: { type: "integer" } },
        required: ["n"],
        url: null,
      },
    });
    for (const state of ["answered", "declined", "withdrawn"]) {
      const [over] = turnOf(question("q1"), ended("q1", state)).steps;

      expect(over).toMatchObject({ question: { state, text: "How many?", fields: { n: { type: "integer" } }, required: ["n"] } });
    }
  });

  it("shows a question that was declined without being asked, with what it said", () => {
    const [step] = turnOf(event("question", 1, { text: "Go to it.\n\nIt was declined.", data: { request: "q2", state: "declined", server: "lit", title: "Literature" } })).steps;

    expect(step).toMatchObject({ kind: "question", question: { request: "q2", state: "declined", text: "Go to it.\n\nIt was declined." } });
  });

  it("has the page a question asks the researcher to go to", () => {
    const [step] = turnOf(question("q1", {}, { url: "https://x.org/consent", fields: {}, required: [] })).steps;

    expect(step).toMatchObject({ question: { url: "https://x.org/consent", fields: {}, required: [] } });
  });

  it("does not take a fields entry that is not a schema for one", () => {
    const [step] = turnOf(question("q1", {}, { fields: { n: 4, m: null, k: { type: "string" } } })).steps;

    expect(step).toMatchObject({ question: { fields: { n: {}, m: {}, k: { type: "string" } } } });
  });

  it("takes a connection that was waiting for the researcher to sign in as not made when the turn ends", () => {
    const [step] = turnOf(connection("connecting"), connection("signing_in", {}, { url: "https://sign.in/x" }), event("stopped", 1, { text: "Stopped." })).steps;

    expect(step).toMatchObject({ connection: { state: "failed", text: "Not connected: the turn ended before it was." } });
  });

  it("takes a state it does not know to be the first of its kind: waiting for a request, connecting for a server", () => {
    const [connecting] = turnOf(connection("mystery")).steps;
    const [approving] = turnOf(asking("r1"), approval("r1", "mystery")).steps;
    const [questioning] = turnOf(question("q1"), ended("q1", "mystery")).steps;

    expect(connecting).toMatchObject({ connection: { state: "connecting" } });
    expect(approving).toMatchObject({ approval: { state: "waiting" } });
    expect(questioning).toMatchObject({ question: { state: "waiting" } });
  });

  it("calls a server by its name when it gave no title", () => {
    const [connecting] = turnOf(connection("connecting", {}, { title: undefined })).steps;
    const [approving] = turnOf(asking("r1", { title: undefined })).steps;
    const [questioning] = turnOf(question("q1", {}, { title: undefined })).steps;

    expect(connecting).toMatchObject({ connection: { title: "lit" } });
    expect(approving).toMatchObject({ approval: { title: "lit" } });
    expect(questioning).toMatchObject({ question: { title: "lit" } });
  });

  it("withdraws what still waits when the turn ends, however it ends", () => {
    for (const end of ["answer", "stopped", "failed"] as const) {
      const steps = turnOf(asking("r1"), question("q1"), asking("r2"), approval("r2", "approved"), event(end, 1, { text: "Over." })).steps;

      expect(steps.map((step) => (step.kind === "approval" ? step.approval.state : step.kind === "question" ? step.question.state : null))).toEqual([
        "withdrawn",
        "withdrawn",
        "approved",
      ]);
    }
  });

  it("counts what waits for the researcher in the turns that are going on", () => {
    const read = (...events: ChatEvent[]) => waitingOnYou(play(...events).turns);

    expect(read()).toBe(0);
    expect(read(asking("r1"), question("q1"))).toBe(2);
    expect(read(asking("r1"), question("q1"), approval("r1", "approved"))).toBe(1);
    expect(read(asking("r1"), question("q1"), event("stopped", 1, { text: "Stopped." }))).toBe(0);
  });

  it("counts a sign-in that is waited for, until it is made, and not a connection that is only being made", () => {
    const read = (...events: ChatEvent[]) => waitingOnYou(play(...events).turns);

    expect(read(connection("connecting"))).toBe(0);
    expect(read(connection("connecting"), connection("signing_in", {}, { url: "https://x.org/in" }))).toBe(1);
    expect(read(connection("connecting"), connection("signing_in"), connection("ready"))).toBe(0);
    expect(read(connection("connecting"), connection("signing_in"), connection("failed"))).toBe(0);
    expect(read(connection("connecting"), connection("signing_in"), asking("r1"))).toBe(2);
  });

  it("makes nothing of what happens outside a turn", () => {
    const outside = [event("connection", 0, { data: { server: "lit", state: "connecting" } }), { ...asking("r1"), turn: 0 }];

    expect(replay(outside.map((one, at) => ({ ...one, id: at + 1 }))).turns).toEqual([]);
  });

  it("is not changed by an event it has read", () => {
    const events = [event("user", 1), asking("r1"), approval("r1", "approved")].map((one, at) => ({ ...one, id: at + 1 }));
    const once = replay(events);

    expect(replay(events, once)).toBe(once);
  });
});
