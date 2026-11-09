"use client";

import { useId, useState } from "react";
import { Hammer, Trash2 } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { Aside, describedBy, Field } from "@/components/settings-fields";
import { Log } from "@/components/setup-jobs";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { api, ApiError } from "@/lib/api";
import { stripAnsi } from "@/lib/format";
import {
  checkEnvironment,
  describeBuilt,
  describeDuration,
  describeImage,
  describePipCheck,
  describeUnsupported,
  emptyEnvironment,
  FAILURE_ADVICE,
  shortId,
  suggestion,
  type EnvironmentDraft,
} from "@/lib/paperagent-environment";
import { EMPTY_LOG, type JobLog } from "@/lib/setup";
import type { EnvironmentBuilt, EnvironmentFailed, EnvironmentRecipe, Job, PaperAgent, PaperAgentEnvironment } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useJobLogs } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";

interface Shared {
  agent: PaperAgent;
  environment: PaperAgentEnvironment;
  // Whether anything is being done to the agent, which what is done to its environment waits for
  busy: boolean;
}

// What a step is called, from the steps of the recipe, and for the few that are not in it
const OTHER_STEPS: Record<string, string> = {
  pull: "Fetch what the build starts from",
  commit: "Keep it as an image",
  "offline run": "Run it with no network",
};

function stepTitle(recipe: EnvironmentRecipe, step: string | null): string | null {
  if (step === null) return null;

  return recipe.steps.find((item) => item.id === step)?.title ?? OTHER_STEPS[step] ?? step;
}

// What the build is going to do, from the code's own files and what a person asked for, in words
function Plan({ recipe, environment }: { recipe: EnvironmentRecipe; environment: PaperAgentEnvironment }) {
  const id = useId();
  const { limits } = environment;

  return (
    <section aria-labelledby={id} className="flex flex-col gap-2" data-testid="environment-plan">
      <h3 id={id} className="text-sm font-medium">
        What would be built
      </h3>
      <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[13rem_minmax(0,1fr)]">
        <dt className="text-muted-foreground">Made with</dt>
        <dd>{recipe.kind === "conda" ? "conda" : "pip"}, from {recipe.files.join(", ")}</dd>
        <dt className="text-muted-foreground">Python</dt>
        <dd className="break-words" data-testid="environment-python">
          {recipe.python === null ? `The one that ${recipe.python_from}` : `${recipe.python}, as ${recipe.python_from}`}
        </dd>
        <dt className="text-muted-foreground">Starting from</dt>
        <dd className="break-all">{recipe.base_image}</dd>
        {recipe.system_packages.length > 0 && (
          <>
            <dt className="text-muted-foreground">System packages first</dt>
            <dd className="break-words">{recipe.system_packages.join(", ")}</dd>
          </>
        )}
        <dt className="text-muted-foreground">Steps</dt>
        <dd>
          <ol aria-label="Steps of the build" className="flex list-decimal flex-col gap-0.5 pl-4">
            {recipe.steps.map((step) => (
              <li key={step.id}>{step.title}</li>
            ))}
          </ol>
        </dd>
      </dl>
      {recipe.notes.map((note) => (
        <p key={note} className="break-words text-xs text-muted-foreground">
          {note}
        </p>
      ))}
      <p className="text-xs text-muted-foreground">
        Installing runs the project&apos;s own install steps, which are its code, so it is done in a container that has none of this
        machine in it: no folder, no key, and nothing signed in. It has the network, to fetch packages, {limits.memory.toUpperCase()}B of memory,
        at most {limits.cpus} processors, and at most {limits.pids.toLocaleString("en-US")} processes. Afterwards it is run with no network.
      </p>
    </section>
  );
}

// Says which Python, what to install first, and the most time and disk, and starts building
function BuildForm({
  agent,
  environment,
  recipe,
  busy,
  draft,
  onDraft,
  jobs,
  onStale,
}: Shared & {
  recipe: EnvironmentRecipe;
  draft: EnvironmentDraft;
  onDraft: (draft: EnvironmentDraft) => void;
  jobs: JobsData;
  onStale: () => void;
}) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [tried, setTried] = useState(false);
  const checked = checkEnvironment(draft, environment);
  const problems = tried ? checked.problems : {};
  const { limits } = environment;
  const change = (part: Partial<EnvironmentDraft>) => onDraft({ ...draft, ...part });

  async function build() {
    setTried(true);
    const options = checked.value;
    if (options === null) return;
    const job = await attempt.run(async () => {
      try {
        return await api.buildPaperAgentEnvironment(agent.id, options);
      } catch (error) {
        // An environment that was built has been kept before the page has looked again, which it does now
        if (error instanceof ApiError && error.code === "done") {
          onStale();

          return undefined;
        }
        throw error;
      }
    });
    if (job) jobs.track(job);
  }

  return (
    <form
      aria-label="Build the environment"
      onSubmit={(event) => {
        event.preventDefault();
        void build();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {recipe.python !== null && (
          <Field
            id={`${id}-python`}
            label="Python"
            hint={`Leave it to the code, which says ${recipe.python} (${recipe.python_from}), or build for another.`}
            problem={problems.python}
          >
            <NativeSelect
              id={`${id}-python`}
              value={draft.python}
              onChange={(event) => change({ python: event.target.value })}
              aria-describedby={describedBy(`${id}-python`, { hint: true, problem: problems.python !== undefined })}
            >
              <option value="">What the code says ({recipe.python})</option>
              {environment.python_versions.map((version) => (
                <option key={version} value={version}>
                  Python {version}
                </option>
              ))}
            </NativeSelect>
          </Field>
        )}
        <Field
          id={`${id}-packages`}
          label="System packages to install first"
          hint={`Debian packages, told apart by spaces or commas, such as libhdf5-dev. At most ${environment.max_system_packages}. A build that fails for want of one says which.`}
          problem={problems.packages}
          className={recipe.python === null ? "sm:col-span-2" : undefined}
        >
          <Input
            id={`${id}-packages`}
            value={draft.packages}
            onChange={(event) => change({ packages: event.target.value })}
            autoComplete="off"
            spellCheck={false}
            placeholder="libhdf5-dev pkg-config"
            aria-invalid={problems.packages !== undefined}
            aria-describedby={describedBy(`${id}-packages`, { hint: true, problem: problems.packages !== undefined })}
          />
        </Field>
        <Field
          id={`${id}-minutes`}
          label="Most time, in minutes"
          hint={`A build that takes longer is stopped. At most ${limits.max_minutes}.`}
          problem={problems.minutes}
        >
          <Input
            id={`${id}-minutes`}
            value={draft.minutes}
            onChange={(event) => change({ minutes: event.target.value })}
            inputMode="numeric"
            autoComplete="off"
            aria-invalid={problems.minutes !== undefined}
            aria-describedby={describedBy(`${id}-minutes`, { hint: true, problem: problems.minutes !== undefined })}
          />
        </Field>
        <Field
          id={`${id}-gigabytes`}
          label="Most disk, in gigabytes"
          hint={`What the build may write to its disk, counting what it installs. It is looked at every few seconds. At most ${limits.max_gigabytes}.`}
          problem={problems.gigabytes}
        >
          <Input
            id={`${id}-gigabytes`}
            value={draft.gigabytes}
            onChange={(event) => change({ gigabytes: event.target.value })}
            inputMode="numeric"
            autoComplete="off"
            aria-invalid={problems.gigabytes !== undefined}
            aria-describedby={describedBy(`${id}-gigabytes`, { hint: true, problem: problems.gigabytes !== undefined })}
          />
        </Field>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={busy || attempt.busy || !environment.docker.ready}>
          <Hammer />
          {attempt.busy ? "Starting…" : busy ? "Building…" : "Build the environment"}
        </Button>
      </div>
    </form>
  );
}

// What the build prints, as it goes
function BuildOutput({ job, jobs }: { job: Job; jobs: JobsData }) {
  const logs = useJobLogs(jobs.jobs, job.id);
  const log: JobLog = logs[job.id] ?? EMPTY_LOG;
  const current = jobs.jobs?.find((item) => item.id === job.id) ?? job;

  return <Log job={current} log={log} />;
}

// Text that is kept on the server, which is asked for when it is wanted to be seen, and each time, as a build may change it
function Kept({ label, load, note }: { label: string; load: () => Promise<string>; note?: string }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const id = useId();
  const [text, setText] = useState<string | null>(null);

  async function toggle() {
    if (text !== null) {
      setText(null);

      return;
    }
    const got = await attempt.run(load);
    if (got !== undefined) setText(got);
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div>
        <Button
          type="button"
          variant="link"
          size="xs"
          className="h-auto p-0"
          onClick={() => void toggle()}
          aria-expanded={text !== null}
          aria-controls={text !== null ? id : undefined}
          disabled={attempt.busy}
        >
          {text !== null ? `Hide ${label}` : attempt.busy ? "Getting it…" : `Show ${label}`}
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      {text !== null && (
        <div id={id} className="flex flex-col gap-1">
          {note && <p className="text-xs text-muted-foreground">{note}</p>}
          <div
            role="region"
            aria-label={label}
            tabIndex={0}
            className="max-h-72 overflow-auto rounded-md bg-muted/60 p-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <pre className="whitespace-pre-wrap break-all font-mono text-xs">{text === "" ? "It is empty." : text}</pre>
          </div>
        </div>
      )}
    </div>
  );
}

// Why the last build did not come to an environment, in what the output says of it, with what it suggests
function Failed({
  failed,
  draft,
  environment,
  onDraft,
}: {
  failed: EnvironmentFailed;
  draft: EnvironmentDraft;
  environment: PaperAgentEnvironment;
  onDraft: (draft: EnvironmentDraft) => void;
}) {
  const id = useId();
  const { failure } = failed;
  const step = stepTitle(failed.recipe, failure.step);
  const suggested = suggestion(failure, draft, environment.limits, environment.python_versions);

  return (
    <section
      aria-labelledby={id}
      className="flex flex-col gap-3 rounded-lg border border-destructive/40 p-3"
      data-testid="environment-failure"
      data-kind={failure.kind}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={id} className="text-sm font-medium">
          The last build failed
        </h3>
        <Badge variant="destructive">{failure.title}</Badge>
      </div>
      <p className="break-words text-sm" data-testid="environment-failure-detail">
        {failure.detail}
      </p>
      {step !== null && (
        <p className="break-words text-xs text-muted-foreground">
          It was at the step &ldquo;{step}&rdquo;{failure.package ? `, with ${failure.package}` : ""}.
        </p>
      )}
      <p className="break-words text-sm">{FAILURE_ADVICE[failure.kind]}</p>
      {suggested !== null && (
        <div>
          <Button type="button" variant="outline" size="sm" onClick={() => onDraft(suggested.draft)}>
            Fill in the form to {suggested.words}
          </Button>
        </div>
      )}
      {failure.tail.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs text-muted-foreground">The end of what that step printed:</p>
          <div
            role="region"
            aria-label="The end of what the step printed"
            tabIndex={0}
            className="max-h-56 overflow-auto rounded-md bg-muted/60 p-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <pre className="whitespace-pre-wrap break-words font-mono text-xs">{failure.tail.map(stripAnsi).join("\n")}</pre>
          </div>
        </div>
      )}
      {environment.has_log && (
        <Kept
          label="everything the build printed"
          load={async () => (await api.paperAgentEnvironmentLog(environment.id)).lines.map(stripAnsi).join("\n")}
          note="The last 4,000 lines are kept."
        />
      )}
      <p className="text-xs text-muted-foreground">
        This is the likeliest reason, read from words that package managers do not keep the same, and not a certainty. The output says
        more.
      </p>
    </section>
  );
}

// Takes away an environment that was built, with its image, so that it can be built again
function ClearEnvironment({
  agent,
  busy,
  onCleared,
}: {
  agent: PaperAgent;
  busy: boolean;
  onCleared: (environment: PaperAgentEnvironment) => void;
}) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);

  async function clear() {
    setAsking(false);
    const next = await attempt.run(() => api.clearPaperAgentEnvironment(agent.id));
    if (next) onCleared(next);
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button variant="outline" size="sm" onClick={() => setAsking(true)} disabled={busy || attempt.busy}>
          <Trash2 />
          Take the environment away
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Take away the environment of {agent.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This takes the image away from Docker, with what was recorded of the build. The code stays, and the environment can be built
              again.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void clear()}>
              Take away
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// An environment that was built: what is in it, what it is, and how far that has been checked
function BuiltEnvironment({
  agent,
  environment,
  built,
  busy,
  onCleared,
}: Shared & { built: EnvironmentBuilt; onCleared: (environment: PaperAgentEnvironment) => void }) {
  const id = useId();
  const conda = built.lock.name.startsWith("conda");

  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid="environment-built">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={id} className="text-sm font-medium">
          The environment
        </h3>
        <Badge variant="secondary">Built, and starts with no network</Badge>
      </div>
      <p className="text-xs text-muted-foreground" data-testid="environment-built-when">
        {describeBuilt(built)}.
      </p>
      <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[13rem_minmax(0,1fr)]">
        <dt className="text-muted-foreground">Python</dt>
        <dd data-testid="environment-built-python">{built.python}</dd>
        <dt className="text-muted-foreground">Packages</dt>
        <dd data-testid="environment-built-packages">
          {built.lock.packages.toLocaleString("en-US")}, listed with their exact versions ({conda ? "conda's list, and what pip added" : "pip freeze"})
        </dd>
        <dt className="text-muted-foreground">The image</dt>
        <dd className="break-all" data-testid="environment-built-image">
          <code className="font-mono text-xs">{shortId(built.image.id)}</code>, which is the hash of what is in it, so that it is the same
          later
        </dd>
        <dt className="text-muted-foreground">Size</dt>
        <dd>{describeImage(built)}</dd>
        <dt className="text-muted-foreground">It began with</dt>
        <dd className="break-all">
          {built.recipe.base_image}
          {built.image.base_id !== "" && (
            <>
              {" "}
              (<code className="font-mono text-xs">{shortId(built.image.base_id)}</code>)
            </>
          )}
        </dd>
        <dt className="text-muted-foreground">Checked</dt>
        <dd data-testid="environment-built-check">{describePipCheck(built.pip_check)}</dd>
        {built.recipe.system_packages.length > 0 && (
          <>
            <dt className="text-muted-foreground">System packages</dt>
            <dd className="break-words">{built.recipe.system_packages.join(", ")}</dd>
          </>
        )}
        <dt className="text-muted-foreground">Steps</dt>
        <dd>
          <ol aria-label="Steps that were run" className="flex list-decimal flex-col gap-0.5 pl-4">
            {built.steps.map((step) => (
              <li key={step.id}>
                {step.title} <span className="text-muted-foreground">({describeDuration(step.seconds)})</span>
              </li>
            ))}
          </ol>
        </dd>
        <dt className="text-muted-foreground">Allowed</dt>
        <dd>
          {built.limits.minutes} minutes and {built.limits.gigabytes} GB of disk
        </dd>
      </dl>
      {built.pip_check.problems.length > 0 && (
        <ul aria-label="What pip check found" className="flex flex-col gap-0.5 break-words text-xs text-muted-foreground">
          {built.pip_check.problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}
      {built.image_present === false && (
        <Aside tone="warning">
          Docker no longer has this image, so it cannot be used. Take the environment away, and build it again.
        </Aside>
      )}
      {built.image_present === null && (
        <Aside tone="warning">Docker could not be asked whether the image is still there. Start Docker to find out.</Aside>
      )}
      <Kept
        key={`lock-${built.image.id}`}
        label="the exact versions"
        load={async () => (await api.paperAgentEnvironmentLock(agent.id)).text}
        note={`Kept as ${built.lock.name}.`}
      />
      {environment.has_log && (
        <Kept
          key={`log-${built.image.id}`}
          label="what the build printed"
          load={async () => (await api.paperAgentEnvironmentLog(agent.id)).lines.map(stripAnsi).join("\n")}
          note="The last 4,000 lines are kept."
        />
      )}
      <p className="text-xs text-muted-foreground">
        All that is known is that this was built and starts. It does not say that the code runs: that is not tried, and a project that
        installs only by running its own scripts, or that needs data, a GPU, or a system that is not Debian, may build and not work.
      </p>
      <ClearEnvironment agent={agent} busy={busy} onCleared={onCleared} />
    </section>
  );
}

// The environment of an agent's code: what would be built from its files and how, building it in a container that has none of
// this machine in it, why a build failed, and what was built
export function EnvironmentSection({
  agent,
  environment,
  busy,
  building,
  jobs,
  onCleared,
  onStale,
}: Shared & {
  // The build that is at work, if there is one
  building: Job | undefined;
  jobs: JobsData;
  onCleared: (environment: PaperAgentEnvironment) => void;
  // Looks at the agent and its environment again, as is done when the server says what the page shows is out of date
  onStale: () => void;
}) {
  const [draft, setDraft] = useState<EnvironmentDraft>(() => emptyEnvironment(environment.limits));
  const { built, failure, recipe, unsupported } = environment;

  if (environment.commit === null) {
    return <p className="text-sm text-muted-foreground">Fetch the code first. The environment is built from the files in it.</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      {!environment.docker.ready && (
        <Aside tone="warning">
          {environment.docker.message ?? "Docker is not running."} Building takes it. The environment cannot be built until it is.
        </Aside>
      )}
      {building !== undefined && <BuildOutput key={building.id} job={building} jobs={jobs} />}
      {built !== null && <BuiltEnvironment agent={agent} environment={environment} built={built} busy={busy} onCleared={onCleared} />}
      {built === null && unsupported !== null && (
        <section className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="environment-unsupported" data-kind={unsupported.kind}>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium">It is not built here</h3>
            <Badge variant="outline">{describeUnsupported(unsupported.kind)}</Badge>
          </div>
          <p className="break-words text-sm">{unsupported.message}</p>
        </section>
      )}
      {built === null && failure !== null && <Failed failed={failure} draft={draft} environment={environment} onDraft={setDraft} />}
      {built === null && recipe !== null && unsupported === null && (
        <>
          <Plan recipe={recipe} environment={environment} />
          <BuildForm
            agent={agent}
            environment={environment}
            recipe={recipe}
            busy={busy || building !== undefined}
            draft={draft}
            onDraft={setDraft}
            jobs={jobs}
            onStale={onStale}
          />
        </>
      )}
    </div>
  );
}
