"use client";

import { Badge } from "@/components/ui/badge";
import { timeAgo } from "@/lib/format";
import { MOST_HELD_SHOWN, describeHolds } from "@/lib/mcp";
import type { McpHolds, McpPrompt, McpResource } from "@/lib/types";
import { cn } from "@/lib/utils";

function Resource({ resource }: { resource: McpResource }) {
  return (
    <>
      <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="font-medium text-foreground">{resource.title ?? resource.name}</span>
        {resource.template && <Badge variant="outline">Template</Badge>}
        <code className="break-all">{resource.uri}</code>
      </span>
      {resource.description !== "" && <span className="break-words">{resource.description}</span>}
    </>
  );
}

function Prompt({ prompt }: { prompt: McpPrompt }) {
  return (
    <>
      <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <code className="font-medium text-foreground">/{prompt.command}</code>
        {prompt.arguments.map((argument) => (
          <span key={argument.name} title={argument.description === "" ? undefined : argument.description}>
            <code>{argument.name}</code>
            {argument.required ? "" : " (optional)"}
          </span>
        ))}
      </span>
      {prompt.description !== "" && <span className="break-words">{prompt.description}</span>}
    </>
  );
}

// A list of what a server holds, as far as it is shown in full
function Listed<T>({ title, testId, items, show }: { title: string; testId: string; items: T[]; show: (item: T) => React.ReactNode }) {
  if (items.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5">
      <h4 className="font-medium text-foreground">{title}</h4>
      <ul className="flex flex-col gap-2">
        {items.slice(0, MOST_HELD_SHOWN).map((item, at) => (
          <li key={at} className="flex flex-col gap-0.5" data-testid={testId}>
            {show(item)}
          </li>
        ))}
      </ul>
      {items.length > MOST_HELD_SHOWN && <p>and {items.length - MOST_HELD_SHOWN} more</p>}
    </div>
  );
}

// What a server lists besides its tools: its resources, which the lead can read, and its prompts, which can be written after
// a slash. It is a line, which opens to the lists, and says when the server was last connected to.
export function Holds({ name, holds, className }: { name: string; holds: McpHolds | null; className?: string }) {
  if (holds === null) return null;
  const summary = describeHolds(holds);
  const seen = holds.seen ? `Seen ${timeAgo(holds.seen)}.` : "Seen just now.";
  if (summary === null && holds.problems.length === 0) {
    return (
      <p className={cn("text-xs text-muted-foreground", className)} data-testid={`mcp-${name}-holds`}>
        It lists no resources or prompts. {seen}
      </p>
    );
  }

  return (
    <details className={cn("text-xs text-muted-foreground", className)} data-testid={`mcp-${name}-holds`}>
      <summary className="cursor-pointer rounded outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
        {summary === null ? "What it lists besides its tools" : `It also lists ${summary}`}
      </summary>
      <div className="mt-2 flex flex-col gap-3">
        <Listed title="Resources, which the lead can read" testId="mcp-resource" items={holds.resources} show={(resource) => <Resource resource={resource} />} />
        <Listed title="Prompts, which are written after a slash" testId="mcp-prompt" items={holds.prompts} show={(prompt) => <Prompt prompt={prompt} />} />
        {holds.problems.length > 0 && (
          <div className="flex flex-col gap-1">
            <h4 className="font-medium text-foreground">What it did not list</h4>
            <ul className="flex flex-col gap-1">
              {holds.problems.map((problem, at) => (
                <li key={at} className="break-words">
                  {problem}
                </li>
              ))}
            </ul>
          </div>
        )}
        {holds.more && <p>It has more than are listed here.</p>}
        <p>{seen}</p>
      </div>
    </details>
  );
}
