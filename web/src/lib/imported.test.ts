import { describe, expect, it } from "vitest";
import {
  addressProblem,
  checkImport,
  describeHost,
  describeHosted,
  describeListed,
  describeMaker,
  describeNote,
  describeWhen,
  EMPTY_IMPORT,
  importState,
  MAX_ADDRESS_CHARS,
  quickImport,
  titleOf,
} from "./imported";
import type { ImportableAgent, PaperAgent } from "./types";

const SCANPY: ImportableAgent = {
  key: "scanpy",
  title: "Scanpy",
  about: "Preprocessing, clustering, and annotating single-cell data with Scanpy",
  made_by: "Paper2Agent",
  url: "https://Paper2Agent-scanpy-mcp.hf.space/mcp",
  site: "https://paper2agent-scanpy-mcp.hf.space/",
  paper: { kind: "doi", doi: "10.1186/s13059-017-1382-0" },
  repo: "https://github.com/scverse/scanpy",
  agent: null,
  paper_agent: null,
};

describe("addressProblem", () => {
  it("takes a web address, with spaces round it", () => {
    expect(addressProblem("https://example.org/mcp")).toBeNull();
    expect(addressProblem("  http://localhost:8000/mcp  ")).toBeNull();
  });

  it("asks for an address", () => {
    expect(addressProblem("")).toBe("Give the address of the server.");
    expect(addressProblem("   ")).toBe("Give the address of the server.");
  });

  it("wants http or https, and no spaces, and not too many characters", () => {
    expect(addressProblem("scanpy")).toContain("begins with http");
    expect(addressProblem("ftp://example.org/mcp")).toContain("begins with http");
    expect(addressProblem("https://example.org/a b")).toContain("no spaces");
    expect(addressProblem(`https://example.org/${"a".repeat(MAX_ADDRESS_CHARS)}`)).toContain("no spaces");
  });

  it("refuses a variable, which a config would put the value of in its place", () => {
    for (const address of ["https://example.org/${SECRET}/mcp", "https://${HOST}/mcp", "https://example.org/mcp$", "https://example.org/{a}"]) {
      expect(addressProblem(address), address).toContain("variable");
    }
  });

  it("sends a key that is in the address to where keys are kept", () => {
    for (const address of ["https://person:secret@example.org/mcp", "https://example.org/mcp?key=secret", "https://example.org/mcp#top"]) {
      expect(addressProblem(address), address).toContain("where keys are kept");
    }
  });

  it("refuses what is not an address", () => {
    expect(addressProblem("https://")).not.toBeNull();
    expect(addressProblem("https://example.org:notaport/mcp")).toBe("That is not a web address.");
  });
});

describe("checkImport", () => {
  const draft = { ...EMPTY_IMPORT, address: "https://example.org/mcp", doi: "10.1000/cellmapper" };

  it("asks for the server and the paper, and says what is wrong with each", () => {
    const checked = checkImport({ ...EMPTY_IMPORT });

    expect(checked.value).toBeNull();
    expect(Object.keys(checked.problems).sort()).toEqual(["address", "doi"]);
  });

  it("sends the server with the paper, and the title and code if they are given", () => {
    expect(checkImport(draft).value).toEqual({ url: "https://example.org/mcp", title: "", paper: { kind: "doi", doi: "10.1000/cellmapper" } });
    expect(checkImport({ ...draft, title: "  Cell  Mapper ", repo: "https://github.com/lab/cellmapper" }).value).toEqual({
      url: "https://example.org/mcp",
      title: "Cell Mapper",
      paper: { kind: "doi", doi: "10.1000/cellmapper" },
      repo: "https://github.com/lab/cellmapper",
    });
  });

  it("asks for a title where the paper is a file", () => {
    const checked = checkImport({ ...draft, kind: "file" });

    expect(checked.value).toBeNull();
    expect(checked.problems.title).toBe("Give the agent a title.");
  });

  it("is nothing while the address is wrong, even if the paper is fit", () => {
    const checked = checkImport({ ...draft, address: "https://example.org/${X}" });

    expect(checked.value).toBeNull();
    expect(Object.keys(checked.problems)).toEqual(["address"]);
  });
});

describe("what is said of an imported agent", () => {
  it("says who made it only where that is known", () => {
    expect(describeMaker({ origin: "Paper2Agent" })).toBe("Made by Paper2Agent");
    expect(describeMaker({ origin: null })).toBe("Made by someone else");
  });

  it("says where it runs, which is not here", () => {
    expect(describeHost({ host: "example.org" })).toBe("Runs on example.org, a machine that is not this one and is not run by Lumi.");
  });

  it("says how many tools it listed", () => {
    expect(describeListed([])).toBe("It listed no tools.");
    expect(describeListed([{ name: "a", summary: "", parameters: [] }])).toBe("It listed 1 tool.");
    expect(describeListed([1, 2, 3].map((name) => ({ name: String(name), summary: "", parameters: [] })))).toBe("It listed 3 tools.");
  });

  it("says when it was imported and its server last connected to", () => {
    const now = new Date("2026-03-10T12:00:00Z");

    expect(describeWhen({ imported_at: "2026-03-10T09:00:00Z", checked_at: "2026-03-10T11:30:00Z" }, now)).toBe(
      "Imported 3 h ago. Its server was last connected to 30 min ago.",
    );
    expect(describeWhen({ imported_at: "nonsense", checked_at: "nonsense" }, now)).toBe("Imported.");
  });

  it("says that a server that is hosted is made and run by others, and that a call asks", () => {
    const said = describeHosted(SCANPY);

    expect(said).toContain("Made by Paper2Agent");
    expect(said).toContain("paper2agent-scanpy-mcp.hf.space, a Space on Hugging Face");
    expect(said).toContain("not run by Lumi");
    expect(said).toContain("each call asks you first");
    expect(describeHosted({ made_by: "Someone", url: "https://example.org/mcp" })).toContain("run on example.org, which");
  });
});

describe("describeNote", () => {
  it("says that the files are on the server of Paper2Agent, where the lab does not upload them", () => {
    expect(describeNote(SCANPY)).toContain("files that are on its server");
    expect(describeNote(SCANPY)).not.toContain("API key");
  });

  it("says that AlphaGenome's tools take a key, which is sent to the server", () => {
    const said = describeNote({ ...SCANPY, key: "alphagenome" });

    expect(said).toContain("AlphaGenome API key as an argument");
    expect(said).toContain("sent to that server");
  });

  it("says nothing of a server that is not Paper2Agent's", () => {
    expect(describeNote({ key: "other", made_by: "Someone" })).toBeNull();
  });
});

describe("what a server that is listed can be", () => {
  it("is imported if an agent has it, added to the agent of its paper if there is one, and new otherwise", () => {
    expect(importState({ ...SCANPY, agent: "scanpy", paper_agent: "scanpy" })).toEqual({ kind: "imported", agent: "scanpy" });
    expect(importState({ ...SCANPY, paper_agent: "mine" })).toEqual({ kind: "add", agent: "mine" });
    expect(importState(SCANPY)).toEqual({ kind: "new" });
  });

  it("is asked for as the agent of its paper, or as the server of an agent that there is, and not both", () => {
    expect(quickImport(SCANPY, { kind: "new" })).toEqual({
      url: SCANPY.url,
      title: "Scanpy",
      paper: { kind: "doi", doi: "10.1186/s13059-017-1382-0" },
      repo: "https://github.com/scverse/scanpy",
    });
    expect(quickImport(SCANPY, { kind: "add", agent: "mine" })).toEqual({ url: SCANPY.url, agent: "mine" });
  });

  it("names an agent by its title, and by its id if it is not listed", () => {
    const list = { agents: [{ id: "mine", title: "My Scanpy" } as PaperAgent] };

    expect(titleOf(list, "mine")).toBe("My Scanpy");
    expect(titleOf(list, "gone")).toBe("gone");
  });
});
