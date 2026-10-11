import { expect, test as base, type Page } from "@playwright/test";

// What the scripted server (e2e/scripted_server.py) is started with
export const TOKEN = "e2e-token";

export const HOME_HEADING = "What would you like to investigate?";

// Opens the link the server prints, which is how a browser is let in
export async function signIn(page: Page): Promise<void> {
  await page.goto(`/?token=${TOKEN}`);
  await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
}

// Asks the lead something from the home page, and waits for the conversation it starts
export async function ask(page: Page, question: string): Promise<string> {
  await page.getByRole("textbox", { name: "Message" }).fill(question);
  await page.getByRole("button", { name: "Send" }).click();
  await page.waitForURL(/\/chat\?id=/);

  return new URL(page.url()).searchParams.get("id") ?? "";
}

// Waits for a turn to be over: the lead is at work from before it writes a word, and the badge that says so goes with
// its answer, so what is waited for is its last reply having the text and the work being done
export async function answered(page: Page, text: string | RegExp, timeout = 10_000): Promise<void> {
  await expect(page.getByTestId("lead-message").last()).toContainText(text, { timeout });
  await expect(page.getByTestId("chat-state")).toHaveCount(0, { timeout });
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible({ timeout });
}

export const test = base.extend({
  page: async ({ page }, provide) => {
    await signIn(page);
    await provide(page);
  },
});

export { expect };
