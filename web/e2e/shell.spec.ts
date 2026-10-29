import { answered, ask, expect, HOME_HEADING, test } from "./fixtures";

test.describe("the shell", () => {
  test("New chat leaves a conversation for a fresh page, and the conversations are listed latest first", async ({ page }) => {
    await ask(page, "The first of two conversations");
    await answered(page, "This answer is from a script");

    await page.getByRole("link", { name: "New chat" }).click();
    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("");

    await ask(page, "The second of two conversations");
    await answered(page, "This answer is from a script");

    const titles = await page
      .getByRole("navigation", { name: "Conversations" })
      .getByRole("link")
      .allInnerTexts();
    const first = titles.findIndex((title) => title.includes("The first of two conversations"));
    const second = titles.findIndex((title) => title.includes("The second of two conversations"));
    expect(first).toBeGreaterThan(-1);
    expect(second).toBeGreaterThan(-1);
    expect(second).toBeLessThan(first);

    await page.getByRole("link", { name: /The first of two conversations/ }).click();
    await expect(page.getByTestId("user-message")).toHaveText("The first of two conversations");
  });

  test("an example fills the message without sending it", async ({ page }) => {
    await page.getByRole("button", { name: /Base editing/ }).click();

    await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(/CRISPR base editors/);
    await expect(page).not.toHaveURL(/chat/);
  });

  test("Send waits for something to send", async ({ page }) => {
    const send = page.getByRole("button", { name: "Send" });
    await expect(send).toBeDisabled();

    // What is asked of the server is counted, because a message with nothing in it that is refused would look the same
    let made = 0;
    await page.route("**/api/chats", (route) => {
      if (route.request().method() === "POST") made += 1;
      return route.continue();
    });

    await page.getByRole("textbox", { name: "Message" }).fill("   ");
    await expect(send).toBeDisabled();
    await page.getByRole("textbox", { name: "Message" }).press("Enter");
    await expect(page).not.toHaveURL(/chat/);

    await page.getByRole("textbox", { name: "Message" }).fill("Now there is something");
    await expect(send).toBeEnabled();
    await send.click();
    await page.waitForURL(/\/chat\?id=/);
    expect(made).toBe(1);
  });

  test("Enter does not send a message a second time while it is being sent", async ({ page }) => {
    let made = 0;
    await page.route("**/api/chats", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      made += 1;
      await new Promise((resolve) => setTimeout(resolve, 600));
      return route.continue();
    });

    const box = page.getByRole("textbox", { name: "Message" });
    await box.fill("Asked once");
    await box.press("Enter");
    await box.press("Enter");
    await page.waitForURL(/\/chat\?id=/);

    await expect(page.getByTestId("user-message")).toHaveCount(1);
    expect(made).toBe(1);
  });

  test("the theme is chosen, kept, and applied before the page is shown", async ({ page }) => {
    const html = page.locator("html");
    await page.emulateMedia({ colorScheme: "light" });
    await page.reload();
    await expect(html).not.toHaveClass(/dark/);

    await page.getByRole("button", { name: "Theme" }).click();
    await page.getByRole("menuitem", { name: "Dark" }).click();
    await expect(html).toHaveClass(/dark/);

    await page.reload();
    await expect(html).toHaveClass(/dark/);

    await page.getByRole("button", { name: "Theme" }).click();
    await page.getByRole("menuitem", { name: "System" }).click();
    await expect(html).not.toHaveClass(/dark/);

    await page.emulateMedia({ colorScheme: "dark" });
    await expect(html).toHaveClass(/dark/);
  });

  test("the conversations can be hidden and shown, the rail stays, and the choice is kept", async ({ page }) => {
    const conversations = page.getByRole("navigation", { name: "Conversations" });
    const pages = page.getByRole("navigation", { name: "Pages" });
    await expect(conversations).toBeVisible();
    await expect(pages).toBeVisible();

    await page.getByRole("button", { name: "Hide the sidebar" }).click();
    await expect(conversations).toBeHidden();
    await expect(pages).toBeVisible();

    await page.reload();
    await expect(conversations).toBeHidden();
    await expect(pages).toBeVisible();

    await page.getByRole("button", { name: "Show the sidebar" }).click();
    await expect(conversations).toBeVisible();
  });
});

test.describe("on a narrow screen", () => {
  test.use({ viewport: { width: 390, height: 800 } });

  test("the conversations are in a drawer that closes when one is chosen", async ({ page }) => {
    await ask(page, "A conversation to find in the drawer");
    await answered(page, "This answer is from a script");
    const sidebar = page.getByRole("complementary", { name: "Sidebar" });
    await expect(sidebar).toBeHidden();

    await page.getByRole("button", { name: "Show the conversations" }).click();
    await expect(sidebar).toBeVisible();
    await expect(sidebar).toBeInViewport();

    await page.getByRole("link", { name: "New chat" }).click();
    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
    await expect(sidebar).toBeHidden();
  });

  test("the drawer closes with Escape, and with a tap outside it", async ({ page }) => {
    const sidebar = page.getByRole("complementary", { name: "Sidebar" });

    await page.getByRole("button", { name: "Show the conversations" }).click();
    await expect(sidebar).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sidebar).toBeHidden();

    await page.getByRole("button", { name: "Show the conversations" }).click();
    await expect(sidebar).toBeVisible();
    await page.mouse.click(380, 400);
    await expect(sidebar).toBeHidden();
  });
});
