import os from "node:os";
import path from "node:path";
import { expect, test } from "../fixtures";
import { openSettings, resetSettings, settings } from "./state";

// Every test here changes what the server is set up with, which they share, so each puts it back and none is run beside
// another
test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await resetSettings(page);
  await page.reload();
});

const SAVED = "Saved. New conversations use these settings.";

test.describe("the settings", () => {
  test("open from the sidebar, show what they are, and close with the button or with Escape, giving the focus back", async ({ page }) => {
    const gear = page.getByRole("button", { name: "Settings", exact: true });
    const dialog = await openSettings(page);

    await expect(dialog.getByRole("tab", { name: "Model" })).toHaveAttribute("aria-selected", "true");
    await expect(dialog.getByRole("combobox", { name: "Model", exact: true })).toHaveValue("gpt-5.2");
    await expect(dialog.getByLabel(/Spending limit/)).toHaveValue("2");
    await expect(dialog.getByRole("checkbox", { name: /Show replies/ })).toBeChecked();
    await expect(dialog.getByRole("button", { name: "Save changes" })).toHaveCount(0);

    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(gear).toBeFocused();

    await openSettings(page);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(gear).toBeFocused();

    await openSettings(page);
    await dialog.getByRole("button", { name: "Close the settings" }).click();
    await expect(dialog).toHaveCount(0);
  });

  test("keep a model that is chosen, which the home page shows, and which is there when they are opened again", async ({ page }) => {
    const dialog = await openSettings(page);

    await dialog.getByRole("combobox", { name: "Model", exact: true }).selectOption("claude-sonnet-4-5");
    await dialog.getByRole("button", { name: "Save changes" }).click();

    await expect(dialog.getByText(SAVED)).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Save changes" })).toHaveCount(0);
    expect((await settings(page)).model).toBe("claude-sonnet-4-5");

    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(page.getByText("claude-sonnet-4-5", { exact: true })).toBeVisible();

    await page.reload();
    const again = await openSettings(page);
    await expect(again.getByRole("combobox", { name: "Model", exact: true })).toHaveValue("claude-sonnet-4-5");
  });

  test("send only what was changed, so that a setting changed meanwhile is not undone", async ({ page }) => {
    const dialog = await openSettings(page);
    expect((await page.request.patch("/api/settings", { data: { stream: false } })).ok()).toBe(true);

    await dialog.getByLabel(/Spending limit/).fill("9");
    const sent = page.waitForRequest((request) => request.method() === "PATCH" && request.url().endsWith("/api/settings"));
    await dialog.getByRole("button", { name: "Save changes" }).click();

    expect((await sent).postDataJSON()).toEqual({ max_cost: 9 });
    await expect(dialog.getByText(SAVED)).toBeVisible();
    expect(await settings(page)).toMatchObject({ max_cost: 9, stream: false });
  });

  test("say which models need a key, and take the person to where it is given", async ({ page }) => {
    const dialog = await openSettings(page);
    const model = dialog.getByRole("combobox", { name: "Model", exact: true });

    await expect(model.locator("option", { hasText: "gpt-5.2 (needs a key)" })).toHaveCount(1);
    await expect(dialog.getByText("This model needs OPENAI_API_KEY, which is not set.")).toBeVisible();
    // The models are grouped by whose they are
    await expect(model.locator('optgroup[label="OpenAI"] option[value="gpt-5.2"]')).toHaveCount(1);
    await expect(model.locator('optgroup[label="Anthropic"] option[value="claude-sonnet-4-5"]')).toHaveCount(1);

    await model.selectOption("claude-sonnet-4-5");
    await expect(dialog.getByText("This model needs ANTHROPIC_API_KEY, which is not set.")).toBeVisible();
    await dialog.getByRole("button", { name: "Add it" }).click();

    await expect(dialog.getByRole("tab", { name: "Keys" })).toHaveAttribute("aria-selected", "true");
    await expect(dialog.getByLabel("Anthropic key", { exact: true })).toBeVisible();
    // What was chosen is kept while the key is given
    await dialog.getByRole("tab", { name: "Model" }).click();
    await expect(model).toHaveValue("claude-sonnet-4-5");
  });

  test("take a spending limit as dollars, or none, and refuse what is not an amount", async ({ page }) => {
    const dialog = await openSettings(page);
    const limit = dialog.getByLabel(/Spending limit/);
    const save = dialog.getByRole("button", { name: "Save changes" });

    await limit.fill("lots");
    await expect(dialog.getByRole("alert").filter({ hasText: "an amount in dollars" })).toBeVisible();
    await expect(limit).toHaveAttribute("aria-invalid", "true");
    await expect(save).toBeDisabled();

    await limit.fill("$7.50");
    await expect(dialog.getByRole("alert")).toHaveCount(0);
    await save.click();
    await expect(dialog.getByText(SAVED)).toBeVisible();
    expect((await settings(page)).max_cost).toBe(7.5);
    await expect(limit).toHaveValue("7.5");

    await limit.fill("");
    await save.click();
    await expect(dialog.getByText(SAVED)).toBeVisible();
    expect((await settings(page)).max_cost).toBeNull();
    await expect(limit).toHaveValue("");
  });

  test("take the name of a model that is not offered, and say why the server refuses one it cannot use", async ({ page }) => {
    const dialog = await openSettings(page);
    const picker = dialog.getByRole("combobox", { name: "Model", exact: true });

    await picker.selectOption({ label: "Another model…" });
    const name = dialog.getByRole("textbox", { name: "Name of the model" });
    await expect(name).toHaveValue("gpt-5.2");

    await name.fill("nonsense-model-xyz");
    await dialog.getByRole("button", { name: "Save changes" }).click();
    await expect(dialog.getByRole("alert")).toContainText("nonsense-model-xyz");
    expect((await settings(page)).model).toBe("gpt-5.2");
    await expect(dialog.getByRole("button", { name: "Save changes" })).toBeEnabled();

    await name.fill("claude-my-own-model");
    await expect(dialog.getByRole("alert")).toHaveCount(0);
    await dialog.getByRole("button", { name: "Save changes" }).click();
    await expect(dialog.getByText(SAVED)).toBeVisible();
    expect((await settings(page)).model).toBe("claude-my-own-model");

    await page.reload();
    const again = await openSettings(page);
    await expect(again.getByRole("combobox", { name: "Model", exact: true }).locator("option:checked")).toHaveText("Another model…");
    await expect(again.getByRole("textbox", { name: "Name of the model" })).toHaveValue("claude-my-own-model");
  });

  test("say that a model needs every key its provider does, when it needs more than one", async ({ page }) => {
    await page.route("**/api/models", (route) =>
      route.fulfill({
        json: { default: "gpt-5.2", models: [{ id: "gpt-5.2", provider: "AzureOpenAI", ready: false }] },
      }),
    );
    await page.route("**/api/keys", (route) =>
      route.fulfill({
        json: {
          settable: ["OPENAI_API_KEY"],
          providers: [
            {
              provider: "AzureOpenAI",
              variables: ["OPENAI_API_KEY", "OPENAI_ENDPOINT"],
              missing: ["OPENAI_API_KEY", "OPENAI_ENDPOINT"],
              ready: false,
            },
          ],
        },
      }),
    );
    const dialog = await openSettings(page);

    await expect(dialog.getByText("This model needs OPENAI_API_KEY, OPENAI_ENDPOINT, which are not set.")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Add them" })).toBeVisible();
  });

  test("name the model when the models cannot be listed, and say so", async ({ page }) => {
    await page.route("**/api/models", (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "internal", message: "The models are not known just now." } }),
      }),
    );
    const dialog = await openSettings(page);

    await expect(dialog.getByText("The list of models could not be read, so the model is named here.")).toBeVisible();
    const name = dialog.getByRole("textbox", { name: "Model", exact: true });
    await expect(name).toHaveValue("gpt-5.2");
    await expect(dialog.getByRole("combobox", { name: "Model", exact: true })).toHaveCount(0);

    await name.fill("claude-my-own-model");
    await dialog.getByRole("button", { name: "Save changes" }).click();
    await expect(dialog.getByText(SAVED)).toBeVisible();
    expect((await settings(page)).model).toBe("claude-my-own-model");
  });

  test("refuse a model with no name, and go back to the models that are offered", async ({ page }) => {
    const dialog = await openSettings(page);
    const picker = dialog.getByRole("combobox", { name: "Model", exact: true });

    await picker.selectOption({ label: "Another model…" });
    await dialog.getByRole("textbox", { name: "Name of the model" }).fill("  ");
    await expect(dialog.getByRole("alert")).toHaveText("Choose a model.");
    await expect(dialog.getByRole("button", { name: "Save changes" })).toBeDisabled();

    await picker.selectOption("gpt-5");
    await expect(dialog.getByRole("textbox", { name: "Name of the model" })).toHaveCount(0);
    await expect(dialog.getByRole("alert")).toHaveCount(0);
    await dialog.getByRole("button", { name: "Save changes" }).click();
    await expect(dialog.getByText(SAVED)).toBeVisible();
    expect((await settings(page)).model).toBe("gpt-5");
  });

  test("keep whether replies are shown as they are written", async ({ page }) => {
    const dialog = await openSettings(page);

    await dialog.getByRole("checkbox", { name: /Show replies/ }).uncheck();
    await dialog.getByRole("button", { name: "Save changes" }).click();

    await expect(dialog.getByText(SAVED)).toBeVisible();
    expect((await settings(page)).stream).toBe(false);
  });
});

test.describe("the code settings", () => {
  test("show what each place for code needs, and nothing of what it does not", async ({ page }) => {
    const dialog = await openSettings(page, "Code");

    await expect(dialog.getByRole("radio", { name: /Nowhere/ })).toBeChecked();
    await expect(dialog.getByRole("combobox", { name: "Image" })).toHaveCount(0);
    await expect(dialog.getByLabel("Python to run code with")).toHaveCount(0);

    await dialog.getByRole("radio", { name: /In a Docker container/ }).check();
    await expect(dialog.getByRole("combobox", { name: "Image" })).toHaveValue("python");
    await expect(dialog.getByRole("checkbox", { name: /Code can reach the network/ })).toBeChecked();
    await expect(dialog.getByLabel("Data lake")).toHaveCount(0);
    await expect(dialog.getByLabel("Python to run code with")).toHaveCount(0);
    await expect(dialog.getByRole("checkbox", { name: /OpenAI key/ })).not.toBeChecked();

    await dialog.getByRole("combobox", { name: "Image" }).selectOption("bio");
    await expect(dialog.getByText("Adds Biomni's bioinformatics tools")).toBeVisible();
    await expect(dialog.getByLabel("Data lake")).toBeVisible();

    await dialog.getByRole("radio", { name: /On this computer/ }).check();
    await expect(dialog.getByRole("combobox", { name: "Image" })).toHaveCount(0);
    await expect(dialog.getByLabel("Python to run code with")).toBeVisible();
    await expect(dialog.getByText("is not held in anything")).toBeVisible();
  });

  test("keep Docker, its image, the network, the data lake, and the keys that code reads", async ({ page }) => {
    const lake = path.join(os.tmpdir(), "vl-e2e-data-lake");
    const dialog = await openSettings(page, "Code");

    await dialog.getByRole("radio", { name: /In a Docker container/ }).check();
    await dialog.getByRole("combobox", { name: "Image" }).selectOption("bio");
    await dialog.getByRole("checkbox", { name: /Code can reach the network/ }).uncheck();
    await dialog.getByLabel("Data lake").fill(lake);
    await dialog.getByRole("checkbox", { name: /OpenAI key/ }).check();
    await dialog.getByRole("checkbox", { name: /Groq key/ }).check();
    await dialog.getByRole("checkbox", { name: /Groq key/ }).uncheck();
    await dialog.getByRole("button", { name: "Save changes" }).click();

    await expect(dialog.getByText(SAVED)).toBeVisible();
    const kept = await settings(page);
    expect(kept).toMatchObject({ code: "docker", sandbox: "bio", network: false, forward_keys: ["OPENAI_API_KEY"] });
    expect(kept.data_lake).toMatch(/vl-e2e-data-lake$/);

    await page.reload();
    const again = await openSettings(page, "Code");
    await expect(again.getByRole("radio", { name: /In a Docker container/ })).toBeChecked();
    await expect(again.getByRole("combobox", { name: "Image" })).toHaveValue("bio");
    await expect(again.getByRole("checkbox", { name: /Code can reach the network/ })).not.toBeChecked();
    await expect(again.getByRole("checkbox", { name: /OpenAI key/ })).toBeChecked();
    await expect(again.getByRole("checkbox", { name: /Groq key/ })).not.toBeChecked();
    await expect(again.getByLabel("Data lake")).toHaveValue(kept.data_lake);
  });

  test("say what the server refuses of the data lake, and keep what was typed", async ({ page }) => {
    const dialog = await openSettings(page, "Code");

    await dialog.getByRole("radio", { name: /In a Docker container/ }).check();
    await dialog.getByRole("combobox", { name: "Image" }).selectOption("base");
    await dialog.getByLabel("Data lake").fill("relative/folder");
    await dialog.getByRole("button", { name: "Save changes" }).click();

    await expect(dialog.getByRole("alert")).toContainText("a full path");
    await expect(dialog.getByLabel("Data lake")).toHaveValue("relative/folder");
    expect((await settings(page)).code).toBe("none");
  });

  test("keep the Python that code runs with on this computer", async ({ page }) => {
    const dialog = await openSettings(page, "Code");

    await dialog.getByRole("radio", { name: /On this computer/ }).check();
    await dialog.getByLabel("Python to run code with").fill(" /usr/bin/python3 ");
    await dialog.getByRole("button", { name: "Save changes" }).click();

    await expect(dialog.getByText(SAVED)).toBeVisible();
    expect(await settings(page)).toMatchObject({ code: "local", python: "/usr/bin/python3" });
  });

  test("say which keys that code can read are not set", async ({ page }) => {
    expect((await page.request.put("/api/keys/GROQ_API_KEY", { data: { value: "gsk-test" } })).ok()).toBe(true);
    const dialog = await openSettings(page, "Code");
    await dialog.getByRole("radio", { name: /In a Docker container/ }).check();

    await expect(dialog.getByText("Not set", { exact: true })).toHaveCount(3);
    await expect(dialog.getByRole("checkbox", { name: /Groq key/ })).toBeVisible();
    await expect(dialog.getByText("Code cannot run while one of them is not set.")).toBeVisible();
  });
});

test.describe("the keys", () => {
  test("show whose each key is, and that none is set", async ({ page }) => {
    const dialog = await openSettings(page, "Keys");

    for (const [provider, name] of [
      ["OpenAI", "OPENAI_API_KEY"],
      ["Anthropic", "ANTHROPIC_API_KEY"],
      ["Gemini", "GEMINI_API_KEY"],
      ["Groq", "GROQ_API_KEY"],
    ]) {
      await expect(dialog.getByLabel(`${provider} key`, { exact: true })).toBeVisible();
      await expect(dialog.getByTestId(`key-state-${name}`)).toHaveText("Not set");
    }
    await expect(dialog.getByText("It is not written to disk")).toBeVisible();
  });

  test("keep a key for the server, which is never shown again, and which makes its models ready", async ({ page }) => {
    const secret = "sk-test-0123456789-secret";
    const dialog = await openSettings(page, "Keys");
    const key = dialog.getByLabel("OpenAI key", { exact: true });
    const save = dialog.getByRole("button", { name: "Save", exact: true }).first();

    await expect(key).toHaveAttribute("type", "password");
    await expect(save).toBeDisabled();

    await key.fill(secret);
    const answered = page.waitForResponse((response) => response.url().endsWith("/api/keys/OPENAI_API_KEY"));
    await save.click();

    expect(await (await answered).text()).not.toContain(secret);
    await expect(dialog.getByTestId("key-state-OPENAI_API_KEY")).toHaveText("Set");
    await expect(dialog.getByText("Saved", { exact: true })).toBeVisible();
    await expect(key).toHaveValue("");
    await expect(dialog).not.toContainText(secret);
    expect(await (await page.request.get("/api/keys")).text()).not.toContain(secret);
    expect((await (await page.request.get("/api/keys")).json()).providers[0]).toMatchObject({ provider: "OpenAI", ready: true });

    // The models of the provider are no longer said to need it, and those of the others still are
    await dialog.getByRole("tab", { name: "Model" }).click();
    const model = dialog.getByRole("combobox", { name: "Model", exact: true });
    await expect(model.locator("option", { hasText: "gpt-5.2 (needs a key)" })).toHaveCount(0);
    await expect(model.locator("option", { hasText: "claude-sonnet-4-5 (needs a key)" })).toHaveCount(1);
    await expect(dialog.getByText("This model needs")).toHaveCount(0);

    await dialog.getByRole("tab", { name: "Keys" }).click();
    await dialog.getByRole("button", { name: "Remove the OpenAI key" }).click();
    await expect(dialog.getByTestId("key-state-OPENAI_API_KEY")).toHaveText("Not set");
    await expect(dialog.getByText("Removed", { exact: true })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Remove the OpenAI key" })).toHaveCount(0);

    await dialog.getByRole("tab", { name: "Model" }).click();
    await expect(model.locator("option", { hasText: "gpt-5.2 (needs a key)" })).toHaveCount(1);
  });

  test("say why the server refuses a key, and keep what was pasted to try again", async ({ page }) => {
    const dialog = await openSettings(page, "Keys");
    const key = dialog.getByLabel("Gemini key", { exact: true });
    await page.route("**/api/keys/GEMINI_API_KEY", (route) =>
      route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "invalid", message: "A key is on one line, with nothing else in it" } }),
      }),
    );

    await key.fill("gm-test");
    await key.press("Enter");

    await expect(dialog.getByRole("alert")).toHaveText("A key is on one line, with nothing else in it");
    await expect(key).toHaveValue("gm-test");
    await expect(dialog.getByTestId("key-state-GEMINI_API_KEY")).toHaveText("Not set");

    await page.unroute("**/api/keys/GEMINI_API_KEY");
    await key.press("Enter");
    await expect(dialog.getByTestId("key-state-GEMINI_API_KEY")).toHaveText("Set");
    await expect(dialog.getByRole("alert")).toHaveCount(0);
  });

  test("give the server the key without the spaces round it", async ({ page }) => {
    const dialog = await openSettings(page, "Keys");

    await dialog.getByLabel("Groq key", { exact: true }).fill("  gsk-test  ");
    const sent = page.waitForRequest((request) => request.method() === "PUT" && request.url().endsWith("/api/keys/GROQ_API_KEY"));
    await dialog.getByRole("button", { name: "Save", exact: true }).nth(3).click();

    expect((await sent).postDataJSON()).toEqual({ value: "gsk-test" });
    await expect(dialog.getByTestId("key-state-GROQ_API_KEY")).toHaveText("Set");
  });

  test("refuse a key that has nothing in it, or is not on one line, before the server is asked", async ({ page }) => {
    const dialog = await openSettings(page, "Keys");
    const key = dialog.getByLabel("Groq key", { exact: true });
    const asked: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "PUT") asked.push(request.url());
    });

    // Nothing in it cannot be sent, and has no Save to send it with
    await key.fill("   ");
    await expect(dialog.getByRole("button", { name: "Save", exact: true }).nth(3)).toBeDisabled();

    // The server would refuse a tab in it, which the page says first
    await key.fill("gsk-abc\tdef");
    await key.press("Enter");

    await expect(dialog.getByRole("alert")).toHaveText("A key is on one line, with nothing else in it.");
    await expect(dialog.getByTestId("key-state-GROQ_API_KEY")).toHaveText("Not set");
    expect(asked).toEqual([]);
  });
});

test.describe("closing with what is not saved", () => {
  test("ask before it is lost, and let the person go on, or give it up", async ({ page }) => {
    const dialog = await openSettings(page);
    const gear = page.getByRole("button", { name: "Settings", exact: true });
    await dialog.getByRole("checkbox", { name: /Show replies/ }).uncheck();

    await page.keyboard.press("Escape");
    await expect(dialog.getByText("What you changed is not saved.")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Keep editing" })).toBeFocused();

    // Asking again takes the question back, and does not lose what was changed
    await page.keyboard.press("Escape");
    await expect(dialog.getByText("What you changed is not saved.")).toHaveCount(0);
    await expect(dialog.getByRole("checkbox", { name: /Show replies/ })).not.toBeChecked();

    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await dialog.getByRole("button", { name: "Keep editing" }).click();
    await expect(dialog.getByText("What you changed is not saved.")).toHaveCount(0);

    await page.mouse.click(5, 5);
    await expect(dialog.getByText("What you changed is not saved.")).toBeVisible();
    await dialog.getByRole("button", { name: "Discard the changes" }).click();

    await expect(dialog).toHaveCount(0);
    await expect(gear).toBeFocused();
    expect((await settings(page)).stream).toBe(true);
    const again = await openSettings(page);
    await expect(again.getByRole("checkbox", { name: /Show replies/ })).toBeChecked();
  });

  test("ask before closing what cannot be saved, since it is wrong, and has nothing that was changed", async ({ page }) => {
    const dialog = await openSettings(page);

    await dialog.getByLabel(/Spending limit/).fill("lots");
    await page.keyboard.press("Escape");
    await expect(dialog.getByText("What you changed is not saved.")).toBeVisible();
    await dialog.getByRole("button", { name: "Discard the changes" }).click();

    await expect(dialog).toHaveCount(0);
  });

  test("close without asking once what was changed is saved", async ({ page }) => {
    const dialog = await openSettings(page);

    await dialog.getByRole("checkbox", { name: /Show replies/ }).uncheck();
    await dialog.getByRole("button", { name: "Save changes" }).click();
    await expect(dialog.getByText(SAVED)).toBeVisible();
    await page.keyboard.press("Escape");

    await expect(dialog).toHaveCount(0);
  });

  test("close without asking when what was changed was changed back", async ({ page }) => {
    const dialog = await openSettings(page);
    const stream = dialog.getByRole("checkbox", { name: /Show replies/ });

    await stream.uncheck();
    await stream.check();
    await page.keyboard.press("Escape");

    await expect(dialog).toHaveCount(0);
  });
});

test.describe("a model whose key is missing", () => {
  test("is put right from where the server's refusal is told", async ({ page }) => {
    await page.route("**/api/chats", (route) =>
      route.request().method() === "POST"
        ? route.fulfill({
            status: 422,
            contentType: "application/json",
            body: JSON.stringify({
              error: { code: "missing_keys", message: "gpt-5.2 needs OPENAI_API_KEY, which is not set. Add it in the settings.", missing: ["OPENAI_API_KEY"] },
            }),
          })
        : route.continue(),
    );

    await page.getByRole("textbox", { name: "Message" }).fill("Something to ask");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "needs OPENAI_API_KEY" })).toBeVisible();

    await page.getByRole("button", { name: "Add the key" }).click();

    const dialog = page.getByRole("dialog", { name: "Settings" });
    await expect(dialog.getByRole("tab", { name: "Keys" })).toHaveAttribute("aria-selected", "true");
    await dialog.getByLabel("OpenAI key", { exact: true }).fill("sk-test-for-the-refused-message");
    await dialog.getByLabel("OpenAI key", { exact: true }).press("Enter");
    await expect(dialog.getByTestId("key-state-OPENAI_API_KEY")).toHaveText("Set");
    await dialog.getByRole("button", { name: "Close", exact: true }).click();

    // What was written is where it was left, and goes now
    await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("Something to ask");
    await page.unroute("**/api/chats");
    await page.getByRole("button", { name: "Send" }).click();
    await page.waitForURL(/\/chat\?id=/);
  });

  test("offers nothing for a refusal that the settings cannot put right", async ({ page }) => {
    await page.route("**/api/chats", (route) =>
      route.request().method() === "POST"
        ? route.fulfill({
            status: 422,
            contentType: "application/json",
            body: JSON.stringify({ error: { code: "invalid", message: "That cannot be started." } }),
          })
        : route.continue(),
    );

    await page.getByRole("textbox", { name: "Message" }).fill("Something to ask");
    await page.getByRole("button", { name: "Send" }).click();

    await expect(page.getByRole("alert").filter({ hasText: "That cannot be started." })).toBeVisible();
    await expect(page.getByRole("button", { name: "Add the key" })).toHaveCount(0);
  });
});

test.describe("on a narrow screen", () => {
  test.use({ viewport: { width: 390, height: 700 } });

  test("open from the drawer, fit the screen, and give the focus back", async ({ page }) => {
    await page.getByRole("button", { name: "Show the conversations" }).click();
    const gear = page.getByRole("button", { name: "Settings", exact: true });
    await gear.click();

    const dialog = page.getByRole("dialog", { name: "Settings" });
    await expect(dialog).toBeVisible();
    const box = await dialog.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.y + box!.height).toBeLessThanOrEqual(700);

    // Every part is reachable by scrolling it, and nothing makes the dialog wider than the screen
    await dialog.getByRole("tab", { name: "Code" }).click();
    await dialog.getByRole("radio", { name: /In a Docker container/ }).check();
    await dialog.getByRole("combobox", { name: "Image" }).selectOption("full");
    await expect(dialog.getByLabel("Data lake")).toBeVisible();
    const scrolled = await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth);
    expect(scrolled).toBe(true);

    await page.keyboard.press("Escape");
    await dialog.getByRole("button", { name: "Discard the changes" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(gear).toBeFocused();
  });
});
