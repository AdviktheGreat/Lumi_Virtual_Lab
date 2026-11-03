"use client";

import { useEffect, useId, useState } from "react";
import { ChevronDown, ChevronRight, Trash2 } from "lucide-react";
import { useServer } from "@/components/server-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { whereFound } from "@/lib/skills";
import type { SkillInfo, SkillPreview } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

// What a skill tells the lead, and the files that come with it, which are read before a skill is trusted
function Instructions({ name }: { name: string }) {
  const { report } = useServer();
  const [preview, setPreview] = useState<Loaded<SkillPreview>>({ kind: "loading" });

  useEffect(() => {
    const abort = new AbortController();
    api.previewSkill(name, abort.signal).then(
      (value) => setPreview({ kind: "ready", value }),
      (error: unknown) => {
        if (abort.signal.aborted) return;
        report(error);
        setPreview({ kind: "failed", error });
      },
    );

    return () => abort.abort();
  }, [name, report]);

  if (preview.kind === "loading") {
    return (
      <p role="status" className="text-xs text-muted-foreground">
        Reading {name}…
      </p>
    );
  }
  if (preview.kind === "failed") {
    return (
      <p role="alert" className="text-xs text-destructive">
        {describeError(preview.error)}
      </p>
    );
  }

  const { instructions, characters, files, more_files: more } = preview.value;

  return (
    <div className="flex flex-col gap-2">
      <div
        role="region"
        aria-label={`What ${name} tells the lead`}
        tabIndex={0}
        className="max-h-72 overflow-auto rounded-md bg-muted/60 p-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-5">{instructions}</pre>
      </div>
      {instructions.length < characters && (
        <p className="text-xs text-muted-foreground">
          Only the first {instructions.length.toLocaleString()} of its {characters.toLocaleString()} characters are shown.
        </p>
      )}
      {files.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium">Files that come with it</p>
          <ul aria-label={`Files of ${name}`} className="grid gap-x-4 gap-y-0.5 text-xs sm:grid-cols-2">
            {files.map((file) => (
              <li key={file} className="min-w-0 truncate" title={file}>
                <code>{file}</code>
              </li>
            ))}
          </ul>
          {more > 0 && <p className="text-xs text-muted-foreground">And {more} more.</p>}
        </div>
      )}
    </div>
  );
}

function Facts({ skill }: { skill: SkillInfo }) {
  const rows: [string, string][] = [["Found in", `${whereFound(skill.source)}: ${skill.directory}`]];
  if (skill.license) rows.push(["License", skill.license]);
  if (skill.compatibility) rows.push(["Needs", skill.compatibility]);

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
      {skill.notes.length > 0 && (
        <ul aria-label={`Notes on ${skill.name}`} className="list-disc pl-4 text-xs text-muted-foreground">
          {skill.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// A skill: whether new conversations are given it, what it is for, and a look at what it tells the lead
export function SkillRow({
  skill,
  onTurn,
  onRemove,
}: {
  skill: SkillInfo;
  onTurn: (enabled: boolean) => void;
  onRemove: (button: HTMLButtonElement) => void;
}) {
  const detailsId = useId();
  const [open, setOpen] = useState(false);

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="skill">
      <div className="flex items-start gap-2.5">
        <Checkbox
          checked={skill.enabled}
          onChange={(event) => onTurn(event.target.checked)}
          aria-label={`Give new conversations ${skill.name}`}
          className="mt-1"
        />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <code className="break-all text-sm font-medium">{skill.name}</code>
            {skill.source !== "workspace" && <Badge variant="outline">Shared with other tools</Badge>}
          </div>
          <p className={open ? "break-words text-sm" : "line-clamp-2 break-words text-sm text-muted-foreground"}>
            {skill.description}
          </p>
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
        {skill.removable && (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={(event) => onRemove(event.currentTarget)}
            aria-label={`Delete ${skill.name}`}
          >
            <Trash2 />
          </Button>
        )}
      </div>
      {open && (
        <div id={detailsId} className="flex flex-col gap-3 pl-[1.625rem]">
          <Facts skill={skill} />
          <Instructions name={skill.name} />
        </div>
      )}
    </li>
  );
}
