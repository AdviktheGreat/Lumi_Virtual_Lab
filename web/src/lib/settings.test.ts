import { describe, expect, it } from "vitest";
import { changesOf, draftOf, isOffered, keysMissingFor, parseLimit, type Draft } from "./settings";
import type { KeyStatuses, Models, Settings } from "./types";

const settings: Settings = {
  model: "gpt-5.2",
  stream: true,
  max_cost: null,
  code: "none",
  sandbox: "python",
  network: true,
  python: "",
  data_lake: "",
  forward_keys: [],
  workspace: "/work",
  max_upload_bytes: 1000,
};

const models: Models = {
  default: "gpt-5.2",
  models: [
    { id: "gpt-5.2", provider: "OpenAI", ready: false },
    { id: "claude-sonnet-4-5", provider: "Anthropic", ready: true },
    { id: "mystery", provider: null, ready: true },
  ],
};

const keys: KeyStatuses = {
  settable: ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
  providers: [
    { provider: "OpenAI", variables: ["OPENAI_API_KEY"], missing: ["OPENAI_API_KEY"], ready: false },
    { provider: "Anthropic", variables: ["ANTHROPIC_API_KEY"], missing: [], ready: true },
  ],
};

const edited = (changes: Partial<Draft>): Draft => ({ ...draftOf(settings), ...changes });

describe("the form's draft of the settings", () => {
  it("shows what the settings say, with a limit as it would be typed and nothing for none", () => {
    expect(draftOf(settings)).toEqual({
      model: "gpt-5.2",
      stream: true,
      limit: "",
      code: "none",
      sandbox: "python",
      network: true,
      python: "",
      dataLake: "",
      forwardKeys: [],
    });
    expect(draftOf({ ...settings, max_cost: 12.5 }).limit).toBe("12.5");
    expect(draftOf({ ...settings, max_cost: 0 }).limit).toBe("0");
  });

  it("is a copy, so that choosing keys does not change the settings", () => {
    const given = { ...settings, forward_keys: ["OPENAI_API_KEY"] };

    draftOf(given).forwardKeys.push("GROQ_API_KEY");

    expect(given.forward_keys).toEqual(["OPENAI_API_KEY"]);
  });
});

describe("reading a limit", () => {
  it("takes nothing, or only spaces, for no limit", () => {
    expect(parseLimit("")).toBeNull();
    expect(parseLimit("   ")).toBeNull();
  });

  it("takes an amount, with or without a dollar sign, a point, or digits before it", () => {
    expect(parseLimit("5")).toBe(5);
    expect(parseLimit(" 12.50 ")).toBe(12.5);
    expect(parseLimit("$7")).toBe(7);
    expect(parseLimit("$ 7.25")).toBe(7.25);
    expect(parseLimit(".5")).toBe(0.5);
    expect(parseLimit("5.")).toBe(5);
    expect(parseLimit("0")).toBe(0);
    expect(parseLimit("007")).toBe(7);
  });

  it("refuses what is not an amount, and what the server would refuse", () => {
    for (const typed of ["-1", "+1", "1e3", "0x10", "abc", "1,000", "1 000", "5 dollars", "NaN", "Infinity", "1.2.3", ".", "$"]) {
      expect(parseLimit(typed), typed).toBeUndefined();
    }
    expect(parseLimit("9".repeat(400))).toBeUndefined();
  });
});

describe("what the form changes", () => {
  it("says nothing of a form that is as the settings are", () => {
    expect(changesOf(draftOf(settings), settings)).toEqual({ changes: {}, problems: {} });
  });

  it("says each setting that differs, as the server is asked for it, and no other", () => {
    const { changes, problems } = changesOf(
      edited({
        model: " claude-sonnet-4-5 ",
        stream: false,
        limit: "$5",
        code: "docker",
        sandbox: "bio",
        network: false,
        python: " /usr/bin/python3 ",
        dataLake: " /data/lake ",
        forwardKeys: ["GROQ_API_KEY"],
      }),
      settings,
    );

    expect(problems).toEqual({});
    expect(changes).toEqual({
      model: "claude-sonnet-4-5",
      stream: false,
      max_cost: 5,
      code: "docker",
      sandbox: "bio",
      network: false,
      python: "/usr/bin/python3",
      data_lake: "/data/lake",
      forward_keys: ["GROQ_API_KEY"],
    });
  });

  it("says one setting alone when only that differs", () => {
    expect(changesOf(edited({ stream: false }), settings).changes).toEqual({ stream: false });
    expect(changesOf(edited({ network: false }), settings).changes).toEqual({ network: false });
    expect(changesOf(edited({ code: "local" }), settings).changes).toEqual({ code: "local" });
    expect(changesOf(edited({ sandbox: "full" }), settings).changes).toEqual({ sandbox: "full" });
    expect(changesOf(edited({ model: "claude-sonnet-4-5" }), settings).changes).toEqual({ model: "claude-sonnet-4-5" });
    expect(changesOf(edited({ python: "/opt/python" }), settings).changes).toEqual({ python: "/opt/python" });
    expect(changesOf(edited({ dataLake: "/lake" }), settings).changes).toEqual({ data_lake: "/lake" });
  });

  it("takes spaces round what was typed for nothing", () => {
    expect(changesOf(edited({ model: " gpt-5.2 ", python: "  ", dataLake: " " }), settings).changes).toEqual({});
  });

  it("puts no limit as null, and says it only when there was one", () => {
    expect(changesOf(edited({ limit: "" }), settings).changes).toEqual({});
    expect(changesOf(edited({ limit: "" }), { ...settings, max_cost: 3 }).changes).toEqual({ max_cost: null });
    expect(changesOf(edited({ limit: "3.0" }), { ...settings, max_cost: 3 }).changes).toEqual({});
    expect(changesOf(edited({ limit: "0" }), settings).changes).toEqual({ max_cost: 0 });
  });

  it("takes the keys for code as the same whatever the order they were chosen in", () => {
    const given = { ...settings, forward_keys: ["OPENAI_API_KEY", "GROQ_API_KEY"] };

    expect(changesOf(edited({ forwardKeys: ["GROQ_API_KEY", "OPENAI_API_KEY"] }), given).changes).toEqual({});
    expect(changesOf(edited({ forwardKeys: ["GROQ_API_KEY"] }), given).changes).toEqual({ forward_keys: ["GROQ_API_KEY"] });
    expect(changesOf(edited({ forwardKeys: ["OPENAI_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY"] }), given).changes).toEqual({
      forward_keys: ["OPENAI_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY"],
    });
    expect(changesOf(edited({ forwardKeys: ["OPENAI_API_KEY", "OPENAI_API_KEY"] }), { ...settings, forward_keys: ["OPENAI_API_KEY", "GROQ_API_KEY"] }).changes).toEqual({
      forward_keys: ["OPENAI_API_KEY", "OPENAI_API_KEY"],
    });
  });

  it("refuses a model with nothing in it, and a limit that is not an amount, and sends neither", () => {
    const { changes, problems } = changesOf(edited({ model: "  ", limit: "lots", stream: false }), settings);

    expect(problems.model).toBe("Choose a model.");
    expect(problems.limit).toMatch(/amount in dollars/);
    expect(changes).toEqual({ stream: false });
  });
});

describe("the models the server offers", () => {
  it("says whether a model is one of them, and that none is while they are not known", () => {
    expect(isOffered("claude-sonnet-4-5", models)).toBe(true);
    expect(isOffered("my-own-model", models)).toBe(false);
    expect(isOffered("gpt-5.2", null)).toBe(false);
  });

  it("names the keys a model needs that are not set", () => {
    expect(keysMissingFor("gpt-5.2", models, keys)).toEqual(["OPENAI_API_KEY"]);
  });

  it("names none for a model whose key is set, that is not offered, or whose provider is not known", () => {
    expect(keysMissingFor("claude-sonnet-4-5", models, keys)).toEqual([]);
    expect(keysMissingFor("my-own-model", models, keys)).toEqual([]);
    expect(keysMissingFor("mystery", models, keys)).toEqual([]);
  });

  it("names none while the models or the keys are not known", () => {
    expect(keysMissingFor("gpt-5.2", null, keys)).toEqual([]);
    expect(keysMissingFor("gpt-5.2", models, null)).toEqual([]);
  });
});
