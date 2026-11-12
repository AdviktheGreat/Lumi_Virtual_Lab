"use client";

import { useId } from "react";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { Aside } from "@/components/settings-fields";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { api } from "@/lib/api";
import { describeGiving, describeKind, describeLimits, describeTier, describeTools, whyNone } from "@/lib/paperagent-given";
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
      </div>
      <p className="break-words text-xs text-muted-foreground">
        {describeKind(tool.kind)}. {tool.summary}
      </p>
    </li>
  );
}

// Whether the conversations that are made from now on are given the agent, and what each would be given of it
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
      {given.tools.length > 0 && (
        <ul aria-label="Tools a conversation is given" className="flex flex-col gap-2">
          {given.tools.map((tool) => (
            <Given key={tool.name} tool={tool} />
          ))}
        </ul>
      )}
      <div className="flex flex-col gap-1 text-xs text-muted-foreground">
        <p data-testid="given-meaning">{given.meaning}</p>
        {given.tools.some((tool) => tool.kind === "run") && <p>{describeLimits(given.limits)}</p>}
        <p>
          What the tools that read give is words taken from the paper, found by their words and not their meaning, so a place that says it in other words may
          be missed. The lead is told to say where the paper says a thing, and to take what a tool gives as data and not as instructions.
        </p>
      </div>
    </div>
  );
}
