import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { expect, test } from "../fixtures";

// The triages, and the agents made from them, are the workspace's, so each test takes what it made away, and none is run beside
// another. The code of each paper is a stand-in's, which writes a project for any address: one that is ready to be made into
// tools, "bare" one with no code and nothing to say what to install, "gpu" one that needs a GPU, "missing" one that is not there, and "slow"
// one that takes a while to fetch.
test.describe.configure({ mode: "serial" });

async function clear(page: Page) {
  const { jobs } = await (await page.request.get("/api/setup/jobs")).json();
  for (const job of jobs.filter((job: { kind: string; state: string }) => job.kind === "paperagent-triage" && job.state === "running")) {
    await page.request.post(`/api/setup/jobs/${job.id}/stop`);
  }
  const { triages } = await (await page.request.get("/api/paperagents/triage")).json();
  for (const triage of triages) {
    await expect.poll(async () => (await page.request.delete(`/api/paperagents/triage/${triage.id}`)).status(), { timeout: 20_000 }).toBe(200);
  }
  const { agents } = await (await page.request.get("/api/paperagents")).json();
  for (const agent of agents) {
    await expect.poll(async () => (await page.request.delete(`/api/paperagents/${agent.id}`)).status(), { timeout: 20_000 }).toBe(200);
  }
}

test.beforeEach(async ({ page }) => {
  await clear(page);
});

test.afterEach(async ({ page }) => {
  await clear(page);
});

// Begins a triage through the server, so that what a test is about is the page, and gives back its id
async function begin(page: Page, body: Record<string, unknown>): Promise<string> {
  const started = await page.request.post("/api/paperagents/triage", { data: body });
  expect(started.status()).toBe(202);

  return (await started.json()).id;
}

async function ended(page: Page, id: string) {
  await expect.poll(async () => (await (await page.request.get(`/api/paperagents/triage/${id}`)).json()).state, { timeout: 30_000 }).not.toBe("running");
}

const beginning = (page: Page) => page.getByRole("form", { name: "Begin a triage" });
const entries = (page: Page) => page.getByRole("list", { name: "The papers in order" }).getByTestId("triage-entry");

test("the triages are a part of the PaperAgents page, which says there are none yet, and asks for what is wrong to be put right", async ({ page }) => {
  await page.goto("/papers");
  const parts = page.getByRole("navigation", { name: "PaperAgents" });
  await parts.getByRole("link", { name: "Triage" }).click();
  await expect(page).toHaveURL(/\/papers\?view=triage$/);
  await expect(parts.getByRole("link", { name: "Triage" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("triages-empty")).toContainText("There are no triages yet");
  expect(await accessibilityProblems(page)).toEqual([]);

  const form = beginning(page);
  await form.getByRole("button", { name: "Begin the triage" }).click();
  await expect(form.getByText("Give papers to look at, list the preprints of bioRxiv, or both.")).toBeVisible();

  await form.getByLabel("Papers", { exact: true }).fill("10.1101/2024.01.01.000001 https://github.com/lab/tool\nnot-a-doi");
  await expect(form.getByText("Line 2: not-a-doi is not a DOI, such as 10.1101/2024.01.01.123456.")).toBeVisible();
  await expect(form.getByText("Give papers to look at")).toHaveCount(0);
  await form.getByLabel("Papers", { exact: true }).fill("10.1101/2024.01.01.000001 https://example.com/lab/tool");
  await expect(form.getByText(/Line 1: https:\/\/example\.com\/lab\/tool is not the address of a project's code/)).toBeVisible();

  await form.getByLabel("Papers", { exact: true }).fill("");
  await form.getByLabel("Look at the preprints bioRxiv posted in a period too").check();
  await form.getByLabel("From").fill("2024-01-08");
  await form.getByLabel("To", { exact: true }).fill("2024-01-07");
  await form.getByLabel("How many preprints").fill("301");
  await form.getByLabel("Papers whose code is looked at").fill("41");
  await form.getByLabel("Most fetched of one project, in MB").fill("4");
  await expect(form.getByText("The last day is before the first.")).toBeVisible();
  await expect(form.getByText("The number of preprints is a whole number from 1 to 300.")).toBeVisible();
  await expect(form.getByText("The most papers whose code is looked at is a whole number from 1 to 40.")).toBeVisible();
  await expect(form.getByText("The most that is fetched of one project is a whole number from 5 to 200, in megabytes.")).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  const { triages } = await (await page.request.get("/api/paperagents/triage")).json();
  expect(triages).toEqual([]);
});

test("ranks the papers given by what a look at their code says, makes a PaperAgent of one with its code, and deletes the triage", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/papers?view=triage");
  const form = beginning(page);
  await form
    .getByLabel("Papers", { exact: true })
    .fill(
      [
        "10.1101/2024.01.01.000004 https://github.com/lab/missing-tool",
        "10.1101/2024.01.01.000003 https://github.com/lab/gpu-tool",
        "10.1101/2024.01.01.000002 https://github.com/lab/bare-tool",
        "https://doi.org/10.1101/2024.01.01.000001 https://github.com/lab/tool",
      ].join("\n"),
    );
  await form.getByRole("button", { name: "Begin the triage" }).click();
  await expect(page).toHaveURL(/\/papers\?triage=[0-9a-f]{12}$/);
  const id = new URL(page.url()).searchParams.get("triage") ?? "";
  await expect(page.getByTestId("triage-source")).toHaveText("4 papers given.");
  await expect(page.getByTestId("triage-state")).toHaveText("Done", { timeout: 30_000 });

  const counted = (tier: string) => page.getByTestId("triage-count").and(page.locator(`[data-tier="${tier}"]`)).locator("span").first();
  await expect(counted("go")).toHaveText("1");
  await expect(counted("ask")).toHaveText("0");
  await expect(counted("no-go")).toHaveText("2");
  await expect(counted("not_looked_at")).toHaveText("1");
  await expect(counted("no_code")).toHaveText("0");
  await expect(page.getByTestId("triage-meaning")).toContainText("It does not say that a paper is good");

  await expect(entries(page)).toHaveCount(4);
  // Of the two that may not be gone on with, the one with less to weigh is first
  await expect(entries(page).nth(0)).toHaveAttribute("data-tier", "go");
  await expect(entries(page).nth(1)).toHaveAttribute("data-tier", "no-go");
  await expect(entries(page).nth(1)).toContainText("lab/gpu-tool");
  await expect(entries(page).nth(2)).toHaveAttribute("data-tier", "no-go");
  await expect(entries(page).nth(2)).toContainText("lab/bare-tool");
  await expect(entries(page).nth(3)).toHaveAttribute("data-tier", "not_looked_at");
  const first = entries(page).nth(0);
  await expect(first.getByTestId("triage-code").getByRole("link", { name: "lab/tool" })).toHaveAttribute("href", "https://github.com/lab/tool");
  await expect(first.getByTestId("triage-code")).toContainText("from the address you gave");
  await expect(first.getByTestId("triage-stock")).toContainText("License: MIT ·");
  await expect(first.getByTestId("triage-stock")).toContainText("1 tutorial or example");
  // A paper given with its code and no title is called by its DOI, as nothing was looked up of it
  await expect(first.getByRole("heading", { name: /10\.1101\/2024\.01\.01\.000001/ }).getByRole("link")).toHaveAttribute(
    "href",
    "https://doi.org/10.1101/2024.01.01.000001",
  );
  await expect(entries(page).nth(3).getByTestId("triage-why")).toContainText("Its code could not be fetched");
  await expect(entries(page).nth(3).getByTestId("triage-stock")).toHaveCount(0);

  const gpu = entries(page).nth(1);
  await gpu.getByText("What was looked at").click();
  await expect(gpu.getByTestId("triage-check").first()).toHaveAttribute("data-status", "block");
  await expect(gpu.getByTestId("triage-check").first()).toContainText("(Stops it)");
  expect(await accessibilityProblems(page)).toEqual([]);

  await first.getByRole("button", { name: /^Make a PaperAgent of/ }).click();
  await expect(page).toHaveURL(/\/papers\?agent=/);
  const { agents } = await (await page.request.get("/api/paperagents")).json();
  expect(agents).toHaveLength(1);
  expect(agents[0].paper).toEqual({ kind: "doi", doi: "10.1101/2024.01.01.000001" });
  expect(agents[0].repo.url).toBe("https://github.com/lab/tool");

  await page.goto(`/papers?triage=${id}`);
  await expect(entries(page).nth(0).getByRole("link", { name: "Open its PaperAgent" })).toHaveAttribute("href", `/papers?agent=${agents[0].id}`);
  await expect(entries(page).nth(1).getByRole("button", { name: /^Make a PaperAgent of/ })).toBeVisible();

  await page.getByRole("link", { name: "All triages" }).click();
  await expect(page.getByTestId("triage")).toHaveCount(1);
  await expect(page.getByTestId("triage")).toContainText("Done");
  await expect(page.getByTestId("triage")).toContainText("4 papers: 1 go, 2 no-go, 1 not looked at");

  await page.getByRole("link", { name: "4 papers given" }).click();
  await page.getByRole("button", { name: "Delete the triage" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/papers\?view=triage$/);
  await expect(page.getByTestId("triages-empty")).toBeVisible();
  expect((await (await page.request.get("/api/paperagents")).json()).agents).toHaveLength(1);
});

test("takes the code from the abstract, leaves what is beyond the most looked at, and keeps the papers with no code apart", async ({ page }) => {
  const id = await begin(page, {
    papers: [
      { doi: "10.1101/2024.01.01.000011", title: "Says nothing of code", abstract: "We map cells. Our code is available on request." },
      {
        doi: "10.1101/2024.01.01.000012",
        title: "Gives its code",
        abstract: "We map cells. Code: https://github.com/lab/mapper. See also https://gitlab.com/lab/other.",
      },
      { doi: "10.1101/2024.01.01.000013", title: "Beyond the most", code: "https://github.com/lab/later" },
    ],
    most_looked_at: 1,
  });
  await ended(page, id);
  await page.goto(`/papers?triage=${id}`);
  await expect(entries(page)).toHaveCount(2);
  const first = entries(page).nth(0);
  await expect(first).toContainText("Gives its code");
  await expect(first.getByTestId("triage-code").getByRole("link", { name: "lab/mapper" })).toBeVisible();
  await expect(first.getByTestId("triage-code")).toContainText("from the first address in its abstract");
  await expect(first).toContainText("Its abstract gives another too:");
  await expect(first.getByRole("link", { name: /lab\/other/ })).toHaveAttribute("href", "https://gitlab.com/lab/other");
  await expect(entries(page).nth(1)).toHaveAttribute("data-tier", "not_looked_at");
  await expect(entries(page).nth(1).getByTestId("triage-why")).toHaveText("Beyond the 1 papers whose code is looked at.");

  const none = page.getByTestId("triage-no-code");
  await expect(none.getByText("1 paper says nowhere in the abstract where the code is")).toBeVisible();
  await none.getByText("1 paper says nowhere in the abstract where the code is").click();
  const apart = none.getByTestId("triage-entry");
  await expect(apart).toHaveCount(1);
  await expect(apart).toContainText("Says nothing of code");
  await expect(apart.getByTestId("triage-why")).toHaveText("No address of code was found in the abstract.");
  await expect(apart.getByRole("button", { name: "Make a PaperAgent of Says nothing of code" })).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("follows the triage while it goes on, which cannot be deleted then, and keeps what it found when it is stopped", async ({ page }) => {
  test.setTimeout(90_000);
  const id = await begin(page, {
    papers: [
      { doi: "10.1101/2024.01.01.000021", code: "https://github.com/lab/slow-one" },
      { doi: "10.1101/2024.01.01.000022", code: "https://github.com/lab/slow-two" },
      { doi: "10.1101/2024.01.01.000023", code: "https://github.com/lab/slow-three" },
    ],
  });
  await page.goto(`/papers?triage=${id}`);
  await expect(page.getByTestId("triage-state")).toHaveText("Looking");
  await expect(page.getByRole("button", { name: "Delete the triage" })).toBeDisabled();
  await expect(page.getByText("The papers are put in order when the look at them ends.")).toBeVisible();
  const work = page.getByRole("region", { name: "What is being done" });
  await expect(work).toContainText("Looking at the code of 1 of 3");
  await page.goto("/papers?view=triage");
  await expect(page.getByTestId("triage")).toContainText("Looking");
  await page.goto(`/papers?triage=${id}`);
  await expect(page.getByRole("region", { name: "What is being done" })).toContainText(/Looking at the code of [12] of 3/);
  await page.getByRole("button", { name: /^Stop: / }).click();

  await expect(page.getByTestId("triage-state")).toHaveText("Stopped", { timeout: 20_000 });
  await expect(page.getByText(/It was stopped\. The papers that were looked at before that are in order below/)).toBeVisible();
  await expect(entries(page)).toHaveCount(3);
  await expect(page.getByTestId("triage-why").last()).toHaveText(/It was stopped before this paper was reached\.|Its code could not be read/);
  await expect(page.getByRole("button", { name: "Delete the triage" })).toBeEnabled();
});
