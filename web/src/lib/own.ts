import { formatBytes } from "./files";
import { timeAgoFromEpoch } from "./format";
import { tidy } from "./scientists";
import type { OwnData, OwnSoftware } from "./types";

// The most characters the server takes of what a piece of data or some software is, and of the name of software
export const MAX_DESCRIPTION = 1000;
export const MAX_SOFTWARE_NAME = 100;

// How many characters there are, as the server counts them: a character of more than one UTF-16 unit is one
function characters(text: string): number {
  return [...text].length;
}

// Why what was written does not say what something is, or null if it does. It is said in words that the lead reads, so
// it has to be there.
export function descriptionProblem(text: string, what: string): string | null {
  const described = tidy(text);
  if (described === "") return `Say what ${what} is, so that the lead knows when to use it.`;
  if (characters(described) > MAX_DESCRIPTION) {
    return `What ${what} is can be at most ${MAX_DESCRIPTION} characters, and this is ${characters(described)}.`;
  }

  return null;
}

// A piece of data is given by uploading a file, or by pointing to a file or folder where it is on the server's machine
export type Way = "upload" | "path";

export interface DataDraft {
  way: Way;
  file: File | null;
  path: string;
  description: string;
}

export const EMPTY_DATA: DataDraft = { way: "upload", file: null, path: "", description: "" };

export type DataProblems = Partial<Record<"source" | "description", string>>;

// What is wrong with a piece of data that is to be given, which is nothing if it is empty. Code finds data by the name of
// its file, so an upload whose name is taken is refused here, where the name is known; the name of what is pointed to is
// found by the server, which refuses it the same way.
export function checkData(draft: DataDraft, taken: readonly string[], limit: number): DataProblems {
  const problems: DataProblems = {};
  if (draft.way === "upload") {
    const { file } = draft;
    if (file === null) {
      problems.source = "Choose the file to upload.";
    } else if (file.size > limit) {
      problems.source = `${file.name} is larger than the ${formatBytes(limit)} that can be uploaded. Point to it where it is on this machine instead.`;
    } else if (taken.includes(file.name)) {
      problems.source = `There is data named ${file.name} already. Code finds data by its name, so delete that first, or rename the file.`;
    }
  } else if (draft.path.trim() === "") {
    problems.source = "Give the full path of the file or folder.";
  }
  const described = descriptionProblem(draft.description, "it");
  if (described !== null) problems.description = described;

  return problems;
}

// What is known of a piece of data, as a line: where it came from, how big it is, and when it was changed
export function dataFacts(data: OwnData, now: Date = new Date()): string {
  const parts = [data.source === "uploaded" ? "Uploaded" : "On this machine"];
  if (data.kind === "folder") parts.push("Folder");
  if (data.kind === "file" && data.bytes !== null) parts.push(formatBytes(data.bytes));
  if (data.kind === "missing") parts.push("Not there");
  const changed = data.modified === null ? "" : timeAgoFromEpoch(data.modified, now);
  if (changed !== "") parts.push(`changed ${changed}`);

  return parts.join(" · ");
}

export type SoftwareProblems = Partial<Record<"name" | "description", string>>;

export interface CheckedSoftware {
  // What to send, or null while there is something wrong
  software: OwnSoftware | null;
  problems: SoftwareProblems;
}

// Whether what was written can be kept as some software, with the name and description as the server keeps them. Some
// that is new takes a name that none has, since the server would keep it in place of what has that name, which is what
// changing it is for.
export function checkSoftware(
  name: string,
  description: string,
  given: readonly OwnSoftware[],
  isNew: boolean,
): CheckedSoftware {
  const title = tidy(name);
  const problems: SoftwareProblems = {};
  if (title === "") problems.name = "Name the software.";
  else if (characters(title) > MAX_SOFTWARE_NAME) {
    problems.name = `The name can be at most ${MAX_SOFTWARE_NAME} characters, and this is ${characters(title)}.`;
  } else if (isNew && given.some((software) => software.name === title)) {
    problems.name = `There is software named ${title}. Change that instead, or choose another name.`;
  }
  const described = descriptionProblem(description, "it");
  if (described !== null) problems.description = described;

  return {
    software: Object.keys(problems).length === 0 ? { name: title, description: tidy(description) } : null,
    problems,
  };
}
