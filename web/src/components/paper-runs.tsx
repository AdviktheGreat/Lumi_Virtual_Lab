"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { describedBy, Field } from "@/components/settings-fields";
import { useServer } from "@/components/server-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Radio } from "@/components/ui/radio";
import { api } from "@/lib/api";
import { formatBytes } from "@/lib/files";
import {
  checkRun,
  describeSource,
  EMPTY_RUN,
  MAX_BIORXIV_LIMIT,
  MAX_RUN_TITLE,
  runFacts,
  SOURCE_KINDS,
  SOURCE_LABELS,
  type RunDraft,
} from "@/lib/papers";
import type { PaperRunEntry, PapersList } from "@/lib/types";
import { useAttempt } from "@/lib/use-papers";

// The page of a run, which is named in the address's query, as a conversation is
export const runAddress = (id: string) => `/papers?id=${encodeURIComponent(id)}`;

function RunRow({ run }: { run: PaperRunEntry }) {
  return (
    <li className="flex flex-col gap-1 rounded-lg border border-border p-3" data-testid="paper-run">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="min-w-0 break-words text-sm font-medium">
          <Link href={runAddress(run.id)} className="rounded-sm outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
            {run.title}
          </Link>
        </h3>
        {run.job_kind !== null && <Badge variant="secondary">{run.job_kind === "papers" ? "Reading" : "Writing functions"}</Badge>}
        {run.given && <Badge variant="outline">Functions given to conversations</Badge>}
      </div>
      <p className="text-xs text-muted-foreground">{describeSource(run.source)}</p>
      <p className="text-xs text-muted-foreground">{runFacts(run)}</p>
    </li>
  );
}

// The runs there are, the latest first
export function RunList({ runs }: { runs: readonly PaperRunEntry[] }) {
  if (runs.length === 0) return <p className="text-sm text-muted-foreground">No papers have been read yet. Make a run below.</p>;

  return (
    <ul aria-label="Runs" className="flex flex-col gap-2">
      {runs.map((run) => (
        <RunRow key={run.id} run={run} />
      ))}
    </ul>
  );
}

// Makes a run, which has read nothing yet: it says where the papers come from, and they are read from its own page
export function NewRun({ list }: { list: PapersList }) {
  const { report } = useServer();
  const router = useRouter();
  const id = useId();
  const [draft, setDraft] = useState<RunDraft>(EMPTY_RUN);
  const [tried, setTried] = useState(false);
  const attempt = useAttempt(report);
  const checked = checkRun(draft);
  const problems = tried ? checked.problems : {};
  const field = (name: string) => `${id}-${name}`;

  function change(part: Partial<RunDraft>) {
    setDraft((was) => ({ ...was, ...part }));
  }

  async function make() {
    setTried(true);
    const body = checked.value;
    if (body === null) return;
    const run = await attempt.run(() => api.makePaperRun(body));
    if (run) router.push(runAddress(run.id));
  }

  return (
    <form
      aria-label="Make a run"
      onSubmit={(event) => {
        event.preventDefault();
        void make();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <Field id={field("title")} label="Title" hint="What the run is called, so that you can find it again." problem={problems.title}>
        <Input
          id={field("title")}
          value={draft.title}
          onChange={(event) => change({ title: event.target.value })}
          maxLength={MAX_RUN_TITLE * 4}
          autoComplete="off"
          readOnly={attempt.busy}
          aria-invalid={problems.title !== undefined}
          aria-describedby={describedBy(field("title"), { hint: true, problem: problems.title !== undefined })}
        />
      </Field>

      <fieldset className="flex flex-wrap gap-x-5 gap-y-2" disabled={attempt.busy}>
        <legend className="mb-1.5 text-sm font-medium">Where the papers come from</legend>
        {SOURCE_KINDS.map((kind) => (
          <label key={kind} className="flex items-center gap-2 text-sm">
            <Radio name={field("kind")} checked={draft.kind === kind} onChange={() => change({ kind })} />
            {SOURCE_LABELS[kind]}
          </label>
        ))}
      </fieldset>

      {draft.kind === "files" && (
        <p className="text-xs text-muted-foreground">
          You upload them to the run once it is made. {list.suffixes.join(", ")} files are read, of up to {formatBytes(list.max_paper_bytes)} each.
        </p>
      )}

      {draft.kind === "folder" && (
        <>
          <Field
            id={field("path")}
            label="Full path of the folder"
            hint="Where it is on the machine the lab runs on. The papers are read where they are, and not copied or changed."
            problem={problems.path}
          >
            <Input
              id={field("path")}
              value={draft.path}
              onChange={(event) => change({ path: event.target.value })}
              placeholder="/Users/you/papers"
              autoComplete="off"
              spellCheck={false}
              readOnly={attempt.busy}
              aria-invalid={problems.path !== undefined}
              aria-describedby={describedBy(field("path"), { hint: true, problem: problems.path !== undefined })}
            />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.recursive} onChange={(event) => change({ recursive: event.target.checked })} disabled={attempt.busy} />
            Read the folders in it as well
          </label>
        </>
      )}

      {draft.kind === "biorxiv" && (
        <div className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id={field("since")} label="From" hint="The first day." problem={problems.since}>
              <Input
                id={field("since")}
                type="date"
                value={draft.since}
                onChange={(event) => change({ since: event.target.value })}
                readOnly={attempt.busy}
                aria-invalid={problems.since !== undefined}
                aria-describedby={describedBy(field("since"), { hint: true, problem: problems.since !== undefined })}
              />
            </Field>
            <Field id={field("until")} label="To" hint="The last day. Blank is up to today." problem={problems.until}>
              <Input
                id={field("until")}
                type="date"
                value={draft.until}
                onChange={(event) => change({ until: event.target.value })}
                readOnly={attempt.busy}
                aria-invalid={problems.until !== undefined}
                aria-describedby={describedBy(field("until"), { hint: true, problem: problems.until !== undefined })}
              />
            </Field>
            <Field id={field("subject")} label="Subject">
              <NativeSelect
                id={field("subject")}
                value={draft.subject}
                onChange={(event) => change({ subject: event.target.value })}
                disabled={attempt.busy}
              >
                <option value="all">All subjects</option>
                {list.subjects.map((subject) => (
                  <option key={subject} value={subject}>
                    {subject}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field
              id={field("limit")}
              label="How many preprints"
              hint={`Up to ${MAX_BIORXIV_LIMIT}.`}
              problem={problems.limit}
            >
              <Input
                id={field("limit")}
                value={draft.limit}
                onChange={(event) => change({ limit: event.target.value })}
                inputMode="numeric"
                autoComplete="off"
                readOnly={attempt.busy}
                aria-invalid={problems.limit !== undefined}
                aria-describedby={describedBy(field("limit"), { hint: true, problem: problems.limit !== undefined })}
              />
            </Field>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.random} onChange={(event) => change({ random: event.target.checked })} disabled={attempt.busy} />
            Choose them at random from the period, and not the first there are
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={draft.includeUnpublished}
              onChange={(event) => change({ includeUnpublished: event.target.checked })}
              disabled={attempt.busy}
            />
            Include preprints that are not published in a journal yet
          </label>
        </div>
      )}

      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={attempt.busy}>
          <Plus />
          {attempt.busy ? "Making…" : "Make the run"}
        </Button>
      </div>
    </form>
  );
}
