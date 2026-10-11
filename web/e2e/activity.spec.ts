import { answered, askWhereCodeRuns, expect, test } from "./fixtures";

const calls = (page: import("@playwright/test").Page) => page.getByTestId("call");
const cells = (page: import("@playwright/test").Page) => page.getByTestId("code-cell");

test.describe("code the lead runs", () => {
  test("code that ran is shown with what it printed, and the lead goes on to answer", async ({ page }) => {
    await askWhereCodeRuns(page, "code:hello please");
    await answered(page, "That is done: 1 step ran.", 30_000);

    await expect(page.getByTestId("steps")).toContainText("Let me run that.");
    await expect(calls(page)).toHaveCount(1);
    await expect(calls(page)).toHaveAttribute("data-status", "done");
    await expect(calls(page)).toContainText("Ran Python code");
    await expect(cells(page)).toHaveCount(1);
    await expect(cells(page)).toHaveAttribute("data-status", "ok");
    await expect(cells(page)).toContainText('print("hello from the session")');
    await expect(cells(page)).toContainText(/Ran in/);
    await expect(page.getByTestId("code-output")).toHaveText("hello from the session");
  });

  test("code is coloured by what its parts are", async ({ page }) => {
    await askWhereCodeRuns(page, "code:hello please");
    await answered(page, "That is done: 1 step ran.", 30_000);

    await expect(cells(page).locator("code .hljs-built_in", { hasText: "print" })).toHaveCount(1);
    await expect(cells(page).locator("code .hljs-string")).toContainText("hello from the session");
  });

  test("code that failed says how, and the lead goes on to answer", async ({ page }) => {
    await askWhereCodeRuns(page, "code:error please");
    await answered(page, "That is done: 1 step ran.", 30_000);

    await expect(cells(page)).toHaveAttribute("data-status", "error");
    await expect(cells(page)).toContainText(/Failed after/);
    const output = page.getByTestId("code-output");
    await expect(output).toContainText("about to fail");
    await expect(output).toContainText("Traceback");
    await expect(output).toContainText("ZeroDivisionError: division by zero");
    // Colour codes in a traceback are not shown as the characters they are made of
    await expect(output).not.toContainText("\u001b");
    await expect(output).not.toContainText("[31m");
    // The error is not said a second time, below a traceback that has it
    await expect(cells(page).getByRole("alert")).toHaveCount(0);
  });

  test("code that ran twice is shown twice, in order, and the second knows what the first did", async ({ page }) => {
    await askWhereCodeRuns(page, "code:two please");
    await answered(page, "That is done: 2 steps ran.", 30_000);

    await expect(calls(page)).toHaveCount(2);
    await expect(page.getByTestId("steps")).toContainText(/First, one thing\.[\s\S]*Now the next\./);
    await expect(page.getByTestId("code-output")).toHaveText(["first 20", "second 42"]);
  });

  test("a figure it drew is shown, and a file it made is a link to the file", async ({ page }) => {
    const id = await askWhereCodeRuns(page, "code:plot please");
    await answered(page, "That is done: 1 step ran.", 30_000);

    const figure = cells(page).getByRole("group", { name: "Figures" }).getByRole("img");
    await expect(figure).toHaveCount(1);
    await expect.poll(() => figure.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
    await expect(figure).toHaveAttribute("src", new RegExp(`^/api/chats/${id}/files/plots/`));

    const made = cells(page).getByRole("list", { name: "Files it made" });
    await expect(made.getByRole("link")).toHaveCount(1);
    await expect(made.getByRole("link", { name: "results.csv" })).toHaveAttribute("href", `/api/chats/${id}/files/results.csv`);
    const file = await page.request.get(`/api/chats/${id}/files/results.csv`);
    expect(await file.text()).toContain("TP53,0.91");
  });

  test("a figure that cannot be loaded says so, in its place", async ({ page }) => {
    await page.route("**/files/plots/**", (route) => route.abort());
    await askWhereCodeRuns(page, "code:plot please");
    await answered(page, "That is done: 1 step ran.", 30_000);

    await expect(cells(page).getByRole("img")).toHaveCount(0);
    await expect(cells(page)).toContainText("plots/figure_1.png is not available");
  });

  test("output too long to keep says what was left out, and is scrolled in a box of its own", async ({ page }) => {
    await askWhereCodeRuns(page, "code:big please");
    await answered(page, "That is done: 1 step ran.", 30_000);

    const output = page.getByTestId("code-output");
    await expect(output).toContainText(/The middle of the output, [\d,]+ bytes, is left out\./);
    await expect(output).toContainText("row 00000");
    await expect(output).toContainText("row 02499");
    const box = await output.evaluate((element) => ({ shown: element.clientHeight, whole: element.scrollHeight }));
    expect(box.shown).toBeLessThanOrEqual(330);
    expect(box.whole).toBeGreaterThan(box.shown);
  });

  test("code that is running says so, and says how long it took when it is done", async ({ page }) => {
    await askWhereCodeRuns(page, "code:slow please");

    await expect(calls(page)).toHaveAttribute("data-status", "running");
    await expect(calls(page)).toContainText("Running Python code");
    await expect(calls(page).getByRole("status").filter({ hasText: "Working" }).first()).toBeVisible();
    await expect(cells(page)).toHaveAttribute("data-status", "running");
    await expect(cells(page).getByRole("status")).toContainText("Running");

    await answered(page, "That is done: 1 step ran.", 30_000);
    await expect(calls(page)).toHaveAttribute("data-status", "done");
    await expect(cells(page)).toContainText(/Ran in 3(\.\d)? ?s/);
    await expect(page.getByTestId("code-output")).toHaveText("slept");
  });

  test("a turn stopped while code runs keeps what the code did, and says it was stopped", async ({ page }) => {
    await askWhereCodeRuns(page, "code:slow please");
    await expect(calls(page)).toHaveAttribute("data-status", "running");

    await page.getByRole("button", { name: "Stop" }).click();

    await expect(page.getByRole("status").filter({ hasText: /stopped/i })).toBeVisible({ timeout: 30_000 });
    // The code is let finish, so that the session is not left in a state the lead does not know of
    await expect(calls(page)).toHaveAttribute("data-status", "done");
    await expect(cells(page)).toHaveAttribute("data-status", "ok");
    await expect(page.getByTestId("code-output")).toHaveText("slept");
    await expect(calls(page).getByRole("status")).toHaveCount(0);
    await expect(page.getByTestId("lead-message")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
  });

  test("what ran is there when the page is opened again", async ({ page }) => {
    await askWhereCodeRuns(page, "code:two please");
    await answered(page, "That is done: 2 steps ran.", 30_000);

    await page.reload();

    await expect(page.getByTestId("lead-message").last()).toContainText("That is done: 2 steps ran.");
    await expect(calls(page)).toHaveCount(2);
    await expect(page.getByTestId("code-output")).toHaveText(["first 20", "second 42"]);
    await expect(page.locator('[data-testid="code-cell"][data-status="ok"]')).toHaveCount(2);
  });

  test("a long script is folded, and opens to show all of it", async ({ page }) => {
    await askWhereCodeRuns(page, "code:long please");
    await answered(page, "That is done: 1 step ran.", 30_000);

    const cell = cells(page);
    await expect(cell).toContainText("step_14 = 14 * 2");
    await expect(cell).not.toContainText("step_15 = 15 * 2");
    const more = cell.getByRole("button", { name: "Show 17 more lines" });
    await expect(more).toHaveAttribute("aria-expanded", "false");

    await more.click();

    await expect(cell).toContainText("print('ran', step_30)");
    await expect(cell.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
    await cell.getByRole("button", { name: "Show less" }).click();
    await expect(cell).not.toContainText("step_15 = 15 * 2");
  });

  test("the code can be copied", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await askWhereCodeRuns(page, "code:long please");
    await answered(page, "That is done: 1 step ran.", 30_000);

    await cells(page).getByRole("button", { name: "Copy code" }).click();

    await expect(cells(page).getByRole("button", { name: "Copied" })).toBeVisible();
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    // All of it is copied, and not only what is shown before it is folded
    expect(copied).toContain("step_1 = 1 * 2");
    expect(copied).toContain("print('ran', step_30)");
    await expect(cells(page).getByRole("button", { name: "Copy code" })).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("what else the lead does", () => {
  test("a tool that is called is shown closed, and opens to what it was asked and what it gave back", async ({ page }) => {
    await askWhereCodeRuns(page, "tool:unknown please");
    await answered(page, "That is done: 1 step ran.", 30_000);

    const call = calls(page);
    await expect(call).toHaveCount(1);
    await expect(call).toContainText("Called mystery_tool");
    await expect(call).toContainText('{"target": "TP53"}');
    await expect(call).not.toHaveAttribute("open", "");
    await expect(call.getByText("Asked", { exact: true })).toBeHidden();

    await call.locator("summary").click();

    await expect(call).toHaveAttribute("open", "");
    await expect(call.getByText("Asked", { exact: true })).toBeVisible();
    await expect(call).toContainText('"target": "TP53"');
    await expect(call.getByText("Result", { exact: true })).toBeVisible();
  });

  test("what the lead was told it has to work with is shown, and a search for more is too", async ({ page }) => {
    await askWhereCodeRuns(page, "tool:resources please");
    await answered(page, "That is done: 1 step ran.", 30_000);

    // What a search for resources tells is written to be read, so it is shown as the page it is written as
    await calls(page).locator("summary").click();
    await expect(calls(page).getByRole("heading", { name: "sgRNA Design Guide: Three-Tiered Approach" })).toBeVisible();

    const resources = page.getByTestId("resources");
    await expect(resources.first()).toContainText("Resources it can look up");
    await expect(resources.first()).toContainText("2 know-how documents");
    await resources.first().locator("summary").click();
    await expect(resources.first()).toContainText("Nothing is named.");
    await expect(calls(page)).toContainText("Looked up resources");
    await expect(calls(page)).toContainText("Score a gene's expression");
    await expect(resources.last()).toContainText("Chose resources for a task");
    await expect(resources.last()).toContainText("2 know-how documents");

    await resources.last().locator("summary").click();
    await expect(resources.last().getByRole("list").first().getByRole("listitem")).toHaveCount(2);
  });
});
