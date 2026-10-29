"use client";

import { useSearchParams } from "next/navigation";
import { Looked } from "@/components/looked";
import { NewRun, RunList } from "@/components/paper-runs";
import { RunPage } from "@/components/paper-run";
import { PageFrame } from "@/components/page-frame";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { workKey } from "@/lib/papers";
import { usePapersList } from "@/lib/use-papers";

const INTRO =
  "The lab reads papers for the tasks, databases, and software they use, and writes functions for the tasks that many of them share. Each run is a set of papers, with what was read from them. Reading spends money on the model in the settings, so each run is told the most it may spend.";

// The runs there are, and the making of one
function Runs() {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const list = usePapersList(report, workKey(jobs.jobs, jobs.finished));

  return (
    <>
      <PageSection title="Runs">
        <Looked state={list.value} label="Looking at the runs" failure="The runs could not be looked at." onRetry={list.reload}>
          {(value) => <RunList runs={value.runs} />}
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

// The page of papers: the runs, or one run, which is named in the address's query as a conversation is
export function PapersView() {
  const id = useSearchParams().get("id");

  if (id) {
    return (
      <PageFrame title="Papers">
        <RunPage key={id} id={id} />
      </PageFrame>
    );
  }

  return (
    <PageFrame title="Papers" intro={INTRO}>
      <Runs />
    </PageFrame>
  );
}
