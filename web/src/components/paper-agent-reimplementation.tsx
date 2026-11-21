"use client";

import { useId, useState } from "react";
import { ChevronDown, ChevronRight, Eye, PenLine, ShieldCheck, Trash2 } from "lucide-react";
import { JobOutput } from "@/components/job-output";
import { ProblemNotice } from "@/components/messages";
import { ReimplementationLabel } from "@/components/paper-agent-reimplementation-label";
import { Printed } from "@/components/printed";
import { useServer } from "@/components/server-provider";
import { Aside, describedBy, Field } from "@/components/settings-fields";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import {
  canCheck,
  checkBudget,
  checkChoice,
  checkInputs,
  checkMatching,
  describeChecking,
  describeEntry,
  describeMatchingCounts,
  describeOffer,
  describeParameters,
  describeTask,
  describeWriting,
  draftOf,
  emptyMatching,
  inputsText,
  matchingTitle,
  offerFormKey,
  sameChoice,
  writingTitle,
  type MatchingDraft,
  type OfferDraft,
} from "@/lib/paperagent-reimplementation";
import type { Job, MatchingClaim, MatchingStatus, PaperAgent, PaperAgentReimplementation, ReimplementationOffer } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";

interface Shared {
  agent: PaperAgent;
  reimplementation: PaperAgentReimplementation;
  // Whether anything is being done to the agent, which what is done here waits for
  busy: boolean;
}

// What the server says when what the page shows is no longer so: the paper, what was read of it, or the agent's tools are not what they
// were, or there is no function to check
const STALE = new Set(["imported", "no_text", "no_numbers", "has_tools", "no_function"]);

function isStale(error: unknown): boolean {
  return error instanceof ApiError && STALE.has(error.code);
}

// How a claim came out, in a word and not only a colour
function MatchingBadge({ status }: { status: MatchingStatus | null }) {
  if (status === null) return <Badge variant="outline">Not tried yet</Badge>;
  const variant = status === "matched" ? "default" : status === "error" || status === "hard_coded" ? "destructive" : "outline";

  return (
    <Badge variant={variant} data-testid="matching-status">
      {matchingTitle(status)}
    </Badge>
  );
}

// The inputs that the person gives for a claim, which the function is called with in place of what a model reads
function InputsEditor({
  agent,
  reimplementation,
  claim,
  busy,
  onChanged,
  onStale,
}: Shared & { claim: MatchingClaim; onChanged: (next: PaperAgentReimplementation) => void; onStale: () => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const id = useId();
  const { checks } = reimplementation;
  const parameters = checks.parameters ?? [];
  const [text, setText] = useState(() => inputsText(claim, parameters));
  const [tried, setTried] = useState(false);
  const checked = checkInputs(text, parameters, checks.limits.most_arguments_chars);
  const problem = tried ? checked.problem : undefined;

  async function run(action: () => Promise<PaperAgentReimplementation>) {
    const next = await attempt.run(async () => {
      try {
        return await action();
      } catch (error) {
        if (isStale(error)) {
          onStale();

          return undefined;
        }
        throw error;
      }
    });
    if (next) onChanged(next);
  }

  async function save() {
    setTried(true);
    const args = checked.value;
    if (args === null) return;
    await run(() => api.givePaperAgentInputs(agent.id, claim.id, args));
  }

  return (
    <form
      aria-label={`Your inputs for the claim of ${claim.value}`}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      className="flex flex-col gap-2"
    >
      <Field
        id={`${id}-inputs`}
        label="Your inputs, as JSON"
        hint={`${describeParameters(parameters)} The function is called with these for this claim in place of what a model reads. They are yours to say, and are not held to the paper's words, but none may hold the paper's number, which a function that is given it could give back.`}
        problem={problem}
      >
        <Textarea
          id={`${id}-inputs`}
          value={text}
          onChange={(event) => setText(event.target.value)}
          spellCheck={false}
          className="font-mono text-xs"
          aria-invalid={problem !== undefined}
          aria-describedby={describedBy(`${id}-inputs`, { hint: true, problem: problem !== undefined })}
        />
      </Field>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" disabled={busy || attempt.busy}>
          {attempt.busy ? "Keeping them…" : "Keep these inputs"}
        </Button>
        {claim.inputs !== null && (
          <Button type="button" variant="outline" size="sm" disabled={busy || attempt.busy} onClick={() => void run(() => api.clearPaperAgentInputs(agent.id, claim.id))}>
            Take your inputs away
          </Button>
        )}
      </div>
    </form>
  );
}

// One claim the function is checked against: its number and sentence, what came of it, and, once they are asked for, the passage around
// it and the inputs that the person gives
function ClaimRow(props: Shared & { claim: MatchingClaim; onChanged: (next: PaperAgentReimplementation) => void; onStale: () => void }) {
  const { claim, reimplementation } = props;
  const id = useId();
  const [open, setOpen] = useState(false);
  const { entry } = claim;
  const lines = entry !== null ? describeEntry(entry) : [];

  return (
    <li
      className="flex flex-col gap-1.5 rounded-lg border border-border p-3"
      data-testid="matching-claim"
      data-id={claim.id}
      data-status={entry?.status ?? "untried"}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium tabular-nums">{claim.value}</span>
        <MatchingBadge status={entry?.status ?? null} />
        {claim.inputs !== null && <Badge variant="secondary">Your inputs</Badge>}
      </div>
      <p className="break-words text-xs">&ldquo;{claim.quote}&rdquo;</p>
      {entry !== null && (
        <ul aria-label="What came of it" className="list-disc pl-5 text-xs text-muted-foreground">
          <li className="break-words">{reimplementation.checks.meaning[entry.status] ?? matchingTitle(entry.status)}</li>
          {lines.map((line, index) => (
            <li key={index} className="break-words">
              {line}
            </li>
          ))}
        </ul>
      )}
      {entry === null && claim.inputs !== null && (
        <p className="break-words text-xs text-muted-foreground">You gave: {JSON.stringify(claim.inputs.arguments)}. It is called with these when it is next checked.</p>
      )}
      <div>
        <Button
          type="button"
          variant="link"
          size="xs"
          className="h-auto p-0"
          aria-expanded={open}
          aria-controls={open ? id : undefined}
          onClick={() => setOpen((was) => !was)}
        >
          {open ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
          {open ? "Hide the passage and your inputs" : claim.inputs !== null ? "Show the passage, and change your inputs" : "Show the passage, and give inputs"}
          <span className="sr-only"> of the claim of {claim.value}</span>
        </Button>
      </div>
      {open && (
        <div id={id} className="flex flex-col gap-3">
          {claim.passage !== null && (
            <div className="flex flex-col gap-1">
              <h4 className="text-xs font-medium">The passage around it, which a model is shown</h4>
              <Printed label={`The passage around the claim of ${claim.value}`} text={claim.passage} />
            </div>
          )}
          {reimplementation.checks.parameters !== null && <InputsEditor {...props} />}
        </div>
      )}
    </li>
  );
}

// Says whether a model reads the inputs, what it may spend, and the most time for the calls, and starts the checking
function MatchingForm({ agent, reimplementation, busy, jobs, onStale }: Shared & { jobs: JobsData; onStale: () => void }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const { checks } = reimplementation;
  const [draft, setDraft] = useState<MatchingDraft>(() => emptyMatching(checks));
  const [tried, setTried] = useState(false);
  const checked = checkMatching(draft, checks);
  const problems = tried ? checked.problems : {};
  const change = (part: Partial<MatchingDraft>) => setDraft({ ...draft, ...part });

  async function check() {
    setTried(true);
    const options = checked.value;
    if (options === null) return;
    const job = await attempt.run(async () => {
      try {
        return await api.checkPaperAgentReimplementation(agent.id, options);
      } catch (error) {
        if (isStale(error)) {
          onStale();

          return undefined;
        }
        throw error;
      }
    });
    if (job) jobs.track(job);
  }

  return (
    <form
      aria-label="Check the function against the paper"
      onSubmit={(event) => {
        event.preventDefault();
        void check();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <div className="flex flex-col gap-0.5">
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={draft.ask}
            onChange={(event) => change({ ask: event.target.checked })}
            aria-describedby={`${id}-ask-what`}
          />
          Let a model read the inputs from the paper
        </label>
        <p id={`${id}-ask-what`} className="pl-6 text-xs text-muted-foreground">
          For each claim that you gave no inputs for, {reimplementation.settings_model}, the model in the settings, is shown the function&apos;s signature and the passage
          around the claim, and may give only values that the passage writes. A program checks each one against the passage. Without it, only the claims that you gave
          inputs for are tried.
        </p>
        {problems.ask && (
          <p role="alert" className="pl-6 text-xs text-destructive">
            {problems.ask}
          </p>
        )}
      </div>
      {draft.ask && (
        <Field
          id={`${id}-budget`}
          label="Most it may spend, in dollars"
          hint="What asking the model costs, for all of the claims. It is looked at before each request, so the one that is going may take a little more than is left. When it is reached, the claims that are left have no inputs."
          problem={problems.budget}
        >
          <Input
            id={`${id}-budget`}
            value={draft.budget}
            onChange={(event) => change({ budget: event.target.value })}
            inputMode="decimal"
            autoComplete="off"
            className="sm:max-w-xs"
            aria-invalid={problems.budget !== undefined}
            aria-describedby={describedBy(`${id}-budget`, { hint: true, problem: problems.budget !== undefined })}
          />
        </Field>
      )}
      <Field
        id={`${id}-minutes`}
        label="Most time for all of the calls, in minutes"
        hint={`Each claim is called ${checks.limits.repeats} times with its inputs. The claims that are left when this is used are not run. At most ${checks.limits.most_minutes}.`}
        problem={problems.minutes}
      >
        <Input
          id={`${id}-minutes`}
          value={draft.minutes}
          onChange={(event) => change({ minutes: event.target.value })}
          inputMode="numeric"
          autoComplete="off"
          className="sm:max-w-xs"
          aria-invalid={problems.minutes !== undefined}
          aria-describedby={describedBy(`${id}-minutes`, { hint: true, problem: problems.minutes !== undefined })}
        />
      </Field>
      <p className="text-xs text-muted-foreground">
        The function is called in a container of the lab&apos;s sandbox image that has no network and none of this machine, and a program looks for the claim&apos;s number in
        what it gave, as the paper rounds it. Up to {checks.limits.most_tried} claims are tried. Checking again replaces what was kept of the last checking, and your inputs stay.
      </p>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={busy || attempt.busy}>
          <ShieldCheck />
          {attempt.busy ? "Starting…" : busy ? "Waiting…" : checks.kept !== null ? "Check it again" : "Check it against the paper"}
        </Button>
      </div>
    </form>
  );
}

// Asks before taking something away, and then does
function TakeAway({
  busy,
  button,
  title,
  description,
  onTake,
}: {
  busy: boolean;
  button: string;
  title: string;
  description: string;
  onTake: () => Promise<PaperAgentReimplementation>;
  // What it gives is shown by whoever takes it
}) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);

  async function take() {
    setAsking(false);
    await attempt.run(onTake);
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button variant="outline" size="sm" onClick={() => setAsking(true)} disabled={busy || attempt.busy}>
          <Trash2 />
          {button}
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{title}</AlertDialogTitle>
            <AlertDialogDescription>{description}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void take()}>
              Take away
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// What came of checking the function against the paper's numbers: its label and tier, each claim with what it came to, and how to check it
function Checks(props: Shared & { jobs: JobsData; onChanged: (next: PaperAgentReimplementation) => void; onStale: () => void }) {
  const { agent, reimplementation, busy, onChanged } = props;
  const { checks } = reimplementation;

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid="reimplementation-checks" data-tier={checks.tier ?? "none"}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium">Checked against the paper</h3>
        {checks.tier !== null && <Badge variant="secondary">Tier {checks.tier}</Badge>}
      </div>
      <p className="text-sm" data-testid="matching-label">
        {checks.label}.{" "}
        <span className="text-muted-foreground">
          {checks.tier !== null
            ? "It is given to the conversations that are given this agent, as a re-implementation and not the authors' code."
            : "It is given to no conversation until it gives a number that the paper reports."}
        </span>
      </p>
      {checks.kept !== null && (
        <p className="text-xs text-muted-foreground" data-testid="matching-how">
          {describeChecking(checks.kept)}
        </p>
      )}
      {checks.kept !== null && !checks.current && (
        <Aside tone="warning">
          <span data-testid="matching-stale">
            The last checking was of another function, another file of the paper, or other claims than are kept now, so what came of each claim is not shown. Check it
            again.
          </span>
        </Aside>
      )}
      {checks.counts !== null && (
        <p className="text-xs text-muted-foreground" data-testid="matching-counts">
          {describeMatchingCounts(checks.counts)}
        </p>
      )}
      {checks.claims.length === 0 ? (
        <p className="text-sm text-muted-foreground">No number of the paper has digits enough to be tried.</p>
      ) : (
        <ul aria-label="The claims it is checked against" className="flex flex-col gap-2">
          {checks.claims.map((claim) => (
            <ClaimRow key={claim.id} {...props} claim={claim} />
          ))}
        </ul>
      )}
      {checks.kept !== null && (
        <TakeAway
          busy={busy}
          button="Take the checks away"
          title={`Take away the checks of the function written from ${agent.title}?`}
          description="This takes away what was kept of checking the function against the paper, so that it is of no tier and is given to no conversation. The function and the inputs that you gave stay, and it can be checked again."
          onTake={async () => {
            const next = await api.clearPaperAgentReimplementationChecks(agent.id);
            onChanged(next);

            return next;
          }}
        />
      )}
    </section>
  );
}

// The function that was written, or why none was: how the writing went, what the model was given, and the code, which the person is to
// read before relying on what it gives
function KeptFunction({ agent, reimplementation, busy, onChanged }: Shared & { onChanged: (next: PaperAgentReimplementation) => void }) {
  const kept = reimplementation.kept;
  if (kept === null) return null;
  const written = kept.status === "written";

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid="reimplementation-kept" data-status={kept.status}>
      <div className="flex flex-wrap items-center gap-2">
        <code className="break-all font-mono text-sm font-medium">{kept.name}</code>
        <Badge variant={written ? "secondary" : kept.status === "failed" ? "destructive" : "outline"} data-testid="reimplementation-status">
          {writingTitle(kept.status)}
        </Badge>
        {written && <ReimplementationLabel label={reimplementation.checks.label} />}
      </div>
      <p className="text-xs text-muted-foreground" data-testid="reimplementation-how">
        {describeWriting(kept)} {describeTask(kept.task, reimplementation.sections)}
      </p>
      {!kept.current && (
        <Aside tone="warning">
          <span data-testid="reimplementation-stale">
            It was written from another file of the paper than the agent has now, so it is not checked or given to anything. Write it again.
          </span>
        </Aside>
      )}
      {kept.error !== null && <p className="break-words text-xs text-destructive">{kept.error}</p>}
      {kept.problems.length > 0 && (
        <ul aria-label="What was wrong with what the model wrote" className="list-disc pl-5 text-xs text-muted-foreground">
          {kept.problems.map((problem, index) => (
            <li key={index} className="break-words">
              {problem}
            </li>
          ))}
        </ul>
      )}
      {written &&
        (kept.source !== null ? (
          <div className="flex flex-col gap-1">
            <h4 className="text-xs font-medium">The function&apos;s code, which a model wrote from the paper</h4>
            <p className="text-xs text-muted-foreground">
              None of the authors&apos; code is in it. Read it before you rely on what it gives: it is what is checked and what a conversation calls.
            </p>
            <Printed label="The function's code" text={kept.source} />
          </div>
        ) : (
          <Aside tone="warning">The function&apos;s file was changed or taken away since it was written, so it is not used. Write it again.</Aside>
        ))}
      <TakeAway
        busy={busy}
        button={written ? "Take the function away" : "Take this away"}
        title={`Take away the function written from ${agent.title}?`}
        description="This takes away the function and what was kept of writing it, its checks, and the inputs that you gave for them. A function can be written again."
        onTake={async () => {
          const next = await api.clearPaperAgentReimplementation(agent.id);
          onChanged(next);

          return next;
        }}
      />
    </section>
  );
}

// What the person chooses of the paper for the model to be given, what they read of it, and their agreement, which is what starts the
// writing. The words are chosen by a program from what they say, and never by the model
function OfferForm({
  agent,
  reimplementation,
  busy,
  jobs,
  onStale,
}: Shared & { jobs: JobsData; onStale: () => void }) {
  const { report } = useServer();
  const id = useId();
  const looking = useAttempt(report);
  const attempt = useAttempt(report);
  const { limits } = reimplementation;
  const [draft, setDraft] = useState<OfferDraft>(() => draftOf(reimplementation));
  const [shown, setShown] = useState<ReimplementationOffer | null>(reimplementation.offer);
  const [shownProblem, setShownProblem] = useState<string | null>(reimplementation.choice_problem);
  const [budget, setBudget] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [tried, setTried] = useState(false);
  // What is wrong with the budget is said when the writing is asked for, and not when only what it would be given is looked at
  const [triedToWrite, setTriedToWrite] = useState(false);
  const checked = checkChoice(draft, limits);
  const said = checkBudget(budget);
  const current = shown !== null && checked.value !== null && sameChoice(checked.value, shown);
  const problems = tried ? checked.problems : {};
  const budgetProblem = triedToWrite ? said.problem : undefined;
  const change = (part: Partial<OfferDraft>) => setDraft({ ...draft, ...part });

  // What is shown is what is agreed to, so a new one is read again before it is agreed to
  function show(offer: ReimplementationOffer | null, problem: string | null) {
    setShown(offer);
    setShownProblem(problem);
    setAgreed(false);
  }

  async function look() {
    setTried(true);
    const choice = checked.value;
    if (choice === null) return;
    const next = await looking.run(() => api.paperAgentReimplementation(agent.id, choice));
    if (next === undefined) return;
    if (!next.ready) {
      onStale();

      return;
    }
    show(next.offer, next.choice_problem);
  }

  async function write() {
    setTried(true);
    setTriedToWrite(true);
    const choice = checked.value;
    if (choice === null || shown === null || !current || !agreed || said.value === null) return;
    const job = await attempt.run(async () => {
      try {
        return await api.writePaperAgentReimplementation(agent.id, { ...choice, agreed: shown.key, max_cost: said.value as number });
      } catch (error) {
        // What would be sent is not what was shown, which is shown in its place, to be read again
        if (error instanceof ApiError && error.code === "changed" && typeof error.details.offer === "object" && error.details.offer !== null) {
          show(error.details.offer as ReimplementationOffer, null);
        } else if (isStale(error)) {
          onStale();

          return undefined;
        }
        throw error;
      }
    });
    if (job) jobs.track(job);
  }

  return (
    <form
      aria-label="Write a function from the paper"
      onSubmit={(event) => {
        event.preventDefault();
        void write();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <h3 className="text-sm font-medium">{reimplementation.kept !== null ? "Write it again" : "Write a function from the paper"}</h3>
      <p className="text-xs text-muted-foreground">
        The model is given only the words of the paper that come of what you choose here, which a program takes from the paper. You read all that it would be given before
        you agree, and nothing is sent until you do.
      </p>
      <fieldset className="flex flex-col gap-2" aria-describedby={problems.sections !== undefined ? `${id}-sections-problem` : undefined}>
        <legend className="mb-1 text-sm font-medium">Sections of the paper to give it</legend>
        {reimplementation.sections.length === 0 ? (
          <p className="text-xs text-muted-foreground">No headings were found in the paper. Say words to look for in it instead.</p>
        ) : (
          reimplementation.sections.map((span) => (
            <label key={span.index} className="flex flex-wrap items-center gap-2 text-sm" data-testid="reimplementation-section" data-index={span.index}>
              <Checkbox
                checked={draft.sections.includes(span.index)}
                onChange={(event) =>
                  change({
                    sections: event.target.checked
                      ? [...draft.sections, span.index].sort((one, other) => one - other)
                      : draft.sections.filter((one) => one !== span.index),
                  })
                }
              />
              <span>{span.title}</span>
              <span className="text-xs text-muted-foreground">
                {span.chars.toLocaleString("en-US")} characters{span.page !== null ? `, page ${span.page}` : ""}
              </span>
              {reimplementation.default_sections.includes(span.index) && <Badge variant="outline">Of the method</Badge>}
            </label>
          ))
        )}
        {problems.sections && (
          <p id={`${id}-sections-problem`} role="alert" className="text-xs text-destructive">
            {problems.sections}
          </p>
        )}
      </fieldset>
      <Field
        id={`${id}-search`}
        label="Words to look for in the paper"
        hint={`Its ${limits.most_searched} best places for these words are given as well. Optional. At most ${limits.most_search_chars} characters.`}
        problem={problems.search}
      >
        <Input
          id={`${id}-search`}
          value={draft.search}
          onChange={(event) => change({ search: event.target.value })}
          autoComplete="off"
          aria-invalid={problems.search !== undefined}
          aria-describedby={describedBy(`${id}-search`, { hint: true, problem: problems.search !== undefined })}
        />
      </Field>
      <Field
        id={`${id}-name`}
        label="What the function is called"
        hint="Lowercase letters, digits, and underscores. Its tool in a conversation is named after it."
        problem={problems.name}
      >
        <Input
          id={`${id}-name`}
          value={draft.name}
          onChange={(event) => change({ name: event.target.value })}
          autoComplete="off"
          spellCheck={false}
          className="font-mono"
          aria-invalid={problems.name !== undefined}
          aria-describedby={describedBy(`${id}-name`, { hint: true, problem: problems.name !== undefined })}
        />
      </Field>
      <Field
        id={`${id}-goal`}
        label="What you want of it"
        hint={`In your words, which the model is told are yours and not the paper's. Optional. At most ${limits.most_goal_chars.toLocaleString("en-US")} characters.`}
        problem={problems.goal}
      >
        <Textarea
          id={`${id}-goal`}
          value={draft.goal}
          onChange={(event) => change({ goal: event.target.value })}
          aria-invalid={problems.goal !== undefined}
          aria-describedby={describedBy(`${id}-goal`, { hint: true, problem: problems.goal !== undefined })}
        />
      </Field>
      <div>
        <Button type="button" variant="outline" size="sm" onClick={() => void look()} disabled={looking.busy}>
          <Eye />
          {looking.busy ? "Looking…" : "Show what it would be given"}
        </Button>
      </div>
      {looking.problem && <ProblemNotice problem={looking.problem} />}
      {shownProblem !== null && (
        <p role="alert" className="text-xs text-destructive" data-testid="reimplementation-choice-problem">
          {shownProblem}.
        </p>
      )}
      {shown !== null && (
        <section className="flex flex-col gap-2" data-testid="reimplementation-offer" data-current={current}>
          <h4 className="text-sm font-medium">What {shown.model} would be given</h4>
          <p className="text-xs text-muted-foreground" data-testid="reimplementation-offer-what">
            {describeOffer(shown, limits.most_chars, reimplementation.sections)}
          </p>
          {shown.cut && <Aside tone="warning">The words were cut to the most that is given, so the end of what was chosen is not in it.</Aside>}
          <Printed label="What the model would be given" text={shown.brief} />
          {!current && (
            <Aside tone="warning">
              <span data-testid="reimplementation-offer-changed">What you chose is not what this is of. Show what it would be given again, and read it, before you agree.</span>
            </Aside>
          )}
        </section>
      )}
      <Field
        id={`${id}-budget`}
        label="Most it may spend, in dollars"
        hint="What asking the model costs. It is asked again, with what was wrong, if what it writes cannot be used, up to a few times. It is looked at before each request, so the one that is going may take a little more than is left."
        problem={budgetProblem}
      >
        <Input
          id={`${id}-budget`}
          value={budget}
          onChange={(event) => setBudget(event.target.value)}
          inputMode="decimal"
          autoComplete="off"
          className="sm:max-w-xs"
          aria-invalid={budgetProblem !== undefined}
          aria-describedby={describedBy(`${id}-budget`, { hint: true, problem: budgetProblem !== undefined })}
        />
      </Field>
      <label className="flex items-start gap-2 text-sm">
        <Checkbox checked={agreed && current} disabled={!current} onChange={(event) => setAgreed(event.target.checked)} className="mt-0.5" />
        <span>
          I have read what the model would be given, and agree to send it. What it writes is a re-implementation, not the authors&apos; code, and is shown as one wherever it
          is shown.
        </span>
      </label>
      <p className="text-xs text-muted-foreground">
        The function is imported in a container with no network, and nothing else of it is run until it is checked.
        {reimplementation.kept !== null ? " Writing it again takes away the function that was written, its checks, and the inputs that you gave." : ""}
      </p>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={busy || attempt.busy || !current || !agreed}>
          <PenLine />
          {attempt.busy ? "Starting…" : busy ? "Waiting…" : reimplementation.kept !== null ? "Agree, and write it again" : "Agree, and write the function"}
        </Button>
      </div>
    </form>
  );
}

// A function written from the words of the paper, where it has no code: what to give the model and the agreement to, the function that
// was written, with its code and its label, and what came of checking it against the numbers that the paper reports
export function ReimplementationSection({
  agent,
  reimplementation,
  busy,
  writing,
  checking,
  jobs,
  onChanged,
  onStale,
}: Shared & {
  // The writing and the checking that are at work, if there is one
  writing: Job | undefined;
  checking: Job | undefined;
  jobs: JobsData;
  // Shows what there is now, as what changed it gives it back
  onChanged: (next: PaperAgentReimplementation) => void;
  // Looks at the agent and what it is made of again, as is done when the server says what the page shows is out of date
  onStale: () => void;
}) {
  const { kept, checks } = reimplementation;
  const idle = writing === undefined && checking === undefined && reimplementation.job === null && checks.job === null;
  const shared = { agent, reimplementation, busy };

  return (
    <div className="flex flex-col gap-4" data-testid="reimplementation" data-ready={reimplementation.ready}>
      {reimplementation.problem !== null && (
        <Aside tone={kept !== null ? "warning" : "muted"}>
          <span data-testid="reimplementation-problem">{reimplementation.problem.message}.</span>
          {reimplementation.problem.code === "has_tools" ? " A function written from the paper is only for a paper with no code." : ""}
        </Aside>
      )}
      {writing !== undefined && <JobOutput key={writing.id} job={writing} jobs={jobs} />}
      {checking !== undefined && <JobOutput key={checking.id} job={checking} jobs={jobs} />}
      {/* What is kept while the function is written or checked is shown when that is over, and the server says that one goes on before the
          page has looked at the jobs */}
      {idle && <KeptFunction {...shared} onChanged={onChanged} />}
      {idle && canCheck(reimplementation) && <Checks {...shared} jobs={jobs} onChanged={onChanged} onStale={onStale} />}
      {idle && canCheck(reimplementation) && <MatchingForm {...shared} jobs={jobs} onStale={onStale} />}
      {idle && reimplementation.ready && <OfferForm key={offerFormKey(reimplementation)} {...shared} jobs={jobs} onStale={onStale} />}
      <p className="text-xs text-muted-foreground" data-testid="reimplementation-meaning">
        {reimplementation.meaning}
      </p>
    </div>
  );
}
