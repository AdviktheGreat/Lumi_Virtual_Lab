import { count, whole, type Checked } from "./checks";
import { timeAgo } from "./format";
import { describeDuration } from "./paperagent-environment";
import type { PaperAgentTools, PaperAgentToolsOptions, ToolCase, ToolDetail, ToolDropped, ToolDroppedKind, ToolsKept, ToolSummary } from "./types";

export interface ToolsDraft {
  minutes: string;
  totalMinutes: string;
  tools: string;
  repeats: string;
  repairs: string;
  gigabytes: string;
}

export function emptyTools(limits: PaperAgentTools["limits"]): ToolsDraft {
  return {
    minutes: String(limits.default_minutes),
    totalMinutes: String(limits.default_total_minutes),
    tools: String(limits.default_tools),
    repeats: String(limits.default_repeats),
    repairs: String(limits.default_repairs),
    gigabytes: String(limits.default_gigabytes),
  };
}

type ToolsKey = "minutes" | "totalMinutes" | "tools" | "repeats" | "repairs" | "gigabytes";

// What making tools is asked for: the most time for the calls of one tool and for all of them, how many tools, how many times each call
// is made again, how many times a wrapper may be rewritten (none is a number too), and the most one call may write, in the amounts
// that the server says it takes
export function checkTools(draft: ToolsDraft, limits: PaperAgentTools["limits"]): Checked<PaperAgentToolsOptions, ToolsKey> {
  const problems: Partial<Record<ToolsKey, string>> = {};
  const asked = (key: ToolsKey, text: string, what: string, least: number, most: number) => {
    const checked = whole(text, what, least, most);
    if (checked.problem) problems[key] = checked.problem;

    return checked.value;
  };
  const minutes = asked("minutes", draft.minutes, "The most time for the calls of one tool, in minutes,", 1, limits.max_minutes);
  const totalMinutes = asked("totalMinutes", draft.totalMinutes, "The most time for all of the tools, in minutes,", 1, limits.max_total_minutes);
  const tools = asked("tools", draft.tools, "How many tools are made", 1, limits.max_tools);
  const repeats = asked("repeats", draft.repeats, "How many times each call is made again", 1, limits.max_repeats);
  const repairs = asked("repairs", draft.repairs, "How many times a wrapper is rewritten", 0, limits.max_repairs);
  const gigabytes = asked("gigabytes", draft.gigabytes, "The most one call may write, in gigabytes,", 1, limits.max_gigabytes);
  if (minutes !== null && totalMinutes !== null && !problems.totalMinutes && totalMinutes < minutes) {
    problems.totalMinutes = "The time for all of the tools cannot be less than the time for one.";
  }
  if (Object.keys(problems).length > 0) return { value: null, problems };
  if (minutes === null || totalMinutes === null || tools === null) return { value: null, problems };
  if (repeats === null || repairs === null || gigabytes === null) return { value: null, problems };

  return { value: { minutes, total_minutes: totalMinutes, tools, repeats, repairs, gigabytes }, problems: {} };
}

// Why a function that a tutorial called is not made a tool, in a few words
export const DROPPED_TITLES: Record<ToolDroppedKind, string> = {
  method: "A method of a class",
  nested: "Defined inside another function",
  variadic: "Takes *args or **kwargs",
  no_usable_call: "No call of it can be made again",
  source_not_found: "Its code was not found",
  source_mismatch: "Not the function that was called",
  too_many_parameters: "Has too many parameters",
  wrapper: "No wrapper of it passes the checks",
  replay_error: "It raised when it was called again",
  replay_differs: "It gave something else when it was called again",
  timed_out: "It did not finish in time",
  out_of_time: "Not tried, as the time was used",
  over_limit: "Not made, as more were called than are made",
};

// What a person may do about the ways in which a tool is not made that they can do something about, which is said after the reason
export const DROPPED_ADVICE: Partial<Record<ToolDroppedKind, string>> = {
  timed_out: "Take the tools away, allow more time, up to the most, and make them again.",
  out_of_time: "Take the tools away, allow more time for all of them, up to the most, and make them again.",
  over_limit: "Take the tools away, allow more tools, up to the most, and make them again.",
};

// What would be made, in a line: how many of the functions that the tutorials called can be tools, and how many cannot
export function describePreview(candidates: number, dropped: number): string {
  const parts = [`${count(candidates, "function")} can be made into ${candidates === 1 ? "a tool" : "tools"}`];
  if (dropped > 0) parts.push(`${dropped} cannot`);

  return `${parts.join(", ")}.`;
}

// How a making of tools came out: how many tools, and how many functions were not made into tools
export function describeMade(kept: ToolsKept): string {
  const left = kept.dropped.length;
  const dropped = `${count(left, "function")} ${left === 1 ? "was" : "were"} not made into a tool.`;
  // A making that did not come to its end has not tried every function, so that none held is not what it found
  if (kept.tools.length === 0) return `${kept.complete ? "No tool held." : "No tool was made."} ${dropped}`;

  return `${count(kept.tools.length, "tool")} of tier A. ${dropped}`;
}

// How long the making took in all, from when it began to when it ended, if it did
export function describeMaking(kept: ToolsKept): string {
  const when = timeAgo(kept.started_at) || "a while ago";
  if (kept.finished_at === null) return `Begun ${when}, and not ended`;
  const seconds = (Date.parse(kept.finished_at) - Date.parse(kept.started_at)) / 1000;

  return Number.isFinite(seconds) && seconds >= 0 ? `Made ${when}, in ${describeDuration(seconds)}` : `Made ${when}`;
}

// How many times each call was made again, in words
function times(repeats: number): string {
  return repeats === 1 ? "once" : `${repeats} times`;
}

// What was checked of a tool, in words: how many calls of the tutorials were made again, and that each gave what the tutorial got
export function describeChecked(tool: Pick<ToolSummary, "checked" | "recorded" | "repeats">): string {
  const left = tool.recorded - tool.checked;
  const calls = `${count(tool.checked, "call")}, each made again ${times(tool.repeats)}, gave what the tutorial got every time`;

  return left > 0 ? `${calls}. ${count(left, "other call")} could not be made again` : calls;
}

const SHOWN = 120;

function cut(text: string, limit = SHOWN): string {
  return text.length <= limit ? text : `${text.slice(0, limit)}…`;
}

// What a call was given, as it was written in the tutorial: each parameter with its value
export function describeArgs(args: Record<string, unknown>): string {
  const shown = Object.entries(args).map(([name, value]) => {
    let text: string;
    try {
      text = JSON.stringify(value) ?? "null";
    } catch {
      text = "?";
    }

    return `${name}=${cut(text, 60)}`;
  });

  return cut(shown.join(", "));
}

// What came of making a call again, in words
export function describeCase(one: ToolCase): string {
  const of = `${one.matched} of ${count(one.repeats, "time")}`;
  if (one.verdict === "match") return `Gave what the tutorial got, ${of}`;
  if (one.verdict === "differs") return `Gave something else. It gave what the tutorial got ${of}`;
  if (one.verdict === "error") return `Raised ${one.error?.type ?? "an error"}${one.error?.message ? `: ${cut(one.error.message, 80)}` : ""}`;

  return "Was not made again";
}

// The numbers within which two numbers are the same, in words
export function describeTolerance(tolerance: ToolDetail["evidence"]["tolerance"]): string {
  return `A number is the same if it is within ${tolerance.relative} of the other, or ${tolerance.absolute} from it. Anything else is the same only if it is equal.`;
}

// A parameter of a tool, as a signature would write it
export function describeParameter(parameter: ToolDetail["signature"][number]): string {
  if (parameter.required) return `${parameter.name}: ${parameter.type}`;

  // A default of nothing is what the code calls None
  return `${parameter.name}: ${parameter.type} = ${parameter.default === null ? "None" : cut(JSON.stringify(parameter.default) ?? "None", 40)}`;
}

// What a function that was not made a tool was found to be, with what the check found, in lines
export function droppedLines(dropped: ToolDropped): string[] {
  return dropped.details.filter((line) => line !== dropped.reason);
}
