"use client";

import { useCallback } from "react";
import { api } from "./api";
import type { Project, ProjectsList } from "./types";
import { useLooked, type Looked } from "./use-looked";

// The projects, with what a page needs to make one
export function useProjectsList(report: (error: unknown) => void, again: string): Looked<ProjectsList> {
  const look = useCallback(() => api.projects(), []);

  return useLooked(look, report, again);
}

// One project, with its team, plan, rounds, findings, and steps
export function useProject(id: string, report: (error: unknown) => void, again: string): Looked<Project> {
  const look = useCallback(() => api.project(id), [id]);

  return useLooked(look, report, again);
}
