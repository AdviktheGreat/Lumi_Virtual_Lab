"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { describedBy, Field } from "@/components/settings-fields";
import { useServer } from "@/components/server-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Radio } from "@/components/ui/radio";
import { api } from "@/lib/api";
import {
  checkRun,
  describeCode,
  describeSolver,
  EMPTY_RUN,
  MAX_RUN_TITLE,
  roundsText,
  runFacts,
  SUBSET_LABELS,
  TAKES_IMAGES,
  TAKES_SUBSET,
  TAKES_TASKS,
  type RunDraft,
} from "@/lib/benchmarks";
import { count } from "@/lib/checks";
import type { BenchmarkInfo, BenchmarkRunEntry, BenchmarksList } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";

// The page of a run, which is named in the address's query, as a conversation is
export const runAddress = (id: string) => `/benchmarks?id=${encodeURIComponent(id)}`;

function RunRow({ run, benchmark }: { run: BenchmarkRunEntry; benchmark: string }) {
  return (
    <li className="flex flex-col gap-1.5 rounded-xl border border-border bg-card p-4 transition-colors hover:border-ring/50" data-testid="benchmark-run">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="min-w-0 break-words text-sm font-medium">
          <Link href={runAddress(run.id)} className="rounded-sm outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
            {run.title}
          </Link>
        </h3>
        {run.job !== null && <Badge variant="secondary">Answering</Badge>}
      </div>
      <p className="text-xs text-muted-foreground">
        {benchmark} · {describeSolver(run)}
      </p>
      <p className="text-xs text-muted-foreground">{runFacts(run)}</p>
    </li>
  );
}

// The runs there are, the latest first
export function RunList({ list }: { list: BenchmarksList }) {
  if (list.runs.length === 0) return <p className="text-sm text-muted-foreground">No run has answered a benchmark yet. Make one below.</p>;
  const titles = new Map(list.benchmarks.map((benchmark) => [benchmark.id, benchmark.title]));

  return (
    <ul aria-label="Runs" className="flex flex-col gap-2">
      {list.runs.map((run) => (
        <RunRow key={run.id} run={run} benchmark={titles.get(run.benchmark) ?? run.benchmark} />
      ))}
    </ul>
  );
}

function questionsOf(benchmark: BenchmarkInfo): string {
  return benchmark.questions === null ? "" : ` (${count(benchmark.questions, "question")})`;
}

// Which of a benchmark's tasks, or which of its questions, a run asks, for the benchmarks that can be narrowed that way
function Narrowing({
  benchmark,
  draft,
  problems,
  busy,
  field,
  change,
}: {
  benchmark: BenchmarkInfo;
  draft: RunDraft;
  problems: Partial<Record<string, string>>;
  busy: boolean;
  field: (name: string) => string;
  change: (part: Partial<RunDraft>) => void;
}) {
  if (TAKES_TASKS.includes(benchmark.id)) {
    return (
      <fieldset className="flex flex-col gap-1.5" disabled={busy} aria-describedby={problems.tasks ? field("tasks-problem") : undefined}>
        <legend className="mb-1.5 text-sm font-medium">Tasks</legend>
        {(benchmark.tasks ?? []).map((task) => (
          <label key={task.name} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={!draft.left.includes(task.name)}
              onChange={(event) =>
                change({ left: event.target.checked ? draft.left.filter((name) => name !== task.name) : [...draft.left, task.name] })
              }
            />
            <span className="min-w-0 break-words">{task.name}</span>
            <span className="text-xs text-muted-foreground">{count(task.questions, "question")}</span>
          </label>
        ))}
        {problems.tasks && (
          <p id={field("tasks-problem")} role="alert" className="text-xs text-destructive">
            {problems.tasks}
          </p>
        )}
      </fieldset>
    );
  }
  if (TAKES_SUBSET.includes(benchmark.id)) {
    const summary = benchmark.subsets?.find((subset) => subset.id === draft.subset)?.summary;

    return (
      <Field id={field("subset")} label="Which questions" hint={summary}>
        <NativeSelect
          id={field("subset")}
          value={draft.subset}
          onChange={(event) => change({ subset: event.target.value as RunDraft["subset"] })}
          disabled={busy}
          aria-describedby={summary ? describedBy(field("subset"), { hint: true }) : undefined}
        >
          {(benchmark.subsets ?? []).map((subset) => (
            <option key={subset.id} value={subset.id}>
              {SUBSET_LABELS[subset.id] ?? subset.id} ({count(subset.questions, "question")})
            </option>
          ))}
        </NativeSelect>
      </Field>
    );
  }
  if (TAKES_IMAGES.includes(benchmark.id)) {
    return (
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={draft.leaveOutImages} onChange={(event) => change({ leaveOutImages: event.target.checked })} disabled={busy} />
        Leave out the questions that refer to an image
        {benchmark.images !== null && <span className="text-xs text-muted-foreground">({benchmark.images} of them)</span>}
      </label>
    );
  }

  return null;
}

// Makes a run, which has answered nothing yet: it says which benchmark, who answers, and how many questions, and the
// answering is started from its own page, where how much it may spend is said
export function NewRun({ list }: { list: BenchmarksList }) {
  const { report } = useServer();
  const router = useRouter();
  const id = useId();
  const [draft, setDraft] = useState<RunDraft>(EMPTY_RUN);
  const [tried, setTried] = useState(false);
  const attempt = useAttempt(report);
  const checked = checkRun(draft, list);
  const problems = tried ? checked.problems : {};
  const field = (name: string) => `${id}-${name}`;
  const benchmark = list.benchmarks.find((candidate) => candidate.id === draft.benchmark) ?? list.benchmarks[0];
  const ready = list.files.ready;

  function change(part: Partial<RunDraft>) {
    setDraft((was) => ({ ...was, ...part }));
  }

  async function make() {
    setTried(true);
    const body = checked.value;
    if (body === null) return;
    const run = await attempt.run(() => api.makeBenchmarkRun(body));
    if (run) router.push(runAddress(run.id));
  }

  return (
    <form
      aria-label="Make a run"
      onSubmit={(event) => {
        event.preventDefault();
        void make();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <Field id={field("title")} label="Title" hint="What the run is called, so that you can find it again." problem={problems.title}>
        <Input
          id={field("title")}
          value={draft.title}
          onChange={(event) => change({ title: event.target.value })}
          maxLength={MAX_RUN_TITLE * 4}
          autoComplete="off"
          readOnly={attempt.busy}
          aria-invalid={problems.title !== undefined}
          aria-describedby={describedBy(field("title"), { hint: true, problem: problems.title !== undefined })}
        />
      </Field>

      <fieldset className="flex flex-col gap-2" disabled={attempt.busy}>
        <legend className="mb-1.5 text-sm font-medium">Benchmark</legend>
        {list.benchmarks.map((candidate) => (
          <label key={candidate.id} className="flex items-start gap-2 text-sm">
            <Radio
              name={field("benchmark")}
              checked={draft.benchmark === candidate.id}
              onChange={() => change({ benchmark: candidate.id })}
              className="mt-0.5"
            />
            <span className="flex min-w-0 flex-col">
              <span>
                {candidate.title}
                <span className="text-muted-foreground">{questionsOf(candidate)}</span>
              </span>
              <span className="text-xs text-muted-foreground">{candidate.summary}</span>
            </span>
          </label>
        ))}
      </fieldset>

      {ready && benchmark && <Narrowing benchmark={benchmark} draft={draft} problems={problems} busy={attempt.busy} field={field} change={change} />}

      <fieldset className="flex flex-col gap-2" disabled={attempt.busy}>
        <legend className="mb-1.5 text-sm font-medium">Who answers</legend>
        {list.solvers.map((solver) => (
          <label key={solver.id} className="flex items-start gap-2 text-sm">
            <Radio name={field("solver")} checked={draft.solver === solver.id} onChange={() => change({ solver: solver.id })} className="mt-0.5" />
            <span className="flex min-w-0 flex-col">
              <span>{solver.title}</span>
              <span className="text-xs text-muted-foreground">{solver.summary}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id={field("rounds")}
          label={draft.solver === "team" ? "Rounds of discussion" : "Rounds of criticism"}
          hint={`Blank is ${draft.solver === "team" ? roundsText("team", 1) : roundsText("single", 0)}. Up to ${list.max_rounds}.`}
          problem={problems.rounds}
        >
          <Input
            id={field("rounds")}
            value={draft.rounds}
            onChange={(event) => change({ rounds: event.target.value })}
            inputMode="numeric"
            autoComplete="off"
            readOnly={attempt.busy}
            aria-invalid={problems.rounds !== undefined}
            aria-describedby={describedBy(field("rounds"), { hint: true, problem: problems.rounds !== undefined })}
          />
        </Field>
        <Field
          id={field("limit")}
          label="How many questions"
          hint="Blank is all of them. A number is the first that many, which is a way to try a run cheaply."
          problem={problems.limit}
        >
          <Input
            id={field("limit")}
            value={draft.limit}
            onChange={(event) => change({ limit: event.target.value })}
            inputMode="numeric"
            autoComplete="off"
            readOnly={attempt.busy}
            aria-invalid={problems.limit !== undefined}
            aria-describedby={describedBy(field("limit"), { hint: true, problem: problems.limit !== undefined })}
          />
        </Field>
      </div>

      <p className="text-xs text-muted-foreground">
        The questions are answered by {list.model}, and {describeCode(list.code)}, as the settings say now. The run keeps both.
      </p>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={attempt.busy || !ready}>
          <Plus />
          {attempt.busy ? "Making…" : "Make the run"}
        </Button>
        {!ready && <span className="text-xs text-muted-foreground">Fetch the files first.</span>}
      </div>
    </form>
  );
}
