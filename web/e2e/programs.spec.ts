import { randomBytes } from "node:crypto";
import type { Page } from "@playwright/test";
import { accessibilityProblems } from "./axe";
import { answered, expect, test } from "./fixtures";

// Every program the tests make is listed for all of them, so a name that only one test has keeps what it looks for from being
// found in another's
const tag = () => randomBytes(3).toString("hex");

const message = (page: Page) => page.getByRole("textbox", { name: "Message" });
const nameField = (page: Page) => page.getByRole("textbox", { name: "Name" });
const instructionsField = (page: Page) => page.getByRole("textbox", { name: "Instructions" });
const kind = (page: Page, name: "Quick task" | "Custom program") => page.getByRole("radio", { name });

async function infoOf(page: Page, id: string) {
  const found = await page.request.get(`/api/chats/${id}`);
  expect(found.status()).toBe(200);

  return found.json();
}

async function send(page: Page, text: string): Promise<string> {
  await message(page).fill(text);
  await page.getByRole("button", { name: "Send" }).click();
  await page.waitForURL(/\/chat\?id=/);

  return new URL(page.url()).searchParams.get("id") ?? "";
}

test.describe("beginning a program", () => {
  test("is as a quick task unless another is chosen, with nothing more to fill in", async ({ page }) => {
    await expect(kind(page, "Quick task")).toBeChecked();
    await expect(kind(page, "Custom program")).not.toBeChecked();
    await expect(nameField(page)).toHaveCount(0);
    await expect(instructionsField(page)).toHaveCount(0);

    const question = `A quick task ${tag()}`;
    const id = await send(page, question);
    await answered(page, `You asked: ${question}`);

    expect(await infoOf(page, id)).toMatchObject({ title: question, config: { kind: "quick_task", instructions: "" } });
    await expect(page.getByTestId("program-instructions-button")).toHaveCount(0);
    const row = page.getByRole("navigation", { name: "Programs" }).getByRole("link", { name: question });
    await expect(row).toBeVisible();
    await expect(row.getByTestId("program-kind")).toHaveCount(0);
  });

  test("is as a custom program with a name and instructions of its own, which the lead is given", async ({ page }) => {
    const name = `Weekly review ${tag()}`;
    const instructions = `Answer in two short lines, ${tag()}.`;

    await kind(page, "Custom program").check();
    await expect(page.getByTestId("program-kind-about")).toContainText("instructions of its own");
    await nameField(page).fill(name);
    await instructionsField(page).fill(`  ${instructions}\n`);
    const id = await send(page, "instructions: what were you told?");
    await answered(page, `Given instructions: ${instructions}`);

    expect(await infoOf(page, id)).toMatchObject({ title: name, config: { kind: "custom", instructions } });
    await expect(page.getByTestId("chat-title")).toHaveText(name);

    const row = page.getByRole("navigation", { name: "Programs" }).getByRole("link", { name: new RegExp(name) });
    await expect(row.getByTestId("program-kind")).toHaveText("Custom");

    // What it was told is shown again with the page opened afresh, and is still what the lead is given in a later message
    await page.reload();
    await expect(page.getByTestId("chat-title")).toHaveText(name);
    await page.getByTestId("program-instructions-button").click();
    const dialog = page.getByTestId("program-instructions");
    await expect(dialog.getByRole("heading", { name: `Instructions of ${name}` })).toBeVisible();
    await expect(dialog.getByRole("region", { name: "Instructions" })).toHaveText(instructions);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);

    await message(page).fill("instructions: and now?");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByTestId("lead-message").last()).toContainText(`Given instructions: ${instructions}`);
    await expect(page.getByTestId("lead-message")).toHaveCount(2);
  });

  test("asks for the name and the instructions that are missing, and begins nothing until they are there", async ({ page }) => {
    let begun = 0;
    page.on("request", (request) => {
      if (request.method() === "POST" && new URL(request.url()).pathname === "/api/chats") begun += 1;
    });

    await kind(page, "Custom program").check();
    await message(page).fill("A question for a program that has no name");
    await page.getByRole("button", { name: "Send" }).click();

    await expect(page.getByText("A custom program needs a name.")).toBeVisible();
    await expect(page.getByText(/A custom program needs instructions/)).toBeVisible();
    await expect(nameField(page)).toBeFocused();
    await expect(nameField(page)).toHaveAttribute("aria-invalid", "true");
    await expect(message(page)).toHaveValue("A question for a program that has no name");

    await nameField(page).fill(`Named ${tag()}`);
    await expect(page.getByText("A custom program needs a name.")).toHaveCount(0);
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText(/A custom program needs instructions/)).toBeVisible();
    await expect(instructionsField(page)).toBeFocused();

    await instructionsField(page).fill("a".repeat(8001));
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Instructions are at most 8,000 characters, and these are 8,001.")).toBeVisible();

    expect(begun).toBe(0);
    await expect(page).not.toHaveURL(/\/chat/);
  });

  test("has the spending limit that is chosen for it, which is the settings' where none is", async ({ page }) => {
    await kind(page, "Custom program").check();
    const limit = page.getByTestId("program-spending");
    await expect(limit).toHaveText("Spending limit: $2");

    await limit.click();
    const panel = page.getByTestId("limits-dialog");
    await panel.getByRole("textbox", { name: "Spending limit (US dollars)" }).fill("0.5");
    await panel.getByTestId("limits-save").click();
    await expect(panel).toHaveCount(0);
    await expect(limit).toHaveText("Spending limit: $0.5");

    await nameField(page).fill(`Costing ${tag()}`);
    await instructionsField(page).fill("Be brief.");
    const id = await send(page, "A question under a limit");
    await answered(page, "You asked: A question under a limit");

    expect(await infoOf(page, id)).toMatchObject({ max_cost: 0.5, config: { kind: "custom" } });
  });

  test("shows the choice and the custom program's form without anything wrong for someone who cannot see them", async ({ page }) => {
    expect(await accessibilityProblems(page, ["heading-order"])).toEqual([]);

    await kind(page, "Custom program").check();
    await nameField(page).fill(`Seen ${tag()}`);
    await instructionsField(page).fill("Be brief.");
    expect(await accessibilityProblems(page, ["heading-order"])).toEqual([]);

    await message(page).fill("A question");
    await page.getByRole("button", { name: "Send" }).click();
    await page.waitForURL(/\/chat\?id=/);
    await answered(page, "You asked: A question");

    await page.getByTestId("program-instructions-button").click();
    await expect(page.getByTestId("program-instructions")).toBeVisible();
    await expect(page.getByTestId("program-instructions")).toHaveCSS("opacity", "1");
    expect(await accessibilityProblems(page, ["heading-order", "aria-hidden-focus", "region", "page-has-heading-one"])).toEqual([]);
  });
});
