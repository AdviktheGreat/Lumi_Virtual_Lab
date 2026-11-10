"use client";

import { Log } from "@/components/setup-jobs";
import { EMPTY_LOG, type JobLog } from "@/lib/setup";
import type { Job } from "@/lib/types";
import { useJobLogs, type JobsData } from "@/lib/use-jobs";

// What a job that is at work prints, as it goes
export function JobOutput({ job, jobs }: { job: Job; jobs: JobsData }) {
  const logs = useJobLogs(jobs.jobs, job.id);
  const log: JobLog = logs[job.id] ?? EMPTY_LOG;
  const current = jobs.jobs?.find((item) => item.id === job.id) ?? job;

  return <Log job={current} log={log} />;
}
