"use client";

import { useCallback } from "react";
import { api } from "./api";
import type { PaperRun, PapersList } from "./types";
import { useLooked, type Looked } from "./use-looked";

// The runs that read papers, with what a page needs to make one
export function usePapersList(report: (error: unknown) => void, again: string): Looked<PapersList> {
  const look = useCallback(() => api.papers(), []);

  return useLooked(look, report, again);
}

// One run, with each of its papers and what they share
export function usePaperRun(id: string, report: (error: unknown) => void, again: string): Looked<PaperRun> {
  const look = useCallback(() => api.paperRun(id), [id]);

  return useLooked(look, report, again);
}
