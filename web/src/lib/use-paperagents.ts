"use client";

import { useCallback } from "react";
import { api } from "./api";
import type {
  PaperAgent,
  PaperAgentData,
  PaperAgentEnvironment,
  PaperAgentGiven,
  PaperAgentReading,
  PaperAgentReference,
  PaperAgentRepository,
  PaperAgentsList,
  PaperAgentTools,
} from "./types";
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

// What there is of an agent's environment, looked at again when it may have changed: as the code is fetched, changed, or taken
// away, which is what it is built from, and as it is built
export function usePaperAgentEnvironment(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgentEnvironment> {
  const look = useCallback(() => api.paperAgentEnvironment(id), [id]);

  return useLooked(look, report, again);
}

// What there is of an agent's data, looked at again when it may have changed: as the paper is read, which is what it names is found
// from, as the code is fetched, which may name it too, and as files are fetched
export function usePaperAgentData(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgentData> {
  const look = useCallback(() => api.paperAgentData(id), [id]);

  return useLooked(look, report, again);
}

// What there is of the running of an agent's tutorials, looked at again when it may have changed: as the code, the environment, or
// the data is changed, which is what they are run with, and as they are run
export function usePaperAgentReference(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgentReference> {
  const look = useCallback(() => api.paperAgentReference(id), [id]);

  return useLooked(look, report, again);
}

// What there is of the making of an agent's tools, looked at again when it may have changed: as the tutorials are run or taken away,
// which is what the tools are made from, and as the tools are made
export function usePaperAgentTools(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgentTools> {
  const look = useCallback(() => api.paperAgentTools(id), [id]);

  return useLooked(look, report, again);
}

export function usePaperAgentGiven(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgentGiven> {
  const look = useCallback(() => api.paperAgentGiven(id), [id]);

  return useLooked(look, report, again);
}
