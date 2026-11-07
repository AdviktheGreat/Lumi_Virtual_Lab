"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FolderInput, Pencil, SquarePen, Trash2 } from "lucide-react";
import { CampaignDialog } from "@/components/campaign-dialog";
import { MoveDialog } from "@/components/campaign-move";
import { useChats } from "@/components/chats-provider";
import { PageHeader } from "@/components/page-header";
import { useServer } from "@/components/server-provider";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import { changesTo, countPrograms, newProgramIn, spentBetween } from "@/lib/campaigns";
import { describeError } from "@/lib/errors";
import { formatCost, timeAgo } from "@/lib/format";
import { UNTITLED } from "@/lib/history";
import { kindName } from "@/lib/programs";
import type { Campaign, ChatSummary } from "@/lib/types";
import { useDocumentTitle } from "@/lib/use-document-title";

const WORKING = new Set(["running", "pausing", "paused", "stopping"]);

export function CampaignNotFound() {
  return (
    <>
      <PageHeader />
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <h1 className="text-lg font-semibold">This campaign is not here</h1>
        <p className="max-w-sm text-sm text-muted-foreground">It may have been deleted, or the address is not one of a campaign.</p>
        <Button asChild variant="outline">
          <Link href="/">Start a program</Link>
        </Button>
      </div>
    </>
  );
}

function stateOf(chat: ChatSummary): string | null {
  if (chat.state === "paused") return "Paused";
  if (WORKING.has(chat.state)) return "Working";

  return chat.state === "interrupted" ? "Cut off" : null;
}

// A program of the campaign: where it is opened, and the means to move it to another campaign or out of this one
function ProgramRow({ chat, onMove }: { chat: ChatSummary; onMove: (button: HTMLButtonElement) => void }) {
  const state = stateOf(chat);
  const title = chat.title || UNTITLED;

  return (
    <li data-chat-id={chat.id} className="group/row flex items-center gap-1 rounded-xl border border-border bg-card pr-2 shadow-xs">
      <Link
        href={`/chat?id=${encodeURIComponent(chat.id)}`}
        className="flex min-w-0 flex-1 flex-col gap-0.5 rounded-xl px-3.5 py-3 outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="truncate text-sm font-medium">{title}</span>
        <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
          <span>{kindName(chat.kind)}</span>
          <span>{timeAgo(chat.updated_at ?? chat.created_at)}</span>
          {chat.spent !== null && <span className="font-mono tabular-nums">{formatCost(chat.spent)}</span>}
          {state !== null && <span className="font-medium text-brand">{state}</span>}
        </span>
      </Link>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={`Change the campaign of ${title}`}
        title="Move to another campaign, or out of this one"
        onClick={(event) => onMove(event.currentTarget)}
        className="shrink-0 text-muted-foreground"
      >
        <FolderInput />
      </Button>
    </li>
  );
}

function DeleteDialog({ campaign, count, onClose }: { campaign: Campaign; count: number; onClose: () => void }) {
  const router = useRouter();
  const { refresh } = useChats();
  const { report } = useServer();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setProblem(null);
    try {
      await api.deleteCampaign(campaign.id);
    } catch (error) {
      // One that is gone already is what was wanted
      if (!(error instanceof ApiError && error.status === 404)) {
        report(error);
        setProblem(describeError(error));
        setBusy(false);

        return;
      }
    }
    await refresh();
    router.push("/");
  }

  return (
    <AlertDialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this campaign?</AlertDialogTitle>
          <AlertDialogDescription>
            “{campaign.name}” is deleted
            {count === 0
              ? "."
              : `. Its ${countPrograms(count)} ${count === 1 ? "is" : "are"} kept, and ${count === 1 ? "is" : "are"} no longer part of a campaign.`}
          </AlertDialogDescription>
        </AlertDialogHeader>
        {problem && (
          <p role="alert" className="text-sm text-destructive">
            {problem}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Keep it</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={busy}
            onClick={(event) => {
              // It is closed when the server has deleted it, and not before
              event.preventDefault();
              void remove();
            }}
          >
            {busy ? "Deleting…" : "Delete"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

// One campaign: its goal, which the lead of each of its programs is told, its programs, and what they have spent between
// them. It is given the campaign's id as its key, and is shown from what the list of campaigns and programs holds, so that
// it is as up to date as the side is.
export function CampaignView({ id }: { id: string }) {
  const { chats, campaigns, refresh } = useChats();
  const { report } = useServer();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [moving, setMoving] = useState<ChatSummary | null>(null);
  // What had the focus when a program's move was begun, to give it back to, since the program may not be here after
  const movedFrom = useRef<HTMLButtonElement | null>(null);
  const campaign = campaigns?.find((each) => each.id === id) ?? null;
  useDocumentTitle(campaign?.name);

  if (campaigns === null || chats === null) {
    return (
      <>
        <PageHeader />
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-5 pt-6" role="status" aria-busy="true" aria-label="Loading the campaign">
          <Skeleton className="h-8 w-1/2" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      </>
    );
  }
  if (campaign === null) return <CampaignNotFound />;

  const programs = chats.filter((chat) => chat.campaign === campaign.id);
  const spent = spentBetween(programs);

  return (
    <>
      <PageHeader>
        <h1 className="min-w-0 flex-1 truncate font-serif text-lg font-medium tracking-tight" data-testid="campaign-title">
          {campaign.name}
        </h1>
        <Button variant="outline" size="sm" onClick={() => setEditing(true)} data-testid="campaign-edit">
          <Pencil aria-hidden />
          Edit
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setDeleting(true)} data-testid="campaign-delete" className="text-muted-foreground hover:text-destructive">
          <Trash2 aria-hidden />
          Delete
        </Button>
      </PageHeader>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-10 px-5 pb-16 pt-6 sm:px-6">
          <section aria-labelledby="campaign-goal" className="flex flex-col gap-2">
            <h2 id="campaign-goal" className="text-sm font-medium text-muted-foreground">
              Goal
            </h2>
            {campaign.brief === "" ? (
              <p className="text-[15px] leading-7 text-muted-foreground" data-testid="campaign-brief-empty">
                No goal is written, so the lead of its programs is told nothing of the campaign. Edit the campaign to write one.
              </p>
            ) : (
              <p className="whitespace-pre-wrap break-words text-[15px] leading-7" data-testid="campaign-brief">
                {campaign.brief}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              The lead of each program of the campaign is told this goal in every message it answers.
            </p>
          </section>

          <section aria-labelledby="campaign-programs" className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-col gap-0.5">
                <h2 id="campaign-programs" className="text-sm font-medium text-muted-foreground">
                  Programs
                </h2>
                <p className="text-sm" data-testid="campaign-totals">
                  {countPrograms(programs.length)}, {formatCost(spent)} spent
                </p>
              </div>
              <Button asChild size="sm" data-testid="campaign-new-program">
                <Link href={newProgramIn(campaign)}>
                  <SquarePen aria-hidden />
                  New program in this campaign
                </Link>
              </Button>
            </div>
            {programs.length === 0 ? (
              <p className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
                No program is part of this campaign yet. Begin one here, or move one in from the list on the side.
              </p>
            ) : (
              <ul className="flex flex-col gap-2" aria-label="Programs of the campaign">
                {programs.map((chat) => (
                  <ProgramRow
                    key={chat.id}
                    chat={chat}
                    onMove={(button) => {
                      movedFrom.current = button;
                      setMoving(chat);
                    }}
                  />
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>

      {editing && (
        <CampaignDialog
          campaign={campaign}
          onSave={async (kept) => {
            const changes = changesTo(campaign, kept);
            if (Object.keys(changes).length === 0) return;
            try {
              await api.changeCampaign(campaign.id, changes);
            } catch (error) {
              report(error);
              throw error;
            }
            await refresh();
          }}
          onClose={() => setEditing(false)}
        />
      )}
      {deleting && <DeleteDialog campaign={campaign} count={programs.length} onClose={() => setDeleting(false)} />}
      {moving !== null && (
        <MoveDialog
          chat={moving}
          onClose={() => setMoving(null)}
          onClosed={(event) => {
            // The program that was moved is gone from the list, and so is its button, which the focus goes back to if it is not
            event.preventDefault();
            const button = movedFrom.current;
            (button !== null && button.isConnected ? button : document.querySelector<HTMLElement>("[data-testid=campaign-new-program]"))?.focus();
          }}
        />
      )}
    </>
  );
}
