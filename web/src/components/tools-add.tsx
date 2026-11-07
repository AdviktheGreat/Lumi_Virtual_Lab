"use client";

import { useRef } from "react";
import { AddServer } from "@/components/mcp-add";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { McpServer } from "@/lib/types";

// Where a server that is not in the catalog is added, by describing it as a config of any other tool does
export function ToolsAdd({
  open,
  onOpenChange,
  servers,
  onSaved,
  onCloseAutoFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  servers: McpServer[];
  onSaved: (servers: McpServer[], name: string) => void;
  onCloseAutoFocus: (event: Event) => void;
}) {
  const nameInput = useRef<HTMLInputElement | null>(null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl" onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>Add an MCP server</DialogTitle>
          <DialogDescription>
            Any server that speaks MCP: one on the web, by its address, or a program to start on this computer. It is on once it is
            added.
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <AddServer servers={servers} nameInput={nameInput} onSaved={onSaved} heading={null} bare />
        </div>
      </DialogContent>
    </Dialog>
  );
}
