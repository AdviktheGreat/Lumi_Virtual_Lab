"use client";

import { useId, useState } from "react";
import { Check, ChevronDown, ChevronRight } from "lucide-react";
import { Instructions } from "@/components/skill-row";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { api } from "@/lib/api";
import { licenseLabel, licenseNote, sizeSaid } from "@/lib/skills";
import type { LibrarySkill, LicenseKind } from "@/lib/types";

// A license that limits what a person may do with a skill stands out from those that do not
function licenseVariant(kind: LicenseKind): "destructive" | "secondary" | "outline" {
  if (kind === "noncommercial") return "destructive";

  return kind === "copyleft" || kind === "none" ? "secondary" : "outline";
}

function Facts({ skill }: { skill: LibrarySkill }) {
  const note = licenseNote(skill.license_kind);
  const rows: [string, string][] = [
    ["Category", skill.category],
    ["License", skill.license ?? "None stated"],
  ];
  if (skill.compatibility) rows.push(["Needs", skill.compatibility]);
  rows.push(["Size", `${skill.files} file${skill.files === 1 ? "" : "s"}, ${sizeSaid(skill.bytes)}`]);

  return (
    <div className="flex flex-col gap-1.5">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="min-w-0 break-words">{value}</dd>
          </div>
        ))}
      </dl>
      {note && <p className="text-xs">{note}</p>}
    </div>
  );
}

// A skill of the library: whether it is chosen to be put in, or that it is in already, what it is for, its license, and a look
// at what it tells the lead before it is put in
export function LibraryRow({
  skill,
  chosen,
  onChoose,
}: {
  skill: LibrarySkill;
  chosen: boolean;
  onChoose: (chosen: boolean) => void;
}) {
  const detailsId = useId();
  const [open, setOpen] = useState(false);

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="library-skill">
      <div className="flex items-start gap-2.5">
        {skill.installed ? (
          <Check aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        ) : (
          <Checkbox
            checked={chosen}
            onChange={(event) => onChoose(event.target.checked)}
            aria-label={`Choose ${skill.name} to put in`}
            className="mt-1"
          />
        )}
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <code className="break-all text-sm font-medium">{skill.name}</code>
            {skill.installed && <Badge variant="secondary">In your skills</Badge>}
            <Badge variant={licenseVariant(skill.license_kind)} title={skill.license ?? undefined}>
              {licenseLabel(skill)}
            </Badge>
          </div>
          <p className={open ? "break-words text-sm" : "line-clamp-2 break-words text-sm text-muted-foreground"}>
            {skill.description}
          </p>
          <p className="text-xs text-muted-foreground">{skill.category}</p>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => setOpen((was) => !was)}
          aria-expanded={open}
          aria-controls={open ? detailsId : undefined}
          aria-label={`${open ? "Hide" : "Read"} what ${skill.name} tells the lead`}
        >
          {open ? <ChevronDown /> : <ChevronRight />}
        </Button>
      </div>
      {open && (
        <div id={detailsId} className="flex flex-col gap-3 pl-[1.625rem]">
          <Facts skill={skill} />
          <Instructions name={skill.name} load={api.previewLibrarySkill} />
        </div>
      )}
    </li>
  );
}
