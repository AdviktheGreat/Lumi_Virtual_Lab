"use client";

import { useId, useState } from "react";
import { BookOpen, ExternalLink, Trash2 } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { describedBy, Field } from "@/components/settings-fields";
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
import { api } from "@/lib/api";
import {
  checkReading,
  describeAnchor,
  describeLeftOut,
  describeLength,
  describeReading,
  EMPTY_READING,
  factCount,
  factGroups,
  FACTS_SHOWN,
  hasReading,
  isLink,
  readThrough,
  type FactGroup,
  type FactLine,
} from "@/lib/paperagents";
import type { PaperAgent, PaperAgentPassage, PaperAgentReading } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";
import { cn } from "@/lib/utils";

const LINK = "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

// How many characters of a quote are said in the name of the button that shows where it is
const NAME_CHARS = 60;

interface Shared {
  agent: PaperAgent;
  reading: PaperAgentReading;
  // Whether the paper is being read, which nothing else is done to the agent in the meantime
  working: boolean;
  // Whether the agent's code is being fetched, which the paper is not read in the meantime
  // Why reading waits, in a sentence, or null if it does not
  blocked: string | null;
}

// Says how much reading may cost, which is always said, and starts it
function ReadForm({ agent, reading, working, blocked, jobs }: Shared & { jobs: JobsData }) {
  const { report } = useServer();
  const id = useId();
  const [draft, setDraft] = useState(EMPTY_READING);
  const [tried, setTried] = useState(false);
  const attempt = useAttempt(report);
  const checked = checkReading(draft);
  const problems = tried ? checked.problems : {};
  // A box that is not shown, since nothing failed, is not asked for
  const retry = draft.retryFailed && reading.failed > 0;
  const finished = readThrough(reading, retry);
  const carrying = hasReading(reading) && !reading.complete;

  async function read() {
    setTried(true);
    const options = checked.value;
    if (options === null || finished) return;
    const job = await attempt.run(() => api.readPaperAgent(agent.id, { ...options, retry_failed: retry }));
    if (job) jobs.track(job);
  }

  return (
    <form
      aria-label="Read the paper"
      onSubmit={(event) => {
        event.preventDefault();
        void read();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <p className="text-sm text-muted-foreground">
        The model in the settings reads the paper a part at a time, and lists what the authors report, what they did and with what, what
        they tested it on, and where they say it falls short, each with the words of the paper that say it. A fact whose words are not in
        the paper is thrown away. It costs what that model charges, so say the most it may spend. A reading that stopped carries on from
        where it was.
      </p>
      {reading.fetchable && (
        <p className="text-sm text-muted-foreground">
          The paper has no file yet, so its text is fetched first, which costs nothing:{" "}
          {agent.paper.kind === "doi"
            ? "from Europe PMC, which has the full text of the papers that are open access and no others"
            : "from the link, if it leads to the public internet"}
          . If it cannot be had, this says why, and the paper can be read from its file instead.
        </p>
      )}
      <Field id={`${id}-budget`} label="Most it may spend, in dollars" problem={problems.budget}>
        <Input
          id={`${id}-budget`}
          value={draft.budget}
          onChange={(event) => setDraft((was) => ({ ...was, budget: event.target.value }))}
          inputMode="decimal"
          autoComplete="off"
          className="sm:max-w-xs"
          aria-invalid={problems.budget !== undefined}
          aria-describedby={describedBy(`${id}-budget`, { problem: problems.budget !== undefined })}
        />
      </Field>
      {reading.failed > 0 && (
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={draft.retryFailed} onChange={(event) => setDraft((was) => ({ ...was, retryFailed: event.target.checked }))} />
          Read again the parts that could not be read
        </label>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={working || blocked !== null || attempt.busy || finished}>
          <BookOpen />
          {attempt.busy
            ? "Starting…"
            : working
              ? reading.fetchable
                ? "Fetching…"
                : "Reading…"
              : carrying
                ? "Carry on reading"
                : reading.fetchable
                  ? "Fetch and read the paper"
                  : "Read the paper"}
        </Button>
        {finished && !working && (
          <span className="text-xs text-muted-foreground">The paper has been read. Clear the reading to read it again.</span>
        )}
        {blocked !== null && !working && <span className="text-xs text-muted-foreground">{blocked}</span>}
      </div>
    </form>
  );
}

// The words of the paper at a place, with what is around them, and the words of the fact marked
function Passage({ id, passage }: { id: string; passage: PaperAgentPassage }) {
  return (
    <div id={id} role="group" aria-label="The paper at this place" className="whitespace-pre-wrap break-words rounded-md bg-muted/40 p-2 text-xs leading-relaxed">
      <span className="text-muted-foreground">{passage.before}</span>
      <mark className="rounded-sm bg-primary/20 px-0.5 text-foreground">{passage.text}</mark>
      <span className="text-muted-foreground">{passage.after}</span>
    </div>
  );
}

// A fact, with the paper's own words for it, where they are, and the way to see them in the paper
function Fact({ agent, line }: { agent: string; line: FactLine }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [passage, setPassage] = useState<PaperAgentPassage | null>(null);
  const { fact, title, tag } = line;
  const excerpt = fact.quote.length > NAME_CHARS ? `${fact.quote.slice(0, NAME_CHARS)}…` : fact.quote;

  async function toggle() {
    if (passage !== null) {
      setPassage(null);

      return;
    }
    const found = await attempt.run(() => api.paperAgentPassage(agent, fact.anchor.start, fact.anchor.end));
    if (found) setPassage(found);
  }

  return (
    <li className="flex flex-col gap-1.5 rounded-lg border border-border px-3 py-2" data-testid="paper-fact">
      {(title !== null || tag !== null) && (
        <div className="flex flex-wrap items-center gap-2">
          {title !== null &&
            (isLink(title) ? (
              <a href={title} target="_blank" rel="noreferrer noopener" className={cn("inline-flex min-w-0 items-center gap-1 break-all text-sm font-medium", LINK)}>
                {title}
                <ExternalLink className="size-3 shrink-0" aria-hidden />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            ) : (
              <span className="min-w-0 break-words text-sm font-medium">{title}</span>
            ))}
          {tag !== null && <Badge variant="outline">{tag}</Badge>}
        </div>
      )}
      <blockquote className="break-words border-l-2 border-border pl-2 text-sm text-muted-foreground">{fact.quote}</blockquote>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">{describeAnchor(fact.anchor)}</span>
        <Button
          variant="ghost"
          size="xs"
          onClick={() => void toggle()}
          disabled={attempt.busy}
          aria-expanded={passage !== null}
          aria-controls={passage !== null ? `${id}-passage` : undefined}
          aria-label={`${passage !== null ? "Hide" : "Show in the paper"}: ${excerpt}`}
        >
          {passage !== null ? "Hide" : attempt.busy ? "Looking…" : "Show in the paper"}
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      {passage !== null && <Passage id={`${id}-passage`} passage={passage} />}
    </li>
  );
}

// The facts of one sort, the first of them, and the way to have the rest
function Group({ agent, group }: { agent: string; group: FactGroup }) {
  const id = useId();
  const [all, setAll] = useState(false);
  const shown = all ? group.facts : group.facts.slice(0, FACTS_SHOWN);

  return (
    <section aria-labelledby={id} className="flex flex-col gap-2">
      <h3 id={id} className="text-sm font-medium">
        {group.label} <span className="font-normal text-muted-foreground">({group.facts.length})</span>
      </h3>
      <ul aria-label={group.label} className="flex flex-col gap-2">
        {shown.map((line) => (
          <Fact key={line.fact.id} agent={agent} line={line} />
        ))}
      </ul>
      {shown.length < group.facts.length && (
        <div>
          <Button variant="outline" size="xs" onClick={() => setAll(true)} aria-label={`Show all ${group.facts.length}: ${group.label}`}>
            Show all {group.facts.length}
          </Button>
        </div>
      )}
    </section>
  );
}

// What was read of the paper, with how far it got, and each fact with the paper's words for it
function Facts({ agent, reading }: { agent: string; reading: PaperAgentReading }) {
  const groups = factGroups(reading);
  const notes = [describeLength(reading), describeLeftOut(reading)].filter((note): note is string => note !== null);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <p className="text-sm" data-testid="paper-reading-summary">
          {describeReading(reading)}
        </p>
        {reading.models.length > 0 && <p className="text-xs text-muted-foreground">Read by {reading.models.join(", ")}.</p>}
        {notes.map((note) => (
          <p key={note} className="text-xs text-muted-foreground">
            {note}
          </p>
        ))}
      </div>
      {groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {reading.read > 0 ? "Nothing was found that the paper's own words bear out." : "Nothing has been found yet."}
        </p>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            {factCount(reading)} facts, each with its words from the paper. What the method was done with and tested on is a draft that
            nobody has checked.
          </p>
          {groups.map((group) => (
            <Group key={group.key} agent={agent} group={group} />
          ))}
        </>
      )}
    </div>
  );
}

// Takes away what was read, so that the paper can be read again from the start
function ClearReading({
  agent,
  working,
  onCleared,
}: {
  agent: PaperAgent;
  // Whether anything is being done to the agent
  working: boolean;
  onCleared: (reading: PaperAgentReading) => void;
}) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);

  async function clear() {
    const next = await attempt.run(() => api.clearPaperAgentReading(agent.id));
    if (next) onCleared(next);
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button variant="outline" size="sm" onClick={() => setAsking(true)} disabled={working || attempt.busy}>
          <Trash2 />
          Clear the reading
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Clear the reading of {agent.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This takes away what was read of the paper, and what it cost is not given back. The paper stays, and can be read again
              from the start, which costs again.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void clear()}>
              Clear
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// Reading the paper of an agent, and what was read: the claims, a draft of the method card, and the resources
export function ReadingSection({
  agent,
  reading,
  working,
  blocked,
  jobs,
  onCleared,
}: Shared & { jobs: JobsData; onCleared: (reading: PaperAgentReading) => void }) {
  if (!reading.has_paper && !reading.fetchable) {
    return <p className="text-sm text-muted-foreground">Upload the paper&apos;s file to have it read.</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <ReadForm agent={agent} reading={reading} working={working} blocked={blocked} jobs={jobs} />
      {hasReading(reading) && (
        <>
          <Facts agent={agent.id} reading={reading} />
          <ClearReading agent={agent} working={working || blocked !== null} onCleared={onCleared} />
        </>
      )}
    </div>
  );
}
