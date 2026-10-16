"use client";

import { useId, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { projectAddress } from "@/components/project-list";
import { describedBy, Field } from "@/components/settings-fields";
import { useServer } from "@/components/server-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Radio } from "@/components/ui/radio";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { describeCode } from "@/lib/benchmarks";
import { checkProject, EMPTY_PROJECT, MAX_PROJECT_TITLE, type ProjectDraft } from "@/lib/projects";
import type { ProjectLimitName, ProjectsList } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";

// A number of a project's, which is blank for what the server says it is by default
function Count({
  id,
  name,
  list,
  value,
  problem,
  busy,
  onChange,
}: {
  id: string;
  name: ProjectLimitName;
  list: ProjectsList;
  value: string;
  problem: string | undefined;
  busy: boolean;
  onChange: (value: string) => void;
}) {
  const { label, default: normal, least, most } = list.limits[name];

  return (
    <Field id={id} label={label} hint={`Blank is ${normal}. From ${least} to ${most}.`} problem={problem}>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        inputMode="numeric"
        autoComplete="off"
        readOnly={busy}
        aria-invalid={problem !== undefined}
        aria-describedby={describedBy(id, { hint: true, problem: problem !== undefined })}
      />
    </Field>
  );
}

// Makes a project, which has done nothing yet: it says what the project is for, who works on it, and how what the work finds
// is passed on, and the work is started from its own page, where how much it may spend is said
export function NewProject({ list }: { list: ProjectsList }) {
  const { report } = useServer();
  const router = useRouter();
  const id = useId();
  const [draft, setDraft] = useState<ProjectDraft>({ ...EMPTY_PROJECT, team: list.default_team, memory: list.default_memory });
  const [tried, setTried] = useState(false);
  const attempt = useAttempt(report);
  const checked = checkProject(draft, list);
  const problems = tried ? checked.problems : {};
  const field = (name: string) => `${id}-${name}`;

  function change(part: Partial<ProjectDraft>) {
    setDraft((was) => ({ ...was, ...part }));
  }

  async function make() {
    setTried(true);
    const body = checked.value;
    if (body === null) return;
    const project = await attempt.run(() => api.makeProject(body));
    if (project) router.push(projectAddress(project.id));
  }

  return (
    <form
      aria-label="Make a project"
      onSubmit={(event) => {
        event.preventDefault();
        void make();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <Field
        id={field("goal")}
        label="Goal"
        hint="What the project is to find out or make, said so that it can be told whether it has."
        problem={problems.goal}
      >
        <Textarea
          id={field("goal")}
          value={draft.goal}
          onChange={(event) => change({ goal: event.target.value })}
          rows={4}
          readOnly={attempt.busy}
          aria-invalid={problems.goal !== undefined}
          aria-describedby={describedBy(field("goal"), { hint: true, problem: problems.goal !== undefined })}
        />
      </Field>
      <Field id={field("title")} label="Title" hint="Optional. Blank is the start of the goal." problem={problems.title}>
        <Input
          id={field("title")}
          value={draft.title}
          onChange={(event) => change({ title: event.target.value })}
          maxLength={MAX_PROJECT_TITLE * 4}
          autoComplete="off"
          readOnly={attempt.busy}
          aria-invalid={problems.title !== undefined}
          aria-describedby={describedBy(field("title"), { hint: true, problem: problems.title !== undefined })}
        />
      </Field>

      <fieldset className="flex flex-col gap-2" disabled={attempt.busy}>
        <legend className="mb-1.5 text-sm font-medium">Who works on it</legend>
        {list.teams.map((team) => (
          <label key={team.id} className="flex items-start gap-2 text-sm">
            <Radio name={field("team")} checked={draft.team === team.id} onChange={() => change({ team: team.id })} className="mt-0.5" />
            <span className="flex min-w-0 flex-col">
              <span>{team.title}</span>
              <span className="text-xs text-muted-foreground">{team.summary}</span>
            </span>
          </label>
        ))}
        {draft.team === "lab" && (
          <p className="text-xs text-muted-foreground">
            {list.team.length > 0 ? `The lab has ${list.team.join(", ")}.` : "The lab has no scientists but the lead and the critic."}
          </p>
        )}
      </fieldset>

      <fieldset className="flex flex-col gap-2" disabled={attempt.busy}>
        <legend className="mb-1.5 text-sm font-medium">What each step is told of what was found</legend>
        {list.memories.map((memory) => (
          <label key={memory.id} className="flex items-start gap-2 text-sm">
            <Radio
              name={field("memory")}
              checked={draft.memory === memory.id}
              onChange={() => change({ memory: memory.id })}
              className="mt-0.5"
            />
            <span className="flex min-w-0 flex-col">
              <span>{memory.title}</span>
              <span className="text-xs text-muted-foreground">{memory.summary}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <Count
          id={field("team-size")}
          name="max_team_size"
          list={list}
          value={draft.teamSize}
          problem={problems.teamSize}
          busy={attempt.busy}
          onChange={(teamSize) => change({ teamSize })}
        />
        <Count
          id={field("meeting-rounds")}
          name="meeting_rounds"
          list={list}
          value={draft.meetingRounds}
          problem={problems.meetingRounds}
          busy={attempt.busy}
          onChange={(meetingRounds) => change({ meetingRounds })}
        />
        {draft.memory === "bm25" && (
          <Count
            id={field("findings")}
            name="findings_per_step"
            list={list}
            value={draft.findings}
            problem={problems.findings}
            busy={attempt.busy}
            onChange={(findings) => change({ findings })}
          />
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        The project is worked on by {list.model}, led by {list.lead ?? "the lead"}, and {describeCode(list.code)}, as the settings say now.
        The project keeps all three.
      </p>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" disabled={attempt.busy}>
          <Plus />
          {attempt.busy ? "Making…" : "Make the project"}
        </Button>
      </div>
    </form>
  );
}
