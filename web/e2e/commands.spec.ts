import type { Locator, Page } from "@playwright/test";
import { accessibilityProblems, pastTheEdge } from "./axe";
import { answered, ask, askWhereCodeRuns, expect, HOME_HEADING, test } from "./fixtures";

const box = (page: Page) => page.getByRole("textbox", { name: "Message" });
// The box by what it is made of, which is found where a dialog hides the page from what is found by its role
const rawBox = (page: Page) => page.locator('textarea[aria-label="Message"]');
const menu = (page: Page) => page.getByTestId("slash-menu");
const options = (page: Page) => menu(page).getByTestId("slash-option");
const lit = (page: Page) => menu(page).locator('[aria-selected="true"]');
const state = (page: Page) => page.getByTestId("chat-state");
const dialog = (page: Page) => page.getByTestId("limits-dialog");
const spending = (scope: Locator) => scope.getByRole("textbox", { name: "Spending limit (US dollars)" });
const sessions = (scope: Locator) => scope.getByRole("textbox", { name: "Team sessions in one answer" });
const rounds = (scope: Locator) => scope.getByRole("textbox", { name: "Rounds in a team session" });

// What the menu lists, by the names the lines are given
async function listed(page: Page): Promise<(string | null)[]> {
  return options(page).evaluateAll((lines) => lines.map((line) => line.getAttribute("data-command")));
}

// Sends a message in the conversation that is open, and does not wait for the answer
async function sendMessage(page: Page, text: string): Promise<void> {
  await box(page).fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

// Writes in the box, and runs what is written with Enter
async function command(page: Page, text: string): Promise<void> {
  await box(page).fill(text);
  await box(page).press("Enter");
}

async function chatInfo(page: Page, id: string) {
  const response = await page.request.get(`/api/chats/${id}`);
  expect(response.status()).toBe(200);

  return response.json();
}

test.describe("the menu of commands", () => {
  test("a slash lists the commands of the page, which narrow as more is written, and Escape puts the list away", async ({ page }) => {
    await expect(menu(page)).toHaveCount(0);

    await box(page).fill("/");
    // What cannot be chosen is listed last, and where code is off, that is what asks for it
    await expect.poll(() => listed(page)).toEqual(["/ask", "/plan", "/search", "/lab", "/budget", "/model", "/help", "/code", "/plot"]);
    await expect(lit(page)).toHaveAttribute("data-command", "/ask");
    await expect(box(page)).toBeFocused();

    await box(page).fill("/mod");
    await expect.poll(() => listed(page)).toEqual(["/model"]);
    await box(page).press("Escape");
    await expect(menu(page)).toHaveCount(0);
    await expect(box(page)).toHaveValue("/mod");

    // Writing more brings it back
    await box(page).press("e");
    await expect.poll(() => listed(page)).toEqual(["/model"]);

    await box(page).fill("/zzz");
    await expect(menu(page)).toHaveCount(0);
  });

  test("the button beside the paperclip opens the list in an empty box, and closes it", async ({ page }) => {
    const button = page.getByTestId("commands-button");
    await button.click();
    await expect(box(page)).toHaveValue("/");
    await expect(menu(page)).toBeVisible();
    await expect(button).toHaveAttribute("aria-pressed", "true");

    await button.click();
    await expect(box(page)).toHaveValue("");
    await expect(menu(page)).toHaveCount(0);

    // Commands are written at the start of an empty box, so with a message begun the button is not for them
    await box(page).fill("A question that is begun");
    await expect(button).toBeDisabled();
  });

  test("a line that begins with a slash and is not a command is a message, as the path of a file is", async ({ page }) => {
    await box(page).fill("/data/counts.csv what is in it");
    await expect(menu(page)).toHaveCount(0);

    await ask(page, "/data/counts.csv what is in it");
    await answered(page, "You asked: /data/counts.csv what is in it");
    await expect(page.getByTestId("user-message")).toHaveText("/data/counts.csv what is in it");
  });

  test("the arrow keys choose, over what cannot be chosen, Tab writes the command out, and Enter runs it", async ({ page }) => {
    await ask(page, "A question to have something to save");
    await answered(page, "You asked: A question to have something to save");

    await box(page).fill("/");
    await expect.poll(() => listed(page)).toEqual([
      "/ask",
      "/plan",
      "/search",
      "/review",
      "/lab",
      "/budget",
      "/model",
      "/rename",
      "/export",
      "/files",
      "/new",
      "/help",
      "/code",
      "/plot",
      "/pause",
      "/resume",
      "/stop",
    ]);
    await expect(lit(page)).toHaveAttribute("data-command", "/ask");
    await box(page).press("ArrowDown");
    await expect(lit(page)).toHaveAttribute("data-command", "/plan");
    await box(page).press("ArrowUp");
    await box(page).press("ArrowUp");
    // Round to the last that can be chosen, which is not one of those that cannot
    await expect(lit(page)).toHaveAttribute("data-command", "/help");
    await expect(options(page).filter({ hasText: "Nothing is running" }).first()).toHaveAttribute("aria-disabled", "true");

    await box(page).fill("/ex");
    await box(page).press("Tab");
    await expect(box(page)).toHaveValue("/export ");
    await expect.poll(() => listed(page)).toEqual(["/export html", "/export pdf", "/export ipynb"]);
    await box(page).fill("/export no");
    await expect.poll(() => listed(page)).toEqual(["/export ipynb"]);

    await command(page, "/help");
    await expect(page.getByTestId("commands-help")).toContainText("/rename");
    await expect(page.getByTestId("commands-help")).toContainText("Save the conversation as a document");
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("commands-help")).toHaveCount(0);
    await expect(box(page)).toHaveValue("");
  });

  test("a command that cannot be run now says why, and is not sent to the lead in place of it", async ({ page }) => {
    await ask(page, "A question before nothing is running");
    await answered(page, "You asked: A question before nothing is running");

    await box(page).fill("/stop");
    await expect(options(page)).toHaveCount(1);
    await expect(options(page).first()).toHaveAttribute("aria-disabled", "true");
    await expect(options(page).first()).toContainText("Nothing is running");
    await expect(lit(page)).toHaveCount(0);

    await box(page).press("Enter");
    await expect(box(page)).toHaveValue("/stop");
    await expect(page.getByTestId("user-message")).toHaveCount(1);

    // Put away, it is a message like any other
    await box(page).press("Escape");
    await box(page).press("Enter");
    await expect(page.getByTestId("user-message")).toHaveCount(2);
    await expect(page.getByTestId("user-message").last()).toHaveText("/stop");
  });
});

test.describe("/budget", () => {
  test("sets the limits of the conversation to begin, which it begins with", async ({ page }) => {
    await command(page, "/budget");

    const panel = dialog(page);
    await expect(panel.getByRole("heading", { name: "Budget and limits" })).toBeVisible();
    await expect(rawBox(page)).toHaveValue("");
    // The settings give a conversation a limit of $2 unless it is told otherwise
    await expect(spending(panel)).toHaveValue("2");
    await expect(sessions(panel)).toHaveValue("3");
    await expect(rounds(panel)).toHaveValue("3");
    await expect(panel.getByTestId("limits-save")).toBeDisabled();

    await spending(panel).fill("0.5");
    await sessions(panel).fill("1");
    await rounds(panel).fill("2");
    await panel.getByTestId("limits-save").click();
    await expect(panel).toHaveCount(0);

    // What was chosen is what the panel opens with, until the conversation begins
    await command(page, "/budget");
    await expect(spending(dialog(page))).toHaveValue("0.5");
    await expect(sessions(dialog(page))).toHaveValue("1");
    await page.keyboard.press("Escape");
    await expect(dialog(page)).toHaveCount(0);

    const id = await ask(page, "A question under a limit");
    await answered(page, "You asked: A question under a limit");
    const info = await chatInfo(page, id);
    expect(info).toMatchObject({ max_cost: 0.5, max_delegations: 1, max_rounds: 2 });
    await expect(page.getByTitle("Spent in this conversation")).toContainText("of $0.50");
  });

  test("says what is wrong with a limit, and asks for nothing until it is put right", async ({ page }) => {
    await command(page, "/budget");
    const panel = dialog(page);

    await spending(panel).fill("plenty");
    await sessions(panel).fill("21");
    await rounds(panel).fill("-1");
    await expect(panel.getByRole("alert")).toHaveText([/amount in dollars/, "A whole number from 0 to 20.", "A whole number from 0 to 10."]);
    await expect(panel.getByTestId("limits-save")).toBeDisabled();

    await spending(panel).fill("3");
    await sessions(panel).fill("20");
    await rounds(panel).fill("10");
    await expect(panel.getByRole("alert")).toHaveCount(0);
    await expect(panel.getByTestId("limits-save")).toBeEnabled();

    // Raised by a dollar or five, from what is there, and taken away
    await panel.getByTestId("raise-5").click();
    await expect(spending(panel)).toHaveValue("8");
    await panel.getByTestId("raise-1").click();
    await expect(spending(panel)).toHaveValue("9");
    await panel.getByTestId("no-limit").click();
    await expect(spending(panel)).toHaveValue("");
    await expect(panel.getByTestId("no-limit")).toBeDisabled();
  });

  test("changes the limits of a conversation while it works, with no note sent to the lead", async ({ page }) => {
    const id = await askWhereCodeRuns(page, "code:slow change the limits while it runs");
    await expect(page.getByText("Running Python code")).toBeVisible();

    // The model is not for changing while the lead works, which the list says, and the budget is
    await box(page).fill("/mo");
    await expect(options(page).first()).toHaveAttribute("aria-disabled", "true");
    await expect(options(page).first()).toContainText("finished");

    await command(page, "/budget");
    const panel = dialog(page);
    await expect(panel.getByRole("heading", { name: "Budget and limits" })).toBeVisible();
    await expect(sessions(panel)).toHaveValue("3");
    await spending(panel).fill("5");
    await sessions(panel).fill("0");
    await panel.getByTestId("limits-save").click();
    await expect(panel).toHaveCount(0);

    const info = await chatInfo(page, id);
    expect(info).toMatchObject({ max_cost: 5, max_delegations: 0, max_rounds: 3 });
    await expect(page.getByTestId("pending-note")).toHaveCount(0);

    await answered(page, "That is done: 1 step ran.", 30_000);
    await expect(page.getByTitle("Spent in this conversation")).toContainText("of $5.00");
    await expect(page.getByTestId("note")).toHaveCount(0);

    // Opened again, it has what it was given
    await command(page, "/budget");
    await expect(spending(dialog(page))).toHaveValue("5");
    await expect(sessions(dialog(page))).toHaveValue("0");
  });

  test("is offered where a turn was stopped by the limit, and raising it lets the conversation go on", async ({ page }) => {
    const made = await page.request.post("/api/chats", { data: { title: "Limit reached", max_cost: 0 } });
    expect(made.status()).toBe(201);
    const id: string = (await made.json()).id;
    await page.goto(`/chat?id=${id}`);

    await box(page).fill("A question that costs something");
    await box(page).press("Enter");
    const notice = page.getByRole("alert").filter({ hasText: "BudgetExceededError" });
    await expect(notice).toBeVisible();
    await notice.getByTestId("raise-limit").click();

    const panel = dialog(page);
    await expect(spending(panel)).toHaveValue("0");
    await expect(panel.getByTestId("limits-save")).toBeDisabled();
    await panel.getByTestId("raise-1").click();
    await expect(spending(panel)).toHaveValue("1");
    await panel.getByTestId("limits-save").click();
    await expect(panel).toHaveCount(0);
    expect(await chatInfo(page, id)).toMatchObject({ max_cost: 1 });

    await box(page).fill("Try again");
    await box(page).press("Enter");
    await answered(page, "You asked: Try again");
    // What stopped the first turn is not offered again once the conversation has gone on
    await expect(page.getByTestId("raise-limit")).toHaveCount(0);
  });

  test("a limit below what is spent says that the lead stops at its next request", async ({ page }) => {
    await ask(page, "A question that is paid for");
    await answered(page, "You asked: A question that is paid for");

    await command(page, "/budget");
    await spending(dialog(page)).fill("0");
    await expect(dialog(page)).toContainText("below what has been spent");
    await spending(dialog(page)).fill("100");
    await expect(dialog(page)).not.toContainText("below what has been spent");
  });
});

test.describe("the commands that stand for what the buttons do", () => {
  test("/rename gives the conversation a new title, and takes nothing without one", async ({ page }) => {
    const id = await ask(page, "A question under its first title");
    await answered(page, "You asked: A question under its first title");

    await box(page).fill("/rename ");
    await expect(options(page).first()).toContainText("Type the new title");
    await box(page).press("Enter");
    await expect(box(page)).toHaveValue("/rename ");

    await command(page, "/rename   A  better   title ");
    await expect(page.getByTestId("chat-title")).toHaveText("A better title");
    await expect(box(page)).toHaveValue("");
    expect(await chatInfo(page, id)).toMatchObject({ title: "A better title" });
  });

  test("/export saves the conversation in the format it is given", async ({ page }) => {
    await ask(page, "Which nanobody binds TP53?");
    await answered(page, "You asked: Which nanobody binds TP53?");

    const saved = page.waitForEvent("download");
    await command(page, "/export html");
    expect((await saved).suggestedFilename()).toBe("Which nanobody binds TP53.html");
    await expect(box(page)).toHaveValue("");
  });

  test("/files shows the files and hides them, /model changes the model, and /new begins another conversation", async ({ page }) => {
    const id = await ask(page, "A question with files in mind");
    await answered(page, "You asked: A question with files in mind");

    await command(page, "/files");
    await expect(page.getByTestId("files-panel")).toBeVisible();
    await expect(page.getByTestId("files-toggle")).toHaveAttribute("aria-pressed", "true");
    await command(page, "/files");
    await expect(page.getByTestId("files-panel")).toHaveCount(0);

    await command(page, "/model");
    await expect(page.getByTestId("model-dialog").getByRole("heading", { name: "Change the model" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("model-dialog")).toHaveCount(0);

    await command(page, "/new");
    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
    expect(new URL(page.url()).searchParams.get("id")).toBeNull();
    expect((await chatInfo(page, id)).turns).toBe(1);
  });

  test("/model on the page where a conversation begins chooses the model it begins with", async ({ page }) => {
    await command(page, "/model");
    const choosing = page.getByTestId("model-dialog");
    await expect(choosing.getByRole("heading", { name: "Choose the model" })).toBeVisible();
    await choosing.getByRole("textbox", { name: "Search the models" }).fill("openrouter gemini pro");
    await choosing.getByTestId("model-option").first().click();
    await expect(choosing).toHaveCount(0);
    await expect(page.getByTestId("model-button")).toContainText("openrouter/google/gemini-2.5-pro");
  });

  test("/pause, /resume, and /stop hold, release, and stop a turn that is going on", async ({ page }) => {
    await askWhereCodeRuns(page, "code:slow steer it with commands");
    await expect(page.getByText("Running Python code")).toBeVisible();

    await command(page, "/pause");
    await expect(state(page)).toHaveText("Pausing");
    await expect(box(page)).toHaveValue("");
    await box(page).fill("/pause");
    await expect(options(page).first()).toContainText("It is held already");
    await expect(options(page).first()).toHaveAttribute("aria-disabled", "true");

    await command(page, "/resume");
    await expect(state(page)).toHaveText("Working");

    await command(page, "/stop");
    await expect(state(page)).toHaveText("Stopping");
    await expect(page.getByRole("status").filter({ hasText: /stopped/i })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("pending-note")).toHaveCount(0);
  });
});

const chip = (page: Page) => page.getByTestId("directive-chip");
const unmet = (page: Page) => page.getByTestId("directive-unmet");

// Opens a conversation that has nothing in it yet, which is made through the server, titled at once so that it is not
// taken for the button that makes one
async function open(page: Page, title: string, config: Record<string, unknown> = {}): Promise<string> {
  const made = await page.request.post("/api/chats", { data: { title, ...config } });
  expect(made.status()).toBe(201);
  const id: string = (await made.json()).id;
  await page.goto(`/chat?id=${id}`);
  await expect(box(page)).toBeVisible();

  return id;
}

const WHERE_CODE_RUNS = { code: { where: "local" } };

test.describe("the commands that go with a message", () => {
  for (const name of ["ask", "plan"]) {
    test(`/${name} begins a conversation with the message, which is shown with the command, and the lead has no tools for it`, async ({
      page,
    }) => {
      await command(page, `/${name} tool:offered which tools do you have`);
      await page.waitForURL(/\/chat\?id=/);

      await answered(page, "Offered:");
      await expect(chip(page)).toHaveText(`/${name}`);
      await expect(page.getByTestId("user-message")).toContainText("tool:offered which tools do you have");
      await expect(page.getByTestId("user-message")).not.toContainText("The researcher gave");
      await expect(page.getByTestId("lead-message").last()).toHaveText("Offered:");
      await expect(unmet(page)).toHaveCount(0);

      // The next message has them again
      await sendMessage(page, "tool:offered again");
      await expect(page.getByTestId("lead-message").last()).toContainText("convene_team");
      await expect(chip(page)).toHaveCount(1);
    });
  }

  test("a message can be several lines, and the command is kept when it is sent again or changed", async ({ page }) => {
    await command(page, "/ask tool:offered first line");
    await page.waitForURL(/\/chat\?id=/);
    await answered(page, "Offered:");

    await box(page).fill("/ask tool:offered second\nline");
    await expect(options(page)).toHaveCount(1);
    await box(page).press("Enter");
    await expect(page.getByTestId("user-message")).toHaveCount(2);
    await expect(page.getByTestId("user-message").last()).toContainText("second line");
    await answered(page, "Offered:");

    await page.getByRole("button", { name: "Retry" }).click();
    await expect(chip(page)).toHaveCount(2);
    await answered(page, "Offered:");
    await expect(page.getByTestId("lead-message").last()).toHaveText("Offered:");

    await page.getByRole("button", { name: "Edit" }).click();
    await page.getByRole("textbox", { name: "Edit message" }).fill("tool:offered changed");
    await page.getByRole("button", { name: "Send again" }).click();
    await expect(page.getByTestId("user-message").last()).toContainText("tool:offered changed");
    await answered(page, "Offered:");
    await expect(chip(page).last()).toHaveText("/ask");
    await expect(page.getByTestId("lead-message").last()).toHaveText("Offered:");
  });

  test("/code is answered with code, or the answer says that there was none", async ({ page }) => {
    await open(page, "Code on a command", WHERE_CODE_RUNS);

    await command(page, "/code code:hello run it");
    await answered(page, "That is done: 1 step ran.");
    await expect(chip(page)).toHaveText("/code");
    await expect(page.getByText("Running Python code").or(page.getByText("hello from the session")).first()).toBeVisible();
    await expect(unmet(page)).toHaveCount(0);

    // Told to run it, a lead that does not still has the say, and the page says what was not done
    await command(page, "/code work it out in your head");
    await answered(page, "You have not run any code for this message");
    await expect(unmet(page)).toHaveText("The lead answered without running any code, though /code asked for it.");
    await expect(unmet(page)).toHaveCount(1);
  });

  test("/plot wants a figure, and code that drew none is not one", async ({ page }) => {
    await open(page, "Plot on a command", WHERE_CODE_RUNS);

    await command(page, "/plot code:plot a figure");
    await answered(page, "That is done: 1 step ran.");
    await expect(unmet(page)).toHaveCount(0);

    await command(page, "/plot code:hello no figure");
    await answered(page, "No figure was made for this message");
    await expect(unmet(page)).toHaveText("The lead answered without making a figure, though /plot asked for one.");
  });

  test("/search is offered where there is a literature tool, and says when the lead did not search", async ({ page }) => {
    const id = await open(page, "Search on a command", { tools: ["pubmed_search"] });
    expect((await chatInfo(page, id)).directives.search).toBeNull();

    await command(page, "/search what is known of KP.3");
    await answered(page, "You have not searched the literature for this message");
    await expect(chip(page)).toHaveText("/search");
    await expect(unmet(page)).toContainText("without searching the literature");

    await open(page, "No search on a command", { tools: [] });
    await box(page).fill("/sea");
    await expect(options(page).first()).toHaveAttribute("aria-disabled", "true");
    await expect(options(page).first()).toContainText("No literature tool is turned on for this conversation");
  });

  test("/review waits for an answer, and has the Critic review it", async ({ page }) => {
    await open(page, "Review on a command");
    await box(page).fill("/rev");
    await expect(options(page).first()).toHaveAttribute("aria-disabled", "true");
    await expect(options(page).first()).toContainText("There is no answer to review yet");
    await box(page).fill("");

    await box(page).fill("A question to be reviewed");
    await box(page).press("Enter");
    await answered(page, "You asked: A question to be reviewed");

    await command(page, "/review");
    await expect(chip(page)).toHaveText("/review");
    await answered(page, "That is done: 1 step ran.");
    await expect(page.getByTestId("user-message")).toHaveCount(2);
    await expect(page.getByText("Scientific Critic").first()).toBeVisible();
    await expect(unmet(page)).toHaveCount(0);

    // With nothing written, there is nothing to change when it is sent again
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
  });

  test("on the page where a conversation begins, what asks for code says that it is off, and review is not there", async ({ page }) => {
    await box(page).fill("/");
    await expect.poll(() => listed(page)).not.toContain("/review");
    await expect(options(page).filter({ hasText: "Code is turned off in the settings" })).toHaveCount(2);
    await expect(options(page).filter({ hasText: "Code is turned off in the settings" }).first()).toHaveAttribute("aria-disabled", "true");
    await expect(lit(page)).toHaveAttribute("data-command", "/ask");

    await box(page).fill("/code ");
    await box(page).press("Enter");
    await expect(box(page)).toHaveValue("/code ");
    await expect(page.getByTestId("user-message")).toHaveCount(0);
  });

  test("they wait for the lead to finish, and say so", async ({ page }) => {
    await askWhereCodeRuns(page, "code:slow wait for the end of it");
    await expect(page.getByText("Running Python code")).toBeVisible();

    await box(page).fill("/as");
    await expect(options(page).first()).toHaveAttribute("aria-disabled", "true");
    await expect(options(page).first()).toContainText("It is given when the lead has finished");
    await box(page).press("Enter");
    await expect(box(page)).toHaveValue("/as");

    await answered(page, "That is done: 1 step ran.", 30_000);
  });

  test("a command the server turns away is put back in the box, with what it said", async ({ page }) => {
    await open(page, "A command that is turned away");
    await page.route("**/api/chats/*/messages", (route) =>
      route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "invalid", message: "/ask cannot be given: for the sake of a test" } }),
      }),
    );

    await command(page, "/ask what is a nanobody");

    await expect(page.getByRole("alert").filter({ hasText: "/ask cannot be given: for the sake of a test" })).toBeVisible();
    await expect(box(page)).toHaveValue("/ask what is a nanobody");
    await expect(page.getByTestId("user-message")).toHaveCount(0);
  });

  test("a command that is turned away on the page where a conversation begins leaves no conversation behind", async ({ page }) => {
    await page.route("**/api/chats/*/messages", (route) =>
      route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "invalid", message: "/plan cannot be given: for the sake of a test" } }),
      }),
    );

    await command(page, "/plan the work");

    await expect(page.getByRole("alert").filter({ hasText: "/plan cannot be given: for the sake of a test" })).toBeVisible();
    await expect(box(page)).toHaveValue("/plan the work");
    expect(new URL(page.url()).pathname).toBe("/");
  });
});

const panel = (page: Page) => page.getByTestId("lab-dialog");
const labChoice = (page: Page) => page.getByTestId("lab-choice");
const startLab = (page: Page) => panel(page).getByTestId("lab-start");
const written = (scope: Locator) => scope.getByRole("textbox", { name: "What should they work on?" });
const labRounds = (scope: Locator) => scope.getByRole("textbox", { name: /^Rounds of / });
const labQuestions = (scope: Locator) => scope.getByRole("textbox", { name: /^Questions they must answer/ });
const teamMember = (scope: Locator, title: string) => scope.getByRole("checkbox", { name: title, exact: true });
const soleMember = (scope: Locator, title: string) => scope.getByRole("radio", { name: title, exact: true });

// Waits for the last message to be sent again, and answered, which the page cannot show by what it says where it says the same
async function resent(page: Page, id: string, send: () => Promise<void>): Promise<void> {
  const before = (await chatInfo(page, id)).last_event_id;
  await send();
  await expect
    .poll(async () => {
      const info = await chatInfo(page, id);

      return info.last_event_id > before && info.state === "idle";
    })
    .toBe(true);
}

test.describe("/lab", () => {
  test("opens a panel, from the list or with words after it, and closing it puts what was written back in the box", async ({ page }) => {
    await open(page, "Lab panel");

    await box(page).fill("/la");
    await expect(options(page).first()).toContainText("Choose who works on it");
    await box(page).press("Enter");
    await expect(panel(page)).toBeVisible();
    await expect(written(panel(page))).toHaveValue("");
    await expect(startLab(page)).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(panel(page)).toHaveCount(0);
    await expect(rawBox(page)).toHaveValue("");

    await command(page, "/lab Design a nanobody");
    await expect(panel(page)).toBeVisible();
    await expect(written(panel(page))).toHaveValue("Design a nanobody");
    await expect(page.getByTestId("user-message")).toHaveCount(0);

    await written(panel(page)).fill("Design a nanobody against TP53");
    await panel(page).getByRole("button", { name: "Cancel" }).click();
    await expect(panel(page)).toHaveCount(0);
    await expect(rawBox(page)).toHaveValue("/lab Design a nanobody against TP53");
    await expect(page.getByTestId("user-message")).toHaveCount(0);
  });

  test("says what is missing or wrong, and starts nothing until it is put right", async ({ page }) => {
    await open(page, "Lab choices");
    await command(page, "/lab");

    const start = startLab(page);
    await expect(start).toBeDisabled();
    await written(panel(page)).fill("Design a nanobody");
    await expect(start).toBeDisabled();
    // What is not yet chosen is said, but it is not a mistake until it has been chosen and put away
    await expect(panel(page).getByText("Choose at least one scientist.")).toBeVisible();
    await expect(panel(page).getByRole("alert")).toHaveCount(0);

    await teamMember(panel(page), "Immunologist").check();
    await expect(start).toBeEnabled();
    await expect(panel(page).getByText("Choose at least one scientist.")).toHaveCount(0);
    await teamMember(panel(page), "Immunologist").uncheck();
    await expect(panel(page).getByRole("alert").filter({ hasText: "at least one" })).toBeVisible();
    await expect(start).toBeDisabled();
    await teamMember(panel(page), "Immunologist").check();

    await labRounds(panel(page)).fill("9");
    await expect(panel(page).getByRole("alert").filter({ hasText: "0 to" })).toBeVisible();
    await expect(start).toBeDisabled();
    await labRounds(panel(page)).fill("two");
    await expect(panel(page).getByRole("alert").filter({ hasText: "whole number" })).toBeVisible();
    await labRounds(panel(page)).fill("1");
    await expect(start).toBeEnabled();

    await labQuestions(panel(page)).fill("q\n".repeat(11));
    await expect(panel(page).getByRole("alert").filter({ hasText: "at most 10" })).toBeVisible();
    await expect(start).toBeDisabled();
    await labQuestions(panel(page)).fill("");
    await expect(start).toBeEnabled();

    // Who works alone is one scientist, and the Critic, who reviews them, is not one to choose
    await panel(page).getByRole("radio", { name: /One scientist/ }).check();
    await expect(panel(page).getByRole("checkbox")).toHaveCount(0);
    await expect(soleMember(panel(page), "Scientific Critic")).toHaveCount(0);
    await expect(soleMember(panel(page), "Principal Investigator")).toHaveCount(0);
    await expect(soleMember(panel(page), "Immunologist")).toBeChecked();
    await soleMember(panel(page), "Geneticist").check();
    await expect(soleMember(panel(page), "Immunologist")).not.toBeChecked();
    await expect(labRounds(panel(page))).toHaveAccessibleName("Rounds of review");
  });

  test("has the team the researcher chose discuss it, and the scientists who were not on the team join it", async ({ page }) => {
    const id = await open(page, "Lab team", { team: ["Scientific Critic", "Immunologist"] });
    expect((await chatInfo(page, id)).team).toEqual(["Scientific Critic", "Immunologist"]);

    await command(page, "/lab Design a nanobody");
    await teamMember(panel(page), "Immunologist").check();
    await expect(panel(page).getByText("not on this conversation's team")).toHaveCount(0);
    await teamMember(panel(page), "Geneticist").check();
    await expect(panel(page).getByText("Geneticist is not on this conversation's team, and joins it.")).toBeVisible();
    await labQuestions(panel(page)).fill("Which epitope?\n\nHow stable is it?");
    await startLab(page).click();

    await expect(panel(page)).toHaveCount(0);
    await answered(page, "That is done: 1 step ran.", 30_000);
    await expect(chip(page)).toHaveText("/lab");
    await expect(labChoice(page)).toHaveText("Immunologist, Geneticist · 1 round");
    await expect(page.getByTestId("user-message")).toContainText("Design a nanobody");
    await expect(page.getByTestId("user-message")).not.toContainText("The researcher gave");
    await expect(page.getByTestId("lab-turn").filter({ hasText: "As the Immunologist" }).first()).toBeVisible();
    await expect(unmet(page)).toHaveCount(0);
    expect((await chatInfo(page, id)).team).toEqual(["Scientific Critic", "Immunologist", "Geneticist"]);

    // The conversation keeps it for the next time the panel is opened, but not what was written in it
    await command(page, "/lab");
    await expect(written(panel(page))).toHaveValue("");
    await expect(teamMember(panel(page), "Immunologist")).toBeChecked();
    await expect(teamMember(panel(page), "Geneticist")).toBeChecked();
    await expect(labQuestions(panel(page))).toHaveValue("");
    await page.keyboard.press("Escape");
  });

  test("has one scientist work on it, and the lead says what the Critic raised", async ({ page }) => {
    await open(page, "Lab alone");
    await command(page, "/lab Is it immunogenic?");
    await panel(page).getByRole("radio", { name: /One scientist/ }).check();
    await soleMember(panel(page), "Immunologist").check();
    await labRounds(panel(page)).fill("2");
    await startLab(page).click();

    await answered(page, "That is done: 1 step ran.", 30_000);
    await expect(chip(page)).toHaveText("/lab");
    await expect(labChoice(page)).toHaveText("Immunologist, with the Critic reviewing · 2 rounds");
    await expect(page.getByText("As the Scientific Critic, I ask what shows that the epitope is exposed.").first()).toBeVisible();
  });

  test("is sent again as it was, and a lead that does not hold the session is told to, and the page says so", async ({ page }) => {
    const id = await open(page, "Lab again");
    await command(page, "/lab Design a nanobody");
    await teamMember(panel(page), "Immunologist").check();
    await startLab(page).click();
    await answered(page, "That is done: 1 step ran.", 30_000);

    await resent(page, id, () => page.getByRole("button", { name: "Retry" }).click());
    await answered(page, "That is done: 1 step ran.", 30_000);
    await expect(chip(page)).toHaveCount(1);
    await expect(labChoice(page)).toHaveText("Immunologist · 1 round");
    await expect(page.getByTestId("user-message")).toHaveCount(1);

    await page.getByRole("button", { name: "Edit" }).click();
    await page.getByRole("textbox", { name: "Edit message" }).fill("Design a nanobody for the spike");
    await resent(page, id, () => page.getByRole("button", { name: "Send again" }).click());
    await answered(page, "That is done: 1 step ran.", 30_000);
    await expect(page.getByTestId("user-message").last()).toContainText("for the spike");
    await expect(labChoice(page).last()).toHaveText("Immunologist · 1 round");

    await command(page, "/lab lab:skip leave it be");
    await teamMember(panel(page), "Immunologist").check();
    await startLab(page).click();
    await answered(page, "No team session has been held for this message", 30_000);
    await expect(unmet(page)).toHaveText("The lead answered without bringing in the scientists you chose, though /lab asked for it.");
  });

  test("a refusal by the server is shown in the panel, which stays as it was written", async ({ page }) => {
    await open(page, "Lab refused");
    await page.route("**/api/chats/*/messages", (route) =>
      route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "invalid", message: "/lab cannot be given: for the sake of a test" } }),
      }),
    );

    await command(page, "/lab Design a nanobody");
    await teamMember(panel(page), "Geneticist").check();
    await startLab(page).click();

    await expect(panel(page).getByRole("alert").filter({ hasText: "/lab cannot be given: for the sake of a test" })).toBeVisible();
    await expect(written(panel(page))).toHaveValue("Design a nanobody");
    await expect(teamMember(panel(page), "Geneticist")).toBeChecked();
    await expect(startLab(page)).toBeEnabled();
    await expect(page.getByTestId("user-message")).toHaveCount(0);
  });

  test("on the page where a conversation begins, it begins the conversation with the team that was chosen", async ({ page }) => {
    await command(page, "/lab Design a nanobody against TP53");
    await expect(panel(page)).toBeVisible();
    await teamMember(panel(page), "Immunologist").check();
    await startLab(page).click();

    await page.waitForURL(/\/chat\?id=/);
    await answered(page, "That is done: 1 step ran.", 30_000);
    await expect(chip(page)).toHaveText("/lab");
    await expect(labChoice(page)).toHaveText("Immunologist · 1 round");
    await expect(page.getByTestId("user-message")).toContainText("Design a nanobody against TP53");
  });

  test("on the page where a conversation begins, a refusal leaves no conversation behind", async ({ page }) => {
    await page.route("**/api/chats/*/messages", (route) =>
      route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "invalid", message: "/lab cannot be given: for the sake of a test" } }),
      }),
    );

    await command(page, "/lab Design a nanobody");
    await teamMember(panel(page), "Immunologist").check();
    await startLab(page).click();

    await expect(panel(page).getByRole("alert").filter({ hasText: "for the sake of a test" })).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/");
  });
});

const SIZES = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "phone", width: 390, height: 844 },
];

// What is not looked at where a dialog is open: the page behind it is hidden from what reads the page, as it should be,
// while what is on it cannot be reached, which axe cannot tell
const DIALOG_OPEN = ["aria-hidden-focus", "region", "page-has-heading-one"];

for (const theme of ["light", "dark"] as const) {
  for (const size of SIZES) {
    test(`the menu and the panels have nothing wrong for someone who cannot see them or use a mouse, and fit the window: ${theme}, ${size.name}`, async ({
      page,
    }) => {
      test.setTimeout(120_000);
      await page.setViewportSize({ width: size.width, height: size.height });
      await page.evaluate((chosen) => localStorage.setItem("vl-theme", chosen), theme);
      await page.reload();
      await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();

      async function looksRight(what: string, skip: string[] = []): Promise<void> {
        // What is fading in is not the colours it will have, which are what is checked
        await page.evaluate(() =>
          Promise.all(
            document
              .getAnimations()
              .filter((animation) => animation.effect?.getComputedTiming().iterations !== Infinity)
              // One that is cut short, as when what is fading in is replaced by what has been looked for, is over
              .map((animation) => animation.finished.catch(() => undefined)),
          ),
        );
        expect.soft(await accessibilityProblems(page, skip), `${what}: what is wrong for someone who cannot see it or use a mouse`).toEqual([]);
        expect.soft(await pastTheEdge(page), `${what}: how far the page goes past its edge`).toBeLessThanOrEqual(0);
      }

      await box(page).fill("/");
      await expect(menu(page)).toBeVisible();
      await looksRight("the list of commands on the first page");
      await box(page).fill("");

      await command(page, "/budget");
      await expect(dialog(page)).toBeVisible();
      await looksRight("the budget", DIALOG_OPEN);
      await spending(dialog(page)).fill("plenty");
      await looksRight("the budget, with a limit that is wrong", DIALOG_OPEN);
      await page.keyboard.press("Escape");

      await command(page, "/help");
      await expect(page.getByTestId("commands-help")).toBeVisible();
      await looksRight("the commands, listed", DIALOG_OPEN);
      await page.keyboard.press("Escape");

      await command(page, "/lab Design a nanobody");
      await expect(panel(page)).toBeVisible();
      await expect(teamMember(panel(page), "Immunologist")).toBeVisible();
      await looksRight("the panel for choosing who works on it", DIALOG_OPEN);
      await teamMember(panel(page), "Immunologist").check();
      await labRounds(panel(page)).fill("many");
      await looksRight("the panel for choosing who works on it, with a team and a number that is wrong", DIALOG_OPEN);
      await panel(page).getByRole("radio", { name: /One scientist/ }).check();
      await looksRight("the panel for choosing who works on it, for one scientist", DIALOG_OPEN);
      await page.keyboard.press("Escape");

      await ask(page, "A question to have a conversation");
      await answered(page, /./, 20_000);
      await box(page).fill("/");
      await expect(options(page).first()).toBeVisible();
      await expect(options(page).filter({ hasText: "Nothing is running" }).first()).toBeVisible();
      await looksRight("the list of commands, with some that cannot be run");
    });
  }
}
