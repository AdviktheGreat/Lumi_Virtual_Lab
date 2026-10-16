"use client";

import { useSearchParams } from "next/navigation";
import { Looked } from "@/components/looked";
import { PageHeader } from "@/components/page-header";
import { PageSection } from "@/components/page-section";
import { ProjectList } from "@/components/project-list";
import { NewProject } from "@/components/project-new";
import { ProjectPage } from "@/components/project-page";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { projectKey } from "@/lib/projects";
import { useProjectsList } from "@/lib/use-projects";

// The projects there are, and the making of one
function Projects() {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const list = useProjectsList(report, projectKey(jobs.jobs, jobs.finished));

  return (
    <>
      <p className="text-sm text-muted-foreground">
        A project is research with a goal, which the lead scientist carries out round by round: the lead chooses a team and makes a plan,
        then decides each step, which is a meeting, code to write and run, or a change to the team, until the critic agrees that the
        answer meets the goal. Working on a project spends money on the model in the settings, so each is told the most it may spend.
      </p>
      <PageSection title="Projects">
        <Looked state={list.value} label="Looking at the projects" failure="The projects could not be looked at." onRetry={list.reload}>
          {(value) => <ProjectList list={value} />}
        </Looked>
      </PageSection>
      <PageSection title="Make a project">
        <Looked state={list.value} label="Looking at what a project takes" failure="What a project takes could not be looked at." onRetry={list.reload}>
          {(value) => <NewProject list={value} />}
        </Looked>
      </PageSection>
    </>
  );
}

// The page of projects: the projects, or one project, which is named in the address's query as a conversation is
export function ProjectsView() {
  const id = useSearchParams().get("id");

  return (
    <>
      <PageHeader>
        <h1 className="min-w-0 flex-1 truncate text-sm font-medium">Projects</h1>
      </PageHeader>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-10 px-4 py-8">
          {id ? <ProjectPage key={id} id={id} /> : <Projects />}
        </div>
      </div>
    </>
  );
}
