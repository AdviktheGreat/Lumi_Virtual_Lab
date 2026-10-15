import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chooseKeepKeys, describeRemoved, describeSaved, describeSource, keepKeys, keyProblem, keyRows } from "./keys";
import type { Keychain, KeyStatuses } from "./types";

const keychain: Keychain = { available: true, name: "macOS Keychain", problem: null };
const nothingSaid = { keychain, sources: {}, problem: null };

const statuses: KeyStatuses = {
  ...nothingSaid,
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
      { name: "OPENAI_API_KEY", provider: "OpenAI", set: true, source: null },
      { name: "ANTHROPIC_API_KEY", provider: "Anthropic", set: false, source: null },
      { name: "GEMINI_API_KEY", provider: "GEMINI_API_KEY", set: false, source: null },
    ]);
  });

  it("takes a provider that needs the key with others for whose it is, when none needs it alone", () => {
    const only: KeyStatuses = {
      ...nothingSaid,
      settable: ["OPENAI_API_KEY"],
      providers: [{ provider: "AzureOpenAI", variables: ["OPENAI_API_KEY", "OPENAI_ENDPOINT"], missing: ["OPENAI_ENDPOINT"], ready: false }],
    };

    expect(keyRows(only)).toEqual([{ name: "OPENAI_API_KEY", provider: "AzureOpenAI", set: true, source: null }]);
  });

  it("takes the provider that needs the key alone for whose it is, whichever is listed first", () => {
    const given: KeyStatuses = {
      ...nothingSaid,
      settable: ["OPENAI_API_KEY"],
      providers: [
        { provider: "AzureOpenAI", variables: ["OPENAI_API_KEY", "OPENAI_ENDPOINT"], missing: [], ready: true },
        { provider: "OpenAI", variables: ["OPENAI_API_KEY"], missing: [], ready: true },
      ],
    };

    expect(keyRows(given)).toEqual([{ name: "OPENAI_API_KEY", provider: "OpenAI", set: true, source: null }]);
  });

  it("says a key is set by its own provider's variables, whichever other variables are missing", () => {
    const given: KeyStatuses = {
      ...nothingSaid,
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

describe("where a key is kept", () => {
  it("is said of each key that is set, by where the server says it came from", () => {
    const given: KeyStatuses = {
      ...statuses,
      sources: { OPENAI_API_KEY: "keychain", ANTHROPIC_API_KEY: "session", GEMINI_API_KEY: "environment" },
    };

    expect(keyRows(given).map((row) => row.source)).toEqual(["keychain", "session", "environment"]);
  });

  it("is told beside the key, in words, with the keychain by its name", () => {
    expect(describeSource("keychain", keychain)).toBe("In the macOS Keychain");
    expect(describeSource("session", keychain)).toBe("Until the server stops");
    expect(describeSource("environment", keychain)).toBe("From the server's environment");
    expect(describeSource(undefined, keychain)).toBeNull();
  });

  it("is told of a keychain with no name as the keychain", () => {
    expect(describeSource("keychain", { available: true, name: null, problem: null })).toBe("In the keychain");
  });
});

describe("what is told of a key that was given or taken away", () => {
  const given = (sources: KeyStatuses["sources"], problem: string | null = null): KeyStatuses => ({
    ...statuses,
    sources,
    problem,
  });

  it("is that it was saved in the keychain, by name, when it was", () => {
    expect(describeSaved(given({ OPENAI_API_KEY: "keychain" }), "OPENAI_API_KEY")).toEqual({
      done: "Saved in the macOS Keychain.",
      warning: null,
    });
  });

  it("is that it was saved until the server stops, when it was kept for the session alone", () => {
    expect(describeSaved(given({ OPENAI_API_KEY: "session" }), "OPENAI_API_KEY")).toEqual({
      done: "Saved until the server stops.",
      warning: null,
    });
  });

  it("is that it was saved until the server stops, with what went wrong, when the keychain would not keep it", () => {
    const told = describeSaved(given({ OPENAI_API_KEY: "session" }, "The key is set until the server stops. Locked."), "OPENAI_API_KEY");

    expect(told).toEqual({ done: "Saved until the server stops.", warning: "The key is set until the server stops. Locked." });
  });

  it("is of the key that was given, and not of another that is kept", () => {
    expect(describeSaved(given({ OPENAI_API_KEY: "keychain", GROQ_API_KEY: "session" }), "GROQ_API_KEY").done).toBe(
      "Saved until the server stops.",
    );
  });

  it("is that a key was removed, with what went wrong if the keychain would not forget it", () => {
    expect(describeRemoved(given({}))).toEqual({ done: "Removed.", warning: null });
    expect(describeRemoved(given({}, "May be back."))).toEqual({ done: "Removed.", warning: "May be back." });
  });
});

describe("keeping the keys that are given", () => {
  const store = new Map<string, string>();

  beforeEach(() => {
    store.clear();
    vi.stubGlobal("localStorage", {
      getItem: (name: string) => store.get(name) ?? null,
      setItem: (name: string, value: string) => void store.set(name, value),
      removeItem: (name: string) => void store.delete(name),
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("is chosen unless it was said not to be", () => {
    expect(keepKeys()).toBe(true);
  });

  it("is chosen against only by what this page keeps to say so, and not by anything else that is kept", () => {
    store.set("virtual-lab.keep-keys", "something else");
    expect(keepKeys()).toBe(true);

    store.set("virtual-lab.keep-keys", "no");
    expect(keepKeys()).toBe(false);
  });

  it("is remembered, as it was chosen, by this browser", () => {
    chooseKeepKeys(false);
    expect(keepKeys()).toBe(false);

    chooseKeepKeys(true);
    expect(keepKeys()).toBe(true);
    // What is kept to say it is chosen is nothing at all, so that a choice made by default is not kept as a choice
    expect(store.size).toBe(0);
  });

  it("is chosen where a browser keeps nothing, and a choice there is for the page that is open", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    });

    expect(keepKeys()).toBe(true);
    expect(() => chooseKeepKeys(false)).not.toThrow();
    expect(() => chooseKeepKeys(true)).not.toThrow();
  });
});
