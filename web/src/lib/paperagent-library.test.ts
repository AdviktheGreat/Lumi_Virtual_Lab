import { describe, expect, it } from "vitest";
import {
  describeEnvironment,
  describeLibraryHealth,
  describeLicense,
  describePackage,
  describePackageState,
  describeTested,
  describeToolCount,
  describeVersion,
  needsAccepting,
  packageAddress,
  packageState,
  shortHash,
  whyNoPackage,
} from "./paperagent-library";
import type { LibraryEntry, ToolPackage } from "./types";

const NOW = new Date("2026-05-02T12:00:00Z");

function made(overrides: Partial<ToolPackage> = {}): ToolPackage {
  return {
    name: "cellmapper-abc1234",
    file: "cellmapper-abc1234.zip",
    made_at: "2026-05-02T11:00:00Z",
    bytes: 2048,
    sha256: "f".repeat(64),
    commit: "a".repeat(40),
    current: true,
    accepted_license: false,
    license: { flag: null, name: "MIT", kind: "permissive" },
    tools: [{ name: "scale", tier: "A", wrapper_sha256: "e".repeat(64) }],
    repo: { files: 6, bytes: 900, sha256: "d".repeat(64) },
    tested: { ok: true, python: "3.11.9", image_id: "sha256:" + "c".repeat(64), at: "2026-05-02T11:00:00Z", seconds: 0.6, calls: 3, tools: [{ name: "scale", cases: [] }] },
    ...overrides,
  };
}

function entry(overrides: Partial<LibraryEntry> = {}): LibraryEntry {
  return {
    id: "cells",
    title: "Cell mapper",
    given: false,
    tier: "A",
    version: { commit: "a".repeat(40), short: "aaaaaaa", ref: "HEAD", url: "https://github.com/example/cellmapper", fetched_at: "2026-05-01T00:00:00Z" },
    environment: {
      kind: "pip",
      python: "3.11",
      base_image: "python:3.11-slim",
      image: { tag: "t", id: "sha256:" + "c".repeat(64), base_id: "b", base_digests: [], architecture: "arm64", size_bytes: 1, added_bytes: 1 },
      built_at: "2026-05-01T00:00:00Z",
      lock: { name: "pip-freeze.txt", packages: 2, sha256: "9".repeat(64) },
      pip_check: true,
    },
    license: { name: "MIT", kind: "permissive", files: ["LICENSE"], flag: null, said: null },
    tools: [{ name: "scale", function: "cellmapper.core.scale", tier: "A", made_as: "A", passed: [], wrapper_sha256: "e".repeat(64), calls: 3 }],
    dropped: 0,
    export: null,
    state: "s",
    ...overrides,
  };
}

describe("the library", () => {
  it("shows a hash short, with or without what kind it is", () => {
    expect(shortHash("sha256:" + "0123456789abcdef".repeat(4))).toBe("0123456789ab");
    expect(shortHash("fedcba9876543210")).toBe("fedcba987654");
  });

  it("says what each part of the pin is", () => {
    expect(describeVersion(entry().version)).toBe("Commit aaaaaaa of HEAD, from https://github.com/example/cellmapper.");
    expect(describeEnvironment(entry().environment)).toBe(
      "A pip environment with Python 3.11, built from python:3.11-slim, with 2 packages at the versions in pip-freeze.txt.",
    );
    const one = { ...entry().environment, lock: { ...entry().environment.lock, packages: 1 }, pip_check: false };
    expect(describeEnvironment(one)).toBe(
      "A pip environment with Python 3.11, built from python:3.11-slim, with 1 package at the versions in pip-freeze.txt. pip found that some of them do not fit together.",
    );
  });

  it("says what the license was found to be", () => {
    expect(describeLicense(entry().license)).toBe("MIT, a permissive license.");
    expect(describeLicense({ name: "GPL-3.0", kind: "copyleft", files: ["LICENSE"], flag: "copyleft", said: "x" })).toBe("GPL-3.0, a copyleft license.");
    expect(describeLicense({ name: "Odd", kind: null, files: [], flag: "unrecognized", said: "x" })).toBe("Odd.");
    expect(describeLicense({ name: null, kind: null, files: [], flag: "none", said: "x" })).toBe("No license was found.");
    expect(describeLicense({ name: null, kind: "unknown", files: ["LICENSE"], flag: "unrecognized", said: "x" })).toBe(
      "A license file whose license was not recognized.",
    );
  });

  it("counts the tools and what was not made into one", () => {
    expect(describeToolCount(entry())).toBe("1 tool");
    expect(describeToolCount(entry({ dropped: 1 }))).toBe("1 tool, and 1 function that was not made into one");
    const two = entry().tools.concat(entry().tools);
    expect(describeToolCount(entry({ tools: two, dropped: 2 }))).toBe("2 tools, and 2 functions that were not made into one");
  });

  it("says how an agent was last found, with a newer version and its schedule", () => {
    expect(describeLibraryHealth({ status: "unchecked", checked_at: null, update: false, watched_every_hours: null }, NOW)).toBe(
      "Unchecked: not looked at since it was made as it is.",
    );
    expect(describeLibraryHealth({ status: "healthy", checked_at: "2026-05-02T10:00:00Z", update: true, watched_every_hours: 24 }, NOW)).toBe(
      "Healthy, looked at 2 h ago; a newer version of the code is proposed; looked at every day.",
    );
    expect(describeLibraryHealth({ status: "broken", checked_at: "not a time", update: false, watched_every_hours: 5 }, NOW)).toBe(
      "Broken, looked at a while ago; looked at every 5 hours.",
    );
  });

  it("tells a package that was made of what is kept from one that is not, and none", () => {
    expect(packageState(entry())).toBe("none");
    expect(packageState(entry({ export: made() }))).toBe("current");
    expect(packageState(entry({ export: made({ current: false }) }))).toBe("stale");
    expect(describePackageState(entry(), NOW)).toBe("No package was made of its tools.");
    expect(describePackageState(entry({ export: made({ current: false }) }), NOW)).toContain("cannot be downloaded");
    expect(describePackageState(entry({ export: made() }), NOW)).toBe("A package was made 1 h ago: 2.0 KB, checked with 3 recorded calls.");
    expect(describePackageState(entry({ export: made({ tested: { ...made().tested, calls: 1 } }) }), NOW)).toContain("with 1 recorded call.");
    expect(describePackageState(entry({ export: made({ made_at: "not a time" }) }), NOW)).toContain("A package was made a while ago:");
  });

  it("says what a package is and how it was checked", () => {
    expect(describePackage(made(), NOW)).toBe("cellmapper-abc1234.zip, 2.0 KB, with 1 tool and 6 files of the code. Made 1 h ago.");
    const two = made({ tools: [...made().tools, ...made().tools], repo: { files: 1, bytes: 1, sha256: "d" }, made_at: "?" });
    expect(describePackage(two, NOW)).toBe("cellmapper-abc1234.zip, 2.0 KB, with 2 tools and 1 file of the code. Made a while ago.");
    expect(describeTested(made().tested)).toBe(
      "Run in a clean container with no network, in the image its tools were made in, with Python 3.11.9: 3 recorded calls of 1 tool gave what the tutorials got, in 0.6 s.",
    );
    const once = { ...made().tested, calls: 1, tools: [{ name: "a", cases: [] }, { name: "b", cases: [] }] };
    expect(describeTested(once)).toContain("1 recorded call of 2 tools gave");
  });

  it("says why a package cannot be made, and when the license is to be accepted first", () => {
    expect(whyNoPackage(null, { ready: true, message: null })).toBe("Make the tools first, as a package is made of them.");
    expect(whyNoPackage(entry(), { ready: false, message: "Docker is not installed." })).toBe(
      "Docker is not installed. A package is checked in Docker before it is kept.",
    );
    expect(whyNoPackage(entry(), { ready: false, message: null })).toBe("Docker is not running. A package is checked in Docker before it is kept.");
    expect(whyNoPackage(entry(), { ready: true, message: null })).toBeNull();
    expect(needsAccepting(entry())).toBe(false);
    expect(needsAccepting(entry({ license: { ...entry().license, flag: "none" } }))).toBe(true);
    expect(packageAddress("a b")).toBe("/api/paperagents/a%20b/export/package");
  });
});
