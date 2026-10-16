"use client";

import { useEffect, useId, useRef, useState } from "react";
import { BookOpen, Trash2, X } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { describedBy, Field } from "@/components/settings-fields";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatBytes } from "@/lib/files";
import { checkRead, describeSource, EMPTY_READ, uploadProblem, type ReadDraft } from "@/lib/papers";
import type { PaperRun, PapersList } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt, type Looked } from "@/lib/use-looked";

interface Shared {
  run: PaperRun;
  // Whether the run is being read or has functions written for it, which nothing else is done to it in the meantime
  working: boolean;
  // Shows the run as it now is, as what changed it gives it back
  onChanged: Looked<PaperRun>["set"];
}

// Adds papers to a run whose papers are uploaded, one after another, with how much of each has gone
function AddPapers({ run, list, working, onChanged }: Shared & { list: PapersList }) {
  const { report } = useServer();
  const id = useId();
  const [sending, setSending] = useState<{ name: string; progress: number } | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  // A file chosen cannot be taken out of its input, so the input is made again to empty it
  const [inputs, setInputs] = useState(0);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  async function add(files: File[]) {
    const called = new AbortController();
    controller.current = called;
    setProblems([]);
    const refused: string[] = [];
    let names = run.uploads?.map((upload) => upload.name) ?? [];
    const limits = { bytes: list.max_paper_bytes, suffixes: list.suffixes, files: list.max_files };
    for (const file of files) {
      const problem = uploadProblem(file, names, limits);
      if (problem !== null) {
        refused.push(problem);
        continue;
      }
      setSending({ name: file.name, progress: 0 });
      try {
        const next = await api.uploadPaper(run.id, file, {
          onProgress: (progress) => setSending({ name: file.name, progress }),
          signal: called.signal,
        });
        names = next.uploads?.map((upload) => upload.name) ?? names;
        onChanged(next);
      } catch (error) {
        // Papers that were called off are not a failure to say anything of
        if (called.signal.aborted) break;
        report(error);
        refused.push(`${file.name}: ${describeError(error)}`);
      }
    }
    controller.current = null;
    setSending(null);
    setProblems(refused);
    setInputs((was) => was + 1);
  }

  return (
    <div className="flex flex-col gap-2">
      <Field
        id={`${id}-files`}
        label="Add papers"
        hint={`${list.suffixes.join(", ")} files, of up to ${formatBytes(list.max_paper_bytes)} each. They are kept by the lab.`}
      >
        <Input
          key={inputs}
          id={`${id}-files`}
          type="file"
          multiple
          accept={list.suffixes.join(",")}
          disabled={working || sending !== null}
          onChange={(event) => void add(Array.from(event.target.files ?? []))}
          aria-describedby={describedBy(`${id}-files`, { hint: true })}
          className="h-auto cursor-pointer py-1 file:mr-3 file:cursor-pointer file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground"
        />
      </Field>
      {sending !== null && (
        <div className="flex flex-col gap-1" role="status">
          <Progress value={sending.progress} aria-label={`Uploading ${sending.name}`} />
          <p className="text-xs text-muted-foreground">
            Uploading {sending.name}, {Math.round(sending.progress * 100)}%
          </p>
          <div>
            <Button type="button" variant="outline" size="xs" onClick={() => controller.current?.abort()}>
              <X />
              Cancel the upload
            </Button>
          </div>
        </div>
      )}
      {problems.length > 0 && (
        <div role="alert">
          <ul aria-label="Papers that were not added" className="flex flex-col gap-1 text-sm text-destructive">
            {problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Uploads({ run, working, onChanged }: Shared) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const uploads = run.uploads ?? [];

  async function remove(name: string) {
    const next = await attempt.run(() => api.removePaper(run.id, name));
    if (next) onChanged(next);
  }

  return (
    <div className="flex flex-col gap-2">
      {uploads.length === 0 ? (
        <p className="text-sm text-muted-foreground">No paper is uploaded to this run yet.</p>
      ) : (
        <ul aria-label="Uploaded papers" className="flex flex-col gap-1">
          {uploads.map((upload) => (
            <li key={upload.name} className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5" data-testid="paper-upload">
              <code className="min-w-0 flex-1 break-all text-sm">{upload.name}</code>
              <span className="shrink-0 text-xs text-muted-foreground">{formatBytes(upload.bytes)}</span>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => void remove(upload.name)}
                disabled={working || attempt.busy}
                aria-label={`Remove ${upload.name}`}
              >
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
    </div>
  );
}

// Says how much reading may cost, which is always said, and starts it
function ReadForm({ run, working, jobs }: Pick<Shared, "run" | "working"> & { jobs: JobsData }) {
  const { report } = useServer();
  const id = useId();
  const [draft, setDraft] = useState<ReadDraft>(EMPTY_READ);
  const [tried, setTried] = useState(false);
  const attempt = useAttempt(report);
  const checked = checkRead(draft);
  const problems = tried ? checked.problems : {};
  const nothing = run.source.kind === "files" && (run.uploads?.length ?? 0) === 0;
  const failures = (run.failed ?? 0) > 0 || run.results.some((result) => result.status === "failed");

  async function read() {
    setTried(true);
    const options = checked.value;
    if (options === null) return;
    const job = await attempt.run(() => api.readPapers(run.id, options));
    if (job) jobs.track(job);
  }

  return (
    <form
      aria-label="Read the papers"
      onSubmit={(event) => {
        event.preventDefault();
        void read();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <p className="text-sm text-muted-foreground">
        Reads each paper that has not been read, and finds the tasks, databases, and software it uses. It is read by the model in the
        settings, which costs what that model charges, so say the most it may spend. A run that stopped carries on from where it was.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id={`${id}-budget`} label="Most it may spend, in dollars" problem={problems.budget}>
          <Input
            id={`${id}-budget`}
            value={draft.budget}
            onChange={(event) => setDraft((was) => ({ ...was, budget: event.target.value }))}
            inputMode="decimal"
            autoComplete="off"
            aria-invalid={problems.budget !== undefined}
            aria-describedby={describedBy(`${id}-budget`, { problem: problems.budget !== undefined })}
          />
        </Field>
        <Field
          id={`${id}-paper`}
          label="Most one paper may spend"
          hint="Optional. A paper that would spend more is not read."
          problem={problems.perPaper}
        >
          <Input
            id={`${id}-paper`}
            value={draft.perPaper}
            onChange={(event) => setDraft((was) => ({ ...was, perPaper: event.target.value }))}
            inputMode="decimal"
            autoComplete="off"
            aria-invalid={problems.perPaper !== undefined}
            aria-describedby={describedBy(`${id}-paper`, { hint: true, problem: problems.perPaper !== undefined })}
          />
        </Field>
      </div>
      {failures && (
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={draft.retryFailed}
            onChange={(event) => setDraft((was) => ({ ...was, retryFailed: event.target.checked }))}
          />
          Read again the papers that failed
        </label>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={working || attempt.busy || nothing}>
          <BookOpen />
          {attempt.busy ? "Starting…" : "Read the papers"}
        </Button>
        {nothing && <span className="text-xs text-muted-foreground">Add some papers first.</span>}
      </div>
    </form>
  );
}

// Where a run's papers are from, adding to them where they are uploaded, and reading them
export function PapersSection({ run, list, working, onChanged, jobs }: Shared & { list: PapersList; jobs: JobsData }) {
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm">{describeSource(run.source)}</p>
      {run.source.kind === "files" && (
        <>
          <Uploads run={run} working={working} onChanged={onChanged} />
          <AddPapers run={run} list={list} working={working} onChanged={onChanged} />
        </>
      )}
      <ReadForm run={run} working={working} jobs={jobs} />
    </div>
  );
}
