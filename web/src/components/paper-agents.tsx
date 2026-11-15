"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Looked } from "@/components/looked";
import { ProblemNotice } from "@/components/messages";
import { AgentFields } from "@/components/paper-agent-fields";
import { ImportAgents } from "@/components/paper-agents-import";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import {
  agentAddress,
  AGENTS_ADDRESS,
  checkAgent,
  describePaper,
  describeSteps,
  EMPTY_AGENT,
  existingOf,
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
        {agent.imported !== null && <Badge variant="outline">Imported, not checked here</Badge>}
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
      <AgentFields draft={draft} change={change} problems={problems} busy={attempt.busy} list={list} field={field} />

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
      <PageSection
        title="Import an agent"
        intro="An agent that someone else made of a paper, which runs on a server of theirs, is brought in, to be used as one is. Nothing of the lab's is done to it, so it is shown as imported and not checked, and every call it is given waits for you."
      >
        <Looked state={list.value} label="Looking at what can be imported" failure="What can be imported could not be looked at." onRetry={list.reload}>
          {(value) => <ImportAgents list={value} />}
        </Looked>
      </PageSection>
    </>
  );
}
