"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { count } from "@/lib/checks";
import { ROWS_SHOWN, stepTitle } from "@/lib/projects";
import type { Project, ProjectFinding } from "@/lib/types";

function Finding({ finding }: { finding: ProjectFinding }) {
  const where = [finding.id, finding.round === null ? "" : `round ${finding.round}`, finding.source ? stepTitle(finding.source) : ""];

  return (
    <li className="flex flex-col gap-1 rounded-lg border border-border p-3" data-testid="project-finding">
      <p className="break-words text-sm font-medium">{finding.claim}</p>
      {finding.evidence && <p className="whitespace-pre-wrap break-words text-xs text-muted-foreground">{finding.evidence}</p>}
      <p className="text-xs text-muted-foreground">{where.filter(Boolean).join(" · ")}</p>
    </li>
  );
}

// What the work has found, each as a claim and what shows it, a few at a time
export function Findings({ project }: { project: Project }) {
  const [shown, setShown] = useState(ROWS_SHOWN);
  const { findings } = project;
  if (findings.length === 0) return <p className="text-sm text-muted-foreground">Nothing has been found yet.</p>;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground" role="status">
        {findings.length > shown ? `The first ${shown} of ${count(findings.length, "finding")}.` : `${count(findings.length, "finding")}.`}
      </p>
      <ul aria-label="Findings" className="flex flex-col gap-2">
        {findings.slice(0, shown).map((finding) => (
          <Finding key={finding.id} finding={finding} />
        ))}
      </ul>
      {findings.length > shown && (
        <div>
          <Button variant="outline" size="sm" onClick={() => setShown((was) => was + ROWS_SHOWN)}>
            Show {Math.min(ROWS_SHOWN, findings.length - shown)} more
          </Button>
        </div>
      )}
    </div>
  );
}
