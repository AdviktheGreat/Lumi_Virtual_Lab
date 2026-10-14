"use client";

import { Square } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { isActive, jobCounts, jobFraction } from "@/lib/setup";
import type { Job } from "@/lib/types";

// What the setup can be asked to do: each starts something on the server, or asks it to stop, and none can be asked
// while another is being asked
export interface SetupActions {
  busy: boolean;
  build: (stage: string) => void;
  fetch: (names?: string[]) => void;
  stop: (job: Job) => void;
  // Shows what a job printed
  showLog: (job: Job) => void;
}

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
export function StopButton({ job, actions }: { job: Job; actions: SetupActions }) {
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
