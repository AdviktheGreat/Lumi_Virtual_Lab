"use client";

import { useId, useRef, useState } from "react";
import { Plug } from "lucide-react";
import { AddServer, RemoveServer } from "@/components/mcp-add";
import { ServerSetup } from "@/components/mcp-setup";
import { Aside, Section } from "@/components/settings-fields";
import { useServer } from "@/components/server-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { describeError } from "@/lib/errors";
import { describeTransport, howManyOn } from "@/lib/mcp";
import type { McpChange, McpServer } from "@/lib/types";
import { useMcpChanges } from "@/lib/use-mcp-changes";
import type { Loaded } from "@/lib/use-settings-data";

function ServerRow({
  server,
  onChange,
  onKeysChanged,
  onRemove,
  onSignOut,
}: {
  server: McpServer;
  onChange: (change: McpChange) => void;
  onKeysChanged: () => void;
  onRemove: (button: HTMLButtonElement) => void;
  onSignOut: () => void;
}) {
  const id = useId();
  const transport = describeTransport(server);

  return (
    <li className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid={`mcp-${server.name}`}>
      <div className="flex items-start gap-2.5">
        <Checkbox
          id={`${id}-on`}
          checked={server.enabled}
          onChange={(event) => onChange({ enabled: event.target.checked })}
          aria-describedby={`${id}-about`}
          className="mt-0.5"
        />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <label htmlFor={`${id}-on`} className="text-sm font-medium">
              {server.title}
            </label>
            {server.title !== server.name && <code className="text-xs text-muted-foreground">{server.name}</code>}
            {server.asks && <Badge variant="outline">Asks before a call</Badge>}
            {server.auth === "oauth" && <Badge variant="outline">Signs in</Badge>}
          </div>
          <p id={`${id}-about`} className="text-xs text-muted-foreground">
            {[server.about, transport].filter(Boolean).join(". ")}
          </p>
          {server.target !== null && <code className="truncate text-xs text-muted-foreground">{server.target}</code>}
        </div>
        {!server.preset && (
          <Button type="button" variant="ghost" size="xs" onClick={(event) => onRemove(event.currentTarget)} aria-label={`Remove ${server.name}`}>
            Remove
          </Button>
        )}
      </div>
      <ServerSetup server={server} onChange={onChange} onKeysChanged={onKeysChanged} onSignOut={onSignOut} inset />
    </li>
  );
}

// The MCP servers whose tools the lead can be given. Each is kept as it is chosen, as the tools are, and a conversation is
// given the servers that are on when it begins.
export function McpSection({ servers, onChanged }: { servers: Loaded<McpServer[]>; onChanged: (servers: McpServer[]) => void }) {
  const { report } = useServer();
  const changes = useMcpChanges(onChanged, report);
  const [removing, setRemoving] = useState<McpServer | null>(null);
  const [asking, setAsking] = useState(false);
  const asker = useRef<HTMLButtonElement | null>(null);
  const nameInput = useRef<HTMLInputElement | null>(null);

  const shown = servers.kind === "ready" ? changes.shown(servers.value) : [];

  return (
    <Section title="MCP servers">
      <Aside>
        <Plug className="mr-1.5 inline size-3.5 align-text-bottom" aria-hidden />
        An MCP server gives the lead more tools, such as other databases and services. A program is given the servers that
        are on when it begins, connects to them when you send its first message, and asks you in the program before a call
        that costs money or cannot be undone.
      </Aside>
      {servers.kind === "loading" && <p className="text-sm text-muted-foreground">Looking at the servers…</p>}
      {servers.kind === "failed" && (
        <p role="alert" className="text-sm text-destructive">
          {describeError(servers.error)}
        </p>
      )}
      {servers.kind === "ready" && (
        <>
          <p role="status" className="text-sm text-muted-foreground" data-testid="mcp-count">
            {howManyOn(shown)}
          </p>
          {changes.problem && (
            <p role="alert" className="text-xs text-destructive">
              {changes.problem}
            </p>
          )}
          {changes.done && (
            <p role="status" className="text-xs text-muted-foreground">
              {changes.done}
            </p>
          )}
          <ul aria-label="MCP servers" className="flex flex-col gap-3">
            {shown.map((server) => (
              <ServerRow
                key={server.name}
                server={server}
                onChange={(what) => changes.change(server.name, what)}
                onKeysChanged={() => void changes.refresh()}
                onSignOut={() => void changes.signOut(server)}
                onRemove={(button) => {
                  asker.current = button;
                  setRemoving(server);
                  setAsking(true);
                }}
              />
            ))}
          </ul>
          <AddServer
            servers={servers.value}
            nameInput={nameInput}
            onSaved={(kept, name) => {
              onChanged(kept);
              changes.setProblem(null);
              changes.setDone(`Saved ${name}. It is on, so programs begun from now on are given its tools.`);
            }}
          />
          <RemoveServer
            server={removing}
            open={asking}
            onOpenChange={setAsking}
            onRemove={(server) => void changes.remove(server)}
            returnFocus={() => (asker.current?.isConnected ? asker.current : nameInput.current)}
          />
        </>
      )}
    </Section>
  );
}
