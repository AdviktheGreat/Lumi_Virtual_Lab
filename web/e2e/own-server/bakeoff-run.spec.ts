import type { Page, Route } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { expect, test } from "../fixtures";

// The bake-offs, the agents that are made for their methods, and the data that they are made of are the workspace's, so each test takes
// what it made away, and none is run beside another
test.describe.configure({ mode: "serial" });

const TASK = "Assign a cell type to each cell of my single-nucleus RNA-seq data.";
const SCANPY = "10.1186/s13059-017-1382-0";
const ARXIV = "https://arxiv.org/abs/2101.00001";
const OWN = ["cells.csv", "truth.csv"];
const CELLS = "cell,gene1,gene2\nc1,1,2\nc2,3,4\n";
const TRUTH = "cell,label\nc1,T\nc2,B\n";

async function clear(page: Page) {
  const { bakeoffs } = await (await page.request.get("/api/bakeoffs")).json();
  for (const bakeoff of bakeoffs) {
    await expect.poll(async () => (await page.request.delete(`/api/bakeoffs/${bakeoff.id}`)).status(), { timeout: 20_000 }).toBe(200);
  }
  const { agents } = await (await page.request.get("/api/paperagents")).json();
  for (const agent of agents) {
    await expect.poll(async () => (await page.request.delete(`/api/paperagents/${agent.id}`)).status(), { timeout: 20_000 }).toBe(200);
  }
  for (const name of OWN) await page.request.delete(`/api/own/data/${name}`);
}

test.beforeEach(async ({ page }) => {
  await clear(page);
});

test.afterEach(async ({ page }) => {
  await clear(page);
});

async function addData(page: Page, name: string, text: string) {
  const added = await page.request.post(`/api/own/data/files?name=${encodeURIComponent(name)}&description=${encodeURIComponent("For a bake-off")}`, {
    data: Buffer.from(text),
    headers: { "Content-Type": "application/octet-stream" },
  });
  expect(added.status()).toBe(201);
}

async function makeBakeoff(page: Page, body: Record<string, unknown> = {}): Promise<string> {
  const made = await page.request.post("/api/bakeoffs", { data: { task: TASK, title: "Cell types", limit: 2, ...body } });
  expect(made.status()).toBe(201);

  return (await made.json()).id;
}

async function addMethod(page: Page, bakeoff: string, body: Record<string, unknown>): Promise<string> {
  const added = await page.request.post(`/api/bakeoffs/${bakeoff}/candidates`, { data: body });
  expect(added.status()).toBe(201);
  const { candidates } = await added.json();

  return candidates[candidates.length - 1].id;
}

async function openBakeoff(page: Page, id: string, title = "Cell types") {
  await page.goto(`/papers?bakeoff=${id}`);
  await expect(page.getByRole("heading", { name: title, level: 2 })).toBeVisible();
}

const running = (page: Page) => page.getByRole("form", { name: "Run the methods" });
const rows = (page: Page) => page.getByTestId("run-row");
const rowOf = (page: Page, name: string) => rows(page).filter({ hasText: `Run ${name}` });
const runWork = (page: Page) => page.getByRole("region", { name: "What is being done to run the methods" });
const methodWork = (page: Page) => page.getByRole("region", { name: "What is being done to the methods" });
const lastRunOf = (page: Page, id: string) => page.getByTestId("run-of-method").and(page.locator(`[data-method="${id}"]`));
const comparedRow = (page: Page, id: string) => page.getByTestId("compare-method").and(page.locator(`[data-method="${id}"]`));

type Candidate = Record<string, unknown> & { id: string };
type View = Record<string, unknown> & { candidates: Candidate[] };

// What the page is shown of a bake-off, changed from what the server says of it. The server still does what is asked of it.
async function showing(page: Page, id: string, change: (view: View) => View) {
  await page.route(`**/api/bakeoffs/${id}`, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();

    return route.fulfill({ response, json: change((await response.json()) as View) });
  });
}

// A method that is built, as the page is shown one
const built = (agent: string, changes: Record<string, unknown> = {}) => ({
  agent: { id: agent, title: `${agent} agent`, repo: null, steps: {} },
  standing: { state: "built", step: null, reason: "", at: "2026-01-01T00:00:00Z" },
  ...changes,
});

function toolsOf(agent: string, names: string[]) {
  return {
    id: agent,
    docker: { ready: true, message: null },
    reference: null,
    preview: null,
    kept: {
      tools: names.map((name) => ({
        name,
        tier: "A",
        module: "scanpy.pp",
        function: name,
        parameters: ["path", "target_sum"],
        checked: 2,
        recorded: 3,
        repeats: 2,
        tutorials: ["basic"],
      })),
    },
    job: null,
    meaning: "A tool of tier A gave again, each time it was called, what its tutorial got.",
  };
}

async function withTools(page: Page, agent: string, names: string[]) {
  await page.route(`**/api/paperagents/${agent}/tools`, (route) => route.fulfill({ json: toolsOf(agent, names) }));
  for (const name of names) {
    await page.route(`**/api/paperagents/${agent}/tools/${name}`, (route) =>
      route.fulfill({
        json: {
          name,
          tier: "A",
          description: `${name} makes the counts comparable.`,
          signature: [
            { name: "path", type: "str", required: true, default: null },
            { name: "target_sum", type: "float", required: false, default: null },
          ],
        },
      }),
    );
  }
}

function jobOf(bakeoff: string, changes: Record<string, unknown> = {}) {
  return {
    id: "job-run",
    kind: "bakeoff-run",
    subject: bakeoff,
    title: "Running the methods: Cell types",
    state: "running",
    message: "Running Scanpy (1 of 2)",
    progress: { finished: 0, total: 2 },
    error: null,
    created_at: new Date().toISOString(),
    finished_at: null,
    log_total: 0,
    ...changes,
  };
}

const scope = { checked: false, why: "no_description", outcome: null, key: null, went_on: false, warnings: [] };

function runOf(candidate: string, changes: Record<string, unknown> = {}) {
  return {
    schema: 2,
    candidate,
    state: "ran",
    why: null,
    reason: "",
    at: new Date().toISOString(),
    by: "person",
    proposed: null,
    tool: { name: "normalise", called: "scanpy.pp.normalize_total", tier: "A" },
    arguments: { path: "/data/cells.csv" },
    seconds: 2.4,
    result: { type: "list", plain: true, chars: 5200, start: "[1, 2, 3", cut: true },
    printed: null,
    data: { own: "cells.csv", path: "/data/cells.csv", files: 1, bytes: 34, fingerprint: "f".repeat(64), complete: true },
    scope,
    method: { agent: "agent-1", commit: "abcdef1", image_id: "sha256:1" },
    since: [],
    ...changes,
  };
}

test("shows the methods side by side before any is run, with nothing scored as nothing, and a table to open in a spreadsheet", async ({ page }) => {
  await addData(page, "cells.csv", CELLS);
  await addData(page, "truth.csv", TRUTH);
  const id = await makeBakeoff(page, { data: "cells.csv", labels: { own: "truth.csv", column: "label", id_column: "cell" } });
  await addMethod(page, id, { paper: { kind: "doi", doi: SCANPY }, name: "Scanpy" });
  await addMethod(page, id, { paper: { kind: "url", url: ARXIV }, name: "Arxiv one" });
  await openBakeoff(page, id);

  // Nothing is built, so nothing can be run, and nothing is at work
  await expect(page.getByTestId("bakeoff-run-none")).toContainText("No method is built, so none can be run");
  await expect(running(page)).toHaveCount(0);
  await expect(runWork(page)).toHaveCount(0);

  // The table says that the methods were held to the right answers, and that none could be, and why
  await expect(page.getByTestId("compare-says")).toContainText("The methods were held to the right answers that the person gave, which are their word");
  await expect(page.getByTestId("compare-outcomes")).toContainText("2 methods: 2 not built.");
  await expect(page.getByTestId("compare-outcomes")).toContainText("$0.00 of $2.00 spent");
  await expect(page.getByTestId("compare-truth")).toContainText('truth.csv, the answers in "label", with what each is the answer to in "cell".');
  await expect(page.getByTestId("compare-truth")).toContainText("2 rows, 2 with an answer.");
  await expect(page.getByTestId("compare-truth")).toContainText("No method could be held to them, so none is ranked.");
  const scanpy = page.getByTestId("compare-method").filter({ hasText: "Scanpy" });
  await expect(scanpy).toHaveAttribute("data-state", "not_built");
  await expect(scanpy).toContainText("Not built");
  // Not scored is not a score of nothing
  await expect(scanpy.getByTestId("compare-score")).toContainText("Not scored.");
  await expect(scanpy.getByTestId("compare-score")).not.toContainText(/\d+ of \d+/);
  await expect(scanpy.getByTestId("compare-rank")).toHaveText("Not ranked");
  await expect(page.getByTestId("compare-pairs-none")).toContainText("Fewer than two methods gave an answer");
  await page.getByText("What agreeing, and a score, mean").click();
  await expect(page.getByTestId("compare-meaning")).toContainText("does not make the answer right");
  expect(await accessibilityProblems(page)).toEqual([]);

  // The tolerance is said back, and what is typed is checked before the table is asked for again
  await expect(page.getByTestId("compare-tolerance")).toContainText("within 0.000001 of the larger of the two");
  const tolerance = page.getByRole("form", { name: "How closely numbers must agree" });
  await expect(tolerance.getByRole("button", { name: "Compare again with these" })).toBeDisabled();
  await tolerance.getByLabel("As a part of the larger number").fill("1");
  await tolerance.getByLabel("For two numbers near zero").fill("-3");
  await tolerance.getByRole("button", { name: "Compare again with these" }).click();
  await expect(tolerance.getByRole("alert").filter({ hasText: "relative tolerance" })).toContainText(/less than 1/i);
  await expect(tolerance.getByRole("alert").filter({ hasText: /is a number that is not negative/ })).toBeVisible();
  const asked: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes(`/api/bakeoffs/${id}/comparison`)) asked.push(request.url());
  });
  await expect.poll(() => asked.length).toBe(0);
  await tolerance.getByLabel("As a part of the larger number").fill("0.01");
  await tolerance.getByLabel("For two numbers near zero").fill("");
  const again = page.waitForRequest((request) => request.url().includes(`/api/bakeoffs/${id}/comparison?relative=0.01`));
  await tolerance.getByRole("button", { name: "Compare again with these" }).click();
  await again;
  await expect(page.getByTestId("compare-tolerance")).toContainText("within 0.01 of the larger of the two");
  await expect(page.getByRole("button", { name: "Go back to what it was" })).toBeVisible();

  // The tables are the server's own, made with the tolerance that is asked for
  const link = page.getByRole("link", { name: "Download as a table, the methods" });
  await expect(link).toHaveAttribute("href", `/api/bakeoffs/${id}/tables/methods?relative=0.01`);
  const table = await page.request.get((await link.getAttribute("href")) ?? "");
  expect(table.status()).toBe(200);
  expect(table.headers()["content-type"]).toContain("text/csv");
  const text = await table.text();
  expect(text.split("\n")[0]).toContain("Method");
  expect(text).toContain("Scanpy");
  expect(text).toContain("Arxiv one");
  await expect(page.getByRole("link", { name: "Download as a table, each two of them" })).toHaveAttribute(
    "href",
    `/api/bakeoffs/${id}/tables/pairs?relative=0.01`,
  );

  await page.getByRole("button", { name: "Go back to what it was" }).click();
  await expect(page.getByTestId("compare-tolerance")).toContainText("within 0.000001 of the larger of the two");
  await expect(link).toHaveAttribute("href", `/api/bakeoffs/${id}/tables/methods`);
});

test("shows the methods side by side without right answers as compared with each other and not ranked", async ({ page }) => {
  const id = await makeBakeoff(page);
  await addMethod(page, id, { paper: { kind: "doi", doi: SCANPY }, name: "Scanpy" });
  await openBakeoff(page, id);

  await expect(page.getByTestId("compare-says")).toContainText("the methods are compared with each other and are not ranked");
  await expect(page.getByTestId("compare-says")).toContainText("Agreeing is not being right.");
  await expect(page.getByTestId("compare-truth")).toHaveCount(0);
  await expect(page.getByRole("columnheader", { name: "Against the right answers" })).toHaveCount(0);
  await expect(page.getByRole("columnheader", { name: "Rank" })).toHaveCount(0);
  await expect(page.getByText("Say which of your data the methods are run on")).toBeVisible();
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("runs the methods that are built: what the person says is checked first, and what is sent is each call and the minutes", async ({ page }) => {
  await addData(page, "cells.csv", CELLS);
  const id = await makeBakeoff(page, { data: "cells.csv" });
  const first = await addMethod(page, id, { paper: { kind: "doi", doi: SCANPY }, name: "Scanpy" });
  const second = await addMethod(page, id, { paper: { kind: "url", url: ARXIV }, name: "Arxiv one" });
  const third = await addMethod(page, id, { paper: { kind: "doi", doi: "10.1000/third" }, name: "Third" });
  let started: ReturnType<typeof jobOf> | null = null;
  await showing(page, id, (view) => ({
    ...view,
    job: started,
    candidates: view.candidates.map((each) => (each.id === first ? { ...each, ...built("agent-1") } : each.id === second ? { ...each, ...built("agent-2") } : each)),
  }));
  await withTools(page, "agent-1", ["normalise", "cluster"]);
  await withTools(page, "agent-2", ["annotate"]);
  await page.route("**/api/setup/jobs", (route) => (route.request().method() === "GET" ? route.fulfill({ json: { jobs: started === null ? [] : [started] } }) : route.fallback()));
  const asked: Record<string, unknown>[] = [];
  let refuse = true;
  await page.route(`**/api/bakeoffs/${id}/run`, (route) => {
    asked.push(route.request().postDataJSON());
    if (refuse) {
      return route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "docker_missing", message: "Docker is not running, and running a method takes it." } }),
      });
    }
    started = jobOf(id);

    return route.fulfill({ status: 202, json: started });
  });
  await openBakeoff(page, id);

  // Only a method that is built is offered, and none is chosen to start with
  await expect(rows(page)).toHaveCount(2);
  await expect(rowOf(page, "Third")).toHaveCount(0);
  await expect(page.getByText("No method is built")).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: /Run Scanpy/ })).not.toBeChecked();
  // The button says how many it will run, so it is found by what every one of its names begins with
  const run = running(page).getByRole("button", { name: /^Run (the methods|\d+ methods?)$/ });
  await run.click();
  await expect(running(page).getByText("Choose at least one method to run.")).toBeVisible();
  expect(asked).toEqual([]);

  // A method that is chosen has its tools to choose from, and what a tool takes is said
  await page.getByRole("checkbox", { name: /Run Scanpy/ }).check();
  const scanpy = rowOf(page, "Scanpy");
  await expect(scanpy.getByRole("radio", { name: "I choose the tool and its arguments" })).toBeChecked();
  const tool = scanpy.getByLabel("Its tool");
  await expect(tool.getByRole("option")).toHaveText(["Choose a tool", "normalise (tier A)", "cluster (tier A)"]);
  await tool.selectOption("normalise");
  const takes = scanpy.getByRole("list", { name: "What normalise takes" });
  await expect(takes).toContainText("path: str");
  await expect(takes).toContainText("needed");
  await expect(takes).toContainText("target_sum: float = None");
  await expect(scanpy.getByTestId("tool-signature")).toContainText("normalise makes the counts comparable.");
  await expect(scanpy.getByTestId("tool-signature")).toContainText("2 calls, each made again 2 times, gave what the tutorial got every time. 1 other call could not be made again.");
  await expect(scanpy.getByRole("textbox", { name: "Its arguments" })).toHaveAttribute("aria-describedby", /hint/);
  await expect(scanpy.getByText(`Your data is at /data/cells.csv`)).toBeVisible();

  // What is wrong with the arguments is said, and nothing is sent
  const args = scanpy.getByRole("textbox", { name: "Its arguments" });
  for (const [typed, said] of [
    ["{path: 1}", "The arguments are JSON"],
    ["[1, 2]", "The arguments are an object"],
    ['{"target_sum": 3.0}', "Write it as 3"],
    ['{"target_sum": 12345678901234567890}', "too many digits"],
  ] as const) {
    await args.fill(typed);
    await run.click();
    await expect(scanpy.getByText(said)).toBeVisible();
  }
  expect(asked).toEqual([]);
  await args.fill("");
  await scanpy.getByLabel("Its tool").selectOption("");
  await run.click();
  await expect(scanpy.getByText("Choose which of Scanpy's tools to call.")).toBeVisible();
  await scanpy.getByLabel("Its tool").selectOption("normalise");
  await args.fill('{"path": "/data/cells.csv"}');
  await expect(scanpy.getByText("Choose which of Scanpy's tools")).toHaveCount(0);

  // A call that a model proposes is paid for out of the limit, which is said, and is not given a tool or arguments
  await page.getByRole("checkbox", { name: /Run Arxiv one/ }).check();
  const arxiv = rowOf(page, "Arxiv one");
  await arxiv.getByRole("radio", { name: /A model proposes the call/ }).check();
  await expect(arxiv.getByTestId("run-propose-note")).toContainText("and not your data");
  await expect(arxiv.getByLabel("Its tool")).toHaveCount(0);
  await expect(page.getByTestId("run-spending")).toContainText("1 model call will be paid for out of the limit");
  await expect(page.getByTestId("run-spending")).toContainText("$2.00 is left of $2.00.");
  const runTwo = running(page).getByRole("button", { name: "Run 2 methods" });
  await expect(runTwo).toBeVisible();

  await running(page).getByLabel("The most minutes one call may take").fill("0");
  await runTwo.click();
  await expect(running(page).getByText("The most minutes that a call may take is a whole number from 1 to 30.")).toBeVisible();
  expect(asked).toEqual([]);
  await running(page).getByLabel("The most minutes one call may take").fill("10");
  expect(await accessibilityProblems(page)).toEqual([]);

  // What the server refuses for is said, and what was said is kept to be sent again
  await runTwo.click();
  await expect(page.getByRole("alert").filter({ hasText: "Docker is not running, and running a method takes it." })).toBeVisible();
  expect(asked).toEqual([{ calls: { [first]: { tool: "normalise", arguments: { path: "/data/cells.csv" } }, [second]: { propose: true } }, minutes: 10 }]);
  await expect(runWork(page)).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: /Run Scanpy/ })).toBeChecked();

  refuse = false;
  await runTwo.click();
  await expect.poll(() => asked.length).toBe(2);
  expect(asked[1]).toEqual(asked[0]);
  await expect(runWork(page)).toContainText("Running the methods: Cell types");
  await expect(runWork(page)).toContainText("Running");
  // Running is shown where it is run, and not where the methods are built
  await expect(methodWork(page)).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: /Run Scanpy/ })).toBeDisabled();
  await expect(runTwo).toBeDisabled();
  await expect(running(page).getByLabel("The most minutes one call may take")).not.toBeEditable();
  await expect(page.getByRole("button", { name: /^Build (all|it|the )/ })).toBeDisabled();
  expect(third).not.toBe(first);
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("shows what came of the last run of each method: what ran, on what, who chose it, and the start of what it gave, and the whole of it on asking", async ({ page }) => {
  await addData(page, "cells.csv", CELLS);
  const id = await makeBakeoff(page, { data: "cells.csv" });
  const ran = await addMethod(page, id, { paper: { kind: "doi", doi: SCANPY }, name: "Scanpy" });
  const failed = await addMethod(page, id, { paper: { kind: "url", url: ARXIV }, name: "Arxiv one" });
  const outside = await addMethod(page, id, { paper: { kind: "doi", doi: "10.1000/third" }, name: "Third" });
  const proposed = await addMethod(page, id, { paper: { kind: "doi", doi: "10.1000/fourth" }, name: "Fourth" });
  const runs: Record<string, ReturnType<typeof runOf>> = {
    [ran]: runOf(ran, { since: ["data"] }),
    [failed]: runOf(failed, {
      state: "failed",
      why: "timed_out",
      reason: "It was stopped after 300 seconds, which is as long as a call was allowed.",
      result: null,
      seconds: 300,
      printed: "loading the counts\nstill loading",
    }),
    [outside]: runOf(outside, {
      state: "not_run",
      why: "outside",
      reason: "The data is outside what the method card of this method's paper says it was used on, and you have not said to go on.",
      tool: null,
      arguments: null,
      seconds: null,
      result: null,
      data: null,
      method: null,
      scope: { ...scope, checked: true, outcome: "outside", warnings: ["The card says mouse, and your data is human."] },
    }),
    [proposed]: runOf(proposed, {
      by: "model",
      proposed: { model: "test/model", reason: "It takes the counts and the data is counts.", cost: 0.0123, tool: "annotate", arguments: "{}" },
      result: { type: "dict", plain: false, chars: 900000, start: '{"type": "dict", "chars": 900000', cut: false },
      method: { agent: "agent-4", commit: "abcdef1", image_id: "sha256:1" },
      since: ["method"],
    }),
  };
  await showing(page, id, (view) => ({
    ...view,
    candidates: view.candidates.map((each) => (each.id === ran ? { ...each, ...built("agent-1"), run: runs[ran] } : { ...each, run: runs[each.id] })),
  }));
  await withTools(page, "agent-1", ["normalise"]);
  const whole = { ...runs[ran], result: { type: "list", value: [1, 2, 3, 4] } };
  let asked = 0;
  await page.route(`**/api/bakeoffs/${id}/candidates/${ran}/run`, (route) => {
    asked += 1;

    return route.fulfill({ json: whole });
  });
  await openBakeoff(page, id);

  const ofRan = lastRunOf(page, ran);
  await expect(ofRan.getByTestId("run-state")).toHaveText("Ran");
  await expect(ofRan).toContainText("It called normalise, a tool of tier A, which calls scanpy.pp.normalize_total in the code of its paper.");
  await expect(ofRan).toContainText("You chose the call.");
  await expect(ofRan).toContainText("It was run on cells.csv, at /data/cells.csv: 1 file, 34 B.");
  await expect(ofRan).toContainText("Your data was not put against a card");
  await expect(ofRan).toContainText("It took 2.4 s.");
  await expect(ofRan.getByTestId("run-since")).toContainText("Your data is not as it was when this ran");
  await expect(ofRan).toContainText("It does not say that what it gave is right.");
  await ofRan.getByText("The arguments it was called with").click();
  await expect(ofRan.getByText('"path": "/data/cells.csv"')).toBeVisible();
  await expect(ofRan.getByTestId("run-result")).toContainText("A list, 5,200 characters as JSON.");
  await expect(ofRan.getByLabel("The start of what it gave")).toHaveText("[1, 2, 3…");
  expect(asked).toBe(0);
  await ofRan.getByRole("button", { name: "Show all that was kept of it" }).click();
  await expect(ofRan.getByTestId("run-result-whole")).toContainText('"value": [');
  await expect(ofRan.getByTestId("run-result")).toContainText("All of it was kept.");
  expect(asked).toBe(1);
  await ofRan.getByRole("button", { name: "Show only the start" }).click();
  await expect(ofRan.getByLabel("The start of what it gave")).toBeVisible();

  const ofFailed = lastRunOf(page, failed);
  await expect(ofFailed.getByTestId("run-state")).toHaveText("Failed");
  await expect(ofFailed).toContainText("It ran out of time");
  await expect(ofFailed).toContainText("It was stopped after 300 seconds");
  await expect(ofFailed).toContainText("It took 5 min.");
  await expect(ofFailed.getByTestId("run-result")).toHaveCount(0);
  await ofFailed.getByText("What it printed").click();
  await expect(ofFailed.getByText("still loading")).toBeVisible();

  const ofOutside = lastRunOf(page, outside);
  await expect(ofOutside.getByTestId("run-state")).toHaveText("Not run");
  await expect(ofOutside).toContainText("Your data is outside what its card says");
  await expect(ofOutside).toContainText("you have not said to go on");
  await expect(ofOutside).toContainText("Your data was outside what its card says.");
  await expect(ofOutside).toContainText("The card says mouse, and your data is human.");
  await expect(ofOutside).not.toContainText("It called");

  const ofProposed = lastRunOf(page, proposed);
  await expect(ofProposed).toContainText("test/model proposed the call, and a program checked it as it checks yours. Asking it cost $0.01.");
  await expect(ofProposed.getByTestId("run-proposed-reason")).toContainText("It takes the counts and the data is counts.");
  await expect(ofProposed.getByTestId("run-since")).toContainText("The method was built again");
  await expect(ofProposed.getByTestId("run-result")).toContainText("It was more than could be kept as it was");
  expect(await accessibilityProblems(page)).toEqual([]);
});

test("puts the methods side by side with their scores, ranks, and agreement, and says where a score is not one", async ({ page }) => {
  await addData(page, "cells.csv", CELLS);
  await addData(page, "truth.csv", TRUTH);
  const id = await makeBakeoff(page, { data: "cells.csv", labels: { own: "truth.csv", column: "label", id_column: "cell" } });
  const a = await addMethod(page, id, { paper: { kind: "doi", doi: SCANPY }, name: "Scanpy" });
  const b = await addMethod(page, id, { paper: { kind: "url", url: ARXIV }, name: "Arxiv one" });
  const c = await addMethod(page, id, { paper: { kind: "doi", doi: "10.1000/third" }, name: "Third" });
  const d = await addMethod(page, id, { paper: { kind: "doi", doi: "10.1000/fourth" }, name: "Fourth" });
  const e = await addMethod(page, id, { paper: { kind: "doi", doi: "10.1000/fifth" }, name: "Fifth" });
  const unscored = (why: string, reason: string) => ({
    scored: false,
    why,
    reason,
    by: null,
    matched: null,
    of: null,
    score: null,
    missing: null,
    extra: null,
    examples: [],
    rank: null,
  });
  const scored = (matched: number, rank: number, changes: Record<string, unknown> = {}) => ({
    scored: true,
    why: null,
    reason: "",
    by: "id",
    matched,
    of: 10,
    score: matched / 10,
    missing: 0,
    extra: 0,
    examples: [],
    rank,
    ...changes,
  });
  const row = (id: string, name: string, changes: Record<string, unknown> = {}) => ({
    id,
    name,
    title: "",
    agent: null,
    state: "ran",
    why: null,
    reason: "",
    tier: "A",
    tool: "annotate",
    seconds: 1.5,
    cost: { reading: 0.4, asking: 0 },
    by: "person",
    kept: "whole",
    since: [],
    score: null,
    agrees: [],
    differs: [],
    unknown: [],
    ...changes,
  });
  const comparison = (tolerance: { relative: number; absolute: number }) => ({
    id,
    title: "Cell types",
    task: TASK,
    limit: 2,
    spent: 0.4,
    cost_known: true,
    tolerance,
    ground_truth: {
      own: "truth.csv",
      column: "label",
      id_column: "cell",
      ok: true,
      why: null,
      problem: null,
      bytes: 22,
      in_data: false,
      says: "",
      rows: 10,
      labelled: 9,
      unlabelled: 1,
      sha256: "0123456789abcdef".repeat(4),
    },
    ranked: true,
    says: "The methods were held to the right answers that the person gave.",
    meaning: "Methods that agree gave the same answer as far as what was kept of it shows.",
    methods: [
      row(a, "Scanpy", { agrees: [b], unknown: [e], score: scored(8, 1, { missing: 1, extra: 2, examples: ["cell c7 was T, not B"] }), since: ["data"] }),
      row(b, "Arxiv one", { agrees: [a], by: "model", cost: { reading: 0.4, asking: 0.0123 }, score: scored(8, 1) }),
      row(c, "Third", { state: "failed", why: "timed_out", reason: "It was stopped after 300 seconds.", tier: null, tool: null, kept: null, score: unscored("no_answer", "It gave no answer, so there is nothing to hold to the labels.") }),
      row(d, "Fourth", { state: "not_built", why: "waiting", reason: "It is waiting for you.", tier: null, tool: null, seconds: null, cost: { reading: null, asking: null }, by: null, kept: null, score: unscored("no_answer", "It gave no answer, so there is nothing to hold to the labels.") }),
      row(e, "Fifth", { kept: "hash", unknown: [a], score: unscored("not_kept", "Only a hash of its answer was kept.") }),
    ],
    pairs: [
      { first: a, second: b, verdict: "agree", how: "The two results are equal within the tolerance.", differences: [], kept: ["whole", "whole"] },
      { first: a, second: e, verdict: "unknown", how: "Only a hash of one answer was kept.", differences: [], kept: ["whole", "hash"] },
      { first: b, second: e, verdict: "differ", how: "The results differ.", differences: ["the result[0] is 1 against 2"], kept: ["whole", "whole"] },
    ],
  });
  const urls: string[] = [];
  await page.route(`**/api/bakeoffs/${id}/comparison*`, (route: Route) => {
    urls.push(route.request().url());
    const asked = new URL(route.request().url()).searchParams;

    return route.fulfill({ json: comparison({ relative: Number(asked.get("relative") ?? 1e-6), absolute: Number(asked.get("absolute") ?? 1e-9) }) });
  });
  await openBakeoff(page, id);

  await expect(page.getByTestId("compare-outcomes")).toContainText("5 methods: 3 ran, 1 failed, 1 not built.");
  await expect(page.getByTestId("compare-outcomes")).toContainText("$0.40 of $2.00 spent");
  await expect(page.getByTestId("compare-truth")).toContainText("10 rows, 9 with an answer, and 1 had none.");
  await expect(page.getByTestId("compare-truth")).toContainText("The file is the one with the hash 0123456789ab");

  // Methods that matched the same number share a rank, and a method that was not scored is not ranked, and is not given a score of nothing
  await expect(comparedRow(page, a).getByTestId("compare-score")).toContainText("8 of 10 (80%)");
  await expect(comparedRow(page, a).getByTestId("compare-score")).toContainText("matched to the labels by what each is the answer to");
  await expect(comparedRow(page, a).getByTestId("compare-score")).toContainText("1 label had no answer from it, and each counts as wrong.");
  await expect(comparedRow(page, a).getByTestId("compare-score")).toContainText("2 answers had no label, and were not counted.");
  await expect(comparedRow(page, a).getByTestId("compare-rank")).toHaveText("1st, shared");
  await expect(comparedRow(page, b).getByTestId("compare-rank")).toHaveText("1st, shared");
  for (const unranked of [c, d, e]) {
    await expect(comparedRow(page, unranked).getByTestId("compare-rank")).toHaveText("Not ranked");
    await expect(comparedRow(page, unranked).getByTestId("compare-score")).toContainText("Not scored.");
    await expect(comparedRow(page, unranked).getByTestId("compare-score")).not.toContainText(/\d+ of \d+/);
  }
  await expect(comparedRow(page, e).getByTestId("compare-score")).toContainText("Only a hash of its answer was kept.");
  await comparedRow(page, a).getByText("Some it got wrong").click();
  await expect(comparedRow(page, a)).toContainText("cell c7 was T, not B");

  // How each came out, what it cost, who chose the call, and what is not as it was
  await expect(comparedRow(page, c)).toHaveAttribute("data-why", "timed_out");
  await expect(comparedRow(page, c)).toContainText("Failed");
  await expect(comparedRow(page, c)).toContainText("It ran out of time");
  await expect(comparedRow(page, d)).toContainText("Not built");
  await expect(comparedRow(page, d)).toContainText("Waiting for you");
  await expect(comparedRow(page, a)).toContainText("annotate");
  await expect(comparedRow(page, a)).toContainText("tier A");
  await expect(comparedRow(page, a)).toContainText("You");
  await expect(comparedRow(page, a).getByTestId("compare-since")).toContainText("Your data is not as it was when it ran");
  await expect(comparedRow(page, b)).toContainText("A model");
  await expect(comparedRow(page, b)).toContainText("$0.01");
  await expect(comparedRow(page, a)).toContainText("$0.40");
  await expect(comparedRow(page, a)).toContainText("None, your call");
  await expect(comparedRow(page, e)).toContainText("Its size and a hash");

  // Which methods agree is said by name, and what is not known is said not to be
  await expect(comparedRow(page, a)).toContainText("Agrees with Arxiv one");
  await expect(comparedRow(page, a)).toContainText("Not known against Fifth");
  const pairs = page.getByTestId("compare-pair");
  await expect(pairs).toHaveCount(3);
  await expect(pairs.nth(0)).toContainText("Scanpy");
  await expect(pairs.nth(0)).toHaveAttribute("data-verdict", "agree");
  await expect(pairs.nth(1)).toHaveAttribute("data-verdict", "unknown");
  await expect(pairs.nth(1)).toContainText("Not known");
  await expect(pairs.nth(1)).toContainText("First: all of it was kept. Second: only its size and a hash were kept");
  await expect(pairs.nth(2)).toHaveAttribute("data-verdict", "differ");
  await expect(pairs.nth(2)).toContainText("the result[0] is 1 against 2");
  expect(await accessibilityProblems(page)).toEqual([]);

  // Asking again with a tolerance asks the server with it
  const tolerance = page.getByRole("form", { name: "How closely numbers must agree" });
  await tolerance.getByLabel("For two numbers near zero").fill("0.5");
  await tolerance.getByRole("button", { name: "Compare again with these" }).click();
  await expect.poll(() => urls.some((url) => url.includes("absolute=0.5"))).toBe(true);
  expect(urls.filter((url) => url.includes("absolute=0.5")).every((url) => !url.includes("relative="))).toBe(true);
  await expect(page.getByTestId("compare-tolerance")).toContainText("or within 0.5 of each other");
});
