"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ExternalLink, Trash2, X } from "lucide-react";
import { Looked } from "@/components/looked";
import { ProblemNotice } from "@/components/messages";
import { PageSection } from "@/components/page-section";
import { CodeSection } from "@/components/paper-agent-code";
import { EnvironmentSection } from "@/components/paper-agent-environment";
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
  describeSource,
  describeSteps,
  environmentJob,
  existingOf,
  isLink,
  lastEnvironmentJob,
  lastReadingJob,
  lastRepositoryJob,
  MAX_AGENT_TITLE,
  paperFile,
  paperLink,
  readingJob,
  readingKey,
  repoName,
  repositoryJob,
  repoProblem,
  STATUS_LABELS,
  STEP_LABELS,
  STEPS,
  titleProblem,
} from "@/lib/paperagents";
import { uploadProblem } from "@/lib/papers";
import { tidy } from "@/lib/scientists";
import type {
  PaperAgent,
  PaperAgentEnvironment,
  PaperAgentReading,
  PaperAgentRepository,
  PaperAgentsList,
  PaperAgentSource,
} from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt, type Looked as LookedAt } from "@/lib/use-looked";
import {
  usePaperAgent,
  usePaperAgentEnvironment,
  usePaperAgentReading,
  usePaperAgentRepository,
  usePaperAgentsList,
} from "@/lib/use-paperagents";
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
              {agent.repo.commit !== undefined && (
                <>
                  {" "}
                  at commit <code className="font-mono text-xs">{agent.repo.commit.slice(0, 12)}</code>
                </>
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
        hint={
          agent.steps.repository === "done"
            ? "Leave it blank if the paper has no code. Changing it takes away the code that was fetched from the old address."
            : "Leave it blank if the paper has no code."
        }
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

// Where the text of a paper was fetched from, with the way to see it there
function Source({ source }: { source: PaperAgentSource }) {
  return (
    <p className="break-words text-xs text-muted-foreground" data-testid="paper-agent-source">
      {isLink(source.url) ? (
        <a href={source.url} target="_blank" rel="noreferrer noopener" className={cn("inline-flex items-center gap-1", LINK)}>
          {describeSource(source)}
          <ExternalLink className="size-3" aria-hidden />
          <span className="sr-only">(opens in a new tab)</span>
        </a>
      ) : (
        describeSource(source)
      )}
      . It is kept as the paper, and is not fetched again.
    </p>
  );
}

// The file the paper is read from: what has been uploaded, or what was fetched and from where, and the way to upload it
// or take it away
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
        <p className="text-sm text-muted-foreground">
          {agent.paper.kind === "file"
            ? "No paper is uploaded to this agent yet."
            : "No file is kept yet. The text of the paper is fetched when it is read, and kept here."}
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
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
          {file.source != null && <Source source={file.source} />}
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
  repository,
  environment,
  onChanged,
  onReload,
}: Pick<Shared, "agent" | "list" | "onChanged"> & {
  jobs: JobsData;
  reading: LookedAt<PaperAgentReading>;
  repository: LookedAt<PaperAgentRepository>;
  environment: LookedAt<PaperAgentEnvironment>;
  // Looks at the agent again, as is done when what was read of its paper is taken away, which changes its steps
  onReload: () => void;
}) {
  const all = jobs.jobs ?? [];
  const job = readingJob(all, agent.id);
  // The agent says that its paper is being read before the jobs have been looked at, as they are when the page opens
  const working = job !== undefined || agent.steps.reading === "running";
  const fetching = repositoryJob(all, agent.id);
  // The same of the code, which is fetched on its own, but not while the paper is read or the agent is changed
  const fetchingCode = fetching !== undefined || agent.steps.repository === "running";
  // How the last fetching ended is said while what it fetched is kept, and if it did not end well, but not after the code has
  // been taken away
  const lastFetch = lastRepositoryJob(all, agent.id);
  const kept = repository.value.kind === "ready" && repository.value.value.cloned;
  // The same of the environment, which is built from the code, and not while anything else is done to the agent
  const making = environmentJob(all, agent.id);
  const makingEnvironment = making !== undefined || agent.steps.environment === "running";
  const lastMake = lastEnvironmentJob(all, agent.id);
  const made = environment.value.kind === "ready" ? environment.value.value : null;
  // How the last building ended is said if it was stopped, or failed with nothing to say why beside it, and while what it built
  // is kept
  const lastMakeShown =
    lastMake !== undefined && (lastMake.state === "succeeded" ? made?.built != null : !(lastMake.state === "failed" && made?.failure != null))
      ? lastMake
      : undefined;
  const idle = !working && !fetchingCode && !makingEnvironment;
  // What the agent's address, paper, or title is changed to may take away its code, and what the paper points to is found from
  // its paper, so the code is looked at again, and the environment, which is of the code
  const changed = (next: PaperAgent) => {
    onChanged(next);
    repository.reload();
    environment.reload();
  };
  const shared = { agent, list, working: !idle, onChanged: changed };
  const own = agent.paper.kind === "file";

  return (
    <>
      <AgentHeader agent={agent} working={!idle} />
      <WorkStatus job={job} last={lastReadingJob(all, agent.id)} jobs={jobs} />
      <PageSection
        title={own ? "Paper" : "Paper file"}
        intro={
          own
            ? "The paper of this agent is a file, which is uploaded here."
            : "The paper is read from a file. When a DOI or a link is read, its text is fetched and kept here as the file. A paper that cannot be fetched is read from a file uploaded here."
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
              blocked={
                fetchingCode
                  ? "The code is being fetched. Reading waits for that."
                  : makingEnvironment
                    ? "The environment is being built. Reading waits for that."
                    : null
              }
              jobs={jobs}
              onCleared={(cleared) => {
                reading.set(cleared);
                onReload();
                // What the paper points to is found from what was read
                repository.reload();
              }}
            />
          )}
        </Looked>
      </PageSection>
      <PageSection
        title="Code"
        intro="Where the paper's code is, fetched at one commit, what is in it, and whether it is worth going on with. Nothing in it is run."
      >
        <WorkStatus
          job={fetching}
          last={lastFetch !== undefined && (lastFetch.state !== "succeeded" || kept) ? lastFetch : undefined}
          jobs={jobs}
          label="Fetching the code"
        />
        <Looked
          state={repository.value}
          label="Looking at the code"
          failure="The code could not be looked at."
          onRetry={repository.reload}
        >
          {(value) => (
            <CodeSection
              agent={agent}
              repository={value}
              busy={!idle}
              jobs={jobs}
              onChanged={changed}
              onCleared={(cleared) => {
                repository.set(cleared);
                environment.reload();
                onReload();
              }}
              onStale={() => {
                onReload();
                repository.reload();
                environment.reload();
              }}
            />
          )}
        </Looked>
      </PageSection>
      <PageSection
        title="Environment"
        intro="What the code needs, installed in a container that has none of this machine in it and kept as an image that runs with no network. The code itself is not run."
      >
        <WorkStatus job={making} last={lastMakeShown} jobs={jobs} label="Building the environment" />
        <Looked
          state={environment.value}
          label="Looking at the environment"
          failure="The environment could not be looked at."
          onRetry={environment.reload}
        >
          {(value) => (
            <EnvironmentSection
              key={agent.id}
              agent={agent}
              environment={value}
              busy={!idle}
              building={making}
              jobs={jobs}
              onCleared={(cleared) => {
                environment.set(cleared);
                onReload();
              }}
              onStale={() => {
                onReload();
                environment.reload();
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
  const repository = usePaperAgentRepository(id, report, again);
  const environment = usePaperAgentEnvironment(id, report, again);
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
              <Agent
                agent={value}
                list={limits}
                jobs={jobs}
                reading={reading}
                repository={repository}
                environment={environment}
                onChanged={agent.set}
                onReload={agent.reload}
              />
            )}
          </Looked>
        )}
      </Looked>
    </>
  );
}
