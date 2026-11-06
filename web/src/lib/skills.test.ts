import { describe, expect, it } from "vitest";
import {
  catalogAdded,
  catalogFilled,
  catalogSaid,
  choiceButtonText,
  choiceKept,
  choiceStart,
  disabledWhen,
  enabledNames,
  filesLeftOut,
  givenSkills,
  HUB_SHOWN,
  hubCounts,
  hubSaid,
  hubSkills,
  howManyChosen,
  howManyOn,
  licenseLabel,
  licenseNote,
  licenseWarnings,
  matching,
  matchingHub,
  NOTHING_TO_PUT_IN_FROM,
  pickedWhen,
  putInSaid,
  sizeSaid,
  skillsFrom,
  sourceLabel,
  tokensSaid,
  vanished,
  whereFound,
} from "./skills";
import type { LibrarySkill, LicenseKind, SkillsCatalog } from "./types";
import type { SkillInfo } from "./types";

const skill = (name: string, description = `${name} does something`, enabled = true): SkillInfo => ({
  name,
  description,
  source: "workspace",
  directory: `/skills/${name}`,
  license: null,
  compatibility: null,
  metadata: {},
  notes: [],
  enabled,
  removable: true,
});

const skills = [
  skill("dose-response", "Fits a dose-response curve to titration data."),
  skill("rna-seq", "Differential expression with DESeq2.", false),
  skill("Plot-Style", "Makes figures that follow the journal's style."),
];

describe("finding a skill", () => {
  it("is by every word written, in its name or its description, whatever the case", () => {
    expect(matching(skills, "dose curve").map((one) => one.name)).toEqual(["dose-response"]);
    expect(matching(skills, "DESEQ2").map((one) => one.name)).toEqual(["rna-seq"]);
    expect(matching(skills, "plot style").map((one) => one.name)).toEqual(["Plot-Style"]);
    expect(matching(skills, "journal fits").map((one) => one.name)).toEqual([]);
  });

  it("is all of them when nothing is written", () => {
    expect(matching(skills, "")).toBe(skills);
    expect(matching(skills, "   ")).toBe(skills);
  });

  it("is none when no skill has the words", () => {
    expect(matching(skills, "proteomics")).toEqual([]);
  });
});

describe("which skills are off", () => {
  it("are those that are off, and the names given turned off too when they are to be turned off", () => {
    expect(disabledWhen(skills, ["dose-response"], false)).toEqual(["dose-response", "rna-seq"]);
  });

  it("are those that are off, less the names given when they are to be turned on", () => {
    expect(disabledWhen(skills, ["rna-seq"], true)).toEqual([]);
  });

  it("stay in the order of the skills, and do not count a name that is not one", () => {
    expect(disabledWhen(skills, ["Plot-Style", "dose-response"], false)).toEqual(["dose-response", "rna-seq", "Plot-Style"]);
    expect(disabledWhen(skills, ["nothing"], false)).toEqual(["rna-seq"]);
  });
});

describe("how many skills are on", () => {
  it("is said as a person says it", () => {
    expect(howManyOn(skills)).toBe("3 skills, 2 on");
    expect(howManyOn(skills.map((one) => ({ ...one, enabled: true })))).toBe("3 skills, all on");
    expect(howManyOn(skills.map((one) => ({ ...one, enabled: false })))).toBe("3 skills, none on");
    expect(howManyOn([skill("only")])).toBe("1 skill, on");
    expect(howManyOn([skill("only", "x", false)])).toBe("1 skill, none on");
    expect(howManyOn([])).toBe("0 skills, all on");
  });
});

describe("what skills are put in from", () => {
  it("is the address of a repository, which begins with https", () => {
    expect(skillsFrom("  https://github.com/owner/skills  ")).toEqual({ from: { git: "https://github.com/owner/skills" } });
    expect(skillsFrom("HTTPS://github.com/owner/skills")).toEqual({ from: { git: "HTTPS://github.com/owner/skills" } });
  });

  it("is the full path of a folder, which begins with a slash or a tilde, or a drive", () => {
    expect(skillsFrom("/Users/me/skills")).toEqual({ from: { path: "/Users/me/skills" } });
    expect(skillsFrom("~/skills")).toEqual({ from: { path: "~/skills" } });
    expect(skillsFrom("C:\\Users\\me\\skills")).toEqual({ from: { path: "C:\\Users\\me\\skills" } });
  });

  it("is not another sort of address, which is said", () => {
    for (const written of ["http://example.org/skills.git", "git@github.com:owner/skills.git", "ssh://example.org/r", "file:///etc"]) {
      expect(skillsFrom(written)).toEqual({ problem: expect.stringContaining("https://") });
    }
  });

  it("is not a path that is not full, or nothing, or something with spaces in it", () => {
    expect(skillsFrom("skills/mine")).toEqual({ problem: NOTHING_TO_PUT_IN_FROM });
    expect(skillsFrom("   ")).toEqual({ problem: NOTHING_TO_PUT_IN_FROM });
    expect(skillsFrom("/Users/me/my skills")).toEqual({ problem: expect.stringContaining("spaces") });
  });
});

describe("what putting in skills did", () => {
  const some = { installed: [{ name: "a", left_out: 0 }, { name: "b", left_out: 3 }], skipped: [] };

  it("is said as a person says it", () => {
    expect(putInSaid(some)).toBe("Put in 2 skills.");
    expect(putInSaid({ installed: [{ name: "a", left_out: 0 }], skipped: [{ name: "b", reason: "x" }] })).toBe(
      "Put in 1 skill. 1 left.",
    );
    expect(putInSaid({ installed: [], skipped: [{ name: "b", reason: "x" }] })).toBe("Nothing new was put in: 1 left.");
    expect(putInSaid({ installed: [], skipped: [] })).toBe("Nothing was put in.");
  });

  it("says which skills had files that were too many or too big to copy", () => {
    expect(filesLeftOut(some)).toEqual([{ name: "b", left_out: 3 }]);
  });
});

describe("where a skill was found", () => {
  it("is said in words", () => {
    expect(whereFound("workspace")).toBe("The lab's skills");
    expect(whereFound("user")).toContain("other tools");
    expect(whereFound("builtin")).toBe("The skills that come with the lab");
    expect(whereFound("elsewhere")).toBe("elsewhere");
  });
});

describe("choosing the skills of a conversation", () => {
  it("begins with those that are on for new conversations", () => {
    expect(enabledNames(skills)).toEqual(["dose-response", "Plot-Style"]);
    expect([...choiceStart(skills, null)]).toEqual(["dose-response", "Plot-Style"]);
  });

  it("begins with what was chosen, less any skill that is not there any more", () => {
    expect([...choiceStart(skills, ["rna-seq", "gone"])]).toEqual(["rna-seq"]);
    expect([...choiceStart(skills, [])]).toEqual([]);
  });

  it("is kept as nothing where it is what new conversations are given, however it was got to", () => {
    expect(choiceKept(skills, new Set(["Plot-Style", "dose-response"]))).toBeNull();
    expect(choiceKept(skills, new Set(["dose-response"]))).toEqual(["dose-response"]);
    expect(choiceKept(skills, new Set(["dose-response", "rna-seq", "Plot-Style"]))).toEqual([
      "dose-response",
      "rna-seq",
      "Plot-Style",
    ]);
    expect(choiceKept(skills, new Set())).toEqual([]);
  });

  it("is kept as nothing for no skills where none is on, and as the names where one is chosen", () => {
    const none = [skill("a", "A", false), skill("b", "B", false)];

    expect(choiceKept(none, new Set())).toBeNull();
    expect(choiceKept(none, new Set(["b"]))).toEqual(["b"]);
  });

  it("is kept in the order the skills are listed, whatever the order of choosing", () => {
    expect(choiceKept(skills, new Set(["Plot-Style", "rna-seq"]))).toEqual(["rna-seq", "Plot-Style"]);
  });

  it("finds the names chosen of skills that were taken away since, in the order they were chosen", () => {
    expect(vanished(skills, ["rna-seq", "gone", "dose-response", "also-gone"])).toEqual(["gone", "also-gone"]);
    expect(vanished(skills, ["rna-seq"])).toEqual([]);
    expect(vanished(skills, [])).toEqual([]);
    expect(vanished([], ["a"])).toEqual(["a"]);
  });

  it("is changed for each name given and for no other, without changing what it was", () => {
    const was = new Set(["a", "b"]);

    expect([...pickedWhen(was, ["c", "a"], true)].sort()).toEqual(["a", "b", "c"]);
    expect([...pickedWhen(was, ["a", "z"], false)]).toEqual(["b"]);
    expect([...was]).toEqual(["a", "b"]);
  });

  it("says how many are chosen as a person says it", () => {
    expect(howManyChosen(0, 0)).toBe("No skills");
    expect(howManyChosen(0, 5)).toBe("No skill chosen, of 5");
    expect(howManyChosen(1, 1)).toBe("The 1 skill is chosen");
    expect(howManyChosen(5, 5)).toBe("All 5 skills are chosen");
    expect(howManyChosen(2, 5)).toBe("2 of 5 skills chosen");
  });

  it("says nothing of the choice on the button until one is made", () => {
    expect(choiceButtonText(null)).toBe("Skills");
    expect(choiceButtonText([])).toBe("Skills · none");
    expect(choiceButtonText(["a", "b"])).toBe("Skills · 2");
  });
});

describe("the skills a conversation was given", () => {
  it("are each shown with what it is for now, and one that is not there any more with null", () => {
    expect(givenSkills(skills, ["rna-seq", "gone", "dose-response"])).toEqual([
      { name: "rna-seq", description: "Differential expression with DESeq2." },
      { name: "gone", description: null },
      { name: "dose-response", description: "Fits a dose-response curve to titration data." },
    ]);
  });
});

const librarySkill = (
  name: string,
  category: string,
  description = `${name} does something`,
  license_kind: LicenseKind = "other",
  license: string | null = "MIT",
): LibrarySkill => ({
  name,
  description,
  group: "Packages",
  category,
  license,
  license_kind,
  compatibility: null,
  files: 2,
  bytes: 1500,
  installed: false,
});

const library = [
  librarySkill("scanpy", "Bioinformatics & Genomics", "Single-cell analysis with Scanpy."),
  librarySkill("rdkit", "Cheminformatics & Drug Discovery", "Molecules and fingerprints."),
  librarySkill("pydeseq2", "Bioinformatics & Genomics", "Differential expression."),
];

const builtIn = (name: string): SkillInfo => ({ ...skill(name), source: "builtin", removable: false });

describe("the skills the Skills page shows", () => {
  const have = [
    builtIn("sample-ids-and-pca"),
    skill("my-protocol", "Our lab's own protocol."),
    skill("scanpy", "Single-cell analysis with Scanpy.", false),
  ];
  const all = hubSkills(have, library);

  it("are those the lab has, in its order, and then those of the library that it does not", () => {
    expect(all.map((each) => each.name)).toEqual(["sample-ids-and-pca", "my-protocol", "scanpy", "rdkit", "pydeseq2"]);
    expect(all.filter((each) => each.info === null).map((each) => each.name)).toEqual(["rdkit", "pydeseq2"]);
  });

  it("say where each comes from: built in, the library, or the person's own", () => {
    expect(all.map((each) => each.source)).toEqual(["builtin", "mine", "library", "library", "library"]);
    expect(sourceLabel("mine")).toBe("Mine");
    expect(sourceLabel("builtin")).toBe("Built in");
    expect(sourceLabel("library")).toBe("Library");
  });

  it("show a skill of the library that the lab has once, as the lab's copy, with the category the library gives it", () => {
    const scanpy = all.filter((each) => each.name === "scanpy");
    expect(scanpy).toHaveLength(1);
    expect(scanpy[0].info?.enabled).toBe(false);
    expect(scanpy[0].category).toBe("Bioinformatics & Genomics");
    expect(all[1].category).toBeNull();
  });

  it("are counted by source, whatever is searched for", () => {
    expect(hubCounts(all)).toEqual({ all: 5, mine: 1, builtin: 1, library: 3 });
    expect(hubCounts([])).toEqual({ all: 0, mine: 0, builtin: 0, library: 0 });
  });

  it("are found by every word written, in the name, description, or category, whatever the case", () => {
    expect(matchingHub(all, "single CELL", "", "").map((each) => each.name)).toEqual(["scanpy"]);
    expect(matchingHub(all, "drug", "", "").map((each) => each.name)).toEqual(["rdkit"]);
    expect(matchingHub(all, "bioinformatics expression", "", "").map((each) => each.name)).toEqual(["pydeseq2"]);
    expect(matchingHub(all, "  ", "", "")).toHaveLength(5);
  });

  it("are narrowed to a source, and to a category, which only the library's skills have", () => {
    expect(matchingHub(all, "", "mine", "").map((each) => each.name)).toEqual(["my-protocol"]);
    expect(matchingHub(all, "", "builtin", "").map((each) => each.name)).toEqual(["sample-ids-and-pca"]);
    expect(matchingHub(all, "", "library", "Bioinformatics & Genomics").map((each) => each.name)).toEqual(["scanpy", "pydeseq2"]);
    expect(matchingHub(all, "differential", "", "Cheminformatics & Drug Discovery")).toEqual([]);
    expect(matchingHub(all, "", "mine", "Bioinformatics & Genomics")).toEqual([]);
  });

  it("are said as how many there are, of how many, and how many of those the lab has on", () => {
    expect(hubSaid(all, 5)).toBe("5 skills, 2 on");
    expect(hubSaid(matchingHub(all, "", "library", ""), 5)).toBe("3 of 5 skills, 0 on");
    expect(hubSaid(matchingHub(all, "drug", "", ""), 5)).toBe("1 of 5 skills");
    expect(hubSaid(matchingHub(all, "protocol", "", ""), 1)).toBe("1 skill, 1 on");
  });

  it("are listed in whole rows of one, two, and three columns", () => {
    expect(HUB_SHOWN % 6).toBe(0);
  });
});

describe("what a license is said to be", () => {
  it("has a note where a person ought to know something before using the skill, and none where not", () => {
    expect(licenseNote("noncommercial")).toMatch(/noncommercial use only/);
    expect(licenseNote("copyleft")).toMatch(/GPL/);
    expect(licenseNote("none")).toMatch(/MIT license/);
    expect(licenseNote("other")).toBeNull();
  });

  it("is a label as written, without the word license, cut where it is long, and says so where there is none", () => {
    expect(licenseLabel(librarySkill("a", "c", "d", "other", "MIT license"))).toBe("MIT");
    expect(licenseLabel(librarySkill("a", "c", "d", "other", "Apache-2.0"))).toBe("Apache-2.0");
    expect(licenseLabel(librarySkill("a", "c", "d", "none", "Unknown"))).toBe("No license stated");
    expect(licenseLabel(librarySkill("a", "c", "d", "none", null))).toBe("No license stated");
    expect(licenseLabel(librarySkill("a", "c", "d", "other", "https://github.com/sympy/sympy/blob/master/LICENSE"))).toBe("License at a link");
    const long = licenseLabel(librarySkill("a", "c", "d", "other", "This skill is provided under the MIT License. IDC data has its own."));
    expect(long.length).toBeLessThanOrEqual(28);
    expect(long.endsWith("…")).toBe(true);
  });

  it("is warned of in a sentence for each kind that has something to say, naming the skills", () => {
    const chosen = [
      librarySkill("deepspot-m", "c", "d", "noncommercial"),
      librarySkill("what-if-oracle", "c", "d", "noncommercial"),
      librarySkill("cobrapy", "c", "d", "copyleft"),
      librarySkill("primekg", "c", "d", "none"),
      librarySkill("pyhealth", "c", "d", "none"),
      librarySkill("scanpy", "c"),
    ];

    expect(licenseWarnings(chosen)).toEqual([
      "deepspot-m and what-if-oracle allow noncommercial use only.",
      "cobrapy is under a GPL license, which sets conditions on sharing it.",
      "primekg and pyhealth state no license, so only the library's MIT license covers them.",
    ]);
    expect(licenseWarnings([librarySkill("scanpy", "c")])).toEqual([]);
    expect(licenseWarnings([librarySkill("solo", "c", "d", "noncommercial")])).toEqual(["solo allows noncommercial use only."]);
    expect(licenseWarnings([librarySkill("solo", "c", "d", "none")])).toEqual(["solo states no license, so only the library's MIT license covers it."]);
  });

  it("names three skills and counts the rest", () => {
    const many = ["a", "b", "c", "d", "e"].map((name) => librarySkill(name, "c", "d", "copyleft"));

    expect(licenseWarnings(many)).toEqual(["a, b, c and 2 more are under GPL licenses, which set conditions on sharing them."]);
  });
});

describe("how big things are said to be", () => {
  it("is in bytes, kilobytes, or megabytes, as a person reads it", () => {
    expect(sizeSaid(0)).toBe("0 bytes");
    expect(sizeSaid(999)).toBe("999 bytes");
    expect(sizeSaid(1500)).toBe("2 KB");
    expect(sizeSaid(406_610)).toBe("407 KB");
    expect(sizeSaid(1_134_736)).toBe("1.1 MB");
  });

  it("says about how many tokens a number of characters is, rounded where there are many", () => {
    expect(tokensSaid(80)).toBe("about 20 tokens");
    expect(tokensSaid(3999)).toBe("about 1,000 tokens");
    expect(tokensSaid(20_000)).toBe("about 5,000 tokens");
    expect(tokensSaid(21_700)).toBe("about 5,400 tokens");
  });
});

describe("what the skills that are on take of every conversation", () => {
  const catalog = (changes: Partial<SkillsCatalog>): SkillsCatalog => ({
    skills: 7,
    chars: 2400,
    budget: 20_000,
    description_chars: 250,
    without_description: 0,
    ...changes,
  });

  it("is said where there is room, without advice", () => {
    expect(catalogSaid(catalog({}))).toEqual({
      text: "The 7 skills that are on take about 600 tokens of the start of every conversation.",
      tight: false,
    });
    expect(catalogSaid(catalog({ skills: 1, chars: 120 })).text).toBe(
      "The skill that is on takes about 30 tokens of the start of every conversation.",
    );
  });

  it("says that none is on", () => {
    expect(catalogSaid(catalog({ skills: 0, chars: 0 }))).toEqual({
      text: "No skill is on, so no conversation begins with a list of skills.",
      tight: false,
    });
  });

  it("says where there is not room, that descriptions are cut, and to turn some off", () => {
    const said = catalogSaid(catalog({ skills: 184, chars: 19_900, description_chars: 95 }));

    expect(said.tight).toBe(true);
    expect(said.text).toContain("The 184 skills that are on take about 5,000 tokens");
    expect(said.text).toContain("The list has room for 20,000 characters, so descriptions are cut to 95 characters.");
    expect(said.text).toContain("Turn some off to give the rest more room.");
  });

  it("says how many are listed by name only", () => {
    expect(catalogSaid(catalog({ skills: 500, description_chars: 60, without_description: 1 })).text).toContain(
      "cut to 60 characters, and 1 skill is listed by name only.",
    );
    expect(catalogSaid(catalog({ skills: 500, description_chars: 60, without_description: 31 })).text).toContain(
      "and 31 skills are listed by name only.",
    );
  });

  it("is how full the list is, never more than full", () => {
    expect(catalogFilled(catalog({ chars: 5000 }))).toBe(0.25);
    expect(catalogFilled(catalog({ chars: 30_000 }))).toBe(1);
    expect(catalogFilled(catalog({ budget: 0 }))).toBe(0);
  });

  it("is added to by skills put in, each with its name and as much of its description as is listed", () => {
    const short = librarySkill("abc", "c", "Does a thing.");
    const long = librarySkill("abcd", "c", "x".repeat(400));

    expect(catalogAdded([short])).toBe(3 + 5 + 13);
    expect(catalogAdded([short, long])).toBe(3 + 5 + 13 + 4 + 5 + 250);
    expect(catalogAdded([])).toBe(0);
  });
});
