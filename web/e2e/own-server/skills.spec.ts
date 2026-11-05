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

// Where the skills that are put in from are, which is on this machine, as it is where the server is
let scratch = "";

test.beforeEach(async ({ page }) => {
  await resetSkills(page);
  scratch = fs.mkdtempSync(path.join(os.tmpdir(), "vl-e2e-skills-"));
  await page.goto("/skills?tab=yours");
  await expect(page.getByRole("heading", { name: "Your skills", level: 2, exact: true })).toBeVisible();
});

test.afterEach(async ({ page }) => {
  fs.rmSync(scratch, { recursive: true, force: true });
  await resetSkills(page);
});

const form = (page: Page) => page.getByRole("form", { name: "Put in skills" });
const row = (page: Page, name: string) => page.getByTestId("skill").filter({ has: page.getByText(name, { exact: true }) });
const count = (page: Page) => page.getByTestId("skills-count");

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

// Puts in the skills of a folder, answering the question that asks whether to
async function putIn(page: Page, where: string) {
  await form(page).getByLabel("Put in skills from").fill(where);
  await form(page).getByRole("button", { name: "Put in the skills" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Put them in" }).click();
}

test.describe("the skills", () => {
  test("are none at first, and the page says where they are kept", async ({ page }) => {
    await expect(page.getByText("There are no skills yet.")).toBeVisible();
    await expect(page.getByRole("list", { name: "Skills", exact: true })).toHaveCount(0);
    await expect(page.getByText("The skills you put in here are kept in")).toBeVisible();
    await expect(page.getByText("where other tools that use skills keep theirs")).toBeVisible();
    await expect(form(page).getByLabel("Put in skills from")).toBeVisible();
  });

  test("are put in from a folder, as copies, and listed with what each is for", async ({ page }) => {
    const where = write("mine", "dose-response", "Fits a dose-response curve.", { "scripts/fit.py": "print('fit')" });
    write("mine", "rna-seq", "Differential expression.");

    await putIn(page, where);

    await expect(page.getByTestId("skills-put-in")).toContainText("Put in 2 skills.");
    await expect(row(page, "dose-response")).toContainText("Fits a dose-response curve.");
    await expect(row(page, "rna-seq")).toContainText("Differential expression.");
    await expect(count(page)).toHaveText("2 skills, all on");
    // What was written is not left in the form
    await expect(form(page).getByLabel("Put in skills from")).toHaveValue("");
    const kept = await listed(page);
    expect(kept.skills.map((skill: { name: string }) => skill.name)).toEqual(["dose-response", "rna-seq"]);
    expect(fs.readFileSync(path.join(kept.folders[0].path, "dose-response", "scripts", "fit.py"), "utf8")).toBe("print('fit')");
    // They are copies: the folder they were put in from is as it was
    expect(fs.existsSync(path.join(where, "dose-response", "SKILL.md"))).toBe(true);
    await page.reload();
    await expect(row(page, "dose-response")).toBeVisible();
  });

  test("are asked about before they are fetched, and nothing is put in if the answer is no", async ({ page }) => {
    const where = write("mine", "dose-response", "Fits a curve.");
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
    await expect(row(page, "dose-response")).toBeVisible();

    await putIn(page, where);

    const said = page.getByTestId("skills-put-in");
    await expect(said).toContainText("Nothing new was put in: 1 left.");
    await said.getByText("Which were left, and why").click();
    await expect(page.getByRole("list", { name: "Skills that were left" })).toContainText("you already have a skill with that name");
    await expect(page.getByTestId("skill")).toHaveCount(1);
  });

  test("that cannot be put in from where was written are refused with what is wrong", async ({ page }) => {
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
    await form(page).getByLabel("Put in skills from").fill("https://127.0.0.1:9/owner/skills.git");
    await form(page).getByRole("button", { name: "Put in the skills" }).click();
    const question = page.getByRole("alertdialog");
    await expect(question).toContainText("https://127.0.0.1:9/owner/skills.git");
    await question.getByRole("button", { name: "Put them in" }).click();

    await expect(page.getByRole("alert").filter({ hasText: "Git could not fetch https://127.0.0.1:9/owner/skills.git" })).toBeVisible();
    expect((await listed(page)).skills).toEqual([]);
  });

  test("a folder with none in it is refused", async ({ page }) => {
    fs.mkdirSync(path.join(scratch, "empty"));

    await putIn(page, path.join(scratch, "empty"));

    await expect(page.getByRole("alert").filter({ hasText: "There is no skill in" })).toBeVisible();
  });
});

test.describe("a skill", () => {
  test("is turned off for new conversations, which is kept", async ({ page }) => {
    await putIn(page, write("mine", "dose-response", "Fits a curve."));
    write("mine", "rna-seq", "Differential expression.");
    await putIn(page, path.join(scratch, "mine"));
    await expect(row(page, "rna-seq")).toBeVisible();

    await row(page, "dose-response").getByRole("checkbox", { name: "Give new conversations dose-response" }).uncheck();

    await expect(count(page)).toHaveText("2 skills, 1 on");
    await expect.poll(async () => (await listed(page)).skills.map((skill: { enabled: boolean }) => skill.enabled)).toEqual([false, true]);
    await page.reload();
    await expect(row(page, "dose-response").getByRole("checkbox")).not.toBeChecked();
    await expect(row(page, "rna-seq").getByRole("checkbox")).toBeChecked();

    // A conversation made now is not given it, and is given the other
    const chat = await (await page.request.post("/api/chats", { data: { team: [] } })).json();
    expect(chat.skills).toEqual(["rna-seq"]);
    await page.request.delete(`/api/chats/${chat.id}`);
  });

  test("may all be turned on or off at once, or those that were searched for", async ({ page }) => {
    for (const name of ["dose-response", "dose-escalation", "rna-seq"]) write("mine", name, `${name} description.`);
    await putIn(page, path.join(scratch, "mine"));
    await expect(count(page)).toHaveText("3 skills, all on");

    await page.getByRole("searchbox", { name: "Search the skills" }).fill("dose");
    await expect(page.getByTestId("skill")).toHaveCount(2);
    await page.getByRole("button", { name: "Turn these off" }).click();
    await expect(count(page)).toHaveText("3 skills, 1 on");
    await expect(page.getByRole("button", { name: "Turn these off" })).toHaveAttribute("aria-disabled", "true");

    await page.getByRole("searchbox", { name: "Search the skills" }).fill("");
    await page.getByRole("button", { name: "Turn all on" }).click();
    await expect(count(page)).toHaveText("3 skills, all on");
    await page.getByRole("button", { name: "Turn all off" }).click();
    await expect(count(page)).toHaveText("3 skills, none on");
    expect((await listed(page)).skills.every((skill: { enabled: boolean }) => !skill.enabled)).toBe(true);
  });

  test("is searched for, and a search that finds none says so", async ({ page }) => {
    for (const name of ["dose-response", "rna-seq"]) write("mine", name, `${name} description.`);
    await putIn(page, path.join(scratch, "mine"));
    const search = page.getByRole("searchbox", { name: "Search the skills" });

    await search.fill("RNA");
    await expect(page.getByTestId("skill")).toHaveCount(1);
    await expect(row(page, "rna-seq")).toBeVisible();
    await search.fill("proteomics");
    await expect(page.getByText("No skill has all of those words.")).toBeVisible();
    await expect(page.getByTestId("skill")).toHaveCount(0);
  });

  test("is read before it is trusted: what it tells the lead, what it needs, and its files", async ({ page }) => {
    await putIn(page, write("mine", "dose-response", "Fits a curve.", { "scripts/fit.py": "x", "references/guide.md": "y" }));
    const skill = row(page, "dose-response");

    await skill.getByRole("button", { name: "Read what dose-response tells the lead" }).click();

    await expect(skill.getByRole("region", { name: "What dose-response tells the lead" })).toContainText("Do it well.");
    await expect(skill).toContainText("License");
    await expect(skill).toContainText("MIT");
    await expect(skill.getByRole("list", { name: "Files of dose-response" })).toContainText("scripts/fit.py");
    await expect(skill.getByRole("list", { name: "Files of dose-response" })).toContainText("references/guide.md");
    await skill.getByRole("button", { name: "Hide what dose-response tells the lead" }).click();
    await expect(skill.getByRole("region")).toHaveCount(0);
  });

  test("is deleted after being asked about, with its folder", async ({ page }) => {
    await putIn(page, write("mine", "dose-response", "Fits a curve."));
    write("mine", "rna-seq", "Differential expression.");
    await putIn(page, path.join(scratch, "mine"));
    const folder = (await listed(page)).folders[0].path;
    await expect(row(page, "rna-seq")).toBeVisible();

    await row(page, "dose-response").getByRole("button", { name: "Delete dose-response" }).click();
    const question = page.getByRole("alertdialog");
    await expect(question).toContainText("Delete dose-response?");
    await question.getByRole("button", { name: "Keep" }).click();
    await expect(row(page, "dose-response")).toBeVisible();

    await row(page, "dose-response").getByRole("button", { name: "Delete dose-response" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete", exact: true }).click();

    await expect(row(page, "dose-response")).toHaveCount(0);
    await expect(page.getByRole("status").filter({ hasText: "Deleted dose-response." })).toBeVisible();
    expect(fs.existsSync(path.join(folder, "dose-response"))).toBe(false);
    expect(fs.existsSync(path.join(folder, "rna-seq", "SKILL.md"))).toBe(true);
    await expect(page.getByRole("searchbox", { name: "Search the skills" })).toBeFocused();
  });

  test("of the person's own folder is shared with other tools, and cannot be deleted from here", async ({ page }) => {
    const own = (await listed(page)).folders[1].path;
    fs.mkdirSync(path.join(own, "shared-skill"), { recursive: true });
    fs.writeFileSync(path.join(own, "shared-skill", "SKILL.md"), "---\nname: shared-skill\ndescription: Kept for other tools too.\n---\nBody.\n");
    try {
      await page.reload();

      const skill = row(page, "shared-skill");
      await expect(skill).toContainText("Shared with other tools");
      await expect(skill.getByRole("button", { name: "Delete shared-skill" })).toHaveCount(0);
      await skill.getByRole("checkbox").uncheck();
      await expect.poll(async () => (await listed(page)).skills[0].enabled).toBe(false);
    } finally {
      fs.rmSync(path.join(own, "shared-skill"), { recursive: true, force: true });
    }
  });

  test("that cannot be used is listed with why, and the others are kept", async ({ page }) => {
    const folder = (await listed(page)).folders[0].path;
    fs.mkdirSync(path.join(folder, "broken"), { recursive: true });
    fs.writeFileSync(path.join(folder, "broken", "SKILL.md"), "No fields here.");
    await putIn(page, write("mine", "dose-response", "Fits a curve."));

    const problems = page.getByTestId("skill-problems");
    await expect(problems).toContainText("1 SKILL.md file could not be used");
    await problems.getByText("could not be used").click();
    await expect(page.getByRole("list", { name: "Skills that could not be used" })).toContainText("broken");
    await expect(row(page, "dose-response")).toBeVisible();
  });
});

test.describe("the list of skills", () => {
  test("shows a few at a time when there are many", async ({ page }) => {
    for (let number = 0; number < 45; number++) write("many", `skill-${String(number).padStart(2, "0")}`, `Does thing ${number}.`);
    await putIn(page, path.join(scratch, "many"));
    await expect(count(page)).toHaveText("45 skills, all on");

    await expect(page.getByTestId("skill")).toHaveCount(40);
    await page.getByRole("button", { name: "Show more (5 left)" }).click();

    await expect(page.getByTestId("skill")).toHaveCount(45);
    await expect(page.getByRole("button", { name: /Show more/ })).toHaveCount(0);
  });

  test("is usable without a mouse or good eyes, and fits a narrow screen", async ({ page }) => {
    await putIn(page, write("mine", "dose-response", "Fits a curve. ".repeat(40), { "scripts/fit.py": "x" }));
    await row(page, "dose-response").getByRole("button", { name: "Read what dose-response tells the lead" }).click();
    await expect(page.getByRole("region", { name: "What dose-response tells the lead" })).toBeVisible();

    expect(await accessibilityProblems(page)).toEqual([]);
    await page.setViewportSize({ width: 390, height: 800 });
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);
  });
});
