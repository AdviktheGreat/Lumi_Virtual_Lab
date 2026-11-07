"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Campaign, ChatSummary } from "@/lib/types";
import { useServer } from "@/components/server-provider";

interface ChatsContext {
  // Every conversation, the latest first, or null before the first look
  chats: ChatSummary[] | null;
  // Every campaign, in the order they were made, or null before the first look, which is as the conversations are
  campaigns: Campaign[] | null;
  // Looks again, which is done after anything that changes the list, and every few seconds besides, so that what
  // another page or a turn that ends in the background did is shown
  refresh: () => Promise<void>;
}

const Context = createContext<ChatsContext | null>(null);

const POLL_MS = 5000;

export function ChatsProvider({ children }: { children: React.ReactNode }) {
  const { report } = useServer();
  const [chats, setChats] = useState<ChatSummary[] | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);

  const refresh = useCallback(async () => {
    try {
      // Together, so that a program is not shown in a campaign that is not shown yet, or the other way round
      const [listed, made] = await Promise.all([api.chats(), api.campaigns()]);
      setChats(listed);
      setCampaigns(made);
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

  const value = useMemo(() => ({ chats, campaigns, refresh }), [chats, campaigns, refresh]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useChats(): ChatsContext {
  const value = useContext(Context);
  if (value === null) throw new Error("useChats needs a ChatsProvider");

  return value;
}
