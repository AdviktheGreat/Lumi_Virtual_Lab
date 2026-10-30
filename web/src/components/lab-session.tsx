"use client";

import { Loader2 } from "lucide-react";
import { Avatar } from "@/components/avatar";
import { CallIcon } from "@/components/call-icon";
import { CodeCell, PendingCell } from "@/components/code-cell";
import { Markdown } from "@/components/markdown";
import { summarize } from "@/lib/calls";
import { stripAnsi } from "@/lib/format";
import {
  inRounds,
  listedCalls,
  roundName,
  type LabCall,
  type LabSession,
  type LabStep,
  type LabTurn,
} from "@/lib/lab";
import { ScrollBox } from "@/components/scroll-box";

const KINDS: Record<string, string> = {
  team: "Team discussion",
  individual: "One scientist, reviewed by the critic",
};

function Waiting({ children }: { children: React.ReactNode }) {
  return (
    <div className="animate-pulse text-xs text-muted-foreground" role="status">
      {children}
    </div>
  );
}

// Who and what the session is, before what was said in it
function About({ lab }: { lab: LabSession }) {
  const kind = (lab.type !== null && KINDS[lab.type]) || "Team session";
  const rounds = lab.rounds === null ? null : `${lab.rounds} ${lab.rounds === 1 ? "round" : "rounds"}`;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">{kind}</span>
        {rounds !== null && <span>{rounds}</span>}
      </div>
      {lab.team.length > 0 && (
        <ul aria-label="Team" className="flex flex-wrap gap-1.5">
          {lab.team.map((name) => (
            <li key={name} className="flex items-center gap-1.5 rounded-full border border-border bg-muted/40 py-0.5 pl-0.5 pr-2.5 text-xs">
              <Avatar name={name} className="size-5 text-[9px]" />
              {name}
            </li>
          ))}
        </ul>
      )}
      {(lab.agenda !== "" || lab.questions.length > 0) && (
        <details className="group text-sm" data-testid="lab-agenda">
          <summary className="w-fit cursor-pointer rounded text-xs font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
            Agenda
          </summary>
          <div className="mt-2 flex flex-col gap-2 rounded-lg border border-border bg-background px-3 py-2">
            {lab.agenda !== "" && <Markdown text={lab.agenda} className="text-sm leading-6" />}
            {lab.questions.length > 0 && (
              <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm marker:text-muted-foreground">
                {lab.questions.map((question, at) => (
                  <li key={at}>{question}</li>
                ))}
              </ol>
            )}
          </div>
        </details>
      )}
    </div>
  );
}

function ToolRow({ call, waiting }: { call: LabCall; waiting: boolean }) {
  const summary = summarize({ name: call.name, arguments: call.arguments, status: waiting ? "running" : "done" });

  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1.5 text-sm" data-testid="lab-tool" data-call={call.name}>
      <CallIcon name={call.name} className="size-3.5 shrink-0 text-muted-foreground" />
      <span className="shrink-0 font-medium">{summary.title}</span>
      {summary.detail && <span className="min-w-0 flex-1 truncate text-muted-foreground">{summary.detail}</span>}
      {!summary.detail && <span className="flex-1" />}
      {waiting && <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" aria-label="Working" />}
    </div>
  );
}

function Said({ text }: { text: string }) {
  return text.trim() === "" ? null : <Markdown text={text} className="text-sm leading-6 text-muted-foreground" />;
}

function StepView({ turn, at, waiting }: { turn: LabTurn; at: number; waiting: boolean }) {
  const step: LabStep = turn.steps[at];

  switch (step.kind) {
    case "reply":
      return step.text.trim() === "" ? null : (
        <div data-testid="lab-reply">
          <Markdown text={step.text} className="text-sm leading-6" />
        </div>
      );
    case "tools": {
      const calls = listedCalls(turn, at);
      const output = step.output?.trim() ? stripAnsi(step.output) : null;
      if (calls.length === 0 && step.said.trim() === "" && output === null) return null;

      return (
        <div className="flex flex-col gap-2">
          <Said text={step.said} />
          {calls.map((call) => (
            <ToolRow key={call.id} call={call} waiting={waiting && step.output === null} />
          ))}
          {output !== null && (
            <details className="text-xs">
              <summary className="w-fit cursor-pointer rounded text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
                What it gave back
              </summary>
              <ScrollBox
                as="pre"
                className="mt-1.5 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-muted/50 px-3 py-2 font-mono text-[13px] leading-5"
              >
                {output}
              </ScrollBox>
            </details>
          )}
        </div>
      );
    }
    case "code":
      return (
        <div className="flex flex-col gap-2">
          <Said text={step.said} />
          {step.cell === null ? (
            <PendingCell code={step.code} language={step.language} running={waiting} />
          ) : (
            <CodeCell cell={step.cell} />
          )}
        </div>
      );
    case "cell":
      return <CodeCell cell={step.cell} />;
  }
}

// What one scientist says and does, by their name
function Speaking({ speaker, children }: { speaker: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2" data-testid="lab-turn" data-speaker={speaker}>
      <div className="flex items-center gap-2">
        <Avatar name={speaker} />
        <span className="text-sm font-medium">{speaker}</span>
      </div>
      <div className="ml-3 flex flex-col gap-3 border-l border-border pl-5">{children}</div>
    </div>
  );
}

function Writing({ text }: { text: string }) {
  return (
    <div data-testid="lab-writing">
      <Markdown text={text} className="text-sm leading-6" />
      <span aria-hidden className="mt-2 inline-block size-2 animate-pulse rounded-full bg-brand" />
    </div>
  );
}

function TurnView({ turn, live, writing }: { turn: LabTurn; live: boolean; writing: string | null }) {
  const last = turn.steps.at(-1);
  // What it is waiting for is shown where it is waited for, which is the tool that has not given back, or the code that
  // has not run
  const busy = last !== undefined && ((last.kind === "tools" && last.output === null) || (last.kind === "code" && last.cell === null));

  return (
    <Speaking speaker={turn.speaker || "A scientist"}>
      {turn.steps.map((step, at) => (
        <StepView key={step.key} turn={turn} at={at} waiting={live && at === turn.steps.length - 1 && writing === null} />
      ))}
      {writing !== null && <Writing text={writing} />}
      {live && writing === null && !busy && <Waiting>Thinking…</Waiting>}
    </Speaking>
  );
}

function RoundHeading({ name }: { name: string }) {
  return (
    <div className="flex items-center gap-3 font-mono text-xs text-muted-foreground">
      <span>{name}</span>
      <span className="h-px flex-1 bg-border" aria-hidden />
    </div>
  );
}

// What the team did for the lead, as they did it: who spoke in each round, what they said, the tools they used, and the
// code they ran
export function LabSessionView({ lab }: { lab: LabSession }) {
  const last = lab.turns.at(-1);
  const writing = lab.writing;
  const live = lab.status === "running";
  // What is being written is part of the turn it is written in, if it is the same scientist's
  const joinsLast = writing !== null && last !== undefined && (writing.speaker === null || writing.speaker === last.speaker);

  return (
    <div className="flex flex-col gap-4" data-testid="lab" data-status={lab.status} data-meeting={lab.meeting}>
      <About lab={lab} />
      {inRounds(lab.turns).map((group) => {
        const name = roundName(group.round, lab);

        return (
          <section key={group.turns[0].key} className="flex flex-col gap-4" aria-label={name ?? "Discussion"}>
            {name !== null && <RoundHeading name={name} />}
            {group.turns.map((turn) => (
              <TurnView key={turn.key} turn={turn} live={live && turn === last} writing={joinsLast && turn === last ? writing.text : null} />
            ))}
          </section>
        );
      })}
      {writing !== null && !joinsLast && (
        <Speaking speaker={writing.speaker ?? "A scientist"}>
          <Writing text={writing.text} />
        </Speaking>
      )}
      {live && last === undefined && writing === null && <Waiting>Getting the team together…</Waiting>}
      {lab.status === "failed" && (
        <p role="alert" className="whitespace-pre-wrap break-words rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {lab.error || "The session failed."}
        </p>
      )}
      {lab.status === "interrupted" && <p className="text-xs text-muted-foreground">The session was cut short.</p>}
    </div>
  );
}
