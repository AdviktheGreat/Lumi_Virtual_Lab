"use client";

import { useCallback } from "react";
import { api } from "./api";
import type { PaperAgent, PaperAgentReading, PaperAgentRepository, PaperAgentsList } from "./types";
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

// What has been read of an agent's paper, looked at again when what it is made from may have changed
export function usePaperAgentReading(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgentReading> {
  const look = useCallback(() => api.paperAgentReading(id), [id]);

  return useLooked(look, report, again);
}

// What there is of an agent's code, looked at again when it may have changed: as the paper is read, which is what the
// projects it points to are found from, and as the code is fetched
export function usePaperAgentRepository(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgentRepository> {
  const look = useCallback(() => api.paperAgentRepository(id), [id]);

  return useLooked(look, report, again);
}
