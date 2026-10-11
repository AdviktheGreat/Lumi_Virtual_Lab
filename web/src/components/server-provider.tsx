"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, NetworkError } from "@/lib/api";
import type { Settings } from "@/lib/types";

// How the server stands with this page: "unreachable" if it is not there, which is "lost" if it was a moment ago,
// and "unauthorized" if it is there and wants the link it printed when it started, which has its token
export type ServerState =
  | { status: "checking" }
  | { status: "ready"; version: string; settings: Settings }
  | { status: "unreachable"; lost: boolean }
  | { status: "unauthorized"; message: string };

interface ServerContext {
  server: ServerState;
  // Looks at the server again
  check: () => Promise<void>;
  // Says what an error from a request was, so that the page that makes it need not: the server is looked at again
  // if it may be what is wrong
  report: (error: unknown) => void;
  // The settings as they are now, once the server has them
  setSettings: (settings: Settings) => void;
}

const Context = createContext<ServerContext | null>(null);

// Seconds between looks at a server that is not there, which a page left open comes back from
const RETRY_MS = 3000;

export function ServerProvider({ children }: { children: React.ReactNode }) {
  const [server, setServer] = useState<ServerState>({ status: "checking" });
  const looking = useRef<Promise<void> | null>(null);

  const check = useCallback(() => {
    if (looking.current !== null) return looking.current;
    const look = (async () => {
      try {
        const health = await api.health();
        const settings = await api.settings();
        setServer({ status: "ready", version: health.version, settings });
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          setServer({ status: "unauthorized", message: error.message });
        } else if (error instanceof NetworkError || error instanceof ApiError) {
          setServer((current) => ({
            status: "unreachable",
            lost: current.status === "ready" || (current.status === "unreachable" && current.lost),
          }));
        } else {
          throw error;
        }
      } finally {
        looking.current = null;
      }
    })();
    looking.current = look;

    return look;
  }, []);

  useEffect(() => {
    // The server is looked at when the page opens, which is when this runs
    void check();
  }, [check]);

  useEffect(() => {
    if (server.status !== "unreachable") return;
    const timer = setInterval(() => void check(), RETRY_MS);

    return () => clearInterval(timer);
  }, [server.status, check]);

  const report = useCallback(
    (error: unknown) => {
      if (error instanceof NetworkError || (error instanceof ApiError && error.status === 401)) void check();
    },
    [check],
  );

  const setSettings = useCallback((settings: Settings) => {
    setServer((current) => (current.status === "ready" ? { ...current, settings } : current));
  }, []);

  const value = useMemo(() => ({ server, check, report, setSettings }), [server, check, report, setSettings]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useServer(): ServerContext {
  const value = useContext(Context);
  if (value === null) throw new Error("useServer needs a ServerProvider");

  return value;
}
