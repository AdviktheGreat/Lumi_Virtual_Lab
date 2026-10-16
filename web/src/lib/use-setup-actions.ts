"use client";

import { useMemo, useState } from "react";
import { api } from "./api";
import { describeError } from "./errors";
import type { Job } from "./types";
import type { JobsData } from "./use-jobs";

// What can be asked of the jobs: each starts something on the server, or asks it to stop, and none can be asked while
// another is being asked
export interface JobActions {
  busy: boolean;
  build: (stage: string) => void;
  fetch: (names?: string[]) => void;
  stop: (job: Job) => void;
}

// What the setup can ask, which includes showing what a job printed, since that is read in the setup
export interface SetupActions extends JobActions {
  showLog: (job: Job) => void;
}

export interface JobActionsState {
  actions: JobActions;
  // Why the latest of them was refused, until another is asked
  problem: string | null;
}

// What can be asked of the jobs, for a page that shows them and what they change
export function useJobActions({
  jobs,
  refreshData,
  report,
}: {
  jobs: JobsData;
  // Looks again at what a job changes, as is done once one is started or refused
  refreshData: () => void;
  report: (error: unknown) => void;
}): JobActionsState {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const { track, refresh: refreshJobs } = jobs;

  const actions = useMemo<JobActions>(() => {
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
    };
  }, [busy, track, refreshData, refreshJobs, report]);

  return { actions, problem };
}
