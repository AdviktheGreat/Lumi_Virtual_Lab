import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { askWhereCodeRuns, expect, test } from "../fixtures";

// The runs and the agents are the workspace's, and a conversation made while a run is given its functions is given them, so
// each test takes what it made away, and none is run beside another
test.describe.configure({ mode: "serial" });

const DESEQ = "Differential expression was found with DESeq2, from samples in GEO, aligned with STAR.";
const SCANPY = "Cells were clustered with Scanpy, and DESeq2 was used to find the markers.";
const TASK = "RNA-seq differential expression with DESeq2";

// Takes away every agent, and then every run, stopping what is at work on one first
async function clear(page: Page) {
  const { agents } = await (await page.request.get("/api/paperagents")).json();
  for (const agent of agents) {
    expect((await page.request.delete(`/api/paperagents/${agent.id}`)).status()).toBe(200);
  }
  const { runs } = await (await page.request.get("/api/papers")).json();
  for (const run of runs) {
    if (run.job) await page.request.post(`/api/setup/jobs/${run.job}/stop`);
    await expect.poll(async () => (await page.request.delete(`/api/papers/runs/${run.id}`)).status(), { timeout: 20_000 }).toBe(200);
  }
}

test.beforeEach(async ({ page }) => {
  await clear(page);
});

test.afterEach(async ({ page }) => {
  await clear(page);
});

// Makes a run of uploaded papers through the server, so that what a test is about is the page
async function arrange(page: Page, title: string, papers: Record<string, string>): Promise<string> {
  const made = await page.request.post("/api/papers/runs", { data: { title, source: { kind: "files" } } });
  expect(made.status()).toBe(201);
  const id: string = (await made.json()).id;
  for (const [name, text] of Object.entries(papers)) {
    const sent = await page.request.post(`/api/papers/runs/${id}/files?name=${encodeURIComponent(name)}`, {
      data: Buffer.from(text),
      headers: { "Content-Type": "application/octet-stream" },
    });
    expect(sent.status()).toBe(201);
  }

  return id;
}

// Reads the papers of a run through the server, and waits until that is done
async function readThrough(page: Page, id: string) {
  const started = await page.request.post(`/api/papers/runs/${id}/read`, { data: { max_cost: 5 } });
  expect(started.status()).toBe(202);
  await expect.poll(async () => (await (await page.request.get(`/api/papers/runs/${id}`)).json()).job, { timeout: 20_000 }).toBeNull();
}

async function openRun(page: Page, id: string, title: string) {
  await page.goto(`/papers?id=${id}`);
  await expect(page.getByRole("heading", { name: title, level: 2 })).toBeVisible();
}

const form = (page: Page, name: string) => page.getByRole("form", { name });

// The papers of the run that is open that were read, which are told from those that were not by the word of their status
const readPapers = (page: Page) =>
  page.getByRole("table", { name: "Papers" }).getByTestId("paper-result").filter({ has: page.getByText("Read", { exact: true }) });

test("the page opens on the agents, and its surveys are a part of it that is reached by a link", async ({ page }) => {
  await page.getByRole("link", { name: "PaperAgents", exact: true }).click();
  await expect(page.getByRole("heading", { name: "PaperAgents", level: 1 })).toBeVisible();
  const parts = page.getByRole("navigation", { name: "PaperAgents" });
  await expect(parts.getByRole("link", { name: "Agents" })).toHaveAttribute("aria-current", "page");
  await expect(parts.getByRole("link", { name: "Surveys" })).not.toHaveAttribute("aria-current");
  await expect(page.getByTestId("paper-agents-empty")).toContainText("There are no PaperAgents yet");
  await expect(page.getByRole("heading", { name: "Make a run" })).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  await parts.getByRole("link", { name: "Surveys" }).click();
  await expect(page).toHaveURL(/\/papers\?view=surveys$/);
  await expect(parts.getByRole("link", { name: "Surveys" })).toHaveAttribute("aria-current", "page");
  await expect(parts.getByRole("link", { name: "Agents" })).not.toHaveAttribute("aria-current");
  await expect(page.getByRole("link", { name: "PaperAgents", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Make a run" })).toBeVisible();
  await expect(page.getByTestId("paper-agents-empty")).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  // The link in the empty agents page leads to the same place
  await parts.getByRole("link", { name: "Agents" }).click();
  await expect(page).toHaveURL(/\/papers$/);
  await page.getByTestId("paper-agents-empty").getByRole("link", { name: "Surveys" }).click();
  await expect(page).toHaveURL(/\/papers\?view=surveys$/);

  // A part that is not one is the agents, as no part is
  await page.goto("/papers?view=nowhere");
  await expect(page.getByTestId("paper-agents-empty")).toBeVisible();
  await expect(parts.getByRole("link", { name: "Agents" })).toHaveAttribute("aria-current", "page");
});

// Makes an agent through the server, so that what a test is about is the page, and gives back its id
async function makeAgent(page: Page, body: Record<string, unknown>): Promise<string> {
  const made = await page.request.post("/api/paperagents", { data: body });
  expect(made.status()).toBe(201);

  return (await made.json()).id;
}

async function openAgent(page: Page, id: string, title: string) {
  await page.goto(`/papers?agent=${id}`);
  await expect(page.getByRole("heading", { name: title, level: 2 })).toBeVisible();
}

const agentIn = (page: Page) => new URL(page.url()).searchParams.get("agent") ?? "";

test("makes an agent of a DOI, with where its code is, which is then listed and opened", async ({ page }) => {
  await page.goto("/papers");
  const making = form(page, "Make an agent");
  await expect(making.getByRole("radio", { name: "A DOI" })).toBeChecked();

  // What is wrong is said by the field, and nothing is sent
  await making.getByRole("button", { name: "Make the agent" }).click();
  await expect(making.getByText("Give a DOI, such as 10.1038/s41586-020-2649-2.")).toBeVisible();
  await making.getByLabel("DOI", { exact: true }).fill("10.1038/ABC.1");
  await making.getByLabel("Where its code is").fill("https://example.org/owner/name");
  await making.getByRole("button", { name: "Make the agent" }).click();
  await expect(making.getByText(/Give the address of the project/)).toBeVisible();
  expect((await (await page.request.get("/api/paperagents")).json()).agents).toEqual([]);
  expect(await accessibilityProblems(page)).toEqual([]);

  await making.getByLabel("Where its code is").fill("https://github.com/Owner/Name");
  await making.getByRole("button", { name: "Make the agent" }).click();

  // With no title, the agent is called by the DOI, which is kept in lower case
  await expect(page.getByRole("heading", { name: "10.1038/abc.1", level: 2 })).toBeVisible();
  const id = agentIn(page);
  expect(id).not.toBe("");
  await expect(page.getByRole("link", { name: /^DOI 10\.1038\/abc\.1/ })).toHaveAttribute("href", "https://doi.org/10.1038/abc.1");
  await expect(page.getByRole("link", { name: /^Owner\/Name/ })).toHaveAttribute("href", "https://github.com/Owner/Name");
  const steps = page.getByRole("list", { name: "Steps" }).getByTestId("paper-agent-step");
  await expect(steps).toHaveCount(5);
  await expect(steps.first()).toContainText("Read the paper");
  await expect(steps.first()).toContainText("Not started");
  await expect(page.getByText("No paper is uploaded to this agent yet.")).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  await page.getByRole("link", { name: "All agents" }).click();
  await expect(page).toHaveURL(/\/papers$/);
  const row = page.getByRole("list", { name: "PaperAgents" }).getByTestId("paper-agent");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("DOI 10.1038/abc.1");
  await expect(row).toContainText("Code: Owner/Name");
  await expect(row).toContainText("Nothing has been done to it yet");
  await expect(page.getByTestId("paper-agents-empty")).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  await row.getByRole("link", { name: "10.1038/abc.1" }).click();
  await expect.poll(() => agentIn(page)).toBe(id);
});

test("makes an agent of a link with a title, and does not make a second of the same paper", async ({ page }) => {
  await page.goto("/papers");
  const making = form(page, "Make an agent");
  await making.getByRole("radio", { name: "A link" }).check();
  await making.getByLabel("Link to the paper").fill("nowhere");
  await making.getByRole("button", { name: "Make the agent" }).click();
  await expect(making.getByText("Give the link, which begins with http:// or https://.")).toBeVisible();

  await making.getByLabel("Link to the paper").fill("https://Example.org/papers/one/");
  await making.getByLabel("Title").fill("  The   first paper ");
  await making.getByRole("button", { name: "Make the agent" }).click();
  await expect(page.getByRole("heading", { name: "The first paper", level: 2 })).toBeVisible();
  const first = agentIn(page);
  await expect(page.getByRole("link", { name: /^https:\/\/example\.org\/papers\/one/ })).toBeVisible();

  // The same paper, written another way, is the same paper
  await page.goto("/papers");
  await making.getByRole("radio", { name: "A link" }).check();
  await making.getByLabel("Link to the paper").fill("https://example.org/papers/one");
  await making.getByLabel("Title").fill("Again");
  await making.getByRole("button", { name: "Make the agent" }).click();
  await expect(making.getByRole("alert").filter({ hasText: "There is a PaperAgent for that paper already" })).toContainText("The first paper");
  await expect(page).toHaveURL(/\/papers$/);
  await making.getByRole("link", { name: "Open that PaperAgent" }).click();
  await expect.poll(() => agentIn(page)).toBe(first);
  expect((await (await page.request.get("/api/paperagents")).json()).agents).toHaveLength(1);

  // A link to a DOI is a DOI
  await page.goto("/papers");
  await making.getByRole("radio", { name: "A DOI" }).check();
  await making.getByLabel("DOI", { exact: true }).fill("10.5555/one");
  await making.getByRole("button", { name: "Make the agent" }).click();
  await expect(page.getByRole("heading", { name: "10.5555/one", level: 2 })).toBeVisible();
  await page.goto("/papers");
  await making.getByRole("radio", { name: "A link" }).check();
  await making.getByLabel("Link to the paper").fill("https://doi.org/10.5555/ONE");
  await making.getByRole("button", { name: "Make the agent" }).click();
  await expect(making.getByRole("alert").filter({ hasText: "There is a PaperAgent for that paper already" })).toBeVisible();
});

test("makes an agent of a file, which is uploaded, uploaded again, and taken away", async ({ page }) => {
  await page.goto("/papers");
  const making = form(page, "Make an agent");
  await making.getByRole("radio", { name: "A file I upload" }).check();
  await expect(making.getByText(/You upload it to the agent once it is made/)).toBeVisible();

  // A title is what such an agent is called by, since there is nothing else to call it
  await making.getByRole("button", { name: "Make the agent" }).click();
  await expect(making.getByText("Give the agent a title.")).toBeVisible();
  await making.getByLabel("Title").fill("My own paper");
  await making.getByRole("button", { name: "Make the agent" }).click();
  await expect(page.getByRole("heading", { name: "My own paper", level: 2 })).toBeVisible();
  const id = agentIn(page);
  await expect(page.getByText("No paper is uploaded to this agent yet.")).toBeVisible();
  await expect(page.getByText("A file that has not been uploaded yet")).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);

  const kept = async () => (await (await page.request.get(`/api/paperagents/${id}`)).json()).paper.file;
  await page.getByLabel("Upload the paper").setInputFiles({ name: "a.txt", mimeType: "text/plain", buffer: Buffer.from(DESEQ) });
  const file = page.getByTestId("paper-agent-file");
  await expect(file).toContainText("a.txt");
  await expect(page.getByText("a.txt, ", { exact: false }).first()).toBeVisible();
  expect(await kept()).toMatchObject({ name: "a.txt", bytes: DESEQ.length });
  expect(await accessibilityProblems(page)).toEqual([]);

  // What is uploaded again takes the place of what was
  await page.getByLabel("Upload it again").setInputFiles({ name: "b.txt", mimeType: "text/plain", buffer: Buffer.from(SCANPY) });
  await expect(file).toContainText("b.txt");
  await expect(file).toHaveCount(1);
  expect(await kept()).toMatchObject({ name: "b.txt", bytes: SCANPY.length });

  // What is not a paper is said not to be, and the paper that is kept is left
  await page.getByLabel("Upload it again").setInputFiles({ name: "run.exe", mimeType: "application/octet-stream", buffer: Buffer.from("MZ") });
  await expect(page.getByRole("alert").filter({ hasText: "run.exe is not a paper this reads" })).toBeVisible();
  await expect(file).toContainText("b.txt");

  await page.getByRole("button", { name: "Remove b.txt" }).click();
  await expect(page.getByText("No paper is uploaded to this agent yet.")).toBeVisible();
  await expect(file).toHaveCount(0);
  expect(await kept()).toBeNull();

  // The paper of another agent is not taken for a second
  const other = await makeAgent(page, { title: "Another", paper: { kind: "file" } });
  const sent = await page.request.post(`/api/paperagents/${other}/paper?name=c.txt`, {
    data: Buffer.from(DESEQ),
    headers: { "Content-Type": "application/octet-stream" },
  });
  expect(sent.status()).toBe(200);
  await page.getByLabel("Upload the paper").setInputFiles({ name: "d.txt", mimeType: "text/plain", buffer: Buffer.from(DESEQ) });
  await expect(page.getByRole("alert").filter({ hasText: "There is a PaperAgent for that paper already" })).toContainText("Another");
  await page.getByRole("link", { name: "Open that PaperAgent" }).click();
  await expect.poll(() => agentIn(page)).toBe(other);
});

test("says again what an agent is called and where its code is", async ({ page }) => {
  const id = await makeAgent(page, { title: "Old title", paper: { kind: "doi", doi: "10.1000/old" }, repo: "https://github.com/owner/old" });
  await openAgent(page, id, "Old title");
  const details = form(page, "What the agent is");
  await expect(details.getByLabel("Title")).toHaveValue("Old title");
  await expect(details.getByLabel("Where its code is")).toHaveValue("https://github.com/owner/old");
  await expect(details.getByRole("button", { name: "Save" })).toBeDisabled();

  // Nothing is saved while what is typed is not fit
  await details.getByLabel("Title").fill("   ");
  await details.getByLabel("Where its code is").fill("https://example.org/a/b");
  await details.getByRole("button", { name: "Save" }).click();
  await expect(details.getByText("Give the agent a title.")).toBeVisible();
  await expect(details.getByText(/Give the address of the project/)).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  expect((await (await page.request.get(`/api/paperagents/${id}`)).json()).title).toBe("Old title");

  await details.getByLabel("Title").fill("New title");
  await details.getByLabel("Where its code is").fill("https://gitlab.com/group/new");
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: "New title", level: 2 })).toBeVisible();
  await expect(page.getByRole("link", { name: /^group\/new/ })).toBeVisible();
  await expect(details.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(await (await page.request.get(`/api/paperagents/${id}`)).json()).toMatchObject({
    title: "New title",
    repo: { url: "https://gitlab.com/group/new" },
  });

  // A blank address takes the code away
  await details.getByLabel("Where its code is").fill("");
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/^Code:/)).toHaveCount(0);
  await expect(details.getByRole("button", { name: "Save" })).toBeDisabled();
  expect((await (await page.request.get(`/api/paperagents/${id}`)).json()).repo).toBeNull();
});

test("deletes an agent, after asking, with the paper that was uploaded to it", async ({ page }) => {
  const id = await makeAgent(page, { title: "Short lived", paper: { kind: "file" } });
  await page.request.post(`/api/paperagents/${id}/paper?name=a.txt`, {
    data: Buffer.from(DESEQ),
    headers: { "Content-Type": "application/octet-stream" },
  });
  await openAgent(page, id, "Short lived");

  await page.getByRole("button", { name: "Delete Short lived" }).click();
  const asking = page.getByRole("alertdialog", { name: "Delete Short lived?" });
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  expect((await page.request.get(`/api/paperagents/${id}`)).status()).toBe(200);

  await page.getByRole("button", { name: "Delete Short lived" }).click();
  await page.getByRole("alertdialog", { name: "Delete Short lived?" }).getByRole("button", { name: "Delete", exact: true }).click();

  await expect(page).toHaveURL(/\/papers$/);
  await expect(page.getByTestId("paper-agents-empty")).toBeVisible();
  expect((await page.request.get(`/api/paperagents/${id}`)).status()).toBe(404);
});

test("says that an agent is not there, rather than showing nothing, and a survey is looked for first", async ({ page }) => {
  await page.goto("/papers?agent=nowhere");
  await expect(page.getByRole("alert").filter({ hasText: "The agent could not be looked at." })).toContainText("There is no PaperAgent");
  await expect(page.getByRole("link", { name: "All agents" })).toBeVisible();

  await page.goto("/papers?id=nowhere&agent=nowhere");
  await expect(page.getByRole("alert").filter({ hasText: "The run could not be looked at." })).toBeVisible();
  await expect(page.getByRole("link", { name: "All runs" })).toBeVisible();
});

test("keeps the agents of the lab apart from the runs of a survey", async ({ page }) => {
  await makeAgent(page, { title: "An agent", paper: { kind: "doi", doi: "10.1000/apart" } });
  await arrange(page, "A survey", { "a.txt": DESEQ });

  await page.goto("/papers");
  await expect(page.getByTestId("paper-agent")).toHaveCount(1);
  await expect(page.getByTestId("paper-run")).toHaveCount(0);
  await page.goto("/papers?view=surveys");
  await expect(page.getByTestId("paper-run")).toHaveCount(1);
  await expect(page.getByTestId("paper-agent")).toHaveCount(0);
});

test("makes an agent of a paper, and an agent of a file, that axe finds nothing wrong with", async ({ page }) => {
  const id = await makeAgent(page, { title: "Accessible agent", paper: { kind: "file" }, repo: "https://github.com/owner/name" });
  await page.request.post(`/api/paperagents/${id}/paper?name=a.txt`, {
    data: Buffer.from(DESEQ),
    headers: { "Content-Type": "application/octet-stream" },
  });
  await makeAgent(page, { title: "Cited agent", paper: { kind: "url", url: "https://example.org/cited" } });

  await page.goto("/papers");
  await expect(page.getByTestId("paper-agent")).toHaveCount(2);
  expect(await accessibilityProblems(page)).toEqual([]);

  await openAgent(page, id, "Accessible agent");
  await expect(page.getByTestId("paper-agent-file")).toContainText("a.txt");
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("makes a run of papers that are uploaded, uploads them, and reads them with a budget", async ({ page }) => {
  await page.getByRole("link", { name: "PaperAgents", exact: true }).click();
  await page.getByRole("navigation", { name: "PaperAgents" }).getByRole("link", { name: "Surveys" }).click();
  await expect(page.getByText("No papers have been read yet.")).toBeVisible();

  await form(page, "Make a run").getByLabel("Title").fill("Gene papers");
  await form(page, "Make a run").getByRole("button", { name: "Make the run" }).click();
  await expect(page.getByRole("heading", { name: "Gene papers", level: 2 })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("id")).toBe("gene-papers");

  await page.getByLabel("Add papers").setInputFiles([
    { name: "a.txt", mimeType: "text/plain", buffer: Buffer.from(DESEQ) },
    { name: "b.txt", mimeType: "text/plain", buffer: Buffer.from(SCANPY) },
  ]);
  await expect(page.getByRole("list", { name: "Uploaded papers" }).getByRole("listitem")).toHaveCount(2);

  await form(page, "Read the papers").getByLabel("Most it may spend, in dollars").fill("2");
  await form(page, "Read the papers").getByRole("button", { name: "Read the papers" }).click();

  await expect(readPapers(page)).toHaveCount(2, { timeout: 15_000 });
  await expect(page.getByRole("region", { name: "What is being done" })).toContainText("Read 2 of 2 papers");

  const tasks = page.getByRole("table", { name: "Tasks" });
  await expect(tasks.getByRole("row", { name: new RegExp(`${TASK}\\s+2$`) })).toBeVisible();
  await expect(tasks.getByRole("row", { name: /Single-cell clustering with Scanpy\s+1$/ })).toBeVisible();
  await expect(page.getByRole("table", { name: "Databases" }).getByRole("row", { name: /GEO\s+2$/ })).toBeVisible();
  await expect(page.getByRole("table", { name: "Software" }).getByRole("row", { name: /STAR\s+2$/ })).toBeVisible();

  // The table that can be downloaded is the one that was counted
  const link = page.getByRole("link", { name: "Download as a table, tasks" });
  const table = await page.request.get((await link.getAttribute("href")) ?? "");
  expect(table.status()).toBe(200);
  expect(await table.text()).toContain(TASK);

  await page.getByRole("link", { name: "All runs" }).click();
  await expect(page).toHaveURL(/\/papers\?view=surveys$/);
  await expect(page.getByTestId("paper-run")).toContainText("Read 2 of 2 papers");
});

test("follows the reading while it goes on, and stops it", async ({ page }) => {
  const id = await arrange(page, "Slow papers", {
    "a.txt": `slow: ${DESEQ}`,
    "b.txt": `slow: ${DESEQ}`,
    "c.txt": `slow: ${DESEQ}`,
  });
  await openRun(page, id, "Slow papers");

  await form(page, "Read the papers").getByRole("button", { name: "Read the papers" }).click();

  const status = page.getByRole("region", { name: "What is being done" });
  await expect(status.getByRole("progressbar", { name: "Progress: Reading papers: Slow papers" })).toBeVisible();
  await expect(status.getByText("0 of 3 papers")).toBeVisible();
  // Nothing else is done to a run while it is being read
  await expect(form(page, "Read the papers").getByRole("button", { name: "Read the papers" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Remove a.txt" })).toBeDisabled();

  // A paper that is stopped in the middle of is not kept, so it is the second that is stopped
  await expect(status.getByText("1 of 3 papers")).toBeVisible({ timeout: 10_000 });
  await status.getByRole("button", { name: "Stop: Reading papers: Slow papers" }).click();
  await expect(status.getByRole("button", { name: "Stopping: Reading papers: Slow papers" })).toBeDisabled();

  await expect(status.getByRole("progressbar")).toHaveCount(0, { timeout: 15_000 });
  await expect(status.getByText("Stopped", { exact: true })).toBeVisible();
  // What was read is kept, and the rest is left for the next time
  const papers = page.getByRole("table", { name: "Papers" });
  await expect(papers.getByTestId("paper-result").filter({ hasText: "Not read" })).toHaveCount(2);
  await expect(form(page, "Read the papers").getByRole("button", { name: "Read the papers" })).toBeEnabled();
});

test("says why a paper was not read, and why reading was refused", async ({ page }) => {
  const id = await arrange(page, "Odd papers", { "good.txt": DESEQ, "bad.txt": `fail: ${DESEQ}` });
  await openRun(page, id, "Odd papers");

  await form(page, "Read the papers").getByRole("button", { name: "Read the papers" }).click();

  const papers = page.getByRole("table", { name: "Papers" });
  await expect(papers.getByTestId("paper-result").filter({ hasText: "Failed" })).toContainText("The scripted model failed to read the paper", {
    timeout: 15_000,
  });
  await expect(readPapers(page)).toHaveCount(1);
  // A paper that failed is read again only if that is asked for
  await expect(form(page, "Read the papers").getByLabel("Read again the papers that failed")).toBeVisible();

  await page.route("**/api/papers/runs/*/read", (route) =>
    route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "missing_keys", message: "gpt-5.2 needs OPENAI_API_KEY, which is not set. Add it in the settings.", missing: ["OPENAI_API_KEY"] },
      }),
    }),
  );
  await form(page, "Read the papers").getByRole("button", { name: "Read the papers" }).click();

  const problem = form(page, "Read the papers").getByRole("alert");
  await expect(problem).toContainText("gpt-5.2 needs OPENAI_API_KEY");
  await expect(problem.getByRole("button", { name: "Add the key" })).toBeVisible();
});

test("asks for what is wrong with a run, a budget, and the papers uploaded to be put right before they are sent", async ({ page }) => {
  await page.goto("/papers?view=surveys");
  const make = form(page, "Make a run");

  await make.getByRole("button", { name: "Make the run" }).click();
  await expect(make.getByRole("alert")).toHaveText("Give the run a title.");
  await make.getByLabel("Title").fill("Preprints");
  await make.getByRole("radio", { name: "bioRxiv" }).check();
  await make.getByRole("button", { name: "Make the run" }).click();
  await expect(make.getByRole("alert")).toHaveText("Say the first day, as a date.");
  await make.getByRole("radio", { name: "A folder on this machine" }).check();
  await make.getByRole("button", { name: "Make the run" }).click();
  await expect(make.getByRole("alert")).toHaveText("Give the full path of the folder.");
  await make.getByLabel("Full path of the folder").fill("/no/such/folder/at/all");
  await make.getByRole("button", { name: "Make the run" }).click();
  await expect(make.getByRole("alert")).toContainText("There is no folder at /no/such/folder/at/all");
  expect((await (await page.request.get("/api/papers")).json()).runs).toEqual([]);

  const id = await arrange(page, "Checked papers", {});
  await openRun(page, id, "Checked papers");
  const read = form(page, "Read the papers");
  await expect(read.getByRole("button", { name: "Read the papers" })).toBeDisabled();
  await page.getByLabel("Add papers").setInputFiles({ name: "notes.docx", mimeType: "application/octet-stream", buffer: Buffer.from("x") });
  await expect(page.getByRole("list", { name: "Papers that were not added" })).toContainText("notes.docx is not a paper this reads");
  await page.getByLabel("Add papers").setInputFiles({ name: "a.txt", mimeType: "text/plain", buffer: Buffer.from(DESEQ) });
  await expect(page.getByTestId("paper-upload")).toHaveCount(1);

  await read.getByLabel("Most it may spend, in dollars").fill("lots");
  await read.getByRole("button", { name: "Read the papers" }).click();
  await expect(read.getByRole("alert")).toHaveText("The most it may spend is an amount in dollars, such as 1 or 0.50.");
  const { jobs } = await (await page.request.get("/api/setup/jobs")).json();
  expect(jobs.filter((job: { subject: string }) => job.subject === id)).toEqual([]);
});

test("reads the papers in a folder where they are, which is not copied", async ({ page }) => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "vl-e2e-papers-"));
  try {
    fs.writeFileSync(path.join(folder, "one.txt"), DESEQ);
    fs.writeFileSync(path.join(folder, "two.txt"), SCANPY);
    await page.goto("/papers?view=surveys");
    const make = form(page, "Make a run");
    await make.getByLabel("Title").fill("Folder papers");
    await make.getByRole("radio", { name: "A folder on this machine" }).check();
    await make.getByLabel("Full path of the folder").fill(folder);

    await make.getByRole("button", { name: "Make the run" }).click();

    await expect(page.getByRole("heading", { name: "Folder papers", level: 2 })).toBeVisible();
    await expect(page.getByRole("table", { name: "Papers" }).getByTestId("paper-result")).toHaveCount(2);
    await expect(page.getByLabel("Add papers")).toHaveCount(0);
    await form(page, "Read the papers").getByRole("button", { name: "Read the papers" }).click();
    await expect(readPapers(page)).toHaveCount(2, { timeout: 15_000 });
  } finally {
    fs.rmSync(folder, { recursive: true, force: true });
  }
});

test("writes functions for the tasks the papers share, shows their code, and gives them to conversations", async ({ page }) => {
  const id = await arrange(page, "Shared tasks", { "a.txt": DESEQ, "b.txt": DESEQ });
  await readThrough(page, id);
  await openRun(page, id, "Shared tasks");
  await expect(page.getByText("No function is written for this run yet.")).toBeVisible();

  await form(page, "Write functions").getByRole("button", { name: "Write the functions" }).click();

  const functions = page.getByRole("list", { name: "Functions" });
  await expect(functions.getByTestId("paper-function")).toHaveCount(1, { timeout: 15_000 });
  const row = functions.getByTestId("paper-function");
  await expect(row).toContainText("Found in 2 papers");
  await expect(row).toContainText("Not run");
  const name = (await row.locator("code").first().textContent()) ?? "";
  expect(name).not.toBe("");

  await row.getByRole("button", { name: `Show the code of ${name}` }).click();
  await expect(row.getByLabel(`Code of ${name}`, { exact: true })).toContainText(`def ${name}(path: str)`);
  await row.getByRole("button", { name: `Hide the code of ${name}` }).click();
  await expect(row.getByLabel(`Code of ${name}`, { exact: true })).toHaveCount(0);

  // A conversation that is made before they are given is not given them, and one made after is
  const given = page.getByLabel("Give these functions to the programs I start");
  await expect(given).not.toBeChecked();
  await given.click();
  await expect(given).toBeChecked();
  expect((await (await page.request.get(`/api/papers/runs/${id}`)).json()).given).toBe(true);
  await askWhereCodeRuns(page, "tool:offered");
  await expect(page.getByTestId("lead-message").last()).toContainText(name, { timeout: 15_000 });

  await openRun(page, id, "Shared tasks");
  await page.getByRole("button", { name: `Delete ${name}` }).click();
  await expect(page.getByText("No function is written for this run yet.")).toBeVisible();
});

test("deletes a run, after asking", async ({ page }) => {
  const id = await arrange(page, "Short lived", { "a.txt": DESEQ });
  await openRun(page, id, "Short lived");

  await page.getByRole("button", { name: "Delete Short lived" }).click();
  const asking = page.getByRole("alertdialog", { name: "Delete Short lived?" });
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  expect((await page.request.get(`/api/papers/runs/${id}`)).status()).toBe(200);

  await page.getByRole("button", { name: "Delete Short lived" }).click();
  await page.getByRole("alertdialog", { name: "Delete Short lived?" }).getByRole("button", { name: "Delete", exact: true }).click();

  await expect(page).toHaveURL(/\/papers\?view=surveys$/);
  await expect(page.getByText("No papers have been read yet.")).toBeVisible();
  expect((await page.request.get(`/api/papers/runs/${id}`)).status()).toBe(404);
});

test("says that a run is not there, rather than showing nothing", async ({ page }) => {
  await page.goto("/papers?id=nowhere");

  await expect(page.getByRole("alert").filter({ hasText: "The run could not be looked at." })).toContainText("There is no run");
  await expect(page.getByRole("link", { name: "All runs" })).toBeVisible();
});

test("has nothing wrong that axe can find, in the runs, or in a run that was read and has a function", async ({ page }) => {
  const id = await arrange(page, "Accessible papers", { "a.txt": DESEQ, "b.txt": SCANPY });
  await readThrough(page, id);
  const written = await page.request.post(`/api/papers/runs/${id}/functions`, { data: { max_cost: 5 } });
  expect(written.status()).toBe(202);
  await expect.poll(async () => (await (await page.request.get(`/api/papers/runs/${id}`)).json()).job, { timeout: 20_000 }).toBeNull();

  await page.goto("/papers?view=surveys");
  await expect(page.getByTestId("paper-run")).toHaveCount(1);
  expect(await accessibilityProblems(page)).toEqual([]);

  await openRun(page, id, "Accessible papers");
  await expect(page.getByTestId("paper-function").first()).toBeVisible();
  await page.getByRole("button", { name: /^Show the code of / }).first().click();
  await expect(page.getByLabel(/^Code of /)).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
});
