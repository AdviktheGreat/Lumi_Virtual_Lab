"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Trash2 } from "lucide-react";
import { Looked } from "@/components/looked";
import { ProblemNotice } from "@/components/messages";
import { PageSection } from "@/components/page-section";
import { Findings } from "@/components/project-findings";
import { StateBadge } from "@/components/project-list";
import { Outcome } from "@/components/project-outcome";
import { Plan, Rounds, Team } from "@/components/project-rounds";
import { Steps } from "@/components/project-steps";
import { StartForm } from "@/components/project-work";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { WorkStatus } from "@/components/work-status";
import { api } from "@/lib/api";
import { describeCode } from "@/lib/benchmarks";
import { sentence } from "@/lib/checks";
import { describeSetup, lastProjectJob, projectFacts, projectJob, projectKey } from "@/lib/projects";
import type { Project, ProjectsList } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";
import { useProject, useProjectsList } from "@/lib/use-projects";

// A project, with its title, what it is for, who works on it, and how far it has got, and the way to delete it
function ProjectHeader({ project, working }: { project: Project; working: boolean }) {
  const { report } = useServer();
  const router = useRouter();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);

  async function remove() {
    const left = await attempt.run(() => api.deleteProject(project.id));
    if (left) router.push("/projects");
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="break-words text-lg font-semibold">{project.title}</h2>
            <StateBadge state={project.state} />
          </div>
          <p className="mt-1 whitespace-pre-wrap break-words text-sm">{project.goal}</p>
          <p className="mt-2 text-sm text-muted-foreground">{describeSetup(project)}</p>
          <p className="text-sm text-muted-foreground">
            {project.model ?? "The model it was made with"} · {sentence(describeCode(project.code))}
          </p>
          <p className="text-sm text-muted-foreground">{projectFacts(project)}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setAsking(true)}
          disabled={working || attempt.busy}
          aria-label={`Delete ${project.title}`}
        >
          <Trash2 />
          Delete
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {project.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This deletes the plan, what was said in each meeting, the code that was run, and everything the project found.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void remove()}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function ProjectBody({ project, list, jobs }: { project: Project; list: ProjectsList; jobs: JobsData }) {
  const all = jobs.jobs ?? [];
  const job = projectJob(all, project.id);
  const working = job !== undefined;

  return (
    <>
      <ProjectHeader project={project} working={working} />
      <WorkStatus job={job} last={lastProjectJob(all, project.id)} jobs={jobs} />
      <Outcome project={project} />
      <PageSection title="Work on it">
        {/* Begun again when the project's standing changes, since what it may be asked to spend is more than it has spent */}
        <StartForm key={project.state} project={project} limits={list.limits} working={working} jobs={jobs} />
      </PageSection>
      <PageSection title="Team and plan" intro="Who works on it, and the tasks the team made of the goal.">
        <Team project={project} />
        <Plan project={project} />
      </PageSection>
      <PageSection title="Rounds" intro="Each round, the lead decides the next step, and it is taken.">
        <Rounds project={project} />
      </PageSection>
      <PageSection title="Findings" intro="What the meetings and the code showed, which the later steps are told of.">
        <Findings project={project} />
      </PageSection>
      <PageSection title="Steps" intro="Each meeting and each run of code. Open one to read what was said or run.">
        <Steps project={project} />
      </PageSection>
    </>
  );
}

// One project: what it is for, how it is going, and what it has found
export function ProjectPage({ id }: { id: string }) {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const project = useProject(id, report, projectKey(jobs.jobs, jobs.finished, id));
  // What a project may be asked does not change with the work on it
  const list = useProjectsList(report, String(jobs.finished));

  return (
    <>
      <Link
        href="/projects"
        className="inline-flex items-center gap-1 self-start rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        All projects
      </Link>
      <Looked state={project.value} label="Looking at the project" failure="The project could not be looked at." onRetry={project.reload}>
        {(value) => (
          <Looked state={list.value} label="Looking at what a project takes" failure="What a project takes could not be looked at." onRetry={list.reload}>
            {(limits) => <ProjectBody project={value} list={limits} jobs={jobs} />}
          </Looked>
        )}
      </Looked>
    </>
  );
}
