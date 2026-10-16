"use client";

import { ProblemNotice } from "@/components/messages";
import { JobProgress, StopButton } from "@/components/setup-job";
import { useServer } from "@/components/server-provider";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { startedText, stateLabel } from "@/lib/setup";
import type { Job } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";

// What is being done to a run, how far it has got, and the way to stop it; and, when nothing is, how the last of it ended
export function WorkStatus({ job, last, jobs }: { job: Job | undefined; last: Job | undefined; jobs: JobsData }) {
  const { report } = useServer();
  const attempt = useAttempt(report);

  async function stop(target: Job) {
    const stopping = await attempt.run(() => api.stopJob(target.id));
    if (stopping) jobs.track(stopping);
  }

  const shown = job ?? last;
  if (shown === undefined) return null;

  return (
    <section aria-label="What is being done" className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium">{shown.title}</h3>
            <Badge variant={shown.state === "failed" ? "destructive" : job ? "secondary" : "outline"}>{stateLabel(shown.state)}</Badge>
          </div>
          <p className="text-xs text-muted-foreground">{startedText(shown.created_at)}</p>
        </div>
        {job && <StopButton job={job} actions={{ busy: attempt.busy, stop: (target) => void stop(target) }} />}
      </div>
      {job || shown.state !== "failed" ? (
        <JobProgress job={shown} />
      ) : (
        <p role="alert" className="break-words text-xs text-destructive">
          {shown.error}
        </p>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
    </section>
  );
}
