import { CircleAlert, OctagonX, Paperclip } from "lucide-react";
import { BrandMark } from "@/components/brand";
import { cn } from "@/lib/utils";
import type { Turn } from "@/lib/transcript";
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

// What the lead says, with who is saying it beside it
export function LeadMessage({
  speaker,
  live = false,
  className,
  children,
}: {
  speaker: string;
  live?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-3" data-testid="lead-message">
      <BrandMark className="mt-0.5 size-6 rounded-md" />
      <div className="min-w-0 flex-1">
        <div className="mb-0.5 text-sm font-medium">{speaker}</div>
        <div className={cn("whitespace-pre-wrap break-words text-[15px] leading-7", className)}>
          {children}
          {live && <span aria-hidden className="ml-0.5 inline-block h-4 w-0.5 translate-y-0.5 animate-pulse bg-foreground" />}
        </div>
      </div>
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
  return (
    <section className="flex flex-col gap-5" aria-label={`Turn ${turn.number}`}>
      {turn.user && <UserMessage text={turn.user.text} attachments={turn.user.attachments} />}
      {turn.outcome === "answered" && <LeadMessage speaker={lead}>{turn.text}</LeadMessage>}
      {turn.outcome === "running" && turn.writing !== "" && (
        <LeadMessage speaker={lead} live>
          {turn.writing}
        </LeadMessage>
      )}
      {turn.outcome === "running" && turn.writing === "" && working && (
        <div className="flex items-center gap-3 text-sm text-muted-foreground" role="status">
          <BrandMark className="size-6 rounded-md" />
          <span className="animate-pulse">{lead} is thinking…</span>
        </div>
      )}
      {turn.outcome === "stopped" && <Notice tone="muted">{turn.text || "Stopped."}</Notice>}
      {turn.outcome === "failed" && <Notice tone="error">{turn.text || "Something went wrong."}</Notice>}
    </section>
  );
}
