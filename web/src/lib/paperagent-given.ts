import { count } from "@/lib/checks";
import type { GivenTool, PaperAgent, PaperAgentGiven } from "@/lib/types";

// What each tier is, in a few words
const TIER_TITLES: Record<string, string> = {
  A: "Runs the authors' code",
  B: "Runs the authors' code, and passed checks that its tutorial did not give it",
  C: "A re-implementation, not the authors' code, which gave a number that the paper reports",
  D: "Reads the paper",
  Imported: "Made by someone else, and not checked here",
};

export function describeTier(tier: string | null): string {
  if (tier === null) return "Nothing to give yet";

  return `Tier ${tier}: ${TIER_TITLES[tier]?.toLowerCase() ?? "not known to this page"}`;
}

// What a tool does, in words
export function describeKind(kind: GivenTool["kind"]): string {
  if (kind === "imported") return "Calls the server that someone else runs, and asks you first";
  if (kind === "reimplementation") return "Runs a function that a model wrote from the paper's words, in a sandbox with no network";

  return kind === "run" ? "Runs the authors' own function" : "Reads what was found in the paper";
}

// Whether a tool runs code when it is called, which is what the limits of a call are of
export function runsCode(tool: Pick<GivenTool, "kind">): boolean {
  return tool.kind === "run" || tool.kind === "reimplementation";
}

// How many tools of each kind, in a line
export function describeTools(tools: readonly GivenTool[]): string {
  const reading = tools.filter((tool) => tool.kind === "reading").length;
  const imported = tools.filter((tool) => tool.kind === "imported").length;
  const reimplemented = tools.filter((tool) => tool.kind === "reimplementation").length;
  const running = tools.length - reading - imported - reimplemented;
  if (tools.length === 0) return "No tool is given.";
  const kinds: [number, string][] = [];
  // The tools that read are always counted for an agent that was made here, even when there are none, as they are the first thing
  // said of it
  if (reading > 0 || imported === 0) kinds.push([reading, "read{s} the paper"]);
  if (running > 0) kinds.push([running, "run{s} its code"]);
  if (reimplemented > 0) kinds.push([reimplemented, "run{s} a re-implementation of it, not the authors' code"]);
  if (imported > 0) kinds.push([imported, "call{s} the server it was imported from"]);
  const parts = kinds.map(([number, what], position) => {
    const phrase = what.replace("{s}", number === 1 ? "s" : "");

    return position === 0 ? `${count(number, "tool")} that ${phrase}` : `${number} that ${phrase}`;
  });

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
  const runs = given.tools.some(runsCode);
  if (!reads) {
    reasons.push(
      agent.steps.reading === "running"
        ? "The paper is being read. The tools that read it are given once its text is kept."
        : "The paper has not been read, so the tools that read it are not given. Read it under Reading.",
    );
  }
  if (!runs && given.problem === null) {
    reasons.push(
      agent.repo !== null
        ? "It has no tool that runs. Tools that run are made of what the tutorials did, under Tools."
        : agent.imported === null
          ? "It has no code, so it has no tool that runs the authors' code. A function can be written from the paper's words under Re-implementation, and is given once it matches a number that the paper reports."
          : "It has no code, so it has no tool that runs.",
    );
  }

  return reasons;
}

// What giving an agent comes to for a conversation, in a line
export function describeGiving(given: boolean): string {
  return given ? "Given to the conversations that you start from now on." : "Not given to conversations.";
}
