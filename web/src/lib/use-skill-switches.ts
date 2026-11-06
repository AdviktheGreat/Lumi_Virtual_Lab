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

  // While changes are waiting, what they are made to is what the last answer gave, to which are added the skills that came
  // some other way meanwhile, such as by being added, so that the next change does not leave them out
  useEffect(() => {
    if (waiting.current === 0) {
      latest.current = skills.skills;
      return;
    }
    const known = new Set(latest.current.map((skill) => skill.name));
    const added = skills.skills.filter((skill) => !known.has(skill.name));
    if (added.length > 0) latest.current = [...latest.current, ...added];
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

  // Deleting waits for the changes made before it, so that one of them that is still being saved does not give back a list
  // that has the skill in it
  const remove = useCallback(
    (skill: SkillInfo): Promise<boolean> => {
      waiting.current += 1;
      const done = queue.current.then(async (): Promise<boolean> => {
        try {
          setProblem(null);
          setDone(null);
          const kept = await api.removeSkill(skill.name);
          latest.current = kept.skills;
          onChanged(kept);
          setDone(`Deleted ${skill.name}.`);

          return true;
        } catch (error) {
          report(error);
          setProblem(describeError(error));

          return false;
        } finally {
          waiting.current -= 1;
          if (waiting.current === 0) setChosen({});
        }
      });
      queue.current = done.then(() => undefined);

      return done;
    },
    [onChanged, report],
  );

  const shown = useMemo(
    () => skills.skills.map((skill) => (skill.name in chosen ? { ...skill, enabled: chosen[skill.name] } : skill)),
    [skills.skills, chosen],
  );

  return { skills: shown, turn, remove, problem, done, clear };
}
