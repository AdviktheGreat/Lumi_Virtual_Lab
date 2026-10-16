"use client";

import { useId, useState } from "react";
import { Play } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { describedBy, Field } from "@/components/settings-fields";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { checkStart, EMPTY_START, type StartDraft } from "@/lib/benchmarks";
import type { BenchmarkRun } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";

// Says how much answering may cost, which is always said, and starts it
export function StartForm({ run, working, jobs }: { run: BenchmarkRun; working: boolean; jobs: JobsData }) {
  const { report } = useServer();
  const id = useId();
  const [draft, setDraft] = useState<StartDraft>(EMPTY_START);
  const [tried, setTried] = useState(false);
  const attempt = useAttempt(report);
  const checked = checkStart(draft);
  const problems = tried ? checked.problems : {};
  const failures = (run.failed ?? 0) > 0;
  const left = run.questions - run.finished;
  const nothing = left <= 0 && !(draft.retryFailed && failures);

  async function start() {
    setTried(true);
    const options = checked.value;
    if (options === null) return;
    const job = await attempt.run(() => api.startBenchmarkRun(run.id, options));
    if (job) jobs.track(job);
  }

  return (
    <form
      aria-label="Answer the questions"
      onSubmit={(event) => {
        event.preventDefault();
        void start();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <p className="text-sm text-muted-foreground">
        Asks each question that has not been answered, and reads and scores the answer. The questions are answered by{" "}
        {run.model ?? "the model the run was made with"}, which costs what that model charges, so say the most it may spend. A run
        that stopped carries on from where it was.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id={`${id}-budget`} label="Most it may spend, in dollars" problem={problems.budget}>
          <Input
            id={`${id}-budget`}
            value={draft.budget}
            onChange={(event) => setDraft((was) => ({ ...was, budget: event.target.value }))}
            inputMode="decimal"
            autoComplete="off"
            aria-invalid={problems.budget !== undefined}
            aria-describedby={describedBy(`${id}-budget`, { problem: problems.budget !== undefined })}
          />
        </Field>
        <Field
          id={`${id}-question`}
          label="Most one question may spend"
          hint="Optional. A question that would spend more is left unanswered."
          problem={problems.perQuestion}
        >
          <Input
            id={`${id}-question`}
            value={draft.perQuestion}
            onChange={(event) => setDraft((was) => ({ ...was, perQuestion: event.target.value }))}
            inputMode="decimal"
            autoComplete="off"
            aria-invalid={problems.perQuestion !== undefined}
            aria-describedby={describedBy(`${id}-question`, { hint: true, problem: problems.perQuestion !== undefined })}
          />
        </Field>
      </div>
      {failures && (
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={draft.retryFailed}
            onChange={(event) => setDraft((was) => ({ ...was, retryFailed: event.target.checked }))}
          />
          Ask again the questions that failed
        </label>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={working || attempt.busy || nothing}>
          <Play />
          {attempt.busy ? "Starting…" : left === run.questions ? "Answer the questions" : "Carry on answering"}
        </Button>
        {nothing && <span className="text-xs text-muted-foreground">Every question has been answered.</span>}
      </div>
    </form>
  );
}
