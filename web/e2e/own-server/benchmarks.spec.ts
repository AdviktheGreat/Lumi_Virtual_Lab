import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { expect, test } from "../fixtures";

// The runs are the workspace's, so each test takes what it made away, and none is run beside another. The first fetches
// the files of the benchmarks, which are small stand-ins here, and the rest find them fetched.
test.describe.configure({ mode: "serial" });

interface Entry {
  id: string;
  job: string | null;
}

// Takes away every run, stopping what is at work on one first
async function clear(page: Page) {
  const { runs } = (await (await page.request.get("/api/benchmarks")).json()) as { runs: Entry[] };
  for (const run of runs) {
    if (run.job) await page.request.post(`/api/setup/jobs/${run.job}/stop`);
    await expect
      .poll(async () => (await page.request.delete(`/api/benchmarks/runs/${run.id}`)).status(), { timeout: 20_000 })
      .toBe(200);
  }
}

test.beforeEach(async ({ page }) => {
  await clear(page);
});

test.afterEach(async ({ page }) => {
  await clear(page);
});

// Makes a run through the server, so that what a test is about is the page
async function arrange(page: Page, body: Record<string, unknown>): Promise<string> {
  expect((await page.request.post("/api/benchmarks/files")).status()).toBe(200);
  const made = await page.request.post("/api/benchmarks/runs", { data: body });
  expect(made.status()).toBe(201);

  return (await made.json()).id;
}

// Answers the questions of a run through the server, and waits until that is done
async function answerThrough(page: Page, id: string) {
  const started = await page.request.post(`/api/benchmarks/runs/${id}/start`, { data: { max_cost: 5 } });
  expect(started.status()).toBe(202);
  await expect
    .poll(async () => (await (await page.request.get(`/api/benchmarks/runs/${id}`)).json()).job, { timeout: 30_000 })
    .toBeNull();
}

async function openRun(page: Page, id: string, title: string) {
  await page.goto(`/benchmarks?id=${id}`);
  await expect(page.getByRole("heading", { name: title, level: 2 })).toBeVisible();
}

const form = (page: Page, name: string) => page.getByRole("form", { name });
const questions = (page: Page) => page.getByRole("table", { name: "Questions" }).getByTestId("benchmark-question");

test("fetches the files, makes a run of LAB-Bench's questions, and answers it with a budget", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Benchmarks", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Benchmarks", level: 1 })).toBeVisible();
  await expect(page.getByText("No run has answered a benchmark yet.")).toBeVisible();

  // A run cannot be made before the questions are there
  const make = form(page, "Make a run");
  await expect(make.getByRole("button", { name: "Make the run" })).toBeDisabled();
  await page.getByRole("button", { name: "Fetch the files" }).click();
  await expect(page.getByRole("region", { name: "The benchmarks' files" })).toContainText("The files of the benchmarks are in");
  await expect(make.getByRole("button", { name: "Make the run" })).toBeEnabled();

  await make.getByLabel("Title").fill("DbQA trial");
  await make.getByRole("radio", { name: /LAB-Bench: DbQA/ }).check();
  await expect(make.getByLabel("Which questions")).toHaveValue("test");
  await expect(make.getByLabel("Which questions").locator("option:checked")).toHaveText("The test questions (5 questions)");
  await make.getByRole("button", { name: "Make the run" }).click();

  await expect(page.getByRole("heading", { name: "DbQA trial", level: 2 })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("id")).toBe("dbqa-trial");
  await expect(page.getByText("5 questions, none answered yet")).toBeVisible();
  await expect(page.getByText("Nothing is scored until some questions have been answered.")).toBeVisible();

  await form(page, "Answer the questions").getByLabel("Most it may spend, in dollars").fill("2");
  await form(page, "Answer the questions").getByRole("button", { name: "Answer the questions" }).click();

  const status = page.getByRole("region", { name: "What is being done" });
  await expect(status.getByText("5 of 5 questions", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(status.getByText("Done", { exact: true })).toBeVisible();

  // The stand-in model is right about the questions with an even number, and wrong about the others
  await expect(page.getByTestId("benchmark-measure-accuracy")).toContainText("60.0%");
  await expect(page.getByTestId("benchmark-measure-coverage")).toBeVisible();
  await expect(questions(page)).toHaveCount(5);
  await page.getByLabel("How it was answered").selectOption("wrong");
  await expect(questions(page)).toHaveCount(2);
  await page.getByLabel("How it was answered").selectOption("all");

  await page.getByRole("button", { name: "Show question lab_bench_dbqa/0" }).click();
  await expect(page.getByLabel("What was asked", { exact: true })).toContainText("Question 0?");
  await expect(page.getByText("The right answer:")).toBeVisible();
  await expect(page.getByRole("list", { name: "What was said in answering it" })).toContainText("[ANSWER]");
  await page.getByRole("button", { name: "Hide question lab_bench_dbqa/0" }).click();
  await expect(page.getByLabel("What was asked", { exact: true })).toHaveCount(0);

  await page.getByRole("link", { name: "All runs" }).click();
  await expect(page.getByTestId("benchmark-run")).toContainText("Answered 5 of 5 questions · 60.0% right");
});

test("scores each task of Biomni-Eval1, and can be narrowed to the questions that were wrong", async ({ page }) => {
  const id = await arrange(page, { title: "Eval one", benchmark: "biomni_eval1", solver: "single" });
  await answerThrough(page, id);
  await openRun(page, id, "Eval one");

  const tasks = page.getByRole("table", { name: "Tasks" });
  await expect(tasks.getByTestId("benchmark-task")).toHaveCount(5);
  await expect(tasks.getByRole("row", { name: /crispr_delivery\s+2 of 2\s+50\.0%$/ })).toBeVisible();
  await expect(tasks.getByRole("row", { name: /gwas_causal_gene_opentargets\s+1 of 1\s+100\.0%$/ })).toBeVisible();
  await expect(page.getByTestId("benchmark-measure-accuracy")).toBeVisible();

  await page.getByLabel("Task", { exact: true }).selectOption("crispr_delivery");
  await expect(questions(page)).toHaveCount(2);
  await page.getByLabel("How it was answered").selectOption("wrong");
  await expect(questions(page)).toHaveCount(1);
  await expect(questions(page).first()).toContainText("crispr_delivery · 1");
  await page.getByLabel("How it was answered").selectOption("failed");
  await expect(page.getByText("No question was answered like that.")).toBeVisible();
});

test("follows the answering while it goes on, stops it, and carries on from where it stopped", async ({ page }) => {
  const id = await arrange(page, { title: "Slow exam", benchmark: "hle", solver: "single", leave_out_images: true });
  await openRun(page, id, "Slow exam");
  await expect(page.getByText("Without the questions that refer to an image")).toBeVisible();
  await expect(page.getByText("3 questions, none answered yet")).toBeVisible();

  await form(page, "Answer the questions").getByRole("button", { name: "Answer the questions" }).click();

  const status = page.getByRole("region", { name: "What is being done" });
  await expect(status.getByRole("progressbar", { name: "Progress: Answering Slow exam" })).toBeVisible();
  await expect(status.getByText("0 of 3 questions", { exact: true })).toBeVisible();
  // Nothing else is done to a run while it is being answered
  await expect(form(page, "Answer the questions").getByRole("button", { name: "Answer the questions" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Delete Slow exam" })).toBeDisabled();

  // A question that is stopped in the middle of is not kept, so it is what comes after the first that is stopped
  await expect(status.getByText("1 of 3 questions", { exact: true })).toBeVisible({ timeout: 10_000 });
  await status.getByRole("button", { name: "Stop: Answering Slow exam" }).click();
  await expect(status.getByRole("button", { name: "Stopping: Answering Slow exam" })).toBeDisabled();

  await expect(status.getByRole("progressbar")).toHaveCount(0, { timeout: 15_000 });
  await expect(status.getByText("Stopped", { exact: true })).toBeVisible();
  // What was answered is kept, and the rest is left for the next time
  await expect(questions(page).filter({ hasText: "Not answered" }).first()).toBeVisible();
  const carry = form(page, "Answer the questions").getByRole("button", { name: "Carry on answering" });
  await expect(carry).toBeEnabled();

  await carry.click();
  await expect(status.getByText("3 of 3 questions", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(status.getByText("Done", { exact: true })).toBeVisible();
  // The stand-in model says B, which is right for two of the three
  await expect(page.getByTestId("benchmark-measure-accuracy")).toContainText("66.7%");
  await expect(form(page, "Answer the questions").getByRole("button", { name: "Carry on answering" })).toBeDisabled();
  await expect(form(page, "Answer the questions")).toContainText("Every question has been answered.");
});

test("asks for what is wrong with a run, and what it may spend, to be put right before it is sent, and keeps who answers", async ({ page }) => {
  await arrange(page, { title: "Placeholder", benchmark: "hle" });
  await page.goto("/benchmarks");
  const make = form(page, "Make a run");

  await make.getByRole("button", { name: "Make the run" }).click();
  await expect(make.getByRole("alert")).toHaveText("Give the run a title.");
  await make.getByLabel("Title").fill("Team run");
  await make.getByRole("radio", { name: /The lead and the team/ }).check();
  await make.getByLabel("Rounds of discussion").fill("9");
  await make.getByLabel("How many questions").fill("0");
  await make.getByRole("button", { name: "Make the run" }).click();
  await expect(make.getByRole("alert")).toHaveCount(2);
  await expect(make).toContainText("The number of rounds is a whole number from 0 to 5.");
  await expect(make).toContainText("The number of questions is a whole number from 1 to");
  await make.getByLabel("Rounds of discussion").fill("2");
  await make.getByLabel("How many questions").fill("3");
  const tasks = ["crispr_delivery", "gwas_causal_gene_opentargets", "gwas_variant_prioritization", "rare_disease_diagnosis", "patient_gene_detection"];
  for (const task of tasks) await make.getByRole("checkbox", { name: new RegExp(`^${task}`) }).uncheck();
  await make.getByRole("button", { name: "Make the run" }).click();
  await expect(make.getByRole("alert")).toHaveText("Choose at least one task.");
  await make.getByRole("checkbox", { name: /^patient_gene_detection/ }).check();
  await make.getByRole("button", { name: "Make the run" }).click();

  await expect(page.getByRole("heading", { name: "Team run", level: 2 })).toBeVisible();
  await expect(page.getByText("Only 1 task: patient_gene_detection · The first 3 questions")).toBeVisible();
  await expect(page.getByText("The lead and the team with gpt-5.2, 2 rounds of discussion")).toBeVisible();
  await expect(page.getByText(/^Led by Principal Investigator, with /)).toBeVisible();
  await expect(page.getByText("No code is run")).toBeVisible();

  const start = form(page, "Answer the questions");
  await start.getByLabel("Most it may spend, in dollars").fill("lots");
  await start.getByRole("button", { name: "Answer the questions" }).click();
  await expect(start.getByRole("alert")).toHaveText("The most it may spend is an amount in dollars, such as 1 or 0.50.");
  const { jobs } = await (await page.request.get("/api/setup/jobs")).json();
  expect(jobs.filter((job: { subject: string }) => job.subject === "team-run")).toEqual([]);

  await page.route("**/api/benchmarks/runs/*/start", (route) =>
    route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "missing_keys", message: "gpt-5.2 needs OPENAI_API_KEY, which is not set. Add it in the settings.", missing: ["OPENAI_API_KEY"] },
      }),
    }),
  );
  await start.getByLabel("Most it may spend, in dollars").fill("1");
  await start.getByRole("button", { name: "Answer the questions" }).click();
  const problem = start.getByRole("alert");
  await expect(problem).toContainText("gpt-5.2 needs OPENAI_API_KEY");
  await expect(problem.getByRole("button", { name: "Add the key" })).toBeVisible();
});

test("deletes a run, after asking", async ({ page }) => {
  const id = await arrange(page, { title: "Short lived", benchmark: "lab_bench_seqqa", limit: 2 });
  await openRun(page, id, "Short lived");

  await page.getByRole("button", { name: "Delete Short lived" }).click();
  const asking = page.getByRole("alertdialog", { name: "Delete Short lived?" });
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  expect((await page.request.get(`/api/benchmarks/runs/${id}`)).status()).toBe(200);

  await page.getByRole("button", { name: "Delete Short lived" }).click();
  await page.getByRole("alertdialog", { name: "Delete Short lived?" }).getByRole("button", { name: "Delete", exact: true }).click();

  await expect(page).toHaveURL(/\/benchmarks$/);
  await expect(page.getByText("No run has answered a benchmark yet.")).toBeVisible();
  expect((await page.request.get(`/api/benchmarks/runs/${id}`)).status()).toBe(404);
});

test("says that a run is not there, rather than showing nothing", async ({ page }) => {
  await page.goto("/benchmarks?id=nowhere");

  await expect(page.getByRole("alert").filter({ hasText: "The run could not be looked at." })).toContainText("There is no benchmark run");
  await expect(page.getByRole("link", { name: "All runs" })).toBeVisible();
});

test("has nothing wrong that axe can find, in the runs, or in a run that was answered", async ({ page }) => {
  const id = await arrange(page, { title: "Accessible exam", benchmark: "lab_bench_dbqa", solver: "single" });
  await answerThrough(page, id);

  await page.goto("/benchmarks");
  await expect(page.getByTestId("benchmark-run")).toHaveCount(1);
  expect(await accessibilityProblems(page)).toEqual([]);

  await openRun(page, id, "Accessible exam");
  await expect(questions(page)).toHaveCount(5);
  await page.getByRole("button", { name: "Show question lab_bench_dbqa/1" }).click();
  await expect(page.getByLabel("What was asked", { exact: true })).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
});
