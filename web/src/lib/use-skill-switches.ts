"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { describeError } from "./errors";
import { disabledWhen } from "./skills";
import type { SkillInfo, Skills } from "./types";

export interface SkillSwitches {
  // The skills as they are shown: what was chosen is shown at once, before the server has answered
  skills: SkillInfo[];
  turn: (names: string[], enabled: boolean) => void;
  remove: (skill: SkillInfo) => Promise<boolean>;
  // What went wrong with the last change, or what was done by it
  problem: string | null;
  done: string | null;
  clear: () => void;
}

// Turning skills on and off, and deleting them. A box answers at once, and what the server holds is what is shown once
// every change has been answered, whether it kept them or not.
export function useSkillSwitches(
  skills: Skills,
  onChanged: (skills: Skills) => void,
  report: (error: unknown) => void,
): SkillSwitches {
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Record<string, boolean>>({});
  // The skills as the server last gave them, which each change is made to. Changes are made one after another, so that
  // two in quick succession do not each start from what was shown before the other.
  const latest = useRef<SkillInfo[]>(skills.skills);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const waiting = useRef(0);

  useEffect(() => {
    if (waiting.current === 0) latest.current = skills.skills;
  }, [skills]);

  const clear = useCallback(() => {
    setProblem(null);
    setDone(null);
  }, []);

  const turn = useCallback(
    (names: string[], enabled: boolean) => {
      waiting.current += 1;
      setChosen((was) => ({ ...was, ...Object.fromEntries(names.map((name) => [name, enabled])) }));
      queue.current = queue.current.then(async () => {
        try {
          setProblem(null);
          setDone(null);
          const kept = await api.saveSkills(disabledWhen(latest.current, names, enabled));
          latest.current = kept.skills;
          onChanged(kept);
        } catch (error) {
          report(error);
          setProblem(describeError(error));
        } finally {
          waiting.current -= 1;
          if (waiting.current === 0) setChosen({});
        }
      });
    },
    [onChanged, report],
  );

  const remove = useCallback(
    async (skill: SkillInfo): Promise<boolean> => {
      setProblem(null);
      setDone(null);
      try {
        const kept = await api.removeSkill(skill.name);
        latest.current = kept.skills;
        onChanged(kept);
        setDone(`Deleted ${skill.name}.`);

        return true;
      } catch (error) {
        report(error);
        setProblem(describeError(error));

        return false;
      }
    },
    [onChanged, report],
  );

  const shown = useMemo(
    () => skills.skills.map((skill) => (skill.name in chosen ? { ...skill, enabled: chosen[skill.name] } : skill)),
    [skills.skills, chosen],
  );

  return { skills: shown, turn, remove, problem, done, clear };
}
