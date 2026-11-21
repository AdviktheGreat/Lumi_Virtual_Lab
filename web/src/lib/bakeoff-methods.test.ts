import { describe, expect, it } from "vitest";
import {
  buildableCount,
  canGoOn,
  checkMethod,
  checkMethodChange,
  checkSearches,
  describeBuildAll,
  describeDropped,
  describeFound,
  describeFullText,
  describeMethodPaper,
  describeShortlist,
  describeStanding,
  describeStep,
  EMPTY_METHOD,
  isAsking,
  isBuildable,
  lastBakeoffJob,
  MAX_SEARCH_CHARS,
  MAX_SEARCH_TYPED,
  MAX_SEARCH_WORDS,
  methodDraftOf,
  methodPaperLink,
  plainSearch,
  pointedTo,
  scopeViewOf,
  type MethodDraft,
} from "./bakeoff-methods";
import type { BakeoffFound, BakeoffMethod, BakeoffScope, BakeoffShortlist, BakeoffStanding, Job } from "./types";

const LIMITS = { max_name_chars: 200 };
const SEARCHES = { max_queries: 3 };

function job(changes: Partial<Job> = {}): Job {
  return {
    id: "j1",
    kind: "bakeoff-build",
    subject: "b1",
    title: "Building",
    state: "succeeded",
    message: "",
    progress: { finished: 1, total: 3 },
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    finished_at: "2026-01-01T00:01:00Z",
    log_total: 0,
    ...changes,
  } as Job;
}

const NOT_CHECKED: BakeoffScope = {
  checked: false,
  why: "no_description",
  reason: "Nothing has been said of what the data is.",
  outcome: null,
  of: [],
  not_checked: [],
  warnings: [],
  card: null,
  reading: null,
  notes: [],
  key: null,
  went_on: false,
  went_on_at: null,
};

const CHECKED: BakeoffScope = {
  ...NOT_CHECKED,
  checked: true,
  why: null,
  reason: "",
  outcome: "outside",
  warnings: ["The card says mouse, and your data is human."],
  card: { status: "draft", approved_at: null, changed_since_approval: false, edited: false, scope_facts: 2 },
  reading: { complete: true, chunks: 4, read: 4, failed: 0 },
  key: "abc123",
};

function method(changes: Partial<BakeoffMethod> = {}): BakeoffMethod {
  return {
    id: "m1",
    name: "Scanpy",
    paper: { kind: "doi", doi: "10.1186/s13059-017-1382-0" },
    title: "",
    repo: null,
    suggested: [],
    added_by: "person",
    added_at: "2026-01-01T00:00:00Z",
    found: null,
    fit: null,
    agent: null,
    standing: { state: "new", step: null, reason: "" },
    scope: NOT_CHECKED,
    ...changes,
  };
}

const standing = (state: BakeoffStanding["state"], changes: Partial<BakeoffStanding> = {}): BakeoffStanding => ({
  state,
  step: null,
  reason: "",
  ...changes,
});

describe("lastBakeoffJob", () => {
  it("is the latest job on the bake-off that is over, of the kinds that work on a bake-off", () => {
    const jobs = [job({ id: "a", state: "running" }), job({ id: "b", kind: "bakeoff-shortlist" }), job({ id: "c" })];
    expect(lastBakeoffJob(jobs, "b1")?.id).toBe("b");
  });

  it("is not a job at work, another bake-off's, or another kind's", () => {
    expect(lastBakeoffJob([job({ state: "running" })], "b1")).toBeUndefined();
    expect(lastBakeoffJob([job({ state: "stopping" })], "b1")).toBeUndefined();
    expect(lastBakeoffJob([job({ subject: "b2" })], "b1")).toBeUndefined();
    expect(lastBakeoffJob([job({ kind: "paperagent-reading" })], "b1")).toBeUndefined();
    expect(lastBakeoffJob(null, "b1")).toBeUndefined();
  });

  it("takes a job that failed or was stopped as the last one", () => {
    expect(lastBakeoffJob([job({ state: "failed" })], "b1")?.state).toBe("failed");
    expect(lastBakeoffJob([job({ state: "stopped" })], "b1")?.state).toBe("stopped");
  });
});

describe("a method's paper", () => {
  it("is said by its DOI or its link, and is read at doi.org or at the link", () => {
    expect(describeMethodPaper({ kind: "doi", doi: "10.1/x" })).toBe("DOI 10.1/x");
    expect(describeMethodPaper({ kind: "url", url: "https://arxiv.org/abs/1" })).toBe("https://arxiv.org/abs/1");
    expect(methodPaperLink({ kind: "doi", doi: "10.1/x" })).toBe("https://doi.org/10.1/x");
    expect(methodPaperLink({ kind: "url", url: "https://arxiv.org/abs/1" })).toBe("https://arxiv.org/abs/1");
  });
});

describe("checkMethod", () => {
  const typed = (changes: Partial<MethodDraft>): MethodDraft => ({ ...EMPTY_METHOD, paper: "10.1186/s13059-017-1382-0", ...changes });

  it("sends a DOI as a DOI, in lower case and without what a link to it begins with", () => {
    expect(checkMethod(typed({ paper: "  DOI: 10.1186/S13059-017-1382-0 " }), LIMITS).value).toEqual({
      paper: { kind: "doi", doi: "10.1186/s13059-017-1382-0" },
    });
    expect(checkMethod(typed({ paper: "https://doi.org/10.1186/s13059-017-1382-0" }), LIMITS).value?.paper).toEqual({
      kind: "doi",
      doi: "10.1186/s13059-017-1382-0",
    });
  });

  it("sends a link as a link", () => {
    expect(checkMethod(typed({ paper: " https://arxiv.org/abs/2101.00001 " }), LIMITS).value).toEqual({
      paper: { kind: "url", url: "https://arxiv.org/abs/2101.00001" },
    });
  });

  it("sends the name once it is tidied, and the code if it is said, and leaves out what is blank", () => {
    expect(checkMethod(typed({ name: "  Scanpy   2 ", repo: " https://github.com/scverse/scanpy " }), LIMITS).value).toEqual({
      paper: { kind: "doi", doi: "10.1186/s13059-017-1382-0" },
      name: "Scanpy 2",
      repo: "https://github.com/scverse/scanpy",
    });
    expect(checkMethod(typed({ name: "   ", repo: "  " }), LIMITS).value).toEqual({ paper: { kind: "doi", doi: "10.1186/s13059-017-1382-0" } });
  });

  it("says what is wrong with a paper that is blank, not a DOI, not a link, or a link to doi.org that holds no DOI", () => {
    expect(checkMethod(typed({ paper: "" }), LIMITS).problems.paper).toMatch(/DOI of its paper/);
    expect(checkMethod(typed({ paper: "scanpy" }), LIMITS).problems.paper).toMatch(/DOI, such as/);
    expect(checkMethod(typed({ paper: "ftp://x.org/a" }), LIMITS).problems.paper).toMatch(/begins with http/);
    expect(checkMethod(typed({ paper: "https://doi.org/not-a-doi" }), LIMITS).problems.paper).toMatch(/no DOI in it/);
    expect(checkMethod(typed({ paper: "https://dx.doi.org/" }), LIMITS).value).toBeNull();
    expect(checkMethod(typed({ paper: "https://doi.org.evil.example/paper" }), LIMITS).value?.paper).toEqual({
      kind: "url",
      url: "https://doi.org.evil.example/paper",
    });
  });

  it("holds a name to the most that the server takes, counted as it counts, and a code address to a project", () => {
    expect(checkMethod(typed({ name: "x".repeat(200) }), LIMITS).value).not.toBeNull();
    expect(checkMethod(typed({ name: "x".repeat(201) }), LIMITS).problems.name).toMatch(/at most 200 characters, and this is 201/);
    expect(checkMethod(typed({ name: "😀".repeat(200) }), LIMITS).value).not.toBeNull();
    expect(checkMethod(typed({ repo: "https://example.com/a/b" }), LIMITS).problems.repo).toMatch(/github.com/);
    expect(checkMethod(typed({ repo: "https://github.com/onlyowner" }), LIMITS).value).toBeNull();
  });

  it("asks for a paper where nothing was typed", () => {
    expect(checkMethod(EMPTY_METHOD, LIMITS)).toEqual({ value: null, problems: { paper: expect.stringMatching(/DOI of its paper/) } });
  });

  it("says every problem at once, and sends nothing", () => {
    const checked = checkMethod({ paper: "no", name: "x".repeat(300), repo: "no" }, LIMITS);
    expect(checked.value).toBeNull();
    expect(Object.keys(checked.problems).sort()).toEqual(["name", "paper", "repo"]);
  });
});

describe("checkMethodChange", () => {
  const was = method({ repo: "https://github.com/a/b" });

  it("says nothing of what is as it was", () => {
    expect(checkMethodChange(methodDraftOf(was), was, LIMITS).value).toEqual({});
    expect(checkMethodChange({ name: "  Scanpy ", repo: " https://github.com/a/b " }, was, LIMITS).value).toEqual({});
  });

  it("says what differs: the name, the code, or both", () => {
    expect(checkMethodChange({ name: "Other", repo: "https://github.com/a/b" }, was, LIMITS).value).toEqual({ name: "Other" });
    expect(checkMethodChange({ name: "Scanpy", repo: "https://github.com/c/d" }, was, LIMITS).value).toEqual({ repo: "https://github.com/c/d" });
    expect(checkMethodChange({ name: "Other", repo: "https://github.com/c/d" }, was, LIMITS).value).toEqual({
      name: "Other",
      repo: "https://github.com/c/d",
    });
  });

  it("takes the code away by saying an empty address, and says nothing of code that was not there", () => {
    expect(checkMethodChange({ name: "Scanpy", repo: "  " }, was, LIMITS).value).toEqual({ repo: "" });
    expect(checkMethodChange({ name: "Scanpy", repo: "" }, method(), LIMITS).value).toEqual({});
  });

  it("holds a name to being there and not too long, and the code to a project", () => {
    expect(checkMethodChange({ name: "  ", repo: "" }, was, LIMITS).problems.name).toMatch(/what it is called/);
    expect(checkMethodChange({ name: "x".repeat(201), repo: "" }, was, LIMITS).problems.name).toMatch(/at most 200/);
    expect(checkMethodChange({ name: "Scanpy", repo: "nope" }, was, LIMITS).problems.repo).toMatch(/github.com/);
    expect(checkMethodChange({ name: "", repo: "nope" }, was, LIMITS).value).toBeNull();
  });

  it("shows a method as it is, with no code as blank", () => {
    expect(methodDraftOf(method())).toEqual({ name: "Scanpy", repo: "" });
    expect(methodDraftOf(was)).toEqual({ name: "Scanpy", repo: "https://github.com/a/b" });
  });
});

describe("where a method stands", () => {
  it("is called what it is, with the step it is at in words", () => {
    expect(describeStanding(standing("built"))).toEqual({ label: "Built", step: null });
    expect(describeStanding(standing("waiting", { step: "preflight" }))).toEqual({ label: "Waiting for you", step: "Looking at its code" });
    expect(describeStanding(standing("failed", { step: "paper" }))).toEqual({ label: "Went wrong", step: "Reading its paper" });
    expect(describeStanding(standing("blocked", { step: "unheard-of" }))).toEqual({ label: "Cannot be built", step: "Unheard-of" });
  });

  it("names the steps that building has, in the words that the server says them in", () => {
    expect(["agent", "code", "paper", "preflight", "environment", "tutorials", "tools"].map(describeStep)).toEqual([
      "finding its PaperAgent",
      "fetching its code",
      "reading its paper",
      "looking at its code",
      "building its environment",
      "running its tutorials",
      "making its tools",
    ]);
  });

  it("may be built unless it is built or is being built", () => {
    for (const state of ["new", "waiting", "blocked", "failed", "pending"] as const) expect(isBuildable({ standing: standing(state) })).toBe(true);
    for (const state of ["built", "building"] as const) expect(isBuildable({ standing: standing(state) })).toBe(false);
    expect(buildableCount([{ standing: standing("built") }, { standing: standing("new") }, { standing: standing("failed") }])).toBe(2);
    expect(buildableCount([])).toBe(0);
  });

  it("is asking only if it is waiting for the person to go on after its code was looked at", () => {
    expect(isAsking({ standing: standing("waiting", { why: "ask" }) })).toBe(true);
    expect(isAsking({ standing: standing("waiting", { why: "choose_code" }) })).toBe(false);
    expect(isAsking({ standing: standing("blocked", { why: "ask" }) })).toBe(false);
    expect(isAsking({ standing: standing("waiting") })).toBe(false);
  });

  it("says what the button that builds them all says", () => {
    expect(describeBuildAll(0, 3)).toBe("All are built");
    expect(describeBuildAll(0, 0)).toBe("All are built");
    expect(describeBuildAll(1, 1)).toBe("Build it");
    expect(describeBuildAll(3, 3)).toBe("Build all");
    expect(describeBuildAll(1, 3)).toBe("Build the one that is not built");
    expect(describeBuildAll(2, 3)).toBe("Build the 2 that are not built");
  });
});

describe("the code that a paper points to", () => {
  it("is offered only while the person has not said where the code is", () => {
    expect(pointedTo({ repo: null, suggested: ["https://github.com/a/b"] })).toEqual(["https://github.com/a/b"]);
    expect(pointedTo({ repo: "https://github.com/c/d", suggested: ["https://github.com/a/b"] })).toEqual([]);
    expect(pointedTo({ repo: null, suggested: [] })).toEqual([]);
  });
});

describe("a method's scope", () => {
  it("is shown as an answer of a scope check once it was put against a card", () => {
    const view = scopeViewOf({ ...CHECKED, of: [], notes: ["a note"] });
    expect(view).toMatchObject({ outcome: "outside", aspects: [], warnings: CHECKED.warnings, notes: ["a note"], not_checked: [] });
    expect(view?.card.scope_facts).toBe(2);
    expect(view?.reading.chunks).toBe(4);
  });

  it("is not shown as one where it was not put against a card, whatever else it says", () => {
    expect(scopeViewOf(NOT_CHECKED)).toBeNull();
    expect(scopeViewOf({ ...CHECKED, checked: false })).toBeNull();
    expect(scopeViewOf({ ...CHECKED, outcome: null })).toBeNull();
    expect(scopeViewOf({ ...CHECKED, card: null })).toBeNull();
    expect(scopeViewOf({ ...CHECKED, reading: null })).toBeNull();
  });

  it("may be gone on with only where it is outside, it has a key, and the person has not said so", () => {
    expect(canGoOn(CHECKED)).toBe(true);
    expect(canGoOn({ ...CHECKED, went_on: true })).toBe(false);
    expect(canGoOn({ ...CHECKED, outcome: "inside" })).toBe(false);
    expect(canGoOn({ ...CHECKED, outcome: "not covered" })).toBe(false);
    expect(canGoOn({ ...CHECKED, key: null })).toBe(false);
    expect(canGoOn({ ...CHECKED, checked: false })).toBe(false);
    expect(canGoOn(NOT_CHECKED)).toBe(false);
  });
});

describe("where a method was found", () => {
  const found: BakeoffFound = {
    source: "europepmc",
    url: "https://europepmc.org/article/MED/1",
    credit: "Wolf et al.",
    venue: "Genome Biology",
    year: 2018,
    cited_by: 3000,
    preprint: false,
    full_text: true,
  };

  it("says the service, the journal and year, how often it is cited, and whether it is a preprint", () => {
    expect(describeFound(found)).toBe("Europe PMC, Genome Biology, 2018, cited 3000 times");
    expect(describeFound({ ...found, cited_by: 1 })).toBe("Europe PMC, Genome Biology, 2018, cited 1 time");
    expect(describeFound({ ...found, cited_by: 0, preprint: true })).toMatch(/^Europe PMC, Genome Biology, 2018, a preprint, which has not been peer reviewed/);
    expect(describeFound({ ...found, source: "arxiv", venue: "q-bio.GN", year: null, cited_by: 0 })).toBe("arXiv, q-bio.GN");
    expect(describeFound({ ...found, source: "somewhere", venue: "", year: 2020, cited_by: 0 })).toBe("somewhere, 2020");
    expect(describeFound({ ...found, venue: "", year: null, cited_by: 0 })).toBe("Europe PMC");
  });

  it("warns that reading may fail only where Europe PMC says it does not hold the full text", () => {
    expect(describeFullText({ ...found, full_text: false })).toMatch(/does not hold its full text/);
    expect(describeFullText(found)).toBeNull();
    expect(describeFullText({ ...found, source: "arxiv", full_text: null })).toBeNull();
  });
});

describe("searches", () => {
  it("are made plain as the server makes them: words only, with no operators, and the first few", () => {
    expect(plainSearch('  "single-cell" AND (clustering OR   annotation)  ')).toBe("single-cell clustering annotation");
    expect(plainSearch("not and or andnot")).toBe("");
    expect(plainSearch("One two three four five six seven eight nine ten")).toBe("One two three four five six seven eight");
    expect(plainSearch("año 日本語 café")).toBe("año 日本語 café");
    expect(plainSearch("snake_case")).toBe("snake case");
    expect(plainSearch("a-b-c d--e")).toBe("a-b-c d e");
    expect(plainSearch("!!! ???")).toBe("");
    expect(MAX_SEARCH_WORDS).toBe(8);
  });

  it("do not end in a space where they are cut in the middle of the space between two words", () => {
    const search = plainSearch(`${"x".repeat(MAX_SEARCH_CHARS - 1)} yy`);
    expect(search).toBe("x".repeat(MAX_SEARCH_CHARS - 1));
  });

  it("are no longer than the server keeps", () => {
    const long = Array.from({ length: 8 }, () => "x".repeat(30)).join(" ");
    expect([...plainSearch(long)].length).toBeLessThanOrEqual(MAX_SEARCH_CHARS);
    expect(plainSearch(long)).toBe(long.slice(0, MAX_SEARCH_CHARS).trim());
  });

  it("are not sent where none was typed, so that a model writes them", () => {
    expect(checkSearches("", SEARCHES)).toEqual({ value: null, problems: {} });
    expect(checkSearches("  \n \r\n\t ", SEARCHES)).toEqual({ value: null, problems: {} });
  });

  it("are sent a line for each, as the server makes them, and once", () => {
    expect(checkSearches("cell type annotation\nSINGLE-cell AND clustering\r\n  Cell  Type annotation \n", SEARCHES).value).toEqual([
      "cell type annotation",
      "SINGLE-cell clustering",
    ]);
  });

  it("are held to the most that the server takes, counted after the same ones are taken once", () => {
    expect(checkSearches("a\nb\nc", SEARCHES).value).toEqual(["a", "b", "c"]);
    expect(checkSearches("a\nb\nc\nd", SEARCHES).problems.searches).toMatch(/At most 3 searches.*these are 4/);
    expect(checkSearches("a\nb\nc\nd", SEARCHES).value).toBeNull();
    expect(checkSearches("a\nb\nc\nA", SEARCHES).value).toEqual(["a", "b", "c"]);
    expect(checkSearches("a\nb", { max_queries: 1 }).problems.searches).toMatch(/At most one search, a line/);
  });

  it("say which has no word to look for, or is too long to be sent", () => {
    expect(checkSearches("cells\nAND OR", SEARCHES).problems.searches).toMatch(/"AND OR" has no word/);
    expect(checkSearches("cells\nAND OR", SEARCHES).value).toBeNull();
    expect(checkSearches("x".repeat(MAX_SEARCH_TYPED + 1), SEARCHES).problems.searches).toMatch(/at most 400 characters/);
    expect(checkSearches("x".repeat(MAX_SEARCH_TYPED + 1), SEARCHES).value).toBeNull();
    expect(checkSearches("x".repeat(MAX_SEARCH_TYPED), SEARCHES).problems.searches).toBeUndefined();
  });
});

describe("what finding methods came to", () => {
  const shortlist: BakeoffShortlist = {
    started_at: "2026-01-01T00:00:00Z",
    finished_at: "2026-01-01T00:01:00Z",
    model: "some/model",
    written_by: "model",
    queries: ["cell type annotation"],
    found: 25,
    total: 60,
    chosen: 4,
    added: 3,
    dropped: { not_shown: 0, twice: 0, quote: 0, more: 0, already: 0, no_room: 0 },
    notes: [],
    complete: true,
    note: null,
    cost: 0.0123,
  };

  it("says why choices were thrown away, for those that were", () => {
    expect(describeDropped(shortlist.dropped)).toEqual([]);
    expect(describeDropped({ ...shortlist.dropped, quote: 2, already: 1 })).toEqual([
      "2 choices whose quoted words are not in the abstract",
      "1 method already in the running",
    ]);
    expect(describeDropped({ not_shown: 1, twice: 2, quote: 3, more: 4, already: 5, no_room: 6 })).toHaveLength(6);
  });

  it("says who wrote the searches, what they found, what was chosen and added, and what it cost", () => {
    const lines = describeShortlist(shortlist);
    expect(lines).toEqual([
      "The searches were written by some/model.",
      "25 papers were shown to some/model, of the 60 that the searches found.",
      "4 chosen, 3 added to the methods.",
      "It spent $0.01.",
    ]);
  });

  it("says when the searches were the person's, when all that were found were shown, and what stopped it", () => {
    const lines = describeShortlist({ ...shortlist, written_by: "person", found: 1, total: 1, dropped: { ...shortlist.dropped, quote: 1 }, note: "The limit was reached." });
    expect(lines[0]).toBe("The searches were yours.");
    expect(lines[1]).toBe("1 paper was shown to some/model.");
    expect(lines).toContain("Thrown away: 1 choice whose quoted words are not in the abstract.");
    expect(lines).toContain("The limit was reached.");
  });
});
