"use client";

import { useEffect, useState } from "react";
import { Looked } from "@/components/looked";
import { useServer } from "@/components/server-provider";
import { api } from "@/lib/api";
import { usageText } from "@/lib/benchmarks";
import { formatDuration } from "@/lib/format";
import type { BenchmarkQuestion, BenchmarkQuestionRow } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

function Text({ label, children }: { label: string; children: string }) {
  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-xs font-medium">{label}</h3>
      <pre
        tabIndex={0}
        aria-label={label}
        className="max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/60 p-2 font-sans text-xs outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {children}
      </pre>
    </div>
  );
}

function Detail({ question }: { question: BenchmarkQuestion }) {
  const usage = usageText(question.usage);

  return (
    <div className="flex flex-col gap-3">
      {question.prompt === null ? (
        <p className="text-xs text-muted-foreground">The question is not shown, as the files of the benchmarks cannot be read.</p>
      ) : (
        <Text label="What was asked">{question.prompt}</Text>
      )}
      <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
        <div className="flex gap-1">
          <dt className="text-muted-foreground">The answer that was read:</dt>
          <dd className="min-w-0 break-words font-medium">{question.answer ?? "none"}</dd>
        </div>
        <div className="flex gap-1">
          <dt className="text-muted-foreground">The right answer:</dt>
          <dd className="min-w-0 break-words font-medium">{question.correct_answer ?? "not known"}</dd>
        </div>
        {question.elapsed !== null && (
          <div className="flex gap-1">
            <dt className="text-muted-foreground">Time taken:</dt>
            <dd>{formatDuration(question.elapsed) || "not known"}</dd>
          </div>
        )}
        {usage && (
          <div className="flex gap-1">
            <dt className="text-muted-foreground">Used:</dt>
            <dd>{usage}</dd>
          </div>
        )}
      </dl>
      {question.error && (
        <p role="alert" className="break-words text-xs text-destructive">
          {question.error}
        </p>
      )}
      {question.output && <Text label="What was read from it">{JSON.stringify(question.output, null, 2)}</Text>}
      {question.turns !== null && question.turns.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-medium">What was said in answering it</h3>
          <ol aria-label="What was said in answering it" className="flex flex-col gap-2">
            {question.turns.map((turn, number) => (
              <li key={number} className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted-foreground">{turn.agent}</span>
                <pre
                  tabIndex={0}
                  aria-label={`${turn.agent} said`}
                  className="max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/60 p-2 font-sans text-xs outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  {turn.message}
                </pre>
              </li>
            ))}
          </ol>
          {question.truncated && <p className="text-xs text-muted-foreground">What was said is cut short here.</p>}
        </div>
      )}
    </div>
  );
}

// A question of a run, which is read from the server when it is asked for, as it holds what was said in answering it
export function QuestionDetail({ run, row }: { run: string; row: BenchmarkQuestionRow }) {
  const { report } = useServer();
  const [state, setState] = useState<Loaded<BenchmarkQuestion>>({ kind: "loading" });
  const [looks, setLooks] = useState(0);

  useEffect(() => {
    const abort = new AbortController();
    api.benchmarkQuestion(run, row.task, row.id, abort.signal).then(
      (value) => setState({ kind: "ready", value }),
      (error: unknown) => {
        if (abort.signal.aborted) return;
        report(error);
        setState({ kind: "failed", error });
      },
    );

    return () => abort.abort();
  }, [run, row.task, row.id, report, looks]);

  return (
    <Looked
      state={state}
      label={`Reading question ${row.key}`}
      failure="The question could not be read."
      onRetry={() => {
        setState({ kind: "loading" });
        setLooks((was) => was + 1);
      }}
    >
      {(value) => <Detail question={value} />}
    </Looked>
  );
}
