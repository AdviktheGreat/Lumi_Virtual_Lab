"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Looked } from "@/components/looked";
import { ProblemNotice } from "@/components/messages";
import { BakeoffFields } from "@/components/paper-bakeoff-fields";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import {
  bakeoffAddress,
  bakeoffKey,
  checkBakeoff,
  describeMethods,
  describeSpending,
  EMPTY_BAKEOFF,
  type BakeoffDraft,
} from "@/lib/bakeoffs";
import { timeAgo } from "@/lib/format";
import type { BakeoffsList, BakeoffSummary } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";
import { useBakeoffsList } from "@/lib/use-bakeoffs";

const INTRO =
  "A bake-off asks which method of the literature is best for a task on your own data. You say what you want done and point to your data, the methods are found and built from their papers, each is run on your data, and they are put side by side: whether they agree, how long they took, what they cost, and which could not be built or run, and why. If you have the right answers, they are scored and ranked by them. One limit on spending is for the whole of it.";

function BakeoffRow({ bakeoff }: { bakeoff: BakeoffSummary }) {
  return (
    <li className="flex flex-col gap-1.5 rounded-xl border border-border bg-card p-4 transition-colors hover:border-ring/50" data-testid="bakeoff">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="min-w-0 break-words text-sm font-medium">
          <Link href={bakeoffAddress(bakeoff.id)} className="rounded-sm outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
            {bakeoff.title}
          </Link>
        </h3>
        {bakeoff.job !== null && <Badge variant="secondary">{bakeoff.job.title}</Badge>}
      </div>
      <p className="line-clamp-2 break-words text-xs text-muted-foreground">{bakeoff.task}</p>
      <p className="text-xs text-muted-foreground">
        {describeMethods(bakeoff.candidates)}. {describeSpending(bakeoff)}. Made {timeAgo(bakeoff.created_at)}.
      </p>
    </li>
  );
}

// The bake-offs there are, the latest first
function BakeoffList({ bakeoffs }: { bakeoffs: readonly BakeoffSummary[] }) {
  if (bakeoffs.length === 0) {
    return (
      <div className="flex flex-col gap-1 rounded-xl border border-dashed border-border p-5" data-testid="bakeoffs-empty">
        <p className="text-sm font-medium">There are no bake-offs yet</p>
        <p className="text-sm text-muted-foreground">Make one below.</p>
      </div>
    );
  }

  return (
    <ul aria-label="Bake-offs" className="flex flex-col gap-2">
      {bakeoffs.map((bakeoff) => (
        <BakeoffRow key={bakeoff.id} bakeoff={bakeoff} />
      ))}
    </ul>
  );
}

// Makes a bake-off, with no methods in it yet. They are put in its own page.
function NewBakeoff({ list }: { list: BakeoffsList }) {
  const { report } = useServer();
  const router = useRouter();
  const id = useId();
  const [draft, setDraft] = useState<BakeoffDraft>(EMPTY_BAKEOFF);
  const [tried, setTried] = useState(false);
  const attempt = useAttempt(report);
  const checked = checkBakeoff(draft, list.limits);
  const problems = tried ? checked.problems : {};
  const full = list.bakeoffs.length >= list.limits.max_bakeoffs;

  async function make() {
    setTried(true);
    const body = checked.value;
    if (body === null) return;
    const bakeoff = await attempt.run(() => api.makeBakeoff(body));
    if (bakeoff) router.push(bakeoffAddress(bakeoff.id));
  }

  return (
    <form
      aria-label="Make a bake-off"
      onSubmit={(event) => {
        event.preventDefault();
        void make();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <BakeoffFields
        draft={draft}
        change={(part) => setDraft((was) => ({ ...was, ...part }))}
        problems={problems}
        busy={attempt.busy}
        own={list.own}
        limits={list.limits}
        field={(name) => `${id}-${name}`}
        settingsModel={list.settings_model}
      />
      {full && (
        <p className="text-xs text-muted-foreground">
          No more than {list.limits.max_bakeoffs} bake-offs can be kept. Delete one to make another.
        </p>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={attempt.busy || full}>
          <Plus />
          {attempt.busy ? "Making…" : "Make the bake-off"}
        </Button>
      </div>
    </form>
  );
}

// The bake-offs there are, and the making of one
export function Bakeoffs() {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const list = useBakeoffsList(report, bakeoffKey(jobs.jobs, jobs.finished));

  return (
    <>
      <PageSection title="Bake-offs" intro={INTRO}>
        <Looked state={list.value} label="Looking at the bake-offs" failure="The bake-offs could not be looked at." onRetry={list.reload}>
          {(value) => <BakeoffList bakeoffs={value.bakeoffs} />}
        </Looked>
      </PageSection>
      <PageSection title="Make a bake-off">
        <Looked state={list.value} label="Looking at what a bake-off takes" failure="What a bake-off takes could not be looked at." onRetry={list.reload}>
          {(value) => <NewBakeoff list={value} />}
        </Looked>
      </PageSection>
    </>
  );
}
