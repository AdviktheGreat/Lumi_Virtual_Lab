"use client";

import { useEffect, useState } from "react";
import { api } from "./api";
import { keysMissingFor } from "./settings";
import type { KeyStatuses, Models } from "./types";

// The keys that a model needs and that are not set, so that a person is told on the first page rather than by a message
// that cannot be answered. They are asked for when the page opens and again whenever `again` changes, as it does when the
// settings have been closed, since a key is given there. Nothing is said while the server has not answered, or if it
// cannot, and what an earlier answer said stands until a later one comes.
export function useMissingKeys(model: string | null, again: number): string[] {
  const [known, setKnown] = useState<{ models: Models; keys: KeyStatuses } | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    Promise.all([api.models(abort.signal), api.keys(abort.signal)]).then(
      ([models, keys]) => {
        if (!abort.signal.aborted) setKnown({ models, keys });
      },
      () => {
        // A message that needs a key is refused with a reason when it is sent
      },
    );

    return () => abort.abort();
  }, [again]);

  return known === null || model === null ? [] : keysMissingFor(model, known.models, known.keys);
}
