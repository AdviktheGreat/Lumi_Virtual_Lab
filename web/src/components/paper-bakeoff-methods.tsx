"use client";

import { useId, useState } from "react";
import { Hammer, Plus } from "lucide-react";
import { Notice, ProblemNotice } from "@/components/messages";
import { BakeoffMethodCard } from "@/components/paper-bakeoff-method";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { describedBy, Field } from "@/components/settings-fields";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { WorkStatus } from "@/components/work-status";
import { api } from "@/lib/api";
import { buildableCount, checkMethod, describeBuildAll, EMPTY_METHOD, lastBakeoffJob, type MethodDraft } from "@/lib/bakeoff-methods";
import { bakeoffJob, describeLeft } from "@/lib/bakeoffs";
import type { Bakeoff, BakeoffBuildBody } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";

// What is being done to the methods and how it ended the last time, with the way to stop it
export function MethodsWork({ bakeoff }: { bakeoff: Bakeoff }) {
  const jobs = useSetupJobs();

  return (
    <WorkStatus
      job={bakeoffJob(jobs.jobs, bakeoff.id)}
      last={lastBakeoffJob(jobs.jobs, bakeoff.id)}
      jobs={jobs}
      label="What is being done to the methods"
    />
  );
}

// The methods that are in the running, each with where it stands, and the way to build them. Building a method makes the PaperAgent of
// its paper, reads the paper, fetches its code, looks at it, and builds what runs it. Reading is the only part that spends money.
export function MethodList({ bakeoff, onChanged, reload }: { bakeoff: Bakeoff; onChanged: (next: Bakeoff) => void; reload: () => void }) {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const attempt = useAttempt(report);
  const working = attempt.busy || bakeoff.job !== null || bakeoffJob(jobs.jobs, bakeoff.id) !== undefined;
  const buildable = buildableCount(bakeoff.candidates);

  async function build(body: BakeoffBuildBody) {
    const job = await attempt.run(() => api.buildBakeoff(bakeoff.id, body));
    if (job) jobs.track(job);
  }

  if (bakeoff.candidates.length === 0) {
    return (
      <div className="flex flex-col gap-1 rounded-xl border border-dashed border-border p-5" data-testid="bakeoff-methods-empty">
        <p className="text-sm font-medium">There are no methods in the running yet</p>
        <p className="text-sm text-muted-foreground">Find them in the literature, or add one by its paper, below.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Building a method makes a PaperAgent of its paper if it has none, reads the paper, fetches the code you said is its code, and looks at it
        before anything is built, so that code that is no use is found before the paper is paid for. Then its environment is built, its tutorials
        are run, and tools are made of what they did. A method is built from the code that is named here, and nothing that a search or a paper
        points to is its code until you say so. {describeLeft(bakeoff)}
      </p>
      <ul aria-label="Methods" className="flex flex-col gap-3">
        {bakeoff.candidates.map((method) => (
          <BakeoffMethodCard
            key={method.id}
            bakeoff={bakeoff}
            method={method}
            working={working}
            onBuild={(body) => void build(body)}
            onChanged={onChanged}
            reload={reload}
          />
        ))}
      </ul>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => void build({})} disabled={working || buildable === 0}>
          <Hammer />
          {attempt.busy ? "Starting…" : describeBuildAll(buildable, bakeoff.candidates.length)}
        </Button>
        {bakeoff.job !== null && <span className="text-xs text-muted-foreground">Something is being done to the methods. Stop it, or wait, to build.</span>}
      </div>
    </div>
  );
}

// Puts a method in the running by its paper, with a name and where its code is if the person says. The methods that a search finds are
// only a start, and a method it left out is added here.
export function AddMethod({ bakeoff, onChanged }: { bakeoff: Bakeoff; onChanged: (next: Bakeoff) => void }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [draft, setDraft] = useState<MethodDraft>(EMPTY_METHOD);
  const [tried, setTried] = useState(false);
  const checked = checkMethod(draft, bakeoff.limits);
  const problems = tried ? checked.problems : {};
  const full = bakeoff.candidates.length >= bakeoff.limits.max_candidates;
  const busy = attempt.busy || bakeoff.job !== null;
  const set = (part: keyof MethodDraft, value: string) => setDraft((was) => ({ ...was, [part]: value }));

  async function add() {
    setTried(true);
    const body = checked.value;
    if (body === null) return;
    const next = await attempt.run(() => api.addBakeoffMethod(bakeoff.id, body));
    if (next) {
      onChanged(next);
      setDraft(EMPTY_METHOD);
      setTried(false);
    }
  }

  return (
    <form
      aria-label="Add a method"
      onSubmit={(event) => {
        event.preventDefault();
        void add();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <Field
        id={`${id}-paper`}
        label="Its paper"
        hint="Its DOI, such as 10.1038/s41586-020-2649-2, or a link to it. Nothing is fetched until you build it."
        problem={problems.paper}
      >
        <Input
          id={`${id}-paper`}
          value={draft.paper}
          onChange={(event) => set("paper", event.target.value)}
          autoComplete="off"
          spellCheck={false}
          readOnly={busy}
          aria-invalid={problems.paper !== undefined}
          aria-describedby={describedBy(`${id}-paper`, { hint: true, problem: problems.paper !== undefined })}
        />
      </Field>
      <Field id={`${id}-name`} label="What it is called" hint="Optional. If it is left blank, its DOI, or where its link leads, is used." problem={problems.name}>
        <Input
          id={`${id}-name`}
          value={draft.name}
          onChange={(event) => set("name", event.target.value)}
          maxLength={bakeoff.limits.max_name_chars * 4}
          autoComplete="off"
          readOnly={busy}
          aria-invalid={problems.name !== undefined}
          aria-describedby={describedBy(`${id}-name`, { hint: true, problem: problems.name !== undefined })}
        />
      </Field>
      <Field
        id={`${id}-repo`}
        label="Where its code is"
        hint="Optional, the address of the project, such as https://github.com/owner/name. If you do not say, you are asked when it is built."
        problem={problems.repo}
      >
        <Input
          id={`${id}-repo`}
          value={draft.repo}
          onChange={(event) => set("repo", event.target.value)}
          autoComplete="off"
          spellCheck={false}
          readOnly={busy}
          aria-invalid={problems.repo !== undefined}
          aria-describedby={describedBy(`${id}-repo`, { hint: true, problem: problems.repo !== undefined })}
        />
      </Field>
      {full && (
        <Notice tone="muted">
          There are {bakeoff.limits.max_candidates} methods in the running, which is as many as there can be. Remove some to add more.
        </Notice>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={busy || full}>
          <Plus />
          {attempt.busy ? "Adding…" : "Add the method"}
        </Button>
      </div>
    </form>
  );
}
