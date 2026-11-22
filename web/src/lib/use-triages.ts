"use client";

import { useCallback } from "react";
import { api } from "./api";
import type { Triage, TriagesList } from "./types";
import { useLooked, type Looked } from "./use-looked";

// The triages, with what a page needs to ask for one. They are looked at again when one is begun or ends.
export function useTriagesList(report: (error: unknown) => void, again: string): Looked<TriagesList> {
  const look = useCallback(() => api.triages(), []);

  return useLooked(look, report, again);
}

// One triage
export function useTriage(id: string, report: (error: unknown) => void, again: string): Looked<Triage> {
  const look = useCallback(() => api.triage(id), [id]);

  return useLooked(look, report, again);
}
