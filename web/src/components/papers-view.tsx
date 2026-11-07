"use client";

import { useSearchParams } from "next/navigation";
import { Looked } from "@/components/looked";
import { Agents, PaperAgentsNav } from "@/components/paper-agents";
import { NewRun, RunList } from "@/components/paper-runs";
import { RunPage } from "@/components/paper-run";
import { PageFrame } from "@/components/page-frame";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { paperView, workKey } from "@/lib/papers";
import { usePapersList } from "@/lib/use-papers";

const INTRO =
  "A PaperAgent makes one paper, with the code that came with it, into something the lab can use. A survey reads many papers for what they have in common.";

const SURVEYS_INTRO =
  "A survey reads papers for the tasks, databases, and software they use, and writes functions for the tasks that many of them share. Each run is a set of papers, with what was read from them. Reading spends money on the model in the settings, so each run is told the most it may spend.";

// The runs there are, and the making of one
function Runs() {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const list = usePapersList(report, workKey(jobs.jobs, jobs.finished));

  return (
    <>
      <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{SURVEYS_INTRO}</p>
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

// The page of PaperAgents: its agents, or its surveys, or one survey, which is named in the address's query as a
// conversation is
export function PapersView() {
  const params = useSearchParams();
  const id = params.get("id");

  if (id) {
    return (
      <PageFrame title="Surveys">
        <RunPage key={id} id={id} />
      </PageFrame>
    );
  }

  const view = paperView(params.get("view"));

  return (
    <PageFrame title="PaperAgents" intro={INTRO}>
      <PaperAgentsNav view={view} />
      {view === "surveys" ? <Runs /> : <Agents />}
    </PageFrame>
  );
}
