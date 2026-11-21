"use client";

import { useId, useState } from "react";
import {
  Circle,
  CircleAlert,
  CircleCheck,
  CircleMinus,
  CirclePause,
  CircleX,
  ExternalLink,
  Loader2,
  Play,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { describedBy, Field } from "@/components/settings-fields";
import { WorkStatus } from "@/components/work-status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import {
  checkMore,
  checkOneGo,
  decisionOf,
  describeLimit,
  describeOneGo,
  emptyOneGo,
  offersWithoutCode,
  ONEGO_STATE_LABELS,
  ONEGO_STEP_LABELS,
  spends,
  type OneGoDecision,
} from "@/lib/paperagent-onego";
import { CHECK_LABELS, isLink, paperFile, repoName, VERDICT_LABELS } from "@/lib/paperagents";
import { timeAgo } from "@/lib/format";
import type { Job, OneGoStep, OneGoStepState, PaperAgent, PaperAgentMakeOptions, PaperAgentOneGo, PaperAgentsList } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";
import { cn } from "@/lib/utils";

const LINK = "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

interface Shared {
  agent: PaperAgent;
  onego: PaperAgentOneGo;
  // Whether something other than making it in one go is being done to the agent, which starting it waits for
  busy: boolean;
  jobs: JobsData;
  // Shows how it stands as what was asked gives it back
  onChanged: (next: PaperAgentOneGo) => void;
}

// Asks the server to start making the agent in one go, or to go on with it, and follows the job that it starts
function useGoing({ agent, jobs, onChanged }: Pick<Shared, "agent" | "jobs" | "onChanged">) {
  const { report } = useServer();
  const attempt = useAttempt(report);

  async function go(options: PaperAgentMakeOptions) {
    const next = await attempt.run(() => api.makePaperAgentInOneGo(agent.id, options));
    if (!next) return;
    onChanged(next);
    if (next.job !== null) jobs.track(next.job);
  }

  return { attempt, go };
}

const STEP_ICONS: Record<OneGoStepState, React.ComponentType<{ className?: string }>> = {
  pending: Circle,
  running: Loader2,
  done: CircleCheck,
  skipped: CircleMinus,
  waiting: CircleAlert,
  failed: CircleX,
  stopped: CirclePause,
};

const STEP_TONES: Record<OneGoStepState, string> = {
  pending: "text-muted-foreground/60",
  running: "text-foreground animate-spin",
  done: "text-foreground",
  skipped: "text-muted-foreground",
  waiting: "text-amber-600 dark:text-amber-400",
  failed: "text-destructive",
  stopped: "text-muted-foreground",
};

// Each step in the order it is done, how it went, and what the one at work is doing
function Timeline({ steps, job }: { steps: OneGoStep[]; job: Job | undefined }) {
  return (
    <ol aria-label="Steps of making it in one go" className="flex flex-col">
      {steps.map((step, index) => {
        const Icon = STEP_ICONS[step.state] ?? Circle;
        const detail = step.state === "running" && job?.progress.step === step.step ? job.progress.detail : undefined;
        const last = index === steps.length - 1;

        return (
          <li key={step.step} className="relative flex gap-3 pb-3 last:pb-0" data-testid="onego-step" data-state={step.state}>
            {!last && <span aria-hidden className="absolute top-5 bottom-0 left-[9px] w-px bg-border" />}
            <Icon className={cn("relative mt-0.5 size-[18px] shrink-0", STEP_TONES[step.state])} aria-hidden />
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className={cn("text-sm", step.state === "pending" ? "text-muted-foreground" : "font-medium")}>{step.title}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{ONEGO_STEP_LABELS[step.state] ?? step.state}</span>
              </div>
              {step.note && <p className="break-words text-xs text-muted-foreground">{step.note}</p>}
              {detail && <p className="break-words text-xs text-muted-foreground">{detail}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// What starting it is asked for: the most that reading may spend, where the code is if nobody has said, and whether it is given
function StartForm({ agent, onego, busy, jobs, onChanged, hosts }: Shared & { hosts: readonly string[] }) {
  const id = useId();
  const [draft, setDraft] = useState(() => emptyOneGo(onego.settings));
  const [tried, setTried] = useState(false);
  const { attempt, go } = useGoing({ agent, jobs, onChanged });
  const reads = spends(agent);
  const asksRepo = agent.repo === null;
  const checked = checkOneGo(draft, { reads, asksRepo, hosts });
  const problems = tried ? checked.problems : {};

  async function start() {
    setTried(true);
    if (checked.value === null) return;
    await go(checked.value);
  }

  return (
    <form
      aria-label="Make it in one go"
      onSubmit={(event) => {
        event.preventDefault();
        void start();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <p className="text-sm text-muted-foreground">
        This fetches the code and looks at it, reads the paper, builds the environment, runs the tutorials, and makes and checks the tools,
        one after another, and gives the agent to your conversations. It stops and asks you where you are to decide: where the code is, when
        the paper does not say; whether to go on with code that looking at it says to ask about; and for more to spend.{" "}
        {reads
          ? "Only reading the paper costs money, in model requests. Everything else runs on this machine."
          : "The paper has been read, so nothing it does costs money."}
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        {reads && (
          <Field
            id={`${id}-budget`}
            label="Most reading may spend, in dollars"
            hint="Reading stops at this, and asks you for more."
            problem={problems.budget}
          >
            <Input
              id={`${id}-budget`}
              value={draft.budget}
              onChange={(event) => setDraft((was) => ({ ...was, budget: event.target.value }))}
              inputMode="decimal"
              autoComplete="off"
              aria-invalid={problems.budget !== undefined}
              aria-describedby={describedBy(`${id}-budget`, { hint: true, problem: problems.budget !== undefined })}
            />
          </Field>
        )}
        {asksRepo && !draft.withoutCode && (
          <Field
            id={`${id}-repo`}
            label="Where the code is"
            hint="Leave it blank to be asked, with the projects that the paper points to."
            problem={problems.repo}
          >
            <Input
              id={`${id}-repo`}
              value={draft.repo}
              onChange={(event) => setDraft((was) => ({ ...was, repo: event.target.value }))}
              autoComplete="off"
              spellCheck={false}
              placeholder="https://github.com/owner/name"
              aria-invalid={problems.repo !== undefined}
              aria-describedby={describedBy(`${id}-repo`, { hint: true, problem: problems.repo !== undefined })}
            />
          </Field>
        )}
      </div>
      <div className="flex flex-col gap-2">
        {asksRepo && (
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.withoutCode} onChange={(event) => setDraft((was) => ({ ...was, withoutCode: event.target.checked }))} />
            The paper has no code: make an agent of the paper only
          </label>
        )}
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={draft.give} onChange={(event) => setDraft((was) => ({ ...was, give: event.target.checked }))} />
          Give it to my conversations once it is made
        </label>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={busy || attempt.busy}>
          <Play />
          {attempt.busy ? "Starting…" : "Make it all now"}
        </Button>
        {busy && <span className="text-xs text-muted-foreground">Something else is being done to the agent. This waits for that.</span>}
      </div>
    </form>
  );
}

// A project that the paper points to, with its words, for the person to say is the code
function CandidateRow({
  url,
  role,
  quote,
  disabled,
  onUse,
}: {
  url: string;
  role: string;
  quote: string;
  disabled: boolean;
  onUse: () => void;
}) {
  return (
    <li className="flex flex-col gap-1.5 rounded-lg border border-border px-3 py-2" data-testid="onego-candidate">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 text-sm font-medium">
          {url.startsWith("https://") && isLink(url) ? (
            <a href={url} target="_blank" rel="noreferrer noopener" className={cn("inline-flex min-w-0 items-center gap-1 break-all", LINK)}>
              {repoName(url)}
              <ExternalLink className="size-3 shrink-0" aria-hidden />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          ) : (
            <span className="break-all">{url}</span>
          )}
        </span>
        {role === "code" && <Badge variant="secondary">The paper says it is the code</Badge>}
      </div>
      {quote && <blockquote className="break-words border-l-2 border-border pl-2 text-sm text-muted-foreground">{quote}</blockquote>}
      <div>
        <Button variant="outline" size="xs" onClick={onUse} disabled={disabled} aria-label={`Use as the code and go on: ${repoName(url)}`}>
          Use as the code and go on
        </Button>
      </div>
    </li>
  );
}

// Where the code is, said by a project the paper points to or by its address
function ChooseCode({
  decision,
  hosts,
  disabled,
  go,
}: {
  decision: Extract<OneGoDecision, { kind: "code" }>;
  hosts: readonly string[];
  disabled: boolean;
  go: (options: PaperAgentMakeOptions) => Promise<void>;
}) {
  const id = useId();
  const [repo, setRepo] = useState("");
  const [tried, setTried] = useState(false);
  const checked = checkOneGo({ budget: "", repo, give: true, withoutCode: false }, { reads: false, asksRepo: true, hosts });
  const problem = tried ? (repo.trim() === "" ? "Give the address of the code." : checked.problems.repo) : undefined;

  return (
    <div className="flex flex-col gap-3">
      {decision.candidates.length > 0 && (
        <ul aria-label="Projects the paper points to" className="flex flex-col gap-2">
          {decision.candidates.map((candidate) => (
            <CandidateRow key={candidate.url} {...candidate} disabled={disabled} onUse={() => void go({ repo: candidate.url })} />
          ))}
        </ul>
      )}
      <form
        aria-label="Say where the code is"
        onSubmit={(event) => {
          event.preventDefault();
          setTried(true);
          if (repo.trim() !== "" && checked.value?.repo !== undefined) void go({ repo: checked.value.repo });
        }}
        className="flex flex-col gap-2"
      >
        <Field id={`${id}-repo`} label={decision.candidates.length > 0 ? "Or say where it is" : "Where the code is"} problem={problem}>
          <div className="flex flex-wrap gap-2">
            <Input
              id={`${id}-repo`}
              value={repo}
              onChange={(event) => setRepo(event.target.value)}
              autoComplete="off"
              spellCheck={false}
              placeholder="https://github.com/owner/name"
              className="min-w-0 flex-1 sm:max-w-md"
              aria-invalid={problem !== undefined}
              aria-describedby={describedBy(`${id}-repo`, { problem: problem !== undefined })}
            />
            <Button type="submit" variant="outline" disabled={disabled}>
              Go on with it
            </Button>
          </div>
        </Field>
      </form>
    </div>
  );
}

// Whether to go on with the code as it was looked at, with what looking at it weighed
function Preflight({ decision }: { decision: Extract<OneGoDecision, { kind: "preflight" }> }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {decision.verdict !== null && (
          <Badge variant={decision.verdict === "no-go" ? "destructive" : "secondary"}>{VERDICT_LABELS[decision.verdict] ?? decision.verdict}</Badge>
        )}
        {decision.commit !== null && (
          <span className="text-xs text-muted-foreground">
            Of commit <code className="font-mono">{decision.commit.slice(0, 12)}</code>
          </span>
        )}
      </div>
      {decision.checks.length > 0 && (
        <ul aria-label="What looking at the code weighed" className="flex flex-col gap-1.5">
          {decision.checks.map((check) => (
            <li key={check.title} className="flex flex-col gap-0.5 rounded-lg border border-border px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{check.title}</span>
                <Badge variant={check.status === "block" ? "destructive" : "outline"}>{CHECK_LABELS[check.status] ?? check.status}</Badge>
              </div>
              <p className="break-words text-xs text-muted-foreground">{check.detail}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// How much more reading may spend, which it carries on from where it stopped with
function MoreToSpend({
  decision,
  disabled,
  go,
}: {
  decision: Extract<OneGoDecision, { kind: "limit" }>;
  disabled: boolean;
  go: (options: PaperAgentMakeOptions) => Promise<void>;
}) {
  const id = useId();
  const [more, setMore] = useState(() => (decision.limit === null ? "1" : String(decision.limit)));
  const [tried, setTried] = useState(false);
  const checked = checkMore(more);
  const problem = tried ? checked.problems.budget : undefined;
  const said = describeLimit(decision.spent, decision.limit);

  return (
    <form
      aria-label="Say how much more reading may spend"
      onSubmit={(event) => {
        event.preventDefault();
        setTried(true);
        if (checked.value !== null) void go(checked.value);
      }}
      className="flex flex-col gap-2"
    >
      {said && <p className="text-sm text-muted-foreground">{said}</p>}
      <Field id={`${id}-more`} label="How much more it may spend, in dollars" problem={problem}>
        <div className="flex flex-wrap gap-2">
          <Input
            id={`${id}-more`}
            value={more}
            onChange={(event) => setMore(event.target.value)}
            inputMode="decimal"
            autoComplete="off"
            className="sm:max-w-xs"
            aria-invalid={problem !== undefined}
            aria-describedby={describedBy(`${id}-more`, { problem: problem !== undefined })}
          />
          <Button type="submit" disabled={disabled}>
            <Play />
            Go on reading
          </Button>
        </div>
      </Field>
    </form>
  );
}

// What stands in the way, and what the person can say to it
function Decision({ agent, onego, busy, jobs, onChanged, hosts }: Shared & { hosts: readonly string[] }) {
  const { attempt, go } = useGoing({ agent, jobs, onChanged });
  const decision = decisionOf(onego);
  const disabled = busy || attempt.busy;
  const stuck = onego.stuck;
  const withoutCode = offersWithoutCode(onego);
  const waiting = onego.state === "waiting";
  // The paper's file is to be uploaded before going on, which is done on this page
  const needsFile = decision.kind === "paper" && paperFile(agent.paper) === null;

  if (decision.kind === "start" || decision.kind === "going") return null;

  return (
    <section
      aria-label={waiting ? "What it is waiting for" : "How it ended"}
      className={cn(
        "flex flex-col gap-3 rounded-lg border p-3",
        waiting ? "border-amber-500/50 bg-amber-500/5" : onego.state === "failed" ? "border-destructive/40" : "border-border",
      )}
      data-testid="onego-decision"
    >
      {decision.kind === "over" ? (
        <p className="text-sm">{onego.summary ?? "Every step has been got to."}</p>
      ) : (
        stuck !== null && <p className="break-words text-sm">{stuck.reason}</p>
      )}
      {decision.kind === "code" && <ChooseCode decision={decision} hosts={hosts} disabled={disabled} go={go} />}
      {decision.kind === "preflight" && <Preflight decision={decision} />}
      {decision.kind === "limit" && <MoreToSpend decision={decision} disabled={disabled} go={go} />}
      {decision.kind === "paper" && (
        <p className="text-sm text-muted-foreground">
          {needsFile ? "Upload the paper's file under Paper file, below, and then go on." : "The paper's file is uploaded, so it can go on."}
        </p>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div className="flex flex-wrap items-center gap-2">
        {decision.kind === "preflight" && (
          <Button onClick={() => void go({ go_on: true })} disabled={disabled}>
            <Play />
            {decision.verdict === "no-go" ? "Go on with this code anyway" : "Go on with this code"}
          </Button>
        )}
        {decision.kind === "paper" && (
          <Button onClick={() => void go({})} disabled={disabled || needsFile}>
            <Play />
            Go on
          </Button>
        )}
        {decision.kind === "again" && (
          <Button onClick={() => void go({})} disabled={disabled}>
            {onego.state === "failed" ? <RotateCcw /> : <Play />}
            {decision.label}
          </Button>
        )}
        {decision.kind === "over" && (
          <Button variant="outline" onClick={() => void go({})} disabled={disabled}>
            <RotateCcw />
            Go over it again
          </Button>
        )}
        {withoutCode && (
          <Button variant="outline" onClick={() => void go({ without_code: true })} disabled={disabled}>
            Go on without the code
          </Button>
        )}
        {busy && <span className="text-xs text-muted-foreground">Something else is being done to the agent. This waits for that.</span>}
      </div>
    </section>
  );
}

// Takes away how making it in one go went, so that it is asked for afresh
function Forget({ agent, onChanged, disabled }: Pick<Shared, "agent" | "onChanged"> & { disabled: boolean }) {
  const { report } = useServer();
  const attempt = useAttempt(report);

  async function forget() {
    const next = await attempt.run(() => api.forgetPaperAgentOneGo(agent.id));
    if (next) onChanged(next);
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button variant="ghost" size="sm" onClick={() => void forget()} disabled={disabled || attempt.busy}>
          <Trash2 />
          {attempt.busy ? "Clearing…" : "Clear this and start afresh"}
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
    </div>
  );
}

// Making the agent in one go: asking for it, how far it has got, what it is waiting for, and the way to stop it
export function OneGoSection({
  agent,
  onego,
  busy,
  job,
  jobs,
  list,
  onChanged,
}: Shared & { job: Job | undefined; list: PaperAgentsList }) {
  const hosts = list.repo_hosts;
  // The job is what says that it is going, before what is kept of it has been looked at again
  const going = job !== undefined || onego.state === "running";
  const shown: PaperAgentOneGo = going && onego.state !== "running" ? { ...onego, state: "running" } : onego;
  const shared = { agent, onego: shown, busy: busy || going, jobs, onChanged };

  if (shown.state === "none" && !going) return <StartForm key={agent.id} {...shared} busy={busy} hosts={hosts} />;

  return (
    <div className="flex flex-col gap-3">
      <WorkStatus job={job} last={undefined} jobs={jobs} label="Making it in one go" />
      {!going && (
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={shown.state === "failed" ? "destructive" : shown.state === "done" ? "secondary" : "outline"}>
            {ONEGO_STATE_LABELS[shown.state] ?? shown.state}
          </Badge>
          <span className="text-xs text-muted-foreground">
            {describeOneGo(shown)}
            {shown.finished_at && ` · ended ${timeAgo(shown.finished_at) || "a while ago"}`}
          </span>
        </div>
      )}
      <Decision key={`${shown.state}:${shown.stuck?.step ?? ""}:${shown.stuck?.kind ?? ""}`} {...shared} busy={busy} hosts={hosts} />
      <Timeline steps={shown.steps} job={job} />
      {!going && <Forget agent={agent} onChanged={onChanged} disabled={busy} />}
    </div>
  );
}
