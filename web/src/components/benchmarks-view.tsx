"use client";

import { useSearchParams } from "next/navigation";
import { FilesCard } from "@/components/benchmark-files";
import { RunPage } from "@/components/benchmark-run";
import { NewRun, RunList } from "@/components/benchmark-runs";
import { Looked } from "@/components/looked";
import { PageHeader } from "@/components/page-header";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { benchmarkKey } from "@/lib/benchmarks";
import { useBenchmarksList } from "@/lib/use-benchmarks";

// The runs there are, and the making of one
function Runs() {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const list = useBenchmarksList(report, benchmarkKey(jobs.jobs, jobs.finished));

  return (
    <>
      <p className="text-sm text-muted-foreground">
        Biomni is scored on questions that have right answers, so that the lab can be scored on the same ones. A run puts a benchmark&apos;s
        questions to the lead alone, or to the lead and the team, and scores the answers by the benchmark&apos;s own rules. Answering
        spends money on the model in the settings, so each run is told the most it may spend.
      </p>
      <PageSection title="The benchmarks' files">
        <Looked state={list.value} label="Looking at the files" failure="The files could not be looked at." onRetry={list.reload}>
          {(value) => <FilesCard list={value} onChanged={list.set} />}
        </Looked>
      </PageSection>
      <PageSection title="Runs">
        <Looked state={list.value} label="Looking at the runs" failure="The runs could not be looked at." onRetry={list.reload}>
          {(value) => <RunList list={value} />}
        </Looked>
      </PageSection>
      <PageSection title="Make a run">
        <Looked state={list.value} label="Looking at what a run takes" failure="What a run takes could not be looked at." onRetry={list.reload}>
          {(value) => <NewRun list={value} />}
        </Looked>
      </PageSection>
    </>
  );
}

// The page of benchmarks: the runs, or one run, which is named in the address's query as a conversation is
export function BenchmarksView() {
  const id = useSearchParams().get("id");

  return (
    <>
      <PageHeader>
        <h1 className="min-w-0 flex-1 truncate text-sm font-medium">Benchmarks</h1>
      </PageHeader>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-10 px-4 py-8">
          {id ? <RunPage key={id} id={id} /> : <Runs />}
        </div>
      </div>
    </>
  );
}
