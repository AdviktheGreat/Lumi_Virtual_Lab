"use client";

import { useId, useState } from "react";
import { Search } from "lucide-react";
import { Notice, ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { describedBy, Field } from "@/components/settings-fields";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { checkSearches, describeShortlist, MAX_SEARCH_TYPED, MAX_SEARCH_WORDS } from "@/lib/bakeoff-methods";
import { describeLeft } from "@/lib/bakeoffs";
import { timeAgo } from "@/lib/format";
import type { Bakeoff } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";

// What the last finding of methods came to, with what the methods that a search finds are and are not
function Shortlist({ bakeoff }: { bakeoff: Bakeoff }) {
  const shortlist = bakeoff.shortlist;
  const found = bakeoff.candidates.some((method) => method.added_by === "search");
  if (shortlist === null && !found) return null;

  return (
    <div className="flex flex-col gap-2" data-testid="bakeoff-shortlist">
      {shortlist !== null && (
        <div className="flex flex-col gap-1">
          <p className="text-sm font-medium">The last time methods were found, {timeAgo(shortlist.finished_at)}</p>
          {shortlist.queries.length > 0 && (
            <ul aria-label="What was searched for" className="flex flex-col gap-0.5 text-xs text-muted-foreground">
              {shortlist.queries.map((query) => (
                <li key={query}>Searched for: {query}</li>
              ))}
            </ul>
          )}
          {describeShortlist(shortlist).map((line) => (
            <p key={line} className="text-xs text-muted-foreground">
              {line}
            </p>
          ))}
          {shortlist.notes.map((note) => (
            <p key={note} className="text-xs text-muted-foreground">
              {note}
            </p>
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground" data-testid="bakeoff-meaning">
        {bakeoff.meaning}
      </p>
    </div>
  );
}

// Finds methods for the task in the literature: a model writes searches, or they are the person's, and it chooses papers from what they
// found, by their abstracts. What it finds is added to the methods, and none is taken away.
export function FindMethods({ bakeoff }: { bakeoff: Bakeoff }) {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const id = useId();
  const attempt = useAttempt(report);
  const [typed, setTyped] = useState("");
  const [tried, setTried] = useState(false);
  const checked = checkSearches(typed, bakeoff.limits);
  const problems = tried ? checked.problems : {};
  const full = bakeoff.candidates.length >= bakeoff.limits.max_candidates;
  const busy = attempt.busy || bakeoff.job !== null;

  async function start() {
    setTried(true);
    if (checked.problems.searches !== undefined) return;
    const searches = checked.value;
    const job = await attempt.run(() => api.shortlistBakeoff(bakeoff.id, searches === null ? {} : { queries: searches }));
    if (job) jobs.track(job);
  }

  return (
    <div className="flex flex-col gap-4">
      <form
        aria-label="Find methods in the literature"
        onSubmit={(event) => {
          event.preventDefault();
          void start();
        }}
        className="flex flex-col gap-4 rounded-lg border border-border p-3"
      >
        <p className="text-sm text-muted-foreground">
          {bakeoff.settings_model} writes a few short searches for what you want done, they are made of Europe PMC and arXiv, and it chooses papers
          that present a method for it from their abstracts, with the words of each abstract that it went by, which a program checks are there. That
          is its reading of abstracts. It is not a ranking, and not that a method works. Reading abstracts is paid for from what is left of the limit.
          {" "}
          {describeLeft(bakeoff)}
        </p>
        <Field
          id={`${id}-searches`}
          label="Your own searches"
          hint={`Optional, a line for each, at most ${bakeoff.limits.max_queries}. Each is used as its words only, the first ${MAX_SEARCH_WORDS} of them. Left blank, the model writes them.`}
          problem={problems.searches}
        >
          <Textarea
            id={`${id}-searches`}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            rows={3}
            maxLength={MAX_SEARCH_TYPED * 4 * bakeoff.limits.max_queries}
            readOnly={busy}
            aria-invalid={problems.searches !== undefined}
            aria-describedby={describedBy(`${id}-searches`, { hint: true, problem: problems.searches !== undefined })}
          />
        </Field>
        {full && (
          <Notice tone="muted">
            There are {bakeoff.limits.max_candidates} methods in the running, which is as many as there can be. Remove some to find more.
          </Notice>
        )}
        {bakeoff.job !== null && <Notice tone="muted">Something is being done to the methods. Stop it, or wait, to find more.</Notice>}
        {attempt.problem && <ProblemNotice problem={attempt.problem} />}
        <div>
          <Button type="submit" disabled={busy || full}>
            <Search />
            {attempt.busy ? "Starting…" : "Find methods"}
          </Button>
        </div>
      </form>
      <Shortlist bakeoff={bakeoff} />
    </div>
  );
}
