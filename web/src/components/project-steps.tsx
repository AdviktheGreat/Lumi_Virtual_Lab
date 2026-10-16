"use client";

import { Fragment, useEffect, useId, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { CodeBlock } from "@/components/code";
import { Looked } from "@/components/looked";
import { Text, Turns } from "@/components/said";
import { useServer } from "@/components/server-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { usageText } from "@/lib/benchmarks";
import { count } from "@/lib/checks";
import { formatCost, formatDuration } from "@/lib/format";
import { ROWS_SHOWN, stepStatusLabel, stepTitle } from "@/lib/projects";
import type { Project, ProjectStep, ProjectStepRow } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

function Detail({ step }: { step: ProjectStep }) {
  const usage = usageText(step.usage);

  return (
    <div className="flex flex-col gap-3">
      <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
        {step.elapsed !== null && (
          <div className="flex gap-1">
            <dt className="text-muted-foreground">Time taken:</dt>
            <dd>{formatDuration(step.elapsed) || "not known"}</dd>
          </div>
        )}
        {usage && (
          <div className="flex gap-1">
            <dt className="text-muted-foreground">Used:</dt>
            <dd>{usage}</dd>
          </div>
        )}
        {step.attempts !== null && (
          <div className="flex gap-1">
            <dt className="text-muted-foreground">Tries to get the code to run:</dt>
            <dd>
              {step.attempts}, and it {step.succeeded ? "worked" : "did not"}
            </dd>
          </div>
        )}
      </dl>
      {step.error && (
        <p role="alert" className="break-words text-xs text-destructive">
          {step.error}
        </p>
      )}
      {step.code !== null && step.code.length > 0 && (
        <div className="flex flex-col gap-3">
          {step.code.map((file) => (
            <div key={file.filename} className="flex flex-col gap-2">
              <h3 className="break-words text-xs font-medium">{file.filename}</h3>
              <CodeBlock code={file.contents} language={file.language || null} foldAfter={12} />
              {file.output && <Text label={`What ${file.filename} printed`}>{file.output}</Text>}
            </div>
          ))}
        </div>
      )}
      {step.output !== null && step.output !== undefined && (
        <Text label="What the step produced">{JSON.stringify(step.output, null, 2)}</Text>
      )}
      {step.turns !== null && step.turns.length > 0 && (
        <Turns label="What was said in the step" turns={step.turns} truncated={step.truncated} />
      )}
    </div>
  );
}

// A step of a project, which is read from the server when it is asked for, as it holds what was said and what was run
function StepDetail({ project, name }: { project: string; name: string }) {
  const { report } = useServer();
  const [state, setState] = useState<Loaded<ProjectStep>>({ kind: "loading" });
  const [looks, setLooks] = useState(0);

  useEffect(() => {
    const abort = new AbortController();
    api.projectStep(project, name, abort.signal).then(
      (value) => setState({ kind: "ready", value }),
      (error: unknown) => {
        if (abort.signal.aborted) return;
        report(error);
        setState({ kind: "failed", error });
      },
    );

    return () => abort.abort();
  }, [project, name, report, looks]);

  return (
    <Looked
      state={state}
      label={`Reading ${stepTitle(name)}`}
      failure="The step could not be read."
      onRetry={() => {
        setState({ kind: "loading" });
        setLooks((was) => was + 1);
      }}
    >
      {(value) => <Detail step={value} />}
    </Looked>
  );
}

function StepRow({ project, row }: { project: string; row: ProjectStepRow }) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const title = stepTitle(row.name);

  return (
    <Fragment>
      <tr className="odd:bg-muted/30 align-top" data-testid="project-step">
        <td className="break-words px-2.5 py-1.5 font-medium">{title}</td>
        <td className="whitespace-nowrap px-2.5 py-1.5">
          <Badge variant={row.status === "failed" ? "destructive" : "outline"}>{stepStatusLabel(row.status)}</Badge>
        </td>
        <td className="whitespace-nowrap px-2.5 py-1.5 text-right tabular-nums">{formatCost(row.cost) || "–"}</td>
        <td className="whitespace-nowrap px-2.5 py-1.5 text-right tabular-nums">{row.elapsed === null ? "–" : formatDuration(row.elapsed) || "–"}</td>
        <td className="px-1 py-1">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setOpen((was) => !was)}
            aria-expanded={open}
            aria-controls={open ? detailId : undefined}
            aria-label={`${open ? "Hide" : "Show"} step ${title}`}
          >
            {open ? <ChevronDown /> : <ChevronRight />}
          </Button>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5} className="px-2.5 pb-3 pt-1">
            <div id={detailId}>
              <StepDetail project={project} name={row.name} />
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

// Each step the project took, in the order it took them, which is a meeting or code that was written and run, and what each
// cost, a few at a time
export function Steps({ project }: { project: Project }) {
  const [shown, setShown] = useState(ROWS_SHOWN);
  const { steps } = project;
  if (steps.length === 0) return <p className="text-sm text-muted-foreground">No step has been taken yet.</p>;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground" role="status">
        {steps.length > shown ? `The first ${shown} of ${count(steps.length, "step")}.` : `${count(steps.length, "step")}.`}
      </p>
      <div className="max-h-[32rem] overflow-auto rounded-lg border border-border">
        <table aria-label="Steps" className="w-full border-collapse text-xs">
          <thead className="sticky top-0 z-10 bg-muted">
            <tr>
              <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                Step
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                Result
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                Cost
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                Time
              </th>
              <th scope="col" className="w-8 px-1 py-1.5">
                <span className="sr-only">Details</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {steps.slice(0, shown).map((row) => (
              <StepRow key={row.name} project={project.id} row={row} />
            ))}
          </tbody>
        </table>
      </div>
      {steps.length > shown && (
        <div>
          <Button variant="outline" size="sm" onClick={() => setShown((was) => was + ROWS_SHOWN)}>
            Show {Math.min(ROWS_SHOWN, steps.length - shown)} more
          </Button>
        </div>
      )}
    </div>
  );
}
