import { describe, expect, it } from "vitest";
import {
  disabledWhen,
  filesLeftOut,
  howManyOn,
  matching,
  NOTHING_TO_PUT_IN_FROM,
  putInSaid,
  skillsFrom,
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
    expect(whereFound("elsewhere")).toBe("elsewhere");
  });
});
