import { ApiError } from "./api";
import { formatBytes } from "./files";
import type { Attachment } from "./types";

// The most files that go with one message, which is as many as the server takes
export const MAX_ATTACHMENTS = 100;

// "queued" is a file that is held until the conversation it is for is there to take it
export type TrayStatus = "queued" | "uploading" | "ready" | "failed";

// A file the researcher has chosen to send with their message, and how far it has got
export interface TrayItem {
  id: number;
  file: File;
  status: TrayStatus;
  // How much of it has been sent, from 0 to 1
  progress: number;
  // What the server named it once it has it, which is the name to send with the message
  attachment: Attachment | null;
  error: string | null;
  // Whether trying again can work, which it cannot for a file the server has turned away for what it is
  retryable: boolean;
}

function sameFile(a: File, b: File): boolean {
  return a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;
}

// What becomes of files that were chosen: those that can go with the message, queued, and a word for each that
// cannot. A file that is there already is not added again. Each is numbered from firstId by its place among the files,
// so that the next batch can begin at firstId plus how many there were.
export function intake(
  existing: TrayItem[],
  files: File[],
  limit: number | null,
  firstId: number,
): { items: TrayItem[]; refused: string[] } {
  const items: TrayItem[] = [];
  const refused: string[] = [];
  let full = false;
  for (const [place, file] of files.entries()) {
    if ([...existing, ...items].some((item) => item.status !== "failed" && sameFile(item.file, file))) continue;
    if (limit !== null && file.size > limit) {
      refused.push(`${file.name} is larger than the ${formatBytes(limit)} that can be attached`);
    } else if (existing.length + items.length >= MAX_ATTACHMENTS) {
      full = true;
    } else {
      items.push({
        id: firstId + place,
        file,
        status: "queued",
        progress: 0,
        attachment: null,
        error: null,
        retryable: true,
      });
    }
  }
  if (full) refused.push(`Only ${MAX_ATTACHMENTS} files can go with one message`);

  return { items, refused };
}

export type TrayAction =
  | { type: "add"; items: TrayItem[] }
  | { type: "begin"; id: number }
  | { type: "progress"; id: number; progress: number }
  | { type: "ready"; id: number; attachment: Attachment }
  | { type: "fail"; id: number; error: string; retryable: boolean }
  | { type: "requeue"; ids: number[] }
  | { type: "requeueReady" }
  | { type: "remove"; ids: number[] };

function change(items: TrayItem[], id: number, update: (item: TrayItem) => TrayItem): TrayItem[] {
  return items.map((item) => (item.id === id ? update(item) : item));
}

function requeued(item: TrayItem): TrayItem {
  return { ...item, status: "queued", progress: 0, attachment: null, error: null, retryable: true };
}

// What the tray holds once something has happened. What is said of a file that has gone from it, or that is not being
// sent any more, such as how far it got as it was called off, changes nothing.
export function tray(items: TrayItem[], action: TrayAction): TrayItem[] {
  switch (action.type) {
    case "add":
      return [...items, ...action.items];
    case "begin":
      return change(items, action.id, (item) => ({ ...item, status: "uploading", progress: 0, error: null }));
    case "progress":
      return change(items, action.id, (item) =>
        item.status === "uploading" ? { ...item, progress: Math.max(item.progress, Math.min(1, action.progress)) } : item,
      );
    case "ready":
      return change(items, action.id, (item) =>
        item.status === "uploading" ? { ...item, status: "ready", progress: 1, attachment: action.attachment } : item,
      );
    case "fail":
      return change(items, action.id, (item) =>
        item.status === "uploading"
          ? { ...item, status: "failed", error: action.error, retryable: action.retryable }
          : item,
      );
    case "requeue":
      return items.map((item) => (action.ids.includes(item.id) && item.status !== "uploading" ? requeued(item) : item));
    case "requeueReady":
      return items.map((item) => (item.status === "ready" ? requeued(item) : item));
    case "remove":
      return items.filter((item) => !action.ids.includes(item.id));
  }
}

export function counts(items: TrayItem[]): Record<TrayStatus, number> {
  const total: Record<TrayStatus, number> = { queued: 0, uploading: 0, ready: 0, failed: 0 };
  for (const item of items) total[item.status] += 1;

  return total;
}

// What the message is sent with: the name each file was given, once, in the order they were chosen
export function attachedNames(items: TrayItem[]): string[] {
  const names = items.flatMap((item) => (item.status === "ready" && item.attachment ? [item.attachment.name] : []));

  return [...new Set(names)];
}

// Whether a message can go as it is, and if not, what is holding it up. A file that is on its way is waited for, and one
// that failed is not left out without the researcher choosing to.
export function readiness(items: TrayItem[]): string | null {
  const { uploading, failed } = counts(items);
  if (uploading > 0) return uploading === 1 ? "Uploading a file…" : `Uploading ${uploading} files…`;
  if (failed > 0) return "Retry or remove the file that failed";

  return null;
}

// Whether trying a file again can work: not when the server has said the file, or the way it is sent, is wrong
export function canRetry(error: unknown): boolean {
  return !(error instanceof ApiError && error.status >= 400 && error.status < 500);
}
