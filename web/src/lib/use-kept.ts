"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Loaded } from "./use-settings-data";

export interface KeptState<T> {
  value: Loaded<T>;
  // What a change gives back, which is all of what was kept as it now is, and is shown from then on
  set: (value: T) => void;
  // Looks again, as is done when the first look failed. What is shown stays until the answer comes.
  reload: () => void;
}

// Something the person keeps with the server, which is looked at when the page opens, and as the page is shown again, since
// what it points to may have been moved or deleted while it was away. `look` must be the same function on every render.
export function useKept<T>(look: (signal?: AbortSignal) => Promise<T>, report: (error: unknown) => void): KeptState<T> {
  const [value, setValue] = useState<Loaded<T>>({ kind: "loading" });
  // A look may be answered after a change that it began before, or after a later look, and must not replace what is
  // newer. Each is numbered as it is made, and an answer is shown only if nothing after it has been.
  const asked = useRef(0);
  const answered = useRef(0);

  const reload = useCallback(() => {
    const number = ++asked.current;
    look().then(
      (found) => {
        if (number <= answered.current) return;
        answered.current = number;
        setValue({ kind: "ready", value: found });
      },
      (error: unknown) => {
        report(error);
        if (number <= answered.current) return;
        answered.current = number;
        setValue((current) => (current.kind === "ready" ? current : { kind: "failed", error }));
      },
    );
  }, [look, report]);

  const set = useCallback((next: T) => {
    answered.current = ++asked.current;
    setValue({ kind: "ready", value: next });
  }, []);

  useEffect(() => {
    // It is looked at when the page opens, which is when this runs
    reload();
    const show = () => {
      if (document.visibilityState === "visible") reload();
    };
    document.addEventListener("visibilitychange", show);

    return () => document.removeEventListener("visibilitychange", show);
  }, [reload]);

  return { value, set, reload };
}
