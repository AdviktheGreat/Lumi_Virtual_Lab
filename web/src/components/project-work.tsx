"use client";

import { useId, useState } from "react";
import { Play } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { describedBy, Field } from "@/components/settings-fields";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { formatCost } from "@/lib/format";
import { checkStart, projectStateNote, startDraftFor, type StartDraft } from "@/lib/projects";
import type { Project, ProjectsList } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";

// Says how much working on a project may cost, which is always said, and starts it, or carries it on from where it stopped
export function StartForm({
  project,
  limits,
  working,
  jobs,
}: {
  project: Project;
  limits: ProjectsList["limits"];
  working: boolean;
  jobs: JobsData;
}) {
  const { report } = useServer();
  const id = useId();
  const [draft, setDraft] = useState<StartDraft>(() => startDraftFor(project));
  const [tried, setTried] = useState(false);
  const attempt = useAttempt(report);
  const checked = checkStart(draft, limits, project.spent);
  const problems = tried ? checked.problems : {};
  const fresh = project.state === "new";

  async function start() {
    setTried(true);
    const options = checked.value;
    if (options === null) return;
    const job = await attempt.run(() => api.startProject(project.id, options));
    if (job) jobs.track(job);
  }

  if (project.state === "finished" && !working) {
    return <p className="text-sm text-muted-foreground">{projectStateNote(project.state)} There is nothing left to do.</p>;
  }

  return (
    <form
      aria-label="Work on the project"
      onSubmit={(event) => {
        event.preventDefault();
        void start();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <p className="text-sm text-muted-foreground">
        The lead plans the work, and decides each round whether to hold a meeting, have code written and run, change the team, or
        put an answer to the critic. This costs what {project.model ?? "the model the project was made with"} charges, so say the most
        it may spend. {fresh ? "" : `${projectStateNote(project.state)} `}
        {project.spent > 0 && `It has spent ${formatCost(project.spent)} so far.`}
      </p>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field
          id={`${id}-budget`}
          label="Most it may spend, in dollars"
          hint={project.spent > 0 ? "Over all the times it is worked on." : undefined}
          problem={problems.budget}
        >
          <Input
            id={`${id}-budget`}
            value={draft.budget}
            onChange={(event) => setDraft((was) => ({ ...was, budget: event.target.value }))}
            inputMode="decimal"
            autoComplete="off"
            aria-invalid={problems.budget !== undefined}
            aria-describedby={describedBy(`${id}-budget`, { hint: project.spent > 0, problem: problems.budget !== undefined })}
          />
        </Field>
        <Field
          id={`${id}-rounds`}
          label={limits.max_rounds.label}
          hint={`Blank is ${limits.max_rounds.default}. Up to ${limits.max_rounds.most}.`}
          problem={problems.rounds}
        >
          <Input
            id={`${id}-rounds`}
            value={draft.rounds}
            onChange={(event) => setDraft((was) => ({ ...was, rounds: event.target.value }))}
            inputMode="numeric"
            autoComplete="off"
            aria-invalid={problems.rounds !== undefined}
            aria-describedby={describedBy(`${id}-rounds`, { hint: true, problem: problems.rounds !== undefined })}
          />
        </Field>
        <Field
          id={`${id}-stalled`}
          label={limits.max_stalled_rounds.label}
          hint={`Blank is ${limits.max_stalled_rounds.default}. Up to ${limits.max_stalled_rounds.most}.`}
          problem={problems.stalled}
        >
          <Input
            id={`${id}-stalled`}
            value={draft.stalled}
            onChange={(event) => setDraft((was) => ({ ...was, stalled: event.target.value }))}
            inputMode="numeric"
            autoComplete="off"
            aria-invalid={problems.stalled !== undefined}
            aria-describedby={describedBy(`${id}-stalled`, { hint: true, problem: problems.stalled !== undefined })}
          />
        </Field>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={working || attempt.busy}>
          <Play />
          {attempt.busy ? "Starting…" : working ? "Working…" : fresh ? "Start the project" : "Carry on"}
        </Button>
      </div>
    </form>
  );
}
