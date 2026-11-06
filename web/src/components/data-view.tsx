"use client";

import { Given } from "@/components/given";
import { LakeTab } from "@/components/setup-lake";
import { OwnDataSection } from "@/components/own-data";
import { OwnSoftwareSection } from "@/components/own-software";
import { PageFrame } from "@/components/page-frame";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { useOwn } from "@/lib/use-own";
import { useJobActions } from "@/lib/use-setup-actions";
import { useDataLake } from "@/lib/use-setup-data";

const GIVEN_FAILED = "What you gave the lab could not be looked at.";

// The data the lab can read: what the person gave it, the software they told it of, and Biomni's data lake
export function DataView() {
  const { report } = useServer();
  const { own, set, reload } = useOwn(report);
  const jobs = useSetupJobs();
  const lake = useDataLake(jobs.finished);
  const { actions, problem } = useJobActions({ jobs, refreshData: lake.refresh, report });

  return (
    <PageFrame
      title="Data"
      intro="What the lab can read when it runs code. What you give it here is in every program you start from then on, and not in one that is already going."
    >
      <PageSection
        title="Your data"
        intro={
          <>
            Files and folders of yours. The lead is told what each is, and code can read them: in Docker they are in{" "}
            <code>/data</code>, and code that runs on this machine is given where they are.
          </>
        }
      >
        <Given given={own} label="Looking at your data" failure={GIVEN_FAILED} onRetry={reload}>
          {(value) => <OwnDataSection own={value} onChanged={set} />}
        </Given>
      </PageSection>

      <PageSection
        title="Your software"
        intro="Software you have that the code may use. The lab does not install it: it has to be where the code runs, which a program checks when its code first runs, and tells the lead if it is not."
      >
        <Given given={own} label="Looking at your software" failure={GIVEN_FAILED} onRetry={reload}>
          {(value) => <OwnSoftwareSection own={value} onChanged={set} />}
        </Given>
      </PageSection>

      <PageSection title="Biomni's data lake">
        <LakeTab lake={lake.lake} jobs={jobs.jobs ?? []} actions={actions} onRetry={lake.refresh} />
        {problem && (
          <p role="alert" className="text-sm text-destructive">
            {problem}
          </p>
        )}
      </PageSection>
    </PageFrame>
  );
}
