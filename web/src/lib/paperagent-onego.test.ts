import { describe, expect, it } from "vitest";
import {
  checkMore,
  checkOneGo,
  decisionOf,
  describeLimit,
  describeOneGo,
  emptyOneGo,
  offersWithoutCode,
  ONEGO_STATE_LABELS,
  ONEGO_STEP_LABELS,
  spends,
} from "./paperagent-onego";
import type { OneGoSettings, OneGoStep, OneGoStepName, OneGoStuck, PaperAgent, PaperAgentOneGo } from "./types";

const SETTINGS: OneGoSettings = { max_cost: null, repo: null, ref: null, give: true, without_code: false, go_on: null };

const ORDER: OneGoStepName[] = ["repository", "reading", "look", "environment", "reference", "tools", "checks", "given"];

function view(changes: Partial<PaperAgentOneGo> = {}): PaperAgentOneGo {
  return {
    id: "cells",
    state: "none",
    started_at: null,
    finished_at: null,
    settings: SETTINGS,
    steps: ORDER.map((step): OneGoStep => ({ step, title: step, state: "pending", note: null })),
    stuck: null,
    summary: null,
    job: null,
    ...changes,
  };
}

function stuck(kind: string, changes: Partial<OneGoStuck> = {}): OneGoStuck {
  return { step: "repository", kind, reason: "Something is in the way.", ...changes };
}

function agentOf(reading: PaperAgent["steps"]["reading"]): PaperAgent {
  return {
    id: "cells",
    title: "Cells",
    created_at: "2026-01-01T00:00:00Z",
    paper: { kind: "doi", doi: "10.1/cells" },
    repo: null,
    steps: { reading, repository: "pending", environment: "pending", data: "pending", tools: "pending" },
    given: false,
    imported: null,
  } as PaperAgent;
}

describe("what is first asked of making an agent in one go", () => {
  it("is what was asked the last time, and a dollar to read the paper when nothing was", () => {
    expect(emptyOneGo(SETTINGS)).toEqual({ budget: "1", repo: "", give: true, withoutCode: false });
    expect(emptyOneGo({ ...SETTINGS, max_cost: 2.5, repo: "https://github.com/a/b", give: false, without_code: true })).toEqual({
      budget: "2.5",
      repo: "https://github.com/a/b",
      give: false,
      withoutCode: true,
    });
    expect(emptyOneGo({ ...SETTINGS, max_cost: 0 }).budget).toBe("0");
  });

  it("asks for the most to spend only while the paper is still to be read", () => {
    expect(spends(agentOf("pending"))).toBe(true);
    expect(spends(agentOf("failed"))).toBe(true);
    expect(spends(agentOf("done"))).toBe(false);
  });
});

describe("checkOneGo", () => {
  const draft = { budget: "1", repo: "", give: true, withoutCode: false };

  it("sends the most to spend, whether it is given, and whether the code is left out", () => {
    expect(checkOneGo(draft, { reads: true, asksRepo: true })).toEqual({
      value: { give: true, without_code: false, max_cost: 1 },
      problems: {},
    });
    expect(checkOneGo({ ...draft, budget: "$0.50", give: false }, { reads: true, asksRepo: false }).value).toEqual({
      give: false,
      without_code: false,
      max_cost: 0.5,
    });
  });

  it("does not ask for the most to spend once the paper has been read, whatever was typed", () => {
    expect(checkOneGo({ ...draft, budget: "lots" }, { reads: false, asksRepo: false })).toEqual({
      value: { give: true, without_code: false },
      problems: {},
    });
  });

  it("says what is wrong with the most to spend", () => {
    expect(checkOneGo({ ...draft, budget: "" }, { reads: true, asksRepo: false })).toEqual({
      value: null,
      problems: { budget: "Say the most reading the paper may spend." },
    });
    expect(checkOneGo({ ...draft, budget: "-1" }, { reads: true, asksRepo: false }).problems.budget).toBe(
      "The most reading the paper may spend is an amount in dollars, such as 1 or 0.50.",
    );
  });

  it("sends where the code is only when the agent does not say, it is given, and the code is not left out", () => {
    const repo = " https://github.com/owner/cells ";

    expect(checkOneGo({ ...draft, repo }, { reads: false, asksRepo: true }).value?.repo).toBe("https://github.com/owner/cells");
    expect(checkOneGo({ ...draft, repo }, { reads: false, asksRepo: false }).value).not.toHaveProperty("repo");
    expect(checkOneGo({ ...draft, repo, withoutCode: true }, { reads: false, asksRepo: true }).value).toEqual({ give: true, without_code: true });
    expect(checkOneGo({ ...draft, repo: "  " }, { reads: false, asksRepo: true }).value).not.toHaveProperty("repo");
  });

  it("says what is wrong with where the code is, at the hosts the server takes", () => {
    const wrong = checkOneGo({ ...draft, repo: "https://example.com/a/b" }, { reads: false, asksRepo: true, hosts: ["github.com"] });

    expect(wrong.value).toBeNull();
    expect(wrong.problems.repo).toBe("Give the address of the project, such as https://github.com/owner/name, at github.com.");
    expect(checkOneGo({ ...draft, repo: "https://example.com/a/b", withoutCode: true }, { reads: false, asksRepo: true }).problems).toEqual({});
  });

  it("says every problem at once", () => {
    expect(Object.keys(checkOneGo({ ...draft, budget: "x", repo: "nope" }, { reads: true, asksRepo: true }).problems).sort()).toEqual([
      "budget",
      "repo",
    ]);
  });
});

describe("checkMore", () => {
  it("sends how much more reading may spend, and says what is wrong with it", () => {
    expect(checkMore("2")).toEqual({ value: { max_cost: 2 }, problems: {} });
    expect(checkMore("")).toEqual({ value: null, problems: { budget: "Say how much more reading may spend." } });
    expect(checkMore("two").value).toBeNull();
  });
});

describe("decisionOf", () => {
  it("is to start it when nothing was asked, to stop it while it goes, and over when every step was got to", () => {
    expect(decisionOf(view())).toEqual({ kind: "start" });
    expect(decisionOf(view({ state: "running", stuck: stuck("code") }))).toEqual({ kind: "going" });
    expect(decisionOf(view({ state: "done" }))).toEqual({ kind: "over" });
  });

  it("is where the code is, with the places the paper points to", () => {
    const candidates = [{ url: "https://github.com/a/b", role: "code" as const, quote: "Our code is at" }];

    expect(decisionOf(view({ state: "waiting", stuck: stuck("code", { candidates }) }))).toEqual({ kind: "code", candidates });
    expect(decisionOf(view({ state: "waiting", stuck: stuck("code") }))).toEqual({ kind: "code", candidates: [] });
  });

  it("is whether to go on with the code that was looked at", () => {
    const checks = [{ title: "License", status: "warn" as const, detail: "None was found." }];

    expect(decisionOf(view({ state: "waiting", stuck: stuck("preflight", { step: "look", verdict: "ask", commit: "abc", checks }) }))).toEqual({
      kind: "preflight",
      verdict: "ask",
      commit: "abc",
      checks,
    });
    expect(decisionOf(view({ state: "waiting", stuck: stuck("preflight") }))).toEqual({ kind: "preflight", verdict: null, commit: null, checks: [] });
  });

  it("is how much more reading may spend", () => {
    expect(decisionOf(view({ state: "waiting", stuck: stuck("limit", { step: "reading", spent: 0.9, limit: 1 }) }))).toEqual({
      kind: "limit",
      spent: 0.9,
      limit: 1,
    });
    expect(decisionOf(view({ state: "waiting", stuck: stuck("limit") }))).toEqual({ kind: "limit", spent: null, limit: null });
  });

  it("is the paper's file, when it was not uploaded or its text could not be had", () => {
    expect(decisionOf(view({ state: "waiting", stuck: stuck("paper_file") }))).toEqual({ kind: "paper" });
    expect(decisionOf(view({ state: "waiting", stuck: stuck("paper_text") }))).toEqual({ kind: "paper" });
  });

  it("is to go on for what is to be put right on this machine, and when it stopped, and to try again when it failed", () => {
    for (const kind of ["docker", "git", "model"]) {
      expect(decisionOf(view({ state: "waiting", stuck: stuck(kind) }))).toEqual({ kind: "again", label: "Go on" });
    }
    expect(decisionOf(view({ state: "stopped", stuck: stuck("stopped") }))).toEqual({ kind: "again", label: "Go on" });
    expect(decisionOf(view({ state: "interrupted" }))).toEqual({ kind: "again", label: "Go on" });
    expect(decisionOf(view({ state: "failed", stuck: stuck("failed") }))).toEqual({ kind: "again", label: "Try again" });
  });

  it("does not take what a step failed with for what the person is asked", () => {
    expect(decisionOf(view({ state: "failed", stuck: stuck("code") }))).toEqual({ kind: "again", label: "Try again" });
    expect(decisionOf(view({ state: "stopped", stuck: stuck("limit") }))).toEqual({ kind: "again", label: "Go on" });
  });
});

describe("offersWithoutCode", () => {
  it("is offered where a step of the code stands in the way", () => {
    for (const step of ["repository", "look", "environment", "reference", "tools", "checks"] as const) {
      expect(offersWithoutCode(view({ state: "waiting", stuck: stuck("code", { step }) }))).toBe(true);
    }
    expect(offersWithoutCode(view({ state: "failed", stuck: stuck("failed", { step: "environment" }) }))).toBe(true);
    expect(offersWithoutCode(view({ state: "interrupted", stuck: stuck("docker", { step: "environment" }) }))).toBe(true);
  });

  it("is not offered for the paper, for giving it, once the code was left out, or when it was stopped", () => {
    expect(offersWithoutCode(view({ state: "waiting", stuck: stuck("limit", { step: "reading" }) }))).toBe(false);
    expect(offersWithoutCode(view({ state: "failed", stuck: stuck("refused", { step: "given" }) }))).toBe(false);
    expect(offersWithoutCode(view({ state: "waiting", settings: { ...SETTINGS, without_code: true }, stuck: stuck("code") }))).toBe(false);
    expect(offersWithoutCode(view({ state: "stopped", stuck: stuck("stopped", { step: "environment" }) }))).toBe(false);
    expect(offersWithoutCode(view({ state: "interrupted" }))).toBe(false);
  });

  it("is not offered when it is not stuck: going, done, or never asked for", () => {
    for (const state of ["running", "done", "none"] as const) {
      expect(offersWithoutCode(view({ state, stuck: stuck("code") }))).toBe(false);
    }
  });
});

describe("describeOneGo", () => {
  it("counts the steps that are over, and says how many of them were skipped", () => {
    const steps = view().steps.map((step, index): OneGoStep => ({
      ...step,
      state: index < 2 ? "done" : index < 4 ? "skipped" : index === 4 ? "failed" : "pending",
    }));

    expect(describeOneGo(view({ steps }))).toBe("4 of 8 steps over, of which 2 skipped");
    expect(describeOneGo(view())).toBe("0 of 8 steps over");
    expect(describeOneGo(view({ steps: [{ step: "given", title: "Give", state: "done", note: null }] }))).toBe("1 of 1 step over");
  });
});

describe("describeLimit", () => {
  it("says what reading spent of what it was given, as far as it is known", () => {
    expect(describeLimit(0.98, 1)).toBe("It spent $0.98 of the $1.00 it was given.");
    expect(describeLimit(0, null)).toBe("It spent $0.00.");
    expect(describeLimit(null, 2)).toBe("It was given $2.00.");
    expect(describeLimit(null, null)).toBeNull();
  });
});

describe("the labels", () => {
  it("name every state and every state of a step", () => {
    expect(Object.keys(ONEGO_STATE_LABELS).sort()).toEqual(["done", "failed", "interrupted", "none", "running", "stopped", "waiting"]);
    expect(Object.keys(ONEGO_STEP_LABELS).sort()).toEqual(["done", "failed", "pending", "running", "skipped", "stopped", "waiting"]);
    expect(ONEGO_STATE_LABELS.waiting).toBe("Waiting for you");
  });
});
