"use client";

import { Progress } from "@/components/ui/progress";
import { catalogFilled, catalogSaid } from "@/lib/skills";
import type { SkillsCatalog } from "@/lib/types";

// What the skills that are on take of every conversation, since the lead is told what each is for before it begins, and
// how full the list is, which is when descriptions are cut
export function SkillsMeter({ catalog }: { catalog: SkillsCatalog }) {
  const { text, tight } = catalogSaid(catalog);

  return (
    <div className="flex flex-col gap-1.5" data-testid="skills-meter">
      <Progress value={catalogFilled(catalog)} aria-label="How full the list of skills that the lead is given is" />
      <p className={tight ? "text-xs text-foreground" : "text-xs text-muted-foreground"}>{text}</p>
    </div>
  );
}
