"use client";

import { useCallback } from "react";
import { api, graphQuery } from "./api";
import { problemOf, type Problem } from "./errors";
import type {
  PaperAgent,
  PaperAgentChecks,
  PaperAgentClaims,
  PaperAgentData,
  PaperAgentEnvironment,
  PaperAgentGiven,
  PaperAgentHealth,
  PaperAgentExport,
  PaperAgentGraph,
  PaperAgentLibrary,
  PaperAgentOneGo,
  PaperAgentReading,
  PaperAgentReference,
  PaperAgentReimplementation,
  PaperAgentRepository,
  PaperAgentsList,
  PaperAgentTools,
  GraphQuery,
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

// What there is of the checks of an agent's tools, looked at again when it may have changed: as the tools are made or taken away, which
// is what is checked, and as they are checked
export function usePaperAgentChecks(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgentChecks> {
  const look = useCallback(() => api.paperAgentChecks(id), [id]);

  return useLooked(look, report, again);
}

// What there is of the trying of an agent's claims, and where each first parts from the paper, looked at together and again when it may have
// changed: as the tutorials are run or taken away, which is what the claims are held to, as the paper is read, and as the claims are tried
export function usePaperAgentClaims(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgentClaims> {
  const look = useCallback(async () => {
    const [reproduction, divergence, variants] = await Promise.all([
      api.paperAgentReproduction(id),
      api.paperAgentDivergence(id),
      api.paperAgentVariants(id),
    ]);

    return { reproduction, divergence, variants };
  }, [id]);

  return useLooked(look, report, again);
}

// What there is of writing a function from an agent's paper and checking it, looked at again when it may have changed: as the paper is
// read, which is what it is written from and checked against, as tools of the authors' code are made, which it is not written beside,
// and as it is written and checked
export function usePaperAgentReimplementation(
  id: string,
  report: (error: unknown) => void,
  again: string,
): Looked<PaperAgentReimplementation> {
  const look = useCallback(() => api.paperAgentReimplementation(id), [id]);

  return useLooked(look, report, again);
}

// How making an agent in one go stands, looked at again as it goes from step to step and as the steps it starts end
export function usePaperAgentOneGo(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgentOneGo> {
  const look = useCallback(() => api.paperAgentOneGo(id), [id]);

  return useLooked(look, report, again);
}

export function usePaperAgentGiven(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgentGiven> {
  const look = useCallback(() => api.paperAgentGiven(id), [id]);

  return useLooked(look, report, again);
}

// How an agent was found when it was last looked at, its schedule, and a newer version of its code that is proposed, looked at again
// as it is looked at, and as what it is made of changes
export function usePaperAgentHealth(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgentHealth> {
  const look = useCallback(() => api.paperAgentHealth(id), [id]);

  return useLooked(look, report, again);
}

export function usePaperAgentExport(id: string, report: (error: unknown) => void, again: string): Looked<PaperAgentExport> {
  const look = useCallback(() => api.paperAgentExport(id), [id]);

  return useLooked(look, report, again);
}

export function usePaperAgentLibrary(report: (error: unknown) => void, again: string): Looked<PaperAgentLibrary> {
  const look = useCallback(() => api.paperAgentLibrary(), []);

  return useLooked(look, report, again);
}

// The graph with the query that it is the answer to, or why it could not be had, so that a page never shows the graph of one query
// under another, which it would while the next is looked at, or after the next failed
export interface AnsweredGraph {
  key: string;
  graph: PaperAgentGraph | null;
  problem: Problem | null;
}

// How the papers of the agents relate, as it is asked for. A query is a look of its own, and is looked at again as the steps that
// make what it is made from end
export function usePaperAgentGraph(query: GraphQuery, report: (error: unknown) => void, again: string): Looked<AnsweredGraph> {
  const { agent, kind, about } = query;
  const look = useCallback(async (): Promise<AnsweredGraph> => {
    const asked = { agent, kind, about };
    try {
      return { key: graphQuery(asked), graph: await api.paperAgentGraph(asked), problem: null };
    } catch (error) {
      report(error);

      return { key: graphQuery(asked), graph: null, problem: problemOf(error) };
    }
  }, [agent, kind, about, report]);

  return useLooked(look, report, again);
}
