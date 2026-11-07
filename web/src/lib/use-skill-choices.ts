"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { SkillChoice } from "./commands";
import { skillChoices } from "./skills";
import type { SkillInfo } from "./types";

// The skills that can be written after a slash, which are read from the server the first time they are wanted, so that a
// conversation, whose skills are named, does not read them for a person who never writes a slash. They are the skills named,
// or where none are, those that are on for new conversations. Where they cannot be read, the skills named are offered
// without what each is for.
export function useSkillChoices(names: readonly string[] | null, wanted: boolean): SkillChoice[] {
  const [library, setLibrary] = useState<SkillInfo[] | null>(null);

  useEffect(() => {
    if (!wanted || library !== null) return;
    let current = true;
    api.skills().then(
      (found) => {
        if (current) setLibrary(found.skills);
      },
      () => undefined,
    );

    return () => {
      current = false;
    };
  }, [wanted, library]);

  return useMemo(() => skillChoices(library, names), [library, names]);
}
