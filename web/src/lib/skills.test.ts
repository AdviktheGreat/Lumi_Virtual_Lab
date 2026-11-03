import { describe, expect, it } from "vitest";
import {
  choiceButtonText,
  choiceKept,
  choiceStart,
  disabledWhen,
  enabledNames,
  filesLeftOut,
  givenSkills,
  howManyChosen,
  howManyOn,
  matching,
  NOTHING_TO_PUT_IN_FROM,
  pickedWhen,
  putInSaid,
  skillsFrom,
  vanished,
  whereFound,
} from "./skills";
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
