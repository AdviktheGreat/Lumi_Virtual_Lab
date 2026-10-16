"use client";

import { useEffect, useId, useState } from "react";
import { Code, CodeXml, Trash2, Wand2 } from "lucide-react";
import { Looked } from "@/components/looked";
import { ProblemNotice } from "@/components/messages";
import { describedBy, Field } from "@/components/settings-fields";
import { useServer } from "@/components/server-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { formatCost } from "@/lib/format";
import {
  checkFunctions,
  count,
  EMPTY_FUNCTIONS,
  functionLabel,
  MAX_FUNCTIONS,
  type FunctionsDraft,
} from "@/lib/papers";
import type { PaperFunction, PaperFunctionRow, PaperRun } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt, type Looked as LookedAt } from "@/lib/use-papers";
import type { Loaded } from "@/lib/use-settings-data";

interface Shared {
  run: PaperRun;
  working: boolean;
  onChanged: LookedAt<PaperRun>["set"];
}

// The code of a function, which is read from the server when it is asked for, so that it is read before it is relied on
function FunctionCode({ run, name }: { run: string; name: string }) {
  const { report } = useServer();
  const [state, setState] = useState<Loaded<PaperFunction>>({ kind: "loading" });
  const [looks, setLooks] = useState(0);

  useEffect(() => {
    const abort = new AbortController();
    api.paperFunction(run, name, abort.signal).then(
      (value) => setState({ kind: "ready", value }),
      (error: unknown) => {
        if (abort.signal.aborted) return;
        report(error);
        setState({ kind: "failed", error });
      },
    );

    return () => abort.abort();
  }, [run, name, report, looks]);

  return (
    <Looked
      state={state}
      label={`Reading the code of ${name}`}
      failure="The code could not be read."
      onRetry={() => {
        setState({ kind: "loading" });
        setLooks((was) => was + 1);
      }}
    >
      {(value) => (
        <div className="flex flex-col gap-2">
          {value.brief && <p className="whitespace-pre-wrap break-words text-xs text-muted-foreground">{value.brief}</p>}
          {value.problems.length > 0 && (
            <ul aria-label="What was found wrong with it" className="list-disc pl-5 text-xs text-destructive">
              {value.problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          )}
          {value.source === null ? (
            <p className="text-xs text-muted-foreground">There is no code to show.</p>
          ) : (
            <pre
              tabIndex={0}
              aria-label={`Code of ${name}`}
              className="max-h-80 overflow-auto rounded-md bg-muted/60 p-2 font-mono text-xs outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {value.source}
            </pre>
          )}
        </div>
      )}
    </Looked>
  );
}

function FunctionRow({ run, row, working, onChanged }: Shared & { row: PaperFunctionRow }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [open, setOpen] = useState(false);
  const codeId = useId();

  async function remove() {
    const next = await attempt.run(() => api.removeFunction(run.id, row.name));
    if (next) onChanged(next);
  }

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="paper-function">
      <div className="flex items-start gap-2">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <code className="break-all text-sm font-medium">{row.name}</code>
            <Badge variant={row.status === "failed" ? "destructive" : row.status === "verified" ? "secondary" : "outline"}>
              {functionLabel(row.status)}
            </Badge>
          </div>
          <p className="break-words text-sm">{row.task}</p>
          <p className="text-xs text-muted-foreground">
            Found in {count(row.papers, "paper")}
            {row.modules.length > 0 && ` · uses ${row.modules.join(", ")}`}
            {row.cost !== null && ` · cost ${formatCost(row.cost) || "nothing"}`}
          </p>
          {row.error && <p className="break-words text-xs text-destructive">{row.error}</p>}
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => setOpen((was) => !was)}
          aria-expanded={open}
          aria-controls={open ? codeId : undefined}
          aria-label={`${open ? "Hide" : "Show"} the code of ${row.name}`}
        >
          {open ? <CodeXml /> : <Code />}
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => void remove()}
          disabled={working || attempt.busy}
          aria-label={`Delete ${row.name}`}
        >
          <Trash2 />
        </Button>
      </div>
      {open && (
        <div id={codeId}>
          <FunctionCode run={run.id} name={row.name} />
        </div>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
    </li>
  );
}

// Says how much writing the functions may cost, and which tasks they are for, and starts it
function WriteForm({ run, working, jobs }: Pick<Shared, "run" | "working"> & { jobs: JobsData }) {
  const { report } = useServer();
  const id = useId();
  const [draft, setDraft] = useState<FunctionsDraft>(EMPTY_FUNCTIONS);
  const [tried, setTried] = useState(false);
  const attempt = useAttempt(report);
  const checked = checkFunctions(draft);
  const problems = tried ? checked.problems : {};
  const unread = run.summary.papers === 0;
  const failures = run.functions.some((row) => row.status === "failed");

  function change(part: Partial<FunctionsDraft>) {
    setDraft((was) => ({ ...was, ...part }));
  }

  async function write() {
    setTried(true);
    const options = checked.value;
    if (options === null) return;
    const job = await attempt.run(() => api.writeFunctions(run.id, options));
    if (job) jobs.track(job);
  }

  return (
    <form
      aria-label="Write functions"
      onSubmit={(event) => {
        event.preventDefault();
        void write();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <p className="text-sm text-muted-foreground">
        Writes a function for each task that several of the papers share, the most common first, from what the papers say of it.
        Which tasks, and how many, is yours to choose. A function that is written already is not written again.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id={`${id}-budget`} label="Most it may spend, in dollars" problem={problems.budget}>
          <Input
            id={`${id}-budget`}
            value={draft.budget}
            onChange={(event) => change({ budget: event.target.value })}
            inputMode="decimal"
            autoComplete="off"
            aria-invalid={problems.budget !== undefined}
            aria-describedby={describedBy(`${id}-budget`, { problem: problems.budget !== undefined })}
          />
        </Field>
        <Field
          id={`${id}-each`}
          label="Most one function may spend"
          hint="Optional. A function that would spend more is not written."
          problem={problems.perFunction}
        >
          <Input
            id={`${id}-each`}
            value={draft.perFunction}
            onChange={(event) => change({ perFunction: event.target.value })}
            inputMode="decimal"
            autoComplete="off"
            aria-invalid={problems.perFunction !== undefined}
            aria-describedby={describedBy(`${id}-each`, { hint: true, problem: problems.perFunction !== undefined })}
          />
        </Field>
        <Field id={`${id}-limit`} label="How many functions" hint={`Up to ${MAX_FUNCTIONS}.`} problem={problems.limit}>
          <Input
            id={`${id}-limit`}
            value={draft.limit}
            onChange={(event) => change({ limit: event.target.value })}
            inputMode="numeric"
            autoComplete="off"
            aria-invalid={problems.limit !== undefined}
            aria-describedby={describedBy(`${id}-limit`, { hint: true, problem: problems.limit !== undefined })}
          />
        </Field>
        <Field
          id={`${id}-fewest`}
          label="Fewest papers a task is found in"
          hint="Tasks found in fewer papers than this are left out."
          problem={problems.minPapers}
        >
          <Input
            id={`${id}-fewest`}
            value={draft.minPapers}
            onChange={(event) => change({ minPapers: event.target.value })}
            inputMode="numeric"
            autoComplete="off"
            aria-invalid={problems.minPapers !== undefined}
            aria-describedby={describedBy(`${id}-fewest`, { hint: true, problem: problems.minPapers !== undefined })}
          />
        </Field>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={draft.verify} onChange={(event) => change({ verify: event.target.checked })} />
        Import each function in a container to check it, which needs Docker
      </label>
      {failures && (
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={draft.retryFailed} onChange={(event) => change({ retryFailed: event.target.checked })} />
          Write again the functions that failed
        </label>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={working || attempt.busy || unread}>
          <Wand2 />
          {attempt.busy ? "Starting…" : "Write the functions"}
        </Button>
        {unread && <span className="text-xs text-muted-foreground">Read the papers first.</span>}
      </div>
    </form>
  );
}

// Whether the functions of a run that were written are given to the conversations that are made from now on
function Give({ run, onChanged }: Pick<Shared, "run" | "onChanged">) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const id = useId();

  async function give(given: boolean) {
    const next = await attempt.run(() => api.giveFunctions(run.id, given));
    if (next) onChanged(next);
  }

  return (
    <div className="flex flex-col gap-1">
      <label className="flex items-center gap-2 text-sm font-medium">
        <Checkbox
          checked={run.given}
          onChange={(event) => void give(event.target.checked)}
          disabled={attempt.busy}
          aria-describedby={id}
        />
        Give these functions to the conversations I start
      </label>
      <p id={id} className="text-xs text-muted-foreground">
        The lead can call the ones that passed as tools, in conversations that begin from now on. One that is already going is not given
        them.
      </p>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
    </div>
  );
}

// The functions written from what a run's papers share, and the way to write more and to give them to conversations
export function FunctionsSection({ run, working, onChanged, jobs }: Shared & { jobs: JobsData }) {
  return (
    <div className="flex flex-col gap-4">
      {run.functions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No function is written for this run yet.</p>
      ) : (
        <>
          <ul aria-label="Functions" className="flex flex-col gap-2">
            {run.functions.map((row) => (
              <FunctionRow key={row.name} run={run} row={row} working={working} onChanged={onChanged} />
            ))}
          </ul>
          <Give run={run} onChanged={onChanged} />
        </>
      )}
      <WriteForm run={run} working={working} jobs={jobs} />
    </div>
  );
}
