import fs from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { expect, test } from "../fixtures";
import { resetSkills, settings } from "./state";

// The skills that come with the lab are those of a folder beside the server's workspace, which is empty until a test puts
// some in, and are the server's whichever test is run, so each test takes them away again, and none is run beside another
test.describe.configure({ mode: "serial" });

let folder = "";

function write(directory: string, name: string, description: string): void {
  const target = path.join(directory, name);
  fs.mkdirSync(target, { recursive: true });
  fs.writeFileSync(path.join(target, "SKILL.md"), `---\nname: ${name}\ndescription: ${description}\nlicense: MIT\n---\n\n# ${name}\n\nDo it well.\n`);
}

test.beforeEach(async ({ page }) => {
  await resetSkills(page);
  folder = `${(await settings(page)).workspace}-builtin-skills`;
  write(folder, "house-style", "Use when figures are made for the lab's papers.");
  write(folder, "house-stats", "Use when a number is asked for.");
  await page.goto("/data");
  await expect(page.getByRole("heading", { name: "Skills", level: 2 })).toBeVisible();
});

test.afterEach(async ({ page }) => {
  // Turned back on before they are gone, since a skill that is turned off and cannot be found stays turned off
  await resetSkills(page);
  for (const name of fs.readdirSync(folder)) fs.rmSync(path.join(folder, name), { recursive: true, force: true });
});

const row = (page: Page, name: string) => page.getByTestId("skill").filter({ has: page.getByText(name, { exact: true }) });
const count = (page: Page) => page.getByTestId("skills-count");

async function listed(page: Page) {
  return (await page.request.get("/api/skills")).json();
}

test.describe("the skills that come with the lab", () => {
  test("are listed as on, say that they come with the lab, and cannot be deleted", async ({ page }) => {
    await expect(count(page)).toHaveText("2 skills, all on");
    await expect(row(page, "house-style").getByText("Comes with the lab", { exact: true })).toBeVisible();
    await expect(row(page, "house-style").getByRole("checkbox")).toBeChecked();
    await expect(row(page, "house-style").getByRole("button", { name: "Delete house-style" })).toHaveCount(0);
    await expect(page.getByText("The lab comes with 2 skills of its own. They cannot be deleted, but they can be turned off")).toBeVisible();
    expect((await page.request.delete("/api/skills/house-style")).status()).toBe(409);
    expect(fs.existsSync(path.join(folder, "house-style", "SKILL.md"))).toBe(true);
  });

  test("can be read, with where they are found said", async ({ page }) => {
    await row(page, "house-style").getByRole("button", { name: "Read what house-style tells the lead" }).click();

    await expect(row(page, "house-style").getByText("The skills that come with the lab: ", { exact: false })).toBeVisible();
    await expect(row(page, "house-style").getByText("Do it well.")).toBeVisible();
  });

  test("can be turned off for new conversations, which are then not given them", async ({ page }) => {
    await row(page, "house-style").getByRole("checkbox", { name: "Give new conversations house-style" }).uncheck();

    await expect(count(page)).toHaveText("2 skills, 1 on");
    await expect
      .poll(async () => (await listed(page)).skills.filter((skill: { enabled: boolean }) => !skill.enabled).map((skill: { name: string }) => skill.name))
      .toEqual(["house-style"]);
    const chat = await (await page.request.post("/api/chats", { data: { team: [] } })).json();
    expect(chat.skills).toEqual(["house-stats"]);
    await page.request.delete(`/api/chats/${chat.id}`);
  });

  test("are offered for a new conversation to be given or not, as the other skills are", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("skills-button").click();
    const dialog = page.getByTestId("skills-dialog");

    await expect(dialog.getByTestId("skills-chosen")).toHaveText("All 2 skills are chosen");
    await dialog.getByRole("checkbox", { name: "house-stats", exact: true }).uncheck();
    await dialog.getByRole("button", { name: "Use these" }).click();
    await expect(page.getByTestId("skills-button")).toHaveText("Skills · 1");
  });

  test("give way to a skill that is put in with the same name, which can then be deleted", async ({ page }) => {
    const mine = path.join(folder, "..", `${path.basename(folder)}-mine`);
    write(mine, "house-style", "Mine, for figures.");
    try {
      const put = await page.request.post("/api/skills/install", { data: { path: mine } });
      expect(put.status()).toBe(200);
      await page.reload();

      await expect(count(page)).toHaveText("2 skills, all on");
      await expect(row(page, "house-style").getByText("Mine, for figures.")).toBeVisible();
      await expect(row(page, "house-style").getByText("Comes with the lab", { exact: true })).toHaveCount(0);
      await row(page, "house-style").getByRole("button", { name: "Delete house-style" }).click();
      await page.getByRole("alertdialog").getByRole("button", { name: "Delete", exact: true }).click();

      await expect(row(page, "house-style").getByText("Comes with the lab", { exact: true })).toBeVisible();
      await expect(row(page, "house-style").getByText("Use when figures are made for the lab's papers.")).toBeVisible();
    } finally {
      fs.rmSync(mine, { recursive: true, force: true });
    }
  });

  test("have nothing wrong that axe can find", async ({ page }) => {
    await expect(count(page)).toHaveText("2 skills, all on");

    expect(await accessibilityProblems(page)).toEqual([]);
  });
});
