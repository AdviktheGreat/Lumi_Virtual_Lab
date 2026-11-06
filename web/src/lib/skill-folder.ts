// A folder of skills as a person gives it to the page, by dropping it or by choosing it, and what can be said of it before
// it is sent. The server decides what is kept (see Skills.upload in virtual_lab/server/skills.py), so this says only what is
// cheap to say and certain: that there is a SKILL.md, and that there are not too many files or too many bytes.

// The most files and bytes that can be put in, which are MAX_COPIED_FILES and MAX_COPIED_BYTES in virtual_lab/skills.py
export const FOLDER_MAX_FILES = 2_000;
export const FOLDER_MAX_BYTES = 50_000_000;

// How many levels below a folder a SKILL.md is looked for, as MAX_SKILL_DEPTH is in virtual_lab/skills.py, and how many
// skills are read to be shown
const FOLDER_SKILL_DEPTH = 5;
export const FOLDER_SKILLS_SHOWN = 50;
const SKILL_READ_BYTES = 20_000;

// What of a repository's folders is not sent, since a skill does not need it and the server leaves it out: SKIPPED_DIRECTORIES
// and UPLOAD_SKIPPED_FILES
const PASSED_OVER_FOLDERS = new Set([".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv"]);
const PASSED_OVER_FILES = new Set([".DS_Store"]);

export interface FolderFile {
  // Where the file is in the folder, from inside it: scripts/fit.py
  path: string;
  file: File;
}

export interface PickedFolder {
  name: string;
  files: FolderFile[];
  bytes: number;
  // How many files were not taken, for being in a folder such as .git or being a .DS_Store
  passedOver: number;
  // Whether there were more files than can be put in, in which case reading stopped
  tooMany: boolean;
}

export type Picked = { folder: PickedFolder } | { problem: string };

export interface FoundSkill {
  // Where its SKILL.md is, from inside the folder
  path: string;
  name: string;
  description: string | null;
}

// Whether a file, by where it is in the folder, is one that is not sent
export function isPassedOver(path: string): boolean {
  const parts = path.split("/");

  return parts.slice(0, -1).some((part) => PASSED_OVER_FOLDERS.has(part)) || PASSED_OVER_FILES.has(parts[parts.length - 1]);
}

function folderOf(files: { path: string; file: File }[], name: string, passedOver: number, tooMany: boolean): PickedFolder {
  return { name, files, bytes: files.reduce((total, each) => total + each.file.size, 0), passedOver, tooMany };
}

// A folder that was chosen with a file input that takes one, whose files each say where they are, starting with the folder's
// own name
export function folderFromInput(files: File[]): Picked {
  if (files.length === 0) return { problem: "There was nothing in that folder." };
  const kept: FolderFile[] = [];
  let name = "";
  let passedOver = 0;
  for (const file of files) {
    const written = file.webkitRelativePath || file.name;
    const slash = written.indexOf("/");
    if (slash >= 0 && name === "") name = written.slice(0, slash);
    const path = slash >= 0 ? written.slice(slash + 1) : written;
    if (isPassedOver(path)) passedOver += 1;
    else kept.push({ path, file });
  }

  return { folder: folderOf(kept, name || "skill", passedOver, kept.length > FOLDER_MAX_FILES) };
}

// What of a dropped item a page can walk, which is the shape of the browser's FileSystemEntry, said here as far as is used so
// that a folder can be made up to try it on
export interface DroppedFile {
  isFile: true;
  isDirectory: false;
  name: string;
  file(done: (file: File) => void, failed: (error: unknown) => void): void;
}

export interface DroppedFolder {
  isFile: false;
  isDirectory: true;
  name: string;
  createReader(): { readEntries(done: (entries: DroppedEntry[]) => void, failed: (error: unknown) => void): void };
}

export type DroppedEntry = DroppedFile | DroppedFolder;

function fileOf(entry: DroppedFile): Promise<File> {
  return new Promise((done, failed) => entry.file(done, failed));
}

// All the entries of a folder: a reader gives them a hundred or so at a time, until it gives none
async function entriesOf(folder: DroppedFolder): Promise<DroppedEntry[]> {
  const reader = folder.createReader();
  const all: DroppedEntry[] = [];
  for (;;) {
    const some = await new Promise<DroppedEntry[]>((done, failed) => reader.readEntries(done, failed));
    if (some.length === 0) return all;
    all.push(...some);
  }
}

// A folder that was dropped, which is walked, leaving out what is not sent and stopping when there are more files than can be
// put in
export async function folderFromDrop(entries: DroppedEntry[]): Promise<Picked> {
  if (entries.length === 0) return { problem: "Nothing was dropped." };
  if (entries.length > 1) return { problem: "Drop one folder, and not several things." };
  const [root] = entries;
  if (root.isFile) {
    return { problem: `${root.name} is a file. Drop the folder that the skill is in, which has a SKILL.md in it.` };
  }
  const kept: FolderFile[] = [];
  let passedOver = 0;
  let tooMany = false;
  async function walk(folder: DroppedFolder, prefix: string): Promise<void> {
    for (const entry of await entriesOf(folder)) {
      if (tooMany) return;
      const path = `${prefix}${entry.name}`;
      if (entry.isDirectory) {
        if (PASSED_OVER_FOLDERS.has(entry.name)) passedOver += 1;
        else await walk(entry, `${path}/`);
      } else if (PASSED_OVER_FILES.has(entry.name)) {
        passedOver += 1;
      } else if (kept.length >= FOLDER_MAX_FILES) {
        tooMany = true;
      } else {
        kept.push({ path, file: await fileOf(entry) });
      }
    }
  }
  try {
    await walk(root, "");
  } catch {
    return { problem: "That folder could not be read. Try choosing it instead." };
  }
  if (kept.length === 0 && !tooMany) return { problem: "There was nothing in that folder." };

  return { folder: folderOf(kept, root.name, passedOver, tooMany) };
}

// How big a folder is, in thousands and millions of bytes, which is how the most that can be put in is said
export function folderSize(bytes: number): string {
  if (bytes < 1_000) return `${bytes} B`;
  if (bytes < 1_000_000) return `${Math.round(bytes / 1_000)} KB`;
  const millions = bytes / 1_000_000;

  return `${millions < 10 ? millions.toFixed(1) : Math.round(millions)} MB`;
}

// What is wrong with a folder before it is sent, or null: that it has no SKILL.md, or more files or bytes than can be put in
export function folderProblem(folder: PickedFolder): string | null {
  if (folder.tooMany || folder.files.length > FOLDER_MAX_FILES) {
    return `${folder.name} has more than ${FOLDER_MAX_FILES.toLocaleString("en-US")} files, which is more than a skill needs. Choose a folder with fewer.`;
  }
  if (folder.bytes > FOLDER_MAX_BYTES) {
    return `${folder.name} is ${folderSize(folder.bytes)}, and no more than ${folderSize(FOLDER_MAX_BYTES)} can be put in. Choose a smaller folder.`;
  }
  if (!folder.files.some((each) => each.path.split("/").pop() === "SKILL.md")) {
    return `There is no SKILL.md in ${folder.name}. A skill is a folder with a SKILL.md in it, which says what it is called and for.`;
  }

  return null;
}

function unquoted(value: string): string {
  const text = value.trim();

  return text.length >= 2 && text[0] === text[text.length - 1] && (text[0] === '"' || text[0] === "'") ? text.slice(1, -1) : text;
}

// The name and the description a SKILL.md gives at its top, read as far as a line each, with a line after it that is indented
// being a part of it, which is as far as is needed to show them. Null is for a field that is not there. A SKILL.md with no
// YAML at its top gives nothing.
export function skillFields(text: string): { name: string | null; description: string | null } {
  const block = /^\uFEFF?---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/.exec(text);
  const fields: Record<string, string> = {};
  if (block !== null) {
    let key: string | null = null;
    for (const line of block[1].split(/\r?\n/)) {
      const top = /^([A-Za-z_][\w-]*):[ \t]*(.*)$/.exec(line);
      if (top !== null) {
        key = top[1];
        const value = top[2].trim();
        // A block of text, which is what follows on the lines indented under it
        fields[key] = /^[>|][+-]?\d*$/.test(value) ? "" : unquoted(value);
      } else if (key !== null && /^[ \t]/.test(line) && line.trim() !== "") {
        fields[key] = `${fields[key]} ${line.trim()}`.trim();
      }
    }
  }

  return { name: fields.name || null, description: fields.description || null };
}

// The skills a folder has, each by its SKILL.md that is not deeper than the server looks, with the name and description it
// gives. A skill with no name is called what its folder is, as the server calls it.
export async function skillsIn(folder: PickedFolder): Promise<{ skills: FoundSkill[]; more: number }> {
  const files = folder.files
    .filter((each) => each.path.split("/").pop() === "SKILL.md" && each.path.split("/").length - 1 <= FOLDER_SKILL_DEPTH)
    .sort((a, b) => a.path.length - b.path.length || a.path.localeCompare(b.path));
  const skills: FoundSkill[] = [];
  for (const { path, file } of files.slice(0, FOLDER_SKILLS_SHOWN)) {
    const parts = path.split("/");
    const called = parts.length > 1 ? parts[parts.length - 2] : folder.name;
    const { name, description } = skillFields(await file.slice(0, SKILL_READ_BYTES).text());
    skills.push({ path, name: name ?? called, description });
  }

  return { skills, more: Math.max(0, files.length - skills.length) };
}
