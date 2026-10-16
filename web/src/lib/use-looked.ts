"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { problemOf, type Problem } from "./errors";
import type { Loaded } from "./use-settings-data";

export interface Looked<T> {
  value: Loaded<T>;
  // What a change gives back, which is shown from then on
  set: (value: T) => void;
  // Looks again, as is done when the first look failed. What is shown stays until the answer comes.
  reload: () => void;
}

// Something the server holds, looked at when the page opens, as the page is shown again, and whenever `again` is not
// what it was, which is how it is looked at again as the work on it goes on
export function useLooked<T>(look: () => Promise<T>, report: (error: unknown) => void, again: string): Looked<T> {
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

  const set = useCallback((found: T) => {
    answered.current = ++asked.current;
    setValue({ kind: "ready", value: found });
  }, []);

  useEffect(() => {
    // What the server holds is looked at when the page opens and when `again` changes, which is when this runs
    reload();
  }, [reload, again]);

  useEffect(() => {
    const show = () => {
      if (document.visibilityState === "visible") reload();
    };
    document.addEventListener("visibilitychange", show);

    return () => document.removeEventListener("visibilitychange", show);
  }, [reload]);

  return { value, set, reload };
}

export interface Attempt {
  // Whether something is being asked of the server, which is one thing at a time
  busy: boolean;
  // Why the latest was refused, until another is made
  problem: Problem | null;
  // Does it, and gives what it gave back, or nothing if it was refused
  run: <T>(action: () => Promise<T>) => Promise<T | undefined>;
  // Takes the problem away, which is shown until it is
  forget: () => void;
}

// What a part of a page asks of the server, and what it was refused for
export function useAttempt(report: (error: unknown) => void): Attempt {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);

  const run = useCallback(
    async <T>(action: () => Promise<T>): Promise<T | undefined> => {
      setBusy(true);
      setProblem(null);
      try {
        return await action();
      } catch (error) {
        report(error);
        setProblem(problemOf(error));

        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [report],
  );
  const forget = useCallback(() => setProblem(null), []);

  return { busy, problem, run, forget };
}
