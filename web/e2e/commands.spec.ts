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
    await expect.poll(() => listed(page)).toEqual(["/budget", "/model", "/help"]);
    await expect(lit(page)).toHaveAttribute("data-command", "/budget");
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
      "/budget",
      "/model",
      "/rename",
      "/export",
      "/files",
      "/new",
      "/help",
      "/pause",
      "/resume",
      "/stop",
    ]);
    await expect(lit(page)).toHaveAttribute("data-command", "/budget");
    await box(page).press("ArrowDown");
    await expect(lit(page)).toHaveAttribute("data-command", "/model");
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
              .map((animation) => animation.finished),
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

      await ask(page, "A question to have a conversation");
      await answered(page, /./, 20_000);
      await box(page).fill("/");
      await expect(options(page).first()).toBeVisible();
      await expect(options(page).filter({ hasText: "Nothing is running" }).first()).toBeVisible();
      await looksRight("the list of commands, with some that cannot be run");
    });
  }
}
