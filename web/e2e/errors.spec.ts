import { answered, ask, expect, HOME_HEADING, test } from "./fixtures";

const refused = (code: string, message: string, status = 422) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify({ error: { code, message } }),
});

// What a page does when it is next looked at, which is when it asks for the list of conversations again
const lookAgain = (page: import("@playwright/test").Page) =>
  page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));

test.describe("when something goes wrong", () => {
  test("a conversation the server refuses to make says why, and what was written is kept", async ({ page }) => {
    await page.route("**/api/chats", (route) =>
      route.request().method() === "POST"
        ? route.fulfill(refused("missing_keys", "gpt-5.2 needs OPENAI_API_KEY, which is not set."))
        : route.continue(),
    );

    await page.getByRole("textbox", { name: "Message" }).fill("Something to ask");
    await page.getByRole("button", { name: "Send" }).click();

    await expect(page.getByRole("alert").filter({ hasText: "needs OPENAI_API_KEY" })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("Something to ask");
    await expect(page).not.toHaveURL(/chat/);
    await expect(page.getByRole("button", { name: "Send" })).toBeEnabled();
  });

  test("a message the server refuses leaves no empty conversation behind", async ({ page }) => {
    await page.route("**/api/chats/*/messages", (route) => route.fulfill(refused("invalid", "That cannot be sent.")));
    const removed: string[] = [];
    page.on("response", (response) => {
      if (response.request().method() === "DELETE") removed.push(`${response.url().split("/").pop()}:${response.status()}`);
    });
    const made = page.waitForResponse((response) => response.url().endsWith("/api/chats") && response.request().method() === "POST");

    await page.getByRole("textbox", { name: "Message" }).fill("Something to ask");
    await page.getByRole("button", { name: "Send" }).click();
    const { id } = await (await made).json();

    await expect(page.getByRole("alert").filter({ hasText: "That cannot be sent." })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("Something to ask");
    await expect(page).not.toHaveURL(/chat/);
    // The server is asked to remove it, and does. Whether it is still there is not asked: a conversation made by
    // another test, at the same moment, can be given the name it had
    expect(removed).toEqual([`${id}:204`]);
  });

  test("a message the server refuses in a conversation says why, and what was written is kept", async ({ page }) => {
    await ask(page, "A question to begin with");
    await answered(page, "You asked: A question to begin with");
    await page.route("**/api/chats/*/messages", (route) => route.fulfill(refused("busy", "The lead is still answering.", 409)));

    await page.getByRole("textbox", { name: "Message" }).fill("A question too soon");
    await page.getByRole("button", { name: "Send" }).click();

    await expect(page.getByTestId("transcript").getByRole("alert")).toHaveCount(0);
    await expect(page.getByRole("alert").filter({ hasText: "The lead is still answering." })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("A question too soon");

    await page.unroute("**/api/chats/*/messages");
    await page.getByRole("button", { name: "Send" }).click();
    await answered(page, "You asked: A question too soon");
    await expect(page.getByRole("alert").filter({ hasText: "still answering" })).toHaveCount(0);
  });

  test("a conversation whose live stream the server refuses says that the connection was lost", async ({ page }) => {
    await page.route("**/api/chats/*/events*", (route) => route.fulfill(refused("internal", "Something went wrong.", 500)));

    await ask(page, "A question whose answer is never streamed");

    await expect(page.getByText("The live connection to this conversation was lost")).toBeVisible();
    await expect(page.getByTestId("chat-title")).toHaveText("A question whose answer is never streamed");
  });

  test("a conversation whose live stream is refused because it is gone says that it is gone", async ({ page }) => {
    let looked = 0;
    await page.route("**/api/chats/*", async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      looked += 1;
      if (looked > 1) return route.fulfill(refused("not_found", "No such conversation.", 404));
      // The first look is answered after the second, which is the newer answer and is not to be undone by it
      await new Promise((resolve) => setTimeout(resolve, 700));
      return route.continue();
    });
    await page.route("**/api/chats/*/events*", (route) => route.fulfill(refused("not_found", "No such conversation.", 404)));

    const firstAnswer = page.waitForResponse((response) => /\/api\/chats\/[^/]+$/.test(response.url()) && response.status() === 200);

    await ask(page, "A question in a conversation that goes");

    const gone = page.getByRole("heading", { name: "This conversation is not here" });
    await expect(gone).toBeVisible();
    await firstAnswer;
    // Time for the page to have been wrong, if it was going to be
    await page.waitForTimeout(300);
    await expect(gone).toBeVisible();
  });

  test("a server that goes away is said to be, and the page carries on when it is back", async ({ page }) => {
    await ask(page, "A question before the server goes");
    await answered(page, "You asked: A question before the server goes");

    await page.route("**/api/**", (route) => route.abort());
    await lookAgain(page);

    await expect(page.getByRole("status").filter({ hasText: "The server cannot be reached" })).toBeVisible();
    await expect(page.getByTestId("user-message")).toHaveText("A question before the server goes");

    await page.unroute("**/api/**");

    await expect(page.getByRole("status").filter({ hasText: "The server cannot be reached" })).toHaveCount(0, {
      timeout: 15_000,
    });
  });

  test("a server that cannot be reached when the page opens says so, and the page opens when it can", async ({ page }) => {
    await page.route("**/api/health", (route) => route.abort());
    await page.reload();

    await expect(page.getByRole("heading", { name: "The server cannot be reached" })).toBeVisible();

    await page.unroute("**/api/health");
    await page.getByRole("button", { name: "Try again" }).click();

    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
  });

  test("a server that stops accepting the token sends the browser back to the link", async ({ page }) => {
    await page.route("**/api/chats", (route) => route.fulfill(refused("unauthorized", "Open the link.", 401)));
    await page.route("**/api/settings", (route) => route.fulfill(refused("unauthorized", "Open the link.", 401)));
    await lookAgain(page);

    await expect(page.getByRole("heading", { name: "Open the link the server printed" })).toBeVisible();
  });
});
