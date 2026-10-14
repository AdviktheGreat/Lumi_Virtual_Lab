import { exportNameOf, type ExportFormat } from "./export";
import { fileUrl } from "./files";
import type {
  Attachment,
  ChatFiles,
  ChatInfo,
  ChatSummary,
  DataLake,
  Health,
  Job,
  KeyStatuses,
  LibraryScientist,
  Models,
  NewChat,
  Scientist,
  Settings,
  SettingsChange,
  SetupStatus,
} from "./types";

// What the server's error says: its code is a word to act on, its message is for a person, and the rest is
// whatever else the code carries, such as the keys that are missing
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

// Not the server's error: the server could not be reached at all
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super("The server cannot be reached. Is it still running?", { cause });
    this.name = "NetworkError";
  }
}

function errorFrom(status: number, body: unknown): ApiError {
  if (typeof body === "object" && body !== null && "error" in body) {
    const { code, message, ...details } = (body as { error: Record<string, unknown> }).error;
    if (typeof code === "string" && typeof message === "string") {
      return new ApiError(status, code, message, details);
    }
  }

  return new ApiError(status, "error", `The server answered ${status}`);
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      signal,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new NetworkError(error);
  }
  // What has no body to read, as the answer to a removal, is read as nothing
  let parsed: unknown;
  try {
    parsed = await response.json();
  } catch {
    parsed = undefined;
  }
  if (!response.ok) {
    throw errorFrom(response.status, parsed);
  }

  return parsed as T;
}

function isAttachment(value: unknown): value is Attachment {
  if (typeof value !== "object" || value === null) return false;
  const { name, path, size } = value as Record<string, unknown>;

  return typeof name === "string" && typeof path === "string" && typeof size === "number";
}

interface UploadOptions {
  // Called with how much of the file has been sent, from 0 to 1
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
}

// Sends a file as the body of a request, which is read by hand rather than with fetch, since fetch cannot say how much
// of a body has gone
function uploadFile(chatId: string, file: File, { onProgress, signal }: UploadOptions = {}): Promise<Attachment> {
  return new Promise((resolve, reject) => {
    const aborted = () => new DOMException("Aborted", "AbortError");
    if (signal?.aborted) {
      reject(aborted());

      return;
    }
    const upload = new XMLHttpRequest();
    upload.open("POST", `/api/chats/${encodeURIComponent(chatId)}/uploads?name=${encodeURIComponent(file.name)}`);
    upload.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress?.(Math.min(1, event.loaded / event.total));
    };
    upload.onload = () => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(upload.responseText);
      } catch {
        parsed = undefined;
      }
      if (upload.status < 200 || upload.status >= 300) {
        reject(errorFrom(upload.status, parsed));
      } else if (isAttachment(parsed)) {
        resolve(parsed);
      } else {
        reject(new ApiError(upload.status, "error", "The server did not say where it kept the file"));
      }
    };
    // The browser says nothing of why, and a folder, which has nothing to read, fails the same way as a lost connection
    upload.onerror = () => reject(new Error("The file could not be sent. It may be a folder, or the server may have stopped."));
    upload.onabort = () => reject(aborted());
    signal?.addEventListener("abort", () => upload.abort(), { once: true });
    upload.send(file);
  });
}

// What a request that is not for JSON is answered with, once it is known to have gone well: what went wrong is told in
// the server's own shape, which is read, and what went well is left for the caller to read
async function fetchBody(address: string, signal?: AbortSignal): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(address, { signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new NetworkError(error);
  }
  if (!response.ok) {
    let parsed: unknown;
    try {
      parsed = await response.json();
    } catch {
      parsed = undefined;
    }
    throw errorFrom(response.status, parsed);
  }

  return response;
}

export interface FileText {
  text: string;
  // Whether the file goes on after what was read
  truncated: boolean;
  // Whether it is not text, which is so for a file that has a null byte in what was read
  binary: boolean;
}

// The start of a file, as text. Only as much as the limit is taken from the server, whatever the size of the file.
async function readFileText(chatId: string, path: string, limit: number, signal?: AbortSignal): Promise<FileText> {
  const response = await fetchBody(fileUrl(chatId, path), signal);
  const reader = response.body?.getReader();
  if (!reader) return { text: await response.text(), truncated: false, binary: false };
  const chunks: Uint8Array[] = [];
  let length = 0;
  let truncated = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      length += value.length;
      if (length > limit) {
        truncated = true;
        void reader.cancel();
        break;
      }
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new NetworkError(error);
  }
  const bytes = new Uint8Array(Math.min(length, limit));
  let at = 0;
  for (const chunk of chunks) {
    const room = bytes.length - at;
    bytes.set(chunk.length > room ? chunk.subarray(0, room) : chunk, at);
    at += Math.min(chunk.length, room);
  }
  // A character that the limit cut in two is dropped by the decoder, which stops reading at what is not whole
  const text = new TextDecoder("utf-8", { fatal: false }).decode(bytes, { stream: truncated });

  return { text, truncated, binary: text.includes("\0") };
}

export interface ExportedChat {
  file: Blob;
  // What to save it as
  name: string;
}

// A conversation as a document, whole, which is made for it by the server. It is fetched here, and not by a link that
// downloads, so that what the server says when it cannot make it is told, and not saved as the file.
async function exportChat(id: string, format: ExportFormat, signal?: AbortSignal): Promise<ExportedChat> {
  const response = await fetchBody(`/api/chats/${encodeURIComponent(id)}/export?format=${format}`, signal);
  let file: Blob;
  try {
    file = await response.blob();
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new NetworkError(error);
  }

  return { file, name: exportNameOf(response.headers.get("Content-Disposition"), format) };
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>("GET", "/health", undefined, signal),
  settings: (signal?: AbortSignal) => request<Settings>("GET", "/settings", undefined, signal),
  // Only what is given is changed, and the settings are given back as they now are
  changeSettings: (changes: SettingsChange) => request<Settings>("PATCH", "/settings", changes),
  models: (signal?: AbortSignal) => request<Models>("GET", "/models", undefined, signal),
  keys: (signal?: AbortSignal) => request<KeyStatuses>("GET", "/keys", undefined, signal),
  // A key is kept by the server until it stops, and is never given back: what comes back is which are set
  setKey: (name: string, value: string) => request<KeyStatuses>("PUT", `/keys/${encodeURIComponent(name)}`, { value }),
  removeKey: (name: string) => request<KeyStatuses>("DELETE", `/keys/${encodeURIComponent(name)}`),
  scientists: async (signal?: AbortSignal) =>
    (await request<{ scientists: LibraryScientist[] }>("GET", "/scientists", undefined, signal)).scientists,
  // One with the title of another takes its place, and the library is given back as it now is
  saveScientist: async (scientist: Scientist) =>
    (await request<{ scientists: LibraryScientist[] }>("PUT", "/scientists", scientist)).scientists,
  removeScientist: async (title: string) =>
    (await request<{ scientists: LibraryScientist[] }>("DELETE", `/scientists/${encodeURIComponent(title)}`)).scientists,
  // Docker, the images, the data lake, the jobs, and what is left to do. Asking is not quick, since Docker is asked.
  setup: (signal?: AbortSignal) => request<SetupStatus>("GET", "/setup", undefined, signal),
  // Starts building a stage of the image, which goes on as a job
  buildImage: (stage: string) => request<Job>("POST", `/setup/images/${encodeURIComponent(stage)}`),
  dataLake: (signal?: AbortSignal) => request<DataLake>("GET", "/setup/data-lake", undefined, signal),
  // Starts fetching the files named, or all of them if none are named, which goes on as a job
  fetchDataLake: (names?: string[]) => request<Job>("POST", "/setup/data-lake", names === undefined ? undefined : { names }),
  jobs: async (signal?: AbortSignal) => (await request<{ jobs: Job[] }>("GET", "/setup/jobs", undefined, signal)).jobs,
  // A job with what it printed from the line numbered, counting from 0
  job: (id: string, logFrom: number, signal?: AbortSignal) =>
    request<Job>("GET", `/setup/jobs/${encodeURIComponent(id)}?log_from=${logFrom}`, undefined, signal),
  stopJob: (id: string) => request<Job>("POST", `/setup/jobs/${encodeURIComponent(id)}/stop`),
  chats: async (signal?: AbortSignal) => (await request<{ chats: ChatSummary[] }>("GET", "/chats", undefined, signal)).chats,
  chat: (id: string, signal?: AbortSignal) => request<ChatInfo>("GET", `/chats/${encodeURIComponent(id)}`, undefined, signal),
  createChat: (chat: NewChat = {}) => request<ChatInfo>("POST", "/chats", chat),
  // Gives it another title, which the server tidies, and tells of to whoever follows the conversation
  renameChat: (id: string, title: string) => request<ChatInfo>("PATCH", `/chats/${encodeURIComponent(id)}`, { title }),
  deleteChat: (id: string) => request<void>("DELETE", `/chats/${encodeURIComponent(id)}`),
  // Attachments are named as the server named them when it was sent the files
  send: (id: string, text: string, attachments: string[] = []) =>
    request<{ turn: number; state: string }>("POST", `/chats/${encodeURIComponent(id)}/messages`, { text, attachments }),
  // What steers a turn that is running is accepted or not: a turn that has ended meanwhile has nothing to steer
  note: (id: string, text: string) =>
    request<{ accepted: boolean }>("POST", `/chats/${encodeURIComponent(id)}/note`, { text }),
  pause: (id: string) => request<{ accepted: boolean }>("POST", `/chats/${encodeURIComponent(id)}/pause`),
  resume: (id: string) => request<{ accepted: boolean }>("POST", `/chats/${encodeURIComponent(id)}/resume`),
  stop: (id: string) => request<{ accepted: boolean }>("POST", `/chats/${encodeURIComponent(id)}/stop`),
  upload: uploadFile,
  // What the conversation made or was given
  files: (id: string, signal?: AbortSignal) => request<ChatFiles>("GET", `/chats/${encodeURIComponent(id)}/files`, undefined, signal),
  fileText: readFileText,
  exportChat,
};
