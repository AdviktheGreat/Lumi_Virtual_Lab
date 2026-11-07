"use client";

import { useEffect, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { Given } from "@/components/given";
import { RemoveServer } from "@/components/mcp-add";
import { PageFrame } from "@/components/page-frame";
import { useServer } from "@/components/server-provider";
import { CatalogCard, ToolCard } from "@/components/tool-card";
import { ToolsAdd } from "@/components/tools-add";
import { WebSearchCard } from "@/components/web-search-card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { catalogToAdd } from "@/lib/tools-nexus";
import type { McpCatalogServer, McpServer } from "@/lib/types";
import { useKept } from "@/lib/use-kept";
import { useMcpChanges } from "@/lib/use-mcp-changes";

const GRID = "grid gap-4 sm:grid-cols-2 lg:grid-cols-3";

// What is said of a server that was added from the catalog, which is on, and which is signed in to where a sign-in is asked for
function addedSaid(server: McpCatalogServer): string {
  const on = `Added ${server.title}. It is on, so programs begun from now on are given its tools.`;

  return server.signs_in ? `${on} It asks you to sign in when you send the first message of a program that has it.` : on;
}

// The tools the lab can call besides those it has built in: the services of the library, which are set up with a key or a
// sign-in, the search of the web, and the servers of others, which are added from a short catalog or by describing them. A
// program begins with the tools that are on.
export function ToolsView() {
  const { report } = useServer();
  const servers = useKept(api.mcp, report);
  const tools = useKept(api.tools, report);
  const keys = useKept(api.keys, report);
  const catalog = useKept(api.mcpCatalog, report);
  const changes = useMcpChanges(servers.set, report);
  const [adding, setAdding] = useState<string | null>(null);
  const [removing, setRemoving] = useState<McpServer | null>(null);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [describing, setDescribing] = useState(false);
  // The button a question was asked from, and the server that was just added, which the focus goes to, since the card of the
  // catalog that was added is gone
  const asker = useRef<HTMLButtonElement | null>(null);
  const addButton = useRef<HTMLButtonElement | null>(null);
  const added = useRef<string | null>(null);
  // The button that opened the dialog that describes a server, and the server it saved, which has the focus once it closes
  const describer = useRef<HTMLButtonElement | null>(null);
  const saved = useRef<string | null>(null);

  useEffect(() => {
    if (added.current === null || servers.value.kind !== "ready") return;
    const card = document.querySelector<HTMLElement>(`[data-testid="tool-${added.current}"] button`);
    if (card === null) return;
    card.focus();
    added.current = null;
  }, [servers.value]);

  function markAdded(name: string) {
    if (catalog.value.kind !== "ready") return;
    catalog.set(catalog.value.value.map((server) => (server.name === name ? { ...server, added: true } : server)));
  }

  async function add(server: McpCatalogServer) {
    if (adding !== null) return;
    setAdding(server.name);
    changes.setProblem(null);
    changes.setDone(null);
    try {
      const kept = await api.addCatalogServer(server.name);
      added.current = server.name;
      servers.set(kept);
      markAdded(server.name);
      changes.setDone(addedSaid(server));
    } catch (error) {
      report(error);
      changes.setProblem(describeError(error));
      // It may have been added by another page since the catalog was looked at
      servers.reload();
      catalog.reload();
    } finally {
      setAdding(null);
    }
  }

  function describe(button: HTMLButtonElement) {
    describer.current = button;
    setDescribing(true);
  }

  function describingClosed(event: Event) {
    event.preventDefault();
    const card = saved.current === null ? null : document.querySelector<HTMLElement>(`[data-testid="tool-${saved.current}"] button`);
    saved.current = null;
    (card ?? describer.current ?? addButton.current)?.focus();
  }

  function describedServer(kept: McpServer[], name: string) {
    saved.current = name;
    servers.set(kept);
    catalog.reload();
    changes.setProblem(null);
    changes.setDone(`Saved ${name}. It is on, so programs begun from now on are given its tools.`);
    setDescribing(false);
  }

  const shown = servers.value.kind === "ready" ? changes.shown(servers.value.value) : [];

  return (
    <PageFrame
      wide
      title="Tools Nexus"
      intro="Services the lead can call for more than it has built in: papers, protein tools, the web, and public databases. A program begins with the tools that are on, and asks you in the program before a call that costs money or cannot be undone."
      action={
        <Button ref={addButton} onClick={(event) => describe(event.currentTarget)}>
          <Plus aria-hidden />
          Add MCP server
        </Button>
      }
    >
      <section aria-labelledby="tools-have" className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <h2 id="tools-have" className="font-serif text-xl font-medium tracking-tight">
            Your tools
          </h2>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Turn one on for the programs you start from now on, and set up what it needs. Each tool that is on adds to what every
            message costs, since the model is told what it does.
          </p>
        </div>
        {changes.problem && (
          <p role="alert" className="text-sm text-destructive">
            {changes.problem}
          </p>
        )}
        {changes.done && (
          <p role="status" className="text-sm text-muted-foreground" data-testid="tools-said">
            {changes.done}
          </p>
        )}
        {/* The cards of a row are as tall as the tallest, until one is opened, which would make the rest tall to match */}
        <ul aria-label="Your tools" className={`${GRID} has-[[aria-expanded=true]]:items-start`}>
          <WebSearchCard
            tools={tools.value}
            keys={keys.value}
            onToolsChanged={tools.set}
            onKeysChanged={keys.set}
            onRetry={() => {
              tools.reload();
              keys.reload();
            }}
          />
          {servers.value.kind === "ready" ? (
            shown.map((server) => (
              <ToolCard
                key={server.name}
                server={server}
                onChange={(what) => changes.change(server.name, what)}
                onKeysChanged={() => void changes.refresh()}
                onSignOut={() => void changes.signOut(server)}
                onRemove={(button) => {
                  asker.current = button;
                  setRemoving(server);
                  setRemoveOpen(true);
                }}
              />
            ))
          ) : (
            <li className="sm:col-span-1 lg:col-span-2">
              <Given given={servers.value} label="Looking at the tools" failure="The tools could not be looked at." onRetry={servers.reload}>
                {() => null}
              </Given>
            </li>
          )}
        </ul>
      </section>

      <section aria-labelledby="tools-more" className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <h2 id="tools-more" className="font-serif text-xl font-medium tracking-tight">
            More tools
          </h2>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Servers that others run, for looking things up in public databases and documentation. Adding one turns it on. What the lead
            asks of a server is sent to it, at the address on its card.
          </p>
        </div>
        <Given given={catalog.value} label="Looking at the catalog" failure="The catalog could not be looked at." onRetry={catalog.reload}>
          {(entries) => {
            const groups = catalogToAdd(entries);

            return (
              <div className="flex flex-col gap-6">
                {groups.length === 0 && (
                  <p className="text-sm text-muted-foreground" data-testid="catalog-empty">
                    You have added every server of the catalog.
                  </p>
                )}
                {groups.map((group) => (
                  <div key={group.group} className="flex flex-col gap-3">
                    <h3 className="text-sm font-medium text-muted-foreground">{group.group}</h3>
                    <ul aria-label={group.group} className={GRID}>
                      {group.servers.map((server) => (
                        <CatalogCard key={server.name} server={server} busy={adding !== null} onAdd={() => void add(server)} />
                      ))}
                    </ul>
                  </div>
                ))}
                <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-dashed border-border px-4 py-3">
                  <p className="min-w-0 flex-1 text-sm text-muted-foreground">
                    A server that is not here can be added by its address, or by the program that starts it.
                  </p>
                  <Button type="button" variant="outline" size="sm" onClick={(event) => describe(event.currentTarget)}>
                    <Plus aria-hidden />
                    Add any MCP server
                  </Button>
                </div>
              </div>
            );
          }}
        </Given>
      </section>

      {servers.value.kind === "ready" && (
        <>
          <ToolsAdd
            open={describing}
            onOpenChange={setDescribing}
            servers={servers.value.value}
            onSaved={describedServer}
            onCloseAutoFocus={describingClosed}
          />
          <RemoveServer
            server={removing}
            open={removeOpen}
            onOpenChange={setRemoveOpen}
            onRemove={(server) =>
              void changes.remove(server).then(() => {
                catalog.reload();
              })
            }
            returnFocus={() => (asker.current?.isConnected ? asker.current : addButton.current)}
          />
        </>
      )}
    </PageFrame>
  );
}
