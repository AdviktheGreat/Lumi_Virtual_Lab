"use client";

import { api } from "./api";
import type { SkillLibrary } from "./types";
import { useKept } from "./use-kept";
import type { Loaded } from "./use-settings-data";

export interface SkillLibraryState {
  library: Loaded<SkillLibrary>;
  // What a change gives back, which is the library as it now is, and is shown from then on
  set: (library: SkillLibrary) => void;
  reload: () => void;
}

// The skills that come with the lab to be put in, and which of them have been, looked at when the page opens and as it is
// shown again, since a skill may have been put in or deleted from another page or another tool while it was away
export function useSkillLibrary(report: (error: unknown) => void): SkillLibraryState {
  const { value, set, reload } = useKept(api.skillLibrary, report);

  return { library: value, set, reload };
}
