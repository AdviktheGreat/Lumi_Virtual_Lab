import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { Locator, Page, Route } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { answered, askWhereCodeRuns, expect, test } from "../fixtures";

// The runs and the agents are the workspace's, and a conversation made while a run is given its functions is given them, so
// each test takes what it made away, and none is run beside another
test.describe.configure({ mode: "serial" });

const DESEQ = "Differential expression was found with DESeq2, from samples in GEO, aligned with STAR.";
const SCANPY = "Cells were clustered with Scanpy, and DESeq2 was used to find the markers.";
const TASK = "RNA-seq differential expression with DESeq2";

// Takes away every agent, and then every run, stopping what is at work on one first
async function clear(page: Page) {
  const { jobs } = await (await page.request.get("/api/setup/jobs")).json();
  const working = ["paperagent-onego", "paperagent-reading", "paperagent-repository", "paperagent-environment", "paperagent-data", "paperagent-reference", "paperagent-tools", "paperagent-checks", "paperagent-reproduction", "paperagent-variant", "paperagent-reimplementation", "paperagent-reimplementation-checks"];
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
  await expect(page.getByTestId("card-status")).toContainText("all that was checked of a fact is that its words are in the paper");

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

const card = (page: Page) => page.getByTestId("card-status");
const cardList = (page: Page, name: string) => page.getByRole("list", { name, exact: true });
const cardOf = async (page: Page, id: string) => (await (await page.request.get(`/api/paperagents/${id}/reading`)).json()).card;

test("says that the card is of the paper's file, which an agent without one has not", async ({ page }) => {
  const id = await makeAgent(page, { title: "No file", paper: { kind: "file" } });
  await openAgent(page, id, "No file");

  await expect(page.getByRole("heading", { name: "Method card", level: 2 })).toBeVisible();
  await expect(page.getByText("The card is kept with the paper's file, which is not here yet.", { exact: false })).toBeVisible();
  await expect(card(page)).toHaveCount(0);
});

test("lets a person correct the method card and approve it, with what they did marked as theirs", async ({ page }) => {
  const id = await makeAgent(page, { title: "Card corrector", paper: { kind: "file" } });
  await openAgent(page, id, "Card corrector");
  await page.getByLabel("Upload the paper").setInputFiles({ name: "cells.txt", mimeType: "text/plain", buffer: Buffer.from(CELLS) });
  await expect(page.getByTestId("paper-agent-file")).toContainText("cells.txt");

  // A card by hand can be begun before the paper is read, and nothing on it is not approved
  await expect(card(page)).toHaveAttribute("data-status", "draft");
  await expect(page.getByRole("button", { name: "Approve the card" })).toBeDisabled();
  await expect(card(page)).toContainText("There is nothing on the card to approve.");

  await reading(page).getByLabel("Most it may spend, in dollars").fill("2");
  await reading(page).getByRole("button", { name: "Read the paper" }).click();
  await expect(summary(page)).toContainText("Read 1 of 1 chunk", { timeout: 15_000 });

  // What was read is the model's, and a draft that nobody has approved
  await expect(card(page)).toContainText("A model made this from the paper");
  await expect(cardList(page, "What the method was tested on").getByTestId("card-fact")).toHaveAttribute("data-by", "reading");
  await expect(cardList(page, "What the method was tested on")).toContainText("Read by the model");
  await expect(page.getByRole("button", { name: "Discard what I did" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Change: / })).toHaveCount(2);
  // A limit that was read is the authors' sentence, which is not changed
  await expect(cardList(page, "Where the authors say it falls short")).toContainText("The authors' sentence is not changed");
  expect(await accessibilityProblems(page)).toEqual([]);

  // A fact that was read is changed, which keeps the paper's words and says what it was read as
  await page.getByRole("button", { name: "Change: mouse" }).click();
  const changing = form(page, "Change: mouse");
  expect(await accessibilityProblems(page)).toEqual([]);
  await changing.getByLabel("What it was tested on").fill("   ");
  await changing.getByRole("button", { name: "Save it" }).click();
  await expect(changing.getByText("Say what it was tested on.")).toBeVisible();
  await changing.getByLabel("What it was tested on").fill("rat");
  await changing.getByLabel("What it is about").selectOption("species");
  await changing.getByRole("button", { name: "Save it" }).click();
  const species = cardList(page, "What the method was tested on");
  await expect(species.getByTestId("card-fact")).toHaveAttribute("data-by", "person");
  await expect(species).toContainText("rat");
  await expect(species).toContainText("Changed by you");
  await expect(species).toContainText("The model read it as: species: mouse");
  await expect(species.getByRole("blockquote")).toHaveText(LIMIT);
  await expect(species.getByRole("button", { name: /^Show in the paper: / })).toBeVisible();
  await expect(card(page)).toContainText("What you did to it: 1 changed.");
  await expect(page.getByRole("button", { name: "Discard what I did" })).toBeVisible();
  const kept = await cardOf(page, id);
  expect(kept.scope[0]).toMatchObject({ by: "person", value: "rat", read_as: { aspect: "species", value: "mouse" } });
  expect(kept.scope[0].anchor).not.toBeNull();

  // A fact that a person adds has their words and no place in the paper, and says so
  await page.getByRole("button", { name: "Add a dataset" }).click();
  const adding = form(page, "Add a dataset");
  await adding.getByRole("button", { name: "Add it" }).click();
  await expect(adding.getByText("Say what the dataset is called.")).toBeVisible();
  await adding.getByLabel("What it is called").fill("Our reads");
  await adding.getByLabel("Its accession, if it has one").fill("GSE999999");
  await adding.getByLabel("Your words for it, if you have some").fill("Table S1 of the supplement");
  await adding.getByRole("button", { name: "Add it" }).click();
  const datasets = cardList(page, "Data used");
  const ours = datasets.getByTestId("card-fact").filter({ hasText: "Our reads" });
  await expect(ours).toHaveAttribute("data-by", "person");
  await expect(ours).toContainText("Added by you");
  await expect(ours).toContainText("GSE999999");
  await expect(ours).toContainText("Your words");
  await expect(ours.getByRole("blockquote")).toHaveText("Table S1 of the supplement");
  await expect(ours.getByRole("button", { name: /^Show in the paper/ })).toHaveCount(0);
  await expect(datasets.getByTestId("card-fact")).toHaveCount(2);

  // A fact that the card has already is refused, with what the server says
  await page.getByRole("button", { name: "Add a dataset" }).click();
  const again = form(page, "Add a dataset");
  await again.getByLabel("What it is called").fill("GEO again");
  await again.getByLabel("Its accession, if it has one").fill("GSE123456");
  await again.getByRole("button", { name: "Add it" }).click();
  await expect(again.getByRole("alert")).toContainText("The card has that already");
  await again.getByRole("button", { name: "Cancel" }).click();
  await expect(again).toHaveCount(0);

  // The data part has the card's datasets, and says which is the person's
  const data = page.getByRole("list", { name: "Datasets the paper names" });
  await expect(data.getByTestId("data-dataset")).toHaveCount(2);
  const own = data.getByTestId("data-dataset").filter({ hasText: "Our reads" });
  await expect(own).toContainText("You added it to the method card");
  await expect(own).toContainText("Its accession is of");
  expect(await accessibilityProblems(page)).toEqual([]);

  // Approving is of the card as it is, and says what it is, which is not that it is right
  await page.getByRole("button", { name: "Approve the card" }).click();
  await expect(card(page)).toHaveAttribute("data-status", "approved");
  await expect(card(page)).toContainText("which is not that it is right");
  expect((await cardOf(page, id)).status).toBe("approved");

  // Any change makes it a draft again, and putting it back makes it the card that was approved
  await page.getByRole("button", { name: "Take off: GEO" }).click();
  await expect(card(page)).toHaveAttribute("data-status", "draft");
  await expect(card(page)).toContainText("has changed since");
  await expect(card(page)).toContainText("1 taken off");
  await expect(datasets.getByTestId("card-fact")).toHaveCount(1);
  await page.getByText("Taken off (1)").click();
  await page.getByRole("button", { name: "Put back: GEO" }).click();
  await expect(datasets.getByTestId("card-fact")).toHaveCount(2);
  await expect(card(page)).toHaveAttribute("data-status", "approved");
  await page.getByRole("button", { name: "Take the approval back" }).click();
  await expect(card(page)).toHaveAttribute("data-status", "draft");
  await expect(card(page)).not.toContainText("has changed since");

  // A fact that a person added is gone when it is taken off, which is asked
  await page.getByRole("button", { name: "Take off: Our reads" }).click();
  const asking = page.getByRole("alertdialog", { name: "Take this off the card?" });
  await expect(asking).toContainText("cannot be put back");
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(datasets.getByTestId("card-fact")).toHaveCount(2);
  await page.getByRole("button", { name: "Take off: Our reads" }).click();
  await page.getByRole("alertdialog", { name: "Take this off the card?" }).getByRole("button", { name: "Take off" }).click();
  await expect(datasets.getByTestId("card-fact")).toHaveCount(1);
  expect((await cardOf(page, id)).removed.datasets).toHaveLength(0);

  // What a person did is kept when the reading is cleared, and is put over the next reading
  await page.getByRole("button", { name: "Clear the reading" }).click();
  await page.getByRole("alertdialog", { name: "Clear the reading of Card corrector?" }).getByRole("button", { name: "Clear", exact: true }).click();
  await expect(page.getByRole("list", { name: "What the authors report" })).toHaveCount(0);
  await expect(species).toContainText("rat");
  await reading(page).getByRole("button", { name: "Read the paper" }).click();
  await expect(summary(page)).toContainText("Read 1 of 1 chunk", { timeout: 15_000 });
  await expect(species).toContainText("Changed by you");
  await expect(species).toContainText("The model read it as: species: mouse");
  await expect(species.getByTestId("card-fact")).toHaveCount(1);

  // A fact that a person changed is changed back to what was read, which is then no change at all
  await page.getByRole("button", { name: "Change back: rat" }).click();
  await expect(species).toContainText("mouse");
  await expect(species).toContainText("Read by the model");
  await expect(page.getByRole("button", { name: "Discard what I did" })).toHaveCount(0);
  expect((await cardOf(page, id)).edited).toBe(false);

  // Discarding what a person did gives back the card that the reading made
  await page.getByRole("button", { name: "Add a method" }).click();
  await form(page, "Add a method").getByLabel("What it is called").fill("Our method");
  await form(page, "Add a method").getByRole("button", { name: "Add it" }).click();
  const methods = page.locator('[data-kind="methods"]');
  await expect(methods).toContainText("Our method");
  await page.getByRole("button", { name: "Discard what I did" }).click();
  const discarding = page.getByRole("alertdialog", { name: "Discard what you did to the card?" });
  await discarding.getByRole("button", { name: "Keep" }).click();
  await expect(methods).toContainText("Our method");
  await page.getByRole("button", { name: "Discard what I did" }).click();
  await page.getByRole("alertdialog", { name: "Discard what you did to the card?" }).getByRole("button", { name: "Discard" }).click();
  await expect(methods).toContainText("No method is on the card.");
  await expect(page.getByRole("button", { name: "Discard what I did" })).toHaveCount(0);
  expect((await cardOf(page, id)).edited).toBe(false);
  // The button to approve has just been switched on, and its colours are not looked at while they change
  await expect(page.getByRole("button", { name: "Approve the card" })).toBeEnabled();
  await page.waitForTimeout(400);
  expect(await accessibilityProblems(page)).toEqual([]);
});

const scopeCheck = (page: Page) => page.getByTestId("scope-check");
const checkingData = (page: Page) => form(page, "Check my data against the card");
const scopeResult = (page: Page) => scopeCheck(page).getByTestId("scope-result");
const scopeWarnings = (page: Page) => scopeCheck(page).getByTestId("scope-warning");
const scopeAnswer = (page: Page, aspect: string) => scopeResult(page).locator(`[data-testid="scope-answer"][data-aspect="${aspect}"]`);

// Says what the data is, and asks for it to be put against the card, which clears what was said before
async function checkData(page: Page, said: Record<string, string>) {
  const checking = checkingData(page);
  for (const label of ["Species", "Tissue", "Assay", "Input format", "Sample size", "What the size counts"]) {
    await checking.getByLabel(label).fill(said[label] ?? "");
  }
  await checking.getByRole("button", { name: "Check it" }).click();
}

test("puts a person's data against the method card, with a warning that quotes the card where it is outside", async ({ page }) => {
  const id = await makeAgent(page, { title: "Scope checker", paper: { kind: "file" } });
  await openAgent(page, id, "Scope checker");
  // An agent with no file has no card, and so nothing to check against
  await expect(scopeCheck(page)).toHaveCount(0);
  await page.getByLabel("Upload the paper").setInputFiles({ name: "cells.txt", mimeType: "text/plain", buffer: Buffer.from(CELLS) });
  await expect(page.getByTestId("paper-agent-file")).toContainText("cells.txt");

  // Before the paper is read the card has nothing on it, so nothing is outside and nothing is inside, and it says so
  await expect(scopeCheck(page).getByRole("heading", { name: "Check my data against the card", level: 3 })).toBeVisible();
  await expect(scopeCheck(page)).toContainText("The card has no statement of what the method was tested on yet");
  await checkData(page, { Species: "human" });
  await expect(scopeResult(page)).toHaveAttribute("data-outcome", "not covered");
  await expect(scopeAnswer(page, "species")).toContainText("The card has no statement of the species.");
  await expect(scopeWarnings(page)).toHaveCount(0);
  await expect(scopeResult(page)).toContainText("The paper has not been read, so the card is what a person put on it.");

  await reading(page).getByLabel("Most it may spend, in dollars").fill("2");
  await reading(page).getByRole("button", { name: "Read the paper" }).click();
  await expect(summary(page)).toContainText("Read 1 of 1 chunk", { timeout: 15_000 });
  // The card is of what the paper said, and the answer that was given before it is not
  await expect(scopeCheck(page).getByTestId("scope-stale")).toContainText("The card has changed since you checked");
  await expect(scopeResult(page)).toHaveCount(0);

  // Nothing said of the data is not checked, and what cannot be sent is said where it is typed, and nothing is sent
  const sent: string[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith(`/paperagents/${id}/scope-check`)) sent.push(request.postData() ?? "");
  });
  const checking = checkingData(page);
  await checkData(page, {});
  await expect(checking.getByRole("alert")).toContainText("Say something of your data");
  await checkData(page, { "Sample size": "many", "What the size counts": "cells" });
  await expect(checking.getByText("The sample size is a whole number, one or more.")).toBeVisible();
  expect(sent).toEqual([]);
  expect(await accessibilityProblems(page)).toEqual([]);

  // Data outside what the card says is warned of, with the card's words and the paper's, and the person can go on
  await checkData(page, { Species: "  human " });
  await expect(scopeResult(page)).toHaveAttribute("data-outcome", "outside");
  await expect(scopeResult(page)).toContainText("One thing is outside.");
  await expect(scopeResult(page)).toContainText("You can go on.");
  await expect(scopeWarnings(page)).toHaveCount(1);
  await expect(scopeWarnings(page).first()).toHaveText(
    `Outside what the card says: the data's species is “human”, and the card gives the species as “mouse” (the paper: “${LIMIT}”).`,
  );
  await expect(scopeAnswer(page, "species")).toHaveAttribute("data-outcome", "outside");
  await expect(scopeAnswer(page, "species").getByTestId("scope-statement")).toContainText("Read by the model");
  await expect(scopeAnswer(page, "species").getByRole("blockquote")).toHaveText(LIMIT);
  // What was sent is what was said, with nothing that was left blank
  expect(sent.map((body) => JSON.parse(body))).toEqual([{ species: "human" }]);
  await expect(scopeResult(page)).toContainText("A model made this from the paper");
  expect(await accessibilityProblems(page)).toEqual([]);

  // Data that is inside gets no warning, whatever the name that it is given
  await checkData(page, { Species: "Mus musculus" });
  await expect(scopeResult(page)).toHaveAttribute("data-outcome", "inside");
  await expect(scopeWarnings(page)).toHaveCount(0);
  await expect(scopeResult(page)).toContainText("not that it works on yours");
  await expect(scopeAnswer(page, "species")).toHaveAttribute("data-outcome", "inside");

  // What the card does not say of is not called inside, and not warned of, and what it does say is shown
  await checkData(page, { Species: "mouse", Tissue: "liver" });
  await expect(scopeResult(page)).toHaveAttribute("data-outcome", "not covered");
  await expect(scopeAnswer(page, "tissue")).toContainText("The card has no statement of the tissue.");
  await expect(scopeWarnings(page)).toHaveCount(0);
  await checkData(page, { Tissue: "liver" });
  await expect(scopeResult(page).getByText("What else the card says (1)")).toBeVisible();
  await scopeResult(page).getByText("What else the card says (1)").click();
  await expect(scopeResult(page).getByRole("list", { name: "What else the card says" })).toContainText("mouse");

  // A statement that a person adds is put against the data and is said to be theirs, with their words
  await page.getByRole("button", { name: "Add what it was tested on" }).click();
  const adding = form(page, "Add what it was tested on");
  await adding.getByLabel("What it is about").selectOption("sample size");
  await adding.getByLabel("What it was tested on").fill("at least 500 nuclei");
  await adding.getByLabel("Your words for it, if you have some").fill("Our protocol needs this");
  await adding.getByRole("button", { name: "Add it" }).click();
  await expect(cardList(page, "What the method was tested on").getByTestId("card-fact")).toHaveCount(2);
  await expect(scopeCheck(page).getByTestId("scope-stale")).toBeVisible();
  await checkData(page, { Species: "human", "Sample size": "1,200", "What the size counts": "nuclei" });
  await expect(scopeResult(page)).toHaveAttribute("data-outcome", "outside");
  await expect(scopeAnswer(page, "sample size")).toHaveAttribute("data-outcome", "inside");
  await expect(scopeAnswer(page, "sample size")).toContainText("1,200 nuclei");
  await expect(scopeWarnings(page)).toHaveCount(1);
  await checkData(page, { "Sample size": "120", "What the size counts": "nuclei" });
  await expect(scopeResult(page)).toHaveAttribute("data-outcome", "outside");
  await expect(scopeWarnings(page).first()).toHaveText(
    "Outside what the card says: the data's sample size is “120 nuclei”, and the card gives the sample size as " +
      "“at least 500 nuclei” (added by a person: “Our protocol needs this”).",
  );
  await expect(scopeAnswer(page, "sample size").getByTestId("scope-statement")).toHaveAttribute("data-by", "person");
  await expect(scopeAnswer(page, "sample size")).toContainText("Added by you");
  // A size with nothing said of what it counts is not put against a size that counts something
  await checkData(page, { "Sample size": "120" });
  await expect(scopeResult(page)).toHaveAttribute("data-outcome", "not covered");
  await expect(scopeAnswer(page, "sample size")).toContainText("Say what the size counts.");
  await expect(scopeWarnings(page)).toHaveCount(0);

  // A person's change to a statement is what the data is put against, with the paper's words beside it
  await page.getByRole("button", { name: "Change: mouse" }).click();
  const changing = form(page, "Change: mouse");
  await changing.getByLabel("What it was tested on").fill("rat");
  await changing.getByRole("button", { name: "Save it" }).click();
  await expect(scopeCheck(page).getByTestId("scope-stale")).toBeVisible();
  await checkData(page, { Species: "mouse" });
  await expect(scopeResult(page)).toHaveAttribute("data-outcome", "outside");
  await expect(scopeWarnings(page).first()).toHaveText(
    `Outside what the card says: the data's species is “mouse”, and the card gives the species as “rat” (changed by a person; the paper's words: “${LIMIT}”).`,
  );
  await expect(scopeAnswer(page, "species")).toContainText("Changed by you");
  await checkData(page, { Species: "rat" });
  await expect(scopeResult(page)).toHaveAttribute("data-outcome", "inside");
  await expect(scopeWarnings(page)).toHaveCount(0);

  // An answer is of the card as it was, so it is gone when the card is approved, and says that it is a person's
  await page.getByRole("button", { name: "Approve the card" }).click();
  await expect(card(page)).toHaveAttribute("data-status", "approved");
  await expect(scopeCheck(page).getByTestId("scope-stale")).toBeVisible();
  await checkData(page, { Species: "human" });
  await expect(scopeResult(page)).toContainText("You approved this card");
  await expect(scopeResult(page)).toContainText("which is not that it is right");
  await expect(scopeResult(page)).toHaveAttribute("data-outcome", "outside");
  await expect(scopeWarnings(page)).toHaveCount(1);
  // The button was switched on and off a moment ago, and its colours are not looked at while they change
  await page.waitForTimeout(400);
  expect(await accessibilityProblems(page)).toEqual([]);

  // Checking changes nothing on the card
  const kept = await cardOf(page, id);
  expect(kept.scope).toHaveLength(2);
  expect(kept.status).toBe("approved");
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
async function agentWithTutorials(page: Page, title: string, paper: Record<string, unknown> = { kind: "file" }, repo = CODE_ADDRESS): Promise<string> {
  const id = await agentWithEnvironment(page, title, repo, paper);
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
  // It says what was and was not shown, and where a conversation is given the tools
  await expect(keptTools(page)).toContainText("does not show that");
  await expect(keptTools(page)).toContainText("A conversation is given the tools when the agent is given to conversations, under In conversations below.");

  await expect(page.getByTestId("tool")).toHaveCount(1);
  const scale = toolNamed(page, "scale");
  await expect(scale).toContainText("scale(values, factor)");
  await expect(scale).toContainText("Made as tier A");
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

// The code of an agent that has a test that calls scale, which is what the tests that come with the code are looked for in
const TESTED_ADDRESS = "https://github.com/example/tested-cellmapper";
const checksForm = (page: Page) => form(page, "Check the tools");
const checkingTools = (page: Page) => page.getByRole("region", { name: "Checking the tools" });
const keptChecks = (page: Page) => page.getByTestId("checks-kept");
const checkedTool = (page: Page, name: string) => page.locator(`[data-testid=checked-tool][data-name=${name}]`);
const checksOf = async (page: Page, id: string) => (await page.request.get(`/api/paperagents/${id}/checks`)).json();
const CHECK = "Check the tools";
const kindNamed = (page: Page, kind: string) => checksForm(page).locator(`[data-testid=check-kind][data-kind=${kind}]`);
const checkOf = (page: Page, tool: string, kind: string) => checkedTool(page, tool).locator(`[data-testid=check][data-kind=${kind}]`);

// Makes an agent whose tools are made, so that what a test is about is their checks, and opens it
async function agentWithTools(page: Page, title: string, paper: Record<string, unknown> = { kind: "file" }, repo = TESTED_ADDRESS): Promise<string> {
  const id = await agentWithTutorials(page, title, paper, repo);
  const started = await page.request.post(`/api/paperagents/${id}/tools`, { data: {} });
  expect(started.status()).toBe(202);
  await expect.poll(async () => (await toolsOf(page, id)).job, { timeout: 30_000 }).toBeNull();
  expect((await toolsOf(page, id)).kept).toMatchObject({ complete: true });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Checks", level: 2, exact: true })).toBeVisible();

  return id;
}

test("says that there is nothing to check until tools are made, and offers the checks once there are", async ({ page }) => {
  const id = await agentWithTutorials(page, "Unmade checks", { kind: "file" }, TESTED_ADDRESS);
  await expect(page.getByRole("heading", { name: "Checks", level: 2, exact: true })).toBeVisible();
  await expect(page.getByTestId("checks-no-tools")).toHaveText("Make the tools first. Checks are of the tools that were made.");
  await expect(checksForm(page)).toHaveCount(0);
  const asked = await page.request.post(`/api/paperagents/${id}/checks`, { data: {} });
  expect(asked.status()).toBe(422);
  expect((await asked.json()).error.code).toBe("no_tools");
  expect(await checksOf(page, id)).toMatchObject({ made: false, tools: [], job: null });
  expect(await accessibilityProblems(page)).toEqual([]);

  // Once the tools are made the page looks again, and they can be checked
  await toolsForm(page).getByRole("button", { name: MAKE }).click();
  await expect(keptTools(page)).toBeVisible({ timeout: 25_000 });
  await expect(page.getByTestId("checks-no-tools")).toHaveCount(0);
  await expect(checksForm(page)).toBeVisible();
  await expect(checkedTool(page, "scale")).toHaveAttribute("data-tier", "A");
});

test("says what each kind of check is against, asks for what is wrong with the asking to be put right, checks the tools, which makes one of tier B, shows how each check went and what it was made of, and takes the checks away", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const id = await agentWithTools(page, "Tested checks");
  await expect(checkedTool(page, "scale")).toHaveAttribute("data-tier", "A");
  await expect(page.getByTestId("checks-tiers")).toHaveText("1 tool: 1 of tier A.");
  await expect(checkedTool(page, "scale")).toContainText("Made as tier A. No check of it has passed.");
  await expect(page.getByTestId("checks-needs")).toContainText("To be of tier B it needs a check that passes against 2 more of:");
  await expect(page.getByTestId("checks-meaning")).toContainText("A check that is not obtained could not be made, which is neither for the tool nor against it.");
  await expect(keptChecks(page).getByRole("button", { name: "Take the checks away" })).toHaveCount(0);

  // The kinds are said, with what each is against, and those that ask a model are told from those that do not
  await expect(checksForm(page).getByTestId("check-kind")).toHaveCount(4);
  await expect(kindNamed(page, "heldout").getByRole("checkbox")).toBeChecked();
  await expect(kindNamed(page, "repo_tests").getByRole("checkbox")).toBeChecked();
  await expect(kindNamed(page, "paper_numbers").getByRole("checkbox")).not.toBeChecked();
  await expect(kindNamed(page, "verifier").getByRole("checkbox")).not.toBeChecked();
  await expect(kindNamed(page, "heldout")).not.toContainText("Asks a model");
  await expect(kindNamed(page, "paper_numbers")).toContainText("Asks a model");
  await expect(kindNamed(page, "verifier")).toContainText("Asks a model");
  await expect(kindNamed(page, "heldout")).toContainText("Against the code's own function, called with inputs that the tutorial did not pass.");
  await expect(kindNamed(page, "repo_tests")).toContainText("Against the tests that come with the code.");
  // The paper was not read, so it has no number to look for
  await expect(kindNamed(page, "paper_numbers").getByRole("checkbox")).toBeDisabled();
  await expect(kindNamed(page, "paper_numbers")).toContainText("Not available: The paper has no number that it reports with digits enough to be looked for.");
  await expect(checksForm(page).getByLabel("Most it may spend, in dollars")).toHaveCount(0);
  await expect(checksForm(page).getByLabel("The model that chooses the inputs")).toHaveCount(0);
  await expect(checksForm(page)).toContainText("no network");
  expect(await accessibilityProblems(page)).toEqual([]);

  // What is wrong with the asking is said before it is sent
  await checksForm(page).getByLabel("Most time for one check of one tool, in minutes").fill("0");
  await checksForm(page).getByLabel("Most time for all of the checks, in minutes").fill("500");
  await checksForm(page).getByLabel("How many times each call is made").fill("9");
  await checksForm(page).getByLabel("Most one run may write, in gigabytes").fill("many");
  await kindNamed(page, "heldout").getByRole("checkbox").uncheck();
  await kindNamed(page, "repo_tests").getByRole("checkbox").uncheck();
  await checksForm(page).getByRole("button", { name: CHECK }).click();
  await expect(checksForm(page).getByText(/for one check of one tool, in minutes, is a whole number from 1 to 30/)).toBeVisible();
  await expect(checksForm(page).getByText(/for all of the checks, in minutes, is a whole number from 1 to 180/)).toBeVisible();
  await expect(checksForm(page).getByText(/How many times each call is made is a whole number from 1 to 3/)).toBeVisible();
  await expect(checksForm(page).getByText(/in gigabytes, is a whole number from 1 to 20/)).toBeVisible();
  await expect(checksForm(page).getByText("Choose at least one kind of check.")).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  expect((await checksOf(page, id)).tools[0].evidence.every((entry: { file: string | null }) => entry.file === null)).toBe(true);

  // A kind that asks a model asks what it may spend, and the one that chooses inputs asks which model does
  await kindNamed(page, "verifier").getByRole("checkbox").check();
  await expect(checksForm(page).getByLabel("Most it may spend, in dollars")).toBeVisible();
  await expect(checksForm(page).getByLabel("The model that chooses the inputs")).toBeVisible();
  await checksForm(page).getByRole("button", { name: CHECK }).click();
  await expect(checksForm(page).getByText(/most it may spend/i).first()).toBeVisible();
  await expect(checksForm(page).getByText("Name the model that chooses the inputs, of another family than the one in the settings.")).toBeVisible();
  await checksForm(page).getByLabel("The model that chooses the inputs").fill("GPT-5.2");
  await checksForm(page).getByRole("button", { name: CHECK }).click();
  await expect(checksForm(page).getByText(/is the model in the settings/)).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  await kindNamed(page, "verifier").getByRole("checkbox").uncheck();
  await expect(checksForm(page).getByLabel("Most it may spend, in dollars")).toHaveCount(0);
  await kindNamed(page, "heldout").getByRole("checkbox").check();
  await kindNamed(page, "repo_tests").getByRole("checkbox").check();
  await checksForm(page).getByLabel("Most time for one check of one tool, in minutes").fill("5");
  await checksForm(page).getByLabel("Most time for all of the checks, in minutes").fill("30");
  await checksForm(page).getByLabel("How many times each call is made").fill("2");
  await checksForm(page).getByLabel("Most one run may write, in gigabytes").fill("2");
  await checksForm(page).getByRole("button", { name: CHECK }).click();

  // Two kinds that need no model are made, which are against two different things, so the tool is of tier B
  await expect(checkedTool(page, "scale")).toHaveAttribute("data-tier", "B", { timeout: 40_000 });
  await expect(checksForm(page).getByRole("button", { name: CHECK })).toBeEnabled();
  await expect(page.getByTestId("checks-tiers")).toHaveText("1 tool: 1 of tier B.");
  await expect(checkedTool(page, "scale")).toContainText("Made as tier A. It passed checks against 2 different things:");
  await expect(checkedTool(page, "scale")).toContainText("2 of 4 kinds of check passed");
  await expect(page.getByTestId("checks-needs")).toHaveCount(0);
  await expect(step(page, "Build the tools")).toContainText("Done");
  // The tools section still says what each was made as, and not what it has become
  await expect(toolNamed(page, "scale")).toContainText("Made as tier A");
  const kept = await checksOf(page, id);
  expect(kept.tools[0]).toMatchObject({ name: "scale", tier: "B", made_as: "A", passed: ["heldout", "repo_tests"] });

  // How each kind went is opened by the tier, and what it was made of is got when it is asked for
  const tier = checkedTool(page, "scale").getByRole("button", { name: /Tier B/ });
  await expect(tier).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("check")).toHaveCount(0);
  await tier.click();
  await expect(tier).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("check")).toHaveCount(4);
  await expect(checkOf(page, "scale", "heldout")).toHaveAttribute("data-status", "passed");
  await expect(checkOf(page, "scale", "repo_tests")).toHaveAttribute("data-status", "passed");
  await expect(checkOf(page, "scale", "paper_numbers")).toHaveAttribute("data-status", "not_run");
  await expect(checkOf(page, "scale", "verifier")).toHaveAttribute("data-status", "not_run");
  await expect(checkOf(page, "scale", "heldout").getByTestId("check-status")).toHaveText("Passed");
  await expect(checkOf(page, "scale", "heldout")).toContainText("gave the same through the tool as from the code's own function");
  await expect(checkOf(page, "scale", "heldout")).toContainText("Against the code's own function");
  await expect(checkOf(page, "scale", "repo_tests")).toContainText("1 test of the code that call the function passed");
  await expect(checkOf(page, "scale", "paper_numbers")).toContainText("Not made");
  await expect(page.getByTestId("check-detail")).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);
  await checkedTool(page, "scale").getByRole("button", { name: "Show what each check was made of" }).click();
  await expect(checkedTool(page, "scale").getByRole("button", { name: "Hide what each check was made of" })).toBeVisible();
  const heldout = checkOf(page, "scale", "heldout");
  await expect(heldout.getByTestId("check-detail").filter({ hasText: "How the calls went" })).toContainText("1 call gave the same through the tool as from the code's own function. Each call was made 2 times.");
  await expect(heldout.getByRole("list", { name: "Calls that were changed" })).toContainText(/nudged: \{'values': \[2, 3, 4\], 'factor': 3\.85\d*\}: the tool and the code's own function gave the same/);
  await expect(checkOf(page, "scale", "repo_tests").getByRole("list", { name: "Tests that call the function" })).toContainText("tests/test_scale.py::test_scale_doubles");
  await expect(checkOf(page, "scale", "repo_tests")).toContainText("1 test ran: 1 passed, 0 failed, 0 stopped with an error, and 0 were skipped.");
  expect(await accessibilityProblems(page)).toEqual([]);
  await checkedTool(page, "scale").getByRole("button", { name: "Hide what each check was made of" }).click();
  await expect(page.getByTestId("check-detail")).toHaveCount(0);
  await tier.click();
  await expect(page.getByTestId("check")).toHaveCount(0);

  // It is the same after the page is looked at again
  await page.reload();
  await expect(checkedTool(page, "scale")).toHaveAttribute("data-tier", "B");

  // Taking them away asks first, and leaves the tools, which are of the tier they were made as
  await keptChecks(page).getByRole("button", { name: "Take the checks away" }).click();
  const asking = page.getByRole("alertdialog", { name: "Take away the checks of the tools of Tested checks?" });
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  await expect(checkedTool(page, "scale")).toHaveAttribute("data-tier", "B");
  await keptChecks(page).getByRole("button", { name: "Take the checks away" }).click();
  await page.getByRole("alertdialog", { name: "Take away the checks of the tools of Tested checks?" }).getByRole("button", { name: "Take away" }).click();
  await expect(checkedTool(page, "scale")).toHaveAttribute("data-tier", "A");
  await expect(keptChecks(page).getByRole("button", { name: "Take the checks away" })).toHaveCount(0);
  await expect(page.getByTestId("tool")).toHaveCount(1);
  expect((await checksOf(page, id)).tools[0]).toMatchObject({ tier: "A", passed: [] });
});

test("a check that fails keeps a tool from tier B, and says which and why", async ({ page }) => {
  test.setTimeout(90_000);
  const id = await agentWithTools(page, "Differing unsound checks");
  await checksForm(page).getByRole("button", { name: CHECK }).click();
  await expect(checkedTool(page, "scale")).toContainText("A check failed, which keeps it from tier B until it is checked again and none fails.", { timeout: 40_000 });
  await expect(checkedTool(page, "scale")).toHaveAttribute("data-tier", "A");
  await expect(page.getByTestId("checks-tiers")).toHaveText("1 tool: 1 of tier A.");
  await expect(page.getByTestId("checks-needs")).toHaveCount(0);
  await expect(checkedTool(page, "scale")).toContainText("0 of 4 kinds of check passed");
  expect((await checksOf(page, id)).tools[0].evidence.filter((entry: { status: string }) => entry.status === "failed").map((entry: { kind: string }) => entry.kind)).toEqual(["heldout", "repo_tests"]);

  await checkedTool(page, "scale").getByRole("button", { name: /Tier A/ }).click();
  await expect(checkOf(page, "scale", "heldout")).toHaveAttribute("data-status", "failed");
  await expect(checkOf(page, "scale", "heldout").getByTestId("check-status")).toHaveText("Failed");
  await expect(checkOf(page, "scale", "heldout")).toContainText("1 of 1 changed calls did not give the same through the tool as from the code's own function.");
  await expect(checkOf(page, "scale", "repo_tests")).toHaveAttribute("data-status", "failed");
  await expect(checkOf(page, "scale", "repo_tests")).toContainText("1 of the 1 tests of the code that call the function did not pass.");
  await checkedTool(page, "scale").getByRole("button", { name: "Show what each check was made of" }).click();
  await expect(checkOf(page, "scale", "repo_tests").getByRole("list", { name: "Tests that did not pass" })).toContainText("tests/test_scale.py::test_scale_doubles: assert [2.5] == [2.0]");
  await expect(checkOf(page, "scale", "heldout").getByRole("list", { name: "Calls that were changed" })).toContainText("they gave something else");
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("follows the checking while it goes on, waits for it before anything else is done to the agent, and keeps what it had made when it is stopped", async ({ page }) => {
  test.setTimeout(90_000);
  const id = await agentWithTools(page, "Unhurried checks", { kind: "doi", doi: "10.1000/unhurried-paper" });
  await checksForm(page).getByRole("button", { name: CHECK }).click();

  const stop = checkingTools(page).getByRole("button", { name: "Stop: Checking the tools: Unhurried checks" });
  await expect(stop).toBeVisible();
  await expect(step(page, "Build the tools")).toContainText("Going on");
  await expect(checkingTools(page)).toContainText("Checking the tools: scale (1 of 2)");
  // What is kept is shown when the checking is over, and the form is not offered again while it goes on
  await expect(keptChecks(page)).toHaveCount(0);
  await expect(checksForm(page)).toHaveCount(0);
  expect((await checksOf(page, id)).job).not.toBeNull();
  await page.reload();
  await expect(stop).toBeVisible();
  await expect(keptChecks(page)).toHaveCount(0);
  // Nothing else is done to the agent while it goes on, and its paper is not read
  await expect(fetchAndRead(page)).toBeDisabled();
  await expect(reading(page)).toContainText("The tools are being checked. Reading waits for that.");
  await expect(page.getByRole("button", { name: "Delete Unhurried checks" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Take the tools away" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Take the code away" })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);
  const refused = await page.request.post(`/api/paperagents/${id}/checks`, { data: {} });
  expect(refused.status()).toBe(409);

  await stop.click();

  await expect(checkingTools(page).getByText("Stopped", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(keptChecks(page)).toBeVisible();
  await expect(step(page, "Build the tools")).toContainText("Done");
  // Nothing was made before it was stopped, which is said by the tool being as it was
  await expect(checkedTool(page, "scale")).toHaveAttribute("data-tier", "A");
  await expect(checkedTool(page, "scale")).toContainText("No check of it has passed.");
  await expect(checksForm(page).getByRole("button", { name: CHECK })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Take the tools away" })).toBeEnabled();
  expect((await checksOf(page, id)).job).toBeNull();
});

test("asks a model of another family for inputs to try, within what it may spend, and says that its words are no part of how a check came out", async ({ page }) => {
  test.setTimeout(120_000);
  const id = await agentWithTools(page, "Modelled checks", { kind: "doi", doi: "10.1000/checks-paper" });
  await readTheAgent(page, id);
  await page.reload();
  const numbers = (await checksOf(page, id)).numbers;
  expect(numbers).toBeGreaterThan(0);
  await expect(kindNamed(page, "paper_numbers").getByRole("checkbox")).toBeEnabled();

  // Only the one that asks for inputs, which is against what the tests that come with the code are not
  await kindNamed(page, "heldout").getByRole("checkbox").uncheck();
  await kindNamed(page, "repo_tests").getByRole("checkbox").uncheck();
  await kindNamed(page, "verifier").getByRole("checkbox").check();
  await checksForm(page).getByLabel("Most it may spend, in dollars").fill("1");
  // The server tells which families are which, and the page shows what it says
  await checksForm(page).getByLabel("The model that chooses the inputs").fill("gpt-4o");
  await checksForm(page).getByRole("button", { name: CHECK }).click();
  await expect(checksForm(page).getByRole("alert")).toContainText("is of the same family as gpt-5.2");
  await checksForm(page).getByLabel("The model that chooses the inputs").fill("my-own-model");
  await checksForm(page).getByRole("button", { name: CHECK }).click();
  await expect(checksForm(page).getByRole("alert")).toContainText("It is not known whose model my-own-model is");
  expect(await accessibilityProblems(page)).toEqual([]);
  expect((await checksOf(page, id)).job).toBeNull();

  await checksForm(page).getByLabel("The model that chooses the inputs").fill("claude-sonnet-4-5");
  await checksForm(page).getByRole("button", { name: CHECK }).click();
  await expect.poll(async () => (await checksOf(page, id)).tools[0].passed, { timeout: 40_000 }).toEqual(["verifier"]);
  // One check against the code's own function is one thing, so the tool is not yet of tier B
  await expect(checkedTool(page, "scale")).toHaveAttribute("data-tier", "A");
  await expect(checkedTool(page, "scale")).toContainText("It passed checks against 1 thing");
  await expect(page.getByTestId("checks-needs")).toContainText("To be of tier B it needs a check that passes against one more of:");
  await checkedTool(page, "scale").getByRole("button", { name: /Tier A/ }).click();
  await expect(checkOf(page, "scale", "verifier")).toHaveAttribute("data-status", "passed");
  await checkedTool(page, "scale").getByRole("button", { name: "Show what each check was made of" }).click();
  const verifier = checkOf(page, "scale", "verifier");
  await expect(verifier.getByRole("list", { name: "The model", exact: true })).toContainText("Asked claude-sonnet-4-5");
  await expect(verifier.getByRole("list", { name: "The model", exact: true })).toContainText("It proposed 3 inputs, and 2 could be run.");
  await expect(verifier.getByRole("list", { name: "Proposed inputs that were not run" })).toContainText("It names scale, which the tool does not take.");
  await expect(verifier.getByRole("list", { name: "Inputs the model proposed that were run" })).toContainText("'factor': 2.0}: the tool and the code's own function gave the same. Its reason: A longer list of fractions than the tutorial passed.");
  const gaps = verifier.getByTestId("check-detail").filter({ hasText: "Where the model thought the wrapper and the code might differ" });
  await expect(gaps).toContainText("These are the model's words. They are no part of how the check came out.");
  await expect(gaps).toContainText("The wrapper gives factor a default that the code may not have.");
  expect(await accessibilityProblems(page)).toEqual([]);

  // A check of another basis, made next, takes it to tier B, and the one before it is kept
  await kindNamed(page, "verifier").getByRole("checkbox").uncheck();
  await kindNamed(page, "repo_tests").getByRole("checkbox").check();
  await checksForm(page).getByRole("button", { name: CHECK }).click();
  await expect(checkedTool(page, "scale")).toHaveAttribute("data-tier", "B", { timeout: 40_000 });
  expect((await checksOf(page, id)).tools[0].passed).toEqual(["repo_tests", "verifier"]);

  // The paper's numbers are looked for in what the tools gave. None of them is there, which is neither for the tool nor against it
  await kindNamed(page, "repo_tests").getByRole("checkbox").uncheck();
  await kindNamed(page, "paper_numbers").getByRole("checkbox").check();
  await checksForm(page).getByRole("button", { name: CHECK }).click();
  await expect.poll(async () => (await checksOf(page, id)).tools[0].evidence.find((entry: { kind: string }) => entry.kind === "paper_numbers").status, { timeout: 40_000 }).toBe("not_obtained");
  await checkedTool(page, "scale").getByRole("button", { name: /Tier B/ }).click();
  await expect(checkOf(page, "scale", "paper_numbers").getByTestId("check-status")).toHaveText("Not obtained");
  await expect(checkOf(page, "scale", "paper_numbers")).toContainText("Against the numbers that the paper reports.");
  await expect(checkedTool(page, "scale")).toHaveAttribute("data-tier", "B");
});

test("says when Docker is not running, why the server refused to check, and looks again when what the page shows is out of date", async ({ page }) => {
  test.setTimeout(90_000);
  const id = await agentWithTools(page, "Refused checks");
  await page.route("**/api/paperagents/*/checks", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();
    const body = await response.json();

    return route.fulfill({ response, json: { ...body, docker: { ready: false, message: "Docker is installed but is not running." } } });
  });
  await page.reload();
  await expect(page.getByText("Docker is installed but is not running. Checking tools takes it. They cannot be checked until it is.")).toBeVisible();
  await expect(checksForm(page).getByRole("button", { name: CHECK })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);
  await page.unroute("**/api/paperagents/*/checks");
  await page.reload();
  await expect(checksForm(page).getByRole("button", { name: CHECK })).toBeEnabled();

  await page.route("**/api/paperagents/*/checks", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "docker_missing", message: "Docker is not installed on this machine, and checking tools takes it." } }),
        })
      : route.fallback(),
  );
  await checksForm(page).getByRole("button", { name: CHECK }).click();
  await expect(checksForm(page).getByRole("alert")).toContainText("Docker is not installed on this machine");
  await page.unroute("**/api/paperagents/*/checks");

  // Tools that were taken away a moment before the page looked are not a reason to refuse: the page looks again
  let looked = 0;
  await page.route("**/api/paperagents/*/checks", (route) => {
    if (route.request().method() === "GET") looked += 1;

    return route.request().method() === "POST"
      ? route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "no_tools", message: "Make the tools first, as it is tools that are checked" } }),
        })
      : route.fallback();
  });
  const before = looked;
  await checksForm(page).getByRole("button", { name: CHECK }).click();
  await expect.poll(() => looked).toBeGreaterThan(before);
  await expect(checksForm(page).getByRole("alert")).toHaveCount(0);
  await page.unroute("**/api/paperagents/*/checks");

  // What was kept of a tool is gone when it is asked for, which is as the tools were taken away, and the page looks again
  let seen = 0;
  await page.route("**/api/paperagents/*/checks", (route) => {
    if (route.request().method() === "GET") seen += 1;

    return route.fallback();
  });
  await page.route("**/api/paperagents/*/checks/*", (route) =>
    route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "not_found", message: "There is no such tool." } }) }),
  );
  await checkedTool(page, "scale").getByRole("button", { name: /Tier A/ }).click();
  const again = seen;
  await checkedTool(page, "scale").getByRole("button", { name: "Show what each check was made of" }).click();
  await expect.poll(() => seen).toBeGreaterThan(again);
  await expect(page.getByTestId("check-detail")).toHaveCount(0);
  await expect(keptChecks(page)).toBeVisible();
  await page.unroute("**/api/paperagents/*/checks/*");
  await page.unroute("**/api/paperagents/*/checks");
  expect((await checksOf(page, id)).tools).toHaveLength(1);
});

const inConversations = (page: Page) => page.getByRole("region", { name: "In conversations" });
const givenTools = (page: Page) => inConversations(page).getByTestId("given-tool");
const giveBox = (page: Page) => page.getByLabel("Give this agent to the conversations I start");
const givenSummary = (page: Page) => page.getByTestId("given-summary");
const givenOf = async (page: Page, id: string) => (await page.request.get(`/api/paperagents/${id}/given`)).json();

// The names of the tools that the model is offered in a conversation that is made now, which the script says when it is asked
async function offeredIn(page: Page, where: "local" | "nowhere"): Promise<string[]> {
  const question = `tool:offered in a conversation where code runs ${where}`;
  const made = await page.request.post("/api/chats", { data: { title: question, ...(where === "local" ? { code: { where: "local" } } : {}) } });
  expect(made.status()).toBe(201);
  await page.goto(`/chat?id=${(await made.json()).id}`);
  await page.getByRole("textbox", { name: "Message" }).fill(question);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await answered(page, "Offered:");
  const text = (await page.getByTestId("lead-message").last().textContent()) ?? "";

  return text.slice(text.indexOf("Offered:") + "Offered:".length).trim().split(/\s+/).filter(Boolean);
}

test("gives an agent to conversations, shows what a conversation is given of it with the tier of each tool, and gives none of it once it is not given or its tools are gone", async ({
  page,
}) => {
  const id = await agentWithTutorials(page, "Given cells");
  const prefix = "given_cells_";
  await sendPaper(page, id, "cells.txt", CELLS);
  await readTheAgent(page, id);
  expect((await page.request.post(`/api/paperagents/${id}/tools`, { data: {} })).status()).toBe(202);
  await expect.poll(async () => (await toolsOf(page, id)).job, { timeout: 30_000 }).toBeNull();
  expect((await toolsOf(page, id)).kept).toMatchObject({ complete: true });
  await openAgent(page, id, "Given cells");

  // It says what a conversation would be given, and that it is not given yet
  await expect(inConversations(page)).toBeVisible();
  await expect(giveBox(page)).not.toBeChecked();
  await expect(givenSummary(page)).toContainText("Tier A: runs the authors' code");
  await expect(givenSummary(page)).toContainText("Not given to conversations.");
  await expect(givenSummary(page)).toContainText("4 tools that read the paper and 1 that runs its code.");
  await expect(givenTools(page)).toHaveCount(5);
  for (const name of ["search_paper", "show_claim", "show_method_card", "check_scope"]) {
    const tool = inConversations(page).locator(`[data-testid=given-tool][data-name=${prefix}${name}]`);
    await expect(tool).toHaveAttribute("data-kind", "reading");
    await expect(tool).toContainText("Tier D");
    await expect(tool).toContainText("Reads what was found in the paper");
  }
  const runs = inConversations(page).locator(`[data-testid=given-tool][data-name=${prefix}scale]`);
  await expect(runs).toHaveAttribute("data-kind", "run");
  await expect(runs).toContainText("Tier A");
  await expect(runs).toContainText("scale(values, factor)");
  await expect(runs).toContainText("Runs the authors' own function");
  await expect(page.getByTestId("given-meaning")).toContainText("None of them shows that what it says or gives is right.");
  await expect(inConversations(page)).toContainText("A call may take up to 5 minutes, in a container with no network");
  await expect(page.getByTestId("given-why")).toHaveCount(0);
  expect(await givenOf(page, id)).toMatchObject({ given: false, tier: "A", problem: null });
  expect(await accessibilityProblems(page)).toEqual([]);

  // A conversation that is made before it is given is not given it
  expect((await offeredIn(page, "local")).filter((name) => name.startsWith(prefix))).toEqual([]);

  // One that is made after is, with the tools that run only where code runs
  await openAgent(page, id, "Given cells");
  await giveBox(page).click();
  await expect(giveBox(page)).toBeChecked();
  await expect(givenSummary(page)).toHaveAttribute("data-given", "true");
  await expect(givenSummary(page)).toContainText("Given to the conversations that you start from now on.");
  expect((await (await page.request.get(`/api/paperagents/${id}`)).json()).given).toBe(true);
  expect((await offeredIn(page, "local")).filter((name) => name.startsWith(prefix))).toEqual([
    `${prefix}check_scope`,
    `${prefix}scale`,
    `${prefix}search_paper`,
    `${prefix}show_claim`,
    `${prefix}show_method_card`,
  ]);
  expect((await offeredIn(page, "nowhere")).filter((name) => name.startsWith(prefix))).toEqual([
    `${prefix}check_scope`,
    `${prefix}search_paper`,
    `${prefix}show_claim`,
    `${prefix}show_method_card`,
  ]);

  // The agents that are given are marked in the list
  await page.goto("/papers");
  await expect(page.getByTestId("paper-agent").filter({ hasText: "Given cells" })).toContainText("Given to conversations");

  // A tool that is taken away is not offered, and the page says why it is not given
  await openAgent(page, id, "Given cells");
  expect((await page.request.delete(`/api/paperagents/${id}/tools`)).status()).toBe(200);
  await page.reload();
  await expect(givenTools(page)).toHaveCount(4);
  await expect(page.getByTestId("given-why")).toContainText("It has no tool that runs. Tools that run are made of what the tutorials did, under Tools.");
  await expect(givenSummary(page)).toContainText("Tier D: reads the paper");
  expect((await offeredIn(page, "local")).filter((name) => name.startsWith(prefix))).toEqual([
    `${prefix}check_scope`,
    `${prefix}search_paper`,
    `${prefix}show_claim`,
    `${prefix}show_method_card`,
  ]);

  // Taking it back gives none of it to a conversation that is made after
  await openAgent(page, id, "Given cells");
  await giveBox(page).click();
  await expect(giveBox(page)).not.toBeChecked();
  expect((await (await page.request.get(`/api/paperagents/${id}`)).json()).given).toBe(false);
  expect((await offeredIn(page, "local")).filter((name) => name.startsWith(prefix))).toEqual([]);
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("says that an agent whose paper has not been read has nothing to give yet, can still be given, and says what is wrong when the tools that run cannot be called", async ({
  page,
}) => {
  const id = await makeAgent(page, { title: "Unread cells", paper: { kind: "file" } });
  await openAgent(page, id, "Unread cells");
  await expect(givenSummary(page)).toContainText("Nothing to give yet");
  await expect(givenSummary(page)).toContainText("No tool is given.");
  await expect(givenTools(page)).toHaveCount(0);
  await expect(page.getByTestId("given-why")).toContainText("The paper has not been read, so the tools that read it are not given. Read it under Reading.");
  await expect(page.getByTestId("given-why")).toContainText(
    "It has no code, so it has no tool that runs the authors' code. A function can be written from the paper's words under Re-implementation, and is given once it matches a number that the paper reports.",
  );
  expect(await givenOf(page, id)).toMatchObject({ given: false, tier: null, tools: [], problem: null });
  expect(await accessibilityProblems(page)).toEqual([]);

  // It can be given before it has anything to give, and a conversation made then is offered none of it
  await giveBox(page).click();
  await expect(giveBox(page)).toBeChecked();
  expect((await offeredIn(page, "local")).filter((name) => name.startsWith("unread_cells_"))).toEqual([]);

  // What the server says of why its tools cannot be called is said as it says it, and is not taken for a tool that is missing
  await page.route("**/api/paperagents/*/given", async (route) => {
    const response = await route.fetch();
    const body = await response.json();

    return route.fulfill({
      response,
      json: {
        ...body,
        tier: "D",
        tools: [{ name: "unread_cells_search_paper", kind: "reading", tier: "D", summary: "Searches the text of the paper for words, and gives the places.", parameters: ["query", "max_results"] }],
        problem: "The tools cannot be run: Docker is not running, or the image of the environment is not in it.",
      },
    });
  });
  await openAgent(page, id, "Unread cells");
  await expect(page.getByTestId("given-problem")).toHaveText("The tools cannot be run: Docker is not running, or the image of the environment is not in it.");
  await expect(givenTools(page)).toHaveCount(1);
  await expect(givenTools(page)).toContainText("unread_cells_search_paper(query, max_results)");
  await expect(page.getByTestId("given-why")).toHaveCount(0);
  await page.unroute("**/api/paperagents/*/given");

  // An agent that is not there is not given, and the page says so
  await page.request.delete(`/api/paperagents/${id}`);
  expect((await page.request.get(`/api/paperagents/${id}/given`)).status()).toBe(404);
});

const FIGURE_ADDRESS = "https://github.com/example/figure-cellmapper";
const claimsForm = (page: Page) => form(page, "Try the claims");
const tryingClaims = (page: Page) => page.getByRole("region", { name: "Trying the claims" });
const keptClaims = (page: Page) => page.getByTestId("claims-kept");
const claimsTable = (page: Page) => page.getByRole("table", { name: "Claims", exact: true });
const claimWithStatus = (page: Page, status: string) => page.locator(`[data-testid=claim][data-status=${status}]`);
const claimsOf = async (page: Page, id: string) => (await page.request.get(`/api/paperagents/${id}/reproduction`)).json();
const TRY = "Try the claims";

// The sentences of a paper whose tutorials give 0.93 at one place: the first is that number, the next two cite a figure that a tutorial
// makes and are not, and the last cites nothing that the code makes. The title is its own, as the same paper is not kept by two agents.
const claimsPaper = (title: string) =>
  [
    `${title}: mapping cell types`,
    "Results",
    "CellMapper reached an AUROC of 0.93 on held-out mouse hippocampus nuclei.",
    "The reference method reached an AUROC of 0.84 on the same nuclei (Figure 2).",
    "A third method reached an AUROC of 0.91 on the same nuclei (Figure 2).",
    "A fourth method reached an AUROC of 0.55 on nuclei of the cortex.",
    "Methods",
    "Clusters were found with Seurat v4.3 after the reads were aligned.",
  ].join("\n\n");

// Makes an agent whose paper has been read and whose tutorials have been run, so that what a test is about is how its claims were held
// to what they gave, and opens it. A title with "scored" in it is of tutorials that give the number that the first claim reports.
async function agentWithClaims(page: Page, title: string, paper = claimsPaper(title), repo = FIGURE_ADDRESS): Promise<string> {
  const id = await agentWithTutorials(page, title, { kind: "file" }, repo);
  await sendPaper(page, id, "claims.txt", paper);
  await readTheAgent(page, id);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Claims", level: 2, exact: true })).toBeVisible();

  return id;
}

test("says that claims are tried once the paper is read and the tutorials are run, and not before", async ({ page }) => {
  const id = await agentWithTutorials(page, "Scored unread", { kind: "file" }, FIGURE_ADDRESS);
  await expect(page.getByRole("heading", { name: "Claims", level: 2, exact: true })).toBeVisible();
  await expect(page.getByTestId("claims-problem")).toHaveText("Read the paper first, as it is the claims that were read from it that are tried.");
  await expect(claimsForm(page).getByRole("button", { name: TRY })).toBeDisabled();
  await expect(keptClaims(page)).toHaveCount(0);
  const asked = await page.request.post(`/api/paperagents/${id}/reproduction`, { data: { max_cost: 1 } });
  expect(asked.status()).toBe(422);
  expect((await asked.json()).error.code).toBe("no_claims");
  expect(await claimsOf(page, id)).toMatchObject({ ready: false, problem: { code: "no_claims" }, kept: null, claims: [], current: false });
  expect(await accessibilityProblems(page)).toEqual([]);

  // Once the paper is read the page looks again, and the claims can be tried
  await sendPaper(page, id, "claims.txt", claimsPaper("Scored unread"));
  await readTheAgent(page, id);
  await page.reload();
  await expect(page.getByTestId("claims-problem")).toHaveCount(0);
  await expect(claimsForm(page).getByRole("button", { name: TRY })).toBeEnabled();
  await expect(claimsForm(page)).toContainText("4 numbers of the paper have digits enough to be tried.");
  await expect(claimsForm(page)).toContainText("Nothing is run: it is what the tutorials kept that the claims are held to.");

  // Tutorials that have not been run are what there is nothing to hold the claims to
  const bare = await agentWithEnvironment(page, "Scored unrun", FIGURE_ADDRESS, { kind: "file" });
  await sendPaper(page, bare, "claims.txt", claimsPaper("Scored unrun"));
  await readTheAgent(page, bare);
  await page.reload();
  await expect(page.getByTestId("claims-problem")).toHaveText("Run the tutorials first, as it is what they gave that the claims are held to.");
  await expect(claimsForm(page).getByRole("button", { name: TRY })).toBeDisabled();
  expect((await page.request.post(`/api/paperagents/${bare}/reproduction`, { data: { max_cost: 1 } })).status()).toBe(422);
});

const showHow = (row: Locator) => row.getByRole("button", { name: /^Show how/ });
const WHOLE_RUN = "What differs, of the whole run";

test("tries the claims with a budget, shows how each came out and what it was held to, and where the tutorial parts from the paper, and takes the trying away", async ({ page }) => {
  test.setTimeout(90_000);
  const id = await agentWithClaims(page, "Scored claims");
  await expect(keptClaims(page)).toHaveCount(0);
  await expect(page.getByTestId("claims-problem")).toHaveCount(0);
  await expect(claimsForm(page)).toContainText("4 numbers of the paper have digits enough to be tried.");
  await expect(claimsForm(page)).toContainText("gpt-5.2, the model in the settings, is asked which place in what the tutorials gave the sentence is about, and is not shown any value there.");
  await expect(claimsForm(page)).not.toContainText("Trying them again takes away");
  expect(await accessibilityProblems(page)).toEqual([]);

  // The most it may spend is always said, and is an amount, and nothing is asked until it is
  await claimsForm(page).getByRole("button", { name: TRY }).click();
  await expect(claimsForm(page).getByText("Say the most it may spend.", { exact: true })).toBeVisible();
  await claimsForm(page).getByLabel("Most it may spend, in dollars").fill("many");
  await claimsForm(page).getByRole("button", { name: TRY }).click();
  await expect(claimsForm(page).getByText("The most it may spend is an amount in dollars, such as 1 or 0.50.", { exact: true })).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  expect((await claimsOf(page, id)).kept).toBeNull();

  await claimsForm(page).getByLabel("Most it may spend, in dollars").fill("1");
  await claimsForm(page).getByRole("button", { name: TRY }).click();
  await expect(keptClaims(page)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("claims-counts")).toHaveText("4 claims: 1 reproduced, 1 partly reproduced, 1 not reproduced, 1 not attempted.");
  await expect(page.getByTestId("claims-how")).toHaveText(/^Tried .+\. gpt-5\.2 was asked 1 time, which cost <\$0\.01\.$/);
  await expect(page.getByTestId("claims-meaning")).toContainText("It does not say that they were run on the paper's data, or that the paper is right.");
  await expect(page.getByTestId("claims-meaning")).toContainText("A difference is one that was found, not a cause");
  await expect(claimsForm(page).getByRole("button", { name: "Try the claims again" })).toBeEnabled();
  await expect(claimsForm(page)).toContainText("Trying them again takes away what was kept of this trying, and the variants that were made of it.");
  expect(await claimsOf(page, id)).toMatchObject({ kept: { complete: true, requests: 1, model: "gpt-5.2" }, current: true, counts: { reproduced: 1, partly: 1, not_reproduced: 1, not_attempted: 1, stale: 0 } });

  // Each claim is told by what the paper says, the number, and how it came out in a word
  await expect(claimsTable(page).getByTestId("claim")).toHaveCount(4);
  const reproduced = claimWithStatus(page, "reproduced");
  await expect(reproduced).toHaveCount(1);
  await expect(reproduced).toContainText("CellMapper reached an AUROC of 0.93 on held-out mouse hippocampus nuclei.");
  await expect(reproduced.getByTestId("claim-status")).toHaveText("Reproduced");
  await expect(reproduced.getByTestId("claim-summary")).toContainText("tutorials/quickstart.ipynb gave 0.93 in a call of cellmapper.core.score(values=[1, 2, 3])");
  await expect(claimWithStatus(page, "partly").getByTestId("claim-status")).toHaveText("Partly reproduced");
  await expect(claimWithStatus(page, "not_reproduced").getByTestId("claim-status")).toHaveText("Not reproduced");
  await expect(claimWithStatus(page, "not_reproduced").getByTestId("claim-summary")).toContainText("where the paper reports 0.84 (10.7% away)");
  const unattempted = claimWithStatus(page, "not_attempted");
  await expect(unattempted.getByTestId("claim-status")).toHaveText("Not attempted");
  await expect(unattempted.getByTestId("claim-summary")).toContainText("No code could be linked to it");
  // A claim that nothing was held to has nothing to show of how
  await expect(showHow(unattempted)).toHaveCount(0);

  // What a claim was held to is shown when it is asked for, with who chose the place, and that it was chosen blind
  await showHow(reproduced).click();
  const held = page.getByRole("list", { name: "What it was held to" });
  await expect(held).toHaveCount(1);
  await expect(held).toContainText("Held to a call of cellmapper.core.score(values=[1, 2, 3]), at result in tutorials/quickstart.ipynb.");
  await expect(held).toContainText("It gave 0.93, and the paper reports 0.93.");
  await expect(held).toContainText("It was found because a result rounds to the paper's number.");
  await expect(held).toContainText("gpt-5.2 chose this place from the words alone, without being shown any value. A program held it to the number.");
  await expect(held).toContainText("The 2 runs of the tutorial agreed.");
  // A claim that reproduced does not part from the paper
  await expect(page.getByTestId("claim-divergence")).toHaveCount(0);
  await expect(reproduced.getByRole("button", { name: /^Hide how/ })).toHaveAttribute("aria-expanded", "true");

  // One that did not shows where the tutorial first parts from the paper, and what differs that was found, which is not said to be why
  const notReproduced = claimWithStatus(page, "not_reproduced");
  await showHow(notReproduced).click();
  await expect(page.getByTestId("claim-divergence")).toHaveCount(1);
  await expect(page.getByTestId("claim-point")).toContainText("the first output, in the order that it made its calls, that parts from the paper is a call of cellmapper.core.score(values=[1, 2, 3]), at result: it gave 0.93, and the paper reports 0.84.");
  await expect(page.getByTestId("claim-point")).toContainText("1 output before it agreed with the paper");
  await expect(page.getByTestId("claim-divergence")).toContainText("Differences found (not shown to be why)");
  await expect(page.getByTestId("claim-divergence")).toContainText("None was found for this tutorial. That does not say that there is none");
  await expect(page.getByRole("list", { name: "What it was held to" }).nth(1)).toContainText("It was found because the sentence and the tutorial both refer to figure 2. No result there rounds to the paper's number.");
  expect(await accessibilityProblems(page)).toEqual([]);
  await reproduced.getByRole("button", { name: /^Hide how/ }).click();
  await expect(page.getByRole("list", { name: "What it was held to" })).toHaveCount(1);
  await notReproduced.getByRole("button", { name: /^Hide how/ }).click();
  await expect(page.getByTestId("claim-detail")).toHaveCount(0);

  // What differs of the whole run is said, with the software that the paper names and what is installed
  const whole = page.getByTestId("claims-whole-run");
  await expect(whole).toContainText(WHOLE_RUN);
  await expect(whole.getByRole("list", { name: "Software that the paper names" })).toContainText("Seurat: the paper says 4.3, none installed (not installed).");

  // They are told apart by how they came out
  const filter = keptClaims(page).getByLabel("Show", { exact: true });
  await expect(filter.locator("option")).toHaveText(["All claims", "Reproduced (1)", "Partly reproduced (1)", "Not reproduced (1)", "Not attempted (1)"]);
  await filter.selectOption({ label: "Not reproduced (1)" });
  await expect(claimsTable(page).getByTestId("claim")).toHaveCount(1);
  await expect(claimsTable(page).getByTestId("claim")).toHaveAttribute("data-status", "not_reproduced");
  await filter.selectOption({ label: "All claims" });
  await expect(claimsTable(page).getByTestId("claim")).toHaveCount(4);

  // They can be saved as a table, which is what the server makes of what is kept
  const download = keptClaims(page).getByRole("link", { name: "Download as a table, the claims" });
  await expect(download).toHaveAttribute("href", `/api/paperagents/${id}/tables/claims`);
  const table = await page.request.get(`/api/paperagents/${id}/tables/claims`);
  expect(table.status()).toBe(200);
  expect(table.headers()["content-type"]).toContain("text/csv");
  expect(table.headers()["content-disposition"]).toContain("attachment");
  expect(await table.text()).toContain("CellMapper reached an AUROC of 0.93 on held-out mouse hippocampus nuclei.");
  expect(await accessibilityProblems(page)).toEqual([]);

  // The trying is taken away only when it is said to be, and what the tutorials gave stays
  await keptClaims(page).getByRole("button", { name: "Take the trying away" }).click();
  const asking = page.getByRole("alertdialog");
  await expect(asking.getByRole("heading", { name: "Take away the trying of the claims of Scored claims?" })).toBeVisible();
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  await expect(keptClaims(page)).toBeVisible();
  expect((await claimsOf(page, id)).kept).not.toBeNull();
  await keptClaims(page).getByRole("button", { name: "Take the trying away" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Take away" }).click();
  await expect(keptClaims(page)).toHaveCount(0);
  const cleared = await claimsOf(page, id);
  expect(cleared).toMatchObject({ kept: null, ready: true, current: false });
  expect(cleared.claims.map((claim: { reason: string }) => claim.reason)).toEqual(["not_tried", "not_tried", "not_tried", "not_tried"]);
  expect((await referenceOf(page, id)).kept).toMatchObject({ complete: true });
  await expect(claimsForm(page).getByRole("button", { name: TRY })).toBeEnabled();
  await expect(claimsForm(page)).not.toContainText("Trying them again takes away");

  // And they are tried again from nothing
  await claimsForm(page).getByLabel("Most it may spend, in dollars").fill("0.50");
  await claimsForm(page).getByRole("button", { name: TRY }).click();
  await expect(page.getByTestId("claims-counts")).toHaveText("4 claims: 1 reproduced, 1 partly reproduced, 1 not reproduced, 1 not attempted.", { timeout: 20_000 });
  await expect(claimsForm(page).getByRole("button", { name: "Try the claims again" })).toBeEnabled();
});

// Sixteen sentences that cite a figure that a tutorial makes, which are asked of a model five at a time, and of which the first of each
// request takes a while to be answered, so that the trying can be followed and stopped between one request and the next
const lingeringPaper = (title: string) =>
  [
    `${title}: mapping cell types`,
    "Results",
    ...Array.from({ length: 16 }, (_, index) => `${index % 5 === 0 ? "slow: " : ""}Method ${index + 1} reached an AUROC of 0.${61 + index} on the same nuclei (Figure 2).`),
  ].join("\n\n");

// Tries the claims of an agent through the server, and waits until that is done
async function tryTheClaims(page: Page, id: string, maxCost = 1) {
  const started = await page.request.post(`/api/paperagents/${id}/reproduction`, { data: { max_cost: maxCost } });
  expect(started.status()).toBe(202);
  await expect.poll(async () => (await claimsOf(page, id)).job, { timeout: 30_000 }).toBeNull();
}

test("follows the trying while it goes on, waits for it before anything else is done to the agent, and keeps what it had tried when it is stopped", async ({ page }) => {
  test.setTimeout(90_000);
  const id = await agentWithClaims(page, "Scored lingering", lingeringPaper("Scored lingering"));
  await expect(claimsForm(page)).toContainText("16 numbers of the paper have digits enough to be tried.");
  await claimsForm(page).getByLabel("Most it may spend, in dollars").fill("1");
  await claimsForm(page).getByRole("button", { name: TRY }).click();

  const stop = tryingClaims(page).getByRole("button", { name: "Stop: Trying the claims: Scored lingering" });
  await expect(stop).toBeVisible();
  // What is kept is shown when the trying is over, and the form is not offered again while it goes on
  await expect(keptClaims(page)).toHaveCount(0);
  await expect(claimsForm(page)).toHaveCount(0);
  expect((await claimsOf(page, id)).job).not.toBeNull();
  await page.reload();
  await expect(stop).toBeVisible();
  await expect(keptClaims(page)).toHaveCount(0);
  await expect(claimsForm(page)).toHaveCount(0);
  // Nothing else is done to the agent while it goes on, and its paper is not read
  await expect(reading(page)).toContainText("The claims are being tried. Reading waits for that.");
  await expect(reading(page).getByRole("button", { name: /^(Read the paper|Carry on reading)$/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Delete Scored lingering" })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);
  const refused = await page.request.post(`/api/paperagents/${id}/reproduction`, { data: { max_cost: 1 } });
  expect(refused.status()).toBe(409);
  expect((await page.request.delete(`/api/paperagents/${id}/reproduction`)).status()).toBe(409);

  await stop.click();

  await expect(tryingClaims(page).getByText("Stopped", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(keptClaims(page)).toBeVisible();
  await expect(page.getByTestId("claims-how")).toContainText("It did not come to its end.");
  expect(await claimsOf(page, id)).toMatchObject({ job: null, kept: { complete: false } });
  // What was tried is kept, and the claims that were not reached are said not to have been tried
  const total = Object.values((await claimsOf(page, id)).counts as Record<string, number>).reduce((sum, each) => sum + each, 0);
  expect(total).toBe(16);
  await expect(claimWithStatus(page, "not_attempted").first().getByTestId("claim-summary")).toHaveText("It has not been tried.");
  await expect(claimsTable(page).getByTestId("claim")).toHaveCount(16);
  await expect(claimsForm(page).getByRole("button", { name: "Try the claims again" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Delete Scored lingering" })).toBeEnabled();
  await expect(keptClaims(page).getByRole("button", { name: "Take the trying away" })).toBeEnabled();
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("says that claims tried before the paper was read again to other claims are stale, and shows nothing of what they came to", async ({ page }) => {
  test.setTimeout(90_000);
  const id = await agentWithClaims(page, "Scored stale");
  await tryTheClaims(page, id);
  await page.reload();
  await expect(claimWithStatus(page, "reproduced")).toHaveCount(1);
  await expect(page.getByTestId("claims-stale")).toHaveCount(0);
  await expect(page.getByTestId("claims-whole-run")).toBeVisible();

  // A paper that says one thing more is read in its place, so that what was tried is of other claims than are kept now
  await sendPaper(page, id, "claims.txt", `${claimsPaper("Scored stale")}\n\nA fifth method reached an AUROC of 0.62 on the same nuclei (Figure 2).`);
  await readTheAgent(page, id);
  await page.reload();
  await expect(page.getByTestId("claims-stale")).toContainText("These were tried against another run of the tutorials, or other claims, than are kept now, so what came of each is not shown. Try the claims again.");
  expect(await claimsOf(page, id)).toMatchObject({ current: false, counts: { stale: 4, reproduced: 0, partly: 0, not_reproduced: 0, not_attempted: 1 } });
  await expect(page.getByTestId("claims-counts")).toHaveText("5 claims: 1 not attempted, 4 stale.");
  await expect(claimsTable(page).getByTestId("claim")).toHaveCount(5);
  await expect(claimWithStatus(page, "stale")).toHaveCount(4);
  await expect(claimWithStatus(page, "reproduced")).toHaveCount(0);
  const first = claimWithStatus(page, "stale").first();
  await expect(first.getByTestId("claim-status")).toHaveText("Stale (was Reproduced)");
  await expect(first.getByTestId("claim-summary")).toHaveText(
    "It was tried against another run of the tutorials, or other claims, than are kept now, so what came of it is not shown. It was reproduced when it was tried. Try the claims again.",
  );
  await expect(claimWithStatus(page, "not_attempted").getByTestId("claim-summary")).toHaveText("It has not been tried.");
  // Nothing of what it came to, or where it parted from the paper, or what differs of the run, is shown, as none of it is of what is kept now
  await expect(keptClaims(page)).not.toContainText("cellmapper.core");
  await expect(keptClaims(page).getByRole("button", { name: /^Show how/ })).toHaveCount(0);
  await expect(page.getByTestId("claims-whole-run")).toHaveCount(0);
  await expect(page.getByTestId("claims-meaning")).not.toContainText("A difference is one that was found");
  const filter = keptClaims(page).getByLabel("Show", { exact: true });
  await expect(filter.locator("option")).toHaveText(["All claims", "Not attempted (1)", "Stale (4)"]);
  await filter.selectOption({ label: "Stale (4)" });
  await expect(claimsTable(page).getByTestId("claim")).toHaveCount(4);
  expect(await accessibilityProblems(page)).toEqual([]);

  // Trying them again is of what is kept now
  await expect(claimsForm(page)).toContainText("5 numbers of the paper have digits enough to be tried.");
  await claimsForm(page).getByLabel("Most it may spend, in dollars").fill("1");
  await claimsForm(page).getByRole("button", { name: "Try the claims again" }).click();
  await expect(page.getByTestId("claims-counts")).toHaveText("5 claims: 1 reproduced, 1 partly reproduced, 2 not reproduced, 1 not attempted.", { timeout: 20_000 });
  await expect(page.getByTestId("claims-stale")).toHaveCount(0);
  await expect(claimWithStatus(page, "stale")).toHaveCount(0);
  // The filter was of a way that no claim comes out now, so all of them are shown
  await expect(claimsTable(page).getByTestId("claim")).toHaveCount(5);
});

test("says what is wrong when the server refuses to try the claims, and looks again at what it shows when what it showed is out of date", async ({ page }) => {
  const id = await agentWithClaims(page, "Scored refused");
  await claimsForm(page).getByLabel("Most it may spend, in dollars").fill("1");

  // What the server says of a missing key is said as it says it, with a way to put it right
  await page.route("**/api/paperagents/*/reproduction", (route) =>
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
  await claimsForm(page).getByRole("button", { name: TRY }).click();
  const problem = claimsForm(page).getByRole("alert");
  await expect(problem).toContainText("gpt-5.2 needs OPENAI_API_KEY");
  await expect(problem.getByRole("button", { name: "Add the key" })).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  await page.unroute("**/api/paperagents/*/reproduction");
  expect((await claimsOf(page, id)).kept).toBeNull();

  // What was read of the paper is taken away behind the page's back, so that there is nothing to try, which the page is told of by the server
  expect((await page.request.delete(`/api/paperagents/${id}/reading`)).status()).toBe(200);
  await expect(claimsForm(page).getByRole("button", { name: TRY })).toBeEnabled();
  await claimsForm(page).getByRole("button", { name: TRY }).click();
  await expect(page.getByTestId("claims-problem")).toHaveText("Read the paper first, as it is the claims that were read from it that are tried.");
  await expect(claimsForm(page).getByRole("button", { name: TRY })).toBeDisabled();
  expect((await claimsOf(page, id)).job).toBeNull();
  expect(await accessibilityProblems(page)).toEqual([]);
});

const variantsForm = (page: Page) => form(page, "Make a variant");
const makeVariantButton = (page: Page) => variantsForm(page).getByRole("button", { name: "Make the variant" });
const keptVariants = (page: Page) => page.getByTestId("variants-kept");
const variantRows = (page: Page) => page.getByTestId("variant");
const makingVariant = (page: Page) => page.getByRole("region", { name: "Making a variant" });
const variantsOf = async (page: Page, id: string) => (await page.request.get(`/api/paperagents/${id}/variants`)).json();
const claimWith = async (page: Page, id: string, status: string): Promise<string> =>
  (await claimsOf(page, id)).claims.find((claim: { status: string }) => claim.status === status).id;
const VARIANTS = { name: "Variants", level: 2, exact: true } as const;
const CLOSING = "This is a variant. It is not the paper's result, and the claim's own result is as it was.";

// Makes an agent whose claims have been tried, so that what a test is about is what is made of them, and opens it on the variants
async function agentWithTriedClaims(page: Page, title: string, paper = claimsPaper(title)): Promise<string> {
  const id = await agentWithClaims(page, title, paper);
  await tryTheClaims(page, id);
  await page.reload();
  await expect(page.getByRole("heading", VARIANTS)).toBeVisible();
  await expect(variantsForm(page)).toBeVisible();

  return id;
}

// Makes a variant through the server, and waits until that is done
async function makeTheVariant(page: Page, id: string, claim: string, changes: Record<string, unknown>) {
  const started = await page.request.post(`/api/paperagents/${id}/variants`, { data: { claim, changes } });
  expect(started.status()).toBe(202);
  await expect.poll(async () => (await variantsOf(page, id)).job, { timeout: 30_000 }).toBeNull();
}

test("says that a variant is made of a claim that was tried, and not before", async ({ page }) => {
  const id = await agentWithClaims(page, "Scored varied early");
  await expect(page.getByRole("heading", VARIANTS)).toBeVisible();
  await expect(page.getByTestId("variants-problem")).toHaveText("Try the claims first, as it is a claim that was tried that a variant is made of.");
  await expect(page.getByTestId("variants-problem")).toHaveAttribute("data-code", "no_reproduction");
  await expect(variantsForm(page)).toHaveCount(0);
  await expect(keptVariants(page)).toHaveCount(0);
  expect(await variantsOf(page, id)).toMatchObject({ ready: false, problem: { code: "no_reproduction" }, claims: [], variants: [], stale: 0, job: null });
  const claim = (await claimsOf(page, id)).claims[0].id;
  const asked = await page.request.post(`/api/paperagents/${id}/variants`, { data: { claim, changes: { values: [4, 5, 6] } } });
  expect(asked.status()).toBe(422);
  expect((await asked.json()).error.code).toBe("no_reproduction");
  expect(await accessibilityProblems(page)).toEqual([]);

  // Once the claims are tried the page looks again, and a variant can be made
  await tryTheClaims(page, id);
  await page.reload();
  await expect(page.getByTestId("variants-problem")).toHaveCount(0);
  await expect(variantsForm(page)).toBeVisible();
  await expect(keptVariants(page)).toHaveCount(0);
});

test("makes variants of a claim's call with new values, says of each that it is not the paper's result, saves them as a table, and takes them away", async ({ page }) => {
  test.setTimeout(150_000);
  const id = await agentWithTriedClaims(page, "Scored varied");
  const reproduced = await claimWith(page, id, "reproduced");
  const own = await claimsOf(page, id);
  const form = variantsForm(page);
  const limits = (await variantsOf(page, id)).limits;
  expect(await variantsOf(page, id)).toMatchObject({ ready: true, problem: null, variants: [], stale: 0, counts: { variants: 0, comparable: 0, rounds_to_paper: 0 } });

  // The claims that a call can be made again of are offered, and why not the others is said when it is asked
  const claim = form.getByLabel("Claim", { exact: true });
  await expect(claim.locator("option")).toHaveCount(4);
  await expect(claim.locator("option").first()).toHaveText("Choose a claim");
  await expect(claim.locator("option").nth(1)).toHaveText("0.93: CellMapper reached an AUROC of 0.93 on held-out mouse hippoc…");
  await expect(form).toContainText("3 claims can be varied.");
  await form.getByRole("button", { name: "Why 1 claim cannot be varied" }).click();
  await expect(form.getByRole("list", { name: "Claims that cannot be varied" })).toContainText("That claim was not attempted, so there is no call that it was held to.");
  await expect(form.getByTestId("variants-refused").locator("li")).toHaveAttribute("data-code", "not_attempted");
  await form.getByRole("button", { name: "Hide why not" }).click();
  await expect(form.getByRole("list", { name: "Claims that cannot be varied" })).toHaveCount(0);

  // A claim is chosen, and nothing is made until what is asked is right
  await makeVariantButton(page).click();
  await expect(form.getByText("Choose the claim whose call is made again.", { exact: true })).toBeVisible();
  await expect(form.getByTestId("variant-argument")).toHaveCount(0);
  await claim.selectOption(reproduced);
  await expect(form.getByRole("group", { name: /What to change in the call of cellmapper\.core\.score/ })).toBeVisible();
  await expect(form.getByTestId("variant-argument")).toHaveCount(1);
  await expect(form.getByTestId("variant-argument")).toContainText("Given [1, 2, 3]");
  await makeVariantButton(page).click();
  await expect(form.getByText("Give at least one argument a new value.", { exact: true })).toBeVisible();
  const values = form.getByLabel("values", { exact: true });
  await values.fill("abc");
  await expect(form.getByText(/^The new value for values is written as JSON/)).toBeVisible();
  await values.fill("[1, 2, 3]");
  await expect(form.getByText("values was given that value, so it is not a change.", { exact: true })).toBeVisible();
  await values.fill(`[${"1, ".repeat(limits.max_value_chars)}1]`);
  await expect(form.getByText(`The new value for values is at most ${limits.max_value_chars} characters of JSON.`, { exact: true })).toBeVisible();
  await values.fill("[4, 5, 6]");
  await form.getByLabel("Most time, in minutes").fill("0");
  await expect(form.getByText(new RegExp(`is a whole number from 1 to ${limits.max_minutes}\\.$`))).toBeVisible();
  await form.getByLabel("How many times each call is made").fill("many");
  await expect(form.getByText(`How many times each call is made is a whole number from 1 to ${limits.max_repeats}.`, { exact: true })).toBeVisible();
  await form.getByLabel("A note (optional)").fill("x".repeat(limits.max_note_chars + 1));
  await expect(form.getByText(`A note is at most ${limits.max_note_chars} characters.`, { exact: true })).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  // Nothing was asked of the server while any of that was wrong
  expect(await variantsOf(page, id)).toMatchObject({ variants: [], job: null });
  await form.getByLabel("Most time, in minutes").fill(String(limits.default_minutes));
  await form.getByLabel("How many times each call is made").fill(String(limits.default_repeats));
  await form.getByLabel("A note (optional)").fill("");
  await expect(form.getByRole("alert")).toHaveCount(0);

  // A variant is made, and shown as what it is
  await makeVariantButton(page).click();
  await expect(variantRows(page)).toHaveCount(1, { timeout: 30_000 });
  const first = variantRows(page).first();
  await expect(first.getByTestId("variant-not-result")).toHaveText("Not the paper's result");
  await expect(first.getByTestId("variant-status")).toHaveText("Gave a number");
  await expect(first.getByTestId("variant-comparable")).toHaveText("Comparable");
  await expect(first).toContainText("Of the claim that says “CellMapper reached an AUROC of 0.93 on held-out mouse hippocampus nuclei.”, which the paper gives as 0.93.");
  await expect(first.getByRole("list", { name: "What was changed" })).toHaveText("values: [4,5,6] in place of [1,2,3]");
  await expect(first.getByTestId("variant-outcome")).toHaveText("It gave 1.02, where the call that the claim was held to gave 0.93.");
  await expect(first.getByTestId("variant-control")).toHaveText(
    "Comparable: the same call with nothing changed gave what the tutorial got, and the variant gave a number.",
  );
  await expect(first.getByTestId("variant-rounds")).toHaveText("The number that it gave does not round to the paper's 0.93.");
  await expect(first.getByTestId("variant-note")).toHaveCount(0);
  await expect(first.getByTestId("variant-made")).toHaveText(
    new RegExp(`^Made .+\\. Each call was made ${limits.default_repeats} times, for at most ${limits.default_minutes} minutes and ${limits.default_gigabytes} gigabytes? written\\.$`),
  );
  await expect(page.getByTestId("variants-counts")).toHaveText("1 variant: 1 comparable, 0 that give a number that rounds to the paper's. None of them is the paper's result.");
  await expect(page.getByTestId("variants-meaning")).toHaveText((await variantsOf(page, id)).meaning);
  // The server's own account is under it, and says the same
  await first.getByRole("button", { name: /^Show how/ }).click();
  await expect(first.getByTestId("variant-text")).toContainText("the call gave 1.02");
  await expect(first.getByTestId("variant-text")).toContainText(CLOSING);
  const how = first.getByRole("list", { name: "How this variant was made" });
  await expect(how).toContainText("The claim was held to a call of cellmapper.core.score(values=[1, 2, 3]), at result, run by tutorials/quickstart.ipynb, which gave 0.93.");
  await expect(how).toContainText("With the changes, the 2 times it was made gave: 1.02, 1.02.");
  await expect(how).toContainText("With nothing changed, it gave 0.93 at the same place.");
  expect(await accessibilityProblems(page)).toEqual([]);
  await first.getByRole("button", { name: /^Hide how/ }).click();
  await expect(how).toHaveCount(0);

  // What was typed stays, so that it can be changed a little and made again. One that gives the number that the paper reports is not that
  // number reproduced, and a note is kept with it
  await expect(values).toHaveValue("[4, 5, 6]");
  await values.fill("[1, 2, 3, 0]");
  await form.getByLabel("A note (optional)").fill("Is it the zero?");
  await makeVariantButton(page).click();
  await expect(variantRows(page)).toHaveCount(2, { timeout: 30_000 });
  const second = variantRows(page).nth(1);
  await expect(second.getByTestId("variant-outcome")).toHaveText("It gave 0.93, where the call that the claim was held to gave 0.93.");
  await expect(second.getByTestId("variant-rounds")).toHaveText(
    "The number that it gave rounds to the paper's 0.93. That is not a reproduction of the paper's result.",
  );
  await expect(second.getByTestId("variant-not-result")).toBeVisible();
  await expect(second.getByTestId("variant-note")).toHaveText("Your note: Is it the zero?");
  await expect(page.getByTestId("variants-counts")).toHaveText(
    "2 variants: 2 comparable, 1 that gives a number that rounds to the paper's. None of them is the paper's result.",
  );

  // One that the call stops at is said so, and has no number to set beside the claim's
  await values.fill('"abc"');
  await form.getByLabel("A note (optional)").fill("");
  await makeVariantButton(page).click();
  await expect(variantRows(page)).toHaveCount(3, { timeout: 30_000 });
  const third = variantRows(page).nth(2);
  await expect(third.getByTestId("variant-status")).toHaveText("Stopped with an error");
  await expect(third.getByTestId("variant-comparable")).toHaveText("Not comparable");
  await expect(third.getByTestId("variant-outcome")).toHaveText("It stopped with TypeError: values must be a list of numbers.");
  await expect(third.getByTestId("variant-control")).toContainText("the variant gave no number to set beside the claim's.");
  await expect(third.getByTestId("variant-rounds")).toHaveCount(0);
  await expect(third).toHaveAttribute("data-status", "error");
  await expect(third).toHaveAttribute("data-comparable", "no");
  const made = await variantsOf(page, id);
  expect(made.variants.map((variant: { variant: { status: string } }) => variant.variant.status)).toEqual(["gave", "gave", "error"]);
  expect(made.counts).toEqual({ variants: 3, comparable: 2, rounds_to_paper: 1 });

  // None of them changed what was said of the claim
  const after = await claimsOf(page, id);
  expect(after.claims).toEqual(own.claims);
  expect(after.counts).toEqual(own.counts);
  await expect(claimWithStatus(page, "reproduced")).toHaveCount(1);
  await expect(claimWithStatus(page, "reproduced").getByTestId("claim-status")).toHaveText("Reproduced");

  // They can be saved as a table, each saying that it is not the paper's result
  const download = keptVariants(page).getByRole("link", { name: "Download as a table, the variants" });
  await expect(download).toHaveAttribute("href", `/api/paperagents/${id}/tables/variants`);
  const table = await page.request.get(`/api/paperagents/${id}/tables/variants`);
  expect(table.status()).toBe(200);
  expect(table.headers()["content-type"]).toContain("text/csv");
  expect(table.headers()["content-disposition"]).toContain("attachment");
  const csv = await table.text();
  expect(csv).toContain("Is it the paper's result");
  expect(csv).toContain("values = [4, 5, 6] in place of [1, 2, 3]");
  expect(csv).toContain("Is it the zero?");
  expect(await accessibilityProblems(page)).toEqual([]);

  // They are taken away only when it is said to be, and what was said of the claim stays
  await keptVariants(page).getByRole("button", { name: "Take the variants away" }).click();
  const asking = page.getByRole("alertdialog");
  await expect(asking.getByRole("heading", { name: "Take away the variants of the claims of Scored varied?" })).toBeVisible();
  await expect(asking).toContainText("This takes away the 3 variants that were kept. What was said of each claim stays as it was, as no variant changes it.");
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(asking).toHaveCount(0);
  await expect(variantRows(page)).toHaveCount(3);
  await keptVariants(page).getByRole("button", { name: "Take the variants away" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Take away" }).click();
  await expect(keptVariants(page)).toHaveCount(0);
  expect(await variantsOf(page, id)).toMatchObject({ variants: [], stale: 0, counts: { variants: 0 } });
  expect((await claimsOf(page, id)).claims).toEqual(own.claims);
  await expect(variantsForm(page)).toBeVisible();
  await expect(claimWithStatus(page, "reproduced")).toHaveCount(1);
});

test("says when the call alone does not give what the tutorial got, so that a variant of it cannot be set beside the claim", async ({ page }) => {
  test.setTimeout(90_000);
  const id = await agentWithTriedClaims(page, "Scored differing");
  const reproduced = await claimWith(page, id, "reproduced");
  await variantsForm(page).getByLabel("Claim", { exact: true }).selectOption(reproduced);
  await variantsForm(page).getByLabel("values", { exact: true }).fill("[4, 5, 6]");
  await makeVariantButton(page).click();
  await expect(variantRows(page)).toHaveCount(1, { timeout: 30_000 });
  const row = variantRows(page).first();
  await expect(row.getByTestId("variant-status")).toHaveText("Gave a number");
  await expect(row.getByTestId("variant-comparable")).toHaveText("Not comparable");
  await expect(row).toHaveAttribute("data-control", "differs");
  await expect(row.getByTestId("variant-control")).toHaveText(
    "Not comparable: the same call with nothing changed did not give what the tutorial got, so the call alone does not stand for what the tutorial did.",
  );
  await expect(page.getByTestId("variants-counts")).toHaveText("1 variant: 0 comparable, 0 that give a number that rounds to the paper's. None of them is the paper's result.");
  await row.getByRole("button", { name: /^Show how/ }).click();
  await expect(row.getByTestId("variant-text")).toContainText("did not give what the tutorial got");
  await expect(row.getByRole("list", { name: "How this variant was made" })).toContainText("With nothing changed, it differs from what the tutorial got: the value is 0.94 where it was 0.93.");
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("follows the making of a variant while it goes on, waits for it before anything else is done to the agent, and keeps nothing if it is stopped", async ({ page }) => {
  test.setTimeout(90_000);
  const id = await agentWithTriedClaims(page, "Scored tedious");
  const reproduced = await claimWith(page, id, "reproduced");
  await variantsForm(page).getByLabel("Claim", { exact: true }).selectOption(reproduced);
  await variantsForm(page).getByLabel("values", { exact: true }).fill("[4, 5, 6]");
  await makeVariantButton(page).click();

  const stop = makingVariant(page).getByRole("button", { name: "Stop: Making a variant of a claim: Scored tedious" });
  await expect(stop).toBeVisible();
  await expect(variantsForm(page)).toHaveCount(0);
  await expect(keptVariants(page)).toHaveCount(0);
  expect((await variantsOf(page, id)).job).not.toBeNull();
  await page.reload();
  await expect(stop).toBeVisible();
  await expect(variantsForm(page)).toHaveCount(0);
  // Nothing else is done to the agent while it goes on
  await expect(reading(page)).toContainText("A variant of a claim is being made. Reading waits for that.");
  await expect(reading(page).getByRole("button", { name: /^(Read the paper|Carry on reading)$/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Delete Scored tedious" })).toBeDisabled();
  await expect(claimsForm(page).getByRole("button", { name: "Waiting…" })).toBeDisabled();
  await expect(keptClaims(page).getByRole("button", { name: "Take the trying away" })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);
  const claim = await claimWith(page, id, "reproduced");
  expect((await page.request.post(`/api/paperagents/${id}/variants`, { data: { claim, changes: { values: [7] } } })).status()).toBe(409);
  expect((await page.request.delete(`/api/paperagents/${id}/variants`)).status()).toBe(409);
  expect((await page.request.delete(`/api/paperagents/${id}/reproduction`)).status()).toBe(409);

  await stop.click();

  await expect(makingVariant(page).getByText("Stopped", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(variantsForm(page)).toBeVisible();
  expect(await variantsOf(page, id)).toMatchObject({ job: null, variants: [], stale: 0 });
  await expect(keptVariants(page)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Delete Scored tedious" })).toBeEnabled();
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("does not show variants of claims that were tried before the paper was read again to other claims, and says that they are kept", async ({ page }) => {
  test.setTimeout(120_000);
  const id = await agentWithTriedClaims(page, "Scored varied stale");
  await makeTheVariant(page, id, await claimWith(page, id, "reproduced"), { values: [4, 5, 6] });
  await page.reload();
  await expect(variantRows(page)).toHaveCount(1);

  // A paper that says one thing more is read in its place, so that the claims that were tried are not those that are kept now
  await sendPaper(page, id, "claims.txt", `${claimsPaper("Scored varied stale")}\n\nA fifth method reached an AUROC of 0.62 on the same nuclei (Figure 2).`);
  await readTheAgent(page, id);
  await page.reload();
  await expect(page.getByTestId("variants-problem")).toHaveText(
    "The claims were tried against another run of the tutorials, or other claims, than are kept now. Try them again.",
  );
  await expect(page.getByTestId("variants-problem")).toHaveAttribute("data-code", "stale");
  expect(await variantsOf(page, id)).toMatchObject({ ready: false, variants: [], stale: 1, claims: [] });
  await expect(variantRows(page)).toHaveCount(0);
  await expect(variantsForm(page)).toHaveCount(0);
  await expect(page.getByTestId("variants-counts")).toHaveText(
    "No variant has been made. 1 variant made of another run of the tutorials, other claims, or another trying is kept and not shown.",
  );
  await expect(keptVariants(page)).not.toContainText("values");
  await expect(keptVariants(page).getByRole("link", { name: "Download as a table, the variants" })).toHaveCount(0);
  const refused = await page.request.post(`/api/paperagents/${id}/variants`, { data: { claim: await claimWith(page, id, "stale"), changes: { values: [7] } } });
  expect(refused.status()).toBe(409);
  expect((await refused.json()).error.code).toBe("stale");
  expect(await accessibilityProblems(page)).toEqual([]);

  // What is kept and not shown can be taken away
  await keptVariants(page).getByRole("button", { name: "Take the variants away" }).click();
  await expect(page.getByRole("alertdialog")).toContainText("This takes away the variant that was kept.");
  await page.getByRole("alertdialog").getByRole("button", { name: "Take away" }).click();
  await expect(keptVariants(page)).toHaveCount(0);
  expect(await variantsOf(page, id)).toMatchObject({ stale: 0, variants: [] });

  // Trying the claims again is of what is kept now, and a variant can be made of it
  await tryTheClaims(page, id);
  await page.reload();
  await expect(page.getByTestId("variants-problem")).toHaveCount(0);
  await expect(variantsForm(page)).toBeVisible();
});

test("takes away the variants when the claims are tried again, which are of the places that the earlier trying held the claims to", async ({ page }) => {
  test.setTimeout(120_000);
  const id = await agentWithTriedClaims(page, "Scored varied again");
  await makeTheVariant(page, id, await claimWith(page, id, "reproduced"), { values: [4, 5, 6] });
  await page.reload();
  await expect(variantRows(page)).toHaveCount(1);
  await claimsForm(page).getByLabel("Most it may spend, in dollars").fill("1");
  await claimsForm(page).getByRole("button", { name: "Try the claims again" }).click();
  await expect(page.getByTestId("claims-counts")).toBeVisible({ timeout: 20_000 });
  await expect(variantRows(page)).toHaveCount(0, { timeout: 20_000 });
  await expect(keptVariants(page)).toHaveCount(0);
  expect(await variantsOf(page, id)).toMatchObject({ variants: [], stale: 0 });
  await expect(variantsForm(page)).toBeVisible();

  // The trying taken away takes away the variants too, and nothing is left to make one of
  await makeTheVariant(page, id, await claimWith(page, id, "reproduced"), { values: [4, 5, 6] });
  await page.reload();
  await expect(variantRows(page)).toHaveCount(1);
  await keptClaims(page).getByRole("button", { name: "Take the trying away" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Take away" }).click();
  await expect(keptClaims(page)).toHaveCount(0);
  await expect(variantRows(page)).toHaveCount(0);
  await expect(page.getByTestId("variants-problem")).toHaveAttribute("data-code", "no_reproduction");
  await expect(variantsForm(page)).toHaveCount(0);
  expect(await variantsOf(page, id)).toMatchObject({ ready: false, variants: [], stale: 0 });
});

test("says what is wrong when the server refuses to make a variant, and looks again at what it shows when what it showed is out of date", async ({ page }) => {
  const id = await agentWithTriedClaims(page, "Scored varied refused");
  const claim = await claimWith(page, id, "reproduced");
  await variantsForm(page).getByLabel("Claim", { exact: true }).selectOption(claim);
  await variantsForm(page).getByLabel("values", { exact: true }).fill("[4, 5, 6]");

  // Docker is not running, as the server says it
  await page.route("**/api/paperagents/*/variants", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "docker_missing", message: "Docker is not running, and making a variant takes it" } }),
        })
      : route.fallback(),
  );
  await makeVariantButton(page).click();
  await expect(variantsForm(page).getByRole("alert")).toContainText("Docker is not running, and making a variant takes it");
  expect(await accessibilityProblems(page)).toEqual([]);
  await page.unroute("**/api/paperagents/*/variants");
  expect(await variantsOf(page, id)).toMatchObject({ variants: [], job: null });

  // The server refuses what the page does not, which is said as it says it
  await page.route("**/api/paperagents/*/variants", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "invalid", message: "The call was not given an argument called speed. It was given values" } }),
        })
      : route.fallback(),
  );
  await makeVariantButton(page).click();
  await expect(variantsForm(page).getByRole("alert")).toContainText("The call was not given an argument called speed. It was given values");
  await page.unroute("**/api/paperagents/*/variants");

  // The trying is taken away behind the page's back, so that there is nothing that was tried, which the page is told of by the server
  expect((await page.request.delete(`/api/paperagents/${id}/reproduction`)).status()).toBe(200);
  await makeVariantButton(page).click();
  await expect(page.getByTestId("variants-problem")).toHaveAttribute("data-code", "no_reproduction");
  await expect(variantsForm(page)).toHaveCount(0);
  expect((await variantsOf(page, id)).job).toBeNull();
  expect(await accessibilityProblems(page)).toEqual([]);
});

// A variant as the server keeps one, for a test to say what it came to
function fakeVariant(id: string, claim: string, part: Record<string, unknown>) {
  return {
    id,
    made_at: new Date().toISOString(),
    seconds: 3.2,
    limits: { minutes: 5, repeats: 2, gigabytes: 2 },
    note: null,
    claim,
    quote: "CellMapper reached an AUROC of 0.93 on held-out mouse hippocampus nuclei.",
    number: "0.93",
    tutorial: { id: "01", path: "tutorials/quickstart.ipynb" },
    call: 3,
    function: "cellmapper.core.score",
    where: "a call of cellmapper.core.score(values=[1, 2, 3]), at result",
    path: [],
    changes: [{ name: "values", was: [1, 2, 3], now: [9] }],
    claim_run: 0.93,
    control: { verdict: "match", gave: 0.93, differences: [], error: null },
    variant: { status: "gave", gave: 0.93, values: [0.93, 0.93], type: "float", error: null, differences: [] },
    comparable: true,
    rounds_to_paper: true,
    repeats: 2,
    tolerance: { relative: 0.001, absolute: 0.000001 },
    text: `With values = [9] in place of [1, 2, 3], the call gave 0.93. ${CLOSING}`,
    ...part,
  };
}

test("says each way that a variant can come out, and what the call with nothing changed did, in words and not only a colour", async ({ page }) => {
  const id = await agentWithTriedClaims(page, "Scored varied ways");
  const claim = await claimWith(page, id, "reproduced");
  const real = await variantsOf(page, id);
  const gave = { status: "gave", gave: 1.02, values: [1.02, 1.02], type: "float", error: null, differences: [] };
  const variants = [
    fakeVariant("aaaaaaaaaaaa", claim, { variant: gave, rounds_to_paper: false }),
    fakeVariant("bbbbbbbbbbbb", claim, {
      variant: { status: "no_place", gave: null, values: [null, null], type: "list", error: null, differences: [] },
      comparable: false,
      rounds_to_paper: null,
    }),
    fakeVariant("cccccccccccc", claim, {
      variant: { status: "unstable", gave: null, values: [0.5, 0.6], type: "float", error: null, differences: ["result: 0.5 against 0.6"] },
      comparable: false,
      rounds_to_paper: null,
    }),
    fakeVariant("dddddddddddd", claim, {
      variant: { status: "error", gave: null, values: [], type: null, error: { type: "ValueError", message: "negative" }, differences: [] },
      control: { verdict: "error", gave: null, differences: [], error: { type: "KeyError", message: "x" } },
      comparable: false,
      rounds_to_paper: null,
    }),
    fakeVariant("eeeeeeeeeeee", claim, {
      variant: { status: "not_run", gave: null, values: [], type: null, error: null, differences: [] },
      control: { verdict: "not_run", gave: null, differences: [], error: null },
      comparable: false,
      rounds_to_paper: null,
    }),
    fakeVariant("ffffffffffff", claim, {
      variant: gave,
      control: { verdict: "differs", gave: null, differences: ["result: 0.7 against 0.93"], error: null },
      comparable: false,
      rounds_to_paper: false,
    }),
  ];
  await page.route("**/api/paperagents/*/variants", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: { ...real, variants, counts: { variants: 6, comparable: 1, rounds_to_paper: 1 } } })
      : route.fallback(),
  );
  await page.reload();
  await expect(variantRows(page)).toHaveCount(6);
  const statuses = ["Gave a number", "Gave no number at the place", "Gave something else each time", "Stopped with an error", "Was not made in the time", "Gave a number"];
  await expect(variantRows(page).getByTestId("variant-status")).toHaveText(statuses);
  await expect(variantRows(page).getByTestId("variant-not-result")).toHaveCount(6);
  await expect(variantRows(page).getByTestId("variant-comparable")).toHaveText([
    "Comparable",
    "Not comparable",
    "Not comparable",
    "Not comparable",
    "Not comparable",
    "Not comparable",
  ]);
  const outcome = (index: number) => variantRows(page).nth(index).getByTestId("variant-outcome");
  await expect(outcome(1)).toHaveText("It ran, and gave a list with no number at the place that the claim was held to.");
  await expect(outcome(2)).toHaveText("It gave something else each time it was made, so no one number is said.");
  await expect(outcome(3)).toHaveText("It stopped with ValueError: negative.");
  await expect(outcome(4)).toHaveText("It was not made in the time that was given.");
  const control = (index: number) => variantRows(page).nth(index).getByTestId("variant-control");
  await expect(control(3)).toContainText("the same call with nothing changed stopped with an error, so the call alone does not stand for what the tutorial did.");
  await expect(control(4)).toContainText("the same call with nothing changed was not made in the time, so the call alone");
  await expect(control(5)).toContainText("the same call with nothing changed did not give what the tutorial got");
  // Only a number that the variant gave is said to round to the paper's or not
  await expect(variantRows(page).nth(1).getByTestId("variant-rounds")).toHaveCount(0);
  await expect(variantRows(page).nth(0).getByTestId("variant-rounds")).toHaveText("The number that it gave does not round to the paper's 0.93.");
  await variantRows(page).nth(3).getByRole("button", { name: /^Show how/ }).click();
  const how = variantRows(page).nth(3).getByRole("list", { name: "How this variant was made" });
  await expect(how).toContainText("With nothing changed, it stopped with KeyError: x.");
  await expect(how).toContainText("With the changes, it stopped with ValueError: negative.");
  await variantRows(page).nth(2).getByRole("button", { name: /^Show how/ }).click();
  await expect(variantRows(page).nth(2).getByRole("list", { name: "How this variant was made" })).toContainText("With the changes, the times it was made differ: result: 0.5 against 0.6.");
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("offers only the arguments that can be changed, and says why a claim whose call cannot be made again is not offered", async ({ page }) => {
  const id = await agentWithTriedClaims(page, "Scored varied args");
  const claim = await claimWith(page, id, "reproduced");
  const real = await variantsOf(page, id);
  const other = real.claims.find((each: { claim: string; can: boolean }) => each.claim !== claim && each.can);
  const refusals = [
    { claim: "r1", can: false, refused: { code: "not_a_call", message: "That claim was held to a line that the tutorial printed, and a line is not a call that can be made again with other arguments" } },
    { claim: "r2", can: false, refused: { code: "cannot_call", message: "The function cannot be read from the code, so it cannot be called directly" } },
  ];
  const mixed = {
    claim,
    can: true,
    refused: null,
    function: "cellmapper.core.score",
    arguments: [
      { name: "values", text: "[1, 2, 3]", value: [1, 2, 3], plain: true },
      { name: "adata", text: "<AnnData object with n_obs × n_vars = 3 × 2>", value: null, plain: false },
      { name: "labels", text: `['${"a".repeat(80)}'...`, value: null, plain: true },
      { name: "flag", text: "None", value: null, plain: true },
    ],
  };
  await page.route("**/api/paperagents/*/variants", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: { ...real, claims: [mixed, other, ...refusals] } }) : route.fallback(),
  );
  await page.reload();
  const form = variantsForm(page);
  await form.getByLabel("Claim", { exact: true }).selectOption(claim);
  await expect(form.getByTestId("variant-argument")).toHaveCount(4);
  // An argument that cannot be given as a value from here is not offered a place to be changed, and says so
  const handle = form.locator("[data-testid=variant-argument][data-name=adata]");
  await expect(handle).toContainText("Given <AnnData object with n_obs × n_vars = 3 × 2>");
  await expect(handle).toContainText("This is not a value that an argument can be given from here, so it is not changed.");
  await expect(handle.getByRole("textbox")).toHaveCount(0);
  await expect(form.getByRole("textbox", { name: "adata" })).toHaveCount(0);
  // One that was too long to be offered has no value to compare, so what is typed is sent for the server to judge, and None is the nothing of JSON
  await form.getByLabel("flag", { exact: true }).fill("null");
  await makeVariantButton(page).click();
  await expect(form.getByText("flag was given that value, so it is not a change.", { exact: true })).toBeVisible();
  await form.getByLabel("flag", { exact: true }).fill("false");
  await expect(form.getByText("flag was given that value, so it is not a change.", { exact: true })).toHaveCount(0);
  await form.getByLabel("labels", { exact: true }).fill('["b"]');
  await expect(form.getByRole("alert")).toHaveCount(0);
  // Changing the claim starts the values over
  await form.getByLabel("Claim", { exact: true }).selectOption(other.claim);
  await form.getByLabel("Claim", { exact: true }).selectOption(claim);
  await expect(form.getByLabel("flag", { exact: true })).toHaveValue("");
  await form.getByRole("button", { name: "Why 2 claims cannot be varied" }).click();
  const why = form.getByRole("list", { name: "Claims that cannot be varied" });
  await expect(why.locator("li")).toHaveCount(2);
  await expect(why.locator("li[data-code=not_a_call]")).toContainText("is not a call that can be made again with other arguments.");
  await expect(why.locator("li[data-code=cannot_call]")).toContainText("so it cannot be called directly.");
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("says that no claim was held to a call that a variant can be made of", async ({ page }) => {
  const id = await agentWithTriedClaims(page, "Scored varied none");
  const real = await variantsOf(page, id);
  const refusals = real.claims.map((each: { claim: string }) => ({
    claim: each.claim,
    can: false,
    refused: { code: "not_a_call", message: "That claim was held to a line that the tutorial printed, and a line is not a call that can be made again with other arguments" },
  }));
  await page.route("**/api/paperagents/*/variants", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: { ...real, claims: refusals } }) : route.fallback(),
  );
  await page.reload();
  await expect(variantsForm(page)).toHaveCount(0);
  await expect(page.getByTestId("variants-none-to-make")).toContainText("No claim was held to a call that a variant can be made of.");
  await page.getByRole("button", { name: "Why 4 claims cannot be varied" }).click();
  await expect(page.getByRole("list", { name: "Claims that cannot be varied" }).locator("li")).toHaveCount(4);
  expect(await accessibilityProblems(page)).toEqual([]);
});

const SUMS_TITLE = "Adding and doubling: a method";
const SUMS_FUNCTION = "reimplemented_adding_and_doubling_a_method";
const SUMS_METHOD = "We take the numbers 0.2, 0.25 and 0.015, add them one to another, and double the sum.";
// A paper that has no code, whose method adds numbers and doubles the sum, and whose results are two numbers that follow from it
const SUMS = [
  SUMS_TITLE,
  "Abstract",
  "A method that doubles.",
  "Methods",
  SUMS_METHOD,
  "Results",
  "The doubled sum reached an AUROC of 0.930 on the held-out set.",
  "Doubled once more, the same numbers reached an AUROC of 1.860 in all.",
  "References",
  "A. One.",
].join("\n\n");

const reimplementation = (page: Page) => page.getByRole("region", { name: "Re-implementation", exact: true });
const writingForm = (page: Page) => form(page, "Write a function from the paper");
const matchingForm = (page: Page) => form(page, "Check the function against the paper");
const sectionOf = (page: Page, title: string) => writingForm(page).getByTestId("reimplementation-section").filter({ hasText: title });
const keptFunction = (page: Page) => page.getByTestId("reimplementation-kept");
const matchingChecks = (page: Page) => page.getByTestId("reimplementation-checks");
const matchingClaim = (page: Page, value: string) => matchingChecks(page).getByTestId("matching-claim").filter({ hasText: value });
const agreeBox = (page: Page) => writingForm(page).getByRole("checkbox", { name: /I have read what the model would be given/ });
const reimplementationOf = async (page: Page, id: string) => (await page.request.get(`/api/paperagents/${id}/reimplementation`)).json();

// An agent whose paper has no code and has been read, through the server, so that what a test is about is the page
async function agentWithSums(page: Page, title: string, text = SUMS): Promise<string> {
  const id = await makeAgent(page, { title, paper: { kind: "file" } });
  await sendPaper(page, id, "sums.txt", text);
  await readTheAgent(page, id);

  return id;
}

// Agrees to what the model would be given, with the most that asking it may spend, and starts the writing
async function writeFunction(page: Page, budget = "1") {
  await agreeBox(page).check();
  await writingForm(page).getByLabel("Most it may spend, in dollars").fill(budget);
  await writingForm(page).getByRole("button", { name: /^Agree, and write/ }).click();
}

test("shows what the model would be given of a paper with no code before anything is sent, and sends nothing until that is agreed to", async ({ page }) => {
  const id = await agentWithSums(page, SUMS_TITLE);
  await openAgent(page, id, SUMS_TITLE);

  await expect(reimplementation(page)).toBeVisible();
  await expect(page.getByTestId("reimplementation")).toHaveAttribute("data-ready", "true");
  await expect(page.getByTestId("reimplementation-meaning")).toContainText("A tool of tier C is a re-implementation");
  await expect(keptFunction(page)).toHaveCount(0);
  await expect(matchingChecks(page)).toHaveCount(0);

  // The sections of the paper are listed, and those of the method are the ones that are chosen to begin with
  await expect(writingForm(page).getByTestId("reimplementation-section")).toHaveCount(3);
  await expect(sectionOf(page, "Methods").getByRole("checkbox")).toBeChecked();
  await expect(sectionOf(page, "Methods")).toContainText("Of the method");
  await expect(sectionOf(page, "Abstract").getByRole("checkbox")).not.toBeChecked();
  await expect(sectionOf(page, "Results").getByRole("checkbox")).not.toBeChecked();

  // What the model would be given is shown as it is sent, and it is only the words that were chosen
  const offer = page.getByTestId("reimplementation-offer");
  await expect(offer).toHaveAttribute("data-current", "true");
  await expect(page.getByTestId("reimplementation-offer-what")).toContainText("1 place of the paper (Methods)");
  await expect(page.getByTestId("reimplementation-offer-what")).toContainText(`The function would be called ${SUMS_FUNCTION}.`);
  await expect(offer.getByRole("region", { name: "What the model would be given" })).toContainText(SUMS_METHOD);
  await expect(offer.getByRole("region", { name: "What the model would be given" })).not.toContainText("AUROC");
  await expect(offer).toContainText(`What ${(await reimplementationOf(page, id)).settings_model} would be given`);
  expect(await accessibilityProblems(page)).toEqual([]);

  // Looking at what would be given is not asking for it to be written, so what is wrong with the budget is not said yet
  await writingForm(page).getByRole("button", { name: "Show what it would be given" }).click();
  await expect(offer).toHaveAttribute("data-current", "true");
  await expect(writingForm(page).getByText("Say the most it may spend.")).toHaveCount(0);

  // Nothing is sent without agreeing, and the agreement is of what was read
  await expect(writingForm(page).getByRole("button", { name: /^Agree, and write/ })).toBeDisabled();
  await agreeBox(page).check();
  await expect(writingForm(page).getByRole("button", { name: /^Agree, and write/ })).toBeEnabled();
  await writingForm(page).getByRole("button", { name: /^Agree, and write/ }).click();
  await expect(writingForm(page).getByText("Say the most it may spend.")).toBeVisible();
  await writingForm(page).getByLabel("Most it may spend, in dollars").fill("lots");
  await writingForm(page).getByRole("button", { name: /^Agree, and write/ }).click();
  await expect(writingForm(page).getByText(/is an amount in dollars, such as 1 or 0.50/)).toBeVisible();
  expect((await reimplementationOf(page, id)).kept).toBeNull();

  // Choosing another section makes what was read not what would be sent, so the agreement is taken back until it is read again
  await sectionOf(page, "Results").getByRole("checkbox").check();
  await expect(offer).toHaveAttribute("data-current", "false");
  await expect(page.getByTestId("reimplementation-offer-changed")).toContainText("What you chose is not what this is of.");
  await expect(agreeBox(page)).toBeDisabled();
  await expect(agreeBox(page)).not.toBeChecked();
  await expect(writingForm(page).getByRole("button", { name: /^Agree, and write/ })).toBeDisabled();
  await writingForm(page).getByRole("button", { name: "Show what it would be given" }).click();
  await expect(offer).toHaveAttribute("data-current", "true");
  await expect(page.getByTestId("reimplementation-offer-what")).toContainText("1 place of the paper (Methods, Results)");
  await expect(offer.getByRole("region", { name: "What the model would be given" })).toContainText("AUROC of 0.930");
  await expect(agreeBox(page)).not.toBeChecked();
  expect(await accessibilityProblems(page)).toEqual([]);

  // Words to look for are given too, a name that is not one is said before anything is asked, and what the server cannot offer is said
  await sectionOf(page, "Results").getByRole("checkbox").uncheck();
  await writingForm(page).getByLabel("What the function is called").fill("Doubled Sum");
  await writingForm(page).getByRole("button", { name: "Show what it would be given" }).click();
  await expect(writingForm(page).getByText(/lowercase letters, digits, and underscores/).first()).toBeVisible();
  await writingForm(page).getByLabel("What the function is called").fill("doubled_sum");
  await sectionOf(page, "Methods").getByRole("checkbox").uncheck();
  await writingForm(page).getByRole("button", { name: "Show what it would be given" }).click();
  await expect(writingForm(page).getByText("Choose a section of the paper, or say words to look for in it.")).toBeVisible();
  await writingForm(page).getByLabel("Words to look for in the paper").fill("zzzzqq");
  await writingForm(page).getByRole("button", { name: "Show what it would be given" }).click();
  await expect(page.getByTestId("reimplementation-choice-problem")).toContainText("Choose a section of the paper, or search for the words");
  await expect(offer).toHaveCount(0);
  await writingForm(page).getByLabel("Words to look for in the paper").fill("numbers");
  await writingForm(page).getByRole("button", { name: "Show what it would be given" }).click();
  await expect(page.getByTestId("reimplementation-choice-problem")).toHaveCount(0);
  await expect(offer).toHaveAttribute("data-current", "true");
  await expect(page.getByTestId("reimplementation-offer-what")).toContainText("The function would be called doubled_sum.");
  await expect(offer.getByRole("region", { name: "What the model would be given" })).toContainText(SUMS_METHOD);
  expect(await accessibilityProblems(page)).toEqual([]);
  expect((await reimplementationOf(page, id)).kept).toBeNull();
});

test("writes a function from the paper's words, shows its code as a re-implementation, checks it against the paper's numbers, which makes it of tier C, gives it to conversations, and takes it away", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const id = await agentWithSums(page, SUMS_TITLE);
  await openAgent(page, id, SUMS_TITLE);
  const prefix = "adding_and_doubling_a_method_";

  await writeFunction(page);
  await expect(keptFunction(page)).toHaveAttribute("data-status", "written", { timeout: 30_000 });
  await expect(page.getByTestId("reimplementation-status")).toHaveText("Written");
  await expect(page.getByTestId("reimplementation-how")).toContainText("by gpt-5.2 in 1 attempt");
  await expect(page.getByTestId("reimplementation-how")).toContainText("imported in a container with no network, and nothing else of it was run");
  await expect(page.getByTestId("reimplementation-how")).toContainText("It was given 1 place of the paper (Methods)");
  await expect(keptFunction(page).getByTestId("reimplementation-label")).toBeVisible();
  const code = keptFunction(page).getByRole("region", { name: "The function's code" });
  await expect(code).toContainText(`def ${SUMS_FUNCTION}(numbers: list[float], times: int = 2) -> float:`);
  await expect(keptFunction(page)).toContainText("None of the authors' code is in it.");
  // What the model was given is not shown again, and the writing goes with the job that did it
  await expect(page.getByRole("region", { name: "Writing the function" })).toContainText("Done");
  const kept = await reimplementationOf(page, id);
  expect(kept.kept).toMatchObject({ status: "written", name: SUMS_FUNCTION, current: true });

  // The claims it can be checked against are listed, none tried, and it is of no tier and is given to nothing
  await expect(matchingChecks(page)).toHaveAttribute("data-tier", "none");
  await expect(page.getByTestId("matching-label")).toContainText("It is given to no conversation until it gives a number that the paper reports.");
  await expect(matchingChecks(page).getByTestId("matching-claim")).toHaveCount(2);
  await expect(matchingClaim(page, "0.930").getByText("Not tried yet")).toBeVisible();
  await expect(matchingClaim(page, "1.860").getByText("Not tried yet")).toBeVisible();
  await expect(givenTools(page)).toHaveCount(4);
  await expect(givenSummary(page)).toContainText("Tier D: reads the paper");
  await expect(page.getByTestId("given-why")).toContainText("A function can be written from the paper's words under Re-implementation");
  expect(await accessibilityProblems(page)).toEqual([]);

  // A model is asked for the inputs, within what it may spend, or the person gives them: with neither, there is nothing to call it with
  await expect(matchingForm(page).getByLabel("Most time for all of the calls, in minutes")).toHaveValue("5");
  await matchingForm(page).getByRole("checkbox", { name: "Let a model read the inputs from the paper" }).uncheck();
  await expect(matchingForm(page).getByLabel("Most it may spend, in dollars")).toHaveCount(0);
  await matchingForm(page).getByRole("button", { name: "Check it against the paper" }).click();
  await expect(matchingForm(page).getByText(/Give the inputs of a claim first, or let a model read them from the paper/)).toBeVisible();
  await matchingForm(page).getByRole("checkbox", { name: "Let a model read the inputs from the paper" }).check();
  await matchingForm(page).getByRole("button", { name: "Check it against the paper" }).click();
  await expect(matchingForm(page).getByText("Say the most it may spend.")).toBeVisible();
  await matchingForm(page).getByLabel("Most it may spend, in dollars").fill("1");
  await matchingForm(page).getByLabel("Most time for all of the calls, in minutes").fill("0");
  await matchingForm(page).getByRole("button", { name: "Check it against the paper" }).click();
  await expect(matchingForm(page).getByText(/is a whole number from 1 to 30/)).toBeVisible();
  expect((await reimplementationOf(page, id)).checks.kept).toBeNull();
  expect(await accessibilityProblems(page)).toEqual([]);

  // It is called with what the paper's own words give, and the number that the paper reports is looked for in what it gave
  await matchingForm(page).getByLabel("Most time for all of the calls, in minutes").fill("5");
  await matchingForm(page).getByRole("button", { name: "Check it against the paper" }).click();
  await expect(matchingChecks(page)).toHaveAttribute("data-tier", "C", { timeout: 30_000 });
  await expect(matchingChecks(page).getByText("Tier C", { exact: true })).toBeVisible();
  await expect(page.getByTestId("matching-label")).toContainText("Re-implementation, matched 1 of 2 tried.");
  await expect(page.getByTestId("matching-counts")).toHaveText("1 matched, 1 not found.");
  await expect(page.getByTestId("matching-how")).toContainText("gpt-5.2 was asked for inputs 2 times");
  await expect(matchingClaim(page, "0.930")).toHaveAttribute("data-status", "matched");
  await expect(matchingClaim(page, "1.860")).toHaveAttribute("data-status", "not_found");
  await expect(matchingClaim(page, "0.930").getByTestId("matching-status")).toHaveText("Matched");
  await expect(matchingClaim(page, "0.930")).toContainText("Called with the inputs that the model read in the passage:");
  await expect(matchingClaim(page, "0.930")).toContainText('{"numbers":[0.2,0.25,0.015]}');
  await expect(matchingClaim(page, "0.930")).toContainText("It gave 0.93, and 0.93 at");
  await expect(matchingClaim(page, "1.860")).toContainText("It gave 0.93.");
  await expect(page.getByRole("region", { name: "Checking the function" })).toContainText("Done");
  expect((await reimplementationOf(page, id)).checks).toMatchObject({ tier: "C", label: "Re-implementation, matched 1 of 2 tried" });
  expect(await accessibilityProblems(page)).toEqual([]);

  // A conversation is given it as a re-implementation, labelled so in what the page says of each tool
  await expect(givenTools(page)).toHaveCount(5);
  await expect(givenSummary(page)).toContainText("Tier C: a re-implementation, not the authors' code, which gave a number that the paper reports");
  await expect(givenSummary(page)).toContainText("4 tools that read the paper and 1 that runs a re-implementation of it, not the authors' code.");
  const reimplemented = inConversations(page).locator("[data-testid=given-tool][data-kind=reimplementation]");
  await expect(reimplemented).toHaveCount(1);
  await expect(reimplemented).toContainText("Tier C");
  await expect(reimplemented.getByTestId("reimplementation-label")).toHaveText("Re-implementation, not the authors' code");
  await expect(reimplemented).toContainText("Runs a function that a model wrote from the paper's words, in a sandbox with no network");
  await expect(page.getByTestId("given-reimplementation")).toContainText("says so too");
  await expect(inConversations(page)).toContainText("A call may take up to 5 minutes, in a container with no network");
  await expect(page.getByTestId("given-why")).toHaveCount(0);
  const tool = (await givenOf(page, id)).tools.find((one: { kind: string }) => one.kind === "reimplementation");
  expect(tool).toMatchObject({ tier: "C", label: "Re-implementation, not the authors' code" });
  expect(await accessibilityProblems(page)).toEqual([]);

  // It is offered to a conversation that is made after the agent is given, and only where code runs
  await openAgent(page, id, SUMS_TITLE);
  await giveBox(page).click();
  await expect(giveBox(page)).toBeChecked();
  expect(await offeredIn(page, "local")).toContain(tool.name);
  expect(await offeredIn(page, "nowhere")).not.toContain(tool.name);
  expect((await offeredIn(page, "local")).filter((name) => name.startsWith(prefix))).toHaveLength(5);

  // The checks are taken away, after asking: it is of no tier again, and is given to nothing, and the function stays
  await openAgent(page, id, SUMS_TITLE);
  await matchingChecks(page).getByRole("button", { name: "Take the checks away" }).click();
  const away = page.getByRole("alertdialog", { name: `Take away the checks of the function written from ${SUMS_TITLE}?` });
  await away.getByRole("button", { name: "Keep" }).click();
  await expect(away).toHaveCount(0);
  await expect(matchingChecks(page)).toHaveAttribute("data-tier", "C");
  await matchingChecks(page).getByRole("button", { name: "Take the checks away" }).click();
  await away.getByRole("button", { name: "Take away", exact: true }).click();
  await expect(matchingChecks(page)).toHaveAttribute("data-tier", "none");
  await expect(matchingClaim(page, "0.930").getByText("Not tried yet")).toBeVisible();
  await expect(matchingChecks(page).getByRole("button", { name: "Take the checks away" })).toHaveCount(0);
  await expect(givenTools(page)).toHaveCount(4);
  await expect(givenSummary(page)).toContainText("Tier D: reads the paper");
  await expect(keptFunction(page)).toHaveAttribute("data-status", "written");
  expect((await offeredIn(page, "local")).filter((name) => name.startsWith(prefix))).toHaveLength(4);
  expect(await accessibilityProblems(page)).toEqual([]);

  // The function is taken away, after asking, with what was kept of writing it, and it can be written again
  await openAgent(page, id, SUMS_TITLE);
  await keptFunction(page).getByRole("button", { name: "Take the function away" }).click();
  const gone = page.getByRole("alertdialog", { name: `Take away the function written from ${SUMS_TITLE}?` });
  await gone.getByRole("button", { name: "Take away", exact: true }).click();
  await expect(keptFunction(page)).toHaveCount(0);
  await expect(matchingChecks(page)).toHaveCount(0);
  await expect(writingForm(page).getByRole("heading", { name: "Write a function from the paper" })).toBeVisible();
  expect((await reimplementationOf(page, id)).kept).toBeNull();
  expect(await accessibilityProblems(page)).toEqual([]);
});

// Writes the function through the server, agreeing to what is offered, and waits until that is done
async function writeThrough(page: Page, id: string) {
  const { offer } = await reimplementationOf(page, id);
  const started = await page.request.post(`/api/paperagents/${id}/reimplementation`, { data: { name: offer.name, sections: offer.sections, agreed: offer.key, max_cost: 1 } });
  expect(started.status()).toBe(202);
  await expect.poll(async () => (await reimplementationOf(page, id)).job, { timeout: 20_000 }).toBeNull();
  expect((await reimplementationOf(page, id)).kept).toMatchObject({ status: "written" });
}

// Checks the function against the paper through the server, and waits until that is done
async function matchThrough(page: Page, id: string, data: Record<string, unknown> = { ask: true, max_cost: 1 }) {
  const started = await page.request.post(`/api/paperagents/${id}/reimplementation/checks`, { data });
  expect(started.status()).toBe(202);
  await expect.poll(async () => (await reimplementationOf(page, id)).checks.job, { timeout: 30_000 }).toBeNull();
}

const inputsForm = (page: Page, value: string) => form(page, `Your inputs for the claim of ${value}`);

test("gives the inputs of a claim in the person's own words, holds them to the function, and calls the function with them in place of what a model reads", async ({ page }) => {
  test.setTimeout(120_000);
  const id = await agentWithSums(page, SUMS_TITLE);
  await writeThrough(page, id);
  await matchThrough(page, id);
  await openAgent(page, id, SUMS_TITLE);
  await expect(matchingClaim(page, "1.860")).toHaveAttribute("data-status", "not_found");

  // The passage that a model is shown is what the person is shown too, and the inputs begin as what the model read
  const claim = matchingClaim(page, "1.860");
  await claim.getByRole("button", { name: /Show the passage, and give inputs/ }).click();
  await expect(claim.getByRole("region", { name: "The passage around the claim of 1.860" })).toContainText(SUMS_METHOD);
  const inputs = inputsForm(page, "1.860");
  const box = inputs.getByLabel("Your inputs, as JSON");
  await expect(box).toHaveValue(JSON.stringify({ numbers: [0.2, 0.25, 0.015] }, null, 2));
  await expect(inputs).toContainText("Its parameters: numbers (list[float], must be given); times (int, 2 if not given).");
  expect(await accessibilityProblems(page)).toEqual([]);

  // What is wrong with them is said before they are sent, and by the server when only it can tell
  const keep = inputs.getByRole("button", { name: "Keep these inputs" });
  await box.fill("not json");
  await keep.click();
  await expect(inputs.getByText("This is not JSON. Give the inputs as an object, by the names of the parameters.")).toBeVisible();
  await box.fill("[1, 2]");
  await keep.click();
  await expect(inputs.getByText("The inputs are a JSON object, by the names of the parameters.")).toBeVisible();
  await box.fill('{"count": 3}');
  await keep.click();
  await expect(inputs.getByText("The function has no parameter named count.")).toBeVisible();
  await box.fill("{}");
  await keep.click();
  await expect(inputs.getByText("Give numbers, which has no default.")).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
  await box.fill('{"numbers": [1.86]}');
  await keep.click();
  await expect(inputs.getByRole("alert")).toBeVisible();
  await expect(inputs).toContainText(/1\.86/);
  await box.fill('{"numbers": "many"}');
  await keep.click();
  await expect(inputs.getByRole("alert")).toBeVisible();
  await box.fill('{"numbers": [1e400]}');
  await keep.click();
  await expect(inputs.getByText("A number in the inputs is too big to be sent exactly.")).toBeVisible();
  expect((await reimplementationOf(page, id)).checks.claims.every((one: { inputs: unknown }) => one.inputs === null)).toBe(true);

  // Inputs that fit the function are kept as the person's, and are what it is called with when it is checked next
  await box.fill('{"numbers": [0.4, 0.5, 0.03], "times": 2}');
  await keep.click();
  await expect(claim.getByText("Your inputs", { exact: true })).toBeVisible();
  await expect(inputs.getByRole("button", { name: "Take your inputs away" })).toBeVisible();
  expect((await reimplementationOf(page, id)).checks.claims.find((one: { value: string }) => one.value === "1.860").inputs).toMatchObject({
    arguments: { numbers: [0.4, 0.5, 0.03], times: 2 },
  });
  expect(await accessibilityProblems(page)).toEqual([]);
  await page.reload();
  await expect(matchingClaim(page, "1.860").getByText("Your inputs", { exact: true })).toBeVisible();
  await expect(matchingClaim(page, "0.930").getByText("Your inputs", { exact: true })).toHaveCount(0);

  await matchingForm(page).getByLabel("Most it may spend, in dollars").fill("1");
  await matchingForm(page).getByRole("button", { name: /^Check it again/ }).click();
  await expect(matchingClaim(page, "1.860")).toHaveAttribute("data-status", "matched", { timeout: 30_000 });
  await expect(matchingClaim(page, "0.930")).toHaveAttribute("data-status", "matched");
  await expect(matchingClaim(page, "1.860")).toContainText("Called with the inputs that you gave:");
  await expect(matchingClaim(page, "0.930")).toContainText("Called with the inputs that the model read in the passage:");
  await expect(page.getByTestId("matching-label")).toContainText("Re-implementation, matched 2 of 2 tried.");
  await expect(page.getByTestId("matching-counts")).toHaveText("2 matched.");
  // A model was asked for the one claim that the person gave no inputs for
  await expect(page.getByTestId("matching-how")).toContainText("gpt-5.2 was asked for inputs 1 time");
  expect(await accessibilityProblems(page)).toEqual([]);

  // Without a model, only the claim that the person gave inputs for is tried
  await matchingForm(page).getByRole("checkbox", { name: "Let a model read the inputs from the paper" }).uncheck();
  await matchingForm(page).getByRole("button", { name: /^Check it again/ }).click();
  await expect(page.getByTestId("matching-how")).toContainText("No model was asked for inputs", { timeout: 30_000 });
  await expect(matchingClaim(page, "1.860")).toHaveAttribute("data-status", "matched");
  await expect(matchingClaim(page, "0.930")).toHaveAttribute("data-status", "no_inputs");
  await expect(page.getByTestId("matching-label")).toContainText("matched 1 of 1 tried");
  await expect(matchingChecks(page)).toHaveAttribute("data-tier", "C");

  // The inputs are taken away, and what the function was called with by them is no more
  await matchingClaim(page, "1.860").getByRole("button", { name: /Show the passage, and change your inputs/ }).click();
  await inputsForm(page, "1.860").getByRole("button", { name: "Take your inputs away" }).click();
  await expect(matchingClaim(page, "1.860").getByText("Your inputs", { exact: true })).toHaveCount(0);
  expect((await reimplementationOf(page, id)).checks.claims.every((one: { inputs: unknown }) => one.inputs === null)).toBe(true);
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("follows the writing of a function while it goes on, waits for it before anything else is done to the agent, and keeps that it was stopped", async ({ page }) => {
  test.setTimeout(90_000);
  const title = "Doubling tedious";
  const id = await agentWithSums(page, title);
  await openAgent(page, id, title);
  await writeFunction(page);

  const writing = page.getByRole("region", { name: "Writing the function" });
  const stop = writing.getByRole("button", { name: `Stop: Writing a function from the paper: ${title}` });
  await expect(stop).toBeVisible();
  await expect(writingForm(page)).toHaveCount(0);
  await expect(keptFunction(page)).toHaveCount(0);
  expect((await reimplementationOf(page, id)).job).not.toBeNull();
  await page.reload();
  await expect(stop).toBeVisible();
  await expect(writingForm(page)).toHaveCount(0);
  // Nothing else is done to the agent while it goes on
  await expect(reading(page)).toContainText("A function is being written from the paper. Reading waits for that.");
  await expect(reading(page).getByRole("button", { name: /^(Read the paper|Carry on reading)$/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: `Delete ${title}` })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);
  const { offer } = await reimplementationOf(page, id);
  expect((await page.request.post(`/api/paperagents/${id}/reimplementation`, { data: { name: offer.name, sections: offer.sections, agreed: offer.key, max_cost: 1 } })).status()).toBe(409);
  expect((await page.request.delete(`/api/paperagents/${id}/reimplementation`)).status()).toBe(409);

  await stop.click();

  await expect(writing.getByText("Stopped", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(writingForm(page)).toBeVisible();
  await expect(keptFunction(page)).toHaveAttribute("data-status", "stopped");
  await expect(page.getByTestId("reimplementation-status")).toHaveText("Stopped");
  await expect(page.getByTestId("reimplementation-how")).toContainText("before a function was written");
  await expect(keptFunction(page).getByRole("region", { name: "The function's code" })).toHaveCount(0);
  await expect(matchingChecks(page)).toHaveCount(0);
  expect(await reimplementationOf(page, id)).toMatchObject({ job: null, kept: { status: "stopped", source: null } });
  await expect(page.getByRole("button", { name: `Delete ${title}` })).toBeEnabled();
  expect(await accessibilityProblems(page)).toEqual([]);

  // What was kept of it is taken away, and it can be written again
  await keptFunction(page).getByRole("button", { name: "Take this away" }).click();
  await page.getByRole("alertdialog", { name: `Take away the function written from ${title}?` }).getByRole("button", { name: "Take away", exact: true }).click();
  await expect(keptFunction(page)).toHaveCount(0);
  expect((await reimplementationOf(page, id)).kept).toBeNull();
});

test("follows the checking of a function while it goes on, waits for it before anything else is done to the agent, and keeps it of no tier if it is stopped", async ({ page }) => {
  test.setTimeout(120_000);
  const title = "Doubling tedious";
  const id = await agentWithSums(page, title);
  await writeThrough(page, id);
  await openAgent(page, id, title);
  await matchingForm(page).getByLabel("Most it may spend, in dollars").fill("1");
  await matchingForm(page).getByRole("button", { name: "Check it against the paper" }).click();

  const checking = page.getByRole("region", { name: "Checking the function" });
  const stop = checking.getByRole("button", { name: `Stop: Checking the function against the paper: ${title}` });
  await expect(stop).toBeVisible();
  await expect(matchingForm(page)).toHaveCount(0);
  await expect(matchingChecks(page)).toHaveCount(0);
  expect((await reimplementationOf(page, id)).checks.job).not.toBeNull();
  await page.reload();
  await expect(stop).toBeVisible();
  await expect(matchingForm(page)).toHaveCount(0);
  // Nothing else is done to the agent while it goes on
  await expect(reading(page)).toContainText("The function written from the paper is being checked. Reading waits for that.");
  await expect(reading(page).getByRole("button", { name: /^(Read the paper|Carry on reading)$/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: `Delete ${title}` })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);
  expect((await page.request.post(`/api/paperagents/${id}/reimplementation/checks`, { data: { ask: true, max_cost: 1 } })).status()).toBe(409);
  expect((await page.request.delete(`/api/paperagents/${id}/reimplementation/checks`)).status()).toBe(409);
  expect((await page.request.delete(`/api/paperagents/${id}/reimplementation`)).status()).toBe(409);

  await stop.click();

  await expect(checking.getByText("Stopped", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(matchingForm(page)).toBeVisible();
  await expect(matchingChecks(page)).toHaveAttribute("data-tier", "none");
  await expect(page.getByTestId("matching-how")).toContainText("It was stopped before it came to its end.");
  await expect(page.getByTestId("matching-label")).toContainText("It is given to no conversation until it gives a number that the paper reports.");
  await expect(keptFunction(page)).toHaveAttribute("data-status", "written");
  await expect(givenSummary(page)).toContainText("Tier D: reads the paper");
  expect((await reimplementationOf(page, id)).checks).toMatchObject({ job: null, tier: null, kept: { status: "stopped" } });
  await expect(page.getByRole("button", { name: `Delete ${title}` })).toBeEnabled();
  expect(await accessibilityProblems(page)).toEqual([]);
});

const problem = (page: Page) => page.getByTestId("reimplementation-problem");

test("says why a function cannot be written from the paper of an agent: it was not read, it reports no number, or it has the authors' code", async ({ page }) => {
  test.setTimeout(120_000);

  // A paper that is not there to be read
  const apart = await makeAgent(page, { title: "Paper apart", paper: { kind: "doi", doi: "10.1000/apart" } });
  await openAgent(page, apart, "Paper apart");
  await expect(reimplementation(page)).toBeVisible();
  await expect(page.getByTestId("reimplementation")).toHaveAttribute("data-ready", "false");
  await expect(problem(page)).toHaveText("Read the paper first, as it is its words that the function is written from.");
  await expect(writingForm(page)).toHaveCount(0);
  await expect(matchingForm(page)).toHaveCount(0);
  await expect(page.getByTestId("reimplementation-meaning")).toContainText("A tool of tier C is a re-implementation");
  expect((await reimplementationOf(page, apart)).problem).toMatchObject({ code: "no_text" });
  expect(await accessibilityProblems(page)).toEqual([]);

  // A paper that reports nothing that a function could be checked against
  const bare = await makeAgent(page, { title: "Paper with no numbers", paper: { kind: "file" } });
  await sendPaper(page, bare, "bare.txt", ["Paper with no numbers", "Methods", "We add the numbers one to another and double the sum.", "References", "A. One."].join("\n\n"));
  await readTheAgent(page, bare);
  await openAgent(page, bare, "Paper with no numbers");
  await expect(page.getByTestId("reimplementation")).toHaveAttribute("data-ready", "false");
  await expect(problem(page)).toContainText("The paper reports no number with digits enough to be told from one by chance");
  await expect(writingForm(page)).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  // An agent that has the authors' code is of that code, and says so, and nothing is offered
  const coded = await agentWithTools(page, "Agent with code");
  await sendPaper(page, coded, "coded.txt", claimsPaper("Agent with code"));
  await readTheAgent(page, coded);
  await openAgent(page, coded, "Agent with code");
  await expect(page.getByTestId("reimplementation")).toHaveAttribute("data-ready", "false");
  await expect(problem(page)).toContainText("This agent has tools that run the authors' own code, which is the method as they ran it.");
  await expect(page.getByTestId("reimplementation")).toContainText("A function written from the paper is only for a paper with no code.");
  await expect(writingForm(page)).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  // What was written is kept and is still shown, with the reason that it cannot be written again
  const written = await agentWithSums(page, "Written then coded");
  await writeThrough(page, written);
  await openAgent(page, written, "Written then coded");
  await page.route("**/api/paperagents/*/reimplementation", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();
    const body = await response.json();

    return route.fulfill({
      response,
      json: { ...body, ready: false, problem: { code: "has_tools", message: "This agent has tools that run the authors' own code, which is the method as they ran it" } },
    });
  });
  await page.reload();
  await expect(problem(page)).toContainText("This agent has tools that run the authors' own code");
  await expect(keptFunction(page)).toHaveAttribute("data-status", "written");
  await expect(writingForm(page)).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);
  await page.unroute("**/api/paperagents/*/reimplementation");

  // An agent that was imported is of the server that it came from
  await page.route("**/api/paperagents/*/reimplementation", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();
    const body = await response.json();

    return route.fulfill({
      response,
      json: { ...body, ready: false, kept: null, problem: { code: "imported", message: "This agent was imported, and what it can do is what the server that it came from does" } },
    });
  });
  await page.reload();
  await expect(problem(page)).toHaveText("This agent was imported, and what it can do is what the server that it came from does.");
  await expect(keptFunction(page)).toHaveCount(0);
  await expect(writingForm(page)).toHaveCount(0);
  await page.unroute("**/api/paperagents/*/reimplementation");
});

test("shows what would be sent again when it is not what was shown, says why the server refused to write or to check, and looks again when what the page shows is out of date", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const id = await agentWithSums(page, "Refused function");
  await openAgent(page, id, "Refused function");
  const { offer } = await reimplementationOf(page, id);
  const refuse = (code: string, message: string, status = 422, more: Record<string, unknown> = {}) => (route: Route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ error: { code, message, ...more } }) })
      : route.fallback();

  // What would be sent is not what was shown: what it is is shown in its place, and is to be read and agreed to again
  await page.route("**/api/paperagents/*/reimplementation", refuse("changed", "What would be sent is not what you were shown", 409, { offer: { ...offer, brief: `${offer.brief}\n\nA sentence that was added.`, key: "another-key" } }));
  await agreeBox(page).check();
  await writingForm(page).getByLabel("Most it may spend, in dollars").fill("1");
  await writingForm(page).getByRole("button", { name: /^Agree, and write/ }).click();
  await expect(writingForm(page).getByRole("alert")).toContainText("What would be sent is not what you were shown");
  await expect(page.getByTestId("reimplementation-offer").getByRole("region", { name: "What the model would be given" })).toContainText("A sentence that was added.");
  await expect(agreeBox(page)).not.toBeChecked();
  await expect(writingForm(page).getByRole("button", { name: /^Agree, and write/ })).toBeDisabled();
  await page.unroute("**/api/paperagents/*/reimplementation");
  expect((await reimplementationOf(page, id)).kept).toBeNull();

  // The server's own reasons are said as they are
  await page.reload();
  await page.route("**/api/paperagents/*/reimplementation", refuse("docker_missing", "Docker is not installed on this machine, and a function is imported in a container."));
  await agreeBox(page).check();
  await writingForm(page).getByLabel("Most it may spend, in dollars").fill("1");
  await writingForm(page).getByRole("button", { name: /^Agree, and write/ }).click();
  await expect(writingForm(page).getByRole("alert")).toContainText("Docker is not installed on this machine");
  await page.unroute("**/api/paperagents/*/reimplementation");

  // Reading that is not what it was, or tools that are made since the page looked, are not a reason to refuse: the page looks again
  let looked = 0;
  await page.route("**/api/paperagents/*/reimplementation", (route) => {
    if (route.request().method() === "GET") looked += 1;

    return route.request().method() === "POST" ? refuse("has_tools", "This agent has tools that run the authors' own code")(route) : route.fallback();
  });
  await page.reload();
  const before = looked;
  await agreeBox(page).check();
  await writingForm(page).getByLabel("Most it may spend, in dollars").fill("1");
  await writingForm(page).getByRole("button", { name: /^Agree, and write/ }).click();
  await expect.poll(() => looked).toBeGreaterThan(before);
  await expect(writingForm(page).getByRole("alert")).toHaveCount(0);
  await page.unroute("**/api/paperagents/*/reimplementation");

  // The same is said of checking, for a function that is no more, and the server's reasons are said as they are
  await writeThrough(page, id);
  await openAgent(page, id, "Refused function");
  await page.route("**/api/paperagents/*/reimplementation/checks", refuse("docker_missing", "Docker is not installed on this machine, and a function is called in a container."));
  await matchingForm(page).getByLabel("Most it may spend, in dollars").fill("1");
  await matchingForm(page).getByRole("button", { name: "Check it against the paper" }).click();
  await expect(matchingForm(page).getByRole("alert")).toContainText("Docker is not installed on this machine");
  await page.unroute("**/api/paperagents/*/reimplementation/checks");

  let seen = 0;
  await page.route("**/api/paperagents/*/reimplementation", (route) => {
    if (route.request().method() === "GET") seen += 1;

    return route.fallback();
  });
  await page.route("**/api/paperagents/*/reimplementation/checks", refuse("no_function", "There is no function written from the paper to check"));
  const after = seen;
  await matchingForm(page).getByRole("button", { name: "Check it against the paper" }).click();
  await expect.poll(() => seen).toBeGreaterThan(after);
  await expect(matchingForm(page).getByRole("alert")).toHaveCount(0);
  await page.unroute("**/api/paperagents/*/reimplementation/checks");
  await page.unroute("**/api/paperagents/*/reimplementation");
  expect((await reimplementationOf(page, id)).kept).toMatchObject({ status: "written" });
  expect(await accessibilityProblems(page)).toEqual([]);
});

// Making an agent in one go, which does each step as its own section would, one after another, and stops where the person is
// to say something
const oneGo = (page: Page) => form(page, "Make it in one go");
const goingOn = (page: Page) => page.getByRole("region", { name: "Making it in one go" });
const decision = (page: Page) => page.getByTestId("onego-decision");
const onegoSteps = (page: Page) => page.getByRole("list", { name: "Steps of making it in one go" }).getByTestId("onego-step");
const onegoStep = (page: Page, title: string) => onegoSteps(page).filter({ hasText: title });
const onegoOf = async (page: Page, id: string) => (await page.request.get(`/api/paperagents/${id}/make`)).json();
const START = "Make it all now";
const EVERY_STEP = "Every step is done. It is given to the conversations you start from now on.";

test("makes an agent in one go, from its paper to the conversations, asking where its code is with the projects the paper points to", async ({
  page,
}) => {
  const id = await makeAgent(page, { title: "Whole mapper", paper: { kind: "file" } });
  await sendPaper(page, id, "cells.txt", CELLS);
  await openAgent(page, id, "Whole mapper");
  await expect(page.getByRole("heading", { name: "In one go", level: 2 })).toBeVisible();
  await expect(oneGo(page)).toContainText("Only reading the paper costs money");

  // What is asked for is said before it is sent
  await oneGo(page).getByLabel("Most reading may spend, in dollars").fill("");
  await oneGo(page).getByLabel("Where the code is").fill("https://example.org/owner/name");
  await oneGo(page).getByRole("button", { name: START }).click();
  await expect(oneGo(page).getByText("Say the most reading the paper may spend.")).toBeVisible();
  await expect(oneGo(page).getByText(/Give the address of the project/)).toBeVisible();
  expect((await onegoOf(page, id)).state).toBe("none");
  expect(await accessibilityProblems(page)).toEqual([]);

  await oneGo(page).getByLabel("Where the code is").fill("");
  await oneGo(page).getByLabel("Most reading may spend, in dollars").fill("2");
  await oneGo(page).getByRole("button", { name: START }).click();

  // Nobody said where the code is, so the paper is read first, and then it asks, with the projects that the paper points to,
  // none of which is taken for the code
  await expect(decision(page)).toContainText("The paper points to the projects below", { timeout: 20_000 });
  await expect(onegoStep(page, "Read the paper")).toHaveAttribute("data-state", "done");
  await expect(onegoStep(page, "Fetch the code")).toHaveAttribute("data-state", "waiting");
  await expect(onegoSteps(page).first()).toContainText("Read the paper");
  await expect(page.getByText("Waiting for you", { exact: true }).first()).toBeVisible();
  const candidate = decision(page).getByTestId("onego-candidate");
  await expect(candidate).toHaveCount(1);
  await expect(candidate).toContainText("The paper says it is the code");
  await expect(candidate.getByRole("blockquote")).toContainText(CODE);
  expect((await (await page.request.get(`/api/paperagents/${id}`)).json()).repo).toBeNull();
  await expect(step(page, "Read the paper")).toContainText("Done");
  expect(await accessibilityProblems(page)).toEqual([]);

  // What the server refuses is said where it was asked
  await page.route("**/api/paperagents/*/make", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "busy", message: "Fetching the code is already running" } }),
        })
      : route.fallback(),
  );
  await candidate.getByRole("button", { name: "Use as the code and go on: example/cellmapper" }).click();
  await expect(decision(page).getByRole("alert")).toContainText("Fetching the code is already running");
  await page.unroute("**/api/paperagents/*/make");

  await candidate.getByRole("button", { name: "Use as the code and go on: example/cellmapper" }).click();

  // Every step is gone through, each the step of its own section, and the agent is given to conversations
  await expect(decision(page)).toContainText(EVERY_STEP, { timeout: 60_000 });
  await expect(onegoSteps(page)).toHaveCount(8);
  for (const each of await onegoSteps(page).all()) await expect(each).toHaveAttribute("data-state", "done");
  await expect(onegoStep(page, "Give it to your conversations")).toContainText("Given to the conversations that you start from now on.");
  const agent = await (await page.request.get(`/api/paperagents/${id}`)).json();
  expect(agent).toMatchObject({ repo: { url: CODE_ADDRESS }, given: true, steps: { reading: "done", repository: "done", environment: "done", tools: "done" } });
  await expect(step(page, "Build the tools")).toContainText("Done");
  await expect(page.getByTestId("code-commit")).toContainText("example/cellmapper at ");
  expect(await accessibilityProblems(page)).toEqual([]);

  // How it went is kept, and is cleared for it to be asked for afresh, with nothing to spend now that the paper is read
  await page.reload();
  await expect(decision(page)).toContainText(EVERY_STEP);
  await page.getByRole("button", { name: "Clear this and start afresh" }).click();
  await expect(oneGo(page)).toBeVisible();
  await expect(oneGo(page).getByLabel("Most reading may spend, in dollars")).toHaveCount(0);
  await expect(oneGo(page).getByLabel("Where the code is")).toHaveCount(0);
  await expect(oneGo(page)).toContainText("nothing it does costs money");
  expect((await onegoOf(page, id)).state).toBe("none");
});

test("follows making it in one go while it goes on, which nothing else is done to the agent meanwhile, stops it, and goes on from where it stopped", async ({
  page,
}) => {
  const id = await makeAgent(page, { title: "Slow whole mapper", paper: { kind: "file" }, repo: CODE_ADDRESS });
  await sendPaper(page, id, "cells.txt", CELLS);
  await readTheAgent(page, id);
  await openAgent(page, id, "Slow whole mapper");
  // The paper has been read and the code is where the agent says, so neither is asked
  await expect(oneGo(page).getByLabel("Most reading may spend, in dollars")).toHaveCount(0);
  await expect(oneGo(page).getByLabel("Where the code is")).toHaveCount(0);
  await oneGo(page).getByLabel("Give it to my conversations once it is made").uncheck();
  await oneGo(page).getByRole("button", { name: START }).click();

  await expect(onegoStep(page, "Build the environment")).toHaveAttribute("data-state", "running", { timeout: 20_000 });
  await expect(goingOn(page).getByRole("progressbar")).toBeVisible();
  await expect(goingOn(page)).toContainText(/\d of 8 steps/);
  await expect(onegoStep(page, "Fetch the code")).toHaveAttribute("data-state", "done");
  await expect(onegoStep(page, "Read the paper")).toContainText("The paper had been read.");
  await expect(building(page)).toBeVisible();
  // Nothing else is done to the agent while it is made
  await expect(page.getByRole("button", { name: "Delete Slow whole mapper" })).toBeDisabled();
  await expect(reading(page)).toContainText("The agent is being made in one go. Reading waits for that.");
  expect(await accessibilityProblems(page)).toEqual([]);

  await goingOn(page).getByRole("button", { name: /^Stop: / }).click();

  await expect(decision(page)).toContainText("Stopped. What was made is kept", { timeout: 20_000 });
  await expect(onegoStep(page, "Build the environment")).toHaveAttribute("data-state", "stopped");
  await expect(goingOn(page)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Delete Slow whole mapper" })).toBeEnabled();
  expect((await onegoOf(page, id))).toMatchObject({ state: "stopped", stuck: { step: "environment", kind: "stopped" } });
  // Leaving out the code is not offered for what the person stopped
  await expect(decision(page).getByRole("button", { name: "Go on without the code" })).toHaveCount(0);

  await decision(page).getByRole("button", { name: "Go on", exact: true }).click();

  // It is not given, as that was asked, and the steps that were done are not done again
  await expect(decision(page)).toContainText("Every step is done.", { timeout: 90_000 });
  await expect(decision(page)).not.toContainText("It is given");
  await expect(onegoStep(page, "Fetch the code")).toContainText("The code had been fetched.");
  await expect(onegoStep(page, "Give it to your conversations")).toHaveAttribute("data-state", "skipped");
  expect((await (await page.request.get(`/api/paperagents/${id}`)).json()).given).toBe(false);
});

test("makes an agent of a DOI all in one go from the form that makes it, and goes on without the code when the person says to", async ({ page }) => {
  await page.goto("/papers");
  const making = form(page, "Make an agent");
  await making.getByLabel("DOI", { exact: true }).fill("10.1234/one.go");
  // A file is uploaded on the agent's page, so it is made in one go there
  await making.getByRole("radio", { name: "A file I upload" }).check();
  await expect(making.getByLabel("Make all of it now, in one go")).toHaveCount(0);
  await making.getByRole("radio", { name: "A DOI" }).check();
  await making.getByLabel("Make all of it now, in one go").check();
  await making.getByLabel("Most reading the paper may spend, in dollars").fill("lots");
  await making.getByRole("button", { name: "Make the agent, all in one go" }).click();
  await expect(making.getByText(/is an amount in dollars/)).toBeVisible();
  expect((await (await page.request.get("/api/paperagents")).json()).agents).toEqual([]);
  expect(await accessibilityProblems(page)).toEqual([]);

  await making.getByLabel("Most reading the paper may spend, in dollars").fill("2");
  await making.getByRole("button", { name: "Make the agent, all in one go" }).click();

  await expect(page.getByRole("heading", { name: "10.1234/one.go", level: 2 })).toBeVisible();
  const id = agentIn(page);
  // The paper is fetched and read, and then it asks where the code is
  await expect(decision(page)).toContainText("The paper points to the projects below", { timeout: 30_000 });
  await decision(page).getByRole("button", { name: "Go on without the code" }).click();

  await expect(decision(page)).toContainText("Made as far as the code allows. You chose to go on without the code.", { timeout: 30_000 });
  for (const title of ["Fetch the code", "Look at the code against the paper", "Build the environment", "Run the tutorials", "Make the tools", "Check the tools"]) {
    await expect(onegoStep(page, title)).toHaveAttribute("data-state", "skipped");
  }
  await expect(onegoStep(page, "Give it to your conversations")).toHaveAttribute("data-state", "done");
  expect((await (await page.request.get(`/api/paperagents/${id}`)).json())).toMatchObject({ repo: null, given: true });
  expect((await onegoOf(page, id)).settings).toMatchObject({ max_cost: 2, without_code: true });
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("asks for the paper's file when its text cannot be had, and for more to spend when reading reaches its limit, and for the code without a project to choose from", async ({
  page,
}) => {
  const id = await makeAgent(page, { title: "Closed whole paper", paper: { kind: "doi", doi: "10.1234/closed.one" } });
  await openAgent(page, id, "Closed whole paper");
  await oneGo(page).getByLabel("Most reading may spend, in dollars").fill("0.0004");
  await oneGo(page).getByRole("button", { name: START }).click();

  // The text could not be fetched, so the paper's file is asked for, which it cannot go on without
  await expect(decision(page)).toContainText("The text of the paper could not be had", { timeout: 20_000 });
  await expect(decision(page)).toContainText("Upload the paper's file under Paper file, below, and then go on.");
  await expect(decision(page).getByRole("button", { name: "Go on", exact: true })).toBeDisabled();
  await expect(onegoStep(page, "Read the paper")).toHaveAttribute("data-state", "waiting");
  await expect(decision(page).getByRole("button", { name: "Go on without the code" })).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  await sendPaper(page, id, "closed.txt", chunked(3, "plain:"));
  await page.reload();
  await expect(decision(page)).toContainText("The paper's file is uploaded, so it can go on.");
  await decision(page).getByRole("button", { name: "Go on", exact: true }).click();

  // Reading stops at the limit it was given, and asks for more, which it carries on with from where it stopped
  await expect(decision(page)).toContainText("Reading reached the limit on spending", { timeout: 20_000 });
  await expect(decision(page)).toContainText("of the <$0.01 it was given.");
  const more = form(page, "Say how much more reading may spend");
  await more.getByLabel("How much more it may spend, in dollars").fill("");
  await more.getByRole("button", { name: "Go on reading" }).click();
  await expect(more.getByText("Say how much more reading may spend.")).toBeVisible();
  expect((await onegoOf(page, id)).state).toBe("waiting");
  await more.getByLabel("How much more it may spend, in dollars").fill("2");
  await more.getByRole("button", { name: "Go on reading" }).click();

  // The paper points to no code, so where it is is asked with nothing to choose from, and what is typed is checked first
  await expect(decision(page)).toContainText("the paper does not point to any", { timeout: 20_000 });
  await expect(decision(page).getByTestId("onego-candidate")).toHaveCount(0);
  await expect(summary(page)).toContainText("Read 3 of 3 chunks");
  const where = form(page, "Say where the code is");
  await where.getByRole("button", { name: "Go on with it" }).click();
  await expect(where.getByText("Give the address of the code.")).toBeVisible();
  await where.getByLabel("Where the code is").fill("https://example.org/owner/name");
  await where.getByRole("button", { name: "Go on with it" }).click();
  await expect(where.getByText(/Give the address of the project/)).toBeVisible();
  expect((await onegoOf(page, id)).state).toBe("waiting");
  expect(await accessibilityProblems(page)).toEqual([]);

  await decision(page).getByRole("button", { name: "Go on without the code" }).click();
  await expect(decision(page)).toContainText("Made as far as the code allows.", { timeout: 20_000 });
});

test("asks whether to go on with code that looking at it says not to, before the paper is paid to be read, and skips what the code cannot do", async ({
  page,
}) => {
  const id = await makeAgent(page, { title: "Gpu whole mapper", paper: { kind: "file" }, repo: "https://github.com/example/gpu-mapper" });
  await sendPaper(page, id, "cells.txt", CELLS);
  await openAgent(page, id, "Gpu whole mapper");
  await oneGo(page).getByRole("button", { name: START }).click();

  // The code is fetched and looked at first, and what stops it is said before anything is spent on reading
  await expect(decision(page)).toContainText("Go on if you accept that, or go on without the code.", { timeout: 20_000 });
  await expect(decision(page)).toContainText("Do not go on");
  await expect(decision(page)).toContainText("Stops it");
  await expect(decision(page)).toContainText("Of commit ");
  await expect(onegoStep(page, "Look at the code against the paper")).toHaveAttribute("data-state", "waiting");
  await expect(onegoStep(page, "Read the paper")).toHaveAttribute("data-state", "pending");
  expect((await (await page.request.get(`/api/paperagents/${id}/reading`)).json()).chunks).toBeNull();
  expect(await accessibilityProblems(page)).toEqual([]);

  await decision(page).getByRole("button", { name: "Go on with this code anyway" }).click();

  // It reads the paper, builds what it can, and skips what the code cannot be made into
  await expect(decision(page)).toContainText("Made as far as the code allows.", { timeout: 60_000 });
  await expect(onegoStep(page, "Look at the code against the paper")).toContainText("You said to go on.");
  await expect(onegoStep(page, "Make the tools")).toHaveAttribute("data-state", "skipped");
  await expect(onegoStep(page, "Check the tools")).toHaveAttribute("data-state", "skipped");
  await expect(onegoStep(page, "Give it to your conversations")).toHaveAttribute("data-state", "done");
  expect((await onegoOf(page, id)).settings.go_on).toMatch(/^[0-9a-f]{40}$/);
});

test("says that the agent was made when making it in one go is refused, and starts making that agent when asked again", async ({ page }) => {
  await page.route("**/api/paperagents/*/make", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "invalid", message: "Something about it was refused" } }),
        })
      : route.fallback(),
  );
  await page.goto("/papers");
  const making = form(page, "Make an agent");
  await making.getByLabel("DOI", { exact: true }).fill("10.1234/refused.go");
  await making.getByLabel("Make all of it now, in one go").check();
  await making.getByRole("button", { name: "Make the agent, all in one go" }).click();

  await expect(making).toContainText("The agent was made, but making all of it in one go could not be started.");
  await expect(making.getByRole("alert")).toContainText("Something about it was refused");
  const { agents } = await (await page.request.get("/api/paperagents")).json();
  expect(agents).toHaveLength(1);
  await expect(making.getByRole("link", { name: "Open the agent, to go on there" })).toHaveAttribute("href", `/papers?agent=${agents[0].id}`);
  expect(await accessibilityProblems(page)).toEqual([]);

  // Asked again, the same paper is not made again: making the agent that was made is started
  await page.unroute("**/api/paperagents/*/make");
  await making.getByRole("button", { name: "Make the agent, all in one go" }).click();
  await expect(page.getByRole("heading", { name: "10.1234/refused.go", level: 2 })).toBeVisible();
  expect(agentIn(page)).toBe(agents[0].id);
  expect((await (await page.request.get("/api/paperagents")).json()).agents).toHaveLength(1);
  await expect.poll(async () => (await onegoOf(page, agents[0].id)).state).not.toBe("none");
});
