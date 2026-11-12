import { count } from "@/lib/checks";
import type { GivenTool, PaperAgent, PaperAgentGiven } from "@/lib/types";

// What each tier is, in a few words
const TIER_TITLES: Record<string, string> = {
  A: "Runs the authors' code",
  D: "Reads the paper",
};

export function describeTier(tier: string | null): string {
  if (tier === null) return "Nothing to give yet";

  return `Tier ${tier}: ${TIER_TITLES[tier]?.toLowerCase() ?? "not known to this page"}`;
}

// What a tool does, in words
export function describeKind(kind: GivenTool["kind"]): string {
  return kind === "run" ? "Runs the authors' own function" : "Reads what was found in the paper";
}

// How many tools of each kind, in a line
export function describeTools(tools: readonly GivenTool[]): string {
  const reading = tools.filter((tool) => tool.kind === "reading").length;
  const running = tools.length - reading;
  if (tools.length === 0) return "No tool is given.";
  const parts = [`${count(reading, "tool")} that read${reading === 1 ? "s" : ""} the paper`];
  if (running > 0) parts.push(`${running} that run${running === 1 ? "s" : ""} its code`);

  return `${parts.join(" and ")}.`;
}

// What a call of a tool that runs is allowed, in words
export function describeLimits(limits: PaperAgentGiven["limits"]): string {
  const minutes = Math.round(limits.call_seconds / 60);

  return `A call may take up to ${count(minutes, "minute")}, in a container with no network, ${limits.memory} of memory, and ${count(Number(limits.cpus), "processor")}.`;
}

// Why there is no tool of a kind, which what is said of the agent shows, for what a person may do about it. The server says
// why tools that run cannot be called when it is Docker or the image, and it is said as it says it.
export function whyNone(agent: PaperAgent, given: PaperAgentGiven): string[] {
  const reasons: string[] = [];
  const reads = given.tools.some((tool) => tool.kind === "reading");
  const runs = given.tools.some((tool) => tool.kind === "run");
  if (!reads) {
    reasons.push(
      agent.steps.reading === "running"
        ? "The paper is being read. The tools that read it are given once its text is kept."
        : "The paper has not been read, so the tools that read it are not given. Read it under Reading.",
    );
  }
  if (!runs && given.problem === null) {
    reasons.push(
      agent.repo === null
        ? "It has no code, so it has no tool that runs."
        : "It has no tool that runs. Tools that run are made of what the tutorials did, under Tools.",
    );
  }

  return reasons;
}

// What giving an agent comes to for a conversation, in a line
export function describeGiving(given: boolean): string {
  return given ? "Given to the conversations that you start from now on." : "Not given to conversations.";
}
