import { count, whole, type Checked } from "./checks";
import { formatBytes } from "./files";
import { timeAgo } from "./format";
import { describeDuration } from "./paperagent-environment";
import type {
  PaperAgentReference,
  PaperAgentReferenceOptions,
  ReferenceKept,
  TutorialCall,
  TutorialFailureKind,
  TutorialStatus,
  TutorialSummary,
  TutorialValue,
} from "./types";

export interface ReferenceDraft {
  minutes: string;
  totalMinutes: string;
  tutorials: string;
  repeats: string;
  gigabytes: string;
  // Whether the runs are given the data that was fetched, to read
  useData: boolean;
}

export function emptyReference(limits: PaperAgentReference["limits"]): ReferenceDraft {
  return {
    minutes: String(limits.default_minutes),
    totalMinutes: String(limits.default_total_minutes),
    tutorials: String(limits.default_tutorials),
    repeats: String(limits.default_repeats),
    gigabytes: String(limits.default_gigabytes),
    useData: true,
  };
}

type ReferenceKey = "minutes" | "totalMinutes" | "tutorials" | "repeats" | "gigabytes";

// What running the tutorials is asked for: the most time for one and for all of them, how many, how many times each, and the most one
// may write, in the amounts that the server says it takes, and whether the data that was fetched is given, if there is any
export function checkReference(
  draft: ReferenceDraft,
  reference: Pick<PaperAgentReference, "limits" | "data">,
): Checked<PaperAgentReferenceOptions, ReferenceKey> {
  const { limits } = reference;
  const problems: Partial<Record<ReferenceKey, string>> = {};
  const asked = (key: ReferenceKey, text: string, what: string, most: number) => {
    const checked = whole(text, what, 1, most);
    if (checked.problem) problems[key] = checked.problem;

    return checked.value;
  };
  const minutes = asked("minutes", draft.minutes, "The most time for one tutorial, in minutes,", limits.max_minutes);
  const totalMinutes = asked("totalMinutes", draft.totalMinutes, "The most time for all of them, in minutes,", limits.max_total_minutes);
  const tutorials = asked("tutorials", draft.tutorials, "How many tutorials are run", limits.max_tutorials);
  const repeats = asked("repeats", draft.repeats, "How many times each is run", limits.max_repeats);
  const gigabytes = asked("gigabytes", draft.gigabytes, "The most one run may write, in gigabytes,", limits.max_gigabytes);
  if (minutes !== null && totalMinutes !== null && !problems.totalMinutes && totalMinutes < minutes) {
    problems.totalMinutes = "The time for all of them cannot be less than the time for one.";
  }
  if (Object.keys(problems).length > 0 || minutes === null || totalMinutes === null) return { value: null, problems };
  if (tutorials === null || repeats === null || gigabytes === null) return { value: null, problems };

  return {
    value: {
      minutes,
      total_minutes: totalMinutes,
      tutorials,
      repeats,
      gigabytes,
      ...(reference.data !== null ? { data: draft.useData } : {}),
    },
    problems: {},
  };
}

// How a tutorial ended, in a few words
export const STATUS_TITLES: Record<TutorialStatus, string> = {
  ok: "Ran to the end",
  failed: "Stopped with a failure",
  timed_out: "Did not finish in time",
  too_big: "Wrote more than is allowed",
};

// What a person may do about each way a tutorial can fail, which is said after what the failure says
export const FAILURE_ADVICE: Record<TutorialFailureKind, string> = {
  needs_network: "A tutorial is run with no network, so what it fetches from the internet cannot be had. Nothing is changed to let it.",
  missing_file: "Data is there only if it was fetched, and a tutorial has to look for it where it is kept. Fetch the data, then run again.",
  missing_package: "The environment is made of what the authors' files list. Build it again with the system package that has it, if it is one.",
  needs_gpu: "A tutorial is run on the processor only, so one that needs a GPU is not run.",
  needs_notebook: "A notebook is run here as Python, cell by cell, and not in a notebook's own kernel.",
  notebook_unreadable: "The notebook's file is not one that can be read as a notebook.",
  out_of_memory: "The memory of a run is not changed, so this cannot be run here.",
  timeout: "Allow it more time, up to the most, and run again.",
  too_big: "Allow it more disk, up to the most, and run again.",
  no_result: "It ended without saying how, which is what a tutorial that stops the process does.",
  error: "The end of what it printed says more.",
};

// What a run of the tutorials is told of to begin with: how many tutorials there are, and how many of them cannot be run
export function describePlan(runnable: number, skipped: number, more: number): string {
  const parts = [`${count(runnable, "tutorial")} can be run here`];
  if (skipped > 0) parts.push(`${skipped} cannot`);
  if (more > 0) parts.push(`${more} more are not listed`);

  return `${parts.join(", ")}.`;
}

// What the runs are given of the data that was fetched, which is nothing if there was none or it was not asked to be given
export function describeGiven(data: { files: number; bytes: number } | null): string {
  return data === null ? "None" : `${count(data.files, "file")}, ${formatBytes(data.bytes)}`;
}

// How long a run took in all, from when it began to when it ended, if it did
export function describeRun(kept: ReferenceKept): string {
  const when = timeAgo(kept.started_at) || "a while ago";
  if (kept.finished_at === null) return `Begun ${when}, and not ended`;
  const seconds = (Date.parse(kept.finished_at) - Date.parse(kept.started_at)) / 1000;

  return Number.isFinite(seconds) && seconds >= 0 ? `Run ${when}, in ${describeDuration(seconds)}` : `Run ${when}`;
}

// How many tutorials ran to their end, and how many gave the same each time that they were run
export function describeOutcome(kept: ReferenceKept): string {
  const ended = kept.tutorials.filter((tutorial) => tutorial.status === "ok").length;
  const agreed = kept.tutorials.filter((tutorial) => tutorial.stable === true).length;
  const total = kept.tutorials.length;
  if (total === 0) return "No tutorial was run.";

  return `${count(total, "tutorial")} ${total === 1 ? "was" : "were"} run: ${ended} to the end, ${total - ended} not. ${agreed} gave the same each time it was run.`;
}

// What was not the same from one run to the next, as the runs are compared by their calls, their files, and what they printed
const DIFFERENCES: Record<string, string> = {
  calls: "the calls to the code",
  files: "the files it wrote",
  output: "what it printed",
  status: "whether it ended",
};

function describeDifferences(differs: readonly string[]): string {
  return differs.map((part) => DIFFERENCES[part] ?? part).join(" and ");
}

// Whether a tutorial's runs agreed, in words. They agree if their calls and files are the same, whatever they printed
export function describeAgreement(summary: TutorialSummary): string {
  if (summary.stable === true) {
    return summary.differs.length === 0
      ? `The same each of ${summary.runs} times`
      : `The calls and the files were the same each of ${summary.runs} times, but ${describeDifferences(summary.differs)} was not`;
  }
  if (summary.stable === false) return `Not the same each of ${summary.runs} times: ${describeDifferences(summary.differs) || "it differs"} differed`;
  if (summary.status !== "ok") return "Not compared, as it did not end";

  return summary.runs <= 1 ? "Run once, so not compared" : "Not compared";
}

// What it kept of a tutorial, in a few words
export function describeKept(summary: TutorialSummary): string {
  const parts = [count(summary.calls, "call") + " to the code"];
  parts.push(`${count(summary.files, "file")} written`);
  if (summary.cells_total > 0) parts.push(`${summary.cells} of ${count(summary.cells_total, "cell")} kept`);

  return parts.join(", ");
}

const SHOWN_CHARS = 120;

function cut(text: string, limit = SHOWN_CHARS): string {
  return text.length <= limit ? text : `${text.slice(0, limit)}…`;
}

// A value that a tutorial passed to the code, or got back, in a line: itself if it is plain data, and otherwise what it was
export function describeValue(value: TutorialValue): string {
  if (value.plain) {
    try {
      return cut(JSON.stringify(value.value) ?? "null");
    } catch {
      return value.type;
    }
  }
  const parts: string[] = [value.type];
  if (value.shape !== undefined) parts.push(`shape ${value.shape.join("×")}`);
  if (value.dtype !== undefined) parts.push(value.dtype);
  if (value.shape === undefined && value.repr !== undefined) parts.push(cut(value.repr, 80));

  return parts.join(", ");
}

// A call that a tutorial made, as it would be written: the function with the arguments that were passed
export function describeCall(call: TutorialCall): string {
  const args = Object.entries(call.args)
    .map(([name, value]) => `${name}=${describeValue(value)}`)
    .join(", ");

  return `${call.module}.${call.function}(${args})`;
}

// What a call gave, in a few words, or that it raised
export function describeResult(call: TutorialCall): string {
  if (!call.returned) return "It raised.";

  return call.result === null ? "Nothing was kept of what it gave." : describeValue(call.result);
}
