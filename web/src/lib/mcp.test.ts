import { describe, expect, it } from "vitest";
import {
  MOST_TOOLS_NAMED,
  describeCheck,
  describeHolds,
  describeSignIn,
  describeTransport,
  howManyOn,
  keysToGive,
  keysToSetElsewhere,
  nameProblem,
  readEntry,
} from "./mcp";
import type { McpHolds, McpServer } from "./types";

const server = (name: string, fields: Partial<McpServer> = {}): McpServer => ({
  name,
  title: name,
  about: null,
  preset: false,
  added: true,
  enabled: true,
  auth: null,
  auth_choices: [],
  transport: "http",
  target: "https://example.com/mcp",
  asks: false,
  signed_in: null,
  missing: [],
  keys_set: [],
  problem: null,
  setup: null,
  holds: null,
  ...fields,
});

describe("the name of a server of one's own", () => {
  const servers = [server("paperclip", { preset: true }), server("mine")];

  it("is one the server takes: it starts with a letter and has only letters, digits, and _", () => {
    for (const name of ["a", "lab_tools", "Tool2", "A".repeat(32)]) expect(nameProblem(name, servers)).toBeNull();
  });

  it("is not empty, not one that starts with a digit, nor one with other characters, nor too long", () => {
    for (const name of ["", "   ", "2fast", "_x", "a b", "a-b", "é", "A".repeat(33)]) expect(nameProblem(name, servers)).not.toBeNull();
  });

  it("is taken without the spaces around it", () => {
    expect(nameProblem("  tools ", servers)).toBeNull();
  });

  it("is not the name of one of the library's servers, which is told", () => {
    expect(nameProblem("paperclip", servers)).toBe("paperclip is the name of one of the library's servers: name yours something else.");
  });

  it("may be the name of one of one's own, which is replaced", () => {
    expect(nameProblem("mine", servers)).toBeNull();
  });
});

describe("a server's entry as it was typed", () => {
  it("is the object that was typed", () => {
    expect(readEntry('{"url": "https://x.org/mcp", "headers": {"A": "b"}}')).toEqual({
      ok: true,
      entry: { url: "https://x.org/mcp", headers: { A: "b" } },
    });
  });

  it("is not nothing", () => {
    for (const text of ["", "  \n "]) expect(readEntry(text)).toMatchObject({ ok: false, problem: expect.stringContaining("Describe the server in JSON") });
  });

  it("is not text that is not JSON, which says what is wrong with it", () => {
    const read = readEntry("{url: 1}");

    expect(read.ok).toBe(false);
    expect(!read.ok && read.problem).toMatch(/^That is not JSON: .+\.$/);
  });

  it("is not a list, a string, a number, or nothing, but an object", () => {
    for (const text of ["[]", '"x"', "7", "null", "true"]) {
      expect(readEntry(text)).toMatchObject({ ok: false, problem: expect.stringContaining("described by an object") });
    }
  });
});

describe("how many servers are on", () => {
  it("is said in words", () => {
    expect(howManyOn([])).toBe("None are on");
    expect(howManyOn([server("a", { enabled: false })])).toBe("None are on");
    expect(howManyOn([server("a"), server("b")])).toBe("All 2 are on");
    expect(howManyOn([server("a"), server("b", { enabled: false }), server("c")])).toBe("2 of 3 are on");
  });
});

describe("how a server is reached", () => {
  it("is said in words, and not for one that cannot be read", () => {
    expect(describeTransport(server("a", { transport: "stdio" }))).toBe("Runs a program on this computer");
    expect(describeTransport(server("a", { transport: "http" }))).toBe("Reached over HTTP");
    expect(describeTransport(server("a", { transport: "sse" }))).toBe("Reached over SSE");
    expect(describeTransport(server("a", { transport: null }))).toBeNull();
  });
});

describe("the keys of a server", () => {
  const given = server("a", {
    missing: [
      { name: "ONE", settable: true },
      { name: "TWO", settable: false },
      { name: "THREE", settable: true },
    ],
    keys_set: ["FOUR"],
  });

  it("are given here where they are of the library's services, and the rest where the server was started", () => {
    expect(keysToSetElsewhere(given)).toEqual(["TWO"]);
    expect(keysToGive(given)).toEqual([
      { name: "ONE", set: false },
      { name: "THREE", set: false },
      { name: "FOUR", set: true },
    ]);
  });

  it("are none for a server that asks for none", () => {
    expect(keysToSetElsewhere(server("a"))).toEqual([]);
    expect(keysToGive(server("a"))).toEqual([]);
  });
});

describe("what a check of a server found", () => {
  it("is the names of the tools, counted", () => {
    expect(describeCheck({ ok: true, tools: ["genes_echo", "genes_count"], reason: null })).toEqual({
      text: "Connected. It gives 2 tools:",
      tools: ["genes_echo", "genes_count"],
      more: 0,
    });
    expect(describeCheck({ ok: true, tools: ["genes_echo"], reason: null }).text).toBe("Connected. It gives 1 tool:");
  });

  it("says so when the server gives no tools", () => {
    expect(describeCheck({ ok: true, tools: [], reason: null })).toEqual({ text: "Connected, but it gives no tools.", tools: [], more: 0 });
  });

  it("names only so many tools, and says how many more there are", () => {
    const tools = Array.from({ length: MOST_TOOLS_NAMED + 5 }, (_, at) => `t${at}`);

    const found = describeCheck({ ok: true, tools, reason: null });

    expect(found.tools).toEqual(tools.slice(0, MOST_TOOLS_NAMED));
    expect(found.more).toBe(5);
    expect(found.text).toBe(`Connected. It gives ${MOST_TOOLS_NAMED + 5} tools:`);
    expect(describeCheck({ ok: true, tools: tools.slice(0, MOST_TOOLS_NAMED), reason: null }).more).toBe(0);
  });

  it("is why it could not be connected to, and names no tools", () => {
    expect(describeCheck({ ok: false, tools: ["ignored"], reason: "Refused." })).toEqual({ text: "Refused.", tools: [], more: 0 });
    expect(describeCheck({ ok: false, tools: [], reason: null }).text).toBe("It could not be connected to.");
  });
});

describe("a server's sign-in", () => {
  it("is said for a server that is signed in to, whether or not it has been", () => {
    expect(describeSignIn(server("a", { signed_in: true }))).toBe("Signed in. Programs use it without asking you.");
    expect(describeSignIn(server("a", { signed_in: false }))).toMatch(/^Not signed in yet\. A program .* when you send its first message\.$/);
  });

  it("is not said for a server that is not signed in to", () => {
    expect(describeSignIn(server("a", { signed_in: null }))).toBeNull();
  });
});

describe("what a server lists besides its tools", () => {
  const holds = (resources: number, prompts: number, more = false): McpHolds => ({
    resources: Array.from({ length: resources }, (_, at) => ({
      name: `r${at}`,
      title: null,
      uri: `genes://r${at}`,
      description: "",
      mime_type: null,
      template: false,
    })),
    prompts: Array.from({ length: prompts }, (_, at) => ({ name: `p${at}`, command: `genes_p${at}`, title: null, description: "", arguments: [] })),
    problems: [],
    more,
  });

  it("is told in a few words, with the counts of each that there is", () => {
    expect(describeHolds(holds(2, 1))).toBe("2 resources and 1 prompt");
    expect(describeHolds(holds(1, 0))).toBe("1 resource");
    expect(describeHolds(holds(0, 3))).toBe("3 prompts");
  });

  it("is nothing where it lists none, and is said to be at least what is counted where there is more", () => {
    expect(describeHolds(holds(0, 0))).toBeNull();
    expect(describeHolds(holds(2, 1, true))).toBe("at least 2 resources and 1 prompt");
  });
});
