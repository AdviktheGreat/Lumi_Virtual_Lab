"use client";

import { Badge } from "@/components/ui/badge";
import { actionLabel, outcomeLabel, taskStatusLabel } from "@/lib/projects";
import type { Project, ProjectMember, ProjectRound } from "@/lib/types";

function Member({ member, role }: { member: ProjectMember; role: string }) {
  return (
    <li className="flex flex-col rounded-lg border border-border px-3 py-2" data-testid="project-member">
      <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
        {member.title}
        <Badge variant="outline">{role}</Badge>
      </span>
      {member.expertise && <span className="break-words text-xs text-muted-foreground">{member.expertise}</span>}
    </li>
  );
}

// Who works on a project: the lead, the scientists on the team, and the critic who reviews the answer
export function Team({ project }: { project: Project }) {
  const { lead, critic, team } = project;
  if (lead === null && critic === null && team.length === 0) return <p className="text-sm text-muted-foreground">Nobody is on the project yet.</p>;

  return (
    <div className="flex flex-col gap-2">
      <ul aria-label="Team" className="grid gap-2 sm:grid-cols-2">
        {lead && <Member member={lead} role="Lead" />}
        {team.map((member) => (
          <Member key={member.title} member={member} role="Team" />
        ))}
        {critic && <Member member={critic} role="Critic" />}
      </ul>
      {team.length === 0 && project.team_mode === "chosen" && (
        <p className="text-xs text-muted-foreground">
          {project.state === "new" ? "The lead chooses the team when the project is started." : "The lead worked without a team."}
        </p>
      )}
    </div>
  );
}

// The work the project needs, in the order it is to be done, and how far each task has got
export function Plan({ project }: { project: Project }) {
  if (project.plan.length === 0) return <p className="text-sm text-muted-foreground">There is no plan until the team has made one.</p>;

  return (
    <ol aria-label="Plan" className="flex flex-col gap-1.5">
      {project.plan.map((task, number) => (
        <li key={number} className="flex items-start gap-2 text-sm" data-testid="project-task">
          <Badge variant={task.status === "done" ? "default" : "outline"} className="mt-0.5">
            {taskStatusLabel(task.status)}
          </Badge>
          <span className={task.status === "dropped" ? "min-w-0 break-words text-muted-foreground line-through" : "min-w-0 break-words"}>
            {task.task}
          </span>
        </li>
      ))}
    </ol>
  );
}

function Round({ round }: { round: ProjectRound }) {
  const failed = round.outcome === "invalid" || round.outcome === "out_of_budget";

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="project-round">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium">
          Round {round.number}: {actionLabel(round.action)}
        </h3>
        <Badge variant={round.outcome === "finished" ? "default" : failed ? "destructive" : "outline"}>
          {outcomeLabel(round.outcome)}
        </Badge>
      </div>
      {round.participants.length > 0 && <p className="text-xs text-muted-foreground">With {round.participants.join(", ")}</p>}
      {round.agenda && <p className="whitespace-pre-wrap break-words text-sm">{round.agenda}</p>}
      {round.questions.length > 0 && (
        <ul aria-label={`Questions of round ${round.number}`} className="list-disc pl-5 text-sm">
          {round.questions.map((question, number) => (
            <li key={number} className="break-words">
              {question}
            </li>
          ))}
        </ul>
      )}
      {round.rationale && <p className="break-words text-xs text-muted-foreground">Why: {round.rationale}</p>}
      {round.progress && <p className="break-words text-xs text-muted-foreground">What was established so far: {round.progress}</p>}
      {round.note && (
        <p className={round.outcome === "invalid" ? "break-words text-xs text-destructive" : "break-words text-xs text-muted-foreground"}>{round.note}</p>
      )}
      {round.found.length > 0 && <p className="text-xs text-muted-foreground">Found {round.found.join(", ")}</p>}
    </li>
  );
}

// What the lead decided in each round, and how it went
export function Rounds({ project }: { project: Project }) {
  if (project.rounds.length === 0) return <p className="text-sm text-muted-foreground">No round has been taken yet.</p>;

  return (
    <ol aria-label="Rounds" className="flex flex-col gap-2">
      {project.rounds.map((round) => (
        <Round key={round.number} round={round} />
      ))}
    </ol>
  );
}
