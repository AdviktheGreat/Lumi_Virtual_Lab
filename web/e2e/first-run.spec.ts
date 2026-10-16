import type { Page } from "@playwright/test";
import { expect, reopenHome, test } from "./fixtures";

const SETTABLE = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"];

// What the server says of the keys, with OpenAI's set or not
const keys = (openai: boolean) => ({
  settable: SETTABLE,
  providers: [
    { provider: "OpenAI", variables: ["OPENAI_API_KEY"], missing: openai ? [] : ["OPENAI_API_KEY"], ready: openai },
    { provider: "Anthropic", variables: ["ANTHROPIC_API_KEY"], missing: [], ready: true },
  ],
  keychain: { available: false, name: null, problem: null },
  sources: openai ? { OPENAI_API_KEY: "session" } : {},
  problem: null,
});

const refused = (code: string, message: string) => ({
  status: 422,
  contentType: "application/json",
  body: JSON.stringify({ error: { code, message } }),
});

// Found by its role in the page, which a dialog that is open hides from the roles of a browser, and so from a query by them
const notice = (page: Page) => page.locator('[role="status"]').filter({ hasText: "needs OPENAI_API_KEY" });

// Any such notice, whatever it says is missing, for what is to be said when nothing is
const anyNotice = (page: Page) => page.locator('[role="status"]').filter({ hasText: /needs .* not set/ });

test.describe("the first page, when the model has no key", () => {
  test("says which key is missing, and opens the keys to add it", async ({ page }) => {
    await page.route("**/api/keys", (route) => route.fulfill({ json: keys(false) }));

    await reopenHome(page);

    await expect(notice(page)).toHaveText(/gpt-5\.2 needs OPENAI_API_KEY, which is not set\./);
    await notice(page).getByRole("button", { name: "Add the key" }).click();
    await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Keys" })).toHaveAttribute("aria-selected", "true");
  });

  test("says so in the plural when the provider needs more than one, and offers to add them", async ({ page }) => {
    const both = ["OPENAI_API_KEY", "OPENAI_ENDPOINT"];
    await page.route("**/api/keys", (route) => {
      const body = keys(false);
      body.providers[0] = { provider: "OpenAI", variables: both, missing: both, ready: false };

      return route.fulfill({ json: body });
    });

    await reopenHome(page);

    await expect(notice(page)).toHaveText(/gpt-5\.2 needs OPENAI_API_KEY, OPENAI_ENDPOINT, which are not set\./);
    await expect(notice(page).getByRole("button", { name: "Add the keys" })).toBeVisible();
  });

  test("lets a message be written and sent all the same", async ({ page }) => {
    await page.route("**/api/keys", (route) => route.fulfill({ json: keys(false) }));

    await reopenHome(page);
    await expect(notice(page)).toBeVisible();

    await expect(page.getByRole("textbox", { name: "Message" })).toBeEnabled();
    await page.getByRole("textbox", { name: "Message" }).fill("Something to ask");
    await expect(page.getByRole("button", { name: "Send" })).toBeEnabled();
  });

  test("is gone as soon as the key is given and the settings are closed, with no reload", async ({ page }) => {
    let given = false;
    await page.route("**/api/keys", (route) => route.fulfill({ json: keys(given) }));
    await page.route("**/api/keys/OPENAI_API_KEY", (route) => {
      given = true;

      return route.fulfill({ json: keys(true) });
    });

    await reopenHome(page);
    await expect(notice(page)).toBeVisible();
    await notice(page).getByRole("button", { name: "Add the key" }).click();
    const dialog = page.getByRole("dialog", { name: "Settings" });
    await dialog.getByLabel("OpenAI key", { exact: true }).fill("sk-test");
    await dialog.getByRole("button", { name: "Save", exact: true }).first().click();
    await expect(dialog.getByTestId("key-state-OPENAI_API_KEY")).toHaveText("Set");
    await dialog.getByRole("button", { name: "Close", exact: true }).first().click();

    await expect(dialog).toHaveCount(0);
    await expect(anyNotice(page)).toHaveCount(0);
  });

  test("is not there when the key is set", async ({ page }) => {
    await page.route("**/api/keys", (route) => route.fulfill({ json: keys(true) }));

    await reopenHome(page);

    await expect(anyNotice(page)).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
  });

  test("says nothing when the server cannot say which keys are set, and the page works", async ({ page }) => {
    await page.route("**/api/keys", (route) => route.fulfill(refused("invalid", "The keys cannot be read.")));

    await reopenHome(page);

    await expect(anyNotice(page)).toHaveCount(0);
    await expect(page.getByRole("alert").filter({ hasText: "The keys cannot be read." })).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "Message" })).toBeEnabled();
  });

  test("is not said a second time when a message is refused for the same key", async ({ page }) => {
    await page.route("**/api/keys", (route) => route.fulfill({ json: keys(false) }));
    await page.route("**/api/chats", (route) =>
      route.request().method() === "POST"
        ? route.fulfill(refused("missing_keys", "gpt-5.2 needs OPENAI_API_KEY, which is not set."))
        : route.continue(),
    );
    await reopenHome(page);
    await expect(notice(page)).toBeVisible();

    await page.getByRole("textbox", { name: "Message" }).fill("Something to ask");
    await page.getByRole("button", { name: "Send" }).click();

    await expect(page.getByRole("alert").filter({ hasText: "needs OPENAI_API_KEY" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Add the key" })).toHaveCount(1);
    await expect(notice(page)).toHaveCount(0);
  });
});
