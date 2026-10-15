import type { Page } from "@playwright/test";
import { answered, askWhereCodeRuns, expect, test } from "./fixtures";

const calls = (page: Page) => page.getByTestId("call");

// Opens a conversation made with what it is given, titled, since the conversations of all the tests are listed on the side
async function openChat(page: Page, data: Record<string, unknown>): Promise<void> {
  const made = await page.request.post("/api/chats", { data });
  expect(made.status()).toBe(201);
  await page.goto(`/chat?id=${(await made.json()).id}`);
  await expect(page.getByRole("button", { name: "Attach files" })).toBeEnabled();
}

async function say(page: Page, message: string): Promise<void> {
  await page.getByRole("textbox", { name: "Message" }).fill(message);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByTestId("user-message")).toContainText(message);
}

test.describe("the tools the lead is given", () => {
  test("the lead looks at the files that were attached with its own tools, and each call says what it did", async ({ page }) => {
    await openChat(page, { title: "Tools: the lead looks at attached files" });
    await page.getByTestId("file-input").setInputFiles({
      name: "counts.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("gene,count\nTP53,5\nBRCA1,7\n"),
    });
    await expect(page.getByTestId("attachment").first()).toHaveAttribute("data-status", "ready");

    await say(page, "tool:files please");
    await answered(page, "That is done: 2 steps ran.", 30_000);

    await expect(calls(page)).toHaveCount(2);
    const [listing, inspecting] = [calls(page).nth(0), calls(page).nth(1)];
    await expect(listing).toHaveAttribute("data-call", "data_files");
    await expect(listing).toContainText("Listed the attached files");
    await expect(inspecting).toHaveAttribute("data-call", "inspect_data_file");
    await expect(inspecting).toContainText("Inspected a data file");
    await expect(inspecting).toContainText("uploads/counts.csv");

    await listing.locator("summary").click();
    await expect(listing).toContainText("uploads/counts.csv (26 bytes)");
    await inspecting.locator("summary").click();
    await expect(inspecting).toContainText("counts.csv: 2 rows, 2 columns");
    await expect(inspecting).toContainText("gene [text]");
  });

  test("a conversation is offered all of them to begin with, except the one that needs code where there is none", async ({ page }) => {
    await openChat(page, { title: "Tools: all are offered" });
    await say(page, "tool:offered");
    await answered(page, "Offered:");

    const offered = page.getByTestId("lead-message").last();
    for (const name of ["pubmed_search", "uniprot_lookup", "chembl_activities", "data_files", "inspect_data_file"]) {
      await expect(offered).toContainText(new RegExp(`\\b${name}\\b`));
    }
    await expect(offered).not.toContainText("fetch_structure_file");

    await askWhereCodeRuns(page, "tool:offered where there is code");
    await answered(page, "Offered:");
    await expect(page.getByTestId("lead-message").last()).toContainText("fetch_structure_file");
  });

  test("a conversation made with some of them is offered those, and none of the others", async ({ page }) => {
    await openChat(page, { title: "Tools: only some are offered", tools: ["data_files"] });
    await say(page, "tool:offered");
    await answered(page, "Offered:");

    const offered = page.getByTestId("lead-message").last();
    await expect(offered).toContainText(/\bdata_files\b/);
    await expect(offered).not.toContainText("pubmed_search");
    await expect(offered).not.toContainText("inspect_data_file");
  });
});
