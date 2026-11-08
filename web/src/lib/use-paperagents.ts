"use client";

import { useCallback } from "react";
import { api } from "./api";
import type { PaperAgent, PaperAgentsList } from "./types";
import { useLooked, type Looked } from "./use-looked";

// The PaperAgents, with what a page needs to make one
export function usePaperAgentsList(report: (error: unknown) => void, again: string): Looked<PaperAgentsList> {
  const look = useCallback(() => api.paperAgents(), []);

  return useLooked(look, report, again);
}

// One agent
export function usePaperAgent(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgent> {
  const look = useCallback(() => api.paperAgent(id), [id]);

  return useLooked(look, report, again);
}
