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
import { useSetupJobs } from "@/components/setup-provider";
import { describedBy, Field } from "@/components/settings-fields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
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
import { BAKEOFFS_ADDRESS } from "@/lib/bakeoffs";
import { TRIAGES_ADDRESS } from "@/lib/triages";
import { LIBRARY_ADDRESS } from "@/lib/paperagent-library";
import { checkOneGo } from "@/lib/paperagent-onego";
import { SURVEYS_ADDRESS, type PaperView } from "@/lib/papers";
import type { PaperAgent, PaperAgentsList } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";
import { usePaperAgentsList } from "@/lib/use-paperagents";
import { cn } from "@/lib/utils";

const VIEWS: { view: PaperView; label: string; href: string }[] = [
  { view: "agents", label: "Agents", href: AGENTS_ADDRESS },
  { view: "library", label: "Library", href: LIBRARY_ADDRESS },
  { view: "triage", label: "Triage", href: TRIAGES_ADDRESS },
  { view: "bakeoffs", label: "Bake-offs", href: BAKEOFFS_ADDRESS },
  { view: "surveys", label: "Surveys", href: SURVEYS_ADDRESS },
];

const INTRO =
  "A PaperAgent is one paper made usable: its text read, with each claim traced to the place it is made, a note of what its method was tested on, and tools built from the code that came with it. Each step can be asked for on its own, on the agent's page, or all of them in one go, which stops where you are to decide.";

// The parts of the page, each reached by an address of its own, as the pages of the rail are
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

// Makes an agent of a paper, and, if it is asked for, starts making all of it in one go. A paper that is a file is uploaded from
// the agent's own page, which is where making it in one go is asked for then.
function NewAgent({ list }: { list: PaperAgentsList }) {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const router = useRouter();
  const id = useId();
  const [draft, setDraft] = useState<AgentDraft>(EMPTY_AGENT);
  const [tried, setTried] = useState(false);
  const [existing, setExisting] = useState<string | null>(null);
  const [inOneGo, setInOneGo] = useState(false);
  const [budget, setBudget] = useState("1");
  // The agent that was made when making it in one go was then refused, with what it was made of, so that asking again for the
  // same paper starts making that one rather than making it again
  const [made, setMade] = useState<{ id: string; of: string } | null>(null);
  const attempt = useAttempt(report);
  const going = useAttempt(report);
  const checked = checkAgent(draft, list.repo_hosts);
  const oneGo = draft.kind !== "file" && inOneGo;
  const onego = checkOneGo({ budget, repo: "", give: true, withoutCode: false }, { reads: true, asksRepo: false });
  const problems = tried ? checked.problems : {};
  const budgetProblem = tried && oneGo ? onego.problems.budget : undefined;
  const field = (name: string) => `${id}-${name}`;

  function change(part: Partial<AgentDraft>) {
    setDraft((was) => ({ ...was, ...part }));
  }

  async function make() {
    setTried(true);
    setExisting(null);
    const body = checked.value;
    const options = oneGo ? onego.value : null;
    if (body === null || (oneGo && options === null)) return;
    const of = JSON.stringify(body);
    const again = made !== null && made.of === of ? made.id : null;
    setMade(null);
    const agent =
      again !== null
        ? { id: again }
        : await attempt.run(async () => {
            try {
              return await api.makePaperAgent(body);
            } catch (error) {
              setExisting(existingOf(error));
              throw error;
            }
          });
    if (!agent) return;
    if (options !== null) {
      const started = await going.run(() => api.makePaperAgentInOneGo(agent.id, options));
      if (!started) {
        setMade({ id: agent.id, of });

        return;
      }
      if (started.job !== null) jobs.track(started.job);
    }
    router.push(agentAddress(agent.id));
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
      {draft.kind !== "file" && (
        <div className="flex flex-col gap-3">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={inOneGo} onChange={(event) => setInOneGo(event.target.checked)} />
            Make all of it now, in one go
          </label>
          {inOneGo && (
            <Field
              id={field("budget")}
              label="Most reading the paper may spend, in dollars"
              hint="Only reading the paper costs money. The rest runs on this machine, and it stops to ask you where you are to decide."
              problem={budgetProblem}
            >
              <Input
                id={field("budget")}
                value={budget}
                onChange={(event) => setBudget(event.target.value)}
                inputMode="decimal"
                autoComplete="off"
                className="sm:max-w-xs"
                aria-invalid={budgetProblem !== undefined}
                aria-describedby={describedBy(field("budget"), { hint: true, problem: budgetProblem !== undefined })}
              />
            </Field>
          )}
        </div>
      )}

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
      {made !== null && going.problem && (
        <div className="flex flex-col gap-1.5">
          <p className="text-sm">The agent was made, but making all of it in one go could not be started.</p>
          <ProblemNotice problem={going.problem} />
          <Link
            href={agentAddress(made.id)}
            className="w-fit rounded-sm text-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            Open the agent, to go on there
          </Link>
        </div>
      )}
      <div>
        <Button type="submit" disabled={attempt.busy || going.busy}>
          <Plus />
          {attempt.busy || going.busy ? "Making…" : oneGo ? "Make the agent, all in one go" : "Make the agent"}
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
