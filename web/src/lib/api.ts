import type { Attachment, ChatInfo, ChatSummary, Health, Models, NewChat, Settings } from "./types";

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

export const api = {
  health: (signal?: AbortSignal) => request<Health>("GET", "/health", undefined, signal),
  settings: (signal?: AbortSignal) => request<Settings>("GET", "/settings", undefined, signal),
  models: (signal?: AbortSignal) => request<Models>("GET", "/models", undefined, signal),
  chats: async (signal?: AbortSignal) => (await request<{ chats: ChatSummary[] }>("GET", "/chats", undefined, signal)).chats,
  chat: (id: string, signal?: AbortSignal) => request<ChatInfo>("GET", `/chats/${encodeURIComponent(id)}`, undefined, signal),
  createChat: (chat: NewChat = {}) => request<ChatInfo>("POST", "/chats", chat),
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
};
