"use client";

import { Square } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { isActive, jobCounts, jobFraction } from "@/lib/setup";
import type { Job } from "@/lib/types";
import type { JobActions } from "@/lib/use-setup-actions";

// How far a job at work has got, and what it is doing
export function JobProgress({ job }: { job: Job }) {
  const counts = jobCounts(job);

  return (
    <div className="flex min-w-0 flex-col gap-1">
      {isActive(job) && <Progress value={jobFraction(job)} aria-label={`Progress: ${job.title}`} />}
      {job.message && <p className="break-words text-xs text-muted-foreground">{job.message}</p>}
      {counts && <p className="text-xs text-muted-foreground">{counts}</p>}
    </div>
  );
}

// Asks a job at work to stop, which it does in a moment, and is said to be doing until it has
export function StopButton({ job, actions }: { job: Job; actions: JobActions }) {
  const stopping = job.state === "stopping";

  return (
    <Button
      variant="outline"
      size="xs"
      onClick={() => actions.stop(job)}
      disabled={stopping || actions.busy}
      aria-label={`${stopping ? "Stopping" : "Stop"}: ${job.title}`}
    >
      <Square />
      {stopping ? "Stopping…" : "Stop"}
    </Button>
  );
}
