import { expect, type Locator, type Page } from "@playwright/test";
import { resetSettings } from "../own-server/state";

// Where a test arranges Docker and the place the data lake is fetched from, which are stand-ins in this server (see
// FakeSetup in e2e/scripted_server.py)
const CONTROL = `http://127.0.0.1:${Number(process.env.E2E_PORT ?? 8799) + 3}`;

// What the stand-ins say of what was done to them
export interface StandIns {
  // The arguments of each build that was begun
  builds: string[][];
  // Whether a build has begun and printed what it was set to
  started: boolean;
  // The tags of the images that are built
  images: string[];
  // The files of the data lake that were asked for
  requests: string[];
}

// Arranges the stand-ins as the order says, and tells what was done to them. See FakeSetup.control for what can be said.
export async function arrange(page: Page, order: Record<string, unknown> = {}): Promise<StandIns> {
  const response = await page.request.post(CONTROL, { data: order });
  expect(response.ok()).toBe(true);

  return response.json();
}

export interface JobInfo {
  id: string;
  kind: string;
  subject: string;
  state: string;
}

export async function jobs(page: Page): Promise<JobInfo[]> {
  return (await (await page.request.get("/api/setup/jobs")).json()).jobs;
}

// Puts the stand-ins, the keys, and the settings as the server began with them. What is at work is let go on first, since
// it would otherwise go on into what is put as it was.
export async function resetSetup(page: Page): Promise<void> {
  await arrange(page, { settle: true });
  await expect.poll(async () => (await jobs(page)).filter((job) => ["running", "stopping"].includes(job.state)).length).toBe(0);
  await arrange(page, { reset: true });
  await resetSettings(page);
}

// Makes the settings those of code that runs in Docker, in a stage of the image
export async function codeInDocker(page: Page, sandbox = "base"): Promise<void> {
  expect((await page.request.patch("/api/settings", { data: { code: "docker", sandbox } })).ok()).toBe(true);
}

// The tag of a stage of the image, as the server names it
export async function tagOf(page: Page, stage: string): Promise<string> {
  const { images } = await (await page.request.get("/api/setup")).json();

  return images.stages.find((found: { target: string }) => found.target === stage).tag;
}

// The names of the files of the data lake, in the order they are fetched in
export async function lakeFiles(page: Page): Promise<{ name: string; commercial: boolean }[]> {
  return (await (await page.request.get("/api/setup/data-lake")).json()).files;
}

// Opens the setup from the sidebar, at one of the parts of it if it is named
export async function openSetup(page: Page, tab?: "Overview" | "Data lake" | "Jobs"): Promise<Locator> {
  await page
    .getByRole("complementary", { name: "Sidebar" })
    .getByRole("button", { name: /^Set up/ })
    .click();
  const dialog = page.getByRole("dialog", { name: "Set up" });
  await expect(dialog).toBeVisible();
  if (tab) await dialog.getByRole("tab", { name: tab }).click();

  return dialog;
}

// Puts every file of the data lake there but those named, as if they had been fetched
export async function leaveMissing(page: Page, names: string[]): Promise<void> {
  const present = (await lakeFiles(page)).map((file) => file.name).filter((name) => !names.includes(name));
  await arrange(page, { present });
}
