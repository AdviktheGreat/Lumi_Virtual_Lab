"use client";

import { Badge } from "@/components/ui/badge";
import { describeStatus } from "@/lib/paperagent-card";
import {
  describeAspect,
  describeOutcome,
  describeReading,
  describeStatementPlace,
  describeStatementWhose,
  OUTCOME_TEXT,
} from "@/lib/paperagent-scope";
import type { ScopeOutcome, ScopeStatement, ScopeView } from "@/lib/types";
import { cn } from "@/lib/utils";

// What an outcome looks like. Only outside is set apart, since it is the only one that is warned of.
const OUTCOME_STYLE: Record<ScopeOutcome, string> = {
  inside: "",
  outside: "border-warning/60 bg-warning/15 text-foreground",
  "not covered": "",
};

// The statements of the card that an answer is of, with whose each is and where it is in the paper
function Statements({ statements }: { statements: ScopeStatement[] }) {
  if (statements.length === 0) return null;

  return (
    <ul className="flex flex-col gap-1.5" aria-label="What the card says">
      {statements.map((statement) => {
        const place = describeStatementPlace(statement);

        return (
          <li key={statement.id} className="flex flex-col gap-0.5" data-testid="scope-statement" data-by={statement.by}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 break-words text-sm font-medium">{statement.value}</span>
              {statement.by === "person" ? (
                <Badge variant="secondary">{describeStatementWhose(statement)}</Badge>
              ) : (
                <span className="text-xs text-muted-foreground">{describeStatementWhose(statement)}</span>
              )}
              {place !== null && <span className="text-xs text-muted-foreground">{place}</span>}
            </div>
            {statement.quote !== "" && (
              <blockquote className="break-words border-l-2 border-border pl-2 text-xs text-muted-foreground">{statement.quote}</blockquote>
            )}
          </li>
        );
      })}
    </ul>
  );
}

// What the card said of the data that was put against it: whether it is inside, outside, or not covered, the warnings with the card's
// words and the paper's, what each thing was put against, and how far the card is to be trusted
export function ScopeResult({ check }: { check: ScopeView }) {
  const outcome = describeOutcome(check);
  const status = describeStatus(check.card);
  const reading = describeReading(check);

  return (
    <div className="flex flex-col gap-3" data-testid="scope-result" data-outcome={check.outcome}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className={cn(OUTCOME_STYLE[check.outcome])}>
          {outcome.label}
        </Badge>
        <p className="min-w-0 text-sm">{outcome.text}</p>
      </div>
      {check.warnings.length > 0 && (
        <ul aria-label="Warnings" className="flex flex-col gap-2">
          {check.warnings.map((warning) => (
            <li key={warning} className="rounded-lg border border-warning/60 bg-warning/15 px-3 py-2 text-sm" data-testid="scope-warning">
              {warning}
            </li>
          ))}
        </ul>
      )}
      <ul aria-label="What you said, put against the card" className="flex flex-col gap-2">
        {check.aspects.map((answer) => (
          <li
            key={answer.aspect}
            className="flex flex-col gap-1.5 rounded-lg border border-border px-3 py-2"
            data-testid="scope-answer"
            data-aspect={answer.aspect}
            data-outcome={answer.outcome}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{describeAspect(answer.aspect)}</span>
              <span className="min-w-0 break-words text-sm">{answer.given}</span>
              <Badge variant="outline" className={cn(OUTCOME_STYLE[answer.outcome])}>
                {OUTCOME_TEXT[answer.outcome].label}
              </Badge>
            </div>
            {answer.reason !== "" && <p className="text-xs text-muted-foreground">{answer.reason}</p>}
            <Statements statements={answer.says} />
          </li>
        ))}
      </ul>
      {check.not_checked.length > 0 && (
        <details className="rounded-lg border border-border px-3 py-2">
          <summary className="cursor-pointer text-sm">What else the card says ({check.not_checked.length})</summary>
          <ul aria-label="What else the card says" className="flex flex-col gap-2 pt-2">
            {check.not_checked.map((part) => (
              <li key={part.aspect} className="flex flex-col gap-1">
                <span className="text-xs font-medium">{describeAspect(part.aspect)}, which you did not say anything of</span>
                <Statements statements={part.says} />
              </li>
            ))}
          </ul>
        </details>
      )}
      <div className="flex flex-col gap-1 text-xs text-muted-foreground">
        <p>
          {status.label}: {status.text}
        </p>
        {reading !== null && <p>{reading}</p>}
        {check.notes.map((note) => (
          <p key={note}>{note}</p>
        ))}
      </div>
    </div>
  );
}
