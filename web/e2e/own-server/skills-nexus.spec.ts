import type { Page } from "@playwright/test";
import { accessibilityProblems, pastTheEdge } from "../axe";
import { expect, test } from "../fixtures";
import { resetSkills } from "./state";

// The skills added are the workspace's, and every conversation made after is given those that are on, so each test takes
// them away again, and none is run beside another. The library they are added from is the server's own, with five skills
// in it that are named here, and forty-five more of the same that make more than a page shows (see write_skill_library in
// e2e/scripted_server.py).
test.describe.configure({ mode: "serial" });

const IN_THE_LIBRARY = 50;
const SHOWN = 36;

test.beforeEach(async ({ page }) => {
  await resetSkills(page);
  await page.goto("/skills");
  await expect(count(page)).toHaveText(`${IN_THE_LIBRARY} skills`);
});

test.afterEach(async ({ page }) => {
  await resetSkills(page);
});

const card = (page: Page, name: string) => page.getByTestId("skill-card").filter({ has: page.getByText(name, { exact: true }) });
const cards = (page: Page) => page.getByTestId("skill-card");
const count = (page: Page) => page.getByTestId("skills-count");
const search = (page: Page) => page.getByRole("searchbox", { name: "Search all skills" });
const category = (page: Page) => page.getByRole("combobox", { name: "Category" });
const chip = (page: Page, name: string) => page.getByRole("group", { name: "Where skills come from" }).getByRole("button", { name: new RegExp(`^${name}`) });
const dialog = (page: Page) => page.getByRole("alertdialog");
const detail = (page: Page, name: string) => page.getByRole("dialog", { name });
const read = (page: Page, name: string) => card(page, name).locator("button[aria-haspopup='dialog']").click();
const addButton = (page: Page, name: string) => card(page, name).getByRole("button", { name: `Add ${name}` });
const switchOf = (page: Page, name: string) => card(page, name).getByRole("switch", { name: `Give new conversations ${name}` });

async function kept(page: Page) {
  return (await page.request.get("/api/skills")).json();
}

test.describe("the Skills Nexus", () => {
  test("is reached from the rail, and shows the skills as cards, without saying where the library came from", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Skills" }).click();

    await expect(page).toHaveURL(/\/skills$/);
    await expect(page.getByRole("heading", { name: "Skills Nexus", level: 1 })).toBeVisible();
    await expect(page.getByRole("tab")).toHaveCount(0);
    await expect(cards(page)).toHaveCount(SHOWN);
    await expect(chip(page, "All")).toHaveText(`All${IN_THE_LIBRARY}`);
    await expect(chip(page, "Mine")).toHaveText("Mine0");
    await expect(chip(page, "Built in")).toHaveText("Built in0");
    await expect(chip(page, "Library")).toHaveText(`Library${IN_THE_LIBRARY}`);
    // Where the library came from, and by whom, is in the notice that comes with the lab, and not on the page
    for (const text of ["Test Skills", "The Tests", "1.2.3", "example.com"]) await expect(page.locator("main")).not.toContainText(text);
  });

  test("shows each skill with its category, and stands out for a license that limits its use", async ({ page }) => {
    await expect(card(page, "dose-curves")).toContainText("Statistics");
    await expect(card(page, "dose-curves")).toContainText("Fits dose-response curves to titration data and reports the IC50.");
    await expect(card(page, "dose-curves")).toContainText("Library");
    await expect(card(page, "dose-curves").getByText("Noncommercial")).toHaveCount(0);
    await expect(card(page, "spatial-guess").getByText("Noncommercial", { exact: true })).toHaveAttribute("data-variant", "destructive");
  });

  test("is read before it is added: what it tells the lead, its files, and what its license means", async ({ page }) => {
    await read(page, "spatial-guess");

    const skill = detail(page, "spatial-guess");
    await expect(skill.getByRole("region", { name: "What spatial-guess tells the lead" })).toContainText("Follow the spatial-guess steps.");
    await expect(skill.getByText("Its license allows noncommercial use only.")).toBeVisible();
    await expect(skill.getByText("PolyForm-Noncommercial-1.0.0", { exact: true })).toHaveAttribute("data-variant", "destructive");
    await expect(skill.getByText("1 file, 100 bytes")).toBeVisible();
    await expect(skill.getByRole("button", { name: "Add spatial-guess" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(skill).toHaveCount(0);

    await read(page, "rna-counts");
    await expect(detail(page, "rna-counts").getByText("Apache-2.0", { exact: true })).toBeVisible();
    await expect(detail(page, "rna-counts").getByRole("list", { name: "Files of rna-counts" }).getByText("scripts/count.py")).toBeVisible();
    await page.keyboard.press("Escape");

    await read(page, "cell-types");
    await expect(detail(page, "cell-types").getByText("No license stated", { exact: true })).toBeVisible();
    await expect(detail(page, "cell-types").getByText("It states no license of its own, so only the library's MIT license covers it.")).toBeVisible();
    await page.keyboard.press("Escape");

    await read(page, "pathway-flux");
    await expect(detail(page, "pathway-flux").getByText("GPL-3.0-or-later", { exact: true })).toBeVisible();
  });

  test("is found by words, by where it comes from, and by category, and a search that finds none says so", async ({ page }) => {
    await search(page).fill("CELL types");
    await expect(count(page)).toHaveText(`1 of ${IN_THE_LIBRARY} skills`);
    await expect(cards(page)).toHaveCount(1);

    await search(page).fill("");
    await category(page).selectOption({ label: "Genomics (2)" });
    await expect(count(page)).toHaveText(`2 of ${IN_THE_LIBRARY} skills`);
    await expect(cards(page)).toHaveCount(2);

    await search(page).fill("dose");
    await expect(page.getByRole("status").filter({ hasText: "No skill matches those words." })).toBeVisible();

    await search(page).fill("");
    await category(page).selectOption({ label: "All categories" });
    await chip(page, "Built in").click();
    await expect(page.getByText("The lab has no skills built in.")).toBeVisible();
    await expect(chip(page, "Built in")).toHaveAttribute("aria-pressed", "true");
    await chip(page, "Library").click();
    await expect(count(page)).toHaveText(`${IN_THE_LIBRARY} skills`);
  });

  test("is shown a few at a time", async ({ page }) => {
    await expect(cards(page)).toHaveCount(SHOWN);

    await page.getByRole("button", { name: `Show more (${IN_THE_LIBRARY - SHOWN} left)` }).click();

    await expect(cards(page)).toHaveCount(IN_THE_LIBRARY);
    await expect(page.getByRole("button", { name: /Show more/ })).toHaveCount(0);
  });

  test("is added after a question that says what it costs and what its license means, and is then on", async ({ page }) => {
    await addButton(page, "spatial-guess").click();

    await expect(dialog(page).getByRole("heading", { name: "Add spatial-guess?" })).toBeVisible();
    await expect(dialog(page).getByText(/It adds about \d+ tokens to the start of every conversation/)).toBeVisible();
    await expect(dialog(page).getByRole("list", { name: "About their licenses" }).getByRole("listitem")).toHaveText([
      "spatial-guess allows noncommercial use only.",
    ]);
    await dialog(page).getByRole("button", { name: "Cancel" }).click();
    await expect(addButton(page, "spatial-guess")).toBeFocused();
    expect((await kept(page)).skills).toEqual([]);

    await addButton(page, "spatial-guess").click();
    await dialog(page).getByRole("button", { name: "Add", exact: true }).click();

    await expect(page.getByTestId("skills-put-in")).toHaveText("Put in 1 skill.");
    await expect(switchOf(page, "spatial-guess")).toHaveAttribute("aria-checked", "true");
    await expect(addButton(page, "spatial-guess")).toHaveCount(0);
    await expect(count(page)).toHaveText(`${IN_THE_LIBRARY} skills, 1 on`);
    await expect(chip(page, "Mine")).toHaveText("Mine0");
    await expect(chip(page, "Library")).toHaveText(`Library${IN_THE_LIBRARY}`);
    await expect(page.getByTestId("skills-meter")).toContainText("The skill that is on takes about");
    const listed = await kept(page);
    expect(listed.skills.map((skill: { name: string; enabled: boolean; source: string }) => [skill.name, skill.enabled, skill.source])).toEqual([
      ["spatial-guess", true, "workspace"],
    ]);
    const chat = await (await page.request.post("/api/chats", { data: { team: [] } })).json();
    expect(chat.skills).toEqual(["spatial-guess"]);
    await page.request.delete(`/api/chats/${chat.id}`);
  });

  test("says what a license that states none, or sets conditions, means before it is added", async ({ page }) => {
    await addButton(page, "pathway-flux").click();
    await expect(dialog(page).getByRole("list", { name: "About their licenses" }).getByRole("listitem")).toHaveText([
      "pathway-flux is under a GPL license, which sets conditions on sharing it.",
    ]);
    await dialog(page).getByRole("button", { name: "Cancel" }).click();

    await category(page).selectOption({ label: "Genomics (2)" });
    await page.getByRole("button", { name: "Add these 2" }).click();
    await expect(dialog(page).getByRole("heading", { name: "Add 2 skills?" })).toBeVisible();
    await expect(dialog(page).getByText(/Together they add about \d+ tokens to the start of every conversation/)).toBeVisible();
    await expect(dialog(page).getByRole("list", { name: "About their licenses" }).getByRole("listitem")).toHaveText([
      "cell-types states no license, so only the library's MIT license covers it.",
    ]);
  });

  test("is added as a whole, for what was found", async ({ page }) => {
    await search(page).fill("filler");
    await expect(count(page)).toHaveText(`45 of ${IN_THE_LIBRARY} skills`);
    await page.getByRole("button", { name: "Add these 45" }).click();

    await expect(dialog(page).getByRole("heading", { name: "Add 45 skills?" })).toBeVisible();
    await expect(dialog(page).getByRole("list", { name: "About their licenses" })).toHaveCount(0);
    await dialog(page).getByRole("button", { name: "Add", exact: true }).click();

    await expect(page.getByTestId("skills-put-in")).toHaveText("Put in 45 skills.");
    expect((await kept(page)).skills).toHaveLength(45);
    await expect(count(page)).toHaveText(`45 of ${IN_THE_LIBRARY} skills, 45 on`);
    await expect(page.getByRole("button", { name: /^Add these/ })).toHaveCount(0);
    await page.getByRole("button", { name: "Turn these off" }).click();
    await expect(count(page)).toHaveText(`45 of ${IN_THE_LIBRARY} skills, 0 on`);
    await page.getByRole("button", { name: "Turn these on" }).click();
    await expect(count(page)).toHaveText(`45 of ${IN_THE_LIBRARY} skills, 45 on`);
  });

  test("is added from where it is read", async ({ page }) => {
    await read(page, "rna-counts");
    await detail(page, "rna-counts").getByRole("button", { name: "Add rna-counts" }).click();
    await dialog(page).getByRole("button", { name: "Add", exact: true }).click();

    await expect(page.getByTestId("skills-put-in")).toHaveText("Put in 1 skill.");
    await expect(detail(page, "rna-counts").getByRole("switch", { name: "Give new conversations rna-counts" })).toHaveAttribute("aria-checked", "true");
    await expect(detail(page, "rna-counts").getByRole("button", { name: "Delete rna-counts" })).toBeVisible();
    expect((await kept(page)).skills.map((skill: { name: string }) => skill.name)).toEqual(["rna-counts"]);
  });

  test("is offered again once it is deleted", async ({ page }) => {
    expect((await page.request.post("/api/skill-library/install", { data: { names: ["dose-curves", "rna-counts"] } })).ok()).toBe(true);
    await page.reload();
    await expect(switchOf(page, "dose-curves")).toHaveAttribute("aria-checked", "true");

    await read(page, "dose-curves");
    await detail(page, "dose-curves").getByRole("button", { name: "Delete dose-curves" }).click();
    await dialog(page).getByRole("button", { name: "Delete", exact: true }).click();
    await expect(page.getByText("Deleted dose-curves.")).toBeVisible();

    await expect(addButton(page, "dose-curves")).toBeVisible();
    await expect(switchOf(page, "dose-curves")).toHaveCount(0);
    await expect(switchOf(page, "rna-counts")).toBeVisible();
  });

  test("is added to by a menu that offers to upload a skill folder, or to put in skills from a repository or a folder", async ({ page }) => {
    const menu = page.getByRole("button", { name: "New skill", exact: true });
    await menu.click();

    await expect(page.getByRole("menuitem")).toHaveText([/^Upload skill/, /^From a repository or folder/]);
    await page.getByRole("menuitem", { name: /^From a repository or folder/ }).click();
    const from = page.getByRole("dialog", { name: "From a repository or folder" });
    await expect(from.getByRole("form", { name: "Put in skills" })).toBeVisible();
    await page.keyboard.press("Escape");

    await expect(from).toHaveCount(0);
    await expect(menu).toBeFocused();
  });

  test("is no longer on the Data page, whose other parts are as they were", async ({ page }) => {
    await page.goto("/data");

    await expect(page.getByRole("heading", { name: "Your data", level: 2 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Skills", level: 2 })).toHaveCount(0);
    await expect(page.getByRole("form", { name: "Put in skills" })).toHaveCount(0);
  });

  test("has nothing wrong that axe can find, and fits a narrow screen", async ({ page }) => {
    expect(await accessibilityProblems(page)).toEqual([]);

    await read(page, "pathway-flux");
    await expect(detail(page, "pathway-flux").getByRole("region", { name: "What pathway-flux tells the lead" })).toContainText("Follow the pathway-flux steps.");
    await expect(detail(page, "pathway-flux")).toHaveCSS("opacity", "1");
    expect(await accessibilityProblems(page)).toEqual([]);
    await page.keyboard.press("Escape");

    await addButton(page, "dose-curves").click();
    await expect(dialog(page).getByRole("heading", { name: "Add dose-curves?" })).toBeVisible();
    await expect(dialog(page)).toHaveCSS("opacity", "1");
    expect(await accessibilityProblems(page)).toEqual([]);
    await dialog(page).getByRole("button", { name: "Cancel" }).click();

    await page.setViewportSize({ width: 360, height: 700 });
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);
    await read(page, "rna-counts");
    await expect(detail(page, "rna-counts")).toBeVisible();
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);
  });
});
