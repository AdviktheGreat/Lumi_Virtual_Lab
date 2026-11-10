"use client";

import { useId, useState } from "react";
import { Play, Trash2 } from "lucide-react";
import { JobOutput } from "@/components/job-output";
import { ProblemNotice } from "@/components/messages";
import { Printed } from "@/components/printed";
import { useServer } from "@/components/server-provider";
import { Aside, describedBy, Field } from "@/components/settings-fields";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { count } from "@/lib/checks";
import { formatBytes } from "@/lib/files";
import { stripAnsi } from "@/lib/format";
import { describeDuration } from "@/lib/paperagent-environment";
import {
  checkReference,
  describeAgreement,
  describeCall,
  describeGiven,
  describeKept,
  describeOutcome,
  describePlan,
  describeResult,
  describeRun,
  emptyReference,
  FAILURE_ADVICE,
  STATUS_TITLES,
  type ReferenceDraft,
} from "@/lib/paperagent-reference";
import type { Job, PaperAgent, PaperAgentReference, ReferenceKept, TutorialDetail, TutorialSummary } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";

interface Shared {
  agent: PaperAgent;
  reference: PaperAgentReference;
  // Whether anything is being done to the agent, which what is done to its tutorials waits for
  busy: boolean;
}

// The tutorials that would be run, and those that would not, with why
function Plan({ reference }: { reference: PaperAgentReference }) {
  const id = useId();
  const plan = reference.plan;
  if (plan === null) return null;

  return (
    <section aria-labelledby={id} className="flex flex-col gap-2" data-testid="reference-plan">
      <h3 id={id} className="text-sm font-medium">
        What would be run
      </h3>
      <p className="text-sm" data-testid="reference-plan-summary">
        {describePlan(plan.runnable.length, plan.skipped.length, plan.more)}
      </p>
      {plan.runnable.length > 0 && (
        <ol aria-label="Tutorials that would be run" className="flex list-decimal flex-col gap-0.5 pl-5 text-sm">
          {plan.runnable.map((item) => (
            <li key={item.id} className="break-all">
              {item.path} <span className="text-muted-foreground">({item.kind === "notebook" ? "a notebook" : "a script"})</span>
            </li>
          ))}
        </ol>
      )}
      {plan.skipped.length > 0 && (
        <ul aria-label="Tutorials that cannot be run here" className="flex flex-col gap-0.5 text-xs text-muted-foreground">
          {plan.skipped.map((item) => (
            <li key={item.path} className="break-words">
              <span className="break-all">{item.path}</span>: {item.reason}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// Says the most time, how many tutorials, how many times each, and the most to write, and starts the run
function RunForm({
  agent,
  reference,
  busy,
  draft,
  onDraft,
  jobs,
  onStale,
}: Shared & { draft: ReferenceDraft; onDraft: (draft: ReferenceDraft) => void; jobs: JobsData; onStale: () => void }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [tried, setTried] = useState(false);
  const checked = checkReference(draft, reference);
  const problems = tried ? checked.problems : {};
  const { limits } = reference;
  const change = (part: Partial<ReferenceDraft>) => onDraft({ ...draft, ...part });

  async function run() {
    setTried(true);
    const options = checked.value;
    if (options === null) return;
    const job = await attempt.run(async () => {
      try {
        return await api.runPaperAgentReference(agent.id, options);
      } catch (error) {
        // Tutorials that were run have been kept before the page has looked again, which it does now
        if (error instanceof ApiError && (error.code === "done" || error.code === "image_missing")) {
          onStale();

          return undefined;
        }
        throw error;
      }
    });
    if (job) jobs.track(job);
  }

  const number = (key: "minutes" | "totalMinutes" | "tutorials" | "repeats" | "gigabytes", label: string, hint: string) => (
    <Field id={`${id}-${key}`} label={label} hint={hint} problem={problems[key]}>
      <Input
        id={`${id}-${key}`}
        value={draft[key]}
        onChange={(event) => change({ [key]: event.target.value })}
        inputMode="numeric"
        autoComplete="off"
        aria-invalid={problems[key] !== undefined}
        aria-describedby={describedBy(`${id}-${key}`, { hint: true, problem: problems[key] !== undefined })}
      />
    </Field>
  );

  return (
    <form
      aria-label="Run the tutorials"
      onSubmit={(event) => {
        event.preventDefault();
        void run();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {number("minutes", "Most time for one tutorial, in minutes", `One that takes longer is stopped. At most ${limits.max_minutes}.`)}
        {number(
          "totalMinutes",
          "Most time for all of them, in minutes",
          `What is left when this is used is not run. At most ${limits.max_total_minutes}.`,
        )}
        {number("tutorials", "How many tutorials to run", `The rest are listed as not run. At most ${limits.max_tutorials}.`)}
        {number(
          "repeats",
          "How many times to run each",
          `Run more than once, a tutorial is seen to give the same or not. At most ${limits.max_repeats}.`,
        )}
        {number(
          "gigabytes",
          "Most one run may write, in gigabytes",
          `Counting its copy of the project. It is looked at every few seconds. At most ${limits.max_gigabytes}.`,
        )}
      </div>
      {reference.data !== null && (
        <label className="flex items-start gap-2 text-sm">
          <Checkbox checked={draft.useData} onChange={(event) => change({ useData: event.target.checked })} className="mt-0.5" />
          <span>
            Give the runs the data that was fetched ({describeGiven(reference.data)}). It is there to read only, at /opt/paper/data, and
            PAPER_DATA says where.
          </span>
        </label>
      )}
      <p className="text-xs text-muted-foreground">
        The tutorials are the project&apos;s own code, so they are run in a container made from the environment&apos;s image that has none of
        this machine in it: no folder and no key, no network, a root that cannot be written to, {limits.memory.toUpperCase()}B of memory, at
        most {limits.cpus} processors, and at most {limits.pids.toLocaleString("en-US")} processes. Each is run in a copy of the project.
      </p>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={busy || attempt.busy || !reference.docker.ready || reference.environment.image_present === false}>
          <Play />
          {attempt.busy ? "Starting…" : busy ? "Running…" : "Run the tutorials"}
        </Button>
      </div>
    </form>
  );
}

// What one tutorial did, which is asked for when it is wanted to be seen, as it is long
function TutorialDetailView({ detail }: { detail: TutorialDetail }) {
  const id = useId();
  const failure = detail.failure;
  const skipped = detail.cells.flatMap((cell) => cell.skipped.map((line) => ({ cell: cell.index, line })));

  return (
    <div className="flex flex-col gap-3 rounded-md border border-border p-3" data-testid="reference-detail">
      {failure !== null && (
        <div className="flex flex-col gap-1.5" data-testid="reference-failure" data-kind={failure.kind}>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="destructive">{failure.title}</Badge>
          </div>
          <p className="break-words text-sm">{failure.detail}</p>
          <p className="break-words text-sm">{FAILURE_ADVICE[failure.kind]}</p>
          {failure.tail.length > 0 && <Printed label="The end of what it said" text={failure.tail.map(stripAnsi).join("\n")} />}
        </div>
      )}
      <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[10rem_minmax(0,1fr)]">
        {detail.python !== null && (
          <>
            <dt className="text-muted-foreground">Python</dt>
            <dd>{detail.python}</dd>
          </>
        )}
        <dt className="text-muted-foreground">Each run</dt>
        <dd>
          <ol aria-label="How each run ended" className="flex flex-col gap-0.5">
            {detail.runs.map((run, index) => (
              <li key={index}>
                Run {index + 1}: {STATUS_TITLES[run.status as keyof typeof STATUS_TITLES]?.toLowerCase() ?? run.status},{" "}
                {describeDuration(run.seconds)}
              </li>
            ))}
          </ol>
        </dd>
        {detail.packages.length > 0 && (
          <>
            <dt className="text-muted-foreground">Code it imported</dt>
            <dd className="break-words">{detail.packages.join(", ")}</dd>
          </>
        )}
      </dl>
      {detail.output.length > 0 && (
        <div className="flex flex-col gap-1">
          <h4 className="text-xs font-medium">The end of what it printed</h4>
          <Printed label="The end of what it printed" text={detail.output.map(stripAnsi).join("\n")} />
        </div>
      )}
      {skipped.length > 0 && (
        <div className="flex flex-col gap-1">
          <h4 className="text-xs font-medium">Lines of the notebook that are not Python, and were left out</h4>
          <ul aria-label="Lines that were left out" className="flex flex-col gap-0.5 font-mono text-xs text-muted-foreground">
            {skipped.slice(0, 20).map((item, index) => (
              <li key={index} className="break-all">
                cell {item.cell}: {item.line}
              </li>
            ))}
          </ul>
        </div>
      )}
      <section aria-labelledby={`${id}-calls`} className="flex flex-col gap-1">
        <h4 id={`${id}-calls`} className="text-xs font-medium">
          Calls to the project&apos;s own functions
        </h4>
        {detail.calls.length === 0 ? (
          <p className="text-xs text-muted-foreground">It made none, so there is nothing to make a tool from.</p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              {detail.calls_seen > detail.calls.length
                ? `${detail.calls_seen} were made, of which ${detail.calls.length} are kept: at most four of each function.`
                : `${count(detail.calls.length, "call")} made.`}
            </p>
            <ul aria-label="Calls that it made" className="flex max-h-72 flex-col gap-1.5 overflow-auto">
              {detail.calls.map((call) => (
                <li key={call.id} className="break-words text-xs" data-testid="reference-call">
                  <code className="font-mono">{describeCall(call)}</code>
                  <span className="text-muted-foreground"> gave </span>
                  <code className="font-mono">{describeResult(call)}</code>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
      {detail.files.length > 0 && (
        <section aria-labelledby={`${id}-files`} className="flex flex-col gap-1">
          <h4 id={`${id}-files`} className="text-xs font-medium">
            Files it wrote
          </h4>
          <ul aria-label="Files that it wrote" className="flex flex-col gap-0.5 text-xs">
            {detail.files.map((file) => (
              <li key={file.path} className="break-all">
                {file.path} <span className="text-muted-foreground">({formatBytes(file.bytes)}{file.new ? "" : ", it was there already"})</span>
              </li>
            ))}
          </ul>
          {detail.files_more > 0 && <p className="text-xs text-muted-foreground">{count(detail.files_more, "more file")} are not listed.</p>}
        </section>
      )}
    </div>
  );
}

// One tutorial of a run: how it ended, whether its runs agreed, and what it did, which is looked at when it is asked for
function Tutorial({ agent, summary, onStale }: { agent: PaperAgent; summary: TutorialSummary; onStale: () => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const id = useId();
  const [detail, setDetail] = useState<TutorialDetail | null>(null);

  async function toggle() {
    if (detail !== null) {
      setDetail(null);

      return;
    }
    const got = await attempt.run(async () => {
      try {
        return await api.paperAgentTutorial(agent.id, summary.id);
      } catch (error) {
        // What was kept of it is gone, as the run was taken away or made again, which the page looks at again
        if (error instanceof ApiError && error.status === 404) {
          onStale();

          return undefined;
        }
        throw error;
      }
    });
    if (got !== undefined) setDetail(got);
  }

  return (
    <li className="flex flex-col gap-1.5 rounded-lg border border-border p-3" data-testid="reference-tutorial" data-status={summary.status}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="break-all text-sm font-medium">{summary.path}</span>
        <Badge variant={summary.status === "ok" ? "secondary" : "destructive"}>{STATUS_TITLES[summary.status]}</Badge>
        {summary.failure !== null && <span className="text-xs text-muted-foreground">{summary.failure.title}</span>}
      </div>
      <p className="text-xs text-muted-foreground">
        {describeDuration(summary.seconds)}. <span data-testid="reference-agreement">{describeAgreement(summary)}.</span> {describeKept(summary)}.
      </p>
      <div>
        <Button
          type="button"
          variant="link"
          size="xs"
          className="h-auto p-0"
          onClick={() => void toggle()}
          aria-expanded={detail !== null}
          aria-controls={detail !== null ? id : undefined}
          disabled={attempt.busy}
        >
          {detail !== null ? "Hide what it did" : attempt.busy ? "Getting it…" : "Show what it did"}
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      {detail !== null && (
        <div id={id}>
          <TutorialDetailView detail={detail} />
        </div>
      )}
    </li>
  );
}

// Takes away what the tutorials gave, with the files kept, and the tools that were made from it, so that they can be run again
function ClearReference({
  agent,
  busy,
  onCleared,
}: {
  agent: PaperAgent;
  busy: boolean;
  onCleared: (reference: PaperAgentReference) => void;
}) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);

  async function clear() {
    setAsking(false);
    const next = await attempt.run(() => api.clearPaperAgentReference(agent.id));
    if (next) onCleared(next);
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button variant="outline" size="sm" onClick={() => setAsking(true)} disabled={busy || attempt.busy}>
          <Trash2 />
          Take what they gave away
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Take away what the tutorials of {agent.title} gave?</AlertDialogTitle>
            <AlertDialogDescription>
              This takes away what was kept of each tutorial, with the files they wrote, and the tools that were made from what they did.
              The environment stays, and the tutorials can be run again.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void clear()}>
              Take away
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// What was kept of a run of the tutorials: how each ended, and what it was and was not run with
function KeptRun({
  agent,
  reference,
  kept,
  busy,
  onCleared,
  onStale,
}: Shared & { kept: ReferenceKept; onCleared: (reference: PaperAgentReference) => void; onStale: () => void }) {
  const id = useId();

  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid="reference-kept">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={id} className="text-sm font-medium">
          What the tutorials gave
        </h3>
        <Badge variant={kept.complete ? "secondary" : "outline"}>{kept.complete ? "Run to the end of the list" : "Not run to the end"}</Badge>
      </div>
      <p className="text-xs text-muted-foreground" data-testid="reference-kept-when">
        {describeRun(kept)}. {describeOutcome(kept)}
      </p>
      <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[13rem_minmax(0,1fr)]">
        <dt className="text-muted-foreground">Given to read</dt>
        <dd>{describeGiven(kept.data)}</dd>
        <dt className="text-muted-foreground">Allowed</dt>
        <dd>
          {kept.limits.minutes} minutes for one and {kept.limits.total_minutes} for all, {count(kept.limits.repeats, "run")} of each, and{" "}
          {kept.limits.gigabytes} GB written
        </dd>
      </dl>
      {kept.tutorials.length > 0 && (
        <ul aria-label="The tutorials that were run" className="flex flex-col gap-2">
          {kept.tutorials.map((summary) => (
            <Tutorial key={summary.id} agent={agent} summary={summary} onStale={onStale} />
          ))}
        </ul>
      )}
      {kept.not_run.length > 0 && (
        <ul aria-label="Tutorials that were not run" className="flex flex-col gap-0.5 text-xs text-muted-foreground" data-testid="reference-not-run">
          {kept.not_run.map((item) => (
            <li key={item.path} className="break-words">
              <span className="break-all">{item.path}</span> was not run: {item.reason}
            </li>
          ))}
        </ul>
      )}
      {kept.skipped.length > 0 && (
        <ul aria-label="Tutorials that cannot be run here" className="flex flex-col gap-0.5 text-xs text-muted-foreground">
          {kept.skipped.map((item) => (
            <li key={item.path} className="break-words">
              <span className="break-all">{item.path}</span>: {item.reason}
            </li>
          ))}
        </ul>
      )}
      {!kept.complete && (
        <Aside>This run did not come to its end, because it was stopped or failed. What it had done is kept, and the next run replaces it.</Aside>
      )}
      <p className="text-xs text-muted-foreground">{reference.meaning}</p>
      <ClearReference agent={agent} busy={busy} onCleared={onCleared} />
    </section>
  );
}

// The tutorials of an agent's code, run in its environment so that what they gave is kept: which would be run, running them in a
// container that has none of this machine in it, and what each did
export function ReferenceSection({
  agent,
  reference,
  busy,
  running,
  settling,
  jobs,
  onCleared,
  onStale,
}: Shared & {
  // The run that is at work, if there is one
  running: Job | undefined;
  // Whether a run has just ended well, and what the page shows of it is from before it did
  settling: boolean;
  jobs: JobsData;
  onCleared: (reference: PaperAgentReference) => void;
  // Looks at the agent and its tutorials again, as is done when the server says what the page shows is out of date
  onStale: () => void;
}) {
  const [draft, setDraft] = useState<ReferenceDraft>(() => emptyReference(reference.limits));
  const { kept, plan } = reference;

  if (reference.commit === null) {
    return <p className="text-sm text-muted-foreground">Fetch the code first. The tutorials are in it.</p>;
  }
  if (!reference.environment.built) {
    return <p className="text-sm text-muted-foreground">Build the environment first. The tutorials are run in it.</p>;
  }
  if (settling) return <p className="text-sm text-muted-foreground">Looking at what the tutorials gave…</p>;
  const finished = kept !== null && kept.complete;

  return (
    <div className="flex flex-col gap-4">
      {!reference.docker.ready && (
        <Aside tone="warning">
          {reference.docker.message ?? "Docker is not running."} Running the tutorials takes it. They cannot be run until it is.
        </Aside>
      )}
      {reference.environment.image_present === false && (
        <Aside tone="warning">
          Docker no longer has the image of the environment, so the tutorials cannot be run. Take the environment away, and build it again.
        </Aside>
      )}
      {running !== undefined && <JobOutput key={running.id} job={running} jobs={jobs} />}
      {/* What is kept while a run goes on is the account of a run that has begun, which is not one that did not come to its end */}
      {kept !== null && running === undefined && (
        <KeptRun agent={agent} reference={reference} kept={kept} busy={busy} onCleared={onCleared} onStale={onStale} />
      )}
      {!finished && plan !== null && plan.runnable.length === 0 && (
        <section className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="reference-none">
          <h3 className="text-sm font-medium">There is nothing to run</h3>
          <p className="text-sm">No tutorial in the code can be run here: only Python is run.</p>
          <Plan reference={reference} />
        </section>
      )}
      {!finished && plan !== null && plan.runnable.length > 0 && (
        <>
          <Plan reference={reference} />
          <RunForm
            agent={agent}
            reference={reference}
            busy={busy || running !== undefined}
            draft={draft}
            onDraft={setDraft}
            jobs={jobs}
            onStale={onStale}
          />
        </>
      )}
    </div>
  );
}
