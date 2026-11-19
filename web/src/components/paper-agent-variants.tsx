"use client";

import { useId, useState } from "react";
import { ChevronDown, ChevronRight, Download, SlidersHorizontal, Trash2 } from "lucide-react";
import { JobOutput } from "@/components/job-output";
import { ProblemNotice } from "@/components/messages";
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
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { api, ApiError } from "@/lib/api";
import { count } from "@/lib/checks";
import { cn } from "@/lib/utils";
import {
  checkVariant,
  claimLabel,
  describeChange,
  describeComparable,
  describeCounts,
  describeMade,
  describeOutcome,
  describeRounds,
  describeRun,
  emptyVariant,
  hasVariants,
  offeredFor,
  signatureOf,
  statusTitle,
  unusable,
  usable,
  valuesFor,
  type VariantDraft,
} from "@/lib/paperagent-variants";
import type { ClaimOutcome, Job, PaperAgent, PaperAgentClaims, Variant, VariantArgument } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";

interface Shared {
  agent: PaperAgent;
  claims: PaperAgentClaims;
  // Whether anything is being done to the agent, which what is done to its variants waits for
  busy: boolean;
}

// Said of every variant, as it is the one thing that must not be taken from one
function NotTheResult() {
  return (
    <Badge variant="outline" data-testid="variant-not-result">
      Not the paper&apos;s result
    </Badge>
  );
}

// One variant: what was changed in which claim's call, what came of it, and whether it can be set beside what the claim was held to
function VariantRow({ variant, striped }: { variant: Variant; striped: boolean }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const rounds = describeRounds(variant);

  return (
    <li
      className={cn("flex flex-col gap-1.5 rounded-lg border border-border p-3", striped && "bg-muted/30")}
      data-testid="variant"
      data-id={variant.id}
      data-claim={variant.claim}
      data-status={variant.variant.status}
      data-control={variant.control.verdict}
      data-comparable={variant.comparable ? "yes" : "no"}
    >
      <div className="flex flex-wrap items-center gap-2">
        <NotTheResult />
        <Badge variant={variant.variant.status === "gave" ? "default" : variant.variant.status === "error" ? "destructive" : "secondary"} data-testid="variant-status">
          {statusTitle(variant.variant.status)}
        </Badge>
        <Badge variant={variant.comparable ? "default" : "outline"} data-testid="variant-comparable">
          {variant.comparable ? "Comparable" : "Not comparable"}
        </Badge>
      </div>
      <p className="break-words text-xs">
        Of the claim that says &ldquo;{variant.quote}&rdquo;, which the paper gives as {variant.number}.
      </p>
      <ul aria-label="What was changed" className="list-disc pl-5 font-mono text-xs" data-testid="variant-changes">
        {variant.changes.map((change) => (
          <li key={change.name} className="break-all">
            {describeChange(change)}
          </li>
        ))}
      </ul>
      <p className="break-words text-xs" data-testid="variant-outcome">
        {describeOutcome(variant)}
      </p>
      <p className="break-words text-xs text-muted-foreground" data-testid="variant-control">
        {describeComparable(variant)}
      </p>
      {rounds !== null && (
        <p className="break-words text-xs text-muted-foreground" data-testid="variant-rounds">
          {rounds}
        </p>
      )}
      {variant.note !== null && (
        <p className="break-words text-xs text-muted-foreground" data-testid="variant-note">
          Your note: {variant.note}
        </p>
      )}
      <p className="text-xs text-muted-foreground" data-testid="variant-made">
        {describeMade(variant)}
      </p>
      <div>
        <Button type="button" variant="link" size="xs" className="h-auto p-0" aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => setOpen((was) => !was)}>
          {open ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
          {open ? "Hide how" : "Show how"}
          <span className="sr-only"> this variant was made</span>
        </Button>
      </div>
      {open && (
        <div id={id} className="flex flex-col gap-1" data-testid="variant-run">
          <p className="break-words text-xs" data-testid="variant-text">
            {variant.text}
          </p>
          <ul aria-label="How this variant was made" className="list-disc pl-5 text-xs text-muted-foreground">
            {describeRun(variant).map((line, index) => (
              <li key={index} className="break-words">
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

// Takes away the variants that were made, which leaves what was said of each claim as it was
function ClearVariants({ agent, busy, kept, onCleared }: { agent: PaperAgent; busy: boolean; kept: number; onCleared: () => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);

  async function clear() {
    setAsking(false);
    const next = await attempt.run(() => api.clearPaperAgentVariants(agent.id));
    if (next) onCleared();
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button variant="outline" size="sm" onClick={() => setAsking(true)} disabled={busy || attempt.busy}>
          <Trash2 />
          Take the variants away
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Take away the variants of the claims of {agent.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This takes away the {kept === 1 ? "variant" : `${kept} variants`} that {kept === 1 ? "was" : "were"} kept. What was said of each claim stays as it was, as no
              variant changes it. Variants can be made again.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void clear()}>
              Take away
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// What was given to one argument of the call, and a place to say what it is to be given instead
function ArgumentField({
  id,
  argument,
  typed,
  problem,
  onChange,
}: {
  id: string;
  argument: VariantArgument;
  typed: string;
  problem: string | undefined;
  onChange: (typed: string) => void;
}) {
  if (!argument.plain) {
    return (
      <div className="flex flex-col gap-1" data-testid="variant-argument" data-name={argument.name} data-plain="no">
        <span className="font-mono text-sm font-medium">{argument.name}</span>
        <p className="break-all font-mono text-xs text-muted-foreground">Given {argument.text}</p>
        <p className="text-xs text-muted-foreground">This is not a value that an argument can be given from here, so it is not changed.</p>
      </div>
    );
  }

  return (
    <div data-testid="variant-argument" data-name={argument.name} data-plain="yes">
      <Field
        id={id}
        label={argument.name}
        hint={
          <>
            Given <code className="break-all font-mono">{argument.text}</code>
          </>
        }
        problem={problem}
      >
        <Input
          id={id}
          value={typed}
          onChange={(event) => onChange(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          className="font-mono"
          placeholder="Not changed"
          aria-invalid={problem !== undefined}
          aria-describedby={describedBy(id, { hint: true, problem: problem !== undefined })}
        />
      </Field>
    </div>
  );
}

// The claims that a variant cannot be made of, each with why, which is opened
function Refusals({
  id,
  refused,
  outcomes,
  open,
  onToggle,
}: {
  id: string;
  refused: ReturnType<typeof unusable>;
  outcomes: Map<string, ClaimOutcome>;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="flex flex-col gap-1" data-testid="variants-refused">
      <div>
        <Button type="button" variant="link" size="xs" className="h-auto p-0" aria-expanded={open} aria-controls={open ? id : undefined} onClick={onToggle}>
          {open ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
          {open ? "Hide why not" : `Why ${count(refused.length, "claim")} cannot be varied`}
        </Button>
      </div>
      {open && (
        <ul id={id} aria-label="Claims that cannot be varied" className="list-disc pl-5 text-xs text-muted-foreground">
          {refused.map((each) => (
            <li key={each.claim} className="break-words" data-claim={each.claim} data-code={each.refused.code}>
              <span className="font-medium text-foreground">{claimLabel(outcomes.get(each.claim), each.claim)}</span>: {each.refused.message}.
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Chooses a claim, gives new values to some of the arguments of the call that it was held to, and starts making the variant
function VariantForm({
  agent,
  claims,
  busy,
  draft,
  onDraft,
  jobs,
  onStale,
}: Shared & { draft: VariantDraft; onDraft: (draft: VariantDraft) => void; jobs: JobsData; onStale: () => void }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [tried, setTried] = useState(false);
  const [why, setWhy] = useState(false);
  const { variants, reproduction } = claims;
  const { limits } = variants;
  const options = usable(variants);
  const refused = unusable(variants);
  // A claim that is chosen is only one that can still be varied, as what is offered changes when the claims are tried again
  const offered = offeredFor(variants, draft.claim);
  const chosen = offered !== undefined ? { ...draft, claim: offered.claim } : { ...draft, claim: "" };
  const checked = checkVariant(chosen, variants);
  const problems = tried ? checked.problems : {};
  const change = (part: Partial<VariantDraft>) => onDraft({ ...draft, ...part });
  const outcomes = new Map<string, ClaimOutcome>(reproduction.claims.map((claim) => [claim.id, claim]));

  async function make() {
    setTried(true);
    const asked = checked.value;
    if (asked === null) return;
    const job = await attempt.run(async () => {
      try {
        return await api.startPaperAgentVariant(agent.id, asked);
      } catch (error) {
        // The tutorials, the claims, or the trying of them are not what the page showed, which it looks at again
        if (
          error instanceof ApiError &&
          (error.code === "stale" || error.code === "no_reproduction" || error.code === "no_reference" || error.code === "not_tried")
        ) {
          onStale();

          return undefined;
        }
        throw error;
      }
    });
    if (job) jobs.track(job);
  }

  const number = (key: "minutes" | "repeats" | "gigabytes", label: string, hint: string) => (
    <Field id={`${id}-${key}`} label={label} hint={hint} problem={problems[key]}>
      <Input
        id={`${id}-${key}`}
        value={draft[key]}
        onChange={(event) => change({ [key]: event.target.value })}
        inputMode="numeric"
        autoComplete="off"
        aria-invalid={problems[key] !== undefined}
        aria-describedby={describedBy(`${id}-${key}`, { hint: true, problem: problems[key] !== undefined })}
      />
    </Field>
  );

  if (options.length === 0) {
    return (
      <div className="flex flex-col gap-2" data-testid="variants-none-to-make">
        <p className="text-sm text-muted-foreground">No claim was held to a call that a variant can be made of.</p>
        {refused.length > 0 && <Refusals id={`${id}-refused`} refused={refused} outcomes={outcomes} open={why} onToggle={() => setWhy((was) => !was)} />}
      </div>
    );
  }

  return (
    <form
      aria-label="Make a variant"
      onSubmit={(event) => {
        event.preventDefault();
        void make();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <p className="text-xs text-muted-foreground">
        Choose a claim, and give new values to some of the arguments of the call that it was held to. The call is made here with nothing changed, and again with
        your changes, each in a container made from the environment&apos;s image that has none of this machine in it and no network. The variant can be set beside
        the claim only if the call with nothing changed gives what the tutorial got.
      </p>
      <Field
        id={`${id}-claim`}
        label="Claim"
        hint={`${count(options.length, "claim")} can be varied.`}
        problem={problems.claim}
      >
        <NativeSelect
          id={`${id}-claim`}
          value={chosen.claim}
          onChange={(event) => onDraft({ ...draft, claim: event.target.value, values: {}, basis: "" })}
          aria-invalid={problems.claim !== undefined}
          aria-describedby={describedBy(`${id}-claim`, { hint: true, problem: problems.claim !== undefined })}
        >
          <option value="">Choose a claim</option>
          {options.map((option) => (
            <option key={option.claim} value={option.claim}>
              {claimLabel(outcomes.get(option.claim), option.claim)}
            </option>
          ))}
        </NativeSelect>
      </Field>
      {refused.length > 0 && <Refusals id={`${id}-refused`} refused={refused} outcomes={outcomes} open={why} onToggle={() => setWhy((was) => !was)} />}
      {offered !== undefined && (
        <fieldset className="flex flex-col gap-3" aria-describedby={problems.changes !== undefined ? `${id}-changes-problem` : undefined}>
          <legend className="mb-1 text-sm font-medium">
            What to change in the call of <code className="break-all font-mono">{offered.function}</code>
          </legend>
          <p className="text-xs text-muted-foreground">
            Write a new value as JSON: text in double quotes, such as &quot;abc&quot;, a number, true, false, null, or a list such as [1, 2, 3]. A number with no point is
            given as a whole number. An argument with nothing written is not changed. At most {limits.most_changes} may be changed at once, each of at most{" "}
            {limits.max_value_chars} characters.
          </p>
          {offered.arguments.map((argument) => (
            <ArgumentField
              key={`${offered.claim}:${argument.name}`}
              id={`${id}-value-${offered.claim}-${argument.name}`}
              argument={argument}
              typed={valuesFor(draft, offered)[argument.name] ?? ""}
              problem={problems[`value:${argument.name}`]}
              onChange={(typed) => change({ values: { ...valuesFor(draft, offered), [argument.name]: typed }, basis: signatureOf(offered) })}
            />
          ))}
          {problems.changes && (
            <p id={`${id}-changes-problem`} role="alert" className="text-xs text-destructive">
              {problems.changes}
            </p>
          )}
        </fieldset>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        {number("minutes", "Most time, in minutes", `For both calls together. At most ${limits.max_minutes}.`)}
        {number("repeats", "How many times each call is made", `It must give the same each time. At most ${limits.max_repeats}.`)}
        {number("gigabytes", "Most a call may write, in gigabytes", `At most ${limits.max_gigabytes}.`)}
      </div>
      <Field
        id={`${id}-note`}
        label="A note (optional)"
        hint={`Why you ask, which is kept with the variant. At most ${limits.max_note_chars} characters.`}
        problem={problems.note}
      >
        <Input
          id={`${id}-note`}
          value={draft.note}
          onChange={(event) => change({ note: event.target.value })}
          autoComplete="off"
          aria-invalid={problems.note !== undefined}
          aria-describedby={describedBy(`${id}-note`, { hint: true, problem: problems.note !== undefined })}
        />
      </Field>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={busy || attempt.busy || !variants.ready}>
          <SlidersHorizontal />
          {attempt.busy ? "Starting…" : busy ? "Waiting…" : "Make the variant"}
        </Button>
      </div>
    </form>
  );
}

// The variants of the claims: a claim's call made again with something changed, beside what the claim was held to. Each is said not to be the
// paper's result, and none changes what was said of its claim
export function VariantsSection({
  agent,
  claims,
  busy,
  making,
  jobs,
  onCleared,
  onStale,
}: Shared & {
  // The making of a variant that is at work, if there is one
  making: Job | undefined;
  jobs: JobsData;
  // Looks at the variants again, as is done when they were taken away
  onCleared: () => void;
  // Looks at the agent and what it is made of again, as is done when the server says what the page shows is out of date
  onStale: () => void;
}) {
  const { variants } = claims;
  const [draft, setDraft] = useState<VariantDraft>(() => emptyVariant(variants));
  const idle = making === undefined && variants.job === null;
  const kept = variants.variants.length + variants.stale;

  return (
    <div className="flex flex-col gap-4">
      {making !== undefined && <JobOutput key={making.id} job={making} jobs={jobs} />}
      {variants.problem !== null && (
        <Aside tone="warning">
          <span data-testid="variants-problem" data-code={variants.problem.code}>
            {variants.problem.message}.
          </span>
        </Aside>
      )}
      {/* What is kept while a variant is made is shown when it is over, and the server says that one goes on before the page has looked at the
          jobs */}
      {idle && hasVariants(variants) && (
        <section className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid="variants-kept">
          <h3 className="text-sm font-medium">The variants that were made</h3>
          <p className="text-xs text-muted-foreground" data-testid="variants-counts">
            {describeCounts(variants.counts, variants.stale)}
          </p>
          {variants.variants.length > 0 && (
            <>
              <ul aria-label="Variants" className="flex flex-col gap-2">
                {variants.variants.map((variant, index) => (
                  <VariantRow key={variant.id} variant={variant} striped={index % 2 === 0} />
                ))}
              </ul>
              <div>
                <a
                  href={`/api/paperagents/${encodeURIComponent(agent.id)}/tables/variants`}
                  download
                  aria-label="Download as a table, the variants"
                  className="inline-flex items-center gap-1 rounded-sm text-xs text-brand underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <Download className="size-3" aria-hidden />
                  Download as a table
                </a>
              </div>
            </>
          )}
          <p className="text-xs text-muted-foreground" data-testid="variants-meaning">
            {variants.meaning}
          </p>
          <ClearVariants agent={agent} busy={busy} kept={kept} onCleared={onCleared} />
        </section>
      )}
      {idle && variants.ready && <VariantForm agent={agent} claims={claims} busy={busy} draft={draft} onDraft={setDraft} jobs={jobs} onStale={onStale} />}
    </div>
  );
}
