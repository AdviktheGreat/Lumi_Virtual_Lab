import { formatBytes } from "./files";
import { timeAgo } from "./format";
import { SANDBOXES } from "./settings";
import type { DataLakeFile, DataLakeSummary, Job, JobState, SetupStep, StepState } from "./types";

// A job is at work until it has finished, stopped, or failed
export function isActive(job: Job): boolean {
  return job.state === "running" || job.state === "stopping";
}

const STATE_LABELS: Record<JobState, string> = {
  running: "Running",
  stopping: "Stopping",
  succeeded: "Done",
  failed: "Failed",
  stopped: "Stopped",
};

export function stateLabel(state: JobState): string {
  return STATE_LABELS[state] ?? state;
}

const STEP_LABELS: Record<StepState, string> = {
  done: "Done",
  todo: "To do",
  running: "In progress",
  blocked: "Waiting",
};

export function stepLabel(state: StepState): string {
  return STEP_LABELS[state] ?? state;
}

// The steps that code cannot run without and that are not done, in the order to do them
export function stepsLeft(steps: readonly SetupStep[]): SetupStep[] {
  return steps.filter((step) => step.required && step.state !== "done");
}

// The job at work on something: of a kind, and of a subject if one is given. The server runs one of a kind at a time.
export function activeJob(jobs: readonly Job[], kind: string, subject?: string): Job | undefined {
  return jobs.find((job) => isActive(job) && job.kind === kind && (subject === undefined || job.subject === subject));
}

// Whether a job that was at work is no longer: it has finished, or it is not in the list, as it is not once the server has
// started again
export function finishedSince(before: readonly Job[], after: readonly Job[]): boolean {
  return before.some((job) => isActive(job) && !after.some((other) => other.id === job.id && isActive(other)));
}

// The jobs with this one in the place of the one that has its id, or first, being the latest, if there is none
export function withJob(jobs: readonly Job[], job: Job): Job[] {
  return jobs.some((other) => other.id === job.id)
    ? jobs.map((other) => (other.id === job.id ? job : other))
    : [job, ...jobs];
}

// The latest job of a kind and a subject, at work or not, as the list gives them, the latest first
export function latestJob(jobs: readonly Job[], kind: string, subject: string): Job | undefined {
  return jobs.find((job) => job.kind === kind && job.subject === subject);
}

// When a job began, in words, which is said as it is for a job whose time cannot be read
export function startedText(created: string): string {
  return `Started ${timeAgo(created) || "a while ago"}`;
}

// What a stage of the image is called, as the settings call it
export function stageLabel(target: string): string {
  return SANDBOXES.find((stage) => stage.value === target)?.label ?? `Biomni ${target}`;
}

// What a job counts, if it counts anything: the files of a fetch, the papers that are read, the functions that are
// written, or the questions that are answered, of how many there are
function counted(job: Job): { done: number; total: number; noun: string } | null {
  const { done, total, finished, papers, functions, questions } = job.progress;
  const found =
    job.kind === "papers"
      ? { done: finished, total: papers, noun: "paper" }
      : job.kind === "functions"
        ? { done: finished, total: functions, noun: "function" }
        : job.kind === "benchmark"
          ? { done: finished, total: questions, noun: "question" }
          : { done, total, noun: "file" };

  return typeof found.done === "number" && typeof found.total === "number" && found.total > 0
    ? { done: found.done, total: found.total, noun: found.noun }
    : null;
}

// How far a job has got, from 0 to 1, or null when it cannot be told, as it cannot of a build, which only prints. A
// fetch of the data lake counts files, and the part of the one that is being fetched.
export function jobFraction(job: Job): number | null {
  if (job.state === "succeeded") return 1;
  const { bytes, bytes_total: announced } = job.progress;
  const sum = counted(job);
  if (sum === null) return null;
  const { done, total } = sum;
  const part = typeof bytes === "number" && typeof announced === "number" && announced > 0 ? Math.min(bytes / announced, 1) : 0;

  return Math.min(Math.max((done + part) / total, 0), 1);
}

// What a job has counted, in words: files, bytes, and the file it is on for a fetch, and papers or functions for the
// work on a run. A job that counts nothing says nothing.
export function jobCounts(job: Job): string {
  const { fetched, bytes, bytes_total: announced, current } = job.progress;
  const parts: string[] = [];
  const sum = counted(job);
  if (sum !== null) parts.push(`${sum.done} of ${sum.total} ${sum.noun}${sum.total === 1 ? "" : "s"}`);
  if (typeof fetched === "number" && fetched > 0) parts.push(`${formatBytes(fetched)} fetched`);
  if (isActive(job) && current && typeof bytes === "number" && typeof announced === "number" && announced > 0) {
    parts.push(`${formatBytes(bytes)} of ${formatBytes(announced)} of this file`);
  }

  return parts.join(" · ");
}

// What a job printed, as much of it as is held: the number of the first line held, counting from 0 at the first it
// printed, and the lines
export interface JobLog {
  start: number;
  lines: string[];
}

export const EMPTY_LOG: JobLog = { start: 0, lines: [] };

// The most lines held of what a job printed, which is what the server holds
export const LOG_LIMIT = 2000;

// The number of the line after the last that is held, which is where to ask for more from
export function logEnd(log: JobLog): number {
  return log.start + log.lines.length;
}

// What a job has printed since, added to what is held. Lines already held are not added again, and lines the server has
// dropped, which no longer give what came before them, put an end to what was held.
export function mergeLog(log: JobLog, chunk: { from: number; lines: string[] }): JobLog {
  const end = logEnd(log);
  if (chunk.from > end) return capLog({ start: chunk.from, lines: chunk.lines });
  if (chunk.from + chunk.lines.length <= end) return log;

  return capLog({ start: log.start, lines: [...log.lines, ...chunk.lines.slice(end - chunk.from)] });
}

function capLog(log: JobLog): JobLog {
  const excess = log.lines.length - LOG_LIMIT;

  return excess > 0 ? { start: log.start + excess, lines: log.lines.slice(excess) } : log;
}

// The files of the data lake that have all the words typed, in their names or what they are, in any order and whatever
// their case, and only those not there if that is asked
export function filterFiles(files: readonly DataLakeFile[], typed: string, onlyMissing: boolean): DataLakeFile[] {
  const words = typed.toLowerCase().split(/\s+/).filter(Boolean);

  return files.filter((file) => {
    if (onlyMissing && file.present) return false;
    const text = `${file.name} ${file.description}`.toLowerCase();

    return words.every((word) => text.includes(word));
  });
}

// The names of the files that are not there, and of those of them that may be used commercially
export function missingNames(files: readonly DataLakeFile[], commercialOnly = false): string[] {
  return files.filter((file) => !file.present && (!commercialOnly || file.commercial)).map((file) => file.name);
}

// About how much of the disk the whole data lake takes, which the server does not say of the files it has not fetched
export const DATA_LAKE_BYTES = 11 * 1024 ** 3;

// What to warn of when what is left to fetch may not fit where the data lake is kept, or nothing when it does or when how
// much is free is not known
export function roomWarning(lake: DataLakeSummary): string | null {
  if (lake.complete || lake.free_bytes === null) return null;
  const needed = DATA_LAKE_BYTES - lake.bytes;
  if (lake.free_bytes >= needed) return null;

  return `The rest of the data lake takes up to about ${formatBytes(needed)}, and ${formatBytes(lake.free_bytes)} is free where it is kept.`;
}
