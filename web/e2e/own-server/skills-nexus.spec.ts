import type { Page } from "@playwright/test";
import { accessibilityProblems, pastTheEdge } from "../axe";
import { expect, test } from "../fixtures";
import { resetSkills } from "./state";

// The skills put in are the workspace's, and every conversation made after is given those that are on, so each test takes
// them away again, and none is run beside another. The library they are put in from is the server's own, with five
// skills in it that are named here, and forty-five more of the same that make more than a page shows (see
// write_skill_library in e2e/scripted_server.py).
test.describe.configure({ mode: "serial" });

const IN_THE_LIBRARY = 50;

test.beforeEach(async ({ page }) => {
  await resetSkills(page);
  await page.goto("/skills");
  await expect(page.getByTestId("library-count")).toHaveText(`${IN_THE_LIBRARY} skills`);
});

test.afterEach(async ({ page }) => {
  await resetSkills(page);
});

const row = (page: Page, name: string) => page.getByTestId("library-skill").filter({ has: page.getByText(name, { exact: true }) });
const count = (page: Page) => page.getByTestId("library-count");
const choose = (page: Page, name: string) => row(page, name).getByRole("checkbox", { name: `Choose ${name} to put in` }).check();
const putInButton = (page: Page) => page.getByRole("button", { name: /^Put in( \d+)?$/ });
const category = (page: Page) => page.getByRole("combobox", { name: "Category" });
const dialog = (page: Page) => page.getByRole("alertdialog");

async function kept(page: Page) {
  return (await page.request.get("/api/skills")).json();
}

test.describe("the Skills Nexus", () => {
  test("is reached from the rail, and opens on the skills that come with the lab", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Skills" }).click();

    await expect(page).toHaveURL(/\/skills$/);
    await expect(page.getByRole("heading", { name: "Skills Nexus", level: 1 })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Discover" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("tab", { name: "Your skills (0)" })).toBeVisible();
    await expect(page.getByTestId("library-source")).toHaveText(
      "50 skills by The Tests in Test Skills, version 1.2.3, under the MIT License and, where a skill says so, its own. 0 in your skills.",
    );
    await expect(page.getByRole("link", { name: "Test Skills" })).toHaveAttribute("href", "https://example.com/test-skills");
  });

  test("lists each skill with its category and license, and stands out for a license that limits its use", async ({ page }) => {
    await expect(row(page, "dose-curves").getByText("MIT", { exact: true })).toBeVisible();
    await expect(row(page, "dose-curves").getByText("Statistics", { exact: true })).toBeVisible();
    await expect(row(page, "rna-counts").getByText("Apache-2.0", { exact: true })).toBeVisible();
    await expect(row(page, "cell-types").getByText("No license stated", { exact: true })).toBeVisible();
    await expect(row(page, "pathway-flux").getByText("GPL-3.0-or-later", { exact: true })).toBeVisible();
    await expect(row(page, "spatial-guess").getByText("PolyForm-Noncommercial-1.0.0", { exact: true })).toHaveAttribute(
      "data-variant",
      "destructive",
    );
  });

  test("is read before it is put in: what it tells the lead, its files, and what its license means", async ({ page }) => {
    await row(page, "spatial-guess").getByRole("button", { name: "Read what spatial-guess tells the lead" }).click();

    await expect(row(page, "spatial-guess").getByText("Follow the spatial-guess steps.")).toBeVisible();
    await expect(row(page, "spatial-guess").getByText("Its license allows noncommercial use only.")).toBeVisible();
    await expect(row(page, "spatial-guess").getByText("1 file, 100 bytes")).toBeVisible();

    await row(page, "rna-counts").getByRole("button", { name: "Read what rna-counts tells the lead" }).click();
    await expect(row(page, "rna-counts").getByRole("list", { name: "Files of rna-counts" }).getByText("scripts/count.py")).toBeVisible();
    await row(page, "rna-counts").getByRole("button", { name: "Hide what rna-counts tells the lead" }).click();
    await expect(row(page, "rna-counts").getByText("Follow the rna-counts steps.")).toHaveCount(0);
  });

  test("is found by words and by category, and a search that finds none says so", async ({ page }) => {
    await page.getByRole("searchbox", { name: "Search the library" }).fill("CELL types");
    await expect(count(page)).toHaveText(`1 of ${IN_THE_LIBRARY} skills`);
    await expect(page.getByTestId("library-skill")).toHaveCount(1);

    await page.getByRole("searchbox", { name: "Search the library" }).fill("");
    await category(page).selectOption({ label: "Genomics (2)" });
    await expect(count(page)).toHaveText(`2 of ${IN_THE_LIBRARY} skills`);
    await expect(page.getByTestId("library-skill")).toHaveCount(2);

    await page.getByRole("searchbox", { name: "Search the library" }).fill("dose");
    await expect(page.getByRole("status").filter({ hasText: "No skill has all of those words in that category." })).toBeVisible();
  });

  test("is shown a few at a time", async ({ page }) => {
    await expect(page.getByTestId("library-skill")).toHaveCount(40);

    await page.getByRole("button", { name: "Show more (10 left)" }).click();

    await expect(page.getByTestId("library-skill")).toHaveCount(IN_THE_LIBRARY);
    await expect(page.getByRole("button", { name: /Show more/ })).toHaveCount(0);
  });

  test("is put in after a question that says what it costs and what the licenses are, and is then on", async ({ page }) => {
    await expect(putInButton(page)).toHaveAttribute("aria-disabled", "true");
    for (const name of ["dose-curves", "cell-types", "pathway-flux", "spatial-guess"]) await choose(page, name);
    await expect(count(page)).toHaveText(`${IN_THE_LIBRARY} skills, 4 chosen`);

    await putInButton(page).click();
    await expect(dialog(page).getByRole("heading", { name: "Put in 4 skills?" })).toBeVisible();
    await expect(dialog(page).getByText(/Together they add about \d+ tokens to the start of every conversation/)).toBeVisible();
    const about = dialog(page).getByRole("list", { name: "About their licenses" });
    await expect(about.getByRole("listitem")).toHaveText([
      "spatial-guess allows noncommercial use only.",
      "pathway-flux is under a GPL license, which sets conditions on sharing it.",
      "cell-types states no license, so only the library's MIT license covers it.",
    ]);

    await dialog(page).getByRole("button", { name: "Cancel" }).click();
    expect((await kept(page)).skills).toEqual([]);

    await putInButton(page).click();
    await dialog(page).getByRole("button", { name: "Put them in" }).click();

    await expect(page.getByTestId("skills-put-in")).toHaveText("Put in 4 skills.");
    await expect(count(page)).toHaveText(`${IN_THE_LIBRARY} skills`);
    await expect(row(page, "dose-curves").getByText("In your skills", { exact: true })).toBeVisible();
    await expect(row(page, "dose-curves").getByRole("checkbox")).toHaveCount(0);
    await expect(row(page, "rna-counts").getByRole("checkbox", { name: "Choose rna-counts to put in" })).toBeVisible();
    await expect(page.getByTestId("library-source")).toContainText("4 in your skills.");
    await expect(page.getByRole("tab", { name: "Your skills (4)" })).toBeVisible();
    const listed = await kept(page);
    expect(listed.skills.map((skill: { name: string }) => skill.name).sort()).toEqual(["cell-types", "dose-curves", "pathway-flux", "spatial-guess"]);
    expect(listed.skills.every((skill: { enabled: boolean; source: string }) => skill.enabled && skill.source === "workspace")).toBe(true);
    const chat = await (await page.request.post("/api/chats", { data: { team: [] } })).json();
    expect([...chat.skills].sort()).toEqual(["cell-types", "dose-curves", "pathway-flux", "spatial-guess"]);
    await page.request.delete(`/api/chats/${chat.id}`);

    await page.getByRole("button", { name: "See them in your skills" }).click();
    await expect(page.getByRole("heading", { name: "Your skills", level: 2, exact: true })).toBeVisible();
    await expect(page.getByTestId("skills-count")).toHaveText("4 skills, all on");
    await expect(page.getByTestId("skills-meter")).toContainText("The 4 skills that are on take about");
  });

  test("is chosen as a whole, for what was found, and the choice is cleared", async ({ page }) => {
    await page.getByRole("searchbox", { name: "Search the library" }).fill("filler");
    await page.getByRole("button", { name: "Choose these" }).click();
    await expect(count(page)).toHaveText(`45 of ${IN_THE_LIBRARY} skills, 45 chosen`);
    await expect(page.getByRole("button", { name: "Choose these" })).toHaveAttribute("aria-disabled", "true");

    await page.getByRole("button", { name: "Clear" }).click();
    await expect(count(page)).toHaveText(`45 of ${IN_THE_LIBRARY} skills`);

    await page.getByRole("button", { name: "Choose these" }).click();
    await putInButton(page).click();
    await expect(dialog(page).getByRole("heading", { name: "Put in 45 skills?" })).toBeVisible();
    await expect(dialog(page).getByRole("list", { name: "About their licenses" })).toHaveCount(0);
    await dialog(page).getByRole("button", { name: "Put them in" }).click();

    await expect(page.getByTestId("skills-put-in")).toHaveText("Put in 45 skills.");
    expect((await kept(page)).skills).toHaveLength(45);
    await expect(page.getByRole("button", { name: "Choose these" })).toHaveAttribute("aria-disabled", "true");
  });

  test("keeps what was chosen while the search changes, and does not offer what is in already", async ({ page }) => {
    await choose(page, "dose-curves");
    await page.getByRole("searchbox", { name: "Search the library" }).fill("rna");
    await choose(page, "rna-counts");
    await expect(count(page)).toHaveText(`1 of ${IN_THE_LIBRARY} skills, 2 chosen`);

    await putInButton(page).click();
    await expect(dialog(page).getByRole("heading", { name: "Put in 2 skills?" })).toBeVisible();
    await dialog(page).getByRole("button", { name: "Put them in" }).click();
    await expect(page.getByTestId("skills-put-in")).toHaveText("Put in 2 skills.");

    // Putting in again what is in already is not offered, and a skill put in by another route is left, and said so
    const again = await page.request.post("/api/skill-library/install", { data: { names: ["dose-curves", "cell-types"] } });
    expect((await again.json()).skipped).toEqual([{ name: "dose-curves", reason: "you already have a skill with that name" }]);
  });

  test("is offered again once it is deleted from your skills", async ({ page }) => {
    expect((await page.request.post("/api/skill-library/install", { data: { names: ["dose-curves", "rna-counts"] } })).ok()).toBe(true);
    await page.reload();
    await expect(row(page, "dose-curves").getByText("In your skills", { exact: true })).toBeVisible();

    await page.getByRole("tab", { name: "Your skills (2)" }).click();
    await page.getByRole("button", { name: "Delete dose-curves" }).click();
    await dialog(page).getByRole("button", { name: "Delete", exact: true }).click();
    await expect(page.getByText("Deleted dose-curves.")).toBeVisible();

    await page.getByRole("tab", { name: "Discover" }).click();
    await expect(row(page, "dose-curves").getByRole("checkbox", { name: "Choose dose-curves to put in" })).toBeVisible();
    await expect(row(page, "dose-curves").getByText("In your skills", { exact: true })).toHaveCount(0);
    await expect(row(page, "rna-counts").getByText("In your skills", { exact: true })).toBeVisible();
  });

  test("opens on your skills where the address says to, which are put in and kept as before", async ({ page }) => {
    await page.goto("/skills?tab=yours");

    await expect(page.getByRole("tab", { name: /^Your skills/ })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("heading", { name: "Your skills", level: 2, exact: true })).toBeVisible();
    await expect(page.getByText("There are no skills yet.")).toBeVisible();
    await expect(page.getByRole("form", { name: "Put in skills" })).toBeVisible();
  });

  test("is no longer on the Data page, whose other parts are as they were", async ({ page }) => {
    await page.goto("/data");

    await expect(page.getByRole("heading", { name: "Your data", level: 2 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Skills", level: 2 })).toHaveCount(0);
    await expect(page.getByRole("form", { name: "Put in skills" })).toHaveCount(0);
  });

  test("has nothing wrong that axe can find, and fits a narrow screen", async ({ page }) => {
    await row(page, "pathway-flux").getByRole("button", { name: "Read what pathway-flux tells the lead" }).click();
    await expect(row(page, "pathway-flux").getByText("Follow the pathway-flux steps.")).toBeVisible();
    await choose(page, "dose-curves");
    // The button fades in once there is something to put in, and is not looked at until it has
    await expect(putInButton(page)).toHaveCSS("opacity", "1");
    expect(await accessibilityProblems(page)).toEqual([]);

    await putInButton(page).click();
    await expect(dialog(page).getByRole("heading", { name: "Put in 1 skill?" })).toBeVisible();
    expect(await accessibilityProblems(page)).toEqual([]);
    await dialog(page).getByRole("button", { name: "Cancel" }).click();

    await page.setViewportSize({ width: 360, height: 700 });
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);
  });
});
