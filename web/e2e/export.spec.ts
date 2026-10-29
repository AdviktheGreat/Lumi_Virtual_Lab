import { readFile } from "node:fs/promises";
import type { Download, Page } from "@playwright/test";
import { answered, ask, askWhereCodeRuns, expect, test } from "./fixtures";

const toggle = (page: Page) => page.getByTestId("export-toggle");
// What the page says went wrong. It is found by its markup and not by its role, since the page outside an open menu, and while
// the menu is closing, is hidden from roles, which would make a check that it is not there pass whether it is or not. The
// announcer Next puts on the page, which is an alert with nothing in it, is not what is looked for.
const alert = (page: Page) => page.locator('[role="alert"]').filter({ hasText: /\S/ });
const htmlExport = /\/api\/chats\/[^/]+\/export\?format=html$/;

// Opens the menu and chooses the format. The menu is waited for to be gone first if it was open, since one that is opened
// while the last is still closing is closed by it, which is something no one clicks fast enough to do.
async function saveAs(page: Page, format: "html" | "pdf" | "ipynb"): Promise<Download> {
  await expect(page.getByRole("menu")).toHaveCount(0);
  const saved = page.waitForEvent("download");
  await toggle(page).click();
  await page.getByTestId(`export-${format}`).click();

  return saved;
}

async function contentOf(download: Download): Promise<string> {
  const path = await download.path();

  return readFile(path, "utf-8");
}

test.describe("saving a conversation as a document", () => {
  test("there is nothing to save in a conversation with nothing in it, and something once it has begun", async ({ page }) => {
    const made = await page.request.post("/api/chats", { data: { title: "Save: nothing said yet" } });
    expect(made.status()).toBe(201);
    await page.goto(`/chat?id=${(await made.json()).id}`);

    await expect(toggle(page)).toBeDisabled();
    await expect(toggle(page)).toHaveAttribute("title", "There is nothing to save yet");

    await page.getByRole("textbox", { name: "Message" }).fill("Now there is something");
    await page.getByRole("button", { name: "Send" }).click();
    await answered(page, "You asked: Now there is something");

    await expect(toggle(page)).toBeEnabled();
  });

  test("a page is saved with what was asked and answered, under the name of the conversation, and the conversation stays open", async ({
    page,
  }) => {
    const question = "Which nanobody binds TP53?";
    const id = await ask(page, question);
    await answered(page, `You asked: ${question}`);

    const download = await saveAs(page, "html");

    expect(download.suggestedFilename()).toBe("Which nanobody binds TP53.html");
    const saved = await contentOf(download);
    expect(saved).toContain("<!DOCTYPE html>");
    expect(saved).toContain(question);
    expect(saved).toContain(`You asked: ${question}`);
    await expect(page).toHaveURL(new RegExp(`/chat\\?id=${id}$`));
    await expect(page.getByTestId("user-message")).toHaveText(question);
    await expect(alert(page)).toHaveCount(0);
    await expect(toggle(page)).toHaveText("Save");
    await expect(toggle(page)).toHaveAttribute("aria-busy", "false");
  });

  test("a PDF is saved as one", async ({ page }) => {
    await ask(page, "Save as a PDF please");
    await answered(page, "You asked: Save as a PDF please");

    const download = await saveAs(page, "pdf");

    expect(download.suggestedFilename()).toBe("Save as a PDF please.pdf");
    const saved = await contentOf(download);
    expect(saved.startsWith("%PDF-1.7")).toBe(true);
    expect(saved).toContain("You asked: Save as a PDF please");
  });

  test("a notebook is saved with the code that ran and the figure it drew", async ({ page }) => {
    await askWhereCodeRuns(page, "code:plot save the notebook");
    await answered(page, "That is done: 1 step ran.", 30_000);

    const download = await saveAs(page, "ipynb");

    expect(download.suggestedFilename()).toBe("code-plot save the notebook.ipynb");
    const notebook = JSON.parse(await contentOf(download));
    expect(notebook.nbformat).toBe(4);
    const code = notebook.cells.filter((cell: { cell_type: string }) => cell.cell_type === "code");
    expect(code).toHaveLength(1);
    expect(code[0].outputs.some((output: { output_type: string }) => output.output_type === "display_data")).toBe(true);
    expect(JSON.stringify(notebook.cells)).toContain("code:plot save the notebook");
  });

  test("the code that ran, what it printed, and the figure it drew are in the page", async ({ page }) => {
    await askWhereCodeRuns(page, "code:plot save the figure");
    await answered(page, "That is done: 1 step ran.", 30_000);

    const saved = await contentOf(await saveAs(page, "html"));

    expect(saved).toContain("class Figure");
    expect(saved).toContain("drawn");
    expect(saved).toContain("data:image/png;base64,");
    expect(saved).toContain("results.csv");
  });

  test("what a team said in its session is in the page", async ({ page }) => {
    await ask(page, "lab:team please, for the page");
    await answered(page, "That is done: 1 step ran.", 30_000);

    const saved = await contentOf(await saveAs(page, "html"));

    expect(saved).toContain("Design a nanobody against TP53.");
    expect(saved).toContain("As the Immunologist, I would target the conserved DNA-binding epitope.");
    expect(saved).toContain("As the Scientific Critic, I ask what shows that the epitope is exposed.");
  });

  test("a PDF that cannot be made is told of in words, not saved as a file, and a page can still be saved", async ({ page }) => {
    await ask(page, "pdf:unavailable on this machine");
    await answered(page, "You asked: pdf:unavailable on this machine");
    let saved = 0;
    page.on("download", () => (saved += 1));

    await toggle(page).click();
    await page.getByTestId("export-pdf").click();

    await expect(alert(page)).toContainText("A PDF cannot be made on this machine");
    await expect(alert(page)).toContainText("print it to a PDF from the browser");
    await expect(toggle(page)).toHaveText("Save");
    expect(saved).toBe(0);

    // What was said stays until something is saved, which is when it is out of date
    const download = await saveAs(page, "html");
    expect(download.suggestedFilename()).toBe("pdf-unavailable on this machine.html");
    await expect(alert(page)).toHaveCount(0);
  });

  test("a server that cannot be reached is told of, and nothing is saved", async ({ page }) => {
    await ask(page, "The server will be gone");
    await answered(page, "You asked: The server will be gone");
    let saved = 0;
    page.on("download", () => (saved += 1));
    await page.route(htmlExport, (route) => route.abort());

    await toggle(page).click();
    await page.getByTestId("export-html").click();

    await expect(alert(page)).toContainText("The server cannot be reached");
    await expect(toggle(page)).toHaveText("Save");
    expect(saved).toBe(0);
  });

  test("while it is being made, it says so and takes no second request, and it is saved when it is ready", async ({ page }) => {
    await ask(page, "Take your time over this one");
    await answered(page, "You asked: Take your time over this one");
    let requests = 0;
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route(htmlExport, async (route) => {
      requests += 1;
      await held;
      await route.continue();
    });

    const saved = page.waitForEvent("download");
    await toggle(page).click();
    await page.getByTestId("export-html").click();

    await expect(toggle(page)).toHaveText("Saving…");
    await expect(toggle(page)).toHaveAttribute("aria-busy", "true");
    // The menu the choice was made in is gone before the button is pressed again, as it is for anyone, since a press
    // while it is still going is not taken as one to open it
    await expect(page.getByTestId("export-html")).toBeHidden();
    await toggle(page).click();
    await expect(page.getByTestId("export-html")).toHaveAttribute("data-disabled", "");
    await expect(page.getByTestId("export-pdf")).toHaveAttribute("data-disabled", "");
    await page.keyboard.press("Escape");

    release();
    expect((await saved).suggestedFilename()).toBe("Take your time over this one.html");
    await expect(toggle(page)).toHaveText("Save");
    expect(requests).toBe(1);
  });

  test("a document that is still being made when the conversation is left is not saved", async ({ page }) => {
    await ask(page, "I will leave before it is ready");
    await answered(page, "You asked: I will leave before it is ready");
    let saved = 0;
    page.on("download", () => (saved += 1));
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => (release = resolve));
    let reachServer: () => void = () => undefined;
    const reached = new Promise<void>((resolve) => (reachServer = resolve));
    await page.route(htmlExport, async (route) => {
      reachServer();
      await held;
      // The page has given up the request by then, which the browser says by failing this
      await route.continue().catch(() => undefined);
    });

    await toggle(page).click();
    await page.getByTestId("export-html").click();
    await reached;
    await page.getByRole("link", { name: "New chat", exact: true }).click();
    await expect(page).not.toHaveURL(/chat/);
    release();
    await page.waitForTimeout(1_000);

    expect(saved).toBe(0);
  });

  test("it is there for a conversation that is still going, as far as it has got", async ({ page }) => {
    await ask(page, "slow: write a long reply");
    await expect(page.getByTestId("chat-state")).toHaveText("Working");

    const saved = await contentOf(await saveAs(page, "html"));

    expect(saved).toContain("slow: write a long reply");
    await answered(page, "word250", 60_000);
  });
});
