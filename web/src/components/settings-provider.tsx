"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { SettingsDialog, type SettingsTab } from "@/components/settings-dialog";
import { useServer } from "@/components/server-provider";
import type { Settings } from "@/lib/types";

interface SettingsContext {
  // Opens the settings, at the part of them that is wanted, and gives the focus back to what had it, or to what is named
  // if what has it is about to go. Nothing opens while the server has not said what they are.
  open: (tab?: SettingsTab, opener?: HTMLElement | null) => void;
}

const Context = createContext<SettingsContext | null>(null);

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const { server } = useServer();
  // What the settings were when they were opened, which the dialog goes on from, and which is not undone should the
  // server be lost while it is open; and what had the focus, which is given it again when they are closed
  const [opened, setOpened] = useState<{ tab: SettingsTab; settings: Settings; opener: HTMLElement | null } | null>(null);
  const settings = server.status === "ready" ? server.settings : null;

  const open = useCallback(
    (tab: SettingsTab = "model", opener?: HTMLElement | null) => {
      const focused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      if (settings !== null) setOpened({ tab, settings, opener: opener === undefined ? focused : opener });
    },
    [settings],
  );
  const value = useMemo(() => ({ open }), [open]);

  return (
    <Context.Provider value={value}>
      {children}
      {opened !== null && (
        <SettingsDialog settings={opened.settings} tab={opened.tab} opener={opened.opener} onClose={() => setOpened(null)} />
      )}
    </Context.Provider>
  );
}

export function useSettings(): SettingsContext {
  const value = useContext(Context);
  if (value === null) throw new Error("useSettings needs a SettingsProvider");

  return value;
}
