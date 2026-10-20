import { answered, ask, expect, test } from "./fixtures";

const SONNET = "openrouter/anthropic/claude-sonnet-4.5";
const GEMINI = "openrouter/google/gemini-2.5-pro";

test.describe("choosing the model", () => {
  test("the model of a conversation to begin is searched for among all of OpenRouter's, and is the one it begins with", async ({
    page,
  }) => {
    await page.getByTestId("model-button").click();
    const dialog = page.getByTestId("model-dialog");
    await expect(dialog.getByRole("heading", { name: "Choose the model" })).toBeVisible();
    await expect(dialog.getByTestId("model-option").first()).toBeVisible();
    await expect(dialog.getByRole("status")).toHaveCount(0);

    // What OpenRouter lists is there with what it costs, and a router with no price, which depends on what it chooses
    await dialog.getByRole("textbox", { name: "Search the models" }).fill("openrouter gemini pro");
    const option = dialog.locator(`[data-model="${GEMINI}"]`);
    await expect(dialog.getByTestId("model-option")).toHaveCount(1);
    await expect(option).toContainText("Google: Gemini 2.5 Pro");
    await expect(option).toContainText("$1.25 in, $10 out per million tokens");
    await expect(option).toContainText("1M tokens");
    await dialog.getByRole("textbox", { name: "Search the models" }).fill("auto router");
    await expect(dialog.locator('[data-model="openrouter/auto"]')).not.toContainText("per million");
    await dialog.getByRole("textbox", { name: "Search the models" }).fill("free");
    await expect(dialog.locator('[data-model="openrouter/meta-llama/llama-3.3-70b-instruct:free"]')).toContainText("Free");

    await dialog.getByRole("textbox", { name: "Search the models" }).fill("gemini");
    await dialog.locator(`[data-model="${GEMINI}"]`).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByTestId("model-button")).toHaveText(GEMINI);

    await ask(page, "Which model are you?");
    await answered(page, "You asked: Which model are you?");
    await expect(page.getByTestId("model-button")).toContainText(GEMINI);
  });

  test("a conversation goes on from where it was with another model, and cannot be switched while it works", async ({ page }) => {
    await ask(page, "First question for the lead");
    await answered(page, "You asked: First question for the lead");
    await expect(page.getByTestId("model-button")).not.toContainText("openrouter");

    await page.getByTestId("model-button").click();
    const dialog = page.getByTestId("model-dialog");
    await expect(dialog.getByRole("heading", { name: "Change the model" })).toBeVisible();
    await dialog.getByRole("textbox", { name: "Search the models" }).fill("claude sonnet");
    await dialog.locator(`[data-model="${SONNET}"]`).click();

    await expect(dialog).toHaveCount(0);
    await expect(page.getByTestId("model-button")).toContainText(SONNET);
    // What was said stays
    await expect(page.getByTestId("user-message")).toHaveText("First question for the lead");
    await expect(page.getByTestId("lead-message")).toHaveCount(1);

    await page.getByRole("textbox", { name: "Message" }).fill("Second question for the lead");
    await page.getByRole("textbox", { name: "Message" }).press("Enter");
    await answered(page, "You asked: Second question for the lead");
    await expect(page.getByTestId("user-message")).toHaveText(["First question for the lead", "Second question for the lead"]);
    await expect(page.getByTestId("model-button")).toContainText(SONNET);

    // It is still the model after the page is opened again
    await page.reload();
    await expect(page.getByTestId("model-button")).toContainText(SONNET);
    await expect(page.getByTestId("lead-message")).toHaveCount(2);
  });

  test("a model that cannot be used is refused where it is chosen, and the conversation keeps its own", async ({ page }) => {
    await ask(page, "A question before a change");
    await answered(page, "You asked: A question before a change");
    const before = await page.getByTestId("model-button").innerText();

    await page.getByTestId("model-button").click();
    const dialog = page.getByTestId("model-dialog");
    await dialog.getByRole("textbox", { name: "Search the models" }).fill("mystery-model");
    await dialog.getByTestId("model-typed").click();

    await expect(dialog.getByRole("alert")).toContainText("Unable to determine the source");
    await dialog.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(page.getByTestId("model-button")).toHaveText(before);
  });
});
