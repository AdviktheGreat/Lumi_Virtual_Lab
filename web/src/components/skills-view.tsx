"use client";

import { useRef, useState } from "react";
import { ChevronDown, FolderUp, GitBranch, Plus } from "lucide-react";
import { Given } from "@/components/given";
import { PageFrame } from "@/components/page-frame";
import { useServer } from "@/components/server-provider";
import { SkillsAdd } from "@/components/skills-add";
import { SkillsHub } from "@/components/skills-hub";
import { SkillUpload } from "@/components/skill-upload";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import type { Skills } from "@/lib/types";
import { useSkillLibrary } from "@/lib/use-skill-library";
import { useSkills } from "@/lib/use-skills";

// The skills the lab can be given: those it has, which are turned on and off, read, and deleted, and those of its library,
// which are added, and the putting in of skills of a person's own: a folder that they choose or drop, or the skills of a Git
// repository or of a folder at a path
export function SkillsView() {
  const { report } = useServer();
  const kept = useSkills(report);
  const offered = useSkillLibrary(report);
  const [opened, setOpened] = useState<"upload" | "from" | null>(null);
  const menu = useRef<HTMLButtonElement | null>(null);

  function changed(result: Skills) {
    kept.set(result);
    offered.reload();
  }

  // A dialog that was opened from the menu is closed to the button that opened the menu, which is not where the menu's item
  // was, since that is gone
  function returnFocus(event: Event) {
    event.preventDefault();
    menu.current?.focus();
  }

  return (
    <PageFrame
      wide
      title="Skills Nexus"
      intro="Written guidance on how to do a kind of work. The lead is told what each skill is for, and reads one when a task calls for it. A conversation begins with the skills that are on."
      action={
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button ref={menu}>
              <Plus aria-hidden />
              New skill
              <ChevronDown aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-80">
            <DropdownMenuItem onSelect={() => setOpened("upload")}>
              <FolderUp aria-hidden />
              <span className="flex flex-col">
                <span>Upload skill</span>
                <span className="text-xs text-muted-foreground">Choose or drop a skill folder from this machine</span>
              </span>
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setOpened("from")}>
              <GitBranch aria-hidden />
              <span className="flex flex-col">
                <span>From a repository or folder</span>
                <span className="text-xs text-muted-foreground">Every skill in a Git repository, or in a folder at a path</span>
              </span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
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
        <>
          <SkillUpload
            open={opened === "upload"}
            onOpenChange={(open) => setOpened(open ? "upload" : null)}
            skills={kept.skills.value.skills}
            onPutIn={changed}
            onCloseAutoFocus={returnFocus}
          />
          <SkillsAdd
            open={opened === "from"}
            onOpenChange={(open) => setOpened(open ? "from" : null)}
            skills={kept.skills.value}
            onPutIn={changed}
            onCloseAutoFocus={returnFocus}
          />
        </>
      )}
    </PageFrame>
  );
}
