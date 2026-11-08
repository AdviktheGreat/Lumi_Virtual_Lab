import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import {
  agentAddress,
  checkAgent,
  checkReading,
  describeAnchor,
  describeLeftOut,
  describeLength,
  describePaper,
  describeReading,
  describeSteps,
  doiOf,
  EMPTY_AGENT,
  EMPTY_READING,
  existingOf,
  factCount,
  factGroups,
  hasReading,
  isLink,
  isRepo,
  lastReadingJob,
  paperFile,
  paperLink,
  readingJob,
  readingKey,
  readThrough,
  repoName,
  repoProblem,
  titleProblem,
  type AgentDraft,
} from "./paperagents";
import type { Job, PaperAgent, PaperAgentReading, ReadAnchor } from "./types";

const draft = (part: Partial<AgentDraft>): AgentDraft => ({ ...EMPTY_AGENT, ...part });

function agent(steps: Partial<PaperAgent["steps"]> = {}): PaperAgent {
  return {
    id: "cells",
    title: "Cells",
    created_at: "2026-01-01T00:00:00Z",
    paper: { kind: "doi", doi: "10.1038/s41586-020-2649-2" },
    repo: null,
    steps: { reading: "pending", repository: "pending", environment: "pending", data: "pending", tools: "pending", ...steps },
  };
}

describe("a DOI that is typed", () => {
  it("is taken in lower case, without what a link to it begins with", () => {
    expect(doiOf("10.1038/S41586-020-2649-2")).toBe("10.1038/s41586-020-2649-2");
    expect(doiOf("  doi: 10.1038/abc  ")).toBe("10.1038/abc");
    expect(doiOf("https://doi.org/10.1038/abc")).toBe("10.1038/abc");
    expect(doiOf("HTTP://dx.doi.org/10.1038/abc")).toBe("10.1038/abc");
  });

  it("is refused if it is not one", () => {
    for (const text of ["", "doi", "11.1038/abc", "10.1/abc", "10.1038/", "10.1038/a b", `10.1038/${"a".repeat(200)}`]) {
      expect(doiOf(text)).toBeNull();
    }
  });
});

describe("a link that is typed", () => {
  it("leads somewhere by http or https, with no name and password in it", () => {
    expect(isLink("https://example.org/paper.pdf")).toBe(true);
    expect(isLink(" http://example.org ")).toBe(true);
    // `new URL` takes http:/host and http:host, which the server does not
    for (const text of [
      "",
      "example.org",
      "ftp://example.org",
      "javascript:alert(1)",
      "https://u:p@example.org",
      "https://a b.org",
      "https://",
      "http:/example.org",
      "http:example.org",
    ]) {
      expect(isLink(text)).toBe(false);
    }
    expect(isLink(`https://example.org/${"a".repeat(2000)}`)).toBe(false);
  });
});

describe("the address of code that is typed", () => {
  it("is a project at a host that holds code", () => {
    expect(isRepo("https://github.com/owner/name")).toBe(true);
    expect(isRepo("https://www.GitHub.com/owner/name/tree/main")).toBe(true);
    expect(isRepo("https://gitlab.com/group/sub/name")).toBe(true);
    for (const text of [
      "http://github.com/owner/name",
      "https://github.com/owner",
      "https://github.com/owner/../name",
      "https://example.org/owner/name",
      "github.com/owner/name",
    ]) {
      expect(isRepo(text)).toBe(false);
    }
  });

  it("is cut to the project as the server cuts it, and is refused for what the server refuses", () => {
    expect(isRepo("https://gitlab.com/group/sub/name/-/tree/main")).toBe(true);
    expect(isRepo("https://github.com/owner/name.git")).toBe(true);
    expect(isRepo("https://github.com/owner/name/tree/main/src")).toBe(true);
    for (const text of [
      "https://gitlab.com/-/name/page",
      "https://gitlab.com/group/-/page",
      "https://github.com/owner/na%2Fme",
      "https://github.com/owner/na@me",
      "https://github.com/owner/na%ZZ",
      "https://github.com/owner/.git",
      "https://github.com:443@evil.example/owner/name",
    ]) {
      expect(isRepo(text)).toBe(false);
    }
  });

  it("may be left blank, and is otherwise told what is wanted", () => {
    expect(repoProblem("")).toBeNull();
    expect(repoProblem("  ")).toBeNull();
    expect(repoProblem("https://github.com/owner/name")).toBeNull();
    expect(repoProblem("nope")).toContain("github.com");
    expect(repoProblem("https://example.org/a/b", ["example.org"])).toBeNull();
  });

  it("is named by its owner and name", () => {
    expect(repoName("https://github.com/owner/name/")).toBe("owner/name");
    expect(repoName("not a link")).toBe("not a link");
  });
});

describe("a title that is typed", () => {
  it("is needed only where it cannot be made of the DOI or the link", () => {
    expect(titleProblem("", true)).not.toBeNull();
    expect(titleProblem("  \n ", true)).not.toBeNull();
    expect(titleProblem("", false)).toBeNull();
    expect(titleProblem("A title", true)).toBeNull();
  });

  it("is at most as long as the server takes", () => {
    expect(titleProblem("a".repeat(200), true)).toBeNull();
    expect(titleProblem("a".repeat(201), true)).toContain("201");
  });
});

describe("an agent that is asked for", () => {
  it("is of a DOI, in the form the server takes", () => {
    const checked = checkAgent(draft({ kind: "doi", doi: " https://doi.org/10.1038/ABC ", title: "  A  paper " }));

    expect(checked.problems).toEqual({});
    expect(checked.value).toEqual({ title: "A paper", paper: { kind: "doi", doi: "10.1038/abc" } });
  });

  it("is of a link, and says where its code is, if it does", () => {
    const checked = checkAgent(draft({ kind: "url", url: " https://example.org/p ", repo: " https://github.com/owner/name " }));

    expect(checked.value).toEqual({
      title: "",
      paper: { kind: "url", url: "https://example.org/p" },
      repo: "https://github.com/owner/name",
    });
  });

  it("is told of a link to doi.org that holds no DOI, which the server refuses", () => {
    expect(checkAgent(draft({ kind: "url", url: "https://doi.org/nothing" })).problems.url).toContain("no DOI");
    expect(checkAgent(draft({ kind: "url", url: "https://dx.doi.org/" })).problems.url).toContain("no DOI");
    expect(checkAgent(draft({ kind: "url", url: "https://doi.org/10.1038/ABC" })).problems).toEqual({});
    expect(checkAgent(draft({ kind: "url", url: "https://doi.org.example.org/p" })).problems).toEqual({});
  });

  it("is of a file, which is uploaded afterward, and is then given a title", () => {
    expect(checkAgent(draft({ kind: "file", title: "Mine" })).value).toEqual({ title: "Mine", paper: { kind: "file" } });
    expect(checkAgent(draft({ kind: "file" })).problems.title).toBeDefined();
  });

  it("is told what is wrong, and then has no value", () => {
    const checked = checkAgent(draft({ kind: "doi", doi: "nope", repo: "https://example.org/a/b", title: "a".repeat(300) }));

    expect(checked.value).toBeNull();
    expect(Object.keys(checked.problems).sort()).toEqual(["doi", "repo", "title"]);
    expect(checkAgent(draft({ kind: "url", url: "nope" })).problems.url).toBeDefined();
  });

  it("is checked against the hosts the server says, when it says them", () => {
    const own = draft({ kind: "doi", doi: "10.1038/abc", repo: "https://example.org/a/b" });

    expect(checkAgent(own).problems.repo).toBeDefined();
    expect(checkAgent(own, ["example.org"]).problems).toEqual({});
  });
});

describe("an agent in words", () => {
  it("says which paper it is of", () => {
    expect(describePaper({ kind: "doi", doi: "10.1/x" })).toBe("DOI 10.1/x");
    expect(describePaper({ kind: "url", url: "https://example.org/p" })).toBe("https://example.org/p");
    expect(describePaper({ kind: "file", file: null })).toContain("not been uploaded");
    expect(describePaper({ kind: "file", file: { name: "p.pdf", bytes: 2048, sha256: "0".repeat(64) } })).toBe("p.pdf, 2.0 KB");
  });

  it("says where the paper can be opened, if it can be", () => {
    expect(paperLink({ kind: "doi", doi: "10.1/x" })).toBe("https://doi.org/10.1/x");
    expect(paperLink({ kind: "url", url: "https://example.org/p" })).toBe("https://example.org/p");
    expect(paperLink({ kind: "file", file: null })).toBeNull();
    // A record that was edited by hand does not send the page anywhere but by http or https
    expect(paperLink({ kind: "url", url: "javascript:alert(1)" })).toBeNull();
  });

  it("says how far it has got", () => {
    expect(describeSteps(agent())).toBe("Nothing has been done to it yet");
    expect(describeSteps(agent({ reading: "done", repository: "done" }))).toBe("2 of 5 steps done");
    expect(describeSteps(agent({ reading: "done", repository: "running" }))).toBe("Take stock of its code is going on");
    expect(describeSteps(agent({ reading: "failed" }))).toBe("Nothing has been done to it yet");
  });

  it("is at an address of its own", () => {
    expect(agentAddress("cells")).toBe("/papers?agent=cells");
    expect(agentAddress("a b")).toBe("/papers?agent=a%20b");
  });
});

describe("the agent that already has a paper", () => {
  it("is the one the server names when it refuses a second", () => {
    expect(existingOf(new ApiError(409, "exists", "It is there", { existing: "cells" }))).toBe("cells");
  });

  it("is nothing for any other refusal", () => {
    expect(existingOf(new ApiError(409, "too_many", "Too many", { existing: "cells" }))).toBeNull();
    expect(existingOf(new ApiError(409, "exists", "It is there"))).toBeNull();
    expect(existingOf(new Error("lost"))).toBeNull();
  });
});

const anchor = (changes: Partial<ReadAnchor> = {}): ReadAnchor => ({ start: 10, end: 80, page: null, section: null, ...changes });

function reading(changes: Partial<PaperAgentReading> = {}): PaperAgentReading {
  return {
    id: "cells",
    has_paper: true,
    has_text: true,
    job: null,
    chunks: 12,
    read: 9,
    skipped: 3,
    failed: 0,
    complete: true,
    dropped: { quote: 0, detail: 0 },
    cost: 0.0421,
    calls: 9,
    models: ["gpt-5.2"],
    characters: 40_000,
    truncated_from: null,
    finished_at: "2026-01-01T00:00:00Z",
    claims: [],
    card: { status: "draft", methods: [], datasets: [], scope: [], limitations: [] },
    resources: { software: [], links: [], availability: [], licenses: [] },
    ...changes,
  };
}

function job(changes: Partial<Job> = {}): Job {
  return {
    id: "j1",
    kind: "paperagent-reading",
    subject: "cells",
    title: "Reading the paper: Cells",
    state: "running",
    message: "",
    progress: {},
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    finished_at: null,
    log_total: 0,
    ...changes,
  };
}

describe("the file of a paper", () => {
  it("is the one uploaded, which a DOI or a link may have beside it", () => {
    const file = { name: "a.pdf", bytes: 10, sha256: "0".repeat(64) };

    expect(paperFile({ kind: "file", file })).toEqual(file);
    expect(paperFile({ kind: "doi", doi: "10.1/a", file })).toEqual(file);
    expect(paperFile({ kind: "url", url: "https://example.org/p", file: null })).toBeNull();
  });

  it("is not there for a DOI or a link that has had none, which the server leaves out, nor for a file that has not come", () => {
    expect(paperFile({ kind: "doi", doi: "10.1/a" })).toBeNull();
    expect(paperFile({ kind: "file", file: null })).toBeNull();
  });
});

describe("the job that reads a paper", () => {
  it("is the one at work on that agent, and not another kind of job or another agent's", () => {
    const jobs = [
      job({ id: "other", subject: "dogs" }),
      job({ id: "survey", kind: "papers" }),
      job({ id: "old", state: "succeeded" }),
      job({ id: "mine" }),
    ];

    expect(readingJob(jobs, "cells")?.id).toBe("mine");
    expect(readingJob(jobs, "none")).toBeUndefined();
    expect(readingJob([job({ state: "stopping" })], "cells")?.state).toBe("stopping");
  });

  it("is, when none is at work, the latest that is over", () => {
    const jobs = [job({ id: "new", state: "stopped" }), job({ id: "old", state: "failed" }), job({ id: "survey", kind: "papers", state: "failed" })];

    expect(lastReadingJob(jobs, "cells")?.id).toBe("new");
    expect(lastReadingJob([job()], "cells")).toBeUndefined();
  });

  it("makes a key that changes as the reading goes on and when it ends", () => {
    const at = (finished?: number) => readingKey([job({ progress: { chunks: 5, finished } })], 0, "cells");

    expect(at(1)).not.toBe(at(2));
    expect(readingKey([job()], 0, "cells")).not.toBe(readingKey([job()], 1, "cells"));
    expect(readingKey(null, 0, "cells")).toBe("0|");
    expect(readingKey([job({ subject: "dogs" })], 0, "cells")).toBe("0|");
  });
});

describe("the limit on what reading may spend", () => {
  it("is always asked for, and is read as dollars", () => {
    expect(checkReading({ ...EMPTY_READING, budget: "" }).problems.budget).toMatch(/Say the most it may spend/);
    expect(checkReading({ ...EMPTY_READING, budget: "lots" }).value).toBeNull();
    expect(checkReading({ ...EMPTY_READING, budget: "-1" }).value).toBeNull();
    expect(checkReading({ budget: "$0.50", retryFailed: true })).toEqual({ value: { max_cost: 0.5, retry_failed: true }, problems: {} });
    expect(checkReading(EMPTY_READING).value).toEqual({ max_cost: 1, retry_failed: false });
  });

  it("may be nothing, which reads nothing", () => {
    expect(checkReading({ ...EMPTY_READING, budget: "0" }).value).toEqual({ max_cost: 0, retry_failed: false });
  });
});

describe("how far a paper has been read", () => {
  it("is begun once there are chunks, however far it got", () => {
    expect(hasReading(reading())).toBe(true);
    expect(hasReading(reading({ chunks: null, read: 0, skipped: 0, complete: false }))).toBe(false);
  });

  it("is through when every chunk has come to something, unless the chunks that failed are read again", () => {
    expect(readThrough(reading(), false)).toBe(true);
    expect(readThrough(reading({ failed: 2 }), false)).toBe(true);
    expect(readThrough(reading({ failed: 2 }), true)).toBe(false);
    expect(readThrough(reading({ failed: 0 }), true)).toBe(true);
    expect(readThrough(reading({ complete: false }), false)).toBe(false);
  });

  it("is said in a line, with what it cost", () => {
    expect(describeReading(reading())).toBe("Read 9 of 12 chunks · 3 left out (the references) · spent $0.04");
    expect(describeReading(reading({ chunks: 1, read: 1, skipped: 0, cost: 0.002 }))).toBe("Read 1 of 1 chunk · spent <$0.01");
    expect(describeReading(reading({ failed: 1, cost: 0 }))).toBe("Read 9 of 12 chunks · 3 left out (the references) · 1 could not be read · spent $0.00");
    expect(describeReading(reading({ cost: null }))).toContain("cost unknown");
    expect(describeReading(reading({ chunks: null }))).toBe("The paper has not been read.");
  });

  it("says how many facts were left out for want of the paper's words", () => {
    expect(describeLeftOut(reading())).toBeNull();
    expect(describeLeftOut(reading({ dropped: { quote: 1, detail: 0 } }))).toBe("1 fact the model gave was left out, because the paper does not bear it out.");
    expect(describeLeftOut(reading({ dropped: { quote: 2, detail: 3 } }))).toBe("5 facts the model gave were left out, because the paper does not bear them out.");
  });

  it("says how much of a long paper was read", () => {
    expect(describeLength(reading())).toBeNull();
    expect(describeLength(reading({ characters: 400_000, truncated_from: 1_250_000 }))).toBe(
      "The paper is long, so only its first 400,000 of 1,250,000 characters were read.",
    );
  });
});

describe("where a fact is in the paper", () => {
  it("is its page and its section, as far as they are known", () => {
    expect(describeAnchor(anchor({ page: 3, section: "Methods" }))).toBe("Page 3, Methods");
    expect(describeAnchor(anchor({ page: 3 }))).toBe("Page 3");
    expect(describeAnchor(anchor({ section: "Results" }))).toBe("Results");
  });

  it("is the characters it is at when nothing else is known", () => {
    expect(describeAnchor(anchor({ start: 1200, end: 3400 }))).toBe("Characters 1,200 to 3,400");
  });
});

describe("the facts of a reading", () => {
  const fact = (id: string) => ({ id, quote: `The words of ${id}.`, anchor: anchor() });

  it("are in the groups a person reads them in, and only the groups that have some", () => {
    const found = reading({
      claims: [
        { ...fact("c1"), kind: "number", value: "0.93" },
        { ...fact("c2"), kind: "comparison", value: "" },
      ],
      card: {
        status: "draft",
        methods: [{ ...fact("m1"), name: "featureCounts" }],
        datasets: [],
        scope: [{ ...fact("s1"), aspect: "sample size", value: "500 nuclei" }],
        limitations: [fact("l1")],
      },
      resources: {
        software: [{ ...fact("w1"), name: "STAR", version: "2.7.10a" }, { ...fact("w2"), name: "R", version: "" }],
        links: [{ ...fact("k1"), url: "https://github.com/example/cellmapper", role: "code" }],
        availability: [{ ...fact("a1"), kind: "data" }],
        licenses: [{ ...fact("i1"), name: "MIT", covers: "code" }],
      },
    });

    const groups = factGroups(found);

    expect(groups.map((group) => group.key)).toEqual(["claims", "methods", "scope", "limitations", "software", "links", "availability", "licenses"]);
    expect(factCount(found)).toBe(10);
    const lines = Object.fromEntries(groups.map((group) => [group.key, group.facts.map(({ title, tag }) => [title, tag])]));
    expect(lines.claims).toEqual([["0.93", "A number"], [null, "A comparison"]]);
    expect(lines.scope).toEqual([["500 nuclei", "Sample size"]]);
    expect(lines.limitations).toEqual([[null, null]]);
    expect(lines.software).toEqual([["STAR", "Version 2.7.10a"], ["R", null]]);
    expect(lines.links).toEqual([["https://github.com/example/cellmapper", "Code"]]);
    expect(lines.availability).toEqual([[null, "Data"]]);
    expect(lines.licenses).toEqual([["MIT", "Code"]]);
  });

  it("are none for a paper that has nothing found in it", () => {
    expect(factGroups(reading())).toEqual([]);
    expect(factCount(reading())).toBe(0);
  });
});
