import { afterEach, describe, expect, it, vi } from "vitest";
import {
  checkLab,
  choosable,
  describeChoice,
  initialDraft,
  joining,
  labChoiceOf,
  questionsOf,
  remember,
  remembered,
  reseated,
  seatsOf,
  withMember,
  withMode,
  type LabDraft,
} from "./team-choice";
import type { LibraryScientist, PaperSeat } from "./types";

const scientist = (title: string, builtin = true): LibraryScientist => ({ title, expertise: `${title} things`, goal: "g", role: "r", builtin });
const LIBRARY = ["Principal Investigator", "Scientific Critic", "Immunologist", "Geneticist"].map((title) => scientist(title));

const SEATS: PaperSeat[] = [{ id: "cell-1", title: "CellMapper", seat: "PaperAgent: CellMapper" }];

const DRAFT: LabDraft = { mode: "team", agenda: "Design a binder", members: ["Immunologist"], rounds: "1", questions: "" };

afterEach(() => vi.unstubAllGlobals());

describe("who is chosen, as a message says it", () => {
  it("is read when it is as the server writes it", () => {
    const lab = { mode: "individual", members: ["Immunologist"], rounds: 0, questions: ["Where?"] };

    expect(labChoiceOf(lab)).toEqual(lab);
    expect(labChoiceOf({ ...lab, questions: undefined })).toEqual({ ...lab, questions: [] });
  });

  it.each([
    null,
    "team",
    {},
    { mode: "crowd", members: ["A"], rounds: 1 },
    { mode: "team", members: [], rounds: 1 },
    { mode: "team", members: ["A", 3], rounds: 1 },
    { mode: "team", members: "A", rounds: 1 },
    { mode: "team", members: ["A"], rounds: -1 },
    { mode: "team", members: ["A"], rounds: 1.5 },
    { mode: "team", members: ["A"], rounds: "1" },
  ])("is not read when it is not, as in %j", (data) => {
    expect(labChoiceOf(data)).toBeNull();
  });

  it("is told in a few words", () => {
    expect(describeChoice({ mode: "team", members: ["Immunologist", "Geneticist"], rounds: 2, questions: [] })).toBe(
      "Immunologist, Geneticist · 2 rounds",
    );
    expect(describeChoice({ mode: "individual", members: ["Immunologist"], rounds: 1, questions: [] })).toBe(
      "Immunologist, with the Critic reviewing · 1 round",
    );
    expect(describeChoice({ mode: "team", members: ["Immunologist"], rounds: 0, questions: [] })).toBe("Immunologist · 0 rounds");
  });
});

describe("who can be chosen", () => {
  it("is all the library but the lead, and, for one who works alone, the Critic", () => {
    expect(choosable(LIBRARY, "Principal Investigator", "team").map((each) => each.title)).toEqual([
      "Scientific Critic",
      "Immunologist",
      "Geneticist",
    ]);
    expect(choosable(LIBRARY, "principal  investigator", "individual").map((each) => each.title)).toEqual(["Immunologist", "Geneticist"]);
  });

  it("has, before the library, those who speak for the papers, with what they speak for, once each, and not the lead", () => {
    const found = choosable([...LIBRARY, scientist("Mine", false)], "Principal Investigator", "individual", [
      ...SEATS,
      { id: "cell-2", title: "Copy", seat: "paperagent:  cellmapper" },
      { id: "lead", title: "Lead", seat: "Principal Investigator" },
    ]);

    expect(found.map((each) => [each.title, each.kind])).toEqual([
      ["PaperAgent: CellMapper", "paper"],
      ["Immunologist", "builtin"],
      ["Geneticist", "builtin"],
      ["Mine", "yours"],
    ]);
    expect(found[1].about).toBe("Immunologist things");
    expect(found[0].about).toBe("Speaks for the paper “CellMapper”, from what was read of it and its tools");
    // One of the library who has the title of a seat is the seat, as the conversation's team has it
    expect(choosable([scientist("paperagent: cellmapper", false), scientist("Geneticist")], "Principal Investigator", "team", SEATS)).toEqual([
      { title: "PaperAgent: CellMapper", about: "Speaks for the paper “CellMapper”, from what was read of it and its tools", kind: "paper" },
      { title: "Geneticist", about: "Geneticist things", kind: "builtin" },
    ]);
  });

  it("joins the team when they are not on it, however their titles are spelled", () => {
    expect(joining(["Immunologist", "Geneticist"], ["immunologist", "Scientific Critic"])).toEqual(["Geneticist"]);
    expect(joining(["Immunologist"], ["Immunologist"])).toEqual([]);
  });
});

describe("the panel's draft", () => {
  it("has questions one to a line, without the empty ones", () => {
    expect(questionsOf("  Which epitope? \n\n How   stable?\n")).toEqual(["Which epitope?", "How stable?"]);
    expect(questionsOf("")).toEqual([]);
  });

  it("is a choice when nothing is wrong with it", () => {
    expect(checkLab({ ...DRAFT, questions: "Where?\nWhy?" }, 3)).toEqual({
      choice: { mode: "team", members: ["Immunologist"], rounds: 1, questions: ["Where?", "Why?"] },
      problems: {},
    });
  });

  it("says what is missing or wrong, and gives no choice", () => {
    const { choice, problems } = checkLab({ ...DRAFT, agenda: "  ", members: [], rounds: "4", questions: "q\n".repeat(11) }, 3);

    expect(choice).toBeNull();
    expect(problems.agenda).toMatch(/what they are to work on/);
    expect(problems.members).toMatch(/at least one/);
    expect(problems.rounds).toMatch(/0 to 3/);
    expect(problems.questions).toMatch(/at most 10/);
    expect(checkLab({ ...DRAFT, rounds: "one" }, 3).problems.rounds).toMatch(/whole number/);
    expect(checkLab({ ...DRAFT, rounds: "-1" }, 3).problems.rounds).toMatch(/whole number/);
    expect(checkLab({ ...DRAFT, rounds: "" }, 3).choice).toBeNull();
    expect(checkLab({ ...DRAFT, questions: "x".repeat(2001) }, 3).problems.questions).toMatch(/2000/);
  });

  it("has exactly one scientist where one works alone", () => {
    const alone: LabDraft = { ...DRAFT, mode: "individual" };

    expect(checkLab({ ...alone, members: ["Immunologist", "Geneticist"] }, 3).problems.members).toMatch(/the one scientist/);
    expect(checkLab({ ...alone, members: [] }, 3).problems.members).toMatch(/the one scientist/);
    expect(checkLab(alone, 3).choice).toMatchObject({ mode: "individual", members: ["Immunologist"] });
  });

  it("keeps who is chosen when the mode changes, but for what the new mode cannot have", () => {
    const team: LabDraft = { ...DRAFT, members: ["Scientific Critic", "Immunologist", "Geneticist"] };

    expect(withMode(team, "individual").members).toEqual(["Immunologist"]);
    expect(withMode({ ...team, mode: "individual", members: ["Geneticist"] }, "team").members).toEqual(["Geneticist"]);
    expect(withMode(team, "team")).toBe(team);
  });

  it("chooses one more where there is a team, and another in place of the first where one works alone", () => {
    expect(withMember(DRAFT, "Geneticist", true).members).toEqual(["Immunologist", "Geneticist"]);
    expect(withMember(DRAFT, "immunologist", false).members).toEqual([]);
    expect(withMember({ ...DRAFT, mode: "individual" }, "Geneticist", true).members).toEqual(["Geneticist"]);
  });
});

describe("the seats of the agents of a conversation that has not begun", () => {
  it("are those the list says, told apart by the end of the id where two would be the same or one would be the lead", () => {
    expect(
      seatsOf(
        [
          { id: "a-111111", title: "Cell", seat: "PaperAgent: Cell" },
          { id: "b-222222", title: "cell", seat: "PaperAgent: cell" },
          { id: "c-333333", title: "Old", seat: undefined },
          { id: "d-444444", title: "Lead", seat: "Principal Investigator" },
        ],
        "Principal Investigator",
      ),
    ).toEqual([
      { id: "a-111111", title: "Cell", seat: "PaperAgent: Cell" },
      { id: "b-222222", title: "cell", seat: "PaperAgent: cell (222222)" },
      { id: "d-444444", title: "Lead", seat: "Principal Investigator (444444)" },
    ]);
  });

  it("are named in a choice by the seats that the conversation gives them once it has begun", () => {
    const planned = [...SEATS, { id: "cell-2", title: "Other", seat: "PaperAgent: Other" }];
    const seated = [{ ...SEATS[0], seat: "PaperAgent: CellMapper (cell-1)" }];
    const choice = { mode: "team" as const, members: ["Immunologist", "paperagent: cellmapper", "PaperAgent: Other"], rounds: 1, questions: [] };

    expect(reseated(choice, planned, seated)).toEqual({ ...choice, members: ["Immunologist", "PaperAgent: CellMapper (cell-1)", "PaperAgent: Other"] });
  });

  it("are named by the agent and not the place, where the server told two of the same title apart the other way round", () => {
    const planned = [
      { id: "a-aaaaaa", title: "X", seat: "PaperAgent: X" },
      { id: "b-bbbbbb", title: "X", seat: "PaperAgent: X (bbbbbb)" },
    ];
    const seated = [
      { id: "b-bbbbbb", title: "X", seat: "PaperAgent: X" },
      { id: "a-aaaaaa", title: "X", seat: "PaperAgent: X (aaaaaa)" },
    ];
    const choice = { mode: "team" as const, members: ["PaperAgent: X (bbbbbb)"], rounds: 1, questions: [] };

    expect(reseated(choice, planned, seated).members).toEqual(["PaperAgent: X"]);
    expect(reseated({ ...choice, members: ["PaperAgent: X", "PaperAgent: X (bbbbbb)"] }, planned, seated).members).toEqual([
      "PaperAgent: X (aaaaaa)",
      "PaperAgent: X",
    ]);
  });
});

describe("what is kept for the next time", () => {
  function stub() {
    const kept = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => kept.get(key) ?? null,
      setItem: (key: string, value: string) => void kept.set(key, value),
    });

    return kept;
  }

  it("is who, and how, and not what they were to work on or what they were asked", () => {
    const kept = stub();

    remember({ mode: "team", members: ["Immunologist"], rounds: 2, questions: ["Secret?"] });

    expect(remembered()).toEqual({ mode: "team", members: ["Immunologist"], rounds: 2 });
    expect([...kept.values()].join("")).not.toMatch(/Secret/);
  });

  it("is nothing where nothing was kept, or what was kept cannot be read, or the page may keep nothing", () => {
    stub();
    expect(remembered()).toBeNull();

    vi.stubGlobal("localStorage", { getItem: () => "{not json", setItem: () => undefined });
    expect(remembered()).toBeNull();

    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    });
    expect(remembered()).toBeNull();
    expect(() => remember({ mode: "team", members: ["A"], rounds: 1, questions: [] })).not.toThrow();
  });

  it("opens the panel with the last choice, where those chosen are still there and the rounds are still allowed", () => {
    const kept = { mode: "team" as const, members: ["geneticist", "Gone", "Principal Investigator"], rounds: 5 };

    expect(initialDraft("Design", kept, LIBRARY, "Principal Investigator", 3)).toEqual({
      mode: "team",
      agenda: "Design",
      members: ["Geneticist"],
      rounds: "3",
      questions: "",
    });
    expect(initialDraft("", null, LIBRARY, "Principal Investigator", 3)).toMatchObject({ mode: "team", members: [], rounds: "1" });
    expect(initialDraft("", null, LIBRARY, "Principal Investigator", 0)).toMatchObject({ rounds: "0" });
    expect(
      initialDraft("", { mode: "individual", members: ["Scientific Critic", "Geneticist"], rounds: 1 }, LIBRARY, "Principal Investigator", 3).members,
    ).toEqual(["Geneticist"]);
  });

  it("opens with those who are wanted chosen too, or, where one works alone, in place of the one chosen last", () => {
    const kept = { mode: "team" as const, members: ["Geneticist"], rounds: 1 };

    expect(initialDraft("", kept, LIBRARY, "Principal Investigator", 3, SEATS, ["PaperAgent: CellMapper"]).members).toEqual([
      "Geneticist",
      "PaperAgent: CellMapper",
    ]);
    expect(initialDraft("", kept, LIBRARY, "Principal Investigator", 3, SEATS, ["geneticist"]).members).toEqual(["Geneticist"]);
    expect(initialDraft("", { ...kept, mode: "individual" }, LIBRARY, "Principal Investigator", 3, SEATS, ["PaperAgent: CellMapper"]).members).toEqual([
      "PaperAgent: CellMapper",
    ]);
    expect(initialDraft("", { ...kept, mode: "individual" }, LIBRARY, "Principal Investigator", 3, SEATS, ["Gone"]).members).toEqual(["Geneticist"]);
    expect(initialDraft("", null, LIBRARY, "Principal Investigator", 3, [], ["PaperAgent: CellMapper"]).members).toEqual([]);
    expect(initialDraft("", { ...kept, members: ["PaperAgent: CellMapper"] }, LIBRARY, "Principal Investigator", 3).members).toEqual([]);
  });
});
