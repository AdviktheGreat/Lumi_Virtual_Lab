import { describe, expect, it } from "vitest";
import { inRounds, initialsOf, listedCalls, reduceLab, roundName, settleLab, SPEAKER_TONES, speakerTone, speaking, writeLab, type LabSession } from "./lab";
import type { ChatEvent } from "./types";

let next = 0;

// An event of a team session as the conversation tells of it
function lab(kind: string, fields: { speaker?: string | null; text?: string; round?: number | null; details?: Record<string, unknown> } = {}): ChatEvent {
  next += 1;

  return {
    kind: "lab",
    id: next,
    turn: 1,
    speaker: fields.speaker ?? null,
    text: fields.text ?? "",
    data: { call: "call_1", event: kind, meeting: "lab_001", round: fields.round ?? null, details: fields.details ?? {} },
    time: 0,
  };
}

function play(events: ChatEvent[], from: LabSession | null = null): LabSession {
  return events.reduce<LabSession | null>((session, event) => reduceLab(session, event), from) as LabSession;
}

const started = () =>
  lab("started", {
    details: {
      meeting_type: "team",
      agenda: "Design a nanobody.",
      agenda_questions: ["Which epitope?", 4],
      num_rounds: 1,
      team: [{ title: "Principal Investigator" }, { title: "Immunologist" }, { name: "no title" }],
    },
  });

const CELL = { language: "python", code: "print(6 * 7)", status: "ok", output: "42\n", duration: 0.5, plots: ["plots/figure_1.png"] };

describe("a team session", () => {
  it("begins with what the meeting says of itself", () => {
    next = 0;

    const session = play([started()]);

    expect(session).toEqual({
      meeting: "lab_001",
      type: "team",
      agenda: "Design a nanobody.",
      questions: ["Which epitope?"],
      rounds: 1,
      team: ["Principal Investigator", "Immunologist"],
      turns: [],
      writing: null,
      status: "running",
      summary: "",
      error: null,
    });
  });

  it("is made of what an event says when it was not told of from its start, and of nothing a server of another version sends", () => {
    next = 0;

    const session = play([lab("turn", { speaker: "Immunologist", round: 1 }), lab("mystery", { text: "?" })]);

    expect(session).toMatchObject({ meeting: "lab_001", type: null, agenda: "", rounds: null, team: [], status: "running" });
    expect(session.turns).toHaveLength(1);
    expect(play([lab("started", { details: { num_rounds: "two", meeting_type: "" } })])).toMatchObject({ type: null, rounds: null });
  });

  it("makes the turn that a reply belongs to, with who said it and in which round, when it was not told of the turn", () => {
    next = 0;

    const session = play([lab("message", { speaker: "Immunologist", text: "I would.", round: 2, details: { kind: "response" } })]);

    expect(session.turns).toEqual([
      { key: expect.any(String), speaker: "Immunologist", round: 2, steps: [{ kind: "reply", key: expect.any(String), text: "I would." }] },
    ]);
  });

  it("has no round for a turn whose round is not a number that there is", () => {
    next = 0;

    const session = play([
      lab("turn", { speaker: "A", round: Infinity }),
      lab("turn", { speaker: "B", round: NaN }),
      lab("turn", { speaker: "C", round: 2 }),
    ]);

    expect(session.turns.map((turn) => turn.round)).toEqual([null, null, 2]);
  });

  it("is a turn for each scientist who spoke, with what they said and did in the order they did it", () => {
    next = 0;

    const session = play([
      started(),
      lab("turn", { speaker: "Principal Investigator", round: 1, details: { name: "Principal_Investigator" } }),
      lab("message", { speaker: "Principal Investigator", text: "Let us begin.", round: 1, details: { kind: "response", index: 2 } }),
      lab("turn", { speaker: "Immunologist", round: 1 }),
      lab("tool_calls", {
        speaker: "Immunologist",
        text: "Looking it up.",
        round: 1,
        details: { calls: [{ id: "c1", name: "search", arguments: '{"q":"TP53"}' }, { name: "other" }] },
      }),
      lab("message", { speaker: "Tool", text: "Found it.", round: 1, details: { kind: "tool_output" } }),
      lab("message", { speaker: "Immunologist", text: "I would target the epitope.", round: 1, details: { kind: "response" } }),
    ]);

    expect(session.turns.map((turn) => [turn.speaker, turn.round, turn.steps.map((step) => step.kind)])).toEqual([
      ["Principal Investigator", 1, ["reply"]],
      ["Immunologist", 1, ["tools", "reply"]],
    ]);
    expect(session.turns[0].steps[0]).toMatchObject({ kind: "reply", text: "Let us begin." });
    expect(session.turns[1].steps[0]).toEqual({
      kind: "tools",
      key: expect.any(String),
      said: "Looking it up.",
      calls: [
        { id: "c1", name: "search", arguments: '{"q":"TP53"}' },
        { id: "call-1", name: "other", arguments: "" },
      ],
      output: "Found it.",
    });
  });

  it("names a turn by its speaker, even where the event does not say who it is", () => {
    next = 0;

    const session = play([lab("turn", { details: { name: "Principal_Investigator" } })]);

    expect(session.turns[0].speaker).toBe("Principal_Investigator");
  });

  it("shows the run of code that a tool made, once, rather than also what the tool gave back", () => {
    next = 0;

    const session = play([
      lab("turn", { speaker: "Immunologist", round: 1 }),
      lab("tool_calls", { details: { calls: [{ id: "c1", name: "run_code", arguments: "{}" }] } }),
      lab("cell", { details: CELL }),
      lab("message", { text: "The code ran.", details: { kind: "tool_output" } }),
    ]);

    const [tools, cell] = session.turns[0].steps;
    expect(tools).toMatchObject({ kind: "tools", output: null });
    expect(cell).toMatchObject({ kind: "cell", cell: { code: "print(6 * 7)", output: "42\n", plots: ["plots/figure_1.png"] } });
    expect(session.turns[0].steps).toHaveLength(2);
  });

  it("gives what a tool returned to the call that has not had an answer", () => {
    next = 0;

    const session = play([
      lab("turn", { speaker: "Immunologist", round: 1 }),
      lab("tool_calls", { details: { calls: [{ id: "c1", name: "search", arguments: "{}" }] } }),
      lab("message", { text: "First result.", details: { kind: "tool_output" } }),
      lab("tool_calls", { details: { calls: [{ id: "c2", name: "search", arguments: "{}" }] } }),
      lab("message", { text: "Second result.", details: { kind: "tool_output" } }),
      lab("message", { text: "Nobody asked for this.", details: { kind: "tool_output" } }),
    ]);

    expect(session.turns[0].steps.map((step) => step.kind === "tools" && step.output)).toEqual(["First result.", "Second result."]);
  });

  it("gives what a tool returned to the last call that has not had an answer, which is not one that code answered", () => {
    next = 0;

    const session = play([
      lab("turn", { speaker: "Immunologist", round: 1 }),
      lab("tool_calls", { details: { calls: [{ id: "c1", name: "run_code", arguments: "{}" }] } }),
      lab("cell", { details: CELL }),
      lab("message", { text: "The code ran.", details: { kind: "tool_output" } }),
      lab("tool_calls", { details: { calls: [{ id: "c2", name: "search", arguments: "{}" }] } }),
      lab("message", { text: "Found it.", details: { kind: "tool_output" } }),
    ]);

    expect(session.turns[0].steps.map((step) => step.kind === "tools" && step.output)).toEqual([null, false, "Found it."]);
  });

  it("gives what a call to run code returned when no code ran for it, though code ran after", () => {
    next = 0;

    const session = play([
      lab("turn", { speaker: "Immunologist", round: 1 }),
      lab("tool_calls", { details: { calls: [{ id: "c1", name: "run_code", arguments: "{}" }] } }),
      lab("message", { text: "There is no session to run it in.", details: { kind: "tool_output" } }),
      lab("code", { details: { code: "x = 1" } }),
      lab("cell", { details: CELL }),
    ]);

    expect(session.turns[0].steps.map((step) => step.kind)).toEqual(["tools", "code"]);
    expect(session.turns[0].steps[0]).toMatchObject({ output: "There is no session to run it in." });
  });

  it("puts the run of code a scientist wrote into the code, and a run with no code before it on its own", () => {
    next = 0;

    const session = play([
      lab("turn", { speaker: "Immunologist", round: 1 }),
      lab("code", { text: "I will run this.", details: { code: "x = 1", language: "python" } }),
      lab("cell", { details: { ...CELL, code: "x = 1" } }),
      lab("cell", { details: CELL }),
    ]);

    const [written, alone] = session.turns[0].steps;
    expect(written).toMatchObject({ kind: "code", said: "I will run this.", code: "x = 1", language: "python", cell: { code: "x = 1", status: "ok" } });
    expect(alone).toMatchObject({ kind: "cell", cell: { code: "print(6 * 7)" } });
  });

  it("holds code that has not run yet, as it was written", () => {
    next = 0;

    const session = play([lab("turn", { speaker: "Immunologist" }), lab("code", { details: { code: "x = 1" } })]);

    expect(session.turns[0].steps).toEqual([{ kind: "code", key: expect.any(String), said: "", code: "x = 1", language: "python", cell: null }]);
  });

  it("leaves out what the conversation already shows, or shows as the run that it is", () => {
    next = 0;

    const session = play([
      lab("turn", { speaker: "Immunologist" }),
      lab("message", { speaker: "Human researcher", text: "A note.", details: { kind: "note" } }),
      lab("message", { text: "```python\nx\n```", details: { kind: "code_action" } }),
      lab("message", { text: "observation", details: { kind: "code_output" } }),
      lab("message", { text: "{}", details: { kind: "structured_output" } }),
      lab("message", { text: "Unknown kind", details: { kind: "from the future" } }),
      lab("message", { text: "No kind" }),
    ]);

    expect(session.turns[0].steps).toEqual([]);
  });

  it("is writing until the reply is there, which replaces what was written", () => {
    next = 0;
    const writing = (text: string, speaker: string | null = "Immunologist") =>
      ({ kind: "writing", id: ++next, turn: 1, speaker, text, data: { call: "call_1", meeting: "lab_001", request: 1 }, time: 0 }) as ChatEvent;

    let session = play([started(), lab("turn", { speaker: "Immunologist", round: 1 })]);
    session = writeLab(session, writing("I would"));
    session = writeLab(session, writing("I would target"));

    expect(session.writing).toEqual({ speaker: "Immunologist", text: "I would target" });
    expect(speaking(session)).toEqual({ speaker: "Immunologist", round: 1 });

    expect(reduceLab(session, lab("message", { text: "I would target it.", details: { kind: "response" } })).writing).toBeNull();
    expect(reduceLab(session, lab("turn", { speaker: "Scientific Critic", round: 1 })).writing).toBeNull();
    expect(reduceLab(session, lab("finished", { text: "Done." })).writing).toBeNull();
    expect(reduceLab(session, lab("failed", { text: "Broke." })).writing).toBeNull();
    // Nothing is written in a session that has ended, as the stream may be late to say
    expect(writeLab(reduceLab(session, lab("finished", { text: "Done." })), writing("late")).writing).toBeNull();
  });

  it("ends with the summary, or with the error that ended it", () => {
    next = 0;
    const turns = [lab("turn", { speaker: "Principal Investigator", round: 2 })];

    const finished = play([...turns, lab("finished", { text: "The summary.", details: { elapsed_time: 3 } })]);
    const failed = play([...turns, lab("failed", { text: "The model went away.", details: { type: "RuntimeError" } })]);

    expect(finished).toMatchObject({ status: "finished", summary: "The summary.", error: null });
    expect(failed).toMatchObject({ status: "failed", error: "The model went away.", summary: "" });
    expect(speaking(finished)).toBeNull();
    expect(speaking(failed)).toBeNull();
    // Nobody has the turn before the first turn is taken
    expect(speaking(play([started()]))).toBeNull();
  });

  it("is cut short, and did not fail, when the researcher stopped it", () => {
    next = 0;
    const writing = writeLab(play([lab("turn", { speaker: "Immunologist", round: 1 })]), writeLabEvent());
    expect(writing.writing).not.toBeNull();

    const stopped = reduceLab(writing, lab("failed", { text: "Stopped by the researcher", details: { type: "ChatStopped" } }));

    expect(stopped).toMatchObject({ status: "interrupted", error: null, writing: null, summary: "" });
    expect(speaking(stopped)).toBeNull();
    expect(settleLab(stopped)).toBe(stopped);
  });

  it("is cut short, if it was going on when the turn ended, and otherwise as it was", () => {
    next = 0;
    const going = writeLab(play([started(), lab("turn", { speaker: "Immunologist" })]), writeLabEvent());
    const done = play([started(), lab("finished", { text: "Done." })]);

    expect(going.writing).not.toBeNull();
    expect(settleLab(going)).toMatchObject({ status: "interrupted", writing: null });
    expect(settleLab(done)).toBe(done);
    expect(settleLab(play([lab("failed", { text: "No." })])).status).toBe("failed");
  });
});

function writeLabEvent(): ChatEvent {
  return { kind: "writing", id: 999, turn: 1, speaker: "Immunologist", text: "I wo", data: { call: "call_1", meeting: "lab_001" }, time: 0 };
}

describe("the name of a round", () => {
  it("is its number, and for the last of a discussion what is done in it", () => {
    expect(roundName(null, { rounds: 1, type: "team" })).toBeNull();
    expect(roundName(1, { rounds: 1, type: "team" })).toBe("Round 1");
    expect(roundName(2, { rounds: 1, type: "team" })).toBe("Summary");
    expect(roundName(2, { rounds: 1, type: "individual" })).toBe("Final answer");
    expect(roundName(3, { rounds: 1, type: "team" })).toBe("Round 3");
    expect(roundName(2, { rounds: null, type: "team" })).toBe("Round 2");
  });
});

describe("what is listed of a turn", () => {
  const turnOf = (...events: ChatEvent[]) => {
    next = 0;

    return play([lab("turn", { speaker: "Immunologist", round: 1 }), ...events]).turns[0];
  };
  const calls = (...names: string[]) =>
    lab("tool_calls", { details: { calls: names.map((name, at) => ({ id: `c${at}`, name, arguments: "{}" })) } });
  const cell = () => lab("cell", { details: { language: "python", code: "1", status: "ok" } });

  it("is every tool called, until code has run", () => {
    const turn = turnOf(calls("find_resources", "run_code"));

    expect(listedCalls(turn, 0).map((call) => call.name)).toEqual(["find_resources", "run_code"]);
  });

  it("leaves out a call to run code once a run is there to show it, and keeps the rest", () => {
    const turn = turnOf(calls("find_resources", "run_code"), cell());

    expect(listedCalls(turn, 0).map((call) => call.name)).toEqual(["find_resources"]);
  });

  it("keeps a call to run code that no run came of, though code ran after", () => {
    const turn = turnOf(calls("run_code"), lab("code", { details: { code: "x = 1" } }), cell());

    expect(listedCalls(turn, 0).map((call) => call.name)).toEqual(["run_code"]);
  });

  it("keeps a call to run code that no run came of, though a later call made one", () => {
    const turn = turnOf(calls("run_code"), calls("run_code"), cell());

    expect(listedCalls(turn, 0).map((call) => call.name)).toEqual(["run_code"]);
    expect(listedCalls(turn, 1)).toEqual([]);
  });

  it("does not take a run from before the call for its run", () => {
    const turn = turnOf(cell(), calls("run_code"));

    expect(listedCalls(turn, 1).map((call) => call.name)).toEqual(["run_code"]);
  });

  it("is nothing for a step that is not of tools, or is not there", () => {
    const turn = turnOf(lab("message", { text: "Hi.", details: { kind: "response" } }));

    expect(listedCalls(turn, 0)).toEqual([]);
    expect(listedCalls(turn, 5)).toEqual([]);
  });
});

describe("rounds", () => {
  const turn = (speaker: string, round: number | null) => ({ key: `${speaker}${round}`, speaker, round, steps: [] });

  it("hold the turns that were in them, in order, and a round that comes again is a round of its own", () => {
    const rounds = inRounds([turn("A", 1), turn("B", 1), turn("A", 2), turn("B", null), turn("C", null), turn("A", 1)]);

    expect(rounds.map((round) => [round.round, round.turns.map((each) => each.speaker)])).toEqual([
      [1, ["A", "B"]],
      [2, ["A"]],
      [null, ["B", "C"]],
      [1, ["A"]],
    ]);
  });

  it("are none where there were no turns", () => {
    expect(inRounds([])).toEqual([]);
  });
});

describe("how a scientist is marked", () => {
  it("is by two letters, or one for a name of one word", () => {
    expect(initialsOf("Scientific Critic")).toBe("SC");
    expect(initialsOf("Principal Investigator")).toBe("PI");
    expect(initialsOf("Immunologist")).toBe("I");
    expect(initialsOf("structural-biologist")).toBe("SB");
    expect(initialsOf("Computational  Systems Biologist")).toBe("CB");
    expect(initialsOf("  ")).toBe("?");
    expect(initialsOf("")).toBe("?");
  });

  it("is by a colour that is the same for a name each time, whatever its case, and is one that there is", () => {
    const names = ["Immunologist", "Scientific Critic", "Principal Investigator", "Bioinformatician", "Chemist", "x"];

    for (const name of names) {
      expect(speakerTone(name)).toBe(speakerTone(name.toUpperCase()));
      expect(speakerTone(name)).toBeGreaterThanOrEqual(0);
      expect(speakerTone(name)).toBeLessThan(SPEAKER_TONES);
    }
    expect(new Set(names.map(speakerTone)).size).toBeGreaterThan(2);
    // The lead, a scientist, and the critic, who are in most sessions, are told apart
    expect(new Set(["Principal Investigator", "Immunologist", "Scientific Critic"].map(speakerTone)).size).toBe(3);
    expect(speakerTone("")).toBe(0);
  });
});
