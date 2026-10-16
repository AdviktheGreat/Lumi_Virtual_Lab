import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { expect, test } from "../fixtures";

// The projects are the workspace's, so each test takes what it made away, and none is run beside another
test.describe.configure({ mode: "serial" });

const GOAL = "Find which of two nanobodies binds KP.3 better.";

interface Entry {
  id: string;
  job: string | null;
}

// Takes away every project, stopping what is at work on one first
async function clear(page: Page) {
  const { projects } = (await (await page.request.get("/api/projects")).json()) as { projects: Entry[] };
  for (const project of projects) {
    if (project.job) await page.request.post(`/api/setup/jobs/${project.job}/stop`);
    await expect
      .poll(async () => (await page.request.delete(`/api/projects/${project.id}`)).status(), { timeout: 20_000 })
      .toBe(200);
  }
}

test.beforeEach(async ({ page }) => {
  await clear(page);
});

test.afterEach(async ({ page }) => {
  await clear(page);
});

// Makes a project through the server, so that what a test is about is the page
async function arrange(page: Page, body: Record<string, unknown>): Promise<string> {
  const made = await page.request.post("/api/projects", { data: body });
  expect(made.status()).toBe(201);

  return (await made.json()).id;
}

// Works on a project through the server, and waits until that is done
async function workThrough(page: Page, id: string) {
  const started = await page.request.post(`/api/projects/${id}/start`, { data: { max_cost: 5 } });
  expect(started.status()).toBe(202);
  await expect
    .poll(async () => (await (await page.request.get(`/api/projects/${id}`)).json()).job, { timeout: 30_000 })
    .toBeNull();
}

// How many jobs have been started on projects, which is how many have worked on one
async function projectJobs(page: Page): Promise<number> {
  const { jobs } = (await (await page.request.get("/api/setup/jobs")).json()) as { jobs: { kind: string }[] };

  return jobs.filter((job) => job.kind === "project").length;
}

async function openProject(page: Page, id: string, title: string) {
  await page.goto(`/projects?id=${id}`);
  await expect(page.getByRole("heading", { name: title, level: 2 })).toBeVisible();
}

const form = (page: Page, name: string) => page.getByRole("form", { name });
const rounds = (page: Page) => page.getByRole("list", { name: "Rounds" }).getByTestId("project-round");
const status = (page: Page) => page.getByRole("region", { name: "What is being done" });

test("makes a project, works on it with a budget, and shows its team, plan, rounds, findings, and answer", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Projects", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Projects", level: 1 })).toBeVisible();
  await expect(page.getByText("No project has been made yet.")).toBeVisible();

  const make = form(page, "Make a project");
  await make.getByRole("button", { name: "Make the project" }).click();
  await expect(make.getByRole("alert")).toHaveText("Say what the project is for.");
  await make.getByLabel("Goal", { exact: true }).fill(GOAL);
  await make.getByLabel("Title", { exact: true }).fill("Nanobody trial");
  await make.getByRole("button", { name: "Make the project" }).click();

  await expect(page.getByRole("heading", { name: "Nanobody trial", level: 2 })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("id")).toBe("nanobody-trial");
  await expect(page.getByText(GOAL, { exact: true })).toBeVisible();
  await expect(page.getByText("No round has been taken yet.")).toBeVisible();
  await expect(page.getByText("Nothing has been found yet.")).toBeVisible();
  await expect(page.getByText("The lead chooses the team when the project is started.")).toBeVisible();

  const work = form(page, "Work on the project");
  await work.getByLabel("Most it may spend, in dollars").fill("2");
  await work.getByRole("button", { name: "Start the project" }).click();

  await expect(status(page).getByText("Done", { exact: true })).toBeVisible({ timeout: 30_000 });
  const outcome = page.getByRole("region", { name: "How it ended" });
  await expect(outcome).toContainText("Finished");
  await expect(outcome.getByTestId("project-answer")).toContainText("Nanobody A binds KP.3 better, as the comparison shows.");
  await expect(outcome.getByRole("link", { name: "Download the report" })).toHaveAttribute("href", "/api/projects/nanobody-trial/report");
  await expect(work).toHaveCount(0);
  await expect(page.getByText("There is nothing left to do.")).toBeVisible();

  const team = page.getByRole("list", { name: "Team" });
  await expect(team).toContainText("Principal Investigator");
  await expect(team).toContainText("Immunologist");
  await expect(team).toContainText("Scientific Critic");
  const tasks = page.getByTestId("project-task");
  await expect(tasks).toHaveCount(2);
  await expect(tasks.first()).toContainText("Done");
  await expect(tasks.first()).toContainText("Compare how strongly the two nanobodies bind KP.3");

  await expect(rounds(page)).toHaveCount(2);
  await expect(rounds(page).first()).toContainText("Round 1: A meeting with one scientist");
  await expect(rounds(page).first()).toContainText("With Immunologist");
  await expect(rounds(page).first()).toContainText("Which has the lower dissociation constant?");
  await expect(rounds(page).last()).toContainText("Round 2: The answer, put to the critic");
  await expect(rounds(page).last()).toContainText("The critic agreed");

  const findings = page.getByRole("list", { name: "Findings" }).getByTestId("project-finding");
  await expect(findings).toHaveCount(1);
  await expect(findings.first()).toContainText("Nanobody A binds KP.3 more strongly than nanobody B.");
  await expect(findings.first()).toContainText("F1 · round 1 · Round 1: the meeting");

  const steps = page.getByRole("table", { name: "Steps" });
  await expect(steps.getByTestId("project-step").first()).toContainText("Choosing the team");
  await expect(steps).toContainText("Making the plan");
  await expect(steps).toContainText("Round 2: the critic's review");
  await page.getByRole("button", { name: "Show step Round 1: the meeting" }).click();
  await expect(page.getByRole("list", { name: "What was said in the step" })).toContainText("Immunologist");
  await expect(page.getByLabel("What the step produced")).toContainText("Nanobody A binds KP.3 more strongly");
  await page.getByRole("button", { name: "Hide step Round 1: the meeting" }).click();
  await expect(page.getByRole("list", { name: "What was said in the step" })).toHaveCount(0);

  await page.getByRole("link", { name: "All projects" }).click();
  const row = page.getByTestId("project");
  await expect(row).toContainText("Nanobody trial");
  await expect(row).toContainText("Finished");
  await expect(row).toContainText("2 rounds · 2 of 2 tasks done");
});

test("follows the work while it goes on, stops it, and carries on from where it stopped", async ({ page }) => {
  const id = await arrange(page, { goal: `hold: ${GOAL}`, title: "Slow project" });
  await openProject(page, id, "Slow project");

  await form(page, "Work on the project").getByRole("button", { name: "Start the project" }).click();

  await expect(status(page).getByRole("progressbar", { name: "Progress: Working on Slow project" })).toBeVisible();
  // Nothing else is done to a project while it is worked on
  await expect(form(page, "Work on the project").getByRole("button", { name: "Working…" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Delete Slow project" })).toBeDisabled();
  await expect(status(page).getByText(/^Round 1 of at most 10/)).toBeVisible({ timeout: 15_000 });

  await status(page).getByRole("button", { name: "Stop: Working on Slow project" }).click();
  await expect(status(page).getByRole("progressbar")).toHaveCount(0, { timeout: 20_000 });
  await expect(status(page).getByText("Stopped", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "How it ended" })).toContainText("Stopped at the person's request.");
  // What was done is kept: the team and the plan were made before the first round
  await expect(page.getByTestId("project-task")).toHaveCount(2);
  const carry = form(page, "Work on the project").getByRole("button", { name: "Carry on" });
  await expect(carry).toBeEnabled();

  await carry.click();
  await expect(status(page).getByText("Done", { exact: true })).toBeVisible({ timeout: 40_000 });
  await expect(page.getByRole("region", { name: "How it ended" })).toContainText("Finished");
  await expect(rounds(page).last()).toContainText("The critic agreed");
});

test("shows what the critic objected to, and the answer it accepted after", async ({ page }) => {
  const id = await arrange(page, { goal: `object: ${GOAL}`, title: "Doubted project" });
  await workThrough(page, id);
  await openProject(page, id, "Doubted project");

  await expect(rounds(page)).toHaveCount(3);
  await expect(rounds(page).nth(1)).toContainText("The critic objected");
  await expect(rounds(page).nth(1)).toContainText("Show the affinities that were measured.");
  await expect(rounds(page).nth(2)).toContainText("The critic agreed");
  await expect(page.getByTestId("project-answer")).toContainText("Nanobody A binds KP.3 better");
});

test("says why a project failed, and that carrying on is possible", async ({ page }) => {
  const id = await arrange(page, { goal: `fail: ${GOAL}`, title: "Failing project" });
  await workThrough(page, id);
  await openProject(page, id, "Failing project");

  const outcome = page.getByRole("region", { name: "How it ended" });
  await expect(outcome).toContainText("Failed");
  await expect(outcome.getByRole("alert")).toContainText("The scripted model failed, as it was asked to");
  await expect(page.getByRole("region", { name: "What is being done" }).getByText("Failed", { exact: true })).toBeVisible();
  await expect(form(page, "Work on the project").getByRole("button", { name: "Carry on" })).toBeEnabled();
});

test("asks for what is wrong with a project, and what it may spend, to be put right before it is sent", async ({ page }) => {
  const before = await projectJobs(page);
  await page.goto("/projects");
  const make = form(page, "Make a project");

  await make.getByLabel("Goal", { exact: true }).fill(GOAL);
  await make.getByLabel("The most scientists on the team").fill("7");
  await make.getByLabel("The rounds of discussion in a meeting").fill("two");
  await make.getByRole("button", { name: "Make the project" }).click();
  await expect(make.getByRole("alert")).toHaveCount(2);
  await expect(make).toContainText("The most scientists on the team is a whole number from 0 to 6.");
  await expect(make).toContainText("The rounds of discussion in a meeting is a whole number from 0 to 5.");

  // How many findings a step is given matters only where the best matches are what it is given
  await expect(make.getByLabel("The most findings a step is given")).toHaveCount(0);
  await make.getByRole("radio", { name: /The best matches/ }).check();
  await expect(make.getByLabel("The most findings a step is given")).toBeVisible();
  await make.getByLabel("The most findings a step is given").fill("5");
  await make.getByRole("radio", { name: /The whole lab/ }).check();
  await expect(make).toContainText("The lab has ");
  await make.getByLabel("The most scientists on the team").fill("2");
  await make.getByLabel("The rounds of discussion in a meeting").fill("0");
  await make.getByRole("button", { name: "Make the project" }).click();

  await expect(page.getByRole("heading", { level: 2 }).first()).toContainText("Find which of two nanobodies binds KP.3 better.");
  await expect(page.getByText("Team: the whole lab, at most 2 · Findings: the best matches · Meetings: 0 rounds of discussion")).toBeVisible();
  await expect(page.getByRole("list", { name: "Team" })).toContainText("Immunologist");

  const start = form(page, "Work on the project");
  await start.getByLabel("Most it may spend, in dollars").fill("lots");
  await start.getByLabel("The most rounds", { exact: true }).fill("101");
  await start.getByRole("button", { name: "Start the project" }).click();
  await expect(start.getByRole("alert")).toHaveCount(2);
  await expect(start).toContainText("The most it may spend is an amount in dollars, such as 1 or 0.50.");
  await expect(start).toContainText("The most rounds is a whole number from 1 to 100.");
  expect(await projectJobs(page)).toBe(before);

  await page.route("**/api/projects/*/start", (route) =>
    route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "missing_keys", message: "gpt-5.2 needs OPENAI_API_KEY, which is not set. Add it in the settings.", missing: ["OPENAI_API_KEY"] },
      }),
    }),
  );
  await start.getByLabel("Most it may spend, in dollars").fill("1");
  await start.getByLabel("The most rounds", { exact: true }).fill("");
  await start.getByRole("button", { name: "Start the project" }).click();
  const problem = start.getByRole("alert");
  await expect(problem).toContainText("gpt-5.2 needs OPENAI_API_KEY");
  await expect(problem.getByRole("button", { name: "Add the key" })).toBeVisible();
});

test("deletes a project, after asking", async ({ page }) => {
  const id = await arrange(page, { goal: GOAL, title: "Short lived" });
  await openProject(page, id, "Short lived");

  await page.getByRole("button", { name: "Delete Short lived" }).click();
  const asking = page.getByRole("alertdialog", { name: "Delete Short lived?" });
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  expect((await page.request.get(`/api/projects/${id}`)).status()).toBe(200);

  await page.getByRole("button", { name: "Delete Short lived" }).click();
  await page.getByRole("alertdialog", { name: "Delete Short lived?" }).getByRole("button", { name: "Delete", exact: true }).click();

  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByText("No project has been made yet.")).toBeVisible();
  expect((await page.request.get(`/api/projects/${id}`)).status()).toBe(404);
});

test("says that a project is not there, rather than showing nothing", async ({ page }) => {
  await page.goto("/projects?id=nowhere");

  await expect(page.getByRole("alert").filter({ hasText: "The project could not be looked at." })).toContainText("There is no project");
  await expect(page.getByRole("link", { name: "All projects" })).toBeVisible();
});

test("has nothing wrong that axe can find, in the projects, or in a project that was worked on", async ({ page }) => {
  const id = await arrange(page, { goal: GOAL, title: "Accessible project" });
  await workThrough(page, id);

  await page.goto("/projects");
  await expect(page.getByTestId("project")).toHaveCount(1);
  expect(await accessibilityProblems(page)).toEqual([]);

  await openProject(page, id, "Accessible project");
  await expect(rounds(page)).toHaveCount(2);
  await page.getByRole("button", { name: "Show step Round 1: the meeting" }).click();
  await expect(page.getByRole("list", { name: "What was said in the step" })).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
});
