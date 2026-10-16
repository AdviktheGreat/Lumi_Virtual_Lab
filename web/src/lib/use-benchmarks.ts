"use client";

import { useCallback } from "react";
import { api } from "./api";
import type { BenchmarkRun, BenchmarksList } from "./types";
import { useLooked, type Looked } from "./use-looked";

// The runs that answer benchmarks, with what a page needs to make one
export function useBenchmarksList(report: (error: unknown) => void, again: string): Looked<BenchmarksList> {
  const look = useCallback(() => api.benchmarks(), []);

  return useLooked(look, report, again);
}

// One run, with how each of its questions was answered
export function useBenchmarkRun(id: string, report: (error: unknown) => void, again: string): Looked<BenchmarkRun> {
  const look = useCallback(() => api.benchmarkRun(id), [id]);

  return useLooked(look, report, again);
}
