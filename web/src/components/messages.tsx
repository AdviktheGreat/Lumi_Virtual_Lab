import { useState } from "react";
import { CircleAlert, OctagonX, Paperclip, Pencil, RotateCcw, type LucideIcon } from "lucide-react";
import { Steps } from "@/components/activity";
import { BrandMark } from "@/components/brand";
import { Markdown } from "@/components/markdown";
import { useSettings } from "@/components/settings-provider";
import { useSetup } from "@/components/setup-provider";
import { Button } from "@/components/ui/button";
import type { Problem } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { holdNotice } from "@/lib/steering";
import { isThinking, type Turn } from "@/lib/transcript";
import type { Attachment, ChatState } from "@/lib/types";

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

// The last message, which can be sent again as it was or changed, in place of it and of what came of it. Its files go
// with it.
function ReplaceableUserMessage({
  text,
  attachments,
  onReplace,
}: {
  text: string;
  attachments: Attachment[];
  onReplace: (text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text);

  if (editing) {
    return (
      <form
        className="flex flex-col items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setEditing(false);
          onReplace(draft);
        }}
      >
        <Files files={attachments} />
        <textarea
          aria-label="Edit message"
          autoFocus
          rows={3}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setEditing(false);
          }}
          className="w-full resize-y rounded-xl border border-input bg-card px-3 py-2 text-[15px] leading-6 outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25"
        />
        <div className="flex gap-1.5">
          <Button type="button" variant="ghost" size="xs" onClick={() => setEditing(false)}>
            Cancel
          </Button>
          <Button type="submit" size="xs" disabled={draft.trim() === "" && attachments.length === 0}>
            Send again
          </Button>
        </div>
      </form>
    );
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <UserMessage text={text} attachments={attachments} />
      <div className="flex gap-1">
        <Button variant="ghost" size="xs" className="text-muted-foreground" onClick={() => onReplace(text)}>
          <RotateCcw aria-hidden />
          Retry
        </Button>
        <Button
          variant="ghost"
          size="xs"
          className="text-muted-foreground"
          onClick={() => {
            setDraft(text);
            setEditing(true);
          }}
        >
          <Pencil aria-hidden />
          Edit
        </Button>
      </div>
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

export function Notice({
  tone,
  icon,
  action,
  children,
}: {
  tone: "error" | "muted";
  // What stands for it, where the tone's own does not
  icon?: LucideIcon;
  // What the person can do about it
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  const Icon = icon ?? (tone === "error" ? CircleAlert : OctagonX);

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
      <div className="min-w-0 flex-1 whitespace-pre-wrap break-words">{children}</div>
      {action}
    </div>
  );
}

// What went wrong, with the way to put it right where there is one
export function ProblemNotice({ problem }: { problem: Problem }) {
  const settings = useSettings();
  const setup = useSetup();

  return (
    <Notice
      tone="error"
      action={
        problem.fix === "keys" ? (
          <Button variant="outline" size="xs" onClick={() => settings.open("keys")} className="shrink-0 text-foreground">
            Add the key
          </Button>
        ) : problem.fix === "setup" ? (
          <Button variant="outline" size="xs" onClick={() => setup.open()} className="shrink-0 text-foreground">
            Set up
          </Button>
        ) : undefined
      }
    >
      {problem.text}
    </Notice>
  );
}

export function TurnView({
  turn,
  lead,
  state,
  onReplace,
}: {
  turn: Turn;
  lead: string;
  state: ChatState;
  // Given for the last turn, once it is over, so that its message can be sent again
  onReplace?: (text: string) => void;
}) {
  const reply = turn.outcome === "answered" ? turn.text : turn.writing;
  const thinking = isThinking(turn, state === "running");
  // The lead is not thinking while it is held, and says so instead
  const held = turn.outcome === "running" ? holdNotice(state) : null;

  return (
    <section className="flex flex-col gap-5" aria-label={`Turn ${turn.number}`}>
      {turn.user &&
        (onReplace ? (
          <ReplaceableUserMessage key={turn.user.text} text={turn.user.text} attachments={turn.user.attachments} onReplace={onReplace} />
        ) : (
          <UserMessage text={turn.user.text} attachments={turn.user.attachments} />
        ))}
      {(turn.steps.length > 0 || reply !== "" || thinking || held !== null) && (
        <LeadBlock speaker={lead}>
          <Steps steps={turn.steps} />
          {reply !== "" && <LeadText text={reply} live={turn.outcome === "running"} />}
          {thinking && (
            <div className="animate-pulse text-sm text-muted-foreground" role="status">
              Thinking…
            </div>
          )}
          {held !== null && (
            <div className="text-sm text-muted-foreground" role="status" data-testid="held">
              {held}
            </div>
          )}
        </LeadBlock>
      )}
      {turn.outcome === "stopped" && <Notice tone="muted">{turn.text || "Stopped."}</Notice>}
      {turn.outcome === "failed" && <Notice tone="error">{turn.text || "Something went wrong."}</Notice>}
    </section>
  );
}
