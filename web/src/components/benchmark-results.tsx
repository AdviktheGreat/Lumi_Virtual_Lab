"use client";

import { Fragment, useId, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { QuestionDetail } from "@/components/benchmark-question";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import {
  filterRows,
  OUTCOME_LABELS,
  OUTCOMES,
  outcomeOf,
  overallMetrics,
  percent,
  ROWS_SHOWN,
  type Outcome,
} from "@/lib/benchmarks";
import { count } from "@/lib/checks";
import { formatCost } from "@/lib/format";
import type { BenchmarkQuestionRow, BenchmarkRun } from "@/lib/types";

// How right the run was: the benchmark's measures over what has been answered, and, where there is more than one task,
// how right it was in each
export function Scores({ run }: { run: BenchmarkRun }) {
  if (run.finished === 0) return <p className="text-sm text-muted-foreground">Nothing is scored until some questions have been answered.</p>;
  const measures = overallMetrics(run.metrics);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-muted-foreground">
        Scored over the {count(run.finished, "question")} answered so far, of {run.questions}.
      </p>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Scores">
        {measures.map((measure) => (
          <div key={measure.name} className="flex flex-col rounded-lg border border-border p-3" data-testid={`benchmark-measure-${measure.name}`}>
            <dt className="text-xs text-muted-foreground">{measure.label}</dt>
            <dd className="text-lg font-semibold tabular-nums">{percent(measure.value)}</dd>
          </div>
        ))}
      </dl>
      {run.tasks.length > 1 && (
        <div className="max-h-72 overflow-auto rounded-lg border border-border">
          <table aria-label="Tasks" className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-muted">
              <tr>
                <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                  Task
                </th>
                <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                  Answered
                </th>
                <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                  Accuracy
                </th>
              </tr>
            </thead>
            <tbody>
              {run.tasks.map((task) => (
                <tr key={task.task} className="odd:bg-muted/30" data-testid="benchmark-task">
                  <td className="break-words px-2.5 py-1">{task.task}</td>
                  <td className="whitespace-nowrap px-2.5 py-1 text-right tabular-nums">
                    {task.finished} of {task.questions}
                  </td>
                  <td className="px-2.5 py-1 text-right tabular-nums">{percent(task.accuracy)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function OutcomeBadge({ row }: { row: BenchmarkQuestionRow }) {
  const outcome = outcomeOf(row);

  return <Badge variant={outcome === "failed" || outcome === "wrong" ? "destructive" : outcome === "right" ? "secondary" : "outline"}>{OUTCOME_LABELS[outcome]}</Badge>;
}

function QuestionRow({ run, row }: { run: string; row: BenchmarkQuestionRow }) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const answered = row.state !== "unanswered";

  return (
    <Fragment>
      <tr className="odd:bg-muted/30 align-top" data-testid="benchmark-question">
        <td className="px-2.5 py-1.5">
          <div className="break-words font-medium">
            {row.task} · {row.id}
          </div>
          {row.prompt && <div className="break-words text-muted-foreground">{row.prompt}</div>}
        </td>
        <td className="whitespace-nowrap px-2.5 py-1.5">
          <OutcomeBadge row={row} />
        </td>
        <td className="break-words px-2.5 py-1.5">{answered ? (row.answer ?? "–") : "–"}</td>
        <td className="break-words px-2.5 py-1.5">{row.correct_answer ?? "–"}</td>
        <td className="whitespace-nowrap px-2.5 py-1.5 text-right tabular-nums">{formatCost(row.cost) || "–"}</td>
        <td className="px-1 py-1">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setOpen((was) => !was)}
            aria-expanded={open}
            aria-controls={open ? detailId : undefined}
            aria-label={`${open ? "Hide" : "Show"} question ${row.key}`}
          >
            {open ? <ChevronDown /> : <ChevronRight />}
          </Button>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={6} className="px-2.5 pb-3 pt-1">
            <div id={detailId}>
              <QuestionDetail run={run} row={row} />
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

// Each question of a run, and how it was answered, which can be narrowed to a task, or to the questions that were right or
// wrong, and of which a few are shown at a time
export function Questions({ run }: { run: BenchmarkRun }) {
  const id = useId();
  const [task, setTask] = useState("");
  const [outcome, setOutcome] = useState<Outcome | "all">("all");
  const [shown, setShown] = useState(ROWS_SHOWN);
  const rows = filterRows(run.results, task, outcome);
  if (run.results.length === 0) return <p className="text-sm text-muted-foreground">This run has no questions to show.</p>;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        {run.tasks.length > 1 && (
          <div className="flex min-w-40 flex-1 flex-col gap-1.5">
            <label htmlFor={`${id}-task`} className="text-xs font-medium">
              Task
            </label>
            <NativeSelect
              id={`${id}-task`}
              value={task}
              onChange={(event) => {
                setTask(event.target.value);
                setShown(ROWS_SHOWN);
              }}
            >
              <option value="">All tasks</option>
              {run.tasks.map((candidate) => (
                <option key={candidate.task} value={candidate.task}>
                  {candidate.task}
                </option>
              ))}
            </NativeSelect>
          </div>
        )}
        <div className="flex min-w-40 flex-1 flex-col gap-1.5">
          <label htmlFor={`${id}-outcome`} className="text-xs font-medium">
            How it was answered
          </label>
          <NativeSelect
            id={`${id}-outcome`}
            value={outcome}
            onChange={(event) => {
              setOutcome(event.target.value as Outcome | "all");
              setShown(ROWS_SHOWN);
            }}
          >
            <option value="all">Every question</option>
            {OUTCOMES.map((candidate) => (
              <option key={candidate} value={candidate}>
                {OUTCOME_LABELS[candidate]}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No question was answered like that.</p>
      ) : (
        <>
          <p className="text-xs text-muted-foreground" role="status">
            {rows.length > shown ? `The first ${shown} of ${count(rows.length, "question")}.` : `${count(rows.length, "question")}.`}
          </p>
          <div className="max-h-[32rem] overflow-auto rounded-lg border border-border">
            <table aria-label="Questions" className="w-full border-collapse text-xs">
              <thead className="sticky top-0 z-10 bg-muted">
                <tr>
                  <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                    Question
                  </th>
                  <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                    Result
                  </th>
                  <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                    Answer
                  </th>
                  <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                    Right answer
                  </th>
                  <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                    Cost
                  </th>
                  <th scope="col" className="w-8 px-1 py-1.5">
                    <span className="sr-only">Details</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, shown).map((row) => (
                  <QuestionRow key={row.key} run={run.id} row={row} />
                ))}
              </tbody>
            </table>
          </div>
          {rows.length > shown && (
            <div>
              <Button variant="outline" size="sm" onClick={() => setShown((was) => was + ROWS_SHOWN)}>
                Show {Math.min(ROWS_SHOWN, rows.length - shown)} more
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
