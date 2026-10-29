"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Ellipsis, Pencil, Trash2 } from "lucide-react";
import { useChats } from "@/components/chats-provider";
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
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { timeAgo } from "@/lib/format";
import { capTitle, cleanTitle, UNTITLED } from "@/lib/history";
import type { ChatSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const WORKING = new Set(["running", "pausing", "paused", "stopping"]);

// What the focus goes to when the conversation it was on is deleted, which is the list, to be gone down from the top
export const LIST_ID = "conversations";

function ChatLink({ chat, active }: { chat: ChatSummary; active: boolean }) {
  const working = WORKING.has(chat.state);

  return (
    <Link
      href={`/chat?id=${encodeURIComponent(chat.id)}`}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex flex-col gap-0.5 rounded-xl py-2 pl-2.5 pr-9 text-sm outline-none transition-colors hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring",
        active && "bg-sidebar-accent text-sidebar-accent-foreground",
      )}
    >
      <span className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate font-medium">{chat.title || UNTITLED}</span>
        {working && (
          <span
            role="img"
            aria-label={chat.state === "paused" ? "Paused" : "Working"}
            className={cn("size-2 shrink-0 rounded-full bg-brand", chat.state !== "paused" && "animate-pulse")}
          />
        )}
        {chat.state === "interrupted" && (
          <span role="img" aria-label="Cut off" className="size-2 shrink-0 rounded-full bg-warning" />
        )}
      </span>
      <span className="truncate text-xs text-muted-foreground">{timeAgo(chat.updated_at ?? chat.created_at)}</span>
    </Link>
  );
}

// The title being changed where it is read. It is kept when Enter is pressed or the focus goes elsewhere, and given up
// with Escape; a title with nothing in it, or the one it had, changes nothing.
function RenameForm({ chat, onDone }: { chat: ChatSummary; onDone: (focusBack: boolean) => void }) {
  const { refresh } = useChats();
  const { report } = useServer();
  const [typed, setTyped] = useState(chat.title);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);

  async function keep(focusBack: boolean) {
    // Enter has it being kept, and the click that follows it, before it is done, is not a second change
    if (saving) return;
    const title = cleanTitle(typed);
    if (title === null || title === chat.title) {
      onDone(focusBack);

      return;
    }
    setSaving(true);
    setProblem(null);
    try {
      await api.renameChat(chat.id, title);
      await refresh();
      onDone(focusBack);
    } catch (error) {
      report(error);
      setProblem(describeError(error));
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void keep(true);
      }}
      className="flex flex-col gap-1 px-1 py-1.5"
    >
      <Input
        ref={input}
        value={typed}
        onChange={(event) => setTyped(capTitle(event.target.value))}
        onBlur={() => void keep(false)}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          // This is the Escape that gives up the new title, and not the one that closes the drawer it is in
          event.preventDefault();
          onDone(true);
        }}
        // Not disabled, which would take the focus from it, and with it the Enter that tries again
        readOnly={saving}
        aria-label="Conversation title"
        aria-invalid={problem !== null}
        autoComplete="off"
      />
      {problem && (
        <p role="alert" className="px-0.5 text-xs text-destructive">
          {problem}
        </p>
      )}
    </form>
  );
}

function DeleteDialog({
  chat,
  active,
  open,
  onOpenChange,
  onClosed,
}: {
  chat: ChatSummary;
  active: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Where the focus goes when it is closed, which is up to the row, because the menu that opened it is gone by then, and
  // which is not the row if it is the one that was deleted
  onClosed: () => void;
}) {
  const router = useRouter();
  const { refresh } = useChats();
  const { report } = useServer();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  function change(next: boolean) {
    // It stays until the server has answered, so that what it said is not lost
    if (busy) return;
    if (!next) setProblem(null);
    onOpenChange(next);
  }

  async function remove() {
    setBusy(true);
    setProblem(null);
    try {
      await api.deleteChat(chat.id);
    } catch (error) {
      // One that is gone already is what was wanted
      if (!(error instanceof ApiError && error.status === 404)) {
        report(error);
        setProblem(describeError(error));
        setBusy(false);

        return;
      }
    }
    setBusy(false);
    onOpenChange(false);
    if (active) router.push("/");
    await refresh();
  }

  return (
    <AlertDialog open={open} onOpenChange={change}>
      <AlertDialogContent
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          onClosed();
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
          <AlertDialogDescription>
            “{chat.title || UNTITLED}” is removed with its messages, its files, and what it ran. This cannot be undone.
            {WORKING.has(chat.state) && " It is at work now, and that is stopped."}
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

// A conversation in the list: where it is opened, and what can be done to it
export function ChatRow({ chat, active }: { chat: ChatSummary; active: boolean }) {
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const focusBack = useRef(false);
  // Set when the menu is closed by choosing from it, which moves the focus on to what was chosen
  const chose = useRef(false);

  useEffect(() => {
    if (renaming || !focusBack.current) return;
    focusBack.current = false;
    trigger.current?.focus();
  }, [renaming]);

  return (
    <div data-chat-id={chat.id} className="group/row relative">
      {renaming ? (
        <RenameForm
          chat={chat}
          onDone={(back) => {
            focusBack.current = back;
            setRenaming(false);
          }}
        />
      ) : (
        <ChatLink chat={chat} active={active} />
      )}
      {/* Not modal, because a modal one holds the focus until it is gone, and what it is closed for takes the focus */}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            ref={trigger}
            variant="ghost"
            size="icon-xs"
            aria-label="Conversation options"
            className={cn(
              "absolute right-1.5 top-2 opacity-0 transition-opacity group-focus-within/row:opacity-100 group-hover/row:opacity-100 data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100",
              // Kept where it is while the menu closes, because a menu whose button moves under it is left, which takes the
              // focus from the title
              renaming && "invisible",
            )}
          >
            <Ellipsis />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          className="w-40"
          onCloseAutoFocus={(event) => {
            if (!chose.current) return;
            chose.current = false;
            event.preventDefault();
          }}
        >
          <DropdownMenuItem
            onSelect={() => {
              chose.current = true;
              setRenaming(true);
            }}
          >
            <Pencil />
            Rename
          </DropdownMenuItem>
          <DropdownMenuItem
            variant="destructive"
            onSelect={() => {
              chose.current = true;
              setDeleting(true);
            }}
          >
            <Trash2 />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <DeleteDialog
        chat={chat}
        active={active}
        open={deleting}
        onOpenChange={setDeleting}
        onClosed={() => (trigger.current ?? document.getElementById(LIST_ID))?.focus()}
      />
    </div>
  );
}
