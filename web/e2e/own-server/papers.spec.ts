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
  const { jobs } = await (await page.request.get("/api/setup/jobs")).json();
  const working = ["paperagent-reading", "paperagent-repository", "paperagent-environment", "paperagent-data", "paperagent-reference", "paperagent-tools"];
  for (const job of jobs.filter((job: { kind: string; state: string }) => working.includes(job.kind) && job.state === "running")) {
    await page.request.post(`/api/setup/jobs/${job.id}/stop`);
  }
  const { agents } = await (await page.request.get("/api/paperagents")).json();
  for (const agent of agents) {
    await expect.poll(async () => (await page.request.delete(`/api/paperagents/${agent.id}`)).status(), { timeout: 20_000 }).toBe(200);
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
  // A DOI is fetched when it is read, and the file of the paper can be uploaded beside it in place of that
  await expect(page.getByRole("heading", { name: "Paper file", level: 2 })).toBeVisible();
  await expect(page.getByText("No file is kept yet. The text of the paper is fetched when it is read, and kept here.")).toBeVisible();
  await expect(page.getByRole("form", { name: "Read the paper" }).getByRole("button", { name: "Fetch and read the paper", exact: true })).toBeVisible();
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
  expect(sent.status()).toBe(201);
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

// A paper of a few sentences, each of which the scripted model reads a fact from, and of one chunk
const RESULT = "CellMapper reached an AUROC of 0.93 on held-out mouse hippocampus nuclei, higher than the 0.88 of Seurat label transfer.";
const METHOD = "Clusters were found with Seurat v4.3 after the reads were aligned.";
const DATA = "Raw sequencing data are available in GEO under accession GSE123456.";
const CODE = "Code is available at https://github.com/example/cellmapper under the MIT license.";
const LIMIT = "CellMapper was only tested on mouse brain tissue, and it assumes at least 500 nuclei in each sample.";
const CELLS = [
  "CellMapper: mapping cell types",
  "Abstract",
  "fabricate: We present CellMapper, a method for mapping cell types.",
  "Results",
  RESULT,
  "Methods",
  METHOD,
  "Data availability",
  DATA,
  "Code availability",
  CODE,
  "Limitations",
  LIMIT,
  "References",
  "1. Doe J. et al. A method for cells. Nature 2020.",
].join("\n\n");

// A paper of a few chunks, each a paragraph that is too long to share a chunk with another, and says what to do to read it
function chunked(chunks: number, mark: string): string {
  const filler = "The reads were aligned to the genome and counted for each gene in each of the samples. ".repeat(40);

  return Array.from({ length: chunks }, (_, number) => `${mark} Part ${number + 1}. ${filler}`).join("\n\n");
}

async function sendPaper(page: Page, id: string, name: string, text: string) {
  const sent = await page.request.post(`/api/paperagents/${id}/paper?name=${encodeURIComponent(name)}`, {
    data: Buffer.from(text),
    headers: { "Content-Type": "application/octet-stream" },
  });
  expect(sent.status()).toBe(201);
}

const reading = (page: Page) => form(page, "Read the paper");
const status = (page: Page) => page.getByRole("region", { name: "What is being done" });
const summary = (page: Page) => page.getByTestId("paper-reading-summary");

test("reads the paper of an agent with a budget, and shows what was found with the paper's own words", async ({ page }) => {
  const id = await makeAgent(page, { title: "Cell mapper", paper: { kind: "file" } });
  await openAgent(page, id, "Cell mapper");
  await expect(page.getByText("Upload the paper's file to have it read.")).toBeVisible();
  await expect(reading(page)).toHaveCount(0);

  await page.getByLabel("Upload the paper").setInputFiles({ name: "cells.txt", mimeType: "text/plain", buffer: Buffer.from(CELLS) });
  await expect(page.getByTestId("paper-agent-file")).toContainText("cells.txt");
  await expect(reading(page)).toBeVisible();
  await expect(summary(page)).toHaveCount(0);

  await reading(page).getByLabel("Most it may spend, in dollars").fill("2");
  await reading(page).getByRole("button", { name: "Read the paper" }).click();

  await expect(summary(page)).toContainText("Read 1 of 1 chunk", { timeout: 15_000 });
  await expect(status(page)).toContainText("Reading the paper: Cell mapper");
  await expect(status(page)).toContainText("Read 1 of 1 chunks");
  await expect(page.getByTestId("paper-agent-step").filter({ hasText: "Read the paper" })).toContainText("Done");

  // Each fact is with the words of the paper, which are in it
  const claims = page.getByRole("list", { name: "What the authors report" });
  await expect(claims.getByTestId("paper-fact")).toHaveCount(1);
  await expect(claims).toContainText("0.93");
  await expect(claims).toContainText("A number");
  await expect(claims.getByRole("blockquote")).toHaveText(RESULT);
  await expect(claims).toContainText("Results");
  await expect(page.getByRole("list", { name: "Software" })).toContainText("Seurat");
  await expect(page.getByRole("list", { name: "Software" })).toContainText("Version 4.3");
  await expect(page.getByRole("list", { name: "Data used" })).toContainText("GSE123456");
  await expect(page.getByRole("list", { name: "What the method was tested on" })).toContainText("Species");
  await expect(page.getByRole("list", { name: "Where the authors say it falls short" }).getByRole("blockquote")).toHaveText(LIMIT);
  const link = page.getByRole("list", { name: "Links" }).getByRole("link", { name: /github\.com\/example\/cellmapper/ });
  await expect(link).toHaveAttribute("href", "https://github.com/example/cellmapper");
  await expect(link).toHaveAttribute("rel", /noopener/);

  // What the model gave that the paper does not bear out is said to have been left out, and is not shown
  await expect(page.getByText("1 fact the model gave was left out, because the paper does not bear it out.")).toBeVisible();
  await expect(page.getByText("This method works on every species.")).toHaveCount(0);
  await expect(page.getByText(/a draft that nobody has checked/)).toBeVisible();

  // The place of a fact is shown in the paper, with what is around it
  const show = claims.getByRole("button", { name: /^Show in the paper: CellMapper reached/ });
  await expect(show).toHaveAttribute("aria-expanded", "false");
  await show.click();
  const shown = claims.getByRole("group", { name: "The paper at this place" });
  await expect(shown.locator("mark")).toHaveText(RESULT);
  await expect(shown).toContainText("Results");
  const hide = claims.getByRole("button", { name: /^Hide: CellMapper reached/ });
  await expect(hide).toHaveAttribute("aria-expanded", "true");
  await expect(hide).toHaveAttribute("aria-controls", (await shown.getAttribute("id")) ?? "none");
  expect(await accessibilityProblems(page)).toEqual([]);
  await claims.getByRole("button", { name: /^Hide: / }).click();
  await expect(shown).toHaveCount(0);

  // A paper that has been read through is not read again until the reading is cleared
  await expect(reading(page).getByRole("button", { name: "Read the paper" })).toBeDisabled();
  await expect(reading(page)).toContainText("The paper has been read. Clear the reading to read it again.");
  const kept = await (await page.request.get(`/api/paperagents/${id}/reading`)).json();
  expect(kept).toMatchObject({ chunks: 1, read: 1, complete: true });
  expect(kept.claims).toHaveLength(1);

  await page.getByRole("button", { name: "Clear the reading" }).click();
  const asking = page.getByRole("alertdialog", { name: "Clear the reading of Cell mapper?" });
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  await expect(claims).toBeVisible();
  await page.getByRole("button", { name: "Clear the reading" }).click();
  await page.getByRole("alertdialog", { name: "Clear the reading of Cell mapper?" }).getByRole("button", { name: "Clear", exact: true }).click();

  await expect(claims).toHaveCount(0);
  await expect(summary(page)).toHaveCount(0);
  await expect(reading(page).getByRole("button", { name: "Read the paper" })).toBeEnabled();
  await expect(page.getByTestId("paper-agent-step").filter({ hasText: "Read the paper" })).toContainText("Not started");
  expect((await (await page.request.get(`/api/paperagents/${id}/reading`)).json()).chunks).toBeNull();
  // The paper is kept
  await expect(page.getByTestId("paper-agent-file")).toContainText("cells.txt");
});

test("reads the file that is uploaded beside a DOI, which is then not fetched", async ({ page }) => {
  const id = await makeAgent(page, { title: "By DOI", paper: { kind: "doi", doi: "10.1000/beside" } });
  await openAgent(page, id, "By DOI");
  await expect(page.getByRole("heading", { name: "Paper file", level: 2 })).toBeVisible();
  await expect(page.getByText("When a DOI or a link is read, its text is fetched", { exact: false })).toBeVisible();
  await expect(page.getByText("Upload the paper's file to have it read.")).toHaveCount(0);
  await expect(fetchAndRead(page)).toBeVisible();

  await page.getByLabel("Upload the paper").setInputFiles({ name: "beside.txt", mimeType: "text/plain", buffer: Buffer.from(CELLS) });
  await expect(page.getByTestId("paper-agent-file")).toContainText("beside.txt");
  await expect(page.getByTestId("paper-agent-source")).toHaveCount(0);
  await expect(page.getByText("DOI 10.1000/beside")).toBeVisible();
  expect((await (await page.request.get(`/api/paperagents/${id}`)).json()).paper).toMatchObject({ kind: "doi", file: { name: "beside.txt" } });

  // A paper that has its file is read from it, and is not asked of Europe PMC
  await expect(fetchAndRead(page)).toHaveCount(0);
  await reading(page).getByRole("button", { name: "Read the paper", exact: true }).click();
  await expect(summary(page)).toContainText("Read 1 of 1 chunk", { timeout: 15_000 });
  await expect(status(page)).toContainText("Reading the paper: By DOI");
  await expect(page.getByRole("list", { name: "What the authors report" })).toContainText("0.93");
  expect((await (await page.request.get(`/api/paperagents/${id}`)).json()).paper.file.source ?? null).toBeNull();

  // Taking the file away takes away what was read of it, and leaves the paper to be fetched
  await page.getByRole("button", { name: "Remove beside.txt" }).click();
  await expect(fetchAndRead(page)).toBeVisible();
  await expect(page.getByRole("list", { name: "What the authors report" })).toHaveCount(0);
  expect((await (await page.request.get(`/api/paperagents/${id}`)).json()).paper.file ?? null).toBeNull();
});

const fetchAndRead = (page: Page) => reading(page).getByRole("button", { name: "Fetch and read the paper", exact: true });

test("fetches the paper of a DOI when it is read, keeps the text as the paper's file, and says where it came from", async ({ page }) => {
  const id = await makeAgent(page, { title: "Open cells", paper: { kind: "doi", doi: "10.1000/open-cells" } });
  await openAgent(page, id, "Open cells");
  await expect(page.getByText("No file is kept yet.", { exact: false })).toBeVisible();
  await expect(reading(page)).toContainText("The paper has no file yet, so its text is fetched first, which costs nothing: from Europe PMC");
  await expect(page.getByTestId("paper-agent-source")).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  await reading(page).getByLabel("Most it may spend, in dollars").fill("2");
  await fetchAndRead(page).click();

  await expect(summary(page)).toContainText("Read 1 of 1 chunk", { timeout: 15_000 });
  await expect(status(page)).toContainText("Fetching and reading the paper: Open cells");
  await expect(page.getByTestId("paper-agent-file")).toContainText("europepmc-pmc7000001.txt");
  const source = page.getByTestId("paper-agent-source");
  await expect(source).toContainText("Fetched from Europe PMC, PMC7000001");
  await expect(source).toContainText("is not fetched again");
  const link = source.getByRole("link", { name: /Fetched from Europe PMC, PMC7000001/ });
  await expect(link).toHaveAttribute("href", "https://europepmc.org/article/PMC/PMC7000001");
  await expect(link).toHaveAttribute("rel", /noopener/);
  await expect(page.getByTestId("paper-agent-step").filter({ hasText: "Read the paper" })).toContainText("Done");
  const claims = page.getByRole("list", { name: "What the authors report" });
  await expect(claims.getByRole("blockquote")).toContainText("AUROC of 0.93");
  expect(await accessibilityProblems(page)).toEqual([]);
  const kept = (await (await page.request.get(`/api/paperagents/${id}`)).json()).paper;
  expect(kept).toMatchObject({ kind: "doi", file: { name: "europepmc-pmc7000001.txt", source: { kind: "europepmc", label: "Europe PMC, PMC7000001" } } });

  // The text that was fetched is the paper from then on, so reading it again is not fetching it again
  await page.getByRole("button", { name: "Clear the reading" }).click();
  await page.getByRole("alertdialog", { name: "Clear the reading of Open cells?" }).getByRole("button", { name: "Clear", exact: true }).click();
  await expect(claims).toHaveCount(0);
  await expect(fetchAndRead(page)).toHaveCount(0);
  await expect(reading(page).getByRole("button", { name: "Read the paper", exact: true })).toBeEnabled();
  await expect(source).toContainText("Fetched from Europe PMC, PMC7000001");

  // Taking the text away leaves the paper to be fetched again
  await page.getByRole("button", { name: "Remove europepmc-pmc7000001.txt" }).click();
  await expect(page.getByTestId("paper-agent-file")).toHaveCount(0);
  await expect(source).toHaveCount(0);
  await expect(fetchAndRead(page)).toBeEnabled();
});

test("fetches the paper of a link when it is read, from where the link leads", async ({ page }) => {
  const id = await makeAgent(page, { title: "Linked cells", paper: { kind: "url", url: "https://example.org/papers/fetched" } });
  await openAgent(page, id, "Linked cells");
  await expect(reading(page)).toContainText("from the link, if it leads to the public internet");

  await fetchAndRead(page).click();

  await expect(summary(page)).toContainText("Read 1 of 1 chunk", { timeout: 15_000 });
  await expect(page.getByTestId("paper-agent-file")).toContainText("linked-paper.txt");
  const link = page.getByTestId("paper-agent-source").getByRole("link", { name: /Fetched from The page at example\.org/ });
  await expect(link).toHaveAttribute("href", "https://example.org/papers/fetched");
  await expect(page.getByRole("list", { name: "Software" })).toContainText("Seurat");
});

test("says why a paper could not be fetched, and reads the file that is uploaded in its place", async ({ page }) => {
  const id = await makeAgent(page, { title: "Closed cells", paper: { kind: "doi", doi: "10.1000/closed-cells" } });
  await openAgent(page, id, "Closed cells");

  await fetchAndRead(page).click();

  const why = "is not open access, so Europe PMC does not give out its full text. Upload the paper's file to have it read.";
  await expect(status(page).getByRole("alert")).toContainText(why, { timeout: 15_000 });
  await expect(page.getByTestId("paper-agent-step").filter({ hasText: "Read the paper" })).toContainText("Failed");
  await expect(page.getByTestId("paper-agent-file")).toHaveCount(0);
  // It can be asked for again, as a paper that could not be reached may be had later
  await expect(fetchAndRead(page)).toBeEnabled();
  expect(await accessibilityProblems(page)).toEqual([]);

  await page.getByLabel("Upload the paper").setInputFiles({ name: "closed.txt", mimeType: "text/plain", buffer: Buffer.from(CELLS) });
  await expect(page.getByTestId("paper-agent-file")).toContainText("closed.txt");
  await expect(page.getByTestId("paper-agent-step").filter({ hasText: "Read the paper" })).toContainText("Not started");
  await reading(page).getByRole("button", { name: "Read the paper", exact: true }).click();
  await expect(summary(page)).toContainText("Read 1 of 1 chunk", { timeout: 15_000 });
  await expect(page.getByRole("list", { name: "What the authors report" })).toContainText("0.93");
});

test("says why a link could not be read as a paper", async ({ page }) => {
  const id = await makeAgent(page, { title: "Walled cells", paper: { kind: "url", url: "https://example.org/closed" } });
  await openAgent(page, id, "Walled cells");

  await fetchAndRead(page).click();

  await expect(status(page).getByRole("alert")).toContainText("too little to be a paper", { timeout: 15_000 });
  await expect(status(page).getByRole("alert")).toContainText("Upload the paper's file to have it read.");
  await expect(page.getByTestId("paper-agent-file")).toHaveCount(0);
});

test("follows the fetching of a paper while it goes on, and keeps nothing if it is stopped", async ({ page }) => {
  const id = await makeAgent(page, { title: "Slow fetch", paper: { kind: "doi", doi: "10.1000/slow-cells" } });
  await openAgent(page, id, "Slow fetch");

  await fetchAndRead(page).click();

  await expect(status(page).getByRole("button", { name: "Stop: Fetching and reading the paper: Slow fetch" })).toBeVisible();
  await expect(reading(page).getByRole("button", { name: "Fetching…" })).toBeDisabled();
  // Nothing else is done to the agent while its paper is got
  await expect(page.getByLabel("Upload the paper")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Delete Slow fetch" })).toBeDisabled();

  await status(page).getByRole("button", { name: "Stop: Fetching and reading the paper: Slow fetch" }).click();

  await expect(status(page).getByText("Stopped", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("paper-agent-file")).toHaveCount(0);
  await expect(page.getByTestId("paper-agent-step").filter({ hasText: "Read the paper" })).toContainText("Not started");
  await expect(fetchAndRead(page)).toBeEnabled();
  expect((await (await page.request.get(`/api/paperagents/${id}`)).json()).paper.file ?? null).toBeNull();
});

test("does not make an agent of a link to this machine or a private network", async ({ page }) => {
  await page.goto("/papers");
  const making = form(page, "Make an agent");
  await making.getByRole("radio", { name: "A link" }).check();
  await making.getByLabel("Link to the paper").fill("http://192.168.0.7/paper");

  await making.getByRole("button", { name: "Make the agent" }).click();

  const problem = making.getByRole("alert");
  await expect(problem).toContainText("A link to a paper is to a site on the public internet, which 192.168.0.7 is not.");
  await expect(problem).toContainText("Upload the paper's file in place of a link to it");
  await expect(page).toHaveURL(/\/papers$/);
  expect((await (await page.request.get("/api/paperagents")).json()).agents).toEqual([]);
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("follows the reading of a paper while it goes on, stops it, and carries on", async ({ page }) => {
  const id = await makeAgent(page, { title: "Slow cells", paper: { kind: "file" } });
  await sendPaper(page, id, "slow.txt", chunked(3, "slow:"));
  await openAgent(page, id, "Slow cells");

  await reading(page).getByRole("button", { name: "Read the paper" }).click();

  await expect(status(page).getByRole("progressbar", { name: "Progress: Reading the paper: Slow cells" })).toBeVisible();
  await expect(status(page).getByText("0 of 3 chunks")).toBeVisible();
  await expect(page.getByTestId("paper-agent-step").filter({ hasText: "Read the paper" })).toContainText("Going on");
  // Nothing else is done to the agent while its paper is read
  await expect(reading(page).getByRole("button", { name: "Reading…" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Remove slow.txt" })).toBeDisabled();
  await expect(page.getByLabel("Upload it again")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Delete Slow cells" })).toBeDisabled();

  await expect(status(page).getByText("1 of 3 chunks")).toBeVisible({ timeout: 10_000 });
  await status(page).getByRole("button", { name: "Stop: Reading the paper: Slow cells" }).click();
  await expect(status(page).getByRole("button", { name: "Stopping: Reading the paper: Slow cells" })).toBeDisabled();

  await expect(status(page).getByRole("progressbar")).toHaveCount(0, { timeout: 15_000 });
  await expect(status(page).getByText("Stopped", { exact: true })).toBeVisible();
  // What was read is kept, and the rest is left for the next time
  await expect(summary(page)).toContainText(/Read [12] of 3 chunks/);
  await expect(page.getByTestId("paper-agent-step").filter({ hasText: "Read the paper" })).toContainText("Not started");
  const carry = reading(page).getByRole("button", { name: "Carry on reading" });
  await expect(carry).toBeEnabled();
  await expect(page.getByRole("button", { name: "Delete Slow cells" })).toBeEnabled();

  await carry.click();
  await expect(summary(page)).toContainText("Read 3 of 3 chunks", { timeout: 20_000 });
  await expect(page.getByTestId("paper-agent-step").filter({ hasText: "Read the paper" })).toContainText("Done");
  await expect(reading(page).getByRole("button", { name: "Read the paper" })).toBeDisabled();
});

test("stops reading at the limit, keeps what was read, and says what is wrong with a limit before it is sent", async ({ page }) => {
  const id = await makeAgent(page, { title: "Limited cells", paper: { kind: "file" } });
  await sendPaper(page, id, "limited.txt", chunked(3, "plain:"));
  await openAgent(page, id, "Limited cells");

  // The limit is always said, and is an amount
  await reading(page).getByLabel("Most it may spend, in dollars").fill("");
  await reading(page).getByRole("button", { name: "Read the paper" }).click();
  await expect(reading(page).getByText("Say the most it may spend.", { exact: true })).toBeVisible();
  await reading(page).getByLabel("Most it may spend, in dollars").fill("lots");
  await reading(page).getByRole("button", { name: "Read the paper" }).click();
  await expect(reading(page).getByText(/is an amount in dollars/)).toBeVisible();
  expect((await (await page.request.get(`/api/paperagents/${id}/reading`)).json()).chunks).toBeNull();

  // A reading that costs more than the limit is stopped after the chunk that went over it
  await reading(page).getByLabel("Most it may spend, in dollars").fill("0.0004");
  await reading(page).getByRole("button", { name: "Read the paper" }).click();
  await expect(status(page)).toContainText("Stopped at the limit", { timeout: 15_000 });
  await expect(summary(page)).toContainText("Read 1 of 3 chunks");
  await expect(reading(page).getByRole("button", { name: "Carry on reading" })).toBeEnabled();
  expect((await (await page.request.get(`/api/paperagents/${id}/reading`)).json())).toMatchObject({ read: 1, complete: false });
});

test("says which parts of a paper could not be read, and reads them again only when asked", async ({ page }) => {
  const id = await makeAgent(page, { title: "Refused cells", paper: { kind: "file" } });
  await sendPaper(page, id, "refused.txt", `${chunked(1, "plain:")}\n\n${chunked(1, "refuse:")}`);
  await openAgent(page, id, "Refused cells");

  await reading(page).getByRole("button", { name: "Read the paper" }).click();

  await expect(summary(page)).toContainText("1 could not be read", { timeout: 15_000 });
  await expect(summary(page)).toContainText("Read 1 of 2 chunks");
  const again = reading(page).getByLabel("Read again the parts that could not be read");
  await expect(again).toBeVisible();
  // The paper has been dealt with, so it is read again only if the parts that failed are asked for
  await expect(reading(page).getByRole("button", { name: "Read the paper" })).toBeDisabled();
  await again.check();
  await expect(reading(page).getByRole("button", { name: "Read the paper" })).toBeEnabled();
});

test("says why a paper could not be read, and why reading was refused", async ({ page }) => {
  const id = await makeAgent(page, { title: "Failing cells", paper: { kind: "file" } });
  await sendPaper(page, id, "failing.txt", chunked(1, "fail:"));
  await openAgent(page, id, "Failing cells");

  await reading(page).getByRole("button", { name: "Read the paper" }).click();

  await expect(status(page).getByRole("alert")).toContainText("The scripted model failed to read the paper", { timeout: 15_000 });
  await expect(page.getByTestId("paper-agent-step").filter({ hasText: "Read the paper" })).toContainText("Failed");

  await page.route("**/api/paperagents/*/reading", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: "missing_keys", message: "gpt-5.2 needs OPENAI_API_KEY, which is not set. Add it in the settings.", missing: ["OPENAI_API_KEY"] },
          }),
        })
      : route.fallback(),
  );
  await reading(page).getByRole("button", { name: /^(Read the paper|Carry on reading)$/ }).click();

  const problem = reading(page).getByRole("alert");
  await expect(problem).toContainText("gpt-5.2 needs OPENAI_API_KEY");
  await expect(problem.getByRole("button", { name: "Add the key" })).toBeVisible();
});

test("has nothing wrong that axe can find, in an agent that is being read, or that was", async ({ page }) => {
  const id = await makeAgent(page, { title: "Accessible reading", paper: { kind: "url", url: "https://example.org/accessible" } });
  await openAgent(page, id, "Accessible reading");
  await expect(fetchAndRead(page)).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);

  await sendPaper(page, id, "accessible.txt", chunked(2, "slow:"));
  await page.reload();
  await reading(page).getByRole("button", { name: "Read the paper" }).click();
  await expect(status(page).getByRole("progressbar")).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);

  await status(page).getByRole("button", { name: /^Stop: / }).click();
  await expect(status(page).getByRole("progressbar")).toHaveCount(0, { timeout: 15_000 });

  await page.request.delete(`/api/paperagents/${id}/reading`);
  await page.request.delete(`/api/paperagents/${id}/paper`);
  await sendPaper(page, id, "cells.txt", CELLS);
  await page.reload();
  await reading(page).getByRole("button", { name: "Read the paper" }).click();
  await expect(summary(page)).toContainText("Read 1 of 1 chunk", { timeout: 15_000 });
  expect(await accessibilityProblems(page)).toEqual([]);
});

// What the page says of an agent's code, which is fetched by a stand-in for Git that writes a small project for any address
const CODE_ADDRESS = "https://github.com/example/cellmapper";
const codeForm = (page: Page) => form(page, "Fetch the code");
const fetching = (page: Page) => page.getByRole("region", { name: "Fetching the code" });
const stock = (page: Page) => page.getByTestId("code-stock");
const stockRow = (page: Page, label: string) => stock(page).getByTestId("code-stock-row").filter({ has: page.locator(`xpath=preceding-sibling::dt[normalize-space()="${label}"]`) });
const header = (page: Page) => page.locator("p", { hasText: /^Code: example\/cellmapper/ });
const step = (page: Page, name: string) => page.getByTestId("paper-agent-step").filter({ hasText: name });

// Reads the paper of an agent through the server, and waits until that is done
async function readTheAgent(page: Page, id: string) {
  const started = await page.request.post(`/api/paperagents/${id}/reading`, { data: { max_cost: 2 } });
  expect(started.status()).toBe(202);
  await expect.poll(async () => (await (await page.request.get(`/api/paperagents/${id}/reading`)).json()).job, { timeout: 20_000 }).toBeNull();
}

// Fetches the code of an agent through the server, and waits until that is done
async function fetchTheCode(page: Page, id: string, data: Record<string, unknown> = {}) {
  const started = await page.request.post(`/api/paperagents/${id}/repository`, { data });
  expect(started.status()).toBe(202);
  await expect.poll(async () => (await (await page.request.get(`/api/paperagents/${id}/repository`)).json()).job, { timeout: 20_000 }).toBeNull();
}

test("offers the code that the paper points to, and fetches it at a commit, shows what was found and whether to go on, and takes it away", async ({
  page,
}) => {
  const id = await makeAgent(page, { title: "Code mapper", paper: { kind: "file" } });
  await sendPaper(page, id, "cells.txt", CELLS);
  await openAgent(page, id, "Code mapper");
  const section = page.getByRole("heading", { name: "Code", level: 2, exact: true });
  await expect(section).toBeVisible();
  // Until the paper is read, and where its code is is not said, there is nothing to fetch or to choose from
  await expect(page.getByText("Say where the code is, under Details below, or read the paper, which may say where it is.")).toBeVisible();
  await expect(codeForm(page)).toHaveCount(0);

  await reading(page).getByRole("button", { name: "Read the paper" }).click();
  await expect(summary(page)).toContainText("Read 1 of 1 chunk", { timeout: 15_000 });

  // The project that the paper's link leads to is offered with the words that say it, and is not fetched
  const candidate = page.getByTestId("code-candidate");
  await expect(candidate).toHaveCount(1);
  await expect(candidate).toContainText("example/cellmapper");
  await expect(candidate).toContainText("The paper says it is the code");
  await expect(candidate.getByRole("blockquote")).toHaveText(CODE);
  await expect(candidate).toContainText("Code availability");
  await expect(codeForm(page)).toHaveCount(0);
  expect((await (await page.request.get(`/api/paperagents/${id}/repository`)).json())).toMatchObject({ repo: null, cloned: false });
  expect(await accessibilityProblems(page)).toEqual([]);

  await candidate.getByRole("button", { name: "Use example/cellmapper as the code" }).click();

  await expect(candidate).toContainText("The code of this agent");
  await expect(candidate.getByRole("button", { name: /^Use / })).toHaveCount(0);
  expect((await (await page.request.get(`/api/paperagents/${id}`)).json()).repo).toEqual({ url: CODE_ADDRESS });
  await expect(codeForm(page)).toBeVisible();
  await expect(step(page, "Take stock of its code")).toContainText("Not started");

  // What is asked for is said before it is sent
  await codeForm(page).getByLabel("Branch, tag, or commit").fill("--upload-pack=x");
  await codeForm(page).getByLabel("Most to fetch, in megabytes").fill("5");
  await codeForm(page).getByRole("button", { name: "Fetch the code" }).click();
  await expect(codeForm(page).getByText("That is not the name of a branch or a tag, or a commit.")).toBeVisible();
  await expect(codeForm(page).getByText(/is a whole number from 10 to 1000/)).toBeVisible();
  expect((await (await page.request.get(`/api/paperagents/${id}/repository`)).json()).cloned).toBe(false);

  await codeForm(page).getByLabel("Branch, tag, or commit").fill("v1.2");
  await codeForm(page).getByLabel("Most to fetch, in megabytes").fill("50");
  await codeForm(page).getByRole("button", { name: "Fetch the code" }).click();

  await expect(page.getByTestId("code-commit")).toContainText("example/cellmapper at ", { timeout: 15_000 });
  await expect(page.getByTestId("code-commit")).toContainText("(v1.2)");
  await expect(fetching(page)).toContainText("Fetching the code and taking stock of it: Code mapper");
  await expect(fetching(page)).toContainText("Fetched ");
  await expect(codeForm(page)).toHaveCount(0);
  await expect(step(page, "Take stock of its code")).toContainText("Done");
  const kept = await (await page.request.get(`/api/paperagents/${id}/repository`)).json();
  expect(kept).toMatchObject({ cloned: true, intake: { url: CODE_ADDRESS, ref: "v1.2", limit_bytes: 50 * 1024 * 1024 } });
  await expect(page.getByTestId("code-commit")).toContainText(kept.intake.commit.slice(0, 12));
  // The commit is on the agent, so that it is the same code later
  await expect(header(page)).toContainText(`at commit ${kept.intake.commit.slice(0, 12)}`);

  // What was found, as rows
  await expect(stockRow(page, "Languages")).toContainText("Python (4 files)");
  await expect(stockRow(page, "Tutorials")).toContainText("1, of which 1 notebook");
  await expect(stockRow(page, "Tutorials")).toContainText("tutorials/quickstart.ipynb");
  await expect(stockRow(page, "Tests")).toContainText("1");
  await expect(stockRow(page, "What to install")).toContainText("requirements.txt (versions given)");
  await expect(stockRow(page, "License")).toContainText("MIT (permissive)");
  await expect(stockRow(page, "GPU")).toContainText("Used if there is one, and not needed");

  // Whether to go on, with each thing that was looked at, which says that nothing was run
  const verdict = page.getByTestId("code-preflight");
  await expect(page.getByTestId("code-verdict")).toHaveText("Go on");
  await expect(page.getByTestId("code-verdict-summary")).toContainText("Go:");
  await expect(verdict.getByTestId("code-check").filter({ hasText: /GPU/ })).toHaveAttribute("data-status", "note");
  await expect(verdict).toContainText("Nothing was run, so it does not say whether the code works");
  expect(kept.preflight.verdict).toBe("go");
  await expect(page.getByText("none of it was run", { exact: false })).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);

  // The commit is the same one if it is fetched again, and the fetching is one that the agent's step says is done
  await page.reload();
  await expect(page.getByTestId("code-commit")).toContainText(kept.intake.commit.slice(0, 12));

  // Taking the code away asks first, and leaves the address
  await page.getByRole("button", { name: "Take the code away" }).click();
  const asking = page.getByRole("alertdialog", { name: "Take away the code of Code mapper?" });
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  await expect(stock(page)).toBeVisible();
  await page.getByRole("button", { name: "Take the code away" }).click();
  await page.getByRole("alertdialog", { name: "Take away the code of Code mapper?" }).getByRole("button", { name: "Take away" }).click();

  await expect(stock(page)).toHaveCount(0);
  await expect(codeForm(page)).toBeVisible();
  await expect(page.getByTestId("code-preflight")).toHaveCount(0);
  await expect(fetching(page)).toHaveCount(0);
  await expect(step(page, "Take stock of its code")).toContainText("Not started");
  await expect(header(page)).not.toContainText("at commit");
  expect((await (await page.request.get(`/api/paperagents/${id}/repository`)).json())).toMatchObject({ cloned: false, intake: null, repo: { url: CODE_ADDRESS } });
  // What the paper was read as is kept
  await expect(page.getByRole("list", { name: "What the authors report" })).toContainText("0.93");
});

test("takes away the code that was fetched when its address is changed, and asks first when a project that the paper points to is used instead", async ({
  page,
}) => {
  const OLD = "https://github.com/example/oldmapper";
  const text = `${CODE}\n\nAn older version is at ${OLD} under the same license.`;
  const id = await makeAgent(page, { title: "Two projects", paper: { kind: "file" }, repo: OLD });
  await sendPaper(page, id, "two.txt", text);
  await readTheAgent(page, id);
  await fetchTheCode(page, id);
  await openAgent(page, id, "Two projects");
  await expect(page.getByTestId("code-commit")).toContainText("example/oldmapper at ");

  // Both are offered, with where each is from, and the one that is the code is said to be
  const candidates = page.getByTestId("code-candidate");
  await expect(candidates).toHaveCount(2);
  await expect(candidates.filter({ hasText: "example/oldmapper" })).toContainText("The code of this agent");
  await expect(candidates.filter({ hasText: "example/oldmapper" }).getByRole("button", { name: /^Use / })).toHaveCount(0);

  // Using the other takes away what was fetched, so it is asked
  await candidates.filter({ hasText: "example/cellmapper" }).getByRole("button", { name: "Use example/cellmapper as the code" }).click();
  const asking = page.getByRole("alertdialog", { name: "Use example/cellmapper as the code?" });
  await expect(asking).toContainText("This takes away the code that was fetched from example/oldmapper");
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  expect((await (await page.request.get(`/api/paperagents/${id}`)).json()).repo.url).toBe(OLD);
  await expect(page.getByTestId("code-commit")).toBeVisible();

  await candidates.filter({ hasText: "example/cellmapper" }).getByRole("button", { name: "Use example/cellmapper as the code" }).click();
  await page.getByRole("alertdialog", { name: "Use example/cellmapper as the code?" }).getByRole("button", { name: "Use it" }).click();

  await expect(page.getByTestId("code-commit")).toHaveCount(0);
  await expect(codeForm(page)).toBeVisible();
  await expect(candidates.filter({ hasText: "example/cellmapper" })).toContainText("The code of this agent");
  await expect(step(page, "Take stock of its code")).toContainText("Not started");
  expect(await (await page.request.get(`/api/paperagents/${id}/repository`)).json()).toMatchObject({ cloned: false, repo: { url: CODE_ADDRESS } });

  // Saying another address under Details does the same
  await fetchTheCode(page, id);
  await page.reload();
  await expect(page.getByTestId("code-commit")).toContainText("example/cellmapper at ");
  await expect(page.getByText("Changing it takes away the code that was fetched from the old address.")).toBeVisible();
  await page.getByLabel("Where its code is").fill(OLD);
  await form(page, "What the agent is").getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByTestId("code-commit")).toHaveCount(0);
  await expect(codeForm(page)).toBeVisible();
});

test("follows the fetching of code while it goes on, and keeps nothing if it is stopped, and says why code could not be fetched", async ({
  page,
}) => {
  const id = await makeAgent(page, { title: "Slow code", paper: { kind: "doi", doi: "10.1000/slow-code" }, repo: "https://github.com/example/slow-code" });
  await openAgent(page, id, "Slow code");
  await codeForm(page).getByRole("button", { name: "Fetch the code" }).click();

  await expect(fetching(page).getByRole("button", { name: "Stop: Fetching the code and taking stock of it: Slow code" })).toBeVisible();
  await expect(step(page, "Take stock of its code")).toContainText("Going on");
  await expect(codeForm(page).getByRole("button", { name: "Fetching…" })).toBeDisabled();
  // Nothing else is done to the agent while its code is fetched, and its paper is not read
  await expect(fetchAndRead(page)).toBeDisabled();
  await expect(reading(page)).toContainText("The code is being fetched. Reading waits for that.");
  await expect(page.getByRole("button", { name: "Delete Slow code" })).toBeDisabled();
  await expect(page.getByLabel("Upload the paper")).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);

  await fetching(page).getByRole("button", { name: "Stop: Fetching the code and taking stock of it: Slow code" }).click();

  await expect(fetching(page).getByText("Stopped", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(stock(page)).toHaveCount(0);
  await expect(step(page, "Take stock of its code")).toContainText("Not started");
  await expect(codeForm(page).getByRole("button", { name: "Fetch the code" })).toBeEnabled();
  await expect(fetchAndRead(page)).toBeEnabled();
  expect((await (await page.request.get(`/api/paperagents/${id}/repository`)).json())).toMatchObject({ cloned: false, intake: null, job: null });

  // A project that is not there, and one that is more than what was asked to be fetched, are said so, with what to do
  for (const [name, address, words] of [
    ["Missing code", "https://github.com/example/missing-code", "was not found, or it is not public"],
    ["Huge code", "https://github.com/example/huge-code", "is bigger than the 50 megabytes that were asked to be fetched"],
  ]) {
    const other = await makeAgent(page, { title: name, paper: { kind: "file" }, repo: address });
    await openAgent(page, other, name);
    await codeForm(page).getByLabel("Most to fetch, in megabytes").fill("50");
    await codeForm(page).getByRole("button", { name: "Fetch the code" }).click();

    await expect(fetching(page).getByRole("alert")).toContainText(words, { timeout: 15_000 });
    await expect(step(page, "Take stock of its code")).toContainText("Failed");
    await expect(codeForm(page).getByRole("button", { name: "Fetch the code" })).toBeEnabled();
    expect(await accessibilityProblems(page)).toEqual([]);
  }
});

test("says why code was not fetched when the server refuses, and that Git is not installed when it is not", async ({ page }) => {
  const id = await makeAgent(page, { title: "Refused code", paper: { kind: "file" }, repo: CODE_ADDRESS });
  await openAgent(page, id, "Refused code");
  await page.route("**/api/paperagents/*/repository", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "git_missing", message: "Git is not installed on this machine, and fetching code takes it." } }),
        })
      : route.fallback(),
  );
  await codeForm(page).getByRole("button", { name: "Fetch the code" }).click();
  await expect(codeForm(page).getByRole("alert")).toContainText("Git is not installed on this machine");
  await page.unroute("**/api/paperagents/*/repository");

  // Code that was fetched a moment before the page looked is not a reason to refuse: the page looks again
  let looked = 0;
  await page.route("**/api/paperagents/*/repository", (route) => {
    if (route.request().method() === "GET") looked += 1;

    return route.request().method() === "POST"
      ? route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "done", message: "The code has been fetched. Remove it to fetch it again." } }),
        })
      : route.fallback();
  });
  const before = looked;
  await codeForm(page).getByRole("button", { name: "Fetch the code" }).click();
  await expect.poll(() => looked).toBeGreaterThan(before);
  await expect(codeForm(page).getByRole("alert")).toHaveCount(0);
  await page.unroute("**/api/paperagents/*/repository");

  await page.route("**/api/paperagents/*/repository", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();

    return route.fulfill({ response, json: { ...(await response.json()), git: false } });
  });
  await page.reload();
  await expect(page.getByText("Git is not installed on this machine, and fetching code takes it. Install it to fetch the code.")).toBeVisible();
  await expect(codeForm(page).getByRole("button", { name: "Fetch the code" })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("says that code needs a GPU and may not be used for money, which is advice that stops short of deciding, and has nothing wrong that axe can find", async ({
  page,
}) => {
  const id = await makeAgent(page, { title: "Gpu code", paper: { kind: "file" }, repo: "https://github.com/example/gpu-mapper" });
  await fetchTheCode(page, id);
  await openAgent(page, id, "Gpu code");

  await expect(page.getByTestId("code-verdict")).toHaveText("Do not go on");
  await expect(page.getByTestId("code-verdict-summary")).toContainText("It needs a GPU");
  const checks = page.getByTestId("code-check");
  // What stops it is first, and each check says how it came out in words and not only by its icon
  await expect(checks.first()).toHaveAttribute("data-status", "block");
  await expect(checks.first()).toContainText("(Stops it)");
  await expect(page.locator("[data-testid=code-check][data-status=block]")).toHaveCount(1);
  await expect(stockRow(page, "GPU")).toContainText("Needed");
  await expect(stockRow(page, "License")).toContainText("non-commercial");
  await expect(stockRow(page, "Tutorials")).toContainText("None");
  expect(await accessibilityProblems(page)).toEqual([]);

  // The advice is in the agent's own words, from its files, for the person who decides
  await expect(page.getByTestId("code-preflight")).toContainText("You decide.");
  const fetched = await (await page.request.get(`/api/paperagents/${id}/repository`)).json();
  expect(fetched.preflight.verdict).toBe("no-go");
});

// What the page says of the environment of an agent's code, which is built by a stand-in for Docker that keeps images by their names
const environmentForm = (page: Page) => form(page, "Build the environment");
const building = (page: Page) => page.getByRole("region", { name: "Building the environment" });
const plan = (page: Page) => page.getByTestId("environment-plan");
const built = (page: Page) => page.getByTestId("environment-built");
const failure = (page: Page) => page.getByTestId("environment-failure");
const environmentOf = async (page: Page, id: string) => (await page.request.get(`/api/paperagents/${id}/environment`)).json();

// Makes an agent whose code is fetched, so that what a test is about is its environment, and opens it
async function agentWithCode(page: Page, title: string, repo = CODE_ADDRESS, paper: Record<string, unknown> = { kind: "file" }): Promise<string> {
  const id = await makeAgent(page, { title, paper, repo });
  await fetchTheCode(page, id);
  await openAgent(page, id, title);

  return id;
}

test("says what would be built from the code, asks for what is wrong with the asking to be put right, builds it, and shows what was built and how far that is known", async ({
  page,
}) => {
  const id = await makeAgent(page, { title: "Plain env", paper: { kind: "file" }, repo: CODE_ADDRESS });
  await openAgent(page, id, "Plain env");
  const section = page.getByRole("heading", { name: "Environment", level: 2, exact: true });
  await expect(section).toBeVisible();
  // Until the code is fetched, there are no files to build from
  await expect(page.getByText("Fetch the code first. The environment is built from the files in it.")).toBeVisible();
  await expect(environmentForm(page)).toHaveCount(0);
  await expect(step(page, "Build what the code needs")).toContainText("Not started");

  await fetchTheCode(page, id);
  await page.reload();
  await expect(plan(page)).toBeVisible();
  await expect(plan(page)).toContainText("pip, from requirements.txt");
  await expect(plan(page)).toContainText("Starting from");
  await expect(plan(page).getByRole("list", { name: "Steps of the build" })).toContainText("requirements.txt");
  await expect(plan(page)).toContainText("none of this machine in it");
  await expect(page.getByTestId("environment-python")).toContainText(/^\d+\.\d+, as /);
  expect((await environmentOf(page, id)).built).toBeNull();
  expect(await accessibilityProblems(page)).toEqual([]);

  // What is asked for is said before it is sent
  await environmentForm(page).getByLabel("System packages to install first").fill("Not_A_Package libhdf5-dev");
  await environmentForm(page).getByLabel("Most time, in minutes").fill("0");
  await environmentForm(page).getByLabel("Most disk, in gigabytes").fill("500");
  await environmentForm(page).getByRole("button", { name: "Build the environment" }).click();
  await expect(environmentForm(page).getByText('"Not_A_Package" is not the name of a Debian package')).toBeVisible();
  await expect(environmentForm(page).getByText(/is a whole number from 1 to 180/)).toBeVisible();
  await expect(environmentForm(page).getByText(/is a whole number from 1 to 40/)).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  expect((await environmentOf(page, id)).built).toBeNull();

  await environmentForm(page).getByLabel("System packages to install first").fill("libhdf5-dev, pkg-config");
  await environmentForm(page).getByLabel("Most time, in minutes").fill("20");
  await environmentForm(page).getByLabel("Most disk, in gigabytes").fill("8");
  await environmentForm(page).getByLabel("Python").selectOption("3.10");
  await environmentForm(page).getByRole("button", { name: "Build the environment" }).click();

  await expect(built(page)).toBeVisible({ timeout: 20_000 });
  await expect(plan(page)).toHaveCount(0);
  await expect(environmentForm(page)).toHaveCount(0);
  await expect(page.getByTestId("environment-built-python")).toHaveText("3.10.9");
  await expect(page.getByTestId("environment-built-packages")).toContainText("2, listed with their exact versions (pip freeze)");
  await expect(page.getByTestId("environment-built-image")).toContainText("which is the hash of what is in it");
  await expect(page.getByTestId("environment-built-check")).toContainText("pip check finds nothing wrong");
  await expect(built(page)).toContainText("libhdf5-dev, pkg-config");
  await expect(built(page)).toContainText("20 minutes and 8 GB of disk");
  await expect(page.getByTestId("environment-built-when")).toContainText("Built ");
  await expect(step(page, "Build what the code needs")).toContainText("Done");
  // It says what is not known, which is that the code runs
  await expect(built(page)).toContainText("All that is known is that this was built and starts. It does not say that the code runs");
  const kept = await environmentOf(page, id);
  expect(kept).toMatchObject({
    built: { python: "3.10.9", recipe: { python: "3.10", system_packages: ["libhdf5-dev", "pkg-config"] }, limits: { minutes: 20, gigabytes: 8 }, image_present: true },
    failure: null,
    job: null,
  });
  await expect(page.getByTestId("environment-built-image")).toContainText(kept.built.image.id.replace("sha256:", "").slice(0, 12));
  expect(await accessibilityProblems(page)).toEqual([]);

  // The exact versions, and what the build printed, are looked at when they are asked for
  await built(page).getByRole("button", { name: "Show the exact versions" }).click();
  await expect(page.getByRole("region", { name: "the exact versions" })).toContainText("scanpy==1.9.3");
  await expect(built(page)).toContainText("Kept as pip-freeze.txt.");
  await built(page).getByRole("button", { name: "Show what the build printed" }).click();
  await expect(page.getByRole("region", { name: "what the build printed" })).toContainText("Starting from python:3.10-slim");
  expect(await accessibilityProblems(page)).toEqual([]);
  await built(page).getByRole("button", { name: "Hide the exact versions" }).click();
  await expect(page.getByRole("region", { name: "the exact versions" })).toHaveCount(0);

  // It is the same environment after the page is looked at again, and cannot be built a second time on top of itself
  await page.reload();
  await expect(built(page)).toBeVisible();
  await expect(page.getByTestId("environment-built-image")).toContainText(kept.built.image.id.replace("sha256:", "").slice(0, 12));
  const again = await page.request.post(`/api/paperagents/${id}/environment`, { data: {} });
  expect(again.status()).toBe(409);

  // Taking it away asks first, takes the image away, and leaves the code
  await built(page).getByRole("button", { name: "Take the environment away" }).click();
  const asking = page.getByRole("alertdialog", { name: "Take away the environment of Plain env?" });
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  await expect(built(page)).toBeVisible();
  await built(page).getByRole("button", { name: "Take the environment away" }).click();
  await page.getByRole("alertdialog", { name: "Take away the environment of Plain env?" }).getByRole("button", { name: "Take away" }).click();

  await expect(built(page)).toHaveCount(0);
  await expect(plan(page)).toBeVisible();
  await expect(environmentForm(page)).toBeVisible();
  await expect(step(page, "Build what the code needs")).toContainText("Not started");
  expect(await environmentOf(page, id)).toMatchObject({ built: null, failure: null });
  await expect(page.getByTestId("code-commit")).toBeVisible();
});

test("follows a build while it goes on, waits for it before anything else is done to the agent, and keeps nothing if it is stopped", async ({
  page,
}) => {
  const id = await agentWithCode(page, "Slow env", CODE_ADDRESS, { kind: "doi", doi: "10.1000/env-paper" });
  await environmentForm(page).getByRole("button", { name: "Build the environment" }).click();

  const stop = building(page).getByRole("button", { name: "Stop: Building the environment: Slow env" });
  await expect(stop).toBeVisible();
  await expect(step(page, "Build what the code needs")).toContainText("Going on");
  await expect(environmentForm(page).getByRole("button", { name: "Building…" })).toBeDisabled();
  // What it prints is shown as it goes
  const printed = page.getByRole("log", { name: "What this printed: Building the environment: Slow env" });
  await expect(printed).toContainText("Collecting package-0", { timeout: 10_000 });
  await expect(printed).toContainText("Starting from python:");
  // Nothing else is done to the agent while it goes on, and its paper is not read
  await expect(fetchAndRead(page)).toBeDisabled();
  await expect(reading(page)).toContainText("The environment is being built. Reading waits for that.");
  await expect(page.getByRole("button", { name: "Delete Slow env" })).toBeDisabled();
  await expect(page.getByLabel("Upload the paper")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Take the code away" })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);

  await stop.click();

  await expect(building(page).getByText("Stopped", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(built(page)).toHaveCount(0);
  await expect(failure(page)).toHaveCount(0);
  await expect(step(page, "Build what the code needs")).toContainText("Not started");
  await expect(environmentForm(page).getByRole("button", { name: "Build the environment" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Take the code away" })).toBeEnabled();
  await expect(fetchAndRead(page)).toBeEnabled();
  expect(await environmentOf(page, id)).toMatchObject({ built: null, failure: null, job: null });
  expect(await accessibilityProblems(page)).toEqual([]);

  // A build that is begun again, and is left to end, is the one that is kept
  await environmentForm(page).getByRole("button", { name: "Build the environment" }).click();
  await expect(built(page)).toBeVisible({ timeout: 25_000 });
  await expect(building(page).getByText("Stopped", { exact: true })).toHaveCount(0);
});

test("says why a build failed, in what it printed, suggests what to ask for, and builds when that is asked", async ({ page }) => {
  const id = await agentWithCode(page, "Zlib env");
  await environmentForm(page).getByRole("button", { name: "Build the environment" }).click();

  await expect(failure(page)).toBeVisible({ timeout: 20_000 });
  await expect(failure(page)).toHaveAttribute("data-kind", "missing_system_library");
  await expect(page.getByTestId("environment-failure-detail")).toContainText("zlib.h");
  await expect(failure(page)).toContainText("It was at the step");
  await expect(failure(page)).toContainText("This is the likeliest reason");
  await expect(step(page, "Build what the code needs")).toContainText("Failed");
  await expect(page.getByRole("region", { name: "The end of what the step printed" })).toContainText("fatal error: zlib.h: No such file or directory");
  // The form is there to try again, and the plan, which is what would be built
  await expect(environmentForm(page)).toBeVisible();
  await expect(plan(page)).toBeVisible();
  await expect(built(page)).toHaveCount(0);
  const stored = await environmentOf(page, id);
  expect(stored.built).toBeNull();
  expect(stored.failure.failure).toMatchObject({ kind: "missing_system_library", system_packages: ["zlib1g-dev"] });
  expect(await accessibilityProblems(page)).toEqual([]);

  // Everything that was printed is kept, and is looked at when asked
  await failure(page).getByRole("button", { name: "Show everything the build printed" }).click();
  await expect(page.getByRole("region", { name: "everything the build printed" })).toContainText("Starting from python:");

  // The suggestion fills in the form, and does not send it
  await expect(environmentForm(page).getByLabel("System packages to install first")).toHaveValue("");
  await failure(page).getByRole("button", { name: "Fill in the form to install zlib1g-dev" }).click();
  await expect(environmentForm(page).getByLabel("System packages to install first")).toHaveValue("zlib1g-dev");
  await expect(failure(page).getByRole("button", { name: /^Fill in the form/ })).toHaveCount(0);
  expect((await environmentOf(page, id)).job).toBeNull();

  await environmentForm(page).getByRole("button", { name: "Build the environment" }).click();

  await expect(built(page)).toBeVisible({ timeout: 20_000 });
  await expect(failure(page)).toHaveCount(0);
  await expect(built(page)).toContainText("zlib1g-dev");
  await expect(step(page, "Build what the code needs")).toContainText("Done");
  expect((await environmentOf(page, id)).failure).toBeNull();
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("suggests another Python for a build that failed for the one it used, and says plainly when it has nothing to say of why", async ({ page }) => {
  const id = await agentWithCode(page, "Oldpython env");
  await environmentForm(page).getByRole("button", { name: "Build the environment" }).click();

  await expect(failure(page)).toHaveAttribute("data-kind", "python_mismatch", { timeout: 20_000 });
  await failure(page).getByRole("button", { name: "Fill in the form to use Python 3.9" }).click();
  await expect(environmentForm(page).getByLabel("Python")).toHaveValue("3.9");
  await environmentForm(page).getByRole("button", { name: "Build the environment" }).click();
  await expect(page.getByTestId("environment-built-python")).toHaveText("3.9.9", { timeout: 20_000 });
  expect((await environmentOf(page, id)).built.recipe.python).toBe("3.9");

  const other = await agentWithCode(page, "Broken env");
  await environmentForm(page).getByRole("button", { name: "Build the environment" }).click();
  await expect(failure(page)).toHaveAttribute("data-kind", "failed", { timeout: 20_000 });
  await expect(failure(page).getByRole("button", { name: /^Fill in the form/ })).toHaveCount(0);
  await expect(failure(page)).toContainText("The output says more.");
  await expect(environmentForm(page)).toBeVisible();
  expect((await environmentOf(page, other)).failure.failure.kind).toBe("failed");
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("says that code is not built here when no file says how, and that Docker is not running when it is not", async ({ page }) => {
  const id = await agentWithCode(page, "Bare env", "https://github.com/example/bare-mapper");

  await expect(page.getByTestId("environment-unsupported")).toHaveAttribute("data-kind", "no_environment");
  await expect(page.getByTestId("environment-unsupported")).toContainText("It is not built here");
  await expect(page.getByTestId("environment-unsupported")).toContainText("Nothing is guessed from the README.");
  await expect(environmentForm(page)).toHaveCount(0);
  await expect(plan(page)).toHaveCount(0);
  const refused = await page.request.post(`/api/paperagents/${id}/environment`, { data: {} });
  expect(refused.status()).toBe(422);
  expect(await accessibilityProblems(page)).toEqual([]);

  const other = await agentWithCode(page, "Stopped docker");
  await page.route("**/api/paperagents/*/environment", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();
    const body = await response.json();

    return route.fulfill({ response, json: { ...body, docker: { ready: false, message: "Docker is installed but is not running." } } });
  });
  await page.reload();
  await expect(page.getByText("Docker is installed but is not running. Building takes it.")).toBeVisible();
  await expect(plan(page)).toBeVisible();
  await expect(environmentForm(page).getByRole("button", { name: "Build the environment" })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);
  expect((await environmentOf(page, other)).docker).toBeDefined();
});

test("says why the server refused to build, and looks again when what the page shows is out of date", async ({ page }) => {
  const id = await agentWithCode(page, "Refused env");
  await page.route("**/api/paperagents/*/environment", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "docker_missing", message: "Docker is not installed on this machine, and building takes it." } }),
        })
      : route.fallback(),
  );
  await environmentForm(page).getByRole("button", { name: "Build the environment" }).click();
  await expect(environmentForm(page).getByRole("alert")).toContainText("Docker is not installed on this machine");
  await page.unroute("**/api/paperagents/*/environment");

  // An environment that was built a moment before the page looked is not a reason to refuse: the page looks again
  let looked = 0;
  await page.route("**/api/paperagents/*/environment", (route) => {
    if (route.request().method() === "GET") looked += 1;

    return route.request().method() === "POST"
      ? route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "done", message: "The environment has been built. Take it away to build it again." } }),
        })
      : route.fallback();
  });
  const before = looked;
  await environmentForm(page).getByRole("button", { name: "Build the environment" }).click();
  await expect.poll(() => looked).toBeGreaterThan(before);
  await expect(environmentForm(page).getByRole("alert")).toHaveCount(0);
  await page.unroute("**/api/paperagents/*/environment");
  expect((await environmentOf(page, id)).built).toBeNull();
});

// What the page says of the data of an agent's paper, which is listed and fetched by stand-ins for the places it is kept at (see
// scripted_server.py): Zenodo record 1000001 has a file that is corrupt, one with no checksum, and one that is restricted, 1000002
// a file that is more than is fetched at first, 1000003 a file that is slow to be sent, and GEO series GSE123456 files with no checksum
const ZENODO_LINKS = [
  "The processed counts are at https://zenodo.org/records/1000001.",
  "A larger atlas is at https://zenodo.org/records/1000002.",
  "A slow one is at https://zenodo.org/records/1000003.",
  "More data are kept at https://osf.io/abcde.",
];
const DATA_PAPER = CELLS.replace(DATA, [DATA, ...ZENODO_LINKS].join("\n\n"));
const dataOf = async (page: Page, id: string) => (await page.request.get(`/api/paperagents/${id}/data`)).json();
const dataHeading = (page: Page) => page.getByRole("heading", { name: "Data", level: 2, exact: true });
const datasets = (page: Page) => page.getByRole("list", { name: "Datasets the paper names" });
const places = (page: Page) => page.getByRole("list", { name: "Places the paper names for its data" });
const placeNamed = (page: Page, label: string) => places(page).getByTestId("data-candidate").filter({ hasText: label });
const listing = (page: Page) => page.getByTestId("data-files");
const fileOf = (page: Page, name: string) => listing(page).getByTestId("data-file").filter({ has: page.getByText(name, { exact: true }) });
const choosing = (page: Page) => form(page, "Fetch the files that are chosen");
const gettingData = (page: Page) => page.getByRole("region", { name: "Fetching the data" });
const keptData = (page: Page) => page.getByTestId("data-kept");
const keptSource = (page: Page, label: string) => page.getByTestId("data-kept-source").filter({ hasText: label });

// Makes an agent whose paper is a file that says where its data is, which is read if it is to be, and opens it
async function agentWithData(page: Page, title: string, read = true): Promise<string> {
  const id = await makeAgent(page, { title, paper: { kind: "file" } });
  await sendPaper(page, id, "cells.txt", DATA_PAPER);
  if (read) await readTheAgent(page, id);
  await openAgent(page, id, title);

  return id;
}

// Looks at what a place has, by the button of a place that the paper names
async function seeFilesOf(page: Page, label: string) {
  await placeNamed(page, label).getByRole("button", { name: `See the files of ${label}` }).click();
  await expect(listing(page)).toBeVisible();
  await expect(listing(page).getByRole("heading", { level: 3 })).toContainText(label);
}

// Fetches files of a place through the server, as the page does, and waits until that is done
async function fetchDataThrough(page: Page, id: string, reference: string, names: string[]) {
  const seen = await (await page.request.get(`/api/paperagents/${id}/data/files?reference=${encodeURIComponent(reference)}`)).json();
  const bytes = seen.files.filter((file: { name: string }) => names.includes(file.name)).reduce((sum: number, file: { bytes: number }) => sum + file.bytes, 0);
  const started = await page.request.post(`/api/paperagents/${id}/data`, { data: { reference, files: names, expected_bytes: bytes, max_megabytes: 500 } });
  expect(started.status()).toBe(202);
  await expect.poll(async () => (await dataOf(page, id)).job, { timeout: 20_000 }).toBeNull();
}

test("shows where the paper says its data is, what each place has before anything is chosen, and fetches nothing until the files are chosen and agreed to", async ({
  page,
}) => {
  test.slow();
  const id = await agentWithData(page, "Data mapper");
  await expect(dataHeading(page)).toBeVisible();
  await expect(page.getByText("Nothing is fetched until you have seen what a place has")).toBeVisible();
  await expect(step(page, "Get the data")).toContainText("Not started");
  await expect(page.getByText("No data has been fetched for this agent.")).toBeVisible();

  // The dataset the paper names is shown with its words, and the place its accession is of
  const named = datasets(page).getByTestId("data-dataset");
  await expect(named).toHaveCount(1);
  await expect(named).toContainText("GSE123456");
  await expect(named.getByRole("blockquote")).toHaveText(DATA);
  await expect(named).toContainText("Its accession is of GEO series GSE123456.");

  // The places the paper names are each once: those that are fetched from, with what the paper says, and one that is not
  await expect(places(page).getByTestId("data-candidate")).toHaveCount(5);
  const zenodo = placeNamed(page, "Zenodo record 1000001");
  await expect(zenodo).toContainText("Named in the paper");
  await expect(zenodo).toContainText("Nothing fetched yet");
  await expect(zenodo.getByRole("blockquote")).toHaveText(ZENODO_LINKS[0]);
  await expect(zenodo.getByRole("link", { name: /Zenodo record 1000001/ })).toHaveAttribute("href", "https://zenodo.org/records/1000001");
  const other = placeNamed(page, "Data at osf.io");
  await expect(other).toContainText("Not fetched from here");
  await expect(other).toContainText("osf.io is not one of the places that data is fetched from here");
  await expect(other.getByRole("button")).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  // Looking at a place asks it what it has, and fetches none of it
  await seeFilesOf(page, "Zenodo record 1000001");
  await expect(listing(page)).toContainText("Nuclei of the mouse hippocampus");
  await expect(page.getByTestId("data-license")).toHaveText("Licensed as cc-by-4.0. 5 files in all.");
  await expect(listing(page).getByTestId("data-file")).toHaveCount(5);
  await expect(fileOf(page, "counts.csv")).toContainText("MD5 checksum given, which it is checked by");
  await expect(fileOf(page, "README.txt")).toContainText("No checksum is given, so it is checked by its size only");
  await expect(fileOf(page, "restricted.zip")).toContainText("Zenodo does not give this file to everyone");
  await expect(listing(page).getByRole("checkbox", { name: "restricted.zip", exact: true })).toBeDisabled();
  await expect(page.getByTestId("data-chosen")).toHaveText("No files are chosen.");
  expect((await dataOf(page, id)).kept.sources).toEqual([]);
  expect(await accessibilityProblems(page)).toEqual([]);

  // What is wrong with the asking is said before anything is sent
  await choosing(page).getByRole("button", { name: "Fetch the files that are chosen" }).click();
  await expect(choosing(page).getByText("Choose at least one file.")).toBeVisible();
  await listing(page).getByRole("checkbox", { name: "counts.csv", exact: true }).check();
  await listing(page).getByRole("checkbox", { name: "metadata.tsv", exact: true }).check();
  await expect(page.getByTestId("data-chosen")).toContainText("2 files chosen, ");
  await choosing(page).getByLabel("Most to fetch, in megabytes").fill("0");
  await choosing(page).getByRole("button", { name: "Fetch the files that are chosen" }).click();
  await expect(choosing(page).getByText("The most to fetch, in megabytes, is a whole number from 1 to 20000.")).toBeVisible();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  // It says what it will do, how far each file is checked, and does nothing if that is not agreed to
  await choosing(page).getByLabel("Most to fetch, in megabytes").fill("5");
  await choosing(page).getByRole("button", { name: "Fetch the files that are chosen" }).click();
  const asking = page.getByRole("alertdialog", { name: /^Fetch 2 files, .*, from Zenodo record 1000001\?$/ });
  await expect(asking).toContainText("2 files will be checked by the checksum that the place gives.");
  await expect(asking).not.toContainText("size only");
  await expect(asking).toContainText("A file that does not match is thrown away, and fetching stops at 5 MB.");
  await expect(asking).toContainText("kept in a folder for this place under data/ in this agent's folder");
  // The dialog is looked at once it has finished appearing, as what is half faded in has less contrast than it will
  await expect(asking).toHaveCSS("opacity", "1");
  expect(await accessibilityProblems(page)).toEqual([]);
  await asking.getByRole("button", { name: "Do not fetch" }).click();
  await expect(asking).toHaveCount(0);
  expect((await dataOf(page, id)).kept.sources).toEqual([]);
  expect((await dataOf(page, id)).job).toBeNull();

  await choosing(page).getByRole("button", { name: "Fetch the files that are chosen" }).click();
  await page.getByRole("alertdialog", { name: /^Fetch 2 files/ }).getByRole("button", { name: "Fetch", exact: true }).click();

  // The files are kept, with how far each was checked, and the step is done
  await expect(keptData(page)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("data-kept-total")).toHaveText(/^2 files, /);
  const source = keptSource(page, "Zenodo record 1000001");
  await expect(source).toContainText("Licensed as cc-by-4.0. Kept in data/zenodo/1000001/.");
  const kept = source.getByTestId("data-kept-file");
  await expect(kept).toHaveCount(2);
  await expect(kept.filter({ hasText: "counts.csv" })).toContainText("Matched the MD5 that the place gave");
  await expect(kept.filter({ hasText: "counts.csv" })).toContainText(/SHA-256 [0-9a-f]{12}…/);
  await expect(keptData(page)).toContainText("it says the file is what the place has, and not that the data is what the paper used");
  await expect(step(page, "Get the data")).toContainText("Done");
  await expect(gettingData(page)).toContainText("Kept 2 files");
  await expect(placeNamed(page, "Zenodo record 1000001")).toContainText("2 files kept");
  const stored = await dataOf(page, id);
  expect(stored.kept.sources[0].files.map((file: { name: string; present: boolean }) => [file.name, file.present])).toEqual([
    ["counts.csv", true],
    ["metadata.tsv", true],
  ]);
  expect(stored.kept.sources[0].files[0].checksum).toMatchObject({ algorithm: "md5" });
  expect(await accessibilityProblems(page)).toEqual([]);

  // The place is looked at again, which says what is kept already, and leaves it out of what can be chosen
  await seeFilesOf(page, "Zenodo record 1000001");
  await expect(fileOf(page, "counts.csv")).toContainText("Kept already");
  await expect(listing(page).getByRole("checkbox", { name: "counts.csv", exact: true })).toBeDisabled();
  await expect(listing(page).getByRole("checkbox", { name: "labels.csv", exact: true })).toBeEnabled();
  await listing(page).getByRole("button", { name: "Choose all that can be fetched" }).click();
  await expect(page.getByTestId("data-chosen")).toContainText("2 files chosen, ");
  await listing(page).getByRole("button", { name: "Choose none" }).click();
  await expect(page.getByTestId("data-chosen")).toHaveText("No files are chosen.");

  // It is the same after the page is looked at again
  await page.reload();
  await expect(keptSource(page, "Zenodo record 1000001").getByTestId("data-kept-file")).toHaveCount(2);
  await expect(step(page, "Get the data")).toContainText("Done");
});

test("throws away a file that is not what its place says it is, keeps what is, and says how far each was checked", async ({ page }) => {
  const id = await agentWithData(page, "Corrupt data");
  await seeFilesOf(page, "Zenodo record 1000001");
  await listing(page).getByRole("checkbox", { name: "labels.csv", exact: true }).check();
  await listing(page).getByRole("checkbox", { name: "README.txt", exact: true }).check();
  await choosing(page).getByRole("button", { name: "Fetch the files that are chosen" }).click();
  const asking = page.getByRole("alertdialog", { name: /^Fetch 2 files/ });
  await expect(asking).toContainText("1 file will be checked by the checksum that the place gives.");
  await expect(asking).toContainText("1 file will be checked by their size only, since the place gives no checksum.");
  await asking.getByRole("button", { name: "Fetch", exact: true }).click();

  // The file that is wrong is said to be, with both checksums, and is not kept; the other is, as checked by its size only
  await expect(gettingData(page).getByText("Failed", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(gettingData(page).getByRole("alert")).toContainText("1 of 2 files were kept, and 1 were not.");
  await expect(gettingData(page).getByRole("alert")).toContainText("labels.csv is not what Zenodo says it is");
  await expect(gettingData(page).getByRole("alert")).toContainText("It was discarded.");
  const kept = keptSource(page, "Zenodo record 1000001").getByTestId("data-kept-file");
  await expect(kept).toHaveCount(1);
  await expect(kept).toContainText("README.txt");
  await expect(kept).toContainText("Checked by its size only, since the place gave no checksum");
  await expect(keptData(page)).not.toContainText("labels.csv");
  await expect(step(page, "Get the data")).toContainText("Done");
  const stored = await dataOf(page, id);
  expect(stored.kept.sources[0].files.map((file: { name: string }) => file.name)).toEqual(["README.txt"]);
  expect(stored.kept.sources[0].files[0].checksum).toBeNull();
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("says that a place gives no checksum and no license, and takes away what was fetched of a place, and of all of them, after asking", async ({
  page,
}) => {
  test.slow();
  const id = await agentWithData(page, "Geo data");
  await datasets(page).getByRole("button", { name: "See the files of GEO series GSE123456" }).click();
  await expect(listing(page).getByRole("heading", { level: 3 })).toContainText("GEO series GSE123456");
  await expect(page.getByTestId("data-license")).toHaveText("The place does not say how it is licensed. 2 files in all.");
  await expect(listing(page)).toContainText("It also has files that are not listed here.");
  await expect(fileOf(page, "suppl/GSE123456_counts.txt.gz")).toContainText("No checksum is given, so it is checked by its size only");

  await listing(page).getByRole("button", { name: "Choose all that can be fetched" }).click();
  await choosing(page).getByRole("button", { name: "Fetch the files that are chosen" }).click();
  const asking = page.getByRole("alertdialog", { name: /^Fetch 2 files, .*, from GEO series GSE123456\?$/ });
  await expect(asking).toContainText("2 files will be checked by their size only, since the place gives no checksum.");
  await expect(asking).toContainText("ftp.ncbi.nlm.nih.gov");
  await asking.getByRole("button", { name: "Fetch", exact: true }).click();

  const source = keptSource(page, "GEO series GSE123456");
  await expect(source).toBeVisible({ timeout: 20_000 });
  await expect(source.getByTestId("data-kept-file")).toHaveCount(2);
  await expect(source).toContainText("The place does not say how it is licensed. Kept in data/geo/GSE123456/.");
  await expect(source.getByTestId("data-kept-file").first()).toContainText("Checked by its size only");
  await expect(source.getByTestId("data-kept-file").filter({ hasText: "suppl/GSE123456_counts.txt.gz" })).toBeVisible();
  // One place has no button to take everything away, which is the same as taking away that place
  await expect(page.getByRole("button", { name: "Take away every file" })).toHaveCount(0);

  await fetchDataThrough(page, id, "https://zenodo.org/records/1000001", ["counts.csv"]);
  await page.reload();
  await expect(page.getByTestId("data-kept-source")).toHaveCount(2);
  await expect(page.getByTestId("data-kept-total")).toHaveText(/^3 files, /);
  await expect(page.getByRole("button", { name: "Take away every file" })).toBeVisible();

  // Taking one place away asks first, and leaves the other
  await keptSource(page, "Zenodo record 1000001").getByRole("button", { name: "Take away the files from Zenodo record 1000001" }).click();
  const one = page.getByRole("alertdialog", { name: "Take away the files from Zenodo record 1000001?" });
  await expect(one).toContainText("This deletes 1 file from this agent's folder");
  await one.getByRole("button", { name: "Keep" }).click();
  await expect(page.getByTestId("data-kept-source")).toHaveCount(2);
  await keptSource(page, "Zenodo record 1000001").getByRole("button", { name: "Take away the files from Zenodo record 1000001" }).click();
  await page.getByRole("alertdialog", { name: "Take away the files from Zenodo record 1000001?" }).getByRole("button", { name: "Take away" }).click();
  await expect(page.getByTestId("data-kept-source")).toHaveCount(1);
  await expect(keptSource(page, "GEO series GSE123456")).toBeVisible();
  await expect(step(page, "Get the data")).toContainText("Done");
  expect((await dataOf(page, id)).kept.sources.map((item: { key: string }) => item.key)).toEqual(["geo:GSE123456"]);

  // Taking all away leaves nothing, and the step is not started
  await page.getByRole("button", { name: "Take away the files from GEO series GSE123456" }).click();
  await page.getByRole("alertdialog", { name: "Take away the files from GEO series GSE123456?" }).getByRole("button", { name: "Take away" }).click();
  await expect(page.getByText("No data has been fetched for this agent.")).toBeVisible();
  await expect(step(page, "Get the data")).toContainText("Not started");
  expect((await dataOf(page, id)).kept).toMatchObject({ files: 0, sources: [] });
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("takes away every file of every place at once, after asking", async ({ page }) => {
  const id = await agentWithData(page, "Two places");
  await fetchDataThrough(page, id, "https://zenodo.org/records/1000001", ["counts.csv", "metadata.tsv"]);
  await fetchDataThrough(page, id, "GSE123456", ["suppl/GSE123456_counts.txt.gz"]);
  await page.reload();
  await expect(page.getByTestId("data-kept-source")).toHaveCount(2);

  await page.getByRole("button", { name: "Take away every file" }).click();
  const asking = page.getByRole("alertdialog", { name: "Take away every file of Two places?" });
  await expect(asking).toContainText("This deletes 3 files from this agent's folder");
  await expect(asking).toContainText("Your own data, and what stands in for a dataset, are not touched.");
  await asking.getByRole("button", { name: "Take away" }).click();

  await expect(page.getByText("No data has been fetched for this agent.")).toBeVisible();
  await expect(step(page, "Get the data")).toContainText("Not started");
  expect((await dataOf(page, id)).kept.files).toBe(0);
});

test("refuses files that come to more than the most that may be fetched before it asks the server, and looks at a place that is typed", async ({
  page,
}) => {
  const id = await agentWithData(page, "Big data");
  await seeFilesOf(page, "Zenodo record 1000002");
  await listing(page).getByRole("checkbox", { name: "atlas.h5ad", exact: true }).check();
  await choosing(page).getByRole("button", { name: "Fetch the files that are chosen" }).click();
  await expect(choosing(page).getByText(/These files come to .* which is more than the .* that may be fetched\. Choose fewer, or raise the most\./)).toBeVisible();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  // Raising the most is what is asked, and then it is asked to be agreed to: it is not sent
  await choosing(page).getByLabel("Most to fetch, in megabytes").fill("1000");
  await choosing(page).getByRole("button", { name: "Fetch the files that are chosen" }).click();
  const asking = page.getByRole("alertdialog", { name: /^Fetch 1 file, .*, from Zenodo record 1000002\?$/ });
  await expect(asking).toContainText("fetching stops at 1,000 MB");
  await asking.getByRole("button", { name: "Do not fetch" }).click();
  expect((await dataOf(page, id)).job).toBeNull();

  // A place that is typed is looked at by the address, a DOI, or an accession, and what is wrong is said
  const typed = form(page, "See the files of a place");
  await typed.getByRole("button", { name: "See the files" }).click();
  await expect(typed.getByText("Say where the data is: an address, a DOI, or an accession such as GSE12345.")).toBeVisible();
  await typed.getByLabel("Another place").fill("https://zenodo.org/records/999");
  await typed.getByRole("button", { name: "See the files" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "was not found" })).toBeVisible();
  await typed.getByLabel("Another place").fill("https://example.org/data.csv");
  await typed.getByRole("button", { name: "See the files" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "is not an address or an accession of one of the places that data is fetched from here" })).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  await typed.getByLabel("Another place").fill("10.5281/zenodo.1000001");
  await typed.getByRole("button", { name: "See the files" }).click();
  await expect(listing(page).getByRole("heading", { level: 3 })).toContainText("Zenodo record 1000001");
  await expect(page.getByRole("alert").filter({ hasText: "is not an address" })).toHaveCount(0);

  // The places that data is fetched from are shown when they are asked for
  await page.getByRole("button", { name: "Show the places data is fetched from" }).click();
  const approved = page.getByRole("list", { name: "Places data is fetched from" });
  await expect(approved.getByTestId("data-approved").filter({ hasText: "Zenodo" })).toContainText("zenodo.org");
  expect(await accessibilityProblems(page)).toEqual([]);
  await page.getByRole("button", { name: "Hide the places data is fetched from" }).click();
  await expect(approved).toHaveCount(0);
});

test("follows the fetching while it goes on, waits for it before anything else is done to the agent, and keeps nothing if it is stopped", async ({
  page,
}) => {
  const id = await agentWithData(page, "Slow data", false);
  const typed = form(page, "See the files of a place");
  await typed.getByLabel("Another place").fill("https://zenodo.org/records/1000003");
  await typed.getByRole("button", { name: "See the files" }).click();
  await listing(page).getByRole("checkbox", { name: "slow.bin", exact: true }).check();
  await choosing(page).getByRole("button", { name: "Fetch the files that are chosen" }).click();
  await page.getByRole("alertdialog", { name: /^Fetch 1 file/ }).getByRole("button", { name: "Fetch", exact: true }).click();

  const stop = gettingData(page).getByRole("button", { name: "Stop: Fetching data: Slow data" });
  await expect(stop).toBeVisible();
  await expect(step(page, "Get the data")).toContainText("Going on");
  const printed = page.getByRole("log", { name: "What this printed: Fetching data: Slow data" });
  await expect(printed).toContainText("Fetching slow.bin (64 bytes) from https://zenodo.org/api/records/1000003/files/slow.bin/content", { timeout: 10_000 });
  await expect(gettingData(page)).toContainText(/0 of 1 file · \d+ B of 64 B/);
  // Nothing else is done to the agent while it goes on
  await expect(reading(page)).toContainText("The data is being fetched. Reading waits for that.");
  await expect(page.getByRole("button", { name: "Delete Slow data" })).toBeDisabled();
  await expect(page.getByLabel("Upload it again")).toBeDisabled();
  await expect(choosing(page).getByRole("button", { name: "Waiting…" })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);

  await stop.click();

  await expect(gettingData(page).getByText("Stopped", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("data-kept")).toHaveCount(0);
  await expect(step(page, "Get the data")).toContainText("Not started");
  await expect(page.getByRole("button", { name: "Delete Slow data" })).toBeEnabled();
  await expect(choosing(page).getByRole("button", { name: "Fetch the files that are chosen" })).toBeEnabled();
  expect(await dataOf(page, id)).toMatchObject({ kept: { files: 0, sources: [] }, job: null });
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("looks again at what a place has when it is not what was shown, and does not fetch what was chosen", async ({ page }) => {
  const id = await agentWithData(page, "Changed data");
  await seeFilesOf(page, "Zenodo record 1000001");
  await listing(page).getByRole("checkbox", { name: "counts.csv", exact: true }).check();
  let listed = 0;
  await page.route("**/api/paperagents/*/data/files*", (route) => {
    listed += 1;

    return route.fallback();
  });
  await page.route("**/api/paperagents/*/data", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "changed", message: "Zenodo record 1000001 has files that are not what was shown. Look at them again." } }),
        })
      : route.fallback(),
  );
  await choosing(page).getByRole("button", { name: "Fetch the files that are chosen" }).click();
  await page.getByRole("alertdialog", { name: /^Fetch 1 file/ }).getByRole("button", { name: "Fetch", exact: true }).click();

  await expect(choosing(page).getByRole("alert")).toHaveCount(1);
  await expect(choosing(page).getByRole("alert")).toContainText("has files that are not what was shown");
  await expect(choosing(page).getByText("Choose at least one file.")).toHaveCount(0);
  await expect.poll(() => listed).toBeGreaterThan(0);
  await expect(page.getByTestId("data-chosen")).toHaveText("No files are chosen.");
  await page.unroute("**/api/paperagents/*/data");
  expect((await dataOf(page, id)).kept.sources).toEqual([]);
});

test("says which of the person's own data stands in for a dataset, for one that is not listed too, and that it was not copied", async ({
  page,
}) => {
  const id = await agentWithData(page, "Stand-in data");
  const added = await page.request.post("/api/own/data/files?name=my-counts.csv&description=Counts%20of%20my%20own", {
    data: Buffer.from("gene,cell1\nA,1\n"),
    headers: { "Content-Type": "application/octet-stream" },
  });
  expect(added.status()).toBe(201);
  try {
    await page.reload();
    const named = datasets(page).getByTestId("data-dataset");
    await expect(named.getByRole("button", { name: /^Take it away: / })).toHaveCount(0);
    await named.getByLabel("Your data to put in the place of GEO").selectOption({ value: "my-counts.csv" });
    await named.getByRole("button", { name: "Use it in its place" }).click();

    await expect(named).toContainText("Stood in for");
    await expect(named).toContainText("Your data my-counts.csv stands in for it");
    await expect(step(page, "Get the data")).toContainText("Done");
    const stored = await dataOf(page, id);
    expect(stored.stand_ins).toHaveLength(1);
    expect(stored.stand_ins[0]).toMatchObject({ own: "my-counts.csv", own_data: { name: "my-counts.csv" } });
    expect(stored.kept.files).toBe(0);
    expect(await accessibilityProblems(page)).toEqual([]);

    // A dataset that the paper does not name is stood in for by what it is called
    await page.getByText("Stand in for a dataset that is not listed").click();
    const unlisted = page.locator("details", { hasText: "Stand in for a dataset that is not listed" });
    await unlisted.getByLabel("What it stands in for").fill("A cohort that the paper does not name");
    await unlisted.getByLabel("Your data to put in the place of A cohort that the paper does not name").selectOption({ value: "my-counts.csv" });
    await unlisted.getByRole("button", { name: "Use it in its place" }).click();
    const others = page.getByRole("list", { name: "Other data that stands in" });
    await expect(others.getByTestId("data-other-stand-in")).toHaveCount(1);
    await expect(others).toContainText("A cohort that the paper does not name");
    expect((await dataOf(page, id)).stand_ins).toHaveLength(2);
    expect(await accessibilityProblems(page)).toEqual([]);

    // It is the same after the page is looked at again, and a warning is given when the data is no longer there
    await page.reload();
    await expect(named).toContainText("Your data my-counts.csv stands in for it");
    expect((await page.request.delete("/api/own/data/my-counts.csv")).ok()).toBe(true);
    await page.reload();
    await expect(page.getByText("There is no data of yours called my-counts.csv now.").first()).toBeVisible();
    expect(await accessibilityProblems(page)).toEqual([]);

    await others.getByRole("button", { name: /^Take it away: my-counts.csv in place of / }).click();
    await expect(others).toHaveCount(0);
    await named.getByRole("button", { name: "Take it away: my-counts.csv in place of GEO" }).click();
    await expect(named).not.toContainText("Stood in for");
    await expect(step(page, "Get the data")).toContainText("Not started");
    expect((await dataOf(page, id)).stand_ins).toEqual([]);
  } finally {
    await page.request.delete("/api/own/data/my-counts.csv");
  }
});

test("says that a paper that has not been read names no dataset and no place yet, and still takes a place that is typed", async ({ page }) => {
  await agentWithData(page, "Unread data", false);
  await expect(page.getByText("The paper has not been read to the end, so what it names is not known yet.")).toBeVisible();
  await expect(page.getByText("No place is named for the data. Say where it is below.")).toBeVisible();
  await expect(form(page, "See the files of a place")).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
});

// What the page says of the tutorials of an agent's code, which are run by a stand-in for Docker (see scripted_server.py): the code
// of "many" has two scripts as well as a notebook, and one in R, which is not run. What a tutorial does is from the agent's title:
// "lengthy" takes a while, "failing" fails for want of a package, "mixed" fails after the first, and "flaky" gives other calls
// each time it is run
const MANY_ADDRESS = "https://github.com/example/many-scripts";
const referenceForm = (page: Page) => form(page, "Run the tutorials");
const runningTutorials = (page: Page) => page.getByRole("region", { name: "Running the tutorials" });
const referencePlan = (page: Page) => page.getByTestId("reference-plan");
const keptRun = (page: Page) => page.getByTestId("reference-kept");
const tutorials = (page: Page) => page.getByTestId("reference-tutorial");
const tutorialNamed = (page: Page, path: string) => tutorials(page).filter({ has: page.getByText(path, { exact: true }) });
const referenceOf = async (page: Page, id: string) => (await page.request.get(`/api/paperagents/${id}/reference`)).json();
const RUN = "Run the tutorials";

// Makes an agent whose code is fetched and whose environment is built, so that what a test is about is its tutorials, and opens it
async function agentWithEnvironment(page: Page, title: string, repo = CODE_ADDRESS, paper: Record<string, unknown> = { kind: "file" }): Promise<string> {
  const id = await makeAgent(page, { title, paper, repo });
  await fetchTheCode(page, id);
  const started = await page.request.post(`/api/paperagents/${id}/environment`, { data: {} });
  expect(started.status()).toBe(202);
  await expect.poll(async () => (await environmentOf(page, id)).job, { timeout: 30_000 }).toBeNull();
  expect((await environmentOf(page, id)).built).not.toBeNull();
  await openAgent(page, id, title);

  return id;
}

test("says what would be run from the code, asks for what is wrong with the asking to be put right, runs the tutorials, and shows what each gave and how far that is known", async ({
  page,
}) => {
  const id = await makeAgent(page, { title: "Plain tutorials", paper: { kind: "file" }, repo: CODE_ADDRESS });
  await openAgent(page, id, "Plain tutorials");
  await expect(page.getByRole("heading", { name: "Tutorials", level: 2, exact: true })).toBeVisible();
  // They are in the code, and are run in the environment, so there is nothing to run until both are there
  await expect(page.getByText("Fetch the code first. The tutorials are in it.")).toBeVisible();
  await expect(referenceForm(page)).toHaveCount(0);
  await fetchTheCode(page, id);
  await page.reload();
  await expect(page.getByText("Build the environment first. The tutorials are run in it.")).toBeVisible();
  await expect(referenceForm(page)).toHaveCount(0);

  const built = await page.request.post(`/api/paperagents/${id}/environment`, { data: {} });
  expect(built.status()).toBe(202);
  await expect.poll(async () => (await environmentOf(page, id)).job, { timeout: 30_000 }).toBeNull();
  await page.reload();
  await expect(referencePlan(page)).toBeVisible();
  await expect(page.getByTestId("reference-plan-summary")).toHaveText("1 tutorial can be run here.");
  await expect(referencePlan(page).getByRole("list", { name: "Tutorials that would be run" })).toContainText("tutorials/quickstart.ipynb (a notebook)");
  await expect(step(page, "Build the tools")).toContainText("Not started");
  expect((await referenceOf(page, id)).kept).toBeNull();
  expect(await accessibilityProblems(page)).toEqual([]);

  // What is wrong with the asking is said before it is sent
  await referenceForm(page).getByLabel("Most time for one tutorial, in minutes").fill("0");
  await referenceForm(page).getByLabel("Most time for all of them, in minutes").fill("500");
  await referenceForm(page).getByLabel("How many tutorials to run").fill("two");
  await referenceForm(page).getByLabel("How many times to run each").fill("9");
  await referenceForm(page).getByLabel("Most one run may write, in gigabytes").fill("99");
  await referenceForm(page).getByRole("button", { name: RUN }).click();
  await expect(referenceForm(page).getByText(/in minutes, is a whole number from 1 to 60/)).toBeVisible();
  await expect(referenceForm(page).getByText(/is a whole number from 1 to 240/)).toBeVisible();
  await expect(referenceForm(page).getByText(/How many tutorials are run is a whole number from 1 to 25/)).toBeVisible();
  await expect(referenceForm(page).getByText(/How many times each is run is a whole number from 1 to 3/)).toBeVisible();
  await expect(referenceForm(page).getByText(/in gigabytes, is a whole number from 1 to 20/)).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  expect((await referenceOf(page, id)).kept).toBeNull();
  await referenceForm(page).getByLabel("Most time for one tutorial, in minutes").fill("20");
  await referenceForm(page).getByLabel("Most time for all of them, in minutes").fill("10");
  await referenceForm(page).getByLabel("How many tutorials to run").fill("5");
  await referenceForm(page).getByLabel("How many times to run each").fill("2");
  await referenceForm(page).getByLabel("Most one run may write, in gigabytes").fill("1");
  await referenceForm(page).getByRole("button", { name: RUN }).click();
  await expect(referenceForm(page).getByText("The time for all of them cannot be less than the time for one.")).toBeVisible();
  expect((await referenceOf(page, id)).kept).toBeNull();

  await referenceForm(page).getByLabel("Most time for all of them, in minutes").fill("30");
  await referenceForm(page).getByRole("button", { name: RUN }).click();

  await expect(keptRun(page)).toBeVisible({ timeout: 25_000 });
  await expect(referencePlan(page)).toHaveCount(0);
  await expect(referenceForm(page)).toHaveCount(0);
  await expect(page.getByTestId("reference-kept-when")).toContainText("1 tutorial was run: 1 to the end, 0 not. 1 gave the same each time it was run.");
  await expect(keptRun(page)).toContainText("Run to the end of the list");
  await expect(keptRun(page)).toContainText("20 minutes for one and 30 for all, 2 runs of each, and 1 GB written");
  await expect(keptRun(page).getByText("Given to read").locator("xpath=following-sibling::dd[1]")).toHaveText("None");
  await expect(step(page, "Build the tools")).toContainText("Not started");
  await expect(tutorials(page)).toHaveCount(1);
  const one = tutorialNamed(page, "tutorials/quickstart.ipynb");
  await expect(one).toHaveAttribute("data-status", "ok");
  await expect(one).toContainText("Ran to the end");
  await expect(one.getByTestId("reference-agreement")).toHaveText("The same each of 2 times.");
  await expect(one).toContainText("2 calls to the code, 1 file written, 2 of 2 cells kept");
  // It says what was and was not shown, which is that it ran here and gave this
  await expect(keptRun(page)).toContainText("It does not show that what it gave is right");
  const kept = await referenceOf(page, id);
  expect(kept).toMatchObject({
    kept: {
      complete: true,
      limits: { minutes: 20, total_minutes: 30, tutorials: 5, repeats: 2, gigabytes: 1 },
      tutorials: [{ path: "tutorials/quickstart.ipynb", status: "ok", runs: 2, stable: true, calls: 2 }],
    },
    job: null,
  });
  expect(await accessibilityProblems(page)).toEqual([]);

  // What a tutorial did is looked at when it is asked for, and is not got before
  await expect(page.getByTestId("reference-detail")).toHaveCount(0);
  await one.getByRole("button", { name: "Show what it did" }).click();
  const detail = page.getByTestId("reference-detail");
  await expect(detail).toBeVisible();
  await expect(detail.getByRole("list", { name: "How each run ended" })).toContainText("Run 2: ran to the end");
  await expect(detail).toContainText("3.11.9");
  await expect(detail.getByTestId("reference-call")).toHaveCount(2);
  await expect(detail.getByTestId("reference-call").first()).toContainText("cellmapper.core.scale(values=[1,2,3], factor=3.5) gave [3.5,7,10.5]");
  await expect(detail.getByTestId("reference-call").last()).toContainText("cellmapper.core.embed(values=[1,2,3]) gave numpy.ndarray, shape 3×2, float64");
  await expect(detail.getByRole("list", { name: "Files that it wrote" })).toContainText("embedding.csv");
  await expect(detail.getByRole("region", { name: "The end of what it printed" })).toContainText("Wrote embedding.csv");
  await expect(detail.getByRole("list", { name: "Lines that were left out" })).toContainText("cell 2: %matplotlib inline");
  await expect(detail.getByTestId("reference-failure")).toHaveCount(0);
  await expect(page.getByText("Code it imported")).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  await one.getByRole("button", { name: "Hide what it did" }).click();
  await expect(detail).toHaveCount(0);

  // It is the same after the page is looked at again, and cannot be run a second time on top of itself
  await page.reload();
  await expect(keptRun(page)).toBeVisible();
  await expect(tutorials(page)).toHaveCount(1);
  expect((await page.request.post(`/api/paperagents/${id}/reference`, { data: {} })).status()).toBe(409);

  // Taking it away asks first, and leaves the code and the environment
  await keptRun(page).getByRole("button", { name: "Take what they gave away" }).click();
  const asking = page.getByRole("alertdialog", { name: "Take away what the tutorials of Plain tutorials gave?" });
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  await expect(keptRun(page)).toBeVisible();
  await keptRun(page).getByRole("button", { name: "Take what they gave away" }).click();
  await page.getByRole("alertdialog", { name: "Take away what the tutorials of Plain tutorials gave?" }).getByRole("button", { name: "Take away" }).click();

  await expect(keptRun(page)).toHaveCount(0);
  await expect(referencePlan(page)).toBeVisible();
  await expect(referenceForm(page)).toBeVisible();
  expect((await referenceOf(page, id)).kept).toBeNull();
  expect((await environmentOf(page, id)).built).not.toBeNull();
  await expect(page.getByTestId("code-commit")).toBeVisible();
});

test("follows a run of the tutorials while it goes on, waits for it before anything else is done to the agent, and keeps what it had done when it is stopped", async ({
  page,
}) => {
  const id = await agentWithEnvironment(page, "Lengthy tutorials", CODE_ADDRESS, { kind: "doi", doi: "10.1000/tutorials-paper" });
  await referenceForm(page).getByRole("button", { name: RUN }).click();

  const stop = runningTutorials(page).getByRole("button", { name: "Stop: Running the tutorials: Lengthy tutorials" });
  await expect(stop).toBeVisible();
  await expect(step(page, "Build the tools")).toContainText("Going on");
  await expect(referenceForm(page).getByRole("button", { name: "Running…" })).toBeDisabled();
  await expect(page.getByRole("log", { name: "What this printed: Running the tutorials: Lengthy tutorials" })).toContainText("Running tutorials/quickstart.ipynb", {
    timeout: 10_000,
  });
  // What is kept of a run that has begun is the account of one that is not over, which is not one that did not come to its end, and
  // is not said to be, even when the page is looked at again while it goes on
  expect((await referenceOf(page, id)).kept).toMatchObject({ complete: false, tutorials: [] });
  await page.reload();
  await expect(stop).toBeVisible();
  await expect(referenceForm(page).getByRole("button", { name: "Running…" })).toBeDisabled();
  await expect(keptRun(page)).toHaveCount(0);
  await expect(page.getByText("did not come to its end")).toHaveCount(0);
  // Nothing else is done to the agent while it goes on, and its paper is not read
  await expect(fetchAndRead(page)).toBeDisabled();
  await expect(reading(page)).toContainText("The tutorials are being run. Reading waits for that.");
  await expect(page.getByRole("button", { name: "Delete Lengthy tutorials" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Take the code away" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Take the environment away" })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);

  await stop.click();

  await expect(runningTutorials(page).getByText("Stopped", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(step(page, "Build the tools")).toContainText("Not started");
  // What came to be before it was stopped is kept, which is nothing here, and is said not to be the whole
  await expect(keptRun(page)).toContainText("Not run to the end");
  await expect(keptRun(page)).toContainText("This run did not come to its end");
  await expect(page.getByTestId("reference-kept-when")).toContainText("No tutorial was run.");
  await expect(tutorials(page)).toHaveCount(0);
  await expect(referenceForm(page).getByRole("button", { name: RUN })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Take the environment away" })).toBeEnabled();
  expect(await referenceOf(page, id)).toMatchObject({ kept: { complete: false, tutorials: [] }, job: null });
  expect(await accessibilityProblems(page)).toEqual([]);

  // Run again and left to end, the run replaces what was kept
  await referenceForm(page).getByRole("button", { name: RUN }).click();
  await expect(keptRun(page)).toContainText("Run to the end of the list", { timeout: 25_000 });
  await expect(keptRun(page)).not.toContainText("Not run to the end");
  await expect(tutorials(page)).toHaveCount(1);
  await expect(runningTutorials(page).getByText("Stopped", { exact: true })).toHaveCount(0);
});

test("says how each tutorial ended, which failed and why, what to do about it, which were not run, and the runs that gave other than the first", async ({
  page,
}) => {
  const failing = await agentWithEnvironment(page, "Failing tutorials", MANY_ADDRESS);
  await expect(page.getByTestId("reference-plan-summary")).toHaveText("3 tutorials can be run here, 1 cannot.");
  await expect(referencePlan(page).getByRole("list", { name: "Tutorials that cannot be run here" })).toContainText(
    "examples/analysis.R: It is written in R, and only Python is run here.",
  );
  // The paths that would be run are listed in the order that they are run in
  await expect(referencePlan(page).getByRole("list", { name: "Tutorials that would be run" }).getByRole("listitem")).toHaveCount(3);
  await referenceForm(page).getByLabel("How many tutorials to run").fill("2");
  await referenceForm(page).getByRole("button", { name: RUN }).click();

  await expect(keptRun(page)).toBeVisible({ timeout: 25_000 });
  await expect(tutorials(page)).toHaveCount(2);
  await expect(page.locator("[data-testid=reference-tutorial][data-status=failed]")).toHaveCount(2);
  await expect(page.getByTestId("reference-kept-when")).toContainText("2 tutorials were run: 0 to the end, 2 not. 0 gave the same each time it was run.");
  await expect(tutorials(page).first()).toContainText("Stopped with a failure");
  await expect(tutorials(page).first()).toContainText("Something it imports is not installed");
  await expect(tutorials(page).first().getByTestId("reference-agreement")).toHaveText("Not compared, as it did not end.");
  // The ones that were over the number allowed are listed as not run, with why
  await expect(page.getByTestId("reference-not-run").getByRole("listitem")).toHaveCount(1);
  await expect(page.getByTestId("reference-not-run")).toContainText("was not run: Only 2 tutorials are run at a time.");
  await expect(page.getByRole("list", { name: "Tutorials that cannot be run here" })).toContainText("examples/analysis.R");
  expect(await accessibilityProblems(page)).toEqual([]);

  await tutorials(page).first().getByRole("button", { name: "Show what it did" }).click();
  const failure = page.getByTestId("reference-failure");
  await expect(failure).toHaveAttribute("data-kind", "missing_package");
  await expect(failure).toContainText("No module named 'scanpy'");
  await expect(failure).toContainText("Build it again with the system package that has it, if it is one.");
  await expect(failure.getByRole("region", { name: "The end of what it said" })).toContainText("ModuleNotFoundError: No module named 'scanpy'");
  await expect(page.getByTestId("reference-call")).toHaveCount(0);
  await expect(page.getByText("It made none, so there is nothing to make a tool from.")).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  const stored = await referenceOf(page, failing);
  expect(stored.kept.tutorials.map((one: { status: string }) => one.status)).toEqual(["failed", "failed"]);

  // Some that ran to the end and some that did not are told apart
  const mixed = await agentWithEnvironment(page, "Mixed tutorials", MANY_ADDRESS);
  await referenceForm(page).getByRole("button", { name: RUN }).click();
  await expect(keptRun(page)).toBeVisible({ timeout: 25_000 });
  await expect(page.getByTestId("reference-kept-when")).toContainText("3 tutorials were run: 1 to the end, 2 not. 1 gave the same each time it was run.");
  await expect(page.locator("[data-testid=reference-tutorial][data-status=ok]")).toHaveCount(1);
  await expect(page.locator("[data-testid=reference-tutorial][data-status=failed]")).toHaveCount(2);
  expect((await referenceOf(page, mixed)).kept.tutorials).toHaveLength(3);
  expect(await accessibilityProblems(page)).toEqual([]);

  // A tutorial that gives other calls when it is run again is not one that can be held to, and is said to be so in words
  await agentWithEnvironment(page, "Flaky tutorials");
  await referenceForm(page).getByRole("button", { name: RUN }).click();
  await expect(keptRun(page)).toBeVisible({ timeout: 25_000 });
  await expect(tutorials(page).first()).toHaveAttribute("data-status", "ok");
  await expect(tutorials(page).first().getByTestId("reference-agreement")).toHaveText("Not the same each of 2 times: the calls to the code differed.");
  await expect(page.getByTestId("reference-kept-when")).toContainText("1 tutorial was run: 1 to the end, 0 not. 0 gave the same each time it was run.");
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("runs each tutorial once if that is asked, and says that what was run once was not compared", async ({ page }) => {
  const id = await agentWithEnvironment(page, "Once tutorials");
  await referenceForm(page).getByLabel("How many times to run each").fill("1");
  await referenceForm(page).getByRole("button", { name: RUN }).click();

  await expect(keptRun(page)).toBeVisible({ timeout: 25_000 });
  await expect(tutorials(page).first().getByTestId("reference-agreement")).toHaveText("Run once, so not compared.");
  await expect(page.getByTestId("reference-kept-when")).toContainText("0 gave the same each time it was run.");
  await expect(keptRun(page)).toContainText("1 run of each");
  expect((await referenceOf(page, id)).kept.tutorials[0]).toMatchObject({ runs: 1, stable: null });
});

test("says that there is nothing to run in code that has no tutorial, and that the tutorials were not run for want of Docker or its image", async ({ page }) => {
  const id = await agentWithEnvironment(page, "No tutorials", "https://github.com/example/gpu-mapper");
  await expect(page.getByTestId("reference-none")).toContainText("There is nothing to run");
  await expect(page.getByTestId("reference-none")).toContainText("No tutorial in the code can be run here: only Python is run.");
  await expect(referenceForm(page)).toHaveCount(0);
  expect((await page.request.post(`/api/paperagents/${id}/reference`, { data: {} })).status()).toBe(422);
  expect(await accessibilityProblems(page)).toEqual([]);

  await agentWithEnvironment(page, "Stopped docker tutorials");
  await page.route("**/api/paperagents/*/reference", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();
    const body = await response.json();

    return route.fulfill({ response, json: { ...body, docker: { ready: false, message: "Docker is installed but is not running." } } });
  });
  await page.reload();
  await expect(page.getByText("Docker is installed but is not running. Running the tutorials takes it.")).toBeVisible();
  await expect(referencePlan(page)).toBeVisible();
  await expect(referenceForm(page).getByRole("button", { name: RUN })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);
  await page.unroute("**/api/paperagents/*/reference");

  await page.route("**/api/paperagents/*/reference", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();
    const body = await response.json();

    return route.fulfill({ response, json: { ...body, environment: { ...body.environment, image_present: false } } });
  });
  await page.reload();
  await expect(page.getByText("Docker no longer has the image of the environment, so the tutorials cannot be run.")).toBeVisible();
  await expect(referenceForm(page).getByRole("button", { name: RUN })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("says why the server refused to run the tutorials, and looks again when what the page shows is out of date", async ({ page }) => {
  const id = await agentWithEnvironment(page, "Refused tutorials");
  await page.route("**/api/paperagents/*/reference", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "docker_missing", message: "Docker is not installed on this machine, and running tutorials takes it." } }),
        })
      : route.fallback(),
  );
  await referenceForm(page).getByRole("button", { name: RUN }).click();
  await expect(referenceForm(page).getByRole("alert")).toContainText("Docker is not installed on this machine");
  await page.unroute("**/api/paperagents/*/reference");

  // Tutorials that were run a moment before the page looked are not a reason to refuse: the page looks again
  let looked = 0;
  await page.route("**/api/paperagents/*/reference", (route) => {
    if (route.request().method() === "GET") looked += 1;

    return route.request().method() === "POST"
      ? route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "done", message: "The tutorials have been run. Remove that to run them again." } }),
        })
      : route.fallback();
  });
  const before = looked;
  await referenceForm(page).getByRole("button", { name: RUN }).click();
  await expect.poll(() => looked).toBeGreaterThan(before);
  await expect(referenceForm(page).getByRole("alert")).toHaveCount(0);
  await page.unroute("**/api/paperagents/*/reference");
  expect((await referenceOf(page, id)).kept).toBeNull();

  // What was kept of a tutorial is gone when it is asked for, which is as the run was taken away, and the page looks again
  await referenceForm(page).getByRole("button", { name: RUN }).click();
  await expect(keptRun(page)).toBeVisible({ timeout: 25_000 });
  let seen = 0;
  await page.route("**/api/paperagents/*/reference", (route) => {
    if (route.request().method() === "GET") seen += 1;

    return route.fallback();
  });
  await page.route("**/api/paperagents/*/reference/*", (route) =>
    route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "not_found", message: "There is no such tutorial." } }) }),
  );
  const again = seen;
  await tutorials(page).first().getByRole("button", { name: "Show what it did" }).click();
  await expect.poll(() => seen).toBeGreaterThan(again);
  await expect(page.getByTestId("reference-detail")).toHaveCount(0);
  await expect(keptRun(page)).toBeVisible();
  await page.unroute("**/api/paperagents/*/reference/*");
  await page.unroute("**/api/paperagents/*/reference");
});

test("gives the runs the data that was fetched, to read, unless that is asked not to be done, and says what they were given", async ({ page }) => {
  test.slow();
  const id = await makeAgent(page, { title: "Data tutorials", paper: { kind: "file" }, repo: CODE_ADDRESS });
  await sendPaper(page, id, "cells.txt", DATA_PAPER);
  await readTheAgent(page, id);
  await fetchTheCode(page, id);
  const built = await page.request.post(`/api/paperagents/${id}/environment`, { data: {} });
  expect(built.status()).toBe(202);
  await expect.poll(async () => (await environmentOf(page, id)).job, { timeout: 30_000 }).toBeNull();
  await fetchDataThrough(page, id, "https://zenodo.org/records/1000001", ["counts.csv"]);
  await openAgent(page, id, "Data tutorials");

  const given = referenceForm(page).getByRole("checkbox", { name: /^Give the runs the data that was fetched/ });
  await expect(given).toBeChecked();
  await expect(referenceForm(page)).toContainText("It is there to read only, at /opt/paper/data, and PAPER_DATA says where.");
  expect(await accessibilityProblems(page)).toEqual([]);
  await given.uncheck();
  await referenceForm(page).getByRole("button", { name: RUN }).click();

  await expect(keptRun(page)).toBeVisible({ timeout: 25_000 });
  await expect(keptRun(page).getByText("Given to read").locator("xpath=following-sibling::dd[1]")).toHaveText("None");
  expect((await referenceOf(page, id)).kept.data).toBeNull();

  // Run again with it, the runs are given what was fetched
  await keptRun(page).getByRole("button", { name: "Take what they gave away" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Take away" }).click();
  await expect(referenceForm(page)).toBeVisible();
  const again = referenceForm(page).getByRole("checkbox", { name: /^Give the runs the data that was fetched/ });
  // What was asked for is still there to ask for again
  await expect(again).not.toBeChecked();
  await again.check();
  await referenceForm(page).getByRole("button", { name: RUN }).click();
  await expect(keptRun(page)).toBeVisible({ timeout: 25_000 });
  await expect(keptRun(page).getByText("Given to read").locator("xpath=following-sibling::dd[1]")).toContainText("1 file, ");
  expect((await referenceOf(page, id)).kept.data).toMatchObject({ files: 1 });
  expect(await accessibilityProblems(page)).toEqual([]);
});

const toolsForm = (page: Page) => form(page, "Make the tools");
const makingTools = (page: Page) => page.getByRole("region", { name: "Making the tools" });
const toolsPreview = (page: Page) => page.getByTestId("tools-preview");
const keptTools = (page: Page) => page.getByTestId("tools-kept");
const toolNamed = (page: Page, name: string) => page.locator(`[data-testid=tool][data-name=${name}]`);
const toolsOf = async (page: Page, id: string) => (await page.request.get(`/api/paperagents/${id}/tools`)).json();
const MAKE = "Make the tools";

// Makes an agent whose tutorials have been run, so that what a test is about is its tools, and opens it
async function agentWithTutorials(page: Page, title: string, paper: Record<string, unknown> = { kind: "file" }): Promise<string> {
  const id = await agentWithEnvironment(page, title, CODE_ADDRESS, paper);
  const started = await page.request.post(`/api/paperagents/${id}/reference`, { data: {} });
  expect(started.status()).toBe(202);
  await expect.poll(async () => (await referenceOf(page, id)).job, { timeout: 30_000 }).toBeNull();
  expect((await referenceOf(page, id)).kept).toMatchObject({ complete: true });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Tools", level: 2, exact: true })).toBeVisible();

  return id;
}

test("says that tools are made of what the tutorials did, and that there is nothing to make until they have been run", async ({ page }) => {
  const id = await agentWithEnvironment(page, "Unrun tools");
  await expect(page.getByRole("heading", { name: "Tools", level: 2, exact: true })).toBeVisible();
  await expect(page.getByTestId("tools-no-reference")).toHaveText("Run the tutorials first. Tools are made from the calls that they made.");
  await expect(toolsForm(page)).toHaveCount(0);
  await expect(toolsPreview(page)).toHaveCount(0);
  await expect(step(page, "Build the tools")).toContainText("Not started");
  const asked = await page.request.post(`/api/paperagents/${id}/tools`, { data: {} });
  expect(asked.status()).toBe(422);
  expect((await asked.json()).error.code).toBe("no_reference");
  expect(await toolsOf(page, id)).toMatchObject({ reference: null, preview: null, kept: null, job: null });
  expect(await accessibilityProblems(page)).toEqual([]);

  // Once they are run the page looks again, and the tools can be made
  await referenceForm(page).getByRole("button", { name: RUN }).click();
  await expect(keptRun(page)).toBeVisible({ timeout: 25_000 });
  await expect(toolsPreview(page)).toBeVisible();
  await expect(page.getByTestId("tools-no-reference")).toHaveCount(0);
  await expect(toolsForm(page)).toBeVisible();
});

test("says what would be made, asks for what is wrong with the asking to be put right, makes the tools, and shows each with how far it was checked and what it was held to", async ({
  page,
}) => {
  const id = await agentWithTutorials(page, "Plain tools");
  await expect(toolsPreview(page)).toBeVisible();
  await expect(page.getByTestId("tools-preview-summary")).toHaveText("2 functions can be made into tools.");
  const candidates = toolsPreview(page).getByRole("list", { name: "Functions that would be made into tools" });
  await expect(candidates).toContainText("scale is cellmapper.core.scale, called 1 time in 1 tutorial");
  await expect(candidates).toContainText("embed is cellmapper.core.embed, called 1 time in 1 tutorial");
  await expect(toolsForm(page)).toContainText("A tool is a small function, written without a model");
  await expect(toolsForm(page)).toContainText("no network");
  await expect(step(page, "Build the tools")).toContainText("Not started");
  expect((await toolsOf(page, id)).kept).toBeNull();
  expect(await accessibilityProblems(page)).toEqual([]);

  // What is wrong with the asking is said before it is sent
  await toolsForm(page).getByLabel("Most time for the calls of one tool, in minutes").fill("0");
  await toolsForm(page).getByLabel("Most time for all of the tools, in minutes").fill("500");
  await toolsForm(page).getByLabel("How many tools to make").fill("many");
  await toolsForm(page).getByLabel("How many times to call each again").fill("9");
  await toolsForm(page).getByLabel("How many times a wrapper may be rewritten").fill("-1");
  await toolsForm(page).getByLabel("Most one call may write, in gigabytes").fill("99");
  await toolsForm(page).getByRole("button", { name: MAKE }).click();
  await expect(toolsForm(page).getByText(/for the calls of one tool, in minutes, is a whole number from 1 to 30/)).toBeVisible();
  await expect(toolsForm(page).getByText(/for all of the tools, in minutes, is a whole number from 1 to 120/)).toBeVisible();
  await expect(toolsForm(page).getByText(/How many tools are made is a whole number from 1 to 50/)).toBeVisible();
  await expect(toolsForm(page).getByText(/How many times each call is made again is a whole number from 1 to 3/)).toBeVisible();
  await expect(toolsForm(page).getByText(/How many times a wrapper is rewritten is a whole number from 0 to 3/)).toBeVisible();
  await expect(toolsForm(page).getByText(/in gigabytes, is a whole number from 1 to 20/)).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  expect((await toolsOf(page, id)).kept).toBeNull();
  await toolsForm(page).getByLabel("Most time for the calls of one tool, in minutes").fill("20");
  await toolsForm(page).getByLabel("Most time for all of the tools, in minutes").fill("10");
  await toolsForm(page).getByLabel("How many tools to make").fill("5");
  await toolsForm(page).getByLabel("How many times to call each again").fill("2");
  await toolsForm(page).getByLabel("How many times a wrapper may be rewritten").fill("1");
  await toolsForm(page).getByLabel("Most one call may write, in gigabytes").fill("1");
  await toolsForm(page).getByRole("button", { name: MAKE }).click();
  await expect(toolsForm(page).getByText("The time for all of the tools cannot be less than the time for one.")).toBeVisible();
  expect((await toolsOf(page, id)).kept).toBeNull();

  await toolsForm(page).getByLabel("Most time for all of the tools, in minutes").fill("30");
  await toolsForm(page).getByRole("button", { name: MAKE }).click();

  await expect(keptTools(page)).toBeVisible({ timeout: 25_000 });
  await expect(toolsPreview(page)).toHaveCount(0);
  await expect(toolsForm(page)).toHaveCount(0);
  await expect(page.getByTestId("tools-kept-when")).toContainText("1 tool of tier A. 1 function was not made into a tool.");
  await expect(keptTools(page)).toContainText("Made to the end of the list");
  await expect(keptTools(page)).toContainText("20 minutes for the calls of one tool and 30 for all, each call made again 2 times, 1 rewrite, and 1 GB written");
  await expect(keptTools(page).getByText("Given to read").locator("xpath=following-sibling::dd[1]")).toHaveText("None");
  await expect(step(page, "Build the tools")).toContainText("Done");
  // It says what was and was not shown, and that a conversation cannot use a tool yet
  await expect(keptTools(page)).toContainText("does not show that");
  await expect(keptTools(page)).toContainText("A conversation cannot use a tool yet.");

  await expect(page.getByTestId("tool")).toHaveCount(1);
  const scale = toolNamed(page, "scale");
  await expect(scale).toContainText("scale(values, factor)");
  await expect(scale).toContainText("Tier A");
  await expect(scale).toContainText("It calls cellmapper.core.scale.");
  await expect(scale).toContainText("1 call, each made again 2 times, gave what the tutorial got every time");
  // The function that gave an array is not a tool, with why, and what was found
  const dropped = page.getByTestId("tools-dropped");
  await expect(dropped.getByTestId("tool-dropped")).toHaveCount(1);
  await expect(dropped.getByTestId("tool-dropped")).toHaveAttribute("data-kind", "replay_differs");
  await expect(dropped).toContainText("cellmapper.core.embed");
  await expect(dropped).toContainText("It gave something else when it was called again");
  await expect(dropped).toContainText("Only how it shows itself was kept, and not all of it, so it cannot be told to be what it was");
  expect(await toolsOf(page, id)).toMatchObject({
    kept: {
      complete: true,
      limits: { minutes: 20, total_minutes: 30, tools: 5, repeats: 2, repairs: 1, gigabytes: 1 },
      tools: [{ name: "scale", tier: "A", checked: 1, recorded: 1, repeats: 2 }],
      dropped: [{ name: "embed", kind: "replay_differs" }],
    },
    job: null,
  });
  expect(await accessibilityProblems(page)).toEqual([]);

  // The wrapper and what it was held to are looked at when they are asked for, and are not got before
  await expect(page.getByTestId("tool-detail")).toHaveCount(0);
  await scale.getByRole("button", { name: "Show the wrapper and the evidence" }).click();
  const detail = page.getByTestId("tool-detail");
  await expect(detail).toBeVisible();
  await expect(detail).toContainText("cellmapper.core.scale");
  await expect(detail).toContainText("cellmapper/core.py, line 3");
  await expect(detail.getByRole("list", { name: "Parameters of the tool" })).toContainText("values: list[float]");
  await expect(detail.getByRole("list", { name: "Parameters of the tool" })).toContainText("factor: float = 1");
  await expect(detail).toContainText("Multiplies each value by a factor.");
  await expect(detail.getByRole("region", { name: "The wrapper's code" })).toContainText("def scale");
  await expect(detail.getByTestId("tool-case")).toHaveCount(1);
  await expect(detail.getByTestId("tool-case")).toHaveAttribute("data-verdict", "match");
  await expect(detail.getByTestId("tool-case")).toContainText("scale(values=[1,2,3], factor=3.5)");
  await expect(detail.getByTestId("tool-case")).toContainText("Gave what the tutorial got, 2 of 2 times");
  await expect(detail).toContainText("1 call of 1 recorded, each made again 2 times.");
  await expect(detail).toContainText("A number is the same if it is within 0.000001 of the other");
  expect(await accessibilityProblems(page)).toEqual([]);
  await scale.getByRole("button", { name: "Hide the wrapper and the evidence" }).click();
  await expect(detail).toHaveCount(0);

  // It is the same after the page is looked at again, and cannot be made a second time on top of itself
  await page.reload();
  await expect(keptTools(page)).toBeVisible();
  await expect(page.getByTestId("tool")).toHaveCount(1);
  expect((await page.request.post(`/api/paperagents/${id}/tools`, { data: {} })).status()).toBe(409);

  // Taking them away asks first, and leaves what the tutorials gave
  await keptTools(page).getByRole("button", { name: "Take the tools away" }).click();
  const asking = page.getByRole("alertdialog", { name: "Take away the tools of Plain tools?" });
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  await expect(keptTools(page)).toBeVisible();
  await keptTools(page).getByRole("button", { name: "Take the tools away" }).click();
  await page.getByRole("alertdialog", { name: "Take away the tools of Plain tools?" }).getByRole("button", { name: "Take away" }).click();

  await expect(keptTools(page)).toHaveCount(0);
  await expect(toolsPreview(page)).toBeVisible();
  await expect(toolsForm(page)).toBeVisible();
  await expect(step(page, "Build the tools")).toContainText("Not started");
  expect((await toolsOf(page, id)).kept).toBeNull();
  expect((await referenceOf(page, id)).kept).toMatchObject({ complete: true });
  await expect(keptRun(page)).toBeVisible();
});

test("follows the making of tools while it goes on, waits for it before anything else is done to the agent, and keeps what it had made when it is stopped", async ({
  page,
}) => {
  const id = await agentWithTutorials(page, "Tedious tools", { kind: "doi", doi: "10.1000/tools-paper" });
  await toolsForm(page).getByRole("button", { name: MAKE }).click();

  const stop = makingTools(page).getByRole("button", { name: "Stop: Making the tools: Tedious tools" });
  await expect(stop).toBeVisible();
  await expect(step(page, "Build the tools")).toContainText("Going on");
  await expect(toolsForm(page).getByRole("button", { name: "Making…" })).toBeDisabled();
  await expect(page.getByRole("log", { name: "What this printed: Making the tools: Tedious tools" })).toContainText("Calling scale again, 1 call of the tutorials", {
    timeout: 10_000,
  });
  // What is kept of a making that has begun is the account of one that is not over, which is not one that did not come to its end
  expect((await toolsOf(page, id)).kept).toMatchObject({ complete: false, tools: [] });
  await page.reload();
  await expect(stop).toBeVisible();
  await expect(toolsForm(page).getByRole("button", { name: "Making…" })).toBeDisabled();
  await expect(keptTools(page)).toHaveCount(0);
  await expect(page.getByText("did not come to its end")).toHaveCount(0);
  // Nothing else is done to the agent while it goes on, and its paper is not read, and the tutorials are not run again
  await expect(fetchAndRead(page)).toBeDisabled();
  await expect(reading(page)).toContainText("The tools are being made. Reading waits for that.");
  await expect(page.getByRole("button", { name: "Delete Tedious tools" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Take the code away" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Take the environment away" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Take what they gave away" })).toBeDisabled();
  await expect(step(page, "Build the tools")).toContainText("Going on");
  expect(await accessibilityProblems(page)).toEqual([]);

  await stop.click();

  await expect(makingTools(page).getByText("Stopped", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(step(page, "Build the tools")).toContainText("Not started");
  // What came to be before it was stopped is kept, which is nothing here, and is said not to be the whole
  await expect(keptTools(page)).toContainText("Not made to the end");
  await expect(keptTools(page)).toContainText("This making did not come to its end");
  await expect(page.getByTestId("tools-kept-when")).toContainText("No tool was made.");
  await expect(page.getByTestId("tool")).toHaveCount(0);
  await expect(toolsForm(page).getByRole("button", { name: MAKE })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Take what they gave away" })).toBeEnabled();
  expect(await toolsOf(page, id)).toMatchObject({ kept: { complete: false, tools: [] }, job: null });
  expect(await accessibilityProblems(page)).toEqual([]);

  // Made again and left to end, the making replaces what was kept
  await toolsForm(page).getByRole("button", { name: MAKE }).click();
  await expect(keptTools(page)).toContainText("Made to the end of the list", { timeout: 40_000 });
  await expect(keptTools(page)).not.toContainText("Not made to the end");
  await expect(page.getByTestId("tool")).toHaveCount(1);
  await expect(makingTools(page).getByText("Stopped", { exact: true })).toHaveCount(0);
});

test("says which functions were not made into tools, and why, when none held, and when none could be", async ({ page }) => {
  const brittle = await agentWithTutorials(page, "Brittle tools");
  await toolsForm(page).getByRole("button", { name: MAKE }).click();
  await expect(keptTools(page)).toBeVisible({ timeout: 25_000 });
  await expect(page.getByTestId("tools-kept-when")).toContainText("No tool held. 2 functions were not made into a tool.");
  await expect(page.getByTestId("tool")).toHaveCount(0);
  await expect(step(page, "Build the tools")).toContainText("Failed");
  const dropped = page.getByTestId("tools-dropped").getByTestId("tool-dropped");
  await expect(dropped).toHaveCount(2);
  // What differed is said, a call at a time
  await expect(dropped.first()).toContainText("cellmapper.core.scale");
  await expect(dropped.first()).toContainText("[0] is 4.5 where it was 3.5");
  await expect(keptTools(page).getByRole("button", { name: "Take the tools away" })).toBeEnabled();
  expect((await toolsOf(page, brittle)).kept).toMatchObject({ complete: true, tools: [], dropped: [{ kind: "replay_differs" }, { kind: "replay_differs" }] });
  expect(await accessibilityProblems(page)).toEqual([]);

  // Methods of a class are not made into tools, so there is nothing to make, and the asking is refused
  const methods = await agentWithTutorials(page, "Methods tools");
  await expect(page.getByTestId("tools-none")).toContainText("There is nothing to make");
  await expect(page.getByTestId("tools-none")).toContainText("No function that the tutorials called can be made into a tool.");
  await expect(toolsPreview(page).getByTestId("tool-dropped")).toHaveCount(2);
  await expect(toolsPreview(page).getByTestId("tool-dropped").first()).toHaveAttribute("data-kind", "method");
  await expect(toolsPreview(page).getByTestId("tool-dropped").first()).toContainText("A method of a class");
  await expect(toolsForm(page)).toHaveCount(0);
  const asked = await page.request.post(`/api/paperagents/${methods}/tools`, { data: {} });
  expect(asked.status()).toBe(422);
  expect((await asked.json()).error.code).toBe("no_tools");
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("takes away the tools when what the tutorials gave is taken away, and says when Docker is not running", async ({ page }) => {
  const id = await agentWithTutorials(page, "Linked tools");
  await toolsForm(page).getByRole("button", { name: MAKE }).click();
  await expect(keptTools(page)).toBeVisible({ timeout: 25_000 });

  await keptRun(page).getByRole("button", { name: "Take what they gave away" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Take away" }).click();
  await expect(keptRun(page)).toHaveCount(0);
  await expect(page.getByTestId("tools-no-reference")).toBeVisible();
  await expect(keptTools(page)).toHaveCount(0);
  await expect(step(page, "Build the tools")).toContainText("Not started");
  expect((await toolsOf(page, id)).kept).toBeNull();

  await referenceForm(page).getByRole("button", { name: RUN }).click();
  await expect(keptRun(page)).toBeVisible({ timeout: 25_000 });
  await expect(toolsForm(page)).toBeVisible();
  await page.route("**/api/paperagents/*/tools", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();
    const body = await response.json();

    return route.fulfill({ response, json: { ...body, docker: { ready: false, message: "Docker is installed but is not running." } } });
  });
  await page.reload();
  await expect(page.getByText("Docker is installed but is not running. Making tools takes it.")).toBeVisible();
  await expect(toolsPreview(page)).toBeVisible();
  await expect(toolsForm(page).getByRole("button", { name: MAKE })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);
  await page.unroute("**/api/paperagents/*/tools");
});

test("says why the server refused to make the tools, and looks again when what the page shows is out of date", async ({ page }) => {
  const id = await agentWithTutorials(page, "Refused tools");
  await page.route("**/api/paperagents/*/tools", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "docker_missing", message: "Docker is not installed on this machine, and making tools takes it." } }),
        })
      : route.fallback(),
  );
  await toolsForm(page).getByRole("button", { name: MAKE }).click();
  await expect(toolsForm(page).getByRole("alert")).toContainText("Docker is not installed on this machine");
  await page.unroute("**/api/paperagents/*/tools");

  // Tools that were made a moment before the page looked are not a reason to refuse: the page looks again
  let looked = 0;
  await page.route("**/api/paperagents/*/tools", (route) => {
    if (route.request().method() === "GET") looked += 1;

    return route.request().method() === "POST"
      ? route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "done", message: "The tools have been made. Remove them to make them again." } }),
        })
      : route.fallback();
  });
  const before = looked;
  await toolsForm(page).getByRole("button", { name: MAKE }).click();
  await expect.poll(() => looked).toBeGreaterThan(before);
  await expect(toolsForm(page).getByRole("alert")).toHaveCount(0);
  await page.unroute("**/api/paperagents/*/tools");
  expect((await toolsOf(page, id)).kept).toBeNull();

  // What was kept of a tool is gone when it is asked for, which is as the tools were taken away, and the page looks again
  await toolsForm(page).getByRole("button", { name: MAKE }).click();
  await expect(keptTools(page)).toBeVisible({ timeout: 25_000 });
  let seen = 0;
  await page.route("**/api/paperagents/*/tools", (route) => {
    if (route.request().method() === "GET") seen += 1;

    return route.fallback();
  });
  await page.route("**/api/paperagents/*/tools/*", (route) =>
    route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "not_found", message: "There is no such tool." } }) }),
  );
  const again = seen;
  await toolNamed(page, "scale").getByRole("button", { name: "Show the wrapper and the evidence" }).click();
  await expect.poll(() => seen).toBeGreaterThan(again);
  await expect(page.getByTestId("tool-detail")).toHaveCount(0);
  await expect(keptTools(page)).toBeVisible();
  await page.unroute("**/api/paperagents/*/tools/*");
  await page.unroute("**/api/paperagents/*/tools");
});
