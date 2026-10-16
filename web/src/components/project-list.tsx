"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { projectFacts, projectStateLabel } from "@/lib/projects";
import type { ProjectEntry, ProjectsList, ProjectState } from "@/lib/types";

// The page of a project, which is named in the address's query, as a conversation is
export const projectAddress = (id: string) => `/projects?id=${encodeURIComponent(id)}`;

// How a project stands, as a word
export function StateBadge({ state }: { state: ProjectState }) {
  const variant = state === "failed" ? "destructive" : state === "running" ? "secondary" : state === "finished" ? "default" : "outline";

  return <Badge variant={variant}>{projectStateLabel(state)}</Badge>;
}

function ProjectRow({ project }: { project: ProjectEntry }) {
  return (
    <li className="flex flex-col gap-1 rounded-lg border border-border p-3" data-testid="project">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="min-w-0 break-words text-sm font-medium">
          <Link href={projectAddress(project.id)} className="rounded-sm outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
            {project.title}
          </Link>
        </h3>
        <StateBadge state={project.state} />
      </div>
      <p className="line-clamp-2 break-words text-xs text-muted-foreground">{project.goal}</p>
      <p className="text-xs text-muted-foreground">{projectFacts(project)}</p>
    </li>
  );
}

// The projects there are, the latest first
export function ProjectList({ list }: { list: ProjectsList }) {
  if (list.projects.length === 0) return <p className="text-sm text-muted-foreground">No project has been made yet. Start one below.</p>;

  return (
    <ul aria-label="Projects" className="flex flex-col gap-2">
      {list.projects.map((project) => (
        <ProjectRow key={project.id} project={project} />
      ))}
    </ul>
  );
}
