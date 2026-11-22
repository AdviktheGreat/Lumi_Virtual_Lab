import { count, whole } from "./checks";
import { timeAgo } from "./format";
import type { HealthRecord, HealthStatus, HealthWatch, PaperAgentHealth, ProposedUpdateSummary, SourceState, UpdateFile } from "./types";

export const STATUS_TITLES: Record<HealthStatus, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  broken: "Broken",
  unchecked: "Unchecked",
};

export const SOURCE_TITLES: Record<SourceState, string> = {
  same: "Where it was",
  moved: "Moved",
  gone: "Gone",
  unknown: "Not known",
  pinned: "One commit",
};

// The badge of a word, which is said in words too and not only by its colour
export function statusVariant(status: HealthStatus): "default" | "secondary" | "destructive" | "outline" {
  if (status === "healthy") return "default";
  if (status === "broken") return "destructive";

  return status === "degraded" ? "secondary" : "outline";
}

export function shortCommit(commit: string): string {
  return commit.slice(0, 7);
}

// When it was looked at, and how long that took
export function describeLooked(health: Pick<HealthRecord, "checked_at" | "seconds">, now: Date = new Date()): string {
  const when = timeAgo(health.checked_at, now) || "a while ago";
  const seconds = health.seconds < 1 ? "under a second" : `${Math.round(health.seconds)} s`;

  return `Looked at ${when}, which took ${seconds}.`;
}

// Why there is nothing that was found to show
export function describeNotLooked(health: Pick<PaperAgentHealth, "watchable" | "health">): string | null {
  if (!health.watchable) return "Make the tools first. An agent is looked at by running its tools again.";
  if (health.health !== null) return null;

  return "It has not been looked at, or not since its code, environment, or tools were made again.";
}

// What was found of the image of the environment
export function describeImage(present: boolean | null): string {
  if (present === true) return "The image of the environment is in Docker.";
  if (present === false) return "The image of the environment is not in Docker any more.";

  return "Docker could not be asked whether the image of the environment is there.";
}

// What the package index said of the versions that are pinned
export function describeDependencies(health: Pick<HealthRecord, "dependencies" | "dependencies_message">): string {
  const pins = health.dependencies;
  if (pins === null) return health.dependencies_message ?? "The pinned versions were not asked of.";
  if (pins.total === 0) return "The lock pins no version that the index can be asked of.";
  const asked = pins.looked_at === pins.total ? `All ${count(pins.total, "pinned version")} were asked of PyPI` : `${pins.looked_at} of ${count(pins.total, "pinned version")} were asked of PyPI`;
  const wrong = pins.problems.length === 0 ? "none is gone or yanked" : `${pins.problems.length} cannot be installed again as ${pins.problems.length === 1 ? "it is" : "they are"}`;
  const unsaid = pins.unsaid > 0 ? ` PyPI did not say of ${pins.unsaid}, which is not held against it.` : "";

  return `${asked}, and ${wrong}.${unsaid}`;
}

// How one tool did when its recorded calls were run again
export function describeTool(tool: HealthRecord["tools"][number]): string {
  if (tool.calls === 0) return "It has no recorded call that could be run again, so it was not held to anything.";
  if (tool.matched === tool.calls) return `Gave again what its tutorials got, ${tool.matched} of ${count(tool.calls, "call")}.`;
  const said = tool.message ? ` ${tool.message}` : "";

  return `${tool.matched} of ${count(tool.calls, "call")} gave again what its tutorials got.${said}`;
}

export function toolHeld(tool: HealthRecord["tools"][number]): "matched" | "differs" | "unheld" {
  if (tool.calls === 0) return "unheld";

  return tool.matched === tool.calls ? "matched" : "differs";
}

// Hours in the words a person would use: days where they are whole days
export function describeHours(hours: number): string {
  if (hours % 24 === 0) return hours === 24 ? "day" : `${hours / 24} days`;

  return hours === 1 ? "hour" : `${hours} hours`;
}

// When a watched agent is looked at next: at the next check of the schedules if it was not started since, or the hours after the last
// start. A time that cannot be read is a look that is due
export function nextLook(watch: Pick<HealthWatch, "every_hours" | "last_started_at">): Date | null {
  if (watch.last_started_at === null) return null;
  const last = new Date(watch.last_started_at);
  if (Number.isNaN(last.getTime())) return null;

  return new Date(last.getTime() + watch.every_hours * 3_600_000);
}

// The schedule, in a sentence
export function describeWatch(watch: HealthWatch | null, now: Date = new Date()): string {
  if (watch === null) return "It is not looked at on a schedule. It is looked at when you ask.";
  const next = nextLook(watch);
  const due = next === null || next.getTime() <= now.getTime();
  const when = due
    ? "It is looked at the next time the server checks the schedules, which it does once a minute."
    : `It is looked at next ${next.toLocaleString("en", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}.`;

  return `It is looked at every ${describeHours(watch.every_hours)} while the server is running. ${when}`;
}

export function checkWatch(typed: string, limits: PaperAgentHealth["limits"]): { value: number | null; problem?: string } {
  return whole(typed, "How often it is looked at, in hours,", limits.min_hours, limits.max_hours);
}

// The newer version, in a line: the commits and how much changed
export function describeUpdate(update: Pick<ProposedUpdateSummary, "from_commit" | "to_commit" | "changed">): string {
  return `From ${shortCommit(update.from_commit)} to ${shortCommit(update.to_commit)}: ${count(update.changed, "file")} changed.`;
}

// What it would change of the tools and the environment
export function describeAffects(update: Pick<ProposedUpdateSummary, "affects" | "environment_files">): string[] {
  const said = [
    update.affects.length > 0
      ? `The file of ${update.affects.length === 1 ? "the tool" : "the tools"} ${update.affects.join(", ")} changed.`
      : "No tool's own file changed. A tool whose function calls a file that changed is not told of by this.",
  ];
  if (update.environment_files.length > 0) {
    said.push(`Files that say what the environment is made of changed: ${update.environment_files.join(", ")}.`);
  }

  return said;
}

export const CHANGE_TITLES: Record<UpdateFile["change"], string> = { added: "Added", removed: "Removed", changed: "Changed" };

// What is shown of one file's change, beside its path
export function describeFile(file: UpdateFile): string {
  if (file.binary) return "Not text, so its lines are not shown.";
  if (file.added === null || file.removed === null) return "Its lines were not compared, as only the first files' are.";
  const lines = `${file.added} added, ${file.removed} taken away`;

  return file.cut ? `${lines}. Its diff is cut, as it is long.` : `${lines}.`;
}

// What a line of a diff is, which is how it is shown
export function lineKind(line: string): "meta" | "hunk" | "added" | "removed" | "same" {
  if (line.startsWith("+++") || line.startsWith("---")) return "meta";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "added";

  return line.startsWith("-") ? "removed" : "same";
}
