import { describe, expect, it } from "vitest";
import {
  FOLDER_MAX_BYTES,
  FOLDER_MAX_FILES,
  folderFromDrop,
  folderFromInput,
  folderProblem,
  folderSize,
  isPassedOver,
  skillFields,
  skillsIn,
  type DroppedEntry,
  type DroppedFolder,
  type FolderFile,
  type Picked,
  type PickedFolder,
} from "./skill-folder";

function file(content: string | Uint8Array, name = "x"): File {
  return new File([content as BlobPart], name);
}

function chosen(path: string, content = "x"): File {
  const made = file(content, path.split("/").pop());
  Object.defineProperty(made, "webkitRelativePath", { value: path });

  return made;
}

function picked(result: Picked): PickedFolder {
  if ("problem" in result) throw new Error(result.problem);

  return result.folder;
}

function entryFile(name: string, content = "x"): DroppedEntry {
  return { isFile: true, isDirectory: false, name, file: (done) => done(file(content, name)) };
}

// A dropped folder whose reader gives its entries a few at a time, as a browser's does
function entryFolder(name: string, entries: DroppedEntry[], at = 3): DroppedFolder {
  return {
    isFile: false,
    isDirectory: true,
    name,
    createReader() {
      let next = 0;

      return {
        readEntries(done) {
          done(entries.slice(next, next + at));
          next += at;
        },
      };
    },
  };
}

function pickedWith(paths: string[], size = 1): PickedFolder {
  const files: FolderFile[] = paths.map((path) => ({ path, file: file("x".repeat(size), path) }));

  return { name: "fit", files, bytes: files.length * size, passedOver: 0, tooMany: false };
}

describe("what of a folder is not sent", () => {
  it("is what a repository holds that a skill does not need", () => {
    expect(isPassedOver(".git/config")).toBe(true);
    expect(isPassedOver("a/node_modules/b.js")).toBe(true);
    expect(isPassedOver("scripts/__pycache__/fit.pyc")).toBe(true);
    expect(isPassedOver(".DS_Store")).toBe(true);
    expect(isPassedOver("scripts/.DS_Store")).toBe(true);
  });

  it("is not a file that has the name of such a folder, or a folder that only begins with it", () => {
    expect(isPassedOver("scripts/fit.py")).toBe(false);
    expect(isPassedOver("SKILL.md")).toBe(false);
    expect(isPassedOver("venv")).toBe(false);
    expect(isPassedOver("venvs/a.txt")).toBe(false);
    expect(isPassedOver(".github/workflows/a.yml")).toBe(false);
  });
});

describe("a folder that was chosen", () => {
  it("is named by the folder, with each file where it is in it", () => {
    const folder = picked(folderFromInput([chosen("fit/SKILL.md", "abc"), chosen("fit/scripts/fit.py", "de")]));

    expect(folder.name).toBe("fit");
    expect(folder.files.map((each) => each.path)).toEqual(["SKILL.md", "scripts/fit.py"]);
    expect(folder.bytes).toBe(5);
    expect(folder.passedOver).toBe(0);
  });

  it("leaves out what is not sent, and says how much", () => {
    const folder = picked(folderFromInput([chosen("fit/SKILL.md"), chosen("fit/.git/config"), chosen("fit/.DS_Store")]));

    expect(folder.files.map((each) => each.path)).toEqual(["SKILL.md"]);
    expect(folder.passedOver).toBe(2);
  });

  it("is a problem when it is empty", () => {
    expect(folderFromInput([])).toEqual({ problem: "There was nothing in that folder." });
  });

  it("is called skill when the browser does not say what the folder is called", () => {
    expect(picked(folderFromInput([file("x", "SKILL.md")])).name).toBe("skill");
  });
});

describe("a folder that was dropped", () => {
  it("is walked to the files in it and below it, each by where it is in the folder", async () => {
    const dropped = entryFolder("fit", [
      entryFile("SKILL.md", "abc"),
      entryFolder("scripts", [entryFile("fit.py", "de"), entryFolder("deep", [entryFile("a.txt")])]),
    ]);

    const folder = picked(await folderFromDrop([dropped]));

    expect(folder.name).toBe("fit");
    expect(folder.files.map((each) => each.path).sort()).toEqual(["SKILL.md", "scripts/deep/a.txt", "scripts/fit.py"]);
    expect(folder.bytes).toBe(6);
  });

  it("is read to the end, though a reader gives only a few entries at a time", async () => {
    const entries = Array.from({ length: 250 }, (_, number) => entryFile(`f${number}.txt`));

    const folder = picked(await folderFromDrop([entryFolder("many", entries, 100)]));

    expect(folder.files).toHaveLength(250);
  });

  it("is not walked into where it is a folder that is not sent", async () => {
    let read = false;
    const modules: DroppedFolder = {
      ...entryFolder("node_modules", []),
      createReader() {
        read = true;

        return { readEntries: (done) => done([]) };
      },
    };

    const folder = picked(await folderFromDrop([entryFolder("fit", [entryFile("SKILL.md"), modules, entryFile(".DS_Store")])]));

    expect(folder.files.map((each) => each.path)).toEqual(["SKILL.md"]);
    expect(folder.passedOver).toBe(2);
    expect(read).toBe(false);
  });

  it("stops being read when it has more files than can be put in", async () => {
    const entries = Array.from({ length: FOLDER_MAX_FILES + 5 }, (_, number) => entryFile(`f${number}.txt`));

    const folder = picked(await folderFromDrop([entryFolder("big", entries, 500)]));

    expect(folder.tooMany).toBe(true);
    expect(folder.files).toHaveLength(FOLDER_MAX_FILES);
    expect(folderProblem(folder)).toContain("more than 2,000 files");
  });

  it("is a problem when it is not one folder", async () => {
    expect(await folderFromDrop([])).toEqual({ problem: "Nothing was dropped." });
    expect(await folderFromDrop([entryFolder("a", []), entryFolder("b", [])])).toEqual({
      problem: "Drop one folder, and not several things.",
    });
    expect(await folderFromDrop([entryFile("SKILL.md")])).toEqual({
      problem: "SKILL.md is a file. Drop the folder that the skill is in, which has a SKILL.md in it.",
    });
    expect(await folderFromDrop([entryFolder("empty", [])])).toEqual({ problem: "There was nothing in that folder." });
  });

  it("is a problem when it cannot be read", async () => {
    const unreadable: DroppedFolder = {
      isFile: false,
      isDirectory: true,
      name: "locked",
      createReader: () => ({ readEntries: (_, failed) => failed(new Error("no")) }),
    };

    expect(await folderFromDrop([unreadable])).toEqual({ problem: "That folder could not be read. Try choosing it instead." });
  });
});

describe("what is wrong with a folder before it is sent", () => {
  it("is nothing when it has a SKILL.md, at its top or below", () => {
    expect(folderProblem(pickedWith(["SKILL.md", "scripts/fit.py"]))).toBeNull();
    expect(folderProblem(pickedWith(["skills/fit/SKILL.md"]))).toBeNull();
  });

  it("is that there is none, which is not made up for by a file that is called almost that", () => {
    expect(folderProblem(pickedWith(["README.md", "skill.md", "SKILL.md.txt"]))).toBe(
      "There is no SKILL.md in fit. A skill is a folder with a SKILL.md in it, which says what it is called and for.",
    );
  });

  it("is that it has too many files or too many bytes", () => {
    expect(folderProblem({ ...pickedWith(["SKILL.md"]), tooMany: true })).toContain("more than 2,000 files");
    expect(folderProblem(pickedWith(["SKILL.md"], FOLDER_MAX_BYTES + 1))).toBe(
      "fit is 50 MB, and no more than 50 MB can be put in. Choose a smaller folder.",
    );
  });
});

describe("how big a folder is said to be", () => {
  it("is in thousands and millions of bytes, as the most that can be put in is", () => {
    expect(folderSize(0)).toBe("0 B");
    expect(folderSize(999)).toBe("999 B");
    expect(folderSize(1_500)).toBe("2 KB");
    expect(folderSize(2_400_000)).toBe("2.4 MB");
    expect(folderSize(49_600_000)).toBe("50 MB");
    expect(folderSize(FOLDER_MAX_BYTES)).toBe("50 MB");
  });
});

describe("what a SKILL.md says at its top", () => {
  it("is its name and description", () => {
    expect(skillFields("---\nname: fit\ndescription: Fits a curve.\nlicense: MIT\n---\n\n# Fit\n")).toEqual({
      name: "fit",
      description: "Fits a curve.",
    });
  });

  it("is read with quotes taken off, a description that goes on over lines, and a block of text", () => {
    expect(skillFields('---\nname: "fit"\ndescription: Fits a curve,\n  and reports the IC50.\n---\n')).toEqual({
      name: "fit",
      description: "Fits a curve, and reports the IC50.",
    });
    expect(skillFields("---\nname: fit\ndescription: >-\n  Fits a curve.\n  Use it for potency.\nlicense: MIT\n---\n")).toEqual({
      name: "fit",
      description: "Fits a curve. Use it for potency.",
    });
    expect(skillFields("---\r\nname: fit\r\ndescription: 'Fits.'\r\n---\r\nBody")).toEqual({ name: "fit", description: "Fits." });
  });

  it("keeps a colon in a description that was not quoted, as the server does", () => {
    expect(skillFields("---\nname: fit\ndescription: Use it when: a potency is asked for\n---\n").description).toBe(
      "Use it when: a potency is asked for",
    );
  });

  it("is nothing for a field that is not there, or where there is no YAML at the top", () => {
    expect(skillFields("---\nname: fit\n---\n")).toEqual({ name: "fit", description: null });
    expect(skillFields("# Fit\n\nname: fit\ndescription: not at the top")).toEqual({ name: null, description: null });
    expect(skillFields("---\nname: fit\nno end to it")).toEqual({ name: null, description: null });
  });

  it("is not read from what is indented under another field, which is its own", () => {
    expect(skillFields("---\nmetadata:\n  name: other\nname: fit\ndescription: d\n---\n")).toEqual({ name: "fit", description: "d" });
  });
});

describe("the skills a folder has", () => {
  const skill = (name: string, description: string) => `---\nname: ${name}\ndescription: ${description}\n---\nBody`;

  function folderOfSkills(files: Record<string, string>, name = "fit"): PickedFolder {
    const made = Object.entries(files).map(([path, content]) => ({ path, file: file(content, path.split("/").pop()) }));

    return { name, files: made, bytes: 0, passedOver: 0, tooMany: false };
  }

  it("is one, where the SKILL.md is at the top", async () => {
    const found = await skillsIn(folderOfSkills({ "SKILL.md": skill("fit", "Fits."), "scripts/fit.py": "x" }));

    expect(found).toEqual({ skills: [{ path: "SKILL.md", name: "fit", description: "Fits." }], more: 0 });
  });

  it("is each below, the nearest first, called what its SKILL.md says or what its folder is", async () => {
    const found = await skillsIn(
      folderOfSkills({
        "skills/b/SKILL.md": skill("beta", "Second."),
        "skills/a/SKILL.md": "---\ndescription: First, with no name.\n---\n",
        "top/SKILL.md": skill("top", "Nearer."),
      }),
    );

    expect(found.skills.map((each) => [each.path, each.name, each.description])).toEqual([
      ["top/SKILL.md", "top", "Nearer."],
      ["skills/a/SKILL.md", "a", "First, with no name."],
      ["skills/b/SKILL.md", "beta", "Second."],
    ]);
  });

  it("is called what the folder is, where the SKILL.md at its top has no name", async () => {
    const found = await skillsIn(folderOfSkills({ "SKILL.md": "---\ndescription: Fits.\n---\n" }, "my-skill"));

    expect(found.skills[0].name).toBe("my-skill");
  });

  it("is not one that is deeper than the server looks, and not a file that only has the name in it", async () => {
    const found = await skillsIn(
      folderOfSkills({ "a/b/c/d/e/f/SKILL.md": skill("deep", "Too deep."), "a/SKILL.md.bak": "x", "a/b/SKILL.md": skill("ok", "Ok.") }),
    );

    expect(found.skills.map((each) => each.name)).toEqual(["ok"]);
  });

  it("is shown up to a number, with how many are not", async () => {
    const files: Record<string, string> = {};
    for (let number = 0; number < 53; number++) files[`skills/s${String(number).padStart(2, "0")}/SKILL.md`] = skill(`s${number}`, "x");

    const found = await skillsIn(folderOfSkills(files));

    expect(found.skills).toHaveLength(50);
    expect(found.more).toBe(3);
  });
});
