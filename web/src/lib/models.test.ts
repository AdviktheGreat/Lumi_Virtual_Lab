import { describe, expect, it } from "vitest";
import { describeContext, describePrice, grouped, matching, rowsOf, typedModel } from "./models";
import { keysMissingFor } from "./settings";
import type { KeyStatuses, Models, OpenRouterList } from "./types";

const models: Models = {
  default: "gpt-5.2",
  models: [
    { id: "gpt-5.2", provider: "OpenAI", ready: true },
    { id: "claude-sonnet-4-5", provider: "Anthropic", ready: false },
    { id: "openrouter/auto", provider: "OpenRouter", ready: true },
    { id: "openrouter/anthropic/claude-sonnet-4.5", provider: "OpenRouter", ready: true },
    { id: "mystery", provider: null, ready: false },
  ],
};

const openrouter: OpenRouterList = {
  problem: null,
  models: [
    { id: "openrouter/auto", name: "Auto Router", context_length: 2_000_000, input_per_million: null, output_per_million: null },
    {
      id: "openrouter/anthropic/claude-sonnet-4.5",
      name: "Anthropic: Claude Sonnet 4.5",
      context_length: 1_000_000,
      input_per_million: 3,
      output_per_million: 15,
    },
    {
      id: "openrouter/meta-llama/llama-3.3-70b-instruct:free",
      name: "Meta: Llama 3.3 70B Instruct (free)",
      context_length: 131_072,
      input_per_million: 0,
      output_per_million: 0,
    },
  ],
};

describe("describing what a model costs and reads", () => {
  it("says what it costs in and out per million tokens", () => {
    expect(describePrice({ input_per_million: 3, output_per_million: 15 })).toBe("$3 in, $15 out per million tokens");
    expect(describePrice({ input_per_million: 0.2834, output_per_million: 0.0009 })).toBe(
      "$0.28 in, <$0.01 out per million tokens",
    );
  });

  it("says a free model is free, and nothing of a price that depends on what is asked", () => {
    expect(describePrice({ input_per_million: 0, output_per_million: 0 })).toBe("Free");
    expect(describePrice({ input_per_million: null, output_per_million: null })).toBeNull();
    expect(describePrice({ input_per_million: 1, output_per_million: null })).toBeNull();
  });

  it("says how much it reads in thousands or millions of tokens", () => {
    expect(describeContext(131_072)).toBe("131k tokens");
    expect(describeContext(1_000_000)).toBe("1M tokens");
    expect(describeContext(1_048_576)).toBe("1M tokens");
    expect(describeContext(2_000_000)).toBe("2M tokens");
    expect(describeContext(null)).toBeNull();
    expect(describeContext(0)).toBeNull();
  });
});

describe("the models to choose from", () => {
  it("is what the server lists while OpenRouter's whole list is not known", () => {
    const rows = rowsOf(models, null);

    expect(rows.map((row) => row.id)).toEqual([
      "gpt-5.2",
      "claude-sonnet-4-5",
      "openrouter/auto",
      "openrouter/anthropic/claude-sonnet-4.5",
      "mystery",
    ]);
    expect(rows.find((row) => row.id === "mystery")?.provider).toBe("Others");
    expect(rows.find((row) => row.id === "claude-sonnet-4-5")?.ready).toBe(false);
  });

  it("has all of OpenRouter's models in the place of the few the server lists, once they are known", () => {
    const rows = rowsOf(models, openrouter);

    expect(rows.map((row) => row.id)).toEqual([
      "gpt-5.2",
      "claude-sonnet-4-5",
      "openrouter/auto",
      "openrouter/anthropic/claude-sonnet-4.5",
      "openrouter/meta-llama/llama-3.3-70b-instruct:free",
      "mystery",
    ]);
    const sonnet = rows.find((row) => row.id === "openrouter/anthropic/claude-sonnet-4.5");
    expect(sonnet).toMatchObject({ name: "Anthropic: Claude Sonnet 4.5", ready: true, context: "1M tokens" });
    expect(sonnet?.price).toBe("$3 in, $15 out per million tokens");
  });

  it("is ready for OpenRouter's models when its key is set, and not when it is not", () => {
    const without: Models = {
      ...models,
      models: models.models.map((choice) => (choice.provider === "OpenRouter" ? { ...choice, ready: false } : choice)),
    };

    expect(rowsOf(without, openrouter).filter((row) => row.provider === "OpenRouter").every((row) => !row.ready)).toBe(true);
  });

  it("has OpenRouter's models alone where the server's list could not be read", () => {
    expect(rowsOf(null, openrouter).map((row) => row.provider)).toEqual(["OpenRouter", "OpenRouter", "OpenRouter"]);
    expect(rowsOf(null, null)).toEqual([]);
  });

  it("is grouped by provider in the order it comes", () => {
    expect(grouped(rowsOf(models, openrouter)).map(([provider, rows]) => [provider, rows.length])).toEqual([
      ["OpenAI", 1],
      ["Anthropic", 1],
      ["OpenRouter", 3],
      ["Others", 1],
    ]);
  });
});

describe("searching the models", () => {
  const rows = rowsOf(models, openrouter);

  it("keeps those that have every word, in the name or in what OpenRouter calls it, whatever the case", () => {
    expect(matching(rows, "CLAUDE").map((row) => row.id)).toEqual([
      "claude-sonnet-4-5",
      "openrouter/anthropic/claude-sonnet-4.5",
    ]);
    expect(matching(rows, "llama free").map((row) => row.id)).toEqual([
      "openrouter/meta-llama/llama-3.3-70b-instruct:free",
    ]);
    expect(matching(rows, "auto router").map((row) => row.id)).toEqual(["openrouter/auto"]);
  });

  it("keeps all of them where nothing is typed, and none where nothing matches", () => {
    expect(matching(rows, "   ")).toBe(rows);
    expect(matching(rows, "no such model")).toEqual([]);
  });

  it("offers a model that is typed and not listed, as it is typed", () => {
    expect(typedModel(rows, "  openrouter/x/y ")).toBe("openrouter/x/y");
    expect(typedModel(rows, "gpt-5.2")).toBeNull();
    expect(typedModel(rows, "   ")).toBeNull();
  });
});

describe("the keys a model needs", () => {
  const keys: KeyStatuses = {
    settable: ["OPENAI_API_KEY", "OPENROUTER_API_KEY"],
    providers: [
      { provider: "OpenAI", variables: ["OPENAI_API_KEY"], missing: [], ready: true },
      { provider: "OpenRouter", variables: ["OPENROUTER_API_KEY"], missing: ["OPENROUTER_API_KEY"], ready: false },
    ],
    keychain: { available: false, name: null, problem: null },
    sources: {},
    problem: null,
  };

  it("are OpenRouter's for any model named for OpenRouter, listed by the server or not", () => {
    expect(keysMissingFor("openrouter/auto", models, keys)).toEqual(["OPENROUTER_API_KEY"]);
    expect(keysMissingFor("openrouter/mistralai/mistral-large", models, keys)).toEqual(["OPENROUTER_API_KEY"]);
    expect(keysMissingFor("openrouter/mistralai/mistral-large", null, keys)).toEqual(["OPENROUTER_API_KEY"]);
    expect(keysMissingFor("gpt-5.2", models, keys)).toEqual([]);
  });
});
