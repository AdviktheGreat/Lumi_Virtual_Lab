"use client";

import { Trash2 } from "lucide-react";
import { SkillAdd, SkillSwitch } from "@/components/skill-card";
import { Instructions } from "@/components/skill-instructions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { licenseLabel, licenseNote, sizeSaid, sourceLabel, whereFound, type HubSkill } from "@/lib/skills";

function Facts({ skill }: { skill: HubSkill }) {
  const { info, library } = skill;
  const license = library?.license ?? info?.license ?? null;
  const rows: [string, React.ReactNode][] = [["From", sourceLabel(skill.source)]];
  if (skill.category !== null) rows.push(["Category", skill.category]);
  if (library !== null) {
    rows.push([
      "License",
      <Badge key="license" variant={library.license_kind === "noncommercial" ? "destructive" : "outline"} title={license ?? undefined}>
        {licenseLabel(library)}
      </Badge>,
    ]);
  } else if (license !== null) {
    rows.push(["License", license]);
  }
  const needs = info?.compatibility ?? library?.compatibility ?? null;
  if (needs !== null) rows.push(["Needs", needs]);
  if (library !== null) rows.push(["Size", `${library.files} file${library.files === 1 ? "" : "s"}, ${sizeSaid(library.bytes)}`]);
  if (info !== null) rows.push(["Kept in", `${whereFound(info.source)}: ${info.directory}`]);
  const note = library === null ? null : licenseNote(library.license_kind);

  return (
    <div className="flex flex-col gap-1.5">
      <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-1 text-xs">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="min-w-0 break-words">{value}</dd>
          </div>
        ))}
      </dl>
      {note && <p className="text-xs">{note}</p>}
      {info !== null && info.notes.length > 0 && (
        <ul aria-label={`Notes on ${skill.name}`} className="list-disc pl-4 text-xs text-muted-foreground">
          {info.notes.map((each) => (
            <li key={each}>{each}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// All of a skill: what it is for, where it comes from, its license, what it tells the lead and the files that come with it,
// which are read before it is trusted, and what can be done with it
export function SkillDetail({
  skill,
  onClose,
  onCloseAutoFocus,
  onTurn,
  onAdd,
  onRemove,
}: {
  skill: HubSkill | null;
  onClose: () => void;
  onCloseAutoFocus: (event: Event) => void;
  onTurn: (enabled: boolean) => void;
  onAdd: (button: HTMLButtonElement) => void;
  onRemove: (button: HTMLButtonElement) => void;
}) {
  return (
    <Dialog open={skill !== null} onOpenChange={(open) => !open && onClose()}>
      {skill !== null && (
        <DialogContent className="sm:max-w-2xl" onCloseAutoFocus={onCloseAutoFocus}>
          <DialogHeader>
            <DialogTitle className="break-words font-serif text-2xl">{skill.name}</DialogTitle>
            <DialogDescription className="max-h-40 overflow-y-auto break-words text-sm leading-6">
              {skill.description}
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2">
            {skill.info === null ? <SkillAdd skill={skill} onAdd={onAdd} /> : <SkillSwitch skill={skill} onTurn={onTurn} />}
            {skill.info?.removable && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={(event) => onRemove(event.currentTarget)}
                aria-label={`Delete ${skill.name}`}
              >
                <Trash2 aria-hidden />
                Delete
              </Button>
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="flex flex-col gap-4">
              <Facts skill={skill} />
              <Instructions name={skill.name} load={skill.info === null ? api.previewLibrarySkill : api.previewSkill} />
            </div>
          </div>
        </DialogContent>
      )}
    </Dialog>
  );
}
