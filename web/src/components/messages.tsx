import { CircleAlert, OctagonX, Paperclip } from "lucide-react";
import { Steps } from "@/components/activity";
import { BrandMark } from "@/components/brand";
import { Markdown } from "@/components/markdown";
import { cn } from "@/lib/utils";
import { isThinking, type Turn } from "@/lib/transcript";
import type { Attachment } from "@/lib/types";

function Files({ files }: { files: Attachment[] }) {
  if (files.length === 0) return null;

  return (
    <ul className="flex flex-wrap justify-end gap-1.5">
      {files.map((file) => (
        <li
          key={file.path}
          className="flex max-w-full items-center gap-1.5 rounded-lg border border-border bg-card px-2 py-1 text-xs text-muted-foreground"
        >
          <Paperclip className="size-3 shrink-0" aria-hidden />
          <span className="truncate">{file.name}</span>
        </li>
      ))}
    </ul>
  );
}

export function UserMessage({ text, attachments }: { text: string; attachments: Attachment[] }) {
  return (
    <div className="flex flex-col items-end gap-1.5" data-testid="user-message">
      <Files files={attachments} />
      {text && (
        <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-secondary px-4 py-2.5 text-[15px] leading-6">
          {text}
        </p>
      )}
    </div>
  );
}

// Everything the lead does in a turn, with who is doing it beside it
export function LeadBlock({ speaker, children }: { speaker: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3" data-testid="lead-block">
      <BrandMark className="mt-0.5 size-6 rounded-md" />
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <div className="text-sm font-medium">{speaker}</div>
        {children}
      </div>
    </div>
  );
}

// What the lead says to the researcher, which is the reply it is writing or the answer it gave
export function LeadText({ text, live = false }: { text: string; live?: boolean }) {
  return (
    <div data-testid="lead-message">
      <Markdown text={text} />
      {live && <span aria-hidden className="mt-2 inline-block size-2 animate-pulse rounded-full bg-brand" />}
    </div>
  );
}

export function Notice({ tone, children }: { tone: "error" | "muted"; children: React.ReactNode }) {
  const Icon = tone === "error" ? CircleAlert : OctagonX;

  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-2 rounded-lg border px-3 py-2 text-sm",
        tone === "error"
          ? "border-destructive/30 bg-destructive/10 text-destructive"
          : "border-border bg-muted/50 text-muted-foreground",
      )}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 whitespace-pre-wrap break-words">{children}</div>
    </div>
  );
}

export function TurnView({ turn, lead, working }: { turn: Turn; lead: string; working: boolean }) {
  const reply = turn.outcome === "answered" ? turn.text : turn.writing;
  const thinking = isThinking(turn, working);

  return (
    <section className="flex flex-col gap-5" aria-label={`Turn ${turn.number}`}>
      {turn.user && <UserMessage text={turn.user.text} attachments={turn.user.attachments} />}
      {(turn.steps.length > 0 || reply !== "" || thinking) && (
        <LeadBlock speaker={lead}>
          <Steps steps={turn.steps} />
          {reply !== "" && <LeadText text={reply} live={turn.outcome === "running"} />}
          {thinking && (
            <div className="animate-pulse text-sm text-muted-foreground" role="status">
              Thinking…
            </div>
          )}
        </LeadBlock>
      )}
      {turn.outcome === "stopped" && <Notice tone="muted">{turn.text || "Stopped."}</Notice>}
      {turn.outcome === "failed" && <Notice tone="error">{turn.text || "Something went wrong."}</Notice>}
    </section>
  );
}
