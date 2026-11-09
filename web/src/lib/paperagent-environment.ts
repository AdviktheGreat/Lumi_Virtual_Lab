import { count, whole, type Checked } from "./checks";
import { formatBytes } from "./files";
import { timeAgo } from "./format";
import type {
  EnvironmentBuilt,
  EnvironmentFailure,
  EnvironmentFailureKind,
  PaperAgentBuildOptions,
  PaperAgentEnvironment,
} from "./types";

// What a Debian package is called, which is what the server takes
const SYSTEM_PACKAGE = /^[a-z0-9][a-z0-9+.-]{1,60}$/;

export interface EnvironmentDraft {
  // A version of Python in place of what the code says, or blank to leave it to the code
  python: string;
  // The Debian packages to install first, as they were typed
  packages: string;
  minutes: string;
  gigabytes: string;
}

export function emptyEnvironment(limits: PaperAgentEnvironment["limits"]): EnvironmentDraft {
  return { python: "", packages: "", minutes: String(limits.default_minutes), gigabytes: String(limits.default_gigabytes) };
}

// The names in what was typed, which are told apart by commas, spaces, or lines, each of them once
export function packageNames(text: string): string[] {
  const names = text.split(/[\s,]+/).filter((name) => name !== "");

  return names.filter((name, place) => names.indexOf(name) === place);
}

type EnvironmentKey = "python" | "packages" | "minutes" | "gigabytes";

// What building is asked for: which Python, which is left out for what the code says, the Debian packages to install first,
// and the most time and disk, in the amounts that the server says it takes
export function checkEnvironment(
  draft: EnvironmentDraft,
  environment: Pick<PaperAgentEnvironment, "limits" | "python_versions" | "max_system_packages">,
): Checked<PaperAgentBuildOptions, EnvironmentKey> {
  const problems: Partial<Record<EnvironmentKey, string>> = {};
  if (draft.python !== "" && !environment.python_versions.includes(draft.python)) {
    problems.python = `Python is one of ${environment.python_versions.join(", ")}.`;
  }
  const names = packageNames(draft.packages);
  const wrong = names.find((name) => !SYSTEM_PACKAGE.test(name));
  if (wrong !== undefined) {
    problems.packages = `"${wrong.slice(0, 60)}" is not the name of a Debian package, such as libhdf5-dev.`;
  } else if (names.length > environment.max_system_packages) {
    problems.packages = `At most ${environment.max_system_packages} packages can be asked for.`;
  }
  const minutes = whole(draft.minutes, "The most time, in minutes,", 1, environment.limits.max_minutes);
  if (minutes.problem) problems.minutes = minutes.problem;
  const gigabytes = whole(draft.gigabytes, "The most disk, in gigabytes,", 1, environment.limits.max_gigabytes);
  if (gigabytes.problem) problems.gigabytes = gigabytes.problem;
  if (Object.keys(problems).length > 0 || minutes.value === null || gigabytes.value === null) return { value: null, problems };

  return {
    value: {
      ...(draft.python !== "" ? { python: draft.python } : {}),
      ...(names.length > 0 ? { system_packages: names } : {}),
      minutes: minutes.value,
      gigabytes: gigabytes.value,
    },
    problems: {},
  };
}

// Why a code is not built here, as a person is told it in a few words
export const UNSUPPORTED_TITLES: Record<string, string> = {
  no_environment: "Nothing says what to install",
  r: "It is in R",
  julia: "It is in Julia",
  docker: "It comes with a Dockerfile",
  pipfile: "It is set up with a Pipfile",
  python_mismatch: "It needs a Python that is not offered",
};

export function describeUnsupported(kind: string): string {
  return UNSUPPORTED_TITLES[kind] ?? "It is not built here";
}

// What a person may do about each way a build can fail, which is said after what the failure says
export const FAILURE_ADVICE: Record<EnvironmentFailureKind, string> = {
  missing_system_library: "Install the Debian package it names first, and build again.",
  version_conflict: "The pins are the authors', and are not changed here. Another Python may let them be met.",
  python_mismatch: "Build again for another Python.",
  not_found: "Another Python may have it. If not, it cannot be had here.",
  network: "Building again may pass.",
  private_dependency: "Nothing is signed in to in a build, so this cannot be built here.",
  build_failed: "The output says what was missing. Name the Debian package that has it, and build again.",
  out_of_memory: "The memory of a build is not changed, so this cannot be built here.",
  too_big: "Allow it more disk, up to the most, and build again.",
  timeout: "Allow it more time, up to the most, and build again.",
  does_not_run: "It built, but it does not start with no network, which is how it has to be run.",
  docker: "Make sure Docker is running and has room, and build again.",
  failed: "The output says more.",
};

// How long a build or a step took, in a few words
export function describeDuration(seconds: number): string {
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} seconds`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds - minutes * 60);

  return rest === 0 ? count(minutes, "minute") : `${count(minutes, "minute")} ${count(rest, "second")}`;
}

// What an image is, as its hash, in a few characters
export function shortId(id: string): string {
  return id.replace(/^sha256:/, "").slice(0, 12);
}

// How big the image is, and how much of that the build added to the image it began with
export function describeImage(built: EnvironmentBuilt): string {
  return `${formatBytes(built.image.size_bytes)}, of which ${formatBytes(built.image.added_bytes)} was added by the build, for ${built.image.architecture}`;
}

export function describeBuilt(built: EnvironmentBuilt): string {
  return `Built ${timeAgo(built.built_at) || "a while ago"}, in ${describeDuration(built.duration)}`;
}

// What `pip check` said of the packages that were installed
export function describePipCheck(check: EnvironmentBuilt["pip_check"]): string {
  return check.ok ? "pip check finds nothing wrong: what the packages ask of each other is met" : `pip check finds ${count(check.problems.length, "problem")}`;
}

// What the draft is changed to by what a failure suggests, and what it says in words, or null if there is nothing in it that
// the draft does not say already
export function suggestion(
  failure: EnvironmentFailure,
  draft: EnvironmentDraft,
  limits: PaperAgentEnvironment["limits"],
  versions: readonly string[],
  // Whether the form lets a Python be chosen, which it does not for a conda file that says its own, and the server refuses one
  canChoosePython: boolean,
): { draft: EnvironmentDraft; words: string } | null {
  const next = { ...draft };
  const words: string[] = [];
  const named = packageNames(draft.packages);
  const added = failure.system_packages.filter((name) => !named.includes(name));
  if (added.length > 0) {
    next.packages = [...named, ...added].join(" ");
    words.push(`install ${added.join(", ")}`);
  }
  if (canChoosePython && failure.python !== null && versions.includes(failure.python) && failure.python !== draft.python) {
    next.python = failure.python;
    words.push(`use Python ${failure.python}`);
  }
  if (failure.kind === "timeout" && Number(draft.minutes) < limits.max_minutes) {
    next.minutes = String(Math.min(limits.max_minutes, Math.max(1, Number(draft.minutes) || limits.default_minutes) * 2));
    words.push(`allow ${count(Number(next.minutes), "minute")}`);
  }
  if (failure.kind === "too_big" && Number(draft.gigabytes) < limits.max_gigabytes) {
    next.gigabytes = String(Math.min(limits.max_gigabytes, Math.max(1, Number(draft.gigabytes) || limits.default_gigabytes) * 2));
    words.push(`allow ${next.gigabytes} gigabytes`);
  }

  return words.length > 0 ? { draft: next, words: words.join(" and ") } : null;
}
