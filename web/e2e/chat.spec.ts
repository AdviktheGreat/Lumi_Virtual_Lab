import { answered, ask, expect, test } from "./fixtures";

const transcript = (page: import("@playwright/test").Page) => page.getByTestId("transcript");

test.describe("a conversation with the lead", () => {
  test("asking a question starts a conversation and shows the lead's answer", async ({ page }) => {
    const question = "How do nanobodies differ from antibodies?";
    const id = await ask(page, question);

    expect(id).not.toBe("");
    await expect(page.getByTestId("user-message")).toHaveText(question);
    await answered(page, "This answer is from a script");
    await expect(page.getByTestId("lead-message")).toContainText(`You asked: ${question}`);
    // It did nothing but answer, so there is no list of what it did, not even an empty one
    await expect(page.getByTestId("steps")).toHaveCount(0);
    await expect(page.getByTestId("chat-title")).toHaveText(question);
    await expect(page).toHaveTitle(`${question} · Virtual Lab`);
  });

  test("the conversation is listed on the side and is there when the page is opened again", async ({ page }) => {
    const question = "Which residues bind the antigen in a nanobody?";
    const id = await ask(page, question);
    await answered(page, "This answer is from a script");

    const link = page.getByRole("navigation", { name: "Conversations" }).getByRole("link", { name: question });
    await expect(link).toHaveAttribute("href", `/chat?id=${id}`);
    await expect(link).toHaveAttribute("aria-current", "page");
    // The list is told as soon as the turn is over, and does not wait to be looked at again
    await expect(link.getByRole("img", { name: "Working" })).toHaveCount(0);

    await page.reload();

    await expect(page.getByTestId("user-message")).toHaveText(question);
    await expect(page.getByTestId("lead-message")).toContainText(`You asked: ${question}`);
    await expect(page.getByTestId("chat-title")).toHaveText(question);
  });

  test("a second message is answered in the same conversation", async ({ page }) => {
    await ask(page, "First question for the lead");
    await answered(page, "You asked: First question for the lead");

    await page.getByRole("textbox", { name: "Message" }).fill("Second question for the lead");
    await page.getByRole("textbox", { name: "Message" }).press("Enter");

    await expect(page.getByTestId("user-message")).toHaveText(["First question for the lead", "Second question for the lead"]);
    await answered(page, "You asked: Second question for the lead");
    await expect(page.getByTestId("lead-message")).toHaveCount(2);
    await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("");
  });

  test("Shift+Enter writes a new line and does not send", async ({ page }) => {
    const box = page.getByRole("textbox", { name: "Message" });
    await box.fill("line one");
    await box.press("Shift+Enter");
    await box.pressSequentially("line two");

    await expect(box).toHaveValue("line one\nline two");
    await expect(page).not.toHaveURL(/chat/);
  });

  test("a reply is shown as it is written, and the lead is working until it is done", async ({ page }) => {
    await ask(page, "slow: write a long reply");

    await expect(page.getByTestId("chat-state")).toHaveText("Working");
    await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
    await expect(page.getByTestId("lead-message")).toContainText("word1 ");
    await answered(page, "word250", 30_000);
  });

  test("Enter while the lead is at work adds a note, and does not send a second message", async ({ page }) => {
    let sent = 0;
    await page.route("**/api/chats/*/messages", (route) => {
      sent += 1;
      return route.continue();
    });
    await ask(page, "slow: write a long reply and be interrupted");
    await expect(page.getByTestId("chat-state")).toHaveText("Working");

    const box = page.getByRole("textbox", { name: "Message" });
    await box.fill("Something said while it works");
    await box.press("Enter");

    await expect(page.getByTestId("pending-note")).toContainText("Something said while it works");
    await expect(box).toHaveValue("");
    await page.getByRole("button", { name: "Stop" }).click();
    await expect(page.getByRole("status").filter({ hasText: /stopped/i })).toBeVisible({ timeout: 30_000 });
    expect(sent).toBe(1);
    await expect(page.getByTestId("user-message")).toHaveCount(1);
    await expect(page.getByTestId("note")).toContainText("Not read: it came too late");
  });

  test("a turn that is stopped says so, and the conversation goes on", async ({ page }) => {
    await ask(page, "slow: write a long reply and be stopped");
    await expect(page.getByTestId("lead-message")).toContainText("word1 ");

    await page.getByRole("button", { name: "Stop" }).click();

    await expect(page.getByRole("status").filter({ hasText: /stopped/i })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
    await expect(page.getByTestId("lead-message")).toHaveCount(0);

    await page.getByRole("textbox", { name: "Message" }).fill("Are you still there?");
    await page.getByRole("button", { name: "Send" }).click();
    await answered(page, "You asked: Are you still there?");
  });

  test("a turn that ends in an error says what went wrong, and the conversation goes on", async ({ page }) => {
    await ask(page, "fail: please");

    await expect(transcript(page).getByRole("alert")).toContainText("The scripted model failed, as it was asked to");
    await expect(page.getByRole("button", { name: "Send" })).toBeVisible();

    await page.getByRole("textbox", { name: "Message" }).fill("A question after the failure");
    await page.getByRole("button", { name: "Send" }).click();
    await answered(page, "You asked: A question after the failure");
  });

  test("a conversation that is not there says so", async ({ page }) => {
    await page.goto("/chat?id=2026-01-01_0000_nothing-here");

    await expect(page.getByRole("heading", { name: "This conversation is not here" })).toBeVisible();
    await page.getByRole("link", { name: "Start a new one" }).click();
    await expect(page.getByRole("heading", { name: "What would you like to investigate?" })).toBeVisible();
  });

  test("an address with no conversation in it says so, and asks the server for none", async ({ page }) => {
    const asked: string[] = [];
    page.on("request", (request) => {
      if (/\/api\/chats\//.test(request.url())) asked.push(request.url());
    });

    await page.goto("/chat");

    await expect(page.getByRole("heading", { name: "This conversation is not here" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Start a new one" })).toBeVisible();
    expect(asked).toEqual([]);
  });

  test("the list on the side is told when a turn is over, without being looked at again", async ({ page }) => {
    // The list is asked for again every few seconds while the page is in view, which would hide a list that was not told
    await page.addInitScript(() => {
      Object.defineProperty(document, "visibilityState", { get: () => "hidden" });
    });
    await page.reload();

    const id = await ask(page, "slow: a reply the list must catch the end of");
    const working = page
      .getByRole("navigation", { name: "Conversations" })
      .locator(`a[href="/chat?id=${id}"]`)
      .getByRole("img", { name: "Working" });
    await expect(working).toBeVisible();

    await answered(page, "word250", 30_000);
    await expect(working).toHaveCount(0, { timeout: 2_000 });
  });

  test("the transcript stays at the end as a reply grows, until the reader scrolls up", async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 500 });
    await ask(page, "slow: grow past the page");
    await expect(page.getByTestId("lead-message")).toContainText("word100 ", { timeout: 30_000 });

    const scroller = transcript(page);
    const gap = () => scroller.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight);
    await expect.poll(gap).toBeLessThan(50);

    await scroller.evaluate((el) => el.scrollTo({ top: 0 }));
    await expect(page.getByRole("button", { name: "Jump to the latest" })).toBeVisible();
    const before = await scroller.evaluate((el) => el.scrollTop);
    await page.waitForTimeout(600);
    expect(await scroller.evaluate((el) => el.scrollTop)).toBe(before);

    await page.getByRole("button", { name: "Jump to the latest" }).click();
    await expect.poll(gap).toBeLessThan(50);
  });
});
