"use client";

import { useCallback, useId, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { Looked } from "@/components/looked";
import { Notice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { Aside, describedBy, Field } from "@/components/settings-fields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Radio } from "@/components/ui/radio";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { problemOf, type Problem } from "@/lib/errors";
import { sameTitle } from "@/lib/scientists";
import {
  checkLab,
  choosable,
  initialDraft,
  joining,
  remember,
  remembered,
  withMember,
  withMode,
  type LabDraft,
  type LabMode,
  type LabProblems,
} from "@/lib/team-choice";
import type { LabChoice, LibraryScientist } from "@/lib/types";
import { useLooked } from "@/lib/use-looked";

const MODES: { value: LabMode; label: string; hint: string }[] = [
  { value: "team", label: "A team discussion", hint: "Several scientists discuss it, with the lead leading, and the lead gives you the summary." },
  { value: "individual", label: "One scientist", hint: "One scientist works on it, and the Scientific Critic reviews what they do." },
];

// Who works on a message, and how, which is chosen from the whole library of scientists, and what they are to work on. Starting
// it gives onStart the agenda and the choice, which may refuse by throwing, and whose refusal is shown here. The lead writes
// the agenda that the team is given, from what is asked here. Closing it gives onClose what was written, to put back where
// it came from, or null when it was started.
export function LabDialog({
  agenda,
  lead,
  team,
  ceiling,
  onStart,
  onClose,
}: {
  // What is to be worked on, as far as it has been written
  agenda: string;
  lead: string;
  // Who is on the conversation's team, or null where it has not begun, so that it is not known
  team: readonly string[] | null;
  // The most rounds the lead may ask a session for
  ceiling: number;
  onStart: (agenda: string, choice: LabChoice) => Promise<void>;
  onClose: (agenda: string | null) => void;
}) {
  const { report } = useServer();
  const look = useCallback(() => api.scientists(), []);
  const library = useLooked(look, report, "");
  // What was written, kept as it is written so that closing the dialog can say what it was
  const writtenRef = useRef(agenda);
  const [sending, setSending] = useState(false);

  return (
    <Dialog open onOpenChange={(open) => !open && !sending && onClose(writtenRef.current)}>
      <DialogContent className="sm:max-w-xl" data-testid="lab-dialog">
        <DialogHeader>
          <DialogTitle>Work on it with the lab</DialogTitle>
          <DialogDescription>
            Choose who works on this. The lead writes what they are told, from what you ask here, and answers you from what they find.
          </DialogDescription>
        </DialogHeader>
        <Looked state={library.value} label="Looking at the scientists" failure="The scientists could not be looked at." onRetry={library.reload}>
          {(scientists) => (
            <LabForm
              scientists={scientists}
              agenda={agenda}
              lead={lead}
              team={team}
              ceiling={ceiling}
              writtenRef={writtenRef}
              sending={sending}
              setSending={setSending}
              onStart={onStart}
              onClose={onClose}
            />
          )}
        </Looked>
      </DialogContent>
    </Dialog>
  );
}

function LabForm({
  scientists,
  agenda,
  lead,
  team,
  ceiling,
  writtenRef,
  sending,
  setSending,
  onStart,
  onClose,
}: {
  scientists: LibraryScientist[];
  agenda: string;
  lead: string;
  team: readonly string[] | null;
  ceiling: number;
  writtenRef: React.RefObject<string>;
  sending: boolean;
  setSending: (sending: boolean) => void;
  onStart: (agenda: string, choice: LabChoice) => Promise<void>;
  onClose: (agenda: string | null) => void;
}) {
  const id = useId();
  const [draft, setDraft] = useState<LabDraft>(() => initialDraft(agenda, remembered(), scientists, lead, ceiling));
  const [problem, setProblem] = useState<Problem | null>(null);
  // What has been changed, since what is wrong with what has not been is not said until it is, as nothing is wrong with a form
  // that has not been filled in yet
  const [touched, setTouched] = useState<ReadonlySet<keyof LabProblems>>(new Set());
  const { choice, problems } = checkLab(draft, ceiling);
  const shown: LabProblems = Object.fromEntries(Object.entries(problems).filter(([field]) => touched.has(field as keyof LabProblems)));
  const available = choosable(scientists, lead, draft.mode);
  const joins = team === null ? [] : joining(draft.members, team);
  const agendaId = `${id}-agenda`;
  const roundsId = `${id}-rounds`;
  const questionsId = `${id}-questions`;
  const membersId = `${id}-members`;

  function edit(next: LabDraft, field?: keyof LabProblems) {
    writtenRef.current = next.agenda;
    setDraft(next);
    setProblem(null);
    if (field) setTouched((was) => new Set(was).add(field));
  }

  async function start() {
    if (sending || choice === null) return;
    setSending(true);
    setProblem(null);
    try {
      await onStart(draft.agenda.trim(), choice);
      remember(choice);
      onClose(null);
    } catch (error) {
      setProblem(problemOf(error));
      setSending(false);
    }
  }

  return (
    <form
      className="flex min-h-0 flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        void start();
      }}
    >
      <div className="-mx-1 flex min-h-0 flex-col gap-5 overflow-y-auto px-1 py-0.5">
        <Field id={agendaId} label="What should they work on?" problem={shown.agenda}>
          <Textarea
            id={agendaId}
            value={draft.agenda}
            onChange={(event) => edit({ ...draft, agenda: event.target.value }, "agenda")}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                void start();
              }
            }}
            rows={3}
            aria-invalid={shown.agenda !== undefined}
            aria-describedby={describedBy(agendaId, { problem: shown.agenda !== undefined })}
            autoFocus
            className="max-h-40"
          />
        </Field>

        <fieldset className="flex flex-col gap-2">
          <legend className="pb-1.5 text-sm font-medium">How</legend>
          {MODES.map((mode) => (
            <label key={mode.value} className="flex cursor-pointer items-start gap-2.5 text-sm">
              <Radio
                name={`${id}-mode`}
                value={mode.value}
                checked={draft.mode === mode.value}
                onChange={() => edit(withMode(draft, mode.value))}
                className="mt-0.5"
              />
              <span className="flex flex-col">
                <span className="font-medium">{mode.label}</span>
                <span className="text-xs text-muted-foreground">{mode.hint}</span>
              </span>
            </label>
          ))}
        </fieldset>

        <fieldset className="flex flex-col gap-1.5" aria-describedby={describedBy(membersId, { problem: problems.members !== undefined })}>
          <legend className="pb-1.5 text-sm font-medium">{draft.mode === "team" ? "Who takes part" : "Who works on it"}</legend>
          <ul className="flex max-h-56 flex-col divide-y divide-border overflow-y-auto rounded-lg border border-border" data-testid="lab-members">
            {available.map((scientist) => {
              const chosen = draft.members.some((member) => sameTitle(member, scientist.title));
              const Control = draft.mode === "team" ? Checkbox : Radio;

              return (
                <li key={scientist.title}>
                  <label className="flex cursor-pointer items-start gap-2.5 px-3 py-2 text-sm hover:bg-muted/50">
                    <Control
                      name={`${id}-member`}
                      checked={chosen}
                      onChange={(event) => edit(withMember(draft, scientist.title, event.target.checked), "members")}
                      aria-label={scientist.title}
                      className="mt-0.5"
                    />
                    <span className="flex min-w-0 flex-col">
                      <span className="flex flex-wrap items-center gap-1.5 font-medium">
                        {scientist.title}
                        {!scientist.builtin && <Badge variant="outline">yours</Badge>}
                      </span>
                      <span className="truncate text-xs text-muted-foreground">{scientist.expertise}</span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
          {problems.members && (
            <p
              id={`${membersId}-problem`}
              role={shown.members ? "alert" : undefined}
              className={shown.members ? "text-xs text-destructive" : "text-xs text-muted-foreground"}
            >
              {problems.members}
            </p>
          )}
        </fieldset>
        {joins.length > 0 && (
          <Aside>
            {joins.join(", ")} {joins.length === 1 ? "is" : "are"} not on this conversation&apos;s team, and {joins.length === 1 ? "joins" : "join"} it.
          </Aside>
        )}

        <Field
          id={roundsId}
          label={draft.mode === "team" ? "Rounds of discussion" : "Rounds of review"}
          problem={shown.rounds}
          hint={`0 is one answer, with no ${draft.mode === "team" ? "discussion" : "review"}. The most the lead may ask for is ${ceiling}, which /budget changes.`}
        >
          <Input
            id={roundsId}
            value={draft.rounds}
            onChange={(event) => edit({ ...draft, rounds: event.target.value }, "rounds")}
            inputMode="numeric"
            aria-invalid={shown.rounds !== undefined}
            aria-describedby={describedBy(roundsId, { hint: true, problem: shown.rounds !== undefined })}
            autoComplete="off"
            className="w-24"
          />
        </Field>

        <Field
          id={questionsId}
          label="Questions they must answer (optional)"
          problem={shown.questions}
          hint="One to a line. They are given to the team as they are."
        >
          <Textarea
            id={questionsId}
            value={draft.questions}
            onChange={(event) => edit({ ...draft, questions: event.target.value }, "questions")}
            rows={2}
            aria-invalid={shown.questions !== undefined}
            aria-describedby={describedBy(questionsId, { hint: true, problem: shown.questions !== undefined })}
            className="max-h-32"
          />
        </Field>
      </div>

      {problem && <Notice tone="error">{problem.text}</Notice>}

      <DialogFooter>
        <Button type="button" variant="outline" disabled={sending} onClick={() => onClose(writtenRef.current)}>
          Cancel
        </Button>
        <Button type="submit" disabled={sending || choice === null} data-testid="lab-start">
          {sending && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
          Start
        </Button>
      </DialogFooter>
    </form>
  );
}
