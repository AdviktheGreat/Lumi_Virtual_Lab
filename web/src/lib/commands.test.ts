import { describe, expect, it } from "vitest";
import {
  commandsFor,
  givenAs,
  isDirective,
  rowsFor,
  takesText,
  typedCommand,
  skillUnmetNote,
  unavailableWhy,
  unmetNote,
  written,
  COMMANDS,
  PROMPT_ROWS,
  SKILL_ROWS,
  type Surroundings,
} from "./commands";
import type { PromptChoice } from "./prompts";

const IDLE: Surroundings = { place: "chat", state: "idle", turns: 2, answered: 2, holdUp: null, directives: {} };
const WORKING: Surroundings = { ...IDLE, state: "running" };
const HOME: Surroundings = { place: "home", state: "idle", turns: 0, answered: 0, holdUp: null, directives: null };

const SKILLS = [
  { name: "dose-response", description: "Fits a dose-response curve." },
  { name: "Plot-Style", description: "Makes figures in the journal's style." },
  { name: "rna-seq", description: "" },
  { name: "ask", description: "A skill that has the name of a command." },
];
const SKILLED: Surroundings = { ...IDLE, skills: SKILLS };

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
    expect(commandsFor("home").map((each) => each.name)).toEqual(["ask", "plan", "search", "code", "plot", "lab", "budget", "model", "skills", "help"]);
    expect(commandsFor("chat").map((each) => each.name)).toEqual(COMMANDS.map((each) => each.name));
  });
});

describe("whether a command can be run", () => {
  it("lets the skills be chosen or looked at at any time, since a conversation that is working does not stop that", () => {
    for (const surroundings of [IDLE, WORKING, HOME, { ...IDLE, state: "paused" as const }]) {
      expect(unavailableWhy(command("skills"), surroundings)).toBeNull();
    }
    expect(rowsFor("/skills", HOME)[0].action).toEqual({ run: { name: "skills", arg: "" } });
    expect(rowsFor("/skills", WORKING)[0].action).toEqual({ run: { name: "skills", arg: "" } });
  });

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

    const commands = ["/budget", "/skills", "/rename", "/export", "/files", "/new", "/pause", "/stop", "/help"];
    // While the lead works, a command that goes with a message waits for it to finish
    const waiting = ["/ask", "/plan", "/search", "/code", "/plot", "/review", "/lab", "/model", "/resume"];

    expect(names.slice(0, 9)).toEqual(commands);
    expect(names.slice(9)).toEqual(waiting);
    expect(rows.slice(0, 9).every((row) => row.reason === null)).toBe(true);
    expect(rows.slice(9).every((row) => row.reason !== null)).toBe(true);
  });

  it("lists only the page's commands where a conversation is not begun", () => {
    expect(rowsFor("/", HOME).map((row) => row.label)).toEqual([
      "/ask",
      "/plan",
      "/search",
      "/code",
      "/plot",
      "/lab",
      "/budget",
      "/model",
      "/skills",
      "/help",
    ]);
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

  it("are the seven that say how the lead is to answer, and take words but for review", () => {
    expect(COMMANDS.filter((each) => isDirective(each.name)).map((each) => each.name)).toEqual([...WRITES, "review", "lab"]);
    expect(WRITES.every(takesText)).toBe(true);
    expect(takesText("lab")).toBe(true);
    expect(takesText("review")).toBe(false);
    expect(takesText("budget")).toBe(false);
    expect(isDirective("budget")).toBe(false);
  });

  it("are given when the lead has finished, and not while it works", () => {
    for (const name of [...WRITES, "review", "lab"]) {
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

  it("have lab ask who works on it in a panel, so that what is to be worked on may be left to it", () => {
    // It is not begun in the box, as the commands that need words are, but is run as soon as it is chosen
    expect(rowsFor("/lab", IDLE)[0].action).toEqual({ run: { name: "lab", arg: "" } });
    expect(rowsFor("/lab ", IDLE)).toMatchObject([{ reason: null, action: { run: { name: "lab", arg: "" } } }]);
    expect(rowsFor("/lab Design a binder", IDLE)[0].action).toEqual({ run: { name: "lab", arg: "Design a binder" } });
    expect(rowsFor("/lab Design\na binder", IDLE)[0].action).toEqual({ run: { name: "lab", arg: "Design\na binder" } });
    // Words that are needed still are for the others
    expect(rowsFor("/ask ", IDLE)[0].reason).toMatch(/Type your question/);
  });

  it("have lab wait on what the server says of the team session", () => {
    const silent = { ...IDLE, directives: { lab: "the lead may not start team sessions" } };

    expect(unavailableWhy(command("lab"), silent)).toBe("The lead may not start team sessions");
    expect(unavailableWhy(command("lab"), HOME)).toBeNull();
    expect(unavailableWhy(command("lab"), { ...IDLE, holdUp: "A file is on its way" })).toBe("A file is on its way");
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
    expect(unmetNote("lab")).toMatch(/\/lab/);
    expect(unmetNote("ask")).toBeNull();
    expect(unmetNote("plan")).toBeNull();
    expect(unmetNote("nothing")).toBeNull();
  });
});

describe("skills written after a slash", () => {
  it("are named by what follows a slash, with the hyphens, digits, and dots a skill's name has", () => {
    expect(typedCommand("/dose-re", "chat", SKILLS)).toEqual({ kind: "naming", query: "dose-re" });
    expect(typedCommand("/scanpy2.1", "chat", SKILLS)).toEqual({ kind: "naming", query: "scanpy2.1" });
  });

  it("are given the words written after the name, whatever the case it was written in, and over several lines", () => {
    expect(typedCommand("/dose-response Fit my curve", "chat", SKILLS)).toEqual({
      kind: "skilling",
      skill: SKILLS[0],
      rest: "Fit my curve",
    });
    expect(typedCommand("/PLOT-style a\nb", "home", SKILLS)).toEqual({ kind: "skilling", skill: SKILLS[1], rest: "a\nb" });
  });

  it("are not a skill unless the conversation has one of that name, and a command is one where both have the name", () => {
    expect(typedCommand("/dose-response Fit it", "chat")).toEqual({ kind: "none" });
    expect(typedCommand("/no-such-skill Fit it", "chat", SKILLS)).toEqual({ kind: "none" });
    expect(typedCommand("/ask Why?", "chat", SKILLS)).toMatchObject({ kind: "arguing", command: command("ask") });
    // The path of a file is still a message
    expect(typedCommand("/data/dose-response.csv Fit it", "chat", SKILLS)).toEqual({ kind: "none" });
  });

  it("are not listed for a slash alone, and are for the letters of their names, after the commands", () => {
    expect(rowsFor("/", SKILLED).map((row) => row.label)).toEqual(rowsFor("/", IDLE).map((row) => row.label));

    const rows = rowsFor("/ose", SKILLED);
    expect(rows).toMatchObject([
      {
        key: "skill dose-response",
        label: "/dose-response",
        summary: "Skill: Fits a dose-response curve.",
        reason: null,
        action: { fill: "/dose-response " },
      },
    ]);
    expect(rowsFor("/r", SKILLED).map((row) => row.label)).toEqual([
      "/review",
      "/rename",
      "/search",
      "/export",
      "/resume",
      "/rna-seq",
      "/dose-response",
    ]);
    expect(rowsFor("/rna", SKILLED).at(-1)?.summary).toBe("Have the lead read this skill first");
  });

  it("are listed up to as many as the menu has room for, those that start with the letters first", () => {
    const many = Array.from({ length: SKILL_ROWS + 5 }, (_, number) => ({ name: `zz-${number}`, description: "" }));
    const rows = rowsFor("/zz", { ...IDLE, skills: [{ name: "azz", description: "" }, ...many] });

    expect(rows).toHaveLength(SKILL_ROWS);
    expect(rows[0].label).toBe("/zz-0");
  });

  it("are sent with the words written after them, trimmed, and wait for there to be some", () => {
    expect(rowsFor("/dose-response ", SKILLED)).toMatchObject([{ label: "/dose-response", reason: "Type what to use it for" }]);
    expect(rowsFor("/dose-response  Fit my curve  ", SKILLED)).toMatchObject([
      { reason: null, summary: "Use the skill dose-response for: Fit my curve", action: { run: { skill: "dose-response", arg: "Fit my curve" } } },
    ]);
    expect(rowsFor("/dose-response a\nb", SKILLED)[0].action).toEqual({ run: { skill: "dose-response", arg: "a\nb" } });
  });

  it("are given when the lead has finished, as a command is, and wait for a file that is still going", () => {
    const working = { ...SKILLED, state: "running" as const };

    expect(rowsFor("/ose", working)[0].reason).toMatch(/finished/);
    expect(rowsFor("/dose-response Fit it", working)[0].reason).toMatch(/finished/);
    expect(rowsFor("/dose-response Fit it", { ...SKILLED, holdUp: "A file is still going" })[0].reason).toBe("A file is still going");
  });

  it("are written out again as they were when they could not be sent", () => {
    expect(written({ skill: "dose-response", arg: "Fit it" })).toBe("/dose-response Fit it");
    expect(written({ skill: "dose-response", arg: "" })).toBe("/dose-response");
  });

  it("are given to the server as a skill, and a command as a command", () => {
    expect(givenAs({ skill: "dose-response", arg: "x" })).toEqual({ skill: "dose-response" });
    expect(givenAs({ name: "ask", arg: "x" })).toEqual({ directive: "ask" });
    expect(givenAs(undefined)).toEqual({});
  });

  it("say when the lead did not read them", () => {
    expect(skillUnmetNote("dose-response")).toBe("The lead answered without reading the skill dose-response, though /dose-response asked for it.");
  });
});

const SUMMARIZE: PromptChoice = {
  server: "genes",
  serverTitle: "Genes",
  command: "genes_summarize_gene",
  name: "summarize_gene",
  description: "Summarize a gene.",
  arguments: [
    { name: "symbol", description: "", required: true },
    { name: "depth", description: "", required: false },
  ],
};
const PLAIN: PromptChoice = { ...SUMMARIZE, command: "genes_overview", name: "overview", description: "", arguments: [] };
const PROMPTED: Surroundings = { ...IDLE, prompts: [SUMMARIZE, PLAIN] };

describe("prompts of MCP servers written after a slash", () => {
  it("are named by what follows a slash, and are given the words written after the name, over several lines", () => {
    expect(typedCommand("/genes_sum", "chat", [], [SUMMARIZE])).toEqual({ kind: "naming", query: "genes_sum" });
    expect(typedCommand("/Genes_Summarize_Gene TP53\nmore", "home", [], [SUMMARIZE])).toEqual({
      kind: "prompting",
      prompt: SUMMARIZE,
      rest: "TP53\nmore",
    });
  });

  it("are not one unless a server of the conversation has it, and a command or a skill of that name comes first", () => {
    expect(typedCommand("/genes_summarize_gene TP53", "chat")).toEqual({ kind: "none" });
    expect(typedCommand("/ask Why?", "chat", [], [{ ...SUMMARIZE, command: "ask" }])).toMatchObject({ kind: "arguing" });
    const skill = { name: "genes_summarize_gene", description: "A skill." };
    expect(typedCommand("/genes_summarize_gene TP53", "chat", [skill], [SUMMARIZE])).toMatchObject({ kind: "skilling" });
  });

  it("are not listed for a slash alone, and are for the letters of their commands, after the commands and the skills", () => {
    expect(rowsFor("/", PROMPTED).map((row) => row.label)).toEqual(rowsFor("/", IDLE).map((row) => row.label));

    expect(rowsFor("/summ", PROMPTED)).toMatchObject([
      {
        key: "prompt genes_summarize_gene",
        label: "/genes_summarize_gene",
        summary: "Prompt of Genes: Summarize a gene.",
        reason: null,
        action: { fill: "/genes_summarize_gene " },
      },
    ]);
    const both = rowsFor("/genes_", { ...PROMPTED, skills: [{ name: "genes_skill", description: "" }] });
    expect(both.map((row) => row.label)).toEqual(["/genes_skill", "/genes_summarize_gene", "/genes_overview"]);
    expect(both.at(-1)?.summary).toBe("Prompt of Genes");
  });

  it("that take no arguments are written out when they are chosen, and those that take some wait to be given them", () => {
    expect(rowsFor("/overview", PROMPTED)).toMatchObject([{ label: "/genes_overview", action: { run: { prompt: PLAIN, values: {}, arg: "" } } }]);
    expect(rowsFor("/genes_overview ", PROMPTED)).toMatchObject([{ reason: null, action: { run: { prompt: PLAIN, values: {}, arg: "" } } }]);
    expect(rowsFor("/genes_overview x", PROMPTED)).toMatchObject([{ reason: "It takes no arguments" }]);
  });

  it("are run with the arguments that were written, and wait for those that are needed", () => {
    expect(rowsFor("/genes_summarize_gene ", PROMPTED)).toMatchObject([{ label: "/genes_summarize_gene", reason: "Type symbol" }]);
    expect(rowsFor("/genes_summarize_gene  TP53 depth=long ", PROMPTED)).toMatchObject([
      {
        reason: null,
        summary: "Write the prompt of Genes out in the box, to read before sending",
        action: { run: { prompt: SUMMARIZE, values: { symbol: "TP53", depth: "long" }, arg: "TP53 depth=long" } },
      },
    ]);
  });

  it("are written out into the box while the lead works, since that is not sending them", () => {
    const working = { ...PROMPTED, state: "running" as const, holdUp: "A file is still going" };

    expect(rowsFor("/summ", working)[0].reason).toBeNull();
    expect(rowsFor("/genes_summarize_gene TP53", working)[0].reason).toBeNull();
  });

  it("are listed up to as many as the menu has room for", () => {
    const many = Array.from({ length: PROMPT_ROWS + 5 }, (_, number) => ({ ...SUMMARIZE, command: `zz_${number}`, name: `zz${number}` }));

    expect(rowsFor("/zz", { ...IDLE, prompts: many })).toHaveLength(PROMPT_ROWS);
  });

  it("are written out again as they were when they could not be written out", () => {
    expect(written({ prompt: SUMMARIZE, values: { symbol: "TP53" }, arg: "TP53" })).toBe("/genes_summarize_gene TP53");
    expect(written({ prompt: PLAIN, values: {}, arg: "" })).toBe("/genes_overview");
  });
});
