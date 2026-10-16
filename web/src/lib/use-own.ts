"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Own } from "./types";
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
  const [own, setOwn] = useState<Loaded<Own>>({ kind: "loading" });
  // A look may be answered after a change that it began before, or after a later look, and must not replace what is
  // newer. Each is numbered as it is made, and an answer is shown only if nothing after it has been.
  const asked = useRef(0);
  const answered = useRef(0);

  const reload = useCallback(() => {
    const number = ++asked.current;
    api.own().then(
      (value) => {
        if (number <= answered.current) return;
        answered.current = number;
        setOwn({ kind: "ready", value });
      },
      (error: unknown) => {
        report(error);
        if (number <= answered.current) return;
        answered.current = number;
        setOwn((current) => (current.kind === "ready" ? current : { kind: "failed", error }));
      },
    );
  }, [report]);

  const set = useCallback((value: Own) => {
    answered.current = ++asked.current;
    setOwn({ kind: "ready", value });
  }, []);

  useEffect(() => {
    // What was given is looked at when the page opens, which is when this runs
    reload();
    const show = () => {
      if (document.visibilityState === "visible") reload();
    };
    document.addEventListener("visibilitychange", show);

    return () => document.removeEventListener("visibilitychange", show);
  }, [reload]);

  return { own, set, reload };
}
