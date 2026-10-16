"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Trash2 } from "lucide-react";
import { Looked } from "@/components/looked";
import { ProblemNotice } from "@/components/messages";
import { FunctionsSection } from "@/components/paper-functions";
import { Results, Shared } from "@/components/paper-findings";
import { PapersSection } from "@/components/paper-work";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { WorkStatus } from "@/components/work-status";
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
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { describeSource, lastJob, runFacts, workJob, workKey } from "@/lib/papers";
import type { PaperRun, PapersList } from "@/lib/types";
import { useAttempt, type Looked as LookedAt } from "@/lib/use-looked";
import { usePaperRun, usePapersList } from "@/lib/use-papers";
import type { JobsData } from "@/lib/use-jobs";

// A run, with its title and how far it has got, and the way to delete it
function RunHeader({ run, working }: { run: PaperRun; working: boolean }) {
  const { report } = useServer();
  const router = useRouter();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);

  async function remove() {
    const left = await attempt.run(() => api.deletePaperRun(run.id));
    if (left) router.push("/papers");
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="break-words text-lg font-semibold">{run.title}</h2>
          <p className="text-sm text-muted-foreground">{describeSource(run.source)}</p>
          <p className="text-sm text-muted-foreground">{runFacts(run)}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setAsking(true)}
          disabled={working || attempt.busy}
          aria-label={`Delete ${run.title}`}
        >
          <Trash2 />
          Delete
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {run.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This deletes the papers uploaded to it, what was found in them, and the functions that were written. Papers that are in a
              folder, or on bioRxiv, are left where they are.
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

function Run({
  run,
  list,
  jobs,
  onChanged,
}: {
  run: PaperRun;
  list: PapersList;
  jobs: JobsData;
  onChanged: LookedAt<PaperRun>["set"];
}) {
  const all = jobs.jobs ?? [];
  const job = workJob(all, run.id);
  const working = job !== undefined;

  return (
    <>
      <RunHeader run={run} working={working} />
      <WorkStatus job={job} last={lastJob(all, run.id)} jobs={jobs} />
      <PageSection title="Papers">
        <PapersSection run={run} list={list} working={working} onChanged={onChanged} jobs={jobs} />
      </PageSection>
      <PageSection title="What was read" intro="Each paper, and how many tasks, databases, and software the model found in it.">
        <Results run={run} />
      </PageSection>
      <PageSection
        title="What the papers share"
        intro="The tasks, databases, and software that are found in the most papers, which is what the functions are written for."
      >
        <Shared run={run} />
      </PageSection>
      <PageSection title="Functions">
        <FunctionsSection run={run} working={working} onChanged={onChanged} jobs={jobs} />
      </PageSection>
    </>
  );
}

// One run: its papers, what was read, what they share, and the functions written from it
export function RunPage({ id }: { id: string }) {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const again = workKey(jobs.jobs, jobs.finished, id);
  const run = usePaperRun(id, report, again);
  // What a run is made from is not changed by the work on it, so it is looked at again only when that has ended
  const list = usePapersList(report, String(jobs.finished));

  return (
    <>
      <Link
        href="/papers"
        className="inline-flex items-center gap-1 self-start rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        All runs
      </Link>
      <Looked state={run.value} label="Looking at the run" failure="The run could not be looked at." onRetry={run.reload}>
        {(value) => (
          <Looked
            state={list.value}
            label="Looking at what a run takes"
            failure="What a run takes could not be looked at."
            onRetry={list.reload}
          >
            {(limits) => <Run run={value} list={limits} jobs={jobs} onChanged={run.set} />}
          </Looked>
        )}
      </Looked>
    </>
  );
}
