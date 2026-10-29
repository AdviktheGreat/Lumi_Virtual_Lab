"use client";

import { useSearchParams } from "next/navigation";
import { Looked } from "@/components/looked";
import { PageFrame } from "@/components/page-frame";
import { PageSection } from "@/components/page-section";
import { ProjectList } from "@/components/project-list";
import { NewProject } from "@/components/project-new";
import { ProjectPage } from "@/components/project-page";
import { useServer } from "@/components/server-provider";
import { useSetupJobs } from "@/components/setup-provider";
import { projectKey } from "@/lib/projects";
import { useProjectsList } from "@/lib/use-projects";

const INTRO =
  "A project is research with a goal, which the lead scientist carries out round by round: the lead chooses a team and makes a plan, then decides each step, which is a meeting, code to write and run, or a change to the team, until the critic agrees that the answer meets the goal. Working on a project spends money on the model in the settings, so each is told the most it may spend.";

// The projects there are, and the making of one
function Projects() {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const list = useProjectsList(report, projectKey(jobs.jobs, jobs.finished));

  return (
    <>
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

  if (id) {
    return (
      <PageFrame title="Projects">
        <ProjectPage key={id} id={id} />
      </PageFrame>
    );
  }

  return (
    <PageFrame title="Projects" intro={INTRO}>
      <Projects />
    </PageFrame>
  );
}
