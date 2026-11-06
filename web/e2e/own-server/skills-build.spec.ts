import { randomBytes } from "node:crypto";
import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { answered, expect, test } from "../fixtures";
import { INITIAL, resetSkills } from "./state";

// What a program that builds a skill is given, and whether it is made, depends on whether code is turned on, which is the
// server's setting for every program, so each test puts it back, and none is run beside another
test.describe.configure({ mode: "serial" });

const name = () => `e2e-curves-${randomBytes(3).toString("hex")}`;

const message = (page: Page) => page.getByRole("textbox", { name: "Message" });
const buildSkill = (page: Page) => page.getByRole("radio", { name: "Build skill" });
const notice = (page: Page) => page.getByTestId("program-start").getByRole("status");
const calls = (page: Page, tool: string) => page.locator(`[data-testid="call"][data-call="${tool}"]`);

test.beforeEach(async ({ page }) => {
  await resetSkills(page);
});

test.afterEach(async ({ page }) => {
  expect((await page.request.patch("/api/settings", { data: { code: INITIAL.code } })).ok()).toBe(true);
  await resetSkills(page);
});

async function codeOn(page: Page): Promise<void> {
  expect((await page.request.patch("/api/settings", { data: { code: "local" } })).ok()).toBe(true);
}

async function skillNames(page: Page): Promise<string[]> {
  const { skills } = await (await page.request.get("/api/skills")).json();

  return skills.map((skill: { name: string }) => skill.name);
}

test.describe("beginning a program that builds a skill", () => {
  test("is chosen from the home page, and where code is off says so and is not begun, with the way to turn it on", async ({ page }) => {
    await page.goto("/");
    await buildSkill(page).check();
    await expect(page.getByTestId("program-kind-about")).toContainText("saves it among the lab's skills");
    await expect(notice(page)).toContainText("Building a skill needs code to run, and code is turned off");
    await expect(page.getByTestId("program-name")).toHaveCount(0);
    expect(await accessibilityProblems(page)).toEqual([]);

    await message(page).fill("I want a skill for dose-response curves");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByTestId("program-start").getByRole("alert")).toContainText("Building a skill needs code to run");
    await expect(page.getByRole("button", { name: "Open settings" })).toBeFocused();
    expect(await accessibilityProblems(page)).toEqual([]);
    await expect(page).toHaveURL(/\/$/);
    await expect(message(page)).toHaveValue("I want a skill for dose-response curves");

    await page.getByRole("button", { name: "Open settings" }).click();
    const dialog = page.getByRole("dialog", { name: "Settings" });
    await expect(dialog.getByRole("tab", { name: "Code" })).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
  });

  test("is refused by the server where code is off, whatever the page says", async ({ page }) => {
    const refused = await page.request.post("/api/chats", { data: { team: [], kind: "build_skill" } });

    expect(refused.status()).toBe(422);
    expect((await refused.json()).error.message).toContain("Building a skill needs code to run");
  });

  test("is chosen from the menu of new skills on the Skills page, which says nothing of code where it is on", async ({ page }) => {
    await codeOn(page);
    await page.goto("/skills");
    await page.getByRole("button", { name: "New skill" }).click();
    await page.getByRole("menuitem", { name: /Build with Lumi/ }).click();

    await expect(page).toHaveURL(/\/\?program=build_skill$/);
    await expect(buildSkill(page)).toBeChecked();
    await expect(notice(page)).toHaveCount(0);
    expect(await accessibilityProblems(page)).toEqual([]);

    // Taking the other way to a program that is begun as any other is has it begin as one again
    await page.getByRole("link", { name: "New program", exact: true }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("radio", { name: "Quick task" })).toBeChecked();
  });
});

test.describe("building a skill", () => {
  test("is shown first and saved when the researcher has answered, and is then among the skills", async ({ page }) => {
    await codeOn(page);
    const skill = name();
    await page.goto("/?program=build_skill");
    await message(page).fill(`Make a skill, skill:build:${skill}`);
    await page.getByRole("button", { name: "Send" }).click();
    await page.waitForURL(/\/chat\?id=/);
    const id = new URL(page.url()).searchParams.get("id") ?? "";
    await answered(page, "2 steps ran");

    // It is only said what would be saved, and nothing is
    await expect(calls(page, "save_skill")).toHaveCount(1);
    await expect(calls(page, "save_skill")).toContainText("Checked a skill before saving it");
    await expect(page.getByTestId("skill-saved")).toHaveCount(0);
    expect(await skillNames(page)).not.toContain(skill);
    expect((await (await page.request.get(`/api/chats/${id}`)).json()).config.kind).toBe("build_skill");
    await expect(page.getByRole("navigation", { name: "Programs" }).getByTestId("program-kind").first()).toBeVisible();

    await message(page).fill(`Yes, save it, skill:save:${skill}`);
    await page.getByRole("button", { name: "Send" }).click();
    await expect(calls(page, "save_skill")).toHaveCount(2);
    await expect(calls(page, "save_skill").last()).toContainText(`Saved the skill ${skill}`, { timeout: 10_000 });
    await expect(page.getByTestId("chat-state")).toHaveCount(0);
    expect(await skillNames(page)).toContain(skill);

    // It is a skill among the others: it is listed, and a program begun after is given it
    await calls(page, "save_skill").last().locator("summary").click();
    await page.getByTestId("skill-saved").click();
    await expect(page).toHaveURL(/\/skills$/);
    await expect(page.getByTestId("skill-card").filter({ has: page.getByText(skill, { exact: true }) })).toBeVisible();
    const later = await page.request.post("/api/chats", { data: { team: [] } });
    expect((await later.json()).config.skills).toContain(skill);
  });
});
