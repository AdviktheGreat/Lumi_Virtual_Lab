import type { Locator, Page } from "@playwright/test";
import { answered, expect, test } from "../fixtures";
import { openSettings, resetTools } from "./state";

// The tools are the server's, which these tests change, so each turns them all back on and none is run beside another
test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await resetTools(page);
  await page.reload();
});

const box = (dialog: Locator, name: string) => dialog.getByRole("checkbox", { name: new RegExp(`^${name}\\b`) });

async function disabled(page: Page): Promise<string[]> {
  const { tools } = await (await page.request.get("/api/tools")).json();

  return tools.filter((tool: { enabled: boolean }) => !tool.enabled).map((tool: { name: string }) => tool.name);
}

// What the lead is offered in a conversation that is begun now
async function offeredNow(page: Page): Promise<string> {
  const made = await page.request.post("/api/chats", { data: { title: "Tools: what is offered" } });
  expect(made.status()).toBe(201);
  await page.goto(`/chat?id=${(await made.json()).id}`);
  await expect(page.getByRole("button", { name: "Attach files" })).toBeEnabled();
  await page.getByRole("textbox", { name: "Message" }).fill("tool:offered");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await answered(page, "Offered:");

  return (await page.getByTestId("lead-message").last().textContent()) ?? "";
}

test("the tools are listed by what they are for, all of them on to begin with", async ({ page }) => {
  const dialog = await openSettings(page, "Tools");

  for (const group of ["Literature", "Proteins and structures", "Chemistry", "Your files"]) {
    await expect(dialog.getByRole("group", { name: group })).toBeVisible();
  }
  await expect(dialog.getByTestId("tools-count")).toHaveText("All 17 are on");
  await expect(dialog.getByRole("group", { name: "Literature" }).getByRole("checkbox")).toHaveCount(5);
  await expect(box(dialog, "pubmed_search")).toBeChecked();
  await expect(dialog.getByText("Look inside a CSV, TSV, or Excel file", { exact: false })).toBeVisible();
  // Only the tool that needs code to be of use says so
  await expect(dialog.getByText("Needs code", { exact: true })).toHaveCount(1);
  await expect(dialog.getByRole("button", { name: "Turn all on" })).toHaveAttribute("aria-disabled", "true");
});

test("a tool that is turned off is kept at once, is off when the settings are opened again, and is not offered", async ({ page }) => {
  const dialog = await openSettings(page, "Tools");

  const sent = page.waitForRequest((request) => request.method() === "PUT" && request.url().endsWith("/api/tools"));
  await box(dialog, "pubmed_search").click();

  expect((await sent).postDataJSON()).toEqual({ disabled: ["pubmed_search"] });
  await expect(dialog.getByTestId("tools-count")).toHaveText("16 of 17 are on");
  await expect(box(dialog, "pubmed_search")).not.toBeChecked();
  await expect.poll(() => disabled(page)).toEqual(["pubmed_search"]);
  // Nothing is left to save, so closing asks nothing
  await expect(dialog.getByRole("button", { name: "Save changes" })).toHaveCount(0);

  await page.reload();
  const again = await openSettings(page, "Tools");
  await expect(box(again, "pubmed_search")).not.toBeChecked();
  await expect(box(again, "arxiv_search")).toBeChecked();

  const offered = await offeredNow(page);
  expect(offered).not.toContain("pubmed_search");
  expect(offered).toContain("arxiv_search");
});

test("every tool is turned off, or on, with one button, and a conversation is offered what is on", async ({ page }) => {
  const dialog = await openSettings(page, "Tools");

  await dialog.getByRole("button", { name: "Turn all off" }).click();
  await expect(dialog.getByTestId("tools-count")).toHaveText("None are on");
  await expect(dialog.getByRole("checkbox", { checked: true })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Turn all off" })).toHaveAttribute("aria-disabled", "true");
  await expect.poll(async () => (await disabled(page)).length).toBe(17);

  await page.reload();
  expect(await offeredNow(page)).not.toContain("pubmed_search");

  const again = await openSettings(page, "Tools");
  await again.getByRole("button", { name: "Turn all on" }).click();
  await expect(again.getByTestId("tools-count")).toHaveText("All 17 are on");
  await expect.poll(() => disabled(page)).toEqual([]);
});

test("a tool shows as it is ticked while the server has yet to answer, and two in a row are both kept, with the focus staying", async ({ page }) => {
  const dialog = await openSettings(page, "Tools");
  let release: () => void = () => undefined;
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/tools", async (route) => {
    if (route.request().method() === "PUT") await held;
    await route.continue();
  });

  await box(dialog, "pubmed_search").focus();
  await page.keyboard.press("Space");
  await box(dialog, "arxiv_search").focus();
  await page.keyboard.press("Space");

  // Neither has been kept, and both show as chosen
  await expect(box(dialog, "pubmed_search")).not.toBeChecked();
  await expect(box(dialog, "arxiv_search")).not.toBeChecked();
  await expect(dialog.getByTestId("tools-count")).toHaveText("15 of 17 are on");
  expect(await disabled(page)).toEqual([]);

  release();

  await expect.poll(async () => (await disabled(page)).sort()).toEqual(["arxiv_search", "pubmed_search"]);
  await expect(dialog.getByTestId("tools-count")).toHaveText("15 of 17 are on");
  await expect(box(dialog, "arxiv_search")).toBeFocused();
  await page.unroute("**/api/tools");
});

test("say why the server refuses, and leave the tool as it was", async ({ page }) => {
  const dialog = await openSettings(page, "Tools");
  await page.route("**/api/tools", (route) =>
    route.request().method() === "PUT"
      ? route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "invalid", message: "That tool is not one the library has" } }),
        })
      : route.continue(),
  );

  await box(dialog, "pubmed_search").click();

  await expect(dialog.getByRole("alert")).toHaveText("That tool is not one the library has");
  await expect(box(dialog, "pubmed_search")).toBeChecked();
  await expect(dialog.getByTestId("tools-count")).toHaveText("All 17 are on");

  await page.unroute("**/api/tools");
  await box(dialog, "pubmed_search").click();
  await expect(dialog.getByTestId("tools-count")).toHaveText("16 of 17 are on");
  await expect(dialog.getByRole("alert")).toHaveCount(0);
});
