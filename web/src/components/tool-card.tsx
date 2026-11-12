"use client";

import { useId, useState } from "react";
import { Check, ChevronDown, ExternalLink, Plus } from "lucide-react";
import { ServerSetup } from "@/components/mcp-setup";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { describeHolds, describeTransport } from "@/lib/mcp";
import { catalogNeeds, needsText, readiness, type Readiness } from "@/lib/tools-nexus";
import type { McpCatalogServer, McpChange, McpServer } from "@/lib/types";
import { cn } from "@/lib/utils";

export const CARD =
  "flex flex-col rounded-2xl border border-border bg-card transition-[border-color,box-shadow] focus-within:border-ring/60 hover:border-ring/60 hover:shadow-sm";

// The control of a tool the lab has: on, so that a new program is given it, or off. It is a switch, which says what it is by
// its words as well as by its colour.
export function ToolSwitch({ title, on, onTurn }: { title: string; on: boolean; onTurn: (enabled: boolean) => void }) {
  return (
    <Button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={`Give new programs ${title}`}
      variant={on ? "secondary" : "outline"}
      size="sm"
      className={cn("rounded-full px-3", on ? "text-foreground" : "text-muted-foreground")}
      onClick={() => onTurn(!on)}
    >
      {on && <Check aria-hidden />}
      {on ? "On" : "Off"}
    </Button>
  );
}

// Whether a tool can be used as it is, as a word, which is not told by its colour alone
export function ReadinessBadge({ readiness: state }: { readiness: Readiness }) {
  return (
    <Badge variant={state.tone === "ready" ? "secondary" : state.tone === "problem" ? "destructive" : "outline"} data-testid="tool-status">
      {state.label}
    </Badge>
  );
}

// The words of a card that say what it is for and what it takes to use, and then what else is to be said of it
export function CardText({ about, needs, children }: { about: string; needs: string; children?: React.ReactNode }) {
  return (
    <>
      <p className="break-words text-[13px] leading-5 text-muted-foreground">{about}</p>
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Needs:</span> {needs}
      </p>
      {children}
    </>
  );
}

// What opens and closes the part of a card where a tool is set up
export function SetUpButton({
  title,
  open,
  controls,
  needsSetUp,
  onToggle,
}: {
  title: string;
  open: boolean;
  controls: string;
  needsSetUp: boolean;
  onToggle: () => void;
}) {
  return (
    <Button type="button" variant="outline" size="sm" aria-expanded={open} aria-controls={controls} onClick={onToggle}>
      {needsSetUp ? "Set up" : "Manage"}
      <span className="sr-only"> {title}</span>
      <ChevronDown aria-hidden className={cn("transition-transform", open && "rotate-180")} />
    </Button>
  );
}

// A server the lab has, as a card: what it is for and what it takes, whether it can be used as it is, and whether a new
// program is given it. It opens to where it is set up: a key or a sign-in, and a look at whether it can be connected to.
export function ToolCard({
  server,
  onChange,
  onKeysChanged,
  onChecked,
  onSignOut,
  onRemove,
}: {
  server: McpServer;
  onChange: (change: McpChange) => void;
  onKeysChanged: () => void;
  onChecked: () => void;
  onSignOut: () => void;
  onRemove: (button: HTMLButtonElement) => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const state = readiness(server);
  const transport = describeTransport(server);
  const holds = server.holds === null ? null : describeHolds(server.holds);

  return (
    <li className={CARD} data-testid={`tool-${server.name}`}>
      <div className="flex flex-1 flex-col gap-1.5 px-4 pb-2 pt-4">
        <div className="flex items-start justify-between gap-2">
          <h3 className="break-words font-serif text-[17px] font-semibold leading-snug">{server.title}</h3>
          <ReadinessBadge readiness={state} />
        </div>
        <CardText about={[server.about, transport].filter(Boolean).join(". ")} needs={needsText(server)}>
          {(server.asks || server.auth === "oauth") && (
            <p className="flex flex-wrap gap-1.5">
              {server.asks && <Badge variant="outline">Asks before a call</Badge>}
              {server.auth === "oauth" && <Badge variant="outline">Signs in</Badge>}
            </p>
          )}
          {server.target !== null && <code className="truncate text-xs text-muted-foreground">{server.target}</code>}
          {holds !== null && (
            <p className="text-xs text-muted-foreground" data-testid={`tool-${server.name}-lists`}>
              <span className="font-medium text-foreground">Also lists:</span> {holds}
            </p>
          )}
        </CardText>
      </div>
      <div className="flex items-center justify-between gap-2 px-4 pb-3 pt-1">
        <span className="flex items-center gap-1.5">
          <SetUpButton title={server.title} open={open} controls={`${id}-setup`} needsSetUp={state.tone !== "ready"} onToggle={() => setOpen(!open)} />
          {!server.preset && (
            <Button type="button" variant="ghost" size="sm" onClick={(event) => onRemove(event.currentTarget)} aria-label={`Remove ${server.name}`}>
              Remove
            </Button>
          )}
        </span>
        <ToolSwitch title={server.title} on={server.enabled} onTurn={(enabled) => onChange({ enabled })} />
      </div>
      {open && (
        <div id={`${id}-setup`} className="flex flex-col gap-3 border-t border-border px-4 py-3" data-testid={`tool-${server.name}-setup`}>
          <ServerSetup server={server} onChange={onChange} onKeysChanged={onKeysChanged} onChecked={onChecked} onSignOut={onSignOut} />
        </div>
      )}
    </li>
  );
}

// The address a server is reached at, without the rest, which is where what the lead asks of it is sent
function hostOf(address: string): string {
  try {
    return new URL(address).host;
  } catch {
    return address;
  }
}

// A server of the catalog that is not set up, as a card: what it is for, who runs it, and what it takes, with the button that
// adds it
export function CatalogCard({ server, busy, onAdd }: { server: McpCatalogServer; busy: boolean; onAdd: () => void }) {
  return (
    <li className={CARD} data-testid={`catalog-${server.name}`}>
      <div className="flex flex-1 flex-col gap-1.5 px-4 pb-2 pt-4">
        <span className="truncate text-xs text-muted-foreground" title={server.maker}>
          {server.maker}
        </span>
        <h3 className="break-words font-serif text-[17px] font-semibold leading-snug">{server.title}</h3>
        <CardText about={server.about} needs={catalogNeeds(server)}>
          {(server.asks || server.signs_in) && (
            <p className="flex flex-wrap gap-1.5">
              {server.asks && <Badge variant="outline">Asks before a call</Badge>}
              {server.signs_in && <Badge variant="outline">Signs in</Badge>}
            </p>
          )}
        </CardText>
        <p className="text-xs text-muted-foreground">
          Reached at <code>{hostOf(server.target)}</code>
        </p>
      </div>
      <div className="flex items-center justify-between gap-2 px-4 pb-3 pt-1">
        <a
          href={server.site}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 rounded text-xs text-muted-foreground underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          About<span className="sr-only"> {server.title}</span>
          <ExternalLink aria-hidden className="size-3" />
        </a>
        <Button type="button" variant="outline" size="sm" className="rounded-full px-3" disabled={busy} aria-label={`Add ${server.title}`} onClick={onAdd}>
          <Plus aria-hidden />
          Add
        </Button>
      </div>
    </li>
  );
}
