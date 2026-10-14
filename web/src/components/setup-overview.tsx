"use client";

import { Check, CircleDashed, Loader2, Lock } from "lucide-react";
import { Aside, Section } from "@/components/settings-fields";
import { JobProgress, StopButton, type SetupActions } from "@/components/setup-job";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { describeError } from "@/lib/errors";
import { activeJob, latestJob, stageLabel, stepLabel, stepsLeft } from "@/lib/setup";
import type { ImageStage, Images, Job, SetupStatus, SetupStep, StepState } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

const ICONS: Record<StepState, React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>> = {
  done: Check,
  todo: CircleDashed,
  running: Loader2,
  blocked: Lock,
};

function StepIcon({ state }: { state: StepState }) {
  const Icon = ICONS[state] ?? CircleDashed;
  const tone = state === "done" ? "bg-success/15 text-success" : "bg-muted text-muted-foreground";

  return (
    <span className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full ${tone}`}>
      <Icon aria-hidden className={`size-3.5 ${state === "running" ? "animate-spin motion-reduce:animate-none" : ""}`} />
      <span className="sr-only">{stepLabel(state)}:</span>
    </span>
  );
}

// Whether a stage is built is not known while Docker is not running, which is what the server says by null
function StageBadge({ stage }: { stage: ImageStage }) {
  if (stage.building) return <Badge variant="secondary">Building</Badge>;
  if (stage.built) return <Badge variant="secondary">Built</Badge>;
  if (stage.built === null) return <Badge variant="outline">Needs Docker</Badge>;

  return <Badge variant="outline">Not built</Badge>;
}

function Stage({
  stage,
  jobs,
  chosen,
  actions,
}: {
  stage: ImageStage;
  jobs: readonly Job[];
  chosen: boolean;
  actions: SetupActions;
}) {
  const building = activeJob(jobs, "image", stage.target);
  const another = activeJob(jobs, "image") !== undefined;
  const failed = latestJob(jobs, "image", stage.target);
  const label = stageLabel(stage.target);
  const canBuild = stage.built === false && !building;

  return (
    <li aria-label={label} className="flex flex-col gap-2 rounded-lg bg-muted/40 p-2.5">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-medium">{label}</h4>
            <StageBadge stage={{ ...stage, building: stage.building || building !== undefined }} />
            {chosen && <Badge variant="outline">Chosen in the settings</Badge>}
          </div>
          <p className="text-xs text-muted-foreground">
            {stage.summary}. Takes {stage.estimate} to build.
          </p>
        </div>
        {canBuild && (
          <Button
            variant="outline"
            size="xs"
            onClick={() => actions.build(stage.target)}
            disabled={another || actions.busy}
            aria-label={`Build ${label}`}
            title={another ? "Another stage is being built" : undefined}
          >
            Build
          </Button>
        )}
        {building && <StopButton job={building} actions={actions} />}
      </div>
      {building && (
        <>
          <JobProgress job={building} />
          <Button variant="link" size="xs" className="h-auto self-start p-0" onClick={() => actions.showLog(building)}>
            Show what it prints
          </Button>
        </>
      )}
      {!building && failed?.state === "failed" && !stage.built && (
        <div className="flex flex-col items-start gap-1">
          <p role="alert" className="break-words text-xs text-destructive">
            The last build failed: {failed.error}
          </p>
          <Button variant="link" size="xs" className="h-auto p-0" onClick={() => actions.showLog(failed)}>
            Show what it printed
          </Button>
        </div>
      )}
    </li>
  );
}

function Stages({
  images,
  jobs,
  sandbox,
  actions,
}: {
  images: Images;
  jobs: readonly Job[];
  sandbox: string;
  actions: SetupActions;
}) {
  return (
    <div className="flex flex-col gap-2">
      {images.emulated && (
        <Aside tone="warning">
          This computer is not an {images.platform.replace("linux/", "")} machine, so Docker runs the image by pretending to be
          one ({images.platform}). Building and running are several times slower that way.
        </Aside>
      )}
      <ul aria-label="Stages of the image" className="flex flex-col gap-2">
        {images.stages.map((stage) => (
          <Stage key={stage.target} stage={stage} jobs={jobs} chosen={stage.target === sandbox} actions={actions} />
        ))}
      </ul>
    </div>
  );
}

function StepRow({
  step,
  action,
  children,
}: {
  step: SetupStep;
  action?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <li aria-label={step.title} className="flex flex-col gap-2.5 rounded-lg border border-border p-3">
      <div className="flex items-start gap-2.5">
        <StepIcon state={step.state} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium">{step.title}</h3>
            {!step.required && <Badge variant="outline">Optional</Badge>}
          </div>
          <p className="break-words text-xs text-muted-foreground">{step.detail}</p>
        </div>
        {action}
      </div>
      {children}
    </li>
  );
}

function Steps({
  status,
  jobs,
  sandbox,
  actions,
  asking,
  onCheck,
  onOpenLake,
  onAddKey,
}: {
  status: SetupStatus;
  jobs: readonly Job[];
  sandbox: string;
  actions: SetupActions;
  asking: boolean;
  onCheck: () => void;
  onOpenLake: () => void;
  onAddKey: () => void;
}) {
  const left = stepsLeft(status.steps).length;
  const fetching = activeJob(jobs, "data_lake");

  return (
    <>
      <p role="status" className="text-sm">
        {left === 0
          ? "Everything code needs is ready."
          : `${left === 1 ? "One thing is" : `${left} things are`} left before code can run in Docker.`}
      </p>
      <ol aria-label="What there is to set up" className="flex flex-col gap-2.5">
        {status.steps.map((step) => {
          if (step.id === "docker") {
            return (
              <StepRow
                key={step.id}
                step={step}
                action={
                  step.state !== "done" && (
                    <Button variant="outline" size="xs" onClick={onCheck} disabled={asking}>
                      {asking ? "Checking…" : "Check again"}
                    </Button>
                  )
                }
              />
            );
          }
          if (step.id === "image") {
            return (
              <StepRow key={step.id} step={step}>
                <Stages images={status.images} jobs={jobs} sandbox={sandbox} actions={actions} />
              </StepRow>
            );
          }
          if (step.id === "data_lake") {
            return (
              <StepRow
                key={step.id}
                step={step}
                action={
                  <Button variant="outline" size="xs" onClick={onOpenLake}>
                    {step.state === "done" ? "See the files" : "Choose files"}
                  </Button>
                }
              >
                {fetching && (
                  <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <JobProgress job={fetching} />
                    </div>
                    <StopButton job={fetching} actions={actions} />
                  </div>
                )}
              </StepRow>
            );
          }
          if (step.id === "model_key") {
            return (
              <StepRow
                key={step.id}
                step={step}
                action={
                  step.state !== "done" && (
                    <Button variant="outline" size="xs" onClick={onAddKey}>
                      Add the key
                    </Button>
                  )
                }
              />
            );
          }

          return <StepRow key={step.id} step={step} />;
        })}
      </ol>
    </>
  );
}

// What there is to do to be ready to run code in Docker, and the doing of it
export function OverviewTab({
  status,
  jobs,
  sandbox,
  actions,
  asking,
  onCheck,
  onOpenLake,
  onAddKey,
}: {
  status: Loaded<SetupStatus>;
  jobs: readonly Job[];
  // The stage of the image the settings choose
  sandbox: string;
  actions: SetupActions;
  asking: boolean;
  onCheck: () => void;
  onOpenLake: () => void;
  onAddKey: () => void;
}) {
  return (
    <Section>
      <p className="text-sm text-muted-foreground">
        Code the lab writes runs in Docker, which keeps it from changing your files. It needs Docker, an environment built from
        Biomni&apos;s, and a key for the model. Biomni&apos;s data lake is not needed, but some of its tools use it.
      </p>
      {status.kind === "loading" && (
        <div className="flex flex-col gap-2.5" role="status" aria-busy="true" aria-label="Looking at what is set up">
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} className="h-16 w-full" />
          ))}
        </div>
      )}
      {status.kind === "failed" && (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-sm text-destructive">
            What is set up could not be looked at. {describeError(status.error)}
          </p>
          <Button variant="outline" size="sm" onClick={onCheck} disabled={asking}>
            Try again
          </Button>
        </div>
      )}
      {status.kind === "ready" && (
        <Steps
          status={status.value}
          jobs={jobs}
          sandbox={sandbox}
          actions={actions}
          asking={asking}
          onCheck={onCheck}
          onOpenLake={onOpenLake}
          onAddKey={onAddKey}
        />
      )}
    </Section>
  );
}
