"use client";

import { useId, useState } from "react";
import { Loader2 } from "lucide-react";
import { Notice } from "@/components/messages";
import { Aside, describedBy, Field } from "@/components/settings-fields";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { problemOf, type Problem } from "@/lib/errors";
import { formatCost } from "@/lib/format";
import { belowSpent, checkLimits, limitsDraftOf, raisedBy, type CurrentLimits, type LimitsDraft } from "@/lib/limits";
import type { ChatLimits, LimitsChange } from "@/lib/types";

// The limits of a conversation, which are the most it may spend and what the lead may ask of the team in answering a
// message. Saving gives onSave what differs from what the conversation has, which may refuse it by throwing, and whose
// refusal is shown here, and which closes the dialog when it is done.
export function LimitsDialog({
  current,
  limits,
  spent,
  begun,
  onSave,
  onClose,
}: {
  current: CurrentLimits;
  // What the lead is given of the team's time unless it is told otherwise, and the most it can be given
  limits: ChatLimits;
  // What the conversation has spent, or null where it has not begun
  spent: number | null;
  // Whether this is the limits of a conversation that has begun, rather than of one that is about to
  begun: boolean;
  onSave: (changes: LimitsChange) => Promise<void>;
  onClose: () => void;
}) {
  const id = useId();
  const [draft, setDraft] = useState<LimitsDraft>(() => limitsDraftOf(current));
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const { changes, problems } = checkLimits(draft, current, limits);
  const changed = Object.keys(changes).length > 0;
  const costId = `${id}-cost`;
  const sessionsId = `${id}-sessions`;
  const roundsId = `${id}-rounds`;

  function edit(next: Partial<LimitsDraft>) {
    setDraft((was) => ({ ...was, ...next }));
    setProblem(null);
  }

  async function save() {
    if (saving || !changed || Object.keys(problems).length > 0) return;
    setSaving(true);
    setProblem(null);
    try {
      await onSave(changes);
      onClose();
    } catch (error) {
      setProblem(problemOf(error));
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !saving && onClose()}>
      <DialogContent className="sm:max-w-md" data-testid="limits-dialog">
        <DialogHeader>
          <DialogTitle>Budget and limits</DialogTitle>
          <DialogDescription>
            {begun
              ? "The spending limit holds from the lead's next request, even while it works. How much of the team's time the lead may ask for holds from the next message."
              : "These hold for the conversation you begin. They can be changed from it, as it goes on."}
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-5"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <Field
            id={costId}
            label="Spending limit (US dollars)"
            problem={problems.cost}
            hint={
              spent !== null
                ? `Spent so far: ${formatCost(spent)}. Leave it empty for no limit.`
                : "The most the conversation may spend, the lead's requests and the team's. Leave it empty for no limit."
            }
          >
            <div className="flex flex-wrap items-center gap-2">
              <Input
                id={costId}
                value={draft.cost}
                onChange={(event) => edit({ cost: event.target.value })}
                inputMode="decimal"
                placeholder="No limit"
                aria-invalid={problems.cost !== undefined}
                aria-describedby={describedBy(costId, { hint: true, problem: problems.cost !== undefined })}
                autoComplete="off"
                autoFocus
                className="w-32"
              />
              {[1, 5].map((more) => (
                <Button
                  key={more}
                  type="button"
                  variant="outline"
                  size="sm"
                  data-testid={`raise-${more}`}
                  onClick={() => edit({ cost: raisedBy(draft.cost, more, spent) })}
                >
                  + ${more}
                </Button>
              ))}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                data-testid="no-limit"
                disabled={draft.cost.trim() === ""}
                onClick={() => edit({ cost: "" })}
              >
                No limit
              </Button>
            </div>
          </Field>
          {belowSpent(draft.cost, spent) && (
            <Aside tone="warning">That is below what has been spent, so the lead stops at its next request.</Aside>
          )}

          <Field
            id={sessionsId}
            label="Team sessions in one answer"
            problem={problems.sessions}
            hint={`How many times the lead may call the team together. 0 has the lead answer alone. Usually ${limits.max_delegations.default}.`}
          >
            <Input
              id={sessionsId}
              value={draft.sessions}
              onChange={(event) => edit({ sessions: event.target.value })}
              inputMode="numeric"
              aria-invalid={problems.sessions !== undefined}
              aria-describedby={describedBy(sessionsId, { hint: true, problem: problems.sessions !== undefined })}
              autoComplete="off"
              className="w-24"
            />
          </Field>

          <Field
            id={roundsId}
            label="Rounds in a team session"
            problem={problems.rounds}
            hint={`The most rounds of discussion the lead may ask for in one session. Usually ${limits.max_rounds.default}.`}
          >
            <Input
              id={roundsId}
              value={draft.rounds}
              onChange={(event) => edit({ rounds: event.target.value })}
              inputMode="numeric"
              aria-invalid={problems.rounds !== undefined}
              aria-describedby={describedBy(roundsId, { hint: true, problem: problems.rounds !== undefined })}
              autoComplete="off"
              className="w-24"
            />
          </Field>

          {problem && <Notice tone="error">{problem.text}</Notice>}

          <DialogFooter>
            <Button type="button" variant="outline" disabled={saving} onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving || !changed || Object.keys(problems).length > 0} data-testid="limits-save">
              {saving && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
              {begun ? "Save" : "Use these"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
