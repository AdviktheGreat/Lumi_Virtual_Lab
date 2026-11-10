import { describe, expect, it } from "vitest";
import {
  checkDataFetch,
  checkedBy,
  describeCandidate,
  describeChecksum,
  describeDataLicense,
  describeKept,
  describeKeptCheck,
  describeOwn,
  describeSaid,
  emptyDataFetch,
  fetchable,
  keptNames,
  MAX_REFERENCE_CHARS,
  MEGABYTE,
  otherStandIns,
  referenceProblem,
  shortDigest,
  standInPresent,
  totalBytes,
  whyNot,
} from "./paperagent-data";
import type { DataCandidate, DataFileListed, PaperAgentData } from "./types";

const LIMITS: PaperAgentData["limits"] = { default_megabytes: 500, min_megabytes: 1, max_megabytes: 20_000, max_kept_megabytes: 50_000, max_files: 100 };

function file(changes: Partial<DataFileListed> = {}): DataFileListed {
  return { name: "counts.csv", bytes: 1000, checksum: { algorithm: "md5", value: "a".repeat(32) }, downloadable: true, why: null, kept: false, ...changes };
}

function candidate(changes: Partial<DataCandidate> = {}): DataCandidate {
  return {
    key: "zenodo:1",
    source: "zenodo",
    reference: "1",
    label: "Zenodo record 1",
    url: "https://zenodo.org/records/1",
    supported: true,
    reason: null,
    facts: [],
    in_code: false,
    fetched: 0,
    ...changes,
  };
}

function data(changes: Partial<PaperAgentData> = {}): PaperAgentData {
  return {
    id: "cells",
    read: true,
    datasets: [],
    candidates: [],
    stand_ins: [],
    own: [],
    kept: { files: 0, bytes: 0, sources: [] },
    sources: [],
    job: null,
    limits: LIMITS,
    ...changes,
  };
}

describe("what can be chosen to fetch", () => {
  it("is a file that the place gives to anyone, says how big it is, and is not kept", () => {
    const none = new Set<string>();

    expect(fetchable(file(), none)).toBe(true);
    expect(fetchable(file({ downloadable: false, why: "needs an account" }), none)).toBe(false);
    expect(fetchable(file({ bytes: null }), none)).toBe(false);
    expect(fetchable(file(), new Set(["counts.csv"]))).toBe(false);
  });

  it("says in a few words why a file is not one to choose", () => {
    expect(whyNot(file(), new Set())).toBeNull();
    expect(whyNot(file(), new Set(["counts.csv"]))).toBe("Kept already");
    expect(whyNot(file({ downloadable: false, why: "needs an account" }), new Set())).toBe("needs an account");
    expect(whyNot(file({ downloadable: false, why: null }), new Set())).toBe("The place does not give it");
    expect(whyNot(file({ bytes: null }), new Set())).toBe("The place does not say how big it is");
  });

  it("adds up what the files that say how big they are come to", () => {
    expect(totalBytes([file({ bytes: 10 }), file({ bytes: null }), file({ bytes: 5 })])).toBe(15);
    expect(totalBytes([])).toBe(0);
  });

  it("counts the files that are checked by a checksum and those that are checked by their size only", () => {
    expect(checkedBy([file(), file({ checksum: null }), file({ checksum: null })])).toEqual({ checksum: 1, size: 2 });
    expect(checkedBy([])).toEqual({ checksum: 0, size: 0 });
  });

  it("says how a file will be checked, as the place allows", () => {
    expect(describeChecksum(file())).toBe("MD5 checksum given, which it is checked by");
    expect(describeChecksum(file({ checksum: { algorithm: "sha256", value: "b".repeat(64) } }))).toBe("SHA-256 checksum given, which it is checked by");
    expect(describeChecksum(file({ checksum: null }))).toBe("No checksum is given, so it is checked by its size only");
  });
});

describe("what fetching is asked for", () => {
  it("starts at the usual most", () => {
    expect(emptyDataFetch(LIMITS)).toEqual({ megabytes: "500" });
  });

  it("is the place, the files by name, what they come to, and the most, once something is chosen", () => {
    const checked = checkDataFetch("https://zenodo.org/records/1", [file({ name: "a", bytes: 10 }), file({ name: "b", bytes: 20 })], { megabytes: "5" }, LIMITS);

    expect(checked.problems).toEqual({});
    expect(checked.value).toEqual({ reference: "https://zenodo.org/records/1", files: ["a", "b"], expected_bytes: 30, max_megabytes: 5 });
  });

  it("is nothing until a file is chosen", () => {
    const checked = checkDataFetch("x", [], { megabytes: "500" }, LIMITS);

    expect(checked.value).toBeNull();
    expect(checked.problems.files).toBe("Choose at least one file.");
  });

  it("is nothing for more files than may be fetched at once", () => {
    const many = Array.from({ length: 101 }, (_, place) => file({ name: `f${place}`, bytes: 1 }));

    expect(checkDataFetch("x", many, { megabytes: "500" }, LIMITS).problems.files).toBe("At most 100 files can be fetched at once.");
    expect(checkDataFetch("x", many.slice(0, 100), { megabytes: "500" }, LIMITS).value).not.toBeNull();
  });

  it("holds the most to a whole number in the range that the server takes", () => {
    for (const typed of ["", "0", "-1", "1.5", "abc", "20001", "1e3"]) {
      const checked = checkDataFetch("x", [file()], { megabytes: typed }, LIMITS);

      expect(checked.value, typed).toBeNull();
      expect(checked.problems.megabytes, typed).toBe("The most to fetch, in megabytes, is a whole number from 1 to 20000.");
    }
    expect(checkDataFetch("x", [file()], { megabytes: " 20000 " }, LIMITS).value?.max_megabytes).toBe(20_000);
  });

  it("is nothing when what is chosen comes to more than the most, and says by how much it comes", () => {
    const checked = checkDataFetch("x", [file({ bytes: 3 * MEGABYTE })], { megabytes: "2" }, LIMITS);

    expect(checked.value).toBeNull();
    expect(checked.problems.megabytes).toBe("These files come to 3.0 MB, which is more than the 2.0 MB that may be fetched. Choose fewer, or raise the most.");
  });

  it("allows exactly the most", () => {
    expect(checkDataFetch("x", [file({ bytes: 2 * MEGABYTE })], { megabytes: "2" }, LIMITS).value?.expected_bytes).toBe(2 * MEGABYTE);
    expect(checkDataFetch("x", [file({ bytes: 2 * MEGABYTE + 1 })], { megabytes: "2" }, LIMITS).value).toBeNull();
  });

  it("says each thing that is wrong at once", () => {
    const checked = checkDataFetch("x", [], { megabytes: "0" }, LIMITS);

    expect(Object.keys(checked.problems).sort()).toEqual(["files", "megabytes"]);
  });
});

describe("a place that is typed", () => {
  it("must be something, and not more than the server takes", () => {
    expect(referenceProblem("")).toMatch(/^Say where the data is/);
    expect(referenceProblem("   ")).toMatch(/^Say where the data is/);
    expect(referenceProblem("GSE12345")).toBeNull();
    expect(referenceProblem("x".repeat(MAX_REFERENCE_CHARS))).toBeNull();
    expect(referenceProblem("x".repeat(MAX_REFERENCE_CHARS + 1))).toBe("That is more than 500 characters.");
  });
});

describe("what is kept", () => {
  const source = (key: string, names: string[]) => ({
    key,
    source: "zenodo",
    reference: "1",
    label: "Zenodo record 1",
    url: "https://zenodo.org/records/1",
    title: "Atlas",
    license: null,
    folder: "zenodo/1",
    files: names.map((name) => ({ name, path: `zenodo/1/${name}`, bytes: 1, sha256: "0".repeat(64), checksum: null, url: "x", fetched_at: "", present: true })),
  });

  it("is the names of the files of one place, and none of another's", () => {
    const kept = data({ kept: { files: 3, bytes: 3, sources: [source("zenodo:1", ["a", "b"]), source("zenodo:2", ["c"])] } });

    expect([...keptNames(kept, "zenodo:1")].sort()).toEqual(["a", "b"]);
    expect([...keptNames(kept, "zenodo:2")]).toEqual(["c"]);
    expect(keptNames(kept, "geo:GSE1").size).toBe(0);
  });

  it("is told by how many files and how big they are", () => {
    expect(describeKept({ files: 0, bytes: 0 })).toBe("No files are kept");
    expect(describeKept({ files: 1, bytes: 2048 })).toBe("1 file, 2.0 KB");
    expect(describeKept({ files: 3, bytes: 3 * MEGABYTE })).toBe("3 files, 3.0 MB");
  });

  it("says how far a file was checked, and no further", () => {
    expect(describeKeptCheck({ checksum: { algorithm: "md5", value: "a".repeat(32) } })).toBe("Matched the MD5 that the place gave");
    expect(describeKeptCheck({ checksum: { algorithm: "sha256", value: "a".repeat(64) } })).toBe("Matched the SHA-256 that the place gave");
    expect(describeKeptCheck({ checksum: null })).toBe("Checked by its size only, since the place gave no checksum");
  });

  it("is shown by the start of its checksum", () => {
    expect(shortDigest("0123456789abcdef0123")).toBe("0123456789ab");
  });
});

describe("how a place is described", () => {
  it("says what it is licensed as, if it says", () => {
    expect(describeDataLicense({ name: "cc-by-4.0", url: null })).toBe("Licensed as cc-by-4.0");
    expect(describeDataLicense({ name: null, url: null })).toBe("The place does not say how it is licensed");
    expect(describeDataLicense(null)).toBe("The place does not say how it is licensed");
  });

  it("says whether a place that the paper names is fetched from, and what is kept of it", () => {
    expect(describeCandidate(candidate())).toBe("Nothing fetched yet");
    expect(describeCandidate(candidate({ fetched: 1 }))).toBe("1 file kept");
    expect(describeCandidate(candidate({ fetched: 4 }))).toBe("4 files kept");
    expect(describeCandidate(candidate({ supported: false, fetched: 0 }))).toBe("Not fetched from here");
  });

  it("says where a place is named", () => {
    const fact = { id: "f", quote: "q", anchor: { start: 0, end: 1, page: null, section: null } };

    expect(describeSaid(candidate({ facts: [fact], in_code: true }))).toBe("Named in the paper and in its code");
    expect(describeSaid(candidate({ facts: [fact] }))).toBe("Named in the paper");
    expect(describeSaid(candidate({ in_code: true }))).toBe("Named in the code");
    expect(describeSaid(candidate())).toBeNull();
  });
});

describe("the person's own data that stands in", () => {
  const own = { name: "my.csv", description: "", kind: "csv", bytes: 2048 };
  const standIn = (key: string, present: boolean) => ({ key, name: key, own: "my.csv", set_at: "", own_data: present ? own : null });

  it("is told by its name, kind, and size", () => {
    expect(describeOwn(own)).toBe("my.csv (csv, 2.0 KB)");
  });

  it("is, apart from the datasets the paper names, those that the paper does not name", () => {
    const named = { key: "d1", name: "Atlas", accession: "", quote: "", anchor: { start: 0, end: 0, page: null, section: null }, candidate: null, stand_in: null };
    const found = data({ datasets: [named], stand_ins: [standIn("d1", true), standIn("name:other", true)] });

    expect(otherStandIns(found).map((item) => item.key)).toEqual(["name:other"]);
  });

  it("is present while the data it names is on the Data page", () => {
    expect(standInPresent(standIn("d1", true))).toBe(true);
    expect(standInPresent(standIn("d1", false))).toBe(false);
    expect(standInPresent({})).toBe(false);
  });
});
