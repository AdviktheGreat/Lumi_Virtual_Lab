"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { ChatSummary } from "@/lib/types";
import { useServer } from "@/components/server-provider";

interface ChatsContext {
  // Every conversation, the latest first, or null before the first look
  chats: ChatSummary[] | null;
  // Looks again, which is done after anything that changes the list, and every few seconds besides, so that what
  // another page or a turn that ends in the background did is shown
  refresh: () => Promise<void>;
}

const Context = createContext<ChatsContext | null>(null);

const POLL_MS = 5000;

export function ChatsProvider({ children }: { children: React.ReactNode }) {
  const { report } = useServer();
  const [chats, setChats] = useState<ChatSummary[] | null>(null);

  const refresh = useCallback(async () => {
    try {
      setChats(await api.chats());
    } catch (error) {
      report(error);
    }
  }, [report]);

  useEffect(() => {
    // The list is read when the page opens, which is when this runs
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, POLL_MS);
    const show = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", show);

    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", show);
    };
  }, [refresh]);

  const value = useMemo(() => ({ chats, refresh }), [chats, refresh]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useChats(): ChatsContext {
  const value = useContext(Context);
  if (value === null) throw new Error("useChats needs a ChatsProvider");

  return value;
}
