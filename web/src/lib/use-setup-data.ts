"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { DataLake, SetupStatus } from "./types";
import type { Loaded } from "./use-settings-data";

export interface SetupData {
  status: Loaded<SetupStatus>;
  lake: Loaded<DataLake>;
  // Whether the answer to the latest question about Docker is still to come, which takes a while when Docker is slow to say
  asking: boolean;
  // Asks for both again, as is done after something that changes them is started. What is shown stays until the
  // answer comes.
  refresh: () => void;
}

// What the setup shows besides the jobs: whether Docker and the images are there, and which files of the data lake are.
// They are asked for when the setup opens, and again as often as a job finishes, which is what changes them.
export function useSetupData(finished: number): SetupData {
  const [status, setStatus] = useState<Loaded<SetupStatus>>({ kind: "loading" });
  const [lake, setLake] = useState<Loaded<DataLake>>({ kind: "loading" });
  const [round, setRound] = useState(0);
  // The question that was last answered, as the round and the number of jobs finished that it was asked at
  const [answered, setAnswered] = useState<string | null>(null);
  const question = `${round}:${finished}`;

  useEffect(() => {
    const abort = new AbortController();
    function load<T>(
      get: (signal: AbortSignal) => Promise<T>,
      show: React.Dispatch<React.SetStateAction<Loaded<T>>>,
      done?: () => void,
    ) {
      get(abort.signal).then(
        (value) => {
          show({ kind: "ready", value });
          done?.();
        },
        (error: unknown) => {
          if (abort.signal.aborted) return;
          // What was shown before is better than nothing
          show((current) => (current.kind === "ready" ? current : { kind: "failed", error }));
          done?.();
        },
      );
    }
    load(api.setup, setStatus, () => setAnswered(`${round}:${finished}`));
    load(api.dataLake, setLake);

    return () => abort.abort();
  }, [finished, round]);

  const refresh = useCallback(() => setRound((current) => current + 1), []);

  return { status, lake, asking: answered !== question, refresh };
}
