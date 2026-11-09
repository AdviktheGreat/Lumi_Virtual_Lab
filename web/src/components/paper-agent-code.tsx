"use client";

import { useId, useState } from "react";
import { CircleCheck, CircleHelp, Download, ExternalLink, Info, OctagonX, Trash2, TriangleAlert, type LucideIcon } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import {
  CHECK_LABELS,
  checkFetch,
  describeAnchor,
  describeCommit,
  describeEstimate,
  describeFetched,
  emptyFetch,
  isLink,
  orderedChecks,
  repoName,
  STOCK_ITEMS_SHOWN,
  stockRows,
  VERDICT_LABELS,
} from "@/lib/paperagents";
import type {
  PaperAgent,
  PaperAgentRepository,
  Preflight,
  PreflightStatus,
  RepositoryCandidate,
  RepositoryStock,
} from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";
import { cn } from "@/lib/utils";

const LINK = "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

// How many of the places in the paper that give a project are shown, with their words
const PLACES_SHOWN = 2;

const CHECK_ICONS: Record<PreflightStatus, LucideIcon> = {
  ok: CircleCheck,
  note: Info,
  warn: TriangleAlert,
  block: OctagonX,
  unknown: CircleHelp,
};

interface Shared {
  agent: PaperAgent;
  repository: PaperAgentRepository;
  // Whether anything is being done to the agent, which what is done to its code waits for
  busy: boolean;
}

// The address of a project, as a link to it if it is one
function Project({ url }: { url: string }) {
  if (!isLink(url)) return <span className="break-all">{url}</span>;

  return (
    <a href={url} target="_blank" rel="noreferrer noopener" className={cn("inline-flex min-w-0 items-center gap-1 break-all", LINK)}>
      {repoName(url)}
      <ExternalLink className="size-3 shrink-0" aria-hidden />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}

// A project that the paper points to, with the paper's words that say it, and the way to say that it is the code
function Candidate({
  agent,
  candidate,
  repository,
  busy,
  onChanged,
}: Shared & { candidate: RepositoryCandidate; onChanged: (agent: PaperAgent) => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);
  const shown = candidate.facts.slice(0, PLACES_SHOWN);
  // What was fetched from another address is taken away when this is the code
  const replaces = repository.cloned && !candidate.chosen;

  async function use() {
    setAsking(false);
    const next = await attempt.run(() => api.changePaperAgent(agent.id, { repo: candidate.url }));
    if (next) onChanged(next);
  }

  return (
    <li className="flex flex-col gap-1.5 rounded-lg border border-border px-3 py-2" data-testid="code-candidate">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 text-sm font-medium">
          <Project url={candidate.url} />
        </span>
        {candidate.role === "code" && <Badge variant="secondary">The paper says it is the code</Badge>}
        {candidate.chosen && <Badge variant="outline">The code of this agent</Badge>}
      </div>
      {shown.map((fact) => (
        <div key={fact.id} className="flex flex-col gap-0.5">
          <blockquote className="break-words border-l-2 border-border pl-2 text-sm text-muted-foreground">{fact.quote}</blockquote>
          <span className="text-xs text-muted-foreground">{describeAnchor(fact.anchor)}</span>
        </div>
      ))}
      {candidate.facts.length > shown.length && (
        <p className="text-xs text-muted-foreground">And {candidate.facts.length - shown.length} more places in the paper.</p>
      )}
      {!candidate.chosen && (
        <div>
          <Button
            variant="outline"
            size="xs"
            onClick={() => (replaces ? setAsking(true) : void use())}
            disabled={busy || attempt.busy}
            aria-label={`Use ${repoName(candidate.url)} as the code`}
          >
            {attempt.busy ? "Saving…" : "Use as the code"}
          </Button>
        </div>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Use {repoName(candidate.url)} as the code?</AlertDialogTitle>
            <AlertDialogDescription>
              This takes away the code that was fetched from {repoName(repository.repo?.url ?? "")}, and what was found in it. Nothing is
              fetched from the new address until you ask.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction onClick={() => void use()}>Use it</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  );
}

// The projects that the paper's links lead to, for a person to say which is the code
function Candidates({ candidates, ...shared }: Shared & { candidates: RepositoryCandidate[]; onChanged: (agent: PaperAgent) => void }) {
  const id = useId();

  return (
    <section aria-labelledby={id} className="flex flex-col gap-2">
      <h3 id={id} className="text-sm font-medium">
        Where the paper points to code <span className="font-normal text-muted-foreground">({candidates.length})</span>
      </h3>
      <p className="text-xs text-muted-foreground">
        These are the projects that the paper&apos;s links lead to. Nothing is fetched from one until you say it is the code and ask for it.
      </p>
      <ul aria-label="Projects the paper points to" className="flex flex-col gap-2">
        {candidates.map((candidate) => (
          <Candidate key={candidate.url} candidate={candidate} {...shared} />
        ))}
      </ul>
    </section>
  );
}

// Says which commit to fetch and how much, which is always said, and starts fetching
function FetchForm({ agent, repository, busy, jobs }: Shared & { jobs: JobsData }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [draft, setDraft] = useState(() => emptyFetch(repository.limits));
  const [tried, setTried] = useState(false);
  const checked = checkFetch(draft, repository.limits);
  const problems = tried ? checked.problems : {};
  const url = agent.repo?.url ?? "";

  async function fetchCode() {
    setTried(true);
    const options = checked.value;
    if (options === null) return;
    const job = await attempt.run(() => api.fetchPaperAgentRepository(agent.id, options));
    if (job) jobs.track(job);
  }

  return (
    <form
      aria-label="Fetch the code"
      onSubmit={(event) => {
        event.preventDefault();
        void fetchCode();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <p className="text-sm text-muted-foreground">
        Fetches one commit of <span className="break-all font-medium">{repoName(url)}</span>, with none of its history, and looks at its files to say what is in them and whether
        it is worth going on. Nothing in it is run: it is only read. The commit is kept, so that it is the same code later. It costs
        nothing.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id={`${id}-ref`}
          label="Branch, tag, or commit"
          hint="Leave it blank for the project's default branch."
          problem={problems.ref}
        >
          <Input
            id={`${id}-ref`}
            value={draft.ref}
            onChange={(event) => setDraft((was) => ({ ...was, ref: event.target.value }))}
            autoComplete="off"
            spellCheck={false}
            placeholder="main"
            aria-invalid={problems.ref !== undefined}
            aria-describedby={describedBy(`${id}-ref`, { hint: true, problem: problems.ref !== undefined })}
          />
        </Field>
        <Field
          id={`${id}-megabytes`}
          label="Most to fetch, in megabytes"
          hint={`A project that is more than this is refused. At most ${repository.limits.max_megabytes.toLocaleString("en-US")}.`}
          problem={problems.megabytes}
        >
          <Input
            id={`${id}-megabytes`}
            value={draft.megabytes}
            onChange={(event) => setDraft((was) => ({ ...was, megabytes: event.target.value }))}
            inputMode="numeric"
            autoComplete="off"
            aria-invalid={problems.megabytes !== undefined}
            aria-describedby={describedBy(`${id}-megabytes`, { hint: true, problem: problems.megabytes !== undefined })}
          />
        </Field>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={busy || attempt.busy || !repository.git}>
          <Download />
          {attempt.busy ? "Starting…" : busy ? "Fetching…" : "Fetch the code"}
        </Button>
      </div>
    </form>
  );
}

// What was found in a project, as rows, each with what it is, what was found, and where
function Stock({ stock }: { stock: RepositoryStock }) {
  return (
    <dl aria-label="What was found in the code" className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[13rem_minmax(0,1fr)]" data-testid="code-stock">
      {stockRows(stock).map((row) => (
        <div key={row.label} className="contents">
          <dt className="text-muted-foreground">{row.label}</dt>
          <dd className="min-w-0 break-words" data-testid="code-stock-row">
            {row.value}
            {row.items.length > 0 && (
              <ul aria-label={row.label} className="mt-1 flex flex-col gap-0.5 text-xs text-muted-foreground">
                {row.items.slice(0, STOCK_ITEMS_SHOWN).map((item) => (
                  <li key={item} className="break-all">
                    {item}
                  </li>
                ))}
                {row.items.length > STOCK_ITEMS_SHOWN && <li>And {row.items.length - STOCK_ITEMS_SHOWN} more.</li>}
              </ul>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

// Whether it is worth going on with the code, from its files, with each thing that was looked at and why
function Verdict({ preflight }: { preflight: Preflight }) {
  const id = useId();
  const estimate = describeEstimate(preflight.estimate);

  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid="code-preflight">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={id} className="text-sm font-medium">
          Whether to go on
        </h3>
        <Badge variant={preflight.verdict === "no-go" ? "destructive" : preflight.verdict === "ask" ? "outline" : "secondary"} data-testid="code-verdict">
          {VERDICT_LABELS[preflight.verdict]}
        </Badge>
      </div>
      <p className="break-words text-sm" data-testid="code-verdict-summary">
        {preflight.summary}
      </p>
      <ul aria-label="What was looked at" className="flex flex-col gap-2">
        {orderedChecks(preflight).map((check) => {
          const Icon = CHECK_ICONS[check.status];

          return (
            <li key={check.id} className="flex items-start gap-2" data-testid="code-check" data-status={check.status}>
              <Icon className={cn("mt-0.5 size-4 shrink-0", check.status === "block" ? "text-destructive" : "text-muted-foreground")} aria-hidden />
              <div className="min-w-0">
                <p className="break-words text-sm font-medium">
                  {check.title} <span className="font-normal text-muted-foreground">({CHECK_LABELS[check.status]})</span>
                </p>
                <p className="break-words text-xs text-muted-foreground">{check.detail}</p>
              </div>
            </li>
          );
        })}
      </ul>
      {estimate !== null && (
        <p className="break-words text-xs text-muted-foreground" data-testid="code-estimate">
          {estimate} {preflight.estimate.basis}
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        This is advice from the files alone. Nothing was run, so it does not say whether the code works, and it can be wrong either
        way. You decide.
      </p>
    </section>
  );
}

// Takes away the code that was fetched, so that it can be fetched again
function ClearCode({
  agent,
  busy,
  onCleared,
}: {
  agent: PaperAgent;
  busy: boolean;
  onCleared: (repository: PaperAgentRepository) => void;
}) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);

  async function clear() {
    const next = await attempt.run(() => api.clearPaperAgentRepository(agent.id));
    if (next) onCleared(next);
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button variant="outline" size="sm" onClick={() => setAsking(true)} disabled={busy || attempt.busy}>
          <Trash2 />
          Take the code away
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Take away the code of {agent.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This takes away the code that was fetched and what was found in it. The address stays, and the code can be fetched again.
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

// What was fetched, and found in it, and whether to go on
function Fetched({ agent, repository, busy, onCleared }: Shared & { onCleared: (repository: PaperAgentRepository) => void }) {
  const { intake, stock, preflight } = repository;
  if (intake === null || stock === null) return null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <p className="break-words text-sm" data-testid="code-commit">
          {describeCommit(intake.url, intake.ref, intake.commit)}
        </p>
        <p className="text-xs text-muted-foreground">
          {describeFetched(intake.cloned_at)}. It is kept as it was at that commit, to be read, and none of it was run.
        </p>
      </div>
      <Stock stock={stock} />
      {preflight !== null && <Verdict preflight={preflight} />}
      <ClearCode agent={agent} busy={busy} onCleared={onCleared} />
    </div>
  );
}

// The code of an agent: the projects its paper points to, fetching one at a commit, what was found in it, and whether it is
// worth going on
export function CodeSection({
  agent,
  repository,
  busy,
  jobs,
  onChanged,
  onCleared,
}: Shared & {
  jobs: JobsData;
  onChanged: (agent: PaperAgent) => void;
  onCleared: (repository: PaperAgentRepository) => void;
}) {
  const shared = { agent, repository, busy };
  const candidates = repository.candidates;
  const hasCode = agent.repo !== null;

  return (
    <div className="flex flex-col gap-4">
      {!repository.git && (
        <Aside tone="warning">Git is not installed on this machine, and fetching code takes it. Install it to fetch the code.</Aside>
      )}
      {candidates.length > 0 && <Candidates candidates={candidates} {...shared} onChanged={onChanged} />}
      {!hasCode && candidates.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Say where the code is, under Details below, or read the paper, which may say where it is.
        </p>
      )}
      {hasCode && !repository.cloned && <FetchForm {...shared} jobs={jobs} />}
      {repository.cloned && <Fetched {...shared} onCleared={onCleared} />}
    </div>
  );
}
