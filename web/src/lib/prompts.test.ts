import { describe, expect, it } from "vitest";
import { promptChoices, readPromptArguments, withPrompt, type PromptChoice } from "./prompts";
import type { McpPrompt, McpServer } from "./types";

const prompt = (name: string, args: McpPrompt["arguments"] = []): McpPrompt => ({
  name,
  command: `genes_${name}`,
  title: null,
  description: `Does ${name}.`,
  arguments: args,
});

const SUMMARIZE = prompt("summarize_gene", [
  { name: "symbol", description: "The gene symbol", required: true },
  { name: "depth", description: "", required: false },
]);

const server = (name: string, fields: Partial<McpServer> = {}): McpServer => ({
  name,
  title: `${name} title`,
  about: null,
  preset: false,
  added: true,
  enabled: true,
  auth: null,
  auth_choices: [],
  transport: "http",
  target: null,
  asks: false,
  signed_in: null,
  missing: [],
  keys_set: [],
  problem: null,
  setup: null,
  holds: { resources: [], prompts: [SUMMARIZE], problems: [], more: false },
  ...fields,
});

const choice = (fields: Partial<PromptChoice> = {}): PromptChoice => ({
  server: "genes",
  serverTitle: "Genes",
  command: "genes_summarize_gene",
  name: "summarize_gene",
  description: "",
  arguments: SUMMARIZE.arguments,
  ...fields,
});

describe("the prompts that can be written after a slash", () => {
  it("are those of the servers that are on, where none are named, and only of those that were connected to", () => {
    const servers = [
      server("genes"),
      server("off", { enabled: false }),
      server("unseen", { holds: null }),
      server("preset", { added: false }),
    ];

    expect(promptChoices(servers, null)).toEqual([
      {
        server: "genes",
        serverTitle: "genes title",
        command: "genes_summarize_gene",
        name: "summarize_gene",
        description: "Does summarize_gene.",
        arguments: SUMMARIZE.arguments,
      },
    ]);
  });

  it("are those of the servers named, as a conversation has them, whether or not they are on now", () => {
    const servers = [server("genes"), server("off", { enabled: false }), server("other")];

    expect(promptChoices(servers, ["off"]).map((each) => each.server)).toEqual(["off"]);
    expect(promptChoices(servers, ["genes", "other"]).map((each) => each.server)).toEqual(["genes", "other"]);
    expect(promptChoices(servers, [])).toEqual([]);
  });

  it("are none until the servers are read", () => {
    expect(promptChoices(null, null)).toEqual([]);
  });
});

describe("the arguments written after a prompt", () => {
  it("are none for a prompt that takes none, and what is written is refused", () => {
    expect(readPromptArguments(choice({ arguments: [] }), "  ")).toEqual({ ok: true, values: {} });
    expect(readPromptArguments(choice({ arguments: [] }), "TP53")).toEqual({ ok: false, problem: "It takes no arguments" });
  });

  it("are the words for the first argument that is needed, and the rest are written name=words", () => {
    expect(readPromptArguments(choice(), "  TP53  ")).toEqual({ ok: true, values: { symbol: "TP53" } });
    expect(readPromptArguments(choice(), "TP53 and its relatives")).toEqual({ ok: true, values: { symbol: "TP53 and its relatives" } });
    expect(readPromptArguments(choice(), "TP53 depth=long")).toEqual({ ok: true, values: { symbol: "TP53", depth: "long" } });
    expect(readPromptArguments(choice(), "depth=very long indeed symbol=BRCA1")).toEqual({
      ok: true,
      values: { depth: "very long indeed", symbol: "BRCA1" },
    });
  });

  it("are the first the prompt takes where it needs none", () => {
    const optional = choice({ arguments: [{ name: "focus", description: "", required: false }, { name: "tone", description: "", required: false }] });

    expect(readPromptArguments(optional, "")).toEqual({ ok: true, values: {} });
    expect(readPromptArguments(optional, "the heart")).toEqual({ ok: true, values: { focus: "the heart" } });
  });

  it("say what is lacking: the words for the first, or name= for any other", () => {
    expect(readPromptArguments(choice(), "")).toEqual({ ok: false, problem: "Type symbol" });
    expect(readPromptArguments(choice(), "depth=long")).toEqual({ ok: false, problem: "Type symbol" });
    const two = choice({
      arguments: [
        { name: "first", description: "", required: true },
        { name: "second", description: "", required: true },
      ],
    });
    expect(readPromptArguments(two, "TP53")).toEqual({ ok: false, problem: "Add second=…" });
    expect(readPromptArguments(two, "TP53 second=BRCA1")).toEqual({ ok: true, values: { first: "TP53", second: "BRCA1" } });
  });

  it("are refused when one is given twice, and a name that the prompt does not take is part of the words", () => {
    expect(readPromptArguments(choice(), "TP53 symbol=BRCA1")).toEqual({ ok: false, problem: "symbol is given twice" });
    expect(readPromptArguments(choice(), "colour=red")).toEqual({ ok: true, values: { symbol: "colour=red" } });
  });

  it("are read whatever the characters of a name, which is not a pattern", () => {
    const odd = choice({ arguments: [{ name: "a.b", description: "", required: true }, { name: "axb", description: "", required: false }] });

    expect(readPromptArguments(odd, "a.b=1 axb=2")).toEqual({ ok: true, values: { "a.b": "1", axb: "2" } });
    expect(readPromptArguments(odd, "axb=2 a.b=1")).toEqual({ ok: true, values: { axb: "2", "a.b": "1" } });
  });

  it("keep the lines of what is written", () => {
    expect(readPromptArguments(choice(), "line one\nline two depth=short")).toEqual({
      ok: true,
      values: { symbol: "line one\nline two", depth: "short" },
    });
  });
});

describe("the box with a prompt put in it", () => {
  it("has the prompt in place of nothing, and after what the person wrote since", () => {
    expect(withPrompt("", "Summarize TP53.")).toBe("Summarize TP53.");
    expect(withPrompt("  \n", "Summarize TP53.")).toBe("Summarize TP53.");
    expect(withPrompt("Also:", "Summarize TP53.")).toBe("Also:\n\nSummarize TP53.");
  });
});
