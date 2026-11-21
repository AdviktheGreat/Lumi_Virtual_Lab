import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { expect, test } from "../fixtures";

// The bake-offs, the agents that are made for their methods, and the data that they are made of are the workspace's, so each test takes
// what it made away, and none is run beside another
test.describe.configure({ mode: "serial" });

const TASK = "Assign a cell type to each cell of my single-nucleus RNA-seq data.";
const SCANPY = "10.1186/s13059-017-1382-0";
const ARXIV = "https://arxiv.org/abs/2101.00001";

async function clear(page: Page) {
  const { bakeoffs } = await (await page.request.get("/api/bakeoffs")).json();
  for (const bakeoff of bakeoffs) {
    await expect.poll(async () => (await page.request.delete(`/api/bakeoffs/${bakeoff.id}`)).status(), { timeout: 20_000 }).toBe(200);
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

async function makeBakeoff(page: Page, body: Record<string, unknown> = {}): Promise<string> {
  const made = await page.request.post("/api/bakeoffs", { data: { task: TASK, title: "Cell types", limit: 2, ...body } });
  expect(made.status()).toBe(201);

  return (await made.json()).id;
}

// Puts a method in the running through the server, and gives back its id
async function addMethod(page: Page, bakeoff: string, body: Record<string, unknown>): Promise<string> {
  const added = await page.request.post(`/api/bakeoffs/${bakeoff}/candidates`, { data: body });
  expect(added.status()).toBe(201);
  const { candidates } = await added.json();

  return candidates[candidates.length - 1].id;
}

const viewOf = async (page: Page, id: string) => (await page.request.get(`/api/bakeoffs/${id}`)).json();

async function openBakeoff(page: Page, id: string, title = "Cell types") {
  await page.goto(`/papers?bakeoff=${id}`);
  await expect(page.getByRole("heading", { name: title, level: 2 })).toBeVisible();
}

const adding = (page: Page) => page.getByRole("form", { name: "Add a method" });
const finding = (page: Page) => page.getByRole("form", { name: "Find methods in the literature" });
const methods = (page: Page) => page.getByTestId("bakeoff-method");
const methodNamed = (page: Page, name: string) => methods(page).filter({ has: page.getByRole("heading", { name, level: 3 }) });
const work = (page: Page) => page.getByRole("region", { name: "What is being done to the methods" });

// What the page is shown of a bake-off, changed from what the server says of it. The server still does what is asked of it.
type View = Record<string, unknown> & { candidates: { id: string }[] };

async function showing(page: Page, id: string, change: (view: View) => View) {
  await page.route(`**/api/bakeoffs/${id}`, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();

    return route.fulfill({ response, json: change((await response.json()) as View) });
  });
}

const standing = (state: string, step: string | null, reason: string, why?: string) => ({ state, step, reason, ...(why !== undefined ? { why } : {}) });

// A job that is at work on a bake-off, as the server describes one
function jobOf(bakeoff: string, kind: string, title: string, changes: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    kind,
    subject: bakeoff,
    title,
    state: "running",
    message: "Looking at the code of Scanpy",
    progress: { finished: 0, total: 2 },
    error: null,
    created_at: new Date().toISOString(),
    finished_at: null,
    log_total: 0,
    ...changes,
  };
}

test("puts a method in the running by its DOI or its link, and says what is wrong before anything is sent", async ({ page }) => {
  const id = await makeBakeoff(page);
  await openBakeoff(page, id);
  await expect(page.getByTestId("bakeoff-methods-empty")).toContainText("There are no methods in the running yet");

  const sent: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith(`/api/bakeoffs/${id}/candidates`)) sent.push(request.postData() ?? "");
  });
  const add = adding(page).getByRole("button", { name: "Add the method" });
  await add.click();
  await expect(adding(page).getByText(/Give the DOI of its paper/)).toBeVisible();
  await adding(page).getByLabel("Its paper").fill("scanpy");
  await adding(page).getByLabel("Where its code is").fill("https://example.org/owner/name");
  await add.click();
  await expect(adding(page).getByText(/Give a DOI, such as/)).toBeVisible();
  await expect(adding(page).getByText(/Give the address of the project/)).toBeVisible();
  await adding(page).getByLabel("Its paper").fill("https://doi.org/not-a-doi");
  await add.click();
  await expect(adding(page).getByText(/has no DOI in it/)).toBeVisible();
  expect(sent).toEqual([]);
  expect(await accessibilityProblems(page)).toEqual([]);

  // A DOI is sent as one, in lower case, with its name tidied and where its code is
  await adding(page).getByLabel("Its paper").fill(`  https://doi.org/${SCANPY.toUpperCase()} `);
  await adding(page).getByLabel("What it is called").fill("  Scanpy   (Wolf) ");
  await adding(page).getByLabel("Where its code is").fill("https://github.com/scverse/scanpy");
  const body = page.waitForRequest((request) => request.method() === "POST" && request.url().endsWith(`/api/bakeoffs/${id}/candidates`));
  await add.click();
  expect((await body).postDataJSON()).toEqual({
    paper: { kind: "doi", doi: SCANPY },
    name: "Scanpy (Wolf)",
    repo: "https://github.com/scverse/scanpy",
  });
  const scanpy = methodNamed(page, "Scanpy (Wolf)");
  await expect(scanpy).toHaveCount(1);
  await expect(scanpy).toHaveAttribute("data-state", "new");
  await expect(scanpy.getByTestId("method-standing")).toHaveText("Not built");
  await expect(scanpy).toContainText("Added by you");
  await expect(scanpy.getByRole("link", { name: `DOI ${SCANPY}` })).toHaveAttribute("href", `https://doi.org/${SCANPY}`);
  await expect(scanpy.getByTestId("method-code").getByRole("link", { name: "scverse/scanpy" })).toHaveAttribute("href", "https://github.com/scverse/scanpy");
  await expect(page.getByTestId("bakeoff-methods-empty")).toHaveCount(0);
  await expect(page.getByText("1 method.", { exact: false }).first()).toBeVisible();
  // The form is made empty again for the next
  await expect(adding(page).getByLabel("Its paper")).toHaveValue("");

  // The same paper is not put in twice, whichever way it is said, and the server says which method it is
  await adding(page).getByLabel("Its paper").fill(SCANPY);
  await add.click();
  await expect(adding(page).getByRole("alert").filter({ hasText: "A method of that paper is in the running already, Scanpy (Wolf)." })).toBeVisible();
  await expect(methods(page)).toHaveCount(1);

  // A link is sent as one, and a method with no name is called by where its link leads
  await adding(page).getByLabel("Its paper").fill(` ${ARXIV} `);
  const link = page.waitForRequest((request) => request.method() === "POST" && request.url().endsWith(`/api/bakeoffs/${id}/candidates`));
  await add.click();
  expect((await link).postDataJSON()).toEqual({ paper: { kind: "url", url: ARXIV } });
  await expect(methods(page)).toHaveCount(2);
  await expect(methodNamed(page, "arxiv.org/abs/2101.00001")).toHaveCount(1);
  expect((await viewOf(page, id)).candidates.map((method: { paper: unknown }) => method.paper)).toEqual([{ kind: "doi", doi: SCANPY }, { kind: "url", url: ARXIV }]);
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("says again what a method is called and where its code is, sending only what differs, and removes it after asking", async ({ page }) => {
  const id = await makeBakeoff(page);
  const method = await addMethod(page, id, { paper: { kind: "doi", doi: SCANPY }, name: "Scanpy", repo: "https://github.com/scverse/scanpy" });
  await openBakeoff(page, id);
  const card = methodNamed(page, "Scanpy");
  await card.getByText("Change its name or where its code is").click();
  const changing = card.getByRole("form", { name: "Change Scanpy" });
  const save = changing.getByRole("button", { name: "Save" });
  await expect(changing.getByLabel("Name")).toHaveValue("Scanpy");
  await expect(changing.getByLabel("Where its code is")).toHaveValue("https://github.com/scverse/scanpy");
  await expect(save).toBeDisabled();

  await changing.getByLabel("Name").fill("   ");
  await changing.getByLabel("Where its code is").fill("https://example.org/a/b");
  await save.click();
  await expect(changing.getByText("Say what it is called.")).toBeVisible();
  await expect(changing.getByText(/Give the address of the project/)).toBeVisible();
  expect((await viewOf(page, id)).candidates[0]).toMatchObject({ name: "Scanpy", repo: "https://github.com/scverse/scanpy" });
  expect(await accessibilityProblems(page)).toEqual([]);

  await changing.getByLabel("Name").fill("Scanpy 1.9");
  await changing.getByLabel("Where its code is").fill("https://github.com/scverse/scanpy");
  const renamed = page.waitForRequest((request) => request.method() === "PATCH" && request.url().endsWith(`/candidates/${method}`));
  await save.click();
  expect((await renamed).postDataJSON()).toEqual({ name: "Scanpy 1.9" });
  await expect(methodNamed(page, "Scanpy 1.9")).toHaveCount(1);

  // An empty address takes the code away
  const after = methodNamed(page, "Scanpy 1.9");
  const again = after.getByRole("form", { name: "Change Scanpy 1.9" });
  await again.getByLabel("Where its code is").fill("");
  const taken = page.waitForRequest((request) => request.method() === "PATCH" && request.url().endsWith(`/candidates/${method}`));
  await again.getByRole("button", { name: "Save" }).click();
  expect((await taken).postDataJSON()).toEqual({ repo: "" });
  await expect(after.getByTestId("method-code")).toContainText("not said");
  expect((await viewOf(page, id)).candidates[0]).toMatchObject({ name: "Scanpy 1.9", repo: null });

  await after.getByRole("button", { name: "Remove Scanpy 1.9" }).click();
  const asking = page.getByRole("alertdialog", { name: "Remove Scanpy 1.9?" });
  await expect(asking).toContainText("Its PaperAgent, if it has one, stays");
  await asking.getByRole("button", { name: "Keep" }).click();
  await expect(methods(page)).toHaveCount(1);
  await after.getByRole("button", { name: "Remove Scanpy 1.9" }).click();
  await page.getByRole("alertdialog", { name: "Remove Scanpy 1.9?" }).getByRole("button", { name: "Remove", exact: true }).click();
  await expect(methods(page)).toHaveCount(0);
  await expect(page.getByTestId("bakeoff-methods-empty")).toBeVisible();
  expect((await viewOf(page, id)).candidates).toEqual([]);
});

const RESULT = "CellMapper reached an AUROC of 0.93 on held-out mouse hippocampus nuclei, higher than the 0.88 of Seurat label transfer.";
const LIMIT = "CellMapper was only tested on mouse brain tissue, and it assumes at least 500 nuclei in each sample.";
const PAPER = [
  "CellMapper: mapping cell types",
  "Abstract",
  "fabricate: We present CellMapper, a method for mapping cell types.",
  "Results",
  RESULT,
  "Methods",
  "Clusters were found with Seurat v4.3 after the reads were aligned.",
  "Limitations",
  LIMIT,
  "References",
  "1. Doe J. et al. A method for cells. Nature 2020.",
].join("\n\n");

test("puts the data against the card of a method's paper, warns where it is outside, and keeps going on only for what the person was shown", async ({ page }) => {
  const id = await makeBakeoff(page, { described: { species: "human" } });
  const method = await addMethod(page, id, { paper: { kind: "doi", doi: SCANPY }, name: "CellMapper" });
  await openBakeoff(page, id);
  const card = methodNamed(page, "CellMapper");

  // Until the method has a PaperAgent, and its paper has been read, there is no card to put the data against, and it says so
  await expect(card.getByTestId("method-scope-none")).toContainText("This method has no PaperAgent yet");
  await expect(card.getByTestId("method-scope")).toHaveCount(0);
  const agent = await page.request.post("/api/paperagents", { data: { title: "CellMapper paper", paper: { kind: "doi", doi: SCANPY } } });
  expect(agent.status()).toBe(201);
  const agentId: string = (await agent.json()).id;
  const sent = await page.request.post(`/api/paperagents/${agentId}/paper?name=cells.txt`, {
    data: Buffer.from(PAPER),
    headers: { "Content-Type": "application/octet-stream" },
  });
  expect(sent.status()).toBe(201);
  await page.reload();
  await expect(card.getByTestId("method-scope-none")).toContainText("The paper has not been read yet");
  await expect(card.getByRole("link", { name: "CellMapper paper" })).toHaveAttribute("href", `/papers?agent=${agentId}`);

  const read = await page.request.post(`/api/paperagents/${agentId}/reading`, { data: { max_cost: 2 } });
  expect(read.status()).toBe(202);
  await expect.poll(async () => (await (await page.request.get(`/api/paperagents/${agentId}/reading`)).json()).complete, { timeout: 20_000 }).toBe(true);
  await page.reload();

  const scope = card.getByTestId("method-scope");
  await expect(scope).toHaveAttribute("data-outcome", "outside");
  await expect(scope.getByTestId("scope-warning")).toHaveCount(1);
  await expect(scope.getByTestId("scope-warning").first()).toContainText("the data's species is “human”, and the card gives the species as “mouse”");
  await expect(scope.getByTestId("scope-result")).toContainText("Outside");
  await expect(scope).toContainText("Going on is yours to say.");
  expect(await accessibilityProblems(page)).toEqual([]);

  // Going on says which scope it was shown, by its key, and is kept
  const key = (await viewOf(page, id)).candidates[0].scope.key;
  expect(key).toEqual(expect.any(String));
  const going = page.waitForRequest((request) => request.method() === "POST" && request.url().endsWith(`/candidates/${method}/go-on`));
  await card.getByRole("button", { name: "Go on with it on my data" }).click();
  expect((await going).postDataJSON()).toEqual({ key });
  await expect(card.getByTestId("method-went-on")).toContainText("You go on with it");
  await expect(card.getByRole("button", { name: "Go on with it on my data" })).toHaveCount(0);
  expect((await viewOf(page, id)).candidates[0].scope).toMatchObject({ went_on: true });
  await page.reload();
  await expect(card.getByTestId("method-went-on")).toBeVisible();

  // It is taken back whenever the person says
  await card.getByRole("button", { name: "Take it back" }).click();
  await expect(card.getByTestId("method-went-on")).toHaveCount(0);
  await expect(card.getByRole("button", { name: "Go on with it on my data" })).toBeVisible();
  expect((await viewOf(page, id)).candidates[0].scope).toMatchObject({ went_on: false, went_on_at: null });

  // It is not kept for data that is said otherwise, though that is outside too, as it is not what they were shown
  await card.getByRole("button", { name: "Go on with it on my data" }).click();
  await expect(card.getByTestId("method-went-on")).toBeVisible();
  expect((await page.request.patch(`/api/bakeoffs/${id}`, { data: { described: { species: "rat" } } })).status()).toBe(200);
  await page.reload();
  await expect(card.getByTestId("method-scope")).toHaveAttribute("data-outcome", "outside");
  await expect(card.getByTestId("method-went-on")).toHaveCount(0);
  await expect(card.getByRole("button", { name: "Go on with it on my data" })).toBeVisible();

  // Data inside what the card says has nothing to go on with, and the card's words are not that the method works
  expect((await page.request.patch(`/api/bakeoffs/${id}`, { data: { described: { species: "mouse" } } })).status()).toBe(200);
  await page.reload();
  await expect(card.getByTestId("method-scope")).toHaveAttribute("data-outcome", "inside");
  await expect(card.getByTestId("method-scope")).toContainText("That is not that it works on yours.");
  await expect(card.getByRole("button", { name: "Go on with it on my data" })).toHaveCount(0);
  await expect(card.getByTestId("scope-warning")).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  // Nothing said of the data is nothing put against the card
  expect((await page.request.patch(`/api/bakeoffs/${id}`, { data: { described: {} } })).status()).toBe(200);
  await page.reload();
  await expect(card.getByTestId("method-scope-none")).toContainText("Nothing has been said of what the data is");
});

test("offers the addresses that a paper points to as its code only for the person to say that they are", async ({ page }) => {
  const id = await makeBakeoff(page);
  const method = await addMethod(page, id, { paper: { kind: "doi", doi: SCANPY }, name: "Scanpy" });
  await showing(page, id, (view) => ({
    ...view,
    candidates: view.candidates.map((each: { id: string }) =>
      each.id === method
        ? {
            ...each,
            suggested: ["https://github.com/scverse/scanpy", "https://gitlab.com/group/sub/scanpy"],
            standing: standing("waiting", "code", "No address of the code was given. The paper or its abstract points to two addresses.", "choose_code"),
          }
        : each,
    ),
  }));
  await openBakeoff(page, id);
  const card = methodNamed(page, "Scanpy");

  await expect(card.getByTestId("method-standing")).toHaveText("Waiting for you");
  await expect(card.getByTestId("method-standing-text")).toContainText("Finding its code");
  await expect(card.getByTestId("method-standing-text")).toContainText("No address of the code was given.");
  await expect(card.getByTestId("method-code")).toContainText("not said");
  const pointed = card.getByTestId("method-pointed");
  await expect(pointed).toContainText("They are not its code until you say so.");
  await expect(pointed.getByRole("listitem")).toHaveCount(2);
  expect((await viewOf(page, id)).candidates[0].repo).toBeNull();
  expect(await accessibilityProblems(page)).toEqual([]);

  const said = page.waitForRequest((request) => request.method() === "PATCH" && request.url().endsWith(`/candidates/${method}`));
  await pointed.getByRole("listitem").nth(1).getByRole("button", { name: "It is its code" }).click();
  expect((await said).postDataJSON()).toEqual({ repo: "https://gitlab.com/group/sub/scanpy" });
  expect((await viewOf(page, id)).candidates[0].repo).toBe("https://gitlab.com/group/sub/scanpy");
  await expect(card.getByTestId("method-code").getByRole("link", { name: "group/sub/scanpy" })).toBeVisible();
  // Where the code is said, nothing is offered
  await expect(card.getByTestId("method-pointed")).toHaveCount(0);
});

test("builds the methods that are not built, one or all, and goes on with one whose code it asks about, which is said to the server", async ({ page }) => {
  const id = await makeBakeoff(page, { described: { species: "mouse" } });
  const first = await addMethod(page, id, { paper: { kind: "doi", doi: SCANPY }, name: "Scanpy", repo: "https://github.com/scverse/scanpy" });
  const second = await addMethod(page, id, { paper: { kind: "url", url: ARXIV }, name: "Arxiv one" });
  let started: ReturnType<typeof jobOf> | null = null;
  await showing(page, id, (view) => ({
    ...view,
    job: started,
    candidates: view.candidates.map((each: { id: string }) =>
      each.id === first
        ? { ...each, standing: standing("waiting", "preflight", "Looking at its code found things to ask you about: it runs a shell script.", "ask") }
        : each,
    ),
  }));
  await page.route("**/api/setup/jobs", (route) => (route.request().method() === "GET" ? route.fulfill({ json: { jobs: started === null ? [] : [started] } }) : route.fallback()));
  const asked: Record<string, unknown>[] = [];
  await page.route(`**/api/bakeoffs/${id}/build`, (route) => {
    asked.push(route.request().postDataJSON());
    started = jobOf(id, "bakeoff-build", "Building the methods: Cell types");

    return route.fulfill({ status: 202, json: started });
  });
  await openBakeoff(page, id);

  // A method that is waiting for the person is gone on with by saying so, and is the only one asked of
  const waiting = methodNamed(page, "Scanpy");
  await expect(waiting.getByTestId("method-standing")).toHaveText("Waiting for you");
  await expect(waiting.getByTestId("method-standing-text")).toContainText("Looking at its code");
  await expect(waiting.getByTestId("method-standing-text")).toContainText("it runs a shell script");
  await expect(waiting.getByRole("button", { name: /^Build/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Build all" })).toBeEnabled();
  await expect(work(page)).toHaveCount(0);
  expect(await accessibilityProblems(page)).toEqual([]);

  await methodNamed(page, "Arxiv one").getByRole("button", { name: "Build Arxiv one" }).click();
  await expect(work(page)).toContainText("Building the methods: Cell types");
  await expect(work(page)).toContainText("Running");
  expect(asked).toEqual([{ candidates: [second] }]);

  // While it is at work nothing is built, removed, or changed, and it can be stopped
  await expect(page.getByRole("button", { name: "Build all" })).toBeDisabled();
  await expect(waiting.getByRole("button", { name: "Go on and build it" })).toBeDisabled();
  await expect(waiting.getByRole("button", { name: "Remove Scanpy" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Add the method" })).toBeDisabled();
  await expect(finding(page).getByRole("button", { name: "Find methods" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Delete Cell types" })).toBeDisabled();
  expect(await accessibilityProblems(page)).toEqual([]);

  await page.route(`**/api/setup/jobs/job-1/stop`, (route) => {
    started = { ...jobOf(id, "bakeoff-build", "Building the methods: Cell types"), state: "stopping" };

    return route.fulfill({ json: started });
  });
  await work(page).getByRole("button", { name: "Stop: Building the methods: Cell types" }).click();
  await expect(work(page).getByRole("button", { name: /^Stopping/ })).toBeDisabled();

  // Once it is over, and how it ended is shown, the methods are built again
  started = null;
  await page.route("**/api/setup/jobs", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: { jobs: [jobOf(id, "bakeoff-build", "Building the methods: Cell types", { state: "stopped", finished_at: new Date().toISOString() })] } })
      : route.fallback(),
  );
  await page.reload();
  await expect(work(page)).toContainText("Stopped");
  await expect(page.getByRole("button", { name: "Build all" })).toBeEnabled();

  await waiting.getByRole("button", { name: "Go on and build it" }).click();
  await expect.poll(() => asked.length).toBe(2);
  expect(asked[1]).toEqual({ candidates: [first], go_on: [first] });
});

test("builds all of the methods in one request, and says why the server refused where it did", async ({ page }) => {
  const id = await makeBakeoff(page);
  await addMethod(page, id, { paper: { kind: "doi", doi: SCANPY }, name: "Scanpy" });
  await addMethod(page, id, { paper: { kind: "url", url: ARXIV }, name: "Arxiv one" });
  const asked: Record<string, unknown>[] = [];
  await page.route(`**/api/bakeoffs/${id}/build`, (route) => {
    asked.push(route.request().postDataJSON());

    return route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "docker_missing", message: "Docker is not running, and building takes it." } }),
    });
  });
  await openBakeoff(page, id);

  await expect(page.getByText(/Building a method makes a PaperAgent of its paper/)).toContainText("$2.00 is left of $2.00.");
  await page.getByRole("button", { name: "Build all" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Docker is not running, and building takes it." })).toBeVisible();
  expect(asked).toEqual([{}]);
  await expect(work(page)).toHaveCount(0);
  // Nothing was started, so nothing is at work, and the methods may be built again
  await expect(page.getByRole("button", { name: "Build all" })).toBeEnabled();
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("finds methods with searches that the person says or that a model writes, and shows what it found and what that is not", async ({ page }) => {
  const id = await makeBakeoff(page);
  const method = await addMethod(page, id, { paper: { kind: "doi", doi: SCANPY }, name: "Found one" });
  const shortlist = {
    started_at: "2026-01-01T00:00:00Z",
    finished_at: new Date().toISOString(),
    model: "some/model",
    written_by: "model",
    queries: ["cell type annotation single-nucleus"],
    found: 25,
    total: 60,
    chosen: 4,
    added: 1,
    dropped: { not_shown: 0, twice: 0, quote: 2, more: 0, already: 1, no_room: 0 },
    notes: [],
    complete: true,
    note: null,
    cost: 0.0123,
  };
  await showing(page, id, (view) => ({
    ...view,
    shortlist,
    candidates: view.candidates.map((each: { id: string }) =>
      each.id === method
        ? {
            ...each,
            added_by: "search",
            title: "Fast and accurate cell type annotation",
            found: { source: "europepmc", url: "", credit: "Wolf", venue: "Genome Biology", year: 2018, cited_by: 3000, preprint: false, full_text: false },
            fit: { quote: "a method to annotate cell types in single-nucleus data", model: "some/model" },
          }
        : each,
    ),
  }));
  const asked: Record<string, unknown>[] = [];
  await page.route(`**/api/bakeoffs/${id}/shortlist`, (route) => {
    asked.push(route.request().postDataJSON());

    return route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "money", message: "Nothing is left of the limit to find methods with." } }),
    });
  });
  await openBakeoff(page, id);

  const card = methodNamed(page, "Found one");
  await expect(card).toContainText("Found by a search");
  await expect(card).toContainText("Fast and accurate cell type annotation");
  await expect(card).toContainText("Europe PMC, Genome Biology, 2018, cited 3000 times");
  await expect(card).toContainText("Europe PMC does not hold its full text");
  await expect(card.getByTestId("method-fit")).toContainText("The words of its abstract that some/model went by in choosing it");
  await expect(card.getByTestId("method-fit").getByRole("blockquote")).toHaveText("a method to annotate cell types in single-nucleus data");

  const record = page.getByTestId("bakeoff-shortlist");
  await expect(record).toContainText("Searched for: cell type annotation single-nucleus");
  await expect(record).toContainText("The searches were written by some/model.");
  await expect(record).toContainText("25 papers were shown to some/model, of the 60 that the searches found.");
  await expect(record).toContainText("4 chosen, 1 added to the methods.");
  await expect(record).toContainText("Thrown away: 2 choices whose quoted words are not in the abstract; 1 method already in the running.");
  await expect(record).toContainText("It spent $0.01.");
  await expect(page.getByTestId("bakeoff-meaning")).not.toBeEmpty();
  expect(await accessibilityProblems(page)).toEqual([]);

  // Where no search is typed, a model writes them
  const find = finding(page).getByRole("button", { name: "Find methods" });
  await find.click();
  await expect(finding(page).getByRole("alert").filter({ hasText: "Nothing is left of the limit to find methods with." })).toBeVisible();
  expect(asked).toEqual([{}]);

  // Searches that are typed are sent as the server makes them, a line each, and not more than it takes
  const searches = finding(page).getByLabel("Your own searches");
  await searches.fill("cell type annotation\nSINGLE-cell AND clustering\ncell type annotation");
  await find.click();
  await expect.poll(() => asked.length).toBe(2);
  expect(asked[1]).toEqual({ queries: ["cell type annotation", "SINGLE-cell clustering"] });

  await searches.fill("one\ntwo\nthree\nfour");
  await find.click();
  await expect(finding(page).getByText(/At most 3 searches, a line for each, and these are 4/)).toBeVisible();
  await searches.fill("AND OR");
  await find.click();
  await expect(finding(page).getByText(/has no word to look for/)).toBeVisible();
  expect(asked).toHaveLength(2);
  expect(await accessibilityProblems(page)).toEqual([]);
});
