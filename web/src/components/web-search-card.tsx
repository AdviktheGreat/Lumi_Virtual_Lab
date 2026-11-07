"use client";

import { useEffect, useId, useRef, useState } from "react";
import { CARD, CardText, ReadinessBadge, SetUpButton, ToolSwitch } from "@/components/tool-card";
import { KeyForm } from "@/components/settings-keys";
import { useServer } from "@/components/server-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { webSearchRow } from "@/lib/keys";
import { engineSaid, webSearchState, webTools } from "@/lib/tools-nexus";
import { disabledWhen } from "@/lib/tools";
import type { KeyStatuses, ToolInfo } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

const TITLE = "Web search";
const ABOUT = "Search the web and read the pages it finds";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <li className={CARD} data-testid="tool-web_search">
      {children}
    </li>
  );
}

function WebSearchReady({
  tools,
  keys,
  onToolsChanged,
  onKeysChanged,
}: {
  tools: ToolInfo[];
  keys: KeyStatuses;
  onToolsChanged: (tools: ToolInfo[]) => void;
  onKeysChanged: (keys: KeyStatuses) => void;
}) {
  const { report } = useServer();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // What was chosen and is not yet kept, shown as it was chosen so that the switch answers at once, until every change has
  // been answered, and then what the server holds is what is shown, whether it kept it or not
  const [chosen, setChosen] = useState<boolean | null>(null);
  // The tools as the server last gave them, which each change is made to, one after another, so that two in quick succession
  // do not each start from what was shown before the other
  const latest = useRef<ToolInfo[]>(tools);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const waiting = useRef(0);

  useEffect(() => {
    if (waiting.current === 0) latest.current = tools;
  }, [tools]);

  function turn(enabled: boolean) {
    waiting.current += 1;
    setChosen(enabled);
    queue.current = queue.current.then(async () => {
      try {
        setProblem(null);
        const names = webTools(latest.current).map((tool) => tool.name);
        const kept = await api.saveTools(disabledWhen(latest.current, names, enabled));
        latest.current = kept;
        onToolsChanged(kept);
      } catch (error) {
        report(error);
        setProblem(describeError(error));
      } finally {
        waiting.current -= 1;
        if (waiting.current === 0) setChosen(null);
      }
    });
  }

  const state = webSearchState(tools, keys);
  const on = chosen ?? state.on;
  const row = webSearchRow(keys);

  return (
    <Shell>
      <div className="flex flex-1 flex-col gap-1.5 px-4 pb-2 pt-4">
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-serif text-[17px] font-semibold leading-snug">{TITLE}</h3>
          <ReadinessBadge readiness={{ tone: "ready", label: "Ready" }} />
        </div>
        <CardText about={ABOUT} needs="Nothing. A key for Exa is optional">
          <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <Badge variant="outline" data-testid="web-search-engine">
              {state.engine}
            </Badge>
            <span>{engineSaid(state.engine)}</span>
          </p>
        </CardText>
        {problem && (
          <p role="alert" className="text-xs text-destructive">
            {problem}
          </p>
        )}
      </div>
      <div className="flex items-center justify-between gap-2 px-4 pb-3 pt-1">
        <SetUpButton title={TITLE} open={open} controls={`${id}-setup`} needsSetUp={false} onToggle={() => setOpen(!open)} />
        <ToolSwitch title={TITLE} on={on} onTurn={turn} />
      </div>
      {open && (
        <div id={`${id}-setup`} className="flex flex-col gap-3 border-t border-border px-4 py-3" data-testid="tool-web_search-setup">
          <KeyForm row={row} keychain={keys.keychain} onChanged={onKeysChanged} />
        </div>
      )}
    </Shell>
  );
}

// The search of the web as a card, among the tools the lab has: it is one of the library's tools and not an MCP server, so
// that it is turned on and off with the other tools, and is given the key of Exa that makes it search with that engine
export function WebSearchCard({
  tools,
  keys,
  onToolsChanged,
  onKeysChanged,
  onRetry,
}: {
  tools: Loaded<ToolInfo[]>;
  keys: Loaded<KeyStatuses>;
  onToolsChanged: (tools: ToolInfo[]) => void;
  onKeysChanged: (keys: KeyStatuses) => void;
  onRetry: () => void;
}) {
  if (tools.kind === "failed" || keys.kind === "failed") {
    const failed = tools.kind === "failed" ? tools.error : keys.kind === "failed" ? keys.error : null;

    return (
      <Shell>
        <div className="flex flex-col items-start gap-2 px-4 py-4">
          <h3 className="font-serif text-[17px] font-semibold leading-snug">{TITLE}</h3>
          <p role="alert" className="text-xs text-destructive">
            It could not be looked at. {describeError(failed)}
          </p>
          <Button variant="outline" size="sm" onClick={onRetry}>
            Try again
          </Button>
        </div>
      </Shell>
    );
  }
  if (tools.kind === "loading" || keys.kind === "loading") {
    return (
      <Shell>
        <div className="flex flex-col gap-2 px-4 py-4" role="status" aria-busy="true" aria-label="Looking at web search">
          <h3 className="font-serif text-[17px] font-semibold leading-snug">{TITLE}</h3>
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      </Shell>
    );
  }

  return <WebSearchReady tools={tools.value} keys={keys.value} onToolsChanged={onToolsChanged} onKeysChanged={onKeysChanged} />;
}
