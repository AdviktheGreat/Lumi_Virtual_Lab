"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { api } from "@/lib/api";
import {
  describeArguments,
  describeBy,
  describeKept,
  describePreview,
  describeRunData,
  describeSeconds,
  describeSince,
  describeWhy,
  keptAs,
  RUN_STATE_LABELS,
} from "@/lib/bakeoff-runs";
import { timeAgo } from "@/lib/format";
import type { BakeoffRun, BakeoffRunState, BakeoffRunSummary } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";
import { cn } from "@/lib/utils";

// What is wrong with something that was run, which is set apart from what is not
const WARNING = "rounded-md border border-warning/60 bg-warning/15 px-1.5 py-0.5 text-foreground";

const STATE_BADGE: Record<BakeoffRunState, { variant: "default" | "secondary" | "outline" | "destructive"; className?: string }> = {
  ran: { variant: "secondary" },
  failed: { variant: "destructive" },
  not_run: { variant: "outline" },
};

// How the data was put against the card of the method's paper when the call was made
function describeScopeAtRun(scope: BakeoffRunSummary["scope"]): string {
  if (!scope.checked) return "Your data was not put against a card, so nothing was held against the method for it.";
  if (scope.outcome === "outside") {
    return scope.went_on
      ? "Your data was outside what its card says, and you had said to go on with it."
      : "Your data was outside what its card says.";
  }
  if (scope.outcome === "inside") return "Your data was inside what its card says.";

  return "What its card says does not cover everything about your data.";
}

// What came of running one method the last time: whether it gave an answer, what was called with what and who chose it, what it was
// run on, and the start of what it gave, with the way to ask for the rest. It says what ran, and not that what it gave is right.
export function RunSummary({ bakeoffId, run }: { bakeoffId: string; run: BakeoffRunSummary }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [whole, setWhole] = useState<BakeoffRun | null>(null);
  const why = describeWhy(run.state, run.why);
  const badge = STATE_BADGE[run.state];
  const seconds = describeSeconds(run.seconds);
  const argumentsText = describeArguments(run.arguments);

  async function showWhole() {
    const found = await attempt.run(() => api.bakeoffRun(bakeoffId, run.candidate));
    if (found) setWhole(found);
  }

  return (
    <div
      className="flex flex-col gap-2 rounded-lg border border-border p-3"
      data-testid="run-summary"
      data-state={run.state}
      data-why={run.why ?? ""}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-medium">The last run</h4>
        <Badge variant={badge.variant} className={cn(badge.className)} data-testid="run-state">
          {RUN_STATE_LABELS[run.state]}
        </Badge>
        {why !== null && <Badge variant="outline">{why}</Badge>}
        <span className="text-xs text-muted-foreground">{timeAgo(run.at)}</span>
      </div>
      {run.reason !== "" && <p className="whitespace-pre-wrap break-words text-sm">{run.reason}</p>}
      {run.since.length > 0 && (
        <ul aria-label="What is not as it was" className="flex flex-col gap-1" data-testid="run-since">
          {describeSince(run.since).map((line) => (
            <li key={line} className={cn("text-xs", WARNING)}>
              {line}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-col gap-1 text-xs text-muted-foreground">
        {run.tool !== null && (
          <p className="break-words">
            It called <span className="font-medium text-foreground">{run.tool.name}</span>, a tool of tier {run.tool.tier}, which calls{" "}
            <code>{run.tool.called}</code> in the code of its paper.
          </p>
        )}
        <p>{describeBy(run)}</p>
        {run.proposed !== null && run.proposed.reason !== "" && (
          <p className="break-words" data-testid="run-proposed-reason">
            What it said of why: {run.proposed.reason}
          </p>
        )}
        {run.data !== null && <p className="break-words">It was run on {describeRunData(run.data)}.</p>}
        <p>{describeScopeAtRun(run.scope)}</p>
        {run.scope.warnings.length > 0 && (
          <ul aria-label="What was said against its card" className="flex list-disc flex-col gap-0.5 pl-4">
            {run.scope.warnings.map((line) => (
              <li key={line} className="break-words">
                {line}
              </li>
            ))}
          </ul>
        )}
        {seconds !== "" && <p>It took {seconds}.</p>}
      </div>
      {run.tool !== null && argumentsText !== "" && (
        <details className="rounded-lg border border-border px-3 py-2">
          <summary className="cursor-pointer text-sm">The arguments it was called with</summary>
          <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words text-xs">{argumentsText}</pre>
        </details>
      )}
      {run.printed !== null && run.printed !== "" && (
        <details className="rounded-lg border border-border px-3 py-2">
          <summary className="cursor-pointer text-sm">What it printed</summary>
          <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words text-xs">{run.printed}</pre>
        </details>
      )}
      {run.result !== null && (
        <div className="flex flex-col gap-1.5" data-testid="run-result">
          <p className="text-sm">{describePreview(run.result)}</p>
          {whole === null ? (
            <>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted/50 p-2 text-xs" aria-label="The start of what it gave">
                {run.result.start}
                {run.result.cut ? "…" : ""}
              </pre>
              {run.result.cut && (
                <div>
                  <Button variant="outline" size="xs" onClick={() => void showWhole()} disabled={attempt.busy}>
                    {attempt.busy ? "Asking…" : "Show all that was kept of it"}
                  </Button>
                </div>
              )}
            </>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">{describeKept(keptAs(whole.result ?? { type: "" }))}.</p>
              <pre
                className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted/50 p-2 text-xs"
                aria-label="All that was kept of what it gave"
                data-testid="run-result-whole"
              >
                {JSON.stringify(whole.result, null, 2)}
              </pre>
              <div>
                <Button variant="outline" size="xs" onClick={() => setWhole(null)}>
                  Show only the start
                </Button>
              </div>
            </>
          )}
        </div>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <p className="text-xs text-muted-foreground">
        This says what was run, on what, and what it gave. It does not say that what it gave is right.
      </p>
    </div>
  );
}
