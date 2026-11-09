import { describe, expect, it } from "vitest";
import {
  checkEnvironment,
  describeBuilt,
  describeDuration,
  describeImage,
  describePipCheck,
  describeUnsupported,
  emptyEnvironment,
  FAILURE_ADVICE,
  packageNames,
  shortId,
  suggestion,
  UNSUPPORTED_TITLES,
  type EnvironmentDraft,
} from "./paperagent-environment";
import type { EnvironmentBuilt, EnvironmentFailure, PaperAgentEnvironment } from "./types";

const limits: PaperAgentEnvironment["limits"] = {
  default_minutes: 30,
  max_minutes: 180,
  default_gigabytes: 6,
  max_gigabytes: 40,
  memory: "8g",
  cpus: "4",
  pids: 1024,
};
const environment = { limits, python_versions: ["3.13", "3.12", "3.11", "3.10", "3.9", "3.8", "3.7"], max_system_packages: 20 };
const draft = (part: Partial<EnvironmentDraft> = {}): EnvironmentDraft => ({ ...emptyEnvironment(limits), ...part });

function failure(part: Partial<EnvironmentFailure> = {}): EnvironmentFailure {
  return {
    kind: "missing_system_library",
    title: "A system library is missing",
    detail: "Something was built that needs the header zlib.h.",
    step: "project",
    package: null,
    system_packages: ["zlib1g-dev"],
    python: null,
    tail: [],
    ...part,
  };
}

describe("what is built, when nothing is said", () => {
  it("is the defaults that the server gives, with the Python left to the code and nothing installed first", () => {
    expect(emptyEnvironment(limits)).toEqual({ python: "", packages: "", minutes: "30", gigabytes: "6" });
    expect(checkEnvironment(draft(), environment)).toEqual({ value: { minutes: 30, gigabytes: 6 }, problems: {} });
  });
});

describe("the names of packages that are typed", () => {
  it("are told apart by spaces, commas, and lines, and each is once", () => {
    expect(packageNames("libhdf5-dev, pkg-config\nlibhdf5-dev  zlib1g-dev,")).toEqual(["libhdf5-dev", "pkg-config", "zlib1g-dev"]);
    expect(packageNames("  ")).toEqual([]);
  });
});

describe("what building is asked for", () => {
  it("has a Python that is offered, and the packages and limits as the server takes them", () => {
    expect(checkEnvironment(draft({ python: "3.9", packages: "libcairo2-dev pkg-config", minutes: "45", gigabytes: "10" }), environment)).toEqual({
      value: { python: "3.9", system_packages: ["libcairo2-dev", "pkg-config"], minutes: 45, gigabytes: 10 },
      problems: {},
    });
  });

  it("refuses a Python that is not offered", () => {
    const checked = checkEnvironment(draft({ python: "2.7" }), environment);

    expect(checked.value).toBeNull();
    expect(checked.problems.python).toBe("Python is one of 3.13, 3.12, 3.11, 3.10, 3.9, 3.8, 3.7.");
  });

  it("refuses what is not the name of a Debian package, and says which", () => {
    for (const bad of ["Lib", "-o", "a;b", "x", "lib$(id)", "a/b", "é-dev"]) {
      const checked = checkEnvironment(draft({ packages: `libz-dev ${bad}` }), environment);
      expect(checked.value, bad).toBeNull();
      expect(checked.problems.packages, bad).toContain(`"${bad}" is not the name of a Debian package`);
    }
  });

  it("refuses more packages than are taken", () => {
    const many = Array.from({ length: 21 }, (_, number) => `lib${number}-dev`).join(" ");

    expect(checkEnvironment(draft({ packages: many }), environment).problems.packages).toBe("At most 20 packages can be asked for.");
    expect(checkEnvironment(draft({ packages: many.split(" ").slice(0, 20).join(" ") }), environment).value).not.toBeNull();
  });

  it("refuses time and disk that are not whole numbers within what is allowed", () => {
    for (const minutes of ["", "0", "181", "1.5", "-3", "soon"]) {
      expect(checkEnvironment(draft({ minutes }), environment).problems.minutes, minutes).toMatch(/is a whole number from 1 to 180/);
    }
    for (const gigabytes of ["", "0", "41", "2.5", "lots"]) {
      expect(checkEnvironment(draft({ gigabytes }), environment).problems.gigabytes, gigabytes).toMatch(/is a whole number from 1 to 40/);
    }
    expect(checkEnvironment(draft({ minutes: "180", gigabytes: "40" }), environment).value).toMatchObject({ minutes: 180, gigabytes: 40 });
  });

  it("says every problem at once", () => {
    const checked = checkEnvironment(draft({ python: "1", packages: "BAD", minutes: "0", gigabytes: "0" }), environment);

    expect(Object.keys(checked.problems).sort()).toEqual(["gigabytes", "minutes", "packages", "python"]);
  });
});

describe("what a failure suggests", () => {
  it("is to install the package it names, added to what was typed and not in place of it", () => {
    const next = suggestion(failure(), draft({ packages: "pkg-config" }), limits, environment.python_versions, true);

    expect(next?.draft.packages).toBe("pkg-config zlib1g-dev");
    expect(next?.words).toBe("install zlib1g-dev");
  });

  it("is nothing if the draft already says it", () => {
    expect(suggestion(failure(), draft({ packages: "zlib1g-dev" }), limits, environment.python_versions, true)).toBeNull();
    expect(suggestion(failure({ system_packages: [] }), draft(), limits, environment.python_versions, true)).toBeNull();
  });

  it("is the Python it points to, if that is one that is offered and is not the one already said", () => {
    const wrong = failure({ kind: "python_mismatch", system_packages: [], python: "3.9" });

    expect(suggestion(wrong, draft(), limits, environment.python_versions, true)).toMatchObject({ draft: { python: "3.9" }, words: "use Python 3.9" });
    expect(suggestion(wrong, draft({ python: "3.9" }), limits, environment.python_versions, true)).toBeNull();
    expect(suggestion({ ...wrong, python: "2.7" }, draft(), limits, environment.python_versions, true)).toBeNull();
  });

  it("is no Python when the form does not offer one, as for a conda file that says its own", () => {
    const wrong = failure({ kind: "python_mismatch", system_packages: [], python: "3.9" });

    expect(suggestion(wrong, draft(), limits, environment.python_versions, false)).toBeNull();
    expect(suggestion(failure({ python: "3.10" }), draft(), limits, environment.python_versions, false)?.words).toBe("install zlib1g-dev");
  });

  it("is both, when it says both", () => {
    const both = failure({ python: "3.10" });

    expect(suggestion(both, draft(), limits, environment.python_versions, true)?.words).toBe("install zlib1g-dev and use Python 3.10");
  });

  it("is twice the time, to the most, for a build that took too long", () => {
    const slow = failure({ kind: "timeout", system_packages: [] });

    expect(suggestion(slow, draft(), limits, environment.python_versions, true)).toMatchObject({ draft: { minutes: "60" }, words: "allow 60 minutes" });
    expect(suggestion(slow, draft({ minutes: "100" }), limits, environment.python_versions, true)?.draft.minutes).toBe("180");
    expect(suggestion(slow, draft({ minutes: "180" }), limits, environment.python_versions, true)).toBeNull();
  });

  it("is twice the disk, to the most, for a build that wrote too much", () => {
    const big = failure({ kind: "too_big", system_packages: [] });

    expect(suggestion(big, draft(), limits, environment.python_versions, true)).toMatchObject({ draft: { gigabytes: "12" }, words: "allow 12 gigabytes" });
    expect(suggestion(big, draft({ gigabytes: "30" }), limits, environment.python_versions, true)?.draft.gigabytes).toBe("40");
    expect(suggestion(big, draft({ gigabytes: "40" }), limits, environment.python_versions, true)).toBeNull();
  });

  it("does not change what the draft says of anything else", () => {
    const next = suggestion(failure(), draft({ python: "3.8", minutes: "50" }), limits, environment.python_versions, true);

    expect(next?.draft).toMatchObject({ python: "3.8", minutes: "50", gigabytes: "6" });
  });
});

describe("what a person is told of why a build failed or a code is not built", () => {
  it("has something to do for every kind of failure, and says why for every kind of code that is not built", () => {
    for (const kind of Object.keys(FAILURE_ADVICE)) expect(FAILURE_ADVICE[kind as keyof typeof FAILURE_ADVICE].length, kind).toBeGreaterThan(10);
    expect(Object.keys(FAILURE_ADVICE).sort()).toEqual(
      [
        "build_failed",
        "does_not_run",
        "docker",
        "failed",
        "missing_system_library",
        "network",
        "not_found",
        "out_of_memory",
        "private_dependency",
        "python_mismatch",
        "timeout",
        "too_big",
        "version_conflict",
      ].sort(),
    );
    for (const kind of Object.keys(UNSUPPORTED_TITLES)) expect(describeUnsupported(kind)).toBe(UNSUPPORTED_TITLES[kind]);
    expect(describeUnsupported("something new")).toBe("It is not built here");
  });
});

describe("what a build that was made is said to be", () => {
  const built = {
    built_at: new Date().toISOString(),
    duration: 3.7,
    image: { id: "sha256:0123456789abcdef0123", size_bytes: 180_000_000, added_bytes: 130_000_000, architecture: "arm64" },
    pip_check: { ok: true, problems: [] as string[] },
  } as unknown as EnvironmentBuilt;

  it("has its time in a few words", () => {
    expect(describeDuration(3.7)).toBe("3.7 seconds");
    expect(describeDuration(42.4)).toBe("42 seconds");
    expect(describeDuration(60)).toBe("1 minute");
    expect(describeDuration(125)).toBe("2 minutes 5 seconds");
    expect(describeDuration(3601)).toBe("60 minutes 1 second");
  });

  it("has its image as a few characters of its hash, which is without the name of the hash", () => {
    expect(shortId("sha256:0123456789abcdef0123")).toBe("0123456789ab");
    expect(shortId("abc")).toBe("abc");
  });

  it("has its size, what the build added, and the processor it is for", () => {
    expect(describeImage(built)).toMatch(/^.+, of which .+ was added by the build, for arm64$/);
  });

  it("says when, and how long it took", () => {
    expect(describeBuilt(built)).toMatch(/^Built .+, in 3\.7 seconds$/);
  });

  it("says what pip check found", () => {
    expect(describePipCheck({ ok: true, problems: [] })).toMatch(/finds nothing wrong/);
    expect(describePipCheck({ ok: false, problems: ["a needs b", "c needs d"] })).toBe("pip check finds 2 problems");
    expect(describePipCheck({ ok: false, problems: ["a needs b"] })).toBe("pip check finds 1 problem");
  });
});
