"use client";

import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { LakeTab } from "@/components/setup-lake";
import { JobsTab } from "@/components/setup-jobs";
import type { SetupActions } from "@/components/setup-job";
import { OverviewTab } from "@/components/setup-overview";
import { useServer } from "@/components/server-provider";
import { useSettings } from "@/components/settings-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { returnFocusTo } from "@/lib/focus";
import type { Job } from "@/lib/types";
import { useJobLogs, type JobsData } from "@/lib/use-jobs";
import { useSetupData } from "@/lib/use-setup-data";

export type SetupTab = "overview" | "lake" | "jobs";

const TABS: { value: SetupTab; label: string }[] = [
  { value: "overview", label: "Overview" },
  { value: "lake", label: "Data lake" },
  { value: "jobs", label: "Jobs" },
];

function isTab(value: string): value is SetupTab {
  return TABS.some((tab) => tab.value === value);
}

// What the code needs to run in Docker, and the building and fetching of what is not there yet. Both go on in the
// background, and go on when this is closed.
export function SetupDialog({
  tab: first,
  opener,
  jobs,
  onClose,
}: {
  tab: SetupTab;
  // What had the focus when it was opened, which has it again once it is closed
  opener: HTMLElement | null;
  jobs: JobsData;
  onClose: () => void;
}) {
  const { server, report } = useServer();
  const settings = useSettings();
  const data = useSetupData(jobs.finished);
  const [tab, setTab] = useState(first);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const logs = useJobLogs(jobs.jobs, tab === "jobs" ? selected : null);
  const { track, refresh: refreshJobs } = jobs;
  const { refresh: refreshData } = data;

  useEffect(() => {
    // What the jobs are is looked at when this opens, since it may have changed since they were last looked at
    void refreshJobs();
  }, [refreshJobs]);

  const actions = useMemo<SetupActions>(() => {
    // Starts or stops something, which is shown once the server has done it. Whatever it was refused for, which may be
    // that it is done already, is looked at again.
    async function run(action: () => Promise<Job>) {
      setBusy(true);
      setProblem(null);
      try {
        track(await action());
        refreshData();
      } catch (error) {
        report(error);
        setProblem(describeError(error));
        void refreshJobs();
        refreshData();
      } finally {
        setBusy(false);
      }
    }

    return {
      busy,
      build: (stage) => void run(() => api.buildImage(stage)),
      fetch: (names) => void run(() => api.fetchDataLake(names)),
      stop: (job) => void run(() => api.stopJob(job.id)),
      showLog: (job) => {
        setSelected(job.id);
        setTab("jobs");
      },
    };
  }, [busy, track, refreshData, refreshJobs, report]);

  const sandbox = server.status === "ready" ? server.settings.sandbox : "";

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="h-[min(40rem,calc(100dvh-2rem))] sm:max-w-2xl" onCloseAutoFocus={returnFocusTo(opener)}>
        <DialogHeader>
          <div className="flex items-center justify-between gap-2">
            <DialogTitle className="text-lg">Set up</DialogTitle>
            <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close the setup">
              <X />
            </Button>
          </div>
          <DialogDescription>
            What the lab needs to run code in Docker, and Biomni&apos;s data lake. Building and fetching go on in the
            background.
          </DialogDescription>
        </DialogHeader>

        <Tabs
          value={tab}
          onValueChange={(value) => {
            if (isTab(value)) setTab(value);
          }}
          className="min-h-0 flex-1"
        >
          <TabsList aria-label="Parts of the setup">
            {TABS.map(({ value, label }) => (
              <TabsTrigger key={value} value={value}>
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value="overview" className="overflow-y-auto pr-1">
            <OverviewTab
              status={data.status}
              jobs={jobs.jobs ?? []}
              sandbox={sandbox}
              actions={actions}
              asking={data.asking}
              onCheck={data.refresh}
              onOpenLake={() => setTab("lake")}
              onAddKey={() => {
                onClose();
                // What has the focus is in this dialog, which is gone by the time the settings are closed
                settings.open("keys", opener);
              }}
            />
          </TabsContent>
          <TabsContent value="lake" className="overflow-y-auto pr-1">
            <LakeTab lake={data.lake} jobs={jobs.jobs ?? []} actions={actions} onRetry={data.refresh} />
          </TabsContent>
          <TabsContent value="jobs" className="overflow-y-auto pr-1">
            <JobsTab jobs={jobs.jobs} selected={selected} logs={logs} actions={actions} onSelect={setSelected} />
          </TabsContent>
        </Tabs>

        <DialogFooter className="border-t border-border pt-3">
          {problem && (
            <p role="alert" className="text-sm text-destructive sm:mr-auto">
              {problem}
            </p>
          )}
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
