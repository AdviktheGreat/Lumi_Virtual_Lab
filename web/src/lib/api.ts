import type { ChatInfo, ChatSummary, Health, Models, NewChat, Settings } from "./types";

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

export const api = {
  health: (signal?: AbortSignal) => request<Health>("GET", "/health", undefined, signal),
  settings: (signal?: AbortSignal) => request<Settings>("GET", "/settings", undefined, signal),
  models: (signal?: AbortSignal) => request<Models>("GET", "/models", undefined, signal),
  chats: async (signal?: AbortSignal) => (await request<{ chats: ChatSummary[] }>("GET", "/chats", undefined, signal)).chats,
  chat: (id: string, signal?: AbortSignal) => request<ChatInfo>("GET", `/chats/${encodeURIComponent(id)}`, undefined, signal),
  createChat: (chat: NewChat = {}) => request<ChatInfo>("POST", "/chats", chat),
  deleteChat: (id: string) => request<void>("DELETE", `/chats/${encodeURIComponent(id)}`),
  send: (id: string, text: string) =>
    request<{ turn: number; state: string }>("POST", `/chats/${encodeURIComponent(id)}/messages`, { text }),
  stop: (id: string) => request<{ accepted: boolean }>("POST", `/chats/${encodeURIComponent(id)}/stop`),
};
