"use client";

import { useId, useState } from "react";
import { ChevronDown, ChevronRight, Download, ListChecks, Trash2 } from "lucide-react";
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
import {
  checkClaims,
  claimStatusTitle,
  describeCounts,
  describeKept,
  describeLink,
  describeSoftware,
  describeStale,
  differenceKind,
  divergenceOf,
  emptyClaims,
  filterClaims,
  filtersOf,
  statusTitle,
  type ClaimFilter,
} from "@/lib/paperagent-claims";
import type { ClaimOutcome, DivergenceClaim, DivergenceDifference, Job, PaperAgent, PaperAgentClaims } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";

interface Shared {
  agent: PaperAgent;
  claims: PaperAgentClaims;
  // Whether anything is being done to the agent, which what is done to its claims waits for
  busy: boolean;
}

// How a claim came out, in a word and not only a colour
function StatusBadge({ claim }: { claim: Pick<ClaimOutcome, "status" | "was"> }) {
  const variant = claim.status === "reproduced" ? "default" : claim.status === "not_reproduced" ? "destructive" : claim.status === "partly" ? "secondary" : "outline";

  return (
    <Badge variant={variant} data-testid="claim-status">
      {claimStatusTitle(claim)}
    </Badge>
  );
}

// A difference that was found, with the paper's words that it is held to, if there are any. It is not said to be why a number differs.
function Difference({ difference }: { difference: DivergenceDifference }) {
  return (
    <li className="break-words" data-kind={difference.kind}>
      <span className="font-medium">{differenceKind(difference.kind)}:</span> {difference.text}
      {difference.quote !== null && <span className="italic text-muted-foreground"> The paper says: &ldquo;{difference.quote}&rdquo;</span>}
    </li>
  );
}

// Where the tutorial of a claim that did not reproduce first parts from the paper, and what differs that was found for it
function Divergence({ found }: { found: DivergenceClaim }) {
  return (
    <section className="flex flex-col gap-1" data-testid="claim-divergence">
      <h4 className="font-medium">Where it first parts from the paper</h4>
      <p className="break-words" data-testid="claim-point">
        {found.point !== null ? found.point.text : "No output is named as parting from the paper, as the number that it gave rounds to the paper's."}
      </p>
      <h4 className="mt-1 font-medium">Differences found (not shown to be why)</h4>
      {found.differences.length > 0 ? (
        <ul aria-label="Differences found" className="list-disc pl-5">
          {found.differences.map((difference, index) => (
            <Difference key={index} difference={difference} />
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground">None was found for this tutorial. That does not say that there is none, as what the paper does not say, and the code&apos;s own defaults, are not seen.</p>
      )}
    </section>
  );
}

// One claim: its sentence, the number that the paper reports, how it came out, and, once it is asked for, what it was held to and where
// the tutorial first parts from the paper
function ClaimRow({ claim, found }: { claim: ClaimOutcome; found: DivergenceClaim | undefined }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const stale = claim.status === "stale";
  const link = stale ? null : claim.link;
  const more = link !== null || found !== undefined;

  return (
    <>
      <tr className="align-top odd:bg-muted/30" data-testid="claim" data-id={claim.id} data-status={claim.status}>
        <td className="break-words px-2.5 py-1.5">{claim.quote}</td>
        <td className="px-2.5 py-1.5 tabular-nums">{claim.value || <span className="text-muted-foreground">None</span>}</td>
        <td className="px-2.5 py-1.5">
          <StatusBadge claim={claim} />
        </td>
        <td className="break-words px-2.5 py-1.5" data-testid="claim-summary">
          {stale ? describeStale(claim) : claim.summary}
        </td>
        <td className="px-2.5 py-1.5 text-right">
          {more && (
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
              {open ? "Hide how" : "Show how"}
              <span className="sr-only"> of the claim that says &ldquo;{claim.quote.slice(0, 60)}&rdquo;</span>
            </Button>
          )}
        </td>
      </tr>
      {open && more && (
        <tr className="odd:bg-muted/30" data-testid="claim-detail" data-id={claim.id}>
          <td colSpan={5} className="px-2.5 pb-2.5">
            <div id={id} className="flex flex-col gap-2 text-xs">
              {link !== null && (
                <section className="flex flex-col gap-1">
                  <h4 className="font-medium">What it was held to</h4>
                  <ul aria-label="What it was held to" className="list-disc pl-5 text-muted-foreground">
                    {describeLink(link).map((line, index) => (
                      <li key={index} className="break-words">
                        {line}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              {found !== undefined && <Divergence found={found} />}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// What differs between what the paper says and what was used here, of the whole run and not of one claim
function WholeRun({ claims }: { claims: PaperAgentClaims }) {
  const { divergence } = claims;
  if (!claims.reproduction.current || !divergence.current || (divergence.software.length === 0 && divergence.differences.length === 0)) return null;

  return (
    <section className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="claims-whole-run">
      <h3 className="text-sm font-medium">What differs, of the whole run</h3>
      {divergence.software.length > 0 && (
        <ul aria-label="Software that the paper names" className="list-disc pl-5 text-xs text-muted-foreground">
          {divergence.software.map((software) => (
            <li key={software.name} className="break-words">
              {describeSoftware(software)}
            </li>
          ))}
        </ul>
      )}
      {divergence.differences.length > 0 && (
        <>
          <h4 className="text-xs font-medium">Differences found (not shown to be why)</h4>
          <ul aria-label="Differences of the whole run" className="list-disc pl-5 text-xs">
            {divergence.differences.map((difference, index) => (
              <Difference key={index} difference={difference} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

// The claims of the paper, each with how it came out, to be told apart by that and saved as a table
function ClaimsTable({ agent, claims }: { agent: PaperAgent; claims: PaperAgentClaims }) {
  const id = useId();
  const { reproduction } = claims;
  const [filter, setFilter] = useState<ClaimFilter>("all");
  const filters = filtersOf(reproduction.counts);
  const shown = filterClaims(reproduction.claims, filters.includes(filter) ? filter : "all");

  return (
    <div className="flex flex-col gap-2" data-testid="claims-table">
      <div className="flex flex-wrap items-end gap-3">
        {filters.length > 2 && (
          <div className="flex flex-col gap-1">
            <label htmlFor={`${id}-filter`} className="text-xs font-medium">
              Show
            </label>
            <NativeSelect id={`${id}-filter`} value={filters.includes(filter) ? filter : "all"} onChange={(event) => setFilter(event.target.value as ClaimFilter)}>
              {filters.map((one) => (
                <option key={one} value={one}>
                  {one === "all" ? "All claims" : `${statusTitle(one)} (${reproduction.counts[one]})`}
                </option>
              ))}
            </NativeSelect>
          </div>
        )}
        <a
          href={`/api/paperagents/${encodeURIComponent(agent.id)}/tables/claims`}
          download
          aria-label="Download as a table, the claims"
          className="ml-auto inline-flex items-center gap-1 rounded-sm text-xs text-brand underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <Download className="size-3" aria-hidden />
          Download as a table
        </a>
      </div>
      <div className="max-h-[32rem] overflow-auto rounded-lg border border-border">
        <table aria-label="Claims" className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-muted">
            <tr>
              <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                What the paper says
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                Number
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                Status
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                What came of it
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                <span className="sr-only">How</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((claim) => (
              <ClaimRow key={claim.id} claim={claim} found={divergenceOf(claims, claim.id)} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Says the most that asking a model may spend, and starts trying the claims
function TryForm({
  agent,
  claims,
  busy,
  jobs,
  onStale,
}: Shared & { jobs: JobsData; onStale: () => void }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [draft, setDraft] = useState(emptyClaims);
  const [tried, setTried] = useState(false);
  const { reproduction } = claims;
  const checked = checkClaims(draft);
  const problem = tried ? checked.problems.budget : undefined;

  async function start() {
    setTried(true);
    const options = checked.value;
    if (options === null) return;
    const job = await attempt.run(async () => {
      try {
        return await api.startPaperAgentReproduction(agent.id, options);
      } catch (error) {
        // The paper, the tutorials, or what was read is not what the page showed, which it looks at again
        if (error instanceof ApiError && (error.code === "no_claims" || error.code === "no_numbers" || error.code === "no_reference")) {
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
      aria-label="Try the claims"
      onSubmit={(event) => {
        event.preventDefault();
        void start();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <Field
        id={`${id}-budget`}
        label="Most it may spend, in dollars"
        hint={`For each claim that states a number, ${reproduction.settings_model}, the model in the settings, is asked which place in what the tutorials gave the sentence is about, and is not shown any value there. A program holds what was kept at that place to the number. The spending is looked at before each request, so that the one that is going may take a little more than is left. When it is reached, the claims that are left are not attempted.`}
        problem={problem}
      >
        <Input
          id={`${id}-budget`}
          value={draft.budget}
          onChange={(event) => setDraft({ budget: event.target.value })}
          inputMode="decimal"
          autoComplete="off"
          className="sm:max-w-xs"
          aria-invalid={problem !== undefined}
          aria-describedby={describedBy(`${id}-budget`, { hint: true, problem: problem !== undefined })}
        />
      </Field>
      <p className="text-xs text-muted-foreground">
        {reproduction.numbers} number{reproduction.numbers === 1 ? "" : "s"} of the paper {reproduction.numbers === 1 ? "has" : "have"} digits enough to be tried. Nothing is run:
        it is what the tutorials kept that the claims are held to.
        {reproduction.kept !== null ? " Trying them again takes away what was kept of this trying, and the variants that were made of it." : ""}
      </p>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={busy || attempt.busy || !reproduction.ready}>
          <ListChecks />
          {attempt.busy ? "Starting…" : busy ? "Waiting…" : reproduction.kept !== null ? "Try the claims again" : "Try the claims"}
        </Button>
      </div>
    </form>
  );
}

// Takes away what was kept of the trying, so that the claims are tried again from nothing. What the tutorials gave stays
function ClearClaims({ agent, busy, onCleared }: { agent: PaperAgent; busy: boolean; onCleared: () => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);

  async function clear() {
    setAsking(false);
    const next = await attempt.run(() => api.clearPaperAgentReproduction(agent.id));
    if (next) onCleared();
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button variant="outline" size="sm" onClick={() => setAsking(true)} disabled={busy || attempt.busy}>
          <Trash2 />
          Take the trying away
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Take away the trying of the claims of {agent.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This takes away what was kept of trying the claims, and the variants that were made of them, as those were read at places that the trying held the claims to. What
              the tutorials gave and what was read of the paper stay. The claims can be tried again.
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

// The claims of the paper, held to what the tutorials gave when they were run here: how each came out, what it was held to, and where
// the tutorial first parts from the paper for those that did not reproduce, and how to try them
export function ClaimsSection({
  agent,
  claims,
  busy,
  trying,
  jobs,
  onCleared,
  onStale,
}: Shared & {
  // The trying that is at work, if there is one
  trying: Job | undefined;
  jobs: JobsData;
  // Looks at the claims again, as is done when they were taken away
  onCleared: () => void;
  // Looks at the agent and what it is made of again, as is done when the server says what the page shows is out of date
  onStale: () => void;
}) {
  const { reproduction, divergence } = claims;
  const idle = trying === undefined && reproduction.job === null;
  const kept = reproduction.kept !== null;

  return (
    <div className="flex flex-col gap-4">
      {trying !== undefined && <JobOutput key={trying.id} job={trying} jobs={jobs} />}
      {reproduction.problem !== null && (
        <Aside tone="warning">
          <span data-testid="claims-problem">{reproduction.problem.message}.</span>
        </Aside>
      )}
      {/* What is kept while the claims are tried is shown when the trying is over, and the server says that one goes on before the page has
          looked at the jobs */}
      {idle && kept && (
        <section className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid="claims-kept">
          <h3 className="text-sm font-medium">The claims of the paper</h3>
          <p className="text-xs text-muted-foreground" data-testid="claims-counts">
            {describeCounts(reproduction.counts, reproduction.more)}
          </p>
          {reproduction.kept !== null && (
            <p className="text-xs text-muted-foreground" data-testid="claims-how">
              {describeKept(reproduction.kept)}
              {reproduction.kept.limit !== null ? ` ${reproduction.kept.limit}.` : ""}
            </p>
          )}
          {reproduction.kept !== null && reproduction.kept.notes.length > 0 && (
            <ul aria-label="Notes on the trying" className="list-disc pl-5 text-xs text-muted-foreground">
              {reproduction.kept.notes.map((note, index) => (
                <li key={index} className="break-words">
                  {note}
                </li>
              ))}
            </ul>
          )}
          {!reproduction.current && (
            <Aside tone="warning">
              <span data-testid="claims-stale">
                These were tried against another run of the tutorials, or other claims, than are kept now, so what came of each is not shown. Try the claims again.
              </span>
            </Aside>
          )}
          <ClaimsTable agent={agent} claims={claims} />
          {divergence.ready && divergence.current && <WholeRun claims={claims} />}
          <p className="text-xs text-muted-foreground" data-testid="claims-meaning">
            {reproduction.meaning}
            {divergence.ready && divergence.claims.length > 0 ? ` ${divergence.meaning}` : ""}
          </p>
          <ClearClaims agent={agent} busy={busy} onCleared={onCleared} />
        </section>
      )}
      {idle && <TryForm agent={agent} claims={claims} busy={busy} jobs={jobs} onStale={onStale} />}
    </div>
  );
}
