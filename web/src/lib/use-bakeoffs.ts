"use client";

import { useCallback } from "react";
import { api } from "./api";
import type { Bakeoff, BakeoffComparison, BakeoffsList, BakeoffTolerance } from "./types";
import { useLooked, type Looked } from "./use-looked";

// The bake-offs, with what a page needs to make one: the person's data, and what the server takes. It is looked at again when
// what finds, builds, or runs the methods of one goes on or ends.
export function useBakeoffsList(report: (error: unknown) => void, again: string): Looked<BakeoffsList> {
  const look = useCallback(() => api.bakeoffs(), []);

  return useLooked(look, report, again);
}

// One bake-off
export function useBakeoff(id: string, report: (error: unknown) => void, again: string): Looked<Bakeoff> {
  const look = useCallback(() => api.bakeoff(id), [id]);

  return useLooked(look, report, again);
}

// The methods of a bake-off side by side, which is made of what is kept and is looked at again when that may have changed, as the methods
// are built or run or the bake-off is said again
export function useBakeoffComparison(
  id: string,
  tolerance: Partial<BakeoffTolerance>,
  report: (error: unknown) => void,
  again: string,
): Looked<BakeoffComparison> {
  const { relative, absolute } = tolerance;
  const look = useCallback(() => api.bakeoffComparison(id, { relative, absolute }), [id, relative, absolute]);

  return useLooked(look, report, again);
}
