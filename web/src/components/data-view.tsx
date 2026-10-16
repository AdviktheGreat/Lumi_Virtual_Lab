"use client";

import { useId } from "react";
import { LakeTab } from "@/components/setup-lake";
import { OwnDataSection } from "@/components/own-data";
import { OwnSoftwareSection } from "@/components/own-software";
import { PageHeader } from "@/components/page-header";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { describeError } from "@/lib/errors";
import { useOwn } from "@/lib/use-own";
import { useJobActions } from "@/lib/use-setup-actions";
import { useDataLake } from "@/lib/use-setup-data";
import type { Own } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

function PageSection({ title, intro, children }: { title: string; intro?: React.ReactNode; children: React.ReactNode }) {
  const id = useId();

  return (
    <section aria-labelledby={id} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id={id} className="text-base font-semibold">
          {title}
        </h2>
        {intro && <p className="text-sm text-muted-foreground">{intro}</p>}
      </div>
      {children}
    </section>
  );
}

// What a part of the page that is made of what the person gave shows until it has been asked for
function Given({
  own,
  label,
  onRetry,
  children,
}: {
  own: Loaded<Own>;
  label: string;
  onRetry: () => void;
  children: (own: Own) => React.ReactNode;
}) {
  if (own.kind === "loading") {
    return (
      <div className="flex flex-col gap-2" role="status" aria-busy="true" aria-label={label}>
        {[0, 1].map((row) => (
          <Skeleton key={row} className="h-16 w-full" />
        ))}
      </div>
    );
  }
  if (own.kind === "failed") {
    return (
      <div className="flex flex-col items-start gap-2">
        <p role="alert" className="text-sm text-destructive">
          What you gave the lab could not be looked at. {describeError(own.error)}
        </p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </div>
    );
  }

  return children(own.value);
}

// The data the lab can read: what the person gave it, the software they told it of, and Biomni's data lake
export function DataView() {
  const { report } = useServer();
  const { own, set, reload } = useOwn(report);
  const jobs = useSetupJobs();
  const lake = useDataLake(jobs.finished);
  const { actions, problem } = useJobActions({ jobs, refreshData: lake.refresh, report });

  return (
    <>
      <PageHeader>
        <h1 className="min-w-0 flex-1 truncate text-sm font-medium">Data</h1>
      </PageHeader>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-10 px-4 py-8">
          <p className="text-sm text-muted-foreground">
            What the lab can read when it runs code. What you give it here is in every conversation you start from then
            on, and not in one that is already going.
          </p>

          <PageSection
            title="Your data"
            intro={
              <>
                Files and folders of yours. The lead is told what each is, and code can read them: in Docker they are in{" "}
                <code>/data</code>, and code that runs on this machine is given where they are.
              </>
            }
          >
            <Given own={own} label="Looking at your data" onRetry={reload}>
              {(value) => <OwnDataSection own={value} onChanged={set} />}
            </Given>
          </PageSection>

          <PageSection
            title="Your software"
            intro="Software you have that the code may use. The lab does not install it: it has to be where the code runs, which a conversation checks when its code first runs, and tells the lead if it is not."
          >
            <Given own={own} label="Looking at your software" onRetry={reload}>
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
        </div>
      </div>
    </>
  );
}
