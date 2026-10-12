"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { EMPTY_LOG, finishedSince, isActive, logEnd, mergeLog, withJob, type JobLog } from "./setup";
import type { Job } from "./types";

// Milliseconds between looks at the jobs while one is at work
export const JOBS_POLL_MS = 1000;

interface JobsState {
  // The jobs, the latest first, or null before the first look
  jobs: Job[] | null;
  // How many times a job that was at work has been found to have finished, which what a job changes is looked at again on
  finished: number;
}

function become(state: JobsState, jobs: Job[]): JobsState {
  const done = state.jobs !== null && finishedSince(state.jobs, jobs);

  return { jobs, finished: state.finished + (done ? 1 : 0) };
}

export interface JobsData extends JobsState {
  // Shows a job that has just been started, or has just been asked to stop, without waiting for the next look
  track: (job: Job) => void;
  // Looks at the jobs now
  refresh: () => Promise<void>;
}

// The jobs the server is running and has run. They are looked at when the page opens and as it is shown again, and
// every second while one is at work, which is how its progress is followed.
export function useJobs(report: (error: unknown) => void): JobsData {
  const [state, setState] = useState<JobsState>({ jobs: null, finished: 0 });
  // A look may be answered after a later one, or after a job was shown that the look began before, and must not replace
  // what is newer. Each is numbered as it is made, and an answer is shown only if no later one has been.
  const asked = useRef(0);
  const answered = useRef(0);

  const refresh = useCallback(async () => {
    const number = ++asked.current;
    try {
      const jobs = await api.jobs();
      if (number <= answered.current) return;
      answered.current = number;
      setState((current) => become(current, jobs));
    } catch (error) {
      report(error);
    }
  }, [report]);

  const track = useCallback((job: Job) => {
    answered.current = ++asked.current;
    setState((current) => become(current, withJob(current.jobs ?? [], job)));
  }, []);

  useEffect(() => {
    // The jobs are looked at when the page opens, which is when this runs
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    const show = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", show);

    return () => document.removeEventListener("visibilitychange", show);
  }, [refresh]);

  const working = state.jobs?.some(isActive) ?? false;
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, JOBS_POLL_MS);

    return () => clearInterval(timer);
  }, [working, refresh]);

  return { ...state, track, refresh };
}

// What the jobs have printed, of each that has been looked at. The lines of the job being looked at are asked for as it
// prints them, which the jobs say by how many it has printed.
export function useJobLogs(jobs: Job[] | null, watched: string | null): Record<string, JobLog> {
  const [logs, setLogs] = useState<Record<string, JobLog>>({});
  const total = jobs?.find((job) => job.id === watched)?.log_total ?? 0;
  const held = watched === null ? undefined : logs[watched];
  const from = logEnd(held ?? EMPTY_LOG);

  useEffect(() => {
    if (watched === null || total <= from) return;
    const abort = new AbortController();
    api.job(watched, from, abort.signal).then(
      (job) => {
        const chunk = job.log;
        if (chunk) setLogs((current) => ({ ...current, [watched]: mergeLog(current[watched] ?? EMPTY_LOG, chunk) }));
      },
      () => {
        // What is held is shown, and the lines are asked for again when the job has printed more
      },
    );

    return () => abort.abort();
  }, [watched, total, from]);

  return logs;
}
