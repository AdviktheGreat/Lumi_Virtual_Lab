import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { expect, test } from "../fixtures";

// The graph of how the agents' papers relate, which is made from what is kept of each when it is looked at. The papers are read
// by the scripted model (see scripted_server.py): "GSE" and digits is a dataset, "Seurat v4.3" is software, a number after
// "AUROC of" is a claim, and an address at github.com is a link to code, each with its sentence as its quote
test.describe.configure({ mode: "serial" });

const ALPHA_CODE = "https://github.com/example/graph-alpha";

const ALPHA = [
  "Alpha: mapping cell types across atlases",
  "Abstract",
  "We present Alpha, a method for mapping cell types.",
  "Results",
  "Alpha reached an AUROC of 0.91 on held-out mouse cells.",
  "Methods",
  "The cells of GEO GSE12345 were mapped.",
  "Clusters were found with Seurat v4.3.",
  "Code availability",
  `The code is at ${ALPHA_CODE}.`,
].join("\n\n");

const BETA = [
  "Beta: faster mapping of cell types",
  "Abstract",
  `Beta builds on ${ALPHA_CODE} to map cell types faster.`,
  "Results",
  "Beta reached an AUROC of 0.91 on held-out mouse cells.",
  "Methods",
  "The cells of GEO GSE12345 were mapped again.",
  "Clusters were found with Seurat v4.3.",
].join("\n\n");

async function clear(page: Page) {
  const { jobs } = await (await page.request.get("/api/setup/jobs")).json();
  for (const job of jobs.filter((job: { kind: string; state: string }) => job.kind.startsWith("paperagent") && job.state === "running")) {
    await page.request.post(`/api/setup/jobs/${job.id}/stop`);
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

async function makeAgent(page: Page, title: string, repo: string): Promise<string> {
  const made = await page.request.post("/api/paperagents", { data: { title, paper: { kind: "file" }, repo } });
  expect(made.status()).toBe(201);

  return (await made.json()).id;
}

// Gives an agent its paper and reads it through the server, waiting until that is done
async function readAgent(page: Page, id: string, text: string) {
  const sent = await page.request.post(`/api/paperagents/${id}/paper?name=paper.txt`, {
    data: Buffer.from(text),
    headers: { "Content-Type": "application/octet-stream" },
  });
  expect(sent.status()).toBe(201);
  const started = await page.request.post(`/api/paperagents/${id}/reading`, { data: { max_cost: 2 } });
  expect(started.status()).toBe(202);
  await expect.poll(async () => (await (await page.request.get(`/api/paperagents/${id}/reading`)).json()).job, { timeout: 20_000 }).toBeNull();
  expect((await (await page.request.get(`/api/paperagents/${id}/reading`)).json()).complete).toBe(true);
}

// Three agents: two whose papers were read and say the same things, one of which builds on the other's code, and one that was not
// read whose code is at the same address as the first's, so that the words of the second name it too
async function threeAgents(page: Page) {
  const alpha = await makeAgent(page, "Alpha mapper", ALPHA_CODE);
  const beta = await makeAgent(page, "Beta mapper", "https://github.com/example/graph-beta");
  const gamma = await makeAgent(page, "Gamma fork", `${ALPHA_CODE}.git`);
  await readAgent(page, alpha, ALPHA);
  await readAgent(page, beta, BETA);

  return { alpha, beta, gamma };
}

const form = (page: Page) => page.getByRole("form", { name: "Ask the graph" });
const relations = (page: Page) => page.getByRole("region", { name: "Relations" }).getByTestId("graph-relation");
const papers = (page: Page) => page.getByRole("region", { name: "Papers" }).getByTestId("graph-paper");
const kindsShown = async (page: Page) => (await relations(page).evaluateAll((items) => items.map((item) => item.getAttribute("data-kind")))).sort();

test("says when there is nothing to relate, with no agent and with one", async ({ page }) => {
  await page.goto("/papers?view=graph");
  await expect(page.getByRole("navigation", { name: "PaperAgents" }).getByRole("link", { name: "Graph" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { name: "Graph", level: 2 })).toBeVisible();
  await expect(page.getByTestId("graph-empty")).toContainText("There are no agents yet");

  await makeAgent(page, "Lonely mapper", ALPHA_CODE);
  await page.goto("/papers?view=graph");
  await expect(page.getByTestId("graph-empty")).toContainText("There is one agent");
  await expect(papers(page)).toHaveCount(1);
  await expect(papers(page).first()).toContainText("Not read, so only its code can relate it to the others.");
  // A paper in no relation has nothing to narrow the graph to
  await expect(papers(page).first().getByRole("button")).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("shows how the papers relate, with where each paper says it, and asks it for one paper, one kind, or words", async ({ page }) => {
  const { alpha, beta, gamma } = await threeAgents(page);
  const kept = await (await page.request.get("/api/paperagents/graph")).json();
  const expected = kept.relations.map((each: { kind: string }) => each.kind).sort();
  expect(expected).toEqual(["agrees", "code", "dataset", "refers", "refers", "software"]);

  await page.goto("/papers?view=graph");
  await expect(relations(page)).toHaveCount(6);
  expect(await kindsShown(page)).toEqual(expected);
  await expect(page.getByTestId("graph-shown")).toHaveText("6 relations between 3 papers");
  // Each kind that is shown is in the legend of the picture, with how many of it there are
  const legend = page.getByTestId("graph-legend");
  for (const name of ["Names the other (2)", "Same code (1)", "Same dataset (1)", "Same software (1)", "Claims that agree (1)", "Not read"]) {
    await expect(legend).toContainText(name);
  }
  await expect(page.getByTestId("graph-picture").locator("line")).toHaveCount(6);
  await expect(page.getByTestId("graph-picture").locator("circle")).toHaveCount(3);

  // What is said of each, as the server says it, and where it is found
  // Beta's words name the code of Alpha, which is where Gamma's is too, and Alpha comes first
  const refers = page.locator('[data-testid="graph-relation"][data-kind="refers"]').first();
  await expect(refers).toContainText(kept.relations.find((each: { kind: string }) => each.kind === "refers").summary);
  await refers.getByText("Where it is found").click();
  await expect(refers).toContainText("Beta mapper says it builds on Alpha mapper, by the address of its code.");
  await expect(refers.getByTestId("graph-quote").first()).toContainText(`Beta builds on ${ALPHA_CODE} to map cell types faster.`);
  await expect(refers.getByTestId("graph-quote").first()).toContainText("Beta mapper, ");

  const dataset = page.locator('[data-testid="graph-relation"][data-kind="dataset"]');
  await expect(dataset).toContainText("By the same accession.");
  await dataset.getByText("Where it is found").click();
  await expect(dataset).toContainText("Named as GSE12345");
  await expect(dataset.getByTestId("graph-quote")).toHaveCount(2);
  await expect(dataset.getByTestId("graph-quote").nth(1)).toContainText("The cells of GEO GSE12345 were mapped again.");

  const software = page.locator('[data-testid="graph-relation"][data-kind="software"]');
  await software.getByText("Where it is found").click();
  await expect(software).toContainText("The same version: Alpha mapper says 4.3; Beta mapper says 4.3.");

  const code = page.locator('[data-testid="graph-relation"][data-kind="code"]');
  await code.getByText("Where it is found").click();
  await expect(code).toContainText("github.com/example/graph-alpha, at commits that are not both known: Alpha mapper at a commit not fetched; Gamma fork at a commit not fetched.");

  const agrees = page.locator('[data-testid="graph-relation"][data-kind="agrees"]');
  await agrees.getByText("Where it is found").click();
  await expect(agrees).toContainText("Numbers in common: 0.91.");
  await expect(agrees.getByTestId("graph-quote").first()).toContainText("Alpha reached an AUROC of 0.91 on held-out mouse cells.");

  // The papers, with what was read of each
  await expect(papers(page)).toHaveCount(3);
  const gammaRow = papers(page).and(page.locator(`[data-id="${gamma}"]`));
  await expect(gammaRow).toContainText("Not read");
  await expect(gammaRow).toContainText("In 2 relations");
  await expect(papers(page).and(page.locator(`[data-id="${alpha}"]`))).toContainText("In 5 relations");
  expect(await accessibilityProblems(page)).toEqual([]);

  // One kind
  await form(page).getByLabel("Kind").selectOption("code");
  await expect(relations(page)).toHaveCount(1);
  expect(await kindsShown(page)).toEqual(["code"]);
  await expect(papers(page)).toHaveCount(2);
  await expect(page.getByRole("region", { name: "Papers" })).toContainText("The papers of these relations");
  // What a paper is in is said of all the relations, and of those that are shown
  await expect(gammaRow).toContainText("In 2 relations, 1 of them shown");
  await expect(papers(page).and(page.locator(`[data-id="${alpha}"]`))).toContainText("In 5 relations, 1 of them shown");

  // One paper, of every kind
  await form(page).getByRole("button", { name: "Show every relation" }).click();
  await expect(relations(page)).toHaveCount(6);
  await form(page).getByLabel("Paper").selectOption(beta);
  await expect(relations(page)).toHaveCount(5);
  expect(await kindsShown(page)).toEqual(["agrees", "dataset", "refers", "refers", "software"]);
  // Its own row says it is the one chosen, and taking it away shows them all
  const betaRow = papers(page).and(page.locator(`[data-id="${beta}"]`));
  await expect(betaRow.getByRole("button", { name: "Show every paper's relations" })).toHaveAttribute("aria-pressed", "true");
  await betaRow.getByRole("button", { name: "Show every paper's relations" }).click();
  await expect(relations(page)).toHaveCount(6);
  await expect(form(page).getByLabel("Paper")).toHaveValue("");
  await gammaRow.getByRole("button", { name: "Only its relations" }).click();
  await expect(relations(page)).toHaveCount(2);
  expect(await kindsShown(page)).toEqual(["code", "refers"]);
  await expect(form(page).getByLabel("Paper")).toHaveValue(gamma);
  await form(page).getByRole("button", { name: "Show every relation" }).click();
  await expect(relations(page)).toHaveCount(6);

  // Words, which are asked of the server before they are kept
  await form(page).getByLabel("Words").fill("GSE12345");
  await form(page).getByRole("button", { name: "Look" }).click();
  await expect(page.getByTestId("graph-about")).toHaveText("Only the relations that have any of these words: GSE12345");
  await expect(relations(page)).toHaveCount(1);
  expect(await kindsShown(page)).toEqual(["dataset"]);

  // Words that have none of their own are refused, and what was shown stays, with the words it is of
  await form(page).getByLabel("Words").fill("the of");
  await form(page).getByRole("button", { name: "Look" }).click();
  await expect(form(page).getByRole("alert").or(form(page).locator('[data-slot="notice"]')).first()).toContainText("Give some words to look for");
  await expect(page.getByTestId("graph-about")).toHaveText("Only the relations that have any of these words: GSE12345");
  await expect(relations(page)).toHaveCount(1);

  // Words that are of nothing
  await form(page).getByLabel("Words").fill("zebrafish");
  await form(page).getByRole("button", { name: "Look" }).click();
  await expect(page.getByTestId("graph-empty")).toContainText("No relation is of what is asked for");
  await page.getByTestId("graph-empty").getByRole("button", { name: "Show every relation" }).click();
  await expect(relations(page)).toHaveCount(6);
  await expect(form(page).getByLabel("Words")).toHaveValue("");
  await expect(page.getByTestId("graph-about")).toHaveCount(0);

  // While words are asked of the server nothing else can be asked, so that the answer is to what is shown
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/paperagents/graph?*about=*", async (route) => {
    await held;
    await route.continue();
  });
  await form(page).getByLabel("Words").fill("Seurat");
  await form(page).getByRole("button", { name: "Look" }).click();
  await expect(form(page).getByLabel("Kind")).toBeDisabled();
  await expect(form(page).getByLabel("Paper")).toBeDisabled();
  await expect(gammaRow.getByRole("button", { name: "Only its relations" })).toBeDisabled();
  release();
  await expect(relations(page)).toHaveCount(1);
  expect(await kindsShown(page)).toEqual(["software"]);
  await expect(form(page).getByLabel("Kind")).toBeEnabled();
  await page.unroute("**/api/paperagents/graph?*about=*");
});

test("never shows the graph of one question under another, while the next is looked at or when it fails", async ({ page }) => {
  await threeAgents(page);
  await page.goto("/papers?view=graph");
  await expect(relations(page)).toHaveCount(6);

  // The graph of one kind is held back, and the graph of every kind is not shown under it meanwhile
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/paperagents/graph?kind=code", async (route) => {
    await held;
    await route.continue();
  });
  await form(page).getByLabel("Kind").selectOption("code");
  await expect(page.getByTestId("graph-looking")).toBeVisible();
  await expect(relations(page)).toHaveCount(0);
  await expect(papers(page)).toHaveCount(0);
  release();
  await expect(relations(page)).toHaveCount(1);
  await expect(page.getByTestId("graph-looking")).toHaveCount(0);
  await page.unroute("**/api/paperagents/graph?kind=code");

  // One that fails says so, and is asked again
  await page.route("**/api/paperagents/graph?kind=software", (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "internal", message: "It broke" } }) }),
  );
  await form(page).getByLabel("Kind").selectOption("software");
  await expect(page.getByTestId("graph-failed")).toBeVisible();
  await expect(relations(page)).toHaveCount(0);
  await page.unroute("**/api/paperagents/graph?kind=software");
  await page.getByTestId("graph-failed").getByRole("button", { name: "Try again" }).click();
  await expect(relations(page)).toHaveCount(1);
  expect(await kindsShown(page)).toEqual(["software"]);

  // An agent that is not in the graph is said not to be, and not to have no relations
  await page.goto("/papers?view=graph&of=no-such-agent");
  await expect(page.getByTestId("graph-empty")).toContainText("This agent is not in the graph");
  await expect(page.getByTestId("graph-empty")).toContainText("It is not among the agents there are now.");
  await page.getByTestId("graph-empty").getByRole("button", { name: "Show every relation" }).click();
  await expect(relations(page)).toHaveCount(6);
});

test("is reached from an agent's page with its relations, and is made again as what it is made from changes", async ({ page }) => {
  const { alpha, beta } = await threeAgents(page);
  await page.goto(`/papers?agent=${beta}`);
  await expect(page.getByRole("heading", { name: "Beta mapper", level: 2 })).toBeVisible();
  await page.getByRole("link", { name: "How its paper relates to the others" }).click();
  await expect(page).toHaveURL(new RegExp(`/papers\\?view=graph&of=${beta}$`));
  await expect(form(page).getByLabel("Paper")).toHaveValue(beta);
  await expect(relations(page)).toHaveCount(5);

  // The reading of the first paper is taken away, so only its code relates it: to Gamma's, and in Beta's words
  expect((await page.request.delete(`/api/paperagents/${alpha}/reading`)).status()).toBe(200);
  await page.goto("/papers?view=graph");
  await expect(relations(page)).toHaveCount(3);
  expect(await kindsShown(page)).toEqual(["code", "refers", "refers"]);
  await expect(papers(page).and(page.locator(`[data-id="${alpha}"]`))).toContainText("Not read");
});
