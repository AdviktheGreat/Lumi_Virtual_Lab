import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import {
  agentAddress,
  checkAgent,
  describePaper,
  describeSteps,
  doiOf,
  EMPTY_AGENT,
  existingOf,
  isLink,
  isRepo,
  paperLink,
  repoName,
  repoProblem,
  titleProblem,
  type AgentDraft,
} from "./paperagents";
import type { PaperAgent } from "./types";

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
