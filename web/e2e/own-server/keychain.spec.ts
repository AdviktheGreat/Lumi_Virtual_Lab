import type { Page } from "@playwright/test";
import { expect, test } from "../fixtures";
import { KEYS, openSettings, resetSettings } from "./state";

// The keys a person gives are kept in the server's keychain, which for these tests is a dictionary the scripted server
// keeps and calls the Test Keychain. The tests change the keys the server has, which the other tests of this server do
// too, so each puts them back and none is run beside another.
test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await resetSettings(page);
  await page.reload();
});

test.afterEach(async ({ page }) => {
  for (const name of KEYS) expect((await page.request.delete(`/api/keys/${name}`)).ok()).toBe(true);
});

const KEEP = /Keep keys in the Test Keychain/;

async function keysOf(page: Page) {
  return (await page.request.get("/api/keys")).json();
}

// What the server tells of the keys, for a test to say instead of it
function told(changes: Record<string, unknown> = {}) {
  return {
    settable: KEYS,
    providers: [
      { provider: "OpenAI", variables: ["OPENAI_API_KEY"], missing: [], ready: true },
      { provider: "Anthropic", variables: ["ANTHROPIC_API_KEY"], missing: ["ANTHROPIC_API_KEY"], ready: false },
      { provider: "Gemini", variables: ["GEMINI_API_KEY"], missing: ["GEMINI_API_KEY"], ready: false },
      { provider: "Groq", variables: ["GROQ_API_KEY"], missing: ["GROQ_API_KEY"], ready: false },
    ],
    keychain: { available: true, name: "Test Keychain", problem: null },
    sources: {},
    problem: null,
    ...changes,
  };
}

test.describe("keeping the keys in the keychain", () => {
  test("a key that is given is kept in it, which is said, and shows where it is kept", async ({ page }) => {
    const secret = "sk-test-in-the-keychain";
    const dialog = await openSettings(page, "Keys");
    await dialog.getByLabel("OpenAI key", { exact: true }).fill(secret);
    const sent = page.waitForRequest((request) => request.method() === "PUT" && request.url().endsWith("/api/keys/OPENAI_API_KEY"));

    await dialog.getByRole("button", { name: "Save", exact: true }).first().click();

    // The person has not said not to, so the server is not told anything of the keychain
    expect((await sent).postDataJSON()).toEqual({ value: secret });
    await expect(dialog.getByText("Saved in the Test Keychain.", { exact: true })).toBeVisible();
    await expect(dialog.getByTestId("key-source-OPENAI_API_KEY")).toHaveText("In the Test Keychain");
    await expect(dialog.getByTestId("key-warning-OPENAI_API_KEY")).toHaveCount(0);
    const shown = await keysOf(page);
    expect(shown.sources).toEqual({ OPENAI_API_KEY: "keychain" });
    expect(shown.keychain).toEqual({ available: true, name: "Test Keychain", problem: null });
    expect(JSON.stringify(shown)).not.toContain(secret);

    // It is where it was kept when the page is opened again
    await page.reload();
    const again = await openSettings(page, "Keys");
    await expect(again.getByTestId("key-source-OPENAI_API_KEY")).toHaveText("In the Test Keychain");

    await again.getByRole("button", { name: "Remove the OpenAI key" }).click();

    await expect(again.getByText("Removed.", { exact: true })).toBeVisible();
    await expect(again.getByTestId("key-source-OPENAI_API_KEY")).toHaveCount(0);
    expect((await keysOf(page)).sources).toEqual({});
  });

  test("keeping them is said in the note, and can be chosen against, which the browser remembers", async ({ page }) => {
    const dialog = await openSettings(page, "Keys");
    const keep = dialog.getByRole("checkbox", { name: KEEP });
    await expect(keep).toBeChecked();
    await expect(dialog.getByText("so that it is there when the server is started again")).toBeVisible();

    await keep.uncheck();

    await expect(dialog.getByText("A key you give is kept until the server stops, and one kept before is forgotten.")).toBeVisible();
    await page.reload();
    const again = await openSettings(page, "Keys");
    await expect(again.getByRole("checkbox", { name: KEEP })).not.toBeChecked();

    await again.getByRole("checkbox", { name: KEEP }).check();
    await page.reload();
    const last = await openSettings(page, "Keys");
    await expect(last.getByRole("checkbox", { name: KEEP })).toBeChecked();
  });

  test("a key given with keeping chosen against is kept until the server stops, and says so", async ({ page }) => {
    const dialog = await openSettings(page, "Keys");
    await dialog.getByRole("checkbox", { name: KEEP }).uncheck();
    await dialog.getByLabel("Groq key", { exact: true }).fill("gsk-test-for-now");
    const sent = page.waitForRequest((request) => request.method() === "PUT" && request.url().endsWith("/api/keys/GROQ_API_KEY"));

    await dialog.getByRole("button", { name: "Save", exact: true }).nth(3).click();

    expect((await sent).postDataJSON()).toEqual({ value: "gsk-test-for-now", remember: false });
    await expect(dialog.getByText("Saved until the server stops.", { exact: true })).toBeVisible();
    await expect(dialog.getByTestId("key-source-GROQ_API_KEY")).toHaveText("Until the server stops");
    expect((await keysOf(page)).sources).toEqual({ GROQ_API_KEY: "session" });

    // Another, given once it is chosen for again, is kept
    await dialog.getByRole("checkbox", { name: KEEP }).check();
    await dialog.getByLabel("Gemini key", { exact: true }).fill("gm-test-kept");
    await dialog.getByRole("button", { name: "Save", exact: true }).nth(2).click();

    await expect(dialog.getByTestId("key-source-GEMINI_API_KEY")).toHaveText("In the Test Keychain");
    expect((await keysOf(page)).sources).toEqual({ GROQ_API_KEY: "session", GEMINI_API_KEY: "keychain" });
  });

  test("says when the keychain would not keep a key that was set all the same", async ({ page }) => {
    const warning = "The key is set until the server stops. The Test Keychain would not keep the key: User canceled the request";
    await page.route("**/api/keys/GROQ_API_KEY", (route) =>
      route.fulfill({
        json: told({ sources: { GROQ_API_KEY: "session" }, problem: warning, providers: told().providers.map((p) => ({ ...p, missing: [], ready: true })) }),
      }),
    );
    const dialog = await openSettings(page, "Keys");
    const key = dialog.getByLabel("Groq key", { exact: true });

    await key.fill("gsk-test");
    await dialog.getByRole("button", { name: "Save", exact: true }).nth(3).click();

    await expect(dialog.getByText("Saved until the server stops.", { exact: true })).toBeVisible();
    await expect(dialog.getByTestId("key-warning-GROQ_API_KEY")).toHaveText(warning);
    await expect(dialog.getByTestId("key-warning-GROQ_API_KEY")).toHaveAttribute("role", "alert");
    await expect(dialog.getByTestId("key-state-GROQ_API_KEY")).toHaveText("Set");
    await expect(dialog.getByTestId("key-source-GROQ_API_KEY")).toHaveText("Until the server stops");

    // What is said of the last change goes when another is begun, by typing, or by taking the key away
    await key.fill("gsk-another");
    await expect(dialog.getByTestId("key-warning-GROQ_API_KEY")).toHaveCount(0);
  });

  test("says of a change that the server refuses only that, and not what was said of the one before it", async ({ page }) => {
    const warning = "The key is set until the server stops. The Test Keychain would not keep the key: User canceled the request";
    await page.route("**/api/keys/GROQ_API_KEY", (route) =>
      route.fulfill({
        json: told({
          sources: { GROQ_API_KEY: "session" },
          problem: warning,
          providers: told().providers.map((p) => ({ ...p, missing: [], ready: true })),
        }),
      }),
    );
    const dialog = await openSettings(page, "Keys");
    await dialog.getByLabel("Groq key", { exact: true }).fill("gsk-test");
    await dialog.getByRole("button", { name: "Save", exact: true }).nth(3).click();
    await expect(dialog.getByTestId("key-warning-GROQ_API_KEY")).toHaveText(warning);
    await page.unroute("**/api/keys/GROQ_API_KEY");
    const refusal = "The key cannot be taken away";
    await page.route("**/api/keys/GROQ_API_KEY", (route) =>
      route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "invalid", message: refusal } }),
      }),
    );

    await dialog.getByRole("button", { name: "Remove the Groq key" }).click();

    await expect(dialog.getByRole("alert")).toHaveText(refusal);
    await expect(dialog.getByTestId("key-warning-GROQ_API_KEY")).toHaveCount(0);
  });

  test("says when the keychain would not forget a key that was taken away", async ({ page }) => {
    const warning = "The key is taken away until the server is started again, and may be back then. The Test Keychain would not forget the key: denied";
    expect((await page.request.put("/api/keys/GROQ_API_KEY", { data: { value: "gsk-test" } })).ok()).toBe(true);
    await page.route("**/api/keys/GROQ_API_KEY", (route) => route.fulfill({ json: told({ problem: warning }) }));
    await page.reload();
    const dialog = await openSettings(page, "Keys");

    await dialog.getByRole("button", { name: "Remove the Groq key" }).click();

    await expect(dialog.getByText("Removed.", { exact: true })).toBeVisible();
    await expect(dialog.getByTestId("key-warning-GROQ_API_KEY")).toHaveText(warning);
  });

  test("says where there is no keychain, and why, and offers no choice about it", async ({ page }) => {
    const why = "This machine has no keychain that the keyring package can use";
    await page.route("**/api/keys", (route) => route.fulfill({ json: told({ keychain: { available: false, name: null, problem: why } }) }));

    const dialog = await openSettings(page, "Keys");

    await expect(dialog.getByText("A key you give here is kept by the server until it stops.")).toBeVisible();
    await expect(dialog.getByTestId("keychain-problem")).toHaveText(why);
    await expect(dialog.getByRole("checkbox", { name: /Keep keys/ })).toHaveCount(0);
  });

  test("says nothing of why where there is no keychain and nothing to say of it", async ({ page }) => {
    await page.route("**/api/keys", (route) => route.fulfill({ json: told({ keychain: { available: false, name: null, problem: null } }) }));

    const dialog = await openSettings(page, "Keys");

    await expect(dialog.getByText("A key you give here is kept by the server until it stops.")).toBeVisible();
    await expect(dialog.getByTestId("keychain-problem")).toHaveCount(0);
  });

  test("says that keys kept earlier were not read, and still offers the keychain for keys given now", async ({ page }) => {
    const why = "Keys kept earlier were not read. The Test Keychain did not answer in 5 seconds: it may be waiting to be unlocked";
    await page.route("**/api/keys", (route) => route.fulfill({ json: told({ keychain: { available: true, name: "Test Keychain", problem: why } }) }));

    const dialog = await openSettings(page, "Keys");

    await expect(dialog.getByTestId("keychain-problem")).toHaveText(why);
    await expect(dialog.getByRole("checkbox", { name: KEEP })).toBeChecked();
  });

  test("says of a key the server was started with that it is from the environment", async ({ page }) => {
    await page.route("**/api/keys", (route) => route.fulfill({ json: told({ sources: { OPENAI_API_KEY: "environment" } }) }));

    const dialog = await openSettings(page, "Keys");

    await expect(dialog.getByTestId("key-source-OPENAI_API_KEY")).toHaveText("From the server's environment");
    await expect(dialog.getByTestId("key-source-GROQ_API_KEY")).toHaveCount(0);
  });
});
