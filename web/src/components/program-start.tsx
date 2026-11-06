"use client";

import { Settings2 } from "lucide-react";
import { Notice } from "@/components/messages";
import { Radio } from "@/components/ui/radio";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Field, describedBy } from "@/components/settings-fields";
import { capTitle } from "@/lib/history";
import { INSTRUCTIONS_LIMIT, lengthOf, NO_CODE_FOR_SKILL, PROGRAM_KINDS, type ProgramDraft, type ProgramProblems } from "@/lib/programs";
import { cn } from "@/lib/utils";

export const PROGRAM_NAME_ID = "program-name";
export const PROGRAM_CODE_ID = "program-code";
export const PROGRAM_INSTRUCTIONS_ID = "program-instructions";

// What a program is to be begun as, chosen above the box that it is begun with. A custom program is given a name and
// instructions of its own, and may be given a spending limit, which is chosen as the limits of any program are. One that
// builds a skill needs code, and where there is none says so, with the way to turn it on.
export function ProgramStart({
  draft,
  onChange,
  problems,
  disabled,
  spending,
  onSpending,
  noCode,
  onCode,
}: {
  draft: ProgramDraft;
  onChange: (draft: ProgramDraft) => void;
  problems: ProgramProblems;
  disabled: boolean;
  // The spending limit it will have, in words, which is the settings' where none was chosen
  spending: string;
  onSpending: () => void;
  // Whether code is turned off in the settings, and what opens them at the setting
  noCode: boolean;
  onCode: () => void;
}) {
  const kind = PROGRAM_KINDS.find((known) => known.kind === draft.kind) ?? PROGRAM_KINDS[0];
  const length = lengthOf(draft.instructions.trim());

  return (
    <div className="flex flex-col gap-3" data-testid="program-start">
      <fieldset className="flex flex-col gap-2" disabled={disabled}>
        <legend className="sr-only">Begin as</legend>
        <div className="flex flex-wrap items-center gap-2">
          {PROGRAM_KINDS.map((known) => (
            <label
              key={known.kind}
              className={cn(
                "inline-flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors has-[:disabled]:cursor-not-allowed has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                known.kind === draft.kind
                  ? "border-primary/40 bg-highlight text-highlight-foreground"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              <Radio
                name="program-kind"
                value={known.kind}
                checked={known.kind === draft.kind}
                onChange={() => onChange({ ...draft, kind: known.kind })}
                className="focus-visible:ring-0"
              />
              {known.name}
            </label>
          ))}
        </div>
        <p className="text-sm text-muted-foreground" data-testid="program-kind-about">
          {kind.about}
        </p>
      </fieldset>

      {draft.kind === "build_skill" && noCode && (
        <Notice
          tone={problems.code === undefined ? "muted" : "error"}
          icon={Settings2}
          action={
            <Button id={PROGRAM_CODE_ID} variant="outline" size="xs" onClick={onCode} className="shrink-0 text-foreground">
              Open settings
            </Button>
          }
        >
          {NO_CODE_FOR_SKILL}
        </Notice>
      )}

      {draft.kind === "custom" && (
        <div className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-4 shadow-sm" data-testid="program-custom">
          <Field id={PROGRAM_NAME_ID} label="Name" problem={problems.name}>
            <Input
              id={PROGRAM_NAME_ID}
              value={draft.name}
              onChange={(event) => onChange({ ...draft, name: capTitle(event.target.value) })}
              disabled={disabled}
              placeholder="Weekly literature review"
              autoComplete="off"
              aria-invalid={problems.name !== undefined}
              aria-describedby={describedBy(PROGRAM_NAME_ID, { problem: problems.name !== undefined })}
            />
          </Field>
          <Field
            id={PROGRAM_INSTRUCTIONS_ID}
            label="Instructions"
            hint={`The lead follows these in all that it does in this program. ${length.toLocaleString("en-US")} of ${INSTRUCTIONS_LIMIT.toLocaleString("en-US")} characters.`}
            problem={problems.instructions}
          >
            <Textarea
              id={PROGRAM_INSTRUCTIONS_ID}
              value={draft.instructions}
              onChange={(event) => onChange({ ...draft, instructions: event.target.value })}
              disabled={disabled}
              rows={5}
              placeholder="What this program is for, how the lead should work in it, and what its answers should look like"
              className="max-h-64 overflow-y-auto"
              aria-invalid={problems.instructions !== undefined}
              aria-describedby={describedBy(PROGRAM_INSTRUCTIONS_ID, { hint: true, problem: problems.instructions !== undefined })}
            />
          </Field>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Button type="button" variant="outline" size="sm" onClick={onSpending} disabled={disabled} data-testid="program-spending">
              {spending}
            </Button>
            <span className="text-xs text-muted-foreground">The most this program may spend. It can be changed from the program.</span>
          </div>
        </div>
      )}
    </div>
  );
}
