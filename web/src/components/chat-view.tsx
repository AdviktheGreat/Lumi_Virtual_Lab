"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowDown } from "lucide-react";
import { NoteChip } from "@/components/activity";
import { CaughtUpProvider } from "@/components/caught-up";
import { useChats } from "@/components/chats-provider";
import { CommandsHelp } from "@/components/commands-help";
import { Composer } from "@/components/composer";
import { ExportMenu } from "@/components/export-menu";
import { ChatFilesProvider } from "@/components/chat-files";
import { FilesButton, FilesPanel } from "@/components/files-panel";
import { LabDialog } from "@/components/lab-dialog";
import { LimitsDialog } from "@/components/limits-dialog";
import { ModelButton, ModelDialog } from "@/components/model-dialog";
import { LeadBlock, Notice, ProblemNotice, TurnView } from "@/components/messages";
import { PageHeader } from "@/components/page-header";
import { useServer } from "@/components/server-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { attachedNames, readiness } from "@/lib/attachments";
import { isDirective, written, type Invocation } from "@/lib/commands";
import { joining } from "@/lib/team-choice";
import { describeError, plainProblem, problemOf, type Problem } from "@/lib/errors";
import { EXPORT_CHOICES } from "@/lib/export";
import { filesChanged } from "@/lib/files";
import { formatCost } from "@/lib/format";
import { cleanTitle } from "@/lib/history";
import { currentTurn, unreadNotes, type SentNote } from "@/lib/steering";
import { useAttachments } from "@/lib/use-attachments";
import { useChat } from "@/lib/use-chat";
import { useExport } from "@/lib/use-export";
import { useFiles } from "@/lib/use-files";
import { useStickToBottom } from "@/lib/use-stick-to-bottom";
import { waitingOnYou, type Turn } from "@/lib/transcript";
import type { ChatState, LabChoice, LimitsChange } from "@/lib/types";

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
  const router = useRouter();
  const { status, transcript, connection, reload } = useChat(id);
  const { refresh } = useChats();
  const { server, report } = useServer();
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [sentNotes, setSentNotes] = useState<SentNote[]>([]);
  const [filesOpen, setFilesOpen] = useState(false);
  const [choosingModel, setChoosingModel] = useState(false);
  const [limiting, setLimiting] = useState(false);
  // What was written after /lab while it is being chosen who works on it, which is null while it is not
  const [labbing, setLabbing] = useState<string | null>(null);
  const [helping, setHelping] = useState(false);
  const exporter = useExport(id, setProblem);
  const attachments = useAttachments(id, server.status === "ready" ? server.settings.max_upload_bytes : null);
  const { scroller, atBottom, jump, onScroll } = useStickToBottom<HTMLDivElement>(transcript.lastId);
  // The files are looked at again when something may have changed them: code ran, a turn ended, or a file was sent
  const sentFiles = attachments.items.filter((item) => item.status === "ready").length;
  const listed = useFiles(id, filesChanged(transcript) + sentFiles);

  const { state, title } = transcript;
  const working = state !== "idle";
  const waitingNotes = unreadNotes(sentNotes, transcript.turns, working);
  const lead = status.kind === "ready" ? status.info.lead : "Lead scientist";
  // What came before the page was opened is replayed to it, and what comes after is as it happens
  const caughtUp = status.kind === "ready" && transcript.lastId >= status.info.last_event_id;

  // The list on the side shows a conversation's title and when it last did anything, which a turn changes
  useEffect(() => {
    void refresh();
  }, [state, title, refresh]);

  useEffect(() => {
    document.title = title ? `${title} · Lumi Virtual Lab` : "Lumi Virtual Lab";

    return () => {
      document.title = "Lumi Virtual Lab";
    };
  }, [title]);

  function attach(files: File[]) {
    const refused = attachments.add(files);
    if (refused.length > 0) setProblem(plainProblem(refused.join("\n")));
  }

  // What is in the box is sent as a message, or a command is, which is given with a message of its own and which, when it
  // could not be sent, is put back in the box
  async function send(command?: Invocation) {
    const text = command ? command.arg.trim() : draft.trim();
    const sent = attachments.items.filter((item) => item.status === "ready");
    setSending(true);
    setProblem(null);
    try {
      await api.send(id, text, attachedNames(sent), false, command?.name);
      setDraft("");
      attachments.remove(sent.map((item) => item.id));
      jump("instant");
    } catch (error) {
      if (command) setDraft(written(command));
      report(error);
      setProblem(problemOf(error));
    } finally {
      setSending(false);
    }
  }

  // What is to be worked on is sent with who is to work on it, which the panel that chose them is told if it could not be, since
  // it is still open to be changed. The scientists who were not on the team are on it afterwards.
  async function sendLab(agenda: string, lab: LabChoice) {
    const sent = attachments.items.filter((item) => item.status === "ready");
    setProblem(null);
    try {
      await api.send(id, agenda, attachedNames(sent), false, "lab", lab);
    } catch (error) {
      report(error);
      throw error;
    }
    attachments.remove(sent.map((item) => item.id));
    jump("instant");
    if (status.kind === "ready" && joining(lab.members, status.info.team).length > 0) reload();
  }

  // The last message is sent again with the files it had, and the command, in place of it and of what came of it
  async function replace(turn: Turn, text: string) {
    setSending(true);
    setProblem(null);
    try {
      await api.send(
        id,
        text.trim(),
        (turn.user?.attachments ?? []).map((file) => file.name),
        true,
        turn.user?.directive,
        turn.user?.lab,
      );
      setSentNotes([]);
      jump("instant");
    } catch (error) {
      report(error);
      setProblem(problemOf(error));
    } finally {
      setSending(false);
    }
  }

  // A note is for the lead as it works, so what is not taken, because it has finished, is left in the box to be sent as a
  // message
  async function note() {
    const text = draft.trim();
    const turn = currentTurn(transcript.turns);
    setSending(true);
    setProblem(null);
    try {
      const { accepted } = await api.note(id, text);
      if (accepted) {
        setSentNotes((notes) => [...notes, { turn, text }]);
        setDraft("");
        jump("instant");
      } else {
        setProblem(plainProblem("The lead had already finished, so the note was not added. Send it as a message instead."));
      }
    } catch (error) {
      report(error);
      setProblem(problemOf(error));
    } finally {
      setSending(false);
    }
  }

  async function steer(action: "pause" | "resume" | "stop") {
    try {
      await api[action](id);
    } catch (error) {
      report(error);
      setProblem(problemOf(error));
    }
  }

  async function rename(typed: string) {
    const next = cleanTitle(typed);
    if (next === null) return;
    setProblem(null);
    try {
      await api.renameChat(id, next);
      void refresh();
    } catch (error) {
      report(error);
      setProblem(problemOf(error));
    }
  }

  function run(invocation: Invocation) {
    const { name, arg } = invocation;
    if (name === "lab") {
      setLabbing(arg);

      return;
    }
    if (isDirective(name)) {
      void send(invocation);

      return;
    }
    switch (name) {
      case "budget":
        setLimiting(true);
        break;
      case "model":
        setChoosingModel(true);
        break;
      case "files":
        setFilesOpen((was) => !was);
        break;
      case "export": {
        const choice = EXPORT_CHOICES.find((each) => each.format === arg);
        if (choice) void exporter.save(choice.format);
        break;
      }
      case "rename":
        void rename(arg);
        break;
      case "new":
        router.push("/");
        break;
      case "pause":
      case "resume":
      case "stop":
        void steer(name);
        break;
      case "help":
        setHelping(true);
        break;
    }
  }

  async function changeLimits(changes: LimitsChange) {
    try {
      await api.setLimits(id, changes);
    } catch (error) {
      report(error);
      throw error;
    }
    reload();
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

  // What the lead waits for from the researcher is what the conversation is waiting for, which is not work
  const label = waitingOnYou(transcript.turns) > 0 ? "Waiting for you" : STATE_LABELS[state];
  const cost = formatCost(transcript.spent);
  const model = status.kind === "ready" ? status.info.config.model : null;

  return (
    <ChatFilesProvider value={id}>
      <CaughtUpProvider value={caughtUp}>
        <PageHeader>
          <h1 className="min-w-0 flex-1 truncate font-serif text-lg font-medium tracking-tight" data-testid="chat-title">
            {title || (status.kind === "ready" ? status.info.title : "") || <span className="sr-only">Conversation</span>}
          </h1>
          {label && (
            <Badge variant="secondary" className="gap-1.5 border-primary/35 bg-highlight text-highlight-foreground" data-testid="chat-state">
              <span className="size-1.5 animate-pulse rounded-full bg-current motion-reduce:animate-none" aria-hidden />
              {label}
            </Badge>
          )}
          {cost && (
            <span className="font-mono text-xs tabular-nums text-muted-foreground" title="Spent in this conversation">
              {cost}
              {transcript.maxCost !== null && ` of ${formatCost(transcript.maxCost)}`}
            </span>
          )}
          <ExportMenu exporter={exporter} disabled={transcript.turns.length === 0} />
          <FilesButton count={listed.loaded ? listed.files.length : null} open={filesOpen} onToggle={() => setFilesOpen((was) => !was)} />
        </PageHeader>

        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            {connection === "closed" && (
              <div className="px-4 pt-3">
                <Notice tone="error">The live connection to this conversation was lost. Reload the page to follow it again.</Notice>
              </div>
            )}

            <div className="relative min-h-0 flex-1">
              <div ref={scroller} onScroll={onScroll} className="h-full overflow-y-auto" data-testid="transcript">
                <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-6">
                  {status.kind === "loading" && transcript.turns.length === 0 && (
                    <div className="flex flex-col gap-3" role="status" aria-busy="true" aria-label="Loading the conversation">
                      <Skeleton className="ml-auto h-10 w-2/5 rounded-2xl" />
                      <Skeleton className="h-4 w-4/5" />
                      <Skeleton className="h-4 w-3/5" />
                    </div>
                  )}
                  {transcript.turns.map((turn, at) => (
                    <TurnView
                      key={turn.number}
                      turn={turn}
                      lead={lead}
                      state={state}
                      onReplace={
                        at === transcript.turns.length - 1 && turn.outcome !== "running" && !working && !sending && caughtUp
                          ? (text) => void replace(turn, text)
                          : undefined
                      }
                      onRaiseLimit={at === transcript.turns.length - 1 && status.kind === "ready" ? () => setLimiting(true) : undefined}
                    />
                  ))}
                  {waitingNotes.map((note, at) => (
                    <NoteChip key={`${note.turn}-${at}`} text={note.text} waiting />
                  ))}
                  {status.kind === "ready" && transcript.turns.length === 0 && connection !== "connecting" && (
                    <LeadBlock speaker={lead}>
                      <p className="text-[15px] leading-7">This conversation has nothing in it yet. Ask something below.</p>
                    </LeadBlock>
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
                  <ProblemNotice problem={problem} />
                </div>
              )}
              <Composer
                value={draft}
                onValueChange={setDraft}
                onSend={() => void send()}
                state={state}
                onNote={() => void note()}
                onPause={() => void steer("pause")}
                onResume={() => void steer("resume")}
                onStop={() => void steer("stop")}
                disabled={sending || status.kind !== "ready"}
                holdUp={readiness(attachments.items)}
                files={{ items: attachments.items, onAdd: attach, onRemove: (item) => attachments.remove([item]), onRetry: attachments.retry }}
                commands={{
                  place: "chat",
                  turns: transcript.turns.length,
                  answered: transcript.turns.filter((turn) => turn.outcome === "answered").length,
                  directives: status.kind === "ready" ? status.info.directives : null,
                  onRun: run,
                }}
                footer={
                  model ? (
                    <ModelButton prefix={lead} model={model} disabled={working || sending} onClick={() => setChoosingModel(true)} />
                  ) : undefined
                }
              />
            </div>
          </div>
          {filesOpen && <FilesPanel id={id} listed={listed} onClose={() => setFilesOpen(false)} />}
        </div>
        {limiting && status.kind === "ready" && server.status === "ready" && (
          <LimitsDialog
            current={{ max_cost: status.info.max_cost, max_delegations: status.info.max_delegations, max_rounds: status.info.max_rounds }}
            limits={server.settings.chat_limits}
            spent={transcript.spent}
            begun
            onSave={changeLimits}
            onClose={() => setLimiting(false)}
          />
        )}
        {labbing !== null && status.kind === "ready" && (
          <LabDialog
            agenda={labbing}
            lead={status.info.lead}
            team={status.info.team}
            ceiling={status.info.max_rounds}
            onStart={sendLab}
            onClose={(left) => {
              setLabbing(null);
              if (left !== null && left.trim() !== "") setDraft(written({ name: "lab", arg: left.trim() }));
            }}
          />
        )}
        {helping && <CommandsHelp place="chat" onClose={() => setHelping(false)} />}
        {choosingModel && model !== null && (
          <ModelDialog
            title="Change the model"
            description="The lead and the team answer with it from the next message. What was said stays, and so do the files. Code that was running starts afresh."
            current={model}
            onChoose={async (next) => {
              if (next !== model) {
                try {
                  await api.switchModel(id, next);
                } catch (error) {
                  report(error);
                  throw error;
                }
                reload();
              }
              setChoosingModel(false);
            }}
            onClose={() => setChoosingModel(false)}
          />
        )}
      </CaughtUpProvider>
    </ChatFilesProvider>
  );
}
