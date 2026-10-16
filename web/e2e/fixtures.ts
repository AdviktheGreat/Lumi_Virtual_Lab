import { expect, test as base, type Page } from "@playwright/test";

// What the scripted server (e2e/scripted_server.py) is started with
export const TOKEN = "e2e-token";

export const HOME_HEADING = "What would you like to investigate?";

// Opens the link the server prints, which is how a browser is let in
export async function signIn(page: Page): Promise<void> {
  await page.goto(`/?token=${TOKEN}`);
  await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
}

// Opens the home page again, which is when it asks what the models and the keys are, and waits until it has been
// answered and shown, so that what is not there is not just not there yet, and what is asked for after is not what it asked
export async function reopenHome(page: Page): Promise<void> {
  const asked = Promise.all(
    ["/api/models", "/api/keys"].map((path) => page.waitForResponse((response) => new URL(response.url()).pathname === path)),
  );
  await page.goto("/");
  await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
  await asked;
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
}

// Asks the lead something from the home page, and waits for the conversation it starts
export async function ask(page: Page, question: string): Promise<string> {
  await page.getByRole("textbox", { name: "Message" }).fill(question);
  await page.getByRole("button", { name: "Send" }).click();
  await page.waitForURL(/\/chat\?id=/);

  return new URL(page.url()).searchParams.get("id") ?? "";
}

// Opens a conversation whose code runs on this machine, and asks the lead something in it. It is made through the
// server, so that what other tests make, and the settings, are left as they are. It is titled at once, since the
// conversations of all the tests are listed on the side, and one called "New chat" would be taken for the button.
export async function askWhereCodeRuns(page: Page, question: string): Promise<string> {
  const made = await page.request.post("/api/chats", { data: { title: question, code: { where: "local" } } });
  expect(made.status()).toBe(201);
  const id: string = (await made.json()).id;

  await page.goto(`/chat?id=${id}`);
  await page.getByRole("textbox", { name: "Message" }).fill(question);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByTestId("user-message")).toHaveText(question);

  return id;
}

// Waits for a turn to be over: the lead is at work from before it writes a word, and the badge that says so goes with
// its answer, so what is waited for is its last reply having the text and the work being done
export async function answered(page: Page, text: string | RegExp, timeout = 10_000): Promise<void> {
  await expect(page.getByTestId("lead-message").last()).toContainText(text, { timeout });
  await expect(page.getByTestId("chat-state")).toHaveCount(0, { timeout });
  await expect(page.getByRole("button", { name: "Send", exact: true })).toBeVisible({ timeout });
}

// What the browser says it refused a page, by the policy the server gives the pages, which a test of any page then
// must find none of: a page that is too much for the policy is a page that does not work
export const refusals = new WeakMap<Page, string[]>();

export const test = base.extend({
  page: async ({ page }, provide) => {
    const refused: string[] = [];
    refusals.set(page, refused);
    page.on("console", (message) => {
      if (message.text().includes("Content Security Policy")) refused.push(message.text());
    });

    await signIn(page);
    await provide(page);

    expect(refused).toEqual([]);
  },
});

export { expect };
