import { describe, expect, it } from "vitest";
import { describeResources, languageLabel, parseArguments, summarize } from "./calls";
import type { Resources } from "./transcript";

const call = (name: string, args: unknown, status: "running" | "done" | "interrupted" = "done") => ({
  name,
  arguments: typeof args === "string" ? args : JSON.stringify(args),
  status,
});

describe("the arguments of a call", () => {
  it("are read when they are an object of JSON", () => {
    expect(parseArguments('{"code":"print(1)"}')).toEqual({ code: "print(1)" });
  });

  it("are nothing when they are not JSON, or not an object", () => {
    expect(parseArguments("{not json")).toBeNull();
    expect(parseArguments("")).toBeNull();
    expect(parseArguments("[1, 2]")).toBeNull();
    expect(parseArguments("null")).toBeNull();
    expect(parseArguments('"text"')).toBeNull();
  });
});

describe("a language", () => {
  it("is named as a person says it", () => {
    expect([languageLabel("python"), languageLabel("R"), languageLabel("bash"), languageLabel("julia")]).toEqual([
      "Python",
      "R",
      "shell",
      "julia",
    ]);
  });

  it("is named the same whatever the case it was written in", () => {
    expect([languageLabel("PYTHON"), languageLabel("Bash")]).toEqual(["Python", "shell"]);
  });
});

describe("what a call is shown as", () => {
  it("is running code, with the code it was given, and it is python unless it says otherwise", () => {
    expect(summarize(call("run_code", { code: "x = 1" }, "running"))).toEqual({
      title: "Running Python code",
      detail: null,
      code: { language: "python", text: "x = 1" },
    });
    expect(summarize(call("run_code", { code: "ls", language: "bash" }))).toMatchObject({
      title: "Ran shell code",
      code: { language: "bash", text: "ls" },
    });
    expect(summarize(call("run_code", { code: "x", language: "" }))).toMatchObject({ code: { language: "python" } });
  });

  it("is code with no code when the arguments have none", () => {
    expect(summarize(call("run_code", "{broken"))).toEqual({ title: "Ran Python code", detail: null, code: null });
    expect(summarize(call("run_code", { code: 4 })).code).toBeNull();
  });

  it("is looking up resources, for the task", () => {
    expect(summarize(call("find_resources", { task: "Align\n  reads to a genome" }, "running"))).toEqual({
      title: "Looking up resources",
      detail: "Align reads to a genome",
      code: null,
    });
    expect(summarize(call("find_resources", { task: "  " })).detail).toBeNull();
    expect(summarize(call("find_resources", {})).title).toBe("Looked up resources");
  });

  it("is convening the team, with who and what for", () => {
    expect(
      summarize(call("convene_team", { agenda: "Design a nanobody against spike", members: ["Immunologist", "Biochemist"] }, "running")),
    ).toEqual({
      title: "Convening the team",
      detail: "Immunologist, Biochemist · Design a nanobody against spike",
      code: null,
    });
    expect(summarize(call("convene_team", { agenda: "Only an agenda" })).detail).toBe("Only an agenda");
    expect(summarize(call("convene_team", { members: ["Critic", 3, " "] })).detail).toBe("Critic");
    expect(summarize(call("convene_team", {})).detail).toBeNull();
  });

  it("is consulting a scientist", () => {
    expect(summarize(call("consult", { member: "Immunologist", agenda: "Which CDR3?" }, "running"))).toEqual({
      title: "Consulting Immunologist",
      detail: "Which CDR3?",
      code: null,
    });
    expect(summarize(call("consult", {})).title).toBe("Consulted a scientist");
  });

  it("is calling a tool by its name, with what it was given", () => {
    expect(summarize(call("blast_search", { sequence: "MKT" }, "running"))).toEqual({
      title: "Calling blast_search",
      detail: '{"sequence":"MKT"}',
      code: null,
    });
    expect(summarize(call("blast_search", {})).detail).toBeNull();
    expect(summarize(call("", "")).title).toBe("Called a tool");
  });

  it("is what a library tool does, with what it is about", () => {
    expect(summarize(call("pubmed_search", { query: "TP53\n nanobody", num_articles: 5 }, "running"))).toEqual({
      title: "Searching PubMed",
      detail: "TP53 nanobody",
      code: null,
    });
    expect(summarize(call("pubmed_search", { query: "TP53", num_articles: 5 }))).toMatchObject({ title: "Searched PubMed" });
    expect(summarize(call("uniprot_lookup", { accession: "P04637" }))).toMatchObject({
      title: "Looked up a protein",
      detail: "P04637",
    });
    expect(summarize(call("fetch_structure_file", { identifier: "1TUP", source: "pdb" }, "running"))).toMatchObject({
      title: "Downloading a structure",
      detail: "1TUP from pdb",
    });
    expect(summarize(call("fetch_structure_file", { identifier: "1TUP" })).detail).toBe("1TUP");
    expect(summarize(call("chembl_activities", { molecule_chembl_id: "CHEMBL25", activity_type: "IC50" })).detail).toBe(
      "CHEMBL25 · IC50",
    );
    expect(summarize(call("chembl_activities", { target_chembl_id: "CHEMBL1", molecule_chembl_id: "CHEMBL25" })).detail).toBe("CHEMBL1");
    expect(summarize(call("chembl_activities", {})).detail).toBeNull();
    expect(summarize(call("inspect_data_file", { filename: "uploads/a.xlsx", sheet: "Counts" }))).toMatchObject({
      title: "Inspected a data file",
      detail: "uploads/a.xlsx · Counts",
    });
    expect(summarize(call("data_files", {}, "running"))).toEqual({ title: "Listing the attached files", detail: null, code: null });
    expect(
      summarize(call("view_image", { path: "uploads/slides.pdf", question: "What is on the slide?", pages: [45, 46] }, "running")),
    ).toEqual({ title: "Looking at an image", detail: "uploads/slides.pdf, pages 45, 46 · What is on the slide?", code: null });
    expect(summarize(call("view_image", { path: "plots/a.png", question: "Values?", pages: [3] })).detail).toBe("plots/a.png, page 3 · Values?");
    expect(summarize(call("view_image", { path: "plots/a.png" }))).toMatchObject({ title: "Looked at an image", detail: "plots/a.png" });
  });

  it("is a library tool with nothing about it when what it was given is broken", () => {
    expect(summarize(call("europepmc_search", "{broken"))).toEqual({ title: "Searched Europe PMC", detail: null, code: null });
    expect(summarize(call("europepmc_search", { query: 4 })).detail).toBeNull();
  });

  it("is in the past once the call is not running, whether it was answered or cut short", () => {
    expect(summarize(call("run_code", {}, "interrupted")).title).toBe("Ran Python code");
    expect(summarize(call("consult", { member: "A" }, "interrupted")).title).toBe("Consulted A");
  });

  it("is shortened to one line", () => {
    const long = "word ".repeat(100);
    const detail = summarize(call("find_resources", { task: long })).detail ?? "";

    expect(detail.length).toBe(160);
    expect(detail.endsWith("…")).toBe(true);
    expect(detail).not.toContain("\n");
  });
});

const resources = (fields: Partial<Resources> = {}): Resources => ({ mode: "all", available: {}, selected: {}, task: null, ...fields });

describe("what the lead is told it has to work with", () => {
  it("is what it was told of, counted by kind and named", () => {
    expect(
      describeResources(
        resources({
          available: { tools: 9, data_lake: 9 },
          selected: { tools: ["m.a", "m.b"], data_lake: ["genes.csv"], libraries: ["numpy"], know_how: ["k1", "k2"] },
        }),
      ),
    ).toEqual({
      title: "Resources it can use",
      detail: "2 tools, 1 data file, 1 software package, 2 know-how documents",
      groups: [
        { label: "Tools", names: ["m.a", "m.b"] },
        { label: "Data files", names: ["genes.csv"] },
        { label: "Software", names: ["numpy"] },
        { label: "Know-how", names: ["k1", "k2"] },
      ],
    });
  });

  it("is what could be looked up, when it is to be asked for", () => {
    expect(describeResources(resources({ mode: "retrieve", available: { tools: 120, libraries: 1 }, selected: { tools: [] } }))).toEqual({
      title: "Resources it can look up",
      detail: "120 tools, 1 software package",
      groups: [],
    });
  });

  it("is what it can use, and not what it can look up, once something is named where it is to be asked for", () => {
    expect(describeResources(resources({ mode: "retrieve", available: { tools: 9 }, selected: { tools: ["m.a"] } }))).toMatchObject({
      title: "Resources it can use",
      detail: "1 tool",
    });
  });

  it("is what was chosen for a task, and what the task was", () => {
    expect(
      describeResources(resources({ mode: "retrieve", task: "Align\n reads", selected: { tools: ["m.a"], know_how: ["k1"] } })),
    ).toEqual({
      title: "Chose resources for a task",
      detail: "Align reads · 1 tool, 1 know-how document",
      groups: [
        { label: "Tools", names: ["m.a"] },
        { label: "Know-how", names: ["k1"] },
      ],
    });
    expect(describeResources(resources({ mode: "retrieve", task: "Nothing fits" })).detail).toBe("Nothing fits");
  });

  it("is none when there are none, and says what there are when none were named", () => {
    expect(describeResources(resources({ mode: "none", available: { tools: 5 } }))).toEqual({ title: "No resources", detail: null, groups: [] });
    expect(describeResources(resources({ available: { tools: 5 } })).detail).toBe("5 tools");
    expect(describeResources(resources({})).detail).toBeNull();
  });
});
