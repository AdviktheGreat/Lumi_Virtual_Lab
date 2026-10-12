"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { KeyStatuses, LibraryScientist, Models } from "./types";

export type Loaded<T> = { kind: "loading" } | { kind: "ready"; value: T } | { kind: "failed"; error: unknown };

const loading = { kind: "loading" } as const;

export interface SettingsData {
  models: Loaded<Models>;
  keys: Loaded<KeyStatuses>;
  scientists: Loaded<LibraryScientist[]>;
  // What a change to the keys or the scientists gives back, which is what is shown from then on
  setKeys: (keys: KeyStatuses) => void;
  setScientists: (scientists: LibraryScientist[]) => void;
  // Asks which models can be reached again, as they can be once a key is given or taken away. What was shown stays if the
  // server cannot say.
  refreshModels: () => Promise<void>;
}

// What the settings offer to choose from: the models, which keys are set, and the library's scientists. They are asked
// for once, when the settings open, and each is shown as it comes.
export function useSettingsData(): SettingsData {
  const [models, setModels] = useState<Loaded<Models>>(loading);
  const [keys, setKeys] = useState<Loaded<KeyStatuses>>(loading);
  const [scientists, setScientists] = useState<Loaded<LibraryScientist[]>>(loading);

  useEffect(() => {
    const abort = new AbortController();
    function load<T>(get: (signal: AbortSignal) => Promise<T>, show: (loaded: Loaded<T>) => void) {
      get(abort.signal).then(
        (value) => show({ kind: "ready", value }),
        (error: unknown) => {
          if (!abort.signal.aborted) show({ kind: "failed", error });
        },
      );
    }
    load(api.models, setModels);
    load(api.keys, setKeys);
    load(api.scientists, setScientists);

    return () => abort.abort();
  }, []);

  const refreshModels = useCallback(async () => {
    try {
      setModels({ kind: "ready", value: await api.models() });
    } catch {
      // The models are as they were shown
    }
  }, []);

  const showKeys = useCallback((value: KeyStatuses) => setKeys({ kind: "ready", value }), []);
  const showScientists = useCallback((value: LibraryScientist[]) => setScientists({ kind: "ready", value }), []);

  return { models, keys, scientists, setKeys: showKeys, setScientists: showScientists, refreshModels };
}
