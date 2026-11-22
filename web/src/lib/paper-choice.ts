import type { PaperAgent } from "./types";

// The agents a conversation that is begun here has: those chosen, or where none were, those that are given to conversations
// and the one that a link names. Of those, only the ones that are there, in the order of the list.
export function papersOf(agents: readonly PaperAgent[], chosen: readonly string[] | null, linked: string): PaperAgent[] {
  return agents.filter((agent) => (chosen === null ? agent.given || agent.id === linked : chosen.includes(agent.id)));
}

// Whether the conversation is to be told which agents it has, which it is unless it is to have those given to conversations
export function choosesPapers(agents: readonly PaperAgent[], chosen: readonly string[] | null, linked: string): boolean {
  return chosen !== null || agents.some((agent) => agent.id === linked && !agent.given);
}

// What the button that opens the choice says
export function papersButtonText(count: number): string {
  if (count === 0) return "No PaperAgents";

  return `${count} PaperAgent${count === 1 ? "" : "s"}`;
}
