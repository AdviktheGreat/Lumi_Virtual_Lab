"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ExternalLink, Trash2, X } from "lucide-react";
import { Looked } from "@/components/looked";
import { ProblemNotice } from "@/components/messages";
import { PageSection } from "@/components/page-section";
import { ReadingSection } from "@/components/paper-agent-reading";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { WorkStatus } from "@/components/work-status";
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
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatBytes } from "@/lib/files";
import {
  agentAddress,
  AGENTS_ADDRESS,
  describePaper,
  describeSteps,
  existingOf,
  isLink,
  lastReadingJob,
  MAX_AGENT_TITLE,
  paperFile,
  paperLink,
  readingJob,
  readingKey,
  repoName,
  repoProblem,
  STATUS_LABELS,
  STEP_LABELS,
  STEPS,
  titleProblem,
} from "@/lib/paperagents";
import { uploadProblem } from "@/lib/papers";
import { tidy } from "@/lib/scientists";
import type { PaperAgent, PaperAgentReading, PaperAgentsList } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt, type Looked as LookedAt } from "@/lib/use-looked";
import { usePaperAgent, usePaperAgentReading, usePaperAgentsList } from "@/lib/use-paperagents";
import { cn } from "@/lib/utils";

const LINK = "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

interface Shared {
  agent: PaperAgent;
  list: PaperAgentsList;
  // Whether the paper is being read, which nothing is done to the agent or its paper in the meantime
  working: boolean;
  // Shows the agent as it now is, as what changed it gives it back
  onChanged: LookedAt<PaperAgent>["set"];
}

// An agent, with its title, which paper it is of, and the way to delete it
function AgentHeader({ agent, working }: { agent: PaperAgent; working: boolean }) {
  const { report } = useServer();
  const router = useRouter();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);
  const link = paperLink(agent.paper);

  async function remove() {
    const left = await attempt.run(() => api.deletePaperAgent(agent.id));
    if (left) router.push(AGENTS_ADDRESS);
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="break-words font-serif text-2xl font-medium tracking-tight">{agent.title}</h2>
          <p className="break-all text-sm text-muted-foreground">
            {link === null ? (
              describePaper(agent.paper)
            ) : (
              <a href={link} target="_blank" rel="noreferrer noopener" className={cn("inline-flex items-center gap-1", LINK)}>
                {describePaper(agent.paper)}
                <ExternalLink className="size-3" aria-hidden />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            )}
          </p>
          {agent.repo !== null && (
            <p className="break-all text-sm text-muted-foreground">
              Code:{" "}
              {isLink(agent.repo.url) ? (
                <a href={agent.repo.url} target="_blank" rel="noreferrer noopener" className={cn("inline-flex items-center gap-1", LINK)}>
                  {repoName(agent.repo.url)}
                  <ExternalLink className="size-3" aria-hidden />
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              ) : (
                agent.repo.url
              )}
            </p>
          )}
          <p className="text-sm text-muted-foreground">{describeSteps(agent)}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setAsking(true)}
          disabled={working || attempt.busy}
          aria-label={`Delete ${agent.title}`}
        >
          <Trash2 />
          Delete
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {agent.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This deletes the agent, with the paper that was uploaded to it and anything that was made from it. A paper that is on the
              web, and its code, are left where they are.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void remove()}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// How far each step of making the agent has got
function Steps({ agent }: { agent: PaperAgent }) {
  return (
    <ol aria-label="Steps" className="flex flex-col gap-1">
      {STEPS.map((step) => (
        <li key={step} className="flex items-baseline justify-between gap-3 rounded-lg border border-border px-3 py-1.5" data-testid="paper-agent-step">
          <span className="text-sm">{STEP_LABELS[step]}</span>
          <span className="shrink-0 text-xs text-muted-foreground">{STATUS_LABELS[agent.steps[step]]}</span>
        </li>
      ))}
    </ol>
  );
}

// What the agent is called, and where its code is, which can be said again
function Details({ agent, list, onChanged }: Shared) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [title, setTitle] = useState(agent.title);
  const [repo, setRepo] = useState(agent.repo?.url ?? "");
  const [tried, setTried] = useState(false);
  const wrongTitle = titleProblem(title, true);
  const wrongRepo = repoProblem(repo, list.repo_hosts);
  const named = tidy(title);
  const where = repo.trim();
  const change = {
    ...(named !== agent.title ? { title: named } : {}),
    ...(where !== (agent.repo?.url ?? "") ? { repo: where } : {}),
  };
  const changed = Object.keys(change).length > 0;

  async function save() {
    setTried(true);
    if (wrongTitle !== null || wrongRepo !== null || !changed) return;
    const next = await attempt.run(() => api.changePaperAgent(agent.id, change));
    if (next) {
      onChanged(next);
      setTitle(next.title);
      setRepo(next.repo?.url ?? "");
      setTried(false);
    }
  }

  return (
    <form
      aria-label="What the agent is"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <Field id={`${id}-title`} label="Title" problem={tried && wrongTitle !== null ? wrongTitle : undefined}>
        <Input
          id={`${id}-title`}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          maxLength={MAX_AGENT_TITLE * 4}
          autoComplete="off"
          readOnly={attempt.busy}
          aria-invalid={tried && wrongTitle !== null}
          aria-describedby={describedBy(`${id}-title`, { problem: tried && wrongTitle !== null })}
        />
      </Field>
      <Field
        id={`${id}-repo`}
        label="Where its code is"
        hint="Leave it blank if the paper has no code."
        problem={tried && wrongRepo !== null ? wrongRepo : undefined}
      >
        <Input
          id={`${id}-repo`}
          value={repo}
          onChange={(event) => setRepo(event.target.value)}
          placeholder="https://github.com/owner/name"
          autoComplete="off"
          spellCheck={false}
          readOnly={attempt.busy}
          aria-invalid={tried && wrongRepo !== null}
          aria-describedby={describedBy(`${id}-repo`, { hint: true, problem: tried && wrongRepo !== null })}
        />
      </Field>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={attempt.busy || !changed}>
          {attempt.busy ? "Saving…" : "Save"}
        </Button>
      </div>
    </form>
  );
}

// The paper of an agent whose paper is a file: what has been uploaded, and the way to upload it again or take it away
function PaperFile({ agent, list, working, onChanged }: Shared) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [sending, setSending] = useState<{ name: string; progress: number } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [existing, setExisting] = useState<string | null>(null);
  // A file chosen cannot be taken out of its input, so the input is made again to empty it
  const [inputs, setInputs] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const file = paperFile(agent.paper);

  useEffect(() => () => controller.current?.abort(), []);

  async function upload(chosen: File | undefined) {
    if (chosen === undefined) return;
    setProblem(null);
    setExisting(null);
    const wrong = uploadProblem(chosen, [], { bytes: list.max_paper_bytes, suffixes: list.suffixes, files: 1 });
    if (wrong !== null) {
      setProblem(wrong);
      setInputs((was) => was + 1);

      return;
    }
    const called = new AbortController();
    controller.current = called;
    setSending({ name: chosen.name, progress: 0 });
    try {
      onChanged(
        await api.uploadAgentPaper(agent.id, chosen, {
          onProgress: (progress) => setSending({ name: chosen.name, progress }),
          signal: called.signal,
        }),
      );
    } catch (error) {
      // A paper that was called off is not a failure to say anything of
      if (!called.signal.aborted) {
        report(error);
        setProblem(describeError(error));
        setExisting(existingOf(error));
      }
    }
    controller.current = null;
    setSending(null);
    setInputs((was) => was + 1);
  }

  async function remove() {
    setProblem(null);
    const next = await attempt.run(() => api.removeAgentPaper(agent.id));
    if (next) onChanged(next);
  }

  return (
    <div className="flex flex-col gap-3">
      {file === null ? (
        <p className="text-sm text-muted-foreground">No paper is uploaded to this agent yet.</p>
      ) : (
        <div className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5" data-testid="paper-agent-file">
          <code className="min-w-0 flex-1 break-all text-sm">{file.name}</code>
          <span className="shrink-0 text-xs text-muted-foreground">{formatBytes(file.bytes)}</span>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => void remove()}
            disabled={working || attempt.busy || sending !== null}
            aria-label={`Remove ${file.name}`}
          >
            <Trash2 />
          </Button>
        </div>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <Field
        id={`${id}-file`}
        label={file === null ? "Upload the paper" : "Upload it again"}
        hint={`${list.suffixes.join(", ")} files, of up to ${formatBytes(list.max_paper_bytes)}. ${
          file === null ? "It is kept by the lab." : "The file now kept is replaced."
        }`}
      >
        <Input
          key={inputs}
          id={`${id}-file`}
          type="file"
          accept={list.suffixes.join(",")}
          disabled={working || attempt.busy || sending !== null}
          onChange={(event) => void upload(event.target.files?.[0])}
          aria-describedby={describedBy(`${id}-file`, { hint: true })}
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
      {problem !== null && (
        <div role="alert" className="flex flex-col gap-1.5 text-sm text-destructive">
          <p>{problem}</p>
          {existing !== null && (
            <Link href={agentAddress(existing)} className={cn("w-fit text-foreground", LINK)}>
              Open that PaperAgent
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

function Agent({
  agent,
  list,
  jobs,
  reading,
  onChanged,
  onReload,
}: Pick<Shared, "agent" | "list" | "onChanged"> & {
  jobs: JobsData;
  reading: LookedAt<PaperAgentReading>;
  // Looks at the agent again, as is done when what was read of its paper is taken away, which changes its steps
  onReload: () => void;
}) {
  const all = jobs.jobs ?? [];
  const job = readingJob(all, agent.id);
  // The agent says that its paper is being read before the jobs have been looked at, as they are when the page opens
  const working = job !== undefined || agent.steps.reading === "running";
  const shared = { agent, list, working, onChanged };
  const own = agent.paper.kind === "file";

  return (
    <>
      <AgentHeader agent={agent} working={working} />
      <WorkStatus job={job} last={lastReadingJob(all, agent.id)} jobs={jobs} />
      <PageSection
        title={own ? "Paper" : "Paper file"}
        intro={
          own
            ? "The paper of this agent is a file, which is uploaded here."
            : "The paper is read from a file. A DOI or a link is not fetched yet, so upload the file of the paper here to have it read."
        }
      >
        <PaperFile
          key={agent.id}
          {...shared}
          onChanged={(next) => {
            onChanged(next);
            // Whether the paper can be read, and what was read of it, are changed by the file that is kept
            reading.reload();
          }}
        />
      </PageSection>
      <PageSection title="Reading" intro="What the paper says it found, what it did, what it was done with, and where it falls short.">
        <Looked
          state={reading.value}
          label="Looking at what was read"
          failure="What was read could not be looked at."
          onRetry={reading.reload}
        >
          {(value) => (
            <ReadingSection
              agent={agent}
              reading={value}
              working={working}
              jobs={jobs}
              onCleared={(cleared) => {
                reading.set(cleared);
                onReload();
              }}
            />
          )}
        </Looked>
      </PageSection>
      <PageSection title="Steps" intro="What is done to make the paper usable. A step is added to the lab as it is built.">
        <Steps agent={agent} />
      </PageSection>
      <PageSection title="Details">
        <Details key={agent.id} {...shared} />
      </PageSection>
    </>
  );
}

// One agent: its paper, how far it has got, what was read of it, and the way to say again what it is called and where its
// code is
export function AgentPage({ id }: { id: string }) {
  const { report } = useServer();
  const jobs = useSetupJobs();
  // What is shown of the agent and its reading is looked at again as the reading goes on, and when it ends
  const again = readingKey(jobs.jobs, jobs.finished, id);
  const agent = usePaperAgent(id, report, again);
  const reading = usePaperAgentReading(id, report, again);
  const list = usePaperAgentsList(report, "");

  return (
    <>
      <Link
        href={AGENTS_ADDRESS}
        className="inline-flex items-center gap-1 self-start rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        All agents
      </Link>
      <Looked state={agent.value} label="Looking at the agent" failure="The agent could not be looked at." onRetry={agent.reload}>
        {(value) => (
          <Looked
            state={list.value}
            label="Looking at what an agent takes"
            failure="What an agent takes could not be looked at."
            onRetry={list.reload}
          >
            {(limits) => (
              <Agent agent={value} list={limits} jobs={jobs} reading={reading} onChanged={agent.set} onReload={agent.reload} />
            )}
          </Looked>
        )}
      </Looked>
    </>
  );
}
