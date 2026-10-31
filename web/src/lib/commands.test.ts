import { describe, expect, it } from "vitest";
import {
  commandsFor,
  isDirective,
  rowsFor,
  takesText,
  typedCommand,
  unavailableWhy,
  unmetNote,
  written,
  COMMANDS,
  type Surroundings,
} from "./commands";

const IDLE: Surroundings = { place: "chat", state: "idle", turns: 2, answered: 2, holdUp: null, directives: {} };
const WORKING: Surroundings = { ...IDLE, state: "running" };
const HOME: Surroundings = { place: "home", state: "idle", turns: 0, answered: 0, holdUp: null, directives: null };

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
    expect(typedCommand("/review now", "home")).toEqual({ kind: "none" });
  });

  it("can be several lines for a command that goes with a message, and not for any other", () => {
    expect(typedCommand("/ask What is\na nanobody?", "chat")).toMatchObject({ kind: "arguing", rest: "What is\na nanobody?" });
    expect(typedCommand("/rename A\nB", "chat")).toEqual({ kind: "none" });
  });
});

describe("where a command is offered", () => {
  it("has the conversation's commands in it, and a few on the page where one begins", () => {
    expect(commandsFor("home").map((each) => each.name)).toEqual(["ask", "plan", "search", "code", "plot", "budget", "model", "help"]);
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

    const commands = ["/budget", "/rename", "/export", "/files", "/new", "/pause", "/stop", "/help"];
    // While the lead works, a command that goes with a message waits for it to finish
    const waiting = ["/ask", "/plan", "/search", "/code", "/plot", "/review", "/model", "/resume"];

    expect(names.slice(0, 8)).toEqual(commands);
    expect(names.slice(8)).toEqual(waiting);
    expect(rows.slice(0, 8).every((row) => row.reason === null)).toBe(true);
    expect(rows.slice(8).every((row) => row.reason !== null)).toBe(true);
  });

  it("lists only the page's commands where a conversation is not begun", () => {
    expect(rowsFor("/", HOME).map((row) => row.label)).toEqual(["/ask", "/plan", "/search", "/code", "/plot", "/budget", "/model", "/help"]);
  });

  it("narrows to the names that begin with what is typed, then those that have it", () => {
    expect(rowsFor("/re", IDLE).map((row) => row.label)).toEqual(["/review", "/rename", "/resume"]);
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

describe("the commands that go with a message", () => {
  const WRITES = ["ask", "plan", "search", "code", "plot"];

  it("are the six that say how the lead is to answer, and take words but for review", () => {
    expect(COMMANDS.filter((each) => isDirective(each.name)).map((each) => each.name)).toEqual([...WRITES, "review"]);
    expect(WRITES.every(takesText)).toBe(true);
    expect(takesText("review")).toBe(false);
    expect(takesText("budget")).toBe(false);
    expect(isDirective("budget")).toBe(false);
  });

  it("are given when the lead has finished, and not while it works", () => {
    for (const name of [...WRITES, "review"]) {
      expect(unavailableWhy(command(name), IDLE)).toBeNull();
      expect(unavailableWhy(command(name), WORKING)).toMatch(/finished/);
      expect(unavailableWhy(command(name), { ...IDLE, state: "paused" })).toMatch(/finished/);
    }
  });

  it("wait for a file that is still going", () => {
    expect(unavailableWhy(command("ask"), { ...IDLE, holdUp: "A file is still going" })).toBe("A file is still going");
  });

  it("give the reason the conversation has for not being given one, as a sentence", () => {
    const surroundings = { ...IDLE, directives: { code: "nothing can run code in this conversation", search: null } };

    expect(unavailableWhy(command("code"), surroundings)).toBe("Nothing can run code in this conversation");
    expect(unavailableWhy(command("search"), surroundings)).toBeNull();
    expect(unavailableWhy(command("plot"), surroundings)).toBeNull();
    expect(unavailableWhy(command("code"), HOME)).toBeNull();
  });

  it("have review wait for an answer to review", () => {
    expect(unavailableWhy(command("review"), { ...IDLE, answered: 0 })).toBe("There is no answer to review yet");
    expect(unavailableWhy(command("review"), { ...IDLE, answered: 1, turns: 3 })).toBeNull();
  });

  it("are sent with the words written after them, trimmed, and wait for there to be some", () => {
    expect(rowsFor("/ask", IDLE)[0].action).toEqual({ fill: "/ask " });
    expect(rowsFor("/ask ", IDLE)[0]).toMatchObject({ reason: "Type your question" });
    expect(rowsFor("/ask  What is a nanobody?  ", IDLE)[0]).toMatchObject({
      reason: null,
      action: { run: { name: "ask", arg: "What is a nanobody?" } },
    });
    expect(rowsFor("/code a\nb", IDLE)[0].action).toEqual({ run: { name: "code", arg: "a\nb" } });
  });

  it("run review as soon as it is chosen, since it has nothing to be finished", () => {
    expect(rowsFor("/review", IDLE)[0].action).toEqual({ run: { name: "review", arg: "" } });
    expect(rowsFor("/review ", IDLE)).toHaveLength(1);
    expect(rowsFor("/review the statistics", IDLE)).toEqual([]);
  });

  it("are written out again as they were when they could not be sent", () => {
    expect(written({ name: "ask", arg: "Why?" })).toBe("/ask Why?");
    expect(written({ name: "review", arg: "" })).toBe("/review");
  });

  it("say when the lead did not do what they asked, for those that ask for something that is checked", () => {
    expect(unmetNote("code")).toMatch(/\/code/);
    expect(unmetNote("plot")).toMatch(/figure/);
    expect(unmetNote("search")).toMatch(/literature/);
    expect(unmetNote("review")).toMatch(/Critic/);
    expect(unmetNote("ask")).toBeNull();
    expect(unmetNote("plan")).toBeNull();
    expect(unmetNote("nothing")).toBeNull();
  });
});
