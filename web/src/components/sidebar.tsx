"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { PanelLeftClose, SquarePen } from "lucide-react";
import { Brand } from "@/components/brand";
import { useChats } from "@/components/chats-provider";
import { useServer } from "@/components/server-provider";
import { useShell } from "@/components/app-shell";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { timeAgo } from "@/lib/format";
import type { ChatSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const WORKING = new Set(["running", "pausing", "paused", "stopping"]);

function ChatLink({ chat, active }: { chat: ChatSummary; active: boolean }) {
  const working = WORKING.has(chat.state);
  const title = chat.title || "New chat";

  return (
    <Link
      href={`/chat?id=${encodeURIComponent(chat.id)}`}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group flex flex-col gap-0.5 rounded-lg px-2.5 py-2 text-sm outline-none transition-colors hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring",
        active && "bg-sidebar-accent text-sidebar-accent-foreground",
      )}
    >
      <span className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate font-medium">{title}</span>
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

function ChatList() {
  const { chats } = useChats();
  const pathname = usePathname();
  const activeId = useSearchParams().get("id");

  if (chats === null) {
    return (
      <div className="flex flex-col gap-2 px-2.5 py-1" aria-busy="true" aria-label="Loading conversations">
        {[0, 1, 2].map((row) => (
          <div key={row} className="flex flex-col gap-1.5">
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-3 w-1/3" />
          </div>
        ))}
      </div>
    );
  }
  if (chats.length === 0) {
    return <p className="px-2.5 py-1 text-sm text-muted-foreground">Conversations you start are kept here.</p>;
  }

  return (
    <ul className="flex flex-col gap-0.5">
      {chats.map((chat) => (
        <li key={chat.id}>
          <ChatLink chat={chat} active={pathname === "/chat" && activeId === chat.id} />
        </li>
      ))}
    </ul>
  );
}

export function Sidebar() {
  const { toggleSidebar } = useShell();
  const { server } = useServer();

  return (
    <>
      <div className="flex h-12 shrink-0 items-center justify-between px-3">
        <Link href="/" aria-label="Virtual Lab" className="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring">
          <Brand />
        </Link>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" onClick={toggleSidebar} aria-label="Hide the sidebar" className="max-md:hidden">
              <PanelLeftClose className="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">Hide the sidebar</TooltipContent>
        </Tooltip>
      </div>
      <div className="px-3 pb-2">
        <Button asChild variant="outline" className="w-full justify-start">
          <Link href="/">
            <SquarePen className="size-4" />
            New chat
          </Link>
        </Button>
      </div>
      <nav aria-label="Conversations" className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        <h2 className="px-2.5 pb-1 pt-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Recent</h2>
        <ChatList />
      </nav>
      <div className="flex items-center justify-between border-t border-sidebar-border px-3 py-2">
        <ThemeToggle />
        {server.status === "ready" && <span className="text-xs text-muted-foreground">v{server.version}</span>}
      </div>
    </>
  );
}
