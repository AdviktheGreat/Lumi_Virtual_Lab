import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { expect, test } from "../fixtures";
import { arrange, lakeFiles, leaveMissing, openSetup, resetSetup } from "./state";

// What they arrange is what every test of the setup shares, and each puts it back, so none is run beside another
test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await resetSetup(page);
});

const lakeSection = (page: Page) => page.getByRole("region", { name: "Biomni's data lake" });
const filesOf = (page: Page) => lakeSection(page).getByRole("list", { name: "Files of the data lake" });

async function openData(page: Page) {
  await page.goto("/data");
  await expect(page.getByRole("heading", { name: "Biomni's data lake", level: 2 })).toBeVisible();
}

test("shows which files of the data lake are there, and which are not, as the setup does", async ({ page }) => {
  const files = await lakeFiles(page);
  const missing = files.slice(-3).map((file) => file.name);
  await leaveMissing(page, missing);

  await openData(page);

  await expect(lakeSection(page).getByText("73 of 76 files")).toBeVisible();
  await expect(filesOf(page).getByRole("listitem")).toHaveCount(76);
  for (const name of missing) await expect(lakeSection(page).getByRole("button", { name: `Fetch ${name}`, exact: true })).toBeVisible();
  await lakeSection(page).getByRole("searchbox", { name: "Search the files" }).fill(missing[0]);
  await expect(filesOf(page).getByRole("listitem")).toHaveCount(1);
});

test("does not ask about Docker, which the setup does and this page has no use for", async ({ page }) => {
  const asked: string[] = [];
  page.on("request", (request) => asked.push(new URL(request.url()).pathname));

  await openData(page);
  await expect(lakeSection(page).getByText(/of 76 files/)).toBeVisible();

  expect(asked).toContain("/api/setup/data-lake");
  expect(asked).toContain("/api/own");
  expect(asked).not.toContain("/api/setup");
});

test("fetches a file from the page, and shows it there", async ({ page }) => {
  const files = await lakeFiles(page);
  await leaveMissing(page, [files[0].name, files[1].name]);
  await openData(page);

  await lakeSection(page).getByRole("button", { name: `Fetch ${files[0].name}`, exact: true }).click();

  await expect(lakeSection(page).getByText("75 of 76 files")).toBeVisible();
  await expect(lakeSection(page).getByRole("button", { name: `Fetch ${files[0].name}`, exact: true })).toHaveCount(0);
  expect((await arrange(page)).requests).toEqual([files[0].name]);
});

test("asks before fetching the files that are not there, and follows the fetch on the page until it is over", async ({ page }) => {
  const files = await lakeFiles(page);
  const missing = files.slice(-3).map((file) => file.name);
  await leaveMissing(page, missing);
  await arrange(page, { hold: [missing[1]] });
  await openData(page);
  const section = lakeSection(page);

  await section.getByRole("button", { name: "Fetch the 3 files that are not there" }).click();
  await expect(section.getByRole("group", { name: "Fetch the data lake" })).toContainText("This fetches 3 files");
  expect((await arrange(page)).requests).toEqual([]);
  await section.getByRole("button", { name: "Start fetching" }).click();

  const progress = section.getByRole("progressbar", { name: "Progress: Fetching Biomni's data lake" });
  await expect(progress).toBeVisible();
  await expect(section.getByText(`Fetching ${missing[1]}`)).toBeVisible();
  await expect(section.getByText("1 of 3 files · 10 KB fetched · 0 B of 10 KB of this file")).toBeVisible();
  // What is being fetched cannot be asked for again, and the sidebar says that something is being fetched
  await expect(section.getByRole("button", { name: `Fetch ${missing[1]}`, exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Set up, something is being built or fetched" })).toBeVisible();

  await arrange(page, { let: [missing[1]] });

  await expect(section.getByText("Every file is there.")).toBeVisible();
  await expect(section.getByText("76 of 76 files")).toBeVisible();
  await expect(progress).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Set up", exact: true })).toBeVisible();
});

test("stops a fetch from the page", async ({ page }) => {
  const files = await lakeFiles(page);
  const missing = files.slice(-3).map((file) => file.name);
  await leaveMissing(page, missing);
  await arrange(page, { hold: [missing[1]] });
  await openData(page);
  const section = lakeSection(page);
  await section.getByRole("button", { name: "Fetch the 3 files that are not there" }).click();
  await section.getByRole("button", { name: "Start fetching" }).click();
  await expect(section.getByText(/1 of 3 files/)).toBeVisible();

  await section.getByRole("button", { name: "Stop: Fetching Biomni's data lake" }).click();
  await expect(section.getByRole("button", { name: "Stopping: Fetching Biomni's data lake" })).toBeDisabled();
  await arrange(page, { let: [missing[1]] });

  await expect(section.getByRole("progressbar")).toHaveCount(0);
  await expect(section.getByText("74 of 76 files")).toBeVisible();
});

test("follows a fetch that is begun in the setup, which is opened over the page", async ({ page }) => {
  const files = await lakeFiles(page);
  const missing = files.slice(-2).map((file) => file.name);
  await leaveMissing(page, missing);
  await arrange(page, { hold: [missing[0]] });
  await openData(page);
  const section = lakeSection(page);

  const dialog = await openSetup(page, "Data lake");
  await dialog.getByRole("button", { name: "Fetch the 2 files that are not there" }).click();
  await dialog.getByRole("button", { name: "Start fetching" }).click();
  await expect(dialog.getByRole("progressbar", { name: "Progress: Fetching Biomni's data lake" })).toBeVisible();
  await dialog.getByRole("button", { name: "Close", exact: true }).click();

  await expect(section.getByRole("progressbar", { name: "Progress: Fetching Biomni's data lake" })).toBeVisible();
  await expect(section.getByRole("button", { name: /^Fetch the \d+ files? that/ })).toHaveCount(0);

  await arrange(page, { let: [missing[0]] });
  await expect(section.getByText("76 of 76 files")).toBeVisible();
});

test("says why a fetch was refused, on the page", async ({ page }) => {
  const files = await lakeFiles(page);
  await leaveMissing(page, [files[0].name]);
  await openData(page);
  await page.route("**/api/setup/data-lake", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "busy", message: "The data lake is being fetched already" } }),
        })
      : route.continue(),
  );

  await lakeSection(page).getByRole("button", { name: `Fetch ${files[0].name}`, exact: true }).click();

  await expect(lakeSection(page).getByRole("alert")).toHaveText("The data lake is being fetched already");
  await expect(lakeSection(page).getByRole("button", { name: `Fetch ${files[0].name}`, exact: true })).toBeEnabled();
});

test("has nothing wrong that axe can find, while a fetch is going on", async ({ page }) => {
  const files = await lakeFiles(page);
  const missing = files.slice(-2).map((file) => file.name);
  await leaveMissing(page, missing);
  await arrange(page, { hold: [missing[0]] });
  await openData(page);
  await lakeSection(page).getByRole("button", { name: "Fetch the 2 files that are not there" }).click();
  await lakeSection(page).getByRole("button", { name: "Start fetching" }).click();
  await expect(lakeSection(page).getByRole("progressbar")).toBeVisible();

  expect(await accessibilityProblems(page)).toEqual([]);

  await arrange(page, { let: [missing[0]] });
});
