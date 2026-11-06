"use client";

import { Check, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { sourceLabel, type HubSkill } from "@/lib/skills";
import { cn } from "@/lib/utils";

// The control of a skill the lab has: on, so that a new conversation is given it, or off. It is a switch, which says
// what it is by its words as well as by its colour.
export function SkillSwitch({ skill, onTurn }: { skill: HubSkill; onTurn: (enabled: boolean) => void }) {
  const on = skill.info?.enabled ?? false;

  return (
    <Button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={`Give new programs ${skill.name}`}
      variant={on ? "secondary" : "outline"}
      size="sm"
      className={cn("rounded-full px-3", on ? "text-foreground" : "text-muted-foreground")}
      onClick={() => onTurn(!on)}
    >
      {on && <Check aria-hidden />}
      {on ? "On" : "Off"}
    </Button>
  );
}

// A skill of the library that the lab does not have yet
export function SkillAdd({ skill, onAdd }: { skill: HubSkill; onAdd: (button: HTMLButtonElement) => void }) {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="rounded-full px-3"
      aria-label={`Add ${skill.name}`}
      onClick={(event) => onAdd(event.currentTarget)}
    >
      <Plus aria-hidden />
      Add
    </Button>
  );
}

// A skill as a card: what it is about, what to call it, and what it is for, which opens to all of it, and below that where
// it comes from and whether the lab has it on
export function SkillCard({
  skill,
  onOpen,
  onTurn,
  onAdd,
}: {
  skill: HubSkill;
  onOpen: (button: HTMLButtonElement) => void;
  onTurn: (enabled: boolean) => void;
  onAdd: (button: HTMLButtonElement) => void;
}) {
  return (
    <li
      className="flex flex-col rounded-2xl border border-border bg-card transition-[border-color,box-shadow] focus-within:border-ring/60 hover:border-ring/60 hover:shadow-sm"
      data-testid="skill-card"
    >
      <button
        type="button"
        aria-haspopup="dialog"
        onClick={(event) => onOpen(event.currentTarget)}
        className="flex min-h-32 flex-1 flex-col gap-1.5 rounded-t-2xl px-4 pb-2 pt-4 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/40"
      >
        {skill.category !== null && (
          <span className="truncate text-xs text-muted-foreground" title={skill.category}>
            {skill.category}
          </span>
        )}
        <span className="break-words font-serif text-[17px] font-semibold leading-snug">{skill.name}</span>
        <span className="line-clamp-3 break-words text-[13px] leading-5 text-muted-foreground">{skill.description}</span>
      </button>
      <div className="flex items-center justify-between gap-2 px-4 pb-3 pt-1">
        <span className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
          <span className="truncate">{sourceLabel(skill.source)}</span>
          {skill.library?.license_kind === "noncommercial" && (
            <Badge variant="destructive" title={skill.library.license ?? undefined}>
              Noncommercial
            </Badge>
          )}
        </span>
        {skill.info === null ? <SkillAdd skill={skill} onAdd={onAdd} /> : <SkillSwitch skill={skill} onTurn={onTurn} />}
      </div>
    </li>
  );
}
