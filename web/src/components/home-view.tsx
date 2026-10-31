"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound } from "lucide-react";
import { BrandLogo } from "@/components/brand";
import { CapabilityCards } from "@/components/capability-cards";
import { useChats } from "@/components/chats-provider";
import { CommandsHelp } from "@/components/commands-help";
import { Composer } from "@/components/composer";
import { LabDialog } from "@/components/lab-dialog";
import { LimitsDialog } from "@/components/limits-dialog";
import { Notice, ProblemNotice } from "@/components/messages";
import { ModelButton, ModelDialog } from "@/components/model-dialog";
import { PageHeader } from "@/components/page-header";
import { useServer } from "@/components/server-provider";
import { useSettings } from "@/components/settings-provider";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { readiness } from "@/lib/attachments";
import { isDirective, written, type Invocation } from "@/lib/commands";
import { plainProblem, problemOf, type Problem } from "@/lib/errors";
import { DEFAULT_LEAD_TITLE } from "@/lib/team-choice";
import { useAttachments } from "@/lib/use-attachments";
import { useMissingKeys } from "@/lib/use-missing-keys";
import type { ChatInfo, LabChoice, LimitsChange } from "@/lib/types";

export function HomeView() {
  const router = useRouter();
  const { server, report } = useServer();
  const { refresh } = useChats();
  const settings = useSettings();
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  // The model chosen here for the conversation to begin, in place of the one the settings name, and whether it is being chosen
  const [chosen, setChosen] = useState<string | null>(null);
  const [choosing, setChoosing] = useState(false);
  // The limits chosen here for it, which are only those that differ from what the settings say, and whether they are being chosen
  const [limitsChosen, setLimitsChosen] = useState<LimitsChange>({});
  const [limiting, setLimiting] = useState(false);
  // What was written after /lab while it is being chosen who works on it, which is null while it is not
  const [labbing, setLabbing] = useState<string | null>(null);
  const [helping, setHelping] = useState(false);
  // There is no conversation to send files to until the message is, so they are held until then
  const attachments = useAttachments(null, server.status === "ready" ? server.settings.max_upload_bytes : null);

  function attach(files: File[]) {
    const refused = attachments.add(files);
    if (refused.length > 0) setProblem(plainProblem(refused.join("\n")));
  }

  // A conversation is begun with a message, which a command may be given with, and with /lab who is to work on it. If it could
  // not be, there is no conversation, and the error is thrown.
  async function begin(text: string, directive?: string, lab?: LabChoice) {
    let chat: ChatInfo | null = null;
    try {
      chat = await api.createChat({ ...(chosen === null ? {} : { model: chosen }), ...limitsChosen });
      const names = await attachments.upload(chat.id);
      await api.send(chat.id, text, names, false, directive, lab);
      void refresh();
      router.push(`/chat?id=${encodeURIComponent(chat.id)}`);
    } catch (error) {
      if (chat !== null) {
        // A conversation that was never begun is not left in the list, and the files it took go with it
        await api.deleteChat(chat.id).catch(() => undefined);
        attachments.requeue();
      }
      throw error;
    }
  }

  // A conversation is begun with what is in the box, or with a command, which is given with the message that begins it
  async function start(command?: Invocation) {
    const text = command ? command.arg.trim() : draft.trim();
    setSending(true);
    setProblem(null);
    try {
      await begin(text, command?.name);
    } catch (error) {
      if (command) setDraft(written(command));
      report(error);
      setProblem(problemOf(error));
      setSending(false);
    }
  }

  // The same, from the panel that chose who is to work on it, which stays open to be changed where it could not be begun
  async function startLab(agenda: string, lab: LabChoice) {
    setSending(true);
    setProblem(null);
    try {
      await begin(agenda, "lab", lab);
    } catch (error) {
      report(error);
      setSending(false);
      throw error;
    }
  }

  const model = chosen ?? (server.status === "ready" ? server.settings.model : null);
  const missing = useMissingKeys(model, settings.closed);
  const ready = server.status === "ready" ? server.settings : null;

  // Where code cannot run, what asks for it is not offered, which is known before there is a conversation
  const noCode = ready !== null && ready.code === "none" ? "code is turned off in the settings" : null;
  const directives = ready === null ? null : { code: noCode, plot: noCode };

  function run(invocation: Invocation) {
    const { name, arg } = invocation;
    if (name === "lab") setLabbing(arg);
    else if (isDirective(name)) void start(invocation);
    else if (name === "budget") setLimiting(true);
    else if (name === "model") setChoosing(true);
    else if (name === "help") setHelping(true);
  }

  return (
    <>
      <PageHeader className="border-transparent" />
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-[radial-gradient(55%_45%_at_88%_0%,var(--highlight),transparent)] px-4 py-8">
        <div className="mx-auto my-auto flex w-full max-w-3xl flex-col gap-10">
          <div className="flex flex-col gap-6">
            <div className="flex flex-col items-start gap-4">
              <BrandLogo className="mb-3" />
              <h1 className="max-w-2xl text-balance font-serif text-4xl font-medium leading-[1.06] tracking-tight sm:text-5xl">
                What would you like to investigate?
              </h1>
              <p className="max-w-xl text-balance text-base leading-7 text-muted-foreground">
                Ask the lead scientist. When a question needs more expertise, the lead brings in the lab&apos;s team.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              {problem && <ProblemNotice problem={problem} />}
              {missing.length > 0 && problem?.fix !== "keys" && (
                <Notice
                  tone="muted"
                  icon={KeyRound}
                  action={
                    <Button variant="outline" size="xs" onClick={() => settings.open("keys")} className="shrink-0 text-foreground">
                      Add the key{missing.length === 1 ? "" : "s"}
                    </Button>
                  }
                >
                  {model} needs {missing.join(", ")}, which {missing.length === 1 ? "is" : "are"} not set.
                </Notice>
              )}
              <Composer
                value={draft}
                onValueChange={setDraft}
                onSend={() => void start()}
                disabled={sending}
                holdUp={readiness(attachments.items)}
                files={{
                  items: attachments.items,
                  onAdd: attach,
                  onRemove: (id) => attachments.remove([id]),
                  onRetry: attachments.retry,
                }}
                commands={{ place: "home", turns: 0, answered: 0, directives, onRun: run }}
                autoFocus
                roomy
                footer={model ? <ModelButton model={model} disabled={sending} onClick={() => setChoosing(true)} /> : undefined}
                className="shadow-md"
              />
            </div>
          </div>

          {choosing && model !== null && (
            <ModelDialog
              title="Choose the model"
              description="The lead and the team of this conversation answer with it. You can change it later, from the conversation."
              current={model}
              onChoose={async (next) => {
                setChosen(next);
                setChoosing(false);
              }}
              onClose={() => setChoosing(false)}
            />
          )}

          {limiting && ready !== null && (
            <LimitsDialog
              current={{
                max_cost: "max_cost" in limitsChosen ? (limitsChosen.max_cost ?? null) : ready.max_cost,
                max_delegations: limitsChosen.max_delegations ?? ready.chat_limits.max_delegations.default,
                max_rounds: limitsChosen.max_rounds ?? ready.chat_limits.max_rounds.default,
              }}
              limits={ready.chat_limits}
              spent={null}
              begun={false}
              onSave={async (changes) => setLimitsChosen((was) => ({ ...was, ...changes }))}
              onClose={() => setLimiting(false)}
            />
          )}
          {labbing !== null && ready !== null && (
            <LabDialog
              agenda={labbing}
              lead={DEFAULT_LEAD_TITLE}
              team={null}
              ceiling={limitsChosen.max_rounds ?? ready.chat_limits.max_rounds.default}
              onStart={startLab}
              onClose={(left) => {
                setLabbing(null);
                if (left !== null && left.trim() !== "") setDraft(written({ name: "lab", arg: left.trim() }));
              }}
            />
          )}
          {helping && <CommandsHelp place="home" onClose={() => setHelping(false)} />}

          <CapabilityCards onChoose={setDraft} />
        </div>
      </div>
    </>
  );
}
