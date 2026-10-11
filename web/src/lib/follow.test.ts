import { describe, expect, it } from "vitest";
import { followChat, parseEvent, type Connection } from "./follow";
import type { ChatEvent } from "./types";

class FakeSource {
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed = false;
  listeners = new Map<string, (event: MessageEvent<string>) => void>();

  constructor(readonly url: string) {}

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, listener);
  }

  close() {
    this.closed = true;
    this.readyState = 2;
  }

  send(data: string, type = "chat") {
    this.listeners.get(type)?.({ data } as MessageEvent<string>);
  }
}

const EVENT: ChatEvent = { kind: "answer", id: 7, turn: 1, speaker: "PI", text: "Done", data: {}, time: 1 };

function follow(after?: number, id = "chat-1") {
  const sources: FakeSource[] = [];
  const events: ChatEvent[] = [];
  const connections: Connection[] = [];
  const following = followChat(
    id,
    { onEvent: (event) => events.push(event), onConnection: (connection) => connections.push(connection) },
    after,
    (url) => {
      const source = new FakeSource(url);
      sources.push(source);

      return source;
    },
  );

  return { source: sources[0], events, connections, following };
}

describe("following a conversation", () => {
  it("opens the stream of its events after the one it has, and says it is connecting", () => {
    const { source, connections } = follow(12);

    expect(source.url).toBe("/api/chats/chat-1/events?after=12");
    expect(connections).toEqual(["connecting"]);
  });

  it("names the conversation safely in the address", () => {
    expect(follow(0, "a b/c").source.url).toBe("/api/chats/a%20b%2Fc/events?after=0");
  });

  it("starts from the first event unless it is told where from", () => {
    expect(follow().source.url).toBe("/api/chats/chat-1/events?after=0");
  });

  it("passes on the events it is sent, and ignores what is not an event", () => {
    const { source, events } = follow();

    source.send(JSON.stringify(EVENT));
    source.send("{not json");
    source.send(JSON.stringify({ hello: "world" }));
    source.send("null");

    expect(events).toEqual([EVENT]);
  });

  it("says when the stream is open, when it was cut off and is being opened again, and when it was refused", () => {
    const { source, connections } = follow();

    source.onopen?.(new Event("open"));
    source.readyState = 0;
    source.onerror?.(new Event("error"));
    source.onopen?.(new Event("open"));
    source.readyState = 2;
    source.onerror?.(new Event("error"));

    expect(connections).toEqual(["connecting", "open", "connecting", "open", "closed"]);
  });

  it("closes the stream, and says nothing more after", () => {
    const { source, events, connections, following } = follow();

    following.close();
    source.send(JSON.stringify(EVENT));
    source.onopen?.(new Event("open"));
    source.onerror?.(new Event("error"));

    expect(source.closed).toBe(true);
    expect(events).toEqual([]);
    expect(connections).toEqual(["connecting"]);
  });
});

describe("an event", () => {
  it("is read from the stream's data", () => {
    expect(parseEvent(JSON.stringify(EVENT))).toEqual(EVENT);
  });

  it("must have a number and a kind", () => {
    expect(parseEvent(JSON.stringify({ id: "7", kind: "answer" }))).toBeNull();
    expect(parseEvent(JSON.stringify({ id: 7 }))).toBeNull();
  });
});
