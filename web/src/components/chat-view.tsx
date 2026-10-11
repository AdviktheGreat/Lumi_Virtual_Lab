"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowDown } from "lucide-react";
import { useChats } from "@/components/chats-provider";
import { Composer } from "@/components/composer";
import { LeadMessage, Notice, TurnView } from "@/components/messages";
import { PageHeader } from "@/components/page-header";
import { useServer } from "@/components/server-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatCost } from "@/lib/format";
import { useChat } from "@/lib/use-chat";
import { useStickToBottom } from "@/lib/use-stick-to-bottom";
import type { ChatState } from "@/lib/types";

const STATE_LABELS: Record<ChatState, string | null> = {
  idle: null,
  running: "Working",
  pausing: "Pausing",
  paused: "Paused",
  stopping: "Stopping",
};

export function ChatNotFound() {
  return (
    <>
      <PageHeader />
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <h1 className="text-lg font-semibold">This conversation is not here</h1>
        <p className="max-w-sm text-sm text-muted-foreground">It may have been deleted, or the address is not one of a conversation.</p>
        <Button asChild variant="outline">
          <Link href="/">Start a new one</Link>
        </Button>
      </div>
    </>
  );
}

// One conversation with the lead. It is given the conversation's id as its key.
export function ChatView({ id }: { id: string }) {
  const { status, transcript, connection } = useChat(id);
  const { refresh } = useChats();
  const { report } = useServer();
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const { scroller, atBottom, jump, onScroll } = useStickToBottom<HTMLDivElement>(transcript.lastId);

  const { state, title } = transcript;
  const working = state !== "idle";
  const lead = status.kind === "ready" ? status.info.lead : "Lead scientist";

  // The list on the side shows a conversation's title and when it last did anything, which a turn changes
  useEffect(() => {
    void refresh();
  }, [state, title, refresh]);

  useEffect(() => {
    document.title = title ? `${title} · Virtual Lab` : "Virtual Lab";

    return () => {
      document.title = "Virtual Lab";
    };
  }, [title]);

  async function send() {
    const text = draft.trim();
    setSending(true);
    setProblem(null);
    try {
      await api.send(id, text);
      setDraft("");
      jump("instant");
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    } finally {
      setSending(false);
    }
  }

  async function stop() {
    try {
      await api.stop(id);
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    }
  }

  if (status.kind === "missing") return <ChatNotFound />;
  if (status.kind === "failed") {
    return (
      <>
        <PageHeader />
        <div className="p-6">
          <Notice tone="error">{describeError(status.error)}</Notice>
        </div>
      </>
    );
  }

  const label = STATE_LABELS[state];
  const cost = formatCost(transcript.spent);
  const model = status.kind === "ready" ? status.info.config.model : null;

  return (
    <>
      <PageHeader>
        <h1 className="min-w-0 flex-1 truncate text-sm font-medium" data-testid="chat-title">
          {title || (status.kind === "ready" ? status.info.title : "")}
        </h1>
        {label && (
          <Badge variant="secondary" className="gap-1.5" data-testid="chat-state">
            <span className="size-1.5 animate-pulse rounded-full bg-brand" aria-hidden />
            {label}
          </Badge>
        )}
        {cost && (
          <span className="text-xs tabular-nums text-muted-foreground" title="Spent in this conversation">
            {cost}
            {transcript.maxCost !== null && ` of ${formatCost(transcript.maxCost)}`}
          </span>
        )}
      </PageHeader>

      {connection === "closed" && (
        <div className="px-4 pt-3">
          <Notice tone="error">The live connection to this conversation was lost. Reload the page to follow it again.</Notice>
        </div>
      )}

      <div className="relative min-h-0 flex-1">
        <div ref={scroller} onScroll={onScroll} className="h-full overflow-y-auto" data-testid="transcript">
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-6">
            {status.kind === "loading" && transcript.turns.length === 0 && (
              <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading the conversation">
                <Skeleton className="ml-auto h-10 w-2/5 rounded-2xl" />
                <Skeleton className="h-4 w-4/5" />
                <Skeleton className="h-4 w-3/5" />
              </div>
            )}
            {transcript.turns.map((turn) => (
              <TurnView key={turn.number} turn={turn} lead={lead} working={working} />
            ))}
            {status.kind === "ready" && transcript.turns.length === 0 && connection !== "connecting" && (
              <LeadMessage speaker={lead}>This conversation has nothing in it yet. Ask something below.</LeadMessage>
            )}
          </div>
        </div>
        {!atBottom && (
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Jump to the latest"
            onClick={() => jump()}
            className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-card shadow-md"
          >
            <ArrowDown className="size-4" />
          </Button>
        )}
      </div>

      <div className="mx-auto w-full max-w-3xl px-4 pb-4 pt-2">
        {problem && (
          <div className="pb-2">
            <Notice tone="error">{problem}</Notice>
          </div>
        )}
        <Composer
          value={draft}
          onValueChange={setDraft}
          onSend={() => void send()}
          running={working}
          onStop={() => void stop()}
          disabled={sending || status.kind !== "ready"}
          footer={model ? `${lead} · ${model}` : undefined}
        />
      </div>
    </>
  );
}
