import { describe, expect, it } from "vitest";
import { keyProblem, keyRows } from "./keys";
import type { KeyStatuses } from "./types";

const statuses: KeyStatuses = {
  settable: ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"],
  providers: [
    { provider: "OpenAI", variables: ["OPENAI_API_KEY"], missing: [], ready: true },
    { provider: "Anthropic", variables: ["ANTHROPIC_API_KEY"], missing: ["ANTHROPIC_API_KEY"], ready: false },
    // A provider that needs the key with another is not whose the key is, while one needs it alone
    { provider: "AzureOpenAI", variables: ["OPENAI_API_KEY", "OPENAI_ENDPOINT"], missing: ["OPENAI_ENDPOINT"], ready: false },
  ],
};

describe("the keys that can be given", () => {
  it("names whose each is and whether it is set, in the order the server gives them", () => {
    expect(keyRows(statuses)).toEqual([
      { name: "OPENAI_API_KEY", provider: "OpenAI", set: true },
      { name: "ANTHROPIC_API_KEY", provider: "Anthropic", set: false },
      { name: "GEMINI_API_KEY", provider: "GEMINI_API_KEY", set: false },
    ]);
  });

  it("takes a provider that needs the key with others for whose it is, when none needs it alone", () => {
    const only: KeyStatuses = {
      settable: ["OPENAI_API_KEY"],
      providers: [{ provider: "AzureOpenAI", variables: ["OPENAI_API_KEY", "OPENAI_ENDPOINT"], missing: ["OPENAI_ENDPOINT"], ready: false }],
    };

    expect(keyRows(only)).toEqual([{ name: "OPENAI_API_KEY", provider: "AzureOpenAI", set: true }]);
  });

  it("takes the provider that needs the key alone for whose it is, whichever is listed first", () => {
    const given: KeyStatuses = {
      settable: ["OPENAI_API_KEY"],
      providers: [
        { provider: "AzureOpenAI", variables: ["OPENAI_API_KEY", "OPENAI_ENDPOINT"], missing: [], ready: true },
        { provider: "OpenAI", variables: ["OPENAI_API_KEY"], missing: [], ready: true },
      ],
    };

    expect(keyRows(given)).toEqual([{ name: "OPENAI_API_KEY", provider: "OpenAI", set: true }]);
  });

  it("says a key is set by its own provider's variables, whichever other variables are missing", () => {
    const given: KeyStatuses = {
      settable: ["OPENAI_API_KEY"],
      providers: [
        { provider: "OpenAI", variables: ["OPENAI_API_KEY"], missing: ["OPENAI_API_KEY"], ready: false },
        { provider: "AzureOpenAI", variables: ["OPENAI_API_KEY", "OPENAI_ENDPOINT"], missing: ["OPENAI_API_KEY", "OPENAI_ENDPOINT"], ready: false },
      ],
    };

    expect(keyRows(given)[0]).toMatchObject({ provider: "OpenAI", set: false });
  });
});

describe("a key as it was typed", () => {
  it("is fine on one line, with spaces round it", () => {
    expect(keyProblem("sk-abc123")).toBeNull();
    expect(keyProblem("  sk-abc123  \n")).toBeNull();
  });

  it("is not fine with nothing in it", () => {
    expect(keyProblem("")).toBe("Paste the key first.");
    expect(keyProblem("  \n ")).toBe("Paste the key first.");
  });

  it("is not fine with more than one line, or a character that no variable holds", () => {
    expect(keyProblem("sk-abc\nsk-def")).toMatch(/one line/);
    expect(keyProblem("sk-abc\tdef")).toMatch(/one line/);
    expect(keyProblem("sk-abc\u0000")).toMatch(/one line/);
    expect(keyProblem("sk-\u007fabc")).toMatch(/one line/);
    expect(keyProblem("sk-abc\u001f")).toMatch(/one line/);
  });
});
