"use client";

import { useId, useState } from "react";
import { Activity, Check, GitCommitHorizontal, X } from "lucide-react";
import { JobOutput } from "@/components/job-output";
import { ProblemNotice } from "@/components/messages";
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
import { timeAgo } from "@/lib/format";
import {
  CHANGE_TITLES,
  checkWatch,
  describeAffects,
  describeDependencies,
  describeFile,
  describeImage,
  describeLooked,
  describeNotLooked,
  describeTool,
  describeUpdate,
  describeWatch,
  lineKind,
  shortCommit,
  SOURCE_TITLES,
  STATUS_TITLES,
  statusVariant,
  toolHeld,
} from "@/lib/paperagent-living";
import type { HealthRecord, HealthStatus, Job, PaperAgent, PaperAgentHealth, ProposedUpdate, UpdateFile } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";
import { cn } from "@/lib/utils";

function StatusBadge({ status }: { status: HealthStatus }) {
  return (
    <Badge variant={statusVariant(status)} data-testid="living-status" data-status={status}>
      {STATUS_TITLES[status]}
    </Badge>
  );
}

// What the last look found: the word, why, and each of the four things that were looked at
function Found({ found }: { found: HealthRecord }) {
  const earlier = found.history.slice(0, -1);

  return (
    <section aria-label="What the last look found" className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid="living-found">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={found.status} />
        <span className="text-xs text-muted-foreground">{describeLooked(found)}</span>
      </div>
      {found.reasons.length > 0 && (
        <ul aria-label="Why" className="flex list-disc flex-col gap-1 pl-5 text-sm" data-testid="living-reasons">
          {found.reasons.map((reason) => (
            <li key={reason} className="break-words">
              {reason}
            </li>
          ))}
        </ul>
      )}
      <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
        <dt className="text-muted-foreground">Where the code is</dt>
        <dd className="min-w-0 break-words" data-testid="living-source" data-state={found.source.state}>
          <span className="font-medium">{SOURCE_TITLES[found.source.state]}.</span> {found.source.message}
          {found.source.update_error !== null && (
            <span className="block text-xs text-muted-foreground">The newer version was not fetched: {found.source.update_error}</span>
          )}
        </dd>
        <dt className="text-muted-foreground">The environment</dt>
        <dd className="min-w-0 break-words" data-testid="living-image">
          {describeImage(found.image.present)}
        </dd>
        <dt className="text-muted-foreground">Pinned versions</dt>
        <dd className="min-w-0 break-words" data-testid="living-pins">
          {describeDependencies(found)}
          {found.dependencies !== null && found.dependencies.problems.length > 0 && (
            <ul aria-label="Pinned versions that cannot be had" className="mt-1 flex flex-col gap-0.5 text-xs">
              {found.dependencies.problems.map((pin) => (
                <li key={`${pin.name}==${pin.version}`}>
                  <code className="font-mono">
                    {pin.name}=={pin.version}
                  </code>{" "}
                  ({pin.state})
                </li>
              ))}
            </ul>
          )}
        </dd>
        <dt className="text-muted-foreground">The tools, run again</dt>
        <dd className="min-w-0 break-words">
          {found.tools_message !== null && <p data-testid="living-tools-message">{found.tools_message}</p>}
          {found.tools.length > 0 && (
            <ul aria-label="The tools, run again" className="flex flex-col gap-1">
              {found.tools.map((tool) => {
                const held = toolHeld(tool);

                return (
                  <li key={tool.name} className="flex flex-wrap items-baseline gap-x-2" data-testid="living-tool" data-name={tool.name} data-held={held}>
                    {held === "matched" ? (
                      <Check className="size-3.5 shrink-0 self-center text-primary" aria-hidden />
                    ) : held === "differs" ? (
                      <X className="size-3.5 shrink-0 self-center text-destructive" aria-hidden />
                    ) : (
                      <span className="size-3.5 shrink-0" aria-hidden />
                    )}
                    <code className="font-mono text-xs font-medium">{tool.name}</code>
                    <span className="min-w-0 text-xs text-muted-foreground">{describeTool(tool)}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </dd>
      </dl>
      {earlier.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <span>Earlier looks, the latest last:</span>
          <ol aria-label="Earlier looks" className="flex flex-wrap gap-1" data-testid="living-history">
            {earlier.map((look) => (
              <li key={look.at}>
                <Badge variant={statusVariant(look.status)} title={new Date(look.at).toLocaleString("en")}>
                  {STATUS_TITLES[look.status]}
                  <span className="sr-only">, {timeAgo(look.at) || "a while ago"}</span>
                </Badge>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

// Starts a look at the agent, which changes nothing that is kept
function LookNow({ agent, busy, jobs, onStale }: { agent: PaperAgent; busy: boolean; jobs: JobsData; onStale: () => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const hint = useId();

  async function look() {
    const job = await attempt.run(async () => {
      try {
        return await api.lookAtPaperAgent(agent.id);
      } catch (error) {
        // Its tools are not what the page showed, which it looks at again
        if (error instanceof ApiError && error.code === "no_tools") onStale();
        throw error;
      }
    });
    if (job) jobs.track(job);
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Button type="button" onClick={() => void look()} disabled={busy || attempt.busy} aria-describedby={hint}>
          <Activity />
          {attempt.busy ? "Starting…" : "Look at it now"}
        </Button>
        <span id={hint} className="text-xs text-muted-foreground">
          Asks where its code is now and of the versions it pins, and runs its tools again in the environment that is kept. Nothing that is kept is
          changed.
        </span>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
    </div>
  );
}

// The schedule it is looked at on, which is the person's
function Watch({ agent, health, onChanged }: { agent: PaperAgent; health: PaperAgentHealth; onChanged: (health: PaperAgentHealth) => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const id = useId();
  const [typed, setTyped] = useState(String(health.watch?.every_hours ?? 24));
  const [tried, setTried] = useState(false);
  const checked = checkWatch(typed, health.limits);
  const problem = tried ? checked.problem : undefined;

  async function watch() {
    setTried(true);
    const hours = checked.value;
    if (hours === null) return;
    const next = await attempt.run(() => api.watchPaperAgent(agent.id, hours));
    if (next) {
      setTried(false);
      onChanged(next);
    }
  }

  async function stop() {
    const next = await attempt.run(() => api.stopWatchingPaperAgent(agent.id));
    if (next) onChanged(next);
  }

  return (
    <form
      aria-label="Look at it on a schedule"
      onSubmit={(event) => {
        event.preventDefault();
        void watch();
      }}
      className="flex flex-col gap-3 rounded-lg border border-border p-3"
    >
      <p className="text-sm" data-testid="living-watch" data-hours={health.watch?.every_hours ?? ""}>
        {describeWatch(health.watch)}
      </p>
      <Field
        id={`${id}-hours`}
        label="How often, in hours"
        hint={`From ${health.limits.min_hours} to ${health.limits.max_hours}, which is ${health.limits.max_hours / 24} days. Nothing is looked at while the server is not running, and an hour that is missed is not made up for.`}
        problem={problem}
      >
        <Input
          id={`${id}-hours`}
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          inputMode="numeric"
          autoComplete="off"
          className="sm:max-w-32"
          aria-invalid={problem !== undefined}
          aria-describedby={describedBy(`${id}-hours`, { hint: true, problem: problem !== undefined })}
        />
      </Field>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="outline" size="sm" disabled={attempt.busy}>
          {health.watch === null ? "Look at it on this schedule" : "Change the schedule"}
        </Button>
        {health.watch !== null && (
          <Button type="button" variant="ghost" size="sm" onClick={() => void stop()} disabled={attempt.busy}>
            Stop looking at it on a schedule
          </Button>
        )}
      </div>
    </form>
  );
}

// One file of the newer version that differs, which opens its diff where there is one
function ChangedFile({ file }: { file: UpdateFile }) {
  const head = (
    <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
      <Badge variant={file.change === "removed" ? "destructive" : file.change === "added" ? "default" : "outline"}>{CHANGE_TITLES[file.change]}</Badge>
      <code className="break-all font-mono text-xs font-medium">{file.path}</code>
      <span className="text-xs text-muted-foreground">{describeFile(file)}</span>
    </span>
  );

  return (
    <li className="min-w-0 rounded-md border border-border p-2" data-testid="update-file" data-path={file.path} data-change={file.change}>
      {file.diff === null ? (
        head
      ) : (
        <details>
          <summary className="cursor-pointer select-none">{head}</summary>
          <pre className="mt-2 max-h-96 overflow-auto rounded-md bg-muted/50 p-2 font-mono text-[11px] leading-5" data-testid="update-diff">
            {file.diff.split("\n").map((line, index) => {
              const kind = lineKind(line);

              return (
                <span
                  key={index}
                  className={cn(
                    "block whitespace-pre",
                    kind === "added" && "bg-primary/10 text-foreground",
                    kind === "removed" && "bg-destructive/10 text-foreground",
                    (kind === "meta" || kind === "hunk") && "text-muted-foreground",
                  )}
                >
                  {line || " "}
                </span>
              );
            })}
          </pre>
        </details>
      )}
    </li>
  );
}

// The newer version of the code that is proposed: what it changes, which is read before it can be taken, and taking it, for the commit
// that was read, or putting it aside
function Update({
  agent,
  health,
  busy,
  jobs,
  onApplied,
  onStale,
  onRefused,
}: {
  agent: PaperAgent;
  health: PaperAgentHealth & { update: NonNullable<PaperAgentHealth["update"]> };
  busy: boolean;
  jobs: JobsData;
  onApplied: () => void;
  onStale: () => void;
  // Said by the section, as a proposal that replaced the one read is shown anew and would lose it
  onRefused: (code: Refusal | null) => void;
}) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [shown, setShown] = useState<ProposedUpdate | null>(null);
  const [read, setRead] = useState(false);
  const [asking, setAsking] = useState(false);
  const summary = health.update;

  async function show() {
    if (shown !== null) {
      setShown(null);
      setRead(false);

      return;
    }
    const got = await attempt.run(() => api.paperAgentUpdate(agent.id));
    if (got === undefined) return;
    onRefused(null);
    if (got.update === null) {
      onStale();

      return;
    }
    setShown(got.update);
  }

  async function take(commit: string) {
    setAsking(false);
    onRefused(null);
    const job = await attempt.run(async () => {
      try {
        return await api.applyPaperAgentUpdate(agent.id, commit);
      } catch (error) {
        // What was read is not what is proposed now, so it is read again
        if (error instanceof ApiError && (error.code === "changed" || error.code === "no_update")) {
          setShown(null);
          setRead(false);
          onRefused(error.code);
          onStale();

          return undefined;
        }
        throw error;
      }
    });
    if (job) {
      jobs.track(job);
      onApplied();
    }
  }

  async function dismiss() {
    const next = await attempt.run(() => api.dismissPaperAgentUpdate(agent.id));
    if (next) onStale();
  }

  return (
    <section aria-label="A newer version of the code" className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid="living-update">
      <div className="flex flex-wrap items-center gap-2">
        <GitCommitHorizontal className="size-4 text-muted-foreground" aria-hidden />
        <h3 className="text-sm font-medium">A newer version of the code</h3>
        <span className="text-xs text-muted-foreground">Proposed {timeAgo(summary.proposed_at) || "a while ago"}</span>
      </div>
      <p className="text-sm" data-testid="living-update-summary">
        {describeUpdate(summary)} The agent stays at {shortCommit(summary.from_commit)} until you take it.
      </p>
      <ul className="flex list-disc flex-col gap-0.5 pl-5 text-xs text-muted-foreground" data-testid="living-update-affects">
        {describeAffects(summary).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" onClick={() => void show()} disabled={attempt.busy} aria-expanded={shown !== null}>
          {shown !== null ? "Hide what it changes" : "Show what it changes"}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => void dismiss()} disabled={busy || attempt.busy}>
          Put it aside
        </Button>
      </div>
      {shown !== null && (
        <div className="flex flex-col gap-3">
          <ul aria-label="What it changes" className="flex flex-col gap-1.5">
            {shown.diff.files.map((file) => (
              <ChangedFile key={file.path} file={file} />
            ))}
          </ul>
          {shown.diff.truncated && (
            <p className="text-xs text-muted-foreground" data-testid="update-truncated">
              Not all of it is shown: {shown.diff.changed} files differ, {shown.diff.files.length} are listed, and a diff that is long or of a file
              whose lines were not compared is not shown whole.
            </p>
          )}
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={read} onChange={(event) => setRead(event.target.checked)} />I have read what {shortCommit(shown.to_commit)} changes
          </label>
          <div>
            <Button type="button" size="sm" onClick={() => setAsking(true)} disabled={!read || busy || attempt.busy}>
              Take {shortCommit(shown.to_commit)}
            </Button>
          </div>
          <AlertDialog open={asking} onOpenChange={setAsking}>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>
                  Take {shortCommit(shown.to_commit)} as the code of {agent.title}?
                </AlertDialogTitle>
                <AlertDialogDescription>
                  The code is fetched at {shortCommit(shown.to_commit)}. The environment, the tutorials&apos; run, the tools, their checks, and the package
                  were made of {shortCommit(shown.from_commit)}, so they are taken away, and are made again by the steps that made them, which you start.
                  Nothing is repaired: whether the newer version works is not known until its tools are made and checked again.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Keep {shortCommit(shown.from_commit)}</AlertDialogCancel>
                <AlertDialogAction onClick={() => void take(shown.to_commit)}>Take it</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
    </section>
  );
}

type Refusal = "changed" | "no_update";

const REFUSALS: Record<Refusal, string> = {
  changed: "Nothing was taken: the newer version that is proposed now is not the one that you read. Read what it changes before you take it.",
  no_update: "Nothing was taken: no newer version is proposed now.",
};

// How the agent is now, as it was found when it was last looked at, the way to look at it again and on a schedule, and a newer version of
// its code, which is taken only when it is approved
export function LivingSection({
  agent,
  health,
  busy,
  looking,
  jobs,
  onChanged,
  onApplied,
  onStale,
}: {
  agent: PaperAgent;
  health: PaperAgentHealth;
  // Whether anything is being done to the agent, which a look waits for
  busy: boolean;
  // The look that is at work, if there is one
  looking: Job | undefined;
  jobs: JobsData;
  onChanged: (health: PaperAgentHealth) => void;
  // Looks at the agent and all it is made of again, as the code is being replaced by the newer version
  onApplied: () => void;
  onStale: () => void;
}) {
  const [refused, setRefused] = useState<Refusal | null>(null);
  const idle = looking === undefined && health.job === null;
  const notLooked = describeNotLooked(health);

  if (!health.watchable) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="living-no-tools">
        {notLooked}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {!health.docker.ready && (
        <Aside tone="warning">
          {health.docker.message ?? "Docker is not running."} The tools are run again in Docker, so a look without it can say only that the agent is
          unchecked.
        </Aside>
      )}
      {looking !== undefined && <JobOutput key={looking.id} job={looking} jobs={jobs} />}
      {idle &&
        (health.health !== null ? (
          <Found found={health.health} />
        ) : (
          <p className="text-sm text-muted-foreground" data-testid="living-not-looked">
            {notLooked}
          </p>
        ))}
      {idle && refused !== null && (
        <div data-testid="update-refused">
          <Aside tone="warning">{REFUSALS[refused]}</Aside>
        </div>
      )}
      {idle && health.update !== null && (
        <Update
          key={health.update.to_commit}
          agent={agent}
          health={{ ...health, update: health.update }}
          busy={busy}
          jobs={jobs}
          onApplied={onApplied}
          onStale={onStale}
          onRefused={setRefused}
        />
      )}
      {idle && <LookNow agent={agent} busy={busy} jobs={jobs} onStale={onStale} />}
      <Watch key={health.watch?.every_hours ?? "none"} agent={agent} health={health} onChanged={onChanged} />
      <p className="text-xs text-muted-foreground" data-testid="living-meaning">
        {health.meaning}
      </p>
    </div>
  );
}
