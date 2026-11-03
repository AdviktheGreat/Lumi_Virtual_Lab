"use client";

import { api } from "./api";
import type { Own } from "./types";
import { useKept } from "./use-kept";
import type { Loaded } from "./use-settings-data";

export interface OwnState {
  own: Loaded<Own>;
  // What a change gives back, which is all of what was given as it now is, and is shown from then on
  set: (own: Own) => void;
  // Looks again, as is done when the first look failed. What is shown stays until the answer comes.
  reload: () => void;
}

// What the person gave the lab. It is looked at when the page opens, and as the page is shown again, since a file that
// was pointed to may have been moved or deleted while it was away.
export function useOwn(report: (error: unknown) => void): OwnState {
  const { value, set, reload } = useKept(api.own, report);

  return { own: value, set, reload };
}
