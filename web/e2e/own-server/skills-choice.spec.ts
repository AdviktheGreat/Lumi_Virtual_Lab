import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { Page } from "@playwright/test";
import { accessibilityProblems, pastTheEdge } from "../axe";
import { ask, expect, test } from "../fixtures";
import { resetSkills } from "./state";

// The skills are the workspace's, which every conversation made after is given those of that are on, so each test takes them
// away again, and none is run beside another
test.describe.configure({ mode: "serial" });

let scratch = "";

const SKILLS = ["alpha-skill", "beta-skill", "gamma-skill"];

function write(name: string, description: string): void {
  const directory = path.join(scratch, name);
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, "SKILL.md"), `---\nname: ${name}\ndescription: ${description}\n---\n\n# ${name}\n`);
}

async function install(page: Page): Promise<void> {
  const response = await page.request.post("/api/skills/install", { data: { path: scratch } });
  expect(response.status()).toBe(200);
}

test.beforeEach(async ({ page }) => {
  await resetSkills(page);
  scratch = fs.mkdtempSync(path.join(os.tmpdir(), "vl-e2e-skill-choice-"));
  write("alpha-skill", "Fits curves to titration data.");
  write("beta-skill", "Differential expression with DESeq2.");
  write("gamma-skill", "Makes figures that follow a journal's style.");
  await install(page);
  await page.goto("/");
  await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
});

test.afterEach(async ({ page }) => {
  fs.rmSync(scratch, { recursive: true, force: true });
  await resetSkills(page);
});

const dialog = (page: Page) => page.getByTestId("skills-dialog");
const button = (page: Page) => page.getByTestId("skills-button");
const box = (page: Page) => page.getByRole("textbox", { name: "Message" });
const chosen = (page: Page) => dialog(page).getByTestId("skills-chosen");
const tick = (page: Page, name: string) => dialog(page).getByRole("checkbox", { name, exact: true });

async function turnOff(page: Page, names: string[]): Promise<void> {
  expect((await page.request.put("/api/skills", { data: { disabled: names } })).status()).toBe(200);
  await page.reload();
  await expect(box(page)).toBeVisible();
}

async function skillsOf(page: Page, id: string): Promise<string[]> {
  return (await (await page.request.get(`/api/chats/${id}`)).json()).config.skills;
}

async function open(page: Page): Promise<void> {
  await button(page).click();
  await expect(dialog(page).getByRole("heading", { name: "Choose the skills" })).toBeVisible();
  await expect(tick(page, "alpha-skill")).toBeVisible();
}

test.describe("choosing the skills of a conversation on the page where it begins", () => {
  test("starts from those that are on for new conversations, and the conversation is given what was chosen", async ({ page }) => {
    await turnOff(page, ["beta-skill"]);
    await expect(button(page)).toHaveText("Skills");
    await open(page);

    await expect(chosen(page)).toHaveText("2 of 3 skills chosen");
    await expect(tick(page, "alpha-skill")).toBeChecked();
    await expect(tick(page, "beta-skill")).not.toBeChecked();
    await expect(tick(page, "gamma-skill")).toBeChecked();

    await tick(page, "alpha-skill").uncheck();
    await tick(page, "beta-skill").check();
    await expect(chosen(page)).toHaveText("2 of 3 skills chosen");
    await dialog(page).getByRole("button", { name: "Use these" }).click();
    await expect(dialog(page)).toHaveCount(0);
    await expect(button(page)).toHaveText("Skills · 2");

    const id = await ask(page, "Which skills do you have?");
    expect(await skillsOf(page, id)).toEqual(["beta-skill", "gamma-skill"]);
  });

  test("is not kept as a choice where it is what is on anyway, so a skill turned on later is given", async ({ page }) => {
    await turnOff(page, ["beta-skill"]);
    await open(page);
    await tick(page, "beta-skill").check();
    await tick(page, "beta-skill").uncheck();
    await dialog(page).getByRole("button", { name: "Use these" }).click();
    await expect(button(page)).toHaveText("Skills");

    expect((await page.request.put("/api/skills", { data: { disabled: [] } })).status()).toBe(200);
    const id = await ask(page, "Is beta there now?");
    expect(await skillsOf(page, id)).toEqual(SKILLS);
  });

  test("can be cancelled, which keeps what was chosen before", async ({ page }) => {
    await open(page);
    await tick(page, "alpha-skill").uncheck();
    await tick(page, "beta-skill").uncheck();
    await dialog(page).getByRole("button", { name: "Use these" }).click();
    await expect(button(page)).toHaveText("Skills · 1");

    await open(page);
    await expect(chosen(page)).toHaveText("1 of 3 skills chosen");
    await tick(page, "gamma-skill").uncheck();
    await dialog(page).getByRole("button", { name: "Cancel" }).click();
    await expect(dialog(page)).toHaveCount(0);
    await expect(button(page)).toHaveText("Skills · 1");

    await open(page);
    await expect(tick(page, "gamma-skill")).toBeChecked();
    await page.keyboard.press("Escape");
    await expect(dialog(page)).toHaveCount(0);
    await expect(button(page)).toHaveText("Skills · 1");
  });

  test("can leave all of them out, and the conversation is given none", async ({ page }) => {
    await open(page);
    await dialog(page).getByRole("button", { name: "Leave all out" }).click();
    await expect(chosen(page)).toHaveText("No skill chosen, of 3");
    await expect(dialog(page).getByRole("button", { name: "Leave all out" })).toHaveAttribute("aria-disabled", "true");
    await dialog(page).getByRole("button", { name: "Use these" }).click();
    await expect(button(page)).toHaveText("Skills · none");

    const id = await ask(page, "With no skills");
    expect(await skillsOf(page, id)).toEqual([]);
  });

  test("is searched, and choosing all or leaving out is of those found only", async ({ page }) => {
    await open(page);
    await dialog(page).getByRole("button", { name: "Leave all out" }).click();
    await dialog(page).getByRole("searchbox", { name: "Search the skills" }).fill("deseq2");
    await expect(dialog(page).getByTestId("skill-choice")).toHaveCount(1);
    await dialog(page).getByRole("button", { name: "Choose these" }).click();
    await dialog(page).getByRole("searchbox", { name: "Search the skills" }).fill("");
    await expect(chosen(page)).toHaveText("1 of 3 skills chosen");
    await expect(tick(page, "beta-skill")).toBeChecked();
    await expect(tick(page, "alpha-skill")).not.toBeChecked();

    await dialog(page).getByRole("searchbox", { name: "Search the skills" }).fill("nothing like this");
    await expect(dialog(page).getByText("No skill has all of those words.")).toBeVisible();
  });

  test("/skills opens the same choice", async ({ page }) => {
    await box(page).fill("/skills");
    await box(page).press("Enter");
    await expect(dialog(page).getByRole("heading", { name: "Choose the skills" })).toBeVisible();
    // The box is found by what it is made of, since the dialog hides the page from what is found by its role
    await expect(page.locator('textarea[aria-label="Message"]')).toHaveValue("");
  });

  test("says where to put skills in when there are none", async ({ page }) => {
    await resetSkills(page);
    await button(page).click();

    await expect(dialog(page).getByText("There are no skills yet.")).toBeVisible();
    await expect(dialog(page).getByRole("link", { name: "Data page" })).toHaveAttribute("href", "/data");
    await expect(dialog(page).getByRole("button", { name: "Use these" })).toBeDisabled();
  });

  test("has nothing wrong that axe can find, and fits a narrow screen", async ({ page }) => {
    await open(page);
    expect(await accessibilityProblems(page)).toEqual([]);

    await page.setViewportSize({ width: 360, height: 700 });
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);
    await expect(dialog(page).getByRole("button", { name: "Use these" })).toBeInViewport();
  });
});

test.describe("the skills of a conversation that has begun", () => {
  test("are shown by /skills, as it was given them and not as they are on for new conversations", async ({ page }) => {
    const made = await page.request.post("/api/chats", { data: { title: "Skill view", skills: ["alpha-skill", "gamma-skill"] } });
    expect(made.status()).toBe(201);
    const id: string = (await made.json()).id;
    await turnOff(page, []);
    await page.goto(`/chat?id=${id}`);

    await box(page).fill("/skills");
    await box(page).press("Enter");

    await expect(dialog(page).getByRole("heading", { name: "The skills of this conversation" })).toBeVisible();
    await expect(dialog(page).getByTestId("skills-given")).toHaveText("2 skills");
    await expect(dialog(page).getByTestId("skill-given").locator("code")).toHaveText(["alpha-skill", "gamma-skill"]);
    await expect(dialog(page).getByText("Fits curves to titration data.")).toBeVisible();
    await expect(dialog(page).getByRole("checkbox")).toHaveCount(0);
    await dialog(page).getByRole("button", { name: "Close" }).click();
    await expect(dialog(page)).toHaveCount(0);
  });

  test("say so of a skill that is not there any more", async ({ page }) => {
    const made = await page.request.post("/api/chats", { data: { title: "Skill gone", skills: ["alpha-skill", "beta-skill"] } });
    const id: string = (await made.json()).id;
    expect((await page.request.delete("/api/skills/beta-skill")).status()).toBe(200);
    await page.goto(`/chat?id=${id}`);

    await box(page).fill("/skills");
    await box(page).press("Enter");

    await expect(dialog(page).getByTestId("skill-given").filter({ hasText: "beta-skill" })).toContainText("not there any more");
    await expect(dialog(page).getByTestId("skill-given").filter({ hasText: "alpha-skill" })).not.toContainText("not there any more");
  });

  test("say that there were none, where none was given", async ({ page }) => {
    const made = await page.request.post("/api/chats", { data: { title: "No skills at all", skills: [] } });
    const id: string = (await made.json()).id;
    await page.goto(`/chat?id=${id}`);

    await box(page).fill("/skills");
    await box(page).press("Enter");

    await expect(dialog(page).getByText("This conversation was given no skills.")).toBeVisible();
    expect(await accessibilityProblems(page)).toEqual([]);
  });
});
