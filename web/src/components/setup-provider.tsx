"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { SetupDialog, type SetupTab } from "@/components/setup-dialog";
import { useServer } from "@/components/server-provider";
import { isActive } from "@/lib/setup";
import { useJobs, type JobsData } from "@/lib/use-jobs";

interface SetupContext {
  // Opens the setup, at the part of it that is wanted
  open: (tab?: SetupTab) => void;
  // Whether the server is building or fetching something, which goes on while the setup is closed
  working: boolean;
}

const Context = createContext<SetupContext | null>(null);

// The jobs, apart from the rest, since they change every second while one is at work, and a page that only opens the
// setup has no need to be drawn again for it
const JobsContext = createContext<JobsData | null>(null);

export function SetupProvider({ children }: { children: React.ReactNode }) {
  const { report } = useServer();
  const jobs = useJobs(report);
  // What it was opened at, and what had the focus, which is given it again when it is closed
  const [opened, setOpened] = useState<{ tab: SetupTab; opener: HTMLElement | null } | null>(null);

  const open = useCallback((tab: SetupTab = "overview") => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setOpened({ tab, opener });
  }, []);
  const working = jobs.jobs?.some(isActive) ?? false;
  const value = useMemo(() => ({ open, working }), [open, working]);

  return (
    <Context.Provider value={value}>
      <JobsContext.Provider value={jobs}>
        {children}
        {opened !== null && (
          <SetupDialog tab={opened.tab} opener={opened.opener} jobs={jobs} onClose={() => setOpened(null)} />
        )}
      </JobsContext.Provider>
    </Context.Provider>
  );
}

export function useSetup(): SetupContext {
  const value = useContext(Context);
  if (value === null) throw new Error("useSetup needs a SetupProvider");

  return value;
}

// What the server is building and fetching, which a page that shows the progress of it follows
export function useSetupJobs(): JobsData {
  const value = useContext(JobsContext);
  if (value === null) throw new Error("useSetupJobs needs a SetupProvider");

  return value;
}
