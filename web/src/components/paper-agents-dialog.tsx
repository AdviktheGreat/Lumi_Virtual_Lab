"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { papersButtonText } from "@/lib/paper-choice";
import type { PaperAgent } from "@/lib/types";

// What shows how many PaperAgents a conversation that is begun here has, beside the model, and opens the choice
export function PaperAgentsButton({ count, disabled, onClick }: { count: number; disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      data-testid="papers-button"
      disabled={disabled}
      onClick={onClick}
      title="Choose the PaperAgents that this program has"
      className="-mx-1 inline-flex shrink-0 items-center gap-1 rounded px-1 py-0.5 outline-none transition-colors enabled:hover:bg-accent enabled:hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span>{papersButtonText(count)}</span>
    </button>
  );
}

// The PaperAgents a conversation is to begin with are chosen, from those it would have, and what is chosen is given to onDone
export function PaperAgentsDialog({
  agents,
  had,
  onDone,
  onClose,
}: {
  agents: readonly PaperAgent[];
  // The ids of those it would have now
  had: readonly string[];
  onDone: (chosen: string[]) => void;
  onClose: () => void;
}) {
  const [picked, setPicked] = useState<ReadonlySet<string>>(() => new Set(had));

  function pick(id: string, on: boolean) {
    setPicked((was) => {
      const next = new Set(was);
      if (on) next.add(id);
      else next.delete(id);

      return next;
    });
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg" data-testid="papers-dialog">
        <DialogHeader>
          <DialogTitle>Choose the PaperAgents</DialogTitle>
          <DialogDescription>
            A program that has an agent is given the tools that read its paper and, where code runs, those that run its code, and a scientist who speaks
            for the paper is on its team. A program keeps the agents it begins with.
          </DialogDescription>
        </DialogHeader>
        {agents.length === 0 ? (
          <p role="status" className="text-sm text-muted-foreground">
            There are no PaperAgents yet. They are made on the{" "}
            <Link href="/papers" className="underline underline-offset-2">
              PaperAgents page
            </Link>
            .
          </p>
        ) : (
          <ul aria-label="PaperAgents" className="-mx-1 flex max-h-72 flex-col gap-1 overflow-y-auto px-1">
            {agents.map((agent) => (
              <li key={agent.id} data-testid="paper-choice" data-id={agent.id}>
                <label className="flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-1.5 hover:bg-accent has-[:focus-visible]:bg-accent">
                  <Checkbox
                    checked={picked.has(agent.id)}
                    onChange={(event) => pick(agent.id, event.target.checked)}
                    aria-label={agent.title}
                    className="mt-1"
                  />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
                      <span className="break-words">{agent.title}</span>
                      {agent.given && <Badge variant="outline">Given to conversations</Badge>}
                    </span>
                    <span className="break-words text-xs text-muted-foreground">
                      {agent.steps.reading === "done" ? (agent.seat ?? "") : "Its paper has not been read, so it can say little of it."}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        <DialogFooter className="sm:justify-between">
          <Button variant="ghost" onClick={() => setPicked(new Set(agents.filter((agent) => agent.given).map((agent) => agent.id)))} disabled={agents.length === 0}>
            Choose those given to conversations
          </Button>
          <div className="flex flex-col-reverse gap-2 sm:flex-row">
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={() => onDone(agents.filter((agent) => picked.has(agent.id)).map((agent) => agent.id))} disabled={agents.length === 0}>
              Use these
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
