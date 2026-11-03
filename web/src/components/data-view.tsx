"use client";

import { LakeTab } from "@/components/setup-lake";
import { OwnDataSection } from "@/components/own-data";
import { OwnSoftwareSection } from "@/components/own-software";
import { PageFrame } from "@/components/page-frame";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { SkillsSection } from "@/components/skills-section";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { describeError } from "@/lib/errors";
import { useOwn } from "@/lib/use-own";
import { useJobActions } from "@/lib/use-setup-actions";
import { useDataLake } from "@/lib/use-setup-data";
import { useSkills } from "@/lib/use-skills";
import type { Loaded } from "@/lib/use-settings-data";

const GIVEN_FAILED = "What you gave the lab could not be looked at.";

// What a part of the page that is made of what the person gave shows until it has been asked for
function Given<T>({
  given,
  label,
  failure,
  onRetry,
  children,
}: {
  given: Loaded<T>;
  label: string;
  // What is said when it could not be looked at
  failure: string;
  onRetry: () => void;
  children: (given: T) => React.ReactNode;
}) {
  if (given.kind === "loading") {
    return (
      <div className="flex flex-col gap-2" role="status" aria-busy="true" aria-label={label}>
        {[0, 1].map((row) => (
          <Skeleton key={row} className="h-16 w-full" />
        ))}
      </div>
    );
  }
  if (given.kind === "failed") {
    return (
      <div className="flex flex-col items-start gap-2">
        <p role="alert" className="text-sm text-destructive">
          {failure} {describeError(given.error)}
        </p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </div>
    );
  }

  return children(given.value);
}

// The data the lab can read: what the person gave it, the software they told it of, and Biomni's data lake
export function DataView() {
  const { report } = useServer();
  const { own, set, reload } = useOwn(report);
  const kept = useSkills(report);
  const jobs = useSetupJobs();
  const lake = useDataLake(jobs.finished);
  const { actions, problem } = useJobActions({ jobs, refreshData: lake.refresh, report });

  return (
    <PageFrame
      title="Data"
      intro="What the lab can read when it runs code. What you give it here is in every conversation you start from then on, and not in one that is already going."
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
        intro="Software you have that the code may use. The lab does not install it: it has to be where the code runs, which a conversation checks when its code first runs, and tells the lead if it is not."
      >
        <Given given={own} label="Looking at your software" failure={GIVEN_FAILED} onRetry={reload}>
          {(value) => <OwnSoftwareSection own={value} onChanged={set} />}
        </Given>
      </PageSection>

      <PageSection
        title="Skills"
        intro={
          <>
            Written guidance on how to do a kind of work, in the Agent Skills format that Claude Code and Codex read too. The
            lead is told what each skill is for, and reads one when a task calls for it. A conversation is given the skills
            that are on when you start it.
          </>
        }
      >
        <Given given={kept.skills} label="Looking at the skills" failure="The skills could not be looked at." onRetry={kept.reload}>
          {(value) => <SkillsSection skills={value} onChanged={kept.set} />}
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
