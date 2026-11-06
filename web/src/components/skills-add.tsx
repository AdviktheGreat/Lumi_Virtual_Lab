"use client";

import { SkillInstall } from "@/components/skill-install";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { Skills, SkillsPutIn } from "@/lib/types";

function Folders({ skills }: { skills: Skills }) {
  const lab = skills.folders.find((folder) => folder.source === "workspace");
  const own = skills.folders.find((folder) => folder.source === "user");

  return (
    <p className="text-xs text-muted-foreground">
      {lab && (
        <>
          The skills you put in are kept in <code className="break-all">{lab.path}</code>.{" "}
        </>
      )}
      {own && (
        <>
          The lab also reads <code className="break-all">{own.path}</code>
          {own.exists ? "" : ", which is not there yet"}, where other tools that use skills keep theirs. A skill in both is
          read from the lab&apos;s own folder.
        </>
      )}
    </p>
  );
}

// Where skills of your own are put in from: a Git repository or a folder on this machine
export function SkillsAdd({
  open,
  onOpenChange,
  skills,
  onPutIn,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  skills: Skills;
  onPutIn: (result: SkillsPutIn) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Add skills</DialogTitle>
          <DialogDescription>Put in your own skills, or those someone else has written.</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="flex flex-col gap-4">
            <SkillInstall onPutIn={onPutIn} />
            <Folders skills={skills} />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
