"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { promptChoices, type PromptChoice } from "./prompts";
import type { McpServer } from "./types";

// The prompts of MCP servers that can be written after a slash, which are read from the server each time a slash is first
// written, so that what a look at a server found since is there, and a person who never writes a slash does not have them read.
// They are the prompts of the servers named, or where none are, of those that are on for new conversations. Where they cannot
// be read there are none.
export function usePromptChoices(names: readonly string[] | null, wanted: boolean): PromptChoice[] {
  const [servers, setServers] = useState<McpServer[] | null>(null);

  useEffect(() => {
    if (!wanted) return;
    let current = true;
    api.mcp().then(
      (found) => {
        if (current) setServers(found);
      },
      () => undefined,
    );

    return () => {
      current = false;
    };
  }, [wanted]);

  return useMemo(() => promptChoices(servers, names), [servers, names]);
}
