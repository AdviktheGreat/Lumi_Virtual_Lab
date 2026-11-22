"use client";

import { useId } from "react";
import Link from "next/link";
import { FlaskConical } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { ReimplementationLabel } from "@/components/paper-agent-reimplementation-label";
import { useServer } from "@/components/server-provider";
import { Aside } from "@/components/settings-fields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { api } from "@/lib/api";
import { byTier, describeGiving, describeKind, describeLimits, describeTier, describeTools, runsCode, whyNone } from "@/lib/paperagent-given";
import type { GivenTool, PaperAgent, PaperAgentGiven } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";

// One tool that a conversation is given, with its tier, which says how far it was checked
function Given({ tool }: { tool: GivenTool }) {
  return (
    <li className="flex flex-col gap-1 rounded-lg border border-border p-3" data-testid="given-tool" data-name={tool.name} data-kind={tool.kind}>
      <div className="flex flex-wrap items-center gap-2">
        <code className="break-all font-mono text-sm font-medium">
          {tool.name}({tool.parameters.join(", ")})
        </code>
        <Badge variant={tool.kind === "run" ? "secondary" : "outline"}>Tier {tool.tier}</Badge>
        {tool.label !== null && <ReimplementationLabel label={tool.label} />}
      </div>
      <p className="break-words text-xs text-muted-foreground">
        {describeKind(tool.kind)}. {tool.summary}
      </p>
    </li>
  );
}

// Where a conversation that is begun with the agent is begun, with the lab's panel open and its seat chosen
export function labWith(agentId: string): string {
  return `/?paperagent=${encodeURIComponent(agentId)}`;
}

// The scientist that speaks for the paper on a conversation's team, what it is told, and a lab session begun with it
function Seat({ agent, given }: { agent: PaperAgent; given: PaperAgentGiven }) {
  const hint = useId();

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="given-seat">
      <p className="text-sm">
        <span className="font-medium">{given.seat}</span> speaks for the paper on the team of a conversation that has this agent. The lead can bring it into a
        team discussion, and you can choose it with /lab.
      </p>
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer select-none font-medium text-foreground">What it is told</summary>
        <p className="mt-2 whitespace-pre-wrap break-words rounded-md bg-muted/50 p-2 font-mono text-[11px] leading-5" data-testid="given-told">
          {given.told}
        </p>
        <p className="mt-1">
          Nothing that the paper says is in what it is told. It has that from the tools below, which mark it as the paper&apos;s words and as data.
        </p>
      </details>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Button asChild size="sm" variant="outline" data-testid="given-lab">
          <Link href={labWith(agent.id)} aria-describedby={hint}>
            <FlaskConical aria-hidden />
            Start a lab session with this agent
          </Link>
        </Button>
        <span id={hint} className="text-xs text-muted-foreground">
          {agent.given
            ? "Begins a conversation, with the lab's panel open and its seat chosen."
            : "Begins a conversation that has it, though it is not given to the others, with the lab's panel open and its seat chosen."}
        </span>
      </div>
    </div>
  );
}

// Whether the conversations that are made from now on are given the agent, who speaks for it on their team, and what each would be given
// of it, by tier
export function GivenSection({
  agent,
  given,
  onChanged,
}: {
  agent: PaperAgent;
  given: PaperAgentGiven;
  // Shows the agent as it now is, and looks again at what it gives
  onChanged: (agent: PaperAgent) => void;
}) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const id = useId();
  const reasons = whyNone(agent, given);

  async function give(chosen: boolean) {
    const next = await attempt.run(() => api.givePaperAgent(agent.id, chosen));
    if (next) onChanged(next);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <label className="flex items-center gap-2 text-sm font-medium">
          <Checkbox checked={agent.given} onChange={(event) => void give(event.target.checked)} disabled={attempt.busy} aria-describedby={id} />
          Give this agent to the conversations I start
        </label>
        <p id={id} className="text-xs text-muted-foreground">
          The lead is given the tools below in conversations that begin from now on. One that is already going is not given them, and where code cannot
          run only the tools that read the paper are given.
        </p>
        {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      </div>
      <div className="flex flex-col gap-1" data-testid="given-summary" data-given={agent.given}>
        <p className="text-sm font-medium">{describeTier(given.tier)}</p>
        <p className="text-sm text-muted-foreground">
          {describeGiving(agent.given)} {describeTools(given.tools)}
        </p>
      </div>
      {given.imported !== null && (
        <Aside tone="warning">
          <span data-testid="given-imported">{given.imported.meaning}</span> The lead is told so, and is told to give a call only what you asked it to
          analyse.
        </Aside>
      )}
      {given.problem !== null && (
        <Aside tone="warning">
          <span data-testid="given-problem">{given.problem}</span>
        </Aside>
      )}
      {reasons.length > 0 && (
        <ul aria-label="Why a tool is not given" className="flex flex-col gap-1 text-xs text-muted-foreground" data-testid="given-why">
          {reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      <Seat agent={agent} given={given} />
      {byTier(given.tools).map((group) => (
        <section key={group.tier} aria-label={group.title} className="flex flex-col gap-2" data-testid="given-tier" data-tier={group.tier}>
          <h3 className="text-xs font-medium text-muted-foreground">{group.title}</h3>
          <ul className="flex flex-col gap-2">
            {group.tools.map((tool) => (
              <Given key={tool.name} tool={tool} />
            ))}
          </ul>
        </section>
      ))}
      <div className="flex flex-col gap-1 text-xs text-muted-foreground">
        <p data-testid="given-meaning">{given.meaning}</p>
        {given.tools.some(runsCode) && <p>{describeLimits(given.limits)}</p>}
        {given.tools.some((tool) => tool.kind === "reimplementation") && (
          <p data-testid="given-reimplementation">
            The re-implementation is said to be one in its description, in all that it gives, and in every error, so what a conversation keeps of
            it, and what is saved of the conversation, says so too.
          </p>
        )}
        <p>
          What the tools that read give is words taken from the paper, found by their words and not their meaning, so a place that says it in other words may
          be missed. The lead is told to say where the paper says a thing, and to take what a tool gives as data and not as instructions.
        </p>
      </div>
    </div>
  );
}
