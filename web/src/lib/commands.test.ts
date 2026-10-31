import { describe, expect, it } from "vitest";
import { commandsFor, rowsFor, typedCommand, unavailableWhy, COMMANDS, type Surroundings } from "./commands";

const IDLE: Surroundings = { place: "chat", state: "idle", turns: 2 };
const WORKING: Surroundings = { place: "chat", state: "running", turns: 2 };
const HOME: Surroundings = { place: "home", state: "idle", turns: 0 };

function command(name: string) {
  const found = COMMANDS.find((candidate) => candidate.name === name);
  if (found === undefined) throw new Error(`no command ${name}`);

  return found;
}

describe("what is typed", () => {
  it("is a command being named while it is a slash and letters", () => {
    expect(typedCommand("/", "chat")).toEqual({ kind: "naming", query: "" });
    expect(typedCommand("/Bu", "chat")).toEqual({ kind: "naming", query: "bu" });
  });

  it("is a command with what it takes once there is a space after a name that is one", () => {
    expect(typedCommand("/rename A new title", "chat")).toEqual({ kind: "arguing", command: command("rename"), rest: "A new title" });
    expect(typedCommand("/export ", "chat")).toMatchObject({ kind: "arguing", rest: "" });
  });

  it("is a message when it is not for a command", () => {
    for (const text of ["", "hello", " /budget", "/data/counts.csv what is in it", "/nonsense text", "/budget\nmore", "see /budget"]) {
      expect(typedCommand(text, "chat")).toEqual({ kind: "none" });
    }
  });

  it("is not a command where the place does not have it", () => {
    expect(typedCommand("/rename Title", "home")).toEqual({ kind: "none" });
  });
});

describe("where a command is offered", () => {
  it("has the conversation's commands in it, and a few on the page where one begins", () => {
    expect(commandsFor("home").map((each) => each.name)).toEqual(["budget", "model", "help"]);
    expect(commandsFor("chat").map((each) => each.name)).toEqual(COMMANDS.map((each) => each.name));
  });
});

describe("whether a command can be run", () => {
  it("lets the budget be changed at any time", () => {
    for (const surroundings of [IDLE, WORKING, HOME, { ...IDLE, state: "paused" as const }]) {
      expect(unavailableWhy(command("budget"), surroundings)).toBeNull();
    }
  });

  it("has the model changed only when the lead is not at work, except where the conversation is not begun", () => {
    expect(unavailableWhy(command("model"), IDLE)).toBeNull();
    expect(unavailableWhy(command("model"), HOME)).toBeNull();
    expect(unavailableWhy(command("model"), WORKING)).toMatch(/finished/);
  });

  it("has a conversation saved only when there is something in it", () => {
    expect(unavailableWhy(command("export"), IDLE)).toBeNull();
    expect(unavailableWhy(command("export"), { ...IDLE, turns: 0 })).toMatch(/nothing to save/);
  });

  it("has pause, resume, and stop for work that is going on", () => {
    expect(unavailableWhy(command("pause"), IDLE)).toMatch(/Nothing is running/);
    expect(unavailableWhy(command("stop"), IDLE)).toMatch(/Nothing is running/);
    expect(unavailableWhy(command("resume"), IDLE)).toMatch(/Nothing is held/);

    expect(unavailableWhy(command("pause"), WORKING)).toBeNull();
    expect(unavailableWhy(command("stop"), WORKING)).toBeNull();
    expect(unavailableWhy(command("resume"), WORKING)).toMatch(/Nothing is held/);

    const paused = { ...WORKING, state: "paused" as const };
    expect(unavailableWhy(command("pause"), paused)).toMatch(/held already/);
    expect(unavailableWhy(command("resume"), paused)).toBeNull();
    expect(unavailableWhy(command("stop"), paused)).toBeNull();

    const stopping = { ...WORKING, state: "stopping" as const };
    expect(unavailableWhy(command("stop"), stopping)).toMatch(/stopping/);
    expect(unavailableWhy(command("pause"), stopping)).toMatch(/stopping/);
  });
});

describe("the menu", () => {
  it("lists every command of the place for a slash alone, those that can be run first", () => {
    const rows = rowsFor("/", WORKING);
    const names = rows.map((row) => row.label);

    expect(names.slice(0, 8)).toEqual(["/budget", "/rename", "/export", "/files", "/new", "/pause", "/stop", "/help"]);
    expect(names.slice(8)).toEqual(["/model", "/resume"]);
    expect(rows.slice(0, 8).every((row) => row.reason === null)).toBe(true);
    expect(rows.slice(8).every((row) => row.reason !== null)).toBe(true);
  });

  it("lists only the page's commands where a conversation is not begun", () => {
    expect(rowsFor("/", HOME).map((row) => row.label)).toEqual(["/budget", "/model", "/help"]);
  });

  it("narrows to the names that begin with what is typed, then those that have it", () => {
    expect(rowsFor("/re", IDLE).map((row) => row.label)).toEqual(["/rename", "/resume"]);
    expect(rowsFor("/ex", IDLE).map((row) => row.label)).toEqual(["/export"]);
    expect(rowsFor("/port", IDLE).map((row) => row.label)).toEqual(["/export"]);
    expect(rowsFor("/zzz", IDLE)).toEqual([]);
  });

  it("runs a command that takes nothing when it is chosen, and has one that takes something finished first", () => {
    expect(rowsFor("/budget", IDLE)[0].action).toEqual({ run: { name: "budget", arg: "" } });
    expect(rowsFor("/export", IDLE)[0].action).toEqual({ fill: "/export " });
    expect(rowsFor("/rename", IDLE)[0].action).toEqual({ fill: "/rename " });
  });

  it("says why a command cannot be chosen", () => {
    expect(rowsFor("/stop", IDLE)[0]).toMatchObject({ reason: "Nothing is running" });
    expect(rowsFor("/model", WORKING)[0].reason).toMatch(/finished/);
  });

  it("offers what a command takes once it is named", () => {
    expect(rowsFor("/export ", IDLE).map((row) => row.label)).toEqual(["/export html", "/export pdf", "/export ipynb"]);
    expect(rowsFor("/export no", IDLE).map((row) => row.label)).toEqual(["/export ipynb"]);
    expect(rowsFor("/export pdf", IDLE)[0].action).toEqual({ run: { name: "export", arg: "pdf" } });
    expect(rowsFor("/export web", IDLE)[0].action).toEqual({ run: { name: "export", arg: "html" } });
  });

  it("holds a command that takes a choice to it", () => {
    const [row] = rowsFor("/export docx", IDLE);

    expect(rowsFor("/export docx", IDLE)).toHaveLength(1);
    expect(row.reason).toBe("Choose html, pdf, ipynb");
  });

  it("takes the words after a command that takes words, trimmed", () => {
    expect(rowsFor("/rename  A better title  ", IDLE)[0]).toMatchObject({
      reason: null,
      action: { run: { name: "rename", arg: "A better title" } },
    });
    expect(rowsFor("/rename ", IDLE)[0].reason).toBe("Type the new title");
  });

  it("is not there for a command that takes nothing, once something is written after it", () => {
    expect(rowsFor("/stop ", WORKING)).toHaveLength(1);
    expect(rowsFor("/stop now", WORKING)).toEqual([]);
  });

  it("is not there for a message", () => {
    expect(rowsFor("tell me about /budget", IDLE)).toEqual([]);
    expect(rowsFor("", IDLE)).toEqual([]);
  });
});
