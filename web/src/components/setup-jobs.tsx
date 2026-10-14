"use client";

import { Section } from "@/components/settings-fields";
import { JobProgress, StopButton, type SetupActions } from "@/components/setup-job";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { stripAnsi } from "@/lib/format";
import { EMPTY_LOG, isActive, logEnd, startedText, stateLabel, type JobLog } from "@/lib/setup";
import type { Job } from "@/lib/types";
import { useStickToBottom } from "@/lib/use-stick-to-bottom";

function Log({ job, log }: { job: Job; log: JobLog }) {
  const { scroller, onScroll } = useStickToBottom<HTMLDivElement>(logEnd(log));

  return (
    <div id={logId(job)} className="flex flex-col gap-1">
      {log.start > 0 && (
        <p className="text-xs text-muted-foreground">The first {log.start} lines are not kept, the server keeps the last ones.</p>
      )}
      {log.lines.length === 0 ? (
        <p role="status" className="text-xs text-muted-foreground">
          {job.log_total === 0 ? "It has not printed anything." : "Getting what it printed…"}
        </p>
      ) : (
        <div
          ref={scroller}
          onScroll={onScroll}
          role="log"
          aria-live="off"
          aria-label={`What this printed: ${job.title}`}
          tabIndex={0}
          className="max-h-64 overflow-auto rounded-md bg-muted/60 p-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <pre className="whitespace-pre-wrap break-words font-mono text-xs">{log.lines.map(stripAnsi).join("\n")}</pre>
        </div>
      )}
    </div>
  );
}

const logId = (job: Job) => `setup-log-${job.id}`;

function JobCard({
  job,
  open,
  log,
  actions,
  onToggle,
}: {
  job: Job;
  open: boolean;
  log: JobLog;
  actions: SetupActions;
  onToggle: () => void;
}) {
  const active = isActive(job);

  return (
    <li aria-label={job.title} className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium">{job.title}</h3>
            <Badge variant={job.state === "failed" ? "destructive" : active ? "secondary" : "outline"}>{stateLabel(job.state)}</Badge>
          </div>
          <p className="text-xs text-muted-foreground">{startedText(job.created_at)}</p>
        </div>
        {active && <StopButton job={job} actions={actions} />}
      </div>
      {active || job.state !== "failed" ? (
        <JobProgress job={job} />
      ) : (
        <p role="alert" className="break-words text-xs text-destructive">
          {job.error}
        </p>
      )}
      <Button
        variant="link"
        size="xs"
        className="h-auto self-start p-0"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={open ? logId(job) : undefined}
      >
        {open ? "Hide what it printed" : "Show what it printed"}
      </Button>
      {open && <Log job={job} log={log} />}
    </li>
  );
}

// What the server has been doing in the background, the latest first, and what each has printed
export function JobsTab({
  jobs,
  selected,
  logs,
  actions,
  onSelect,
}: {
  jobs: readonly Job[] | null;
  // The job whose output is shown
  selected: string | null;
  logs: Record<string, JobLog>;
  actions: SetupActions;
  onSelect: (id: string | null) => void;
}) {
  return (
    <Section>
      {jobs === null && (
        <div className="flex flex-col gap-2" role="status" aria-busy="true" aria-label="Looking at the jobs">
          {[0, 1].map((row) => (
            <Skeleton key={row} className="h-20 w-full" />
          ))}
        </div>
      )}
      {jobs !== null && jobs.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Nothing has been built or fetched since the server started. What is, is listed here, with what it prints.
        </p>
      )}
      {jobs !== null && jobs.length > 0 && (
        <ul aria-label="Jobs" className="flex flex-col gap-2.5">
          {jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              open={selected === job.id}
              log={logs[job.id] ?? EMPTY_LOG}
              actions={actions}
              onToggle={() => onSelect(selected === job.id ? null : job.id)}
            />
          ))}
        </ul>
      )}
    </Section>
  );
}
