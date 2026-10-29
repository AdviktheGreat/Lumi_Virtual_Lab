"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Trash2 } from "lucide-react";
import { Questions, Scores } from "@/components/benchmark-results";
import { StartForm } from "@/components/benchmark-work";
import { Looked } from "@/components/looked";
import { ProblemNotice } from "@/components/messages";
import { PageSection } from "@/components/page-section";
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
import { Button } from "@/components/ui/button";
import { WorkStatus } from "@/components/work-status";
import { api } from "@/lib/api";
import { sentence } from "@/lib/checks";
import {
  benchmarkJob,
  benchmarkKey,
  describeCode,
  describeNarrowing,
  describeSolver,
  lastBenchmarkJob,
  runFacts,
} from "@/lib/benchmarks";
import type { BenchmarkRun } from "@/lib/types";
import { useBenchmarkRun, useBenchmarksList } from "@/lib/use-benchmarks";
import { useAttempt } from "@/lib/use-looked";
import type { JobsData } from "@/lib/use-jobs";

// A run, with its title, who answers it, and how far it has got, and the way to delete it
function RunHeader({ run, benchmark, working }: { run: BenchmarkRun; benchmark: string; working: boolean }) {
  const { report } = useServer();
  const router = useRouter();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);
  const narrowing = describeNarrowing(run.benchmark, run.options, run.limit);

  async function remove() {
    const left = await attempt.run(() => api.deleteBenchmarkRun(run.id));
    if (left) router.push("/benchmarks");
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="break-words font-serif text-2xl font-medium tracking-tight">{run.title}</h2>
          <p className="text-sm text-muted-foreground">
            {benchmark}
            {narrowing.length > 0 && ` · ${narrowing.join(" · ")}`}
          </p>
          <p className="text-sm text-muted-foreground">{describeSolver(run)}</p>
          {run.solver === "team" && run.team.length > 0 && (
            <p className="break-words text-sm text-muted-foreground">
              Led by {run.lead ?? "the lead"}, with {run.team.join(", ")}
            </p>
          )}
          <p className="text-sm text-muted-foreground">{sentence(describeCode(run.code))}</p>
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
      {run.problem && (
        <p role="alert" className="break-words text-sm text-destructive">
          {run.problem}.
        </p>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {run.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This deletes how each question was answered, and what was said in answering it. The files of the benchmarks are left where
              they are.
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

function Run({ run, benchmark, jobs }: { run: BenchmarkRun; benchmark: string; jobs: JobsData }) {
  const all = jobs.jobs ?? [];
  const job = benchmarkJob(all, run.id);
  const working = job !== undefined;

  return (
    <>
      <RunHeader run={run} benchmark={benchmark} working={working} />
      <WorkStatus job={job} last={lastBenchmarkJob(all, run.id)} jobs={jobs} />
      <PageSection title="Answer the questions">
        <StartForm run={run} working={working} jobs={jobs} />
      </PageSection>
      <PageSection title="Scores" intro="How right the answers were, by the rule of the benchmark.">
        <Scores run={run} />
      </PageSection>
      <PageSection title="Questions" intro="Each question, and how it was answered. Open one to read what was asked and what was said.">
        <Questions run={run} />
      </PageSection>
    </>
  );
}

// One run: the questions it asks, how they were answered, and how right the answers were
export function RunPage({ id }: { id: string }) {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const run = useBenchmarkRun(id, report, benchmarkKey(jobs.jobs, jobs.finished, id));
  // What the benchmarks are called does not change with the work on a run
  const list = useBenchmarksList(report, String(jobs.finished));

  return (
    <>
      <Link
        href="/benchmarks"
        className="inline-flex items-center gap-1 self-start rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        All runs
      </Link>
      <Looked state={run.value} label="Looking at the run" failure="The run could not be looked at." onRetry={run.reload}>
        {(value) => (
          <Looked
            state={list.value}
            label="Looking at the benchmarks"
            failure="The benchmarks could not be looked at."
            onRetry={list.reload}
          >
            {(benchmarks) => (
              <Run
                run={value}
                benchmark={benchmarks.benchmarks.find((candidate) => candidate.id === value.benchmark)?.title ?? value.benchmark}
                jobs={jobs}
              />
            )}
          </Looked>
        )}
      </Looked>
    </>
  );
}
