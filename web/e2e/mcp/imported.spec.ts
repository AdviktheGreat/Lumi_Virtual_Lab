import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { expect, test } from "../fixtures";
import { HttpServer } from "./state";

// An agent that someone else made is brought in from the server that hosts it, which here is the test server of the MCP library's own
// tests, started as a program and reached over HTTP as Paper2Agent's are over the web. The agents are the workspace's of this server,
// which no other file of this project makes, and each test takes away what it made. None is given to conversations, since the
// conversations of the other files are made beside these, so what a conversation does with one is the tests of the server's.
test.describe.configure({ mode: "serial" });

const PAPER = "10.1000/cellmapper";
const form = (page: Page, name: string) => page.getByRole("form", { name });

async function clear(page: Page) {
  const { agents } = await (await page.request.get("/api/paperagents")).json();
  for (const agent of agents) {
    await expect.poll(async () => (await page.request.delete(`/api/paperagents/${agent.id}`)).status(), { timeout: 20_000 }).toBe(200);
  }
}

let hosted: HttpServer;

test.beforeAll(async () => {
  hosted = await HttpServer.started();
});

test.afterAll(() => {
  hosted.stop();
});

test.beforeEach(async ({ page }) => {
  await clear(page);
});

test.afterEach(async ({ page }) => {
  await clear(page);
});

// Imports the server through the API, so that what a test is about is the page, and gives back the id of the agent
async function imported(page: Page, title = "Cell Mapper", url = hosted.url): Promise<string> {
  const made = await page.request.post("/api/paperagents/import", { data: { url, title, paper: { kind: "doi", doi: PAPER } } });
  expect(made.status(), await made.text()).toBe(201);

  return (await made.json()).id;
}

async function openAgent(page: Page, id: string, title: string) {
  await page.goto(`/papers?agent=${id}`);
  await expect(page.getByRole("heading", { name: title, level: 2 })).toBeVisible();
}

test("imports the server of an agent from its address and the paper it is of, which is shown as imported and not checked", async ({ page }) => {
  await page.goto("/papers");
  const importing = form(page, "Import an agent");

  // What is wrong is said by the field, and nothing is sent
  await importing.getByRole("button", { name: "Import the agent" }).click();
  await expect(importing.getByText("Give the address of the server.")).toBeVisible();
  await expect(importing.getByText("Give a DOI, such as 10.1038/s41586-020-2649-2.")).toBeVisible();
  expect((await (await page.request.get("/api/paperagents")).json()).agents).toEqual([]);

  await importing.getByLabel("Address of the server").fill(hosted.url);
  await importing.getByLabel("DOI", { exact: true }).fill(PAPER);
  await importing.getByLabel("Title").fill("Cell Mapper");
  await importing.getByRole("button", { name: "Import the agent" }).click();

  await expect(page).toHaveURL(/\/papers\?agent=cell-mapper$/);
  await expect(page.getByRole("heading", { name: "Cell Mapper", level: 2 })).toBeVisible();
  const badges = page.getByTestId("imported-badges");
  await expect(badges).toContainText("Imported");
  await expect(badges).toContainText("Not checked here");

  const section = page.getByTestId("imported");
  await expect(section).toContainText("Tier Imported");
  await expect(section).toContainText("Made by someone else");
  await expect(section.getByTestId("imported-meaning")).toContainText("nothing of Lumi's has been done to it");
  await expect(section).toContainText(`Runs on 127.0.0.1:${hosted.port}, a machine that is not this one and is not run by Lumi.`);
  await expect(section).toContainText(hosted.url);
  const echo = section.getByTestId("imported-tool").and(page.locator('[data-name="echo"]'));
  await expect(echo).toContainText("echo(text, times)");
  await expect(echo).toContainText("Says the text back.");
  expect(await accessibilityProblems(page)).toEqual([]);

  // The agent is listed, and says that it was imported
  await page.getByRole("link", { name: "All agents" }).click();
  await expect(page.getByTestId("paper-agent")).toContainText("Cell Mapper");
  await expect(page.getByTestId("paper-agent")).toContainText("Imported, not checked here");
});

test("shows what a conversation would be given of an imported agent, as imported tools that were not checked", async ({ page }) => {
  const id = await imported(page);
  await openAgent(page, id, "Cell Mapper");

  const summary = page.getByTestId("given-summary");
  await expect(summary).toContainText("Tier Imported: made by someone else, and not checked here");
  await expect(summary).toContainText("tools that call the server it was imported from");
  const tools = page.getByTestId("given-tool").and(page.locator('[data-kind="imported"]'));
  await expect(tools.and(page.locator('[data-name="cell_mapper_echo"]'))).toContainText("Tier Imported");
  await expect(tools.and(page.locator('[data-name="cell_mapper_echo"]'))).toContainText("Calls the server that someone else runs, and asks you first");
  await expect(page.getByTestId("given-imported")).toContainText("nothing of Lumi's has been done to it");
  // Nothing that reads the paper or runs its code is offered, since nothing was done to make them
  await expect(page.getByTestId("given-tool").and(page.locator('[data-kind="reading"], [data-kind="run"]'))).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("refuses an address with a variable in it, or a key, before it is sent", async ({ page }) => {
  await page.goto("/papers");
  const importing = form(page, "Import an agent");
  await importing.getByLabel("DOI", { exact: true }).fill(PAPER);

  await importing.getByLabel("Address of the server").fill("https://example.org/${SECRET}/mcp");
  await importing.getByRole("button", { name: "Import the agent" }).click();
  await expect(importing.getByText(/no \$, \{, or \} in it/)).toBeVisible();

  await importing.getByLabel("Address of the server").fill("https://example.org/mcp?key=secret");
  await expect(importing.getByText(/where keys are kept/)).toBeVisible();
  expect((await (await page.request.get("/api/paperagents")).json()).agents).toEqual([]);

  // The server holds the same to what is sent without the page
  const sent = await page.request.post("/api/paperagents/import", {
    data: { url: "https://example.org/${HOME}/mcp", paper: { kind: "doi", doi: PAPER } },
  });
  expect(sent.status()).toBe(422);
});

test("says that a server cannot be connected to, and makes no agent of it", async ({ page }) => {
  const away = await HttpServer.chosen();
  await page.goto("/papers");
  const importing = form(page, "Import an agent");
  await importing.getByLabel("Address of the server").fill(away.url);
  await importing.getByLabel("DOI", { exact: true }).fill(PAPER);

  await importing.getByRole("button", { name: "Import the agent" }).click();

  await expect(importing.getByRole("alert")).toContainText("could not be connected to");
  await expect(page).toHaveURL(/\/papers$/);
  expect((await (await page.request.get("/api/paperagents")).json()).agents).toEqual([]);
});

test("does not import a server twice, and leads to the agent that has it", async ({ page }) => {
  const first = await imported(page, "First");
  await page.goto("/papers");
  const importing = form(page, "Import an agent");
  await importing.getByLabel("Address of the server").fill(hosted.url);
  await importing.getByLabel("DOI", { exact: true }).fill("10.1000/other");

  await importing.getByRole("button", { name: "Import the agent" }).click();

  await expect(importing.getByRole("alert")).toContainText("was imported already");
  await importing.getByRole("link", { name: "Open that PaperAgent" }).click();
  await expect(page).toHaveURL(new RegExp(`/papers\\?agent=${first}$`));
});

test("connects to the server again, says if it cannot be, and keeps what it had listed", async ({ page }) => {
  const own = await HttpServer.started();
  try {
    const id = await imported(page, "Cell Mapper", own.url);
    await openAgent(page, id, "Cell Mapper");
    const section = page.getByTestId("imported");
    const tools = section.getByTestId("imported-tool");
    const listed = await tools.count();
    expect(listed).toBeGreaterThan(0);

    own.stop();
    await section.getByRole("button", { name: "Connect again" }).click();
    await expect(section.getByRole("alert")).toContainText("could not be connected to");
    await expect(section.getByTestId("imported-failure")).toContainText("could not be connected to");
    await expect(section).toContainText("What was kept of the server is as it was.");
    await expect(tools).toHaveCount(listed);

    await own.start();
    await section.getByRole("button", { name: "Connect again" }).click();
    await expect(section.getByTestId("imported-failure")).toHaveCount(0);
    await expect(section.getByTestId("imported-done")).toContainText("Connected again. It listed");
    await expect(tools).toHaveCount(listed);
    expect(await accessibilityProblems(page)).toEqual([]);
  } finally {
    own.stop();
  }
});

test("takes the server away, after asking, and leaves the agent of the paper", async ({ page }) => {
  const id = await imported(page);
  await openAgent(page, id, "Cell Mapper");

  await page.getByRole("button", { name: "Remove the server" }).click();
  const asking = page.getByRole("alertdialog");
  await expect(asking).toContainText("Remove the server of Cell Mapper?");
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(page.getByTestId("imported")).toBeVisible();

  await page.getByRole("button", { name: "Remove the server" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Remove", exact: true }).click();

  await expect(page.getByTestId("imported")).toHaveCount(0);
  await expect(page.getByTestId("imported-badges")).toHaveCount(0);
  await expect(form(page, "Import a server for this agent")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Cell Mapper", level: 2 })).toBeVisible();
  const kept = await (await page.request.get(`/api/paperagents/${id}`)).json();
  expect(kept.imported).toBeNull();
  expect((await (await page.request.get(`/api/paperagents/${id}/given`)).json()).tier).toBeNull();
});

test("adds a server to an agent that was made here, and the rest of it is left as it was", async ({ page }) => {
  const made = await page.request.post("/api/paperagents", {
    data: { title: "Mine", paper: { kind: "doi", doi: PAPER }, repo: "https://github.com/lab/cellmapper" },
  });
  const id: string = (await made.json()).id;
  await openAgent(page, id, "Mine");
  await expect(page.getByTestId("imported-badges")).toHaveCount(0);
  const adding = form(page, "Import a server for this agent");

  await adding.getByRole("button", { name: "Import the server" }).click();
  await expect(adding.getByText("Give the address of the server.")).toBeVisible();
  await adding.getByLabel("Address of the server").fill(hosted.url);
  await adding.getByRole("button", { name: "Import the server" }).click();

  await expect(page.getByTestId("imported")).toContainText("Tier Imported");
  await expect(page.getByTestId("imported-badges")).toContainText("Imported");
  await expect(page.getByRole("heading", { name: "Mine", level: 2 })).toBeVisible();
  const kept = await (await page.request.get(`/api/paperagents/${id}`)).json();
  expect(kept.imported.url).toBe(hosted.url);
  expect(kept.repo).toEqual({ url: "https://github.com/lab/cellmapper" });
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("lists the servers that Paper2Agent hosts, says whose they are and where they run, and asks before it connects", async ({ page }) => {
  await page.goto("/papers");
  const listed = page.getByRole("list", { name: "Agents that others host" }).getByTestId("importable");
  await expect(listed).toHaveCount(3);
  expect(await listed.evaluateAll((items) => items.map((item) => item.getAttribute("data-key")))).toEqual(["scanpy", "tissue", "alphagenome"]);

  const scanpy = listed.and(page.locator('[data-key="scanpy"]'));
  await expect(scanpy).toHaveAttribute("data-state", "new");
  await expect(scanpy).toContainText("Made by Paper2Agent");
  await expect(scanpy.getByTestId("importable-hosted")).toContainText("a Space on Hugging Face, which is not run by Lumi");
  await expect(scanpy.getByTestId("importable-hosted")).toContainText("each call asks you first");
  await expect(scanpy).toContainText("does not upload files to it");
  await expect(scanpy.getByRole("link", { name: "Its paper" })).toHaveAttribute("href", "https://doi.org/10.1186/s13059-017-1382-0");
  await expect(scanpy.getByRole("link", { name: "Its code" })).toHaveAttribute("href", "https://github.com/scverse/scanpy");
  await expect(listed.and(page.locator('[data-key="alphagenome"]'))).toContainText("AlphaGenome API key as an argument");
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("asks for the server that is listed as the agent of its paper, and as the server of an agent that there is", async ({ page }) => {
  const requests: Record<string, unknown>[] = [];
  // The hosts are on the web, which the tests do not reach: what is sent is what is looked at, and the agent that is answered with is a real one
  const real = await imported(page, "Stand-in");
  const agent = await (await page.request.get(`/api/paperagents/${real}`)).json();
  await page.route("**/api/paperagents/import", async (route) => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(agent) });
  });
  await page.goto("/papers");
  const scanpy = page.getByTestId("importable").and(page.locator('[data-key="scanpy"]'));

  await scanpy.getByRole("button", { name: "Import Scanpy" }).click();
  await expect(page).toHaveURL(new RegExp(`/papers\\?agent=${real}$`));
  expect(requests).toEqual([
    {
      url: "https://Paper2Agent-scanpy-mcp.hf.space/mcp",
      title: "Scanpy",
      paper: { kind: "doi", doi: "10.1186/s13059-017-1382-0" },
      repo: "https://github.com/scverse/scanpy",
    },
  ]);

  // An agent of its paper that there is already is not made again: the server is added to it
  const mine = await page.request.post("/api/paperagents", { data: { title: "My Scanpy", paper: { kind: "doi", doi: "10.1186/s13059-017-1382-0" } } });
  const mineId: string = (await mine.json()).id;
  await page.goto("/papers");
  await expect(scanpy).toHaveAttribute("data-state", "add");
  await expect(scanpy).toContainText("There is a PaperAgent of this paper already, My Scanpy.");
  await scanpy.getByRole("button", { name: "Add the server to My Scanpy" }).click();
  await expect(page).toHaveURL(new RegExp(`/papers\\?agent=${real}$`));
  expect(requests[1]).toEqual({ url: "https://Paper2Agent-scanpy-mcp.hf.space/mcp", agent: mineId });
});

test("shows a server that is listed as imported once an agent has it, with the way to the agent", async ({ page }) => {
  const real = await imported(page, "Scanpy agent");
  // The server that is listed is on the web, which the tests do not reach, so the list says that this agent has it
  await page.route("**/api/paperagents", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();
    const body = await response.json();
    body.importable = body.importable.map((server: { key: string }) => (server.key === "scanpy" ? { ...server, agent: real, paper_agent: real } : server));
    return route.fulfill({ response, json: body });
  });
  await page.goto("/papers");

  const scanpy = page.getByTestId("importable").and(page.locator('[data-key="scanpy"]'));
  await expect(scanpy).toHaveAttribute("data-state", "imported");
  await expect(scanpy.getByTestId("importable-done")).toContainText("Imported as Scanpy agent");
  await expect(scanpy.getByRole("button")).toHaveCount(0);
  await scanpy.getByRole("link", { name: "Scanpy agent" }).click();
  await expect(page).toHaveURL(new RegExp(`/papers\\?agent=${real}$`));
});

test("says on the Tools page where an agent that someone else made is imported, and does not list it with the servers", async ({ page }) => {
  await page.goto("/tools");
  const note = page.getByTestId("tools-agents");
  await expect(note).toContainText("Scanpy, TISSUE, and AlphaGenome");
  await expect(note).toContainText("imported and not checked");
  await note.getByRole("link", { name: "PaperAgents" }).click();
  await expect(page).toHaveURL(/\/papers$/);
});
