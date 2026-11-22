import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { expect, test } from "../fixtures";

// The lab's library, which lists the agents that have tools as versions that are pinned, and the package that is made of an agent's
// tools. The package's own check in a clean container is a stand-in (see scripted_server.py): the tools of code whose address says
// "breaks" give something else. Code whose address says "copyleft" has the GPL, and one that says "unlicensed" has no license
test.describe.configure({ mode: "serial" });

const TESTED = "https://github.com/example/tested-cellmapper";

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

const exportOf = async (page: Page, id: string) => (await page.request.get(`/api/paperagents/${id}/export`)).json();
const section = (page: Page) => page.getByRole("region", { name: "Package", exact: true });
const make = (page: Page) => section(page).getByRole("button", { name: /^Make (a package|the package again)$/ });
const made = (page: Page) => section(page).getByTestId("package-made");

// Makes an agent through the server, step after step, up to its tools, waiting for each
async function agentWithTools(page: Page, title: string, repo: string): Promise<string> {
  const created = await page.request.post("/api/paperagents", { data: { title, paper: { kind: "file" }, repo } });
  expect(created.status()).toBe(201);
  const id: string = (await created.json()).id;
  for (const step of ["repository", "environment", "reference", "tools"]) {
    const started = await page.request.post(`/api/paperagents/${id}/${step}`, { data: {} });
    expect(started.status(), step).toBe(202);
    await expect.poll(async () => (await (await page.request.get(`/api/paperagents/${id}/${step}`)).json()).job, { timeout: 30_000 }).toBeNull();
  }
  expect((await (await page.request.get(`/api/paperagents/${id}/tools`)).json()).kept).toMatchObject({ complete: true });

  return id;
}

async function openAgent(page: Page, id: string, title: string) {
  await page.goto(`/papers?agent=${id}`);
  await expect(page.getByRole("heading", { name: title, level: 2 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Package", level: 2, exact: true })).toBeVisible();
}

// Makes the package from the page and waits for the job to end
async function makePackage(page: Page, id: string) {
  await make(page).click();
  await expect.poll(async () => (await exportOf(page, id)).job, { timeout: 30_000 }).toBeNull();
}

test("lists only the agents that have tools, and says that a package is made of the tools", async ({ page }) => {
  await page.goto("/papers?view=library");
  await expect(page.getByRole("navigation", { name: "PaperAgents" }).getByRole("link", { name: "Library" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("library-empty")).toContainText("No agent has tools yet");

  const created = await page.request.post("/api/paperagents", { data: { title: "Toolless mapper", paper: { kind: "file" }, repo: TESTED } });
  const id: string = (await created.json()).id;
  expect((await (await page.request.get("/api/paperagents/library")).json()).agents).toEqual([]);
  await openAgent(page, id, "Toolless mapper");
  await expect(section(page).getByTestId("package-no-tools")).toHaveText("Make the tools first, as a package is made of them.");
  await expect(make(page)).toHaveCount(0);
  const asked = await page.request.post(`/api/paperagents/${id}/export`, { data: {} });
  expect(asked.status()).toBe(422);
  // Its code was not fetched, which the tools are made of
  expect((await asked.json()).error.code).toBe("no_code");
});

test("shows an agent's pin, makes a package of its tools that was checked, downloads it, and takes it away", async ({ page }) => {
  const id = await agentWithTools(page, "Packed mapper", TESTED);
  const { entry } = await exportOf(page, id);

  // The library lists it, pinned to its commit, its environment, and its tools, with no package yet
  await page.goto("/papers?view=library");
  const listed = page.getByTestId("library-entry");
  await expect(listed).toHaveCount(1);
  await expect(listed.getByRole("link", { name: "Packed mapper" })).toHaveAttribute("href", `/papers?agent=${id}`);
  await expect(listed.getByTestId("library-version")).toHaveText(`Commit ${entry.version.commit.slice(0, 7)} of ${entry.version.ref}, from ${TESTED}.`);
  await expect(listed.getByTestId("library-environment")).toContainText(`with Python ${entry.environment.python}`);
  await expect(listed.getByTestId("library-environment")).toContainText(`${entry.environment.lock.packages} packages at the versions in ${entry.environment.lock.name}`);
  await expect(listed.getByTestId("library-license")).toContainText("MIT, a permissive license.");
  await expect(listed.getByTestId("library-license")).toHaveAttribute("data-flag", "");
  await expect(listed.getByTestId("library-tool")).toHaveCount(entry.tools.length);
  await expect(listed.getByTestId("library-tool").first()).toHaveAttribute("data-tier", "A");
  await expect(listed.getByTestId("library-health")).toHaveAttribute("data-status", "unchecked");
  await expect(listed.getByTestId("library-health")).toContainText("Unchecked: not looked at since it was made as it is.");
  await expect(listed.getByTestId("library-package")).toHaveAttribute("data-state", "none");
  await expect(listed.getByTestId("library-package")).toHaveText("No package was made of its tools.");
  await expect(page.getByTestId("library-meaning")).toContainText("A tool of tier A calls the authors' own function");
  expect(await accessibilityProblems(page)).toEqual([]);

  // On its page the package is made, and kept as it passed its check
  await openAgent(page, id, "Packed mapper");
  await expect(section(page).getByTestId("library-pin")).toBeVisible();
  await expect(section(page).getByTestId("package-license")).toHaveCount(0);
  await expect(make(page)).toHaveText("Make a package");
  await makePackage(page, id);
  await expect(made(page)).toHaveAttribute("data-current", "true");
  const kept = (await exportOf(page, id)).entry.export;
  expect(kept).toMatchObject({ current: true, accepted_license: false, tested: { ok: true } });
  await expect(made(page).getByTestId("package-summary")).toContainText(`${kept.file}, `);
  await expect(made(page).getByTestId("package-tested")).toContainText(`${kept.tested.calls} recorded call`);
  await expect(made(page).getByTestId("package-tested")).toContainText("gave what the tutorials got");
  await expect(made(page)).toContainText(kept.sha256);
  await expect(section(page).getByRole("region", { name: "Making the package" })).toHaveCount(0);
  await expect(make(page)).toHaveText("Make the package again");
  expect(await accessibilityProblems(page)).toEqual([]);

  // It downloads as the file that was kept
  const [download] = await Promise.all([page.waitForEvent("download"), made(page).getByRole("link", { name: `Download ${kept.file}` }).click()]);
  expect(download.suggestedFilename()).toBe(kept.file);
  const file = await page.request.get(`/api/paperagents/${id}/export/package`);
  expect(file.status()).toBe(200);
  expect((await file.body()).subarray(0, 2).toString()).toBe("PK");

  // The library says so, and downloads it too
  await page.goto("/papers?view=library");
  await expect(listed.getByTestId("library-package")).toHaveAttribute("data-state", "current");
  await expect(listed.getByTestId("library-package")).toContainText(`checked with ${kept.tested.calls} recorded call`);
  await expect(listed.getByTestId("library-package").getByRole("link", { name: `Download ${kept.file}` })).toHaveAttribute(
    "href",
    `/api/paperagents/${id}/export/package`,
  );

  // Taken away, there is none, and none can be downloaded
  await openAgent(page, id, "Packed mapper");
  await made(page).getByRole("button", { name: "Take the package away" }).click();
  await expect(made(page)).toHaveCount(0);
  await expect(make(page)).toHaveText("Make a package");
  expect((await exportOf(page, id)).entry.export).toBeNull();
  expect((await page.request.get(`/api/paperagents/${id}/export/package`)).status()).toBe(404);
});

test("says that a package is out of date once the tools are checked again, and cannot be downloaded until it is made again", async ({ page }) => {
  test.setTimeout(90_000);
  const id = await agentWithTools(page, "Stale mapper", TESTED);
  await openAgent(page, id, "Stale mapper");
  await makePackage(page, id);
  await expect(made(page)).toHaveAttribute("data-current", "true");

  // Checking the tools makes one of tier B, which the package was not made of
  const checks = page.getByRole("form", { name: "Check the tools" });
  await checks.getByRole("button", { name: "Check the tools" }).click();
  await expect.poll(async () => (await (await page.request.get(`/api/paperagents/${id}/checks`)).json()).job, { timeout: 30_000 }).toBeNull();
  expect((await exportOf(page, id)).entry.export.current).toBe(false);
  await expect(made(page)).toHaveAttribute("data-current", "false");
  await expect(made(page)).toContainText("Out of date");
  await expect(made(page)).toContainText("so it cannot be downloaded. Make it again.");
  await expect(made(page).getByRole("link", { name: /^Download / })).toHaveCount(0);
  const refused = await page.request.get(`/api/paperagents/${id}/export/package`);
  expect(refused.status()).toBe(409);
  expect((await refused.json()).error.code).toBe("stale");
  await expect(section(page).getByTestId("library-tool").first()).toHaveAttribute("data-tier", "B");

  await page.goto("/papers?view=library");
  await expect(page.getByTestId("library-package")).toHaveAttribute("data-state", "stale");
  await expect(page.getByTestId("library-entry").getByText("Tier B", { exact: true }).first()).toBeVisible();

  await openAgent(page, id, "Stale mapper");
  await makePackage(page, id);
  await expect(made(page)).toHaveAttribute("data-current", "true");
  expect((await page.request.get(`/api/paperagents/${id}/export/package`)).status()).toBe(200);
});

test("asks that what is said of a flagged license be read before a package is made of the code, and says that it was", async ({ page }) => {
  const id = await agentWithTools(page, "Copyleft mapper", "https://github.com/example/copyleft-tested-cellmapper");
  await openAgent(page, id, "Copyleft mapper");
  await expect(section(page).getByTestId("library-license")).toHaveAttribute("data-flag", "copyleft");
  await expect(section(page).getByTestId("library-license")).toContainText("GPL-3.0, a copyleft license.");
  await expect(section(page).getByTestId("library-license")).toContainText("Copyleft");
  const said = section(page).getByTestId("package-license");
  await expect(said).toContainText("The code's license is a copyleft one");
  await expect(make(page)).toBeDisabled();

  // The server refuses it too, until it is said to go on
  const refused = await page.request.post(`/api/paperagents/${id}/export`, { data: {} });
  expect(refused.status()).toBe(409);
  expect((await refused.json()).error.code).toBe("license");

  await said.getByRole("checkbox", { name: "I have read this, and go on" }).check();
  await expect(make(page)).toBeEnabled();
  expect(await accessibilityProblems(page)).toEqual([]);
  await makePackage(page, id);
  await expect(made(page)).toHaveAttribute("data-current", "true");
  await expect(made(page).getByTestId("package-accepted")).toContainText("Made after you said to go on with code whose license is flagged: copyleft.");
  expect((await exportOf(page, id)).entry.export).toMatchObject({ accepted_license: true, license: { flag: "copyleft" } });
  // Making it again asks again
  await expect(said.getByRole("checkbox", { name: "I have read this, and go on" })).not.toBeChecked();

  const bare = await agentWithTools(page, "Unlicensed mapper", "https://github.com/example/unlicensed-tested-cellmapper");
  await page.goto("/papers?view=library");
  const listed = page.getByTestId("library-entry").and(page.locator(`[data-id="${bare}"]`));
  await expect(listed.getByTestId("library-license")).toHaveAttribute("data-flag", "none");
  await expect(listed.getByTestId("library-license")).toContainText("No license was found.");
  await expect(listed.getByTestId("library-license")).toContainText("No license");
});

test("keeps no package that does not give what the tutorials got in its check, and says why", async ({ page }) => {
  const id = await agentWithTools(page, "Breaking mapper", "https://github.com/example/breaks-tested-cellmapper");
  await openAgent(page, id, "Breaking mapper");
  await makePackage(page, id);
  const status = section(page).getByRole("region", { name: "Making the package" });
  await expect(status).toContainText("Failed");
  await expect(status).toContainText("The package was not kept, as it did not pass its check in a clean container.");
  await expect(status).toContainText("gave 0.91 where its tutorial got 0.93");
  await expect(made(page)).toHaveCount(0);
  expect((await exportOf(page, id)).entry.export).toBeNull();
});
