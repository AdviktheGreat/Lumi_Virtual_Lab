"use client";

import { useId, useState } from "react";
import { ChevronDown, ChevronRight, ShieldCheck, Trash2 } from "lucide-react";
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
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import {
  asksModel,
  checkChecks,
  describeBasis,
  describeDetails,
  describeNeeds,
  describePassed,
  describeStanding,
  describeTiers,
  describeWhen,
  emptyChecks,
  hasChecks,
  statusTitle,
  whyNot,
  type ChecksDraft,
} from "@/lib/paperagent-checks";
import type { CheckedTool, CheckedToolDetail, CheckEvidence, CheckStatus, Job, PaperAgent, PaperAgentChecks } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";

interface Shared {
  agent: PaperAgent;
  checks: PaperAgentChecks;
  // Whether anything is being done to the agent, which what is done to its checks waits for
  busy: boolean;
}

// How a check stands, in a word and not only a colour
function StatusBadge({ status }: { status: CheckStatus }) {
  const variant = status === "passed" ? "default" : status === "failed" ? "destructive" : "outline";

  return (
    <Badge variant={variant} data-testid="check-status">
      {statusTitle(status)}
    </Badge>
  );
}

// One kind of check of one tool: how it went, what it was against, and, once it is asked for, what it was made of
function Evidence({ entry, detail, checks }: { entry: CheckEvidence; detail: CheckEvidence | undefined; checks: PaperAgentChecks }) {
  const sections = detail?.details ? describeDetails(entry.kind, detail.details) : [];

  return (
    <li className="flex flex-col gap-1 rounded-md border border-border p-2.5" data-testid="check" data-kind={entry.kind} data-status={entry.status}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{entry.title}</span>
        <StatusBadge status={entry.status} />
      </div>
      <p className="break-words text-xs">{entry.summary}</p>
      <p className="break-words text-xs text-muted-foreground">
        Against {describeBasis(entry.basis, checks.bases)}. {describeWhen(entry)}.
        {entry.status === "stale" && entry.was !== null ? ` It ${entry.was === "not_obtained" ? "could not be made" : entry.was} when it was made.` : ""}
      </p>
      {sections.map((section) => (
        <section key={section.title} className="mt-1 flex flex-col gap-0.5" data-testid="check-detail">
          <h4 className="text-xs font-medium">{section.title}</h4>
          {section.words && <p className="text-xs italic text-muted-foreground">{section.words}</p>}
          <ul aria-label={section.title} className="list-disc pl-5 text-xs text-muted-foreground">
            {section.lines.map((line, index) => (
              <li key={index} className="break-words">
                {line}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </li>
  );
}

// One tool: the tier that its checks come to, which opens how each kind of check of it went
function CheckedToolRow({ agent, tool, checks, onStale }: { agent: PaperAgent; tool: CheckedTool; checks: PaperAgentChecks; onStale: () => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const id = useId();
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<CheckedToolDetail | null>(null);
  const needs = describeNeeds(tool, checks);

  async function toggleDetail() {
    if (detail !== null) {
      setDetail(null);

      return;
    }
    const got = await attempt.run(async () => {
      try {
        return await api.paperAgentToolChecks(agent.id, tool.name);
      } catch (error) {
        // What was kept of it is gone, or its tool is, which the page looks at again
        if (error instanceof ApiError && error.status === 404) {
          onStale();

          return undefined;
        }
        throw error;
      }
    });
    if (got !== undefined) setDetail(got);
  }

  return (
    <li className="flex flex-col gap-1.5 rounded-lg border border-border p-3" data-testid="checked-tool" data-name={tool.name} data-tier={tool.tier}>
      <div className="flex flex-wrap items-center gap-2">
        <code className="break-all font-mono text-sm font-medium">{tool.name}</code>
        <Badge asChild variant={tool.tier === "B" ? "default" : "secondary"}>
          <button
            type="button"
            className="cursor-pointer"
            aria-expanded={open}
            aria-controls={open ? id : undefined}
            onClick={() => setOpen((was) => !was)}
          >
            Tier {tool.tier}
            {open ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
            <span className="sr-only">{open ? ", hide how its checks went" : ", show how its checks went"}</span>
          </button>
        </Badge>
        <span className="text-xs text-muted-foreground">{describePassed(tool)}</span>
      </div>
      <p className="break-words text-xs text-muted-foreground">
        It calls {tool.module}.{tool.function}. {describeStanding(tool, checks)}
      </p>
      {needs !== null && (
        <p className="break-words text-xs text-muted-foreground" data-testid="checks-needs">
          {needs}
        </p>
      )}
      {open && (
        <div id={id} className="flex flex-col gap-2">
          <ul aria-label={`Checks of ${tool.name}`} className="flex flex-col gap-2">
            {tool.evidence.map((entry) => (
              <Evidence key={entry.kind} entry={entry} detail={detail?.evidence.find((one) => one.kind === entry.kind)} checks={checks} />
            ))}
          </ul>
          <div>
            <Button type="button" variant="link" size="xs" className="h-auto p-0" onClick={() => void toggleDetail()} disabled={attempt.busy}>
              {detail !== null ? "Hide what each check was made of" : attempt.busy ? "Getting it…" : "Show what each check was made of"}
            </Button>
          </div>
          {attempt.problem && <ProblemNotice problem={attempt.problem} />}
        </div>
      )}
    </li>
  );
}

// Says which kinds of check, the most time and the most to write, how often each call is made, and, for the kinds that ask a model, what
// it may spend and which model chooses inputs, and starts the checking
function CheckForm({
  agent,
  checks,
  busy,
  draft,
  onDraft,
  jobs,
  onStale,
}: Shared & { draft: ChecksDraft; onDraft: (draft: ChecksDraft) => void; jobs: JobsData; onStale: () => void }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [tried, setTried] = useState(false);
  const checked = checkChecks(draft, checks);
  const problems = tried ? checked.problems : {};
  const { limits } = checks;
  const change = (part: Partial<ChecksDraft>) => onDraft({ ...draft, ...part });
  const model = asksModel(draft, checks.kinds);
  const choosing = draft.kinds.includes("verifier");

  async function check() {
    setTried(true);
    const options = checked.value;
    if (options === null) return;
    const job = await attempt.run(async () => {
      try {
        return await api.checkPaperAgentTools(agent.id, options);
      } catch (error) {
        // The tools or the image they were made in are not what the page showed, which it looks at again
        if (error instanceof ApiError && (error.code === "no_tools" || error.code === "no_reference" || error.code === "image_missing")) {
          onStale();

          return undefined;
        }
        throw error;
      }
    });
    if (job) jobs.track(job);
  }

  const number = (key: "minutes" | "totalMinutes" | "repeats" | "gigabytes", label: string, hint: string) => (
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

  return (
    <form
      aria-label="Check the tools"
      onSubmit={(event) => {
        event.preventDefault();
        void check();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <fieldset className="flex flex-col gap-3" aria-describedby={problems.kinds !== undefined ? `${id}-kinds-problem` : undefined}>
        <legend className="mb-1 text-sm font-medium">Which checks to make</legend>
        {checks.kinds.map((kind) => {
          const why = whyNot(kind.kind, checks);
          const on = draft.kinds.includes(kind.kind);

          return (
            <div key={kind.kind} className="flex flex-col gap-0.5" data-testid="check-kind" data-kind={kind.kind}>
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={on && why === null}
                  disabled={why !== null}
                  aria-describedby={`${id}-${kind.kind}-what`}
                  onChange={(event) => change({ kinds: event.target.checked ? [...draft.kinds, kind.kind] : draft.kinds.filter((one) => one !== kind.kind) })}
                />
                <span>{kind.title}</span>
                {kind.model && <Badge variant="outline">Asks a model</Badge>}
              </label>
              <p id={`${id}-${kind.kind}-what`} className="pl-6 text-xs text-muted-foreground">
                Against {describeBasis(kind.basis, checks.bases)}. {kind.what}
                {why !== null ? ` Not available: ${why}` : ""}
              </p>
            </div>
          );
        })}
        {problems.kinds && (
          <p id={`${id}-kinds-problem`} role="alert" className="text-xs text-destructive">
            {problems.kinds}
          </p>
        )}
      </fieldset>
      {model && (
        <Field
          id={`${id}-budget`}
          label="Most it may spend, in dollars"
          hint="What asking a model costs, over every kind that asks one. It is looked at before each request, so that the one that is going may take a little more than is left. When it is reached, the kinds that ask a model are not made for the tools that are left."
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
      {choosing && checks.settings_family !== null && (
        <Field
          id={`${id}-verifier`}
          label="The model that chooses the inputs"
          hint={`It must be of another family than ${checks.settings_model}, which is ${checks.settings_family}'s, the model in the settings, so that it does not miss what that one misses. Its family is told by its name, and a name that does not say whose it is is refused. It chooses what is tried. A program runs it, and judges, and it cannot say that a tool passed.`}
          problem={problems.verifier}
        >
          <Input
            id={`${id}-verifier`}
            value={draft.verifier}
            onChange={(event) => change({ verifier: event.target.value })}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={problems.verifier !== undefined}
            aria-describedby={describedBy(`${id}-verifier`, { hint: true, problem: problems.verifier !== undefined })}
          />
        </Field>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {number("minutes", "Most time for one check of one tool, in minutes", `A check that takes longer is not obtained. At most ${limits.max_minutes}.`)}
        {number("totalMinutes", "Most time for all of the checks, in minutes", `What is left when this is used is not tried. At most ${limits.max_total_minutes}.`)}
        {number("repeats", "How many times each call is made", `It must give the same each time. At most ${limits.max_repeats}.`)}
        {number("gigabytes", "Most one run may write, in gigabytes", `Counting its copy of the project. At most ${limits.max_gigabytes}.`)}
      </div>
      <p className="text-xs text-muted-foreground">
        Each check is made in a container made from the environment&apos;s image that has none of this machine in it: no folder and no key, no
        network, a root that cannot be written to, {limits.memory.toUpperCase()}B of memory, at most {limits.cpus} processors, and at most{" "}
        {limits.pids.toLocaleString("en-US")} processes. Each is kept as it is made, so a checking that is stopped keeps what it had made, and
        the next checking replaces what it checks again.
      </p>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={busy || attempt.busy || !checks.docker.ready}>
          <ShieldCheck />
          {attempt.busy ? "Starting…" : busy ? "Checking…" : "Check the tools"}
        </Button>
      </div>
    </form>
  );
}

// Takes away the checks, so that the tools are of the tier they were made as. The tools stay
function ClearChecks({ agent, busy, onCleared }: { agent: PaperAgent; busy: boolean; onCleared: (checks: PaperAgentChecks) => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);

  async function clear() {
    setAsking(false);
    const next = await attempt.run(() => api.clearPaperAgentChecks(agent.id));
    if (next) onCleared(next);
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button variant="outline" size="sm" onClick={() => setAsking(true)} disabled={busy || attempt.busy}>
          <Trash2 />
          Take the checks away
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Take away the checks of the tools of {agent.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This takes away what was kept of checking the tools. The tools stay, and are of the tier they were made as. The checks can be made again.
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

// The checks of the tools that are made: each tool with the tier its checks come to, which opens how each kind of check of it went,
// and how to make more of them, which is what tier B comes of
export function ChecksSection({
  agent,
  checks,
  busy,
  checking,
  jobs,
  onCleared,
  onStale,
}: Shared & {
  // The checking that is at work, if there is one
  checking: Job | undefined;
  jobs: JobsData;
  onCleared: (checks: PaperAgentChecks) => void;
  // Looks at the agent and what it is made of again, as is done when the server says what the page shows is out of date
  onStale: () => void;
}) {
  const [draft, setDraft] = useState<ChecksDraft>(() => emptyChecks(checks));
  const idle = checking === undefined && checks.job === null;

  if (!checks.made) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="checks-no-tools">
        Make the tools first. Checks are of the tools that were made.
      </p>
    );
  }
  if (checks.tools.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="checks-no-tools">
        No tool held when they were made, so there is nothing to check.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {!checks.docker.ready && (
        <Aside tone="warning">{checks.docker.message ?? "Docker is not running."} Checking tools takes it. They cannot be checked until it is.</Aside>
      )}
      {checking !== undefined && <JobOutput key={checking.id} job={checking} jobs={jobs} />}
      {/* What is kept while the tools are checked is shown when the checking is over, and the server says that one goes on before the
          page has looked at the jobs */}
      {idle && (
        <section className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid="checks-kept">
          <h3 className="text-sm font-medium">The tools and their checks</h3>
          <p className="text-xs text-muted-foreground" data-testid="checks-tiers">
            {describeTiers(checks.tools)}
          </p>
          <ul aria-label="The tools and their checks" className="flex flex-col gap-2">
            {checks.tools.map((tool) => (
              <CheckedToolRow key={tool.name} agent={agent} tool={tool} checks={checks} onStale={onStale} />
            ))}
          </ul>
          <p className="text-xs text-muted-foreground" data-testid="checks-meaning">
            {checks.meaning} A check that is not obtained could not be made, which is neither for the tool nor against it.
          </p>
          {hasChecks(checks.tools) && <ClearChecks agent={agent} busy={busy} onCleared={onCleared} />}
        </section>
      )}
      {idle && <CheckForm agent={agent} checks={checks} busy={busy} draft={draft} onDraft={setDraft} jobs={jobs} onStale={onStale} />}
    </div>
  );
}
