import { describe, expect, it } from "vitest";
import {
  actionLabel,
  checkProject,
  checkStart,
  describeSetup,
  EMPTY_PROJECT,
  lastProjectJob,
  projectFacts,
  projectJob,
  projectKey,
  projectStateNote,
  startDraftFor,
  stepTitle,
} from "./projects";
import type { Job, ProjectEntry, ProjectsList } from "./types";

function job(changes: Partial<Job> = {}): Job {
  return {
    id: "j1",
    kind: "project",
    subject: "nanobodies",
    title: "Working on Nanobodies",
    state: "running",
    message: "",
    progress: {},
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    finished_at: null,
    log_total: 0,
    ...changes,
  };
}

function entry(changes: Partial<ProjectEntry> = {}): ProjectEntry {
  return {
    id: "nanobodies",
    title: "Nanobodies",
    goal: "Find which binds better.",
    created_at: "2026-01-01T00:00:00Z",
    model: "gpt-5.2",
    state: "finished",
    rounds_taken: 2,
    tasks: 3,
    tasks_done: 2,
    spent: 0.4321,
    max_cost: 2,
    job: null,
    ...changes,
  };
}

const limits: ProjectsList["limits"] = {
  max_team_size: { label: "The most scientists on the team", default: 3, least: 0, most: 6 },
  meeting_rounds: { label: "The rounds of discussion in a meeting", default: 1, least: 0, most: 5 },
  findings_per_step: { label: "The most findings a step is given", default: 8, least: 1, most: 50 },
  max_rounds: { label: "The most rounds", default: 10, least: 1, most: 100 },
  max_stalled_rounds: { label: "The most rounds in a row without more of the plan done", default: 3, least: 1, most: 100 },
};
const list = { limits, max_goal_chars: 100 };

describe("how a project is told of", () => {
  it("says how far it has got, and what it has spent of what it may", () => {
    expect(projectFacts(entry())).toBe("2 rounds · 2 of 3 tasks done · spent $0.43 of $2.00");
    expect(projectFacts(entry({ rounds_taken: 1, tasks: 0, tasks_done: 0, spent: 0, max_cost: null }))).toBe("1 round · spent $0.00");
    expect(projectFacts(entry({ state: "new" }))).toBe("Not started");
  });

  it("says how a project is set up", () => {
    const setup = { team_mode: "chosen", max_team_size: 3, memory: "pick", meeting_rounds: 1 } as const;

    expect(describeSetup(setup)).toBe("Team: the lead chooses, at most 3 · Findings: the lead picks · Meetings: 1 round of discussion");
    expect(describeSetup({ ...setup, team_mode: "lab", memory: "bm25", meeting_rounds: 0 })).toBe(
      "Team: the whole lab, at most 3 · Findings: the best matches · Meetings: 0 rounds of discussion",
    );
  });

  it("names a step by its round and what it was", () => {
    expect(stepTitle("team")).toBe("Choosing the team");
    expect(stepTitle("plan")).toBe("Making the plan");
    expect(stepTitle("round_02_meeting")).toBe("Round 2: the meeting");
    expect(stepTitle("round_11_review")).toBe("Round 11: the critic's review");
    expect(stepTitle("round_03_strange")).toBe("Round 3: strange");
    expect(stepTitle("odd")).toBe("odd");
  });

  it("says what a decision was, and what to do for a project that has not finished", () => {
    expect(actionLabel("write_code")).toBe("Code to write and run");
    expect(actionLabel("")).toBe("No decision");
    expect(projectStateNote("out_of_budget")).toContain("spend more");
    expect(projectStateNote("running")).toBe("");
  });
});

describe("the jobs of a project", () => {
  it("finds the job at work on a project, and the latest that is over", () => {
    const over = job({ id: "j0", state: "failed" });

    expect(projectJob([over, job()], "nanobodies")?.id).toBe("j1");
    expect(projectJob([job()], "other")).toBeUndefined();
    expect(lastProjectJob([job(), over], "nanobodies")?.id).toBe("j0");
    expect(lastProjectJob([job({ kind: "benchmark", state: "failed" })], "nanobodies")).toBeUndefined();
  });

  it("changes what it is as the round, or what is spent, changes, and how many jobs have ended", () => {
    const at = (round: number, spent: number) => projectKey([job({ progress: { round, spent } })], 0);

    expect(at(1, 0.1)).not.toBe(at(1, 0.2));
    expect(at(1, 0.1)).not.toBe(at(2, 0.1));
    expect(projectKey([job()], 0)).not.toBe(projectKey([job()], 1));
    expect(projectKey([job({ subject: "other", progress: { round: 3 } })], 0, "nanobodies")).toBe("0|");
    expect(projectKey(null, 2)).toBe("2|");
  });
});

describe("making a project", () => {
  it("asks for a goal, and for a title of a fit length", () => {
    const checked = checkProject({ ...EMPTY_PROJECT, title: "x".repeat(201) }, list);

    expect(checked.value).toBeNull();
    expect(checked.problems.goal).toBe("Say what the project is for.");
    expect(checked.problems.title).toBe("The title can be at most 200 characters, and this is 201.");
    expect(checkProject({ ...EMPTY_PROJECT, goal: "g".repeat(101) }, list).problems.goal).toBe(
      "The goal can be at most 100 characters, and this is 101.",
    );
  });

  it("sends only what is asked, and leaves the rest to be what the server says", () => {
    expect(checkProject({ ...EMPTY_PROJECT, goal: "  Find it.\nSoon.  " }, list).value).toEqual({
      goal: "Find it.\nSoon.",
      team: "chosen",
      memory: "pick",
    });
    expect(
      checkProject(
        { ...EMPTY_PROJECT, goal: "Find it.", title: " A  title ", team: "lab", teamSize: "2", meetingRounds: "0" },
        list,
      ).value,
    ).toEqual({ goal: "Find it.", title: "A title", team: "lab", memory: "pick", max_team_size: 2, meeting_rounds: 0 });
  });

  it("takes how many findings a step is given only where the best matches are what it is given", () => {
    const draft = { ...EMPTY_PROJECT, goal: "Find it.", findings: "5" };

    expect(checkProject(draft, list).value).toEqual({ goal: "Find it.", team: "chosen", memory: "pick" });
    expect(checkProject({ ...draft, memory: "bm25" }, list).value).toMatchObject({ memory: "bm25", findings_per_step: 5 });
    expect(checkProject({ ...draft, memory: "bm25", findings: "51" }, list).problems.findings).toBe(
      "The most findings a step is given is a whole number from 1 to 50.",
    );
  });

  it("says what is wrong with each number that does not fit", () => {
    const checked = checkProject({ ...EMPTY_PROJECT, goal: "Find it.", teamSize: "7", meetingRounds: "-1" }, list);

    expect(checked.value).toBeNull();
    expect(checked.problems.teamSize).toBe("The most scientists on the team is a whole number from 0 to 6.");
    expect(checked.problems.meetingRounds).toBe("The rounds of discussion in a meeting is a whole number from 0 to 5.");
  });
});

describe("starting work on a project", () => {
  it("always asks for the most it may spend", () => {
    expect(checkStart({ budget: "", rounds: "", stalled: "" }, limits).problems.budget).toBe("Say the most it may spend.");
    expect(checkStart({ budget: "lots", rounds: "", stalled: "" }, limits).problems.budget).toBe(
      "The most it may spend is an amount in dollars, such as 1 or 0.50.",
    );
  });

  it("sends the rounds only where they are given", () => {
    expect(checkStart({ budget: "$2", rounds: "", stalled: "" }, limits).value).toEqual({ max_cost: 2 });
    expect(checkStart({ budget: "2", rounds: "5", stalled: "2" }, limits).value).toEqual({
      max_cost: 2,
      max_rounds: 5,
      max_stalled_rounds: 2,
    });
    expect(checkStart({ budget: "2", rounds: "101", stalled: "0" }, limits).problems).toEqual({
      rounds: "The most rounds is a whole number from 1 to 100.",
      stalled: "The most rounds in a row without more of the plan done is a whole number from 1 to 100.",
    });
  });

  it("wants more than a project has spent already, since what it may spend is over all the times it is worked on", () => {
    expect(checkStart({ budget: "0.5", rounds: "", stalled: "" }, limits, 0.43).value).toEqual({ max_cost: 0.5 });
    expect(checkStart({ budget: "0.4", rounds: "", stalled: "" }, limits, 0.43).problems.budget).toContain("it has spent $0.43 already");
    expect(startDraftFor({ spent: 0 }).budget).toBe("1");
    expect(startDraftFor({ spent: 0.43 }).budget).toBe("2");
    expect(startDraftFor({ spent: 2 }).budget).toBe("3");
  });
});
