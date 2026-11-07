import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { Page } from "@playwright/test";
import { accessibilityProblems, pastTheEdge } from "../axe";
import { answered, ask, expect, test } from "../fixtures";
import { resetSkills } from "./state";

// The skills are the workspace's, which every conversation made after is given those of that are on, so each test takes them
// away again, and none is run beside another
test.describe.configure({ mode: "serial" });

let scratch = "";

function write(name: string, description: string): void {
  const directory = path.join(scratch, name);
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, "SKILL.md"), `---\nname: ${name}\ndescription: ${description}\n---\n\n# ${name}\n\nFit it.\n`);
}

const box = (page: Page) => page.getByRole("textbox", { name: "Message" });
const menu = (page: Page) => page.getByTestId("slash-menu");
const options = (page: Page) => menu(page).getByTestId("slash-option");
// What the scripted lead says once it has read a skill, which is the one step that it takes
const READ = "That is done: 1 step ran.";
const chip = (page: Page) => page.getByTestId("skill-chip");
const unmet = (page: Page) => page.getByTestId("directive-unmet");

// What the menu lists, by the names the lines are given
async function listed(page: Page): Promise<(string | null)[]> {
  return options(page).evaluateAll((lines) => lines.map((line) => line.getAttribute("data-command")));
}

test.beforeEach(async ({ page }) => {
  await resetSkills(page);
  scratch = fs.mkdtempSync(path.join(os.tmpdir(), "vl-e2e-skill-slash-"));
  write("alpha-skill", "Fits curves to titration data.");
  write("beta-skill", "Differential expression with DESeq2.");
  write("gamma-skill", "Makes figures that follow a journal's style.");
  expect((await page.request.post("/api/skills/install", { data: { path: scratch } })).status()).toBe(200);
  // The page reads the skills as it opens, which a command written at once is not taken for a message before
  const read = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/skills" && response.request().method() === "GET");
  await page.goto("/");
  await expect(box(page)).toBeVisible();
  await read;
});

test.afterEach(async ({ page }) => {
  fs.rmSync(scratch, { recursive: true, force: true });
  await resetSkills(page);
});

test.describe("the skills in the menu of commands", () => {
  test("are not listed for a slash alone, and are for the letters of their names, with what each is for", async ({ page }) => {
    await box(page).fill("/");
    await expect(menu(page)).toBeVisible();
    expect(await listed(page)).not.toContain("/alpha-skill");

    await box(page).fill("/alp");
    // They are read from the server when a slash is first written, so they are there a moment after
    await expect.poll(() => listed(page)).toEqual(["/alpha-skill"]);
    await expect(options(page).first()).toContainText("Skill: Fits curves to titration data.");
    expect(await accessibilityProblems(page)).toEqual([]);
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);

    // Commands come first, and the skills with the letters in their names after them
    await box(page).fill("/skill");
    await expect.poll(() => listed(page)).toEqual(["/skills", "/alpha-skill", "/beta-skill", "/gamma-skill"]);
  });

  test("are written out with Tab, and then wait for what they are to be used for", async ({ page }) => {
    await box(page).fill("/gam");
    await expect.poll(() => listed(page)).toEqual(["/gamma-skill"]);

    await box(page).press("Tab");

    await expect(box(page)).toHaveValue("/gamma-skill ");
    await expect(options(page)).toHaveCount(1);
    await expect(options(page).first()).toContainText("Type what to use it for");
    await expect(options(page).first()).toHaveAttribute("aria-disabled", "true");
    // Enter does nothing while nothing can be chosen
    await box(page).press("Enter");
    await expect(page).toHaveURL(/\/$/);
    await expect(box(page)).toHaveValue("/gamma-skill ");
  });
});

test.describe("a message given with a skill", () => {
  test("is sent with the skill, which the lead is told to read, and is shown with it", async ({ page }) => {
    await box(page).fill("/alpha");
    await expect.poll(() => listed(page)).toEqual(["/alpha-skill"]);

    await box(page).fill("/alpha-skill Fit my curve skill:use:alpha-skill");
    await expect(options(page)).toHaveCount(1);
    await expect(options(page).first()).toContainText("Use the skill alpha-skill for: Fit my curve");
    await box(page).press("Enter");
    await page.waitForURL(/\/chat\?id=/);

    await answered(page, READ);
    await expect(chip(page)).toHaveText("/alpha-skill");
    await expect(page.getByTestId("user-message")).toContainText("Fit my curve skill:use:alpha-skill");
    await expect(page.getByTestId("user-message")).not.toContainText("/alpha-skill Fit");
    await expect(page.locator('[data-testid="call"][data-call="activate_skill"]')).toHaveCount(1);
    await expect(unmet(page)).toHaveCount(0);
  });

  test("that the lead answers without reading the skill says so, and is sent again with it by Retry and by Edit", async ({ page }) => {
    await box(page).fill("/alpha-skill Fit my curve");
    await box(page).press("Enter");
    await page.waitForURL(/\/chat\?id=/);
    const id = new URL(page.url()).searchParams.get("id") ?? "";

    await answered(page, "You asked:");
    await expect(chip(page)).toHaveText("/alpha-skill");
    await expect(unmet(page)).toHaveText("The lead answered without reading the skill alpha-skill, though /alpha-skill asked for it.");

    // What is sent is what the server is asked, since the answer is the same one
    const sent = () => page.waitForRequest((request) => request.method() === "POST" && request.url().endsWith(`/api/chats/${id}/messages`));
    let request = sent();
    await page.getByRole("button", { name: "Retry" }).click();
    expect((await request).postDataJSON()).toMatchObject({ text: "Fit my curve", replace_last: true, skill: "alpha-skill" });
    await answered(page, "You asked:");
    await expect(chip(page)).toHaveText("/alpha-skill");
    await expect(unmet(page)).toHaveCount(1);

    await page.getByRole("button", { name: "Edit" }).click();
    await page.getByRole("textbox", { name: "Edit message" }).fill("Fit my curve skill:use:alpha-skill");
    request = sent();
    await page.getByRole("button", { name: "Send again" }).click();
    expect((await request).postDataJSON()).toMatchObject({ replace_last: true, skill: "alpha-skill" });
    await answered(page, READ);
    await expect(chip(page)).toHaveText("/alpha-skill");
    await expect(unmet(page)).toHaveCount(0);

    // The conversation was given the skills that were on, so a later message can be given with any of them
    await box(page).fill("/beta-skill Compare the arms skill:use:beta-skill");
    await box(page).press("Enter");
    await expect(chip(page)).toHaveText(["/alpha-skill", "/beta-skill"]);
    await answered(page, READ);
    await expect(unmet(page)).toHaveCount(0);
    expect((await (await page.request.get(`/api/chats/${id}`)).json()).turns).toBe(2);
  });

  test("is not given one that the conversation does not have, which is a message as it was written", async ({ page }) => {
    const made = await page.request.post("/api/chats", { data: { team: [], skills: ["alpha-skill"], title: "Only the first skill" } });
    expect(made.status()).toBe(201);
    await page.goto(`/chat?id=${(await made.json()).id}`);

    await box(page).fill("/beta");
    await expect(menu(page)).toHaveCount(0);
    await box(page).fill("/alp");
    await expect.poll(() => listed(page)).toEqual(["/alpha-skill"]);

    await box(page).fill("/beta-skill Compare the arms");
    await expect(menu(page)).toHaveCount(0);
    await box(page).press("Enter");

    await answered(page, "You asked: /beta-skill Compare the arms");
    await expect(page.getByTestId("user-message")).toHaveText("/beta-skill Compare the arms");
    await expect(chip(page)).toHaveCount(0);
  });

  test("is refused by the server for a skill the conversation does not have, whatever the page says", async ({ page }) => {
    const id = await ask(page, "Hello");
    await answered(page, "You asked: Hello");

    const refused = await page.request.post(`/api/chats/${id}/messages`, { data: { text: "Go", skill: "no-such-skill" } });

    expect(refused.status()).toBe(422);
    expect((await refused.json()).error.message).toContain("no skill called 'no-such-skill'");
  });
});
