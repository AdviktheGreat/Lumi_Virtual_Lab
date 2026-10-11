"use client";

import { useEffect, useReducer } from "react";
import { api, ApiError } from "./api";
import { followChat, type Connection } from "./follow";
import { emptyTranscript, reduce, type Transcript } from "./transcript";
import type { ChatEvent, ChatInfo } from "./types";

export type ChatStatus =
  | { kind: "loading" }
  | { kind: "ready"; info: ChatInfo }
  // The conversation is not there, which is the case for one that was deleted, or an address that is wrong
  | { kind: "missing" }
  | { kind: "failed"; error: unknown };

export interface Followed {
  status: ChatStatus;
  transcript: Transcript;
  connection: Connection;
}

type Action =
  | { type: "event"; event: ChatEvent }
  | { type: "connection"; connection: Connection }
  | { type: "status"; status: ChatStatus };

const initial: Followed = { status: { kind: "loading" }, transcript: emptyTranscript, connection: "connecting" };

function step(state: Followed, action: Action): Followed {
  switch (action.type) {
    case "event":
      return { ...state, transcript: reduce(state.transcript, action.event) };
    case "connection":
      return { ...state, connection: action.connection };
    case "status":
      return { ...state, status: action.status };
  }
}

function statusOf(error: unknown): ChatStatus {
  return error instanceof ApiError && error.status === 404 ? { kind: "missing" } : { kind: "failed", error };
}

// A conversation, as it is now and as it goes: what it is, and its events from the first, so that what is shown is the
// same on a page opened at any time. A component that has this is given the conversation's id as its key, so that
// another conversation starts from nothing.
export function useChat(id: string): Followed {
  const [state, dispatch] = useReducer(step, initial);

  useEffect(() => {
    const abort = new AbortController();
    // Of two looks that overlap, the later one has the newer answer, whichever comes back first
    let latest = 0;
    const look = () => {
      const mine = ++latest;
      const current = () => mine === latest && !abort.signal.aborted;

      return api.chat(id, abort.signal).then(
        (info) => {
          if (current()) dispatch({ type: "status", status: { kind: "ready", info } });
        },
        (error: unknown) => {
          if (current()) dispatch({ type: "status", status: statusOf(error) });
        },
      );
    };
    void look();
    const following = followChat(id, {
      onEvent: (event) => dispatch({ type: "event", event }),
      onConnection: (connection) => {
        dispatch({ type: "connection", connection });
        // A stream the server refused is for a reason that asking for the conversation tells
        if (connection === "closed") void look();
      },
    });

    return () => {
      abort.abort();
      following.close();
    };
  }, [id]);

  return state;
}
