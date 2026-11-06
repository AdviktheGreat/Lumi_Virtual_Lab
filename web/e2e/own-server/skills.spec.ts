import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { Page } from "@playwright/test";
import { accessibilityProblems, pastTheEdge } from "../axe";
import { expect, test } from "../fixtures";
import { resetSkills } from "./state";

// The skills are the workspace's, and every conversation made after is given those that are on, so each test takes them
// away again, and none is run beside another
test.describe.configure({ mode: "serial" });

// The skills of the library the server has, which are on the page beside those a test puts in (see write_skill_library in
// e2e/scripted_server.py)
const IN_THE_LIBRARY = 50;

// Where the skills that are put in from are, which is on this machine, as it is where the server is
let scratch = "";

test.beforeEach(async ({ page }) => {
  await resetSkills(page);
  scratch = fs.mkdtempSync(path.join(os.tmpdir(), "vl-e2e-skills-"));
  await page.goto("/skills");
  await expect(page.getByRole("heading", { name: "Skills Nexus", level: 1 })).toBeVisible();
  await expect(count(page)).toHaveText(`${IN_THE_LIBRARY} skills`);
});

test.afterEach(async ({ page }) => {
  fs.rmSync(scratch, { recursive: true, force: true });
  await resetSkills(page);
});

const addDialog = (page: Page) => page.getByRole("dialog", { name: "Add skills" });
const form = (page: Page) => addDialog(page).getByRole("form", { name: "Put in skills" });
const card = (page: Page, name: string) => page.getByTestId("skill-card").filter({ has: page.getByText(name, { exact: true }) });
const cards = (page: Page) => page.getByTestId("skill-card");
const count = (page: Page) => page.getByTestId("skills-count");
const search = (page: Page) => page.getByRole("searchbox", { name: "Search all skills" });
const mine = (page: Page) => page.getByRole("button", { name: /^Mine/ });
const switchOf = (page: Page, name: string) => card(page, name).getByRole("switch", { name: `Give new conversations ${name}` });
const detail = (page: Page, name: string) => page.getByRole("dialog", { name });

async function listed(page: Page) {
  return (await page.request.get("/api/skills")).json();
}

// Writes a skill in a folder of the scratch folder, and says where that folder is
function write(folder: string, name: string, description: string, files: Record<string, string> = {}): string {
  const directory = path.join(scratch, folder, name);
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, "SKILL.md"), `---\nname: ${name}\ndescription: ${description}\nlicense: MIT\n---\n\n# ${name}\n\nDo it well.\n`);
  for (const [file, content] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(directory, file)), { recursive: true });
    fs.writeFileSync(path.join(directory, file), content);
  }

  return path.join(scratch, folder);
}

async function openAdd(page: Page) {
  await page.getByRole("button", { name: "Add skills", exact: true }).click();
  await expect(addDialog(page)).toBeVisible();
}

async function closeAdd(page: Page) {
  await page.keyboard.press("Escape");
  await expect(addDialog(page)).toHaveCount(0);
}

// Puts in the skills of a folder, answering the question that asks whether to. The dialog it is done in is left open, so
// that what it says can be read.
async function putIn(page: Page, where: string) {
  // The dialog is hidden from what is found by its role while a question is over it, so it is found by what is in it
  if (!(await page.getByLabel("Put in skills from").isVisible())) await openAdd(page);
  await form(page).getByLabel("Put in skills from").fill(where);
  await form(page).getByRole("button", { name: "Put in the skills" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Put them in" }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
}

// Puts them in and shows the skills put in, which are the ones that are not the library's
async function putInAndShow(page: Page, where: string) {
  await putIn(page, where);
  await expect(addDialog(page).getByTestId("skills-put-in")).toBeVisible();
  await closeAdd(page);
  await mine(page).click();
}

test.describe("the skills you add", () => {
  test("are none at first, and the dialog that adds them says where they are kept", async ({ page }) => {
    await expect(mine(page)).toHaveText("Mine0");
    await mine(page).click();
    await expect(page.getByText("You have not added any skills of your own yet.")).toBeVisible();
    await expect(cards(page)).toHaveCount(0);

    await openAdd(page);

    await expect(addDialog(page).getByText("The skills you put in are kept in")).toBeVisible();
    await expect(addDialog(page).getByText("where other tools that use skills keep theirs")).toBeVisible();
    await expect(form(page).getByLabel("Put in skills from")).toBeVisible();
  });

  test("are put in from a folder, as copies, and shown with what each is for", async ({ page }) => {
    const where = write("mine", "dose-response", "Fits a dose-response curve.", { "scripts/fit.py": "print('fit')" });
    write("mine", "rna-seq", "Differential expression.");

    await putIn(page, where);

    await expect(addDialog(page).getByTestId("skills-put-in")).toContainText("Put in 2 skills.");
    // What was written is not left in the form
    await expect(form(page).getByLabel("Put in skills from")).toHaveValue("");
    await closeAdd(page);
    await expect(mine(page)).toHaveText("Mine2");
    await mine(page).click();
    await expect(card(page, "dose-response")).toContainText("Fits a dose-response curve.");
    await expect(card(page, "rna-seq")).toContainText("Differential expression.");
    await expect(count(page)).toHaveText(`2 of ${IN_THE_LIBRARY + 2} skills, 2 on`);
    const kept = await listed(page);
    expect(kept.skills.map((skill: { name: string }) => skill.name)).toEqual(["dose-response", "rna-seq"]);
    expect(fs.readFileSync(path.join(kept.folders[0].path, "dose-response", "scripts", "fit.py"), "utf8")).toBe("print('fit')");
    // They are copies: the folder they were put in from is as it was
    expect(fs.existsSync(path.join(where, "dose-response", "SKILL.md"))).toBe(true);
    await page.reload();
    await mine(page).click();
    await expect(card(page, "dose-response")).toBeVisible();
  });

  test("are asked about before they are fetched, and nothing is put in if the answer is no", async ({ page }) => {
    const where = write("mine", "dose-response", "Fits a curve.");
    await openAdd(page);
    await form(page).getByLabel("Put in skills from").fill(where);
    await form(page).getByRole("button", { name: "Put in the skills" }).click();

    const question = page.getByRole("alertdialog");
    await expect(question).toContainText("instructions that the lead follows");
    await question.getByRole("button", { name: "Cancel" }).click();

    await expect(question).toHaveCount(0);
    await expect(form(page).getByRole("button", { name: "Put in the skills" })).toBeFocused();
    expect((await listed(page)).skills).toEqual([]);
  });

  test("that are put in again are left, and which, and why, is said", async ({ page }) => {
    const where = write("mine", "dose-response", "Fits a curve.");
    await putIn(page, where);
    await expect(addDialog(page).getByTestId("skills-put-in")).toContainText("Put in 1 skill.");

    await putIn(page, where);

    const said = addDialog(page).getByTestId("skills-put-in");
    await expect(said).toContainText("Nothing new was put in: 1 left.");
    await said.getByText("Which were left, and why").click();
    await expect(page.getByRole("list", { name: "Skills that were left" })).toContainText("you already have a skill with that name");
    await closeAdd(page);
    await mine(page).click();
    await expect(cards(page)).toHaveCount(1);
  });

  test("that cannot be put in from where was written are refused with what is wrong", async ({ page }) => {
    await openAdd(page);
    const input = form(page).getByLabel("Put in skills from");
    const submit = form(page).getByRole("button", { name: "Put in the skills" });
    const sent: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/api/skills")) sent.push(request.url());
    });

    await submit.click();
    await expect(form(page).getByRole("alert")).toContainText("Give the address of a Git repository");
    await input.fill("http://example.org/skills.git");
    await expect(form(page).getByRole("alert")).toContainText("https://");
    await expect(input).toHaveAttribute("aria-invalid", "true");
    await submit.click();
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    expect(sent).toEqual([]);

    // What the server refuses is told as it says it
    await input.fill(path.join(scratch, "nothing-here"));
    await submit.click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Put them in" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "There is no folder at" })).toBeVisible();
  });

  test("that are in a repository that cannot be fetched are refused with what Git said", async ({ page }) => {
    await openAdd(page);
    await form(page).getByLabel("Put in skills from").fill("https://127.0.0.1:9/owner/skills.git");
    await form(page).getByRole("button", { name: "Put in the skills" }).click();
    const question = page.getByRole("alertdialog");
    await expect(question).toContainText("https://127.0.0.1:9/owner/skills.git");
    await question.getByRole("button", { name: "Put them in" }).click();

    await expect(page.getByRole("alert").filter({ hasText: "Git could not fetch https://127.0.0.1:9/owner/skills.git" })).toBeVisible();
    expect((await listed(page)).skills).toEqual([]);
  });

  test("from a folder with none in it are refused", async ({ page }) => {
    fs.mkdirSync(path.join(scratch, "empty"));

    await putIn(page, path.join(scratch, "empty"));

    await expect(page.getByRole("alert").filter({ hasText: "There is no skill in" })).toBeVisible();
  });
});

test.describe("a skill", () => {
  test("is turned off for new conversations, which is kept", async ({ page }) => {
    await putIn(page, write("mine", "dose-response", "Fits a curve."));
    write("mine", "rna-seq", "Differential expression.");
    await putInAndShow(page, path.join(scratch, "mine"));
    await expect(card(page, "rna-seq")).toBeVisible();

    await switchOf(page, "dose-response").click();

    await expect(switchOf(page, "dose-response")).toHaveAttribute("aria-checked", "false");
    await expect(count(page)).toHaveText(`2 of ${IN_THE_LIBRARY + 2} skills, 1 on`);
    await expect.poll(async () => (await listed(page)).skills.map((skill: { enabled: boolean }) => skill.enabled)).toEqual([false, true]);
    await page.reload();
    await mine(page).click();
    await expect(switchOf(page, "dose-response")).toHaveAttribute("aria-checked", "false");
    await expect(switchOf(page, "rna-seq")).toHaveAttribute("aria-checked", "true");

    // A conversation made now is not given it, and is given the other
    const chat = await (await page.request.post("/api/chats", { data: { team: [] } })).json();
    expect(chat.skills).toEqual(["rna-seq"]);
    await page.request.delete(`/api/chats/${chat.id}`);
  });

  test("may all be turned on or off at once, or those that were searched for", async ({ page }) => {
    for (const name of ["dose-response", "dose-escalation", "rna-seq"]) write("mine", name, `${name} description.`);
    await putInAndShow(page, path.join(scratch, "mine"));
    await expect(count(page)).toHaveText(`3 of ${IN_THE_LIBRARY + 3} skills, 3 on`);

    await search(page).fill("dose");
    await expect(cards(page)).toHaveCount(2);
    await page.getByRole("button", { name: "Turn these off" }).click();
    await expect(count(page)).toHaveText(`2 of ${IN_THE_LIBRARY + 3} skills, 0 on`);
    await expect(page.getByRole("button", { name: "Turn these off" })).toHaveCount(0);

    await search(page).fill("");
    await expect(count(page)).toHaveText(`3 of ${IN_THE_LIBRARY + 3} skills, 1 on`);
    await page.getByRole("button", { name: /^All/ }).click();
    await expect(count(page)).toHaveText(`${IN_THE_LIBRARY + 3} skills, 1 on`);
    await page.getByRole("button", { name: "Turn all on" }).click();
    await expect(count(page)).toHaveText(`${IN_THE_LIBRARY + 3} skills, 3 on`);
    await page.getByRole("button", { name: "Turn all off" }).click();
    await expect(count(page)).toHaveText(`${IN_THE_LIBRARY + 3} skills, 0 on`);
    expect((await listed(page)).skills.every((skill: { enabled: boolean }) => !skill.enabled)).toBe(true);
  });

  test("is searched for, and a search that finds none says so", async ({ page }) => {
    for (const name of ["dose-response", "rna-seq"]) write("mine", name, `${name} description.`);
    await putInAndShow(page, path.join(scratch, "mine"));

    await search(page).fill("RNA");
    await expect(cards(page)).toHaveCount(1);
    await expect(card(page, "rna-seq")).toBeVisible();
    await search(page).fill("proteomics");
    await expect(page.getByText("No skill matches those words.")).toBeVisible();
    await expect(cards(page)).toHaveCount(0);
  });

  test("is read before it is trusted: what it tells the lead, what it needs, and its files", async ({ page }) => {
    await putInAndShow(page, write("mine", "dose-response", "Fits a curve.", { "scripts/fit.py": "x", "references/guide.md": "y" }));

    await card(page, "dose-response").locator("button[aria-haspopup='dialog']").click();

    const skill = detail(page, "dose-response");
    await expect(skill.getByRole("region", { name: "What dose-response tells the lead" })).toContainText("Do it well.");
    await expect(skill).toContainText("Fits a curve.");
    await expect(skill).toContainText("License");
    await expect(skill).toContainText("MIT");
    await expect(skill.getByRole("list", { name: "Files of dose-response" })).toContainText("scripts/fit.py");
    await expect(skill.getByRole("list", { name: "Files of dose-response" })).toContainText("references/guide.md");
    await page.keyboard.press("Escape");
    await expect(skill).toHaveCount(0);
    await expect(card(page, "dose-response").locator("button[aria-haspopup='dialog']")).toBeFocused();
  });

  test("is turned on or off from where it is read", async ({ page }) => {
    await putInAndShow(page, write("mine", "dose-response", "Fits a curve."));
    await card(page, "dose-response").locator("button[aria-haspopup='dialog']").click();

    await detail(page, "dose-response").getByRole("switch", { name: "Give new conversations dose-response" }).click();

    await expect.poll(async () => (await listed(page)).skills[0].enabled).toBe(false);
    await expect(detail(page, "dose-response").getByRole("switch")).toHaveAttribute("aria-checked", "false");
  });

  test("is deleted after being asked about, with its folder", async ({ page }) => {
    await putIn(page, write("mine", "dose-response", "Fits a curve."));
    write("mine", "rna-seq", "Differential expression.");
    await putInAndShow(page, path.join(scratch, "mine"));
    const folder = (await listed(page)).folders[0].path;
    await expect(card(page, "rna-seq")).toBeVisible();

    await card(page, "dose-response").locator("button[aria-haspopup='dialog']").click();
    await detail(page, "dose-response").getByRole("button", { name: "Delete dose-response" }).click();
    const question = page.getByRole("alertdialog");
    await expect(question).toContainText("Delete dose-response?");
    await question.getByRole("button", { name: "Keep" }).click();
    await expect(detail(page, "dose-response")).toBeVisible();

    await detail(page, "dose-response").getByRole("button", { name: "Delete dose-response" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete", exact: true }).click();

    await expect(detail(page, "dose-response")).toHaveCount(0);
    await expect(card(page, "dose-response")).toHaveCount(0);
    await expect(page.getByRole("status").filter({ hasText: "Deleted dose-response." })).toBeVisible();
    expect(fs.existsSync(path.join(folder, "dose-response"))).toBe(false);
    expect(fs.existsSync(path.join(folder, "rna-seq", "SKILL.md"))).toBe(true);
    await expect(search(page)).toBeFocused();
  });

  test("of the person's own folder is shared with other tools, and cannot be deleted from here", async ({ page }) => {
    const own = (await listed(page)).folders[1].path;
    fs.mkdirSync(path.join(own, "shared-skill"), { recursive: true });
    fs.writeFileSync(path.join(own, "shared-skill", "SKILL.md"), "---\nname: shared-skill\ndescription: Kept for other tools too.\n---\nBody.\n");
    try {
      await page.reload();
      await mine(page).click();

      await card(page, "shared-skill").locator("button[aria-haspopup='dialog']").click();
      const skill = detail(page, "shared-skill");
      await expect(skill).toContainText("Your skills, which other tools read too");
      await expect(skill.getByRole("button", { name: "Delete shared-skill" })).toHaveCount(0);
      await skill.getByRole("switch").click();
      await expect.poll(async () => (await listed(page)).skills[0].enabled).toBe(false);
    } finally {
      fs.rmSync(path.join(own, "shared-skill"), { recursive: true, force: true });
    }
  });

  test("that cannot be used is listed with why, and the others are kept", async ({ page }) => {
    const folder = (await listed(page)).folders[0].path;
    fs.mkdirSync(path.join(folder, "broken"), { recursive: true });
    fs.writeFileSync(path.join(folder, "broken", "SKILL.md"), "No fields here.");
    await putInAndShow(page, write("mine", "dose-response", "Fits a curve."));

    const problems = page.getByTestId("skill-problems");
    await expect(problems).toContainText("1 SKILL.md file could not be used");
    await problems.getByText("could not be used").click();
    await expect(page.getByRole("list", { name: "Skills that could not be used" })).toContainText("broken");
    await expect(card(page, "dose-response")).toBeVisible();
  });
});

test.describe("the list of skills", () => {
  test("shows a few at a time when there are many", async ({ page }) => {
    for (let number = 0; number < 45; number++) write("many", `skill-${String(number).padStart(2, "0")}`, `Does thing ${number}.`);
    await putInAndShow(page, path.join(scratch, "many"));
    await expect(count(page)).toHaveText(`45 of ${IN_THE_LIBRARY + 45} skills, 45 on`);

    await expect(cards(page)).toHaveCount(36);
    await page.getByRole("button", { name: "Show more (9 left)" }).click();

    await expect(cards(page)).toHaveCount(45);
    await expect(page.getByRole("button", { name: /Show more/ })).toHaveCount(0);
  });

  test("is usable without a mouse or good eyes, and fits a narrow screen", async ({ page }) => {
    await putInAndShow(page, write("mine", "dose-response", "Fits a curve. ".repeat(40), { "scripts/fit.py": "x" }));
    await card(page, "dose-response").locator("button[aria-haspopup='dialog']").click();
    await expect(page.getByRole("region", { name: "What dose-response tells the lead" })).toBeVisible();

    expect(await accessibilityProblems(page)).toEqual([]);
    await page.setViewportSize({ width: 390, height: 800 });
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);
    await page.keyboard.press("Escape");

    await openAdd(page);
    // The dialog fades in, and is not looked at until it has
    await expect(addDialog(page)).toHaveCSS("opacity", "1");
    expect(await accessibilityProblems(page)).toEqual([]);
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);
  });
});
