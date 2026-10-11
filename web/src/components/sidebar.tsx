"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { PanelLeftClose, Search as SearchIcon, SquarePen, X } from "lucide-react";
import { Brand } from "@/components/brand";
import { ChatRow } from "@/components/chat-row";
import { useChats } from "@/components/chats-provider";
import { useServer } from "@/components/server-provider";
import { useShell } from "@/components/app-shell";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { inDays, matchingTitles, SEARCH_FROM } from "@/lib/history";

function Search({ typed, onTyped }: { typed: string; onTyped: (typed: string) => void }) {
  return (
    <div className="sticky top-0 z-10 bg-sidebar pb-1 pt-0.5">
      <div className="relative">
        <SearchIcon aria-hidden className="pointer-events-none absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
        <Input
          type="search"
          value={typed}
          onChange={(event) => onTyped(event.target.value)}
          onKeyDown={(event) => {
            // Escape empties the search, and closes the drawer it is in only when there is nothing to empty
            if (event.key !== "Escape" || typed === "") return;
            event.preventDefault();
            onTyped("");
          }}
          placeholder="Search conversations"
          aria-label="Search conversations"
          autoComplete="off"
          className="pl-8 pr-8 [&::-webkit-search-cancel-button]:appearance-none"
        />
        {typed !== "" && (
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label="Clear the search"
            onClick={() => onTyped("")}
            className="absolute right-1 top-1"
          >
            <X />
          </Button>
        )}
      </div>
    </div>
  );
}

function ChatList() {
  const { chats } = useChats();
  const pathname = usePathname();
  const activeId = useSearchParams().get("id");
  const [typed, setTyped] = useState("");

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

  // What was typed no longer counts once there are too few conversations to need it, which is when it is not shown
  const searchable = chats.length >= SEARCH_FROM;
  const shown = searchable ? matchingTitles(chats, typed) : chats;

  return (
    <>
      {searchable && <Search typed={typed} onTyped={setTyped} />}
      {shown.length === 0 && (
        <p className="px-2.5 py-1 text-sm text-muted-foreground">No conversation has all of those words in its title.</p>
      )}
      {inDays(shown).map((day) => (
        <div key={day.name}>
          <h2 className="px-2.5 pb-1 pt-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">{day.name}</h2>
          <ul className="flex flex-col gap-0.5">
            {day.chats.map((chat) => (
              <li key={chat.id}>
                <ChatRow chat={chat} active={pathname === "/chat" && activeId === chat.id} />
              </li>
            ))}
          </ul>
        </div>
      ))}
    </>
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
        <ChatList />
      </nav>
      <div className="flex items-center justify-between border-t border-sidebar-border px-3 py-2">
        <ThemeToggle />
        {server.status === "ready" && <span className="text-xs text-muted-foreground">v{server.version}</span>}
      </div>
    </>
  );
}
