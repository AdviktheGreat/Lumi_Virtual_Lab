"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Trash2 } from "lucide-react";
import { Looked } from "@/components/looked";
import { Notice, ProblemNotice } from "@/components/messages";
import { PageSection } from "@/components/page-section";
import { BakeoffFields } from "@/components/paper-bakeoff-fields";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
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
import {
  bakeoffKey,
  BAKEOFFS_ADDRESS,
  checkChange,
  describeLabels,
  describeLeft,
  describeMethods,
  describeScope,
  describeSpending,
  draftOf,
  isNoChange,
} from "@/lib/bakeoffs";
import { formatBytes } from "@/lib/files";
import { timeAgo } from "@/lib/format";
import type { Bakeoff, BakeoffsList } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";
import { useBakeoff, useBakeoffsList } from "@/lib/use-bakeoffs";
import type { Looked as LookedAt } from "@/lib/use-looked";

// What is wrong with something that a bake-off was told, which is set apart from what is not
const WARNING = "rounded-md border border-warning/60 bg-warning/15 px-1.5 py-0.5 text-foreground";

// A bake-off, with what it is called and what it is for, and the way to delete it. It may not be changed or deleted while its
// methods are being found, built, or run, which the server would refuse.
function BakeoffHeader({ bakeoff }: { bakeoff: Bakeoff }) {
  const { report } = useServer();
  const router = useRouter();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);

  async function remove() {
    const left = await attempt.run(() => api.deleteBakeoff(bakeoff.id));
    if (left) router.push(BAKEOFFS_ADDRESS);
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="break-words font-serif text-2xl font-medium tracking-tight">{bakeoff.title}</h2>
          <p className="text-sm text-muted-foreground">
            {describeMethods(bakeoff.candidates.length)}. Made {timeAgo(bakeoff.created_at)}.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setAsking(true)}
          disabled={bakeoff.job !== null || attempt.busy}
          aria-label={`Delete ${bakeoff.title}`}
        >
          <Trash2 />
          Delete
        </Button>
      </div>
      {bakeoff.job !== null && (
        <div className="flex flex-wrap items-center gap-2" data-testid="bakeoff-job">
          <Badge variant="secondary">{bakeoff.job.title}</Badge>
          <span className="text-xs text-muted-foreground">{bakeoff.job.message}</span>
        </div>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {bakeoff.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This deletes the bake-off, with what was kept of running its methods. The PaperAgents that were made for its methods stay,
              as they are of their papers, and so does your data.
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

// What the bake-off is for, which data it is run on and what that is, where the right answers are and whether they can be used now,
// and what has been spent
function Summary({ bakeoff }: { bakeoff: Bakeoff }) {
  const scope = describeScope(bakeoff.described);
  const data = bakeoff.data;
  const labels = bakeoff.labels;

  return (
    <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_minmax(0,1fr)]" data-testid="bakeoff-summary">
      <dt className="text-muted-foreground">What you want done</dt>
      <dd className="whitespace-pre-wrap break-words">{bakeoff.task}</dd>
      <dt className="text-muted-foreground">Your data</dt>
      <dd className="break-words" data-testid="bakeoff-data">
        {data === null ? (
          "Not said yet"
        ) : data.missing ? (
          <>
            {data.own}. <span className={WARNING}>It is not where the Data page says it is, so the methods cannot be run on it.</span>
          </>
        ) : (
          <>
            {data.own}
            {data.kind === "folder" ? ", a folder" : data.bytes !== undefined ? `, ${formatBytes(data.bytes)}` : ""}
          </>
        )}
      </dd>
      <dt className="text-muted-foreground">What your data is</dt>
      <dd data-testid="bakeoff-described">
        {scope.length === 0 ? (
          "Not said, so no method is warned of being used on data unlike what it was tested on."
        ) : (
          <ul className="flex flex-col gap-0.5">
            {scope.map((line) => (
              <li key={line.label}>
                {line.label}: {line.value}
              </li>
            ))}
          </ul>
        )}
      </dd>
      <dt className="text-muted-foreground">Right answers</dt>
      <dd className="flex flex-col gap-1" data-testid="bakeoff-labels">
        {labels === null ? (
          <span>None, so the methods are compared with each other and are not ranked.</span>
        ) : (
          <>
            <span className="break-words">{describeLabels(labels)}</span>
            {!labels.ok && (
              <span className={WARNING} data-testid="bakeoff-labels-problem">
                {labels.problem}. The methods are not scored by them until that is put right.
              </span>
            )}
            <span className="text-xs text-muted-foreground">{labels.says}</span>
          </>
        )}
      </dd>
      <dt className="text-muted-foreground">Spending</dt>
      <dd data-testid="bakeoff-spending">
        <span>{describeSpending(bakeoff)}.</span> <span className="text-muted-foreground">{describeLeft(bakeoff)}</span>
      </dd>
    </dl>
  );
}

// Says again what the bake-off is for, which data it is run on, what that is, where the right answers are, and what it may spend.
// Only what differs is sent.
function ChangeForm({ bakeoff, list, onChanged }: { bakeoff: Bakeoff; list: BakeoffsList; onChanged: LookedAt<Bakeoff>["set"] }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [draft, setDraft] = useState(() => draftOf(bakeoff));
  const [tried, setTried] = useState(false);
  const checked = checkChange(draft, bakeoff);
  const problems = tried ? checked.problems : {};
  const unchanged = checked.value !== null && isNoChange(checked.value);
  const busy = attempt.busy || bakeoff.job !== null;

  async function save() {
    setTried(true);
    const change = checked.value;
    if (change === null || isNoChange(change)) return;
    const next = await attempt.run(() => api.changeBakeoff(bakeoff.id, change));
    if (next) {
      onChanged(next);
      setTried(false);
    }
  }

  return (
    <form
      aria-label="Change the bake-off"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <BakeoffFields
        draft={draft}
        change={(part) => setDraft((was) => ({ ...was, ...part }))}
        problems={problems}
        busy={busy}
        own={list.own}
        limits={bakeoff.limits}
        field={(name) => `${id}-${name}`}
        settingsModel={bakeoff.settings_model}
      />
      {bakeoff.job !== null && <Notice tone="muted">It cannot be changed while its methods are being found, built, or run. Stop that first.</Notice>}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={busy || unchanged}>
          {attempt.busy ? "Saving…" : "Save the changes"}
        </Button>
      </div>
    </form>
  );
}

function BakeoffBody({ bakeoff, list, onChanged }: { bakeoff: Bakeoff; list: BakeoffsList; onChanged: LookedAt<Bakeoff>["set"] }) {
  return (
    <div className="flex flex-col gap-10">
      <BakeoffHeader bakeoff={bakeoff} />
      <PageSection title="What it is">
        <Summary bakeoff={bakeoff} />
      </PageSection>
      <PageSection title="Change it" intro="Only what you change is said again. The limit cannot be less than what has been spent.">
        {/* The form is made again when what the bake-off is changes, so that it shows what it is and not what was typed before */}
        <ChangeForm key={JSON.stringify(draftOf(bakeoff))} bakeoff={bakeoff} list={list} onChanged={onChanged} />
      </PageSection>
    </div>
  );
}

// One bake-off
export function BakeoffPage({ id }: { id: string }) {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const again = bakeoffKey(jobs.jobs, jobs.finished, id);
  const bakeoff = useBakeoff(id, report, again);
  const list = useBakeoffsList(report, again);

  return (
    <>
      <Link
        href={BAKEOFFS_ADDRESS}
        className="inline-flex items-center gap-1 self-start rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        All bake-offs
      </Link>
      <Looked state={bakeoff.value} label="Looking at the bake-off" failure="The bake-off could not be looked at." onRetry={bakeoff.reload}>
        {(value) => (
          <Looked state={list.value} label="Looking at what a bake-off takes" failure="What a bake-off takes could not be looked at." onRetry={list.reload}>
            {(limits) => <BakeoffBody bakeoff={value} list={limits} onChanged={bakeoff.set} />}
          </Looked>
        )}
      </Looked>
    </>
  );
}
