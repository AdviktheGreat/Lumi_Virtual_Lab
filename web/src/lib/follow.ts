import type { ChatEvent } from "./types";

// "connecting" is the first connection and any after the stream was cut off, which the browser makes again on its
// own, naming the last event it had. "closed" is for good: the server refused the stream.
export type Connection = "connecting" | "open" | "closed";

export interface Following {
  close(): void;
}

interface Source {
  readyState: number;
  onopen: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void;
  close(): void;
}

export type SourceFactory = (url: string) => Source;

const CLOSED = 2;

export function parseEvent(data: string): ChatEvent | null {
  try {
    const event = JSON.parse(data) as Partial<ChatEvent> | null;
    if (typeof event?.id === "number" && typeof event.kind === "string") {
      return event as ChatEvent;
    }
  } catch {
    // A stream that sends what is not an event is not followed further than the events before it
  }

  return null;
}

// Follows a conversation's events: those after the one named, then each as it happens.
export function followChat(
  id: string,
  handlers: { onEvent: (event: ChatEvent) => void; onConnection: (connection: Connection) => void },
  after = 0,
  open: SourceFactory = (url) => new EventSource(url),
): Following {
  const source = open(`/api/chats/${encodeURIComponent(id)}/events?after=${after}`);
  let closed = false;
  handlers.onConnection("connecting");
  source.onopen = () => {
    if (!closed) handlers.onConnection("open");
  };
  source.onerror = () => {
    if (closed) return;
    handlers.onConnection(source.readyState === CLOSED ? "closed" : "connecting");
  };
  source.addEventListener("chat", (message) => {
    const event = parseEvent(message.data);
    if (event !== null && !closed) handlers.onEvent(event);
  });

  return {
    close() {
      closed = true;
      source.close();
    },
  };
}
