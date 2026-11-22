import { describe, expect, it } from "vitest";
import {
  agentFrom,
  agentOf,
  checkGiven,
  checkTitle,
  checkTriage,
  describeCodeFrom,
  describeCounts,
  describeStock,
  describeTriageSource,
  emptyTriage,
  lastTriageJob,
  orderedTriageChecks,
  TIERS,
  TRIAGE_JOB,
  triageAddress,
  triageJob,
  triageKey,
  TRIAGES_ADDRESS,
  type TriageDraft,
} from "./triages";
import type { Job, PaperAgent, TriageEntry, TriageLimits } from "./types";

const LIMITS: TriageLimits = {
  most_triages: 20,
  most_given: 3,
  most_listed: 300,
  default_listed: 50,
  most_looked_at: 40,
  default_looked_at: 20,
  default_megabytes: 50,
  min_megabytes: 5,
  max_megabytes: 200,
};

function job(changes: Partial<Job> = {}): Job {
  return {
    id: "j1",
    kind: TRIAGE_JOB,
    subject: "t1",
    title: "Looking at the code of a listing of papers",
    state: "running",
    message: "",
    progress: {},
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    finished_at: null,
    log_total: 0,
    ...changes,
  } as Job;
}

function entry(changes: Partial<TriageEntry> = {}): TriageEntry {
  return {
    rank: 1,
    position: 1,
    tier: "go",
    why: "Go: nothing in the files stands in the way of making tools from this code.",
    verdict: "go",
    doi: "10.1101/2024.01.01.000001",
    title: "A method",
    date: null,
    category: null,
    paper: { kind: "doi", doi: "10.1101/2024.01.01.000001" },
    code: "https://github.com/lab/tool",
    code_from: "person",
    other_codes: [],
    checks: [],
    tutorials: 1,
    estimate: { low: 0.01, high: 0.05, tutorials: 1 },
    stock: { commit: "0123456789abcdef0123", files: 12, bytes: 2048, languages: ["Python", "R"], license: "MIT" },
    ...changes,
  };
}

const draft = (changes: Partial<TriageDraft> = {}): TriageDraft => ({ ...emptyTriage(LIMITS), ...changes });

describe("addresses and jobs", () => {
  it("names a triage in the query, and the triages as a view", () => {
    expect(TRIAGES_ADDRESS).toBe("/papers?view=triage");
    expect(triageAddress("a b")).toBe("/papers?triage=a%20b");
  });

  it("finds the job at work on a triage, and the last that ended", () => {
    const at = job();
    const ended = job({ id: "j2", state: "succeeded" });
    const other = job({ id: "j3", subject: "t2" });
    const bakeoff = job({ id: "j4", kind: "bakeoff-run" });
    expect(triageJob([bakeoff, ended, other, at], "t1")).toBe(at);
    expect(triageJob([ended], "t1")).toBeUndefined();
    expect(triageJob(null, "t1")).toBeUndefined();
    expect(lastTriageJob([at, ended], "t1")).toBe(ended);
    expect(lastTriageJob([at], "t1")).toBeUndefined();
  });

  it("changes as triages begin and end, and not as one gets further", () => {
    const at = job();
    expect(triageKey([at], 2)).toBe("2|j1");
    expect(triageKey([job({ message: "Looking at the code of 2 of 3" })], 2)).toBe("2|j1");
    expect(triageKey([at], 3)).toBe("3|j1");
    expect(triageKey([at, job({ id: "j2", subject: "t2" })], 0, "t2")).toBe("0|j2");
    expect(triageKey([job({ state: "succeeded" }), job({ id: "j4", kind: "bakeoff-run" })], 1)).toBe("1|");
  });
});

describe("checkGiven", () => {
  it("takes a DOI a line, with the address of its code after it if there is one", () => {
    const given = checkGiven("10.1101/AAA https://github.com/lab/tool\n\n  doi:10.1234/bbb  \nhttps://doi.org/10.1234/ccc, https://gitlab.com/g/s/p\n", 10);
    expect(given).toEqual({
      value: [{ doi: "10.1101/aaa", code: "https://github.com/lab/tool" }, { doi: "10.1234/bbb" }, { doi: "10.1234/ccc", code: "https://gitlab.com/g/s/p" }],
    });
  });

  it("keeps the first of a paper given twice, and counts each paper once", () => {
    expect(checkGiven("10.1234/a https://github.com/x/one\n10.1234/A https://github.com/x/two\n10.1234/b", 2)).toEqual({
      value: [{ doi: "10.1234/a", code: "https://github.com/x/one" }, { doi: "10.1234/b" }],
    });
  });

  it("says which line is wrong, and why", () => {
    expect(checkGiven("10.1234/a\nnot-a-doi", 10).problem).toBe("Line 2: not-a-doi is not a DOI, such as 10.1101/2024.01.01.123456.");
    expect(checkGiven("10.1234/a https://example.com/x/y", 10).problem).toContain("Line 1: https://example.com/x/y is not the address of a project's code");
    expect(checkGiven("10.1234/a http://github.com/x/y", 10).problem).toContain("is not the address");
    expect(checkGiven("10.1234/a https://github.com/x/y extra", 10).problem).toBe("Line 1 has more than a DOI and the address of its code.");
    expect(checkGiven("10.1234/a https://github.com/x/y extra", 10).value).toEqual([]);
  });

  it("takes no more papers than the server does", () => {
    expect(checkGiven("10.1234/a\n10.1234/b\n10.1234/c", 3).problem).toBeUndefined();
    expect(checkGiven("10.1234/a\n10.1234/b\n10.1234/c\n10.1234/d", 3).problem).toBe("At most 3 papers can be given, and these are 4.");
  });

  it("takes only the hosts it is told of", () => {
    expect(checkGiven("10.1234/a https://codeberg.org/x/y", 10, ["github.com"]).problem).toContain("is not the address");
  });
});

describe("checkTriage", () => {
  it("starts from what the server says", () => {
    expect(emptyTriage(LIMITS)).toEqual({
      papers: "",
      listing: false,
      since: "",
      until: "",
      subject: "all",
      limit: "50",
      lookedAt: "20",
      megabytes: "50",
    });
  });

  it("asks for papers, a listing, or both", () => {
    expect(checkTriage(draft(), LIMITS)).toEqual({ value: null, problems: { form: "Give papers to look at, list the preprints of bioRxiv, or both." } });
    expect(checkTriage(draft({ papers: "\n  \n" }), LIMITS).problems.form).toBeDefined();
  });

  it("sends the papers given, and what is looked at", () => {
    expect(checkTriage(draft({ papers: "10.1234/a", lookedAt: "3", megabytes: "5" }), LIMITS)).toEqual({
      value: { papers: [{ doi: "10.1234/a" }], most_looked_at: 3, max_megabytes: 5 },
      problems: {},
    });
  });

  it("sends a listing, and the papers too if there are any", () => {
    expect(checkTriage(draft({ listing: true, since: "2024-01-01", until: "2024-01-07", subject: "genomics", limit: "300" }), LIMITS).value).toEqual({
      listing: { since: "2024-01-01", until: "2024-01-07", subject: "genomics", limit: 300 },
      most_looked_at: 20,
      max_megabytes: 50,
    });
    expect(checkTriage(draft({ papers: "10.1234/a", listing: true, since: "2024-01-01" }), LIMITS).value).toEqual({
      papers: [{ doi: "10.1234/a" }],
      listing: { since: "2024-01-01", subject: "all", limit: 50 },
      most_looked_at: 20,
      max_megabytes: 50,
    });
  });

  it("says what is wrong with a listing", () => {
    expect(checkTriage(draft({ listing: true }), LIMITS).problems).toEqual({ since: "Say the first day, as a date." });
    expect(checkTriage(draft({ listing: true, since: "2024-01-08", until: "2024-01-07" }), LIMITS).problems).toEqual({
      until: "The last day is before the first.",
    });
    expect(checkTriage(draft({ listing: true, since: "2024-01-07", until: "2024-01-07" }), LIMITS).problems).toEqual({});
    expect(checkTriage(draft({ listing: true, since: "2024-01-01", until: "2024-02-30" }), LIMITS).problems.until).toBe(
      "Say the last day, as a date, or leave it blank.",
    );
    expect(checkTriage(draft({ listing: true, since: "2024-01-01", limit: "301" }), LIMITS).problems.limit).toBe(
      "The number of preprints is a whole number from 1 to 300.",
    );
    expect(checkTriage(draft({ listing: true, since: "2024-01-01", limit: "0" }), LIMITS).problems.limit).toBeDefined();
  });

  it("leaves a listing out that is not asked for, even if it was typed", () => {
    expect(checkTriage(draft({ papers: "10.1234/a", since: "nonsense", limit: "x" }), LIMITS).value?.listing).toBeUndefined();
  });

  it("says what is wrong with how much is looked at", () => {
    const wrong = checkTriage(draft({ papers: "10.1234/a", lookedAt: "41", megabytes: "4" }), LIMITS);
    expect(wrong.value).toBeNull();
    expect(wrong.problems).toEqual({
      lookedAt: "The most papers whose code is looked at is a whole number from 1 to 40.",
      megabytes: "The most that is fetched of one project is a whole number from 5 to 200, in megabytes.",
    });
    expect(checkTriage(draft({ papers: "10.1234/a", lookedAt: "0" }), LIMITS).problems.lookedAt).toBeDefined();
    expect(checkTriage(draft({ papers: "10.1234/a", megabytes: "201" }), LIMITS).problems.megabytes).toBeDefined();
    expect(checkTriage(draft({ papers: "10.1234/a", lookedAt: "40", megabytes: "200" }), LIMITS).problems).toEqual({});
  });

  it("does not ask for papers when what was typed of them is wrong", () => {
    expect(checkTriage(draft({ papers: "nope" }), LIMITS).problems).toEqual({
      papers: "Line 1: nope is not a DOI, such as 10.1101/2024.01.01.123456.",
    });
  });
});

describe("describing a triage", () => {
  it("says where its papers came from", () => {
    expect(describeTriageSource({ papers: 2, listing: null })).toBe("2 papers given");
    expect(describeTriageSource({ papers: 1, listing: { since: "2024-01-01", until: null, subject: "all", limit: 100 } })).toBe(
      "1 paper given and up to 100 bioRxiv preprints posted from 2024-01-01 on",
    );
    expect(describeTriageSource({ papers: 0, listing: { since: "2024-01-01", until: "2024-01-07", subject: "genomics", limit: 5 } })).toBe(
      "Up to 5 bioRxiv preprints in genomics posted from 2024-01-01 to 2024-01-07",
    );
    expect(describeTriageSource({ papers: 0, listing: { since: "2024-01-01", until: "2024-01-01", subject: "all", limit: 5 } })).toBe(
      "Up to 5 bioRxiv preprints posted on 2024-01-01",
    );
    expect(describeTriageSource({ papers: 0, listing: null })).toBe("No papers");
  });

  it("counts the papers of each tier, leaving out those with none", () => {
    expect(describeCounts({ papers: 4, go: 1, ask: 0, "no-go": 1, not_looked_at: 0, no_code: 2 })).toBe("4 papers: 1 go, 1 no-go, 2 no code found");
    expect(describeCounts({ papers: 0, go: 0, ask: 0, "no-go": 0, not_looked_at: 0, no_code: 0 })).toBe("0 papers");
    expect(TIERS).toEqual(["go", "ask", "no-go", "not_looked_at", "no_code"]);
  });

  it("says what was found of the code", () => {
    expect(describeStock(entry().stock!)).toBe("Python, R · License: MIT · 12 files, 2.0 KB · at 0123456789ab");
    expect(describeStock({ commit: "abc", files: 1, bytes: 0, languages: [], license: null })).toBe("No language found · No license found · 1 file, 0 B · at abc");
    expect(describeCodeFrom(entry())).toBe("the address you gave");
    expect(describeCodeFrom(entry({ code_from: "abstract" }))).toBe("the first address in its abstract");
    expect(describeCodeFrom(entry({ code_from: null }))).toBeNull();
  });

  it("names each check, and puts them in the order they are weighed in", () => {
    expect(checkTitle({ id: "gpu" })).toBe("It runs without a GPU");
    expect(checkTitle({ id: "something-new" })).toBe("something-new");
    const checks = orderedTriageChecks([
      { id: "a", status: "ok", detail: "" },
      { id: "b", status: "block", detail: "" },
      { id: "c", status: "note", detail: "" },
      { id: "d", status: "warn", detail: "" },
      { id: "e", status: "unknown", detail: "" },
    ]);
    expect(checks.map((check) => check.id)).toEqual(["b", "d", "e", "c", "a"]);
  });
});

describe("agents of triaged papers", () => {
  const agent = (id: string, paper: PaperAgent["paper"]) => ({ id, paper }) as PaperAgent;

  it("finds the agent of a paper by its DOI, in any case", () => {
    const agents = [
      agent("u", { kind: "url", url: "https://example.org/10.1234/a" } as PaperAgent["paper"]),
      agent("d", { kind: "doi", doi: "10.1234/a" } as PaperAgent["paper"]),
    ];
    expect(agentOf(agents, "10.1234/A")?.id).toBe("d");
    expect(agentOf(agents, "10.1234/b")).toBeUndefined();
    expect(agentOf(agents, null)).toBeUndefined();
  });

  it("makes an agent of the paper with the code the triage found, called by its title", () => {
    expect(agentFrom(entry())).toEqual({
      title: "A method",
      paper: { kind: "doi", doi: "10.1101/2024.01.01.000001" },
      repo: "https://github.com/lab/tool",
    });
    expect(agentFrom(entry({ code: null }))).toEqual({ title: "A method", paper: { kind: "doi", doi: "10.1101/2024.01.01.000001" } });
    expect(agentFrom(entry({ paper: null }))).toBeNull();
    expect(agentFrom(entry({ title: "  " }))?.title).toBe("10.1101/2024.01.01.000001");
    const long = agentFrom(entry({ title: `${"é".repeat(199)}  ${"x".repeat(100)}` }))!.title;
    expect([...long].length).toBe(199);
    expect(agentFrom(entry({ title: "x".repeat(250) }))!.title).toBe("x".repeat(200));
  });
});
