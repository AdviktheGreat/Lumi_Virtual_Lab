import { characters, count, dollars, whole, type Checked } from "./checks";
import { formatCost } from "./format";
import { tidy } from "./scientists";
import { activeJob, isActive } from "./setup";
import type {
  Job,
  NewProject,
  Project,
  ProjectAction,
  ProjectEntry,
  ProjectMemory,
  ProjectRound,
  ProjectsList,
  ProjectStartOptions,
  ProjectState,
  ProjectTeam,
} from "./types";

// What the server takes of a project's title
export const MAX_PROJECT_TITLE = 200;

// How many findings, and steps' rows, are shown of a project's, before more are asked for
export const ROWS_SHOWN = 50;

// The kind of the job that works on a project, of which one is at work at a time
export const JOB_KIND = "project";

export const STATE_LABELS: Record<ProjectState, string> = {
  new: "Not started",
  running: "Working",
  finished: "Finished",
  out_of_budget: "Out of budget",
  out_of_rounds: "Out of rounds",
  stalled: "Stalled",
  stopped: "Stopped",
  failed: "Failed",
  interrupted: "Interrupted",
};

export function projectStateLabel(state: ProjectState): string {
  return STATE_LABELS[state] ?? state;
}

// What a project that is not at work says of how it stands, and what to do to carry it on
const STATE_NOTES: Record<ProjectState, string> = {
  new: "Nothing has been done yet.",
  running: "",
  finished: "The critic agreed that the answer meets the goal.",
  out_of_budget: "It spent all it was allowed. Say it may spend more, and it carries on from where it was.",
  out_of_rounds: "It took all the rounds it was allowed without finishing. Allow it more rounds, and it carries on from where it was.",
  stalled: "No more of the plan was done for some rounds, so it ended. Carrying on tries again, and more rounds without progress may be allowed.",
  stopped: "It was stopped. What was done is kept, and carrying on takes it from there.",
  failed: "It failed. What was done is kept, and carrying on takes it from there.",
  interrupted: "The server stopped while it was at work. What was done is kept, and carrying on takes it from there.",
};

export function projectStateNote(state: ProjectState): string {
  return STATE_NOTES[state] ?? "";
}

export const ACTION_LABELS: Record<ProjectAction, string> = {
  team_meeting: "A team meeting",
  individual_meeting: "A meeting with one scientist",
  write_code: "Code to write and run",
  change_team: "A change to the team",
  finish: "The answer, put to the critic",
};

export function actionLabel(action: ProjectRound["action"]): string {
  return action === "" ? "No decision" : (ACTION_LABELS[action] ?? action);
}

const ROUND_OUTCOMES: Record<string, string> = {
  done: "Done",
  invalid: "Could not be carried out",
  objected: "The critic objected",
  finished: "The critic agreed",
  stopped: "Stopped",
  out_of_budget: "Ran out of budget",
  running: "In progress",
  interrupted: "Interrupted",
};

export function outcomeLabel(outcome: string): string {
  return ROUND_OUTCOMES[outcome] ?? outcome;
}

const TASK_STATUSES: Record<string, string> = {
  "to do": "To do",
  "in progress": "In progress",
  done: "Done",
  dropped: "Dropped",
};

export function taskStatusLabel(status: string): string {
  return TASK_STATUSES[status] ?? status;
}

export const TEAM_LABELS: Record<ProjectTeam, string> = {
  chosen: "The lead chooses",
  lab: "The whole lab",
};

export const MEMORY_LABELS: Record<ProjectMemory, string> = {
  pick: "The lead picks",
  bm25: "The best matches",
  summaries: "Every summary",
};

const STEP_PARTS: Record<string, string> = {
  decision: "the decision",
  meeting: "the meeting",
  code: "the code that was written",
  run: "the code that was run",
  findings: "what the code showed",
  review: "the critic's review",
};

// What a step is called, from its name, which says the round it was taken in and what it was: `round_02_meeting`
export function stepTitle(name: string): string {
  if (name === "team") return "Choosing the team";
  if (name === "plan") return "Making the plan";
  const found = /^round_(\d+)_(.+)$/.exec(name);
  if (found === null) return name;

  return `Round ${Number(found[1])}: ${STEP_PARTS[found[2]] ?? found[2]}`;
}

const STEP_STATUSES: Record<string, string> = {
  completed: "Done",
  failed: "Failed",
  running: "In progress",
  interrupted: "Interrupted",
};

export function stepStatusLabel(status: string): string {
  return STEP_STATUSES[status] ?? status;
}

// How far a project has got, as a line: the rounds it took, how much of the plan is done, and what it has spent of what it
// may spend
export function projectFacts(project: ProjectEntry): string {
  if (project.state === "new") return "Not started";
  const parts = [count(project.rounds_taken, "round")];
  if (project.tasks > 0) parts.push(`${project.tasks_done} of ${count(project.tasks, "task")} done`);
  const spent = `spent ${formatCost(project.spent)}`;
  parts.push(project.max_cost === null ? spent : `${spent} of ${formatCost(project.max_cost)}`);

  return parts.join(" · ");
}

const lower = (text: string) => `${text[0].toLowerCase()}${text.slice(1)}`;

// How a project is set up, as a line: who is on the team, how findings are passed on, and how long a meeting goes on
export function describeSetup(project: Pick<Project, "team_mode" | "max_team_size" | "memory" | "meeting_rounds">): string {
  const rounds = `${count(project.meeting_rounds, "round")} of discussion`;

  return `Team: ${lower(TEAM_LABELS[project.team_mode])}, at most ${project.max_team_size} · Findings: ${lower(MEMORY_LABELS[project.memory])} · Meetings: ${rounds}`;
}

// Who works on a project, in words: the lead, with the scientists the lead chose or the lab has, and the critic
export function describeWorkers(project: Pick<Project, "lead" | "team" | "team_mode" | "critic">): string {
  const lead = project.lead?.title ?? "The lead";
  const team = project.team.map((member) => member.title);
  const who = team.length > 0 ? `${lead}, with ${team.join(", ")}` : project.team_mode === "chosen" ? `${lead}, who chooses a team` : lead;

  return project.critic ? `${who}, and ${project.critic.title} as the critic` : who;
}

// The job at work on a project, and the latest that is over, whose outcome is how it was last worked on
export function projectJob(jobs: readonly Job[], project: string): Job | undefined {
  return activeJob(jobs, JOB_KIND, project);
}

export function lastProjectJob(jobs: readonly Job[], project: string): Job | undefined {
  return jobs.find((job) => !isActive(job) && job.kind === JOB_KIND && job.subject === project);
}

// What changes as a project is worked on, so that what a page shows of projects is looked at again when it does: which
// jobs are at work, the round each is in, and what it has spent, which changes with every call to the model, and how many
// jobs have ended
export function projectKey(jobs: readonly Job[] | null, ended: number, project?: string): string {
  const at = (jobs ?? [])
    .filter((job) => isActive(job) && job.kind === JOB_KIND && (project === undefined || job.subject === project))
    .map((job) => `${job.id}:${job.progress.round ?? ""}:${job.progress.spent ?? ""}`);

  return `${ended}|${at.join(",")}`;
}

export interface ProjectDraft {
  goal: string;
  title: string;
  team: ProjectTeam;
  memory: ProjectMemory;
  teamSize: string;
  meetingRounds: string;
  findings: string;
}

export const EMPTY_PROJECT: ProjectDraft = {
  goal: "",
  title: "",
  team: "chosen",
  memory: "pick",
  teamSize: "",
  meetingRounds: "",
  findings: "",
};

type ProjectKey = "goal" | "title" | "teamSize" | "meetingRounds" | "findings";

// A number of a project's, which is blank for the default, as the server takes it, or a whole number in the range it has
function limit(
  text: string,
  name: keyof ProjectsList["limits"],
  limits: ProjectsList["limits"],
): { value: number | null; problem?: string } {
  if (text.trim() === "") return { value: null };
  const { label, least, most } = limits[name];

  return whole(text, label, least, most);
}

export function checkProject(
  draft: ProjectDraft,
  list: Pick<ProjectsList, "limits" | "max_goal_chars">,
): Checked<NewProject, ProjectKey> {
  const goal = draft.goal.trim();
  const title = tidy(draft.title);
  const problems: Partial<Record<ProjectKey, string>> = {};
  if (goal === "") problems.goal = "Say what the project is for.";
  else if (characters(goal) > list.max_goal_chars) {
    problems.goal = `The goal can be at most ${list.max_goal_chars} characters, and this is ${characters(goal)}.`;
  }
  if (characters(title) > MAX_PROJECT_TITLE) {
    problems.title = `The title can be at most ${MAX_PROJECT_TITLE} characters, and this is ${characters(title)}.`;
  }
  const teamSize = limit(draft.teamSize, "max_team_size", list.limits);
  const meetingRounds = limit(draft.meetingRounds, "meeting_rounds", list.limits);
  const findings = draft.memory === "bm25" ? limit(draft.findings, "findings_per_step", list.limits) : { value: null };
  if (teamSize.problem) problems.teamSize = teamSize.problem;
  if (meetingRounds.problem) problems.meetingRounds = meetingRounds.problem;
  if (findings.problem) problems.findings = findings.problem;

  const body: NewProject = { goal, team: draft.team, memory: draft.memory };
  if (title !== "") body.title = title;
  if (teamSize.value !== null) body.max_team_size = teamSize.value;
  if (meetingRounds.value !== null) body.meeting_rounds = meetingRounds.value;
  if (findings.value !== null) body.findings_per_step = findings.value;

  return { value: Object.keys(problems).length === 0 ? body : null, problems };
}

export interface StartDraft {
  budget: string;
  rounds: string;
  stalled: string;
}

export const EMPTY_START: StartDraft = { budget: "1", rounds: "", stalled: "" };

// What to start with for a project: for one that has spent, a little more than it has, since what it may spend is over all
// the times it is worked on
export function startDraftFor(project: Pick<ProjectEntry, "spent">): StartDraft {
  return { ...EMPTY_START, budget: project.spent > 0 ? String(Math.ceil(project.spent) + 1) : EMPTY_START.budget };
}

type StartKey = "budget" | "rounds" | "stalled";

export function checkStart(
  draft: StartDraft,
  limits: ProjectsList["limits"],
  spent = 0,
): Checked<ProjectStartOptions, StartKey> {
  const budget = dollars(draft.budget, "the most it may spend", false);
  const rounds = limit(draft.rounds, "max_rounds", limits);
  const stalled = limit(draft.stalled, "max_stalled_rounds", limits);
  const problems: Partial<Record<StartKey, string>> = {};
  if (budget.problem) problems.budget = budget.problem;
  else if (budget.value !== null && spent > 0 && budget.value <= spent) {
    problems.budget = `The most it may spend is over all the times it is worked on, and it has spent ${formatCost(spent)} already, so say more than that.`;
  }
  if (rounds.problem) problems.rounds = rounds.problem;
  if (stalled.problem) problems.stalled = stalled.problem;
  if (Object.keys(problems).length > 0 || budget.value === null) return { value: null, problems };

  const options: ProjectStartOptions = { max_cost: budget.value };
  if (rounds.value !== null) options.max_rounds = rounds.value;
  if (stalled.value !== null) options.max_stalled_rounds = stalled.value;

  return { value: options, problems };
}
