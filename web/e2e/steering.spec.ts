import { answered, ask, askWhereCodeRuns, expect, test } from "./fixtures";

const box = (page: import("@playwright/test").Page) => page.getByRole("textbox", { name: "Message" });
const state = (page: import("@playwright/test").Page) => page.getByTestId("chat-state");

// Code that takes three seconds is what the lead is waiting on in these, which leaves time to steer it
const WORKING = "code:slow";

test.describe("steering a turn that is going on", () => {
  test("what is written while the lead works is a note, which is shown as sent and then as read", async ({ page }) => {
    let messages = 0;
    await page.route("**/api/chats/*/messages", (route) => {
      messages += 1;
      return route.continue();
    });
    await askWhereCodeRuns(page, `${WORKING} a note while it runs`);
    await expect(page.getByText("Running Python code")).toBeVisible();

    await expect(box(page)).toHaveAttribute("placeholder", /Add a note/);
    await box(page).fill("Look at the B cells too");
    await box(page).press("Enter");

    await expect(page.getByTestId("pending-note")).toContainText("Look at the B cells too");
    await expect(page.getByTestId("pending-note")).toContainText("it is read before the next step");
    await expect(box(page)).toHaveValue("");

    // It is read before the lead is asked again, as what the researcher said while it worked, which the script answers
    await answered(page, /added a note while you were working:\s+Look at the B cells too/, 30_000);
    await expect(page.getByTestId("pending-note")).toHaveCount(0);
    await expect(page.getByTestId("note")).toHaveCount(1);
    await expect(page.getByTestId("note")).toContainText("Look at the B cells too");
    await expect(page.getByTestId("note")).toContainText("Read by the lead");
    // A note is not a message, so the turn is the same one and no second was begun
    expect(messages).toBe(1);
    await expect(page.getByTestId("user-message")).toHaveCount(1);
  });

  test("a note is added with its button too, and an empty one cannot be", async ({ page }) => {
    await askWhereCodeRuns(page, `${WORKING} the button`);
    await expect(page.getByText("Running Python code")).toBeVisible();

    const add = page.getByRole("button", { name: "Add note" });
    await expect(add).toBeDisabled();
    await box(page).fill("   ");
    await expect(add).toBeDisabled();

    await box(page).fill("Mind the controls");
    await add.click();

    await expect(page.getByTestId("pending-note")).toContainText("Mind the controls");
    await answered(page, /added a note while you were working:\s+Mind the controls/, 30_000);
    await expect(page.getByTestId("note")).toContainText("Read by the lead");
  });

  test("a note that comes after the lead has written its last reply is shown as not read", async ({ page }) => {
    await ask(page, "slow: a reply that is too far along for a note");
    await expect(page.getByTestId("lead-message")).toContainText("word1 ");

    await box(page).fill("Too late for you");
    await page.getByRole("button", { name: "Add note" }).click();
    await expect(page.getByTestId("pending-note")).toContainText("Too late for you");

    await answered(page, "word250", 30_000);
    await expect(page.getByTestId("pending-note")).toHaveCount(0);
    await expect(page.getByTestId("note")).toContainText("Not read: it came too late");
  });

  test("a note that was not taken, because the lead had finished, stays in the box to be sent as a message", async ({ page }) => {
    await page.route("**/api/chats/*/note", (route) => route.fulfill({ json: { accepted: false } }));
    await ask(page, "slow: a reply that ends before the note");
    await expect(page.getByTestId("lead-message")).toContainText("word1 ");

    await box(page).fill("Did you get this?");
    await page.getByRole("button", { name: "Add note" }).click();

    await expect(page.getByRole("alert").filter({ hasText: "The lead had already finished, so the note was not added" })).toBeVisible();
    await expect(box(page)).toHaveValue("Did you get this?");
    await expect(page.getByTestId("pending-note")).toHaveCount(0);
  });

  test("a note that could not be sent says why and stays in the box", async ({ page }) => {
    await page.route("**/api/chats/*/note", (route) =>
      route.fulfill({ status: 500, json: { error: { code: "internal", message: "The note could not be kept" } } }),
    );
    await ask(page, "slow: a reply while a note fails");
    await expect(page.getByTestId("lead-message")).toContainText("word1 ");

    await box(page).fill("Please read this");
    await box(page).press("Enter");

    await expect(page.getByRole("alert").filter({ hasText: "The note could not be kept" })).toBeVisible();
    await expect(box(page)).toHaveValue("Please read this");
    await expect(page.getByTestId("pending-note")).toHaveCount(0);
  });

  test("a turn can be held while code runs, takes a note while it is held, and goes on when it is let go", async ({ page }) => {
    await askWhereCodeRuns(page, `${WORKING} hold it`);
    await expect(page.getByText("Running Python code")).toBeVisible();

    await page.getByRole("button", { name: "Pause" }).click();

    // The code is carried through, and the turn is held before the lead is asked anything more
    await expect(state(page)).toHaveText("Pausing");
    await expect(page.getByTestId("held")).toHaveText("Pausing once this step is done…");
    await expect(state(page)).toHaveText("Paused", { timeout: 15_000 });
    // The lead is not thinking while it is held, and the page says what it is waiting for instead
    await expect(page.getByTestId("held")).toHaveText("Paused. The lead goes on when you resume.");
    await expect(page.getByText("Thinking…")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Pause" })).toHaveCount(0);
    await expect(box(page)).toHaveAttribute("placeholder", "Add a note, then resume…");
    await page.waitForTimeout(1_000);
    await expect(state(page)).toHaveText("Paused");
    await expect(page.getByTestId("lead-message")).toHaveCount(0);

    await box(page).fill("Use the second sample");
    await box(page).press("Enter");
    await expect(page.getByTestId("pending-note")).toContainText("Use the second sample");

    await page.getByRole("button", { name: "Resume" }).click();

    await answered(page, /added a note while you were working:\s+Use the second sample/, 30_000);
    await expect(page.getByTestId("held")).toHaveCount(0);
    await expect(page.getByTestId("note")).toContainText("Read by the lead");
    await expect(page.getByTestId("note")).toContainText("Use the second sample");
  });

  test("a pause that has not taken hold yet is called off by letting it go", async ({ page }) => {
    await askWhereCodeRuns(page, `${WORKING} change of mind`);
    await expect(page.getByText("Running Python code")).toBeVisible();

    await page.getByRole("button", { name: "Pause" }).click();
    await expect(state(page)).toHaveText("Pausing");
    await page.getByRole("button", { name: "Resume" }).click();

    await expect(state(page)).toHaveText("Working");
    await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
    await answered(page, "That is done: 1 step ran.", 30_000);
  });

  test("a turn that is held can be stopped, which keeps what was done", async ({ page }) => {
    await askWhereCodeRuns(page, `${WORKING} hold then stop`);
    await expect(page.getByText("Running Python code")).toBeVisible();
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(state(page)).toHaveText("Paused", { timeout: 15_000 });

    await page.getByRole("button", { name: "Stop" }).click();

    await expect(page.getByRole("status").filter({ hasText: /stopped/i })).toBeVisible({ timeout: 15_000 });
    await expect(state(page)).toHaveCount(0);
    await expect(page.getByTestId("code-output")).toHaveText("slept");
    await expect(page.getByRole("button", { name: "Send", exact: true })).toBeVisible();
  });

  test("while a turn is being stopped, nothing more can be done to it", async ({ page }) => {
    await askWhereCodeRuns(page, `${WORKING} stop and wait`);
    await expect(page.getByText("Running Python code")).toBeVisible();

    await page.getByRole("button", { name: "Stop" }).click();

    await expect(state(page)).toHaveText("Stopping");
    await expect(page.getByTestId("held")).toHaveText("Stopping once this step is done…");
    await expect(page.getByRole("button", { name: "Stop" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Pause" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Add note" })).toBeDisabled();
    await expect(box(page)).toHaveAttribute("placeholder", "Stopping…");
    // Writing is not stopped, so that what is written is not lost, but Enter has nothing to add it to
    await box(page).fill("Too late");
    await box(page).press("Enter");
    await expect(page.getByTestId("pending-note")).toHaveCount(0);
    await expect(box(page)).toHaveValue("Too late");

    await expect(page.getByRole("status").filter({ hasText: /stopped/i })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("held")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Send", exact: true })).toBeEnabled();
  });

  test("a conversation that is not at work offers to send, and nothing to pause, stop, or add to", async ({ page }) => {
    await ask(page, "A plain question");
    await answered(page, "You asked: A plain question");

    for (const name of ["Pause", "Resume", "Stop", "Add note"]) {
      await expect(page.getByRole("button", { name })).toHaveCount(0);
    }
    await expect(box(page)).toHaveAttribute("placeholder", "Ask the lead scientist…");
  });

  test("a conversation that is held when the page is opened is shown as held, with the way to let it go", async ({ page }) => {
    await askWhereCodeRuns(page, `${WORKING} reload while held`);
    await expect(page.getByText("Running Python code")).toBeVisible();
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(state(page)).toHaveText("Paused", { timeout: 15_000 });

    await page.reload();

    await expect(state(page)).toHaveText("Paused");
    await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();
    await page.getByRole("button", { name: "Resume" }).click();
    await answered(page, "That is done: 1 step ran.", 30_000);
  });
});
