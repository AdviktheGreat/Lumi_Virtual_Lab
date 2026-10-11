"use client";

import { useState } from "react";
import { ChevronRight, Library, Loader2, MessageSquareText, Search, StickyNote, Terminal, Users, Wrench } from "lucide-react";
import { CodeBlock } from "@/components/code";
import { CodeCell, PendingCell } from "@/components/code-cell";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { describeResources, parseArguments, summarize } from "@/lib/calls";
import { stripAnsi } from "@/lib/format";
import type { Call, Resources, Step } from "@/lib/transcript";

// Names listed in a card before the rest are counted
const NAMES_SHOWN = 40;

const ICONS = { run_code: Terminal, find_resources: Search, convene_team: Users, consult: MessageSquareText } as const;

function Header({
  icon: Icon,
  title,
  detail,
  trailing,
}: {
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  title: string;
  detail?: string | null;
  trailing?: React.ReactNode;
}) {
  return (
    <>
      <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        <Icon className="size-3.5" aria-hidden />
      </span>
      <span className="shrink-0 text-sm font-medium">{title}</span>
      {detail && <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{detail}</span>}
      {!detail && <span className="flex-1" />}
      {trailing}
    </>
  );
}

function Running() {
  return (
    <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground" role="status">
      <Loader2 className="size-3.5 animate-spin" aria-hidden />
      Working
    </span>
  );
}

function CutShort() {
  return <span className="shrink-0 text-xs text-muted-foreground">Cut short</span>;
}

function Trailing({ call }: { call: Call }) {
  if (call.status === "running") return <Running />;
  if (call.status === "interrupted") return <CutShort />;

  return null;
}

const CARD = "rounded-xl border border-border bg-card";

// What a call that ran code is: the code, and each time it ran
function CodeCall({ call }: { call: Call }) {
  const summary = summarize(call);
  const running = call.status === "running";

  return (
    <div className={CARD} data-testid="call" data-call={call.name} data-status={call.status}>
      <div className="flex items-center gap-2.5 px-3 py-2">
        <Header icon={Terminal} title={summary.title} trailing={<Trailing call={call} />} />
      </div>
      <div className="flex flex-col gap-3 border-t border-border/70 p-3">
        {call.cells.map((cell, at) => (
          <CodeCell key={at} cell={cell} />
        ))}
        {call.cells.length === 0 && summary.code !== null && (
          <PendingCell code={summary.code.text} language={summary.code.language} running={running} />
        )}
        {call.cells.length === 0 && !running && call.output !== null && call.output !== "" && (
          <pre className="max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-muted/50 px-3 py-2 text-[13px] leading-5">
            {stripAnsi(call.output)}
          </pre>
        )}
      </div>
    </div>
  );
}

// Any other tool: what it was asked and what it gave back, which are there to be opened
function ToolCall({ call }: { call: Call }) {
  const summary = summarize(call);
  const args = parseArguments(call.arguments);
  const Icon = ICONS[call.name as keyof typeof ICONS] ?? Wrench;
  const asked = args !== null && Object.keys(args).length > 0 ? JSON.stringify(args, null, 2) : null;
  // What the team or a search tells is written to be read, which a tool's own output may not be
  const written = call.name === "convene_team" || call.name === "consult" || call.name === "find_resources";

  return (
    <details className={`group ${CARD}`} data-testid="call" data-call={call.name} data-status={call.status}>
      <summary className="flex cursor-pointer list-none items-center gap-2.5 rounded-xl px-3 py-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" aria-hidden />
        <Header icon={Icon} title={summary.title} detail={summary.detail} trailing={<Trailing call={call} />} />
      </summary>
      <div className="flex flex-col gap-3 border-t border-border/70 p-3">
        {asked !== null && (
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">Asked</span>
            <CodeBlock code={asked} language="json" foldAfter={12} />
          </div>
        )}
        {asked === null && call.arguments.trim() !== "" && call.arguments.trim() !== "{}" && (
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">Asked</span>
            <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-muted/50 px-3 py-2 font-mono text-[13px]">
              {call.arguments}
            </pre>
          </div>
        )}
        {call.output !== null && (
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">Result</span>
            <div className="max-h-96 overflow-auto rounded-lg border border-border bg-background px-3 py-2">
              {written ? (
                <Markdown text={call.output} className="text-sm leading-6" />
              ) : (
                <pre className="whitespace-pre-wrap break-words font-mono text-[13px] leading-5">{stripAnsi(call.output)}</pre>
              )}
            </div>
          </div>
        )}
        {call.output === null && call.status === "running" && (
          <span className="text-xs text-muted-foreground">Nothing has come back yet.</span>
        )}
      </div>
    </details>
  );
}

function ResourcesCard({ resources }: { resources: Resources }) {
  const summary = describeResources(resources);
  const [all, setAll] = useState<Record<string, boolean>>({});

  return (
    <details className={`group ${CARD}`} data-testid="resources">
      <summary className="flex cursor-pointer list-none items-center gap-2.5 rounded-xl px-3 py-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" aria-hidden />
        <Header icon={Library} title={summary.title} detail={summary.detail} />
      </summary>
      <div className="flex flex-col gap-3 border-t border-border/70 p-3">
        {summary.groups.length === 0 && <span className="text-xs text-muted-foreground">Nothing is named.</span>}
        {summary.groups.map((group) => {
          const names = all[group.label] ? group.names : group.names.slice(0, NAMES_SHOWN);

          return (
            <div key={group.label} className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">{group.label}</span>
              <ul className="flex flex-wrap gap-1.5">
                {names.map((name) => (
                  <li key={name} className="rounded-md border border-border bg-muted/50 px-1.5 py-0.5 font-mono text-xs">
                    {name}
                  </li>
                ))}
                {group.names.length > names.length && (
                  <li>
                    <Button type="button" variant="ghost" size="xs" onClick={() => setAll((was) => ({ ...was, [group.label]: true }))}>
                      {group.names.length - names.length} more
                    </Button>
                  </li>
                )}
              </ul>
            </div>
          );
        })}
      </div>
    </details>
  );
}

const READ_BY = { lead: "Read by the lead", lab: "Read by the team" } as const;

function NoteChip({ text, to, read }: { text: string; to: "lead" | "lab" | null; read: boolean }) {
  return (
    <div className="flex flex-col items-end gap-1" data-testid="note">
      <p className="flex max-w-[85%] items-start gap-2 whitespace-pre-wrap break-words rounded-xl border border-dashed border-border px-3 py-2 text-sm">
        <StickyNote className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        {text}
      </p>
      <span className="text-xs text-muted-foreground">{read && to !== null ? READ_BY[to] : "Not read: it came too late"}</span>
    </div>
  );
}

// What the lead did before it answered, in the order it did it
export function Steps({ steps }: { steps: Step[] }) {
  if (steps.length === 0) return null;

  return (
    <div className="flex flex-col gap-3" data-testid="steps">
      {steps.map((step) => {
        switch (step.kind) {
          case "say":
            return <Markdown key={step.key} text={step.text} className="text-muted-foreground" />;
          case "call":
            return step.call.name === "run_code" ? <CodeCall key={step.key} call={step.call} /> : <ToolCall key={step.key} call={step.call} />;
          case "resources":
            return <ResourcesCard key={step.key} resources={step.resources} />;
          case "note":
            return <NoteChip key={step.key} text={step.text} to={step.to} read={step.read} />;
        }
      })}
    </div>
  );
}
