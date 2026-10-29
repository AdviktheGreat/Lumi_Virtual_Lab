"use client";

import { useSearchParams } from "next/navigation";
import { FilesCard } from "@/components/benchmark-files";
import { RunPage } from "@/components/benchmark-run";
import { NewRun, RunList } from "@/components/benchmark-runs";
import { Looked } from "@/components/looked";
import { PageFrame } from "@/components/page-frame";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { benchmarkKey } from "@/lib/benchmarks";
import { useBenchmarksList } from "@/lib/use-benchmarks";

const INTRO =
  "Biomni is scored on questions that have right answers, so that the lab can be scored on the same ones. A run puts a benchmark's questions to the lead alone, or to the lead and the team, and scores the answers by the benchmark's own rules. Answering spends money on the model in the settings, so each run is told the most it may spend.";

// The runs there are, and the making of one
function Runs() {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const list = useBenchmarksList(report, benchmarkKey(jobs.jobs, jobs.finished));

  return (
    <>
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

  if (id) {
    return (
      <PageFrame title="Benchmarks">
        <RunPage key={id} id={id} />
      </PageFrame>
    );
  }

  return (
    <PageFrame title="Benchmarks" intro={INTRO}>
      <Runs />
    </PageFrame>
  );
}
