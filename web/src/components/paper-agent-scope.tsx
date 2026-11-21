"use client";

import { useId, useState } from "react";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { ScopeFields } from "@/components/paper-agent-scope-fields";
import { ScopeResult } from "@/components/paper-agent-scope-result";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cardVersion, checkScope, EMPTY_SCOPE_DRAFT, type ScopeDraft } from "@/lib/paperagent-scope";
import type { MethodCard, PaperAgent, ScopeCheck } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";

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
        {current !== null && <ScopeResult check={current} />}
      </div>
    </section>
  );
}
