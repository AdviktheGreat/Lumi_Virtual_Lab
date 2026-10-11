import type { Transcript } from "./transcript";

// Where a conversation's files are, which the server sends with a type that runs nothing, so that a page may show
// what the agents' code wrote

const IMAGE_TYPES = /\.(png|jpe?g|gif|webp|svg)$/i;

export function isImage(path: string): boolean {
  return IMAGE_TYPES.test(path);
}

// The address of a file, by its path from the conversation's files
export function fileUrl(chatId: string, path: string, download = false): string {
  const encoded = path.split("/").map(encodeURIComponent).join("/");

  return `/api/chats/${encodeURIComponent(chatId)}/files/${encoded}${download ? "?download=true" : ""}`;
}

// A path from where the code ran, tidied, if it stays inside the conversation's files: nothing that starts from the
// root, goes up a directory, or is not a path on any system
export function insidePath(path: string): string | null {
  if (path.startsWith("/")) return null;
  const parts = path.split("/").filter((part) => part !== "" && part !== ".");
  if (parts.length === 0 || parts.some((part) => part === ".." || part.includes("\\") || part.includes("\0"))) {
    return null;
  }

  return parts.join("/");
}

// What an address in an answer names, if it names a file of the conversation: a path, with nothing in front of it that
// would take the page elsewhere
export function localPath(address: string): string | null {
  const given = address.trim();
  if (given === "" || /^[a-z][a-z0-9+.-]*:/i.test(given)) {
    return null;
  }
  try {
    return insidePath(decodeURI(given.split(/[?#]/)[0]));
  } catch {
    return null;
  }
}

// A size, as a person would say it
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }

  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

// What a file is shown as in the page: a picture, a table, text, or nothing, for which it can only be saved
export type Preview = "image" | "table" | "text" | "none";

const IMAGE_MEDIA = new Set(["image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"]);
const TABLE_MEDIA = new Set(["text/csv", "text/tab-separated-values"]);
const TEXT_MEDIA = new Set(["application/json", "application/xml", "application/x-yaml", "application/yaml", "application/toml"]);
// Files the server cannot tell the type of, or sends as a download, which are text all the same
const TEXT_EXTENSIONS = new Set([
  "txt", "md", "py", "r", "sh", "log", "json", "yaml", "yml", "toml", "ini", "cfg", "xml",
  "fa", "fasta", "fna", "faa", "fastq", "fq", "gb", "gbk", "gff", "gtf", "bed", "vcf", "sam", "pdb", "cif", "mol", "sdf", "smi", "tex", "bib", "sql",
]);

function extensionOf(path: string): string {
  const name = path.split("/").at(-1) ?? "";
  const dot = name.lastIndexOf(".");

  return dot <= 0 ? "" : name.slice(dot + 1).toLowerCase();
}

export function previewOf(file: { path: string; type: string }): Preview {
  const type = file.type.split(";")[0].trim().toLowerCase();
  const extension = extensionOf(file.path);
  if (IMAGE_MEDIA.has(type)) return "image";
  if (TABLE_MEDIA.has(type) || extension === "csv" || extension === "tsv") return "table";
  if (type.startsWith("text/") || TEXT_MEDIA.has(type) || TEXT_EXTENSIONS.has(extension)) return "text";

  return "none";
}

// Whether the server shows a file in the page itself, so that opening it in a tab does not save it. A PDF is not: the
// policy it is sent with, which keeps what an agent wrote from running, also stops a browser from showing it.
export function opensInPage(file: { type: string }): boolean {
  const type = file.type.split(";")[0].trim().toLowerCase();

  return IMAGE_MEDIA.has(type) || TABLE_MEDIA.has(type) || type === "text/plain" || type === "text/markdown" || type === "application/json";
}

export function baseName(path: string): string {
  return path.split("/").at(-1) ?? path;
}

// The directory of a path, which is empty for a file that is at the top
export function folderOf(path: string): string {
  const at = path.lastIndexOf("/");

  return at === -1 ? "" : path.slice(0, at);
}

export interface Folder<T extends { path: string }> {
  // Empty for what is at the top
  name: string;
  files: T[];
}

// Files by the directory they are in, with what is at the top first and then the directories in order
export function inFolders<T extends { path: string }>(files: T[]): Folder<T>[] {
  const folders = new Map<string, T[]>();
  for (const file of [...files].sort((a, b) => a.path.localeCompare(b.path, "en", { numeric: true }))) {
    const name = folderOf(file.path);
    folders.set(name, [...(folders.get(name) ?? []), file]);
  }

  return [...folders.entries()]
    .sort(([a], [b]) => a.localeCompare(b, "en", { numeric: true }))
    .map(([name, inside]) => ({ name, files: inside }));
}

// The files whose path has the words that were typed, in any order and whatever their case
export function matching<T extends { path: string }>(files: T[], typed: string): T[] {
  const words = typed.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return files;

  return files.filter((file) => {
    const path = file.path.toLowerCase();

    return words.every((word) => path.includes(word));
  });
}

// A number that goes up whenever something has happened that may have made or changed a file, which is when code has run,
// when a turn has ended, and when a file was sent with a message
export function filesChanged(transcript: Transcript): number {
  let changes = 0;
  for (const turn of transcript.turns) {
    changes += turn.user?.attachments.length ?? 0;
    if (turn.outcome !== "running") changes += 1;
    for (const step of turn.steps) {
      if (step.kind !== "call") continue;
      changes += step.call.cells.length;
      for (const labStep of step.call.lab?.turns.flatMap((each) => each.steps) ?? []) {
        if (labStep.kind === "cell" || (labStep.kind === "code" && labStep.cell !== null)) changes += 1;
      }
    }
  }

  return changes;
}

// What a table's cells are divided by
export function dividerOf(file: { path: string; type: string }): string {
  return file.type.split(";")[0].trim().toLowerCase() === "text/tab-separated-values" || extensionOf(file.path) === "tsv" ? "\t" : ",";
}
