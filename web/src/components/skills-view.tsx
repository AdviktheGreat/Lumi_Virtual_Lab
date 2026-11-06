"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Given } from "@/components/given";
import { PageFrame } from "@/components/page-frame";
import { useServer } from "@/components/server-provider";
import { SkillsAdd } from "@/components/skills-add";
import { SkillsHub } from "@/components/skills-hub";
import { Button } from "@/components/ui/button";
import type { Skills } from "@/lib/types";
import { useSkillLibrary } from "@/lib/use-skill-library";
import { useSkills } from "@/lib/use-skills";

// The skills the lab can be given: those it has, which are turned on and off, read, and deleted, and those of its library,
// which are added, and the putting in of skills of a person's own from a Git repository or a folder
export function SkillsView() {
  const { report } = useServer();
  const kept = useSkills(report);
  const offered = useSkillLibrary(report);
  const [adding, setAdding] = useState(false);

  function changed(result: Skills) {
    kept.set(result);
    offered.reload();
  }

  return (
    <PageFrame
      wide
      title="Skills Nexus"
      intro="Written guidance on how to do a kind of work. The lead is told what each skill is for, and reads one when a task calls for it. A conversation begins with the skills that are on."
      action={
        <Button onClick={() => setAdding(true)}>
          <Plus aria-hidden />
          Add skills
        </Button>
      }
    >
      <Given given={offered.library} label="Looking at the skills" failure="The skills could not be looked at." onRetry={offered.reload}>
        {(library) => (
          <Given given={kept.skills} label="Looking at the skills" failure="The skills could not be looked at." onRetry={kept.reload}>
            {(skills) => <SkillsHub skills={skills} library={library} onChanged={changed} onPutIn={changed} />}
          </Given>
        )}
      </Given>
      {kept.skills.kind === "ready" && (
        <SkillsAdd open={adding} onOpenChange={setAdding} skills={kept.skills.value} onPutIn={changed} />
      )}
    </PageFrame>
  );
}
