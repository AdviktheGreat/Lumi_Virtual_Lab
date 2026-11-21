"use client";

import { useId, useState } from "react";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { ScopeFields } from "@/components/paper-agent-scope-fields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { describeStatus } from "@/lib/paperagent-card";
import {
  cardVersion,
  checkScope,
  describeAspect,
  describeOutcome,
  describeReading,
  describeStatementPlace,
  describeStatementWhose,
  EMPTY_SCOPE_DRAFT,
  OUTCOME_TEXT,
  type ScopeDraft,
} from "@/lib/paperagent-scope";
import type { MethodCard, PaperAgent, ScopeCheck, ScopeOutcome, ScopeStatement } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";
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
function Result({ check }: { check: ScopeCheck }) {
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

// A form that puts what a person's data is against what the card says the method was used on, before a tool is run on it. It
// warns, with the card's words, and stops nothing. An answer is kept only while the card is as it was when it was given.
export function ScopeCheckSection({ agent, card }: { agent: PaperAgent; card: MethodCard }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [draft, setDraft] = useState<ScopeDraft>(EMPTY_SCOPE_DRAFT);
  const [tried, setTried] = useState(false);
  const [answer, setAnswer] = useState<{ check: ScopeCheck; version: string } | null>(null);
  const version = cardVersion(card);
  const checked = checkScope(draft);
  const problems = tried ? checked.problems : {};
  const current = answer !== null && answer.version === version ? answer.check : null;
  const set = (part: keyof ScopeDraft, value: string) => setDraft((was) => ({ ...was, [part]: value }));

  async function run() {
    setTried(true);
    const data = checked.value;
    if (data === null) return;
    const found = await attempt.run(() => api.checkPaperAgentScope(agent.id, data));
    if (found) setAnswer({ check: found, version });
  }

  return (
    <section aria-labelledby={`${id}-title`} className="flex flex-col gap-3" data-testid="scope-check">
      <div className="flex flex-col gap-1">
        <h3 id={`${id}-title`} className="text-sm font-medium">
          Check my data against the card
        </h3>
        <p className="text-sm text-muted-foreground">
          Say what your data is, any of it, and the card&apos;s statements of what the method was tested on are put against it before you run a
          tool on it. A program compares the words and the numbers. It warns, with the card&apos;s words, if your data is outside, and it
          stops nothing.
        </p>
        {card.scope.length === 0 && (
          <p className="text-xs text-muted-foreground">
            The card has no statement of what the method was tested on yet, so nothing can be told to be outside. Add one above.
          </p>
        )}
      </div>
      <form
        aria-label="Check my data against the card"
        onSubmit={(event) => {
          event.preventDefault();
          void run();
        }}
        className="flex flex-col gap-3 rounded-lg border border-border bg-muted/30 p-3"
      >
        <ScopeFields draft={draft} change={set} problems={problems} id={id} />
        {problems.form && (
          <p role="alert" className="text-xs text-destructive">
            {problems.form}
          </p>
        )}
        {attempt.problem && <ProblemNotice problem={attempt.problem} />}
        <div>
          <Button type="submit" size="sm" disabled={attempt.busy}>
            {attempt.busy ? "Checking…" : "Check it"}
          </Button>
        </div>
      </form>
      <div aria-live="polite" className="flex flex-col gap-2">
        {answer !== null && current === null && (
          <p className="text-sm text-muted-foreground" data-testid="scope-stale">
            The card has changed since you checked, so that answer is gone. Check again.
          </p>
        )}
        {current !== null && <Result check={current} />}
      </div>
    </section>
  );
}
