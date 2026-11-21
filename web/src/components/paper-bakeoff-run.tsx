"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { Play } from "lucide-react";
import { Looked } from "@/components/looked";
import { Notice, ProblemNotice } from "@/components/messages";
import { RunSummary } from "@/components/paper-bakeoff-run-summary";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { describedBy, Field } from "@/components/settings-fields";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Radio } from "@/components/ui/radio";
import { Textarea } from "@/components/ui/textarea";
import { WorkStatus } from "@/components/work-status";
import { api } from "@/lib/api";
import { lastBakeoffJob } from "@/lib/bakeoff-methods";
import {
  callOf,
  checkRun,
  chosenCount,
  dataPlace,
  describeProposing,
  describeRunAll,
  EMPTY_RUN,
  isRunnable,
  MAX_RUN_MINUTES,
  proposingCount,
  type CallDraft,
  type RunDraft,
  type RunKey,
} from "@/lib/bakeoff-runs";
import { bakeoffJob, describeLeft, RUN_JOBS } from "@/lib/bakeoffs";
import { describeChecked, describeParameter } from "@/lib/paperagent-tools";
import type { Bakeoff, BakeoffMethod, ToolSummary } from "@/lib/types";
import { useAttempt, useLooked } from "@/lib/use-looked";
import { usePaperAgentTools } from "@/lib/use-paperagents";

// What is being done to run the methods and how it ended the last time, with the way to stop it
export function RunWork({ bakeoff }: { bakeoff: Bakeoff }) {
  const jobs = useSetupJobs();

  return (
    <WorkStatus
      job={bakeoffJob(jobs.jobs, bakeoff.id, RUN_JOBS)}
      last={lastBakeoffJob(jobs.jobs, bakeoff.id, RUN_JOBS)}
      jobs={jobs}
      label="What is being done to run the methods"
    />
  );
}

// What a tool takes and what was checked of it, as a person writing arguments for it needs it
function ToolSignature({ agentId, tool, meaning }: { agentId: string; tool: ToolSummary; meaning: string }) {
  const { report } = useServer();
  const look = useCallback(() => api.paperAgentTool(agentId, tool.name), [agentId, tool.name]);
  const detail = useLooked(look, report, tool.name);

  return (
    <div className="flex flex-col gap-1.5 rounded-lg bg-muted/40 p-2" data-testid="tool-signature">
      <Looked state={detail.value} label={`Looking at ${tool.name}`} failure={`${tool.name} could not be looked at.`} onRetry={detail.reload}>
        {(found) => (
          <>
            {found.description !== "" && <p className="whitespace-pre-wrap break-words text-xs">{found.description}</p>}
            {found.signature.length === 0 ? (
              <p className="text-xs text-muted-foreground">It takes no arguments.</p>
            ) : (
              <ul aria-label={`What ${tool.name} takes`} className="flex flex-col gap-0.5">
                {found.signature.map((parameter) => (
                  <li key={parameter.name} className="break-words text-xs">
                    <code>{describeParameter(parameter)}</code>
                    <span className="text-muted-foreground">{parameter.required ? ", needed" : ""}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </Looked>
      <p className="text-xs text-muted-foreground">{describeChecked(tool)}.</p>
      <details>
        <summary className="cursor-pointer text-xs text-muted-foreground">What its tier says</summary>
        <p className="pt-1 text-xs text-muted-foreground">{meaning}</p>
      </details>
    </div>
  );
}

// Which tool of a method to call and with what, as the person says it: the tools that the method has are the ones to choose from, since
// a call of any other would not be made
function ToolChoice({
  bakeoff,
  method,
  call,
  change,
  problems,
  disabled,
  id,
}: {
  bakeoff: Bakeoff;
  method: BakeoffMethod;
  call: CallDraft;
  change: (part: Partial<CallDraft>) => void;
  problems: Partial<Record<RunKey, string>>;
  disabled: boolean;
  id: string;
}) {
  const { report } = useServer();
  const tools = usePaperAgentTools(method.agent?.id ?? "", report, method.standing.at ?? "");
  const loaded = tools.value.kind === "ready";
  const known = tools.value.kind === "ready" && (tools.value.value.kept?.tools ?? []).some((tool) => tool.name === call.tool);
  const toolProblem = problems[`${method.id}:tool`];
  const argsProblem = problems[`${method.id}:args`];
  const place = bakeoff.data !== null ? dataPlace(bakeoff.data.own) : "/data/…";

  // A tool that the method no longer has, as it was built again, is not one to call, and a call of it would be kept as not run in
  // place of the last run
  useEffect(() => {
    if (loaded && call.tool !== "" && !known) change({ tool: "" });
  }, [loaded, call.tool, known, change]);

  return (
    <Looked state={tools.value} label={`Looking at the tools of ${method.name}`} failure="Its tools could not be looked at." onRetry={tools.reload}>
      {(found) => {
        const kept = found.kept?.tools ?? [];
        if (kept.length === 0) return <Notice tone="muted">It has no tools to call now. Build it again.</Notice>;
        const chosen = kept.find((tool) => tool.name === call.tool);

        return (
          <div className="flex flex-col gap-3">
            <Field id={`${id}-tool`} label="Its tool" problem={toolProblem}>
              <NativeSelect
                id={`${id}-tool`}
                value={chosen !== undefined ? call.tool : ""}
                onChange={(event) => change({ tool: event.target.value })}
                disabled={disabled}
                aria-invalid={toolProblem !== undefined}
                aria-describedby={describedBy(`${id}-tool`, { problem: toolProblem !== undefined })}
              >
                <option value="">Choose a tool</option>
                {kept.map((tool) => (
                  <option key={tool.name} value={tool.name}>
                    {tool.name} (tier {tool.tier})
                  </option>
                ))}
              </NativeSelect>
            </Field>
            {chosen !== undefined && <ToolSignature agentId={method.agent?.id ?? ""} tool={chosen} meaning={found.meaning} />}
            <Field
              id={`${id}-args`}
              label="Its arguments"
              hint={`An object of JSON, by the names of the tool's parameters, such as {"path": "${place}"}. Your data is at ${place}, and a place in it is a place that starts with that. Leave it blank for none.`}
              problem={argsProblem}
            >
              <Textarea
                id={`${id}-args`}
                value={call.args}
                onChange={(event) => change({ args: event.target.value })}
                readOnly={disabled}
                spellCheck={false}
                autoComplete="off"
                rows={3}
                className="font-mono text-xs"
                aria-invalid={argsProblem !== undefined}
                aria-describedby={describedBy(`${id}-args`, { hint: true, problem: argsProblem !== undefined })}
              />
            </Field>
          </div>
        );
      }}
    </Looked>
  );
}

// One method that can be run: whether to run it, who chooses its call, and the call if the person does
function RunRow({
  bakeoff,
  method,
  call,
  change,
  problems,
  disabled,
}: {
  bakeoff: Bakeoff;
  method: BakeoffMethod;
  call: CallDraft;
  change: (part: Partial<CallDraft>) => void;
  problems: Partial<Record<RunKey, string>>;
  disabled: boolean;
}) {
  const id = useId();

  return (
    <li className="flex flex-col gap-3 rounded-xl border border-border bg-card p-3" data-testid="run-row" data-method={method.id}>
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={call.run} onChange={(event) => change({ run: event.target.checked })} disabled={disabled} />
        <span>
          Run <span className="font-medium">{method.name}</span>
        </span>
      </label>
      {call.run && (
        <div className="flex flex-col gap-3 pl-6">
          <fieldset className="flex flex-col gap-1.5" disabled={disabled}>
            <legend className="mb-1 text-xs font-medium text-muted-foreground">Who chooses the call</legend>
            <label className="flex items-center gap-2 text-sm">
              <Radio name={`${id}-mode`} checked={call.mode === "say"} onChange={() => change({ mode: "say" })} />I choose the tool and its arguments
            </label>
            <label className="flex items-center gap-2 text-sm">
              <Radio name={`${id}-mode`} checked={call.mode === "propose"} onChange={() => change({ mode: "propose" })} />A model proposes the call, which is
              paid for out of the limit
            </label>
          </fieldset>
          {call.mode === "say" ? (
            <ToolChoice bakeoff={bakeoff} method={method} call={call} change={change} problems={problems} disabled={disabled} id={id} />
          ) : (
            <p className="text-xs text-muted-foreground" data-testid="run-propose-note">
              {bakeoff.settings_model} is shown the task, what you said your data is, and what the method&apos;s tools say of themselves, and not
              your data. It writes a call, and a program checks the call against the tool as it checks yours, before anything is run. A call that
              does not fit is not made, and says why.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

// Runs the methods that are built on the person's data: for each that is chosen, one call of one of its tools, which the person writes or
// a model proposes. What came of each is kept and shown below, with why a method was not run.
export function RunMethods({ bakeoff }: { bakeoff: Bakeoff }) {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const id = useId();
  const attempt = useAttempt(report);
  const [draft, setDraft] = useState<RunDraft>(EMPTY_RUN);
  const [tried, setTried] = useState(false);
  const checked = checkRun(draft, bakeoff.candidates, bakeoff.limits);
  const problems = tried ? checked.problems : {};
  const working = attempt.busy || bakeoff.job !== null || bakeoffJob(jobs.jobs, bakeoff.id) !== undefined;
  const runnable = bakeoff.candidates.filter(isRunnable);
  const chosen = chosenCount(draft, bakeoff.candidates);
  const proposing = proposingCount(draft, bakeoff.candidates);
  const data = bakeoff.data;
  const unrunnable = data === null || data.missing;
  const ran = bakeoff.candidates.filter((method) => method.run !== null);

  const changeCall = useCallback((methodId: string, part: Partial<CallDraft>) => {
    setDraft((was) => ({ ...was, calls: { ...was.calls, [methodId]: { ...callOf(was, methodId), ...part } } }));
  }, []);

  async function run() {
    setTried(true);
    const body = checked.value;
    if (body === null || working || unrunnable) return;
    const job = await attempt.run(() => api.runBakeoff(bakeoff.id, body));
    if (job) {
      jobs.track(job);
      setTried(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Running a method calls one of its tools once, on your data, in a container that has no network and can only read the data. The call is
        yours, or a model&apos;s to propose and a program to check as it checks yours. Data that is outside what the card of a method&apos;s paper
        says is not run on unless you have said to go on with that method. Whatever comes of a call is kept, with why a method was not run, and
        it says what was run, on what, and what it gave. It does not say that what it gave is right. Only the last run of each method is kept.
      </p>
      <RunWork bakeoff={bakeoff} />
      {data === null && (
        <Notice tone="muted">Say which of your data the methods are run on, under &ldquo;Change it&rdquo; below, and then run them.</Notice>
      )}
      {data !== null && data.missing && (
        <Notice tone="muted">
          {data.own} is not where the Data page says it is, so the methods cannot be run on it.
        </Notice>
      )}
      {runnable.length === 0 ? (
        <div className="flex flex-col gap-1 rounded-xl border border-dashed border-border p-5" data-testid="bakeoff-run-none">
          <p className="text-sm font-medium">No method is built, so none can be run</p>
          <p className="text-sm text-muted-foreground">Build the methods above. A method that is not built has no tools to call.</p>
        </div>
      ) : (
        <form
          aria-label="Run the methods"
          onSubmit={(event) => {
            event.preventDefault();
            void run();
          }}
          className="flex flex-col gap-4 rounded-lg border border-border p-3"
        >
          <ul aria-label="Methods to run" className="flex flex-col gap-3">
            {runnable.map((method) => (
              <RunRow
                key={method.id}
                bakeoff={bakeoff}
                method={method}
                call={callOf(draft, method.id)}
                change={(part) => changeCall(method.id, part)}
                problems={problems}
                disabled={working}
              />
            ))}
          </ul>
          <Field
            id={`${id}-minutes`}
            label="The most minutes one call may take"
            hint={`A whole number from 1 to ${MAX_RUN_MINUTES}. A call that takes longer is stopped, and is kept as one that failed.`}
            problem={problems.minutes}
            className="max-w-xs"
          >
            <Input
              id={`${id}-minutes`}
              value={draft.minutes}
              onChange={(event) => setDraft((was) => ({ ...was, minutes: event.target.value }))}
              inputMode="numeric"
              autoComplete="off"
              readOnly={working}
              aria-invalid={problems.minutes !== undefined}
              aria-describedby={describedBy(`${id}-minutes`, { hint: true, problem: problems.minutes !== undefined })}
            />
          </Field>
          <p className="text-xs text-muted-foreground" data-testid="run-spending">
            {describeProposing(proposing)} {proposing > 0 ? describeLeft(bakeoff) : ""}
          </p>
          {problems.calls !== undefined && (
            <p role="alert" className="text-xs text-destructive">
              {problems.calls}
            </p>
          )}
          {attempt.problem && <ProblemNotice problem={attempt.problem} />}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={working || unrunnable}>
              <Play />
              {attempt.busy ? "Starting…" : describeRunAll(chosen)}
            </Button>
            {bakeoff.job !== null && <span className="text-xs text-muted-foreground">Something is being done to the methods. Stop it, or wait, to run them.</span>}
          </div>
        </form>
      )}
      {ran.length > 0 && (
        <section aria-label="What came of running the methods" className="flex flex-col gap-3">
          <h3 className="text-sm font-medium">What came of running them</h3>
          <ul className="flex flex-col gap-3">
            {ran.map((method) =>
              method.run === null ? null : (
                <li key={method.id} className="flex flex-col gap-1.5" data-testid="run-of-method" data-method={method.id}>
                  <p className="break-words text-sm font-medium">{method.name}</p>
                  <RunSummary key={method.run.at} bakeoffId={bakeoff.id} run={method.run} />
                </li>
              ),
            )}
          </ul>
        </section>
      )}
    </div>
  );
}
