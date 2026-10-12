import { expect, test } from "../fixtures";
import { openSettings, resetScientists } from "./state";

// The library is the server's, and these tests change it, so each puts it back and none is run beside another
test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await resetScientists(page);
  await page.reload();
});

const GENETICIST = {
  title: "Statistical Geneticist",
  expertise: "Population structure and association testing",
  goal: "Find the variants that explain a trait",
  role: "Plan and check the statistics of a study",
};

// Fills in the form for a scientist, which is open
async function write(dialog: import("@playwright/test").Locator, scientist: Partial<typeof GENETICIST>) {
  for (const [part, value] of Object.entries(scientist)) {
    await dialog.getByLabel(part[0].toUpperCase() + part.slice(1), { exact: true }).fill(value);
  }
}

const row = (dialog: import("@playwright/test").Locator, title: string) =>
  dialog.getByTestId("scientist").filter({ has: dialog.page().getByText(title, { exact: true }) });

test("the library is shown with the lab's own scientists, which cannot be deleted", async ({ page }) => {
  const dialog = await openSettings(page, "Scientists");

  const principal = row(dialog, "Principal Investigator");
  await expect(principal).toBeVisible();
  await expect(principal.getByText("Built in", { exact: true })).toBeVisible();
  await expect(principal.getByRole("button", { name: "Edit Principal Investigator" })).toBeVisible();
  await expect(principal.getByRole("button", { name: /^Delete/ })).toHaveCount(0);
  await expect(dialog.getByText("Yours", { exact: true })).toHaveCount(0);
});

test("a scientist is added, shown as the person's own, and kept by the server", async ({ page }) => {
  const dialog = await openSettings(page, "Scientists");

  await dialog.getByRole("button", { name: "Add a scientist" }).click();
  await write(dialog, GENETICIST);
  await dialog.getByRole("button", { name: "Save scientist" }).click();

  await expect(dialog.getByText("Saved Statistical Geneticist.")).toBeVisible();
  const added = row(dialog, GENETICIST.title);
  await expect(added.getByText("Yours", { exact: true })).toBeVisible();
  await expect(added).toContainText(GENETICIST.expertise);
  const kept = (await (await page.request.get("/api/scientists")).json()).scientists;
  expect(kept.find((scientist: { title: string }) => scientist.title === GENETICIST.title)).toMatchObject({
    ...GENETICIST,
    builtin: false,
  });
});

test("what is missing is said once it is tried to save, and nothing is sent until there is none", async ({ page }) => {
  const dialog = await openSettings(page, "Scientists");
  const sent: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "PUT") sent.push(request.url());
  });

  await dialog.getByRole("button", { name: "Add a scientist" }).click();
  // Nothing is said of a form that is only just open
  await expect(dialog.getByRole("alert")).toHaveCount(0);

  await write(dialog, { title: "Half Done", goal: "   " });
  await dialog.getByRole("button", { name: "Save scientist" }).click();

  await expect(dialog.getByRole("alert").filter({ hasText: "Expertise is needed." })).toBeVisible();
  await expect(dialog.getByRole("alert").filter({ hasText: "Goal is needed." })).toBeVisible();
  await expect(dialog.getByRole("alert").filter({ hasText: "Role is needed." })).toBeVisible();
  await expect(dialog.getByRole("alert").filter({ hasText: "Title is needed." })).toHaveCount(0);
  await expect(dialog.getByLabel("Goal", { exact: true })).toHaveAttribute("aria-invalid", "true");
  expect(sent).toEqual([]);

  await write(dialog, { expertise: "Something", goal: "Something else", role: "Something more" });
  await expect(dialog.getByRole("alert")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Save scientist" }).click();
  await expect(dialog.getByText("Saved Half Done.")).toBeVisible();
  expect(sent).toHaveLength(1);
});

test("a title that one has is not taken by someone new, in any case", async ({ page }) => {
  const dialog = await openSettings(page, "Scientists");

  await dialog.getByRole("button", { name: "Add a scientist" }).click();
  await write(dialog, { ...GENETICIST, title: "  principal   INVESTIGATOR " });
  await dialog.getByRole("button", { name: "Save scientist" }).click();

  await expect(dialog.getByRole("alert")).toContainText("There is a scientist with this title");
  await expect(dialog.getByRole("button", { name: "Save scientist" })).toBeVisible();
});

test("a scientist of the person's own is edited, and keeps its title", async ({ page }) => {
  expect((await page.request.put("/api/scientists", { data: GENETICIST })).ok()).toBe(true);
  const dialog = await openSettings(page, "Scientists");

  await dialog.getByRole("button", { name: `Edit ${GENETICIST.title}` }).click();
  await expect(dialog.getByLabel("Title", { exact: true })).toHaveValue(GENETICIST.title);
  await expect(dialog.getByLabel("Title", { exact: true })).toHaveJSProperty("readOnly", true);
  await expect(dialog.getByLabel("Goal", { exact: true })).toHaveValue(GENETICIST.goal);

  await write(dialog, { goal: "Find\nthe   causes of a trait" });
  await dialog.getByRole("button", { name: "Save scientist" }).click();

  await expect(dialog.getByText("Saved Statistical Geneticist.")).toBeVisible();
  const kept = (await (await page.request.get("/api/scientists")).json()).scientists;
  // The server keeps words with one space between them, and what is edited is what is kept
  expect(kept.filter((scientist: { title: string }) => scientist.title === GENETICIST.title)).toEqual([
    { ...GENETICIST, goal: "Find the causes of a trait", builtin: false },
  ]);
});

test("a scientist of the lab's own is edited into the person's own, and deleting it gives the lab's back", async ({ page }) => {
  const dialog = await openSettings(page, "Scientists");

  await dialog.getByRole("button", { name: "Edit Scientific Critic" }).click();
  await expect(dialog.getByText("Saving keeps your own version")).toBeVisible();
  await write(dialog, { expertise: "Finding flaws in the statistics of a study" });
  await dialog.getByRole("button", { name: "Save scientist" }).click();

  const mine = row(dialog, "Scientific Critic");
  await expect(mine.getByText("Yours", { exact: true })).toBeVisible();
  await expect(mine).toContainText("Finding flaws in the statistics of a study");
  await expect(dialog.getByTestId("scientist").filter({ hasText: "Scientific Critic" })).toHaveCount(1);

  await mine.getByRole("button", { name: "Delete Scientific Critic" }).click();
  await expect(page.getByRole("alertdialog")).toContainText("a built-in scientist with this title, theirs is used again");
  await page.getByRole("button", { name: "Delete", exact: true }).click();

  await expect(dialog.getByText("Deleted Scientific Critic.")).toBeVisible();
  // What was deleted can be neither focused nor sought, but the settings still have the focus
  await expect(dialog.getByRole("button", { name: "Delete Scientific Critic" })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Add a scientist" })).toBeFocused();
  const lab = row(dialog, "Scientific Critic");
  await expect(lab.getByText("Built in", { exact: true })).toBeVisible();
  await expect(lab).not.toContainText("Finding flaws in the statistics of a study");
});

test("a deletion is asked about, and is not made when it is not wanted", async ({ page }) => {
  expect((await page.request.put("/api/scientists", { data: GENETICIST })).ok()).toBe(true);
  const dialog = await openSettings(page, "Scientists");

  await dialog.getByRole("button", { name: `Delete ${GENETICIST.title}` }).click();
  await expect(page.getByRole("alertdialog")).toContainText(`Delete ${GENETICIST.title}?`);
  await page.getByRole("button", { name: "Keep", exact: true }).click();

  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(row(dialog, GENETICIST.title)).toBeVisible();
  // The focus is back on the button that asked
  await expect(dialog.getByRole("button", { name: `Delete ${GENETICIST.title}` })).toBeFocused();

  // Escape gives up the question, and not the settings behind it
  await dialog.getByRole("button", { name: `Delete ${GENETICIST.title}` }).click();
  // The question takes the focus when it is shown, and takes Escape for itself a moment after that: sent in that moment,
  // it would be taken by the settings behind it, which no one at a keyboard is quick enough to do
  await expect(page.getByRole("button", { name: "Keep", exact: true })).toBeFocused();
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
  await page.keyboard.press("Escape");
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(dialog).toBeVisible();
  await expect(row(dialog, GENETICIST.title)).toBeVisible();
  await expect(dialog.getByRole("button", { name: `Delete ${GENETICIST.title}` })).toBeFocused();
});

test("a scientist whose title has a slash in it is saved, edited, and deleted", async ({ page }) => {
  const dialog = await openSettings(page, "Scientists");
  const title = "Chemist / Physicist";

  await dialog.getByRole("button", { name: "Add a scientist" }).click();
  await write(dialog, { ...GENETICIST, title });
  await dialog.getByRole("button", { name: "Save scientist" }).click();
  await expect(row(dialog, title)).toBeVisible();

  await dialog.getByRole("button", { name: `Delete ${title}` }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();

  await expect(dialog.getByText(`Deleted ${title}.`)).toBeVisible();
  await expect(row(dialog, title)).toHaveCount(0);
});

test("what the server refuses is said, and what was written is kept", async ({ page }) => {
  const dialog = await openSettings(page, "Scientists");
  await page.route("**/api/scientists", (route) =>
    route.request().method() === "PUT"
      ? route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "invalid", message: "A scientist needs a goal" } }),
        })
      : route.continue(),
  );

  await dialog.getByRole("button", { name: "Add a scientist" }).click();
  await write(dialog, GENETICIST);
  await dialog.getByRole("button", { name: "Save scientist" }).click();

  await expect(dialog.getByRole("alert")).toHaveText("A scientist needs a goal");
  await expect(dialog.getByLabel("Role", { exact: true })).toHaveValue(GENETICIST.role);

  await page.unroute("**/api/scientists");
  await dialog.getByRole("button", { name: "Save scientist" }).click();
  await expect(dialog.getByText("Saved Statistical Geneticist.")).toBeVisible();
});

test("a scientist who is being written is kept on moving to another part of the settings, and asked about on closing", async ({ page }) => {
  const dialog = await openSettings(page, "Scientists");

  await dialog.getByRole("button", { name: "Add a scientist" }).click();
  await write(dialog, { title: "Half Written" });
  await dialog.getByRole("tab", { name: "Keys" }).click();
  await dialog.getByRole("tab", { name: "Scientists" }).click();
  await expect(dialog.getByLabel("Title", { exact: true })).toHaveValue("Half Written");

  await page.keyboard.press("Escape");
  await expect(dialog.getByText("What you changed is not saved.")).toBeVisible();
  await dialog.getByRole("button", { name: "Keep editing" }).click();

  // Giving the scientist up is not losing anything that was written, since there is nothing in the form
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog.getByRole("button", { name: "Add a scientist" })).toBeVisible();
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await expect(dialog).toHaveCount(0);

  const again = await openSettings(page, "Scientists");
  await again.getByRole("button", { name: "Add a scientist" }).click();
  await expect(again.getByLabel("Title", { exact: true })).toHaveValue("");
});

test("a scientist who is edited and changed back is not asked about on closing", async ({ page }) => {
  const dialog = await openSettings(page, "Scientists");

  await dialog.getByRole("button", { name: "Edit Immunologist" }).click();
  const expertise = dialog.getByLabel("Expertise", { exact: true });
  const was = await expertise.inputValue();
  await expertise.fill("Something else");
  await expertise.fill(was);
  await page.keyboard.press("Escape");

  await expect(dialog).toHaveCount(0);
});
