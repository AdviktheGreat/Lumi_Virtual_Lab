import { describe, expect, it } from "vitest";
import {
  checkData,
  checkSoftware,
  dataFacts,
  descriptionProblem,
  EMPTY_DATA,
  MAX_DESCRIPTION,
  MAX_SOFTWARE_NAME,
  type DataDraft,
} from "./own";
import type { OwnData } from "./types";

const LIMIT = 20 * 1024;

function fileOf(name: string, size = 10): File {
  return new File([new Uint8Array(size)], name);
}

const upload: DataDraft = { way: "upload", file: fileOf("counts.csv"), path: "", description: "Gene counts" };
const point: DataDraft = { way: "path", file: null, path: "/data/counts.csv", description: "Gene counts" };

describe("saying what something is", () => {
  it("needs words, and does not count spaces and line breaks as them", () => {
    expect(descriptionProblem("", "it")).toBe("Say what it is, so that the lead knows when to use it.");
    expect(descriptionProblem(" \n\t ", "Samtools")).toBe("Say what Samtools is, so that the lead knows when to use it.");
    expect(descriptionProblem("Raw counts", "it")).toBeNull();
  });

  it("can be as long as the server takes, once the spaces are tidied, and no longer", () => {
    expect(descriptionProblem("a".repeat(MAX_DESCRIPTION), "it")).toBeNull();
    expect(descriptionProblem(`${"a".repeat(MAX_DESCRIPTION - 1)}   \n  `, "it")).toBeNull();
    expect(descriptionProblem("a".repeat(MAX_DESCRIPTION + 1), "it")).toBe(
      `What it is can be at most ${MAX_DESCRIPTION} characters, and this is ${MAX_DESCRIPTION + 1}.`,
    );
  });

  it("counts a character as one however it is stored, as the server does", () => {
    // Each of these is two UTF-16 units, and a character
    expect(descriptionProblem("🧬".repeat(MAX_DESCRIPTION), "it")).toBeNull();
    expect(descriptionProblem("🧬".repeat(MAX_DESCRIPTION + 1), "it")).toContain(`this is ${MAX_DESCRIPTION + 1}`);
  });
});

describe("whether data can be given", () => {
  it("can be, by uploading a file or by pointing to one, once it is said what it is", () => {
    expect(checkData(upload, [], LIMIT)).toEqual({});
    expect(checkData(point, [], LIMIT)).toEqual({});
  });

  it("says what is missing of a form that has not been filled in", () => {
    expect(checkData(EMPTY_DATA, [], LIMIT)).toEqual({
      source: "Choose the file to upload.",
      description: "Say what it is, so that the lead knows when to use it.",
    });
    expect(checkData({ ...EMPTY_DATA, way: "path", path: "  " }, [], LIMIT)).toEqual({
      source: "Give the full path of the file or folder.",
      description: "Say what it is, so that the lead knows when to use it.",
    });
  });

  it("looks at the file when uploading, and at the path when pointing, and not at the other", () => {
    expect(checkData({ ...point, file: fileOf("big.bin", LIMIT + 1) }, [], LIMIT)).toEqual({});
    expect(checkData({ ...upload, path: "" }, [], LIMIT)).toEqual({});
    expect(checkData({ ...upload, way: "path" }, [], LIMIT).source).toBe("Give the full path of the file or folder.");
  });

  it("takes a file as big as the limit, and refuses one that is a byte more, saying where to point to it", () => {
    expect(checkData({ ...upload, file: fileOf("exact.bin", LIMIT) }, [], LIMIT)).toEqual({});
    expect(checkData({ ...upload, file: fileOf("big.bin", LIMIT + 1) }, [], LIMIT).source).toBe(
      "big.bin is larger than the 20 KB that can be uploaded. Point to it where it is on this machine instead.",
    );
  });

  it("refuses a name that is taken, since code finds data by its name", () => {
    expect(checkData(upload, ["counts.csv"], LIMIT).source).toBe(
      "There is data named counts.csv already. Code finds data by its name, so delete that first, or rename the file.",
    );
    expect(checkData(upload, ["counts.csv.gz", "Counts.csv"], LIMIT)).toEqual({});
  });

  it("says the description is too long as well as the source is wrong", () => {
    const problems = checkData({ ...upload, file: null, description: "x".repeat(MAX_DESCRIPTION + 1) }, [], LIMIT);

    expect(Object.keys(problems)).toEqual(["source", "description"]);
  });
});

describe("what is said of a piece of data", () => {
  const now = new Date("2025-03-10T12:00:00Z");
  const seconds = now.getTime() / 1000;
  const data: OwnData = {
    name: "counts.csv",
    description: "Gene counts",
    source: "uploaded",
    path: null,
    kind: "file",
    bytes: 2048,
    modified: seconds - 3 * 3600,
  };

  it("says where it came from, how big it is, and when it was changed", () => {
    expect(dataFacts(data, now)).toBe("Uploaded · 2.0 KB · changed 3 h ago");
  });

  it("says a folder is one, without a size, and that what was pointed to is on this machine", () => {
    expect(dataFacts({ ...data, source: "path", kind: "folder", bytes: null }, now)).toBe(
      "On this machine · Folder · changed 3 h ago",
    );
  });

  it("says what is not there, and says nothing of a time it does not have", () => {
    expect(dataFacts({ ...data, source: "path", kind: "missing", bytes: null, modified: null }, now)).toBe(
      "On this machine · Not there",
    );
  });

  it("leaves out a size that the server could not tell", () => {
    expect(dataFacts({ ...data, bytes: null, modified: null }, now)).toBe("Uploaded");
  });
});

describe("whether software can be given", () => {
  const given = [{ name: "Samtools", description: "BAM files" }];

  it("can be, with its name and what it is for, tidy", () => {
    const checked = checkSoftware("  Sam   tools ", "Reads\n and  writes BAM", given, true);

    expect(checked.problems).toEqual({});
    expect(checked.software).toEqual({ name: "Sam tools", description: "Reads and writes BAM" });
  });

  it("says what is missing, and sends nothing", () => {
    const checked = checkSoftware(" ", "", given, true);

    expect(checked.software).toBeNull();
    expect(checked.problems).toEqual({
      name: "Name the software.",
      description: "Say what it is, so that the lead knows when to use it.",
    });
  });

  it("takes a name as long as the server does, and no longer", () => {
    expect(checkSoftware("n".repeat(MAX_SOFTWARE_NAME), "Tool", given, true).problems).toEqual({});
    expect(checkSoftware("n".repeat(MAX_SOFTWARE_NAME + 1), "Tool", given, true).problems.name).toBe(
      `The name can be at most ${MAX_SOFTWARE_NAME} characters, and this is ${MAX_SOFTWARE_NAME + 1}.`,
    );
  });

  it("is new only with a name that none has, but may be changed, which keeps it under the name it has", () => {
    expect(checkSoftware(" Samtools ", "Another", given, true).problems.name).toBe(
      "There is software named Samtools. Change that instead, or choose another name.",
    );
    expect(checkSoftware("samtools", "Another", given, true).problems).toEqual({});
    expect(checkSoftware("Samtools", "Another", given, false)).toEqual({
      software: { name: "Samtools", description: "Another" },
      problems: {},
    });
  });
});
