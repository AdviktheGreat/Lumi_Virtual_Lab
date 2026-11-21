import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { expect, test } from "../fixtures";

// The bake-offs and the data that they are made of are the workspace's, so each test takes what it made away, and none is run
// beside another
test.describe.configure({ mode: "serial" });

const TASK = "Assign a cell type to each cell of my single-nucleus RNA-seq data.";
const OWN = ["cells.csv", "truth.csv", "notes.txt"];

async function clear(page: Page) {
  const { bakeoffs } = await (await page.request.get("/api/bakeoffs")).json();
  for (const bakeoff of bakeoffs) {
    await expect.poll(async () => (await page.request.delete(`/api/bakeoffs/${bakeoff.id}`)).status(), { timeout: 20_000 }).toBe(200);
  }
  for (const name of OWN) await page.request.delete(`/api/own/data/${name}`);
}

test.beforeEach(async ({ page }) => {
  await clear(page);
});

test.afterEach(async ({ page }) => {
  await clear(page);
});

// Puts a file on the Data page through the server, so that what a test is about is the page of the bake-offs
async function addData(page: Page, name: string, text: string) {
  const added = await page.request.post(`/api/own/data/files?name=${encodeURIComponent(name)}&description=${encodeURIComponent("For a bake-off")}`, {
    data: Buffer.from(text),
    headers: { "Content-Type": "application/octet-stream" },
  });
  expect(added.status()).toBe(201);
}

const CELLS = "cell,gene1,gene2\nc1,1,2\nc2,3,4\n";
const TRUTH = "cell,label\nc1,T\nc2,B\n";

// Makes a bake-off through the server, and gives back its id
async function makeBakeoff(page: Page, body: Record<string, unknown>): Promise<string> {
  const made = await page.request.post("/api/bakeoffs", { data: { task: TASK, limit: 2, ...body } });
  expect(made.status()).toBe(201);

  return (await made.json()).id;
}

async function viewOf(page: Page, id: string) {
  return (await page.request.get(`/api/bakeoffs/${id}`)).json();
}

async function openBakeoff(page: Page, id: string, title: string) {
  await page.goto(`/papers?bakeoff=${id}`);
  await expect(page.getByRole("heading", { name: title, level: 2 })).toBeVisible();
}

const bakeoffIn = (page: Page) => new URL(page.url()).searchParams.get("bakeoff") ?? "";
const making = (page: Page) => page.getByRole("form", { name: "Make a bake-off" });
const changing = (page: Page) => page.getByRole("form", { name: "Change the bake-off" });

test("the bake-offs are a part of the PaperAgents page, which says there are none yet", async ({ page }) => {
  await page.goto("/papers");
  const parts = page.getByRole("navigation", { name: "PaperAgents" });
  await expect(parts.getByRole("link", { name: "Bake-offs" })).not.toHaveAttribute("aria-current");

  await parts.getByRole("link", { name: "Bake-offs" }).click();
  await expect(page).toHaveURL(/\/papers\?view=bakeoffs$/);
  await expect(parts.getByRole("link", { name: "Bake-offs" })).toHaveAttribute("aria-current", "page");
  await expect(parts.getByRole("link", { name: "Agents" })).not.toHaveAttribute("aria-current");
  await expect(page.getByTestId("bakeoffs-empty")).toContainText("There are no bake-offs yet");
  await expect(making(page)).toBeVisible();
  await expect(page.getByTestId("paper-agents-empty")).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("asks for what is wrong with a bake-off to be put right before it is sent, then makes it and opens it", async ({ page }) => {
  await page.goto("/papers?view=bakeoffs");
  await making(page).getByRole("button", { name: "Make the bake-off" }).click();
  await expect(making(page).getByText("Say what you want done.")).toBeVisible();
  await expect(making(page).getByText(/Say the most it may spend/)).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);

  await making(page).getByLabel("What you want done", { exact: true }).fill(TASK);
  await making(page).getByLabel("Most it may spend, in dollars").fill("two");
  await making(page).getByRole("button", { name: "Make the bake-off" }).click();
  await expect(making(page).getByText(/is an amount in dollars/)).toBeVisible();
  expect((await (await page.request.get("/api/bakeoffs")).json()).bakeoffs).toEqual([]);

  await making(page).getByLabel("Most it may spend, in dollars").fill("$2");
  await making(page).getByRole("button", { name: "Make the bake-off" }).click();

  // With no title, it is called by the start of what it is for
  await expect(page).toHaveURL(/\/papers\?bakeoff=/);
  await expect(page.getByRole("heading", { name: TASK, level: 2 })).toBeVisible();
  const summary = page.getByTestId("bakeoff-summary");
  await expect(summary).toContainText(TASK);
  await expect(page.getByTestId("bakeoff-data")).toHaveText("Not said yet");
  await expect(page.getByTestId("bakeoff-described")).toContainText("Not said");
  await expect(page.getByTestId("bakeoff-labels")).toContainText("None, so the methods are compared with each other and are not ranked.");
  await expect(page.getByTestId("bakeoff-spending")).toContainText("$0.00 of $2.00 spent");
  await expect(page.getByTestId("bakeoff-spending")).toContainText("$2.00 is left of $2.00.");
  await expect(page.getByText("No methods yet")).toBeVisible();
  expect(await viewOf(page, bakeoffIn(page))).toMatchObject({ task: TASK, limit: 2, spent: 0, data: null, described: null, labels: null });
  expect(await accessibilityProblems(page)).toEqual([]);

  await page.getByRole("link", { name: "All bake-offs" }).click();
  await expect(page).toHaveURL(/\/papers\?view=bakeoffs$/);
  const row = page.getByTestId("bakeoff");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText(TASK);
  await expect(row).toContainText("No methods yet. $0.00 of $2.00 spent.");
  await expect(page.getByTestId("bakeoffs-empty")).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  await row.getByRole("link", { name: TASK }).click();
  await expect(page.getByRole("heading", { name: TASK, level: 2 })).toBeVisible();
});

test("makes a bake-off with the data it is run on, what that is, and where the right answers are, and shows them", async ({ page }) => {
  await addData(page, "cells.csv", CELLS);
  await addData(page, "truth.csv", TRUTH);
  await addData(page, "notes.txt", "not a table of answers");
  await page.goto("/papers?view=bakeoffs");
  const form = making(page);

  // A file that is not a table is not offered as the place of right answers, and a table is
  const answers = form.getByLabel("The file that has them");
  await expect(answers.getByRole("option", { name: /^notes\.txt/ })).toHaveCount(0);
  await expect(answers.getByRole("option", { name: /^truth\.csv/ })).toHaveCount(1);
  await expect(form.getByLabel("Your data", { exact: true }).getByRole("option", { name: /^notes\.txt/ })).toHaveCount(1);

  await form.getByLabel("What you want done", { exact: true }).fill(TASK);
  await form.getByLabel("Title", { exact: true }).fill("  Cell   types ");
  await form.getByLabel("Your data", { exact: true }).selectOption("cells.csv");
  await form.getByLabel("Species", { exact: true }).fill("human");
  await form.getByLabel("Sample size", { exact: true }).fill("5,000");
  await form.getByLabel("What the size counts").fill("cells");
  await form.getByLabel("Most it may spend, in dollars").fill("1.50");

  // A column of right answers is needed with the file, and one that is not in it is refused by the server
  await answers.selectOption("truth.csv");
  await form.getByRole("button", { name: "Make the bake-off" }).click();
  await expect(form.getByText("Say which column has the right answer for each row.")).toBeVisible();
  await form.getByLabel("Its column of answers").fill("nope");
  await form.getByRole("button", { name: "Make the bake-off" }).click();
  await expect(form.getByRole("alert").filter({ hasText: "There is no column called 'nope'" })).toBeVisible();
  expect((await (await page.request.get("/api/bakeoffs")).json()).bakeoffs).toEqual([]);
  expect(await accessibilityProblems(page)).toEqual([]);

  await form.getByLabel("Its column of answers").fill("label");
  await form.getByLabel("Its column of what each is the answer to").fill("cell");
  await form.getByRole("button", { name: "Make the bake-off" }).click();

  await expect(page.getByRole("heading", { name: "Cell types", level: 2 })).toBeVisible();
  await expect(page.getByTestId("bakeoff-data")).toContainText(/cells\.csv, \d+ B/);
  const described = page.getByTestId("bakeoff-described");
  await expect(described).toContainText("Species: human");
  await expect(described).toContainText("Sample size: 5,000 cells");
  // What was not said is not shown as said, though the bake-off keeps every part
  await expect(described.getByRole("listitem")).toHaveCount(2);
  await expect(described).not.toContainText("Tissue");
  const labels = page.getByTestId("bakeoff-labels");
  await expect(labels).toContainText('truth.csv, the answers in "label", with what each is the answer to in "cell"');
  await expect(labels).toContainText("The right answers are the person's word: nothing here checks them.");
  await expect(page.getByTestId("bakeoff-labels-problem")).toHaveCount(0);
  await expect(page.getByTestId("bakeoff-spending")).toContainText("$0.00 of $1.50 spent");
  expect(await viewOf(page, bakeoffIn(page))).toMatchObject({
    title: "Cell types",
    data: { own: "cells.csv" },
    described: { species: "human", sample_size: 5000, sample_unit: "cells" },
    labels: { own: "truth.csv", column: "label", id_column: "cell", ok: true },
    limit: 1.5,
  });
  expect(await accessibilityProblems(page)).toEqual([]);

  // The form for changing it shows what it is
  await expect(changing(page).getByLabel("Your data", { exact: true })).toHaveValue("cells.csv");
  await expect(changing(page).getByLabel("Species", { exact: true })).toHaveValue("human");
  await expect(changing(page).getByLabel("The file that has them")).toHaveValue("truth.csv");
  await expect(changing(page).getByLabel("Its column of answers")).toHaveValue("label");
  await expect(changing(page).getByLabel("Most it may spend, in dollars")).toHaveValue("1.5");
});

test("says again what a bake-off is, sending only what differs, and takes away what is said to be taken away", async ({ page }) => {
  await addData(page, "cells.csv", CELLS);
  await addData(page, "truth.csv", TRUTH);
  const id = await makeBakeoff(page, {
    title: "First name",
    data: "cells.csv",
    described: { species: "human" },
    labels: { own: "truth.csv", column: "label" },
  });
  await openBakeoff(page, id, "First name");
  const form = changing(page);
  const save = form.getByRole("button", { name: "Save the changes" });
  await expect(save).toBeDisabled();

  // Nothing is sent while what is typed is not fit
  await form.getByLabel("Title", { exact: true }).fill("   ");
  await form.getByLabel("Most it may spend, in dollars").fill("");
  await save.click();
  await expect(form.getByText("Say what it is called.")).toBeVisible();
  await expect(form.getByText(/Say the most it may spend/)).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  expect((await viewOf(page, id)).title).toBe("First name");

  await form.getByLabel("Title", { exact: true }).fill("Second name");
  await form.getByLabel("Most it may spend, in dollars").fill("3");
  const sent = page.waitForRequest((request) => request.method() === "PATCH" && request.url().endsWith(`/api/bakeoffs/${id}`));
  await save.click();
  expect((await sent).postDataJSON()).toEqual({ title: "Second name", limit: 3 });
  await expect(page.getByRole("heading", { name: "Second name", level: 2 })).toBeVisible();
  await expect(page.getByTestId("bakeoff-spending")).toContainText("$0.00 of $3.00 spent");
  await expect(save).toBeDisabled();
  expect(await viewOf(page, id)).toMatchObject({ title: "Second name", limit: 3, data: { own: "cells.csv" }, described: { species: "human" } });

  // The data, what it is, and the right answers are taken away by saying none of them
  await form.getByLabel("Your data", { exact: true }).selectOption("");
  await form.getByLabel("Species", { exact: true }).fill("");
  await form.getByLabel("The file that has them").selectOption("");
  await form.getByLabel("Its column of answers").fill("");
  const taken = page.waitForRequest((request) => request.method() === "PATCH" && request.url().endsWith(`/api/bakeoffs/${id}`));
  await save.click();
  expect((await taken).postDataJSON()).toEqual({ data: "", described: {}, labels: {} });
  await expect(page.getByTestId("bakeoff-data")).toHaveText("Not said yet");
  await expect(page.getByTestId("bakeoff-labels")).toContainText("None, so the methods are compared with each other");
  expect(await viewOf(page, id)).toMatchObject({ data: null, described: null, labels: null });
});

test("changes the title of a bake-off whose right answers are gone, and says that they cannot be used", async ({ page }) => {
  await addData(page, "cells.csv", CELLS);
  await addData(page, "truth.csv", TRUTH);
  const id = await makeBakeoff(page, { title: "Answers that go", data: "cells.csv", labels: { own: "truth.csv", column: "label" } });
  expect((await page.request.delete("/api/own/data/truth.csv")).ok()).toBe(true);
  await openBakeoff(page, id, "Answers that go");

  await expect(page.getByTestId("bakeoff-labels-problem")).toContainText("The methods are not scored by them until that is put right.");
  expect(await accessibilityProblems(page)).toEqual([]);

  // What was not changed is not said again, so what is gone does not stand in the way
  await changing(page).getByLabel("Title", { exact: true }).fill("Answers that went");
  await changing(page).getByRole("button", { name: "Save the changes" }).click();
  await expect(page.getByRole("heading", { name: "Answers that went", level: 2 })).toBeVisible();
  expect((await viewOf(page, id)).labels).toMatchObject({ own: "truth.csv", column: "label", ok: false });
});

test("deletes a bake-off, after asking", async ({ page }) => {
  const id = await makeBakeoff(page, { title: "Short lived" });
  await openBakeoff(page, id, "Short lived");

  await page.getByRole("button", { name: "Delete Short lived" }).click();
  const asking = page.getByRole("alertdialog", { name: "Delete Short lived?" });
  await expect(asking).toContainText("The PaperAgents that were made for its methods stay");
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  expect((await page.request.get(`/api/bakeoffs/${id}`)).status()).toBe(200);

  await page.getByRole("button", { name: "Delete Short lived" }).click();
  await page.getByRole("alertdialog", { name: "Delete Short lived?" }).getByRole("button", { name: "Delete", exact: true }).click();

  await expect(page).toHaveURL(/\/papers\?view=bakeoffs$/);
  await expect(page.getByTestId("bakeoffs-empty")).toBeVisible();
  expect((await page.request.get(`/api/bakeoffs/${id}`)).status()).toBe(404);
});

test("says that a bake-off is not there, rather than showing nothing", async ({ page }) => {
  await page.goto("/papers?bakeoff=nowhere");
  await expect(page.getByRole("alert").filter({ hasText: "The bake-off could not be looked at." })).toContainText("There is no bake-off");
  await page.getByRole("link", { name: "All bake-offs" }).click();
  await expect(page.getByTestId("bakeoffs-empty")).toBeVisible();
});

test("does not let a bake-off be changed or deleted while its methods are being found, built, or run", async ({ page }) => {
  const id = await makeBakeoff(page, { title: "Busy one" });
  const real = await viewOf(page, id);
  const job = {
    id: "job-1",
    kind: "bakeoff-run",
    subject: id,
    title: "Running the methods: Busy one",
    state: "running",
    message: "Running 1 of 2",
    progress: { finished: 1, total: 2 },
    error: null,
    created_at: real.created_at,
    finished_at: null,
    log_total: 0,
  };
  await page.route(`**/api/bakeoffs/${id}`, (route) => (route.request().method() === "GET" ? route.fulfill({ json: { ...real, job } }) : route.fallback()));
  await openBakeoff(page, id, "Busy one");

  await expect(page.getByTestId("bakeoff-job")).toContainText("Running the methods: Busy one");
  await expect(page.getByTestId("bakeoff-job")).toContainText("Running 1 of 2");
  await expect(page.getByRole("button", { name: "Delete Busy one" })).toBeDisabled();
  await expect(changing(page).getByRole("button", { name: "Save the changes" })).toBeDisabled();
  await expect(changing(page)).toContainText("It cannot be changed while its methods are being found, built, or run.");
  await expect(changing(page).getByLabel("Title", { exact: true })).not.toBeEditable();
  expect(await accessibilityProblems(page)).toEqual([]);
});
