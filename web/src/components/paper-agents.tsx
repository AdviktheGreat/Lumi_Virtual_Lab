"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Looked } from "@/components/looked";
import { ProblemNotice } from "@/components/messages";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { describedBy, Field } from "@/components/settings-fields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Radio } from "@/components/ui/radio";
import { api } from "@/lib/api";
import { formatBytes } from "@/lib/files";
import {
  agentAddress,
  AGENTS_ADDRESS,
  checkAgent,
  describePaper,
  describeSteps,
  EMPTY_AGENT,
  existingOf,
  MAX_AGENT_TITLE,
  PAPER_KIND_LABELS,
  PAPER_KINDS,
  repoName,
  type AgentDraft,
} from "@/lib/paperagents";
import { SURVEYS_ADDRESS, type PaperView } from "@/lib/papers";
import type { PaperAgent, PaperAgentsList } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";
import { usePaperAgentsList } from "@/lib/use-paperagents";
import { cn } from "@/lib/utils";

const VIEWS: { view: PaperView; label: string; href: string }[] = [
  { view: "agents", label: "Agents", href: AGENTS_ADDRESS },
  { view: "surveys", label: "Surveys", href: SURVEYS_ADDRESS },
];

const INTRO =
  "A PaperAgent is one paper made usable: its text read, with each claim traced to the place it is made, a note of what its method was tested on, and tools built from the code that came with it. For now an agent keeps which paper it is of and where its code is. The steps that read the paper and build its tools are added one at a time.";

// The two parts of the page, each reached by an address of its own, as the pages of the rail are
export function PaperAgentsNav({ view }: { view: PaperView }) {
  return (
    <nav aria-label="PaperAgents" className="flex gap-1 border-b border-border">
      {VIEWS.map((part) => {
        const current = part.view === view;

        return (
          <Link
            key={part.view}
            href={part.href}
            aria-current={current ? "page" : undefined}
            className={cn(
              "-mb-px rounded-t-sm border-b-2 px-3 py-2 text-sm outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50",
              current ? "border-foreground font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {part.label}
          </Link>
        );
      })}
    </nav>
  );
}

function AgentRow({ agent }: { agent: PaperAgent }) {
  return (
    <li className="flex flex-col gap-1.5 rounded-xl border border-border bg-card p-4 transition-colors hover:border-ring/50" data-testid="paper-agent">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="min-w-0 break-words text-sm font-medium">
          <Link href={agentAddress(agent.id)} className="rounded-sm outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
            {agent.title}
          </Link>
        </h3>
        {agent.given && <Badge variant="secondary">Given to conversations</Badge>}
      </div>
      <p className="break-all text-xs text-muted-foreground">{describePaper(agent.paper)}</p>
      {agent.repo !== null && <p className="break-all text-xs text-muted-foreground">Code: {repoName(agent.repo.url)}</p>}
      <p className="text-xs text-muted-foreground">{describeSteps(agent)}</p>
    </li>
  );
}

// The agents there are, the latest first
function AgentList({ agents }: { agents: readonly PaperAgent[] }) {
  if (agents.length === 0) {
    return (
      <div className="flex flex-col gap-1 rounded-xl border border-dashed border-border p-5" data-testid="paper-agents-empty">
        <p className="text-sm font-medium">There are no PaperAgents yet</p>
        <p className="text-sm text-muted-foreground">
          Make one below. To read many papers at once, for what they share, see{" "}
          <Link href={SURVEYS_ADDRESS} className="rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
            Surveys
          </Link>
          .
        </p>
      </div>
    );
  }

  return (
    <ul aria-label="PaperAgents" className="flex flex-col gap-2">
      {agents.map((agent) => (
        <AgentRow key={agent.id} agent={agent} />
      ))}
    </ul>
  );
}

// Makes an agent of a paper, which has nothing done to it yet. A paper that is a file is uploaded from the agent's own page.
function NewAgent({ list }: { list: PaperAgentsList }) {
  const { report } = useServer();
  const router = useRouter();
  const id = useId();
  const [draft, setDraft] = useState<AgentDraft>(EMPTY_AGENT);
  const [tried, setTried] = useState(false);
  const [existing, setExisting] = useState<string | null>(null);
  const attempt = useAttempt(report);
  const checked = checkAgent(draft, list.repo_hosts);
  const problems = tried ? checked.problems : {};
  const field = (name: string) => `${id}-${name}`;

  function change(part: Partial<AgentDraft>) {
    setDraft((was) => ({ ...was, ...part }));
  }

  async function make() {
    setTried(true);
    setExisting(null);
    const body = checked.value;
    if (body === null) return;
    const agent = await attempt.run(async () => {
      try {
        return await api.makePaperAgent(body);
      } catch (error) {
        setExisting(existingOf(error));
        throw error;
      }
    });
    if (agent) router.push(agentAddress(agent.id));
  }

  return (
    <form
      aria-label="Make an agent"
      onSubmit={(event) => {
        event.preventDefault();
        void make();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <fieldset className="flex flex-wrap gap-x-5 gap-y-2" disabled={attempt.busy}>
        <legend className="mb-1.5 text-sm font-medium">Which paper</legend>
        {PAPER_KINDS.map((kind) => (
          <label key={kind} className="flex items-center gap-2 text-sm">
            <Radio name={field("kind")} checked={draft.kind === kind} onChange={() => change({ kind })} />
            {PAPER_KIND_LABELS[kind]}
          </label>
        ))}
      </fieldset>

      {draft.kind === "doi" && (
        <Field id={field("doi")} label="DOI" hint="Such as 10.1038/s41586-020-2649-2. A link to a DOI works too." problem={problems.doi}>
          <Input
            id={field("doi")}
            value={draft.doi}
            onChange={(event) => change({ doi: event.target.value })}
            autoComplete="off"
            spellCheck={false}
            readOnly={attempt.busy}
            aria-invalid={problems.doi !== undefined}
            aria-describedby={describedBy(field("doi"), { hint: true, problem: problems.doi !== undefined })}
          />
        </Field>
      )}

      {draft.kind === "url" && (
        <Field id={field("url")} label="Link to the paper" hint="Where it can be read on the web." problem={problems.url}>
          <Input
            id={field("url")}
            value={draft.url}
            onChange={(event) => change({ url: event.target.value })}
            placeholder="https://"
            autoComplete="off"
            spellCheck={false}
            readOnly={attempt.busy}
            aria-invalid={problems.url !== undefined}
            aria-describedby={describedBy(field("url"), { hint: true, problem: problems.url !== undefined })}
          />
        </Field>
      )}

      {draft.kind === "file" && (
        <p className="text-xs text-muted-foreground">
          You upload it to the agent once it is made. {list.suffixes.join(", ")} files are read, of up to {formatBytes(list.max_paper_bytes)}.
        </p>
      )}

      <Field
        id={field("title")}
        label="Title"
        hint={draft.kind === "file" ? "What the agent is called." : "What the agent is called. If it is left blank, the DOI or the link is used."}
        problem={problems.title}
      >
        <Input
          id={field("title")}
          value={draft.title}
          onChange={(event) => change({ title: event.target.value })}
          maxLength={MAX_AGENT_TITLE * 4}
          autoComplete="off"
          readOnly={attempt.busy}
          aria-invalid={problems.title !== undefined}
          aria-describedby={describedBy(field("title"), { hint: true, problem: problems.title !== undefined })}
        />
      </Field>

      <Field
        id={field("repo")}
        label="Where its code is"
        hint={`Optional. The address of the project, such as https://github.com/owner/name, at ${list.repo_hosts.join(", ")}.`}
        problem={problems.repo}
      >
        <Input
          id={field("repo")}
          value={draft.repo}
          onChange={(event) => change({ repo: event.target.value })}
          placeholder="https://github.com/owner/name"
          autoComplete="off"
          spellCheck={false}
          readOnly={attempt.busy}
          aria-invalid={problems.repo !== undefined}
          aria-describedby={describedBy(field("repo"), { hint: true, problem: problems.repo !== undefined })}
        />
      </Field>

      {attempt.problem && (
        <div className="flex flex-col gap-1.5">
          <ProblemNotice problem={attempt.problem} />
          {existing !== null && (
            <Link
              href={agentAddress(existing)}
              className="w-fit rounded-sm text-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              Open that PaperAgent
            </Link>
          )}
        </div>
      )}
      <div>
        <Button type="submit" disabled={attempt.busy}>
          <Plus />
          {attempt.busy ? "Making…" : "Make the agent"}
        </Button>
      </div>
    </form>
  );
}

// The PaperAgents there are, and the making of one
export function Agents() {
  const { report } = useServer();
  const list = usePaperAgentsList(report, "");

  return (
    <>
      <PageSection title="Agents" intro={INTRO}>
        <Looked state={list.value} label="Looking at the agents" failure="The agents could not be looked at." onRetry={list.reload}>
          {(value) => <AgentList agents={value.agents} />}
        </Looked>
      </PageSection>
      <PageSection title="Make an agent">
        <Looked state={list.value} label="Looking at what an agent takes" failure="What an agent takes could not be looked at." onRetry={list.reload}>
          {(value) => <NewAgent list={value} />}
        </Looked>
      </PageSection>
    </>
  );
}
