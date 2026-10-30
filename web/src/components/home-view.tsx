"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound } from "lucide-react";
import { BrandLogo } from "@/components/brand";
import { CapabilityCards } from "@/components/capability-cards";
import { useChats } from "@/components/chats-provider";
import { Composer } from "@/components/composer";
import { Notice, ProblemNotice } from "@/components/messages";
import { ModelButton, ModelDialog } from "@/components/model-dialog";
import { PageHeader } from "@/components/page-header";
import { useServer } from "@/components/server-provider";
import { useSettings } from "@/components/settings-provider";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { readiness } from "@/lib/attachments";
import { plainProblem, problemOf, type Problem } from "@/lib/errors";
import { useAttachments } from "@/lib/use-attachments";
import { useMissingKeys } from "@/lib/use-missing-keys";
import type { ChatInfo } from "@/lib/types";

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
  // There is no conversation to send files to until the message is, so they are held until then
  const attachments = useAttachments(null, server.status === "ready" ? server.settings.max_upload_bytes : null);

  function attach(files: File[]) {
    const refused = attachments.add(files);
    if (refused.length > 0) setProblem(plainProblem(refused.join("\n")));
  }

  async function start() {
    const text = draft.trim();
    setSending(true);
    setProblem(null);
    let chat: ChatInfo | null = null;
    try {
      chat = await api.createChat(chosen === null ? {} : { model: chosen });
      const names = await attachments.upload(chat.id);
      await api.send(chat.id, text, names);
      void refresh();
      router.push(`/chat?id=${encodeURIComponent(chat.id)}`);
    } catch (error) {
      if (chat !== null) {
        // A conversation that was never begun is not left in the list, and the files it took go with it
        await api.deleteChat(chat.id).catch(() => undefined);
        attachments.requeue();
      }
      report(error);
      setProblem(problemOf(error));
      setSending(false);
    }
  }

  const model = chosen ?? (server.status === "ready" ? server.settings.model : null);
  const missing = useMissingKeys(model, settings.closed);

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

          <CapabilityCards onChoose={setDraft} />
        </div>
      </div>
    </>
  );
}
