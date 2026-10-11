"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Dna, FlaskConical, Microscope, Network } from "lucide-react";
import { BrandMark } from "@/components/brand";
import { useChats } from "@/components/chats-provider";
import { Composer } from "@/components/composer";
import { Notice } from "@/components/messages";
import { PageHeader } from "@/components/page-header";
import { useServer } from "@/components/server-provider";
import { api } from "@/lib/api";
import { readiness } from "@/lib/attachments";
import { describeError } from "@/lib/errors";
import { useAttachments } from "@/lib/use-attachments";
import type { ChatInfo } from "@/lib/types";

const EXAMPLES = [
  {
    icon: Dna,
    title: "Base editing",
    prompt: "Explain how CRISPR base editors work and where they fall short, and what would improve them.",
  },
  {
    icon: Microscope,
    title: "Experiment design",
    prompt: "Plan an experiment to test whether knocking down a gene changes T-cell exhaustion, with controls.",
  },
  {
    icon: Network,
    title: "Method comparison",
    prompt: "Compare structure-prediction and physics-based approaches to docking an antibody to its antigen.",
  },
  {
    icon: FlaskConical,
    title: "Analysis plan",
    prompt: "Draft an analysis plan for a case-control GWAS of 5,000 samples, from quality control to follow-up.",
  },
];

export function HomeView() {
  const router = useRouter();
  const { server, report } = useServer();
  const { refresh } = useChats();
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // There is no conversation to send files to until the message is, so they are held until then
  const attachments = useAttachments(null, server.status === "ready" ? server.settings.max_upload_bytes : null);

  function attach(files: File[]) {
    const refused = attachments.add(files);
    if (refused.length > 0) setProblem(refused.join("\n"));
  }

  async function start() {
    const text = draft.trim();
    setSending(true);
    setProblem(null);
    let chat: ChatInfo | null = null;
    try {
      chat = await api.createChat();
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
      setProblem(describeError(error));
      setSending(false);
    }
  }

  const model = server.status === "ready" ? server.settings.model : null;

  return (
    <>
      <PageHeader />
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-4 py-8">
        <div className="flex w-full max-w-2xl flex-col gap-8">
          <div className="flex flex-col items-center gap-3 text-center">
            <BrandMark className="size-11 rounded-xl [&_svg]:size-6" />
            <h1 className="text-balance text-3xl font-semibold tracking-tight">What would you like to investigate?</h1>
            <p className="max-w-md text-balance text-[15px] text-muted-foreground">
              Ask the lead scientist. When a question needs more expertise, the lead brings in the lab&apos;s team.
            </p>
          </div>

          <div className="flex flex-col gap-2">
            {problem && <Notice tone="error">{problem}</Notice>}
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
              footer={model}
              className="shadow-md"
            />
          </div>

          <ul className="grid gap-2 sm:grid-cols-2" aria-label="Examples">
            {EXAMPLES.map(({ icon: Icon, title, prompt }) => (
              <li key={title}>
                <button
                  type="button"
                  onClick={() => setDraft(prompt)}
                  className="flex h-full w-full flex-col gap-1 rounded-xl border border-border bg-card p-3 text-left text-sm outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="flex items-center gap-2 font-medium">
                    <Icon className="size-4 text-brand" aria-hidden />
                    {title}
                  </span>
                  <span className="line-clamp-2 text-muted-foreground">{prompt}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
