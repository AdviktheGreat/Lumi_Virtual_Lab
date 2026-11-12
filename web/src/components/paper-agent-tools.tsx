"use client";

import { useId, useState } from "react";
import { Play, Trash2 } from "lucide-react";
import { JobOutput } from "@/components/job-output";
import { ProblemNotice } from "@/components/messages";
import { Printed } from "@/components/printed";
import { useServer } from "@/components/server-provider";
import { Aside, describedBy, Field } from "@/components/settings-fields";
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
import { api, ApiError } from "@/lib/api";
import { count } from "@/lib/checks";
import { describeValue } from "@/lib/paperagent-reference";
import {
  checkTools,
  describeArgs,
  describeCase,
  describeChecked,
  describeMade,
  describeMaking,
  describeParameter,
  describePreview,
  describeTolerance,
  droppedLines,
  DROPPED_ADVICE,
  DROPPED_TITLES,
  emptyTools,
  type ToolsDraft,
} from "@/lib/paperagent-tools";
import type { Job, PaperAgent, PaperAgentTools, ToolCandidate, ToolDetail, ToolDropped, ToolsKept, ToolSummary } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";

interface Shared {
  agent: PaperAgent;
  tools: PaperAgentTools;
  // Whether anything is being done to the agent, which what is done to its tools waits for
  busy: boolean;
}

// A function that was not made a tool, with why, what the check found, and what a person may do about it
function Dropped({ item }: { item: ToolDropped }) {
  const lines = droppedLines(item);
  const advice = DROPPED_ADVICE[item.kind];

  return (
    <li className="flex flex-col gap-0.5 break-words text-xs" data-testid="tool-dropped" data-kind={item.kind}>
      <span>
        <code className="font-mono">
          {item.module}.{item.function}
        </code>{" "}
        <span className="text-muted-foreground">({count(item.calls, "call")}):</span> {DROPPED_TITLES[item.kind] ?? item.kind}. {item.reason}
      </span>
      {lines.length > 0 && (
        <ul aria-label={`What was found of ${item.name}`} className="list-disc pl-5 text-muted-foreground">
          {lines.map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
      )}
      {advice !== undefined && <span className="text-muted-foreground">{advice}</span>}
    </li>
  );
}

// What would be made, from what the tutorials called, and what would not, with why
function Preview({ tools }: { tools: PaperAgentTools }) {
  const id = useId();
  const preview = tools.preview;
  if (preview === null) return null;

  return (
    <section aria-labelledby={id} className="flex flex-col gap-2" data-testid="tools-preview">
      <h3 id={id} className="text-sm font-medium">
        What would be made
      </h3>
      <p className="text-sm" data-testid="tools-preview-summary">
        {describePreview(preview.candidates.length, preview.dropped.length)}
      </p>
      {preview.candidates.length > 0 && (
        <ul aria-label="Functions that would be made into tools" className="flex flex-col gap-1 text-sm">
          {preview.candidates.map((candidate: ToolCandidate) => (
            <li key={candidate.name} className="break-words" data-testid="tools-candidate">
              <code className="font-mono">{candidate.name}</code>{" "}
              <span className="text-muted-foreground">
                is {candidate.module}.{candidate.function}, called {count(candidate.cases, "time")} in {count(candidate.tutorials.length, "tutorial")}
                {candidate.skipped.length > 0 ? `, and ${count(candidate.skipped.length, "other call")} cannot be made again` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
      {preview.dropped.length > 0 && (
        <ul aria-label="Functions that cannot be made into tools" className="flex flex-col gap-1.5">
          {preview.dropped.map((item) => (
            <Dropped key={item.name} item={item} />
          ))}
        </ul>
      )}
      {preview.unused.length > 0 && (
        <ul aria-label="Tutorials whose calls were not looked at" className="flex flex-col gap-0.5 text-xs text-muted-foreground">
          {preview.unused.map((item) => (
            <li key={item.tutorial} className="break-words">
              <span className="break-all">{item.tutorial}</span>: {item.reason}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// Says the most time, how many tools, how many times each call is made again, how many rewrites, and the most to write, and starts it
function MakeForm({
  agent,
  tools,
  busy,
  draft,
  onDraft,
  jobs,
  onStale,
}: Shared & { draft: ToolsDraft; onDraft: (draft: ToolsDraft) => void; jobs: JobsData; onStale: () => void }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [tried, setTried] = useState(false);
  const checked = checkTools(draft, tools.limits);
  const problems = tried ? checked.problems : {};
  const { limits } = tools;
  const change = (part: Partial<ToolsDraft>) => onDraft({ ...draft, ...part });

  async function make() {
    setTried(true);
    const options = checked.value;
    if (options === null) return;
    const job = await attempt.run(async () => {
      try {
        return await api.makePaperAgentTools(agent.id, options);
      } catch (error) {
        // Tools that were made have been kept before the page has looked again, or the tutorials they are made from are not as they
        // were, which the page looks at again now
        if (error instanceof ApiError && (error.code === "done" || error.code === "no_reference" || error.code === "image_missing")) {
          onStale();

          return undefined;
        }
        throw error;
      }
    });
    if (job) jobs.track(job);
  }

  const number = (key: "minutes" | "totalMinutes" | "tools" | "repeats" | "repairs" | "gigabytes", label: string, hint: string) => (
    <Field id={`${id}-${key}`} label={label} hint={hint} problem={problems[key]}>
      <Input
        id={`${id}-${key}`}
        value={draft[key]}
        onChange={(event) => change({ [key]: event.target.value })}
        inputMode="numeric"
        autoComplete="off"
        aria-invalid={problems[key] !== undefined}
        aria-describedby={describedBy(`${id}-${key}`, { hint: true, problem: problems[key] !== undefined })}
      />
    </Field>
  );

  return (
    <form
      aria-label="Make the tools"
      onSubmit={(event) => {
        event.preventDefault();
        void make();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {number(
          "minutes",
          "Most time for the calls of one tool, in minutes",
          `A tool that takes longer is not made. At most ${limits.max_minutes}.`,
        )}
        {number(
          "totalMinutes",
          "Most time for all of the tools, in minutes",
          `What is left when this is used is not tried. At most ${limits.max_total_minutes}.`,
        )}
        {number("tools", "How many tools to make", `The rest are listed as not made. At most ${limits.max_tools}.`)}
        {number(
          "repeats",
          "How many times to call each again",
          `A call that gives other than the tutorial got, once, is not held to. At most ${limits.max_repeats}.`,
        )}
        {number(
          "repairs",
          "How many times a wrapper may be rewritten",
          `Only how it is written is changed, never what it calls. From 0 to ${limits.max_repairs}.`,
        )}
        {number(
          "gigabytes",
          "Most one call may write, in gigabytes",
          `Counting its copy of the project. At most ${limits.max_gigabytes}.`,
        )}
      </div>
      {tools.reference?.data === true && (
        <p className="text-xs text-muted-foreground">The calls are given the data that the tutorials were given, to read only, at /opt/paper/data.</p>
      )}
      <p className="text-xs text-muted-foreground">
        A tool is a small function, written without a model, that calls one function of the code and has no algorithm of its own. Each call
        of the tutorials is made again in a container made from the environment&apos;s image that has none of this machine in it: no folder
        and no key, no network, a root that cannot be written to, {limits.memory.toUpperCase()}B of memory, at most {limits.cpus} processors,
        and at most {limits.pids.toLocaleString("en-US")} processes. Each call is made in a copy of the project of its own, with the
        arguments that the tutorial passed.
      </p>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={busy || attempt.busy || !tools.docker.ready}>
          <Play />
          {attempt.busy ? "Starting…" : busy ? "Making…" : "Make the tools"}
        </Button>
      </div>
    </form>
  );
}

// What was kept of one tool: its wrapper, its signature, and each call that was made again and what it gave
function ToolDetailView({ detail }: { detail: ToolDetail }) {
  const id = useId();
  const { evidence } = detail;

  return (
    <div className="flex flex-col gap-3 rounded-md border border-border p-3" data-testid="tool-detail">
      <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[10rem_minmax(0,1fr)]">
        <dt className="text-muted-foreground">It calls</dt>
        <dd className="break-all">
          <code className="font-mono">
            {detail.repo.module}.{detail.repo.function}
          </code>{" "}
          <span className="text-muted-foreground">
            ({detail.repo.file}, line {detail.repo.line})
          </span>
        </dd>
        <dt className="text-muted-foreground">Parameters</dt>
        <dd>
          {detail.signature.length === 0 ? (
            "None"
          ) : (
            <ul aria-label="Parameters of the tool" className="flex flex-col gap-0.5">
              {detail.signature.map((parameter) => (
                <li key={parameter.name}>
                  <code className="font-mono text-xs">{describeParameter(parameter)}</code>
                </li>
              ))}
            </ul>
          )}
        </dd>
        {detail.description !== "" && (
          <>
            <dt className="text-muted-foreground">What the code says of it</dt>
            <dd className="break-words">{detail.description}</dd>
          </>
        )}
        <dt className="text-muted-foreground">Wrapper&apos;s hash</dt>
        <dd className="break-all font-mono text-xs">{detail.wrapper_sha256.slice(0, 16)}</dd>
      </dl>
      <div className="flex flex-col gap-1">
        <h4 className="text-xs font-medium">The wrapper&apos;s code</h4>
        <Printed label="The wrapper's code" text={detail.source} />
      </div>
      <section aria-labelledby={`${id}-evidence`} className="flex flex-col gap-1.5">
        <h4 id={`${id}-evidence`} className="text-xs font-medium">
          Calls that were made again
        </h4>
        <p className="text-xs text-muted-foreground">
          {count(evidence.checked, "call")} of {evidence.recorded} recorded, each made again {count(evidence.repeats, "time")}. {describeTolerance(evidence.tolerance)}
        </p>
        <ul aria-label="Calls that were made again" className="flex max-h-80 flex-col gap-2 overflow-auto">
          {evidence.cases.map((one) => (
            <li key={`${one.tutorial}-${one.call}`} className="break-words text-xs" data-testid="tool-case" data-verdict={one.verdict}>
              <span className="text-muted-foreground">
                Call {one.call} of {one.tutorial}:
              </span>{" "}
              <code className="font-mono">
                {detail.repo.function}({describeArgs(one.args)})
              </code>
              <span className="text-muted-foreground"> gave </span>
              <code className="font-mono">{describeValue(one.expected)}</code>
              <span className="text-muted-foreground"> in the tutorial. </span>
              {describeCase(one)}.
              {one.differences.length > 0 && (
                <ul aria-label="How it differed" className="list-disc pl-5 text-muted-foreground">
                  {one.differences.map((line, index) => (
                    <li key={index}>{line}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </section>
      {evidence.skipped.length > 0 && (
        <section className="flex flex-col gap-1">
          <h4 className="text-xs font-medium">Calls that could not be made again</h4>
          <ul aria-label="Calls that could not be made again" className="flex flex-col gap-0.5 text-xs text-muted-foreground">
            {evidence.skipped.map((one) => (
              <li key={`${one.tutorial}-${one.call}`} className="break-words">
                Call {one.call} of {one.tutorial}: {one.reason}
              </li>
            ))}
          </ul>
        </section>
      )}
      {evidence.repairs.length > 0 && (
        <section className="flex flex-col gap-1">
          <h4 className="text-xs font-medium">How the wrapper was rewritten</h4>
          <ul aria-label="How the wrapper was rewritten" className="flex flex-col gap-0.5 text-xs text-muted-foreground">
            {evidence.repairs.map((one, index) => (
              <li key={index} className="break-words">
                {one.change}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

// One tool that was made: what it is, how far it was checked, and its wrapper and evidence, which are asked for when they are wanted
function Tool({ agent, tool, onStale }: { agent: PaperAgent; tool: ToolSummary; onStale: () => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const id = useId();
  const [detail, setDetail] = useState<ToolDetail | null>(null);

  async function toggle() {
    if (detail !== null) {
      setDetail(null);

      return;
    }
    const got = await attempt.run(async () => {
      try {
        return await api.paperAgentTool(agent.id, tool.name);
      } catch (error) {
        // What was kept of it is gone, or is no longer one that can be read as a tool, which the page looks at again
        if (error instanceof ApiError && error.status === 404) {
          onStale();

          return undefined;
        }
        throw error;
      }
    });
    if (got !== undefined) setDetail(got);
  }

  return (
    <li className="flex flex-col gap-1.5 rounded-lg border border-border p-3" data-testid="tool" data-name={tool.name}>
      <div className="flex flex-wrap items-center gap-2">
        <code className="break-all font-mono text-sm font-medium">
          {tool.name}({tool.parameters.join(", ")})
        </code>
        <Badge variant="secondary">Tier {tool.tier}</Badge>
      </div>
      <p className="break-words text-xs text-muted-foreground">
        It calls {tool.module}.{tool.function}. {describeChecked(tool)}.
      </p>
      <div>
        <Button
          type="button"
          variant="link"
          size="xs"
          className="h-auto p-0"
          onClick={() => void toggle()}
          aria-expanded={detail !== null}
          aria-controls={detail !== null ? id : undefined}
          disabled={attempt.busy}
        >
          {detail !== null ? "Hide the wrapper and the evidence" : attempt.busy ? "Getting it…" : "Show the wrapper and the evidence"}
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      {detail !== null && (
        <div id={id}>
          <ToolDetailView detail={detail} />
        </div>
      )}
    </li>
  );
}

// Takes away the tools, with what is known of them, so that they can be made again. What the tutorials gave stays
function ClearTools({ agent, busy, onCleared }: { agent: PaperAgent; busy: boolean; onCleared: (tools: PaperAgentTools) => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);

  async function clear() {
    setAsking(false);
    const next = await attempt.run(() => api.clearPaperAgentTools(agent.id));
    if (next) onCleared(next);
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button variant="outline" size="sm" onClick={() => setAsking(true)} disabled={busy || attempt.busy}>
          <Trash2 />
          Take the tools away
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Take away the tools of {agent.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This takes away the tools and what is known of them. What the tutorials gave stays, and the tools can be made again.
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

// What was kept of the making of tools: which were made, which functions were not and why, and what it was allowed
function KeptTools({
  agent,
  tools,
  kept,
  busy,
  onCleared,
  onStale,
}: Shared & { kept: ToolsKept; onCleared: (tools: PaperAgentTools) => void; onStale: () => void }) {
  const id = useId();

  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid="tools-kept">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={id} className="text-sm font-medium">
          The tools
        </h3>
        <Badge variant={kept.complete ? "secondary" : "outline"}>{kept.complete ? "Made to the end of the list" : "Not made to the end"}</Badge>
      </div>
      <p className="text-xs text-muted-foreground" data-testid="tools-kept-when">
        {describeMaking(kept)}. {describeMade(kept)}
      </p>
      <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[13rem_minmax(0,1fr)]">
        <dt className="text-muted-foreground">Given to read</dt>
        <dd>{kept.data ? "The data that the tutorials were given" : "None"}</dd>
        <dt className="text-muted-foreground">Allowed</dt>
        <dd>
          {kept.limits.minutes} minutes for the calls of one tool and {kept.limits.total_minutes} for all, each call made again{" "}
          {count(kept.limits.repeats, "time")}, {count(kept.limits.repairs, "rewrite")}, and {kept.limits.gigabytes} GB written
        </dd>
      </dl>
      {kept.tools.length > 0 && (
        <ul aria-label="The tools that were made" className="flex flex-col gap-2">
          {kept.tools.map((tool) => (
            <Tool key={tool.name} agent={agent} tool={tool} onStale={onStale} />
          ))}
        </ul>
      )}
      {kept.dropped.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <h4 className="text-xs font-medium">Functions that were not made into tools</h4>
          <ul aria-label="Functions that were not made into tools" className="flex flex-col gap-1.5" data-testid="tools-dropped">
            {kept.dropped.map((item) => (
              <Dropped key={item.name} item={item} />
            ))}
          </ul>
        </section>
      )}
      {kept.unused.length > 0 && (
        <ul aria-label="Tutorials whose calls were not looked at" className="flex flex-col gap-0.5 text-xs text-muted-foreground">
          {kept.unused.map((item) => (
            <li key={item.tutorial} className="break-words">
              <span className="break-all">{item.tutorial}</span>: {item.reason}
            </li>
          ))}
        </ul>
      )}
      {!kept.complete && (
        <Aside>This making did not come to its end, because it was stopped or failed. The tools that were made are kept, and the next making replaces them.</Aside>
      )}
      <p className="text-xs text-muted-foreground">{tools.meaning} A conversation is given the tools when the agent is given to conversations, under In conversations below.</p>
      <ClearTools agent={agent} busy={busy} onCleared={onCleared} />
    </section>
  );
}

// The tools that are made of the calls the tutorials made: which would be made and which would not, making them in a container that
// has none of this machine in it, and each tool with the evidence for it
export function ToolsSection({
  agent,
  tools,
  busy,
  making,
  settling,
  jobs,
  onCleared,
  onStale,
}: Shared & {
  // The making that is at work, if there is one
  making: Job | undefined;
  // Whether a making has just ended well, and what the page shows of it is from before it did
  settling: boolean;
  jobs: JobsData;
  onCleared: (tools: PaperAgentTools) => void;
  // Looks at the agent and its tools again, as is done when the server says what the page shows is out of date
  onStale: () => void;
}) {
  const [draft, setDraft] = useState<ToolsDraft>(() => emptyTools(tools.limits));
  const { kept, preview } = tools;

  if (tools.reference === null) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="tools-no-reference">
        Run the tutorials first. Tools are made from the calls that they made.
      </p>
    );
  }
  if (settling) return <p className="text-sm text-muted-foreground">Looking at the tools…</p>;
  const finished = kept !== null && kept.complete;

  return (
    <div className="flex flex-col gap-4">
      {!tools.docker.ready && (
        <Aside tone="warning">
          {tools.docker.message ?? "Docker is not running."} Making tools takes it. They cannot be made until it is.
        </Aside>
      )}
      {making !== undefined && <JobOutput key={making.id} job={making} jobs={jobs} />}
      {/* What is kept while the tools are made is the account of a making that has begun, which is not one that did not come to its end.
          The server says that one goes on before the page has looked at the jobs */}
      {kept !== null && making === undefined && tools.job === null && (
        <KeptTools agent={agent} tools={tools} kept={kept} busy={busy} onCleared={onCleared} onStale={onStale} />
      )}
      {!finished && preview !== null && preview.candidates.length === 0 && (
        <section className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="tools-none">
          <h3 className="text-sm font-medium">There is nothing to make</h3>
          <p className="text-sm">No function that the tutorials called can be made into a tool.</p>
          <Preview tools={tools} />
        </section>
      )}
      {!finished && preview !== null && preview.candidates.length > 0 && (
        <>
          <Preview tools={tools} />
          <MakeForm
            agent={agent}
            tools={tools}
            busy={busy || making !== undefined || tools.job !== null}
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
