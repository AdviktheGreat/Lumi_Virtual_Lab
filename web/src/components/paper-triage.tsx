"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, CircleCheck, CircleHelp, ExternalLink, Info, OctagonX, Plus, Trash2, TriangleAlert, type LucideIcon } from "lucide-react";
import { Looked } from "@/components/looked";
import { Notice, ProblemNotice } from "@/components/messages";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { WorkStatus } from "@/components/work-status";
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
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { agentAddress, CHECK_LABELS, describeEstimate, existingOf, isLink, repoName } from "@/lib/paperagents";
import {
  agentFrom,
  agentOf,
  checkTitle,
  describeCodeFrom,
  describeCounts,
  describeStock,
  describeTriageSource,
  lastTriageJob,
  orderedTriageChecks,
  STATE_LABELS,
  TIER_LABELS,
  TIERS,
  triageJob,
  triageKey,
  TRIAGES_ADDRESS,
} from "@/lib/triages";
import type { PaperAgent, PreflightStatus, Triage, TriageEntry, TriageTier } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";
import { usePaperAgentsList } from "@/lib/use-paperagents";
import { useTriage } from "@/lib/use-triages";
import { cn } from "@/lib/utils";

const LINK = "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

const CHECK_ICONS: Record<PreflightStatus, LucideIcon> = {
  ok: CircleCheck,
  note: Info,
  warn: TriangleAlert,
  block: OctagonX,
  unknown: CircleHelp,
};

const TIER_STYLES: Record<TriageTier, string> = {
  go: "border-success/50 bg-success/10 text-success",
  ask: "border-warning/50 bg-warning/10 text-warning",
  "no-go": "border-destructive/40 bg-destructive/10 text-destructive",
  not_looked_at: "border-border bg-muted/50 text-muted-foreground",
  no_code: "border-border bg-muted/50 text-muted-foreground",
};

// A link that opens in a new tab, which says so to a reader of the screen
function Away({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className={cn("inline-flex min-w-0 items-center gap-1 break-words", LINK, className)}>
      {children}
      <ExternalLink className="size-3 shrink-0" aria-hidden />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}

// The address of a project, as a link to it if it is one, which the server keeps only if it is https
function Project({ url }: { url: string }) {
  if (!url.startsWith("https://") || !isLink(url)) return <span className="break-all">{url}</span>;

  return (
    <Away href={url} className="break-all">
      {repoName(url)}
    </Away>
  );
}

// The way to delete a triage, which may not be done while it is being made, which the server would refuse
function TriageHeader({ triage }: { triage: Triage }) {
  const { report } = useServer();
  const router = useRouter();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);
  const running = triage.state === "running";
  const title = describeTriageSource(triage.source);

  async function remove() {
    const left = await attempt.run(() => api.deleteTriage(triage.id));
    if (left) router.push(TRIAGES_ADDRESS);
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="break-words font-serif text-2xl font-medium tracking-tight">Triage</h2>
            <Badge
              variant={triage.state === "failed" || triage.state === "interrupted" ? "destructive" : running ? "secondary" : "outline"}
              data-testid="triage-state"
            >
              {STATE_LABELS[triage.state]}
            </Badge>
          </div>
          <p className="break-words text-sm" data-testid="triage-source">
            {title}.
          </p>
          <p className="text-sm text-muted-foreground">
            Begun {timeAgo(triage.created_at)}
            {triage.finished_at !== null && <>, ended {timeAgo(triage.finished_at)}</>}. The code of at most{" "}
            {triage.settings.most_looked_at === 1 ? "one paper" : `${triage.settings.most_looked_at} papers`} is looked at, and at most{" "}
            {triage.settings.max_megabytes} MB of each.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setAsking(true)} disabled={running || attempt.busy} aria-label="Delete the triage">
          <Trash2 />
          Delete
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete the triage?</AlertDialogTitle>
            <AlertDialogDescription>
              This deletes what was found of the code of its papers. The PaperAgents that were made from it stay.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void remove()}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// How the triage ended, where that is something to know
function Ending({ triage }: { triage: Triage }) {
  if (triage.state === "running") {
    return <Notice tone="muted">The papers are put in order when the look at them ends.</Notice>;
  }
  if (triage.state === "interrupted") {
    return (
      <Notice tone="error">
        The server stopped while the triage was being made, so what was found was not kept. Delete it and begin another.
      </Notice>
    );
  }
  const kept = triage.entries.length > 0;
  if (triage.state === "failed") {
    return (
      <Notice tone="error">
        It failed{triage.note ? `: ${triage.note.replace(/\.?$/, ".")}` : "."}{" "}
        {kept ? "What was found before that is below." : "It ended before any paper was looked at, so nothing was kept."}
      </Notice>
    );
  }
  if (triage.state === "stopped") {
    return (
      <Notice tone="muted">
        {kept
          ? "It was stopped. The papers that were looked at before that are in order below, and of the rest it is said why."
          : "It was stopped before any paper was looked at, so nothing was kept."}
      </Notice>
    );
  }

  return null;
}

// How many papers came to each tier
function Counts({ triage }: { triage: Triage }) {
  return (
    <ul aria-label="How many papers came to each" className="grid grid-cols-2 gap-2 sm:grid-cols-5">
      {TIERS.map((tier) => (
        <li key={tier} className={cn("flex flex-col rounded-lg border px-3 py-2", TIER_STYLES[tier])} data-testid="triage-count" data-tier={tier}>
          <span className="text-xl font-medium tabular-nums">{triage.counts[tier]}</span>
          <span className="text-xs">{TIER_LABELS[tier]}</span>
        </li>
      ))}
    </ul>
  );
}

// What the order means and does not, and what each tier is
function Meaning({ triage }: { triage: Triage }) {
  const meaning = triage.meaning;

  return (
    <div className="flex flex-col gap-2 text-sm" data-testid="triage-meaning">
      <p className="max-w-3xl">{meaning.ranking}</p>
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">How it is ordered, and what each tier means</summary>
        <div className="flex flex-col gap-2 pt-2">
          <p>{meaning.order}</p>
          <dl className="grid gap-x-3 gap-y-1 sm:grid-cols-[8rem_minmax(0,1fr)]">
            {TIERS.map((tier) => (
              <div key={tier} className="contents">
                <dt className="font-medium text-foreground">{TIER_LABELS[tier]}</dt>
                <dd>{meaning.tiers[tier]}</dd>
              </div>
            ))}
          </dl>
          <p>{meaning.checked}</p>
        </div>
      </details>
    </div>
  );
}

// Makes a PaperAgent of a paper, with the code that the triage found, or opens the one there is
function MakeAgent({ entry, agent }: { entry: TriageEntry; agent: PaperAgent | undefined }) {
  const { report } = useServer();
  const router = useRouter();
  const attempt = useAttempt(report);
  const [existing, setExisting] = useState<string | null>(null);
  const body = agentFrom(entry);
  if (body === null) return null;

  if (agent !== undefined) {
    return (
      <Link href={agentAddress(agent.id)} className={cn("w-fit text-sm", LINK)}>
        Open its PaperAgent
      </Link>
    );
  }

  async function make() {
    if (body === null) return;
    setExisting(null);
    const made = await attempt.run(async () => {
      try {
        return await api.makePaperAgent(body);
      } catch (error) {
        setExisting(existingOf(error));
        throw error;
      }
    });
    if (made) router.push(agentAddress(made.id));
  }

  return (
    <div className="flex flex-col gap-1.5">
      <Button variant="outline" size="sm" className="w-fit" onClick={() => void make()} disabled={attempt.busy} aria-label={`Make a PaperAgent of ${entry.title}`}>
        <Plus />
        {attempt.busy ? "Making…" : "Make a PaperAgent"}
      </Button>
      {attempt.problem && (
        <div className="flex flex-col gap-1.5">
          <ProblemNotice problem={attempt.problem} />
          {existing !== null && (
            <Link href={agentAddress(existing)} className={cn("w-fit text-sm", LINK)}>
              Open that PaperAgent
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

// What was found of one paper: where it is in the order and why, its code, and each check that was made of it
function Entry({ entry, agent }: { entry: TriageEntry; agent: PaperAgent | undefined }) {
  const from = describeCodeFrom(entry);
  const estimate = entry.estimate !== null ? describeEstimate({ ...entry.estimate, basis: "" }) : null;
  const facts = [entry.doi !== null ? `DOI ${entry.doi}` : null, entry.date, entry.category].filter((fact) => fact !== null);
  const checks = orderedTriageChecks(entry.checks);

  return (
    <li className="flex gap-3 rounded-xl border border-border bg-card p-4" data-testid="triage-entry" data-tier={entry.tier}>
      <span className="w-8 shrink-0 pt-0.5 text-right font-mono text-sm text-muted-foreground tabular-nums">
        <span aria-hidden>{entry.rank}</span>
        <span className="sr-only">Ranked {entry.rank}</span>
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-start gap-2">
          <h3 className="min-w-0 flex-1 break-words text-sm font-medium">
            {entry.doi !== null ? <Away href={`https://doi.org/${entry.doi}`}>{entry.title}</Away> : entry.title}
          </h3>
          <span className={cn("rounded-md border px-1.5 py-0.5 text-xs font-medium", TIER_STYLES[entry.tier])} data-testid="triage-tier">
            {TIER_LABELS[entry.tier]}
          </span>
        </div>
        {facts.length > 0 && <p className="break-words text-xs text-muted-foreground">{facts.join(" · ")}</p>}
        <p className="break-words text-sm" data-testid="triage-why">
          {entry.why}
        </p>
        {entry.code !== null && (
          <p className="break-words text-xs text-muted-foreground" data-testid="triage-code">
            Code: <Project url={entry.code} />
            {from !== null && `, from ${from}`}
          </p>
        )}
        {entry.other_codes.length > 0 && (
          <p className="break-words text-xs text-muted-foreground">
            Its abstract gives {entry.other_codes.length === 1 ? "another" : "others"} too:{" "}
            {entry.other_codes.map((url, at) => (
              <span key={url}>
                {at > 0 && ", "}
                <Project url={url} />
              </span>
            ))}
          </p>
        )}
        {entry.stock !== null && (
          <p className="break-words text-xs text-muted-foreground" data-testid="triage-stock">
            {describeStock(entry.stock)}
            {entry.tutorials !== null && ` · ${entry.tutorials} ${entry.tutorials === 1 ? "tutorial or example" : "tutorials or examples"}`}
          </p>
        )}
        {estimate !== null && <p className="break-words text-xs text-muted-foreground">{estimate}</p>}
        {checks.length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground">What was looked at</summary>
            <ul aria-label={`What was looked at of ${entry.title}`} className="flex flex-col gap-1.5 pt-2">
              {checks.map((check) => {
                const Icon = CHECK_ICONS[check.status];

                return (
                  <li key={check.id} className="flex items-start gap-2" data-testid="triage-check" data-status={check.status}>
                    <Icon className={cn("mt-0.5 size-3.5 shrink-0", check.status === "block" ? "text-destructive" : "text-muted-foreground")} aria-hidden />
                    <div className="min-w-0">
                      <p className="break-words font-medium">
                        {checkTitle(check)} <span className="font-normal text-muted-foreground">({CHECK_LABELS[check.status]})</span>
                      </p>
                      <p className="break-words text-muted-foreground">{check.detail}</p>
                    </div>
                  </li>
                );
              })}
            </ul>
          </details>
        )}
        <MakeAgent entry={entry} agent={agent} />
      </div>
    </li>
  );
}

// The papers in order. Those that say nowhere where their code is are kept apart at the end, as there is often a great many of them.
function Entries({ triage, agents }: { triage: Triage; agents: readonly PaperAgent[] }) {
  const shown = triage.entries.filter((entry) => entry.tier !== "no_code");
  const none = triage.entries.filter((entry) => entry.tier === "no_code");
  if (triage.entries.length === 0) {
    return <p className="text-sm text-muted-foreground">No papers were found to look at.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      {shown.length > 0 && (
        <ol aria-label="The papers in order" className="flex flex-col gap-2">
          {shown.map((entry) => (
            <Entry key={entry.position} entry={entry} agent={agentOf(agents, entry.doi)} />
          ))}
        </ol>
      )}
      {none.length > 0 && (
        <details className="flex flex-col gap-2" open={shown.length === 0} data-testid="triage-no-code">
          <summary className="cursor-pointer text-sm text-muted-foreground">
            {none.length} {none.length === 1 ? "paper says" : "papers say"} nowhere in the abstract where the code is
          </summary>
          <ol aria-label="The papers with no code found" className="flex flex-col gap-2 pt-2">
            {none.map((entry) => (
              <Entry key={entry.position} entry={entry} agent={agentOf(agents, entry.doi)} />
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}

function TriageBody({ triage, agents }: { triage: Triage; agents: readonly PaperAgent[] }) {
  const jobs = useSetupJobs();

  return (
    <div className="flex flex-col gap-10">
      <div className="flex flex-col gap-4">
        <TriageHeader triage={triage} />
        <WorkStatus job={triageJob(jobs.jobs, triage.id)} last={lastTriageJob(jobs.jobs, triage.id)} jobs={jobs} label="What is being done" />
        <Ending triage={triage} />
      </div>
      {triage.entries.length > 0 && (
        <PageSection title="What it came to" intro={describeCounts(triage.counts) + "."}>
          <Counts triage={triage} />
          <Meaning triage={triage} />
        </PageSection>
      )}
      {(triage.entries.length > 0 || triage.state === "done") && (
        <PageSection title="The papers" intro="The best to make tools from first are at the top. A PaperAgent made from one is given the code the triage found.">
          <Entries triage={triage} agents={agents} />
        </PageSection>
      )}
    </div>
  );
}

// One triage
export function TriagePage({ id }: { id: string }) {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const again = triageKey(jobs.jobs, jobs.finished, id);
  const triage = useTriage(id, report, again);
  const agents = usePaperAgentsList(report, again);
  const known = agents.value.kind === "ready" ? agents.value.value.agents : [];

  return (
    <>
      <Link
        href={TRIAGES_ADDRESS}
        className="inline-flex items-center gap-1 self-start rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        All triages
      </Link>
      <Looked state={triage.value} label="Looking at the triage" failure="The triage could not be looked at." onRetry={triage.reload}>
        {(value) => <TriageBody triage={value} agents={known} />}
      </Looked>
    </>
  );
}
