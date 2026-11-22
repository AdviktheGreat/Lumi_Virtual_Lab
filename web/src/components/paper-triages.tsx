"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ListOrdered } from "lucide-react";
import { Looked } from "@/components/looked";
import { Notice, ProblemNotice } from "@/components/messages";
import { PageSection } from "@/components/page-section";
import { describedBy, Field } from "@/components/settings-fields";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import {
  checkTriage,
  describeCounts,
  describeTriageSource,
  emptyTriage,
  MOST_LOOKED_UP,
  STATE_LABELS,
  triageAddress,
  triageKey,
  type TriageDraft,
} from "@/lib/triages";
import type { TriagesList, TriageSummary } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";
import { useTriagesList } from "@/lib/use-triages";

const INTRO =
  "A triage asks which papers of a list have code worth making tools from first. You give papers by DOI, or ask for the preprints bioRxiv posted in a period, or both. The code of each is fetched at one commit, read, and checked as a PaperAgent's is before anything is built, and then the papers are put in order. Nothing is run, no model is asked, and nothing is spent. It says how likely the code is to give tools without trouble, and not whether a paper is good.";

// How many characters the papers may be typed in, so that a paste of something else is not taken whole
const MAX_PAPERS_CHARS = 60_000;

function TriageRow({ triage }: { triage: TriageSummary }) {
  return (
    <li className="flex flex-col gap-1.5 rounded-xl border border-border bg-card p-4 transition-colors hover:border-ring/50" data-testid="triage">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="min-w-0 break-words text-sm font-medium">
          <Link href={triageAddress(triage.id)} className="rounded-sm outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
            {describeTriageSource(triage.source)}
          </Link>
        </h3>
        <Badge variant={triage.state === "failed" || triage.state === "interrupted" ? "destructive" : triage.state === "running" ? "secondary" : "outline"}>
          {STATE_LABELS[triage.state]}
        </Badge>
      </div>
      <p className="text-xs text-muted-foreground">
        {triage.state === "running" ? "The papers are put in order when the look at them ends" : describeCounts(triage.counts)}. Begun{" "}
        {timeAgo(triage.created_at)}.
      </p>
    </li>
  );
}

// The triages there are, the latest first
function TriageList({ triages }: { triages: readonly TriageSummary[] }) {
  if (triages.length === 0) {
    return (
      <div className="flex flex-col gap-1 rounded-xl border border-dashed border-border p-5" data-testid="triages-empty">
        <p className="text-sm font-medium">There are no triages yet</p>
        <p className="text-sm text-muted-foreground">Begin one below.</p>
      </div>
    );
  }

  return (
    <ul aria-label="Triages" className="flex flex-col gap-2">
      {triages.map((triage) => (
        <TriageRow key={triage.id} triage={triage} />
      ))}
    </ul>
  );
}

// Begins a triage, which is a job, and goes to its page, where how far it has got is shown
function NewTriage({ list }: { list: TriagesList }) {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const router = useRouter();
  const id = useId();
  const limits = list.limits;
  const [draft, setDraft] = useState<TriageDraft>(() => emptyTriage(limits));
  const [tried, setTried] = useState(false);
  const attempt = useAttempt(report);
  const checked = checkTriage(draft, limits);
  const problems = tried ? checked.problems : {};
  const full = list.triages.length >= limits.most_triages;
  const field = (name: string) => `${id}-${name}`;
  const busy = attempt.busy;

  function change(part: Partial<TriageDraft>) {
    setDraft((was) => ({ ...was, ...part }));
  }

  async function begin() {
    setTried(true);
    const body = checked.value;
    if (body === null) return;
    const triage = await attempt.run(() => api.startTriage(body));
    if (!triage) return;
    if (triage.job !== null) jobs.track(triage.job);
    router.push(triageAddress(triage.id));
  }

  return (
    <form
      aria-label="Begin a triage"
      onSubmit={(event) => {
        event.preventDefault();
        void begin();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <Field
        id={field("papers")}
        label="Papers"
        hint={`A line each: its DOI, and after it, if you know it, the address of its code. A paper given without an address has its abstract looked up, for the first ${MOST_LOOKED_UP} of them, and the first address of code in it is used. Up to ${limits.most_given}.`}
        problem={problems.papers}
      >
        <Textarea
          id={field("papers")}
          value={draft.papers}
          onChange={(event) => change({ papers: event.target.value })}
          maxLength={MAX_PAPERS_CHARS}
          rows={5}
          spellCheck={false}
          placeholder={"10.1101/2024.01.01.123456 https://github.com/owner/name\n10.1038/s41586-020-2649-2"}
          className="font-mono text-xs"
          readOnly={busy}
          aria-invalid={problems.papers !== undefined}
          aria-describedby={describedBy(field("papers"), { hint: true, problem: problems.papers !== undefined })}
        />
      </Field>

      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={draft.listing} onChange={(event) => change({ listing: event.target.checked })} disabled={busy} />
        Look at the preprints bioRxiv posted in a period too
      </label>

      {draft.listing && (
        <div className="grid gap-4 sm:grid-cols-2" data-testid="triage-listing">
          <Field id={field("since")} label="From" hint="The first day." problem={problems.since}>
            <Input
              id={field("since")}
              type="date"
              value={draft.since}
              onChange={(event) => change({ since: event.target.value })}
              readOnly={busy}
              aria-invalid={problems.since !== undefined}
              aria-describedby={describedBy(field("since"), { hint: true, problem: problems.since !== undefined })}
            />
          </Field>
          <Field id={field("until")} label="To" hint="The last day. Blank is up to today." problem={problems.until}>
            <Input
              id={field("until")}
              type="date"
              value={draft.until}
              onChange={(event) => change({ until: event.target.value })}
              readOnly={busy}
              aria-invalid={problems.until !== undefined}
              aria-describedby={describedBy(field("until"), { hint: true, problem: problems.until !== undefined })}
            />
          </Field>
          <Field id={field("subject")} label="Subject">
            <NativeSelect id={field("subject")} value={draft.subject} onChange={(event) => change({ subject: event.target.value })} disabled={busy}>
              <option value="all">All subjects</option>
              {list.subjects.map((subject) => (
                <option key={subject} value={subject}>
                  {subject}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field id={field("limit")} label="How many preprints" hint={`The first that are listed, up to ${limits.most_listed}.`} problem={problems.limit}>
            <Input
              id={field("limit")}
              value={draft.limit}
              onChange={(event) => change({ limit: event.target.value })}
              inputMode="numeric"
              autoComplete="off"
              readOnly={busy}
              aria-invalid={problems.limit !== undefined}
              aria-describedby={describedBy(field("limit"), { hint: true, problem: problems.limit !== undefined })}
            />
          </Field>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id={field("looked")}
          label="Papers whose code is looked at"
          hint={`At most, up to ${limits.most_looked_at}, in the order they are given and listed. Each is a fetch of its code, and the rest are said to have been left.`}
          problem={problems.lookedAt}
        >
          <Input
            id={field("looked")}
            value={draft.lookedAt}
            onChange={(event) => change({ lookedAt: event.target.value })}
            inputMode="numeric"
            autoComplete="off"
            readOnly={busy}
            aria-invalid={problems.lookedAt !== undefined}
            aria-describedby={describedBy(field("looked"), { hint: true, problem: problems.lookedAt !== undefined })}
          />
        </Field>
        <Field
          id={field("megabytes")}
          label="Most fetched of one project, in MB"
          hint={`From ${limits.min_megabytes} to ${limits.max_megabytes}. A project larger than this is not looked at.`}
          problem={problems.megabytes}
        >
          <Input
            id={field("megabytes")}
            value={draft.megabytes}
            onChange={(event) => change({ megabytes: event.target.value })}
            inputMode="numeric"
            autoComplete="off"
            readOnly={busy}
            aria-invalid={problems.megabytes !== undefined}
            aria-describedby={describedBy(field("megabytes"), { hint: true, problem: problems.megabytes !== undefined })}
          />
        </Field>
      </div>

      {!list.git && <Notice tone="muted">Git is not installed on this machine, and fetching the code of the papers takes it.</Notice>}
      {full && (
        <p className="text-xs text-muted-foreground">
          No more than {limits.most_triages} triages can be kept. Delete one to begin another.
        </p>
      )}
      {problems.form && (
        <p role="alert" className="text-xs text-destructive">
          {problems.form}
        </p>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={busy || full || !list.git}>
          <ListOrdered />
          {busy ? "Beginning…" : "Begin the triage"}
        </Button>
      </div>
    </form>
  );
}

// The triages there are, and the beginning of one
export function Triages() {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const list = useTriagesList(report, triageKey(jobs.jobs, jobs.finished));

  return (
    <>
      <PageSection title="Triages" intro={INTRO}>
        <Looked state={list.value} label="Looking at the triages" failure="The triages could not be looked at." onRetry={list.reload}>
          {(value) => <TriageList triages={value.triages} />}
        </Looked>
      </PageSection>
      <PageSection title="Begin a triage">
        <Looked state={list.value} label="Looking at what a triage takes" failure="What a triage takes could not be looked at." onRetry={list.reload}>
          {(value) => <NewTriage list={value} />}
        </Looked>
      </PageSection>
    </>
  );
}
