"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { DataLake, SetupStatus } from "./types";
import type { Loaded } from "./use-settings-data";

// Asks for something and shows what comes. What was shown before is better than nothing, so a failure to ask again
// leaves it be.
function load<T>(
  get: (signal: AbortSignal) => Promise<T>,
  show: React.Dispatch<React.SetStateAction<Loaded<T>>>,
  signal: AbortSignal,
  done?: () => void,
) {
  get(signal).then(
    (value) => {
      show({ kind: "ready", value });
      done?.();
    },
    (error: unknown) => {
      if (signal.aborted) return;
      show((current) => (current.kind === "ready" ? current : { kind: "failed", error }));
      done?.();
    },
  );
}

export interface DataLakeData {
  lake: Loaded<DataLake>;
  // Asks again, as is done after something that changes the files is started. What is shown stays until the answer comes.
  refresh: () => void;
}

// Which files of Biomni's data lake are there, which are asked for when the page opens, and again as often as a job
// finishes, which is what changes them
export function useDataLake(finished: number): DataLakeData {
  const [lake, setLake] = useState<Loaded<DataLake>>({ kind: "loading" });
  const [round, setRound] = useState(0);

  useEffect(() => {
    const abort = new AbortController();
    load(api.dataLake, setLake, abort.signal);

    return () => abort.abort();
  }, [finished, round]);

  const refresh = useCallback(() => setRound((current) => current + 1), []);

  return { lake, refresh };
}

export interface SetupData extends DataLakeData {
  status: Loaded<SetupStatus>;
  // Whether the answer to the latest question about Docker is still to come, which takes a while when Docker is slow to say
  asking: boolean;
}

// What the setup shows besides the jobs: whether Docker and the images are there, and which files of the data lake are.
// They are asked for when the setup opens, and again as often as a job finishes.
export function useSetupData(finished: number): SetupData {
  const { lake, refresh: refreshLake } = useDataLake(finished);
  const [status, setStatus] = useState<Loaded<SetupStatus>>({ kind: "loading" });
  const [round, setRound] = useState(0);
  // The question that was last answered, as the round and the number of jobs finished that it was asked at
  const [answered, setAnswered] = useState<string | null>(null);
  const question = `${round}:${finished}`;

  useEffect(() => {
    const abort = new AbortController();
    load(api.setup, setStatus, abort.signal, () => setAnswered(`${round}:${finished}`));

    return () => abort.abort();
  }, [finished, round]);

  const refresh = useCallback(() => {
    setRound((current) => current + 1);
    refreshLake();
  }, [refreshLake]);

  return { status, lake, asking: answered !== question, refresh };
}
