"use client";

import { api } from "./api";
import type { Skills } from "./types";
import { useKept } from "./use-kept";
import type { Loaded } from "./use-settings-data";

export interface SkillsState {
  skills: Loaded<Skills>;
  // What a change gives back, which is all the skills as they now are, and is shown from then on
  set: (skills: Skills) => void;
  reload: () => void;
}

// The skills there are, looked at when the page opens and as it is shown again, since a folder of skills may have been
// changed by another tool while it was away
export function useSkills(report: (error: unknown) => void): SkillsState {
  const { value, set, reload } = useKept(api.skills, report);

  return { skills: value, set, reload };
}
