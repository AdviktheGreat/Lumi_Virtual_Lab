import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { Page, Route } from "@playwright/test";
import { accessibilityProblems, pastTheEdge } from "../axe";
import { expect, test } from "../fixtures";
import { resetSkills } from "./state";

// The skills are the workspace's, and every conversation made after is given those that are on, so each test takes them
// away again, and none is run beside another
test.describe.configure({ mode: "serial" });

const IN_THE_LIBRARY = 50;

// Where the folders that are chosen are, which is on this machine, as it is where the browser is
let scratch = "";

test.beforeEach(async ({ page }) => {
  await resetSkills(page);
  scratch = fs.mkdtempSync(path.join(os.tmpdir(), "vl-e2e-upload-"));
  await page.goto("/skills");
  await expect(page.getByRole("heading", { name: "Skills Nexus", level: 1 })).toBeVisible();
  await expect(page.getByTestId("skills-count")).toHaveText(`${IN_THE_LIBRARY} skills`);
});

test.afterEach(async ({ page }) => {
  fs.rmSync(scratch, { recursive: true, force: true });
  await resetSkills(page);
});

const dialog = (page: Page) => page.getByRole("dialog", { name: "Upload skill" });
const folderInput = (page: Page) => dialog(page).getByLabel("Skill folder");
const upload = (page: Page) => dialog(page).getByRole("button", { name: "Upload", exact: true });
const menu = (page: Page) => page.getByRole("button", { name: "New skill", exact: true });
const mine = (page: Page) => page.getByRole("button", { name: /^Mine/ });
const card = (page: Page, name: string) => page.getByTestId("skill-card").filter({ has: page.getByText(name, { exact: true }) });

async function listed(page: Page) {
  return (await page.request.get("/api/skills")).json();
}

// Writes a folder that has a SKILL.md at its top, and the files that are given, and says where it is
function folder(name: string, skill: string | null, files: Record<string, string> = {}): string {
  const directory = path.join(scratch, name);
  fs.mkdirSync(directory, { recursive: true });
  if (skill !== null) fs.writeFileSync(path.join(directory, "SKILL.md"), skill);
  for (const [file, content] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(directory, file)), { recursive: true });
    fs.writeFileSync(path.join(directory, file), content);
  }

  return directory;
}

const skill = (name: string, description: string) => `---\nname: ${name}\ndescription: ${description}\nlicense: MIT\n---\n\n# ${name}\n\nDo it well.\n`;

async function open(page: Page) {
  await menu(page).click();
  await page.getByRole("menuitem", { name: /^Upload skill/ }).click();
  await expect(dialog(page)).toBeVisible();
}

async function choose(page: Page, where: string) {
  await folderInput(page).setInputFiles(where);
}

test.describe("uploading a skill", () => {
  test("is begun from the New skill menu, and cannot be done before a folder is chosen", async ({ page }) => {
    await open(page);

    await expect(dialog(page)).toContainText("Drop a skill folder here");
    await expect(dialog(page)).toContainText("A skill is a folder with a SKILL.md in it");
    await expect(dialog(page)).toContainText("Upload only skills you trust");
    await expect(dialog(page).getByRole("button", { name: "Choose a folder" })).toBeVisible();
    await expect(upload(page)).toBeDisabled();
    await page.keyboard.press("Escape");

    await expect(dialog(page)).toHaveCount(0);
    await expect(menu(page)).toBeFocused();
  });

  test("shows the folder that was chosen and the skill in it, leaving out what a skill does not need", async ({ page }) => {
    const where = folder("dose-folder", skill("dose-response", "Fits a dose-response curve."), {
      "scripts/fit.py": "print('fit')",
      ".git/config": "[core]",
      ".DS_Store": "x",
    });
    await open(page);

    await choose(page, where);

    await expect(dialog(page).getByTestId("skill-folder-name")).toHaveText("dose-folder");
    await expect(dialog(page)).toContainText("2 files");
    await expect(dialog(page)).toContainText("2 left out that a skill does not need");
    await expect(dialog(page)).toContainText("1 skill in it");
    await expect(dialog(page).getByRole("list", { name: "Skills in the folder" })).toContainText("dose-response");
    await expect(dialog(page).getByRole("list", { name: "Skills in the folder" })).toContainText("Fits a dose-response curve.");
    await expect(upload(page)).toBeEnabled();
    await expect(upload(page)).toBeFocused();
  });

  test("puts the skill in with its files, as a copy, and it is then on the page and on", async ({ page }) => {
    const where = folder("dose-folder", skill("dose-response", "Fits a dose-response curve."), {
      "scripts/fit.py": "print('fit')",
      "references/guide.md": "Guide.",
      ".git/config": "[core]",
      ".DS_Store": "x",
    });
    await open(page);
    await choose(page, where);

    await upload(page).click();

    await expect(dialog(page).getByTestId("skills-put-in")).toContainText("Put in 1 skill.");
    await expect(dialog(page)).toContainText("dose-response is now with the lab's skills, and on");
    await expect(dialog(page).getByRole("button", { name: "Done" })).toBeFocused();
    await dialog(page).getByRole("button", { name: "Done" }).click();
    await expect(dialog(page)).toHaveCount(0);
    await expect(menu(page)).toBeFocused();
    await expect(mine(page)).toHaveText("Mine1");
    await mine(page).click();
    await expect(card(page, "dose-response")).toContainText("Fits a dose-response curve.");
    await expect(card(page, "dose-response").getByRole("switch")).toHaveAttribute("aria-checked", "true");
    const kept = await listed(page);
    const put = path.join(kept.folders[0].path, "dose-response");
    expect(fs.readFileSync(path.join(put, "scripts", "fit.py"), "utf8")).toBe("print('fit')");
    expect(fs.readFileSync(path.join(put, "references", "guide.md"), "utf8")).toBe("Guide.");
    expect(fs.existsSync(path.join(put, ".git"))).toBe(false);
    expect(fs.existsSync(path.join(put, ".DS_Store"))).toBe(false);
    // The folder it was chosen from is as it was
    expect(fs.existsSync(path.join(where, "SKILL.md"))).toBe(true);
  });

  test("puts in each skill of a folder that has several, and is begun again by Upload another", async ({ page }) => {
    const where = folder("collection", null, {
      "skills/dose-response/SKILL.md": skill("dose-response", "Fits a curve."),
      "skills/rna-seq/SKILL.md": skill("rna-seq", "Differential expression."),
    });
    await open(page);

    await choose(page, where);

    await expect(dialog(page)).toContainText("2 skills in it");
    await expect(dialog(page).getByRole("list", { name: "Skills in the folder" })).toContainText("skills/rna-seq/SKILL.md");
    await upload(page).click();
    await expect(dialog(page).getByTestId("skills-put-in")).toContainText("Put in 2 skills.");
    await dialog(page).getByRole("button", { name: "Upload another" }).click();

    await expect(dialog(page)).toContainText("Drop a skill folder here");
    expect((await listed(page)).skills.map((each: { name: string }) => each.name)).toEqual(["dose-response", "rna-seq"]);
  });

  test("is replaced by a folder that is chosen after it", async ({ page }) => {
    const first = folder("first", skill("first-skill", "The first."));
    const second = folder("second", skill("second-skill", "The second."));
    await open(page);
    await choose(page, first);
    await expect(dialog(page).getByTestId("skill-folder-name")).toHaveText("first");

    await dialog(page).getByRole("button", { name: "Choose another" }).click();
    await choose(page, second);

    await expect(dialog(page).getByTestId("skill-folder-name")).toHaveText("second");
    await expect(dialog(page)).not.toContainText("first-skill");
    await expect(dialog(page)).toContainText("second-skill");
  });

  test("is refused before it is sent when the folder has no SKILL.md", async ({ page }) => {
    const sent: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/api/skills")) sent.push(request.url());
    });
    await open(page);

    await choose(page, folder("notes", null, { "README.md": "Not a skill.", "skill.md": "Wrong case." }));

    await expect(dialog(page).getByRole("alert")).toContainText("There is no SKILL.md in notes.");
    await expect(upload(page)).toBeDisabled();
    expect(sent).toEqual([]);
    // Another folder can be chosen over it
    await dialog(page).getByRole("button", { name: "Choose another" }).click();
    await choose(page, folder("fine", skill("fine-skill", "Fine.")));
    await expect(dialog(page).getByRole("alert")).toHaveCount(0);
    await expect(upload(page)).toBeEnabled();
  });

  test("says before it is sent that a skill is left out for being one that you have, and again after", async ({ page }) => {
    await open(page);
    await choose(page, folder("dose-folder", skill("dose-response", "Fits a curve.")));
    await upload(page).click();
    await expect(dialog(page).getByTestId("skills-put-in")).toContainText("Put in 1 skill.");
    await dialog(page).getByRole("button", { name: "Upload another" }).click();

    await choose(page, folder("again", skill("dose-response", "Fits a curve, again.")));

    await expect(dialog(page).getByRole("list", { name: "Skills in the folder" })).toContainText("You already have a skill with this name");
    await upload(page).click();
    const said = dialog(page).getByTestId("skills-put-in");
    await expect(said).toContainText("Nothing new was put in: 1 left.");
    await said.getByText("Which were left, and why").click();
    await expect(page.getByRole("list", { name: "Skills that were left" })).toContainText("you already have a skill with that name");
    expect((await listed(page)).skills).toHaveLength(1);
  });

  test("says before it is sent that a skill has no description, and the server leaves it out with why", async ({ page }) => {
    await open(page);

    await choose(page, folder("nameless", "---\nname: nameless-skill\n---\n\nBody.\n"));

    await expect(dialog(page).getByRole("list", { name: "Skills in the folder" })).toContainText("No description was found");
    await upload(page).click();
    const said = dialog(page).getByTestId("skills-put-in");
    await expect(said).toContainText("Nothing new was put in: 1 left.");
    await said.getByText("Which were left, and why").click();
    await expect(page.getByRole("list", { name: "Skills that were left" })).toContainText("it has no description");
    expect((await listed(page)).skills).toEqual([]);
  });

  test("is not closed while the folder is being sent, and can be called off", async ({ page }) => {
    let held: Route | undefined;
    await page.route("**/api/skills/upload", (route) => {
      held = route;
    });
    await open(page);
    await choose(page, folder("dose-folder", skill("dose-response", "Fits a curve.")));

    await upload(page).click();

    await expect(dialog(page).getByRole("progressbar", { name: "Uploading dose-folder" })).toBeVisible();
    await expect(dialog(page).getByRole("button", { name: "Uploading…" })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog(page)).toBeVisible();
    await dialog(page).getByRole("button", { name: "Cancel the upload" }).click();

    await expect(dialog(page).getByRole("progressbar")).toHaveCount(0);
    await expect(dialog(page).getByRole("alert")).toHaveCount(0);
    await expect(upload(page)).toBeEnabled();
    // What was held is dropped, and not let through to the server after it was called off
    await held?.abort().catch(() => undefined);
    await page.unroute("**/api/skills/upload");
    expect((await listed(page)).skills).toEqual([]);
    // The dialog can be closed again
    await page.keyboard.press("Escape");
    await expect(dialog(page)).toHaveCount(0);
  });

  test("tells what the server refused with, and leaves the folder chosen to be sent again", async ({ page }) => {
    await page.route("**/api/skills/upload", (route) =>
      route.fulfill({
        status: 413,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "too_large", message: "The folder is more than 50 MB, which is more than a skill needs" } }),
      }),
    );
    await open(page);
    await choose(page, folder("dose-folder", skill("dose-response", "Fits a curve.")));

    await upload(page).click();

    await expect(dialog(page).getByRole("alert")).toContainText("The folder is more than 50 MB");
    await expect(dialog(page).getByTestId("skill-folder-name")).toHaveText("dose-folder");
    await expect(upload(page)).toBeEnabled();
  });

  test("lights the place for it when a file is dragged over, and takes only a folder that is dropped", async ({ page }) => {
    await open(page);
    const zone = dialog(page).getByTestId("skill-folder-zone");
    const transfer = await page.evaluateHandle(() => {
      const made = new DataTransfer();
      made.items.add(new File(["x"], "SKILL.md"));

      return made;
    });

    await zone.dispatchEvent("dragover", { dataTransfer: transfer });
    await expect(zone).toHaveAttribute("data-dragging", "true");
    await zone.dispatchEvent("dragleave", { dataTransfer: transfer });
    await expect(zone).toHaveAttribute("data-dragging", "false");
    await zone.dispatchEvent("drop", { dataTransfer: transfer });

    await expect(dialog(page).getByRole("alert")).toBeVisible();
    await expect(upload(page)).toBeDisabled();
    expect((await listed(page)).skills).toEqual([]);
  });

  test("has nothing wrong that axe can find, and fits a narrow screen", async ({ page }) => {
    await open(page);
    // The dialog fades in, and is not looked at until it has
    await expect(dialog(page)).toHaveCSS("opacity", "1");
    expect(await accessibilityProblems(page)).toEqual([]);

    await choose(page, folder("dose-folder", skill("dose-response", "Fits a curve. ".repeat(40)), { "scripts/fit.py": "x" }));
    await expect(dialog(page).getByTestId("skill-folder-name")).toBeVisible();
    // The button that was off fades to on, and is not looked at until it has
    await expect(upload(page)).toBeEnabled();
    await expect(upload(page)).toHaveCSS("opacity", "1");
    expect(await accessibilityProblems(page)).toEqual([]);
    await page.setViewportSize({ width: 390, height: 800 });
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);

    await choose(page, folder("notes", null, { "README.md": "x" }));
    await expect(dialog(page).getByRole("alert")).toBeVisible();
    expect(await accessibilityProblems(page)).toEqual([]);
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);
  });
});
