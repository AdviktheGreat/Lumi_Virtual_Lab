"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  BookOpenCheck,
  ChevronRight,
  Container,
  Database,
  FolderPlus,
  MessagesSquare,
  PanelLeftClose,
  Puzzle,
  Search as SearchIcon,
  Settings,
  SquarePen,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import { BrandMark } from "@/components/brand";
import { CampaignDialog } from "@/components/campaign-dialog";
import { MoveDialog } from "@/components/campaign-move";
import { ChatRow, LIST_ID } from "@/components/chat-row";
import { useChats } from "@/components/chats-provider";
import { useSettings } from "@/components/settings-provider";
import { useSetup } from "@/components/setup-provider";
import { useServer } from "@/components/server-provider";
import { useShell } from "@/components/app-shell";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { campaignAddress, groupByCampaign, type CampaignGroup } from "@/lib/campaigns";
import { inDays, matchingTitles, SEARCH_FROM } from "@/lib/history";
import type { ChatSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

// The pages, which are reached from the rail: the conversations first, and then the rest
const PAGES: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/", label: "Programs", icon: MessagesSquare },
  { href: "/data", label: "Data", icon: Database },
  { href: "/skills", label: "Skills", icon: Puzzle },
  { href: "/tools", label: "Tools", icon: Wrench },
  { href: "/papers", label: "PaperAgents", icon: BookOpenCheck },
];

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
          placeholder="Search programs"
          aria-label="Search programs"
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

function PageLinks() {
  const pathname = usePathname();

  return (
    <nav aria-label="Pages" className="flex flex-col items-center gap-1 px-1.5">
      <ul className="flex flex-col items-center gap-1">
        {PAGES.map(({ href, label, icon: Icon }) => {
          // The conversations are the page the home and every conversation belong to
          const active = href === "/" ? pathname === "/" || pathname === "/chat" || pathname === "/campaign" : pathname === href;

          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className="group flex w-14 flex-col items-center gap-1 rounded-xl py-1.5 text-[11px] font-medium text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring aria-[current=page]:text-foreground"
              >
                <span
                  className={cn(
                    "flex h-8 w-10 items-center justify-center rounded-xl transition-colors group-hover:bg-sidebar-accent",
                    active && "bg-highlight text-highlight-foreground ring-1 ring-inset ring-primary/20 group-hover:bg-highlight",
                  )}
                >
                  <Icon className="size-[18px]" aria-hidden />
                </span>
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

// A campaign in the list, with its programs under it, which can be hidden and shown. Its name is the way to its page.
function CampaignGroupView({
  group,
  open,
  onToggle,
  active,
  activeChat,
  onMove,
}: {
  group: CampaignGroup;
  open: boolean;
  onToggle: () => void;
  // Whether its page is the one that is open, and which program is
  active: boolean;
  activeChat: string | null;
  onMove: (chat: ChatSummary) => void;
}) {
  const { campaign, programs } = group;

  return (
    <li data-testid="campaign-group" data-campaign-id={campaign.id}>
      <div className="flex items-center gap-0.5">
        <Button
          variant="ghost"
          size="icon-xs"
          aria-expanded={open}
          aria-label={`${open ? "Hide" : "Show"} the programs of ${campaign.name}`}
          onClick={onToggle}
          className="shrink-0 text-muted-foreground"
        >
          <ChevronRight className={cn("transition-transform motion-reduce:transition-none", open && "rotate-90")} />
        </Button>
        <Link
          href={campaignAddress(campaign.id)}
          aria-current={active ? "page" : undefined}
          className={cn(
            "flex min-w-0 flex-1 items-center gap-2 rounded-xl py-1.5 pl-1.5 pr-2.5 text-sm font-medium outline-none transition-colors hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring",
            active && "bg-sidebar-accent text-sidebar-accent-foreground",
          )}
        >
          <span className="min-w-0 flex-1 truncate">{campaign.name}</span>
          <span className="shrink-0 text-xs font-normal tabular-nums text-muted-foreground" aria-label={`${programs.length} programs`}>
            {programs.length}
          </span>
        </Link>
      </div>
      {open && programs.length > 0 && (
        <ul className="ml-3.5 flex flex-col gap-0.5 border-l border-sidebar-border pl-1">
          {programs.map((chat) => (
            <li key={chat.id}>
              <ChatRow chat={chat} active={activeChat === chat.id} onMove={onMove} />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function ChatList() {
  const { chats, campaigns } = useChats();
  const pathname = usePathname();
  const activeId = useSearchParams().get("id");
  const [typed, setTyped] = useState("");
  // The campaigns that are hidden, by id, and the program that is being moved to another
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [moving, setMoving] = useState<ChatSummary | null>(null);

  if (chats === null) {
    return (
      <div className="flex flex-col gap-2 px-2.5 py-1" role="status" aria-busy="true" aria-label="Loading programs">
        {[0, 1, 2].map((row) => (
          <div key={row} className="flex flex-col gap-1.5">
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-3 w-1/3" />
          </div>
        ))}
      </div>
    );
  }
  if (chats.length === 0 && (campaigns ?? []).length === 0) {
    return <p className="px-2.5 py-1 text-sm text-muted-foreground">Programs you start are kept here.</p>;
  }

  // What was typed no longer counts once there are too few conversations to need it, which is when it is not shown
  const searchable = chats.length >= SEARCH_FROM;
  const searching = searchable && typed.trim() !== "";
  const shown = searchable ? matchingTitles(chats, typed) : chats;
  const { groups, alone } = groupByCampaign(shown, campaigns ?? []);
  // A search shows the programs it found, and so only the campaigns that have some
  const listed = searching ? groups.filter((group) => group.programs.length > 0) : groups;
  const activeChat = pathname === "/chat" ? activeId : null;

  return (
    <>
      {searchable && <Search typed={typed} onTyped={setTyped} />}
      {shown.length === 0 && (
        <p className="px-2.5 py-1 text-sm text-muted-foreground">No program has all of those words in its title.</p>
      )}
      {listed.length > 0 && (
        <div>
          <h2 className="px-2.5 pb-1 pt-3 text-xs font-medium text-muted-foreground">Campaigns</h2>
          <ul className="flex flex-col gap-0.5" aria-label="Campaigns">
            {listed.map((group) => (
              <CampaignGroupView
                key={group.campaign.id}
                group={group}
                open={searching || !hidden.has(group.campaign.id)}
                onToggle={() =>
                  setHidden((was) => {
                    const next = new Set(was);
                    if (!next.delete(group.campaign.id)) next.add(group.campaign.id);

                    return next;
                  })
                }
                active={pathname === "/campaign" && activeId === group.campaign.id}
                activeChat={activeChat}
                onMove={setMoving}
              />
            ))}
          </ul>
        </div>
      )}
      {inDays(alone).map((day) => (
        <div key={day.name}>
          <h2 className="px-2.5 pb-1 pt-3 text-xs font-medium text-muted-foreground">{day.name}</h2>
          <ul className="flex flex-col gap-0.5">
            {day.chats.map((chat) => (
              <li key={chat.id}>
                <ChatRow chat={chat} active={activeChat === chat.id} onMove={setMoving} />
              </li>
            ))}
          </ul>
        </div>
      ))}
      {moving !== null && (
        <MoveDialog
          chat={moving}
          onClose={() => setMoving(null)}
          onClosed={(event) => {
            // The program is where it was moved to, which is not where its row was, so the focus goes to its options there,
            // or to the list if it is not shown
            event.preventDefault();
            const row = document.querySelector<HTMLElement>(`[data-chat-id="${CSS.escape(moving.id)}"] button[aria-label="Program options"]`);
            (row ?? document.getElementById(LIST_ID))?.focus();
          }}
        />
      )}
    </>
  );
}

function Rail() {
  const settings = useSettings();
  const setup = useSetup();

  return (
    <div className="flex w-[4.5rem] shrink-0 flex-col items-center gap-3 border-r border-sidebar-border py-3">
      <Link
        href="/"
        aria-label="Lumi Virtual Lab"
        className="rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
      >
        <BrandMark className="size-11" />
      </Link>
      <PageLinks />
      <div className="mt-auto flex flex-col items-center gap-1">
        <Button variant="ghost" size="icon" aria-label="Settings" onClick={() => settings.open()} className="text-muted-foreground">
          <Settings className="size-[18px]" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label={setup.working ? "Set up, something is being built or fetched" : "Set up"}
          onClick={() => setup.open()}
          className="relative text-muted-foreground"
        >
          <Container className="size-[18px]" />
          {setup.working && (
            <span aria-hidden className="absolute right-1.5 top-1.5 size-2 animate-pulse rounded-full bg-primary motion-reduce:animate-none" />
          )}
        </Button>
        <ThemeToggle />
      </div>
    </div>
  );
}

function Panel() {
  const router = useRouter();
  const { toggleSidebar, sidebarShown } = useShell();
  const { server } = useServer();
  const { refresh } = useChats();
  const [creating, setCreating] = useState(false);

  return (
    <div className={cn("flex min-h-0 w-64 min-w-0 shrink flex-col border-r border-sidebar-border md:shrink-0", !sidebarShown && "md:hidden")}>
      <div className="flex h-14 shrink-0 items-center justify-between gap-2 px-4">
        <p className="min-w-0 truncate font-serif text-xl font-medium tracking-tight">Lumi Virtual Lab</p>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" onClick={toggleSidebar} aria-label="Hide the sidebar" className="max-md:hidden">
              <PanelLeftClose className="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">Hide the sidebar</TooltipContent>
        </Tooltip>
      </div>
      <div className="flex flex-col gap-1 px-3 pb-3 pt-2">
        <Button asChild className="w-full justify-start gap-2" size="lg">
          <Link href="/">
            <SquarePen className="size-4" />
            New program
          </Link>
        </Button>
        <Button variant="ghost" className="w-full justify-start gap-2 text-muted-foreground" onClick={() => setCreating(true)}>
          <FolderPlus className="size-4" />
          New campaign
        </Button>
      </div>
      <nav id={LIST_ID} tabIndex={-1} aria-label="Programs" className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 outline-none">
        <ChatList />
      </nav>
      {server.status === "ready" && (
        <p className="border-t border-sidebar-border px-4 py-2.5 text-xs text-muted-foreground">Lumi Virtual Lab v{server.version}</p>
      )}
      {creating && (
        <CampaignDialog
          campaign={null}
          onSave={async (kept) => {
            const made = await api.makeCampaign(kept);
            await refresh();
            router.push(campaignAddress(made.id));
          }}
          onClose={() => setCreating(false)}
        />
      )}
    </div>
  );
}

export function Sidebar() {
  return (
    <>
      <Rail />
      <Panel />
    </>
  );
}
