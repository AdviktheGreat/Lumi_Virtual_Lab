// The lab's library of the agents that have tools, each as a version that is pinned, and the package that can be made of an agent's
// tools: what is said of each part of the pin, of the code's license, and of a package that was made

import { formatBytes } from "./files";
import { timeAgo } from "./format";
import { describeHours, STATUS_TITLES } from "./paperagent-living";
import type { LibraryEntry, LibraryHealth, LicenseFlag, ToolPackage } from "./types";

export const LIBRARY_ADDRESS = "/papers?view=library";

export const FLAG_TITLES: Record<LicenseFlag, string> = {
  none: "No license",
  unrecognized: "License not recognized",
  noncommercial: "Non-commercial use only",
  copyleft: "Copyleft",
};

// A hash as it is shown beside what it is of, which is enough to tell two apart by eye. The whole is in the package's manifest
export function shortHash(hash: string): string {
  const bare = hash.startsWith("sha256:") ? hash.slice("sha256:".length) : hash;

  return bare.slice(0, 12);
}

export function describeVersion(version: LibraryEntry["version"]): string {
  return `Commit ${version.short} of ${version.ref}, from ${version.url}.`;
}

export function describeEnvironment(environment: LibraryEntry["environment"]): string {
  const { lock } = environment;
  const packages = `${lock.packages} ${lock.packages === 1 ? "package" : "packages"}`;
  const fit = environment.pip_check ? "" : " pip found that some of them do not fit together.";

  return `A ${environment.kind} environment with Python ${environment.python}, built from ${environment.base_image}, with ${packages} at the versions in ${lock.name}.${fit}`;
}

export function describeLicense(license: LibraryEntry["license"]): string {
  if (license.name === null) return license.files.length > 0 ? "A license file whose license was not recognized." : "No license was found.";

  return license.kind !== null ? `${license.name}, a ${license.kind} license.` : `${license.name}.`;
}

// What there is of the agent's tools beside them: how many there are, and how many functions were not made into tools
export function describeToolCount(entry: Pick<LibraryEntry, "tools" | "dropped">): string {
  const tools = `${entry.tools.length} ${entry.tools.length === 1 ? "tool" : "tools"}`;
  if (entry.dropped === 0) return tools;

  return `${tools}, and ${entry.dropped} ${entry.dropped === 1 ? "function that was" : "functions that were"} not made into one`;
}

// How an agent was when it was last looked at, in a line, with a newer version and the schedule if there are
export function describeLibraryHealth(health: LibraryHealth, now: Date = new Date()): string {
  const looked =
    health.checked_at === null
      ? `${STATUS_TITLES[health.status]}: not looked at since it was made as it is`
      : `${STATUS_TITLES[health.status]}, looked at ${timeAgo(health.checked_at, now) || "a while ago"}`;
  const update = health.update ? "; a newer version of the code is proposed" : "";
  const watched = health.watched_every_hours !== null ? `; looked at every ${describeHours(health.watched_every_hours)}` : "";

  return `${looked}${update}${watched}.`;
}

export type PackageState = "none" | "current" | "stale";

export function packageState(entry: Pick<LibraryEntry, "export">): PackageState {
  if (entry.export === null) return "none";

  return entry.export.current ? "current" : "stale";
}

export function describePackage(made: ToolPackage, now: Date = new Date()): string {
  const tools = `${made.tools.length} ${made.tools.length === 1 ? "tool" : "tools"}`;

  return `${made.file}, ${formatBytes(made.bytes)}, with ${tools} and ${made.repo.files} ${made.repo.files === 1 ? "file" : "files"} of the code. Made ${timeAgo(made.made_at, now) || "a while ago"}.`;
}

// How the package was checked before it was kept, which is the only way that one is kept
export function describeTested(tested: ToolPackage["tested"]): string {
  const calls = `${tested.calls} recorded ${tested.calls === 1 ? "call" : "calls"}`;
  const tools = `${tested.tools.length} ${tested.tools.length === 1 ? "tool" : "tools"}`;

  return `Run in a clean container with no network, in the image its tools were made in, with Python ${tested.python}: ${calls} of ${tools} gave what the tutorials got, in ${tested.seconds} s.`;
}

// What a package is said to be in the library, in a line
export function describePackageState(entry: Pick<LibraryEntry, "export">, now: Date = new Date()): string {
  if (entry.export === null) return "No package was made of its tools.";
  if (!entry.export.current) return "Its package was made of what is not kept now, so it cannot be downloaded. Make it again on the agent's page.";

  return `A package was made ${timeAgo(entry.export.made_at, now) || "a while ago"}: ${formatBytes(entry.export.bytes)}, checked with ${entry.export.tested.calls} recorded ${entry.export.tested.calls === 1 ? "call" : "calls"}.`;
}

// Why a package cannot be made now, if it cannot: there are no tools, or Docker is not running, which it is checked in
export function whyNoPackage(entry: LibraryEntry | null, docker: { ready: boolean; message: string | null }): string | null {
  if (entry === null) return "Make the tools first, as a package is made of them.";
  if (!docker.ready) return `${docker.message ?? "Docker is not running."} A package is checked in Docker before it is kept.`;

  return null;
}

// Whether the person is to say that they read what is said of the code's license before a package is made of it
export function needsAccepting(entry: Pick<LibraryEntry, "license">): boolean {
  return entry.license.flag !== null;
}

export const packageAddress = (id: string) => `/api/paperagents/${encodeURIComponent(id)}/export/package`;
