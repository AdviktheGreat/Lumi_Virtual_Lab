import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import {
  agentAddress,
  checkAgent,
  checkFetch,
  checkReading,
  describeAnchor,
  describeCommit,
  describeData,
  describeEstimate,
  describeFetched,
  describeLicense,
  describeLeftOut,
  describeLength,
  describePaper,
  describeSource,
  describeReading,
  describeSteps,
  doiOf,
  emptyFetch,
  EMPTY_AGENT,
  EMPTY_READING,
  dataJob,
  environmentJob,
  existingOf,
  factCount,
  factGroups,
  hasReading,
  isLink,
  isRepo,
  lastDataJob,
  lastEnvironmentJob,
  lastReadingJob,
  lastReferenceJob,
  lastToolsJob,
  lastRepositoryJob,
  orderedChecks,
  paperFile,
  paperLink,
  readingJob,
  readingKey,
  readThrough,
  referenceJob,
  refProblem,
  repoName,
  repoProblem,
  repositoryJob,
  stockRows,
  STOCK_ITEMS_SHOWN,
  titleProblem,
  toolsJob,
  type AgentDraft,
} from "./paperagents";
import type { Job, PaperAgent, PaperAgentReading, PaperAgentRepository, Preflight, ReadAnchor, RepositoryStock } from "./types";

const draft = (part: Partial<AgentDraft>): AgentDraft => ({ ...EMPTY_AGENT, ...part });

function agent(steps: Partial<PaperAgent["steps"]> = {}): PaperAgent {
  return {
    id: "cells",
    title: "Cells",
    created_at: "2026-01-01T00:00:00Z",
    paper: { kind: "doi", doi: "10.1038/s41586-020-2649-2" },
    repo: null,
    steps: { reading: "pending", repository: "pending", environment: "pending", data: "pending", tools: "pending", ...steps },
    given: false,
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

  it("says where the text of the paper was fetched from", () => {
    const source = { kind: "europepmc", label: "Europe PMC, PMC3258128", url: "https://europepmc.org/article/MED/21937511" } as const;

    expect(describeSource(source)).toBe("Fetched from Europe PMC, PMC3258128");
    expect(describeSource({ kind: "link", label: "The page at example.org", url: "https://example.org/p" })).toBe(
      "Fetched from The page at example.org",
    );
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
    fetchable: false,
    source: null,
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
    // The file that was fetched says where from
    const fetched = { ...file, source: { kind: "europepmc", label: "Europe PMC, PMC1", url: "https://europepmc.org/article/PMC/PMC1" } } as const;
    expect(paperFile({ kind: "doi", doi: "10.1/a", file: fetched })?.source?.kind).toBe("europepmc");
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

  it("changes as the code is fetched, and says nothing of another agent's", () => {
    const fetching = job({ id: "f1", kind: "paperagent-repository" });

    expect(readingKey([fetching], 0, "cells")).not.toBe(readingKey([], 0, "cells"));
    expect(readingKey([{ ...fetching, subject: "dogs" }], 0, "cells")).toBe("0|");
    expect(readingKey([{ ...fetching, state: "succeeded" }], 0, "cells")).toBe("0|");
  });
});

describe("the job that builds the environment of an agent", () => {
  const building = (changes: Partial<Job> = {}) => job({ id: "b1", kind: "paperagent-environment", ...changes });

  it("is the one at work on that agent, and not the one that fetches its code or another agent's", () => {
    const jobs = [job({ id: "reading" }), building({ id: "other", subject: "dogs" }), building({ id: "old", state: "failed" }), building()];

    expect(environmentJob(jobs, "cells")?.id).toBe("b1");
    expect(environmentJob(jobs.slice(0, 3), "cells")).toBeUndefined();
    expect(environmentJob([job({ kind: "paperagent-repository" })], "cells")).toBeUndefined();
  });

  it("is, when none is at work, the latest that is over", () => {
    const jobs = [building({ id: "new", state: "stopped" }), building({ id: "old", state: "failed" }), job({ state: "failed" })];

    expect(lastEnvironmentJob(jobs, "cells")?.id).toBe("new");
    expect(lastEnvironmentJob([building()], "cells")).toBeUndefined();
  });

  it("changes the key that the page looks again by, and says nothing of another agent's", () => {
    expect(readingKey([building()], 0, "cells")).not.toBe(readingKey([], 0, "cells"));
    expect(readingKey([building()], 0, "cells")).not.toBe(readingKey([job({ id: "b1", kind: "paperagent-repository" })], 0, "cells"));
    expect(readingKey([building({ subject: "dogs" })], 0, "cells")).toBe("0|");
    expect(readingKey([building({ state: "succeeded" })], 0, "cells")).toBe("0|");
  });
});

describe("the job that runs the tutorials of an agent", () => {
  const running = (changes: Partial<Job> = {}) => job({ id: "r1", kind: "paperagent-reference", ...changes });

  it("is the one at work on that agent, and not the one that builds its environment or another agent's", () => {
    const jobs = [job({ id: "reading" }), running({ id: "other", subject: "dogs" }), running({ id: "old", state: "failed" }), running()];

    expect(referenceJob(jobs, "cells")?.id).toBe("r1");
    expect(referenceJob(jobs.slice(0, 3), "cells")).toBeUndefined();
    expect(referenceJob([job({ kind: "paperagent-environment" })], "cells")).toBeUndefined();
  });

  it("is, when none is at work, the latest that is over", () => {
    const jobs = [running({ id: "new", state: "stopped" }), running({ id: "old", state: "failed" }), job({ state: "failed" })];

    expect(lastReferenceJob(jobs, "cells")?.id).toBe("new");
    expect(lastReferenceJob([running()], "cells")).toBeUndefined();
  });

  it("changes the key that the page looks again by, and says nothing of another agent's", () => {
    expect(readingKey([running()], 0, "cells")).not.toBe(readingKey([], 0, "cells"));
    expect(readingKey([running()], 0, "cells")).not.toBe(readingKey([job({ id: "r1", kind: "paperagent-data" })], 0, "cells"));
    expect(readingKey([running({ subject: "dogs" })], 0, "cells")).toBe("0|");
    expect(readingKey([running({ state: "succeeded" })], 0, "cells")).toBe("0|");
  });
});

describe("the job that fetches the data of an agent", () => {
  const getting = (changes: Partial<Job> = {}) => job({ id: "d1", kind: "paperagent-data", ...changes });

  it("is the one at work on that agent, and not the one that fetches its code or another agent's", () => {
    const jobs = [job({ id: "reading" }), getting({ id: "other", subject: "dogs" }), getting({ id: "old", state: "failed" }), getting()];

    expect(dataJob(jobs, "cells")?.id).toBe("d1");
    expect(dataJob(jobs.slice(0, 3), "cells")).toBeUndefined();
    expect(dataJob([job({ kind: "paperagent-repository" })], "cells")).toBeUndefined();
  });

  it("is, when none is at work, the latest that is over", () => {
    const jobs = [getting({ id: "new", state: "stopped" }), getting({ id: "old", state: "failed" }), job({ state: "failed" })];

    expect(lastDataJob(jobs, "cells")?.id).toBe("new");
    expect(lastDataJob([getting()], "cells")).toBeUndefined();
  });

  it("changes the key that the page looks again by, and says nothing of another agent's", () => {
    expect(readingKey([getting()], 0, "cells")).not.toBe(readingKey([], 0, "cells"));
    expect(readingKey([getting()], 0, "cells")).not.toBe(readingKey([job({ id: "d1", kind: "paperagent-environment" })], 0, "cells"));
    expect(readingKey([getting({ subject: "dogs" })], 0, "cells")).toBe("0|");
    expect(readingKey([getting({ state: "succeeded" })], 0, "cells")).toBe("0|");
  });
});

describe("the job that fetches the code of an agent", () => {
  const fetching = (changes: Partial<Job> = {}) => job({ id: "f1", kind: "paperagent-repository", ...changes });

  it("is the one at work on that agent, and not the one that reads its paper or another agent's", () => {
    const jobs = [job({ id: "reading" }), fetching({ id: "other", subject: "dogs" }), fetching({ id: "old", state: "failed" }), fetching()];

    expect(repositoryJob(jobs, "cells")?.id).toBe("f1");
    expect(repositoryJob(jobs.slice(0, 3), "cells")).toBeUndefined();
    expect(readingJob(jobs, "cells")?.id).toBe("reading");
  });

  it("is, when none is at work, the latest that is over", () => {
    const jobs = [fetching({ id: "new", state: "failed" }), fetching({ id: "old", state: "succeeded" }), job({ state: "failed" })];

    expect(lastRepositoryJob(jobs, "cells")?.id).toBe("new");
    expect(lastRepositoryJob([fetching()], "cells")).toBeUndefined();
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

const limits: PaperAgentRepository["limits"] = { default_megabytes: 200, min_megabytes: 10, max_megabytes: 1000 };

describe("the name of a branch, a tag, or a commit", () => {
  it("may be left out, for the project's default", () => {
    expect(refProblem("")).toBeNull();
    expect(refProblem("   ")).toBeNull();
  });

  it("is what Git takes, and not what it could take for an option or a way out of the project", () => {
    for (const ref of ["main", "v1.2.3", "release/2.0", "feature_x+y", "a".repeat(40), "user@host"]) expect(refProblem(ref)).toBeNull();
    for (const ref of ["-rf", "--upload-pack=x", "a..b", "a//b", "main.", "main/", "main.lock", ".hidden", "a b", "a:b", "a~1", "a".repeat(201)]) {
      expect(refProblem(ref)).toMatch(/not the name of a branch/);
    }
  });
});

describe("what fetching the code is asked for", () => {
  it("is the project's default branch and the usual most, if nothing is said", () => {
    expect(emptyFetch(limits)).toEqual({ ref: "", megabytes: "200" });
    expect(checkFetch(emptyFetch(limits), limits)).toEqual({ value: { max_megabytes: 200 }, problems: {} });
  });

  it("names the ref that was typed, without the space round it", () => {
    expect(checkFetch({ ref: " v1.0 ", megabytes: "50" }, limits)).toEqual({ value: { ref: "v1.0", max_megabytes: 50 }, problems: {} });
  });

  it("is refused, each part with its own reason, when the ref is wrong or the most is not a whole number in range", () => {
    expect(checkFetch({ ref: "-x", megabytes: "200" }, limits).problems.ref).toMatch(/not the name/);
    for (const megabytes of ["", "5", "1001", "2.5", "lots", "-20"]) {
      const checked = checkFetch({ ref: "", megabytes }, limits);

      expect(checked.value).toBeNull();
      expect(checked.problems.megabytes).toMatch(/^The most to fetch, in megabytes, is a whole number from 10 to 1000\./);
    }
    expect(Object.keys(checkFetch({ ref: "a..b", megabytes: "0" }, limits).problems).sort()).toEqual(["megabytes", "ref"]);
  });
});

function preflight(changes: Partial<Preflight> = {}): Preflight {
  return {
    verdict: "ask",
    summary: "Ask first",
    checks: [
      { id: "code", title: "Code", status: "ok", detail: "d" },
      { id: "license", title: "License", status: "warn", detail: "d" },
      { id: "tutorials", title: "Tutorials", status: "note", detail: "d" },
      { id: "gpu", title: "GPU", status: "block", detail: "d" },
      { id: "data", title: "Data", status: "unknown", detail: "d" },
      { id: "size", title: "Size", status: "warn", detail: "d" },
    ],
    estimate: { low: 0.5, high: 1.5, tutorials: 3, basis: "At about so much each." },
    ...changes,
  };
}

describe("the checks of whether to go on", () => {
  it("come in the order a person weighs them: what stops it first, and what is fine last, as they were otherwise", () => {
    expect(orderedChecks(preflight()).map((check) => check.id)).toEqual(["gpu", "license", "size", "data", "tutorials", "code"]);
  });

  it("are not reordered in the one that is given", () => {
    const given = preflight();
    orderedChecks(given);

    expect(given.checks[0].id).toBe("code");
  });
});

describe("what making tools from the tutorials is guessed to cost", () => {
  it("is said as a range, or as one amount if the two are the same", () => {
    expect(describeEstimate({ low: 0.5, high: 1.5, tutorials: 3, basis: "" })).toBe("Making tools from 3 tutorials is guessed at $0.50 to $1.50 in model requests.");
    expect(describeEstimate({ low: 0.25, high: 0.25, tutorials: 1, basis: "" })).toBe("Making tools from 1 tutorial is guessed at $0.25 in model requests.");
  });

  it("is not said when it cannot be told, or there is nothing to make tools from", () => {
    expect(describeEstimate({ low: null, high: null, tutorials: 3, basis: "" })).toBeNull();
    expect(describeEstimate({ low: 0, high: 0, tutorials: 0, basis: "" })).toBeNull();
  });
});

describe("what was fetched", () => {
  it("is the project at a short commit and what was asked for", () => {
    const commit = "0123456789abcdef0123456789abcdef01234567";

    expect(describeCommit("https://github.com/a/b", "HEAD", commit)).toBe("a/b at 0123456789ab (the default branch)");
    expect(describeCommit("https://github.com/a/b", "v2", commit)).toBe("a/b at 0123456789ab (v2)");
  });

  it("is dated, and says so even if the date cannot be read", () => {
    expect(describeFetched("not a date")).toBe("Fetched a while ago");
    expect(describeFetched(new Date().toISOString())).toMatch(/^Fetched /);
  });
});

function stock(changes: Partial<RepositoryStock> = {}): RepositoryStock {
  return {
    schema: 1,
    files: 120,
    bytes: 2_500_000,
    complete: true,
    languages: [
      { name: "Python", files: 80, bytes: 1 },
      { name: "R", files: 5, bytes: 1 },
    ],
    notebooks: { count: 2, listed: [] },
    tutorials: { count: 3, characters: 100, listed: [{ path: "tutorials/a.ipynb", kind: "notebook", bytes: 1, characters: 1 }] },
    tests: { count: 0, listed: [] },
    environment: [
      { path: "requirements.txt", kind: "pip", pins: "all" },
      { path: "setup.py", kind: "setup", pins: null },
    ],
    license: { files: ["LICENSE"], name: "MIT", kind: "permissive", from: "text" },
    readme: { path: "README.md", example: true },
    gpu: { required: [], optional: [{ path: "a.py", signal: "cuda", kind: "optional" }] },
    data: { count: 0, bytes: 0, listed: [], lfs: false, lfs_pointers: 0, dvc: false, links: [], accessions: [] },
    submodules: [],
    absolute_paths: { count: 0, listed: [] },
    ...changes,
  };
}

describe("what was found in a project", () => {
  it("is rows of what it is and what was found, with the paths of it", () => {
    const rows = Object.fromEntries(stockRows(stock()).map((row) => [row.label, row]));

    expect(rows.Size.value).toBe("120 files, 2.4 MB");
    expect(rows.Languages.value).toBe("Python (80 files), R (5 files)");
    expect(rows.Tutorials).toMatchObject({ value: "3, of which 2 notebooks", items: ["tutorials/a.ipynb"] });
    expect(rows.Tests.value).toBe("None");
    expect(rows["What to install"].value).toBe("requirements.txt (versions given), setup.py");
    expect(rows.License).toMatchObject({ value: "MIT (permissive)", items: ["LICENSE"] });
    expect(rows.GPU).toMatchObject({ value: "Used if there is one, and not needed", items: ["cuda (a.py)"] });
    expect(rows.Data.value).toBe("Nothing says where it is");
    expect(Object.keys(rows)).not.toContain("Submodules, which are not fetched");
  });

  it("says that only part of a large project was looked at", () => {
    expect(stockRows(stock({ complete: false }))[0].value).toMatch(/only part of it was looked at/);
  });

  it("says what is missing as what is missing", () => {
    const rows = Object.fromEntries(
      stockRows(
        stock({
          languages: [],
          environment: [],
          license: null,
          tutorials: { count: 0, characters: 0, listed: [] },
          gpu: { required: [{ path: "m.py", signal: "cuda", kind: "required" }], optional: [] },
        }),
      ).map((row) => [row.label, row]),
    );

    expect(rows.Languages.value).toBe("No code was found");
    expect(rows["What to install"].value).toBe("No file says");
    expect(rows.License.value).toBe("None");
    expect(rows.Tutorials.value).toBe("None, but the README shows how it is used");
    expect(rows.GPU.value).toBe("Needed");
  });

  it("adds a row for submodules and for examples that read from someone's computer, only when there are some", () => {
    const rows = stockRows(
      stock({
        submodules: [{ path: "ext/x", url: "https://github.com/a/x" }],
        absolute_paths: { count: 2, listed: [{ path: "run.py", example: "/home/u/data" }] },
      }),
    );

    expect(rows.find((row) => row.label.startsWith("Submodules"))).toMatchObject({ value: "1", items: ["ext/x"] });
    expect(rows.find((row) => row.label.startsWith("Examples"))).toMatchObject({ value: "2", items: ["/home/u/data (run.py)"] });
  });

  it("is a limit on the paths that a page lists, which is five", () => {
    expect(STOCK_ITEMS_SHOWN).toBe(5);
  });
});

describe("the license of a project", () => {
  it("is its name and kind, or the kind alone if the name is not known", () => {
    expect(describeLicense(stock())).toBe("MIT (permissive)");
    expect(describeLicense(stock({ license: { files: ["COPYING"], name: null, kind: "copyleft", from: "text" } }))).toBe("Not recognized, copyleft");
    expect(describeLicense(stock({ license: { files: ["L"], name: "CC-BY-NC-4.0", kind: "noncommercial", from: "text" } }))).toBe(
      "CC-BY-NC-4.0 (for non-commercial use)",
    );
    expect(describeLicense(stock({ license: null }))).toBe("None");
  });
});

describe("the data of a project", () => {
  it("is what is in it and what it points to, and says when nothing does", () => {
    const data = { count: 2, bytes: 3_000_000, listed: [], lfs: true, lfs_pointers: 4, dvc: true, links: ["https://zenodo.org/x"], accessions: ["GSE1", "GSE2", "GSE3", "GSE4"] };
    const said = describeData(stock({ data }));

    expect(said).toContain("2 data or model files (2.9 MB)");
    expect(said).toContain("4 files in Git LFS, which are not fetched");
    expect(said).toContain("kept with DVC, which is not fetched");
    expect(said).toContain("1 link to where data is kept");
    expect(said).toContain("accessions GSE1, GSE2, GSE3");
    expect(said).not.toContain("GSE4");
    expect(describeData(stock())).toBe("Nothing says where it is");
  });
});

describe("the job that makes the tools of an agent", () => {
  const making = (changes: Partial<Job> = {}) => job({ id: "t1", kind: "paperagent-tools", ...changes });

  it("is the one at work on that agent, and not the one that runs its tutorials or another agent's", () => {
    const jobs = [job({ kind: "paperagent-reference" }), making({ id: "other", subject: "dogs" }), making({ id: "old", state: "failed" }), making()];

    expect(toolsJob(jobs, "cells")?.id).toBe("t1");
    expect(toolsJob(jobs.slice(0, 3), "cells")).toBeUndefined();
    expect(toolsJob([job({ kind: "paperagent-reference" })], "cells")).toBeUndefined();
  });

  it("is, when none is at work, the latest that is over", () => {
    const jobs = [making({ id: "new", state: "stopped" }), making({ id: "old", state: "failed" }), job({ state: "failed" })];

    expect(lastToolsJob(jobs, "cells")?.id).toBe("new");
    expect(lastToolsJob([making()], "cells")).toBeUndefined();
  });

  it("changes the key that the page looks again by, apart from the running of the tutorials, and says nothing of another agent's", () => {
    expect(readingKey([making()], 0, "cells")).not.toBe(readingKey([], 0, "cells"));
    expect(readingKey([making()], 0, "cells")).not.toBe(readingKey([job({ id: "t1", kind: "paperagent-reference" })], 0, "cells"));
    expect(readingKey([making({ subject: "dogs" })], 0, "cells")).toBe("0|");
    expect(readingKey([making({ state: "succeeded" })], 0, "cells")).toBe("0|");
  });
});
