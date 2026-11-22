import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { expect, test } from "../fixtures";

// What the page of an agent tells the person who wrote its paper, or reviews it, of what a reader who takes the code as a stranger
// would hit, and the package it gives them. Code whose address says "unlicensed" has no license (see scripted_server.py)
test.describe.configure({ mode: "serial" });

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

const section = (page: Page) => page.getByRole("region", { name: "For authors and reviewers", exact: true });

async function agent(page: Page, title: string, repo: string): Promise<string> {
  const created = await page.request.post("/api/paperagents", { data: { title, paper: { kind: "file" }, repo } });
  expect(created.status()).toBe(201);

  return (await created.json()).id;
}

// Runs a step through the server and waits for it to end
async function run(page: Page, id: string, step: string) {
  const started = await page.request.post(`/api/paperagents/${id}/${step}`, { data: {} });
  expect(started.status(), step).toBe(202);
  await expect.poll(async () => (await (await page.request.get(`/api/paperagents/${id}/${step}`)).json()).job, { timeout: 30_000 }).toBeNull();
}

async function openAgent(page: Page, id: string, title: string) {
  await page.goto(`/papers?agent=${id}`);
  await expect(page.getByRole("heading", { name: title, level: 2 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "For authors and reviewers", level: 2, exact: true })).toBeVisible();
}

test("says that nothing is known until the code is fetched, and gives no package", async ({ page }) => {
  const id = await agent(page, "Unfetched mapper", "https://github.com/example/tested-cellmapper");
  await openAgent(page, id, "Unfetched mapper");
  await expect(section(page).getByTestId("author-verdict")).toHaveAttribute("data-verdict", "not_checked");
  await expect(section(page).getByTestId("author-verdict")).toContainText("Not looked at");
  await expect(section(page).getByTestId("author-unchecked").locator('[data-id="repository"]')).toContainText(
    "It is run in the Code part of this page.",
  );
  // What is known without the code, such as that the paper was not read, is said all the same
  const view = await (await page.request.get(`/api/paperagents/${id}/author`)).json();
  await expect(section(page).getByTestId("author-finding")).toHaveCount(view.findings.length);
  await expect(section(page).getByRole("region", { name: "Steps that were not run" })).toBeVisible();
  await expect(section(page).getByTestId("author-card")).toHaveCount(0);
  await expect(section(page).getByTestId("author-package")).toHaveAttribute("data-ready", "false");
  await expect(section(page).getByTestId("author-package")).toContainText("Fetch the code first");
  await expect(section(page).getByRole("link", { name: "Download the package" })).toHaveCount(0);
  expect((await page.request.get(`/api/paperagents/${id}/author/package`)).status()).toBe(409);
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("shows what a reader would hit once the code is fetched, the texts for the authors, and downloads the package", async ({ page }) => {
  const id = await agent(page, "Unlicensed mapper", "https://github.com/example/unlicensed-tested-cellmapper");
  await openAgent(page, id, "Unlicensed mapper");
  await expect(section(page).getByTestId("author-verdict")).toHaveAttribute("data-verdict", "not_checked");

  // A step run from elsewhere is seen once the page looks at the agent again
  await run(page, id, "repository");
  await page.reload();
  const view = await (await page.request.get(`/api/paperagents/${id}/author`)).json();
  expect(view.verdict).not.toBe("not_checked");
  const license = view.findings.find((item: { area: string }) => item.area === "license");
  expect(license).toBeTruthy();
  await expect(section(page).getByTestId("author-verdict")).toHaveAttribute("data-verdict", view.verdict);
  await expect(section(page).getByTestId("author-finding")).toHaveCount(view.findings.length);
  const shown = section(page).locator(`[data-testid="author-finding"][data-id="${license.id}"]`);
  await expect(shown).toContainText(license.title);
  await expect(shown).toContainText("License");
  await expect(section(page).getByTestId("author-unchecked").locator('[data-id="environment"]')).toContainText("Environment part");
  await expect(section(page).getByTestId("author-unchecked").locator('[data-id="repository"]')).toHaveCount(0);

  const card = section(page).getByTestId("author-card");
  await card.getByText("The reproducibility card").click();
  await expect(card.getByRole("button", { name: "Copy as Markdown" })).toBeVisible();
  await expect(section(page).getByTestId("author-statement").getByRole("button", { name: "Copy as Markdown" })).toBeHidden();

  await expect(section(page).getByTestId("author-package")).toHaveAttribute("data-ready", "true");
  for (const file of view.package.files) {
    await expect(section(page).getByRole("list", { name: "What the package has" })).toContainText(file.name);
  }
  const link = section(page).getByRole("link", { name: "Download the package" });
  const fetched = await page.request.get((await link.getAttribute("href"))!);
  expect(fetched.status()).toBe(200);
  expect(fetched.headers()["content-type"]).toContain("zip");
  expect((await fetched.body()).subarray(0, 2).toString()).toBe("PK");
  await expect(section(page).getByTestId("author-meaning")).toHaveText(view.meaning);
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("looks again when a step is run from the page, and when asked", async ({ page }) => {
  const id = await agent(page, "Growing mapper", "https://github.com/example/tested-cellmapper");
  await openAgent(page, id, "Growing mapper");
  await expect(section(page).getByTestId("author-verdict")).toHaveAttribute("data-verdict", "not_checked");
  await page.getByRole("region", { name: "Code", exact: true }).getByRole("button", { name: /^Fetch the code/ }).click();
  await expect(section(page).getByTestId("author-verdict")).not.toHaveAttribute("data-verdict", "not_checked", { timeout: 30_000 });

  // Running a step through the server is seen when the reader asks to look again
  await run(page, id, "environment");
  await section(page).getByRole("button", { name: "Look again" }).click();
  await expect(section(page).getByTestId("author-unchecked").locator('[data-id="environment"]')).toHaveCount(0);
});
