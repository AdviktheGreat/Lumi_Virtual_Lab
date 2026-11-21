"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ExternalLink, Trash2, X } from "lucide-react";
import { Looked } from "@/components/looked";
import { ProblemNotice } from "@/components/messages";
import { PageSection } from "@/components/page-section";
import { CodeSection } from "@/components/paper-agent-code";
import { ChecksSection } from "@/components/paper-agent-checks";
import { ClaimsSection } from "@/components/paper-agent-claims";
import { VariantsSection } from "@/components/paper-agent-variants";
import { DataSection } from "@/components/paper-agent-data";
import { EnvironmentSection } from "@/components/paper-agent-environment";
import { GivenSection } from "@/components/paper-agent-given";
import { ImportedSection } from "@/components/paper-agent-imported";
import { OneGoSection } from "@/components/paper-agent-onego";
import { CardSection } from "@/components/paper-agent-card";
import { ReadingSection } from "@/components/paper-agent-reading";
import { ReferenceSection } from "@/components/paper-agent-reference";
import { ReimplementationSection } from "@/components/paper-agent-reimplementation";
import { ToolsSection } from "@/components/paper-agent-tools";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatBytes } from "@/lib/files";
import {
  agentAddress,
  AGENTS_ADDRESS,
  checksJob,
  dataJob,
  describePaper,
  describeSource,
  describeSteps,
  environmentJob,
  existingOf,
  isLink,
  lastChecksJob,
  lastDataJob,
  lastEnvironmentJob,
  lastMatchingJob,
  lastReadingJob,
  lastReferenceJob,
  lastReimplementationJob,
  lastReproductionJob,
  lastRepositoryJob,
  lastToolsJob,
  lastVariantJob,
  matchingJob,
  MAX_AGENT_TITLE,
  onegoJob,
  paperFile,
  paperLink,
  readingJob,
  readingKey,
  referenceJob,
  reimplementationJob,
  repoName,
  reproductionJob,
  repositoryJob,
  repoProblem,
  STATUS_LABELS,
  STEP_LABELS,
  STEPS,
  titleProblem,
  toolsJob,
  variantJob,
} from "@/lib/paperagents";
import { hasChecks } from "@/lib/paperagent-checks";
import { uploadProblem } from "@/lib/papers";
import { tidy } from "@/lib/scientists";
import type {
  PaperAgent,
  PaperAgentChecks,
  PaperAgentClaims,
  PaperAgentData,
  PaperAgentEnvironment,
  PaperAgentGiven,
  PaperAgentOneGo,
  PaperAgentReading,
  PaperAgentReference,
  PaperAgentReimplementation,
  PaperAgentRepository,
  PaperAgentsList,
  PaperAgentSource,
  PaperAgentTools,
} from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt, type Looked as LookedAt } from "@/lib/use-looked";
import {
  usePaperAgent,
  usePaperAgentChecks,
  usePaperAgentClaims,
  usePaperAgentData,
  usePaperAgentEnvironment,
  usePaperAgentGiven,
  usePaperAgentOneGo,
  usePaperAgentReading,
  usePaperAgentReference,
  usePaperAgentReimplementation,
  usePaperAgentRepository,
  usePaperAgentsList,
  usePaperAgentTools,
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
          {agent.imported !== null && (
            <div className="my-1 flex flex-wrap gap-2" data-testid="imported-badges">
              <Badge variant="secondary">Imported</Badge>
              <Badge variant="outline">Not checked here</Badge>
            </div>
          )}
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
  data,
  reference,
  tools,
  checks,
  claims,
  reimplementation,
  given,
  onego,
  onChanged,
  onReload,
}: Pick<Shared, "agent" | "list" | "onChanged"> & {
  jobs: JobsData;
  reading: LookedAt<PaperAgentReading>;
  repository: LookedAt<PaperAgentRepository>;
  environment: LookedAt<PaperAgentEnvironment>;
  data: LookedAt<PaperAgentData>;
  reference: LookedAt<PaperAgentReference>;
  tools: LookedAt<PaperAgentTools>;
  checks: LookedAt<PaperAgentChecks>;
  claims: LookedAt<PaperAgentClaims>;
  reimplementation: LookedAt<PaperAgentReimplementation>;
  given: LookedAt<PaperAgentGiven>;
  onego: LookedAt<PaperAgentOneGo>;
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
  // The same of the data, which is fetched on its own, but not while anything else is done to the agent
  const getting = dataJob(all, agent.id);
  const fetchingData = getting !== undefined || agent.steps.data === "running";
  const gotten = data.value.kind === "ready" ? data.value.value : null;
  const lastGet = lastDataJob(all, agent.id);
  // How the last fetching ended is said if it did not end well, and while the files it fetched are kept
  const lastGetShown = lastGet !== undefined && (lastGet.state !== "succeeded" || (gotten?.kept.files ?? 0) > 0) ? lastGet : undefined;
  // The same of the tutorials, which are run in the environment, and not while anything else is done to the agent. The agent says that
  // its tools are being made while they are run or while the tools are made, which is the step they are part of, so until the jobs
  // have been looked at it is not known which of the two it is
  const running = referenceJob(all, agent.id);
  const makingTools = toolsJob(all, agent.id);
  const checkingTools = checksJob(all, agent.id);
  const runningTutorials =
    running !== undefined || (agent.steps.tools === "running" && makingTools === undefined && checkingTools === undefined);
  const ranReference = reference.value.kind === "ready" ? reference.value.value : null;
  const lastRun = lastReferenceJob(all, agent.id);
  // How the last run ended is said if it did not end well, and while what it gave is kept
  // A run that is over, and succeeded, while what the page has of it is from before it ended: it is looked at again, and what is
  // kept is not said to be a run that did not come to its end in the meantime
  const settling = lastRun?.state === "succeeded" && ranReference?.kept != null && !ranReference.kept.complete;
  const lastRunShown =
    lastRun !== undefined && (lastRun.state !== "succeeded" || (ranReference?.kept?.tutorials.length ?? 0) > 0) ? lastRun : undefined;
  // The same of the tools, which are made of what the tutorials gave
  const madeTools = tools.value.kind === "ready" ? tools.value.value : null;
  const lastMaking = lastToolsJob(all, agent.id);
  // How the last making ended is said if it did not end well, and while what it made is kept
  const lastMakingShown = lastMaking !== undefined && (lastMaking.state !== "succeeded" || madeTools?.kept != null) ? lastMaking : undefined;
  // A making that is over, and succeeded, while what the page has of it is from before it ended
  const settlingTools = lastMaking?.state === "succeeded" && madeTools?.kept != null && !madeTools.kept.complete;
  // The same of the checks of the tools, which are made of the tools, and which the agent says go on under the step of its tools
  const madeChecks = checks.value.kind === "ready" ? checks.value.value : null;
  const lastChecking = lastChecksJob(all, agent.id);
  // How the last checking ended is said if it did not end well, and while there is anything that it made
  const lastCheckingShown =
    lastChecking !== undefined && (lastChecking.state !== "succeeded" || (madeChecks !== null && hasChecks(madeChecks.tools))) ? lastChecking : undefined;
  // The same of the claims, which are held to what the tutorials gave, and of the variants made of them. Neither is a step of the agent, so
  // the agent does not say that they go on
  const tryingClaims = reproductionJob(all, agent.id);
  const makingVariant = variantJob(all, agent.id);
  const madeClaims = claims.value.kind === "ready" ? claims.value.value.reproduction : null;
  const lastTrying = lastReproductionJob(all, agent.id);
  // How the last trying ended is said if it did not end well, and while what it made is kept
  const lastTryingShown = lastTrying !== undefined && (lastTrying.state !== "succeeded" || madeClaims?.kept != null) ? lastTrying : undefined;
  const madeVariants = claims.value.kind === "ready" ? claims.value.value.variants : null;
  const lastVariant = lastVariantJob(all, agent.id);
  // How the last making of a variant ended is said if it did not end well, and while there are variants that it made
  const lastVariantShown = lastVariant !== undefined && (lastVariant.state !== "succeeded" || (madeVariants !== null && madeVariants.variants.length > 0)) ? lastVariant : undefined;
  // The same of the function written from the paper, and of checking it against the paper, neither of which is a step of the agent
  const writingFunction = reimplementationJob(all, agent.id);
  const checkingFunction = matchingJob(all, agent.id);
  const written = reimplementation.value.kind === "ready" ? reimplementation.value.value : null;
  const lastWriting = lastReimplementationJob(all, agent.id);
  // How the last writing ended is said if it did not end well, and while what it wrote is kept
  const lastWritingShown = lastWriting !== undefined && (lastWriting.state !== "succeeded" || written?.kept != null) ? lastWriting : undefined;
  const lastMatching = lastMatchingJob(all, agent.id);
  // How the last checking ended is said if it did not end well, and while what it found is kept
  const lastMatchingShown =
    lastMatching !== undefined && (lastMatching.state !== "succeeded" || written?.checks.kept != null) ? lastMatching : undefined;
  // Making it in one go, which does the steps one after another, and nothing else is done to the agent in the meantime. The agent
  // says that it is being made before the jobs have been looked at
  const going = onegoJob(all, agent.id);
  const makingInOneGo = going !== undefined || agent.onego != null;
  // Whether anything but making it in one go is being done to the agent, which starting that waits for
  const othersIdle =
    !working &&
    !fetchingCode &&
    !makingEnvironment &&
    !fetchingData &&
    !runningTutorials &&
    makingTools === undefined &&
    checkingTools === undefined &&
    tryingClaims === undefined &&
    makingVariant === undefined &&
    writingFunction === undefined &&
    checkingFunction === undefined;
  const idle = othersIdle && !makingInOneGo;
  // What the agent's address, paper, or title is changed to may take away its code, and what the paper points to is found from
  // its paper, so the code is looked at again, and the environment, which is of the code
  const changed = (next: PaperAgent) => {
    onChanged(next);
    repository.reload();
    environment.reload();
    data.reload();
    reference.reload();
    claims.reload();
    tools.reload();
    reimplementation.reload();
    checks.reload();
    given.reload();
    onego.reload();
  };
  const shared = { agent, list, working: !idle, onChanged: changed };
  const own = agent.paper.kind === "file";

  return (
    <>
      <AgentHeader agent={agent} working={!idle} />
      <WorkStatus job={job} last={lastReadingJob(all, agent.id)} jobs={jobs} />
      {agent.imported === null && (
        <PageSection
          title="In one go"
          intro="Every step that needs nothing from you, done one after another, from reading the paper to giving the agent to your conversations. Each is the step of its own section below, which shows what it made. A step that was done is not done again."
        >
          <Looked state={onego.value} label="Looking at making it in one go" failure="Making it in one go could not be looked at." onRetry={onego.reload}>
            {(value) => (
              <OneGoSection
                agent={agent}
                onego={value}
                busy={!othersIdle}
                job={going}
                jobs={jobs}
                list={list}
                onChanged={(next) => {
                  onego.set(next);
                  // Going on without the code, or with an address, is kept with the agent
                  onReload();
                }}
              />
            )}
          </Looked>
        </PageSection>
      )}
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
            // A function written from the paper is of the file it was written from
            reimplementation.reload();
          }}
        />
      </PageSection>
      <PageSection title="Reading" intro="What the paper reports, and the software, links, and licenses it names, each with its own words.">
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
                makingInOneGo
                  ? "The agent is being made in one go. Reading waits for that."
                  : fetchingCode
                    ? "The code is being fetched. Reading waits for that."
                    : makingEnvironment
                      ? "The environment is being built. Reading waits for that."
                      : fetchingData
                        ? "The data is being fetched. Reading waits for that."
                        : running !== undefined
                          ? "The tutorials are being run. Reading waits for that."
                          : makingTools !== undefined
                            ? "The tools are being made. Reading waits for that."
                            : checkingTools !== undefined
                              ? "The tools are being checked. Reading waits for that."
                              : tryingClaims !== undefined
                                ? "The claims are being tried. Reading waits for that."
                                : makingVariant !== undefined
                                  ? "A variant of a claim is being made. Reading waits for that."
                                  : writingFunction !== undefined
                                    ? "A function is being written from the paper. Reading waits for that."
                                    : checkingFunction !== undefined
                                      ? "The function written from the paper is being checked. Reading waits for that."
                                      : runningTutorials
                                        ? "The tutorials are being run or the tools made. Reading waits for that."
                                        : null
              }
              jobs={jobs}
              onCleared={(cleared) => {
                reading.set(cleared);
                onReload();
                // The claims that are tried are those that were read
                claims.reload();
                // A function is written from what was read, and checked against its numbers
                reimplementation.reload();
                // What the paper points to is found from what was read
                repository.reload();
                data.reload();
                // The tools that read it are given only while its text is kept
                given.reload();
              }}
            />
          )}
        </Looked>
      </PageSection>
      <PageSection
        title="Method card"
        intro="What the method was done with and tested on, and where it falls short. A model drafts it from the paper. You read it, put right what is wrong, and approve it, and what you did is kept apart and marked as yours."
      >
        <Looked
          state={reading.value}
          label="Looking at the method card"
          failure="The method card could not be looked at."
          onRetry={reading.reload}
        >
          {(value) => (
            <CardSection
              agent={agent}
              reading={value}
              working={working}
              onChanged={(next) => {
                reading.set(next);
                // The data that the paper names, and whether it can be found, are of the card
                data.reload();
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
                // What the code names for the data is found from the code, and its tutorials are what are run
                data.reload();
                reference.reload();
                claims.reload();
                tools.reload();
                reimplementation.reload();
                checks.reload();
                given.reload();
                onReload();
              }}
              onStale={() => {
                onReload();
                repository.reload();
                environment.reload();
                data.reload();
                reference.reload();
                claims.reload();
                tools.reload();
                reimplementation.reload();
                checks.reload();
                given.reload();
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
                // What was run in the image goes with it
                reference.reload();
                claims.reload();
                tools.reload();
                reimplementation.reload();
                checks.reload();
                given.reload();
                onReload();
              }}
              onStale={() => {
                onReload();
                environment.reload();
                reference.reload();
                claims.reload();
                tools.reload();
                reimplementation.reload();
                checks.reload();
                given.reload();
              }}
            />
          )}
        </Looked>
      </PageSection>
      <PageSection
        title="Data"
        intro="Where the data the paper used is, what each place has, and the files you choose to fetch. Nothing is fetched until you have seen the files and agreed to what they come to."
      >
        <WorkStatus job={getting} last={lastGetShown} jobs={jobs} label="Fetching the data" />
        <Looked state={data.value} label="Looking at the data" failure="The data could not be looked at." onRetry={data.reload}>
          {(value) => (
            <DataSection
              key={agent.id}
              agent={agent}
              data={value}
              busy={!idle}
              fetching={getting}
              jobs={jobs}
              onData={(next) => {
                data.set(next);
                // What the tutorials are given to read is what was fetched
                reference.reload();
                claims.reload();
                tools.reload();
                reimplementation.reload();
                checks.reload();
                given.reload();
                onReload();
              }}
            />
          )}
        </Looked>
      </PageSection>
      <PageSection
        title="Tutorials"
        intro="The tutorials of the code, run in the environment so that what they did is kept. This shows that they ran here and what they gave. It does not show that what they gave is right."
      >
        <WorkStatus job={running} last={lastRunShown} jobs={jobs} label="Running the tutorials" />
        <Looked state={reference.value} label="Looking at the tutorials" failure="The tutorials could not be looked at." onRetry={reference.reload}>
          {(value) => (
            <ReferenceSection
              key={agent.id}
              agent={agent}
              reference={value}
              busy={!idle}
              running={running}
              settling={settling}
              jobs={jobs}
              onCleared={(cleared) => {
                reference.set(cleared);
                // The tools are made of what the tutorials gave
                tools.reload();
                reimplementation.reload();
                checks.reload();
                given.reload();
                onReload();
              }}
              onStale={() => {
                onReload();
                reference.reload();
                claims.reload();
                tools.reload();
                reimplementation.reload();
                checks.reload();
                given.reload();
              }}
            />
          )}
        </Looked>
      </PageSection>
      <PageSection
        title="Tools"
        intro="Small functions that each call one function of the code, made of the calls the tutorials made. Each is called again in the environment, to see that it gives what the tutorial got. This does not show that what it gives is right."
      >
        <WorkStatus job={makingTools} last={lastMakingShown} jobs={jobs} label="Making the tools" />
        <Looked state={tools.value} label="Looking at the tools" failure="The tools could not be looked at." onRetry={tools.reload}>
          {(value) => (
            <ToolsSection
              key={agent.id}
              agent={agent}
              tools={value}
              busy={!idle}
              making={makingTools}
              settling={settlingTools}
              jobs={jobs}
              onCleared={(cleared) => {
                tools.set(cleared);
                // The checks are of the tools, so they go with them
                checks.reload();
                // A function can be written from the paper only while there are no tools of the authors' code
                reimplementation.reload();
                given.reload();
                onReload();
              }}
              onStale={() => {
                onReload();
                reference.reload();
                claims.reload();
                tools.reload();
                reimplementation.reload();
                checks.reload();
                given.reload();
              }}
            />
          )}
        </Looked>
      </PageSection>
      <PageSection
        title="Checks"
        intro="What the tools gave again for inputs that their tutorials did not pass, what the code's own tests say, and, where you ask for it, what the paper reports. A tool that passed checks against two different things is of tier B. This does not show that what a tool gives is right."
      >
        <WorkStatus job={checkingTools} last={lastCheckingShown} jobs={jobs} label="Checking the tools" />
        <Looked state={checks.value} label="Looking at the checks" failure="The checks could not be looked at." onRetry={checks.reload}>
          {(value) => (
            <ChecksSection
              key={agent.id}
              agent={agent}
              checks={value}
              busy={!idle}
              checking={checkingTools}
              jobs={jobs}
              onCleared={(cleared) => {
                checks.set(cleared);
                // What a conversation is given says the tier of each tool
                given.reload();
                onReload();
              }}
              onStale={() => {
                onReload();
                reference.reload();
                claims.reload();
                tools.reload();
                reimplementation.reload();
                checks.reload();
                given.reload();
              }}
            />
          )}
        </Looked>
      </PageSection>
      <PageSection
        title="Claims"
        intro="Each claim of the paper that states a number, held to what the tutorials gave when they were run here, and, for those that did not reproduce, where the tutorial first parts from the paper. This is of the tutorials as they ran here. It does not say that they were run on the paper's data, or that the paper is right."
      >
        <WorkStatus job={tryingClaims} last={lastTryingShown} jobs={jobs} label="Trying the claims" />
        <Looked state={claims.value} label="Looking at the claims" failure="The claims could not be looked at." onRetry={claims.reload}>
          {(value) => (
            <ClaimsSection
              key={agent.id}
              agent={agent}
              claims={value}
              busy={!idle}
              trying={tryingClaims}
              jobs={jobs}
              onCleared={() => claims.reload()}
              onStale={() => {
                onReload();
                reference.reload();
                tools.reload();
                reimplementation.reload();
                checks.reload();
                claims.reload();
                given.reload();
              }}
            />
          )}
        </Looked>
      </PageSection>
      <PageSection
        title="Variants"
        intro="A claim's call made again, in the environment of the tutorials, with arguments that you change, beside what the claim was held to. A variant is not the paper's result, and it does not change what was said of its claim."
      >
        <WorkStatus job={makingVariant} last={lastVariantShown} jobs={jobs} label="Making a variant" />
        <Looked state={claims.value} label="Looking at the variants" failure="The variants could not be looked at." onRetry={claims.reload}>
          {(value) => (
            <VariantsSection
              key={agent.id}
              agent={agent}
              claims={value}
              busy={!idle}
              making={makingVariant}
              jobs={jobs}
              onCleared={() => claims.reload()}
              onStale={() => {
                onReload();
                reference.reload();
                tools.reload();
                reimplementation.reload();
                checks.reload();
                claims.reload();
                given.reload();
              }}
            />
          )}
        </Looked>
      </PageSection>
      <PageSection
        title="Re-implementation"
        intro="For a paper with no code, a function that a model writes from the paper's words, which you choose and read before anything is sent. It is a re-implementation, not the authors' code, and is labelled as one wherever it is shown. It is given to conversations only once it gives a number that the paper reports, which does not show that it does what the authors did."
      >
        <WorkStatus job={writingFunction} last={lastWritingShown} jobs={jobs} label="Writing the function" />
        <WorkStatus job={checkingFunction} last={lastMatchingShown} jobs={jobs} label="Checking the function" />
        <Looked
          state={reimplementation.value}
          label="Looking at the re-implementation"
          failure="The re-implementation could not be looked at."
          onRetry={reimplementation.reload}
        >
          {(value) => (
            <ReimplementationSection
              key={agent.id}
              agent={agent}
              reimplementation={value}
              busy={!idle}
              writing={writingFunction}
              checking={checkingFunction}
              jobs={jobs}
              onChanged={(next) => {
                reimplementation.set(next);
                // What a conversation is given is of the function and of what came of checking it
                given.reload();
              }}
              onStale={() => {
                onReload();
                reading.reload();
                tools.reload();
                reimplementation.reload();
                given.reload();
              }}
            />
          )}
        </Looked>
      </PageSection>
      <PageSection
        title={agent.imported === null ? "Import a server" : "Imported server"}
        intro={
          agent.imported === null
            ? "An agent that someone else made of this paper runs on a server of theirs. Bringing it in lets you give it to conversations, shown as imported and not checked, with every call waiting for you."
            : "This agent was made by someone else, and runs on a server of theirs. Nothing of the lab's has been done to it: what it says of itself is what its maker says."
        }
      >
        <ImportedSection key={agent.id} agent={agent} onChanged={changed} />
      </PageSection>
      <PageSection
        title="In conversations"
        intro="Give this agent to the conversations you start, so that the lead can search what the paper says, with the place, and, where code runs, call the tools made of its code or the function written from its words. A tier says how far a tool was checked. It does not say that what the paper says or what a tool gives is right."
      >
        <Looked state={given.value} label="Looking at what the agent gives" failure="What the agent gives could not be looked at." onRetry={given.reload}>
          {(value) => (
            <GivenSection
              key={agent.id}
              agent={agent}
              given={value}
              onChanged={(next) => {
                onChanged(next);
                given.reload();
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
  const data = usePaperAgentData(id, report, again);
  const reference = usePaperAgentReference(id, report, again);
  const tools = usePaperAgentTools(id, report, again);
  const checks = usePaperAgentChecks(id, report, again);
  const claims = usePaperAgentClaims(id, report, again);
  const reimplementation = usePaperAgentReimplementation(id, report, again);
  const given = usePaperAgentGiven(id, report, again);
  const onego = usePaperAgentOneGo(id, report, again);
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
                data={data}
                reference={reference}
                tools={tools}
                checks={checks}
                claims={claims}
                reimplementation={reimplementation}
                given={given}
                onego={onego}
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
