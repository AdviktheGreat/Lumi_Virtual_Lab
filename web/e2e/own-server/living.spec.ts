import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { expect, test } from "../fixtures";

// How the page says an agent is now, and what a newer version of its code would change. Where the code is now, what PyPI says of the
// versions that are pinned, and the package's own check are stand-ins (see scripted_server.py): code whose address says "moves" is at a
// newer commit once it has been asked of, the lock of an agent whose title says "yanked" pins a version that was yanked, and the tools
// of code whose address says "breaks" give something else
test.describe.configure({ mode: "serial" });

const TESTED = "https://github.com/example/tested-cellmapper";
const BREAKS = "https://github.com/example/breaks-tested-cellmapper";
// The server remembers which code has moved on for as long as it runs, so each try is of an address of its own
const moves = () => `https://github.com/example/moves-tested-cellmapper-${Date.now()}`;

async function clear(page: Page) {
  const { jobs } = await (await page.request.get("/api/setup/jobs")).json();
  for (const job of jobs.filter((job: { kind: string; state: string }) => job.kind.startsWith("paperagent") && job.state === "running")) {
    await page.request.post(`/api/setup/jobs/${job.id}/stop`);
  }
  const { agents } = await (await page.request.get("/api/paperagents")).json();
  for (const agent of agents) {
    await expect.poll(async () => (await page.request.delete(`/api/paperagents/${agent.id}`)).status(), { timeout: 20_000 }).toBe(200);
  }
}

test.beforeEach(async ({ page }) => {
  await clear(page);
});

test.afterEach(async ({ page }) => {
  await clear(page);
});

const healthOf = async (page: Page, id: string) => (await page.request.get(`/api/paperagents/${id}/health`)).json();
const section = (page: Page) => page.getByRole("region", { name: "Health", exact: true });
const found = (page: Page) => page.getByTestId("living-found");
const lookNow = (page: Page) => section(page).getByRole("button", { name: "Look at it now" });
const schedule = (page: Page) => page.getByRole("form", { name: "Look at it on a schedule" });

// Makes an agent through the server, step after step, up to its tools, waiting for each
async function agentWithTools(page: Page, title: string, repo: string): Promise<string> {
  const made = await page.request.post("/api/paperagents", { data: { title, paper: { kind: "file" }, repo } });
  expect(made.status()).toBe(201);
  const id: string = (await made.json()).id;
  for (const [step, part] of [
    ["repository", "repository"],
    ["environment", "environment"],
    ["reference", "reference"],
    ["tools", "tools"],
  ]) {
    const started = await page.request.post(`/api/paperagents/${id}/${step}`, { data: {} });
    expect(started.status(), step).toBe(202);
    await expect.poll(async () => (await (await page.request.get(`/api/paperagents/${id}/${part}`)).json()).job, { timeout: 30_000 }).toBeNull();
  }
  expect((await (await page.request.get(`/api/paperagents/${id}/tools`)).json()).kept).toMatchObject({ complete: true });

  return id;
}

async function openAgent(page: Page, id: string, title: string) {
  await page.goto(`/papers?agent=${id}`);
  await expect(page.getByRole("heading", { name: title, level: 2 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Health", level: 2, exact: true })).toBeVisible();
}

// Starts a look from the page and waits for what it found to be shown
async function lookAt(page: Page, id: string) {
  await lookNow(page).click();
  await expect.poll(async () => (await healthOf(page, id)).job, { timeout: 30_000 }).toBeNull();
  await expect(found(page)).toBeVisible();
}

test("says that an agent is looked at by running its tools, which it has none of until they are made", async ({ page }) => {
  const made = await page.request.post("/api/paperagents", { data: { title: "Toolless mapper", paper: { kind: "file" }, repo: TESTED } });
  const id: string = (await made.json()).id;
  await openAgent(page, id, "Toolless mapper");
  await expect(section(page).getByTestId("living-no-tools")).toHaveText("Make the tools first. An agent is looked at by running its tools again.");
  await expect(lookNow(page)).toHaveCount(0);
  await expect(schedule(page)).toHaveCount(0);
  const asked = await page.request.post(`/api/paperagents/${id}/health`);
  expect(asked.status()).toBe(422);
  expect((await asked.json()).error.code).toBe("no_tools");
});

test("looks at an agent, says that it is healthy and what each part of the look found, and keeps what earlier looks said", async ({ page }) => {
  const id = await agentWithTools(page, "Healthy mapper", TESTED);
  await openAgent(page, id, "Healthy mapper");
  await expect(section(page).getByTestId("living-not-looked")).toContainText("It has not been looked at");
  await expect(section(page).getByTestId("living-meaning")).toContainText("Healthy is that the tools gave again");

  await lookAt(page, id);
  await expect(found(page).getByTestId("living-status")).toHaveText("Healthy");
  await expect(found(page).getByTestId("living-reasons")).toHaveCount(0);
  await expect(found(page).getByTestId("living-source")).toHaveAttribute("data-state", "same");
  await expect(found(page).getByTestId("living-source")).toContainText("Where it was. The code is where it was fetched from, at the same commit.");
  await expect(found(page).getByTestId("living-image")).toHaveText("The image of the environment is in Docker.");
  await expect(found(page).getByTestId("living-pins")).toHaveText("All 2 pinned versions were asked of PyPI, and none is gone or yanked.");
  const tools = found(page).getByTestId("living-tool");
  const kept = (await healthOf(page, id)).health.tools as { name: string; calls: number }[];
  expect(kept.length).toBeGreaterThan(0);
  await expect(tools).toHaveCount(kept.length);
  for (const tool of kept.filter((one) => one.calls > 0)) {
    await expect(tools.and(page.locator(`[data-name="${tool.name}"]`))).toHaveAttribute("data-held", "matched");
  }
  await expect(found(page).getByTestId("living-history")).toHaveCount(0);
  // Nothing else is done to the agent while it is looked at, and nothing that is kept was changed by it
  expect((await (await page.request.get(`/api/paperagents/${id}/tools`)).json()).kept).toMatchObject({ complete: true });
  expect(await accessibilityProblems(page)).toEqual([]);

  // A second look says what the first found, as the one before it
  await lookAt(page, id);
  await expect(found(page).getByTestId("living-history").getByRole("listitem")).toHaveCount(1);
  await expect(found(page).getByTestId("living-history")).toContainText("Healthy");
  expect((await healthOf(page, id)).health.history).toHaveLength(2);
});

test("keeps the schedule that is set, says when it is looked at, and stops it", async ({ page }) => {
  const id = await agentWithTools(page, "Watched mapper", TESTED);
  await openAgent(page, id, "Watched mapper");
  await expect(schedule(page).getByTestId("living-watch")).toHaveText("It is not looked at on a schedule. It is looked at when you ask.");
  const hours = schedule(page).getByLabel("How often, in hours");
  await expect(hours).toHaveValue("24");

  // What is not a whole number in range is said before it is sent
  let sent = 0;
  page.on("request", (request) => {
    if (request.method() === "PUT" && request.url().endsWith(`/api/paperagents/${id}/watch`)) sent += 1;
  });
  for (const typed of ["0", "2161", "1.5", "six"]) {
    await hours.fill(typed);
    await schedule(page).getByRole("button", { name: "Look at it on this schedule" }).click();
    await expect(schedule(page).getByRole("alert")).toHaveText("How often it is looked at, in hours, is a whole number from 1 to 2160.");
    await expect(hours).toHaveAttribute("aria-invalid", "true");
  }
  expect(sent).toBe(0);

  await hours.fill("6");
  await schedule(page).getByRole("button", { name: "Look at it on this schedule" }).click();
  await expect(schedule(page).getByTestId("living-watch")).toHaveAttribute("data-hours", "6");
  await expect(schedule(page).getByRole("alert")).toHaveCount(0);
  expect((await healthOf(page, id)).watch).toMatchObject({ every_hours: 6 });
  // The server looks at an agent whose schedule was never started at its next check of the schedules, which this one makes every few
  // seconds, and says when it was started; the page then says when the next look is
  await expect.poll(async () => (await healthOf(page, id)).watch?.last_started_at ?? null, { timeout: 20_000 }).not.toBeNull();
  await expect.poll(async () => (await healthOf(page, id)).health?.status ?? null, { timeout: 30_000 }).toBe("healthy");
  await page.reload();
  await expect(schedule(page).getByTestId("living-watch")).toContainText("It is looked at every 6 hours while the server is running. It is looked at next ");
  await expect(found(page).getByTestId("living-status")).toHaveText("Healthy");
  await expect(schedule(page).getByLabel("How often, in hours")).toHaveValue("6");

  await schedule(page).getByLabel("How often, in hours").fill("48");
  await schedule(page).getByRole("button", { name: "Change the schedule" }).click();
  await expect(schedule(page).getByTestId("living-watch")).toContainText("It is looked at every 2 days");
  await schedule(page).getByRole("button", { name: "Stop looking at it on a schedule" }).click();
  await expect(schedule(page).getByTestId("living-watch")).toHaveText("It is not looked at on a schedule. It is looked at when you ask.");
  expect((await healthOf(page, id)).watch).toBeNull();
  // What was found stays
  await expect(found(page).getByTestId("living-status")).toHaveText("Healthy");
});

test("says that an agent whose lock pins a version that was yanked is degraded, and one whose tools give something else is broken", async ({
  page,
}) => {
  const id = await agentWithTools(page, "Yanked mapper", TESTED);
  await openAgent(page, id, "Yanked mapper");
  await lookAt(page, id);
  await expect(found(page).getByTestId("living-status")).toHaveText("Degraded");
  await expect(found(page).getByTestId("living-reasons").getByRole("listitem")).toHaveText([
    "1 pinned version cannot be installed again as they are: oldpin==0.0.1 (yanked)",
  ]);
  await expect(found(page).getByTestId("living-pins")).toContainText("All 3 pinned versions were asked of PyPI, and 1 cannot be installed again as it is.");
  await expect(found(page).getByRole("list", { name: "Pinned versions that cannot be had" })).toHaveText("oldpin==0.0.1 (yanked)");
  await expect(found(page).locator('[data-testid="living-tool"][data-held="differs"]')).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  const other = await agentWithTools(page, "Breaking mapper", BREAKS);
  await openAgent(page, other, "Breaking mapper");
  await lookAt(page, other);
  await expect(found(page).getByTestId("living-status")).toHaveText("Broken");
  await expect(found(page).getByTestId("living-reasons")).toContainText("No tool gave again what its tutorials got: ");
  await expect(found(page).getByTestId("living-reasons")).toContainText("gave 0.91 where its tutorial got 0.93");
  await expect(found(page).getByTestId("living-pins")).toHaveText("All 2 pinned versions were asked of PyPI, and none is gone or yanked.");
  const differs = found(page).locator('[data-testid="living-tool"][data-held="differs"]');
  await expect(differs).not.toHaveCount(0);
  await expect(differs.first()).toContainText("gave 0.91 where its tutorial got 0.93");
  await expect(found(page).locator('[data-testid="living-tool"][data-held="matched"]')).toHaveCount(0);
});

test("shows a newer version of the code as a diff, which is put aside or taken only once it has been read and approved", async ({ page }) => {
  const id = await agentWithTools(page, "Moving mapper", moves());
  const { commit: before, ref } = (await healthOf(page, id)).version as { commit: string; ref: string };
  await openAgent(page, id, "Moving mapper");
  await lookAt(page, id);
  // A newer version is not a word: the version that is kept still works as it did
  await expect(found(page).getByTestId("living-status")).toHaveText("Healthy");
  await expect(found(page).getByTestId("living-source")).toHaveAttribute("data-state", "moved");
  const proposed = (await healthOf(page, id)).update;
  expect(proposed).toMatchObject({ from_commit: before, changed: 3, environment_files: ["requirements.txt"] });
  const update = page.getByTestId("living-update");
  await expect(update.getByTestId("living-update-summary")).toHaveText(
    `From ${before.slice(0, 7)} to ${proposed.to_commit.slice(0, 7)}: 3 files changed. The agent stays at ${before.slice(0, 7)} until you take it.`,
  );
  await expect(update.getByTestId("living-update-affects")).toContainText("scale");
  await expect(update.getByTestId("living-update-affects")).toContainText("Files that say what the environment is made of changed: requirements.txt.");

  // Put aside, it is gone until the next look, which proposes it again
  await update.getByRole("button", { name: "Put it aside" }).click();
  await expect(update).toHaveCount(0);
  expect((await healthOf(page, id)).update).toBeNull();
  await lookAt(page, id);
  await expect(update).toBeVisible();

  // What it changes is read first, and it cannot be taken before
  await expect(update.getByRole("button", { name: /^Take / })).toHaveCount(0);
  await update.getByRole("button", { name: "Show what it changes" }).click();
  const files = update.getByRole("list", { name: "What it changes" }).getByTestId("update-file");
  await expect(files).toHaveCount(3);
  await expect(files.nth(0)).toHaveAttribute("data-path", "CHANGELOG.md");
  await expect(files.nth(0)).toHaveAttribute("data-change", "added");
  await expect(files.nth(1)).toHaveAttribute("data-path", "cellmapper/core.py");
  await expect(files.nth(1)).toContainText("1 added, 1 taken away.");
  await files.nth(1).locator("summary").click();
  await expect(files.nth(1).getByTestId("update-diff")).toContainText('+    """Multiplies each value by a factor, which is 1 unless said."""');
  await expect(files.nth(1).getByTestId("update-diff")).toContainText('-    """Multiplies each value by a factor."""');
  await expect(files.nth(2)).toHaveAttribute("data-path", "requirements.txt");
  expect(await accessibilityProblems(page)).toEqual([]);
  const take = update.getByRole("button", { name: `Take ${proposed.to_commit.slice(0, 7)}` });
  await expect(take).toBeDisabled();

  // The server takes only the commit that was proposed, in full
  const wrong = await page.request.post(`/api/paperagents/${id}/update/apply`, { data: { commit: "c".repeat(40) } });
  expect(wrong.status()).toBe(409);
  expect((await wrong.json()).error.code).toBe("changed");
  const short = await page.request.post(`/api/paperagents/${id}/update/apply`, { data: { commit: proposed.to_commit.slice(0, 7) } });
  expect(short.status()).toBe(422);

  await update.getByRole("checkbox", { name: `I have read what ${proposed.to_commit.slice(0, 7)} changes` }).check();
  await take.click();
  const asking = page.getByRole("alertdialog");
  await expect(asking).toContainText("so they are taken away, and are made again by the steps that made them, which you start");
  // Keeping it changes nothing
  await asking.getByRole("button", { name: `Keep ${before.slice(0, 7)}` }).click();
  await expect(asking).toHaveCount(0);
  expect((await healthOf(page, id)).version.commit).toBe(before);

  // A proposal that was replaced between reading and taking is refused, said so, and is to be read again
  await page.route(`**/api/paperagents/${id}/update/apply`, (route) =>
    route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "changed", message: "It changed." } }) }),
  );
  await take.click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Take it" }).click();
  await expect(section(page).getByTestId("update-refused")).toContainText("is not the one that you read");
  await expect(update.getByRole("list", { name: "What it changes" })).toHaveCount(0);
  await page.unroute(`**/api/paperagents/${id}/update/apply`);
  expect((await healthOf(page, id)).version.commit).toBe(before);
  await update.getByRole("button", { name: "Show what it changes" }).click();
  await expect(section(page).getByTestId("update-refused")).toHaveCount(0);
  await expect(take).toBeDisabled();
  await update.getByRole("checkbox", { name: `I have read what ${proposed.to_commit.slice(0, 7)} changes` }).check();

  await take.click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Take it" }).click();
  await expect.poll(async () => (await healthOf(page, id)).version?.commit ?? null, { timeout: 30_000 }).toBeNull();
  await expect.poll(async () => (await (await page.request.get(`/api/paperagents/${id}/repository`)).json()).job, { timeout: 30_000 }).toBeNull();
  // It is the commit that was approved, still of the ref that it was fetched at before, so that it is looked at again by that ref
  const { intake } = await (await page.request.get(`/api/paperagents/${id}/repository`)).json();
  expect(intake).toMatchObject({ commit: proposed.to_commit, ref: ref });
  // What was made of the old commit went with it, so there is nothing to look at until the tools are made again
  await expect(section(page).getByTestId("living-no-tools")).toBeVisible();
  expect((await (await page.request.get(`/api/paperagents/${id}/environment`)).json()).built).toBeNull();
});
