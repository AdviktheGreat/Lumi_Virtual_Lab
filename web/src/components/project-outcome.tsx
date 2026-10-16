"use client";

import { Download } from "lucide-react";
import { Markdown } from "@/components/markdown";
import { StateBadge } from "@/components/project-list";
import { projectStateNote } from "@/lib/projects";
import type { Project } from "@/lib/types";

// How a project that is not at work ended, why, and what it answered, with the report to keep
export function Outcome({ project }: { project: Project }) {
  const { state } = project;
  if (state === "running" || state === "new") return null;
  const note = state === "finished" ? "" : projectStateNote(state);

  return (
    <section aria-label="How it ended" className="flex flex-col gap-3 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <StateBadge state={state} />
        {project.reason && <p className="min-w-0 break-words text-sm">{project.reason}</p>}
      </div>
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
      {project.error && (
        <p role="alert" className="break-words text-xs text-destructive">
          {project.error}
        </p>
      )}
      {project.answer && (
        <div className="flex flex-col gap-1" data-testid="project-answer">
          <h3 className="text-sm font-medium">The answer</h3>
          <Markdown text={project.answer} className="text-sm leading-6" />
        </div>
      )}
      {!project.answer && project.proposed_answer && (
        <div className="flex flex-col gap-1" data-testid="project-proposed-answer">
          <h3 className="text-sm font-medium">The last answer put to the critic, which it did not accept</h3>
          <Markdown text={project.proposed_answer} className="text-sm leading-6" />
          {project.objections.length > 0 && (
            <>
              <h3 className="mt-2 text-sm font-medium">What the critic objected to</h3>
              <ul aria-label="Objections" className="list-disc pl-5 text-sm">
                {project.objections.map((objection, number) => (
                  <li key={number} className="break-words">
                    {objection}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      {project.report && (
        <div>
          <a
            href={`/api/projects/${encodeURIComponent(project.id)}/report`}
            download
            className="inline-flex items-center gap-1 rounded-sm text-sm text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <Download className="size-3.5" aria-hidden />
            Download the report
          </a>
        </div>
      )}
    </section>
  );
}
