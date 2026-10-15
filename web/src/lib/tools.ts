import type { ToolInfo } from "./types";

export interface ToolGroup {
  name: string;
  tools: ToolInfo[];
}

// The tools by what they are for, in the order the server listed them, which keeps the tools of a group together
export function groupTools(tools: ToolInfo[]): ToolGroup[] {
  const groups: ToolGroup[] = [];
  for (const tool of tools) {
    const group = groups.find((candidate) => candidate.name === tool.group);
    if (group === undefined) groups.push({ name: tool.group, tools: [tool] });
    else group.tools.push(tool);
  }

  return groups;
}

// The names of those that are off once each of the names given is turned on or off, with the rest as they were. The
// server is told which are off and not which are on, so that a tool it gains later is on.
export function disabledWhen(tools: ToolInfo[], names: string[], enabled: boolean): string[] {
  const chosen = new Set(names);

  return tools.filter((tool) => (chosen.has(tool.name) ? !enabled : !tool.enabled)).map((tool) => tool.name);
}

// How many are turned on, as a person reads it
export function howManyOn(tools: ToolInfo[]): string {
  const on = tools.filter((tool) => tool.enabled).length;
  if (on === 0) return "None are on";
  if (on === tools.length) return `All ${tools.length} are on`;

  return `${on} of ${tools.length} are on`;
}
